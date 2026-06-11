# Antigravity Interview System Technical README

Last updated: 2026-06-03

This document explains how Antigravity's interview engine works, why it is designed this way, and how a tester should think about each component. It is written for a new engineer or QA intern joining the project.

## Product Philosophy

Antigravity is not a quiz bot and not a resume validator. The product goal is to run a role-calibrated interview that discovers how a candidate thinks under realistic ambiguity.

The system should:

- start from the candidate's resume and target role;
- identify the highest-signal work surfaces;
- ask grounded, human, plain-English questions;
- clarify before pressuring;
- pressure only after enough context exists;
- test application transfer to a nearby role-relevant scenario;
- measure coverage and uncertainty honestly;
- avoid endless drilling on one claim;
- avoid over-punishing resume hype when interview evidence is narrower;
- report what was shown, what was not tested, and what remains uncertain.

The system should not:

- ask deterministic generic interview questions during assessment-critical phases;
- promote off-role projects just because they sound technical;
- ask hidden implementation-internal questions unless the candidate claimed that layer;
- treat one inflated claim as proof the whole candidate is bad;
- produce confident rejection language after a narrow or tunneled interview;
- hide failures behind retries that rewrite the test.

## High-Level Interview Flow

The intended flow is:

```text
resume + role
  -> resume parse
  -> SurfacePlanV2 recommendation
  -> focus/sub-focus plan
  -> launch-ready map prep
  -> warm opener
  -> primary focus frame/clarify/explore
  -> application transfer
  -> coverage questions
  -> second anchor / role-relevant pivot
  -> synthesis / close
  -> Report V2
```

The interview starts with a human warm opener. The first content question should usually be exploratory, not prosecutorial. The system then builds depth incrementally.

## Runtime Components

### FastAPI routes

Primary file:

- `backend/api/routes.py`

Important endpoints:

- `/start_interview`: starts a prepared interview session.
- `/process_turn`: receives a committed candidate answer and returns the next interviewer question.
- `/partial_transcript`: receives partial transcript snapshots for speculative work.
- `/end_interview`: finalizes the session and report.
- `/state`: exposes current session state.
- `/report/{session_id}`: exposes report output.
- `/tts`, `/tts_filler`: speech synthesis endpoints.

### Orchestrator

Primary file:

- `backend/services/orchestrator.py`

This is the runtime brain. It coordinates:

- session initialization;
- map preparation;
- fast-path question serving;
- background agent analysis;
- application-transfer staging;
- coverage staging;
- second-anchor routing;
- synthesis and finalization;
- Report V2 generation.

The orchestrator has two important loops:

1. Fast path:
   - consume already prepared packets;
   - select the next question quickly;
   - update visible state;
   - start background work.

2. Background pipeline:
   - analyze the candidate answer;
   - run agents;
   - decide the next route;
   - stage the next packet;
   - pre-generate TTS where possible.

The split exists because the voice product needs a fast response, but high-quality reasoning may take longer.

## Agents

### ResumeAgent

Primary file:

- `backend/agents/resume_agent.py`

Purpose:

- parse resume;
- extract roles, claims, metrics, projects, and evidence anchors;
- feed map planning and follow-up prompts.

### ConceptAgent

Primary file:

- `backend/agents/concept_agent.py`

Purpose:

- extract concrete concepts from the latest answer;
- identify entities and topic surfaces;
- support downstream weakness/follow-up logic.

### WeaknessAgent

Primary file:

- `backend/agents/weakness_agent.py`

Purpose:

- identify gaps, vagueness, unsupported claims, shallow reasoning, or contradictions;
- classify severity;
- suggest whether to continue probing.

Important caution:

- Weakness detection should guide the interview, not dominate it. A weakness is not automatically a verdict.

### DiscrepancyAgent

Primary file:

- `backend/agents/discrepancy_agent.py`

Purpose:

- compare the candidate's answer against resume claims and prior statements;
- identify suspected or confirmed contradictions;
- trigger direct challenge only when evidence supports it.

### ReasoningBehaviorAgent

Primary file:

- `backend/agents/reasoning_behavior_agent.py`

Purpose:

- evaluate how the candidate reasons;
- track clarity, calibration, first-principles reasoning, and adaptability.

### FollowUpAgent

Primary file:

- `backend/agents/followup_agent.py`

Purpose:

- generate clarification questions;
- generate depth probes;
- adapt map follow-ups;
- generate coverage questions;
- generate graceful close messages.

This agent is used both in normal question generation and rescue situations.

### ApplicationAgent

Primary file:

- `backend/agents/application_agent.py`

Purpose:

- create role-relevant application-transfer scenarios;
- preserve the candidate's actual evidence boundary;
- avoid unsupported hidden implementation internals;
- create a coverage map for the transfer question.

Application transfer is not just a hard question. It tests whether the candidate can apply their demonstrated thinking to an adjacent role-relevant situation.

### PolicyCheckerAgent

Primary file:

- `backend/agents/policy_checker_agent.py`

Purpose:

- warn about routing policy risks;
- detect repeated focus/surface streaks;
- flag missing map focus;
- flag late generic routes;
- flag bad question readiness.

It is mostly advisory today. It records warnings and helps evaluate whether the runtime drifted from the intended interview philosophy.

### EvaluationAgent and Report V2

Primary files:

- `backend/agents/evaluation_agent.py`
- `backend/models/final_report.py`

Purpose:

- evaluate final role fit;
- apply coverage gates;
- generate evidence-first Report V2;
- avoid candidate-wide conclusions when interview coverage was narrow.

The final report should synthesize evidence, not merely average scores.

## Map Preparation

Primary file:

- `backend/services/interview_map.py`

Map prep is the most important upstream quality layer.

### Step 1: Resume and role context

Inputs:

- resume text;
- target role;
- years of experience;
- optional artifacts or known role rubric.

The resume is not treated as truth. It is treated as a source of claims and potential interview surfaces.

### Step 2: SurfacePlanV2 recommendation

SurfacePlanV2 is a pre-map recommendation layer. It identifies:

- experience areas;
- focus areas;
- sub-focus surfaces;
- testable surfaces;
- demoted/off-role surfaces;
- missing or risky checks.

Current default model:

- `openai/gpt-5.4-mini`

Important rule:

- `recommended_allocation_hint` is advisory only.
- It must not directly decide question counts or interview budgets.

### Step 3: Focus plan

The focus plan turns recommendations into role-relevant focus areas.

Good focus areas are not just resume bullets. They are testable surfaces, such as:

- seller activation attribution;
- event taxonomy and denominator design;
- dashboard decision support;
- dbt modeling and reconciliation;
- ownership boundary around instrumentation.

The focus plan should demote off-role artifacts unless the role makes them relevant.

### Step 4: LaunchTrackLite

Launch-Ready Map Prep V3 introduced `LaunchTrackLite`.

Startup no longer waits for a perfect full V2 map. It only requires the first two launch tracks to be usable.

LaunchTrackLite contains:

- `frame`;
- `clarify`;
- `explore`;
- `pressure`;
- `recover`;
- two assessment dimensions max;
- expected space;
- signal goal;
- information gain;
- voice complexity;
- focus and sub-focus provenance.

Startup does not require:

- full six-posture ladder;
- synthesize question;
- candidate Q4 options;
- rich recovery object;
- all secondary tracks;
- whole-map Sonnet review.

### Step 5: Compact launch critic

Startup uses a compact Sonnet critic. It answers:

- Are the first two tracks usable?
- Are they role-relevant?
- Are they distinct?
- Is the primary anchor sensible?
- Is the second anchor usable for coverage or pivot?
- Is anything unsafe enough to block launch?

Local issues become warnings if launch is still safe.

### Step 6: Async hydration

After launch-ready state is saved, the orchestrator starts async hydration for deferred tracks.

Hydration should:

- generate richer full V2 tracks;
- critique each track individually;
- quarantine bad tracks;
- add accepted tracks into routing;
- never overwrite active launch tracks.

Important bug fixed on 2026-06-03:

- hydration now starts only after the launch map is saved into session state.
- Earlier, hydration could read an empty session map and silently exit.

## Question Philosophy

Questions should follow a voice-first ladder:

1. Frame:
   - start the claim;
   - give the candidate a direction;
   - avoid prosecutor tone.

2. Clarify:
   - ask definitions, denominator, ownership boundary, scope.

3. Explore:
   - ask how they reasoned through the work.

4. Pressure:
   - ask one sharp challenge after context exists.

5. Synthesize:
   - recap plainly and test uncertainty or limits.

6. Recover:
   - handle shallow, vague, or evasive answers.

Good questions:

- are spoken plainly;
- have one main ask;
- expose a decision space;
- include an escape hatch when giving answer lanes;
- test high-signal reasoning, not trivia.

Bad questions:

- ask "which part are you most confident in";
- ask late low-level recall like exact SQL script names;
- sound like a prosecutor from turn 2;
- ask multiple hidden questions in one sentence;
- introduce unsupported internals.

## Application Transfer

Application transfer usually appears around turns 5-7 when enough evidence exists.

It tests:

- role-relevant application;
- transfer of reasoning;
- breadth across 2-3 surfaces;
- at most one or two earned depth probes.

The system may ask a grounding clarification before application transfer when the candidate's depth layer is ambiguous. That grounding question should not count as evidence breadth.

Depth levels are roughly:

- L1: decision/framing;
- L2: operating workflow or analytics mechanism;
- L3: specialized technical layer supported by evidence;
- L4: deep internals, only if explicitly claimed or confirmed.

Hidden internals like model weights, embeddings, diffusion internals, or proprietary engine parameters should not be asked unless supported.

## Coverage

Application transfer creates a coverage map.

Coverage checks whether the candidate addressed important dimensions such as:

- attribution strategy;
- denominator;
- guardrails;
- confound handling;
- stakeholder communication;
- identity/dedupe;
- system boundary.

Coverage dimensions can be:

- voluntary;
- recovered;
- missed;
- partial/surface.

If a depth-eligible coverage answer is partial, the system may ask one earned depth probe.

## Second Anchor

Second anchor exists to prevent the whole interview from living on one claim.

It should:

- test another role-relevant focus or sub-focus;
- avoid off-role promotion;
- avoid holding patterns;
- use semantic surface rotation.

The runtime now treats second anchor as:

```text
focus_key + sub_focus_key / surface_kind
```

not just a parent focus label.

If a second-anchor surface has already been used, the orchestrator retires it and tries another surface, reserve map material, or close.

## Final Report Philosophy

Report V2 is evidence-first.

It should separate:

- what the candidate showed;
- what the resume claimed;
- what was tested;
- what was not tested;
- where the candidate was honest;
- where claims were contradicted;
- where the interviewer quality limits confidence.

The report uses multiple lenses:

- claim integrity;
- role technical fit;
- reasoning and communication;
- human calibration;
- transferable strengths;
- coverage and interviewer quality.

The report should not mathematically average lenses. It should synthesize contextually.

## Testing Philosophy

Testing should be staged:

1. No-credit deterministic contracts.
2. Saved-map replay.
3. Map-only paid run.
4. One full paid gate.
5. Small batch.
6. Full silverline suite.

Do not jump directly to broad paid simulation when scaffolding is unstable.

Important tests:

- parser contracts;
- map contracts;
- map validation;
- agenda contracts;
- ripper contracts;
- policy checker;
- question quality;
- final report contracts;
- scaffolding audit;
- saved-map replay;
- robust full simulation suite.

## Current Known Cleanup

As of 2026-06-03:

- Launch-ready V3 startup is paid-confirmed on `marketplace_growth`.
- Terminal graceful-close messages still travel through question-packet scoring, so they can be flagged as "not question-like".
- `legacy_agenda_backup` still exists as a route label and should be retired or renamed carefully.
- Full async hydration needs more confirmation across `best_product` and `strong_ai`.
- Policy warnings should be reviewed after each paid run, not ignored.

## How To Read A Simulation Artifact

Important fields:

- `quality_gate`: whether the harness accepted the run.
- `map_policy_trace`: model and policy settings.
- `map_validation`: launch readiness and focus reports.
- `map_quality_review`: compact critic result.
- `turns`: flat transcript table.
- `route_repetition`: focus/surface/route/phase sequence.
- `assessment_coverage`: coverage and breadth math.
- `application_transfer_arc`: transfer state.
- `policy_checker_events`: per-turn policy warnings.
- `question_quality`: best/worst question summaries.
- `final_evaluation`: Report V2 style result.

Do not rely only on `turns[]` for focus metadata. In some harness exports, `turns[]` has served question text but incomplete focus labels; richer focus/surface data lives in `route_repetition`, `assessment_coverage`, trace events, and policy events.

