"""
Pure contract tests for the live-interview agenda controller.

Run:
  python3 -m backend.test_interview_agenda_contract
"""

from __future__ import annotations

from backend.services.orchestrator import (
    _apply_hard_coverage_gate,
    _assessment_coverage,
    _build_question_packet,
    _infer_focus,
    _infer_grounding_depth,
    _reselect_second_anchor_for_surface,
    _select_agenda_decision,
    _select_third_surface_probe,
    _second_anchor_packet_block_reason,
    _should_force_focus_ratio_rotation,
)
from backend.services.interview_map import select_from_trajectory_map_detailed
from backend.agents.evaluation_agent import _apply_evaluation_sanity_calibration
from backend.state.interview_agenda import initial_interview_agenda
from backend.state.interview_agenda import next_secondary_focus
from backend.state.interview_agenda import next_secondary_surface


def _map_turn(focus_key: str, sub_focus_key: str = "") -> dict:
    return {
        "focus_key": focus_key,
        "sub_focus_key": sub_focus_key,
        "route_kind": "trajectory_map_surface",
    }


def _state() -> dict:
    interview_map = {
        "focus_areas": [
            {"focus_key": "daily_mantra", "label": "Daily Mantra"},
            {"focus_key": "dashboards", "label": "AppsFlyer Dashboards"},
            {"focus_key": "cv_benchmark", "label": "CV Benchmarking"},
        ]
    }
    return {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
        "candidate_state": {"implementation_anchor": "I defined the Daily Mantra event taxonomy."},
        "history": [],
        "question_count": 0,
        "evidence_question_count": 4,
        "application_question_served": False,
        "prepped_application_question": "How would you transfer this instrumentation logic to a new subscription product?",
    }


def test_secondary_focus_prefers_role_relevant_surface_weight() -> None:
    interview_map = {
        "focus_areas": [
            {
                "focus_key": "daily_mantra",
                "label": "Daily Mantra Product Analytics",
                "sub_focuses": [
                    {
                        "label": "retention experiment causal validity",
                        "sub_focus_key": "retention_experiment_causal_validity",
                        "role_relevance_weight": 3.0,
                        "profile_importance_weight": 3.0,
                        "evidence_strength": 3.0,
                        "claim_risk": 2.5,
                        "coverage_value": 3.0,
                    }
                ],
            },
            {
                "focus_key": "cv_benchmark",
                "label": "Computer Vision Benchmarking",
                "sub_focuses": [
                    {
                        "label": "YOLO SORT optical flow benchmark",
                        "sub_focus_key": "yolo_sort_optical_flow_benchmark",
                        "role_relevance_weight": 1.2,
                        "profile_importance_weight": 1.4,
                        "evidence_strength": 2.6,
                        "claim_risk": 2.5,
                        "coverage_value": 1.4,
                    }
                ],
            },
            {
                "focus_key": "dashboard_automation",
                "label": "Dashboard Automation",
                "sub_focuses": [
                    {
                        "label": "AppsFlyer campaign dashboard decision support",
                        "sub_focus_key": "appsflyer_campaign_dashboard_decision_support",
                        "role_relevance_weight": 2.8,
                        "profile_importance_weight": 2.4,
                        "evidence_strength": 2.5,
                        "claim_risk": 1.8,
                        "coverage_value": 2.6,
                    }
                ],
            },
        ]
    }
    state = {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
    }
    focus_key, focus_label = next_secondary_focus(state, avoid_focus="daily_mantra")
    assert focus_key == "dashboard_automation", (focus_key, focus_label)


def test_secondary_surface_can_choose_high_value_same_parent_over_offrole_focus() -> None:
    interview_map = {
        "focus_areas": [
            {
                "focus_key": "seller_marketplace",
                "label": "Seller Marketplace Analytics",
                "sub_focuses": [
                    {
                        "label": "Seller onboarding event taxonomy",
                        "sub_focus_key": "seller_onboarding_taxonomy",
                        "surface_kind": "event_taxonomy",
                        "role_relevance_weight": 2.8,
                        "profile_importance_weight": 2.8,
                        "evidence_strength": 2.7,
                        "coverage_value": 2.7,
                    },
                    {
                        "label": "Marketplace health dashboard decision support",
                        "sub_focus_key": "marketplace_health_dashboard",
                        "surface_kind": "dashboard_reporting",
                        "role_relevance_weight": 3.0,
                        "profile_importance_weight": 2.9,
                        "evidence_strength": 2.8,
                        "coverage_value": 3.0,
                    },
                ],
            },
            {
                "focus_key": "ocr_side_project",
                "label": "OCR Side Project",
                "sub_focuses": [
                    {
                        "label": "Tesseract invoice parser",
                        "sub_focus_key": "tesseract_invoice_parser",
                        "surface_kind": "computer_vision",
                        "role_relevance_weight": 1.1,
                        "profile_importance_weight": 1.1,
                        "evidence_strength": 1.8,
                        "coverage_value": 1.1,
                    }
                ],
            },
        ]
    }
    state = {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
        "history": [
            {
                "focus_key": "seller_marketplace",
                "sub_focus_key": "seller_onboarding_taxonomy",
                "route_kind": "trajectory_map_surface",
            }
        ],
    }
    state["interview_agenda"]["turns_by_surface"] = {"seller_marketplace::seller_onboarding_taxonomy": 1}
    state["interview_agenda"]["turns_by_focus"] = {"seller_marketplace": 1}

    surface = next_secondary_surface(state, avoid_focus="seller_marketplace")

    assert surface["focus_key"] == "seller_marketplace", surface
    assert surface["sub_focus_key"] == "marketplace_health_dashboard", surface
    assert surface["surface_kind"] == "dashboard_reporting", surface


def test_map_selector_preserves_preferred_second_anchor_surface_metadata() -> None:
    interview_map = {
        "focus_areas": [
            {
                "focus_key": "seller_marketplace",
                "label": "Seller Marketplace Analytics",
                "track_schema": "v2_ladder",
                "sub_focuses": [
                    {
                        "label": "Seller onboarding event taxonomy",
                        "sub_focus_key": "seller_onboarding_taxonomy",
                        "surface_kind": "event_taxonomy",
                        "coverage_value": 2.6,
                    },
                    {
                        "label": "Marketplace health dashboard decision support",
                        "sub_focus_key": "marketplace_health_dashboard",
                        "surface_kind": "dashboard_reporting",
                        "coverage_value": 3.0,
                    },
                ],
                "question_ladder": [
                    {
                        "posture": "frame",
                        "main_question": "For the marketplace health dashboard, what decision was it mainly helping product or ops make?",
                        "signal_goal": "Test dashboard decision use",
                        "expected_space": ["product decision", "ops queue", "reconciliation"],
                        "information_gain": "high",
                        "voice_complexity": "low",
                    }
                ],
                "dimensions": [],
            }
        ]
    }

    result = select_from_trajectory_map_detailed(
        interview_map,
        sprint=2,
        focus_key="seller_marketplace",
        answer="Let's move to the dashboard work.",
        entities=[],
        history=[],
        preferred_sub_focus_key="marketplace_health_dashboard",
        preferred_surface_kind="dashboard_reporting",
    )

    assert result, result
    assert result["sub_focus_key"] == "marketplace_health_dashboard", result
    assert result["surface_kind"] == "dashboard_reporting", result


def test_second_anchor_reselects_after_spent_surface() -> None:
    interview_map = {
        "focus_areas": [
            {
                "focus_key": "marketplace_models",
                "label": "Marketplace Modeling",
                "track_schema": "v2_ladder",
                "sub_focuses": [
                    {
                        "label": "dbt grain reconciliation",
                        "sub_focus_key": "dbt_grain_reconciliation",
                        "surface_kind": "data_modeling",
                        "coverage_value": 2.5,
                    },
                    {
                        "label": "Marketplace health dashboard",
                        "sub_focus_key": "marketplace_health_dashboard",
                        "surface_kind": "dashboard_reporting",
                        "coverage_value": 3.0,
                    },
                ],
                "question_ladder": [
                    {
                        "posture": "frame",
                        "main_question": "For the marketplace health dashboard, what decision was it mainly helping product or ops make?",
                        "signal_goal": "Test dashboard decision use",
                        "expected_space": ["decision use", "ops bottleneck", "metric reconciliation"],
                        "information_gain": "high",
                        "voice_complexity": "low",
                        "sub_focus_key": "marketplace_health_dashboard",
                        "sub_focus_label": "Marketplace health dashboard",
                        "surface_kind": "dashboard_reporting",
                    },
                    {
                        "posture": "clarify",
                        "main_question": "In the dbt models, what grain did you choose for joining seller events and support tickets?",
                        "signal_goal": "Test modeling grain",
                        "expected_space": ["seller grain", "ticket joins", "dedupe"],
                        "information_gain": "high",
                        "voice_complexity": "low",
                        "sub_focus_key": "dbt_grain_reconciliation",
                        "sub_focus_label": "dbt grain reconciliation",
                        "surface_kind": "data_modeling",
                    },
                ],
                "dimensions": [],
            }
        ]
    }
    state = {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
    }
    history = [
        {
            "route_kind": "second_anchor",
            "focus_key": "marketplace_models",
            "sub_focus_key": "dbt_grain_reconciliation",
            "surface_kind": "data_modeling",
        }
    ]
    packet = {
        "route_kind": "second_anchor",
        "focus_key": "marketplace_models",
        "sub_focus_key": "dbt_grain_reconciliation",
    }

    assert _second_anchor_packet_block_reason(packet, history) == "second_anchor_surface_already_used"

    replacement = _reselect_second_anchor_for_surface(
        state,
        history,
        sprint=2,
        target={
            "focus_key": "marketplace_models",
            "focus_label": "Marketplace Modeling",
            "sub_focus_key": "dbt_grain_reconciliation",
            "surface_kind": "data_modeling",
            "surface_key": "marketplace_models::dbt_grain_reconciliation",
        },
        answer="Let's move beyond dbt.",
    )

    assert replacement, replacement
    assert replacement["sub_focus_key"] == "marketplace_health_dashboard", replacement
    assert replacement["surface_kind"] == "dashboard_reporting", replacement


def test_application_transfer_beats_depth() -> None:
    state = _state()
    decision = _select_agenda_decision(
        state,
        history=[],
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="trajectory_map_mechanism",
        weakness={"severity": "high", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "application_transfer", decision


def test_application_grounding_precedes_transfer_when_depth_is_ambiguous() -> None:
    state = _state()
    state["coverage_map"] = {
        "application_question": "Imagine this workflow in a new product.",
        "implementation_anchor": "video workflow",
        "grounding_needed": True,
        "grounding_question": "Before I apply this to a new case, were you handling workflow logic, specialized internals, or something else?",
        "max_depth_level": 3,
        "dimensions": [],
    }
    decision = _select_agenda_decision(
        state,
        history=[],
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="trajectory_map_surface",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "application_grounding", decision


def test_application_grounding_answer_routes_to_transfer() -> None:
    state = _state()
    state["application_transfer_arc"] = {
        "grounding_needed": True,
        "grounding_served": True,
        "grounding_done": True,
        "grounding_question": "Were you handling workflow logic or specialized internals?",
    }
    decision = _select_agenda_decision(
        state,
        history=[{"focus_key": "daily_mantra", "route_kind": "application_grounding"}],
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="application_grounding",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "application_transfer", decision
    assert decision["reason"] == "application_grounding_answered_transfer_ready", decision


def test_application_grounding_is_not_assessment_breadth() -> None:
    state = _state()
    state["application_question_served"] = True
    state["history"] = [
        {"focus_key": "daily_mantra", "sub_focus_key": "conversion", "route_kind": "trajectory_map_surface"},
        {"focus_key": "daily_mantra", "route_kind": "application_grounding"},
        {"focus_key": "daily_mantra", "coverage_dimension_id": "denominator", "route_kind": "coverage_surface"},
    ]
    state["coverage_map"] = {
        "coverage_score": 0.5,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    coverage = _assessment_coverage(state)
    assert coverage["distinct_focuses"] == 1, coverage
    assert coverage["distinct_surfaces"] == 2, coverage
    assert coverage["max_same_surface_streak"] == 1, coverage


def test_grounding_depth_caps_specialized_internals_without_confirmation() -> None:
    level, terms = _infer_grounding_depth(
        "Mostly workflow orchestration and review labels, not model internals or embeddings.",
        max_depth_level=4,
    )
    assert level == 2, (level, terms)

    level, terms = _infer_grounding_depth(
        "I handled embedding distance checks and CLIP scores directly for identity drift.",
        max_depth_level=4,
    )
    assert level == 4, (level, terms)
    assert "embedding" in terms or "embeddings" in terms, terms


def test_coverage_not_blocked_by_fatigue() -> None:
    state = _state()
    state["application_question_served"] = True
    state["coverage_map"] = {
        "application_question": "Transfer scenario",
        "implementation_anchor": "event taxonomy",
        "coverage_score": 0,
        "coverage_confidence": 0.6,
        "total_weight": 2,
        "dimensions": [
            {
                "id": "guardrail",
                "label": "Guardrails",
                "description": "Names guardrail metrics",
                "expected_approaches": ["refunds", "retention"],
                "surfacing_question": "What guardrails would you watch?",
                "weight": 1,
                "coverage_state": "not_evaluated",
                "candidate_response": "",
                "surfacing_attempted": False,
            }
        ],
    }
    decision = _select_agenda_decision(
        state,
        history=[_map_turn("daily_mantra")] * 6,
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="application_transfer",
        weakness={"severity": "high", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=True,
    )
    assert decision["route"] == "coverage", decision


def test_focus_pivot_on_continue_false() -> None:
    state = _state()
    state["prepped_application_question"] = ""
    state["evidence_question_count"] = 2
    decision = _select_agenda_decision(
        state,
        history=[_map_turn("daily_mantra")] * 4,
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="trajectory_map_surface",
        weakness={"severity": "high", "continue_probing": False},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "focus_pivot", decision
    assert decision["focus_key"] == "dashboards", decision


def test_no_early_primary_pivot_from_ratio() -> None:
    state = _state()
    state["prepped_application_question"] = ""
    state["evidence_question_count"] = 1
    state["history"] = [_map_turn("daily_mantra")]
    decision = _select_agenda_decision(
        state,
        history=state["history"],
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="trajectory_map_surface",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "phase_depth", decision
    assert decision["focus_key"] == "daily_mantra", decision


def test_background_ratio_guard_uses_evidence_floor() -> None:
    state = _state()
    state["history"] = [_map_turn("daily_mantra")]
    assert not _should_force_focus_ratio_rotation(state, state["history"], "daily_mantra")


def test_map_backed_packet_requires_focus_attribution() -> None:
    try:
        _build_question_packet(
            question_text="What tradeoff did you make there?",
            sprint=1,
            route_kind="trajectory_map_surface",
            parsed_resume={},
            resume="",
        )
    except RuntimeError as exc:
        assert "missing map focus" in str(exc), exc
    else:
        raise AssertionError("map-backed route accepted a general focus packet")


def test_focus_inference_uses_dimension_and_subfocus_text() -> None:
    focus_key, focus_label = _infer_focus(
        "What was the exact denominator for Mantra Track End completion, and how did late events affect it?",
        "",
        {},
        "",
        trajectory_focus_areas=[
            {
                "focus_key": "daily_mantra_event_taxonomy",
                "label": "Daily Mantra Event Taxonomy",
                "anchor_context": "Defined product analytics events for Daily Mantra.",
                "sub_focuses": ["Mantra Track End completion denominator"],
                "dimensions": [
                    {
                        "id": "metric_definition",
                        "label": "Metric Definition",
                        "surface": "What counted as Mantra Track End completion?",
                    }
                ],
            },
            {
                "focus_key": "computer_vision_tracking",
                "label": "Computer Vision Vehicle Tracking",
                "anchor_context": "Benchmarked YOLO, SORT, and optical flow.",
            },
        ],
    )
    assert focus_key == "daily_mantra_event_taxonomy", (focus_key, focus_label)


def test_ratio_pivot_after_primary_floor() -> None:
    state = _state()
    state["prepped_application_question"] = ""
    state["evidence_question_count"] = 4
    state["history"] = [_map_turn("daily_mantra") for _ in range(4)]
    decision = _select_agenda_decision(
        state,
        history=state["history"],
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="trajectory_map_surface",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "focus_pivot", decision
    assert decision["focus_key"] == "dashboards", decision


def test_hard_gate_blocks_tunneled_no_hire() -> None:
    state = _state()
    state["application_question_served"] = True
    state["history"] = [_map_turn("daily_mantra") for _ in range(8)]
    state["coverage_map"] = {
        "coverage_score": 0.2,
        "dimensions": [
            {"coverage_state": "voluntary", "surfacing_attempted": False},
            {"coverage_state": "not_evaluated", "surfacing_attempted": False},
        ],
    }
    coverage = _assessment_coverage(state)
    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "NO HIRE", "overall_score": 3.0, "confidence_score": 0.8, "risk_flags": []},
        coverage,
    )
    assert gated["hire_recommendation"] == "INSUFFICIENT_DATA", gated
    assert gated["coverage_gate"]["passed"] is False, gated


def test_subfocus_surfaces_count_for_completion_breadth() -> None:
    state = _state()
    state["application_question_served"] = True
    state["history"] = [
        {
            "focus_key": "daily_mantra",
            "focus_label": "Daily Mantra",
            "sub_focus_key": "retention_experiment",
            "sub_focus_label": "Retention experiment",
            "route_kind": "trajectory_map_surface",
        },
        {
            "focus_key": "daily_mantra",
            "focus_label": "Daily Mantra",
            "sub_focus_key": "event_taxonomy",
            "sub_focus_label": "Event taxonomy",
            "route_kind": "trajectory_map_surface",
        },
    ]
    state["coverage_map"] = {
        "coverage_score": 0.5,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    coverage = _assessment_coverage(state)
    assert coverage["distinct_focuses"] == 1, coverage
    assert coverage["distinct_surfaces"] == 2, coverage
    assert coverage["minimum_viable_completion"] is True, coverage


def test_three_subfocus_surfaces_avoid_tunnel_gate() -> None:
    state = _state()
    state["application_question_served"] = True
    state["history"] = [
        _map_turn("daily_mantra", "retention"),
        _map_turn("daily_mantra", "conversion"),
        _map_turn("daily_mantra", "event_taxonomy"),
    ]
    state["coverage_map"] = {
        "coverage_score": 0.7,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    coverage = _assessment_coverage(state)
    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "NO HIRE", "overall_score": 3.0, "confidence_score": 0.8, "risk_flags": []},
        coverage,
    )
    assert gated["coverage_gate"]["passed"] is True, gated
    assert coverage["distinct_focuses"] == 1, coverage
    assert coverage["distinct_surfaces"] == 3, coverage


def test_coverage_dimensions_count_as_distinct_surfaces() -> None:
    state = _state()
    state["application_question_served"] = True
    state["history"] = [
        {"focus_key": "daily_mantra", "coverage_dimension_id": "metric_denominator", "route_kind": "coverage_surface"},
        {"focus_key": "daily_mantra", "coverage_dimension_id": "proxy_metric", "route_kind": "coverage_surface"},
        {"focus_key": "daily_mantra", "coverage_dimension_id": "stakeholder_translation", "route_kind": "coverage_surface"},
        _map_turn("daily_mantra", "retention_experiment"),
    ]
    state["coverage_map"] = {
        "coverage_score": 0.5,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    coverage = _assessment_coverage(state)
    assert coverage["distinct_focuses"] == 1, coverage
    assert coverage["distinct_surfaces"] == 4, coverage
    assert coverage["max_same_surface_streak"] == 1, coverage
    assert coverage["surfaces_by_focus"]["daily_mantra"] == [
        "coverage::metric_denominator",
        "coverage::proxy_metric",
        "coverage::stakeholder_translation",
        "retention_experiment",
    ], coverage


def test_second_anchor_budget_forces_synthesis_close() -> None:
    state = _state()
    state["application_question_served"] = True
    state["evidence_question_count"] = 13
    state["question_count"] = 12
    state["coverage_map"] = {
        "coverage_score": 0.9,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    history = [
        {"focus_key": "dashboards", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
        {"focus_key": "dashboards", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
        {"focus_key": "cv_benchmark", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
    ] + [
        {"focus_key": "daily_mantra", "route_kind": "trajectory_map_boundary", "agenda_phase": "primary_depth"}
        for _ in range(9)
    ]
    decision = _select_agenda_decision(
        state,
        history=history,
        current_focus_key="cv_benchmark",
        current_focus_label="CV Benchmarking",
        answered_route_kind="second_anchor",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "synthesis_close", decision
    assert decision["reason"] == "second_anchor_budget_exhausted", decision


def test_second_anchor_budget_before_synthesis_floor_keeps_grounded_depth() -> None:
    state = _state()
    state["application_question_served"] = True
    state["evidence_question_count"] = 10
    state["question_count"] = 9
    state["coverage_map"] = {
        "coverage_score": 0.9,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    history = [
        {"focus_key": "dashboards", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
        {"focus_key": "dashboards", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
        {"focus_key": "cv_benchmark", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
    ] + [
        {"focus_key": "daily_mantra", "route_kind": "trajectory_map_boundary", "agenda_phase": "primary_depth"}
        for _ in range(6)
    ]
    decision = _select_agenda_decision(
        state,
        history=history,
        current_focus_key="dashboards",
        current_focus_label="Dashboards",
        answered_route_kind="second_anchor",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "phase_depth", decision
    assert decision["reason"] == "second_anchor_budget_wait_until_synthesis_floor", decision


def test_second_anchor_waits_until_turn_ten_window() -> None:
    state = _state()
    state["application_question_served"] = True
    state["evidence_question_count"] = 8
    state["question_count"] = 7
    state["coverage_map"] = {
        "coverage_score": 0.9,
        "dimensions": [{"coverage_state": "voluntary", "surfacing_attempted": True}],
    }
    decision = _select_agenda_decision(
        state,
        history=[],
        current_focus_key="daily_mantra",
        current_focus_label="Daily Mantra",
        answered_route_kind="coverage_surface",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "phase_depth", decision
    assert decision["reason"] == "second_anchor_wait_until_floor", decision


def test_final_synthesis_moves_to_graceful_exit() -> None:
    state = _state()
    state["application_question_served"] = True
    state["evidence_question_count"] = 14
    state["coverage_map"] = None
    decision = _select_agenda_decision(
        state,
        history=[
            {"focus_key": "dashboards", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
            {"focus_key": "dashboards", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
            {"focus_key": "cv_benchmark", "route_kind": "synthesis_close", "agenda_phase": "synthesis_close"},
        ],
        current_focus_key="cv_benchmark",
        current_focus_label="CV Benchmarking",
        answered_route_kind="synthesis_close",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "graceful_exit", decision
    assert decision["reason"] == "final_synthesis_already_served", decision


def test_final_synthesis_never_reopens_depth_for_floor() -> None:
    state = _state()
    state["application_question_served"] = True
    state["evidence_question_count"] = 10
    state["coverage_map"] = None
    decision = _select_agenda_decision(
        state,
        history=[
            {"focus_key": "technical_anchor", "route_kind": "synthesis_close", "agenda_phase": "synthesis_close"},
        ],
        current_focus_key="technical_anchor",
        current_focus_label="Technical Anchor",
        answered_route_kind="synthesis_close",
        weakness={"severity": "medium", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "graceful_exit", decision
    assert decision["reason"] == "final_synthesis_already_served", decision


def _third_surface_state(question: str | None = None, *, quarantined: bool = False) -> dict:
    dashboard_question = question or "Which dashboard metric caused the most disagreement, and what decision changed because of it?"
    interview_map = {
        "launch_focus_keys": ["activation_attribution", "seller_taxonomy"],
        "map_quarantine": [{"focus_key": "marketplace_dashboard", "reason": "bad wording"}] if quarantined else [],
        "focus_areas": [
            {
                "focus_key": "activation_attribution",
                "label": "Seller Activation Attribution",
                "track_source": "llm",
                "sub_focuses": [
                    {"sub_focus_key": "support_kyc_confound", "label": "Support and KYC confound", "coverage_value": 3.0},
                ],
                "question_ladder": [
                    {
                        "posture": "explore",
                        "main_question": "If support calls and KYC UX shipped together, which split would you check first?",
                        "expected_space": ["support calls", "KYC UX", "seller cohorts"],
                        "signal_goal": "Test attribution separation.",
                        "information_gain": "high",
                        "voice_complexity": "low",
                    }
                ],
            },
            {
                "focus_key": "seller_taxonomy",
                "label": "Seller Onboarding Taxonomy",
                "track_source": "llm",
                "sub_focuses": [
                    {"sub_focus_key": "event_chain", "label": "Event chain", "coverage_value": 2.7},
                ],
                "question_ladder": [
                    {
                        "posture": "explore",
                        "main_question": "What did first listing mean in your event chain?",
                        "expected_space": ["event definition", "seller state"],
                        "signal_goal": "Test taxonomy definition.",
                        "information_gain": "high",
                        "voice_complexity": "low",
                    }
                ],
            },
            {
                "focus_key": "marketplace_dashboard",
                "label": "Marketplace Health Dashboard",
                "track_source": "quarantined" if quarantined else "llm",
                "sub_focuses": [
                    {
                        "sub_focus_key": "ops_metric_disagreement",
                        "label": "Ops metric disagreement",
                        "surface_kind": "dashboard_reporting",
                        "coverage_value": 2.8,
                        "role_relevance_weight": 2.8,
                        "profile_importance_weight": 2.7,
                        "evidence_strength": 2.5,
                    },
                    {
                        "sub_focus_key": "healthy_metric_failure",
                        "label": "Healthy-looking metric failure",
                        "surface_kind": "dashboard_reporting",
                        "coverage_value": 2.6,
                        "role_relevance_weight": 2.7,
                    },
                ],
                "question_ladder": [
                    {
                        "posture": "explore",
                        "main_question": dashboard_question,
                        "expected_space": ["metric disagreement", "business decision", "stakeholder action"],
                        "signal_goal": "Expose marketplace operating judgment from the dashboard surface.",
                        "information_gain": "high",
                        "voice_complexity": "low",
                    },
                    {
                        "posture": "pressure",
                        "main_question": "If that metric looked healthy while refunds got worse, what would you check next?",
                        "expected_space": ["refunds", "metric gaming", "seller quality"],
                        "signal_goal": "Test tension between dashboard health and business health.",
                        "information_gain": "high",
                        "voice_complexity": "low",
                    },
                ],
            },
        ],
    }
    return {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
        "history": [],
    }


def test_third_surface_probe_selects_one_high_signal_deferred_surface() -> None:
    state = _third_surface_state()
    history = [
        {"focus_key": "activation_attribution", "sub_focus_key": "support_kyc_confound", "route_kind": "trajectory_map_surface"},
        {"focus_key": "seller_taxonomy", "sub_focus_key": "event_chain", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
    ]
    result = _select_third_surface_probe(
        state,
        history,
        sprint=2,
        avoid_focus="seller_taxonomy",
        answer="The taxonomy answer was clear.",
        turn_number=11,
    )
    assert result, result
    assert result["route_kind"] == "third_surface_probe", result
    assert result["focus_key"] == "marketplace_dashboard", result
    assert result["sub_focus_key"] == "ops_metric_disagreement", result
    assert "dashboard metric" in result["question"].lower(), result


def test_third_surface_probe_rejects_bad_self_rating_question() -> None:
    state = _third_surface_state("Which part are you most confident in?")
    history = [
        {"focus_key": "activation_attribution", "sub_focus_key": "support_kyc_confound", "route_kind": "trajectory_map_surface"},
        {"focus_key": "seller_taxonomy", "sub_focus_key": "event_chain", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
    ]
    result = _select_third_surface_probe(
        state,
        history,
        sprint=2,
        avoid_focus="seller_taxonomy",
        answer="The taxonomy answer was clear.",
        turn_number=11,
    )
    assert result is None, result


def test_third_surface_probe_skips_quarantined_deferred_surface() -> None:
    state = _third_surface_state(quarantined=True)
    history = [
        {"focus_key": "activation_attribution", "sub_focus_key": "support_kyc_confound", "route_kind": "trajectory_map_surface"},
        {"focus_key": "seller_taxonomy", "sub_focus_key": "event_chain", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
    ]
    result = _select_third_surface_probe(
        state,
        history,
        sprint=2,
        avoid_focus="seller_taxonomy",
        answer="The taxonomy answer was clear.",
        turn_number=11,
    )
    assert result is None, result


def test_third_surface_probe_allows_second_turn_only_on_depth_trigger() -> None:
    state = _third_surface_state()
    first_history = [
        {"focus_key": "activation_attribution", "sub_focus_key": "support_kyc_confound", "route_kind": "trajectory_map_surface"},
        {"focus_key": "seller_taxonomy", "sub_focus_key": "event_chain", "route_kind": "second_anchor", "agenda_phase": "second_anchor"},
        {
            "focus_key": "marketplace_dashboard",
            "sub_focus_key": "ops_metric_disagreement",
            "route_kind": "third_surface_probe",
            "question": "Which dashboard metric caused the most disagreement, and what decision changed because of it?",
        },
    ]
    no_trigger = _select_third_surface_probe(
        state,
        first_history,
        sprint=2,
        avoid_focus="marketplace_dashboard",
        answer="I used the dashboard to discuss weekly business reviews.",
        turn_number=12,
    )
    assert no_trigger is None, no_trigger

    triggered = _select_third_surface_probe(
        state,
        first_history,
        sprint=2,
        avoid_focus="marketplace_dashboard",
        answer="I segmented sellers, but refunds and SLA lag showed a possible confound.",
        turn_number=12,
    )
    assert triggered, triggered
    assert triggered["route_kind"] == "third_surface_probe", triggered
    assert "refund" in triggered["question"].lower(), triggered


def test_evaluator_sanity_softens_impossible_zero() -> None:
    history = [
        {
            "question": f"Question {i}",
            "answer": "I defined the metric, checked the denominator, used guardrails, and explained the tradeoff clearly.",
        }
        for i in range(12)
    ]
    calibrated = _apply_evaluation_sanity_calibration(
        {
            "hire_recommendation": "NO HIRE",
            "overall_score": 0,
            "confidence_score": 0.7,
            "risk_flags": [],
        },
        history=history,
        per_answer_scores=[{"score": 6.0} for _ in history],
        coverage_verdict_ratio=0.55,
        coverage_portrait={"coverage_score": 0.55, "primary_domain": {}},
    )
    assert calibrated["overall_score"] >= 4.0, calibrated
    assert calibrated["hire_recommendation"] == "MAYBE", calibrated
    assert calibrated["risk_flags"], calibrated


def main() -> None:
    test_secondary_focus_prefers_role_relevant_surface_weight()
    test_secondary_surface_can_choose_high_value_same_parent_over_offrole_focus()
    test_map_selector_preserves_preferred_second_anchor_surface_metadata()
    test_second_anchor_reselects_after_spent_surface()
    test_application_transfer_beats_depth()
    test_application_grounding_precedes_transfer_when_depth_is_ambiguous()
    test_application_grounding_answer_routes_to_transfer()
    test_application_grounding_is_not_assessment_breadth()
    test_grounding_depth_caps_specialized_internals_without_confirmation()
    test_coverage_not_blocked_by_fatigue()
    test_focus_pivot_on_continue_false()
    test_no_early_primary_pivot_from_ratio()
    test_background_ratio_guard_uses_evidence_floor()
    test_map_backed_packet_requires_focus_attribution()
    test_focus_inference_uses_dimension_and_subfocus_text()
    test_ratio_pivot_after_primary_floor()
    test_hard_gate_blocks_tunneled_no_hire()
    test_subfocus_surfaces_count_for_completion_breadth()
    test_three_subfocus_surfaces_avoid_tunnel_gate()
    test_coverage_dimensions_count_as_distinct_surfaces()
    test_second_anchor_budget_forces_synthesis_close()
    test_second_anchor_budget_before_synthesis_floor_keeps_grounded_depth()
    test_second_anchor_waits_until_turn_ten_window()
    test_final_synthesis_moves_to_graceful_exit()
    test_final_synthesis_never_reopens_depth_for_floor()
    test_third_surface_probe_selects_one_high_signal_deferred_surface()
    test_third_surface_probe_rejects_bad_self_rating_question()
    test_third_surface_probe_skips_quarantined_deferred_surface()
    test_third_surface_probe_allows_second_turn_only_on_depth_trigger()
    test_evaluator_sanity_softens_impossible_zero()
    print("interview agenda contract tests passed")


if __name__ == "__main__":
    main()
