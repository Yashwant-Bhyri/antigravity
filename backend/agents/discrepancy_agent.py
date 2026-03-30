from backend.models.llm_router import LLMRouter


PROMPT = """Compare:
- Resume claims
- Candidate explanation

Detect inconsistencies between what the candidate claims to have built/know
and what they actually demonstrate in their answer.

Output JSON:
{
  "conflict": true/false,
  "description": "...",
  "severity": "low | high"
}
"""


class DiscrepancyAgent:
    """
    Cross-verifies what candidate claims on resume vs what they explain.
    Flags bluffing, resume inflation, and knowledge gaps.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def check(self, resume: str, answer: str) -> dict:
        return await self.llm.call(
            system=PROMPT,
            user=f"Resume:\n{resume}\n\nCandidate Explanation:\n{answer}",
        )
