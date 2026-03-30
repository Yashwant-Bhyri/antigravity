# AGENTS.md — Shared AI Context File
> This file is the single source of truth for both AI assistants working on Antigravity.
> **Claude Code** and **Antigravity (Gemini/AI chat)** must both read this at the start of every session and update it after completing work.
> Yash edits this too when making decisions or giving direction.
> **⚠️ RULE: Always `git pull` before reading this file. Always `git push` after updating it.**

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
4. Flag anything the other AI needs to know in `## Handoff Notes`

---

## PROJECT IDENTITY

**Name:** Antigravity — AI Adversarial Interview Engine
**Location:** `/Users/yash/antigravity/`
**Goal:** A real-time voice-based cognitive interrogation system that probes the failure boundaries of a candidate's reasoning — not a chatbot, not a quiz engine.

**Core Loop:** User speaks → ASR streams → Parallel agents fire → Weakness detected → Follow-up generated → TTS responds instantly

**Philosophy:** Probe → Break → Analyze → Adapt. Never validate. Always attack the weakest point.

---

## CURRENT STATE

**Status:** Scaffold complete. No agent is wired to a real LLM yet — all `call()` paths exist but need real prompts validated and tested.

**What exists:**
```
backend/
  main.py                          ✅ FastAPI entry point
  api/routes.py                    ✅ /start_interview, /process_speech, /get_state
  services/
    orchestrator.py                ✅ Skeleton — parallel agent dispatch
    asr_service.py                 🔲 Stub — needs Deepgram WebSocket integration
    tts_service.py                 🔲 Stub — needs ElevenLabs/Cartesia integration
  agents/
    concept_agent.py               ✅ Prompt written, wired to LLMRouter
    weakness_agent.py              ✅ Prompt written, wired to LLMRouter ⭐
    followup_agent.py              ✅ Prompt + strategy map written
    evaluation_agent.py            ✅ Multi-pass scoring skeleton
    discrepancy_agent.py           ✅ Prompt written
    resume_agent.py                ✅ Prompt written
    reasoning_behavior_agent.py    ✅ Prompt written
  models/
    llm_router.py                  ✅ Tiered routing: Haiku → Sonnet → Opus (Anthropic)
  state/
    session_manager.py             ✅ Redis async read/write
  data/
    question_bank/ml_questions.json  ✅ 3 sample questions seeded
```

**What does NOT exist yet:**
- RAG retrieval (vector DB not wired up)
- LangGraph StateGraph (pseudocode only in notes, not implemented)
- Kafka/event bus (docker-compose only has Redis for now)
- Frontend (WebRTC voice UI)
- Evaluation dashboard / recruiter UI
- Tests (unit + simulation)
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
| `/sessions` list endpoint (recruiter dashboard) | — | Dashboard page exists, needs backend endpoint + Postgres |
| LangGraph StateGraph wiring | — | Low priority — raw asyncio works fine for now |
| Postgres persistence (interview logs, session list) | — | Redis works for active sessions; need Postgres for history |
| Testing: unit tests for agents, simulation tests | — | No tests exist yet |

---

## COMPLETED

| Task | Done By | Date | Notes |
|---|---|---|---|
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
| Audio flow: browser → backend WS → Deepgram (not client-side SDK) | API keys never in browser; full control + logging | 2026-03-30 |

---

## HANDOFF NOTES
> Time-sensitive notes from one AI to the other. Clear these once acknowledged.

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
