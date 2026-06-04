"""
No-credit saved-map replay suite.

This harness answers a deliberately narrow question:

1. Can saved full runtime maps from session exports pass today's map/start
   contract without regenerating a map?
2. Do historical full-run artifacts still show route/report issues after the
   latest quality gates?
3. Which map-policy artifacts are replayable full maps versus summary-only
   artifacts that cannot prove runtime behavior?

It must not call any LLM. To avoid the startup seed LLM call, the harness
injects the first map opener into `prepped_next_question` before calling
`start_prepared_session()`.

Run:
  PYTHONPATH=. python3 backend/test_saved_map_replay_suite.py

Useful knobs:
  SAVED_MAP_REPLAY_EXPORT_GLOB=backend/data/session_exports/*.json
  SAVED_MAP_REPLAY_FULL_GLOB=/tmp/antigravity_*full*.json
  SAVED_MAP_REPLAY_MAP_GLOB=/tmp/antigravity_*map_policy.json
  SAVED_MAP_REPLAY_MAX_EXPORTS=8
  SAVED_MAP_REPLAY_OUTPUT_PREFIX=/tmp/antigravity_saved_map_replay
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import backend.main  # noqa: F401 - loads runtime env without printing secrets
from backend.services import interview_map as interview_map_module
from backend.services.orchestrator import (
    Orchestrator,
    SPRINT_OPENERS,
    _build_question_packet,
    _track_opener,
)
from backend.state.interview_agenda import initial_interview_agenda

try:
    from backend.test_robust_interview_simulation_suite import CASES as ROBUST_CASES
except Exception:
    ROBUST_CASES = ()


MAP_BACKED_ROUTES = {
    "trajectory_map_surface",
    "trajectory_map_mechanism",
    "trajectory_map_boundary",
    "coverage_surface",
    "coverage_depth_probe",
    "application_grounding",
    "application_transfer",
    "second_anchor",
}


def _clean(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _full_export_paths() -> list[Path]:
    pattern = os.environ.get(
        "SAVED_MAP_REPLAY_EXPORT_GLOB",
        "/Users/yash/antigravity/backend/data/session_exports/*.json",
    )
    paths = [Path(p) for p in glob.glob(pattern)]
    paths = [
        path
        for path in paths
        if path.is_file()
        and isinstance(_safe_load_map(path), dict)
        and bool((_safe_load_map(path) or {}).get("focus_areas"))
    ]
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    max_exports = int(os.environ.get("SAVED_MAP_REPLAY_MAX_EXPORTS", "8") or "8")
    return paths[:max_exports]


def _safe_load_map(path: Path) -> dict[str, Any] | None:
    try:
        data = _load_json(path)
        interview_map = data.get("interview_trajectory_map") if isinstance(data, dict) else None
        return interview_map if isinstance(interview_map, dict) else None
    except Exception:
        return None


def _first_two_ready(validation: dict[str, Any]) -> bool:
    reports = validation.get("focus_reports") if isinstance(validation, dict) else []
    return sum(1 for item in (reports or [])[:2] if isinstance(item, dict) and item.get("ready")) >= 2


def _focus_summary(interview_map: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for area in (interview_map.get("focus_areas") or [])[:6]:
        if not isinstance(area, dict):
            continue
        rows.append(
            {
                "focus_key": area.get("focus_key"),
                "label": area.get("label"),
                "track_source": area.get("track_source"),
                "track_model": area.get("track_model"),
                "schema": area.get("map_schema_version") or area.get("track_schema"),
                "opener": _track_opener(area),
                "dimension_count": len(interview_map_module._track_dimensions(area)),
                "ladder_count": len(area.get("question_ladder") or []),
                "sub_focus_count": len(area.get("sub_focuses") or []),
            }
        )
    return rows


def _validation_contract_classification(validation: dict[str, Any], focuses: list[dict[str, Any]]) -> str:
    errors = [str(item or "") for item in (validation.get("errors") or [])]
    if validation.get("ready"):
        return "current_contract_ready"
    if focuses and all(int(item.get("ladder_count") or 0) == 0 for item in focuses):
        if any("question_ladder missing postures" in error for error in errors):
            return "obsolete_legacy_pre_ladder_map"
    if any("surface probe empty" in error for error in errors):
        return "summary_or_track_missing_surface_probes"
    if any("missing focus" in error.lower() for error in errors):
        return "focus_attribution_contract_failure"
    return "current_contract_rejected"


def _case_for_key(key: object) -> Any | None:
    key_text = str(key or "").strip()
    if not key_text:
        return None
    return next((case for case in ROBUST_CASES if getattr(case, "key", "") == key_text), None)


async def _replay_runtime_map_start(
    *,
    source: str,
    source_session_id: str = "",
    source_question_count: Any = None,
    source_report_ready: Any = None,
    key: str = "",
    label: str = "",
    target_role: str = "",
    years_experience: str = "",
    resume: str = "",
    parsed_resume: dict[str, Any] | None = None,
    interview_map: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    validation = interview_map_module.validate_interview_map(
        interview_map,
        require_all_llm=False,
        min_llm_branch_ratio=0.72,
    )
    focus_areas = [
        item for item in (interview_map.get("focus_areas") or [])
        if isinstance(item, dict)
    ]
    result: dict[str, Any] = {
        "source": source,
        "source_session_id": source_session_id,
        "source_question_count": source_question_count,
        "source_report_ready": source_report_ready,
        "key": key,
        "label": label,
        "target_role": target_role,
        "years_experience": years_experience,
        "focus_count": len(focus_areas),
        "focuses": _focus_summary(interview_map),
        "validation": validation,
        "validation_ready": bool(validation.get("ready")),
        "first_two_ready": _first_two_ready(validation),
        "start_replay_ok": False,
    }
    result["contract_classification"] = _validation_contract_classification(
        validation,
        result["focuses"],
    )
    if not focus_areas:
        result["error"] = "export_missing_focus_areas"
        return result
    if not validation.get("ready"):
        result["error"] = "current_validation_rejected_saved_map"
        return result

    orch = Orchestrator()
    session_id = f"saved-map-replay-{uuid.uuid4()}"
    parsed_resume = parsed_resume if isinstance(parsed_resume, dict) else {}
    state = orch._build_initial_state(
        session_id=session_id,
        resume=str(resume or ""),
        github_links=[],
        parsed_resume=parsed_resume,
        target_role=str(target_role or ""),
        years_experience=str(years_experience or ""),
        prior_assessment_context=None,
        prior_assessment_prompt="",
    )
    first_focus = focus_areas[0]
    first_map_question = _track_opener(first_focus)
    if not first_map_question:
        result["error"] = "first_focus_missing_opener"
        return result
    state.update(
        {
            "interview_trajectory_map": interview_map,
            "interview_map_status": "ready",
            "interview_map_error": "",
            "interview_map_validation": validation,
            "interview_map_prepared_at": time.time(),
            "interview_agenda": initial_interview_agenda(interview_map),
            "prepped_next_question": first_map_question,
            "prepped_next_question_turn_number": 0,
            "prepped_next_context": {
                "route_kind": "trajectory_map_surface",
                "replay_seed": True,
            },
            "prepped_next_packet": _build_question_packet(
                question_text=first_map_question,
                sprint=1,
                route_kind="trajectory_map_surface",
                parsed_resume=parsed_resume,
                resume=str(resume or ""),
                followups=[],
                source_turn_number=0,
                focus_key_override=str(first_focus.get("focus_key") or ""),
                focus_label_override=str(first_focus.get("label") or ""),
                question_posture="frame",
                signal_goal="Saved-map replay startup seed",
                expected_space=[],
                information_gain="high",
                voice_complexity="low",
                ladder_field="question_ladder.frame.main_question",
            ),
        }
    )
    await orch.session_manager.save_state(session_id, state)
    try:
        await orch.start_prepared_session(session_id)
        replay_state = await orch.session_manager.get_state(session_id)
        active_packet = replay_state.get("active_question_packet") or {}
        prepped_packet = replay_state.get("prepped_next_packet") or {}
        result.update(
            {
                "start_replay_ok": True,
                "replay_session_id": session_id,
                "opening_question": replay_state.get("last_question"),
                "opening_is_warm_open": replay_state.get("last_question") == SPRINT_OPENERS[1],
                "active_route": active_packet.get("route_kind"),
                "prepped_route": prepped_packet.get("route_kind"),
                "prepped_focus_key": prepped_packet.get("focus_key"),
                "prepped_question": replay_state.get("prepped_next_question"),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }
        )
    except Exception as exc:
        result.update(
            {
                "start_replay_ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:800],
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }
        )
    finally:
        try:
            await orch.session_manager.delete_session(session_id)
        except Exception:
            pass
    return result


async def _replay_export_start(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    interview_map = data.get("interview_trajectory_map") or {}
    return await _replay_runtime_map_start(
        source=str(path),
        source_session_id=str(data.get("session_id") or ""),
        source_question_count=data.get("question_count"),
        source_report_ready=data.get("report_ready"),
        target_role=str(data.get("target_role") or ""),
        years_experience=str(data.get("years_experience") or ""),
        resume=str(data.get("resume") or ""),
        parsed_resume=data.get("parsed_resume") if isinstance(data.get("parsed_resume"), dict) else {},
        interview_map=interview_map,
    )


async def _replay_map_policy_runtime_start(path: Path, item: dict[str, Any]) -> dict[str, Any] | None:
    interview_map = item.get("interview_trajectory_map")
    if not isinstance(interview_map, dict) or not interview_map.get("focus_areas"):
        return None
    case = _case_for_key(item.get("key"))
    return await _replay_runtime_map_start(
        source=str(path),
        key=str(item.get("key") or ""),
        label=str(item.get("label") or ""),
        target_role=str(item.get("target_role") or getattr(case, "target_role", "") or ""),
        years_experience=str(item.get("years_experience") or getattr(case, "years_experience", "") or ""),
        resume=str(item.get("resume") or getattr(case, "resume", "") or ""),
        parsed_resume=item.get("parsed_resume") if isinstance(item.get("parsed_resume"), dict) else {},
        interview_map=interview_map,
    )


def _route_repetition(turns: list[dict[str, Any]]) -> dict[str, Any]:
    max_focus_streak = 0
    max_surface_streak = 0
    focus_streak = 0
    surface_streak = 0
    last_focus = ""
    last_surface = ""
    focus_sequence: list[str] = []
    surface_sequence: list[str] = []
    for turn in turns:
        route = str(turn.get("route_kind") or "")
        if route not in MAP_BACKED_ROUTES:
            continue
        focus = str(turn.get("answered_focus_key") or turn.get("state_focus_key") or "").strip()
        surface = str(
            turn.get("answered_sub_focus_key")
            or turn.get("coverage_dimension_id")
            or turn.get("coverage_dimension_label")
            or focus
            or ""
        ).strip()
        if focus:
            focus_sequence.append(focus)
            focus_streak = focus_streak + 1 if focus == last_focus else 1
            max_focus_streak = max(max_focus_streak, focus_streak)
            last_focus = focus
        if surface:
            surface_sequence.append(surface)
            surface_streak = surface_streak + 1 if surface == last_surface else 1
            max_surface_streak = max(max_surface_streak, surface_streak)
            last_surface = surface
    return {
        "max_same_focus_streak": max_focus_streak,
        "max_same_surface_streak": max_surface_streak,
        "distinct_focuses": len(set(focus_sequence)),
        "distinct_surfaces": len(set(surface_sequence)),
        "focus_sequence": focus_sequence,
        "surface_sequence": surface_sequence,
    }


def _analyze_full_artifact(path: Path) -> list[dict[str, Any]]:
    try:
        payload = _load_json(path)
    except Exception as exc:
        return [{"source": str(path), "artifact_error": f"{type(exc).__name__}: {exc}"}]
    if not isinstance(payload, list):
        return [{"source": str(path), "artifact_error": "expected_list"}]
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        turns = item.get("turns") if isinstance(item.get("turns"), list) else []
        routes = [str(t.get("route_kind") or "") for t in turns if isinstance(t, dict)]
        phases = [str(t.get("agenda_phase") or "") for t in turns if isinstance(t, dict)]
        warnings = sorted(
            {
                str(code)
                for turn in turns
                if isinstance(turn, dict)
                for code in (turn.get("policy_warning_codes") or [])
                if str(code)
            }
        )
        map_missing_focus = [
            int(turn.get("turn") or 0)
            for turn in turns
            if isinstance(turn, dict)
            and str(turn.get("route_kind") or "") in MAP_BACKED_ROUTES
            and not str(turn.get("answered_focus_key") or turn.get("state_focus_key") or "").strip()
        ]
        close_routes = [
            idx + 1 for idx, route in enumerate(routes)
            if route in {"synthesis_close", "graceful_exit", "complete"}
        ]
        rows.append(
            {
                "source": str(path),
                "key": item.get("key"),
                "label": item.get("label"),
                "ok": item.get("ok"),
                "error_type": item.get("error_type"),
                "error": item.get("error"),
                "turn_count": len(turns),
                "question_count": item.get("question_count"),
                "quality_gate": item.get("quality_gate"),
                "routes": routes,
                "phases": phases,
                "application_grounding_turn": item.get("application_grounding_turn"),
                "application_transfer_turn": item.get("application_transfer_turn"),
                "coverage_turns": item.get("coverage_turns") or [],
                "second_anchor_turn": item.get("second_anchor_turn"),
                "route_repetition_recomputed": _route_repetition(turns),
                "policy_warning_codes": warnings,
                "map_backed_missing_focus_turns": map_missing_focus,
                "close_turns": close_routes,
                "final_recommendation": (item.get("final_evaluation") or {}).get("hire_recommendation"),
                "final_score": (item.get("final_evaluation") or {}).get("overall_score"),
                "map_failure_diagnostics": item.get("map_failure_diagnostics") or {},
            }
        )
    return rows


def _analyze_map_policy_artifact(path: Path) -> list[dict[str, Any]]:
    try:
        payload = _load_json(path)
    except Exception as exc:
        return [{"source": str(path), "artifact_error": f"{type(exc).__name__}: {exc}"}]
    if not isinstance(payload, list):
        return [{"source": str(path), "artifact_error": "expected_list"}]
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        has_runtime_map = isinstance(item.get("interview_trajectory_map"), dict)
        focus_summaries = item.get("focus_areas") if isinstance(item.get("focus_areas"), list) else []
        summary_has_ladder = any(
            isinstance(area, dict) and isinstance(area.get("question_ladder"), list) and area.get("question_ladder")
            for area in focus_summaries
        )
        summary_has_dimensions = any(
            isinstance(area, dict) and isinstance(area.get("dimensions"), list) and area.get("dimensions")
            for area in focus_summaries
        )
        summary_has_surface_probes = any(
            isinstance(area, dict)
            and any(
                isinstance(surface, dict)
                and (
                    surface.get("surface_probe")
                    or surface.get("mechanism_probe")
                    or surface.get("boundary_probe")
                )
                for surface in (area.get("sub_focuses") or [])
            )
            for area in focus_summaries
        )
        if has_runtime_map:
            classification = "runtime_map_replayable"
        elif summary_has_ladder and summary_has_dimensions and not summary_has_surface_probes:
            classification = "summary_only_ladder_map_missing_runtime_surface_probes"
        else:
            classification = "summary_only_not_start_replayable"
        rows.append(
            {
                "source": str(path),
                "key": item.get("key"),
                "label": item.get("label"),
                "ok": item.get("ok"),
                "elapsed_ms": item.get("elapsed_ms"),
                "first_two_launch_ready": item.get("first_two_launch_ready"),
                "launch_ready": item.get("launch_ready"),
                "full_map_ready": item.get("full_map_ready"),
                "focus_count": item.get("focus_count") or len(focus_summaries),
                "has_runtime_map": has_runtime_map,
                "classification": classification,
                "summary_has_ladder": summary_has_ladder,
                "summary_has_dimensions": summary_has_dimensions,
                "summary_has_surface_probes": summary_has_surface_probes,
                "failure_diagnostics": item.get("map_failure_diagnostics") or {},
                "focuses": [
                    {
                        "focus_key": area.get("focus_key"),
                        "label": area.get("label"),
                        "dimension_count": area.get("dimension_count"),
                        "ladder_count": area.get("question_ladder_count"),
                        "opener": area.get("opener"),
                    }
                    for area in focus_summaries[:4]
                    if isinstance(area, dict)
                ],
            }
        )
    return rows


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# Saved Map Replay Report", ""]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    summary = report.get("summary") or {}
    lines.append("## Summary")
    for key, value in summary.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Saved Full-Map Start Replays")
    lines.append("")
    lines.append("| Source | Role | Focuses | Valid | First 2 | Start | Opening | Prepped Focus |")
    lines.append("|---|---|---:|---:|---:|---:|---|---|")
    for row in report.get("start_replays", []):
        lines.append(
            f"| `{Path(row.get('source', '')).name}` | {_clean(row.get('target_role'), 50)} | "
            f"{row.get('focus_count')} | {row.get('validation_ready')} | {row.get('first_two_ready')} | "
            f"{row.get('start_replay_ok')} | {_clean(row.get('opening_question'), 120)} | "
            f"`{_clean(row.get('prepped_focus_key'), 80)}` |"
        )
        if row.get("error") or row.get("error_type"):
            lines.append(
                f"|  |  |  |  |  |  | class=`{row.get('contract_classification')}` "
                f"error=`{_clean(row.get('error') or row.get('error_type'), 220)}` |  |"
            )
    for row in report.get("start_replays", []):
        lines.extend(["", f"### `{Path(row.get('source', '')).name}`", ""])
        lines.append(f"- Source session: `{row.get('source_session_id')}`")
        lines.append(f"- Validation errors: `{json.dumps((row.get('validation') or {}).get('errors') or [], ensure_ascii=True)[:900]}`")
        lines.append("- Focuses:")
        for focus in row.get("focuses", []) or []:
            lines.append(
                f"  - `{focus.get('focus_key')}` {_clean(focus.get('label'), 120)} "
                f"dims={focus.get('dimension_count')} ladder={focus.get('ladder_count')} "
                f"opener={_clean(focus.get('opener'), 180)}"
            )
    lines.extend(["", "## Raw Map-Policy Start Replays", ""])
    lines.append("| Source | Case | Role | Focuses | Valid | First 2 | Start | Opening | Prepped Focus |")
    lines.append("|---|---|---|---:|---:|---:|---:|---|---|")
    for row in report.get("map_policy_start_replays", []):
        lines.append(
            f"| `{Path(row.get('source', '')).name}` | {_clean(row.get('key') or row.get('label'), 50)} | "
            f"{_clean(row.get('target_role'), 50)} | {row.get('focus_count')} | "
            f"{row.get('validation_ready')} | {row.get('first_two_ready')} | {row.get('start_replay_ok')} | "
            f"{_clean(row.get('opening_question'), 120)} | `{_clean(row.get('prepped_focus_key'), 80)}` |"
        )
        if row.get("error") or row.get("error_type"):
            lines.append(
                f"|  |  |  |  |  |  |  | class=`{row.get('contract_classification')}` "
                f"error=`{_clean(row.get('error') or row.get('error_type'), 220)}` |  |"
            )
    lines.extend(["", "## Historical Full-Run Artifact Analysis", ""])
    lines.append("| Source | Case | OK | Turns | App | Coverage | Second | Focus Streak | Surface Streak | Gate Failures |")
    lines.append("|---|---|---:|---:|---:|---|---:|---:|---:|---|")
    for row in report.get("full_artifacts", []):
        rep = row.get("route_repetition_recomputed") or {}
        gate = row.get("quality_gate") or {}
        lines.append(
            f"| `{Path(row.get('source', '')).name}` | {_clean(row.get('key') or row.get('label'), 50)} | "
            f"{row.get('ok')} | {row.get('turn_count')} | {row.get('application_transfer_turn')} | "
            f"{row.get('coverage_turns')} | {row.get('second_anchor_turn')} | "
            f"{rep.get('max_same_focus_streak')} | {rep.get('max_same_surface_streak')} | "
            f"`{json.dumps(gate.get('failures') or [], ensure_ascii=True)[:220]}` |"
        )
    lines.extend(["", "## Map Policy Artifact Classification", ""])
    lines.append("| Source | Case | OK | Focuses | First 2 | Class |")
    lines.append("|---|---|---:|---:|---:|---|")
    for row in report.get("map_policy_artifacts", []):
        lines.append(
            f"| `{Path(row.get('source', '')).name}` | {_clean(row.get('key') or row.get('label'), 50)} | "
            f"{row.get('ok')} | {row.get('focus_count')} | {row.get('first_two_launch_ready')} | "
            f"`{row.get('classification')}` |"
        )
    lines.extend(["", "## Takeaways", ""])
    for item in report.get("takeaways", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    prefix = os.environ.get("SAVED_MAP_REPLAY_OUTPUT_PREFIX", "/tmp/antigravity_saved_map_replay")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = Path(f"{prefix}_{stamp}.json")
    md_path = Path(f"{prefix}_{stamp}.md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(f"[SavedMapReplay] Wrote {json_path}")
    print(f"[SavedMapReplay] Wrote {md_path}")
    return json_path, md_path


async def main() -> None:
    start_replays = []
    for path in _full_export_paths():
        print(f"[SavedMapReplay] Start replay: {path.name}", flush=True)
        start_replays.append(await _replay_export_start(path))

    full_glob = os.environ.get("SAVED_MAP_REPLAY_FULL_GLOB", "/tmp/antigravity_*full*.json")
    full_paths = sorted([Path(p) for p in glob.glob(full_glob)], key=lambda p: p.stat().st_mtime, reverse=True)[:16]
    full_rows: list[dict[str, Any]] = []
    for path in full_paths:
        full_rows.extend(_analyze_full_artifact(path))

    map_glob = os.environ.get("SAVED_MAP_REPLAY_MAP_GLOB", "/tmp/antigravity_*map_policy.json")
    map_paths = sorted([Path(p) for p in glob.glob(map_glob)], key=lambda p: p.stat().st_mtime, reverse=True)[:16]
    map_rows: list[dict[str, Any]] = []
    map_policy_start_replays: list[dict[str, Any]] = []
    for path in map_paths:
        map_rows.extend(_analyze_map_policy_artifact(path))
        try:
            payload = _load_json(path)
        except Exception:
            payload = None
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    replay = await _replay_map_policy_runtime_start(path, item)
                    if replay:
                        map_policy_start_replays.append(replay)

    failed_starts = [row for row in start_replays if not row.get("start_replay_ok")]
    obsolete_starts = [
        row for row in start_replays
        if row.get("contract_classification") == "obsolete_legacy_pre_ladder_map"
    ]
    full_failures = [
        row for row in full_rows
        if row.get("quality_gate") and not (row.get("quality_gate") or {}).get("passed")
    ]
    summary = {
        "full_map_exports_replayed": len(start_replays),
        "start_replay_passed": sum(1 for row in start_replays if row.get("start_replay_ok")),
        "start_replay_failed": len(failed_starts),
        "obsolete_legacy_pre_ladder_exports": len(obsolete_starts),
        "historical_full_cases_analyzed": len(full_rows),
        "historical_full_quality_failures": len(full_failures),
        "map_policy_artifacts_classified": len(map_rows),
        "runtime_replayable_map_policy_artifacts": sum(1 for row in map_rows if row.get("has_runtime_map")),
        "runtime_map_policy_start_replays": len(map_policy_start_replays),
        "runtime_map_policy_start_replay_passed": sum(
            1 for row in map_policy_start_replays if row.get("start_replay_ok")
        ),
        "summary_only_map_policy_artifacts": sum(1 for row in map_rows if not row.get("has_runtime_map")),
        "summary_only_ladder_maps_missing_surface_probes": sum(
            1
            for row in map_rows
            if row.get("classification") == "summary_only_ladder_map_missing_runtime_surface_probes"
        ),
    }
    takeaways = []
    if failed_starts and len(failed_starts) != len(obsolete_starts):
        takeaways.append(
            "Some saved full maps no longer pass today's start contract; inspect validation errors before paid runs."
        )
    elif obsolete_starts:
        takeaways.append(
            "Saved full session exports are obsolete pre-ladder maps; their rejection is a schema-migration artifact, not proof that today's map generator failed."
        )
    else:
        takeaways.append(
            "Saved full runtime maps that validate under today's contract can start cleanly without regenerating maps."
        )
    if full_failures:
        takeaways.append(
            "Historical full-run artifacts still contain quality-gate failures; use them as posthoc route/report regression fixtures."
        )
    if summary["summary_only_map_policy_artifacts"]:
        takeaways.append(
            "Most `/tmp` map-policy files are summaries, not raw runtime maps; they are good for human map review but cannot prove startup replay."
        )
    if map_policy_start_replays:
        takeaways.append(
            "Raw runtime maps embedded in map-policy artifacts replayed "
            f"{summary['runtime_map_policy_start_replay_passed']}/{summary['runtime_map_policy_start_replays']} "
            "through today's startup contract."
        )
    if summary["summary_only_ladder_maps_missing_surface_probes"]:
        takeaways.append(
            "Recent map-policy summaries include the new ladder questions, but omit runtime surface-probe fields, so they cannot be faithfully replayed unless we persist the raw map."
        )
    takeaways.append(
        "This harness intentionally does not prove fresh Gemini/Sonnet map generation quality, latency, or live per-turn LLM behavior."
    )
    report = {
        "summary": summary,
        "start_replays": start_replays,
        "map_policy_start_replays": map_policy_start_replays,
        "full_artifacts": full_rows,
        "map_policy_artifacts": map_rows,
        "takeaways": takeaways,
    }
    _write_report(report)


if __name__ == "__main__":
    asyncio.run(main())
