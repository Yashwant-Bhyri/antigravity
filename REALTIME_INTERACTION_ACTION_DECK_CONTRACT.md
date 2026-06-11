# Realtime Interaction And Action Deck Contract

This document captures the product and architecture revelations from the June 1 discussion about action decks, hierarchical trajectory maps, Realtime voice behavior, fillers, clarification, continuation prompts, and the need to modulate adversarial pressure.

It complements `REALTIME_ACTION_DECK_ARCHITECTURE.md`. That document defines the broad backend/Realtime split. This document defines the human interaction contract and the turn-counting rules that must sit between the candidate and the assessment brain.

Status: design contract, not fully implemented.

## 1. Core Thesis

Antigravity should not behave like a sequence of isolated technical questions.

The live voice experience should feel like:

```text
candidate speaks
interviewer acknowledges
candidate gets fair room to clarify or continue
backend assesses the complete answer
action deck selects the next approved move
Realtime renders the selected move naturally
```

The assessment must still be rigorous. But rigor should not mean every interaction feels like a negative card was drawn.

The central principle:

```text
Preserve conversational dignity first.
Preserve assessment integrity always.
Choose the least adversarial move that still gains the needed evidence.
```

## 2. Why This Document Exists

The earlier action-deck idea was:

```text
Instead of staging one next question, stage a small set of approved moves.
```

Yash refined that into a stronger requirement:

1. The next move should be hierarchical and trajectory-aware.
2. If the candidate already answered the planned follow-up, skip it.
3. If the candidate says something that changes the branch, follow the new branch.
4. If the candidate is short or unclear, give them room before scoring the answer as weak.
5. If the candidate does not understand the question, rephrase it without incrementing the question count.
6. Every answer should receive some spoken acknowledgment, but not fake praise.
7. The system state cannot be dominated by negative/adversarial signals.

This is not a tone-polish request. It is a core architecture rule.

## 3. Main Terms

### Assessment Turn

A counted technical interview question.

Assessment turns consume evidence budget, advance trajectory state, and appear as real questions in the report.

Examples:

- mechanism probe
- boundary probe
- ownership probe
- discrepancy challenge
- application transfer
- coverage pivot
- synthesis close

### Interaction Move

A non-counting conversational move.

Interaction moves help the candidate understand, continue, pause, recover, or feel heard. They do not consume the assessment budget.

Examples:

- receipt
- repeat
- rephrase
- simplify
- invite continuation
- slow down
- pause
- resume
- bad-audio repair
- clarify wording

### Action Deck

A compact local set of backend-approved candidate moves for the current moment.

It is not the full interview map. It is the local option set exposed to an arbiter or Realtime tool layer.

### Trajectory Map

The larger interview plan over resume claims, focus areas, sub-focus surfaces, and expected evidence progression.

It answers:

```text
What should this interview eventually cover?
```

### Local Action Deck

The current moment's approved choices.

It answers:

```text
Given what just happened, what are the 3-7 safe next moves?
```

### Policy Arbiter

A small selector, likely a fast backend LLM call or deterministic-plus-LLM hybrid, that chooses from approved moves.

It should not invent new assessment questions.

### Realtime Voice Layer

The candidate-facing interaction manager.

It handles speech, timing, warmth, silence, interruptions, clarification, continuation prompts, and natural rendering of approved moves.

It should not independently generate new technical assessment questions.

## 4. The Architecture Shape

The correct shape is hierarchical but not a rigid decision tree.

```text
global trajectory map
  -> local action deck
    -> answer signal classification
      -> invalidation and activation of moves
        -> policy arbiter selection
          -> Realtime spoken rendering
            -> spoken question commit
```

The trajectory map can know that Question A usually leads to B, C, or D. But the voice model should not be handed the full tree and asked to navigate freely.

The backend owns the hierarchy. Realtime owns the human delivery.

## 5. Hierarchical Multi-Trajectory Behavior

The system should support logic like:

```text
Ask Question A.

If candidate explains mechanism:
  Ask boundary follow-up B.

If candidate admits they do not know:
  Ask simpler ownership/scope question C.

If candidate already answers B while answering A:
  Do not ask B. Move to D.

If candidate says something that contradicts the resume claim:
  Activate challenge E, but only if it is fair and evidence-relevant.

If candidate is confused:
  Rephrase A as A1 without counting a new question.

If candidate gives a thin answer:
  Invite continuation A2 without counting a new question.
```

This hierarchy should be represented as move metadata, not as a brittle hard-coded tree.

Example:

```json
{
  "id": "probe_cache_boundary",
  "intent": "boundary_probe",
  "question": "What failure case still remains if cache invalidation succeeds but the database write is delayed?",
  "trigger_if": ["mechanism_explained", "boundary_not_answered"],
  "invalid_if": ["boundary_already_answered", "candidate_did_not_own_component"],
  "supersedes": ["generic_scaling_probe"],
  "priority_class": "local_continuity",
  "evidence_gain": "high",
  "candidate_pressure": "medium"
}
```

## 6. Tie-Break Policy

If multiple moves are available, hierarchy should win inside clear priority classes.

Recommended priority:

1. Operational and safety events
2. Already-answered invalidation
3. Clarification/rephrase when the candidate did not understand
4. Same-turn continuation when the answer is short or unfinished
5. Direct contradiction or claim-risk, when fair and material
6. Local continuity on the current claim
7. Positive-signal exploration
8. Coverage or pivot after sufficient local evidence
9. Synthesis or close
10. Recovery/fail-closed if no good assessment move exists

Important: the tie-break should not always escalate pressure. If two moves have similar evidence gain, prefer the one with lower unnecessary pressure and better conversational continuity.

## 7. Turn Counting Contract

The system must distinguish counted assessment moves from non-counting interaction moves.

### Counting Assessment Moves

These increment `question_count` and consume trajectory/action-deck budget:

- new mechanism question
- new boundary question
- new ownership question
- new debugging/failure-mode probe
- new application-transfer question
- new coverage-surface question
- new discrepancy challenge
- new topic pivot
- final synthesis question

### Non-Counting Interaction Moves

These must not increment `question_count`:

- "I hear you. Is there one concrete example you would add?"
- "Let me say that more simply."
- "I'll repeat the question."
- "No rush. Take a moment."
- "I can slow this down."
- "Would you like me to rephrase that?"
- "I think my question was too compressed. Let me restate it."
- "I may not have caught the last part. Could you repeat the final sentence?"

The backend should store these in turn metadata, not as separate interview questions.

## 8. Same-Turn Expansion

Short or incomplete answers should often receive a continuation prompt before being judged.

Flow:

```text
Assessment Question A
Candidate gives short answer
Realtime gives receipt
Realtime asks non-counting continuation prompt
Candidate adds detail or declines
Backend merges both answer parts
Backend evaluates the merged answer
Action deck selects next assessment move
```

Example:

```text
Candidate: "Mostly cost."
Realtime: "I hear you. I want to give you a little more room there. What was the concrete cost driver?"
Candidate: "The main issue was that full video resampling was billed per generated second, so we moved to seed-preserving edits."
```

This should be one assessment turn with two answer parts, not two questions.

## 9. Clarification And Rephrase Contract

If the candidate does not understand the question, that is not a failed technical answer yet.

Realtime may rephrase the same backend-approved question.

Rules:

- Preserve the original assessment intent.
- Simplify wording.
- Add brief context if needed.
- Do not introduce a new technical probe.
- Do not reveal hidden scoring or weakness labels.
- Do not increment `question_count`.
- Do not consume a trajectory branch.
- Log the rephrase attempt.

Example:

```text
Original backend question:
What invariant prevented duplicate gateway charges when a timeout occurred after the external charge succeeded?

Simplified Realtime rephrase:
Let me put that more simply. If the payment gateway charged the card but your server saw a timeout, what rule in your system stopped the retry from charging again?
```

Both are the same assessment turn.

## 10. Receipt Contract

Every candidate answer should usually receive a small spoken receipt before the next assessment move.

The receipt is not random filler. It tells the candidate they were heard and gives the interaction a human rhythm.

Neutral receipts:

```text
I follow.
I hear you.
That gives me the shape of it.
Okay, I see what you are pointing to.
That helps me understand your angle.
```

Strong-answer receipts:

```text
That is useful because you separated the mechanism from the outcome.
That is a clear distinction.
Good, you are naming the actual failure mode there.
That is a concrete answer.
```

Incomplete-answer receipts:

```text
I hear you. I want to give you a little more room there.
Okay. I think there may be one more concrete step underneath that.
I follow the direction, but I want to make the question easier to enter.
```

Avoid fake or premature praise:

```text
Great answer.
Amazing.
Perfect.
Exactly.
```

These should only be used when genuinely earned.

## 11. Filler, Hold Phrase, And Receipt Are Different

Do not merge these concepts.

### Receipt

Responds to candidate content.

```text
I see the distinction.
```

### Continuation Prompt

Gives candidate more room in the same turn.

```text
Is there one concrete example you would add?
```

### Rephrase

Restates the same question.

```text
Let me say that more simply.
```

### Hold Phrase

Covers system work or recovery.

```text
Give me one second. I want to ask the next part in a way that is fair and specific.
```

### Assessment Question

Targets new evidence.

```text
What failure remained after that guard was added?
```

Only the last category should count as a new technical question.

## 12. Balanced Answer Signal Model

The answer classifier must not be built only around negative or adversarial labels.

A bad state model:

```text
mechanism_gap
boundary_gap
contradiction
weakness
stuck
skip
resume_conflict
```

This creates an interview that feels like it is always searching for failure.

A better state model includes positive, neutral, operational, and risk signals.

### Positive Signals

- answered_mechanism
- answered_boundary
- gave_concrete_example
- described_tradeoff
- named_guardrail
- showed_recovery
- corrected_own_claim
- separated_ownership_from_team_work
- introduced_interesting_signal
- showed_reasoning_under_uncertainty

### Neutral / Continuation Signals

- partial_but_promising
- needs_more_room
- needs_rephrase
- answer_is_high_level
- answer_is_anecdotal
- likely_memory_reconstruction_needed
- candidate_is_thinking

### Operational Signals

- asks_for_repeat
- asks_for_rephrase
- asks_to_pause
- asks_to_skip
- bad_audio_possible
- interruption_or_barge_in
- long_silence
- candidate_quit_intent

### Risk Signals

- contradiction_or_claim_risk
- mechanism_not_explained
- boundary_not_tested
- ownership_unclear
- overclaim_risk
- hallucinated_detail_risk
- repeated_non_answer

Risk signals are allowed. They just cannot be the whole state space.

## 13. Move Families

Action decks should include more than pressure moves.

### Validation Moves

Use when the candidate gave a good answer and the system should verify depth without punishing them.

```text
That is a concrete answer. What made that guardrail reliable under the worst retry case?
```

### Explore-Strength Moves

Use when the candidate reveals a promising signal.

```text
That part is interesting. Stay with the tradeoff for a second: what did you choose not to optimize?
```

### Narrative-Invitation Moves

Use when recall-heavy questioning would be brittle.

```text
Reconstruct it from first principles. If you were building that flow again, where would you expect the first failure to appear?
```

### Simplification Moves

Use when the candidate is short, nervous, confused, or the question was too compressed.

```text
Let me make it simpler: what was the one rule that kept the same user action from being processed twice?
```

### Mechanism Moves

Use when a claim was named but not explained.

```text
What exactly changed in the system when that guard was added?
```

### Boundary Moves

Use after mechanism is present.

```text
What failure case did that still not cover?
```

### Ownership Moves

Use when personal scope matters.

```text
Which part of that path did you personally design or implement?
```

### Coverage Moves

Use when the current focus has enough evidence.

```text
Switching to the dashboarding work, how did the attribution window affect the metric you trusted?
```

### Challenge Moves

Use sparingly, when contradiction is material and fair.

```text
I want to check one tension. Earlier you said the retry was safe after timeout, but now the webhook path sounds unhandled. Which version is accurate?
```

### Synthesis Moves

Use near close.

```text
What part of your experience do you think this interview has not fairly tested yet?
```

## 14. Action Deck Fields To Add

Current `active_question_packet` and `prepped_next_packet` are useful but too narrow.

Future `ActionMove` should include:

```json
{
  "id": "move_t6_boundary_retry_webhook",
  "intent": "boundary_probe",
  "question": "What failure case still remained if the gateway timed out but later sent a success webhook?",
  "priority_class": "local_continuity",
  "focus_key": "payment_retry_idempotency",
  "sub_focus_key": "timeout_webhook_state_machine",
  "source": "primary_deck",
  "trigger_if": ["answered_mechanism", "boundary_not_tested"],
  "invalid_if": ["boundary_already_answered", "candidate_did_not_own_component"],
  "evidence_gain": "high",
  "candidate_pressure": "medium",
  "conversation_value": "high",
  "must_preserve": ["gateway timeout", "success webhook", "state machine"],
  "allowed_rephrase_scope": "simplify_without_changing_intent",
  "counts_as_assessment_turn": true
}
```

Future `InteractionMove` should include:

```json
{
  "id": "interaction_t6_rephrase_1",
  "kind": "rephrase",
  "text": "Let me put that more simply...",
  "source_question_move_id": "move_t6_boundary_retry_webhook",
  "preserves_intent": true,
  "counts_as_assessment_turn": false,
  "reason": "candidate_did_not_understand"
}
```

Future `AnswerSignalPacket` should include:

```json
{
  "turn_id": "t6",
  "answer_parts": [
    {"kind": "initial_answer", "text": "..."},
    {"kind": "same_turn_continuation", "text": "..."}
  ],
  "positive_signals": ["gave_concrete_example", "named_guardrail"],
  "neutral_signals": ["partial_but_promising"],
  "operational_signals": [],
  "risk_signals": ["boundary_not_tested"],
  "already_answered_move_ids": ["move_t6_mechanism_probe"],
  "needs_same_turn_continuation": false,
  "needs_rephrase": false
}
```

## 15. Realtime Prompt Boundary

Realtime instructions should explicitly separate interaction moves from assessment moves.

Draft:

```text
You are the candidate-facing interviewer voice for Antigravity.

Your first job is to keep the candidate oriented and heard.
Your second job is to render backend-approved assessment moves naturally.

You may independently perform non-counting interaction moves:
- brief receipt
- repeat the current question
- rephrase the current question
- simplify the current question
- ask if the candidate wants to add one concrete detail
- pause, resume, slow down
- handle bad audio
- handle quit intent

You may not independently invent a new technical assessment question.
For technical progression, use only backend-approved moves.

When rephrasing, preserve the original intent.
When inviting continuation, do not add a new technical probe.
Ask one question at a time.
Do not reveal scoring, weakness labels, route kinds, hidden analysis, or internal state.
```

## 16. Spoken Question Commit

If Realtime rephrases an assessment question, the backend must know what was actually said.

The evaluator should use `spoken_text`, not only the backend draft.

Example:

```json
{
  "session_id": "session-id",
  "turn_id": "t7",
  "selected_move_id": "move_t7_boundary_retry_webhook",
  "backend_question": "What failure remains if the gateway times out but later sends a success webhook?",
  "spoken_text": "Let me make that simpler. If the gateway charged the card but your server saw a timeout, what rule stopped the retry from charging again?",
  "interaction_moves_before_answer": [
    {
      "kind": "rephrase",
      "reason": "candidate_did_not_understand",
      "counts_as_assessment_turn": false
    }
  ],
  "backend_intent_preserved": true,
  "counts_as_assessment_turn": true
}
```

## 17. Same-Turn Data Model

A single assessment turn may include several interaction events.

```json
{
  "turn_id": "t4",
  "assessment_question_count_index": 4,
  "selected_move_id": "move_t4_mechanism_probe",
  "backend_question": "...",
  "spoken_question": "...",
  "interaction_events": [
    {"kind": "receipt", "text": "I follow.", "counts": false},
    {"kind": "continuation_invite", "text": "Is there one concrete example you would add?", "counts": false}
  ],
  "answer_parts": [
    {"kind": "initial", "text": "Mostly cost."},
    {"kind": "continuation", "text": "Full video resampling was billed per generated second..."}
  ],
  "merged_answer": "Mostly cost. Full video resampling was billed per generated second...",
  "final_answer_ready_for_assessment": true
}
```

## 18. Scenario Flows

### Strong Answer

```text
Candidate answers mechanism clearly.
Realtime: "That is a clear distinction."
Backend marks answered_mechanism.
Action deck invalidates mechanism follow-up.
Arbiter selects boundary or tradeoff move.
```

### Short Answer

```text
Candidate gives a two-word answer.
Realtime: "I hear you. I want to give you a little more room there. What was the concrete example?"
Candidate expands.
Backend merges both parts.
No new question count.
```

### Candidate Does Not Understand

```text
Candidate: "Sorry, what do you mean?"
Realtime rephrases the same question.
Backend logs rephrase.
No new question count.
No trajectory branch consumed.
```

### Candidate Already Answered The Planned Follow-Up

```text
Candidate answers mechanism and boundary in one response.
Backend marks planned boundary move invalid.
Arbiter selects D instead of repeating B.
```

### Contradiction

```text
Candidate says something that conflicts with resume or earlier answer.
Backend marks contradiction_or_claim_risk.
Challenge move activates.
Arbiter checks pressure budget and evidence value.
If fair, ask a direct but non-accusatory clarification.
```

### Candidate Wants To Skip

```text
Realtime treats this as operational, not technical answer content.
Backend marks skipped focus as low evidence.
Recovery deck retrieves simpler or adjacent move.
No fake scoring of "skip" as a bad technical explanation.
```

## 19. Implementation Direction

Do not start by rewriting the Realtime layer.

Start by making the backend contract capable of representing this.

Suggested slices:

1. Add typed models for `ActionMove`, `ActionDeck`, `InteractionMove`, `AnswerSignalPacket`, `SpokenQuestionCommit`.
2. Add `counts_as_assessment_turn` to every move.
3. Add interaction event logging inside the session history model.
4. Add same-turn answer part merging for continuation prompts.
5. Add a compact answer-signal classifier with positive, neutral, operational, and risk signals.
6. Generate a local action deck from the existing `prepped_next_packet`, trajectory map, coverage map, and recovery candidates.
7. Add invalidation rules for already-answered moves.
8. Add policy arbiter over approved deck moves.
9. Add Realtime tools for rephrase, continuation, recovery request, spoken commit.
10. Shadow old route selection against action-deck selection before removing old routes.

## 20. Current Code Mapping

Existing nearby concepts:

- `active_question_packet` is a proto-current-move object.
- `prepped_next_packet` is a proto-next-move object.
- `select_from_trajectory_map_detailed()` already returns map-grounded route kinds.
- trajectory-map recovery already handles short answers in some cases.
- Realtime simulation routes exist, but they do not yet use action decks.

Missing concepts:

- no real `ActionDeck`
- no `InteractionMove`
- no `AnswerSignalPacket`
- no spoken-question commit path
- no non-counting rephrase/continuation model
- no balanced positive/neutral/risk signal classifier
- no arbiter over multiple approved moves
- no Realtime tool boundary for action decks

## 21. Acceptance Criteria

This architecture is working only if:

- Every assessment question has provenance.
- Every Realtime-spoken assessment question is committed back to backend.
- Rephrase/repeat/continuation do not increment question count.
- Short answers get fair same-turn expansion before being treated as low evidence.
- Candidate confusion triggers a rephrase, not a penalty.
- Already-answered planned probes are skipped.
- Positive signals can trigger exploration, not only harder challenge.
- Risk signals exist but do not dominate the entire state model.
- Realtime never invents a new technical assessment question outside approved moves.
- The final report can distinguish assessment questions from interaction moves.

## 22. Product Non-Negotiables

Do not ask trash fallback questions.

Do not make fake praise the default.

Do not convert every answer into a weakness hunt.

Do not treat confusion as failure before rephrasing.

Do not count clarification as a new question.

Do not let Realtime freely interview outside the backend-approved deck.

Do not hide spoken-question drift from the evaluator.

Do measure substance with enough fairness that the candidate can actually reveal it.

## 23. Open Questions

- How many same-turn continuation prompts are allowed before the system must move on?
- Should the first short answer always receive continuation, or only when the question was complex?
- Which signals should Realtime classify locally versus backend classify after transcript?
- How much rephrasing is allowed before `backend_intent_preserved` becomes false?
- Should receipts be generated by Realtime, backend, or a small phrase policy?
- How do we test that positive-signal exploration improves evidence rather than becoming soft drift?
- How should the final report display non-counting interaction moves?

## 24. Working Summary

The action deck should not be only a deck of attacks.

It should be a deck of fair next moves:

```text
receipt
rephrase
continue
simplify
validate
explore strength
probe mechanism
probe boundary
clarify ownership
challenge contradiction
pivot for coverage
close with synthesis
```

Realtime makes the interaction humane.

The backend keeps the assessment honest.

The action deck is the contract between them.
