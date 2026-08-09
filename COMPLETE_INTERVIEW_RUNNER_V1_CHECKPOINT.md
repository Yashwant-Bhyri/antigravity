# CompleteInterviewRunnerV1 checkpoint

Status: **COMPLETE — SHADOW CONTROL ONLY**

This checkpoint is one deterministic control run, not interview-quality evidence and not a promotion of the CandidateActor or any live route.

## Result

- Frozen world: `world_01_product_analyst`
- Production path: `Orchestrator.prepare_session_map()` → `start_prepared_session()` → `handle_transcript()` → `end_session()`
- Visible turns committed: **15/15**
- Trace events: **167**
- Quiescence boundaries: **16**, all non-timeout with no tracked pipeline/hydration work left running
- Report finalization: complete; `shadow_only=true`; `candidate_quality_claim=not_assessed`
- Blocker: none
- Five-world run: not run
- Paid providers: not called

Durable run files:

- Canonical trace: `/tmp/antigravity_complete_interview_runner_v1_control_20260809/complete_interview_runner_v1_canonical_trace.json`
  - SHA-256: `41a05c382f79e0492e91b5a78dd300a74b3efae29692d3e3714448c747cbb13e`
  - Mode: `0600`
  - Independently reloads with `InterviewTraceV1.from_records(...)` and passes `verify_integrity()`; it reconstructs all 15 spoken question/answer pairs.

- Redacted projection artifact: `/tmp/antigravity_complete_interview_runner_v1_control_20260809/complete_interview_runner_v1_shadow_artifact.json`
  - SHA-256: `2ab6ea51a815832bf86e5bf3a413b2fce1af498fcbc5b82b9ed1bffc690690c3`
  - `artifact_kind=redacted_projection_only`; its embedded records are not the reconstruction source.
- Run manifest: `/tmp/antigravity_complete_interview_runner_v1_control_20260809/complete_interview_runner_v1_shadow_manifest.json`
  - SHA-256: `50fd979d99f5d0525fd5cde85b95c52ea79d2eef0eaf27b4f5393df9042b11f0`
- Canonical spoken-history SHA-256: `786acc94f6a4ad60f8181a75e3cfe44905026607231e05bfdeaa27ea68a674ed`
- Static contract manifest: `backend/data/complete_interview_runner_v1_manifest.json`

## Causal boundary table

| Boundary | Authoritative producer | Isolated runner seam | Truth guard / evidence |
|---|---|---|---|
| Map and startup | Production `Orchestrator` and map/agent implementations | Local deterministic provider-boundary responses only; no route compiler or replay | Production startup methods are called directly; no future candidate facts are passed to the Orchestrator |
| Question materialization | Production response returned by the Orchestrator | `InterviewTraceV1` recorder | Exact served text and evaluator projection are recorded before delivery |
| Preparation and delivery start | Trace-backed runner boundary | `BrowserPlaybackAdapter` | Prepared and delivery-start events carry runtime epoch, version, provenance, and idempotency |
| Playback completion | Browser playback ACK boundary | `BrowserPlaybackAdapter` | A positive completed ACK is required before `spoken_question_committed`; no ACK cannot create spoken truth |
| Candidate answer | CandidateActorV1 actual-grant ledger/control seam | `DeterministicActualGrantCandidate` + provider-free actual-grant generator | Only the actor's current visible response crosses into `handle_transcript`; private ledger facts are excluded from trace/artifact |
| Semantic and route decision | Production `handle_transcript` pipeline and staged route response | Trace shadow interpretation stores attribution only | No forced route, map backfill, future fact, or test-only route compiler is used |
| Evidence state | Production staged analysis plus trace evidence references | In-memory trace/report sink | Evidence references must resolve to committed answer/semantic events; unsupported references are rejected |
| Background completion | Production Orchestrator task sets | `await`/flush loop over production inflight sets | Each next committed step is preceded by a quiescence record; lateness/timeouts are recorded as blockers |
| Report finalization | Production `end_session` and report agents | In-memory persistence/handoff/telemetry sinks | Report claim is shadow-only and cannot become a candidate-quality or hiring claim |

## Failure-attribution results

The contract suite injects each boundary failure and checks that downstream truth is absent or explicitly rejected:

| Injection | Expected attribution | Result |
|---|---|---|
| No playback ACK | Browser playback boundary | No spoken question, answer, evidence, or report truth |
| TTS failure | Local TTS/playback boundary | Delivery failed; no spoken truth |
| Stale epoch then retry | Playback epoch boundary | Stale ACK rejected; fresh attempt may ACK and commit exactly once |
| Semantic timeout/fallback | Semantic finalization boundary | Fallback is immutable; late semantic result cannot add inventory/evidence |
| Rejected route | Orchestrator route/materialization boundary | Route is not materialized or spoken |
| Unsupported report evidence | Trace evidence-reference boundary | `TraceReferenceError`; claim/final event is not accepted |
| Background-task lateness | Orchestrator quiescence boundary | Recorded as timeout/lateness; never silently treated as complete |

## Production versus adapter audit

Production code actually called: `backend/services/orchestrator.py`, the production map builder/validator, production agent classes, production `InterviewTraceV1`, production coverage/report models, and production `end_session()` finalization path.

Isolated adapters: ephemeral in-memory session storage in place of Redis; in-memory telemetry/report/handoff sinks; local TTS and browser playback ACK boundary in place of external audio/browser completion; deterministic CandidateActorV1 actual-grant control boundary; and a local no-paid provider-boundary response seam required to execute the production agents without OpenRouter. The provider seam supplies structured inputs only; it does not own agenda, map, route, evidence, or report decisions.

Forbidden state untouched: developer Redis, Postgres, production telemetry/report files, Cartesia, ElevenLabs, Deepgram, OpenRouter/other paid LLM providers, live API routes, UI, and audio runtime. No `.env` file was read or printed.

## Residuals

- CandidateActorV1 real-model behavior remains REJECT/pending calibration; this run assesses only deterministic actual-grant control behavior.
- Only one frozen world was run. No five-world baseline, provider-quality claim, or promotion claim is made.
- The local control provider is deterministic execution support, not model-quality evidence.
- The repeated late short-answer-rescue path is a property of this deterministic actor/control input and is not an interview-quality judgment.
- Production model labels emitted in map diagnostics are metadata from existing configuration; no provider call occurred.
