# Demo Video Script — Tech Warriers
## Autonomous Customer Resolution Agent · Tech Zephyr 4.0 · PS5

Read this in your own words, don't memorize it word-for-word — sounding
natural matters more than sounding exact. Practice once without recording
first. Scenario used throughout: **ORD1004**.

---

### 0:00–0:20 — INTRO
**[ON SCREEN: Streamlit app open, before clicking Run]**

> "Hi, I'm Chandraditya from team Tech Warriers, and this is my submission
> for Track 3, Problem Statement 5 — the Autonomous Customer Resolution
> Agent. Unlike a chatbot that just replies to a ticket, this agent actually
> goes and resolves the issue itself — it retrieves real data, takes a real
> action, checks that the action worked, and changes its plan when
> something blocks it. Let me show you."

---

### 0:20–0:40 — GOAL
**[ON SCREEN: Select "ORD1004 — Smartwatch damaged" from the dropdown, click Run Agent]**

> "I'll run a case where a customer's Smartwatch — order ORD1004 — arrived
> damaged. The agent's goal is simple to state but not simple to execute:
> resolve this complaint, using only the tools it's given. I'm not telling
> it what to do next — it decides that itself."

---

### 0:40–1:15 — DECISION
**[ON SCREEN: Let the steps stream in — get_order, get_policy, check_return_window, check_inventory]**

> "Watch what it does before taking any action. First it pulls the order
> details. Then it checks the policy for a 'damaged' complaint — refund or
> replacement are both allowed, but only within a 30-day window, so it
> checks that next. Then it checks stock, since replacement obviously needs
> inventory. None of this is hardcoded per case — the model is deciding
> this sequence on its own based on what it's already learned."

---

### 1:15–1:35 — ACTION + FAILURE
**[ON SCREEN: execute_replacement step appears, result shows success: false, out_of_stock]**

> "Now it tries to replace the item — and this fails. The Smartwatch is out
> of stock. This is the failure moment the rubric asks for: a real blocked
> action, not a scripted one."

---

### 1:35–2:15 — ADAPTATION (the main event)
**[ON SCREEN: orange adaptation box appears — "switch": replacement → refund. Then execute_refund fails with payment_gateway_timeout. Then a second orange box appears — "retry": execute_refund → execute_refund]**

> "Here's the part I actually want you to pay attention to. The agent
> doesn't get stuck — it switches to a refund instead, since that's also
> allowed by policy. But then the refund itself fails too, this time with a
> simulated payment gateway timeout. And here's the key distinction: this
> failure is different in kind — it's temporary, not permanent — so instead
> of giving up on refunds entirely, the agent retries the exact same
> action. And it succeeds. So in one run, you're seeing two completely
> different adaptation strategies: switching approaches when something's
> truly blocked, and retrying when something's just flaky."

---

### 2:15–2:40 — VERIFICATION + OUTCOME
**[ON SCREEN: verify_order_state step, then green "RESOLVED" banner, then rubric checklist]**

> "Before declaring success, it independently re-checks the order status
> in the database rather than just trusting its own action call — that's
> the verification step. And here's the final outcome: resolved, with a
> one-line summary the agent wrote itself. Below that, I've got a live
> checklist mapping this exact run back to the rubric criteria."

---

### 2:40–3:00 — CLOSE
**[ON SCREEN: back on the resolved screen, or your face if webcam is on]**

> "So that's Goal, Decision, Action, a real Intermediate failure,
> Adaptation — twice, in two different ways — and a verified Final
> Outcome, all in one autonomous run. With more time I'd add a second live
> agent for fraud-risk checks on high-value refunds. Thanks for watching —
> this has been Tech Warriors' submission for Tech Zephyr 4.0."

---

## Backup line if something goes wrong on camera
If the agent does something unexpected mid-recording, don't panic or
restart — just narrate it honestly:
> "Interesting — it's trying a different order than I expected here. That's
> actually a good example of the model reasoning independently rather than
> following a fixed script." Then keep going. Judges respect composure more
> than a perfectly clean take.
