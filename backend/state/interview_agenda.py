from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AGENDA_PHASES = {
    "warm_open",
    "primary_depth",
    "application_transfer",
    "coverage_surface",
    "coverage_depth",
    "second_anchor",
    "synthesis_close",
    "complete",
}

FOCUS_STREAK_CAP = 4
FOCUS_RATIO_CAP = 0.55
FOCUS_RATIO_MIN_EVIDENCE_TURNS = 4
PRIMARY_FOCUS_MIN_EVIDENCE_TURNS = 3
MAX_COVERAGE_OPENINGS = 4
MIN_COVERAGE_OPENINGS_BEFORE_STREAK_PIVOT = 2
MIN_COMPLETION_TURNS = 15

NON_SUBSTANTIVE_SURFACE_ROUTES = {
    "",
    "application_grounding",
    "complete",
    "echo_guard",
    "graceful_exit",
    "synthesis_close",
    "sprint_opener",
    "warm_open",
    "unknown",
}


def _clean_focus_key(value: object) -> str:
    key = str(value or "").strip()
    if key in {"", "general", "general_background", "general background"}:
        return ""
    return key


def _clean_sub_focus_key(value: object) -> str:
    key = str(value or "").strip()
    if key in {"", "general", "general_background", "general background"}:
        return ""
    return key


def _surface_key(turn: dict) -> str:
    if str(turn.get("route_kind") or "").strip() in NON_SUBSTANTIVE_SURFACE_ROUTES:
        return ""
    focus = _clean_focus_key(turn.get("focus_key"))
    if not focus:
        return ""
    coverage_dim = str(turn.get("coverage_dimension_id") or "").strip()
    if coverage_dim:
        return f"{focus}::coverage::{coverage_dim}"
    sub_focus = _clean_sub_focus_key(turn.get("sub_focus_key"))
    return f"{focus}::{sub_focus}" if sub_focus else focus


def _coerce_surface_weight(value: object, default: float = 1.5) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1.0, min(3.0, parsed))


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _safe_list(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def _sub_focus_key_from_label(label: str) -> str:
    import re

    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", str(label or "").lower())
        if len(token) > 2
    ]
    return "_".join(tokens[:8])


def _sub_focus_parts(item: object, focus_key: str) -> tuple[str, str, float]:
    if isinstance(item, dict):
        label = str(
            item.get("label")
            or item.get("name")
            or item.get("surface")
            or item.get("sub_focus")
            or item.get("sub_focus_label")
            or item.get("sub_focus_key")
            or ""
        ).strip()
        key = str(item.get("sub_focus_key") or item.get("key") or item.get("id") or "").strip()
        role_relevance = _coerce_surface_weight(
            item.get("role_relevance_weight")
            or item.get("role_relevance")
            or item.get("role_weight")
            or item.get("weight")
        )
        profile_importance = _coerce_surface_weight(
            item.get("profile_importance_weight")
            or item.get("profile_importance")
            or item.get("profile_weight"),
            default=role_relevance,
        )
        evidence_strength = _coerce_surface_weight(item.get("evidence_strength"))
        claim_risk = _coerce_surface_weight(item.get("claim_risk") or item.get("clean_risk"))
        explicit_value = item.get("coverage_value") or item.get("value") or item.get("priority_weight")
        value = (
            _coerce_surface_weight(explicit_value)
            if explicit_value is not None
            else _coerce_surface_weight(
                (role_relevance * 0.45)
                + (profile_importance * 0.25)
                + (evidence_strength * 0.15)
                + (claim_risk * 0.15)
            )
        )
    else:
        label = str(item or "").strip()
        key = ""
        value = 1.5
    key = key or _sub_focus_key_from_label(label) or focus_key
    return key, label, value


def _surface_kind(value: object) -> str:
    return str(value or "").strip().lower()


def _sub_focus_surface_candidate(area: dict, item: object, index: int) -> dict[str, Any]:
    focus_key = _clean_focus_key(area.get("focus_key"))
    focus_label_value = str(area.get("label") or focus_key).strip()
    sub_key, sub_label, value = _sub_focus_parts(item, focus_key)
    if isinstance(item, dict):
        kind = _surface_kind(item.get("surface_kind"))
        role_relevance = _coerce_surface_weight(item.get("role_relevance_weight") or item.get("role_relevance"))
        profile_importance = _coerce_surface_weight(item.get("profile_importance_weight") or item.get("profile_importance"))
        evidence_strength = _coerce_surface_weight(item.get("evidence_strength"))
        claim_risk = _coerce_surface_weight(item.get("claim_risk") or item.get("clean_risk"))
        source_snippets = [str(s or "") for s in (item.get("source_snippets") or []) if str(s or "").strip()]
    else:
        kind = ""
        role_relevance = value
        profile_importance = value
        evidence_strength = 1.5
        claim_risk = 1.5
        source_snippets = []
    return {
        "focus_key": focus_key,
        "focus_label": focus_label_value,
        "sub_focus_key": sub_key,
        "sub_focus_label": sub_label or sub_key,
        "surface_kind": kind,
        "surface_key": f"{focus_key}::{sub_key}" if sub_key else focus_key,
        "coverage_value": value,
        "role_relevance_weight": role_relevance,
        "profile_importance_weight": profile_importance,
        "evidence_strength": evidence_strength,
        "claim_risk": claim_risk,
        "source_snippets": source_snippets[:3],
        "map_order": index,
    }


def anchor_surface_candidates(interview_map: dict | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    order = 0
    for area in focus_areas_from_map(interview_map):
        focus_key = _clean_focus_key(area.get("focus_key"))
        if not focus_key:
            continue
        sub_focuses = area.get("sub_focuses") or []
        if isinstance(sub_focuses, list) and sub_focuses:
            for item in sub_focuses:
                candidate = _sub_focus_surface_candidate(area, item, order)
                order += 1
                if candidate.get("surface_key"):
                    candidates.append(candidate)
        else:
            value = _coerce_surface_weight(
                area.get("coverage_value")
                or area.get("role_relevance_weight")
                or area.get("profile_importance_weight")
                or area.get("priority_weight")
            )
            candidates.append({
                "focus_key": focus_key,
                "focus_label": str(area.get("label") or focus_key).strip(),
                "sub_focus_key": "",
                "sub_focus_label": "",
                "surface_kind": _surface_kind(area.get("surface_kind")),
                "surface_key": focus_key,
                "coverage_value": value,
                "role_relevance_weight": _coerce_surface_weight(area.get("role_relevance_weight"), default=value),
                "profile_importance_weight": _coerce_surface_weight(area.get("profile_importance_weight"), default=value),
                "evidence_strength": _coerce_surface_weight(area.get("evidence_strength")),
                "claim_risk": _coerce_surface_weight(area.get("claim_risk")),
                "source_snippets": [str(s or "") for s in (area.get("resume_snippets") or []) if str(s or "").strip()][:3],
                "map_order": order,
            })
            order += 1
    return candidates


def surface_value_map(interview_map: dict | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for area in focus_areas_from_map(interview_map):
        focus = _clean_focus_key(area.get("focus_key"))
        if not focus:
            continue
        sub_focuses = area.get("sub_focuses") or []
        if isinstance(sub_focuses, list) and sub_focuses:
            for item in sub_focuses:
                sub_key, _, value = _sub_focus_parts(item, focus)
                if sub_key:
                    values[f"{focus}::{sub_key}"] = max(values.get(f"{focus}::{sub_key}", 0.0), value)
        else:
            values[focus] = _coerce_surface_weight(
                area.get("coverage_value")
                or area.get("role_relevance_weight")
                or area.get("profile_importance_weight")
                or area.get("priority_weight")
            )
    return values


def focus_priority_value(interview_map: dict | None, focus_key: str) -> float:
    focus_key = _clean_focus_key(focus_key)
    if not focus_key:
        return 1.5
    prefix = f"{focus_key}::"
    values = [
        value
        for surface, value in surface_value_map(interview_map).items()
        if surface == focus_key or surface.startswith(prefix)
    ]
    return max(values) if values else 1.5


def focus_areas_from_map(interview_map: dict | None) -> list[dict[str, Any]]:
    areas = (interview_map or {}).get("focus_areas", [])
    if not isinstance(areas, list):
        return []
    return [area for area in areas if isinstance(area, dict) and _clean_focus_key(area.get("focus_key"))]


def focus_label(interview_map: dict | None, focus_key: str) -> str:
    focus_key = _clean_focus_key(focus_key)
    for area in focus_areas_from_map(interview_map):
        if _clean_focus_key(area.get("focus_key")) == focus_key:
            return str(area.get("label") or focus_key)
    return focus_key


def focus_queue(interview_map: dict | None) -> list[str]:
    keys: list[str] = []
    for area in focus_areas_from_map(interview_map):
        key = _clean_focus_key(area.get("focus_key"))
        if key and key not in keys:
            keys.append(key)
    return keys


@dataclass
class InterviewAgendaState:
    phase: str = "warm_open"
    primary_focus_key: str = ""
    current_focus_key: str = ""
    secondary_focus_queue: list[str] = field(default_factory=list)
    exhausted_focus_keys: list[str] = field(default_factory=list)
    turns_by_focus: dict[str, int] = field(default_factory=dict)
    turns_by_surface: dict[str, int] = field(default_factory=dict)
    phase_turn_count: int = 0
    coverage_opening_count: int = 0
    coverage_depth_used: dict[str, bool] = field(default_factory=dict)
    last_route_reason: str = "initialized"
    completion_eligible: bool = False
    close_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase if self.phase in AGENDA_PHASES else "warm_open",
            "primary_focus_key": self.primary_focus_key,
            "current_focus_key": self.current_focus_key,
            "secondary_focus_queue": list(self.secondary_focus_queue),
            "exhausted_focus_keys": list(self.exhausted_focus_keys),
            "turns_by_focus": dict(self.turns_by_focus),
            "turns_by_surface": dict(self.turns_by_surface),
            "phase_turn_count": self.phase_turn_count,
            "coverage_opening_count": self.coverage_opening_count,
            "coverage_depth_used": dict(self.coverage_depth_used),
            "last_route_reason": self.last_route_reason,
            "completion_eligible": self.completion_eligible,
            "close_reason": self.close_reason,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "InterviewAgendaState":
        data = data if isinstance(data, dict) else {}
        phase = str(data.get("phase") or "warm_open")
        if phase not in AGENDA_PHASES:
            phase = "warm_open"
        return cls(
            phase=phase,
            primary_focus_key=str(data.get("primary_focus_key") or ""),
            current_focus_key=str(data.get("current_focus_key") or ""),
            secondary_focus_queue=_safe_list(data.get("secondary_focus_queue")),
            exhausted_focus_keys=_safe_list(data.get("exhausted_focus_keys")),
            turns_by_focus=_safe_dict(data.get("turns_by_focus")),
            turns_by_surface=_safe_dict(data.get("turns_by_surface")),
            phase_turn_count=_safe_int(data.get("phase_turn_count")),
            coverage_opening_count=_safe_int(data.get("coverage_opening_count")),
            coverage_depth_used=_safe_dict(data.get("coverage_depth_used")),
            last_route_reason=str(data.get("last_route_reason") or "loaded"),
            completion_eligible=bool(data.get("completion_eligible")),
            close_reason=str(data.get("close_reason") or ""),
        )


def initial_interview_agenda(interview_map: dict | None = None) -> dict[str, Any]:
    queue = focus_queue(interview_map)
    primary = queue[0] if queue else ""
    return InterviewAgendaState(
        phase="warm_open",
        primary_focus_key=primary,
        current_focus_key=primary,
        secondary_focus_queue=queue[1:],
        last_route_reason="initialized",
    ).to_dict()


def ensure_interview_agenda(state: dict) -> dict[str, Any]:
    agenda = InterviewAgendaState.from_dict(state.get("interview_agenda"))
    queue = focus_queue(state.get("interview_trajectory_map") or {})
    if queue:
        if not agenda.primary_focus_key or agenda.primary_focus_key not in queue:
            agenda.primary_focus_key = queue[0]
        if not agenda.current_focus_key or agenda.current_focus_key not in queue:
            agenda.current_focus_key = agenda.primary_focus_key
        known_secondaries = [
            key for key in agenda.secondary_focus_queue
            if key in queue and key != agenda.primary_focus_key
        ]
        for key in queue:
            if key != agenda.primary_focus_key and key not in known_secondaries:
                known_secondaries.append(key)
        agenda.secondary_focus_queue = known_secondaries
    state["interview_agenda"] = agenda.to_dict()
    return state["interview_agenda"]


def distinct_substantive_focus_count(history: list[dict]) -> int:
    return len({
        _clean_focus_key(turn.get("focus_key"))
        for turn in history
        if str(turn.get("route_kind") or "").strip() not in NON_SUBSTANTIVE_SURFACE_ROUTES
        and _clean_focus_key(turn.get("focus_key"))
    })


def distinct_substantive_surface_count(history: list[dict]) -> int:
    return len({
        _surface_key(turn)
        for turn in history
        if _surface_key(turn)
    })


def surfaces_by_focus(history: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for turn in history:
        if str(turn.get("route_kind") or "").strip() in NON_SUBSTANTIVE_SURFACE_ROUTES:
            continue
        focus = _clean_focus_key(turn.get("focus_key"))
        if not focus:
            continue
        coverage_dim = str(turn.get("coverage_dimension_id") or "").strip()
        surface = (
            f"coverage::{coverage_dim}"
            if coverage_dim
            else (_clean_sub_focus_key(turn.get("sub_focus_key")) or focus)
        )
        grouped.setdefault(focus, [])
        if surface not in grouped[focus]:
            grouped[focus].append(surface)
    return grouped


def weighted_surface_coverage(interview_map: dict | None, history: list[dict]) -> dict[str, Any]:
    values = surface_value_map(interview_map)
    tested = {
        _surface_key(turn)
        for turn in history
        if _surface_key(turn)
    }
    tested_weight = 0.0
    high_value_tested: list[str] = []
    high_value_available = [
        surface for surface, value in values.items()
        if value >= 2.5
    ]
    for surface in tested:
        value = values.get(surface)
        if value is None and "::" not in surface:
            value = focus_priority_value(interview_map, surface)
        if value is None:
            value = 1.5
        tested_weight += value
        if value >= 2.5:
            high_value_tested.append(surface)
    total_weight = sum(values.values())
    if total_weight <= 0 and tested:
        total_weight = len(tested) * 1.5
    ratio = tested_weight / total_weight if total_weight > 0 else 0.0
    return {
        "tested_weight": round(tested_weight, 3),
        "total_weight": round(total_weight, 3),
        "ratio": round(min(1.0, ratio), 3),
        "high_value_tested": sorted(high_value_tested),
        "high_value_tested_count": len(high_value_tested),
        "high_value_available_count": len(high_value_available),
    }


def max_same_focus_streak(history: list[dict]) -> int:
    streak = 0
    max_streak = 0
    current = ""
    for turn in history:
        if str(turn.get("route_kind") or "").strip() in NON_SUBSTANTIVE_SURFACE_ROUTES:
            continue
        focus = _clean_focus_key(turn.get("focus_key"))
        if not focus:
            continue
        if focus == current:
            streak += 1
        else:
            current = focus
            streak = 1
        max_streak = max(max_streak, streak)
    return max_streak


def max_same_surface_streak(history: list[dict]) -> int:
    streak = 0
    max_streak = 0
    current = ""
    for turn in history:
        surface = _surface_key(turn)
        if not surface:
            continue
        if surface == current:
            streak += 1
        else:
            current = surface
            streak = 1
        max_streak = max(max_streak, streak)
    return max_streak


def dominant_focus_ratio(history: list[dict]) -> float:
    counts: dict[str, int] = {}
    for turn in history:
        if str(turn.get("route_kind") or "").strip() in NON_SUBSTANTIVE_SURFACE_ROUTES:
            continue
        focus = _clean_focus_key(turn.get("focus_key"))
        if focus:
            counts[focus] = counts.get(focus, 0) + 1
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    return max(counts.values()) / total


def next_secondary_focus(state: dict, avoid_focus: str = "") -> tuple[str, str]:
    agenda = ensure_interview_agenda(state)
    exhausted = set(agenda.get("exhausted_focus_keys") or [])
    avoid_focus = _clean_focus_key(avoid_focus)
    interview_map = state.get("interview_trajectory_map") or {}
    ordered = []
    seen: set[str] = set()
    for key in list(agenda.get("secondary_focus_queue") or []) + focus_queue(interview_map):
        cleaned = _clean_focus_key(key)
        if cleaned and cleaned not in seen and cleaned not in exhausted and cleaned != avoid_focus:
            seen.add(cleaned)
            ordered.append(cleaned)
    if ordered:
        ranked = sorted(
            enumerate(ordered),
            key=lambda item: (-focus_priority_value(interview_map, item[1]), item[0]),
        )
        selected = ranked[0][1]
        return selected, focus_label(interview_map, selected)
    return "", ""


def next_secondary_surface(
    state: dict,
    avoid_focus: str = "",
    avoid_surface: str = "",
    avoid_surfaces: set[str] | None = None,
) -> dict[str, Any]:
    """Return the best unspent second-anchor surface, not just a parent focus.

    Focus rotation is still preferred when possible, but a resume can contain
    multiple role-relevant surfaces inside one parent focus. This selector keeps
    those surfaces addressable so a "second anchor" is semantically real.
    """
    agenda = ensure_interview_agenda(state)
    exhausted = set(agenda.get("exhausted_focus_keys") or [])
    turns_by_surface = dict(agenda.get("turns_by_surface") or {})
    turns_by_focus = dict(agenda.get("turns_by_focus") or {})
    avoid_focus = _clean_focus_key(avoid_focus)
    avoid_surface = str(avoid_surface or "").strip()
    avoid_surface_set = {
        str(surface or "").strip()
        for surface in (avoid_surfaces or set())
        if str(surface or "").strip()
    }
    if avoid_surface:
        avoid_surface_set.add(avoid_surface)

    candidates = [
        candidate for candidate in anchor_surface_candidates(state.get("interview_trajectory_map") or {})
        if candidate.get("surface_key")
        and candidate.get("focus_key") not in exhausted
        and candidate.get("surface_key") not in avoid_surface_set
    ]
    if not candidates:
        return {}

    unasked = [c for c in candidates if int(turns_by_surface.get(c["surface_key"], 0) or 0) == 0]
    pool = unasked or candidates
    def score(candidate: dict[str, Any]) -> tuple:
        surface_turns = int(turns_by_surface.get(candidate["surface_key"], 0) or 0)
        focus_turns = int(turns_by_focus.get(candidate["focus_key"], 0) or 0)
        value = _coerce_surface_weight(candidate.get("coverage_value"))
        role = _coerce_surface_weight(candidate.get("role_relevance_weight"))
        profile = _coerce_surface_weight(candidate.get("profile_importance_weight"))
        evidence = _coerce_surface_weight(candidate.get("evidence_strength"))
        weighted_value = (value * 0.45) + (role * 0.25) + (profile * 0.15) + (evidence * 0.15)
        if candidate.get("focus_key") != avoid_focus:
            weighted_value += 0.35
        same_focus = 1 if candidate.get("focus_key") == avoid_focus else 0
        return (
            surface_turns,
            -weighted_value,
            same_focus,
            focus_turns,
            int(candidate.get("map_order") or 0),
        )

    return dict(sorted(pool, key=score)[0])


def least_used_focus(state: dict, avoid_focus: str = "") -> tuple[str, str]:
    agenda = ensure_interview_agenda(state)
    counts = dict(agenda.get("turns_by_focus") or {})
    avoid_focus = _clean_focus_key(avoid_focus)
    candidates = [
        key for key in focus_queue(state.get("interview_trajectory_map") or {})
        if key and key != avoid_focus
    ]
    if not candidates:
        return "", ""
    interview_map = state.get("interview_trajectory_map") or {}
    candidates.sort(key=lambda key: (int(counts.get(key, 0) or 0), -focus_priority_value(interview_map, key), key))
    selected = candidates[0]
    return selected, focus_label(interview_map, selected)
