from backend.models.llm_router import LLMRouter


PROMPT = """You are a meta-cognition evaluator.

Do NOT evaluate technical accuracy.
Evaluate HOW the candidate thinks and communicates.

Track:
1. Structure: Do they enumerate steps? ("First... Second...")
2. Clarification behavior: Do they ask for constraints before designing?
3. Adaptability: How do they react when their answer is challenged?
4. Confidence calibration: Are they overconfident or appropriately uncertain?

Return JSON:
{
  "structure_score": 0-3,
  "clarification_behavior": "asks | assumes | mixed",
  "adaptability": "flexible | rigid | defensive",
  "confidence_calibration": "calibrated | overconfident | underconfident",
  "notes": "..."
}
"""


class ReasoningBehaviorAgent:
    """
    Runs in parallel — evaluates meta-cognition, not technical accuracy.
    Captures HOW the candidate thinks, not just WHAT they answer.
    This feeds into the final hire recommendation.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def evaluate(self, answer: str, was_challenged: bool = False) -> dict:
        context = f"Candidate was challenged: {was_challenged}\n\nAnswer:\n{answer}"
        return await self.llm.call(system=PROMPT, user=context)
