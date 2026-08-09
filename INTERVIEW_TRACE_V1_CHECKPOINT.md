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
- only explicit `PlaybackAckStatus.COMPLETED` establishes positive playback truth;
- failed delivery does not become spoken, answer, semantic, opportunity, or evidence truth;
- operation-level idempotent retries preserve one canonical event, while same-key content changes and alternate-key logical reuse fail;
- mutation/clock/append exceptions restore canonical events, indexes, ledgers, and epoch state, while domain rejections return one canonical rejected-validation receipt;
- materialization, preparation, delivery-attempt, ACK, failure, spoken, answer, semantic-final, evidence, report-claim, and final-evaluation identities are exactly once (distinct delivery attempts are the explicit retry unit);
- stale epoch/version attempts append a rejected validation receipt and do not mutate the turn; future answer-version gaps do not create a turn ledger;
- rejected validation cannot authorize a visible question;
- imported materialization cannot follow an accepted validation unless that validation explicitly authorizes a visible route commit;
- imported validation requires interviewer, evaluator, and operator `validation_status` values to be exactly equal;
- a playback ACK and delivery failure are mutually exclusive for one delivery attempt, including when a later spoken record is present;
- final decision-time semantics cannot be overwritten by shadow interpretation;
- action grants, validations, materializations, and spoken questions retain one consistent immediately-prior spoken-question lineage;
- opportunity inventory import re-normalizes unique IDs, admitted kinds, excluded reasons, and typed prior evidence references;
- report claims cite only typed evidence events, and final evaluations can cite only report claims whose evidence is included;
- nested canonical payloads and causal-parent collections are immutable in memory;
- candidate/actor/interviewer/evaluator/operator projections use explicit per-event allowlists, with no global sequence in candidate/actor projections;
- candidate/actor projections omit pre-playback materialized question text and producer/runtime/timestamp internals while evaluator/operator evidence remains available;
- secrets, prompt variants, credentials, and raw provider payload fields are excluded or redacted;
- import verifies canonical sanitized payloads and complete redaction metadata without requiring original secret bytes: every `[REDACTED]` marker leaf and sensitive-key redaction path must be enumerated exactly, and paths are sorted/deduplicated so legal JSON object-key reordering cannot change trace validity;
- `from_records(..., verify=False)` is tainted/read-only until a complete `verify_integrity()` succeeds, so it cannot append canonical events or produce authority projections;
- import verifies schema/type/genesis, IDs and keys, unique earlier parents, sequence/hash-chain, decision/provenance recomputation, runtime epochs, answer-version continuity, typed lifecycle lineage, redaction metadata, and logical identity uniqueness;
- export/reload rebuilds indexes from canonical events, including rejection telemetry without ghost turn ledgers, and reconstructs the same canonical spoken history;
- mutation, reorder, invalid lineage, and invalid hash-chain records are rejected. Valid-tail truncation requires an external durable seal and cannot be detected from a prefix alone.

## View boundaries

- Candidate and candidate actor receive only candidate-experienced lifecycle information after playback is proven. They do not receive pre-playback materialized text, semantic, opportunity, route, evidence, report, or evaluator truth.
- Interviewer receives bounded operational decision context required to drive the interview, but not frozen CandidateWorld truth, excluded-option reasoning, full semantic/shadow payloads, evidence-state contents, report text, or evaluation summary.
- Evaluator receives causal evidence required for postmortem and final attribution.
- Operator receives bounded status/diagnostic metadata, not raw answers, full semantic judgments, or final evaluation content.

## Verification

Run from the project root:

```bash
python3 -m py_compile backend/services/interview_trace_v1.py backend/test_interview_trace_v1_contract.py
python3 -m unittest -v backend.test_interview_trace_v1_contract
python3 -m pytest -q backend/test_interview_trace_v1_contract.py
git diff --check
python3 -c 'import hashlib, json; from pathlib import Path; manifest=json.loads(Path("backend/data/interview_trace_v1_checkpoint_manifest.json").read_text()); assert all(hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"] for item in manifest["files"])'
```

The accepted local run executes 39 deterministic tests covering happy path, delivery failure/retry, exact idempotency/conflicts, atomic exceptions, stale and future-version attempts, validation rejection, semantic shadow disagreement, causal provenance, typed report/final lineage, view isolation, nested immutability/redaction, schema/genesis/type import checks, rehashed tamper detection, visible-route authorization, cross-view validation-status equality, ACK/failure exclusivity, immediate-prior lineage, tainted import isolation, opportunity normalization, idempotent value-pattern/key/mixed redaction round-trips, canonical redaction-path ordering under legal JSON object-key reordering, missing/fabricated redaction metadata rejection, candidate projection boundaries, index rebuild equivalence, and replay stability.

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
- The exact `[REDACTED]` marker is reserved as canonical redacted data; a literal caller value equal to that marker is intentionally indistinguishable from a redacted value and must remain reserved by the production schema.
- Value-pattern import verification proves marker/path consistency and does not recover or independently attest the original secret bytes.
- Tail completeness is not inferable from a valid prefix; an external durable end-of-trace seal/checkpoint is required to detect truncation.
- The repository-wide pytest command cannot collect provider-backed modules in this clean environment without `OPENROUTER_API_KEY`; this checkpoint made no provider calls and does not claim those suites passed.
- Contract tests prove lifecycle behavior, not interview quality or production-path fidelity.

The next checkpoint should integrate this contract through a production-faithful complete-interview runner before any live authority change.
