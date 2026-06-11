# Antigravity Simulation Conversation Recap

Last updated: 2026-05-26

This README is a re-onboarding document for the engineering simulation workstream that grew out of the Antigravity interview product conversation. It recaps the history, product reasoning, implementation progress, current state, and next direction.

## 1. Why This Workstream Started

Antigravity began as a live adversarial interview engine. The original product goal was to interrogate resume claims, detect weak reasoning, and generate sharp follow-up questions in a voice-led interview.

That system showed real promise:

- Weakness detection was often technically accurate.
- Discrepancy probing could expose inflated or false claims.
- Final evaluations were more calibrated than expected.
- The trajectory/interview-map concept had strong bones.

But the deeper review exposed structural problems:

- Resume parsing was unreliable.
- Focus inference often failed.
- The interview map was underused at runtime.
- The system could get stuck drilling one topic.
- It leaned too heavily toward adversarial proof instead of balanced substance measurement.
- Candidate comfort and psychological flow were not yet strong enough.

The conclusion was important: Antigravity should not merely be an adversarial interview. It should become a substance measurement system.

The engineering simulation idea emerged from that realization.

## 2. The Product Philosophy Shift

The old center of gravity was:

> Probe the candidate until weak claims break.

The new center of gravity became:

> Observe the candidate doing realistic engineering work, then separate what was proved from what remains uncertain.

This changed the product frame.

The goal is not to catch candidates. The goal is to measure engineering substance:

- Can they understand a real production problem?
- Can they form the right invariants?
- Can they implement a safe patch?
- Can they validate their own work?
- Can they explain what tests prove and do not prove?
- Can they reason about production risk beyond the sandbox?

This is the north star:

> An AI-observed engineering simulation that measures how a candidate thinks, implements, validates, and explains uncertainty under realistic production pressure.

## 3. Why Simulation, Not Just Interview

Normal interviews are constrained by words. Candidates can say they understand idempotency, concurrency, transactions, retries, Kubernetes, data pipelines, or model deployment, but the interview may never test whether they can actually operate inside that world.

The proposed simulation layer extends Antigravity by adding a workbench:

- The candidate still interacts with an interviewer.
- The candidate also edits code, runs tests, and handles staged production evidence.
- The system observes artifacts, not just claims.
- The report becomes evidence-backed instead of purely conversational.

This fits the larger ProvenHire direction:

- Logic/aptitude round maps general reasoning.
- DSA round maps algorithmic skill.
- Antigravity interview maps resume/world claims and conceptual depth.
- Engineering simulation maps job-like execution behavior.

Together, these can eventually form a candidate skill map.

## 4. Why Payment Retry Safety Was Chosen First

The first complete simulation chosen was payment retry safety.

Reason: it is small enough to build, but deep enough to test real backend judgment.

A shallow candidate says:

> Use idempotency keys.

A stronger candidate can explain:

- client retries
- duplicate money movement
- idempotency-key ownership
- same-key payload conflicts
- pending/completed state reuse
- gateway timeout ambiguity
- database uniqueness
- concurrency collapse
- webhook/reconciliation gaps
- monitoring and rollback concerns

The payment case is excellent because it tests whether the candidate is safe around money movement.

The core question is not:

> Can the candidate pass a unit test?

It is:

> Would this candidate be safe to put on a payments backend team?

## 5. Early Mistakes And Corrections

The first simulation prototype tried to do too much:

- voice
- Gemini/OpenAI realtime
- Deepgram
- Cartesia
- polished UI
- code execution
- scoring
- investor-demo readiness

That scattered focus. Voice and live-agent features were distracting from the core truth: the simulation had to be honest before it could be alive.

Early product failures included:

- Candidate could click through with little work.
- Starter-code behavior could accidentally produce score-like signal.
- Correct code alone could over-reward shallow reasoning.
- Reports were not yet explicit enough about uncertainty.
- Admin/persistence could not reliably prove completed sessions existed.

The workstream then narrowed to one rule:

> First make the simulation refuse fake progress, measure evidence correctly, and explain uncertainty honestly.

## 6. Current Implemented Product

There are now two standalone simulations.

### Payment Retry Safety

Route:

```text
/simulation
```

The candidate works through five stages:

1. Understanding
2. Planning
3. Implementation
4. Validation
5. Reflection

The candidate edits:

```text
payment.mjs
```

The system runs real Node tests against the candidate code.

The test suite checks:

- missing idempotency key rejection
- first request creates one completed charge
- duplicate completed request reuses original result
- duplicate pending request reuses existing attempt
- same key with different amount/currency is rejected
- gateway timeout leaves recoverable non-completed state
- concurrent duplicate retries collapse to one payment/charge
- key cannot be reused by a different user
- gateway receives idempotency key
- retry after recoverable gateway failure does not blindly create a second charge

### Inventory Race

Route:

```text
/simulation/inventory
```

The candidate edits:

```text
inventory.mjs
```

This simulation tests:

- concurrent read/write race recognition
- optimistic locking
- compare-and-decrement behavior
- oversell prevention
- contention handling
- ghost inventory / crash-between-writes risk

## 7. Current Backend Architecture

Main files:

```text
backend/services/simulation_service.py
backend/services/inventory_simulation_service.py
backend/api/routes.py
backend/test_simulation_service.py
backend/test_inventory_simulation_service.py
```

Important backend behavior:

- Session state is stored in Redis.
- Completed sessions are marked as complete for longer retention.
- Simulation reports remain available through report endpoints.
- Admin uses lightweight summary indexes instead of scanning full report blobs.

Summary keys:

```text
sim_summary:*
invsim_summary:*
```

This was added because scanning full `sim:*` / `invsim:*` JSON blobs caused admin/session listing to hang or feel unreliable.

## 8. Current Frontend Architecture

Main files:

```text
app/simulation/page.tsx
app/simulation/inventory/page.tsx
app/simulation/admin/page.tsx
app/simulation/report/[session_id]/page.tsx
tests/simulation.e2e.spec.ts
```

The current UI is an engineering cockpit:

- left rail for stage/state/worklog
- center workbench for code and tests
- report area for final evidence
- admin page for completed sessions
- shareable report route

The voice controls were intentionally removed from the main simulation surface for now. This was a deliberate product decision: the core simulation must become trustworthy before voice makes it feel alive.

## 9. Evidence Contract

The most important current product contract:

> The simulation must not reward fake progress.

Current guarantees:

- Empty/lazy candidate cannot advance meaningfully.
- No premature score appears.
- Run Tests stays unavailable until implementation evidence exists.
- Starter code cannot count as candidate validation.
- Bad patches fail real tests.
- Green tests alone do not guarantee Strong Hire.
- Keyword-salad reasoning is capped below Strong Hire.
- Strong code plus strong reasoning can reach Strong Hire.

This is the difference between a demo toy and an assessment product.

## 10. Reasoning Quality And Authorship

The system now scores reasoning artifacts, not just code.

It looks for:

- causal reasoning
- concrete technical anchors
- sequence/order-of-operations thinking
- action verbs
- production-twist handling
- repetition / keyword stuffing
- shallow lexical coverage

Reports now include:

```text
Reasoning Quality / Authorship Signal
```

This section exists because a candidate may paste correct code without demonstrating independent engineering judgment.

For example:

- good code + weak notes = lower signal
- good code + strong causal explanation = strong signal

This is a core product moat.

## 11. Evidence Ledger

Final reports include an evidence ledger.

The ledger separates:

- what runtime tests proved
- what hidden tests proved
- what the candidate acknowledged
- what remains untested
- what production risks remain
- what the next challenge should be

This is one of the most important architectural moves in the product.

The report no longer says only:

> Candidate scored 98.

It can say:

> Candidate proved duplicate retry safety and cross-user conflict handling, but real webhook reconciliation and database crash boundaries remain unproven.

That distinction is the product.

## 12. Production Twists

The payment simulation injects a production twist after green tests:

- A gateway timeout was marked as failed.
- The client retried.
- A second charge was created.
- A delayed `charge.succeeded` webhook arrived for the original timed-out attempt.
- Now two real charges exist for the same operation.

The inventory simulation injects a ghost-inventory twist:

- Inventory decrement succeeded.
- Process crashed before reservation write.
- Inventory is reduced without matching reservation/order.

These twists force the candidate to reason beyond unit tests.

## 13. Current QA Coverage

Automated E2E coverage lives in:

```text
tests/simulation.e2e.spec.ts
```

Current browser scenarios:

1. Empty click-through is blocked.
2. Starter code cannot become candidate evidence.
3. Strong payment candidate completes and reaches Strong Hire.
4. Keyword-salad candidate with correct code is capped below Strong Hire.
5. Inventory simulation completes with persisted report.
6. Admin lists completed payment and inventory reports.

Last verified command:

```bash
PLAYWRIGHT_NEXT_START=1 PLAYWRIGHT_BACKEND_PORT=8001 PLAYWRIGHT_FRONTEND_PORT=3002 npm run test:simulation:e2e
```

Expected:

```text
6 passed
```

## 14. How To Run Locally

Backend:

```bash
python3 -u -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Frontend:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run start -- -p 3002
```

Payment simulation:

```text
http://127.0.0.1:3002/simulation
```

Inventory simulation:

```text
http://127.0.0.1:3002/simulation/inventory
```

Admin:

```text
http://127.0.0.1:3002/simulation/admin
```

Backend tests:

```bash
python3 backend/test_simulation_service.py
python3 backend/test_inventory_simulation_service.py
```

Build:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run build
```

E2E:

```bash
PLAYWRIGHT_NEXT_START=1 PLAYWRIGHT_BACKEND_PORT=8001 PLAYWRIGHT_FRONTEND_PORT=3002 npm run test:simulation:e2e
```

## 15. Demo Paths

### Lazy Candidate

Run:

- Start simulation.
- Press Next Stage without writing.
- Type: `I will check the code`
- Press Next Stage.

Expected:

- blocked
- no score
- Run Tests disabled

### Bad Patch

Use strong notes but paste `BAD_PATCH` from:

```text
tests/simulation.e2e.spec.ts
```

Expected:

- tests fail
- about `3/10 checks`
- duplicate/idempotency failures visible

### Strong Payment Candidate

Use:

- `UNDERSTANDING_NOTE`
- `PLANNING_NOTE`
- `IMPLEMENTATION_NOTE`
- `GOOD_PATCH`
- `VALIDATION_NOTE`
- `REFLECTION_NOTE`

Expected:

- `10/10 checks passing`
- Strong Hire
- around 98
- report separates proved vs unproved

### Keyword-Salad Candidate

Use:

- `KEYWORD_SALAD_NOTES`
- `GOOD_PATCH`

Expected:

- tests pass
- not Strong Hire
- Mixed Signal / capped score
- weak reasoning/authorship uncertainty called out

### Strong Inventory Candidate

Use:

- `INVENTORY_UNDERSTANDING_NOTE`
- `INVENTORY_PLANNING_NOTE`
- `INVENTORY_IMPLEMENTATION_NOTE`
- `GOOD_INVENTORY_PATCH`
- `INVENTORY_VALIDATION_NOTE`
- `INVENTORY_REFLECTION_NOTE`

Expected:

- Strong Hire
- ghost inventory / crash-between-writes remains called out

## 16. Security And Secrets Note

During the conversation, API keys were pasted into chat for OpenAI, OpenRouter, Cartesia, Deepgram, and Gemini.

Those keys should be considered exposed and rotated before any production or shared demo use.

The simulation code should not hard-code secrets. Runtime keys belong in environment variables only.

## 17. What Is Strong Now

The strongest parts today:

- The product refuses fake progress.
- Real code runs against real tests.
- Hidden checks test deeper behavior.
- Reports distinguish evidence from uncertainty.
- Keyword-salad candidates are not over-rewarded.
- Strong candidates can be rewarded.
- Admin can prove completed sessions exist.
- Payment and inventory share the same assessment philosophy.

This is no longer just a visual prototype. It has an assessment spine.

## 18. What Is Still Weak

The product is honest, but not yet fully alive.

Current weaknesses:

- The stage flow can still feel like filling out a form.
- The interviewer is not yet deeply adaptive in the UI.
- Production twists are effective, but could be more interactive.
- The code sandbox is acceptable for internal prototype use, not public arbitrary execution.
- Reports are good, but can become more hiring-panel-ready.
- The simulation framework is still hard-coded around two cases.
- Voice should remain frozen until the core flow is more polished.

## 19. Recommended Next Sprint

Recommended next sprint:

```text
Make The Simulation Feel Like A Real Engineering Interview
```

Suggested scope:

1. Make stage prompts sharper and more conversational.
2. Make production twists feel like live incident updates.
3. Make evidence ledger visually central.
4. Add a post-report next challenge interaction.
5. Improve report narrative for hiring-panel readability.
6. Keep voice and new integrations frozen.

The core is now reliable enough to polish the human experience.

## 20. Long-Term North Star

The simulation workstream should eventually become:

> A job-specific engineering assessment engine that uses prior candidate signals, resume claims, DSA performance, and Antigravity interview findings to generate a realistic work simulation, observe candidate behavior, and produce an evidence-backed skill map.

That means future simulations should not be random coding tasks.

They should be selected because:

- the role requires that skill
- the candidate claims that skill
- previous rounds surfaced uncertainty around that skill
- the job would actually require similar work

The end product should answer:

```text
What did this candidate prove?
What did they merely claim?
What remains untested?
What should we test next?
Would we trust them in this production environment?
```

That is the real product direction.

