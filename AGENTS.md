# AGENTS.md — Shared AI Context File
> This file is the single source of truth for ALL AI assistants working on Antigravity.
> **Claude Code**, **Codex**, and **Antigravity (Gemini)** must all read this at the start of every session and update it after completing work.
> Yash edits this too when making decisions or giving direction.
> **⚠️ RULE: Always `git pull` before reading this file. Always `git push` after updating it.**

---

## 🤝 ONBOARDING — FOR ANY AI JOINING THIS PROJECT

**Welcome to Antigravity. Read this entire section before touching any code.**

### Who is on this team
| Agent | Role | Interface |
|-------|------|-----------|
| **Claude Code** | Primary backend + full-stack implementation, architecture decisions | Claude Code CLI (Yash's terminal) |
| **Codex** | Code generation, refactoring, implementation tasks | OpenAI Codex / ChatGPT |
| **Antigravity (Gemini)** | Full-stack, ideation, research, implementation | Google Gemini chat |
| **Yash** | Product owner, final decision maker | All of the above |

### Mandatory reading — go through EVERY LINE of these files before doing ANY work

**In `/Users/yash/antigravity/` (the project root):**
1. `AGENTS.md` ← you are here — read it entirely, every section
2. `PROJECT_STATE.md` ← **THE RELIGIOUS LOG BOOK.** Mandatory reading and mandatory update. Read the chronicle of the project's trajectory before doing any work.
3. `README.md` — project overview and API reference
4. `/Users/yash/Downloads/notes.md` — full PRD (Parts 1–5), the product vision, agent design, latency strategy, infra plan. This is the WHY behind every decision.

**Backend — read every file line by line:**
4. `backend/main.py` — FastAPI app entry, lifespan hooks, CORS
5. `backend/api/routes.py` — ALL endpoints: `/start_interview`, `/process_turn`, `/partial_transcript`, `/tts`, `/tts_filler`, `/end_interview`, `/state`, `/report`, `/deepgram_token`
6. `backend/services/orchestrator.py` — THE BRAIN. Parallel agent dispatch, attack strategy selection, sprint progression, prefetch logic. Most critical file in the backend.
7. `backend/services/tts_service.py` — ElevenLabs streaming TTS, filler cache warm-up
8. `backend/services/asr_service.py` — DEAD CODE. Do not use or modify. Frontend uses Deepgram SDK directly.
9. `backend/models/llm_router.py` — OpenRouter tiered model routing (Haiku/Sonnet/Opus)
10. `backend/state/session_manager.py` — Redis async session state, 1hr TTL
11. `backend/agents/concept_agent.py`
12. `backend/agents/weakness_agent.py` ← MOST IMPORTANT AGENT
13. `backend/agents/followup_agent.py`
14. `backend/agents/evaluation_agent.py`
15. `backend/agents/discrepancy_agent.py`
16. `backend/agents/resume_agent.py`
17. `backend/agents/reasoning_behavior_agent.py`

**Frontend — read every file line by line:**
18. `frontend/lib/audio.ts` — Deepgram browser SDK, utterance buffering, NER entity extraction, TTS utilities
19. `frontend/app/page.tsx` — Landing page (resume input)
20. `frontend/app/interview/[session_id]/page.tsx` — Main interview UI, filler-first response logic
21. `frontend/app/report/[session_id]/page.tsx` — Report display
22. `frontend/app/dashboard/page.tsx` — Recruiter dashboard (BLOCKED — needs `/sessions` backend endpoint)
23. `frontend/components/Waveform.tsx` — AIOrb, audio-reactive waveform
24. `frontend/app/layout.tsx`

**Config/Infra:**
25. `infra/docker-compose.yml`
26. `requirements.txt`
27. `frontend/package.json`
28. `.env.example` (never read `.env` directly — ask Yash for keys)

**Collaboration:**
29. `COLLAB.md` ← shared async discussion space between all AIs. Read it. Add to it when you have suggestions, questions, or critiques for the team.

### Rules you MUST follow
- Follow all conventions in the `## CONVENTIONS` section below exactly
- Never re-debate decisions in `## DECISIONS LOG` unless Yash explicitly reopens them
- Check `## IN PROGRESS` before starting work — don't duplicate
- After completing work: update `## COMPLETED`, `## DECISIONS LOG`, `## HANDOFF NOTES`
- **MANDATORY**: Update `PROJECT_STATE.md` with granular logs of **WHAT**, **WHY**, and **IMPACT** of every architectural shift or major code commit. This is non-negotiable.
- All cross-AI communication goes in `COLLAB.md`

---

## HOW TO USE THIS FILE

**Before starting any work:**
1. Read this entire file
2. Check `## In Progress` — don't duplicate work already being done
3. Check `## Decisions Log` — don't re-debate settled decisions
4. Check `## Conventions` — follow them exactly

**After completing work:**
1. Move your item from `## In Progress` to `## Completed`
2. Log what you did and any important decisions in `## Decisions Log`
3. Update `## Current State` if the architecture changed
4. **Update `PROJECT_STATE.md`** with granular logs (What, Why, Impact).
5. Flag anything the other AI needs to know in `## Handoff Notes`

---

## PROJECT IDENTITY

**Name:** Antigravity — AI Adversarial Interview Engine
**Location:** `/Users/yash/antigravity/`
**Goal:** A real-time voice-based cognitive interrogation system that probes the failure boundaries of a candidate's reasoning — not a chatbot, not a quiz engine.

**Core Loop:** User speaks → ASR streams → Parallel agents fire → Weakness detected → Follow-up generated → TTS responds instantly

**Philosophy:** Probe → Break → Analyze → Adapt. Never validate. Always attack the weakest point.

---

## CURRENT STATE

**Status:** Full end-to-end interview loop is live and running. All 7 agents wired. Frontend complete.

**Architecture note:** Audio flow is CLIENT-SIDE Deepgram SDK (not backend WebSocket relay). This was a deliberate change for latency. `asr_service.py` is preserved but unused — frontend uses `@deepgram/sdk` directly. The `/stream/{session_id}` WebSocket endpoint in the README is outdated.

**What exists and is FULLY WIRED:**
```
backend/
  main.py                          ✅ FastAPI + lifespan (filler cache warm on startup)
  api/routes.py                    ✅ All endpoints: /start_interview, /process_turn,
                                      /partial_transcript, /tts, /tts_filler, /end_interview,
                                      /state, /report
  services/
    orchestrator.py                ✅ Full: parallel 4-agent dispatch, discrepancy priority,
                                      attack strategy selection, per-answer scoring (async),
                                      reasoning behavior wired, sprint progression
    tts_service.py                 ✅ ElevenLabs streaming + filler pre-cache at startup
    asr_service.py                 🔲 Dead code — browser SDK used instead
  agents/
    concept_agent.py               ✅ Wired — partial + final transcript
    weakness_agent.py              ✅ Wired — context-aware (sprint, prior weaknesses)
    followup_agent.py              ✅ Wired — STRATEGY_MAP used in prompts,
                                      generate_discrepancy_challenge() method live
    evaluation_agent.py            ✅ Wired — Opus, accepts reasoning signals + per-answer scores
    discrepancy_agent.py           ✅ Wired — high severity triggers direct confrontation
    resume_agent.py                ✅ Wired — parses at session start, feeds all follow-ups
    reasoning_behavior_agent.py    ✅ Wired — runs in parallel, feeds final evaluation
  models/
    llm_router.py                  ✅ Tier-aware max_tokens: small=256, medium=768, large=2500
  state/
    session_manager.py             ✅ Redis async, 1hr TTL

frontend/
  app/page.tsx                     ✅ Landing page
  app/interview/[id]/page.tsx      ✅ True parallel filler-first: filler fires immediately,
                                      LLM + TTS prefetch run in parallel, zero gap on response
  app/report/[id]/page.tsx         ✅ Full report page
  app/dashboard/page.tsx           ⚠️ Frontend exists — blocked on /sessions backend endpoint
  lib/audio.ts                     ✅ playFiller(), prefetchAudio(), playAudioUrl()
  components/Waveform.tsx          ✅ AIOrb + audio-reactive waveform
```

**What does NOT exist yet:**
- `/sessions` list endpoint + Postgres persistence (dashboard blocked)
- RAG question bank (FAISS/Pinecone — not started)
- LangGraph StateGraph (raw asyncio works fine, low priority)
- Kafka/event bus (Redis Streams as fallback when needed)
- Tests (unit + simulation — none exist)
- GitHub Actions CI

---

## TECH STACK

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI + Python 3.11 | async throughout |
| LLM (Claude) | Anthropic SDK | Haiku/Sonnet/Opus tiered |
| LLM (Gemini) | Google Generative AI SDK | for tasks Yash routes there |
| Orchestration | LangGraph StateGraph | not yet implemented |
| Session state | Redis (async) | running in Docker |
| Event bus | Kafka (planned) | Redis Streams as fallback |
| ASR | Deepgram WebSocket | streaming partial transcripts |
| TTS | ElevenLabs | streaming, interruptible — **DECIDED** |
| Vector DB | FAISS (local dev) → Pinecone (prod) | RAG for question bank |
| Database | PostgreSQL | interview logs, scores |
| Deployment | Docker + Kubernetes | docker-compose for local |

---

## CONVENTIONS
> Follow these exactly. Do not deviate without updating this section.

1. **Agents never see raw transcripts.** They only receive JSON output from the preceding agent. Strict prompt chain isolation.
2. **All agent calls are async.** Use `asyncio.gather()` for parallel execution. Never block.
3. **LLM tier assignment:**
   - `small` (Haiku) → classification, concept extraction, resume parsing
   - `medium` (Sonnet) → weakness detection, follow-up generation, discrepancy
   - `large` (Opus) → evaluation scoring, deep reasoning
4. **State lives in Redis only.** Never pass full state as function arguments between services.
5. **Weakness severity drives branching.** `high` → dynamic LLM follow-up. `low/medium` → precomputed question from RAG bank.
6. **Filler-first TTS.** Always emit a filler token before the real response to mask latency.
7. **Python imports:** absolute imports only (`from backend.agents.x import X`), never relative.
8. **JSON outputs from all agents.** If LLM returns plain text, LLMRouter attempts to parse it. Agents must handle both `dict` and `str` returns gracefully.
9. **No sync Redis calls.** Use `redis.asyncio` everywhere.

---

## IN PROGRESS
> List who is working on what. Include AI name so we don't duplicate.

| Task | Owner | Notes |
|---|---|---|
| Frontend `turn_id` stale-response protection | Codex | `frontend/app/interview/[session_id]/page.tsx` + `frontend/lib/audio.ts`; depends on GM-1 |
| `/sessions` list endpoint (recruiter dashboard) | — | Dashboard page exists, needs backend endpoint + Postgres |
| LangGraph StateGraph wiring | — | Low priority — raw asyncio works fine for now |
| Postgres persistence (interview logs, session list) | — | Redis works for active sessions; need Postgres for history |
| Testing: unit tests for agents, simulation tests | — | No tests exist yet |


---

## COMPLETED

| Task | Done By | Date | Notes |
|---|---|---|---|
| Verified-startup interview map + compact focus keys | Codex | 2026-04-15 | `backend/services/orchestrator.py` now awaits `_seed_first_question()` and `_build_interview_map()` before `start_session()` returns, verifies non-empty `interview_trajectory_map`, and traces a compact map preview; `backend/api/routes.py` now returns `trajectory_focus_areas`; `backend/services/interview_map.py` now compacts fallback/LLM focus keys so they don’t balloon into raw-resume sentences; `frontend/app/interview/[session_id]/page.tsx` no longer waits on a background map and instead expects the startup state to already contain it; verified with `python3 -m py_compile` and `npm run build` |
| Raw-resume focus packs + trajectory-map retrieval hardening | Codex | 2026-04-15 | `backend/services/interview_map.py` now builds focus areas from raw-resume seeds plus exact supporting snippets, treats those snippets as source-of-truth in the map prompt, and no longer falls back to an arbitrary first focus area when overlap is weak; `backend/services/orchestrator.py` now passes focus-context/snippets into speculative, clarification, discrepancy, attack, bank-followup, sprint-question, and sprint-opener generation; `backend/agents/followup_agent.py` now lets speculative refine/keep contend with a relevant map candidate and requires clearer in-question pivot phrasing; `frontend/lib/audio.ts` normalized to `endpointing=1500` / `utterance_end_ms=2800`; verified with `python3 -m py_compile` and `npm run build` |
| Short-answer rescue hardening + generic-packet demotion | Codex | 2026-04-15 | `backend/services/orchestrator.py` no longer lets synthetic/generic packets outrank rescue/speculative candidates; rescue now covers 1–18 word answers, generic staged fallback can be overridden by speculative/rescue, and explicit rescue trace events were added; verified with `python3 -m py_compile` and a live terse-answer simulation against the local backend |
| Short-answer rescue + refine-or-keep speculative loop | Codex | 2026-04-15 | `backend/services/orchestrator.py` now tries one bounded `short_answer_rescue` Haiku call before generic fallback when a tiny answer arrives with nothing staged; `backend/agents/followup_agent.py` speculative generation now supports structured `keep` vs `replace` decisions using the current cached speculative question instead of blindly overwriting it on every new partial snapshot; verified with `python3 -m py_compile` and helper sanity checks |
| STT timing retune to `endpointing=1500` / `utterance_end_ms=2800` | Codex | 2026-04-15 | After analyzing live run `061852df-d640-4a05-a962-4c1ce7fbc739`, adjusted Deepgram timing in `lib/audio.ts` to trim perceived dead air without undoing the calmer turn-commit architecture: slightly faster utterance-end handoff, slightly calmer `is_final` chunking; intended follow-up work remains short-answer rescue + refine-or-keep speculative generation |
| Calmer STT boundaries + throttled interim partial snapshots | Codex | 2026-04-15 | Rolled `lib/audio.ts` back toward Deepgram-led turn boundaries (`utterance_end_ms=3000`, long safety timeout only), started sending throttled interim `/partial_transcript` snapshots with `is_final` + `snapshot_seq`, updated `backend/api/routes.py` + `backend/services/orchestrator.py` for stale-snapshot-safe speculative handling, and adjusted `app/interview/[session_id]/page.tsx` so normal UtteranceEnd commits bypass the old defensive hold; verified with `python3 -m py_compile`, `npm run build`, and a live local smoke test that recorded `api.partial_transcript` events in telemetry JSONL |
| Full interview telemetry + per-session trace capture | Codex | 2026-04-15 | Added `backend/services/interview_telemetry.py` plus `/api/telemetry` and `/api/telemetry/{session_id}`; instrumented backend routes, orchestrator fast/slow paths, TTS pre-generation/cache, and frontend audio/interview events so live runs now capture API calls, latencies, route decisions, flush reasons, playback timing, stale/revision behavior, and bottleneck/error events into `backend/runtime/interview_traces/{session_id}.jsonl`; smoke-tested endpoint readback and verified with `python3 -m py_compile` and `npm run build` |
| ElevenLabs live backend path restored | Codex | 2026-04-15 | Fixed `backend/main.py` dotenv resolution so the backend always loads repo-root env files with `.env` as the source of truth and `.env.local` only filling missing values; restarted the backend and verified `/api/tts_health` reports `last_provider_used=elevenlabs` with empty error state and live `/api/tts` returns `x-tts-provider: elevenlabs` plus valid MP3 audio |
| Packetized follow-up scheduling + immediate turn memory | Codex | 2026-04-15 | `backend/services/orchestrator.py` now uses `active_question_packet` / `prepped_next_packet` so current-thread follow-ups are deterministic and no longer starved by the next staged topic; committed answers now create immediate `history` skeletons and `_apply_staged_analysis()` enriches them in place by `turn_id`; seed staging now includes packet follow-ups; added `/api/tts_health` plus TTS runtime provider/config visibility; verified with `python3 -m py_compile` and a live sanity check where Turn 1 and Turn 2 both served `bank_followup_fast` |
| Follow-up continuity + anti-tunneling + STT calming pass | Codex | 2026-04-14 | `backend/services/orchestrator.py` now lets queued bank follow-ups beat generic staged pivots, preserves up to two follow-ups, and pivots sooner on repeated same-focus high-severity probing; `backend/agents/followup_agent.py` now seeds sprint questions from transition memory/topic anchors and discourages generic Sprint 3 prompts; `frontend/lib/audio.ts` and `app/interview/[session_id]/page.tsx` now gate early commit more conservatively and merge clustered finals with a 700ms settle window; `backend/services/tts_service.py` now enforces ElevenLabs as project policy; verified with `python3 -m py_compile` and `npm run build` |
| API base normalization + follow-up output hardening | Codex | 2026-04-14 | Added shared `lib/api.ts` so landing/interview/report/dashboard/audio all normalize `NEXT_PUBLIC_API_URL` consistently, restored landing-page `target_role` / `years_experience` validation, and hardened `followup_agent.py` so malformed LLM output is validated and replaced with route-specific fallback questions instead of leaking labels/JSON into the interview; verified with `python3 -m py_compile` and `npm run build` |
| Same-turn revision versioning + explicit ElevenLabs-default TTS | Codex | 2026-04-14 | `backend/services/orchestrator.py` now assigns backend-managed `answer_version`s to same-turn revisions, drops superseded staged analyses, and prevents older background runs from overwriting newer revisions; `backend/services/tts_service.py` now keeps ElevenLabs as the default provider unless `TTS_PROVIDER=cartesia` is explicitly set, while still allowing Cartesia fallback if ElevenLabs is unconfigured; verified with `python3 -m py_compile` and `npm run build` |
| Config precedence hardening + trajectory-map prompt hardening | Codex | 2026-04-15 | Added `backend/config/env_runtime.py` so TTS/model aliases resolve uniformly, changed `backend/main.py` so repo-root `.env` loads as base and `.env.local` overrides it, updated local override config to pin `TTS_PROVIDER=elevenlabs` plus the current OpenRouter tier models, and tightened `backend/services/interview_map.py` so generic/off-focus generated questions are rejected and replaced by deterministic fallbacks; verified with `python3 -m py_compile`, live `/api/tts_health`, and live `/api/tts` returning `x-tts-provider: elevenlabs` |
| Sprint continuity + anti-tunnel follow-up routing | Codex | 2026-04-14 | Added deterministic resume fallback parsing in `resume_agent.py`, focus-family tracking + finite contradiction/deflection budgets in `orchestrator.py`, and richer sprint handoff briefs / avoid-topic guidance in `followup_agent.py`; also fixed sprint handoff using the answered question instead of the next follow-up; verified with `python3 -m py_compile` and `npm run build` |
| Split-answer merge + backend staging hardening | Codex | 2026-04-14 | `app/interview/[session_id]/page.tsx` now merges late STT chunks into one candidate turn and supports same-turn revision with the same `turn_id`; `backend/services/orchestrator.py` now uses an ordered `prepped_turn_queue` instead of a single fragile staging slot; `lib/audio.ts` waits for audio readiness before playback; `EvaluationAgent` JSON example now includes `INSUFFICIENT_DATA`; verified with `python3 -m py_compile` and `npm run build` |
| Role/YOE-calibrated interview flow + report contract | Codex | 2026-04-14 | Added `target_role` + `years_experience` input on landing page, threaded calibration through `ResumeAgent` / `WeaknessAgent` / `EvaluationAgent`, added discrepancy levels (`none/suspected/confirmed`), report `untested_dimensions`, and a light breadth guard in `orchestrator.py`; verified with `python3 -m py_compile` and `npm run build` |
| Frontend turn-commit hotfix for mid-thought cutoff | Codex | 2026-04-05 | `frontend/lib/audio.ts` no longer lets CV directly flush utterances into the LLM path; `frontend/app/interview/[session_id]/page.tsx` now invalidates AI_THINKING turns as soon as the user resumes partial speech; verified with `npm run build` |
| Frontend `turn_id` stale-response protection | Codex | 2026-04-04 | `frontend/app/interview/[session_id]/page.tsx` + `frontend/lib/audio.ts`; sends `turn_id`, drops stale replies, invalidates on end/unmount, verified with `npm run build` |
| GM-2: Multimodal Turn Prediction (MediaPipe CV) | Antigravity | 2026-04-04 | `frontend/lib/vision.ts` + `audio.ts` fusion; Lip closure + Gaze prediction |
| GM-1: FloorManager + Transcript Accumulator + Barge-in | Antigravity | 2026-04-04 | `frontend/lib/audio.ts` refactored with interruption/abort support |
| Full project scaffold (all agents, router, session manager, API, Docker) | Claude Code | 2026-03-30 | See `/backend/` |
| Initial question bank seeded (3 questions) | Claude Code | 2026-03-30 | `data/question_bank/ml_questions.json` |
| Git initialized + first commit | Claude Code | 2026-03-30 | ✅ Done |
| GitHub private repo created + pushed | Antigravity | 2026-03-30 | ✅ Live at github.com/Yashwant-Bhyri/antigravity |
| AGENTS.md created (shared AI coordination protocol) | Claude Code | 2026-03-30 | ✅ Committed and pushed |
| Deepgram ASR fully wired (nova-3, streaming, partial+final callbacks) | Claude Code | 2026-03-30 | `backend/services/asr_service.py` |
| Orchestrator predictive prefetch on partial transcripts | Claude Code | 2026-03-30 | `on_partial_transcript()` in orchestrator |
| WebSocket endpoint `/stream/{session_id}` for audio streaming | Claude Code | 2026-03-30 | `backend/api/routes.py` |
| ElevenLabs TTS (eleven_turbo_v2_5, filler-first streaming) | Claude Code | 2026-03-30 | `backend/services/tts_service.py` |
| Sprint progression (5Q per sprint, auto-advance 1→2→3) | Claude Code | 2026-03-30 | `orchestrator.py` |
| Persona switching (curious_lead → socratic_mentor → senior_peer) | Claude Code | 2026-03-30 | `orchestrator.py` + `followup_agent.py` |
| Interview termination (30 min or sprint 3 exhausted) | Claude Code | 2026-03-30 | `orchestrator._is_complete()` |
| Full interview evaluation at session end (Opus model) | Claude Code | 2026-03-30 | `evaluation_agent.score_full_interview()` |
| FollowUpAgent rewrite: 3 persona prompts, no RAG, resume-grounded | Claude Code | 2026-03-30 | `backend/agents/followup_agent.py` |
| POST /end_interview endpoint | Claude Code | 2026-03-30 | `backend/api/routes.py` |
| Frontend: sprint dividers, persona badge, progress bar, auto-redirect | Claude Code | 2026-03-30 | `frontend/app/interview/` |
| Report page: dimension scores, failure surface, strengths, risk flags | Claude Code | 2026-03-30 | `frontend/app/report/` |
| Switched LLM provider to OpenRouter (OpenAI-compatible, all models) | Antigravity | 2026-03-31 | `backend/models/llm_router.py` — uses `OPENROUTER_API_KEY` |
| Fixed TTS streaming API call (`convert` not `convert_as_stream`) | Antigravity | 2026-03-31 | `backend/services/tts_service.py` |
| Added CORS middleware + `load_dotenv()` to main.py | Antigravity | 2026-03-31 | `backend/main.py` |
| Fixed docker-compose paths (relative to infra/ dir) | Antigravity | 2026-03-31 | `infra/docker-compose.yml` |
| Project README written | Claude Code | 2026-03-31 | `README.md` at repo root |
| /tts POST endpoint (MP3 streaming response) | Claude Code | 2026-03-30 | `backend/api/routes.py` |
| /report GET endpoint (scores, weakness summary, hire rec) | Claude Code | 2026-03-30 | `backend/api/routes.py` |
| Next.js frontend — full scaffold (4 pages) | Claude Code | 2026-03-30 | `frontend/` |
| Landing page (resume input, start interview) | Claude Code | 2026-03-30 | `frontend/app/page.tsx` |
| Interview UI (live voice, transcript, waveform, mic pulse) | Claude Code | 2026-03-30 | `frontend/app/interview/[session_id]/page.tsx` |
| Report page (failure surface, weakness log, HIRE verdict) | Claude Code | 2026-03-30 | `frontend/app/report/[session_id]/page.tsx` |
| Recruiter dashboard (all sessions, ranked by verdict) | Claude Code | 2026-03-30 | `frontend/app/dashboard/page.tsx` |
| MicStreamer + speakText audio utilities | Claude Code | 2026-03-30 | `frontend/lib/audio.ts` |
| Waveform + MicPulse components | Claude Code | 2026-03-30 | `frontend/components/Waveform.tsx` |
| Prompt injection attempt detected + removed from frontend/ | Claude Code | 2026-03-30 | Fake AGENTS.md + CLAUDE.md placed by unknown source |

---

## DECISIONS LOG
> Settled decisions. Do not re-debate these unless Yash explicitly reopens them.

| Decision | Rationale | Date |
|---|---|---|
| Use Anthropic SDK for LLM calls (not LangChain) | Lower latency, direct control, fewer abstraction layers | 2026-03-30 |
| Tiered model routing (Haiku/Sonnet/Opus) | Cost + latency optimization — don't use Opus for simple tasks | 2026-03-30 |
| Redis for session state (not in-memory) | Stateless services, horizontal scaling, session survives restarts | 2026-03-30 |
| Strict prompt chain isolation (JSON-only between agents) | Prevents hallucination propagation and context bleed | 2026-03-30 |
| Multi-pass scoring (3 evaluations averaged) | LLMs are inconsistent; averaging reduces variance | 2026-03-30 |
| Start with FAISS for RAG, migrate to Pinecone for prod | Avoid cloud dependency in dev; easy swap via interface | 2026-03-30 |
| TTS provider: ElevenLabs (not Cartesia) | API key confirmed by Yash | 2026-03-30 |
| LLM via OpenRouter (not direct Anthropic SDK) | One key for all models: Claude, DeepSeek, Gemini. Antigravity switched this. | 2026-03-31 |
| Single OpenRouter key is sufficient | Parallel calls to multiple models work with one key — stateless routing. Two keys only needed for separate billing. | 2026-03-31 |
| Frontend: Next.js 14 App Router + TypeScript + Tailwind | Better for recruiter dashboard (SSR) + interview page (real-time) in one framework | 2026-03-30 |
| V1 scope: full product (candidate + recruiter dashboard + reports) | Yash confirmed — build everything, deploy later | 2026-03-30 |
| Audio flow: client-side Deepgram SDK (NOT backend WS relay) | Lower latency, simpler architecture. Key exposed via /deepgram_token — acceptable for internal tool. Original decision reversed. | 2026-04-01 |
| Interview calibration should be role/level-relative, not a universal senior bar | Prevents modest ownership claims from being over-probed and lets reports mark under-tested dimensions as inconclusive rather than low | 2026-04-14 |
| Interim STT snapshots are speculative-only; canonical turns still require a real utterance boundary | Lets the backend prepare better follow-ups from live speech without allowing unstable interim text to fragment history or trigger immature interruptions | 2026-04-15 |
| With interim snapshots in place, `endpointing` should be tuned for chunk quality, not ultra-fast commit | We now rely on `utterance_end_ms` for actual turn commit; a slightly higher `endpointing` can reduce speculative churn without reintroducing the old interruption bug | 2026-04-15 |
| Short answers deserve one bounded rescue attempt before generic fallback | Very short answers are where the live loop was still collapsing; a small fast-path rescue is a better trade-off than instantly serving a generic sprint fallback | 2026-04-15 |

---

## HANDOFF NOTES
> Time-sensitive notes from one AI to the other. Clear these once acknowledged.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- The latest raw-resume/focus-pack hardening is local only. Nothing was pushed.
- `backend/services/interview_map.py` now uses exact raw-resume snippets as the canonical grounding for each focus area and no longer returns an arbitrary first focus area when retrieval is uncertain. This was a real prompt-pollution risk in the earlier selector.
- `backend/services/orchestrator.py` now passes focus-context + exact snippets into speculative generation, discrepancy/clarification/attack probes, adapted bank follow-ups, sprint questions, and sprint openers. Speculative generation can now compare the rolling partial transcript against both `current_best_question` and a relevant interview-map candidate.
- Important mismatch to keep in mind: the live code still does **not** block `start_session()` on `_build_interview_map()`. It still uses `asyncio.create_task(...)` for `_seed_first_question()` and `_build_interview_map()`. Some recent `COLLAB.md` prose claimed `await asyncio.gather(...)`; that is not true in the current code.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-05**
- The root-cause hotfix for the "mid-thought fragment goes to LLM" bug is now in the frontend.
- `frontend/lib/audio.ts` no longer lets the CV score directly call `_flushUtterance()`. Vision now predicts only; meaning commit is still gated by Deepgram `UtteranceEnd` / safety flush.
- `frontend/app/interview/[session_id]/page.tsx` now invalidates the active turn immediately if new partial speech arrives while the app is still in `AI_THINKING`.
- This should stop the most visible failure mode: a prematurely committed fragment reaching TTS while the candidate has already resumed speaking.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-04**
- Frontend stale-response protection is now wired in `frontend/app/interview/[session_id]/page.tsx` and `frontend/lib/audio.ts`.
- Each committed utterance generates a `turn_id`, sends it through `/process_turn`, and silently drops late responses whose echoed `turn_id` no longer matches `currentTurnIdRef`.
- `endInterview()` and component unmount now invalidate the active `turn_id`.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-14**
- Role/YOE calibration is now live in code.
- Landing page collects `target_role` + `years_experience`; `/start_interview` stores them in session state.
- `ResumeAgent` now emits richer ownership/claim context; `WeaknessAgent` and `EvaluationAgent` use that plus role/YOE to calibrate pressure.
- `DiscrepancyAgent` now distinguishes `suspected` from `confirmed`.
- `EvaluationAgent` can return `INSUFFICIENT_DATA` and `untested_dimensions`; report page renders those safely.
- `orchestrator.py` now has a light breadth guard to avoid repeatedly tunneling on the same weakness family without a confirmed contradiction.
- When `onBargeIn` lands in Gemini's floor manager, the intended invalidation hook is: `currentTurnIdRef.current = crypto.randomUUID()`.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-14**
- The broken session `f905995d-6897-45c1-a491-0bf6f9ee8003` matched a real split-answer bug, not just user error.
- `app/interview/[session_id]/page.tsx` no longer turns a late `onFinal` fragment into a fresh answer turn; it now merges chunks into an `AnswerDraft`, waits a short settle window, and if another chunk arrives mid-processing it resubmits as a same-turn revision with the same `turn_id`.
- `backend/services/orchestrator.py` now treats same `turn_id` submissions as same-turn revisions and no longer relies on a single `prepped_turn_analysis` slot; queued analyses are ordered and consumed later, so `question_count` and `history` should stop drifting apart under fast successive turns.
- The exact UI regression path was already present in the `6c7fea5` interview-page changes (`processingRef` + `pendingFinalRef` replay path). `7e9b63e` made turn boundaries more likely to surface under load, but it was not the sole cause.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-14**
- The dummy-candidate session `6132c99e-34f4-4c05-a462-66bf1248d50b` exposed two real behavior issues:
  - sprint transitions still felt cold
  - contradiction pressure on the Wondershare internship was allowed to dominate too long
- Fixes now in code:
  - `resume_agent.py` backfills parsed resume structure heuristically when the LLM parse is sparse, so follow-ups and sprint openers have stronger grounding even when the small-model parse underperforms
  - `orchestrator.py` now tags each turn with a focus family and applies finite budgets for repeated deflection / contradiction on the same focus before forcing broader exploration
  - `_maybe_advance_sprint()` now uses the question the candidate actually answered when building sprint handoff memory; previously it could accidentally hand off the next follow-up question instead
  - `followup_agent.py` now gets continuity briefs + over-probed topics to avoid so sprint openers/questions feel more connected and less cold

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-14**
- I took the remaining backend robustness fixes directly.
- `backend/services/orchestrator.py` now carries a backend-managed `answer_version` for each committed same-turn revision, stores `latest_turn_versions` in Redis session state, and discards superseded staged analyses before they can mutate canonical history. This removes the old timing assumption where an older background pipeline could still win by finishing later.
- `_pipeline_inflight` is now keyed by `(session_id, turn_id, answer_version)`, so only exact duplicate work is suppressed; same-turn revisions are still allowed to run.
- `backend/services/tts_service.py` now realigns provider selection to the existing project decision: ElevenLabs remains the default when `TTS_PROVIDER` is unset, Cartesia is explicit opt-in via `TTS_PROVIDER=cartesia`, and Cartesia is only used implicitly when ElevenLabs is entirely unconfigured.
- Verified with `python3 -m py_compile` and `npm run build`.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-14**
- I fixed the remaining integrated-review issues directly.
- Added shared `lib/api.ts` so frontend fetches now normalize `NEXT_PUBLIC_API_URL` consistently to include `/api`; this is now used by the landing page, interview page, report page, dashboard, and `lib/audio.ts`.
- `backend/agents/followup_agent.py` now validates cleaned LLM question output before returning it. Serialized JSON strings with a `question` field are extracted, label-only / blob-like outputs are rejected, and each generation path now has a route-specific fallback question instead of trusting `_clean_question_output()` blindly.
- `app/page.tsx` once again requires `target_role` and `years_experience` before interview start, restoring the role/YOE calibration contract.
- Verified with `python3 -m py_compile` and `npm run build`.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-14**
- I took a direct pass on the persistent live-interaction complaints: missing follow-ups, same-concept tunneling, vague Sprint 3 starts, over-eager STT commit, and TTS provider drift.
- `backend/services/orchestrator.py` now prioritizes queued bank follow-ups ahead of generic staged sprint pivots, preserves up to two follow-up templates, and keeps remaining follow-ups alive after a `bank_followup_fast` turn instead of overwriting them immediately. I also tightened repeated same-focus pivoting for high-severity non-recovering turns.
- `backend/agents/followup_agent.py` now queries sprint seeds using transition memory + latest topic anchor + weakness hints, and the sprint prompts explicitly ban generic stock design questions unless they match candidate context.
- `frontend/lib/audio.ts` no longer treats speculative early-commit like a forced flush: early-commit now requires a substantive utterance, Deepgram end-of-utterance timing is looser, and the hard cap is longer. `app/interview/[session_id]/page.tsx` now uses `ANSWER_SETTLE_MS = 700` so clustered final chunks merge before `processTurn`.
- `backend/services/tts_service.py` now enforces ElevenLabs as project policy even if `TTS_PROVIDER=cartesia` is set; Cartesia is emergency fallback only when ElevenLabs credentials are absent.
- Verified with `python3 -m py_compile` and `npm run build`.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- I implemented the next architectural fix directly in `backend/services/orchestrator.py`: the interview loop now distinguishes the **current thread** from the **next parked topic** via `active_question_packet` and `prepped_next_packet`.
- The important behavioral change is that `handle_transcript()` no longer eagerly consumes `prepped_next_question` if the current question still has deterministic follow-ups left. That next topic stays parked until the current thread is exhausted or pivoted away from.
- Fast-path memory is now immediate: committed answers create a `history` skeleton with `analysis_status=\"pending\"`, and `_apply_staged_analysis()` enriches the same turn in place by `turn_id` instead of returning early on duplicates.
- I also added `TTSService.status_snapshot()` and `/api/tts_health` so we can see the live provider/config state during runtime debugging instead of guessing.
- Verified with `python3 -m py_compile`, `curl /api/tts_health`, and a live sanity check where Turn 1 and Turn 2 both served `bank_followup_fast` rather than generic sprint fallback.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- I fixed the remaining live ElevenLabs mismatch in `backend/main.py`.
- Root cause was config-loading drift: the running backend was not guaranteed to use the same repo-root env precedence as the successful direct ElevenLabs SDK probe.
- `backend/main.py` now resolves `.env` and `.env.local` from the project root, loads `.env` first with override, then loads `.env.local` only to fill missing values.
- After restart, startup no longer falls back during filler warm-up, `/api/tts_health` reports `last_provider_used=elevenlabs` with an empty error state, and live `/api/tts` now returns `x-tts-provider: elevenlabs` plus valid MP3 audio.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- I added full interview telemetry capture for the next live tests.
- New trace sink: `backend/services/interview_telemetry.py`, storing JSONL under `backend/runtime/interview_traces/{session_id}.jsonl`.
- New endpoints:
  - `POST /api/telemetry` for client-side/browser events
  - `GET /api/telemetry/{session_id}` for summary + recent events
- Instrumented:
  - backend API request timings
  - orchestrator fast-track / background-pipeline decisions and latencies
  - TTS pre-generation + cache hits
  - frontend floor transitions, flush reasons, processTurn/prefetch timings, hold/revoke behavior, and playback events
- Verified with a smoke event round-trip, `python3 -m py_compile`, and `npm run build`.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- I implemented Yash’s “send the real-time transcript too, but don’t let it prematurely act” idea directly.
- `lib/audio.ts` now sends throttled interim `/partial_transcript` snapshots with `turn_id`, `is_final`, and `snapshot_seq`; the backend still treats them as speculative-only.
- I rolled the frontend back toward the calmer STT behavior Yash preferred: Deepgram owns turn boundaries again (`utterance_end_ms=3000`), the custom early-commit/hard-cap commit path is gone, and only a long safety timeout remains as a defensive fallback.
- `backend/services/orchestrator.py` now rejects stale partial snapshots by sequence and uses the richer stream only for speculative prep / entity accumulation. Canonical turn history still only mutates in `handle_transcript()`.
- `app/interview/[session_id]/page.tsx` now skips the old defensive TTS hold on normal UtteranceEnd-backed finals; only safety-timeout commits remain defensive.
- Smoke-tested live against the running backend: both interim and final partial snapshots returned `200`, and the per-session JSONL trace recorded the new fields correctly.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- After reviewing live run `061852df-d640-4a05-a962-4c1ce7fbc739`, I retuned `lib/audio.ts` again:
  - `utterance_end_ms: 3000 -> 2800`
  - `endpointing: 1200 -> 1500`
- Reasoning: the calmer architecture fixed the interruption problem, so we can now shave a little dead air while also reducing `is_final` churn. Since interim snapshots already feed speculative prep, endpointing no longer has to be hyper-aggressive.
- Current speculative prompt context is still intentionally light: accumulated current-turn partial transcript + last question + sprint/persona + trimmed resume context. It does not yet include candidate-model memory or refine-or-keep logic.
- Later UX idea to keep in mind: when we intentionally pivot topics, the generated final question should include a natural bridge phrase in the same spoken utterance rather than using a separate filler fragment.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- I implemented the next two missing pieces:
  - `short_answer_rescue` in the fast path
  - refine-or-keep speculative generation
- `backend/services/orchestrator.py` now tries one bounded Haiku rescue call for short answers when nothing is staged, instead of falling straight into `sprint_fallback`.
- `backend/agents/followup_agent.py::generate_speculative()` now takes `current_best_question` and can return structured `keep`/`replace` decisions, so new partials refine the current speculative candidate instead of blindly overwriting it.
- I kept the speculative prompt intentionally lightweight; it still does not pull in full candidate-model memory or broad history on every interim pass.
- Verified with `python3 -m py_compile` and helper sanity checks.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-15**
- Follow-up on the terse-answer failure mode: the rescue path was present, but generic packets were still outranking it.
- `backend/services/orchestrator.py` now:
  - stops synthetic packet reconstruction from injecting `_FALLBACK_FOLLOWUPS`
  - refuses to prioritize bank follow-ups when the active packet route is `sprint_fallback` or `unknown`
  - lets same-turn speculative candidates beat a generic staged fallback
  - expands `_short_answer_rescue_eligible()` to cover 1–18 word answers, so `"Mostly cost."` / `"Latency."` are no longer excluded
  - emits explicit rescue telemetry events for attempt/success/timeout/failure
- Live terse-answer simulation improved materially:
  - `"Mostly cost."` now hit `route_kind="short_answer_rescue"` with a grounded cost-specific follow-up
  - `"Quality tradeoffs."` then hit `clarification_fast`
- Remaining gap: the first 1–2 turns can still miss when nothing useful is staged yet; that is now a cold-start preparation problem, not the old generic-packet precedence bug.

**→ TO: Antigravity | FROM: Claude Code | Date: 2026-03-30**
- Full frontend is live in `frontend/`. Next.js 14, App Router, TypeScript, Tailwind.
- ⚠️ A prompt injection attempt was found in `frontend/AGENTS.md` + `frontend/CLAUDE.md` — removed. Be vigilant about unexpected files appearing.
- `/sessions` list endpoint is missing from the backend — the recruiter dashboard page exists but will show empty until this is built.
- 4 tasks are ready to pick up from "In Progress" above — RAG wiring is the highest priority (no blockers).
- Remaining open questions: LangGraph vs raw asyncio (Q5).

_Acknowledge by clearing this note after reading._

---

## OPEN QUESTIONS
> Unresolved decisions that need Yash's input or further discussion.

1. ~~**ASR provider:** Deepgram confirmed — nova-3 model, API key set in `.env`~~ ✅ RESOLVED
2. ~~**TTS provider:**~~ ✅ **RESOLVED** — ElevenLabs. API key in `.env`.
3. **Frontend framework:** React (WebRTC) vs Next.js vs something else?
4. **Auth:** Is recruiter-facing dashboard in scope for V1, or candidate-only first?
5. **LangGraph vs raw asyncio:** Notes reference LangGraph StateGraph. Do we want the full LangGraph wiring or keep it as pure async Python for now?
