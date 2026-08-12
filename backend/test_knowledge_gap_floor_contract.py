"""No-provider contracts for the production knowledge-gap viability floor."""

from __future__ import annotations

import asyncio
import copy
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

# Importing the production route module constructs its module-level service
# graph.  A temporary sentinel keeps this no-provider contract importable
# without reading any credential file; restore the environment immediately.
_original_openrouter_key = os.environ.get("OPENROUTER_API_KEY")
try:
    os.environ.setdefault("OPENROUTER_API_KEY", "test-only-no-provider")
    from backend.api.routes import (
        PartialRequest,
        TurnRequest,
        VoiceCommitTurnRequest,
        _require_turn_id,
        partial_transcript,
        process_turn,
        voice_commit_turn,
    )
finally:
    if _original_openrouter_key is None:
        os.environ.pop("OPENROUTER_API_KEY", None)
from backend.services.orchestrator import (
    Orchestrator,
    _build_question_packet,
    _knowledge_gap_signal,
    _looks_like_explicit_knowledge_gap,
    _question_is_near_duplicate,
    _record_knowledge_gap_floor,
    _select_agenda_decision,
    _select_knowledge_gap_pivot,
    _select_knowledge_gap_recovery,
    _short_answer_rescue_used_for_focus,
)
from backend.state.interview_agenda import initial_interview_agenda


def _area(focus_key: str, label: str) -> dict:
    return {
        "focus_key": focus_key,
        "label": label,
        "track_schema": "v2_ladder",
        "coverage_value": 3.0,
        "sub_focuses": [
            {
                "sub_focus_key": f"{focus_key}_surface",
                "label": f"{label} surface",
                "coverage_value": 3.0,
            }
        ],
        "question_ladder": [
            {
                "posture": "recover",
                "main_question": f"Which small part of {label} can you describe?",
            },
            {
                "posture": "clarify",
                "main_question": f"What decision did your {label} work support?",
            },
            {
                "posture": "explore",
                "main_question": f"How did you validate the {label} result?",
            },
        ],
        "recovery": {
            "honest_gap": f"What narrower part of {label} can you describe?",
        },
    }


def _state() -> dict:
    interview_map = {
        "focus_areas": [
            _area("retention", "retention"),
            _area("experimentation", "experimentation"),
            _area("delivery", "delivery"),
        ]
    }
    state = {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
        "history": [],
        "current_sprint": 1,
    }
    return state


def _append_served_turn(history: list[dict], *, focus_key: str, question: str, route_kind: str) -> None:
    history.append(
        {
            "focus_key": focus_key,
            "question": question,
            "route_kind": route_kind,
        }
    )


def test_explicit_gap_floor_is_narrow_and_short_facts_are_not_gaps() -> None:
    for answer in (
        "I don't know",
        "I do not know how",
        "cannot answer that",
        "Not my area",
        "No experience with it",
        "I haven't worked with that",
        "I'm not familiar with it",
    ):
        assert _looks_like_explicit_knowledge_gap(answer), answer

    for answer in (
        "SQL and weekly retention",
        "I used SQL",
        "three cohorts",
        "I don't know, but I built the dashboard",
    ):
        assert not _looks_like_explicit_knowledge_gap(answer), answer
        assert not _knowledge_gap_signal(answer)[0], answer

    factual_state = _state()
    factual = _record_knowledge_gap_floor(
        factual_state,
        focus_key="retention",
        text="three cohorts",
        turn_id="fact-1",
    )
    assert factual["action"] == "normal"

    assert _knowledge_gap_signal(
        "I don't know",
        reasoning={"adaptability": "admitted_gap", "structure_score": 0},
    )[0]


def test_evidence_bearing_gap_phrases_reset_pressure_and_global_duplicate_is_blocked() -> None:
    evidence_answers = (
        "I don't know the exact latency, roughly 50 milliseconds",
        "Not sure exactly, around 40 percent",
        "I haven't used Kafka; we used Redis Streams instead",
        "I don't know the exact number. It was under 100 milliseconds.",
    )
    for answer in evidence_answers:
        assert not _looks_like_explicit_knowledge_gap(answer), answer
        assert not _knowledge_gap_signal(answer)[0], answer
        assert not _knowledge_gap_signal(
            answer,
            weakness={"type": "deflection", "continue_probing": False},
            reasoning={"adaptability": "admitted_gap", "structure_score": 0},
        )[0], answer
        state = _state()
        state["knowledge_gap_floor"] = {
            "close_requested": True,
            "pending_action": "close",
            "last_signal_id": "prior:1",
            "last_signal_was_gap": True,
        }
        result = _record_knowledge_gap_floor(
            state,
            focus_key="retention",
            text=answer,
            turn_id="evidence",
        )
        assert result["action"] == "normal", answer
        assert not state["knowledge_gap_floor"].get("close_requested"), answer

    history = [{"focus_key": "retention", "surface_key": "retention::cohort", "signal_goal": "retention validation", "question": "How did you define the cohort?"}]
    history.extend({"question": f"visible question {index}"} for index in range(15))
    assert _question_is_near_duplicate("How did you define the cohort?", history, focus_key="experimentation")
    assert _question_is_near_duplicate("How did you define the cohort?", history, focus_key="retention")
    assert not _question_is_near_duplicate(
        {"question": "How did you validate the experiment?", "focus_key": "experimentation", "surface_key": "experimentation::experiment", "signal_goal": "experimentation validation"},
        history,
    )
    assert not _question_is_near_duplicate(
        {"question": "How did you validate experimentation?", "focus_key": "experimentation", "surface_key": "experimentation::experiment", "signal_goal": "experimentation validation"},
        [{"question": "How did you validate retention?", "focus_key": "retention", "surface_key": "retention::cohort", "signal_goal": "retention validation"}],
    )


def test_revision_safe_transition_recall_and_scoped_facts() -> None:
    state = _state()
    for answer, version in (("I don't know", 1), ("No idea", 2)):
        result = _record_knowledge_gap_floor(
            state, focus_key="retention", text=answer, turn_id="revision-turn", answer_version=version, turn_number=1
        )
        assert result["action"] == "recover"
    assert len(state["knowledge_gap_floor"]["semantic_events"]) == 1
    factual = _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="I compared two cohorts and changed the launch sequence.",
        turn_id="revision-turn",
        answer_version=3,
        turn_number=1,
    )
    assert factual["action"] == "normal"
    assert state["knowledge_gap_floor"]["rescue_counts"] == {}

    for phrase in (
        "No idea", "I don't remember", "I can't recall", "I'd have to look that up", "I'm unsure", "Hard to say",
        "I still don't know after 2 attempts",
    ):
        assert _looks_like_explicit_knowledge_gap(phrase), phrase
    scoped_facts = (
        "The team handled Kafka while I reviewed the design.",
        "I don't know the version, but the migration succeeded.",
        "I don't know the product name, but I designed the fallback.",
        "I did not own deployment, but I reviewed releases.",
        "Not sure which version; the migration finished successfully.",
    )
    for phrase in scoped_facts:
        assert not _knowledge_gap_signal(
            phrase,
            weakness={"type": "deflection", "continue_probing": False},
            reasoning={"adaptability": "admitted_gap", "structure_score": 0},
        )[0], phrase
    assert _knowledge_gap_signal(
        "I haven't used Kafka; we used nothing",
        weakness={"type": "deflection", "continue_probing": False},
        reasoning={"adaptability": "admitted_gap", "structure_score": 0},
    )[0]


def test_api_requires_stable_turn_identity() -> None:
    try:
        _require_turn_id("")
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "turn_id" in str(exc.detail)
    else:
        raise AssertionError("blank turn identity must be rejected at the API boundary")
    assert _require_turn_id("  stable-turn-1  ") == "stable-turn-1"


async def _test_api_rejects_blank_turn_identity_before_dispatch() -> None:
    for endpoint, request in (
        (process_turn, TurnRequest(session_id="gap-production", transcript="I don't know", turn_id=" ")),
        (partial_transcript, PartialRequest(session_id="gap-production", transcript="I don't know", turn_id="")),
        (voice_commit_turn, VoiceCommitTurnRequest(session_id="gap-production", transcript="I don't know", turn_id="")),
    ):
        try:
            await endpoint(request)
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "turn_id" in str(exc.detail)
        else:
            raise AssertionError(f"{endpoint.__name__} dispatched without a stable turn identity")


def test_api_rejects_blank_turn_identity_before_dispatch() -> None:
    asyncio.run(_test_api_rejects_blank_turn_identity_before_dispatch())


def test_eleven_gap_trajectory_pivots_and_closes_at_turn_three() -> None:
    state = _state()
    history: list[dict] = []
    focus_key = "retention"
    close_at = None
    served_routes: list[str] = []

    # This is the observed failure shape. The floor must stop consuming the
    # remaining eight answers rather than interrogating the unavailable focus.
    for turn_number in range(1, 12):
        result = _record_knowledge_gap_floor(
            state,
            focus_key=focus_key,
            text="I don't know",
            turn_id=f"gap-{turn_number}",
        )
        decision = _select_agenda_decision(
            state,
            history=history,
            current_focus_key=focus_key,
            current_focus_label=focus_key,
            answered_route_kind="",
            weakness=None,
            discrepancy_conflict=False,
            honest_admission=False,
            force_focus_rotation=False,
        )
        if result["action"] == "recover":
            assert decision["route"] == "knowledge_gap_recovery"
            recovery = _select_knowledge_gap_recovery(
                state,
                history,
                sprint=1,
                focus_key=focus_key,
                answer="I don't know",
                entities=[],
            )
            assert recovery is not None
            served_routes.append(recovery["route_kind"])
            _append_served_turn(
                history,
                focus_key=focus_key,
                question=recovery["question"],
                route_kind=recovery["route_kind"],
            )
        elif result["action"] == "rotate":
            assert decision["route"] == "knowledge_gap_pivot"
            pivot = _select_knowledge_gap_pivot(
                state,
                history,
                sprint=1,
                current_focus_key=focus_key,
                answer="I don't know",
                entities=[],
            )
            assert pivot is not None
            assert pivot["focus_key"] != focus_key
            assert pivot["question"] not in {turn["question"] for turn in history}
            focus_key = pivot["focus_key"]
            served_routes.append("knowledge_gap_pivot")
            _append_served_turn(
                history,
                focus_key=focus_key,
                question=pivot["question"],
                route_kind="knowledge_gap_pivot",
            )
        else:
            assert result["action"] == "close"
            assert decision["route"] == "graceful_exit"
            close_at = turn_number
            break

    assert close_at == 3, state["knowledge_gap_floor"]
    assert served_routes[0] == "trajectory_map_short_answer_rescue"
    assert served_routes[1] == "knowledge_gap_pivot"
    decision = _select_agenda_decision(
        state,
        history=history,
        current_focus_key=focus_key,
        current_focus_label=focus_key,
        answered_route_kind="",
        weakness=None,
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "graceful_exit"
    assert decision["phase"] == "synthesis_close"


def test_substantive_recovery_resets_pressure_but_does_not_reuse_rescue() -> None:
    state = _state()
    first = _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="I don't know",
        turn_id="gap-1",
    )
    assert first["action"] == "recover"

    recovered = _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="I compared weekly retention across two cohorts and changed launch sequencing.",
        turn_id="fact-1",
    )
    assert recovered["action"] == "normal"
    assert state["knowledge_gap_floor"]["consecutive_gap_turns"] == 0
    assert state["knowledge_gap_floor"]["active_gap_focus_keys"] == []

    next_gap = _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="Not my area",
        turn_id="gap-2",
    )
    assert next_gap["action"] == "rotate"
    assert _short_answer_rescue_used_for_focus(state, "retention", [])


def test_repeated_rescue_is_blocked_and_focus_is_marked_exhausted() -> None:
    state = _state()
    history: list[dict] = []
    first = _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="No experience with it",
        turn_id="gap-1",
    )
    assert first["action"] == "recover"
    first_recovery = _select_knowledge_gap_recovery(
        state,
        history,
        sprint=1,
        focus_key="retention",
        answer="No experience with it",
        entities=[],
    )
    assert first_recovery is not None
    _append_served_turn(
        history,
        focus_key="retention",
        question=first_recovery["question"],
        route_kind=first_recovery["route_kind"],
    )

    second = _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="cannot answer that",
        turn_id="gap-2",
    )
    assert second["action"] == "rotate"
    assert "retention" in state["knowledge_gap_floor"]["blocked_focus_keys"]
    assert "retention" in state["interview_agenda"]["exhausted_focus_keys"]


def test_close_floor_marks_report_eligibility_and_minimum_viable_evidence() -> None:
    state = _state()
    state.update(
        {
            "question_count": 3,
            "evidence_question_count": 3,
            "current_sprint": 1,
            "sprint_question_count": 3,
            "application_question_served": True,
            "coverage_map": {
                "dimensions": [
                    {"id": "decision", "coverage_state": "voluntary", "weight": 1.0}
                ]
            },
            "history": [
                {"focus_key": "retention", "route_kind": "trajectory_map_surface"},
                {"focus_key": "experimentation", "route_kind": "trajectory_map_surface"},
            ],
        }
    )
    _record_knowledge_gap_floor(
        state,
        focus_key="retention",
        text="I don't know",
        turn_id="gap-1",
    )
    _record_knowledge_gap_floor(
        state,
        focus_key="experimentation",
        text="I don't know",
        turn_id="gap-2",
    )

    assert Orchestrator.__new__(Orchestrator)._is_complete(state)
    assert state["interview_agenda"]["phase"] == "complete"
    assert state["interview_agenda"]["close_reason"].startswith("knowledge_gap_floor_")
    assert state["interview_agenda"]["completion_eligible"] is True
    assert state["assessment_coverage"]["minimum_viable_completion"] is True


class _MemorySessionStore:
    def __init__(self, state: dict):
        self.state = copy.deepcopy(state)
        self.save_count = 0

    async def get_state(self, session_id: str) -> dict:
        return copy.deepcopy(self.state)

    async def save_state(self, session_id: str, state: dict) -> None:
        self.state = copy.deepcopy(state)
        self.save_count += 1


class _InterleavingSessionStore(_MemorySessionStore):
    def __init__(self, state: dict):
        super().__init__(state)
        self.ready = asyncio.Event()
        self.release = asyncio.Event()
        self._task_gets: dict[str, int] = {}

    async def get_state(self, session_id: str) -> dict:
        task = asyncio.current_task()
        name = task.get_name() if task else ""
        self._task_gets[name] = self._task_gets.get(name, 0) + 1
        if name == "bg-turn-1" and self._task_gets[name] == 2:
            self.ready.set()
            await self.release.wait()
        return await super().get_state(session_id)


class _FollowupProbe:
    def __init__(self) -> None:
        self.adapt_calls = 0

    async def adapt_followup(self, **kwargs):
        self.adapt_calls += 1
        return "PACKET FOLLOW-UP MUST NOT PREEMPT THE GAP FLOOR"

    async def generate_graceful_close(self, *args, **kwargs):
        return "Thanks, that gives me enough signal for now. We'll wrap here."

    async def generate_confession_pivot(self, **kwargs):
        return "Which materially different part of the work can you describe?"

    async def generate_discrepancy_challenge(self, **kwargs):
        return "Can you reconcile those two details?"

    async def generate_clarification(self, **kwargs):
        return "What is one concrete example?"

    async def generate(self, **kwargs):
        return "What tradeoff did you make?"

    async def generate_sprint_question(self, **kwargs):
        return "What decision did you make?", []

    async def generate_coverage_surface(self, **kwargs):
        return "Which coverage dimension did you address?"

    async def generate_coverage_depth_probe(self, **kwargs):
        return "What mechanism supported that result?"


class _WeaknessProbe:
    llm = SimpleNamespace(deterministic_replay=False)

    async def detect(self, *args, **kwargs):
        return {
            "type": "deflection",
            "severity": "low",
            "continue_probing": False,
            "probe_direction": "clarification",
            "weakness": "The candidate set a knowledge boundary.",
            "inferred_focus_key": "retention",
        }


class _DiscrepancyProbe:
    async def check(self, *args, **kwargs):
        return {"conflict_level": "none", "description": ""}


class _ReasoningProbe:
    async def evaluate(self, *args, **kwargs):
        return {"adaptability": "admitted_gap", "structure_score": 0}


class _ConceptProbe:
    async def extract(self, *args, **kwargs):
        return []


class _PolicyProbe:
    def check(self, *args, **kwargs):
        return {"policy_status": "ok", "warnings": [], "primary_warning_codes": [], "metrics": {}}


async def _noop_trace(session_id: str, event: str, **fields) -> None:
    return None


async def _noop_background(**kwargs) -> None:
    return None


async def _noop_finalization(session_id: str) -> None:
    return None


def _production_state(
    *,
    floor: dict | None = None,
    history: list[dict] | None = None,
    question_count: int = 1,
    current_turn_number: int = 1,
    latest_turn_versions: dict | None = None,
    application_served: bool = True,
) -> dict:
    state = _state()
    last_question = "Which retention detail did you own?"
    packet = _build_question_packet(
        question_text=last_question,
        sprint=1,
        route_kind="trajectory_map_surface",
        parsed_resume={},
        resume="",
        followups=["PACKET FOLLOW-UP"],
        source_turn_number=question_count,
        focus_key_override="retention",
        focus_label_override="retention",
    )
    state.update(
        {
            "session_id": "gap-production",
            "current_sprint": 1,
            "current_persona": "curious_lead",
            "sprint_name": "Project Defense",
            "question_count": question_count,
            "evidence_question_count": question_count,
            "sprint_question_count": 0,
            "interview_start_time": time.time() - 5,
            "interview_started": True,
            "interview_complete": False,
            "finalization_status": "idle",
            "finalization_error": "",
            "report_ready": False,
            "resume": "",
            "parsed_resume": {},
            "github_links": [],
            "target_role": "",
            "years_experience": "",
            "prior_assessment_context": {},
            "prior_assessment_prompt": "",
            "skills": [],
            "scores": {},
            "weaknesses": [],
            "failure_surface": {},
            "final_evaluation": None,
            "last_question": last_question,
            "active_question_packet": packet,
            "current_question_followups": ["PACKET FOLLOW-UP"],
            "current_question_followup_asked": False,
            "current_answer_turn_id": "prior-turn",
            "current_answer_question": "",
            "current_answer_turn_number": current_turn_number,
            "current_answer_version": 1,
            "latest_turn_versions": latest_turn_versions or {"prior-turn": 1},
            "candidate_state": {},
            "candidate_model": {"project_map": {}, "established_facts": [], "probed_weaknesses": []},
            "application_question_served": application_served,
            "application_transfer_arc": {"main_transfer_served": application_served},
            "coverage_map": (
                {"dimensions": [{"id": "decision", "coverage_state": "voluntary", "weight": 1.0}]}
                if application_served
                else None
            ),
            "prepped_turn_queue": [],
            "speculative_cache": {},
            "history": copy.deepcopy(history or []),
            "knowledge_gap_floor": copy.deepcopy(floor or {}),
        }
    )
    return state


def _production_orchestrator(store: _MemorySessionStore, *, background_stub: bool = True):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.session_manager = store
    orchestrator.followup_agent = _FollowupProbe()
    orchestrator.weakness_agent = _WeaknessProbe()
    orchestrator.discrepancy_agent = _DiscrepancyProbe()
    orchestrator.reasoning_agent = _ReasoningProbe()
    orchestrator.concept_agent = _ConceptProbe()
    orchestrator.policy_checker_agent = _PolicyProbe()
    orchestrator._partial_entities = {}
    orchestrator._partial_snapshot_meta = {}
    orchestrator._pipeline_inflight = set()
    orchestrator._turn_pipeline_running = {}
    orchestrator._per_answer_scores = {}
    orchestrator._speculative_locks = {}
    orchestrator._finalization_inflight = set()
    orchestrator._hydration_inflight = set()
    orchestrator.tts_service = None
    orchestrator._trace = _noop_trace
    orchestrator._score_answer_async = lambda *args, **kwargs: asyncio.sleep(0)
    if background_stub:
        orchestrator._run_background_pipeline = _noop_background
        orchestrator.start_finalization_background = _noop_finalization
    return orchestrator


async def _test_production_fast_route_precedence() -> None:
    close_floor = {
        "semantic_events": {
            "turn:prior-1": {"turn_id": "prior-1", "version": 1, "turn_number": 1, "sequence": 1, "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"]},
            "turn:prior-2": {"turn_id": "prior-2", "version": 1, "turn_number": 2, "sequence": 2, "focus_key": "experimentation", "is_gap": True, "sources": ["explicit_text"]},
        },
    }
    close_state = _production_state(
        floor=close_floor,
        history=[
            {"focus_key": "retention", "focus_label": "retention", "question": "old retention", "route_kind": "trajectory_map_surface"},
            {"focus_key": "experimentation", "focus_label": "experimentation", "question": "old experiment", "route_kind": "trajectory_map_surface"},
        ],
    )
    close_store = _MemorySessionStore(close_state)
    close_orchestrator = _production_orchestrator(close_store)
    close_result = await close_orchestrator.handle_transcript(
        "gap-production", "I don't know", entities=[], turn_id="close-turn"
    )
    assert close_result["complete"] is True
    assert close_result["route_kind"] == "complete"
    assert close_orchestrator.followup_agent.adapt_calls == 0
    assert close_store.state["active_question_packet"]["route_kind"] == "graceful_exit"

    rotate_floor = {
        "semantic_events": {
            "turn:prior-1": {"turn_id": "prior-1", "version": 1, "turn_number": 1, "sequence": 1, "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"]},
        },
    }
    rotate_state = _production_state(floor=rotate_floor, history=[])
    experimentation = rotate_state["interview_trajectory_map"]["focus_areas"][1]
    experimentation["question_ladder"] = [
        {"posture": "frame", "main_question": "Which experiment result changed your launch decision?"},
    ]
    rotate_store = _MemorySessionStore(rotate_state)
    rotate_orchestrator = _production_orchestrator(rotate_store)
    rotate_result = await rotate_orchestrator.handle_transcript(
        "gap-production", "I don't know", entities=[], turn_id="rotate-turn"
    )
    assert rotate_result["complete"] is False
    assert rotate_result["route_kind"] != "bank_followup_fast"
    assert "experiment result" in rotate_result["response"]
    assert rotate_orchestrator.followup_agent.adapt_calls == 0


async def _test_production_sticky_close_reset() -> None:
    state = _production_state(
        current_turn_number=3,
        floor={
            "semantic_events": {
                "turn:prior-1": {"turn_id": "prior-1", "version": 1, "turn_number": 1, "sequence": 1, "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"]},
                "turn:prior-2": {"turn_id": "prior-2", "version": 1, "turn_number": 2, "sequence": 2, "focus_key": "experimentation", "is_gap": True, "sources": ["explicit_text"]},
            },
        }
    )
    store = _MemorySessionStore(state)
    orchestrator = _production_orchestrator(store)
    result = await orchestrator.handle_transcript(
        "gap-production",
        "I compared weekly retention across two cohorts and changed launch sequencing.",
        entities=[],
        turn_id="recovery-turn",
    )
    assert result["complete"] is False
    assert store.state["knowledge_gap_floor"].get("close_requested") is not True
    assert store.state["knowledge_gap_floor"]["pending_action"] == "normal"


async def _test_production_historical_revision_is_rejected_without_mutation() -> None:
    history = [
        {
            "turn_id": "turn-1",
            "question": "Which retention detail did you own?",
            "answer": "I don't know",
            "focus_key": "retention",
            "route_kind": "trajectory_map_surface",
        },
        {
            "turn_id": "turn-2",
            "question": "Which experiment result did you own?",
            "answer": "I don't know",
            "focus_key": "experimentation",
            "route_kind": "trajectory_map_surface",
        },
        {
            "turn_id": "turn-3",
            "question": "Which delivery detail did you own?",
            "answer": "I don't know",
            "focus_key": "delivery",
            "route_kind": "trajectory_map_surface",
        },
    ]
    floor = {
        "pending_action": "close",
        "close_requested": True,
        "last_signal_id": "turn-3:1",
        "last_signal_was_gap": True,
        "semantic_events": {
            "turn:turn-1": {
                "turn_id": "turn-1", "version": 1, "turn_number": 1, "sequence": 1,
                "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"],
            },
            "turn:turn-2": {
                "turn_id": "turn-2", "version": 1, "turn_number": 2, "sequence": 2,
                "focus_key": "experimentation", "is_gap": True, "sources": ["explicit_text"],
            },
            "turn:turn-3": {
                "turn_id": "turn-3", "version": 1, "turn_number": 3, "sequence": 3,
                "focus_key": "delivery", "is_gap": True, "sources": ["explicit_text"],
            },
        },
    }
    state = _production_state(
        floor=floor,
        history=history,
        question_count=3,
        current_turn_number=3,
        latest_turn_versions={"turn-1": 1, "turn-2": 1, "turn-3": 1},
    )
    state["current_answer_turn_id"] = "turn-3"
    state["current_answer_turn_number"] = 3
    state["current_answer_version"] = 1
    state["current_answer_question"] = "Which delivery detail did you own?"
    state["current_answer_response"] = "What delivery tradeoff did you make?"
    state["last_question"] = "What delivery tradeoff did you make?"
    state["active_question_packet"] = _build_question_packet(
        question_text="What delivery tradeoff did you make?",
        sprint=1,
        route_kind="trajectory_map_surface",
        parsed_resume={},
        resume="",
        followups=["PACKET FOLLOW-UP"],
        source_turn_number=3,
        focus_key_override="delivery",
        focus_label_override="delivery",
    )
    store = _MemorySessionStore(state)
    orchestrator = _production_orchestrator(store)
    history_before = copy.deepcopy(store.state["history"])
    floor_before = copy.deepcopy(store.state["knowledge_gap_floor"])
    queue_before = copy.deepcopy(store.state.get("prepped_turn_queue", []))

    result = await orchestrator.handle_transcript(
        "gap-production",
        "I compared retention across two cohorts.",
        entities=[],
        turn_id="turn-1",
    )

    assert result["route_kind"] == "revision_rejected_historical"
    assert result["response"] == "What delivery tradeoff did you make?"
    assert result["question_count"] == 3
    assert store.state["history"] == history_before
    assert store.state["knowledge_gap_floor"] == floor_before
    assert store.state.get("prepped_turn_queue", []) == queue_before
    assert store.state["current_answer_turn_id"] == "turn-3"
    assert store.state["last_question"] == "What delivery tradeoff did you make?"


async def _test_production_revision_empty_id_and_semantic_upgrade() -> None:
    state = _production_state()
    store = _MemorySessionStore(state)
    orchestrator = _production_orchestrator(store)
    first = await orchestrator.handle_transcript("gap-production", "I don't know", entities=[], turn_id="revision-turn")
    second = await orchestrator.handle_transcript("gap-production", "No idea", entities=[], turn_id="revision-turn")
    third = await orchestrator.handle_transcript(
        "gap-production",
        "I compared two cohorts and changed the launch sequence.",
        entities=[],
        turn_id="revision-turn",
    )
    assert first["complete"] is False and second["complete"] is False and third["complete"] is False
    assert store.state["knowledge_gap_floor"]["pending_action"] == "normal"
    assert len(store.state["knowledge_gap_floor"]["semantic_events"]) == 1
    assert store.state["knowledge_gap_floor"]["semantic_events"]["turn:revision-turn"]["version"] == 3

    empty_store = _MemorySessionStore(_production_state())
    empty_orchestrator = _production_orchestrator(empty_store, background_stub=False)
    await empty_orchestrator.handle_transcript("gap-production", "I don't know", entities=[], turn_id="")
    for _ in range(8):
        await asyncio.sleep(0)
    empty_floor = empty_store.state.get("knowledge_gap_floor") or {}
    assert not empty_floor.get("semantic_events"), empty_floor
    assert empty_floor.get("pending_action", "normal") not in {"recover", "rotate", "close"}

    upgrade_state = _production_state(
        floor={
            "semantic_events": {
                "turn:turn-1": {
                    "turn_id": "turn-1", "version": 1, "turn_number": 1, "sequence": 1,
                    "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"], "source": "fast",
                }
            }
        },
        current_turn_number=2,
        latest_turn_versions={"turn-1": 1},
    )
    upgrade_state["current_answer_turn_id"] = "turn-1"
    upgrade_state["active_question_packet"]["focus_key"] = "experimentation"
    upgrade_state["active_question_packet"]["focus_label"] = "experimentation"
    upgrade_state["current_answer_question"] = "Which experimentation result did you own?"
    upgrade_state["last_question"] = "Which experimentation result did you own?"
    upgrade_store = _MemorySessionStore(upgrade_state)
    upgrade_orchestrator = _production_orchestrator(upgrade_store)
    fast = await upgrade_orchestrator.handle_transcript(
        "gap-production", "I didn't write that", entities=[], turn_id="turn-2"
    )
    assert fast["complete"] is False
    assert upgrade_store.state["knowledge_gap_floor"]["pending_action"] == "normal"
    real_background = Orchestrator._run_background_pipeline.__get__(upgrade_orchestrator)
    await real_background(
        "gap-production", "I didn't write that", [], "Which experimentation result did you own?", "turn-2", 2, 1
    )
    upgrade_floor = upgrade_store.state["knowledge_gap_floor"]
    assert upgrade_floor["close_requested"] is True
    assert len(upgrade_floor["semantic_events"]) == 2
    assert upgrade_floor["semantic_events"]["turn:turn-1"]["is_gap"] is True
    assert upgrade_floor["semantic_events"]["turn:turn-2"]["is_gap"] is True


async def _test_production_true_cross_turn_interleaving() -> None:
    state = _production_state(
        floor={
            "semantic_events": {
                "turn:turn-1": {
                    "turn_id": "turn-1", "version": 1, "turn_number": 1, "sequence": 1,
                    "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"], "source": "fast",
                }
            }
        },
        current_turn_number=1,
        latest_turn_versions={"turn-1": 1},
    )
    state["current_answer_turn_id"] = "turn-1"
    state["history"] = [{"turn_id": "turn-1", "question": "Which retention detail did you own?", "answer": "I don't know", "focus_key": "retention", "route_kind": "trajectory_map_surface", "analysis_status": "pending"}]
    store = _InterleavingSessionStore(state)
    orchestrator = _production_orchestrator(store)
    real_background = Orchestrator._run_background_pipeline.__get__(orchestrator)
    old_task = asyncio.create_task(
        real_background(
            "gap-production", "I don't know", [], "Which retention detail did you own?", "turn-1", 1, 1
        ),
        name="bg-turn-1",
    )
    await store.ready.wait()
    store.state["active_question_packet"]["focus_key"] = "experimentation"
    store.state["active_question_packet"]["focus_label"] = "experimentation"
    store.state["current_answer_question"] = "Which experimentation result did you own?"
    store.state["last_question"] = "Which experimentation result did you own?"
    newer = await orchestrator.handle_transcript("gap-production", "I don't know", entities=[], turn_id="turn-2")
    store.state["coverage_map"] = {"marker": "turn-2"}
    store.state["application_transfer_arc"] = {"marker": "turn-2"}
    store.state["prepped_next_question"] = "TURN-2-SENTINEL"
    floor_after_turn_2 = copy.deepcopy(store.state["knowledge_gap_floor"])
    store.release.set()
    await old_task
    assert newer["complete"] is True
    assert store.state["coverage_map"] == {"marker": "turn-2"}
    assert store.state["application_transfer_arc"] == {"marker": "turn-2"}
    assert store.state["prepped_next_question"] == "TURN-2-SENTINEL"
    assert store.state["knowledge_gap_floor"] == floor_after_turn_2
    floor = store.state["knowledge_gap_floor"]
    assert floor["close_requested"] is True
    assert set(floor["semantic_events"]) == {"turn:turn-1", "turn:turn-2"}
    assert not any(item.get("turn_id") == "turn-1" for item in store.state.get("prepped_turn_queue", []))


def _background_state(*, stale: bool = False) -> dict:
    state = _production_state(
        history=[
            {
                "turn_id": "turn-1",
                "question": "Which retention detail did you own?",
                "answer": "I don't know",
                "focus_key": "retention",
                "focus_label": "retention",
                "route_kind": "trajectory_map_surface",
                "analysis_status": "pending",
            }
        ],
        question_count=1,
        current_turn_number=2 if stale else 1,
        latest_turn_versions={"turn-1": 2 if stale else 1},
    )
    state["current_answer_turn_id"] = "turn-1"
    state["current_answer_turn_number"] = 2 if stale else 1
    if stale:
        state["knowledge_gap_floor"] = {
            "close_requested": True,
            "pending_action": "close",
            "last_signal_id": "turn-2:1",
            "semantic_events": {
                "turn:prior-0": {"turn_id": "prior-0", "version": 1, "turn_number": 0, "sequence": 1, "focus_key": "experimentation", "is_gap": True, "sources": ["explicit_text"]},
                "turn:turn-2": {"turn_id": "turn-2", "version": 1, "turn_number": 2, "sequence": 2, "focus_key": "retention", "is_gap": True, "sources": ["explicit_text"]},
            },
        }
    return state


async def _test_production_background_floor_persistence() -> None:
    store = _MemorySessionStore(_background_state())
    orchestrator = _production_orchestrator(store, background_stub=False)
    await orchestrator._run_background_pipeline(
        "gap-production",
        "I don't know",
        [],
        "Which retention detail did you own?",
        "turn-1",
        1,
        1,
    )
    await asyncio.sleep(0)
    floor = store.state["knowledge_gap_floor"]
    assert floor["last_signal_id"] == "turn-1:1"
    assert floor["pending_action"] == "recover"
    assert store.save_count > 0

    stale_store = _MemorySessionStore(_background_state(stale=True))
    stale_orchestrator = _production_orchestrator(stale_store, background_stub=False)
    await stale_orchestrator._run_background_pipeline(
        "gap-production",
        "I don't know",
        [],
        "Which retention detail did you own?",
        "turn-1",
        1,
        1,
    )
    assert stale_store.state["knowledge_gap_floor"]["last_signal_id"] == "turn-2:1"
    assert stale_store.state["knowledge_gap_floor"]["pending_action"] == "close"


async def _test_production_graceful_low_evidence_report() -> None:
    state = _production_state(
        floor={
            "close_requested": True,
            "pending_action": "close",
            "last_signal_id": "gap-2:1",
            "last_signal_was_gap": True,
            "last_reason": "knowledge_gap_floor_close_consecutive_pressure",
        },
        history=[
            {"turn_id": "gap-1", "question": "q1", "answer": "I don't know", "focus_key": "retention", "route_kind": "trajectory_map_surface"},
            {"turn_id": "gap-2", "question": "q2", "answer": "Not my area", "focus_key": "retention", "route_kind": "trajectory_map_short_answer_rescue"},
        ],
        question_count=2,
        current_turn_number=2,
        application_served=False,
    )
    state["interview_agenda"]["completion_eligible"] = False
    store = _MemorySessionStore(state)
    orchestrator = _production_orchestrator(store)

    async def score_full_interview(**kwargs):
        return {
            "schema_version": "final_report_v2",
            "overall_score": 8.0,
            "hire_recommendation": "MAYBE",
            "confidence_score": 0.9,
            "summary": "Positive assessment.",
            "risk_flags": [],
            "strengths": [],
            "breakdown": {"reasoning": "strong"},
        }

    orchestrator.evaluation_agent = SimpleNamespace(score_full_interview=score_full_interview)
    captured_reports = []

    async def capture_persist_session(**kwargs):
        captured_reports.append(kwargs["full_report"])

    with patch("backend.services.orchestrator.persist_session", new=capture_persist_session):
        result = await orchestrator.end_session("gap-production")
        await asyncio.sleep(0)

    evaluation = result["final_evaluation"]
    assert result["finalization_status"] == "complete"
    assert result["report_ready"] is True
    assert evaluation["hire_recommendation"] == "INSUFFICIENT_DATA"
    assert evaluation["completion_contract"] == {
        "kind": "graceful_low_evidence",
        "assessment_eligible": False,
        "report_finalization": "complete_with_insufficient_data",
        "reason": "knowledge_gap_floor_close_consecutive_pressure",
    }
    assert evaluation["coverage_gate"]["passed"] is False
    assert "knowledge_gap_floor_closed_low_evidence" in evaluation["coverage_gate"]["reasons"]
    assert captured_reports[0]["completion_contract"]["assessment_eligible"] is False
    assert evaluation["overall_score"] is None
    assert evaluation["confidence_score"] is None
    assert evaluation["breakdown"] == {}
    assert evaluation["strengths"] == []
    assert evaluation["resume_claim_calibration"]["claims_substantiated"] == []
    assert evaluation["ability_profile"]["target_role_fit"] == "insufficient_data"
    assert evaluation["role_fit_profile"]["target_role_fit"] == "insufficient_data"
    assert evaluation["failure_surface"] == {}
    assert store.state["scores"] == {}
    assert store.state["failure_surface"] == {}


def test_production_path_regressions() -> None:
    asyncio.run(_test_production_fast_route_precedence())
    asyncio.run(_test_production_sticky_close_reset())
    asyncio.run(_test_production_background_floor_persistence())
    asyncio.run(_test_production_graceful_low_evidence_report())


def test_production_historical_revision_is_rejected_without_mutation() -> None:
    asyncio.run(_test_production_historical_revision_is_rejected_without_mutation())


def test_production_revision_empty_id_and_semantic_upgrade() -> None:
    asyncio.run(_test_production_revision_empty_id_and_semantic_upgrade())


def test_production_true_cross_turn_interleaving() -> None:
    asyncio.run(_test_production_true_cross_turn_interleaving())


def main() -> None:
    test_explicit_gap_floor_is_narrow_and_short_facts_are_not_gaps()
    test_evidence_bearing_gap_phrases_reset_pressure_and_global_duplicate_is_blocked()
    test_revision_safe_transition_recall_and_scoped_facts()
    test_eleven_gap_trajectory_pivots_and_closes_at_turn_three()
    test_substantive_recovery_resets_pressure_but_does_not_reuse_rescue()
    test_repeated_rescue_is_blocked_and_focus_is_marked_exhausted()
    test_close_floor_marks_report_eligibility_and_minimum_viable_evidence()
    test_api_requires_stable_turn_identity()
    test_production_path_regressions()
    test_production_historical_revision_is_rejected_without_mutation()
    test_production_revision_empty_id_and_semantic_upgrade()
    test_production_true_cross_turn_interleaving()
    print("knowledge gap floor contract tests passed")


if __name__ == "__main__":
    main()
