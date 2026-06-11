# Antigravity Engineering Simulation PRD

## 1. Product Thesis

Antigravity should not only ask candidates what they know. It should place them inside a realistic engineering situation and observe how they think, decide, validate, communicate, recover, and prove safety.

The core bet is simple: strong engineers reveal themselves through work behavior, not just answer content. They form mental models, ask clarifying questions, isolate risk, make small safe changes, use tests as evidence, explain tradeoffs, and know what remains unproven. Weak candidates often know the vocabulary but fail when the situation requires execution.

The engineering simulation exists to measure that difference.

This is not meant to replace all interviewing. It is meant to become the highest-signal layer in the ProvenHire assessment stack, sitting alongside aptitude, DSA, and the existing Antigravity interview. DSA tests algorithmic fluency. The voice interview tests claimed experience and reasoning depth. The simulation tests applied engineering judgment under a realistic work surface.

In its best form, this becomes a job-specific engineering cockpit: the candidate enters a controlled but realistic incident, feature, debugging, migration, ML, infra, or architecture scenario; an AI interviewer sits beside them; the system observes both work and explanation; and the final report explains what the candidate proved, what they failed to prove, and what still remains uncertain.

## 2. Why We Started With Payment Retry Safety

The first simulation needed to be small enough to build end-to-end but meaningful enough to expose real engineering judgment.

Payment idempotency is a good V1 case because:

- It is technically concrete.
- It has real production stakes: duplicate charges are serious.
- It requires more than syntax changes.
- It tests mental model, state transitions, failure recovery, validation, and tradeoff explanation.
- It can be validated with deterministic tests.
- It maps to backend roles without needing a full database, gateway, container, or Kubernetes environment.

The intended candidate task is:

> A checkout endpoint can double-charge users when mobile clients retry after timeouts. Fix the handler so repeated requests with the same idempotency key do not create duplicate gateway charges, conflicting payloads are rejected, and gateway failures leave recoverable state.

This is deliberately not a LeetCode problem. It is a compact slice of production engineering.

## 3. Product Goal

Build one excellent, agent-verifiable engineering simulation that proves the product shape:

- The candidate sees a realistic engineering situation.
- The interviewer guides without giving away the answer.
- The candidate can think, speak, write, edit code, run tests, and revise.
- The system captures evidence from behavior, not only final answer.
- The final report separates proof from uncertainty.
- The entire flow can be tested by an agent browser, not only manually.

V1 should not try to generate many simulations. One high-quality simulation is more valuable than ten shallow ones.

## 4. Success Criteria

### Candidate Experience

A candidate should feel like they are in a serious engineering workbench, not a quiz page.

They should be able to:

- Understand the incident.
- Ask or write clarifying thoughts.
- Plan a safe patch.
- Edit code.
- Run tests.
- See meaningful failures.
- Improve the solution.
- Explain what is proven and what is not.
- Use voice or typed worklog without the product collapsing.

### Assessment Quality

The system should distinguish between:

- A candidate who knows the term “idempotency” but cannot implement it.
- A candidate who patches the happy path but misses conflict or failure handling.
- A candidate who passes tests by accident but cannot explain safety.
- A candidate who can reason, validate, and communicate like a production engineer.

### Demo Quality

For an investor/team demo, V1 should show:

- A premium command-center interface.
- Real code execution.
- A failing attempt.
- A successful correction.
- Voice-assisted interaction.
- Final scoring/reporting.
- Evidence timeline.
- A clear sense of future extensibility.

### Engineering Quality

The prototype must not be fake.

Minimum bar:

- Backend tests run real Node test cases.
- Candidate code is executed in a temp workspace.
- Malicious or broken code is constrained and times out.
- The browser e2e test operates the product like a candidate.
- Voice config failures are visible and graceful.
- The app cannot produce a confident final report without validation evidence.

## 5. What Was Implemented

### Frontend

Route:

- `/simulation`

Core UI:

- Left rail: case file, stage rail, constraints.
- Center: interviewer presence, voice controls, candidate worklog, code workbench.
- Right rail: evidence score, test results, score breakdown, telemetry.

Stages:

1. Understanding
2. Planning
3. Implementation
4. Validation
5. Reflection

Voice controls:

- Cartesia-backed `Speak Prompt`.
- Deepgram-backed `Record Audio Note`.
- Deepgram-backed `Upload Audio Note`.
- Gemini Live `Start Gemini Mic` path using backend-minted ephemeral tokens.

Workbench:

- Styled textarea editor for `payment.mjs`.
- Real test runner button.
- Finalize button with validation gates.

### Backend

Simulation APIs:

- `POST /api/simulation/start`
- `GET /api/simulation/state/{session_id}`
- `POST /api/simulation/interviewer_turn`
- `POST /api/simulation/run_tests`
- `POST /api/simulation/finalize`
- `GET /api/simulation/voice_status`
- `POST /api/simulation/transcribe_audio/{session_id}`
- `POST /api/simulation/gemini_live_token/{session_id}`
- dormant OpenAI realtime endpoint retained but not active by default

Test runner:

- Writes candidate code to temp directory.
- Runs Node tests against fake `PaymentStore` and `Gateway`.
- Returns structured pass/fail details.
- Handles syntax errors, timeout, and restricted file access.

Test cases:

- Missing idempotency key is rejected.
- First request creates one completed charge.
- Duplicate completed request returns original result without second charge.
- Duplicate pending request reuses existing attempt.
- Same key with different payload is rejected.
- Gateway timeout leaves recoverable non-completed state.

Scoring:

- Correctness/tests: 50%
- Validation/debug behavior: 20%
- Planning/mental model: 15%
- Reflection/tradeoffs: 10%
- Collaboration/interviewer responsiveness: 5%

Current scoring still leans too heavily on test results and note length. It is useful for a prototype but not yet a serious hiring rubric.

### Voice Stack

Current voice modes:

- Cartesia for prompt playback.
- Deepgram Flux for streaming-style transcription where possible.
- Nova fallback for batch audio compatibility where needed.
- Gemini Live with ephemeral tokens for live interviewer voice/mic path.

Important correction:

The first Gemini implementation was not good enough. It spoke but did not actually listen. The current version opens a browser mic stream and sends realtime audio chunks to Gemini Live through `sendRealtimeInput`. It reaches `gemini.open` and `gemini.listening`. It still needs manual human mic validation before I would call it production-grade.

## 6. Robustness Assessment

### What Is Real

The simulation spine is real:

- The page starts a session.
- Candidate work is stored.
- Code is edited in browser.
- Tests actually execute.
- Bad code fails.
- Good code passes.
- Final report uses backend state.
- Agent browser can complete the flow.

The validation layer is real:

- Runtime tests catch meaningful idempotency failures.
- The test result surface is visible to the candidate.
- The report references actual validation state.

The browser-agent verification loop is real:

- Playwright can operate the page.
- It can fill worklogs.
- It can submit bad and good patches.
- It can assert report output.
- It can capture screenshots.

The voice-adjacent layer is partially real:

- Cartesia prompt audio works when provider is reachable.
- Deepgram transcription works.
- Gemini Live token creation works.
- Gemini Live mic session opens and streams.

### What Is Still Thin

The editor is not yet a real IDE:

- No syntax highlighting.
- No file tree.
- No diff.
- No inline test failure mapping.
- No code intelligence.

The scoring is not yet high-trust:

- Planning and reflection are mostly length-based.
- It does not deeply judge quality of reasoning.
- It does not score candidate debugging sequence with enough nuance.
- It does not yet separate “passed tests” from “understands why tests prove safety.”

The simulation does not yet model true concurrency:

- It checks duplicate behavior sequentially.
- It does not simulate database transaction races.
- It does not enforce unique constraints through a real DB.
- It does not test lock/transaction design under parallel writes.

Voice is not yet the product’s strongest layer:

- Gemini Live requires manual validation with real human speech.
- Deepgram/Cartesia/Gemini add provider complexity.
- The UX between “recorded note,” “live mic,” and “typed worklog” needs clearer product semantics.

Final report is useful but not yet recruiter-grade:

- It lacks a narrative explanation of candidate behavior.
- It does not show a timeline of failed hypothesis -> test evidence -> corrected implementation.
- It does not quote the candidate’s reasoning.
- It does not clearly say what the candidate did not prove.

## 7. Standard I Should Have Set Earlier

The correct standard was:

> Nothing counts as implemented unless it survives a candidate-style browser run and proves the exact product claim.

That means:

- “Gemini Live integrated” only counts if it hears candidate audio and responds.
- “Assessment works” only counts if premature finalization is impossible.
- “Voice-led” only counts if the candidate can use voice naturally, not just hear a TTS prompt.
- “Simulation works” only counts if bad behavior fails and corrected behavior passes.
- “Report works” only counts if it is based on real evidence, not accidental button state.

I initially fell below that standard. I connected pieces and verified pieces, but I did not fully test the user-facing claim. That is the failure mode we need to guard against in this project generally: infrastructure can look impressive while the product moment still feels hollow.

The new standard should be:

1. Every feature has a product claim.
2. Every product claim has an agent-browser test.
3. Every agent-browser test includes at least one failure path.
4. Every report must be impossible to generate without evidence.
5. Every voice claim must be validated with actual input/output, not just provider connectivity.

## 8. Best-Form Product Vision

In the best version, Antigravity Simulation becomes an engineering assessment operating system.

The candidate does not enter a static test. They enter a role-specific engineering situation.

Examples:

- Backend: payment retries, API race conditions, migration rollback, queue retries, auth bugs.
- Frontend: broken state management, performance regression, accessibility defect, design-system refactor.
- ML/AI: model deployment failure, eval regression, prompt/tooling incident, data leakage issue.
- Infra: Kubernetes rollout failure, Docker build issue, Terraform drift, observability gap.
- Data: schema migration, pipeline backfill, deduplication, correctness under late-arriving events.

The simulation is built from three inputs:

1. Job role requirements.
2. Candidate skill map from aptitude, DSA, and Antigravity interview.
3. Claims/risks extracted from resume and prior rounds.

Then the system chooses the highest-signal simulation:

- Not random.
- Not generic.
- Not “build a TODO app.”
- A compact scenario that tests the candidate exactly where the job and candidate uncertainty intersect.

The best-form candidate journey:

1. Enters a live workbench.
2. AI teammate/interviewer briefs the incident.
3. Candidate asks clarifying questions.
4. Candidate explores files/logs/tests.
5. Candidate proposes plan.
6. Candidate edits code/config/system behavior.
7. Candidate runs validation.
8. System injects realistic failure or new evidence if appropriate.
9. Candidate revises.
10. Candidate reflects on tradeoffs and production rollout.
11. Final report maps observed behavior to job-relevant competencies.

The key product insight:

> The simulation should not only test whether the candidate gets the answer. It should reveal how they behave while approaching uncertainty.

## 9. Evidence Model

The product should observe evidence across multiple channels:

Code evidence:

- What changed.
- Whether the change is minimal or reckless.
- Whether it handles edge cases.
- Whether it preserves existing behavior.
- Whether it uses appropriate abstractions.

Validation evidence:

- Did the candidate run tests?
- Did they interpret failures correctly?
- Did they add or request missing tests?
- Did they distinguish unit proof from production proof?

Reasoning evidence:

- Did they build a causal model?
- Did they identify the actual risk?
- Did they ask useful clarifying questions?
- Did they sequence work safely?

Communication evidence:

- Did they explain tradeoffs?
- Did they respond to interviewer nudges?
- Did they admit uncertainty?
- Did they avoid overclaiming?

Production judgment evidence:

- Did they mention monitoring?
- Did they consider rollback?
- Did they know what remains untested?
- Did they understand concurrency, data integrity, or operational blast radius?

## 10. Report Vision

The final report should not be just a score.

It should answer:

- What did the candidate prove?
- What did they fail to prove?
- What did they only claim?
- What evidence supports the rating?
- What job competencies were tested?
- What competencies remain untested?
- Would this person be safe in the target role?

Ideal report structure:

- Executive recommendation.
- Competency map.
- Timeline of candidate behavior.
- Code/test evidence.
- Interviewer observations.
- Strengths.
- Risks.
- Unresolved questions.
- Suggested follow-up interview topics.

Example verdict style:

> Candidate demonstrates strong applied backend judgment around idempotency and failure recovery. They identified the gateway-before-persistence risk, patched the state machine, validated duplicate/completed/conflict/failure cases, and correctly noted that true concurrent DB writes remain unproven without transaction/unique-index testing. Strong hire signal for backend reliability work, with follow-up recommended on database isolation and production reconciliation.

## 11. Near-Term Roadmap

### V1.1 Hardening

- Replace textarea editor with Monaco.
- Add explicit “cannot finalize yet” checklist.
- Add visual validation timeline.
- Add clearer Gemini mic status.
- Add manual live mic QA checklist.
- Add report section for “what remains unproven.”
- Improve scoring beyond word counts.

### V1.2 Assessment Quality

- Add hidden concurrency test.
- Add candidate-authored test option.
- Add patch diff summary.
- Add structured rubric evaluator.
- Add event timeline scoring.
- Add “candidate used tests well/poorly” classifier.

### V1.3 Simulation Authoring

- Define simulation schema.
- Build scenario templates.
- Add role-to-simulation matching.
- Generate simulation from job description and candidate skill map.
- Add reviewer/critic agent to validate scenario quality.

### V2 Platform

- Real sandbox/microVM execution.
- Multi-file repo tasks.
- Logs, metrics, dashboards, fake incidents.
- Team-interviewer persona.
- Adaptive evidence injection.
- ProvenHire candidate skill map integration.

## 12. Open Questions

- Should Gemini Live be the main voice interviewer, or should Deepgram + Cartesia remain the default until Gemini mic quality is proven?
- How much candidate assistance is allowed before it contaminates assessment?
- Should tests be visible, hidden, or mixed?
- Should candidates be able to write their own tests?
- What is the right timebox for simulations by role level?
- How do we prevent candidates from gaming a small fixed scenario?
- What is the minimum sandbox required before public release?

## 13. Product Risks

### Risk: Beautiful Demo, Weak Signal

The UI can impress while the assessment remains shallow. The antidote is evidence-first reporting and hard validation gates.

### Risk: Over-Reliance On Tests

Passing tests is not the same as being a strong engineer. The system must score reasoning, validation behavior, and production judgment.

### Risk: Voice Complexity Distracts From Core Simulation

Voice is important, but if it becomes the main engineering burden before the simulation is strong, it slows the product. Voice should support assessment, not define it.

### Risk: Scenario Overfitting

One fixed challenge can be memorized. Long term, scenarios need variants, generated parameters, and hidden dimensions.

### Risk: Unsafe Code Execution

V1 temp-dir execution is acceptable only for internal prototype use. Public use requires proper container/microVM isolation.

## 14. Definition Of Done For This Prototype

The prototype is done when:

- A candidate can complete the full flow without developer help.
- They cannot finalize without running tests.
- A bad patch visibly fails.
- A good patch visibly passes.
- Voice input/output paths are understandable and stable enough for demo.
- The final report is evidence-based.
- Browser-agent e2e passes.
- Manual human demo produces no embarrassing state transitions.

Current status:

- Simulation spine: working.
- Test runner: working.
- Agent e2e: working.
- Premature finalization: fixed.
- Deepgram audio note: working.
- Gemini Live mic: wired, opens, streams, needs final manual human speech validation.
- Scoring/report: useful prototype, not yet final hiring-grade.

## 15. North Star

The north star is not “AI interviewer asks harder questions.”

The north star is:

> A hiring system that watches engineers operate inside realistic work, measures the evidence they create, and tells companies what the candidate has actually proven.

That is the product worth building.

