"""Truth-bounded candidate actor runtime for the frozen CandidateWorldV1 trial.

This module is deliberately isolated from the live interview runtime.  A
trusted test harness creates a turn projection from an explicit fact grant;
the actor generator receives only that projection, the exact current
candidate-visible question, candidate-visible history, and a bounded behavior
state.  The generator is never handed the actor-private store or evaluator
material.

Generation and validation are separate phases.  A response that fails
validation is returned as a rejected, non-canonical artifact with an empty
canonical ``answer_text``.  It is never promoted to candidate speech.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence


WORLD_DIR = Path(__file__).resolve().parents[1] / "data" / "candidate_worlds" / "luna_trial_v1"
ACTOR_PRIVATE_DIR = WORLD_DIR / "projections" / "actor_private"
ACTOR_PROJECTION_DIR = WORLD_DIR / "projections" / "actor"

PROMPT_SCHEMA_VERSION = "candidate_actor_prompt_v1"
RESPONSE_SCHEMA_VERSION = "candidate_actor_response_v1"
REVIEW_PACKET_SCHEMA_VERSION = "candidate_actor_review_packet_v1"

FACT_ID_RE = re.compile(r"^fact_[a-z0-9_]+$")
FACT_MARKER_RE = re.compile(r"(?:\bfact_[a-z0-9_]+\b|\[\s*(?:fact|cite|citation)[^\]]*\])", re.I)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.I)

BOUNDARY_ACTIONS = {
    "none",
    "ownership_boundary",
    "protected_boundary",
    "honest_gap",
    "memory_limit",
    "question_clarification",
}
UNCERTAINTY_KINDS = {
    "none",
    "memory_limit",
    "scope_limit",
    "causal_limit",
    "protected_limit",
    "unknown",
    "ambiguous",
    "unavailable",
}
FATIGUE_PHASES = {"early", "middle", "late"}
OWNERSHIP_STATUSES = {"owned", "partial", "team_owned", "not_owned", "protected", "ambiguous"}

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "did", "do",
    "for", "from", "had", "has", "have", "he", "her", "his", "how", "i", "if", "in",
    "is", "it", "its", "me", "my", "no", "not", "of", "on", "or", "our", "she", "so",
    "that", "the", "their", "them", "there", "they", "this", "to", "was", "we", "were",
    "what", "when", "which", "who", "why", "with", "you", "your", "yes", "just", "one",
}
_GENERIC_SUPPORT_TOKENS = {
    "work", "worked", "role", "part", "area", "thing", "result", "project", "feature",
    "system", "team", "process", "question", "answer", "details", "detail", "change",
    "changed", "used", "use", "made", "make", "did", "doing", "helped", "support",
}
_SOCIAL_ONLY_RE = re.compile(
    r"^(?:could you repeat(?: that)?|please repeat(?: that)?|i need a moment|give me a second|"
    r"let me think|sorry|thanks|thank you|i'm not sure where to start|which part matters|"
    r"can we move on|let's move on|i don't know)$",
    re.I,
)
_PERSONAL_OWNERSHIP_RE = re.compile(
    r"\b(?:i|we|my|our)\b.{0,48}\b(?:owned|own|built|designed|deployed|implemented|"
    r"architected|led|created|wrote|fixed|shipped|controlled|was responsible for)\b",
    re.I,
)
_POSITIVE_OWNERSHIP_RE = re.compile(
    r"\b(?:i|we|my|our)\b.{0,48}\b(?:owned|own|built|designed|deployed|implemented|"
    r"architected|led|created|wrote|fixed|shipped|controlled|responsible)\b",
    re.I,
)
_NEGATIVE_BOUNDARY_RE = re.compile(
    r"\b(?:did not|didn't|not|never|no|cannot|can't|couldn't|outside|unowned|"
    r"teammate|teammates|team|backend engineer|engineering|not mine)\b",
    re.I,
)
_BROAD_OWNERSHIP_RE = re.compile(
    r"\b(?:entire|whole|all|every|full|solely|single[- ]handed|end[- ]to[- ]end|"
    r"the (?:whole|entire|full) (?:system|platform|feature|project))\b",
    re.I,
)
_DISHONESTY_RE = re.compile(r"\b(?:i lied|i was dishonest|i deceived|fraud|fabricated|made it up)\b", re.I)
_INTERNAL_SPEECH_RE = re.compile(
    r"\b(?:evaluator(?:_hidden_truth)?|actor_private|move_family|move families|sufficiency|"
    r"hiring verdict|expected answer|gold answer|route_kind|disclosure_controller|"
    r"candidate_actor|fact_ids|schema internals|latent capability|grader|judge label)\b",
    re.I,
)


class CandidateActorError(ValueError):
    """Base error for malformed actor inputs or trusted grants."""


class DisclosureGrantError(CandidateActorError):
    """Raised when a trusted caller attempts an invalid fact grant."""


class ActorPromptError(CandidateActorError):
    """Raised when a prompt would violate actor isolation."""


class CandidateGenerator(Protocol):
    """Minimal generator interface; implementations receive only actor input."""

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None) -> Mapping[str, Any] | str:
        ...


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    if isinstance(value, bytes):
        data = value
    else:
        data = _json_bytes(value)
    return hashlib.sha256(data).hexdigest()


def _unique_ids(values: Iterable[str], label: str) -> list[str]:
    result = list(values)
    if any(not isinstance(value, str) or not FACT_ID_RE.fullmatch(value) for value in result):
        raise CandidateActorError(f"{label} contains an invalid fact ID")
    if len(result) != len(set(result)):
        raise CandidateActorError(f"{label} contains duplicate fact IDs")
    return sorted(result)


def _tokenize(value: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(value) if token.lower() not in _STOP_WORDS}


def _normalized(value: str) -> str:
    return " ".join(TOKEN_RE.findall(value.lower()))


def _contains_all_or_substantial(haystack: str, needle: str) -> bool:
    normalized_haystack = _normalized(haystack)
    normalized_needle = _normalized(needle)
    if not normalized_needle:
        return False
    if normalized_needle in normalized_haystack:
        return True
    needle_tokens = _tokenize(needle)
    if not needle_tokens:
        return True
    overlap = needle_tokens & _tokenize(haystack)
    distinctive_overlap = {token for token in overlap if token not in _GENERIC_SUPPORT_TOKENS and len(token) >= 4}
    if not distinctive_overlap and len(overlap) < min(2, len(needle_tokens)):
        return False
    required = 1 if len(needle_tokens) <= 3 else max(2, min(4, (len(needle_tokens) + 3) // 4))
    return len(overlap) >= required


def _literal_tokens(value: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?%?\b", value))


def _temporal_tokens(value: str) -> set[str]:
    return set(re.findall(
        r"\b(?:19|20)\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
        r"\b(?:before|after|during|later|earlier|first|last|next|previous|yesterday|today|tomorrow)\b",
        value.lower(),
    ))


def _key_names(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).lower()
            yield from _key_names(child)
    elif isinstance(value, list):
        for child in value:
            yield from _key_names(child)


def _assert_no_forbidden_keys(value: Any, *, label: str) -> None:
    forbidden_exact = {
        "evaluator_hidden_truth",
        "evaluator_only",
        "actor_private",
        "latent_capability_profile",
        "hiring_hypotheses",
        "acceptable_move_sets",
        "hard_invalid_moves",
        "evidence_sufficiency",
        "sufficiency_conditions",
        "move_families",
        "interviewer_strategy",
        "hiring_verdict",
        "expected_answer",
        "gold_answer",
    }
    found = sorted({key for key in _key_names(value) if key in forbidden_exact})
    if found:
        raise ActorPromptError(f"{label} contains forbidden actor-isolation keys: {found}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise CandidateActorError(f"projection not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateActorError(f"projection is not valid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise CandidateActorError(f"projection root must be an object: {path.name}")
    return value


def load_actor_private_projection(world_id: str) -> dict[str, Any]:
    """Load candidate-private truth for a trusted harness, never for a generator."""

    if not re.fullmatch(r"world_[a-z0-9_]+", world_id):
        raise CandidateActorError(f"invalid world ID: {world_id}")
    return _load_json(ACTOR_PRIVATE_DIR / f"{world_id}.json")


def load_actor_turn_projection(world_id: str) -> dict[str, Any]:
    """Load the frozen actor-visible baseline projection."""

    if not re.fullmatch(r"world_[a-z0-9_]+", world_id):
        raise CandidateActorError(f"invalid world ID: {world_id}")
    return _load_json(ACTOR_PROJECTION_DIR / f"{world_id}.json")


def _safe_turn_fact(fact: Mapping[str, Any], *, protected_summary: bool) -> dict[str, Any]:
    statement = fact.get("statement")
    ownership = fact.get("ownership")
    disclosure = fact.get("disclosure")
    if not isinstance(statement, Mapping) or not isinstance(ownership, Mapping) or not isinstance(disclosure, Mapping):
        raise DisclosureGrantError(f"fact {fact.get('fact_id', '<unknown>')} has malformed private shape")

    if protected_summary:
        statement_text = str(disclosure.get("allowed_summary", "")).strip()
        if not statement_text:
            raise DisclosureGrantError(f"protected fact {fact['fact_id']} has no safe summary")
        safe_disclosure = {
            "eligibility": "protected_summary",
            "prerequisite_fact_ids": list(disclosure.get("prerequisite_fact_ids", [])),
            "earliest_turn": disclosure.get("earliest_turn", 0),
            "reveal_trigger": disclosure.get("reveal_trigger", "Candidate states a boundary"),
            "candidate_can_volunteer": disclosure.get("candidate_can_volunteer", False),
            "allowed_summary": statement_text,
            "prohibited_expansion": ["Do not reveal protected values, identities, or exact confidential details."],
        }
        ownership_value = {
            "status": "protected",
            "scope": "Protected details; generic method or boundary may be discussed",
            "boundary_text": str(ownership.get("boundary_text", "Protected details remain unavailable.")),
            "owned_by": "Company, partners, or customers",
            "ownership_evidence_ids": [fact["fact_id"]],
        }
    else:
        statement_text = str(statement.get("text", "")).strip()
        safe_disclosure = _deepcopy(disclosure)
        ownership_value = _deepcopy(ownership)

    if not statement_text:
        raise DisclosureGrantError(f"fact {fact['fact_id']} has empty statement text")
    return {
        "fact_id": fact["fact_id"],
        "label": fact.get("label", fact["fact_id"]),
        "statement_text": statement_text,
        "category": fact.get("category", "unknown"),
        "ownership": ownership_value,
        "disclosure": safe_disclosure,
    }


def _validate_grant(
    private_projection: Mapping[str, Any],
    *,
    turn_number: int,
    already_revealed_fact_ids: Sequence[str],
    newly_granted_fact_ids: Sequence[str],
    authorized_safe_summary_fact_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(turn_number, int) or turn_number < 0:
        raise DisclosureGrantError("turn_number must be a non-negative integer")
    already = _unique_ids(already_revealed_fact_ids, "already_revealed_fact_ids")
    newly = _unique_ids(newly_granted_fact_ids, "newly_granted_fact_ids")
    safe = _unique_ids(authorized_safe_summary_fact_ids, "authorized_safe_summary_fact_ids")
    if set(already) & set(newly):
        raise DisclosureGrantError("newly granted facts overlap already revealed facts")

    raw_facts = private_projection.get("factual_truth")
    if not isinstance(raw_facts, list):
        raise DisclosureGrantError("actor-private projection has no factual_truth list")
    facts = {str(fact.get("fact_id")): fact for fact in raw_facts if isinstance(fact, Mapping)}
    requested = set(already) | set(newly)
    unknown = requested - set(facts)
    if unknown:
        raise DisclosureGrantError(f"unknown fact IDs: {sorted(unknown)}")
    if not set(safe).issubset(requested):
        raise DisclosureGrantError("safe-summary IDs must be part of the current grant")

    for fact_id in sorted(requested):
        fact = facts[fact_id]
        disclosure = fact.get("disclosure") if isinstance(fact, Mapping) else None
        if not isinstance(disclosure, Mapping):
            raise DisclosureGrantError(f"fact {fact_id} has no disclosure rule")
        eligibility = str(disclosure.get("eligibility", ""))
        if eligibility in {"unavailable", "unknown"}:
            raise DisclosureGrantError(f"fact {fact_id} is unavailable")
        if eligibility == "protected" and fact_id not in safe:
            raise DisclosureGrantError(f"protected fact {fact_id} requires an explicit safe-summary grant")
        if disclosure.get("earliest_turn", 0) > turn_number:
            raise DisclosureGrantError(f"fact {fact_id} is not available at turn {turn_number}")
        prerequisites = set(disclosure.get("prerequisite_fact_ids", []))
        if not prerequisites.issubset(set(already)):
            missing = sorted(prerequisites - set(already))
            raise DisclosureGrantError(f"fact {fact_id} is missing already-revealed prerequisites: {missing}")
        if fact_id in newly and eligibility not in {"eligible", "conditional", "protected"}:
            raise DisclosureGrantError(f"fact {fact_id} has unsupported eligibility {eligibility}")

    return facts, {"already": already, "newly": newly, "safe": safe}


def _sanitize_behavior_policy(_policy: Any, *, current_behavior: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return one derived behavior, never a recursively filtered policy tree.

    The frozen projection keeps authoring-time alternatives so the offline
    projection gates can inspect them.  A candidate runtime must not receive
    those alternatives: filtering fact IDs inside a recursive copy still
    leaks future response policies and fatigue phases.  The only accepted
    output is the current behavior selected by the trusted harness.
    """

    if current_behavior is None:
        current_behavior = {
            "behavior_mode": "baseline",
            "fatigue_phase": "early",
            "speaking_guidance": "Follow the supplied behavior mode.",
            "response_guidance": "Answer the current question at one bounded level; use only granted facts.",
            "correction_guidance": "Correct a prior claim when current granted facts support the correction.",
            "contradiction_guidance": "Reject an incorrect premise without accepting ungranted facts.",
        }
    allowed = {
        "behavior_mode",
        "fatigue_phase",
        "speaking_guidance",
        "response_guidance",
        "correction_guidance",
        "contradiction_guidance",
    }
    return {key: _deepcopy(current_behavior[key]) for key in allowed if key in current_behavior}


def _materialize_trusted_actor_turn_projection(
    world_id: str,
    *,
    turn_number: int,
    already_revealed_fact_ids: Sequence[str],
    newly_granted_fact_ids: Sequence[str],
    authorized_safe_summary_fact_ids: Sequence[str],
) -> dict[str, Any]:
    """Materialize a projection from state already resolved by the ledger.

    This is intentionally private.  It accepts the derived history only so a
    ledger can create an immutable reservation; callers cannot use it as a
    disclosure API.
    """

    private_projection = load_actor_private_projection(world_id)
    base_projection = load_actor_turn_projection(world_id)
    facts, grant = _validate_grant(
        private_projection,
        turn_number=turn_number,
        already_revealed_fact_ids=already_revealed_fact_ids,
        newly_granted_fact_ids=newly_granted_fact_ids,
        authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
    )
    granted_ids = set(grant["already"]) | set(grant["newly"])
    projection = _deepcopy(base_projection)
    projection["turn_context"] = {
        "turn_number": turn_number,
        "already_revealed_fact_ids": grant["already"],
        "newly_granted_fact_ids": grant["newly"],
        "granted_fact_ids": sorted(granted_ids),
        "controller_authority": "trusted_disclosure_controller_only",
        "question_semantics_used": False,
    }
    projection["granted_facts"] = [
        _safe_turn_fact(facts[fact_id], protected_summary=fact_id in set(grant["safe"]))
        for fact_id in sorted(granted_ids)
    ]
    # This is still an offline projection, but it must not carry the full
    # authoring policy tree into any downstream prompt accidentally.
    projection["behavior_policy"] = _sanitize_behavior_policy(projection.get("behavior_policy"))
    assert_safe_actor_turn_projection(projection)
    return projection


def build_trusted_actor_turn_projection(
    world_id: str,
    *,
    turn_number: int,
    requested_fact_ids: Sequence[str] = (),
    disclosure_ledger: "AppendOnlyDisclosureLedgerV1 | None" = None,
    request_kind: str = "interviewer",
    trigger_satisfied_fact_ids: Sequence[str] = (),
    prohibited_reveal_fact_ids: Sequence[str] = (),
    authorized_safe_summary_fact_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Materialize a safe actor turn through an actor-owned ledger.

    ``requested_fact_ids`` is only a request.  Prior history and the actual
    newly granted set come from ``disclosure_ledger``.  The old public shape
    accepted caller-supplied ``already_revealed_fact_ids`` and
    ``newly_granted_fact_ids``; those parameters are deliberately gone so a
    caller cannot inject or rewrite disclosure history.
    """
    if disclosure_ledger is None:
        raise DisclosureGrantError(
            "build_trusted_actor_turn_projection requires an actor-owned disclosure ledger; "
            "caller-supplied history is not supported"
        )
    if disclosure_ledger.world_id != world_id:
        raise DisclosureGrantError("disclosure ledger world does not match requested world")
    return disclosure_ledger.reserve_projection(
        turn_number=turn_number,
        requested_fact_ids=requested_fact_ids,
        request_kind=request_kind,
        trigger_satisfied_fact_ids=trigger_satisfied_fact_ids,
        prohibited_reveal_fact_ids=prohibited_reveal_fact_ids,
        authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
    )


@dataclass(frozen=True)
class CandidateVisibleTurnV1:
    """One turn of conversation that is visible to the candidate actor."""

    speaker: str
    text: str
    turn_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.speaker not in {"interviewer", "candidate"}:
            raise ActorPromptError("conversation speaker must be interviewer or candidate")
        if not isinstance(self.text, str):
            raise ActorPromptError("conversation text must be a string")
        output: dict[str, Any] = {"speaker": self.speaker, "text": self.text}
        if self.turn_number is not None:
            if not isinstance(self.turn_number, int) or self.turn_number < 0:
                raise ActorPromptError("conversation turn_number must be a non-negative integer")
            output["turn_number"] = self.turn_number
        return output


@dataclass(frozen=True)
class BehaviorStateV1:
    """Explicit, non-evaluative behavior and fatigue state."""

    fatigue_phase: str = "early"
    behavior_mode: str = "baseline"
    turn_number: int = 0
    repeated_question_count: int = 0
    protected_pressure_count: int = 0
    frustration_reasons: tuple[str, ...] = field(default_factory=tuple)
    speaking_guidance: str = ""
    response_guidance: str = ""
    correction_guidance: str = ""
    contradiction_guidance: str = ""

    def to_dict(self) -> dict[str, Any]:
        if self.fatigue_phase not in FATIGUE_PHASES:
            raise ActorPromptError(f"unknown fatigue phase: {self.fatigue_phase}")
        if not isinstance(self.behavior_mode, str) or not self.behavior_mode.strip():
            raise ActorPromptError("behavior_mode must be a non-empty string")
        if _INTERNAL_SPEECH_RE.search(self.behavior_mode):
            raise ActorPromptError("behavior_mode contains actor-internal labels")
        for name, value in (
            ("turn_number", self.turn_number),
            ("repeated_question_count", self.repeated_question_count),
            ("protected_pressure_count", self.protected_pressure_count),
        ):
            if not isinstance(value, int) or value < 0:
                raise ActorPromptError(f"{name} must be a non-negative integer")
        reasons = [str(reason) for reason in self.frustration_reasons]
        if any(_INTERNAL_SPEECH_RE.search(reason) for reason in reasons):
            raise ActorPromptError("frustration_reasons contain actor-internal labels")
        guidance_values = {
            "speaking_guidance": self.speaking_guidance,
            "response_guidance": self.response_guidance,
            "correction_guidance": self.correction_guidance,
            "contradiction_guidance": self.contradiction_guidance,
        }
        for name, guidance in guidance_values.items():
            if not isinstance(guidance, str):
                raise ActorPromptError(f"{name} must be a string")
            if _INTERNAL_SPEECH_RE.search(guidance) or FACT_MARKER_RE.search(guidance):
                raise ActorPromptError(f"{name} contains actor-internal labels or fact markers")
        return {
            "fatigue_phase": self.fatigue_phase,
            "behavior_mode": self.behavior_mode,
            "turn_number": self.turn_number,
            "repeated_question_count": self.repeated_question_count,
            "protected_pressure_count": self.protected_pressure_count,
            "frustration_reasons": reasons,
            "speaking_guidance": self.speaking_guidance,
            "response_guidance": self.response_guidance,
            "correction_guidance": self.correction_guidance,
            "contradiction_guidance": self.contradiction_guidance,
        }


def _behavior_state(value: BehaviorStateV1 | Mapping[str, Any] | None) -> BehaviorStateV1:
    if value is None:
        return BehaviorStateV1()
    if isinstance(value, BehaviorStateV1):
        value.to_dict()
        return value
    if not isinstance(value, Mapping):
        raise ActorPromptError("behavior_state must be an object")
    allowed = {
        "fatigue_phase",
        "behavior_mode",
        "turn_number",
        "repeated_question_count",
        "protected_pressure_count",
        "frustration_reasons",
        "speaking_guidance",
        "response_guidance",
        "correction_guidance",
        "contradiction_guidance",
    }
    extra = set(value) - allowed
    if extra:
        raise ActorPromptError(f"behavior_state contains unsupported keys: {sorted(extra)}")
    reasons = value.get("frustration_reasons", ())
    if isinstance(reasons, str) or not isinstance(reasons, (list, tuple)):
        raise ActorPromptError("frustration_reasons must be an array")
    return BehaviorStateV1(
        fatigue_phase=str(value.get("fatigue_phase", "early")),
        behavior_mode=str(value.get("behavior_mode", "baseline")),
        turn_number=int(value.get("turn_number", 0)),
        repeated_question_count=int(value.get("repeated_question_count", 0)),
        protected_pressure_count=int(value.get("protected_pressure_count", 0)),
        frustration_reasons=tuple(str(reason) for reason in reasons),
        speaking_guidance=str(value.get("speaking_guidance", "")),
        response_guidance=str(value.get("response_guidance", "")),
        correction_guidance=str(value.get("correction_guidance", "")),
        contradiction_guidance=str(value.get("contradiction_guidance", "")),
    )


def _conversation(value: Sequence[CandidateVisibleTurnV1 | Mapping[str, Any]] | None) -> tuple[CandidateVisibleTurnV1, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise ActorPromptError("prior conversation must be an array")
    result: list[CandidateVisibleTurnV1] = []
    for index, item in enumerate(value):
        if isinstance(item, CandidateVisibleTurnV1):
            turn = item
        elif isinstance(item, Mapping):
            allowed = {"speaker", "text", "turn_number"}
            extra = set(item) - allowed
            if extra:
                raise ActorPromptError(f"conversation[{index}] contains unsupported keys: {sorted(extra)}")
            if "speaker" not in item or "text" not in item:
                raise ActorPromptError(f"conversation[{index}] requires speaker and text")
            turn = CandidateVisibleTurnV1(
                speaker=str(item["speaker"]),
                text=item["text"],
                turn_number=item.get("turn_number"),
            )
        else:
            raise ActorPromptError(f"conversation[{index}] must be an object")
        turn.to_dict()
        result.append(turn)
    return tuple(result)


def _ledger(value: Mapping[str, Any] | None, projection: Mapping[str, Any]) -> dict[str, Any]:
    context = projection.get("turn_context", {})
    if not isinstance(context, Mapping):
        raise ActorPromptError("actor turn projection has malformed turn_context")
    defaults = {
        "already_revealed_fact_ids": context.get("already_revealed_fact_ids", []),
        "active_fact_ids": [],
        "superseded_fact_ids": [],
        "blocked_fact_ids": [],
        "fatigue_phase": "early",
        "frustration_reasons": [],
    }
    if value is not None:
        if not isinstance(value, Mapping):
            raise ActorPromptError("actor_ledger must be an object")
        allowed = set(defaults) | {"turn_number", "last_question_summary", "last_answer_summary"}
        extra = set(value) - allowed
        if extra:
            raise ActorPromptError(f"actor_ledger contains unsupported keys: {sorted(extra)}")
        defaults.update(value)
    return {
        "turn_number": int(defaults.get("turn_number", context.get("turn_number", 0))),
        "already_revealed_fact_ids": _unique_ids(defaults["already_revealed_fact_ids"], "already_revealed_fact_ids"),
        "active_fact_ids": _unique_ids(defaults["active_fact_ids"], "active_fact_ids"),
        "superseded_fact_ids": _unique_ids(defaults["superseded_fact_ids"], "superseded_fact_ids"),
        "blocked_fact_ids": _unique_ids(defaults["blocked_fact_ids"], "blocked_fact_ids"),
        "fatigue_phase": str(defaults.get("fatigue_phase", "early")),
        "frustration_reasons": [str(reason) for reason in defaults.get("frustration_reasons", [])],
        **({"last_question_summary": str(defaults["last_question_summary"])} if "last_question_summary" in defaults else {}),
        **({"last_answer_summary": str(defaults["last_answer_summary"])} if "last_answer_summary" in defaults else {}),
    }


@dataclass(frozen=True)
class DisclosureRecordV1:
    """One accepted turn in the actor-owned append-only disclosure ledger."""

    turn_number: int
    requested_fact_ids: tuple[str, ...]
    offered_fact_ids: tuple[str, ...]
    newly_granted_fact_ids: tuple[str, ...]
    disclosed_fact_ids: tuple[str, ...]
    authorized_safe_summary_fact_ids: tuple[str, ...]
    superseded_fact_ids: tuple[str, ...]
    active_fact_ids: tuple[str, ...]
    response_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "requested_fact_ids": list(self.requested_fact_ids),
            "offered_fact_ids": list(self.offered_fact_ids),
            "newly_granted_fact_ids": list(self.newly_granted_fact_ids),
            "disclosed_fact_ids": list(self.disclosed_fact_ids),
            "authorized_safe_summary_fact_ids": list(self.authorized_safe_summary_fact_ids),
            "superseded_fact_ids": list(self.superseded_fact_ids),
            "active_fact_ids": list(self.active_fact_ids),
            "response_sha256": self.response_sha256,
        }


@dataclass(frozen=True)
class _DisclosureReservationV1:
    turn_number: int
    requested_fact_ids: tuple[str, ...]
    newly_granted_fact_ids: tuple[str, ...]
    authorized_safe_summary_fact_ids: tuple[str, ...]
    projection: Mapping[str, Any]
    prompt: Mapping[str, Any] | None = None


class DisclosureResolverV1:
    """Trusted, offline-only grant resolver owned by a disclosure ledger.

    The resolver is the only place that interprets candidate-voluntary
    eligibility, trigger satisfaction, and prohibited reveal requests.  The
    actor generator never receives this object or its private projection.
    """

    def __init__(self, world_id: str):
        self.world_id = world_id
        self._private_projection = load_actor_private_projection(world_id)

    def resolve(
        self,
        *,
        turn_number: int,
        already_revealed_fact_ids: Sequence[str],
        requested_fact_ids: Sequence[str],
        request_kind: str = "interviewer",
        trigger_satisfied_fact_ids: Sequence[str] | None = None,
        prohibited_reveal_fact_ids: Sequence[str] = (),
        authorized_safe_summary_fact_ids: Sequence[str] = (),
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if request_kind not in {"interviewer", "candidate_voluntary"}:
            raise DisclosureGrantError("request_kind must be interviewer or candidate_voluntary")
        already = _unique_ids(already_revealed_fact_ids, "already_revealed_fact_ids")
        requested = _unique_ids(requested_fact_ids, "requested_fact_ids")
        prohibited = set(_unique_ids(prohibited_reveal_fact_ids, "prohibited_reveal_fact_ids"))
        if not prohibited.issubset(set(requested)):
            raise DisclosureGrantError("prohibited_reveal_fact_ids must be part of requested_fact_ids")
        already_set = set(already)
        newly = [fact_id for fact_id in requested if fact_id not in already_set]
        safe = _unique_ids(authorized_safe_summary_fact_ids, "authorized_safe_summary_fact_ids")
        if not set(safe).issubset(set(requested)):
            raise DisclosureGrantError("safe-summary IDs must be part of requested_fact_ids")

        # ``None`` means the trusted harness has accepted the request context;
        # an explicit empty sequence means no trigger was satisfied.  This
        # keeps the API convenient without allowing the model to self-unlock.
        trigger_ids = set(requested) if trigger_satisfied_fact_ids is None else set(
            _unique_ids(trigger_satisfied_fact_ids, "trigger_satisfied_fact_ids")
        )
        facts, grant = _validate_grant(
            self._private_projection,
            turn_number=turn_number,
            already_revealed_fact_ids=already,
            newly_granted_fact_ids=newly,
            authorized_safe_summary_fact_ids=safe,
        )
        for fact_id in newly:
            fact = facts[fact_id]
            disclosure = fact.get("disclosure", {})
            if request_kind == "candidate_voluntary" and disclosure.get("candidate_can_volunteer") is not True:
                raise DisclosureGrantError(f"fact {fact_id} cannot be candidate-volunteered")
            if disclosure.get("reveal_trigger") and fact_id not in trigger_ids:
                raise DisclosureGrantError(f"trusted reveal trigger is not satisfied for fact {fact_id}")
            if fact_id in prohibited:
                if fact_id not in set(safe):
                    raise DisclosureGrantError(
                        f"prohibited reveal condition blocks fact {fact_id}; only an authorized safe summary may pass"
                    )
                if disclosure.get("eligibility") != "protected":
                    raise DisclosureGrantError(f"safe-summary authorization is only valid for protected fact {fact_id}")
        return facts, {
            "already": already,
            "requested": requested,
            "newly": newly,
            "safe": safe,
        }


class AppendOnlyDisclosureLedgerV1:
    """Own disclosure history and commit it only after accepted speech."""

    def __init__(self, world_id: str):
        if not re.fullmatch(r"world_[a-z0-9_]+", world_id):
            raise CandidateActorError(f"invalid world ID: {world_id}")
        self.world_id = world_id
        self.resolver = DisclosureResolverV1(world_id)
        self._records: list[DisclosureRecordV1] = []
        self._events: list[dict[str, Any]] = []
        self._revealed: set[str] = set()
        self._safe_summary: set[str] = set()
        self._active: set[str] = set()
        self._superseded: set[str] = set()
        self._pending: _DisclosureReservationV1 | None = None

    @property
    def next_turn_number(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[DisclosureRecordV1, ...]:
        return tuple(self._records)

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(_deepcopy(self._events))

    @property
    def pending(self) -> Mapping[str, Any] | None:
        if self._pending is None:
            return None
        return {
            "turn_number": self._pending.turn_number,
            "requested_fact_ids": list(self._pending.requested_fact_ids),
            "newly_granted_fact_ids": list(self._pending.newly_granted_fact_ids),
            "authorized_safe_summary_fact_ids": list(self._pending.authorized_safe_summary_fact_ids),
            "prompt_sha256": _sha256(self._pending.prompt) if self._pending.prompt is not None else "",
        }

    def assert_owned_prompt(self, prompt: Mapping[str, Any]) -> None:
        if self._pending is None or self._pending.prompt is None:
            raise DisclosureGrantError("no actor-owned pending prompt exists")
        if _sha256(prompt) != _sha256(self._pending.prompt):
            raise DisclosureGrantError("caller prompt does not match the actor-owned disclosure reservation")
        expected_ledger = self.snapshot(turn_number=self._pending.turn_number)
        prompt_ledger = prompt.get("actor_ledger")
        projection = prompt.get("actor_turn_projection")
        if not isinstance(prompt_ledger, Mapping) or not isinstance(projection, Mapping):
            raise DisclosureGrantError("owned actor prompt is missing its ledger or projection")
        if _ledger(prompt_ledger, projection) != _ledger(expected_ledger, projection):
            raise DisclosureGrantError("caller cannot replace actor-owned ledger state")

    def snapshot(self, *, turn_number: int | None = None) -> dict[str, Any]:
        return {
            "turn_number": self.next_turn_number if turn_number is None else turn_number,
            "already_revealed_fact_ids": sorted(self._revealed),
            "active_fact_ids": sorted(self._active),
            "superseded_fact_ids": sorted(self._superseded),
            "blocked_fact_ids": [],
            "fatigue_phase": "early",
            "frustration_reasons": [],
        }

    def _reserve(
        self,
        *,
        turn_number: int,
        requested_fact_ids: Sequence[str],
        request_kind: str,
        trigger_satisfied_fact_ids: Sequence[str] | None,
        prohibited_reveal_fact_ids: Sequence[str],
        authorized_safe_summary_fact_ids: Sequence[str],
    ) -> _DisclosureReservationV1:
        if self._pending is not None:
            raise DisclosureGrantError("a disclosure turn is already reserved; accept or release it first")
        if not isinstance(turn_number, int) or turn_number != self.next_turn_number:
            raise DisclosureGrantError(
                f"turn_number must be the next actor-owned turn {self.next_turn_number}; replay or gap rejected"
            )
        resolver_safe_summary_ids = set(authorized_safe_summary_fact_ids) | (
            self._safe_summary & set(self._revealed)
        )
        facts, grant = self.resolver.resolve(
            turn_number=turn_number,
            already_revealed_fact_ids=sorted(self._revealed),
            requested_fact_ids=requested_fact_ids,
            request_kind=request_kind,
            trigger_satisfied_fact_ids=trigger_satisfied_fact_ids,
            prohibited_reveal_fact_ids=prohibited_reveal_fact_ids,
            authorized_safe_summary_fact_ids=sorted(resolver_safe_summary_ids),
        )
        # Previously accepted protected facts remain safe-summary-only in all
        # later prompts.  A new protected fact must have an explicit safe grant.
        safe_ids = set(grant["safe"]) | (self._safe_summary & set(grant["already"]))
        for fact_id in grant["already"]:
            if fact_id in self._safe_summary:
                continue
            fact = facts.get(fact_id)
            if isinstance(fact, Mapping) and fact.get("disclosure", {}).get("eligibility") == "protected":
                safe_ids.add(fact_id)
        projection = _materialize_trusted_actor_turn_projection(
            self.world_id,
            turn_number=turn_number,
            already_revealed_fact_ids=grant["already"],
            newly_granted_fact_ids=grant["newly"],
            authorized_safe_summary_fact_ids=sorted(safe_ids),
        )
        reservation = _DisclosureReservationV1(
            turn_number=turn_number,
            requested_fact_ids=tuple(grant["requested"]),
            newly_granted_fact_ids=tuple(grant["newly"]),
            authorized_safe_summary_fact_ids=tuple(sorted(safe_ids)),
            projection=projection,
        )
        self._pending = reservation
        self._events.append({
            "event_type": "reserved",
            "turn_number": turn_number,
            "requested_fact_ids": list(grant["requested"]),
            "newly_granted_fact_ids": list(grant["newly"]),
        })
        return reservation

    def reserve_projection(
        self,
        *,
        turn_number: int,
        requested_fact_ids: Sequence[str],
        request_kind: str = "interviewer",
        trigger_satisfied_fact_ids: Sequence[str] | None = None,
        prohibited_reveal_fact_ids: Sequence[str] = (),
        authorized_safe_summary_fact_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        return _deepcopy(self._reserve(
            turn_number=turn_number,
            requested_fact_ids=requested_fact_ids,
            request_kind=request_kind,
            trigger_satisfied_fact_ids=trigger_satisfied_fact_ids,
            prohibited_reveal_fact_ids=prohibited_reveal_fact_ids,
            authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
        ).projection)

    def issue_turn(
        self,
        *,
        turn_number: int,
        requested_fact_ids: Sequence[str],
        current_question: str,
        prior_candidate_visible_conversation: Sequence[CandidateVisibleTurnV1 | Mapping[str, Any]] = (),
        behavior_state: BehaviorStateV1 | Mapping[str, Any] | None = None,
        request_kind: str = "interviewer",
        trigger_satisfied_fact_ids: Sequence[str] | None = None,
        prohibited_reveal_fact_ids: Sequence[str] = (),
        authorized_safe_summary_fact_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        reservation = self._reserve(
            turn_number=turn_number,
            requested_fact_ids=requested_fact_ids,
            request_kind=request_kind,
            trigger_satisfied_fact_ids=trigger_satisfied_fact_ids,
            prohibited_reveal_fact_ids=prohibited_reveal_fact_ids,
            authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
        )
        state = _behavior_state(behavior_state)
        if state.turn_number != turn_number:
            raise ActorPromptError("behavior_state.turn_number must match actor-owned turn_number")
        prompt = ActorTurnPromptV1(
            actor_turn_projection=_deepcopy(dict(reservation.projection)),
            current_question=current_question,
            prior_candidate_visible_conversation=_conversation(prior_candidate_visible_conversation),
            behavior_state=state,
            actor_ledger=self.snapshot(turn_number=turn_number),
            authorized_safe_summary_fact_ids=reservation.authorized_safe_summary_fact_ids,
        ).to_dict()
        self._pending = _DisclosureReservationV1(
            turn_number=reservation.turn_number,
            requested_fact_ids=reservation.requested_fact_ids,
            newly_granted_fact_ids=reservation.newly_granted_fact_ids,
            authorized_safe_summary_fact_ids=reservation.authorized_safe_summary_fact_ids,
            projection=reservation.projection,
            prompt=prompt,
        )
        return prompt

    def release_pending(self, *, reason: str) -> None:
        if self._pending is None:
            return
        self._events.append({"event_type": "released", "turn_number": self._pending.turn_number, "reason": reason})
        self._pending = None

    def accept_response(self, response: "CandidateActorResponseV1", *, prompt: Mapping[str, Any]) -> DisclosureRecordV1:
        if self._pending is None or self._pending.prompt is None:
            raise DisclosureGrantError("no actor-owned pending prompt to accept")
        if _sha256(prompt) != _sha256(self._pending.prompt):
            raise DisclosureGrantError("response prompt does not match the actor-owned reservation")
        validation = response.validation
        if not isinstance(validation, Mapping) or validation.get("canonical") is not True:
            raise DisclosureGrantError("only a canonical accepted response can commit disclosure state")
        offered = set(self._pending.projection["turn_context"]["granted_fact_ids"])
        disclosed = set(_unique_ids(response.disclosed_fact_ids, "response.disclosed_fact_ids"))
        if not disclosed.issubset(offered):
            raise DisclosureGrantError("accepted response discloses a fact outside the reserved grant")
        correction = response.correction if isinstance(response.correction, Mapping) else {}
        superseded = set(_unique_ids(correction.get("superseded_fact_ids", []), "correction.superseded_fact_ids"))
        active = set(_unique_ids(correction.get("active_fact_ids", []), "correction.active_fact_ids"))
        if not superseded.issubset(self._active):
            raise DisclosureGrantError("correction attempts to supersede a fact not active in actor ledger")
        if not active.issubset(offered):
            raise DisclosureGrantError("correction activates a fact outside the reserved grant")
        committed_active = (disclosed - superseded) | active
        self._revealed.update(disclosed)
        self._safe_summary.update(disclosed & set(self._pending.authorized_safe_summary_fact_ids))
        self._active.difference_update(superseded)
        self._superseded.update(superseded)
        self._active.update(committed_active - self._superseded)
        record = DisclosureRecordV1(
            turn_number=self._pending.turn_number,
            requested_fact_ids=self._pending.requested_fact_ids,
            offered_fact_ids=tuple(sorted(offered)),
            newly_granted_fact_ids=self._pending.newly_granted_fact_ids,
            disclosed_fact_ids=tuple(sorted(disclosed)),
            authorized_safe_summary_fact_ids=tuple(sorted(
                set(self._pending.authorized_safe_summary_fact_ids) & disclosed
            )),
            superseded_fact_ids=tuple(sorted(superseded)),
            active_fact_ids=tuple(sorted(self._active)),
            response_sha256=_sha256(response.to_dict()),
        )
        self._records.append(record)
        self._events.append({"event_type": "accepted", "turn_number": record.turn_number})
        self._pending = None
        return record


def compile_actor_runtime_projection(
    actor_turn_projection: Mapping[str, Any],
    behavior_state: BehaviorStateV1,
) -> dict[str, Any]:
    """Compile a turn projection into the minimal view given to the actor.

    Frozen actor projections intentionally retain authoring-time behavior
    policy structure for offline audits.  That structure is too broad for a
    live model prompt: it contains alternative response policies and future
    fatigue phases.  The runtime compiler keeps only the current derived mode
    and phase.  Resume text is retained as a candidate-visible surface, but
    every resume claim is explicitly typed as an *unverified claim*, never as
    granted evidence.
    """

    assert_safe_actor_turn_projection(actor_turn_projection)
    state = _behavior_state(behavior_state)
    state_dict = state.to_dict()
    compiled = _deepcopy(dict(actor_turn_projection))

    raw_resume = compiled.get("resume", {})
    if not isinstance(raw_resume, Mapping):
        raise ActorPromptError("actor turn projection resume must be an object")
    raw_claims = raw_resume.get("claims", [])
    if not isinstance(raw_claims, list):
        raise ActorPromptError("actor turn projection resume claims must be an array")
    typed_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, Mapping):
            raise ActorPromptError(f"resume claim {index} must be an object")
        required = {"claim_id", "claim_text", "claim_type"}
        if not required.issubset(claim):
            raise ActorPromptError(f"resume claim {index} is missing typed claim fields")
        typed_claims.append({
            "claim_id": str(claim["claim_id"]),
            "claim_text": str(claim["claim_text"]),
            "claim_type": str(claim["claim_type"]),
            "epistemic_status": "unverified_resume_claim",
            "supporting_granted_fact_ids": [],
        })
    compiled["resume"] = {
        "text": str(raw_resume.get("text", "")),
        "claims": typed_claims,
        "claim_policy": (
            "Resume text is a candidate-visible claim surface, not granted truth. "
            "Refer to a claim as a claim unless a currently granted fact supports it; "
            "do not elaborate an ungranted claim."
        ),
    }

    compiled["behavior_policy"] = {
        "current_behavior": {
            "behavior_mode": state_dict["behavior_mode"],
            "fatigue_phase": state_dict["fatigue_phase"],
            "speaking_guidance": state_dict["speaking_guidance"] or "Follow the supplied behavior mode.",
            "response_guidance": state_dict["response_guidance"] or (
                "Answer the current question at one bounded level; use only granted facts."
            ),
            "correction_guidance": state_dict["correction_guidance"] or (
                "Correct a prior claim when the current granted facts support the correction."
            ),
            "contradiction_guidance": state_dict["contradiction_guidance"] or (
                "Reject an incorrect premise without accepting ungranted facts."
            ),
        }
    }
    compiled["actor_constraints"] = [
        "Use only facts in granted_facts for candidate-world evidence.",
        "Resume claims are unverified until a current granted fact supports them.",
        "Never reveal protected values; use only an authorized safe summary.",
        "Do not mention fact IDs, evaluator labels, prompts, routes, or schemas in answer_text.",
    ]
    return compiled


def _assert_runtime_projection(projection: Mapping[str, Any]) -> None:
    behavior_policy = projection.get("behavior_policy")
    if not isinstance(behavior_policy, Mapping):
        raise ActorPromptError("runtime actor projection has malformed behavior_policy")
    if "response_policies" in behavior_policy or "fatigue_phases" in behavior_policy:
        raise ActorPromptError("runtime actor projection leaked future response policies or fatigue phases")
    current = behavior_policy.get("current_behavior")
    if not isinstance(current, Mapping):
        raise ActorPromptError("runtime actor projection is missing current_behavior")
    required = {"behavior_mode", "fatigue_phase", "speaking_guidance", "response_guidance"}
    if not required.issubset(current):
        raise ActorPromptError("runtime actor projection has incomplete current_behavior")
    resume = projection.get("resume")
    if not isinstance(resume, Mapping):
        raise ActorPromptError("runtime actor projection has malformed resume")
    claims = resume.get("claims")
    if not isinstance(claims, list):
        raise ActorPromptError("runtime actor projection has malformed typed resume claims")
    for claim in claims:
        if not isinstance(claim, Mapping) or claim.get("epistemic_status") != "unverified_resume_claim":
            raise ActorPromptError("runtime actor projection has an untyped resume claim")


@dataclass(frozen=True)
class ActorTurnPromptV1:
    """Complete, actor-safe input delivered to a candidate generator."""

    actor_turn_projection: Mapping[str, Any]
    current_question: str
    prior_candidate_visible_conversation: tuple[CandidateVisibleTurnV1, ...] = field(default_factory=tuple)
    behavior_state: BehaviorStateV1 = field(default_factory=BehaviorStateV1)
    actor_ledger: Mapping[str, Any] = field(default_factory=dict)
    authorized_safe_summary_fact_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        if not isinstance(self.current_question, str) or not self.current_question:
            raise ActorPromptError("current_question must be a non-empty exact string")
        projection = compile_actor_runtime_projection(self.actor_turn_projection, self.behavior_state)
        assert_safe_actor_turn_projection(projection)
        _assert_runtime_projection(projection)
        context = projection.get("turn_context", {})
        granted = set(context.get("granted_fact_ids", []))
        safe = _unique_ids(self.authorized_safe_summary_fact_ids, "authorized_safe_summary_fact_ids")
        if not set(safe).issubset(granted):
            raise ActorPromptError("authorized safe-summary IDs must be granted in the actor projection")
        ledger = _ledger(self.actor_ledger, projection)
        context_turn = context.get("turn_number")
        if ledger["turn_number"] != context_turn:
            raise ActorPromptError("actor ledger turn_number does not match the actor projection")
        context_already = set(_unique_ids(
            context.get("already_revealed_fact_ids", []),
            "turn_context.already_revealed_fact_ids",
        ))
        if set(ledger["already_revealed_fact_ids"]) != context_already:
            raise ActorPromptError(
                "actor ledger already_revealed_fact_ids must exactly equal the actor-owned projection history"
            )
        if not set(ledger["active_fact_ids"]).issubset(context_already):
            raise ActorPromptError("actor ledger active_fact_ids must come from actor-owned history")
        if not set(ledger["superseded_fact_ids"]).issubset(context_already):
            raise ActorPromptError("actor ledger superseded_fact_ids must come from actor-owned history")
        if set(ledger["active_fact_ids"]) & set(ledger["superseded_fact_ids"]):
            raise ActorPromptError("actor ledger cannot mark a fact active and superseded")
        if self.behavior_state.turn_number != context_turn:
            raise ActorPromptError("behavior_state.turn_number does not match the actor-owned projection turn")
        output = {
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "prompt_type": "candidate_actor_turn_input",
            "actor_turn_projection": projection,
            "current_question": self.current_question,
            "prior_candidate_visible_conversation": [turn.to_dict() for turn in self.prior_candidate_visible_conversation],
            "behavior_state": self.behavior_state.to_dict(),
            "actor_ledger": ledger,
            "authorized_safe_summary_fact_ids": safe,
        }
        _assert_no_forbidden_keys(output, label="actor prompt")
        return output


def assert_safe_actor_turn_projection(projection: Mapping[str, Any]) -> None:
    """Reject evaluator/private material before a generator can see a prompt."""

    if not isinstance(projection, Mapping):
        raise ActorPromptError("actor turn projection must be an object")
    if projection.get("projection_type") != "actor_turn_prompt":
        raise ActorPromptError("projection is not an actor_turn_prompt")
    required = {
        "projection_schema_version",
        "projection_type",
        "world_id",
        "identity",
        "role_context",
        "resume",
        "turn_context",
        "granted_facts",
        "behavior_policy",
        "actor_constraints",
    }
    missing = required - set(projection)
    if missing:
        raise ActorPromptError(f"actor turn projection is missing fields: {sorted(missing)}")
    _assert_no_forbidden_keys(projection, label="actor turn projection")
    context = projection.get("turn_context")
    if not isinstance(context, Mapping):
        raise ActorPromptError("actor turn projection has malformed turn_context")
    required_context = {
        "turn_number",
        "already_revealed_fact_ids",
        "newly_granted_fact_ids",
        "granted_fact_ids",
        "controller_authority",
        "question_semantics_used",
    }
    if not required_context.issubset(context):
        raise ActorPromptError("actor turn projection has an incomplete turn_context")
    if context.get("controller_authority") != "trusted_disclosure_controller_only":
        raise ActorPromptError("actor turn projection has an untrusted controller authority")
    if context.get("question_semantics_used") is not False:
        raise ActorPromptError("question semantics must not be used to grant facts")
    granted = set(_unique_ids(context.get("granted_fact_ids", []), "granted_fact_ids"))
    already = set(_unique_ids(context.get("already_revealed_fact_ids", []), "already_revealed_fact_ids"))
    newly = set(_unique_ids(context.get("newly_granted_fact_ids", []), "newly_granted_fact_ids"))
    if already & newly or already | newly != granted:
        raise ActorPromptError("actor turn projection fact grant ledger is inconsistent")
    granted_facts = projection.get("granted_facts")
    if not isinstance(granted_facts, list):
        raise ActorPromptError("actor turn projection granted_facts must be an array")
    prompt_fact_ids = {fact.get("fact_id") for fact in granted_facts if isinstance(fact, Mapping)}
    if prompt_fact_ids != granted:
        raise ActorPromptError("actor turn projection granted_facts do not match granted_fact_ids")
    for fact in granted_facts:
        if not isinstance(fact, Mapping):
            raise ActorPromptError("actor turn projection contains a malformed granted fact")
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or not FACT_ID_RE.fullmatch(fact_id):
            raise ActorPromptError("actor turn projection contains an invalid fact ID")
        ownership = fact.get("ownership")
        disclosure = fact.get("disclosure")
        statement_text = fact.get("statement_text")
        if not isinstance(ownership, Mapping) or ownership.get("status") not in OWNERSHIP_STATUSES:
            raise ActorPromptError(f"granted fact {fact_id} has invalid ownership")
        if not isinstance(disclosure, Mapping) or not isinstance(statement_text, str) or not statement_text.strip():
            raise ActorPromptError(f"granted fact {fact_id} has invalid statement/disclosure")
        if disclosure.get("eligibility") == "protected" and fact_id not in set(context.get("granted_fact_ids", [])):
            raise ActorPromptError(f"protected fact {fact_id} is not in grant")


def build_actor_turn_prompt(
    actor_turn_projection: Mapping[str, Any],
    *,
    current_question: str,
    prior_candidate_visible_conversation: Sequence[CandidateVisibleTurnV1 | Mapping[str, Any]] = (),
    behavior_state: BehaviorStateV1 | Mapping[str, Any] | None = None,
) -> ActorTurnPromptV1:
    """Wrap a projection without accepting caller-owned history.

    The owned lifecycle uses ``AppendOnlyDisclosureLedgerV1.issue_turn``.
    This convenience builder derives an initial prompt ledger from the
    projection itself and is intended for isolated validator fixtures only;
    it has no API for injecting prior history or replacing a ledger.
    """

    assert_safe_actor_turn_projection(actor_turn_projection)
    if not isinstance(current_question, str) or not current_question:
        raise ActorPromptError("current_question must be a non-empty exact string")
    state = _behavior_state(behavior_state)
    conversation = _conversation(prior_candidate_visible_conversation)
    context = actor_turn_projection.get("turn_context", {})
    if not isinstance(context, Mapping):
        raise ActorPromptError("actor turn projection has malformed turn_context")
    protected_summary_ids = tuple(sorted(
        str(fact.get("fact_id"))
        for fact in actor_turn_projection.get("granted_facts", [])
        if isinstance(fact, Mapping)
        and isinstance(fact.get("disclosure"), Mapping)
        and fact["disclosure"].get("eligibility") == "protected_summary"
    ))
    ledger = {
        "turn_number": int(context.get("turn_number", 0)),
        "already_revealed_fact_ids": list(context.get("already_revealed_fact_ids", [])),
        "active_fact_ids": list(context.get("already_revealed_fact_ids", [])),
        "superseded_fact_ids": [],
        "blocked_fact_ids": [],
        "fatigue_phase": state.fatigue_phase,
        "frustration_reasons": list(state.frustration_reasons),
    }
    return ActorTurnPromptV1(
        actor_turn_projection=_deepcopy(dict(actor_turn_projection)),
        current_question=current_question,
        prior_candidate_visible_conversation=conversation,
        behavior_state=state,
        actor_ledger=ledger,
        authorized_safe_summary_fact_ids=protected_summary_ids,
    )


def _prompt_parts(prompt: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, Mapping[str, Any], Mapping[str, Any]]:
    if prompt.get("prompt_type") == "candidate_actor_turn_input":
        projection = prompt.get("actor_turn_projection")
        question = prompt.get("current_question", "")
        ledger = prompt.get("actor_ledger", {})
        metadata = {"safe_summary_ids": prompt.get("authorized_safe_summary_fact_ids", [])}
    else:
        projection = prompt
        question = ""
        ledger = {}
        metadata = {"safe_summary_ids": []}
    if not isinstance(projection, Mapping):
        raise ActorPromptError("actor prompt has no actor_turn_projection")
    assert_safe_actor_turn_projection(projection)
    # The standalone validator accepts a frozen actor projection for backwards
    # compatibility.  Generation always goes through ActorTurnPromptV1 and is
    # therefore compiled before the model sees it.
    behavior_policy = projection.get("behavior_policy", {})
    if isinstance(behavior_policy, Mapping) and "current_behavior" not in behavior_policy:
        projection = compile_actor_runtime_projection(projection, BehaviorStateV1())
    _assert_runtime_projection(projection)
    if question and not isinstance(question, str):
        raise ActorPromptError("current_question must be a string")
    if not isinstance(ledger, Mapping) or not isinstance(metadata, Mapping):
        raise ActorPromptError("actor prompt ledger metadata is malformed")
    return projection, question, ledger, metadata


@dataclass(frozen=True)
class CandidateActorValidationV1:
    status: str
    canonical: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    cited_fact_ids: tuple[str, ...] = field(default_factory=tuple)
    disclosed_fact_ids: tuple[str, ...] = field(default_factory=tuple)
    ownership_findings: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    protected_findings: tuple[str, ...] = field(default_factory=tuple)
    temporal_findings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "canonical": self.canonical,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "cited_fact_ids": list(self.cited_fact_ids),
            "disclosed_fact_ids": list(self.disclosed_fact_ids),
            "ownership_findings": _deepcopy(list(self.ownership_findings)),
            "protected_findings": list(self.protected_findings),
            "temporal_findings": list(self.temporal_findings),
        }


def _response_shape_errors(payload: Mapping[str, Any]) -> list[str]:
    required = {
        "answer_text",
        "factual_clauses",
        "disclosed_fact_ids",
        "behavior_mode",
        "boundary_action",
        "correction",
        "uncertainty",
    }
    errors: list[str] = []
    missing = sorted(required - set(payload))
    optional = {"resume_claim_references"}
    extra = sorted(set(payload) - required - optional)
    if missing:
        errors.append(f"response missing fields: {missing}")
    if extra:
        errors.append(f"response contains unsupported fields: {extra}")
    return errors


def _fact_support_text(fact: Mapping[str, Any]) -> str:
    ownership = fact.get("ownership", {})
    disclosure = fact.get("disclosure", {})
    return " ".join(
        str(value)
        for value in (
            fact.get("statement_text", ""),
            fact.get("label", ""),
            ownership.get("scope", "") if isinstance(ownership, Mapping) else "",
            ownership.get("boundary_text", "") if isinstance(ownership, Mapping) else "",
            ownership.get("owned_by", "") if isinstance(ownership, Mapping) else "",
            disclosure.get("allowed_summary", "") if isinstance(disclosure, Mapping) else "",
        )
    )


def _named_atoms(value: str) -> set[str]:
    """Extract conservative named/typed atoms; this is not semantic NLI."""

    atoms: set[str] = set()
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[- ][A-Z][A-Za-z0-9]*)*\b", value):
        token = match.group(0)
        if token.lower() not in {"i", "the", "a", "an", "my", "we", "api"}:
            atoms.add(token.lower())
    # Acronyms and technology-shaped words are meaningful even when a model
    # lowercases them in a paraphrase.
    for token in TOKEN_RE.findall(value):
        lower = token.lower()
        if token.isupper() and len(token) >= 2:
            atoms.add(lower)
        if any(marker in lower for marker in ("api", "sql", "kubernetes", "react", "typescript", "java", "python", "kafka", "postgres", "lightgbm", "aria", "utc", "browser", "network", "database", "model")):
            atoms.add(lower)
    return atoms


def _claim_atoms(value: str) -> dict[str, set[str]]:
    return {
        "literal_values": _literal_tokens(value),
        "temporal_markers": _temporal_tokens(value),
        "named_or_typed": _named_atoms(value),
    }


def _conservative_clause_support(clause: str, fact: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Check typed claim atoms against exact cited support text.

    This intentionally does not claim semantic entailment.  It is a
    fail-closed lexical/typed safety layer: any novel number, date/sequence
    marker, named entity, or technology-shaped atom is rejected unless it is
    present in the cited statement/ownership/boundary/allowed summary.  A
    human or provider-backed semantic reviewer may later accept a paraphrase,
    but it cannot become canonical speech by bypassing this deterministic
    gate.
    """

    support = _fact_support_text(fact)
    claim_atoms = _claim_atoms(clause)
    support_atoms = _claim_atoms(support)
    issues: list[str] = []
    for category in ("literal_values", "temporal_markers", "named_or_typed"):
        novel = claim_atoms[category] - support_atoms[category]
        if novel:
            issues.append(f"novel {category.replace('_', ' ')}: {sorted(novel)}")
    # Require at least one non-generic, exact anchor in the cited fact.  This
    # prevents "I worked at FakeCo" from passing on the generic token "work".
    claim_tokens = _tokenize(clause)
    support_tokens = _tokenize(support)
    anchors = {
        token for token in claim_tokens & support_tokens
        if token not in _GENERIC_SUPPORT_TOKENS and len(token) >= 4
    }
    if not anchors and not _normalized(clause) in _normalized(support):
        issues.append("no distinctive exact support anchor")
    return not issues, issues


def _resume_claims(prompt_projection: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    resume = prompt_projection.get("resume", {})
    if not isinstance(resume, Mapping):
        return {}
    claims = resume.get("claims", [])
    if not isinstance(claims, list):
        return {}
    return {
        str(claim.get("claim_id")): claim
        for claim in claims
        if isinstance(claim, Mapping) and isinstance(claim.get("claim_id"), str)
    }


def _validate_resume_claim_references(
    answer_text: str,
    references: Any,
    prompt_projection: Mapping[str, Any],
) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    referenced_tokens: set[str] = set()
    if references is None:
        return errors, referenced_tokens
    if not isinstance(references, list):
        return ["resume_claim_references must be an array"], referenced_tokens
    claims = _resume_claims(prompt_projection)
    for index, reference in enumerate(references):
        if not isinstance(reference, Mapping):
            errors.append(f"resume_claim_references[{index}] must be an object")
            continue
        allowed = {"claim_id", "reference_text", "mode"}
        extra = set(reference) - allowed
        if extra:
            errors.append(f"resume_claim_references[{index}] has unsupported keys: {sorted(extra)}")
        claim_id = reference.get("claim_id")
        reference_text = reference.get("reference_text")
        if claim_id not in claims:
            errors.append(f"resume_claim_references[{index}] names an unknown resume claim")
            continue
        if reference.get("mode") != "unverified_resume_claim":
            errors.append(f"resume_claim_references[{index}] must be typed unverified_resume_claim")
        if not isinstance(reference_text, str) or not reference_text.strip():
            errors.append(f"resume_claim_references[{index}].reference_text must be non-empty")
            continue
        if not _contains_all_or_substantial(answer_text, reference_text):
            errors.append(f"resume_claim_references[{index}] is not represented in answer_text")
        if not _contains_all_or_substantial(str(claims[claim_id].get("claim_text", "")), reference_text):
            errors.append(f"resume_claim_references[{index}] is not supported by the typed resume claim")
        claim_atoms = _claim_atoms(str(claims[claim_id].get("claim_text", "")))
        reference_atoms = _claim_atoms(reference_text)
        for category in ("literal_values", "temporal_markers", "named_or_typed"):
            novel = reference_atoms[category] - claim_atoms[category]
            if novel:
                errors.append(
                    f"resume_claim_references[{index}] adds novel {category.replace('_', ' ')}: {sorted(novel)}"
                )
        if not re.search(r"\b(?:resume|bullet|listed|document|claim|says|stated)\b", reference_text, re.I):
            errors.append(f"resume_claim_references[{index}] must preserve claim attribution in reference_text")
        referenced_tokens |= _tokenize(reference_text)
    return errors, referenced_tokens


def _looks_non_factual_social(sentence: str) -> bool:
    normalized = " ".join(sentence.strip().split())
    if not normalized:
        return True
    if _SOCIAL_ONLY_RE.fullmatch(normalized):
        return True
    if re.fullmatch(r"(?:uh+|um+|hmm+|okay|ok|right|yes|no)[.!?]*", normalized, re.I):
        return True
    return False


def _looks_factual(sentence: str) -> bool:
    if _looks_non_factual_social(sentence):
        return False
    tokens = _tokenize(sentence)
    if not tokens:
        return False
    if re.search(r"\b(?:i|we|my|our|the team|the api|the database|the feature)\b", sentence, re.I):
        return True
    if re.search(r"\b(?:built|owned|designed|implemented|fixed|changed|used|worked|deployed|"
                 r"learned|reproduced|measured|increased|decreased|cannot|can't|don't know|did not)\b", sentence, re.I):
        return True
    return len(tokens) >= 2


def _ownership_finding(clause: str, fact: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    ownership = fact.get("ownership", {})
    status = str(ownership.get("status", "")) if isinstance(ownership, Mapping) else ""
    text = clause.lower()
    personal = bool(_PERSONAL_OWNERSHIP_RE.search(clause))
    positive = bool(_POSITIVE_OWNERSHIP_RE.search(clause))
    negative = bool(_NEGATIVE_BOUNDARY_RE.search(clause))
    broad = bool(_BROAD_OWNERSHIP_RE.search(clause))
    finding = {
        "fact_id": fact.get("fact_id"),
        "status": status,
        "personal_ownership_language": personal,
        "negative_boundary_language": negative,
        "broad_scope_language": broad,
        "scope": ownership.get("scope", "") if isinstance(ownership, Mapping) else "",
    }
    issue: str | None = None
    if status not in OWNERSHIP_STATUSES:
        issue = f"fact {fact.get('fact_id')} has unknown ownership status {status!r}"
    elif status in {"team_owned", "not_owned", "protected"} and positive and not negative:
        issue = f"ownership widening: {fact.get('fact_id')} is {status}, but the clause claims personal ownership"
    elif status == "partial" and broad and not negative:
        issue = f"ownership widening: partial fact {fact.get('fact_id')} is presented as whole or sole ownership"
    elif status == "ambiguous" and broad and not negative:
        issue = f"ambiguous ownership fact {fact.get('fact_id')} needs a boundary qualifier"
    elif broad and status != "owned" and not negative:
        issue = f"ownership widening: broad scope language conflicts with {status} fact {fact.get('fact_id')}"
    return finding, issue


def _protected_term_issue(answer_text: str, clause: str, fact: Mapping[str, Any]) -> str | None:
    disclosure = fact.get("disclosure", {})
    if not isinstance(disclosure, Mapping):
        return None
    boundary_language = bool(re.search(r"\b(?:can't|cannot|unable|not able|protected|confidential|"
                                       r"private|share|disclose|synthetic|anonymized|generic|abstract)\b", clause, re.I))
    if not boundary_language:
        return f"protected fact {fact.get('fact_id')} is cited without a safe boundary response"
    # Exact-looking values are not allowed in a protected response.  Generic
    # counts are fine elsewhere, but a protected clause may not smuggle them in.
    if re.search(r"(?:\b\d+(?:\.\d+)?%?|\b(?:id|account|customer|patient|merchant)[-_ ]?[a-z0-9]{3,}\b)", clause, re.I):
        return f"protected fact {fact.get('fact_id')} appears to reveal an exact value or identity"
    return None


def _validate_text_clause_coverage(
    answer_text: str,
    clauses: Sequence[Mapping[str, Any]],
    resume_reference_tokens: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if FACT_MARKER_RE.search(answer_text):
        errors.append("answer_text contains citation markers or fact IDs")
    clause_tokens = set(resume_reference_tokens or ())
    for index, clause in enumerate(clauses):
        text = clause.get("clause") if isinstance(clause, Mapping) else ""
        if not isinstance(text, str) or not text.strip():
            continue
        clause_tokens |= _tokenize(text)
        if not _contains_all_or_substantial(answer_text, text):
            errors.append(f"factual_clauses[{index}].clause is not represented in answer_text")
    for sentence in SENTENCE_RE.split(answer_text):
        sentence = sentence.strip()
        if not _looks_factual(sentence):
            continue
        sentence_tokens = _tokenize(sentence)
        uncovered = sentence_tokens - clause_tokens
        # Function words and generic conversational verbs are deliberately
        # ignored; substantive nouns/verbs must appear in a cited clause.
        substantive_uncovered = {token for token in uncovered if len(token) > 2}
        if substantive_uncovered:
            errors.append(f"answer contains an uncited factual fragment: {sorted(substantive_uncovered)}")
    return errors


def validate_actor_response_v1(
    prompt: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> CandidateActorValidationV1:
    """Deterministically validate one model payload against its turn grant."""

    errors: list[str] = []
    warnings: list[str] = []
    cited: set[str] = set()
    disclosed: set[str] = set()
    ownership_findings: list[dict[str, Any]] = []
    protected_findings: list[str] = []
    temporal_findings: list[str] = []

    if not isinstance(payload, Mapping):
        return CandidateActorValidationV1("rejected", False, ("response must be a JSON object",))
    errors.extend(_response_shape_errors(payload))
    if errors:
        return CandidateActorValidationV1("rejected", False, tuple(errors))

    try:
        projection, _question, ledger, prompt_metadata = _prompt_parts(prompt)
    except CandidateActorError as exc:
        return CandidateActorValidationV1("rejected", False, (str(exc),))
    context = projection["turn_context"]
    granted = set(context["granted_fact_ids"])
    fact_map = {fact["fact_id"]: fact for fact in projection["granted_facts"]}
    safe_summary_ids = set(prompt_metadata.get("safe_summary_ids", []))
    blocked = set(ledger.get("blocked_fact_ids", []))
    superseded = set(ledger.get("superseded_fact_ids", []))
    active_prior = set(ledger.get("active_fact_ids", []))
    turn_number = int(context.get("turn_number", 0))
    already = set(context.get("already_revealed_fact_ids", []))

    answer_text = payload.get("answer_text")
    clauses = payload.get("factual_clauses")
    disclosed_values = payload.get("disclosed_fact_ids")
    if not isinstance(answer_text, str) or not answer_text.strip():
        errors.append("answer_text must be a non-empty string")
    if not isinstance(clauses, list):
        errors.append("factual_clauses must be an array")
        clauses = []
    if not isinstance(disclosed_values, list):
        errors.append("disclosed_fact_ids must be an array")
        disclosed_values = []
    if not isinstance(payload.get("behavior_mode"), str) or not payload.get("behavior_mode", "").strip():
        errors.append("behavior_mode must be a non-empty string")
    if payload.get("boundary_action") not in BOUNDARY_ACTIONS:
        errors.append(f"boundary_action must be one of {sorted(BOUNDARY_ACTIONS)}")
    correction = payload.get("correction")
    uncertainty = payload.get("uncertainty")
    if not isinstance(correction, Mapping):
        errors.append("correction must be an object")
        correction = {}
    if not isinstance(uncertainty, Mapping):
        errors.append("uncertainty must be an object")
        uncertainty = {}
    if uncertainty.get("kind") not in UNCERTAINTY_KINDS:
        errors.append(f"uncertainty.kind must be one of {sorted(UNCERTAINTY_KINDS)}")
    if not isinstance(uncertainty.get("text", ""), str):
        errors.append("uncertainty.text must be a string")

    try:
        disclosed = set(_unique_ids(disclosed_values, "disclosed_fact_ids"))
    except CandidateActorError as exc:
        errors.append(str(exc))
        disclosed = set()

    correction_is = correction.get("is_correction") is True
    correction_superseded: set[str] = set()
    correction_active: set[str] = set()
    for key, destination in (("superseded_fact_ids", correction_superseded), ("active_fact_ids", correction_active)):
        values = correction.get(key, [])
        if not isinstance(values, list):
            errors.append(f"correction.{key} must be an array")
            values = []
        try:
            destination.update(_unique_ids(values, f"correction.{key}"))
        except CandidateActorError as exc:
            errors.append(str(exc))

    for index, clause in enumerate(clauses):
        if not isinstance(clause, Mapping):
            errors.append(f"factual_clauses[{index}] must be an object")
            continue
        clause_text = clause.get("clause")
        fact_ids = clause.get("fact_ids")
        if not isinstance(clause_text, str) or not clause_text.strip():
            errors.append(f"factual_clauses[{index}].clause must be non-empty")
        if not isinstance(fact_ids, list):
            errors.append(f"factual_clauses[{index}].fact_ids must be an array")
            continue
        try:
            ids = _unique_ids(fact_ids, f"factual_clauses[{index}].fact_ids")
        except CandidateActorError as exc:
            errors.append(str(exc))
            ids = []
        cited.update(ids)
        if not ids:
            errors.append(f"factual_clauses[{index}] must cite at least one fact")
        for fact_id in ids:
            fact = fact_map.get(fact_id)
            if fact is None:
                if fact_id not in granted:
                    errors.append(f"factual_clauses[{index}] cites a fact outside the current grant: {fact_id}")
                continue
            statement = fact.get("statement_text", "")
            ownership = fact.get("ownership", {})
            disclosure = fact.get("disclosure", {})
            if not isinstance(clause_text, str):
                errors.append(f"factual_clauses[{index}] is not supported by cited fact {fact_id}")
            else:
                supported, support_issues = _conservative_clause_support(clause_text, fact)
                if not supported:
                    errors.append(
                        f"factual_clauses[{index}] fails conservative support for {fact_id}: "
                        f"{'; '.join(support_issues)}"
                    )
            finding, ownership_issue = _ownership_finding(clause_text or "", fact)
            ownership_findings.append(finding)
            if ownership_issue:
                errors.append(ownership_issue)
            if isinstance(disclosure, Mapping) and disclosure.get("eligibility") in {"protected", "protected_summary"}:
                if fact_id not in safe_summary_ids:
                    errors.append(f"protected fact {fact_id} was cited without an authorized safe-summary grant")
                protected_issue = _protected_term_issue(answer_text if isinstance(answer_text, str) else "", clause_text or "", fact)
                if protected_issue:
                    protected_findings.append(protected_issue)
                    errors.append(protected_issue)
            if isinstance(disclosure, Mapping):
                earliest = int(disclosure.get("earliest_turn", 0))
                if earliest > turn_number:
                    temporal_findings.append(f"fact {fact_id} earliest_turn={earliest} exceeds turn {turn_number}")
                    errors.append(temporal_findings[-1])
                prerequisites = set(disclosure.get("prerequisite_fact_ids", []))
                if not prerequisites.issubset(already):
                    temporal_findings.append(f"fact {fact_id} prerequisites are not already revealed")
                    errors.append(temporal_findings[-1])
            _ = statement  # Keeps the support shape explicit for reviewers.

    cited.update(correction_superseded)
    cited.update(correction_active)
    if not cited.issubset(granted):
        errors.append(f"response cites facts outside the current grant: {sorted(cited - granted)}")
    if not disclosed.issubset(granted):
        errors.append(f"response discloses facts outside the current grant: {sorted(disclosed - granted)}")
    if cited - correction_superseded - correction_active and not (cited - correction_superseded - correction_active).issubset(disclosed):
        errors.append("every currently asserted cited fact must be listed in disclosed_fact_ids")
    if not correction_active.issubset(disclosed):
        errors.append("correction.active_fact_ids must be listed in disclosed_fact_ids")
    if disclosed & blocked:
        errors.append(f"response discloses blocked facts: {sorted(disclosed & blocked)}")
    if disclosed & superseded:
        errors.append(f"response reactivates superseded facts: {sorted(disclosed & superseded)}")

    if correction_is:
        if not correction_superseded or not correction_active:
            errors.append("a correction must name both superseded and active facts")
        if correction_superseded & correction_active:
            errors.append("a correction cannot supersede and activate the same fact")
        if active_prior and not (correction_superseded & active_prior):
            errors.append("correction does not supersede an active prior fact")
        if _DISHONESTY_RE.search(answer_text if isinstance(answer_text, str) else ""):
            errors.append("correction invents a dishonesty admission not authorized by the actor contract")
    elif correction_superseded or correction_active:
        errors.append("correction fact IDs require correction.is_correction=true")

    if payload.get("boundary_action") == "protected_boundary" and not any(
        isinstance(fact_map.get(fact_id, {}).get("disclosure"), Mapping)
        and fact_map[fact_id]["disclosure"].get("eligibility") in {"protected", "protected_summary"}
        for fact_id in cited
        if fact_id in fact_map
    ):
        errors.append("protected_boundary action requires an authorized protected boundary fact")
    if payload.get("boundary_action") == "ownership_boundary" and not any(
        fact_map.get(fact_id, {}).get("ownership", {}).get("status") in {"partial", "team_owned", "not_owned", "ambiguous"}
        for fact_id in cited
        if fact_id in fact_map
    ):
        warnings.append("ownership_boundary action has no explicitly partial/team/unowned cited fact")
    if payload.get("boundary_action") == "honest_gap" and not any(
        fact_map.get(fact_id, {}).get("ownership", {}).get("status") == "not_owned"
        or fact_map.get(fact_id, {}).get("category") in {"unknown", "boundary"}
        for fact_id in cited
        if fact_id in fact_map
    ):
        warnings.append("honest_gap action has no explicitly not-owned or boundary fact")

    resume_references = payload.get("resume_claim_references")
    resume_reference_errors, resume_reference_tokens = _validate_resume_claim_references(
        answer_text if isinstance(answer_text, str) else "",
        resume_references,
        projection,
    )
    errors.extend(resume_reference_errors)
    if isinstance(answer_text, str):
        errors.extend(_validate_text_clause_coverage(answer_text, clauses, resume_reference_tokens))
        if _INTERNAL_SPEECH_RE.search(answer_text):
            errors.append("answer_text contains evaluator or prompt-internal language")
    else:
        errors.append("answer_text cannot be checked for clause coverage")

    expected_disclosed = cited - correction_superseded
    if disclosed != expected_disclosed:
        missing = sorted(expected_disclosed - disclosed)
        extra = sorted(disclosed - expected_disclosed)
        if missing:
            errors.append(f"disclosed_fact_ids omits cited active facts: {missing}")
        if extra:
            errors.append(f"disclosed_fact_ids contains facts not asserted by clauses: {extra}")

    status = "accepted" if not errors else "rejected"
    return CandidateActorValidationV1(
        status=status,
        canonical=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        cited_fact_ids=tuple(sorted(cited)),
        disclosed_fact_ids=tuple(sorted(disclosed)),
        ownership_findings=tuple(ownership_findings),
        protected_findings=tuple(dict.fromkeys(protected_findings)),
        temporal_findings=tuple(dict.fromkeys(temporal_findings)),
    )


# Short alias for callers that mirror the older trial helper name.
validate_actor_response = validate_actor_response_v1


@dataclass(frozen=True)
class GenerationMetadataV1:
    mode: str
    provider: str
    model: str
    seed: int | None
    latency_ms: float
    deterministic_replay: bool
    raw_output_type: str
    raw_output_sha256: str
    error_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "seed": self.seed,
            "latency_ms": self.latency_ms,
            "deterministic_replay": self.deterministic_replay,
            "raw_output_type": self.raw_output_type,
            "raw_output_sha256": self.raw_output_sha256,
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class CandidateActorResponseV1:
    """Validated candidate speech plus non-speech metadata."""

    answer_text: str
    factual_clauses: tuple[dict[str, Any], ...]
    disclosed_fact_ids: tuple[str, ...]
    behavior_mode: str
    boundary_action: str
    correction: Mapping[str, Any]
    uncertainty: Mapping[str, Any]
    generation_metadata: Mapping[str, Any]
    validation: Mapping[str, Any]
    resume_claim_references: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_schema_version": RESPONSE_SCHEMA_VERSION,
            "answer_text": self.answer_text,
            "factual_clauses": _deepcopy(list(self.factual_clauses)),
            "disclosed_fact_ids": list(self.disclosed_fact_ids),
            "behavior_mode": self.behavior_mode,
            "boundary_action": self.boundary_action,
            "correction": _deepcopy(dict(self.correction)),
            "uncertainty": _deepcopy(dict(self.uncertainty)),
            "resume_claim_references": _deepcopy(list(self.resume_claim_references)),
            "generation_metadata": _deepcopy(dict(self.generation_metadata)),
            "validation": _deepcopy(dict(self.validation)),
        }


def _empty_response(metadata: GenerationMetadataV1, validation: CandidateActorValidationV1) -> CandidateActorResponseV1:
    return CandidateActorResponseV1(
        answer_text="",
        factual_clauses=(),
        disclosed_fact_ids=(),
        behavior_mode="rejected",
        boundary_action="none",
        correction={"is_correction": False, "superseded_fact_ids": [], "active_fact_ids": []},
        uncertainty={"kind": "unknown", "text": ""},
        generation_metadata=metadata.to_dict(),
        validation=validation.to_dict(),
    )


def _strict_payload(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if isinstance(raw, Mapping):
        payload = _deepcopy(dict(raw))
    elif isinstance(raw, str):
        try:
            payload_value = json.loads(raw)
        except json.JSONDecodeError:
            return None, ["generator output was not strict JSON"]
        if not isinstance(payload_value, dict):
            return None, ["generator output JSON must be an object"]
        payload = payload_value
    else:
        return None, ["generator output must be a JSON object or JSON string"]
    return payload, []


async def _call_generator(generator: Any, prompt: Mapping[str, Any], seed: int | None) -> Any:
    method = getattr(generator, "generate", None)
    if method is None or not callable(method):
        raise CandidateActorError("candidate generator must expose generate(prompt, seed=...)")
    result = method(prompt, seed=seed)
    if inspect.isawaitable(result):
        return await result
    return result


class StaticActorGenerator:
    """Small deterministic fake used for lifecycle and validator tests only."""

    provider = "fixture"
    model = "static-fixture"
    mode = "deterministic"
    deterministic_replay = True

    def __init__(self, payload: Mapping[str, Any] | str):
        self.payload = _deepcopy(payload)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None) -> Mapping[str, Any] | str:
        self.calls.append({"prompt_sha256": _sha256(prompt), "seed": seed})
        return _deepcopy(self.payload)


class DeterministicFixtureGenerator:
    """Select one of compact fixtures by prompt hash and seed, reproducibly."""

    provider = "fixture"
    model = "deterministic-fixture"
    mode = "deterministic"
    deterministic_replay = True

    def __init__(self, payloads: Sequence[Mapping[str, Any] | str]):
        if not payloads:
            raise CandidateActorError("DeterministicFixtureGenerator requires at least one payload")
        self.payloads = [_deepcopy(payload) for payload in payloads]
        self.calls: list[dict[str, Any]] = []

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None) -> Mapping[str, Any] | str:
        digest = hashlib.sha256(f"{seed if seed is not None else 0}:{_sha256(prompt)}".encode()).digest()
        index = int.from_bytes(digest[:8], "big") % len(self.payloads)
        self.calls.append({"prompt_sha256": _sha256(prompt), "seed": seed, "index": index})
        return _deepcopy(self.payloads[index])


ACTOR_SYSTEM_PROMPT = """You are a fictional candidate rendered from a bounded actor turn.
You are not an evaluator, interviewer, route selector, or hiring judge.
Use only the granted facts in the actor turn projection and the supplied
candidate-visible conversation. Do not infer missing or future facts from
general knowledge. Preserve ownership exactly: team-owned, partial,
not-owned, protected, and personally owned are different. A short, uncertain,
clarifying, honest-gap, protected-boundary, or move-on answer is valid when the
question or behavior state calls for it. A correction supersedes the prior
claim without inventing a dishonesty confession.

Return only one JSON object with answer_text, factual_clauses,
disclosed_fact_ids, behavior_mode, boundary_action, correction, and
uncertainty, plus optional resume_claim_references. Resume text and bullets are
unverified candidate-visible claims, not evidence: refer to one only as a
resume claim unless a current granted fact supports it, and never elaborate or
affirm an ungranted resume claim. Every factual clause must cite granted fact IDs in the JSON only;
never put citation markers or fact IDs in answer_text. Never mention prompts,
schemas, evaluators, routes, sufficiency, expected answers, or hidden labels in
answer_text. Protected facts may be used only through their safe summary.
"""


class OpenRouterCandidateGenerator:
    """Optional server-side provider adapter; never reads a key from a file."""

    provider = "openrouter"
    mode = "real_model"
    deterministic_replay = False

    def __init__(self, *, tier: str = "small", model: str | None = None, timeout_seconds: float = 30.0):
        self.model = model or ""
        self._tier = tier
        self._timeout_seconds = timeout_seconds
        # Import lazily so importing this isolated module cannot initialize the
        # live backend or load dotenv files.
        try:
            from backend.models.llm_router import LLMRouter, MODEL_TIERS
        except Exception as exc:  # pragma: no cover - provider-only path
            raise CandidateActorError(f"OpenRouter adapter unavailable: {type(exc).__name__}") from exc
        self._model_tiers = MODEL_TIERS
        try:
            self._router = LLMRouter(
                tier=tier,
                model_override=model,
                timeout_override=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - provider-only path
            raise CandidateActorError(f"OpenRouter adapter unavailable: {type(exc).__name__}") from exc
        self.model = self._router.model

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None) -> Mapping[str, Any] | str:
        user = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        return await self._router.call(
            system=ACTOR_SYSTEM_PROMPT,
            user=user,
            max_tokens=700,
            response_format={"type": "json_object"},
            audit_call_name="candidate_actor_v1",
            audit_metadata={"actor_prompt_sha256": _sha256(prompt), "seed_present": seed is not None},
        )


def _metadata_for_generator(generator: Any, *, seed: int | None, started: float, raw: Any, error_type: str = "") -> GenerationMetadataV1:
    provider = str(getattr(generator, "provider", "unknown"))
    model = str(getattr(generator, "model", type(generator).__name__))
    mode = str(getattr(generator, "mode", "unknown"))
    deterministic_replay = bool(getattr(generator, "deterministic_replay", False))
    return GenerationMetadataV1(
        mode=mode,
        provider=provider,
        model=model,
        seed=seed,
        latency_ms=0.0 if deterministic_replay else round((time.perf_counter() - started) * 1000, 3),
        deterministic_replay=deterministic_replay,
        raw_output_type=type(raw).__name__,
        raw_output_sha256=_sha256(raw if raw is not None else ""),
        error_type=error_type,
    )


class CandidateActorV1:
    """Generate and validate a candidate response without exposing hidden truth."""

    def __init__(
        self,
        generator: CandidateGenerator,
        *,
        seed: int | None = 0,
        world_id: str | None = None,
    ):
        self.generator = generator
        self.seed = seed
        self.world_id = world_id or ""
        self.accepted_responses: list[CandidateActorResponseV1] = []

    @classmethod
    def from_world(
        cls,
        world_id: str,
        generator: CandidateGenerator,
        *,
        seed: int | None = 0,
    ) -> "CandidateActorV1":
        # Load only to prove the requested world exists.  The private object is
        # not stored on the actor instance and is never passed to a generator.
        load_actor_private_projection(world_id)
        return cls(generator, seed=seed, world_id=world_id)

    async def respond(
        self,
        prompt: ActorTurnPromptV1 | Mapping[str, Any] | None = None,
        *,
        actor_turn_projection: Mapping[str, Any] | None = None,
        current_question: str | None = None,
        prior_candidate_visible_conversation: Sequence[CandidateVisibleTurnV1 | Mapping[str, Any]] = (),
        behavior_state: BehaviorStateV1 | Mapping[str, Any] | None = None,
        actor_ledger: Mapping[str, Any] | None = None,
        authorized_safe_summary_fact_ids: Sequence[str] = (),
    ) -> CandidateActorResponseV1:
        if prompt is None:
            if actor_turn_projection is None or current_question is None:
                raise ActorPromptError("respond requires an actor turn projection and exact current question")
            prompt_obj = build_actor_turn_prompt(
                actor_turn_projection,
                current_question=current_question,
                prior_candidate_visible_conversation=prior_candidate_visible_conversation,
                behavior_state=behavior_state,
                actor_ledger=actor_ledger,
                authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
            )
            prompt_dict = prompt_obj.to_dict()
        elif isinstance(prompt, ActorTurnPromptV1):
            prompt_dict = prompt.to_dict()
        elif isinstance(prompt, Mapping):
            if prompt.get("prompt_type") == "candidate_actor_turn_input":
                prompt_dict = _deepcopy(dict(prompt))
                # Re-validate and normalize the trust boundary before passing
                # it to a generator.
                _prompt_parts(prompt_dict)
                _assert_no_forbidden_keys(prompt_dict, label="actor prompt")
            elif current_question is not None:
                prompt_dict = build_actor_turn_prompt(
                    prompt,
                    current_question=current_question,
                    prior_candidate_visible_conversation=prior_candidate_visible_conversation,
                    behavior_state=behavior_state,
                    actor_ledger=actor_ledger,
                    authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
                ).to_dict()
            else:
                raise ActorPromptError("a bare actor projection requires current_question")
        else:
            raise ActorPromptError("prompt must be an ActorTurnPromptV1 or object")

        started = time.perf_counter()
        raw: Any = None
        try:
            raw = await _call_generator(self.generator, prompt_dict, self.seed)
        except Exception as exc:
            metadata = _metadata_for_generator(
                self.generator,
                seed=self.seed,
                started=started,
                raw=raw,
                error_type=type(exc).__name__,
            )
            validation = CandidateActorValidationV1("rejected", False, (f"generator failed: {type(exc).__name__}",))
            return _empty_response(metadata, validation)

        metadata = _metadata_for_generator(self.generator, seed=self.seed, started=started, raw=raw)
        payload, parse_errors = _strict_payload(raw)
        if parse_errors or payload is None:
            validation = CandidateActorValidationV1("rejected", False, tuple(parse_errors or ["invalid generator output"]))
            return _empty_response(metadata, validation)
        validation = validate_actor_response_v1(prompt_dict, payload)
        if not validation.canonical:
            return _empty_response(metadata, validation)

        correction = dict(payload["correction"])
        response = CandidateActorResponseV1(
            answer_text=payload["answer_text"],
            factual_clauses=tuple(_deepcopy(payload["factual_clauses"])),
            disclosed_fact_ids=tuple(sorted(payload["disclosed_fact_ids"])),
            behavior_mode=payload["behavior_mode"],
            boundary_action=payload["boundary_action"],
            correction=correction,
            uncertainty=dict(payload["uncertainty"]),
            generation_metadata=metadata.to_dict(),
            validation=validation.to_dict(),
            resume_claim_references=tuple(_deepcopy(payload.get("resume_claim_references", []))),
        )
        self.accepted_responses.append(response)
        return response

    async def respond_from_trusted_grant(
        self,
        *,
        turn_number: int,
        already_revealed_fact_ids: Sequence[str],
        newly_granted_fact_ids: Sequence[str],
        current_question: str,
        prior_candidate_visible_conversation: Sequence[CandidateVisibleTurnV1 | Mapping[str, Any]] = (),
        behavior_state: BehaviorStateV1 | Mapping[str, Any] | None = None,
        actor_ledger: Mapping[str, Any] | None = None,
        authorized_safe_summary_fact_ids: Sequence[str] = (),
    ) -> CandidateActorResponseV1:
        """Convenience for a trusted offline harness; generator still sees only the final prompt."""

        if not self.world_id:
            raise DisclosureGrantError("respond_from_trusted_grant requires actor world_id")
        projection = build_trusted_actor_turn_projection(
            self.world_id,
            turn_number=turn_number,
            already_revealed_fact_ids=already_revealed_fact_ids,
            newly_granted_fact_ids=newly_granted_fact_ids,
            authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
        )
        return await self.respond(
            actor_turn_projection=projection,
            current_question=current_question,
            prior_candidate_visible_conversation=prior_candidate_visible_conversation,
            behavior_state=behavior_state,
            actor_ledger=actor_ledger,
            authorized_safe_summary_fact_ids=authorized_safe_summary_fact_ids,
        )


def build_review_packet(
    prompt: Mapping[str, Any],
    response: CandidateActorResponseV1 | Mapping[str, Any],
    *,
    case_id: str = "",
) -> dict[str, Any]:
    """Build a reviewer artifact that explicitly withholds evaluator truth."""

    if isinstance(response, CandidateActorResponseV1):
        response_value = response.to_dict()
    elif isinstance(response, Mapping):
        response_value = _deepcopy(dict(response))
    else:
        raise CandidateActorError("response must be a CandidateActorResponseV1 or object")
    if prompt.get("prompt_type") == "candidate_actor_turn_input":
        projection = prompt.get("actor_turn_projection", {})
        question = prompt.get("current_question", "")
        conversation = prompt.get("prior_candidate_visible_conversation", [])
    else:
        projection = prompt
        question = ""
        conversation = []
    assert_safe_actor_turn_projection(projection)
    return {
        "review_packet_schema_version": REVIEW_PACKET_SCHEMA_VERSION,
        "case_id": case_id,
        "world_id": projection.get("world_id", ""),
        "question": question,
        "prior_candidate_visible_conversation": _deepcopy(conversation),
        "granted_fact_ids": list(projection.get("turn_context", {}).get("granted_fact_ids", [])),
        "granted_facts": _deepcopy(projection.get("granted_facts", [])),
        "answer_text": response_value.get("answer_text", ""),
        "factual_clauses": _deepcopy(response_value.get("factual_clauses", [])),
        "disclosed_fact_ids": list(response_value.get("disclosed_fact_ids", [])),
        "behavior_mode": response_value.get("behavior_mode", ""),
        "boundary_action": response_value.get("boundary_action", ""),
        "correction": _deepcopy(response_value.get("correction", {})),
        "uncertainty": _deepcopy(response_value.get("uncertainty", {})),
        "generation_metadata": _deepcopy(response_value.get("generation_metadata", {})),
        "validation": _deepcopy(response_value.get("validation", {})),
        "evaluator_truth_withheld_from_actor": True,
        "evaluator_truth": {"status": "withheld", "available_only_to_trusted_offline_reviewer": True},
    }


__all__ = [
    "ACTOR_PRIVATE_DIR",
    "ACTOR_PROJECTION_DIR",
    "ACTOR_SYSTEM_PROMPT",
    "ActorPromptError",
    "ActorTurnPromptV1",
    "BehaviorStateV1",
    "CandidateActorError",
    "CandidateActorResponseV1",
    "CandidateActorValidationV1",
    "CandidateActorV1",
    "CandidateGenerator",
    "CandidateVisibleTurnV1",
    "DeterministicFixtureGenerator",
    "DisclosureGrantError",
    "GenerationMetadataV1",
    "OpenRouterCandidateGenerator",
    "StaticActorGenerator",
    "assert_safe_actor_turn_projection",
    "build_actor_turn_prompt",
    "build_review_packet",
    "build_trusted_actor_turn_projection",
    "load_actor_private_projection",
    "load_actor_turn_projection",
    "validate_actor_response",
    "validate_actor_response_v1",
]
