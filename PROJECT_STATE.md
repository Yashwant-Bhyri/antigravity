# PROJECT_STATE.md — The Religious Log Book

> This is the single source of truth for the **Project Trajectory**. 
> Every agent (Claude, Codex, Antigravity) MUST update this file after every major change. 
> We track not just what we did, but **WHY**, the **IMPACT**, and the **DRIVE** behind every architectural shift.

---

## 🧭 CORE TRAJECTORY
| Phase | Goal | Rationale | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1: Interrogator** | Purely adversarial cognitive interrogation. | Test the failure boundaries of reasoning. | ✅ Complete |
| **Phase 2: Robust Validator** | Balance interrogation with curiosity and technical validation. | Foster meaningful technical exchange; reward intellectual honesty. | 🏃 In Progress |
| **Phase 3: Real-Time Flow** | Eliminate dead air and conversational lag. | Move from sequential 10s pauses to a 500ms "Two-Track" response system. | 🏃 In Progress |

---

## 📜 STEP-BY-STEP ACTIVITY LOG

### [2026-04-15] — Full Interview Telemetry + Session Trace Capture
- **WHAT**: Added a new append-only telemetry sink in `backend/services/interview_telemetry.py` that writes per-session JSONL traces to `backend/runtime/interview_traces/{session_id}.jsonl`. Added `POST /api/telemetry` for browser/client events and `GET /api/telemetry/{session_id}` for summary + recent-event readback. Instrumented backend API routes, orchestrator fast-track/background-pipeline stages, TTS pre-generation/cache, and the frontend audio/interview loop (`lib/audio.ts`, `app/interview/[session_id]/page.tsx`) so live runs now record STT flush reasons, floor transitions, process-turn latency, route decisions, TTS provider/source/latency, playback events, same-turn reopen behavior, hold/revoke behavior, and warning/error/bottleneck events.
- **WHY**: Live testing was still surfacing rich qualitative failures ("no follow-ups", "cold pivots", "fragmented narration", "stalls"), but the codebase only had scattered `print` and `console.log` lines. That made it hard to distinguish frontend STT timing problems from backend route selection, cache misses, or slow background pipelines. We needed a single per-session trace that captures the entire interview lifecycle across browser + backend.
- **IMPACT**: The next live interview run is diagnosable end to end. We can now inspect one session trace and answer: which API calls happened, how long each stage took, whether TTS was prepped or live, why a flush occurred (`early_commit` / `utterance_end` / `hard_cap`), whether the turn reopened as a same-turn revision, what route kind the orchestrator selected, what the background pipeline was doing, and where stalls/fallbacks/errors occurred. This turns vague UX complaints into concrete, timestamped failure evidence.

### [2026-04-15] — ElevenLabs Live Backend Path Restored
- **WHAT**: Fixed `backend/main.py` so dotenv loading is resolved from the project root instead of the process working directory. The backend now loads `/Users/yash/antigravity/.env` first with override enabled, then loads `.env.local` only to fill missing values. Restarted the backend and re-verified the live TTS path end to end.
- **WHY**: Direct ElevenLabs SDK probes were succeeding from the same machine, but the live backend was still returning `x-tts-provider: cartesia`. That meant the account/provider itself was healthy and the mismatch had to be in the running backend config path. The old startup logic let cwd-relative / stale local env precedence drift away from the effective config used by the successful direct probe.
- **IMPACT**: The backend and direct probes now agree on provider credentials/config. Startup filler warming no longer falls back immediately, `/api/tts_health` reports `last_provider_used="elevenlabs"` with no active error, and live `/api/tts` is back to returning ElevenLabs MP3 audio instead of emergency Cartesia fallback.

### [2026-04-15] — Packetized Follow-Up Scheduling + Immediate Turn Memory
- **WHAT**: Refactored `backend/services/orchestrator.py` so the live interview loop now tracks an `active_question_packet` and a `prepped_next_packet` instead of relying on a loose mix of `prepped_next_question` plus opportunistic follow-up arrays. Each question packet carries the current thread’s question text, route kind, focus, and deterministic follow-up templates. `handle_transcript()` now prioritizes follow-ups from the current packet before consuming a parked next-topic packet. Also added immediate skeleton turn records to `history` on the fast path (`analysis_status="pending"`), and changed `_apply_staged_analysis()` to enrich those skeleton records in place by `turn_id` instead of skipping them as duplicates. Added lightweight TTS runtime visibility via `TTSService.status_snapshot()` and `/api/tts_health`.
- **WHY**: The core bug was architectural, not just prompt quality. The fast path was trying to both deepen the current topic and advance to the next topic, and the next-topic staging path kept starving or overwriting the deepening path. That made follow-ups disappear, continuity feel one turn late, and early turns collapse into generic fallback even when the background pipeline had already chosen the next topic. The history model also lagged behind the conversation because new memory only arrived when staged analysis was consumed later.
- **IMPACT**: The orchestrator now has an explicit notion of “current thread” versus “next topic,” which is the actual fix for early-turn follow-up starvation. Follow-ups are deterministic and can stay on-thread even when the next topic is already prepared. Turn memory lands immediately instead of one turn late, which should improve continuity and reduce `question_count/history` drift. TTS runtime state is also now inspectable in a live environment instead of opaque during failures.

### [2026-04-14] — Follow-Up Continuity + Anti-Tunneling + STT Turn-Calming Pass
- **WHAT**: Reworked follow-up sequencing in `backend/services/orchestrator.py` so queued bank follow-ups can beat generic staged sprint pivots, preserved up to two follow-up templates instead of a single one-shot slot, and stopped overwriting remaining follow-ups after a `bank_followup_fast` turn. Tightened the same-focus breadth guard so repeated high-severity non-recovering probes pivot sooner. Improved sprint question generation in `backend/agents/followup_agent.py` by querying the question bank with transition memory / topic anchor / weakness hints and by forbidding generic cold-start design prompts. On the frontend, slowed the STT commit path in `lib/audio.ts` and `app/interview/[session_id]/page.tsx`: early-commit now respects a real eligibility gate, Deepgram end-of-utterance timing is less eager, and clustered final chunks get a 700ms settle window before `processTurn`.
- **WHY**: Repeated live tests were still showing the same interaction failures despite earlier timing fixes: almost no real follow-ups, repeated drilling on the same concept, Sprint 3 questions feeling detached and generic, and natural narration getting split into many micro-turns / same-turn revisions. The previous architecture had structural causes for each of those behaviors, not just prompt-quality issues.
- **IMPACT**: The interview should now deepen more naturally before jumping topics, pivot away from dead-end contradiction loops sooner, enter Sprint 3 with stronger continuity, and stop interrupting hesitant speakers as aggressively. This is a user-experience hardening pass on the core live loop, not just a wording tweak.

### [2026-04-14] — Frontend API Contract Normalized + Follow-Up Output Safeguards
- **WHAT**: Added shared frontend API-base normalization in `lib/api.ts` and switched the landing page, interview page, report page, dashboard, and browser audio helper to use it. Restored landing-page enforcement of `target_role` and `years_experience`. Hardened `backend/agents/followup_agent.py` so raw/serialized/malformed LLM question output is validated and replaced with route-specific fallback questions when needed.
- **WHY**: The frontend had drifted into two incompatible API-base assumptions: the landing page normalized `NEXT_PUBLIC_API_URL` to `/api`, while the other pages used the raw env value directly. Separately, question-cleaning logic could still leak garbage like `Question:` or serialized payloads into the live interview if the LLM ignored formatting instructions. The landing page had also stopped enforcing the calibration inputs that the new role/YOE-relative interview flow depends on.
- **IMPACT**: Frontend fetch paths now share one API contract instead of depending on page-by-page assumptions. Interview question generation is safer under malformed LLM output and degrades to usable fallback prompts instead of blank/junk text. The role/YOE calibration path is once again consistently populated at interview start.

### [2026-04-14] — Revision-Safe Background Staging + TTS Provider Realignment
- **WHAT**: Added backend-managed `answer_version` tracking in `backend/services/orchestrator.py` for same-turn revisions. Staged analyses now carry version metadata, superseded staged items are dropped before canonical apply, and background runs self-discard if a newer revision exists for the same `turn_id`. Also restored ElevenLabs as the default TTS provider in `backend/services/tts_service.py`, with Cartesia preserved as explicit opt-in or fallback-only when ElevenLabs is unavailable.
- **WHY**: The prior same-turn revision logic still depended on timing assumptions: an older background pipeline could overwrite or be applied ahead of a fuller revised answer if it finished at the wrong time. Separately, the runtime had started silently switching to Cartesia whenever a Cartesia key existed, which conflicted with the project's settled TTS decision and made provider behavior environment-dependent.
- **IMPACT**: Same-turn revision handling is now version-safe instead of race-prone. Older analyses cannot mutate canonical history once a newer revision exists. TTS behavior is once again predictable: ElevenLabs remains the default contract, while Cartesia support stays available without silently changing the runtime path.

### [2026-04-15] — Calmer STT Boundaries + Interim Snapshots for Speculative Prep
- **WHAT**: Reworked the frontend/backend partial-transcript contract so `lib/audio.ts` now sends throttled interim `/partial_transcript` snapshots, not just Deepgram `is_final` blocks. Each snapshot carries `turn_id`, `is_final`, and `snapshot_seq`. At the same time, the frontend STT commit policy was rolled back toward a calmer Deepgram-led model: `utterance_end_ms=3000`, custom early-commit and hard-cap commit logic removed, and only a long safety timeout retained as a defensive fallback. `backend/api/routes.py` and `backend/services/orchestrator.py` now accept the richer partial payload, reject stale snapshots by sequence, and use them only for speculative prep / entity accumulation. `app/interview/[session_id]/page.tsx` now treats normal UtteranceEnd-backed finals as immediately settled and keeps the old defensive TTS hold only for safety-timeout commits.
- **WHY**: Live telemetry showed the “low-latency” path was actually hurting the experience: one natural answer could turn into many revisions, the AI repeatedly prepared follow-ups while the user was still talking, and the backend saw far less live context than the UI implied because pure interim text never reached `/partial_transcript`. The user explicitly preferred better turn integrity and good follow-ups over shaving the last 1-2 seconds.
- **IMPACT**: The backend now has richer real-time context for speculative follow-up prep without being allowed to treat unstable interim text as canonical interview history. Turn commits should be much less fragment-prone, interruptions should be less immature, and the system is now aligned around a clearer contract: speculative thinking can happen continuously, but committed action still waits for a real utterance boundary.

### [2026-04-15] — STT Timing Retune After First Stable Live Run
- **WHAT**: Tuned Deepgram timing in `lib/audio.ts` from `endpointing=1200 / utterance_end_ms=3000` to `endpointing=1500 / utterance_end_ms=2800`.
- **WHY**: Live run `061852df-d640-4a05-a962-4c1ce7fbc739` showed that the calmer commit architecture was doing its job: one natural answer now usually became one committed turn, with zero follow-up revocations while the user was still speaking. That gave us room to shave a bit of perceived dead air. Because interim snapshots now stream continuously to `/partial_transcript`, `endpointing` no longer needs to be ultra-low just to feed speculative prep; it can instead be tuned for calmer chunk quality.
- **IMPACT**: The system should hand off slightly faster after the user finishes, while also producing slightly fewer `is_final` fragments and speculative churn than the `1200` setting. This is an incremental timing optimization on top of the calmer architecture, not a return to the old early-commit behavior.

### [2026-04-14] — "Pure Vercel" Deployment Shift
- **WHAT**: Stripped heavy AI dependencies (FAISS, SentenceTransformers) and configured `vercel.json`.
- **WHY**: To shrink the backend from ~1GB to <50MB, enabling direct deployment as Vercel Serverless Functions.
- **IMPACT**: Infrastructure simplified from a Docker-hybrid (Railway/Vercel) to a unified Vercel-only deploy.

### [2026-04-14] — Stabilization: The Memory Core
- **WHAT**: Implemented `generate_sprint_opener` and initialized Turn 1 pre-seeding logic.
- **WHY**: To fix the "Cold Start" problem and ensure sprint transitions feel like a continuation, not a reset.
- **IMPACT**: AI persona feels significantly more intelligent and grounded in previous turns.

### [2026-04-07] — The Two-Track "Fast/Slow" Response Strategy
- **WHAT**: Proposed and refined the "Adversarial Shadow" two-track system in `COLLAB.md`.
- **WHY**: Yash reported 5-10s of dead air causing a "mechanical" feel.
- **IMPACT**: Eliminates conversational lag. The AI responds in <500ms (Fast Track) while planning the next adversarial probe in the background (Slow Track).

### [2026-04-13] — Dynamic Sprint Openers
- **WHAT**: `generate_sprint_opener()` added to `FollowUpAgent`. `_maybe_advance_sprint()` in orchestrator is now async and calls it at every sprint transition with the full prior sprint history (including current answer as a synthetic entry). Falls back to static `SPRINT_OPENERS` if LLM fails.
- **WHY**: Live test `a82b7820` confirmed static sprint openers produce cold-start questions that ignore all prior context. Turn 6 (sprint 2 opener) asked "pick one idea at the core of what you've built" after 5 turns drilling latent-space steering and feature map engine — candidate answered with a fragment.
- **IMPACT**: Sprint transitions now carry context forward. Opener references specific things said in the previous sprint. Haiku call adds ~300ms to the sprint transition turn (acceptable — only fires once per sprint).

### [2026-04-13] — LATER_EDITS.md Created
- **WHAT**: Created `/Users/yash/antigravity/LATER_EDITS.md` — structured backlog of deferred improvements.
- **WHY**: Multiple items identified in testing that aren't urgent but must not be forgotten (CV warmup, utterance_end_ms tuning, filler loop cooldown, faiss model reload bug, project_map, confession pivot, distress detection, weakness_summary rendering, stale response invalidation).
- **IMPACT**: Single place to track deferred work. Prevents re-discovering the same issues each session.

### [2026-04-13] — Two-Track Architecture Deployed + Tested (a82b7820)
- **WHAT**: First live test of the full two-track implementation from the prior session.
- **WHAT WORKED**: Mid-sprint turns (3+) serving prepped adversarial probes correctly. Turn 5 context-aware question confirms bg pipeline staging works. WeaknessAgent correctly identified vague ML claims, latent-space steering unsubstantiated, attribution ambiguity.
- **WHAT FAILED**: Turn 1 always hits raw fallback (no prepped_q on first turn ever). Sprint 2 opener was static (fixed above). bg pipeline may have failed on Turn 1 (first-run issue — not confirmed).
- **REMAINING GAP**: Turn 1 cold start — pre-seeding prepped_next_question at start_session with a Haiku resume-based question. Pending product decision.

### [2026-04-07] — Honesty Detection Logic
- **WHAT**: Updated `WeaknessAgent` and `ReasoningBehaviorAgent` to detect "Admitted Gaps."
- **WHY**: The system was attacking candidates for being honest about their limits, which is a desirable engineering trait.
- **IMPACT**: High-severity attacks are now downgraded to curious probes if the candidate admits a gap.

---

## 🛠️ EXPERIMENT & IDEAS LEDGER
| Idea | Status | Rationale / Outcome |
| :--- | :--- | :--- |
| **Backend ASR Service** | 🪦 Buried | Replaced by client-side Deepgram SDK for lower latency and simpler architecture. |
| **RAG-based Questioning** | 🧊 Shelved (v2) | Moving to a pre-seeded bank for v1 stability. |
| **Mic Throttling (Ghost-VAD)** | 🏗️ Active | Prevents the AI from hearing itself and causing a recursion loop (The Softmax Incident). |
| **HandoverManager** | 🏗️ Active | Prevents "Split Answer" bugs where a mid-thought pause triggers a premature AI response. |

---

## 🚨 REGRESSIONS & COMPLEXITY LOG
- **[2026-04-07] The "Stable Softmax" Echo Loop**: 
  - *Symptom*: AI began interviewing itself recursively.
  - *Cause*: Acoustic echo picked up AI output as user input.
  - *Fix*: Implementing Mic Throttling in the frontend.
- **[2026-04-07] The "Answer Splitter" Bug**:
  - *Symptom*: 3s silence flushes a partial thought, causing disjointed responses.
  - *Cause*: Hard timeout on `UtteranceEnd`.
  - *Fix*: Handover logic to detect trailing fragments.

---

## 🔄 RESURRECTED IDEAS
| Idea | Initially Rejected | Why it returned? |
| :--- | :--- | :--- |
| **Fast Haiku Adaptations** | Latency concerns | Necessary to ground deepening questions in <500ms. |

---
