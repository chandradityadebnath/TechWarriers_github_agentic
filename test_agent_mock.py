"""
Mock test harness for agent.py.

Simulates a sequence of Gemini responses WITHOUT hitting the real API, so we
can verify the agent loop's control flow (tool dispatch, adaptation
detection, finish_case handling) is correct before spending real API quota.

Run this any time you change agent.py's loop logic to sanity-check it fast.
"""

import db_setup
import agent


class FakeCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class FakeCandidate:
    def __init__(self, content_marker):
        self.content = content_marker  # not inspected by our fake client, just passed along


class FakeResponse:
    def __init__(self, name=None, args=None, text=""):
        self.function_calls = [FakeCall(name, args)] if name else []
        self.text = text
        self.candidates = [FakeCandidate(f"<model turn: {name}>")]


class FakeModels:
    """Stands in for client.models -- pops one scripted response per call."""
    def __init__(self, scripted_responses):
        self._queue = list(scripted_responses)
        self.calls_made = 0

    def generate_content(self, model, contents, config):
        self.calls_made += 1
        if not self._queue:
            raise AssertionError("FakeModels ran out of scripted responses -- loop made too many calls")
        return self._queue.pop(0)


class FakeClient:
    def __init__(self, scripted_responses):
        self.models = FakeModels(scripted_responses)


def test_out_of_stock_adaptation_flow():
    """
    Scripts the exact decision sequence a well-behaved agent SHOULD make for
    ORD1001 (damaged, but replacement SKU is out of stock):
      get_order -> get_policy -> check_inventory -> execute_replacement (fails)
      -> execute_refund (adapts, succeeds) -> verify_order_state -> finish_case
    """
    db_setup.create_database()  # fresh DB each test run

    scripted = [
        FakeResponse(name="get_order", args={"order_id": "ORD1001"}, text="Checking the order first."),
        FakeResponse(name="get_policy", args={"issue_type": "damaged"}, text="Checking allowed actions."),
        FakeResponse(name="check_inventory", args={"sku": "SKU-B22"}, text="Checking stock before replacing."),
        FakeResponse(name="execute_replacement", args={"order_id": "ORD1001"}, text="Attempting replacement."),
        FakeResponse(name="execute_refund", args={"order_id": "ORD1001"}, text="Replacement blocked, falling back to refund."),
        FakeResponse(name="verify_order_state", args={"order_id": "ORD1001", "expected_status": "refunded"}, text="Verifying."),
        FakeResponse(name="finish_case", args={
            "status": "resolved",
            "resolution": "Refund issued for damaged headphones; replacement was out of stock."
        }, text="Done."),
    ]

    fake_client = FakeClient(scripted)

    case = agent.run_case(
        order_id="ORD1001",
        customer_complaint="My Bluetooth Headphones arrived damaged.",
        case_id="CASE_MOCK_001",
        client=fake_client,
    )

    # --- Assertions ---
    assert case.status == "resolved", f"Expected resolved, got {case.status}"
    assert len(case.adaptations) == 1, f"Expected exactly 1 adaptation, got {len(case.adaptations)}"
    adapt = case.adaptations[0]
    assert adapt["blocked_action"] == "execute_replacement"
    assert adapt["new_action"] == "execute_refund"
    assert fake_client.models.calls_made == 7, f"Expected 7 model calls, got {fake_client.models.calls_made}"

    print("PASS: out-of-stock adaptation flow works end-to-end.")
    case.print_trace()


def test_escalation_when_all_actions_blocked():
    """
    A harder case: everything the agent tries fails, so it must escalate
    rather than loop forever or falsely claim success.
    """
    db_setup.create_database()

    scripted = [
        FakeResponse(name="get_order", args={"order_id": "ORD1002"}),
        FakeResponse(name="get_policy", args={"issue_type": "wrong_item"}),
        FakeResponse(name="execute_replacement", args={"order_id": "ORD1002"}),
        FakeResponse(name="finish_case", args={
            "status": "escalated",
            "resolution": "Unable to safely resolve automatically; escalating to human agent."
        }),
    ]
    fake_client = FakeClient(scripted)

    case = agent.run_case(
        order_id="ORD1002",
        customer_complaint="Wrong item was shipped to me.",
        case_id="CASE_MOCK_002",
        client=fake_client,
    )

    assert case.status == "escalated", f"Expected escalated, got {case.status}"
    print("PASS: escalation path works.")
    case.print_trace()


def test_double_adaptation_cascading_failures():
    """
    The showpiece scenario (ORD1004): replacement is PERMANENTLY blocked
    (out of stock) -> agent SWITCHES to refund -> refund hits a TRANSIENT
    gateway timeout -> agent RETRIES the same refund -> succeeds.
    Two distinct adaptation types in a single case.
    """
    db_setup.create_database()

    scripted = [
        FakeResponse(name="get_order", args={"order_id": "ORD1004"}),
        FakeResponse(name="get_policy", args={"issue_type": "damaged"}),
        FakeResponse(name="check_return_window", args={"order_id": "ORD1004"}),
        FakeResponse(name="check_inventory", args={"sku": "SKU-D44"}),
        FakeResponse(name="execute_replacement", args={"order_id": "ORD1004"}),   # fails: out_of_stock
        FakeResponse(name="execute_refund", args={"order_id": "ORD1004"}),         # fails: payment_gateway_timeout
        FakeResponse(name="execute_refund", args={"order_id": "ORD1004"}),         # retry -> succeeds
        FakeResponse(name="verify_order_state", args={"order_id": "ORD1004", "expected_status": "refunded"}),
        FakeResponse(name="finish_case", args={
            "status": "resolved",
            "resolution": "Refund issued after replacement was unavailable and a transient payment error was retried."
        }),
    ]
    fake_client = FakeClient(scripted)

    case = agent.run_case(
        order_id="ORD1004",
        customer_complaint="My Smartwatch arrived damaged.",
        case_id="CASE_MOCK_003",
        client=fake_client,
    )

    assert case.status == "resolved"
    assert len(case.adaptations) == 2, f"Expected 2 adaptations, got {len(case.adaptations)}"
    assert case.adaptations[0]["adaptation_type"] == "switch"
    assert case.adaptations[0]["blocked_action"] == "execute_replacement"
    assert case.adaptations[1]["adaptation_type"] == "retry"
    assert case.adaptations[1]["blocked_action"] == "execute_refund"

    print("PASS: double-adaptation cascading failure flow works.")
    case.print_trace()


def test_escalation_due_to_expired_policy_window():
    """
    ORD1005 is far outside its 30-day policy window. The agent should
    recognize this via check_return_window and escalate immediately WITHOUT
    ever attempting a refund/replacement/cancellation.
    """
    db_setup.create_database()

    scripted = [
        FakeResponse(name="get_order", args={"order_id": "ORD1005"}),
        FakeResponse(name="get_policy", args={"issue_type": "damaged"}),
        FakeResponse(name="check_return_window", args={"order_id": "ORD1005"}),
        FakeResponse(name="finish_case", args={
            "status": "escalated",
            "resolution": "Policy window has expired (134+ days since order); cannot auto-resolve."
        }),
    ]
    fake_client = FakeClient(scripted)

    case = agent.run_case(
        order_id="ORD1005",
        customer_complaint="This USB-C charger was damaged.",
        case_id="CASE_MOCK_004",
        client=fake_client,
    )

    assert case.status == "escalated"
    assert not case.has_tried("execute_refund")
    assert not case.has_tried("execute_replacement")
    assert not case.has_tried("execute_cancellation")

    print("PASS: expired-policy-window escalation works without attempting any action.")
    case.print_trace()


if __name__ == "__main__":
    test_out_of_stock_adaptation_flow()
    test_escalation_when_all_actions_blocked()
    test_double_adaptation_cascading_failures()
    test_escalation_due_to_expired_policy_window()
    print("\nAll mock tests passed.")
