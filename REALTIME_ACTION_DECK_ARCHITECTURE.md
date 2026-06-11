# Realtime Action Deck Architecture Notes

This document captures the working product and engineering direction discussed around Antigravity's interview orchestration, Realtime voice integration, hard-coded routing cleanup, recovery behavior, and claim-specific action decks.

It is intentionally not a marketing document. It is a memory artifact for product/engineering decisions so the conversation does not get lost.

## 1. Core Diagnosis

Antigravity already has a strong backend reasoning layer:

- interview map generation
- weakness detection
- discrepancy detection
- reasoning behavior analysis
- follow-up generation
- staged async processing
- coverage and final evaluation

The problem is not simply "the system is dumb." The more precise problem is:

```text
The analysis layer is often strong.
The routing and conversation layer still has too many hard-coded semantic decisions.
```

The current system sometimes treats counters, regexes, route-kind priority chains, token overlap, and fallback templates as if they were interview judgment. That is the source of many bad product behaviors:

- repeated drilling on the same topic
- generic fallback questions
- brittle short-answer handling
- bad-resume failure modes
- mechanical transitions
- poor candidate comfort under pressure
- "system decided" moments where no real intelligence made the decision

The goal is not to delete all deterministic logic. The goal is to move semantic judgment out of hard-coded heuristics and into staged LLM-backed action selection, while preserving deterministic system safety.

## 2. Important Distinction

There are two very different kinds of hard-coded logic.

### Keep Deterministic System Controls

These are software invariants and should remain deterministic:

- turn IDs
- stale response protection
- echo guards
- canonical state mutation rules
- max interview duration
- deduping exact repeated questions
- telemetry
- session persistence
- tool permission boundaries
- professional safety rules
- finalization state
- replayability and auditability

These are not "dumb." They are product safety.

### Replace Hard-Coded Semantic Judgment

These should increasingly become LLM-backed or action-deck-backed:

- which question to ask next
- whether to probe deeper or pivot
- whether a short answer means confusion, weakness, disengagement, bad audio, or bad question design
- whether a topic has enough evidence
- which resume snippet matters now
- whether a prepared question still fits the current answer
- whether pressure should increase or soften
- whether an answer deserves clarification vs challenge vs transition

This is where the product needs interviewer intelligence.

## 3. Architectural Stance

Realtime should not become the entire interview brain.

Realtime should also not be a dumb voice skin.

The target role is:

```text
Realtime = candidate-facing interaction manager / conversation director
Backend = interview brain and evidence system
Policy Arbiter = fast selector over backend-approved action decks
```

### Realtime Owns

- voice presence
- turn-taking
- silence handling
- filler and hold phrases
- interruption and barge-in behavior
- repeat / pause / resume / quit
- pacing changes
- warmth and candidate comfort
- professional redirection
- natural spoken rendering of selected backend-approved moves

### Backend Owns

- interview map
- resume/claim extraction
- claim-specific reserve decks
- weakness detection
- discrepancy detection
- reasoning behavior
- coverage state
- route evidence
- candidate model
- final evaluation
- canonical transcript and spoken-question logging

### Policy Arbiter Owns

- selecting the best move from available action decks
- choosing continue vs clarify vs pivot vs close
- enforcing "do not overprobe"
- enforcing "measure substance, do not prosecute forever"
- balancing evidence gain, candidate state, topic fatigue, and coverage

The policy arbiter can be a small fast backend LLM call, not necessarily Realtime.

## 4. What "Small Fast Backend LLM" Means

This means a normal text LLM API call with:

- very small prompt
- strict JSON schema
- 3-5 candidate moves
- compact state features
- no full resume dump
- no full transcript dump
- hard timeout

Example:

```text
Input:
  - current state summary
  - candidate state
  - route constraints
  - 3-5 candidate moves

Output:
  - selected_move_id
  - reason_code
  - delivery_tone
  - whether to soften, probe, pivot, or close

Target:
  150-700ms
```

It should not generate the entire interview. It should choose from already prepared intelligent moves.

## 5. Action Decks

The key abstraction is the Action Deck.

Instead of staging one `prepped_next_question`, the backend should stage a small set of candidate moves.

Example shape:

```json
{
  "deck_id": "turn_7_primary",
  "source_turn_id": "t6",
  "deck_type": "primary",
  "freshness": "current",
  "situation_summary": "Candidate named SET NX but did not explain the race condition it prevents.",
  "resume_snippet_cards": [
    {
      "id": "redis_retry_claim",
      "text": "Built Redis-backed payment retry idempotency flow",
      "risk": "mechanism not yet proven"
    }
  ],
  "moves": [
    {
      "id": "clarify_setnx_race",
      "intent": "probe_mechanism",
      "question": "What exact race condition did SET NX prevent in your retry flow?",
      "evidence_gain": "high",
      "candidate_pressure": "medium",
      "topic_repetition_risk": "medium",
      "must_preserve": ["SET NX", "race condition", "retry flow"]
    },
    {
      "id": "pivot_golang_services",
      "intent": "coverage_pivot",
      "question": "Switching to your Golang service work, how did you handle timeouts between services?",
      "evidence_gain": "medium",
      "candidate_pressure": "low",
      "topic_repetition_risk": "low",
      "must_preserve": ["Golang service", "timeouts"]
    }
  ],
  "do_not_do": [
    "do not ask another generic scaling question",
    "do not accuse the candidate of lying",
    "do not reveal hidden weakness analysis"
  ]
}
```

The deck should include the relevant resume snippets needed for this decision, not the whole resume.

## 6. Deck Types

The system should keep multiple ready decks.

### Primary Deck

Generated from the latest full background analysis. This is the normal next-question source.

### Reserve Deck

Generated during map prep or background hydration. Contains strong claim-specific alternatives for top resume claims.

### Recovery Deck

Used for short answers, skips, silence, confusion, bad audio, low-context resumes, or failed backend staging.

### Coverage Deck

Contains moves that surface untested dimensions or adjacent focus areas.

### Operational Deck

Not technical assessment. Contains candidate-facing interaction moves:

- repeat
- pause
- resume
- slow down
- clarify wording
- quit
- take a break

Operational moves can be handled mostly by Realtime tools.

## 7. Claim-Specific Reserve Decks

Avoid generic fallbacks. During interview map preparation, generate strong reserve tracks around the highest-confidence claims.

For each top claim, generate directional moves:

- mechanism probes
- ownership probes
- boundary probes
- failure-mode probes
- debugging probes
- tradeoff probes
- simplified probes
- short-answer rescue probes

Example for a Redis payment idempotency claim:

```text
Mechanism:
  What exact race condition did SET NX prevent in your retry flow?

Boundary:
  What failure remains if Redis succeeds but the Postgres write fails?

Ownership:
  Which part of that retry path did you personally implement?

Debugging:
  What symptom would tell you duplicate retries were still happening?

Simplified:
  In one concrete step, how did you stop the same payment from being processed twice?
```

These are not generic fallback questions. They are precomputed, claim-specific, directional, and ready.

## 8. Short Answer Handling

Short answers can mean many things:

- candidate is weak
- candidate is nervous
- candidate did not understand
- candidate is disengaged
- audio/STT failed
- question was too complex
- resume claim was inflated

So short answers should not all receive the same fallback.

Proposed policy:

```text
First short answer:
  use a claim-specific simplified probe

Second short answer on same topic:
  ask ownership/scope clarification or offer a rephrase

Third short answer / repeated no-content:
  pivot to another claim or ask candidate to choose a concrete area they can speak about

Continued non-engagement:
  pause, wrap, or mark low-evidence outcome
```

The short-answer rescue should be specific and simpler, not generic and softer.

## 9. Recovery Question Service

If the normal backend path has no ready high-quality question, do not ask a static fallback.

Create a Recovery Question Service.

This can be implemented in Python, but should be treated as a backend service/tool, not an ad hoc script.

Flow:

```text
Candidate skips / freezes / backend has no ready question
  ↓
Realtime says a soft hold phrase immediately
  ↓
Backend calls RecoveryQuestionService
  ↓
Service returns 5-10 ranked claim-specific moves in <3s
  ↓
Policy arbiter chooses one
  ↓
Realtime speaks it naturally
```

### Trigger Cases

- candidate says "skip"
- candidate says "I don't know"
- repeated silence
- backend has no PrimaryDeck
- LLM pipeline failed
- current topic is overprobed
- answer is too short twice
- candidate asks to move to another experience
- Realtime requests `request_recovery_deck(reason)`

### Retrieval Priority

1. Claim-specific reserve deck generated during map prep
2. Unused trajectory map questions
3. Coverage deck / adjacent focus deck
4. Fast LLM rescue generation from top snippets
5. Fail closed / pause / degraded wrap

### Latency Budget

```text
0-100ms:
  Realtime starts hold phrase

0-500ms:
  retrieve reserve deck / unused trajectory moves

500-1200ms:
  rank by focus, skip reason, coverage, repetition, candidate state

1200-2500ms:
  only if needed, small LLM generates rescue moves

2500-3000ms:
  return ranked deck or fail closed
```

Most cases should be retrieval + ranking over prepared decks, not live generation.

### Example Output

```json
{
  "reason": "candidate_skip",
  "latency_budget_ms": 3000,
  "moves": [
    {
      "id": "redis_simplified_mechanism_1",
      "question": "In one concrete step, how did you stop the same payment from being processed twice?",
      "source": "reserve_deck",
      "focus_key": "redis_payment_retry",
      "relevance": 0.91,
      "pressure": "low",
      "intent": "simplified_mechanism_probe"
    }
  ]
}
```

## 10. Hold Phrases And Fillers

Filler should not be random "Interesting" style audio.

Use context-aware hold phrases when the system is doing work:

```text
Totally fine. Let's slow down for a second. I am going to reframe this around a more concrete part of your experience.
```

```text
No problem. Take a breath. I will shift this into a cleaner question so you can answer it properly.
```

```text
Give me one second. I want to ask the next part in a way that is fair and specific.
```

These should be calm, professional, and non-patronizing.

Avoid overdoing emotional language like:

```text
I hope you are doing fine.
```

That can feel strange in an interview. Prefer professional support over therapeutic tone.

## 11. Realtime Operational Tools

Realtime should have tools/skills for operational behavior:

```text
repeat_last_question()
pause_interview(duration_seconds)
resume_interview()
adjust_pacing(speed: slower | normal | faster)
mark_candidate_stuck()
request_rephrase_current_question()
request_recovery_deck(reason)
commit_spoken_question(text, move_id)
submit_candidate_turn(transcript)
end_interview(reason)
```

### Allowed Autonomy

Realtime can autonomously handle:

- repeat requests
- pause requests
- resume requests
- pacing requests
- "I did not hear you"
- "can you say that again?"
- "can I take a break?"
- "I want to quit"
- silence nudges
- brief professional redirection

Realtime cannot autonomously invent:

- new technical assessment questions
- discrepancy challenges
- scoring commentary
- hidden weakness explanations
- free topic pivots outside backend-approved actions

## 12. Silence Policy

Realtime should manage silence locally without always calling the backend.

Proposed policy:

```text
0-5 seconds:
  do nothing

5-10 seconds:
  soft filler if needed: "Take your time."

10-20 seconds:
  light support: "No rush. Would repeating the question help?"

20-45 seconds:
  offer operational choices: "I can repeat it, slow down, or we can pause for a minute."

45+ seconds:
  call backend: mark_long_silence / request_recovery_deck
```

Silence handling is interaction management, not technical assessment. Realtime is a good fit.

## 13. Realtime Prompt Boundary

Prompt alone is not enough, but it matters.

Candidate-facing Realtime instructions should include:

```text
You are the candidate-facing interviewer voice for Antigravity.

You may handle operational requests:
- repeat
- pause
- resume
- slow down
- clarify wording
- end interview

You may not:
- answer technical questions for the candidate
- reveal scoring or hidden analysis
- reveal weakness labels, suspicion, fraud risk, route_kind, or internal state
- discuss unrelated personal, political, sexual, medical, or non-interview topics
- abandon the interview context
- invent new assessment questions
- accuse the candidate of lying
- continue after the candidate quits

For technical interview progression, use only backend-approved moves.

Ask one question at a time.
Keep responses concise.
Preserve the backend-provided intent.
If backend state is missing, request a repair move instead of improvising.
```

If the candidate derails:

```text
I am going to keep us focused on the interview. Let's return to the engineering question.
```

If the candidate asks for the answer:

```text
I can rephrase the question, but I cannot solve it for you. What part are you unsure about?
```

## 14. Internal Agent Communication

Do not make internal agents chat with each other in prose.

Use structured packets.

Example:

```json
{
  "weakness_signal": {
    "type": "mechanism_gap",
    "severity": "medium",
    "evidence": "Named SET NX but did not explain race condition",
    "recommended_intents": ["clarify_mechanism", "pivot_after_one_more"]
  },
  "coverage_signal": {
    "focus_key": "redis_retry",
    "probe_count": 3,
    "sufficient_evidence": true,
    "next_best_focus": "golang_microservices"
  },
  "candidate_state": {
    "engagement": "normal",
    "confidence": "unclear",
    "needs_simpler_question": false
  }
}
```

The policy arbiter consumes structured state and action decks.

## 15. Cost And Token Exposure

The backend may spend 300k-450k internal tokens per interview.

Realtime should not see those tokens.

Realtime should see:

- conversational surface
- current action deck
- compact state features
- selected move
- operational tool results

Estimated per full 15-turn interview:

```text
Backend hidden orchestration:
  300k-450k tokens
  Realtime exposure: 0

Candidate transcript text equivalent:
  ~2.5k tokens

AI spoken text equivalent:
  ~700-1.2k tokens

Action deck text injected per turn:
  ~300-700 tokens x 15
  = ~4.5k-10.5k text tokens

Static Realtime instructions/tools:
  ~800-1.5k tokens, mostly cacheable

Realtime total extra text surface:
  likely ~8k-18k text tokens/session

Realtime audio:
  roughly 10k-25k audio input tokens
  roughly 3k-10k audio output tokens
```

Very rough incremental Realtime cost estimate:

```text
~$0.60-$1.70 per full interview
```

Total interview cost may land closer to:

```text
~$3-$5 per serious full interview
```

This is not automatically bad for a high-signal hiring assessment. But it only makes sense if Realtime creates real product value:

- lower latency
- better interruption handling
- better silence/freeze handling
- better operational conversation
- better candidate comfort
- better spoken delivery
- less mechanical interview feel

The dangerous expensive version is dumping maps, full histories, and backend traces into Realtime every turn. Do not do that.

## 16. STT + TTS vs Realtime

Possible options:

### Current STT + TTS

- cheapest
- more controllable
- higher latency
- less conversationally alive
- harder interruption handling

### Realtime Transcription + External TTS

- better turn handling
- still has TTS delay
- loses native speech-to-speech feel

### Realtime Text + External TTS

- may save some audio output cost
- reintroduces TTS latency
- loses much of the product spark

### Full Realtime Speech-to-Speech

- most expensive
- best UX
- best candidate-facing turbulence handling
- strongest sense of human presence

Current stance:

```text
There is no obvious way to get all Realtime benefits without paying for Realtime audio.
```

Streaming TTS can approximate some parts, but not the same presence, interruption, and turbulence management.

## 17. What Is The Point Of Realtime?

Realtime is the turbulence manager.

It handles the messy human layer:

- candidate interrupts
- candidate freezes
- candidate asks to repeat
- candidate wants slower pacing
- candidate rambles
- candidate gives partial answers
- candidate says "wait, let me think"
- candidate wants a break
- candidate quits
- candidate asks unrelated things
- candidate is nervous

With STT + backend + TTS, the product feels like:

```text
record -> transcribe -> process -> synthesize -> play
```

Realtime can feel like:

```text
someone is actually there
```

That is the product spark.

## 18. Frameworks: LangChain, LangGraph, MCP

Do not add LangChain right now. It is likely to add abstraction noise before solving the core problem.

LangGraph may become useful later if deck generation, retries, and recovery flows become too complex to track manually.

Current recommendation:

```text
Now:
  plain Python/Pydantic models
  explicit orchestrator state
  action deck services
  typed structured packets

Later:
  consider LangGraph if orchestration graphs become hard to visualize or retry
```

MCP/tool protocols are useful when the model needs to operate external capabilities:

- run tests
- inspect GitHub
- spin a sandbox
- query logs
- operate simulation environments
- run Docker/Kubernetes/migration tasks

MCP is not necessary for internal agent-to-agent communication. Structured state is better there.

## 19. Migration Plan

### Phase 1: Data Models

Add typed models for:

- ActionDeck
- ActionMove
- ResumeSnippetCard
- CandidateStateSummary
- ArbiterDecision
- RecoveryDeckRequest
- RecoveryDeckResponse

### Phase 2: Generate Reserve Decks At Map Prep

For top claims, generate claim-specific reserve moves:

- mechanism
- ownership
- boundary
- debugging
- tradeoff
- simplified
- short-answer rescue

### Phase 3: Background Pipeline Produces Decks

Change background staging from:

```text
one prepped_next_question
```

to:

```text
PrimaryDeck + optional CoverageDeck + optional RecoveryDeck
```

### Phase 4: Policy Arbiter

Add a small fast LLM arbiter:

- strict JSON
- tiny prompt
- short timeout
- selects move
- returns reason code and delivery tone

### Phase 5: Recovery Question Service

Implement retrieval/ranking from prepared decks.

Only call a live LLM if prepared moves are insufficient.

### Phase 6: Realtime Operational Layer

Add Realtime tools:

- repeat
- pause
- resume
- pacing
- quit
- request recovery deck
- commit spoken question

### Phase 7: Canonical Spoken Logging

Every meaningful Realtime-spoken assessment question must be logged back:

```json
{
  "turn_id": "t7",
  "selected_move_id": "clarify_setnx_race",
  "spoken_text": "What exact race condition did SET NX prevent in your retry flow?",
  "route_kind": "clarification_fast",
  "backend_intent_preserved": true
}
```

The evaluator should use the actual spoken question.

### Phase 8: Remove Static Semantic Fallbacks

Remove static fallback questions from live interview flow.

Replace with:

- staged intelligent deck
- recovery deck
- retry
- pause
- fail closed

## 20. Non-Negotiable Product Principle

Do not ask trash fallback questions.

If the LLM fails, the product should not pretend a hard-coded generic prompt is intelligent.

Preferred behavior:

```text
retry quickly
use already staged LLM-backed move
retrieve from claim-specific reserve deck
ask a professional hold phrase
pause or wrap degraded
```

Bad behavior:

```text
ask "What would you do differently if you started from scratch?"
ask "What breaks under load?"
ask "Walk me through your thinking."
```

Unless those questions were specifically generated and grounded for this candidate, they should not appear as emergency fallbacks.

## 21. Final Working Thesis

The product should move from:

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

Realtime is worth using if it becomes:

```text
the human interaction manager between a messy candidate and a structured interview brain
```

It is not worth using if it is only expensive TTS.

The backend remains the evidence system. Realtime manages the candidate-facing turbulence. Action decks are the contract between them.

## 22. What "100% Robust" Means Here

Robust does not mean every model call succeeds. Robust means the product never silently degrades into a stupid interview.

Target robustness means:

- no static generic fallback questions in live assessment
- no hidden backend failure pretending to be low-confidence success
- no Realtime free-form technical interviewing outside approved moves
- no evaluator using a question that was not actually spoken
- no full backend state dumped into Realtime context
- no repeated drilling without explicit evidence-gain justification
- no candidate stuck in silence without humane operational handling
- no skip / quit / pause request handled as if it were technical answer content
- no low-context resume session collapsing because the system had no grounded move ready
- no agent-to-agent prose chains when structured packets are enough

The product should either:

```text
ask a strong grounded question
ask a humane operational repair
pause and recover
or fail closed transparently
```

It should not improvise trash.

## 23. Scope Boundary

This architecture is for Antigravity interview orchestration and later simulation assessment integration.

### In Scope

- replacing hard-coded semantic routing with action-deck arbitration
- adding claim-specific reserve decks
- adding recovery deck service
- adding Realtime candidate-facing operational tools
- improving filler, silence, pause, skip, repeat, and quit handling
- preserving backend evaluation and evidence control
- canonical logging of spoken questions
- reducing Realtime context to compact action state

### Out Of Scope For The First Build

- rebuilding the entire orchestration in LangGraph
- replacing all backend agents with Realtime
- letting Realtime independently evaluate candidates
- full MCP-based simulation environment orchestration
- complex multi-agent self-conversation
- perfect cost optimization before product correctness

The immediate goal is not "maximum agent fantasy." The immediate goal is a more reliable interview brain-to-voice contract.

## 24. Concrete Backend Data Contracts

The implementation should introduce typed models before changing behavior.

### ActionMove

```json
{
  "id": "clarify_setnx_race",
  "intent": "probe_mechanism",
  "question": "What exact race condition did SET NX prevent in your retry flow?",
  "focus_key": "redis_payment_retry",
  "focus_label": "Redis payment retry idempotency",
  "source": "primary_deck",
  "route_kind": "clarification_fast",
  "evidence_gain": "high",
  "candidate_pressure": "medium",
  "topic_repetition_risk": "medium",
  "requires_backend_approval": true,
  "must_preserve": ["SET NX", "race condition", "retry flow"],
  "do_not_rephrase_as": ["accusation", "multi-part question"],
  "resume_snippet_ids": ["redis_retry_claim"],
  "generated_by": "followup_agent",
  "created_for_turn_id": "t6"
}
```

### ActionDeck

```json
{
  "id": "deck_t6_primary",
  "session_id": "session-id",
  "source_turn_id": "t6",
  "deck_type": "primary",
  "status": "ready",
  "expires_after_turn": 7,
  "situation_summary": "Candidate named SET NX but did not explain the race condition.",
  "candidate_state_summary": {
    "engagement": "normal",
    "communication_mode": "normal",
    "confidence_signal": "unclear",
    "topic_fatigue": "medium"
  },
  "resume_snippet_cards": [],
  "moves": [],
  "do_not_do": [],
  "degraded_reason": ""
}
```

### ArbiterDecision

```json
{
  "selected_move_id": "clarify_setnx_race",
  "decision": "ask_selected_move",
  "reason_code": "highest_evidence_gain_without_exceeding_topic_budget",
  "delivery_tone": "curious_direct",
  "should_pivot_after_this": true,
  "requires_realtime_rephrase": true,
  "max_sentences": 2,
  "one_question_only": true
}
```

### SpokenQuestionCommit

```json
{
  "session_id": "session-id",
  "turn_id": "t7",
  "selected_move_id": "clarify_setnx_race",
  "backend_question": "What exact race condition did SET NX prevent in your retry flow?",
  "spoken_text": "Staying on the retry flow, what exact race condition did SET NX prevent?",
  "route_kind": "clarification_fast",
  "backend_intent_preserved": true,
  "spoken_at_ms": 123456
}
```

The final evaluator must use `spoken_text`, not just the backend draft.

## 25. Request/Response Endpoints And Tools

The eventual API/tool surface should be small and explicit.

### Backend Endpoints

```text
GET  /interview/{session_id}/action_deck
POST /interview/{session_id}/arbiter_decision
POST /interview/{session_id}/spoken_question
POST /interview/{session_id}/recovery_deck
POST /interview/{session_id}/operational_event
```

### Realtime Tools

```text
get_current_action_deck()
commit_spoken_question(move_id, spoken_text)
request_recovery_deck(reason)
repeat_last_question()
pause_interview(duration_seconds)
resume_interview()
adjust_pacing(speed)
end_interview(reason)
mark_candidate_stuck(reason)
```

Realtime should not have a tool like:

```text
generate_next_interview_question_freely()
```

That would break the architecture.

## 26. Full Turn Flow

### Normal Turn

```text
1. Realtime asks selected approved question.
2. Realtime commits spoken question to backend.
3. Candidate answers.
4. Realtime captures transcript and turn events.
5. Backend stores canonical answer.
6. Fast path selects from ready deck if available.
7. Background pipeline analyzes answer.
8. Background pipeline creates next PrimaryDeck, ReserveDeck updates, and RecoveryDeck updates.
9. Policy arbiter selects next move.
10. Realtime speaks selected move.
```

### Candidate Gets Stuck

```text
1. Realtime detects long silence.
2. Realtime says a humane hold phrase.
3. If short silence: no backend call.
4. If prolonged silence: call request_recovery_deck(reason="long_silence").
5. Recovery service retrieves claim-specific simplified moves.
6. Arbiter chooses low-pressure, high-clarity move.
7. Realtime asks it.
```

### Candidate Says Skip

```text
1. Realtime recognizes operational/engagement event.
2. Realtime does not treat "skip" as technical answer content.
3. Realtime says: "No problem, I will move this into a cleaner area."
4. Backend recovery deck retrieves adjacent claim-specific moves.
5. Arbiter decides whether to simplify, pivot, or mark evidence gap.
6. Realtime speaks selected backend-approved move.
```

### Backend Has No Ready Question

```text
1. Realtime says hold phrase within ~100ms.
2. Recovery service retrieves from reserve and trajectory decks.
3. If no prepared move is good enough, small LLM generates rescue moves from top snippets.
4. If rescue fails, interview pauses or wraps degraded.
5. Never ask a static generic fallback question.
```

### Candidate Quits

```text
1. Realtime confirms once if needed.
2. Realtime calls end_interview(reason="candidate_quit").
3. Backend finalizes with partial evidence.
4. Realtime does not continue interviewing.
```

## 27. Policy Arbiter Prompt Shape

The arbiter should be boring, strict, and JSON-only.

It should not be asked to be creative. It should be asked to choose.

Prompt contents:

```text
You are selecting the next interview move from approved options.

Do not create a new question.
Do not add new resume claims.
Do not reveal hidden analysis.
Prioritize evidence gain, coverage, candidate fairness, and avoiding overprobing.
Choose exactly one move or request recovery.
Return strict JSON.
```

Input:

```json
{
  "interview_goal": "measure engineering substance, not prosecute forever",
  "current_sprint": "Project Defense",
  "recent_history_summary": "...",
  "candidate_state": {},
  "coverage_state": {},
  "topic_fatigue": {},
  "moves": []
}
```

Output:

```json
{
  "selected_move_id": "...",
  "decision": "ask_selected_move",
  "reason_code": "...",
  "delivery_tone": "curious_direct",
  "one_question_only": true
}
```

If the arbiter fails or times out, select the highest-ranked ready move from an LLM-generated deck. Do not select from static fallback templates.

## 28. Current Code Areas To Replace Gradually

The current code has several areas that should become deck/arbiter driven.

### High Priority

- `_FALLBACK_FOLLOWUPS` in `backend/services/orchestrator.py`
- agent crash fallbacks that silently turn failed analysis into benign defaults
- `_infer_focus()` as final semantic truth
- `_seed_relevant_to_answer()` as token-overlap relevance judge
- `_should_prioritize_bank_followup()`
- fast-track priority chain in `handle_transcript()`
- generic `sprint_fallback` route
- route selection priority chain in `_run_background_pipeline()`
- consecutive weakness / topic fatigue counters as final decision-makers
- fallback question helpers in `followup_agent.py`
- deterministic fallback map tracks being treated as production-ready

### Keep Or Refine, Do Not Remove

- echo guard
- stale turn/revision protection
- deduping exact repeated questions
- telemetry
- session finalization
- max interview duration
- state persistence
- frontend floor control
- canonical state mutation invariants

The cleanup should not be a blind deletion. It should be a controlled migration from semantic heuristics to deck/arbiter decisions.

## 29. Acceptance Criteria

The architecture is working only if these are true:

- Every live assessment question has provenance: primary deck, reserve deck, recovery deck, or explicit LLM generation.
- No live assessment question comes from a static generic fallback.
- Every Realtime-spoken assessment question is committed back to backend.
- The final report can show what was asked, why it was selected, and what evidence it targeted.
- Candidate skip/pause/repeat/quit events are handled operationally, not scored as technical answers.
- Short-answer recovery is claim-specific and simpler, not generic.
- Recovery deck returns useful ranked moves within 3 seconds.
- Realtime context stays compact and does not receive full maps or traces.
- Backend can replay a session from canonical spoken questions and transcripts.
- A failed agent call creates degraded state, retry, recovery, or fail-closed behavior, not fake success.

## 30. Suggested First Implementation Slice

Do not start by rewriting Realtime.

Start with the backend contract.

### Slice 1

Add Pydantic models:

- `ActionMove`
- `ActionDeck`
- `ResumeSnippetCard`
- `ArbiterDecision`
- `RecoveryDeckRequest`
- `RecoveryDeckResponse`

### Slice 2

During map preparation, generate reserve moves for top claims and store them in session state.

### Slice 3

Change background pipeline to stage:

```text
prepped_action_deck
```

while still also filling the old `prepped_next_question` for backward compatibility.

### Slice 4

Add RecoveryQuestionService that retrieves and ranks existing reserve/trajectory moves.

### Slice 5

Add arbiter over action decks but keep old routing as emergency shadow comparison.

### Slice 6

Log:

- deck candidates
- selected move
- spoken text
- reason code
- route kind
- whether old route would have differed

### Slice 7

Once deck selection proves better, remove live static fallback question routes.

This gives the team a safe migration path without breaking the interview overnight.

## 31. Product Philosophy Reminder

The goal is not to catch people forever.

The goal is to measure substance.

Adversariality is a tool. It is not the product identity.

Strong candidates should experience pressure as an opportunity to show evidence. Weak candidates should naturally score lower because evidence does not appear. Inflated claims should be exposed, but the system should not spend the whole interview proving one claim false after sufficient evidence exists.

The interview should feel:

```text
sharp
fair
human
specific
grounded
non-generic
non-prosecutorial
high-signal
```

The engineering architecture should make that product philosophy hard to violate.
