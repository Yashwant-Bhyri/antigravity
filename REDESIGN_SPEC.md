# Antigravity — Product Redesign Specification
**Version**: 2.0
**Status**: Design-locked, pending implementation
**Authors**: Yash + Claude Code + Codex (boardroom synthesis)
**Date**: 2026-05-06

> This document is the product's constitution going forward. Every agent prompt, every routing decision, every scoring rubric, every report section should be written against it. Supersedes all prior PRDs, notes.md Parts 1–5, and any COLLAB.md framing that contradicts it.

---

## Table of Contents

1. [The North Star — What This Product Actually Is](#1-the-north-star)
2. [The Five Locked Ideology Decisions](#2-the-five-locked-ideology-decisions)
3. [The Canonical Interview Arc](#3-the-canonical-interview-arc)
4. [Layer 1 — The Missing Fast-Path Classifier](#4-layer-1--the-missing-fast-path-classifier)
5. [Layer 2 — Interview Structure Redesign](#5-layer-2--interview-structure-redesign)
6. [Layer 3 — Question Quality Overhaul](#6-layer-3--question-quality-overhaul)
7. [Layer 4 — Detection Layer Upgrades](#7-layer-4--detection-layer-upgrades)
8. [Layer 5 — Scoring Redesign](#8-layer-5--scoring-redesign)
9. [Layer 6 — Report Redesign](#9-layer-6--report-redesign)
10. [Layer 7 — Candidate Experience](#10-layer-7--candidate-experience)
11. [Layer 8 — Engineering Architecture Fixes](#11-layer-8--engineering-architecture-fixes)
12. [Immediate Launch Fixes (Pre-v2)](#12-immediate-launch-fixes-pre-v2)
13. [Data Flywheel — The Long-Term Moat](#13-data-flywheel--the-long-term-moat)
14. [Phased Implementation Roadmap](#14-phased-implementation-roadmap)

---

## 1. The North Star

### What the product is NOT

It is not an "adversarial interview engine." It is not a trap-setter. It is not a stress-test machine. It does not optimize to defeat the candidate.

The current codebase already knows this. `WeaknessAgent` downgrades severity when the candidate admits a gap. `ReasoningBehaviorAgent` classifies `admitted_gap` as intellectual honesty, not evasion. `EvaluationAgent` separates claim-credibility risk from overall engineering judgment and explicitly marks untested dimensions as `inconclusive`, not `low`. The tests (`story_depth`, `honest_boundary`, `conflict_pressure`, `topic_switch_minimalism`) encode a product that respects honesty, avoids tunneling, and pivots gracefully. The code is ahead of the language used to describe it.

### What the product IS

**A boundary-mapping engine that converts claimed experience into defended, mechanistic evidence.**

The resume is a hypothesis graph, not a truth source. The interview is the measurement instrument. Every agent, every routing decision, every question exists to answer one question:

> *"Where exactly does this candidate's knowledge actually live, at what depth, across which domains, and how does that map onto what this role requires?"*

Adversarial technique — mechanism forcing, contradiction surfacing, confidence stress-testing — is the measurement instrument. It is never the goal.

### ProvenHire's product promise, precisely stated

**"We convert resume claims into defended evidence. Here is exactly what this candidate knows, where their knowledge ends, and how that maps to your role."**

Not: "We ran them through a brutal interview and they passed."
Not: "We stress-tested them."

Evidence. Boundaries. Calibration. That is what the hiring manager actually needs and what ProvenHire can actually deliver.

### The internal language change

All agent prompts, all route labels, all internal comments should shift immediately:

| Old language | New language |
|---|---|
| "adversarial engine" | "boundary-mapping engine" |
| "attack strategy" | "probe direction" |
| "break the candidate" | "locate the knowledge boundary" |
| "interrogation" | "evidence-grounded interview" |
| "failure surface" | "knowledge boundary map" |
| "no validation" | "mechanism-first" |

This is not cosmetic. Internal language bleeds into prompt writing, persona calibration, and question tone. The code should say what the product means.

---

## 2. The Five Locked Ideology Decisions

These were identified in the boardroom as the decisions that have been open, implicit, or inconsistently applied. They are now locked.

### Decision 1: Intellectual honesty is a first-class positive signal

A candidate who accurately scopes their knowledge boundary is demonstrating a quality that matters more for hiring than the size of their knowledge. They score **better** than a candidate who bluffs past the same boundary.

**Concrete implications:**
- `ReasoningBehaviorAgent`: `admitted_gap` → `adaptability: "admitted_gap"` is already positive. Make this explicit in the scoring rubric.
- `WeaknessAgent`: admitted gap → downgrade to `medium` or `low` is already implemented. This should be reinforced, not softened.
- `EvaluationAgent`: Add `intellectual_integrity` as a named scoring dimension (see Layer 5). A candidate who said "I don't know" honestly at 3 boundary moments should score higher on this dimension than a candidate who bluffed the same 3 moments.
- Report: Surface `intellectual_integrity` explicitly. Hiring managers value this.

### Decision 2: The hire recommendation is a computed threshold, not an LLM judgment

The hire recommendation is what ProvenHire's reputation rests on. It cannot be a freeform LLM judgment. It must be a structured computation:

1. Score each tested dimension against the role's minimum threshold
2. Compute coverage (what fraction of the role's required dimensions were actually tested)
3. Apply the decision rule: `HIRE = X% of required dimensions above threshold AND confidence ≥ Y%`
4. LLM generates the **narrative** explaining the recommendation; the recommendation itself is computed

The LLM explains. It does not decide.

### Decision 3: Coverage modulates confidence explicitly and proportionally

A candidate who answered 12 questions across 4 domains has a fundamentally different evidence base than one who answered 4 questions narrowly. The confidence score must be a function of `n_dimensions_tested / n_dimensions_required_by_role`. Narrow sessions produce low-confidence reports even if all answers were strong.

This is already partially implemented in `EvaluationAgent` via the COVERAGE_NOTE. Make it a first-class computed field, not an LLM instruction.

### Decision 4: The canonical interview arc is fixed

The interview must move through this exact sequence. Deviation requires explicit signal justification (see Layer 2).

```
Story → Ownership → Mechanism → Constraint → Boundary → Recovery → Synthesis
```

This is product law. Sprint structure, persona shifts, question routing, all agent prompts must be aligned to this arc.

### Decision 5: The report has three views, one data layer

The report is the product. ProvenHire has three buyers with different needs. The same underlying session data must produce three distinct views:

- **Recruiter view**: Verdict + one sentence + key risk. Readable in 10 seconds.
- **Hiring manager view**: Evidence-anchored breakdown. Every score tied to a transcript moment. What to probe further in their own follow-up.
- **Calibration view** (deferred to v2.1): Candidate's score relative to role benchmark and prior pool distribution.

---

## 3. The Canonical Interview Arc

This is the locked interview arc. All sprint structure, persona shifts, and question routing derive from it.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1: STORY                                                          │
│  "Tell me about a project you're proud of."                             │
│  Goal: Establish what the candidate claims. Map the terrain.            │
│  Persona: curious_lead                                                  │
│  Gate to next: "I have sufficient terrain mapped."                      │
├─────────────────────────────────────────────────────────────────────────┤
│  STEP 2: OWNERSHIP                                                      │
│  "What part was actually yours?"                                        │
│  Goal: Separate what they built from what they observed.                │
│  Persona: curious_lead                                                  │
│  Gate to next: "I have high-confidence ownership signal."               │
│  Special case: Total admission → pivot to INHERITED CODEBASE arc        │
├─────────────────────────────────────────────────────────────────────────┤
│  STEP 3: MECHANISM                                                      │
│  "How did it actually work — at the component level?"                   │
│  Goal: Force mechanism over concept. Test if they own the internals.    │
│  Persona: curious_lead → socratic_mentor                                │
│  Gate to next: "I can locate their conceptual depth on this domain."    │
├─────────────────────────────────────────────────────────────────────────┤
│  STEP 4: CONSTRAINT                                                     │
│  "What broke, what traded off, what were the real limitations?"         │
│  Goal: Test production awareness and honest scoping.                    │
│  Persona: socratic_mentor                                               │
│  Gate to next: "I understand their constraint reasoning."               │
├─────────────────────────────────────────────────────────────────────────┤
│  STEP 5: BOUNDARY                                                       │
│  "Where does your understanding stop?"                                  │
│  Goal: Locate the exact knowledge edge. Not punitive — diagnostic.      │
│  Persona: socratic_mentor → senior_peer                                 │
│  Gate to next: "Boundary located."                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  STEP 6: RECOVERY                                                       │
│  "Given you hit the boundary — what do you do from here?"               │
│  Goal: Measure intellectual integrity. Reason forward? Bluff? Scope?   │
│  Persona: senior_peer                                                   │
│  Note: THIS IS THE MOST DIFFERENTIATING SIGNAL IN THE INTERVIEW.        │
├─────────────────────────────────────────────────────────────────────────┤
│  STEP 7: SYNTHESIS                                                      │
│  "Given everything — how would you approach X from scratch?"            │
│  Goal: Can they integrate owned knowledge + admitted gaps coherently?   │
│  Persona: senior_peer                                                   │
│  This is where 7s separate from 9s.                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Sprint Mapping to Arc

| Sprint | Steps | Focus | Persona |
|---|---|---|---|
| Sprint 1 — Project Defense | Story → Ownership | Did you actually build this? | curious_lead |
| Sprint 2 — Mechanism Depth | Mechanism → Constraint | Do you understand why it works? Interviewer picks the concept. | socratic_mentor |
| Sprint 3 — Systems Reasoning | Boundary → Recovery → Synthesis | Can you reason about failure and integrate what you know? | senior_peer |

### Sprint Progression Gate (CRITICAL CHANGE)

**Current**: Auto-advance after 5 questions OR high weakness threshold.
**Redesigned**: Signal-gated progression.

```python
SPRINT_ADVANCE_GATE = {
    1 → 2: ownership_signal_confidence >= 0.7  # High confidence on what they built vs claimed
    2 → 3: mechanism_depth_located = True       # Conceptual boundary found on at least 1 domain
}
```

If Sprint 1 reveals the candidate inflated ownership entirely (total admission), Sprint 2 must re-anchor. The premise of Sprint 2 (probe the concepts behind their claimed work) is invalid if Sprint 1 collapsed. Trigger the **Inherited Codebase arc** instead:

```
Total Admission Arc:
"Okay — you inherited it / used it / didn't write this. Walk me through what broke
first. What did you not understand when you first touched it? What would you
redesign if starting fresh?"
```

This tests debugging depth, system comprehension, and intellectual honesty — equally valuable signal.

---

## 4. Layer 1 — The Missing Fast-Path Classifier

### The Gap

The classify step in the `constraint → classify → probe → escalate` chain is missing as a first-class signal. Currently, response classification is emergent inside `WeaknessAgent`'s background LLM reasoning. This means:
- It's a background operation (one turn of lag)
- It's implicit (you get `attack_strategy` but not the classification itself)
- It doesn't gate the fast-path question selection

### The Fix

Add a fast Haiku call (~50ms) that runs **in the fast path** before `FollowUpAgent` picks the next question.

```python
# New: backend/agents/response_classifier.py

PROMPT = """Classify this interview answer along four axes. Return JSON only.

{
  "depth_level": "surface | conceptual | mechanistic | specific_artifact",
  "confidence": "underconfident | calibrated | overconfident",
  "honesty_signal": "genuine | performing | deflecting | admitted_gap",
  "consistency": "consistent | contradicts_prior | contradicts_resume | internal_contradiction"
}

Definitions:
- surface: named the technology, cannot explain how it works
- conceptual: explained the what/why, misses the mechanism
- mechanistic: explained the mechanism, weak on failure/edge cases
- specific_artifact: named specific components, errors, tradeoffs, production details
- admitted_gap: explicitly acknowledged limit of knowledge or corrected prior claim
- internal_contradiction: statement contradicts something else said in THIS answer
"""
```

### The Dispatch Table

The classifier output becomes the explicit routing signal in `handle_transcript()`:

```python
RESPONSE_DISPATCH = {
    ("surface", "overconfident"):        "mechanism_probe",     # "Walk me through exactly how X works"
    ("surface", "calibrated"):           "mechanism_probe",     # Gentle push to mechanism
    ("conceptual", "calibrated"):        "failure_probe",       # "When does that break?"
    ("mechanistic", "calibrated"):       "boundary_test",       # Adjacent domain or edge case
    ("specific_artifact", any):          "depth_or_advance",    # Strong answer → go deeper or advance
    (any, "contradicts_prior"):          "contradiction_trap",  # "In turn 3 you said X…"
    (any, "contradicts_resume"):         "discrepancy_challenge", # DiscrepancyAgent escalation
    (any, "deflecting"):                 "ownership_anchor",    # "Specifically, what did YOU build?"
    (any, "admitted_gap"):               "pivot",               # Do NOT keep drilling. Pivot.
    ("conceptual", "overconfident"):     "stress_test",         # Challenge the confidence
}
```

This makes the system's routing deterministic and debuggable. Right now the routing is emergent — you can't predict which path it takes or explain why after the fact.

**File**: Create `backend/agents/response_classifier.py`. Wire into `backend/services/orchestrator.py:handle_transcript()` before `FollowUpAgent` selection.

---

## 5. Layer 2 — Interview Structure Redesign

### Change 1: Sprint 2 — Interviewer Picks the Concept

**Current**: "Pick one idea at the core of what you've built — how did it work?"
**Problem**: Candidate picks their best-prepared topic. Defeats the purpose.
**Fix**: Sprint 2 opener takes a concept that **emerged organically from Sprint 1** and probes it from first principles. The system picks — not the candidate.

```python
# In generate_sprint_opener() for sprint 2:
# 1. Read the last 5 turns of Sprint 1
# 2. Extract the most technically specific concept the candidate mentioned
#    (a technology, a system component, an algorithm they named)
# 3. Anchor Sprint 2 on THAT concept
# Example output: "You mentioned using a write-through cache in the sync layer.
#                  Let's go deeper — explain exactly how cache invalidation works
#                  in that design from first principles."
```

### Change 2: Total Confession Pivot (LATER_EDITS → NOW)

This is no longer deferred. It is a philosophical gap.

**Trigger conditions** (either):
- `admitted_gap` on 2+ consecutive turns
- Explicit fabrication admission detected in transcript ("I just used tools", "I don't actually know this", "I didn't write this")

**Response**: Set `full_confession = True` in session state. Switch all subsequent questions to:
- What broke on your watch with this system?
- What did you not understand when you first touched it?
- What would you change if starting from scratch?
- How do you approach learning something you're given but don't understand?

This tests equally valuable signals: debugging ability, intellectual honesty, learning speed. Never punish a confession by continuing to hammer technical claims the candidate just admitted don't hold.

**File**: `backend/services/orchestrator.py:handle_transcript()` — detect `full_confession` signal and route accordingly. `backend/agents/weakness_agent.py` — pass `full_confession` flag, shift attack strategy to `conceptual`/`product` framing.

### Change 3: The Synthesis Question (New)

At Sprint 3 close, before ending: one synthesis question.

```
"Given everything you've shared — what you know well, where you had gaps,
 what you'd do differently — how would you approach building [role-relevant system]
 from scratch today?"
```

This tests whether the candidate can integrate owned knowledge + admitted gaps into a coherent position. It is the highest signal question in the entire interview. A candidate who says "I'd be confident on A and B, I'd bring in help for C" is more hireable than someone who claims to own everything.

**File**: `backend/services/orchestrator.py:_maybe_advance_sprint()` — add synthesis question generation at sprint 3 close. `backend/agents/followup_agent.py` — add `generate_synthesis_question()` method.

---

## 6. Layer 3 — Question Quality Overhaul

### Change 1: Attack Strategy → Enforced Question Templates

`WeaknessAgent` detects `attack_strategy: "contradiction"` but `FollowUpAgent` interprets this with too much latitude. Each strategy should map to an explicit question template that the agent fills in — not vibes passed as context.

```python
ATTACK_STRATEGY_TEMPLATES = {
    "contradiction": "Earlier you said {claim_a}. But {claim_b} implies that couldn't work. Which is actually true, and what am I missing?",
    "implementation_probe": "Walk me through exactly how {component} works — step by step, at the code level.",
    "ownership_probe": "When you say you built {artifact}, what specifically did you write? What was already there?",
    "edge_case": "What happens to {system} when {failure_condition}? Walk me through it.",
    "scaling": "That design works at {current_scale}. At {10x_scale}, what's the first thing that breaks?",
    "step_by_step": "Take me through your reasoning from the beginning. What's the first step?",
    "clarification": "When you say {vague_term}, what specifically do you mean? Give me a concrete example.",
}
```

These are templates with slots — the LLM fills in the slots from context, not the full question. This ensures question *structure* matches strategy while allowing content to be grounded in the candidate's actual answer.

**File**: `backend/agents/followup_agent.py` — add `ATTACK_STRATEGY_TEMPLATES`, modify `generate()` to use template-filling rather than freeform generation.

### Change 2: Trajectory Replan at High-Signal Moments

Questions are currently adapted one at a time, reactively. At key moments (sprint transition, total admission, very strong answer, very weak answer), the system should run a **trajectory replan** — generate the next 2-3 questions as a branch rather than the next 1 question reactively.

**Trigger conditions for replan**:
- Sprint transition
- `depth_level: specific_artifact` (strong answer → advance or go deeper, plan 2 questions)
- `full_confession` detected
- `contradicts_resume` confirmed (follow-up is multi-turn, needs pre-planned branch)

**Cost**: One Sonnet call at these moments. Not every turn — only high-signal pivot points.

**File**: `backend/services/orchestrator.py` — add `_trigger_trajectory_replan()` called at the above conditions. `backend/agents/followup_agent.py` — add `generate_question_branch(n=3)` method.

### Change 3: Pre-Interview Question Quality Audit

The interview map is built, structurally validated, and then used. There is no semantic quality check. Add a quality pass after map generation:

```python
QUALITY_CRITERIA = [
    "opener contains a specific artifact from the resume (not a generic 'tell me about a project')",
    "dimension questions escalate in depth: surface → mechanism → boundary",
    "recovery questions are specific to the failure mode (not generic 'what would you do differently')",
    "no dimension question is answerable with a Wikipedia-level response",
]
```

Questions that fail quality criteria are regenerated before the session starts. This catches thin LLM output before it runs.

**File**: `backend/services/interview_map.py` — add `audit_map_quality()` post-validation pass.

---

## 7. Layer 4 — Detection Layer Upgrades

### Change 1: Within-Interview Consistency Checking

`DiscrepancyAgent` currently checks resume vs demonstrated knowledge. This misses the richer signal: **within-interview contradiction**.

```
Turn 3: "I designed the database schema from scratch."
Turn 7: "The backend was already built when I joined."
→ These directly contradict. The system should surface this.
```

**Implementation**: Add `InternalConsistencyAgent` or extend `DiscrepancyAgent` with a `check_internal()` method. Triggered when the candidate makes a strong ownership claim (not every turn — triggers on `ownership_probe` or `specific_artifact` depth level). Checks last 10 turns for contradictions with the current claim.

```python
# New output from extended DiscrepancyAgent:
{
  "conflict_type": "resume_vs_answer | internal | none",
  "conflict_level": "none | suspected | confirmed",
  "turn_a": 3,
  "claim_a": "...",
  "turn_b": 7,
  "claim_b": "...",
  "severity": "low | medium | high"
}
```

**File**: `backend/agents/discrepancy_agent.py` — add `check_internal(answer, history)` method. `backend/services/orchestrator.py:_run_background_pipeline()` — wire internal consistency check alongside existing discrepancy check.

### Change 2: ReasoningBehaviorAgent → Live Interview Feedback

`ReasoningBehaviorAgent` currently runs in the background and its output goes only to the final evaluation. This is a waste of the most real-time-useful signal in the system.

**The signal that needs to enter the live interview**:
- `confidence_calibration: overconfident` → next question should be a calibration stress test
- `adaptability: defensive` → next question should be less confrontational, more collaborative
- `clarification_behavior: asks_to_deflect` → candidate is stalling, anchor to specific artifact
- `adaptability: admitted_gap` → pivot, do not keep drilling

**Implementation**: After `_run_background_pipeline()`, write a `reasoning_signal` summary to session state. `handle_transcript()` reads this on the next turn (via `_apply_staged_analysis`) and passes it to `FollowUpAgent` as an explicit context modifier alongside weakness and discrepancy.

```python
# New field in staged analysis:
"reasoning_signal": {
    "tone_modifier": "soften | maintain | escalate",  # Based on adaptability
    "confidence_pressure": True | False,              # Based on confidence_calibration
    "stall_detected": True | False                    # Based on clarification behavior
}
```

**File**: `backend/services/orchestrator.py:_run_background_pipeline()` — add `reasoning_signal` computation. `backend/agents/followup_agent.py` — accept and apply `tone_modifier` and `confidence_pressure` in question generation.

### Change 3: WeaknessAgent "Revisit or Advance" Decision

`WeaknessAgent` detects and proposes. It does not make a strategic meta-decision about interview coverage. Add a field:

```python
{
  "weakness": "...",
  "type": "...",
  "severity": "...",
  "attack_strategy": "...",
  "continue_probing": True | False,  # NEW
  "continue_reason": "boundary not yet located | weakness is high severity and unresolved | ..."
}
```

`continue_probing: False` + "boundary located on this domain" → system should advance to a new domain. This prevents tunneling in a way that's explicit and debuggable rather than governed by the implicit overprobed-topic budget.

**File**: `backend/agents/weakness_agent.py` — add `continue_probing` + `continue_reason` to output schema and prompt.

---

## 8. Layer 5 — Scoring Redesign

### Change 1: Add `intellectual_integrity` as a First-Class Dimension

The current dimensions are `reasoning`, `technical_depth`, `communication`, `adaptability`. Add `intellectual_integrity`.

```python
"intellectual_integrity": {
    "description": "Did the candidate accurately scope their knowledge? Did they acknowledge gaps honestly? Did they recover with reasoning when they hit the boundary?",
    "observable_criteria": {
        "1-3": "Consistently bluffed past knowledge boundaries, overclaimed ownership, gave circular answers when challenged",
        "4-6": "Mixed — some accurate scoping, some inflation; corrected when explicitly pressed",
        "7-8": "Proactively acknowledged gaps, attempted to reason forward from incomplete knowledge",
        "9-10": "Consistently accurate self-assessment, strong recovery behavior — 'I don't know, but reasoning from X, I'd expect...'"
    }
}
```

This is the dimension that ProvenHire's buyers will find most differentiated from any other interview tool.

### Change 2: Rubric-Based Scoring with Evidence Anchoring

**Current**: 3 LLM calls on the same prompt, average the scores. This reduces variance but not bias.

**Redesigned**:
1. Score against explicit observable criteria (not "rate 0-10")
2. Require evidence: every score must be accompanied by a specific quote or paraphrase from the interview
3. Two-pass: Score pass → Evidence pass (verify the score is justified by the evidence)

```python
PER_ANSWER_RUBRIC = {
    "problem_framing": {
        "0": "Did not attempt to define the problem",
        "1": "Named the problem but didn't scope it",
        "2": "Clearly framed the problem before engaging with solution"
    },
    "logical_reasoning": {
        "0": "No discernible reasoning structure",
        "1": "Some structure but missing key steps",
        "2": "Clear structure, most steps present",
        "3": "Complete stepwise reasoning, handles edge cases"
    },
    # ...
}

# Evidence requirement — every scored answer must produce:
{
    "score": 7,
    "breakdown": { "problem_framing": 2, "logical_reasoning": 3, ... },
    "evidence": "Candidate said: '[exact quote]'. This demonstrated X because Y.",
    "confidence": 0.85
}
```

**File**: `backend/agents/evaluation_agent.py` — replace 3-pass prompt with rubric-based scoring + evidence requirement.

### Change 3: Hire Recommendation as Computed Threshold

```python
def compute_hire_recommendation(
    dimension_scores: dict,        # {"reasoning": 7.2, "technical_depth": 6.1, ...}
    coverage: float,               # 0.0–1.0: fraction of role dimensions tested
    confidence: float,             # 0.0–1.0: computed from coverage
    role_thresholds: dict,         # Per-role minimum dimension scores
) -> tuple[str, str]:
    """
    Returns (recommendation, narrative_prompt).
    Recommendation is computed. LLM only writes the narrative explanation.
    """
    tested_dimensions = {k: v for k, v in dimension_scores.items() if v != "inconclusive"}
    dimensions_above_threshold = sum(
        1 for dim, score in tested_dimensions.items()
        if isinstance(score, (int, float)) and score >= role_thresholds.get(dim, 6.0)
    )
    pct_above_threshold = dimensions_above_threshold / len(tested_dimensions) if tested_dimensions else 0

    if coverage < 0.4:
        return "INSUFFICIENT_DATA", "Coverage too narrow to make a reliable recommendation."
    if pct_above_threshold >= 0.75 and confidence >= 0.7:
        return "HIRE", "..."
    if pct_above_threshold >= 0.5 and confidence >= 0.5:
        return "MAYBE", "..."
    return "NO HIRE", "..."
```

**File**: `backend/agents/evaluation_agent.py` — add `compute_hire_recommendation()` as a pure function. LLM call produces narrative only after recommendation is computed.

### Change 4: Coverage → Confidence Computation

```python
def compute_confidence(
    n_questions_asked: int,
    n_dimensions_tested: int,
    n_dimensions_required: int,
    question_quality_scores: list[float],  # Per-question quality (map-backed vs fallback)
) -> float:
    coverage_ratio = n_dimensions_tested / max(n_dimensions_required, 1)
    question_quality = sum(question_quality_scores) / max(len(question_quality_scores), 1)
    base_confidence = coverage_ratio * question_quality
    # Clamp to 0.3–0.95 (never fully confident or fully inconclusive)
    return max(0.3, min(0.95, base_confidence))
```

**File**: `backend/agents/evaluation_agent.py` — replace LLM-estimated `confidence_score` with this computation.

---

## 9. Layer 6 — Report Redesign

### Three Views, One Data Layer

The same session data produces three views depending on who's reading:

#### Recruiter View (default, 10-second read)
```
┌──────────────────────────────────────────────────────┐
│  Jane Smith — Senior Backend Engineer                │
│  Interviewed 2026-05-06 · 28 min · 14 questions     │
│                                                      │
│  ● HIRE                        Score: 7.8 / 10      │
│                                Confidence: 74%       │
│                                                      │
│  Key signal: Demonstrated strong distributed systems │
│  reasoning. One claim (ML pipeline ownership) did    │
│  not hold under mechanism probing.                   │
│                                                      │
│  → View hiring manager report                        │
└──────────────────────────────────────────────────────┘
```

#### Hiring Manager View (evidence-anchored, full breakdown)
Every score anchored to a transcript moment:

```
Technical Depth: 7.1 / 10
  Evidence: "When asked about cache invalidation under concurrent writes,
  candidate explained the write-invalidate protocol and correctly identified
  the thundering herd problem. Did not address clock skew in distributed
  invalidation — this was left as a gap."

Intellectual Integrity: 8.5 / 10
  Evidence: "At turn 9, when pressed on ML pipeline ownership, candidate
  said: 'Honestly, I used the existing training loop — my contribution was
  the feature engineering pipeline.' This is the correct honest scoping of
  their actual contribution."

What to probe further in your own interview:
  - Clock skew in distributed cache invalidation
  - ML training loop understanding (explicitly admitted gap)
  - System design under Byzantine fault conditions (not tested — insufficient time)
```

#### Calibration View (v2.1, post-data flywheel)
```
Score: 7.8 — Top 31% of senior backend candidates (n=1,247)
Technical Depth: 7.1 — Above median for this role band
Intellectual Integrity: 8.5 — Top 15% of all candidates
```

### Evidence Anchoring — Implementation

Every dimension score in the report must be accompanied by:
1. The specific question that tested it
2. The candidate's relevant quote or paraphrase
3. What the evidence demonstrates (positive) and what it misses (gap)

This requires `EvaluationAgent` to produce structured evidence objects, not just scores. (See Layer 5 Change 2.)

### Report Language Update

Change "Failure boundary analysis" → "Interview Assessment Report"
Change "Failure Surface" → "Knowledge Boundary Map"
Change "Detected Weaknesses" → "Probing Points" (or "Areas Tested")

The report is read by hiring managers and sometimes by candidates in post-interview feedback. The language should reflect what the product actually does.

---

## 10. Layer 7 — Candidate Experience

### Change 1: Warm-Up Phase (90 seconds, unscored)

Most candidates spend the first 2 minutes of an AI interview calibrating: How formal is this? What level of detail does it want? Does it know my domain? This calibration time corrupts the measurement of the actual first 2 minutes.

**Implementation**: Add a 90-second warm-up before Sprint 1. Unchallengeable, not scored, not included in weakness detection.

```
Warm-up question: "Before we get into the main interview, just to calibrate —
what kind of work have you been doing most recently? A sentence or two is fine."
```

The warm-up response is used only to: (a) calibrate the candidate's communication baseline for `ReasoningBehaviorAgent`, and (b) confirm the session is working technically (audio, latency, Deepgram). Not scored.

**File**: `backend/services/orchestrator.py:start_prepared_session()` — add warm-up question as turn 0, flagged `is_warmup: True`. `backend/services/orchestrator.py:_run_background_pipeline()` — skip warm-up turn in scoring and analysis.

### Change 2: Context-Aware Fillers

Current fillers: "Got it", "Interesting", "I see" — completely context-free.

These should reference something specific from what was just said:

```python
CONTEXT_AWARE_FILLER_TEMPLATES = [
    "Interesting — the {entity} part is what I want to dig into.",
    "Got it — so the core of this was {brief_summary}.",
    "Okay — and that's where things get specific.",
    "Right — let me think about that for a second.",
]
```

The `{entity}` and `{brief_summary}` slots are filled from the partial transcript entities accumulated during the candidate's answer. This deepens the conversational feel significantly.

**File**: `backend/services/tts_service.py` — add context-aware filler generation. `backend/services/orchestrator.py:handle_transcript()` — pass last-entity context to filler selection.

### Change 3: Thinking Silence Detection (HandoverManager)

The current system treats all silence ≥ threshold as turn end. But candidates who think before they speak produce "thinking silence" — genuine cognitive processing, not turn yield. Rushing them produces incomplete answers and degrades measurement.

**Signal for thinking silence**:
- Last partial transcript ends with a filler word ("um", "uh", "like", "so")
- Partial word count is below the candidate's baseline average
- Silence duration is < 4s (true turn ends are usually longer)

**Implementation**:
```python
def is_thinking_silence(
    last_partial: str,
    silence_duration_ms: int,
    candidate_baseline_words: int,
    current_word_count: int
) -> bool:
    filler_words = {"um", "uh", "like", "so", "well", "just", "and"}
    last_word = last_partial.strip().split()[-1].lower() if last_partial.strip() else ""
    if last_word in filler_words and silence_duration_ms < 4000:
        return True
    if current_word_count < (candidate_baseline_words * 0.4) and silence_duration_ms < 3000:
        return True
    return False
```

If `is_thinking_silence()` returns `True`, extend the commit delay by 2s and do not fire TTS filler.

**File**: New `HandoverManager` class in `lib/audio.ts`. Integrate into `UtteranceEnd` handling.

---

## 11. Layer 8 — Engineering Architecture Fixes

### Fix 1: Dynamic Interview Map

**Current**: Map is built at session start and consumed as the interview proceeds. Sprint 2 and Sprint 3 branches are pre-built before Sprint 1 runs.

**Problem**: Sprint 1 discovers things (strongest domain, ownership signals, specific technologies mentioned) that should anchor Sprint 2. The current map ignores Sprint 1 discoveries for Sprint 2 generation.

**Fix**: At Sprint 1 → Sprint 2 transition, run a **map update pass**:

```python
async def update_map_for_sprint(
    session_id: str,
    current_sprint: int,
    sprint_discoveries: dict  # What Sprint 1 found: strongest domain, key technologies, ownership signals
) -> None:
    """Regenerate sprint_2 and sprint_3 branches based on Sprint 1 discoveries."""
    # This runs as asyncio.create_task at sprint transition
    # Writes to prepped_sprint_2_branches, prepped_sprint_3_branches in session state
    # Sprint 2 opener now anchors on the specific concept that emerged from Sprint 1
```

**File**: `backend/services/interview_map.py` — add `update_map_for_sprint()`. `backend/services/orchestrator.py:_maybe_advance_sprint()` — trigger update pass as background task at transition.

### Fix 2: Per-Answer Scores → Live Interview Feedback

Per-answer scores from `EvaluationAgent.score_answer()` currently feed only the final report. They should also influence the live interview.

```python
# If per-answer scores show consistent high performance (3 consecutive answers ≥ 7.5):
→ Advance sprint faster (reduce sprint question budget by 1)
→ Raise question difficulty tier in next selection

# If per-answer scores show consistent low performance (3 consecutive answers ≤ 4.0):
→ Attempt a rescue question (different angle, lower complexity threshold)
→ Set confidence_note: "narrow evidence" even if boundary not explicitly located
```

**File**: `backend/services/orchestrator.py:handle_transcript()` — read `per_answer_scores` rolling average and use in sprint progression decision.

### Fix 3: Graceful Degradation Quality Indicators

Every question served should carry a quality tier:

```python
QUESTION_QUALITY_TIERS = {
    "map_llm_attack":    1.0,  # Map-backed, LLM-authored attack probe
    "map_llm_sprint":    0.9,  # Map-backed, LLM-authored sprint question
    "map_deterministic": 0.7,  # Map-backed, deterministic template
    "speculative":       0.6,  # Speculative from partial STT
    "bank_adapted":      0.6,  # Bank question adapted to answer
    "sprint_fallback":   0.3,  # Generic sprint fallback template
}
```

This quality score is stored per-turn in history and fed into `compute_confidence()`. A session with many fallback questions gets a lower confidence score in the report — and the report says so explicitly.

**File**: `backend/services/orchestrator.py:handle_transcript()` — tag `route_quality` on every served turn. Feed into `compute_confidence()`.

### Fix 4: Ranked Speculative Queue

**Current**: Single best-candidate speculative question with `keep/replace` decisions.

**Fix**: Maintain a ranked queue of 3-5 speculative questions with their generation context. At commit time, the fast path picks the most contextually appropriate one rather than just the most recently computed one.

```python
speculative_queue: list[{
    "question": str,
    "generated_at": float,
    "trigger": "new_entity | admission | rolling_length",
    "entity_context": list[str],
    "relevance_score": float,
}]
```

**File**: `backend/services/orchestrator.py` — replace `speculative_cache` single-slot with `speculative_queue` ranked list.

### Fix 5: Admin Endpoint Security (CRITICAL for production)

`/admin/redis-dump` is completely unauthenticated and dumps raw session data including full resumes and interview reports. This must be fixed before any real traffic hits the system.

```python
# Minimum viable fix:
ADMIN_SECRET = os.environ.get("ANTIGRAVITY_ADMIN_SECRET")

@router.get("/admin/redis-dump")
async def redis_dump(x_admin_secret: str = Header(None)):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    # ... rest of endpoint
```

**File**: `backend/api/routes.py` — add header auth check. Add `ANTIGRAVITY_ADMIN_SECRET` to `render.yaml` env vars.

---

## 12. Immediate Launch Fixes (Pre-v2)

These are blocking issues for a working launch. Fix these before implementing anything in Layers 1–8.

### Fix A: Dashboard Data Mapping Bug (30 min)

`/sessions` endpoint returns raw Postgres rows. `full_report` JSONB is not unpacked. Dashboard expects top-level fields (`failure_surface`, `raw_weaknesses`, `total_questions`, `scores`). Fix in `routes.py:get_sessions()`:

```python
@router.get("/sessions")
async def get_sessions():
    rows = await list_sessions()
    result = []
    for r in rows:
        if hasattr(r.get("created_at"), "isoformat"):
            r["created_at"] = r["created_at"].isoformat()
        full = r.pop("full_report", None) or {}
        if isinstance(full, str):
            import json
            full = json.loads(full)
        r.update({
            "failure_surface": full.get("failure_surface", {}),
            "raw_weaknesses": full.get("raw_weaknesses", []),
            "total_questions": full.get("total_questions", 0),
            "scores": full.get("scores", {}),
            "hire_recommendation": full.get("hire_recommendation") or r.get("hire_recommendation"),
            "summary": full.get("summary", ""),
            "target_role": full.get("target_role", ""),
            "confidence_score": full.get("confidence_score"),
        })
        result.append(r)
    return result
```

### Fix B: Candidate Identity (2–3 hrs)

Add `candidate_name` and `candidate_email` fields throughout:
1. `app/page.tsx` intake form — add name + email input fields
2. `StartInterviewRequest` pydantic model — add `candidate_name: str = ""`, `candidate_email: str = ""`
3. Orchestrator `start_session()` — store in session state
4. `full_report` dict in `end_session()` — include `candidate_name`, `candidate_email`
5. `backend/db/postgres.py` — `ALTER TABLE sessions ADD COLUMN IF NOT EXISTS candidate_name TEXT`
6. `backend/db/postgres.py:persist_session()` — include `candidate_name` in upsert
7. `app/report/[session_id]/page.tsx` — display candidate name in report header
8. `app/dashboard/page.tsx` — display candidate name in session table row

### Fix C: Admin Endpoint Auth (20 min)

See Layer 8 Fix 5 above. Must be done before any real interview data flows.

### Fix D: FAISS Model Reload Bug (15 min)

```python
# backend/rag/faiss_store.py — current (broken):
def _get_model():
    return SentenceTransformer("all-MiniLM-L6-v2")

# Fix:
_model = None
def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model
```

### Fix E: Weakness Summary Rendering (20 min)

`weakness_summary` is computed in the `/report/{session_id}` endpoint and in the `full_report` dict but never rendered in `app/report/[session_id]/page.tsx`. Add a "Weakness Pattern" section to the report JSX showing the count-by-type breakdown.

---

## 13. Data Flywheel — The Long-Term Moat

The product gets smarter with every session or it stays static. This is the architectural decision that determines whether Antigravity builds a moat or stays a commodity.

### What to collect

Every session is labeled training data. The value chain:

```
Session runs
  → Scores computed, recommendation made
  → ProvenHire tracks hire outcome (6-month performance review from employer)
  → Outcome label attached to session
  → Questions that produced high-signal answers labeled as high-quality
  → Benchmark distribution updated
  → Scoring rubrics calibrated against outcome labels
  → Question bank refined with high-quality, high-yield questions
```

### Implementation phases

**Phase 1 (collect)**: Add `outcome_label` field to sessions table. ProvenHire posts `POST /api/feedback/{session_id}` with `{ hired: bool, 6_month_rating: int }` after hire outcome is known. Store in Postgres.

**Phase 2 (analyze)**: Build offline pipeline to correlate dimension scores → hire outcomes. Identify which dimension scores are most predictive.

**Phase 3 (calibrate)**: Update scoring rubrics to weight most-predictive dimensions higher. Tune hire recommendation thresholds against empirical outcome data.

**Phase 4 (benchmark)**: Build benchmark distributions per role type + experience band. Report shows "top X% of candidates for this role" rather than raw scores.

**Phase 5 (fine-tune)**: Fine-tune WeaknessAgent and FollowUpAgent on high-signal sessions. The questions that consistently produced the clearest boundary signal become the training set.

### Schema addition (Phase 1)

```sql
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS outcome_hired BOOLEAN;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS outcome_rating INTEGER;  -- 1-5, 6-month review
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS outcome_reported_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS outcome_notes TEXT;
```

---

## 14. Phased Implementation Roadmap

### Phase 0 — Launch Fixes (This week, 1–3 days)

| Item | File | Time |
|---|---|---|
| Dashboard data mapping bug | `backend/api/routes.py` | 30 min |
| Candidate identity (name/email) | multiple | 3 hrs |
| Admin endpoint auth | `backend/api/routes.py` | 20 min |
| FAISS model caching fix | `backend/rag/faiss_store.py` | 15 min |
| Weakness summary rendering | `app/report/[session_id]/page.tsx` | 20 min |
| Report language update (title, section names) | `app/report/[session_id]/page.tsx` | 30 min |

**Exit criteria**: Dashboard shows real data with candidate names. Reports are readable and correctly titled. No unauthenticated admin access.

---

### Phase 1 — Core Philosophy Alignment (1–2 weeks)

| Item | Layer | Time |
|---|---|---|
| Response classifier (fast-path, Haiku) | Layer 1 | 1 day |
| Dispatch table replacing implicit routing | Layer 1 | 0.5 day |
| Total confession pivot logic | Layer 2 | 1 day |
| WeaknessAgent "continue_probing" field | Layer 4 | 0.5 day |
| Attack strategy → enforced templates | Layer 3 | 1 day |
| Internal language change (all prompts) | All agents | 1 day |
| `intellectual_integrity` scoring dimension | Layer 5 | 0.5 day |

**Exit criteria**: Interview routing is explicit and deterministic. Confession is handled gracefully. Questions follow structure templates. Scoring includes intellectual integrity.

---

### Phase 2 — Scoring & Report Redesign (2–3 weeks)

| Item | Layer | Time |
|---|---|---|
| Rubric-based scoring + evidence anchoring | Layer 5 | 2 days |
| `compute_hire_recommendation()` threshold function | Layer 5 | 1 day |
| `compute_confidence()` from coverage | Layer 5 | 0.5 day |
| Three-view report architecture | Layer 6 | 2 days |
| Evidence-anchored report sections | Layer 6 | 2 days |
| Question quality tier tracking | Layer 8 | 1 day |

**Exit criteria**: Every score has evidence. Hire recommendation is computed, not generated. Report serves recruiter and hiring manager distinctly.

---

### Phase 3 — Interview Intelligence Upgrades (3–4 weeks)

| Item | Layer | Time |
|---|---|---|
| Sprint 2 — interviewer picks concept | Layer 2 | 1 day |
| Synthesis question at Sprint 3 close | Layer 2 | 0.5 day |
| Sprint progression — signal-gated | Layer 2 | 1 day |
| ReasoningBehaviorAgent → live interview signal | Layer 4 | 1.5 days |
| Internal consistency checking | Layer 4 | 1.5 days |
| Trajectory replan at high-signal moments | Layer 3 | 2 days |
| Dynamic interview map (post-Sprint 1 update) | Layer 8 | 2 days |
| Per-answer scores → live interview feedback | Layer 8 | 1 day |

**Exit criteria**: Interview adapts in real-time to reasoning behavior. Sprint transitions are intelligent. Questions branch rather than just chain.

---

### Phase 4 — Experience & Architecture Polish (4–6 weeks)

| Item | Layer | Time |
|---|---|---|
| Warm-up phase (90s unscored) | Layer 7 | 1 day |
| Context-aware fillers | Layer 7 | 1 day |
| HandoverManager (thinking silence detection) | Layer 7 | 2 days |
| Ranked speculative queue | Layer 8 | 1 day |
| Pre-interview question quality audit | Layer 3 | 1 day |
| Graceful degradation quality indicators | Layer 8 | 1 day |

**Exit criteria**: Interview experience feels natural, not robotic. Candidate experience optimizes for measurement quality.

---

### Phase 5 — Data Flywheel (Ongoing, starts after first 50 sessions)

| Item | Time |
|---|---|
| Outcome label collection schema + ProvenHire feedback endpoint | 1 day |
| Benchmark distribution computation | 1 week |
| Calibration report view | 1 week |
| Question quality scoring pipeline | 2 weeks |
| Scoring rubric calibration against outcomes | 1 month |
| Fine-tuning pipeline (v3 roadmap) | 3 months |

---

## Appendix A — Files Changed Summary

| File | Changes |
|---|---|
| `backend/agents/response_classifier.py` | **NEW** — fast-path Haiku classifier |
| `backend/agents/weakness_agent.py` | Add `continue_probing`, `full_confession` handling, template enforcement |
| `backend/agents/followup_agent.py` | Add `generate_synthesis_question()`, `generate_question_branch()`, template-filling for attack strategies, tone_modifier support |
| `backend/agents/discrepancy_agent.py` | Add `check_internal()` for within-interview consistency |
| `backend/agents/evaluation_agent.py` | Rubric-based scoring, evidence anchoring, `intellectual_integrity` dimension, `compute_hire_recommendation()`, `compute_confidence()` |
| `backend/agents/reasoning_behavior_agent.py` | Add `reasoning_signal` summary output for live interview |
| `backend/services/orchestrator.py` | Wire classifier, confession pivot, synthesis question, signal-gated sprints, per-answer score feedback, quality tier tracking |
| `backend/services/interview_map.py` | Add `update_map_for_sprint()`, `audit_map_quality()` |
| `backend/api/routes.py` | Fix `/sessions` data mapping, admin auth |
| `backend/db/postgres.py` | Add `candidate_name`, `candidate_email`, outcome label columns |
| `backend/rag/faiss_store.py` | Fix `_get_model()` caching |
| `app/page.tsx` | Add candidate name/email fields |
| `app/report/[session_id]/page.tsx` | Three-view report, evidence anchoring, language update |
| `app/dashboard/page.tsx` | Candidate name column, proper hire_recommendation from stored field |
| `lib/audio.ts` | HandoverManager for thinking silence detection |

---

## Appendix B — What Does NOT Change

- Two-track architecture (fast path + slow background pipeline) — this is correct and production-worthy
- Seven-agent pipeline structure — agents, tiers, and parallel dispatch are right
- Interview map as startup-blocking control plane — this is the right gate
- ProvenHire handoff integration — fully built and correct
- Redis session state + Postgres persistence pattern — correct
- OpenRouter tier routing — correct
- Filler-first TTS latency masking — correct

The foundation is solid. What changes is the organizing intelligence sitting on top of it.

---

*End of specification. Implementation ownership to be assigned per phase in AGENTS.md.*
