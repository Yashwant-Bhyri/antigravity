# Antigravity

**AI-observed technical assessment platform.** Two parallel product tracks built by Yash (sole engineer and product owner): a real-time voice interview engine and an engineering simulation workbench.

---

## What This Is

Antigravity evaluates engineering candidates the way a senior hiring committee would — not through a quiz, but through observed behavior under realistic pressure. The system watches how a candidate reasons through ambiguity, corrects themselves, defends decisions, and actually executes.

**Two product surfaces:**

- **Voice Interview Engine** — a live AI interviewer that probes a candidate's resume in real time. Deepgram ASR, multi-agent backend orchestrator, Cartesia/ElevenLabs TTS. The AI has read your resume before you connect and is genuinely trying to understand what you actually built.
- **Engineering Simulation** — a staged workbench where candidates read an incident brief, plan a fix, edit real code, run a sandboxed Node.js test suite, and defend their decisions under AI assessment. The interviewer is a persistent presence, not just a judge at the end.

---

## Architecture Overview

```
Next.js (App Router)              FastAPI (Python)
────────────────────              ─────────────────────────────────────────
app/
  page.tsx (voice landing)        backend/
  interview/[id]/page.tsx           main.py
  simulation/page.tsx               api/routes.py
  simulation/inventory/page.tsx     services/
  simulation/report/[id]/page.tsx     orchestrator.py         ← voice engine brain
  simulation/admin/page.tsx           interview_map.py        ← resume trajectory map
  report/[id]/page.tsx                simulation_service.py
  dashboard/page.tsx                  inventory_simulation_service.py
                                      tts_service.py
lib/audio.ts                          session_manager.py      ← Redis + in-memory
lib/api.ts                        agents/
components/design-system.tsx          weakness_agent.py
components/Waveform.tsx (AIOrb)       followup_agent.py
                                      evaluation_agent.py
                                      discrepancy_agent.py
                                      reasoning_behavior_agent.py
                                      resume_agent.py
                                  models/llm_router.py        ← OpenRouter multi-tier
```

**State:** Redis-backed active interview state. Simulation sessions write lightweight summary rows (`sim_summary:*`, `invsim_summary:*`) separately for fast admin listing.

**LLM:** OpenRouter. Current policy is task-based: Gemini Flash/Flash Lite for cheaper structured generation and repair, Sonnet for high-quality critique/follow-up/report authority, Gemini Pro as a large-tier report candidate, and DeepSeek as advisory audit only. Opus is not a default live path.

**TTS:** Cartesia (primary, permanent), ElevenLabs (fallback).

**ASR:** Deepgram browser SDK. `endpointing=1500`, `utterance_end_ms=2800`. Interim snapshots streamed to `/partial_transcript` for speculative prep without committing unstable text as canonical history.

---

## Track 1: Voice Interview Engine

### Two-Track Architecture

The core architectural insight: next question is ready before the current answer finishes.

```
Candidate answers Turn N
    │
    ├─ FAST TRACK (~300-500ms)
    │   handle_transcript()
    │   → _apply_staged_analysis()   ← Codex Invariant: canonical state mutates HERE only
    │   → consume prepped_next_packet from background
    │   → priority waterfall if empty
    │   → serve question
    │
    └─ SLOW TRACK (runs during candidate answer)
        _run_background_pipeline()
        → WeaknessAgent (parallel)
        → DiscrepancyAgent (parallel)
        → ReasoningBehaviorAgent (parallel)
        → FollowUpAgent.generate()
        → write to prepped_next_packet
        → never touches canonical state
```

**The Codex Invariant:** canonical state (history, weaknesses, scores) only mutates in `_apply_staged_analysis()` at the start of the next turn. The background pipeline only writes to staging fields. Clean turn boundaries, no mid-turn state corruption.

### Resume-Grounded Interview Map

Before the candidate connects, the system builds a launch-ready per-candidate question map:

1. **Focus/Sub-Focus Plan** — selects role-relevant experience areas and weighted sub-focus surfaces from the resume.
2. **Launch Track Generation** — generates only the first two startup-critical tracks before turn 1.
3. **Question Ladder** — each track contains frame, clarify, explore, pressure, synthesize, and recover postures.
4. **Launch Critic/Repair** — critiques only the launch tracks; exact field issues are surgically repaired.
5. **Async Hydration** — later tracks are generated/quarantined after launch and must not block turn 1.

The map is what separates resume-grounded probing from generic interviewing. A well-built map knows the candidate said "scaled Golang microservices to 10M users" and asks about the specific failure modes of that architecture, not "tell me about scaling."

**Startup contract:** `POST /prepare_interview_map` must produce `launch_ready=true`: two role-relevant, schema-valid, LLM-authored launch tracks. Full-map hydration can continue asynchronously.

**No deterministic assessment fallback:** assessment-critical map/question/report paths fail closed, quarantine, or repair surgically instead of inventing generic fallback questions.

### Evolution

**April 2026 — Foundation:**
First working system. Phase 1 philosophy: adversarial-first, claim-verification as primary axis. Twenty real test runs surfaced the pattern: questions weren't relevant to what candidates had done, interviews got stuck drilling one topic, felt robotic and uninviting.

**Core bugs discovered:**
- Turn 1 always hit `sprint_fallback` — no prepped question on session start
- Sprint transitions were cold — no context carried forward
- 5–10s dead air between turns felt mechanical
- Terse answers (`"Mostly cost."`) trapped the whole session in a drilling loop
- Resume parser silently failing on all real resumes (C-1)
- `_infer_focus()` returning empty every turn, breaking all downstream routing (C-2)
- Bridge never fired — `consecutive_high_weakness_count` stuck at 0 (C-3)
- `sprint_seed` dominated routing 7/15 turns; trajectory map underutilized (C-4)

**Solutions shipped:**
- Two-track fast/slow architecture
- Packetized follow-up scheduling (`active_question_packet` + `prepped_next_packet`)
- Same-turn revision versioning — older background analyses cannot overwrite newer revisions
- Short-answer rescue — terse answers (1–18 words) eligible for grounded domain-specific follow-up
- STT calming — `utterance_end_ms=2800`, interim snapshots for speculative prep
- Dynamic sprint openers — Haiku call at sprint transitions referencing specific prior-sprint content
- Interview map hardened — launch-ready bounded prep, typed sub-focus surfaces, voice-first question ladders, surgical repair, async hydration, and hard coverage gates

**April 2026 — Platform hardening:**
- Full per-session JSONL telemetry at `backend/runtime/interview_traces/` — STT flush reasons, floor transitions, process-turn latency, TTS provider/source/latency, route decisions
- ProvenHire integration — `/launch?token=...` frontend route, signed callbacks with retry/backoff, async finalization (final turn returns immediately; report scores in background)
- Frontend visual system overhaul — `components/design-system.tsx`, `globals.css` design token system, `AIOrb` waveform component

**May 2026 — Philosophy shift:**

After a deep mentor-style audit of every agent and service, several design principles settled:

| Old philosophy | New philosophy |
|---|---|
| Investigation — prove claims right or wrong | Measurement — gather enough evidence to form a verdict, then move on |
| Adversarial-first | Substance first; adversariality is a tool, not an identity |
| Maximum probing = good interviewing | Maximum authentic signal under conversational balance |

**Key settled insight:** bad candidates score low naturally. Good candidates score high naturally. Proving fraud is a byproduct, not a goal. An investigation ≠ an interview.

**Three-layer questioning model (agreed, not yet built):**

| Layer | What it is | Currently designed for? |
|---|---|---|
| Technical | What competency is tested | Yes |
| Communication | How naturally/invitingly phrased | No |
| Psychological | What mental state it induces | No |

**Transition intelligence:** conversational quality lives in transitions, not isolated questions. Evaluation unit should be `(Q_n → A_n → Q_{n+1})` as a tuple. Not yet modeled.

**Product decisions hardened:**
- Cartesia = permanent TTS primary
- Coverage score = advisory signal, does not override final LLM hire recommendation
- RLHF: pairwise preference on `(Q, A, Q+1)` tuples — but NOT until C-1 through C-4 are fixed (current data has routing failures that would produce noisy training signal)

### What's Working Well (Don't Break It)

- WeaknessAgent detection — accurate and precise across both completed sessions
- DiscrepancyAgent — reliably catches confirmed contradictions
- Trajectory map generation — when resume parses correctly, maps are strong
- Map critic self-evaluation — correctly flags weak probes, gives repair instructions
- Final evaluation verdicts — correctly calibrated in both completed sessions
- Speculative generation — fires and produces good questions
- Two-track staging architecture — the design is correct even though routing is broken

### Pre-Production Bug Audit

Full audit in `problem.md`. Critical blockers (cannot ship):

| ID | Issue |
|---|---|
| C-1 | Resume parser (`_heuristic_parse()`) producing garbage on all real resumes — skills=[], projects=[], contact info classified as project names. Silent failure. |
| C-2 | `_infer_focus()` returns `""` every turn — breaks map navigation, coverage tracking, bridge mechanism. `active_question_packet.focus_key` carries the correct value and should just be propagated. |
| C-3 | `consecutive_high_weakness_count` stuck at 0 — bridge never fires — interviews get stuck on one topic. |
| C-4 | `sprint_seed` dominates — improvised Haiku questions instead of the carefully built map. Root cause is C-2. |

**Fix order:** C-1 → C-2 → C-3 → C-4 (unblocks the architecture). Then H-1 through H-5 (experience tier, ownership language calibration, conversational pressure gauge). See `problem.md` for full list.

---

## Track 2: Engineering Simulation

### Philosophy

Candidates are placed inside a realistic incident, edit real code, run a real test suite, and defend their decisions. The system measures observed behavior, not declared competence.

**Core promise:** passing tests is evidence, but not enough. Senior signal requires coherent reasoning about what the tests prove, what production scenarios remain unproven, and what you would monitor after deploy. A candidate who gets it right first time and explains why outscores one who fails, fixes, and never understands why it works.

### Domain 1: Payment Retry Safety (`/simulation`)

**The scenario:** payment handler has an idempotency hole — retried requests can double-charge. Candidate reads the incident, edits `payment.mjs`, runs 10 checks (6 public + 4 hidden including hidden concurrency/conflict cases), defends tradeoffs.

**Assessment state machine:**
1. **Understanding** — read the incident brief; articulate the invariant being violated
2. **Planning** — state the patch: mechanism, contention handling, partial failure behavior
3. **Implementation** — edit `payment.mjs`; explain why your approach prevents double-charge
4. **Validation** — run tests; explain what green tests prove and what remains unproven
5. **Reflection** — tradeoffs, observability, production gaps

Each stage requires a concrete worklog artifact to advance. Pressing Next with no work produces no score. Starter code remains a baseline, never candidate signal.

**Test runner:** sandboxed Node.js (`--permission` flags, temp directory, 10s timeout). 6 public + 4 hidden checks. Production twist injection at implementation stage (gateway timeout webhook).

**Scoring:** runtime evidence + reasoning quality. Shallow candidates capped below Strong Hire. Keyword-salad exploit patched: deterministic quality layer scores each stage artifact for concrete payment anchors, cause/effect language, action verbs, repetition, keyword-list shape.

**Exploits found and fixed:**

| Exploit | Fix |
|---|---|
| Click through all stages → non-zero score | Backend-owned state machine with gate checks; starter code is baseline, never candidate signal |
| Keyword list + correct code → Strong Hire | Deterministic reasoning-quality layer; shallow candidates capped with explicit report notice |
| Concise plan → misclassified as keyword salad | Detector distinguishes concise-but-causal from multi-stage keyword lists |
| First-pass correctness capped at 82 | Coherent green-code candidates are no longer hit by a hidden verbosity tax |
| Voice/Gemini controls in cockpit | De-voiced cockpit; voice is opt-in via env var |

### Domain 2: Flash Sale Inventory Race (`/simulation/inventory`)

**The scenario:** oversell incident during a 60-second flash sale — 847 units reserved against 500 inventory. Write-skew race: requests read `available > 0` before any write completes.

Candidate traces the race, chooses a locking strategy (optimistic/pessimistic/CAS), patches `inventory.mjs`, survives 20–100 concurrent requests in the hidden concurrency suite, defends the production tradeoffs.

`RaceyInventoryStore` uses `setImmediate` delays to expose the race window. Starter code fails hidden concurrency tests by design.

Same assessment philosophy as payment: shallow keyword-heavy candidates capped; coherent first-pass candidates Strong Hire eligible.

### Platform Features

- **Admin dashboard** (`/simulation/admin`) — lists all completed sessions; persists across backend restart via lightweight Redis summary rows (`sim_summary:*`, `invsim_summary:*`)
- **Shareable reports** (`/simulation/report/[session_id]`) — score, hiring signal badge, breakdown bars, What Was Proved, What Remains Unproven, Candidate Quotes, Session Timeline
- **Evidence ledger** — final reports include `evidence_ledger`: runtime proof dimensions, candidate-artifact acknowledgements, production gaps, authorship alignment. Auditable; ready for adaptive challenge routing.

### Interview Theater UI

Both simulation pages use a 2-zone Interview Theater layout:

```
┌──────────────────────────────┬───────────────────────────────────────────┐
│  Interview Channel  (360px)  │  Technical Workspace  (flex-1)            │
│                              │                                           │
│  AI Orb + interviewer msg    │  Understanding  → incident brief reading  │
│  Stage progress pills        │  Planning       → constraints + editor    │
│  Required artifact gate      │  Impl/Validate  → editor + test results   │
│  Worklog textarea (flex-1)   │  Complete       → inline report           │
│  Telemetry strip             │                                           │
│  Back / Next Stage nav       │                                           │
└──────────────────────────────┴───────────────────────────────────────────┘
```

Design principle: the workspace changes character per stage. The interviewer is a persistent presence on the left. Evidence surfaces inline. The interface feels like a precision testing instrument, not a SaaS dashboard.

Monaco editor theme (`ag-dark`) and options extracted as shared constants — no duplication across pages. Backward navigation skips the LLM call (restores saved state, prevents 8s+ delays on Back). Applied to both services.

### E2E Coverage

6/6 Playwright scenarios in `tests/simulation.e2e.spec.ts`:

| Test | What it proves |
|---|---|
| Empty click-through blocked | No score without work; gate enforcement |
| Starter code rejected as candidate signal | Baseline protection |
| Strong candidate → Strong Hire | Full completion path |
| Keyword-salad + correct code → capped | Reasoning quality gate |
| Inventory simulation completes with persisted report | Full second domain |
| Admin lists completed payment + inventory sessions | Persistence across restart |

---

## Current State (May 2026)

### Complete and tested

| Feature | Status |
|---|---|
| Voice interview engine | Working — routing bugs C-1 through C-4 known |
| Interview map (resume-grounded) | Working — strict validation gate |
| Two-track fast/slow orchestration | Working |
| Same-turn revision versioning | Working |
| Short-answer rescue | Working |
| Full telemetry (per-session JSONL) | Working |
| ProvenHire handoff integration | Working |
| Frontend visual system (`design-system.tsx`) | Complete |
| Payment simulation (Domain 1) | Complete — gated, scored, tested |
| Inventory simulation (Domain 2) | Complete — same assessment philosophy |
| Admin dashboard + Redis persistence | Working — survives restart |
| Shareable report pages | Working |
| Evidence ledger in reports | Working |
| Interview Theater UI (both sims) | Complete |
| E2E suite | 6/6 passing |

### Pending work

**Voice engine (priority order):**
- C-1: Resume parser failing on real resumes (silent)
- C-2: `_infer_focus()` returns empty every turn
- C-3: Bridge never fires; `consecutive_high_weakness_count` stuck at 0
- C-4: `sprint_seed` dominates routing
- Multi-worker safety: process-local sidecars are not multi-worker safe
- Three-layer questioning model (Layers 2–3 not yet built)
- RLHF experiment: blocked on C-1 through C-4 fix first

**Simulation:**
- v2 payment simulation: retry queues, DLQ patterns, deeper failure taxonomy (research doc at `/Users/yash/Downloads/deep-research-report (1).md`)
- Additional simulation domains
- Real-time voice interviewer for simulation (code exists, gated by env vars)
- Public code execution boundary: V1 Node sandbox acceptable for internal prototype; public deployment needs container or microVM

**Infra:**
- ASGI shim (`api/index.py`) leaks traceback on boot failure
- Reports expire with Redis TTL unless persisted to Postgres

---

## Running Locally

```bash
# Install
npm install
pip install -r requirements.txt

# Frontend
npm run dev                          # http://localhost:3000

# Backend
python3 -m uvicorn backend.main:app --reload --port 8000

# E2E tests
PLAYWRIGHT_NEXT_START=1 PLAYWRIGHT_BACKEND_PORT=8001 PLAYWRIGHT_FRONTEND_PORT=3002 \
  npm run test:simulation:e2e
```

**Env vars:**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
OPENROUTER_API_KEY=...
REDIS_URL=redis://localhost:6379
CARTESIA_API_KEY=...
ELEVENLABS_API_KEY=...        # fallback TTS
DEEPGRAM_API_KEY=...          # voice interview ASR
ANTIGRAVITY_WEBHOOK_SECRET=...
```

---

## Routes

| Route | Description |
|---|---|
| `/` | Landing — start voice interview |
| `/interview/[session_id]` | Live voice interview workspace |
| `/report/[session_id]` | Voice interview final report |
| `/dashboard` | Recruiter session dashboard |
| `/simulation` | Payment Retry Safety simulation |
| `/simulation/inventory` | Flash Sale Inventory Race simulation |
| `/simulation/report/[id]` | Shareable simulation assessment report |
| `/simulation/admin` | Admin — all completed simulation sessions |

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/prepare_interview_map` | Parse resume, build trajectory map, run critic |
| POST | `/start_interview` | Open session, deliver opening question |
| POST | `/process_turn` | Submit committed utterance → agents → follow-up returned |
| POST | `/partial_transcript` | Entity accumulation during speech (no LLM) |
| POST | `/end_interview/{session_id}` | Trigger final evaluation + persist to Postgres |
| GET | `/report/{session_id}` | Full evaluation report |
| GET | `/deepgram_token` | Vend Deepgram key to browser SDK |
| POST | `/simulation/start` | Start payment simulation session |
| POST | `/simulation/interviewer_turn` | Move to next stage, get AI message |
| POST | `/simulation/run_tests` | Execute sandboxed Node.js test suite |
| POST | `/simulation/finalize` | Score and generate final report |
| GET | `/simulation/sessions` | Admin: list all completed sessions |
| POST | `/simulation/inventory/start` | Start inventory simulation session |

---

## Key Files

| File | Role |
|---|---|
| `backend/services/orchestrator.py` | Voice interview runtime brain — turn handling, staging, sprint logic |
| `backend/services/interview_map.py` | Resume-grounded trajectory map — focus areas, branch hydration, validation |
| `backend/services/simulation_service.py` | Payment sim logic, scoring, keyword-salad detection, test runner |
| `backend/services/inventory_simulation_service.py` | Inventory sim logic, concurrency tests, same scoring philosophy |
| `backend/models/llm_router.py` | OpenRouter multi-tier wrapper, JSON recovery, timeout handling |
| `backend/state/session_manager.py` | Redis + in-memory session state |
| `app/simulation/page.tsx` | Payment simulation UI — Interview Theater layout |
| `app/simulation/inventory/page.tsx` | Inventory simulation UI — Interview Theater layout |
| `app/simulation/admin/page.tsx` | Admin dashboard |
| `app/simulation/report/[session_id]/page.tsx` | Shareable simulation report |
| `app/interview/[session_id]/page.tsx` | Live voice interview UI |
| `components/design-system.tsx` | `AGButton`, `AGSurface`, `AGChip`, `AGScoreGauge`, etc. |
| `components/Waveform.tsx` | `AIOrb` component |
| `lib/audio.ts` | Deepgram + TTS + floor-state machine |
| `tests/simulation.e2e.spec.ts` | 6-scenario Playwright suite |
| `problem.md` | Pre-production bug audit — start here for engineering |

---

## Design Documents

| File | What it covers |
|---|---|
| `2CISASUE copy.md` | Three-layer questioning model, epistemic aggression diagnosis, "LLM as renderer" principle, transition intelligence, RLHF experiment design |
| `ISASUE.md` | Current problems and proposed solutions |
| `SIMULATION_PRD.md` | Engineering simulation product requirements |
| `PAYMENT_RETRY_SAFETY_PRD.md` | Payment domain simulation spec |
| `REALTIME_ACTION_DECK_ARCHITECTURE.md` | Real-time voice architecture for simulation |
| `REALTIME_INTERACTION_ACTION_DECK_CONTRACT.md` | Realtime interaction contract: action decks, non-counting rephrases/continuations, receipts, balanced answer signals |
| `ai_observed_engineering_simulation_platform_thesis_document.md` | Long-term vision — candidates inside simulated broken codebases, IDE telemetry. **Different product from current Antigravity. Do not conflate.** |

---

## AI Coordination

Built primarily with Claude Code.

- `AGENTS.md` — shared context for all AI contributors
- `COLLAB.md` — async discussion board
- `PROJECT_STATE.md` — chronological activity log, every major change
- `HANDOFF_CONTEXT.md` — full session context for AI continuity

---

## Product Philosophy

The system's purpose is to **measure substance, not prove guilt.**

Bad candidates score low naturally. Good candidates score high naturally. You don't need to prove anyone wrong 20 times — three probes from different angles (mechanism / implementation / boundary) establishes whether a claim is inflated. After that, drilling the same hole adds pressure, not evidence.

For the simulation: **passing tests is evidence, not a verdict.** Senior signal requires coherent reasoning about what the tests prove, what production scenarios remain unproven, and what you would monitor after deploy.

The interviewer is not a judge. It is a senior engineer sitting beside the candidate, watching how they think.
