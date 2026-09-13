"""
Step 4: The agent loop -- the decision-making brain of the system.

Uses Google's current Gemini SDK (google-genai, `from google import genai`)
with MANUAL function calling (not automatic) so we keep full control of the
loop for state tracking, adaptation logging, and building the demo trace
required by the PDF's "Goal -> Decision -> Action -> Intermediate Result ->
Adaptation -> Final Outcome" structure.

This is what turns Steps 1-3 (DB, tools, state) from a script into an
AGENT: the *model itself* decides which tool to call next based on what it
has observed so far, and must adapt when a tool call fails.
"""

import os
import re
import time
from google import genai
from google.genai import types

import tools
from state import CaseState

# The free Gemini tier's rate limit is easy to hit: a single case can need
# 7-9 model calls, and the free tier for gemini-2.5-flash is commonly just
# 5 requests/minute. Rather than crashing the whole case on a 429, we
# detect it and wait out Google's own suggested retry delay.
MAX_RATE_LIMIT_RETRIES = 4
DEFAULT_RETRY_WAIT_SECONDS = 65


def _is_rate_limit_error(message: str) -> bool:
    return "RESOURCE_EXHAUSTED" in message or "429" in message


def _extract_retry_delay(message: str) -> int:
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)", message)
    return int(match.group(1)) + 3 if match else DEFAULT_RETRY_WAIT_SECONDS

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_STEPS = 12

SYSTEM_INSTRUCTION = """
You are an autonomous customer resolution agent for an online retailer.

GOAL: given a customer's order and complaint, actually RESOLVE it using the
tools provided. Describing a resolution is not enough -- you must call the
tools that change system state.

Rules you must follow:
1. Always retrieve the order, then the policy for its issue_type, then
   check_return_window, and (if a replacement is possible) the inventory --
   all BEFORE taking any state-changing action.
2. If check_return_window reports within_window = false, NO automated
   action is permitted. Do not attempt refund/replacement/cancellation --
   call finish_case immediately with status 'escalated' and explain that
   the policy window has expired.
3. Only take an action that the policy's allowed_actions list permits.
4. Failures come in two kinds -- react differently to each:
   - PERMANENT (e.g. out_of_stock, order_already_refunded): do NOT retry
     the same action. Switch to a different ALLOWED action instead.
   - TRANSIENT (e.g. payment_gateway_timeout -- anything that sounds like a
     temporary system glitch): retry the EXACT SAME action once before
     giving up on it.
5. After a state-changing action finally succeeds, you MUST call
   verify_order_state to confirm it before finishing.
6. Call finish_case exactly once, at the very end, with a one-line
   resolution summary and status 'resolved' or 'escalated'.
7. Escalate only if no allowed action can succeed after the retries above.
8. Call exactly ONE tool per turn. Keep any reasoning brief.
"""

# --- Tool declarations (must mirror the functions in tools.py) ---

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_order",
        description="Retrieve order details including sku, status, and issue_type.",
        parameters_json_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="get_policy",
        description="Retrieve the resolution policy (allowed actions) for a given issue type.",
        parameters_json_schema={
            "type": "object",
            "properties": {"issue_type": {"type": "string"}},
            "required": ["issue_type"],
        },
    ),
    types.FunctionDeclaration(
        name="check_inventory",
        description="Check stock count for a SKU before attempting a replacement.",
        parameters_json_schema={
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    ),
    types.FunctionDeclaration(
        name="execute_refund",
        description="Issue a refund for an order. Fails if already refunded/cancelled.",
        parameters_json_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="execute_replacement",
        description="Ship a replacement for an order. Fails if the SKU is out of stock.",
        parameters_json_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="execute_cancellation",
        description="Cancel an order. Fails if already refunded/replaced/cancelled.",
        parameters_json_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="verify_order_state",
        description="Re-check the order's actual status against an expected status.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "expected_status": {"type": "string"},
            },
            "required": ["order_id", "expected_status"],
        },
    ),
    types.FunctionDeclaration(
        name="check_return_window",
        description="Deterministically check whether an order is still within its policy's return/claim window.",
        parameters_json_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="finish_case",
        description="Call this exactly once when the case is fully resolved or must be escalated.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["resolved", "escalated"]},
                "resolution": {"type": "string"},
            },
            "required": ["status", "resolution"],
        },
    ),
]

TOOL_FUNCTIONS = {
    "get_order": tools.get_order,
    "get_policy": tools.get_policy,
    "check_inventory": tools.check_inventory,
    "execute_refund": tools.execute_refund,
    "execute_replacement": tools.execute_replacement,
    "execute_cancellation": tools.execute_cancellation,
    "verify_order_state": tools.verify_order_state,
    "check_return_window": tools.check_return_window,
}

# Keys that indicate a tool call did NOT succeed
_FAILURE_KEYS = ("success", "found", "verified", "within_window")

# Reason strings that indicate a TRANSIENT failure (worth retrying the same
# action) as opposed to a PERMANENT one (must switch to a different action).
_TRANSIENT_REASON_HINTS = ("timeout", "transient", "gateway", "temporarily")


def _is_failure(result: dict) -> bool:
    for key in _FAILURE_KEYS:
        if key in result and result[key] is False:
            return True
    return False


def _is_transient(reason: str) -> bool:
    reason = (reason or "").lower()
    return any(hint in reason for hint in _TRANSIENT_REASON_HINTS)


def run_case_stream(order_id: str, customer_complaint: str, case_id: str, client=None):
    """
    Generator version of the agent loop: yields an event dict after every
    meaningful moment (goal set, tool call + result, adaptation, finish) so a
    UI (e.g. Streamlit) can render the reasoning live instead of waiting for
    the whole case to finish. `event["case"]` is always the same underlying
    CaseState object, fully up to date at the moment of the yield.

    Event types yielded: 'goal' | 'step' | 'adaptation' | 'finished'
    """
    if client is None:
        client = genai.Client()  # picks up GEMINI_API_KEY (or GOOGLE_API_KEY) from env

    order_preview = tools.get_order(order_id)
    case = CaseState(
        case_id=case_id,
        order_id=order_id,
        customer_id=order_preview.get("customer_id", "UNKNOWN"),
        goal=f"Resolve complaint for order {order_id}: {customer_complaint}",
    )
    yield {"type": "goal", "case": case}

    tool = types.Tool(function_declarations=TOOL_DECLARATIONS)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[tool],
    )

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(
                text=f"Order ID: {order_id}\nCustomer complaint: {customer_complaint}\n"
                     f"Resolve this case using the available tools."
            )],
        )
    ]

    pending_failure = None  # (failed_action_name, reason) -- used to detect adaptation

    for _ in range(MAX_STEPS):
        response = None
        for attempt in range(MAX_RATE_LIMIT_RETRIES):
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME, contents=contents, config=config,
                )
                break
            except Exception as e:
                msg = str(e)
                if not _is_rate_limit_error(msg) or attempt == MAX_RATE_LIMIT_RETRIES - 1:
                    raise
                wait_s = _extract_retry_delay(msg)
                yield {
                    "type": "rate_limited",
                    "case": case,
                    "wait_seconds": wait_s,
                    "attempt": attempt + 1,
                }
                time.sleep(wait_s)

        if not response.function_calls:
            # Model responded with plain text instead of a tool call -- nudge it back.
            contents.append(response.candidates[0].content)
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text="You must call one of the provided tools, including finish_case when done."
                )],
            ))
            continue

        call = response.function_calls[0]
        name = call.name
        args = dict(call.args) if call.args else {}
        thought = (response.text or "").strip()

        if name == "finish_case":
            status = args.get("status", "resolved")
            resolution = args.get("resolution", "No resolution summary provided.")
            case.add_step(thought or "Concluding the case.", name, args, {"status": status})
            if status == "escalated":
                case.mark_escalated(resolution)
            else:
                case.mark_resolved(resolution)
            yield {"type": "finished", "case": case}
            return

        func = TOOL_FUNCTIONS.get(name)
        result = func(**args) if func else {"error": f"unknown_tool_{name}"}

        # --- Adaptation detection ---
        # A pending failure exists from a previous action. Decide whether
        # this new call resolves it, and if so, HOW (retry vs switch).
        if pending_failure and name.startswith("execute_"):
            prev_action, prev_reason = pending_failure
            if name == prev_action and not _is_failure(result):
                case.record_adaptation(prev_action, prev_reason, name, adaptation_type="retry")
                pending_failure = None
                yield {"type": "adaptation", "case": case, "detail": case.adaptations[-1]}
            elif name != prev_action:
                case.record_adaptation(prev_action, prev_reason, name, adaptation_type="switch")
                pending_failure = None
                yield {"type": "adaptation", "case": case, "detail": case.adaptations[-1]}

        # Track any NEW failure from this call for the next iteration to react to.
        if _is_failure(result) and name.startswith("execute_"):
            pending_failure = (name, result.get("reason", "unknown_failure"))

        case.add_step(thought or f"Calling {name}.", name, args, result)
        yield {"type": "step", "case": case}

        # Feed the function call + its result back into the conversation
        contents.append(response.candidates[0].content)
        function_response_part = types.Part.from_function_response(name=name, response=result)
        contents.append(types.Content(role="tool", parts=[function_response_part]))

    else:
        # Loop exhausted without the model calling finish_case
        case.mark_escalated("Max reasoning steps reached without a confirmed resolution.")
        yield {"type": "finished", "case": case}


def run_case(order_id: str, customer_complaint: str, case_id: str, client=None) -> CaseState:
    """Convenience wrapper: drains run_case_stream and returns the final CaseState."""
    final_case = None
    for event in run_case_stream(order_id, customer_complaint, case_id, client=client):
        final_case = event["case"]
    return final_case


if __name__ == "__main__":
    result_case = run_case(
        order_id="ORD1001",
        customer_complaint="My Bluetooth Headphones arrived damaged. I'd like it resolved.",
        case_id="CASE_LIVE_001",
    )
    result_case.print_trace()
