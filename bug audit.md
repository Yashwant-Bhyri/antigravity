# Bug Audit

Date: 2026-04-17

This file captures the important bugs found during the exhaustive audit of the runtime codebase.
Each finding includes severity, confidence, affected area, why it matters, evidence, and a likely fix direction.

## Critical

### 1. Same-turn revisions can permanently lose analysis
- Severity: `critical`
- Confidence: `proven`
- Affected area: `backend/services/orchestrator.py`
- Why it matters: a candidate can revise an answer, but the final version may never receive weakness, discrepancy, or reasoning analysis. That corrupts continuity, weakness tracking, and the final report.
- Evidence:
  - `handle_transcript()` launches a background pipeline per committed answer version.
  - `_run_background_pipeline()` suppresses a newer revision if any version of the same `turn_id` is already running.
  - The older run later discards itself as stale if `latest_turn_versions` advanced.
  - Result: old version is discarded, new version never ran, no staged analysis survives.
- Code references:
  - `backend/services/orchestrator.py:1274`
  - `backend/services/orchestrator.py:1452`
  - `backend/services/orchestrator.py:1822`
- Likely fix direction:
  - Keep the per-turn throttle if needed, but queue or rerun the newest revision after the current run finishes.
  - Do not let "older run discarded" plus "newer run skipped" produce a no-analysis state.

## High

### 2. Session state has a whole-blob lost-update race
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/state/session_manager.py`, `backend/services/orchestrator.py`
- Why it matters: concurrent async tasks can silently overwrite each other's session changes, including staged analysis, speculative cache, current turn metadata, and revision state.
- Evidence:
  - `SessionManager.save_state()` writes the entire session as one JSON blob via Redis `setex`.
  - Fast path, background pipeline, speculative generation, and seed generation all do independent read-modify-write cycles.
  - There is no compare-and-swap, version guard, Redis transaction, or field-level merge.
- Code references:
  - `backend/state/session_manager.py:18`
  - `backend/services/orchestrator.py:1248`
  - `backend/services/orchestrator.py:1927`
  - `backend/services/orchestrator.py:2030`
  - `backend/services/orchestrator.py:2109`
- Likely fix direction:
  - Move hot fields to atomic Redis keys/hashes or add optimistic concurrency/versioned CAS around session saves.

### 3. Final completed turn can be missing full analysis
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/services/orchestrator.py`
- Why it matters: when the interview completes on the current answer, the final report can miss that turn's weakness, discrepancy, and reasoning metadata.
- Evidence:
  - Completion is checked before the background pipeline for the just-submitted answer is launched.
  - `end_session()` only flushes already-staged analysis; it does not generate missing analysis for the current final answer.
- Code references:
  - `backend/services/orchestrator.py:1247`
  - `backend/services/orchestrator.py:1250`
  - `backend/services/orchestrator.py:1274`
- Likely fix direction:
  - Run a blocking final-analysis flush before full interview evaluation, or reuse the background pipeline logic synchronously for the last turn.

### 4. Recruiter dashboard is incompatible with the `/sessions` response
- Severity: `high`
- Confidence: `proven`
- Affected area: `app/dashboard/page.tsx`, `backend/api/routes.py`, `backend/db/postgres.py`
- Why it matters: the dashboard is effectively safe only when there are zero rows. Once real sessions exist, the page is set up to fail on missing fields.
- Evidence:
  - `/sessions` returns raw Postgres rows.
  - Stored columns are only `session_id`, `created_at`, `resume_snippet`, `hire_recommendation`, `overall_score`, `sprint_reached`, `duration_minutes`.
  - The dashboard expects `failure_surface`, `raw_weaknesses`, and `total_questions`.
  - It calls `Object.values(s.failure_surface)` even though that field is not returned.
- Code references:
  - `backend/api/routes.py:331`
  - `backend/db/postgres.py:71`
  - `app/dashboard/page.tsx:35`
  - `app/dashboard/page.tsx:81`
- Likely fix direction:
  - Either expand `/sessions` into a report-shaped summary endpoint or simplify the dashboard to use only persisted columns.

### 5. RAG question bank is broken in the checked-in runtime setup
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/rag/`, Python dependency manifests
- Why it matters: question-bank retrieval is likely inactive in current environments, and if the dependencies are later installed the current implementation still rebuilds the embedding model on every search.
- Evidence:
  - `faiss_store.py` imports `sentence_transformers` and `faiss`.
  - `requirements.txt` and `api/requirements.txt` do not declare `faiss-cpu` or `sentence-transformers`.
  - Local import check during audit confirmed `faiss=False` and `sentence_transformers=False`.
  - `_get_model()` creates a fresh `SentenceTransformer` each time, including in `search()`.
- Code references:
  - `backend/rag/faiss_store.py:21`
  - `backend/rag/faiss_store.py:28`
  - `backend/rag/faiss_store.py:51`
  - `requirements.txt`
  - `api/requirements.txt`
- Likely fix direction:
  - Add the missing dependencies or remove the feature from the active path.
  - Cache the embedding model globally instead of reconstructing it on every search.
  - Stop swallowing startup load failure silently if RAG is expected to be live.

### 6. Telemetry filesystem writes are incompatible with Vercel-style deployment
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/services/interview_telemetry.py`, `vercel.json`
- Why it matters: telemetry can fail or block deployment in serverless environments that do not permit repo-local writes.
- Evidence:
  - Telemetry writes JSONL files under `backend/runtime/interview_traces`.
  - The repo is configured for Vercel-style deployment.
  - Vercel Functions use a read-only filesystem except for `/tmp`.
- Code references:
  - `backend/services/interview_telemetry.py:21`
  - `backend/services/interview_telemetry.py:34`
  - `vercel.json`
- Likely fix direction:
  - Use `/tmp` only for ephemeral traces or move telemetry storage to an external durable sink.

### 7. Completed-session persistence is fire-and-forget
- Severity: `high`
- Confidence: `strongly implied`
- Affected area: `backend/services/orchestrator.py`, `backend/api/routes.py`
- Why it matters: a user can receive a finished report while the completed session never reaches Postgres.
- Evidence:
  - `persist_session()` is scheduled with `asyncio.create_task()` and not awaited.
  - The HTTP response returns immediately after `end_session()`.
  - This is especially risky in serverless or shutdown-prone environments.
- Code references:
  - `backend/services/orchestrator.py:744`
  - `backend/api/routes.py:147`
  - `vercel.json`
- Likely fix direction:
  - Await persistence or move it to a durable background queue.

### 8. Legacy staged shadow can double-apply and wipe focus metadata
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/services/orchestrator.py`
- Why it matters: the interview can lose canonical topic/focus metadata for completed turns, which directly weakens breadth guards, trajectory-map retrieval, sprint continuity, and any later report logic that depends on per-turn focus.
- Evidence:
  - The background pipeline writes both the modern queue item in `prepped_turn_queue` and the legacy shadow in `prepped_turn_analysis` / `prepped_next_metadata`.
  - On the next committed turn, `handle_transcript()` appends the legacy shadow back into the queue instead of deduplicating it.
  - `_apply_staged_analysis()` then applies both payloads.
  - The modern queue payload carries `focus_key` / `focus_label`, but the legacy payload does not.
  - The second apply can therefore overwrite an already-complete turn with empty focus fields.
- Code references:
  - `backend/services/orchestrator.py:1104`
  - `backend/services/orchestrator.py:1131`
  - `backend/services/orchestrator.py:1787`
  - `backend/services/orchestrator.py:2350`
  - `backend/services/orchestrator.py:2406`
- Likely fix direction:
  - Delete the legacy staging shadow entirely, or at minimum dedupe exact `(turn_id, answer_version)` staged items before apply and ensure both payload shapes are identical.

### 9. Same-turn revision suppression can leave the newest answer unanalyzed
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/services/orchestrator.py`
- Why it matters: when a candidate revises the same answer turn while the old background pipeline is still running, the latest version can reach the next turn with only a pending skeleton and no completed weakness/discrepancy/reasoning analysis.
- Evidence:
  - `handle_transcript()` increments `answer_version` and always tries to launch a new background pipeline for same-turn revisions.
  - `_run_background_pipeline()` suppresses any newer revision while another version of the same `turn_id` is already in `_turn_pipeline_running`.
  - The older pipeline later self-discards as stale if `latest_turn_versions[turn_id]` is newer.
  - No replacement pipeline is scheduled for that newest version after the stale one exits.
- Code references:
  - `backend/services/orchestrator.py:1044`
  - `backend/services/orchestrator.py:1747`
  - `backend/services/orchestrator.py:1921`
  - `backend/services/orchestrator.py:2321`
- Likely fix direction:
  - Cancel and replace the old pipeline, or queue the newest revision to run immediately after the in-flight one completes instead of dropping it.

### 10. Completed reports disappear after the Redis session TTL expires
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/state/session_manager.py`, `backend/api/routes.py`, `app/report/[session_id]/page.tsx`, `backend/db/postgres.py`
- Why it matters: completed interviews can still appear in the recruiter dashboard summary, but their full report page stops working once the Redis session expires.
- Evidence:
  - `SessionManager` stores each session with a fixed 1-hour TTL via `setex`.
  - `/report/{session_id}` still reads the full report from Redis-backed session state.
  - the report page treats a non-OK response as `notFound()`.
  - Postgres persistence only stores summary fields like recommendation and overall score, not the full final report payload.
- Code references:
  - `backend/state/session_manager.py:16`
  - `backend/state/session_manager.py:18`
  - `backend/api/routes.py:370`
  - `app/report/[session_id]/page.tsx:25`
  - `backend/db/postgres.py:71`
  - `backend/db/postgres.py:84`
- Likely fix direction:
  - Persist the full completed report to durable storage and make `/report/{session_id}` fall back to that durable source instead of relying solely on TTL-bound Redis state.

### 11. Natural interview completion triggers a second full finalization pass
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/api/routes.py`, `backend/services/orchestrator.py`, `app/interview/[session_id]/page.tsx`
- Why it matters: naturally completed interviews can be evaluated twice, and the second pass runs after per-answer scoring context has already been consumed, making the final saved report path unnecessarily expensive and potentially inconsistent.
- Evidence:
  - `handle_transcript()` already calls `end_session()` before returning a `complete=True` response.
  - `end_session()` consumes `self._per_answer_scores` via `pop(session_id, [])`.
  - after receiving the complete response, the frontend still calls `POST /end_interview/{session_id}` automatically.
  - that route calls `orchestrator.end_session(session_id)` again.
- Code references:
  - `backend/services/orchestrator.py:850`
  - `backend/services/orchestrator.py:1723`
  - `backend/api/routes.py:166`
  - `app/interview/[session_id]/page.tsx:377`
- Likely fix direction:
  - Make completion idempotent: either skip the extra `/end_interview` call after a natural `complete` response, or make `end_session()` a no-op once final evaluation has already been materialized.

## Medium

### 12. "Start Fresh Run" drops calibration inputs
- Severity: `medium`
- Confidence: `proven`
- Affected area: `app/page.tsx`, `app/interview/[session_id]/page.tsx`
- Why it matters: a fresh run launched from an existing session can be calibrated differently from a normal launch, changing probing pressure and final evaluation.
- Evidence:
  - Normal launch sends `target_role` and `years_experience`.
  - The "Start Fresh Run" path resubmits only `resume` and `github_links`.
- Code references:
  - `app/page.tsx:31`
  - `app/interview/[session_id]/page.tsx:758`
  - `backend/api/routes.py:57`
  - `backend/services/orchestrator.py:551`
- Likely fix direction:
  - Preserve and resend `target_role` and `years_experience` in the fresh-run flow.

### 13. `/process_turn` does not translate missing sessions into 404
- Severity: `medium`
- Confidence: `proven`
- Affected area: `backend/api/routes.py`
- Why it matters: expired or stale interview sessions hit the hottest path with a 500 instead of a clean client-handleable 404.
- Evidence:
  - `SessionManager.get_state()` raises `KeyError` on missing sessions.
  - `/process_turn` does not catch it.
  - Other session routes do catch `KeyError` and return 404.
- Code references:
  - `backend/state/session_manager.py:21`
  - `backend/api/routes.py:123`
  - `backend/api/routes.py:150`
  - `backend/api/routes.py:345`
- Likely fix direction:
  - Use the same `KeyError -> HTTPException(404)` pattern as the other session routes.

### 14. Agent output normalization is inconsistent
- Severity: `medium`
- Confidence: `proven`
- Affected area: `backend/models/llm_router.py`, `backend/services/interview_map.py`, multiple agents
- Why it matters: malformed model output silently degrades interview quality instead of being normalized or surfaced cleanly, and one startup-critical path can fall back even when the model response was almost usable.
- Evidence:
  - `LLMRouter` can return either parsed JSON or raw string.
  - `ConceptAgent` blindly calls `result.get(...)`, which fails on string output and collapses to an empty concept list through its caller's exception handling.
  - `ReasoningBehaviorAgent` returns raw model output without normalization.
  - `LLMRouter`'s last-resort rescue searches for `{ ... }` objects but not `[ ... ]` arrays.
  - `_extract_focus_seeds_llm()` explicitly expects a JSON array from the router.
  - If the model wraps a valid array in commentary without a fenced block, the router returns raw text and interview-map seed extraction falls back to deterministic resume parsing.
- Code references:
  - `backend/models/llm_router.py:47`
  - `backend/models/llm_router.py:71`
  - `backend/models/llm_router.py:83`
  - `backend/agents/concept_agent.py:32`
  - `backend/agents/reasoning_behavior_agent.py:41`
  - `backend/services/interview_map.py:317`
  - `backend/services/interview_map.py:325`
  - `backend/services/interview_map.py:498`
  - `backend/services/orchestrator.py:1572`
- Likely fix direction:
  - Normalize every agent return type at the agent boundary so each agent returns a stable dict/list fallback shape.
  - Add explicit array-aware recovery or split the router API into typed `call_json_object(...)` / `call_json_array(...)` paths.

### 15. Startup-critical interview-map build is heavyweight and unbounded
- Severity: `medium`
- Confidence: `strongly implied`
- Affected area: `backend/services/interview_map.py`, `backend/services/orchestrator.py`, `backend/models/llm_router.py`
- Why it matters: session startup now blocks on the interview map, so a slow or hanging map build directly delays or prevents interviews from starting.
- Evidence:
  - `start_session()` now awaits `_build_interview_map()` before returning.
  - `generate_interview_map()` launches 3-5 parallel `_generate_focus_track()` calls.
  - `_generate_focus_track()` uses `LLMRouter(tier="large")`.
  - `large` currently maps to `deepseek/deepseek-r1`.
  - There is no explicit timeout or degraded-mode threshold around those startup-critical focus-track calls.
- Code references:
  - `backend/services/orchestrator.py:785`
  - `backend/services/interview_map.py:451`
  - `backend/services/interview_map.py:487`
  - `backend/models/llm_router.py:9`
  - `backend/models/llm_router.py:53`
- Likely fix direction:
  - Put explicit timeouts around track generation, use a cheaper startup-safe model tier or cached map path, and define a deterministic minimum viable map instead of making full large-tier generation part of the blocking startup contract.

### 16. ASGI fallback leaks traceback and `sys.path`
- Severity: `medium`
- Confidence: `proven`
- Affected area: `api/index.py`
- Why it matters: in any real deployment, boot failures expose internal structure to clients.
- Evidence:
  - The error response includes full traceback lines and `sys.path`.
- Code references:
  - `api/index.py:21`
- Likely fix direction:
  - Return a generic 500 body and log details server-side only.

### 17. Main interview turns no longer use filler-first TTS latency masking
- Severity: `medium`
- Confidence: `proven`
- Affected area: `app/interview/[session_id]/page.tsx`, `lib/audio.ts`, `backend/api/routes.py`, `backend/services/tts_service.py`
- Why it matters: the repo still treats filler-first TTS as a core latency-masking convention, but normal follow-up turns now wait through `processTurn` and `/tts` directly. Whenever staged audio misses or the backend runs slow, the candidate hears dead air instead of a masked handoff.
- Evidence:
  - Normal turn handling waits for `processTurn(...)`, then calls `prefetchAudio(...)`, then plays the real response.
  - `prefetchFillerAudio()` is only used in the silence-nudge path.
  - `/tts_filler` is only serving that nudge flow.
  - `TTSService.stream_with_filler()` still exists, but there is no live caller on the main interview path.
- Code references:
  - `app/interview/[session_id]/page.tsx:455`
  - `app/interview/[session_id]/page.tsx:473`
  - `app/interview/[session_id]/page.tsx:651`
  - `lib/audio.ts:567`
  - `lib/audio.ts:609`
  - `backend/api/routes.py:197`
  - `backend/services/tts_service.py:227`
- Likely fix direction:
  - Either restore a revocable filler-first path for normal turns, or explicitly retire filler-first as a product contract and remove the stale abstraction/docs.

### 18. Pre-generated TTS audio can be overwritten by stale background jobs
- Severity: `medium`
- Confidence: `proven`
- Affected area: `backend/services/tts_service.py`, `backend/services/orchestrator.py`, `backend/api/routes.py`
- Why it matters: the backend can do the expensive TTS work ahead of time and still lose the latency win if an older pre-generation task finishes last and overwrites the correct next-question audio. The result is a silent cache miss and avoidable live synthesis on the hottest playback path.
- Evidence:
  - `_prepped_audio` stores only one entry per `session_id`.
  - `pre_generate(...)` writes to that slot unconditionally.
  - the orchestrator dispatches pre-generation with `asyncio.create_task(...)`, so overlapping stale/new synth jobs are not versioned or cancelled.
  - `get_prepped(...)` only consumes the cache on an exact text match, so a stale overwrite simply turns into a miss rather than being rejected as outdated.
- Code references:
  - `backend/services/tts_service.py:87`
  - `backend/services/tts_service.py:233`
  - `backend/services/tts_service.py:243`
  - `backend/services/tts_service.py:271`
  - `backend/services/orchestrator.py:2457`
  - `backend/api/routes.py:257`
- Likely fix direction:
  - Version pre-generated entries by question hash or turn/version metadata, and reject late stale writes instead of letting a single session slot be overwritten blindly.

### 19. The interview UI can show candidate answers that the backend never accepted
- Severity: `medium`
- Confidence: `proven`
- Affected area: `app/interview/[session_id]/page.tsx`
- Why it matters: on any `processTurn` failure, the candidate's answer remains in the local transcript even though the server may not have committed it. That creates silent divergence between what the user thinks was recorded and what the backend will actually use for future turns, resume state, or the final report.
- Evidence:
  - `commitAnswerDraft(...)` appends or updates the candidate message in local UI before `processTurn(...)` returns.
  - if the request fails, the catch path shows an error and returns the floor to listening.
  - there is no rollback, pending-state marker, or refetch of canonical session state after failure.
- Code references:
  - `app/interview/[session_id]/page.tsx:416`
  - `app/interview/[session_id]/page.tsx:423`
  - `app/interview/[session_id]/page.tsx:503`
  - `app/interview/[session_id]/page.tsx:509`
- Likely fix direction:
  - Treat locally rendered candidate turns as pending until backend acknowledgement, and on failure either roll them back or resync from `/state/{session_id}` before letting the session continue.

### 20. Critical live interview state still lives in process-local sidecars
- Severity: `high`
- Confidence: `proven`
- Affected area: `backend/state/session_manager.py`, `backend/services/orchestrator.py`, `backend/services/tts_service.py`
- Why it matters: the repo still describes Redis as the state store, but several live interview correctness paths depend on Python-process-local memory. In multi-worker, serverless, or non-sticky routing setups, the system can lose partial entity accumulation, per-answer scores, speculative coordination, inflight guards, and pre-generated TTS hits even though the Redis session blob still exists.
- Evidence:
  - `SessionManager` persists only the Redis JSON blob.
  - the orchestrator keeps `_pipeline_inflight`, `_turn_pipeline_running`, `_per_answer_scores`, `_partial_entities`, `_partial_snapshot_meta`, and `_speculative_locks` in process memory.
  - `end_session()` consumes `_per_answer_scores` from that local memory for final evaluation.
  - `handle_transcript()` merges committed entities from `_partial_entities`, not from Redis.
  - `TTSService` keeps `_prepped_audio` only in process memory, so `/tts` fast-path hits are also worker-local.
- Code references:
  - `AGENTS.md:182`
  - `backend/state/session_manager.py:18`
  - `backend/services/orchestrator.py:647`
  - `backend/services/orchestrator.py:651`
  - `backend/services/orchestrator.py:653`
  - `backend/services/orchestrator.py:654`
  - `backend/services/orchestrator.py:655`
  - `backend/services/orchestrator.py:656`
  - `backend/services/orchestrator.py:850`
  - `backend/services/orchestrator.py:915`
  - `backend/services/orchestrator.py:957`
  - `backend/services/orchestrator.py:1055`
  - `backend/services/orchestrator.py:1907`
  - `backend/services/orchestrator.py:1925`
  - `backend/services/orchestrator.py:2630`
  - `backend/services/tts_service.py:84`
  - `backend/services/tts_service.py:87`
  - `backend/services/tts_service.py:233`
- Likely fix direction:
  - Move load-bearing live session adjuncts into Redis or another shared store with session/turn/version keys, or explicitly constrain deployment to sticky single-worker execution and document that as a hard runtime assumption.

### 21. Echo-suppression cooldown can plausibly drop real user answer openings
- Severity: `medium`
- Confidence: `plausible risk`
- Affected area: `lib/audio.ts`, `app/interview/[session_id]/page.tsx`
- Why it matters: immediately after AI playback ends, candidates often begin by repeating the same project name, technology, or noun phrase from the question. The browser transcript handler can treat that early answer text as AI echo and discard it, which risks clipping the start of real answers and delaying the handoff into the committed-turn path.
- Evidence:
  - transcript handling drops any non-empty text that `isLikelyAiEcho(...)` matches.
  - `recentAiTextNorm` is retained for `aiEchoCooldownMs` after AI speech ends.
  - `isLikelyEchoSnippet(...)` accepts substring and word-overlap matches, not just exact playback bleed.
  - the interview page resumes listening almost immediately after the 300ms post-playback drain, so valid candidate speech can land inside that cooldown window.
- Code references:
  - `lib/audio.ts:44`
  - `lib/audio.ts:65`
  - `lib/audio.ts:140`
  - `lib/audio.ts:200`
  - `lib/audio.ts:390`
  - `app/interview/[session_id]/page.tsx:365`
  - `app/interview/[session_id]/page.tsx:374`
- Likely fix direction:
  - Narrow post-playback echo rejection to stronger evidence than generic lexical overlap, and re-tune the cooldown window so the first legitimate answer fragment is less likely to be mistaken for speaker bleed.

## Low / Quality Debt

### 22. Runtime no longer matches the documented prompt-chain isolation model
- Severity: `low`
- Confidence: `proven`
- Affected area: `AGENTS.md`, `backend/services/orchestrator.py`
- Why it matters: the repo still documents a clean JSON-only agent chain, but the live runtime now fans raw transcript, raw resume text, parsed resume, and rebuilt memory context out to multiple agents in parallel. That increases token duplication, encourages inconsistent interpretation across agents, and makes the architecture harder to reason about because the docs and code no longer describe the same system.
- Evidence:
  - `AGENTS.md` says agents never see raw transcripts and only receive JSON from the preceding agent.
  - the background pipeline builds `memory_context` from history/candidate-model state and sends raw `text`, `resume`, and `parsed_resume` directly to multiple agents.
- Code references:
  - `AGENTS.md:176`
  - `backend/services/orchestrator.py:1986`
  - `backend/services/orchestrator.py:2007`
  - `backend/services/orchestrator.py:2023`
  - `backend/services/orchestrator.py:2032`
  - `backend/services/orchestrator.py:2048`
- Likely fix direction:
  - Either update the architecture/docs to reflect the shared-context fan-out design, or reintroduce an explicit typed intermediate contract so agents consume normalized upstream outputs rather than overlapping raw context.

### 23. Frontend telemetry is unbatched and the most important playback events are not session-scoped
- Severity: `low`
- Confidence: `proven`
- Affected area: `lib/audio.ts`, `app/interview/[session_id]/page.tsx`, `backend/api/routes.py`
- Why it matters: observability is now part of the live data highway, but it still behaves like ad hoc debug logging. The frontend emits one `/telemetry` POST per event, there are 20 call sites in `lib/audio.ts` and 20 more in the interview page, and `playAudioUrl()` logs completion/abort/fallback under `"system"` instead of the real session id. That adds avoidable side traffic and weakens per-session playback diagnosis.
- Evidence:
  - `trackInterviewEvent()` issues a standalone `fetch(.../telemetry)` call.
  - the audio file and interview page each contain 20 call sites for that helper.
  - playback and filler events in `playAudioUrl()` / `prefetchFillerAudio()` use `"system"` rather than the active interview session id.
- Code references:
  - `lib/audio.ts:7`
  - `lib/audio.ts:15`
  - `lib/audio.ts:609`
  - `lib/audio.ts:659`
  - `lib/audio.ts:669`
  - `lib/audio.ts:692`
  - `backend/api/routes.py:232`
- Likely fix direction:
  - Batch client telemetry per turn or short interval, and thread the real `session_id` through playback/filler helpers so session traces capture the actual user-perceived audio lifecycle.

### 24. Startup swallows subsystem failures too aggressively
- Severity: `low`
- Confidence: `proven`
- Affected area: `backend/main.py`
- Why it matters: broken warmup, Postgres init, or question-bank load can look like a healthy boot and only surface later as degraded behavior.
- Code references:
  - `backend/main.py:39`
  - `backend/main.py:45`
  - `backend/main.py:52`
- Likely fix direction:
  - Log explicit degraded-mode startup state instead of silently swallowing all failures.

### 25. Dockerfile uses `uvicorn --reload` by default
- Severity: `low`
- Confidence: `proven`
- Affected area: `Dockerfile`
- Why it matters: this is a dev-only flag and a poor default for a deployment image.
- Code references:
  - `Dockerfile:10`
- Likely fix direction:
  - Separate dev and prod entrypoints.

### 26. `TTSService` has no shutdown path for its shared HTTP client
- Severity: `low`
- Confidence: `proven`
- Affected area: `backend/services/tts_service.py`
- Why it matters: long-lived clients should be closed cleanly during app shutdown.
- Code references:
  - `backend/services/tts_service.py:86`
- Likely fix direction:
  - Add an app shutdown hook that closes the shared `httpx.AsyncClient`.

## Verification Notes

- Python compile pass succeeded during audit:
  - `python -m compileall backend api`
- Frontend build was not runnable in this workspace because `next` is not installed locally.
- Local dependency check confirmed:
  - `faiss`: missing
  - `sentence_transformers`: missing
  - `numpy`: present

## Highest-Risk Files

The audit found the highest concentration of correctness risk in:
- `backend/services/orchestrator.py`
- `backend/state/session_manager.py`
- `app/interview/[session_id]/page.tsx`
- `lib/audio.ts`
- `backend/api/routes.py`

These are the best starting points for the first round of fixes.
