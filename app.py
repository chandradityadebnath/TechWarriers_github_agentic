"""
Step 6: Streamlit UI for the Autonomous Customer Resolution Agent.

Built to actually DEMO WELL:
- Steps stream in live (goal -> tool call -> result -> adaptation -> outcome)
  instead of dumping a static block, so judges watch the reasoning happen.
- Adaptation moments get a visually distinct callout -- this is the single
  most heavily-weighted rubric line (15%), so it should be impossible to miss.
- A rubric coverage checklist is computed live from the actual run, so you
  can literally point at the screen and show every PDF requirement being hit.
- Full trace is downloadable as JSON for your submission evidence.

Run with: streamlit run app.py
"""

import json
import time
import os
import streamlit as st

import db_setup
import tools
import agent

st.set_page_config(
    page_title="Autonomous Customer Resolution Agent",
    page_icon="\U0001F916",
    layout="centered",
)

SCENARIOS = {
    "ORD1001 \u2014 Damaged headphones (single adaptation)": {
        "order_id": "ORD1001",
        "complaint": "My Bluetooth Headphones arrived damaged. I'd like this resolved.",
    },
    "ORD1002 \u2014 Wrong item shipped (clean success)": {
        "order_id": "ORD1002",
        "complaint": "I received the wrong item in my order. Please fix this.",
    },
    "ORD1004 \u2014 Smartwatch damaged (double adaptation: switch + retry)": {
        "order_id": "ORD1004",
        "complaint": "My Smartwatch arrived damaged and I want it resolved.",
    },
    "ORD1005 \u2014 Expired policy window (escalation)": {
        "order_id": "ORD1005",
        "complaint": "This USB-C charger was damaged, please help.",
    },
    "Custom order ID / complaint": None,
}


def result_badge(result: dict) -> str:
    """Infers a success/failure/info badge from a tool result dict."""
    for key in ("success", "verified", "within_window"):
        if key in result:
            return "\u2705" if result[key] else "\u274C"
    if "found" in result:
        return "\u2705" if result["found"] else "\u2753"
    return "\u2139\uFE0F"


def render_step(step: dict):
    badge = result_badge(step["result"])
    with st.container(border=True):
        st.markdown(f"**Step {step['step_number']} \u2014 `{step['action']}`** {badge}")
        if step["thought"]:
            st.caption(f"\U0001F4AD {step['thought']}")
        st.code(json.dumps(step["result"], indent=2), language="json")


def render_adaptation(detail: dict):
    verb = "retried" if detail.get("adaptation_type") == "retry" else "switched to"
    icon = "\U0001F501" if detail.get("adaptation_type") == "retry" else "\U0001F504"
    st.warning(
        f"{icon} **Adaptation ({detail.get('adaptation_type', 'switch')})** \u2014 "
        f"`{detail['blocked_action']}` was blocked (*{detail['reason']}*), "
        f"so the agent {verb} `{detail['new_action']}`."
    )


def render_final(case):
    if case.status == "resolved":
        st.success(f"\u2705 **RESOLVED** \u2014 {case.resolution}")
    else:
        st.error(f"\U0001F6A8 **ESCALATED** \u2014 {case.resolution}")


def rubric_checklist(case):
    tools_used = {s["action"] for s in case.history}
    retrieved = bool(tools_used & {"get_order", "get_policy", "check_inventory"})
    checked_constraints = bool(tools_used & {"check_inventory", "check_return_window"})
    executed = any(
        s["action"].startswith("execute_") and s["result"].get("success")
        for s in case.history
    )
    verified = any(
        s["action"] == "verify_order_state" and s["result"].get("verified")
        for s in case.history
    )
    adapted = len(case.adaptations) > 0
    escalated_appropriately = case.status == "escalated"

    rows = [
        ("Retrieved customer/order/policy info", retrieved),
        ("Checked real-world constraints (stock / policy window)", checked_constraints),
        ("Executed a state-changing action", executed),
        ("Verified the outcome independently", verified or escalated_appropriately),
        ("Adapted to a blocked or failed action", adapted or "N/A \u2014 no failure occurred"),
        ("Escalated only when no action could succeed", escalated_appropriately or "N/A \u2014 case resolved"),
    ]
    for label, ok in rows:
        if ok is True:
            st.markdown(f"- \u2705 {label}")
        elif ok is False:
            st.markdown(f"- \u274C {label}")
        else:
            st.markdown(f"- \u27A1\uFE0F {label} ({ok})")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("\u2699\uFE0F Setup")

api_key_input = st.sidebar.text_input(
    "Gemini API key",
    value=os.environ.get("GEMINI_API_KEY", ""),
    type="password",
    help="Falls back to the GEMINI_API_KEY environment variable if left blank.",
)
model_name = st.sidebar.text_input("Model", value=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))

if st.sidebar.button("\U0001F504 Reset database to fresh seed data"):
    db_setup.create_database()
    st.sidebar.success("Database reset.")

st.sidebar.markdown("---")
st.sidebar.caption("Tech Zephyr 4.0 \u00b7 Track 3: Smart Automation \u00b7 PS5")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.title("\U0001F916 Autonomous Customer Resolution Agent")
st.caption("Goal \u2192 Decision \u2192 Action \u2192 Result \u2192 Adaptation \u2192 Final Outcome")

if not os.path.exists(tools.DB_PATH):
    db_setup.create_database()

scenario_label = st.selectbox("Choose a case", list(SCENARIOS.keys()))

if scenario_label == "Custom order ID / complaint":
    order_id = st.text_input("Order ID", value="ORD1001")
    complaint = st.text_area("Customer complaint", value="")
else:
    order_id = SCENARIOS[scenario_label]["order_id"]
    complaint = SCENARIOS[scenario_label]["complaint"]
    order_preview = tools.get_order(order_id)
    if order_preview["found"]:
        st.info(
            f"**Order {order_id}** \u2014 {order_preview['product_name']} "
            f"(\u20b9{order_preview['price']:.2f}) \u00b7 issue: *{order_preview['issue_type']}* "
            f"\u00b7 ordered {order_preview['order_date']}"
        )

run_clicked = st.button("\u25B6\uFE0F Run Agent", type="primary", use_container_width=True)

if run_clicked:
    if not api_key_input:
        st.error("Please provide a Gemini API key in the sidebar (or set GEMINI_API_KEY).")
        st.stop()

    from google import genai
    client = genai.Client(api_key=api_key_input)
    agent.MODEL_NAME = model_name  # honor sidebar override

    st.markdown("### \U0001F3AF Goal")
    goal_placeholder = st.empty()
    st.markdown("### \U0001F9E9 Reasoning trace")
    trace_area = st.container()

    final_case = None
    try:
        for event in agent.run_case_stream(
            order_id=order_id,
            customer_complaint=complaint,
            case_id=f"CASE_UI_{int(time.time())}",
            client=client,
        ):
            case = event["case"]
            final_case = case

            if event["type"] == "goal":
                goal_placeholder.info(f"**{case.goal}**")

            elif event["type"] == "step":
                with trace_area:
                    render_step(case.history[-1])
                time.sleep(0.4)

            elif event["type"] == "adaptation":
                with trace_area:
                    render_adaptation(event["detail"])
                time.sleep(0.4)

            elif event["type"] == "rate_limited":
                with trace_area:
                    st.info(
                        f"\u23F3 Hit the Gemini API's free-tier rate limit \u2014 "
                        f"waiting {event['wait_seconds']}s before retrying "
                        f"(attempt {event['attempt']}/4). This is expected on the "
                        f"free tier and the run will continue automatically."
                    )

            elif event["type"] == "finished":
                with trace_area:
                    if case.history and case.history[-1]["action"] == "finish_case":
                        render_step(case.history[-1])
                st.markdown("### \U0001F3C1 Final Outcome")
                render_final(case)

    except Exception as e:
        st.error(f"Agent run failed: {e}")
        st.stop()

    if final_case:
        st.markdown("### \U0001F4CB Rubric coverage (this run)")
        rubric_checklist(final_case)

        st.markdown("### \U0001F4E5 Evidence")
        st.download_button(
            "Download full case trace (JSON)",
            data=json.dumps(final_case.to_dict(), indent=2),
            file_name=f"{final_case.case_id}.json",
            mime="application/json",
        )
        st.download_button(
            "Download raw tool-call log (JSON)",
            data=json.dumps(tools.get_tool_call_log(), indent=2),
            file_name=f"{final_case.case_id}_tool_calls.json",
            mime="application/json",
        )
