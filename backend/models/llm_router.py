import os
import json
from anthropic import AsyncAnthropic


# Model routing tiers — small for speed, large for depth
MODEL_TIERS = {
    "small": "claude-haiku-4-5-20251001",   # concept extraction, resume parsing
    "medium": "claude-sonnet-4-6",           # weakness detection, follow-ups
    "large": "claude-opus-4-6",              # deep reasoning, evaluation
}


class LLMRouter:
    """
    Routes LLM calls to the right model tier based on task complexity.
    - small  → fast classification tasks (~50ms)
    - medium → follow-up generation, weakness detection (~100-200ms)
    - large  → deep evaluation, scoring (~300-500ms)
    """

    def __init__(self, tier: str = "medium"):
        assert tier in MODEL_TIERS, f"Unknown tier: {tier}"
        self.model = MODEL_TIERS[tier]
        self.client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    async def call(self, system: str, user: str) -> dict | str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text.strip()

        # Try to parse as JSON; fall back to raw string
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError:
                return text
