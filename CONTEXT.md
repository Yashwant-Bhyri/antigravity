# ANTIGRAVITY — FULL CONTEXT DOCUMENT
> Paste this at the top of a new chat session. It contains the complete end-to-end picture
> of what exists, what every file does, what has been decided, and what is unfinished.
> After reading this, read the files listed in **§ FILE READING ORDER** — in that order.

---

## § 1. WHAT THIS IS

**Antigravity** is a real-time voice-based AI adversarial interview engine.

It is NOT a chatbot. It is NOT a quiz tool. It is a **cognitive interrogation system** that:
- Listens to a candidate speak (via microphone, live)
- Detects the exact point where their reasoning breaks down
- Generates a targeted follow-up that attacks that specific gap
- Adapts its persona and strategy across 3 escalating sprints
- Produces a hiring report with failure surface, claim credibility risk, and a HIRE/MAYBE/NO HIRE verdict

**Core philosophy:** Probe → Break → Analyze → Adapt. Never validate. Always find the weakest point.

**Who uses it:** Recruiters upload a candidate's resume. The system runs the interview. The recruiter reads the report.

**Current status:** Full end-to-end interview loop is live. Two real interviews have been run and analyzed. The system works but has had several behavioral bugs found and fixed through real usage.

---

## § 2. ARCHITECTURE OVERVIEW

```
CANDIDATE (browser)
    │
    ├── Microphone → Deepgram SDK (browser-side, nova-3, streaming)
    │       ├── is_final fragments → utteranceBuffer (accumulate)
    │       ├── UtteranceEnd (3s VAD silence) → flush → POST /process_turn
    │       └── Entities (NER) extracted by Deepgram, sent with transcript
    │
    ├── POST /process_turn → FastAPI backend
    │       │
    │       └── Orchestrator.handle_transcript()
    │               ├── WeaknessAgent.detect()    ─┐
    │               ├── DiscrepancyAgent.check()  ─┤ asyncio.gather() — parallel
    │               ├── ReasoningBehaviorAgent()  ─┘
    │               ├── ConceptAgent.extract() [if no Deepgram NER entities]
    │               │
    │               ├── Priority chain:
    │               │   1. Discrepancy (high severity, not exhausted) → challenge question
    │               │   2. Weakness (high severity, not exhausted, not 2x consecutive) → probe
    │               │   3. Bank follow-up (adapted from RAG question bank) → deepen current topic
    │               │   4. Sprint question (advance to next topic)
    │               │
    │               └── Returns: { response, sprint, persona, weakness, pivoting, turn_id, ... }
    │
    ├── POST /tts → ElevenLabs → MP3 blob → Audio element plays
    │
    └── TTS plays → candidate hears question → speaks → cycle repeats
```

**Sprint structure (5 questions each):**
- Sprint 1 — Project Defense — `curious_lead` persona — who built what, ownership
- Sprint 2 — Foundations — `socratic_mentor` persona — conceptual depth, first principles
- Sprint 3 — System Design — `senior_peer` persona — trade-offs, scaling, failure modes

**After sprint 3 or 30 minutes:** `end_session()` → `EvaluationAgent.score_full_interview()` → Redis state → report page.

---

## § 3. FILE READING ORDER
> Read these IN ORDER. Each file builds on the last. Do not skip.

### Core logic (read first)
1. `backend/services/orchestrator.py` — **THE BRAIN**. Read every line. This is the central controller: parallel agent dispatch, attack strategy selection, sprint progression, candidate memory, honest admission soft-cap, consecutive weakness guard, follow-up sequencing.
2. `backend/agents/weakness_agent.py` — Most important agent. Detects the exact failure point. Sprint-aware. Memory-aware.
3. `backend/agents/followup_agent.py` — Generates every question the candidate hears. 4 methods: `generate()` (weakness probe), `generate_discrepancy_challenge()`, `generate_sprint_question()` (returns tuple with seed followups), `adapt_followup()` (grounds bank template in candidate's actual answer).
4. `backend/agents/discrepancy_agent.py` — Cross-verifies resume claims vs. what candidate says. Now memory-aware (won't re-flag confirmed projects).
5. `backend/agents/evaluation_agent.py` — Two modes: `score_answer()` (3-pass averaged, runs async in background) and `score_full_interview()` (Opus, called at session end, produces full report).

### Supporting agents
6. `backend/agents/reasoning_behavior_agent.py` — Evaluates HOW candidate thinks (meta-cognition). `admitted_gap` adaptability triggers honest admission soft-cap in orchestrator.
7. `backend/agents/resume_agent.py` — Parses resume at session start into structured JSON (skills, projects, claims, tools, experience).
8. `backend/agents/concept_agent.py` — Extracts technical concepts from transcript. Only runs if Deepgram NER didn't extract entities.

### Infrastructure
9. `backend/api/routes.py` — All endpoints. Key: `/process_turn`, `/tts`, `/start_interview`, `/end_interview/{id}`, `/report/{id}`, `/state/{id}`.
10. `backend/models/llm_router.py` — OpenRouter via OpenAI-compatible SDK. Tier routing: small=Haiku, medium=Sonnet, large=Opus.
11. `backend/state/session_manager.py` — Redis async. All session state lives here. 1hr TTL.
12. `backend/services/tts_service.py` — ElevenLabs, `eleven_turbo_v2_5`, `mp3_44100_128`. Filler pre-cache at startup. `stream()` method.
13. `backend/main.py` — FastAPI entry. Lifespan: warms filler cache, inits Postgres schema, loads RAG index.
14. `backend/rag/question_bank.py` — FAISS + sentence-transformers. `retrieve(text, sprint, top_k)` returns questions with followup arrays.
15. `backend/data/question_bank/ml_questions.json` — 34 questions. 10 sprint 1, 12 sprint 2, 12 sprint 3. Each has `followups: [...]` arrays used by `adapt_followup()`.

### Frontend
16. `frontend/lib/audio.ts` — **Most complex frontend file.** Deepgram browser SDK, FloorState machine (IDLE/USER_SPEAKING/AI_THINKING/AI_SPEAKING), utterance accumulation + UtteranceEnd flush, echo cancellation, barge-in VAD, `prefetchAudio()`, `playAudioUrl()`, `speakWithBrowser()` (sentence-chunked fallback).
17. `frontend/lib/vision.ts` — MediaPipe FaceLandmarker. CPU delegate. RAF loop for lip closure + gaze stability prediction. Stored as `latestVision` instance var — read synchronously in transcript handler (never awaited in hot path).
18. `frontend/app/interview/[session_id]/page.tsx` — Main interview UI. `handleFollowup()`, `processingRef`, `pendingFinalRef`, `currentTurnIdRef`, 300ms drain after TTS, pivot marker rendering.
19. `frontend/app/report/[session_id]/page.tsx` — Report display. Shows `claim_credibility_risk`, failure surface bars, weakness log, hire verdict.
20. `frontend/app/page.tsx` — Landing page. Resume textarea → POST `/start_interview` → redirect to `/interview/{session_id}`.
21. `frontend/components/Waveform.tsx` — AIOrb and audio-reactive waveform.

### Project context
22. `AGENTS.md` — Shared AI coordination file. Decisions log, conventions, in-progress tasks, completed work.
23. `COLLAB.md` — Async discussion between Claude Code, Codex, and Gemini.

---

## § 4. SESSION STATE SCHEMA

Every session stored in Redis under `session_id`. Full shape:

```python
{
    "session_id": str,
    # Sprint tracking
    "current_sprint": int,          # 1 | 2 | 3
    "current_persona": str,         # curious_lead | socratic_mentor | senior_peer
    "sprint_name": str,
    "question_count": int,          # total questions asked
    "sprint_question_count": int,   # questions in current sprint (resets on advance)
    # Timing
    "interview_start_time": float,  # time.time()
    "interview_complete": bool,
    # Candidate data
    "resume": str,                  # raw resume text
    "parsed_resume": {              # from ResumeAgent
        "skills": [...], "projects": [...], "claims": [...],
        "tools": [...], "experience": {...}
    },
    "github_links": [...],
    "skills": [...],
    # History & scores
    "history": [                    # one entry per turn
        {
            "question": str,
            "answer": str,
            "weakness": {type, severity, weakness, attack_strategy},
            "concepts": [...],
            "discrepancy": {conflict, description, severity},
            "reasoning_behavior": {structure_score, adaptability, ...},
            "sprint": int,
            "persona": str,
        }
    ],
    "weaknesses": [...],            # flat list of all weakness dicts
    "scores": {},                   # populated at end_session
    "failure_surface": {},          # populated at end_session
    "final_evaluation": None,       # EvaluationAgent output at end_session
    # Current state
    "last_question": str,           # the question currently pending candidate's answer
    # Adversarialism guardrails
    "consecutive_high_weakness_count": int,  # resets on sprint advance or type change
    "last_weakness_type": str | None,
    # Follow-up sequencing
    "current_question_followups": [...],  # seed follow-ups from RAG for current sprint Q
    "current_question_followup_asked": bool,
    # Cross-turn memory
    "candidate_model": {
        "project_map": {},          # {"candidate name": {"resume_entry": str, "confirmed_turn": int}}
        "established_facts": [...], # confirmed truths, passed as context to agents
        "probed_weaknesses": [...], # last 8 probed areas, passed as context to agents
    },
}
```

---

## § 5. ORCHESTRATOR DECISION LOGIC (the most important thing to understand)

On every `handle_transcript()` call:

```
1. Run 3 agents in parallel:
   WeaknessAgent.detect(question, answer, sprint, prior_weaknesses, memory_context)
   DiscrepancyAgent.check(resume, answer, memory_context)
   ReasoningBehaviorAgent.evaluate(answer, was_challenged)
   [ConceptAgent only if no Deepgram NER entities]

2. Honest admission soft-cap:
   IF reasoning.adaptability == "admitted_gap" AND weakness.severity == "high":
       weakness.severity = "medium"  ← intellectual honesty rewarded

3. Consecutive weakness guard:
   IF same weakness type fires high 2x in a row:
       force_sprint_question = True  ← prevents infinite probe loops

4. Sprint 3 strategy remap:
   IF sprint == 3 AND attack_strategy in (implementation_probe, step_by_step):
       attack_strategy = "scaling"  ← keep Sprint 3 at system design altitude

5. Priority chain (pick one):
   A. discrepancy.conflict AND severity==high AND not force → discrepancy challenge
   B. weakness.severity==high AND not force → targeted probe
   C. current_question_followups not empty AND not asked yet → adapt_followup()
   D. else → generate_sprint_question()  (advance topic)

6. Update candidate_model (no LLM call — derived from outputs):
   - non-conflict discrepancy → add to established_facts
   - weakness → add to probed_weaknesses (capped at 8)

7. Update history, weaknesses, question_count, last_question

8. Maybe advance sprint (every 5 questions)

9. Maybe terminate (sprint 3 done or 30min elapsed)
```

---

## § 6. FLOOR STATE MACHINE (frontend)

Lives in `frontend/lib/audio.ts` as `FloorState` enum and `InterviewSession` class.

```
IDLE
  └─► USER_SPEAKING  (session.start() transitions here)
        │
        ├── Deepgram is_final fragments → utteranceBuffer.push()
        ├── UtteranceEnd (3s silence) → _flushUtterance(forced=true)
        ├── Safety timer (30s) → _flushUtterance(forced=true) [Deepgram failure fallback only]
        │
        └─► AI_THINKING  (_flushUtterance clears buffer, calls onFinal)
              │
              │  [processTurn → backend → response ready]
              │  [prefetchAudio → ElevenLabs → blob URL]
              │
              └─► AI_SPEAKING  (300ms drain after audio ends)
                    │
                    └─► USER_SPEAKING  (cycle repeats)
                         OR
                    └─► IDLE  (interview complete)
```

**Key behaviors:**
- `transition(AI_THINKING | AI_SPEAKING)` → clears `utteranceBuffer` (reverb protection)
- During `AI_SPEAKING`: all Deepgram transcripts blocked EXCEPT barge-in VAD check (250ms + 8 chars)
- Barge-in: aborts AbortController → audio stops → floor → USER_SPEAKING
- `processingRef`: prevents concurrent `onFinal` handlers. If `onFinal` fires during processing, stores in `pendingFinalRef`, invalidates in-flight `turn_id`.
- `echoCancellation: true` on `getUserMedia` — prevents TTS audio from entering mic pipeline
- 300ms drain after `playAudioUrl` resolves before floor → USER_SPEAKING (reverb window)

---

## § 7. KEY BEHAVIORS AND GUARDRAILS

### Honest admission handling
When candidate explicitly admits a gap ("I don't actually know this", "I mislabeled that"):
1. `ReasoningBehaviorAgent` returns `adaptability: "admitted_gap"`
2. Orchestrator soft-caps weakness severity to `medium` (from `high`)
3. `WeaknessAgent` prompt instructs: "set severity to medium/low — do NOT punish intellectual honesty"
4. Persona prompts have "NEW RULE: reward honesty by moving on"
Result: system pivots to curiosity instead of attacking the admission.

### Consecutive weakness guard
If the same weakness type fires as `high` twice in a row:
- `consecutive_high_weakness_count >= 2` → `force_sprint_question = True`
- Frontend shows "shifting focus" divider in transcript
- Resets on sprint advance or when weakness type changes

### Follow-up sequencing rhythm
After a sprint question: one adapted bank follow-up is injected before the next sprint question.
`adapt_followup()` takes the raw template and grounds it in the candidate's specific answer.
Gives: Sprint Q → Deepening follow-up → Next sprint Q (not just rapid-fire sprint questions)

### Cross-turn memory
`candidate_model` in session state — updated every turn, zero extra LLM calls:
- `established_facts`: confirmed project mappings passed to DiscrepancyAgent → won't re-flag
- `probed_weaknesses`: recent probes passed to WeaknessAgent → won't re-attack same ground

### Sprint 3 strategy remap
`implementation_probe` and `step_by_step` are Sprint 2 strategies (code-level).
In Sprint 3 (System Design), these are remapped to `scaling` — keeps conversation at trade-off altitude.

---

## § 8. AGENT PROMPTS (what each agent is told to do)

### WeaknessAgent
- Finds ONE weakness: `missing_step | vague | incorrect | shallow | overconfidence`
- Assigns severity: `low | medium | high`
- Assigns attack strategy: `implementation_probe | edge_case | scaling | contradiction | step_by_step`
- Sprint-aware: Sprint 1 = ownership gaps, Sprint 2 = conceptual accuracy, Sprint 3 = trade-offs
- Receives `memory_context`: probed weaknesses from prior turns (won't repeat same probe)
- IMPORTANT clause: `admitted_gap` → severity must be `medium` or `low`

### DiscrepancyAgent
- Compares resume claims vs. candidate explanation
- Returns `{ conflict: bool, description: str, severity: low|high }`
- Receives `memory_context`: established_facts from prior turns (won't re-flag confirmed projects)
- IMPORTANT: if prior turns confirmed a claim, do NOT re-flag it

### FollowUpAgent (3 personas)
- `curious_lead`: broad first, deepen naturally, never confrontational, rewards honesty
- `socratic_mentor`: explain in plain language, guide thinking, never embarrass
- `senior_peer`: collaborative design session, realistic constraints, trade-off thinking
- 4 methods: `generate()`, `generate_discrepancy_challenge()`, `generate_sprint_question()`, `adapt_followup()`
- `generate_sprint_question()` returns `(question, seed_followups)` — seed followups stored for next turn

### ReasoningBehaviorAgent
- Evaluates meta-cognition only (not technical accuracy)
- structure_score (0-3), clarification_behavior, adaptability, confidence_calibration
- `adaptability` enum: `flexible | rigid | defensive | admitted_gap`

### EvaluationAgent
- `score_answer()`: 3-pass averaged per-answer scoring (async, non-blocking)
- `score_full_interview()`: Opus model, full transcript + weaknesses + reasoning signals
- Outputs: `overall_score`, `breakdown`, `failure_surface`, `hire_recommendation`, `confidence_score`, `claim_credibility_risk`
- Coverage-aware: if `unique_weakness_types / total_weaknesses < 0.3`, injects coverage note, caps confidence ≤ 0.6

---

## § 9. KNOWN ISSUES AND OPEN ITEMS

### Infrastructure issues (not code bugs)
- **PostgreSQL is not running.** `persist_session()` background task crashes silently with `ConnectionRefusedError`. Interviews work; recruiter dashboard is empty. Start Postgres from `infra/docker-compose.yml` to fix.
- **`/tts_filler` called 15+ times in a single interview** (seen in logs). This suggests a loop or repeated silence nudge. Root cause not yet confirmed — worth investigating in `session.onSilence` handler.

### Pending features (agreed but not implemented)
1. **Total confession pivot** (`full_confession` state flag): when candidate explicitly admits they don't know anything and asks to end — system should switch all subsequent questions to product/conceptual thinking, ignore resume claims entirely. This directly addresses Turn 10-15 failure mode in second interview (candidate admitted resume inflation but system kept probing technical claims).
2. **Candidate distress detection**: "please end the interview, I'm done" → graceful off-ramp or mode switch. No handling exists.
3. **Postgres persistence + `/sessions` endpoint** → recruiter dashboard unblocked.
4. **`tts_filler` loop investigation** → unclear if silence nudge is firing incorrectly.

### Design questions (not yet decided)
- `tts_filler` is pre-cached but currently only called during `onSilence`. The original filler-first strategy (fire filler immediately after candidate stops, before LLM responds) was discussed but the current flow goes straight to LLM. Worth revisiting for perceived latency.
- Cross-AI collaboration (`COLLAB.md`) — Codex and Gemini have been involved; check `COLLAB.md` for their latest notes before making architectural changes.

---

## § 10. ENVIRONMENT AND INFRA

### Services needed (all local)
- Redis: `docker-compose up redis` from `infra/`
- PostgreSQL: `docker-compose up postgres` from `infra/` (currently NOT running — dashboard dead)
- Backend: `uvicorn backend.main:app --reload --port 8000 >> uvicorn.log 2>&1`
- Frontend: `cd frontend && npm run dev -- --port 3001 >> ../frontend.log 2>&1`

### API keys (all in `.env` at project root)
```
OPENROUTER_API_KEY=...       # LLM routing (Claude Haiku/Sonnet/Opus via OpenRouter)
DEEPGRAM_API_KEY=...         # ASR (exposed to browser via /deepgram_token — intentional)
ELEVENLABS_API_KEY=...       # TTS (also TTS_API_KEY — both set, service reads either)
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Model routing (via OpenRouter)
| Tier | Model | Used for |
|------|-------|---------|
| small | claude-haiku-4-5 | concept extraction, resume parsing |
| medium | claude-sonnet-4-5 | weakness detection, follow-up generation, discrepancy |
| large | claude-opus-4-5 | full interview evaluation (end of session) |

### LLM output format
All agents return JSON. `LLMRouter.call()` auto-parses. Agents handle both `dict` and `str` returns (graceful fallbacks in all agents).

---

## § 11. DECISIONS THAT ARE LOCKED (do not re-debate)

| Decision | Reason |
|----------|---------|
| Client-side Deepgram SDK (not backend WebSocket relay) | Lower latency. Key exposed via `/deepgram_token` — acceptable for internal tool. |
| ElevenLabs for TTS | Confirmed by Yash. `eleven_turbo_v2_5`, `mp3_44100_128`. |
| OpenRouter for all LLM calls | One key, all models. `AsyncOpenAI` with OpenRouter base URL. |
| Redis for session state | Stateless services, 1hr TTL, async. |
| FAISS for RAG in dev → Pinecone in prod | Easy swap via interface. FAISS live, 34 questions loaded. |
| Fillers disabled (TTS only, no filler prefix) | Decided by Yash. Routes.py: "Always use plain stream() — fillers disabled." |
| `asr_service.py` is dead code | Do not use or modify. Browser SDK is the ASR path. |
| Absolute imports only | `from backend.agents.x import X`, never relative. |

---

## § 12. CONVENTIONS

1. All agent calls are async. `asyncio.gather()` for parallel. Never block.
2. State lives in Redis only. Never pass full state as function arguments between services.
3. JSON outputs from all agents. If LLM returns plain text, `LLMRouter` tries to parse it. Handle both `dict` and `str`.
4. No sync Redis calls. `redis.asyncio` everywhere.
5. `weakness.severity` drives branching: `high` → dynamic LLM follow-up. `low/medium` → bank follow-up or sprint question.
6. Agents never see raw transcripts — they see agent-processed data. (Exception: WeaknessAgent and DiscrepancyAgent take raw answer text — this is intentional and correct.)
7. Per-answer scoring (`_score_answer_async`) runs as a background `asyncio.create_task()` — never blocks the response path.
8. `turn_id` is generated client-side, echoed by backend, checked on return — stale responses are silently dropped.

---

## § 13. REPO STRUCTURE (complete)

```
antigravity/
├── AGENTS.md                          Shared AI coordination (decisions, in-progress, conventions)
├── COLLAB.md                          Async discussion board (Claude/Codex/Gemini)
├── CONTEXT.md                         ← this file
├── README.md                          API reference + setup guide
├── requirements.txt
├── .env                               API keys (never commit)
├── .env.example
├── Dockerfile
│
├── backend/
│   ├── main.py                        FastAPI entry, lifespan hooks
│   ├── api/
│   │   └── routes.py                  All HTTP endpoints
│   ├── services/
│   │   ├── orchestrator.py            THE BRAIN — read this first
│   │   ├── tts_service.py             ElevenLabs streaming TTS
│   │   └── asr_service.py             DEAD CODE — do not use
│   ├── agents/
│   │   ├── weakness_agent.py          Most important agent
│   │   ├── followup_agent.py          Question generation (4 methods)
│   │   ├── discrepancy_agent.py       Resume vs. answer cross-check
│   │   ├── evaluation_agent.py        Final scoring (Opus)
│   │   ├── reasoning_behavior_agent.py  Meta-cognition evaluator
│   │   ├── concept_agent.py           Technical concept extraction
│   │   └── resume_agent.py            Resume parser
│   ├── models/
│   │   └── llm_router.py              OpenRouter tiered routing
│   ├── state/
│   │   └── session_manager.py         Redis async session state
│   ├── rag/
│   │   ├── question_bank.py           FAISS + sentence-transformers retriever
│   │   └── faiss_store.py             FAISS index wrapper
│   └── data/
│       └── question_bank/
│           └── ml_questions.json      34 questions with followups arrays
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx                   Landing page (resume input)
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   ├── interview/[session_id]/
│   │   │   └── page.tsx               Main interview UI (most complex page)
│   │   ├── report/[session_id]/
│   │   │   └── page.tsx               Report display
│   │   └── dashboard/
│   │       └── page.tsx               Recruiter dashboard (blocked — needs Postgres)
│   ├── lib/
│   │   ├── audio.ts                   Deepgram SDK, FloorState, TTS utilities
│   │   └── vision.ts                  MediaPipe CV (lip closure, gaze stability)
│   ├── components/
│   │   └── Waveform.tsx               AIOrb + waveform
│   └── package.json
│
└── infra/
    └── docker-compose.yml             Redis + Postgres
```

---


---

*Last updated: 2026-04-07 | Git: main branch | Commit: 52d865b*
