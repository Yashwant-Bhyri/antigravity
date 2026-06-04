from __future__ import annotations

from typing import Any

from backend.state.interview_agenda import (
    FOCUS_STREAK_CAP,
    distinct_substantive_focus_count,
    distinct_substantive_surface_count,
    dominant_focus_ratio,
    max_same_focus_streak,
    max_same_surface_streak,
    surfaces_by_focus,
)


_GENERIC_LATE_ROUTES = {
    "",
    "unknown",
    "sprint_seed",
    "legacy_agenda_backup",
    "sprint_opener",
    "prepped_next_question",
}

_MAP_BACKED_ROUTES = {
    "application_anchor_recovery",
    "application_grounding",
    "application_transfer",
    "coverage_surface",
    "coverage_depth_probe",
    "reserve_map_question",
    "second_anchor",
    "third_surface_probe",
    "focus_pivot",
    "trajectory_map_surface",
    "trajectory_map_mechanism",
    "trajectory_map_boundary",
    "trajectory_map_bridge",
    "trajectory_map_focus_pivot",
}


def _clean_key(value: object) -> str:
    key = str(value or "").strip()
    if key in {"", "general", "general_background", "general background"}:
        return ""
    return key


def _surface_key(turn: dict[str, Any]) -> str:
    focus = _clean_key(turn.get("focus_key"))
    if not focus:
        return ""
    coverage_dim = str(turn.get("coverage_dimension_id") or "").strip()
    if coverage_dim:
        return f"{focus}::coverage::{coverage_dim}"
    sub_focus = _clean_key(turn.get("sub_focus_key"))
    return f"{focus}::{sub_focus}" if sub_focus else focus


def _last_streak(values: list[str]) -> int:
    current = ""
    streak = 0
    for value in values:
        if not value:
            continue
        if value == current:
            streak += 1
        else:
            current = value
            streak = 1
    return streak


def _tail_streak(values: list[str], target: str) -> int:
    streak = 0
    for value in reversed(values):
        if value != target:
            break
        streak += 1
    return streak


def _coverage_evaluated_count(coverage_map: object) -> int:
    if not isinstance(coverage_map, dict):
        return 0
    count = 0
    for dimension in coverage_map.get("dimensions") or []:
        if not isinstance(dimension, dict):
            continue
        state = str(dimension.get("coverage_state") or "").strip()
        response = str(dimension.get("candidate_response") or "").strip()
        if state and state != "not_evaluated":
            count += 1
        elif response:
            count += 1
    return count


def _route_values(history: list[dict[str, Any]]) -> list[str]:
    return [str(turn.get("route_kind") or "").strip() for turn in history]


class PolicyCheckerAgent:
    """
    Signal-only interview policy monitor.

    This agent does not call an LLM and does not steer the interview yet. It watches
    the route/focus/posture sequence and emits typed warnings when the live flow is
    about to repeat our known failure modes: tunneling, stale generic routing,
    missing map-backed focus attribution, skipped application transfer/coverage, or
    prosecutor-style posture streaks.
    """

    def check(
        self,
        state: dict[str, Any],
        *,
        next_packet: dict[str, Any] | None = None,
        next_route_kind: str = "",
        agenda_phase: str = "",
        agenda_reason: str = "",
        turn_number: int = 0,
    ) -> dict[str, Any]:
        packet = dict(next_packet or {})
        route_kind = str(next_route_kind or packet.get("route_kind") or "").strip()
        history = [
            item
            for item in (state.get("history") or [])
            if isinstance(item, dict)
        ]
        projected_turn = {
            "focus_key": packet.get("focus_key") or "",
            "focus_label": packet.get("focus_label") or "",
            "sub_focus_key": packet.get("sub_focus_key") or "",
            "sub_focus_label": packet.get("sub_focus_label") or "",
            "coverage_dimension_id": packet.get("coverage_dimension_id") or "",
            "coverage_dimension_label": packet.get("coverage_dimension_label") or "",
            "route_kind": route_kind,
            "question_posture": packet.get("question_posture") or "",
        }
        projected_history = history + ([projected_turn] if route_kind else [])
        evidence_turn_count = max(int(state.get("question_count") or 0), len(history), int(turn_number or 0))
        projected_focus = _clean_key(projected_turn.get("focus_key"))
        projected_surface = _surface_key(projected_turn)
        warnings: list[dict[str, Any]] = []

        def warn(
            code: str,
            severity: str,
            message: str,
            suggested_action: str,
            evidence: dict[str, Any] | None = None,
        ) -> None:
            warnings.append(
                {
                    "code": code,
                    "severity": severity,
                    "message": message,
                    "suggested_action": suggested_action,
                    "evidence": dict(evidence or {}),
                }
            )

        focus_streak = max_same_focus_streak(projected_history)
        surface_streak = max_same_surface_streak(projected_history)
        current_surface_streak = _last_streak([_surface_key(t) for t in projected_history])
        current_focus_streak = _last_streak([_clean_key(t.get("focus_key")) for t in projected_history])
        focus_surfaces = surfaces_by_focus(projected_history).get(projected_focus, [])

        if projected_surface and current_surface_streak > FOCUS_STREAK_CAP:
            warn(
                "same_surface_streak",
                "high",
                "The next packet would exceed the same-surface streak cap.",
                "stop_same_surface",
                {
                    "surface": projected_surface,
                    "current_surface_streak": current_surface_streak,
                    "cap": FOCUS_STREAK_CAP,
                    "route_kind": route_kind,
                },
            )

        if (
            projected_focus
            and current_focus_streak > FOCUS_STREAK_CAP + 1
            and len(focus_surfaces) < 2
        ):
            warn(
                "same_parent_focus_low_surface_breadth",
                "medium",
                "The parent focus is repeating without enough distinct sub-focus or coverage surfaces.",
                "prefer_coverage_or_second_anchor",
                {
                    "focus_key": projected_focus,
                    "current_focus_streak": current_focus_streak,
                    "distinct_surfaces_in_focus": len(focus_surfaces),
                    "surfaces": focus_surfaces,
                },
            )

        close_routes = {"synthesis_close", "graceful_exit", "complete"}
        question_quality = packet.get("question_quality") if isinstance(packet.get("question_quality"), dict) else {}
        legacy_label_with_grounded_packet = (
            route_kind == "legacy_agenda_backup"
            and bool(projected_focus)
            and bool(str(packet.get("question_text") or "").strip())
            and not bool(question_quality.get("should_block"))
        )
        if evidence_turn_count >= 5 and route_kind in _GENERIC_LATE_ROUTES and not legacy_label_with_grounded_packet:
            warn(
                "late_generic_route",
                "high",
                "A generic or stale sprint route is being staged after the interview should be map/coverage led.",
                "prefer_agenda_route",
                {
                    "route_kind": route_kind,
                    "evidence_turn_count": evidence_turn_count,
                    "agenda_phase": agenda_phase,
                    "agenda_reason": agenda_reason,
                },
            )
        elif evidence_turn_count >= 5 and legacy_label_with_grounded_packet:
            warn(
                "legacy_route_label",
                "low",
                "The route label is legacy_agenda_backup, but the packet carries concrete focus/question metadata.",
                "rename_route_or_preserve_specific_route_kind",
                {
                    "route_kind": route_kind,
                    "focus_key": projected_focus,
                    "agenda_phase": agenda_phase,
                    "agenda_reason": agenda_reason,
                },
            )

        if route_kind in _MAP_BACKED_ROUTES and not projected_focus:
            warn(
                "map_focus_missing",
                "high",
                "A map-backed packet is missing a concrete focus key.",
                "fail_closed_or_repair_packet",
                {
                    "route_kind": route_kind,
                    "question_preview": str(packet.get("question_text") or "")[:180],
                },
            )

        if route_kind in close_routes:
            question_quality = {}

        if question_quality.get("should_block"):
            warn(
                "bad_question_readiness",
                "high",
                "The next packet matches a known bad-question family or unsafe question shape.",
                "repair_or_replace_question_before_serving",
                {
                    "route_kind": route_kind,
                    "question_preview": str(packet.get("question_text") or "")[:180],
                    "flag_codes": list(question_quality.get("flag_codes") or [])[:8],
                    "severity_counts": question_quality.get("severity_counts") or {},
                },
            )
        elif question_quality.get("flag_codes"):
            warn(
                "question_readiness_warning",
                "low",
                "The next packet has non-blocking question-quality warnings.",
                "prefer_cleaner_question_if_available",
                {
                    "route_kind": route_kind,
                    "question_preview": str(packet.get("question_text") or "")[:180],
                    "flag_codes": list(question_quality.get("flag_codes") or [])[:8],
                },
            )

        app_served = bool(state.get("application_question_served"))
        app_staged = route_kind in {"application_anchor_recovery", "application_grounding", "application_transfer"} or bool(state.get("staged_application_question"))
        app_arc = state.get("application_transfer_arc") if isinstance(state.get("application_transfer_arc"), dict) else {}
        grounding_in_progress = bool(app_arc.get("grounding_served") and not app_arc.get("grounding_done"))
        if evidence_turn_count >= 8 and not app_served and not app_staged and not grounding_in_progress:
            warn(
                "application_transfer_late_or_missing",
                "high",
                "Application transfer has not been served or staged by the expected evidence window.",
                "prefer_application_transfer",
                {
                    "evidence_turn_count": evidence_turn_count,
                    "route_kind": route_kind,
                    "agenda_phase": agenda_phase,
                },
            )

        coverage_map = state.get("coverage_map")
        coverage_evaluated = _coverage_evaluated_count(coverage_map)
        coverage_route_staged = route_kind in {"coverage_surface", "coverage_depth_probe"}
        if app_served and isinstance(coverage_map, dict) and coverage_evaluated == 0 and not coverage_route_staged:
            warn(
                "coverage_skipped_after_application",
                "high",
                "Application transfer is served but no coverage dimension has been evaluated or staged next.",
                "prefer_coverage",
                {
                    "route_kind": route_kind,
                    "agenda_phase": agenda_phase,
                    "coverage_dimensions": len(coverage_map.get("dimensions") or []),
                },
            )

        second_anchor_attempted = any(
            str(turn.get("route_kind") or "") == "second_anchor"
            or str(turn.get("agenda_phase") or "") == "second_anchor"
            for turn in history
        ) or route_kind == "second_anchor"
        if evidence_turn_count >= 13 and not second_anchor_attempted:
            warn(
                "second_anchor_late",
                "medium",
                "The interview is late enough that a second anchor should have been attempted or explicitly skipped.",
                "prefer_second_anchor",
                {
                    "evidence_turn_count": evidence_turn_count,
                    "distinct_focus_count": distinct_substantive_focus_count(projected_history),
                    "distinct_surface_count": distinct_substantive_surface_count(projected_history),
                    "route_kind": route_kind,
                },
            )

        posture_sequence = [
            str(turn.get("question_posture") or "").strip()
            for turn in projected_history
            if str(turn.get("question_posture") or "").strip()
        ]
        pressure_streak = _tail_streak(posture_sequence, "pressure")
        if pressure_streak > 2:
            warn(
                "prosecutor_streak",
                "medium",
                "More than two pressure-posture questions are queued consecutively.",
                "insert_frame_or_clarify",
                {
                    "pressure_streak": pressure_streak,
                    "posture_sequence_tail": posture_sequence[-5:],
                },
            )

        route_sequence = _route_values(projected_history)
        second_anchor_count = sum(1 for route in route_sequence if route == "second_anchor")
        second_anchor_tail_streak = _tail_streak(route_sequence, "second_anchor")
        second_anchor_attempted_before_next = any(
            str(turn.get("route_kind") or "") == "second_anchor"
            or str(turn.get("agenda_phase") or "") == "second_anchor"
            for turn in history
        )
        if route_kind == "synthesis_close" and not second_anchor_attempted_before_next and evidence_turn_count < 13:
            warn(
                "synthesis_before_second_anchor",
                "medium",
                "A synthesis/close route is being staged before a second anchor has been attempted.",
                "prefer_second_anchor_before_close",
                {
                    "evidence_turn_count": evidence_turn_count,
                    "route_kind": route_kind,
                    "agenda_phase": agenda_phase,
                },
            )
        if route_kind == "second_anchor" and second_anchor_count > 3:
            warn(
                "second_anchor_overused",
                "medium",
                "Second-anchor routing is being used as a holding pattern instead of closing or synthesizing.",
                "prefer_synthesis_or_distinct_focus",
                {
                    "second_anchor_count": second_anchor_count,
                    "second_anchor_tail_streak": second_anchor_tail_streak,
                    "distinct_focus_count": distinct_substantive_focus_count(projected_history),
                    "distinct_surface_count": distinct_substantive_surface_count(projected_history),
                },
            )
        elif route_kind == "second_anchor" and second_anchor_tail_streak > 3:
            warn(
                "second_anchor_streak",
                "low",
                "Several second-anchor questions are queued consecutively.",
                "prefer_distinct_surface_or_close",
                {
                    "second_anchor_count": second_anchor_count,
                    "second_anchor_tail_streak": second_anchor_tail_streak,
                },
            )

        if (
            str(state.get("finalization_status") or "") == "complete"
            and not bool(state.get("report_ready"))
        ):
            warn(
                "completion_without_report",
                "high",
                "The session is marked finalized but report_ready is false.",
                "repair_completion_state",
                {
                    "finalization_status": state.get("finalization_status"),
                    "report_ready": state.get("report_ready"),
                },
            )

        max_severity_rank = max(
            ({"low": 1, "medium": 2, "high": 3}.get(w.get("severity"), 0) for w in warnings),
            default=0,
        )
        status = "ok"
        if max_severity_rank >= 3:
            status = "block_recommended"
        elif max_severity_rank >= 1:
            status = "warn"

        return {
            "policy_status": status,
            "warnings": warnings,
            "primary_warning_codes": [warning["code"] for warning in warnings[:5]],
            "should_steer": False,
            "steering_suggestion": "",
            "confidence": 0.85 if warnings else 0.75,
            "metrics": {
                "turn_number": turn_number,
                "evidence_turn_count": evidence_turn_count,
                "route_kind": route_kind,
                "agenda_phase": agenda_phase,
                "agenda_reason": agenda_reason,
                "projected_focus_key": projected_focus,
                "projected_surface_key": projected_surface,
                "max_same_focus_streak": focus_streak,
                "max_same_surface_streak": surface_streak,
                "current_focus_streak": current_focus_streak,
                "current_surface_streak": current_surface_streak,
                "dominant_focus_ratio": round(dominant_focus_ratio(projected_history), 3),
                "distinct_focus_count": distinct_substantive_focus_count(projected_history),
                "distinct_surface_count": distinct_substantive_surface_count(projected_history),
                "coverage_evaluated_count": coverage_evaluated,
                "second_anchor_count": second_anchor_count,
                "second_anchor_tail_streak": second_anchor_tail_streak,
            },
        }
