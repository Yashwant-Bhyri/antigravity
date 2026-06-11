# Antigravity Deployment Readiness And Git Inventory

Date: 2026-06-11
Repo: `https://github.com/Yashwant-Bhyri/antigravity.git`
Local branch: `main`
Current base commit: `f9ebc3c fix second anchor and deferred hydration gates`
Pull status: `git pull --ff-only` returned `Already up to date.`

## Purpose

This document is the release-control snapshot for getting the current Antigravity worktree ready to push and deploy. It records what is changed, what is new, what should ship, what should stay local, and the safest path from local code to GitHub and then to production-style manual testing.

## Current Read

The worktree is not a tiny UI tweak. It contains:

- the locked live interview room integration;
- replay QA launcher and replay backend service;
- Deepgram/TTS/browser runtime fixes;
- report and interview-route UI changes;
- backend replay endpoints and runtime turn-revision handling;
- interview-map/question-quality/report/orchestrator fixes from the V1 readiness work;
- many exploratory/demo visualizer routes and research docs;
- local runtime LLM usage/quality logs that should not be committed.

The repo is up to date with `origin/main`, so there is no remote merge conflict right now. The risk is not remote drift; the risk is accidentally committing too broad a local artifact set.

## Tracked Files Changed

These files are already tracked by Git and have local modifications.

| File | Insertions | Deletions | Release read |
|---|---:|---:|---|
| `AGENTS.md` | 18 | 0 | Shared project state/handoff updates. Commit only if the content is intentional and not stale. |
| `PROJECT_STATE.md` | 23 | 0 | Project chronicle update. Commit if it accurately reflects current state. |
| `app/globals.css` | 311 | 0 | UI/design tokens/global styling. Likely required for new room/simulation UI. |
| `app/interview/[session_id]/page.tsx` | 99 | 17 | Existing working interview route changes. Needs smoke check because it is fallback-critical. |
| `app/report/[session_id]/page.tsx` | 216 | 5 | Report UI changes. Include if report page still builds and renders. |
| `backend/api/routes.py` | 136 | 0 | Replay endpoints and turn-revision request contract. Required for replay room QA and barge-in repair. |
| `backend/data/question_quality_guide.json` | 11 | 0 | Question-quality policy additions. Include with backend quality tests. |
| `backend/main.py` | 2 | 0 | CORS/local frontend allowance. Include if harmless for deployment config. |
| `backend/models/final_report.py` | 34 | 0 | Report model updates. Include with report contract tests. |
| `backend/services/interview_map.py` | 3 | 1 | Map generation policy fix. Include if already verified in V1 lock. |
| `backend/services/orchestrator.py` | 104 | 17 | Core runtime routing/app-transfer/coverage changes. High value, high risk; must run backend contract tests. |
| `backend/services/question_quality.py` | 14 | 2 | Deterministic question-quality checks. Include with question-quality tests. |
| `backend/state/session_manager.py` | 31 | 5 | Session persistence/reconnect behavior. Include with backend smoke. |
| `backend/test_final_report_contract.py` | 56 | 0 | Test coverage for report contract. Commit with code. |
| `backend/test_question_quality_contract.py` | 73 | 0 | Test coverage for question-quality policy. Commit with code. |
| `components/Waveform.tsx` | 45 | 21 | Visual/audio-reactive component changes. Include if current UI depends on it. |
| `lib/audio.ts` | 43 | 6 | Deepgram/TTS/barge-in/repeat/cache runtime fixes. Required for current working room. |
| `lib/vision.ts` | 49 | 21 | Vision log suppression/error handling. Include if it prevents dev console breakage. |
| `package.json` | 16 | 2 | Adds Playwright/replay scripts and new deps. Required for tests and UI runtime. |
| `package-lock.json` | 896 | 6 | Dependency lock update. Must commit with `package.json`. |
| `problem.md` | 404 | 380 | Large pre-production issue/audit rewrite. Commit only if intended as a canonical doc. |

## Untracked Release-Candidate Code

These are new files/directories that look directly related to the live room, replay QA, simulation product, or test harness.

| Path | What it is | Recommended action |
|---|---|---|
| `app/interview-room/[session_id]/page.tsx` | Live locked interview room controller route. | Commit. Core feature. |
| `app/interview-room/replay/page.tsx` | Replay QA launcher page. | Commit. Needed for manual testing without LLM spend. |
| `components/interview-room/InterviewRoomFloor.tsx` | Locked room visual shell extracted for live route. | Commit. Core feature. |
| `components/agents-ui/agent-audio-visualizer-aura.tsx` | Shared aura/presence visual. | Commit if imported by room shell. |
| `components/agents-ui/react-shader-toy.tsx` | Shader helper for aura. | Commit if imported by aura. |
| `hooks/agents-ui/use-agent-audio-visualizer-aura.ts` | Aura hook. | Commit if imported by aura. |
| `backend/services/replay_interview_service.py` | Deterministic replay adapter for live endpoints. | Commit. Core QA harness. |
| `scripts/generate-replay-wav.mjs` | Replay WAV fixture generation. | Commit if automated voice QA remains part of the product test plan. |
| `tests/interview-room.e2e.spec.ts` | Mocked live room route test. | Commit. |
| `tests/interview-room-live-smoke.e2e.spec.ts` | Real-session live smoke test. | Commit if documented as optional/env-gated. |
| `tests/interview-room-replay.e2e.spec.ts` | Replay launcher/room E2E test. | Commit. |
| `tests/interview-room-replay-voice.e2e.spec.ts` | Replay voice QA test. | Commit if it skips cleanly without required env/media fixtures. |
| `tests/simulation.e2e.spec.ts` | Simulation E2E test. | Commit if simulation routes are part of this deployment. |
| `playwright.config.ts` | Browser test config. | Commit with tests. |
| `lib/utils.ts` | Utility helper, likely class merge. | Commit if imported. |
| `components.json` | shadcn/ui-style component config. | Commit if `lib/utils.ts`/UI uses it. |
| `lib/voiceRuntime.ts` | Voice runtime helper/experiment. | Inspect before commit; commit only if imported by shipped routes. |

## Untracked Product/Demo Routes

These routes may be useful for demos, but they should be intentionally selected. Do not blindly ship all visualizer prototypes unless we want them public in the deployed app.

| Path | Release read |
|---|---|
| `app/investor-demo/page.tsx` | Likely useful for demos; decide whether public route is acceptable. |
| `app/simulation/page.tsx` | Engineering simulation core route. Commit if V1 includes simulation. |
| `app/simulation/admin/page.tsx` | Admin surface. Be careful exposing without auth. |
| `app/simulation/inventory/page.tsx` | Inventory simulation route. Commit if V1 includes this domain. |
| `app/simulation/report/[session_id]/page.tsx` | Simulation report route. Commit with simulation. |
| `app/voice-lab/page.tsx` | Voice lab/debug route. Keep local unless deliberately shipping an internal lab. |
| `app/visualizer-livekit-room-floor-locked/page.tsx` | Canonical locked visual reference. Commit if we want it preserved for comparison. |
| `app/visualizer-livekit-room-floor/page.tsx` | Visual prototype. Usually keep local or put behind internal route. |
| `app/visualizer-livekit-room-voice-lab/page.tsx` | Prototype/lab. Usually keep local. |
| `app/visualizer-livekit-room/page.tsx` | Prototype. Usually keep local. |
| `app/visualizer-livekit/page.tsx` | Prototype. Usually keep local. |
| `app/visualizer-livekit-candidate/page.tsx` | Prototype. Usually keep local. |
| `app/visualizer-livekit-neural/page.tsx` | Prototype. Usually keep local. |
| `app/visualizer-interview-demo-claude/page.tsx` | Demo variant. Usually keep local unless needed for investor demo. |
| `app/visualizer-interview-demo-cursor/page.tsx` | Demo variant. Usually keep local. |
| `app/visualizer-interview-demo-dossier/page.tsx` | Demo variant. Usually keep local. |
| `app/visualizer-interview-demo-flash/page.tsx` | Demo variant. Usually keep local. |
| `app/visualizer-interview-demo-synthesis/page.tsx` | Demo variant. Usually keep local. |
| `app/visualizer-map-prep-candidate/page.tsx` | Map-prep visualizer. Internal/debug route. |
| `app/visualizer-map-prep-cinematic/page.tsx` | Map-prep visualizer. Internal/debug route. |
| `app/visualizer-map-prep-internal/page.tsx` | Internal map-prep visualizer. Do not expose casually. |
| `app/visualizer-map-prep-intro/page.tsx` | Map-prep visualizer. Internal/demo route. |

## Untracked Docs

These are useful for handoff and product memory, but they are not all deployment-critical. We should either commit them as docs or move non-canonical drafts into a local archive.

| File | Release read |
|---|---|
| `ANTIGRAVITY_INTERVIEW_SYSTEM_TECHNICAL_README.md` | Strong candidate for commit; intern/onboarding technical guide. |
| `CONVERSATION_EVOLUTION_README.md` | Good project-history doc if polished. |
| `CONVERSATION_RECAP_README.md` | Good project-history doc if not duplicate. |
| `SIMULATION_CONVERSATION_README.md` | Commit if simulation work is in scope. |
| `SIMULATION_CONVERSATION_RECAP_README.md` | Commit if not duplicate. |
| `MARKETPLACE_GROWTH_V3_RUN_README.md` | Commit if useful as test artifact/historical run analysis. |
| `MODEL_EVALUATION_README.md` | Commit if model selection history matters. |
| `DEMO_DESIGN_DOSSIER.md` | Commit if used for product/design handoff. |
| `HANDOFF_CONTEXT.md` | Commit if current and accurate. |
| `ANTIGRAVITY_PRODUCT_STRATEGY_AND_DEMO_BRIEF.md` | Commit if product strategy should live in repo. |
| `ANTIGRAVITY_DEMO_VARIANT_INTENTION_BRIEF.md` | Commit if demo routes are committed. |
| `ANTIGRAVITY_UI_RESEARCH_PRD.md` | Commit if it is the UI design rationale. |
| `SIMULATION_PRD.md` | Commit if simulation product track ships. |
| `PAYMENT_RETRY_SAFETY_PRD.md` | Commit if simulation product track ships. |
| `REALTIME_ACTION_DECK_ARCHITECTURE.md` | Commit only if action deck is part of near-term architecture. |
| `REALTIME_INTERACTION_ACTION_DECK_CONTRACT.md` | Commit only if action deck is part of near-term architecture. |
| `ai_observed_engineering_simulation_platform_thesis_document.md` | Product thesis; commit if intentionally canonical. |
| `ISASUE.md` | Looks like rough issue notes. Rename or keep local. |
| `2CISASUE copy.md` | Looks like rough/duplicate issue notes. Keep local or rename before commit. |

## Untracked HTML Previews

These are standalone design previews. They are not needed for production runtime unless someone explicitly uses them as artifacts.

- `antigravity-live-room-preview.html`
- `antigravity-neural-interview-preview.html`
- `antigravity-neural-visualizer-preview.html`
- `antigravity-ui-research-brief.html`

Recommended action: keep local or move to a clearly named `docs/design-previews/` folder if we want them versioned.

## Replay Fixtures And Runtime Logs

### Session exports

Directory: `backend/data/session_exports/`
Count: 13 JSON files
Approx size: 936 KB

These are used by `ReplayInterviewService` as replay cases. They are small enough to commit and useful for deployed/manual QA if the replay launcher should show cases outside Yash's machine.

Files:

- `0186a07c-2ec2-413e-b297-c76b5aaa541b.json`
- `099b5417-1355-4a39-98fb-11a86e98a65f.json`
- `0a3779aa-4b8c-49df-8058-18af0cb44bcc.json`
- `3b362657-5f4b-4937-a930-44cc1009ec54.json`
- `3dfa958d-9395-4c7c-a9bc-d3a9ff747f78.json`
- `3e95257c-f290-4546-9a8e-e22430f2cb9d.json`
- `405b4943-f4cd-4370-88dc-b2722d630b55.json`
- `5ce15b7c-a0c1-4731-b0e8-90acab38266c.json`
- `6013d0d3-14d3-47ad-aafa-23c377be9cfd.json`
- `a3a1e7b5-c931-437a-a9c8-77b14294856a.json`
- `c1e66811-c749-431c-9925-47636d4cbb46.json`
- `ced237fe-624e-401f-b55a-8404ae1ae6a3.json`
- `f35e4aaf-6a39-44a6-bc66-bf186a70801c.json`

### Runtime logs

Directories:

- `backend/runtime/llm_usage/` approx 14 MB
- `backend/runtime/llm_quality/` approx 9.6 MB

Recommended action: do not commit. They are local spend/quality logs and can contain operational telemetry. `.gitignore` now excludes both directories.

## Deployment Surface

### Frontend

Likely deployment target: Vercel.

Relevant files:

- `package.json`
- `package-lock.json`
- `next.config.ts`
- `vercel.json`

Current frontend build command:

```bash
npm run build
```

Important environment variable:

```bash
NEXT_PUBLIC_API_URL=https://<backend-host>
```

For local testing this is usually `http://localhost:8000`. For production/manual test deployment it should point to the deployed FastAPI backend, not a local port.

### Backend

Likely deployment target: Render.

Relevant files:

- `render.yaml`
- `requirements.txt`
- `backend/main.py`

Render command from `render.yaml`:

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Important backend environment variables:

- `OPENROUTER_API_KEY`
- `DEEPGRAM_API_KEY`
- `CARTESIA_API_KEY`
- `ELEVENLABS_API_KEY`
- `REDIS_URL`
- `DATABASE_URL`
- `FRONTEND_URL`
- `PROVENHIRE_API_URL`
- `ANTIGRAVITY_WEBHOOK_SECRET`

### Vercel rewrite caution

`vercel.json` currently rewrites `/api/(.*)` to `/api/index.py`, which imports `backend.main`. This means a Vercel deploy may try to serve FastAPI through Vercel Python serverless, while `render.yaml` separately deploys the backend on Render.

Before production deployment, choose one of these API strategies:

1. Frontend-only Vercel + backend on Render. Set `NEXT_PUBLIC_API_URL` to Render and consider removing/neutralizing the Vercel Python API rewrite if it is not needed.
2. Full Vercel Python ASGI route. Keep `api/index.py`, but verify FastAPI dependencies and long-running voice/replay endpoints work inside Vercel limits.

For the current manual testing plan, strategy 1 is safer: Vercel frontend, Render backend.

## Recommended Commit Strategy

Do not run `git add .`.

Suggested split:

### Commit 1: Live room and replay QA

Include:

- `app/interview-room/`
- `components/interview-room/`
- `components/agents-ui/`
- `hooks/agents-ui/`
- `lib/audio.ts`
- `lib/vision.ts`
- `components/Waveform.tsx`
- `backend/api/routes.py`
- `backend/services/replay_interview_service.py`
- `backend/main.py`
- `backend/data/session_exports/` if replay cases should exist in deploy
- `package.json`
- `package-lock.json`
- `playwright.config.ts`
- `scripts/generate-replay-wav.mjs`
- `tests/interview-room*.ts`
- `.gitignore`
- this document

### Commit 2: Interview brain/report/question-quality readiness

Include:

- `backend/services/orchestrator.py`
- `backend/services/interview_map.py`
- `backend/services/question_quality.py`
- `backend/data/question_quality_guide.json`
- `backend/models/final_report.py`
- `backend/state/session_manager.py`
- `backend/test_final_report_contract.py`
- `backend/test_question_quality_contract.py`
- `app/interview/[session_id]/page.tsx`
- `app/report/[session_id]/page.tsx`
- `app/globals.css`

This should only be committed after backend contract tests pass.

### Commit 3: Docs and demos

Include only curated docs and public-safe demo routes.

Avoid committing:

- `backend/runtime/llm_usage/`
- `backend/runtime/llm_quality/`
- rough duplicate docs such as `2CISASUE copy.md` unless renamed/cleaned;
- public internal visualizer/admin routes unless intentionally exposed.

## Minimum Verification Before Push

Run these locally before pushing:

```bash
npm run build
python3 -m py_compile backend/main.py backend/api/routes.py backend/services/replay_interview_service.py backend/services/orchestrator.py backend/services/interview_map.py backend/services/question_quality.py backend/models/final_report.py backend/state/session_manager.py
python3 backend/test_question_quality_contract.py
python3 backend/test_final_report_contract.py
npm run test:replay-room
git diff --check
```

For the live voice route, also manually verify:

- `/interview-room/replay` loads replay cases.
- A replay room starts.
- TTS asks the opening question.
- Candidate speech produces live partial transcript.
- Barge-in/continued answer stays attached to the previous question.
- Repeat question stops current playback and reuses cached repeat/question audio.
- The static answer acknowledgment plays before the next question.
- Committed history updates once per answer.
- End interview reaches report/close state.

## Push Procedure

Safe branch flow:

```bash
git checkout -b release/v1-live-room-replay
git add <curated file list>
git status --short
git commit -m "prepare live room replay QA release"
git push -u origin release/v1-live-room-replay
```

If main auto-deployment is required today:

```bash
git checkout main
git pull --ff-only
git add <curated file list>
git status --short
git commit -m "prepare live room replay QA release"
git push origin main
```

Do the main push only after the verification commands pass and the staged file list is reviewed.

## Manual Testing Deployment Plan

1. Deploy backend to Render with required env vars and a working Redis URL.
2. Confirm backend health:

```bash
curl https://<backend-host>/health
curl https://<backend-host>/api/replay/cases
```

3. Deploy frontend to Vercel with:

```bash
NEXT_PUBLIC_API_URL=https://<backend-host>
```

4. Confirm frontend pages:

```text
https://<frontend-host>/
https://<frontend-host>/interview-room/replay
```

5. Manual test with 5 people using replay first, then live sessions:

- 1 person tests normal answer flow.
- 1 person tests repeat question.
- 1 person tests barge-in while TTS is speaking.
- 1 person tests delayed continuation after answer commit.
- 1 person tests long answers and report close.

6. Only after replay/manual voice QA is stable, start paid LLM-backed live sessions.

## Open Release Questions

- Should the many `app/visualizer-*` demo routes be public in V1, hidden, or left uncommitted?
- Should replay QA be available in production, or only preview/staging?
- Should `vercel.json` keep the Python API rewrite if the backend is deployed on Render?
- Are `problem.md`, `AGENTS.md`, and `PROJECT_STATE.md` current enough to commit as canonical project memory?
- Do we want a dedicated staging branch/deployment before touching `main`?

