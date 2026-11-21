# NextPay — Collections Prioritization Agent

*Project Plan & PRD · Problem Statement 2: “Who Will Pay First?” · Sarvam × Cashfree Buildathon, Team of 5 · Working title, rename as you like*

## PART A — PROJECT PLAN

### 1. Overview

Build an agent-driven system that decides which overdue borrower to contact today, reaches them by voice in their own language, collects payment (full or partial) through Cashfree, and re-forms the call queue the moment a payment, promise, or claim changes the picture — all while explaining every decision in plain language and staying inside the problem’s fairness and compliance red lines.

### 2. Objectives

- Replace blind loan-number-order calling with a defensible, explainable ranking.
- Turn outreach into collected money, not just contacted borrowers.
- Make the queue reactive: it updates live as real-world events (payments, promises, claims) land.
- Prove the ranking is fair (no protected-signal dependence) and effective (beats the naive order on a held-out test).

### 3. Scope

**In scope for the build:**

- Synthetic borrower book generator (two books: a “training” book with known outcomes, and a “held-out” book that mimics the demo-day curveball)
- Ranking engine with a defensible, auditable scoring formula
- Outbound voice calling via Sarvam (Saaras for understanding, Bulbul for speaking)
- Cashfree Payment Links (full and partial payment, with webhooks)
- Event-driven queue re-ranking (payment, partial payment, lapsed promise, unverified “already paid” claim, expired link)
- Lender dashboard: ranked queue, reasons, live updates, held-out evaluation panel, fairness swap-test panel
- A fairness audit tool (the “swap test”) and a held-out evaluation harness

**Out of scope:**

- Real customer data or production system integration
- Full legal/regulatory sign-off (we model the rules; a compliance team would still need to review before production)
- Production-grade authentication beyond what the demo needs

### 4. Personas

- **Meena** — the collections manager. Primary user of the dashboard; needs to see *who*, *why*, and *what happened*, at a glance.
- **The borrower** — receives the call, can pay in full, pay partially, make a promise, claim prior payment, or ask for a callback.
- **The authorised lender** — the only role allowed to approve changed loan terms (the agent itself cannot do this).
- **The judge** — watches a 10–12 minute demo and needs to see money move live, and the fairness/held-out proof.

### 5. System Architecture

```
[Borrower book] --> [Ranking Engine (Lambda)] --> [Relay Agent]
                                                         |
                          +------------------------------+------------------------------+
                          |                              |                               |
                 [Sarvam: Saaras/Bulbul]        [Cashfree: Payment Links]        [Dashboard (HTTP action → UI)]
                          |                              |
                   (call outcome / intent)      (webhook: PAID / PARTIALLY_PAID /
                          |                       EXPIRED / CANCELLED)
                          +--------------→ [Event Handler (Lambda)] --------------→ [Re-rank + update dashboard]
```

- **Relay** is the orchestration layer: Trigger → Agent → Actions, as in the builder briefing.
- **AWS Lambda** holds the parts Relay’s drag-and-drop actions can’t express cleanly: the scoring formula, the idempotent balance-update logic, and the swap-test/held-out evaluation routines.
- **Cashfree Payment Links + Webhooks** are the money and event source of truth.
- **Sarvam** is the language layer only — it never feeds scoring directly (see Section 8).

### 6. Workstreams & Ownership

| # | Workstream | Core tasks |
| --- | --- | --- |
| A | Synthetic data | Borrower book generator (fields below), held-out “book v2” with unseen patterns, sample call scripts/audio incl. the Kannada “already paid” line, pre-seeded Cashfree sandbox Payment Links in multiple states |
| B | Ranking engine | Scoring formula, reason strings, swap test, held-out evaluation harness |
| C | Voice/outreach | Saaras transcription, Bulbul calling, constrained intent extraction, compliance script (recording disclosure, identity verification) |
| D | Payments & events | Payment Link creation (full/partial), webhook listener, idempotent state machine |
| E | Lender dashboard | Ranked queue view, reason display, live re-ranking, held-out + swap-test panels, hardship/approval panel |
| F | Relay + infra | Wire triggers → agent → actions, Lambda functions, secret properties, demo rehearsal |

Suggested: one person per workstream, with whoever owns B (ranking) and D (payments) pairing closely, since the event state machine depends on both.

### 7. Timeline

**Before the 4-hour build (prep work, as much as time allows):**

- Finalize the borrower book schema and generate both books
- Stand up Cashfree + Sarvam sandbox accounts (see builder briefing setup steps)
- Draft the ranking formula and reason-string templates
- Sketch the dashboard UI

**During the build (11:30 AM–3:30 PM):**

- Hour 1: Wire the Relay trigger → agent → action skeleton; load borrower book; get one webhook round-tripping end to end
- Hour 2: Implement the full state machine (Section 9) and the ranking formula (Section 8); connect Sarvam calling
- Hour 3: Build the dashboard panels; connect live re-ranking to the UI
- Hour 4: Run the held-out evaluation and swap test; rehearse the demo script (Section 13); fix what breaks

## PART B — PRODUCT REQUIREMENTS

### 8. Ranking Logic (Detailed Spec)

**Allowed signals (the only things that may feed the score):**

- Verified payment receipts
- An explicitly requested callback
- Previous timely payments made *after* a reminder
- Prior unaided payments (paid without needing a reminder)
- Explicit future promises (a stated promise-to-pay date)
- Language — used only to pick which language to speak in, never as a scoring input

**Excluded from scoring, with no exceptions:** gender, caste, religion, name, locality/PIN code, accent, phone model, and raw text embeddings of call transcripts. Speech is reduced to a small, fixed set of intents (e.g., *will pay now*, *promise date given*, *already paid claim*, *cannot pay/hardship*, *callback requested*, *no response*) before it ever reaches the scorer — the raw embedding never does.

**Prototype formula** (demo weights, not final):

```
score = 3 × callback_due
      + min(2, prior_payments_after_reminders)
      − min(2, prior_unaided_payments)
```

Sort descending; break ties on a stable borrower ID (deterministic, never random). This rewards people who asked to be called and people who respond to reminders, and deprioritizes people who reliably pay on their own — directly matching the problem’s framing: *“Someone who usually pays on their own can wait.”*

Every ranked borrower must carry a **plain-language reason string** generated from the same inputs (e.g., “Called back last month after a reminder; no outstanding promise” — a manager should be able to read it aloud and understand the score).

**Fairness audit (the swap test):** take an identical borrower record and swap only the name, language, and area/locality. Re-run scoring, eligibility, and reason generation. The outputs must be unchanged. Run this across a representative sample before the demo, and keep the results ready to show live. Separately, review aggregate outcome gaps across groups (not just this record-level test) as a second, independent check.

**Held-out evaluation (prove it before anyone pays):**

1. Freeze the ranking rule using the labeled “book v1” (known outcomes).
2. Run it blind on “book v2” (outcomes withheld).
3. Take the top-K eligible borrowers under the same call budget as the naive loan-number order.
4. Report: confirmed payers ÷ K, rupees recovered, and how many of the K were actually ineligible (wasted calls).
5. Before any outcome labels are available, separately check: no red-line (“gate”) violations in the ranked list, ranking stability under small input perturbations, and 100% reason coverage.
6. Note for future iteration (stretch, not required for the demo): a rigorous causal claim that *calling* — not just ranking — caused the payment needs a randomized comparison group among eligible, consenting borrowers.

### 9. Event & State Logic

| Event | System response |
| --- | --- |
| Full verified payment | Close the balance, remove the borrower from the queue |
| Partial payment (e.g., ₹300 of ₹1,000) | Update the remaining balance **once** (₹1,000 → ₹700), stop the old full-amount demand, record the next agreed date. Must be idempotent — replaying the same payment event must leave the balance at ₹700, not deduct again |
| Promise lapses (agreed date passes, no payment) | Trigger a balance check, then re-run eligibility and contact-time checks before re-queuing |
| Unverified “already paid” claim (e.g., “I paid at the branch”) | Pause outward collection for that borrower immediately, pending reconciliation against actual records |
| Expired or cancelled payment link | Leaves the obligation open — balance is not cleared, borrower stays eligible for the queue |

Idempotency is the trap to design around explicitly: key every webhook handler off a unique transaction/event ID so a retried or duplicate delivery never double-applies a balance change.

### 10. Offers for Borrowers Who Cannot Pay in Full

- A permitted partial payment, with the **first minimum amount disclosed upfront** (Cashfree Payment Links support a minimum first payment)
- A callback at a time the **borrower chooses**, not the system
- Escalation to a **human** hardship conversation — once hardship is flagged, automated pressure stops entirely
- Changed loan terms (restructuring, discounts) can only be approved by an **authorised lender role** — the agent must never do this unilaterally
- Before discussing any balance: identify the lender, disclose that the call is recorded (in the borrower’s own language), and verify the listener’s identity

### 11. Compliance Checklist (red lines — treat as non-negotiable, tick off before demo)

- [ ] No scoring on gender, caste, religion, name, locality, PIN code, accent, phone model, or raw embeddings
- [ ] Calling restricted to the permitted window (8 AM–7 PM by default, adjustable if the borrower asks for a different time)
- [ ] Recording disclosed to every borrower, in their own language
- [ ] No threats, shaming, or pressure language anywhere in the call scripts
- [ ] Every score ships with a plain-language reason
- [ ] Changed loan terms require explicit authorised-lender approval
- [ ] Listener identity verified before any balance is discussed
- [ ] Webhook handling is idempotent — no event can cause a double payment or double balance update
- [ ] Unreconciled claims (e.g., “already paid”) pause the queue rather than being guessed at

### 12. Lender Dashboard Requirements

- **Ranked queue**: borrower, score, reason, eligibility status, last contact outcome
- **Live re-ranking**: visibly updates the moment a webhook event fires — this should be the dashboard’s signature “wow” moment in the demo
- **Event log**: every ranking and state-change decision, traceable back to the signals that produced it
- **Held-out comparison panel**: confirmed payers/K and rupees recovered, ranked order vs. naive order, side by side
- **Swap-test panel**: shows an identical record before/after a name/language/area swap, with unchanged score and reason, as live proof of no proxy dependence
- **Hardship & partial-payment panel**: borrowers currently on a partial-payment plan with their next agreed date; hardship cases flagged for human review, with an explicit “authorised lender approval” action gated behind a role check

### 13. Demo Script

1. **Reconciliation pause** — live call where a borrower says, in Kannada, “ನಾನು ನಿನ್ನೆ ಬ್ಯಾಂಕ್‌ನಲ್ಲಿ ಹಣ ಕಟ್ಟಿದ್ದೇನೆ” (“I deposited the money at the bank yesterday”). Show the queue immediately pausing that borrower for reconciliation.
2. **Idempotent partial payment** — a separate borrower pays ₹300 of ₹1,000 via a Payment Link. Dashboard shows the balance drop to ₹700 and the next agreed date recorded. Replay the same webhook event live — balance stays at ₹700, proving no double-deduction.
3. **Held-out proof** — show confirmed payers/K and rupees recovered on “book v2,” ranked order vs. naive loan-number order.
4. **Fairness proof** — show the swap-test panel: identical record, swapped name/language/area, unchanged score and reason.
5. **(If time allows) Hardship path** — a borrower who can’t pay in full is offered a partial plan, a chosen callback time, or escalation to a human — not pressure.

### 14. Milestone Targets

- **Solid**: clean a messy book, rank it with a reason per borrower, get one eligible borrower actually contacted and paid in the Cashfree sandbox.
- **Strong**: queue re-forms live after a real event; partial-payment and callback alternatives are actually offered and used.
- **Exceptional**: held-out comparison shows the ranking beats the naive order; swap test shows no reliance on protected characteristics or their proxies.

### 15. Deliverables Checklist

- [ ] Working end-to-end demo ending in a sandbox payment, partial payment, or a precisely explained refusal/pause
- [ ] Short design-choices note: signals used and excluded (and why), architecture choices, what you deliberately didn’t use
- [ ] One success case (borrower reached and paid) and one failure/decline case (e.g., the reconciliation-pause or hardship path) shown end to end
- [ ] All data synthetic, built to match Cashfree’s published sandbox test data

### 16. Open Decisions for the Team

- Which language(s) to demo live — confirm Bulbul’s current supported-language list before committing to Kannada on stage
- The real daily call cap to model (≈360/day matches the original six-caller team) vs. a smaller number to walk through live on stage
- Who plays the “authorised lender” role approving changed terms in the demo — a teammate at a dashboard button, most likely
