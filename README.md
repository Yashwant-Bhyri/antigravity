# Antigravity — AI Adversarial Interview Engine

A real-time voice-based cognitive evaluation system. Not a chatbot. Not a quiz engine.
**Probe → Break → Analyze → Adapt.**

---

## What it does

Conducts a 30-minute adversarial technical interview across 3 sprints:

| Sprint | Duration | Persona | Goal |
|--------|----------|---------|------|
| Project Defense | 0–10 min | Curious Lead | Attack ownership, design decisions, failure modes |
| Foundations | 10–20 min | Socratic Mentor | Test first principles, no buzzwords |
| System Design | 20–30 min | Senior Peer | Chaos injection, scaling trade-offs, real failures |

At the end: a full evaluation report with scores, failure surface, and **HIRE / MAYBE / NO HIRE**.

---

## Architecture

```
Browser mic (PCM16)
    ↓ Deepgram SDK (browser-side, direct to Deepgram — key via /deepgram_token)
Deepgram nova-3 ASR (streaming)
    ↓ Turn Engine: FloorManager + BargeInController + CV TurnEndScore
    ↓ partial → entity accumulation (timing only, no LLM)
    ↓ final   → committed utterance → parallel agents
                 ├─ WeaknessAgent       ← most important
                 ├─ ConceptAgent
                 ├─ DiscrepancyAgent
                 └─ ReasoningBehaviorAgent
    ↓
Orchestrator selects follow-up (discrepancy → weakness → sprint question)
    ↓
ElevenLabs TTS (filler-first, ~75ms first chunk)
    ↓
Browser plays audio (AbortController for barge-in)
```

**On session end:** EvaluationAgent (Opus) scores full transcript → report generated → persisted to Postgres.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python 3.11, async throughout |
| LLM | OpenRouter (Anthropic Claude — Haiku/Sonnet/Opus tiered) |
| ASR | Deepgram nova-3 — browser SDK (client-side direct, not backend relay) |
| TTS | ElevenLabs eleven_turbo_v2_5, streaming |
| Turn detection | FloorManager (audio VAD) + optional MediaPipe CV fusion |
| Session state | Redis (async, 1hr TTL) |
| Persistence | Postgres (completed sessions, recruiter dashboard) |
| RAG | FAISS local → Pinecone (prod) |
| Frontend | Next.js 14, App Router, TypeScript, Tailwind |

---

## Project Structure

```
antigravity/
├── backend/
│   ├── main.py                       ← FastAPI app + lifespan (TTS warmup, Postgres init)
│   ├── api/routes.py                 ← All endpoints
│   ├── services/
│   │   ├── orchestrator.py           ← Core brain: sprints, personas, agent dispatch
│   │   └── tts_service.py            ← ElevenLabs streaming + filler cache
│   ├── agents/
│   │   ├── weakness_agent.py         ← ⭐ Most important
│   │   ├── concept_agent.py
│   │   ├── followup_agent.py         ← 3 persona prompts + RAG-grounded sprint questions
│   │   ├── evaluation_agent.py       ← Full interview scorer (Opus)
│   │   ├── discrepancy_agent.py
│   │   ├── resume_agent.py
│   │   └── reasoning_behavior_agent.py
│   ├── rag/
│   │   ├── faiss_store.py            ← FAISS index + sentence-transformers embeddings
│   │   └── question_bank.py          ← Question retrieval wrapper
│   ├── db/
│   │   └── postgres.py               ← Async Postgres (session persistence)
│   ├── models/llm_router.py          ← OpenRouter, tiered routing
│   └── state/session_manager.py      ← Redis session state
├── frontend/
│   ├── app/
│   │   ├── page.tsx                  ← Landing / start interview
│   │   ├── interview/[id]/           ← Live voice interview UI + floor state
│   │   ├── report/[id]/              ← Full evaluation report
│   │   └── dashboard/                ← Recruiter dashboard
│   ├── lib/
│   │   ├── audio.ts                  ← InterviewSession: FloorManager, BargeIn, TTS
│   │   └── vision.ts                 ← CVSensor: MediaPipe turn prediction (opt-in)
│   └── components/Waveform.tsx       ← AIOrb + audio-reactive waveform
├── infra/docker-compose.yml
├── AGENTS.md                         ← Shared AI coordination file (Claude + Codex + Gemini)
├── COLLAB.md                         ← Async AI team discussion board
└── .env.example
```

---

## Running locally

**1. Clone and set up env**
```bash
git clone https://github.com/Yashwant-Bhyri/antigravity.git
cd antigravity
cp .env.example .env
# Fill in OPENROUTER_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, DATABASE_URL
```

**2. Start Redis**
```bash
brew install redis && brew services start redis
# or: docker-compose -f infra/docker-compose.yml up redis
```

**3. Start backend**
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

**4. Start frontend**
```bash
cd frontend
npm install
npm run dev   # runs on localhost:3000
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/start_interview` | Create session, parse resume, get opening question |
| POST | `/process_turn` | Submit full committed utterance → agents run → follow-up returned |
| POST | `/partial_transcript` | Entity accumulation during speech (timing only, no LLM) |
| GET | `/deepgram_token` | Vend Deepgram key to browser SDK |
| POST | `/tts` | Synthesize speech → MP3 stream |
| GET | `/tts_filler` | Pre-cached filler phrase → instant MP3 |
| POST | `/end_interview/{session_id}` | Trigger full evaluation + Postgres persist |
| GET | `/report/{session_id}` | Full report with hire recommendation |
| GET | `/state/{session_id}` | Raw session state |
| GET | `/sessions` | All completed sessions (recruiter dashboard) |

---

## AI Coordination

Built by three AI assistants in parallel:
**Claude Code** (Anthropic) + **Codex** (OpenAI) + **Antigravity** (Google Gemini)

See `AGENTS.md` for the shared context file — all AIs read/write it to stay in sync.
See `COLLAB.md` for async discussion between agents.
Always `git pull` before starting a session. Always `git push` after.
