import os
import json
from openai import AsyncOpenAI


# Model routing tiers via OpenRouter
# OpenRouter model IDs: https://openrouter.ai/models
MODEL_TIERS = {
    "small": "anthropic/claude-haiku-4-5",      # concept extraction, resume parsing (~50ms)
    "medium": "anthropic/claude-sonnet-4-5",    # weakness detection, follow-ups (~200ms)
    "large": "anthropic/claude-opus-4-5",       # deep evaluation, scoring (~500ms)
}

# Alternative cheap/fast options for cost optimization:
# "small": "google/gemini-flash-1.5"
# "medium": "openai/gpt-4o-mini"
# "large": "openai/gpt-4o"


class LLMRouter:
    """
    Routes LLM calls to the right model tier via OpenRouter.
    OpenRouter is OpenAI API-compatible — one key, all models.

    Tiers:
    - small  → fast classification tasks (~50ms)
    - medium → follow-up generation, weakness detection (~200ms)
    - large  → deep evaluation, scoring (~500ms)
    """

    def __init__(self, tier: str = "medium"):
        assert tier in MODEL_TIERS, f"Unknown tier: {tier}. Choose from: {list(MODEL_TIERS.keys())}"
        self.model = MODEL_TIERS[tier]
        self.client = AsyncOpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )

    async def call(self, system: str, user: str, max_tokens: int = 512) -> dict | str:
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = response.choices[0].message.content.strip()

        # Try to parse as JSON; fall back to raw string
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Strip markdown code fences if present
            if text.startswith("```"):
                parts = text.split("```")
                if len(parts) >= 2:
                    inner = parts[1]
                    if inner.startswith("json"):
                        inner = inner[4:]
                    try:
                        return json.loads(inner.strip())
                    except json.JSONDecodeError:
                        pass
            return text
