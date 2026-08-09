# CandidateActorV1 behavioral provider gate checkpoint

Status: `complete`

This is an isolated, bounded experiment. It does not modify or exercise the live orchestrator, UI, audio, or runner paths.

## Matrix

- Planned rows/call cap: `30/30`.
- Completed provider calls: `30`.
- World 04 classes: `12`; other-world actual grants: `12`; stress rows: `6`.
- Deterministic preflight of all planned grant chains: `passed` for `30` rows.
- Credential source: dedicated `.env.qwen.local` loader only; no `.env` read and no secret values serialized.

## Deterministic safety oracle

- Ledger-owned prerequisite/temporal grants, protected safe summaries, correction supersession, ownership boundaries, honest gaps, contradiction prompts, short answers, prompt fact-ID isolation, and rollback after an ungranted response are covered by the focused actual-grant fixture suite.
- Deterministic metrics use the actor validator, granted-ID scope, ownership findings, temporal findings, protected findings, and response shape. They are lexical/scope safety checks, not semantic proof of human truth.
- Naturalness and answer-class quality are marked for independent subjective review; no model self-judge is used as the sole oracle.

## Results

- Summary: `{"canonical_rows": 0, "failure_classes": {"deterministic_safety_rejection": 15, "schema_or_parse_rejection": 15}, "metrics": {"answer_class_fidelity_deterministic": {"failed": 30, "passed": 0, "total": 30}, "answer_naturalness_subjective_candidate": {"failed": 30, "passed": 0, "total": 30}, "canonical_response": {"failed": 30, "passed": 0, "total": 30}, "correction_behavior": {"failed": 2, "passed": 28, "total": 30}, "honest_uncertainty": {"failed": 0, "passed": 30, "total": 30}, "no_ungranted_fact_leakage": {"failed": 0, "passed": 30, "total": 30}, "ownership_calibration": {"failed": 0, "passed": 30, "total": 30}, "protected_info_compliance": {"failed": 27, "passed": 3, "total": 30}, "temporal_compliance": {"failed": 0, "passed": 30, "total": 30}, "truth_entailment_to_granted_fact_ids": {"failed": 30, "passed": 0, "total": 30}}, "provider_calls_completed": 30, "stress": {"repetition_rate": 0.8333, "rows": 6, "unique_answer_hashes": 1}}`
- Per-row answer text is intentionally omitted from this durable checkpoint; `30` redacted raw packet(s) are under the reported `/tmp` artifact directory.

## Residual risks

- A provider response that passes deterministic lexical validation can still be semantically wrong in a way this gate does not prove.
- Six repeated rows measure nondeterminism only for one fixed World 04 prompt; they do not establish production reproducibility.
- Provider availability, latency, and model behavior are experiment evidence, not a promotion decision for CompleteInterviewRunnerV1.

Source hashes are recorded in `backend/data/candidate_worlds/luna_trial_v1/candidate_actor_v1_provider_gate_manifest.json`; the manifest excludes its own hash to avoid circularity.
