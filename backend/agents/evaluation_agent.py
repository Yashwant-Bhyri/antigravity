from backend.models.llm_router import LLMRouter


PROMPT = """Evaluate the candidate's answer based on:

1. Problem framing (0-2)
2. Logical reasoning (0-3)
3. Technical correctness (0-3)
4. Production awareness (0-2)

Weights: Reasoning > Correctness > Depth > Communication

Return JSON:
{
  "score": X,
  "breakdown": {
    "problem_framing": X,
    "logical_reasoning": X,
    "technical_correctness": X,
    "production_awareness": X
  },
  "confidence": 0.0-1.0
}
"""


class EvaluationAgent:
    """
    Multi-pass scorer. Runs 3 evaluations and averages to reduce LLM inconsistency.
    Uses a large model for accuracy.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="large")

    async def score(self, question: str, answer: str) -> dict:
        # Multi-pass scoring for stability
        import asyncio
        scores = await asyncio.gather(
            self._score_once(question, answer),
            self._score_once(question, answer),
            self._score_once(question, answer),
        )
        avg_score = sum(s.get("score", 0) for s in scores) / len(scores)
        return {
            "score": round(avg_score, 2),
            "passes": scores,
        }

    async def _score_once(self, question: str, answer: str) -> dict:
        return await self.llm.call(
            system=PROMPT,
            user=f"Question: {question}\n\nAnswer: {answer}",
        )
