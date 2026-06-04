"""
Resume-grounded interview map / trajectory bank.

This module builds a structured, resume-specific LLM-authored spine for the interview.
It is additive to the live weakness/discrepancy/speculative pipeline:

- live pipeline wins when it has a strong next move
- trajectory map wins when runtime generation is weak, generic, or not ready

The emphasis here is robustness:
- LLM-authored focus extraction from parsed resume
- per-focus generation so we do not collapse into one giant brittle JSON blob
- structured branches by sprint + answer state
- fail-closed startup behavior when the LLM contract is invalid
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.config.env_runtime import env_first
from backend.models.llm_router import LLMRouter, _load_json_lenient
from backend.services.surface_plan import (
    SURFACE_PLANNER_MODEL,
    compact_surface_plan_for_prompt,
    generate_surface_plan_v2,
    surface_plan_alignment_warnings,
)


# ── Pydantic output schemas ───────────────────────────────────────────────────
# These enforce structure on LLM-generated JSON. Validation errors are caught
# and converted to partial-recovery dicts — never raised to callers.

class _DimensionSchema(BaseModel):
    id: str = ""
    label: str = ""
    resume_anchor: str = ""
    surface: str = ""
    mechanism: str = ""
    boundary: str = ""
    signal_weight: float = 1.5

class _SubFocusPlanSchema(BaseModel):
    label: str = ""
    sub_focus_key: str = ""
    surface_kind: str = ""
    role_relevance_weight: float = 1.5
    profile_importance_weight: float = 1.5
    evidence_strength: float = 1.5
    claim_risk: float = 1.5
    coverage_value: float = 1.5
    why_priority: str = ""
    source_snippets: list[str] = Field(default_factory=list)

class _RecoverySchema(BaseModel):
    short_answer: str = ""
    honest_gap: str = ""
    claim_conflict: str = ""
    metric_risk: str = ""
    overclaim_risk: str = ""
    bridge: str = ""

class _QuestionLadderItemSchema(BaseModel):
    posture: str = ""
    main_question: str = ""
    signal_goal: str = ""
    expected_space: list[str] = Field(default_factory=list)
    follow_up_if_shallow: str = ""
    follow_up_if_strong: str = ""
    information_gain: str = "medium"
    voice_complexity: str = "medium"

class _TrackSchema(BaseModel):
    opener: str = ""
    dimensions: list[_DimensionSchema] = Field(default_factory=list)
    recovery: _RecoverySchema = Field(default_factory=_RecoverySchema)
    candidate_q4_options: list[str] = Field(default_factory=list)
    question_ladder: list[_QuestionLadderItemSchema] = Field(default_factory=list)

class _LaunchLiteQuestionSchema(BaseModel):
    posture: str = ""
    main_question: str = ""
    signal_goal: str = ""
    expected_space: list[str] = Field(default_factory=list)
    information_gain: str = "high"
    voice_complexity: str = "low"

class _LaunchLiteDimensionSchema(BaseModel):
    id: str = ""
    label: str = ""
    resume_anchor: str = ""
    question: str = ""
    signal_goal: str = ""
    surface_kind: str = "breadth"
    signal_weight: float = 2.0

class _LaunchTrackLiteSchema(BaseModel):
    frame: _LaunchLiteQuestionSchema = Field(default_factory=_LaunchLiteQuestionSchema)
    clarify: _LaunchLiteQuestionSchema = Field(default_factory=_LaunchLiteQuestionSchema)
    explore: _LaunchLiteQuestionSchema = Field(default_factory=_LaunchLiteQuestionSchema)
    pressure: _LaunchLiteQuestionSchema = Field(default_factory=_LaunchLiteQuestionSchema)
    recover_short_answer: str = ""
    dimensions: list[_LaunchLiteDimensionSchema] = Field(default_factory=list)

class _FocusAreaPlanSchema(BaseModel):
    label: str = ""
    focus_key: str = ""
    anchor_context: str = ""
    sub_focuses: list[Any] = Field(default_factory=list)
    resume_snippets: list[str] = Field(default_factory=list)
    why_priority: str = ""

class _FocusPlanSchema(BaseModel):
    focus_areas: list[_FocusAreaPlanSchema] = Field(default_factory=list)

class _FocusReviewSchema(BaseModel):
    focus_key: str = ""
    label: str = ""
    score: float = 6.0
    opener_issue: str = ""
    issues: list[str] = Field(default_factory=list)

class _RepairTargetSchema(BaseModel):
    focus_key: str = ""
    path: str = ""
    issue: str = ""
    instruction: str = ""
    severity: str = "minor"
    issue_scope: str = "field_level"
    action: str = "surgical_repair"
    reason: str = ""


class _CriticIssueSchema(BaseModel):
    issue_scope: str = "field_level"
    focus_key: str = ""
    path: str = ""
    severity: str = "minor"
    action: str = "surgical_repair"
    reason: str = ""

class _CriticSchema(BaseModel):
    ready: bool = False
    overall_score: float = 6.0
    top_two_score: float = 6.0
    opener_quality_score: float = 6.0
    dimension_depth_score: float = 6.0
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)
    focus_reviews: list[_FocusReviewSchema] = Field(default_factory=list)
    typed_issues: list[_CriticIssueSchema] = Field(default_factory=list)
    repair_targets: list[_RepairTargetSchema] = Field(default_factory=list)


class MapPreparationError(RuntimeError):
    """Map-prep failure that preserves the evidence needed for debugging."""

    def __init__(self, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def _validate_schema(raw: Any, model_cls: type[BaseModel]) -> tuple[dict, list[str]]:
    """
    Validate `raw` against `model_cls`. Returns (validated_dict, schema_errors).
    Never raises. On partial failure, falls back field-by-field so valid data is kept.
    """
    if not isinstance(raw, dict):
        if isinstance(raw, str):
            parsed = _load_json_lenient(raw)
            if isinstance(parsed, dict):
                raw = parsed
            else:
                return model_cls().model_dump(), ["raw output was not valid JSON object"]
        else:
            return model_cls().model_dump(), [f"raw output type {type(raw).__name__} not a dict"]

    try:
        return model_cls.model_validate(raw).model_dump(), []
    except ValidationError as exc:
        errors = [f"{e['loc']}: {e['msg']}" for e in exc.errors()]
        # Partial recovery: start from model defaults, override with valid fields
        defaults = model_cls().model_dump()
        for key, value in raw.items():
            if key not in defaults:
                continue
            try:
                partial = model_cls.model_validate({key: value})
                defaults[key] = getattr(partial, key)
            except (ValidationError, Exception):
                pass
        return defaults, errors


_VALID_BRANCHES = {
    "if_strong",
    "if_vague",
    "if_honest_gap",
    "if_claim_conflict",
    "if_short_answer",
    "bridge_to_next_focus",
}

_SPRINT_KEYS = ("sprint_1", "sprint_2", "sprint_3")
_SPRINT_KEY = {1: "sprint_1", 2: "sprint_2", 3: "sprint_3"}

_BRANCH_PRIORITY_DEFAULT = [
    "if_vague",
    "if_strong",
    "bridge_to_next_focus",
]
_BRANCH_PRIORITY_SHORT = [
    "if_short_answer",
    "if_vague",
    "if_strong",
    "bridge_to_next_focus",
]
_BRANCH_PRIORITY_ADMISSION = [
    "if_honest_gap",
    "if_vague",
    "if_strong",
    "bridge_to_next_focus",
]
_BRANCH_PRIORITY_DISCREPANCY = [
    "if_claim_conflict",
    "if_vague",
    "if_strong",
    "bridge_to_next_focus",
]

ROUTE_SHORT_ANSWER_RESCUE = "trajectory_map_short_answer_rescue"
ROUTE_HONESTY_PROBE = "trajectory_map_honesty_probe"
ROUTE_FOLLOWUP = "trajectory_map_followup"
ROUTE_BRIDGE = "trajectory_map_bridge"
ROUTE_CHALLENGE = "trajectory_map_challenge"
ROUTE_STRONG = "trajectory_map_strong_followup"
ROUTE_OPENER = "trajectory_map_opener"
ROUTE_METRIC_PROBE = "trajectory_map_metric_probe"
ROUTE_OVERCLAIM_PROBE = "trajectory_map_overclaim_probe"
ROUTE_SURFACE = "trajectory_map_surface"
ROUTE_MECHANISM = "trajectory_map_mechanism"
ROUTE_BOUNDARY = "trajectory_map_boundary"

_BRANCH_TO_ROUTE = {
    "if_short_answer": ROUTE_SHORT_ANSWER_RESCUE,
    "if_honest_gap": ROUTE_HONESTY_PROBE,
    "if_claim_conflict": ROUTE_CHALLENGE,
    "bridge_to_next_focus": ROUTE_BRIDGE,
    "if_strong": ROUTE_STRONG,
    "if_vague": ROUTE_FOLLOWUP,
}

_DEPTH_TO_ROUTE = {
    1: ROUTE_SURFACE,
    2: ROUTE_MECHANISM,
    3: ROUTE_BOUNDARY,
}

_OVERCLAIM_VOCAB: frozenset[str] = frozenset({
    "manifold", "diffusion", "conditioning", "steering",
    "quantization", "distillation", "fine-tuning", "finetuning",
    "alignment", "rlhf",
})


_TRACK_SYSTEM_BASE = """You are an expert technical interviewer designing a precision interview track for one specific resume focus area.

Your goal: generate questions that reveal whether the candidate genuinely understands and can apply what they claimed — not whether they can recall facts or recite process.

The track has four layers:
1. question_ladder — voice-first interview rhythm: frame, clarify, explore, pressure, synthesize, recover
2. dimensions — 2–5 assessment axes grounded in resume evidence, each with surface/mechanism/boundary escalation. Use 3+ when the focus genuinely has enough distinct surfaces; 2 is acceptable only with a complete high-information ladder.
3. opener, recovery, and candidate_q4_options — legacy compatibility views derived from the ladder/dimensions, not separate creative targets

Output contract:
- Return one JSON object only. The root object must directly contain "question_ladder", "opener", "dimensions", "recovery", and "candidate_q4_options".
- Do not wrap the object in {"track": ...}, arrays, markdown, prose, or commentary.
- Every generated question must be a string. question_ladder items are objects containing question strings.
- Do not create a different interview plan in opener/recovery. The ladder is the real plan; opener should mirror the frame/clarify question, and recovery should mirror the recover/pressure/clarify ladder items.

UNIVERSAL QUESTION QUALITY RULES — apply to every question regardless of role:

Every question must:
- Reference a specific number, system name, outcome, or decision from the anchor claim
- Have a clearly distinguishable strong answer vs. weak answer
- Sound like a senior practitioner asking it in a real conversation — not an AI generating interview questions
- Be answerable in under 90 seconds

Never generate questions that:
- Test memory of sequence: "What was the first X you defined/built/chose?"
- Name the solution you are looking for: "Did you consider caching?" "Did you use indexing?"
- Assume failure without a specific anchor: "What went wrong with X?" (without naming what X is)
- Ask about general process: "How do you typically approach X?" — want specific instances not general answers
- Compound two questions into one sentence
- Exceed 40 words
- Start with "Can you tell me about..." or "Could you explain..."
- Use accusatory phrasing like "prove", "caught", "fake", "lying", or a hostile "actually".
- Sound abstract, overly polished, or vocabulary-heavy. Prefer simple spoken English for Indian candidates.
- Use inflated analytics jargon when plain words work. Avoid phrases like "maturity window", "temporal fast-forward", "incremental revenue", "analytical integrity", "cohort health", and "lifetime value" unless the resume itself uses them.
- If you mean "how long did you wait before counting conversion", say "time window". If you mean "payments happened earlier", say that directly.

The pattern every question must follow:
[specific element from their resume claim] + [consequence, challenge, or extension appropriate to the role domain]

question_ladder rules:
- Generate exactly 6 items with postures: frame, clarify, explore, pressure, synthesize, recover.
- frame starts the claim gently and gives a light answer lane; it must not sound like prosecution.
- frame and synthesize should often include 2-3 candidate-facing answer lanes when that reduces ambiguity, but never make it feel like multiple choice. Always include an opening such as "or was there something else?" / "what else was in play?" / "or was another reason more important?"
- clarify asks for definition, denominator, ownership boundary, or scope.
- explore asks how they reasoned through the work.
- pressure asks one sharp challenge only after context exists.
- synthesize uses plain language to check what is certain vs uncertain; no evaluator jargon. Prefer explicit options over abstract phrasing.
- recover is a small follow-up for shallow, vague, or evasive answers.
- main_question must be 18–35 words whenever possible, one question mark, one clear ask.
- expected_space must list 2–4 internal answer areas, not a script for the candidate.
- follow_up_if_shallow must be a small same-thread question, not a new topic. Use it when the candidate only agrees with the options without reasoning through them.
- follow_up_if_strong should deepen only if the candidate already gave a good answer.
- information_gain must be "high" for at least 3 items per track.
- voice_complexity must be "low" or "medium" for at least 4 items per track.
- Do not turn every item into pressure. Pressure must be timed and earned.
- Do not mark a question voice_complexity="low" if it contains specialist wording that a normal candidate may not understand when spoken aloud.
- Do not assume hidden implementation details from resume wording. If the source snippets do not explicitly mention an internal mechanism, ask first what they personally owned or how the system worked at a high level.
- Technical depth must be earned from the candidate's answer. Start with frame/clarify/explore, then ask pressure or implementation-specific probes only after ownership and operating level are clear.
- For technical resumes, do not jump from a product phrase to internals like engine parameters, internal model parameters, latent vectors, diffusion noise, routing algorithms, or optimizer behavior unless the snippets or candidate answer explicitly mention them.

Guided-question examples below are STYLE EXAMPLES ONLY. Adapt to the actual resume/role; never copy trial, conversion, or product words unless the candidate actually has that claim.
- Good analyst frame: "When you moved the trial from 7 days to 1 day, were you mainly trying to improve paid conversion, reduce low-intent trials, test urgency, or was there something else? Talk me through how you framed that decision."
- Good engineering frame: "When you redesigned the inference path, were you mainly reducing latency, memory use, failure rate, or was another constraint more important? Talk me through how you framed that decision."
- Good synthesize: "From that work, what should we carry forward as a fair conclusion, and what should we avoid claiming too strongly?"
- Good synthesize: "If this result came up in a review, what concrete check would you show first to explain what happened?"
- Bad synthesize: "Which part are you most confident in?" Self-rating; it lets the candidate perform certainty without showing evidence.
- Bad synthesize: "What part of the conclusion are you most confident in?" Too abstract and self-evaluative.
- Bad frame: "Was it conversion, low-intent trials, or urgency?" Too closed; it invites choosing one option instead of explaining the reasoning space.

Opener rules:
- 20–30 words, directed at the anchor claim
- Include company/experience context: "At [company], you [outcome] — walk me through..."
- Invite narration of the specific work — do NOT ask a mechanism question as the opener
- "Walk me through" and "tell me about" ARE allowed in openers for non-analyst roles — they are the correct framing for narrative-first entry
- The opener must invite the candidate to narrate in their own words before any depth probing begins

Dimension rules (generate 2–5, each grounded in actual resume evidence):
- surface: confirms the concept exists in their experience — basic familiarity is enough to answer
- mechanism: tests whether they understand WHY it works — genuine depth required
- boundary: unanswerable without real hands-on ownership — tests edges, failures, constraints
- Each probe must name the specific artifact, technology, number, or result from resume_anchor
- Probes must escalate: surface < mechanism < boundary in required depth
- Do not repeat angles across dimensions
- signal_weight 1.0–3.0: rate each dimension by how much a weak answer reveals about role fitness
  3.0 = directly tests the core claim; weak answer invalidates the resume bullet
  2.0 = tests adjacent understanding; weak answer is meaningful signal
  1.0 = confirms familiarity; weak answer is a minor flag only

candidate_q4_options rules (generate 3–4 standalone questions):
- These are alternative Q4 questions for adaptive selection at runtime
- Each targets a different aspect of the anchor claim
- Cover the most likely gaps based on what candidates typically under-explain about this type of claim
- Each must follow the universal quality rules above — specific, consequential, human-sounding
- These are standalone questions, not surface/mechanism/boundary levels

Recovery rules (one set covers the entire focus area):
- short_answer: rescue a 1–8 word answer by naming the specific artifact and asking one concrete thing
- honest_gap: reward admission, pivot to what they do understand in this focus area
- claim_conflict: confront a specific contradiction between their answer and the resume claim
- metric_risk: when they cite a number without methodology — ask for baseline, measurement method, denominator
- overclaim_risk: when they use domain vocabulary without operational grounding — ask what that term meant in the part they personally handled, without assuming they owned every internal layer
- bridge: natural pivot that explicitly names the next focus area

Output: return ONLY JSON. No commentary, no markdown fences, no placeholders."""

_TRACK_SYSTEM_ANALYST_OVERRIDE = """

ROLE-TYPE OVERRIDE — Product Analyst / PM / Growth role:

For this role, depth means analytical reasoning quality — not implementation fidelity.

QUESTION CHALLENGE TYPES for analyst roles (use these patterns for dimensions and candidate_q4_options):
- causal_validity (signal_weight 3.0): "[Specific outcome] happened — [named confound or alternative explanation] was also present. How do you know [X] caused it and not [the confound]?"
- metric_definition (signal_weight 3.0): "That [specific number] — what was the exact definition? What was in the denominator, what was the time window, what counted as [the event]?"
- scenario_tension (signal_weight 2.5): "Suppose [metric they improved] kept going up but [a related metric that should move with it] dropped — what would you investigate first and why?"
- decision_reasoning (signal_weight 2.5): "What specific data point convinced you [their exact decision] was the right call — and what was the strongest alternative you ruled out?"
- business_impact (signal_weight 2.0): "What did [their specific work] actually change in how the team made decisions — give me one decision that was made differently because of it?"

dimensions MUST include at least one causal_validity question and one metric_definition question as the first two dimensions. These fire regardless of candidate fluency.

Opener: ask for the candidate's decision frame or metric definition in plain language. NEVER "walk me through" or "tell me about" — these are too broad for analyst roles. Do not make the opener a full pressure test; pressure belongs in the pressure ladder item after frame/clarify.

TWO PATTERNS — pick based on the evidence available:

Pattern A — Contradiction available (two claims in the anchor are in tension):
Format: "At [company], you [specific outcome] — [named contradiction]. Before we go deeper, [what explains the gap] and [what would make you wrong]?"
Example: "At GrowFast, your churn model had 44% recall — meaning most churners were never flagged — yet the resume claims a 35% churn reduction. Before we go deeper, what explains that gap, and what would make you wrong?"

Pattern B — No contradiction (resume claims are internally consistent):
Take the most specific number in the anchor. Identify the ONE assumption or decision that number rests on that the candidate made a choice about. Challenge that decision directly.
Format: "At [company], you [specific outcome with the number] — before we go anywhere else, [specific assumption the number rests on] — [ask them to defend or name the source of that assumption]."
Example: "At MindFul, you ran the streak notification test at 0.85 power — before we go anywhere else, what effect size did you input when you ran that power calculation, and where did that assumption come from?"
The opener must guide them toward a specific analytical decision, not ask for a broad story. Every clean number has a latent assumption underneath it — find it, but ask it in plain spoken language.

The opener MUST name a specific number from the resume AND ask for the decision, denominator, or guardrail behind it.

HANDLING "ARCHITECTED / BUILT / IMPLEMENTED" CLAIMS ON AN ANALYST RESUME:
When a PA claims to have built something, the right probe is at the INTERSECTION of their build decisions and their analytical conclusions — not pure implementation and not pure outcome. Their build decisions are upstream of their analytical results. Probe whether they understand that dependency.

WRONG (pure implementation — tests engineering, not analyst fitness):
"What events did you define in your taxonomy?" / "What properties did you attach to a session-start event?" / "What schema did you design?"
These test instrumentation craft. A PA who got lucky with a clean schema can answer these. Irrelevant.

RIGHT (build-decision → analytical consequence):
"You designed the event schema from scratch — when the retention experiment showed lift, was there any instrumentation gap in what you built that made you less confident in the attribution? What would you have tracked differently?"
"You architected the event tracking — which property you chose NOT to capture early on forced a workaround when you needed to answer a product question later?"
These are unanswerable without both having built it AND having tried to use it under real analytical pressure. This is the signal.

The rule: implementation probes are valid for analysts ONLY when framed as "your build decision created a constraint or enabled a conclusion — what was it?" Isolated implementation questions with no analytical consequence are signal_weight 1.0 maximum.

Analyst signal_weight 3.0 goes to: causal attribution challenges, metric definition and denominator validity, decision reasoning under uncertainty, consequence of their own design choices on their analytical conclusions."""


_TRACK_SYSTEM_ENGINEER_GUIDE = """

ROLE-TYPE GUIDE — Software / Backend / Infrastructure / Full-stack Engineer:

Engineering openers should establish scope before pressure. A good opener asks what problem they were solving, what part they personally owned, or what made the system hard. It should not assume hidden internals from resume keywords.

QUESTION CHALLENGE TYPES for engineering roles (use these patterns):
- failure_mode (signal_weight 3.0): "In [their specific system] — what breaks first when [realistic load or failure condition]?"
- design_tradeoff (signal_weight 3.0): "You chose [their specific approach] — when is that the wrong call? What condition makes you not use it?"
- ownership_specificity (signal_weight 2.5): "Which part did you personally write, configure, or decide, and which parts came from libraries, teammates, or existing systems?"
- scale_behavior (signal_weight 2.0): "How does [their system] behave differently at [realistic scale increase — 10x, multi-region, concurrent writes]?"

Opener format: "You worked on [specific thing] at [company] — what problem were you solving, and what part did you personally own?" Use the company and system name from the resume."""


_TRACK_SYSTEM_ML_GUIDE = """

ROLE-TYPE GUIDE — ML Engineer / Data Scientist:

QUESTION CHALLENGE TYPES for ML/data science roles:
- distribution_shift (signal_weight 3.0): "What happens to [their model/system] when [realistic input distribution change]?"
- eval_integrity (signal_weight 3.0): "How did you know [their claimed result] was actually better — and not overfitting to [their test condition]?"
- generalization_boundary (signal_weight 2.5): "Where does [their approach] fail — what condition makes it the wrong choice for this problem?"
- statistical_validity (signal_weight 2.0): "What assumption does [their metric or result] break if [realistic violation of that assumption]?"

Opener: directed at the model or experiment they claimed. Invite them to describe what they were solving, what they personally owned, and why their approach fit. Do not ask about latent-space, diffusion, training-loop, or optimization internals unless the snippets explicitly mention them."""


_TRACK_SYSTEM_DATA_ENG_GUIDE = """

ROLE-TYPE GUIDE — Data Engineer / Analytics Engineer:

QUESTION CHALLENGE TYPES for data engineering roles:
- pipeline_failure (signal_weight 3.0): "What happens to [their pipeline] when [upstream schema change / late-arriving data / source outage]?"
- schema_decision (signal_weight 3.0): "You structured [their schema/model] that way — what query pattern breaks if you need to add [realistic new requirement]?"
- freshness_tradeoff (signal_weight 2.5): "In [their system] — how did you decide between [latency vs accuracy / cost vs freshness / batch vs streaming]?"
- failure_recovery (signal_weight 2.0): "When [their pipeline] fails mid-run — what state is left behind and how do you recover without double-counting?"

Opener: directed at the pipeline or data model they claimed to own."""


def _is_analyst_or_pm_role(role_type: str = "") -> bool:
    role_lower = role_type.lower()
    phrase_match = any(
        keyword in role_lower
        for keyword in (
            "analyst",
            "analytics",
            "product manager",
            "product analyst",
            "product lead",
            "product strategy",
            "product ops",
            "growth",
            "business analyst",
            "data analyst",
            "analytics manager",
            "research analyst",
            "marketing analyst",
            "operations analyst",
            "go-to-market",
            "gtm",
            "revenue ops",
            "strategy",
        )
    )
    return phrase_match or bool(re.search(r"\b(a?pm)\b", role_lower))


def _track_system_prompt_sections(role_type: str = "") -> list[tuple[str, str]]:
    """Return named prompt sections so schema, voice, and role guidance travel separately."""
    sections: list[tuple[str, str]] = [
        ("schema_voice_and_output_contract", _TRACK_SYSTEM_BASE),
    ]
    role_lower = (role_type or "").lower()
    if _is_analyst_or_pm_role(role_type):
        sections.append(("role_specific_guidance", _TRACK_SYSTEM_ANALYST_OVERRIDE))
    elif any(t in role_lower for t in ("data engineer", "analytics engineer", "data eng", "dbt", "pipeline")):
        sections.append(("role_specific_guidance", _TRACK_SYSTEM_DATA_ENG_GUIDE))
    elif any(t in role_lower for t in ("machine learning", "ml engineer", "data scientist", "research scientist")):
        sections.append(("role_specific_guidance", _TRACK_SYSTEM_ML_GUIDE))
    elif any(t in role_lower for t in ("backend", "software engineer", "full stack", "fullstack", "infrastructure", "platform")):
        sections.append(("role_specific_guidance", _TRACK_SYSTEM_ENGINEER_GUIDE))
    return sections


def _track_system_prompt(role_type: str = "") -> str:
    """Return the track system prompt with named sections kept explicit."""
    return "\n\n".join(
        f"### {name}\n{body.strip()}"
        for name, body in _track_system_prompt_sections(role_type)
        if body and body.strip()
    )


# Keep _TRACK_SYSTEM as an alias for callers that haven't been updated yet
_TRACK_SYSTEM = _TRACK_SYSTEM_BASE

_TRACK_USER_TEMPLATE = """Candidate background:
{resume_context}

Current focus area:
- Label: {label}
- Focus key: {focus_key}
- Resume anchor: {anchor_context}
{sub_focuses_block}- Exact resume snippets:
{resume_snippets}
- Next focus area (for bridge): {next_focus_label}
- Critic guidance: {repair_guidance}
{prior_track_context}
Return ONLY this JSON structure (no markdown, no commentary):
{{
  "question_ladder": [
    {{
      "posture": "frame",
      "main_question": "plain spoken question with a light answer lane",
      "signal_goal": "what this question is trying to learn",
      "expected_space": ["answer area 1", "answer area 2", "answer area 3"],
      "follow_up_if_shallow": "small same-thread depth probe if candidate only gives a shallow answer",
      "follow_up_if_strong": "deeper follow-up if the candidate already gave a strong answer",
      "information_gain": "high",
      "voice_complexity": "low"
    }}
  ],
  "opener": "targeted question 20-30 words — anchored to a specific number or decision from the resume — see system prompt for role-specific opener rules",
  "dimensions": [
    {{
      "id": "snake_case_dimension_id",
      "label": "short dimension label",
      "resume_anchor": "exact or near-exact resume claim this dimension probes",
      "surface": "question confirming basic familiarity — specific anchor from their claim + basic probe",
      "mechanism": "question requiring genuine depth — specific anchor + consequence or challenge",
      "boundary": "question unanswerable without real hands-on ownership — specific anchor + edge case or failure",
      "signal_weight": 2.0
    }}
  ],
  "candidate_q4_options": [
    "standalone Q4 question option A — targets one specific aspect of the anchor claim",
    "standalone Q4 question option B — targets a different aspect",
    "standalone Q4 question option C — targets a third aspect",
    "standalone Q4 question option D — targets the analytical reasoning or decision behind the claim"
  ],
  "recovery": {{
    "short_answer": "rescue for 1-8 word answers — names specific artifact, asks one concrete thing",
    "honest_gap": "reward honesty, pivot to what they do understand here",
    "claim_conflict": "confront the specific contradiction between answer and resume claim",
    "metric_risk": "probe measurement methodology — what was counted, what baseline, what denominator",
    "overclaim_risk": "ask what the technical vocabulary does in their specific implementation",
    "bridge": "pivot that explicitly names {next_focus_label}"
  }}
}}

Hard rules:
- question_ladder must have exactly one item each for frame, clarify, explore, pressure, synthesize, recover
- frame and clarify must be plain, guided, and not prosecutor-like
- pressure must not appear before the pressure ladder item
- synthesize must be plain language and evidence-seeking, not self-rating. Ask what conclusion is fair to carry forward, what should not be overclaimed, or what concrete check would decide the uncertainty.
- opener must be anchored to a specific claim, number, or decision from the resume snippets — follow the role-specific opener rules in the system prompt exactly
- opener must include company/experience context from the resume snippets
- 2–5 dimensions, every dimension must have a real resume_anchor from the snippets above. Prefer 3+, but do not pad a track with low-signal dimensions when the question_ladder already covers the missing surface.
- every surface/mechanism/boundary question must follow the pattern: [specific element from their claim] + [consequence, challenge, or probe]
- NO memory questions: never "what was the first X", never "what did you try first"
- NO existence checks: never "did you consider X" — never name the solution you are looking for
- boundary probes must be unanswerable by someone who only read documentation
- signal_weight: 3.0 for dimensions that directly test the core claim; 1.5 default; 1.0 for peripheral context
- candidate_q4_options: 3–4 standalone questions covering different aspects of the anchor claim
- recovery.bridge must explicitly name "{next_focus_label}"
"""

_LAUNCH_LITE_SYSTEM = """You are generating the launch-ready part of an interview map.

Goal: create only the first usable interview arc for one resume focus. Do not create a full interview map.

Return one JSON object only with:
{
  "frame": {"posture": "frame", "main_question": "...", "signal_goal": "...", "expected_space": ["..."], "information_gain": "high", "voice_complexity": "low"},
  "clarify": {"posture": "clarify", "main_question": "...", "signal_goal": "...", "expected_space": ["..."], "information_gain": "high", "voice_complexity": "low"},
  "explore": {"posture": "explore", "main_question": "...", "signal_goal": "...", "expected_space": ["..."], "information_gain": "high|medium", "voice_complexity": "low|medium"},
  "pressure": {"posture": "pressure", "main_question": "...", "signal_goal": "...", "expected_space": ["..."], "information_gain": "high", "voice_complexity": "medium"},
  "recover_short_answer": "one short same-focus rescue question",
  "dimensions": [
    {"id": "scope_or_definition", "label": "Scope/definition", "resume_anchor": "...", "question": "...", "signal_goal": "...", "surface_kind": "breadth", "signal_weight": 2.5},
    {"id": "mechanism_or_boundary", "label": "Mechanism/boundary", "resume_anchor": "...", "question": "...", "signal_goal": "...", "surface_kind": "depth", "signal_weight": 2.5}
  ]
}

Rules:
- Generate only frame, clarify, explore, pressure, recover_short_answer, and 2 dimensions.
- Do not generate synthesize, candidate_q4_options, full recovery objects, or 3+ dimensions.
- Every question must be plain spoken English for an Indian candidate.
- frame must be exploratory, not prosecutor-like.
- clarify must ask definition, denominator, ownership boundary, or scope.
- pressure must be one challenge only, not a compound prosecutor question.
- Keep normal questions 18-35 words where possible; never exceed 45 words.
- If answer lanes are useful, include an escape hatch like "or something else?"
- Do not ask hidden internals unless the snippets explicitly support that layer.
- Analyst roles: prefer metric definition, denominator, attribution, decision, and guardrail surfaces.
- Engineering roles: establish ownership and operating level before implementation depth.
- JSON only. No markdown, no commentary."""

_LAUNCH_LITE_USER_TEMPLATE = """Candidate background:
{resume_context}

Target role: {target_role}

Launch focus:
- Label: {label}
- Focus key: {focus_key}
- Anchor context: {anchor_context}
{sub_focuses_block}- Exact resume snippets:
{resume_snippets}

Return only the launch-ready lite track JSON."""

_LAUNCH_PAIR_CRITIC_SYSTEM = """You are a compact launch-readiness critic for two interview-map launch tracks.

Return one JSON object only:
{
  "ready": true,
  "overall_score": 8.0,
  "top_two_score": 8.0,
  "issues": ["..."],
  "focus_reviews": [{"focus_key": "...", "label": "...", "score": 8.0, "issues": []}],
  "typed_issues": [{"issue_scope": "plan_level|track_level|field_level|readability_level", "focus_key": "...", "path": "...", "severity": "minor|major", "action": "keep|surgical_repair|track_repair|plan_repair|accept_with_warning", "reason": "..."}]
}

Judge only launch safety:
- two tracks are distinct enough for startup;
- both are role-relevant;
- first track is a sensible primary anchor;
- second track is a usable pivot/coverage anchor;
- frame/clarify are not pressure questions;
- no unsupported hidden internals or off-role promotion.

Do not demand full-map richness, Q4 options, full recovery, or 3+ dimensions."""

_GENERIC_PHRASES = (
    "what would you do differently",
    "walk me through your thinking",
    "say more about",
    "tell me more",
    "can you elaborate",
    "where does your mental model",
)

_SNIPPET_TOKEN_STOPWORDS = {
    "with", "from", "that", "this", "these", "those", "their", "there", "into",
    "using", "used", "built", "build", "engineered", "worked", "project", "projects",
    "present", "current", "technical", "skills", "experience", "assistant", "intern",
    "research", "school", "university", "admission", "scholarship", "leading", "peer",
    "advisor",
}

_TECH_PHRASE_PATTERNS = (
    r"\bSQL\b",
    r"\bOCR\b",
    r"\bRAG\b",
    r"\bLLM\b",
    r"\bNLP\b",
    r"\bDSP\b",
    r"\bNPU\b",
)


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _compact_focus_key(label: str, proposed: str = "", max_tokens: int = 6) -> str:
    ignored = {
        "ai", "ml", "engineering", "engineer", "intern", "internship",
        "project", "projects", "system", "systems", "work", "experience",
        "built", "using", "with", "custom", "full", "stack",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for source in (proposed, label):
        for token in re.findall(r"[a-z0-9]+", (source or "").lower()):
            if len(token) <= 2 or token in ignored or token in seen:
                continue
            tokens.append(token)
            seen.add(token)
            if len(tokens) >= max_tokens:
                return "_".join(tokens)
    return _normalize_key(proposed or label)


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 2 and token not in _SNIPPET_TOKEN_STOPWORDS
    }


def _anchor_context_for_focus(seed: dict) -> str:
    anchor = str(seed.get("anchor_context", "") or "").strip()
    if anchor:
        return anchor
    snippets = _sub_focus_source_snippets(seed)
    if snippets:
        return " ".join(snippets[:2])[:500]
    labels = [
        str(item.get("label") or "").strip()
        for item in _normalize_sub_focuses(seed.get("sub_focuses"), focus_key=str(seed.get("focus_key") or ""))
        if str(item.get("label") or "").strip()
    ]
    return " | ".join(labels[:3])[:300]


def _sub_focus_source_snippets(seed: dict) -> list[str]:
    snippets: list[str] = []
    for sub_focus in _normalize_sub_focuses(seed.get("sub_focuses"), focus_key=str(seed.get("focus_key") or "")):
        for snippet in sub_focus.get("source_snippets") or []:
            clean = _clean_track_value(snippet)
            if clean:
                snippets.append(clean)
    seen: set[str] = set()
    deduped: list[str] = []
    for snippet in snippets:
        key = snippet.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(snippet)
    return deduped[:6]


def _resume_units(resume: str) -> list[str]:
    units: list[str] = []
    for raw_line in resume.splitlines():
        line = re.sub(r"\s+", " ", raw_line.replace("•", " ").strip())
        if len(line) < 12:
            continue
        if re.fullmatch(r"[-–—:| ]+", line):
            continue
        units.append(line)
    return units


_FOCUS_SECTION_HEADERS = (
    "experience",
    "projects",
    "research",
    "work experience",
    "professional experience",
)

_IGNORE_SECTION_HEADERS = (
    "education",
    "awards",
    "honors",
    "scholarships",
    "technical skills",
    "skills",
    "top skills",
    "contact",
)


def _canonicalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("•", " ").strip())


def _resume_focus_source(resume: str) -> str:
    return resume


def _looks_like_work_header(line: str) -> bool:
    lowered = line.lower()
    if any(token in lowered for token in ("university", "b.eng", "scholarship", "advisor", "top skills", "skills:")):
        return False
    if re.match(
        r"^(architected|engineered|built|implemented|designed|developed|optimized|reconstructed|assisted|worked on|led)\b",
        lowered,
    ):
        return False
    if any(token in lowered for token in ("intern", "engineer", "research assistant", "developer")):
        return True
    if "@" in line and re.search(r"\b(20(?:1[5-9]|2[0-9]))\b", line):
        return True
    if re.search(r"\b(20\d{2})\b", line) and any(token in lowered for token in (" - ", "–", "present", "sept", "jan", "july", "june")):
        return True
    return False


def _resume_work_entries(resume: str) -> list[dict]:
    lines = [_canonicalize_line(line) for line in (_resume_focus_source(resume) or resume).splitlines() if _canonicalize_line(line)]
    entries: list[dict] = []
    current: dict | None = None
    for line in lines:
        lowered = line.lower()
        if "skills" in lowered and len(line.split()) > 3:
            continue
        if _looks_like_work_header(line):
            if current:
                entries.append(current)
            current = {"header": line, "details": []}
            continue
        if current:
            current["details"].append(line)
    if current:
        entries.append(current)
    return entries


def _derive_entry_label(header: str, details: list[str]) -> str:
    header = re.sub(r"\s+", " ", header).strip(" -,:")
    # Em-dash separates "Role — Topic [Org]  Dates": take the topic side
    if "—" in header or " - " in header:
        sep = "—" if "—" in header else " - "
        header = header.split(sep, 1)[1].strip(" -,:")
    else:
        for separator in (":", "@"):
            if separator in header:
                header = header.split(separator, 1)[0 if separator == "@" else 1].strip(" -,:")
                break
    header = re.sub(r"\[(.*?)\]", r"\1", header).strip()  # expand brackets: [HKU x Google] → HKU x Google
    header = re.sub(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s–\-]+[A-Za-z]*\s*(20\d{2})?\b", "", header, flags=re.IGNORECASE).strip(" -,:")
    header = re.sub(r"\b(20\d{2}.*|present)\b", "", header, flags=re.IGNORECASE).strip(" -,:")
    if "," in header and len(header.split()) > 6:
        header = header.split(",", 1)[0].strip()

    if details:
        detail_blob = " ".join(details[:3])
        match = re.search(
            r"\b(agent[- ]based .*? pipeline|audio classification pipeline|benchmark framework|rag optimization .*? framework|script framework|classifier)\b",
            detail_blob,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" -,.").title()

    cleaned = re.sub(r"^(ai|research)\s+", "", header, flags=re.IGNORECASE).strip()
    return cleaned.title() if cleaned else "Recent Technical Work"


def _prettify_focus_label(label: str) -> str:
    cleaned = re.sub(r"\s+", " ", label).strip(" -,.")
    if not cleaned:
        return "Recent Technical Work"
    # Strip role prefix before em-dash: "Research Assistant — Topic" → "Topic"
    if "—" in cleaned or " – " in cleaned:
        sep = "—" if "—" in cleaned else " – "
        right = cleaned.split(sep, 1)[1].strip(" -,.")
        if right:
            cleaned = right
    # Strip month ranges like "Jun–Sep 2025" and bare years
    cleaned = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s–\-]+[A-Za-z]*\s*(20\d{2})?\b",
        "", cleaned, flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b20\d{2}\b", "", cleaned)
    # Normalize square brackets to parens so org names stay in token set
    cleaned = re.sub(r"\[([^\]]*?)\]", r"(\1)", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,.")
    if not cleaned:
        return "Recent Technical Work"
    replacements = {
        "Aigc": "AIGC",
        "Tinyml": "TinyML",
        "Ui": "UI",
        "Sql": "SQL",
        "Ocr": "OCR",
        "Adk": "ADK",
        "Mfcc": "MFCC",
        "Npu": "NPU",
        "Dsp": "DSP",
        "Llms": "LLMs",
        "Llm": "LLM",
        "Hku": "HKU",
        "Ml": "ML",
    }
    words = []
    for word in cleaned.title().split():
        words.append(replacements.get(word, word))
    return " ".join(words)


def _detail_focus_labels(details: list[str], max_labels: int = 2) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    patterns = (
        r"\b(agent[- ]based [\w\s-]+ pipeline)\b",
        r"\b(\w+[- ]based [\w\s-]+ pipeline)\b",
        r"\b(\w+ classification pipeline)\b",
        r"\b(multi-modal [\w\s-]+ framework)\b",
        r"\b([\w\s-]+ benchmark framework)\b",
        r"\b(benchmark framework)\b",
        r"\b([\w\s-]+ inference pipeline)\b",
        r"\b([\w\s-]+ generation pipeline)\b",
    )
    for detail in details:
        for pattern in patterns:
            match = re.search(pattern, detail, flags=re.IGNORECASE)
            if not match:
                continue
            label = _prettify_focus_label(match.group(1))
            key = _compact_focus_key(label)
            if key in seen:
                continue
            seen.add(key)
            labels.append(label)
            if len(labels) >= max_labels:
                return labels
    return labels


def _focus_candidate_units(resume: str) -> list[str]:
    candidates: list[str] = []
    for entry in _resume_work_entries(resume):
        header = str(entry.get("header", "") or "").strip()
        details = [str(detail).strip() for detail in entry.get("details", []) if str(detail).strip()]
        if header:
            candidates.append(header)
        for detail in details[:3]:
            if len(detail) >= 24:
                candidates.append(detail)
    for unit in _resume_units(_resume_focus_source(resume) or resume):
        fragments = re.split(r"(?<=[.!?])\s+|[;•]", unit)
        for fragment in fragments:
            cleaned = re.sub(r"\s+", " ", fragment.strip(" -,."))
            if (
                len(cleaned) >= 12
                and not cleaned.lower().startswith("top skills")
                and "scholarship" not in cleaned.lower()
                and "advisor" not in cleaned.lower()
            ):
                candidates.append(cleaned)
    return candidates or _resume_units(resume)


def _is_noise_snippet(unit: str) -> bool:
    lowered = unit.lower()
    if "@" in unit and "." in unit and len(unit.split()) <= 8:
        return True
    if re.fullmatch(r"[0-9+| :/().-]+", unit):
        return True
    if lowered.startswith("technical skills") or lowered == "experience:":
        return True
    if any(
        token in lowered
        for token in (
            "scholarship",
            "award",
            "advisor",
            "b.eng",
            "university",
            "school of data science",
        )
    ):
        return True
    return False


def _extract_resume_snippets(resume: str, seed: dict, limit: int = 3) -> list[str]:
    query_source = " ".join(
        [
            str(seed.get("label", "") or ""),
            _anchor_context_for_focus(seed),
            " ".join(_sub_focus_texts(seed.get("sub_focuses"), focus_key=str(seed.get("focus_key") or ""))),
            str(seed.get("why_priority") or ""),
        ]
    )
    query_tokens = _tokenize(query_source)
    if not query_tokens:
        return []

    snippets: list[str] = []
    label_lower = str(seed.get("label", "") or "").lower()

    entries = _resume_work_entries(resume)
    best_entry: dict | None = None
    best_entry_score = 0.0
    for entry in entries:
        header = str(entry.get("header", "") or "").strip()
        details = [str(detail).strip() for detail in entry.get("details", []) if str(detail).strip()]
        combined = " ".join([header, *details])
        combined_tokens = _tokenize(combined)
        overlap = query_tokens & combined_tokens
        if not overlap:
            continue
        exact_phrase_bonus = 2.5 if label_lower and label_lower in combined.lower() else 0.0
        detail_bonus = min(len(details), 3) * 0.15
        score = len(overlap) + exact_phrase_bonus + detail_bonus
        if score > best_entry_score:
            best_entry_score = score
            best_entry = {"header": header, "details": details}

    if best_entry:
        scored_details: list[tuple[float, str]] = []
        for detail in best_entry.get("details", []):
            if _is_noise_snippet(detail):
                continue
            detail_tokens = _tokenize(detail)
            overlap = query_tokens & detail_tokens
            if not overlap:
                continue
            exact_phrase_bonus = 2.0 if label_lower and label_lower in detail.lower() else 0.0
            density_bonus = len(overlap) / max(len(query_tokens), 1)
            scored_details.append((len(overlap) + exact_phrase_bonus + density_bonus, detail))
        scored_details.sort(key=lambda item: item[0], reverse=True)
        for _, detail in scored_details:
            if detail not in snippets:
                snippets.append(detail)
            if len(snippets) >= limit:
                return snippets[:limit]

        header = str(best_entry.get("header", "") or "").strip()
        if header and not _is_noise_snippet(header):
            snippets.append(header)
        if len(snippets) >= limit:
            return snippets[:limit]

    units = _resume_units(_resume_focus_source(resume) or resume)
    if not units:
        return snippets[:limit]

    scored_units: list[tuple[float, int, str]] = []
    for unit in units:
        if _is_noise_snippet(unit):
            continue
        unit_tokens = _tokenize(unit)
        if not unit_tokens:
            continue
        overlap = query_tokens & unit_tokens
        if not overlap:
            continue
        exact_phrase_bonus = 2.0 if label_lower and label_lower in unit.lower() else 0.0
        overlap_ratio = len(overlap) / max(len(query_tokens), 1)
        scored_units.append((len(overlap) + exact_phrase_bonus + overlap_ratio, len(unit_tokens), unit))

    scored_units.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, _, unit in scored_units:
        if unit not in snippets:
            snippets.append(unit)
        if len(snippets) >= limit:
            break
    return snippets[:limit]


def _fallback_focus_seeds_from_resume(resume: str, limit: int = 5) -> list[dict]:
    raise RuntimeError("Deterministic focus seed fallback is disabled; LLM focus planning must succeed.")

    def _derive_focus_label(unit: str) -> str:
        cleaned = re.sub(r"\s+", " ", unit.strip(" -,."))
        cleaned = re.sub(
            r"^(built|designed|developed|created|implemented|engineered|led|owned|launched|shipped|optimized|debugged)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(using|with|for|through|via)\b.*$", "", cleaned, flags=re.IGNORECASE).strip(" -,.:")
        cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned, flags=re.IGNORECASE)
        tokens = cleaned.split()
        if not tokens:
            return "Recent Technical Work"
        short = " ".join(tokens[:6]).strip(" -,.:")
        return short.title()

    seeds: list[dict] = []
    seen: set[str] = set()
    for entry in _resume_work_entries(resume):
        header = str(entry.get("header", "") or "").strip()
        details = [str(detail).strip() for detail in entry.get("details", []) if str(detail).strip()]
        if not header:
            continue
        for detail_label in _detail_focus_labels(details, max_labels=2):
            focus_key = _compact_focus_key(detail_label)
            if not focus_key or focus_key in seen or _is_redundant_label(detail_label, [seed["label"] for seed in seeds]):
                continue
            anchor_context = next(
                (detail[:220] for detail in details if detail_label.lower().split()[0] in detail.lower()),
                details[0][:220] if details else header[:220],
            )
            seeds.append({
                "label": detail_label,
                "focus_key": focus_key,
                "anchor_context": anchor_context,
            })
            seen.add(focus_key)
            if len(seeds) >= limit:
                return seeds[:limit]

        label = _prettify_focus_label(_derive_entry_label(header, details))
        if label != "Recent Technical Work":
            focus_key = _compact_focus_key(label)
            if focus_key and focus_key not in seen and not _is_redundant_label(label, [seed["label"] for seed in seeds]):
                anchor_context = details[0][:220] if details else header[:220]
                seeds.append({
                    "label": label,
                    "focus_key": focus_key,
                    "anchor_context": anchor_context,
                })
                seen.add(focus_key)
                if len(seeds) >= limit:
                    return seeds[:limit]

    if len(seeds) >= min(limit, 3):
        return seeds[:limit]

    units = _focus_candidate_units(resume)
    for unit in units:
        lowered = unit.lower()
        if _is_noise_snippet(unit):
            continue
        if (
            len(unit.split()) <= 4
            and any(marker in lowered for marker in ("intern", "engineer", "assistant"))
            and not any(marker in lowered for marker in ("built", "designed", "developed", "implemented", "led", "owned"))
        ):
            continue
        if not any(
            marker in lowered
            for marker in (
                "intern", "engineer", "assistant", "@", "pipeline", "project",
                "built", "designed", "developed", "implemented", "led", "owned",
                "service", "dashboard", "system", "debug", "latency", "postgres",
                "redis", "retrieval", "ranking", "benchmark", "classifier", "interface",
            )
        ):
            continue
        label = unit.split(":", 1)[0].strip(" -")
        if "@" in label:
            label = label.split("@", 1)[0].strip(" -")
        if "." in label and len(label.split()) > 8:
            label = label.split(".", 1)[-1].strip(" -")
        label = _prettify_focus_label(_derive_focus_label(label or unit))
        if len(label) > 80:
            label = label[:80].rsplit(" ", 1)[0]
        focus_key = _compact_focus_key(label)
        if not focus_key or focus_key in seen or _is_redundant_label(label, [seed["label"] for seed in seeds]):
            continue
        seeds.append({
            "label": label,
            "focus_key": focus_key,
            "anchor_context": unit[:220],
        })
        seen.add(focus_key)
        if len(seeds) >= limit:
            break
    return seeds



_FOCUS_SEED_TIMEOUT_SECONDS = 8.0
_FOCUS_TRACK_TIMEOUT_SECONDS = 6.5
_FOCUS_TRACK_BACKGROUND_TIMEOUT_SECONDS = 75.0  # Sonnet 4.6 at 1500 tokens takes 30-60s
_FOCUS_TRACK_BUILD_DEADLINE_SECONDS = 15.0
_FOCUS_TRACK_MAX_AREAS = 4
_RICH_MAP_BANNED_LABEL_TOKENS = (
    "scholarship",
    "advisor",
    "university",
    "skills",
    "contact",
    "district",
    "boulevard",
    "phone",
    "email",
)
_RICH_MAP_CORE_BRANCHES = {
    "sprint_1.if_strong",
    "sprint_1.if_vague",
    "sprint_1.if_short_answer",
    "sprint_2.if_strong",
    "sprint_3.if_strong",
}
# Equivalent richness gate for new dimension schema — must have opener + ≥3 dims + full recovery
_DIM_RECOVERY_REQUIRED = {
    "short_answer", "honest_gap", "claim_conflict", "metric_risk", "overclaim_risk", "bridge",
}
_MAP_TARGET_FOCUS_AREAS = 5   # upper bound — planner decides actual count (2–5) from resume quality
_MAP_MIN_FOCUS_AREAS = 2      # minimum acceptable after planner selection
_MAP_LAUNCH_TRACK_COUNT = 2   # startup blocks only on the first two launch-critical tracks
_MAP_MIN_READY_SCORE = 7.0
_MAP_GENERATOR_MODEL = env_first("OPENROUTER_MAP_GENERATOR_MODEL", default="google/gemini-3.5-flash")
_MAP_RESCUE_MODEL = env_first(
    "OPENROUTER_MAP_RESCUE_MODEL",
    "OPENROUTER_MAP_SONNET_RESCUE_MODEL",
    default="anthropic/claude-sonnet-4.6",
)
_MAP_CRITIC_MODEL = env_first("OPENROUTER_MAP_CRITIC_MODEL", default=_MAP_RESCUE_MODEL)
_MAP_CRITIC_SCHEMA_RESCUE_MODEL = env_first(
    "OPENROUTER_MAP_CRITIC_SCHEMA_RESCUE_MODEL",
    default="google/gemini-3.5-flash",
)
_MAP_TRACK_SCHEMA_RESCUE_MODEL = env_first(
    "OPENROUTER_MAP_TRACK_SCHEMA_RESCUE_MODEL",
    default="google/gemini-3.1-flash-lite",
)
_LAUNCH_LITE_REPAIR_MODEL = env_first(
    "OPENROUTER_LAUNCH_TRACK_LITE_REPAIR_MODEL",
    default=SURFACE_PLANNER_MODEL or _MAP_TRACK_SCHEMA_RESCUE_MODEL,
)
_MAP_AUDIT_MODEL = env_first("OPENROUTER_MAP_AUDIT_MODEL", default="deepseek/deepseek-v4-flash")
_MAP_AUDIT_SOFT_TIMEOUT_SECONDS = float(env_first("MAP_AUDIT_SOFT_TIMEOUT_SECONDS", default="2.5"))
_MAP_PRIMARY_MAX_TOKENS = 2800
_MAP_RETRY_MAX_TOKENS = 1600
_MAP_JSON_RESPONSE_FORMAT = {"type": "json_object"}
_FOCUS_PLAN_PRIMARY_MAX_TOKENS = 4000  # Gemini 3.5 Flash often returns high-quality but verbose plans.
_FOCUS_PLAN_RETRY_MAX_TOKENS = 2500
_MAP_CRITIC_MAX_TOKENS = 2600   # critic JSON with up to 5 focus reviews
_MAP_SURGICAL_REPAIR_MAX_TOKENS = 1400
_LAUNCH_LITE_MAX_TOKENS = 1800
_LAUNCH_LITE_REPAIR_MAX_TOKENS = 1400
_LAUNCH_LITE_CRITIC_MAX_TOKENS = 900
_VALID_ISSUE_SCOPES = {
    "plan_level",
    "track_level",
    "field_level",
    "readability_level",
    "weighting_level",
}
_VALID_REPAIR_ACTIONS = {
    "keep",
    "surgical_repair",
    "track_repair",
    "plan_repair",
    "accept_with_warning",
}

_MAP_CRITIC_SYSTEM = """You are a pragmatic interview-map critic.

Review the proposed map slice like a strong senior interviewer. Your job is to improve it, not to block it over minor imperfections.

Judge all focus areas provided in this request carefully. In launch-track reviews, the request contains only the two startup-critical tracks; do not infer problems about omitted later tracks:
- are the chosen focus areas distinct and non-redundant? Two areas from the same role must probe different technical surfaces.
- is each question_ladder usable as a spoken interview rhythm: frame/clarify first, then explore/pressure, then plain synthesis/recovery?
- do frame and clarify questions guide the candidate without sounding like a prosecutor question?
- is each opener anchored to a specific, provable resume claim? Generic "walk me through everything you've done" is not acceptable — but "At [company], you [specific outcome] — walk me through that work" IS acceptable for non-engineering roles. Engineering openers must use specific framing (what was the core problem, what broke, what was the tradeoff), not "walk me through".
- does each opener enter a clear first dimension rather than asking about everything at once?
- do the dimensions have genuine resume grounding — not generic dimension types applied without evidence?
- does each dimension escalate correctly: surface (basic familiarity) → mechanism (genuine depth) → boundary (unanswerable without real ownership)?
- do the boundary probes require actual hands-on work to answer — not just documentation reading?
- does the ladder include a usable recovery posture for short, vague, honest-gap, or evasive answers?
- legacy recovery fields are compatibility fields. Flag bad/missing/duplicated legacy recovery for later cleanup, but do not block launch if the question_ladder is strong and runtime-usable.
- does the bridge explicitly name the next focus area?

SCORING RUBRIC — use this to calibrate overall_score and per-area score:
9–10: The ladder has strong interview rhythm, plain guided questions, high information gain, and pressure only after frame/clarify. Boundary probes are unanswerable without hands-on ownership. signal_weight 3.0 dimensions fire directly on the core resume claim.
7–8: Solid grounding but one or more questions are overpacked, too prosecutor-like too early, or low-information. Ladder recovery is usable; legacy recovery may have minor compatibility notes.
5–6: Openers are generic or untethered from specific resume claims. Dimensions use standard templates without resume evidence. Boundary probes could be answered by someone who read the resume carefully but never did the work.
Below 5: Dimensions repeat angles, ladder recovery is missing/unusable, or focus areas cover the wrong work entirely.

A score above 8.5 requires: at least 3 high-information ladder items, frame/clarify in plain guided language, and every boundary probe names a specific artifact or number from the resume that only an owner would know.

Mark ready=true when every focus area has a strong opener, a complete runtime-usable question_ladder, and either ≥3 grounded dimensions or exactly 2 high-signal dimensions with a complete high-information ladder.
Also require a usable question_ladder: frame/clarify must be guided and plain, pressure must be one challenge, and synthesize must use simple language.
Legacy recovery/candidate_q4_options issues should be accept_with_warning unless the ladder itself cannot recover signal.
Do not reward low-information specificity. A question about a tiny property name is weak unless that property changes the hiring signal.
Do not make every question a prosecutor question. Penalise pressure wording in frame/clarify.
Prioritize actionable repair instructions over harsh rejection. Be precise about which dimension and which probe level is weak — "dimension X surface probe is answerable from documentation" beats "questions could be stronger".

When only one question or field is weak, do not ask for full regeneration. Add a repair_targets entry for the exact field to replace. Use paths like:
- question_ladder[0].main_question
- question_ladder[1].follow_up_if_shallow
- question_ladder[2].expected_space
- opener
- dimensions[0].surface
- dimensions[1].mechanism
- dimensions[2].boundary
- recovery.metric_risk
- candidate_q4_options[0]

Classify every material issue with issue_scope and action:
- plan_level + plan_repair: wrong/missing/duplicate focus areas, wrong ranking, bad role relevance plan.
- track_level + track_repair: a whole focus track has the wrong boundary or several dimensions are unusable.
- field_level + surgical_repair: one exact question/field is weak or has the wrong angle.
- readability_level + surgical_repair: one exact field is too packed, robotic, or hard to say aloud.
- weighting_level + accept_with_warning or surgical_repair: suspicious weights; only repair if a concrete weight field is wrong.
Only use broad repair_instructions for problems that cannot be fixed by replacing one or two questions. A note like "focus area 2 opener drifts into another angle" is field_level with path=opener, not plan_level.

Return JSON only."""

_FOCUS_PLAN_SYSTEM = """You are a senior technical interviewer deciding which resume experiences are worth deep probing.

Return 2 to 5 focus areas. Exactly as many as genuinely qualify — stop at 2 if only 2 experiences are truly interview-worthy, go to 5 if 5 distinct experiences each clear the bar. Do not pad; do not artificially cap.

RANKING PRIORITY (apply in order):
1. Most recent role or internship with specific technical system names, architecture decisions, or measurable outcomes — rank this #1
2. Second most recent internship or research with measurable technical claims (latency, accuracy %, cost reduction)
3–5. Additional entries only if each one introduces genuinely different technical territory (different domain, stack, or problem class) and contains defensible implementation depth

INCLUDE:
- systems the candidate claims to have personally built end-to-end
- experiences with specific model names, API names, architecture decisions, or metrics the candidate would have to defend
- work where "how did you measure that?" or "what did you personally write?" has an interesting answer

EXCLUDE:
- education, scholarships, skills lists, contact info
- coursework with no novel contribution beyond the assignment
- bullets that only list tool names with no architecture ("used Python, Pandas, SQL")
- vague contributions ("contributed to", "helped with", "assisted")
- rudimentary or introductory work not worth a senior interviewer's time

DEDUPLICATION RULES (critical — violations cause map failure):
- If one internship or project has multiple impressive technical angles, merge them into ONE wider focus area unless the role-relevant same-experience exception applies. The dimensions inside that area will cover all the angles.
- Each additional focus area slot should usually represent a DIFFERENT company, project, or research effort from all prior slots unless a real target-role job contains distinct role-critical surfaces.
- If you are tempted to create two areas from the same company/project, first ask whether they test different target-role reasoning surfaces. If yes, keep them split; if no, combine them into one richer area.

ROLE-RELEVANT SAME-EXPERIENCE EXCEPTION:
- When the target role directly matches a real job in the resume, prefer that job's distinct role-relevant surfaces over older unrelated internships.
- For Product Analyst / Analytics / Growth roles, retention experiments, conversion or pricing experiments, event taxonomy/instrumentation, funnel analysis, marketing/CAC dashboards, and reactivation dashboards may each be separate focus areas when they test different reasoning surfaces.
- Do not promote an unrelated research internship as the main secondary anchor merely because it is a different company. Use it only after the top role-relevant surfaces have been represented.

SUB-FOCUS INSTRUCTION:
When a single focus area covers multiple distinct technical surfaces (e.g. an inference pipeline AND a data modeling layer), list each surface as an object in sub_focuses. The track generator uses this list to guarantee at least one dimension per sub-focus — so be explicit. Sub-focus labels should be 5–12 words, grounded in the resume. If a focus area has only one coherent technical surface, sub_focuses may be empty or contain just that one surface object.
IMPORTANT — assign sub_focuses by analytical theme, not positional proximity in the resume text. If a credibility challenge or causal attribution claim appears near an infrastructure bullet but logically belongs with a measurement or outcome claim, assign it to the focus area whose theme is most analytically adjacent. A concurrent-experiment attribution challenge belongs with the outcome it challenges, not with the pipeline that served it.
Each sub-focus must carry numeric value signals:
- role_relevance_weight 1.0-3.0: how directly this surface tests the target role. Off-role flashy claims should be 1.0-1.4 even if technically impressive.
- profile_importance_weight 1.0-3.0: how central this surface is in the candidate's overall profile and recency.
- evidence_strength 1.0-3.0: how concrete the resume evidence is.
- claim_risk 1.0-3.0: how much overclaim/credibility risk exists if the candidate cannot defend it.
- coverage_value 1.0-3.0: final priority for interview time. Role relevance must dominate this value; do not give high coverage_value to irrelevant claims just because they are risky.

QUESTION BUDGET AND TIME ALLOCATION:
- area[0] (primary anchor): receives the first deep pass and usually 3–4 direct questions before application transfer. Do not describe it as a 60% tunnel.
- area[1] (secondary): should be ready as the first pivot after application-transfer coverage.
- area[2] and beyond: attention-check or role-breadth anchors; use only after stronger role-relevant surfaces are covered. A 2-month internship must NEVER receive equal billing as a 12-month current role.
- Bridge direction: always from most-recent toward oldest — never route backward in time toward older or less relevant experience

JSON only, no markdown, no commentary."""


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)


def _safe_json_preview(value: object, limit: int = 6000) -> str:
    try:
        return _json_text(value)[:limit]
    except Exception:
        return str(value)[:limit]


def _affordable_token_budget_from_error(exc: Exception) -> int | None:
    message = str(exc or "")
    match = re.search(r"can only afford (\d+) tokens", message, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        affordable = int(match.group(1))
    except Exception:
        return None
    return max(256, affordable - 32)



def _map_critic_user_prompt(*, resume: str, candidate: dict, stage: str) -> str:
    area_count = len((candidate.get("focus_areas") or []) if isinstance(candidate, dict) else [])
    return "\n".join([
        f"Review stage: {stage}",
        "",
        "Candidate resume:",
        resume,
        "",
        "Proposed interview map candidate:",
        _json_text(candidate),
        "",
        "Return ONLY JSON with this schema:",
        "{",
        '  "ready": true,',
        '  "overall_score": 0,',
        '  "top_two_score": 0,',
        '  "opener_quality_score": 0,',
        '  "dimension_depth_score": 0,',
        '  "strengths": ["..."],',
        '  "issues": ["..."],',
        '  "repair_instructions": ["..."],',
        '  "focus_reviews": [',
        "    {",
        '      "focus_key": "snake_case_identifier",',
        '      "label": "focus label",',
        '      "score": 0,',
        '      "opener_issue": "",',
        '      "issues": ["..."]',
        "    }",
        "  ],",
        '  "typed_issues": [',
        "    {",
        '      "issue_scope": "plan_level|track_level|field_level|readability_level|weighting_level",',
        '      "focus_key": "snake_case_identifier_or_blank_for_plan_level",',
        '      "path": "question_ladder[0].main_question | opener | dimensions[0].surface | recovery.metric_risk | candidate_q4_options[0] | blank_for_plan_level",',
        '      "severity": "minor|major",',
        '      "action": "keep|surgical_repair|track_repair|plan_repair|accept_with_warning",',
        '      "reason": "why this issue is scoped this way"',
        "    }",
        "  ],",
        '  "repair_targets": [',
        "    {",
        '      "focus_key": "snake_case_identifier",',
        '      "path": "question_ladder[0].main_question | opener | dimensions[0].surface | recovery.metric_risk | candidate_q4_options[0]",',
        '      "issue": "what is weak",',
        '      "instruction": "how to replace only this field",',
        '      "severity": "minor|major",',
        '      "issue_scope": "field_level|readability_level|weighting_level",',
        '      "action": "surgical_repair",',
        '      "reason": "why this exact field is repairable"'
        "    }",
        "  ]",
        "}",
        "",
        "Scoring expectations:",
        f"- use {_MAP_MIN_READY_SCORE} as a guideline for strong launch quality, not a rigid blocker",
        f"- mark ready=true when all {area_count} focus areas have usable question_ladders, strong openers, and either >=3 grounded dimensions or 2 high-signal dimensions with a complete high-information ladder",
        "- legacy recovery/candidate_q4_options are compatibility fields; do not mark launch not-ready only because those fields duplicate ladder questions",
        "- opener_quality_score: 0-10, penalise prosecutor-like frame/clarify items and generic walk-through openers",
        "- dimension_depth_score: 0-10, penalise dimensions where boundary probes could be answered from documentation alone",
        "- repair_targets: include exact field paths for local question swaps; leave empty for plan-level or full-track problems",
        "- typed_issues: always distinguish plan_level from field_level/readability_level; route one bad opener to surgical_repair",
        "- prioritize actionable repair instructions over harsh rejection",
        f"- keep response compact: at most 3 strengths, 3 issues, 4 repair instructions, focus_reviews for all {area_count} areas",
        "- JSON only",
    ])


def _compact_map_candidate_for_critic(candidate: dict) -> dict:
    areas: list[dict] = []
    for area in (candidate.get("focus_areas") or [])[:_MAP_TARGET_FOCUS_AREAS]:
        if not isinstance(area, dict):
            continue
        track = area.get("track") if isinstance(area.get("track"), dict) else area
        areas.append({
            "focus_key": area.get("focus_key", ""),
            "label": area.get("label", ""),
            "anchor_context": area.get("anchor_context", ""),
            "sub_focuses": [
                {
                    "label": sf.get("label", ""),
                    "surface_kind": sf.get("surface_kind", ""),
                    "coverage_value": sf.get("coverage_value"),
                    "role_relevance_weight": sf.get("role_relevance_weight"),
                }
                for sf in _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or ""))[:4]
            ],
            "question_ladder": [
                {
                    "posture": item.get("posture", ""),
                    "main_question": item.get("main_question", ""),
                    "signal_goal": item.get("signal_goal", ""),
                    "expected_space": item.get("expected_space", []),
                    "follow_up_if_shallow": item.get("follow_up_if_shallow", ""),
                    "follow_up_if_strong": item.get("follow_up_if_strong", ""),
                    "information_gain": item.get("information_gain", ""),
                    "voice_complexity": item.get("voice_complexity", ""),
                }
                for item in (track.get("question_ladder") or [])[:6]
                if isinstance(item, dict)
            ],
            "opener": track.get("opener", ""),
            "dimensions": [
                {
                    "id": dim.get("id") or dim.get("label", ""),
                    "label": dim.get("label", ""),
                    "surface": dim.get("surface", ""),
                    "mechanism": dim.get("mechanism", ""),
                    "boundary": dim.get("boundary", ""),
                    "signal_weight": dim.get("signal_weight"),
                }
                for dim in (track.get("dimensions") or [])[:4]
                if isinstance(dim, dict)
            ],
            "recovery": {
                key: value
                for key, value in (track.get("recovery") or {}).items()
                if key in {"short_answer", "honest_gap", "metric_risk", "bridge"}
            } if isinstance(track.get("recovery"), dict) else {},
        })
    return {"focus_areas": areas}


def _compact_map_critic_user_prompt(*, candidate: dict, stage: str) -> str:
    area_count = len((candidate.get("focus_areas") or []) if isinstance(candidate, dict) else [])
    return "\n".join([
        f"Review stage: {stage}",
        "",
        "Compact proposed interview map candidate:",
        _json_text(_compact_map_candidate_for_critic(candidate)),
        "",
        "Return exactly ONE JSON object. Do not return a top-level array.",
        "Use this exact object shape:",
        "{",
        '  "ready": true,',
        '  "overall_score": 0,',
        '  "top_two_score": 0,',
        '  "opener_quality_score": 0,',
        '  "dimension_depth_score": 0,',
        '  "strengths": ["..."],',
        '  "issues": ["..."],',
        '  "repair_instructions": ["..."],',
        '  "focus_reviews": [',
        '    {"focus_key": "snake_case_identifier", "label": "focus label", "score": 0, "opener_issue": "", "issues": ["..."]}',
        "  ],",
        '  "typed_issues": [],',
        '  "repair_targets": []',
        "}",
        "",
        f"Include focus_reviews for all {area_count} focus areas. JSON object only.",
    ])


def _focus_plan_user_prompt(
    *,
    resume: str,
    dedup_hint: str = "",
    target_role: str = "",
    surface_plan_v2: dict | None = None,
) -> str:
    _is_analyst_role = _is_analyst_or_pm_role(target_role)
    anchor_rule = (
        "- anchor_context must prioritize OUTCOME CLAIMS (metrics delivered, decisions made, recommendations adopted) over implementation claims for this role"
        if _is_analyst_role
        else "- area[0] must be the single most technically rich and recent experience"
    )
    same_experience_rule = (
        "- PRODUCT/ANALYTICS EXCEPTION: if the same real job has distinct role-critical surfaces, split them into separate focus_areas before using unrelated internships. Retention/conversion experiments, event taxonomy, funnel analysis, dashboard automation, CAC/marketing analytics, and reactivation can be separate areas when each has evidence."
        if _is_analyst_role
        else "- if one project has multiple technical angles, merge them into one wider area with those surfaces listed in sub_focuses — do not allocate two focus area slots to the same work"
    )
    decision_surface_rule = (
        "- For analytics roles, preserve decision-use reporting/dashboard surfaces when the resume names multiple business metrics or operational consumers. If not launch-critical, keep them as a deferred focus or explicit sub-focus; do not bury them inside taxonomy/modeling unless the dashboard is only a thin output view."
        if _is_analyst_role
        else "- Preserve a deployment, monitoring, or user-facing operational surface only when it tests a different skill than the core implementation."
    )
    lines = [
        f"Target role: {target_role}" if target_role else "",
        "Resume (full text):",
        resume,
        "",
        "Return ONLY JSON with this schema:",
        "{",
        '  "focus_areas": [',
        "    {",
        '      "label": "topic-focused name, no dates, no role titles",',
        '      "focus_key": "snake_case_identifier",',
        '      "anchor_context": "one sentence: the exact system built or the specific technical claim",',
        '      "sub_focuses": [',
        '        {',
        '          "label": "distinct technical surface",',
        '          "sub_focus_key": "snake_case_surface_key",',
        '          "surface_kind": "conversion_experiment | retention_experiment | event_taxonomy | dashboard_reporting | acquisition_marketing | data_pipeline | backend_system | ml_model | ai_agent | computer_vision | design_ux | research | operations | leadership | other",',
        '          "role_relevance_weight": 1.0,',
        '          "profile_importance_weight": 1.0,',
        '          "evidence_strength": 1.0,',
        '          "claim_risk": 1.0,',
        '          "coverage_value": 1.0,',
        '          "why_priority": "why this surface deserves or does not deserve interview time",',
        '          "source_snippets": ["exact or near-exact quote supporting this surface"]',
        '        }',
        '      ],',
        '      "resume_snippets": ["exact or near-exact quote from resume"],',
        '      "why_priority": "what makes this worth probing hard"',
        "    }",
        "  ]",
        "}",
        "",
        "Rules:",
        "- 2 to 5 focus_areas, exactly as many as genuinely qualify — never pad, never cut a qualifying area",
        "- because launch prep may quarantine one weak area, return at least 3 focus_areas whenever the resume has 3 credible role-relevant or high-value surfaces; stop at 2 only when a third surface would be padding",
        anchor_rule,
        "- each additional area should usually represent a different company, project, or research effort unless the target-role exception below applies",
        same_experience_rule,
        decision_surface_rule,
        "- each additional area must introduce genuinely different technical territory (different domain, stack, or problem class)",
        "- for role-matched jobs, role relevance outranks company diversity",
        "- sub_focuses may use legacy strings only if unavoidable; prefer objects with weights",
        "- surface_kind is a typed taxonomy label for validators and routing; choose the nearest kind from the schema, do not invent company-specific kinds",
        "- role_relevance_weight must dominate coverage_value; off-role flashy claims should receive low coverage_value even when claim_risk is high",
        "- profile_importance_weight should reflect recency, duration, ownership, and how central the surface is to the candidate's resume",
        "- evidence_strength should be high only for concrete metrics, named systems, exact tools, or clear ownership",
        "- claim_risk should be high for inflated metrics, vague ownership, or claims likely to mislead; it must not by itself make irrelevant work high priority",
        "- labels: topic-focused ('AIGC Video Pipeline' not 'Software Engineer Intern')",
        "- keep anchor_context under 180 chars, snippets under 160 chars each",
        "- every text value must be a single-line JSON string; weights must be JSON numbers",
        "- no track key, no extra keys, no markdown",
    ]
    compact_surface_plan = compact_surface_plan_for_prompt(surface_plan_v2)
    if compact_surface_plan:
        lines.extend([
            "",
            "SurfacePlanV2 typed recommendation:",
            compact_surface_plan,
            "",
            "How to use SurfacePlanV2:",
            "- Treat this as a first-class planning signal, not a hard template.",
            "- Use focus/sub-focus/testable surfaces to preserve high-signal role-relevant areas.",
            "- You may merge, split, add, or demote areas only when the resume evidence and target role justify it.",
            "- If you ignore a high role-relevance surface, explain the better reason in why_priority.",
            "- recommended_allocation_hint is advisory only; never convert it directly into question counts or fixed turn budgets.",
            "- Demoted/off-role surfaces should not become launch focus areas unless their role relevance is explicit in the resume.",
        ])
    lines = [l for l in lines if l]  # strip empty lines from missing target_role
    if dedup_hint:
        dedup_repair_rule = (
            "In particular: if the same job appeared in multiple focus areas, merge only genuinely redundant areas. Keep distinct role-critical product/analytics surfaces split when they test different reasoning surfaces, then use remaining slots for other strong work."
            if _is_analyst_role
            else "In particular: if the same project appeared in multiple focus areas, merge those technical surfaces into one wider focus area and use the freed slot(s) for genuinely different projects."
        )
        lines.extend([
            "",
            "CRITICAL — fix these problems from the previous attempt before returning:",
            dedup_hint,
            dedup_repair_rule,
        ])
    return "\n".join(lines)


def _clean_resume_snippets(snippets: object) -> list[str]:
    cleaned: list[str] = []
    for item in snippets if isinstance(snippets, list) else []:
        if isinstance(item, dict):
            value = ""
            for key in ("snippet", "quote", "text", "value", "line", "evidence"):
                value = _clean_track_value(item.get(key))
                if value:
                    break
        else:
            value = _clean_track_value(item)
        if value and value not in cleaned:
            cleaned.append(value[:180])
        if len(cleaned) >= 2:
            break
    return cleaned


def _fallback_quality_review(candidate: dict, *, stage: str, issue: str) -> dict:
    raise RuntimeError("Deterministic map critic fallback is disabled; LLM critique must succeed.")


def _recover_focus_areas_from_text(raw: str) -> list[dict]:
    recovered: list[dict] = []
    if not isinstance(raw, str):
        return recovered
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    object_pattern = re.compile(r"\{[^{}]*\"label\"\s*:\s*\"(?:[^\"\\\\]|\\\\.)*\"[\s\S]*?\}", re.MULTILINE)
    for match in object_pattern.finditer(cleaned):
        chunk = match.group(0)
        label_match = re.search(r'"label"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
        if not label_match:
            continue
        focus_key_match = re.search(r'"focus_key"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
        anchor_match = re.search(r'"anchor_context"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
        priority_match = re.search(r'"why_priority"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
        snippets_match = re.search(r'"resume_snippets"\s*:\s*\[(.*?)\]', chunk, flags=re.S)
        snippets: list[str] = []
        if snippets_match:
            snippets = [
                _clean_track_value(bytes(value, "utf-8").decode("unicode_escape"))
                for value in re.findall(r'"((?:[^"\\]|\\.)*)"', snippets_match.group(1))
            ]
        recovered.append({
            "label": _clean_track_value(bytes(label_match.group(1), "utf-8").decode("unicode_escape")),
            "focus_key": _clean_track_value(bytes((focus_key_match.group(1) if focus_key_match else ""), "utf-8").decode("unicode_escape")),
            "anchor_context": _clean_track_value(bytes((anchor_match.group(1) if anchor_match else ""), "utf-8").decode("unicode_escape")),
            "resume_snippets": snippets,
            "why_priority": _clean_track_value(bytes((priority_match.group(1) if priority_match else ""), "utf-8").decode("unicode_escape")),
        })
        if len(recovered) >= _MAP_TARGET_FOCUS_AREAS:
            break
    return recovered


def _focus_plan_text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("label", "name", "title", "text", "value", "focus", "surface", "description"):
            text = _clean_track_value(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        return " ".join(text for text in (_focus_plan_text(item) for item in value) if text)
    return _clean_track_value(value)


def _normalize_candidate_focus_area(area: dict, *, resume: str, existing_labels: list[str]) -> dict | None:
    if not isinstance(area, dict):
        return None
    label = _prettify_focus_label(_focus_plan_text(area.get("label", "")))
    if not label or _is_redundant_label(label, existing_labels):
        return None
    anchor_context = _focus_plan_text(area.get("anchor_context", ""))
    focus_key = _compact_focus_key(label, _focus_plan_text(area.get("focus_key", "")))
    if not focus_key:
        return None
    sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=focus_key)
    seed = {
        "label": label,
        "focus_key": focus_key,
        "anchor_context": anchor_context,
        "sub_focuses": sub_focuses,
    }
    resume_snippets = _clean_resume_snippets(
        area.get("resume_snippets")
        or area.get("resume_evidence")
        or area.get("supporting_lines")
    )
    if not resume_snippets:
        resume_snippets = _extract_resume_snippets(resume, seed, limit=3)
    if not anchor_context:
        anchor_context = resume_snippets[0] if resume_snippets else label
    return {
        "label": label,
        "focus_key": focus_key,
        "anchor_context": anchor_context[:300],
        "sub_focuses": sub_focuses,
        "resume_snippets": resume_snippets[:3],
        "why_priority": _clean_track_value(area.get("why_priority", ""))[:120],
        "surface_kind": _primary_surface_kind({**area, "focus_key": focus_key, "sub_focuses": sub_focuses}),
        "coverage_value": _focus_area_priority_value({**area, "focus_key": focus_key, "sub_focuses": sub_focuses}),
        "track": area.get("track") if isinstance(area.get("track"), dict) else None,
    }


def _normalize_map_candidate(candidate: dict | str, *, resume: str) -> dict:
    if isinstance(candidate, str):
        cleaned = candidate.strip()
        parsed = _load_json_lenient(cleaned)
        if isinstance(parsed, dict):
            candidate = parsed
        else:
            recovered = _recover_focus_areas_from_text(cleaned)
            if recovered:
                candidate = {"focus_areas": recovered}
            else:
                raise RuntimeError("Interview map candidate was not valid JSON.")
    if not isinstance(candidate, dict):
        raise ValueError("Interview map candidate must be a JSON object.")

    normalized: list[dict] = []
    existing_labels: list[str] = []
    seen_focus_keys: set[str] = set()
    for raw_area in candidate.get("focus_areas", []) if isinstance(candidate.get("focus_areas", []), list) else []:
        area = _normalize_candidate_focus_area(raw_area, resume=resume, existing_labels=existing_labels)
        if not area:
            continue
        if area["focus_key"] in seen_focus_keys:
            continue
        normalized.append(area)
        existing_labels.append(area["label"])
        seen_focus_keys.add(area["focus_key"])
        if len(normalized) >= _MAP_TARGET_FOCUS_AREAS:
            break

    if len(normalized) < _MAP_MIN_FOCUS_AREAS:
        raise RuntimeError(
            f"LLM focus planner returned only {len(normalized)} usable focus areas; refusing deterministic padding."
        )

    normalized = sorted(
        enumerate(normalized),
        key=lambda item: (-_focus_area_priority_value(item[1]), item[0]),
    )
    ordered_focus_areas = [area for _, area in normalized]

    return {
        "focus_areas": ordered_focus_areas[:_MAP_TARGET_FOCUS_AREAS],
        "notes": _clean_track_value(candidate.get("notes", "")) if isinstance(candidate, dict) else "",
    }



async def _run_focus_plan_call(llm: "LLMRouter", user_prompt: str, primary_max_tokens: int, retry_max_tokens: int) -> dict | None:
    """Single model attempt at focus area selection. Returns raw dict or None."""
    last_error: Exception | None = None
    for max_tokens in (primary_max_tokens, retry_max_tokens):
        try:
            raw = await llm.call(
                system=_FOCUS_PLAN_SYSTEM,
                user=user_prompt,
                max_tokens=max_tokens,
                response_format=_MAP_JSON_RESPONSE_FORMAT,
            )
            return raw if isinstance(raw, dict) else None
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            affordable_tokens = _affordable_token_budget_from_error(exc)
            if affordable_tokens and affordable_tokens < max_tokens:
                try:
                    raw = await llm.call(
                        system=_FOCUS_PLAN_SYSTEM,
                        user=user_prompt,
                        max_tokens=affordable_tokens,
                        response_format=_MAP_JSON_RESPONSE_FORMAT,
                    )
                    return raw if isinstance(raw, dict) else None
                except Exception:
                    pass
            if "fewer max_tokens" not in message and "credits" not in message:
                break  # non-recoverable — stop trying this model
    return None


def _normalize_issue_scope(value: object, path: str = "") -> str:
    raw = _clean_track_value(value).lower()
    if raw in _VALID_ISSUE_SCOPES:
        return raw
    path_lower = _clean_track_value(path).lower()
    if path_lower in {"focus_plan", "focus_area", "focus_areas", "plan"}:
        return "plan_level"
    if path_lower in {"track", "dimensions", "recovery"}:
        return "track_level"
    if path_lower:
        return "field_level"
    return "field_level"


def _normalize_repair_action(value: object, scope: str = "") -> str:
    raw = _clean_track_value(value).lower()
    if raw in _VALID_REPAIR_ACTIONS:
        return raw
    if scope == "plan_level":
        return "plan_repair"
    if scope == "track_level":
        return "track_repair"
    if scope == "weighting_level":
        return "accept_with_warning"
    return "surgical_repair"


def _normalized_typed_issue(item: dict, *, default_focus: str = "") -> dict | None:
    if not isinstance(item, dict):
        return None
    path = _clean_track_value(item.get("path", ""))
    scope = _normalize_issue_scope(item.get("issue_scope"), path)
    action = _normalize_repair_action(item.get("action"), scope)
    focus_key = _clean_track_value(item.get("focus_key", "") or default_focus)
    reason = _clean_track_value(
        item.get("reason")
        or item.get("issue")
        or item.get("instruction")
        or ""
    )
    severity = _clean_track_value(item.get("severity", "minor")).lower() or "minor"
    if severity not in {"minor", "major"}:
        severity = "major" if severity in {"high", "critical", "severe"} else "minor"
    if not reason and not path and scope != "plan_level":
        return None
    return {
        "issue_scope": scope,
        "focus_key": focus_key,
        "path": path,
        "severity": severity,
        "action": action,
        "reason": reason,
    }


def _normalized_repair_target(item: dict, *, default_focus: str = "") -> dict | None:
    if not isinstance(item, dict):
        return None
    path = _clean_track_value(item.get("path", ""))
    if not path:
        return None
    scope = _normalize_issue_scope(item.get("issue_scope"), path)
    action = _normalize_repair_action(item.get("action"), scope)
    return {
        "focus_key": _clean_track_value(item.get("focus_key", "") or default_focus),
        "path": path,
        "issue": _clean_track_value(item.get("issue", "")),
        "instruction": _clean_track_value(item.get("instruction", "")),
        "severity": _clean_track_value(item.get("severity", "minor")) or "minor",
        "issue_scope": scope,
        "action": action,
        "reason": _clean_track_value(item.get("reason", "") or item.get("issue", "")),
    }


def _critic_signals_plan_problem(review: dict) -> bool:
    """True when the critic's output indicates the focus plan itself is bad (duplicates/same-project splits)."""
    if not isinstance(review, dict):
        return False
    typed_issues = [item for item in (review.get("typed_issues") or []) if isinstance(item, dict)]
    repair_targets = [item for item in (review.get("repair_targets") or []) if isinstance(item, dict)]
    if typed_issues or repair_targets:
        for item in [*typed_issues, *repair_targets]:
            scope = _normalize_issue_scope(item.get("issue_scope"), item.get("path", ""))
            action = _normalize_repair_action(item.get("action"), scope)
            if scope == "plan_level" or action == "plan_repair":
                return True
        # If every typed item is local, do not let vague global prose trigger plan regeneration.
        if typed_issues:
            return False
    if review.get("repair_targets"):
        # Local question swaps should not trigger expensive focus-plan regeneration
        # unless the critic explicitly names area selection/deduplication itself.
        # Phrases like "focus area 2 opener" are local track-quality feedback.
        scoped_text = " ".join(
            str(s)
            for s in [
                *list(review.get("issues") or []),
                *list(review.get("repair_instructions") or []),
            ]
        ).lower()
        explicit_plan_terms = (
            "focus plan",
            "area selection",
            "wrong focus area",
            "wrong focus areas",
            "missing focus area",
            "missing focus areas",
            "same project",
            "same company",
            "duplicate focus",
            "duplicate focus area",
            "redundant focus",
            "redundant focus area",
            "merge focus",
            "merge area",
            "combine focus",
            "combine area",
            "collapse focus",
            "collapse area",
            "consolidate focus",
            "consolidate area",
        )
        if not any(term in scoped_text for term in explicit_plan_terms):
            return False
    texts = [
        *[str(s) for s in (review.get("issues") or [])],
        *[str(s) for s in (review.get("repair_instructions") or [])],
    ]
    joined = " ".join(texts).lower()
    problem_signals = (
        "duplic",
        "redundant",
        "overlap",
        "same project",
        "same company",
        "too similar",
        "merge focus",
        "merge area",
        "combine focus",
        "combine area",
        "collapse focus",
        "collapse area",
        "consolidate focus",
        "consolidate area",
    )
    return any(sig in joined for sig in problem_signals)


def _extract_plan_repair_hint(review: dict) -> str:
    """Pull the critic's specific complaints into a short string for the plan-regeneration prompt."""
    if not isinstance(review, dict):
        return ""
    fragments: list[str] = []
    for issue in (review.get("issues") or [])[:3]:
        text = str(issue or "").strip()
        if text:
            fragments.append(text)
    for instruction in (review.get("repair_instructions") or [])[:2]:
        text = str(instruction or "").strip()
        if text:
            fragments.append(text)
    return " | ".join(fragments)[:400]


def _dashboard_decision_surface_hint(*, resume: str, candidate: dict, target_role: str = "") -> str:
    """Detect role-relevant dashboard/reporting surfaces that the focus plan accidentally dropped."""
    if not _is_analyst_or_pm_role(target_role):
        return ""

    resume_lower = str(resume or "").lower()
    dashboard_lines = [
        line.strip()
        for line in str(resume or "").splitlines()
        if re.search(r"\b(dashboard|reporting|report|looker|metabase|tableau|power\s*bi)\b", line, re.I)
    ]
    if not dashboard_lines:
        return ""

    metric_terms = (
        "activation", "conversion", "retention", "refund", "sla", "support",
        "lag", "cohort", "funnel", "cac", "cpi", "cpm", "spend", "revenue",
        "buyer", "seller", "onboarding", "health", "operational", "bottleneck",
    )
    decision_terms = (
        "decision", "stakeholder", "product", "ops", "operations", "health",
        "reconcile", "reconciliation", "bottleneck", "sla", "support", "metric",
    )
    dashboard_signal = sum(
        1
        for term in metric_terms
        if term in resume_lower
    ) + sum(1 for term in decision_terms if term in resume_lower)
    if dashboard_signal < 3:
        return ""

    plan_text_parts: list[str] = []
    for area in candidate.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        plan_text_parts.extend(
            str(area.get(key) or "")
            for key in ("label", "focus_key", "anchor_context", "why_priority")
        )
        for snippet in area.get("resume_snippets") or []:
            plan_text_parts.append(str(snippet or ""))
        for sub_focus in _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or "")):
            plan_text_parts.extend(
                str(sub_focus.get(key) or "")
                for key in (
                    "label",
                    "sub_focus_key",
                    "surface_kind",
                    "why_priority",
                    "coverage_value",
                    "role_relevance_weight",
                )
            )
            plan_text_parts.extend(str(s or "") for s in (sub_focus.get("source_snippets") or []))
    plan_text = " ".join(plan_text_parts).lower()
    has_dashboard_surface = (
        "dashboard_reporting" in plan_text
        or "dashboard" in plan_text
        or "reporting" in plan_text
        or "reconciliation" in plan_text
        or "decision use" in plan_text
    )
    if has_dashboard_surface:
        return ""

    examples = " | ".join(dashboard_lines[:3])[:360]
    return (
        "The resume contains a concrete dashboard/reporting decision-use surface for this analytics role, "
        "but the focus plan omitted it. Preserve it as a focus_area or an explicit sub_focus with "
        "surface_kind='dashboard_reporting' unless it is only a thin output view. Resume evidence: "
        f"{examples}"
    )


async def _generate_focus_area_plan(
    *,
    resume: str,
    session_id: str,
    dedup_hint: str = "",
    target_role: str = "",
    surface_plan_v2: dict | None = None,
) -> dict:
    user_prompt = _focus_plan_user_prompt(
        resume=resume,
        dedup_hint=dedup_hint,
        target_role=target_role,
        surface_plan_v2=surface_plan_v2,
    )

    attempts = [
        ("primary", _MAP_GENERATOR_MODEL, 60.0),
    ]
    if _MAP_RESCUE_MODEL and _MAP_RESCUE_MODEL != _MAP_GENERATOR_MODEL:
        attempts.append(("rescue", _MAP_RESCUE_MODEL, 75.0))

    raw = None
    last_error: Exception | None = None
    selected_model = ""
    selected_source = ""
    for source, model, timeout in attempts:
        try:
            raw = await _run_focus_plan_call(
                LLMRouter(tier="medium", model_override=model, timeout_override=timeout),
                user_prompt,
                _FOCUS_PLAN_PRIMARY_MAX_TOKENS,
                _FOCUS_PLAN_RETRY_MAX_TOKENS,
            )
            if isinstance(raw, dict):
                selected_model = model
                selected_source = source
                break
        except Exception as exc:
            last_error = exc

    if not isinstance(raw, dict):
        error_note = f" Last error: {type(last_error).__name__}: {last_error}" if last_error else ""
        raise RuntimeError(f"Focus-area planning failed: no policy model returned usable output.{error_note}")

    def _validated_normalization_input(raw_plan: dict) -> tuple[dict, list[str], int, int]:
        raw_count = len(raw_plan.get("focus_areas") or []) if isinstance(raw_plan.get("focus_areas"), list) else 0
        validated, errors = _validate_schema(raw_plan, _FocusPlanSchema)
        if errors:
            print(f"[TrajectoryMap] Focus plan schema issues: {errors[:3]}")
        validated_count = len(validated.get("focus_areas") or [])
        normalization_candidate = {**raw_plan, "focus_areas": validated["focus_areas"]}
        if errors and raw_count > validated_count:
            normalization_candidate = raw_plan
        return normalization_candidate, errors, raw_count, validated_count

    normalization_input, plan_errors, raw_focus_area_count, validated_focus_area_count = _validated_normalization_input(raw)

    try:
        normalized = _normalize_map_candidate(normalization_input, resume=resume)
    except Exception as exc:
        rescue_error = ""
        if selected_source == "primary" and _MAP_RESCUE_MODEL and _MAP_RESCUE_MODEL != _MAP_GENERATOR_MODEL:
            try:
                rescue_prompt = "\n\n".join([
                    user_prompt,
                    "Primary planner output was launch-insufficient. Return 2-5 distinct role-relevant focus_areas.",
                    "Use SurfacePlanV2 recommendations when present. Do not pad with off-role or generic areas.",
                    f"Primary normalization failure: {type(exc).__name__}: {str(exc)[:600]}",
                    f"Primary raw focus areas: {_safe_json_preview(raw.get('focus_areas'), 3000)}",
                ])
                rescue_raw = await _run_focus_plan_call(
                    LLMRouter(tier="medium", model_override=_MAP_RESCUE_MODEL, timeout_override=75.0),
                    rescue_prompt,
                    _FOCUS_PLAN_PRIMARY_MAX_TOKENS,
                    _FOCUS_PLAN_RETRY_MAX_TOKENS,
                )
                if not isinstance(rescue_raw, dict):
                    raise RuntimeError(f"rescue returned {type(rescue_raw).__name__}")
                (
                    rescue_input,
                    rescue_errors,
                    rescue_raw_count,
                    rescue_validated_count,
                ) = _validated_normalization_input(rescue_raw)
                normalized = _normalize_map_candidate(rescue_input, resume=resume)
                raw = rescue_raw
                plan_errors = rescue_errors
                raw_focus_area_count = rescue_raw_count
                validated_focus_area_count = rescue_validated_count
                selected_model = _MAP_RESCUE_MODEL
                selected_source = "rescue_after_primary_insufficient"
            except Exception as rescue_exc:
                rescue_error = f"{type(rescue_exc).__name__}: {str(rescue_exc)[:800]}"
        if "normalized" not in locals():
            raise MapPreparationError(
                str(exc),
                {
                    "session_id": session_id,
                    "failure_family": "focus_plan_normalization",
                    "cause_type": type(exc).__name__,
                    "cause": str(exc)[:1000],
                    "rescue_error": rescue_error,
                    "raw_focus_area_count": raw_focus_area_count,
                    "validated_focus_area_count": validated_focus_area_count,
                    "schema_errors": plan_errors[:8],
                    "raw_focus_areas_preview": _safe_json_preview(raw.get("focus_areas") if isinstance(raw, dict) else raw, 5000),
                    "surface_plan_v2_focus_count": len((surface_plan_v2 or {}).get("focus_areas") or []) if isinstance(surface_plan_v2, dict) else 0,
                },
            ) from exc
    decision_surface_hint = _dashboard_decision_surface_hint(
        resume=resume,
        candidate=normalized,
        target_role=target_role,
    )
    if decision_surface_hint and not dedup_hint:
        print(
            f"[TrajectoryMap] Focus plan omitted role-relevant dashboard/reporting surface"
            + (f" for {session_id[:8]}" if session_id else "")
            + "; regenerating focus plan once with typed preservation hint"
        )
        repaired = await _generate_focus_area_plan(
            resume=resume,
            session_id=session_id,
            dedup_hint=decision_surface_hint,
            target_role=target_role,
            surface_plan_v2=surface_plan_v2,
        )
        repaired.setdefault("_focus_plan_repair_hints", []).append(decision_surface_hint)
        return repaired
    if decision_surface_hint:
        normalized.setdefault("_focus_plan_validation_warnings", []).append(decision_surface_hint)
    alignment_warnings = surface_plan_alignment_warnings(normalized, surface_plan_v2)
    if alignment_warnings:
        normalized.setdefault("_surface_plan_alignment_warnings", []).extend(alignment_warnings)
    n = len(normalized.get("focus_areas", []) or [])
    if n < _MAP_MIN_FOCUS_AREAS:
        raise MapPreparationError(
            f"Focus-area plan returned fewer than {_MAP_MIN_FOCUS_AREAS} usable areas (got {n}).",
            {
                "session_id": session_id,
                "failure_family": "focus_plan_normalization",
                "cause_type": "ValueError",
                "cause": f"Focus-area plan returned fewer than {_MAP_MIN_FOCUS_AREAS} usable areas (got {n}).",
                "raw_focus_area_count": raw_focus_area_count,
                "validated_focus_area_count": validated_focus_area_count,
                "normalized_focus_area_count": n,
                "schema_errors": plan_errors[:8],
                "raw_focus_areas_preview": _safe_json_preview(raw.get("focus_areas") if isinstance(raw, dict) else raw, 5000),
                "surface_plan_v2_focus_count": len((surface_plan_v2 or {}).get("focus_areas") or []) if isinstance(surface_plan_v2, dict) else 0,
            },
        )

    print(
        f"[TrajectoryMap] Planned {n} focus areas"
        + (f" for {session_id[:8]}" if session_id else "")
        + (f" via {selected_source}:{selected_model}" if selected_model else "")
    )
    return {
        **normalized,
        "_focus_plan_model": selected_model,
        "_focus_plan_source": selected_source,
        "_surface_plan_v2": surface_plan_v2 if isinstance(surface_plan_v2, dict) else {},
    }


def _build_critic_review(payload: dict, *, stage: str, critic_model: str) -> dict:
    """Normalise a raw critic response into the canonical review shape."""
    typed_issues: list[dict] = []
    for item in payload.get("typed_issues") or []:
        normalized = _normalized_typed_issue(item)
        if normalized:
            typed_issues.append(normalized)

    repair_targets: list[dict] = []
    for item in payload.get("repair_targets") or []:
        normalized = _normalized_repair_target(item)
        if normalized:
            repair_targets.append(normalized)

    if not typed_issues:
        for item in repair_targets:
            issue = _normalized_typed_issue({
                "issue_scope": item.get("issue_scope"),
                "focus_key": item.get("focus_key"),
                "path": item.get("path"),
                "severity": item.get("severity"),
                "action": item.get("action"),
                "reason": item.get("reason") or item.get("issue") or item.get("instruction"),
            })
            if issue:
                typed_issues.append(issue)

    return {
        "stage": stage,
        "critic_model": critic_model,
        "ready": bool(payload.get("ready", False)),
        "overall_score": _safe_float(payload.get("overall_score", 0), 0.0),
        "top_two_score": _safe_float(payload.get("top_two_score", 0), 0.0),
        # New fields from updated critic prompt; fall back to old names for backward compat
        "opener_quality_score": _safe_float(payload.get("opener_quality_score", payload.get("coverage_score", 0)), 0.0),
        "dimension_depth_score": _safe_float(payload.get("dimension_depth_score", payload.get("branch_richness_score", 0)), 0.0),
        "strengths": [str(s).strip() for s in (payload.get("strengths") or []) if str(s).strip()][:8],
        "issues": [str(s).strip() for s in (payload.get("issues") or []) if str(s).strip()][:8],
        "repair_instructions": [str(s).strip() for s in (payload.get("repair_instructions") or []) if str(s).strip()][:8],
        "focus_reviews": [
            {
                "focus_key": _clean_track_value(item.get("focus_key", "")),
                "label": _clean_track_value(item.get("label", "")),
                "score": _safe_float(item.get("score", 0), 0.0),
                "opener_issue": _clean_track_value(item.get("opener_issue", "")),
                "issues": [str(v).strip() for v in (item.get("issues") or []) if str(v).strip()][:4],
            }
            for item in (payload.get("focus_reviews") or [])
            if isinstance(item, dict)
        ][: _MAP_TARGET_FOCUS_AREAS],
        "typed_issues": typed_issues[:16],
        "repair_targets": repair_targets[:12],
    }


def _looks_like_focus_review(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(
        item.get("focus_key")
        and (
            "score" in item
            or "opener_issue" in item
            or "issues" in item
            or "label" in item
        )
    )


def _looks_like_typed_issue(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(item.get("issue_scope") or item.get("action")) and bool(item.get("reason") or item.get("issue"))


def _looks_like_repair_target(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(item.get("path")) and bool(item.get("instruction") or item.get("issue") or item.get("reason"))


def _critic_payload_completeness(item: dict) -> int:
    keys = {
        "ready",
        "overall_score",
        "top_two_score",
        "opener_quality_score",
        "dimension_depth_score",
        "strengths",
        "issues",
        "repair_instructions",
        "focus_reviews",
        "typed_issues",
        "repair_targets",
    }
    return sum(1 for key in keys if key in item)


def _coerce_critic_payload(raw: Any) -> tuple[dict, list[str]]:
    """Recover common model-authored critic shapes before Pydantic validation.

    Some providers return `[{"ready": ...}]` or a list of focus-review/issue
    fragments despite JSON-object instructions. Treat those as recoverable
    schema drift instead of replacing the critic with default scores.
    """
    if isinstance(raw, dict):
        return raw, []
    notes: list[str] = []
    if isinstance(raw, str):
        cleaned = raw.strip()
        if (
            cleaned.endswith(("[", "{", ",", ":"))
            and any(key in cleaned for key in ("overall_score", "focus_reviews", "repair_targets", "typed_issues"))
        ):
            return {
                "_critic_unrecoverable_shape": True,
                "_raw_malformed_critic": raw[:12000],
                "issues": ["critic returned truncated JSON object text"],
            }, ["critic returned truncated JSON object text"]
        parsed = _load_json_lenient(raw)
        if parsed is None:
            if (
                cleaned.startswith("{")
                or cleaned.startswith("```")
                or any(key in cleaned for key in ("overall_score", "focus_reviews", "repair_targets", "typed_issues"))
            ):
                return {
                    "_critic_unrecoverable_shape": True,
                    "_raw_malformed_critic": raw[:12000],
                    "issues": ["critic returned malformed JSON object text"],
                }, ["critic returned malformed JSON object text"]
            return raw, []
        raw = parsed
    if not isinstance(raw, list):
        return raw, []
    expanded_items: list[Any] = []
    for item in raw:
        if isinstance(item, str):
            try:
                parsed_item = json.loads(item)
            except json.JSONDecodeError:
                expanded_items.append(item)
                continue
            if isinstance(parsed_item, list):
                expanded_items.extend(parsed_item)
            else:
                expanded_items.append(parsed_item)
        else:
            expanded_items.append(item)
    dict_items = [item for item in expanded_items if isinstance(item, dict)]
    if not dict_items:
        string_items = [_clean_track_value(item) for item in expanded_items if _clean_track_value(item)]
        return {
            "_critic_unrecoverable_shape": True,
            "issues": string_items[:8],
        }, ["critic returned a list with no JSON objects"]
    notes.append(f"critic returned list; recovered {len(dict_items)} object(s)")

    full_payloads = [
        item for item in dict_items
        if _critic_payload_completeness(item) >= 2
        or any(key in item for key in ("ready", "overall_score", "focus_reviews", "repair_targets", "typed_issues"))
    ]
    if len(full_payloads) == 1:
        return full_payloads[0], notes

    if len(full_payloads) > 1:
        merged: dict[str, Any] = {}
        # Scalar scores come from the most complete payload; list fields are unioned.
        primary = sorted(full_payloads, key=_critic_payload_completeness, reverse=True)[0]
        for key in ("ready", "overall_score", "top_two_score", "opener_quality_score", "dimension_depth_score"):
            if key in primary:
                merged[key] = primary.get(key)
        for key in ("strengths", "issues", "repair_instructions", "focus_reviews", "typed_issues", "repair_targets"):
            values: list[Any] = []
            seen: set[str] = set()
            for item in full_payloads:
                raw_values = item.get(key)
                if not isinstance(raw_values, list):
                    continue
                for value in raw_values:
                    marker = json.dumps(value, sort_keys=True, ensure_ascii=True) if isinstance(value, (dict, list)) else str(value)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    values.append(value)
            if values:
                merged[key] = values
        return merged, notes

    focus_reviews = [item for item in dict_items if _looks_like_focus_review(item)]
    repair_targets = [item for item in dict_items if _looks_like_repair_target(item)]
    typed_issues = [item for item in dict_items if _looks_like_typed_issue(item)]
    issues = [
        _clean_track_value(item.get("issue") or item.get("reason") or item.get("message") or item.get("comment") or "")
        for item in dict_items
    ]
    issues = [item for item in issues if item]
    recovered = {
        "ready": False,
        "overall_score": 6.0,
        "top_two_score": 6.0,
        "opener_quality_score": 6.0,
        "dimension_depth_score": 6.0,
        "issues": issues[:8],
        "focus_reviews": focus_reviews[:_MAP_TARGET_FOCUS_AREAS],
        "typed_issues": typed_issues[:16],
        "repair_targets": repair_targets[:12],
    }
    return recovered, notes


async def _critique_map_candidate(
    *,
    resume: str,
    candidate: dict,
    stage: str,
    model_override: str | None = None,
    timeout_override: float = 90.0,
) -> dict:
    critic = LLMRouter(
        tier="medium",
        model_override=model_override or _MAP_CRITIC_MODEL,
        timeout_override=timeout_override,
    )
    user_prompt = _map_critic_user_prompt(resume=resume, candidate=candidate, stage=stage)
    strict_retry_prompt = "\n".join([
        user_prompt,
        "",
        "CRITICAL RETRY: Your previous response did not satisfy the contract.",
        "Return exactly one JSON object, not an array and not a list of strings.",
        "The object must contain ready, overall_score, top_two_score, opener_quality_score, dimension_depth_score, strengths, issues, repair_instructions, focus_reviews, typed_issues, and repair_targets.",
    ])
    compact_retry_prompt = _compact_map_critic_user_prompt(candidate=candidate, stage=f"{stage}_compact_schema_retry")

    async def _call_and_validate_with(llm: LLMRouter, prompt: str, max_tokens: int) -> tuple[dict, list[str], bool, str]:
        raw = await llm.call(
            system=_MAP_CRITIC_SYSTEM,
            user=prompt,
            max_tokens=max_tokens,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        coerced, coercion_notes = _coerce_critic_payload(raw)
        malformed_text = ""
        if isinstance(coerced, dict):
            malformed_text = str(coerced.pop("_raw_malformed_critic", "") or "")
            unrecoverable_shape = bool(coerced.pop("_critic_unrecoverable_shape", False))
        else:
            unrecoverable_shape = False
        validated, schema_errors = _validate_schema(coerced, _CriticSchema)
        return validated, [*coercion_notes, *schema_errors], unrecoverable_shape, malformed_text

    async def _repair_malformed_critic_text(malformed_text: str) -> tuple[dict, list[str], LLMRouter, bool]:
        if not malformed_text or not _MAP_CRITIC_SCHEMA_RESCUE_MODEL:
            raise RuntimeError("critic returned unrecoverable malformed JSON without repairable text")
        repair_critic = LLMRouter(
            tier="medium",
            model_override=_MAP_CRITIC_SCHEMA_RESCUE_MODEL,
            timeout_override=45.0,
        )
        repair_prompt = "\n".join([
            "You are a JSON repair utility. Do not critique the map.",
            "Repair the malformed critic output into exactly one JSON object with this schema:",
            '{"ready": boolean, "overall_score": number, "top_two_score": number, "opener_quality_score": number, "dimension_depth_score": number, "strengths": string[], "issues": string[], "repair_instructions": string[], "focus_reviews": [{"focus_key": string, "label": string, "score": number, "opener_issue": string, "issues": string[]}], "typed_issues": [], "repair_targets": []}',
            "Preserve the critic's content. If a field is missing, use a neutral default. Return JSON object only.",
            "",
            "Malformed critic output:",
            malformed_text[:9000],
        ])
        validated, schema_errors, unrecoverable_shape, _ = await _call_and_validate_with(repair_critic, repair_prompt, 1200)
        return validated, schema_errors, repair_critic, unrecoverable_shape

    async def _schema_rescue_critic() -> tuple[dict, list[str], LLMRouter, bool]:
        if not _MAP_CRITIC_SCHEMA_RESCUE_MODEL or _MAP_CRITIC_SCHEMA_RESCUE_MODEL == critic.model:
            raise RuntimeError("critic returned JSON array without object after compact schema retry")
        rescue_critic = LLMRouter(
            tier="medium",
            model_override=_MAP_CRITIC_SCHEMA_RESCUE_MODEL,
            timeout_override=60.0,
        )
        validated, schema_errors, unrecoverable_shape, _ = await _call_and_validate_with(
            rescue_critic,
            compact_retry_prompt,
            1400,
        )
        return validated, schema_errors, rescue_critic, unrecoverable_shape

    primary_prompt = compact_retry_prompt if stage.endswith("_repair") else user_prompt

    try:
        validated, schema_errors, unrecoverable_shape, malformed_text = await _call_and_validate_with(
            critic,
            primary_prompt,
            _MAP_CRITIC_MAX_TOKENS,
        )
        if unrecoverable_shape and malformed_text:
            print(f"[TrajectoryMap] Critic returned malformed JSON text during {stage}; trying fast schema repair")
            repaired, repair_errors, repair_critic, repair_unrecoverable = await _repair_malformed_critic_text(malformed_text)
            if not repair_unrecoverable:
                review = _build_critic_review(
                    repaired,
                    stage=stage,
                    critic_model=f"{critic.model}->json_repair:{repair_critic.model}",
                )
                review["schema_repair_used"] = True
                review["primary_critic_model"] = critic.model
                if repair_errors:
                    print(f"[TrajectoryMap] Critic JSON repair issues during {stage}: {repair_errors[:3]}")
                return review
        if unrecoverable_shape:
            print(f"[TrajectoryMap] Critic returned unrecoverable array shape during {stage}; retrying strict schema once")
            validated, schema_errors, unrecoverable_shape, malformed_text = await _call_and_validate_with(critic, strict_retry_prompt, _MAP_CRITIC_MAX_TOKENS)
            if unrecoverable_shape and malformed_text:
                repaired, repair_errors, repair_critic, repair_unrecoverable = await _repair_malformed_critic_text(malformed_text)
                if not repair_unrecoverable:
                    review = _build_critic_review(
                        repaired,
                        stage=stage,
                        critic_model=f"{critic.model}->json_repair:{repair_critic.model}",
                    )
                    review["schema_repair_used"] = True
                    review["primary_critic_model"] = critic.model
                    if repair_errors:
                        print(f"[TrajectoryMap] Critic JSON repair issues during {stage}: {repair_errors[:3]}")
                    return review
            if unrecoverable_shape:
                print(f"[TrajectoryMap] Critic strict retry still returned array during {stage}; retrying compact critic schema")
                validated, schema_errors, unrecoverable_shape, malformed_text = await _call_and_validate_with(
                    critic,
                    compact_retry_prompt,
                    min(_MAP_CRITIC_MAX_TOKENS, 1400),
                )
                if unrecoverable_shape and malformed_text:
                    repaired, repair_errors, repair_critic, repair_unrecoverable = await _repair_malformed_critic_text(malformed_text)
                    if not repair_unrecoverable:
                        review = _build_critic_review(
                            repaired,
                            stage=stage,
                            critic_model=f"{critic.model}->json_repair:{repair_critic.model}",
                        )
                        review["schema_repair_used"] = True
                        review["primary_critic_model"] = critic.model
                        if repair_errors:
                            print(f"[TrajectoryMap] Critic JSON repair issues during {stage}: {repair_errors[:3]}")
                        return review
                if unrecoverable_shape:
                    print(
                        f"[TrajectoryMap] Critic compact retry still returned array during {stage}; "
                        f"trying schema rescue model {_MAP_CRITIC_SCHEMA_RESCUE_MODEL}"
                    )
                    validated, schema_errors, rescue_critic, unrecoverable_shape = await _schema_rescue_critic()
                    if unrecoverable_shape:
                        raise RuntimeError("critic returned JSON array without object after schema rescue")
                    review = _build_critic_review(
                        validated,
                        stage=stage,
                        critic_model=f"{critic.model}->schema_rescue:{rescue_critic.model}",
                    )
                    review["schema_rescue_used"] = True
                    review["primary_critic_model"] = critic.model
                    if schema_errors:
                        print(f"[TrajectoryMap] Critic schema rescue issues during {stage}: {schema_errors[:3]}")
                    return review
        if schema_errors:
            print(f"[TrajectoryMap] Critic schema issues during {stage}: {schema_errors[:3]}")
        return _build_critic_review(validated, stage=stage, critic_model=critic.model)
    except Exception as exc:
        affordable_tokens = _affordable_token_budget_from_error(exc)
        if affordable_tokens and affordable_tokens < _MAP_CRITIC_MAX_TOKENS:
            try:
                validated, schema_errors, unrecoverable_shape, malformed_text = await _call_and_validate_with(critic, primary_prompt, affordable_tokens)
                if unrecoverable_shape and malformed_text:
                    repaired, repair_errors, repair_critic, repair_unrecoverable = await _repair_malformed_critic_text(malformed_text)
                    if not repair_unrecoverable:
                        review = _build_critic_review(
                            repaired,
                            stage=stage,
                            critic_model=f"{critic.model}->json_repair:{repair_critic.model}",
                        )
                        review["schema_repair_used"] = True
                        review["primary_critic_model"] = critic.model
                        return review
                if unrecoverable_shape:
                    validated, schema_errors, unrecoverable_shape, malformed_text = await _call_and_validate_with(critic, strict_retry_prompt, affordable_tokens)
                    if unrecoverable_shape:
                        validated, schema_errors, unrecoverable_shape, malformed_text = await _call_and_validate_with(
                            critic,
                            compact_retry_prompt,
                            min(affordable_tokens, 1200),
                        )
                        if unrecoverable_shape:
                            validated, schema_errors, rescue_critic, unrecoverable_shape = await _schema_rescue_critic()
                            if unrecoverable_shape:
                                raise RuntimeError("critic returned JSON array without object after schema rescue")
                            review = _build_critic_review(
                                validated,
                                stage=stage,
                                critic_model=f"{critic.model}->schema_rescue:{rescue_critic.model}",
                            )
                            review["schema_rescue_used"] = True
                            review["primary_critic_model"] = critic.model
                            return review
                if schema_errors:
                    print(f"[TrajectoryMap] Critic schema issues (retry) during {stage}: {schema_errors[:3]}")
                return _build_critic_review(validated, stage=stage, critic_model=critic.model)
            except Exception:
                pass
        raise RuntimeError(f"Map critic failed during {stage}; refusing fallback review: {type(exc).__name__}: {exc}") from exc


async def _audit_map_candidate(*, resume: str, candidate: dict, stage: str) -> dict:
    """
    Cheap second-opinion map audit.

    This is intentionally advisory. It must never become a blocking precondition
    before Sonnet rescue or final map readiness.
    """
    if not _MAP_AUDIT_MODEL or _MAP_AUDIT_MODEL == _MAP_CRITIC_MODEL:
        return {}
    try:
        return await _critique_map_candidate(
            resume=resume,
            candidate=candidate,
            stage=f"{stage}_audit",
            model_override=_MAP_AUDIT_MODEL,
            timeout_override=60.0,
        )
    except Exception as exc:
        return {
            "stage": f"{stage}_audit",
            "critic_model": _MAP_AUDIT_MODEL,
            "ready": False,
            "overall_score": 0.0,
            "top_two_score": 0.0,
            "issues": [f"audit_failed: {type(exc).__name__}: {str(exc)[:180]}"],
            "repair_instructions": [],
            "focus_reviews": [],
            "advisory_only": True,
        }


def _compact_focus_plan_for_audit(candidate: dict) -> dict:
    areas: list[dict] = []
    for area in (candidate.get("focus_areas") or [])[:_MAP_TARGET_FOCUS_AREAS]:
        if not isinstance(area, dict):
            continue
        areas.append({
            "focus_key": _clean_track_value(area.get("focus_key", "")),
            "label": _clean_track_value(area.get("label", "")),
            "anchor_context": _clean_track_value(area.get("anchor_context", ""))[:220],
            "coverage_value": _focus_area_priority_value(area),
            "why_priority": _clean_track_value(area.get("why_priority", ""))[:160],
            "sub_focuses": [
                {
                    "label": sf.get("label", ""),
                    "surface_kind": sf.get("surface_kind", ""),
                    "role_relevance_weight": sf.get("role_relevance_weight"),
                    "profile_importance_weight": sf.get("profile_importance_weight"),
                    "evidence_strength": sf.get("evidence_strength"),
                    "claim_risk": sf.get("claim_risk"),
                    "coverage_value": sf.get("coverage_value"),
                }
                for sf in _normalize_sub_focuses(
                    area.get("sub_focuses"),
                    focus_key=_clean_track_value(area.get("focus_key", "")),
                )[:4]
            ],
            "resume_snippets": list(area.get("resume_snippets", []) or [])[:2],
        })
    return {"focus_areas": areas}


async def _audit_focus_plan_candidate(*, resume: str, candidate: dict, stage: str, target_role: str = "") -> dict:
    """
    Cheap DeepSeek focus-plan audit.

    The audit sees only ranking/overlap evidence, not full generated tracks. It is
    advisory by design and is consumed only as a warning/hint layer.
    """
    if not _MAP_AUDIT_MODEL or _MAP_AUDIT_MODEL == _MAP_CRITIC_MODEL:
        return {}
    llm = LLMRouter(
        tier="small",
        model_override=_MAP_AUDIT_MODEL,
        timeout_override=20.0,
    )
    prompt = "\n".join([
        f"Audit stage: {stage}",
        f"Target role: {target_role or 'unspecified'}",
        "",
        "Candidate resume excerpt:",
        resume[:4500],
        "",
        "Focus plan:",
        _json_text(_compact_focus_plan_for_audit(candidate)),
        "",
        "Check only these launch-plan risks:",
        "- duplicate or overlapping top-two surfaces",
        "- off-role work promoted above role-relevant work",
        "- source snippets that do not support the selected focus",
        "- ranking that would make turn 1 start on the wrong anchor",
        "",
        "Return JSON only:",
        '{"advisory_only": true, "ready": true, "warnings": ["..."], "top_two_distinct": true, "off_role_promotion": false, "ranking_concern": false, "suggested_swap": {"replace_focus_key": "", "with_focus_key": "", "reason": ""}}',
    ])
    try:
        raw = await llm.call(
            system="You are a cheap advisory focus-plan auditor. Return JSON only. Never rewrite the map.",
            user=prompt,
            max_tokens=900,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        payload = raw if isinstance(raw, dict) else (_load_json_lenient(raw) if isinstance(raw, str) else {})
        payload = payload if isinstance(payload, dict) else {}
        return {
            "stage": f"{stage}_focus_plan_audit",
            "critic_model": _MAP_AUDIT_MODEL,
            "advisory_only": True,
            "ready": bool(payload.get("ready", True)),
            "warnings": [str(v).strip() for v in (payload.get("warnings") or []) if str(v).strip()][:6],
            "top_two_distinct": bool(payload.get("top_two_distinct", True)),
            "off_role_promotion": bool(payload.get("off_role_promotion", False)),
            "ranking_concern": bool(payload.get("ranking_concern", False)),
            "suggested_swap": payload.get("suggested_swap") if isinstance(payload.get("suggested_swap"), dict) else {},
        }
    except Exception as exc:
        return {
            "stage": f"{stage}_focus_plan_audit",
            "critic_model": _MAP_AUDIT_MODEL,
            "advisory_only": True,
            "ready": False,
            "warnings": [f"audit_failed: {type(exc).__name__}: {str(exc)[:180]}"],
            "top_two_distinct": True,
            "off_role_promotion": False,
            "ranking_concern": False,
        }


def _compact_ladder_quality_for_audit(candidate: dict) -> dict:
    areas: list[dict] = []
    for area in (candidate.get("focus_areas") or [])[:_MAP_LAUNCH_TRACK_COUNT]:
        if not isinstance(area, dict):
            continue
        ladder = area.get("question_ladder") if isinstance(area.get("question_ladder"), list) else []
        areas.append({
            "focus_key": _clean_track_value(area.get("focus_key", "")),
            "label": _clean_track_value(area.get("label", "")),
            "surface_kind": _primary_surface_kind(area),
            "coverage_value": _focus_area_priority_value(area),
            "question_ladder": [
                {
                    "posture": _clean_track_value(item.get("posture", "")),
                    "main_question": _clean_track_value(item.get("main_question", "")),
                    "expected_space": list(item.get("expected_space") or [])[:4],
                    "information_gain": _clean_track_value(item.get("information_gain", "")),
                    "voice_complexity": _clean_track_value(item.get("voice_complexity", "")),
                }
                for item in ladder
                if isinstance(item, dict)
            ],
        })
    return {"focus_areas": areas}


async def _audit_ladder_quality_candidate(*, candidate: dict, stage: str, target_role: str = "") -> dict:
    """
    Cheap advisory audit for ladder expected-space and voice quality.

    This never blocks launch readiness. If the signal is bad enough, the
    caller records it for Sonnet-targeted verification/repair in a later pass.
    """
    if not _MAP_AUDIT_MODEL or _MAP_AUDIT_MODEL == _MAP_CRITIC_MODEL:
        return {}
    llm = LLMRouter(
        tier="small",
        model_override=_MAP_AUDIT_MODEL,
        timeout_override=18.0,
    )
    prompt = "\n".join([
        f"Audit stage: {stage}",
        f"Target role: {target_role or 'unspecified'}",
        "",
        "Launch question ladders:",
        _json_text(_compact_ladder_quality_for_audit(candidate)),
        "",
        "Evaluate only these signals:",
        "- expected_space quality: does it name broad answer areas rather than a script?",
        "- voice complexity: would an Indian candidate understand the spoken question?",
        "- closed-choice risk: does the question feel like yes/no or multiple choice without an escape hatch?",
        "- low-information risk: does it ask trivia that would not change a hiring decision?",
        "- prosecutor-streak risk: do too many questions sound like pressure too early?",
        "",
        "Good guided question: 'Were you mainly trying to improve paid conversion, reduce low-intent trials, test urgency, or was something else more important? Talk me through how you framed that decision.'",
        "Bad closed question: 'Was it conversion, low-intent trials, or urgency?'",
        "Bad jargon question: 'What was the temporal maturity window for analytical integrity?'",
        "",
        "Return JSON only:",
        '{"advisory_only": true, "ready": true, "warnings": ["..."], "voice_complexity_flags": [{"focus_key": "", "posture": "", "reason": ""}], "expected_space_flags": [{"focus_key": "", "posture": "", "reason": ""}], "low_information_flags": [{"focus_key": "", "posture": "", "reason": ""}], "closed_question_flags": [{"focus_key": "", "posture": "", "reason": ""}], "sonnet_escalation_recommended": false}',
    ])
    try:
        raw = await llm.call(
            system="You are a cheap advisory question-ladder auditor. Return JSON only. Do not rewrite questions.",
            user=prompt,
            max_tokens=1000,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        payload = raw if isinstance(raw, dict) else (_load_json_lenient(raw) if isinstance(raw, str) else {})
        payload = payload if isinstance(payload, dict) else {}

        def _flags(key: str) -> list[dict]:
            items = payload.get(key)
            if not isinstance(items, list):
                return []
            return [
                item
                for item in items
                if isinstance(item, dict) and _clean_track_value(item.get("reason", ""))
            ][:8]

        return {
            "stage": f"{stage}_ladder_quality_audit",
            "critic_model": _MAP_AUDIT_MODEL,
            "advisory_only": True,
            "ready": bool(payload.get("ready", True)),
            "warnings": [str(v).strip() for v in (payload.get("warnings") or []) if str(v).strip()][:6],
            "voice_complexity_flags": _flags("voice_complexity_flags"),
            "expected_space_flags": _flags("expected_space_flags"),
            "low_information_flags": _flags("low_information_flags"),
            "closed_question_flags": _flags("closed_question_flags"),
            "sonnet_escalation_recommended": bool(payload.get("sonnet_escalation_recommended", False)),
        }
    except Exception as exc:
        return {
            "stage": f"{stage}_ladder_quality_audit",
            "critic_model": _MAP_AUDIT_MODEL,
            "advisory_only": True,
            "ready": False,
            "warnings": [f"ladder_audit_failed: {type(exc).__name__}: {str(exc)[:180]}"],
            "sonnet_escalation_recommended": False,
        }


async def _take_audit_if_ready(task: "asyncio.Task[dict] | None") -> dict:
    if task is None:
        return {}
    if task.done():
        try:
            return task.result()
        except Exception as exc:
            return {"advisory_only": True, "issues": [f"audit_result_failed: {type(exc).__name__}: {exc}"]}
    return {
        "stage": "audit_pending",
        "critic_model": _MAP_AUDIT_MODEL,
        "ready": False,
        "overall_score": 0.0,
        "issues": ["audit still running; not blocking map readiness"],
        "repair_instructions": [],
        "focus_reviews": [],
        "advisory_only": True,
        "pending": True,
    }


def _review_score(review: dict | None) -> float:
    if not isinstance(review, dict):
        return 0.0
    try:
        return float(review.get("overall_score", 0) or 0)
    except Exception:
        return 0.0


def _review_is_ready(review: dict | None) -> bool:
    if not isinstance(review, dict):
        return False
    if bool(review.get("ready")):
        return True
    return _review_score(review) >= _MAP_MIN_READY_SCORE


def _has_targeted_repairs(review: dict | None) -> bool:
    """Return True if the critic identified fixable issues that warrant a repair pass.

    This forces re-generation even when score >= _MAP_MIN_READY_SCORE, closing the
    case where a 7.2 map has explicit repair instructions that were silently dropped.
    """
    if not isinstance(review, dict):
        return False
    for issue in review.get("typed_issues") or []:
        if not isinstance(issue, dict):
            continue
        action = _normalize_repair_action(issue.get("action"), issue.get("issue_scope", ""))
        if action in {"surgical_repair", "track_repair", "plan_repair"}:
            return True
    for target in review.get("repair_targets") or []:
        if isinstance(target, dict) and _clean_track_value(target.get("path", "")):
            return True
    repair_instructions = review.get("repair_instructions") or []
    if len(repair_instructions) >= 2:
        return True
    if not repair_instructions and not review.get("focus_reviews"):
        return False
    focus_reviews = review.get("focus_reviews") or []
    for fr in focus_reviews:
        if isinstance(fr, dict) and (fr.get("issues") or fr.get("opener_issue")):
            return True
    return False


def _has_launch_ready_priority_tracks(review: dict | None) -> bool:
    """True when the first launch-critical focus tracks already clear the critic gate."""
    if not isinstance(review, dict):
        return False
    focus_reviews = [item for item in (review.get("focus_reviews") or []) if isinstance(item, dict)]
    if len(focus_reviews) < _MAP_MIN_FOCUS_AREAS:
        return False
    ready_count = 0
    for item in focus_reviews[:_MAP_MIN_FOCUS_AREAS]:
        try:
            score = float(item.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        opener_issue = str(item.get("opener_issue") or "").strip()
        if score >= _MAP_MIN_READY_SCORE and not _opener_issue_blocks_launch(opener_issue, score):
            ready_count += 1
    return ready_count >= _MAP_MIN_FOCUS_AREAS


def _opener_issue_blocks_launch(opener_issue: str, score: float) -> bool:
    """Classify critic opener notes without treating harmless prose as a fatal issue."""
    text = _clean_track_value(opener_issue).lower()
    if not text:
        return False
    harmless_markers = (
        "none",
        "no issue",
        "no blocking",
        "not blocking",
        "acceptable",
        "minor",
        "strong",
        "solid",
        "well-anchored",
        "well anchored",
    )
    if any(marker in text for marker in harmless_markers) and score >= _MAP_MIN_READY_SCORE:
        return False
    blocking_markers = (
        "wrong",
        "misaligned",
        "unsupported",
        "generic",
        "malformed",
        "broken",
        "missing",
        "empty",
        "not anchored",
        "off-role",
        "off role",
    )
    if any(marker in text for marker in blocking_markers):
        return True
    return score < (_MAP_MIN_READY_SCORE + 0.3)


def _startup_ready_without_repair(review: dict | None) -> bool:
    """Startup is allowed when the critic says ready and the first two tracks are launch-safe."""
    if not _review_is_ready(review):
        return False
    try:
        top_two_score = float((review or {}).get("top_two_score", 0) or 0)
    except (TypeError, ValueError):
        top_two_score = 0.0
    # The Sonnet critic's top_two_score is the startup authority. Focus-level
    # notes still surface in the report, but minor/local notes should not pull
    # the whole map into a second full generation pass.
    return top_two_score >= 8.0 or _has_launch_ready_priority_tracks(review)


def _coerce_llm_track(raw_track: dict | None, *, seed: dict, next_focus_label: str, source_override: str | None = None) -> dict:
    if not isinstance(raw_track, dict):
        raise RuntimeError(f"LLM track missing for focus '{seed.get('focus_key', '')}'.")

    # V3 launch-lite schema. This is the startup-only contract; it is converted
    # into the existing runtime ladder/dimension shape before selectors see it.
    if raw_track.get("launch_track_lite") or raw_track.get("map_schema_version") == "v3_launch_lite":
        parsed = _parse_launch_track_lite(raw_track, seed)
        dims = parsed.get("dimensions", [])
        llm_branches = [
            *[f"question_ladder[{idx}].main_question" for idx, _ in enumerate(parsed.get("question_ladder") or [])],
            *[f"dimensions[{idx}]" for idx, _ in enumerate(dims)],
        ]
        return {
            "track": parsed,
            "source": source_override or "llm",
            "llm_branches": llm_branches,
            "fallback_branches": [],
            "llm_branch_count": len(llm_branches),
            "fallback_branch_count": 0,
        }

    # V2 ladder schema. Legacy aliases may be present, but the ladder is the
    # authoritative question contract.
    if "question_ladder" in raw_track or "opener" in raw_track or "dimensions" in raw_track:
        parsed = _parse_dimension_output(raw_track, seed)
        parsed.setdefault("candidate_q4_options", [])
        dims = parsed.get("dimensions", [])
        llm_branches = [d["id"] for d in dims]
        return {
            "track": parsed,
            "source": source_override or "llm",
            "llm_branches": llm_branches,
            "fallback_branches": [],
            "llm_branch_count": len(llm_branches),
            "fallback_branch_count": 0,
        }

    # Legacy sprint/branch schema — backward compat for old maps in Redis
    cleaned_result: dict[str, dict[str, str]] = {}
    llm_branches: list[str] = []
    for sprint_key in _SPRINT_KEYS:
        sprint = raw_track.get(sprint_key, {})
        if not isinstance(sprint, dict):
            sprint = {}
        cleaned_sprint: dict[str, str] = {}
        for branch in _VALID_BRANCHES:
            value = _clean_track_value(sprint.get(branch, ""))
            branch_key = f"{sprint_key}.{branch}"
            if value:
                cleaned_sprint[branch] = value
                llm_branches.append(branch_key)
        if _VALID_BRANCHES - set(cleaned_sprint):
            raise RuntimeError(f"LLM track for {seed.get('focus_key')} missing {sprint_key} branches.")
        cleaned_result[sprint_key] = cleaned_sprint

    return {
        "track": cleaned_result,
        "source": source_override or "llm",
        "llm_branches": llm_branches,
        "fallback_branches": [],
        "llm_branch_count": len(llm_branches),
        "fallback_branch_count": 0,
    }


def _candidate_to_runtime_map(
    *,
    resume: str,
    candidate: dict,
    pass_one_review: dict | None,
    final_review: dict | None,
    session_id: str = "",
) -> dict:
    focus_areas_raw = list(candidate.get("focus_areas", []) or [])
    focus_areas: list[dict] = []
    for index, area in enumerate(focus_areas_raw[:_MAP_TARGET_FOCUS_AREAS]):
        next_focus_label = (
            str(focus_areas_raw[(index + 1) % len(focus_areas_raw)].get("label", "") or "").strip()
            if len(focus_areas_raw) > 1
            else "another area from the candidate's background"
        )
        seed = {
            "label": str(area.get("label", "") or f"Focus Area {index + 1}").strip(),
            "focus_key": str(area.get("focus_key", "") or f"focus_{index + 1}").strip(),
            "anchor_context": str(area.get("anchor_context", "") or "").strip(),
            "sub_focuses": _normalize_sub_focuses(
                area.get("sub_focuses"),
                focus_key=str(area.get("focus_key", "") or f"focus_{index + 1}").strip(),
            ),
            "resume_snippets": list(area.get("resume_snippets", []) or []),
        }
        if not seed["resume_snippets"]:
            seed["resume_snippets"] = _extract_resume_snippets(resume, seed, limit=3)
        if not seed["anchor_context"]:
            seed["anchor_context"] = seed["resume_snippets"][0] if seed["resume_snippets"] else seed["label"]
        track_result = _coerce_llm_track(
            area.get("track"),
            seed=seed,
            next_focus_label=next_focus_label,
            source_override=str(area.get("_gen_source", "") or ""),
        )
        track_data = track_result["track"]
        explicit_schema = str(track_data.get("map_schema_version", "") or "")
        schema_version = explicit_schema or ("v2_ladder" if "question_ladder" in track_data else "sprint")
        if schema_version == "v2_ladder":
            track_data["legacy_compat"] = _legacy_compat_from_v2_track(track_data)
            track_data["opener"] = track_data["legacy_compat"]["opener"]
            track_data["dimensions"] = track_data["legacy_compat"]["dimensions"]
            track_data["recovery"] = track_data["legacy_compat"]["recovery"]
            track_data["candidate_q4_options"] = track_data["legacy_compat"]["candidate_q4_options"]
            track_data["assessment_dimensions"] = track_data["legacy_compat"]["dimensions"]
        elif schema_version == "v3_launch_lite":
            track_data["legacy_compat"] = _legacy_compat_from_v2_track(track_data)
            track_data["opener"] = track_data["legacy_compat"]["opener"]
            track_data["dimensions"] = track_data["legacy_compat"]["dimensions"]
            track_data["recovery"] = track_data["legacy_compat"]["recovery"]
            track_data["candidate_q4_options"] = track_data["legacy_compat"]["candidate_q4_options"]
            track_data["assessment_dimensions"] = track_data["legacy_compat"]["dimensions"]
        focus_areas.append({
            "map_schema_version": schema_version if schema_version in {"v2_ladder", "v3_launch_lite"} else "legacy_sprint",
            "primary_question_contract": "launch_track_lite" if schema_version == "v3_launch_lite" else ("question_ladder" if schema_version == "v2_ladder" else "legacy_sprint_branches"),
            "legacy_fields_authority": "compatibility_only" if schema_version in {"v2_ladder", "v3_launch_lite"} else "authoritative_legacy",
            "label": seed["label"],
            "focus_key": seed["focus_key"],
            "anchor_context": seed["anchor_context"],
            "sub_focuses": seed["sub_focuses"],
            "resume_snippets": seed["resume_snippets"][:3],
            "coverage_value": _focus_area_priority_value({**area, "sub_focuses": seed["sub_focuses"]}),
            "track_source": track_result.get("source", "llm"),
            "track_model": str(area.get("_gen_model", "") or ""),
            "track_latency_ms": int(area.get("_track_latency_ms", 0) or 0),
            "generation_attempt_errors": list(area.get("_generation_attempt_errors", []) or []),
            "track_generation_strategy": str(area.get("_track_generation_strategy", "") or ""),
            "repair_strategy": str(area.get("_repair_strategy", "") or ""),
            "repair_target_count": int(area.get("_repair_target_count", 0) or 0),
            "repair_provenance": list(area.get("_repair_provenance", []) or []),
            "track_schema": schema_version,
            "llm_branch_count": int(track_result.get("llm_branch_count", 0) or 0),
            "fallback_branch_count": int(track_result.get("fallback_branch_count", 0) or 0),
            "llm_branches": list(track_result.get("llm_branches", []) or []),
            "fallback_branches": list(track_result.get("fallback_branches", []) or []),
            "why_priority": str(area.get("why_priority", "") or "").strip(),
            **track_data,
        })

    if session_id:
        print(
            f"[TrajectoryMap] Finalized two-pass map with {len(focus_areas)} focus areas for {session_id[:8]}"
        )

    focus_areas = [
        area for _, area in sorted(
            enumerate(focus_areas),
            key=lambda item: (-_focus_area_priority_value(item[1]), item[0]),
        )
    ]

    return {
        "map_schema_version": "v2_ladder",
        "primary_question_contract": "question_ladder",
        "legacy_fields_authority": "compatibility_only",
        "focus_areas": focus_areas,
        "generated_at": time.time(),
        "pending_hydration_focus_keys": [],
        "generation_strategy": "two_pass_full_resume_reasoning",
        "pass_1_review": pass_one_review or {},
        "quality_review": final_review or {},
        "generation_notes": str(candidate.get("notes", "") or "").strip(),
    }


def _repair_provenance_for_candidate(candidate_or_map: dict) -> list[dict]:
    repairs: list[dict] = []
    for area in candidate_or_map.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        repairs.extend([r for r in (area.get("_repair_provenance") or area.get("repair_provenance") or []) if isinstance(r, dict)])
    return repairs


def _repair_summary(candidate_or_map: dict) -> dict:
    repairs = _repair_provenance_for_candidate(candidate_or_map)
    by_scope: dict[str, int] = {}
    by_acceptance: dict[str, int] = {}
    for repair in repairs:
        scope = str(repair.get("issue_scope") or "field_level")
        accepted_by = str(repair.get("accepted_by") or "")
        by_scope[scope] = by_scope.get(scope, 0) + 1
        by_acceptance[accepted_by] = by_acceptance.get(accepted_by, 0) + 1
    return {
        "count": len(repairs),
        "by_scope": by_scope,
        "by_acceptance": by_acceptance,
        "repairs": repairs[:20],
    }


def _can_skip_full_repair_critic(candidate: dict, *, plan_repaired: bool) -> bool:
    if plan_repaired:
        return False
    for area in candidate.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        strategy = str(area.get("_track_generation_strategy") or "")
        if strategy and strategy not in {"surgical_question_patch", "preserved_high_score_track", "preserved_untouched_track"}:
            return False
    repairs = _repair_provenance_for_candidate(candidate)
    if not repairs or len(repairs) > 3:
        return False
    return all(str(item.get("accepted_by") or "") == "field_verifier" for item in repairs)


def _field_verified_review(previous_review: dict, repaired_candidate: dict) -> dict:
    repairs = _repair_provenance_for_candidate(repaired_candidate)
    repaired_fields = {
        (str(repair.get("focus_key") or ""), str(repair.get("path") or ""))
        for repair in repairs
    }

    def _is_repaired_issue(issue: dict) -> bool:
        return any(
            str(issue.get("focus_key") or "") == focus_key
            and str(issue.get("path") or "") == path
            for focus_key, path in repaired_fields
        )

    focus_reviews: list[dict] = []
    for item in (previous_review or {}).get("focus_reviews", []):
        if not isinstance(item, dict):
            continue
        updated = dict(item)
        focus_key = str(updated.get("focus_key") or "")
        if any(key == focus_key for key, _ in repaired_fields):
            updated["score"] = max(_safe_float(updated.get("score", 0), 0.0), 8.0)
            if (focus_key, "opener") in repaired_fields:
                updated["opener_issue"] = ""
            repaired_paths = {path for key, path in repaired_fields if key == focus_key}
            updated["issues"] = [
                issue for issue in (updated.get("issues") or [])
                if not any(path and path in str(issue) for path in repaired_paths)
            ]
        focus_reviews.append(updated)
    return {
        **(previous_review or {}),
        "stage": "pass_1_field_verified_repair",
        "ready": True,
        "overall_score": max(_review_score(previous_review), 8.0),
        "top_two_score": max(_safe_float((previous_review or {}).get("top_two_score", 0), 0.0), 8.0),
        "field_verified_repair": True,
        "focus_reviews": focus_reviews or (previous_review or {}).get("focus_reviews", []),
        "repair_targets": [
            target for target in (previous_review or {}).get("repair_targets", [])
            if isinstance(target, dict) and not _is_repaired_issue(target)
        ],
        "typed_issues": [
            issue for issue in (previous_review or {}).get("typed_issues", [])
            if isinstance(issue, dict) and not _is_repaired_issue(issue)
        ],
        "repair_summary": _repair_summary(repaired_candidate),
        "repair_instructions": [
            str(item)
            for item in (previous_review or {}).get("repair_instructions", [])
            if "opener" not in str(item).lower() and "question" not in str(item).lower()
        ][:4],
    }


def _focus_key_for_area(area: dict) -> str:
    return _clean_track_value(area.get("focus_key", "")) if isinstance(area, dict) else ""


def _candidate_focus_subset(candidate: dict, *, focus_keys: list[str] | None = None, count: int | None = None) -> dict:
    areas = [dict(area) for area in (candidate.get("focus_areas") or []) if isinstance(area, dict)]
    if focus_keys is not None:
        wanted = [key for key in focus_keys if key]
        by_key = {_focus_key_for_area(area): area for area in areas}
        selected = [dict(by_key[key]) for key in wanted if key in by_key]
    else:
        selected = areas[: max(count or len(areas), 0)]
    return {
        **candidate,
        "focus_areas": selected,
    }


def _track_debug_summary(track: object) -> dict:
    if not isinstance(track, dict):
        return {"track_type": type(track).__name__, "present": bool(track)}
    ladder = track.get("question_ladder") if isinstance(track.get("question_ladder"), list) else []
    dimensions = _track_dimensions(track)
    return {
        "opener": _track_opener(track)[:260],
        "map_schema_version": _clean_track_value(track.get("map_schema_version", "")),
        "primary_question_contract": _clean_track_value(track.get("primary_question_contract", "")),
        "legacy_fields_authority": _clean_track_value(track.get("legacy_fields_authority", "")),
        "ladder_postures": [
            _clean_track_value(item.get("posture", ""))
            for item in ladder
            if isinstance(item, dict)
        ],
        "ladder_questions": [
            {
                "posture": _clean_track_value(item.get("posture", "")),
                "main_question": _clean_track_value(item.get("main_question", ""))[:260],
                "information_gain": _clean_track_value(item.get("information_gain", "")),
                "voice_complexity": _clean_track_value(item.get("voice_complexity", "")),
            }
            for item in ladder[:6]
            if isinstance(item, dict)
        ],
        "dimension_count": len(dimensions),
        "dimensions": [
            {
                "id": _clean_track_value(dim.get("id", "")),
                "label": _clean_track_value(dim.get("label", "")),
                "surface": _clean_track_value(dim.get("surface", ""))[:180],
                "mechanism": _clean_track_value(dim.get("mechanism", ""))[:180],
                "boundary": _clean_track_value(dim.get("boundary", ""))[:180],
            }
            for dim in dimensions[:4]
            if isinstance(dim, dict)
        ],
        "recovery_keys": sorted([
            key for key, value in _track_recovery(track).items()
            if value
        ]),
    }


def _candidate_debug_summary(candidate: dict | None) -> dict:
    if not isinstance(candidate, dict):
        return {}
    areas: list[dict] = []
    for area in (candidate.get("focus_areas") or [])[:_MAP_TARGET_FOCUS_AREAS]:
        if not isinstance(area, dict):
            continue
        areas.append({
            "focus_key": _clean_track_value(area.get("focus_key", "")),
            "label": _clean_track_value(area.get("label", "")),
            "coverage_value": _focus_area_priority_value(area),
            "track_model": _clean_track_value(area.get("_gen_model", "")),
            "track_strategy": _clean_track_value(
                area.get("_track_generation_strategy")
                or area.get("_repair_strategy")
                or ""
            ),
            "track_latency_ms": int(area.get("_track_latency_ms", 0) or 0),
            "attempt_errors": list(area.get("_generation_attempt_errors") or [])[:3],
            "repair_provenance": list(area.get("_repair_provenance") or [])[:6],
            "track": _track_debug_summary(area.get("track")),
        })
    return {
        "focus_count": len(areas),
        "focus_areas": areas,
        "overlap_warnings": list(candidate.get("_overlap_warnings") or [])[:8],
    }


def _review_debug_summary(review: dict | None) -> dict:
    if not isinstance(review, dict):
        return {}
    return {
        "stage": review.get("stage"),
        "critic_model": review.get("critic_model"),
        "ready": bool(review.get("ready")),
        "overall_score": review.get("overall_score"),
        "top_two_score": review.get("top_two_score"),
        "opener_quality_score": review.get("opener_quality_score"),
        "dimension_depth_score": review.get("dimension_depth_score"),
        "startup_repair_deferred": bool(review.get("startup_repair_deferred")),
        "issues": list(review.get("issues") or [])[:8],
        "focus_reviews": [
            {
                "focus_key": item.get("focus_key"),
                "score": item.get("score"),
                "opener_issue": item.get("opener_issue"),
                "issues": list(item.get("issues") or [])[:4],
            }
            for item in (review.get("focus_reviews") or [])[:_MAP_LAUNCH_TRACK_COUNT]
            if isinstance(item, dict)
        ],
        "typed_issues": list(review.get("typed_issues") or [])[:10],
        "repair_targets": list(review.get("repair_targets") or [])[:10],
        "schema_repair_used": bool(review.get("schema_repair_used") or review.get("schema_rescue_used")),
        "primary_critic_model": review.get("primary_critic_model", ""),
    }


def _map_failure_diagnostics(
    *,
    session_id: str,
    focus_plan: dict | None,
    pass_one_candidate: dict | None,
    pass_one_review: dict | None,
    repair_feedback_review: dict | None,
    repaired_candidate: dict | None,
    repaired_review: dict | None,
    blocking_launch_targets: list[dict] | None,
    latency_steps: list[dict],
    cause: Exception,
) -> dict:
    return {
        "session_id": session_id,
        "failure_family": "launch_map_readiness",
        "cause_type": type(cause).__name__,
        "cause": str(cause)[:1000],
        "focus_plan": _candidate_debug_summary(focus_plan or {}),
        "pass_one_candidate": _candidate_debug_summary(pass_one_candidate or {}),
        "pass_one_review": _review_debug_summary(pass_one_review),
        "repair_feedback_review": _review_debug_summary(repair_feedback_review),
        "blocking_launch_targets": list(blocking_launch_targets or [])[:12],
        "repaired_candidate": _candidate_debug_summary(repaired_candidate or {}),
        "repaired_review": _review_debug_summary(repaired_review),
        "latency_breakdown": {"steps": latency_steps},
        "model_policy": {
            "map_generator_model": _MAP_GENERATOR_MODEL,
            "map_rescue_model": _MAP_RESCUE_MODEL,
            "map_critic_model": _MAP_CRITIC_MODEL,
            "map_track_schema_rescue_model": _MAP_TRACK_SCHEMA_RESCUE_MODEL,
            "launch_track_lite_repair_model": _LAUNCH_LITE_REPAIR_MODEL,
            "map_critic_schema_rescue_model": _MAP_CRITIC_SCHEMA_RESCUE_MODEL,
            "map_audit_model": _MAP_AUDIT_MODEL,
        },
    }


def _launch_focus_keys(candidate: dict) -> list[str]:
    return [
        _focus_key_for_area(area)
        for area in (candidate.get("focus_areas") or [])[:_MAP_LAUNCH_TRACK_COUNT]
        if isinstance(area, dict) and _focus_key_for_area(area)
    ]


def _deferred_focus_areas(full_plan: dict, launch_keys: list[str]) -> list[dict]:
    launch = set(launch_keys)
    deferred: list[dict] = []
    for area in (full_plan.get("focus_areas") or [])[:_MAP_TARGET_FOCUS_AREAS]:
        if not isinstance(area, dict):
            continue
        focus_key = _focus_key_for_area(area)
        if focus_key and focus_key not in launch:
            deferred.append({
                key: value
                for key, value in dict(area).items()
                if key not in {"track", "opener", "dimensions", "recovery", "candidate_q4_options"}
            })
    return deferred


def _focus_identity_tokens(area: dict) -> set[str]:
    if not isinstance(area, dict):
        return set()
    stop = {"and", "the", "with", "from", "that", "this", "into", "using"}
    return {
        token
        for token in re.findall(
            r"[a-z0-9]+",
            " ".join([
                str(area.get("focus_key") or ""),
                str(area.get("label") or ""),
            ]).lower(),
        )
        if len(token) > 3 and token not in stop
    }


def _surface_plan_area_is_represented(surface_area: dict, focus_plan_areas: list[dict]) -> bool:
    """Return True only when a planner focus remains a distinct routable area.

    A sub-focus mention such as "dashboard analysis" inside a taxonomy focus is
    not enough; the whole point of this preservation layer is to keep high-value
    third/fourth surfaces available for async hydration and second-anchor use.
    """
    surface_key = _clean_track_value(surface_area.get("focus_key", ""))
    surface_label_tokens = _focus_identity_tokens(surface_area)
    for plan_area in focus_plan_areas:
        plan_key = _clean_track_value(plan_area.get("focus_key", ""))
        if surface_key and plan_key and surface_key == plan_key:
            return True
        plan_label_tokens = _focus_identity_tokens(plan_area)
        if surface_label_tokens and len(surface_label_tokens & plan_label_tokens) >= min(2, len(surface_label_tokens)):
            return True
        surface_kinds = {
            _normalize_surface_kind(sub_focus.get("surface_kind"))
            for sub_focus in (surface_area.get("sub_focuses") or [])
            if isinstance(sub_focus, dict)
        }
        plan_kinds = {
            _normalize_surface_kind(sub_focus.get("surface_kind"))
            for sub_focus in _normalize_sub_focuses(
                plan_area.get("sub_focuses"),
                focus_key=str(plan_area.get("focus_key") or ""),
            )
            if isinstance(sub_focus, dict)
        }
        surface_dashboard = "dashboard_reporting" in surface_kinds or bool({"dashboard", "dashboarding"} & surface_label_tokens)
        plan_dashboard = "dashboard_reporting" in plan_kinds or bool({"dashboard", "dashboarding"} & plan_label_tokens)
        dashboard_identity_overlap = bool(surface_label_tokens & plan_label_tokens) or (
            bool({"dashboard", "dashboarding"} & surface_label_tokens)
            and bool({"dashboard", "dashboarding"} & plan_label_tokens)
        )
        if surface_dashboard and plan_dashboard and dashboard_identity_overlap:
            return True
    return False


def _surface_plan_area_to_focus_seed(area: dict) -> dict:
    label = _focus_plan_text(area.get("label") or area.get("focus_key") or "Planner surface")[:120]
    focus_key = _compact_focus_key(label, _focus_plan_text(area.get("focus_key") or label))
    source_snippets = _clean_resume_snippets(area.get("source_snippets") or [])
    role_relevance = _coerce_map_weight((_safe_float(area.get("role_relevance"), 1.0) / 5.0) * 3.0)
    profile_importance = _coerce_map_weight((_safe_float(area.get("profile_importance"), 1.0) / 5.0) * 3.0)
    evidence_strength = _coerce_map_weight((_safe_float(area.get("evidence_strength"), 1.0) / 5.0) * 3.0)
    claim_risk = _coerce_map_weight((_safe_float(area.get("claim_risk"), 1.0) / 5.0) * 3.0)
    sub_focuses: list[dict] = []
    for sub_focus in (area.get("sub_focuses") or [])[:4]:
        if not isinstance(sub_focus, dict):
            continue
        sub_label = _focus_plan_text(sub_focus.get("label") or sub_focus.get("sub_focus_key"))[:100]
        if not sub_label:
            continue
        testable = [
            _focus_plan_text(item)[:160]
            for item in (sub_focus.get("testable_surfaces") or [])[:4]
            if _focus_plan_text(item)
        ]
        sub_focuses.append({
            "label": sub_label,
            "sub_focus_key": _focus_plan_text(sub_focus.get("sub_focus_key") or _sub_focus_key_from_label(sub_label))[:80],
            "surface_kind": _normalize_surface_kind(sub_focus.get("surface_kind")) or "other",
            "role_relevance_weight": role_relevance,
            "profile_importance_weight": profile_importance,
            "evidence_strength": evidence_strength,
            "claim_risk": claim_risk,
            "coverage_value": _coerce_map_weight(
                (role_relevance * 0.45)
                + (profile_importance * 0.25)
                + (evidence_strength * 0.15)
                + (claim_risk * 0.15)
            ),
            "why_priority": _focus_plan_text(sub_focus.get("why_test") or "Planner-preserved high-signal surface")[:180],
            "source_snippets": _clean_resume_snippets(
                list(sub_focus.get("source_snippets") or []) + testable
            )[:2],
        })
    return {
        "label": label,
        "focus_key": focus_key,
        "anchor_context": " ".join(source_snippets[:2])[:500] or _focus_plan_text(area.get("why_high_signal"))[:500],
        "why_priority": _focus_plan_text(area.get("why_high_signal") or "Preserved from SurfacePlanV2 as a high-signal deferred surface.")[:220],
        "coverage_value": _coerce_map_weight(max(role_relevance, profile_importance, evidence_strength, claim_risk)),
        "role_relevance_weight": role_relevance,
        "profile_importance_weight": profile_importance,
        "evidence_strength": evidence_strength,
        "claim_risk": claim_risk,
        "resume_snippets": source_snippets[:3],
        "sub_focuses": sub_focuses,
        "_preserved_from_surface_plan_v2": True,
    }


def _merge_surface_plan_deferred_focuses(full_plan: dict, surface_plan_v2: dict | None) -> tuple[dict, list[dict]]:
    """Preserve high-value planner surfaces that Gemini compressed away.

    SurfacePlanV2 is advisory for launch ordering, but it should not disappear
    from the map completely when it found a role-relevant third/fourth surface.
    Missing high-value surfaces are appended after Gemini's plan so they hydrate
    asynchronously and never block turn 1.
    """
    if not isinstance(full_plan, dict) or not isinstance(surface_plan_v2, dict):
        return full_plan, []
    focus_areas = [dict(area) for area in (full_plan.get("focus_areas") or []) if isinstance(area, dict)]
    if len(focus_areas) >= _MAP_TARGET_FOCUS_AREAS:
        return full_plan, []
    preserved: list[dict] = []
    existing_keys = {_focus_key_for_area(area) for area in focus_areas}
    for area in surface_plan_v2.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        role_relevance = _safe_float(area.get("role_relevance"), 1.0)
        profile_importance = _safe_float(area.get("profile_importance"), 1.0)
        evidence_strength = _safe_float(area.get("evidence_strength"), 1.0)
        if role_relevance < 4.0 or profile_importance < 4.0 or evidence_strength < 3.0:
            continue
        if _surface_plan_area_is_represented(area, focus_areas):
            continue
        seed = _surface_plan_area_to_focus_seed(area)
        key = _focus_key_for_area(seed)
        if not key or key in existing_keys:
            continue
        focus_areas.append(seed)
        existing_keys.add(key)
        preserved.append({
            "focus_key": key,
            "label": seed.get("label", ""),
            "source_focus_key": area.get("focus_key", ""),
            "reason": "SurfacePlanV2 high-signal focus was omitted or collapsed by Gemini focus planning; preserved for async hydration.",
            "coverage_value": seed.get("coverage_value"),
        })
        if len(focus_areas) >= _MAP_TARGET_FOCUS_AREAS:
            break
    if not preserved:
        return full_plan, []
    merged = {
        **full_plan,
        "focus_areas": focus_areas,
    }
    merged.setdefault("_surface_plan_preserved_deferred", []).extend(preserved)
    return merged, preserved


def _attach_launch_metadata(
    interview_map: dict,
    *,
    full_plan: dict,
    launch_candidate: dict,
    launch_review: dict,
    focus_plan_audit: dict | None = None,
    quarantined: list[dict] | None = None,
) -> dict:
    launch_keys = _launch_focus_keys(launch_candidate)
    deferred = _deferred_focus_areas(full_plan, launch_keys)
    quarantined = [q for q in (quarantined or []) if isinstance(q, dict)]
    pending_keys = [
        _focus_key_for_area(area)
        for area in deferred
        if _focus_key_for_area(area)
        and _focus_key_for_area(area) not in {str(q.get("focus_key") or "") for q in quarantined}
    ]
    interview_map = dict(interview_map)
    interview_map["launch_ready"] = True
    interview_map["full_map_ready"] = not pending_keys
    interview_map["needs_async_hydration"] = bool(pending_keys)
    interview_map["launch_focus_keys"] = launch_keys
    interview_map["pending_hydration_focus_keys"] = pending_keys
    interview_map["deferred_focus_plan"] = deferred
    interview_map["map_quarantine"] = quarantined
    interview_map["launch_quality_review"] = launch_review or {}
    interview_map["generation_strategy"] = "bounded_launch_ready_async_hydration"
    if focus_plan_audit:
        interview_map["focus_plan_audit_review"] = {
            **focus_plan_audit,
            "advisory_only": True,
        }
    return interview_map


def _review_launch_failure_keys(review: dict | None, launch_keys: list[str]) -> list[str]:
    if not isinstance(review, dict):
        return launch_keys[:]
    failed: list[str] = []
    scores: dict[str, float] = {}
    for item in review.get("focus_reviews") or []:
        if not isinstance(item, dict):
            continue
        key = _clean_track_value(item.get("focus_key", ""))
        if not key:
            continue
        try:
            scores[key] = float(item.get("score", 0) or 0)
        except (TypeError, ValueError):
            scores[key] = 0.0
        if key in launch_keys and _opener_issue_blocks_launch(str(item.get("opener_issue") or ""), scores[key]):
            failed.append(key)
    for key in launch_keys:
        if scores.get(key, 0.0) and scores[key] < _MAP_MIN_READY_SCORE and key not in failed:
            failed.append(key)
    for issue in review.get("typed_issues") or []:
        if not isinstance(issue, dict):
            continue
        key = _clean_track_value(issue.get("focus_key", ""))
        path = _clean_track_value(issue.get("path", ""))
        if _is_legacy_compatibility_path(path):
            continue
        scope = _normalize_issue_scope(issue.get("issue_scope"), issue.get("path", ""))
        action = _normalize_repair_action(issue.get("action"), scope)
        if key in launch_keys and (
            str(issue.get("severity") or "").lower() == "major"
            or scope in {"plan_level", "track_level"}
            or action in {"plan_repair", "track_repair"}
        ) and key not in failed:
            failed.append(key)
    return failed


def _is_legacy_compatibility_path(path: str) -> bool:
    path_lower = _clean_track_value(path).lower()
    return path_lower.startswith("recovery.") or path_lower.startswith("candidate_q4_options")


def _launch_track_has_plan_issue(review: dict | None, launch_keys: list[str]) -> bool:
    if not isinstance(review, dict):
        return False
    for issue in list(review.get("typed_issues") or []) + list(review.get("repair_targets") or []):
        if not isinstance(issue, dict):
            continue
        scope = _normalize_issue_scope(issue.get("issue_scope"), issue.get("path", ""))
        action = _normalize_repair_action(issue.get("action"), scope)
        key = _clean_track_value(issue.get("focus_key", ""))
        severity = _clean_track_value(issue.get("severity", "")).lower()
        reason = _clean_track_value(issue.get("reason") or issue.get("issue") or issue.get("instruction") or "").lower()
        major = severity in {"major", "critical", "high"}
        substantive_track_blocker = major or any(
            marker in reason
            for marker in (
                "wrong focus",
                "wrong primary",
                "off-role",
                "off role",
                "duplicate",
                "not distinct",
                "not launch",
                "unusable",
                "unsupported",
                "unsafe",
                "missing",
                "truncated",
            )
        )
        if (scope == "plan_level" or action == "plan_repair") and (not key or key in launch_keys):
            return True
        if key in launch_keys and (scope == "track_level" or action == "track_repair") and substantive_track_blocker:
            return True
    return False


def _focus_index_lookup_from_review(review: dict | None) -> dict[int, str]:
    lookup: dict[int, str] = {}
    if not isinstance(review, dict):
        return lookup
    for index, item in enumerate(review.get("focus_reviews") or []):
        if isinstance(item, dict):
            key = _clean_track_value(item.get("focus_key", ""))
            if key:
                lookup[index] = key
    return lookup


def _issue_focus_key_from_path(review: dict | None, item: dict) -> str:
    focus_key = _clean_track_value(item.get("focus_key", ""))
    if focus_key:
        return focus_key
    path = _clean_track_value(item.get("path", ""))
    match = re.match(r"focus_areas\[(\d+)\]\.", path)
    if not match:
        return ""
    try:
        index = int(match.group(1))
    except ValueError:
        return ""
    return _focus_index_lookup_from_review(review).get(index, "")


def _blocking_launch_repair_targets(review: dict | None, launch_keys: list[str]) -> list[dict]:
    if not isinstance(review, dict):
        return []
    launch = set(launch_keys)
    blocking: list[dict] = []
    for item in list(review.get("typed_issues") or []) + list(review.get("repair_targets") or []):
        if not isinstance(item, dict):
            continue
        focus_key = _issue_focus_key_from_path(review, item)
        if focus_key not in launch:
            continue
        path = _clean_track_value(item.get("path", ""))
        scope = _normalize_issue_scope(item.get("issue_scope"), path)
        action = _normalize_repair_action(item.get("action"), scope)
        severity = _clean_track_value(item.get("severity", "")).lower()
        reason = _clean_track_value(item.get("reason") or item.get("issue") or item.get("instruction") or "").lower()
        path_lower = path.lower()
        if _is_legacy_compatibility_path(path_lower):
            continue
        is_opener_or_readability = (
            path_lower.endswith("opener")
            or path_lower == "opener"
            or scope == "readability_level"
        )
        is_launch_question_field = (
            path_lower.startswith("question_ladder")
            or path_lower.startswith("recovery.")
            or path_lower.startswith("candidate_q4_options")
            or path_lower.startswith("dimensions")
        )
        major = severity in {"major", "critical", "high"}
        substantive_track_blocker = major or any(
            marker in reason
            for marker in (
                "wrong focus",
                "wrong primary",
                "off-role",
                "off role",
                "duplicate",
                "not distinct",
                "not launch",
                "unusable",
                "unsupported",
                "unsafe",
                "missing",
                "truncated",
            )
        )
        if (
            scope == "plan_level"
            or action == "plan_repair"
            or ((scope == "track_level" or action == "track_repair") and substantive_track_blocker)
            or (major and (is_opener_or_readability or is_launch_question_field))
        ):
            blocking.append(item)
    return blocking[:6]


def _review_with_only_launch_blockers(review: dict, blockers: list[dict]) -> dict:
    blocker_keys = {
        (
            _issue_focus_key_from_path(review, item),
            _clean_track_value(item.get("path", "")),
            _clean_track_value(item.get("reason") or item.get("issue") or item.get("instruction") or ""),
        )
        for item in blockers
        if isinstance(item, dict)
    }

    def _keep(item: dict) -> bool:
        key = (
            _issue_focus_key_from_path(review, item),
            _clean_track_value(item.get("path", "")),
            _clean_track_value(item.get("reason") or item.get("issue") or item.get("instruction") or ""),
        )
        return key in blocker_keys

    return {
        **review,
        "typed_issues": [
            item for item in (review.get("typed_issues") or [])
            if isinstance(item, dict) and _keep(item)
        ],
        "repair_targets": [
            item for item in (review.get("repair_targets") or [])
            if isinstance(item, dict) and _keep(item)
        ],
        "repair_instructions": [
            "Repair only the blocking launch-readability/opener fields; defer noncritical local notes."
        ],
    }


def _replace_failed_launch_tracks(full_plan: dict, launch_keys: list[str], failed_keys: list[str]) -> tuple[dict, list[dict]]:
    """Replace failed launch focus keys with next-best focus areas without regenerating the plan."""
    areas = [dict(area) for area in (full_plan.get("focus_areas") or []) if isinstance(area, dict)]
    if len(areas) < _MAP_LAUNCH_TRACK_COUNT:
        return _candidate_focus_subset(full_plan, count=_MAP_LAUNCH_TRACK_COUNT), []
    failed = set(failed_keys or [])
    selected: list[dict] = []
    quarantined: list[dict] = []
    used: set[str] = set()
    for area in areas[:_MAP_LAUNCH_TRACK_COUNT]:
        key = _focus_key_for_area(area)
        if key in failed:
            quarantined.append({
                "focus_key": key,
                "label": area.get("label", ""),
                "reason": "launch track failed critic gate; replaced with next best focus area",
                "source": "launch_replacement",
            })
            continue
        selected.append(area)
        if key:
            used.add(key)
    for area in areas[_MAP_LAUNCH_TRACK_COUNT:]:
        if len(selected) >= _MAP_LAUNCH_TRACK_COUNT:
            break
        key = _focus_key_for_area(area)
        if key and key not in used and key not in failed:
            selected.append(area)
            used.add(key)
    return {**full_plan, "focus_areas": selected}, quarantined


def _score_map_question(area: dict, path: str, question: str, *, target_role: str = "") -> float:
    score = 8.0
    flags = _question_readability_flags(question)
    score -= min(3.0, len(flags) * 1.0)
    seed = {
        "label": area.get("label", ""),
        "focus_key": area.get("focus_key", ""),
        "anchor_context": area.get("anchor_context", ""),
        "resume_snippets": area.get("resume_snippets", []),
        "sub_focuses": area.get("sub_focuses", []),
    }
    if _question_is_generic_or_off_focus(question, seed):
        score -= 2.0
    if _boundary_leak_issue(area, path, question, target_role=target_role):
        score -= 2.0
    tokens = _content_tokens(question)
    if len(tokens) >= 7:
        score += 0.7
    if any(token in question.lower() for token in ("denominator", "guardrail", "schema", "attribution", "latency", "reconcile", "failure", "tradeoff", "baseline")):
        score += 0.6
    return max(0.0, min(10.0, round(score, 1)))


def _map_quality_scorecard(interview_map: dict, *, target_role: str = "") -> dict:
    focus_areas = [a for a in (interview_map.get("focus_areas") or []) if isinstance(a, dict)]
    questions: list[dict] = []
    boundary_penalties = 0
    readability_flags = 0
    opener_scores: list[float] = []
    dimension_scores: list[float] = []
    for area in focus_areas:
        for path, question in _iter_track_question_fields(area):
            score = _score_map_question(area, path, question, target_role=target_role)
            flags = _question_readability_flags(question)
            leak = _boundary_leak_issue(area, path, question, target_role=target_role)
            readability_flags += len(flags)
            boundary_penalties += 1 if leak else 0
            if path == "opener":
                opener_scores.append(score)
            if path.startswith("dimensions"):
                dimension_scores.append(score)
            questions.append({
                "focus_key": area.get("focus_key"),
                "label": area.get("label"),
                "path": path,
                "score": score,
                "question": question,
                "readability_flags": flags,
                "boundary_issue": leak.get("reason") if leak else "",
            })
    total_questions = max(1, len(questions))
    boundary_score = max(0.0, 10.0 - (boundary_penalties * 2.0))
    readability_score = max(0.0, 10.0 - min(8.0, readability_flags * 0.8))
    opener_score = round(sum(opener_scores) / len(opener_scores), 1) if opener_scores else 0.0
    dimension_depth_score = round(sum(dimension_scores) / len(dimension_scores), 1) if dimension_scores else 0.0
    average_question_score = sum(q["score"] for q in questions) / total_questions
    weight_warnings = _weight_calibration_warnings(interview_map)
    overall = round(
        (average_question_score * 0.35)
        + (boundary_score * 0.20)
        + (opener_score * 0.20)
        + (dimension_depth_score * 0.15)
        + (readability_score * 0.10)
        - min(1.5, len(weight_warnings) * 0.2),
        1,
    )
    sorted_questions = sorted(questions, key=lambda item: item["score"], reverse=True)
    return {
        "overall_score": max(0.0, min(10.0, overall)),
        "focus_boundary_score": round(boundary_score, 1),
        "opener_score": opener_score,
        "dimension_depth_score": dimension_depth_score,
        "readability_score": round(readability_score, 1),
        "weight_calibration_warnings": weight_warnings,
        "top_3_best_questions": sorted_questions[:3],
        "top_3_weakest_questions": sorted(questions, key=lambda item: item["score"])[:3],
        "repair_actions_taken": _repair_summary(interview_map),
    }


def _label_token_set(label: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (label or "").lower())
        if len(token) > 2 and token not in {"system", "project", "work", "technical"}
    }


_OVERLAP_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "how", "did", "you", "your", "was", "that", "this",
    "what", "when", "why", "have", "had", "can", "would", "could", "should", "from",
    "into", "than", "which", "not", "any", "are", "were", "will", "its", "but", "all",
    "one", "two", "three", "more", "also", "each", "per", "use", "used", "using",
    "then", "them", "they", "their", "been", "being", "tell", "about", "explain",
    "describe", "walk", "through", "give", "show", "what", "where", "there",
})


def _content_tokens(text: str) -> frozenset[str]:
    """Content tokens for overlap detection — stopwords removed, min length 3."""
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) >= 4 and token not in _OVERLAP_STOPWORDS
    )


def _jaccard_score(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_redundant_label(label: str, existing_labels: list[str]) -> bool:
    candidate_tokens = _label_token_set(label)
    if not candidate_tokens:
        return False
    for existing in existing_labels:
        existing_tokens = _label_token_set(existing)
        if not existing_tokens:
            continue
        overlap = candidate_tokens & existing_tokens
        if candidate_tokens <= existing_tokens or existing_tokens <= candidate_tokens:
            return True
        if overlap and len(overlap) / min(len(candidate_tokens), len(existing_tokens)) >= 0.75:
            return True
    return False


def _normalize_seed_candidates(items: list[dict], limit: int = 5) -> list[dict]:
    normalized: list[dict] = []
    labels: list[str] = []
    seen_keys: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _prettify_focus_label(str(item.get("label", "") or ""))
        anchor = str(item.get("anchor_context", "") or "").strip()
        if not label or not anchor:
            continue
        lowered = f"{label} {anchor}".lower()
        if any(token in lowered for token in ("scholarship", "award", "advisor", "university", "contact", "phone", "email")):
            continue
        if _is_redundant_label(label, labels):
            continue
        focus_key = _compact_focus_key(label, str(item.get("focus_key", "") or ""))
        if not focus_key or focus_key in seen_keys:
            continue
        normalized.append({
            "label": label,
            "focus_key": focus_key,
            "anchor_context": anchor[:220],
        })
        labels.append(label)
        seen_keys.add(focus_key)
        if len(normalized) >= limit:
            break
    return normalized



def _extract_focus_signals(seed: dict) -> dict[str, str]:
    label = str(seed.get("label", "") or "this work").strip()
    anchor = _anchor_context_for_focus(seed)
    snippets = [str(snippet).strip() for snippet in seed.get("resume_snippets", []) if str(snippet).strip()]
    source_parts = [label, anchor]
    source_parts.extend(snippets[:2])
    source_text = " ".join(part for part in source_parts if part)

    artifact = label
    if len(artifact.split()) > 8:
        artifact = " ".join(artifact.split()[:8]).strip(" -,.")

    ranked_matches: list[tuple[int, int, str]] = []
    seen_tech: set[str] = set()
    for pattern in _TECH_PHRASE_PATTERNS:
        match = re.search(pattern, source_text, flags=re.IGNORECASE)
        if not match:
            continue
        phrase = re.sub(r"\s+", " ", match.group(0).strip())
        normalized = phrase.lower()
        if normalized in seen_tech:
            continue
        seen_tech.add(normalized)
        ranked_matches.append((match.start(), len(phrase), phrase))

    metric_match = re.search(
        r"(\b\d+%[+~]?\b|\b<\s*\d+\s*ms\b|\b\d+\s*KB\b|\b\d+(?:\.\d+)?\s*[x×]\b|\b\d+(?:,\d{3})+\+?\b)",
        source_text,
        flags=re.IGNORECASE,
    )
    metric = re.sub(r"\s+", " ", metric_match.group(0)).strip() if metric_match else ""

    domain = ""
    lowered = source_text.lower()
    for needle, phrase in (
        ("video-generation", "the video-generation workflow"),
        ("aigc", "the video-generation workflow"),
        ("audio", "the audio pipeline"),
        ("benchmark", "the benchmark design"),
        ("sql", "the SQL and schema design"),
        ("classifier", "the classifier pipeline"),
        ("latency", "the latency profile"),
        ("retrieval", "the retrieval setup"),
        ("ui-to-latent", "the UI control-mapping layer"),
    ):
        if needle in lowered:
            domain = phrase
            break

    ranked_matches.sort(key=lambda item: (item[0], item[1]))
    tech_matches = [phrase for _, _, phrase in ranked_matches]
    family_probe = _artifact_family({
        "artifact": artifact or label or "this work",
        "primary_tech": tech_matches[0] if tech_matches else "",
        "secondary_tech": tech_matches[1] if len(tech_matches) > 1 else "",
        "metric": metric,
        "domain": domain or artifact or label or "the system",
    })
    artifact_norm = re.sub(r"[^a-z0-9]+", " ", artifact.lower()).strip()
    priorities: list[str] = []

    ordered_matches: list[tuple[tuple[int, int, int, int], str]] = []
    for position, _, phrase in ranked_matches:
        normalized = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
        priority_index = next(
            (index for index, needle in enumerate(priorities) if needle in phrase.lower()),
            len(priorities),
        )
        is_artifact_echo = 1 if normalized == artifact_norm else 0
        ordered_matches.append(((is_artifact_echo, priority_index, position, len(phrase)), phrase))

    ordered_matches.sort(key=lambda item: item[0])
    tech_matches = [phrase for _, phrase in ordered_matches[:3]]

    primary_tech = tech_matches[0] if tech_matches else domain or artifact
    secondary_tech = tech_matches[1] if len(tech_matches) > 1 else primary_tech
    return {
        "artifact": artifact or label or "this work",
        "primary_tech": primary_tech,
        "secondary_tech": secondary_tech,
        "metric": metric,
        "domain": domain or artifact or label or "the system",
    }


def _artifact_family(signals: dict[str, str]) -> str:
    artifact = signals.get("artifact", "").lower()
    domain = signals.get("domain", "").lower()
    primary_tech = signals.get("primary_tech", "").lower()
    combined = " ".join([artifact, domain, primary_tech])
    if "benchmark" in combined or "dataset" in combined:
        return "benchmark"
    if "interface" in combined or "ui" in combined:
        return "interface"
    if any(token in combined for token in ("classifier", "classification", "tinyml")):
        return "classifier"
    if "schema" in combined or "sql" in combined:
        return "data_modeling"
    if "pipeline" in combined:
        return "pipeline"
    return "system"


def _fallback_track(seed: dict, next_focus_label: str) -> dict:
    raise RuntimeError("Deterministic sprint-track fallback is disabled; LLM track generation must succeed.")


def _fallback_dimension_track(seed: dict, next_focus_label: str, role_type: str = "") -> dict:
    raise RuntimeError("Deterministic dimension-track fallback is disabled; LLM track generation must succeed.")


_QUESTION_LADDER_POSTURES = ("frame", "clarify", "explore", "pressure", "synthesize", "recover")
_QUESTION_LADDER_QUESTION_FIELDS = {"main_question", "follow_up_if_shallow", "follow_up_if_strong"}


def _normalize_question_ladder(raw_ladder: object, *, opener: str, dims: list[dict], recovery: dict) -> list[dict]:
    items: list[dict] = []
    if isinstance(raw_ladder, list):
        for raw_item in raw_ladder:
            if not isinstance(raw_item, dict):
                continue
            posture = _clean_track_value(raw_item.get("posture", "")).lower()
            if posture not in _QUESTION_LADDER_POSTURES:
                continue
            main_question = _clean_track_value(raw_item.get("main_question", ""))
            if not main_question:
                continue
            expected_raw = raw_item.get("expected_space") or []
            expected_space = [
                _clean_track_value(item)
                for item in expected_raw
                if isinstance(item, str) and _clean_track_value(item)
            ][:4]
            info_gain = _clean_track_value(raw_item.get("information_gain", "medium")).lower()
            if info_gain not in {"high", "medium", "low"}:
                info_gain = "medium"
            voice_complexity = _clean_track_value(raw_item.get("voice_complexity", "medium")).lower()
            if voice_complexity not in {"low", "medium", "high"}:
                voice_complexity = "medium"
            items.append({
                "posture": posture,
                "main_question": main_question,
                "signal_goal": _clean_track_value(raw_item.get("signal_goal", "")),
                "expected_space": expected_space,
                "follow_up_if_shallow": _clean_track_value(raw_item.get("follow_up_if_shallow", "")),
                "follow_up_if_strong": _clean_track_value(raw_item.get("follow_up_if_strong", "")),
                "information_gain": info_gain,
                "voice_complexity": voice_complexity,
            })

    by_posture: dict[str, dict] = {}
    for item in items:
        by_posture.setdefault(item["posture"], item)

    # Compatibility synthesis: if an older model returns legacy fields only,
    # derive a ladder from LLM-authored questions rather than inventing new probes.
    dim0 = dims[0] if dims else {}
    dim1 = dims[1] if len(dims) > 1 else dim0
    dim2 = dims[2] if len(dims) > 2 else dim1
    fallbacks = {
        "frame": opener,
        "clarify": dim0.get("surface", ""),
        "explore": dim1.get("mechanism", ""),
        "pressure": dim0.get("boundary", "") or dim2.get("boundary", ""),
        "synthesize": dim2.get("mechanism", "") or dim1.get("boundary", ""),
        "recover": recovery.get("short_answer", "") or recovery.get("honest_gap", ""),
    }
    goals = {
        "frame": "Start the claim in a guided, non-prosecutor way.",
        "clarify": "Clarify the definition, denominator, scope, or ownership boundary.",
        "explore": "Understand how the candidate reasoned through the work.",
        "pressure": "Pressure-test one important assumption after context exists.",
        "synthesize": "Check what is certain, uncertain, and worth carrying forward.",
        "recover": "Recover signal from a shallow or vague answer.",
    }
    ladder: list[dict] = []
    for posture in _QUESTION_LADDER_POSTURES:
        item = dict(by_posture.get(posture) or {})
        if not item:
            question = _clean_track_value(fallbacks.get(posture, ""))
            if not question:
                continue
            item = {
                "posture": posture,
                "main_question": question,
                "signal_goal": goals[posture],
                "expected_space": [],
                "follow_up_if_shallow": "",
                "follow_up_if_strong": "",
                "information_gain": "high" if posture in {"clarify", "pressure", "explore"} else "medium",
                "voice_complexity": "medium",
            }
        ladder.append(item)
    return ladder


def _ladder_item_text(ladder: list[dict], posture: str, *fields: str) -> str:
    for item in ladder:
        if not isinstance(item, dict) or item.get("posture") != posture:
            continue
        for field in fields:
            value = _clean_track_value(item.get(field, ""))
            if value:
                return value
    return ""


def _legacy_compat_from_v2_track(track: dict) -> dict:
    """Build legacy read-model fields from the V2 ladder/dimension contract.

    The returned object is deliberately a compatibility view. Runtime question
    authority belongs to question_ladder; legacy aliases exist only while older
    consumers are migrated.
    """
    ladder = track.get("question_ladder") if isinstance(track.get("question_ladder"), list) else []
    dimensions = [
        dim for dim in (track.get("dimensions") or [])
        if isinstance(dim, dict)
    ]
    raw_recovery = track.get("recovery") if isinstance(track.get("recovery"), dict) else {}
    opener = (
        _ladder_item_text(ladder, "frame", "main_question")
        or _ladder_item_text(ladder, "clarify", "main_question")
        or _clean_track_value(track.get("opener", ""))
    )
    recovery_defaults = {
        "short_answer": _ladder_item_text(ladder, "recover", "follow_up_if_shallow", "main_question"),
        "honest_gap": _ladder_item_text(ladder, "recover", "follow_up_if_strong", "main_question"),
        "claim_conflict": _ladder_item_text(ladder, "pressure", "main_question"),
        "metric_risk": _ladder_item_text(ladder, "clarify", "main_question"),
        "overclaim_risk": _ladder_item_text(ladder, "pressure", "follow_up_if_shallow", "main_question"),
        "bridge": _ladder_item_text(ladder, "synthesize", "main_question"),
    }
    recovery = {
        field: _clean_track_value(raw_recovery.get(field, "")) or value
        for field, value in recovery_defaults.items()
        if _clean_track_value(raw_recovery.get(field, "")) or value
    }
    return {
        "schema_version": "legacy_compat_from_v2_ladder",
        "authority": "compatibility_only",
        "derived_from": "question_ladder",
        "opener": opener,
        "dimensions": dimensions[:6],
        "recovery": recovery,
        "candidate_q4_options": [
            _clean_track_value(item)
            for item in (track.get("candidate_q4_options") or [])
            if isinstance(item, str) and _clean_track_value(item)
        ],
    }


def _legacy_compat(area: dict) -> dict:
    compat = area.get("legacy_compat") if isinstance(area.get("legacy_compat"), dict) else {}
    if compat:
        return compat
    return {
        "opener": _clean_track_value(area.get("opener", "")),
        "dimensions": area.get("dimensions") if isinstance(area.get("dimensions"), list) else [],
        "recovery": area.get("recovery") if isinstance(area.get("recovery"), dict) else {},
        "candidate_q4_options": area.get("candidate_q4_options") if isinstance(area.get("candidate_q4_options"), list) else [],
        "authority": "legacy_fallback",
    }


def _track_opener(area: dict) -> str:
    ladder = area.get("question_ladder") if isinstance(area.get("question_ladder"), list) else []
    return (
        _ladder_item_text(ladder, "frame", "main_question")
        or _ladder_item_text(ladder, "clarify", "main_question")
        or _clean_track_value(_legacy_compat(area).get("opener", ""))
        or _clean_track_value(area.get("opener", ""))
    )


def _track_dimensions(area: dict) -> list[dict]:
    dims = area.get("assessment_dimensions")
    if not isinstance(dims, list):
        dims = _legacy_compat(area).get("dimensions")
    if not isinstance(dims, list):
        dims = area.get("dimensions")
    return [dim for dim in (dims or []) if isinstance(dim, dict)]


def _track_recovery(area: dict) -> dict:
    recovery = _legacy_compat(area).get("recovery")
    if not isinstance(recovery, dict):
        recovery = area.get("recovery")
    return recovery if isinstance(recovery, dict) else {}


def _track_candidate_q4_options(area: dict) -> list[str]:
    options = _legacy_compat(area).get("candidate_q4_options")
    if not isinstance(options, list):
        options = area.get("candidate_q4_options")
    return [_clean_track_value(item) for item in (options or []) if isinstance(item, str) and _clean_track_value(item)]


def _synthesize_legacy_dimensions_from_ladder(
    *,
    ladder: list[dict],
    seed: dict,
    existing_dims: list[dict],
) -> list[dict]:
    """
    Compatibility bridge for modern ladder-first tracks.

    If a model gives strong LLM-authored ladder questions but underfills the
    legacy dimensions array, keep the ladder and derive the minimum legacy
    surfaces from those same questions. This avoids expensive Sonnet rescue for
    shape-only failures without inventing deterministic interview content.
    """
    dims = [
        dim for dim in (existing_dims or [])
        if _dimension_minimally_usable(dim)
    ]
    if len(dims) >= 2:
        return dims

    anchor = _anchor_context_for_focus(seed) or str(seed.get("label") or "")
    clarify_q = _ladder_item_text(ladder, "clarify", "main_question")
    explore_q = _ladder_item_text(ladder, "explore", "main_question")
    pressure_q = _ladder_item_text(ladder, "pressure", "main_question")
    synth_q = _ladder_item_text(ladder, "synthesize", "main_question")
    recover_q = _ladder_item_text(ladder, "recover", "main_question", "follow_up_if_shallow")
    frame_q = _ladder_item_text(ladder, "frame", "main_question")
    pressure_followup = _ladder_item_text(ladder, "pressure", "follow_up_if_shallow", "follow_up_if_strong")

    candidates = [
        {
            "id": "metric_definition_or_scope",
            "label": "Metric definition, scope, and ownership",
            "resume_anchor": anchor,
            "surface": clarify_q or frame_q,
            "mechanism": explore_q or synth_q,
            "boundary": pressure_q or pressure_followup,
            "signal_weight": 3.0,
        },
        {
            "id": "evidence_boundary_and_decision_risk",
            "label": "Evidence boundary, guardrails, and decision risk",
            "resume_anchor": anchor,
            "surface": synth_q or explore_q,
            "mechanism": recover_q or pressure_followup or pressure_q,
            "boundary": pressure_followup or pressure_q or recover_q,
            "signal_weight": 2.5,
        },
    ]

    seen_ids = {str(dim.get("id") or "") for dim in dims if isinstance(dim, dict)}
    for candidate in candidates:
        if len(dims) >= 2:
            break
        if candidate["id"] in seen_ids:
            continue
        if not (candidate.get("surface") and candidate.get("mechanism") and candidate.get("boundary")):
            continue
        dims.append(candidate)
        seen_ids.add(candidate["id"])
    return dims


def _parse_dimension_output(raw: dict | str, seed: dict) -> dict:
    """Parse new opener+dimensions+recovery schema. Invalid output fails closed."""
    if isinstance(raw, str):
        parsed = _load_json_lenient(raw)
        if parsed is None:
            raise RuntimeError(f"Track output was not JSON for {seed.get('focus_key')}.")
        raw = parsed

    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        raw = raw[0]

    if isinstance(raw, dict) and "track" in raw and "opener" not in raw and isinstance(raw.get("track"), dict):
        raw = raw["track"]

    if not isinstance(raw, dict):
        raise RuntimeError(f"Track output must be an object for {seed.get('focus_key')}.")
    raw = _pre_normalize_track_schema(raw)

    # Pydantic validation: coerce types and catch structural errors early
    validated, schema_errors = _validate_schema(raw, _TrackSchema)
    if schema_errors:
        raise RuntimeError(f"Track schema issues for '{seed.get('label', '?')}': {schema_errors[:3]}")

    opener = _clean_track_value(validated.get("opener", ""))
    dims_raw = validated.get("dimensions") or []
    recovery_raw = validated.get("recovery") or {}
    q4_options_raw = validated.get("candidate_q4_options") or []
    ladder_raw = validated.get("question_ladder") or raw.get("question_ladder") or []

    dims: list[dict] = []
    for d in dims_raw:
        if not isinstance(d, dict):
            continue
        dim_id = _clean_track_value(d.get("id", ""))
        dim_label = _clean_track_value(d.get("label", ""))
        resume_anchor = _clean_track_value(d.get("resume_anchor", ""))
        surface = _clean_track_value(d.get("surface", ""))
        mechanism = _clean_track_value(d.get("mechanism", ""))
        boundary = _clean_track_value(d.get("boundary", ""))
        if not (dim_id and surface and mechanism and boundary):
            continue
        signal_weight = _coerce_signal_weight(d.get("signal_weight"), 1.5)
        dim = {
            "id": dim_id,
            "label": dim_label or dim_id,
            "resume_anchor": resume_anchor,
            "surface": surface,
            "mechanism": mechanism,
            "boundary": boundary,
            "signal_weight": signal_weight,
        }
        dim.setdefault("signal_weight", 1.5)
        dims.append(dim)

    # Preserve candidate_q4_options from LLM output
    candidate_q4_options = [
        _clean_track_value(q) for q in q4_options_raw
        if isinstance(q, str) and _clean_track_value(q)
    ]

    recovery_fields = ("short_answer", "honest_gap", "claim_conflict", "metric_risk", "overclaim_risk", "bridge")
    recovery: dict[str, str] = {}
    for field in recovery_fields:
        val = _clean_track_value(recovery_raw.get(field, "") if isinstance(recovery_raw, dict) else "")
        if val:
            recovery[field] = val

    preliminary_ladder = _normalize_question_ladder(
        ladder_raw,
        opener=opener,
        dims=dims,
        recovery=recovery,
    )
    opener_replacement = (
        _ladder_item_text(preliminary_ladder, "frame", "main_question")
        or _ladder_item_text(preliminary_ladder, "clarify", "main_question")
    )
    opener_safety_flags = _question_repair_safety_flags(opener) if opener else ["empty_question"]
    if (
        not opener
        or "appears_truncated" in opener_safety_flags
        or "missing_question_mark" in opener_safety_flags
    ):
        opener = (
            opener_replacement
            or opener
        )
    dims = _synthesize_legacy_dimensions_from_ladder(
        ladder=preliminary_ladder,
        seed=seed,
        existing_dims=dims,
    )

    if not opener or len(dims) < 2:
        raise RuntimeError(
            f"Track for {seed.get('focus_key')} missing opener or minimum dimensions: opener={bool(opener)} dims={len(dims)}"
        )

    question_ladder = _normalize_question_ladder(
        preliminary_ladder or ladder_raw,
        opener=opener,
        dims=dims,
        recovery=recovery,
    )
    ladder_postures = {item.get("posture") for item in question_ladder}
    high_info_count = sum(1 for item in question_ladder if item.get("information_gain") == "high")
    full_ladder_ready = set(_QUESTION_LADDER_POSTURES).issubset(ladder_postures) and high_info_count >= 3
    if len(ladder_postures) < 4:
        raise RuntimeError(f"Track for {seed.get('focus_key')} missing usable question_ladder.")
    if len(dims) < 3 and not full_ladder_ready:
        raise RuntimeError(
            f"Track for {seed.get('focus_key')} has only {len(dims)} dimensions and no complete high-info ladder."
        )
    unsupported_flags: list[str] = []
    for index, item in enumerate(question_ladder):
        for field in ("main_question", "follow_up_if_shallow", "follow_up_if_strong"):
            text = _clean_track_value(item.get(field, ""))
            if not text:
                continue
            for flag in _unsupported_hidden_assumption_flags(text, seed):
                unsupported_flags.append(f"question_ladder[{index}].{field}.{flag}")
    for index, dim in enumerate(dims):
        for field in ("surface", "mechanism", "boundary"):
            text = _clean_track_value(dim.get(field, ""))
            for flag in _unsupported_hidden_assumption_flags(text, seed):
                unsupported_flags.append(f"dimensions[{index}].{field}.{flag}")
    if unsupported_flags:
        raise RuntimeError(
            f"Track for {seed.get('focus_key')} contains unsupported hidden implementation assumptions: "
            + ", ".join(unsupported_flags[:5])
        )

    result = {
        "map_schema_version": "v2_ladder",
        "primary_question_contract": "question_ladder",
        "question_ladder": question_ladder,
        "opener": opener,
        "dimensions": dims[:6],
        "recovery": recovery,
        "candidate_q4_options": candidate_q4_options,
    }
    legacy_compat = _legacy_compat_from_v2_track(result)
    result["legacy_compat"] = legacy_compat
    result["opener"] = legacy_compat["opener"]
    result["dimensions"] = legacy_compat["dimensions"]
    result["recovery"] = legacy_compat["recovery"]
    result["candidate_q4_options"] = legacy_compat["candidate_q4_options"]
    result["assessment_dimensions"] = legacy_compat["dimensions"]
    result.setdefault("candidate_q4_options", [])
    return result


def _clean_track_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _safe_float(value: object, default: float = 0.0, *, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _coerce_signal_weight(value: object, default: float = 1.5) -> float:
    if isinstance(value, (int, float)):
        return _safe_float(value, default, min_value=1.0, max_value=3.0)
    text = _clean_track_value(value).lower()
    if not text:
        return default
    label_weights = {
        "critical": 3.0,
        "highest": 3.0,
        "high": 3.0,
        "medium": 2.0,
        "moderate": 2.0,
        "low": 1.5,
        "minor": 1.0,
    }
    if text in label_weights:
        return label_weights[text]
    match = re.search(r"\d+(?:\.\d+)?", text)
    if match:
        return _safe_float(match.group(0), default, min_value=1.0, max_value=3.0)
    return default


def _pre_normalize_track_schema(raw: dict) -> dict:
    """Normalize harmless LLM shape drift before strict schema validation."""
    normalized = dict(raw)

    def _coerce_text_field(value: object) -> str:
        if isinstance(value, dict):
            for key in ("question", "main_question", "text", "value", "label", "name", "follow_up", "prompt", "ask"):
                coerced = _clean_track_value(value.get(key))
                if coerced:
                    return coerced
            return ""
        if isinstance(value, list):
            parts = [_coerce_text_field(item) for item in value]
            return " ".join(part for part in parts if part)
        return _clean_track_value(value)

    normalized["opener"] = _coerce_text_field(raw.get("opener"))

    dims: list[dict] = []
    for item in raw.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        dim = dict(item)
        for field in ("id", "label", "resume_anchor", "surface", "mechanism", "boundary"):
            dim[field] = _coerce_text_field(dim.get(field))
        dim["signal_weight"] = _coerce_signal_weight(dim.get("signal_weight"), 1.5)
        dims.append(dim)
    normalized["dimensions"] = dims

    ladder: list[dict] = []
    for item in raw.get("question_ladder") or []:
        if not isinstance(item, dict):
            continue
        ladder_item = dict(item)
        expected_space = ladder_item.get("expected_space") or []
        if isinstance(expected_space, str):
            expected_space = [
                part.strip()
                for part in re.split(r"[,;/]|\band\b", expected_space)
                if part.strip()
            ]
        elif isinstance(expected_space, list):
            expected_space = [
                _coerce_text_field(part)
                for part in expected_space
                if _coerce_text_field(part)
            ]
        ladder_item["expected_space"] = expected_space if isinstance(expected_space, list) else []
        for field in (
            "posture",
            "main_question",
            "signal_goal",
            "follow_up_if_shallow",
            "follow_up_if_strong",
            "information_gain",
            "voice_complexity",
        ):
            ladder_item[field] = _coerce_text_field(ladder_item.get(field))
        ladder.append(ladder_item)
    normalized["question_ladder"] = ladder

    recovery_raw = raw.get("recovery")
    if isinstance(recovery_raw, dict):
        recovery: dict[str, str] = {}
        for key, value in recovery_raw.items():
            if isinstance(value, dict):
                value = (
                    value.get("question")
                    or value.get("main_question")
                    or value.get("text")
                    or value.get("value")
                    or value.get("follow_up")
                    or ""
                )
            recovery[str(key)] = _clean_track_value(value)
        normalized["recovery"] = recovery
    else:
        normalized["recovery"] = {}

    q4_raw = raw.get("candidate_q4_options")
    if isinstance(q4_raw, list):
        normalized["candidate_q4_options"] = [
            _clean_track_value(
                item.get("question") or item.get("main_question") or item.get("text") or item.get("value")
            )
            if isinstance(item, dict)
            else _clean_track_value(item)
            for item in q4_raw
        ]
    else:
        normalized["candidate_q4_options"] = []
    return normalized


def _dimension_minimally_usable(dim: dict) -> bool:
    if not isinstance(dim, dict):
        return False
    try:
        signal_weight = float(dim.get("signal_weight") or 0)
    except (TypeError, ValueError):
        signal_weight = 0.0
    if signal_weight < 1.0:
        return False
    for field in ("surface", "mechanism", "boundary"):
        text = _clean_track_value(dim.get(field, ""))
        if len(re.findall(r"[A-Za-z0-9%+.-]+", text)) < 5:
            return False
        if "?" not in text:
            return False
    return True


def _coerce_map_weight(value: object, default: float = 1.5) -> float:
    return _safe_float(value, default, min_value=1.0, max_value=3.0)


_SURFACE_KIND_ALIASES: dict[str, str] = {
    "conversion": "conversion_experiment",
    "conversion_experiment": "conversion_experiment",
    "pricing": "conversion_experiment",
    "trial": "conversion_experiment",
    "funnel": "conversion_experiment",
    "retention": "retention_experiment",
    "retention_experiment": "retention_experiment",
    "reactivation": "retention_experiment",
    "activation": "retention_experiment",
    "event_taxonomy": "event_taxonomy",
    "taxonomy": "event_taxonomy",
    "instrumentation": "event_taxonomy",
    "tracking": "event_taxonomy",
    "dashboard": "dashboard_reporting",
    "dashboard_reporting": "dashboard_reporting",
    "reporting": "dashboard_reporting",
    "acquisition": "acquisition_marketing",
    "marketing": "acquisition_marketing",
    "acquisition_marketing": "acquisition_marketing",
    "data_pipeline": "data_pipeline",
    "pipeline": "data_pipeline",
    "backend": "backend_system",
    "backend_system": "backend_system",
    "ml": "ml_model",
    "ml_model": "ml_model",
    "machine_learning": "ml_model",
    "ai_agent": "ai_agent",
    "agent": "ai_agent",
    "computer_vision": "computer_vision",
    "cv": "computer_vision",
    "design": "design_ux",
    "ux": "design_ux",
    "design_ux": "design_ux",
    "research": "research",
    "operations": "operations",
    "ops": "operations",
    "leadership": "leadership",
    "other": "other",
}


def _normalize_surface_kind(value: object) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    if not raw:
        return ""
    return _SURFACE_KIND_ALIASES.get(raw, raw if raw in set(_SURFACE_KIND_ALIASES.values()) else "other")


def _sub_focus_key_from_label(label: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (label or "").lower())
        if len(token) > 2
    ]
    return "_".join(tokens[:8])


def _normalize_sub_focus_entry(item: object, *, focus_key: str = "") -> dict | None:
    if isinstance(item, dict):
        label = _focus_plan_text(
            item.get("label")
            or item.get("name")
            or item.get("surface")
            or item.get("sub_focus")
            or item.get("sub_focus_label")
            or item.get("key")
            or item.get("sub_focus_key")
        )[:100]
        key = _focus_plan_text(item.get("sub_focus_key") or item.get("key") or item.get("id"))
        surface_kind = _normalize_surface_kind(
            item.get("surface_kind")
            or item.get("surface_type")
            or item.get("kind")
            or item.get("taxonomy")
        )
        role_relevance = _coerce_map_weight(
            item.get("role_relevance_weight")
            or item.get("role_relevance")
            or item.get("role_weight")
            or item.get("weight")
        )
        profile_importance = _coerce_map_weight(
            item.get("profile_importance_weight")
            or item.get("profile_importance")
            or item.get("profile_weight"),
            default=role_relevance,
        )
        evidence_strength = _coerce_map_weight(item.get("evidence_strength"))
        claim_risk = _coerce_map_weight(item.get("claim_risk") or item.get("clean_risk"))
        explicit_value = item.get("coverage_value") or item.get("value") or item.get("priority_weight")
        coverage_value = (
            _coerce_map_weight(explicit_value)
            if explicit_value is not None
            else _coerce_map_weight(
                (role_relevance * 0.45)
                + (profile_importance * 0.25)
                + (evidence_strength * 0.15)
                + (claim_risk * 0.15)
            )
        )
        source_snippets = _clean_resume_snippets(
            item.get("source_snippets")
            or item.get("resume_snippets")
            or item.get("evidence")
            or item.get("supporting_lines")
        )
        why_priority = _focus_plan_text(item.get("why_priority") or item.get("rationale") or "")[:180]
    else:
        label = _clean_track_value(item)[:100]
        key = ""
        surface_kind = ""
        role_relevance = profile_importance = evidence_strength = claim_risk = coverage_value = 1.5
        source_snippets = []
        why_priority = ""

    if not label:
        return None
    key = _clean_track_value(key) or _sub_focus_key_from_label(label) or focus_key
    if not key:
        return None
    return {
        "label": label,
        "sub_focus_key": key[:80],
        "surface_kind": surface_kind,
        "role_relevance_weight": role_relevance,
        "profile_importance_weight": profile_importance,
        "evidence_strength": evidence_strength,
        "claim_risk": claim_risk,
        "coverage_value": coverage_value,
        "why_priority": why_priority,
        "source_snippets": source_snippets[:2],
    }


def _normalize_sub_focuses(raw: object, *, focus_key: str = "") -> list[dict]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        sub_focus = _normalize_sub_focus_entry(item, focus_key=focus_key)
        if not sub_focus:
            continue
        key = str(sub_focus.get("sub_focus_key") or "")
        if key in seen:
            continue
        seen.add(key)
        normalized.append(sub_focus)
    return normalized[:6]


def _sub_focus_texts(raw: object, *, focus_key: str = "") -> list[str]:
    texts: list[str] = []
    for sub_focus in _normalize_sub_focuses(raw, focus_key=focus_key):
        parts = [
            str(sub_focus.get("label") or ""),
            str(sub_focus.get("why_priority") or ""),
            " ".join(str(s) for s in (sub_focus.get("source_snippets") or []) if s),
        ]
        text = " ".join(part for part in parts if part).strip()
        if text:
            texts.append(text)
    return texts


def _focus_area_priority_value(area: dict) -> float:
    if not isinstance(area, dict):
        return 1.5
    sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or ""))
    if sub_focuses:
        return max(float(sf.get("coverage_value") or 1.5) for sf in sub_focuses)
    return _coerce_map_weight(
        area.get("coverage_value")
        or area.get("role_relevance_weight")
        or area.get("profile_importance_weight")
        or area.get("priority_weight")
    )


def _primary_surface_kind(area: dict) -> str:
    if not isinstance(area, dict):
        return ""
    explicit = _normalize_surface_kind(area.get("surface_kind"))
    if explicit and explicit != "other":
        return explicit
    sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or ""))
    ranked = sorted(
        (
            (
                float(sf.get("coverage_value") or 1.5),
                _normalize_surface_kind(sf.get("surface_kind")),
            )
            for sf in sub_focuses
        ),
        reverse=True,
    )
    for _, kind in ranked:
        if kind and kind != "other":
            return kind
    return explicit


def _weight_calibration_warnings(candidate: dict) -> list[dict]:
    """Flag suspicious sub-focus weight distributions without forcing target values."""
    warnings: list[dict] = []
    surfaces: list[dict] = []
    for area in candidate.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        focus_key = _clean_track_value(area.get("focus_key", ""))
        label = _clean_track_value(area.get("label", ""))
        sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=focus_key)
        if not sub_focuses:
            continue
        for index, sf in enumerate(sub_focuses):
            item = {
                "focus_key": focus_key,
                "label": label,
                "path": f"sub_focuses[{index}].coverage_value",
                "sub_focus_label": sf.get("label"),
                "role_relevance_weight": float(sf.get("role_relevance_weight") or 1.5),
                "profile_importance_weight": float(sf.get("profile_importance_weight") or 1.5),
                "evidence_strength": float(sf.get("evidence_strength") or 1.5),
                "claim_risk": float(sf.get("claim_risk") or 1.5),
                "coverage_value": float(sf.get("coverage_value") or 1.5),
            }
            surfaces.append(item)
            role = item["role_relevance_weight"]
            risk = item["claim_risk"]
            coverage = item["coverage_value"]
            if role >= 2.6 and coverage <= 1.8:
                warnings.append({
                    **item,
                    "severity": "minor",
                    "warning": "High role relevance has unexpectedly low coverage value.",
                })
            if risk >= 2.6 and role <= 1.5 and coverage >= 2.3:
                warnings.append({
                    **item,
                    "severity": "major",
                    "warning": "High-risk but low-role-relevance surface is overprioritized.",
                })
            if role <= 1.7 and coverage >= 2.6:
                warnings.append({
                    **item,
                    "severity": "major",
                    "warning": "Off-role surface has high coverage value.",
                })

    if len(surfaces) >= 3:
        values = [round(float(item["coverage_value"]), 1) for item in surfaces]
        if len(set(values)) == 1 or (max(values) - min(values) <= 0.2 and sum(values) / len(values) >= 2.7):
            warnings.append({
                "focus_key": "",
                "path": "sub_focuses[*].coverage_value",
                "severity": "minor",
                "warning": "Coverage values are suspiciously clustered; ranking may not reflect role relevance/profile importance.",
                "coverage_values": values,
            })
    return warnings[:12]


def _question_is_generic_or_off_focus(question: str, seed: dict) -> bool:
    cleaned = _clean_track_value(question).lower()
    if not cleaned:
        return True
    if any(phrase in cleaned for phrase in _GENERIC_PHRASES):
        anchor = _anchor_context_for_focus(seed).lower()
        if not anchor or not any(token in cleaned for token in re.findall(r"[a-z0-9]+", anchor) if len(token) > 3):
            return True

    anchor_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", f"{seed.get('label', '')} {_anchor_context_for_focus(seed)}".lower())
        if len(token) > 3
    }
    if anchor_tokens and not (anchor_tokens & set(re.findall(r"[a-z0-9]+", cleaned))):
        return True
    return False


_HIDDEN_TECH_ASSUMPTION_TERMS = (
    "engine parameter",
    "engine parameters",
    "internal parameter",
    "internal parameters",
    "model parameter",
    "model parameters",
    "latent space",
    "latent state",
    "latent vector",
    "latent vectors",
    "embedding distance",
    "embedding distances",
    "identity embedding",
    "identity embeddings",
    "embedding space",
    "clip score",
    "clip scores",
    "facial crop",
    "facial crops",
    "cross-attention",
    "cross attention",
    "diffusion noise",
    "noise schedule",
    "sampler",
    "denoising",
    "optimizer",
    "backprop",
    "training loop",
    "feature extractor",
    "model weights",
    "gradient",
)

_HIDDEN_TERM_SUPPORT_ALIASES = {
    "feature extractor": (
        "feature extraction",
        "audio features",
        "mediapipe audio features",
        "media pipe audio features",
    ),
    "model weights": (
        "tensorflow lite",
        "tflite",
        "int8",
        "quantization",
        "quantizing",
        "classifier",
        "model invocation",
        "model optimization",
        "fine-tune",
        "fine tune",
        "training",
        "weights",
    ),
    "optimizer": ("training", "fine-tune", "fine tune", "optimizer"),
    "backprop": ("training", "fine-tune", "fine tune", "backprop"),
    "training loop": ("training", "fine-tune", "fine tune", "training loop"),
}


def _seed_evidence_text(seed: dict) -> str:
    snippets = []
    if isinstance(seed, dict):
        snippets.extend(str(item) for item in seed.get("resume_snippets") or [] if item)
        snippets.extend(_sub_focus_source_snippets(seed))
        snippets.append(str(seed.get("anchor_context") or ""))
        snippets.append(str(seed.get("label") or ""))
        snippets.append(str(seed.get("why_priority") or ""))
        for sub_focus in _normalize_sub_focuses(seed.get("sub_focuses"), focus_key=str(seed.get("focus_key") or "")):
            snippets.append(str(sub_focus.get("label") or ""))
            snippets.append(str(sub_focus.get("why_priority") or ""))
    return " ".join(snippets).lower()


def _evidence_supports_hidden_term(term: str, evidence: str) -> bool:
    if term in evidence:
        return True
    for alias in _HIDDEN_TERM_SUPPORT_ALIASES.get(term, ()):
        if alias in evidence:
            return True
    return False


def _unsupported_hidden_assumption_flags(question: str, seed: dict) -> list[str]:
    lowered = _clean_track_value(question).lower()
    evidence = _seed_evidence_text(seed)
    flags: list[str] = []
    for term in _HIDDEN_TECH_ASSUMPTION_TERMS:
        if term in lowered and not _evidence_supports_hidden_term(term, evidence):
            flags.append(f"unsupported_internal_assumption:{term.replace(' ', '_')}")
    return flags


def _question_readability_flags(question: str) -> list[str]:
    """Cheap voice-readability gate for questions that will be spoken aloud."""
    text = _clean_track_value(question)
    lowered = text.lower()
    if not text:
        return ["empty_question"]
    flags: list[str] = []
    words = re.findall(r"[A-Za-z0-9%+.-]+", text)
    if len(words) > 46:
        flags.append("over_46_words")
    if text.count("?") > 1:
        flags.append("multiple_question_marks")
    chain_count = len(re.findall(r"\b(?:and|then|also)\s+(?:how|what|why|where|when|which)\b", lowered))
    chain_count += max(0, len(re.findall(r"\b(?:how|what|why|where|when|which)\b", lowered)) - 3)
    if chain_count >= 2:
        flags.append("multi_challenge_chain")
    if len(re.findall(r"[,;:]", text)) >= 5 and len(words) > 34:
        flags.append("overpacked_clauses")
    return flags


def _question_repair_safety_flags(question: str) -> list[str]:
    text = _clean_track_value(question)
    flags = list(_question_readability_flags(text))
    words = re.findall(r"[A-Za-z0-9%+.-]+", text)
    if len(words) < 15:
        flags.append("under_15_words")
    if "?" not in text:
        flags.append("missing_question_mark")
    if re.search(r"\b(?:for|with|through|from|to|and|or|because|while|during|via|on|at|the|a|an)$", text.lower()):
        flags.append("appears_truncated")
    if text and text[-1] not in ".?!'\"":
        flags.append("appears_truncated")
    if any(term in text.lower() for term in ("manifold", "epistemic", "orthogonal", "latent space")):
        flags.append("overly_abstract_language")
    return sorted(set(flags))


_SCHEMA_RESCUE_PLACEHOLDER_TERMS = {
    "statistical significance",
    "long-term retention",
    "funnel analysis",
    "hypothesis testing",
    "data-driven decision making",
    "business impact",
    "user engagement",
    "metric analysis",
    "product decision",
    "implementation details",
}


def _track_schema_rescue_quality_flags(track: dict, *, seed: dict) -> list[str]:
    """Reject shape-repaired tracks that are valid JSON but bad interview material."""
    flags: list[str] = []
    ladder = track.get("question_ladder") if isinstance(track.get("question_ladder"), list) else []
    dims = track.get("dimensions") if isinstance(track.get("dimensions"), list) else []
    recovery = track.get("recovery") if isinstance(track.get("recovery"), dict) else {}

    postures = {
        str(item.get("posture") or "").strip().lower()
        for item in ladder
        if isinstance(item, dict)
    }
    missing_postures = set(_QUESTION_LADDER_POSTURES) - postures
    if missing_postures:
        flags.append("ladder_missing_postures:" + ",".join(sorted(missing_postures)))

    high_info_count = sum(
        1
        for item in ladder
        if isinstance(item, dict) and str(item.get("information_gain") or "").lower() == "high"
    )
    if high_info_count < 3:
        flags.append("ladder_high_info_below_3")

    for index, item in enumerate(ladder):
        if not isinstance(item, dict):
            continue
        posture = str(item.get("posture") or "").strip().lower()
        main_question = _clean_track_value(item.get("main_question", ""))
        if not main_question:
            flags.append(f"ladder[{index}].empty_main_question")
            continue
        words = re.findall(r"[A-Za-z0-9%+.-]+", main_question)
        if "?" not in main_question:
            flags.append(f"ladder[{index}].missing_question_mark")
        if len(words) < 6:
            flags.append(f"ladder[{index}].too_short_question")
        if "appears_truncated" in _question_repair_safety_flags(main_question):
            flags.append(f"ladder[{index}].appears_truncated")
        for assumption_flag in _unsupported_hidden_assumption_flags(main_question, seed):
            flags.append(f"ladder[{index}].{assumption_flag}")
        if posture in {"frame", "clarify", "explore", "pressure"} and not item.get("expected_space"):
            flags.append(f"ladder[{index}].empty_expected_space")

    if len(dims) < 2:
        flags.append("dimensions_below_2")
    for index, dim in enumerate(dims):
        if not isinstance(dim, dict):
            continue
        try:
            signal_weight = float(dim.get("signal_weight") or 0)
        except (TypeError, ValueError):
            signal_weight = 0.0
        if signal_weight < 1.0:
            flags.append(f"dimensions[{index}].signal_weight_too_low")
        for field in ("surface", "mechanism", "boundary"):
            text = _clean_track_value(dim.get(field, ""))
            lowered = text.lower()
            words = re.findall(r"[A-Za-z0-9%+.-]+", text)
            if len(words) < 5:
                flags.append(f"dimensions[{index}].{field}_too_short")
            if lowered in _SCHEMA_RESCUE_PLACEHOLDER_TERMS or any(
                lowered == term or lowered.startswith(term + " ")
                for term in _SCHEMA_RESCUE_PLACEHOLDER_TERMS
            ):
                flags.append(f"dimensions[{index}].{field}_placeholder")
            if "?" not in text:
                flags.append(f"dimensions[{index}].{field}_not_question")
            for assumption_flag in _unsupported_hidden_assumption_flags(text, seed):
                flags.append(f"dimensions[{index}].{field}_{assumption_flag}")

    for field, value in recovery.items():
        text = _clean_track_value(value)
        if re.match(r"^(?:i|i'm|i am|we|we're|we are)\b", text.lower()):
            flags.append(f"recovery.{field}_candidate_voice")

    return sorted(set(flags))


def _iter_track_question_fields(area: dict) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for index, item in enumerate(area.get("question_ladder") or []):
        if not isinstance(item, dict):
            continue
        for key in ("main_question", "follow_up_if_shallow", "follow_up_if_strong"):
            value = _clean_track_value(item.get(key, ""))
            if value:
                fields.append((f"question_ladder[{index}].{key}", value))
    opener = _track_opener(area)
    if opener:
        fields.append(("opener", opener))
    for index, dim in enumerate(_track_dimensions(area)):
        if not isinstance(dim, dict):
            continue
        for key in ("surface", "mechanism", "boundary"):
            value = _clean_track_value(dim.get(key, ""))
            if value:
                fields.append((f"dimensions[{index}].{key}", value))
    recovery = _track_recovery(area)
    for key in ("short_answer", "honest_gap", "claim_conflict", "metric_risk", "overclaim_risk", "bridge"):
        value = _clean_track_value(recovery.get(key, ""))
        if value:
            fields.append((f"recovery.{key}", value))
    for index, value in enumerate(_track_candidate_q4_options(area)):
        clean = _clean_track_value(value)
        if clean:
            fields.append((f"candidate_q4_options[{index}]", clean))
    return fields


def _focus_boundary_resolution(area: dict) -> dict[str, Any]:
    surface_kind = _primary_surface_kind(area)
    if surface_kind in {"event_taxonomy"}:
        return {
            "kind": "taxonomy",
            "source": "typed_surface_kind",
            "heuristic_fallback_used": False,
            "surface_kind": surface_kind,
        }
    if surface_kind in {"dashboard_reporting", "acquisition_marketing"}:
        return {
            "kind": "dashboard",
            "source": "typed_surface_kind",
            "heuristic_fallback_used": False,
            "surface_kind": surface_kind,
        }
    if surface_kind in {"conversion_experiment", "retention_experiment"}:
        return {
            "kind": "conversion",
            "source": "typed_surface_kind",
            "heuristic_fallback_used": False,
            "surface_kind": surface_kind,
        }
    text = " ".join([
        str(area.get("label", "")),
        str(area.get("focus_key", "")),
        str(area.get("anchor_context", "")),
        " ".join(str(sf.get("label", "")) for sf in _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or ""))),
    ]).lower()
    if any(token in text for token in ("event taxonomy", "instrumentation", "tracking", "event schema", "event definition", "taxonomy")):
        return {
            "kind": "taxonomy",
            "source": "keyword_heuristic_fallback",
            "heuristic_fallback_used": True,
            "surface_kind": surface_kind,
        }
    if any(token in text for token in ("dashboard", "appsflyer", "cac", "cpi", "cpm", "campaign", "acquisition", "reporting")):
        return {
            "kind": "dashboard",
            "source": "keyword_heuristic_fallback",
            "heuristic_fallback_used": True,
            "surface_kind": surface_kind,
        }
    if any(token in text for token in ("retention", "conversion", "subscription", "trial", "pricing", "a/b", "experiment", "funnel")):
        return {
            "kind": "conversion",
            "source": "keyword_heuristic_fallback",
            "heuristic_fallback_used": True,
            "surface_kind": surface_kind,
        }
    return {
        "kind": "unknown",
        "source": "unclassified",
        "heuristic_fallback_used": False,
        "surface_kind": surface_kind,
    }


def _focus_boundary_kind(area: dict) -> str:
    return str(_focus_boundary_resolution(area).get("kind") or "unknown")


def _has_any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _boundary_leak_issue(area: dict, path: str, question: str, *, target_role: str = "") -> dict | None:
    boundary_resolution = _focus_boundary_resolution(area)
    kind = str(boundary_resolution.get("kind") or "unknown")
    if kind == "unknown":
        return None
    lowered = question.lower()
    focus_key = _clean_track_value(area.get("focus_key", ""))
    role_is_analytics = _is_analyst_or_pm_role(target_role)
    if kind == "taxonomy":
        outcome_tokens = ("trial", "subscription", "retention", "conversion", "lift", "revenue", "pricing", "completion", "churn")
        taxonomy_tokens = (
            "event", "schema", "taxonomy", "tracking", "instrument", "dedupe",
            "attribution", "late", "denominator", "definition", "logged", "webhook",
        )
        analysis_intent_tokens = (
            "what moved", "why did", "caused", "cause", "driver", "drove",
            "rule out", "baseline", "cohort", "guardrail", "experiment",
            "measure", "measured", "attribution", "noise", "confound",
        )
        outcome_led_but_role_valid = (
            role_is_analytics
            and _has_any_phrase(lowered, outcome_tokens)
            and _has_any_phrase(lowered, analysis_intent_tokens)
        )
        if (
            _has_any_phrase(lowered, outcome_tokens)
            and not _has_any_phrase(lowered, taxonomy_tokens)
            and not outcome_led_but_role_valid
        ):
            return {
                "issue_scope": "field_level",
                "focus_key": focus_key,
                "path": path,
                "severity": "major" if path == "opener" else "minor",
                "action": "surgical_repair",
                "boundary_kind_source": boundary_resolution.get("source"),
                "heuristic_fallback_used": bool(boundary_resolution.get("heuristic_fallback_used")),
                "reason": "Taxonomy/instrumentation question drifts into outcome metrics without testing measurement, causal analysis, event definitions, schema, dedupe, late events, attribution instrumentation, or ownership boundaries.",
            }
    if kind == "conversion":
        dashboard_tokens = ("dashboard", "cac", "cpi", "cpm", "appsflyer", "spend", "ad-set", "acquisition")
        conversion_tokens = (
            "denominator", "guardrail", "causal", "attribution", "experiment",
            "lift", "baseline", "cohort", "conversion", "retention", "trial",
            "churn", "checkout", "pricing", "funnel", "holdout", "seasonal",
            "buyer", "seller", "success", "activation",
        )
        if any(token in lowered for token in dashboard_tokens) and not any(token in lowered for token in conversion_tokens):
            return {
                "issue_scope": "field_level",
                "focus_key": focus_key,
                "path": path,
                "severity": "minor",
                "action": "surgical_repair",
                "boundary_kind_source": boundary_resolution.get("source"),
                "heuristic_fallback_used": bool(boundary_resolution.get("heuristic_fallback_used")),
                "reason": "Conversion/retention question leaks into dashboard reporting instead of causal lift, denominator, guardrails, or experiment attribution.",
            }
    if kind == "dashboard":
        cv_tokens = ("yolo", "opencv", "optical flow", "sort", "vehicle", "computer vision")
        dashboard_tokens = ("dashboard", "attribution", "window", "join", "latency", "reconcile", "campaign", "decision", "cac", "cpi", "cpm", "spend")
        if any(token in lowered for token in cv_tokens) and not any(token in lowered for token in dashboard_tokens):
            return {
                "issue_scope": "field_level",
                "focus_key": focus_key,
                "path": path,
                "severity": "major",
                "action": "surgical_repair",
                "boundary_kind_source": boundary_resolution.get("source"),
                "heuristic_fallback_used": bool(boundary_resolution.get("heuristic_fallback_used")),
                "reason": "Dashboard/acquisition question leaks into unrelated technical work instead of attribution windows, joins, latency, reconciliation, or decision use.",
            }
    return None


def _cheap_structural_review(candidate: dict, *, target_role: str = "") -> dict:
    """Deterministic review layer: cheap, typed, and local whenever possible."""
    typed_issues: list[dict] = []
    repair_targets: list[dict] = []
    focus_reviews: dict[str, dict] = {}
    role_is_analytics = _is_analyst_or_pm_role(target_role)

    for area in candidate.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        focus_key = _clean_track_value(area.get("focus_key", ""))
        label = _clean_track_value(area.get("label", ""))
        review = focus_reviews.setdefault(focus_key, {
            "focus_key": focus_key,
            "label": label,
            "score": 8.0,
            "opener_issue": "",
            "issues": [],
        })
        boundary_resolution = _focus_boundary_resolution(area)
        if boundary_resolution.get("heuristic_fallback_used"):
            review["issues"].append(
                "Boundary classification used keyword heuristic fallback because typed surface_kind metadata was missing or unusable."
            )
            typed_issues.append({
                "issue_scope": "weighting_level",
                "focus_key": focus_key,
                "path": "sub_focuses[*].surface_kind",
                "severity": "minor",
                "action": "accept_with_warning",
                "reason": "Typed surface_kind metadata was missing or unusable, so boundary validation used keyword heuristic fallback.",
                "heuristic_fallback_used": True,
                "boundary_kind": boundary_resolution.get("kind"),
                "boundary_kind_source": boundary_resolution.get("source"),
            })
        for path, question in _iter_track_question_fields(area.get("track") if isinstance(area.get("track"), dict) else area):
            flags = _question_readability_flags(question)
            if flags:
                issue = {
                    "issue_scope": "readability_level",
                    "focus_key": focus_key,
                    "path": path,
                    "severity": "major" if "empty_question" in flags or path == "opener" else "minor",
                    "action": "surgical_repair",
                    "reason": f"Voice-readability issue: {', '.join(flags)}.",
                }
                typed_issues.append(issue)
                repair_targets.append({
                    **issue,
                    "issue": issue["reason"],
                    "instruction": "Replace only this field with one concise, spoken interview question under about 40 words.",
                })
                review["issues"].append(issue["reason"])
                if path == "opener":
                    review["opener_issue"] = issue["reason"]
            if role_is_analytics:
                boundary_issue = _boundary_leak_issue(area, path, question, target_role=target_role)
                if boundary_issue:
                    if (
                        path.startswith("question_ladder")
                        or path.startswith("recovery.")
                        or path.startswith("candidate_q4_options")
                    ) and _focus_area_priority_value(area) >= 2.5:
                        boundary_issue = {
                            **boundary_issue,
                            "severity": "major",
                        }
                    typed_issues.append(boundary_issue)
                    repair_targets.append({
                        **boundary_issue,
                        "issue": boundary_issue["reason"],
                        "instruction": "Replace only this field so it stays inside the focus boundary and remains grounded in the resume.",
                    })
                    review["issues"].append(boundary_issue["reason"])
                    if path == "opener":
                        review["opener_issue"] = boundary_issue["reason"]

    weight_warnings = _weight_calibration_warnings(candidate)
    for warning in weight_warnings:
        typed_issues.append({
            "issue_scope": "weighting_level",
            "focus_key": str(warning.get("focus_key") or ""),
            "path": str(warning.get("path") or ""),
            "severity": str(warning.get("severity") or "minor"),
            "action": "accept_with_warning",
            "reason": str(warning.get("warning") or ""),
        })

    return {
        "typed_issues": typed_issues[:24],
        "repair_targets": repair_targets[:12],
        "focus_reviews": list(focus_reviews.values())[:_MAP_TARGET_FOCUS_AREAS],
        "weight_calibration_warnings": weight_warnings,
    }


def _merge_cheap_review(review: dict, cheap: dict) -> dict:
    if not isinstance(review, dict):
        review = {}
    merged = dict(review)
    typed = list(merged.get("typed_issues") or [])
    targets = list(merged.get("repair_targets") or [])
    seen_issues = {
        (
            str(i.get("focus_key") or ""),
            str(i.get("path") or ""),
            str(i.get("issue_scope") or ""),
            str(i.get("reason") or ""),
        )
        for i in typed
        if isinstance(i, dict)
    }
    for issue in cheap.get("typed_issues") or []:
        if not isinstance(issue, dict):
            continue
        key = (
            str(issue.get("focus_key") or ""),
            str(issue.get("path") or ""),
            str(issue.get("issue_scope") or ""),
            str(issue.get("reason") or ""),
        )
        if key not in seen_issues:
            typed.append(issue)
            seen_issues.add(key)
    seen_targets = {
        (str(t.get("focus_key") or ""), str(t.get("path") or ""), str(t.get("issue") or ""))
        for t in targets
        if isinstance(t, dict)
    }
    for target in cheap.get("repair_targets") or []:
        if not isinstance(target, dict):
            continue
        key = (str(target.get("focus_key") or ""), str(target.get("path") or ""), str(target.get("issue") or ""))
        if key not in seen_targets:
            targets.append(target)
            seen_targets.add(key)
    merged["typed_issues"] = typed[:24]
    merged["repair_targets"] = targets[:12]
    merged["weight_calibration_warnings"] = cheap.get("weight_calibration_warnings") or merged.get("weight_calibration_warnings") or []
    blocking_targets = [
        target
        for target in targets
        if isinstance(target, dict)
        and (
            str(target.get("severity") or "").lower() == "major"
            and str(target.get("path") or "") == "opener"
        )
    ]
    if blocking_targets:
        merged["ready"] = False

    focus_by_key = {
        str(item.get("focus_key") or ""): dict(item)
        for item in (merged.get("focus_reviews") or [])
        if isinstance(item, dict)
    }
    for cheap_fr in cheap.get("focus_reviews") or []:
        if not isinstance(cheap_fr, dict):
            continue
        key = str(cheap_fr.get("focus_key") or "")
        if not key:
            continue
        existing = focus_by_key.setdefault(key, {
            "focus_key": key,
            "label": str(cheap_fr.get("label") or ""),
            "score": 8.0,
            "opener_issue": "",
            "issues": [],
        })
        issues = list(existing.get("issues") or [])
        for issue in cheap_fr.get("issues") or []:
            if issue and issue not in issues:
                issues.append(issue)
        existing["issues"] = issues[:6]
        if cheap_fr.get("opener_issue") and not existing.get("opener_issue"):
            existing["opener_issue"] = cheap_fr.get("opener_issue")
        if cheap_fr.get("opener_issue"):
            existing["score"] = min(float(existing.get("score") or 8.0), 6.8)
        elif issues:
            existing["score"] = min(float(existing.get("score") or 8.0), 7.2)
    if focus_by_key:
        merged["focus_reviews"] = list(focus_by_key.values())[:_MAP_TARGET_FOCUS_AREAS]
    return merged


def _parse_track_output(raw: dict | str, seed: dict, fallback_track: dict) -> dict:
    if isinstance(raw, dict):
        result = raw
    elif isinstance(raw, str):
        result = _load_json_lenient(raw)
        if not isinstance(result, dict):
            raise ValueError(f"Track output was not a JSON object for {seed.get('focus_key')}")
    else:
        raise ValueError(f"Unexpected track output type: {type(raw)}")

    cleaned_result: dict[str, dict[str, str]] = {}
    llm_branches: list[str] = []
    for sprint_key in _SPRINT_KEYS:
        track = result.get(sprint_key, {})
        if not isinstance(track, dict):
            track = {}
        cleaned_track: dict[str, str] = {}
        for branch in _VALID_BRANCHES:
            value = _clean_track_value(track.get(branch, ""))
            if value and not _question_is_generic_or_off_focus(value, seed):
                cleaned_track[branch] = value
                llm_branches.append(f"{sprint_key}.{branch}")
        if _VALID_BRANCHES - set(cleaned_track):
            raise ValueError(f"{sprint_key} missing LLM-authored branches")
        cleaned_result[sprint_key] = cleaned_track
    return {
        "track": cleaned_result,
        "llm_branches": llm_branches,
        "fallback_branches": [],
        "llm_branch_count": len(llm_branches),
        "fallback_branch_count": 0,
    }


async def _repair_track_schema_only(
    *,
    raw_track: object,
    seed: dict,
    parse_error: Exception,
    session_id: str = "",
) -> dict | None:
    """
    Cheap shape-only rescue for useful track content in the wrong JSON contract.

    This is deliberately not a content rewrite. It asks a small model to preserve
    the candidate-specific questions while normalizing the object into the
    unified ladder + legacy compatibility schema. If the normalized output still
    fails the local parser, Sonnet full rescue can handle the content problem.
    """
    if not _MAP_TRACK_SCHEMA_RESCUE_MODEL:
        return None
    prompt = "\n".join([
        "You are a JSON schema normalizer for an interview-map track.",
        "Do not invent new interview questions. Do not improve wording. Preserve the useful content from the raw output.",
        "Return exactly one JSON object with these root keys:",
        "opener, question_ladder, dimensions, recovery, candidate_q4_options.",
        "",
        "Unified contract:",
        "- question_ladder: exactly these postures when available: frame, clarify, explore, pressure, synthesize, recover.",
        "- each ladder item needs posture, main_question, signal_goal, expected_space, follow_up_if_shallow, follow_up_if_strong, information_gain, voice_complexity.",
        "- dimensions: 2-5 objects with id, label, resume_anchor, surface, mechanism, boundary, signal_weight.",
        "- recovery: short_answer, honest_gap, claim_conflict, metric_risk, overclaim_risk, bridge.",
        "- If legacy fields are missing but ladder content exists, derive compatibility fields from the ladder text only.",
        "- If content is genuinely absent, leave the field empty; do not make up new assessment content.",
        "",
        f"Focus key: {seed.get('focus_key', '')}",
        f"Focus label: {seed.get('label', '')}",
        f"Parser error to fix: {type(parse_error).__name__}: {str(parse_error)[:500]}",
        "",
        "Raw model output:",
        _safe_json_preview(raw_track, limit=9000),
    ])
    llm = LLMRouter(
        tier="small",
        model_override=_MAP_TRACK_SCHEMA_RESCUE_MODEL,
        timeout_override=30.0,
    )
    try:
        started = time.perf_counter()
        repaired_raw = await llm.call(
            system="You repair JSON shape only. Return JSON object only.",
            user=prompt,
            max_tokens=2200,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        parsed = _parse_dimension_output(repaired_raw, seed)
        quality_flags = _track_schema_rescue_quality_flags(parsed, seed=seed)
        if quality_flags:
            raise RuntimeError(
                "schema_repair_quality_rejected: " + ", ".join(quality_flags[:8])
            )
        parsed["_schema_repair_used"] = True
        parsed["_schema_repair_model"] = llm.model
        parsed["_schema_repair_latency_ms"] = round((time.perf_counter() - started) * 1000)
        return parsed
    except Exception as exc:
        print(
            f"[TrajectoryMap] Track schema repair failed"
            + (f" for {session_id[:8]}" if session_id else "")
            + f" focus={seed.get('focus_key')}: {type(exc).__name__}: {str(exc)[:220]}"
        )
        return None


async def _generate_focus_track(
    *,
    resume_context: str,
    seed: dict,
    next_focus_label: str,
    session_id: str,
    fast_mode: bool = True,
    repair_guidance: str = "",
    prior_track_context: str = "",
    role_type: str = "",
) -> dict:
    def _make_user(snippets_limit: int, anchor_limit: int) -> str:
        prior_block = (
            f"\nPrior track context (for deduplication):\n{prior_track_context}\n"
            if prior_track_context.strip()
            else ""
        )
        sub_focuses = _normalize_sub_focuses(seed.get("sub_focuses"), focus_key=str(seed.get("focus_key") or ""))
        sub_focuses_block = (
            "- Sub-focuses (must have >=1 dimension each, prioritize higher coverage_value): "
            + " | ".join(
                (
                    f"{sf.get('label')} "
                    f"(role_relevance {sf.get('role_relevance_weight')}, "
                    f"profile_importance {sf.get('profile_importance_weight')}, "
                    f"evidence {sf.get('evidence_strength')}, "
                    f"claim_risk {sf.get('claim_risk')}, "
                    f"coverage_value {sf.get('coverage_value')})"
                )
                for sf in sub_focuses
            )
            + "\n"
            if sub_focuses
            else ""
        )
        return _TRACK_USER_TEMPLATE.format(
            resume_context=resume_context,
            label=seed["label"],
            focus_key=seed["focus_key"][:64],
            anchor_context=_anchor_context_for_focus(seed)[:anchor_limit] or seed["label"],
            sub_focuses_block=sub_focuses_block,
            resume_snippets="\n".join(f"- {s}" for s in seed.get("resume_snippets", [])[:snippets_limit]) or "- None available",
            next_focus_label=next_focus_label or "another area from the candidate's background",
            repair_guidance=repair_guidance.strip() or "None. Write the strongest grounded track you can.",
            prior_track_context=prior_block,
        )

    # Policy: primary generator first, then direct Sonnet rescue. DeepSeek audit
    # is handled separately and is never a required bridge before Sonnet.
    primary_tokens = 2800 if fast_mode else 4200
    primary_timeout = _FOCUS_TRACK_TIMEOUT_SECONDS if fast_mode else _FOCUS_TRACK_BACKGROUND_TIMEOUT_SECONDS
    llm = LLMRouter(
        tier="small" if fast_mode else "medium",
        model_override=None if fast_mode else _MAP_GENERATOR_MODEL,
        timeout_override=None if fast_mode else 90.0,
    )
    user = _make_user(snippets_limit=5, anchor_limit=400)
    last_error: Exception | None = None
    attempt_errors: list[dict] = []

    _track_sys = _track_system_prompt(role_type)

    async def _attempt(llm_: LLMRouter, prompt: str, max_tok: int, timeout: float) -> dict | None:
        nonlocal last_error

        def _raw_shape(raw_value: object, exc: Exception) -> dict:
            shape = {
                "model": llm_.model,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "raw_type": type(raw_value).__name__,
            }
            if isinstance(raw_value, dict):
                shape["raw_keys"] = list(raw_value.keys())[:12]
            elif isinstance(raw_value, list):
                shape["raw_len"] = len(raw_value)
            try:
                shape["raw_preview"] = _json_text(raw_value)[:3000]
            except Exception:
                shape["raw_preview"] = str(raw_value)[:3000]
            return shape

        try:
            raw = await asyncio.wait_for(
                llm_.call(
                    system=_track_sys,
                    user=prompt,
                    max_tokens=max_tok,
                    response_format=_MAP_JSON_RESPONSE_FORMAT,
                ),
                timeout=timeout,
            )
            try:
                parsed_track = _parse_dimension_output(raw, seed)
            except Exception as parse_exc:
                repaired_track = await _repair_track_schema_only(
                    raw_track=raw,
                    seed=seed,
                    parse_error=parse_exc,
                    session_id=session_id,
                )
                if repaired_track:
                    attempt_errors.append({
                        **_raw_shape(raw, parse_exc),
                        "schema_repair_used": True,
                        "schema_repair_model": repaired_track.get("_schema_repair_model"),
                        "schema_repair_latency_ms": repaired_track.get("_schema_repair_latency_ms"),
                    })
                    return {
                        "track": repaired_track,
                        "source": "llm",
                        "model": llm_.model,
                        "generation_attempt_errors": attempt_errors[:],
                        "generation_strategy": "schema_repaired_track",
                    }
                last_error = parse_exc
                attempt_errors.append(_raw_shape(raw, parse_exc))
                return None
            return {
                "track": parsed_track,
                "source": "llm",
                "model": llm_.model,
                "generation_attempt_errors": attempt_errors[:],
            }
        except Exception as exc:
            last_error = exc
            attempt_errors.append({
                "model": llm_.model,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })
            affordable = _affordable_token_budget_from_error(exc)
            if affordable and affordable < max_tok:
                try:
                    raw2 = await asyncio.wait_for(
                        llm_.call(
                            system=_track_sys,
                            user=prompt,
                            max_tokens=affordable,
                            response_format=_MAP_JSON_RESPONSE_FORMAT,
                        ),
                        timeout=timeout,
                    )
                    try:
                        parsed_track2 = _parse_dimension_output(raw2, seed)
                    except Exception as parse_exc2:
                        repaired_track2 = await _repair_track_schema_only(
                            raw_track=raw2,
                            seed=seed,
                            parse_error=parse_exc2,
                            session_id=session_id,
                        )
                        if repaired_track2:
                            attempt_errors.append({
                                **_raw_shape(raw2, parse_exc2),
                                "schema_repair_used": True,
                                "schema_repair_model": repaired_track2.get("_schema_repair_model"),
                                "schema_repair_latency_ms": repaired_track2.get("_schema_repair_latency_ms"),
                            })
                            return {
                                "track": repaired_track2,
                                "source": "llm",
                                "model": llm_.model,
                                "generation_attempt_errors": attempt_errors[:],
                                "generation_strategy": "schema_repaired_track",
                            }
                        last_error = parse_exc2
                        attempt_errors.append(_raw_shape(raw2, parse_exc2))
                        return None
                    return {
                        "track": parsed_track2,
                        "source": "llm",
                        "model": llm_.model,
                        "generation_attempt_errors": attempt_errors[:],
                    }
                except Exception as exc2:
                    last_error = exc2
                    attempt_errors.append({
                        "model": llm_.model,
                        "error_type": type(exc2).__name__,
                        "error": str(exc2)[:500],
                    })
            return None

    result = await _attempt(llm, user, primary_tokens, primary_timeout)
    if result:
        return result

    # Direct rescue retry. This intentionally skips DeepSeek as a blocking
    # middle step so slow cheap audit cannot delay a Sonnet save.
    if fast_mode:
        retry_llm = LLMRouter(tier="medium", model_override=_MAP_RESCUE_MODEL, timeout_override=12.0)
        retry_user = _make_user(snippets_limit=4, anchor_limit=300)
        result = await _attempt(retry_llm, retry_user, 2800, 12.0)
    else:
        retry_llm = LLMRouter(tier="medium", model_override=_MAP_RESCUE_MODEL, timeout_override=90.0)
        retry_user = _make_user(snippets_limit=4, anchor_limit=320)
        result = await _attempt(retry_llm, retry_user, 4200, 90.0)

    if result:
        return result

    raise RuntimeError(
        f"Focus track generation failed for {seed['focus_key']}; refusing deterministic fallback: "
        f"{type(last_error).__name__}: {str(last_error) or '(no message)'}; "
        f"attempt_errors={_json_text(attempt_errors)[:1500]}"
    )


def _launch_text(value: object) -> str:
    """Coerce common model-authored text wrappers without inventing content."""
    if isinstance(value, str):
        return _clean_track_value(value)
    if isinstance(value, (int, float, bool)):
        return _clean_track_value(value)
    if isinstance(value, list):
        parts = [_launch_text(item) for item in value]
        return _clean_track_value(" ".join(part for part in parts if part))
    if isinstance(value, dict):
        for key in (
            "main_question",
            "question",
            "prompt",
            "text",
            "value",
            "surface",
            "ask",
            "follow_up",
            "follow_up_if_shallow",
        ):
            text = _launch_text(value.get(key))
            if text:
                return text
        return _clean_track_value(" ".join(_launch_text(v) for v in value.values()))
    return ""


def _launch_expected_space(value: object) -> list[str]:
    if isinstance(value, list):
        items = [_launch_text(item) for item in value]
    elif isinstance(value, str):
        items = [part.strip() for part in re.split(r"[,;|]\s*", value) if part.strip()]
    elif isinstance(value, dict):
        items = [_launch_text(value)]
    else:
        items = []
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = _clean_track_value(item)
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean[:120])
    return out[:6]


def _launch_question_from_ladder(raw: dict, posture: str) -> dict:
    for key in ("question_ladder", "ladder", "questions"):
        ladder = raw.get(key)
        if not isinstance(ladder, list):
            continue
        for item in ladder:
            if not isinstance(item, dict):
                continue
            if _clean_track_value(item.get("posture", "")).lower() == posture:
                return item
    return {}


def _question_has_pressure_tone(question: str) -> bool:
    text = _clean_track_value(question).lower()
    if not text:
        return False
    pressure_markers = (
        "prove ",
        "defend ",
        "justify ",
        "why should i believe",
        "what makes you think",
        "how do you know this wasn't",
        "what would invalidate",
        "what failure would",
        "what confounder would",
    )
    return any(marker in text for marker in pressure_markers)


def _normalize_launch_question(raw: object, *, posture: str) -> dict:
    if not isinstance(raw, dict):
        raw = {"main_question": raw}
    question = _launch_text(raw)
    if not question:
        question = _launch_text(raw.get("main_question") or raw.get("question") or raw.get("prompt"))
    raw_gain = _clean_track_value(raw.get("information_gain") or "high").lower()
    if posture in {"frame", "clarify", "pressure"}:
        information_gain = "high"
    elif raw_gain in {"high", "medium", "low"}:
        information_gain = raw_gain
    else:
        information_gain = "high"
    raw_voice = _clean_track_value(raw.get("voice_complexity") or "low").lower()
    return {
        "posture": posture,
        "main_question": question,
        "signal_goal": _launch_text(raw.get("signal_goal") or raw.get("goal") or raw.get("assessment_goal"))[:180],
        "expected_space": _launch_expected_space(raw.get("expected_space") or raw.get("answer_space") or raw.get("expected_answer")),
        "follow_up_if_shallow": _launch_text(raw.get("follow_up_if_shallow") or raw.get("shallow_follow_up"))[:260],
        "follow_up_if_strong": _launch_text(raw.get("follow_up_if_strong") or raw.get("strong_follow_up"))[:260],
        "information_gain": information_gain,
        "voice_complexity": raw_voice if raw_voice in {"low", "medium", "high"} else "low",
    }


def _normalize_launch_dimension(raw: object, *, seed: dict, index: int) -> dict | None:
    if not isinstance(raw, dict):
        raw = {"question": raw}
    question = _launch_text(raw.get("question") or raw.get("surface") or raw.get("main_question") or raw.get("prompt"))
    if not question:
        return None
    dim_id = _normalize_key(_launch_text(raw.get("id") or raw.get("label") or f"launch_dimension_{index + 1}")) or f"launch_dimension_{index + 1}"
    surface_kind = _normalize_surface_kind(raw.get("surface_kind") or raw.get("kind") or "")
    if surface_kind == "other":
        surface_kind = "breadth" if index == 0 else "depth"
    return {
        "id": dim_id[:80],
        "label": _launch_text(raw.get("label") or dim_id.replace("_", " ").title())[:140],
        "resume_anchor": _launch_text(raw.get("resume_anchor") or raw.get("anchor") or _anchor_context_for_focus(seed))[:280],
        "question": question,
        "signal_goal": _launch_text(raw.get("signal_goal") or raw.get("goal") or "")[:180],
        "surface_kind": surface_kind,
        "signal_weight": _safe_float(raw.get("signal_weight"), 2.5, min_value=1.0, max_value=3.0),
    }


def _launch_lite_to_runtime_track(raw: dict, seed: dict) -> dict:
    ladder = [
        {
            **raw[posture],
            "posture": posture,
        }
        for posture in ("frame", "clarify", "explore", "pressure")
    ]
    recover_question = _launch_text(raw.get("recover_short_answer", ""))
    ladder.append({
        "posture": "recover",
        "main_question": recover_question,
        "signal_goal": "Recover one concrete detail without changing focus.",
        "expected_space": ["specific example", "scope", "evidence"],
        "follow_up_if_shallow": recover_question,
        "follow_up_if_strong": "",
        "information_gain": "medium",
        "voice_complexity": "low",
    })

    dims: list[dict] = []
    for index, dim in enumerate(raw.get("dimensions") or []):
        if not isinstance(dim, dict):
            continue
        question = _clean_track_value(dim.get("question", ""))
        if not question:
            continue
        kind = _clean_track_value(dim.get("surface_kind", "")).lower()
        clarify_q = ladder[1]["main_question"]
        explore_q = ladder[2]["main_question"]
        pressure_q = ladder[3]["main_question"]
        dims.append({
            "id": _normalize_key(dim.get("id") or f"launch_dimension_{index + 1}")[:80],
            "label": _clean_track_value(dim.get("label") or f"Launch dimension {index + 1}"),
            "resume_anchor": _clean_track_value(dim.get("resume_anchor") or _anchor_context_for_focus(seed)),
            "surface": question if kind in {"breadth", "scope", "definition"} or index == 0 else clarify_q,
            "mechanism": explore_q if index == 0 else question,
            "boundary": pressure_q if index == 0 else question,
            "signal_weight": _safe_float(dim.get("signal_weight"), 2.5, min_value=1.0, max_value=3.0),
        })
    result = {
        "map_schema_version": "v3_launch_lite",
        "primary_question_contract": "launch_track_lite",
        "launch_track_lite": True,
        "question_ladder": ladder,
        "opener": ladder[0]["main_question"],
        "dimensions": dims[:2],
        "recovery": {
            "short_answer": recover_question,
            "honest_gap": recover_question,
            "claim_conflict": recover_question,
            "metric_risk": ladder[1]["main_question"],
            "overclaim_risk": ladder[3]["main_question"],
            "bridge": "",
        },
        "candidate_q4_options": [],
        "_launch_lite_raw": {
            "frame": raw.get("frame"),
            "clarify": raw.get("clarify"),
            "explore": raw.get("explore"),
            "pressure": raw.get("pressure"),
            "recover_short_answer": raw.get("recover_short_answer"),
            "dimensions": raw.get("dimensions"),
        },
    }
    legacy_compat = _legacy_compat_from_v2_track(result)
    result["legacy_compat"] = legacy_compat
    result["opener"] = legacy_compat["opener"]
    result["dimensions"] = legacy_compat["dimensions"]
    result["recovery"] = legacy_compat["recovery"]
    result["candidate_q4_options"] = legacy_compat["candidate_q4_options"]
    result["assessment_dimensions"] = legacy_compat["dimensions"]
    return result


def _parse_launch_track_lite(raw: dict | str, seed: dict) -> dict:
    """Parse the V3 startup-only launch-lite track. This is not the full V2 map contract."""
    if isinstance(raw, str):
        parsed = _load_json_lenient(raw)
        if parsed is None:
            raise RuntimeError(f"LaunchTrackLite output was not JSON for {seed.get('focus_key')}.")
        raw = parsed
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        raw = raw[0]
    if isinstance(raw, dict):
        for wrapper in ("launch_track", "launch_track_lite", "track"):
            if isinstance(raw.get(wrapper), dict):
                raw = raw[wrapper]
                break
    if not isinstance(raw, dict):
        raise RuntimeError(f"LaunchTrackLite output must be an object for {seed.get('focus_key')}.")

    normalized: dict[str, Any] = {}
    for posture in ("frame", "clarify", "explore", "pressure"):
        source = raw.get(posture)
        if not source:
            source = _launch_question_from_ladder(raw, posture)
        normalized[posture] = _normalize_launch_question(source or {}, posture=posture)

    normalized["recover_short_answer"] = _launch_text(
        raw.get("recover_short_answer")
        or raw.get("recover")
        or raw.get("short_answer_recovery")
        or _launch_question_from_ladder(raw, "recover")
    )
    dims_source = raw.get("dimensions") or raw.get("assessment_dimensions") or []
    if isinstance(dims_source, dict):
        dims_source = list(dims_source.values())
    dimensions: list[dict] = []
    if isinstance(dims_source, list):
        for index, item in enumerate(dims_source):
            dim = _normalize_launch_dimension(item, seed=seed, index=index)
            if dim:
                dimensions.append(dim)
            if len(dimensions) >= 2:
                break
    normalized["dimensions"] = dimensions

    validated, schema_errors = _validate_schema(normalized, _LaunchTrackLiteSchema)
    if schema_errors:
        raise RuntimeError(f"LaunchTrackLite schema issues for '{seed.get('label', '?')}': {schema_errors[:3]}")

    question_errors: list[str] = []
    for posture in ("frame", "clarify", "explore", "pressure"):
        question = _clean_track_value((validated.get(posture) or {}).get("main_question", ""))
        flags = _question_repair_safety_flags(question)
        if "empty_question" in flags or "appears_truncated" in flags or "missing_question_mark" in flags:
            question_errors.append(f"{posture}: {', '.join(flags)}")
        if posture == "frame" and _question_has_pressure_tone(question):
            question_errors.append("frame: pressure_tone")
        for flag in _unsupported_hidden_assumption_flags(question, seed):
            question_errors.append(f"{posture}: {flag}")
    recover = _clean_track_value(validated.get("recover_short_answer", ""))
    if not recover:
        question_errors.append("recover_short_answer missing")
    elif "appears_truncated" in _question_repair_safety_flags(recover):
        question_errors.append("recover_short_answer truncated")
    if len(validated.get("dimensions") or []) < 2:
        question_errors.append(f"only {len(validated.get('dimensions') or [])} launch dimensions")
    for index, dim in enumerate(validated.get("dimensions") or []):
        question = _clean_track_value(dim.get("question", ""))
        flags = _question_repair_safety_flags(question)
        if "empty_question" in flags or "appears_truncated" in flags or "missing_question_mark" in flags:
            question_errors.append(f"dimensions[{index}].question: {', '.join(flags)}")
        for flag in _unsupported_hidden_assumption_flags(question, seed):
            question_errors.append(f"dimensions[{index}].question: {flag}")
    if question_errors:
        raise RuntimeError(
            f"LaunchTrackLite quality issues for {seed.get('focus_key')}: "
            + "; ".join(question_errors[:8])
        )

    return _launch_lite_to_runtime_track(validated, seed)


async def _repair_launch_track_lite(
    *,
    raw_track: object,
    seed: dict,
    parse_error: Exception,
    session_id: str = "",
) -> dict | None:
    if not _LAUNCH_LITE_REPAIR_MODEL:
        return None
    prompt = "\n".join([
        "You repair one LaunchTrackLite JSON object for interview startup.",
        "Preserve assessment intent and focus. Do not invent a new focus area.",
        "You may fill missing launch-only fields using the focus snippets, but do not create full V2/Q4/synthesis content.",
        "",
        "Required JSON shape:",
        "{frame, clarify, explore, pressure, recover_short_answer, dimensions[2]}",
        "Each question object needs posture, main_question, signal_goal, expected_space, information_gain, voice_complexity.",
        "Every main_question must be spoken English, one question, under 45 words, and include a question mark.",
        "",
        f"Focus key: {seed.get('focus_key', '')}",
        f"Focus label: {seed.get('label', '')}",
        f"Anchor context: {_anchor_context_for_focus(seed)[:600]}",
        "Resume snippets:",
        "\n".join(f"- {s}" for s in (seed.get("resume_snippets") or [])[:5]),
        "",
        f"Parser error to fix: {type(parse_error).__name__}: {str(parse_error)[:800]}",
        "",
        "Raw model output:",
        _safe_json_preview(raw_track, limit=8000),
    ])
    llm = LLMRouter(
        tier="small",
        model_override=_LAUNCH_LITE_REPAIR_MODEL,
        timeout_override=30.0,
    )
    try:
        started = time.perf_counter()
        repaired_raw = await llm.call(
            system="You repair LaunchTrackLite JSON only. Return one JSON object.",
            user=prompt,
            max_tokens=_LAUNCH_LITE_REPAIR_MAX_TOKENS,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        parsed = _parse_launch_track_lite(repaired_raw, seed)
        parsed["_schema_repair_used"] = True
        parsed["_schema_repair_model"] = llm.model
        parsed["_schema_repair_latency_ms"] = round((time.perf_counter() - started) * 1000)
        return parsed
    except Exception as exc:
        print(
            f"[TrajectoryMap] LaunchTrackLite repair failed"
            + (f" for {session_id[:8]}" if session_id else "")
            + f" focus={seed.get('focus_key')}: {type(exc).__name__}: {str(exc)[:220]}"
        )
        return None


async def _generate_launch_track_lite(
    *,
    resume_context: str,
    seed: dict,
    session_id: str,
    target_role: str = "",
) -> dict:
    sub_focuses = _normalize_sub_focuses(seed.get("sub_focuses"), focus_key=str(seed.get("focus_key") or ""))
    sub_focuses_block = (
        "- Sub-focuses: "
        + " | ".join(
            (
                f"{sf.get('label')} "
                f"(surface_kind {sf.get('surface_kind')}, role {sf.get('role_relevance_weight')}, "
                f"profile {sf.get('profile_importance_weight')}, evidence {sf.get('evidence_strength')}, "
                f"risk {sf.get('claim_risk')}, coverage {sf.get('coverage_value')})"
            )
            for sf in sub_focuses[:4]
        )
        + "\n"
        if sub_focuses
        else ""
    )
    user = _LAUNCH_LITE_USER_TEMPLATE.format(
        resume_context=resume_context[:9000],
        target_role=target_role or "unspecified",
        label=seed["label"],
        focus_key=seed["focus_key"][:64],
        anchor_context=_anchor_context_for_focus(seed)[:700] or seed["label"],
        sub_focuses_block=sub_focuses_block,
        resume_snippets="\n".join(f"- {s}" for s in seed.get("resume_snippets", [])[:5]) or "- None available",
    )
    attempts: list[tuple[str, str, float, int]] = [("primary", _MAP_GENERATOR_MODEL, 45.0, _LAUNCH_LITE_MAX_TOKENS)]
    if _MAP_RESCUE_MODEL and _MAP_RESCUE_MODEL != _MAP_GENERATOR_MODEL:
        attempts.append(("rescue", _MAP_RESCUE_MODEL, 60.0, _LAUNCH_LITE_MAX_TOKENS))
    attempt_errors: list[dict] = []
    last_error: Exception | None = None

    for label, model, timeout, max_tokens in attempts:
        llm = LLMRouter(
            tier="medium" if label == "rescue" else "small",
            model_override=model,
            timeout_override=timeout,
        )
        try:
            raw = await asyncio.wait_for(
                llm.call(
                    system=_LAUNCH_LITE_SYSTEM,
                    user=user,
                    max_tokens=max_tokens,
                    response_format=_MAP_JSON_RESPONSE_FORMAT,
                ),
                timeout=timeout,
            )
            try:
                parsed = _parse_launch_track_lite(raw, seed)
            except Exception as parse_exc:
                repaired = await _repair_launch_track_lite(
                    raw_track=raw,
                    seed=seed,
                    parse_error=parse_exc,
                    session_id=session_id,
                )
                attempt_errors.append({
                    "model": llm.model,
                    "attempt": label,
                    "error_type": type(parse_exc).__name__,
                    "error": str(parse_exc)[:500],
                    "raw_type": type(raw).__name__,
                    "raw_keys": list(raw.keys())[:12] if isinstance(raw, dict) else [],
                    "raw_preview": _safe_json_preview(raw, limit=2400),
                    "schema_repair_used": bool(repaired),
                    "schema_repair_model": repaired.get("_schema_repair_model") if repaired else "",
                    "schema_repair_latency_ms": repaired.get("_schema_repair_latency_ms") if repaired else 0,
                })
                if repaired:
                    return {
                        "track": repaired,
                        "source": "llm",
                        "model": llm.model,
                        "generation_attempt_errors": attempt_errors[:],
                        "generation_strategy": "launch_track_lite_schema_repaired",
                        "repair_strategy": "launch_track_lite_schema_repair",
                        "repair_target_count": 1,
                    }
                last_error = parse_exc
                continue
            return {
                "track": parsed,
                "source": "llm",
                "model": llm.model,
                "generation_attempt_errors": attempt_errors[:],
                "generation_strategy": "launch_track_lite",
            }
        except Exception as exc:
            last_error = exc
            attempt_errors.append({
                "model": model,
                "attempt": label,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })

    raise RuntimeError(
        f"LaunchTrackLite generation failed for {seed['focus_key']}: "
        f"{type(last_error).__name__}: {str(last_error) or '(no message)'}; "
        f"attempt_errors={_json_text(attempt_errors)[:1500]}"
    )


async def _generate_launch_lite_tracks_for_candidate(
    *,
    resume: str,
    candidate: dict,
    session_id: str,
    target_role: str = "",
) -> dict:
    focus_areas = list(candidate.get("focus_areas", []) or [])
    if not focus_areas:
        return candidate

    def _make_seed(index: int, area: dict) -> dict:
        focus_key = str(area.get("focus_key", "") or f"focus_{index + 1}").strip()
        sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=focus_key)
        resume_snippets = _clean_resume_snippets(
            list(area.get("resume_snippets", []) or [])
            + [
                snippet
                for sub_focus in sub_focuses
                for snippet in (sub_focus.get("source_snippets") or [])
            ]
        )
        return {
            "label": str(area.get("label", "") or f"Focus Area {index + 1}").strip(),
            "focus_key": focus_key,
            "anchor_context": str(area.get("anchor_context", "") or "").strip() or " ".join(resume_snippets[:2])[:500],
            "sub_focuses": sub_focuses,
            "resume_snippets": resume_snippets,
        }

    async def _gen_track(index: int) -> dict:
        area = focus_areas[index]
        seed = _make_seed(index, area)
        started = time.perf_counter()
        result = await _generate_launch_track_lite(
            resume_context=resume,
            seed=seed,
            session_id=session_id,
            target_role=target_role,
        )
        updated = dict(area)
        updated["track"] = result.get("track")
        updated["_gen_source"] = result.get("source", "llm")
        updated["_gen_model"] = result.get("model", "")
        updated["_track_latency_ms"] = round((time.perf_counter() - started) * 1000)
        updated["_track_generation_strategy"] = result.get("generation_strategy", "launch_track_lite")
        updated["_generation_attempt_errors"] = list(result.get("generation_attempt_errors") or [])
        if result.get("repair_strategy"):
            updated["_repair_strategy"] = result.get("repair_strategy")
            updated["_repair_target_count"] = result.get("repair_target_count", 0)
        return updated

    results = await asyncio.gather(*[_gen_track(i) for i in range(len(focus_areas))])
    return {
        **candidate,
        "focus_areas": results,
        "_map_prep_v3_trace": {
            "launch_track_contract": "LaunchTrackLite",
            "launch_seed_keys": [str(area.get("focus_key") or "") for area in focus_areas],
            "track_attempts": [
                {
                    "focus_key": area.get("focus_key"),
                    "model": area.get("_gen_model"),
                    "strategy": area.get("_track_generation_strategy"),
                    "latency_ms": area.get("_track_latency_ms"),
                    "attempt_errors": area.get("_generation_attempt_errors") or [],
                }
                for area in results
            ],
        },
    }


async def _critique_launch_lite_candidate(
    *,
    resume: str,
    candidate: dict,
    stage: str = "launch_lite_tracks",
    target_role: str = "",
) -> dict:
    compact_candidate = _compact_map_candidate_for_critic(candidate)
    user = "\n".join([
        f"Review stage: {stage}",
        f"Target role: {target_role or 'unspecified'}",
        "",
        "Resume context, only for grounding/off-role checks:",
        resume[:5000],
        "",
        "LaunchTrackLite candidate:",
        _json_text(compact_candidate),
        "",
        "Return exactly one JSON object following the system schema.",
    ])
    llm = LLMRouter(
        tier="medium",
        model_override=_MAP_CRITIC_MODEL,
        timeout_override=60.0,
    )
    started = time.perf_counter()
    try:
        raw = await llm.call(
            system=_LAUNCH_PAIR_CRITIC_SYSTEM,
            user=user,
            max_tokens=_LAUNCH_LITE_CRITIC_MAX_TOKENS,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        payload, notes = _coerce_critic_payload(raw)
        if not isinstance(payload, dict):
            raise RuntimeError(f"launch critic returned {type(payload).__name__}")
        review = _build_critic_review(payload, stage=stage, critic_model=llm.model)
        review["schema_repair_notes"] = notes
        review["latency_ms"] = round((time.perf_counter() - started) * 1000)
        review["critic_contract"] = "compact_launch_lite_pair_critic"
        return review
    except Exception as exc:
        return {
            "stage": stage,
            "critic_model": llm.model,
            "critic_contract": "compact_launch_lite_pair_critic",
            "ready": False,
            "overall_score": 0.0,
            "top_two_score": 0.0,
            "issues": [f"Launch critic failed: {type(exc).__name__}: {str(exc)[:240]}"],
            "focus_reviews": [],
            "typed_issues": [{
                "issue_scope": "plan_level",
                "focus_key": "",
                "path": "",
                "severity": "major",
                "action": "plan_repair",
                "reason": "compact launch critic failed; startup cannot launch without authority review",
            }],
            "repair_targets": [],
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }


def _focus_review_score(critic_feedback: dict | None, focus_key: str) -> float | None:
    """Return the per-area score from the critic for focus_key, or None if not found."""
    if not isinstance(critic_feedback, dict):
        return None
    for fr in (critic_feedback.get("focus_reviews") or []):
        if isinstance(fr, dict) and _clean_track_value(fr.get("focus_key", "")) == focus_key:
            try:
                return float(fr.get("score", 0))
            except (TypeError, ValueError):
                return None
    return None


def _focus_review_has_significant_issues(critic_feedback: dict | None, focus_key: str) -> bool:
    """True only if the critic flagged an opener_issue for this area.
    Minor issues list entries don't block preservation — every area has some notes."""
    if not isinstance(critic_feedback, dict):
        return False
    for fr in (critic_feedback.get("focus_reviews") or []):
        if not isinstance(fr, dict):
            continue
        if _clean_track_value(fr.get("focus_key", "")) != focus_key:
            continue
        opener_issue = str(fr.get("opener_issue") or "").strip()
        try:
            score = float(fr.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        if opener_issue and _opener_issue_blocks_launch(opener_issue, score):
            return True
    return False


def _async_hydration_acceptance(
    *,
    updated_area: dict,
    review: dict,
    focus_key: str,
    focus_score: float,
    focus_issue: str,
) -> tuple[bool, str]:
    """Decide whether a deferred track is usable enough to join the live map.

    Async hydration is not startup authority. A deferred third/fourth surface
    should be quarantined for semantic or structural failures, but not erased
    because of local style notes or stale legacy compatibility fields.
    """
    validation = validate_interview_map(
        {"focus_areas": [updated_area]},
        require_all_llm=True,
        min_focus_areas=1,
    )
    if not validation.get("ready"):
        return False, "; ".join(str(err) for err in (validation.get("errors") or [])[:3])

    for item in updated_area.get("question_ladder") or []:
        if not isinstance(item, dict):
            continue
        question = _clean_track_value(item.get("main_question", ""))
        safety_flags = set(_question_repair_safety_flags(question))
        blocking_flags = safety_flags & {"empty", "appears_truncated", "missing_question_mark"}
        if blocking_flags:
            return False, f"question_ladder.{item.get('posture') or 'unknown'} unsafe: {', '.join(sorted(blocking_flags))}"

    text_parts: list[str] = []
    text_parts.extend(str(issue or "") for issue in (review.get("issues") or []))
    for fr in review.get("focus_reviews") or []:
        if not isinstance(fr, dict) or _clean_track_value(fr.get("focus_key", "")) != focus_key:
            continue
        text_parts.append(str(fr.get("opener_issue") or ""))
        text_parts.extend(str(issue or "") for issue in (fr.get("issues") or []))
    for issue in list(review.get("typed_issues") or []) + list(review.get("repair_targets") or []):
        if not isinstance(issue, dict):
            continue
        if _issue_focus_key_from_path(review, issue) != focus_key:
            continue
        path_lower = _clean_track_value(issue.get("path", "")).lower()
        if _is_legacy_compatibility_path(path_lower):
            continue
        text_parts.append(str(issue.get("reason") or issue.get("issue") or issue.get("instruction") or ""))
    review_text = " ".join(text_parts).lower()
    semantic_blockers = (
        "wrong focus",
        "wrong primary",
        "off-role",
        "off role",
        "unsupported implementation assumption",
        "unsupported implementation detail",
        "unsupported implementation layer",
        "not role-relevant to",
        "not role relevant to",
        "fabricated claim",
        "fabricated resume",
        "fabricated evidence",
        "not grounded in resume",
        "missing question_ladder",
        "unusable track",
    )
    if any(marker in review_text for marker in semantic_blockers):
        return False, "semantic async hydration blocker: " + review_text[:220]
    if focus_issue and _opener_issue_blocks_launch(focus_issue, focus_score) and focus_score < 6.8:
        return False, f"blocking opener issue at score {focus_score:.1f}: {focus_issue[:220]}"
    if focus_score and focus_score < 6.5:
        return False, f"async hydration score {focus_score:.1f} below usable deferred threshold"
    return True, "accepted_deferred_surface_with_warnings" if not _review_is_ready(review) else "accepted_deferred_surface"


def _track_from_candidate(original_candidate: dict | None, focus_key: str) -> dict | None:
    """Extract the generated track dict for focus_key from a prior candidate result."""
    if not isinstance(original_candidate, dict):
        return None
    for area in (original_candidate.get("focus_areas") or []):
        if not isinstance(area, dict):
            continue
        if _clean_track_value(area.get("focus_key", "")) == focus_key:
            return area.get("track") if isinstance(area.get("track"), dict) else None
    return None


def _track_model_from_candidate(original_candidate: dict | None, focus_key: str) -> str:
    """Extract the model provenance for focus_key from a prior candidate result."""
    if not isinstance(original_candidate, dict):
        return ""
    for area in (original_candidate.get("focus_areas") or []):
        if not isinstance(area, dict):
            continue
        if _clean_track_value(area.get("focus_key", "")) == focus_key:
            return str(area.get("_gen_model") or area.get("track_model") or "")
    return ""


def _critic_guidance_for_focus(review: dict | None, focus_key: str) -> str:
    if not isinstance(review, dict):
        return ""
    guidance: list[str] = []
    for instruction in review.get("repair_instructions", []) or []:
        text = _clean_track_value(instruction)
        if text:
            guidance.append(text)
    for item in review.get("focus_reviews", []) or []:
        if not isinstance(item, dict):
            continue
        if _clean_track_value(item.get("focus_key", "")) != focus_key:
            continue
        for issue in item.get("issues", []) or []:
            text = _clean_track_value(issue)
            if text:
                guidance.append(f"Fix this focus-specific weakness: {text}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in guidance:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 6:
            break
    return " ".join(deduped)


def _repair_targets_for_focus(review: dict | None, focus_key: str, label: str = "") -> list[dict]:
    """Return localized repair targets for one focus track.

    Critic output from older runs may only contain focus_reviews/issues, so this
    also infers conservative field-level targets from those notes.
    """
    if not isinstance(review, dict):
        return []
    focus_norm = _clean_track_value(focus_key)
    label_norm = _clean_track_value(label).lower()
    targets: list[dict] = []
    seen: set[tuple[str, str]] = set()
    seen_paths: set[str] = set()
    focus_index_by_key: dict[str, int] = {}
    for idx, fr in enumerate(review.get("focus_reviews", []) or []):
        if isinstance(fr, dict):
            key = _clean_track_value(fr.get("focus_key", ""))
            if key and key not in focus_index_by_key:
                focus_index_by_key[key] = idx

    def _local_path_for_focus(path: str, item_focus: str = "") -> str:
        raw_path = _clean_track_value(path)
        if not raw_path:
            return ""
        match = re.fullmatch(r"focus_areas\[(\d+)\]\.(.+)", raw_path)
        if not match:
            return raw_path
        try:
            index = int(match.group(1))
        except ValueError:
            return ""
        expected_index = focus_index_by_key.get(focus_norm)
        if expected_index is None:
            return ""
        if item_focus and item_focus != focus_norm:
            return ""
        if index != expected_index:
            return ""
        return match.group(2)

    def _add(
        path: str,
        issue: str,
        instruction: str = "",
        severity: str = "minor",
        issue_scope: str = "field_level",
        action: str = "surgical_repair",
        reason: str = "",
    ) -> None:
        clean_path = _clean_track_value(path)
        if not clean_path:
            return
        if clean_path.lower() in seen_paths:
            return
        key = (clean_path.lower(), _clean_track_value(issue).lower())
        if key in seen:
            return
        seen.add(key)
        seen_paths.add(clean_path.lower())
        targets.append({
            "focus_key": focus_norm,
            "path": clean_path,
            "issue": _clean_track_value(issue),
            "instruction": _clean_track_value(instruction),
            "severity": _clean_track_value(severity) or "minor",
            "issue_scope": _normalize_issue_scope(issue_scope, clean_path),
            "action": _normalize_repair_action(action, issue_scope),
            "reason": _clean_track_value(reason or issue),
        })

    for issue in review.get("typed_issues", []) or []:
        if not isinstance(issue, dict):
            continue
        item_focus = _clean_track_value(issue.get("focus_key", ""))
        if item_focus and item_focus != focus_norm:
            continue
        action = _normalize_repair_action(issue.get("action"), issue.get("issue_scope", ""))
        if action != "surgical_repair":
            continue
        path = _local_path_for_focus(str(issue.get("path", "")), item_focus)
        if not path:
            continue
        reason = str(issue.get("reason", ""))
        _add(
            path,
            reason or "Field requires surgical repair.",
            reason or "Replace only this exact field.",
            str(issue.get("severity", "minor")),
            str(issue.get("issue_scope", "field_level")),
            action,
            reason,
        )

    for item in review.get("repair_targets", []) or []:
        if not isinstance(item, dict):
            continue
        item_focus = _clean_track_value(item.get("focus_key", ""))
        if item_focus and item_focus != focus_norm:
            continue
        path = _local_path_for_focus(str(item.get("path", "")), item_focus)
        if not path:
            continue
        _add(
            path,
            str(item.get("issue", "")),
            str(item.get("instruction", "")),
            str(item.get("severity", "minor")),
            str(item.get("issue_scope", "field_level")),
            str(item.get("action", "surgical_repair")),
            str(item.get("reason", "")),
        )

    explicit_target_count = len(targets)

    if explicit_target_count == 0:
        for fr in review.get("focus_reviews", []) or []:
            if not isinstance(fr, dict):
                continue
            item_focus = _clean_track_value(fr.get("focus_key", ""))
            if item_focus and item_focus != focus_norm:
                continue
            opener_issue = _clean_track_value(fr.get("opener_issue", ""))
            if opener_issue:
                _add("opener", opener_issue, "Replace only the opener with a sharper grounded entry question.", "major")
            for issue in fr.get("issues", []) or []:
                issue_text = _clean_track_value(issue)
                lowered = issue_text.lower()
                if not issue_text:
                    continue
                if "opener" in lowered:
                    _add("opener", issue_text, "Replace only the opener.", "major")
                elif "surface" in lowered:
                    _add("dimensions[*].surface", issue_text, "Replace the specific weak surface probe only.")
                elif "mechanism" in lowered:
                    _add("dimensions[*].mechanism", issue_text, "Replace the specific weak mechanism probe only.")
                elif "boundary" in lowered:
                    _add("dimensions[*].boundary", issue_text, "Replace the specific weak boundary probe only.", "major")
                elif "q4" in lowered or "alternative" in lowered:
                    _add("candidate_q4_options[*]", issue_text, "Replace only the weak Q4 option.")
                elif "recover" in lowered or "honest" in lowered or "gap" in lowered or "metric" in lowered:
                    _add("recovery.metric_risk", issue_text, "Replace only the recovery question closest to this issue.")

    # If the critic only emitted global repair text but names this focus, make it
    # eligible for a local patch instead of forcing full-track regeneration.
    if explicit_target_count == 0:
        for instruction in review.get("repair_instructions", []) or []:
            text = _clean_track_value(instruction)
            lowered = text.lower()
            if not text:
                continue
            if focus_norm.lower() not in lowered and (not label_norm or label_norm not in lowered):
                continue
            if "opener" in lowered:
                _add("opener", text, text, "major")
            elif "surface" in lowered:
                _add("dimensions[*].surface", text, text)
            elif "mechanism" in lowered:
                _add("dimensions[*].mechanism", text, text)
            elif "boundary" in lowered:
                _add("dimensions[*].boundary", text, text, "major")

    return targets[:5]


def _targets_are_surgical(targets: list[dict], *, focus_score: float | None) -> bool:
    if not targets:
        return False
    if focus_score is not None and focus_score < 6.5:
        return False
    major_count = sum(1 for t in targets if str(t.get("severity", "")).lower() == "major")
    if len(targets) > 4 or major_count > 2:
        return False
    broad_paths = {"focus_area", "focus_plan", "track", "dimensions", "recovery"}
    for target in targets:
        path = str(target.get("path", "")).strip().lower()
        scope = _normalize_issue_scope(target.get("issue_scope"), path)
        action = _normalize_repair_action(target.get("action"), scope)
        if scope in {"plan_level", "track_level"} or action in {"plan_repair", "track_repair"}:
            return False
        if path in broad_paths:
            return False
        if not (
            re.fullmatch(r"opener", path)
            or re.fullmatch(r"question_ladder\[(?:\d+|\*)\]\.(main_question|follow_up_if_shallow|follow_up_if_strong|expected_space)", path)
            or re.fullmatch(r"dimensions\[(?:\d+|\*)\]\.(surface|mechanism|boundary)", path)
            or re.fullmatch(r"recovery\.(short_answer|honest_gap|claim_conflict|metric_risk|overclaim_risk|bridge)", path)
            or re.fullmatch(r"candidate_q4_options\[(?:\d+|\*)\]", path)
        ):
            return False
    return True


def _apply_track_update(track: dict, path: str, value: str, seed: dict) -> bool:
    """Apply one question-level update. Returns False for unsupported paths."""
    clean_value = _clean_track_value(value)
    if not clean_value:
        return False
    clean_path = _clean_track_value(path)
    if clean_path == "opener":
        if _question_is_generic_or_off_focus(clean_value, seed):
            return False
        track["opener"] = clean_value
        return True

    ladder_match = re.fullmatch(
        r"question_ladder\[(\d+)\]\.(main_question|follow_up_if_shallow|follow_up_if_strong|expected_space)",
        clean_path,
    )
    if ladder_match:
        ladder = track.get("question_ladder")
        if not isinstance(ladder, list):
            return False
        index = int(ladder_match.group(1))
        field = ladder_match.group(2)
        if index < 0 or index >= len(ladder) or not isinstance(ladder[index], dict):
            return False
        if field == "expected_space":
            parsed = _load_json_lenient(clean_value)
            if isinstance(parsed, list):
                ladder[index][field] = [
                    _clean_track_value(item)
                    for item in parsed
                    if isinstance(item, str) and _clean_track_value(item)
                ][:4]
            else:
                ladder[index][field] = [
                    _clean_track_value(part)
                    for part in re.split(r"[,;]", clean_value)
                    if _clean_track_value(part)
                ][:4]
            return bool(ladder[index][field])
        if _question_is_generic_or_off_focus(clean_value, seed):
            return False
        ladder[index][field] = clean_value
        return True

    recovery_match = re.fullmatch(
        r"recovery\.(short_answer|honest_gap|claim_conflict|metric_risk|overclaim_risk|bridge)",
        clean_path,
    )
    if recovery_match:
        recovery = track.setdefault("recovery", {})
        if not isinstance(recovery, dict):
            return False
        recovery[recovery_match.group(1)] = clean_value
        return True

    dim_match = re.fullmatch(
        r"dimensions\[(\d+)\]\.(surface|mechanism|boundary)",
        clean_path,
    )
    if dim_match:
        dimensions = track.get("dimensions")
        if not isinstance(dimensions, list):
            return False
        index = int(dim_match.group(1))
        field = dim_match.group(2)
        if index < 0 or index >= len(dimensions) or not isinstance(dimensions[index], dict):
            return False
        if _question_is_generic_or_off_focus(clean_value, seed):
            return False
        dimensions[index][field] = clean_value
        return True

    q4_match = re.fullmatch(r"candidate_q4_options\[(\d+)\]", clean_path)
    if q4_match:
        q4_options = track.setdefault("candidate_q4_options", [])
        if not isinstance(q4_options, list):
            return False
        index = int(q4_match.group(1))
        if index < 0:
            return False
        if _question_is_generic_or_off_focus(clean_value, seed):
            return False
        while len(q4_options) <= index:
            q4_options.append("")
        q4_options[index] = clean_value
        return True

    return False


def _get_track_value(track: dict, path: str) -> str:
    clean_path = _clean_track_value(path)
    if clean_path == "opener":
        return _clean_track_value(track.get("opener", ""))
    ladder_match = re.fullmatch(
        r"question_ladder\[(\d+)\]\.(main_question|follow_up_if_shallow|follow_up_if_strong|expected_space)",
        clean_path,
    )
    if ladder_match:
        ladder = track.get("question_ladder")
        index = int(ladder_match.group(1))
        field = ladder_match.group(2)
        if isinstance(ladder, list) and 0 <= index < len(ladder) and isinstance(ladder[index], dict):
            value = ladder[index].get(field, "")
            if isinstance(value, list):
                return json.dumps(value)
            return _clean_track_value(value)
    recovery_match = re.fullmatch(
        r"recovery\.(short_answer|honest_gap|claim_conflict|metric_risk|overclaim_risk|bridge)",
        clean_path,
    )
    if recovery_match:
        recovery = track.get("recovery") if isinstance(track.get("recovery"), dict) else {}
        return _clean_track_value(recovery.get(recovery_match.group(1), ""))
    dim_match = re.fullmatch(r"dimensions\[(\d+)\]\.(surface|mechanism|boundary)", clean_path)
    if dim_match:
        dimensions = track.get("dimensions")
        index = int(dim_match.group(1))
        if isinstance(dimensions, list) and 0 <= index < len(dimensions) and isinstance(dimensions[index], dict):
            return _clean_track_value(dimensions[index].get(dim_match.group(2), ""))
    q4_match = re.fullmatch(r"candidate_q4_options\[(\d+)\]", clean_path)
    if q4_match:
        q4_options = track.get("candidate_q4_options")
        index = int(q4_match.group(1))
        if isinstance(q4_options, list) and 0 <= index < len(q4_options):
            return _clean_track_value(q4_options[index])
    return ""


def _target_for_path(targets: list[dict], path: str) -> dict:
    clean_path = _clean_track_value(path)
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_path = _clean_track_value(target.get("path", ""))
        if target_path == clean_path:
            return target
        if "[*]" in target_path:
            pattern = re.escape(target_path).replace(r"\[\*\]", r"\[\d+\]")
            if re.fullmatch(pattern, clean_path):
                return target
    return {}


def _verify_repaired_fields(seed: dict, track: dict, provenance: list[dict]) -> list[dict]:
    verified: list[dict] = []
    for item in provenance:
        path = str(item.get("path") or "")
        new_value = _get_track_value(track, path)
        if not new_value:
            raise RuntimeError(f"Surgical repair removed or failed to set {path}.")
        if (
            path.startswith("dimensions")
            or path == "opener"
            or path.startswith("candidate_q4_options")
            or (path.startswith("question_ladder") and not path.endswith(".expected_space"))
        ):
            if _question_is_generic_or_off_focus(new_value, seed):
                raise RuntimeError(f"Surgical repair produced generic/off-focus question at {path}.")
        flags = _question_repair_safety_flags(new_value) if (
            path == "opener"
            or path.startswith("dimensions")
            or path.startswith("candidate_q4_options")
            or (path.startswith("question_ladder") and not path.endswith(".expected_space"))
        ) else []
        if (
            path == "opener"
            or path.startswith("dimensions")
            or path.startswith("candidate_q4_options")
            or (path.startswith("question_ladder") and not path.endswith(".expected_space"))
        ):
            flags.extend(_unsupported_hidden_assumption_flags(new_value, seed))
        if flags:
            raise RuntimeError(f"Surgical repair failed safety/readability at {path}: {', '.join(flags)}")
        old_tokens = _content_tokens(str(item.get("old_value") or ""))
        new_tokens = _content_tokens(new_value)
        if old_tokens and new_tokens and _jaccard_score(old_tokens, new_tokens) >= 0.92:
            raise RuntimeError(f"Surgical repair barely changed {path}.")
        verified.append({
            **item,
            "new_value": new_value,
            "accepted_by": "field_verifier",
            "verifier_warnings": [],
        })
    return verified


def _apply_track_updates_with_provenance(
    track: dict,
    updates: list[dict],
    seed: dict,
    *,
    targets: list[dict] | None = None,
    model: str = "",
    latency_ms: int = 0,
) -> tuple[dict, list[dict]]:
    patched = json.loads(json.dumps(track))
    provenance: list[dict] = []
    targets = targets or []
    for update in updates:
        if not isinstance(update, dict):
            continue
        path = str(update.get("path", ""))
        value = str(update.get("value", ""))
        old_value = _get_track_value(patched, path)
        if _apply_track_update(patched, path, value, seed):
            target = _target_for_path(targets, path)
            provenance.append({
                "focus_key": str(seed.get("focus_key") or ""),
                "path": _clean_track_value(path),
                "old_value": old_value,
                "new_value": _get_track_value(patched, path),
                "issue_scope": _normalize_issue_scope(target.get("issue_scope"), path),
                "repair_reason": _clean_track_value(target.get("reason") or target.get("issue") or target.get("instruction") or ""),
                "model": model,
                "latency_ms": latency_ms,
                "accepted_by": "",
            })
    if not provenance:
        raise RuntimeError("Surgical repair returned no applicable question updates.")
    parsed = _parse_dimension_output(patched, seed)
    provenance = _verify_repaired_fields(seed, parsed, provenance)
    return parsed, provenance


def _apply_track_updates(track: dict, updates: list[dict], seed: dict) -> dict:
    patched, _ = _apply_track_updates_with_provenance(track, updates, seed)
    return patched


def _surgical_repair_user_prompt(*, seed: dict, track: dict, targets: list[dict]) -> str:
    return "\n".join([
        "You are repairing a generated interview focus track.",
        "",
        "Rules:",
        "- Replace ONLY the fields listed by the repair targets.",
        "- Do not rewrite the full track.",
        "- Keep every replacement specific to the resume anchor and human-sounding.",
        "- If a target path contains [*], choose the single concrete bad field and return a concrete zero-based path like dimensions[1].boundary.",
        "- question_ladder paths are supported, for example question_ladder[1].main_question or question_ladder[2].follow_up_if_shallow.",
        "- Each value must be one interview question, not commentary.",
        "- Replacements must be complete spoken questions: at least 15 words, one clear question mark, no mid-sentence truncation.",
        "",
        "Focus seed:",
        _json_text({
            "label": seed.get("label", ""),
            "focus_key": seed.get("focus_key", ""),
            "anchor_context": seed.get("anchor_context", ""),
            "resume_snippets": seed.get("resume_snippets", [])[:3],
            "sub_focuses": seed.get("sub_focuses", [])[:6],
        }),
        "",
        "Current track:",
        _json_text(track),
        "",
        "Repair targets:",
        _json_text(targets),
        "",
        "Return ONLY JSON:",
        "{",
        '  "updates": [',
        '    {"path": "opener", "value": "replacement question"}',
        "  ]",
        "}",
    ])


async def _repair_focus_track_surgically(
    *,
    seed: dict,
    existing_track: dict,
    critic_feedback: dict | None,
    session_id: str,
    role_type: str = "",
) -> dict | None:
    focus_key = str(seed.get("focus_key", "") or "")
    targets = _repair_targets_for_focus(
        critic_feedback,
        focus_key,
        str(seed.get("label", "") or ""),
    )
    focus_score = _focus_review_score(critic_feedback, focus_key)
    if not _targets_are_surgical(targets, focus_score=focus_score):
        return None

    prompt = _surgical_repair_user_prompt(seed=seed, track=existing_track, targets=targets)
    system = (
        "You repair individual questions in an interview map. "
        "Return JSON with an updates array only. Do not regenerate unaffected fields."
    )
    attempts = [("primary", _MAP_GENERATOR_MODEL, 24.0)]
    if _MAP_RESCUE_MODEL and _MAP_RESCUE_MODEL != _MAP_GENERATOR_MODEL:
        attempts.append(("rescue", _MAP_RESCUE_MODEL, 36.0))

    last_error: Exception | None = None
    for source, model, timeout in attempts:
        llm = LLMRouter(tier="medium", model_override=model, timeout_override=timeout)
        try:
            repair_started = time.perf_counter()
            raw = await llm.call(
                system=system,
                user=prompt,
                max_tokens=_MAP_SURGICAL_REPAIR_MAX_TOKENS,
                response_format=_MAP_JSON_RESPONSE_FORMAT,
            )
            if not isinstance(raw, dict):
                raise RuntimeError("Surgical repair output was not a JSON object.")
            updates = raw.get("updates")
            if not isinstance(updates, list):
                raise RuntimeError("Surgical repair output omitted updates array.")
            repair_latency_ms = round((time.perf_counter() - repair_started) * 1000)
            patched_track, repair_provenance = _apply_track_updates_with_provenance(
                existing_track,
                updates,
                seed,
                targets=targets,
                model=llm.model,
                latency_ms=repair_latency_ms,
            )
            print(
                f"[TrajectoryMap] Surgical question repair for '{focus_key}'"
                + (f" in {session_id[:8]}" if session_id else "")
                + f" via {source}:{llm.model} ({len(updates)} update candidates)"
            )
            return {
                "track": patched_track,
                "source": "llm",
                "model": llm.model,
                "repair_strategy": "surgical_question_patch",
                "repair_target_count": len(targets),
                "repair_provenance": repair_provenance,
                "accepted_by": "field_verifier",
            }
        except Exception as exc:
            last_error = exc
            continue

    print(
        f"[TrajectoryMap] Surgical question repair failed for '{focus_key}'"
        + (f" in {session_id[:8]}" if session_id else "")
        + f"; falling back to full track regeneration: {type(last_error).__name__}: {last_error}"
    )
    return None


def _dim_context_summary(area_label: str, track: dict | None) -> str:
    """Return a one-line deduplication hint from a completed track-1 dimension result."""
    if not isinstance(track, dict):
        return ""
    dims = _track_dimensions(track)
    if not dims:
        return ""
    dim_labels = ", ".join(
        _clean_track_value(d.get("label") or d.get("id", ""))
        for d in dims[:6]
        if isinstance(d, dict)
    )
    if not dim_labels:
        return ""
    return (
        f"Track already generated for '{area_label}' examines: {dim_labels}. "
        f"Do not duplicate these angles in the dimensions you generate now."
    )


def _check_cross_area_overlap(areas: list[dict], *, session_id: str = "") -> list[str]:
    """
    Comprehensive post-generation overlap check across ALL content in every area.

    Checks: ladder questions, openers, dimension labels, surface/mechanism/boundary probe texts.
    Bridge text is excluded — bridges intentionally reference adjacent area names.
    Returns list of warning strings (and also prints each one).
    """
    # slot_type → Jaccard threshold to flag as overlap
    THRESHOLDS = {"ladder": 0.62, "opener": 0.60, "label": 0.50, "probe": 0.58}

    # Collect (area_label, slot_type, slot_name, tokens) tuples
    slots: list[tuple[str, str, str, frozenset[str]]] = []
    for area in areas:
        area_label = str(area.get("label", "") or "")
        for index, item in enumerate(area.get("question_ladder") or []):
            if not isinstance(item, dict):
                continue
            question = _clean_track_value(item.get("main_question", ""))
            posture = _clean_track_value(item.get("posture", "")) or str(index)
            if question:
                slots.append((area_label, "ladder", f"ladder:{posture}", _content_tokens(question)))
        opener = _track_opener(area)
        if opener:
            slots.append((area_label, "opener", "opener", _content_tokens(opener)))
        for dim in _track_dimensions(area):
            if not isinstance(dim, dict):
                continue
            dim_id = str(dim.get("id", "") or dim.get("label", "") or "dim")
            dim_label_text = str(dim.get("label", "") or "")
            if dim_label_text:
                slots.append((area_label, "label", f"dim:{dim_id}:label", _content_tokens(dim_label_text)))
            for probe_key in ("surface", "mechanism", "boundary"):
                probe_text = str(dim.get(probe_key, "") or "")
                if probe_text:
                    slots.append((area_label, "probe", f"dim:{dim_id}:{probe_key}", _content_tokens(probe_text)))

    warnings_out: list[str] = []
    for i in range(len(slots)):
        area_a, type_a, name_a, toks_a = slots[i]
        for j in range(i + 1, len(slots)):
            area_b, type_b, name_b, toks_b = slots[j]
            if area_a == area_b:
                continue  # intra-area is fine
            if type_a != type_b:
                continue  # compare like-for-like only
            threshold = THRESHOLDS.get(type_a, 0.60)
            score = _jaccard_score(toks_a, toks_b)
            if score >= threshold:
                msg = (
                    f"[TrajectoryMap] Content overlap"
                    + (f" for {session_id[:8]}" if session_id else "")
                    + f": '{name_a}' in '{area_a}' ↔ '{name_b}' in '{area_b}'"
                    + f" (Jaccard={score:.2f})"
                )
                print(msg)
                warnings_out.append(msg)
    return warnings_out


async def _generate_priority_tracks_for_candidate(
    *,
    resume: str,
    candidate: dict,
    session_id: str,
    critic_feedback: dict | None = None,
    original_candidate: dict | None = None,
    target_role: str = "",
) -> dict:
    focus_areas = list(candidate.get("focus_areas", []) or [])
    if not focus_areas:
        return candidate

    def _make_seed(index: int, area: dict) -> dict:
        focus_key = str(area.get("focus_key", "") or f"focus_{index + 1}").strip()
        sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=focus_key)
        resume_snippets = _clean_resume_snippets(
            list(area.get("resume_snippets", []) or [])
            + [
                snippet
                for sub_focus in sub_focuses
                for snippet in (sub_focus.get("source_snippets") or [])
            ]
        )
        return {
            "label": str(area.get("label", "") or f"Focus Area {index + 1}").strip(),
            "focus_key": focus_key,
            "anchor_context": str(area.get("anchor_context", "") or "").strip() or " ".join(resume_snippets[:2])[:500],
            "sub_focuses": sub_focuses,
            "resume_snippets": resume_snippets,
        }

    def _next_label(index: int) -> str:
        return (
            str(focus_areas[(index + 1) % len(focus_areas)].get("label", "") or "").strip()
            if len(focus_areas) > 1
            else "another area from the candidate's background"
        )

    def _apply_result(area: dict, result: dict) -> dict:
        """Merge generation result into area and preserve source provenance alongside track."""
        updated = dict(area)
        updated["track"] = result.get("track")
        updated["_gen_source"] = result.get("source", "llm")
        updated["_gen_model"] = result.get("model", "")
        if result.get("generation_attempt_errors"):
            updated["_generation_attempt_errors"] = list(result.get("generation_attempt_errors") or [])
        if result.get("latency_ms") is not None:
            updated["_track_latency_ms"] = int(result.get("latency_ms") or 0)
        if result.get("generation_strategy"):
            updated["_track_generation_strategy"] = result.get("generation_strategy")
        if result.get("repair_strategy"):
            updated["_repair_strategy"] = result.get("repair_strategy")
        if result.get("repair_target_count"):
            updated["_repair_target_count"] = result.get("repair_target_count")
        if result.get("repair_provenance"):
            updated["_repair_provenance"] = result.get("repair_provenance")
        return updated

    # Surgical repair: when critic_feedback and original_candidate are both present, preserve any
    # area that already scored well (≥8.0) with no significant issues — regenerating it introduces
    # variance and can degrade what was already high-quality. Only regenerate areas the critic
    # actually flagged.
    _preserve_threshold = 8.0

    def _should_preserve(focus_key: str) -> bool:
        if not critic_feedback or not original_candidate:
            return False
        score = _focus_review_score(critic_feedback, focus_key)
        if score is None or score < _preserve_threshold:
            return False
        if _focus_review_has_significant_issues(critic_feedback, focus_key):
            return False
        return _track_from_candidate(original_candidate, focus_key) is not None

    def _has_explicit_repair_for_focus(focus_key: str, label: str = "") -> bool:
        if not critic_feedback:
            return False
        for item in list(critic_feedback.get("typed_issues") or []) + list(critic_feedback.get("repair_targets") or []):
            if not isinstance(item, dict):
                continue
            item_focus = _clean_track_value(item.get("focus_key", ""))
            if item_focus and item_focus != focus_key:
                continue
            path = _clean_track_value(item.get("path", ""))
            scope = _normalize_issue_scope(item.get("issue_scope"), path)
            action = _normalize_repair_action(item.get("action"), scope)
            if path and action == "surgical_repair":
                return True
            if scope in {"plan_level", "track_level"} or action in {"plan_repair", "track_repair"}:
                return True
        return False

    all_indices = list(range(len(focus_areas)))

    async def _gen_track(index: int) -> dict:
        track_started = time.perf_counter()
        area = focus_areas[index]
        seed = _make_seed(index, area)
        fk = seed["focus_key"]
        existing_track = _track_from_candidate(original_candidate, fk)

        if _should_preserve(fk):
            preserved_track = existing_track
            print(
                f"[TrajectoryMap] Preserving high-score area '{area.get('label', fk)}'"
                + (f" for {session_id[:8]}" if session_id else "")
                + f" (score {_focus_review_score(critic_feedback, fk):.1f} ≥ {_preserve_threshold})"
            )
            return _apply_result(area, {
                "track": preserved_track,
                "source": "llm",
                "model": _track_model_from_candidate(original_candidate, fk),
                "latency_ms": round((time.perf_counter() - track_started) * 1000),
                "generation_strategy": "preserved_high_score_track",
            })

        if existing_track and critic_feedback and original_candidate and not _has_explicit_repair_for_focus(fk, seed["label"]):
            print(
                f"[TrajectoryMap] Preserving untouched launch area '{area.get('label', fk)}'"
                + (f" for {session_id[:8]}" if session_id else "")
                + "; no explicit repair target for this focus"
            )
            return _apply_result(area, {
                "track": existing_track,
                "source": "llm",
                "model": _track_model_from_candidate(original_candidate, fk),
                "latency_ms": round((time.perf_counter() - track_started) * 1000),
                "generation_strategy": "preserved_untouched_track",
            })

        if existing_track:
            surgical_result = await _repair_focus_track_surgically(
                seed=seed,
                existing_track=existing_track,
                critic_feedback=critic_feedback,
                session_id=session_id,
                role_type=target_role,
            )
            if surgical_result:
                surgical_result["latency_ms"] = round((time.perf_counter() - track_started) * 1000)
                surgical_result["generation_strategy"] = "surgical_question_patch"
                return _apply_result(area, surgical_result)

        result = await _generate_focus_track(
            resume_context=resume,
            seed=seed,
            next_focus_label=_next_label(index),
            session_id=session_id,
            fast_mode=False,
            repair_guidance=_critic_guidance_for_focus(critic_feedback, fk),
            prior_track_context="",
            role_type=target_role,
        )
        result["latency_ms"] = round((time.perf_counter() - track_started) * 1000)
        result.setdefault("generation_strategy", "full_track_generation")
        return _apply_result(area, result)

    results = await asyncio.gather(*[_gen_track(i) for i in all_indices])
    for i, result in zip(all_indices, results):
        focus_areas[i] = result

    # Post-generation: comprehensive overlap check across ALL content in all generated areas.
    overlap_warnings = _check_cross_area_overlap(focus_areas, session_id=session_id)
    if overlap_warnings:
        print(
            f"[TrajectoryMap] {len(overlap_warnings)} cross-area overlap(s) detected"
            + (f" for {session_id[:8]}" if session_id else "")
            + " — consider regenerating affected areas with tighter deduplication guidance"
        )

    return {
        **candidate,
        "focus_areas": focus_areas,
        "_overlap_warnings": overlap_warnings,
    }


async def generate_interview_map(
    *,
    resume: str,
    session_id: str = "",
    target_role: str = "",
) -> dict:
    """
    Build only the launch-critical interview map before turn 1.

    Startup contract:
    focus/sub-focus plan -> generate two launch tracks -> critique those tracks
    -> start when launch_ready. Remaining tracks hydrate asynchronously.
    """
    started = time.perf_counter()
    latency_steps: list[dict[str, Any]] = []

    def _mark_latency(stage: str, stage_started: float, **extra: Any) -> None:
        item = {
            "stage": stage,
            "elapsed_ms": round((time.perf_counter() - stage_started) * 1000),
        }
        if extra:
            item.update(extra)
        latency_steps.append(item)

    try:
        stage_started = time.perf_counter()
        surface_plan_v2: dict[str, Any] = {}
        try:
            surface_plan_v2 = await generate_surface_plan_v2(
                resume=resume,
                target_role=target_role,
                session_id=session_id,
            )
            _mark_latency(
                "surface_plan_v2",
                stage_started,
                focus_count=len(surface_plan_v2.get("focus_areas") or []),
                model=surface_plan_v2.get("planner_model") or SURFACE_PLANNER_MODEL,
                schema_errors=len(surface_plan_v2.get("schema_errors") or []),
            )
        except Exception as exc:
            surface_plan_v2 = {
                "schema_version": "surface_plan_v2",
                "planner_model": SURFACE_PLANNER_MODEL,
                "focus_areas": [],
                "demoted_or_off_role_surfaces": [],
                "missing_or_risky_checks": [],
                "planning_notes": "",
                "planner_error": f"{type(exc).__name__}: {exc}",
            }
            _mark_latency(
                "surface_plan_v2_failed_nonblocking",
                stage_started,
                model=SURFACE_PLANNER_MODEL,
                error=surface_plan_v2["planner_error"][:220],
            )

        stage_started = time.perf_counter()
        focus_plan = await _generate_focus_area_plan(
            resume=resume,
            session_id=session_id,
            target_role=target_role,
            surface_plan_v2=surface_plan_v2,
        )
        _mark_latency(
            "focus_area_plan",
            stage_started,
            focus_count=len(focus_plan.get("focus_areas") or []),
            model=focus_plan.get("_focus_plan_model", ""),
            source=focus_plan.get("_focus_plan_source", ""),
            surface_plan_alignment_warnings=len(focus_plan.get("_surface_plan_alignment_warnings") or []),
        )
        focus_plan, preserved_deferred_surfaces = _merge_surface_plan_deferred_focuses(
            focus_plan,
            surface_plan_v2,
        )
        if preserved_deferred_surfaces:
            _mark_latency(
                "surface_plan_deferred_preservation",
                time.perf_counter(),
                preserved_count=len(preserved_deferred_surfaces),
                preserved_focus_keys=[
                    item.get("focus_key")
                    for item in preserved_deferred_surfaces
                    if isinstance(item, dict)
                ],
            )

        focus_plan_audit_task = asyncio.create_task(
            _audit_focus_plan_candidate(
                resume=resume,
                candidate=focus_plan,
                stage="launch_plan",
                target_role=target_role,
            )
        )

        launch_plan = _candidate_focus_subset(focus_plan, count=_MAP_LAUNCH_TRACK_COUNT)
        if len(launch_plan.get("focus_areas") or []) < _MAP_LAUNCH_TRACK_COUNT:
            raise RuntimeError("Focus-area plan had fewer than two launch-usable surfaces.")

        stage_started = time.perf_counter()
        pass_one_candidate = await _generate_launch_lite_tracks_for_candidate(
            resume=resume,
            candidate=launch_plan,
            session_id=session_id,
            target_role=target_role,
        )
        _mark_latency(
            "launch_track_generation",
            stage_started,
            focus_count=len(pass_one_candidate.get("focus_areas") or []),
            track_latencies=[
                {
                    "focus_key": area.get("focus_key"),
                    "model": area.get("_gen_model"),
                    "strategy": area.get("_track_generation_strategy") or "launch_track_lite",
                    "elapsed_ms": area.get("_track_latency_ms"),
                    "attempt_errors": area.get("_generation_attempt_errors") or [],
                }
                for area in (pass_one_candidate.get("focus_areas") or [])
                if isinstance(area, dict)
            ],
        )
        ladder_quality_audit_task: asyncio.Task | None = None
        stage_started = time.perf_counter()
        pass_one_review = await _critique_launch_lite_candidate(
            resume=resume,
            candidate=pass_one_candidate,
            stage="launch_lite_tracks",
            target_role=target_role,
        )
        _mark_latency(
            "launch_sonnet_lite_pair_critic",
            stage_started,
            score=_review_score(pass_one_review),
            ready=_review_is_ready(pass_one_review),
            targeted_repairs=_has_targeted_repairs(pass_one_review),
        )
        stage_started = time.perf_counter()
        focus_plan_audit = await _take_audit_if_ready(focus_plan_audit_task)
        _mark_latency(
            "focus_plan_deepseek_audit_wait",
            stage_started,
            returned=bool(focus_plan_audit),
            pending=bool((focus_plan_audit or {}).get("pending")),
            timed_out=False,
            warnings=len((focus_plan_audit or {}).get("warnings") or []),
        )

        final_candidate = pass_one_candidate
        final_review = pass_one_review
        final_audit: dict = {}
        ladder_quality_audit: dict = {}
        quarantined: list[dict] = []
        repaired_candidate: dict | None = None
        repaired_review: dict | None = None

        startup_ready_without_repair = _startup_ready_without_repair(pass_one_review)
        launch_keys_for_repair = _launch_focus_keys(pass_one_candidate)
        blocking_launch_targets = _blocking_launch_repair_targets(pass_one_review, launch_keys_for_repair)
        repair_feedback_review = (
            _review_with_only_launch_blockers(pass_one_review, blocking_launch_targets)
            if blocking_launch_targets
            else pass_one_review
        )
        if startup_ready_without_repair and _has_targeted_repairs(pass_one_review) and not blocking_launch_targets:
            deferred_targets = len(pass_one_review.get("typed_issues") or []) + len(pass_one_review.get("repair_targets") or [])
            final_review = {
                **pass_one_review,
                "startup_repair_deferred": True,
                "startup_repair_deferred_reason": (
                    "critic returned launch-ready priority tracks; local or noncritical map repairs "
                    "were recorded but did not block interview startup"
                ),
            }
            _mark_latency(
                "pass_1_startup_repair_deferred",
                time.perf_counter(),
                reason="ready_review_and_launch_ready_priority_tracks",
                deferred_targets=deferred_targets,
                overall_score=_review_score(pass_one_review),
                top_two_score=pass_one_review.get("top_two_score"),
            )
        elif startup_ready_without_repair and blocking_launch_targets:
            startup_ready_without_repair = False
            _mark_latency(
                "launch_blocking_repair_required",
                time.perf_counter(),
                target_count=len(blocking_launch_targets),
            )

        if not startup_ready_without_repair:
            try:
                repair_started = time.perf_counter()
                launch_keys = _launch_focus_keys(pass_one_candidate)
                failed_launch_keys = _review_launch_failure_keys(repair_feedback_review, launch_keys)
                plan_repaired = False
                repair_base_plan = pass_one_candidate

                if _launch_track_has_plan_issue(repair_feedback_review, launch_keys):
                    print(
                        f"[TrajectoryMap] Launch critic flagged plan-level issue"
                        + (f" for {session_id[:8]}" if session_id else "")
                        + "; replacing failed launch focus from existing plan"
                    )
                    replacement_plan, new_quarantine = _replace_failed_launch_tracks(
                        focus_plan,
                        launch_keys,
                        failed_launch_keys or launch_keys,
                    )
                    quarantined.extend(new_quarantine)
                    if len(replacement_plan.get("focus_areas") or []) < _MAP_LAUNCH_TRACK_COUNT:
                        # Full plan regeneration is allowed only when we cannot assemble two usable
                        # launch surfaces from the existing plan.
                        hint = _extract_plan_repair_hint(repair_feedback_review)
                        stage_started = time.perf_counter()
                        replacement_plan = await _generate_focus_area_plan(
                            resume=resume,
                            session_id=session_id,
                            dedup_hint=hint,
                            target_role=target_role,
                            surface_plan_v2=surface_plan_v2,
                        )
                        replacement_plan = _candidate_focus_subset(replacement_plan, count=_MAP_LAUNCH_TRACK_COUNT)
                        plan_repaired = True
                        _mark_latency(
                            "repair_focus_area_plan",
                            stage_started,
                            focus_count=len(replacement_plan.get("focus_areas") or []),
                            model=replacement_plan.get("_focus_plan_model", ""),
                            source=replacement_plan.get("_focus_plan_source", ""),
                        )
                    repair_base_plan = replacement_plan

                stage_started = time.perf_counter()
                repaired_candidate = await _generate_launch_lite_tracks_for_candidate(
                    resume=resume,
                    candidate=repair_base_plan,
                    session_id=session_id,
                    target_role=target_role,
                )
                _mark_latency(
                    "launch_lite_repair_track_generation",
                    stage_started,
                    focus_count=len(repaired_candidate.get("focus_areas") or []),
                    track_latencies=[
                        {
                            "focus_key": area.get("focus_key"),
                            "model": area.get("_gen_model"),
                            "strategy": area.get("_track_generation_strategy") or area.get("_repair_strategy") or "launch_track_lite",
                            "elapsed_ms": area.get("_track_latency_ms"),
                            "attempt_errors": area.get("_generation_attempt_errors") or [],
                            "repair_strategy": area.get("_repair_strategy"),
                            "repair_targets": area.get("_repair_target_count"),
                        }
                        for area in (repaired_candidate.get("focus_areas") or [])
                        if isinstance(area, dict)
                    ],
                    repair_summary=_repair_summary(repaired_candidate),
                )
                if _can_skip_full_repair_critic(repaired_candidate, plan_repaired=plan_repaired):
                    repaired_review = _field_verified_review(pass_one_review, repaired_candidate)
                    _mark_latency(
                        "launch_repair_sonnet_critic_skipped",
                        time.perf_counter(),
                        reason="1-3 field-level repairs accepted by field_verifier",
                        repair_summary=_repair_summary(repaired_candidate),
                    )
                    _mark_latency(
                        "launch_repair_deepseek_audit_wait_skipped",
                        time.perf_counter(),
                        reason="field verifier accepted surgical repair; advisory audit from pass_1 retained",
                    )
                else:
                    stage_started = time.perf_counter()
                    repaired_review = await _critique_launch_lite_candidate(
                        resume=resume,
                        candidate=repaired_candidate,
                        stage="launch_lite_tracks_repair",
                        target_role=target_role,
                    )
                    _mark_latency(
                        "launch_repair_sonnet_lite_pair_critic",
                        stage_started,
                        score=_review_score(repaired_review),
                        ready=_review_is_ready(repaired_review),
                        startup_ready=_startup_ready_without_repair(repaired_review),
                    )

                _mark_latency("launch_repair_pass_total", repair_started)
                if not _startup_ready_without_repair(repaired_review) and not plan_repaired:
                    repaired_launch_keys = _launch_focus_keys(repaired_candidate or pass_one_candidate)
                    post_repair_failed_keys = _review_launch_failure_keys(repaired_review, repaired_launch_keys)
                    if post_repair_failed_keys and _launch_track_has_plan_issue(repaired_review, repaired_launch_keys):
                        print(
                            f"[TrajectoryMap] Launch track still failed after repair"
                            + (f" for {session_id[:8]}" if session_id else "")
                            + "; replacing failed focus from existing plan"
                        )
                        replacement_plan, new_quarantine = _replace_failed_launch_tracks(
                            focus_plan,
                            repaired_launch_keys,
                            post_repair_failed_keys,
                        )
                        quarantined.extend(new_quarantine)
                        replacement_keys = _launch_focus_keys(replacement_plan)
                        if (
                            len(replacement_plan.get("focus_areas") or []) >= _MAP_LAUNCH_TRACK_COUNT
                            and replacement_keys != repaired_launch_keys
                        ):
                            stage_started = time.perf_counter()
                            repaired_candidate = await _generate_launch_lite_tracks_for_candidate(
                                resume=resume,
                                candidate=replacement_plan,
                                session_id=session_id,
                                target_role=target_role,
                            )
                            _mark_latency(
                                "launch_lite_post_repair_replacement_generation",
                                stage_started,
                                focus_count=len(repaired_candidate.get("focus_areas") or []),
                                replaced_focus_keys=post_repair_failed_keys,
                                replacement_focus_keys=replacement_keys,
                                track_latencies=[
                                    {
                                        "focus_key": area.get("focus_key"),
                                        "model": area.get("_gen_model"),
                                        "strategy": area.get("_track_generation_strategy") or area.get("_repair_strategy") or "launch_track_lite",
                                        "elapsed_ms": area.get("_track_latency_ms"),
                                        "attempt_errors": area.get("_generation_attempt_errors") or [],
                                    }
                                    for area in (repaired_candidate.get("focus_areas") or [])
                                    if isinstance(area, dict)
                                ],
                            )
                            stage_started = time.perf_counter()
                            repaired_review = await _critique_launch_lite_candidate(
                                resume=resume,
                                candidate=repaired_candidate,
                                stage="launch_lite_replacement_after_repair",
                                target_role=target_role,
                            )
                            plan_repaired = True
                            _mark_latency(
                                "launch_lite_post_repair_replacement_critic",
                                stage_started,
                                score=_review_score(repaired_review),
                                ready=_review_is_ready(repaired_review),
                                startup_ready=_startup_ready_without_repair(repaired_review),
                            )
                if _startup_ready_without_repair(repaired_review):
                    final_candidate = repaired_candidate
                    final_review = repaired_review
                else:
                    raise MapPreparationError(
                        "Launch tracks did not reach readiness after bounded repair/replacement.",
                        _map_failure_diagnostics(
                            session_id=session_id,
                            focus_plan=focus_plan,
                            pass_one_candidate=pass_one_candidate,
                            pass_one_review=pass_one_review,
                            repair_feedback_review=repair_feedback_review,
                            repaired_candidate=repaired_candidate,
                            repaired_review=repaired_review,
                            blocking_launch_targets=blocking_launch_targets,
                            latency_steps=latency_steps,
                            cause=RuntimeError("Launch tracks did not reach readiness after bounded repair/replacement."),
                        ),
                    )
            except Exception as exc:
                if not _has_launch_ready_priority_tracks(pass_one_review):
                    if isinstance(exc, MapPreparationError):
                        raise
                    raise MapPreparationError(
                        f"Launch repair pass failed and pass-1 tracks were not launch-ready: "
                        f"{type(exc).__name__}: {exc}",
                        _map_failure_diagnostics(
                            session_id=session_id,
                            focus_plan=focus_plan,
                            pass_one_candidate=pass_one_candidate,
                            pass_one_review=pass_one_review,
                            repair_feedback_review=repair_feedback_review,
                            repaired_candidate=repaired_candidate,
                            repaired_review=repaired_review,
                            blocking_launch_targets=blocking_launch_targets,
                            latency_steps=latency_steps,
                            cause=exc,
                        ),
                    ) from exc
                print(
                    f"[TrajectoryMap] Launch repair pass failed"
                    + (f" for {session_id[:8]}" if session_id else "")
                    + f"; keeping launch-ready pass-1 launch tracks: {type(exc).__name__}: {exc}"
                )
                final_candidate = pass_one_candidate
                final_review = pass_one_review

        stage_started = time.perf_counter()
        if ladder_quality_audit_task is not None:
            ladder_quality_audit = await _take_audit_if_ready(ladder_quality_audit_task)
        else:
            ladder_quality_audit = {}
        _mark_latency(
            "ladder_quality_deepseek_audit_wait_skipped",
            stage_started,
            returned=bool(ladder_quality_audit),
            pending=bool((ladder_quality_audit or {}).get("pending")),
            timed_out=False,
            warnings=len((ladder_quality_audit or {}).get("warnings") or []),
            escalation_recommended=bool((ladder_quality_audit or {}).get("sonnet_escalation_recommended")),
        )

        stage_started = time.perf_counter()
        interview_map = _candidate_to_runtime_map(
            resume=resume,
            candidate=final_candidate,
            pass_one_review=pass_one_review,
            final_review=final_review,
            session_id=session_id,
        )
        _mark_latency("runtime_map_finalization", stage_started)
        interview_map = _attach_launch_metadata(
            interview_map,
            full_plan=focus_plan,
            launch_candidate=final_candidate,
            launch_review=final_review,
            focus_plan_audit=focus_plan_audit,
            quarantined=quarantined,
        )
        if final_audit:
            interview_map["audit_review"] = {
                **final_audit,
                "advisory_only": True,
            }
        if ladder_quality_audit:
            interview_map["ladder_quality_audit_review"] = {
                **ladder_quality_audit,
                "advisory_only": True,
            }
        interview_map["surface_plan_v2"] = surface_plan_v2
        interview_map["surface_plan_alignment_warnings"] = list(
            focus_plan.get("_surface_plan_alignment_warnings") or []
        )
        interview_map["generation_strategy"] = "launch_ready_map_prep_v3_lite_then_async_hydration"
        interview_map["repair_summary"] = _repair_summary(interview_map)
        interview_map["weight_calibration_warnings"] = _weight_calibration_warnings(interview_map)
        interview_map["map_quality_scorecard"] = _map_quality_scorecard(interview_map, target_role=target_role)
        interview_map["map_prep_v3_trace"] = {
            "contract": "SurfacePlanV2 -> focus_plan -> LaunchTrackLite[2] -> compact_launch_critic -> async_hydrate_full_v2",
            "surface_plan": {
                "focus_count": len(surface_plan_v2.get("focus_areas") or []),
                "model": surface_plan_v2.get("planner_model") or SURFACE_PLANNER_MODEL,
                "schema_errors": list(surface_plan_v2.get("schema_errors") or [])[:6],
                "error": surface_plan_v2.get("planner_error", ""),
            },
            "focus_plan": {
                "raw_focus_count": len(focus_plan.get("focus_areas") or []),
                "normalized_focus_count": len(_normalize_map_candidate(focus_plan, resume=resume).get("focus_areas") or []),
                "model": focus_plan.get("_focus_plan_model", ""),
                "source": focus_plan.get("_focus_plan_source", ""),
                "alignment_warnings": list(focus_plan.get("_surface_plan_alignment_warnings") or [])[:8],
                "preserved_deferred_surfaces": list(focus_plan.get("_surface_plan_preserved_deferred") or [])[:6],
            },
            "launch_seeds_selected": [
                {
                    "focus_key": area.get("focus_key"),
                    "label": area.get("label"),
                    "coverage_value": _focus_area_priority_value(area),
                    "sub_focuses": [
                        {
                            "sub_focus_key": sf.get("sub_focus_key"),
                            "label": sf.get("label"),
                            "surface_kind": sf.get("surface_kind"),
                            "coverage_value": sf.get("coverage_value"),
                        }
                        for sf in _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or ""))[:4]
                    ],
                }
                for area in (launch_plan.get("focus_areas") or [])[:_MAP_LAUNCH_TRACK_COUNT]
                if isinstance(area, dict)
            ],
            "launch_track_generation": (final_candidate.get("_map_prep_v3_trace") or pass_one_candidate.get("_map_prep_v3_trace") or {}),
            "pass_one_compact_critic": pass_one_review,
            "final_compact_critic": final_review,
            "map_quarantine": quarantined,
            "async_hydration_queue": [
                str(item.get("focus_key") or "")
                for item in (focus_plan.get("focus_areas") or [])[_MAP_LAUNCH_TRACK_COUNT:]
                if isinstance(item, dict) and str(item.get("focus_key") or "")
            ],
            "surface_plan_preserved_deferred": list(focus_plan.get("_surface_plan_preserved_deferred") or [])[:6],
        }
        interview_map["model_policy"] = {
            "map_generator_model": _MAP_GENERATOR_MODEL,
            "map_rescue_model": _MAP_RESCUE_MODEL,
            "map_critic_model": _MAP_CRITIC_MODEL,
            "map_track_schema_rescue_model": _MAP_TRACK_SCHEMA_RESCUE_MODEL,
            "launch_track_lite_repair_model": _LAUNCH_LITE_REPAIR_MODEL,
            "map_critic_schema_rescue_model": _MAP_CRITIC_SCHEMA_RESCUE_MODEL,
            "map_audit_model": _MAP_AUDIT_MODEL,
            "surface_planner_model": SURFACE_PLANNER_MODEL,
            "surface_plan_v2_enabled": True,
            "surface_plan_allocation_is_advisory": True,
            "sonnet_rescue_independent_of_deepseek": True,
            "deepseek_audit_blocks_sonnet": False,
            "surgical_question_repair_enabled": True,
            "typed_critic_routing_enabled": True,
            "field_verifier_can_skip_second_full_critic": True,
            "ladder_quality_audit_model": _MAP_AUDIT_MODEL,
            "ladder_quality_audit_blocks_launch": False,
            "bounded_launch_ready_startup": True,
            "launch_track_lite_enabled": True,
            "launch_track_lite_critic_enabled": True,
            "launch_track_lite_repair_enabled": True,
            "full_v2_hydration_after_launch": True,
            "launch_track_count": _MAP_LAUNCH_TRACK_COUNT,
            "full_map_startup_critic_enabled": False,
            "async_hydration_enabled": True,
            "interview_map_v2_ladder_authority": True,
            "legacy_fields_are_compatibility_view": True,
        }

        stage_started = time.perf_counter()
        startup_validation = validate_interview_map(
            interview_map,
            require_all_llm=False,
            min_llm_branch_ratio=0.72,
        )
        _mark_latency(
            "startup_validation",
            stage_started,
            priority_llm_ready_count=startup_validation.get("priority_llm_ready_count", 0),
            ready=startup_validation.get("ready"),
            errors=startup_validation.get("errors", [])[:4],
        )
        # Startup only needs the two launch tracks. Deferred focus areas live in
        # deferred_focus_plan and hydrate after turn 1; they must not trigger
        # synchronous full-map repair here.
        if startup_validation.get("priority_llm_ready_count", 0) < _MAP_MIN_FOCUS_AREAS:
            missing_priority_keys = [
                str(area.get("focus_key", "") or "")
                for area in (interview_map.get("focus_areas") or [])
                if str(area.get("track_source", "") or "") != "llm"
            ]
            missing_priority_keys = [key for key in missing_priority_keys if key]
            if missing_priority_keys:
                print(
                    f"[TrajectoryMap] Fewer than {_MAP_MIN_FOCUS_AREAS} LLM-ready tracks; repairing"
                    + (f" for {session_id[:8]}" if session_id else "")
                    + f": {', '.join(missing_priority_keys)}"
                )
                stage_started = time.perf_counter()
                interview_map = await hydrate_interview_map_tracks(
                    interview_map=interview_map,
                    resume=resume,
                    session_id=session_id,
                    focus_keys=missing_priority_keys,
                )
                _mark_latency(
                    "startup_priority_hydration",
                    stage_started,
                    focus_keys=missing_priority_keys,
                )
                startup_validation = validate_interview_map(
                    interview_map,
                    require_all_llm=False,
                    min_llm_branch_ratio=0.72,
                )

        if not startup_validation.get("ready"):
            interview_map["map_prep_v3_trace"]["final_launch_readiness_reason"] = {
                "ready": False,
                "errors": startup_validation.get("errors", []),
                "warnings": startup_validation.get("warnings", []),
            }
            raise MapPreparationError(
                "LaunchTrackLite map failed startup validation.",
                {
                    "session_id": session_id,
                    "map_prep_v3_trace": interview_map.get("map_prep_v3_trace", {}),
                    "startup_validation": startup_validation,
                    "latency_steps": latency_steps,
                },
            )

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        interview_map["launch_ready"] = bool(startup_validation.get("ready")) and int(startup_validation.get("priority_llm_ready_count", 0) or 0) >= _MAP_LAUNCH_TRACK_COUNT
        interview_map["full_map_ready"] = not bool(interview_map.get("pending_hydration_focus_keys"))
        interview_map["needs_async_hydration"] = bool(interview_map.get("pending_hydration_focus_keys"))
        interview_map["map_prep_v3_trace"]["final_launch_readiness_reason"] = {
            "ready": interview_map["launch_ready"],
            "priority_llm_ready_count": startup_validation.get("priority_llm_ready_count", 0),
            "pending_hydration_focus_keys": interview_map.get("pending_hydration_focus_keys", []),
        }
        interview_map["latency_breakdown"] = {
            "total_ms": elapsed_ms,
            "steps": latency_steps,
        }
        print(
            f"[TrajectoryMap] Built launch-ready map with {len(interview_map.get('focus_areas', []))} launch focus areas in {elapsed_ms}ms"
            + (f" for {session_id[:8]}" if session_id else "")
        )
        return interview_map
    except Exception as exc:
        print(
            f"[TrajectoryMap] Startup map generation failed"
            + (f" for {session_id[:8]}" if session_id else "")
            + f": {type(exc).__name__}: {exc}"
        )
        raise


def build_deterministic_interview_map(
    *,
    resume: str,
    session_id: str = "",
    role_type: str = "",
) -> dict:
    raise RuntimeError("Deterministic interview-map fallback is disabled; LLM map generation must succeed.")


def audit_map_quality(interview_map: dict) -> list[str]:
    """
    Lightweight quality check. Returns warning strings — does not block session start.
    Called after map preparation; warnings are logged but non-fatal.
    """
    warnings: list[str] = []
    focus_areas = interview_map.get("focus_areas", []) if isinstance(interview_map, dict) else []
    if not focus_areas:
        warnings.append("No focus areas generated")
        return warnings

    primary = focus_areas[0]
    opener = _track_opener(primary)
    if primary.get("tracks") and isinstance(primary["tracks"], list) and primary["tracks"]:
        opener = _track_opener(primary["tracks"][0]) or opener
    if opener and len(opener.split()) > 30:
        warnings.append(f"Primary opener is too long ({len(opener.split())} words)")

    for fa in focus_areas:
        dims = _track_dimensions(fa)
        for track in fa.get("tracks", []) or []:
            dims = dims + _track_dimensions(track)
        for dim in dims:
            if not isinstance(dim, dict):
                continue
            if "signal_weight" not in dim:
                warnings.append(f"Dimension '{dim.get('id', '?')}' in '{fa.get('label', '?')}' missing signal_weight")
                break

    return warnings


def validate_interview_map(
    interview_map: dict,
    *,
    require_all_llm: bool = False,
    min_focus_areas: int = _MAP_MIN_FOCUS_AREAS,
    min_llm_branch_ratio: float = 0.72,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    focus_areas = interview_map.get("focus_areas", []) if isinstance(interview_map, dict) else []
    if not isinstance(focus_areas, list):
        focus_areas = []
    pending_focuses = list(interview_map.get("pending_hydration_focus_keys", []) or []) if isinstance(interview_map, dict) else []

    if len(focus_areas) < min_focus_areas:
        errors.append(f"Map has only {len(focus_areas)} focus areas; need at least {min_focus_areas}.")

    quality_review = interview_map.get("quality_review", {}) if isinstance(interview_map, dict) else {}
    if isinstance(quality_review, dict):
        review_ready = quality_review.get("ready")
        review_score = _review_score(quality_review)
        if review_ready is False:
            warnings.append("Map critic suggested further improvements before launch.")
        elif review_score and review_score < _MAP_MIN_READY_SCORE:
            warnings.append(
                f"Map critic score is {review_score:.1f}; need at least {_MAP_MIN_READY_SCORE:.1f}."
            )

    llm_focus_count = 0
    rich_focus_count = 0
    priority_llm_ready_count = 0
    focus_reports: list[dict] = []
    for index, area in enumerate(focus_areas):
        label = str(area.get("label", "") or "").strip()
        focus_key = str(area.get("focus_key", "") or "").strip()
        track_source = str(area.get("track_source", "") or "")
        schema_version = str(area.get("track_schema", "") or "")
        llm_branch_count = int(area.get("llm_branch_count", 0) or 0)
        fallback_branch_count = int(area.get("fallback_branch_count", 0) or 0)
        llm_branches = set(str(item) for item in (area.get("llm_branches", []) or []))
        is_launch_lite = schema_version == "v3_launch_lite" or bool(area.get("launch_track_lite"))
        is_dim_schema = schema_version in {"dimension", "v2_ladder", "v3_launch_lite"} or bool(area.get("question_ladder")) or ("opener" in area or "dimensions" in area)
        focus_errors: list[str] = []

        if not label or not focus_key:
            focus_errors.append("missing label or focus key")
        if any(token in label.lower() for token in _RICH_MAP_BANNED_LABEL_TOKENS):
            focus_errors.append(f"label '{label}' looks like metadata noise")

        if is_dim_schema:
            # Validate ladder schema. Full V2 tracks require the full six-posture
            # ladder; V3 launch-lite tracks require only the startup arc.
            opener = _track_opener(area)
            dims = _track_dimensions(area)
            recovery = _track_recovery(area)
            ladder = area.get("question_ladder", []) if isinstance(area.get("question_ladder"), list) else []
            if not opener:
                focus_errors.append(f"{label}: opener missing")
            ladder_postures = {
                str(item.get("posture") or "").strip().lower()
                for item in ladder
                if isinstance(item, dict) and _clean_track_value(item.get("main_question", ""))
            }
            required_postures = {"frame", "clarify", "explore", "pressure", "recover"} if is_launch_lite else set(_QUESTION_LADDER_POSTURES)
            missing_postures = sorted(required_postures - ladder_postures)
            if missing_postures:
                focus_errors.append(f"{label}: question_ladder missing postures: {', '.join(missing_postures)}")
            high_info_count = sum(
                1 for item in ladder
                if isinstance(item, dict) and str(item.get("information_gain") or "").lower() == "high"
            )
            if ladder and high_info_count < 3:
                focus_errors.append(f"{label}: question_ladder has only {high_info_count} high-information items")
            ladder_ready = not missing_postures and high_info_count >= 3
            if len(dims) < 2:
                focus_errors.append(f"{label}: only {len(dims)} dimensions (need ≥2)")
            elif not is_launch_lite and len(dims) < 3 and not ladder_ready:
                focus_errors.append(f"{label}: only {len(dims)} dimensions and ladder is not complete/high-information")
            for dim in dims[:6]:
                if not isinstance(dim, dict):
                    continue
                for probe_key in ("surface", "mechanism", "boundary"):
                    if not _clean_track_value(dim.get(probe_key, "")):
                        focus_errors.append(f"{label}/{dim.get('id', '?')}: {probe_key} probe empty")

            total_branches = llm_branch_count + fallback_branch_count
            if total_branches == 0:
                total_branches = len(dims) or 1
            llm_ratio = llm_branch_count / total_branches if total_branches else 0.0
            # is_rich requires LLM provenance — a complete fallback track must not count as ready.
            is_rich = track_source == "llm" and opener and len(dims) >= 2 and ladder_ready
        else:
            # Legacy sprint/branch schema
            if track_source == "deterministic_fallback" and llm_branch_count == 0 and fallback_branch_count == 0:
                fallback_branch_count = len(_SPRINT_KEYS) * len(_VALID_BRANCHES)
            total_branches = llm_branch_count + fallback_branch_count
            llm_ratio = llm_branch_count / total_branches if total_branches else 0.0
            for sprint_key in _SPRINT_KEYS:
                sprint = area.get(sprint_key, {})
                if not isinstance(sprint, dict):
                    focus_errors.append(f"{label}: {sprint_key} missing")
                    continue
                for branch in _VALID_BRANCHES:
                    if not _clean_track_value(sprint.get(branch, "")):
                        focus_errors.append(f"{label}: {sprint_key}.{branch} empty")
            is_rich = llm_ratio >= min_llm_branch_ratio and _RICH_MAP_CORE_BRANCHES <= llm_branches

        if track_source == "llm":
            llm_focus_count += 1
        if is_rich:
            rich_focus_count += 1
            priority_llm_ready_count += 1  # all areas are generated in phase 2, so all are "priority"

        if require_all_llm:
            if track_source != "llm":
                focus_errors.append(f"{label}: track_source is {track_source}, expected llm")
            if not is_rich:
                focus_errors.append(f"{label}: does not meet richness gate")

        if focus_errors:
            errors.extend(focus_errors)

        focus_reports.append({
            "label": label,
            "focus_key": focus_key,
            "track_source": track_source,
            "track_schema": schema_version or ("dimension" if is_dim_schema else "sprint"),
            "llm_branch_count": llm_branch_count,
            "fallback_branch_count": fallback_branch_count,
            "llm_branch_ratio": round(llm_ratio, 3),
            "pending": focus_key in pending_focuses,
            "ready": not focus_errors,
            "is_rich": is_rich,
        })

    if require_all_llm and pending_focuses:
        errors.append(f"Map still has pending hydration focuses: {', '.join(pending_focuses)}")
    # Startup contract: need ≥ _MAP_MIN_FOCUS_AREAS LLM-ready areas to launch.
    # Remaining areas can be hydrated by the orchestrator after startup.
    if not require_all_llm and priority_llm_ready_count < _MAP_MIN_FOCUS_AREAS:
        errors.append(
            f"Only {priority_llm_ready_count}/{len(focus_areas)} focus areas are LLM-ready"
            f" (need ≥{_MAP_MIN_FOCUS_AREAS} to launch)."
        )
    if not require_all_llm and llm_focus_count < len(focus_areas):
        warnings.append(f"Only {llm_focus_count}/{len(focus_areas)} focus areas are fully LLM-sourced; remaining will be hydrated.")

    return {
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "focus_count": len(focus_areas),
        "llm_focus_count": llm_focus_count,
        "rich_focus_count": rich_focus_count,
        "priority_llm_ready_count": priority_llm_ready_count,
        "pending_focus_keys": pending_focuses,
        "focus_reports": focus_reports,
        "require_all_llm": require_all_llm,
        "min_llm_branch_ratio": min_llm_branch_ratio,
    }


async def hydrate_interview_map_tracks(
    *,
    interview_map: dict,
    resume: str,
    session_id: str = "",
    focus_keys: list[str] | None = None,
) -> dict:
    if not isinstance(interview_map, dict):
        return interview_map

    focus_areas = interview_map.get("focus_areas", [])
    if not isinstance(focus_areas, list) or not focus_areas:
        return interview_map

    focus_areas = [dict(area) for area in focus_areas if isinstance(area, dict)]
    deferred_plan = [
        dict(area)
        for area in (interview_map.get("deferred_focus_plan") or [])
        if isinstance(area, dict)
    ]
    existing_keys = {
        str(area.get("focus_key", "") or "")
        for area in focus_areas
        if str(area.get("focus_key", "") or "")
    }
    resume_focus = _resume_focus_source(resume) or resume
    target_keys = set(focus_keys or interview_map.get("pending_hydration_focus_keys", []) or [])
    if not target_keys:
        target_keys = {
            str(area.get("focus_key", "") or "")
            for area in focus_areas
            if str(area.get("track_source", "") or "") != "llm"
        }
    quarantined_keys = {
        str(item.get("focus_key") or "")
        for item in (interview_map.get("map_quarantine") or [])
        if isinstance(item, dict)
    }
    target_keys = {key for key in target_keys if key and key not in quarantined_keys}

    for area in deferred_plan:
        key = str(area.get("focus_key", "") or "")
        if key and key in target_keys and key not in existing_keys:
            focus_areas.append({
                **area,
                "track_source": "pending_async_hydration",
                "track_schema": "",
                "llm_branch_count": 0,
                "fallback_branch_count": 0,
                "llm_branches": [],
                "fallback_branches": [],
                "pending_hydration": True,
            })
            existing_keys.add(key)

    # Build list of (index, area) pairs that need hydration
    pending_pairs = [
        (index, area)
        for index, area in enumerate(focus_areas)
        if str(area.get("focus_key", "") or "") in target_keys
    ]

    async def _hydrate_one(index: int, area: dict) -> tuple[int, dict]:
        focus_key = str(area.get("focus_key", "") or "")
        next_focus_label = (
            str(focus_areas[(index + 1) % len(focus_areas)].get("label", "") or "").strip()
            if len(focus_areas) > 1
            else "another area from the candidate's background"
        )
        seed = {
            "label": str(area.get("label", "") or ""),
            "focus_key": focus_key,
            "anchor_context": str(area.get("anchor_context", "") or ""),
            "sub_focuses": _normalize_sub_focuses(area.get("sub_focuses"), focus_key=focus_key),
            "resume_snippets": _clean_resume_snippets(
                list(area.get("resume_snippets", []) or [])
                + _sub_focus_source_snippets(area)
            ),
        }
        if not seed["anchor_context"]:
            seed["anchor_context"] = " ".join(seed["resume_snippets"][:2])[:500]
        result = await _generate_focus_track(
            resume_context=resume_focus,
            seed=seed,
            next_focus_label=next_focus_label,
            session_id=session_id,
            fast_mode=False,
        )
        if result.get("source") == "llm":
            track_data = result["track"]
            schema_v = "v2_ladder" if "question_ladder" in track_data else "sprint"
            updated = {
                **area,
                "map_schema_version": "v2_ladder" if schema_v == "v2_ladder" else "legacy_sprint",
                "primary_question_contract": "question_ladder" if schema_v == "v2_ladder" else "legacy_sprint_branches",
                "legacy_fields_authority": "compatibility_only" if schema_v == "v2_ladder" else "authoritative_legacy",
                "track_source": "llm",
                "track_schema": schema_v,
                "llm_branch_count": int(result.get("llm_branch_count", 0) or 0),
                "fallback_branch_count": int(result.get("fallback_branch_count", 0) or 0),
                "llm_branches": list(result.get("llm_branches", []) or []),
                "fallback_branches": list(result.get("fallback_branches", []) or []),
                "pending_hydration": False,
                **track_data,
            }
            try:
                single_candidate = {"focus_areas": [updated]}
                review = await _critique_map_candidate(
                    resume=resume,
                    candidate=single_candidate,
                    stage="async_hydration_track",
                    timeout_override=60.0,
                )
                review = _merge_cheap_review(review, _cheap_structural_review(single_candidate))
                focus_score = 0.0
                focus_issue = ""
                for item in review.get("focus_reviews") or []:
                    if isinstance(item, dict) and str(item.get("focus_key") or "") == focus_key:
                        focus_score = _safe_float(item.get("score", 0), 0.0)
                        focus_issue = str(item.get("opener_issue") or "")
                        break
                accepted, acceptance_reason = _async_hydration_acceptance(
                    updated_area=updated,
                    review=review,
                    focus_key=focus_key,
                    focus_score=focus_score,
                    focus_issue=focus_issue,
                )
                if not accepted:
                    return index, {
                        **area,
                        "track_source": "quarantined",
                        "pending_hydration": False,
                        "map_quarantine_reason": acceptance_reason or "; ".join((review.get("issues") or [])[:2]) or "async hydration critic did not accept track",
                        "_hydration_review": review,
                    }
                updated["_hydration_review"] = review
                updated["async_hydration_acceptance"] = acceptance_reason
            except Exception as exc:
                return index, {
                    **area,
                    "track_source": "quarantined",
                    "pending_hydration": False,
                    "map_quarantine_reason": f"async hydration critic failed: {type(exc).__name__}: {str(exc)[:180]}",
                }
            return index, updated
        return index, area  # source was fallback — keep original

    # Fire all pending hydrations in parallel
    hydration_results = await asyncio.gather(
        *[_hydrate_one(i, a) for i, a in pending_pairs],
        return_exceptions=True,
    )

    updated_focus_areas = list(focus_areas)
    hydrated_keys: list[str] = []
    quarantine = [
        item for item in (interview_map.get("map_quarantine") or [])
        if isinstance(item, dict)
    ]
    for outcome in hydration_results:
        if isinstance(outcome, BaseException):
            print(f"[TrajectoryMap] Hydration task raised: {type(outcome).__name__}: {outcome}")
            continue
        index, updated_area = outcome
        updated_focus_areas[index] = updated_area
        if updated_area.get("track_source") == "llm":
            hydrated_keys.append(str(updated_area.get("focus_key", "") or ""))
        elif updated_area.get("track_source") == "quarantined":
            quarantine.append({
                "focus_key": str(updated_area.get("focus_key", "") or ""),
                "label": str(updated_area.get("label", "") or ""),
                "reason": str(updated_area.get("map_quarantine_reason", "") or "async hydration rejected track"),
                "source": "async_hydration",
            })

    quarantine_keys = {
        str(item.get("focus_key") or "")
        for item in quarantine
        if isinstance(item, dict)
    }
    updated_focus_areas = [
        area for area in updated_focus_areas
        if str(area.get("track_source", "") or "") != "quarantined"
    ]

    remaining = [
        key
        for key in list(interview_map.get("pending_hydration_focus_keys", []) or [])
        if key not in set(hydrated_keys) and key not in quarantine_keys
    ]
    deferred_remaining = [
        area for area in deferred_plan
        if str(area.get("focus_key", "") or "") in set(remaining)
    ]
    return {
        **interview_map,
        "focus_areas": updated_focus_areas,
        "pending_hydration_focus_keys": remaining,
        "deferred_focus_plan": deferred_remaining,
        "map_quarantine": quarantine,
        "full_map_ready": not remaining,
        "needs_async_hydration": bool(remaining),
        "last_hydrated_at": time.time() if hydrated_keys else interview_map.get("last_hydrated_at"),
    }


def get_focus_area_context(
    interview_map: dict,
    *,
    focus_key: str,
    query_text: str = "",
    history: list[dict] | None = None,
    limit: int = 3,
) -> dict | None:
    if not isinstance(interview_map, dict):
        return None
    focus_areas = interview_map.get("focus_areas", [])
    if not isinstance(focus_areas, list) or not focus_areas:
        return None

    history = history or []
    current_matches = [area for area in focus_areas if _focus_area_matches(area, focus_key)]
    if current_matches:
        area = current_matches[0]
    else:
        last_focus_key = _last_substantive_focus(history)
        last_matches = [area for area in focus_areas if _focus_area_matches(area, last_focus_key)]
        if last_matches:
            area = last_matches[0]
        else:
            query_tokens = _tokenize(query_text)
            if not query_tokens:
                return None
            scored: list[tuple[int, dict]] = []
            for candidate in focus_areas:
                candidate_tokens = _tokenize(
                    " ".join(
                        [
                            str(candidate.get("label", "") or ""),
                            str(candidate.get("anchor_context", "") or ""),
                            " ".join(candidate.get("resume_snippets", []) or []),
                        ]
                    )
                )
                score = len(query_tokens & candidate_tokens)
                if score:
                    scored.append((score, candidate))
            scored.sort(key=lambda item: item[0], reverse=True)
            if not scored:
                return None
            area = scored[0][1]

    snippets = [str(snippet).strip() for snippet in area.get("resume_snippets", []) if str(snippet).strip()][:limit]
    label = str(area.get("label", "") or "")
    anchor_context = str(area.get("anchor_context", "") or "")
    prompt_context_lines = []
    if label:
        prompt_context_lines.append(f"Focus area: {label}")
    if anchor_context:
        prompt_context_lines.append(f"Resume anchor: {anchor_context}")
    if snippets:
        prompt_context_lines.append("Exact resume snippets:")
        prompt_context_lines.extend(f"- {snippet}" for snippet in snippets)

    return {
        "focus_key": str(area.get("focus_key", "") or ""),
        "focus_label": label,
        "anchor_context": anchor_context,
        "resume_snippets": snippets,
        "prompt_context": "\n".join(prompt_context_lines),
    }


_METRIC_NUMBER_RE = re.compile(
    r"\b\d+\s*%"                                                      # 40%
    r"|\b\d+\s*percent\b"                                              # 40 percent
    r"|\b\d+x\b"                                                       # 3x
    r"|\b\d+\s*times\b"                                                # 3 times
    r"|\b\d+\s*(?:ms|milliseconds?|seconds?|minutes?|hours?|days?)\b" # 200ms
    r"|\b(?:reduced?|improved?|increased?|decreased?)\s+(?:by\s+)?\d+"# reduced by 35
    r"|\b\d+\s*fold\b",                                                # 3 fold
    re.IGNORECASE,
)
_METHODOLOGY_KEYWORDS = frozenset({
    # Verbs/procedures that indicate HOW they measured — naming a baseline alone is not methodology
    "measured", "compared", "benchmarked", "evaluated", "tracked",
    "logged", "profiled", "instrumented", "a/b", "experiment", "dataset",
    "formula", "calculated", "computation", "ablation",
})


def _has_metric_risk(answer: str) -> bool:
    """True when the answer cites a number but gives no methodology to back it up."""
    if not _METRIC_NUMBER_RE.search(answer):
        return False
    answer_lower = answer.lower()
    return not any(kw in answer_lower for kw in _METHODOLOGY_KEYWORDS)


def _has_overclaim_risk(answer: str) -> bool:
    """True when the answer uses domain vocabulary from _OVERCLAIM_VOCAB with no operational context."""
    answer_lower = answer.lower()
    tokens = set(re.findall(r"[a-z0-9]+", answer_lower)) | set(re.findall(r"[a-z0-9-]+", answer_lower))
    found = _OVERCLAIM_VOCAB & tokens
    if not found:
        return False
    # Only flag when the term is used without any concrete operational grounding —
    # look for phrases that indicate real work: "I built", "we called", "the pipeline", etc.
    grounding_phrases = ("built", "called", "implemented", "wrote", "pipeline", "function", "class", "module", "api")
    return not any(phrase in answer_lower for phrase in grounding_phrases)


def _branch_priority(
    *,
    is_short: bool,
    admission: bool,
    has_discrepancy: bool,
    branch_hint: str = "",
) -> list[str]:
    if branch_hint and branch_hint in _VALID_BRANCHES:
        remainder = [b for b in _BRANCH_PRIORITY_DEFAULT if b != branch_hint]
        return [branch_hint] + remainder
    if has_discrepancy:
        return _BRANCH_PRIORITY_DISCREPANCY
    if admission:
        return _BRANCH_PRIORITY_ADMISSION
    if is_short:
        return _BRANCH_PRIORITY_SHORT
    return _BRANCH_PRIORITY_DEFAULT


def _already_asked(question: str, history: list[dict], window: int = 15) -> bool:
    if not question:
        return False
    normalized = re.sub(r"[^a-z0-9\s]", " ", question.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for turn in history[-window:]:
        asked = re.sub(r"[^a-z0-9\s]", " ", str(turn.get("question", "") or "").lower())
        asked = re.sub(r"\s+", " ", asked).strip()
        if asked and asked == normalized:
            return True
    return False


def _focus_area_matches(area: dict, focus_key: str) -> bool:
    map_key = _normalize_key(str(area.get("focus_key", "") or ""))
    target = _normalize_key(focus_key)
    if not map_key or not target:
        return False
    if map_key == target or map_key in target or target in map_key:
        return True

    ignored = {"ai", "engineering", "engineer", "intern", "internship", "at"}
    map_tokens = {token for token in map_key.split("_") if token and token not in ignored}
    target_tokens = {token for token in target.split("_") if token and token not in ignored}
    overlap = map_tokens & target_tokens
    if len(overlap) >= 2:
        return True
    if map_tokens and target_tokens:
        return len(overlap) / min(len(map_tokens), len(target_tokens)) >= 0.6
    return False


def _last_substantive_focus(history: list[dict]) -> str:
    for turn in reversed(history):
        answer = str(turn.get("answer", "") or "").strip()
        if len(answer.split()) < 8:
            continue
        focus_key = str(turn.get("focus_key", "") or "").strip()
        if focus_key:
            return focus_key
    return ""


def select_from_trajectory_map(
    interview_map: dict,
    *,
    sprint: int,
    focus_key: str,
    answer: str,
    entities: list[str],
    history: list[dict],
    admission: bool = False,
    has_discrepancy: bool = False,
    branch_hint: str = "",
) -> tuple[str, str] | None:
    result = select_from_trajectory_map_detailed(
        interview_map,
        sprint=sprint,
        focus_key=focus_key,
        answer=answer,
        entities=entities,
        history=history,
        admission=admission,
        has_discrepancy=has_discrepancy,
        branch_hint=branch_hint,
    )
    if not result:
        return None
    return result["question"], result["route_kind"]


def _focus_history_count(history: list[dict], focus_key: str) -> int:
    if not focus_key:
        return 0
    return sum(
        1
        for item in history
        if isinstance(item, dict) and str(item.get("focus_key") or "") == focus_key
    )


def _asked_ladder_postures(history: list[dict], focus_key: str) -> set[str]:
    postures: set[str] = set()
    for item in history:
        if not isinstance(item, dict):
            continue
        if focus_key and str(item.get("focus_key") or "") != focus_key:
            continue
        posture = str(item.get("question_posture") or "").strip().lower()
        if posture:
            postures.add(posture)
    return postures


def _ladder_posture_order(*, depth: int, focus_turns: int, branch_hint: str, is_short: bool, admission: bool) -> list[str]:
    if branch_hint in {"if_short_answer", "if_honest_gap"} or is_short or admission:
        return ["recover", "clarify", "frame", "explore"]
    if focus_turns <= 0:
        return ["frame", "clarify", "explore", "pressure"]
    if focus_turns == 1:
        return ["clarify", "explore", "frame", "pressure"]
    if depth <= 1:
        return ["explore", "clarify", "pressure", "synthesize"]
    if depth == 2:
        return ["explore", "pressure", "clarify", "synthesize"]
    return ["pressure", "synthesize", "explore", "clarify"]


def _ladder_same_thread_followups_allowed(area: dict) -> bool:
    """Reserve same-question follow-ups for surfaces worth spending extra interview time on."""
    if not isinstance(area, dict):
        return False
    priority = _focus_area_priority_value(area)
    if priority >= 2.4:
        return True
    high_value_ladder_items = [
        item
        for item in area.get("question_ladder") or []
        if isinstance(item, dict) and str(item.get("information_gain") or "").lower() == "high"
    ]
    return priority >= 2.1 and len(high_value_ladder_items) >= 3


def _preferred_sub_focus_for_area(
    area: dict,
    *,
    preferred_sub_focus_key: str = "",
    preferred_surface_kind: str = "",
) -> dict[str, str]:
    focus_key = str(area.get("focus_key") or "").strip()
    preferred_sub_focus_key = str(preferred_sub_focus_key or "").strip()
    preferred_surface_kind = _normalize_surface_kind(preferred_surface_kind)
    sub_focuses = _normalize_sub_focuses(area.get("sub_focuses"), focus_key=focus_key)
    if not sub_focuses:
        return {
            "sub_focus_key": "",
            "sub_focus_label": "",
            "surface_kind": _primary_surface_kind(area),
        }

    if preferred_sub_focus_key:
        for item in sub_focuses:
            if str(item.get("sub_focus_key") or "").strip() == preferred_sub_focus_key:
                return {
                    "sub_focus_key": str(item.get("sub_focus_key") or "").strip(),
                    "sub_focus_label": str(item.get("label") or item.get("sub_focus_key") or "").strip(),
                    "surface_kind": _normalize_surface_kind(item.get("surface_kind")),
                }

    if preferred_surface_kind:
        ranked = sorted(
            [
                item for item in sub_focuses
                if _normalize_surface_kind(item.get("surface_kind")) == preferred_surface_kind
            ],
            key=lambda item: float(item.get("coverage_value") or 1.5),
            reverse=True,
        )
        if ranked:
            item = ranked[0]
            return {
                "sub_focus_key": str(item.get("sub_focus_key") or "").strip(),
                "sub_focus_label": str(item.get("label") or item.get("sub_focus_key") or "").strip(),
                "surface_kind": _normalize_surface_kind(item.get("surface_kind")),
            }

    ranked = sorted(
        sub_focuses,
        key=lambda item: float(item.get("coverage_value") or 1.5),
        reverse=True,
    )
    item = ranked[0]
    return {
        "sub_focus_key": str(item.get("sub_focus_key") or "").strip(),
        "sub_focus_label": str(item.get("label") or item.get("sub_focus_key") or "").strip(),
        "surface_kind": _normalize_surface_kind(item.get("surface_kind")),
    }


def _area_surface_preference_score(
    area: dict,
    *,
    preferred_sub_focus_key: str = "",
    preferred_surface_kind: str = "",
) -> int:
    preferred_sub_focus_key = str(preferred_sub_focus_key or "").strip()
    preferred_surface_kind = _normalize_surface_kind(preferred_surface_kind)
    if not preferred_sub_focus_key and not preferred_surface_kind:
        return 0
    score = 0
    if preferred_surface_kind and _primary_surface_kind(area) == preferred_surface_kind:
        score += 4
    for item in _normalize_sub_focuses(area.get("sub_focuses"), focus_key=str(area.get("focus_key") or "")):
        if preferred_sub_focus_key and str(item.get("sub_focus_key") or "").strip() == preferred_sub_focus_key:
            score += 8
        if preferred_surface_kind and _normalize_surface_kind(item.get("surface_kind")) == preferred_surface_kind:
            score += 4
    return score


def _sort_by_surface_preference(
    areas: list[dict],
    *,
    preferred_sub_focus_key: str = "",
    preferred_surface_kind: str = "",
) -> list[dict]:
    if not preferred_sub_focus_key and not preferred_surface_kind:
        return areas
    return sorted(
        areas,
        key=lambda area: -_area_surface_preference_score(
            area,
            preferred_sub_focus_key=preferred_sub_focus_key,
            preferred_surface_kind=preferred_surface_kind,
        ),
    )


def _select_from_question_ladder(
    area: dict,
    *,
    history: list[dict],
    depth: int,
    is_short: bool,
    admission: bool,
    branch_hint: str,
    preferred_sub_focus_key: str = "",
    preferred_surface_kind: str = "",
) -> dict | None:
    ladder = area.get("question_ladder")
    if not isinstance(ladder, list) or not ladder:
        return None
    focus_key_out = str(area.get("focus_key", "") or "")
    focus_label_out = str(area.get("label", "") or "")
    focus_turns = _focus_history_count(history, focus_key_out)
    asked_postures = _asked_ladder_postures(history, focus_key_out)
    order = _ladder_posture_order(
        depth=depth,
        focus_turns=focus_turns,
        branch_hint=branch_hint,
        is_short=is_short,
        admission=admission,
    )
    by_posture = {
        str(item.get("posture") or "").lower(): item
        for item in ladder
        if isinstance(item, dict)
    }
    preferred_surface = _preferred_sub_focus_for_area(
        area,
        preferred_sub_focus_key=preferred_sub_focus_key,
        preferred_surface_kind=preferred_surface_kind,
    )
    needs_recovery_followup = branch_hint in {"if_short_answer", "if_honest_gap"} or is_short or admission
    same_thread_followups_allowed = _ladder_same_thread_followups_allowed(area)
    for posture in order:
        item = by_posture.get(posture)
        if not item:
            continue
        if posture == "recover":
            candidate_fields = (
                ["follow_up_if_shallow", "main_question"]
                if same_thread_followups_allowed
                else ["main_question"]
            )
        elif posture in asked_postures:
            if not needs_recovery_followup:
                continue
            if not same_thread_followups_allowed:
                continue
            candidate_fields = ["follow_up_if_shallow", "follow_up_if_strong"]
        else:
            candidate_fields = ["main_question"]
        for field in candidate_fields:
            question = _clean_track_value(item.get(field, ""))
            if not question or _already_asked(question, history):
                continue
            route_kind = ROUTE_FOLLOWUP
            if posture == "clarify":
                route_kind = ROUTE_SURFACE
            elif posture == "explore":
                route_kind = ROUTE_MECHANISM
            elif posture == "pressure":
                route_kind = ROUTE_BOUNDARY
            elif posture == "recover":
                route_kind = ROUTE_SHORT_ANSWER_RESCUE if is_short else ROUTE_FOLLOWUP
            elif posture == "synthesize":
                route_kind = ROUTE_MECHANISM
            return {
                "question": question,
                "route_kind": route_kind,
                "focus_key": focus_key_out,
                "focus_label": focus_label_out,
                "sub_focus_key": preferred_surface.get("sub_focus_key", ""),
                "sub_focus_label": preferred_surface.get("sub_focus_label", ""),
                "surface_kind": preferred_surface.get("surface_kind", ""),
                "branch": f"ladder_{posture}_{field}",
                "question_posture": posture,
                "signal_goal": _clean_track_value(item.get("signal_goal", "")),
                "expected_space": list(item.get("expected_space") or [])[:4],
                "information_gain": _clean_track_value(item.get("information_gain", "medium")).lower(),
                "voice_complexity": _clean_track_value(item.get("voice_complexity", "medium")).lower(),
                "ladder_field": field,
            }
    return None


def _select_from_dimension_area(
    area: dict,
    *,
    history: list[dict],
    depth: int,
    dimension_id: str,
    is_short: bool,
    admission: bool,
    has_discrepancy: bool,
    metric_risk: bool,
    overclaim_risk: bool,
    branch_hint: str,
    allow_bridge: bool,
    preferred_sub_focus_key: str = "",
    preferred_surface_kind: str = "",
) -> dict | None:
    """Route a question from a dimension-schema focus area."""
    recovery = _track_recovery(area)
    dims = _track_dimensions(area)
    focus_key_out = str(area.get("focus_key", "") or "")
    focus_label_out = str(area.get("label", "") or "")
    preferred_surface = _preferred_sub_focus_for_area(
        area,
        preferred_sub_focus_key=preferred_sub_focus_key,
        preferred_surface_kind=preferred_surface_kind,
    )

    def _ret(q: str, route: str, branch: str) -> dict | None:
        q = q.strip()
        if not q or _already_asked(q, history):
            return None
        return {
            "question": q,
            "route_kind": route,
            "focus_key": focus_key_out,
            "focus_label": focus_label_out,
            "sub_focus_key": preferred_surface.get("sub_focus_key", ""),
            "sub_focus_label": preferred_surface.get("sub_focus_label", ""),
            "surface_kind": preferred_surface.get("surface_kind", ""),
            "branch": branch,
        }

    ladder_result = _select_from_question_ladder(
        area,
        history=history,
        depth=depth,
        is_short=is_short,
        admission=admission,
        branch_hint=branch_hint,
        preferred_sub_focus_key=preferred_sub_focus_key,
        preferred_surface_kind=preferred_surface_kind,
    )
    if ladder_result:
        return ladder_result

    # Recovery signals take absolute priority (order matters)
    if branch_hint == "if_short_answer" or is_short:
        r = _ret(recovery.get("short_answer", ""), ROUTE_SHORT_ANSWER_RESCUE, "short_answer")
        if r:
            return r
    if branch_hint == "if_honest_gap" or admission:
        r = _ret(recovery.get("honest_gap", ""), ROUTE_HONESTY_PROBE, "honest_gap")
        if r:
            return r
    if branch_hint == "if_claim_conflict" or has_discrepancy:
        r = _ret(recovery.get("claim_conflict", ""), ROUTE_CHALLENGE, "claim_conflict")
        if r:
            return r
    if metric_risk:
        r = _ret(recovery.get("metric_risk", ""), ROUTE_METRIC_PROBE, "metric_risk")
        if r:
            return r
    if overclaim_risk:
        r = _ret(recovery.get("overclaim_risk", ""), ROUTE_OVERCLAIM_PROBE, "overclaim_risk")
        if r:
            return r

    # Normal depth-based probing: try active dimension first, then unused dims by signal_weight desc
    depth_key = {1: "surface", 2: "mechanism", 3: "boundary"}.get(max(1, min(3, depth)), "surface")
    route_kind = _DEPTH_TO_ROUTE.get(max(1, min(3, depth)), ROUTE_SURFACE)
    active_dims = [d for d in dims if isinstance(d, dict) and d.get("id") == dimension_id]
    other_dims = sorted(
        [d for d in dims if isinstance(d, dict) and d.get("id") != dimension_id],
        key=lambda d: float(d.get("signal_weight") or 1.5),
        reverse=True,
    )
    for dim in active_dims + other_dims:
        probe = _clean_track_value(dim.get(depth_key, ""))
        r = _ret(probe, route_kind, f"dim_{dim.get('id', '')}_{depth_key}")
        if r:
            return r
        # Fall back to surface within the same dim if deeper probe was asked
        if depth_key != "surface":
            probe_s = _clean_track_value(dim.get("surface", ""))
            r = _ret(probe_s, ROUTE_SURFACE, f"dim_{dim.get('id', '')}_surface")
            if r:
                return r

    # Bridge as last resort when allowed
    if allow_bridge:
        r = _ret(recovery.get("bridge", ""), ROUTE_BRIDGE, "bridge")
        if r:
            return r

    return None


def select_from_trajectory_map_detailed(
    interview_map: dict,
    *,
    sprint: int,
    focus_key: str,
    answer: str,
    entities: list[str],
    history: list[dict],
    admission: bool = False,
    has_discrepancy: bool = False,
    branch_hint: str = "",
    depth: int = 1,
    dimension_id: str = "",
    metric_risk: bool = False,
    overclaim_risk: bool = False,
    preferred_sub_focus_key: str = "",
    preferred_surface_kind: str = "",
) -> dict | None:
    if not isinstance(interview_map, dict):
        return None

    focus_areas = interview_map.get("focus_areas", [])
    if not isinstance(focus_areas, list) or not focus_areas:
        return None

    word_count = len([word for word in answer.split() if word])
    is_short = 1 <= word_count <= 8

    # Auto-detect signals from answer text if not provided by caller
    if not metric_risk:
        metric_risk = _has_metric_risk(answer)
    if not overclaim_risk:
        overclaim_risk = _has_overclaim_risk(answer)

    current_matches = [area for area in focus_areas if _focus_area_matches(area, focus_key)]
    last_focus_key = _last_substantive_focus(history)
    last_focus_matches = [
        area for area in focus_areas
        if area not in current_matches and _focus_area_matches(area, last_focus_key)
    ]
    query_tokens = _tokenize(
        " ".join(
            [
                focus_key or "",
                answer or "",
                " ".join(entities or []),
                str(history[-1].get("question", "") or "") if history else "",
            ]
        )
    )
    remaining_scored: list[tuple[int, dict]] = []
    for area in focus_areas:
        if area in current_matches or area in last_focus_matches:
            continue
        area_tokens = _tokenize(
            " ".join(
                [
                    str(area.get("label", "") or ""),
                    str(area.get("anchor_context", "") or ""),
                    " ".join(area.get("resume_snippets", []) or []),
                ]
            )
        )
        score = len(query_tokens & area_tokens)
        if score:
            remaining_scored.append((score, area))
    remaining_scored.sort(key=lambda item: item[0], reverse=True)
    remaining = [area for _, area in remaining_scored]

    search_groups = [
        _sort_by_surface_preference(
            current_matches,
            preferred_sub_focus_key=preferred_sub_focus_key,
            preferred_surface_kind=preferred_surface_kind,
        ),
        _sort_by_surface_preference(
            last_focus_matches,
            preferred_sub_focus_key=preferred_sub_focus_key,
            preferred_surface_kind=preferred_surface_kind,
        ),
        _sort_by_surface_preference(
            remaining,
            preferred_sub_focus_key=preferred_sub_focus_key,
            preferred_surface_kind=preferred_surface_kind,
        ),
    ]

    for group_index, group in enumerate(search_groups):
        if not group:
            continue
        for area in group:
            schema = str(area.get("track_schema", "") or "")
            is_dimension_schema = schema in {"dimension", "v2_ladder"} or bool(area.get("question_ladder")) or ("opener" in area or "dimensions" in area)

            if is_dimension_schema:
                result = _select_from_dimension_area(
                    area,
                    history=history,
                    depth=depth,
                    dimension_id=dimension_id,
                    is_short=is_short,
                    admission=admission,
                    has_discrepancy=has_discrepancy,
                    metric_risk=metric_risk,
                    overclaim_risk=overclaim_risk,
                    branch_hint=branch_hint,
                    allow_bridge=(group_index == 0 and branch_hint == "bridge_to_next_focus") or group_index > 0,
                    preferred_sub_focus_key=preferred_sub_focus_key,
                    preferred_surface_kind=preferred_surface_kind,
                )
                if result:
                    return result
                continue

            # Legacy sprint/branch schema path
            sprint_key = _SPRINT_KEY.get(sprint, "sprint_1")
            priority = _branch_priority(
                is_short=is_short,
                admission=admission,
                has_discrepancy=has_discrepancy,
                branch_hint=branch_hint,
            )
            track = area.get(sprint_key, {})
            if not isinstance(track, dict):
                continue

            branch_order = list(priority)
            if group_index == 0 and "bridge_to_next_focus" in branch_order and branch_hint != "bridge_to_next_focus":
                branch_order = [b for b in branch_order if b != "bridge_to_next_focus"]

            for branch in branch_order:
                question = str(track.get(branch, "") or "").strip()
                if not question or _already_asked(question, history):
                    continue
                route_kind = _BRANCH_TO_ROUTE.get(branch, ROUTE_FOLLOWUP)
                return {
                    "question": question,
                    "route_kind": route_kind,
                    "focus_key": str(area.get("focus_key", "") or ""),
                    "focus_label": str(area.get("label", "") or ""),
                    "branch": branch,
                }

        # Bridge fallback for group 0 on legacy schema
        if group_index == 0:
            for area in group:
                schema = str(area.get("track_schema", "") or "")
                if schema in {"dimension", "v2_ladder"} or area.get("question_ladder") or "opener" in area or "dimensions" in area:
                    continue
                sprint_key = _SPRINT_KEY.get(sprint, "sprint_1")
                track = area.get(sprint_key, {})
                if not isinstance(track, dict):
                    continue
                bridge_question = str(track.get("bridge_to_next_focus", "") or "").strip()
                if bridge_question and not _already_asked(bridge_question, history):
                    return {
                        "question": bridge_question,
                        "route_kind": ROUTE_BRIDGE,
                        "focus_key": str(area.get("focus_key", "") or ""),
                        "focus_label": str(area.get("label", "") or ""),
                        "branch": "bridge_to_next_focus",
                    }

    return None
