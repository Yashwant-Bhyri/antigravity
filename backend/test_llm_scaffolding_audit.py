"""
Full deterministic LLM scaffolding audit.

This is not a paid model-quality suite. It stress-tests the code around LLM
calls: JSON repair, schema coercion, map/critic parsers, focus attribution,
agenda/verdict gates, historical artifact replay, and nearby mutations of prior
failures.

Run with:
  PYTHONPATH=. python3 -m backend.test_llm_scaffolding_audit
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.models.final_report import build_final_evidence_packet, normalize_final_report_v2
from backend.models.llm_router import _load_json_lenient, _quality_flags
from backend.services.interview_map import (
    _anchor_context_for_focus,
    _blocking_launch_repair_targets,
    _cheap_structural_review,
    _coerce_critic_payload,
    _field_verified_review,
    _focus_boundary_resolution,
    _map_quality_scorecard,
    _parse_dimension_output,
    _question_repair_safety_flags,
    _sub_focus_source_snippets,
    validate_interview_map,
)
from backend.services.orchestrator import (
    _apply_hard_coverage_gate,
    _assessment_coverage,
    _build_question_packet,
    _clone_question_packet,
    _coverage_map_progress,
    _normalize_followups,
    _packet_followups_remaining,
)
from backend.state.interview_agenda import (
    InterviewAgendaState,
    initial_interview_agenda,
    next_secondary_focus,
    weighted_surface_coverage,
)


AUDIT_STATUSES = {
    "solved",
    "solved_but_narrow",
    "masked",
    "hardcoded_risk",
    "still_broken",
    "unknown",
}


@dataclass
class AuditCase:
    case_id: str
    component: str
    failure_family: str
    source: str
    expected_behavior: str
    actual_behavior: str
    status: str
    severity: str = "medium"
    hardcoding_risk: str = "low"
    globality_risk: str = "low"
    recommended_fix: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in AUDIT_STATUSES:
            raise ValueError(f"invalid audit status: {self.status}")


@dataclass
class CallSiteInventoryItem:
    surface: str
    tier: str
    owner: str
    expected_output: str
    parser_or_consumer: str
    current_coverage: str
    risk_note: str = ""


def _short(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _run_case(
    *,
    case_id: str,
    component: str,
    failure_family: str,
    source: str,
    expected_behavior: str,
    fn: Callable[[], tuple[bool, str, dict[str, Any]]],
    severity: str = "medium",
    hardcoding_risk: str = "low",
    globality_risk: str = "low",
    recommended_fix: str = "",
) -> AuditCase:
    started = time.perf_counter()
    try:
        ok, actual, evidence = fn()
    except Exception as exc:  # noqa: BLE001 - audit must classify failures, not hide them.
        ok = False
        actual = f"{type(exc).__name__}: {exc}"
        evidence = {"exception": repr(exc)}
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    evidence = dict(evidence or {})
    evidence["elapsed_ms"] = elapsed_ms
    return AuditCase(
        case_id=case_id,
        component=component,
        failure_family=failure_family,
        source=source,
        expected_behavior=expected_behavior,
        actual_behavior=actual,
        status="solved" if ok else "still_broken",
        severity=severity,
        hardcoding_risk=hardcoding_risk,
        globality_risk=globality_risk,
        recommended_fix=recommended_fix if not ok else "",
        evidence=evidence,
    )


def _ladder_items() -> list[dict[str, Any]]:
    return [
        {
            "posture": "frame",
            "main_question": (
                "When you moved the trial from 7 days to 1 day, were you improving paid conversion, "
                "filtering low-intent users, testing urgency, or was there something else?"
            ),
            "signal_goal": "Frame the decision.",
            "expected_space": ["conversion", "trial quality", "urgency", "other driver"],
            "follow_up_if_shallow": "Which of those was the main business reason?",
            "follow_up_if_strong": "What tradeoff made that choice risky?",
            "information_gain": "high",
            "voice_complexity": "low",
        },
        {
            "posture": "clarify",
            "main_question": "That 42% conversion number - what counted as conversion, and which users were in the denominator?",
            "signal_goal": "Clarify denominator.",
            "expected_space": ["paid conversion", "eligible users", "time window"],
            "follow_up_if_shallow": "What was excluded from that denominator?",
            "follow_up_if_strong": "Which denominator would make the lift look weaker?",
            "information_gain": "high",
            "voice_complexity": "low",
        },
        {
            "posture": "explore",
            "main_question": "What user behavior changed after the trial became shorter, apart from more users paying earlier?",
            "signal_goal": "Explore behavior change.",
            "expected_space": ["activation", "refunds", "repeat use"],
            "follow_up_if_shallow": "What signal showed user quality did not drop?",
            "follow_up_if_strong": "What cohort check gave you confidence?",
            "information_gain": "high",
            "voice_complexity": "low",
        },
        {
            "posture": "pressure",
            "main_question": "If conversion improved but early refunds also rose, would you keep the one-day trial or rethink it?",
            "signal_goal": "Pressure-test guardrail judgment.",
            "expected_space": ["refunds", "retention", "threshold"],
            "follow_up_if_shallow": "Which guardrail would matter most?",
            "follow_up_if_strong": "What threshold would trigger rollback?",
            "information_gain": "high",
            "voice_complexity": "medium",
        },
        {
            "posture": "synthesize",
            "main_question": (
                "Which part are you most confident about: conversion improved, quality held, "
                "the trial change caused the lift, or something else?"
            ),
            "signal_goal": "Synthesize confidence.",
            "expected_space": ["conversion", "quality", "causality", "uncertainty"],
            "follow_up_if_shallow": "Which part has the strongest evidence?",
            "follow_up_if_strong": "Which part would need more proof?",
            "information_gain": "high",
            "voice_complexity": "low",
        },
        {
            "posture": "recover",
            "main_question": "If you do not remember every detail, which part of the trial experiment did you personally analyze?",
            "signal_goal": "Recover ownership signal.",
            "expected_space": ["personal analysis", "scope"],
            "follow_up_if_shallow": "What did you personally calculate?",
            "follow_up_if_strong": "Where did your ownership stop?",
            "information_gain": "medium",
            "voice_complexity": "low",
        },
    ]


def _valid_dimensions(count: int = 3) -> list[dict[str, Any]]:
    base = [
        {
            "id": "decision_frame",
            "label": "Decision frame",
            "resume_anchor": "trial conversion improved from 27% to 42%",
            "surface": "What was the business decision behind reducing the trial from seven days to one?",
            "mechanism": "How did you separate urgency from low-intent trial removal in the conversion lift?",
            "boundary": "What result would make you roll back the one-day trial despite higher conversion?",
            "signal_weight": 3.0,
        },
        {
            "id": "denominator",
            "label": "Denominator",
            "resume_anchor": "42% conversion",
            "surface": "Which users counted in the 42% conversion denominator?",
            "mechanism": "How did you handle users who never reached the trial offer?",
            "boundary": "What denominator mistake would make the conversion lift look fake?",
            "signal_weight": 3.0,
        },
        {
            "id": "guardrails",
            "label": "Guardrails",
            "resume_anchor": "cancellation and refund guardrails",
            "surface": "Which cancellation or refund signal mattered most after the trial change?",
            "mechanism": "How did that guardrail affect your read of the conversion improvement?",
            "boundary": "What guardrail movement would make the business result unacceptable?",
            "signal_weight": 2.5,
        },
    ]
    return base[:count]


def _runtime_area(focus_key: str = "conversion", label: str = "Conversion") -> dict[str, Any]:
    return {
        "label": label,
        "focus_key": focus_key,
        "track_source": "llm",
        "track_schema": "dimension",
        "llm_branch_count": 3,
        "fallback_branch_count": 0,
        "llm_branches": ["decision_frame", "denominator", "guardrails"],
        "fallback_branches": [],
        "sub_focuses": [
            {
                "label": "Trial conversion denominator",
                "sub_focus_key": "trial_denominator",
                "surface_kind": "conversion_experiment",
                "role_relevance_weight": 3.0,
                "profile_importance_weight": 3.0,
                "evidence_strength": 2.7,
                "claim_risk": 2.4,
                "coverage_value": 3.0,
                "source_snippets": ["Optimized trial-to-subscription conversion rate from 27% to 42%."],
            }
        ],
        "resume_snippets": ["Optimized trial-to-subscription conversion rate from 27% to 42%."],
        "question_ladder": _ladder_items(),
        "opener": "When you moved the trial from 7 days to 1 day, what decision were you trying to make?",
        "dimensions": _valid_dimensions(),
        "recovery": {
            "short_answer": "What did you personally calculate?",
            "honest_gap": "Fair. Which part did you personally analyze?",
            "claim_conflict": "Which part did you own versus inherit?",
            "metric_risk": "What denominator made the 42% number valid?",
            "overclaim_risk": "What evidence proves the lift was causal?",
            "bridge": "How does this connect to the next focus area?",
        },
    }


def _coverage(**overrides: Any) -> dict[str, Any]:
    base = {
        "application_transfer_served": True,
        "coverage_dimensions": 4,
        "coverage_evaluated_dimensions": 2,
        "coverage_surfaced_dimensions": 2,
        "coverage_score": 0.55,
        "distinct_focuses": 2,
        "distinct_surfaces": 2,
        "high_value_surfaces_available_count": 2,
        "high_value_surfaces_tested_count": 1,
        "dominant_focus_ratio": 0.50,
        "max_same_surface_streak": 3,
        "breadth_viable": True,
        "full_breadth_viable": True,
        "history_len": 15,
    }
    base.update(overrides)
    return base


def _history() -> list[dict[str, Any]]:
    return [
        {
            "question": "Your conversion improved from 27% to 42%; what moved that lift?",
            "answer": "I reduced the trial window, tracked eligible trial starters, and checked cancellation guardrails.",
            "focus_key": "daily_mantra",
            "focus_label": "Daily Mantra",
            "sub_focus_key": "conversion",
            "sub_focus_label": "Conversion experiment",
        },
        {
            "question": "How did the dashboard change decisions for campaign teams?",
            "answer": "It reconciled AppsFlyer spend with transactions daily, so teams could pause weak ad sets faster.",
            "focus_key": "dashboard",
            "focus_label": "Marketing dashboards",
            "sub_focus_key": "attribution",
            "sub_focus_label": "Attribution dashboard",
        },
    ]


def callsite_inventory() -> list[CallSiteInventoryItem]:
    return [
        CallSiteInventoryItem("resume_parse", "small", "ResumeAgent.parse", "parsed resume dict", "agent schema checks", "parser_contracts"),
        CallSiteInventoryItem("concept_extract", "small", "ConceptAgent.extract", "concept list dict", "agent schema checks", "parser_contracts"),
        CallSiteInventoryItem("seed_question", "small", "FollowUpAgent.generate_seed_question", "plain question string", "_finalize_question_output", "small_model_quality"),
        CallSiteInventoryItem("clarification_fast", "small", "FollowUpAgent.generate_clarification", "plain question string", "_finalize_question_output", "small_model_quality"),
        CallSiteInventoryItem("coverage_dimension_eval", "small", "Orchestrator._evaluate_coverage_dimension", "coverage eval dict", "coverage-map consumer", "small_model_quality"),
        CallSiteInventoryItem("weakness_detection", "medium", "WeaknessAgent.detect", "weakness dict", "agent normalization", "medium_quality"),
        CallSiteInventoryItem("discrepancy_check", "medium", "DiscrepancyAgent.check", "discrepancy dict", "agent schema checks", "medium_quality"),
        CallSiteInventoryItem("reasoning_behavior", "medium", "ReasoningBehaviorAgent.evaluate", "reasoning dict", "agent schema checks", "medium_quality"),
        CallSiteInventoryItem("targeted_followup", "medium", "FollowUpAgent.generate", "plain question string", "_finalize_question_output", "medium_quality"),
        CallSiteInventoryItem("application_transfer", "medium", "ApplicationAgent.generate", "application transfer dict", "agent schema checks", "medium_quality"),
        CallSiteInventoryItem("map_focus_plan", "medium", "interview_map._generate_focus_area_plan", "focus-area plan dict", "plan parser/validator", "medium_quality"),
        CallSiteInventoryItem("map_track_generation", "medium", "interview_map._generate_focus_track", "track dict", "_parse_dimension_output", "this_audit"),
        CallSiteInventoryItem("map_critic", "medium", "interview_map._critique_map_candidate", "critic dict", "_coerce_critic_payload", "this_audit"),
        CallSiteInventoryItem("map_repair", "medium", "interview_map repair pipeline", "patched track/candidate", "field verifier + critic", "this_audit"),
        CallSiteInventoryItem("per_answer_score", "large", "EvaluationAgent.score_answer", "score dict", "evaluation consumer", "tier_matrix_only", "Needs mutation cases around local score over-weighting."),
        CallSiteInventoryItem("final_report", "large", "EvaluationAgent.score_full_interview", "FinalReportV2 dict", "normalize_final_report_v2", "final_report_contract"),
        CallSiteInventoryItem("rest_report", "n/a", "GET /report", "API response dict", "routes.py coercion", "scaffolding_contracts"),
        CallSiteInventoryItem("usage_logging", "n/a", "LLMUsageLogger/QualityLogger", "JSONL metadata", "load_usage_records", "usage_audit"),
    ]


def historical_failure_registry() -> list[dict[str, str]]:
    return [
        {"id": "gemini_ladder_only_rejected", "component": "map_track", "family": "schema_drift"},
        {"id": "missing_recovery_short_answer", "component": "map_track", "family": "schema_drift"},
        {"id": "two_strong_dimensions_rejected", "component": "map_track", "family": "brittle_parser"},
        {"id": "nested_source_snippets_not_promoted", "component": "map_plan", "family": "prompt_contract_mismatch"},
        {"id": "truncated_legacy_opener_trusted", "component": "map_track", "family": "brittle_parser"},
        {"id": "sonnet_critic_schema_instability", "component": "map_critic", "family": "schema_drift"},
        {"id": "field_repair_hid_unrelated_issues", "component": "repair", "family": "under_repair"},
        {"id": "untouched_launch_track_regenerated", "component": "repair", "family": "over_repair"},
        {"id": "deepseek_advisory_mislabeled_timeout", "component": "map_critic", "family": "rescue_masking"},
        {"id": "boundary_false_positive_campaign_churn", "component": "map_critic", "family": "hardcoded_rule"},
        {"id": "early_anti_tunnel_cv_pivot", "component": "agenda", "family": "focus_drift"},
        {"id": "general_focus_overwrite", "component": "agenda", "family": "focus_drift"},
        {"id": "generic_sprint_opener_hijack", "component": "agenda", "family": "prompt_contract_mismatch"},
        {"id": "application_transfer_wrong_domain", "component": "application_transfer", "family": "focus_drift"},
        {"id": "narrow_interview_no_hire", "component": "final_report", "family": "verdict_overreach"},
        {"id": "report_claim_hype_overpunishment", "component": "final_report", "family": "verdict_overreach"},
    ]


def deterministic_mutation_cases() -> list[AuditCase]:
    cases: list[AuditCase] = []

    cases.append(_run_case(
        case_id="json_lenient_extra_wrapper_noise",
        component="llm_router",
        failure_family="schema_drift",
        source="synthetic_mutation",
        expected_behavior="accept",
        fn=lambda: (
            _load_json_lenient('```json\n{"ready": true, "issues": []}\n```') == {"ready": True, "issues": []},
            "parsed fenced object without inventing content",
            {"parsed": _load_json_lenient('```json\n{"ready": true, "issues": []}\n```')},
        ),
    ))

    cases.append(_run_case(
        case_id="json_lenient_rejects_nested_fragment",
        component="llm_router",
        failure_family="brittle_parser",
        source="synthetic_mutation",
        expected_behavior="fail_closed",
        fn=lambda: (
            _load_json_lenient('prefix {bad json ["nested"]') is None,
            "rejected malformed outer object instead of parsing nested array",
            {"parsed": _load_json_lenient('prefix {bad json ["nested"]')},
        ),
    ))

    def _quality_flag_case() -> tuple[bool, str, dict[str, Any]]:
        flags = _quality_flags(
            raw_text='```json\n{"a": 1',
            cleaned_text='{"a": 1',
            parsed=None,
            response_format={"type": "json_object"},
        )
        return "json_parse_failed" in flags and "brace_mismatch" in flags, "quality flags expose malformed JSON", {"flags": flags}

    cases.append(_run_case(
        case_id="quality_flags_malformed_json_visible",
        component="llm_router",
        failure_family="schema_drift",
        source="synthetic_mutation",
        expected_behavior="warn_only",
        fn=_quality_flag_case,
    ))

    def _ladder_only_case() -> tuple[bool, str, dict[str, Any]]:
        raw = {
            "question_ladder": _ladder_items(),
            "opener": "",
            "dimensions": [],
            "recovery": {},
            "candidate_q4_options": [],
        }
        parsed = _parse_dimension_output(raw, {"focus_key": "conversion", "label": "Conversion"})
        ok = bool(parsed.get("opener")) and len(parsed.get("dimensions") or []) >= 2 and parsed["recovery"].get("short_answer")
        return ok, "ladder-only track normalized into legacy compatibility fields", {
            "opener": parsed.get("opener"),
            "dimension_count": len(parsed.get("dimensions") or []),
            "recovery_keys": sorted((parsed.get("recovery") or {}).keys()),
        }

    cases.append(_run_case(
        case_id="gemini_ladder_only_track_replay",
        component="map_track",
        failure_family="schema_drift",
        source="historical_failure_registry",
        expected_behavior="accept",
        fn=_ladder_only_case,
        recommended_fix="Keep ladder as source-of-truth until runtime fully drops legacy fields.",
    ))

    def _two_dim_case() -> tuple[bool, str, dict[str, Any]]:
        raw = {
            "question_ladder": _ladder_items(),
            "opener": "When you moved the trial from 7 days to 1 day, what decision were you trying to make?",
            "dimensions": _valid_dimensions(2),
            "recovery": {},
        }
        parsed = _parse_dimension_output(raw, {"focus_key": "conversion", "label": "Conversion"})
        return len(parsed.get("dimensions") or []) == 2, "accepted two dimensions only with complete high-info ladder", {
            "dimension_count": len(parsed.get("dimensions") or []),
            "postures": [item.get("posture") for item in parsed.get("question_ladder") or []],
        }

    cases.append(_run_case(
        case_id="two_strong_dimensions_complete_ladder",
        component="map_track",
        failure_family="brittle_parser",
        source="historical_failure_registry",
        expected_behavior="accept",
        fn=_two_dim_case,
    ))

    def _nested_snippet_case() -> tuple[bool, str, dict[str, Any]]:
        seed = {
            "focus_key": "retention",
            "sub_focuses": [
                {
                    "label": "Retention lift",
                    "source_snippets": ["Increased user retention from 25% to 42% through A/B testing."],
                }
            ],
        }
        snippets = _sub_focus_source_snippets(seed)
        anchor = _anchor_context_for_focus(seed)
        ok = bool(snippets) and "25% to 42%" in anchor
        return ok, "nested sub-focus snippets feed anchor context", {"snippets": snippets, "anchor": anchor}

    cases.append(_run_case(
        case_id="nested_source_snippets_promoted",
        component="map_plan",
        failure_family="prompt_contract_mismatch",
        source="historical_failure_registry",
        expected_behavior="accept",
        fn=_nested_snippet_case,
    ))

    def _truncated_opener_case() -> tuple[bool, str, dict[str, Any]]:
        raw = {
            "question_ladder": _ladder_items(),
            "opener": "At Daily Mantra, you increased retention from 25% to 42%. Before we",
            "dimensions": _valid_dimensions(2),
            "recovery": {},
        }
        parsed = _parse_dimension_output(raw, {"focus_key": "retention", "label": "Retention"})
        flags = _question_repair_safety_flags(raw["opener"])
        ok = "appears_truncated" in flags and parsed["opener"] != raw["opener"] and parsed["opener"].endswith("?")
        return ok, "truncated legacy opener replaced by ladder opener", {"flags": flags, "opener": parsed.get("opener")}

    cases.append(_run_case(
        case_id="truncated_legacy_opener_replaced",
        component="map_track",
        failure_family="brittle_parser",
        source="historical_failure_registry",
        expected_behavior="repair_surgically",
        fn=_truncated_opener_case,
    ))

    def _critic_list_case() -> tuple[bool, str, dict[str, Any]]:
        raw = [
            {"focus_key": "conversion", "score": 8.0, "issues": []},
            {"issue_scope": "field_level", "focus_key": "conversion", "path": "opener", "action": "surgical_repair", "reason": "Too long."},
        ]
        payload, notes = _coerce_critic_payload(raw)
        ok = bool(payload.get("focus_reviews")) and bool(payload.get("typed_issues"))
        return ok, "critic list shape recovered into typed payload", {"payload": payload, "notes": notes}

    cases.append(_run_case(
        case_id="sonnet_critic_list_shape_recovered",
        component="map_critic",
        failure_family="schema_drift",
        source="historical_failure_registry",
        expected_behavior="repair_surgically",
        fn=_critic_list_case,
    ))

    def _critic_malformed_case() -> tuple[bool, str, dict[str, Any]]:
        payload, notes = _coerce_critic_payload('{"ready": true, "overall_score": 8.1, "focus_reviews": [')
        ok = payload.get("_critic_unrecoverable_shape") is True and bool(notes)
        return ok, "malformed critic JSON marked unrecoverable, not silently default-ready", {"payload": payload, "notes": notes}

    cases.append(_run_case(
        case_id="sonnet_critic_malformed_fails_closed",
        component="map_critic",
        failure_family="schema_drift",
        source="synthetic_mutation",
        expected_behavior="fail_closed",
        fn=_critic_malformed_case,
    ))

    def _field_repair_leftover_case() -> tuple[bool, str, dict[str, Any]]:
        previous = {
            "ready": False,
            "typed_issues": [
                {"focus_key": "retention", "path": "opener", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad opener."},
                {"focus_key": "conversion", "path": "question_ladder[3].follow_up_if_strong", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad follow-up."},
            ],
            "repair_targets": [
                {"focus_key": "retention", "path": "opener", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad opener."},
                {"focus_key": "conversion", "path": "question_ladder[3].follow_up_if_strong", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad follow-up."},
            ],
        }
        repaired = {
            "focus_areas": [
                {
                    "focus_key": "retention",
                    "_repair_provenance": [{"focus_key": "retention", "path": "opener", "accepted_by": "field_verifier"}],
                }
            ]
        }
        review = _field_verified_review(previous, repaired)
        ok = len(review.get("typed_issues") or []) == 1 and review["typed_issues"][0]["focus_key"] == "conversion"
        return ok, "field verifier removes only repaired issue and preserves unrelated issues", {"review": review}

    cases.append(_run_case(
        case_id="field_repair_preserves_unrelated_issue",
        component="repair",
        failure_family="under_repair",
        source="historical_failure_registry",
        expected_behavior="warn_only",
        fn=_field_repair_leftover_case,
    ))

    def _indexed_repair_target_case() -> tuple[bool, str, dict[str, Any]]:
        review = {
            "focus_reviews": [
                {"focus_key": "retention", "score": 8.0},
                {"focus_key": "taxonomy", "score": 7.8},
            ],
            "typed_issues": [
                {
                    "issue_scope": "readability_level",
                    "focus_key": "",
                    "path": "focus_areas[1].opener",
                    "severity": "major",
                    "action": "surgical_repair",
                    "reason": "Launch opener too long.",
                },
                {
                    "issue_scope": "field_level",
                    "focus_key": "conversion",
                    "path": "dimensions[2].boundary",
                    "severity": "minor",
                    "action": "surgical_repair",
                    "reason": "Later boundary issue.",
                },
            ]
        }
        targets = _blocking_launch_repair_targets(review, ["retention", "taxonomy"])
        ok = len(targets) == 1 and targets[0]["path"] == "focus_areas[1].opener"
        return ok, "only launch-blocking indexed repair target blocks startup", {"targets": targets}

    cases.append(_run_case(
        case_id="indexed_critic_path_localized",
        component="repair",
        failure_family="over_repair",
        source="synthetic_mutation",
        expected_behavior="repair_surgically",
        fn=_indexed_repair_target_case,
    ))

    def _boundary_campaign_case() -> tuple[bool, str, dict[str, Any]]:
        candidate = {
            "focus_areas": [
                {
                    **_runtime_area("retention", "Retention campaign lifecycle"),
                    "sub_focuses": [
                        {
                            "label": "Lifecycle churn retention",
                            "sub_focus_key": "lifecycle_churn",
                            "surface_kind": "retention_experiment",
                            "coverage_value": 3.0,
                            "role_relevance_weight": 3.0,
                            "source_snippets": ["Reduced churn by improving lifecycle campaign targeting."],
                        }
                    ],
                    "opener": "When the lifecycle campaign reduced churn, what user behavior changed first?",
                }
            ]
        }
        review = _cheap_structural_review(candidate, target_role="Product Analyst")
        text = json.dumps(review, ensure_ascii=True).lower()
        ok = "dashboard leakage" not in text and "boundary" not in text
        return ok, "campaign/churn language in retention surface does not trigger dashboard boundary false positive", {"review": review}

    cases.append(_run_case(
        case_id="boundary_checker_campaign_churn_not_dashboard",
        component="map_critic",
        failure_family="hardcoded_rule",
        source="historical_failure_registry",
        expected_behavior="warn_only",
        fn=_boundary_campaign_case,
        hardcoding_risk="medium",
        globality_risk="medium",
    ))

    def _boundary_heuristic_visible_case() -> tuple[bool, str, dict[str, Any]]:
        area = {
            **_runtime_area("retention_without_kind", "Retention campaign lifecycle"),
            "sub_focuses": [
                {
                    "label": "Lifecycle churn retention",
                    "sub_focus_key": "lifecycle_churn",
                    "coverage_value": 2.8,
                    "role_relevance_weight": 2.8,
                    "source_snippets": ["Reduced churn by improving lifecycle campaign targeting."],
                }
            ],
            "opener": "When the lifecycle campaign reduced churn, what user behavior changed first?",
        }
        resolution = _focus_boundary_resolution(area)
        review = _cheap_structural_review({"focus_areas": [area]}, target_role="Product Analyst")
        text = json.dumps(review, ensure_ascii=True).lower()
        ok = (
            resolution.get("heuristic_fallback_used") is True
            and "heuristic_fallback_used" in text
            and "accept_with_warning" in text
        )
        return ok, "missing typed surface_kind uses visible heuristic warning, not silent word-rule routing", {
            "resolution": resolution,
            "review": review,
        }

    cases.append(_run_case(
        case_id="boundary_heuristic_fallback_is_visible",
        component="map_critic",
        failure_family="hardcoded_rule",
        source="synthetic_mutation",
        expected_behavior="warn_only",
        fn=_boundary_heuristic_visible_case,
        hardcoding_risk="medium",
        globality_risk="medium",
        recommended_fix="Keep shrinking heuristic fallback usage by requiring typed surface_kind in generated focus plans.",
    ))

    def _wrong_surface_kind_case() -> tuple[bool, str, dict[str, Any]]:
        area = {
            **_runtime_area("dashboard_wrong_kind", "Dashboard attribution"),
            "surface_kind": "dashboard_reporting",
            "sub_focuses": [
                {
                    "label": "Dashboard attribution",
                    "sub_focus_key": "dashboard_attribution",
                    "surface_kind": "dashboard_reporting",
                    "coverage_value": 2.8,
                    "role_relevance_weight": 2.8,
                }
            ],
            "opener": "In the YOLO vehicle tracking benchmark, which optical-flow failure mattered most?",
            "question_ladder": [
                {**item, "main_question": "In the YOLO vehicle tracking benchmark, which optical-flow failure mattered most?"}
                if item["posture"] == "frame" else item
                for item in _ladder_items()
            ],
        }
        review = _cheap_structural_review({"focus_areas": [area]}, target_role="Product Analyst")
        text = json.dumps(review, ensure_ascii=True).lower()
        ok = "dashboard/acquisition question leaks into unrelated technical work" in text and "surgical_repair" in text
        return ok, "typed dashboard surface catches off-domain CV question as local repair, not plan regen", {"review": review}

    cases.append(_run_case(
        case_id="wrong_surface_kind_question_gets_local_repair",
        component="map_critic",
        failure_family="focus_drift",
        source="synthetic_mutation",
        expected_behavior="repair_surgically",
        fn=_wrong_surface_kind_case,
        severity="high",
    ))

    def _ladder_missing_weights_combo_case() -> tuple[bool, str, dict[str, Any]]:
        raw = {
            "question_ladder": _ladder_items(),
            "opener": "",
            "dimensions": [],
            "recovery": {},
        }
        seed = {
            "focus_key": "messy_focus",
            "label": "Messy focus",
            "sub_focuses": [
                {"label": "Noisy high-value surface", "coverage_value": "bad", "role_relevance_weight": "bad"}
            ],
        }
        parsed = _parse_dimension_output(raw, seed)
        candidate = {
            "focus_areas": [
                {
                    **parsed,
                    "focus_key": "messy_focus",
                    "label": "Messy focus",
                    "track_source": "llm",
                    "llm_branch_count": len(parsed.get("dimensions") or []),
                    "fallback_branch_count": 0,
                    "sub_focuses": seed["sub_focuses"],
                }
            ]
        }
        validation = validate_interview_map(candidate, require_all_llm=False)
        focus_report = (validation.get("focus_reports") or [{}])[0]
        ok = (
            bool(parsed.get("opener"))
            and focus_report.get("ready") is True
            and focus_report.get("is_rich") is True
            and focus_report.get("fallback_branch_count") == 0
        )
        return ok, "ladder-only track with noisy weights normalizes as rich/LLM-ready without fake fallback branches", {
            "parsed_dimension_count": len(parsed.get("dimensions") or []),
            "validation": validation,
        }

    cases.append(_run_case(
        case_id="ladder_only_track_with_noisy_weights_combo",
        component="map_track",
        failure_family="schema_drift",
        source="synthetic_mutation",
        expected_behavior="accept",
        fn=_ladder_missing_weights_combo_case,
        globality_risk="medium",
    ))

    def _packet_focus_case() -> tuple[bool, str, dict[str, Any]]:
        try:
            _build_question_packet(
                question_text="What moved that metric?",
                sprint=1,
                route_kind="trajectory_map_surface",
                parsed_resume={},
                resume="",
                focus_key_override="general",
            )
        except RuntimeError as exc:
            return "missing map focus" in str(exc), "map-backed general focus fails closed", {"exception": str(exc)}
        return False, "map-backed general focus was silently accepted", {}

    cases.append(_run_case(
        case_id="map_backed_packet_rejects_general_focus",
        component="agenda",
        failure_family="focus_drift",
        source="historical_failure_registry",
        expected_behavior="fail_closed",
        fn=_packet_focus_case,
        severity="high",
    ))

    def _followup_char_split_case() -> tuple[bool, str, dict[str, Any]]:
        packet = {"followups": "What is the denominator?", "asked_followup_count": "bad", "max_followups": "bad"}
        cloned = _clone_question_packet(packet)
        ok = _normalize_followups("What is the denominator?") == [] and cloned["followups"] == [] and _packet_followups_remaining(packet) == []
        return ok, "string followups do not char-split into bogus followup queue", {"cloned": cloned}

    cases.append(_run_case(
        case_id="followup_queue_rejects_string_char_split",
        component="agenda",
        failure_family="brittle_parser",
        source="synthetic_mutation",
        expected_behavior="accept",
        fn=_followup_char_split_case,
    ))

    def _agenda_secondary_weight_case() -> tuple[bool, str, dict[str, Any]]:
        interview_map = {
            "focus_areas": [
                _runtime_area("retention", "Daily Mantra retention"),
                {
                    **_runtime_area("dashboard", "Dashboard attribution"),
                    "sub_focuses": [{"label": "Dashboard attribution", "sub_focus_key": "dashboard_attribution", "coverage_value": 2.8}],
                },
                {
                    **_runtime_area("cv_benchmarking", "Computer vision benchmarking"),
                    "sub_focuses": [{"label": "CV benchmarking", "sub_focus_key": "cv_methods", "coverage_value": 1.2}],
                },
            ]
        }
        state = {"interview_trajectory_map": interview_map, "interview_agenda": initial_interview_agenda(interview_map)}
        key, label = next_secondary_focus(state, avoid_focus="retention")
        ok = key == "dashboard"
        return ok, "secondary pivot prefers role-relevant weighted surface over off-role flashy surface", {"selected": key, "label": label}

    cases.append(_run_case(
        case_id="agenda_secondary_focus_prefers_weighted_role_surface",
        component="agenda",
        failure_family="focus_drift",
        source="historical_failure_registry",
        expected_behavior="accept",
        fn=_agenda_secondary_weight_case,
        hardcoding_risk="low",
        globality_risk="medium",
    ))

    def _agenda_from_bad_shape_case() -> tuple[bool, str, dict[str, Any]]:
        agenda = InterviewAgendaState.from_dict({"phase": "nonsense", "secondary_focus_queue": "bad", "turns_by_focus": []})
        data = agenda.to_dict()
        ok = data["phase"] == "warm_open" and data["secondary_focus_queue"] == [] and data["turns_by_focus"] == {}
        return ok, "agenda state coerces malformed shapes safely", {"agenda": data}

    cases.append(_run_case(
        case_id="agenda_state_bad_shapes_coerced",
        component="agenda",
        failure_family="schema_drift",
        source="synthetic_mutation",
        expected_behavior="accept",
        fn=_agenda_from_bad_shape_case,
    ))

    def _coverage_gate_case() -> tuple[bool, str, dict[str, Any]]:
        coverage = _coverage(
            application_transfer_served=False,
            coverage_evaluated_dimensions=0,
            distinct_focuses=1,
            distinct_surfaces=1,
            dominant_focus_ratio=0.9,
            max_same_surface_streak=6,
        )
        result = _apply_hard_coverage_gate({"hire_recommendation": "NO HIRE", "overall_score": 2, "confidence_score": 0.9}, coverage)
        ok = result["hire_recommendation"] == "INSUFFICIENT_DATA" and result["confidence_score"] <= 0.45
        return ok, "hard coverage gate blocks NO HIRE under narrow/tunneled interview", {"result": result}

    cases.append(_run_case(
        case_id="narrow_tunneled_interview_blocks_no_hire",
        component="final_report",
        failure_family="verdict_overreach",
        source="historical_failure_registry",
        expected_behavior="mark_insufficient_data",
        fn=_coverage_gate_case,
        severity="high",
    ))

    def _coverage_bad_shape_case() -> tuple[bool, str, dict[str, Any]]:
        progress = _coverage_map_progress({"coverage_score": "bad-float", "dimensions": "not-a-list"})
        coverage = _assessment_coverage({
            "history": [{"question": "Q?", "answer": "Substantive answer with enough words to count.", "focus_key": "a", "sub_focus_key": "b"}],
            "coverage_map": {"coverage_score": "bad-float", "dimensions": "not-a-list"},
            "interview_trajectory_map": {},
        })
        ok = progress["score"] == 0.0 and coverage["minimum_viable_completion"] is False
        return ok, "bad coverage shapes coerce to incomplete, not fake-ready", {"progress": progress, "coverage": coverage}

    cases.append(_run_case(
        case_id="coverage_shape_drift_not_fake_ready",
        component="coverage",
        failure_family="schema_drift",
        source="synthetic_mutation",
        expected_behavior="mark_insufficient_data",
        fn=_coverage_bad_shape_case,
    ))

    def _final_report_hype_case() -> tuple[bool, str, dict[str, Any]]:
        packet = build_final_evidence_packet(
            history=_history(),
            resume="Architected analytics tracking and optimized trial conversion from 27% to 42%.",
            weaknesses=[{"type": "ownership", "severity": "medium", "weakness": "Architecture ownership needs follow-up."}],
            assessment_coverage=_coverage(),
            target_role="Product Analyst",
        )
        result = normalize_final_report_v2(
            {
                "hire_recommendation": "MAYBE",
                "overall_score": 6,
                "confidence_score": 0.6,
                "risk_flags": ["Specific architecture ownership claim needs follow-up."],
                "strengths": ["Metric denominator and guardrail reasoning held up."],
            },
            packet,
        )
        ok = result["resume_claim_calibration"]["impact_on_verdict"] == "scoped" and result["hire_recommendation"] == "MAYBE"
        return ok, "resume hype remains scoped claim calibration, not global punishment", {"result": result}

    cases.append(_run_case(
        case_id="final_report_resume_hype_scoped",
        component="final_report",
        failure_family="verdict_overreach",
        source="historical_failure_registry",
        expected_behavior="accept",
        fn=_final_report_hype_case,
    ))

    def _final_report_harsh_language_case() -> tuple[bool, str, dict[str, Any]]:
        packet = build_final_evidence_packet(
            history=_history(),
            resume="Built analytics dashboards.",
            weaknesses=[],
            assessment_coverage=_coverage(distinct_focuses=1, distinct_surfaces=1, dominant_focus_ratio=0.9, max_same_surface_streak=6),
            target_role="Product Analyst",
        )
        result = normalize_final_report_v2(
            {
                "hire_recommendation": "NO HIRE",
                "overall_score": 2,
                "confidence_score": 0.9,
                "summary": "The candidate showed severe inability and completely failed the interview.",
                "risk_flags": ["The candidate completely failed the interview."],
            },
            packet,
        )
        text = json.dumps(result, ensure_ascii=True).lower()
        ok = result["hire_recommendation"] == "INSUFFICIENT_DATA" and "completely failed the interview" not in text
        return ok, "punitive candidate-wide language removed under narrow coverage", {"result": result}

    cases.append(_run_case(
        case_id="final_report_punitive_language_scoped",
        component="final_report",
        failure_family="verdict_overreach",
        source="historical_failure_registry",
        expected_behavior="mark_insufficient_data",
        fn=_final_report_harsh_language_case,
        severity="high",
    ))

    def _final_report_strong_local_scores_narrow_coverage_case() -> tuple[bool, str, dict[str, Any]]:
        packet = build_final_evidence_packet(
            history=_history(),
            resume="Optimized conversion and built dashboards.",
            weaknesses=[],
            per_answer_scores=[
                {"turn_number": 1, "score": 9.0, "answer_excerpt": "Strong answer."},
                {"turn_number": 2, "score": 8.8, "answer_excerpt": "Strong answer."},
            ],
            assessment_coverage=_coverage(
                application_transfer_served=False,
                coverage_evaluated_dimensions=0,
                distinct_focuses=1,
                distinct_surfaces=1,
                high_value_surfaces_tested_count=0,
                dominant_focus_ratio=0.95,
            ),
            target_role="Product Analyst",
        )
        result = normalize_final_report_v2(
            {
                "hire_recommendation": "HIRE",
                "overall_score": 8.8,
                "confidence_score": 0.9,
                "summary": "Very strong local answers.",
                "strengths": ["Strong local analytics reasoning."],
            },
            packet,
        )
        ok = (
            result["hire_recommendation"] == "INSUFFICIENT_DATA"
            and result["overall_score"] <= 5.0
            and result["confidence_score"] <= 0.45
            and result["final_evidence_packet"]["avg_answer_score"] == 8.9
        )
        return ok, "strong per-answer scores cannot override missing app-transfer/coverage/breadth gates", {
            "result": result,
        }

    cases.append(_run_case(
        case_id="strong_local_scores_do_not_override_narrow_coverage",
        component="final_report",
        failure_family="verdict_overreach",
        source="synthetic_mutation",
        expected_behavior="mark_insufficient_data",
        fn=_final_report_strong_local_scores_narrow_coverage_case,
        severity="high",
    ))

    def _weighted_surface_case() -> tuple[bool, str, dict[str, Any]]:
        interview_map = {
            "focus_areas": [
                {
                    **_runtime_area("daily_mantra", "Daily Mantra"),
                    "sub_focuses": [
                        {"label": "Conversion", "sub_focus_key": "conversion", "coverage_value": 3.0},
                        {"label": "Event taxonomy", "sub_focus_key": "taxonomy", "coverage_value": 2.7},
                    ],
                }
            ]
        }
        coverage = weighted_surface_coverage(
            interview_map,
            [{"focus_key": "daily_mantra", "sub_focus_key": "conversion", "route_kind": "trajectory_map_surface"}],
        )
        ok = coverage["high_value_tested_count"] == 1 and coverage["total_weight"] >= 5.0
        return ok, "weighted surface coverage tracks sub-focuses instead of flattening same job into one blob", {"coverage": coverage}

    cases.append(_run_case(
        case_id="weighted_surface_coverage_subfocus_not_flattened",
        component="coverage",
        failure_family="focus_drift",
        source="synthetic_mutation",
        expected_behavior="accept",
        fn=_weighted_surface_case,
    ))

    def _map_validation_case() -> tuple[bool, str, dict[str, Any]]:
        bad_map = {"focus_areas": [{**_runtime_area(), "track_source": "deterministic_fallback", "llm_branch_count": 0, "fallback_branch_count": 3}]}
        validation = validate_interview_map(bad_map, require_all_llm=True)
        ok = validation["ready"] is False and any("deterministic_fallback" in error for error in validation["errors"])
        return ok, "strict map validation rejects deterministic fallback tracks", {"validation": validation}

    cases.append(_run_case(
        case_id="strict_map_validation_rejects_deterministic_fallback",
        component="map_track",
        failure_family="rescue_masking",
        source="synthetic_mutation",
        expected_behavior="fail_closed",
        fn=_map_validation_case,
        severity="high",
    ))

    def _map_scorecard_case() -> tuple[bool, str, dict[str, Any]]:
        scorecard = _map_quality_scorecard({"focus_areas": [_runtime_area()]}, target_role="Product Analyst")
        ok = "top_3_best_questions" in scorecard and "repair_actions_taken" in scorecard and scorecard.get("overall_score", 0) > 0
        return ok, "map scorecard exposes question quality and repair summary fields", {"scorecard": scorecard}

    cases.append(_run_case(
        case_id="map_scorecard_has_review_surfaces",
        component="map_track",
        failure_family="prompt_contract_mismatch",
        source="current_contract",
        expected_behavior="warn_only",
        fn=_map_scorecard_case,
    ))

    return cases


def run_existing_contract_tests() -> list[AuditCase]:
    modules = [
        "backend.test_llm_router_json",
        "backend.test_parser_contracts",
        "backend.test_scaffolding_contracts",
        "backend.test_interview_map_contract",
        "backend.test_interview_map_validation",
        "backend.test_interview_agenda_contract",
        "backend.test_final_report_contract",
        "backend.test_llm_usage_audit",
    ]
    cases: list[AuditCase] = []
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", ".")
    for module in modules:
        started = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", module],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        ok = proc.returncode == 0
        cases.append(AuditCase(
            case_id=f"existing_contract::{module}",
            component="existing_contract_suite",
            failure_family="current_contract",
            source="current_contract",
            expected_behavior="accept",
            actual_behavior="contract test passed" if ok else "contract test failed",
            status="solved" if ok else "still_broken",
            severity="high",
            recommended_fix="" if ok else f"Fix failing deterministic contract module {module} before paid runs.",
            evidence={
                "returncode": proc.returncode,
                "elapsed_ms": elapsed_ms,
                "stdout_tail": proc.stdout[-1600:],
                "stderr_tail": proc.stderr[-1600:],
            },
        ))
    return cases


def _artifact_paths(limit: int = 120) -> list[Path]:
    patterns = [
        "antigravity*.json",
        "antigravity*map_policy*.json",
        "antigravity*sim*.json",
        "antigravity*quality*.json",
        "antigravity*probe*.json",
        "antigravity*matrix*.json",
    ]
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(Path("/tmp").glob(pattern))
    return sorted(paths, key=lambda path: path.stat().st_mtime)[-limit:]


def _iter_artifact_records(path: Path, data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        if "focus_areas" in data or "track" in data or "summary" in data:
            return [data]
        records: list[dict[str, Any]] = []
        for key in ("results", "rows", "cases"):
            value = data.get(key)
            if isinstance(value, list):
                records.extend(item for item in value if isinstance(item, dict))
        return records or [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def replay_historical_artifacts() -> tuple[list[AuditCase], dict[str, Any]]:
    cases: list[AuditCase] = []
    summary = {
        "scanned_paths": 0,
        "json_load_failures": 0,
        "records_seen": 0,
        "map_records": 0,
        "probe_records": 0,
        "report_records": 0,
        "attempt_error_records": 0,
        "interesting_attempt_errors": [],
    }
    for path in _artifact_paths():
        summary["scanned_paths"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            summary["json_load_failures"] += 1
            cases.append(AuditCase(
                case_id=f"artifact_json_load::{path.name}",
                component="historical_artifact",
                failure_family="schema_drift",
                source="historical_artifact",
                expected_behavior="warn_only",
                actual_behavior=f"could not load artifact JSON: {type(exc).__name__}",
                status="unknown",
                severity="low",
                evidence={"path": str(path), "error": str(exc)},
            ))
            continue
        records = _iter_artifact_records(path, data)
        summary["records_seen"] += len(records)
        for index, record in enumerate(records[:50]):
            case_prefix = f"{path.name}::{index}"
            attempt_errors = record.get("attempt_errors") or record.get("generation_attempt_errors") or []
            if attempt_errors:
                summary["attempt_error_records"] += 1
                preview = json.dumps(attempt_errors, ensure_ascii=True, default=str)[:800]
                summary["interesting_attempt_errors"].append({"path": str(path), "preview": preview})
                cases.append(AuditCase(
                    case_id=f"artifact_attempt_errors::{case_prefix}",
                    component="historical_artifact",
                    failure_family="schema_drift",
                    source="historical_artifact",
                    expected_behavior="warn_only",
                    actual_behavior="artifact contains generation attempt errors for review",
                    status="unknown",
                    severity="low",
                    evidence={"path": str(path), "attempt_errors_preview": preview},
                ))

            if isinstance(record.get("track"), dict):
                summary["probe_records"] += 1
                track = record["track"]
                try:
                    parsed = _parse_dimension_output(track, record.get("seed") or {"focus_key": "artifact", "label": "Artifact"})
                    ok = bool(parsed.get("question_ladder")) and bool(parsed.get("opener"))
                    status = "solved" if ok else "still_broken"
                    actual = "track artifact parses under current parser" if ok else "track artifact did not preserve opener/ladder"
                except Exception as exc:  # noqa: BLE001
                    parsed = {"error": str(exc)}
                    status = "unknown"
                    actual = "track artifact obsolete or invalid under current parser"
                cases.append(AuditCase(
                    case_id=f"artifact_track_replay::{case_prefix}",
                    component="map_track",
                    failure_family="schema_drift",
                    source="historical_artifact",
                    expected_behavior="accept",
                    actual_behavior=actual,
                    status=status,
                    severity="low",
                    evidence={"path": str(path), "parsed_preview": _short(parsed, 1200)},
                ))

            if isinstance(record.get("focus_areas"), list):
                summary["map_records"] += 1
                candidate = {
                    "focus_areas": record.get("focus_areas"),
                    "quality_review": record.get("quality_review") or record.get("map_quality_scorecard") or {},
                    "launch_ready": record.get("launch_ready"),
                    "pending_hydration_focus_keys": record.get("pending_hydration_focus_keys") or [],
                }
                validation = validate_interview_map(candidate, require_all_llm=False)
                status = "solved" if validation.get("ready") or record.get("launch_ready") else "unknown"
                cases.append(AuditCase(
                    case_id=f"artifact_map_validation::{case_prefix}",
                    component="map_track",
                    failure_family="schema_drift",
                    source="historical_artifact",
                    expected_behavior="accept",
                    actual_behavior="map artifact validated or was launch-ready" if status == "solved" else "map artifact not ready under current validator",
                    status=status,
                    severity="low",
                    evidence={
                        "path": str(path),
                        "launch_ready": record.get("launch_ready"),
                        "focus_count": len(record.get("focus_areas") or []),
                        "validation": validation,
                    },
                ))

            if record.get("schema_version") == "final_report_v2" or "hire_recommendation" in record:
                summary["report_records"] += 1
                verdict = str(record.get("hire_recommendation") or "").upper()
                gate = record.get("coverage_gate") or {}
                if verdict == "NO HIRE" and gate.get("passed") is False:
                    status = "still_broken"
                    actual = "historical report has NO HIRE with failed coverage gate"
                else:
                    status = "solved"
                    actual = "historical report verdict/gate shape is not obviously contradictory"
                cases.append(AuditCase(
                    case_id=f"artifact_report_gate::{case_prefix}",
                    component="final_report",
                    failure_family="verdict_overreach",
                    source="historical_artifact",
                    expected_behavior="mark_insufficient_data",
                    actual_behavior=actual,
                    status=status,
                    severity="low" if status == "solved" else "medium",
                    evidence={"path": str(path), "verdict": verdict, "coverage_gate": gate},
                ))
    summary["interesting_attempt_errors"] = summary["interesting_attempt_errors"][-20:]
    return cases, summary


def static_hardcoding_scan() -> list[AuditCase]:
    runtime_paths = [
        Path("backend/services/interview_map.py"),
        Path("backend/services/orchestrator.py"),
        Path("backend/agents/application_agent.py"),
        Path("backend/models/final_report.py"),
    ]
    suspicious_terms = [
        "apparao",
        "daily mantra",
        "product analyst",
        "computer vision",
        "cv benchmarking",
        "trial from 7 days to 1 day",
    ]
    cases: list[AuditCase] = []
    root = Path(__file__).resolve().parents[1]
    for rel in runtime_paths:
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8").lower()
        except FileNotFoundError:
            continue
        hits = {}
        for term in suspicious_terms:
            count = text.count(term)
            if count:
                hits[term] = count
        if not hits:
            continue
        status = "hardcoded_risk"
        severity = "low"
        recommended = (
            "Review these occurrences manually. Prompt examples are acceptable only if marked style-only; "
            "routing or validation logic should use typed role/surface metadata instead."
        )
        if rel.name in {"orchestrator.py", "application_agent.py"} and any(term in hits for term in ("apparao", "daily mantra", "cv benchmarking")):
            severity = "medium"
        cases.append(AuditCase(
            case_id=f"static_hardcoding_scan::{rel}",
            component="static_scan",
            failure_family="hardcoded_rule",
            source="current_contract",
            expected_behavior="warn_only",
            actual_behavior="runtime file contains role/resume-specific terms requiring manual review",
            status=status,
            severity=severity,
            hardcoding_risk="medium",
            globality_risk="medium",
            recommended_fix=recommended,
            evidence={"path": str(path), "hits": hits},
        ))
    return cases


def summarize_cases(cases: list[AuditCase]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_component: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for case in cases:
        by_status[case.status] = by_status.get(case.status, 0) + 1
        by_component[case.component] = by_component.get(case.component, 0) + 1
        by_family[case.failure_family] = by_family.get(case.failure_family, 0) + 1
    high_severity_failures = [
        case for case in cases
        if case.status == "still_broken" and case.severity == "high"
    ]
    unresolved = [
        case for case in cases
        if case.status in {"still_broken", "hardcoded_risk", "masked", "solved_but_narrow", "unknown"}
    ]
    return {
        "total_cases": len(cases),
        "by_status": by_status,
        "by_component": by_component,
        "by_failure_family": by_family,
        "high_severity_failures": [case.case_id for case in high_severity_failures],
        "unresolved_or_review_needed": len(unresolved),
        "green_for_paid_confirmation": not high_severity_failures,
    }


def render_markdown(report: dict[str, Any]) -> str:
    cases = [AuditCase(**case) for case in report["cases"]]
    summary = report["summary"]
    lines = [
        "# Antigravity LLM Scaffolding Audit",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Total cases: **{summary['total_cases']}**",
        f"- Status counts: `{summary['by_status']}`",
        f"- Green for targeted paid confirmation: **{summary['green_for_paid_confirmation']}**",
        f"- High-severity failures: `{summary['high_severity_failures']}`",
        "",
        "## Top Risks",
        "",
    ]
    risky = [
        case for case in cases
        if case.status in {"still_broken", "hardcoded_risk", "masked", "solved_but_narrow", "unknown"}
    ]
    risky.sort(key=lambda c: ({"high": 0, "medium": 1, "low": 2}.get(c.severity, 3), c.status, c.case_id))
    if not risky:
        lines.append("- No unresolved audit risks found.")
    for case in risky[:25]:
        lines.append(
            f"- **{case.status}** / `{case.severity}` / `{case.component}` / `{case.case_id}`: "
            f"{case.actual_behavior}"
        )
        if case.recommended_fix:
            lines.append(f"  - Fix: {case.recommended_fix}")

    lines.extend([
        "",
        "## Fixed vs Brittle Table",
        "",
        "| Case | Component | Family | Expected | Actual | Status | Hardcode Risk | Globality Risk |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for case in cases:
        lines.append(
            "| "
            + " | ".join([
                case.case_id,
                case.component,
                case.failure_family,
                case.expected_behavior,
                _short(case.actual_behavior, 120).replace("|", "/"),
                case.status,
                case.hardcoding_risk,
                case.globality_risk,
            ])
            + " |"
        )

    artifact_summary = report.get("artifact_summary") or {}
    lines.extend([
        "",
        "## Historical Artifact Replay",
        "",
        f"- Scanned paths: `{artifact_summary.get('scanned_paths', 0)}`",
        f"- Records seen: `{artifact_summary.get('records_seen', 0)}`",
        f"- Map records: `{artifact_summary.get('map_records', 0)}`",
        f"- Probe records: `{artifact_summary.get('probe_records', 0)}`",
        f"- Report records: `{artifact_summary.get('report_records', 0)}`",
        f"- Attempt-error records: `{artifact_summary.get('attempt_error_records', 0)}`",
        "",
        "## Untested / Weakly Tested Call Sites",
        "",
    ])
    for item in report["inventory"]:
        if "MISSING" in item["current_coverage"] or "tier_matrix_only" in item["current_coverage"] or item.get("risk_note"):
            lines.append(
                f"- `{item['surface']}` ({item['owner']}): coverage=`{item['current_coverage']}`. {item.get('risk_note') or ''}"
            )

    lines.extend([
        "",
        "## Recommended Next Fixes",
        "",
    ])
    recommendations = []
    for case in risky:
        if case.recommended_fix and case.recommended_fix not in recommendations:
            recommendations.append(case.recommended_fix)
    if not recommendations:
        recommendations = [
            "Run the targeted paid confirmation batch only after reviewing hardcoded-risk warnings.",
            "Keep expanding historical replay as more raw LLM quality logs become available.",
        ]
    for rec in recommendations[:12]:
        lines.append(f"- {rec}")
    lines.append("")
    return "\n".join(lines)


def write_report(cases: list[AuditCase], artifact_summary: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": summarize_cases(cases),
        "inventory": [asdict(item) for item in callsite_inventory()],
        "historical_failure_registry": historical_failure_registry(),
        "artifact_summary": artifact_summary,
        "cases": [asdict(case) for case in cases],
    }
    json_path = Path(f"/tmp/antigravity_scaffolding_audit_{timestamp}.json")
    md_path = Path(f"/tmp/antigravity_scaffolding_audit_{timestamp}.md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path, report


def main() -> None:
    cases: list[AuditCase] = []
    cases.extend(run_existing_contract_tests())
    cases.extend(deterministic_mutation_cases())
    artifact_cases, artifact_summary = replay_historical_artifacts()
    cases.extend(artifact_cases)
    cases.extend(static_hardcoding_scan())
    json_path, md_path, report = write_report(cases, artifact_summary)
    print(json.dumps(report["summary"], indent=2, ensure_ascii=True))
    print(f"JSON: {json_path}")
    print(f"MD: {md_path}")
    if report["summary"]["high_severity_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
