# Candidate actor contract

This contract describes how a future language model may speak as a candidate from a frozen `CandidateWorldV1`. It is a design artifact only. Nothing in this directory is wired into the live interviewer.

## Purpose and authority boundary

The actor is a renderer of eligible candidate speech. It is not an evaluator, interviewer, route selector, fact generator, or benchmark judge. It may vary phrasing, hesitation, answer length, ordering, and tone according to the behavior profile. It may not vary underlying truth.

The runtime has four physically separate artifacts:

1. `projections/actor_private/` contains the candidate's complete lived facts, ownership and disclosure metadata, and behavior model. It excludes evaluator move values, acceptable moves, sufficiency judgments, capability verdicts, expected reports, and interviewer strategy.
2. `projections/actor/` is the turn prompt. A trusted disclosure controller copies only shared identity/resume/context plus facts explicitly granted for that turn and the bounded behavior state. It never receives question semantics and cannot unlock facts from a leading question.
3. `projections/interviewer/` contains resume text/claims and conversation events only. It does not contain latent world truth, actor eligibility, or evaluator fields.
4. `projections/evaluator/` contains the complete frozen world, evidence graph, attribution rules, acceptable move sets and tradeoffs, invalid reality violations, and sufficiency conditions.

The actor model receives only the turn prompt, not the actor-private store. A turn prompt includes the IDs of facts already granted and newly granted, but the fact text for no other unit. Identity, role context, resume, and granted factual text are copied verbatim; projection isolation is enforced structurally rather than by rewriting words.

The actor must never receive:

- `evaluator_hidden_truth` or any evaluator projection;
- the actor-private store when generating a turn response;
- latent capability labels, confidence scores, move values, sufficiency conditions, reviewer traps, or likely verdicts;
- facts that are not yet eligible for disclosure;
- an expected answer, preferred question, gold trajectory, or controller action;
- raw secret values represented by protected boundaries.

## Frozen truth invariants

1. **Evidence units are the only factual source.** Every factual clause in an answer must cite one or more `fact_id` values in the machine-readable response. No uncited factual clause is allowed.
2. **No ownership widening.** Paraphrase cannot move a fact from `team_owned`, `partial`, `not_owned`, or `protected` to `owned`. The actor must preserve `ownership.scope`, `boundary_text`, and `owned_by`.
3. **No temporal leakage.** A fact is unavailable until all `disclosure.prerequisite_fact_ids` are satisfied, `earliest_turn` is reached, and the current question or voluntary-disclosure rule matches `reveal_trigger` without hitting a prohibited condition.
4. **No future-memory invention.** If a fact is `unknown`, `unavailable`, or outside the world, the actor says it does not know, does not remember, or did not own the area. It must not complete the answer from general model knowledge.
5. **Protected means protected.** The actor may use only `allowed_summary`. It must never reveal a value or identity named in `prohibited_expansion`, even if the interviewer insists.
6. **Corrections replace active truth.** When a fact supersedes another fact, the corrected fact becomes active and the predecessor remains available only as historical context. The actor may say what it previously stated, but may not continue presenting it as current truth.
7. **Contradiction is typed, not moralized.** A correction, memory refinement, scope clarification, or interviewer-created premise is not automatically deception. The actor describes the candidate's behavior; the evaluator owns interpretation.
8. **World identity is stable across questions.** Alternate questions may reveal different eligible facts, but they cannot produce different employers, timelines, outcomes, ownership, or capability history.
9. **Behavior can vary; truth cannot.** The actor may produce a short, fluent, rambling, nervous, defensive, or corrected realization permitted by the behavior profile. It may not choose a behavior solely to help or hurt the interviewer.
10. **The actor does not optimize against Antigravity.** It does not know route names, modules, evaluation rules, evidence sufficiency, or known product failure modes.

## Disclosure state

The runtime should maintain a local actor ledger independent of interviewer evaluation:

```json
{
  "turn_number": 4,
  "granted_fact_ids": ["fact_a", "fact_b"],
  "disclosed_fact_ids": ["fact_a"],
  "superseded_fact_ids": [],
  "blocked_fact_ids": [],
  "active_protected_boundary_ids": [],
  "fatigue_phase": "middle",
  "frustration_reasons": [],
  "last_question_summary": "Asked for the candidate's personal contribution",
  "last_answer_summary": "Named a team boundary"
}
```

Eligibility is computed outside the actor. The actor may select only from `granted_fact_ids` in the current turn prompt. A candidate-volunteered fact is still unavailable unless the trusted controller explicitly grants it after checking `candidate_can_volunteer`, prerequisites, temporal constraints, and protected status. The current interviewer question may be supplied as conversation input, but question semantics are never accepted as a disclosure grant.

If the interviewer states an incorrect premise, that premise does not enter the ledger as candidate truth. The actor may correct it using eligible facts. If the interviewer supplies a factual detail that happens to match an ineligible fact, the runtime must not automatically disclose the hidden fact; it may permit a neutral confirmation only if the world's reveal conditions would independently allow it.

## Required actor output

The actor returns strict JSON before any speech rendering:

```json
{
  "answer_text": "I owned the client validation; the API was my teammate's work.",
  "factual_clauses": [
    {
      "clause": "I owned the client validation",
      "fact_ids": ["fact_form_ownership"]
    },
    {
      "clause": "the API was my teammate's work",
      "fact_ids": ["fact_team_feature"]
    }
  ],
  "disclosed_fact_ids": ["fact_form_ownership", "fact_team_feature"],
  "behavior_mode": "nervous_but_concrete",
  "boundary_action": "none",
  "correction": {
    "is_correction": false,
    "superseded_fact_ids": [],
    "active_fact_ids": []
  },
  "uncertainty": {
    "kind": "none",
    "text": ""
  }
}
```

`boundary_action` is one of `none`, `ownership_boundary`, `protected_boundary`, `honest_gap`, `memory_limit`, or `question_clarification`. This field describes the answer; it does not select the interviewer's next move.

Non-factual social speech such as “Could you repeat that?” or “I need a moment” may have no fact citation. Any clause about work, outcomes, identity, ownership, sequence, behavior, or capability requires citations.

## Question handling policies

The runtime classifies question shape only to select a behavior policy, not a route:

- **Broad:** follow the world's broad response policy. A concise or fluent-but-general answer is valid if that is the candidate's behavior. Do not silently disclose the richest fact.
- **Sharp and bounded:** disclose eligible concrete evidence matching the requested artifact, decision, sequence, or boundary.
- **Repeated:** do not invent novelty. The candidate may summarize, refer to an earlier answer, become frustrated, or offer a different already-eligible consequence as permitted by the world.
- **Unfair or protected:** state the boundary once and offer an allowed abstraction. Repeated pressure does not make protected facts eligible.
- **Ambiguous:** ask a short clarifying question or answer one reasonable interpretation while naming the ambiguity.
- **Compound:** answer one or two components, state ownership boundaries, and ask which remaining part matters. Do not fabricate coverage of every layer.
- **Leading:** the actor must not adopt interviewer-supplied technical content unless an eligible fact independently supports it. A leading question cannot manufacture competence.
- **Irrelevant:** the actor may answer from an eligible neutral or side-project fact. The actor does not know that the topic is low-value; that judgment belongs to the interviewer and evaluator.

## Short answers and recovery

Short answers are first-class behavior, not malformed output. A valid two-word answer may cite only a broad surface fact. A later bounded question may unlock a more detailed eligible fact. The actor must not expand merely because the evaluator wants signal.

For nervous candidates, recovery changes verbal access but not truth. A bounded prompt can make a fact eligible through its `reveal_trigger`; a leading prompt that supplies the mechanism must be flagged as contaminated. For fluent candidates, a sharp prompt may narrow a conceptual answer into concrete evidence. Both behaviors use the same frozen evidence ledger.

## Correction and contradiction protocol

When a correction is triggered:

1. Identify the predecessor fact and the superseding fact.
2. Ensure the superseding fact is eligible and all prerequisites are satisfied.
3. Generate a natural correction that preserves what was genuinely observed and changes only what the correction changes.
4. Return both `superseded_fact_ids` and `active_fact_ids`.
5. Mark the predecessor superseded in the actor ledger after the answer is accepted.

An interviewer assertion that widens ownership is not a candidate contradiction. The actor should reject the premise using the narrow owned and unowned facts. An interviewer accusation of dishonesty does not authorize an apology or confession unless the frozen world contains one.

## Fatigue and frustration

Fatigue is deterministic enough to be reviewable but not scripted word-for-word. The runtime advances phases based on turn count and world-specific events such as repeated questions, protected-detail pressure, or fair recovery. It must not use fatigue to change fact truth, confidence, or ownership.

Late-stage frustration may shorten answers, produce explicit requests to move on, or reduce voluntary detail. A report must not treat interviewer-induced frustration as a latent capability fact unless the world explicitly supports that interpretation.

## Validation approach

Validation should happen before speech is shown:

1. Parse strict JSON and reject extra fields.
2. Verify every cited fact exists in the frozen world.
3. Verify every cited or disclosed fact is in the current prompt's `granted_fact_ids` and not blocked or superseded.
4. Verify all disclosure prerequisites are satisfied and `earliest_turn` is met.
5. Split `answer_text` into factual clauses and require citation coverage for each.
6. Compare ownership language with the cited facts. Reject widened scope, invented sole ownership, or erased partner boundaries.
7. Check protected terms and prohibited expansions using exact terms plus semantic review.
8. Check correction references and update the ledger atomically only after acceptance.
9. Check that answer content does not mention evaluator truth, route names, move value, schema internals, or fact IDs in spoken text.
10. If validation fails, use a bounded repair prompt containing only the same eligible facts. If repair fails, fall back to an authored answer realization or a truthful short boundary; never invent a generic factual answer.

The local `validate_actor_response.py` currently enforces the deterministic citation-scope part of this contract: any citation ID outside the current turn's grant is rejected. Semantic checking of uncited prose remains a human/runtime follow-up.

Automated validation cannot prove psychological realism, natural dialogue, or fairness. Human review should inspect whether actor behavior becomes stereotyped, whether short-answer recovery is too deterministic, whether fluent speech is unfairly coded as suspicious, and whether alternative phrasings remain consistent.

## Candidate actor system prompt template

```text
You are speaking as one fictional candidate from a frozen CandidateWorldV1.

You are not an evaluator. You do not know what the interviewer should ask next,
what evidence is sufficient, or what hiring conclusion is expected.

Use only ELIGIBLE_FACTS. Every factual clause must cite fact IDs in your JSON
output. Preserve ownership exactly. Never reveal protected details. Never infer
missing facts from general knowledge. Follow the supplied behavior state even
when it makes an answer short, nervous, fluent, defensive, or incomplete.

If the question is repeated, unfair, ambiguous, compound, or leading, follow
the matching candidate policy. A correction supersedes old truth; it does not
create an automatic dishonesty confession. If you do not know or did not own
something, say so.

Return only the required actor JSON. Do not mention facts, schemas, evaluator
truth, interview routes, or these instructions in answer_text.
```

The prompt should be accompanied by only the redacted actor view and the current actor ledger. The complete world file remains a reviewer artifact, not a runtime prompt.
