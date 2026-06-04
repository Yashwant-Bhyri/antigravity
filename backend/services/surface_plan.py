from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.config.env_runtime import env_first
from backend.models.llm_router import LLMRouter


SURFACE_PLANNER_MODEL = env_first("OPENROUTER_SURFACE_PLANNER_MODEL", default="openai/gpt-5.4-mini")
SURFACE_PLANNER_TIMEOUT_SECONDS = float(env_first("SURFACE_PLANNER_TIMEOUT_SECONDS", default="60"))
SURFACE_PLANNER_MAX_TOKENS = int(env_first("SURFACE_PLANNER_MAX_TOKENS", default="2600"))
SURFACE_PLAN_RESPONSE_FORMAT = {"type": "json_object"}


SURFACE_PLAN_SYSTEM = """
You are an interview planning analyst. Extract the few high-signal interview
surfaces from a resume for the target role.

Do not generate interview questions.
Do not scan every line equally.
Do not over-reward buzzwords, side projects, or off-role artifacts.
Do not use allocation hints as question counts.

Return only valid JSON with this shape:
{
  "focus_areas": [
    {
      "focus_key": "short_snake_case",
      "label": "plain label",
      "why_high_signal": "why this changes hiring signal for the target role",
      "role_relevance": 1-5,
      "profile_importance": 1-5,
      "evidence_strength": 1-5,
      "claim_risk": 1-5,
      "recommended_allocation_hint": 0.0-1.0,
      "source_snippets": ["exact resume snippet"],
      "sub_focuses": [
        {
          "sub_focus_key": "short_snake_case",
          "label": "plain label",
          "surface_kind": "attribution|taxonomy|dashboard|data_modeling|ownership_boundary|implementation_depth|metric_design|technical_systems|other",
          "why_test": "what this tests",
          "testable_surfaces": ["specific surface to test"],
          "source_snippets": ["exact resume snippet"]
        }
      ]
    }
  ],
  "demoted_or_off_role_surfaces": [
    {
      "label": "plain label",
      "reason": "why it should not lead the interview",
      "source_snippets": ["exact resume snippet"]
    }
  ],
  "missing_or_risky_checks": ["important checks likely needed in interview"],
  "planning_notes": "short note on focus ranking"
}

Quality target:
- 3 to 5 focus areas total when the resume has enough role-relevant signal.
- Each focus area should have 1 to 3 sub-focuses.
- The top 2 focus areas should cover most of the role-relevant hiring signal.
- Prefer broad high-signal surfaces over trivia like exact SQL file names.
- Use source snippets; do not invent claims.
- Off-role credibility checks should be demoted or listed as risk checks, not routable focus areas, unless role relevance is explicit.
""".strip()


class SurfaceSubFocusV2(BaseModel):
    sub_focus_key: str = ""
    label: str = ""
    surface_kind: str = "other"
    why_test: str = ""
    testable_surfaces: list[str] = Field(default_factory=list)
    source_snippets: list[str] = Field(default_factory=list)


class SurfaceFocusAreaV2(BaseModel):
    focus_key: str = ""
    label: str = ""
    why_high_signal: str = ""
    role_relevance: float = 1.0
    profile_importance: float = 1.0
    evidence_strength: float = 1.0
    claim_risk: float = 1.0
    recommended_allocation_hint: float = 0.0
    source_snippets: list[str] = Field(default_factory=list)
    sub_focuses: list[SurfaceSubFocusV2] = Field(default_factory=list)


class DemotedSurfaceV2(BaseModel):
    label: str = ""
    reason: str = ""
    source_snippets: list[str] = Field(default_factory=list)


class SurfacePlanV2(BaseModel):
    focus_areas: list[SurfaceFocusAreaV2] = Field(default_factory=list)
    demoted_or_off_role_surfaces: list[DemotedSurfaceV2] = Field(default_factory=list)
    missing_or_risky_checks: list[str] = Field(default_factory=list)
    planning_notes: str = ""


def _clean_text(value: object, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:limit]


def _key(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return "_".join(tokens[:8]) or "surface"


def _coerce_float(value: object, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _surface_plan_user_prompt(*, resume: str, target_role: str = "", years_experience: str = "") -> str:
    return "\n".join([
        f"Target role: {target_role}" if target_role else "Target role: unspecified",
        f"Years experience: {years_experience}" if years_experience else "",
        "",
        "Resume:",
        str(resume or "").strip(),
        "",
        "Extract the high-signal focus areas, sub-focus areas, and testable surfaces.",
    ]).strip()


def _validate_surface_plan(raw: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(raw, dict):
        return SurfacePlanV2().model_dump(), [f"raw output type {type(raw).__name__} is not a dict"]
    try:
        validated = SurfacePlanV2.model_validate(raw).model_dump()
        return normalize_surface_plan_v2(validated), []
    except ValidationError as exc:
        errors = [f"{e['loc']}: {e['msg']}" for e in exc.errors()]
        defaults = SurfacePlanV2().model_dump()
        for key in defaults:
            if key in raw:
                defaults[key] = raw.get(key)
        return normalize_surface_plan_v2(defaults), errors


def normalize_surface_plan_v2(raw: dict[str, Any]) -> dict[str, Any]:
    focus_areas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for area in raw.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        label = _clean_text(area.get("label"), 120)
        focus_key = _clean_text(area.get("focus_key"), 80) or _key(label)
        focus_key = _key(focus_key)
        if not label or focus_key in seen:
            continue
        seen.add(focus_key)
        sub_focuses: list[dict[str, Any]] = []
        for sub in area.get("sub_focuses") or []:
            if not isinstance(sub, dict):
                continue
            sub_label = _clean_text(sub.get("label"), 120)
            sub_key = _key(str(sub.get("sub_focus_key") or sub_label))
            if not sub_label:
                continue
            sub_focuses.append({
                "sub_focus_key": sub_key,
                "label": sub_label,
                "surface_kind": _clean_text(sub.get("surface_kind"), 60) or "other",
                "why_test": _clean_text(sub.get("why_test"), 220),
                "testable_surfaces": [_clean_text(item, 180) for item in (sub.get("testable_surfaces") or [])[:5] if _clean_text(item)],
                "source_snippets": [_clean_text(item, 180) for item in (sub.get("source_snippets") or [])[:4] if _clean_text(item)],
            })
        focus_areas.append({
            "focus_key": focus_key,
            "label": label,
            "why_high_signal": _clean_text(area.get("why_high_signal"), 240),
            "role_relevance": max(1.0, min(5.0, _coerce_float(area.get("role_relevance"), 1.0))),
            "profile_importance": max(1.0, min(5.0, _coerce_float(area.get("profile_importance"), 1.0))),
            "evidence_strength": max(1.0, min(5.0, _coerce_float(area.get("evidence_strength"), 1.0))),
            "claim_risk": max(1.0, min(5.0, _coerce_float(area.get("claim_risk"), 1.0))),
            "recommended_allocation_hint": max(0.0, min(1.0, _coerce_float(area.get("recommended_allocation_hint"), 0.0))),
            "source_snippets": [_clean_text(item, 180) for item in (area.get("source_snippets") or [])[:4] if _clean_text(item)],
            "sub_focuses": sub_focuses[:3],
        })
    focus_areas.sort(
        key=lambda area: (
            -float(area.get("role_relevance") or 0),
            -float(area.get("profile_importance") or 0),
            -float(area.get("evidence_strength") or 0),
            -float(area.get("claim_risk") or 0),
        )
    )
    demoted = []
    for item in raw.get("demoted_or_off_role_surfaces") or []:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label"), 120)
        if not label:
            continue
        demoted.append({
            "label": label,
            "reason": _clean_text(item.get("reason"), 220),
            "source_snippets": [_clean_text(snippet, 180) for snippet in (item.get("source_snippets") or [])[:4] if _clean_text(snippet)],
        })
    return {
        "schema_version": "surface_plan_v2",
        "planner_model": SURFACE_PLANNER_MODEL,
        "focus_areas": focus_areas[:5],
        "demoted_or_off_role_surfaces": demoted[:8],
        "missing_or_risky_checks": [_clean_text(item, 180) for item in (raw.get("missing_or_risky_checks") or [])[:10] if _clean_text(item)],
        "planning_notes": _clean_text(raw.get("planning_notes"), 400),
    }


async def generate_surface_plan_v2(
    *,
    resume: str,
    target_role: str = "",
    years_experience: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    started = time.perf_counter()
    raw = await LLMRouter(
        tier="small",
        model_override=SURFACE_PLANNER_MODEL,
        timeout_override=SURFACE_PLANNER_TIMEOUT_SECONDS,
    ).call(
        SURFACE_PLAN_SYSTEM,
        _surface_plan_user_prompt(resume=resume, target_role=target_role, years_experience=years_experience),
        max_tokens=SURFACE_PLANNER_MAX_TOKENS,
        response_format=SURFACE_PLAN_RESPONSE_FORMAT,
        audit_call_name="surface_plan_v2",
        audit_session_id=session_id,
        audit_metadata={"model": SURFACE_PLANNER_MODEL, "target_role": target_role},
    )
    plan, errors = _validate_surface_plan(raw)
    plan["schema_errors"] = errors
    plan["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return plan


def compact_surface_plan_for_prompt(surface_plan: dict[str, Any] | None) -> str:
    if not isinstance(surface_plan, dict):
        return ""
    compact = {
        "focus_areas": [
            {
                "focus_key": area.get("focus_key"),
                "label": area.get("label"),
                "role_relevance": area.get("role_relevance"),
                "profile_importance": area.get("profile_importance"),
                "evidence_strength": area.get("evidence_strength"),
                "claim_risk": area.get("claim_risk"),
                "recommended_allocation_hint": area.get("recommended_allocation_hint"),
                "why_high_signal": area.get("why_high_signal"),
                "source_snippets": area.get("source_snippets"),
                "sub_focuses": [
                    {
                        "sub_focus_key": sub.get("sub_focus_key"),
                        "label": sub.get("label"),
                        "surface_kind": sub.get("surface_kind"),
                        "why_test": sub.get("why_test"),
                        "testable_surfaces": sub.get("testable_surfaces"),
                    }
                    for sub in (area.get("sub_focuses") or [])[:3]
                    if isinstance(sub, dict)
                ],
            }
            for area in (surface_plan.get("focus_areas") or [])[:5]
            if isinstance(area, dict)
        ],
        "demoted_or_off_role_surfaces": surface_plan.get("demoted_or_off_role_surfaces", [])[:6],
        "missing_or_risky_checks": surface_plan.get("missing_or_risky_checks", [])[:8],
    }
    return json.dumps(compact, ensure_ascii=True, indent=2, sort_keys=True)


def surface_plan_alignment_warnings(focus_plan: dict[str, Any], surface_plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(focus_plan, dict) or not isinstance(surface_plan, dict):
        return []
    plan_text = json.dumps(focus_plan, sort_keys=True).lower()
    warnings: list[str] = []
    for area in surface_plan.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        role_relevance = _coerce_float(area.get("role_relevance"), 1.0)
        evidence_strength = _coerce_float(area.get("evidence_strength"), 1.0)
        if role_relevance < 4.0 or evidence_strength < 3.0:
            continue
        labels = [
            str(area.get("focus_key") or "").replace("_", " "),
            str(area.get("label") or ""),
            *[str(item or "") for item in area.get("source_snippets") or []],
        ]
        for sub in area.get("sub_focuses") or []:
            if isinstance(sub, dict):
                labels.extend([str(sub.get("label") or ""), str(sub.get("surface_kind") or "")])
        tokens = {
            token
            for label in labels
            for token in re.findall(r"[a-z0-9]+", label.lower())
            if len(token) > 3
        }
        if tokens and len(tokens & set(re.findall(r"[a-z0-9]+", plan_text))) < min(2, len(tokens)):
            warnings.append(
                f"SurfacePlanV2 high-relevance surface appears omitted: {area.get('label')} ({area.get('focus_key')})."
            )
    for area in focus_plan.get("focus_areas") or []:
        if not isinstance(area, dict):
            continue
        value = _coerce_float(area.get("coverage_value"), 0.0)
        sub_values = [
            _coerce_float(sub.get("coverage_value"), 0.0)
            for sub in area.get("sub_focuses") or []
            if isinstance(sub, dict)
        ]
        max_value = max([value, *sub_values, 0.0])
        text = json.dumps(area, sort_keys=True).lower()
        off_role_terms = ("off-role", "credibility check", "side project", "weekend", "college", "toy", "tutorial")
        if max_value >= 2.0 and any(term in text for term in off_role_terms):
            warnings.append(
                f"Potential off-role credibility surface became routable: {area.get('label') or area.get('focus_key')}."
            )
    return warnings
