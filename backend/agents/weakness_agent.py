from backend.models.llm_router import LLMRouter


PROMPT = """You are an expert technical interviewer.

Your job is NOT to validate answers.
Your job is to identify weaknesses.

Given:
- Question
- Candidate Answer

Identify:
1. Missing steps in reasoning
2. Vague or buzzword-heavy responses
3. Incorrect assumptions
4. Unexplained concepts
5. Potential edge cases ignored

Output JSON:
{
  "weakness": "...",
  "type": "missing_step | vague | incorrect | shallow",
  "severity": "low | medium | high",
  "attack_strategy": "implementation_probe | edge_case | scaling | contradiction"
}
"""


class WeaknessAgent:
    """
    Core agent — THE most important agent in the system.
    Detects the exact failure point in the candidate's reasoning.
    Uses a medium model — latency target: ~100ms.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def detect(self, question: str, answer: str) -> dict:
        result = await self.llm.call(
            system=PROMPT,
            user=f"Question: {question}\n\nCandidate Answer: {answer}",
        )
        return result
