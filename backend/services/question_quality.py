from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


GUIDE_PATH = Path(__file__).resolve().parents[1] / "data" / "question_quality_guide.json"


@lru_cache(maxsize=1)
def load_question_quality_guide() -> dict[str, Any]:
    try:
        return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "unavailable", "principles": [], "postures": {}, "bad_question_families": {}}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _word_count(text: str) -> int:
    return len(re.findall(r"[a-zA-Z0-9]+", text or ""))


def _has_answer_lane(text: str) -> bool:
    lowered = _normalize(text)
    has_options = bool(re.search(r"\b(were you|was it|were they|are you|is it)\b", lowered)) and "," in lowered
    has_escape = bool(re.search(r"\b(or was there something else|or was another|or something else|what else was|beyond these|if not these)\b", lowered))
    return has_options and has_escape


def _question_mark_count(text: str) -> int:
    return str(text or "").count("?")


def _pattern_flags(question: str) -> list[dict[str, Any]]:
    lowered = _normalize(question)
    flags: list[dict[str, Any]] = []

    def add(code: str, severity: str, reason: str, evidence: str = "") -> None:
        flags.append({"code": code, "severity": severity, "reason": reason, "evidence": evidence[:160]})

    if re.search(r"\b(which|what)\s+(part|component|area|piece|bit|aspect|section)\b.{0,80}\b(most|more|least)?\s*confident\b", lowered):
        add("self_rating_certainty", "high", "Asks the candidate to self-rate confidence instead of showing evidence.")
    if re.search(r"\b(most confident|strongest area|weakest area|rate yourself|how confident are you)\b", lowered):
        add("self_rating_certainty", "high", "Uses confidence/self-rating language with low evidence value.")

    if re.search(r"\b(specific|exact)\s+(sql\s+)?(script|query|file|property|column|variable|method name|debugger|tool)\b", lowered):
        add("low_signal_implementation_recall", "high", "Asks for tiny implementation recall instead of reasoning.")
    if re.search(r"\b(which|what)\s+(specific\s+|exact\s+)?(debugger|tool)\b.{0,80}\b(run|ran|use|used|reuse|reused)\b", lowered):
        add("low_signal_implementation_recall", "high", "Asks for tool/debugger recall instead of reasoning or consequence.")
    if re.search(r"\bwhat\s+(was\s+the\s+)?(main|primary|specific|exact)?\s*tools?\b.{0,80}\b(use|used|most|mainly|pull|validate|debug|run|ran)\b", lowered):
        add("low_signal_implementation_recall", "high", "Asks for tool recall without a decision or analytical consequence.")
    if re.search(r"\bwhat\s+tools?\s+did\s+you\s+(use|run|try)\b", lowered):
        add("low_signal_implementation_recall", "high", "Asks for tool recall instead of reasoning or consequence.")
    if re.search(r"\bwhat\s+(file|payload|serialization|storage)\s+format\b", lowered):
        add("low_signal_implementation_recall", "high", "Asks for low-level format recall instead of reasoning or consequence.")
    if re.search(r"\b(which|what)\s+team\b.{0,80}\b(owned|handled|managed|responsible|deployed|deployment|deployments)\b", lowered):
        add("low_signal_ownership_recall", "high", "Asks for org-chart ownership recall instead of the candidate's boundary or reasoning.")
    if re.search(r"\b(production\s+)?(dbt|airflow|looker|metabase|mixpanel|segment)\s+deployments?\b", lowered) and not re.search(r"\b(impact|risk|decision|trade[- ]?off|changed|broke|trust|accuracy|denominator|guardrail)\b", lowered):
        add("low_signal_ownership_recall", "high", "Deployment ownership recall is low signal unless tied to a consequence.")
    if re.search(r"\b(which|what)\s+event\s+propert(y|ies)\b", lowered):
        add("low_signal_event_property_recall", "medium", "Event-property recall is often low signal unless tied to analytical consequence.")

    if re.search(r"\b(your|the)\s+framework\s+for\b", lowered) or re.search(r"\bhow do you generally approach\b", lowered):
        add("generic_framework_abstraction", "medium", "Abstract framework prompt risks repeated or performative answers.")
    if re.search(r"\b(can you elaborate|tell me more|say more about|walk me through your thinking)\b", lowered):
        add("generic_low_context_prompt", "medium", "Generic prompt lacks a specific signal target.")

    chain_hits = len(re.findall(r"\b(and how|and why|and what|what else|then how|also how)\b", lowered))
    if chain_hits >= 2:
        add("compound_chain", "high", "Question likely hides multiple asks in one turn.", str(chain_hits))
    if _question_mark_count(question) > 1:
        add("multiple_question_marks", "high", "More than one question mark usually means multiple asks.")
    if _word_count(question) > 55:
        add("overlong_question", "medium", "Question is likely too long to speak clearly.")
    if _word_count(question) > 75:
        add("severely_overlong_question", "high", "Question is too long for one spoken turn.")

    if re.search(r"\b(prove|fake|lying|caught|gotcha)\b", lowered):
        add("hostile_language", "high", "Hostile wording is not allowed.")

    unsupported_internal_terms = (
        "model weights", "modify the weights", "training loop", "optimizer",
        "latent vector", "latent representation", "diffusion noise", "engine parameters",
        "internal parameters",
    )
    for term in unsupported_internal_terms:
        if term in lowered:
            add("possible_unsupported_internals", "medium", "Question asks about internals; verify resume/answer supports that layer.", term)
            break

    if re.search(r"\bwhat (should|can) we (carry|take) forward\b", lowered) and "evidence" not in lowered and "check" not in lowered:
        add("synthesis_without_evidence_check", "low", "Synthesis is better when tied to evidence or a concrete check.")

    return flags


def check_question_readiness(
    question: str,
    *,
    route_kind: str = "",
    posture: str = "",
    turn_number: int = 0,
    surface_kind: str = "",
    expected_space: list[str] | None = None,
) -> dict[str, Any]:
    """
    Deterministic bad-question filter.

    This does not decide whether a question is brilliant. It catches known bad
    families and shape risks before a packet is served or staged.
    """
    text = str(question or "").strip()
    flags: list[dict[str, Any]] = []

    def add(code: str, severity: str, reason: str, evidence: str = "") -> None:
        flags.append({"code": code, "severity": severity, "reason": reason, "evidence": evidence[:160]})

    if not text:
        add("empty_question", "high", "Question text is empty.")
    if text and not text.endswith("?"):
        add("missing_question_mark", "medium", "Question should usually end with a question mark.")
    if text.endswith(("—", "-", ",", ";", ":")):
        add("truncated_question", "high", "Question appears truncated.")
    if _word_count(text) < 6 and route_kind not in {"warm_open", "graceful_exit"}:
        add("too_short_question", "medium", "Question is too short to carry a useful signal.")

    flags.extend(_pattern_flags(text))

    lowered_posture = _normalize(posture)
    if lowered_posture in {"frame", "clarify"}:
        for flag in list(flags):
            if flag["code"] in {"self_rating_certainty", "hostile_language", "compound_chain"}:
                flag["severity"] = "high"
        if re.search(r"\b(prove|defend|justify why you)\b", _normalize(text)):
            add("pressure_in_early_posture", "high", "Frame/clarify should not sound like cross-examination.")
    if lowered_posture == "frame" and re.search(r"\b(were you|was it)\b", _normalize(text)) and "," in text and not _has_answer_lane(text):
        add("closed_answer_lane_without_escape", "medium", "Guided answer lanes need an escape hatch like 'or was there something else?'.")
    if lowered_posture == "synthesize":
        if any(flag["code"] == "self_rating_certainty" for flag in flags):
            add("bad_synthesis_self_rating", "high", "Synthesis should ask for fair conclusion/evidence, not confidence performance.")
    if turn_number >= 10:
        if any(flag["code"] in {"low_signal_implementation_recall", "low_signal_event_property_recall", "low_signal_ownership_recall"} for flag in flags):
            add("late_low_level_probe", "high", "Late interview turns should not introduce low-level definition/recall probes.")
    if not expected_space and route_kind in {"coverage_surface", "coverage_depth_probe", "application_transfer", "second_anchor", "reserve_map_question", "third_surface_probe"}:
        add("missing_expected_space", "low", "Map-backed questions should carry expected-space metadata when possible.")

    high_codes = {flag["code"] for flag in flags if flag.get("severity") == "high"}
    should_block = bool(
        high_codes
        and route_kind not in {"warm_open", "graceful_exit", "complete"}
    )
    return {
        "accepted": not should_block,
        "should_block": should_block,
        "flags": flags,
        "flag_codes": [flag["code"] for flag in flags],
        "severity_counts": {
            "high": sum(1 for flag in flags if flag.get("severity") == "high"),
            "medium": sum(1 for flag in flags if flag.get("severity") == "medium"),
            "low": sum(1 for flag in flags if flag.get("severity") == "low"),
        },
        "guide_version": load_question_quality_guide().get("version", "unknown"),
        "route_kind": route_kind,
        "posture": posture,
        "surface_kind": surface_kind,
    }
