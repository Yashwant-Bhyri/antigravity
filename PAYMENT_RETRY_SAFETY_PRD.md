# Payment Retry Safety Simulation PRD

## 1. Simulation Thesis

Payment retry safety is one of the cleanest ways to test real backend engineering judgment.

It looks small on the surface: prevent duplicate charges when clients retry a payment request. But underneath that surface are the exact skills that separate production engineers from keyword engineers:

- idempotency design
- state-machine thinking
- transaction boundaries
- database uniqueness
- external gateway failure handling
- concurrency safety
- reconciliation
- observability
- rollback planning
- customer-impact reasoning

The best version of this simulation should not merely ask a candidate to “add an idempotency key.” That is too shallow. A strong candidate must prove that money movement is safe across retries, timeouts, process crashes, duplicate requests, payload conflicts, database races, and gateway uncertainty.

The goal is to simulate the kind of work a backend engineer would actually do on a checkout/payments team during or after a duplicate-charge incident.

## 2. Target Roles

This simulation is most relevant for these roles:

### Backend Software Engineer

Primary signal:

- API correctness
- state transitions
- idempotency
- error handling
- tests
- code quality

This is the default version.

### Senior Backend / Platform Engineer

Primary signal:

- concurrency safety
- transactional design
- operational rollout
- observability
- reconciliation
- system boundaries

This version includes database-level races, outbox/reconciliation patterns, and incident response.

### Payments / Fintech Engineer

Primary signal:

- money movement safety
- gateway semantics
- ledger consistency
- customer-impact minimization
- auditability

This version includes ledger rows, authorization/capture semantics, refund/void considerations, and reconciliation reports.

### Site Reliability / Production Engineer

Primary signal:

- incident diagnosis
- metrics/logs/traces
- blast-radius control
- rollback
- alert design

This version starts from production telemetry and asks the candidate to diagnose and mitigate before patching.

### Data Engineer / Analytics Engineer

Secondary but possible variant:

- duplicate transaction detection
- reconciliation pipeline
- late-arriving events
- correctness of financial reporting

This version focuses less on API patching and more on discovering duplicate charges, reconciling gateway exports, and producing a trustworthy financial correction dataset.

## 3. Candidate Narrative

The candidate joins a checkout team mid-incident.

Mobile clients retry `POST /payments` when the network times out. The service currently creates a payment row, calls the payment gateway, and marks the row completed. Under retries and process crashes, some customers receive duplicate gateway charges.

The candidate is asked to:

1. Understand the incident.
2. Identify where duplicate money movement can happen.
3. Design an idempotency-safe patch.
4. Implement the patch.
5. Run tests and debug failures.
6. Handle a production-grade twist.
7. Explain rollout, monitoring, reconciliation, and remaining risk.

The simulation should feel like a real engineering exercise, not a puzzle.

## 4. Elite Version Product Goal

Build a simulation that can distinguish:

- Someone who can say “use idempotency keys.”
- Someone who can implement idempotency in a happy-path handler.
- Someone who understands database constraints and race conditions.
- Someone who understands gateway uncertainty and reconciliation.
- Someone who can operate safely under production incident pressure.

The elite version should test both correctness and engineering maturity.

The question is not:

> Can the candidate pass a unit test?

The question is:

> Would this candidate be safe to put on a payments backend team?

## 5. Environment Design

### V1 Current Environment

Current prototype:

- single editable `payment.mjs`
- fake in-memory `PaymentStore`
- fake `Gateway`
- Node test runner
- visible tests
- staged worklog
- final scoring

This proves the basic product loop.

### Elite Environment

The elite version should use a realistic mini-system:

```text
payment-sim/
  src/
    api/
      payments.ts
    db/
      schema.sql
      migrations/
    services/
      paymentService.ts
      idempotencyService.ts
      gatewayClient.ts
      ledgerService.ts
      reconciliationService.ts
    workers/
      paymentRetryWorker.ts
      reconciliationWorker.ts
    observability/
      metrics.ts
      logger.ts
  tests/
    public/
    hidden/
    chaos/
  fixtures/
    gateway-events.json
    production-logs.jsonl
    retry-traffic.json
```

Runtime dependencies:

- Node or Go service
- PostgreSQL container
- Redis container for locks/short-lived cache if role variant requires it
- fake payment gateway service
- fake webhook service
- test harness that can generate concurrent traffic
- logs/metrics/traces visible in the UI

The candidate should not need to manage Docker manually. The simulation workbench should start the environment, show service health, and expose the relevant files/tests.

## 6. Core System Model

The simulated service contains:

### Payment API

Endpoint:

```http
POST /payments
Idempotency-Key: <client-operation-id>
```

Request:

```json
{
  "user_id": "u_123",
  "amount_cents": 4200,
  "currency": "USD",
  "payment_method_id": "pm_abc"
}
```

Response:

```json
{
  "payment_id": "pay_123",
  "status": "completed",
  "gateway_charge_id": "ch_456"
}
```

### Payment States

Recommended state machine:

```text
requested
  -> pending_gateway
  -> completed
  -> failed_recoverable
  -> failed_terminal

completed
  -> refunded
  -> disputed
```

The candidate does not have to invent this exact naming, but must preserve the core invariant:

> A single idempotency key for the same payload must map to one logical payment operation and at most one successful external charge.

### Database Tables

Minimum tables:

```sql
payments (
  id uuid primary key,
  user_id text not null,
  amount_cents int not null,
  currency text not null,
  idempotency_key text not null,
  request_fingerprint text not null,
  status text not null,
  gateway_charge_id text,
  failure_reason text,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique (idempotency_key)
)
```

```sql
payment_attempts (
  id uuid primary key,
  payment_id uuid references payments(id),
  gateway_request_id text,
  gateway_charge_id text,
  status text not null,
  error_code text,
  created_at timestamptz not null
)
```

```sql
ledger_entries (
  id uuid primary key,
  payment_id uuid references payments(id),
  type text not null,
  amount_cents int not null,
  currency text not null,
  created_at timestamptz not null
)
```

Senior/fintech variant adds:

- gateway webhook events
- reconciliation imports
- refunds/voids
- audit log
- outbox table

## 7. Candidate Tasks

### Stage 1: Understand

The candidate receives:

- incident brief
- simplified endpoint code
- production symptoms
- selected logs
- failing customer examples

They must identify:

- where duplicate charges can happen
- what idempotency key means
- what payload conflicts are
- what gateway uncertainty means
- what data they need before patching

Expected strong behavior:

- asks whether gateway supports idempotency
- asks whether idempotency key is client-generated or server-generated
- checks current DB uniqueness
- asks how retries are generated
- distinguishes duplicate request from duplicate charge
- identifies process-crash window

Weak behavior:

- says “use Redis lock” without explaining failure modes
- only checks if key exists after gateway call
- ignores conflicting payloads
- treats timeout as failure even though gateway may have charged

### Stage 2: Plan

Candidate must propose:

- persistence-before-gateway strategy
- uniqueness/transaction strategy
- conflict detection
- pending-state handling
- timeout recovery
- test plan
- monitoring plan

Strong plan:

```text
1. Require idempotency key.
2. Compute request fingerprint from amount/currency/payment_method/user.
3. In a transaction, insert payment with unique idempotency key or load existing.
4. If existing fingerprint differs, reject conflict.
5. If completed, return original result.
6. If pending, avoid duplicate gateway charge; either return pending or resume via safe attempt semantics.
7. Call gateway with gateway-level idempotency key when available.
8. Persist gateway charge id before returning completed.
9. If gateway times out, mark recoverable/unknown and reconcile.
10. Add metrics and reconciliation.
```

### Stage 3: Implement

Candidate edits code.

Basic role:

- `paymentService.ts`
- tests

Senior role:

- migration
- transaction logic
- gateway client idempotency
- reconciliation worker
- observability

Fintech role:

- ledger integrity
- audit trail
- reconciliation report

SRE role:

- mitigation script
- alert
- dashboard
- rollback plan

### Stage 4: Validate

Candidate runs public tests first.

Public tests check:

- missing idempotency key
- first request succeeds
- duplicate completed request returns same result
- payload conflict rejected
- gateway failure does not fake completion

Hidden tests check:

- concurrent duplicate requests
- process crash after gateway charge before DB update
- gateway timeout but charge later appears in webhook
- DB unique constraint race
- retry after recoverable failure
- same idempotency key across users
- request fingerprint canonicalization
- currency mismatch
- amount precision

Chaos tests check:

- gateway returns 500 after charging
- gateway returns timeout but webhook arrives
- DB transaction deadlock
- worker retry duplicates events
- delayed webhook arrives before API retry

### Stage 5: Production Twist

The simulation injects new evidence after an initial patch.

Examples:

#### Twist A: Gateway Timeout Ambiguity

The candidate sees:

```text
gateway.charge() timed out
customer retried
gateway webhook later says first charge succeeded
```

Strong candidate:

- does not mark timeout as terminal failure
- creates recoverable/unknown state
- reconciles webhook to payment
- avoids second charge

#### Twist B: Concurrent Retry Race

Two identical requests arrive within 12 ms.

Strong candidate:

- relies on DB uniqueness/transaction, not only in-memory check
- handles unique violation by loading existing row
- avoids double gateway call

#### Twist C: Payload Conflict

Same idempotency key used for `$42 USD` and `$99 USD`.

Strong candidate:

- rejects conflict
- does not create new payment
- does not call gateway

#### Twist D: Process Crash Window

Service crashes after gateway charge succeeds but before DB update.

Strong candidate:

- uses gateway idempotency key if available
- records attempt before call
- reconciliation can recover
- does not pretend code alone can solve all uncertainty

### Stage 6: Reflection

Candidate must explain:

- what is proven by tests
- what remains untested
- how they would deploy
- what metrics matter
- how to reconcile historical duplicates
- what code they want reviewed
- what product/customer impact exists

## 8. Test Design

### Public Tests

Public tests are visible and meant to guide the candidate.

They should catch obvious issues:

- missing key
- duplicate completed retry
- conflict
- timeout state
- one charge only

### Hidden Tests

Hidden tests protect assessment quality.

They should catch:

- hardcoded behavior
- non-transactional check-then-insert
- duplicate gateway calls under concurrency
- incorrect pending handling
- false completion on timeout
- no fingerprint conflict

### Behavioral Tests

These do not only test final code.

They inspect:

- did candidate run tests before finalizing
- did candidate revise after failures
- did candidate mention monitoring
- did candidate identify remaining uncertainty
- did candidate overclaim safety

### Mutation Tests

The harness can mutate:

- gateway latency
- duplicate request timing
- DB isolation behavior
- webhook ordering
- failure after charge

Strong solutions survive more mutations.

## 9. Elite Scoring Rubric

### Correctness: 35%

Measures:

- idempotency behavior
- conflict detection
- no duplicate charge
- proper state transitions
- gateway failure handling
- concurrency safety

### Validation Behavior: 20%

Measures:

- runs tests early
- interprets failures correctly
- revises based on evidence
- understands hidden risks
- does not finalize without validation

### Production Judgment: 20%

Measures:

- transaction/unique constraint understanding
- reconciliation plan
- observability
- rollout safety
- customer impact handling

### Communication / Collaboration: 10%

Measures:

- asks clarifying questions
- explains assumptions
- responds to interviewer nudges
- admits uncertainty

### Code Quality: 10%

Measures:

- minimal patch
- readable state handling
- no broad rewrites
- no fragile hacks

### Integrity / Calibration: 5%

Measures:

- does not overclaim
- states what remains unproven
- distinguishes simulated proof from production proof

## 10. Role-Specific Variants

## Variant A: Backend Software Engineer

### Goal

Fix the API handler safely.

### Candidate Work

- edit service code
- use store/gateway APIs
- pass runtime tests
- explain edge cases

### Key Signals

- knows idempotency semantics
- avoids second charge
- handles conflict
- handles timeout
- writes minimal correct patch

### Hidden Test

Concurrent duplicate request.

### Strong Verdict

Candidate can safely implement backend payment idempotency under standard retry conditions.

## Variant B: Senior Backend / Platform Engineer

### Goal

Make the payment operation safe under concurrency and crash recovery.

### Candidate Work

- add DB unique constraint
- use transaction
- handle unique violation
- add payment attempt row
- use gateway idempotency key
- add reconciliation worker

### Key Signals

- understands DB as source of truth
- knows check-then-insert race
- handles crash windows
- distinguishes API idempotency from gateway idempotency
- designs operational recovery

### Hidden Test

50 concurrent retries plus gateway timeout ambiguity.

### Strong Verdict

Candidate can own production-grade payment reliability work.

## Variant C: Payments / Fintech Engineer

### Goal

Protect financial correctness and auditability.

### Candidate Work

- preserve ledger invariants
- reconcile gateway exports
- identify duplicate historical charges
- propose refund/void workflow
- produce audit-safe status transitions

### Key Signals

- does not treat charge as just a boolean
- understands ledger vs gateway state
- thinks about customer correction
- thinks about audit trails

### Hidden Test

Gateway shows two charges, internal ledger shows one completed payment.

### Strong Verdict

Candidate understands payment correctness beyond API success.

## Variant D: SRE / Production Engineer

### Goal

Diagnose and mitigate active duplicate-charge incident.

### Candidate Work

- inspect logs/metrics
- identify duplicate charge pattern
- disable risky retry path or gate rollout
- add alert
- design backfill/reconciliation
- coordinate rollback

### Key Signals

- reduces blast radius first
- uses evidence
- avoids speculative patching during incident
- communicates customer impact

### Hidden Test

Metrics are misleading: API error rate looks low, but gateway duplicate rate is high.

### Strong Verdict

Candidate can operate safely during a high-stakes incident.

## Variant E: Data / Reconciliation Engineer

### Goal

Find and reconcile duplicate payment outcomes.

### Candidate Work

- compare internal payments table with gateway export
- identify duplicate charges by customer/payment method/time window
- produce correction dataset
- flag ambiguous cases
- design ongoing reconciliation job

### Key Signals

- handles late events
- avoids false positives
- understands financial reporting correctness
- creates auditable output

### Hidden Test

Two legitimate separate purchases look similar to duplicates.

### Strong Verdict

Candidate can build trustworthy reconciliation pipelines for financial systems.

## 11. UI / Workbench Requirements

### Candidate View

Must include:

- case brief
- incident timeline
- file explorer
- code editor
- terminal/test output
- logs panel
- metrics panel
- gateway event stream
- interviewer voice/chat
- worklog
- validation checklist

### Evidence View

Must show:

- current score is provisional
- tests passed/failed
- hidden tests not revealed
- unresolved production risks
- what stage candidate is in
- whether finalize is locked

### Interviewer Behavior

The interviewer should:

- ask one question at a time
- not give solution code
- nudge toward evidence
- ask for production implications
- challenge overclaims
- recognize strong reasoning
- move the candidate onward when enough evidence is collected

Bad interviewer behavior:

- “Great job!” after shallow answers
- giving away “use unique constraint”
- drilling one issue forever
- allowing finalization without validation
- turning the simulation into trivia

## 12. Data And Telemetry

Capture:

- code snapshots
- diffs
- test runs
- failed test names
- time between failure and fix
- voice transcript
- typed worklog
- stage transitions
- interviewer prompts
- candidate final reflection
- hidden test outcome
- final report

Derived signals:

- validation discipline
- debugging persistence
- overclaim rate
- evidence quality
- production-risk awareness
- code churn
- time-to-first-test
- time-to-green

## 13. Final Report Requirements

The report should include:

### Executive Summary

Example:

> Candidate fixed core payment retry idempotency and passed visible plus hidden duplicate-request tests. They correctly rejected conflicting payloads and avoided fake completion on timeout. They did not fully address crash recovery after gateway success before DB update, so production readiness depends on adding gateway reconciliation.

### Evidence Timeline

Example:

```text
03:12 Candidate identified gateway-before-persistence risk.
05:44 Candidate proposed pending state before gateway call.
08:10 First patch failed concurrent duplicate hidden test.
11:32 Candidate added DB uniqueness handling.
13:05 Public and hidden tests passed.
15:20 Candidate correctly noted reconciliation remains out of scope.
```

### Competency Scores

- API correctness
- concurrency safety
- payment domain judgment
- validation behavior
- operational maturity
- communication

### What Candidate Proved

- implemented basic idempotency
- avoided duplicate completed retries
- rejected conflicts
- handled gateway timeout as recoverable

### What Candidate Did Not Prove

- real DB isolation under production load
- gateway webhook reconciliation
- refund handling for historical duplicates
- rollout/backfill plan

### Hiring Signal

Clear recommendation:

- Strong hire signal
- Hire signal with follow-up
- Mixed signal
- Weak signal
- No hire signal

## 14. Anti-Gaming Design

To avoid memorized solutions:

- randomize gateway behavior
- randomize visible vs hidden tests
- vary schema names
- vary gateway semantics
- vary whether gateway supports idempotency
- vary incident evidence
- generate role-specific twists
- require reflection grounded in actual run evidence

Candidate should not pass by pasting a known solution unless they also demonstrate reasoning and production awareness.

## 15. External Integrations

Possible integrations:

- Stripe-like fake gateway
- Postgres container
- Redis container
- OpenTelemetry traces
- Grafana-like metrics panel
- Log stream with JSONL search
- Git-style diff viewer
- Monaco editor
- Docker/microVM sandbox
- LLM interviewer
- Deepgram/Gemini/Cartesia voice layer

Public production version must use isolated execution:

- container per session minimum
- microVM preferred
- no host filesystem access
- network egress controlled
- time/memory limits
- artifact cleanup

## 16. Elite Hidden Test Examples

### Test: Concurrent Idempotency Race

```text
Send 25 identical requests with same idempotency key.
Expected:
- one payment row
- one gateway charge
- all responses map to same payment
```

### Test: Conflict Under Race

```text
Two requests use same key but different amount.
Expected:
- original request wins if inserted first
- conflicting request rejected
- no second gateway charge
```

### Test: Gateway Timeout With Later Webhook

```text
Gateway times out, then sends charge.succeeded webhook.
Expected:
- payment not marked completed before evidence
- webhook links to existing attempt
- retry does not create second charge
```

### Test: Process Crash Window

```text
Crash after gateway charge succeeds, before DB completed update.
Expected:
- reconciliation can recover status
- retry does not blindly create second charge
```

### Test: Historical Duplicate Reconciliation

```text
Gateway export has duplicate charges for same idempotency key.
Expected:
- duplicates identified
- ambiguous cases flagged
- correction dataset produced
```

## 17. What “Excellent Candidate” Looks Like

An excellent candidate says or demonstrates:

- “The idempotency key identifies the client operation, not the payment row.”
- “Same key with different payload must be a conflict.”
- “The database needs a unique constraint; app-level check is not enough.”
- “Gateway timeout does not mean no charge happened.”
- “We need a pending or unknown state.”
- “If the gateway supports idempotency keys, pass ours through.”
- “Completion requires persisted gateway evidence.”
- “A real production rollout needs metrics and reconciliation.”
- “These tests prove the simulated contract, but not all concurrency or gateway-reconciliation cases.”

They do not overclaim.

That last part matters.

## 18. What “Weak Candidate” Looks Like

A weak candidate:

- only checks if key exists after charging
- stores idempotency in memory
- ignores conflicting payloads
- marks timeout as failed/completed incorrectly
- creates a new row on retry
- passes happy path but fails duplicate edge cases
- never runs tests
- cannot explain what remains unproven
- says “use Redis lock” without considering lock expiry/crash
- says “just retry” around money movement

## 19. Product Readiness Levels

### Level 1: Demo

- single file
- fake store/gateway
- public tests
- basic report

Current prototype is around here, with some Level 2 pieces.

### Level 2: Serious Internal Assessment

- multi-file repo
- hidden tests
- better scoring
- real Postgres container
- role-specific rubric
- manual review possible

### Level 3: External Pilot

- sandboxed execution
- variant generation
- stable voice layer
- recruiter-grade reports
- anti-gaming protection
- session replay

### Level 4: Category-Defining Product

- job-specific generated simulations
- candidate skill-map targeting
- multi-round evidence fusion
- adaptive scenario twists
- enterprise reporting
- calibrated hiring recommendations

## 20. Near-Term Implementation Plan For This Specific Simulation

### Step 1: Fix V1 Integrity

- hard block premature finalize
- visible checklist for missing requirements
- final report only after validation
- manual Gemini mic validation

### Step 2: Add Real DB Variant

- Postgres container
- schema migration
- unique idempotency key
- transaction test
- concurrent request harness

### Step 3: Add Gateway Ambiguity

- fake gateway service
- timeout-after-charge mode
- delayed webhook
- retry worker

### Step 4: Add Hidden Tests

- concurrent duplicates
- conflict race
- timeout recovery
- process crash window

### Step 5: Improve Report

- evidence timeline
- code diff
- candidate quote extraction
- hidden vs visible test summary
- “what remains unproven”

### Step 6: Role Variants

- backend variant
- senior backend variant
- payments/fintech variant
- SRE incident variant
- data reconciliation variant

## 21. Final Product Standard

The elite standard for this payment simulation is:

> A strong candidate should leave behind enough evidence that a payments engineering manager would trust the report even without watching the whole session.

That means:

- code evidence
- test evidence
- concurrency evidence
- operational reasoning
- communication evidence
- explicit uncertainty

The best version does not simply ask “did they know idempotency?”

It answers:

> Can this person safely work on systems where bugs move real money?

