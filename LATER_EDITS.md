# Later Edits — Deferred Work

Items identified during testing / design review that are not urgent enough to fix now but should not be forgotten.

---

## Turn Detection & Latency

### CV-based turn prediction (currently stub)
**What**: `audio.ts` computes a vision fusion score (lip closure × 0.4 + gaze stability × 0.3 + audio silence × 0.3) but only `console.log`s it — never commits an utterance.
**Goal**: When score ≥ 0.85, treat as soft turn-end signal. Gate it: only fire early commit if silence has been ≥ 400ms AND accumulated text ≥ 15 chars. Never bypass `UtteranceEnd` for canonical commits — CV should be a *warm-up* trigger (pre-fetch next question) not a *meaning commit* trigger.
**File**: `frontend/lib/audio.ts` — vision fusion block (~line 254)

### Reduce UtteranceEnd silence threshold
**What**: Currently `utterance_end_ms: 3000` (3s of silence before Deepgram fires). Feels like a long pause in conversation.
**Goal**: Try 1800ms–2200ms. Risk: mid-thought splits if candidate pauses mid-sentence. Should be tested against real interview audio.
**File**: `frontend/lib/audio.ts:139`

### HandoverManager — mid-thought pause detection
**What**: Candidate pauses >3s mid-thought (thinking pause, not turn end). Currently the safety timer or UtteranceEnd fires and splits the answer.
**Goal**: Detect "thinking pause" vs "turn yield" — maybe using filler words ("um", "uh", "like") in the partial transcript as a signal that the candidate is still formulating. If last partial ends with a filler, extend the flush delay.
**File**: new class or helper in `audio.ts`

---

## Question Quality

### Partial STT → more directed follow-ups (v2 RAG path)
**What**: Partial STT entities are accumulated but not used to pre-fetch or bias follow-up questions. No RAG pipeline yet.
**Goal**: While candidate is speaking, embed partial transcript → query question bank for top-K candidates → pass to Haiku for selection. This is the full `problem2.md` proposal.
**Depends on**: question bank embeddings, FAISS store (`backend/rag/faiss_store.py` — also has the `_get_model()` reload bug, see below)
**Files**: `backend/rag/faiss_store.py`, `backend/agents/followup_agent.py`, `backend/services/orchestrator.py:on_partial_transcript`

### faiss_store._get_model() caching bug
**What**: `_get_model()` reloads `SentenceTransformer` on every `search()` call — no module-level caching.
**Fix**: Cache as module-level singleton: `_model = None; def _get_model(): global _model; if _model is None: _model = SentenceTransformer(...); return _model`
**File**: `backend/rag/faiss_store.py`

---

## Memory & Candidate Model

### project_map never populated
**What**: `candidate_model.project_map` is initialized in `start_session` but nothing ever writes to it.
**Goal**: When candidate describes a project, extract project name + key claims into `project_map`. Use in sprint transitions to reference the specific project by name.
**File**: `backend/services/orchestrator.py:_run_background_pipeline` — add project extraction pass

### Total confession → product/conceptual pivot
**What**: When candidate explicitly admits fabrication ("I just coded with tools", "I don't know any of this"), the system should pivot to a product/conceptual mode instead of hammering the same technical questions.
**Current behavior**: The honest admission soft-cap downgrades severity to `medium`, but the system still keeps drilling implementation details (see transcript Turns 10–15).
**Goal**: After `admitted_gap` on 2+ consecutive turns, set a `full_confession` flag and switch `attack_strategy` to `conceptual` / `product` framing across all agents.
**File**: `backend/services/orchestrator.py:_run_background_pipeline`, `backend/agents/weakness_agent.py`

### Candidate distress detection
**What**: "Please end the interview, I'm done" → currently the system continues interviewing (it should respect this).
**Goal**: Detect withdrawal phrases in `handle_transcript` fast path, set `interview_complete = True`, return a graceful off-ramp response.
**File**: `backend/services/orchestrator.py:handle_transcript`

---

## Scoring & Report

### weakness_summary not rendered in report
**What**: `weakness_summary` is computed in the report page but never rendered in JSX.
**File**: `frontend/app/report/[session_id]/page.tsx`

---

## TTS / Audio Loop

### TTS filler loop — add cooldown
**What**: `onSilence` fires on every `UtteranceEnd` with no text → plays filler → AI_SPEAKING → USER_SPEAKING → next UtteranceEnd fires. No cooldown exists.
**Fix**: In `onSilence` handler (`frontend/app/interview/[session_id]/page.tsx`), skip if < 15s since last nudge. Track `lastNudgeAt` ref.
**File**: `frontend/app/interview/[session_id]/page.tsx`
