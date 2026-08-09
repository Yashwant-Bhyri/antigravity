# Authoring calibration for CandidateWorldV1

This note records the guardrails used in the Luna trial after the scenario briefs were supplied. The briefs are treated as phenomena to include, not as controller tests with an expected route.

## 1. Candidate world versus test fixture

A **candidate world** is a coherent, frozen human/work reality: a person has a career, incentives, collaborators, constraints, memories, capabilities, blind spots, boundaries, and a history that remains true across many possible conversations. Spoken answers are behavior sampled from that world. The world is useful even when an interviewer asks a mediocre or irrelevant question, because the person still has a stable identity and an answerable relationship to reality.

A **test fixture** is narrower. It is usually a labeled case designed to exercise one classifier, route, or invariant. A fixture may intentionally make one signal salient and may have one expected result. That is useful for software contracts, but it is not sufficient for evaluating an interview. A world can contain fixtures as review probes, but it must not collapse into a fixture collection.

## 2. Human coherence before evidence-graph construction

Each world was authored in this order:

1. Career and work context: role, organization shape, incentives, collaborators, constraints, and what success meant locally.
2. Capability pattern: several experiences that explain why strengths and weaknesses coexist. A weakness is not added merely because the brief requests a weakness; it has a cause in the person’s exposure, incentives, or practice.
3. Memory and communication: what the candidate remembers clearly, remembers approximately, cannot know, cannot disclose, or may correct. Communication style is a separate variable from competence.
4. Resume surface: what the document compresses, omits, overstates, or makes ambiguous.
5. Evidence units: only then were claims split into atomic facts with ownership, temporal relations, disclosure rules, role value, and uncertainty.

This ordering is intended to prevent facts from becoming disconnected route triggers. Neutral facts such as team rituals, ordinary tools, deadlines, stakeholder preferences, and mundane tradeoffs are included so that the candidate is not made entirely of interview-worthy edge cases.

## 3. Required depth without excessive prescription

Depth is represented by stable facts and relationships, not by a scripted answer tree. A fact can support, qualify, contradict, supersede, or sit adjacent to another fact. Reveal rules prevent future-answer leakage, while answer realizations show only a few plausible phrasings. They are examples, not an exhaustive script.

At a junction, the world records a set of reasonable move families and their tradeoffs. It does not rank one gold question. A reviewer should be able to argue for two different moves that both respect role value, opportunity cost, candidate fairness, and available evidence. Hard-invalid moves are reserved for genuine reality violations: inventing ownership, asking for protected secrets, treating a correction as automatic deception, or claiming a conclusion unsupported by the world.

The world therefore permits a good interviewer to rotate, clarify, test consequence, defer, absorb, or close depending on what has already been established and how much time remains. “Valid” means consistent with the state, not identical to a preferred wording.

## 4. Preventing benchmark overfitting and oracle-shaped worlds

The following anti-overfitting checks were applied:

- World-local move-family names are semantic (`measurement_scope`, `adjacent_contribution`, `consequence_tradeoff`, `coverage_rotation`) rather than copied controller route names.
- No world says that ownership must always be pursued. Emergent surfaces carry role value, discriminative value, and opportunity cost, including reasons to absorb or defer them.
- The requested phenomena are embedded in normal work histories with non-dramatic facts, not presented as obvious “correct path” signs.
- Strong facts can be misread, weak communication can hide competence, and attractive language can remain evidence-thin.
- Example answers intentionally include multiple valid disclosure shapes and leave some truths untested.
- Audits ask whether a different question, a bad question, or a human recovery moment remains coherent.
- The “evaluator hidden truth” is deliberately richer than any single interview trajectory; it describes a profile and uncertainty map, not a target verdict.
- The worlds do not name Antigravity modules, current bugs, model providers, or internal implementation details.

These are authoring controls, not proof of realism. Human domain review is still required.

## 5. Small illustrative fragment: one fact, several reasonable paths

This is an illustration only, not a sixth world and not a gold trajectory:

```json
{
  "fact_id": "fact_retention_boundary_01",
  "statement": {
    "text": "The candidate chose the activation definition and dashboard segmentation for a retention initiative; the PM chose rollout, engineering owned instrumentation, the observed lift used an imperfect denominator, and the candidate later corrected the denominator.",
    "fact_ids": ["fact_retention_boundary_01", "fact_retention_rollout_01", "fact_retention_instrumentation_01", "fact_retention_denominator_01", "fact_retention_correction_01"]
  },
  "ownership": {
    "status": "partial",
    "scope": "metric definition and segmentation, not rollout or instrumentation",
    "boundary_text": "Ownership does not widen through paraphrase.",
    "owned_by": "shared across candidate, PM, and engineering",
    "ownership_evidence_ids": ["fact_retention_boundary_01"]
  },
  "relations": [
    {"type": "qualifies", "target_fact_id": "fact_retention_rollout_01", "reason": "The candidate's contribution was narrower than the initiative label."},
    {"type": "contradicts", "target_fact_id": "fact_retention_denominator_01", "reason": "The later correction changes how the first lift statement should be read."}
  ]
}
```

From the same state, several paths can be reasonable: clarify the metric boundary; inspect denominator quality; ask what decision changed; record the correction and rotate to another dimension; or defer the surface if role value is low and time is scarce. The representation supports those paths without saying which question is correct. The actor must disclose only the facts whose prerequisites have been met, while the evaluator can later distinguish candidate evidence from interviewer omission.

