# Conversation Evolution README

Last updated: 2026-05-26

This README recaps the product and engineering conversation that led to the current Antigravity interview redesign direction. It is meant for someone returning after a few weeks who needs to quickly understand the history, progress, reasoning, and current target architecture.

The companion implementation-oriented architecture note is:

- `REALTIME_ACTION_DECK_ARCHITECTURE.md`

This file tells the story of how we got there.

## 1. Starting Point

Antigravity began as an adaptive AI technical interview system inside the ProvenHire hiring platform.

The broader ProvenHire assessment stack includes:

- logic / aptitude
- DSA round
- Antigravity interview
- future engineering simulation assessments

The original strategic idea was that these assessments should eventually combine into a candidate skill map. Antigravity would not merely be a resume Q&A bot. It would become one of the high-signal measurement layers for engineering substance.

## 2. Initial Repo / Product Deep Dive

The first request was to deeply inspect the codebase because README-level documentation was unreliable.

The main areas studied were:

- `app/interview/[session_id]/page.tsx`
- backend interview orchestration
- follow-up generation
- trajectory map generation
- session exports
- real interview dumps
- report outputs
- simulation service

The early focus was not code changes. It was understanding:

- how questions are generated
- how follow-ups work
- how weaknesses are detected
- how discrepancies are challenged
- how the interview map is used
- where the system succeeds
- where it fails structurally

## 3. Real Session Export Review

Several real interview export JSON files under `backend/data/session_exports/` were reviewed or referenced.

Important examples included:

- `ced237fe-624e-401f-b55a-8404ae1ae6a3.json`
- `3b362657-5f4b-4937-a930-44cc1009ec54.json`
- `5ce15b7c-a0c1-4731-b0e8-90acab38266c.json`
- `c1e66811-c749-431c-9925-47636d4cbb46.json`

The goal was to understand good versus bad interview behavior from actual completed runs, not just from source code.

## 4. What Was Found Good

The system had real strengths.

The weakness detection layer was genuinely useful. It could identify technically meaningful gaps such as:

- candidate names a mechanism but cannot explain what problem it solves
- candidate claims ownership but cannot describe implementation details
- candidate explains a system at surface level without failure-mode depth
- candidate contradicts resume claims under probing

The discrepancy system also showed value. In adversarial or inflated-resume sessions, it could keep pressure on a claim long enough to expose contradictions or admissions.

The trajectory map, when used correctly, produced strong interview-quality questions. Some boundary probes and mechanism probes were much better than generic interview prompts.

Final evaluations were often directionally calibrated:

- maybe / no-hire recommendations were not random
- confidence was higher when failure evidence was clear
- reports could distinguish conceptual knowledge from implementation depth

The core conclusion was:

```text
The analysis layer is real.
The routing layer is structurally weaker than the analysis layer.
```

## 5. What Was Found Broken

Several recurring problems were identified.

### Resume Parser Weakness

The resume parser often returned weak or empty structured data:

- `skills: []`
- `projects: []`
- `experiences: []`
- wrong experience tier
- fragmented claims
- tools split incorrectly

The map generator sometimes worked around this by reading raw resume text, but downstream modules still relied on broken parsed fields.

### Focus Inference Failure

Focus inference was often empty or wrong.

This broke downstream behavior:

- bridge mechanism
- coverage map tracking
- speculative cache lookup
- focus-aware routing
- map traversal

### Bridge / Pivot Not Firing Reliably

The system could get stuck on one project or one failed claim for too long instead of moving to another focus area.

Even when enough evidence had been collected, it sometimes kept probing the same topic.

### Map Underutilization

The carefully generated trajectory map was not always the primary runtime source of questions.

The runtime frequently fell through to seed/fallback behavior, meaning the interview quality depended too heavily on per-turn LLM luck or generic paths.

### Coverage Problems

Some sessions left major claimed areas untested. For example:

- database optimization
- microservices architecture
- CI/CD
- LLM integration
- caching strategies

The system could expose one weak claim but fail to measure the rest of the candidate.

### STT / Voice Noise

Speech-to-text artifacts entered the evaluation path. The models were resilient enough to sometimes work around this, but the product did not explicitly handle transcription uncertainty.

## 6. Product Philosophy Shift

A major conceptual shift happened in the conversation.

The system had been leaning toward:

```text
adversarial interview that catches inflated resumes
```

The refined target became:

```text
substance measurement interview that uses adversarial pressure when useful
```

This distinction matters.

Adversariality is useful:

- strong candidates can use pressure as a chance to provide evidence
- weak or inflated candidates naturally get exposed
- resume claims need verification

But adversariality should not become the whole product identity.

The interview should measure substance across the candidate's world, not spend 15 turns proving one claim false after sufficient evidence already exists.

The desired product behavior:

- challenge strongly when evidence gain is high
- stop drilling when enough evidence exists
- pivot to coverage when one area is resolved
- make room for candidates to show real ability
- distinguish nervousness, confusion, bad audio, weak answer, and inflated claim

## 7. Question Quality Framework

Question quality was broken down into three layers.

### Technical Layer

Does the question target the right engineering substance?

Examples:

- mechanism
- ownership
- failure mode
- tradeoff
- debugging
- scale boundary
- real implementation detail

### Communicative Layer

How is the question expressed?

Possible modes:

- curiosity
- direct challenge
- clarification
- collaborative exploration
- pressure
- simplification
- transition

### Psychological / Interaction Layer

Does the interaction help the candidate reveal substance?

The system must not create a cold or hostile environment where it only measures how well the candidate performs under awkward AI interaction. It must create enough comfort and clarity to measure real engineering substance.

This became one of the main reasons to consider Realtime.

## 8. Engineering Simulation Ambition

The conversation expanded from Antigravity interview into a more ambitious future product:

```text
an engineering simulation assessment led by a voice interviewer
```

The idea was not a silent coding task. It was:

- candidate reads a challenge
- voice interviewer sits beside them
- candidate plans
- candidate implements or reasons
- system provides a controlled workbench
- candidate validates
- candidate reflects
- interviewer interacts throughout

The simulation should test job-relevant engineering work, not abstract trivia.

An early concrete simulation existed:

- Payment Retry Safety simulation
- live workbench
- test runner
- stage rail
- optional Realtime mic path

This became a preview of how Antigravity could expand beyond interviews into robust engineering task simulations.

## 9. Realtime Integration Analysis

A separate question document asked how OpenAI Realtime should fit into Antigravity.

Initial rejected idea:

```text
Replace large parts of orchestration with Realtime.
```

Final direction:

```text
Realtime should become the candidate-facing interaction manager / conversation director.
The backend should remain the interview brain and evidence system.
```

Realtime should own:

- voice presence
- interruptions
- pacing
- filler / hold phrases
- repeat / pause / resume / quit
- silence handling
- warmth
- professional redirection
- natural delivery

Realtime should not own:

- interview map
- weakness analysis
- discrepancy analysis
- scoring
- final evaluation
- free technical question generation
- hidden reasoning state

## 10. Core Architecture Decision

The target architecture became:

```text
Backend creates approved possible moves.
Policy arbiter selects the best move.
Realtime speaks it naturally and handles turbulence.
Backend logs what was actually spoken.
```

In shorthand:

```text
Backend = evidence system
Policy Arbiter = move selector
Realtime = human interaction manager
Action Deck = contract between them
```

This is the central design.

## 11. Hard-Coded Routing Problem

A major frustration was that the current system has too many semantic decisions made without LLM judgment.

Examples:

- regexes deciding candidate state
- token overlap deciding focus
- counters deciding topic fatigue
- route-kind priority chains deciding next question
- static fallbacks deciding what to ask
- agent failure fallbacks pretending everything is fine

The conclusion:

```text
Keep hard-coded software controls.
Remove hard-coded semantic interview judgment.
```

Keep deterministic:

- turn IDs
- stale response guards
- echo guards
- state mutation invariants
- telemetry
- session persistence
- finalization
- dedupe

Replace or reduce deterministic:

- "what should we ask next?"
- "should we pivot?"
- "is this enough evidence?"
- "is the candidate stuck, weak, confused, or disengaged?"
- "which resume claim matters now?"

## 12. No Trash Fallback Principle

One of the strongest principles from the conversation:

```text
Do not ask trash fallback questions.
```

Bad behavior:

- LLM fails
- system silently uses generic fallback
- candidate hears a low-quality question
- report pretends interview remained meaningful

Preferred behavior:

- retry quickly
- use already staged LLM-backed move
- retrieve from claim-specific reserve deck
- ask a professional hold phrase
- pause or wrap degraded
- mark failure honestly

Fallback should not mean "generic question." Fallback should mean "recover using prepared intelligent options or fail closed."

## 13. Action Decks

The main new abstraction is the Action Deck.

Instead of staging one next question, backend stages a set of candidate moves:

- primary moves
- reserve moves
- recovery moves
- coverage moves
- operational moves

Each move includes:

- question
- intent
- route kind
- focus key
- resume snippet references
- pressure level
- evidence gain
- repetition risk
- constraints
- provenance

The arbiter chooses from these moves. Realtime renders the selected move.

## 14. Claim-Specific Reserve Decks

The user strongly pushed back against generic recovery questions.

The refined idea:

```text
During interview map preparation, generate strong reserve moves around the highest-confidence claims.
```

For each top claim, generate:

- mechanism probes
- ownership probes
- boundary probes
- debugging probes
- tradeoff probes
- simplified probes
- short-answer rescue probes

Example for Redis payment idempotency:

- what exact race condition did SET NX prevent?
- what happens if Redis succeeds but Postgres write fails?
- which part did you personally implement?
- what symptom would show duplicate retries still happening?
- in one concrete step, how did you stop duplicate processing?

These are not generic fallback questions. They are claim-specific, precomputed, and ready.

## 15. Recovery Question Service

A proposed service handles emergency routing when:

- candidate skips
- candidate freezes
- backend has no ready question
- current topic is overprobed
- answer is too short repeatedly
- LLM pipeline failed
- candidate wants another experience

Flow:

```text
Realtime says a humane hold phrase.
Recovery service retrieves/ranks 5-10 relevant moves.
Policy arbiter selects one.
Realtime speaks it.
```

Target latency:

```text
<3 seconds end to end
```

Most cases should be retrieval/ranking over prepared decks, not live generation.

## 16. Filler And Silence Handling

Filler should not be random "Interesting" audio.

Realtime should handle operational silence locally:

```text
0-5s: do nothing
5-10s: "Take your time."
10-20s: "No rush. Would repeating the question help?"
20-45s: offer repeat, slow down, or pause
45s+: call backend recovery
```

Hold phrases should be professional and non-patronizing:

- "Give me one second. I want to ask the next part in a way that is fair and specific."
- "No problem. I will reframe this around a more concrete part of your experience."
- "Let's slow down here for a second."

## 17. Realtime Tools / Skills

Realtime should be given operational tools:

- repeat last question
- pause interview
- resume interview
- adjust pacing
- mark candidate stuck
- request recovery deck
- commit spoken question
- submit candidate turn
- end interview

Realtime can autonomously handle operational events:

- repeat
- pause
- resume
- slow down
- quit
- did not hear
- candidate stuck
- unrelated derailment redirection

Realtime cannot autonomously invent assessment questions.

## 18. Canonical Spoken Logging

Every meaningful Realtime-spoken technical question must be committed to backend.

The evaluator must use what was actually spoken, not only the backend draft.

This avoids split brain:

```text
backend thinks Q was asked
Realtime actually phrased something else
evaluation becomes corrupted
```

The log should include:

- selected move id
- backend question
- spoken text
- route kind
- whether intent was preserved
- turn id
- timestamp

## 19. Cost / Token Reasoning

The backend may spend 300k-450k internal LLM tokens per interview.

Realtime should not see those tokens.

Realtime should only see:

- current action deck
- compact state
- conversational surface
- tool results

Rough estimate per 15-turn full interview:

- Realtime text surface: ~8k-18k tokens
- Realtime audio input: ~10k-25k audio tokens
- Realtime audio output: ~3k-10k audio tokens
- incremental Realtime cost: roughly ~$0.60-$1.70
- total serious interview cost may be ~$3-$5

Conclusion:

The cost is acceptable if Realtime creates real product value. It is not acceptable if it is just expensive TTS.

## 20. STT/TTS Versus Realtime

Current STT + TTS is cheaper and controllable, but less alive.

Realtime provides:

- native conversational feel
- faster interruption handling
- better silence/freeze management
- better operational interaction
- stronger candidate-facing presence

There is no obvious way to get all Realtime benefits while avoiding Realtime audio cost. Streaming TTS can approximate some pieces but not the full presence and turbulence handling.

## 21. Framework Stance

Do not add LangChain right now.

LangGraph may become useful later, but only after typed state and action deck contracts exist.

MCP/tool protocols are useful for engineering simulations when the model needs to operate external capabilities:

- run tests
- inspect GitHub
- operate sandbox
- query logs
- run Docker/Kubernetes-like tasks

MCP is not needed for internal agent-to-agent communication. Use structured state packets instead.

## 22. Implementation Direction

The suggested implementation order:

1. Add typed models for action decks and moves.
2. Generate reserve decks during map preparation.
3. Stage `prepped_action_deck` alongside old `prepped_next_question`.
4. Add RecoveryQuestionService.
5. Add a lightweight backend policy arbiter.
6. Log deck candidates and selected moves.
7. Add Realtime operational tools.
8. Add canonical spoken question commits.
9. Shadow old route decisions against new deck decisions.
10. Remove static semantic fallbacks once deck routing proves better.

Do not rip out old routing in one pass. Migrate safely.

## 23. Current Best Thesis

The system should evolve from:

```text
hard-coded fallback question
```

to:

```text
staged intelligent options
+ tiny policy arbiter
+ bounded Realtime delivery
+ operational tools
+ recovery service
+ claim-specific reserve decks
```

The interview product should feel:

- sharp
- fair
- human
- specific
- grounded
- non-generic
- non-prosecutorial
- high-signal

The backend remains the evidence system. Realtime manages human turbulence. Action decks are the contract.

## 24. Important Files To Read Next

Start with:

- `REALTIME_ACTION_DECK_ARCHITECTURE.md`
- `INTERVIEW_REDESIGN.md`
- `backend/services/orchestrator.py`
- `backend/services/interview_map.py`
- `backend/agents/followup_agent.py`
- `backend/agents/weakness_agent.py`
- `backend/agents/discrepancy_agent.py`
- `backend/services/simulation_service.py`
- `app/interview/[session_id]/page.tsx`
- `app/simulation/page.tsx`

For real session evidence, inspect:

- `backend/data/session_exports/`

For the simulation direction, inspect:

- `PAYMENT_RETRY_SAFETY_PRD.md`

## 25. Open Questions

Still unresolved:

- exact ActionDeck Pydantic schema
- how many reserve moves per claim
- how to score action move relevance
- whether arbiter should run every turn or only when multiple plausible moves exist
- how much Realtime rephrasing is allowed before backend intent is considered changed
- how to handle resume parser failure before map generation
- how to expose recovery deck debugging in telemetry
- when to end a low-engagement interview gracefully
- how to price and model Realtime cost in production

## 26. Practical Rule For Future Work

When deciding whether to use code or LLM judgment, ask:

```text
Is this a system invariant or interview judgment?
```

If system invariant:

```text
Keep deterministic code.
```

If interview judgment:

```text
Prefer staged LLM-backed action decks, policy arbitration, and explicit provenance.
```

That is the central engineering rule from the conversation.

