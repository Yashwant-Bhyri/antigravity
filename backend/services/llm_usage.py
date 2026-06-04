from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


_LLM_USAGE_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "llm_usage_context",
    default={},
)


def _truthy_env(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def estimate_text_tokens(text: str) -> int:
    """
    Cheap metadata-only estimate used when provider usage is absent.

    This is intentionally conservative and dependency-free. Exact accounting comes
    from provider usage metadata when OpenRouter returns it.
    """
    if not text:
        return 0
    return max(1, int(math.ceil(len(text) / 4)))


def text_hash(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:24]


def current_llm_usage_context() -> dict[str, Any]:
    return dict(_LLM_USAGE_CONTEXT.get() or {})


@contextlib.contextmanager
def llm_usage_context(**fields: Any) -> Iterator[None]:
    """
    Attach session/run metadata to all LLM calls made in this async context.

    Context vars are copied into asyncio tasks at creation time, which lets the
    orchestrator tag background-agent calls without changing every agent method.
    """
    base = current_llm_usage_context()
    merged = dict(base)
    for key, value in fields.items():
        if value is not None and value != "":
            merged[key] = value
    token = _LLM_USAGE_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LLM_USAGE_CONTEXT.reset(token)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value[:25]]
    if isinstance(value, dict):
        return {str(k)[:80]: _json_safe(v) for k, v in list(value.items())[:50]}
    return str(value)[:500]


class LLMUsageLogger:
    """Append-only JSONL logger for metadata-only LLM token accounting."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    def enabled(self) -> bool:
        return _truthy_env(os.environ.get("LLM_USAGE_AUDIT"), default=True)

    def _resolve_root(self) -> Path:
        configured = (os.environ.get("LLM_USAGE_DIR") or "").strip()
        if configured:
            return Path(configured).expanduser()
        if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
            return Path("/tmp/llm_usage")
        return Path(__file__).resolve().parents[1] / "runtime" / "llm_usage"

    def usage_path(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._resolve_root() / f"{day}.jsonl"

    def _append_record(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")

    async def log(self, event: str, **fields: Any) -> dict[str, Any]:
        if not self.enabled():
            return {}
        context = current_llm_usage_context()
        record = {
            "ts": round(time.time(), 3),
            "iso_ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **{key: _json_safe(value) for key, value in context.items()},
            **{key: _json_safe(value) for key, value in fields.items()},
        }
        try:
            async with self._lock:
                await asyncio.to_thread(self._append_record, self.usage_path(), record)
        except Exception:
            # Token auditing must never break the live interview path.
            return {}
        return record


def load_usage_records(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = Path(root).expanduser() if root else llm_usage_logger._resolve_root()
    if base.is_file():
        paths = [base]
    else:
        paths = sorted(base.glob("*.jsonl"))
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        records.append(parsed)
        except FileNotFoundError:
            continue
    return records


llm_usage_logger = LLMUsageLogger()


class LLMQualityLogger:
    """
    Opt-in full-fidelity LLM prompt/result logger for controlled debugging runs.

    This intentionally lives beside, not inside, the metadata token logger. Enable
    only when inspecting prompt quality or corrupted/redundant call behavior.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    def enabled(self) -> bool:
        return _truthy_env(os.environ.get("LLM_QUALITY_AUDIT"), default=False)

    def capture_text(self) -> bool:
        # Full text capture is allowed only after the explicit quality audit is on.
        return self.enabled() and _truthy_env(os.environ.get("LLM_QUALITY_CAPTURE_TEXT"), default=True)

    def _resolve_root(self) -> Path:
        configured = (os.environ.get("LLM_QUALITY_DIR") or "").strip()
        if configured:
            return Path(configured).expanduser()
        if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
            return Path("/tmp/llm_quality")
        return Path(__file__).resolve().parents[1] / "runtime" / "llm_quality"

    def quality_path(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._resolve_root() / f"{day}.jsonl"

    def _append_record(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")

    async def log(self, event: str, **fields: Any) -> dict[str, Any]:
        if not self.enabled():
            return {}
        context = current_llm_usage_context()
        record = {
            "ts": round(time.time(), 3),
            "iso_ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **{key: _json_safe(value) for key, value in context.items()},
            **fields,
        }
        try:
            async with self._lock:
                await asyncio.to_thread(self._append_record, self.quality_path(), record)
        except Exception:
            # Quality capture is diagnostic only; never break the product path.
            return {}
        return record


def load_quality_records(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = Path(root).expanduser() if root else llm_quality_logger._resolve_root()
    if base.is_file():
        paths = [base]
    else:
        paths = sorted(base.glob("*.jsonl"))
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        records.append(parsed)
        except FileNotFoundError:
            continue
    return records


llm_quality_logger = LLMQualityLogger()
