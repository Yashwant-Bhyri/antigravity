from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Awaitable

import backend.main  # noqa: F401 - loads app env without printing secrets
from backend.agents.application_agent import ApplicationAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.reasoning_behavior_agent import ReasoningBehaviorAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.models.llm_router import LLMRouter, MODEL_TIERS
from backend.services import interview_map as interview_map_module
from backend.services.interview_map import (
    _critique_map_candidate,
    _generate_focus_area_plan,
    _generate_focus_track,
    validate_interview_map,
)
from backend.test_small_model_quality_deepdive import (
    APPARAO_RESUME,
    MESSY_ENGINEER_RESUME,
    NOISY_ACADEMIC_RESUME,
    SENIOR_BACKEND_RESUME,
    VAGUE_OVERCLAIM_RESUME,
)


MODELS = [
    "anthropic/claude-sonnet-4.6",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3.5-flash",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
]

CALLTYPE_INVENTORY = [
    {"surface": "resume_parse", "tier": "small", "owner": "ResumeAgent.parse", "covered": "small_quality"},
    {"surface": "concept_extract", "tier": "small", "owner": "ConceptAgent.extract", "covered": "small_quality"},
    {"surface": "seed_question", "tier": "small", "owner": "FollowUpAgent.generate_seed_question", "covered": "small_quality"},
    {"surface": "clarification_fast", "tier": "small", "owner": "FollowUpAgent.generate_clarification", "covered": "small_quality"},
    {"surface": "adapt_followup", "tier": "small", "owner": "FollowUpAgent.adapt_followup", "covered": "small_quality"},
    {"surface": "speculative_followup", "tier": "small", "owner": "FollowUpAgent.generate_speculative", "covered": "small_quality"},
    {"surface": "implementation_anchor", "tier": "small", "owner": "Orchestrator._extract_implementation_anchor", "covered": "small_quality"},
    {"surface": "coverage_dimension_eval", "tier": "small", "owner": "Orchestrator._evaluate_coverage_dimension", "covered": "small_replacement"},
    {"surface": "application_coverage_eval", "tier": "small", "owner": "Orchestrator._evaluate_application_coverage", "covered": "small_quality"},
    {"surface": "confession_pivot", "tier": "small", "owner": "FollowUpAgent.generate_confession_pivot", "covered": "MISSING"},
    {"surface": "coverage_surface_question", "tier": "small", "owner": "FollowUpAgent.generate_coverage_surface", "covered": "MISSING"},
    {"surface": "coverage_depth_probe", "tier": "small", "owner": "FollowUpAgent.generate_coverage_depth_probe", "covered": "MISSING"},
    {"surface": "live_q4_candidates", "tier": "small", "owner": "Orchestrator._generate_live_q4_candidates", "covered": "MISSING"},
    {"surface": "weakness_detection", "tier": "medium", "owner": "WeaknessAgent.detect", "covered": "this_file"},
    {"surface": "discrepancy_check", "tier": "medium", "owner": "DiscrepancyAgent.check", "covered": "this_file"},
    {"surface": "reasoning_behavior", "tier": "medium", "owner": "ReasoningBehaviorAgent.evaluate", "covered": "this_file"},
    {"surface": "targeted_followup", "tier": "medium", "owner": "FollowUpAgent.generate", "covered": "this_file"},
    {"surface": "discrepancy_challenge", "tier": "medium", "owner": "FollowUpAgent.generate_discrepancy_challenge", "covered": "this_file"},
    {"surface": "sprint_question", "tier": "medium", "owner": "FollowUpAgent.generate_sprint_question", "covered": "this_file"},
    {"surface": "sprint_opener", "tier": "medium", "owner": "FollowUpAgent.generate_sprint_opener", "covered": "this_file"},
    {"surface": "prefetch", "tier": "medium", "owner": "FollowUpAgent.prefetch", "covered": "this_file"},
    {"surface": "application_transfer", "tier": "medium", "owner": "ApplicationAgent.generate", "covered": "this_file"},
    {"surface": "map_focus_plan", "tier": "medium", "owner": "interview_map._generate_focus_area_plan", "covered": "this_file"},
    {"surface": "map_track_generation", "tier": "medium/map_generator", "owner": "interview_map._generate_focus_track", "covered": "this_file"},
    {"surface": "map_critic", "tier": "medium/map_critic", "owner": "interview_map._critique_map_candidate", "covered": "this_file"},
    {"surface": "per_answer_score", "tier": "large", "owner": "EvaluationAgent.score_answer", "covered": "tier_matrix_only"},
    {"surface": "final_evaluation", "tier": "large", "owner": "EvaluationAgent.score_full_interview", "covered": "tier_matrix_only"},
    {"surface": "simulation_interviewer", "tier": "small", "owner": "SimulationService / InventorySimulationService interviewer", "covered": "OUTSIDE_AI_INTERVIEW_MIGRATION"},
    {"surface": "simulation_scorer", "tier": "medium", "owner": "SimulationService scorer", "covered": "OUTSIDE_AI_INTERVIEW_MIGRATION"},
]


CASES: list[dict[str, Any]] = [
    {
        "name": "apparao_clean_product",
        "resume": APPARAO_RESUME,
        "target_role": "Product Analyst",
        "years_experience": "1",
        "question": "Walk me through the analytics event tracking work at Daily Mantra.",
        "answer": (
            "I defined Daily Mantra events for session start, mantra discovery, track start, track end, video exposure, "
            "trial start, payment initiated, and subscription success, so retention and conversion experiments used stable denominators."
        ),
        "weak_answer": "We improved retention and conversion using dashboards and some experiments, but I do not remember the exact event definitions.",
        "application_answer": (
            "For BNPL I would separate payment initiated, authorization pending, webhook success, failed authorization, "
            "and order confirmed, with pending-state reporting and refund/support-ticket guardrails."
        ),
        "expected_focus_terms": ["daily mantra", "retention", "trial", "conversion", "event", "dashboard", "computer vision"],
        "expected_question_terms": ["event", "trial", "conversion", "denominator", "Daily Mantra", "retention", "dashboard"],
        "expected_weakness": {"type": {"vague", "ambiguous_but_promising", "shallow"}, "severity": {"medium", "high"}},
        "expected_discrepancy": {"none", "suspected"},
        "expected_reasoning": {"flexible", "admitted_gap", "underconfident", "calibrated"},
    },
    {
        "name": "messy_engineer",
        "resume": MESSY_ENGINEER_RESUME,
        "target_role": "AI Agent Development Engineer",
        "years_experience": "1",
        "question": "Walk me through the PixelForge image workflow.",
        "answer": (
            "For the image workflow I preserved seed consistency and mask validation through a React and Node interface, "
            "then tested whether prompt edits changed only the intended region instead of regenerating the whole image."
        ),
        "weak_answer": "I mostly connected APIs and prompts. The model did the image stuff, and I am not sure about the masking internals.",
        "application_answer": (
            "For a noisy wearable I would test microphone drift, confidence thresholds, buffering, and an uncertain-class path "
            "instead of forcing every clip into a label."
        ),
        "expected_focus_terms": ["pixelforge", "prompt", "seed", "mask", "react", "tiny", "tflite", "ocr"],
        "expected_question_terms": ["PixelForge", "prompt", "seed", "mask", "React", "Node", "image"],
        "expected_weakness": {"type": {"ambiguous_but_promising", "shallow", "vague"}, "severity": {"medium", "low"}},
        "expected_discrepancy": {"none", "suspected"},
        "expected_reasoning": {"admitted_gap", "calibrated", "underconfident"},
    },
    {
        "name": "vague_overclaim",
        "resume": VAGUE_OVERCLAIM_RESUME,
        "target_role": "Product Analyst",
        "years_experience": "3",
        "question": "You reported a 75% retention improvement. What exactly changed in the metric?",
        "answer": (
            "We looked at dashboards and conversion improved because of campaigns and models. "
            "I do not remember the exact denominator or guardrails."
        ),
        "weak_answer": (
            "We looked at dashboards and conversion improved because of campaigns and models. "
            "I do not remember the exact denominator or guardrails."
        ),
        "application_answer": "I would use AI dashboards for buyers and sellers. The main metric would be growth, and I would check details later.",
        "expected_focus_terms": ["checkout", "conversion", "instrumentation", "discount", "margin", "denominator"],
        "expected_question_terms": ["denominator", "guardrail", "conversion", "dashboard", "margin", "instrumentation", "ownership"],
        "expected_weakness": {"type": {"vague", "missing_step", "deflection", "ambiguous_but_promising"}, "severity": {"medium", "high"}},
        "expected_discrepancy": {"suspected", "confirmed"},
        "expected_reasoning": {"admitted_gap", "underconfident", "calibrated"},
    },
    {
        "name": "senior_backend_incident",
        "resume": SENIOR_BACKEND_RESUME,
        "target_role": "Backend Engineer",
        "years_experience": "5",
        "question": "Walk me through the idempotent retry flow.",
        "answer": (
            "The retry path used idempotency keys before enqueueing Kafka outbox events. Redis locks only protected short duplicate submissions; "
            "the real source of truth stayed in Postgres settlement state transitions."
        ),
        "weak_answer": "We used Redis and Kafka so duplicate payments stopped. I don't remember how settlement states were modeled.",
        "application_answer": (
            "For subscription pause/resume I would separate request accepted, billing paused, webhook confirmed, and entitlement changed, "
            "with idempotency keys and reconciliation for delayed webhooks."
        ),
        "expected_focus_terms": ["idempotent", "payment", "redis", "kafka", "outbox", "duplicate", "settlement"],
        "expected_question_terms": ["idempotency", "Kafka", "outbox", "Redis", "settlement", "duplicate", "webhook"],
        "expected_weakness": {"type": {"ambiguous_but_promising", "shallow", "missing_step"}, "severity": {"medium", "high"}},
        "expected_discrepancy": {"none", "suspected"},
        "expected_reasoning": {"calibrated", "admitted_gap", "underconfident"},
    },
    {
        "name": "noisy_academic",
        "resume": NOISY_ACADEMIC_RESUME,
        "target_role": "AI Product Engineer",
        "years_experience": "2",
        "question": "Walk me through the clinician-facing retrieval prototype.",
        "answer": (
            "The prototype logged failed-query categories and attached citation confidence labels so clinicians could see when the retrieval summary was weak."
        ),
        "weak_answer": "It was RAG, so we added citations and confidence. I don't know the exact evaluation setup.",
        "application_answer": (
            "For legal search I would track unsupported citation rates, failed-query categories, confidence labels, and review queues for low-confidence summaries."
        ),
        "expected_focus_terms": ["retrieval", "summaries", "keyword search", "failed-query", "citation", "confidence"],
        "expected_question_terms": ["retrieval", "citation", "confidence", "clinician", "failed-query", "prototype"],
        "expected_weakness": {"type": {"ambiguous_but_promising", "shallow", "vague"}, "severity": {"medium", "low"}},
        "expected_discrepancy": {"none", "suspected"},
        "expected_reasoning": {"admitted_gap", "calibrated", "underconfident"},
    },
]


@contextmanager
def medium_model(model: str):
    old_tiers = dict(MODEL_TIERS)
    old_generator = interview_map_module._MAP_GENERATOR_MODEL
    old_critic = interview_map_module._MAP_CRITIC_MODEL
    MODEL_TIERS["medium"] = model
    interview_map_module._MAP_GENERATOR_MODEL = model
    interview_map_module._MAP_CRITIC_MODEL = model
    try:
        yield
    finally:
        MODEL_TIERS.clear()
        MODEL_TIERS.update(old_tiers)
        interview_map_module._MAP_GENERATOR_MODEL = old_generator
        interview_map_module._MAP_CRITIC_MODEL = old_critic


def norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def text_of(value: object) -> str:
    if isinstance(value, tuple):
        value = value[0]
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("question") or value.get("followup") or value.get("text") or json.dumps(value, ensure_ascii=True))
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def hits(text: object, terms: list[str]) -> list[str]:
    haystack = norm(text)
    return [term for term in terms if norm(term) in haystack]


def score(base: int, failures: list[str], penalty: int = 14) -> int:
    return max(0, base - penalty * len(failures))


def validate_question(value: object, case: dict[str, Any], *, max_words: int = 34) -> tuple[int, list[str], dict[str, Any]]:
    text = text_of(value).strip()
    lower = norm(text)
    failures: list[str] = []
    if len(text.split()) < 6:
        failures.append("too_short")
    if len(text.split()) > max_words:
        failures.append("too_long")
    if not (text.endswith("?") or lower.startswith(("walk me through", "tell me", "explain", "describe", "help me", "show me", "switching to", "staying with"))):
        failures.append("not_question_like")
    if any(phrase in lower for phrase in ("tell me more", "can you elaborate", "walk me through that")) and not hits(text, case["expected_question_terms"]):
        failures.append("generic")
    grounded = hits(text, case["expected_question_terms"])
    if not grounded:
        failures.append("not_grounded_in_case")
    if case["name"] == "vague_overclaim" and not any(term in lower for term in ("denominator", "guardrail", "instrument", "margin", "metric", "ownership")):
        failures.append("missed_vague_overclaim_probe")
    if "lying" in lower or "fake" in lower or "caught" in lower:
        failures.append("bad_accusatory_tone")
    return score(100, failures), failures, {"grounded_hits": grounded}


def validate_weakness(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(result, dict):
        return 0, ["non_dict"], {}
    failures: list[str] = []
    for key in ("weakness", "type", "severity", "probe_direction", "continue_probing"):
        if key not in result:
            failures.append(f"missing_{key}")
    weakness_type = str(result.get("type") or "")
    severity = str(result.get("severity") or "")
    if weakness_type not in {"missing_step", "vague", "incorrect", "shallow", "overconfidence", "deflection", "ambiguous_but_promising"}:
        failures.append("bad_type")
    if severity not in {"low", "medium", "high"}:
        failures.append("bad_severity")
    expected = case.get("expected_weakness", {})
    if expected and weakness_type not in expected.get("type", set()):
        failures.append(f"unexpected_type:{weakness_type}")
    if expected and severity not in expected.get("severity", set()):
        failures.append(f"unexpected_severity:{severity}")
    if case["name"] in {"messy_engineer", "noisy_academic"} and severity == "high" and "do not remember" in norm(case["weak_answer"]):
        failures.append("overpunished_honest_gap")
    return score(100, failures, 12), failures, {"type": weakness_type, "severity": severity}


def validate_discrepancy(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(result, dict):
        return 0, ["non_dict"], {}
    failures: list[str] = []
    level = str(result.get("conflict_level") or "")
    if level not in {"none", "suspected", "confirmed"}:
        failures.append("bad_conflict_level")
    if level not in case.get("expected_discrepancy", {"none", "suspected", "confirmed"}):
        failures.append(f"unexpected_conflict:{level}")
    if not str(result.get("description") or "").strip():
        failures.append("missing_description")
    return score(100, failures, 16), failures, {"conflict_level": level}


def validate_reasoning(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(result, dict):
        return 0, ["non_dict"], {}
    failures: list[str] = []
    for key in ("structure_score", "clarification_behavior", "adaptability", "confidence_calibration", "notes"):
        if key not in result:
            failures.append(f"missing_{key}")
    adaptability = str(result.get("adaptability") or "")
    confidence = str(result.get("confidence_calibration") or "")
    if adaptability not in {"flexible", "rigid", "defensive", "confrontational", "admitted_gap"}:
        failures.append("bad_adaptability")
    if confidence not in {"calibrated", "overconfident", "underconfident"}:
        failures.append("bad_confidence")
    expected = case.get("expected_reasoning", set())
    if expected and adaptability not in expected and confidence not in expected:
        failures.append(f"unexpected_reasoning:{adaptability}/{confidence}")
    return score(100, failures, 12), failures, {"adaptability": adaptability, "confidence": confidence}


def validate_application(value: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict):
        return 0, ["non_dict"], {}
    failures: list[str] = []
    question = str(value.get("application_question") or "")
    dims = value.get("dimensions") or []
    if len(question.split()) < 16:
        failures.append("question_too_short")
    if not hits(question, case["expected_question_terms"]):
        failures.append("question_not_grounded")
    if not isinstance(dims, list) or not (4 <= len(dims) <= 6):
        failures.append("bad_dimension_count")
    else:
        dim_text = json.dumps(dims, ensure_ascii=True)
        if len(hits(dim_text, ["guardrail", "failure", "metric", "latency", "confidence", "state", "denominator", "reconciliation"])) < 2:
            failures.append("dimensions_not_role_rich")
        for idx, dim in enumerate(dims):
            if not isinstance(dim, dict):
                failures.append(f"dim_{idx}_not_dict")
                continue
            if not str(dim.get("id") or "").strip():
                failures.append(f"dim_{idx}_missing_id")
            if not str(dim.get("surfacing_question") or "").strip().endswith("?"):
                failures.append(f"dim_{idx}_bad_question")
    return score(100, failures, 12), failures, {"dimension_count": len(dims) if isinstance(dims, list) else 0}


def validate_prefetch(value: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(value, list):
        return 0, ["non_list"], {}
    failures: list[str] = []
    if not value:
        failures.append("empty")
    for q in value[:2]:
        q_score, q_failures, _ = validate_question(q, case, max_words=30)
        if q_score < 70:
            failures.extend(f"q_{f}" for f in q_failures[:2])
    return score(100, failures, 12), failures, {"count": len(value)}


def validate_focus_plan(value: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(value, dict):
        return 0, ["non_dict"], {}
    areas = value.get("focus_areas") or []
    failures: list[str] = []
    if not isinstance(areas, list) or not (2 <= len(areas) <= 5):
        failures.append("bad_focus_count")
        areas = []
    joined = json.dumps(areas, ensure_ascii=True)
    focus_hits = hits(joined, case["expected_focus_terms"])
    required = 3 if case["name"] != "apparao_clean_product" else 4
    if len(focus_hits) < required:
        failures.append(f"low_focus_recall:{len(focus_hits)}/{required}")
    if any(term in norm(joined) for term in ("phone", "email", "github maybe", "cgpa", "address")):
        failures.append("noise_leaked")
    keys = [str(area.get("focus_key") or "") for area in areas if isinstance(area, dict)]
    if len(keys) != len(set(keys)):
        failures.append("duplicate_focus_keys")
    return score(100, failures, 14), failures, {"focus_count": len(areas), "focus_hits": focus_hits}


def validate_track(value: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(value, dict):
        return 0, ["non_dict"], {}
    track = value.get("track") if "track" in value else value
    if not isinstance(track, dict):
        return 0, ["missing_track"], {}
    failures: list[str] = []
    opener = str(track.get("opener") or "")
    dims = track.get("dimensions") or []
    recovery = track.get("recovery") or {}
    if not opener:
        failures.append("missing_opener")
    elif not hits(opener, case["expected_question_terms"]):
        failures.append("opener_not_grounded")
    if not isinstance(dims, list) or len(dims) < 3:
        failures.append("too_few_dimensions")
    else:
        dim_text = json.dumps(dims, ensure_ascii=True)
        if len(hits(dim_text, case["expected_question_terms"] + ["mechanism", "boundary", "failure", "tradeoff"])) < 3:
            failures.append("dimensions_not_specific")
    required_recovery = {"short_answer", "honest_gap", "claim_conflict", "metric_risk", "overclaim_risk", "bridge"}
    if not isinstance(recovery, dict) or not required_recovery.issubset(set(recovery)):
        failures.append("incomplete_recovery")
    return score(100, failures, 14), failures, {"dimension_count": len(dims) if isinstance(dims, list) else 0}


def validate_critic(value: object, _case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(value, dict):
        return 0, ["non_dict"], {}
    failures: list[str] = []
    for key in ("ready", "overall_score", "top_two_score", "issues", "repair_instructions", "focus_reviews"):
        if key not in value:
            failures.append(f"missing_{key}")
    try:
        overall = float(value.get("overall_score", 0))
    except Exception:
        overall = 0.0
        failures.append("bad_overall_score")
    issues = value.get("issues") or []
    repairs = value.get("repair_instructions") or []
    if overall >= 8 and not issues:
        failures.append("failed_to_notice_flawed_map")
    if not repairs and not issues:
        failures.append("no_actionable_feedback")
    return score(100, failures, 12), failures, {"overall_score": overall}


async def timed(task: str, model: str, case: str, coro: Awaitable[Any], timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        if hasattr(result, "to_dict"):
            result = result.to_dict()
        return {
            "task": task,
            "model": model,
            "case": case,
            "ok": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "task": task,
            "model": model,
            "case": case,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "result": None,
            "error": f"{type(exc).__name__}: {str(exc)[:360]}",
        }


def parsed_stub(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_name": case["name"],
        "skills": case["expected_question_terms"][:6],
        "tools": case["expected_question_terms"][:6],
        "projects": [{"name": case["expected_focus_terms"][0], "description": case["answer"], "ownership_level": "primary"}],
        "claims": [{"text": case["answer"], "project": case["expected_focus_terms"][0], "strength": "strong"}],
        "experiences": [{"title": case["target_role"], "company": "resume company", "contribution_type": "built"}],
        "experience_tier": "mid",
    }


def flawed_map(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "focus_areas": [
            {
                "label": "General Background",
                "focus_key": "general_background",
                "anchor_context": "General resume discussion",
                "opener": "Tell me about yourself?",
                "dimensions": [],
                "recovery": {},
                "track_source": "llm",
            },
            {
                "label": "General Background Duplicate",
                "focus_key": "general_background_duplicate",
                "anchor_context": "General resume discussion",
                "opener": "Can you explain your work?",
                "dimensions": [],
                "recovery": {},
                "track_source": "llm",
            },
        ],
        "source": "llm",
    }


async def run_model_case(model: str, case: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with medium_model(model):
        parsed = parsed_stub(case)
        resume_context = _build_resume_context(parsed, case["resume"])

        weakness = WeaknessAgent()
        weakness.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
        row = await timed(
            "weakness_detection",
            model,
            case["name"],
            weakness.detect(
                case["question"],
                case["weak_answer"],
                sprint=1,
                parsed_resume=parsed,
                target_role=case["target_role"],
                years_experience=case["years_experience"],
                focus_areas=[{"focus_key": "primary_focus", "label": case["expected_focus_terms"][0]}],
            ),
            85.0,
        )
        row["score"], row["failures"], row["quality_details"] = validate_weakness(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)
        weakness_result = row.get("result") if isinstance(row.get("result"), dict) else {}

        discrepancy = DiscrepancyAgent()
        discrepancy.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
        row = await timed("discrepancy_check", model, case["name"], discrepancy.check(case["resume"], case["weak_answer"]), 85.0)
        row["score"], row["failures"], row["quality_details"] = validate_discrepancy(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)
        discrepancy_result = row.get("result") if isinstance(row.get("result"), dict) else {}

        reasoning = ReasoningBehaviorAgent()
        reasoning.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
        row = await timed("reasoning_behavior", model, case["name"], reasoning.evaluate(case["weak_answer"], was_challenged=True), 85.0)
        row["score"], row["failures"], row["quality_details"] = validate_reasoning(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)

        app = ApplicationAgent()
        app.llm = LLMRouter(tier="medium", model_override=model, timeout_override=90.0)
        row = await timed(
            "application_transfer",
            model,
            case["name"],
            app.generate(case["answer"], case["target_role"], case["target_role"], case["years_experience"], [case["resume"][:900]]),
            95.0,
        )
        row["score"], row["failures"], row["quality_details"] = validate_application(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)

        followup = FollowUpAgent()
        followup.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
        for task, coro, validator in [
            (
                "targeted_followup",
                followup.generate(
                    case["question"],
                    case["weak_answer"],
                    weakness_result or {"type": "vague", "weakness": "needs concrete mechanism", "probe_direction": "ownership_probe"},
                    "curious_lead",
                    case["resume"],
                    parsed_resume=parsed,
                    focus_context=f"Current focus: {case['expected_focus_terms'][0]}",
                ),
                lambda result: validate_question(result, case),
            ),
            (
                "discrepancy_challenge",
                followup.generate_discrepancy_challenge(
                    case["question"],
                    case["weak_answer"],
                    discrepancy_result or {"description": "The answer is weakly aligned with the resume claim.", "conflict_level": "suspected"},
                    "curious_lead",
                    case["resume"],
                    parsed_resume=parsed,
                ),
                lambda result: validate_question(result, case),
            ),
            (
                "sprint_question",
                followup.generate_sprint_question(
                    sprint=1,
                    persona="curious_lead",
                    resume=case["resume"],
                    history=[{"question": case["question"], "answer": case["answer"], "focus_label": case["expected_focus_terms"][0]}],
                    parsed_resume=parsed,
                    focus_context=f"Stay grounded in {case['expected_focus_terms'][0]}",
                    pivoting_hint=False,
                ),
                lambda result: validate_question(result, case, max_words=40),
            ),
            (
                "sprint_opener",
                followup.generate_sprint_opener(
                    sprint=2,
                    persona="curious_lead",
                    resume=case["resume"],
                    parsed_resume=parsed,
                    prior_sprint_history=[{"question": case["question"], "answer": case["answer"]}],
                    transition_brief="Move from claim narration into the technical mechanism.",
                    focus_context=f"Bridge from {case['expected_focus_terms'][0]} into its mechanism.",
                ),
                lambda result: validate_question(result, case, max_words=42),
            ),
            (
                "prefetch",
                followup.prefetch(case["expected_question_terms"][:3], {"current_persona": "curious_lead", "parsed_resume": parsed, "resume": case["resume"], "current_sprint": 1}),
                lambda result: validate_prefetch(result, case),
            ),
        ]:
            row = await timed(task, model, case["name"], coro, 85.0)
            row["score"], row["failures"], row["quality_details"] = validator(row.get("result")) if row["ok"] else (0, [row["error"]], {})
            rows.append(row)

        row = await timed(
            "map_focus_plan",
            model,
            case["name"],
            _generate_focus_area_plan(resume=case["resume"], session_id=f"medium-quality-{case['name']}", target_role=case["target_role"]),
            95.0,
        )
        row["score"], row["failures"], row["quality_details"] = validate_focus_plan(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)

        seed = {
            "label": case["expected_focus_terms"][0].title(),
            "focus_key": "primary_focus",
            "anchor_context": case["answer"],
            "resume_snippets": [case["answer"], case["resume"][:500]],
            "sub_focuses": case["expected_question_terms"][:3],
        }
        row = await timed(
            "map_track_generation",
            model,
            case["name"],
            _generate_focus_track(
                resume_context=case["resume"],
                seed=seed,
                next_focus_label="a second resume anchor",
                session_id=f"medium-quality-track-{case['name']}",
                fast_mode=False,
                role_type=case["target_role"],
            ),
            110.0,
        )
        row["score"], row["failures"], row["quality_details"] = validate_track(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)

        row = await timed(
            "map_critic",
            model,
            case["name"],
            _critique_map_candidate(resume=case["resume"], candidate=flawed_map(case), stage="quality_flawed_probe"),
            95.0,
        )
        row["score"], row["failures"], row["quality_details"] = validate_critic(row.get("result"), case) if row["ok"] else (0, [row["error"]], {})
        rows.append(row)

    return rows


def compact_result(value: object) -> object:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, str):
        return value[:900]
    if isinstance(value, list):
        return value[:8]
    if isinstance(value, dict):
        if "focus_areas" in value:
            validation = validate_interview_map(value, require_all_llm=False)
            return {
                "focus_count": len(value.get("focus_areas") or []),
                "validation": validation,
                "preview": [
                    {
                        "label": area.get("label"),
                        "focus_key": area.get("focus_key"),
                        "opener": area.get("opener"),
                        "dimension_count": len(area.get("dimensions") or []),
                        "track_source": area.get("track_source"),
                    }
                    for area in (value.get("focus_areas") or [])[:4]
                    if isinstance(area, dict)
                ],
            }
        if "track" in value and isinstance(value.get("track"), dict):
            track = value["track"]
            return {
                "source": value.get("source"),
                "opener": track.get("opener"),
                "dimension_count": len(track.get("dimensions") or []),
                "recovery_keys": sorted((track.get("recovery") or {}).keys()) if isinstance(track.get("recovery"), dict) else [],
                "candidate_q4_options": (track.get("candidate_q4_options") or [])[:3],
            }
        if "application_question" in value:
            return {
                "application_question": value.get("application_question"),
                "dimension_count": len(value.get("dimensions") or []),
                "dimensions": value.get("dimensions", [])[:3],
            }
        return value
    return value


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    by_task_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
        by_task_model.setdefault((row["task"], row["model"]), []).append(row)

    def pack(items: list[dict[str, Any]]) -> dict[str, Any]:
        scores = [int(row.get("score", 0)) for row in items]
        latencies = [int(row.get("elapsed_ms", 0)) for row in items]
        return {
            "passes": sum(1 for row in items if row.get("ok") and row.get("score", 0) >= 80),
            "calls": len(items),
            "avg_score": round(statistics.mean(scores), 1) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "avg_latency_ms": round(statistics.mean(latencies)) if latencies else 0,
            "failures": sorted({f for row in items for f in row.get("failures", []) if f})[:10],
        }

    return {
        "by_model": {model: pack(items) for model, items in by_model.items()},
        "by_task_model": {f"{task}::{model}": pack(items) for (task, model), items in sorted(by_task_model.items())},
    }


def write_inventory_report() -> Path:
    path = Path("/tmp/antigravity_llm_callsite_inventory.md")
    lines = [
        "# Antigravity LLM Call-Site Inventory",
        "",
        "| Surface | Tier | Owner | Coverage Status |",
        "|---|---|---|---|",
    ]
    for item in CALLTYPE_INVENTORY:
        lines.append(f"| `{item['surface']}` | `{item['tier']}` | `{item['owner']}` | `{item['covered']}` |")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_reports(rows: list[dict[str, Any]]) -> None:
    inventory_path = write_inventory_report()
    output_rows = []
    for row in rows:
        copied = dict(row)
        copied["result_preview"] = compact_result(copied.pop("result", None))
        output_rows.append(copied)
    summary = summarize(output_rows)

    suffix = os.environ.get("MEDIUM_QUALITY_OUTPUT_SUFFIX", "").strip()
    suffix_part = f"_{re.sub(r'[^A-Za-z0-9_.-]+', '_', suffix)}" if suffix else ""
    out_json = Path(f"/tmp/antigravity_medium_model_quality_deepdive{suffix_part}.json")
    out_md = Path(f"/tmp/antigravity_medium_model_quality_deepdive{suffix_part}.md")
    out_json.write_text(json.dumps({"inventory": CALLTYPE_INVENTORY, "summary": summary, "rows": output_rows}, indent=2, ensure_ascii=True), encoding="utf-8")

    lines = [
        "# Medium Model Contract + Quality Deep Dive",
        "",
        f"Inventory report: `{inventory_path}`",
        "",
        "Quality gate: score >= 80. Includes isolated contract checks and qualitative rubric checks for medium-tier interview surfaces.",
        "",
        "## Model Summary",
        "| Model | Passes | Calls | Avg Score | Min Score | Avg Latency ms | Failures |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for model, item in summary["by_model"].items():
        lines.append(
            f"| `{model}` | {item['passes']} | {item['calls']} | {item['avg_score']:.1f} | {item['min_score']} | {item['avg_latency_ms']} | {'; '.join(item['failures'][:6])} |"
        )

    lines.extend(["", "## Task Summary", "| Task | Model | Passes | Calls | Avg Score | Min Score | Avg Latency ms | Failures |", "|---|---|---:|---:|---:|---:|---:|---|"])
    for key, item in summary["by_task_model"].items():
        task, model = key.split("::", 1)
        lines.append(
            f"| `{task}` | `{model}` | {item['passes']} | {item['calls']} | {item['avg_score']:.1f} | {item['min_score']} | {item['avg_latency_ms']} | {'; '.join(item['failures'][:5])} |"
        )

    lines.extend(["", "## Representative Outputs"])
    interesting = {"application_transfer", "targeted_followup", "map_focus_plan", "map_track_generation", "map_critic"}
    for row in output_rows:
        if row["task"] not in interesting:
            continue
        if row["case"] != output_rows[0]["case"]:
            continue
        lines.append(f"\n### {row['task']} / `{row['model']}` / {row['case']}")
        lines.append(f"- Score: {row['score']} | Latency: {row['elapsed_ms']} ms | Failures: {', '.join(row.get('failures') or ['none'])}")
        lines.append("```json")
        lines.append(json.dumps(row.get("result_preview"), indent=2, ensure_ascii=True)[:2200])
        lines.append("```")

    lines.extend(["", f"JSON: `{out_json}`"])
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[MediumQuality] Wrote {out_json}")
    print(f"[MediumQuality] Wrote {out_md}")
    print(f"[MediumQuality] Wrote {inventory_path}")


async def main() -> None:
    models = [
        item.strip()
        for item in os.environ.get("MEDIUM_QUALITY_MODELS", ",".join(MODELS)).split(",")
        if item.strip()
    ]
    selected_cases = {
        item.strip()
        for item in os.environ.get("MEDIUM_QUALITY_CASES", "").split(",")
        if item.strip()
    }
    case_limit = int(os.environ.get("MEDIUM_QUALITY_CASE_LIMIT", str(len(CASES))) or len(CASES))
    cases = [case for case in CASES if not selected_cases or case["name"] in selected_cases][:case_limit]
    rows: list[dict[str, Any]] = []
    for model in models:
        print(f"[MediumQuality] Running {model}", flush=True)
        for case in cases:
            rows.extend(await run_model_case(model, case))
    write_reports(rows)
    for model, item in summarize(rows)["by_model"].items():
        print(
            f"[MediumQuality] {model}: {item['passes']}/{item['calls']} "
            f"passes, avg score {item['avg_score']}, avg latency {item['avg_latency_ms']}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
