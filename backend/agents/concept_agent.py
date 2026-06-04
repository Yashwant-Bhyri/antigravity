from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter


PROMPT = """You are a concept extraction engine.

Input:
- Candidate answer

Output:
- List of key technical concepts mentioned
- Ignore filler words

Return JSON: {"concepts": [...]}
"""


class ConceptAgent:
    """
    Extracts technical concepts from a candidate's answer.
    Runs in parallel at the start of every turn.
    Uses a small/fast model — latency target: ~50ms.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="small")

    async def extract(self, answer: str) -> list[str]:
        result = await self.llm.call(
            system=PROMPT,
            user=f"Candidate answer: {answer}",
            response_format=JSON_OBJECT_FORMAT,
        )
        if isinstance(result, dict):
            concepts = result.get("concepts", [])
        elif isinstance(result, list):
            concepts = result
        else:
            raise RuntimeError("ConceptAgent returned non-JSON output.")
        if not isinstance(concepts, list):
            raise RuntimeError("ConceptAgent output key 'concepts' must be a list.")
        return [str(concept).strip() for concept in concepts if str(concept).strip()]
