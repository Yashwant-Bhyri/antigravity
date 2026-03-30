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
    ↓ WebSocket /stream/{session_id}
Deepgram nova-3 ASR (streaming)
    ↓ partial → concept extraction → speculative prefetch
    ↓ final   → parallel agents
                 ├─ WeaknessAgent      ← most important
                 ├─ ConceptAgent
                 └─ DiscrepancyAgent
    ↓
Orchestrator selects follow-up
    ↓
ElevenLabs TTS (filler-first streaming, ~75ms first chunk)
    ↓
Browser plays audio
```

**On session end:** EvaluationAgent (Opus) scores full transcript → report generated.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python 3.11, async throughout |
| LLM | OpenRouter (Anthropic Claude — Haiku/Sonnet/Opus tiered) |
| ASR | Deepgram nova-3, WebSocket streaming |
| TTS | ElevenLabs eleven_turbo_v2_5, streaming |
| Session state | Redis (async) |
| Frontend | Next.js 14, App Router, TypeScript, Tailwind |

---

## Project Structure

```
antigravity/
├── backend/
│   ├── main.py                    ← FastAPI app + CORS
│   ├── api/routes.py              ← All endpoints + WebSocket
│   ├── services/
│   │   ├── orchestrator.py        ← Core brain: sprints, personas, flow
│   │   ├── asr_service.py         ← Deepgram WebSocket
│   │   └── tts_service.py         ← ElevenLabs streaming
│   ├── agents/
│   │   ├── weakness_agent.py      ← ⭐ Most important
│   │   ├── concept_agent.py
│   │   ├── followup_agent.py      ← 3 persona prompts
│   │   ├── evaluation_agent.py    ← Full interview scorer
│   │   ├── discrepancy_agent.py
│   │   ├── resume_agent.py
│   │   └── reasoning_behavior_agent.py
│   ├── models/llm_router.py       ← OpenRouter, tiered routing
│   └── state/session_manager.py   ← Redis session state
├── frontend/                      ← Next.js app
│   ├── app/
│   │   ├── page.tsx               ← Landing / start interview
│   │   ├── interview/[id]/        ← Live voice interview UI
│   │   ├── report/[id]/           ← Full evaluation report
│   │   └── dashboard/             ← Recruiter dashboard
│   ├── lib/audio.ts               ← Mic capture + TTS playback
│   └── components/Waveform.tsx    ← Animated waveform + mic pulse
├── infra/docker-compose.yml
├── AGENTS.md                      ← Shared AI coordination file
└── .env.example
```

---

## Running locally

**1. Clone and set up env**
```bash
git clone https://github.com/Yashwant-Bhyri/antigravity.git
cd antigravity
cp .env.example .env
# Fill in OPENROUTER_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY
```

**2. Start Redis**
```bash
docker-compose -f infra/docker-compose.yml up redis
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
| POST | `/start_interview` | Create session, get opening question |
| WS | `/stream/{session_id}` | Stream PCM16 audio, receive followups |
| POST | `/tts` | Synthesize speech → MP3 stream |
| POST | `/end_interview/{session_id}` | Trigger full evaluation |
| GET | `/report/{session_id}` | Full report with hire recommendation |
| GET | `/state/{session_id}` | Raw session state |

---

## AI Coordination

This project is built by two AI assistants in parallel:
**Claude Code** (Anthropic) + **Antigravity** (Google Gemini)

See `AGENTS.md` for the shared context file — both AIs read/write it to stay in sync.
Always `git pull` before starting a session. Always `git push` after.
