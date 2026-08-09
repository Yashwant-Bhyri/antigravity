# InterviewTraceV1 checkpoint

## Purpose

`InterviewTraceV1` is an isolated, production-shaped causal record for complete-interview review. It does not change the live interviewer. It makes candidate-visible delivery truth, decision-time semantics, opportunity selection, evidence updates, and report attribution reconstructable without treating ordinary telemetry as canonical state.

## Current-code ambiguities verified before implementation

- Existing backend telemetry records events but does not provide a typed causal-parent graph, runtime-epoch/answer-version enforcement, per-view redaction contract, or tamper-evident chain.
- The live `/process_turn` path carries frontend turn/revision identifiers, while asynchronous analysis is staged and may be applied later.
- The frontend adopts the next question before audio playback is proven successful.
- `playAudioUrl` resolves error/abort paths without a distinct successful playback acknowledgement.

These findings identify future integration seams. This isolated contract does not claim they have been repaired in production.

## Contract

Every event contains stable session and turn identity, answer version, runtime epoch, sequence, event type, causal parents, producer and timestamps, payload schema version, decision/provenance hashes, redaction metadata, idempotency key, predecessor hash, and event hash.

The modeled lifecycle includes session/epoch changes; question materialization, preparation, delivery, acknowledgement/failure, and spoken commit; answer receipt; final and shadow semantics; opportunity inventory and action grant; transition validation; evidence update; report claims; and final evaluation.

Hard behavior enforced by the API and tests:

- no spoken commit without successful playback acknowledgement;
- failed delivery does not become spoken, answer, semantic, opportunity, or evidence truth;
- idempotent retries preserve one canonical event, while conflicting reuse fails;
- stale epoch/version attempts append a rejected validation receipt and do not mutate the turn;
- rejected validation cannot authorize a visible question;
- final decision-time semantics cannot be overwritten by shadow interpretation;
- action grants and spoken questions retain exact opportunity, evidence, and prior-spoken provenance;
- nested canonical payloads and causal-parent collections are immutable in memory;
- candidate/actor/interviewer/evaluator/operator projections use explicit per-event allowlists;
- secrets and raw provider/prompt payload fields are excluded or redacted;
- mutation, truncation, and reorder are detected by integrity verification;
- export/reload reconstructs the same canonical spoken history.

## View boundaries

- Candidate and candidate actor receive only candidate-experienced lifecycle information. They do not receive semantic, opportunity, route, evidence, report, or evaluator truth.
- Interviewer receives bounded operational decision context required to drive the interview, but not frozen CandidateWorld truth, excluded-option reasoning, full semantic/shadow payloads, evidence-state contents, report text, or evaluation summary.
- Evaluator receives causal evidence required for postmortem and final attribution.
- Operator receives bounded status/diagnostic metadata, not raw answers, full semantic judgments, or final evaluation content.

## Verification

Run from the project root:

```bash
python3 -m py_compile backend/services/interview_trace_v1.py backend/test_interview_trace_v1_contract.py
python3 -m unittest -v backend.test_interview_trace_v1_contract
```

The accepted local run executes 13 deterministic tests covering happy path, delivery failure/retry, idempotency, stale attempts, validation rejection, semantic shadow disagreement, causal provenance, view isolation, nested immutability/redaction, import exports, tamper/reorder detection, and replay stability.

## Future integration seams

1. Create the session trace beside `/start_interview` state creation and persist events durably rather than holding the in-memory reference implementation.
2. Emit decision and inventory events at the orchestrator's immutable decision boundary before question materialization.
3. Emit delivery-start in the backend/UI bridge, playback acknowledgement only from a positive browser audio completion signal, and delivery failure from explicit error/abort paths.
4. Commit the spoken question only after that positive acknowledgement; use the spoken event as the next answer's parent.
5. Emit evidence updates from the canonical state commit and report claims with exact evidence-event references.
6. Preserve idempotency keys and compare-and-set runtime epoch/answer version across Redis updates and retries.

## What remains unproven

- No live route, Redis, Postgres, TTS, browser playback, orchestrator, or report code is instrumented yet.
- The reference store is in memory; production durability, transaction boundaries, retention, and concurrent-writer behavior remain to be implemented.
- The hash chain is tamper-evident for accidental or unsophisticated mutation, not a signed adversarial audit log.
- Redaction is key/pattern based and must be paired with an explicit production payload schema and privacy review.
- Contract tests prove lifecycle behavior, not interview quality or production-path fidelity.

The next checkpoint should integrate this contract through a production-faithful complete-interview runner before any live authority change.
