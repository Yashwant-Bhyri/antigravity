"""
Resume-grounded interview map / trajectory bank.

This module builds a structured, resume-specific fallback spine for the interview.
It is additive to the live weakness/discrepancy/speculative pipeline:

- live pipeline wins when it has a strong next move
- trajectory map wins when runtime generation is weak, generic, or not ready

The emphasis here is robustness:
- deterministic focus extraction from parsed resume
- per-focus generation so we do not collapse into one giant brittle JSON blob
- structured branches by sprint + answer state
- deterministic fallback templates when the LLM underperforms
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.models.llm_router import LLMRouter


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

class _RecoverySchema(BaseModel):
    short_answer: str = ""
    honest_gap: str = ""
    claim_conflict: str = ""
    metric_risk: str = ""
    overclaim_risk: str = ""
    bridge: str = ""

class _TrackSchema(BaseModel):
    opener: str = ""
    dimensions: list[_DimensionSchema] = Field(default_factory=list)
    recovery: _RecoverySchema = Field(default_factory=_RecoverySchema)
    candidate_q4_options: list[str] = Field(default_factory=list)

class _FocusAreaPlanSchema(BaseModel):
    label: str = ""
    focus_key: str = ""
    anchor_context: str = ""
    sub_focuses: list[str] = Field(default_factory=list)
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


def _validate_schema(raw: Any, model_cls: type[BaseModel]) -> tuple[dict, list[str]]:
    """
    Validate `raw` against `model_cls`. Returns (validated_dict, schema_errors).
    Never raises. On partial failure, falls back field-by-field so valid data is kept.
    """
    if not isinstance(raw, dict):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return model_cls().model_dump(), ["raw output was not valid JSON"]
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

The track has three layers:
1. opener — warm, narrative-inviting question directed at the anchor claim with company/experience context
2. dimensions — 3–5 probing axes grounded in resume evidence, each with surface/mechanism/boundary escalation
3. recovery — 6 response-type overlays usable at any point
4. candidate_q4_options — 3–4 standalone Q4 alternatives for adaptive selection at runtime

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

The pattern every question must follow:
[specific element from their resume claim] + [consequence, challenge, or extension appropriate to the role domain]

Opener rules:
- 20–30 words, directed at the anchor claim
- Include company/experience context: "At [company], you [outcome] — walk me through..."
- Invite narration of the specific work — do NOT ask a mechanism question as the opener
- "Walk me through" and "tell me about" ARE allowed in openers for non-analyst roles — they are the correct framing for narrative-first entry
- The opener must invite the candidate to narrate in their own words before any depth probing begins

Dimension rules (generate 3–5, each grounded in actual resume evidence):
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
- overclaim_risk: when they use domain vocabulary without operational grounding — ask what that term does in their specific implementation
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

Opener: ALWAYS a direct causal challenge or hypothesis question. NEVER "walk me through" or "tell me about" — these are hard-banned for analyst roles. They invite narrative; analysts must defend, not tour.
Format: "At [company], you [specific outcome with the number] — [specific challenge, contradiction, or forced choice that requires an immediate analytical position]."
Forced-choice pattern (use this): "...before we go deeper, [specific contested claim] — [what do you believe] and [what would make you wrong]?"
Example: "At Daily Mantra, retention went from 25% to 42% — Video, Today, and AI Guruji all shipped in the same window. Before we go deeper, which of those three do you believe drove the most lift, and what would make you wrong?"
The opener MUST name a specific number from the resume AND force the candidate to take a position they then have to defend.

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

OVERRIDE: Do NOT use "walk me through" in engineering openers. This overrides the base rule. Engineering openers must use a specific framing — a direct question about the system, its core problem, or its design.

QUESTION CHALLENGE TYPES for engineering roles (use these patterns):
- failure_mode (signal_weight 3.0): "In [their specific system] — what breaks first when [realistic load or failure condition]?"
- design_tradeoff (signal_weight 3.0): "You chose [their specific approach] — when is that the wrong call? What condition makes you not use it?"
- implementation_specificity (signal_weight 2.5): "What did you specifically write or configure to make [their claimed behavior] work?"
- scale_behavior (signal_weight 2.0): "How does [their system] behave differently at [realistic scale increase — 10x, multi-region, concurrent writes]?"

Opener format: "You built [specific thing] at [company] — [what was the core problem you were solving / how did that actually work / what made that hard]?" Use the company and system name from the resume."""


_TRACK_SYSTEM_ML_GUIDE = """

ROLE-TYPE GUIDE — ML Engineer / Data Scientist:

QUESTION CHALLENGE TYPES for ML/data science roles:
- distribution_shift (signal_weight 3.0): "What happens to [their model/system] when [realistic input distribution change]?"
- eval_integrity (signal_weight 3.0): "How did you know [their claimed result] was actually better — and not overfitting to [their test condition]?"
- generalization_boundary (signal_weight 2.5): "Where does [their approach] fail — what condition makes it the wrong choice for this problem?"
- statistical_validity (signal_weight 2.0): "What assumption does [their metric or result] break if [realistic violation of that assumption]?"

Opener: directed at the model or experiment they claimed. Invite them to describe what they were solving and why their approach."""


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
            "growth",
            "business analyst",
            "data analyst",
        )
    )
    return phrase_match or bool(re.search(r"\b(a?pm)\b", role_lower))


def _track_system_prompt(role_type: str = "") -> str:
    """Return the track system prompt with role-type guide appended."""
    base = _TRACK_SYSTEM_BASE
    role_lower = (role_type or "").lower()
    if _is_analyst_or_pm_role(role_type):
        return base + _TRACK_SYSTEM_ANALYST_OVERRIDE
    if any(t in role_lower for t in ("data engineer", "analytics engineer", "data eng", "dbt", "pipeline")):
        return base + _TRACK_SYSTEM_DATA_ENG_GUIDE
    if any(t in role_lower for t in ("machine learning", "ml engineer", "data scientist", "research scientist")):
        return base + _TRACK_SYSTEM_ML_GUIDE
    if any(t in role_lower for t in ("backend", "software engineer", "full stack", "fullstack", "infrastructure", "platform")):
        return base + _TRACK_SYSTEM_ENGINEER_GUIDE
    return base


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
  "opener": "warm narrative question 20-30 words — 'At [company], you [outcome] — walk me through...' — invites narration, does NOT ask mechanism",
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
- opener must be warm and narrative — it enters the focus area by inviting the candidate to narrate
- opener must include company/experience context from the resume snippets
- 3–5 dimensions, every dimension must have a real resume_anchor from the snippets above
- every surface/mechanism/boundary question must follow the pattern: [specific element from their claim] + [consequence, challenge, or probe]
- NO memory questions: never "what was the first X", never "what did you try first"
- NO existence checks: never "did you consider X" — never name the solution you are looking for
- boundary probes must be unanswerable by someone who only read documentation
- signal_weight: 3.0 for dimensions that directly test the core claim; 1.5 default; 1.0 for peripheral context
- candidate_q4_options: 3–4 standalone questions covering different aspects of the anchor claim
- recovery.bridge must explicitly name "{next_focus_label}"
"""

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
    return str(seed.get("anchor_context", "") or "").strip()


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
        r"\b(agent[- ]based .*? pipeline)\b",
        r"\b(audio classification pipeline)\b",
        r"\b(multi-modal benchmark framework)\b",
        r"\b(benchmark framework)\b",
        r"\b(complex hybrid sql queries)\b",
        r"\b(relational db schemas)\b",
        r"\b(custom classifier)\b",
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
    query_tokens = _tokenize(f"{seed.get('label', '')} {_anchor_context_for_focus(seed)}")
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
_MAP_MIN_READY_SCORE = 7.0
_MAP_GENERATOR_MODEL = "anthropic/claude-sonnet-4-6"
_MAP_CRITIC_MODEL = "anthropic/claude-sonnet-4-6"
_MAP_PRIMARY_MAX_TOKENS = 2800
_MAP_RETRY_MAX_TOKENS = 1600
_MAP_JSON_RESPONSE_FORMAT = {"type": "json_object"}
_FOCUS_PLAN_PRIMARY_MAX_TOKENS = 1600  # up to 5 areas × ~300 tokens each
_FOCUS_PLAN_RETRY_MAX_TOKENS = 1000
_MAP_CRITIC_MAX_TOKENS = 1800   # critic JSON with up to 5 focus reviews

_MAP_CRITIC_SYSTEM = """You are a pragmatic interview-map critic.

Review the proposed map like a strong senior interviewer. Your job is to improve the map, not to block it over minor imperfections.

Judge all focus areas carefully — the map may have 2 to 5 areas and every one is startup-critical:
- are the chosen focus areas distinct and non-redundant? Two areas from the same role must probe different technical surfaces.
- is each opener anchored to a specific, provable resume claim? Generic "walk me through everything you've done" is not acceptable — but "At [company], you [specific outcome] — walk me through that work" IS acceptable for non-engineering roles. Engineering openers must use specific framing (what was the core problem, what broke, what was the tradeoff), not "walk me through".
- does each opener enter a clear first dimension rather than asking about everything at once?
- do the dimensions have genuine resume grounding — not generic dimension types applied without evidence?
- does each dimension escalate correctly: surface (basic familiarity) → mechanism (genuine depth) → boundary (unanswerable without real ownership)?
- do the boundary probes require actual hands-on work to answer — not just documentation reading?
- does the recovery set cover short answers, honest gaps, claim conflicts, metric claims without methodology, and vocabulary overclaims?
- does the bridge explicitly name the next focus area?

SCORING RUBRIC — use this to calibrate overall_score and per-area score:
9–10: Every opener is a direct causal challenge or hypothesis — no "walk me through". Every boundary probe is unanswerable without hands-on ownership. signal_weight 3.0 dimensions fire directly on the core resume claim. No surface probe is answerable from documentation alone.
7–8: Solid grounding but one or more openers invite narrative rather than force an analytical position. Some surface probes are answerable without real ownership. Recovery is complete.
5–6: Openers are generic or untethered from specific resume claims. Dimensions use standard templates without resume evidence. Boundary probes could be answered by someone who read the resume carefully but never did the work.
Below 5: Dimensions repeat angles, recovery is incomplete, or focus areas cover the wrong work entirely.

A score above 8.5 requires: opener forces an immediate analytical position, the first dimension is a causal_validity or metric_definition challenge, and every boundary probe names a specific artifact or number from the resume that only an owner would know.

Mark ready=true when every focus area has a strong opener, ≥3 grounded dimensions, and a complete recovery overlay.
Prioritize actionable repair instructions over harsh rejection. Be precise about which dimension and which probe level is weak — "dimension X surface probe is answerable from documentation" beats "questions could be stronger".

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
- If one internship or project has multiple impressive technical angles, merge them into ONE wider focus area. The dimensions inside that area will cover all the angles — do not allocate two separate focus area slots to the same work.
- Each additional focus area slot must represent a DIFFERENT company, project, or research effort from all prior slots.
- If you are tempted to create two areas from the same company/project, combine their technical surfaces into one richer area and use the freed slot for a genuinely different project.

SUB-FOCUS INSTRUCTION:
When a single focus area covers multiple distinct technical surfaces (e.g. an inference pipeline AND a data modeling layer), list each surface as a short phrase in sub_focuses. The track generator uses this list to guarantee at least one dimension per sub-focus — so be explicit. Sub-focus phrases should be 5–12 words, grounded in the resume. If a focus area has only one coherent technical surface, sub_focuses may be empty or contain just that one phrase.

QUESTION BUDGET AND TIME ALLOCATION:
- area[0] (primary anchor): receives ~60% of total interview time — this is the single most analytically rich experience. Select it for depth, not recency alone.
- area[1] (secondary): receives ~25% — worth verifying but not the primary signal
- area[2] and beyond: ~15% attention-check level — 2–3 questions max, confirms the work was real. A 2-month internship must NEVER receive equal billing as a 12-month current role.
- Bridge direction: always from most-recent toward oldest — never route backward in time toward older or less relevant experience

JSON only, no markdown, no commentary."""


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)


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
        "  ]",
        "}",
        "",
        "Scoring expectations:",
        f"- use {_MAP_MIN_READY_SCORE} as a guideline for strong launch quality, not a rigid blocker",
        f"- mark ready=true when all {area_count} focus areas have strong openers and ≥3 grounded dimensions",
        "- opener_quality_score: 0-10, penalise generic walk-through openers, reward hypothesis-style anchored openers",
        "- dimension_depth_score: 0-10, penalise dimensions where boundary probes could be answered from documentation alone",
        "- prioritize actionable repair instructions over harsh rejection",
        f"- keep response compact: at most 3 strengths, 3 issues, 4 repair instructions, focus_reviews for all {area_count} areas",
        "- JSON only",
    ])


def _focus_plan_user_prompt(*, resume: str, dedup_hint: str = "", target_role: str = "") -> str:
    _is_analyst_role = _is_analyst_or_pm_role(target_role)
    anchor_rule = (
        "- anchor_context must prioritize OUTCOME CLAIMS (metrics delivered, decisions made, recommendations adopted) over implementation claims for this role"
        if _is_analyst_role
        else "- area[0] must be the single most technically rich and recent experience"
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
        '      "sub_focuses": ["distinct technical surface 1", "distinct technical surface 2"],',
        '      "resume_snippets": ["exact or near-exact quote from resume"],',
        '      "why_priority": "what makes this worth probing hard"',
        "    }",
        "  ]",
        "}",
        "",
        "Rules:",
        "- 2 to 5 focus_areas, exactly as many as genuinely qualify — never pad, never cut a qualifying area",
        anchor_rule,
        "- each additional area must represent a DIFFERENT company, project, or research effort from the previous ones",
        "- if one project has multiple technical angles, merge them into one wider area with those surfaces listed in sub_focuses — do not allocate two focus area slots to the same work",
        "- each additional area must introduce genuinely different technical territory (different domain, stack, or problem class)",
        "- labels: topic-focused ('AIGC Video Pipeline' not 'Software Engineer Intern')",
        "- keep anchor_context under 180 chars, snippets under 160 chars each",
        "- every value must be a single-line JSON string",
        "- no track key, no extra keys, no markdown",
    ]
    lines = [l for l in lines if l]  # strip empty lines from missing target_role
    if dedup_hint:
        lines.extend([
            "",
            "CRITICAL — fix these problems from the previous attempt before returning:",
            dedup_hint,
            "In particular: if the same project appeared in multiple focus areas, merge those technical surfaces into one wider focus area and use the freed slot(s) for genuinely different projects.",
        ])
    return "\n".join(lines)


def _clean_resume_snippets(snippets: object) -> list[str]:
    cleaned: list[str] = []
    for item in snippets if isinstance(snippets, list) else []:
        value = _clean_track_value(item)
        if value and value not in cleaned:
            cleaned.append(value[:180])
        if len(cleaned) >= 2:
            break
    return cleaned


def _fallback_quality_review(candidate: dict, *, stage: str, issue: str) -> dict:
    focus_areas = list(candidate.get("focus_areas", []) or []) if isinstance(candidate, dict) else []
    detailed_tracks = sum(1 for area in focus_areas if isinstance(area.get("track"), dict))
    top_two_detailed = sum(1 for area in focus_areas[:2] if isinstance(area.get("track"), dict))
    overall_score = 7.6 if len(focus_areas) >= _MAP_MIN_FOCUS_AREAS and detailed_tracks >= 2 else 6.0
    return {
        "stage": stage,
        "critic_model": _MAP_CRITIC_MODEL,
        "ready": overall_score >= _MAP_MIN_READY_SCORE,
        "overall_score": overall_score,
        "top_two_score": 8.0 if top_two_detailed >= 2 else 6.0,
        "opener_quality_score": min(len(focus_areas), _MAP_TARGET_FOCUS_AREAS) / _MAP_TARGET_FOCUS_AREAS * 10.0,
        "dimension_depth_score": min(detailed_tracks, _MAP_TARGET_FOCUS_AREAS) / _MAP_TARGET_FOCUS_AREAS * 10.0,
        "strengths": [
            "Map generation completed and preserved the ranked focus areas.",
            "Critic fallback kept the map moving instead of failing startup over malformed review JSON.",
        ],
        "issues": [issue],
        "repair_instructions": [
            "Sharpen weak or generic questions in the first two focus areas.",
            "Regenerate any tracks that still rely on fallback phrasing.",
        ],
        "focus_reviews": [
            {
                "focus_key": _clean_track_value(area.get("focus_key", "")),
                "label": _clean_track_value(area.get("label", "")),
                "score": 8.0 if isinstance(area.get("track"), dict) else 6.0,
                "issues": [] if isinstance(area.get("track"), dict) else ["Track missing or incomplete."],
            }
            for area in focus_areas[:_MAP_TARGET_FOCUS_AREAS]
            if isinstance(area, dict)
        ],
    }


def _coerce_critic_payload(raw: dict | str) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("Critic response was not a JSON object.")

    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first != -1 and last != -1 and last > first:
            snippet = cleaned[first:last + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                pass
        raise


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


def _normalize_candidate_focus_area(area: dict, *, resume: str, existing_labels: list[str]) -> dict | None:
    if not isinstance(area, dict):
        return None
    label = _prettify_focus_label(_clean_track_value(area.get("label", "")))
    if not label or _is_redundant_label(label, existing_labels):
        return None
    anchor_context = _clean_track_value(area.get("anchor_context", ""))
    focus_key = _compact_focus_key(label, _clean_track_value(area.get("focus_key", "")))
    if not focus_key:
        return None
    sub_focuses = [
        _clean_track_value(s)[:100]
        for s in (area.get("sub_focuses") or [])
        if isinstance(s, str) and _clean_track_value(s)
    ][:6]
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
        "track": area.get("track") if isinstance(area.get("track"), dict) else None,
    }


def _normalize_map_candidate(candidate: dict | str, *, resume: str) -> dict:
    if isinstance(candidate, str):
        cleaned = candidate.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            candidate = json.loads(cleaned)
        except json.JSONDecodeError:
            recovered = _recover_focus_areas_from_text(cleaned)
            if recovered:
                candidate = {"focus_areas": recovered}
            else:
                raise
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

    # Only pad with deterministic seeds if the planner returned fewer than the minimum.
    # If the planner returned ≥ _MAP_MIN_FOCUS_AREAS we trust its judgment about which
    # experiences are worth probing — do NOT pad with rudimentary fallback entries.
    if len(normalized) < _MAP_MIN_FOCUS_AREAS:
        for seed in _fallback_focus_seeds_from_resume(resume, limit=_MAP_MIN_FOCUS_AREAS):
            if seed["focus_key"] in seen_focus_keys:
                continue
            if _is_redundant_label(seed["label"], existing_labels):
                continue
            snippets = _extract_resume_snippets(resume, seed, limit=3)
            normalized.append({
                "label": seed["label"],
                "focus_key": seed["focus_key"],
                "anchor_context": seed["anchor_context"],
                "resume_snippets": snippets[:3],
                "why_priority": "",
                "track": None,
            })
            existing_labels.append(seed["label"])
            seen_focus_keys.add(seed["focus_key"])
            if len(normalized) >= _MAP_MIN_FOCUS_AREAS:
                break

    return {
        "focus_areas": normalized[:_MAP_TARGET_FOCUS_AREAS],
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


def _critic_signals_plan_problem(review: dict) -> bool:
    """True when the critic's output indicates the focus plan itself is bad (duplicates/same-project splits)."""
    if not isinstance(review, dict):
        return False
    texts = [
        *[str(s) for s in (review.get("issues") or [])],
        *[str(s) for s in (review.get("repair_instructions") or [])],
    ]
    joined = " ".join(texts).lower()
    problem_signals = ("merge", "duplic", "redundant", "overlap", "same project", "same company",
                       "same role", "split", "collapse", "combine", "consolidate", "too similar")
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


async def _generate_focus_area_plan(*, resume: str, session_id: str, dedup_hint: str = "", target_role: str = "") -> dict:
    user_prompt = _focus_plan_user_prompt(resume=resume, dedup_hint=dedup_hint, target_role=target_role)

    raw = await _run_focus_plan_call(
        LLMRouter(tier="medium", timeout_override=60.0),
        user_prompt,
        _FOCUS_PLAN_PRIMARY_MAX_TOKENS,
        _FOCUS_PLAN_RETRY_MAX_TOKENS,
    )

    if not isinstance(raw, dict):
        raise RuntimeError("Focus-area planning failed: model returned no usable output.")

    validated_plan, plan_errors = _validate_schema(raw, _FocusPlanSchema)
    if plan_errors:
        print(f"[TrajectoryMap] Focus plan schema issues: {plan_errors[:3]}")
    raw = {**raw, "focus_areas": validated_plan["focus_areas"]}

    normalized = _normalize_map_candidate(raw, resume=resume)
    n = len(normalized.get("focus_areas", []) or [])
    if n < _MAP_MIN_FOCUS_AREAS:
        raise ValueError(f"Focus-area plan returned fewer than {_MAP_MIN_FOCUS_AREAS} usable areas (got {n}).")

    print(
        f"[TrajectoryMap] Planned {n} focus areas"
        + (f" for {session_id[:8]}" if session_id else "")
    )
    return normalized


def _build_critic_review(payload: dict, *, stage: str, critic_model: str) -> dict:
    """Normalise a raw critic response into the canonical review shape."""
    return {
        "stage": stage,
        "critic_model": critic_model,
        "ready": bool(payload.get("ready", False)),
        "overall_score": float(payload.get("overall_score", 0) or 0),
        "top_two_score": float(payload.get("top_two_score", 0) or 0),
        # New fields from updated critic prompt; fall back to old names for backward compat
        "opener_quality_score": float(payload.get("opener_quality_score", payload.get("coverage_score", 0)) or 0),
        "dimension_depth_score": float(payload.get("dimension_depth_score", payload.get("branch_richness_score", 0)) or 0),
        "strengths": [str(s).strip() for s in (payload.get("strengths") or []) if str(s).strip()][:8],
        "issues": [str(s).strip() for s in (payload.get("issues") or []) if str(s).strip()][:8],
        "repair_instructions": [str(s).strip() for s in (payload.get("repair_instructions") or []) if str(s).strip()][:8],
        "focus_reviews": [
            {
                "focus_key": _clean_track_value(item.get("focus_key", "")),
                "label": _clean_track_value(item.get("label", "")),
                "score": float(item.get("score", 0) or 0),
                "issues": [str(v).strip() for v in (item.get("issues") or []) if str(v).strip()][:4],
            }
            for item in (payload.get("focus_reviews") or [])
            if isinstance(item, dict)
        ][: _MAP_TARGET_FOCUS_AREAS],
    }


async def _critique_map_candidate(*, resume: str, candidate: dict, stage: str) -> dict:
    critic = LLMRouter(
        tier="medium",
        model_override=_MAP_CRITIC_MODEL,
        timeout_override=90.0,
    )
    user_prompt = _map_critic_user_prompt(resume=resume, candidate=candidate, stage=stage)
    try:
        raw = await critic.call(
            system=_MAP_CRITIC_SYSTEM,
            user=user_prompt,
            max_tokens=_MAP_CRITIC_MAX_TOKENS,
            response_format=_MAP_JSON_RESPONSE_FORMAT,
        )
        validated, schema_errors = _validate_schema(raw, _CriticSchema)
        if schema_errors:
            print(f"[TrajectoryMap] Critic schema issues during {stage}: {schema_errors[:3]}")
        return _build_critic_review(validated, stage=stage, critic_model=critic.model)
    except Exception as exc:
        affordable_tokens = _affordable_token_budget_from_error(exc)
        if affordable_tokens and affordable_tokens < _MAP_CRITIC_MAX_TOKENS:
            try:
                raw = await critic.call(
                    system=_MAP_CRITIC_SYSTEM,
                    user=user_prompt,
                    max_tokens=affordable_tokens,
                    response_format=_MAP_JSON_RESPONSE_FORMAT,
                )
                validated, schema_errors = _validate_schema(raw, _CriticSchema)
                if schema_errors:
                    print(f"[TrajectoryMap] Critic schema issues (retry) during {stage}: {schema_errors[:3]}")
                return _build_critic_review(validated, stage=stage, critic_model=critic.model)
            except Exception:
                pass
        print(
            f"[TrajectoryMap] Critic call failed during {stage}; using heuristic fallback: "
            f"{type(exc).__name__}: {exc}"
        )
        return _fallback_quality_review(
            candidate,
            stage=stage,
            issue=f"Critic call failed during {stage}: {type(exc).__name__}: {exc}",
        )


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


def _coerce_llm_track(raw_track: dict | None, *, seed: dict, next_focus_label: str, source_override: str | None = None) -> dict:
    fallback_dim = _fallback_dimension_track(seed, next_focus_label)

    if not isinstance(raw_track, dict):
        fallback_dims = fallback_dim.get("dimensions", [])
        return {
            "track": fallback_dim,
            "source": "deterministic_fallback",
            "llm_branches": [],
            "fallback_branches": [d["id"] for d in fallback_dims],
            "llm_branch_count": 0,
            "fallback_branch_count": len(fallback_dims),
        }

    # New dimension schema: opener + dimensions + recovery
    if "opener" in raw_track or "dimensions" in raw_track:
        parsed = _parse_dimension_output(raw_track, seed, fallback_dim)
        parsed.setdefault("candidate_q4_options", [])
        dims = parsed.get("dimensions", [])
        fallback_dim_ids = {d["id"] for d in fallback_dim.get("dimensions", [])}
        llm_branches = [d["id"] for d in dims if d["id"] not in fallback_dim_ids]
        fallback_branches = [d["id"] for d in dims if d["id"] in fallback_dim_ids]
        # Use preserved source provenance — do NOT infer from content (fallback dicts also have
        # opener/dimensions keys and would be mislabelled as "llm" without this override).
        source = source_override if source_override in ("llm", "deterministic_fallback") else "llm"
        return {
            "track": parsed,
            "source": source,
            "llm_branches": llm_branches,
            "fallback_branches": fallback_branches,
            "llm_branch_count": len(llm_branches),
            "fallback_branch_count": len(fallback_branches),
        }

    # Legacy sprint/branch schema — backward compat for old maps in Redis
    fallback_track = _fallback_track(seed, next_focus_label)
    cleaned_result: dict[str, dict[str, str]] = {}
    llm_branches: list[str] = []
    fallback_branches: list[str] = []
    for sprint_key in _SPRINT_KEYS:
        sprint = raw_track.get(sprint_key, {})
        fallback_sprint = fallback_track.get(sprint_key, {})
        if not isinstance(sprint, dict):
            sprint = {}
        cleaned_sprint: dict[str, str] = {}
        for branch in _VALID_BRANCHES:
            value = _clean_track_value(sprint.get(branch, ""))
            branch_key = f"{sprint_key}.{branch}"
            if value:
                cleaned_sprint[branch] = value
                llm_branches.append(branch_key)
            else:
                cleaned_sprint[branch] = _clean_track_value(fallback_sprint.get(branch, ""))
                fallback_branches.append(branch_key)
        cleaned_result[sprint_key] = cleaned_sprint

    return {
        "track": cleaned_result,
        "source": "llm",
        "llm_branches": llm_branches,
        "fallback_branches": fallback_branches,
        "llm_branch_count": len(llm_branches),
        "fallback_branch_count": len(fallback_branches),
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
            "sub_focuses": [str(s).strip() for s in (area.get("sub_focuses") or []) if str(s).strip()],
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
        schema_version = "dimension" if ("opener" in track_data or "dimensions" in track_data) else "sprint"
        focus_areas.append({
            "label": seed["label"],
            "focus_key": seed["focus_key"],
            "anchor_context": seed["anchor_context"],
            "sub_focuses": seed["sub_focuses"],
            "resume_snippets": seed["resume_snippets"][:3],
            "track_source": track_result.get("source", "deterministic_fallback"),
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

    return {
        "focus_areas": focus_areas,
        "generated_at": time.time(),
        "pending_hydration_focus_keys": [],
        "generation_strategy": "two_pass_full_resume_reasoning",
        "pass_1_review": pass_one_review or {},
        "quality_review": final_review or {},
        "generation_notes": str(candidate.get("notes", "") or "").strip(),
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
        ("video", "the video-generation workflow"),
        ("audio", "the audio pipeline"),
        ("benchmark", "the benchmark design"),
        ("sql", "the SQL and schema design"),
        ("classifier", "the classifier pipeline"),
        ("latency", "the latency profile"),
        ("retrieval", "the retrieval setup"),
        ("ui-to-latent", "the UI-to-latent translation path"),
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
    priority_map = {
        "classifier": [
            "dsp",
            "npu",
        ],
        "benchmark": [
            "ocr",
            "sql",
            "rag",
        ],
        "data_modeling": [
            "sql",
            "ocr",
        ],
        "pipeline": [
            "rag",
            "llm",
            "nlp",
        ],
    }
    artifact_norm = re.sub(r"[^a-z0-9]+", " ", artifact.lower()).strip()
    priorities = priority_map.get(family_probe, [])

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
    signals = _extract_focus_signals(seed)
    artifact = signals["artifact"]
    primary_tech = signals["primary_tech"]
    secondary_tech = signals["secondary_tech"]
    metric = signals["metric"]
    domain = signals["domain"]
    family = _artifact_family(signals)

    metric_clause = f" around {metric}" if metric else ""
    sprint_1_strong = f"Staying with {artifact}, why did you choose {primary_tech} for the critical path?"
    sprint_1_vague = f"In {artifact}, which exact component did you personally implement rather than just tune or review?"
    sprint_2_strong = f"In {artifact}, what mechanism inside {primary_tech} mattered most to making {domain} work well?"
    sprint_2_vague = f"For {artifact}, what was the actual mechanism behind {primary_tech}, not just the high-level goal?"
    sprint_3_strong = f"If {artifact} had to operate at much larger scale{metric_clause}, what would you redesign first around {primary_tech}?"
    sprint_3_vague = f"What reliability risk would you watch first if {artifact} had to handle real production pressure?"

    if family == "classifier":
        sprint_1_strong = f"Staying with {artifact}, why did you choose {primary_tech} over a simpler inference path?"
        sprint_2_strong = f"In {artifact}, what part of the inference or feature-extraction path mattered most to accuracy?"
        sprint_3_strong = f"If {artifact} had to preserve accuracy{metric_clause} on weaker hardware, what would you redesign first?"
    elif family == "interface":
        sprint_1_strong = f"Staying with {artifact}, how did you translate user intent into {primary_tech} without losing control?"
        sprint_2_strong = f"In {artifact}, what mechanism kept the UI controls aligned with the underlying generation behavior?"
        sprint_3_strong = f"If {artifact} had to support many more controls and users, what would you redesign first?"
    elif family == "benchmark":
        sprint_1_strong = f"Staying with {artifact}, why did you structure it around {primary_tech} instead of a simpler benchmark design?"
        sprint_2_strong = f"In {artifact}, what mechanism made the evaluation challenge genuinely hard rather than superficial?"
        sprint_3_strong = f"If {artifact} had to expand much further, what data-quality or evaluation risk would you tackle first?"
    elif family == "data_modeling":
        sprint_1_strong = f"Staying with {artifact}, why did you choose {primary_tech} as the core modeling surface?"
        sprint_2_strong = f"In {artifact}, what schema or query mechanism mattered most to making the workload realistic?"
        sprint_3_strong = f"If {artifact} had to support much larger query volume, what would you redesign first?"

    return {
        "sprint_1": {
            "if_strong": sprint_1_strong,
            "if_vague": sprint_1_vague,
            "if_honest_gap": f"That's useful. Within {artifact}, which part of {primary_tech} do you feel you can explain confidently?",
            "if_claim_conflict": f"Your resume frames {artifact} as hands-on work. Which concrete module did you actually own end to end?",
            "if_short_answer": f"On {artifact}, what specific part of {primary_tech} are you referring to?",
            "bridge_to_next_focus": f"Before we move on, how does {artifact} connect to {next_focus_label} in your background?",
        },
        "sprint_2": {
            "if_strong": sprint_2_strong,
            "if_vague": sprint_2_vague,
            "if_honest_gap": f"Even if you did not own all of {artifact}, what concept behind {primary_tech} do you understand best?",
            "if_claim_conflict": f"You mention {artifact} confidently. What did you have to reason through inside {secondary_tech} yourself?",
            "if_short_answer": f"When you answer briefly about {artifact}, what concrete mechanism inside {primary_tech} are you pointing to?",
            "bridge_to_next_focus": f"Keeping {artifact} in mind, what nearby part of your background should we examine next?",
        },
        "sprint_3": {
            "if_strong": sprint_3_strong,
            "if_vague": sprint_3_vague,
            "if_honest_gap": f"If you did not own all of {artifact}, which design tradeoff there can you still reason about confidently?",
            "if_claim_conflict": f"If {artifact} were stressed harder in production, where would your current story about {primary_tech} start to break?",
            "if_short_answer": f"For {artifact}, what specific bottleneck or failure mode around {primary_tech} are you referring to?",
            "bridge_to_next_focus": f"Using {artifact} as a bridge, how would you contrast it with {next_focus_label}?",
        },
    }


def _fallback_dimension_track(seed: dict, next_focus_label: str) -> dict:
    """Deterministic opener + dimensions + recovery when LLM generation fails."""
    signals = _extract_focus_signals(seed)
    artifact = signals["artifact"]
    primary_tech = signals["primary_tech"]
    secondary_tech = signals["secondary_tech"]
    metric = signals["metric"]
    domain = signals["domain"]
    family = _artifact_family(signals)
    metric_clause = f" around {metric}" if metric else ""
    next_label = next_focus_label or "another area from your background"

    if family == "classifier":
        opener = f"On {artifact} — how did you approach the inference pipeline from feature extraction through model output?"
        dim_surface = f"Which component of the {artifact} inference path did you personally own?"
        dim_mech = f"What did {primary_tech} contribute specifically versus what you wrote from scratch?"
        dim_boundary = f"When the classifier degraded on real data, what was the first place you looked inside {primary_tech}?"
    elif family == "interface":
        opener = f"In {artifact} — how did user-facing controls translate into {primary_tech} instructions?"
        dim_surface = f"What was the internal representation between UI input and {primary_tech} behavior?"
        dim_mech = f"How did you keep multiple controls from interfering with each other inside {primary_tech}?"
        dim_boundary = f"If a control produced no visible effect in {artifact}, what would you check first?"
    elif family == "benchmark":
        opener = f"In {artifact} — how did you design the evaluation challenge to require genuine reasoning, not pattern matching?"
        dim_surface = f"What made {artifact} harder than simpler benchmarks in the same space?"
        dim_mech = f"How did you validate that {primary_tech} difficulty was calibrated correctly?"
        dim_boundary = f"What data-quality problem in {artifact} would most undermine its results?"
    elif family == "data_modeling":
        opener = f"In {artifact} — how did you approach the schema design to support the query workload?"
        dim_surface = f"Which part of the {artifact} schema did you personally design versus inherit?"
        dim_mech = f"What was the hardest query in {artifact} to make both correct and performant?"
        dim_boundary = f"If the {artifact} query volume tripled, where would the schema break first?"
    else:
        opener = f"On {artifact} — start with how you approached {domain} specifically."
        dim_surface = f"Which exact component of {artifact} did you personally build rather than integrate?"
        dim_mech = f"What was the mechanism inside {primary_tech} that made {domain} work correctly?"
        dim_boundary = f"If {artifact} had to handle production pressure{metric_clause}, what would break first in your current design?"

    return {
        "opener": opener,
        "dimensions": [
            {
                "id": "implementation_ownership",
                "label": "What they personally built",
                "resume_anchor": _anchor_context_for_focus(seed) or artifact,
                "surface": dim_surface,
                "mechanism": dim_mech,
                "boundary": dim_boundary,
            },
            {
                "id": "technology_choice",
                "label": "Technology decisions",
                "resume_anchor": primary_tech or artifact,
                "surface": f"Why did you choose {primary_tech} for {artifact} over simpler alternatives?",
                "mechanism": f"What did {primary_tech} specifically contribute that justified the complexity?",
                "boundary": f"If {primary_tech} were unavailable, what specifically would change in {artifact}?",
            },
            {
                "id": "failure_modes",
                "label": "Failures and debugging",
                "resume_anchor": _anchor_context_for_focus(seed) or artifact,
                "surface": f"What was the hardest bug you encountered in {artifact}?",
                "mechanism": f"What did that failure reveal about how {primary_tech} behaves under stress?",
                "boundary": f"If {artifact} ran in a more demanding environment, where would it degrade first and why?",
            },
        ],
        "recovery": {
            "short_answer": f"On {artifact} specifically — what part of {primary_tech} are you referring to?",
            "honest_gap": f"Fair. Which part of {artifact} can you explain most confidently end-to-end?",
            "claim_conflict": f"Your resume describes {artifact} as hands-on work. Which module did you actually own versus review?",
            "metric_risk": f"You mentioned a metric{metric_clause} — what was the baseline you compared against and how did you measure it?",
            "overclaim_risk": f"You used that term — what does it do specifically in your {artifact} implementation?",
            "bridge": f"Switching to {next_label} — how does the design thinking there contrast with what you just described?",
        },
    }


def _parse_dimension_output(raw: dict | str, seed: dict, fallback: dict) -> dict:
    """Parse new opener+dimensions+recovery schema. Falls back gracefully on bad output."""
    if isinstance(raw, str):
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            raw = json.loads(cleaned)
        except json.JSONDecodeError:
            obj_match = re.search(r"\{[\s\S]*\}", cleaned)
            if obj_match:
                try:
                    raw = json.loads(obj_match.group(0))
                except json.JSONDecodeError:
                    return fallback
            else:
                return fallback

    if not isinstance(raw, dict):
        return fallback

    # Pydantic validation: coerce types and catch structural errors early
    validated, schema_errors = _validate_schema(raw, _TrackSchema)
    if schema_errors:
        print(f"[TrajectoryMap] Track schema issues for '{seed.get('label', '?')}': {schema_errors[:3]}")

    opener = _clean_track_value(validated.get("opener", ""))
    dims_raw = validated.get("dimensions") or []
    recovery_raw = validated.get("recovery") or {}
    q4_options_raw = validated.get("candidate_q4_options") or []

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
        try:
            signal_weight = float(d.get("signal_weight") or 1.5)
        except (TypeError, ValueError):
            signal_weight = 1.5
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
    fallback_recovery = fallback.get("recovery", {})
    for field in recovery_fields:
        val = _clean_track_value(recovery_raw.get(field, "") if isinstance(recovery_raw, dict) else "")
        recovery[field] = val or _clean_track_value(fallback_recovery.get(field, ""))

    if not opener or len(dims) < 3:
        fallback_dims = fallback.get("dimensions", [])
        if not opener:
            opener = fallback.get("opener", "")
        if len(dims) < 3:
            dims = dims + [d for d in fallback_dims if d.get("id") not in {x["id"] for x in dims}]
            dims = dims[:6]

    result = {
        "opener": opener,
        "dimensions": dims[:6],
        "recovery": recovery,
        "candidate_q4_options": candidate_q4_options,
    }
    result.setdefault("candidate_q4_options", [])
    return result


def _clean_track_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


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


def _parse_track_output(raw: dict | str, seed: dict, fallback_track: dict) -> dict:
    if isinstance(raw, dict):
        result = raw
    elif isinstance(raw, str):
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        result = json.loads(cleaned)
    else:
        raise ValueError(f"Unexpected track output type: {type(raw)}")

    cleaned_result: dict[str, dict[str, str]] = {}
    llm_branches: list[str] = []
    fallback_branches: list[str] = []
    for sprint_key in _SPRINT_KEYS:
        track = result.get(sprint_key, {})
        fallback_branch_track = fallback_track.get(sprint_key, {})
        if not isinstance(track, dict):
            track = {}
        cleaned_track: dict[str, str] = {}
        for branch in _VALID_BRANCHES:
            value = _clean_track_value(track.get(branch, ""))
            if value and not _question_is_generic_or_off_focus(value, seed):
                cleaned_track[branch] = value
                llm_branches.append(f"{sprint_key}.{branch}")
            elif fallback_branch_track.get(branch):
                cleaned_track[branch] = _clean_track_value(fallback_branch_track.get(branch, ""))
                fallback_branches.append(f"{sprint_key}.{branch}")
        if _VALID_BRANCHES - set(cleaned_track):
            raise ValueError(f"{sprint_key} missing branches after fallback fill")
        cleaned_result[sprint_key] = cleaned_track
    return {
        "track": cleaned_result,
        "llm_branches": llm_branches,
        "fallback_branches": fallback_branches,
        "llm_branch_count": len(llm_branches),
        "fallback_branch_count": len(fallback_branches),
    }


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
    fallback_dim = _fallback_dimension_track(seed, next_focus_label)

    def _make_user(snippets_limit: int, anchor_limit: int) -> str:
        prior_block = (
            f"\nPrior track context (for deduplication):\n{prior_track_context}\n"
            if prior_track_context.strip()
            else ""
        )
        sub_focuses = [str(s).strip() for s in (seed.get("sub_focuses") or []) if str(s).strip()]
        sub_focuses_block = (
            "- Sub-focuses (must have ≥1 dimension each): "
            + " | ".join(sub_focuses)
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

    # Startup-critical path: small model first for speed, medium fallback for quality.
    primary_tokens = 1600 if fast_mode else 2000
    primary_timeout = _FOCUS_TRACK_TIMEOUT_SECONDS if fast_mode else _FOCUS_TRACK_BACKGROUND_TIMEOUT_SECONDS
    llm = LLMRouter(
        tier="small" if fast_mode else "medium",
        model_override=None if fast_mode else _MAP_GENERATOR_MODEL,
        timeout_override=None if fast_mode else 90.0,
    )
    user = _make_user(snippets_limit=5, anchor_limit=400)
    last_error: Exception | None = None

    _track_sys = _track_system_prompt(role_type)

    async def _attempt(llm_: LLMRouter, prompt: str, max_tok: int, timeout: float) -> dict | None:
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
            return {"track": _parse_dimension_output(raw, seed, fallback_dim), "source": "llm"}
        except Exception as exc:
            nonlocal last_error
            last_error = exc
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
                    return {"track": _parse_dimension_output(raw2, seed, fallback_dim), "source": "llm"}
                except Exception as exc2:
                    last_error = exc2
            return None

    result = await _attempt(llm, user, primary_tokens, primary_timeout)
    if result:
        return result

    # Upgrade-tier retry
    if fast_mode:
        retry_llm = LLMRouter(tier="medium", timeout_override=10.0)
        retry_user = _make_user(snippets_limit=4, anchor_limit=300)
        result = await _attempt(retry_llm, retry_user, 1500, 10.0)
    else:
        retry_llm = LLMRouter(tier="large", model_override=_MAP_GENERATOR_MODEL, timeout_override=90.0)
        retry_user = _make_user(snippets_limit=4, anchor_limit=320)
        result = await _attempt(retry_llm, retry_user, 1800, 90.0)

    if result:
        return result

    print(
        f"[TrajectoryMap] Focus {seed['focus_key']} fell back to deterministic templates"
        + (f" for {session_id[:8]}" if session_id else "")
        + f": {type(last_error).__name__}: {str(last_error) or '(no message)'}"
    )
    fallback_dims = fallback_dim.get("dimensions", [])
    return {
        "track": fallback_dim,
        "source": "deterministic_fallback",
        "llm_branches": [],
        "fallback_branches": [d["id"] for d in fallback_dims],
        "llm_branch_count": 0,
        "fallback_branch_count": len(fallback_dims),
    }


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


def _dim_context_summary(area_label: str, track: dict | None) -> str:
    """Return a one-line deduplication hint from a completed track-1 dimension result."""
    if not isinstance(track, dict):
        return ""
    dims = track.get("dimensions", [])
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

    Checks: openers, dimension labels, surface/mechanism/boundary probe texts.
    Bridge text is excluded — bridges intentionally reference adjacent area names.
    Returns list of warning strings (and also prints each one).
    """
    # slot_type → Jaccard threshold to flag as overlap
    THRESHOLDS = {"opener": 0.60, "label": 0.50, "probe": 0.58}

    # Collect (area_label, slot_type, slot_name, tokens) tuples
    slots: list[tuple[str, str, str, frozenset[str]]] = []
    for area in areas:
        area_label = str(area.get("label", "") or "")
        opener = str(area.get("opener", "") or "")
        if opener:
            slots.append((area_label, "opener", "opener", _content_tokens(opener)))
        for dim in (area.get("dimensions") or []):
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
    target_role: str = "",
) -> dict:
    focus_areas = list(candidate.get("focus_areas", []) or [])
    if not focus_areas:
        return candidate

    def _make_seed(index: int, area: dict) -> dict:
        return {
            "label": str(area.get("label", "") or f"Focus Area {index + 1}").strip(),
            "focus_key": str(area.get("focus_key", "") or f"focus_{index + 1}").strip(),
            "anchor_context": str(area.get("anchor_context", "") or "").strip(),
            "sub_focuses": [str(s).strip() for s in (area.get("sub_focuses") or []) if str(s).strip()],
            "resume_snippets": list(area.get("resume_snippets", []) or []),
        }

    def _next_label(index: int) -> str:
        return (
            str(focus_areas[(index + 1) % len(focus_areas)].get("label", "") or "").strip()
            if len(focus_areas) > 1
            else "another area from the candidate's background"
        )

    def _apply_result(area: dict, result: dict) -> dict:
        """Merge generation result into area — preserve source provenance alongside track."""
        updated = dict(area)
        updated["track"] = result.get("track")
        # Preserve provenance so _candidate_to_runtime_map can set track_source correctly.
        # Fallback tracks are fully populated dicts so we can't detect source from content alone.
        updated["_gen_source"] = result.get("source", "deterministic_fallback")
        return updated

    # Phase 2: generate ALL fixated areas in parallel — areas were fixated in phase 1 (focus plan)
    # so we know exactly which experiences to probe; no sequential dependency.
    all_indices = list(range(len(focus_areas)))

    async def _gen_track(index: int) -> dict:
        area = focus_areas[index]
        seed = _make_seed(index, area)
        result = await _generate_focus_track(
            resume_context=resume,
            seed=seed,
            next_focus_label=_next_label(index),
            session_id=session_id,
            fast_mode=False,
            repair_guidance=_critic_guidance_for_focus(critic_feedback, seed["focus_key"]),
            prior_track_context="",
            role_type=target_role,
        )
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
    Build the startup-critical interview map using the full resume.

    Pass 1:
    - read the full resume
    - choose 5 focus areas with one structured planning call
    - fully detail the top 2 tracks in parallel

    Critique 1:
    - Sonnet grades launch readiness and gives compact repair direction

    Optional repair:
    - if the first two tracks are not strong enough, regenerate only those startup tracks once

    Startup contract:
    - if the first two priority tracks are robust, the interview may start immediately
    - remaining focus areas may still use deterministic tracks for now
    """
    started = time.perf_counter()
    try:
        focus_plan = await _generate_focus_area_plan(
            resume=resume,
            session_id=session_id,
            target_role=target_role,
        )
        pass_one_candidate = await _generate_priority_tracks_for_candidate(
            resume=resume,
            candidate=focus_plan,
            session_id=session_id,
            target_role=target_role,
        )
        pass_one_review = await _critique_map_candidate(
            resume=resume,
            candidate=pass_one_candidate,
            stage="pass_1",
        )

        final_candidate = pass_one_candidate
        final_review = pass_one_review

        if not _review_is_ready(pass_one_review) or _has_targeted_repairs(pass_one_review):
            try:
                # If the critic is telling us the focus plan itself is wrong (duplicate splits,
                # redundant areas, same project in multiple slots), regenerate the plan first.
                # Retrying tracks against a bad plan cannot fix a bad plan.
                repair_base_plan = focus_plan
                if _critic_signals_plan_problem(pass_one_review):
                    hint = _extract_plan_repair_hint(pass_one_review)
                    print(
                        f"[TrajectoryMap] Critic flagged plan-level problem"
                        + (f" for {session_id[:8]}" if session_id else "")
                        + f"; regenerating focus plan with dedup hint"
                    )
                    try:
                        repair_base_plan = await _generate_focus_area_plan(
                            resume=resume,
                            session_id=session_id,
                            dedup_hint=hint,
                            target_role=target_role,
                        )
                    except Exception as plan_exc:
                        print(
                            f"[TrajectoryMap] Focus plan regeneration failed"
                            + (f" for {session_id[:8]}" if session_id else "")
                            + f"; falling back to original plan: {type(plan_exc).__name__}: {plan_exc}"
                        )
                        repair_base_plan = focus_plan

                repaired_candidate = await _generate_priority_tracks_for_candidate(
                    resume=resume,
                    candidate=repair_base_plan,
                    session_id=session_id,
                    critic_feedback=pass_one_review,
                    target_role=target_role,
                )
                repaired_review = await _critique_map_candidate(
                    resume=resume,
                    candidate=repaired_candidate,
                    stage="pass_1_repair",
                )
                if _review_score(repaired_review) >= _review_score(pass_one_review):
                    final_candidate = repaired_candidate
                    final_review = repaired_review
            except Exception as exc:
                print(
                    f"[TrajectoryMap] Startup repair pass failed"
                    + (f" for {session_id[:8]}" if session_id else "")
                    + f"; keeping pass 1 map: {type(exc).__name__}: {exc}"
                )
                final_candidate = pass_one_candidate
                final_review = _fallback_quality_review(
                    pass_one_candidate,
                    stage="pass_1_degraded",
                    issue=f"Startup repair pass failed; keeping the first-pass map: {type(exc).__name__}: {exc}",
                )

        interview_map = _candidate_to_runtime_map(
            resume=resume,
            candidate=final_candidate,
            pass_one_review=pass_one_review,
            final_review=final_review,
            session_id=session_id,
        )

        startup_validation = validate_interview_map(
            interview_map,
            require_all_llm=False,
            min_llm_branch_ratio=0.72,
        )
        # Startup only needs _MAP_MIN_FOCUS_AREAS LLM-ready areas — remaining can be hydrated
        # later by the caller. Requiring all areas here caused the 6-minute blocking wait in prod.
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
                interview_map = await hydrate_interview_map_tracks(
                    interview_map=interview_map,
                    resume=resume,
                    session_id=session_id,
                    focus_keys=missing_priority_keys,
                )

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        print(
            f"[TrajectoryMap] Built {len(interview_map.get('focus_areas', []))} focus areas in {elapsed_ms}ms"
            + (f" for {session_id[:8]}" if session_id else "")
        )
        return interview_map
    except Exception as exc:
        print(
            f"[TrajectoryMap] Startup map generation failed"
            + (f" for {session_id[:8]}" if session_id else "")
            + f": {type(exc).__name__}: {exc}"
        )
        fallback = build_deterministic_interview_map(resume=resume, session_id=session_id)
        priority_keys = [
            str(area.get("focus_key", "") or "")
            for area in (fallback.get("focus_areas") or [])
            if str(area.get("focus_key", "") or "")
        ]
        if priority_keys:
            fallback = await hydrate_interview_map_tracks(
                interview_map=fallback,
                resume=resume,
                session_id=session_id,
                focus_keys=priority_keys,
            )
        fallback["quality_review"] = {
            "stage": "fallback",
            "critic_model": "none",
            "ready": True,
            "overall_score": 7.0,
            "issues": [f"Startup planner failed; used deterministic focus plan plus targeted track recovery: {type(exc).__name__}: {exc}"],
            "repair_instructions": [],
            "focus_reviews": [],
        }
        return fallback


def build_deterministic_interview_map(
    *,
    resume: str,
    session_id: str = "",
) -> dict:
    """
    Build a fully deterministic interview map with no provider calls.

    This is the startup safety net when the LLM-backed trajectory builder is slow
    or unavailable. The goal is not perfect phrasing; the goal is to guarantee a
    resume-grounded spine so the interview can still start cleanly.
    """
    started = time.perf_counter()
    seeds = _fallback_focus_seeds_from_resume(resume)
    if not seeds:
        resume_units = _resume_units(resume)
        anchor = resume_units[0][:220] if resume_units else "the candidate's recent technical work"
        seeds = [{
            "label": "Recent Technical Work",
            "focus_key": "recent_technical_work",
            "anchor_context": anchor,
        }]

    focus_areas: list[dict] = []
    for index, seed in enumerate(seeds[:5]):
        focus_key = _compact_focus_key(
            str(seed.get("label", "") or ""),
            str(seed.get("focus_key", "") or ""),
        )
        normalized_seed = {
            **seed,
            "focus_key": focus_key or f"focus_{index + 1}",
        }
        snippets = _extract_resume_snippets(resume, normalized_seed, limit=3)
        if not snippets:
            anchor_context = _anchor_context_for_focus(normalized_seed)
            if anchor_context:
                snippets = [anchor_context]
        normalized_seed["resume_snippets"] = snippets[:3]
        next_focus_label = (
            str(seeds[(index + 1) % len(seeds)].get("label", "") or "").strip()
            if len(seeds) > 1
            else "another area from the candidate's background"
        )
        fallback_dim = _fallback_dimension_track(normalized_seed, next_focus_label)
        fallback_dims = fallback_dim.get("dimensions", [])
        focus_areas.append({
            "label": str(normalized_seed.get("label", "") or f"Focus Area {index + 1}").strip(),
            "focus_key": normalized_seed["focus_key"],
            "anchor_context": _anchor_context_for_focus(normalized_seed),
            "resume_snippets": list(normalized_seed.get("resume_snippets", [])[:3]),
            "track_source": "deterministic_fallback",
            "track_schema": "dimension",
            "llm_branch_count": 0,
            "fallback_branch_count": len(fallback_dims),
            "llm_branches": [],
            "fallback_branches": [d["id"] for d in fallback_dims],
            **fallback_dim,
        })

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    print(
        f"[TrajectoryMap] Built deterministic fallback with {len(focus_areas)} focus areas in {elapsed_ms}ms"
        + (f" for {session_id[:8]}" if session_id else "")
    )
    return {
        "focus_areas": focus_areas,
        "generated_at": time.time(),
        "source": "deterministic_fallback",
        "pending_hydration_focus_keys": [area["focus_key"] for area in focus_areas],
    }


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
    opener = ""
    if primary.get("tracks") and isinstance(primary["tracks"], list) and primary["tracks"]:
        opener = primary["tracks"][0].get("opener", "") or ""
    elif primary.get("opener"):
        opener = str(primary["opener"])
    if opener and len(opener.split()) > 30:
        warnings.append(f"Primary opener is too long ({len(opener.split())} words)")

    for fa in focus_areas:
        dims = fa.get("dimensions", []) or []
        for track in fa.get("tracks", []) or []:
            dims = dims + (track.get("dimensions", []) or [])
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
        is_dim_schema = schema_version == "dimension" or ("opener" in area or "dimensions" in area)
        focus_errors: list[str] = []

        if not label or not focus_key:
            focus_errors.append("missing label or focus key")
        if any(token in label.lower() for token in _RICH_MAP_BANNED_LABEL_TOKENS):
            focus_errors.append(f"label '{label}' looks like metadata noise")

        if is_dim_schema:
            # Validate new dimension schema
            opener = _clean_track_value(area.get("opener", ""))
            dims = area.get("dimensions", []) if isinstance(area.get("dimensions"), list) else []
            recovery = area.get("recovery", {}) if isinstance(area.get("recovery"), dict) else {}
            if not opener:
                focus_errors.append(f"{label}: opener missing")
            if len(dims) < 3:
                focus_errors.append(f"{label}: only {len(dims)} dimensions (need ≥3)")
            missing_recovery = sorted(_DIM_RECOVERY_REQUIRED - set(recovery.keys()))
            if missing_recovery:
                focus_errors.append(f"{label}: recovery missing fields: {', '.join(missing_recovery)}")
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
            is_rich = track_source == "llm" and opener and len(dims) >= 3 and not missing_recovery
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

    resume_focus = _resume_focus_source(resume) or resume
    target_keys = set(focus_keys or interview_map.get("pending_hydration_focus_keys", []) or [])
    if not target_keys:
        target_keys = {
            str(area.get("focus_key", "") or "")
            for area in focus_areas
            if str(area.get("track_source", "") or "") != "llm"
        }

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
            "resume_snippets": list(area.get("resume_snippets", []) or []),
        }
        result = await _generate_focus_track(
            resume_context=resume_focus,
            seed=seed,
            next_focus_label=next_focus_label,
            session_id=session_id,
            fast_mode=False,
        )
        if result.get("source") == "llm":
            track_data = result["track"]
            schema_v = "dimension" if ("opener" in track_data or "dimensions" in track_data) else "sprint"
            return index, {
                **area,
                "track_source": "llm",
                "track_schema": schema_v,
                "llm_branch_count": int(result.get("llm_branch_count", 0) or 0),
                "fallback_branch_count": int(result.get("fallback_branch_count", 0) or 0),
                "llm_branches": list(result.get("llm_branches", []) or []),
                "fallback_branches": list(result.get("fallback_branches", []) or []),
                **track_data,
            }
        return index, area  # source was fallback — keep original

    # Fire all pending hydrations in parallel
    hydration_results = await asyncio.gather(
        *[_hydrate_one(i, a) for i, a in pending_pairs],
        return_exceptions=True,
    )

    updated_focus_areas = list(focus_areas)
    hydrated_keys: list[str] = []
    for outcome in hydration_results:
        if isinstance(outcome, BaseException):
            print(f"[TrajectoryMap] Hydration task raised: {type(outcome).__name__}: {outcome}")
            continue
        index, updated_area = outcome
        updated_focus_areas[index] = updated_area
        if updated_area.get("track_source") == "llm":
            hydrated_keys.append(str(updated_area.get("focus_key", "") or ""))

    remaining = [
        str(area.get("focus_key", "") or "")
        for area in updated_focus_areas
        if str(area.get("track_source", "") or "") != "llm"
    ]
    return {
        **interview_map,
        "focus_areas": updated_focus_areas,
        "pending_hydration_focus_keys": remaining,
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
) -> dict | None:
    """Route a question from a dimension-schema focus area."""
    recovery = area.get("recovery", {})
    dims = area.get("dimensions", [])
    focus_key_out = str(area.get("focus_key", "") or "")
    focus_label_out = str(area.get("label", "") or "")

    def _ret(q: str, route: str, branch: str) -> dict | None:
        q = q.strip()
        if not q or _already_asked(q, history):
            return None
        return {"question": q, "route_kind": route, "focus_key": focus_key_out, "focus_label": focus_label_out, "branch": branch}

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

    search_groups = [current_matches, last_focus_matches, remaining]

    for group_index, group in enumerate(search_groups):
        if not group:
            continue
        for area in group:
            schema = str(area.get("track_schema", "") or "")
            is_dimension_schema = schema == "dimension" or ("opener" in area or "dimensions" in area)

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
                if schema == "dimension" or "opener" in area or "dimensions" in area:
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
