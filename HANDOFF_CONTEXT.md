# Antigravity — Session Handoff Context

**Purpose:** Feed this file to a new Claude Code session to bring it fully up to speed for a **product and ideas conversation** — not engineering. No code changes. The goal is to continue a deep discussion about the product's philosophy, interview design, psychological layer, and where this goes as a product.

**Instructions for the new session:** Read this file first, then follow the reading sequence below in order. Do not skip steps. Do not jump to fixing code. The grounding is for the conversation, not for implementation. Once grounded, engage as a thinking partner — challenge ideas, contribute your own analysis, disagree where you disagree. This is not a yes-man role.

---

## What This Project Is

Antigravity is a **voice-native AI technical interviewing system**. It conducts live structured interviews, evaluates candidates, and sends results to recruiters. The system is designed to test ownership, reasoning depth, and engineering judgment under real conversational pressure — not trivia, not LeetCode.

It is NOT a chatbot. It is NOT a form. It is a fully orchestrated multi-agent interview system with:
- Resume-grounded interview map generation (pre-built before the candidate connects)
- Real-time voice (Deepgram STT, Cartesia TTS)
- Parallel background agent pipeline (weakness detection, discrepancy detection, reasoning behavior)
- Staged question delivery (next question prepared while candidate answers current one)
- Final evaluation with hire recommendation

The system is currently in pre-production. It has been tested on ~20 real candidates. It has real bugs that block production. The goal of the next session is to fix them.

---

## Stack at a Glance

- **Frontend:** Next.js App Router, TypeScript, Tailwind
- **Backend:** FastAPI (Python), single Vercel serverless function at `api/index.py`
- **State:** Redis (Upstash) — live sessions, 4h TTL
- **DB:** Postgres — completed session storage
- **STT:** Deepgram (browser-side)
- **TTS:** Cartesia (backend)
- **LLMs:** All via OpenRouter
  - small: `claude-haiku-4-5` (seed questions, adaptation, speculative)
  - medium: `claude-sonnet-4-6` (weakness, discrepancy, reasoning, follow-up)
  - large: `deepseek/deepseek-r1` (final evaluation only)

---

## Mandatory Reading Sequence

Go through these in order. Do not rush. The context compounds.

---

### STEP 1 — Read the pre-production bug audit first

```
/Users/yash/antigravity/problem.md
```

This is the most important file for the next session. It contains:
- 4 CRITICAL bugs that block production
- 5 HIGH priority quality issues
- 6 MEDIUM priority issues
- 6 DESIGN/architectural gaps

Read it fully. The bug IDs (C-1, C-2, C-3, C-4, H-1, etc.) are referenced throughout the codebase discussion. Know them.

---

### STEP 2 — Understand the system architecture end-to-end

Read the orchestrator (the interview controller — ~2600 lines):
```
/Users/yash/antigravity/backend/services/orchestrator.py
```
Read in chunks using offset/limit. Key sections to understand:
- The class docstring at the top (explains the two-track architecture)
- `handle_transcript()` — the fast path, the entire priority waterfall
- `_run_background_pipeline()` — what runs while the candidate answers
- `_apply_staged_analysis()` — the Codex invariant (canonical state only mutates here)
- `_infer_focus()` — this is C-2 in problem.md, it's broken
- `consecutive_high_weakness_count` tracking — this is C-3, also broken
- `start_prepared_session()`, `prepare_session_map()`

Read the interview map generator (~1400 lines):
```
/Users/yash/antigravity/backend/services/interview_map.py
```
Key sections:
- `generate_interview_map()` — the full LLM pipeline
- `_FOCUS_PLAN_SYSTEM` prompt — how focus areas are selected from resume
- `_TRACK_SYSTEM_BASE` + role overrides — how dimension probes are generated
- `_MAP_CRITIC_SYSTEM` — the critic pass that scores and flags weak questions
- `select_from_trajectory_map()` and `select_from_trajectory_map_detailed()` — runtime question selection (this is where C-4 shows up)
- The route name constants at the top — `ROUTE_*` strings

---

### STEP 3 — Read the agents

These are all in `/Users/yash/antigravity/backend/agents/`. Read all of them:

```
/Users/yash/antigravity/backend/agents/resume_agent.py
```
This is C-1 in problem.md. The parser is producing garbage output on real resumes. Read `_heuristic_parse()` and `_merge_with_fallback()` specifically.

```
/Users/yash/antigravity/backend/agents/followup_agent.py
```
The most complex agent. All 13 methods. Understand:
- `PERSONA_PROMPTS` (3 personas)
- `PROBE_DIRECTION_INSTRUCTIONS` (7 directions — these need an 8th: `explore_strength`)
- The full priority chain inside `generate()`
- `_build_resume_context()` — this receives broken parsed_resume (C-1 downstream effect)
- `adapt_followup()` — lightweight surface modification (not deep enough)

```
/Users/yash/antigravity/backend/agents/weakness_agent.py
/Users/yash/antigravity/backend/agents/discrepancy_agent.py
/Users/yash/antigravity/backend/agents/reasoning_behavior_agent.py
/Users/yash/antigravity/backend/agents/evaluation_agent.py
```

```
/Users/yash/antigravity/backend/models/llm_router.py
```
Understand the three tiers (small/medium/large), token budgets, timeouts, and how JSON extraction works.

```
/Users/yash/antigravity/backend/models/coverage_map.py
/Users/yash/antigravity/backend/state/candidate_state.py
/Users/yash/antigravity/backend/state/session_manager.py
```

---

### STEP 4 — Read the API routes

```
/Users/yash/antigravity/backend/api/routes.py
```
Understand all endpoints. Key ones: `prepare_interview_map`, `start_interview`, `process_turn`, `partial_transcript`, `end_interview`, `report`.

---

### STEP 5 — Read real session exports (ground truth of what actually happens)

These are completed real interviews. Read both fully.

**Session 1 — Praveen (MAYBE, 6.5/10):**
```
/Users/yash/antigravity/backend/data/session_exports/ced237fe-624e-401f-b55a-8404ae1ae6a3.json
```
This is a mediocre candidate — conceptual knowledge, no implementation depth. Read the full history (15 turns), all weaknesses, the final_evaluation, and the interview_trajectory_map. Key things to notice:
- `parsed_resume` is garbage (C-1 visible here)
- Every turn has `focus_key: ""` (C-2 visible here)
- `sprint_seed` dominates route_kinds (C-4 visible here)
- 7 of 14 weaknesses labeled `shallow` or `missing_step` — accuracy is good
- Final verdict MAYBE is calibrated correctly

**Session 2 — Mahesh (NO HIRE, 2/10):**
```
/Users/yash/antigravity/backend/data/session_exports/5ce15b7c-a0c1-4731-b0e8-90acab38266c.json
```
This is a resume fraud case. Read the full history. Key things:
- Turn 2: candidate answers "hello" to a technical question — how the system handles it
- Turn 6: candidate admits maker-checker was never implemented — `conflict_level: "confirmed"`
- Turn 9: candidate admits fine-grained RBAC was never implemented — second confirmed contradiction
- Turn 10: candidate describes trusting client email in request body for auth — `type: "incorrect"`, actual security flaw caught
- ALL 15 turns stuck on CMS/RBAC — Golang microservices never tested (C-3 / bridge never fires)
- `consecutive_high_weakness_count: 0` at session end despite 8+ high-severity weaknesses — C-3 confirmed broken
- Final verdict NO HIRE at confidence 0.85 — calibrated correctly despite incomplete coverage

**Session 3 — AppsForBharat (never ran, map only):**
```
/Users/yash/antigravity/backend/data/session_exports/3b362657-5f4b-4937-a930-44cc1009ec54.json
```
Same resume as Session 2 but this session was prepared and never started. Read `interview_trajectory_map` and `pass_1_review` (the critic output). This shows what a GOOD trajectory map looks like — both focus areas have strong surface/mechanism/boundary dimension probes. The critic also correctly flags two weak surface probes and gives specific repair instructions. This is the system working as designed.

---

### STEP 6 — Read the design documents (understand where the product is going)

```
/Users/yash/antigravity/2CISASUE copy.md
```
The most important design doc. Covers:
- Why the current system feels robotic (epistemic aggression, not just bad tone)
- The three-layer questioning model (Technical / Communication / Psychological)
- "LLM as renderer, system as interviewer" — the architectural principle
- Transition intelligence — quality lives in (Q, A, Q+1) not isolated questions
- The RLHF / pairwise preference learning experiment design

```
/Users/yash/antigravity/ISASUE.md
```
Summary doc. Lists current problems and proposed solutions concisely.

```
/Users/yash/antigravity/ai_observed_engineering_simulation_platform_thesis_document.md
```
Long-term vision doc — engineering simulation platform (give candidates a broken codebase, observe debugging behavior). READ THIS but understand: this is a DIFFERENT product from Antigravity. Do not conflate. It is a long-term direction, not the next sprint.

---

### STEP 7 — Read supporting files for full context

```
/Users/yash/antigravity/backend/services/provenhire_handoff.py
```
ProvenHire integration — how Antigravity receives candidates from and sends results back to the ATS.

```
/Users/yash/antigravity/app/interview/[session_id]/page.tsx
```
The frontend interview page (~1242 lines). Understand:
- The floor state machine (IDLE → USER_SPEAKING → AI_THINKING → AI_SPEAKING)
- Barge-in handling
- TTS pre-caching and filler audio
- How partial transcripts are sent to backend

---

## Key Things to Know Going In

### The Two-Track Architecture
**Fast Track (~300-500ms):** `handle_transcript()` — consumes staged analysis from previous turn → serves pre-staged question from background pipeline → OR falls through priority chain to seed/fallback. Must be fast. No heavy LLM calls here.

**Slow Track (runs during candidate's answer):** `_run_background_pipeline()` — parallel WeaknessAgent + DiscrepancyAgent + ReasoningBehaviorAgent → full FollowUpAgent priority chain → writes staged next question. NEVER touches canonical state. Only writes to `prepped_*` fields.

**The Codex Invariant:** Canonical state (history, weaknesses, scores) only mutates in `_apply_staged_analysis()` at the START of the next turn, not during background pipeline. This is intentional and must be preserved.

### The Critical Bugs (know these before touching any code)

**C-1 (Resume Parser):** `resume_agent.py` produces garbage `parsed_resume` on real resumes. Skills=[], projects=[], experiences=[] despite rich resume content. The trajectory map bypasses this (reads raw resume string directly). Everything else downstream (FollowUpAgent._build_resume_context, experience_tier, ownership level) gets garbage. The failure is silent — no exceptions.

**C-2 (_infer_focus broken):** Every turn in every completed session has `focus_key: ""`. `_infer_focus()` always returns empty. This breaks: trajectory map selection, coverage tracking, bridge mechanism, speculative cache. The active_question_packet already has the correct focus_key — it just needs to be propagated to the turn history instead of re-inferred.

**C-3 (Bridge never fires):** `consecutive_high_weakness_count` shows 0 at session end despite multiple high-severity weaknesses. The bridge mechanism that should pivot the interview to a new focus area when one is exhausted never triggers. This caused Mahesh's interview to spend all 15 turns on one topic.

**C-4 (sprint_seed dominates):** The trajectory map is built carefully with LLM + critic + repair. At runtime, 7 of 15 turns fall through to `sprint_seed` (Haiku improvisation) instead of using the map. Likely caused by C-2 (can't navigate the map without focus_key) and the background pipeline not reliably staging map-sourced questions.

### What's Working Well (don't break it)
- WeaknessAgent detection is accurate and precise
- DiscrepancyAgent catches confirmed contradictions reliably
- The trajectory map generation quality is high (when the resume parses correctly)
- The critic pass self-evaluation is functioning
- Final evaluation verdicts are calibrated correctly
- Speculative generation fires and produces good questions
- The two-track staging architecture (fast path + background) is correct in design

### Philosophy Direction (settled, don't re-litigate)
- Moving from adversarial-first to substance-measurement-first
- Adversariality is a tool, not the philosophy
- The goal is measuring real capability, not proving claims true/false
- "Follow the interesting signal" branch needs to be added (system only follows up on failures, never on strengths)
- Experience-tier calibration needs to be added (junior/mid/senior probe depth is currently identical)
- RLHF experiment is the right medium-term direction but ONLY after Phase 1 bugs are fixed

---

## What the Previous Session Actually Discussed (the real handoff)

This session was a deep product and philosophy conversation. These are the threads that were live and unresolved when context ran out. The new session should pick these up.

---

### Thread 1 — Measurement vs. Proof (most important, still open)

The system is currently built as an investigation tool masquerading as an interview tool. It tries to PROVE candidates right or wrong. The right goal is to MEASURE substance. These are different activities.

Key settled point: bad candidates naturally score low, good candidates naturally score high — you don't need to prove anyone wrong 20 times. Three follow-up questions from multiple angles is enough to establish a claim is inflated. After that you should move on and measure more dimensions, not keep drilling the same hole.

What's NOT settled: how do you actually operationalize "measurement mode" vs "verification mode" in a live interview system? What does the routing logic look like? What signals tell the system it has enough evidence and should pivot?

---

### Thread 2 — The Psychological Layer (open, needs more depth)

Yash made a strong argument that the psychological contract of the interview is the most important underinvested layer. The analogy he used: people are more vulnerable and open with ChatGPT than they are with social media apps that have their real data — because of HOW the interaction feels, not the content.

The core problem: if a candidate doesn't feel psychologically safe, you're only measuring how well they perform under pressure, not their actual depth. You can have perfect questions and still get worse signal than a mediocre human interviewer because the human establishes psychological comfort and the AI doesn't.

What was identified as missing:
- No acknowledgment when a candidate says something correct or interesting
- No "follow the interesting signal" branch — system only follows failures, never strengths
- No genuine curiosity — every question is a probe, never "wait, that's interesting, tell me more"
- No narrative invitation mode — questions demand technical recall, never activate storytelling

What's NOT settled: what specific conversation moves establish psychological safety in a voice AI interview? This is harder than it sounds because the usual human signals (eye contact, nodding, tone warmth) are absent. What replaces them?

---

### Thread 3 — Question Quality: Human-Good vs AI-Good (open)

Yash made a point that AI-generated questions that LOOK good on paper often fail to elicit real substance from humans. The example: "What was the first thing that broke your assumptions?" — technically relevant, but psychologically narrow and hard to emotionally enter.

There are two separate critiques here:
1. Questions demand episodic memory ("what broke first?") when they should invite reasoning ("how would you expect this to behave under X?") — people lose context on past projects, reconstruction is easier than recall
2. Questions are semantically optimized (extract information) instead of conversationally inviting (create momentum for the person to share more)

What's NOT settled: is the memory/context-loss argument correct? The counter-argument is that a person who genuinely owned something can reconstruct the reasoning even without remembering specifics. The question framing (recall vs. reasoning) might matter more than the question type. This needs more discussion.

---

### Thread 4 — Adversariality as Tool vs. Philosophy (partially settled)

Settled: adversariality-first is wrong. The interview should not open in challenge mode. The psychological contract from Q1 should be curiosity, not interrogation.

Settled: adversariality is necessary and valuable — it puts the right pressure on claims, exposes fraud, tests depth. It just needs to be earned through the conversation, not applied from the first question.

NOT settled: what's the right escalation curve? How does the system know when to apply pressure vs. when to ease off? What signals tell it the candidate has shown enough to deserve the harder question, vs. the candidate is already at their ceiling and more pressure just produces defensive noise?

---

### Thread 5 — The RLHF Experiment Direction (early stage, needs more thought)

The design documents propose pairwise preference learning of conversational trajectories (Q, A, Q+1) judged by human evaluators across 4 dimensions: technical, conversational, psychological, reasoning.

The core insight: humans are bad at absolute scoring but good at comparative preference. "Which trajectory feels more human?" is easier and more reliable than "rate this 1-10."

Open questions that need more discussion:
- Who are the right evaluators? A person who can judge BOTH technical depth AND conversational quality AND psychological dynamics is rare. How do you find them? How many do you need?
- If you generate trajectory pairs from the same LLM, are you just learning which version of that LLM's priors is preferred? Or does pairwise comparison surface genuine signal about human preference?
- What's the minimum viable experiment — what does the smallest useful version of this look like?

---

### Thread 6 — The Engineering Simulation Platform (long-term, separate product)

The thesis document (ai_observed_engineering_simulation_platform_thesis_document.md) proposes replacing voice Q&A with placing candidates inside simulated broken codebases and observing their debugging behavior via telemetry.

The strongest idea in it: **imperfect AI as a test of verification ability** — the system generates tests with intentional gaps, candidates who validate catch it, candidates who blindly accept it fail. This reveals whether someone can supervise AI output, which is increasingly the core engineering skill.

The conversation settled: this is a DIFFERENT product, not Antigravity v2. Do not conflate. But it's worth continuing to think about because the verification-ability insight might be applicable to the current voice interview format in some way. How?

---

## What the Session Did NOT Get To

These were identified as important but never discussed:

1. **The narrative invitation structures** — the design docs say "invite storytelling not extraction" but never specify what conversation moves actually trigger narrative. What are they concretely?

2. **Experience-tier calibration in depth** — how should questions actually differ for a 1-year engineer vs a 5-year engineer beyond just "ownership depth"? What does good junior-tier interviewing look like vs good senior-tier interviewing?

3. **The specific RLHF experiment design** — what does the evaluator interface look like? What's the minimum dataset size? How do you generate trajectory pairs with enough diversity?

4. **ProvenHire integration and how it affects interview design** — candidates coming from an ATS have prior assessment context. How should that change the interview? Should it?

---

## Recommended First Actions for the New Session

1. Read `problem.md` — know the bugs, but don't focus on fixing them. This session is ideas.
2. Read the three design documents in this order:
   - `/Users/yash/antigravity/ISASUE.md` (shortest, sets the problem)
   - `/Users/yash/antigravity/2CISASUE copy.md` (most developed, the real proposal)
   - `/Users/yash/antigravity/ai_observed_engineering_simulation_platform_thesis_document.md` (long-term vision)
3. Read ONE of the real session exports to get grounded in what the system actually does:
   - `/Users/yash/antigravity/backend/data/session_exports/5ce15b7c-a0c1-4731-b0e8-90acab38266c.json` (Mahesh, NO HIRE — most interesting)
4. Then engage. Pick up whichever thread above feels most unresolved and go deep on it.

Do not start fixing code. This is a product thinking session.

---

## File Map (quick reference)

```
/Users/yash/antigravity/
├── problem.md                          ← START HERE. Pre-production bug audit.
├── HANDOFF_CONTEXT.md                  ← This file
├── 2CISASUE copy.md                    ← Design: preference-aligned conversational interviewing
├── ISASUE.md                           ← Design: problem summary doc
├── ai_observed_engineering_simulation_platform_thesis_document.md  ← Long-term vision (different product)
│
├── backend/
│   ├── api/routes.py                   ← All API endpoints
│   ├── services/
│   │   ├── orchestrator.py             ← THE interview controller (~2600 lines)
│   │   ├── interview_map.py            ← Map generation + runtime selection (~1400 lines)
│   │   ├── tts_service.py              ← TTS + filler pre-caching
│   │   └── provenhire_handoff.py       ← ATS integration
│   ├── agents/
│   │   ├── resume_agent.py             ← C-1 IS HERE. Broken parser.
│   │   ├── followup_agent.py           ← All 13 question generation methods
│   │   ├── weakness_agent.py           ← Working well. Don't break.
│   │   ├── discrepancy_agent.py        ← Working well. Don't break.
│   │   ├── reasoning_behavior_agent.py
│   │   ├── evaluation_agent.py         ← Final hire recommendation
│   │   ├── concept_agent.py
│   │   └── application_agent.py
│   ├── models/
│   │   ├── llm_router.py               ← 3 tiers, JSON extraction, think-tag stripping
│   │   └── coverage_map.py             ← Dimension coverage tracking
│   └── state/
│       ├── candidate_state.py          ← Disengagement, communication mode, fatigue
│       └── session_manager.py          ← Redis-backed session state
│
├── app/
│   ├── interview/[session_id]/page.tsx ← Frontend interview page (~1242 lines)
│   ├── launch/page.tsx                 ← ProvenHire handoff entry
│   ├── dashboard/                      ← Recruiter dashboard
│   └── report/[session_id]/            ← Post-interview report
│
└── backend/data/session_exports/
    ├── ced237fe-...json                ← Praveen session (MAYBE, 6.5) — mediocre candidate
    ├── 5ce15b7c-...json                ← Mahesh session (NO HIRE, 2.0) — resume fraud
    └── 3b362657-...json                ← AppsForBharat (never ran) — good map example
```

---

## What Was Accomplished in the Previous Session

1. Full A-Z codebase read — all agents, orchestrator, interview_map, frontend, routes
2. Both completed sessions analyzed in detail — every turn, all weaknesses, all route_kinds
3. Four design documents read and analyzed
4. Extended discussion on product philosophy — measurement vs. proof, adversariality as tool, psychological layer
5. Full pre-production bug audit written to `problem.md` — 4 critical, 5 high, 6 medium, 6 design issues
6. Memory files updated at `/Users/yash/.claude/projects/-Users-yash-antigravity/memory/`

The previous session was entirely analysis and planning. No code was changed. This session continues the product and ideas conversation — see the six open threads above.
