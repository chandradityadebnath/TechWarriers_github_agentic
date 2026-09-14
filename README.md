# Autonomous Customer Resolution Agent
**Tech Zephyr 4.0 · Track 3: Smart Automation · Problem Statement 5**

**Team:** Tech Warriers (solo)

**Demo video:** https://drive.google.com/file/d/1eYOOsjpSRiZUDCEoyj55Z-IfxCutYgS4/view?usp=sharing

An agent that actually *resolves* a customer's issue across simulated
enterprise systems (customer DB, orders, inventory, policy) — not just
classifies the ticket or drafts a reply. It retrieves evidence, executes a
real state-changing action, verifies the result, and **replans when an
action is blocked**, escalating only when nothing safe will work.

## Quick start

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
export GEMINI_API_KEY='your-key-here'

python3 db_setup.py          # (re)creates the database with seed data -- ALWAYS run this before a fresh demo
python3 test_agent_mock.py   # sanity-checks the agent loop with zero API calls
python3 agent.py             # runs one case live against the real Gemini API
streamlit run app.py         # the demo UI
```

> **Before every demo run:** run `python3 db_setup.py` (or click "Reset database" in the sidebar) first. The database is stateful — once an order is refunded/replaced, running the same case again will behave differently, since that action is no longer available. Always demo from a clean seed.

## Approach :

We treat customer resolution as a closed loop, not a single generation
step: the agent retrieves evidence from four simulated systems (customer,
order, inventory, policy), reasons about which action the *policy actually
permits*, executes a real state-changing action, and independently
re-verifies the result rather than trusting its own action call. When an
action is blocked, the loop doesn't stop — it distinguishes a **permanent**
block (out of stock → switch to a different allowed action) from a
**transient** one (a gateway timeout → retry the same action), which
mirrors how a real support system actually behaves.

## Final solution :

A single Gemini-powered agent (manual function calling, not the SDK's
auto-loop) making one tool call per turn against 8 tools backed by a real
SQLite database. Every step, failure, and adaptation is logged to a
persistent per-case JSON state file. A Streamlit UI streams this reasoning
live and computes a rubric-coverage checklist from the actual run, rather
than from a canned script.

## Architecture :

| File | Role |
|---|---|
| `db_setup.py` | SQLite schema + seed data: customers, orders, inventory, policies, and injected faults |
| `tools.py` | The agent's tools: retrieval (`get_order`, `get_policy`, `check_inventory`, `check_return_window`) and state-changing actions (`execute_refund`, `execute_replacement`, `execute_cancellation`, `verify_order_state`). Every call is logged. |
| `state.py` | `CaseState`: persistent task state — goal, step history, attempted actions, and explicitly logged adaptation events. Saved to JSON per case. |
| `agent.py` | The decision loop. Uses Gemini function calling (manual, not automatic) so every tool call, failure, and replan is fully inspectable. |
| `test_agent_mock.py` | Scripts Gemini's responses to verify the loop's control flow (dispatch, adaptation detection, escalation) without spending API calls. |
| `app.py` | Streamlit demo UI — streams the reasoning live and shows a rubric-coverage checklist computed from the actual run. |

## Demo scenarios (pick these live during judging)

| Order | Scenario | What it demonstrates |
|---|---|---|
| `ORD1001` | Damaged headphones, replacement out of stock | Single **switch** adaptation (replacement → refund) |
| `ORD1002` | Wrong item shipped, replacement in stock | Clean success path, no adaptation needed — good contrast case |
| `ORD1004` | Damaged smartwatch, replacement out of stock **and** a transient payment error | **Two** adaptation types in one case: switch (replacement → refund), then retry (same refund succeeds on 2nd attempt) |
| `ORD1005` | Damaged charger, 134 days old | Correctly **escalates** without ever touching an action — policy window expired |

`ORD1004` is the strongest single demo: it hits almost every rubric line in one run.

## How this maps to the rubric :

- **Agentic workflow & autonomy (25%)** — the model decides every tool call itself; nothing is hardcoded per-scenario.
- **Tool/environment interaction (15%)** — 8 distinct tools, all backed by a real SQLite DB with actual state mutation.
- **Adaptation & failure recovery (15%)** — two distinct adaptation types (switch vs. retry) are detected, logged, and displayed.
- **Technical implementation (15%)** — manual function calling (not the SDK's auto-loop) for full control and inspectability; persistent JSON state per case.
- **Evaluation, verification & robustness (10%)** — `verify_order_state` independently re-reads the DB rather than trusting the action call's own claim; `check_return_window` does deterministic date math instead of trusting the LLM's arithmetic.

## Challenges :

- **Database is stateful across runs.** Because actions actually mutate the DB, running the same order twice behaves differently the second time (e.g. a refund can't be issued again). We solved this by making the reset step explicit and prominent rather than automatic, so a demo can't silently show stale results.
- **LLM decision ordering isn't fully deterministic.** The mock test suite (`test_agent_mock.py`) verifies the *loop's* control flow is correct against a scripted sequence, but the live model may take a slightly different, still-valid path than the one shown in our tests.
- **Distinguishing transient vs. permanent failures.** Early versions treated every failed action the same way (always switch). We split this into two adaptation types so the agent retries recoverable errors instead of abandoning a perfectly valid action.

## Conclusion :

The system demonstrates genuine closed-loop agentic behavior against the
PS5 requirements: goal-driven execution, real tool/environment interaction,
persistent state, observation-driven replanning across two distinct failure
types, and independent verification before declaring success. It escalates
rather than guessing when no safe action exists, which we consider more
important for a customer-facing system than forcing a resolution.

