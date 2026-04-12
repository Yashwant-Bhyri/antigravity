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

---

## HANDOFF NOTES
> Time-sensitive notes from one AI to the other. Clear these once acknowledged.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-05**
- The root-cause hotfix for the "mid-thought fragment goes to LLM" bug is now in the frontend.
- `frontend/lib/audio.ts` no longer lets the CV score directly call `_flushUtterance()`. Vision now predicts only; meaning commit is still gated by Deepgram `UtteranceEnd` / safety flush.
- `frontend/app/interview/[session_id]/page.tsx` now invalidates the active turn immediately if new partial speech arrives while the app is still in `AI_THINKING`.
- This should stop the most visible failure mode: a prematurely committed fragment reaching TTS while the candidate has already resumed speaking.

**→ TO: Claude Code, Antigravity | FROM: Codex | Date: 2026-04-04**
- Frontend stale-response protection is now wired in `frontend/app/interview/[session_id]/page.tsx` and `frontend/lib/audio.ts`.
- Each committed utterance generates a `turn_id`, sends it through `/process_turn`, and silently drops late responses whose echoed `turn_id` no longer matches `currentTurnIdRef`.
- `endInterview()` and component unmount now invalidate the active `turn_id`.
- When `onBargeIn` lands in Gemini's floor manager, the intended invalidation hook is: `currentTurnIdRef.current = crypto.randomUUID()`.

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
