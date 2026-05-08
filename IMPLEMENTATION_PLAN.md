# Antigravity — Full Implementation Plan

> Synthesized from: full codebase read (40+ files) · REDESIGN_SPEC.md · INTERVIEW_REDESIGN.md · two production session autopsies (e5170a7a, 98c80520)
> Date: 2026-05-06
> Status: Ready for implementation

---

## How to Use This Document

This is a surgical manual. Every change below maps to a confirmed failure in session data or a specific design decision — nothing is speculative. Changes are ordered by dependency: implement Layer 0 first, then proceed. Each section names the exact file, function, and line range. Where diffs are provided, they are the full target state — not pseudocode.

**What this document is not:** A feature wishlist. Every item here has a traced problem behind it. If an item feels optional, re-read the session autopsy in INTERVIEW_REDESIGN.md §1.

---

## Layer 0 — Philosophy Corrections (Do This First, It Changes All Prompts)

Before any code changes, the internal language of the system must shift. This is not cosmetic — LLM prompts embedded in agent code use the exact terminology below, and that language bleeds into the questions generated. "Attack strategy" produces different outputs from "probe direction."

### Terminology Audit

| Current Term | Replace With | Where |
|---|---|---|
| `attack_strategy` | `probe_direction` | `weakness_agent.py` output schema + all consumers |
| `attack_probe` | `depth_probe` | `orchestrator.py` route name + all logging |
| `failure_surface` | `knowledge_boundary_map` | report section + `evaluation_agent.py` output |
| `Detected Weaknesses` | `Probing Points` | `app/report/[session_id]/page.tsx` section title |
| `Failure boundary analysis` | `Interview Assessment Report` | report page title |
| `aggressive_probe` | `deep_probe` | `orchestrator.py` local variable |
| `WeaknessAgent` | Keep class name, but update ALL prompt strings from "detect weakness" → "identify knowledge boundary" | `weakness_agent.py` system prompt |
| `ATTACK_STRATEGY_INSTRUCTIONS` dict | `PROBE_DIRECTION_INSTRUCTIONS` | `followup_agent.py` |

### WeaknessAgent Prompt Language Shift

**File: `backend/agents/weakness_agent.py`**

Replace the system prompt instruction:
```
# BEFORE
"Identify the exact nature of the weakness or gap..."

# AFTER
"Identify where the candidate's knowledge boundary sits — not as a deficit,
but as a map of what they know deeply vs. where their understanding becomes surface-level."
```

Add `continue_probing: bool` to WeaknessAgent output schema (currently missing per REDESIGN_SPEC):
- `true` when boundary has been confirmed (don't ask again)
- `false` when the boundary is still unclear and a different probe angle would be productive

### Attack Strategy → Probe Direction Rename

**File: `backend/agents/followup_agent.py`**
Rename `ATTACK_STRATEGY_INSTRUCTIONS` → `PROBE_DIRECTION_INSTRUCTIONS`. Update all references in `generate()` and `adapt_followup()`.

The content of the dict is already mostly correct — the language is the issue, not the logic.

---

## Layer 1 — RAG Removal (Complete Excision)

The RAG pathway (FAISS + question bank) is dead weight. It adds startup latency, a 80MB model-reload bug, and a dependency on `ml_questions.json` which isn't being updated. `generate_sprint_question()` already has a non-RAG path; RAG is the fallback that shouldn't exist.

### Files to Delete Entirely

```
backend/rag/faiss_store.py
backend/rag/question_bank.py
data/ml_questions.json          (if it exists at this path)
```

Verify with: `find . -name "ml_questions.json"` and `find . -name "faiss_store.py"`.

### Call Sites to Remove

**File: `backend/main.py`** — lifespan function:
```python
# REMOVE this block entirely:
try:
    from backend.rag.question_bank import question_bank
    await asyncio.to_thread(question_bank.build_index)
    print("[Startup] RAG question bank index built.")
except Exception as e:
    print(f"[Startup] RAG index build failed (non-fatal): {e}")
```

Also remove any import of `question_bank` from main.py.

**File: `backend/agents/followup_agent.py`** — `generate_sprint_question()`:
```python
# REMOVE this block (the retrieve() call and its guard):
try:
    from backend.rag.question_bank import question_bank
    retrieved = question_bank.retrieve(query=context_summary, sprint=sprint, top_k=3)
    if retrieved:
        rag_block = "\n\nRelevant question templates for context:\n" + "\n".join(
            f"- {q['question']}" for q in retrieved
        )
except Exception:
    rag_block = ""
```

After removing, `generate_sprint_question()` uses only the LLM + interview map path — which is already the primary path.

**File: `backend/services/orchestrator.py`** — anywhere `question_bank` is imported or called. Search: `grep -n "question_bank\|faiss_store\|retrieve(" backend/services/orchestrator.py`.

### Verify Removal

After deletion, run: `grep -rn "question_bank\|faiss_store\|ml_questions" backend/` — should return zero results.

Remove from `requirements.txt` / `pyproject.toml`:
- `faiss-cpu` (or `faiss-gpu`)
- `sentence-transformers`

These are large packages. Removing them meaningfully reduces the deployment image size.

---

## Layer 2 — Immediate Bug Fixes

These are confirmed bugs with no architectural dependency. Ship these first.

### Bug 1 — Dashboard Data Unmapped

**Symptom:** Dashboard shows 0/null for every meaningful field on every real session.
**Root cause:** `/sessions` endpoint returns raw Postgres rows without unpacking the `full_report` JSONB column.

**File: `backend/api/routes.py`** — `get_sessions()` handler:

```python
# CURRENT (broken):
rows = await postgres.list_sessions()
return [dict(row) for row in rows]

# FIXED:
rows = await postgres.list_sessions()
result = []
for row in rows:
    d = dict(row)
    full_report = d.pop("full_report", None) or {}
    if isinstance(full_report, str):
        import json
        full_report = json.loads(full_report)
    # Unpack fields the dashboard expects at top level
    d["overall_score"] = full_report.get("overall_score")
    d["hire_recommendation"] = full_report.get("hire_recommendation")
    d["weakness_summary"] = full_report.get("weakness_summary", {})
    d["raw_weaknesses"] = full_report.get("raw_weaknesses", [])
    d["failure_surface"] = full_report.get("failure_surface", {})
    d["total_questions"] = full_report.get("total_questions")
    d["scores"] = full_report.get("scores", {})
    result.append(d)
return result
```

Also fix `app/dashboard/page.tsx`: the `recommendationFromSurface()` function derives verdict from `failure_surface` averages. Replace with direct use of `hire_recommendation` from the unpacked row:
```typescript
// Remove recommendationFromSurface() entirely.
// Use: session.hire_recommendation ?? "UNKNOWN"
```

### Bug 2 — Admin Endpoint Unauthenticated

**File: `backend/api/routes.py`** — `/admin/redis-dump` endpoint:

```python
# ADD at the top of the handler, before any Redis access:
admin_secret = os.environ.get("ANTIGRAVITY_ADMIN_SECRET", "")
if not admin_secret:
    raise HTTPException(status_code=503, detail="Admin endpoint not configured")
provided = request.headers.get("X-Admin-Secret", "")
if not hmac.compare_digest(provided, admin_secret):
    raise HTTPException(status_code=401, detail="Unauthorized")
```

Add `ANTIGRAVITY_ADMIN_SECRET` to Render environment variables. If it's unset in prod, the endpoint returns 503 rather than dumping data.

### Bug 3 — Weakness Summary Not Rendered

**File: `app/report/[session_id]/page.tsx`**

Add `weakness_summary` to the `Report` type:
```typescript
interface Report {
  // ... existing fields ...
  weakness_summary?: Record<string, number>;  // e.g. { "shallow": 3, "vague": 2 }
}
```

Add a "Probing Points" section to the JSX (replacing "Detected Weaknesses"):
```tsx
{report.weakness_summary && Object.keys(report.weakness_summary).length > 0 && (
  <section>
    <h2>Probing Points</h2>
    <ul>
      {Object.entries(report.weakness_summary).map(([type, count]) => (
        <li key={type}>{type}: {count}</li>
      ))}
    </ul>
  </section>
)}
```

### Bug 4 — Report Language/Titles

**File: `app/report/[session_id]/page.tsx`**:
- Page `<title>` and `<h1>`: "Failure boundary analysis" → "Interview Assessment Report"
- Section heading "Failure Surface": → "Knowledge Boundary Map"
- Section heading "Detected Weaknesses": → "Probing Points"

These are string replacements — no logic changes.

### Bug 5 — FAISS Singleton (Moot After Layer 1)

This bug (model reload on every search) is resolved by the RAG removal in Layer 1. No separate fix needed.

---

## Layer 3 — P0 Map Generation Fixes (Group A)

These are the surgical changes from INTERVIEW_REDESIGN.md §13, Group A. They fix the interview map pipeline which runs before the candidate speaks — broken maps produce broken interviews regardless of all other fixes.

### A1 — Thread `target_role` Into Map Generation

**The single root cause of role-blindness:** `generate_interview_map()` never receives `target_role`. It's available in session state at call time but isn't passed.

**File: `backend/services/orchestrator.py`**, around line 2811:
```python
# BEFORE:
interview_map = await asyncio.wait_for(
    generate_interview_map(
        resume=resume,
        session_id=session_id,
    ),
    timeout=...,
)

# AFTER:
interview_map = await asyncio.wait_for(
    generate_interview_map(
        resume=resume,
        session_id=session_id,
        target_role=state.get("target_role", ""),
    ),
    timeout=...,
)
```

**File: `backend/services/interview_map.py`** — function signature (around line 2327):
```python
# BEFORE:
async def generate_interview_map(
    *,
    resume: str,
    session_id: str = "",
) -> dict:

# AFTER:
async def generate_interview_map(
    *,
    resume: str,
    session_id: str = "",
    target_role: str = "",
) -> dict:
```

Thread `target_role` through to every internal call: `_generate_focus_area_plan()`, `_generate_priority_tracks_for_candidate()`, `hydrate_interview_map_tracks()`. Each of these needs a `target_role: str = ""` parameter added.

**Risk:** Zero. Defaults to `""`. All existing behavior unchanged when empty.

### A2 — Role-Type Anchor Selection Override

**File: `backend/services/interview_map.py`** — `_focus_plan_user_prompt()` (around line 988):

Add `target_role: str = ""` parameter. Inject role-conditional anchor ranking BEFORE the core rules section:

```python
def _focus_plan_user_prompt(*, resume: str, dedup_hint: str = "", target_role: str = "") -> str:
    lines = ["Resume (full text):", resume, ""]

    role_lower = target_role.lower()
    is_analyst_role = any(t in role_lower for t in (
        "product analyst", "product manager", "growth analyst",
        "data analyst", "analytics", "pm ", "apm",
    ))
    if is_analyst_role:
        lines.extend([
            f"ROLE CONTEXT: This is a {target_role} role.",
            "ANCHOR SELECTION OVERRIDE FOR ANALYTICS/PM ROLES:",
            "- The highest-priority anchor is the OUTCOME claim with the richest experimental",
            "  and analytical reasoning surface area.",
            "- A bullet claiming '25%→42% retention via A/B testing' OUTRANKS 'architected",
            "  analytics infrastructure' because the outcome claim implies: hypothesis formation,",
            "  experiment design, causal attribution, and measurement validity.",
            "- Implementation and infrastructure claims become sub-dimensions of the outcome",
            "  they enabled — not separate focus areas.",
            "- Quantified outcome claims with A/B testing, conversion optimization, or funnel",
            "  analysis are always anchor[0].",
            "",
        ])

    # ... existing lines with JSON schema spec ...
```

**Risk:** Only fires when `target_role` contains analyst/PM keywords. All other roles use existing behavior unchanged.

### A3 — Role-Type Depth Instructions in Track System Prompt

The `_TRACK_SYSTEM` module-level constant must become a function. The "No walk me through" rule that currently prohibits warm narrative openers is correct for engineering roles but actively harmful for analyst/PM roles.

**File: `backend/services/interview_map.py`** — convert `_TRACK_SYSTEM` constant (around line 188) to function:

```python
def _track_system_prompt(role_type: str = "") -> str:
    role_lower = role_type.lower()
    is_analyst_role = any(t in role_lower for t in (
        "product analyst", "product manager", "growth analyst",
        "data analyst", "analytics",
    ))

    base = (
        "You are an expert technical interviewer designing a precision interview track "
        "for one specific resume focus area.\n\n"
        "Your goal: write questions that find where a candidate's knowledge actually ends — "
        "not what vocabulary they know, but what they can explain from genuine hands-on experience."
    )

    if is_analyst_role:
        depth_instruction = """

ROLE-TYPE OVERRIDE — PRODUCT ANALYST / PM ROLE:
For this role, "depth" means analytical reasoning quality, not implementation fidelity.

Opener rules (OVERRIDE):
- Opener must be warm, narrative-inviting, anchored to the OUTCOME claim, not the implementation.
- Pattern: "Walk me through [the experiment / the analysis] — what were you actually testing and why?"
- NEVER ask what was built first, what event was defined first, or implementation chronology.
- The opener should invite the candidate to narrate the work in their own words.
- "Tell me more about" and "walk me through" ARE allowed — they produce better signal for this role.

Mandatory dimensions for analyst roles — include at least one of each:
1. METRIC VALIDITY: probe how the key metric was defined, what the denominator was, over what
   time window, what cohort. Example: "That 25→42% retention — Day-7 on new installs, or
   something else? What was in the denominator?"
2. CAUSAL REASONING: probe whether the candidate understands WHY the result happened, not just
   that it did. Example: "How do you know the trial change caused the conversion improvement —
   what rules out organic growth or seasonality?"
3. EXPERIMENT DESIGN (if A/B testing claimed): variant assignment, contamination, and result
   interpretation. Example: "If a user qualified for both experiments simultaneously, what
   happened to variant attribution?"

Boundary probe definition for analyst roles:
- NOT "what breaks at scale" — that's an engineering question
- YES "what would make this result wrong, unmeasurable, or uninterpretable"
"""
    else:
        depth_instruction = """

Opener rules:
- Reference the single most specific artifact or technology named in the resume snippets
- Pick one end of the problem as a starting hypothesis — do not ask about everything at once
- Must be consistent with dimensions[0]: the opener enters that dimension
- Max 24 words. No "walk me through" or "tell me about" — those invite monologue
- The answer should be answerable at different depths: shallowness reveals itself quickly
"""

    remainder = (
        "\n\n"
        + """Dimension rules (generate 4–6, each grounded in actual resume evidence):
- surface: confirms the concept exists in their experience
- mechanism: tests whether they understand WHY it works
- boundary: designed to be unanswerable if they only read documentation or didn't personally own this

signal_weight: float 1.0–3.0. Rate each dimension by how much it reveals about role fitness.
  For analyst roles: metric_validity=3.0, causal_reasoning=3.0, experiment_design=2.5, implementation_details=1.5
  For engineering roles: boundary probes on core claimed system=3.0, secondary tools=1.5
  Default when uncertain: 1.5

"""
        # ... append the rest of the existing _TRACK_SYSTEM content here ...
    )
    return base + depth_instruction + remainder
```

Everywhere `_TRACK_SYSTEM` is currently referenced (two LLM calls minimum), replace with `_track_system_prompt(role_type=target_role)`.

**Risk:** Medium. Thread `role_type: str = ""` through `_generate_focus_track()` and `_generate_priority_tracks_for_candidate()`. Test both LLM call sites.

### A4 — Fix the Repair Loop Trigger

**The bug:** `_review_is_ready()` returns True when `overall_score >= 7.0`, which means the Apparao map (score: 7.6) skipped all four repair instructions from the critic. The repair mechanism itself works — only the trigger threshold is wrong.

**File: `backend/services/interview_map.py`** — add helper function:

```python
def _has_targeted_repairs(review: dict | None) -> bool:
    """True when the critic identified specific fixable issues, even if overall score looks ready."""
    if not isinstance(review, dict):
        return False
    if len(review.get("repair_instructions") or []) >= 2:
        return True
    for fr in (review.get("focus_reviews") or []):
        if isinstance(fr, dict) and fr.get("opener_issue"):
            return True
    return False
```

**Change the gate** (around line 2370):
```python
# BEFORE:
if not _review_is_ready(pass_one_review):

# AFTER:
if not _review_is_ready(pass_one_review) or _has_targeted_repairs(pass_one_review):
```

**Why this is safe:** The repair path generates WITH critic feedback as guidance. If repaired tracks score lower, the original is kept (existing line: `if _review_score(repaired_review) >= _review_score(pass_one_review)`). Worst case: one extra generation call that doesn't improve quality, and original ships. This is a no-regression change.

### A5 — Focus Area Budget Allocation Instruction

**File: `backend/services/interview_map.py`** — append to `_FOCUS_PLAN_SYSTEM` (around line 896):

```python
_FOCUS_PLAN_SYSTEM = """...(existing content)...

BUDGET ALLOCATION SIGNALS (used by question routing — shapes your area selection priority):
- area[0] receives approximately 60% of interview time — select the single most analytically rich experience
- area[1] receives approximately 20-25%
- area[2]+ receive attention-check level coverage — 2-3 questions max
- If the resume contains an academic internship of ≤3 months with no continuity to current career path,
  include it as area[2] at most — NEVER elevate it above current-role work
- A 2-month summer internship must NOT share equal slot weight with a 12-month current role
- Bridge direction: always from most-recent toward oldest — never route backward in time

JSON only, no markdown, no commentary."""
```

**Risk:** Zero. Documentation-level context added to the prompt. No schema changes.

### A6 — Add `signal_weight` to Dimension Schema

**File: `backend/services/interview_map.py`** — `_TRACK_USER_TEMPLATE` dimension schema (around line 235):

```python
# Add signal_weight to the dimension output format:
{
  "id": "snake_case_dimension_id",
  "label": "short dimension label",
  "resume_anchor": "exact or near-exact resume claim this dimension probes",
  "surface": "question confirming basic familiarity",
  "mechanism": "question requiring genuine implementation understanding",
  "boundary": "question unanswerable without real hands-on ownership",
  "signal_weight": 1.5   # ← NEW FIELD
}
```

**File: `backend/services/interview_map.py`** — `_coerce_llm_track()` function: handle missing `signal_weight` with a default:
```python
for dim in track.get("dimensions", []):
    dim.setdefault("signal_weight", 1.5)
```

**File: `backend/services/interview_map.py`** — `select_from_trajectory_map_detailed()`: when multiple dimensions are available for a focus area, sort by `signal_weight` descending before selecting:
```python
available_dims = [d for d in focus_area["dimensions"] if not d.get("asked")]
if available_dims:
    available_dims.sort(key=lambda d: d.get("signal_weight", 1.5), reverse=True)
    next_dim = available_dims[0]
```

**Risk:** Medium. New field in dimension schema — `_coerce_llm_track()` default handles backward compatibility. Selection function change affects ordering but not correctness.

---

## Layer 4 — P0 Live Interview Fixes (Group B)

These are orchestrator-level guards. Independent of each other and of the map fixes. Can ship in any order.

### B1 — Skip Signal Detection

**Root cause of session e5170a7a:** Candidate said "skip" and "move on" six times. None triggered any routing change — they were scored as deflections, exhausting the deflection budget, and the same focus area continued.

**File: `backend/services/orchestrator.py`** — after `_ADMISSION_SIGNALS` regex (around line 83):

```python
_SKIP_SIGNALS = re.compile(
    r"\b(skip|next question|move on|move to something|different topic|"
    r"another topic|something else|can we move|let'?s move|"
    r"change the topic|switch topics)\b",
    re.IGNORECASE,
)

_SOCIAL_DEFLECTION_SIGNALS = re.compile(
    r"\b(i'?m good|don'?t worry|that'?s fine|no no no|thank you i'?m good|"
    r"i'?m okay with that|it'?s okay|never mind)\b",
    re.IGNORECASE,
)

def _looks_like_skip_request(text: str) -> bool:
    return bool(_SKIP_SIGNALS.search(text))

def _looks_like_social_deflection(text: str) -> bool:
    return bool(_SOCIAL_DEFLECTION_SIGNALS.search(text))
```

**File: `backend/services/orchestrator.py`** — in `handle_transcript()`, after the echo guard:

```python
# Skip/disengagement detection — runs before consuming staged analysis
candidate_state = state.setdefault("candidate_state", _initial_candidate_state())
if _looks_like_skip_request(text):
    candidate_state["explicit_skip_count"] = candidate_state.get("explicit_skip_count", 0) + 1
    candidate_state["disengagement_level"] = min(
        5.0,
        candidate_state.get("disengagement_level", 0.0) + 2.0,
    )
    state["_force_focus_rotation"] = True
elif _looks_like_social_deflection(text):
    candidate_state["social_deflection_count"] = candidate_state.get("social_deflection_count", 0) + 1
    candidate_state["disengagement_level"] = min(
        5.0,
        candidate_state.get("disengagement_level", 0.0) + 1.0,
    )
state["candidate_state"] = candidate_state
```

**File: `backend/services/orchestrator.py`** — in `_run_background_pipeline()`, after the `force_sprint_question` flags:
```python
if state.get("_force_focus_rotation"):
    force_sprint_question = True
    pivoting = True
    state.pop("_force_focus_rotation", None)  # consume the flag once
```

### B2 — Topic Fatigue Ratio Check

**Root cause of session e5170a7a:** The existing anti-tunneling guard fires only when `same_focus_recent >= 2 AND severity == "high"`. With 13/15 questions on Veo-3 at varying severities, none of the window-based conditions fired.

**File: `backend/services/orchestrator.py`** — in `_run_background_pipeline()`, after `same_focus_history` is computed:

```python
# Topic fatigue ratio — fires even when severity varies turn-to-turn
total_history_turns = len(history)
focus_ratio = (
    len(same_focus_history) / total_history_turns
    if total_history_turns >= 5 else 0.0
)
topic_ratio_exceeded = focus_ratio > 0.55

if topic_ratio_exceeded:
    force_sprint_question = True
    pivoting = True
    await self._trace(
        session_id, "topic_fatigue_ratio_exceeded",
        turn_id=turn_id,
        focus_key=current_focus_key,
        focus_ratio=round(focus_ratio, 2),
        total_turns=total_history_turns,
    )
```

**Also add to `candidate_state.topic_fatigue` dict tracking:**
After a question on `current_focus_key` is committed to history, increment:
```python
topic_fatigue = candidate_state.setdefault("topic_fatigue", {})
topic_fatigue[current_focus_key] = topic_fatigue.get(current_focus_key, 0) + 1
```

**Risk:** Low. Only fires when `focus_ratio > 0.55` with ≥5 turns. The `force_sprint_question = True` path already exists.

### B3 — Warm Guard (No Attack Probe on First Two Turns)

**Root cause:** `_run_background_pipeline()` has no turn_number guard on the `aggressive_probe` route. Turn 2 (the response to the candidate's first answer) can be an adversarial mechanism probe even when the opening preamble promised "let's ease in."

**File: `backend/services/orchestrator.py`** — change `aggressive_probe` condition (around line 2410):

```python
# BEFORE:
aggressive_probe = (
    isinstance(weakness, dict)
    and weakness.get("severity") == "high"
    and weakness.get("attack_strategy") not in ("clarification", "ownership_probe")
)

# AFTER:
aggressive_probe = (
    isinstance(weakness, dict)
    and weakness.get("severity") == "high"
    and weakness.get("probe_direction") not in ("clarification", "ownership_probe")
    and turn_number >= 2   # protect first two turns — warmth promise must be kept
)
```

(Note: `attack_strategy` → `probe_direction` per Layer 0 rename.)

When `aggressive_probe` is blocked by `turn_number < 2`, the route falls through to `sprint_seed` → `generate_sprint_question()` — which is the correct warm/narrative behavior.

### B4 — Initialize `candidate_state` in Session State

**File: `backend/services/orchestrator.py`** — in `_build_initial_state()` (around line 755), add to the return dict:

```python
"candidate_state": {
    "disengagement_level": 0.0,
    "consecutive_no_content": 0,
    "explicit_skip_count": 0,
    "social_deflection_count": 0,
    "incoherence_count": 0,
    "communication_mode": "normal",       # "normal" | "simplified" | "narrative_only"
    "topic_fatigue": {},                   # {focus_key: question_count}
    "forced_exit_triggered": False,
    "phase": "orientation",
    "anchor_confidence": None,             # set during Phase 2 — "high" | "medium" | "low"
    "implementation_anchor": None,         # extracted from Phase 2 answers
    "second_domain_surfaced": None,        # populated when candidate mentions second experience
},
```

**Risk:** Zero. New nested dict in session state. Existing code doesn't read `candidate_state`, so no regressions.

---

## Layer 5 — P1 Candidate State Layer

These changes build on Layer 4's `candidate_state` initialization. The `CandidateState` dataclass lives in its own file and is used as the typed interface for state dict operations.

### New File: `backend/state/candidate_state.py`

```python
from dataclasses import dataclass, field


@dataclass
class CandidateState:
    disengagement_level: float = 0.0
    consecutive_no_content: int = 0
    explicit_skip_count: int = 0
    social_deflection_count: int = 0
    incoherence_count: int = 0
    communication_mode: str = "normal"       # "normal" | "simplified" | "narrative_only"
    topic_fatigue: dict = field(default_factory=dict)
    topic_fatigue_threshold: int = 4
    forced_exit_triggered: bool = False
    phase: str = "orientation"
    anchor_confidence: str | None = None
    implementation_anchor: str | None = None
    second_domain_surfaced: str | None = None


DISENGAGEMENT_INCREMENTS = {
    "explicit_skip": 2.0,
    "social_deflection": 1.0,
    "zero_content": 0.5,
    "incoherent": 1.0,
    "substantive_answer": -0.5,
}


def update_disengagement(state_dict: dict, signal: str) -> float:
    """Apply a disengagement signal. Returns new disengagement_level."""
    cs = state_dict.setdefault("candidate_state", {})
    current = cs.get("disengagement_level", 0.0)
    delta = DISENGAGEMENT_INCREMENTS.get(signal, 0.0)
    new_level = max(0.0, min(5.0, current + delta))
    cs["disengagement_level"] = new_level
    return new_level


def check_topic_fatigue(state_dict: dict, focus_key: str) -> bool:
    """Returns True if forced rotation should trigger for this focus_key."""
    cs = state_dict.get("candidate_state", {})
    threshold = cs.get("topic_fatigue_threshold", 4)
    count = cs.get("topic_fatigue", {}).get(focus_key, 0)
    return count >= threshold


def get_topic_fatigue_ratio(state_dict: dict, focus_key: str) -> float:
    cs = state_dict.get("candidate_state", {})
    fatigue = cs.get("topic_fatigue", {})
    total = sum(fatigue.values())
    if total == 0:
        return 0.0
    return fatigue.get(focus_key, 0) / total


def detect_communication_mode(turn1_text: str, turn2_text: str) -> str:
    """
    Run on first two turns only. Returns communication_mode.
    ESL markers: word repetition, mid-sentence restarts, fragmented syntax.
    """
    combined = f"{turn1_text} {turn2_text}".lower()
    words = combined.split()

    # Word repetition — "while while while", "for for that"
    repetition_count = sum(
        1 for i in range(len(words) - 1) if words[i] == words[i + 1]
    )

    # Very short responses (single-word or near-empty)
    turn1_words = len(turn1_text.split())
    turn2_words = len(turn2_text.split())
    shutdown_count = sum(1 for w in (turn1_words, turn2_words) if w < 5)

    if repetition_count >= 3:
        return "simplified"
    if shutdown_count >= 2:
        return "narrative_only"
    return "normal"
```

### Disengagement Action Thresholds in Orchestrator

**File: `backend/services/orchestrator.py`** — in `_run_background_pipeline()`, after candidate_state is read:

```python
from backend.state.candidate_state import update_disengagement, check_topic_fatigue

disengagement_level = state.get("candidate_state", {}).get("disengagement_level", 0.0)

# Level 2.0 → save-face pivot question
if disengagement_level >= 2.0 and not state.get("_save_face_pivot_used"):
    # FollowUpAgent will receive a hint to use confession_pivot route
    state["_next_route_hint"] = "confession_pivot"
    state["_save_face_pivot_used"] = True

# Level 3.0 → force topic rotation
if disengagement_level >= 3.0:
    force_sprint_question = True
    pivoting = True

# Level 4.0 → simplified communication mode
if disengagement_level >= 4.0:
    cs = state.setdefault("candidate_state", {})
    cs["communication_mode"] = "simplified"

# Level 5.0 → graceful exit — skip to Phase 6 close
if disengagement_level >= 5.0 and not state.get("candidate_state", {}).get("forced_exit_triggered"):
    cs = state.setdefault("candidate_state", {})
    cs["forced_exit_triggered"] = True
    state["_next_route_hint"] = "graceful_exit"
```

### Confession Pivot Route in FollowUpAgent

**File: `backend/agents/followup_agent.py`** — add new method:

```python
async def generate_confession_pivot(self, state: dict) -> str:
    """
    Save-face pivot when disengagement_level >= 2.0.
    Resets the frame to what the candidate is most confident about.
    """
    target_role = state.get("target_role", "this role")
    prompt = (
        f"You are conducting a technical interview for a {target_role} position. "
        "The candidate appears to be struggling with the current line of questioning. "
        "Generate ONE warm, reframing question that:\n"
        "- Acknowledges the difficulty without dwelling on it\n"
        "- Redirects to what the candidate knows best\n"
        "- Opens a new avenue rather than repeating the old one\n"
        "Pattern: 'Let me try a different angle — [what skill/area are you most confident explaining "
        "that this role needs?]'\n"
        "Return only the question text."
    )
    result = await self.llm.complete_small(prompt)
    return self._clean_question_output(result)
```

In the orchestrator routing block, handle `_next_route_hint == "confession_pivot"`:
```python
if state.get("_next_route_hint") == "confession_pivot":
    state.pop("_next_route_hint", None)
    followup = await self.followup_agent.generate_confession_pivot(state)
```

### Communication Mode Detection (Turns 1-2)

**File: `backend/services/orchestrator.py`** — in `handle_transcript()`, when `turn_number == 1` (second turn, zero-indexed):

```python
from backend.state.candidate_state import detect_communication_mode

if turn_number == 1:
    # Two turns of data now available — detect communication mode
    history = state.get("conversation_history", [])
    if len(history) >= 2:
        turn0_text = history[-2].get("candidate_text", "")
        turn1_text = history[-1].get("candidate_text", "")
        mode = detect_communication_mode(turn0_text, turn1_text)
        cs = state.setdefault("candidate_state", {})
        cs["communication_mode"] = mode
        if mode != "normal":
            await self._trace(session_id, "communication_mode_detected", mode=mode, turn=turn_number)
```

### Pass `communication_mode` to FollowUpAgent

**File: `backend/agents/followup_agent.py`** — in all `generate_*` methods, add `communication_mode: str = "normal"` parameter. When `communication_mode != "normal"`, append to the prompt:

```python
if communication_mode == "simplified":
    prompt += (
        "\n\nCOMMUNICATION STYLE: Use maximum ONE sentence per question. "
        "Prefer 'Tell me about X' framing. Avoid compound questions. "
        "Use simple vocabulary. This candidate is communicating in a non-primary language."
    )
elif communication_mode == "narrative_only":
    prompt += (
        "\n\nCOMMUNICATION STYLE: Ask open narrative questions only — "
        "'Tell me more about what you were working on.' "
        "No mechanism probes. No closed questions."
    )
```

---

## Layer 6 — P1 Evaluation Fixes (Group D)

These changes improve the evaluation pipeline. Most are additive — the existing EvaluationAgent is closer to the target state than expected (it already has `INSUFFICIENT_DATA`, `untested_dimensions`, `coverage_note`).

### D1 — Move `hire_recommendation` Out of LLM Output

**Root cause:** Same transcript at different LLM temperatures → different `hire_recommendation`. This creates inconsistency for ProvenHire.

**File: `backend/agents/evaluation_agent.py`** — remove `hire_recommendation` from the `FULL_INTERVIEW_PROMPT` output schema. LLM should output `raw_score` and `score_breakdown` only.

Add a pure Python function after the LLM call:

```python
def compute_hire_recommendation(
    overall_score: float,
    coverage_ratio: float,
    weakness_types: list[str],
    discrepancy_level: str = "none",
    disengagement_triggered: bool = False,
) -> str:
    """
    Deterministic hire recommendation. No LLM randomness.

    coverage_ratio: 0.0-1.0, fraction of expected dimensions tested
    weakness_types: list of WeaknessAgent.weakness_type values across all turns
    """
    if disengagement_triggered:
        return "INSUFFICIENT_DATA"

    # Homogeneous weakness types + low coverage = no signal
    unique_types = set(weakness_types)
    if coverage_ratio < 0.35:
        return "INSUFFICIENT_DATA"

    # Confirmed discrepancy overrides score
    if discrepancy_level == "confirmed":
        return "CLAIM_RISK_FLAG"

    # Score-based tiers
    if overall_score >= 8.0 and coverage_ratio >= 0.75:
        return "STRONG_HIRE"
    elif overall_score >= 6.5 and coverage_ratio >= 0.55:
        return "HIRE"
    elif overall_score >= 4.5 and coverage_ratio >= 0.35:
        return "MAYBE"
    elif coverage_ratio >= 0.45:
        return "NO_HIRE"
    else:
        return "INSUFFICIENT_DATA"


def compute_confidence(
    coverage_ratio: float,
    questions_asked: int,
    disengagement_level: float,
    discrepancy_level: str,
) -> float:
    """Deterministic confidence score. 0.0-1.0."""
    base = min(1.0, coverage_ratio)

    # Penalize for very few questions
    if questions_asked < 5:
        base *= 0.6
    elif questions_asked < 8:
        base *= 0.8

    # Penalize for disengagement
    if disengagement_level >= 3.0:
        base *= 0.7
    elif disengagement_level >= 2.0:
        base *= 0.85

    # Confirmed discrepancy adds confidence (we know something definitively)
    if discrepancy_level == "confirmed":
        base = min(1.0, base + 0.1)

    return round(max(0.1, min(1.0, base)), 2)
```

Call these after the LLM returns `overall_score` and `coverage_ratio`:
```python
hire_recommendation = compute_hire_recommendation(
    overall_score=full_eval.get("overall_score", 0),
    coverage_ratio=coverage_ratio,
    weakness_types=[t.get("weakness_type") for t in all_weaknesses],
    discrepancy_level=state.get("discrepancy_level", "none"),
    disengagement_triggered=state.get("candidate_state", {}).get("forced_exit_triggered", False),
)
confidence_score = compute_confidence(
    coverage_ratio=coverage_ratio,
    questions_asked=total_questions,
    disengagement_level=state.get("candidate_state", {}).get("disengagement_level", 0.0),
    discrepancy_level=state.get("discrepancy_level", "none"),
)
```

### D2 — Role-Adjusted Per-Answer Scoring Rubric

**File: `backend/agents/evaluation_agent.py`** — `score_answer()` prompt:

For analyst roles, swap the scoring dimensions:
```python
# Detect role from state
is_analyst_role = any(t in (target_role or "").lower() for t in (
    "product analyst", "product manager", "data analyst", "analytics",
))

if is_analyst_role:
    scoring_dimensions = (
        "problem_framing, logical_reasoning, measurement_validity, business_impact_awareness"
    )
else:
    scoring_dimensions = (
        "problem_framing, logical_reasoning, technical_correctness, production_awareness"
    )
```

### D3 — Wire ReasoningBehaviorAgent Signal Into Live Interview

**Current gap:** `ReasoningBehaviorAgent` runs in the background pipeline and outputs `adaptability`, `structure_score`, `clarification_behavior` — but these signals are not fed back into Turn N+1 question generation. They go only to the final evaluation.

**File: `backend/services/orchestrator.py`** — in `_run_background_pipeline()`, after `ReasoningBehaviorAgent` completes:

```python
reasoning = await reasoning_behavior_agent_task
if isinstance(reasoning, dict):
    adaptability = reasoning.get("adaptability", "")
    state["_reasoning_tone_signal"] = adaptability   # consumed by followup_agent
```

**File: `backend/agents/followup_agent.py`** — in `generate()`, read and apply:
```python
tone_signal = state.get("_reasoning_tone_signal", "")
if tone_signal in ("defensive", "confrontational"):
    # Back off — use collaborative framing, not challenge framing
    tone_instruction = (
        "\n\nTONE ADJUSTMENT: The candidate has shown defensive behavior. "
        "Use collaborative framing ('Help me understand...' not 'Why did you...'). "
        "Do not challenge directly — create space for them to reconsider voluntarily."
    )
elif tone_signal == "admitted_gap":
    # Don't probe the admitted gap further — pivot
    tone_instruction = (
        "\n\nTONE ADJUSTMENT: The candidate has acknowledged a gap. "
        "Do not probe this gap further. Move to a different area."
    )
else:
    tone_instruction = ""
```

---

## Layer 7 — P2 New Interview Architecture

This is the largest structural change. Build in the order listed — each component is a prerequisite for the next.

### 7a — New File: `backend/models/coverage_map.py`

```python
from dataclasses import dataclass, field


COVERAGE_WEIGHTS = {
    "voluntary":         1.0,
    "recovered_deep":    0.7,
    "recovered_surface": 0.4,
    "missed":            0.0,
    "incorrect":        -0.2,
    "not_evaluated":     0.0,
}


@dataclass
class CoverageDimension:
    id: str
    label: str
    description: str
    expected_approaches: list[str]
    surfacing_question: str
    weight: float
    coverage_state: str = "not_evaluated"
    candidate_response: str = ""
    surfacing_attempted: bool = False


@dataclass
class AnswerCoverageMap:
    application_question: str
    implementation_anchor: str
    dimensions: list[CoverageDimension]
    total_weight: float
    coverage_score: float = 0.0
    coverage_confidence: float = 0.0    # 0.0-1.0: how well the LLM knows this domain

    def compute_coverage_score(self) -> float:
        if self.total_weight == 0:
            return 0.0
        weighted_sum = sum(
            d.weight * COVERAGE_WEIGHTS.get(d.coverage_state, 0.0)
            for d in self.dimensions
        )
        self.coverage_score = max(0.0, weighted_sum / self.total_weight)
        return self.coverage_score

    def unsurfaced_dimensions(self) -> list[CoverageDimension]:
        return [
            d for d in self.dimensions
            if d.coverage_state == "not_evaluated" and not d.surfacing_attempted
        ]

    def to_dict(self) -> dict:
        return {
            "application_question": self.application_question,
            "implementation_anchor": self.implementation_anchor,
            "coverage_score": self.coverage_score,
            "coverage_confidence": self.coverage_confidence,
            "dimensions": [
                {
                    "id": d.id,
                    "label": d.label,
                    "description": d.description,
                    "surfacing_question": d.surfacing_question,
                    "weight": d.weight,
                    "coverage_state": d.coverage_state,
                    "surfacing_attempted": d.surfacing_attempted,
                }
                for d in self.dimensions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerCoverageMap":
        dims = [
            CoverageDimension(
                id=d["id"],
                label=d["label"],
                description=d["description"],
                expected_approaches=[],
                surfacing_question=d["surfacing_question"],
                weight=d["weight"],
                coverage_state=d.get("coverage_state", "not_evaluated"),
                surfacing_attempted=d.get("surfacing_attempted", False),
            )
            for d in data.get("dimensions", [])
        ]
        return cls(
            application_question=data["application_question"],
            implementation_anchor=data["implementation_anchor"],
            dimensions=dims,
            total_weight=sum(d.weight for d in dims),
            coverage_score=data.get("coverage_score", 0.0),
            coverage_confidence=data.get("coverage_confidence", 0.0),
        )
```

### 7b — New Agent: `backend/agents/application_agent.py`

This agent runs at the end of Phase 2 (after Turn 4). It takes the `implementation_anchor` extracted from the candidate's narration and produces:
1. The application transfer question (Phase 3)
2. The AnswerCoverageMap (the expected-answer lattice for Phase 4)

```python
import json
from backend.models.llm_router import LLMRouter
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension


APPLICATION_SYSTEM = """You are designing an application transfer question for a technical interview.

Given what a candidate just described building, you must:
1. Create ONE application transfer question — a new scenario in the same domain with ONE new constraint.
2. Generate 4-6 dimensions that a strong answer should address.

Rules for the application question:
- MUST reference the implementation_anchor specifically (name what they said they built)
- Adjacent constraint — same domain, ONE meaningful shift (batch→real-time, single-user→multi-tenant, controlled→adversarial)
- Situational framing: "Imagine your PM comes to you tomorrow and says..."
- Multiple valid implementation approaches must exist
- Calibrate to experience: junior→surface design; senior→failure modes and boundary conditions

Rules for dimensions:
- 4-6 dimensions maximum
- Each dimension: a distinct aspect of a strong answer to the application question
- expected_approaches: 2-3 valid implementations for this dimension (candidate doesn't need to name these, just address the concept)
- surfacing_question: a single exploratory prompt that names the SITUATION, not the SOLUTION
  - Wrong: "Did you consider caching?" (names the solution)
  - Right: "What happens when the pipeline falls behind real-time?" (names the problem space)
- weight: 1.0-3.0 based on importance to role fitness

Return JSON only:
{
  "application_question": "string",
  "adjacent_constraint": "string (what changed — e.g. 'batch → real-time session updates')",
  "anchor_reference": "string (the specific thing from their answer the question references)",
  "coverage_confidence": 0.0-1.0 (how well you know this domain — be honest; niche domains = lower),
  "dimensions": [
    {
      "id": "snake_case_id",
      "label": "short label",
      "description": "what this dimension tests",
      "expected_approaches": ["approach_a", "approach_b"],
      "surfacing_question": "the single exploratory prompt for this dimension",
      "weight": 1.5
    }
  ]
}"""


class ApplicationAgent:
    def __init__(self):
        self.llm = LLMRouter()

    async def generate(
        self,
        implementation_anchor: str,
        candidate_domain: str,
        target_role: str,
        years_experience: str,
        resume_snippets: list[str],
    ) -> AnswerCoverageMap | None:
        resume_context = "\n".join(f"- {s}" for s in (resume_snippets or [])[:5])
        user_msg = (
            f"Target role: {target_role}\n"
            f"Experience level: {years_experience}\n"
            f"Candidate domain: {candidate_domain}\n\n"
            f"Resume context:\n{resume_context}\n\n"
            f"Implementation anchor (what they said they built):\n{implementation_anchor}\n\n"
            "Generate the application transfer question and coverage map."
        )
        try:
            raw = await self.llm.complete_small(
                user_msg,
                system=APPLICATION_SYSTEM,
                max_tokens=1500,
            )
            data = self.llm.extract_json(raw)
            if not data:
                return None

            dims = [
                CoverageDimension(
                    id=d["id"],
                    label=d["label"],
                    description=d["description"],
                    expected_approaches=d.get("expected_approaches", []),
                    surfacing_question=d["surfacing_question"],
                    weight=float(d.get("weight", 1.5)),
                )
                for d in data.get("dimensions", [])
            ]
            return AnswerCoverageMap(
                application_question=data["application_question"],
                implementation_anchor=implementation_anchor,
                dimensions=dims,
                total_weight=sum(d.weight for d in dims),
                coverage_confidence=float(data.get("coverage_confidence", 0.5)),
            )
        except Exception as e:
            print(f"[ApplicationAgent] Generation failed: {e}")
            return None
```

### 7c — STAR-Lite Extraction in Orchestrator

At the end of Turn 4 (turn_number == 3, zero-indexed), extract `implementation_anchor` from the candidate's Phase 2 narration.

**File: `backend/services/orchestrator.py`** — in `_run_background_pipeline()`, when `turn_number == 3`:

```python
if turn_number == 3 and not state.get("candidate_state", {}).get("implementation_anchor"):
    # Extract implementation anchor from turns 2-3 (Phase 2 narration)
    history = state.get("conversation_history", [])
    phase2_text = " ".join(
        h.get("candidate_text", "")
        for h in history[-2:]
        if h.get("candidate_text")
    )
    anchor = await self._extract_implementation_anchor(session_id, phase2_text, state)
    if anchor:
        cs = state.setdefault("candidate_state", {})
        cs["implementation_anchor"] = anchor
        cs["anchor_confidence"] = _classify_anchor_confidence(anchor, phase2_text)

        # Kick off application transfer generation in background
        asyncio.create_task(
            self._generate_application_transfer(session_id, state)
        )
```

Add helper methods:

```python
async def _extract_implementation_anchor(
    self, session_id: str, phase2_text: str, state: dict
) -> str | None:
    """Extract the specific implementation detail from the candidate's Phase 2 narration."""
    prompt = (
        "From the following interview response, extract the single most specific "
        "implementation detail the candidate described — what they personally built, "
        "wrote, or figured out, at implementation level (not what the system does, "
        "but what they made). Return one sentence. If no specific detail exists, "
        f"return empty string.\n\nCandidate said:\n{phase2_text}"
    )
    result = await self.llm.complete_small(prompt, max_tokens=150)
    return result.strip() if result and len(result.strip()) > 20 else None


def _classify_anchor_confidence(anchor: str, phase2_text: str) -> str:
    """
    Classify anchor quality from text signals.
    high: first-person + specific artifact + number or named decision
    medium: correct vocabulary but no specific artifact
    low: system-language or generic
    """
    first_person_markers = ("i wrote", "i built", "i had to", "i figured", "i implemented")
    if any(m in anchor.lower() for m in first_person_markers):
        return "high"
    generic_markers = ("we handled", "it was", "the system", "we made sure")
    if any(m in anchor.lower() for m in generic_markers):
        return "low"
    return "medium"


async def _generate_application_transfer(self, session_id: str, state: dict) -> None:
    """Background task: generate application transfer question + coverage map."""
    try:
        cs = state.get("candidate_state", {})
        anchor = cs.get("implementation_anchor")
        if not anchor:
            return

        from backend.agents.application_agent import ApplicationAgent
        agent = ApplicationAgent()
        coverage_map = await agent.generate(
            implementation_anchor=anchor,
            candidate_domain=state.get("focus_key", ""),
            target_role=state.get("target_role", ""),
            years_experience=state.get("years_experience", "mid"),
            resume_snippets=state.get("resume_snippets", []),
        )
        if coverage_map:
            state["coverage_map"] = coverage_map.to_dict()
            state["prepped_application_question"] = coverage_map.application_question
            await self.session_manager.save_state(session_id, state)
    except Exception as e:
        print(f"[Orchestrator] Application transfer generation failed: {e}")
```

### 7d — Coverage-Guided Follow-up Route in FollowUpAgent

**File: `backend/agents/followup_agent.py`** — add coverage routing methods:

```python
from backend.models.coverage_map import AnswerCoverageMap

async def generate_coverage_surface(
    self,
    dimension_id: str,
    coverage_map: AnswerCoverageMap,
    state: dict,
) -> str:
    """
    Generate the surfacing question for an uncovered dimension.
    The surfacing_question is pre-built in the coverage map — this serves it with
    persona-appropriate framing.
    """
    dim = next((d for d in coverage_map.dimensions if d.id == dimension_id), None)
    if not dim:
        return await self.generate_sprint_question(state=state)

    persona = state.get("current_persona", "curious_lead")
    prompt = (
        f"You are conducting an interview in the voice of '{persona}'.\n"
        f"Deliver this coverage surfacing question in your persona's voice — warm and exploratory, "
        f"not interrogative:\n\n{dim.surfacing_question}\n\n"
        "Return only the question text, in your persona's voice. One sentence."
    )
    result = await self.llm.complete_small(prompt, max_tokens=100)
    return self._clean_question_output(result)


async def generate_coverage_depth_probe(
    self,
    dimension_id: str,
    coverage_map: AnswerCoverageMap,
    candidate_surface_response: str,
    state: dict,
) -> str:
    """
    Depth-of-recovery follow-up: candidate named the concept but couldn't explain mechanism.
    One probe — then move on regardless of answer.
    """
    dim = next((d for d in coverage_map.dimensions if d.id == dimension_id), None)
    if not dim:
        return await self.generate_sprint_question(state=state)

    anchor = coverage_map.implementation_anchor
    prompt = (
        f"The candidate mentioned '{dim.label}' when prompted but couldn't explain "
        f"how they implemented it in their specific system.\n"
        f"Their system: {anchor}\n"
        f"Generate ONE follow-up that asks for the mechanism specifically — "
        f"'In [their specific implementation], what did that look like concretely?'\n"
        "Return only the question. One sentence."
    )
    result = await self.llm.complete_small(prompt, max_tokens=120)
    return self._clean_question_output(result)
```

### 7e — Coverage Route Selection in Orchestrator

**File: `backend/services/orchestrator.py`** — in `_run_background_pipeline()`, add coverage routing logic for Phase 4 (turns 5-9):

```python
if turn_number >= 5 and state.get("coverage_map"):
    from backend.models.coverage_map import AnswerCoverageMap
    cmap = AnswerCoverageMap.from_dict(state["coverage_map"])

    last_dim_id = state.get("_last_coverage_dim_id")
    last_recovery = state.get("_last_coverage_recovery_depth")

    if last_dim_id and last_recovery == "surface":
        # Depth-of-recovery follow-up
        followup = await self.followup_agent.generate_coverage_depth_probe(
            dimension_id=last_dim_id,
            coverage_map=cmap,
            candidate_surface_response=text,
            state=state,
        )
        state["_last_coverage_dim_id"] = None
        state["_last_coverage_recovery_depth"] = None
    else:
        unsurfaced = cmap.unsurfaced_dimensions()
        if unsurfaced:
            # Sort by weight — surface most important gaps first
            unsurfaced.sort(key=lambda d: d.weight, reverse=True)
            next_dim = unsurfaced[0]
            next_dim.surfacing_attempted = True
            state["_last_coverage_dim_id"] = next_dim.id
            state["coverage_map"] = cmap.to_dict()

            followup = await self.followup_agent.generate_coverage_surface(
                dimension_id=next_dim.id,
                coverage_map=cmap,
                state=state,
            )
        else:
            # All dimensions surfaced — normal sprint progression
            followup = await self.followup_agent.generate_sprint_question(state=state)
```

### 7f — Coverage Evaluation: Classify Each Dimension

After the candidate responds to a surfacing question, classify coverage state. This runs as part of the background pipeline.

**File: `backend/services/orchestrator.py`** — add helper:

```python
async def _evaluate_coverage_dimension(
    self,
    dimension_id: str,
    coverage_map_dict: dict,
    candidate_response: str,
) -> tuple[str, str]:
    """
    Returns (coverage_state, recovery_depth).
    coverage_state: "voluntary" | "recovered_deep" | "recovered_surface" | "missed" | "incorrect"
    recovery_depth: "deep" | "surface" | None
    """
    from backend.models.coverage_map import AnswerCoverageMap
    cmap = AnswerCoverageMap.from_dict(coverage_map_dict)
    dim = next((d for d in cmap.dimensions if d.id == dimension_id), None)
    if not dim:
        return "missed", None

    prompt = (
        f"Interview dimension: {dim.label}\n"
        f"Description: {dim.description}\n"
        f"Expected approaches (any of these count): {', '.join(dim.expected_approaches)}\n\n"
        f"Candidate response: {candidate_response}\n\n"
        "Did the candidate address this dimension?\n"
        "- full: addressed with specific mechanism or implementation detail\n"
        "- partial: named the concept but couldn't explain how to implement\n"
        "- not_covered: didn't address it at all when prompted\n"
        "- incorrect: addressed it but with a conceptual error\n"
        "Use semantic matching — different terminology is fine if the concept is correct.\n"
        'Return JSON: {"coverage": "full|partial|not_covered|incorrect", "reason": "one line"}'
    )
    raw = await self.llm.complete_small(prompt, max_tokens=100)
    data = self.llm.extract_json(raw) or {}
    coverage = data.get("coverage", "not_covered")

    state_map = {
        "full": ("recovered_deep", "deep"),
        "partial": ("recovered_surface", "surface"),
        "not_covered": ("missed", None),
        "incorrect": ("incorrect", None),
    }
    return state_map.get(coverage, ("missed", None))
```

---

## Layer 8 — Coverage Portrait Evaluation Output

Once the `AnswerCoverageMap` is scored, the evaluation output format expands to the coverage portrait.

### Verdict Tier System

**File: `backend/agents/evaluation_agent.py`** — replace the LLM-generated `hire_recommendation` with the `compute_hire_recommendation()` function from Layer 6/D1.

The verdict tiers:

| Verdict | Condition |
|---|---|
| `STRONG_HIRE` | coverage_score > 0.75, domain_score > 0.80 |
| `HIRE` | coverage_score > 0.55, domain_score > 0.65 |
| `MAYBE` | coverage_score > 0.35, domain_score 0.45-0.65 |
| `NO_HIRE` | coverage_score > 0.45, domain_score < 0.40, confirmed gaps even when prompted |
| `CLAIM_RISK_FLAG` | Confirmed discrepancy on core claims — appended to any verdict |
| `INSUFFICIENT_DATA` | coverage_score < 0.35 OR disengagement forced early exit |

### Extended Evaluation Output Schema

**File: `backend/agents/evaluation_agent.py`** — extend `score_full_interview()` return dict with coverage portrait fields:

```python
# After computing coverage from coverage_map (if available):
if coverage_map:
    cmap = AnswerCoverageMap.from_dict(coverage_map)
    cmap.compute_coverage_score()

    voluntary = [d.label for d in cmap.dimensions if d.coverage_state == "voluntary"]
    recovered = [d.label for d in cmap.dimensions if d.coverage_state in ("recovered_deep", "recovered_surface")]
    missed = [d.label for d in cmap.dimensions if d.coverage_state == "missed"]
    incorrect = [d.label for d in cmap.dimensions if d.coverage_state == "incorrect"]

    coverage_portrait = {
        "coverage_score": cmap.coverage_score,
        "coverage_confidence": cmap.coverage_confidence,
        "primary_domain": {
            "voluntary_coverage": voluntary,
            "recovered_coverage": recovered,
            "missed_coverage": missed,
            "incorrect_coverage": incorrect,
            "domain_score": cmap.coverage_score,
        },
    }
else:
    coverage_portrait = None

return {
    **existing_fields,
    "coverage_portrait": coverage_portrait,
    "hire_recommendation": hire_recommendation,      # from compute_hire_recommendation()
    "confidence_score": confidence_score,            # from compute_confidence()
    "verdict_basis": "coverage_portrait" if coverage_portrait else "weakness_aggregation",
    "verdict_confidence_basis": _build_verdict_explanation(
        coverage_portrait, hire_recommendation, disengagement_triggered,
    ),
}
```

### Report Page Update

**File: `app/report/[session_id]/page.tsx`** — add coverage portrait section:

```typescript
interface CoveragePortrait {
  coverage_score: number;
  coverage_confidence: number;
  primary_domain: {
    voluntary_coverage: string[];
    recovered_coverage: string[];
    missed_coverage: string[];
    incorrect_coverage: string[];
    domain_score: number;
  };
}

interface Report {
  // ... existing fields ...
  coverage_portrait?: CoveragePortrait;
  verdict_basis?: string;
  verdict_confidence_basis?: string;
}
```

In the JSX, add a "Coverage Portrait" section when `report.coverage_portrait` is present:

```tsx
{report.coverage_portrait && (
  <section>
    <h2>Knowledge Coverage</h2>
    <p>Coverage: {Math.round(report.coverage_portrait.coverage_score * 100)}% of expected dimensions</p>
    {report.coverage_portrait.primary_domain.voluntary_coverage.length > 0 && (
      <div>
        <h3>Demonstrated Voluntarily</h3>
        <ul>{report.coverage_portrait.primary_domain.voluntary_coverage.map(l => <li key={l}>{l}</li>)}</ul>
      </div>
    )}
    {report.coverage_portrait.primary_domain.recovered_coverage.length > 0 && (
      <div>
        <h3>Recovered When Prompted</h3>
        <ul>{report.coverage_portrait.primary_domain.recovered_coverage.map(l => <li key={l}>{l}</li>)}</ul>
      </div>
    )}
    {report.coverage_portrait.primary_domain.missed_coverage.length > 0 && (
      <div>
        <h3>Not Addressed</h3>
        <ul>{report.coverage_portrait.primary_domain.missed_coverage.map(l => <li key={l}>{l}</li>)}</ul>
      </div>
    )}
    {report.verdict_confidence_basis && (
      <p className="verdict-basis">{report.verdict_confidence_basis}</p>
    )}
  </section>
)}
```

---

## Layer 9 — P3 Polish and Calibration

These are lower-priority items. Implement after P0-P2 is stable.

### Context-Aware Filler Phrases

**2026-05-07 Yash final decision:** Context-aware TTS fillers are NOT in the current release. Keep the live system on the simple default filler pool. The state-aware selection below is future-version backlog only.

**File: `backend/services/tts_service.py`** — future-version idea: the current filler phrases ("Interesting.", "Got it.", etc.) are context-free. Replace with state-aware selection:

```python
FILLER_PHRASES_BY_CONTEXT = {
    "technical_answer": ["Right.", "Okay.", "Got it.", "Sure."],
    "admission": ["Appreciate the honesty.", "Got it.", "Okay."],
    "confusion": ["Alright.", "Let me ask it differently."],
    "default": ["Interesting.", "Got it.", "Alright.", "I see.", "Right.", "Sure."],
}
```

Pass context to `get_filler_payload()` and select from the appropriate list.

### Candidate Name in Report

**File: `backend/agents/resume_agent.py`** — the resume parser should extract `candidate_name`. Add to the output schema if not already present.

**File: `backend/api/routes.py`** — pass `candidate_name` from session state into the report response. Display in `app/report/[session_id]/page.tsx` header.

### Interview Map Quality Gate

**File: `backend/services/interview_map.py`** — `audit_map_quality()` function (pre-interview check):

```python
def audit_map_quality(interview_map: dict) -> list[str]:
    """
    Returns a list of quality warnings. Called before session start.
    If warnings exist, log them but don't block — just flag.
    """
    warnings = []
    focus_areas = interview_map.get("focus_areas", [])
    if not focus_areas:
        warnings.append("No focus areas generated")
        return warnings

    primary = focus_areas[0]
    opener = primary.get("tracks", [{}])[0].get("opener", "") if primary.get("tracks") else ""
    if len(opener.split()) > 30:
        warnings.append(f"Primary opener is too long ({len(opener.split())} words)")

    # Check for signal_weight being present
    for fa in focus_areas:
        for track in fa.get("tracks", []):
            for dim in track.get("dimensions", []):
                if "signal_weight" not in dim:
                    warnings.append(f"Dimension '{dim.get('id')}' missing signal_weight")
                    break

    return warnings
```

### Graceful Close Turn Generation

**File: `backend/agents/followup_agent.py`** — add `generate_graceful_close()`:

```python
async def generate_graceful_close(self, state: dict, turn_in_close: int) -> str:
    """Generates Phase 6 close questions (turns 14-15)."""
    if turn_in_close == 0:
        return (
            "Alright, we're almost done — before we finish, is there anything about your work "
            "or what you've been building that you wanted to talk about that we didn't get to?"
        )
    else:
        return (
            "Last one — what kind of work are you most excited to be doing in the next role? "
            "Like what's the thing you really want to get into?"
        )
```

### Postgres Sessions Endpoint — Full Report Unpack

Already addressed in Layer 2 Bug 1. Ensure the `app/dashboard/page.tsx` displays `coverage_score` and `verdict_basis` when available from the new schema.

---

## Layer 10 — Dependency Graph and Shipping Order

```
LAYER 0 (Philosophy)        → Independent. Ship first — changes all prompts.
LAYER 1 (RAG Removal)       → Independent. Ship second — reduces dead code.
LAYER 2 (Bug Fixes)         → Independent of all others. Can ship anytime.

LAYER 3 (Map Fixes):
  A1 (target_role thread)   → Prerequisite for A2, A3
  A2 (anchor selection)     → Requires A1
  A3 (track system prompt)  → Requires A1; provides foundation for A6
  A4 (repair loop fix)      → Independent of A1-A3, ships alone
  A5 (budget allocation)    → Independent, ships alone
  A6 (signal_weight)        → Requires A3 to generate the field

LAYER 4 (Orchestrator Fixes):
  B4 (candidate_state init) → Prerequisite for B1, B2, Layer 5
  B1 (skip detection)       → Requires B4
  B2 (fatigue ratio)        → Requires B4
  B3 (warm guard)           → Independent — 2 lines, ships alone first

LAYER 5 (Candidate State):
  candidate_state.py        → Requires B4
  Disengagement thresholds  → Requires candidate_state.py + B4
  Communication mode        → Requires candidate_state.py
  Confession pivot          → Requires disengagement thresholds

LAYER 6 (Evaluation):
  D1 (hire_recommendation)  → Independent of all layers — pure Python functions
  D2 (analyst rubric)       → Requires A1 (target_role available)
  D3 (reasoning feedback)   → Requires B4 (state dict structure)

LAYER 7 (New Architecture):
  coverage_map.py           → Independent
  application_agent.py      → Requires coverage_map.py
  STAR-lite extraction      → Requires application_agent.py + B4
  Coverage routing          → Requires STAR-lite + coverage_map.py
  Coverage evaluation       → Requires coverage routing

LAYER 8 (Coverage Portrait): → Requires LAYER 7 complete
LAYER 9 (Polish):           → After LAYER 8 stable
```

### Recommended Shipping Batches

**Batch 1 (Ship immediately — no regressions possible):**
- Layer 0 terminology audit
- Layer 1 RAG removal
- Layer 2 Bug 1 (dashboard), Bug 2 (admin auth), Bug 3-4 (report rendering)
- B3 (warm guard — 2 lines)

**Batch 2 (Map quality — one PR):**
- A4 (repair loop fix) — standalone
- A5 (budget allocation) — standalone
- A1 + A2 (target_role thread + anchor override)

**Batch 3 (Map depth + routing — one PR):**
- A3 (track system prompt function)
- A6 (signal_weight)
- B4 + B1 + B2 (candidate_state init + skip + fatigue ratio)

**Batch 4 (Candidate State Layer — one PR):**
- `candidate_state.py` new file
- Disengagement thresholds in orchestrator
- Communication mode detection
- Confession pivot + FollowUpAgent `communication_mode` support

**Batch 5 (Evaluation Integrity — one PR):**
- D1 (`compute_hire_recommendation()`, `compute_confidence()`)
- D2 (analyst rubric)
- D3 (ReasoningBehaviorAgent → live feedback)

**Batch 6 (New Architecture — staged rollout):**
- `coverage_map.py`
- `application_agent.py`
- STAR-lite extraction + `_generate_application_transfer()`
- Coverage routing in orchestrator
- Coverage evaluation classifier

**Batch 7 (Coverage Portrait — complete the loop):**
- Extended evaluation output
- Report page coverage portrait section
- Dashboard coverage_score display

---

## Layer 11 — What Does NOT Change

These components are confirmed correct. Do not touch them during this implementation.

| Component | Status | Reason |
|---|---|---|
| Two-track architecture (fast path + background pipeline) | Keep | Correct design, no issues found |
| `select_from_trajectory_map_detailed()` | Keep (add weight ordering in A6) | Works correctly |
| Discrepancy detection (DiscrepancyAgent) | Keep | Moves from interview driver → background signal |
| Sprint/persona structure (curious_lead → socratic_mentor → senior_peer) | Keep | Maps cleanly to Orientation → STAR-lite → Application |
| `PERSONA_PROMPTS` content | Keep for P0 | Already correctly warm |
| `EvaluationAgent.score_full_interview()` structure | Keep, extend | Already has INSUFFICIENT_DATA, untested_dimensions, coverage_note |
| `SessionManager` | Keep | 30-line implementation is clean and correct |
| Redis session management | Keep | Unchanged by all layers |
| ProvenHire integration | Keep | Untouched by all design changes |
| `SPRINT_OPENERS[1]` | Keep | Already correctly warm |
| TTS pre-generation pipeline | Keep | `pre_generate()` + `get_prepped()` pattern is correct |
| Deepgram configuration | Keep | Nova-3 + NER + utterance_end_ms=2800 is correct |
| Background pipeline parallelism | Keep | Correct use of `asyncio.gather()` |
| `_pipeline_inflight` guard | Keep | Prevents duplicate background runs |

---

## Appendix A — Files Modified by Layer

| File | Layers | Type |
|---|---|---|
| `backend/agents/weakness_agent.py` | 0 | Modify — terminology + `continue_probing` field |
| `backend/agents/followup_agent.py` | 0, 5, 7d | Modify — terminology, communication_mode, coverage routes |
| `backend/agents/evaluation_agent.py` | 6 | Modify — hire_recommendation extracted to Python |
| `backend/agents/application_agent.py` | 7b | **NEW** |
| `backend/services/orchestrator.py` | 3-A1, 4-B1/B2/B3/B4, 5, 7c/7e | Modify — many surgical additions |
| `backend/services/interview_map.py` | 3-A1/A2/A3/A4/A5/A6 | Modify — role-aware generation |
| `backend/state/candidate_state.py` | 5 | **NEW** |
| `backend/models/coverage_map.py` | 7a | **NEW** |
| `backend/api/routes.py` | 2 | Modify — dashboard unpack, admin auth |
| `backend/main.py` | 1 | Modify — remove RAG startup |
| `backend/rag/faiss_store.py` | 1 | **DELETE** |
| `backend/rag/question_bank.py` | 1 | **DELETE** |
| `app/report/[session_id]/page.tsx` | 2, 8 | Modify — report language, coverage portrait |
| `app/dashboard/page.tsx` | 2 | Modify — fix recommendation derivation |

---

## Appendix B — New Environment Variables

| Variable | Required By | Purpose |
|---|---|---|
| `ANTIGRAVITY_ADMIN_SECRET` | Layer 2 / Bug 2 | Auth for `/admin/redis-dump` |
| _(Remove)_ `FAISS_*`, `SENTENCE_TRANSFORMERS_*` | Layer 1 | Not needed after RAG removal |

No other new env vars required for P0-P1. The coverage portrait and application agent use existing LLM infrastructure (LLMRouter / OpenRouter).

---

*Every change in this document traces to a confirmed session failure or a specific design decision in INTERVIEW_REDESIGN.md §9/§13 or REDESIGN_SPEC.md. Nothing here is speculative.*
