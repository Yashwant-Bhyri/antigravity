# Antigravity Engineering Simulation Conversation Recap

This document recaps the product conversation, implementation arc, and current state of the Antigravity engineering simulation workstream. It is meant for picking the project back up after time away without needing the full chat history.

Last updated: 2026-05-26

## Short Version

We started with a deep review of Antigravity's existing interview engine and found that the analysis layer was genuinely strong, but the routing/interview-navigation layer had structural weaknesses. That led to a larger product question: how do we move beyond an adversarial interview into an assessment system that measures real engineering substance?

The answer we converged on was an engineering simulation layer inside the ProvenHire assessment stack. The simulation is not a quiz and not a coding challenge in isolation. It is an interviewer-observed workbench where the candidate reads an incident, explains their mental model, plans, edits code, runs real tests, handles production-style uncertainty, reflects on tradeoffs, and receives a report that separates what was proved from what remains unproved.

The first implemented slice is Payment Retry Safety at `/simulation`. A second Inventory Race simulation was added at `/simulation/inventory`. Both now have real test execution, gated stages, reasoning-quality scoring, evidence ledgers, report persistence, and Playwright E2E coverage.

## Why This Started

The early Antigravity interview system had impressive pieces:

- Weakness detection was technically sharp.
- Discrepancy detection could expose inflated or contradictory resume claims.
- Final verdicts were often calibrated.
- The trajectory-map concept had strong potential for grounded interview navigation.

But the system also had obvious product and architecture problems:

- Resume parsing was unreliable.
- Focus inference often returned empty values.
- The interview could tunnel too hard on one weakness.
- The bridge/coverage mechanisms were underused or broken.
- The system leaned too much toward catching candidates and not enough toward measuring substance.
- Strong candidates sometimes had too little room to demonstrate breadth.
- STT noise and candidate psychology were not handled carefully enough.

The philosophical correction was important:

> Antigravity should not primarily be an investigation system. It should be a substance measurement system.

Adversarial pressure is still useful, but only as one mode of assessment. The product needs curiosity, exploration, challenge, validation, psychological safety, and proof. The candidate's resume is not the thing to prosecute; it is a map into the candidate's claimed world.

## Product Direction That Emerged

The broader ProvenHire stack was framed as:

- Aptitude / logic: general cognitive signal.
- DSA: algorithmic and coding fluency signal.
- Antigravity interview: claimed-experience and reasoning-depth signal.
- Engineering simulation: applied engineering judgment under realistic work conditions.

The simulation layer became the ambitious extension:

- Pick a specific job role.
- Use the candidate skill map from DSA + Antigravity interview.
- Choose or generate a highly relevant engineering simulation.
- Observe how the candidate works, not only what answer they give.
- Produce an evidence-based report that says what was proved, what was not proved, and what challenge should come next.

The agreed product principle:

> One excellent, robust, agent-verifiable simulation is more valuable than ten shallow simulations.

## Initial Concerns And Course Correction

There was early temptation to add voice, Gemini Live, OpenAI Realtime, Cartesia, Deepgram, audio upload, and other impressive-sounding interfaces.

That created distraction. The core product was not voice. The core product was:

- Does the simulation refuse fake progress?
- Does it measure engineering evidence correctly?
- Does it distinguish green tests from real reasoning?
- Does it explain uncertainty honestly?
- Does it feel like engineering work, not a form with tests attached?

The eventual call was:

> Freeze voice and integration complexity until the simulation itself is undeniably strong.

This was the right call. Voice is still product-relevant later, but it cannot compensate for weak assessment semantics.

## Chosen First Simulation: Payment Retry Safety

Payment retry safety was chosen because it is small enough to build end-to-end but rich enough to test real backend judgment.

On the surface, the candidate needs to prevent duplicate charges when a mobile client retries `POST /payments`.

Underneath, the simulation tests:

- idempotency keys
- duplicate request handling
- pending/completed state reuse
- same-key payload conflicts
- gateway timeout behavior
- concurrency races
- gateway idempotency propagation
- delayed webhook/reconciliation risk
- monitoring and rollout judgment

This case is strongest for:

- Backend Software Engineer
- Senior Backend / Platform Engineer
- Payments / Fintech Engineer
- Production / Reliability Engineer

## Implemented Product Shape

The current simulation loop has five fixed stages:

1. Understanding
2. Planning
3. Implementation
4. Validation
5. Reflection

The candidate must:

- Read the incident.
- Write a concrete understanding artifact.
- Write a plan with invariants and failure modes.
- Edit the handler code.
- Run real tests.
- Explain validation evidence.
- Address the production twist.
- Reflect on monitoring, reconciliation, and remaining risks.

The system then produces a report.

## Payment Simulation Current Behavior

Route:

```text
http://127.0.0.1:3002/simulation
```

Core backend route family:

```text
POST /api/simulation/start
GET  /api/simulation/state/{session_id}
POST /api/simulation/interviewer_turn
POST /api/simulation/run_tests
POST /api/simulation/finalize
GET  /api/simulation/report/{session_id}
GET  /api/simulation/sessions
```

Core file map:

```text
app/simulation/page.tsx
app/simulation/admin/page.tsx
app/simulation/inventory/page.tsx
app/simulation/report/[session_id]/page.tsx
backend/services/simulation_service.py
backend/services/inventory_simulation_service.py
backend/api/routes.py
backend/test_simulation_service.py
backend/test_inventory_simulation_service.py
tests/simulation.e2e.spec.ts
playwright.config.ts
SIMULATION_PRD.md
PAYMENT_RETRY_SAFETY_PRD.md
```

## Key Product Guarantees Added

### Fake Progress Is Blocked

Lazy candidates cannot click through and receive a score.

The system blocks empty/vague stage artifacts and keeps `Run Tests` disabled until implementation evidence exists.

### Starter Code Does Not Count

The system runs a starter baseline, but that baseline is not candidate evidence.

If the candidate reaches implementation without changing `payment.mjs`, `Run Tests` stays unavailable or the backend rejects validation.

### Bad Patches Fail

A superficial patch that only requires an idempotency key but still inserts a fresh row and charges again fails the runtime suite.

Expected bad-patch result:

```text
3/10 checks
```

### Strong Candidates Can Win

A strong candidate with correct code and coherent reasoning can reach:

```text
98 / Strong Hire
```

### Green Tests Alone Are Not Enough

A candidate who pastes correct code but gives keyword-heavy shallow notes is capped below Strong Hire.

Expected keyword-salad result:

```text
~68 / Mixed Signal
```

The report now explicitly calls out reasoning/authorship uncertainty.

### Reports Separate Evidence From Uncertainty

Reports include:

- What Was Proved
- What Remains Unproven
- Reasoning Quality / Authorship Signal
- Candidate Quotes
- Session Timeline
- Evidence Ledger
- Next Challenge

This matters because passing unit tests does not prove production safety.

## The Production Twist

After the candidate gets the request-path tests green, the simulation injects a production twist:

- Gateway returned a network timeout.
- The local service marked the payment failed.
- The client retried.
- A second charge was created.
- A delayed `charge.succeeded` webhook arrived for the original timed-out request.
- Now two gateway charges exist for one user operation.

This twist tests whether the candidate understands that request-path idempotency is not the whole payment-safety story.

The expected strong answer acknowledges:

- webhook reconciliation is still unimplemented
- refund/void workflow needs production handling
- gateway and local state can diverge
- monitoring is required for aged pending/failed payments and webhook mismatches

## Inventory Simulation

The second simulation is a flash-sale inventory race.

Route:

```text
http://127.0.0.1:3002/simulation/inventory
```

It tests:

- concurrent read/write race conditions
- oversell prevention
- optimistic locking
- versioned compare-and-decrement
- contention handling
- crash-between-writes risk
- ghost inventory reconciliation

Expected strong-candidate result:

```text
96 / Strong Hire
```

The inventory simulation was added to prove that the assessment philosophy can generalize beyond payments.

## Admin And Persistence

Admin route:

```text
http://127.0.0.1:3002/simulation/admin
```

Important hardening:

- Completed payment and inventory sessions are listed.
- Reports can be opened after navigation.
- Session rows include scenario, stage, score, tests, runs, twist, updated time, and report link.
- Admin now reads lightweight Redis summary rows instead of scanning full report blobs.

Summary keys:

```text
sim_summary:*
invsim_summary:*
```

This was added because scanning full `sim:*` / `invsim:*` blobs made `/api/simulation/sessions` slow or hanging in demo conditions.

## Testing History

The QA philosophy became:

> Do not test whether it looks nice. Test whether it refuses fake progress, measures evidence correctly, and explains uncertainty honestly.

The important QA flows:

1. Lazy candidate
2. Starter-code abuse
3. Bad patch
4. Strong candidate
5. Keyword-salad + correct code
6. Evidence ledger
7. Inventory strong candidate
8. Admin / persistence

The current Playwright suite covers:

- empty click-through is blocked
- starter code cannot count as candidate validation
- payment strong candidate completion
- keyword-salad candidate with correct code capped below Strong Hire
- inventory simulation completion and persisted report
- admin lists completed payment and inventory reports

Current expected command:

```bash
PLAYWRIGHT_NEXT_START=1 PLAYWRIGHT_BACKEND_PORT=8001 PLAYWRIGHT_FRONTEND_PORT=3002 npm run test:simulation:e2e
```

Last known good result:

```text
6 passed
```

## Current Run Commands

Start backend:

```bash
python3 -u -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Start frontend:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run start -- -p 3002
```

Build:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run build
```

Backend simulation tests:

```bash
python3 backend/test_simulation_service.py
python3 backend/test_inventory_simulation_service.py
```

E2E:

```bash
PLAYWRIGHT_NEXT_START=1 PLAYWRIGHT_BACKEND_PORT=8001 PLAYWRIGHT_FRONTEND_PORT=3002 npm run test:simulation:e2e
```

Demo routes:

```text
Payment:   http://127.0.0.1:3002/simulation
Inventory: http://127.0.0.1:3002/simulation/inventory
Admin:     http://127.0.0.1:3002/simulation/admin
```

## Demo Script

Recommended investor/team demo:

1. Lazy candidate
   - Start simulation.
   - Press Next with empty notes.
   - Paste `I will check the code`.
   - Press Next again.
   - Show that the system blocks progress and gives no score.

2. Bad patch
   - Use decent notes.
   - Paste the bad patch from `tests/simulation.e2e.spec.ts`.
   - Run tests.
   - Show `3/10 checks` and meaningful failure names.

3. Strong candidate
   - Use strong notes and `GOOD_PATCH` from `tests/simulation.e2e.spec.ts`.
   - Run tests.
   - Show `10/10 checks passing`.
   - Finalize.
   - Show `Strong Hire`, `What Was Proved`, `What Remains Unproven`, and `Reasoning Quality / Authorship Signal`.

4. Keyword-salad candidate
   - Use `KEYWORD_SALAD_NOTES` but paste `GOOD_PATCH`.
   - Show tests pass but score stays below Strong Hire.
   - Show authorship/reasoning uncertainty.

5. Admin
   - Open `/simulation/admin`.
   - Show completed payment and inventory sessions.
   - Open a persisted report.

## Important Design Decisions

### Do Not Reintroduce Voice Before The Core Is Stable

Voice is important, but it is not the current blocker.

The core blocker was always assessment truth:

- fake progress refusal
- evidence measurement
- reasoning/authorship detection
- honest uncertainty
- robust reports
- persistence/admin proof

Voice should support this loop later. It should not distract from it.

### Do Not Treat Passing Tests As Final Truth

Runtime tests prove specific behavior in the sandbox.

They do not prove:

- real Postgres transaction behavior
- gateway webhook reconciliation
- crash recovery
- refund/void workflows
- multi-region payment semantics
- production observability quality

The report must keep this distinction visible.

### Do Not Reward Verbosity Alone

Earlier scoring over-penalized concise correct candidates and over-rewarded fail-then-fix ceremony.

The current stance:

- concise coherent reasoning can be Strong Hire
- keyword-heavy shallow reasoning is capped
- first-pass correctness can be a strong signal if the candidate explains what was proved and what was not

### Keep One Excellent Slice Before Expanding

The product ambition is broad, but expansion should happen only after the first slice is reliable.

The current two slices are:

- Payment Retry Safety
- Flash Sale Inventory Race

More simulations should follow the same evidence contract, not just copy the UI.

## Current Architecture Notes

### Payment Service

Main service:

```text
backend/services/simulation_service.py
```

Responsibilities:

- session state
- stage gates
- starter baseline
- test runner
- scoring
- artifact quality
- evidence ledger
- report generation
- Redis summary rows

### Inventory Service

Main service:

```text
backend/services/inventory_simulation_service.py
```

Responsibilities mirror the payment service, but the domain is inventory race safety.

### Frontend

Main payment UI:

```text
app/simulation/page.tsx
```

Inventory UI:

```text
app/simulation/inventory/page.tsx
```

Admin UI:

```text
app/simulation/admin/page.tsx
```

Shareable report:

```text
app/simulation/report/[session_id]/page.tsx
```

### Tests

Primary E2E file:

```text
tests/simulation.e2e.spec.ts
```

This file also contains the canonical demo notes and patches:

- `BAD_PATCH`
- `GOOD_PATCH`
- `GOOD_INVENTORY_PATCH`
- `UNDERSTANDING_NOTE`
- `PLANNING_NOTE`
- `IMPLEMENTATION_NOTE`
- `VALIDATION_NOTE`
- `REFLECTION_NOTE`
- `KEYWORD_SALAD_NOTES`
- inventory note constants

## What Is Strong Now

- The product no longer rewards click-through.
- Starter code is separated from candidate evidence.
- Bad patches fail meaningful tests.
- Strong candidates can reach Strong Hire.
- Keyword-salad candidates are capped despite green tests.
- Reports explain uncertainty.
- Admin can show persisted completed sessions.
- Payment and inventory share the same philosophy.
- E2E covers six important product behaviors.

## What Is Still Weak Or Prototype-Level

- The code execution sandbox is a local Node permission sandbox, not a public-grade microVM/container boundary.
- The payment simulation uses fake in-memory store/gateway, not Postgres + gateway service + webhooks.
- Voice is intentionally de-emphasized and not yet the main product loop.
- Simulation authoring/generation is not built.
- Role-to-simulation matching is not built.
- ProvenHire handoff for simulation results is not fully productized.
- Admin is useful for demo/internal review, not a full recruiter analytics dashboard.
- Payment and inventory services duplicate patterns that should eventually become a shared simulation framework.

## Intended Next Steps

### Near Term

1. Keep the current demo green.
2. Avoid adding voice or new domains until the current two simulations are stable.
3. Refactor shared simulation primitives only when duplication becomes painful:
   - stage gates
   - artifact quality
   - report model
   - evidence ledger
   - summary persistence
   - test runner contract

### Product Next

1. Improve the payment environment toward `PAYMENT_RETRY_SAFETY_PRD.md`:
   - real database transaction boundary
   - webhook event queue
   - reconciliation worker
   - gateway event fixture
   - production logs/metrics

2. Build the simulation authoring schema:
   - scenario
   - starter files
   - public tests
   - hidden tests
   - stage requirements
   - scoring rubric
   - twist events
   - evidence ledger dimensions

3. Connect to candidate/job skill maps:
   - DSA results
   - Antigravity interview findings
   - target role requirements
   - selected high-signal simulation

### Strategic Next

The long-term product should become an engineering assessment operating system:

- interview-led
- simulation-grounded
- evidence-first
- role-specific
- adaptive
- honest about uncertainty

The win condition is not “AI asks hard questions.”

The win condition is:

> A hiring team can trust the report because it says exactly what the candidate proved, how they proved it, what remains untested, and what to test next.

## Security Notes

Several API keys were pasted during the original conversation for experimentation. Do not hardcode them and do not rely on chat-pasted keys as safe long-term credentials. Rotate any exposed keys before real use.

Keep secrets in runtime environment files only. Do not commit `.env` or `.env.local`.

## Mental Model To Resume Work

When returning to this project, hold this distinction:

- Antigravity interview measures claimed experience and reasoning under conversation.
- Engineering simulation measures applied judgment under a work surface.
- The report is the product artifact.
- Evidence truth matters more than interface sparkle.

If a new feature does not improve evidence quality, uncertainty honesty, or candidate measurement, it is probably not the next thing to build.
