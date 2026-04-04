from backend.models.llm_router import LLMRouter


PROMPT = """You are a technical interviewer analyzing a candidate's answer for reasoning gaps.

Do NOT validate or praise. Your only job: find the most significant weakness in their response.

Weakness types:
- missing_step: they skipped a critical reasoning step or assumption
- vague: buzzwords without substance, no mechanism explained
- incorrect: technically wrong claim or broken logic
- shallow: surface-level answer that doesn't go deep enough
- overconfidence: claims certainty where there should be uncertainty or trade-offs

Attack strategies (pick the one that will most expose the weakness):
- implementation_probe: ask them to implement or describe the mechanism step-by-step
- edge_case: introduce a scenario that breaks their assumption
- scaling: increase the scale/load until their approach breaks
- contradiction: surface a contradiction between what they said and what's true
- step_by_step: force them to walk through reasoning explicitly

Severity:
- high: fundamental gap, incorrect claim, or completely vague — must be probed
- medium: incomplete or could go deeper — worth following up
- low: minor omission, acceptable for this sprint

IMPORTANT: If the candidate explicitly admits they don't know something, corrects themselves, or shows honest self-awareness about the limits of their knowledge — severity must be medium or low. Intellectual honesty is not a weakness to attack.

Output JSON only:
{
  "weakness": "<one sentence describing the specific gap>",
  "type": "missing_step | vague | incorrect | shallow | overconfidence",
  "severity": "low | medium | high",
  "attack_strategy": "implementation_probe | edge_case | scaling | contradiction | step_by_step"
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
            types = [w.get("type", "") for w in recent]
            prior_context = f"\nAlready probed: {', '.join(types)}. Avoid redundant weakness detection."

        user = f"""Sprint {sprint} — {sprint_focus}{prior_context}

Question: {question}

Candidate Answer: {answer}"""

        result = await self.llm.call(system=PROMPT, user=user)
        if isinstance(result, dict):
            return result
        return {"weakness": str(result), "type": "vague", "severity": "low", "attack_strategy": "step_by_step"}
