"""
Contract checks for metadata-only LLM token usage auditing.

Run with:
  PYTHONPATH=. python3 backend/test_llm_usage_audit.py
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from backend.llm_quality_audit_report import build_quality_report
from backend.llm_token_audit_report import build_report
from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter, _extract_usage
from backend.services.llm_usage import load_quality_records, load_usage_records


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    async def create(self, **payload):
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("No fake response queued")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _response(content: str, usage: object | None = None) -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
    )


async def _run_json_retry_case(usage_dir: str, quality_dir: str) -> list[dict]:
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["LLM_USAGE_DIR"] = usage_dir
    os.environ["LLM_QUALITY_DIR"] = quality_dir
    os.environ["LLM_USAGE_AUDIT"] = "1"
    os.environ["LLM_QUALITY_AUDIT"] = "1"
    os.environ["LLM_QUALITY_CAPTURE_TEXT"] = "1"

    router = LLMRouter(tier="small", model_override="test/model")
    router.client = FakeClient([
        _response(
            "not json",
            SimpleNamespace(input_tokens=11, output_tokens=3),
        ),
        _response(
            '{"ok": true}',
            {"prompt_tokens": 17, "completion_tokens": 5, "total_tokens": 22},
        ),
    ])
    result = await router.call(
        "system SECRET_SYSTEM_TEXT",
        "user SECRET_RESUME_TEXT",
        max_tokens=20,
        response_format=JSON_OBJECT_FORMAT,
        audit_call_name="contract.retry_case",
        audit_session_id="session-123",
        audit_turn_id="turn-1",
    )
    assert result == {"ok": True}
    return load_usage_records(usage_dir)


async def _run_missing_usage_case(usage_dir: str, quality_dir: str) -> list[dict]:
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["LLM_USAGE_DIR"] = usage_dir
    os.environ["LLM_QUALITY_DIR"] = quality_dir
    os.environ["LLM_USAGE_AUDIT"] = "1"
    os.environ["LLM_QUALITY_AUDIT"] = "0"

    router = LLMRouter(tier="medium", model_override="test/missing-usage")
    router.client = FakeClient([_response("plain answer", None)])
    result = await router.call(
        "short system",
        "short user",
        max_tokens=100,
        audit_call_name="contract.missing_usage_case",
    )
    assert result == "plain answer"
    return load_usage_records(usage_dir)


def main() -> None:
    assert _extract_usage(_response("", SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5))) == {
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
    }
    assert _extract_usage(_response("", {"input_tokens": 7, "output_tokens": 4})) == {
        "prompt_tokens": 7,
        "completion_tokens": 4,
        "total_tokens": 11,
    }
    assert _extract_usage(_response("", None)) == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        usage_dir = str(Path(tmpdir) / "usage")
        quality_dir = str(Path(tmpdir) / "quality")
        records = asyncio.run(_run_json_retry_case(usage_dir, quality_dir))
        attempts = [record for record in records if record.get("event") == "llm_call_attempt"]
        aggregates = [record for record in records if record.get("event") == "llm_call"]
        assert len(attempts) == 2
        assert len(aggregates) == 1
        assert attempts[0]["actual_prompt_tokens"] == 11
        assert attempts[0]["actual_completion_tokens"] == 3
        assert attempts[1]["actual_prompt_tokens"] == 17
        assert attempts[1]["actual_completion_tokens"] == 5
        assert attempts[1]["retry_reason"] == "json_parse_failed"
        assert aggregates[0]["retried"] is True
        assert aggregates[0]["retry_succeeded"] is True
        assert aggregates[0]["billable_prompt_tokens"] == 28
        assert aggregates[0]["billable_completion_tokens"] == 8
        dumped = json.dumps(records)
        assert "SECRET_RESUME_TEXT" not in dumped
        assert "SECRET_SYSTEM_TEXT" not in dumped

        report = build_report(records)
        assert report["summary"]["calls"] == 1
        assert report["summary"]["retry_attempts"] == 1
        assert report["summary"]["billable_total_tokens"] == 36
        assert report["by_model"]["test/model"]["calls"] == 1
        quality_records = load_quality_records(quality_dir)
        quality_attempts = [record for record in quality_records if record.get("event") == "llm_quality_attempt"]
        quality_calls = [record for record in quality_records if record.get("event") == "llm_quality_call"]
        assert len(quality_attempts) == 2
        assert len(quality_calls) == 1
        assert quality_attempts[0]["system_prompt"] == "system SECRET_SYSTEM_TEXT"
        assert quality_attempts[0]["user_prompt"] == "user SECRET_RESUME_TEXT"
        assert quality_attempts[0]["cleaned_output"] == "not json"
        assert "json_parse_failed" in quality_attempts[0]["flags"]
        assert quality_calls[0]["final_value"] == {"ok": True}
        quality_report = build_quality_report(quality_records, records)
        assert quality_report["summary"]["quality_attempt_records"] == 2
        assert quality_report["summary"]["parse_failures"] == 1
        assert quality_report["by_agent_family"]["Other"]["call_ids"] == 1

    with tempfile.TemporaryDirectory() as tmpdir:
        usage_dir = str(Path(tmpdir) / "usage")
        quality_dir = str(Path(tmpdir) / "quality")
        records = asyncio.run(_run_missing_usage_case(usage_dir, quality_dir))
        aggregate = [record for record in records if record.get("event") == "llm_call"][0]
        assert aggregate["usage_source"] == "estimate"
        assert aggregate["billable_total_tokens"] > 0
        assert load_quality_records(quality_dir) == []

    print("llm usage audit checks passed")


if __name__ == "__main__":
    main()
