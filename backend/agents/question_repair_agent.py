from __future__ import annotations

import os
import re
from typing import Any

from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter
from backend.services.question_quality import check_question_readiness


_REPAIR_FLAG_CODES = {
    "compound_chain",
    "multiple_question_marks",
    "overlong_question",
    "severely_overlong_question",
    "truncated_question",
}


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", str(text or "")))


def _route_word_limit(route_kind: str) -> int:
    route = str(route_kind or "").strip().lower()
    if route in {"coverage_surface", "coverage_depth_probe"}:
        return 30
    if route == "application_transfer":
        return 45
    return 40


def _has_answer_lanes(text: str) -> bool:
    cleaned = str(text or "").lower()
    if " or " not in cleaned:
        return False
    if re.search(r"\b(mainly|whether|which of|came from|because of|driven by)\b", cleaned):
        return True
    return len(re.findall(r",", cleaned)) >= 1


def _has_escape_hatch(text: str) -> bool:
    return bool(re.search(
        r"\b(or something else|something else|anything else|what else|some other|another reason|other reason|beyond these|if not these)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ))


def _ensure_escape_hatch(text: str) -> str:
    cleaned = _normalize_text(text)
    if not cleaned or not _has_answer_lanes(cleaned) or _has_escape_hatch(cleaned):
        return cleaned
    if cleaned.endswith("?"):
        cleaned = cleaned[:-1].rstrip()
    return f"{cleaned}, or something else?"


class QuestionRepairAgent:
    """Shared fast repair lane for overlong candidate-facing questions."""

    def __init__(self) -> None:
        self.llm = LLMRouter(
            tier="small",
            model_override=os.environ.get("QUESTION_REPAIR_MODEL", "gpt-oss-120b").strip(),
            timeout_override=float(os.environ.get("QUESTION_REPAIR_TIMEOUT_SECONDS", "20")),
        )

    @staticmethod
    def _needs_repair(question: str, readiness: dict[str, Any], *, route_kind: str = "") -> bool:
        flag_codes = {str(code).strip() for code in (readiness.get("flag_codes") or []) if str(code).strip()}
        if flag_codes & _REPAIR_FLAG_CODES:
            return True
        return _word_count(question) > _route_word_limit(route_kind)

    async def repair(
        self,
        *,
        question: str,
        route_kind: str,
        posture: str,
        turn_number: int = 0,
        surface_kind: str = "",
        expected_space: list[str] | None = None,
        target_role: str = "",
        focus_label: str = "",
        sub_focus_label: str = "",
        signal_goal: str = "",
        anchor_context: str = "",
        audit_call_name: str = "QuestionRepairAgent.repair",
        audit_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        original = _normalize_text(question)
        readiness_before = check_question_readiness(
            original,
            route_kind=route_kind,
            posture=posture,
            turn_number=int(turn_number or 0),
            surface_kind=surface_kind,
            expected_space=list(expected_space or [])[:4],
        )
        if not original:
            return {
                "attempted": False,
                "accepted": False,
                "question": "",
                "reason": "empty_question",
                "readiness_before": readiness_before,
                "repair_model": getattr(self.llm, "model", ""),
                "repair_backend": getattr(self.llm, "backend", ""),
            }
        if not self._needs_repair(original, readiness_before, route_kind=route_kind):
            return {
                "attempted": False,
                "accepted": False,
                "question": original,
                "reason": "repair_not_needed",
                "readiness_before": readiness_before,
                "repair_model": getattr(self.llm, "model", ""),
                "repair_backend": getattr(self.llm, "backend", ""),
            }

        prompt = (
            "Rewrite this candidate-facing interview question for live spoken delivery.\n"
            "Preserve the exact evaluation intent, role relevance, changed constraint, and answer space.\n"
            "This is a light wording repair only: shorten the question without changing what is being tested.\n\n"
            "Rules:\n"
            "- Output one natural spoken question.\n"
            f"- Prefer 16-{max(24, _route_word_limit(route_kind) - 4)} words. Hard maximum {_route_word_limit(route_kind)} words.\n"
            "- Keep exactly one real ask and one question mark.\n"
            "- If the question presents answer lanes or comparisons, keep an escape hatch like 'or something else?'.\n"
            "- Do not add new internals, ownership claims, or hidden assumptions.\n"
            "- If the original question offered open answer lanes, preserve that openness.\n"
            "- Return JSON only: {\"question\": \"...\", \"notes\": \"...\"}\n\n"
            f"Route kind: {route_kind or 'unknown'}\n"
            f"Posture: {posture or 'unknown'}\n"
            f"Turn number: {int(turn_number or 0)}\n"
            f"Surface kind: {surface_kind or 'unknown'}\n"
            f"Target role: {target_role or 'not specified'}\n"
            f"Focus label: {focus_label or 'not specified'}\n"
            f"Sub-focus label: {sub_focus_label or 'not specified'}\n"
            f"Signal goal: {signal_goal or 'not specified'}\n"
            f"Expected answer space: {', '.join(str(item).strip() for item in (expected_space or [])[:4] if str(item).strip()) or 'not specified'}\n"
            f"Anchor/context: {anchor_context[:900] if anchor_context else 'not specified'}\n"
            f"Deterministic readiness flags: {', '.join(readiness_before.get('flag_codes') or []) or 'none'}\n\n"
            f"Original question: {original}"
        )
        result = await self.llm.call(
            system=(
                "You are a strict spoken-question repair editor. "
                "Keep the interview signal intact while making the question short, speakable, and safe."
            ),
            user=prompt,
            max_tokens=220,
            response_format=JSON_OBJECT_FORMAT,
            audit_call_name=audit_call_name,
            audit_metadata={
                **(audit_metadata if isinstance(audit_metadata, dict) else {}),
                "route_kind": route_kind,
                "question_posture": posture,
                "repair_scope": "spoken_question",
            },
        )
        rewritten = _normalize_text((result or {}).get("question") if isinstance(result, dict) else "")
        rewritten = _ensure_escape_hatch(rewritten)
        if not rewritten:
            return {
                "attempted": True,
                "accepted": False,
                "question": original,
                "reason": "llm_empty_question",
                "readiness_before": readiness_before,
                "repair_model": getattr(self.llm, "model", ""),
                "repair_backend": getattr(self.llm, "backend", ""),
            }

        readiness_after = check_question_readiness(
            rewritten,
            route_kind=route_kind,
            posture=posture,
            turn_number=int(turn_number or 0),
            surface_kind=surface_kind,
            expected_space=list(expected_space or [])[:4],
        )
        before_high = int((readiness_before.get("severity_counts") or {}).get("high") or 0)
        after_high = int((readiness_after.get("severity_counts") or {}).get("high") or 0)
        before_words = _word_count(original)
        after_words = _word_count(rewritten)
        route_limit = _route_word_limit(route_kind)

        rejected_reason = ""
        if after_high > before_high:
            rejected_reason = "introduced_more_high_severity_flags"
        elif after_words > max(route_limit, before_words):
            rejected_reason = "rewrite_did_not_shrink"
        elif self._needs_repair(rewritten, readiness_after, route_kind=route_kind):
            rejected_reason = "rewrite_still_not_speakable"

        accepted = not rejected_reason and rewritten != original
        return {
            "attempted": True,
            "accepted": accepted,
            "question": rewritten if accepted else original,
            "rewritten_question": rewritten,
            "reason": "rewrite_accepted" if accepted else (rejected_reason or "rewrite_kept_original_shape"),
            "readiness_before": readiness_before,
            "readiness_after": readiness_after,
            "notes": str((result or {}).get("notes") or "") if isinstance(result, dict) else "",
            "repair_model": getattr(self.llm, "model", ""),
            "repair_backend": getattr(self.llm, "backend", ""),
        }
