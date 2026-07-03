import os
import json
import sys
import time
import uuid
from typing import Any
from openai import AsyncOpenAI
from backend.config.env_runtime import env_first, model_tier
from backend.services.llm_usage import estimate_text_tokens, llm_quality_logger, llm_usage_logger, text_hash


# Model routing tiers via OpenRouter
# OpenRouter model IDs: https://openrouter.ai/models
DEFAULT_MODEL_TIERS = {
    "small": "anthropic/claude-haiku-4.5",    # concept extraction, resume parsing
    "medium": "anthropic/claude-sonnet-4.6",  # weakness detection, follow-ups
    "large": "deepseek/deepseek-v4-pro",      # cost-capped evaluation default; do not default to Opus
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

JSON_OBJECT_FORMAT = {"type": "json_object"}

CEREBRAS_NATIVE_MODEL_PREFIXES = (
    "gpt-oss-",
    "gemma-4-",
)


def _strip_provider_prefix(model: str) -> str:
    cleaned = str(model or "").strip()
    if "/" in cleaned:
        return cleaned.rsplit("/", 1)[-1].strip()
    return cleaned


def _is_cerebras_native_model(model: str) -> bool:
    local_name = _strip_provider_prefix(model).lower()
    return any(local_name.startswith(prefix) for prefix in CEREBRAS_NATIVE_MODEL_PREFIXES)


def _openrouter_fallback_model_for_cerebras_native(model: str) -> str:
    cleaned = str(model or "").strip()
    local_name = _strip_provider_prefix(cleaned)
    if "/" in cleaned and not local_name.lower().startswith("gemma-4-"):
        return cleaned
    if local_name.lower().startswith("gpt-oss-"):
        return f"openai/{local_name}"
    if local_name.lower().startswith("gemma-4-"):
        return os.environ.get("OPENROUTER_GEMMA_4_FALLBACK_MODEL", "").strip()
    return cleaned


def _env_flag(*names: str) -> bool:
    value = env_first(*names, default="").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _get_attr_or_key(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _extract_usage(response: Any) -> dict[str, int | None]:
    usage = _get_attr_or_key(response, "usage")
    prompt_tokens = _get_attr_or_key(usage, "prompt_tokens")
    completion_tokens = _get_attr_or_key(usage, "completion_tokens")
    total_tokens = _get_attr_or_key(usage, "total_tokens")

    # Some provider payloads use Anthropic-style naming when proxied.
    if prompt_tokens is None:
        prompt_tokens = _get_attr_or_key(usage, "input_tokens")
    if completion_tokens is None:
        completion_tokens = _get_attr_or_key(usage, "output_tokens")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = int(prompt_tokens) + int(completion_tokens)

    def _int_or_none(raw: Any) -> int | None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return {
        "prompt_tokens": _int_or_none(prompt_tokens),
        "completion_tokens": _int_or_none(completion_tokens),
        "total_tokens": _int_or_none(total_tokens),
    }


def _response_format_label(response_format: dict | None) -> str:
    if not response_format:
        return ""
    if isinstance(response_format, dict):
        return str(response_format.get("type") or "dict")
    return type(response_format).__name__


def _parsed_shape(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _quality_flags(
    *,
    raw_text: str,
    cleaned_text: str,
    parsed: Any,
    response_format: dict | None,
    error_type: str = "",
) -> list[str]:
    flags: list[str] = []
    stripped = cleaned_text.strip()
    if error_type:
        flags.append("provider_error")
    if not stripped:
        flags.append("empty_output")
    if "<think>" in raw_text:
        flags.append("reasoning_block_stripped")
    if raw_text.strip().startswith("```") or "```" in raw_text:
        flags.append("markdown_fence")
    if response_format and parsed is None:
        flags.append("json_parse_failed")
    if response_format and stripped and not stripped.startswith(("{", "[")):
        flags.append("non_json_prefix")
    if stripped.endswith((",", "[", "{")):
        flags.append("likely_truncated")
    if parsed is None and response_format and stripped.count("{") != stripped.count("}"):
        flags.append("brace_mismatch")
    if parsed is None and response_format and stripped.count("[") != stripped.count("]"):
        flags.append("bracket_mismatch")
    return flags


def _safe_audit_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in list((metadata or {}).items())[:30]:
        clean_key = str(key)[:80]
        if value is None or isinstance(value, (bool, int, float)):
            safe[clean_key] = value
        elif isinstance(value, str):
            safe[clean_key] = {"chars": len(value), "hash": text_hash(value)}
        else:
            safe[clean_key] = {"type": type(value).__name__}
    return safe


def _detect_call_site() -> str:
    frame = sys._getframe(1)
    while frame:
        filename = frame.f_code.co_filename.replace("\\", "/")
        if not filename.endswith("/backend/models/llm_router.py"):
            module = frame.f_globals.get("__name__", "")
            return f"{module}.{frame.f_code.co_name}:{frame.f_lineno}"
        frame = frame.f_back
    return "unknown"


def _detect_stack_context() -> dict[str, str]:
    frame = sys._getframe(1)
    context = {"call_site": "unknown", "session_id": "", "turn_id": ""}
    while frame:
        filename = frame.f_code.co_filename.replace("\\", "/")
        if not filename.endswith("/backend/models/llm_router.py"):
            if context["call_site"] == "unknown":
                module = frame.f_globals.get("__name__", "")
                context["call_site"] = f"{module}.{frame.f_code.co_name}:{frame.f_lineno}"
            if not context["session_id"]:
                raw_session_id = frame.f_locals.get("session_id")
                if isinstance(raw_session_id, str):
                    context["session_id"] = raw_session_id
            if not context["turn_id"]:
                raw_turn_id = frame.f_locals.get("turn_id")
                if isinstance(raw_turn_id, str):
                    context["turn_id"] = raw_turn_id
        if context["call_site"] != "unknown" and context["session_id"] and context["turn_id"]:
            break
        frame = frame.f_back
    return context


def _load_json_lenient(text: str) -> dict | list | None:
    """
    Parse model-authored JSON without inventing content.

    Some providers, Gemini 3.5 Flash in particular, produce strong JSON-shaped
    content with harmless wrapper noise: markdown fences without a closing fence,
    or one extra trailing brace after the real object. We still fail closed on
    invalid content, but we should not reject a valid first JSON value just
    because the provider added syntactic dust after it.
    """
    cleaned = text.strip()
    if not cleaned:
        return None

    if cleaned.startswith("```"):
        import re as _re
        cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned).strip()
        cleaned = _re.sub(r"\s*```$", "", cleaned).strip()

    decoder = json.JSONDecoder()
    for candidate in (cleaned,):
        try:
            value, end = decoder.raw_decode(candidate)
            trailing = candidate[end:].strip()
            if not trailing or set(trailing) <= {"`", "}"}:
                return value
        except json.JSONDecodeError:
            pass

    object_start = cleaned.find("{")
    array_start = cleaned.find("[")
    start_positions: list[int] = []
    if object_start != -1 and (array_start == -1 or object_start < array_start):
        # If the model began a JSON object but malformed/truncated it, do not
        # accidentally parse a nested array such as "strengths" as the whole
        # response. Callers need the contract failure, not a plausible fragment.
        start_positions = [object_start]
    elif array_start != -1:
        start_positions = [array_start]
    for start in start_positions:
        fragment = cleaned[start:]
        try:
            value, _ = decoder.raw_decode(fragment)
            return value
        except json.JSONDecodeError:
            continue
        except ValueError:
            continue

    # Last local recovery layer before asking another model to reformat. This
    # repairs syntax only; the caller still validates the contract/schema.
    for start in start_positions:
        fragment = cleaned[start:]
        try:
            from json_repair import loads as _repair_json_loads

            repaired = _repair_json_loads(fragment)
        except Exception:
            continue
        if object_start != -1 and start == object_start and isinstance(repaired, dict):
            import re as _re

            # Avoid turning arbitrary bracket noise into invented object keys.
            # Local repair is only acceptable when the original text already
            # shows object-style key/value intent.
            if not _re.search(r'"[^"\\]{1,120}"\s*:', fragment):
                continue
            return repaired
        if array_start != -1 and start == array_start and isinstance(repaired, (dict, list)):
            return repaired
    return None

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
        requested_model = (model_override or MODEL_TIERS[tier]).strip()
        backend_name = env_first("LLM_ROUTER_BACKEND", default="openrouter").strip().lower()
        auto_cerebras_native = (
            _is_cerebras_native_model(requested_model)
            and bool(os.environ.get("CEREBRAS_API_KEY", "").strip())
            and not _env_flag("LLM_ROUTER_DISABLE_CEREBRAS_NATIVE_AUTO")
        )
        self.openrouter_fallback_model = _openrouter_fallback_model_for_cerebras_native(requested_model)
        self.backend = "cerebras_direct" if auto_cerebras_native else (backend_name or "openrouter")
        self.model = (
            _strip_provider_prefix(requested_model)
            if self.backend in {"cerebras", "cerebras_direct", "direct_cerebras"}
            else (
                self.openrouter_fallback_model
                if _is_cerebras_native_model(requested_model)
                else requested_model
            )
        )
        if self.backend in {"cerebras", "cerebras_direct", "direct_cerebras"}:
            api_key_name = "CEREBRAS_API_KEY"
            base_url = env_first("LLM_ROUTER_BASE_URL", "CEREBRAS_BASE_URL", default="https://api.cerebras.ai/v1")
            self._token_param = "max_completion_tokens"
        else:
            api_key_name = "OPENROUTER_API_KEY"
            base_url = env_first("LLM_ROUTER_BASE_URL", "OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")
            self._token_param = "max_tokens"
        self.client = AsyncOpenAI(
            api_key=os.environ[api_key_name],
            base_url=base_url,
            timeout=timeout_override or TIER_TIMEOUT_SECONDS[tier],
        )

    async def call(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        audit_call_name: str | None = None,
        audit_session_id: str | None = None,
        audit_turn_id: str | None = None,
        audit_metadata: dict | None = None,
    ) -> dict | str:
        if max_tokens is None:
            max_tokens = TIER_MAX_TOKENS[self.tier]
        call_id = uuid.uuid4().hex
        stack_context = _detect_stack_context()
        call_site = audit_call_name or stack_context["call_site"]
        audit_session_id = audit_session_id or stack_context["session_id"]
        audit_turn_id = audit_turn_id or stack_context["turn_id"]
        response_format_name = _response_format_label(response_format)
        audit_metadata = _safe_audit_metadata(audit_metadata if isinstance(audit_metadata, dict) else {})
        quality_capture_text = llm_quality_logger.capture_text()
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request_payload[self._token_param] = max_tokens
        if self.backend in {"cerebras", "cerebras_direct", "direct_cerebras"}:
            request_payload["temperature"] = 0
            request_payload["seed"] = 0
        if response_format:
            request_payload["response_format"] = response_format
        import re as _re

        async def _attempt(
            payload: dict,
            *,
            attempt_number: int,
            retry_reason: str = "",
        ) -> tuple[str, dict | list | None, dict[str, Any], Exception | None]:
            started = time.perf_counter()
            error_type = ""
            error_message = ""
            response = None
            raw_text = ""
            cleaned_text = ""
            parsed: dict | list | None = None
            attempt_record: dict[str, Any] = {}
            captured_exc: Exception | None = None
            try:
                response = await self.client.chat.completions.create(**payload)
                raw_text = response.choices[0].message.content or ""
                cleaned_text = _re.sub(r"<think>[\s\S]*?</think>", "", raw_text.strip()).strip()
                parsed = _load_json_lenient(cleaned_text)
            except Exception as exc:
                captured_exc = exc
                error_type = type(exc).__name__
                error_message = str(exc)[:500]
            finally:
                elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                usage = _extract_usage(response)
                messages = payload.get("messages", [])
                system_text = str((messages[0] or {}).get("content", "")) if len(messages) > 0 else ""
                user_text = str((messages[1] or {}).get("content", "")) if len(messages) > 1 else ""
                estimated_prompt_tokens = estimate_text_tokens(system_text) + estimate_text_tokens(user_text)
                estimated_completion_tokens = estimate_text_tokens(cleaned_text)
                actual_prompt_tokens = usage.get("prompt_tokens")
                actual_completion_tokens = usage.get("completion_tokens")
                actual_total_tokens = usage.get("total_tokens")
                billable_prompt_tokens = actual_prompt_tokens if actual_prompt_tokens is not None else estimated_prompt_tokens
                billable_completion_tokens = (
                    actual_completion_tokens
                    if actual_completion_tokens is not None
                    else estimated_completion_tokens
                )
                billable_total_tokens = (
                    actual_total_tokens
                    if actual_total_tokens is not None
                    else estimated_prompt_tokens + estimated_completion_tokens
                )
                attempt_record = {
                    "max_tokens_requested": int(payload.get("max_completion_tokens") or payload.get("max_tokens") or 0),
                    "system_chars": len(system_text),
                    "user_chars": len(user_text),
                    "output_chars": len(cleaned_text),
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                    "estimated_completion_tokens": estimated_completion_tokens,
                    "estimated_total_tokens": estimated_prompt_tokens + estimated_completion_tokens,
                    "actual_prompt_tokens": actual_prompt_tokens,
                    "actual_completion_tokens": actual_completion_tokens,
                    "actual_total_tokens": actual_total_tokens,
                    "billable_prompt_tokens": billable_prompt_tokens,
                    "billable_completion_tokens": billable_completion_tokens,
                    "billable_total_tokens": billable_total_tokens,
                    "usage_source": "provider" if actual_total_tokens is not None else "estimate",
                    "elapsed_ms": elapsed_ms,
                    "success": not error_type,
                    "error_type": error_type,
                    "error": error_message,
                }
                flags = _quality_flags(
                    raw_text=raw_text,
                    cleaned_text=cleaned_text,
                    parsed=parsed,
                    response_format=response_format,
                    error_type=error_type,
                )
                attempt_record["quality_flags"] = flags
                await llm_usage_logger.log(
                    "llm_call_attempt",
                    call_id=call_id,
                    attempt_number=attempt_number,
                    retry_reason=retry_reason,
                    call_site=call_site,
                    session_id=audit_session_id or "",
                    turn_id=audit_turn_id or "",
                    tier=self.tier,
                    model=self.model,
                    max_tokens_requested=int(payload.get("max_completion_tokens") or payload.get("max_tokens") or 0),
                    response_format=response_format_name,
                    system_chars=len(system_text),
                    user_chars=len(user_text),
                    output_chars=len(cleaned_text),
                    estimated_prompt_tokens=estimated_prompt_tokens,
                    estimated_completion_tokens=estimated_completion_tokens,
                    estimated_total_tokens=estimated_prompt_tokens + estimated_completion_tokens,
                    actual_prompt_tokens=actual_prompt_tokens,
                    actual_completion_tokens=actual_completion_tokens,
                    actual_total_tokens=actual_total_tokens,
                    usage_source=attempt_record["usage_source"],
                    billable_prompt_tokens=billable_prompt_tokens,
                    billable_completion_tokens=billable_completion_tokens,
                    billable_total_tokens=billable_total_tokens,
                    completion_token_utilization=round(
                        (
                            actual_completion_tokens
                            if actual_completion_tokens is not None
                            else estimated_completion_tokens
                        )
                        / max(int(payload.get("max_completion_tokens") or payload.get("max_tokens") or 1), 1),
                        4,
                    ),
                    system_hash=text_hash(system_text),
                    user_hash=text_hash(user_text),
                    output_hash=text_hash(cleaned_text),
                    parsed_shape=_parsed_shape(parsed),
                    parse_success=parsed is not None,
                    success=not error_type,
                    error_type=error_type,
                    error=error_message,
                    elapsed_ms=elapsed_ms,
                    metadata=audit_metadata,
                )
                quality_record: dict[str, Any] = {
                    "call_id": call_id,
                    "attempt_number": attempt_number,
                    "retry_reason": retry_reason,
                    "call_site": call_site,
                    "session_id": audit_session_id or "",
                    "turn_id": audit_turn_id or "",
                    "tier": self.tier,
                    "model": self.model,
                    "max_tokens_requested": int(payload.get("max_completion_tokens") or payload.get("max_tokens") or 0),
                    "response_format": response_format_name,
                    "system_chars": len(system_text),
                    "user_chars": len(user_text),
                    "raw_output_chars": len(raw_text),
                    "cleaned_output_chars": len(cleaned_text),
                    "system_hash": text_hash(system_text),
                    "user_hash": text_hash(user_text),
                    "raw_output_hash": text_hash(raw_text),
                    "cleaned_output_hash": text_hash(cleaned_text),
                    "parsed_shape": _parsed_shape(parsed),
                    "parse_success": parsed is not None,
                    "success": not error_type,
                    "error_type": error_type,
                    "error": error_message,
                    "flags": flags,
                    "elapsed_ms": elapsed_ms,
                    "metadata": audit_metadata,
                }
                if quality_capture_text:
                    quality_record.update({
                        "system_prompt": system_text,
                        "user_prompt": user_text,
                        "raw_output": raw_text,
                        "cleaned_output": cleaned_text,
                    })
                await llm_quality_logger.log("llm_quality_attempt", **quality_record)
            return cleaned_text, parsed, attempt_record, captured_exc

        # Parse JSON when the model provides it. Callers that require JSON now
        # validate semantic shape themselves and fail closed instead of using
        # deterministic content fallbacks.
        attempt_records: list[dict[str, Any]] = []
        text, parsed, attempt_record, captured_exc = await _attempt(request_payload, attempt_number=1)
        attempt_records.append(attempt_record)
        if parsed is None and response_format:
            retry_payload = dict(request_payload)
            retry_payload.pop("max_tokens", None)
            retry_payload.pop("max_completion_tokens", None)
            retry_payload[self._token_param] = min(max(max_tokens * 2, 1000), 8000)
            retry_reason = (
                f"provider_error:{type(captured_exc).__name__}"
                if captured_exc
                else "json_parse_failed"
            )
            retry_payload["messages"] = [
                request_payload["messages"][0],
                {
                    "role": "user",
                    "content": (
                        f"{user}\n\n"
                        "Your response must be one complete valid JSON value. "
                        "No markdown, no commentary, no truncated arrays or objects."
                    ),
                },
            ]
            retry_text, retry_parsed, retry_attempt_record, retry_exc = await _attempt(
                retry_payload,
                attempt_number=2,
                retry_reason=retry_reason,
            )
            attempt_records.append(retry_attempt_record)
            if retry_parsed is not None:
                await self._log_aggregate(
                    call_id=call_id,
                    call_site=call_site,
                    response_format_name=response_format_name,
                    attempts=attempt_records,
                    final_value=retry_parsed,
                    retried=True,
                    retry_succeeded=True,
                    audit_session_id=audit_session_id,
                    audit_turn_id=audit_turn_id,
                    audit_metadata=audit_metadata,
                )
                return retry_parsed
            if retry_exc:
                await self._log_aggregate(
                    call_id=call_id,
                    call_site=call_site,
                    response_format_name=response_format_name,
                    attempts=attempt_records,
                    final_value=retry_text,
                    retried=True,
                    retry_succeeded=False,
                    audit_session_id=audit_session_id,
                    audit_turn_id=audit_turn_id,
                    audit_metadata=audit_metadata,
                )
                raise retry_exc
        if captured_exc and parsed is None:
            await self._log_aggregate(
                call_id=call_id,
                call_site=call_site,
                response_format_name=response_format_name,
                attempts=attempt_records,
                final_value=text,
                retried=len(attempt_records) > 1,
                retry_succeeded=False,
                audit_session_id=audit_session_id,
                audit_turn_id=audit_turn_id,
                audit_metadata=audit_metadata,
            )
            raise captured_exc
        final_value = parsed if parsed is not None else text
        await self._log_aggregate(
            call_id=call_id,
            call_site=call_site,
            response_format_name=response_format_name,
            attempts=attempt_records,
            final_value=final_value,
            retried=len(attempt_records) > 1,
            retry_succeeded=False,
            audit_session_id=audit_session_id,
            audit_turn_id=audit_turn_id,
            audit_metadata=audit_metadata,
        )
        return final_value

    async def _log_aggregate(
        self,
        *,
        call_id: str,
        call_site: str,
        response_format_name: str,
        attempts: list[dict[str, Any]],
        final_value: Any,
        retried: bool,
        retry_succeeded: bool,
        audit_session_id: str | None,
        audit_turn_id: str | None,
        audit_metadata: dict,
    ) -> None:
        total_estimated_prompt = sum(int(item.get("estimated_prompt_tokens") or 0) for item in attempts)
        total_estimated_completion = sum(int(item.get("estimated_completion_tokens") or 0) for item in attempts)
        total_billable_prompt = sum(int(item.get("billable_prompt_tokens") or 0) for item in attempts)
        total_billable_completion = sum(int(item.get("billable_completion_tokens") or 0) for item in attempts)
        total_billable = sum(int(item.get("billable_total_tokens") or 0) for item in attempts)
        total_actual_prompt = sum(
            int(item.get("actual_prompt_tokens") or 0)
            for item in attempts
            if item.get("actual_prompt_tokens") is not None
        )
        total_actual_completion = sum(
            int(item.get("actual_completion_tokens") or 0)
            for item in attempts
            if item.get("actual_completion_tokens") is not None
        )
        total_actual = sum(
            int(item.get("actual_total_tokens") or 0)
            for item in attempts
            if item.get("actual_total_tokens") is not None
        )
        provider_usage_available = any(item.get("actual_total_tokens") is not None for item in attempts)
        max_tokens_total = sum(int(item.get("max_tokens_requested") or 0) for item in attempts)
        output_chars_total = sum(int(item.get("output_chars") or 0) for item in attempts)
        elapsed_ms_total = sum(float(item.get("elapsed_ms") or 0.0) for item in attempts)
        await llm_usage_logger.log(
            "llm_call",
            call_id=call_id,
            call_site=call_site,
            session_id=audit_session_id or "",
            turn_id=audit_turn_id or "",
            tier=self.tier,
            model=self.model,
            attempt_count=len(attempts),
            retried=bool(retried),
            retry_succeeded=bool(retry_succeeded),
            response_format=response_format_name,
            max_tokens_requested=max_tokens_total,
            estimated_prompt_tokens=total_estimated_prompt,
            estimated_completion_tokens=total_estimated_completion,
            estimated_total_tokens=total_estimated_prompt + total_estimated_completion,
            actual_prompt_tokens=total_actual_prompt if provider_usage_available else None,
            actual_completion_tokens=total_actual_completion if provider_usage_available else None,
            actual_total_tokens=total_actual if provider_usage_available else None,
            billable_prompt_tokens=total_billable_prompt,
            billable_completion_tokens=total_billable_completion,
            billable_total_tokens=total_billable,
            usage_source="provider" if provider_usage_available else "estimate",
            output_chars=output_chars_total,
            completion_token_utilization=round(
                total_billable_completion / max(max_tokens_total, 1),
                4,
            ),
            final_shape=_parsed_shape(final_value),
            elapsed_ms=round(elapsed_ms_total, 3),
            metadata=audit_metadata,
        )
        flags = sorted({
            flag
            for item in attempts
            for flag in (item.get("quality_flags") or [])
        })
        quality_record: dict[str, Any] = {
            "call_id": call_id,
            "call_site": call_site,
            "session_id": audit_session_id or "",
            "turn_id": audit_turn_id or "",
            "tier": self.tier,
            "model": self.model,
            "attempt_count": len(attempts),
            "retried": bool(retried),
            "retry_succeeded": bool(retry_succeeded),
            "response_format": response_format_name,
            "max_tokens_requested": max_tokens_total,
            "final_shape": _parsed_shape(final_value),
            "flags": flags,
            "elapsed_ms": round(elapsed_ms_total, 3),
            "metadata": audit_metadata,
        }
        if llm_quality_logger.capture_text():
            quality_record["final_value"] = final_value
        await llm_quality_logger.log("llm_quality_call", **quality_record)
