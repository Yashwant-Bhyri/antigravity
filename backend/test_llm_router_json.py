"""
Contract checks for lenient LLM JSON parsing.

Run with:
  PYTHONPATH=. python3 backend/test_llm_router_json.py
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from backend.models.llm_router import _load_json_lenient
from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter


class _FakeCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true, "source": "retry"}'))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_lenient_local_json_parser() -> None:
    assert _load_json_lenient('prefix {"ready": true, "issues": []}') == {
        "ready": True,
        "issues": [],
    }
    assert _load_json_lenient('prefix ["a", "b"]') == ["a", "b"]

    malformed_outer_object = '''
```json
{
  "ready": true,
  "strengths": [
    "good opener",
    "good dimensions"
  ],
  "issues": [
    "truncated outer object"
  ]
'''
    assert _load_json_lenient(malformed_outer_object) == {
        "ready": True,
        "strengths": ["good opener", "good dimensions"],
        "issues": ["truncated outer object"],
    }

    # Do not let json-repair invent an object from non-object garbage.
    assert _load_json_lenient('prefix {bad json ["nested"]') is None

    valid_fenced_object = '''
```json
{
  "ready": true,
  "strengths": ["good opener"]
}
```
'''
    assert _load_json_lenient(valid_fenced_object) == {
        "ready": True,
        "strengths": ["good opener"],
    }


async def test_json_response_retries_after_provider_decode_error() -> None:
    router = LLMRouter.__new__(LLMRouter)
    router.tier = "small"
    router.model = "fake/provider"
    router.client = _FakeClient()
    result = await router.call(
        system="Return JSON.",
        user="Return {ok:true}.",
        response_format=JSON_OBJECT_FORMAT,
        audit_call_name="test_json_response_retries_after_provider_decode_error",
    )
    assert result == {"ok": True, "source": "retry"}
    assert router.client.chat.completions.calls == 2


async def main() -> None:
    test_lenient_local_json_parser()
    await test_json_response_retries_after_provider_decode_error()
    print("llm-router JSON parser checks passed")


if __name__ == "__main__":
    asyncio.run(main())
