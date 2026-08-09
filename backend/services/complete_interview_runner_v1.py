"""Bounded, deterministic shadow runner for the live interview controller.

This module is intentionally not a route, UI, audio, or replay implementation.
It drives :class:`backend.services.orchestrator.Orchestrator` directly and
records the candidate-visible boundary in the already accepted
``InterviewTraceV1`` ledger.

The runner has four deliberately narrow test seams:

* an in-memory session store, so Redis is never contacted;
* in-memory telemetry/report sinks, so runtime files/Postgres/handoff systems
  are never contacted;
* a browser-playback adapter, which is the only authority allowed to advance
  delivery to spoken truth; and
* a deterministic CandidateActorV1 actual-grant generator, which is the only
  source of candidate answers in the control run.

The local control LLM below is a provider-boundary substitute, not an agenda,
route, map, or report authority.  It exists solely because this checkpoint
must not call a paid provider.  All map normalization, orchestration, agent
dispatch, route selection, application-transfer handling, and finalization
remain the production implementations.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from backend.services.candidate_actor_v1 import BehaviorStateV1, CandidateActorV1
from backend.services.interview_trace_v1 import (
    InterviewTraceV1,
    PlaybackAckStatus,
    TraceEventType,
    TraceInvariantError,
    TraceReferenceError,
    TraceStaleError,
    TraceView,
)
from backend.services.orchestrator import Orchestrator


try:  # The canonical module lives under services; keep a clear import error.
    from backend.services.candidate_actor_v1 import load_actor_turn_projection
except ImportError as exc:  # pragma: no cover - import-time diagnostic only
    raise RuntimeError("CandidateActorV1 is required by CompleteInterviewRunnerV1") from exc


RUNNER_SCHEMA_VERSION = "complete_interview_runner_v1"
CONTROL_PROVIDER_ID = "local.deterministic_control_provider"
CONTROL_PROVIDER_MODEL = "complete-interview-runner-v1-control"
DEFAULT_WORLD_ID = "world_01_product_analyst"
DEFAULT_ROLE = "Product Analyst"
DEFAULT_YEARS = "4-5"
DEFAULT_MAX_TURNS = 15
CANONICAL_TRACE_FILE = "complete_interview_runner_v1_canonical_trace.json"
REDACTED_ARTIFACT_FILE = "complete_interview_runner_v1_shadow_artifact.json"
RUN_MANIFEST_FILE = "complete_interview_runner_v1_shadow_manifest.json"


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _write_owner_only_text(path: Path, text: str) -> None:
    """Write a durable synthetic artifact with explicit owner-only mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.chmod(path, 0o600)


class IsolatedSessionStore:
    """Async Redis-shaped state adapter backed by a private process dictionary."""

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self.saved_session_ids: list[str] = []

    async def save_state(self, session_id: str, state: dict[str, Any]) -> None:
        self._states[str(session_id)] = _clone(state)
        if session_id not in self.saved_session_ids:
            self.saved_session_ids.append(session_id)

    async def get_state(self, session_id: str) -> dict[str, Any]:
        try:
            return _clone(self._states[str(session_id)])
        except KeyError as exc:
            raise KeyError(f"isolated session does not exist: {session_id}") from exc

    async def delete_session(self, session_id: str) -> None:
        self._states.pop(str(session_id), None)

    async def exists(self, session_id: str) -> bool:
        return str(session_id) in self._states

    @property
    def session_ids(self) -> tuple[str, ...]:
        return tuple(self._states)


class IsolatedTelemetrySink:
    """Append-only in-memory replacement for the production telemetry sink."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def log(
        self,
        session_id: str,
        event: str,
        *,
        source: str = "backend",
        level: str = "info",
        **fields: Any,
    ) -> dict[str, Any]:
        record = {
            "session_id": str(session_id),
            "event": str(event),
            "source": str(source),
            "level": str(level),
            **_clone(fields),
        }
        self.events.append(record)
        return _clone(record)


class IsolatedReportSink:
    """Captures persistence/handoff calls without invoking external systems."""

    def __init__(self) -> None:
        self.persist_calls: list[dict[str, Any]] = []
        self.handoff_complete_calls: list[dict[str, Any]] = []
        self.handoff_failed_calls: list[dict[str, Any]] = []

    async def persist_session(self, **kwargs: Any) -> None:
        self.persist_calls.append(_clone(kwargs))

    async def notify_handoff_complete(self, handoff_id: str, session_id: str, report: Any) -> None:
        self.handoff_complete_calls.append({
            "handoff_id": str(handoff_id),
            "session_id": str(session_id),
            "report_hash": sha256_json(report),
        })

    async def notify_handoff_failed(self, handoff_id: str, session_id: str, reason: str) -> None:
        self.handoff_failed_calls.append({
            "handoff_id": str(handoff_id),
            "session_id": str(session_id),
            "reason": str(reason)[:300],
        })


class DeterministicTTSAdapter:
    """Local pre-generation adapter; it never contacts Cartesia/ElevenLabs."""

    provider = "local-control-tts"

    def __init__(self, *, fail_on_calls: Iterable[int] = ()) -> None:
        self.fail_on_calls = {int(item) for item in fail_on_calls}
        self.calls: list[dict[str, Any]] = []

    async def pre_generate(self, session_id: str, text: str) -> str:
        call_number = len(self.calls) + 1
        record = {
            "call_number": call_number,
            "session_id": str(session_id),
            "text_hash": sha256_json(str(text)),
            "provider": self.provider,
        }
        self.calls.append(record)
        if call_number in self.fail_on_calls:
            raise RuntimeError("deterministic_tts_failure")
        return f"local://tts/{sha256_json(text)}"


@dataclass(frozen=True)
class PlaybackDeliveryResult:
    acknowledged: bool
    failure_reason: str = ""
    retryable: bool = True
    ack_status: str = PlaybackAckStatus.COMPLETED.value


class BrowserPlaybackAdapter:
    """Explicit browser playback ACK boundary used by the shadow trace."""

    def __init__(self, *, failure_modes: Mapping[int, str] | None = None) -> None:
        self.failure_modes = {int(k): str(v) for k, v in (failure_modes or {}).items()}
        self.attempts: list[dict[str, Any]] = []

    def mode_for_turn(self, turn_number: int) -> str:
        return self.failure_modes.get(int(turn_number), "ack")

    async def deliver(
        self,
        *,
        trace: InterviewTraceV1,
        turn_id: str,
        answer_version: int,
        prepared_event_id: str,
        runtime_epoch: int,
        turn_number: int,
        attempt_number: int = 1,
        mode: str | None = None,
    ) -> PlaybackDeliveryResult:
        mode = str(mode or self.mode_for_turn(turn_number)).strip().lower()
        attempt_id = f"delivery-{turn_id}-{attempt_number}"
        started = trace.record_question_delivery_started(
            turn_id=turn_id,
            answer_version=answer_version,
            question_prepared_event_id=prepared_event_id,
            delivery_attempt_id=attempt_id,
            runtime_epoch=runtime_epoch,
            provider="local-control-playback",
            producer="runner.browser_playback_adapter",
            idempotency_key=f"delivery-start:{turn_id}:{answer_version}:{attempt_id}",
        )
        result = PlaybackDeliveryResult(acknowledged=False)
        if mode in {"no_ack", "tts_failure", "stale_epoch", "semantic_timeout"}:
            reason = {
                "no_ack": "browser_playback_no_ack",
                "tts_failure": "tts_synthesis_failed",
                "stale_epoch": "stale_runtime_epoch_before_ack",
                "semantic_timeout": "semantic_timeout_before_delivery",
            }[mode]
            if mode == "stale_epoch":
                # The failed attempt is recorded in the current epoch; the stale
                # ACK below is intentionally rejected and cannot become speech.
                failed = trace.record_delivery_failed(
                    turn_id=turn_id,
                    answer_version=answer_version,
                    delivery_attempt_id=attempt_id,
                    delivery_started_event_id=started.event_id,
                    reason=reason,
                    runtime_epoch=runtime_epoch,
                    producer="runner.browser_playback_adapter",
                    idempotency_key=f"delivery-failed:{turn_id}:{answer_version}:{attempt_id}",
                )
                stale = trace.record_playback_acknowledged(
                    turn_id=turn_id,
                    answer_version=answer_version,
                    delivery_attempt_id=attempt_id,
                    delivery_started_event_id=started.event_id,
                    runtime_epoch=runtime_epoch + 1,
                    producer="runner.browser_playback_adapter",
                    idempotency_key=f"playback-ack-stale:{turn_id}:{answer_version}:{attempt_id}",
                )
                result = PlaybackDeliveryResult(
                    acknowledged=False,
                    failure_reason=f"{reason}:{stale.reason or 'rejected'}",
                )
            else:
                trace.record_delivery_failed(
                    turn_id=turn_id,
                    answer_version=answer_version,
                    delivery_attempt_id=attempt_id,
                    delivery_started_event_id=started.event_id,
                    reason=reason,
                    runtime_epoch=runtime_epoch,
                    producer="runner.browser_playback_adapter",
                    idempotency_key=f"delivery-failed:{turn_id}:{answer_version}:{attempt_id}",
                )
                result = PlaybackDeliveryResult(acknowledged=False, failure_reason=reason)
        else:
            ack = trace.record_playback_acknowledged(
                turn_id=turn_id,
                answer_version=answer_version,
                delivery_attempt_id=attempt_id,
                delivery_started_event_id=started.event_id,
                runtime_epoch=runtime_epoch,
                producer="runner.browser_playback_adapter",
                idempotency_key=f"playback-ack:{turn_id}:{answer_version}:{attempt_id}",
                client_ack=PlaybackAckStatus.COMPLETED,
            )
            result = PlaybackDeliveryResult(acknowledged=bool(ack.accepted))
        self.attempts.append({
            "turn_number": turn_number,
            "turn_id": turn_id,
            "attempt_number": attempt_number,
            "attempt_id": attempt_id,
            "mode": mode,
            "started_event_id": started.event_id,
            "acknowledged": result.acknowledged,
            "failure_reason": result.failure_reason,
        })
        return result


class ActualGrantControlGenerator:
    """Provider-free generator that speaks only from the current actor grant."""

    provider = "fixture"
    model = "candidate-actor-actual-grant-control"
    mode = "deterministic"
    deterministic_replay = True

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None) -> Mapping[str, Any]:
        projection = prompt.get("actor_turn_projection") or {}
        context = projection.get("turn_context") or {}
        facts = {
            str(fact.get("fact_id")): fact
            for fact in projection.get("granted_facts", [])
            if isinstance(fact, Mapping) and fact.get("fact_id")
        }
        newly = [str(item) for item in context.get("newly_granted_fact_ids", [])]
        clauses: list[dict[str, Any]] = []
        for fact_id in newly:
            fact = facts.get(fact_id) or {}
            statement = str(fact.get("statement_text") or "").strip()
            if statement:
                clauses.append({"clause": statement, "fact_ids": [fact_id]})
        answer_text = " ".join(item["clause"] for item in clauses) or "I don't know."
        ownership_statuses = {
            str((fact.get("ownership") or {}).get("status") or "")
            for fact in facts.values()
        }
        boundary_action = "ownership_boundary" if ownership_statuses & {
            "partial", "team_owned", "not_owned", "ambiguous"
        } else "none"
        return {
            "answer_text": answer_text,
            "factual_clauses": clauses,
            "disclosed_fact_ids": newly,
            "behavior_mode": "fixture_actual_grant_control",
            "boundary_action": boundary_action,
            "correction": {
                "is_correction": False,
                "superseded_fact_ids": [],
                "active_fact_ids": [],
            },
            "uncertainty": {
                "kind": "unknown" if not clauses else "none",
                "text": "" if clauses else "No current fact was granted for this setup turn.",
            },
        }


class DeterministicActualGrantCandidate:
    """Replaceable CandidateActor boundary for one frozen world control run."""

    FACT_REQUEST_SEQUENCE = (
        "fact_identity_role",
        "fact_team_context",
        "fact_resume_retention",
        "fact_retention_cohort",
    )

    def __init__(self, world_id: str, *, seed: int = 17) -> None:
        if world_id != DEFAULT_WORLD_ID:
            raise ValueError(
                "CompleteInterviewRunnerV1 control checkpoint is intentionally one-world only: "
                f"{DEFAULT_WORLD_ID}"
            )
        self.world_id = world_id
        self.generator = ActualGrantControlGenerator()
        self.actor = CandidateActorV1.from_world(world_id, self.generator, seed=seed)
        self.visible_conversation: list[dict[str, Any]] = []
        self.turn_records: list[dict[str, Any]] = []

    def requested_fact_ids_for_turn(self, turn_number: int) -> tuple[str, ...]:
        index = int(turn_number) - 1
        if 0 <= index < len(self.FACT_REQUEST_SEQUENCE):
            return (self.FACT_REQUEST_SEQUENCE[index],)
        return ()

    async def answer(self, *, turn_number: int, question: str) -> Any:
        from backend.services.candidate_actor_v1 import CandidateVisibleTurnV1

        behavior = BehaviorStateV1(
            fatigue_phase="early" if turn_number <= 5 else ("middle" if turn_number <= 10 else "late"),
            behavior_mode="baseline",
            # CandidateActorV1 owns a zero-based disclosure turn counter;
            # the runner's visible interview turn numbers are one-based.
            turn_number=turn_number - 1,
            speaking_guidance="Give the headline first and expand when asked.",
            response_guidance="Use only the facts available in the current question context.",
            correction_guidance="Correct an earlier statement only when the current fact supports it.",
            contradiction_guidance="State the boundary plainly when the question asks beyond your facts.",
        )
        prompt = self.actor.issue_turn(
            requested_fact_ids=self.requested_fact_ids_for_turn(turn_number),
            current_question=question,
            prior_candidate_visible_conversation=self.visible_conversation,
            behavior_state=behavior,
        )
        response = await self.actor.respond(prompt)
        validation = response.validation if isinstance(response.validation, Mapping) else {}
        if not bool(validation.get("canonical")) or not response.answer_text.strip():
            raise RuntimeError(
                "candidate_actor_control_rejected: "
                + "; ".join(str(item) for item in (validation.get("errors") or [])[:3])
            )
        self.visible_conversation.append(CandidateVisibleTurnV1(
            speaker="interviewer",
            text=question,
            turn_number=turn_number,
        ).to_dict())
        self.visible_conversation.append(CandidateVisibleTurnV1(
            speaker="candidate",
            text=response.answer_text,
            turn_number=turn_number,
        ).to_dict())
        self.turn_records.append({
            "turn_number": turn_number,
            "answer_text": response.answer_text,
            "answer_sha256": sha256_json(response.answer_text),
            "validation": _clone(validation),
            "requested_fact_count": len(self.requested_fact_ids_for_turn(turn_number)),
            "disclosed_fact_count": len(response.disclosed_fact_ids),
            "provider": response.generation_metadata.get("provider"),
            "model": response.generation_metadata.get("model"),
        })
        return response


class DeterministicControlLLMRouter:
    """No-paid-provider control response seam; never an agenda authority."""

    provider = CONTROL_PROVIDER_ID
    deterministic_replay = True

    def __init__(
        self,
        tier: str = "small",
        model_override: str | None = None,
        timeout_override: float | None = None,
        **_: Any,
    ) -> None:
        self.tier = str(tier)
        self.model = model_override or f"{CONTROL_PROVIDER_MODEL}:{self.tier}"
        self.timeout_override = timeout_override
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _focus_from_user(user: str) -> tuple[str, str]:
        lower = user.lower()
        if "retention" in lower or "repeat booking" in lower:
            return "retention_cohort_analysis", "Retention cohort analysis"
        if "campaign" in lower or "segment" in lower or "lifecycle" in lower:
            return "lifecycle_campaign_rules", "Lifecycle campaign rules"
        return "retention_cohort_analysis", "Retention cohort analysis"

    @staticmethod
    def _lite_track(user: str) -> dict[str, Any]:
        focus_key, label = DeterministicControlLLMRouter._focus_from_user(user)
        if focus_key == "retention_cohort_analysis":
            frame = "At Looply, what product decision did your retention cohorts and reporting help the team make?"
            clarify = "How did you define the eligible cohort and the D30 observation window?"
            explore = "How did excluding test accounts or duplicate organizations change the decision?"
            pressure = "What could make the D30 comparison misleading, and how would you check it?"
            recover = "Which retention number or decision did you personally investigate?"
            anchors = [
                ("cohort_definition", "Cohort and denominator", "Built retention cohorts and reporting used by product and growth teams."),
                ("late_data_guardrail", "Late-data guardrail", "Labels late-arriving data before comparing D30 retention."),
            ]
        else:
            frame = "At Looply, what decision did your customer segments and lifecycle campaign rules support?"
            clarify = "How did you decide which customer behavior belonged in a segment?"
            explore = "How did the campaign rule change the action a product or growth partner took?"
            pressure = "What could make a segment look useful while sending the wrong customers a message?"
            recover = "Which segment or campaign decision did you personally shape?"
            anchors = [
                ("segment_definition", "Segment definition", "Defined customer segments and campaign rules for lifecycle messaging."),
                ("decision_use", "Decision use", "Defined customer segments and campaign rules used for lifecycle messaging."),
            ]

        def q(posture: str, text: str, goal: str, space: list[str], gain: str = "high") -> dict[str, Any]:
            return {
                "posture": posture,
                "main_question": text,
                "signal_goal": goal,
                "expected_space": space,
                "information_gain": gain,
                "voice_complexity": "low" if posture in {"frame", "clarify"} else "medium",
            }

        return {
            "frame": q("frame", frame, "Establish the concrete decision and the candidate's analytical contribution.", ["decision", "metric", "personal contribution"]),
            "clarify": q("clarify", clarify, "Test scope and definition before mechanism depth.", ["eligibility", "window", "ownership"]),
            "explore": q("explore", explore, "Test how an analytical choice affected a product decision.", ["trade-off", "comparison", "decision use"]),
            "pressure": q("pressure", pressure, "Test measurement validity and a realistic guardrail.", ["confound", "check", "limitation"]),
            "recover_short_answer": recover,
            "dimensions": [
                {
                    "id": dim_id,
                    "label": dim_label,
                    "resume_anchor": anchor,
                    "question": question,
                    "signal_goal": "Test grounded role-relevant reasoning.",
                    "surface_kind": "depth" if index else "breadth",
                    "signal_weight": 2.8 if index == 0 else 2.2,
                }
                for index, (dim_id, dim_label, anchor) in enumerate(anchors)
                for question in [
                    "What evidence would make that choice useful for a product decision?"
                    if index == 0
                    else "What boundary would make that segment or comparison unsafe to use?"
                ]
            ],
        }

    @staticmethod
    def _full_track(user: str) -> dict[str, Any]:
        lite = DeterministicControlLLMRouter._lite_track(user)
        focus_key, label = DeterministicControlLLMRouter._focus_from_user(user)
        if focus_key == "retention_cohort_analysis":
            anchor = "Built retention cohorts and reporting used by product and growth teams."
            opener = "At Looply, which decision did your retention cohorts and reporting make easier for product or growth?"
            questions = [
                ("frame", opener, "Establish the decision and scope.", ["decision", "metric", "ownership"]),
                ("clarify", "How did you define the eligible signup cohort and observation window?", "Test denominator and scope.", ["eligibility", "window", "exclusions"]),
                ("explore", "How did those cohort choices change the interpretation a product partner received?", "Test decision use.", ["trade-off", "interpretation", "partner use"]),
                ("pressure", "What could make the D30 comparison misleading, and what check would you run?", "Test guardrails.", ["confound", "check", "limitation"]),
                ("synthesize", "What evidence would support a fair conclusion from that retention comparison?", "Test calibrated synthesis.", ["evidence", "limitation", "next check"]),
                ("recover", "Which retention definition or decision would you like to make more concrete?", "Recover a bounded detail.", ["definition", "decision", "artifact"]),
            ]
            dims = [
                {"id": "cohort_definition", "label": "Cohort definition", "resume_anchor": anchor, "surface": "What did the cohort represent?", "mechanism": "How did your eligibility and window choices affect the result?", "boundary": "What late data or duplicate account case could invalidate the comparison?", "signal_weight": 2.8},
                {"id": "decision_use", "label": "Decision use", "resume_anchor": anchor, "surface": "Who used the reporting and for which decision?", "mechanism": "How did you connect the comparison to a product or growth action?", "boundary": "When would you stop a team from acting on the number?", "signal_weight": 2.3},
                {"id": "causal_guardrail", "label": "Causal guardrail", "resume_anchor": "Partnered on an AI engagement launch that improved repeat booking by 11%.", "surface": "What did the 11% figure compare?", "mechanism": "How would you separate a launch effect from other changes?", "boundary": "What evidence would show the lift was not causal?", "signal_weight": 2.5},
            ]
        else:
            anchor = "Defined customer segments and campaign rules for lifecycle messaging."
            opener = "At Looply, what customer decision did your segments and campaign rules help product or growth make?"
            questions = [
                ("frame", opener, "Establish the decision and scope.", ["decision", "segment", "ownership"]),
                ("clarify", "How did you decide which customer behavior belonged in a segment?", "Test definition and boundary.", ["behavior", "eligibility", "scope"]),
                ("explore", "How did a rule change the message or action a partner took?", "Test decision use.", ["rule", "action", "trade-off"]),
                ("pressure", "What could make a segment look useful while sending the wrong customers a message?", "Test guardrails.", ["confound", "misclassification", "check"]),
                ("synthesize", "What evidence would support using that segment for a lifecycle decision?", "Test calibrated synthesis.", ["evidence", "limitation", "next check"]),
                ("recover", "Which segment definition or campaign decision would you like to make concrete?", "Recover a bounded detail.", ["definition", "decision", "artifact"]),
            ]
            dims = [
                {"id": "segment_definition", "label": "Segment definition", "resume_anchor": anchor, "surface": "What behavior defined the segment?", "mechanism": "How did you choose the boundary between segments?", "boundary": "What customer behavior could make that boundary misleading?", "signal_weight": 2.8},
                {"id": "decision_use", "label": "Decision use", "resume_anchor": anchor, "surface": "Who used the segment and for what action?", "mechanism": "How did the rule change the lifecycle action?", "boundary": "When would you stop using that rule?", "signal_weight": 2.3},
                {"id": "measurement_guardrail", "label": "Measurement guardrail", "resume_anchor": anchor, "surface": "What outcome showed the rule was useful?", "mechanism": "How did you compare outcomes fairly?", "boundary": "What would make the outcome look better without improving the product?", "signal_weight": 2.5},
            ]
        ladder = [
            {
                "posture": posture,
                "main_question": text,
                "signal_goal": goal,
                "expected_space": space,
                "follow_up_if_shallow": text,
                "follow_up_if_strong": text,
                "information_gain": "high" if posture != "recover" else "medium",
                "voice_complexity": "low" if posture in {"frame", "clarify"} else "medium",
            }
            for posture, text, goal, space in questions
        ]
        return {
            "opener": opener,
            "dimensions": dims,
            "recovery": {
                "short_answer": questions[-1][1],
                "honest_gap": "What part of that work did you understand well enough to explain?",
                "claim_conflict": "Which part of the resume claim should we narrow or clarify?",
                "metric_risk": questions[3][1],
                "overclaim_risk": questions[2][1],
                "bridge": "Switching to the other role-relevant surface from your background.",
            },
            "candidate_q4_options": [questions[2][1], questions[3][1], questions[4][1]],
            "question_ladder": ladder,
        }

    @staticmethod
    def _focus_plan() -> dict[str, Any]:
        return {
            "focus_areas": [
                {
                    "label": "Retention cohort analysis",
                    "focus_key": "retention_cohort_analysis",
                    "anchor_context": "Built retention cohorts and reporting used by product and growth teams.",
                    "why_priority": "Most role-relevant analytical claim with measurable decision and denominator depth.",
                    "resume_snippets": [
                        "Built retention cohorts and reporting used by product and growth teams.",
                        "Partnered on an AI engagement launch that improved repeat booking by 11%.",
                    ],
                    "sub_focuses": [
                        {
                            "label": "Cohort and denominator definition",
                            "sub_focus_key": "cohort_definition",
                            "surface_kind": "metric_design",
                            "role_relevance_weight": 2.9,
                            "profile_importance_weight": 2.8,
                            "evidence_strength": 2.8,
                            "claim_risk": 2.0,
                            "coverage_value": 2.9,
                            "why_priority": "Tests metric validity directly.",
                            "source_snippets": ["Built retention cohorts and reporting used by product and growth teams."],
                        },
                        {
                            "label": "Decision and causal guardrails",
                            "sub_focus_key": "decision_guardrails",
                            "surface_kind": "dashboard_reporting",
                            "role_relevance_weight": 2.7,
                            "profile_importance_weight": 2.5,
                            "evidence_strength": 2.4,
                            "claim_risk": 2.2,
                            "coverage_value": 2.7,
                            "why_priority": "Tests whether product evidence is used with calibrated claims.",
                            "source_snippets": ["Partnered on an AI engagement launch that improved repeat booking by 11%."],
                        },
                    ],
                },
                {
                    "label": "Lifecycle campaign rules",
                    "focus_key": "lifecycle_campaign_rules",
                    "anchor_context": "Defined customer segments and campaign rules for lifecycle messaging.",
                    "why_priority": "Distinct role-relevant surface for segmentation and stakeholder decisions.",
                    "resume_snippets": [
                        "Defined customer segments and campaign rules for lifecycle messaging.",
                        "Created self-serve dashboards for product managers.",
                    ],
                    "sub_focuses": [
                        {
                            "label": "Segment boundary and taxonomy",
                            "sub_focus_key": "segment_definition",
                            "surface_kind": "taxonomy",
                            "role_relevance_weight": 2.7,
                            "profile_importance_weight": 2.4,
                            "evidence_strength": 2.5,
                            "claim_risk": 2.0,
                            "coverage_value": 2.6,
                            "why_priority": "Tests how behavioral definitions become usable actions.",
                            "source_snippets": ["Defined customer segments and campaign rules for lifecycle messaging."],
                        },
                        {
                            "label": "Partner decision use",
                            "sub_focus_key": "campaign_decision_use",
                            "surface_kind": "dashboard_reporting",
                            "role_relevance_weight": 2.5,
                            "profile_importance_weight": 2.2,
                            "evidence_strength": 2.3,
                            "claim_risk": 1.8,
                            "coverage_value": 2.4,
                            "why_priority": "Tests practical product and growth communication.",
                            "source_snippets": ["Created self-serve dashboards for product managers."],
                        },
                    ],
                },
            ]
        }

    @staticmethod
    def _resume_parse() -> dict[str, Any]:
        return {
            "candidate_name": "Priya Nair",
            "skills": ["SQL", "dbt", "Looker", "experimentation"],
            "tools": ["SQL", "dbt", "Looker"],
            "projects": [
                {
                    "name": "Retention analytics",
                    "description": "Retention cohorts and reporting used by product and growth teams.",
                    "technologies": ["SQL", "dbt", "Looker"],
                    "ownership_level": "primary",
                    "contribution_type": "built",
                }
            ],
            "claims": [
                {"text": "Built retention cohorts and reporting used by product and growth teams.", "project": "Retention analytics", "strength": "strong", "contribution_type": "built"},
                {"text": "Partnered on an AI engagement launch that improved repeat booking by 11%.", "project": "Looply engagement launch", "strength": "moderate", "contribution_type": "partnered"},
                {"text": "Defined customer segments and campaign rules for lifecycle messaging.", "project": "Lifecycle messaging", "strength": "strong", "contribution_type": "built"},
            ],
            "experiences": [
                {"title": "Product Analyst", "company": "Looply", "duration": "2023-present", "contribution_type": "built"},
                {"title": "Analytics Associate", "company": "Looply", "duration": "2021-2023", "contribution_type": "built"},
            ],
            "experience": {"ml": 0, "swe": 0, "data_eng": 4},
            "experience_tier": "senior",
        }

    @staticmethod
    def _application_map() -> dict[str, Any]:
        return {
            "application_question": "Suppose product wants to expand the retention analysis to a new customer segment; how would you define the decision measure and check that the comparison is fair?",
            "adjacent_constraint": "A new customer segment changes the population being compared.",
            "anchor_reference": "the retention cohorts and reporting work described",
            "coverage_confidence": 0.8,
            "grounding_needed": False,
            "grounding_question": "",
            "max_depth_level": 3,
            "depth_allowed_terms": ["cohort", "denominator", "observation window", "comparison"],
            "dimensions": [
                {
                    "id": "decision_measure",
                    "label": "Decision measure",
                    "description": "Define the outcome and denominator for the new segment.",
                    "expected_approaches": ["define an outcome", "state the denominator", "set an observation window"],
                    "surfacing_question": "What outcome and denominator would make the new-segment comparison useful?",
                    "surface_kind": "breadth",
                    "depth_eligible": False,
                    "weight": 2.8,
                },
                {
                    "id": "comparison_fairness",
                    "label": "Comparison fairness",
                    "description": "Check exclusions, timing, and confounds before acting on movement.",
                    "expected_approaches": ["check eligibility", "compare like windows", "identify confounds"],
                    "surfacing_question": "What could make the new segment look better without reflecting a real product change?",
                    "surface_kind": "breadth",
                    "depth_eligible": False,
                    "weight": 2.6,
                },
                {
                    "id": "stakeholder_tradeoff",
                    "label": "Stakeholder trade-off",
                    "description": "Translate evidence limits into a practical product decision.",
                    "expected_approaches": ["state a limitation", "recommend a next check", "explain the decision trade-off"],
                    "surfacing_question": "How would you explain the evidence limit before a product partner acted?",
                    "surface_kind": "depth",
                    "depth_eligible": True,
                    "weight": 2.2,
                },
            ],
        }

    @staticmethod
    def _report() -> dict[str, Any]:
        return {
            "hire_recommendation": "MAYBE",
            "overall_score": 6.0,
            "confidence_score": 0.45,
            "breakdown": {"reasoning": 6, "technical_depth": 6, "communication": 6, "adaptability": 6},
            "failure_surface": {"control_shadow": 0.0},
            "role_fit_profile": {
                "target_role_fit": "inconclusive",
                "best_fit_archetype": "shadow control only",
                "strongest_signal": "not assessed",
                "largest_unresolved_risk": "not assessed",
                "alternate_fit_notes": "This local provider output is not promotion evidence.",
            },
            "ability_profile": {
                "strongest_verified_signal": "not assessed",
                "weakest_verified_signal": "not assessed",
                "alternate_fit_archetypes": [],
                "target_role_fit": "inconclusive",
                "role_fit_explanation": "Shadow-control artifact only; candidate and provider quality are not assessed.",
            },
            "resume_claim_calibration": {
                "claims_tested": [],
                "claims_substantiated": [],
                "claims_partially_substantiated": [],
                "claims_not_substantiated": [],
                "claims_untested": [],
                "impact_on_verdict": "inconclusive",
            },
            "lens_findings": {},
            "tested_strengths": [],
            "tested_risks": [],
            "risk_flags": ["SHADOW_ONLY: no hiring inference"],
            "strengths": [],
            "claim_findings": [],
            "claim_credibility_risk": {"level": "not_tested", "detail": "shadow control"},
            "untested_dimensions": ["all candidate quality dimensions"],
            "recommended_followups": [],
            "candidate_safe_summary": "Shadow-control report only; no candidate-quality conclusion was produced.",
            "recruiter_summary": "Shadow-control report only; no candidate-quality conclusion was produced.",
        }

    async def call(self, system: str, user: str, **kwargs: Any) -> Any:
        system_text = str(system or "")
        user_text = str(user or "")
        low_system = system_text.lower()
        low_user = user_text.lower()
        self.calls.append({
            "tier": self.tier,
            "model": self.model,
            "system_hash": sha256_json(system_text),
            "user_hash": sha256_json(user_text),
            "response_format": _clone(kwargs.get("response_format")),
        })

        if "resume parser" in low_system:
            return self._resume_parse()
        if "interview planning analyst" in low_system:
            plan = self._focus_plan()
            plan.update({"demoted_or_off_role_surfaces": [], "missing_or_risky_checks": [], "planning_notes": "Control-only map input."})
            return plan
        if "senior technical interviewer deciding which resume experiences" in low_system:
            return self._focus_plan()
        if "launch-ready part of an interview map" in low_system:
            return self._lite_track(user_text)
        if "compact launch-readiness critic" in low_system:
            focus_key, label = self._focus_from_user(user_text)
            return {
                "ready": True,
                "overall_score": 8.0,
                "top_two_score": 8.0,
                "opener_quality_score": 8.0,
                "dimension_depth_score": 8.0,
                "strengths": ["distinct role-relevant launch tracks"],
                "issues": [],
                "repair_instructions": [],
                "focus_reviews": [{"focus_key": focus_key, "label": label, "score": 8.0, "opener_issue": "", "issues": []}],
                "typed_issues": [],
                "repair_targets": [],
            }
        if "cheap advisory focus-plan auditor" in low_system:
            return {"advisory_only": True, "ready": True, "warnings": [], "top_two_distinct": True, "off_role_promotion": False, "ranking_concern": False, "suggested_swap": {}}
        if "cheap advisory question-ladder auditor" in low_system:
            return {"advisory_only": True, "ready": True, "warnings": [], "voice_complexity_flags": [], "expected_space_flags": [], "low_information_flags": [], "closed_question_flags": [], "sonnet_escalation_recommended": False}
        if "compact map critic" in low_system or "map critic" in low_system:
            return {"ready": True, "overall_score": 8.0, "top_two_score": 8.0, "opener_quality_score": 8.0, "dimension_depth_score": 8.0, "strengths": [], "issues": [], "repair_instructions": [], "focus_reviews": [], "typed_issues": [], "repair_targets": []}
        if "launchtracklite" in low_system or "full interview map" in low_system or "question_ladder" in low_system and "return only" in low_system:
            return self._full_track(user_text)
        if "application transfer" in low_system or "application-transfer" in low_user:
            return self._application_map()
        if "verify whether this rewritten application-transfer" in low_user or "strict verifier for rewritten interview" in low_system:
            return {"accepted": True, "reason": "control question remains grounded and speakable", "risk_flags": []}
        if "rewrite this application-transfer" in low_user or '"question"' in low_user and "rewrite" in low_user:
            return {"question": "Suppose product wants to expand the retention analysis to a new customer segment; how would you define the measure and check the comparison is fair?"}
        if "coverage" in low_system and "dimensions" in low_user:
            ids = re.findall(r"'id': '([^']+)'|\"id\": \"([^\"]+)\"", user_text)
            flat_ids = [a or b for a, b in ids]
            return {"dimensions": [{"id": item, "coverage": "full", "reason": "control answer classified deterministically"} for item in flat_ids]}
        if "coverage" in low_system and "interview dimension" in low_user:
            match = re.search(r"Interview dimension:\s*([^\n]+)", user_text)
            return {"coverage": "full", "reason": f"control coverage for {match.group(1).strip() if match else 'dimension'}"}
        if "meta-cognition evaluator" in low_system:
            return {"structure_score": 2, "clarification_behavior": "mixed", "adaptability": "flexible", "confidence_calibration": "calibrated", "notes": "control-only behavioral shape"}
        if "compare:" in low_system or "detect inconsistencies" in low_system:
            return {"conflict_level": "none", "description": "control provider did not assert a discrepancy", "severity": "low"}
        if "concept extraction" in low_system:
            return {"concepts": ["metric", "cohort", "decision"]}
        if "evaluate this single interview answer" in low_system:
            return {"score": 6.0, "breakdown": {"problem_framing": 1, "logical_reasoning": 2, "measurement_validity": 2, "business_impact_awareness": 1}, "confidence": 0.45}
        if "writing antigravity's final interview report" in low_system:
            return self._report()
        if "independent report fairness reviewer" in low_system:
            return {"concerns": [], "score_alignment": "aligned", "tone_alignment": "fair", "missed_strengths": [], "confidence_band_adjustment": "none"}
        if "live_q4_candidates" in low_user:
            return {"live_q4_candidates": ["What decision did that retention comparison change, and what evidence supported it?", "What could make that comparison misleading for the team?"]}
        if "return json only" in low_user and "accepted" in low_user and "risk_flags" in low_user:
            return {"accepted": True, "reason": "control acceptance", "risk_flags": []}
        if "return json" in low_user and "question" in low_user and ("repair" in low_user or "rewrite" in low_user):
            return {"question": "What evidence would make the retention comparison useful for a product decision?"}
        if "return json" in low_user and "updates" in low_user:
            return {"updates": []}
        if "return one sentence" in low_user or "extract the strongest grounded transfer anchor" in low_user:
            return "the retention cohort and reporting choices the candidate described"
        if "return json" in low_user and "dimensions" in low_user and "coverage" in low_user:
            return {"dimensions": []}
        # FollowUpAgent paths accept either a question string or a dict.  The
        # output is grounded in the current exchange but does not introduce
        # a world fact or a future route.
        return "What evidence supported that decision, and what limitation would you explain to the team?"


@dataclass(frozen=True)
class CompleteInterviewRunnerConfig:
    world_id: str = DEFAULT_WORLD_ID
    target_role: str = DEFAULT_ROLE
    years_experience: str = DEFAULT_YEARS
    max_turns: int = DEFAULT_MAX_TURNS
    control_seed: int = 17
    runtime_epoch: int = 0
    quiescence_timeout_seconds: float = 8.0
    artifact_dir: Path | None = None
    playback_failure_modes: Mapping[int, str] = field(default_factory=dict)


@dataclass
class CompleteInterviewRunnerResult:
    status: str
    session_id: str
    turns_committed: int
    trace_records: list[dict[str, Any]]
    canonical_spoken_history: list[dict[str, Any]]
    artifact_path: str = ""
    artifact_sha256: str = ""
    manifest_path: str = ""
    manifest_sha256: str = ""
    blocker: dict[str, Any] | None = None
    report_summary: dict[str, Any] = field(default_factory=dict)
    adapter_audit: dict[str, Any] = field(default_factory=dict)
    quiescence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "status": self.status,
            "session_id": self.session_id,
            "turns_committed": self.turns_committed,
            "trace_records": _clone(self.trace_records),
            "canonical_spoken_history": _clone(self.canonical_spoken_history),
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "blocker": _clone(self.blocker),
            "report_summary": _clone(self.report_summary),
            "adapter_audit": _clone(self.adapter_audit),
            "quiescence": _clone(self.quiescence),
        }


class CompleteInterviewRunnerV1:
    """Drive one frozen world through the real Orchestrator decision path."""

    def __init__(
        self,
        config: CompleteInterviewRunnerConfig | None = None,
        *,
        session_store: IsolatedSessionStore | None = None,
        telemetry_sink: IsolatedTelemetrySink | None = None,
        report_sink: IsolatedReportSink | None = None,
        playback_adapter: BrowserPlaybackAdapter | None = None,
        tts_adapter: DeterministicTTSAdapter | None = None,
        candidate_actor: DeterministicActualGrantCandidate | None = None,
        control_router: DeterministicControlLLMRouter | None = None,
    ) -> None:
        self.config = config or CompleteInterviewRunnerConfig()
        if self.config.max_turns < 1:
            raise ValueError("max_turns must be positive")
        if self.config.world_id != DEFAULT_WORLD_ID:
            raise ValueError("the first checkpoint is intentionally limited to world_01_product_analyst")
        self.session_store = session_store or IsolatedSessionStore()
        self.telemetry_sink = telemetry_sink or IsolatedTelemetrySink()
        self.report_sink = report_sink or IsolatedReportSink()
        self.playback_adapter = playback_adapter or BrowserPlaybackAdapter(
            failure_modes=self.config.playback_failure_modes
        )
        self.tts_adapter = tts_adapter or DeterministicTTSAdapter()
        self.candidate_actor = candidate_actor or DeterministicActualGrantCandidate(
            self.config.world_id,
            seed=self.config.control_seed,
        )
        self.control_router = control_router or DeterministicControlLLMRouter()
        self.orchestrator: Orchestrator | None = None
        self.trace: InterviewTraceV1 | None = None
        self.quiescence: list[dict[str, Any]] = []
        self.blocker: dict[str, Any] | None = None

    @contextmanager
    def _isolated_production_bindings(self):
        """Patch only external boundaries while retaining production logic."""
        import importlib
        import backend.models.llm_router as llm_router_module
        import backend.services.interview_map as interview_map_module
        import backend.services.interview_telemetry as telemetry_module
        import backend.services.surface_plan as surface_plan_module
        import backend.agents.application_agent as application_module

        old = {
            "trace": telemetry_module.interview_telemetry,
            "orchestrator_trace": __import__("backend.services.orchestrator", fromlist=["interview_telemetry"]).interview_telemetry,
            "persist": __import__("backend.services.orchestrator", fromlist=["persist_session"]).persist_session,
            "handoff_complete": __import__("backend.services.orchestrator", fromlist=["notify_handoff_complete"]).notify_handoff_complete,
            "handoff_failed": __import__("backend.services.orchestrator", fromlist=["notify_handoff_failed"]).notify_handoff_failed,
            "llm_router": llm_router_module.LLMRouter,
            "map_llm": interview_map_module.LLMRouter,
            "surface_llm": surface_plan_module.LLMRouter,
            "application_llm": application_module.LLMRouter,
        }
        agent_module_names = (
            "backend.agents.concept_agent",
            "backend.agents.weakness_agent",
            "backend.agents.followup_agent",
            "backend.agents.discrepancy_agent",
            "backend.agents.evaluation_agent",
            "backend.agents.resume_agent",
            "backend.agents.reasoning_behavior_agent",
        )
        old["agent_llms"] = {
            name: getattr(importlib.import_module(name), "LLMRouter")
            for name in agent_module_names
        }
        orchestrator_module = __import__("backend.services.orchestrator", fromlist=["Orchestrator"])
        telemetry_module.interview_telemetry = self.telemetry_sink
        orchestrator_module.interview_telemetry = self.telemetry_sink
        orchestrator_module.persist_session = self.report_sink.persist_session
        orchestrator_module.notify_handoff_complete = self.report_sink.notify_handoff_complete
        orchestrator_module.notify_handoff_failed = self.report_sink.notify_handoff_failed
        llm_router_module.LLMRouter = DeterministicControlLLMRouter
        interview_map_module.LLMRouter = DeterministicControlLLMRouter
        surface_plan_module.LLMRouter = DeterministicControlLLMRouter
        application_module.LLMRouter = DeterministicControlLLMRouter
        for name in agent_module_names:
            setattr(importlib.import_module(name), "LLMRouter", DeterministicControlLLMRouter)
        try:
            yield
        finally:
            telemetry_module.interview_telemetry = old["trace"]
            orchestrator_module.interview_telemetry = old["orchestrator_trace"]
            orchestrator_module.persist_session = old["persist"]
            orchestrator_module.notify_handoff_complete = old["handoff_complete"]
            orchestrator_module.notify_handoff_failed = old["handoff_failed"]
            llm_router_module.LLMRouter = old["llm_router"]
            interview_map_module.LLMRouter = old["map_llm"]
            surface_plan_module.LLMRouter = old["surface_llm"]
            application_module.LLMRouter = old["application_llm"]
            for name, router_class in old["agent_llms"].items():
                setattr(importlib.import_module(name), "LLMRouter", router_class)

    def _bind_existing_agent_routers(self, orchestrator: Orchestrator) -> None:
        for agent in (
            orchestrator.concept_agent,
            orchestrator.weakness_agent,
            orchestrator.followup_agent,
            orchestrator.discrepancy_agent,
            orchestrator.evaluation_agent,
            orchestrator.resume_agent,
            orchestrator.reasoning_agent,
            orchestrator.policy_checker_agent,
        ):
            for name in tuple(vars(agent)):
                if name == "llm" or name.endswith("_llm") or name == "llm_fast":
                    if "repair_fallback_llms" not in name:
                        setattr(agent, name, self.control_router)

    async def _await_background_quiescence(self, session_id: str, *, boundary: str) -> dict[str, Any]:
        orchestrator = self.orchestrator
        if orchestrator is None:
            raise RuntimeError("runner orchestrator is not initialized")
        started = time.perf_counter()
        timed_out = False
        while True:
            pipeline = bool(orchestrator._pipeline_inflight)
            turn_pipeline = bool(orchestrator._turn_pipeline_running.get(session_id))
            hydration = session_id in orchestrator._hydration_inflight
            finalization = session_id in orchestrator._finalization_inflight
            if not pipeline and not turn_pipeline and not hydration and not finalization:
                break
            if time.perf_counter() - started >= self.config.quiescence_timeout_seconds:
                timed_out = True
                break
            await asyncio.sleep(0.001)
        record = {
            "boundary": boundary,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "timed_out": timed_out,
            "pipeline_inflight": len(orchestrator._pipeline_inflight),
            "turn_pipeline_running": len(orchestrator._turn_pipeline_running.get(session_id, set())),
            "hydration_inflight": session_id in orchestrator._hydration_inflight,
            "finalization_inflight": session_id in orchestrator._finalization_inflight,
        }
        self.quiescence.append(record)
        await self.telemetry_sink.log(session_id, "runner_background_quiescence", source="runner", **record)
        return record

    def _trace_event(self, event_type: str, *, turn_id: str = "") -> dict[str, Any] | None:
        assert self.trace is not None
        for event in reversed(self.trace.events):
            if event.event_type == event_type and (not turn_id or event.turn_id == turn_id):
                return event.to_record()
        return None

    def _semantic_interpretation(self, *, analysis: Mapping[str, Any], response: Mapping[str, Any], answer: str) -> dict[str, Any]:
        # This is a trace boundary record, not a new evaluator.  It cites only
        # production output and the exact committed answer's shape; no frozen
        # world truth is copied into the Orchestrator or report.
        return {
            "source": "orchestrator_control_shadow",
            "control_only": True,
            "served_route_kind": str(response.get("route_kind") or ""),
            "answer_chars": len(answer),
            "weakness_type": str((analysis.get("weakness") or {}).get("type") or "") if isinstance(analysis.get("weakness"), dict) else "",
            "weakness_severity": str((analysis.get("weakness") or {}).get("severity") or "") if isinstance(analysis.get("weakness"), dict) else "",
            "discrepancy_level": str((analysis.get("discrepancy") or {}).get("conflict_level") or "") if isinstance(analysis.get("discrepancy"), dict) else "",
            "analysis_status": "shadow_control",
        }

    async def _record_answer_boundary(
        self,
        *,
        turn_number: int,
        turn_id: str,
        answer: str,
        response: Mapping[str, Any],
        state_after: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        assert self.trace is not None
        spoken = self._trace_event(TraceEventType.SPOKEN_QUESTION_COMMITTED.value, turn_id=turn_id)
        if not spoken:
            raise TraceReferenceError(f"no spoken question for committed answer {turn_id}")
        answer_receipt = self.trace.record_answer_received(
            turn_id=turn_id,
            answer_version=1,
            spoken_question_event_id=str(spoken["event_id"]),
            answer_text=answer,
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.candidate_actor_boundary",
            idempotency_key=f"answer:{turn_id}:1",
        )
        queue = state_after.get("prepped_turn_queue") or []
        analysis: dict[str, Any] = {}
        if isinstance(queue, list):
            for item in reversed(queue):
                if isinstance(item, dict) and item.get("turn_id") == turn_id:
                    candidate = item.get("analysis")
                    if isinstance(candidate, dict):
                        analysis = candidate
                        break
        semantic = self.trace.record_semantic_interpretation_finalized(
            turn_id=turn_id,
            answer_version=1,
            answer_event_id=answer_receipt.event_id,
            interpretation=self._semantic_interpretation(analysis=analysis, response=response, answer=answer),
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"semantic-final:{turn_id}:1",
        )
        next_question = str(response.get("response") or "").strip()
        route_kind = str(response.get("route_kind") or "").strip()
        terminal = bool(response.get("complete")) or route_kind in {"complete", "synthesis_close"} and not next_question
        admitted: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        if next_question and not bool(response.get("complete")):
            admitted.append({
                "opportunity_id": f"opp:{turn_id}:next",
                "kind": route_kind or "orchestrator_next_question",
                "surface_id": str((response.get("focus_key") or state_after.get("current_answer_context", {}).get("focus_key") or "") if isinstance(state_after.get("current_answer_context"), dict) else ""),
                "surface_label": str((response.get("focus_label") or "") or ""),
                "reason": "actual Orchestrator response",
                "evidence_event_ids": [semantic.event_id],
            })
        else:
            excluded.append({
                "opportunity_id": f"opp:{turn_id}:terminal",
                "reason": "actual Orchestrator returned no next visible route",
                "evidence_event_ids": [semantic.event_id],
            })
        inventory = self.trace.record_opportunity_inventory_compiled(
            turn_id=turn_id,
            answer_version=1,
            semantic_event_id=semantic.event_id,
            admitted_candidates=admitted,
            excluded_candidates=excluded,
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"inventory:{turn_id}:1",
        )
        evidence = self.trace.record_evidence_state_updated(
            turn_id=turn_id,
            answer_version=1,
            semantic_event_id=semantic.event_id,
            opportunity_inventory_event_id=inventory.event_id,
            evidence_state={
                "status": "shadow_control",
                "answer_committed": True,
                "next_route_available": bool(admitted),
                "terminal": terminal,
            },
            source_event_ids=[semantic.event_id, inventory.event_id],
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"evidence:{turn_id}:1",
        )
        return semantic.event_id, evidence.event_id, str(admitted[0]["opportunity_id"]) if admitted else ""

    async def _materialize_and_deliver(
        self,
        *,
        turn_number: int,
        turn_id: str,
        question: str,
        route_kind: str,
        opportunity_id: str,
        evidence_event_id: str,
        prior_spoken_event_id: str,
        action_grant_event_id: str,
    ) -> bool:
        assert self.trace is not None
        validation = self.trace.record_state_transition_validated(
            turn_id=turn_id,
            answer_version=1,
            decision="accepted",
            visible_route_commit_allowed=True,
            source_opportunity_id=opportunity_id,
            source_evidence_event_ids=[evidence_event_id],
            prior_spoken_question_event_id=prior_spoken_event_id,
            action_grant_event_id=action_grant_event_id,
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"validation:{turn_id}:1",
        )
        if not validation.accepted:
            return False
        materialized = self.trace.record_question_materialized(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question:{turn_id}",
            visible_text=question,
            source_opportunity_id=opportunity_id,
            source_evidence_event_ids=[evidence_event_id],
            prior_spoken_question_event_id=prior_spoken_event_id,
            action_grant_event_id=action_grant_event_id,
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"materialized:{turn_id}:1",
            route_kind=route_kind,
        )
        prepared = self.trace.record_question_prepared(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question:{turn_id}",
            materialized_event_id=materialized.event_id,
            source_opportunity_id=opportunity_id,
            source_evidence_event_ids=[evidence_event_id],
            prior_spoken_question_event_id=prior_spoken_event_id,
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"prepared:{turn_id}:1",
        )
        # The TTS adapter is intentionally only pre-generation metadata.  It
        # cannot advance spoken truth; only BrowserPlaybackAdapter can do that.
        try:
            await self.tts_adapter.pre_generate(self.trace.session_id, question)
        except Exception as exc:
            await self.telemetry_sink.log(
                self.trace.session_id,
                "runner_tts_failure",
                source="runner",
                turn_id=turn_id,
                error_type=type(exc).__name__,
            )
            # The browser adapter still records the failed delivery attempt so
            # a TTS error can never silently become spoken truth.
            mode = "tts_failure"
        else:
            mode = self.playback_adapter.mode_for_turn(turn_number)
        delivery = await self.playback_adapter.deliver(
            trace=self.trace,
            turn_id=turn_id,
            answer_version=1,
            prepared_event_id=prepared.event_id,
            runtime_epoch=self.trace.runtime_epoch,
            turn_number=turn_number,
            attempt_number=1,
            mode=mode,
        )
        if not delivery.acknowledged:
            await self.telemetry_sink.log(
                self.trace.session_id,
                "runner_spoken_truth_blocked",
                source="runner",
                level="warn",
                turn_id=turn_id,
                reason=delivery.failure_reason or "no_playback_ack",
            )
            return False
        started_attempt = f"delivery-{turn_id}-1"
        ack_event = self._trace_event(TraceEventType.PLAYBACK_ACKNOWLEDGED.value, turn_id=turn_id)
        if not ack_event:
            return False
        spoken = self.trace.record_spoken_question_committed(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question:{turn_id}",
            visible_text=question,
            question_materialized_event_id=materialized.event_id,
            playback_ack_event_id=str(ack_event["event_id"]),
            delivery_attempt_id=started_attempt,
            prior_spoken_question_event_id=prior_spoken_event_id,
            source_opportunity_id=opportunity_id,
            source_evidence_event_ids=[evidence_event_id],
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.browser_playback_adapter",
            idempotency_key=f"spoken:{turn_id}:1",
        )
        return bool(spoken.accepted)

    async def _commit_opening_question(self, *, question: str) -> bool:
        assert self.trace is not None
        turn_id = "control-turn-01"
        session_event = self.trace.events[0]
        validation = self.trace.record_state_transition_validated(
            turn_id=turn_id,
            answer_version=1,
            decision="accepted",
            visible_route_commit_allowed=True,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session_event.event_id],
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"validation:{turn_id}:1",
        )
        if not validation.accepted:
            return False
        materialized = self.trace.record_question_materialized(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question:{turn_id}",
            visible_text=question,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session_event.event_id],
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"materialized:{turn_id}:1",
            route_kind="warm_open",
        )
        prepared = self.trace.record_question_prepared(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question:{turn_id}",
            materialized_event_id=materialized.event_id,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session_event.event_id],
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.orchestrator_shadow_boundary",
            idempotency_key=f"prepared:{turn_id}:1",
        )
        try:
            await self.tts_adapter.pre_generate(self.trace.session_id, question)
        except Exception as exc:
            await self.telemetry_sink.log(
                self.trace.session_id,
                "runner_tts_failure",
                source="runner",
                turn_id=turn_id,
                error_type=type(exc).__name__,
            )
            mode = "tts_failure"
        else:
            mode = self.playback_adapter.mode_for_turn(1)
        delivery = await self.playback_adapter.deliver(
            trace=self.trace,
            turn_id=turn_id,
            answer_version=1,
            prepared_event_id=prepared.event_id,
            runtime_epoch=self.trace.runtime_epoch,
            turn_number=1,
            mode=mode,
        )
        if not delivery.acknowledged:
            return False
        ack = self._trace_event(TraceEventType.PLAYBACK_ACKNOWLEDGED.value, turn_id=turn_id)
        if not ack:
            return False
        spoken = self.trace.record_spoken_question_committed(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question:{turn_id}",
            visible_text=question,
            question_materialized_event_id=materialized.event_id,
            playback_ack_event_id=str(ack["event_id"]),
            delivery_attempt_id=f"delivery-{turn_id}-1",
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session_event.event_id],
            runtime_epoch=self.trace.runtime_epoch,
            producer="runner.browser_playback_adapter",
            idempotency_key=f"spoken:{turn_id}:1",
        )
        return bool(spoken.accepted)

    def _report_summary(self, state: Mapping[str, Any]) -> dict[str, Any]:
        evaluation = state.get("final_evaluation") if isinstance(state, Mapping) else None
        report = evaluation if isinstance(evaluation, dict) else {}
        return {
            "shadow_only": True,
            "candidate_quality_claim": "not_assessed",
            "schema_version": str(report.get("schema_version") or ""),
            "finalization_status": str(state.get("finalization_status") or ""),
            "report_ready": bool(state.get("report_ready")),
            "report_sha256": sha256_json(report) if report else "",
            "hire_recommendation_excluded": True,
        }

    def _build_artifact(self, result: CompleteInterviewRunnerResult, state: Mapping[str, Any]) -> dict[str, Any]:
        assert self.trace is not None
        source_trace_integrity_verified = bool(self.trace.verify_integrity())
        evaluator_projection = self.trace.project(TraceView.EVALUATOR)
        return {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "artifact_kind": "redacted_projection_only",
            "world_id": self.config.world_id,
            "session_id": self.trace.session_id,
            "runtime_epoch": self.trace.runtime_epoch,
            "status": result.status,
            "turns_committed": result.turns_committed,
            "blocker": _clone(result.blocker),
            "trace": {
                "records": self.trace.export_records(),
                "evaluator_projection": evaluator_projection,
                "canonical_spoken_history": self.trace.canonical_spoken_history(),
                "canonical_trace_file": CANONICAL_TRACE_FILE,
                "source_trace_integrity_verified_before_redaction": source_trace_integrity_verified,
            },
            "adapter_audit": _clone(result.adapter_audit),
            "quiescence": _clone(self.quiescence),
            "report_summary": _clone(result.report_summary),
            "redaction": {
                "raw_provider_prompts_excluded": True,
                "raw_provider_responses_excluded": True,
                "secrets_excluded": True,
                "actor_private_truth_excluded_from_orchestrator": True,
                "trace_payloads_are_InterviewTraceV1_redacted_records": True,
                "redacted_records_are_not_reconstruction_source": True,
            },
            "hashes": {
                "redacted_projection_records_sha256": sha256_json(self.trace.export_records()),
                "evaluator_projection_sha256": sha256_json(evaluator_projection),
                "canonical_spoken_history_sha256": sha256_json(self.trace.canonical_spoken_history()),
            },
        }

    def _write_artifact(self, result: CompleteInterviewRunnerResult, state: Mapping[str, Any]) -> None:
        artifact_dir = self.config.artifact_dir
        if artifact_dir is None:
            return
        artifact_dir = Path(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        assert self.trace is not None
        canonical_records = self.trace.export_records()
        canonical_trace_path = artifact_dir / CANONICAL_TRACE_FILE
        # Do not sort keys here.  InterviewTraceV1's provenance source-ref
        # order is part of its canonical export and must survive disk reload.
        _write_owner_only_text(
            canonical_trace_path,
            json.dumps(canonical_records, ensure_ascii=True, indent=2) + "\n",
        )
        canonical_trace_sha256 = hashlib.sha256(canonical_trace_path.read_bytes()).hexdigest()
        artifact = self._build_artifact(result, state)
        artifact["trace"]["canonical_trace_sha256"] = canonical_trace_sha256
        artifact["hashes"]["canonical_trace_sha256"] = canonical_trace_sha256
        artifact_path = artifact_dir / REDACTED_ARTIFACT_FILE
        _write_owner_only_text(
            artifact_path,
            json.dumps(artifact, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        )
        redacted_artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "artifact_kind": artifact["artifact_kind"],
            "redacted_artifact_file": artifact_path.name,
            "redacted_artifact_sha256": redacted_artifact_sha256,
            "canonical_trace_file": canonical_trace_path.name,
            "canonical_trace_sha256": canonical_trace_sha256,
            "canonical_spoken_history_sha256": artifact["hashes"]["canonical_spoken_history_sha256"],
            "evaluator_projection_sha256": artifact["hashes"]["evaluator_projection_sha256"],
            "source_trace_integrity_verified_before_redaction": artifact["trace"]["source_trace_integrity_verified_before_redaction"],
            "redaction_policy": artifact["redaction"],
        }
        manifest_path = artifact_dir / RUN_MANIFEST_FILE
        _write_owner_only_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        )
        result.artifact_path = str(artifact_path)
        result.artifact_sha256 = manifest["redacted_artifact_sha256"]
        result.manifest_path = str(manifest_path)
        result.manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    async def run(self) -> CompleteInterviewRunnerResult:
        with self._isolated_production_bindings():
            orchestrator = Orchestrator(tts_service=self.tts_adapter)
            self.orchestrator = orchestrator
            orchestrator.session_manager = self.session_store
            self._bind_existing_agent_routers(orchestrator)
            try:
                resume_projection = load_actor_turn_projection(self.config.world_id)
                resume_text = str((resume_projection.get("resume") or {}).get("text") or "").strip()
                session_id = await orchestrator.prepare_session_map(
                    resume_text,
                    [],
                    target_role=self.config.target_role,
                    years_experience=self.config.years_experience,
                )
                self.trace = InterviewTraceV1(session_id, runtime_epoch=self.config.runtime_epoch)
                await orchestrator.start_prepared_session(session_id)
                state = await self.session_store.get_state(session_id)
                opening_question = str(state.get("last_question") or "").strip()
                if not opening_question:
                    raise RuntimeError("production Orchestrator returned no opening question")
                if not await self._commit_opening_question(question=opening_question):
                    self.blocker = {"layer": "browser_playback", "reason": "opening_question_not_spoken"}
                    result = CompleteInterviewRunnerResult(
                        status="blocked",
                        session_id=session_id,
                        turns_committed=0,
                        trace_records=self.trace.export_records(),
                        canonical_spoken_history=self.trace.canonical_spoken_history(),
                        blocker=self.blocker,
                        adapter_audit=self._adapter_audit(),
                    )
                    self._write_artifact(result, state)
                    return result

                turns_committed = 0
                for turn_number in range(1, self.config.max_turns + 1):
                    turn_id = f"control-turn-{turn_number:02d}"
                    if not self._trace_event(TraceEventType.SPOKEN_QUESTION_COMMITTED.value, turn_id=turn_id):
                        self.blocker = {"layer": "trace_delivery", "turn_number": turn_number, "reason": "question_not_spoken"}
                        break
                    spoken = self._trace_event(TraceEventType.SPOKEN_QUESTION_COMMITTED.value, turn_id=turn_id)
                    question = str((spoken or {}).get("payload", {}).get("views", {}).get(TraceView.EVALUATOR.value, {}).get("question_text") or "")
                    if not question:
                        self.blocker = {"layer": "trace_provenance", "turn_number": turn_number, "reason": "served_question_text_missing"}
                        break
                    actor_response = await self.candidate_actor.answer(turn_number=turn_number, question=question)
                    answer = str(actor_response.answer_text).strip()
                    response = await orchestrator.handle_transcript(
                        session_id,
                        answer,
                        entities=[],
                        turn_id=turn_id,
                    )
                    await self._await_background_quiescence(session_id, boundary=f"after_{turn_id}")
                    state_after = await self.session_store.get_state(session_id)
                    _, evidence_event_id, opportunity_id = await self._record_answer_boundary(
                        turn_number=turn_number,
                        turn_id=turn_id,
                        answer=answer,
                        response=response,
                        state_after=state_after,
                    )
                    turns_committed += 1
                    if bool(response.get("complete")) or not str(response.get("response") or "").strip():
                        break
                    next_turn_number = turn_number + 1
                    if next_turn_number > self.config.max_turns:
                        break
                    next_turn_id = f"control-turn-{next_turn_number:02d}"
                    prior_spoken_id = str((spoken or {}).get("event_id") or "")
                    grant = self.trace.record_action_grant_selected(
                        turn_id=next_turn_id,
                        answer_version=1,
                        opportunity_inventory_event_id=str(self._trace_event(TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value, turn_id=turn_id)["event_id"]),
                        opportunity_id=opportunity_id,
                        source_evidence_event_ids=[str(self._trace_event(TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value, turn_id=turn_id)["event_id"])],
                        prior_spoken_question_event_id=prior_spoken_id,
                        action=str(response.get("route_kind") or "orchestrator_next_question"),
                        runtime_epoch=self.trace.runtime_epoch,
                        producer="runner.orchestrator_shadow_boundary",
                        idempotency_key=f"grant:{next_turn_id}:1",
                    )
                    next_question = str(response.get("response") or "").strip()
                    if not await self._materialize_and_deliver(
                        turn_number=next_turn_number,
                        turn_id=next_turn_id,
                        question=next_question,
                        route_kind=str(response.get("route_kind") or ""),
                        opportunity_id=opportunity_id,
                        evidence_event_id=str(self._trace_event(TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value, turn_id=turn_id)["event_id"]),
                        prior_spoken_event_id=prior_spoken_id,
                        action_grant_event_id=grant.event_id,
                    ):
                        self.blocker = {"layer": "browser_playback", "turn_number": next_turn_number, "reason": "next_question_not_spoken"}
                        break

                await self._await_background_quiescence(session_id, boundary="before_finalization")
                state = await self.session_store.get_state(session_id)
                if self.blocker is None and turns_committed >= self.config.max_turns and not state.get("interview_complete"):
                    # The controller owns completion; a bounded checkpoint that
                    # reaches the turn cap without its completion signal is an
                    # exact production-layer blocker, not a forced route.
                    self.blocker = {
                        "layer": "production_orchestrator_completion",
                        "reason": "max_turns_reached_without_controller_completion",
                        "turns_committed": turns_committed,
                    }
                if state.get("finalization_status") not in {"complete", "running"} or not state.get("report_ready"):
                    state = await orchestrator.end_session(session_id)
                    await self._await_background_quiescence(session_id, boundary="after_end_session")
                    state = await self.session_store.get_state(session_id)
                evidence_events = [
                    event.event_id
                    for event in self.trace.events
                    if event.event_type == TraceEventType.EVIDENCE_STATE_UPDATED.value
                ]
                if evidence_events and state.get("report_ready"):
                    claim = self.trace.record_report_claim_emitted(
                        claim_id="shadow-control-completion",
                        claim_text="SHADOW_ONLY: the bounded production-control run completed its recorded boundary.",
                        source_evidence_event_ids=[evidence_events[-1]],
                        audience="operator",
                        runtime_epoch=self.trace.runtime_epoch,
                        producer="runner.report_shadow_sink",
                        idempotency_key="report-claim:shadow-control-completion",
                    )
                    self.trace.record_final_evaluation_completed(
                        evaluation_id="shadow-control-final",
                        report_claim_event_ids=[claim.event_id],
                        evidence_event_ids=[evidence_events[-1]],
                        evaluation_summary={
                            "shadow_only": True,
                            "actor_quality": "not_assessed",
                            "production_report_schema": str((state.get("final_evaluation") or {}).get("schema_version") or ""),
                            "production_report_sha256": sha256_json(state.get("final_evaluation") or {}),
                        },
                        runtime_epoch=self.trace.runtime_epoch,
                        producer="runner.report_shadow_sink",
                        idempotency_key="final-evaluation:shadow-control-final",
                    )
                self.trace.verify_integrity()
                status = "complete" if turns_committed == self.config.max_turns and self.blocker is None else "blocked"
                result = CompleteInterviewRunnerResult(
                    status=status,
                    session_id=session_id,
                    turns_committed=turns_committed,
                    trace_records=self.trace.export_records(),
                    canonical_spoken_history=self.trace.canonical_spoken_history(),
                    blocker=self.blocker,
                    report_summary=self._report_summary(state),
                    adapter_audit=self._adapter_audit(),
                    quiescence=self.quiescence,
                )
                self._write_artifact(result, state)
                return result
            except Exception as exc:
                if self.trace is None:
                    raise
                self.blocker = {
                    "layer": "runner_execution",
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:500],
                }
                state = await self.session_store.get_state(session_id) if 'session_id' in locals() else {}
                result = CompleteInterviewRunnerResult(
                    status="blocked",
                    session_id=self.trace.session_id,
                    turns_committed=len(self.trace.canonical_spoken_history()),
                    trace_records=self.trace.export_records(),
                    canonical_spoken_history=self.trace.canonical_spoken_history(),
                    blocker=self.blocker,
                    report_summary=self._report_summary(state),
                    adapter_audit=self._adapter_audit(),
                    quiescence=self.quiescence,
                )
                self._write_artifact(result, state)
                return result

    def _adapter_audit(self) -> dict[str, Any]:
        return {
            "production_code_called": [
                "Orchestrator.prepare_session_map",
                "Orchestrator.start_prepared_session",
                "Orchestrator.handle_transcript",
                "Orchestrator._run_background_pipeline",
                "Orchestrator._generate_application_transfer",
                "Orchestrator.end_session",
                "ResumeAgent.parse",
                "Interview map generation/validation/selection",
                "all configured production agents through the Orchestrator",
                "InterviewTraceV1 append/invariant/integrity methods",
            ],
            "isolated_adapters": [
                "IsolatedSessionStore: replaces Redis session I/O",
                "IsolatedTelemetrySink: replaces file telemetry I/O",
                "IsolatedReportSink: replaces Postgres persistence and ProvenHire handoff",
                "DeterministicTTSAdapter: replaces external TTS pre-generation only",
                "BrowserPlaybackAdapter: replaces browser playback completion ACK",
                "DeterministicActualGrantCandidate: replaces CandidateActor provider boundary",
                "DeterministicControlLLMRouter: no-paid provider response seam only; not route/map/report authority",
            ],
            "forbidden_external_state_touched": ["developer Redis", "Postgres", "production telemetry files", "Cartesia", "ElevenLabs", "paid LLM providers", "live routes/UI/audio"],
            "candidate_actor_quality": "not_assessed; deterministic actual-grant fixture/control only",
        }


__all__ = [
    "ActualGrantControlGenerator",
    "BrowserPlaybackAdapter",
    "CompleteInterviewRunnerConfig",
    "CompleteInterviewRunnerResult",
    "CompleteInterviewRunnerV1",
    "CONTROL_PROVIDER_ID",
    "DeterministicActualGrantCandidate",
    "DeterministicControlLLMRouter",
    "DeterministicTTSAdapter",
    "IsolatedReportSink",
    "IsolatedSessionStore",
    "IsolatedTelemetrySink",
    "PlaybackDeliveryResult",
    "RUNNER_SCHEMA_VERSION",
    "sha256_json",
]
