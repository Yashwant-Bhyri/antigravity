from backend.models.llm_router import LLMRouter


PROMPT = """You are a senior technical interviewer.

Given:
- Question
- Candidate Answer
- Detected Weakness

Generate ONE follow-up question that:
- targets the weakness directly
- does NOT give hints
- increases cognitive load
- forces deeper reasoning

Do not explain anything. Only output the question.
"""

STRATEGY_MAP = {
    "missing_step": "implementation_probe",
    "vague": "step_by_step",
    "incorrect": "contradiction",
    "shallow": "edge_case",
    "overconfidence": "scaling",
}


class FollowUpAgent:
    """
    Generates the next probing question based on detected weakness.
    Selects attack strategy from weakness type.
    Uses a medium model.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def generate(self, question: str, answer: str, weakness: dict) -> str:
        result = await self.llm.call(
            system=PROMPT,
            user=(
                f"Question: {question}\n\n"
                f"Answer: {answer}\n\n"
                f"Weakness: {weakness.get('weakness', '')}\n"
                f"Strategy: {weakness.get('attack_strategy', 'general_probe')}"
            ),
        )
        return result if isinstance(result, str) else result.get("followup", "")

    async def get_precomputed(self, state: dict) -> str:
        # TODO: pull from RAG question bank based on current sprint + skills
        sprint = state.get("current_sprint", 1)
        return f"[Precomputed question for sprint {sprint}]"

    async def prefetch(self, concepts: list[str], state: dict) -> list[str]:
        """
        Speculatively generate follow-ups for detected concepts while candidate
        is still speaking. Called from on_partial_transcript for latency masking.
        Returns a list so orchestrator can pick the best one after final transcript.
        """
        if not concepts:
            return []

        prompt = (
            f"Candidate is discussing: {', '.join(concepts[:3])}.\n"
            f"Generate 2 short probing follow-up questions that target likely weak spots. "
            f"Output JSON: {{\"questions\": [\"...\", \"...\"]}}"
        )
        result = await self.llm.call(
            system="You are a senior technical interviewer. Be concise.",
            user=prompt,
        )
        if isinstance(result, dict):
            return result.get("questions", [])
        return []
