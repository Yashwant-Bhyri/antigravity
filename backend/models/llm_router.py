import os
import json
from openai import AsyncOpenAI
from backend.config.env_runtime import model_tier


# Model routing tiers via OpenRouter
# OpenRouter model IDs: https://openrouter.ai/models
DEFAULT_MODEL_TIERS = {
    "small": "anthropic/claude-haiku-4-5",   # concept extraction, resume parsing
    "medium": "anthropic/claude-sonnet-4-6", # weakness detection, follow-ups
    "large": "deepseek/deepseek-r1",         # strongest reasoning/evaluation path for now
}

MODEL_TIERS = {
    tier: model_tier(tier, default_model)
    for tier, default_model in DEFAULT_MODEL_TIERS.items()
}

# Default max_tokens per tier. Interview-map generation now sends the full
# resume plus prior pass context, so the stronger tiers need much more room.
TIER_MAX_TOKENS = {
    "small": 512,
    "medium": 1800,
    "large": 7000,
}

TIER_TIMEOUT_SECONDS = {
    "small": 20.0,
    "medium": 75.0,
    "large": 180.0,
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
    - small  → lightweight extraction or utility tasks
    - medium → critique, follow-up generation, evaluation
    - large  → full-resume reasoning and rich map construction
    """

    def __init__(
        self,
        tier: str = "medium",
        *,
        model_override: str | None = None,
        timeout_override: float | None = None,
    ):
        assert tier in MODEL_TIERS, f"Unknown tier: {tier}. Choose from: {list(MODEL_TIERS.keys())}"
        self.tier = tier
        self.model = (model_override or MODEL_TIERS[tier]).strip()
        self.client = AsyncOpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
            timeout=timeout_override or TIER_TIMEOUT_SECONDS[tier],
        )

    async def call(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> dict | str:
        if max_tokens is None:
            max_tokens = TIER_MAX_TOKENS[self.tier]
        request_payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format:
            request_payload["response_format"] = response_format
        response = await self.client.chat.completions.create(**request_payload)
        text = response.choices[0].message.content or ""
        text = text.strip()

        # Strip reasoning model thinking blocks (<think>...</think>)
        import re as _re
        text = _re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

        # Try to parse as JSON; fall back to raw string
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Strip markdown code fences if present
            if "```" in text:
                fenced = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
                if fenced:
                    try:
                        return json.loads(fenced.group(1).strip())
                    except json.JSONDecodeError:
                        pass
            # Last resort: recover either a JSON array or object embedded in surrounding text.
            arr_match = _re.search(r"\[[\s\S]*\]", text)
            if arr_match:
                try:
                    return json.loads(arr_match.group(0))
                except json.JSONDecodeError:
                    pass
            obj_match = _re.search(r"\{[\s\S]*\}", text)
            if obj_match:
                try:
                    return json.loads(obj_match.group(0))
                except json.JSONDecodeError:
                    pass
            return text
