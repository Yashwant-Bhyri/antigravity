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
