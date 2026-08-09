# CandidateWorldV1 — Luna authoring trial

This directory is an isolated, exploratory capability trial for authoring frozen candidate worlds for Antigravity. It is not wired into the live backend, frontend, orchestrator, report path, or any existing experiment. The five worlds are deliberately **non-gold**: they are inputs for human review, not accepted evaluation truth.

## What is here

- `candidate_world_v1.schema.json` — strict JSON Schema for one frozen world.
- `authoring_calibration.md` — anti-overfitting methodology and the requested small multi-path fragment.
- `actor_contract.md` — a future candidate-actor runtime contract. It keeps the actor inside disclosed evidence and hides evaluator truth.
- `world_index.json` — inventory, role metadata, and a coverage matrix.
- `worlds/` — five authored worlds requested for this trial.
- `audits/` — one self-audit per world plus the cross-world adversarial audit.
- `reviewer_scorecard.md` — a compact human review instrument and rejection rules.
- `validate_trial.py` — local read-only schema, reference, citation, and coverage validation.
- `projections/actor_private/` — candidate truth, ownership/disclosure metadata, and behavior only; no evaluator strategy or verdict fields.
- `projections/actor/` — turn-scoped actor prompts containing only trusted granted facts.
- `projections/interviewer/` — resume plus conversation events only.
- `projections/evaluator/` — frozen truth, evidence graph, move-family sets, invalid reality violations, and sufficiency metadata.
- `materialize_projections.py`, `disclosure_controller.py`, and `validate_actor_response.py` — deterministic projection, disclosure, and citation-scope tools.
- `check_projections.py` — recursive boundary/coherence/leakage checks; `projection_manifest.json` — source and projection SHA-256 freeze.

## How to review

Review the worlds as simulations of underlying reality, not as ideal answer scripts. For every proposed interviewer move, ask:

1. Is the move legal from the disclosed state, and is it one of several defensible moves?
2. Does the answer use only eligible fact IDs, with ownership preserved at the narrowest stated boundary?
3. Would a different but reasonable question still produce a coherent answer from the same identity?
4. Does the resulting hiring read separate evidence, uncertainty, and interviewer failure?

Start with `reviewer_scorecard.md`, read the matching world audit before judging a world, and use `evaluator_hidden_truth` only as reviewer truth. A candidate actor must never receive that field.

## Authoring methodology

The worlds use a frozen-truth / spoken-behavior split:

- `evidence_units` are the only factual source of truth. Each has a stable ID, ownership boundary, temporal/reveal rule, relationships, role value, and protected conditions.
- `candidate_behavior_profile`, `response_policies`, and `answer_realizations` describe how the person may speak. They are realizations, not new facts.
- `acceptable_move_families` describe action families and opportunity-cost tradeoffs; they intentionally do not encode one gold next question.
- `evaluator_hidden_truth` contains the calibrated interpretation, unresolved hiring questions, and traps for reviewers. It is not candidate-visible.

The authoring pass intentionally includes concise answers, corrections, honest gaps, irrelevant novelty, protected details, absorbable facts, and multiple reasonable trajectories. The trial does not claim that these choices are psychologically representative or production-calibrated.

## Projection trust model

The source world is evaluator-owned. It is never passed wholesale to an actor or interviewer. The actor-private store keeps the candidate's complete lived facts, ownership/disclosure rules, and behavior model while excluding move values, sufficiency judgments, capability verdicts, expected reports, and interviewer strategy. Each actor turn is then materialized by an explicit trusted grant of fact IDs; question text is not an input to disclosure and cannot self-unlock a fact. The interviewer projection contains only resume text/claims and conversation events. The evaluator projection retains the complete frozen world and reviewer metadata.

Natural text is copied verbatim. Projection isolation is enforced by field shapes, exact-ID scope checks, recursive validators, and coherence assertions—not by token-level redaction.

`projection_v1.schema.json` is deep-strict for actor-private behavior internals (short-answer, response-policy, correction, contradiction, and fatigue structures, including `allowed_disclosure`/`must_not_do` shapes) and for actor-turn/interviewer surfaces. Evaluator `frozen_truth` internals remain schema-permissive because they are an exact copy of the already-strict CandidateWorldV1 schema; the recursive checker independently asserts exact equality, move metadata equality, and source/reference validity. The checker also injects an unexpected nested key into every private behavior/list-item shape and requires schema rejection.

## Validation

Run from this `backend/` worktree:

```bash
python3 data/candidate_worlds/luna_trial_v1/validate_trial.py
python3 data/candidate_worlds/luna_trial_v1/materialize_projections.py --verify
python3 data/candidate_worlds/luna_trial_v1/check_projections.py
```

The base validator checks JSON Schema conformance, unique IDs, relationship targets, reveal prerequisites, cited fact IDs in answer realizations and structured narrative fields, and index/world consistency. The projection checker additionally validates all four physically separate surfaces for all five worlds, checks recursive nested fields, runs disclosure-controller and response-citation tests, and asserts natural prose was not corrupted. Passing validation means the artifacts are structurally coherent; it does not mean they are good enough as gold evaluation material.

To regenerate projections after an intentional source change, run `python3 data/candidate_worlds/luna_trial_v1/materialize_projections.py --force`, then rerun both validators. `--verify` is read-only and fails if any source or projection hash differs from `projection_manifest.json`.

## Projection freeze checkpoint

The current checkpoint is ready for independent Codex/human judgment, not promotion. Review `projection_manifest.json` and `checkpoint_handoff.md` for the exact frozen file set, hashes, commands, results, and residual risks. The projection materializer is isolated to this directory; no live backend/frontend/orchestrator path imports it.

## Status

Authorship status: `exploratory_non_gold`.

No paid provider calls were made for this trial. No `.env` file was read. No live behavior was changed.
