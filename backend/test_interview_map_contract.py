"""
Contract check: deterministic interview-map generation is disabled.

Run with:
  python3 -m backend.test_interview_map_contract
"""

import asyncio

import backend.services.interview_map as interview_map_module
from backend.services.interview_map import (
    _FOCUS_PLAN_SYSTEM,
    _apply_track_updates_with_provenance,
    _anchor_context_for_focus,
    _attach_launch_metadata,
    _blocking_launch_repair_targets,
    _candidate_focus_subset,
    _cheap_structural_review,
    _compact_ladder_quality_for_audit,
    _compact_map_critic_user_prompt,
    _coerce_critic_payload,
    _critic_signals_plan_problem,
    _extract_resume_snippets,
    _focus_boundary_kind,
    _focus_review_has_significant_issues,
    _focus_plan_user_prompt,
    _map_quality_scorecard,
    _merge_surface_plan_deferred_focuses,
    _normalize_map_candidate,
    _parse_dimension_output,
    _parse_launch_track_lite,
    _question_readability_flags,
    _question_repair_safety_flags,
    _track_dimensions,
    _track_opener,
    _track_recovery,
    _track_schema_rescue_quality_flags,
    _repair_targets_for_focus,
    _replace_failed_launch_tracks,
    _track_system_prompt_sections,
    _weight_calibration_warnings,
    build_deterministic_interview_map,
    hydrate_interview_map_tracks,
    select_from_trajectory_map_detailed,
    validate_interview_map,
)


MESSY_RESUME = """
(+86) 15914122353 | 123040005@link.cuhk.edu.cn| 2001 Longxiang Boulevard, Longgang District, Shenzhen :
TheChineseUniversityofHongKong,Shenzhen(B.Eng. in Computer Science and Engineering)
2024 Guangdong Government Outstanding International Student Scholarship
2025 Leading Academic Peer Advisor @ School of Data Science, CUHK-SZ
TECHNICAL SKILLS:
Top Skills: Python, C++, SQL Hybrid, RISC- V, Git, Docker, Google GCP, AWS Deployment, Linux, Deployment Testing
EXPERIENCE:
AI Agent Development Engineer [Intern] : AIGC Algorithms - Wondershare Filmora @ Shenzhen Jan 2026 – Present
Architected and prototyped an end-to-end Agent based AIGC video generation and editing pipeline on Google ADK by implementing a unified seed-based generation workflow.
Engineered a ML - feature-map control system that translates orthogonal control axes into pixel-level semantic generation instructions for Google Veo 3 seed-regeneration.
Built a semantic UI-to-latent translation interface that maps intuitive editing controls to diffusion conditioning vectors.
AI Engineer Intern : AI Model Developer - Optek Microelectronics @ Shenzhen, China 2025 July - Sept
Engineered a full-stack TinyML Audio Classification Pipeline, by integrating MediaPipe Audio for real-time feature extraction, TensorFlow Lite-Micro INT8 for quantized inference, and Edge Impulse for SDK deployment.
Optimized and delivered a custom classifier for a 700 MHz DSP + 16 MB NPU, accomplishing <10 ms latency and 4× model compression.
Research Assistant : HKU- COLUMBIA- ALIBABA- CUHKSZ@ BIRD Vision 2025 June - Sept
Reconstructed an advanced multi-modal benchmark framework that pioneered BIRD-SQL dataset.
Designed relational DB schemas, and created complex hybrid SQL queries.
"""


def _runtime_area(focus_key: str, label: str, *, coverage_value: float = 2.5) -> dict:
    dims = [
        {
            "id": f"{focus_key}_surface",
            "label": "Surface",
            "surface": "Which exact artifact did you own?",
            "mechanism": "How did you make the core decision?",
            "boundary": "What failure would expose weak ownership?",
            "signal_weight": 2.0,
        },
        {
            "id": f"{focus_key}_metric",
            "label": "Metric",
            "surface": "What denominator did you use?",
            "mechanism": "How did you isolate the effect?",
            "boundary": "What confounder would invalidate the result?",
            "signal_weight": 2.0,
        },
        {
            "id": f"{focus_key}_decision",
            "label": "Decision",
            "surface": "Who used the output?",
            "mechanism": "How did it change a product decision?",
            "boundary": "What decision should not rely on it?",
            "signal_weight": 2.0,
        },
    ]
    return {
        "label": label,
        "focus_key": focus_key,
        "anchor_context": label,
        "surface_kind": "conversion_experiment",
        "coverage_value": coverage_value,
        "sub_focuses": [
            {
                "label": label,
                "sub_focus_key": focus_key,
                "surface_kind": "conversion_experiment",
                "role_relevance_weight": coverage_value,
                "profile_importance_weight": coverage_value,
                "evidence_strength": coverage_value,
                "claim_risk": 2.0,
                "coverage_value": coverage_value,
                "why_priority": "Synthetic contract-test surface.",
                "source_snippets": [label],
            }
        ],
        "track_source": "llm",
        "track_schema": "dimension",
        "llm_branch_count": len(dims),
        "fallback_branch_count": 0,
        "llm_branches": [dim["id"] for dim in dims],
        "fallback_branches": [],
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": f"For {label}, what decision were you trying to make?",
                "signal_goal": "Frame the claim.",
                "expected_space": ["decision", "scope"],
                "follow_up_if_shallow": f"What made {label} important enough to test?",
                "follow_up_if_strong": f"What alternative decision did you reject for {label}?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": f"For {label}, what exact metric or denominator did you use?",
                "signal_goal": "Clarify measurement.",
                "expected_space": ["metric", "denominator"],
                "follow_up_if_shallow": "What was included and excluded from that denominator?",
                "follow_up_if_strong": "Which denominator would have made the result look weaker?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": f"For {label}, what user or system behavior changed after your work?",
                "signal_goal": "Explore mechanism.",
                "expected_space": ["behavior", "mechanism"],
                "follow_up_if_shallow": "What evidence showed that behavior had actually changed?",
                "follow_up_if_strong": "What alternative explanation did you rule out?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "pressure",
                "main_question": f"If {label} improved one metric but hurt quality, what result would make you rethink it?",
                "signal_goal": "Pressure-test tradeoff.",
                "expected_space": ["guardrail", "threshold"],
                "follow_up_if_shallow": "Which guardrail would matter most?",
                "follow_up_if_strong": "What threshold would make you pause the rollout?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "synthesize",
                "main_question": f"For {label}, which part are you most confident about, and which part is still uncertain?",
                "signal_goal": "Synthesize certainty.",
                "expected_space": ["confidence", "uncertainty"],
                "follow_up_if_shallow": "What evidence supports the confident part?",
                "follow_up_if_strong": "What extra data would remove the remaining uncertainty?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
            {
                "posture": "recover",
                "main_question": f"If you do not remember every detail of {label}, which part did you personally own?",
                "signal_goal": "Recover ownership signal.",
                "expected_space": ["ownership"],
                "follow_up_if_shallow": "What did you personally change or decide?",
                "follow_up_if_strong": "Where did your ownership stop?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
        ],
        "opener": f"For {label}, what was the core claim you can defend?",
        "dimensions": dims,
        "recovery": {
            "short_answer": "Which part did you own?",
            "honest_gap": "Which part was outside your scope?",
            "claim_conflict": "What evidence would change your claim?",
            "metric_risk": "What denominator could mislead us?",
            "overclaim_risk": "Where does your ownership stop?",
            "bridge": "Let's move to the next focus.",
        },
    }


def main() -> None:
    prompt = _focus_plan_user_prompt(
        resume=MESSY_RESUME,
        target_role="Product Analyst",
        dedup_hint="Previous attempt used two areas from the same job.",
    )
    assert "Keep distinct role-critical product/analytics surfaces split" in prompt, prompt
    assert "merge only genuinely redundant areas" in prompt, prompt
    assert "role_relevance_weight" in prompt, prompt
    assert "claim_risk" in prompt, prompt
    assert "surface_kind" in prompt, prompt
    assert "return at least 3 focus_areas whenever the resume has 3 credible" in prompt, prompt
    assert "60% of total interview time" not in _FOCUS_PLAN_SYSTEM, _FOCUS_PLAN_SYSTEM
    track_prompt = interview_map_module._track_system_prompt("Product Analyst")
    assert "were you mainly trying to improve paid conversion" in track_prompt, track_prompt
    assert "candidate-facing answer lane" in track_prompt, track_prompt
    assert "or was there something else" in track_prompt, track_prompt
    assert "Too closed" in track_prompt, track_prompt
    assert "STYLE EXAMPLES ONLY" in track_prompt, track_prompt
    assert "Good engineering frame" in track_prompt, track_prompt
    prompt_sections = _track_system_prompt_sections("Product Analyst")
    assert [name for name, _ in prompt_sections] == [
        "schema_voice_and_output_contract",
        "role_specific_guidance",
    ], prompt_sections

    compact_prompt = _compact_map_critic_user_prompt(
        candidate={
            "focus_areas": [
                {
                    "focus_key": "agentic_video_generation",
                    "label": "Agentic Video Generation",
                    "anchor_context": "Built an agentic video workflow.",
                    "track": {
                        "opener": "How did you preserve seed lineage?",
                        "dimensions": [
                            {
                                "id": "seed_lineage",
                                "label": "Seed lineage",
                                "surface": "What state did you store?",
                                "mechanism": "How did it flow?",
                                "boundary": "What failure broke it?",
                            }
                        ],
                        "recovery": {},
                    },
                }
            ]
        },
        stage="contract",
    )
    assert "Return exactly ONE JSON object" in compact_prompt, compact_prompt
    assert "Do not return a top-level array" in compact_prompt, compact_prompt

    snippets = _extract_resume_snippets(
        """
Product Analyst, Daily Mantra
- Architected event taxonomy for session flow and feature adoption.
- Automated AppsFlyer dashboards for CAC, CPI, CPM, spend.
""",
        {
            "label": "Dashboard Automation",
            "anchor_context": "Marketing analytics dashboarding",
            "sub_focuses": ["CAC CPI CPM AppsFlyer campaign dashboard"],
        },
    )
    assert snippets and "AppsFlyer" in snippets[0], snippets
    assert "retention from 25% to 42%" in _anchor_context_for_focus({
        "focus_key": "retention",
        "sub_focuses": [
            {
                "label": "Retention experiments",
                "source_snippets": [
                    "Increased user retention from 25% to 42% through A/B testing and product launches."
                ],
            }
        ],
    })

    normalized = _normalize_map_candidate(
        {
            "focus_areas": [
                {
                    "label": "Computer Vision Benchmarking",
                    "focus_key": "cv_benchmark",
                    "anchor_context": "Benchmarked YOLO and optical flow.",
                    "sub_focuses": [
                        {
                            "label": "YOLO SORT optical flow benchmark",
                            "role_relevance_weight": 1.2,
                            "profile_importance_weight": 1.4,
                            "evidence_strength": 2.6,
                            "claim_risk": 2.5,
                            "coverage_value": 1.4,
                        }
                    ],
                    "resume_snippets": ["Benchmarked YOLO with SORT and optical flow."],
                },
                {
                    "label": "Dashboard Automation",
                    "focus_key": "dashboard_automation",
                    "anchor_context": "Automated AppsFlyer marketing dashboards.",
                    "sub_focuses": [
                        {
                            "label": "AppsFlyer campaign dashboard decision support",
                            "role_relevance_weight": 2.8,
                            "profile_importance_weight": 2.4,
                            "evidence_strength": 2.5,
                            "claim_risk": 1.8,
                            "coverage_value": 2.6,
                        }
                    ],
                    "resume_snippets": ["Automated AppsFlyer Marketing Dashboards."],
                },
            ]
        },
        resume=MESSY_RESUME,
    )
    assert normalized["focus_areas"][0]["focus_key"] == "dashboard_automation", normalized
    assert isinstance(normalized["focus_areas"][0]["sub_focuses"][0], dict), normalized

    local_repair_review = {
        "repair_targets": [{"path": "focus_areas[0].dimensions[1].surface", "instruction": "Sharpen wording."}],
        "issues": ["Question wording is generic."],
        "repair_instructions": ["Replace this one question; do not regenerate the plan."],
    }
    assert not _critic_signals_plan_problem(local_repair_review), local_repair_review

    focus_area_opener_repair = {
        "repair_targets": [
            {
                "focus_key": "analytics_event_taxonomy",
                "path": "opener",
                "instruction": "Replace only this opener.",
            }
        ],
        "issues": [
            "Focus area 2 opener is a near-duplicate angle of area 1's trial conversion mechanism."
        ],
        "repair_instructions": [
            "Replace area 2 opener to anchor on the track completion claim, not the conversion figure."
        ],
    }
    assert not _critic_signals_plan_problem(focus_area_opener_repair), focus_area_opener_repair

    real_plan_problem = {
        "repair_targets": [{"path": "opener", "instruction": "Local repair also exists."}],
        "issues": ["The focus plan has duplicate focus areas from the same project."],
        "repair_instructions": ["Merge focus areas before repairing questions."],
    }
    assert _critic_signals_plan_problem(real_plan_problem), real_plan_problem

    typed_field_issue = {
        "typed_issues": [
            {
                "issue_scope": "field_level",
                "focus_key": "analytics_event_taxonomy",
                "path": "opener",
                "action": "surgical_repair",
                "reason": "Opener asks about conversion instead of taxonomy.",
            }
        ],
        "issues": ["Focus area 2 opener drifted."],
    }
    assert not _critic_signals_plan_problem(typed_field_issue), typed_field_issue

    typed_plan_issue = {
        "typed_issues": [
            {
                "issue_scope": "plan_level",
                "action": "plan_repair",
                "reason": "The map duplicated the same focus area twice.",
            }
        ],
    }
    assert _critic_signals_plan_problem(typed_plan_issue), typed_plan_issue

    coerced, notes = _coerce_critic_payload([
        {
            "ready": True,
            "overall_score": 8.2,
            "top_two_score": 8.0,
            "opener_quality_score": 8.4,
            "dimension_depth_score": 8.1,
            "focus_reviews": [
                {
                    "focus_key": "analytics_event_taxonomy",
                    "label": "Analytics event taxonomy",
                    "score": 8.0,
                    "issues": [],
                }
            ],
        }
    ])
    assert notes and coerced["overall_score"] == 8.2 and coerced["ready"] is True, (coerced, notes)

    fragment_payload, fragment_notes = _coerce_critic_payload([
        {
            "focus_key": "analytics_event_taxonomy",
            "label": "Analytics event taxonomy",
            "score": 7.4,
            "opener_issue": "Opener is too broad.",
            "issues": ["Replace opener."],
        },
        {
            "issue_scope": "field_level",
            "focus_key": "analytics_event_taxonomy",
            "path": "opener",
            "action": "surgical_repair",
            "reason": "Opener is too broad.",
        },
    ])
    assert fragment_notes and fragment_payload["focus_reviews"][0]["score"] == 7.4, fragment_payload
    assert fragment_payload["typed_issues"][0]["path"] == "opener", fragment_payload

    string_list_payload, string_list_notes = _coerce_critic_payload([
        "The opener is too generic.",
        "The dimensions are shallow.",
    ])
    assert string_list_payload["_critic_unrecoverable_shape"] is True, string_list_payload
    assert string_list_notes and string_list_payload["issues"][0] == "The opener is too generic.", string_list_payload

    taxonomy_candidate = {
        "focus_areas": [
            {
                "label": "Analytics event taxonomy and instrumentation",
                "focus_key": "analytics_event_taxonomy",
                "anchor_context": "Defined critical product events for Daily Mantra.",
                "surface_kind": "event_taxonomy",
                "sub_focuses": [
                    {
                        "label": "Event schema and adoption tracking",
                        "surface_kind": "event_taxonomy",
                        "role_relevance_weight": 2.8,
                        "profile_importance_weight": 2.5,
                        "evidence_strength": 2.5,
                        "claim_risk": 2.0,
                        "coverage_value": 2.6,
                    }
                ],
                "track": {
                    "opener": "Your conversion improved from 27% to 42%; what moved that lift?",
                    "dimensions": [
                        {
                            "id": "event_schema",
                            "label": "Event schema",
                            "surface": "Which event definitions did you own in the schema?",
                            "mechanism": "How did you handle dedupe for repeated session events?",
                            "boundary": "What late event would have broken attribution?",
                        }
                    ],
                    "recovery": {},
                    "candidate_q4_options": [],
                },
            }
        ]
    }
    assert _focus_boundary_kind(taxonomy_candidate["focus_areas"][0]) == "taxonomy"
    typed_taxonomy_area = _runtime_area("subscription_schema", "Subscription conversion schema")
    typed_taxonomy_area["surface_kind"] = "event_taxonomy"
    typed_taxonomy_area["sub_focuses"][0]["surface_kind"] = "event_taxonomy"
    assert _focus_boundary_kind(typed_taxonomy_area) == "taxonomy", typed_taxonomy_area
    cheap_review = _cheap_structural_review(taxonomy_candidate, target_role="Product Analyst")
    assert not any(
        issue.get("issue_scope") == "field_level"
        and issue.get("focus_key") == "analytics_event_taxonomy"
        and issue.get("path") == "opener"
        for issue in cheap_review.get("typed_issues", [])
    ), cheap_review

    taxonomy_candidate["focus_areas"][0]["track"]["opener"] = (
        "Your conversion improved from 27% to 42%; tell me about revenue."
    )
    vague_outcome_review = _cheap_structural_review(taxonomy_candidate, target_role="Product Analyst")
    assert any(
        issue.get("issue_scope") == "field_level"
        and issue.get("focus_key") == "analytics_event_taxonomy"
        and issue.get("path") == "opener"
        for issue in vague_outcome_review.get("typed_issues", [])
    ), vague_outcome_review

    overpacked = (
        "How did you define the event taxonomy, and how did you dedupe late events, "
        "and what attribution window did you use, and why was that better than the old flow?"
    )
    assert _question_readability_flags(overpacked), overpacked
    truncated = "At LoopCart, you instrumented six flows for the payment"
    truncated_flags = _question_repair_safety_flags(truncated)
    assert "missing_question_mark" in truncated_flags and "appears_truncated" in truncated_flags, truncated_flags

    parsed_track = _parse_dimension_output(
        {
            "question_ladder": _runtime_area("trial_conversion", "Trial conversion")["question_ladder"],
            "opener": "When you changed the trial length, what business decision were you trying to make?",
            "dimensions": _runtime_area("trial_conversion", "Trial conversion")["dimensions"],
            "recovery": _runtime_area("trial_conversion", "Trial conversion")["recovery"],
            "candidate_q4_options": ["What would you check before scaling this experiment?"],
        },
        {"focus_key": "trial_conversion", "label": "Trial conversion"},
    )
    assert parsed_track["question_ladder"][0]["posture"] == "frame", parsed_track
    assert parsed_track["opener"] == parsed_track["question_ladder"][0]["main_question"], parsed_track
    assert parsed_track["map_schema_version"] == "v2_ladder", parsed_track
    assert parsed_track["primary_question_contract"] == "question_ladder", parsed_track
    assert parsed_track["legacy_compat"]["authority"] == "compatibility_only", parsed_track
    assert parsed_track["legacy_compat"]["opener"] == parsed_track["question_ladder"][0]["main_question"], parsed_track
    stale_alias_area = dict(parsed_track)
    stale_alias_area["opener"] = "Stale legacy opener should not win?"
    stale_alias_area["dimensions"] = []
    stale_alias_area["recovery"] = {"short_answer": "Stale recovery?"}
    assert _track_opener(stale_alias_area) == parsed_track["question_ladder"][0]["main_question"], stale_alias_area
    assert _track_dimensions(stale_alias_area), stale_alias_area
    assert "denominator" in _track_recovery(stale_alias_area).get("metric_risk", "").lower(), stale_alias_area

    ladder_only_track = _parse_dimension_output(
        {
            "question_ladder": [
                {
                    "posture": "frame",
                    "main_question": "When you moved the trial from 7 days to 1 day, what business decision were you trying to make: improve conversion, reduce low-intent trials, test urgency, or something else?",
                    "signal_goal": "Frame the decision.",
                    "expected_space": ["conversion", "trial quality", "user urgency"],
                    "follow_up_if_shallow": "What was broken in the 7-day trial that made duration feel like the lever?",
                    "follow_up_if_strong": "What was the strongest reason not to cut the trial so aggressively?",
                    "information_gain": "high",
                    "voice_complexity": "low",
                },
                {
                    "posture": "clarify",
                    "main_question": "That 42% conversion number — what exactly counted as conversion: trial start to paid subscription, install to subscription, or something else?",
                    "signal_goal": "Clarify metric definition.",
                    "expected_space": ["denominator", "conversion event", "time window"],
                    "follow_up_if_shallow": "What was the denominator — how many users went into that calculation?",
                    "follow_up_if_strong": "Did the attribution window change when the trial became shorter?",
                    "information_gain": "high",
                    "voice_complexity": "low",
                },
                {
                    "posture": "explore",
                    "main_question": "How did you land on 1 day specifically instead of 2 or 3 days?",
                    "signal_goal": "Explore decision reasoning.",
                    "expected_space": ["variant choice", "behavior signal"],
                    "follow_up_if_shallow": "What data made 1 day look better than another duration?",
                    "follow_up_if_strong": "If 2 days had won, what would that say about the mechanism?",
                    "information_gain": "high",
                    "voice_complexity": "low",
                },
                {
                    "posture": "pressure",
                    "main_question": "If conversion rose but 30-day cancellations also rose, what result would make you rethink or roll back the change?",
                    "signal_goal": "Pressure-test guardrail judgment.",
                    "expected_space": ["guardrail threshold", "refunds", "retention"],
                    "follow_up_if_shallow": "What cancellation movement would be too much for you?",
                    "follow_up_if_strong": "How would you explain keeping it if refunds moved slightly but revenue quality improved?",
                    "information_gain": "high",
                    "voice_complexity": "low",
                },
                {
                    "posture": "synthesize",
                    "main_question": "Looking back, which part are you most confident about: conversion improved, refunds stayed healthy, the trial change caused it, or something else?",
                    "signal_goal": "Synthesize certainty.",
                    "expected_space": ["confidence", "uncertainty", "confounders"],
                    "follow_up_if_shallow": "What else was changing at the same time?",
                    "follow_up_if_strong": "What extra data would make your conclusion stronger?",
                    "information_gain": "high",
                    "voice_complexity": "low",
                },
                {
                    "posture": "recover",
                    "main_question": "If you do not remember the full experiment setup, what part of the conversion analysis did you personally own?",
                    "signal_goal": "Recover ownership signal.",
                    "expected_space": ["ownership", "scope"],
                    "follow_up_if_shallow": "What did you personally calculate or decide?",
                    "follow_up_if_strong": "Where did your ownership stop?",
                    "information_gain": "medium",
                    "voice_complexity": "low",
                },
            ]
        },
        {
            "label": "Subscription Conversion Optimization",
            "focus_key": "subscription_conversion",
            "anchor_context": "Optimized trial-to-subscription conversion from 27% to 42% by reducing trial from 7 days to 1 day.",
        },
    )
    assert ladder_only_track["opener"].startswith("When you moved the trial"), ladder_only_track
    assert ladder_only_track["legacy_compat"]["derived_from"] == "question_ladder", ladder_only_track
    assert ladder_only_track["assessment_dimensions"] == ladder_only_track["legacy_compat"]["dimensions"], ladder_only_track
    assert len(ladder_only_track["dimensions"]) >= 2, ladder_only_track
    assert ladder_only_track["dimensions"][0]["surface"].startswith("That 42% conversion"), ladder_only_track
    assert ladder_only_track["recovery"]["metric_risk"].startswith("That 42% conversion"), ladder_only_track
    truncated_legacy_opener_track = _parse_dimension_output(
        {
            **ladder_only_track,
            "opener": "At Daily Mantra, retention went from 25% to 42%. Before we go anywhere else, did that 42% measure Day",
            "dimensions": [],
        },
        {
            "label": "Retention",
            "focus_key": "retention",
            "anchor_context": "Increased user retention from 25% to 42% through A/B testing.",
        },
    )
    assert truncated_legacy_opener_track["opener"].startswith("When you moved the trial"), truncated_legacy_opener_track
    assert "measure Day" not in truncated_legacy_opener_track["opener"], truncated_legacy_opener_track

    warnings = _weight_calibration_warnings({
        "focus_areas": [
            {
                "label": "Computer Vision Benchmarking",
                "focus_key": "cv_benchmark",
                "sub_focuses": [
                    {
                        "label": "YOLO SORT optical flow benchmark",
                        "role_relevance_weight": 1.2,
                        "profile_importance_weight": 1.2,
                        "evidence_strength": 2.8,
                        "claim_risk": 2.9,
                        "coverage_value": 2.7,
                    }
                ],
            }
        ]
    })
    assert any("Off-role" in w.get("warning", "") or "overprioritized" in w.get("warning", "") for w in warnings), warnings

    patched, provenance = _apply_track_updates_with_provenance(
        {
            "opener": "Tell me about your analytics work.",
            "dimensions": [
                {
                    "id": "event_schema",
                    "label": "Event schema",
                    "resume_anchor": "Architected event taxonomy.",
                    "surface": "Which event definitions did you own?",
                    "mechanism": "How did you dedupe repeated events?",
                    "boundary": "What late event would break attribution?",
                    "signal_weight": 3.0,
                },
                {
                    "id": "ownership_boundary",
                    "label": "Ownership boundary",
                    "resume_anchor": "Enabled real-time product insights.",
                    "surface": "Who consumed the taxonomy output?",
                    "mechanism": "How did you validate feature adoption events?",
                    "boundary": "Which downstream decision would fail if tracking was wrong?",
                    "signal_weight": 2.5,
                },
                {
                    "id": "attribution_instrumentation",
                    "label": "Attribution instrumentation",
                    "resume_anchor": "Powered retention and conversion experiments.",
                    "surface": "Which attribution field joined sessions to experiments?",
                    "mechanism": "How did you handle events arriving out of order?",
                    "boundary": "What schema change would force a backfill?",
                    "signal_weight": 2.0,
                },
            ],
            "recovery": {
                "short_answer": "Which part did you own directly?",
                "honest_gap": "What part did you not own?",
                "claim_conflict": "What evidence would change your claim?",
                "metric_risk": "What denominator could make the metric misleading?",
                "overclaim_risk": "Where might the claim be overstated?",
                "bridge": "Let's move to the next analytics surface.",
            },
            "candidate_q4_options": [],
        },
        [
            {
                "path": "opener",
                "value": "For the Daily Mantra event taxonomy, which event definition carried the highest risk of double-counting?",
            }
        ],
        {
            "label": "Daily Mantra event taxonomy",
            "focus_key": "analytics_event_taxonomy",
            "anchor_context": "Architected event taxonomy for Daily Mantra.",
            "resume_snippets": ["Architected event taxonomy for session flow and feature adoption."],
        },
        targets=[
            {
                "path": "opener",
                "issue_scope": "field_level",
                "issue": "Generic opener.",
                "reason": "Replace generic opener.",
            }
        ],
        model="test/model",
        latency_ms=12,
    )
    assert patched["opener"].startswith("For the Daily Mantra event taxonomy"), patched
    assert provenance[0]["old_value"] == "Tell me about your analytics work.", provenance
    assert provenance[0]["accepted_by"] == "field_verifier", provenance

    try:
        _apply_track_updates_with_provenance(
            _runtime_area("loopcart_payments", "LoopCart payment instrumentation"),
            [{"path": "question_ladder[0].main_question", "value": truncated}],
            {
                "label": "LoopCart payment instrumentation",
                "focus_key": "loopcart_payments",
                "anchor_context": "Instrumented checkout flows.",
                "resume_snippets": ["Instrumented six checkout flows."],
            },
            targets=[{"path": "question_ladder[0].main_question", "issue_scope": "readability_level"}],
            model="test/model",
            latency_ms=5,
        )
    except RuntimeError as exc:
        assert "safety" in str(exc), exc
    else:
        raise AssertionError("truncated ladder repair was unexpectedly accepted")

    ladder_map = {"focus_areas": [_runtime_area("product_conversion", "Product conversion experiments")]}
    first_ladder = select_from_trajectory_map_detailed(
        ladder_map,
        sprint=1,
        focus_key="product_conversion",
        answer="",
        entities=[],
        history=[],
        depth=0,
    )
    assert first_ladder["question_posture"] == "frame", first_ladder
    second_ladder = select_from_trajectory_map_detailed(
        ladder_map,
        sprint=1,
        focus_key="product_conversion",
        answer="We were deciding whether shorter trials improved paid conversion without hurting quality.",
        entities=[],
        history=[
            {
                "focus_key": "product_conversion",
                "question_posture": "frame",
                "question": first_ladder["question"],
                "answer": "We were deciding whether shorter trials improved paid conversion without hurting quality.",
            }
        ],
        depth=1,
    )
    assert second_ladder["question_posture"] in {"clarify", "explore"}, second_ladder
    after_clarify_ladder = select_from_trajectory_map_detailed(
        ladder_map,
        sprint=1,
        focus_key="product_conversion",
        answer="The denominator was users who started the trial in the test window.",
        entities=[],
        history=[
            {
                "focus_key": "product_conversion",
                "question_posture": "frame",
                "question": first_ladder["question"],
                "answer": "We were deciding whether shorter trials improved paid conversion.",
            },
            {
                "focus_key": "product_conversion",
                "question_posture": "clarify",
                "question": second_ladder["question"],
                "answer": "The denominator was users who started the trial in the test window.",
            },
        ],
        depth=1,
    )
    assert after_clarify_ladder["question_posture"] != "clarify", after_clarify_ladder
    assert after_clarify_ladder["ladder_field"] == "main_question", after_clarify_ladder
    shallow_ladder = select_from_trajectory_map_detailed(
        ladder_map,
        sprint=1,
        focus_key="product_conversion",
        answer="It improved conversion.",
        entities=[],
        history=[
            {
                "focus_key": "product_conversion",
                "question_posture": "frame",
                "question": first_ladder["question"],
                "answer": "It improved conversion.",
            }
        ],
        depth=1,
        branch_hint="shallow",
    )
    assert shallow_ladder["question_posture"] == "recover", shallow_ladder
    assert shallow_ladder["ladder_field"] == "follow_up_if_shallow", shallow_ladder

    low_value_ladder_map = {
        "focus_areas": [
            _runtime_area("off_role_surface", "Off-role side project", coverage_value=1.4)
        ]
    }
    low_value_recovery = select_from_trajectory_map_detailed(
        low_value_ladder_map,
        sprint=1,
        focus_key="off_role_surface",
        answer="Yes.",
        entities=[],
        history=[
            {
                "focus_key": "off_role_surface",
                "question_posture": "frame",
                "question": "For Off-role side project, what decision were you trying to make?",
                "answer": "Yes.",
            }
        ],
        depth=1,
        branch_hint="if_short_answer",
    )
    assert low_value_recovery["question_posture"] == "recover", low_value_recovery
    assert low_value_recovery["ladder_field"] == "main_question", low_value_recovery

    low_value_repeated_posture = select_from_trajectory_map_detailed(
        low_value_ladder_map,
        sprint=1,
        focus_key="off_role_surface",
        answer="Yes.",
        entities=[],
        history=[
            {
                "focus_key": "off_role_surface",
                "question_posture": "frame",
                "question": "For Off-role side project, what decision were you trying to make?",
                "answer": "Yes.",
            },
            {
                "focus_key": "off_role_surface",
                "question_posture": "recover",
                "question": "If you do not remember every detail of Off-role side project, which part did you personally own?",
                "answer": "Yes.",
            },
        ],
        depth=1,
        branch_hint="if_short_answer",
    )
    assert not (
        low_value_repeated_posture["question_posture"] == "recover"
        and low_value_repeated_posture["ladder_field"].startswith("follow_up")
    ), low_value_repeated_posture
    compact_ladder_audit = _compact_ladder_quality_for_audit(ladder_map)
    assert compact_ladder_audit["focus_areas"][0]["surface_kind"] == "conversion_experiment", compact_ladder_audit
    assert compact_ladder_audit["focus_areas"][0]["question_ladder"][0]["expected_space"], compact_ladder_audit

    scorecard = _map_quality_scorecard({
        "focus_areas": [
            {
                "label": "Daily Mantra event taxonomy",
                "focus_key": "analytics_event_taxonomy",
                "anchor_context": "Architected event taxonomy for Daily Mantra.",
                "sub_focuses": [],
                "opener": patched["opener"],
                "dimensions": [
                    {
                        "surface": "Which event definitions did you own in the schema?",
                        "mechanism": "How did you handle dedupe for repeated session events?",
                        "boundary": "What late event would have broken attribution?",
                    }
                ],
                "question_ladder": _runtime_area("analytics_event_taxonomy", "Daily Mantra event taxonomy")["question_ladder"],
                "recovery": {},
            }
        ]
    })
    assert "top_3_best_questions" in scorecard and "repair_actions_taken" in scorecard, scorecard

    full_plan = {
        "focus_areas": [
            {
                "label": "Product conversion experiments",
                "focus_key": "product_conversion",
                "anchor_context": "Improved trial-to-subscription conversion.",
                "sub_focuses": [{"label": "Trial conversion denominator", "coverage_value": 2.8}],
                "resume_snippets": ["Optimized trial-to-subscription conversion rate from 27% to 42%."],
            },
            {
                "label": "Analytics event taxonomy",
                "focus_key": "analytics_event_taxonomy",
                "anchor_context": "Defined session flow and feature adoption events.",
                "sub_focuses": [{"label": "Event schema and dedupe", "coverage_value": 2.6}],
                "resume_snippets": ["Architected core analytics event tracking."],
            },
            {
                "label": "Computer vision benchmarking",
                "focus_key": "cv_benchmarking",
                "anchor_context": "Benchmarked YOLO, SORT, and optical flow.",
                "sub_focuses": [{"label": "CV method benchmarking", "coverage_value": 1.3}],
                "resume_snippets": ["Benchmarked three heuristic methods."],
            },
        ]
    }
    launch_plan = _candidate_focus_subset(full_plan, count=2)
    launch_runtime_map = {
        "focus_areas": [
            _runtime_area("product_conversion", "Product conversion experiments"),
            _runtime_area("analytics_event_taxonomy", "Analytics event taxonomy"),
        ],
        "quality_review": {"ready": True, "overall_score": 8.1, "top_two_score": 8.0},
    }
    bounded_map = _attach_launch_metadata(
        launch_runtime_map,
        full_plan=full_plan,
        launch_candidate=launch_plan,
        launch_review={"ready": True, "overall_score": 8.1, "top_two_score": 8.0},
    )
    bounded_validation = validate_interview_map(bounded_map, require_all_llm=False)
    assert bounded_validation["ready"], bounded_validation
    assert bounded_map["launch_ready"] is True and bounded_map["needs_async_hydration"] is True, bounded_map
    assert bounded_map["pending_hydration_focus_keys"] == ["cv_benchmarking"], bounded_map
    assert [area["focus_key"] for area in bounded_map["focus_areas"]] == [
        "product_conversion",
        "analytics_event_taxonomy",
    ], bounded_map

    compressed_focus_plan = {
        "focus_areas": [
            {
                "label": "Event taxonomy and metric definitions",
                "focus_key": "event_taxonomy_metric_definitions",
                "anchor_context": "Built seller onboarding event taxonomy.",
                "sub_focuses": [
                    {
                        "label": "Dashboard analysis mentioned but not routable",
                        "surface_kind": "dashboard_reporting",
                        "coverage_value": 2.6,
                    }
                ],
                "resume_snippets": ["Owned metric definitions, dashboard analysis, and stakeholder interpretation."],
            },
            {
                "label": "Analytics data modeling",
                "focus_key": "analytics_data_modeling",
                "anchor_context": "Created BigQuery and dbt models joining seller events and support tickets.",
                "sub_focuses": [{"label": "Cross-domain joining", "surface_kind": "data_pipeline", "coverage_value": 2.8}],
                "resume_snippets": ["Created BigQuery and dbt models joining seller events, support tickets, KYC status, and listing approvals."],
            },
        ],
        "_focus_plan_model": "google/gemini-3.5-flash",
        "_focus_plan_source": "primary",
    }
    surface_plan = {
        "schema_version": "surface_plan_v2",
        "focus_areas": [
            {
                "focus_key": "event_taxonomy_metric_definition",
                "label": "Event taxonomy and metric definitions",
                "role_relevance": 5,
                "profile_importance": 5,
                "evidence_strength": 5,
                "claim_risk": 2,
                "why_high_signal": "Core taxonomy and metric ownership.",
                "source_snippets": ["Built seller onboarding event taxonomy."],
                "sub_focuses": [{"label": "Event taxonomy design", "surface_kind": "taxonomy"}],
            },
            {
                "focus_key": "marketplace_health_dashboarding",
                "label": "Marketplace health dashboarding",
                "role_relevance": 5,
                "profile_importance": 5,
                "evidence_strength": 4,
                "claim_risk": 3,
                "why_high_signal": "Tests whether the candidate can operate marketplace health, SLA, refunds, lag, and stakeholder decision surfaces.",
                "source_snippets": ["Built marketplace health dashboard for seller activation, buyer conversion, first-order lag, refunds, and support SLA."],
                "sub_focuses": [
                    {
                        "sub_focus_key": "ops_dashboard_decision_use",
                        "label": "Dashboard decision use",
                        "surface_kind": "dashboard",
                        "why_test": "Tests whether dashboard metrics changed product or ops decisions.",
                        "testable_surfaces": ["Which metric caused disagreement", "Which tile mattered most for marketplace health"],
                        "source_snippets": ["Built marketplace health dashboard for seller activation, buyer conversion, first-order lag, refunds, and support SLA."],
                    }
                ],
            },
        ],
    }
    merged_plan, preserved = _merge_surface_plan_deferred_focuses(compressed_focus_plan, surface_plan)
    assert preserved and preserved[0]["focus_key"] == "marketplace_health_dashboarding", preserved
    assert [area["focus_key"] for area in merged_plan["focus_areas"]][:2] == [
        "event_taxonomy_metric_definitions",
        "analytics_data_modeling",
    ], merged_plan
    assert "marketplace_health_dashboarding" in [
        area["focus_key"] for area in merged_plan["focus_areas"][2:]
    ], merged_plan
    merged_bounded_map = _attach_launch_metadata(
        launch_runtime_map,
        full_plan=merged_plan,
        launch_candidate=_candidate_focus_subset(merged_plan, count=2),
        launch_review={"ready": True, "overall_score": 8.1, "top_two_score": 8.0},
    )
    assert "marketplace_health_dashboarding" in merged_bounded_map["pending_hydration_focus_keys"], merged_bounded_map
    dashboard_already_distinct_plan = {
        **compressed_focus_plan,
        "focus_areas": [
            *compressed_focus_plan["focus_areas"],
            {
                "label": "Marketplace health dashboard",
                "focus_key": "marketplace_health_dashboard",
                "anchor_context": "Built marketplace health dashboard for activation, lag, refunds, and SLA.",
                "sub_focuses": [
                    {
                        "label": "Dashboard metric selection",
                        "surface_kind": "dashboard_reporting",
                        "coverage_value": 2.5,
                    }
                ],
                "resume_snippets": ["Built marketplace health dashboard for seller activation, buyer conversion, first-order lag, refunds, and support SLA."],
            },
        ],
    }
    no_duplicate_plan, no_duplicate_preserved = _merge_surface_plan_deferred_focuses(
        dashboard_already_distinct_plan,
        surface_plan,
    )
    assert not no_duplicate_preserved, no_duplicate_preserved
    assert len(no_duplicate_plan["focus_areas"]) == 3, no_duplicate_plan

    replacement_plan, quarantine = _replace_failed_launch_tracks(
        full_plan,
        ["product_conversion", "analytics_event_taxonomy"],
        ["analytics_event_taxonomy"],
    )
    assert [area["focus_key"] for area in replacement_plan["focus_areas"]] == [
        "product_conversion",
        "cv_benchmarking",
    ], replacement_plan
    assert quarantine and quarantine[0]["focus_key"] == "analytics_event_taxonomy", quarantine

    launch_seed = {
        "label": "Seller activation attribution",
        "focus_key": "seller_activation_attribution",
        "anchor_context": "Reported seller activation improved from 22% to 38% after checklist, support-call, and KYC UX changes.",
        "resume_snippets": [
            "Reported seller activation improved from 22% to 38% after checklist, support-call, and KYC UX changes.",
            "Owned metric definitions and analysis; platform engineering owned event SDK and dbt deployment.",
        ],
        "sub_focuses": [
            {
                "label": "Activation denominator and attribution",
                "sub_focus_key": "activation_denominator_attribution",
                "surface_kind": "conversion_experiment",
                "coverage_value": 2.9,
                "source_snippets": ["Reported seller activation improved from 22% to 38% after checklist, support-call, and KYC UX changes."],
            }
        ],
    }
    launch_raw = {
        "frame": {
            "main_question": "When seller activation moved from 22% to 38%, what decision were you trying to support, and what else mattered beyond activation?",
            "signal_goal": "Understand the decision framing behind the claim.",
            "expected_space": "activation, seller quality, support load, first order",
            "information_gain": "high",
            "voice_complexity": "low",
        },
        "clarify": "For that 38% activation metric, who was included in the denominator, and how did you treat sellers blocked at KYC?",
        "explore": {
            "question": ["Checklist, support calls, and KYC UX changed together.", "Which split would you check first, or something else?"],
            "signal_goal": "Test attribution thinking without overclaiming causality.",
            "expected_space": ["support-call exposure", "KYC status", "listing approval", "seller segment"],
        },
        "pressure": {
            "prompt": "If activation improved but refund rate or support SLA worsened, what would make you rethink the rollout?",
            "signal_goal": "Test guardrail judgment.",
            "expected_space": ["refunds", "support SLA", "low-quality listings", "first-order lag"],
            "voice_complexity": "medium",
        },
        "recover_short_answer": "Which one segment or comparison would you check first to make this more concrete?",
        "dimensions": [
            {
                "id": "denominator_scope",
                "label": "Denominator and scope",
                "resume_anchor": "seller activation improved from 22% to 38%",
                "question": {"text": "What exact seller population counted in the activation denominator, and which sellers were excluded or separated?"},
                "signal_goal": "Check metric scope.",
                "surface_kind": "breadth",
                "signal_weight": 2.7,
            },
            {
                "id": "concurrent_rollout_boundary",
                "label": "Concurrent rollout boundary",
                "resume_anchor": "checklist, support-call, and KYC UX changes",
                "question": "If support calls and KYC UX moved together, what comparison would best separate product lift from support lift?",
                "signal_goal": "Check causal boundary.",
                "surface_kind": "depth",
                "signal_weight": 2.8,
            },
        ],
    }
    launch_track = _parse_launch_track_lite(launch_raw, launch_seed)
    assert launch_track["map_schema_version"] == "v3_launch_lite", launch_track
    assert launch_track["primary_question_contract"] == "launch_track_lite", launch_track
    assert len(launch_track["dimensions"]) == 2, launch_track
    assert "synthesize" not in {item["posture"] for item in launch_track["question_ladder"]}, launch_track
    assert launch_track["candidate_q4_options"] == [], launch_track

    lite_area_one = {
        **launch_seed,
        "track_source": "llm",
        "track_schema": "v3_launch_lite",
        "llm_branch_count": 7,
        "fallback_branch_count": 0,
        "llm_branches": ["question_ladder[0].main_question", "question_ladder[1].main_question"],
        "fallback_branches": [],
        **launch_track,
    }
    lite_area_two = {
        **_runtime_area("marketplace_dashboard", "Marketplace health dashboard"),
        "map_schema_version": "v3_launch_lite",
        "primary_question_contract": "launch_track_lite",
        "track_schema": "v3_launch_lite",
        "launch_track_lite": True,
        "question_ladder": launch_track["question_ladder"],
        "dimensions": launch_track["dimensions"],
        "assessment_dimensions": launch_track["dimensions"],
        "opener": launch_track["opener"],
        "recovery": launch_track["recovery"],
        "candidate_q4_options": [],
        "llm_branch_count": 7,
    }
    lite_map = {
        "focus_areas": [lite_area_one, lite_area_two],
        "quality_review": {"ready": True, "overall_score": 8.0, "top_two_score": 8.0},
    }
    lite_validation = validate_interview_map(lite_map, require_all_llm=False)
    assert lite_validation["ready"], lite_validation
    lite_selection = select_from_trajectory_map_detailed(
        lite_map,
        sprint=1,
        focus_key="seller_activation_attribution",
        answer="",
        entities=[],
        history=[],
        depth=0,
    )
    assert lite_selection and lite_selection["focus_key"] == "seller_activation_attribution", lite_selection
    assert lite_selection["question_posture"] in {"frame", "clarify"}, lite_selection

    indexed_repair_review = {
        "focus_reviews": [
            {"focus_key": "product_conversion", "score": 8.0, "issues": []},
            {"focus_key": "analytics_event_taxonomy", "score": 7.2, "issues": []},
        ],
        "typed_issues": [
            {
                "issue_scope": "field_level",
                "focus_key": "",
                "path": "focus_areas[1].dimensions[0].surface",
                "severity": "minor",
                "action": "surgical_repair",
                "reason": "Indexed path should localize to the second focus.",
            }
        ],
    }
    indexed_targets = _repair_targets_for_focus(
        indexed_repair_review,
        "analytics_event_taxonomy",
        "Analytics event taxonomy",
    )
    assert indexed_targets and indexed_targets[0]["path"] == "dimensions[0].surface", indexed_targets
    assert not _repair_targets_for_focus(indexed_repair_review, "product_conversion", "Product conversion"), indexed_repair_review
    harmless_opener_note = {
        "focus_reviews": [
            {
                "focus_key": "analytics_event_taxonomy",
                "score": 8.1,
                "opener_issue": "None - opener is direct and grounded.",
                "issues": ["Minor dimension note."],
            }
        ]
    }
    assert not _focus_review_has_significant_issues(harmless_opener_note, "analytics_event_taxonomy"), harmless_opener_note
    launch_blocker_review = {
        "focus_reviews": [
            {"focus_key": "product_conversion", "score": 8.0},
            {"focus_key": "analytics_event_taxonomy", "score": 8.0},
        ],
        "typed_issues": [
            {
                "issue_scope": "readability_level",
                "focus_key": "",
                "path": "focus_areas[1].opener",
                "severity": "major",
                "action": "surgical_repair",
                "reason": "Launch opener is too long to say aloud.",
            },
            {
                "issue_scope": "field_level",
                "focus_key": "analytics_event_taxonomy",
                "path": "dimensions[2].boundary",
                "severity": "minor",
                "action": "surgical_repair",
                "reason": "Noncritical later boundary can be deferred.",
            },
        ],
    }
    blockers = _blocking_launch_repair_targets(
        launch_blocker_review,
        ["product_conversion", "analytics_event_taxonomy"],
    )
    assert len(blockers) == 1 and blockers[0]["path"] == "focus_areas[1].opener", blockers

    async def _hydration_contract() -> None:
        original_track = bounded_map["focus_areas"][0]["opener"]

        async def fake_generate_focus_track(**kwargs):
            seed = kwargs["seed"]
            return {
                "source": "llm",
                "llm_branch_count": 3,
                "fallback_branch_count": 0,
                "llm_branches": ["a", "b", "c"],
                "fallback_branches": [],
                "track": {
                    "opener": f"For {seed['label']}, which benchmark result mattered most?",
                    "question_ladder": _runtime_area(seed["focus_key"], seed["label"])["question_ladder"],
                    "dimensions": _runtime_area(seed["focus_key"], seed["label"])["dimensions"],
                    "recovery": _runtime_area(seed["focus_key"], seed["label"])["recovery"],
                    "candidate_q4_options": [],
                },
            }

        async def fake_critique_map_candidate(**kwargs):
            area = kwargs["candidate"]["focus_areas"][0]
            return {
                "ready": True,
                "overall_score": 8.2,
                "top_two_score": 8.2,
                "opener_quality_score": 8.2,
                "dimension_depth_score": 8.2,
                "focus_reviews": [
                    {
                        "focus_key": area["focus_key"],
                        "label": area["label"],
                        "score": 8.2,
                        "opener_issue": "",
                        "issues": [],
                    }
                ],
                "typed_issues": [],
                "repair_targets": [],
            }

        old_generate = interview_map_module._generate_focus_track
        old_critic = interview_map_module._critique_map_candidate
        try:
            interview_map_module._generate_focus_track = fake_generate_focus_track
            interview_map_module._critique_map_candidate = fake_critique_map_candidate
            hydrated = await hydrate_interview_map_tracks(
                interview_map=bounded_map,
                resume="resume",
                session_id="contract",
                focus_keys=["cv_benchmarking"],
            )
        finally:
            interview_map_module._generate_focus_track = old_generate
            interview_map_module._critique_map_candidate = old_critic
        assert hydrated["focus_areas"][0]["opener"] == original_track, hydrated
        assert hydrated["pending_hydration_focus_keys"] == [], hydrated
        assert hydrated["full_map_ready"] is True, hydrated
        assert hydrated["focus_areas"][-1]["focus_key"] == "cv_benchmarking", hydrated

    asyncio.run(_hydration_contract())

    async def _targeted_repair_preserves_untouched_tracks() -> None:
        area_one = _runtime_area("retention", "Retention")
        area_two = _runtime_area("conversion", "Conversion")
        candidate = {
            "focus_areas": [
                {
                    "focus_key": "retention",
                    "label": "Retention",
                    "anchor_context": "Retention lift",
                    "resume_snippets": ["Retention lift"],
                    "track": area_one,
                },
                {
                    "focus_key": "conversion",
                    "label": "Conversion",
                    "anchor_context": "Conversion lift",
                    "resume_snippets": ["Conversion lift"],
                    "track": area_two,
                },
            ]
        }
        critic_feedback = {
            "ready": False,
            "focus_reviews": [
                {"focus_key": "retention", "label": "Retention", "score": 7.0, "opener_issue": "Opener too narrow.", "issues": []},
                {"focus_key": "conversion", "label": "Conversion", "score": 7.2, "opener_issue": "", "issues": ["Minor non-blocking note."]},
            ],
            "repair_targets": [
                {
                    "focus_key": "retention",
                    "path": "opener",
                    "issue": "Opener too narrow.",
                    "instruction": "Repair only opener.",
                    "severity": "major",
                    "issue_scope": "field_level",
                    "action": "surgical_repair",
                }
            ],
            "typed_issues": [],
        }

        async def fake_repair_focus_track_surgically(**kwargs):
            track = dict(kwargs["existing_track"])
            track["opener"] = "Repaired retention opener?"
            return {
                "track": track,
                "source": "llm",
                "model": "fake-repair",
                "repair_provenance": [
                    {
                        "focus_key": kwargs["seed"]["focus_key"],
                        "path": "opener",
                        "old_value": kwargs["existing_track"]["opener"],
                        "new_value": track["opener"],
                        "issue_scope": "field_level",
                        "repair_reason": "test",
                        "model": "fake-repair",
                        "latency_ms": 1,
                        "accepted_by": "field_verifier",
                    }
                ],
            }

        async def fail_full_generation(**kwargs):
            raise AssertionError(f"untouched focus should not be regenerated: {kwargs['seed']['focus_key']}")

        old_repair = interview_map_module._repair_focus_track_surgically
        old_generate = interview_map_module._generate_focus_track
        try:
            interview_map_module._repair_focus_track_surgically = fake_repair_focus_track_surgically
            interview_map_module._generate_focus_track = fail_full_generation
            repaired = await interview_map_module._generate_priority_tracks_for_candidate(
                resume="resume",
                candidate=candidate,
                session_id="targeted",
                critic_feedback=critic_feedback,
                original_candidate=candidate,
                target_role="Product Analyst",
            )
        finally:
            interview_map_module._repair_focus_track_surgically = old_repair
            interview_map_module._generate_focus_track = old_generate

        repaired_areas = repaired["focus_areas"]
        assert repaired_areas[0]["track"]["opener"] == "Repaired retention opener?", repaired
        assert repaired_areas[1]["track"]["opener"] == area_two["opener"], repaired
        assert repaired_areas[1]["_track_generation_strategy"] == "preserved_untouched_track", repaired

    asyncio.run(_targeted_repair_preserves_untouched_tracks())

    leftover_review = interview_map_module._field_verified_review(
        {
            "ready": False,
            "overall_score": 7.2,
            "top_two_score": 7.2,
            "focus_reviews": [
                {"focus_key": "retention", "label": "Retention", "score": 7.0, "opener_issue": "Bad opener.", "issues": []},
                {"focus_key": "conversion", "label": "Conversion", "score": 7.0, "opener_issue": "", "issues": ["Bad follow-up."]},
            ],
            "typed_issues": [
                {"focus_key": "retention", "path": "opener", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad opener."},
                {"focus_key": "conversion", "path": "question_ladder[3].follow_up_if_strong", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad follow-up."},
            ],
            "repair_targets": [
                {"focus_key": "retention", "path": "opener", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad opener."},
                {"focus_key": "conversion", "path": "question_ladder[3].follow_up_if_strong", "issue_scope": "field_level", "action": "surgical_repair", "reason": "Bad follow-up."},
            ],
        },
        {
            "focus_areas": [
                {
                    "focus_key": "retention",
                    "_repair_provenance": [
                        {
                            "focus_key": "retention",
                            "path": "opener",
                            "accepted_by": "field_verifier",
                        }
                    ],
                }
            ]
        },
    )
    assert len(leftover_review["typed_issues"]) == 1, leftover_review
    assert leftover_review["typed_issues"][0]["focus_key"] == "conversion", leftover_review
    assert len(leftover_review["repair_targets"]) == 1, leftover_review
    assert interview_map_module._can_skip_full_repair_critic(
        {
            "focus_areas": [
                {
                    "_track_generation_strategy": "surgical_question_patch",
                    "_repair_provenance": [
                        {"accepted_by": "field_verifier", "focus_key": "retention", "path": "opener"}
                    ],
                },
                {
                    "_track_generation_strategy": "preserved_untouched_track",
                },
            ]
        },
        plan_repaired=False,
    )
    assert not interview_map_module._can_skip_full_repair_critic(
        {
            "focus_areas": [
                {
                    "_track_generation_strategy": "surgical_question_patch",
                    "_repair_provenance": [
                        {"accepted_by": "field_verifier", "focus_key": "retention", "path": "opener"}
                    ],
                },
                {
                    "_track_generation_strategy": "full_track_generation",
                },
            ]
        },
        plan_repaired=False,
    )

    hollow_schema_rescue_track = _runtime_area("trial_conversion", "Trial conversion")
    hollow_schema_rescue_track["question_ladder"][1]["main_question"] = "For that 42"
    hollow_schema_rescue_track["question_ladder"][1]["expected_space"] = []
    hollow_schema_rescue_track["dimensions"] = [
        {
            "id": "stat_sig",
            "label": "Statistical significance",
            "resume_anchor": "Trial conversion",
            "surface": "statistical significance",
            "mechanism": "funnel analysis",
            "boundary": "long-term retention",
            "signal_weight": 0.5,
        },
        {
            "id": "decision",
            "label": "Decision",
            "resume_anchor": "Trial conversion",
            "surface": "business impact",
            "mechanism": "hypothesis testing",
            "boundary": "data-driven decision making",
            "signal_weight": 0.5,
        },
    ]
    hollow_schema_rescue_track["recovery"]["short_answer"] = "I don't remember the denominator."
    rescue_flags = _track_schema_rescue_quality_flags(
        hollow_schema_rescue_track,
        seed={"focus_key": "trial_conversion", "label": "Trial conversion"},
    )
    assert "ladder[1].missing_question_mark" in rescue_flags, rescue_flags
    assert "dimensions[0].surface_placeholder" in rescue_flags, rescue_flags
    assert "recovery.short_answer_candidate_voice" in rescue_flags, rescue_flags

    recovery_only_review = {
        "ready": False,
        "overall_score": 7.8,
        "top_two_score": 7.8,
        "focus_reviews": [
            {"focus_key": "retention", "label": "Retention", "score": 8.1, "opener_issue": "", "issues": ["Recovery bridge duplicates ladder."]},
            {"focus_key": "conversion", "label": "Conversion", "score": 8.0, "opener_issue": "", "issues": []},
        ],
        "typed_issues": [
            {
                "focus_key": "retention",
                "path": "recovery.bridge",
                "issue_scope": "field_level",
                "severity": "major",
                "action": "surgical_repair",
                "reason": "Legacy bridge duplicates ladder synthesis.",
            }
        ],
        "repair_targets": [
            {
                "focus_key": "retention",
                "path": "recovery.bridge",
                "issue_scope": "field_level",
                "severity": "major",
                "action": "surgical_repair",
                "reason": "Legacy bridge duplicates ladder synthesis.",
            }
        ],
    }
    assert not _blocking_launch_repair_targets(recovery_only_review, ["retention", "conversion"]), recovery_only_review
    assert not interview_map_module._review_launch_failure_keys(recovery_only_review, ["retention", "conversion"]), recovery_only_review

    minor_empty_track_hint_review = {
        "ready": True,
        "overall_score": 8.4,
        "top_two_score": 8.4,
        "focus_reviews": [
            {"focus_key": "seller_taxonomy", "label": "Seller taxonomy", "score": 8.3, "opener_issue": "", "issues": []},
            {"focus_key": "dashboard_ops", "label": "Dashboard ops", "score": 8.2, "opener_issue": "", "issues": []},
        ],
        "typed_issues": [
            {
                "focus_key": "seller_taxonomy",
                "path": "question_ladder[*].follow_up_if_strong",
                "issue_scope": "track_level",
                "severity": "minor",
                "action": "track_repair",
                "reason": "",
            }
        ],
    }
    assert not _blocking_launch_repair_targets(
        minor_empty_track_hint_review,
        ["seller_taxonomy", "dashboard_ops"],
    ), minor_empty_track_hint_review
    assert not interview_map_module._launch_track_has_plan_issue(
        minor_empty_track_hint_review,
        ["seller_taxonomy", "dashboard_ops"],
    ), minor_empty_track_hint_review

    track_level_review = {
        "typed_issues": [
            {
                "focus_key": "weak_second_track",
                "path": "",
                "issue_scope": "track_level",
                "severity": "major",
                "action": "track_repair",
                "reason": "The whole track is under-grounded and should be replaced if repair fails.",
            }
        ]
    }
    assert interview_map_module._launch_track_has_plan_issue(
        track_level_review,
        ["primary_track", "weak_second_track"],
    ), track_level_review

    try:
        build_deterministic_interview_map(resume=MESSY_RESUME)
    except RuntimeError as exc:
        assert "disabled" in str(exc).lower(), exc
        print("deterministic interview-map fallback is disabled")
        return

    raise AssertionError("deterministic interview-map fallback unexpectedly succeeded")


if __name__ == "__main__":
    main()
