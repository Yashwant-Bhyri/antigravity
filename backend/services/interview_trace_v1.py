"""Immutable causal trace contract for complete Antigravity interviews.

This module is intentionally isolated from the live interviewer.  It provides a
small, standard-library-only contract that a later integration checkpoint can
feed from the existing orchestrator, TTS, browser playback, and report seams.

The trace is an append-only hash chain.  Lifecycle helpers mutate only the
trace's derived index; they never rewrite an earlier event.  A rejected or
stale operation is represented by a ``state_transition_validated`` event with a
rejected decision, while the attempted operation itself is not treated as
canonical truth.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence


TRACE_SCHEMA_VERSION = "interview_trace_v1"
PAYLOAD_SCHEMA_VERSION = "interview_trace_payload_v1"
GENESIS_HASH = "0" * 64
REDACTED = "[REDACTED]"


class TraceEventType(str, Enum):
    SESSION_STARTED = "session_started"
    RUNTIME_EPOCH_ADVANCED = "runtime_epoch_advanced"
    QUESTION_PREPARED = "question_prepared"
    QUESTION_DELIVERY_STARTED = "question_delivery_started"
    PLAYBACK_ACKNOWLEDGED = "playback_acknowledged"
    DELIVERY_FAILED = "delivery_failed"
    SPOKEN_QUESTION_COMMITTED = "spoken_question_committed"
    ANSWER_RECEIVED = "answer_received"
    SEMANTIC_INTERPRETATION_FINALIZED = "semantic_interpretation_finalized"
    SEMANTIC_INTERPRETATION_SHADOW = "semantic_interpretation_shadow"
    OPPORTUNITY_INVENTORY_COMPILED = "opportunity_inventory_compiled"
    ACTION_GRANT_SELECTED = "action_grant_selected"
    QUESTION_MATERIALIZED = "question_materialized"
    STATE_TRANSITION_VALIDATED = "state_transition_validated"
    EVIDENCE_STATE_UPDATED = "evidence_state_updated"
    REPORT_CLAIM_EMITTED = "report_claim_emitted"
    FINAL_EVALUATION_COMPLETED = "final_evaluation_completed"


_TRACE_EVENT_NAMES = frozenset(event_type.value for event_type in TraceEventType)

# Opportunity inventories are compiled from an immutable semantic decision.
# Keep their evidence references typed to decision-bearing events so a
# serialized inventory cannot smuggle in session/delivery/diagnostic events as
# if they were candidate evidence.
_OPPORTUNITY_EVIDENCE_EVENT_TYPES = frozenset(
    {
        TraceEventType.ANSWER_RECEIVED.value,
        TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
        TraceEventType.EVIDENCE_STATE_UPDATED.value,
    }
)


class PlaybackAckStatus(str, Enum):
    """The only browser acknowledgement that establishes positive playback truth."""

    COMPLETED = "playback_completed"


class TraceView(str, Enum):
    CANDIDATE = "candidate"
    ACTOR = "actor"
    INTERVIEWER = "interviewer"
    EVALUATOR = "evaluator"
    OPERATOR = "operator"


class TraceError(Exception):
    """Base class for trace-contract failures."""


class TraceInvariantError(TraceError):
    """An operation would violate the causal lifecycle or a hard invariant."""


class TraceReferenceError(TraceInvariantError):
    """An event or source opportunity reference is missing or inconsistent."""


class TraceStaleError(TraceInvariantError):
    """An operation belongs to an old answer version or runtime epoch."""


class TraceConflictError(TraceInvariantError):
    """An idempotency key/event id was reused with different content."""


class TraceIntegrityError(TraceError):
    """The serialized event chain was mutated, truncated, or reordered."""


class TraceImmutableDecisionError(TraceInvariantError):
    """A decision-time semantic output was asked to be overwritten."""


def _freeze_value(value: Any) -> Any:
    """Recursively freeze JSON-shaped values used inside a trace event."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(child) for child in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(child) for child in value)
    return copy.deepcopy(value)


def _thaw_value(value: Any) -> Any:
    """Return a mutable JSON-shaped copy for serialization/projection."""
    if isinstance(value, Mapping):
        return {str(key): _thaw_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_value(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_thaw_value(child) for child in value)
    return copy.deepcopy(value)


@dataclass(frozen=True)
class TraceReceipt:
    """Result of an append attempt.

    ``accepted`` describes whether the attempted domain operation was applied.
    A duplicate retry is accepted and marked ``idempotent``.  A stale or
    domain-rejected operation returns ``accepted=False`` with one canonical
    rejection/audit event.  Exceptions from validation, conflict, clock, or
    append failure leave the trace byte-for-byte unchanged.
    """

    accepted: bool
    event: "TraceEvent | None"
    idempotent: bool = False
    reason: str = ""

    @property
    def event_id(self) -> str:
        return self.event.event_id if self.event is not None else ""


@dataclass(frozen=True)
class TraceEvent:
    schema_version: str
    event_id: str
    session_id: str
    turn_id: str
    answer_version: int
    runtime_epoch: int
    sequence: int
    event_type: str
    causal_parent_ids: tuple[str, ...]
    occurred_at_ms: int
    recorded_at_ms: int
    producer: str
    payload_schema_version: str
    payload: Mapping[str, Any]
    decision_hash: str
    provenance_hash: str
    redaction: Mapping[str, Any]
    idempotency_key: str
    previous_event_hash: str
    event_hash: str

    def __post_init__(self) -> None:
        # ``frozen=True`` only protects attributes on the dataclass itself.
        # Freeze nested payloads as well so a receipt/event handed to a caller
        # cannot mutate the bytes covered by ``event_hash``.
        object.__setattr__(self, "causal_parent_ids", tuple(str(item) for item in self.causal_parent_ids))
        object.__setattr__(self, "payload", _freeze_value(self.payload))
        object.__setattr__(self, "redaction", _freeze_value(self.redaction))

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-safe copy suitable for durable storage."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "answer_version": self.answer_version,
            "runtime_epoch": self.runtime_epoch,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "causal_parent_ids": list(self.causal_parent_ids),
            "occurred_at_ms": self.occurred_at_ms,
            "recorded_at_ms": self.recorded_at_ms,
            "producer": self.producer,
            "payload_schema_version": self.payload_schema_version,
            "payload": _thaw_value(self.payload),
            "decision_hash": self.decision_hash,
            "provenance_hash": self.provenance_hash,
            "redaction": _thaw_value(self.redaction),
            "idempotency_key": self.idempotency_key,
            "previous_event_hash": self.previous_event_hash,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "TraceEvent":
        """Build an event from a serialized record without trusting its hash."""
        try:
            if not isinstance(record, Mapping):
                raise TraceIntegrityError("Trace event record must be an object")
            required = {
                "schema_version", "event_id", "session_id", "turn_id", "answer_version",
                "runtime_epoch", "sequence", "event_type", "causal_parent_ids", "occurred_at_ms",
                "recorded_at_ms", "producer", "payload_schema_version", "payload", "decision_hash",
                "provenance_hash", "redaction", "idempotency_key", "previous_event_hash", "event_hash",
            }
            missing = sorted(required - set(record.keys()))
            if missing:
                raise TraceIntegrityError(f"Trace event record is missing fields: {', '.join(missing)}")
            string_fields = (
                "schema_version", "event_id", "session_id", "turn_id", "event_type",
                "producer", "payload_schema_version", "decision_hash", "provenance_hash",
                "idempotency_key", "previous_event_hash", "event_hash",
            )
            for field_name in string_fields:
                if not isinstance(record[field_name], str):
                    raise TraceIntegrityError(f"Trace field {field_name} must be a string")
            integer_fields = ("answer_version", "runtime_epoch", "sequence", "occurred_at_ms", "recorded_at_ms")
            for field_name in integer_fields:
                if isinstance(record[field_name], bool) or not isinstance(record[field_name], int):
                    raise TraceIntegrityError(f"Trace field {field_name} must be an integer")
            raw_parents = record["causal_parent_ids"]
            if isinstance(raw_parents, (str, bytes)) or not isinstance(raw_parents, Sequence):
                raise TraceIntegrityError("causal_parent_ids must be an array")
            if any(not isinstance(item, str) for item in raw_parents):
                raise TraceIntegrityError("causal_parent_ids entries must be strings")
            raw_payload = record["payload"]
            if not isinstance(raw_payload, Mapping):
                raise TraceIntegrityError("payload must be an object")
            raw_redaction = record["redaction"]
            if not isinstance(raw_redaction, Mapping):
                raise TraceIntegrityError("redaction must be an object")
            return cls(
                schema_version=str(record["schema_version"]),
                event_id=str(record["event_id"]),
                session_id=str(record["session_id"]),
                turn_id=str(record["turn_id"] or ""),
                answer_version=int(record["answer_version"]),
                runtime_epoch=int(record.get("runtime_epoch", 0)),
                sequence=int(record["sequence"]),
                event_type=str(record["event_type"]),
                causal_parent_ids=tuple(str(item) for item in raw_parents),
                occurred_at_ms=int(record["occurred_at_ms"]),
                recorded_at_ms=int(record["recorded_at_ms"]),
                producer=str(record["producer"]),
                payload_schema_version=str(record["payload_schema_version"]),
                payload=copy.deepcopy(dict(raw_payload)),
                decision_hash=str(record["decision_hash"]),
                provenance_hash=str(record["provenance_hash"]),
                redaction=copy.deepcopy(dict(raw_redaction)),
                idempotency_key=str(record["idempotency_key"]),
                previous_event_hash=str(record["previous_event_hash"]),
                event_hash=str(record["event_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TraceIntegrityError(f"Malformed trace event record: {exc}") from exc


@dataclass
class _TurnLedger:
    runtime_epoch: int
    current_answer_version: int
    question_id: str = ""
    source_opportunity_id: str = ""
    source_evidence_event_ids: tuple[str, ...] = ()
    prior_spoken_question_event_id: str = ""
    materialized_event_id: str = ""
    prepared_event_id: str = ""
    action_grant_event_id: str = ""
    validation_event_id: str = ""
    validation_status: str = ""
    visible_route_commit_allowed: bool = False
    delivery_started_by_attempt: dict[str, str] = field(default_factory=dict)
    delivery_failed_attempts: set[str] = field(default_factory=set)
    delivery_failed_event_by_attempt: dict[str, str] = field(default_factory=dict)
    playback_ack_by_attempt: dict[str, str] = field(default_factory=dict)
    spoken_question_event_id: str = ""
    answer_event_by_version: dict[int, str] = field(default_factory=dict)
    semantic_final_by_version: dict[int, str] = field(default_factory=dict)
    shadow_event_ids_by_version: dict[int, list[str]] = field(default_factory=dict)
    inventory_event_by_version: dict[int, str] = field(default_factory=dict)
    evidence_event_by_version: dict[int, str] = field(default_factory=dict)


_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization|cookie|credential|"
    r"raw[_-]?(?:provider|payload|response|body)|provider[_-]?(?:payload|response|body)|"
    r"request[_-]?headers?|response[_-]?headers?|system[_-]?(?:prompt|message|content|instruction)|"
    r"user[_-]?(?:prompt|message|content|instruction)|hidden[_-]?(?:prompt|message|content|instruction)|"
    r"(?:developer|role|agent)[_-]?(?:prompt|message|content|instruction)|"
    r"(?:prompt|instruction|instructions|system|developer)[_-]?(?:text|template|body|content|message|context)?|"
    r"(?:prompt|instruction|instructions|system|developer))",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|credential)\s*[:=]\s*[^\s,;]+|"
    r"(?:sk|sk-ant|rk|ghp|github_pat|xox[baprs]-|AIza|AKIA)[A-Za-z0-9_\-]{8,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"https?://[^\s/@:]+:[^\s/@]+@[^\s]+|"
    r"(?:postgres|postgresql|redis|rediss)://[^\s]+|"
    r"-----BEGIN [A-Z ]+ PRIVATE KEY-----)",
    re.IGNORECASE,
)
_VIEW_NAMES = {view.value for view in TraceView}


def _is_sensitive_key(key: str) -> bool:
    """Match secret/prompt keys even when separators or casing are altered."""
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return bool(_SENSITIVE_KEY_RE.search(key)) or any(
        token in normalized
        for token in (
            "apikey", "accesstoken", "refreshtoken", "secret", "password",
            "authorization", "cookie", "credential", "privatekey", "prompt",
            "instruction", "systemmessage", "systemcontent", "developermessage",
            "developercontent", "usermessage", "usercontent", "hiddenmessage",
        )
    )


# Projection is a trust boundary, not a convenience serialization of the
# multi-view event payload.  Every view/event pair has an explicit key
# allowlist.  In particular, ``actor`` is CandidateActorV1: it may observe
# only candidate-owned/session, delivery, spoken-question, and own-answer
# acknowledgement facts.  It must never receive route, opportunity,
# semantic, evidence, report, or shadow truth.
_PROJECTION_ALLOWLISTS: dict[str, dict[str, frozenset[str]]] = {
    TraceView.CANDIDATE.value: {
        TraceEventType.SESSION_STARTED.value: frozenset({"session_started"}),
        TraceEventType.RUNTIME_EPOCH_ADVANCED.value: frozenset(),
        # Preparation/materialization are pre-playback internal lifecycle
        # events.  The candidate only receives the question after the spoken
        # commit, never the text that was staged before playback succeeded.
        TraceEventType.QUESTION_PREPARED.value: frozenset(),
        TraceEventType.QUESTION_DELIVERY_STARTED.value: frozenset({"delivery_attempt_id"}),
        TraceEventType.PLAYBACK_ACKNOWLEDGED.value: frozenset({"delivery_attempt_id", "acknowledged"}),
        TraceEventType.DELIVERY_FAILED.value: frozenset({"delivery_attempt_id", "delivery_failed"}),
        TraceEventType.SPOKEN_QUESTION_COMMITTED.value: frozenset({"question_id", "question_text"}),
        TraceEventType.ANSWER_RECEIVED.value: frozenset({"answer_received", "answer_version"}),
        TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value: frozenset(),
        TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value: frozenset(),
        TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value: frozenset(),
        TraceEventType.ACTION_GRANT_SELECTED.value: frozenset(),
        TraceEventType.QUESTION_MATERIALIZED.value: frozenset(),
        TraceEventType.STATE_TRANSITION_VALIDATED.value: frozenset(),
        TraceEventType.EVIDENCE_STATE_UPDATED.value: frozenset(),
        TraceEventType.REPORT_CLAIM_EMITTED.value: frozenset({"claim_id", "claim_text"}),
        TraceEventType.FINAL_EVALUATION_COMPLETED.value: frozenset(),
    },
    TraceView.ACTOR.value: {
        TraceEventType.SESSION_STARTED.value: frozenset({"session_started"}),
        TraceEventType.RUNTIME_EPOCH_ADVANCED.value: frozenset(),
        TraceEventType.QUESTION_PREPARED.value: frozenset(),
        TraceEventType.QUESTION_DELIVERY_STARTED.value: frozenset({"delivery_attempt_id"}),
        TraceEventType.PLAYBACK_ACKNOWLEDGED.value: frozenset({"delivery_attempt_id", "acknowledged"}),
        TraceEventType.DELIVERY_FAILED.value: frozenset({"delivery_attempt_id", "delivery_failed", "retryable"}),
        TraceEventType.SPOKEN_QUESTION_COMMITTED.value: frozenset({"question_id", "question_text", "delivery_attempt_id"}),
        TraceEventType.ANSWER_RECEIVED.value: frozenset({"answer_received", "answer_version"}),
        TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value: frozenset(),
        TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value: frozenset(),
        TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value: frozenset(),
        TraceEventType.ACTION_GRANT_SELECTED.value: frozenset(),
        TraceEventType.QUESTION_MATERIALIZED.value: frozenset(),
        TraceEventType.STATE_TRANSITION_VALIDATED.value: frozenset(),
        TraceEventType.EVIDENCE_STATE_UPDATED.value: frozenset(),
        TraceEventType.REPORT_CLAIM_EMITTED.value: frozenset(),
        TraceEventType.FINAL_EVALUATION_COMPLETED.value: frozenset(),
    },
    TraceView.INTERVIEWER.value: {
        TraceEventType.SESSION_STARTED.value: frozenset({"session_started"}),
        TraceEventType.RUNTIME_EPOCH_ADVANCED.value: frozenset({"runtime_epoch"}),
        TraceEventType.QUESTION_PREPARED.value: frozenset({"question_id"}),
        TraceEventType.QUESTION_DELIVERY_STARTED.value: frozenset({"delivery_attempt_id"}),
        TraceEventType.PLAYBACK_ACKNOWLEDGED.value: frozenset({"delivery_attempt_id", "acknowledged"}),
        TraceEventType.DELIVERY_FAILED.value: frozenset({"delivery_attempt_id", "delivery_failed"}),
        TraceEventType.SPOKEN_QUESTION_COMMITTED.value: frozenset({"question_id", "question_text"}),
        TraceEventType.ANSWER_RECEIVED.value: frozenset({"spoken_question_event_id"}),
        TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value: frozenset({"semantic_status"}),
        TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value: frozenset({"semantic_status"}),
        TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value: frozenset({"admitted_opportunity_ids"}),
        TraceEventType.ACTION_GRANT_SELECTED.value: frozenset({"action", "opportunity_id"}),
        TraceEventType.QUESTION_MATERIALIZED.value: frozenset({"question_id", "question_text", "route_kind"}),
        TraceEventType.STATE_TRANSITION_VALIDATED.value: frozenset({"validation_status", "visible_route_commit_allowed"}),
        TraceEventType.EVIDENCE_STATE_UPDATED.value: frozenset({"evidence_state_hash"}),
        TraceEventType.REPORT_CLAIM_EMITTED.value: frozenset({"claim_id", "audience"}),
        TraceEventType.FINAL_EVALUATION_COMPLETED.value: frozenset({"evaluation_id", "status"}),
    },
    TraceView.EVALUATOR.value: {
        TraceEventType.SESSION_STARTED.value: frozenset({"session_started"}),
        TraceEventType.RUNTIME_EPOCH_ADVANCED.value: frozenset({"previous_runtime_epoch", "runtime_epoch"}),
        TraceEventType.QUESTION_PREPARED.value: frozenset({"question_id", "materialized_event_id", "source_opportunity_id", "source_evidence_event_ids", "prior_spoken_question_event_id"}),
        TraceEventType.QUESTION_DELIVERY_STARTED.value: frozenset({"delivery_attempt_id", "question_prepared_event_id"}),
        TraceEventType.PLAYBACK_ACKNOWLEDGED.value: frozenset({"delivery_attempt_id", "acknowledged", "client_ack"}),
        TraceEventType.DELIVERY_FAILED.value: frozenset({"delivery_attempt_id", "delivery_failed", "retryable"}),
        TraceEventType.SPOKEN_QUESTION_COMMITTED.value: frozenset({"question_id", "question_text", "question_materialized_event_id", "playback_ack_event_id", "delivery_attempt_id", "source_opportunity_id", "source_evidence_event_ids", "prior_spoken_question_event_id"}),
        TraceEventType.ANSWER_RECEIVED.value: frozenset({"spoken_question_event_id", "answer_text_hash", "answer_text"}),
        TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value: frozenset({"answer_event_id", "interpretation", "decision_immutable"}),
        TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value: frozenset({"answer_event_id", "shadow_of_event_id", "interpretation", "disagreement", "does_not_overwrite_final"}),
        TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value: frozenset({"semantic_event_id", "admitted_candidates", "excluded_candidates"}),
        TraceEventType.ACTION_GRANT_SELECTED.value: frozenset({"action", "opportunity_id", "opportunity_inventory_event_id", "source_evidence_event_ids", "prior_spoken_question_event_id"}),
        TraceEventType.QUESTION_MATERIALIZED.value: frozenset({"question_id", "question_text", "source_opportunity_id", "source_evidence_event_ids", "prior_spoken_question_event_id", "action_grant_event_id", "route_kind"}),
        TraceEventType.STATE_TRANSITION_VALIDATED.value: frozenset({"validation_status", "visible_route_commit_allowed", "source_opportunity_id", "source_evidence_event_ids", "prior_spoken_question_event_id", "action_grant_event_id", "reason", "candidate_event_type", "attempted_answer_version", "attempted_runtime_epoch", "current_answer_version", "current_runtime_epoch"}),
        TraceEventType.EVIDENCE_STATE_UPDATED.value: frozenset({"semantic_event_id", "opportunity_inventory_event_id", "source_event_ids", "evidence_state"}),
        TraceEventType.REPORT_CLAIM_EMITTED.value: frozenset({"claim_id", "claim_text", "audience", "source_evidence_event_ids"}),
        TraceEventType.FINAL_EVALUATION_COMPLETED.value: frozenset({"evaluation_id", "report_claim_event_ids", "evidence_event_ids", "evaluation_summary"}),
    },
    TraceView.OPERATOR.value: {
        TraceEventType.SESSION_STARTED.value: frozenset({"session_started", "runtime_epoch"}),
        TraceEventType.RUNTIME_EPOCH_ADVANCED.value: frozenset({"previous_runtime_epoch", "runtime_epoch"}),
        TraceEventType.QUESTION_PREPARED.value: frozenset({"question_id", "materialized_event_id"}),
        TraceEventType.QUESTION_DELIVERY_STARTED.value: frozenset({"delivery_attempt_id", "provider"}),
        TraceEventType.PLAYBACK_ACKNOWLEDGED.value: frozenset({"delivery_attempt_id", "client_ack"}),
        TraceEventType.DELIVERY_FAILED.value: frozenset({"delivery_attempt_id", "delivery_failed", "retryable", "reason"}),
        TraceEventType.SPOKEN_QUESTION_COMMITTED.value: frozenset({"question_id", "delivery_attempt_id", "playback_ack_event_id"}),
        TraceEventType.ANSWER_RECEIVED.value: frozenset({"spoken_question_event_id", "answer_chars"}),
        TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value: frozenset({"semantic_status", "answer_event_id"}),
        TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value: frozenset({"semantic_status"}),
        TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value: frozenset({"inventory_status", "admitted_count", "excluded_count"}),
        TraceEventType.ACTION_GRANT_SELECTED.value: frozenset({"action", "opportunity_id"}),
        TraceEventType.QUESTION_MATERIALIZED.value: frozenset({"question_id", "route_kind"}),
        TraceEventType.STATE_TRANSITION_VALIDATED.value: frozenset({"validation_status", "visible_route_commit_allowed", "reason"}),
        TraceEventType.EVIDENCE_STATE_UPDATED.value: frozenset({"evidence_state_hash", "source_event_count"}),
        TraceEventType.REPORT_CLAIM_EMITTED.value: frozenset({"claim_id", "audience"}),
        TraceEventType.FINAL_EVALUATION_COMPLETED.value: frozenset({"evaluation_id", "status"}),
    },
}


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "to_record"):
        return value.to_record()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _dedupe_ids(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _canonical_redacted_paths(paths: Iterable[str]) -> list[str]:
    """Make redaction metadata independent of object insertion order."""

    return sorted({str(path) for path in paths})


def _redact_value(value: Any, path: str, redacted_paths: list[str]) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            if _is_sensitive_key(key):
                result[key] = REDACTED
                redacted_paths.append(child_path)
                continue
            result[key] = _redact_value(raw_value, child_path, redacted_paths)
        return result
    if isinstance(value, (list, tuple)):
        return [
            _redact_value(item, f"{path}[{index}]", redacted_paths)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        # A pre-sanitized marker is canonical redacted data.  Recording it
        # here makes creation and verified import use the same path contract.
        if value == REDACTED or _SECRET_VALUE_RE.search(value):
            redacted_paths.append(path or "value")
            return REDACTED
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_views(
    views: Mapping[str | TraceView, Mapping[str, Any] | None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload_views: dict[str, Any] = {}
    redacted_paths: list[str] = []
    for raw_view, raw_payload in views.items():
        view = raw_view.value if isinstance(raw_view, TraceView) else str(raw_view)
        if view not in _VIEW_NAMES:
            raise TraceInvariantError(f"Unknown trace projection view: {view}")
        if raw_payload is None:
            continue
        if not isinstance(raw_payload, Mapping):
            raise TraceInvariantError(f"Payload for view '{view}' must be an object")
        payload_views[view] = _redact_value(dict(raw_payload), f"views.{view}", redacted_paths)
    payload = {"views": payload_views}
    redaction = {
        "policy": TRACE_SCHEMA_VERSION,
        "raw_provider_payload_excluded": True,
        "raw_secrets_excluded": True,
        "exact_text_authorized_views": sorted(
            view
            for view, payload_view in payload_views.items()
            if any(
                key in payload_view
                for key in ("question_text", "visible_text", "answer_text", "claim_text")
            )
        ),
        "redacted_paths": _canonical_redacted_paths(redacted_paths),
    }
    return payload, redaction


def _redaction_metadata_for_sanitized_views(
    views: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive redaction metadata from an already-sanitized payload.

    Verified import cannot rediscover the original bytes that triggered a
    value-pattern redaction.  The sanitized marker is therefore the canonical
    evidence: every marker leaf must be listed, every sensitive-key child must
    be a marker and listed, and no raw value-pattern secret may remain.
    """

    redacted_paths: list[str] = []
    payload_views: dict[str, Any] = {}

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for raw_key, raw_value in value.items():
                key = str(raw_key)
                child_path = f"{path}.{key}"
                if _is_sensitive_key(key):
                    if raw_value != REDACTED:
                        raise TraceInvariantError(
                            f"sensitive key {child_path} is not canonically redacted"
                        )
                    redacted_paths.append(child_path)
                    continue
                walk(raw_value, child_path)
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if isinstance(value, str):
            if value == REDACTED:
                redacted_paths.append(path or "value")
                return
            if _SECRET_VALUE_RE.search(value):
                raise TraceInvariantError(f"raw secret value remains at {path}")

    for raw_view, raw_payload in views.items():
        view = raw_view.value if isinstance(raw_view, TraceView) else str(raw_view)
        if view not in _VIEW_NAMES:
            raise TraceInvariantError(f"Unknown trace projection view: {view}")
        if not isinstance(raw_payload, Mapping):
            raise TraceInvariantError(f"Payload for view '{view}' must be an object")
        payload_view = dict(raw_payload)
        payload_views[view] = payload_view
        walk(payload_view, f"views.{view}")

    return {
        "policy": TRACE_SCHEMA_VERSION,
        "raw_provider_payload_excluded": True,
        "raw_secrets_excluded": True,
        "exact_text_authorized_views": sorted(
            view
            for view, payload_view in payload_views.items()
            if any(
                key in payload_view
                for key in ("question_text", "visible_text", "answer_text", "claim_text")
            )
        ),
        "redacted_paths": _canonical_redacted_paths(redacted_paths),
    }


def _view(event: TraceEvent, view: TraceView | str) -> dict[str, Any]:
    name = view.value if isinstance(view, TraceView) else str(view)
    if name not in _VIEW_NAMES:
        raise TraceInvariantError(f"Unknown trace projection view: {name}")
    views = event.payload.get("views") if isinstance(event.payload, Mapping) else {}
    if not isinstance(views, Mapping):
        return {}
    value = views.get(name)
    return _thaw_value(value) if isinstance(value, Mapping) else {}


def _project_view_payload(event: TraceEvent, view_name: str) -> dict[str, Any]:
    """Apply the explicit per-view/per-event projection allowlist."""
    try:
        allowed = _PROJECTION_ALLOWLISTS[view_name][event.event_type]
    except KeyError as exc:
        raise TraceInvariantError(
            f"Projection allowlist is incomplete for view={view_name} event={event.event_type}"
        ) from exc
    raw = _view(event, view_name)
    return {key: raw[key] for key in sorted(allowed) if key in raw}


def _atomic_public(method: Callable[..., Any]) -> Callable[..., Any]:
    """Make a public mutation all-or-nothing, including late append failures."""

    @functools.wraps(method)
    def wrapped(self: "InterviewTraceV1", *args: Any, **kwargs: Any) -> Any:
        self._ensure_authoritative()
        snapshot = self._snapshot_mutable_state()
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self._restore_mutable_state(snapshot)
            raise

    return wrapped


class InterviewTraceV1:
    """Append-only causal interview trace with invariant-enforcing helpers."""

    def __init__(
        self,
        session_id: str,
        *,
        runtime_epoch: int = 0,
        clock: Callable[[], int] | None = None,
        auto_start: bool = True,
    ) -> None:
        self.session_id = str(session_id or "").strip()
        if not self.session_id:
            raise TraceInvariantError("session_id is required")
        if runtime_epoch < 0:
            raise TraceInvariantError("runtime_epoch cannot be negative")
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._events: list[TraceEvent] = []
        self._events_by_id: dict[str, TraceEvent] = {}
        self._events_by_idempotency: dict[str, TraceEvent] = {}
        self._turns: dict[str, _TurnLedger] = {}
        self._runtime_epoch = int(runtime_epoch)
        self._session_started_event_id = ""
        self._last_spoken_question_event_id = ""
        self._final_evaluation_event_id = ""
        # A newly constructed trace is authoritative because all canonical
        # events originate from this instance.  Imports explicitly taint the
        # instance until a complete integrity verification succeeds.
        self._authoritative = True
        self._integrity_verified = True
        if auto_start:
            self.start_session()

    @property
    def runtime_epoch(self) -> int:
        return self._runtime_epoch

    @property
    def is_authoritative(self) -> bool:
        """Whether canonical mutations/projections are currently permitted."""
        return self._authoritative

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    @property
    def last_spoken_question_event_id(self) -> str:
        return self._last_spoken_question_event_id

    def _ensure_authoritative(self) -> None:
        if not self._authoritative:
            raise TraceIntegrityError(
                "Trace loaded with verify=False is tainted/read-only; "
                "successful verify_integrity() is required before canonical operations"
            )

    def _snapshot_mutable_state(self) -> tuple[Any, ...]:
        """Capture every canonical/index field that a public operation can touch."""
        return (
            list(self._events),
            dict(self._events_by_id),
            dict(self._events_by_idempotency),
            copy.deepcopy(self._turns),
            self._runtime_epoch,
            self._session_started_event_id,
            self._last_spoken_question_event_id,
            self._final_evaluation_event_id,
        )

    def _restore_mutable_state(self, snapshot: tuple[Any, ...]) -> None:
        (
            events,
            events_by_id,
            events_by_idempotency,
            turns,
            runtime_epoch,
            session_started_event_id,
            last_spoken_question_event_id,
            final_evaluation_event_id,
        ) = snapshot
        self._events = list(events)
        self._events_by_id = dict(events_by_id)
        self._events_by_idempotency = dict(events_by_idempotency)
        self._turns = copy.deepcopy(turns)
        self._runtime_epoch = runtime_epoch
        self._session_started_event_id = session_started_event_id
        self._last_spoken_question_event_id = last_spoken_question_event_id
        self._final_evaluation_event_id = final_evaluation_event_id

    @classmethod
    def from_records(
        cls,
        records: Sequence[Mapping[str, Any]],
        *,
        verify: bool = True,
        clock: Callable[[], int] | None = None,
    ) -> "InterviewTraceV1":
        """Load an exported trace.

        ``verify=False`` is intentionally available only for audit tools that
        need to load a suspect artifact and then report why verification fails.
        It must not be used as a production ingestion shortcut.
        """
        if not records:
            raise TraceIntegrityError("Cannot load an empty trace")
        parsed = [TraceEvent.from_record(record) for record in records]
        event_ids: set[str] = set()
        idempotency_keys: set[str] = set()
        for event in parsed:
            if event.event_id in event_ids:
                raise TraceIntegrityError(f"Duplicate event id: {event.event_id}")
            if event.idempotency_key in idempotency_keys:
                raise TraceIntegrityError(f"Duplicate idempotency key: {event.idempotency_key}")
            event_ids.add(event.event_id)
            idempotency_keys.add(event.idempotency_key)
        trace = cls(parsed[0].session_id, auto_start=False, clock=clock)
        trace._authoritative = False
        trace._integrity_verified = False
        trace._events = parsed
        trace._events_by_id = {event.event_id: event for event in parsed}
        trace._events_by_idempotency = {event.idempotency_key: event for event in parsed}
        # Seed the derived epoch index from the durable tail only so
        # verify_integrity can compare it to the independently replayed
        # canonical epoch before _rebuild_indexes runs.  The tail value is not
        # trusted by itself: every epoch transition is validated below.
        trace._runtime_epoch = parsed[-1].runtime_epoch
        if verify:
            trace.verify_integrity()
        trace._rebuild_indexes()
        return trace

    def export_records(self) -> list[dict[str, Any]]:
        return [event.to_record() for event in self._events]

    def _now(self) -> int:
        value = int(self._clock())
        if value < 0:
            raise TraceInvariantError("clock returned a negative timestamp")
        return value

    def _event_fingerprint(self, event: TraceEvent) -> str:
        return self._operation_fingerprint(
            session_id=event.session_id,
            turn_id=event.turn_id,
            answer_version=event.answer_version,
            runtime_epoch=event.runtime_epoch,
            event_type=event.event_type,
            causal_parent_ids=event.causal_parent_ids,
            producer=event.producer,
            payload=event.payload,
            decision_hash=event.decision_hash,
            provenance_hash=event.provenance_hash,
            idempotency_key=event.idempotency_key,
        )

    @staticmethod
    def _operation_fingerprint(
        *,
        session_id: str,
        turn_id: str,
        answer_version: int,
        runtime_epoch: int,
        event_type: str,
        causal_parent_ids: Iterable[str],
        producer: str,
        payload: Mapping[str, Any],
        decision_hash: str,
        provenance_hash: str,
        idempotency_key: str,
    ) -> str:
        return _canonical(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "answer_version": answer_version,
                "runtime_epoch": runtime_epoch,
                "event_type": event_type,
                "causal_parent_ids": tuple(causal_parent_ids),
                "producer": producer,
                "payload": payload,
                "decision_hash": decision_hash,
                "provenance_hash": provenance_hash,
                "idempotency_key": idempotency_key,
            }
        )

    @staticmethod
    def _decision_hash(event_name: str, payload: Mapping[str, Any]) -> str:
        return _sha256(
            {
                "event_type": event_name,
                "decision": _view_payload_for_hash(payload, TraceView.EVALUATOR),
            }
        )

    @staticmethod
    def _provenance_hash(parents: Sequence[str], payload: Mapping[str, Any]) -> str:
        return _sha256(
            {
                "causal_parent_ids": tuple(parents),
                "provenance": _source_refs(payload),
            }
        )

    def _append_raw(
        self,
        event_type: TraceEventType | str,
        *,
        turn_id: str = "",
        answer_version: int = 0,
        runtime_epoch: int | None = None,
        causal_parent_ids: Iterable[str] = (),
        producer: str,
        views: Mapping[str | TraceView, Mapping[str, Any] | None],
        idempotency_key: str,
        event_id: str | None = None,
        occurred_at_ms: int | None = None,
        decision_material: Any = None,
        provenance_material: Any = None,
        logical_existing_event_id: str = "",
    ) -> TraceReceipt:
        self._ensure_authoritative()
        event_name = event_type.value if isinstance(event_type, TraceEventType) else str(event_type)
        if event_name not in {item.value for item in TraceEventType}:
            raise TraceInvariantError(f"Unknown event type: {event_name}")
        if answer_version < 0:
            raise TraceInvariantError("answer_version cannot be negative")
        record_epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        if record_epoch < 0:
            raise TraceInvariantError("runtime_epoch cannot be negative")
        event_id_value = str(event_id or uuid.uuid4())
        idempotency = str(idempotency_key or "").strip()
        if not idempotency:
            raise TraceInvariantError("idempotency_key is required")
        raw_parents = tuple(str(value or "").strip() for value in causal_parent_ids)
        if any(not parent_id for parent_id in raw_parents):
            raise TraceInvariantError("causal_parent_ids cannot contain empty ids")
        if len(raw_parents) != len(set(raw_parents)):
            raise TraceInvariantError("causal_parent_ids must not contain duplicates")
        parents = raw_parents
        for parent_id in parents:
            if parent_id not in self._events_by_id:
                raise TraceReferenceError(f"Unknown causal parent event: {parent_id}")
        payload, redaction = _safe_views(views)
        # Hashes are deliberately recomputable from the durable event record.
        # The legacy material arguments remain accepted for call-site clarity,
        # but are not an unverifiable second source of truth.
        del decision_material, provenance_material
        decision_hash = self._decision_hash(event_name, payload)
        provenance_hash = self._provenance_hash(parents, payload)

        logical_existing = self._events_by_id.get(str(logical_existing_event_id or ""))
        if logical_existing is not None:
            candidate_fingerprint = self._operation_fingerprint(
                session_id=self.session_id,
                turn_id=str(turn_id or ""),
                answer_version=int(answer_version),
                runtime_epoch=record_epoch,
                event_type=event_name,
                causal_parent_ids=parents,
                producer=str(producer),
                payload=payload,
                decision_hash=decision_hash,
                provenance_hash=provenance_hash,
                idempotency_key=idempotency,
            )
            if (
                logical_existing.event_type != event_name
                or logical_existing.idempotency_key != idempotency
                or candidate_fingerprint != self._event_fingerprint(logical_existing)
            ):
                raise TraceConflictError(
                    f"Logical {event_name} already exists with a different operation fingerprint"
                )
            return TraceReceipt(accepted=True, event=logical_existing, idempotent=True)

        existing_by_key = self._events_by_idempotency.get(idempotency)
        if existing_by_key is not None:
            candidate = self._event_fingerprint(
                TraceEvent(
                    schema_version=TRACE_SCHEMA_VERSION,
                    event_id=event_id_value,
                    session_id=self.session_id,
                    turn_id=str(turn_id or ""),
                    answer_version=int(answer_version),
                    runtime_epoch=record_epoch,
                    sequence=existing_by_key.sequence,
                    event_type=event_name,
                    causal_parent_ids=parents,
                    occurred_at_ms=existing_by_key.occurred_at_ms,
                    recorded_at_ms=existing_by_key.recorded_at_ms,
                    producer=str(producer),
                    payload_schema_version=PAYLOAD_SCHEMA_VERSION,
                    payload=payload,
                    decision_hash=decision_hash,
                    provenance_hash=provenance_hash,
                    redaction=redaction,
                    idempotency_key=idempotency,
                    previous_event_hash=existing_by_key.previous_event_hash,
                    event_hash=existing_by_key.event_hash,
                )
            )
            if candidate != self._event_fingerprint(existing_by_key):
                raise TraceConflictError(f"Idempotency key reused with different content: {idempotency}")
            return TraceReceipt(accepted=True, event=existing_by_key, idempotent=True)

        existing_by_id = self._events_by_id.get(event_id_value)
        if existing_by_id is not None:
            candidate = self._event_fingerprint(
                TraceEvent(
                    schema_version=TRACE_SCHEMA_VERSION,
                    event_id=event_id_value,
                    session_id=self.session_id,
                    turn_id=str(turn_id or ""),
                    answer_version=int(answer_version),
                    runtime_epoch=record_epoch,
                    sequence=existing_by_id.sequence,
                    event_type=event_name,
                    causal_parent_ids=parents,
                    occurred_at_ms=existing_by_id.occurred_at_ms,
                    recorded_at_ms=existing_by_id.recorded_at_ms,
                    producer=str(producer),
                    payload_schema_version=PAYLOAD_SCHEMA_VERSION,
                    payload=payload,
                    decision_hash=decision_hash,
                    provenance_hash=provenance_hash,
                    redaction=redaction,
                    idempotency_key=idempotency,
                    previous_event_hash=existing_by_id.previous_event_hash,
                    event_hash=existing_by_id.event_hash,
                )
            )
            if candidate != self._event_fingerprint(existing_by_id):
                raise TraceConflictError(f"Event id reused with different content: {event_id_value}")
            return TraceReceipt(accepted=True, event=existing_by_id, idempotent=True)

        sequence = len(self._events) + 1
        previous_hash = self._events[-1].event_hash if self._events else GENESIS_HASH
        occurred = self._now() if occurred_at_ms is None else int(occurred_at_ms)
        recorded = self._now()
        event_body = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "event_id": event_id_value,
            "session_id": self.session_id,
            "turn_id": str(turn_id or ""),
            "answer_version": int(answer_version),
            "runtime_epoch": record_epoch,
            "sequence": sequence,
            "event_type": event_name,
            "causal_parent_ids": list(parents),
            "occurred_at_ms": occurred,
            "recorded_at_ms": recorded,
            "producer": str(producer or "unknown"),
            "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
            "payload": payload,
            "decision_hash": decision_hash,
            "provenance_hash": provenance_hash,
            "redaction": redaction,
            "idempotency_key": idempotency,
            "previous_event_hash": previous_hash,
        }
        event_hash = hashlib.sha256(_canonical(event_body).encode("utf-8")).hexdigest()
        event = TraceEvent(event_hash=event_hash, **event_body)
        self._events.append(event)
        self._events_by_id[event.event_id] = event
        self._events_by_idempotency[event.idempotency_key] = event
        return TraceReceipt(accepted=True, event=event)

    def _event(self, event_id: str) -> TraceEvent:
        try:
            return self._events_by_id[str(event_id)]
        except KeyError as exc:
            raise TraceReferenceError(f"Unknown event reference: {event_id}") from exc

    def _event_type(self, event_id: str) -> str:
        return self._event(event_id).event_type

    def _turn(self, turn_id: str) -> _TurnLedger:
        try:
            return self._turns[str(turn_id)]
        except KeyError as exc:
            raise TraceReferenceError(f"Unknown turn: {turn_id}") from exc

    def _turn_for_new_or_existing(
        self,
        *,
        turn_id: str,
        answer_version: int,
        runtime_epoch: int,
        attempted_event_type: str,
        idempotency_key: str,
        causal_parent_ids: Iterable[str],
        allow_new: bool = True,
    ) -> tuple[_TurnLedger | None, TraceReceipt | None]:
        turn_key = str(turn_id or "").strip()
        if not turn_key:
            raise TraceInvariantError(f"turn_id is required for {attempted_event_type}")
        if runtime_epoch != self._runtime_epoch:
            return None, self._reject_stale(
                attempted_event_type=attempted_event_type,
                turn_id=turn_key,
                answer_version=answer_version,
                runtime_epoch=runtime_epoch,
                idempotency_key=idempotency_key,
                causal_parent_ids=causal_parent_ids,
                reason="stale_runtime_epoch",
            )
        ledger = self._turns.get(turn_key)
        if ledger is None:
            if not allow_new or answer_version < 1:
                raise TraceInvariantError(f"Cannot create turn for {attempted_event_type}")
            if answer_version != 1:
                return None, self._reject_stale(
                    attempted_event_type=attempted_event_type,
                    turn_id=turn_key,
                    answer_version=answer_version,
                    runtime_epoch=runtime_epoch,
                    idempotency_key=idempotency_key,
                    causal_parent_ids=causal_parent_ids,
                    reason="answer_version_gap",
                )
            ledger = _TurnLedger(runtime_epoch=runtime_epoch, current_answer_version=answer_version)
            self._turns[turn_key] = ledger
            return ledger, None
        if runtime_epoch != ledger.runtime_epoch:
            return None, self._reject_stale(
                attempted_event_type=attempted_event_type,
                turn_id=turn_key,
                answer_version=answer_version,
                runtime_epoch=runtime_epoch,
                idempotency_key=idempotency_key,
                causal_parent_ids=causal_parent_ids,
                reason="stale_turn_runtime_epoch",
            )
        if answer_version < ledger.current_answer_version:
            return None, self._reject_stale(
                attempted_event_type=attempted_event_type,
                turn_id=turn_key,
                answer_version=answer_version,
                runtime_epoch=runtime_epoch,
                idempotency_key=idempotency_key,
                causal_parent_ids=causal_parent_ids,
                reason="stale_answer_version",
            )
        if answer_version > ledger.current_answer_version + 1:
            return None, self._reject_stale(
                attempted_event_type=attempted_event_type,
                turn_id=turn_key,
                answer_version=answer_version,
                runtime_epoch=runtime_epoch,
                idempotency_key=idempotency_key,
                causal_parent_ids=causal_parent_ids,
                reason="answer_version_gap",
            )
        if answer_version > ledger.current_answer_version:
            ledger.current_answer_version = answer_version
        return ledger, None

    def _reject_stale(
        self,
        *,
        attempted_event_type: str,
        turn_id: str,
        answer_version: int,
        runtime_epoch: int,
        idempotency_key: str,
        causal_parent_ids: Iterable[str],
        reason: str,
    ) -> TraceReceipt:
        current = self._turns.get(turn_id)
        current_version = current.current_answer_version if current else 0
        parents = [parent for parent in causal_parent_ids if parent in self._events_by_id]
        rejection_key = f"rejection:{idempotency_key or attempted_event_type}:{turn_id}:{answer_version}:{runtime_epoch}"
        existing = self._events_by_idempotency.get(rejection_key)
        if existing is not None:
            existing_view = _view(existing, TraceView.EVALUATOR)
            expected_view = {
                "validation_status": "rejected",
                "candidate_event_type": attempted_event_type,
                "reason": reason,
                "attempted_answer_version": answer_version,
                "attempted_runtime_epoch": runtime_epoch,
                "current_answer_version": current_version,
                "current_runtime_epoch": self._runtime_epoch,
            }
            if (
                existing.event_type != TraceEventType.STATE_TRANSITION_VALIDATED.value
                or existing_view != expected_view
            ):
                raise TraceConflictError("Rejection idempotency key reused with different content")
            return TraceReceipt(accepted=False, event=existing, idempotent=True, reason=reason)
        appended = self._append_raw(
            TraceEventType.STATE_TRANSITION_VALIDATED,
            turn_id=turn_id,
            answer_version=current_version,
            runtime_epoch=self._runtime_epoch,
            causal_parent_ids=parents,
            producer="trace.validation",
            idempotency_key=rejection_key,
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {
                    "validation_status": "rejected",
                    "visible_route_commit_allowed": False,
                },
                TraceView.EVALUATOR: {
                    "validation_status": "rejected",
                    "candidate_event_type": attempted_event_type,
                    "reason": reason,
                    "attempted_answer_version": answer_version,
                    "attempted_runtime_epoch": runtime_epoch,
                    "current_answer_version": current_version,
                    "current_runtime_epoch": self._runtime_epoch,
                },
                TraceView.OPERATOR: {
                    "validation_status": "rejected",
                    "candidate_event_type": attempted_event_type,
                    "reason": reason,
                    "attempted_answer_version": answer_version,
                    "attempted_runtime_epoch": runtime_epoch,
                },
            },
            decision_material={"validation_status": "rejected", "reason": reason},
            provenance_material={"attempted_event_type": attempted_event_type, "causal_parent_ids": parents},
        )
        return TraceReceipt(accepted=False, event=appended.event, reason=reason)

    def _require_event_type(self, event_id: str, expected: TraceEventType | str) -> TraceEvent:
        event = self._event(event_id)
        expected_name = expected.value if isinstance(expected, TraceEventType) else str(expected)
        if event.event_type != expected_name:
            raise TraceReferenceError(f"Event {event_id} is {event.event_type}, expected {expected_name}")
        return event

    def _require_sources(self, event_ids: Sequence[str], *, label: str) -> tuple[str, ...]:
        raw_refs = tuple(str(event_id or "").strip() for event_id in event_ids)
        if any(not ref for ref in raw_refs):
            raise TraceReferenceError(f"{label} cannot contain empty event ids")
        if len(raw_refs) != len(set(raw_refs)):
            raise TraceInvariantError(f"{label} cannot contain duplicate event ids")
        refs = raw_refs
        if not refs:
            raise TraceReferenceError(f"{label} must contain at least one event id")
        for event_id in refs:
            self._event(event_id)
        return refs

    def _require_sources_of_type(
        self,
        event_ids: Sequence[str],
        *,
        expected: TraceEventType,
        label: str,
    ) -> tuple[str, ...]:
        refs = self._require_sources(event_ids, label=label)
        for event_id in refs:
            self._require_event_type(event_id, expected)
        return refs

    def _require_opportunity_evidence_sources(
        self,
        event_ids: Sequence[str],
        *,
        label: str,
        known_events: Mapping[str, TraceEvent] | None = None,
    ) -> tuple[str, ...]:
        """Require canonical, prior, decision-bearing opportunity evidence."""
        if isinstance(event_ids, (str, bytes)) or not isinstance(event_ids, Sequence):
            raise TraceReferenceError(f"{label} must be an array of event ids")
        if any(not isinstance(event_id, str) for event_id in event_ids):
            raise TraceReferenceError(f"{label} must contain string event ids")
        refs = tuple(event_id.strip() for event_id in event_ids)
        if any(not ref for ref in refs) or len(refs) != len(set(refs)):
            raise TraceReferenceError(f"{label} contains empty/duplicate event ids")
        if not refs:
            raise TraceReferenceError(f"{label} must contain at least one event id")
        for event_id in refs:
            if known_events is None:
                referenced = self._event(event_id)
            else:
                try:
                    referenced = known_events[event_id]
                except KeyError as exc:
                    raise TraceReferenceError(
                        f"{label} cites an unknown or future event: {event_id}"
                    ) from exc
            if referenced.event_type not in _OPPORTUNITY_EVIDENCE_EVENT_TYPES:
                raise TraceReferenceError(
                    f"{label} cites non-evidence event type {referenced.event_type}: {event_id}"
                )
        return refs

    def _find_logical_event(self, event_type: TraceEventType, field_name: str, value: str) -> str:
        needle = str(value or "")
        if not needle:
            return ""
        for event in self._events:
            if event.event_type != event_type.value:
                continue
            evaluator = _view(event, TraceView.EVALUATOR)
            if str(evaluator.get(field_name) or "") == needle:
                return event.event_id
        return ""

    def _require_current_epoch(self, epoch: int) -> None:
        if int(epoch) != self._runtime_epoch:
            raise TraceStaleError(
                f"Operation runtime_epoch={epoch} does not match current runtime_epoch={self._runtime_epoch}"
            )

    def _require_immediate_prior_spoken_question(
        self,
        prior_spoken_question_event_id: str,
        *,
        label: str,
    ) -> str:
        """Require the one spoken question immediately preceding this route."""
        supplied = str(prior_spoken_question_event_id or "").strip()
        expected = self._last_spoken_question_event_id
        if supplied != expected:
            raise TraceInvariantError(
                f"{label} must reference the immediately prior spoken question"
            )
        if supplied:
            self._require_event_type(supplied, TraceEventType.SPOKEN_QUESTION_COMMITTED)
        return supplied

    @_atomic_public
    def start_session(self, *, producer: str = "backend.session", idempotency_key: str = "session-start") -> TraceReceipt:
        existing_session_id = self._session_started_event_id
        existing_session = self._event(existing_session_id) if existing_session_id else None
        session_epoch = existing_session.runtime_epoch if existing_session is not None else self._runtime_epoch
        receipt = self._append_raw(
            TraceEventType.SESSION_STARTED,
            runtime_epoch=session_epoch,
            producer=producer,
            idempotency_key=idempotency_key,
            views={
                TraceView.CANDIDATE: {"session_started": True},
                TraceView.ACTOR: {"session_started": True},
                TraceView.INTERVIEWER: {"session_started": True},
                TraceView.EVALUATOR: {"session_started": True},
                TraceView.OPERATOR: {"session_started": True, "runtime_epoch": session_epoch},
            },
            decision_material={"session_started": True},
            provenance_material={"session_id": self.session_id},
            logical_existing_event_id=existing_session_id,
        )
        self._session_started_event_id = receipt.event.event_id
        return receipt

    @_atomic_public
    def advance_runtime_epoch(self, new_runtime_epoch: int, *, producer: str = "backend.runtime") -> TraceReceipt:
        next_epoch = int(new_runtime_epoch)
        epoch_key = f"runtime-epoch:{next_epoch}"
        if next_epoch == self._runtime_epoch:
            existing = self._events_by_idempotency.get(epoch_key)
            if existing is not None and existing.event_type == TraceEventType.RUNTIME_EPOCH_ADVANCED.value:
                if existing.producer != producer:
                    raise TraceConflictError("Runtime epoch idempotency key reused with a different producer")
                return TraceReceipt(accepted=True, event=existing, idempotent=True)
        if next_epoch <= self._runtime_epoch:
            raise TraceInvariantError("runtime_epoch must advance monotonically")
        previous_epoch = self._runtime_epoch
        receipt = self._append_raw(
            TraceEventType.RUNTIME_EPOCH_ADVANCED,
            runtime_epoch=next_epoch,
            producer=producer,
            idempotency_key=epoch_key,
            causal_parent_ids=[self._events[-1].event_id] if self._events else [],
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"runtime_epoch": next_epoch},
                TraceView.EVALUATOR: {"previous_runtime_epoch": previous_epoch, "runtime_epoch": next_epoch},
                TraceView.OPERATOR: {"previous_runtime_epoch": previous_epoch, "runtime_epoch": next_epoch},
            },
            decision_material={"previous_runtime_epoch": previous_epoch, "runtime_epoch": next_epoch},
            provenance_material={"previous_event_id": self._events[-1].event_id if self._events else ""},
        )
        self._runtime_epoch = next_epoch
        return receipt

    @_atomic_public
    def record_opportunity_inventory_compiled(
        self,
        *,
        turn_id: str,
        answer_version: int,
        semantic_event_id: str,
        admitted_candidates: Sequence[Mapping[str, Any]],
        excluded_candidates: Sequence[Mapping[str, Any]],
        runtime_epoch: int | None = None,
        producer: str = "backend.opportunity_inventory",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        semantic = self._require_event_type(semantic_event_id, TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED)
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value,
            idempotency_key=idempotency_key or f"inventory:{turn_id}:{answer_version}:{semantic_event_id}",
            causal_parent_ids=[semantic_event_id],
        )
        if rejected:
            return rejected
        assert ledger is not None
        final_id = ledger.semantic_final_by_version.get(answer_version)
        if final_id and final_id != semantic_event_id:
            raise TraceImmutableDecisionError("Inventory must use the immutable semantic decision for this answer version")
        if not final_id:
            raise TraceReferenceError("semantic_event_id is not the finalized decision for this turn/version")
        admitted = self._normalize_opportunities(admitted_candidates, admitted=True)
        excluded = self._normalize_opportunities(excluded_candidates, admitted=False)
        all_ids = [item["opportunity_id"] for item in admitted + excluded]
        if len(all_ids) != len(set(all_ids)):
            raise TraceInvariantError("Opportunity ids must be unique across admitted and excluded candidates")
        inventory_key = idempotency_key or f"inventory:{turn_id}:{answer_version}:{semantic_event_id}"
        receipt = self._append_raw(
            TraceEventType.OPPORTUNITY_INVENTORY_COMPILED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[semantic_event_id],
            producer=producer,
            idempotency_key=inventory_key,
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {
                    "admitted_opportunity_ids": [item["opportunity_id"] for item in admitted],
                },
                TraceView.EVALUATOR: {
                    "semantic_event_id": semantic_event_id,
                    "admitted_candidates": admitted,
                    "excluded_candidates": excluded,
                },
                TraceView.OPERATOR: {
                    "inventory_status": "compiled",
                    "admitted_count": len(admitted),
                    "excluded_count": len(excluded),
                },
            },
            decision_material={"admitted": admitted, "excluded": excluded},
            provenance_material={"semantic_event_id": semantic_event_id},
            logical_existing_event_id=ledger.inventory_event_by_version.get(answer_version, ""),
        )
        ledger.inventory_event_by_version[answer_version] = receipt.event.event_id
        return receipt

    def _normalize_opportunities(
        self,
        candidates: Sequence[Mapping[str, Any]],
        *,
        admitted: bool,
        known_events: Mapping[str, TraceEvent] | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            raise TraceInvariantError("Opportunity candidates must be an array")
        result: list[dict[str, Any]] = []
        for raw in candidates:
            if not isinstance(raw, Mapping):
                raise TraceInvariantError("Opportunity candidates must be objects")
            opportunity_id = str(raw.get("opportunity_id") or raw.get("id") or "").strip()
            if not opportunity_id:
                raise TraceInvariantError("Every opportunity must have an opportunity_id")
            evidence_ids = self._require_opportunity_evidence_sources(
                raw.get("evidence_event_ids") or raw.get("source_evidence_event_ids") or [],
                label=f"opportunity {opportunity_id} evidence_event_ids",
                known_events=known_events,
            )
            item: dict[str, Any] = {
                "opportunity_id": opportunity_id,
                "evidence_event_ids": list(evidence_ids),
                "kind": str(raw.get("kind") or raw.get("action") or "").strip(),
                "surface_id": str(raw.get("surface_id") or "").strip(),
                "surface_label": str(raw.get("surface_label") or "").strip(),
                "reason": str(raw.get("reason") or "").strip(),
                "admitted": admitted,
            }
            if admitted and not item["kind"]:
                raise TraceInvariantError(f"Admitted opportunity {opportunity_id} needs a kind")
            if not admitted and not item["reason"]:
                raise TraceInvariantError(f"Excluded opportunity {opportunity_id} needs an exclusion reason")
            result.append(item)
        return result

    @_atomic_public
    def record_action_grant_selected(
        self,
        *,
        turn_id: str,
        answer_version: int,
        opportunity_inventory_event_id: str,
        opportunity_id: str,
        source_evidence_event_ids: Sequence[str],
        prior_spoken_question_event_id: str,
        action: str,
        runtime_epoch: int | None = None,
        producer: str = "backend.action_grant",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        inventory = self._require_event_type(
            opportunity_inventory_event_id,
            TraceEventType.OPPORTUNITY_INVENTORY_COMPILED,
        )
        prior = self._require_event_type(
            prior_spoken_question_event_id,
            TraceEventType.SPOKEN_QUESTION_COMMITTED,
        )
        refs = self._require_sources(source_evidence_event_ids, label="action grant source_evidence_event_ids")
        inventory_view = _view(inventory, TraceView.EVALUATOR)
        candidates = inventory_view.get("admitted_candidates") if isinstance(inventory_view, dict) else []
        candidate = next(
            (item for item in candidates if isinstance(item, dict) and item.get("opportunity_id") == opportunity_id),
            None,
        )
        if candidate is None:
            excluded = inventory_view.get("excluded_candidates") if isinstance(inventory_view, dict) else []
            if any(isinstance(item, dict) and item.get("opportunity_id") == opportunity_id for item in excluded):
                raise TraceInvariantError("An excluded opportunity cannot receive an action grant")
            raise TraceReferenceError(f"Opportunity is not in the compiled inventory: {opportunity_id}")
        if tuple(candidate.get("evidence_event_ids") or []) != refs:
            raise TraceInvariantError("Action grant evidence must exactly match the admitted opportunity evidence")
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.ACTION_GRANT_SELECTED.value,
            idempotency_key=idempotency_key or f"grant:{turn_id}:{answer_version}:{opportunity_id}",
            causal_parent_ids=[opportunity_inventory_event_id, prior.event_id, *refs],
        )
        if rejected:
            return rejected
        assert ledger is not None
        if not ledger.action_grant_event_id:
            self._require_immediate_prior_spoken_question(
                prior.event_id,
                label="Action grant",
            )
        grant_key = idempotency_key or f"grant:{turn_id}:{answer_version}:{opportunity_id}"
        if ledger.action_grant_event_id:
            existing_grant = self._event(ledger.action_grant_event_id)
            if existing_grant.idempotency_key != grant_key:
                raise TraceConflictError("A turn cannot receive a second action grant")
        receipt = self._append_raw(
            TraceEventType.ACTION_GRANT_SELECTED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[opportunity_inventory_event_id, prior.event_id, *refs],
            producer=producer,
            idempotency_key=grant_key,
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {
                    "action": action,
                    "opportunity_id": opportunity_id,
                },
                TraceView.EVALUATOR: {
                    "action": action,
                    "opportunity_id": opportunity_id,
                    "opportunity_inventory_event_id": inventory.event_id,
                    "source_evidence_event_ids": list(refs),
                    "prior_spoken_question_event_id": prior.event_id,
                },
                TraceView.OPERATOR: {
                    "action": action,
                    "opportunity_id": opportunity_id,
                },
            },
            decision_material={"action": action, "opportunity_id": opportunity_id},
            provenance_material={
                "opportunity_inventory_event_id": inventory.event_id,
                "source_evidence_event_ids": refs,
                "prior_spoken_question_event_id": prior.event_id,
            },
            logical_existing_event_id=ledger.action_grant_event_id,
        )
        ledger.question_id = str(ledger.question_id or f"question:{turn_id}")
        ledger.source_opportunity_id = opportunity_id
        ledger.source_evidence_event_ids = refs
        ledger.prior_spoken_question_event_id = prior.event_id
        ledger.action_grant_event_id = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_state_transition_validated(
        self,
        *,
        turn_id: str,
        answer_version: int,
        decision: str,
        visible_route_commit_allowed: bool,
        source_opportunity_id: str,
        source_evidence_event_ids: Sequence[str],
        prior_spoken_question_event_id: str = "",
        action_grant_event_id: str = "",
        runtime_epoch: int | None = None,
        producer: str = "backend.state_validator",
        idempotency_key: str = "",
        reason: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"accepted", "rejected"}:
            raise TraceInvariantError("decision must be accepted or rejected")
        refs = self._require_sources(source_evidence_event_ids, label="validation source_evidence_event_ids")
        if prior_spoken_question_event_id:
            self._require_event_type(prior_spoken_question_event_id, TraceEventType.SPOKEN_QUESTION_COMMITTED)
        if action_grant_event_id:
            self._require_event_type(action_grant_event_id, TraceEventType.ACTION_GRANT_SELECTED)
        validation_key = idempotency_key or f"validation:{turn_id}:{answer_version}:{source_opportunity_id}:{normalized_decision}"
        if normalized_decision == "rejected":
            # A domain rejection is canonical audit evidence, but it is not a
            # turn mutation and must never create/advance a derived ledger.
            return self._reject_stale(
                attempted_event_type=TraceEventType.STATE_TRANSITION_VALIDATED.value,
                turn_id=str(turn_id or ""),
                answer_version=answer_version,
                runtime_epoch=epoch,
                idempotency_key=validation_key,
                causal_parent_ids=[item for item in [action_grant_event_id, prior_spoken_question_event_id, *refs] if item],
                reason="stale_runtime_epoch" if epoch != self._runtime_epoch else (reason or "domain_rejected"),
            )
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.STATE_TRANSITION_VALIDATED.value,
            idempotency_key=validation_key,
            causal_parent_ids=[item for item in [action_grant_event_id, prior_spoken_question_event_id, *refs] if item],
        )
        if rejected:
            return rejected
        assert ledger is not None
        if action_grant_event_id:
            if ledger.action_grant_event_id != action_grant_event_id:
                raise TraceReferenceError("Validation does not match this turn's action grant")
        elif not (turn_id and source_opportunity_id):
            raise TraceReferenceError("Startup validation still needs a source opportunity")
        if ledger.source_opportunity_id and ledger.source_opportunity_id != source_opportunity_id:
            raise TraceInvariantError("Validation source opportunity does not match the action grant")
        if ledger.source_evidence_event_ids and ledger.source_evidence_event_ids != refs:
            raise TraceInvariantError("Validation source evidence does not match the action grant")
        if ledger.prior_spoken_question_event_id and ledger.prior_spoken_question_event_id != prior_spoken_question_event_id:
            raise TraceInvariantError("Validation prior question does not match the action grant")
        if not ledger.source_opportunity_id:
            ledger.source_opportunity_id = source_opportunity_id
        if not ledger.source_evidence_event_ids:
            ledger.source_evidence_event_ids = refs
        if not ledger.prior_spoken_question_event_id:
            ledger.prior_spoken_question_event_id = prior_spoken_question_event_id
        receipt = self._append_raw(
            TraceEventType.STATE_TRANSITION_VALIDATED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[item for item in [action_grant_event_id, prior_spoken_question_event_id, *refs] if item],
            producer=producer,
            idempotency_key=idempotency_key or f"validation:{turn_id}:{answer_version}:{source_opportunity_id}:{normalized_decision}",
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {
                    "validation_status": normalized_decision,
                    "visible_route_commit_allowed": bool(visible_route_commit_allowed and normalized_decision == "accepted"),
                },
                TraceView.EVALUATOR: {
                    "validation_status": normalized_decision,
                    "visible_route_commit_allowed": bool(visible_route_commit_allowed and normalized_decision == "accepted"),
                    "source_opportunity_id": source_opportunity_id,
                    "source_evidence_event_ids": list(refs),
                    "prior_spoken_question_event_id": prior_spoken_question_event_id,
                    "action_grant_event_id": action_grant_event_id,
                    "reason": reason,
                },
                TraceView.OPERATOR: {
                    "validation_status": normalized_decision,
                    "visible_route_commit_allowed": bool(visible_route_commit_allowed and normalized_decision == "accepted"),
                    "reason": reason,
                },
            },
            decision_material={"decision": normalized_decision, "visible_route_commit_allowed": visible_route_commit_allowed},
            provenance_material={
                "source_opportunity_id": source_opportunity_id,
                "source_evidence_event_ids": refs,
                "prior_spoken_question_event_id": prior_spoken_question_event_id,
                "action_grant_event_id": action_grant_event_id,
            },
            logical_existing_event_id=ledger.validation_event_id,
        )
        # Run this final lineage gate after the append has exercised the clock
        # and event path.  The public atomic wrapper rolls back the temporary
        # append if the live route is stale/split, preserving the exact
        # exception/rollback contract for late failures as well.
        if not ledger.validation_event_id:
            self._require_immediate_prior_spoken_question(
                prior_spoken_question_event_id,
                label="Validation",
            )
        ledger.validation_event_id = receipt.event.event_id
        ledger.validation_status = normalized_decision
        ledger.visible_route_commit_allowed = bool(
            visible_route_commit_allowed and normalized_decision == "accepted"
        )
        return TraceReceipt(
            accepted=normalized_decision == "accepted",
            event=receipt.event,
            idempotent=receipt.idempotent,
            reason=reason if normalized_decision == "rejected" else "",
        )

    @_atomic_public
    def record_question_materialized(
        self,
        *,
        turn_id: str,
        answer_version: int,
        question_id: str,
        visible_text: str,
        source_opportunity_id: str,
        source_evidence_event_ids: Sequence[str],
        prior_spoken_question_event_id: str = "",
        action_grant_event_id: str = "",
        runtime_epoch: int | None = None,
        producer: str = "backend.question_materializer",
        idempotency_key: str = "",
        route_kind: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        text = str(visible_text or "").strip()
        if not text:
            raise TraceInvariantError("question materialized requires exact candidate-visible text")
        refs = self._require_sources(source_evidence_event_ids, label="materialized source_evidence_event_ids")
        ledger = self._turns.get(str(turn_id))
        if ledger is None:
            raise TraceReferenceError("Question materialization requires a prior validation event")
        if epoch != self._runtime_epoch or epoch != ledger.runtime_epoch or answer_version < ledger.current_answer_version:
            return self._reject_stale(
                attempted_event_type=TraceEventType.QUESTION_MATERIALIZED.value,
                turn_id=turn_id,
                answer_version=answer_version,
                runtime_epoch=epoch,
                idempotency_key=idempotency_key or f"materialized:{turn_id}:{answer_version}:{question_id}",
                causal_parent_ids=[ledger.validation_event_id] if ledger.validation_event_id else [],
                reason="stale_materialization_context",
            )
        if answer_version > ledger.current_answer_version + 1:
            return self._reject_stale(
                attempted_event_type=TraceEventType.QUESTION_MATERIALIZED.value,
                turn_id=turn_id,
                answer_version=answer_version,
                runtime_epoch=epoch,
                idempotency_key=idempotency_key or f"materialized:{turn_id}:{answer_version}:{question_id}",
                causal_parent_ids=[ledger.validation_event_id] if ledger.validation_event_id else [],
                reason="answer_version_gap",
            )
        if ledger.validation_status != "accepted" or not ledger.visible_route_commit_allowed:
            raise TraceInvariantError("Rejected validation cannot apply visible route commit")
        if ledger.source_opportunity_id != source_opportunity_id or ledger.source_evidence_event_ids != refs:
            raise TraceInvariantError("Materialized question provenance does not match the action grant")
        if not ledger.materialized_event_id:
            self._require_immediate_prior_spoken_question(
                prior_spoken_question_event_id,
                label="Materialized question",
            )
        if ledger.prior_spoken_question_event_id != prior_spoken_question_event_id:
            raise TraceInvariantError("Materialized question must reference the exact prior spoken question")
        if action_grant_event_id and ledger.action_grant_event_id != action_grant_event_id:
            raise TraceInvariantError("Materialized question action grant mismatch")
        if not action_grant_event_id and ledger.action_grant_event_id:
            action_grant_event_id = ledger.action_grant_event_id
        parents = [ledger.validation_event_id, action_grant_event_id, prior_spoken_question_event_id, *refs]
        parents = [item for item in parents if item]
        receipt = self._append_raw(
            TraceEventType.QUESTION_MATERIALIZED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=parents,
            producer=producer,
            idempotency_key=idempotency_key or f"materialized:{turn_id}:{answer_version}:{question_id}",
            views={
                TraceView.CANDIDATE: {"question_text": text},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {
                    "question_id": question_id,
                    "question_text": text,
                    "route_kind": route_kind,
                },
                TraceView.EVALUATOR: {
                    "question_id": question_id,
                    "question_text": text,
                    "source_opportunity_id": source_opportunity_id,
                    "source_evidence_event_ids": list(refs),
                    "prior_spoken_question_event_id": prior_spoken_question_event_id,
                    "action_grant_event_id": action_grant_event_id,
                    "route_kind": route_kind,
                },
                TraceView.OPERATOR: {
                    "question_id": question_id,
                    "route_kind": route_kind,
                },
            },
            decision_material={"question_id": question_id, "question_text": text, "route_kind": route_kind},
            provenance_material={
                "source_opportunity_id": source_opportunity_id,
                "source_evidence_event_ids": refs,
                "prior_spoken_question_event_id": prior_spoken_question_event_id,
                "action_grant_event_id": action_grant_event_id,
            },
            logical_existing_event_id=ledger.materialized_event_id,
        )
        ledger.question_id = question_id
        ledger.materialized_event_id = receipt.event.event_id
        ledger.current_answer_version = max(ledger.current_answer_version, answer_version)
        return receipt

    @_atomic_public
    def record_question_prepared(
        self,
        *,
        turn_id: str,
        answer_version: int,
        question_id: str,
        materialized_event_id: str,
        source_opportunity_id: str,
        source_evidence_event_ids: Sequence[str],
        prior_spoken_question_event_id: str = "",
        runtime_epoch: int | None = None,
        producer: str = "backend.question_preparer",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        materialized = self._require_event_type(materialized_event_id, TraceEventType.QUESTION_MATERIALIZED)
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.QUESTION_PREPARED.value,
            idempotency_key=idempotency_key or f"prepared:{turn_id}:{answer_version}:{question_id}",
            causal_parent_ids=[materialized_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.materialized_event_id != materialized_event_id:
            raise TraceReferenceError("Question prepared must reference the current materialization")
        materialized_view = _view(materialized, TraceView.EVALUATOR)
        if materialized_view.get("question_id") != question_id:
            raise TraceInvariantError("Prepared question id does not match materialization")
        if materialized_view.get("source_opportunity_id") != source_opportunity_id:
            raise TraceInvariantError("Prepared question opportunity does not match materialization")
        refs = self._require_sources(
            source_evidence_event_ids,
            label="prepared source_evidence_event_ids",
        )
        if tuple(materialized_view.get("source_evidence_event_ids") or []) != refs:
            raise TraceInvariantError("Prepared question evidence does not match materialization")
        if materialized_view.get("prior_spoken_question_event_id", "") != prior_spoken_question_event_id:
            raise TraceInvariantError("Prepared question prior-spoken reference does not match materialization")
        receipt = self._append_raw(
            TraceEventType.QUESTION_PREPARED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[materialized_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"prepared:{turn_id}:{answer_version}:{question_id}",
            views={
                TraceView.CANDIDATE: {"question_id": question_id},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"question_id": question_id},
                TraceView.EVALUATOR: {
                    "question_id": question_id,
                    "materialized_event_id": materialized_event_id,
                    "source_opportunity_id": source_opportunity_id,
                    "source_evidence_event_ids": list(refs),
                    "prior_spoken_question_event_id": prior_spoken_question_event_id,
                },
                TraceView.OPERATOR: {"question_id": question_id, "materialized_event_id": materialized_event_id},
            },
            decision_material={"question_id": question_id},
            provenance_material={"materialized_event_id": materialized_event_id},
            logical_existing_event_id=ledger.prepared_event_id,
        )
        ledger.prepared_event_id = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_question_delivery_started(
        self,
        *,
        turn_id: str,
        answer_version: int,
        question_prepared_event_id: str,
        delivery_attempt_id: str,
        runtime_epoch: int | None = None,
        producer: str = "frontend.delivery",
        idempotency_key: str = "",
        provider: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        prepared = self._require_event_type(question_prepared_event_id, TraceEventType.QUESTION_PREPARED)
        attempt = str(delivery_attempt_id or "").strip()
        if not attempt:
            raise TraceInvariantError("delivery_attempt_id is required")
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.QUESTION_DELIVERY_STARTED.value,
            idempotency_key=idempotency_key or f"delivery-start:{turn_id}:{answer_version}:{attempt}",
            causal_parent_ids=[question_prepared_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.prepared_event_id != prepared.event_id:
            raise TraceReferenceError("Delivery must reference the current prepared question")
        if ledger.spoken_question_event_id:
            raise TraceInvariantError("Cannot start delivery after the question was committed as spoken")
        receipt = self._append_raw(
            TraceEventType.QUESTION_DELIVERY_STARTED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[question_prepared_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"delivery-start:{turn_id}:{answer_version}:{attempt}",
            views={
                TraceView.CANDIDATE: {"delivery_attempt_id": attempt},
                TraceView.ACTOR: {"delivery_attempt_id": attempt},
                TraceView.INTERVIEWER: {"delivery_attempt_id": attempt},
                TraceView.EVALUATOR: {"delivery_attempt_id": attempt, "question_prepared_event_id": prepared.event_id},
                TraceView.OPERATOR: {"delivery_attempt_id": attempt, "provider": provider},
            },
            decision_material={"delivery_attempt_id": attempt},
            provenance_material={"question_prepared_event_id": prepared.event_id},
            logical_existing_event_id=ledger.delivery_started_by_attempt.get(attempt, ""),
        )
        ledger.delivery_started_by_attempt[attempt] = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_playback_acknowledged(
        self,
        *,
        turn_id: str,
        answer_version: int,
        delivery_attempt_id: str,
        delivery_started_event_id: str,
        runtime_epoch: int | None = None,
        producer: str = "frontend.playback",
        idempotency_key: str = "",
        client_ack: PlaybackAckStatus | str = PlaybackAckStatus.COMPLETED,
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        started = self._require_event_type(delivery_started_event_id, TraceEventType.QUESTION_DELIVERY_STARTED)
        attempt = str(delivery_attempt_id or "").strip()
        if not attempt:
            raise TraceInvariantError("delivery_attempt_id is required")
        ack_status = client_ack.value if isinstance(client_ack, PlaybackAckStatus) else str(client_ack or "").strip()
        if ack_status != PlaybackAckStatus.COMPLETED.value:
            raise TraceInvariantError("Only explicit playback_completed acknowledgement is positive playback truth")
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.PLAYBACK_ACKNOWLEDGED.value,
            idempotency_key=idempotency_key or f"playback-ack:{turn_id}:{answer_version}:{attempt}",
            causal_parent_ids=[delivery_started_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.delivery_started_by_attempt.get(attempt) != started.event_id:
            raise TraceReferenceError("Playback ACK does not match a delivery attempt")
        if attempt in ledger.delivery_failed_attempts:
            raise TraceInvariantError("A failed delivery attempt cannot be acknowledged")
        receipt = self._append_raw(
            TraceEventType.PLAYBACK_ACKNOWLEDGED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[delivery_started_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"playback-ack:{turn_id}:{answer_version}:{attempt}",
            views={
                TraceView.CANDIDATE: {"delivery_attempt_id": attempt, "acknowledged": True},
                TraceView.ACTOR: {"delivery_attempt_id": attempt, "acknowledged": True},
                TraceView.INTERVIEWER: {"delivery_attempt_id": attempt, "acknowledged": True},
                TraceView.EVALUATOR: {"delivery_attempt_id": attempt, "acknowledged": True, "client_ack": ack_status},
                TraceView.OPERATOR: {"delivery_attempt_id": attempt, "client_ack": ack_status},
            },
            decision_material={"delivery_attempt_id": attempt, "acknowledged": True},
            provenance_material={"delivery_started_event_id": started.event_id},
            logical_existing_event_id=ledger.playback_ack_by_attempt.get(attempt, ""),
        )
        ledger.playback_ack_by_attempt[attempt] = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_delivery_failed(
        self,
        *,
        turn_id: str,
        answer_version: int,
        delivery_attempt_id: str,
        delivery_started_event_id: str,
        reason: str,
        retryable: bool = True,
        runtime_epoch: int | None = None,
        producer: str = "frontend.delivery",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        started = self._require_event_type(delivery_started_event_id, TraceEventType.QUESTION_DELIVERY_STARTED)
        attempt = str(delivery_attempt_id or "").strip()
        if not attempt:
            raise TraceInvariantError("delivery_attempt_id is required")
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.DELIVERY_FAILED.value,
            idempotency_key=idempotency_key or f"delivery-failed:{turn_id}:{answer_version}:{attempt}",
            causal_parent_ids=[delivery_started_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.delivery_started_by_attempt.get(attempt) != started.event_id:
            raise TraceReferenceError("Delivery failure does not match a delivery attempt")
        if attempt in ledger.playback_ack_by_attempt:
            raise TraceInvariantError("A successfully acknowledged delivery cannot later fail")
        receipt = self._append_raw(
            TraceEventType.DELIVERY_FAILED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[delivery_started_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"delivery-failed:{turn_id}:{answer_version}:{attempt}",
            views={
                TraceView.CANDIDATE: {"delivery_attempt_id": attempt, "delivery_failed": True},
                TraceView.ACTOR: {"delivery_attempt_id": attempt, "delivery_failed": True, "retryable": retryable},
                TraceView.INTERVIEWER: {"delivery_attempt_id": attempt, "delivery_failed": True},
                TraceView.EVALUATOR: {"delivery_attempt_id": attempt, "delivery_failed": True, "retryable": retryable},
                TraceView.OPERATOR: {"delivery_attempt_id": attempt, "delivery_failed": True, "retryable": retryable, "reason": reason},
            },
            decision_material={"delivery_attempt_id": attempt, "delivery_failed": True, "retryable": retryable},
            provenance_material={"delivery_started_event_id": started.event_id},
            logical_existing_event_id=ledger.delivery_failed_event_by_attempt.get(attempt, ""),
        )
        ledger.delivery_failed_attempts.add(attempt)
        ledger.delivery_failed_event_by_attempt[attempt] = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_spoken_question_committed(
        self,
        *,
        turn_id: str,
        answer_version: int,
        question_id: str,
        visible_text: str,
        question_materialized_event_id: str,
        playback_ack_event_id: str,
        delivery_attempt_id: str,
        prior_spoken_question_event_id: str = "",
        source_opportunity_id: str = "",
        source_evidence_event_ids: Sequence[str] = (),
        runtime_epoch: int | None = None,
        producer: str = "frontend.playback",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        materialized = self._require_event_type(question_materialized_event_id, TraceEventType.QUESTION_MATERIALIZED)
        ack = self._require_event_type(playback_ack_event_id, TraceEventType.PLAYBACK_ACKNOWLEDGED)
        text = str(visible_text or "").strip()
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.SPOKEN_QUESTION_COMMITTED.value,
            idempotency_key=idempotency_key or f"spoken:{turn_id}:{answer_version}:{question_id}",
            causal_parent_ids=[question_materialized_event_id, playback_ack_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.materialized_event_id != materialized.event_id:
            raise TraceReferenceError("Spoken question must reference the current materialization")
        if ledger.playback_ack_by_attempt.get(delivery_attempt_id) != ack.event_id:
            raise TraceReferenceError("Spoken question must reference the ACK for its delivery attempt")
        if delivery_attempt_id in ledger.delivery_failed_attempts:
            raise TraceInvariantError("A failed delivery attempt cannot become spoken")
        # A repeat against an already committed logical spoken event should
        # reach the exact-once/conflict fingerprint check below even though a
        # later spoken question may now be the trace-wide latest event.
        if not ledger.spoken_question_event_id:
            self._require_immediate_prior_spoken_question(
                prior_spoken_question_event_id,
                label="Spoken question",
            )
        materialized_view = _view(materialized, TraceView.EVALUATOR)
        if materialized_view.get("question_id") != question_id or materialized_view.get("question_text") != text:
            raise TraceInvariantError("Spoken question text/id must exactly match materialization")
        expected_prior = str(materialized_view.get("prior_spoken_question_event_id") or "")
        if expected_prior != str(prior_spoken_question_event_id or ""):
            raise TraceInvariantError("Spoken question prior reference must exactly match materialization")
        refs = self._require_sources(
            source_evidence_event_ids,
            label="spoken source_evidence_event_ids",
        )
        if tuple(materialized_view.get("source_evidence_event_ids") or []) != refs:
            raise TraceInvariantError("Spoken question evidence must exactly match materialization")
        if str(materialized_view.get("source_opportunity_id") or "") != str(source_opportunity_id or ""):
            raise TraceInvariantError("Spoken question opportunity must exactly match materialization")
        receipt = self._append_raw(
            TraceEventType.SPOKEN_QUESTION_COMMITTED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[question_materialized_event_id, playback_ack_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"spoken:{turn_id}:{answer_version}:{question_id}",
            views={
                TraceView.CANDIDATE: {"question_id": question_id, "question_text": text},
                TraceView.ACTOR: {"question_id": question_id, "delivery_attempt_id": delivery_attempt_id},
                TraceView.INTERVIEWER: {"question_id": question_id, "question_text": text},
                TraceView.EVALUATOR: {
                    "question_id": question_id,
                    "question_text": text,
                    "question_materialized_event_id": materialized.event_id,
                    "playback_ack_event_id": ack.event_id,
                    "delivery_attempt_id": delivery_attempt_id,
                    "source_opportunity_id": source_opportunity_id,
                    "source_evidence_event_ids": list(refs),
                    "prior_spoken_question_event_id": prior_spoken_question_event_id,
                },
                TraceView.OPERATOR: {
                    "question_id": question_id,
                    "delivery_attempt_id": delivery_attempt_id,
                    "playback_ack_event_id": ack.event_id,
                },
            },
            decision_material={"question_id": question_id, "question_text": text},
            provenance_material={
                "question_materialized_event_id": materialized.event_id,
                "playback_ack_event_id": ack.event_id,
                "prior_spoken_question_event_id": prior_spoken_question_event_id,
                "source_opportunity_id": source_opportunity_id,
                "source_evidence_event_ids": refs,
            },
            logical_existing_event_id=ledger.spoken_question_event_id,
        )
        ledger.spoken_question_event_id = receipt.event.event_id
        self._last_spoken_question_event_id = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_answer_received(
        self,
        *,
        turn_id: str,
        answer_version: int,
        spoken_question_event_id: str,
        answer_text: str,
        runtime_epoch: int | None = None,
        producer: str = "frontend.asr",
        idempotency_key: str = "",
        answer_text_authorized: bool = True,
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        spoken = self._require_event_type(spoken_question_event_id, TraceEventType.SPOKEN_QUESTION_COMMITTED)
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.ANSWER_RECEIVED.value,
            idempotency_key=idempotency_key or f"answer:{turn_id}:{answer_version}:{_sha256(answer_text)}",
            causal_parent_ids=[spoken_question_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.spoken_question_event_id != spoken.event_id:
            raise TraceReferenceError("Answer must reference the spoken question for the same turn")
        answer = str(answer_text or "").strip()
        if not answer:
            raise TraceInvariantError("answer_received requires non-empty answer text")
        evaluator_view: dict[str, Any] = {
            "spoken_question_event_id": spoken.event_id,
            "answer_text_hash": _sha256(answer),
        }
        if answer_text_authorized:
            evaluator_view["answer_text"] = answer
        receipt = self._append_raw(
            TraceEventType.ANSWER_RECEIVED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[spoken_question_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"answer:{turn_id}:{answer_version}:{_sha256(answer)}",
            views={
                TraceView.CANDIDATE: {"answer_received": True, "answer_version": answer_version},
                TraceView.ACTOR: {"answer_received": True, "answer_version": answer_version},
                TraceView.INTERVIEWER: {"spoken_question_event_id": spoken.event_id},
                TraceView.EVALUATOR: evaluator_view,
                TraceView.OPERATOR: {"spoken_question_event_id": spoken.event_id, "answer_chars": len(answer)},
            },
            decision_material={"answer_text_hash": _sha256(answer), "answer_version": answer_version},
            provenance_material={"spoken_question_event_id": spoken.event_id},
            logical_existing_event_id=ledger.answer_event_by_version.get(answer_version, ""),
        )
        ledger.answer_event_by_version[answer_version] = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_semantic_interpretation_finalized(
        self,
        *,
        turn_id: str,
        answer_version: int,
        answer_event_id: str,
        interpretation: Mapping[str, Any],
        runtime_epoch: int | None = None,
        producer: str = "backend.semantic_interpreter",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        answer = self._require_event_type(answer_event_id, TraceEventType.ANSWER_RECEIVED)
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
            idempotency_key=idempotency_key or f"semantic-final:{turn_id}:{answer_version}:{answer_event_id}",
            causal_parent_ids=[answer_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.answer_event_by_version.get(answer_version) != answer.event_id:
            raise TraceReferenceError("Semantic interpretation must reference the current answer event")
        if not isinstance(interpretation, Mapping):
            raise TraceInvariantError("interpretation must be an object")
        result = dict(interpretation)
        semantic_key = idempotency_key or f"semantic-final:{turn_id}:{answer_version}:{answer_event_id}"
        existing_final_id = ledger.semantic_final_by_version.get(answer_version, "")
        if existing_final_id:
            existing_final = self._event(existing_final_id)
            existing_interpretation = _view(existing_final, TraceView.EVALUATOR).get("interpretation")
            if existing_final.idempotency_key == semantic_key:
                if existing_interpretation == result:
                    return TraceReceipt(accepted=True, event=existing_final, idempotent=True)
                raise TraceConflictError("Semantic final idempotency key reused with different content")
            raise TraceImmutableDecisionError(
                "Decision-time semantic output is immutable; append a semantic_interpretation_shadow event"
            )
        receipt = self._append_raw(
            TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[answer_event_id],
            producer=producer,
            idempotency_key=semantic_key,
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"semantic_status": "finalized"},
                TraceView.EVALUATOR: {
                    "answer_event_id": answer_event_id,
                    "interpretation": result,
                    "decision_immutable": True,
                },
                TraceView.OPERATOR: {"semantic_status": "finalized", "answer_event_id": answer_event_id},
            },
            decision_material={"interpretation": result},
            provenance_material={"answer_event_id": answer_event_id},
            logical_existing_event_id=existing_final_id,
        )
        ledger.semantic_final_by_version[answer_version] = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_semantic_interpretation_shadow(
        self,
        *,
        turn_id: str,
        answer_version: int,
        answer_event_id: str,
        finalized_event_id: str,
        interpretation: Mapping[str, Any],
        disagreement: Mapping[str, Any] | None = None,
        runtime_epoch: int | None = None,
        producer: str = "backend.semantic_shadow",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        answer = self._require_event_type(answer_event_id, TraceEventType.ANSWER_RECEIVED)
        finalized = self._require_event_type(
            finalized_event_id,
            TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED,
        )
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value,
            idempotency_key=idempotency_key or f"semantic-shadow:{turn_id}:{answer_version}:{finalized_event_id}:{_sha256(interpretation)}",
            causal_parent_ids=[answer_event_id, finalized_event_id],
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.answer_event_by_version.get(answer_version) != answer.event_id:
            raise TraceReferenceError("Shadow interpretation must reference the current answer event")
        if ledger.semantic_final_by_version.get(answer_version) != finalized.event_id:
            raise TraceReferenceError("Shadow interpretation must compare against the immutable final decision")
        result = dict(interpretation)
        disagreement_payload = dict(disagreement or {})
        receipt = self._append_raw(
            TraceEventType.SEMANTIC_INTERPRETATION_SHADOW,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=[answer_event_id, finalized_event_id],
            producer=producer,
            idempotency_key=idempotency_key or f"semantic-shadow:{turn_id}:{answer_version}:{finalized_event_id}:{_sha256(interpretation)}",
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"semantic_status": "shadow"},
                TraceView.EVALUATOR: {
                    "answer_event_id": answer_event_id,
                    "shadow_of_event_id": finalized.event_id,
                    "interpretation": result,
                    "disagreement": disagreement_payload,
                    "does_not_overwrite_final": True,
                },
                TraceView.OPERATOR: {"semantic_status": "shadow", "disagreement": disagreement_payload},
            },
            decision_material={"interpretation": result, "disagreement": disagreement_payload},
            provenance_material={"answer_event_id": answer_event_id, "shadow_of_event_id": finalized.event_id},
        )
        ledger.shadow_event_ids_by_version.setdefault(answer_version, []).append(receipt.event.event_id)
        return receipt

    @_atomic_public
    def record_evidence_state_updated(
        self,
        *,
        turn_id: str,
        answer_version: int,
        semantic_event_id: str,
        opportunity_inventory_event_id: str,
        evidence_state: Mapping[str, Any],
        source_event_ids: Sequence[str],
        runtime_epoch: int | None = None,
        producer: str = "backend.evidence_state",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        semantic = self._require_event_type(semantic_event_id, TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED)
        inventory = self._require_event_type(opportunity_inventory_event_id, TraceEventType.OPPORTUNITY_INVENTORY_COMPILED)
        refs = self._require_sources(source_event_ids, label="evidence source_event_ids")
        if semantic_event_id not in refs or opportunity_inventory_event_id not in refs:
            raise TraceInvariantError("Evidence update must cite its semantic and opportunity inventory sources")
        ledger, rejected = self._turn_for_new_or_existing(
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            attempted_event_type=TraceEventType.EVIDENCE_STATE_UPDATED.value,
            idempotency_key=idempotency_key or f"evidence:{turn_id}:{answer_version}:{semantic_event_id}:{opportunity_inventory_event_id}",
            causal_parent_ids=refs,
            allow_new=False,
        )
        if rejected:
            return rejected
        assert ledger is not None
        if ledger.semantic_final_by_version.get(answer_version) != semantic.event_id:
            raise TraceReferenceError("Evidence update must use the immutable semantic decision")
        if ledger.inventory_event_by_version.get(answer_version) != inventory.event_id:
            raise TraceReferenceError("Evidence update must use the current opportunity inventory")
        if not ledger.spoken_question_event_id:
            raise TraceInvariantError("Delivery must be spoken before evidence or coverage truth can advance")
        state = dict(evidence_state)
        receipt = self._append_raw(
            TraceEventType.EVIDENCE_STATE_UPDATED,
            turn_id=turn_id,
            answer_version=answer_version,
            runtime_epoch=epoch,
            causal_parent_ids=refs,
            producer=producer,
            idempotency_key=idempotency_key or f"evidence:{turn_id}:{answer_version}:{semantic_event_id}:{opportunity_inventory_event_id}",
            views={
                TraceView.CANDIDATE: {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"evidence_state_hash": _sha256(state)},
                TraceView.EVALUATOR: {
                    "semantic_event_id": semantic.event_id,
                    "opportunity_inventory_event_id": inventory.event_id,
                    "source_event_ids": list(refs),
                    "evidence_state": state,
                },
                TraceView.OPERATOR: {"evidence_state_hash": _sha256(state), "source_event_count": len(refs)},
            },
            decision_material={"evidence_state": state},
            provenance_material={"source_event_ids": refs},
            logical_existing_event_id=ledger.evidence_event_by_version.get(answer_version, ""),
        )
        ledger.evidence_event_by_version[answer_version] = receipt.event.event_id
        return receipt

    @_atomic_public
    def record_report_claim_emitted(
        self,
        *,
        claim_id: str,
        claim_text: str,
        source_evidence_event_ids: Sequence[str],
        audience: str = "recruiter",
        runtime_epoch: int | None = None,
        producer: str = "backend.report",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        self._require_current_epoch(epoch)
        refs = self._require_sources_of_type(
            source_evidence_event_ids,
            expected=TraceEventType.EVIDENCE_STATE_UPDATED,
            label="report claim source_evidence_event_ids",
        )
        if not str(claim_text or "").strip():
            raise TraceInvariantError("report claim text is required")
        claim_existing_event_id = self._find_logical_event(
            TraceEventType.REPORT_CLAIM_EMITTED, "claim_id", claim_id
        )
        receipt = self._append_raw(
            TraceEventType.REPORT_CLAIM_EMITTED,
            runtime_epoch=epoch,
            causal_parent_ids=refs,
            producer=producer,
            idempotency_key=idempotency_key or f"report-claim:{claim_id}",
            views={
                TraceView.CANDIDATE: {"claim_id": claim_id, "claim_text": claim_text} if audience == "candidate" else {},
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"claim_id": claim_id, "audience": audience},
                TraceView.EVALUATOR: {
                    "claim_id": claim_id,
                    "claim_text": claim_text,
                    "audience": audience,
                    "source_evidence_event_ids": list(refs),
                },
                TraceView.OPERATOR: {"claim_id": claim_id, "audience": audience},
            },
            decision_material={"claim_id": claim_id, "claim_text": claim_text, "audience": audience},
            provenance_material={"source_evidence_event_ids": refs},
            logical_existing_event_id=claim_existing_event_id,
        )
        return receipt

    @_atomic_public
    def record_final_evaluation_completed(
        self,
        *,
        evaluation_id: str,
        report_claim_event_ids: Sequence[str],
        evidence_event_ids: Sequence[str],
        evaluation_summary: Mapping[str, Any],
        runtime_epoch: int | None = None,
        producer: str = "backend.final_evaluator",
        idempotency_key: str = "",
    ) -> TraceReceipt:
        epoch = self._runtime_epoch if runtime_epoch is None else int(runtime_epoch)
        self._require_current_epoch(epoch)
        claim_refs = self._require_sources_of_type(
            report_claim_event_ids,
            expected=TraceEventType.REPORT_CLAIM_EMITTED,
            label="final evaluation report_claim_event_ids",
        )
        for event_id in claim_refs:
            self._require_event_type(event_id, TraceEventType.REPORT_CLAIM_EMITTED)
        evidence_refs = self._require_sources_of_type(
            evidence_event_ids,
            expected=TraceEventType.EVIDENCE_STATE_UPDATED,
            label="final evaluation evidence_event_ids",
        )
        evidence_set = set(evidence_refs)
        for claim_id in claim_refs:
            claim_view = _view(self._event(claim_id), TraceView.EVALUATOR)
            if not set(claim_view.get("source_evidence_event_ids") or []).issubset(evidence_set):
                raise TraceReferenceError("Final evaluation evidence must cover every report claim citation")
        parents = _dedupe_ids([*claim_refs, *evidence_refs])
        summary = dict(evaluation_summary)
        final_existing_event_id = self._final_evaluation_event_id
        receipt = self._append_raw(
            TraceEventType.FINAL_EVALUATION_COMPLETED,
            runtime_epoch=epoch,
            causal_parent_ids=parents,
            producer=producer,
            idempotency_key=idempotency_key or f"final-evaluation:{evaluation_id}",
            views={
                TraceView.CANDIDATE: {
                    "evaluation_id": evaluation_id,
                    "status": "completed",
                },
                TraceView.ACTOR: {},
                TraceView.INTERVIEWER: {"evaluation_id": evaluation_id, "status": "completed"},
                TraceView.EVALUATOR: {
                    "evaluation_id": evaluation_id,
                    "report_claim_event_ids": list(claim_refs),
                    "evidence_event_ids": list(evidence_refs),
                    "evaluation_summary": summary,
                },
                TraceView.OPERATOR: {"evaluation_id": evaluation_id, "status": "completed"},
            },
            decision_material={"evaluation_id": evaluation_id, "evaluation_summary": summary},
            provenance_material={"report_claim_event_ids": claim_refs, "evidence_event_ids": evidence_refs},
            logical_existing_event_id=final_existing_event_id,
        )
        self._final_evaluation_event_id = receipt.event.event_id
        return receipt

    def project(self, view: TraceView | str) -> list[dict[str, Any]]:
        """Project only the selected sensitivity view.

        Each projection is filtered through the explicit per-view/per-event
        allowlist.  The actor projection is CandidateActorV1 and therefore
        omits all internal decision, opportunity, semantic, evidence, report,
        and shadow truth.
        """
        self._ensure_authoritative()
        view_name = view.value if isinstance(view, TraceView) else str(view)
        if view_name not in _VIEW_NAMES:
            raise TraceInvariantError(f"Unknown trace projection view: {view_name}")
        result: list[dict[str, Any]] = []
        for event in self._events:
            payload = _project_view_payload(event, view_name)
            if not payload:
                continue
            item = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "event_id": event.event_id,
                "session_id": event.session_id,
                "turn_id": event.turn_id,
                "answer_version": event.answer_version,
                "event_type": event.event_type,
                "payload": payload,
                "redaction": {
                    "policy": event.redaction.get("policy"),
                    "raw_provider_payload_excluded": True,
                    "raw_secrets_excluded": True,
                },
            }
            if view_name not in {TraceView.CANDIDATE.value, TraceView.ACTOR.value}:
                item.update(
                    {
                        "runtime_epoch": event.runtime_epoch,
                        "occurred_at_ms": event.occurred_at_ms,
                        "recorded_at_ms": event.recorded_at_ms,
                        "producer": event.producer,
                    }
                )
                item["sequence"] = event.sequence
            result.append(item)
        return result

    def canonical_spoken_history(self) -> list[dict[str, Any]]:
        """Replay the same canonical spoken questions and latest answers."""
        self._ensure_authoritative()
        spoken: dict[str, dict[str, Any]] = {}
        answer_by_turn: dict[str, tuple[int, TraceEvent]] = {}
        for event in self._events:
            if event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value:
                view = _view(event, TraceView.EVALUATOR)
                spoken[event.turn_id] = {
                    "turn_id": event.turn_id,
                    "question_id": view.get("question_id", ""),
                    "question_text": view.get("question_text", ""),
                    "spoken_event_id": event.event_id,
                    "spoken_sequence": event.sequence,
                }
            elif event.event_type == TraceEventType.ANSWER_RECEIVED.value:
                current = answer_by_turn.get(event.turn_id)
                if current is None or event.answer_version > current[0]:
                    answer_by_turn[event.turn_id] = (event.answer_version, event)
        result: list[dict[str, Any]] = []
        for item in sorted(spoken.values(), key=lambda row: row["spoken_sequence"]):
            answer_version, answer_event = answer_by_turn.get(item["turn_id"], (0, None))
            answer_view = _view(answer_event, TraceView.EVALUATOR) if answer_event else {}
            result.append(
                {
                    **item,
                    "answer_event_id": answer_event.event_id if answer_event else "",
                    "answer_version": answer_version,
                    "answer_text": answer_view.get("answer_text", ""),
                }
            )
        return result

    def verify_integrity(self) -> bool:
        """Verify the durable event contract before rebuilding derived indexes."""
        if not self._events:
            raise TraceIntegrityError("Trace is empty")
        known_event_types = {item.value for item in TraceEventType}
        seen_ids: set[str] = set()
        seen_events: dict[str, TraceEvent] = {}
        seen_keys: set[str] = set()
        previous_hash = GENESIS_HASH
        canonical_runtime_epoch: int | None = None
        session_start_count = 0
        turn_max_answer_version: dict[str, int] = {}
        turn_runtime_epoch: dict[str, int] = {}
        logical_identities: dict[tuple[Any, ...], str] = {}

        def record_logical_identity(identity: tuple[Any, ...], event: TraceEvent) -> None:
            previous = logical_identities.get(identity)
            if previous is not None:
                raise TraceIntegrityError(
                    f"Duplicate logical identity {identity!r}: {previous} and {event.event_id}"
                )
            logical_identities[identity] = event.event_id

        for expected_sequence, event in enumerate(self._events, start=1):
            if event.schema_version != TRACE_SCHEMA_VERSION:
                raise TraceIntegrityError(f"Unsupported trace schema at {event.event_id}: {event.schema_version}")
            if event.payload_schema_version != PAYLOAD_SCHEMA_VERSION:
                raise TraceIntegrityError(
                    f"Unsupported payload schema at {event.event_id}: {event.payload_schema_version}"
                )
            if event.event_type not in known_event_types:
                raise TraceIntegrityError(f"Unknown event type at {event.event_id}: {event.event_type}")
            if not event.event_id or not event.idempotency_key:
                raise TraceIntegrityError("Trace events require non-empty event and idempotency identities")
            if event.session_id != self.session_id:
                raise TraceIntegrityError(f"Event {event.event_id} belongs to another session")
            if event.sequence != expected_sequence:
                raise TraceIntegrityError(
                    f"Sequence mismatch at {event.event_id}: expected {expected_sequence}, got {event.sequence}"
                )
            if expected_sequence == 1:
                if event.event_type != TraceEventType.SESSION_STARTED.value:
                    raise TraceIntegrityError("Trace must begin with exactly one session_started genesis event")
                if event.causal_parent_ids or event.turn_id or event.answer_version != 0:
                    raise TraceIntegrityError("session_started genesis cannot have parents, turn, or answer version")
            if event.event_type == TraceEventType.SESSION_STARTED.value:
                session_start_count += 1
                if expected_sequence != 1:
                    raise TraceIntegrityError("session_started may only occur at sequence 1")
                canonical_runtime_epoch = event.runtime_epoch
            if event.answer_version < 0 or event.runtime_epoch < 0:
                raise TraceIntegrityError(f"Negative version/epoch at {event.event_id}")
            if event.event_type == TraceEventType.RUNTIME_EPOCH_ADVANCED.value:
                epoch_view = _view(event, TraceView.EVALUATOR)
                if event.turn_id or event.answer_version != 0 or len(event.causal_parent_ids) != 1:
                    raise TraceIntegrityError(f"Invalid runtime epoch event shape at {event.event_id}")
                if canonical_runtime_epoch is None:
                    raise TraceIntegrityError(f"Runtime epoch advanced before session genesis at {event.event_id}")
                try:
                    previous_epoch = int(epoch_view.get("previous_runtime_epoch", -1))
                    next_epoch = int(epoch_view.get("runtime_epoch", -1))
                except (TypeError, ValueError) as exc:
                    raise TraceIntegrityError(f"Malformed runtime epoch payload at {event.event_id}") from exc
                if (
                    previous_epoch != canonical_runtime_epoch
                    or next_epoch != event.runtime_epoch
                    or event.runtime_epoch <= canonical_runtime_epoch
                    or event.causal_parent_ids[0] != self._events[expected_sequence - 2].event_id
                ):
                    raise TraceIntegrityError(f"Invalid runtime epoch transition at {event.event_id}")
                canonical_runtime_epoch = event.runtime_epoch
            elif canonical_runtime_epoch is None or event.runtime_epoch != canonical_runtime_epoch:
                raise TraceIntegrityError(
                    f"Event {event.event_id} uses epoch {event.runtime_epoch}, expected {canonical_runtime_epoch}"
                )
            if event.event_id in seen_ids:
                raise TraceIntegrityError(f"Duplicate event id: {event.event_id}")
            if event.idempotency_key in seen_keys:
                raise TraceIntegrityError(f"Duplicate idempotency key: {event.idempotency_key}")
            parents = tuple(event.causal_parent_ids)
            if len(parents) != len(set(parents)):
                raise TraceIntegrityError(f"Duplicate causal parent at {event.event_id}")
            for parent_id in parents:
                if parent_id not in seen_ids:
                    raise TraceIntegrityError(
                        f"Unknown or non-prior causal parent {parent_id} at {event.event_id}"
                    )
            seen_ids.add(event.event_id)
            seen_keys.add(event.idempotency_key)
            if event.previous_event_hash != previous_hash:
                raise TraceIntegrityError(f"Hash-chain predecessor mismatch at {event.event_id}")
            expected_decision_hash = self._decision_hash(event.event_type, event.payload)
            if event.decision_hash != expected_decision_hash:
                raise TraceIntegrityError(f"Decision hash mismatch at {event.event_id}")
            expected_provenance_hash = self._provenance_hash(parents, event.payload)
            if event.provenance_hash != expected_provenance_hash:
                raise TraceIntegrityError(f"Provenance hash mismatch at {event.event_id}")
            payload_views = event.payload.get("views") if isinstance(event.payload, Mapping) else None
            if not isinstance(payload_views, Mapping):
                raise TraceIntegrityError(f"Event payload views must be an object at {event.event_id}")
            try:
                expected_safe_payload, _ = _safe_views(payload_views)
                expected_redaction = _redaction_metadata_for_sanitized_views(payload_views)
            except TraceError as exc:
                raise TraceIntegrityError(f"Invalid/redaction-unsafe payload at {event.event_id}") from exc
            if _canonical(_thaw_value(expected_safe_payload)) != _canonical(_thaw_value(event.payload)):
                raise TraceIntegrityError(f"Payload is not canonically redacted at {event.event_id}")
            if _canonical(_thaw_value(expected_redaction)) != _canonical(_thaw_value(event.redaction)):
                raise TraceIntegrityError(f"Redaction metadata mismatch at {event.event_id}")
            is_rejection_diagnostic = (
                event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value
                and bool(_view(event, TraceView.EVALUATOR).get("candidate_event_type"))
            )
            if event.event_type not in {
                TraceEventType.SESSION_STARTED.value,
                TraceEventType.RUNTIME_EPOCH_ADVANCED.value,
                TraceEventType.REPORT_CLAIM_EMITTED.value,
                TraceEventType.FINAL_EVALUATION_COMPLETED.value,
            } and not is_rejection_diagnostic:
                if not event.turn_id or event.answer_version < 1:
                    raise TraceIntegrityError(f"Canonical turn event has invalid turn/version at {event.event_id}")
                previous_version = turn_max_answer_version.get(event.turn_id, 0)
                if event.answer_version < previous_version or event.answer_version > previous_version + 1:
                    raise TraceIntegrityError(f"Answer version gap/regression at {event.event_id}")
                turn_max_answer_version[event.turn_id] = max(previous_version, event.answer_version)
                prior_epoch = turn_runtime_epoch.setdefault(event.turn_id, event.runtime_epoch)
                if prior_epoch != event.runtime_epoch:
                    raise TraceIntegrityError(f"Turn crosses runtime epochs at {event.event_id}")
            elif is_rejection_diagnostic:
                diagnostic_view = _view(event, TraceView.EVALUATOR)
                if diagnostic_view.get("validation_status") != "rejected":
                    raise TraceIntegrityError(f"Validation diagnostic must be rejected at {event.event_id}")
                if event.turn_id and event.answer_version > turn_max_answer_version.get(event.turn_id, 0):
                    raise TraceIntegrityError(f"Validation diagnostic advances answer version at {event.event_id}")
            if event.event_type in {
                TraceEventType.QUESTION_MATERIALIZED.value,
                TraceEventType.QUESTION_PREPARED.value,
                TraceEventType.SPOKEN_QUESTION_COMMITTED.value,
                TraceEventType.ANSWER_RECEIVED.value,
                TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
                TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value,
                TraceEventType.ACTION_GRANT_SELECTED.value,
                TraceEventType.EVIDENCE_STATE_UPDATED.value,
            } or (
                event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value
                and not is_rejection_diagnostic
            ):
                record_logical_identity(
                    (event.event_type, event.turn_id, event.answer_version),
                    event,
                )
            elif event.event_type in {
                TraceEventType.QUESTION_DELIVERY_STARTED.value,
                TraceEventType.PLAYBACK_ACKNOWLEDGED.value,
                TraceEventType.DELIVERY_FAILED.value,
            }:
                attempt = str(_view(event, TraceView.EVALUATOR).get("delivery_attempt_id") or "").strip()
                if not attempt:
                    raise TraceIntegrityError(f"Delivery event requires an attempt id at {event.event_id}")
                record_logical_identity(
                    (event.event_type, event.turn_id, event.answer_version, attempt),
                    event,
                )
            elif event.event_type == TraceEventType.REPORT_CLAIM_EMITTED.value:
                claim_id = str(_view(event, TraceView.EVALUATOR).get("claim_id") or "").strip()
                if not claim_id:
                    raise TraceIntegrityError(f"Report claim requires a claim id at {event.event_id}")
                record_logical_identity((event.event_type, claim_id), event)
            elif event.event_type == TraceEventType.FINAL_EVALUATION_COMPLETED.value:
                record_logical_identity((event.event_type,), event)
            self._verify_import_event_semantics(event, seen_events)
            body = event.to_record()
            supplied_hash = body.pop("event_hash")
            expected_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
            if supplied_hash != expected_hash:
                raise TraceIntegrityError(f"Event hash mismatch at {event.event_id}")
            seen_events[event.event_id] = event
            previous_hash = event.event_hash
        if session_start_count != 1:
            raise TraceIntegrityError("Trace must contain exactly one session_started genesis event")
        if canonical_runtime_epoch is None:
            raise TraceIntegrityError("Trace has no canonical runtime epoch")
        self._authoritative = True
        self._integrity_verified = True
        return True

    def _verify_import_event_semantics(
        self,
        event: TraceEvent,
        seen_events: Mapping[str, TraceEvent],
    ) -> None:
        """Verify typed causal lineage that hashes alone cannot establish."""

        parents = tuple(event.causal_parent_ids)
        evaluator = _view(event, TraceView.EVALUATOR)

        if event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value:
            validation_statuses = tuple(
                _view(event, view).get("validation_status")
                for view in (TraceView.INTERVIEWER, TraceView.EVALUATOR, TraceView.OPERATOR)
            )
            if not (
                validation_statuses[0] == validation_statuses[1] == validation_statuses[2]
            ):
                raise TraceIntegrityError(
                    f"Validation status disagrees across views at {event.event_id}"
                )

        def parent_event(
            reference_id: str,
            expected_type: TraceEventType,
            *,
            same_scope: bool = True,
        ) -> TraceEvent:
            reference = str(reference_id or "").strip()
            if reference not in parents:
                raise TraceIntegrityError(f"{reference} is not a parent of {event.event_id}")
            try:
                parent = seen_events[reference]
            except KeyError as exc:
                raise TraceIntegrityError(f"Unknown parent {reference} at {event.event_id}") from exc
            if parent.event_type != expected_type.value:
                raise TraceIntegrityError(
                    f"{event.event_id} parent {reference} is {parent.event_type}, expected {expected_type.value}"
                )
            if same_scope and (parent.turn_id != event.turn_id or parent.answer_version != event.answer_version):
                raise TraceIntegrityError(f"{event.event_id} parent {reference} crosses turn/version scope")
            return parent

        def refs_from_payload(
            field_name: str,
            *,
            expected_type: TraceEventType | None = None,
        ) -> tuple[str, ...]:
            raw_refs = evaluator.get(field_name)
            if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, Sequence):
                raise TraceIntegrityError(f"{field_name} must be an array at {event.event_id}")
            refs = tuple(str(item or "").strip() for item in raw_refs)
            if any(not ref for ref in refs) or len(refs) != len(set(refs)):
                raise TraceIntegrityError(f"{field_name} contains empty/duplicate ids at {event.event_id}")
            for reference in refs:
                try:
                    referenced = seen_events[reference]
                except KeyError as exc:
                    raise TraceIntegrityError(f"{field_name} cites unknown/future event at {event.event_id}") from exc
                if expected_type is not None and referenced.event_type != expected_type.value:
                    raise TraceIntegrityError(
                        f"{field_name} cites {referenced.event_type}, expected {expected_type.value} at {event.event_id}"
                    )
            return refs

        def latest_prior_spoken_question_id() -> str:
            for prior_event in reversed(tuple(seen_events.values())):
                if prior_event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value:
                    return prior_event.event_id
            return ""

        def require_immediate_prior_spoken_question(field_name: str) -> str:
            supplied = str(evaluator.get(field_name) or "").strip()
            expected = latest_prior_spoken_question_id()
            if supplied != expected:
                raise TraceIntegrityError(
                    f"{event.event_type} {field_name} is not the immediately prior spoken question "
                    f"at {event.event_id}"
                )
            if supplied:
                parent_event(supplied, TraceEventType.SPOKEN_QUESTION_COMMITTED, same_scope=False)
            return supplied

        def require_delivery_attempt_exclusive() -> None:
            """ACK and failure are mutually exclusive for one delivery attempt."""
            attempt = str(evaluator.get("delivery_attempt_id") or "").strip()
            if not attempt:
                return
            opposite_type = (
                TraceEventType.DELIVERY_FAILED.value
                if event.event_type == TraceEventType.PLAYBACK_ACKNOWLEDGED.value
                else TraceEventType.PLAYBACK_ACKNOWLEDGED.value
            )
            for prior_event in seen_events.values():
                if prior_event.event_type != opposite_type:
                    continue
                prior_view = _view(prior_event, TraceView.EVALUATOR)
                if (
                    prior_event.turn_id == event.turn_id
                    and prior_event.answer_version == event.answer_version
                    and str(prior_view.get("delivery_attempt_id") or "").strip() == attempt
                ):
                    raise TraceIntegrityError(
                        f"Delivery attempt {attempt} has mutually exclusive ACK/failure events"
                    )

        if event.event_type == TraceEventType.QUESTION_MATERIALIZED.value:
            if not str(evaluator.get("question_id") or "").strip() or not str(evaluator.get("question_text") or "").strip():
                raise TraceIntegrityError(f"Question materialization lacks exact question identity/text at {event.event_id}")
            validation_candidates = [
                seen_events[parent_id]
                for parent_id in parents
                if seen_events[parent_id].event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value
                and not _view(seen_events[parent_id], TraceView.EVALUATOR).get("candidate_event_type")
            ]
            if len(validation_candidates) != 1:
                raise TraceIntegrityError(f"Question materialization must have one accepted validation parent at {event.event_id}")
            validation = validation_candidates[0]
            validation_view = _view(validation, TraceView.EVALUATOR)
            if (
                validation_view.get("validation_status") != "accepted"
                or validation_view.get("visible_route_commit_allowed") is not True
            ):
                raise TraceIntegrityError(
                    f"Question materialization is based on a validation that cannot authorize visible commit "
                    f"at {event.event_id}"
                )
            materialized_refs = refs_from_payload("source_evidence_event_ids")
            for field_name in ("source_opportunity_id", "prior_spoken_question_event_id", "action_grant_event_id"):
                if evaluator.get(field_name, "") != validation_view.get(field_name, ""):
                    raise TraceIntegrityError(f"Materialization {field_name} disagrees with validation at {event.event_id}")
            action_id = str(evaluator.get("action_grant_event_id") or "")
            if action_id:
                action = parent_event(action_id, TraceEventType.ACTION_GRANT_SELECTED)
                action_view = _view(action, TraceView.EVALUATOR)
                if action_view.get("opportunity_id") != evaluator.get("source_opportunity_id"):
                    raise TraceIntegrityError(f"Materialization opportunity disagrees with action grant at {event.event_id}")
                if tuple(action_view.get("source_evidence_event_ids") or ()) != materialized_refs:
                    raise TraceIntegrityError(f"Materialization evidence disagrees with action grant at {event.event_id}")
            prior_id = str(evaluator.get("prior_spoken_question_event_id") or "")
            require_immediate_prior_spoken_question("prior_spoken_question_event_id")
            expected_parents = tuple(
                item
                for item in (validation.event_id, action_id, prior_id, *materialized_refs)
                if item
            )
            if parents != expected_parents:
                raise TraceIntegrityError(f"Materialization parents do not match payload at {event.event_id}")
        elif event.event_type == TraceEventType.QUESTION_PREPARED.value:
            materialized_id = str(evaluator.get("materialized_event_id") or "")
            if len(parents) != 1:
                raise TraceIntegrityError(f"Question preparation must have one parent at {event.event_id}")
            materialized = parent_event(materialized_id, TraceEventType.QUESTION_MATERIALIZED)
            materialized_view = _view(materialized, TraceView.EVALUATOR)
            for field_name in ("question_id", "source_opportunity_id", "prior_spoken_question_event_id"):
                if evaluator.get(field_name, "") != materialized_view.get(field_name, ""):
                    raise TraceIntegrityError(f"Prepared {field_name} mismatch at {event.event_id}")
            if refs_from_payload("source_evidence_event_ids") != tuple(materialized_view.get("source_evidence_event_ids") or ()):
                raise TraceIntegrityError(f"Prepared evidence mismatch at {event.event_id}")
        elif event.event_type == TraceEventType.QUESTION_DELIVERY_STARTED.value:
            prepared_id = str(evaluator.get("question_prepared_event_id") or "")
            if len(parents) != 1:
                raise TraceIntegrityError(f"Delivery start must have one parent at {event.event_id}")
            parent_event(prepared_id, TraceEventType.QUESTION_PREPARED)
            if not str(evaluator.get("delivery_attempt_id") or "").strip():
                raise TraceIntegrityError(f"Delivery start has no attempt id at {event.event_id}")
        elif event.event_type in {
            TraceEventType.PLAYBACK_ACKNOWLEDGED.value,
            TraceEventType.DELIVERY_FAILED.value,
        }:
            if len(parents) != 1:
                raise TraceIntegrityError(f"{event.event_type} must have one delivery parent at {event.event_id}")
            started = parent_event(parents[0], TraceEventType.QUESTION_DELIVERY_STARTED)
            attempt = str(evaluator.get("delivery_attempt_id") or "")
            started_attempt = str(_view(started, TraceView.EVALUATOR).get("delivery_attempt_id") or "")
            if not attempt or attempt != started_attempt:
                raise TraceIntegrityError(f"Delivery attempt mismatch at {event.event_id}")
            require_delivery_attempt_exclusive()
            if event.event_type == TraceEventType.PLAYBACK_ACKNOWLEDGED.value:
                actor_view = _view(event, TraceView.ACTOR)
                if (
                    evaluator.get("client_ack") != PlaybackAckStatus.COMPLETED.value
                    or evaluator.get("acknowledged") is not True
                    or actor_view.get("delivery_attempt_id") != attempt
                    or actor_view.get("acknowledged") is not True
                ):
                    raise TraceIntegrityError(f"Playback acknowledgement is not completed at {event.event_id}")
            elif evaluator.get("delivery_failed") is not True or _view(event, TraceView.ACTOR).get("delivery_failed") is not True:
                raise TraceIntegrityError(f"Delivery failure is not marked failed at {event.event_id}")
        elif event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value:
            materialized_id = str(evaluator.get("question_materialized_event_id") or "")
            ack_id = str(evaluator.get("playback_ack_event_id") or "")
            if parents != (materialized_id, ack_id):
                raise TraceIntegrityError(f"Spoken question parents do not match payload at {event.event_id}")
            materialized = parent_event(materialized_id, TraceEventType.QUESTION_MATERIALIZED)
            ack = parent_event(ack_id, TraceEventType.PLAYBACK_ACKNOWLEDGED)
            if evaluator.get("delivery_attempt_id") != _view(ack, TraceView.EVALUATOR).get("delivery_attempt_id"):
                raise TraceIntegrityError(f"Spoken question ACK attempt mismatch at {event.event_id}")
            materialized_view = _view(materialized, TraceView.EVALUATOR)
            for field_name in ("question_id", "question_text", "source_opportunity_id", "prior_spoken_question_event_id"):
                if evaluator.get(field_name, "") != materialized_view.get(field_name, ""):
                    raise TraceIntegrityError(f"Spoken {field_name} mismatch at {event.event_id}")
            if refs_from_payload("source_evidence_event_ids") != tuple(materialized_view.get("source_evidence_event_ids") or ()):
                raise TraceIntegrityError(f"Spoken evidence mismatch at {event.event_id}")
        elif event.event_type == TraceEventType.ANSWER_RECEIVED.value:
            spoken_id = str(evaluator.get("spoken_question_event_id") or "")
            if parents != (spoken_id,):
                raise TraceIntegrityError(f"Answer parent does not match payload at {event.event_id}")
            parent_event(spoken_id, TraceEventType.SPOKEN_QUESTION_COMMITTED)
            answer_text = evaluator.get("answer_text")
            if answer_text is not None and str(evaluator.get("answer_text_hash") or "") != _sha256(str(answer_text).strip()):
                raise TraceIntegrityError(f"Answer text hash mismatch at {event.event_id}")
        elif event.event_type == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value:
            answer_id = str(evaluator.get("answer_event_id") or "")
            if parents != (answer_id,):
                raise TraceIntegrityError(f"Semantic final parent does not match payload at {event.event_id}")
            parent_event(answer_id, TraceEventType.ANSWER_RECEIVED)
            if evaluator.get("decision_immutable") is not True:
                raise TraceIntegrityError(f"Semantic final is not immutable at {event.event_id}")
        elif event.event_type == TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value:
            answer_id = str(evaluator.get("answer_event_id") or "")
            final_id = str(evaluator.get("shadow_of_event_id") or "")
            if parents != (answer_id, final_id):
                raise TraceIntegrityError(f"Semantic shadow parents do not match payload at {event.event_id}")
            parent_event(answer_id, TraceEventType.ANSWER_RECEIVED)
            parent_event(final_id, TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED)
            if evaluator.get("does_not_overwrite_final") is not True:
                raise TraceIntegrityError(f"Semantic shadow is not non-overwriting at {event.event_id}")
        elif event.event_type == TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value:
            semantic_id = str(evaluator.get("semantic_event_id") or "")
            if parents != (semantic_id,):
                raise TraceIntegrityError(f"Opportunity inventory parent does not match payload at {event.event_id}")
            parent_event(semantic_id, TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED)
            try:
                normalized_admitted = self._normalize_opportunities(
                    evaluator.get("admitted_candidates"),
                    admitted=True,
                    known_events=seen_events,
                )
                normalized_excluded = self._normalize_opportunities(
                    evaluator.get("excluded_candidates"),
                    admitted=False,
                    known_events=seen_events,
                )
            except TraceError as exc:
                raise TraceIntegrityError(
                    f"Opportunity inventory normalization failed at {event.event_id}"
                ) from exc
            all_ids = [
                item["opportunity_id"]
                for item in [*normalized_admitted, *normalized_excluded]
            ]
            if len(all_ids) != len(set(all_ids)):
                raise TraceIntegrityError(
                    f"Opportunity ids are not unique at {event.event_id}"
                )
            if _canonical(normalized_admitted) != _canonical(evaluator.get("admitted_candidates")):
                raise TraceIntegrityError(
                    f"Admitted opportunity inventory is not canonically normalized at {event.event_id}"
                )
            if _canonical(normalized_excluded) != _canonical(evaluator.get("excluded_candidates")):
                raise TraceIntegrityError(
                    f"Excluded opportunity inventory is not canonically normalized at {event.event_id}"
                )
        elif event.event_type == TraceEventType.ACTION_GRANT_SELECTED.value:
            inventory_id = str(evaluator.get("opportunity_inventory_event_id") or "")
            prior_id = str(evaluator.get("prior_spoken_question_event_id") or "")
            grant_refs = refs_from_payload("source_evidence_event_ids")
            if parents != (inventory_id, prior_id, *grant_refs):
                raise TraceIntegrityError(f"Action grant parents do not match payload at {event.event_id}")
            parent_event(inventory_id, TraceEventType.OPPORTUNITY_INVENTORY_COMPILED, same_scope=False)
            require_immediate_prior_spoken_question("prior_spoken_question_event_id")
            parent_event(prior_id, TraceEventType.SPOKEN_QUESTION_COMMITTED, same_scope=False)
            inventory_view = _view(seen_events[inventory_id], TraceView.EVALUATOR)
            candidates = inventory_view.get("admitted_candidates") or ()
            candidate = next(
                (item for item in candidates if item.get("opportunity_id") == evaluator.get("opportunity_id")),
                None,
            )
            if candidate is None or tuple(candidate.get("evidence_event_ids") or ()) != grant_refs:
                raise TraceIntegrityError(f"Action grant opportunity/evidence mismatch at {event.event_id}")
        elif event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value:
            if evaluator.get("candidate_event_type"):
                return
            action_id = str(evaluator.get("action_grant_event_id") or "")
            prior_id = str(evaluator.get("prior_spoken_question_event_id") or "")
            validation_refs = refs_from_payload("source_evidence_event_ids")
            expected_parents = tuple(
                item for item in (action_id, prior_id, *validation_refs) if item
            )
            if parents != expected_parents:
                raise TraceIntegrityError(f"Validation parents do not match payload at {event.event_id}")
            if evaluator.get("validation_status") != "accepted":
                raise TraceIntegrityError(f"Canonical validation is not accepted at {event.event_id}")
            visible_route_commit_allowed = evaluator.get("visible_route_commit_allowed")
            if not isinstance(visible_route_commit_allowed, bool):
                raise TraceIntegrityError(
                    f"Validation visible-route authorization must be boolean at {event.event_id}"
                )
            for view_name in (TraceView.INTERVIEWER, TraceView.OPERATOR):
                if _view(event, view_name).get("visible_route_commit_allowed") != visible_route_commit_allowed:
                    raise TraceIntegrityError(
                        f"Validation visible-route authorization disagrees across views at {event.event_id}"
                    )
            if action_id:
                action = parent_event(action_id, TraceEventType.ACTION_GRANT_SELECTED)
                action_view = _view(action, TraceView.EVALUATOR)
                for field_name in (
                    "source_opportunity_id",
                    "source_evidence_event_ids",
                    "prior_spoken_question_event_id",
                ):
                    expected = action_view.get(
                        "opportunity_id" if field_name == "source_opportunity_id" else field_name
                    )
                    if evaluator.get(field_name) != expected:
                        raise TraceIntegrityError(
                            f"Validation {field_name} disagrees with action grant at {event.event_id}"
                        )
            require_immediate_prior_spoken_question("prior_spoken_question_event_id")
            if prior_id:
                parent_event(prior_id, TraceEventType.SPOKEN_QUESTION_COMMITTED, same_scope=False)
        elif event.event_type == TraceEventType.EVIDENCE_STATE_UPDATED.value:
            evidence_refs = refs_from_payload("source_event_ids")
            if evidence_refs != parents:
                raise TraceIntegrityError(f"Evidence parents do not match payload at {event.event_id}")
            parent_event(str(evaluator.get("semantic_event_id") or ""), TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED)
            parent_event(str(evaluator.get("opportunity_inventory_event_id") or ""), TraceEventType.OPPORTUNITY_INVENTORY_COMPILED)
        elif event.event_type == TraceEventType.REPORT_CLAIM_EMITTED.value:
            report_refs = refs_from_payload(
                "source_evidence_event_ids",
                expected_type=TraceEventType.EVIDENCE_STATE_UPDATED,
            )
            if report_refs != parents:
                raise TraceIntegrityError(f"Report claim cites non-evidence parents at {event.event_id}")
        elif event.event_type == TraceEventType.FINAL_EVALUATION_COMPLETED.value:
            claim_refs = refs_from_payload(
                "report_claim_event_ids",
                expected_type=TraceEventType.REPORT_CLAIM_EMITTED,
            )
            evidence_refs = refs_from_payload(
                "evidence_event_ids",
                expected_type=TraceEventType.EVIDENCE_STATE_UPDATED,
            )
            if _dedupe_ids([*claim_refs, *evidence_refs]) != parents:
                raise TraceIntegrityError(f"Final evaluation parents do not match lineage at {event.event_id}")
            evidence_set = set(evidence_refs)
            for claim_id in claim_refs:
                claim_sources = tuple(
                    str(item or "").strip()
                    for item in _view(seen_events[claim_id], TraceView.EVALUATOR).get("source_evidence_event_ids", ())
                )
                if not set(claim_sources).issubset(evidence_set):
                    raise TraceIntegrityError(f"Final evaluation cites unrelated evidence at {event.event_id}")

    def _rebuild_indexes(self) -> None:
        self._session_started_event_id = ""
        self._last_spoken_question_event_id = ""
        self._final_evaluation_event_id = ""
        self._turns = {}
        self._runtime_epoch = self._events[0].runtime_epoch if self._events else 0
        for event in self._events:
            if event.event_type == TraceEventType.SESSION_STARTED.value:
                self._session_started_event_id = event.event_id
            elif event.event_type == TraceEventType.RUNTIME_EPOCH_ADVANCED.value:
                self._runtime_epoch = event.runtime_epoch
            elif (
                event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value
                and _view(event, TraceView.EVALUATOR).get("candidate_event_type")
            ):
                # Rejected/stale diagnostics are canonical telemetry, not a
                # visible route transition.  They must not create a ghost
                # _TurnLedger during replay.
                continue
            elif event.turn_id:
                ledger = self._turns.setdefault(
                    event.turn_id,
                    _TurnLedger(runtime_epoch=event.runtime_epoch, current_answer_version=max(event.answer_version, 1)),
                )
                ledger.current_answer_version = max(ledger.current_answer_version, event.answer_version)
                if event.event_type == TraceEventType.ACTION_GRANT_SELECTED.value:
                    view = _view(event, TraceView.EVALUATOR)
                    ledger.action_grant_event_id = event.event_id
                    ledger.source_opportunity_id = str(view.get("opportunity_id") or "")
                    ledger.source_evidence_event_ids = tuple(view.get("source_evidence_event_ids") or [])
                    ledger.prior_spoken_question_event_id = str(view.get("prior_spoken_question_event_id") or "")
                elif event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value:
                    view = _view(event, TraceView.EVALUATOR)
                    # Stale/concurrent-operation diagnostics are validation
                    # evidence, not a replacement for the already accepted
                    # visible-route validation.  Replaying one must not make
                    # an earlier spoken route look rejected.
                    if not view.get("candidate_event_type"):
                        ledger.validation_event_id = event.event_id
                        ledger.validation_status = str(view.get("validation_status") or "")
                        ledger.visible_route_commit_allowed = bool(view.get("visible_route_commit_allowed"))
                elif event.event_type == TraceEventType.QUESTION_MATERIALIZED.value:
                    ledger.materialized_event_id = event.event_id
                    view = _view(event, TraceView.EVALUATOR)
                    ledger.question_id = str(view.get("question_id") or "")
                    ledger.source_opportunity_id = str(view.get("source_opportunity_id") or ledger.source_opportunity_id)
                    ledger.source_evidence_event_ids = tuple(view.get("source_evidence_event_ids") or ledger.source_evidence_event_ids)
                    ledger.prior_spoken_question_event_id = str(view.get("prior_spoken_question_event_id") or ledger.prior_spoken_question_event_id)
                elif event.event_type == TraceEventType.QUESTION_PREPARED.value:
                    ledger.prepared_event_id = event.event_id
                elif event.event_type == TraceEventType.QUESTION_DELIVERY_STARTED.value:
                    view = _view(event, TraceView.ACTOR)
                    attempt = str(view.get("delivery_attempt_id") or "")
                    if attempt:
                        ledger.delivery_started_by_attempt[attempt] = event.event_id
                elif event.event_type == TraceEventType.PLAYBACK_ACKNOWLEDGED.value:
                    view = _view(event, TraceView.ACTOR)
                    attempt = str(view.get("delivery_attempt_id") or "")
                    if attempt:
                        ledger.playback_ack_by_attempt[attempt] = event.event_id
                elif event.event_type == TraceEventType.DELIVERY_FAILED.value:
                    view = _view(event, TraceView.ACTOR)
                    attempt = str(view.get("delivery_attempt_id") or "")
                    if attempt:
                        ledger.delivery_failed_attempts.add(attempt)
                        ledger.delivery_failed_event_by_attempt[attempt] = event.event_id
                elif event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value:
                    ledger.spoken_question_event_id = event.event_id
                    self._last_spoken_question_event_id = event.event_id
                elif event.event_type == TraceEventType.ANSWER_RECEIVED.value:
                    ledger.answer_event_by_version[event.answer_version] = event.event_id
                elif event.event_type == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value:
                    ledger.semantic_final_by_version[event.answer_version] = event.event_id
                elif event.event_type == TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value:
                    ledger.shadow_event_ids_by_version.setdefault(event.answer_version, []).append(event.event_id)
                elif event.event_type == TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value:
                    ledger.inventory_event_by_version[event.answer_version] = event.event_id
                elif event.event_type == TraceEventType.EVIDENCE_STATE_UPDATED.value:
                    ledger.evidence_event_by_version[event.answer_version] = event.event_id
            if event.event_type == TraceEventType.FINAL_EVALUATION_COMPLETED.value:
                self._final_evaluation_event_id = event.event_id


def _view_payload_for_hash(payload: Mapping[str, Any], view: TraceView) -> Any:
    views = payload.get("views") if isinstance(payload, Mapping) else {}
    if isinstance(views, Mapping):
        return views.get(view.value, {})
    return {}


def _source_refs(payload: Mapping[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                child = str(child_key)
                if child.endswith("_event_id") and isinstance(child_value, str):
                    found.append(child_value)
                elif child.endswith("_event_ids") and isinstance(child_value, Sequence) and not isinstance(child_value, str):
                    found.extend(str(item) for item in child_value)
                walk(child_value, child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                walk(item, key)

    walk(payload)
    return list(_dedupe_ids(found))


__all__ = [
    "InterviewTraceV1",
    "PAYLOAD_SCHEMA_VERSION",
    "PlaybackAckStatus",
    "TraceError",
    "TraceEvent",
    "TraceEventType",
    "TraceConflictError",
    "TraceImmutableDecisionError",
    "TraceInvariantError",
    "TraceIntegrityError",
    "TraceReceipt",
    "TraceReferenceError",
    "TraceStaleError",
    "TraceView",
    "TRACE_SCHEMA_VERSION",
]
