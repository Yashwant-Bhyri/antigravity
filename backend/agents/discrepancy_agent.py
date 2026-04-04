from backend.models.llm_router import LLMRouter


PROMPT = """Compare:
- Resume claims
- Candidate explanation

Detect inconsistencies between what the candidate claims to have built/know
and what they actually demonstrate in their answer.

IMPORTANT: If prior turns have already confirmed that a particular project or claim is
credible (listed in "Already established as true"), do NOT re-flag it as a conflict.
A candidate describing the same project across multiple turns is normal interview behavior,
not a discrepancy. Only flag genuinely new contradictions.

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
    Memory context prevents re-flagging claims already confirmed in prior turns.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def check(self, resume: str, answer: str, memory_context: str = "") -> dict:
        memory_section = f"\n\n{memory_context}" if memory_context else ""
        return await self.llm.call(
            system=PROMPT,
            user=f"Resume:\n{resume}{memory_section}\n\nCandidate Explanation:\n{answer}",
        )
