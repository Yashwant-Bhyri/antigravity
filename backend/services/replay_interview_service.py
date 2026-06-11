from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.interview_telemetry import interview_telemetry


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:80] or "case"


class ReplayInterviewService:
    """
    Deterministic replay adapter for the live voice room.

    A replay session intentionally uses the normal live endpoints, but answers are
    advanced against saved artifacts instead of the interview orchestrator. This
    keeps Deepgram, TTS, frontend floor state, telemetry, and room rendering real
    while guaranteeing zero LLM spend for sessions prefixed with ``replay_``.
    """

    session_prefix = "replay_"

    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self._cases_cache: dict[str, dict[str, Any]] | None = None
        self._case_cache_loaded_at = 0.0
        self._sessions: dict[str, dict[str, Any]] = {}
        self._captures: dict[str, list[dict[str, Any]]] = {}

    def is_replay_session(self, session_id: str) -> bool:
        return str(session_id or "").startswith(self.session_prefix)

    def _artifact_paths(self) -> list[Path]:
        patterns = [
            "/tmp/antigravity_v1_*full_gate.json",
            "/tmp/antigravity_v1_gate_*full_gate.json",
            "/tmp/antigravity_v1_edge_*full_gate.json",
            "/tmp/antigravity_surface_preserve_full_*full_gate.json",
            "/tmp/antigravity_map_v3_*full_gate.json",
            str(self.root / "backend" / "data" / "session_exports" / "*.json"),
        ]
        paths: list[Path] = []
        for pattern in patterns:
            paths.extend(sorted(Path("/").glob(pattern.lstrip("/"))))
        unique: dict[str, Path] = {str(path): path for path in paths if path.exists()}
        return sorted(unique.values(), key=lambda item: str(item))

    def _read_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _normalize_turns_from_gate(self, raw_turns: list[Any]) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_turns, start=1):
            turn = _as_dict(raw)
            question = _clean_text(turn.get("question"))
            answer = _clean_text(turn.get("answer"))
            next_question = _clean_text(turn.get("ai_response"))
            if not question and not next_question:
                continue
            turns.append(
                {
                    "turn": int(turn.get("turn") or index),
                    "question": question,
                    "saved_answer": answer,
                    "next_question": next_question,
                    "route_kind": _clean_text(turn.get("route_kind")) or "replay_turn",
                    "agenda_phase": _clean_text(turn.get("agenda_phase")),
                    "answer_bucket": _clean_text(turn.get("answer_bucket")),
                    "source_metadata": {
                        key: turn.get(key)
                        for key in (
                            "coverage_surface_kind",
                            "coverage_focus_key",
                            "focus_key",
                            "question_count",
                            "policy_warnings",
                        )
                        if key in turn
                    },
                }
            )
        return turns

    def _case_from_full_gate(self, item: dict[str, Any], path: Path, index: int) -> dict[str, Any] | None:
        turns = self._normalize_turns_from_gate(_as_list(item.get("turns")))
        opening_question = _clean_text(item.get("opening_question")) or (turns[0]["question"] if turns else "")
        if not opening_question:
            return None

        key_hint = _clean_text(item.get("key")) or path.stem
        label = _clean_text(item.get("label")) or key_hint.replace("_", " ").title()
        case_id = _slug(f"{key_hint}_{index}_{path.stem}")
        final_evaluation = _as_dict(item.get("final_evaluation"))
        candidate_name = (
            _clean_text(_as_dict(item.get("parsed_resume")).get("name"))
            or _clean_text(_as_dict(item.get("parsed_resume")).get("candidate_name"))
            or _clean_text(item.get("candidate_name"))
            or label
        )
        return {
            "case_id": case_id,
            "label": label,
            "source_type": "full_gate_artifact",
            "source_path": str(path),
            "target_role": _clean_text(item.get("target_role")) or "Candidate",
            "years_experience": _clean_text(item.get("years_experience")) or "",
            "candidate_name": candidate_name,
            "resume": _clean_text(item.get("resume")) or _clean_text(item.get("resume_text")),
            "parsed_resume": _as_dict(item.get("parsed_resume")) or {"name": candidate_name},
            "opening_question": opening_question,
            "turns": turns,
            "turn_count": len(turns),
            "final_evaluation": final_evaluation,
            "quality_gate": _as_dict(item.get("quality_gate")),
            "interview_trajectory_map": _as_dict(item.get("interview_trajectory_map")),
            "map_available": bool(item.get("interview_trajectory_map")),
            "report_available": bool(final_evaluation),
        }

    def _case_from_session_export(self, item: dict[str, Any], path: Path) -> dict[str, Any] | None:
        history = _as_list(item.get("history"))
        if not history and not _clean_text(item.get("last_question")):
            return None
        turns: list[dict[str, Any]] = []
        for index, raw in enumerate(history, start=1):
            entry = _as_dict(raw)
            next_entry = _as_dict(history[index]) if index < len(history) else {}
            turns.append(
                {
                    "turn": index,
                    "question": _clean_text(entry.get("question")),
                    "saved_answer": _clean_text(entry.get("answer")),
                    "next_question": _clean_text(next_entry.get("question")),
                    "route_kind": _clean_text(entry.get("route_kind")) or "session_export_replay",
                    "agenda_phase": _clean_text(entry.get("agenda_phase")),
                    "answer_bucket": "",
                    "source_metadata": {},
                }
            )
        opening_question = (turns[0]["question"] if turns else "") or _clean_text(item.get("last_question"))
        if not opening_question:
            return None
        session_id = _clean_text(item.get("session_id")) or path.stem
        parsed_resume = _as_dict(item.get("parsed_resume"))
        candidate_name = (
            _clean_text(parsed_resume.get("name"))
            or _clean_text(parsed_resume.get("candidate_name"))
            or _clean_text(parsed_resume.get("full_name"))
            or "Session Export"
        )
        return {
            "case_id": _slug(f"export_{session_id}_{path.stem}"),
            "label": f"Export: {candidate_name}",
            "source_type": "session_export",
            "source_path": str(path),
            "target_role": _clean_text(item.get("target_role")) or "Candidate",
            "years_experience": _clean_text(item.get("years_experience")) or "",
            "candidate_name": candidate_name,
            "resume": _clean_text(item.get("resume")),
            "parsed_resume": parsed_resume or {"name": candidate_name},
            "opening_question": opening_question,
            "turns": turns,
            "turn_count": len(turns),
            "final_evaluation": _as_dict(item.get("final_evaluation")),
            "quality_gate": _as_dict(item.get("quality_gate")),
            "interview_trajectory_map": _as_dict(item.get("interview_trajectory_map")),
            "map_available": bool(item.get("interview_trajectory_map")),
            "report_available": bool(item.get("final_evaluation")),
        }

    def _load_cases(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        if self._cases_cache is not None and now - self._case_cache_loaded_at < 8:
            return self._cases_cache

        cases: dict[str, dict[str, Any]] = {}
        for path in self._artifact_paths():
            payload = self._read_json(path)
            items = payload if isinstance(payload, list) else [payload]
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                if path.name.startswith("session_export") or "session_exports" in str(path):
                    case = self._case_from_session_export(item, path)
                else:
                    case = self._case_from_full_gate(item, path, index)
                if case:
                    cases[case["case_id"]] = case

        self._cases_cache = cases
        self._case_cache_loaded_at = now
        return cases

    async def list_cases(self) -> dict[str, Any]:
        cases = self._load_cases()
        rows = []
        for case in sorted(cases.values(), key=lambda item: item["label"]):
            rows.append(
                {
                    "case_id": case["case_id"],
                    "label": case["label"],
                    "source_type": case["source_type"],
                    "source_path": case["source_path"],
                    "target_role": case["target_role"],
                    "years_experience": case["years_experience"],
                    "candidate_name": case["candidate_name"],
                    "turn_count": case["turn_count"],
                    "map_available": case["map_available"],
                    "report_available": case["report_available"],
                }
            )
        return {"cases": rows, "count": len(rows)}

    async def start_case(self, case_id: str, *, max_turns: int = 0) -> dict[str, Any]:
        cases = self._load_cases()
        case = cases.get(case_id)
        if not case:
            raise KeyError(case_id)

        created = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_id = f"{self.session_prefix}{case_id}_{created}"
        turns = list(case["turns"])
        if max_turns and max_turns > 0:
            turns = turns[:max_turns]
        session = {
            "session_id": session_id,
            "case": case,
            "turns": turns,
            "cursor": 0,
            "history": [],
            "question_count": 0,
            "last_question": case["opening_question"],
            "interview_complete": False,
            "report_ready": False,
            "finalization_status": "not_started",
            "created_at": created,
            "partials": [],
        }
        self._sessions[session_id] = session
        self._captures[session_id] = []
        await interview_telemetry.log(
            session_id,
            "replay.session_started",
            source="backend.replay",
            case_id=case_id,
            label=case["label"],
            turn_count=len(turns),
            source_path=case["source_path"],
            llm_calls_allowed=False,
        )
        return {
            "session_id": session_id,
            "case_id": case_id,
            "opening_question": case["opening_question"],
            "turn_count": len(turns),
            "target_role": case["target_role"],
            "candidate_name": case["candidate_name"],
            "zero_llm": True,
        }

    def _snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        case = session["case"]
        return {
            "session_id": session["session_id"],
            "question_count": session["question_count"],
            "interview_complete": bool(session["interview_complete"]),
            "report_ready": bool(session["report_ready"]),
            "finalization_status": session["finalization_status"],
            "resume": case.get("resume", ""),
            "github_links": [],
            "target_role": case.get("target_role", ""),
            "years_experience": case.get("years_experience", ""),
            "current_sprint": 1,
            "current_persona": "Replay interviewer",
            "last_question": "" if session["interview_complete"] else session["last_question"],
            "history": session["history"],
            "parsed_resume": case.get("parsed_resume") or {"name": case.get("candidate_name", "Candidate")},
            "interview_trajectory_map": case.get("interview_trajectory_map") or {},
            "final_evaluation": case.get("final_evaluation") or {},
            "quality_gate": case.get("quality_gate") or {},
            "replay_metadata": {
                "case_id": case["case_id"],
                "label": case["label"],
                "source_type": case["source_type"],
                "source_path": case["source_path"],
                "turn_count": len(session["turns"]),
                "cursor": session["cursor"],
                "zero_llm": True,
            },
        }

    async def get_state(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return self._snapshot(session)

    async def partial_transcript(
        self,
        session_id: str,
        transcript: str,
        *,
        entities: list[str] | None = None,
        turn_id: str = "",
        is_final: bool = True,
        snapshot_seq: int = 0,
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        session["partials"].append(
            {
                "turn_id": turn_id,
                "snapshot_seq": snapshot_seq,
                "is_final": is_final,
                "transcript": transcript,
                "entities": entities or [],
                "ts": round(time.time(), 3),
            }
        )
        await interview_telemetry.log(
            session_id,
            "replay.partial_transcript",
            source="backend.replay",
            turn_id=turn_id,
            is_final=is_final,
            snapshot_seq=snapshot_seq,
            transcript_chars=len(transcript or ""),
            transcript_words=len((transcript or "").split()),
            entities_count=len(entities or []),
        )
        return {"ok": True, "replay": True}

    async def process_turn(
        self,
        session_id: str,
        transcript: str,
        *,
        entities: list[str] | None = None,
        turn_id: str = "",
        revision_of_turn_id: str = "",
        revision_question: str = "",
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        if session["interview_complete"]:
            return {
                "response": "",
                "complete": True,
                "question_count": session["question_count"],
                "route_kind": "replay_complete",
                "turn_id": turn_id,
                "replay": True,
            }

        history = session["history"]
        previous_answer = _clean_text(history[-1].get("answer")) if history else ""
        cleaned_transcript = _clean_text(transcript)
        revision_question_clean = _clean_text(revision_question)
        revision_index = -1
        if history and (revision_of_turn_id or revision_question_clean):
            for idx in range(len(history) - 1, -1, -1):
                item = history[idx]
                item_turn_id = _clean_text(item.get("turn_id"))
                item_question = _clean_text(item.get("question"))
                if revision_of_turn_id and item_turn_id == revision_of_turn_id:
                    revision_index = idx
                    break
                if revision_question_clean and item_question == revision_question_clean:
                    revision_index = idx
                    break
        is_same_turn_revision = bool(
            history
            and (
                revision_index >= 0
                or (turn_id and history[-1].get("turn_id") == turn_id)
                or (
                    not history[-1].get("turn_id")
                    and previous_answer
                    and cleaned_transcript.startswith(previous_answer)
                )
            )
        )
        if is_same_turn_revision:
            target_index = revision_index if revision_index >= 0 else len(history) - 1
            target_item = history[target_index]
            target_previous_answer = _clean_text(target_item.get("answer"))
            revised_answer = transcript
            if target_previous_answer and not cleaned_transcript.startswith(target_previous_answer):
                revised_answer = f"{target_previous_answer} {transcript}".strip()
            target_item["answer"] = revised_answer
            if revision_of_turn_id and not target_item.get("turn_id"):
                target_item["turn_id"] = revision_of_turn_id
            await interview_telemetry.log(
                session_id,
                "replay.process_turn_revision",
                source="backend.replay",
                turn_id=turn_id,
                transcript_chars=len(transcript or ""),
                transcript_words=len((transcript or "").split()),
                question_count=session["question_count"],
                cursor=session["cursor"],
                revision_index=target_index,
                revision_of_turn_id=revision_of_turn_id,
            )
            return {
                "response": session.get("last_question") or "",
                "complete": False,
                "question_count": session["question_count"],
                "route_kind": "replay_revision",
                "agenda_phase": "replay_revision",
                "turn_id": turn_id,
                "replay": True,
                "zero_llm": True,
                "revision": True,
            }

        cursor = int(session["cursor"])
        turns = session["turns"]
        turn = turns[cursor] if cursor < len(turns) else {}
        current_question = session["last_question"] or _clean_text(turn.get("question"))
        session["history"].append(
            {
                "turn_id": turn_id,
                "question": current_question,
                "answer": transcript,
                "sprint": 1,
                "route_kind": _clean_text(turn.get("route_kind")) or "replay_turn",
                "agenda_phase": _clean_text(turn.get("agenda_phase")),
                "replay_saved_answer": _clean_text(turn.get("saved_answer")),
            }
        )
        session["cursor"] = cursor + 1
        session["question_count"] = len(session["history"])

        next_question = _clean_text(turn.get("next_question"))
        if not next_question and cursor + 1 < len(turns):
            next_question = _clean_text(_as_dict(turns[cursor + 1]).get("question"))

        complete = not next_question or session["cursor"] >= len(turns)
        if complete:
            session["interview_complete"] = True
            session["report_ready"] = bool(session["case"].get("final_evaluation"))
            session["finalization_status"] = "complete" if session["report_ready"] else "replay_complete"
            session["last_question"] = ""
        else:
            session["last_question"] = next_question

        await interview_telemetry.log(
            session_id,
            "replay.process_turn",
            source="backend.replay",
            turn_id=turn_id,
            cursor=cursor,
            route_kind=_clean_text(turn.get("route_kind")) or "replay_turn",
            agenda_phase=_clean_text(turn.get("agenda_phase")),
            transcript_chars=len(transcript or ""),
            transcript_words=len((transcript or "").split()),
            entities_count=len(entities or []),
            question_count=session["question_count"],
            complete=complete,
        )
        return {
            "response": next_question,
            "complete": complete,
            "question_count": session["question_count"],
            "route_kind": _clean_text(turn.get("route_kind")) or "replay_turn",
            "agenda_phase": _clean_text(turn.get("agenda_phase")),
            "turn_id": turn_id,
            "replay": True,
            "zero_llm": True,
        }

    async def end_interview(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        session["interview_complete"] = True
        session["report_ready"] = bool(session["case"].get("final_evaluation"))
        session["finalization_status"] = "complete" if session["report_ready"] else "replay_complete"
        evaluation = session["case"].get("final_evaluation") or {}
        await interview_telemetry.log(
            session_id,
            "replay.end_interview",
            source="backend.replay",
            question_count=session["question_count"],
            history_len=len(session["history"]),
            hire_recommendation=evaluation.get("hire_recommendation"),
            overall_score=evaluation.get("overall_score"),
        )
        return {
            "session_id": session_id,
            "complete": True,
            "report_ready": bool(session["report_ready"]),
            "finalization_status": session["finalization_status"],
            "hire_recommendation": evaluation.get("hire_recommendation", "N/A"),
            "overall_score": evaluation.get("overall_score", 0),
            "summary": evaluation.get("summary", ""),
            "replay": True,
            "zero_llm": True,
        }

    async def record_capture(self, session_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_replay_session(session_id):
            raise KeyError(session_id)
        capture = {
            "ts": round(time.time(), 3),
            "event_type": event_type,
            "payload": payload or {},
        }
        self._captures.setdefault(session_id, []).append(capture)
        await interview_telemetry.log(
            session_id,
            f"replay.capture.{event_type}",
            source="qa.capture",
            **(payload or {}),
        )
        return {"ok": True, "capture_count": len(self._captures[session_id])}

    def _llm_like_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flagged: list[dict[str, Any]] = []
        markers = ("openrouter", "llm_router", "llm.", "anthropic", "claude", "gemini", "deepseek", "gpt-5")
        for event in events:
            event_name = _clean_text(event.get("event")).lower()
            source = _clean_text(event.get("source")).lower()
            provider = _clean_text(event.get("provider") or event.get("provider_used")).lower()
            model = _clean_text(event.get("model")).lower()
            # TTS and Deepgram providers are allowed in replay QA.
            if event_name.startswith("api.tts") or "deepgram" in provider or source.startswith("frontend"):
                continue
            haystack = " ".join([event_name, source, provider, model])
            if any(marker in haystack for marker in markers):
                flagged.append(event)
        return flagged

    def _status(self, passed: bool, detail: str, *, count: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"passed": bool(passed), "detail": detail}
        if count is not None:
            result["count"] = count
        return result

    def _qa_checks(self, events: list[dict[str, Any]], captures: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        event_names = [_clean_text(event.get("event")) for event in events]
        llm_events = self._llm_like_events(events)
        partial_count = sum(1 for name in event_names if name in {"api.partial_transcript", "replay.partial_transcript", "partial_snapshot_sent"})
        commit_count = sum(1 for name in event_names if name in {"api.process_turn", "replay.process_turn", "room_turn_commit", "frontend_process_turn"})
        floor_count = sum(1 for name in event_names if name == "floor_transition")
        tts_count = sum(1 for name in event_names if name in {"api.tts", "frontend_tts_prefetch"})
        playback_count = sum(1 for name in event_names if name in {"frontend_audio_playback_done", "frontend_audio_playback_started"})
        filler_count = sum(1 for name in event_names if "tts_filler" in name or name == "frontend_tts_filler")
        barge_count = sum(1 for name in event_names if "barge" in name)
        silence_count = sum(1 for name in event_names if "silence" in name or "utterance_empty" in name)
        layout_captures = [capture for capture in captures if capture.get("event_type") in {"layout_snapshot", "screenshot"}]
        return {
            "zero_llm_guard": self._status(not llm_events, f"{len(llm_events)} LLM-like telemetry events recorded", count=len(llm_events)),
            "partials_recorded": self._status(partial_count > 0, f"{partial_count} partial/final transcript events recorded", count=partial_count),
            "final_commit_recorded": self._status(commit_count > 0, f"{commit_count} final commit/process events recorded", count=commit_count),
            "tts_recorded": self._status(tts_count > 0, f"{tts_count} TTS request/prefetch events recorded", count=tts_count),
            "playback_recorded": self._status(playback_count > 0, f"{playback_count} playback events recorded", count=playback_count),
            "floor_transitions_recorded": self._status(floor_count > 0, f"{floor_count} floor transitions recorded", count=floor_count),
            "filler_path_recorded": self._status(filler_count > 0, f"{filler_count} filler events recorded", count=filler_count),
            "barge_in_recorded": self._status(barge_count > 0, f"{barge_count} barge-in events recorded", count=barge_count),
            "silence_recorded": self._status(silence_count > 0, f"{silence_count} silence events recorded", count=silence_count),
            "layout_captures_recorded": self._status(bool(layout_captures), f"{len(layout_captures)} layout/screenshot captures recorded", count=len(layout_captures)),
            "history_consistent": self._status(
                len(state.get("history", [])) == int(state.get("question_count", 0) or 0),
                f"history={len(state.get('history', []))}, question_count={state.get('question_count', 0)}",
            ),
        }

    def _write_report_files(self, session_id: str, report: dict[str, Any]) -> dict[str, str]:
        base = Path("/tmp") / f"antigravity_replay_qa_{session_id}"
        json_path = base.with_suffix(".json")
        md_path = base.with_suffix(".md")
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        checks = report.get("checks", {})
        rows = []
        for name, check in checks.items():
            status = "PASS" if check.get("passed") else "WARN"
            rows.append(f"| {name} | {status} | {check.get('detail', '')} |")
        md = "\n".join(
            [
                f"# Replay QA Report: {session_id}",
                "",
                f"- Case: {report.get('case', {}).get('label', 'Unknown')}",
                f"- Source: `{report.get('case', {}).get('source_path', '')}`",
                f"- Events: {len(report.get('events', []))}",
                f"- Captures: {len(report.get('captures', []))}",
                "",
                "## Checks",
                "",
                "| Check | Status | Detail |",
                "|---|---:|---|",
                *rows,
                "",
                "## Top Issues",
                "",
                *(f"- {issue.get('event')} ({issue.get('source')}): {issue.get('level', 'info')}" for issue in report.get("issues", [])[:12]),
            ]
        )
        md_path.write_text(md, encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path)}

    async def qa_report(self, session_id: str, *, write_files: bool = True) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        events = await interview_telemetry.get_events(session_id, limit=0)
        captures = self._captures.get(session_id, [])
        state = self._snapshot(session)
        checks = self._qa_checks(events, captures, state)
        issues = [
            event
            for event in events
            if event.get("level") in {"warn", "error"}
            or any(token in _clean_text(event.get("event")).lower() for token in ("fail", "error", "discard", "stale"))
        ]
        report = {
            "session_id": session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "case": {
                "case_id": session["case"]["case_id"],
                "label": session["case"]["label"],
                "source_type": session["case"]["source_type"],
                "source_path": session["case"]["source_path"],
            },
            "state": state,
            "checks": checks,
            "events": events,
            "captures": captures,
            "issues": issues,
        }
        if write_files:
            report["artifact_paths"] = self._write_report_files(session_id, report)
        return report


replay_interview_service = ReplayInterviewService()
