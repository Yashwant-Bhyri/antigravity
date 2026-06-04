"""
Tier-aware model matrix for Antigravity's live AI interview module.

This is different from test_model_bakeoff.py:
- it does not force one model across every task
- it tests small candidates only on small-tier call sites
- it tests medium candidates only on medium-tier call sites
- it tests large candidates only on evaluation-tier call sites
- it runs a few full tier combinations through a realistic in-process interview chain

Run:
  python3 -m backend.test_tiered_model_matrix

Useful knobs:
  TIER_MATRIX_SMALL_CASE_LIMIT=2
  TIER_MATRIX_MEDIUM_CASE_LIMIT=2
  TIER_MATRIX_MAP_CASE_LIMIT=1
  TIER_MATRIX_E2E_CASE_LIMIT=1

The script imports backend.main so the normal application dotenv loader runs.
It does not print secrets. Results are written to /tmp.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import backend.main  # noqa: F401 - load app env without printing secrets
from backend.agents.application_agent import ApplicationAgent
from backend.agents.concept_agent import ConceptAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.evaluation_agent import EvaluationAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.reasoning_behavior_agent import ReasoningBehaviorAgent
from backend.agents.resume_agent import ResumeAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension
from backend.models.llm_router import LLMRouter, MODEL_TIERS
from backend.services import interview_map as interview_map_module
from backend.services.interview_map import generate_interview_map, validate_interview_map
from backend.services.orchestrator import Orchestrator
from backend.test_model_bakeoff import MESSY_AI_RESUME, _map_score, _question_score, _resume_score


SMALL_MODELS = [
    "anthropic/claude-haiku-4.5",
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash",
    "deepseek/deepseek-v4-flash",
]

MEDIUM_MODELS = [
    "anthropic/claude-sonnet-4.6",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
]

LARGE_MODELS = [
    "anthropic/claude-opus-4.8-fast",
    "anthropic/claude-sonnet-4.6",
    "google/gemini-3.1-pro-preview",
    "deepseek/deepseek-v4-pro",
]

TIER_COMBOS = [
    {
        "name": "claude_baseline",
        "small": "anthropic/claude-haiku-4.5",
        "medium": "anthropic/claude-sonnet-4.6",
        "large": "anthropic/claude-opus-4.8-fast",
        "map_generator": "anthropic/claude-sonnet-4.6",
        "map_critic": "anthropic/claude-sonnet-4.6",
    },
    {
        "name": "gemini_tiered",
        "small": "google/gemini-3.1-flash-lite",
        "medium": "google/gemini-3.1-pro-preview",
        "large": "google/gemini-3.1-pro-preview",
        "map_generator": "google/gemini-3.1-pro-preview",
        "map_critic": "google/gemini-3.1-pro-preview",
    },
    {
        "name": "deepseek_tiered",
        "small": "deepseek/deepseek-v4-flash",
        "medium": "deepseek/deepseek-v4-pro",
        "large": "deepseek/deepseek-v4-pro",
        "map_generator": "deepseek/deepseek-v4-pro",
        "map_critic": "deepseek/deepseek-v4-pro",
    },
    {
        "name": "gemini_small_claude_reasoning",
        "small": "google/gemini-3.1-flash-lite",
        "medium": "anthropic/claude-sonnet-4.6",
        "large": "anthropic/claude-opus-4.8-fast",
        "map_generator": "anthropic/claude-sonnet-4.6",
        "map_critic": "anthropic/claude-sonnet-4.6",
    },
    {
        "name": "gemini_small_sonnet_gemini_eval",
        "small": "google/gemini-3.1-flash-lite",
        "medium": "anthropic/claude-sonnet-4.6",
        "large": "google/gemini-3.1-pro-preview",
        "map_generator": "anthropic/claude-sonnet-4.6",
        "map_critic": "anthropic/claude-sonnet-4.6",
    },
]

SMALL_CASE_LIMIT = int(os.environ.get("TIER_MATRIX_SMALL_CASE_LIMIT", "2") or "2")
MEDIUM_CASE_LIMIT = int(os.environ.get("TIER_MATRIX_MEDIUM_CASE_LIMIT", "2") or "2")
LARGE_CASE_LIMIT = int(os.environ.get("TIER_MATRIX_LARGE_CASE_LIMIT", "1") or "1")
MAP_CASE_LIMIT = int(os.environ.get("TIER_MATRIX_MAP_CASE_LIMIT", "1") or "1")
E2E_CASE_LIMIT = int(os.environ.get("TIER_MATRIX_E2E_CASE_LIMIT", "1") or "1")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _cases() -> list[dict[str, str]]:
    root = Path(__file__).resolve().parent
    loaded = [
        _load_json(root / "runtime/qa_maps/merit_product_analyst_riya_resume.json"),
        _load_json(root / "runtime/qa_maps/trap_product_analyst_aarav_resume.json"),
    ]
    cases: list[dict[str, str]] = []
    for item in loaded:
        if isinstance(item, dict) and item.get("resume"):
            cases.append({
                "name": str(item.get("candidate") or item.get("name") or f"case_{len(cases)+1}"),
                "resume": str(item.get("resume") or ""),
                "target_role": str(item.get("target_role") or "Product Analyst"),
                "years_experience": str(item.get("years_experience") or "3"),
                "intro_answer": (
                    "I have been working on product analytics for checkout, retention, and reporting workflows, "
                    "mostly around instrumentation quality and causal analysis."
                ),
                "project_answer": (
                    "At BrightCart I rebuilt checkout instrumentation and split payment-start, payment-fail, "
                    "retry-success, and order-confirmed events so we could isolate wallet verification as the real drop-off."
                ),
                "application_answer": (
                    "For a marketplace version I would define seller-side and buyer-side funnel events separately, "
                    "hold denominator rules constant, segment by new versus returning users, and run a guardrail on refund rate."
                ),
            })
    cases.append({
        "name": "messy_ai_engineering_resume",
        "resume": MESSY_AI_RESUME,
        "target_role": "AI Agent Development Engineer",
        "years_experience": "1",
        "intro_answer": (
            "I recently worked on AIGC video workflows and TinyML audio inference, mostly integration-heavy engineering."
        ),
        "project_answer": (
            "For the TinyML classifier I integrated MediaPipe Audio feature extraction with TensorFlow Lite Micro INT8 "
            "deployment and worked on keeping latency under 10 milliseconds on the embedded target."
        ),
        "application_answer": (
            "If I had to move that to a noisy wearable device, I would validate feature drift, quantization accuracy, "
            "battery constraints, on-device buffering, and fallback behavior when the signal is too weak."
        ),
    })
    return cases


@contextmanager
def _tier_override(
    *,
    small: str | None = None,
    medium: str | None = None,
    large: str | None = None,
    map_generator: str | None = None,
    map_critic: str | None = None,
):
    old_tiers = dict(MODEL_TIERS)
    old_generator = interview_map_module._MAP_GENERATOR_MODEL
    old_critic = interview_map_module._MAP_CRITIC_MODEL
    if small:
        MODEL_TIERS["small"] = small
    if medium:
        MODEL_TIERS["medium"] = medium
    if large:
        MODEL_TIERS["large"] = large
    if map_generator:
        interview_map_module._MAP_GENERATOR_MODEL = map_generator
    if map_critic:
        interview_map_module._MAP_CRITIC_MODEL = map_critic
    try:
        yield
    finally:
        MODEL_TIERS.clear()
        MODEL_TIERS.update(old_tiers)
        interview_map_module._MAP_GENERATOR_MODEL = old_generator
        interview_map_module._MAP_CRITIC_MODEL = old_critic


async def _timed(scope: str, task: str, model: str, case: str, coro, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        row = {
            "scope": scope,
            "task": task,
            "model": model,
            "case": case,
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "result": result,
        }
        print(f"[TierMatrix] {scope}:{task}:{model}:{case} ok {row['latency_ms']}ms", flush=True)
        return row
    except Exception as exc:
        row = {
            "scope": scope,
            "task": task,
            "model": model,
            "case": case,
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:700],
        }
        print(f"[TierMatrix] {scope}:{task}:{model}:{case} FAIL {row['error_type']} {row['latency_ms']}ms", flush=True)
        return row


def _static_coverage_map(case: dict[str, str]) -> dict[str, Any]:
    cmap = AnswerCoverageMap(
        application_question="How would you transfer this work to a marketplace setting?",
        implementation_anchor=case["project_answer"],
        dimensions=[
            CoverageDimension(
                id="instrumentation_contract",
                label="Instrumentation contract",
                description="Defines stable event names, ownership, and denominator rules.",
                expected_approaches=["canonical events", "denominator rules", "event ownership"],
                surfacing_question="What event contract would you define first?",
                weight=1.5,
            ),
            CoverageDimension(
                id="causal_guardrails",
                label="Causal guardrails",
                description="Separates true lift from mix shift or selection effects.",
                expected_approaches=["cohorts", "holdout", "guardrail metrics"],
                surfacing_question="How would you stop a false lift from passing?",
                weight=1.5,
            ),
        ],
        total_weight=3.0,
    )
    return cmap.to_dict()


def _questionish_score(value: Any, resume: str) -> int:
    if isinstance(value, tuple):
        value = value[0]
    if isinstance(value, dict):
        value = value.get("question") or value.get("followup") or json.dumps(value)[:200]
    return _question_score(str(value or ""), resume)


def _dict_score(value: Any, keys: list[str]) -> int:
    if not isinstance(value, dict):
        return 0
    present = sum(1 for key in keys if value.get(key) not in (None, "", []))
    return round(100 * present / max(len(keys), 1))


def _concept_score(value: Any) -> int:
    if isinstance(value, list) and value:
        return min(40 + len(value) * 15, 100)
    return 0


def _app_score(value: Any) -> int:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict):
        return 0
    dims = value.get("dimensions") or []
    return min(35 + len(dims) * 20, 100) if value.get("application_question") and dims else 0


def _eval_score(value: Any, final: bool = False) -> int:
    if not isinstance(value, dict):
        return 0
    if final:
        keys = ["overall_score", "breakdown", "hire_recommendation", "confidence_score", "risk_flags"]
    else:
        keys = ["score", "breakdown", "confidence"]
    return _dict_score(value, keys)


def _compact_result(row: dict[str, Any]) -> None:
    result = row.get("result")
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    if isinstance(result, dict) and "focus_areas" in result:
        result = {
            "focus_count": len(result.get("focus_areas") or []),
            "validation": validate_interview_map(result, require_all_llm=False),
            "preview": [
                {
                    "label": area.get("label"),
                    "focus_key": area.get("focus_key"),
                    "track_source": area.get("track_source"),
                    "dimension_count": len(area.get("dimensions") or []),
                    "opener": area.get("opener"),
                }
                for area in (result.get("focus_areas") or [])[:4]
            ],
        }
    elif isinstance(result, dict):
        result = {k: v for k, v in result.items() if k not in {"raw_resume", "resume"}}
    row["result"] = result


async def _small_rows(model: str, cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _tier_override(small=model):
        for case in cases[:SMALL_CASE_LIMIT]:
            concept = ConceptAgent()
            concept.llm = LLMRouter(tier="small", model_override=model, timeout_override=25.0)
            row = await _timed("small", "concept_extract", model, case["name"], concept.extract(case["project_answer"]), 30.0)
            row["score"] = _concept_score(row.get("result"))
            rows.append(row)

            resume_agent = ResumeAgent()
            resume_agent.llm = LLMRouter(tier="small", model_override=model, timeout_override=45.0)
            row = await _timed(
                "small",
                "resume_parse",
                model,
                case["name"],
                resume_agent.parse(case["resume"], target_role=case["target_role"], years_experience=case["years_experience"]),
                50.0,
            )
            parsed = row.get("result") if row.get("ok") else {}
            row["score"] = _resume_score(parsed)
            rows.append(row)

            followup = FollowUpAgent()
            followup.llm_fast = LLMRouter(tier="small", model_override=model, timeout_override=30.0)
            resume_context = _build_resume_context(parsed if isinstance(parsed, dict) else {}, case["resume"])
            for task, coro in [
                ("seed_question", followup.generate_seed_question(1, "curious_lead", resume_context)),
                (
                    "clarification_fast",
                    followup.generate_clarification(
                        "What did you personally build?",
                        case["project_answer"],
                        {"type": "ownership_ambiguity", "weakness": "scope unclear", "probe_direction": "ownership_probe"},
                        "curious_lead",
                        case["resume"],
                        parsed_resume=parsed if isinstance(parsed, dict) else {},
                    ),
                ),
                (
                    "speculative_followup",
                    followup.generate_speculative(
                        partial_text=case["project_answer"][:500],
                        new_entities=["checkout", "instrumentation"],
                        last_question="Walk me through the strongest project.",
                        persona="curious_lead",
                        sprint=1,
                        resume_context=resume_context,
                        focus_context="Use the current project claim.",
                    ),
                ),
            ]:
                row = await _timed("small", task, model, case["name"], coro, 35.0)
                row["score"] = _questionish_score(row.get("result"), case["resume"]) if row.get("ok") else 0
                rows.append(row)

            orch = Orchestrator()
            row = await _timed(
                "small",
                "application_coverage_eval",
                model,
                case["name"],
                orch._evaluate_application_coverage(_static_coverage_map(case), case["application_answer"]),
                35.0,
            )
            result = row.get("result")
            row["score"] = 100 if isinstance(result, dict) and result else 0
            rows.append(row)
    return rows


async def _medium_rows(model: str, cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _tier_override(medium=model):
        for case in cases[:MEDIUM_CASE_LIMIT]:
            parsed_stub = {
                "candidate_name": case["name"],
                "claims": [{"text": case["project_answer"]}],
                "projects": [{"name": "primary claim", "description": case["project_answer"]}],
                "skills": ["analytics", "instrumentation", "causal analysis"],
            }
            resume_context = _build_resume_context(parsed_stub, case["resume"])

            weakness = WeaknessAgent()
            weakness.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
            row = await _timed(
                "medium",
                "weakness_detection",
                model,
                case["name"],
                weakness.detect(
                    "Walk me through the strongest project.",
                    case["project_answer"],
                    sprint=1,
                    parsed_resume=parsed_stub,
                    target_role=case["target_role"],
                    years_experience=case["years_experience"],
                ),
                80.0,
            )
            weakness_result = row.get("result") if row.get("ok") else {}
            row["score"] = _dict_score(weakness_result, ["type", "severity", "weakness", "probe_direction"])
            rows.append(row)

            discrepancy = DiscrepancyAgent()
            discrepancy.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
            row = await _timed(
                "medium",
                "discrepancy_check",
                model,
                case["name"],
                discrepancy.check(case["resume"], case["project_answer"]),
                80.0,
            )
            row["score"] = _dict_score(row.get("result"), ["conflict_level", "description", "should_confront"])
            rows.append(row)

            reasoning = ReasoningBehaviorAgent()
            reasoning.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
            row = await _timed("medium", "reasoning_behavior", model, case["name"], reasoning.evaluate(case["project_answer"], was_challenged=True), 80.0)
            row["score"] = _dict_score(row.get("result"), ["structure_score", "adaptability", "clarification_behavior"])
            rows.append(row)

            app = ApplicationAgent()
            app.llm = LLMRouter(tier="medium", model_override=model, timeout_override=80.0)
            row = await _timed(
                "medium",
                "application_transfer",
                model,
                case["name"],
                app.generate(
                    implementation_anchor=case["project_answer"],
                    candidate_domain=case["target_role"],
                    target_role=case["target_role"],
                    years_experience=case["years_experience"],
                    resume_snippets=[case["resume"][:600]],
                ),
                85.0,
            )
            row["score"] = _app_score(row.get("result"))
            rows.append(row)

            followup = FollowUpAgent()
            followup.llm = LLMRouter(tier="medium", model_override=model, timeout_override=75.0)
            row = await _timed(
                "medium",
                "targeted_followup",
                model,
                case["name"],
                followup.generate(
                    "Walk me through the strongest project.",
                    case["project_answer"],
                    weakness_result if isinstance(weakness_result, dict) else {"type": "depth", "weakness": "needs detail", "probe_direction": "step_by_step"},
                    "curious_lead",
                    case["resume"],
                    parsed_resume=parsed_stub,
                ),
                80.0,
            )
            row["score"] = _questionish_score(row.get("result"), case["resume"]) if row.get("ok") else 0
            rows.append(row)

            row = await _timed(
                "medium",
                "sprint_question",
                model,
                case["name"],
                followup.generate_sprint_question(
                    sprint=1,
                    persona="curious_lead",
                    resume=case["resume"],
                    history=[{"question": "Intro?", "answer": case["intro_answer"]}],
                    parsed_resume=parsed_stub,
                    focus_context="Stay on the primary project claim.",
                ),
                80.0,
            )
            row["score"] = _questionish_score(row.get("result"), case["resume"]) if row.get("ok") else 0
            rows.append(row)
    return rows


async def _large_rows(model: str, cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _tier_override(large=model):
        for case in cases[:LARGE_CASE_LIMIT]:
            evaluator = EvaluationAgent()
            evaluator.llm = LLMRouter(tier="large", model_override=model, timeout_override=150.0)
            row = await _timed(
                "large",
                "per_answer_score",
                model,
                case["name"],
                evaluator.score_answer(
                    "What data signal confirmed users were failing at wallet verification?",
                    case["project_answer"],
                    target_role=case["target_role"],
                    years_experience=case["years_experience"],
                ),
                170.0,
            )
            row["score"] = _eval_score(row.get("result"))
            rows.append(row)

            history = [
                {"sprint": 1, "persona": "curious_lead", "question": "Quick intro?", "answer": case["intro_answer"]},
                {"sprint": 1, "persona": "curious_lead", "question": "Walk me through the strongest project.", "answer": case["project_answer"]},
                {"sprint": 2, "persona": "socratic_mentor", "question": "How would you transfer this to a marketplace?", "answer": case["application_answer"]},
            ]
            row = await _timed(
                "large",
                "final_evaluation",
                model,
                case["name"],
                evaluator.score_full_interview(
                    history=history,
                    resume=case["resume"],
                    weaknesses=[{"type": "causal_reasoning", "severity": "medium", "weakness": "Needs denominator clarity"}],
                    reasoning_signals=[{"structure_score": 2, "adaptability": "steady", "clarification_behavior": "direct"}],
                    per_answer_scores=[{"question": "project", "score": 7.5, "breakdown": {}}],
                    target_role=case["target_role"],
                    years_experience=case["years_experience"],
                    parsed_resume={"claims": [{"text": case["project_answer"]}]},
                    coverage_map=_static_coverage_map(case),
                    coverage_ratio=0.65,
                ),
                170.0,
            )
            row["score"] = _eval_score(row.get("result"), final=True)
            rows.append(row)
    return rows


async def _map_rows(combo: dict[str, str], cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _tier_override(**{k: combo[k] for k in ("small", "medium", "large", "map_generator", "map_critic")}):
        for case in cases[:MAP_CASE_LIMIT]:
            row = await _timed(
                "e2e_combo",
                "interview_map_prepare",
                combo["name"],
                case["name"],
                generate_interview_map(
                    resume=case["resume"],
                    session_id=f"tier-matrix-{combo['name']}-{case['name'][:8]}",
                    target_role=case["target_role"],
                ),
                140.0,
            )
            row["small_model"] = combo["small"]
            row["medium_model"] = combo["medium"]
            row["large_model"] = combo["large"]
            row["map_generator"] = combo["map_generator"]
            row["map_critic"] = combo["map_critic"]
            row["score"] = _map_score(row.get("result")) if row.get("ok") else 0
            rows.append(row)
    return rows


async def _e2e_rows(combo: dict[str, str], cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _tier_override(**{k: combo[k] for k in ("small", "medium", "large", "map_generator", "map_critic")}):
        for case in cases[:E2E_CASE_LIMIT]:
            parsed: dict[str, Any] = {}
            map_payload: dict[str, Any] = {}
            history: list[dict[str, str]] = []
            total_score = 0
            parts = 0

            resume_agent = ResumeAgent()
            row = await _timed(
                "e2e_combo",
                "e2e_resume_parse",
                combo["name"],
                case["name"],
                resume_agent.parse(case["resume"], target_role=case["target_role"], years_experience=case["years_experience"]),
                60.0,
            )
            parsed = row.get("result") if row.get("ok") and isinstance(row.get("result"), dict) else {}
            row["score"] = _resume_score(parsed)
            total_score += row["score"]; parts += 1
            rows.append(row)

            row = await _timed(
                "e2e_combo",
                "e2e_map_prepare",
                combo["name"],
                case["name"],
                generate_interview_map(
                    resume=case["resume"],
                    session_id=f"e2e-{combo['name']}",
                    target_role=case["target_role"],
                ),
                150.0,
            )
            map_payload = row.get("result") if row.get("ok") and isinstance(row.get("result"), dict) else {}
            row["score"] = _map_score(map_payload)
            total_score += row["score"]; parts += 1
            rows.append(row)

            followup = FollowUpAgent()
            resume_context = _build_resume_context(parsed, case["resume"])
            row = await _timed("e2e_combo", "e2e_seed_question", combo["name"], case["name"], followup.generate_seed_question(1, "curious_lead", resume_context), 45.0)
            row["score"] = _questionish_score(row.get("result"), case["resume"])
            total_score += row["score"]; parts += 1
            rows.append(row)
            seed_question = str(row.get("result") or "Walk me through your strongest project.")
            history.append({"sprint": 1, "persona": "curious_lead", "question": seed_question, "answer": case["project_answer"]})

            weakness = WeaknessAgent()
            row = await _timed(
                "e2e_combo",
                "e2e_weakness_detection",
                combo["name"],
                case["name"],
                weakness.detect(seed_question, case["project_answer"], sprint=1, parsed_resume=parsed, target_role=case["target_role"], years_experience=case["years_experience"]),
                90.0,
            )
            weakness_result = row.get("result") if row.get("ok") and isinstance(row.get("result"), dict) else {}
            row["score"] = _dict_score(weakness_result, ["type", "severity", "weakness", "probe_direction"])
            total_score += row["score"]; parts += 1
            rows.append(row)

            app = ApplicationAgent()
            row = await _timed(
                "e2e_combo",
                "e2e_application_transfer",
                combo["name"],
                case["name"],
                app.generate(case["project_answer"], case["target_role"], case["target_role"], case["years_experience"], [case["resume"][:700]]),
                100.0,
            )
            app_result = row.get("result")
            row["score"] = _app_score(app_result)
            total_score += row["score"]; parts += 1
            rows.append(row)
            coverage_map = app_result.to_dict() if hasattr(app_result, "to_dict") else _static_coverage_map(case)
            history.append({"sprint": 2, "persona": "socratic_mentor", "question": coverage_map.get("application_question", "Application?"), "answer": case["application_answer"]})

            evaluator = EvaluationAgent()
            row = await _timed(
                "e2e_combo",
                "e2e_final_evaluation",
                combo["name"],
                case["name"],
                evaluator.score_full_interview(
                    history=history,
                    resume=case["resume"],
                    weaknesses=[weakness_result] if weakness_result else [],
                    reasoning_signals=[{"structure_score": 2, "adaptability": "steady", "clarification_behavior": "direct"}],
                    per_answer_scores=[],
                    coverage_ratio=0.65,
                    target_role=case["target_role"],
                    years_experience=case["years_experience"],
                    parsed_resume=parsed,
                    coverage_map=coverage_map,
                ),
                170.0,
            )
            row["score"] = _eval_score(row.get("result"), final=True)
            total_score += row["score"]; parts += 1
            rows.append(row)

            combo_ok = all(
                r.get("ok")
                for r in rows
                if r.get("model") == combo["name"]
                and r.get("case") == case["name"]
                and r.get("task", "").startswith("e2e_")
            )
            rows.append({
                "scope": "e2e_combo",
                "task": "combo_summary",
                "model": combo["name"],
                "case": case["name"],
                "ok": combo_ok,
                "latency_ms": sum(int(r.get("latency_ms", 0) or 0) for r in rows if r.get("model") == combo["name"] and r.get("case") == case["name"] and r.get("task", "").startswith("e2e_")),
                "score": round(total_score / max(parts, 1), 1),
                "error_type": None if combo_ok else "ComboFailed",
                "error": None if combo_ok else "One or more E2E stages failed.",
                "small_model": combo["small"],
                "medium_model": combo["medium"],
                "large_model": combo["large"],
                "map_generator": combo["map_generator"],
                "map_critic": combo["map_critic"],
            })
    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["scope"], row["task"], row["model"]), []).append(row)
    task_rankings: dict[str, list[dict[str, Any]]] = {}
    for (scope, task, model), group in grouped.items():
        scores = [float(r.get("score", 0) or 0) for r in group]
        ok_count = sum(1 for r in group if r.get("ok"))
        latencies = [int(r.get("latency_ms", 0) or 0) for r in group if r.get("ok")]
        task_rankings.setdefault(f"{scope}:{task}", []).append({
            "model": model,
            "success_rate": ok_count / max(len(group), 1),
            "mean_score": statistics.mean(scores) if scores else 0,
            "median_latency_ms": statistics.median(latencies) if latencies else None,
            "calls": len(group),
        })
    for ranked in task_rankings.values():
        ranked.sort(key=lambda item: (item["success_rate"], item["mean_score"], -(item["median_latency_ms"] or 999999)), reverse=True)

    by_model_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_model_scope.setdefault((row["scope"], row["model"]), []).append(row)
    overall = []
    for (scope, model), group in by_model_scope.items():
        scores = [float(r.get("score", 0) or 0) for r in group]
        latencies = [int(r.get("latency_ms", 0) or 0) for r in group if r.get("ok")]
        overall.append({
            "scope": scope,
            "model": model,
            "success_rate": sum(1 for r in group if r.get("ok")) / max(len(group), 1),
            "mean_score": statistics.mean(scores) if scores else 0,
            "median_latency_ms": statistics.median(latencies) if latencies else None,
            "calls": len(group),
        })
    overall.sort(key=lambda item: (item["scope"], -item["success_rate"], -item["mean_score"], item["median_latency_ms"] or 999999))
    return {"overall": overall, "task_rankings": task_rankings}


def _markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = ["# Antigravity Tiered Model Matrix", ""]
    lines.append("## Scope")
    lines.append("- Small tier: concept extraction, resume parsing, seed/clarification/speculative questions, application coverage classification.")
    lines.append("- Medium tier: weakness, discrepancy, reasoning behavior, application transfer, targeted follow-up, sprint question.")
    lines.append("- Large tier: per-answer scoring and final interview evaluation.")
    lines.append("- E2E combinations: resume parse -> map prep -> seed question -> weakness -> application transfer -> final evaluation.")
    lines.append("")
    lines.append("## Overall By Scope")
    lines.append("| Scope | Model/combo | Success | Mean score | Median latency | Calls |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for item in summary["overall"]:
        lines.append(
            f"| {item['scope']} | `{item['model']}` | {item['success_rate']:.0%} | "
            f"{item['mean_score']:.1f} | {item['median_latency_ms'] or 'n/a'} ms | {item['calls']} |"
        )
    lines.append("")
    lines.append("## Task Rankings")
    for task, ranked in summary["task_rankings"].items():
        lines.append(f"### {task}")
        lines.append("| Rank | Model/combo | Success | Mean score | Median latency | Calls |")
        lines.append("|---:|---|---:|---:|---:|---:|")
        for idx, item in enumerate(ranked, 1):
            lines.append(
                f"| {idx} | `{item['model']}` | {item['success_rate']:.0%} | "
                f"{item['mean_score']:.1f} | {item['median_latency_ms'] or 'n/a'} ms | {item['calls']} |"
            )
        lines.append("")
    failures = [r for r in rows if not r.get("ok")]
    if failures:
        lines.append("## Failures")
        for row in failures[:80]:
            lines.append(
                f"- `{row['scope']}` / `{row['model']}` / `{row['case']}` / `{row['task']}`: "
                f"{row.get('error_type')} - {row.get('error')}"
            )
    return "\n".join(lines).strip() + "\n"


async def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not available after app env load.")
    cases = _cases()
    rows: list[dict[str, Any]] = []

    for model in SMALL_MODELS:
        rows.extend(await _small_rows(model, cases))
    for model in MEDIUM_MODELS:
        rows.extend(await _medium_rows(model, cases))
    for model in LARGE_MODELS:
        rows.extend(await _large_rows(model, cases))
    for combo in TIER_COMBOS:
        rows.extend(await _map_rows(combo, cases))
    for combo in TIER_COMBOS:
        rows.extend(await _e2e_rows(combo, cases))

    for row in rows:
        _compact_result(row)

    summary = _summarize(rows)
    out_json = Path("/tmp/antigravity_tiered_model_matrix_results.json")
    out_md = Path("/tmp/antigravity_tiered_model_matrix_report.md")
    out_json.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str), encoding="utf-8")
    out_md.write_text(_markdown(summary, rows), encoding="utf-8")
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(_markdown(summary, rows))


if __name__ == "__main__":
    asyncio.run(main())
