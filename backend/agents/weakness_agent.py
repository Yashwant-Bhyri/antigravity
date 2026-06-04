from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter

_VALID_WEAKNESS_TYPES = {
    "missing_step",
    "vague",
    "incorrect",
    "shallow",
    "overconfidence",
    "deflection",
    "ambiguous_but_promising",
}
_VALID_SEVERITIES = {"low", "medium", "high"}
_VALID_PROBE_DIRECTIONS = {
    "clarification",
    "implementation_probe",
    "ownership_probe",
    "edge_case",
    "scaling",
    "contradiction",
    "step_by_step",
}

_WEAKNESS_TYPE_ALIASES = {
    "none": "ambiguous_but_promising",
    "no_weakness": "ambiguous_but_promising",
    "no clear weakness": "ambiguous_but_promising",
    "valid": "ambiguous_but_promising",
    "strong": "ambiguous_but_promising",
    "good": "ambiguous_but_promising",
    "gap": "missing_step",
    "reasoning_gap": "missing_step",
    "conceptual_gap": "missing_step",
    "missing_context": "missing_step",
    "unsupported": "vague",
    "unsupported_claim": "vague",
    "unclear": "vague",
    "evasive": "deflection",
    "dodging": "deflection",
    "partially_answered": "ambiguous_but_promising",
}

_PROBE_DIRECTION_ALIASES = {
    "mechanism": "implementation_probe",
    "implementation": "implementation_probe",
    "ownership": "ownership_probe",
    "edge": "edge_case",
    "counterexample": "edge_case",
    "causal": "step_by_step",
    "causality": "step_by_step",
    "clarify": "clarification",
    "follow_up": "clarification",
}


PROMPT = """You are a technical interviewer analyzing a candidate's answer for reasoning gaps.

Do NOT validate or praise. Your job is to identify the most important next probe.
Sometimes that means exposing a weakness. Sometimes that means asking one clarification question
before escalating.

Weakness types:
- missing_step: they skipped a critical reasoning step or assumption
- vague: buzzwords without substance, no mechanism explained
- incorrect: technically wrong claim or broken logic
- shallow: surface-level answer that doesn't go deep enough
- overconfidence: claims certainty where there should be uncertainty or trade-offs
- deflection: they avoided the actual question, redirected, or talked around it
- ambiguous_but_promising: there may be real substance here, but it needs one clarification turn before attack

Probe directions (pick the one that will most illuminate the candidate's knowledge boundary):
- clarification: ask one exploratory clarifying question before escalating
- implementation_probe: ask them to implement or describe the mechanism step-by-step
- ownership_probe: pin down what they personally built versus what the team/system did
- edge_case: introduce a scenario that breaks their assumption
- scaling: increase the scale/load until their approach breaks
- contradiction: surface a contradiction between what they said and what's true
- step_by_step: force them to walk through reasoning explicitly

Severity:
- high: fundamental gap, incorrect claim, or completely vague — must be probed
- medium: incomplete or could go deeper — worth following up
- low: minor omission, acceptable for this sprint

IMPORTANT: If the candidate explicitly admits a gap, corrects their own previous claim, or shows high intellectual honesty (e.g., 'I actually mislabeled that, it was just prompt engineering'), set severity to 'medium' or 'low'. Intellectual honesty is a strength, not a weakness—do NOT punish it with a high-severity attack probe. Pick an 'implementation_probe' or 'step_by_step' to explore the NEW truth they just provided.

Calibration rules:
- Use the expected role, years of experience, and resume ownership signals to calibrate severity.
- If the candidate claims only internship / contributing / supporting ownership, do NOT hold them to the same ownership bar as someone claiming leadership or end-to-end architecture.
- Use `ownership_probe` when the main uncertainty is "what did YOU personally do?"
- Use `clarification` with `ambiguous_but_promising` when the answer hints at substance and deserves one clarifying question before confrontation.
- Use `deflection` when they do not seriously attempt the question.

Focus routing:
- If a list of active focus area keys is provided, set `inferred_focus_key` to the key whose label best matches what the candidate was answering about. Pick the closest match. If no focus areas are provided or none match, leave it as an empty string.

Output JSON only:
{
  "weakness": "<one sentence describing the specific gap>",
  "type": "missing_step | vague | incorrect | shallow | overconfidence | deflection | ambiguous_but_promising",
  "severity": "low | medium | high",
  "probe_direction": "clarification | implementation_probe | ownership_probe | edge_case | scaling | contradiction | step_by_step",
  "continue_probing": true,
  "inferred_focus_key": "<focus_key from the active area list, or empty string>"
}"""


class WeaknessAgent:
    """
    Core agent — THE most important agent in the system.
    Detects the exact failure point in the candidate's reasoning.
    Context-aware: uses sprint + previous weaknesses to avoid redundant probing.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def detect(
        self,
        question: str,
        answer: str,
        sprint: int = 1,
        prior_weaknesses: list[dict] | None = None,
        memory_context: str = "",
        parsed_resume: dict | None = None,
        target_role: str = "",
        years_experience: str = "",
        focus_areas: list[dict] | None = None,
    ) -> dict:
        """
        Detects weakness in the candidate's answer.
        Sprint context shifts what counts as 'high severity':
          Sprint 1: ownership gaps, vague project claims
          Sprint 2: conceptual gaps, incorrect fundamentals
          Sprint 3: system design holes, missing trade-offs
        """
        sprint_focus = {
            1: "Focus on: did they actually build this? Are they vague about their own contribution?",
            2: "Focus on: are they hand-waving fundamentals? Is reasoning mechanically correct?",
            3: "Focus on: are they ignoring trade-offs, failure modes, or scale implications?",
        }.get(sprint, "")

        prior_context = ""
        if prior_weaknesses:
            recent = prior_weaknesses[-3:]  # last 3 weaknesses
            typed = [f"{w.get('type', '')}({w.get('severity', '')})" for w in recent]
            prior_context = f"\nAlready probed: {', '.join(typed)}. Avoid redundant weakness detection."

        memory_section = f"\n\nCandidate context from prior turns:\n{memory_context}" if memory_context else ""
        parsed_resume = parsed_resume or {}
        experience_tier = parsed_resume.get("experience_tier", "")
        projects = parsed_resume.get("projects", [])
        experiences = parsed_resume.get("experiences", [])
        ownership_signals = []
        for project in projects[:3]:
            ownership_signals.append(
                f"{project.get('name', 'project')}: ownership={project.get('ownership_level', 'unknown')} contribution={project.get('contribution_type', 'contributed')}"
            )
        for exp in experiences[:2]:
            ownership_signals.append(
                f"{exp.get('title', 'role')} @ {exp.get('company', '')}: contribution={exp.get('contribution_type', 'contributed')}"
            )
        calibration_context = (
            f"\nExpected target role: {target_role or 'not provided'}"
            f"\nExpected years of experience: {years_experience or 'not provided'}"
            f"\nResume experience tier: {experience_tier or 'unknown'}"
        )
        if ownership_signals:
            calibration_context += "\nOwnership signals:\n- " + "\n- ".join(ownership_signals)
        prior_assessment_prompt = str(parsed_resume.get("prior_assessment_prompt", "") or "").strip()
        if prior_assessment_prompt:
            calibration_context += f"\nPrior assessment context:\n{prior_assessment_prompt[:1200]}"

        focus_context = ""
        if focus_areas:
            focus_list = "\n".join(
                f"  - key={fa.get('focus_key', '')}  label={fa.get('label', '')}"
                for fa in focus_areas
                if fa.get("focus_key")
            )
            if focus_list:
                focus_context = f"\nActive focus areas (for inferred_focus_key):\n{focus_list}"

        user = f"""Sprint {sprint} — {sprint_focus}{prior_context}{memory_section}
{calibration_context}{focus_context}

Question: {question}

Candidate Answer: {answer}"""

        result = await self.llm.call(system=PROMPT, user=user, response_format=JSON_OBJECT_FORMAT)
        if isinstance(result, dict):
            weakness_type = str(result.get("type", "")).strip().lower()
            severity = str(result.get("severity", "")).strip().lower()
            probe_direction = str(result.get("probe_direction", "")).strip().lower()
            weakness_type = _WEAKNESS_TYPE_ALIASES.get(weakness_type, weakness_type)
            probe_direction = _PROBE_DIRECTION_ALIASES.get(probe_direction, probe_direction)
            if weakness_type == "ambiguous_but_promising" and severity not in _VALID_SEVERITIES:
                severity = "low"
            if weakness_type not in _VALID_WEAKNESS_TYPES:
                result["_normalization_warning"] = f"invalid weakness type normalized: {weakness_type}"
                weakness_type = "ambiguous_but_promising"
                severity = severity if severity in _VALID_SEVERITIES else "low"
                probe_direction = probe_direction if probe_direction in _VALID_PROBE_DIRECTIONS else "clarification"
            if severity not in _VALID_SEVERITIES:
                result["_normalization_warning"] = f"invalid severity normalized: {severity}"
                severity = "medium"
            if probe_direction not in _VALID_PROBE_DIRECTIONS:
                result["_normalization_warning"] = f"invalid probe_direction normalized: {probe_direction}"
                probe_direction = "clarification"
            result["type"] = weakness_type
            result["severity"] = severity
            result["probe_direction"] = probe_direction
            result["weakness"] = str(result.get("weakness", "") or "").strip()
            result["continue_probing"] = bool(result.get("continue_probing", True))
            result["inferred_focus_key"] = str(result.get("inferred_focus_key", "") or "").strip()
            return result
        raise RuntimeError("WeaknessAgent returned non-JSON output.")
