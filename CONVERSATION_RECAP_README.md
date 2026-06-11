# Antigravity Conversation Recap README

**Date:** 2026-05-26  
**Purpose:** Re-entry document for Yash or any AI teammate returning after a break.  
**Scope:** This recaps the product conversation, codebase analysis, real-session findings, philosophy evolution, simulation pivot, and current open direction. It is not a replacement for `AGENTS.md`, `PROJECT_STATE.md`, `problem.md`, or the PRDs.

---

## 1. One-Line Summary

Antigravity started as a real-time adversarial voice interview engine, proved that its analysis layer can detect real weakness and resume inflation, then evolved toward a broader thesis: measure authentic engineering substance through better conversational policy and, eventually, realistic engineering simulations.

The most important product shift:

> From "prove whether the candidate is lying" to "measure what the candidate can actually do, under calibrated pressure, with evidence."

---

## 2. What Antigravity Was Originally

The original product identity was:

- A voice-native AI technical interview system.
- Resume-grounded and adversarial.
- Designed to probe ownership, reasoning depth, contradictions, and failure boundaries.
- Built around the loop: user speaks -> Deepgram STT -> backend agents -> follow-up -> Cartesia/ElevenLabs TTS.
- Intended to produce a final HIRE / MAYBE / NO HIRE report.

The early philosophy was aggressive:

> Probe -> Break -> Analyze -> Adapt.

This produced strong negative-signal detection, but also created a risk: the system could become an investigation tool more than an interview system.

---

## 3. Current Technical Shape Of The Interview System

The interview system has these major components:

- **Frontend:** Next.js App Router in `app/`, shared UI components in `components/`, browser audio control in `lib/audio.ts`.
- **Backend:** FastAPI in `backend/main.py` and `backend/api/routes.py`.
- **State:** Redis-backed session state through `backend/state/session_manager.py`.
- **STT:** Deepgram browser-side SDK. Backend `asr_service.py` is historical/dead code.
- **TTS:** Cartesia-first policy, ElevenLabs fallback only.
- **LLMs:** OpenRouter-routed model tiers:
  - small: Haiku-class extraction/adaptation
  - medium: Sonnet-class weakness, discrepancy, follow-up
  - large: DeepSeek R1 / larger reasoning path for final evaluation
- **Core orchestration:** `backend/services/orchestrator.py`.
- **Interview map:** `backend/services/interview_map.py`.
- **Agents:** resume, weakness, discrepancy, reasoning behavior, follow-up, evaluation, concept/application support.

Runtime architecture became a two-track system:

1. **Fast path:** serve the next question quickly, ideally from staged analysis.
2. **Slow/background path:** while the candidate answers, run weakness/discrepancy/reasoning/follow-up generation and stage the next turn.

The important invariant:

> Canonical state should be mutated only when staged analysis is applied, not by speculative background jobs.

---

## 4. What Worked Better Than Expected

The strongest parts of the system are real.

### Weakness Detection

The `WeaknessAgent` can identify precise implementation gaps:

- Candidate names Redis `SET NX` but cannot explain the race condition it solves.
- Candidate describes creating a record before calling a payment gateway but cannot reason about process crash between those steps.
- Candidate understands a term conceptually but cannot execute it in a real failure path.

This is not just keyword matching. It often lands on issues a senior human interviewer would also catch.

### Discrepancy Detection

The discrepancy path is strong in adversarial cases. In the Mahesh session, the system caught direct contradictions:

- Resume claimed maker-checker workflows; candidate admitted they were not implemented.
- Resume claimed fine-grained RBAC; candidate admitted it was not implemented.
- Candidate described trusting client-provided email for auth, exposing a real security flaw.

### Final Evaluation

The final verdicts were generally calibrated:

- Praveen: MAYBE / 6.5, conceptual but shallow.
- Mahesh: NO HIRE / 2.0, confirmed contradictions and weak security reasoning.

The evaluation layer is not perfect, but it was not the main failure point.

### Trajectory Map Generation

When the map is good, it creates high-quality interview probes:

- Surface / mechanism / boundary questions.
- Resume-specific claims.
- Critic pass that can identify weak or generic probes.

The problem is less map generation and more runtime use of the map.

---

## 5. What Broke In Real Sessions

The real session exports became the turning point.

Important files:

- `backend/data/session_exports/ced237fe-624e-401f-b55a-8404ae1ae6a3.json`
- `backend/data/session_exports/5ce15b7c-a0c1-4731-b0e8-90acab38266c.json`
- `backend/data/session_exports/3b362657-5f4b-4937-a930-44cc1009ec54.json`
- `backend/data/session_exports/3e95257c-f290-4546-9a8e-e22430f2cb9d.json`
- `backend/data/session_exports/3dfa958d-9395-4c7c-a9bc-d3a9ff747f78.json`

### C-1: Resume Parser Failure

The resume parser silently produces bad structured state:

- `skills: []`
- `projects: []`
- `experiences: []`
- claims cut off mid-bullet
- contact info and education misclassified as projects
- `CI/CD` split into `CI` and `CD`

The interview map survives because it reads raw resume text. But follow-ups, tiering, ownership classification, and resume context often receive garbage.

### C-2: Focus Inference Broken

Completed sessions showed:

```json
"focus_key": "",
"focus_label": ""
```

on turn after turn.

This breaks:

- map traversal
- coverage tracking
- bridge routing
- speculative cache lookup
- focus-area exhaustion detection

The active question packet often already has the correct focus key. The system should propagate it instead of relying only on weak re-inference.

### C-3: Bridge Never Fires

The Mahesh session spent all 15 turns around CMS/RBAC and never reached:

- Golang microservices
- Redis caching
- CI/CD
- AWS/Grafana
- LLM automation

Once a claim is sufficiently collapsed, the interview should move on. Re-proving the same fraud is not the same as measuring the candidate.

### C-4: Trajectory Map Underused

In Praveen's full 15-turn session, many questions came from `sprint_seed` rather than the carefully built map.

That means the product spent expensive LLM calls building a map, then often fell back to improvised questions at runtime.

### STT / Voice Noise

Some transcripts contain speech artifacts and unclear phrases. The LLMs are resilient, but the system has no explicit STT confidence or transcript-noise handling layer. That creates fairness and measurement risk.

---

## 6. Product Philosophy Shift

The biggest conceptual shift came from the product conversation around adversariality.

Old framing:

> Be adversarial. Break claims. Catch fraud.

New framing:

> Measure technical substance. Use adversariality when it improves evidence.

Adversariality remains valuable. It exposes inflated claims and tests pressure behavior. But it should be a tool, not the product's whole personality.

The better loop is:

```text
Invite -> Ground -> Probe -> Stress -> Recover -> Bridge -> Compare -> Conclude
```

The interview should:

- elicit authentic signal
- ground claims in concrete artifacts
- stress the claim when needed
- stop drilling when evidence is enough
- move across the candidate's skill surface
- distinguish "not tested" from "tested and failed"

The new product identity is closer to:

> A technical substance measurement system that uses conversation, pressure, and simulation to extract evidence of real engineering ability.

---

## 7. The Three-Layer Question Model

The design docs introduced a key framework:

1. **Technical layer:** what capability or claim is being tested?
2. **Communication layer:** how is the question phrased?
3. **Psychological layer:** what state does it induce in the candidate?

The psychological layer is not decoration. It changes what the system can measure.

If the system makes candidates defensive, confused, or cornered too early, it may measure "performance under an awkward AI interface" instead of engineering substance.

Good question design is not only about technical relevance. It is also about whether the question creates a path for the candidate to surface real memory, reasoning, tradeoffs, and uncertainty.

Example shift:

Bad/extractive:

```text
What broke first?
```

Better/invitational but still technical:

```text
At what point did this stop being a normal CRUD feature and start creating real engineering pressure? What changed in the system at that point?
```

The good version invites narrative, then demands concrete technical grounding.

---

## 8. LLM As Renderer, System As Interviewer

This became a central architectural principle.

The LLM should not be trusted to "be a good interviewer" from prompt text alone.

The system should decide:

- active claim
- claim status
- evidence level
- route mode
- pressure level
- probe budget
- focus exhaustion
- breadth requirement
- whether to challenge, bridge, recover, or explore strength

Then the LLM should render the selected move into a natural question.

In other words:

```text
Policy engine decides the interview move.
LLM renders the language.
```

This is the path away from prompt-only behavior and toward a real interview operating system.

---

## 9. Proposed Conversation Policy Layer

Before any RLHF or preference learning, the system needs clean deterministic primitives:

### Claim Ledger

Every resume claim should have:

- claim text
- source span
- domain/focus area
- status: untested, supported, weak, contradicted, inconclusive
- evidence snippets
- probe count
- confidence

### Question Modes

Questions should be selected from modes such as:

- invitation
- grounding
- mechanism
- boundary
- contradiction
- recovery
- bridge
- breadth
- close
- explore strength

### Probe Budget

No claim should be probed indefinitely. Once a claim is sufficiently weak or contradicted, mark it and move on.

### Pressure Gauge

Track cumulative interviewer pressure:

- challenge routes
- contradiction routes
- boundary probes
- repeated same-topic pressure

When pressure gets too high, force recovery or curiosity mode.

### Coverage Governor

The system must know what it has not tested. A candidate report should be honest:

- tested and strong
- tested and weak
- contradicted
- not tested

Untested should not silently become weak.

---

## 10. RLHF / Preference Learning Discussion

The design docs propose pairwise preference learning over conversational trajectories:

```text
resume snippet -> question A -> candidate answer -> follow-up B
```

Evaluators compare two possible trajectories along:

- technical signal
- conversational flow
- psychological openness
- escalation quality
- human plausibility
- richness of candidate response

The conclusion:

- Directionally right.
- Not the immediate first fix.

Reason:

> Preference learning over broken state will optimize style over bad routing.

First fix:

- resume parsing
- focus persistence
- bridge routing
- claim ledger
- pressure and coverage policy
- usage telemetry

Then collect pairwise preference data on top of stable primitives.

---

## 11. Engineering Simulation Pivot

The simulation thesis was introduced as a longer-term and higher-signal direction:

> Do not only ask candidates what they know. Put them inside realistic engineering situations and observe how they work.

This is a different product surface from the voice interview, but it became increasingly important.

The reasoning:

- Modern engineering is less about recalling trivia and more about debugging, validating, planning, and operating systems.
- AI changes engineering. Code generation is abundant; judgment and verification are scarce.
- Strong engineers reveal themselves through workflow behavior:
  - mental model formation
  - clarifying questions
  - safe patch planning
  - test-driven validation
  - debugging loops
  - tradeoff explanation
  - observability and rollout thinking

The simulation platform is not just "better questions." It is a controlled engineering workbench.

---

## 12. Payment Retry Safety Simulation

The first simulation slice is payment idempotency / retry safety.

Main PRDs:

- `SIMULATION_PRD.md`
- `PAYMENT_RETRY_SAFETY_PRD.md`

Core scenario:

> Mobile clients retry `POST /payments` after timeouts. The current service can create duplicate gateway charges. The candidate must make the endpoint idempotent and prove safety.

Why this case is strong:

- small enough for V1
- production-relevant
- deterministic tests possible
- tests state-machine thinking
- exposes shallow "just use idempotency key" answers
- maps well to backend engineering

The simulation evaluates:

- understanding
- planning
- implementation
- validation
- reflection
- code correctness
- reasoning quality
- authorship signal
- production gaps

Implemented capabilities include:

- `/simulation` frontend route
- staged workbench
- editable code
- Node test runner
- payment fake store/gateway
- backend-owned stage gates
- final report
- evidence ledger
- Playwright e2e flows
- admin listing
- Redis summary rows
- inventory simulation parity work

Important caveat:

> V1's Node permission sandbox is acceptable for internal prototype validation, but public arbitrary code execution still needs a stronger container or microVM boundary.

---

## 13. Evidence Ledger Direction

The simulation work introduced a stronger reporting model:

Instead of only giving a score, the report should say:

- what was proved by runtime tests
- what was claimed only in notes
- what remains unproven
- where authorship is uncertain
- what production gap should be tested next

This evidence-ledger idea applies back to the voice interview too.

The best version of Antigravity should not say:

```text
Candidate is weak.
```

It should say:

```text
Claim A was contradicted.
Claim B was supported at surface level only.
Dimension C was never tested.
Dimension D showed strong causal reasoning.
Next best probe is X.
```

---

## 14. Cost And Token Analysis

An OpenRouter CSV was analyzed for session usage.

Important conclusion:

> OpenRouter usage is internal text-agent usage, not voice/audio usage.

For one full 15-turn interview (`ced237fe-624e-401f-b55a-8404ae1ae6a3`), the likely cost profile was:

- all-in map prep + live interview: about `$1.14`
- live interview only: about `$0.85`
- map/prep before interview start: about `$0.29`

The internal text-agent usage was much larger than the actual spoken text boundary:

- candidate answers / STT transcript: about 10,312 chars, about 1,653 words
- AI questions / TTS text: about 2,811 chars, about 495 words
- internal live LLM text usage: hundreds of thousands of prompt/output tokens

Important architectural rule:

> Voice at the edge. Text inside the brain.

In a future voice-agent architecture:

- STT/audio tokens should be spent only on user speech.
- TTS/audio tokens should be spent only on final spoken assistant output.
- Internal agents should communicate as text/JSON.

Do not route every internal agent through a voice model.

---

## 15. Current Product Direction

There are now two related but distinct product directions:

### A. Voice Interview System

Purpose:

- resume-grounded live interview
- detect inflated claims
- measure reasoning depth
- produce recruiter report

Near-term needs:

- fix critical routing/state bugs
- improve conversational policy
- add claim ledger
- add coverage honesty
- improve cost/usage telemetry
- stop over-tunneling
- follow strengths as well as weaknesses

### B. Engineering Simulation Platform

Purpose:

- put candidates in realistic engineering tasks
- observe work behavior
- evaluate correctness, validation, reasoning, and production judgment

Near-term needs:

- harden sandboxing
- deepen payment case
- stabilize voice interviewer path
- make evidence ledger central
- add adaptive next challenge
- build more domain variants only after one case is excellent

These should not be conflated.

The interview system is fast, broad, and resume-grounded.

The simulation system is deeper, more expensive, and higher-signal for applied engineering.

The long-term product stack may use both:

```text
Resume/ATS context
  -> short voice interview to map claims and risks
  -> targeted engineering simulation
  -> evidence-ledger report
  -> recruiter/team decision
```

---

## 16. Open Decisions And Questions

### Interview System

- How exactly should measurement mode vs verification mode be represented in routing?
- What is the hard probe budget per claim?
- How should the pressure gauge be calculated?
- When should the system acknowledge strength?
- What is the minimum claim ledger schema?
- How should junior/mid/senior calibration change actual question phrasing?
- Should coverage force breadth even when a contradiction is juicy?

### Simulation System

- How strong does sandboxing need to be before external users?
- Should simulations allow AI help, and if yes, how should AI usage be constrained?
- Should AI occasionally be imperfect to test verification ability?
- How should telemetry distinguish strong AI collaboration from blind AI outsourcing?
- What is the next simulation after payment retry safety?

### Voice Agent Economics

- How do we separately log:
  - STT audio duration/cost
  - TTS text/audio duration/cost
  - internal LLM prompt/completion/reasoning/cost
  - realtime audio tokens if used
- Can we keep Realtime voice at the edge while preserving text-agent orchestration inside?

---

## 17. Most Important Files To Read Next

If returning cold, read in this order:

1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `problem.md`
4. `HANDOFF_CONTEXT.md`
5. `2CISASUE copy.md`
6. `ISASUE.md`
7. `ai_observed_engineering_simulation_platform_thesis_document.md`
8. `SIMULATION_PRD.md`
9. `PAYMENT_RETRY_SAFETY_PRD.md`
10. `backend/data/session_exports/5ce15b7c-a0c1-4731-b0e8-90acab38266c.json`
11. `backend/data/session_exports/ced237fe-624e-401f-b55a-8404ae1ae6a3.json`
12. `backend/services/orchestrator.py`
13. `backend/services/interview_map.py`
14. `backend/services/simulation_service.py`
15. `backend/services/inventory_simulation_service.py`

---

## 18. Recommended Next Work

### If continuing the voice interview product

1. Fix resume parsing or bypass structured parse for runtime decisions.
2. Propagate focus keys from active question packets into history.
3. Make bridge routing deterministic after repeated same-focus weakness.
4. Add a claim ledger and probe budget.
5. Add pressure gauge and recovery mode.
6. Add `explore_strength` routing.
7. Persist OpenRouter usage per call with session id, agent, route kind, and turn id.
8. Separate STT/TTS usage from internal LLM usage.

### If continuing the simulation product

1. Harden code execution boundary beyond Node permission mode.
2. Deepen payment retry safety toward production-grade DB/gateway/reconciliation cases.
3. Keep the core cockpit focused on evidence, not optional voice controls.
4. Make evidence ledger the central product surface.
5. Add adaptive next-challenge execution.
6. Preserve deterministic tests and browser-agent verification.
7. Add usage/cost telemetry by simulation family and stage.

---

## 19. The Product North Star

The best version of Antigravity is not merely an AI interviewer.

It is an evidence engine for engineering judgment.

It should answer:

- What did this candidate actually prove?
- What did they only claim?
- What broke under pressure?
- What remained untested?
- How did they reason, validate, and recover?
- Would this person be safe to put into the target engineering role?

The strongest product principle from the whole conversation:

> Great assessment is not maximum probing. It is maximum authentic signal under calibrated pressure, with evidence.

