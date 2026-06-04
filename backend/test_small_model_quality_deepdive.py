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

from backend.agents.concept_agent import ConceptAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.resume_agent import ResumeAgent
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension
from backend.models.llm_router import LLMRouter, MODEL_TIERS
from backend.services.orchestrator import Orchestrator


MODELS = [
    "anthropic/claude-haiku-4.5",
    "google/gemini-3.1-flash-lite",
]

APPARAO_RESUME = """S V S APPARAO
Education: IIIT Sri City, B.Tech CSE, CGPA 7.51/10.
Product Analyst, Daily Mantra, AppsforBharat, Dec 2024-Present.
- Increased user retention from 25% to 42% through A/B testing and deployed features (Video, Today, AI Guruji).
- Optimized trial-to-subscription conversion rate from 27% to 42% by reducing trial period from 7 days to 1 day.
- Increased Mantra Track End completion from 27.5% to 55.5% by launching Videos and Today experiments.
- Architected analytics event tracking for Daily Mantra zero-to-one product, defining session flow, engagement, feature adoption, and conversion funnel events.
Associate Business Analyst, AppsforBharat, May 2024-Nov 2024.
- Automated AppsFlyer dashboards for campaign/ad-set CAC, CPI, CPM, spend.
- Created an executive business dashboard integrating impressions, transactions, and conversions.
Computer Vision Intern, IIT Hyderabad.
- Benchmarked blob tracking, YOLO with SORT, and optical flow across 400+ road frames.
"""

MESSY_ENGINEER_RESUME = """k latha | mail junk | github maybe
random notes: loves ai stuff and frontend/backend and cv.
Experience --
AI Engineer Intern @ PixelForge:
made prompt workflow for image edits, reduced failed regeneration, had seed control, mask validation, React/Node UI, queue retry on provider failure.
ML Project:
tiny audio classifier on microcontroller; TensorFlow Lite Micro INT8; target latency <10ms; validation around 95 percent; noisy labels.
Research helper:
OCR + retrieval notes for scanned forms, compared retrieval prompts and extraction errors, no production deploy.
Skills: python javascript sql react fastapi pytorch opencv APIs.
"""

VAGUE_OVERCLAIM_RESUME = """Aarav M
Product Analyst, Northstar Commerce.
- Improved checkout conversion from 41% to 36% after fixing instrumentation for payment-start, payment-fail, retry-success, and order-confirmed.
- Discount experiment showed +12% conversion lift but 4.6 point gross-margin drop.
Product Analyst, VideoHealth.
- Reported 75% retention improvement while denominator changed from lesson_started to video_started.
- Built dashboards for Video Growth, AI Coach Quality, and Today Engagement with different active-user definitions.
"""

SENIOR_BACKEND_RESUME = """Riya Sen
Senior Backend Engineer, LedgerPay, 2020-2025.
- Designed idempotent payment retry flow using idempotency keys, Redis locks, Kafka outbox events, and reconciliation jobs.
- Reduced duplicate-charge incidents by 68% by separating authorization, capture, webhook receipt, and settlement states.
- Migrated monolith billing worker to FastAPI services with Postgres, Redis, Kafka, Prometheus alerts, and runbooks.
Backend Engineer, ShopGrid, 2017-2020.
- Built order fulfillment APIs and inventory reservation flows with optimistic locking.
"""

NOISY_ACADEMIC_RESUME = """Dr. M. Rao | +91 9999999999 | LinkedIn | email@example.com
Education:
PhD coursework in Human-Computer Interaction, GPA 3.8. Many seminars. Address line.
Publications:
- Workshop paper on evaluating hallucination explanations for medical search interfaces.
Projects:
- Built a clinician-facing prototype that compared retrieval-augmented summaries against baseline keyword search, logged failed-query categories, and added citation confidence labels.
Teaching:
- TA for databases and statistics.
Skills:
Python, SQL, Streamlit, Postgres, IR evaluation, annotation guidelines.
"""


CASES: list[dict[str, Any]] = [
    {
        "name": "apparao_clean_product",
        "target_role": "Product Analyst",
        "years_experience": "1",
        "resume": APPARAO_RESUME,
        "answer": (
            "I defined Daily Mantra events for session start, mantra discovery, track start, track end, "
            "video exposure, trial start, payment initiated, and subscription success so retention and conversion experiments had clean denominators."
        ),
        "partial": "event taxonomy trial conversion mantra track completion denominator",
        "expected_terms": ["retention", "trial", "conversion", "track end", "event", "dashboard", "computer vision"],
        "expected_concepts": ["event", "taxonomy", "trial", "conversion", "denominator"],
        "question_terms": ["Daily Mantra", "retention", "trial", "event", "dashboard", "AppsFlyer", "Mantra"],
        "forbidden_terms": ["email", "phone", "linkedin", "github", "cgpa"],
        "anchor_expected": True,
        "anchor_terms": ["event", "track", "trial", "taxonomy", "denominator"],
        "application_answer": (
            "For BNPL I would separate payment initiated, authorization pending, webhook success, failed authorization, "
            "and order confirmed. I would use pending states in daily reporting and keep refund and support-ticket guardrails."
        ),
        "expected_coverage": {"denominator": "voluntary", "guardrails": "voluntary", "uncertainty": "voluntary"},
    },
    {
        "name": "messy_engineer",
        "target_role": "AI Agent Development Engineer",
        "years_experience": "1",
        "resume": MESSY_ENGINEER_RESUME,
        "answer": (
            "For the image workflow I preserved seed consistency and mask validation through a React and Node interface, "
            "then tested whether prompt edits changed only the intended region instead of regenerating the whole image."
        ),
        "partial": "seed control mask validation prompt workflow React Node image edits",
        "expected_terms": ["pixelforge", "prompt", "seed", "mask", "react", "tiny", "tflite", "ocr"],
        "expected_concepts": ["seed", "mask", "prompt", "react", "workflow"],
        "question_terms": ["PixelForge", "prompt", "seed", "mask", "React", "TinyML", "TensorFlow", "audio classifier", "microcontroller", "OCR"],
        "forbidden_terms": ["mail junk", "contact", "github maybe"],
        "anchor_expected": True,
        "anchor_terms": ["seed", "mask", "prompt", "React", "Node"],
        "application_answer": (
            "On a noisy wearable I would test microphone drift, confidence thresholds, buffering, "
            "and an uncertain-class path instead of forcing every clip into a label."
        ),
        "expected_coverage": {"uncertainty": "voluntary"},
    },
    {
        "name": "vague_overclaim",
        "target_role": "Product Analyst",
        "years_experience": "3",
        "resume": VAGUE_OVERCLAIM_RESUME,
        "answer": (
            "We looked at dashboards and conversion improved because of campaigns and models. "
            "I do not remember the exact denominator or guardrails."
        ),
        "partial": "dashboards conversion improved models campaigns denominator not remember",
        "expected_terms": ["checkout", "conversion", "instrumentation", "discount", "margin", "denominator"],
        "expected_concepts": ["dashboard", "conversion", "denominator", "guardrail"],
        "question_terms": ["Northstar", "VideoHealth", "checkout", "denominator", "guardrail", "conversion", "dashboard", "margin", "instrumentation"],
        "forbidden_terms": ["definitely built", "personally built the model", "productionized"],
        "anchor_expected": False,
        "anchor_terms": [],
        "application_answer": "I would use AI dashboards for buyers and sellers. The main metric would be growth, and I would check details later.",
        "expected_coverage": {"denominator": "not_evaluated", "guardrails": "not_evaluated"},
    },
    {
        "name": "terse_honest_gap",
        "target_role": "Product Analyst",
        "years_experience": "2",
        "resume": VAGUE_OVERCLAIM_RESUME,
        "answer": (
            "I owned some event definitions and queries, but another engineer productionized the dbt models, "
            "so my ownership should be scoped."
        ),
        "partial": "owned event definitions queries engineer productionized dbt ownership scoped",
        "expected_terms": ["checkout", "conversion", "instrumentation", "dashboard", "active-user", "denominator"],
        "expected_concepts": ["event", "queries", "dbt", "ownership"],
        "question_terms": ["Northstar", "checkout", "owned", "event", "query", "dbt", "handoff", "scope", "instrumentation"],
        "forbidden_terms": ["lying", "fake", "caught", "contradiction"],
        "anchor_expected": True,
        "anchor_terms": ["event", "query", "ownership", "scoped"],
        "application_answer": "I would define event names, firing rules, denominator checks, and handoff notes for the engineer.",
        "expected_coverage": {"denominator": "voluntary"},
    },
    {
        "name": "senior_backend_incident",
        "target_role": "Backend Engineer",
        "years_experience": "5",
        "resume": SENIOR_BACKEND_RESUME,
        "answer": (
            "The retry path used idempotency keys before enqueueing Kafka outbox events. Redis locks only protected short duplicate submissions; "
            "the real source of truth stayed in Postgres settlement state transitions."
        ),
        "partial": "idempotency keys Kafka outbox Redis locks Postgres settlement state",
        "expected_terms": ["idempotent", "payment", "redis", "kafka", "outbox", "duplicate-charge", "settlement"],
        "expected_concepts": ["idempotency", "kafka", "outbox", "redis", "postgres"],
        "question_terms": ["LedgerPay", "payment", "idempotency", "Kafka", "outbox", "Redis", "settlement", "duplicate"],
        "forbidden_terms": ["frontend", "computer vision", "marketing"],
        "anchor_expected": True,
        "anchor_terms": ["idempotency", "Kafka", "outbox", "Redis", "Postgres"],
        "application_answer": (
            "For subscription pause/resume I would separate request accepted, billing paused, webhook confirmed, and entitlement changed, "
            "with idempotency keys and reconciliation for delayed webhooks."
        ),
        "expected_coverage": {"uncertainty": "voluntary", "denominator": "voluntary"},
    },
    {
        "name": "noisy_academic",
        "target_role": "AI Product Engineer",
        "years_experience": "2",
        "resume": NOISY_ACADEMIC_RESUME,
        "answer": (
            "The prototype logged failed-query categories and attached citation confidence labels so clinicians could see when the retrieval summary was weak."
        ),
        "partial": "failed query categories citation confidence labels retrieval summary",
        "expected_terms": ["retrieval", "summaries", "keyword search", "failed-query", "citation", "confidence"],
        "expected_concepts": ["retrieval", "citation", "confidence", "prototype"],
        "question_terms": ["retrieval", "citation", "confidence", "clinician", "failed-query", "prototype"],
        "forbidden_terms": ["phone", "email", "address", "gpa"],
        "anchor_expected": True,
        "anchor_terms": ["failed-query", "citation", "confidence", "retrieval"],
        "application_answer": (
            "For legal search I would track unsupported citation rates, failed-query categories, confidence labels, and review queues for low-confidence summaries."
        ),
        "expected_coverage": {"guardrails": "voluntary", "uncertainty": "voluntary"},
    },
]


@contextmanager
def small_model(model: str):
    old = MODEL_TIERS.get("small")
    MODEL_TIERS["small"] = model
    try:
        yield
    finally:
        MODEL_TIERS["small"] = old


def normalize(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def result_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("question") or value.get("followup") or value.get("text") or json.dumps(value, ensure_ascii=True))
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def hit_count(text: object, terms: list[str]) -> int:
    haystack = normalize(text)
    return sum(1 for term in terms if normalize(term) in haystack)


def term_hits(text: object, terms: list[str]) -> list[str]:
    haystack = normalize(text)
    return [term for term in terms if normalize(term) in haystack]


def score_from_failures(base: int, failures: list[str], penalty: int = 12) -> int:
    return max(0, base - penalty * len(failures))


def validate_resume_parse(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    failures: list[str] = []
    if not isinstance(result, dict):
        return 0, ["non_dict"], {}
    for key in ("skills", "tools", "projects", "claims", "experiences"):
        if key not in result:
            failures.append(f"missing_{key}")
    claims = result.get("claims") if isinstance(result.get("claims"), list) else []
    projects = result.get("projects") if isinstance(result.get("projects"), list) else []
    experiences = result.get("experiences") if isinstance(result.get("experiences"), list) else []
    tools = result.get("tools") if isinstance(result.get("tools"), list) else []
    haystack = json.dumps(
        {"claims": claims, "projects": projects, "experiences": experiences, "tools": tools},
        ensure_ascii=True,
    )
    hits = term_hits(haystack, case["expected_terms"])
    required_hits = max(3, min(5, len(case["expected_terms"]) - 1))
    if len(hits) < required_hits:
        failures.append(f"low_golden_claim_recall:{len(hits)}/{required_hits}")
    noise_hits = term_hits(haystack, case["forbidden_terms"])
    if noise_hits:
        failures.append(f"noise_or_hallucination:{','.join(noise_hits[:3])}")
    if len(claims) + len(projects) < 2:
        failures.append("too_few_work_anchors")
    if case["name"] == "noisy_academic" and re.search(r"\b(gpa|phone|address|email)\b", normalize(haystack)):
        failures.append("academic_contact_noise_leaked")
    score = 100
    score -= max(0, required_hits - len(hits)) * 10
    score -= 14 * len([f for f in failures if not f.startswith("low_golden")])
    return max(0, score), failures, {"expected_hits": hits, "noise_hits": noise_hits}


def validate_concepts(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(result, list):
        return 0, ["non_list"], {}
    hits = term_hits(result, case["expected_concepts"])
    failures: list[str] = []
    if len(hits) < max(2, len(case["expected_concepts"]) - 1):
        failures.append(f"low_concept_recall:{len(hits)}/{len(case['expected_concepts'])}")
    if len(result) > 12:
        failures.append("concept_list_too_broad")
    bad_hits = term_hits(result, case["forbidden_terms"])
    if bad_hits:
        failures.append(f"forbidden_concept:{','.join(bad_hits[:2])}")
    return score_from_failures(round(100 * len(hits) / max(len(case["expected_concepts"]), 1)), failures, 10), failures, {"expected_hits": hits}


def validate_question(result: object, case: dict[str, Any], *, kind: str) -> tuple[int, list[str], dict[str, Any]]:
    text = result_text(result).strip()
    lower = normalize(text)
    failures: list[str] = []
    words = text.split()
    if len(words) < 6:
        failures.append("too_short")
    if len(words) > (38 if kind == "seed_question" else 26):
        failures.append("too_long")
    questionish = (
        text.endswith("?")
        or lower.startswith(("walk me through", "tell me", "explain", "describe", "help me understand", "show me"))
        or re.match(r"^(great|nice|okay|got it|that.s helpful).{0,80}\b(tell me|walk me|help me|show me)\b", lower)
    )
    if not questionish:
        failures.append("not_question_like")
    generic_patterns = (
        "tell me more",
        "can you elaborate",
        "walk me through that",
        "what did you do there",
        "what was your role in this project",
    )
    grounded_hits = term_hits(text, case["question_terms"])
    if any(pattern in lower for pattern in generic_patterns) and not grounded_hits:
        failures.append("generic_question")
    if not grounded_hits:
        failures.append("not_grounded_in_case")
    forbidden_hits = term_hits(text, case["forbidden_terms"])
    if forbidden_hits:
        failures.append(f"forbidden_or_bad_tone:{','.join(forbidden_hits[:3])}")
    if case["name"] == "vague_overclaim" and not any(term in lower for term in ("denominator", "guardrail", "metric", "instrument", "margin", "owner", "ownership")):
        failures.append("missed_vague_overclaim_probe")
    if case["name"] == "terse_honest_gap" and any(term in lower for term in ("contradict", "inconsistent", "why claim", "why did you say")):
        failures.append("punished_honest_scope")
    return score_from_failures(100, failures, 14), failures, {"grounded_hits": grounded_hits}


def validate_speculative(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(result, dict):
        return 0, ["non_dict"], {}
    action = str(result.get("action") or "").strip()
    failures: list[str] = []
    if action not in {"keep", "replace", "use_map_candidate"}:
        failures.append("invalid_action")
    if action == "replace":
        score, q_failures, details = validate_question(result.get("question", ""), case, kind="speculative_followup")
        return max(0, score - 8 * len(failures)), failures + q_failures, details
    if action == "use_map_candidate":
        return 90, failures, {"action": action}
    return score_from_failures(84, failures, 20), failures, {"action": action}


def validate_anchor(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    text = result_text(result).strip()
    lower = normalize(text)
    failures: list[str] = []
    if not case["anchor_expected"]:
        if not text or lower in {"none", "null", '""', "empty string"}:
            return 100, [], {"anchor_hits": []}
        if any(marker in lower for marker in ("no specific", "not enough", "does not describe")):
            return 96, [], {"anchor_hits": []}
        if len(text.split()) > 7:
            failures.append("invented_specific_anchor_for_vague_answer")
        return score_from_failures(70, failures, 25), failures, {"anchor_hits": term_hits(text, case["anchor_terms"])}
    hits = term_hits(text, case["anchor_terms"])
    if len(hits) < max(1, min(3, len(case["anchor_terms"]) - 1)):
        failures.append(f"low_anchor_specificity:{len(hits)}")
    if len(text.split()) < 8:
        failures.append("anchor_too_short")
    if any(marker in lower for marker in ("no specific", "not provided", "empty string")):
        failures.append("anchor_refused_when_expected")
    return score_from_failures(100, failures, 18), failures, {"anchor_hits": hits}


def build_coverage_map(case: dict[str, Any]) -> dict[str, Any]:
    dims = [
        CoverageDimension(
            id="denominator",
            label="Denominator discipline",
            description="Defines boundaries, entry criteria, or state transitions for the metric/system.",
            expected_approaches=["event boundary", "entry criteria", "state transition"],
            surfacing_question="What exactly enters the denominator or state boundary here?",
            weight=2.5,
        ),
        CoverageDimension(
            id="guardrails",
            label="Guardrails",
            description="Names adverse metrics or safety checks that prevent a misleading win.",
            expected_approaches=["refunds", "support tickets", "unsupported citations", "duplicate charges"],
            surfacing_question="What guardrails would you watch while this ships?",
            weight=2.0,
        ),
        CoverageDimension(
            id="uncertainty",
            label="Uncertainty handling",
            description="Handles ambiguous, delayed, noisy, or low-confidence states honestly.",
            expected_approaches=["pending state", "unknown bucket", "confidence threshold", "review queue"],
            surfacing_question="What happens when the state is ambiguous or delayed?",
            weight=1.5,
        ),
    ]
    return AnswerCoverageMap(
        application_question="Transfer your approach to a neighboring product/system with delayed or noisy outcomes.",
        implementation_anchor=case["answer"],
        dimensions=dims,
        total_weight=sum(d.weight for d in dims),
        coverage_confidence=0.8,
    ).to_dict()


def validate_coverage(result: object, case: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    if not isinstance(result, dict):
        return 0, ["non_dict"], {}
    failures: list[str] = []
    expected = case["expected_coverage"]
    matches = 0
    for dim_id, expected_state in expected.items():
        actual = result.get(dim_id)
        if actual == expected_state:
            matches += 1
        elif expected_state == "voluntary" and actual in {"recovered_deep", "recovered_surface"}:
            matches += 1
        elif expected_state == "not_evaluated" and actual in {"not_evaluated", "missed"}:
            matches += 1
        else:
            failures.append(f"{dim_id}:{actual}!={expected_state}")
    bad_states = [v for v in result.values() if v not in {"voluntary", "recovered_deep", "recovered_surface", "missed", "incorrect", "not_evaluated"}]
    if bad_states:
        failures.append("bad_state_values")
    return max(0, round(100 * matches / max(len(expected), 1)) - 10 * len(bad_states)), failures, {"expected": expected, "actual": result}


async def timed(task: str, model: str, case: str, coro: Awaitable[Any], timeout: float = 60.0) -> dict[str, Any]:
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
            "error": f"{type(exc).__name__}: {str(exc)[:260]}",
        }


def attach_score(row: dict[str, Any], validator, case: dict[str, Any]) -> dict[str, Any]:
    if not row["ok"]:
        row["score"] = 0
        row["failures"] = [row["error"]]
        row["quality_details"] = {}
        return row
    score, failures, details = validator(row["result"], case)
    row["score"] = score
    row["failures"] = failures
    row["quality_details"] = details
    return row


async def run_model_case(model: str, case: dict[str, Any], repeat: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with small_model(model):
        concept = ConceptAgent()
        concept.llm = LLMRouter(tier="small", model_override=model, timeout_override=40.0)

        resume_agent = ResumeAgent()
        resume_agent.llm = LLMRouter(tier="small", model_override=model, timeout_override=75.0)

        followup = FollowUpAgent()
        followup.llm_fast = LLMRouter(tier="small", model_override=model, timeout_override=45.0)

        orch = Orchestrator()

        row = await timed("resume_parse_quality", model, case["name"], resume_agent.parse(case["resume"], case["target_role"], case["years_experience"]), 80.0)
        attach_score(row, validate_resume_parse, case)
        rows.append(row)
        parsed = row.get("result") if isinstance(row.get("result"), dict) else {}
        resume_context = _build_resume_context(parsed, case["resume"])

        row = await timed("concept_extract_quality", model, case["name"], concept.extract(case["answer"]), 45.0)
        attach_score(row, validate_concepts, case)
        rows.append(row)

        row = await timed("seed_question_quality", model, case["name"], followup.generate_seed_question(1, "curious_lead", resume_context), 50.0)
        attach_score(row, lambda result, c: validate_question(result, c, kind="seed_question"), case)
        rows.append(row)

        row = await timed(
            "clarification_quality",
            model,
            case["name"],
            followup.generate_clarification(
                "Walk me through the strongest resume claim there.",
                case["answer"],
                {"type": "ambiguous_but_promising", "weakness": "ownership or mechanism needs precision", "probe_direction": "ownership_probe"},
                "curious_lead",
                case["resume"],
                parsed_resume=parsed,
            ),
            50.0,
        )
        attach_score(row, lambda result, c: validate_question(result, c, kind="clarification"), case)
        rows.append(row)

        row = await timed(
            "adapt_followup_quality",
            model,
            case["name"],
            followup.adapt_followup(
                raw_followup="What was the exact mechanism that made this work?",
                question="Walk me through your most important project.",
                answer=case["answer"],
                persona="curious_lead",
                resume_context=resume_context,
            ),
            50.0,
        )
        attach_score(row, lambda result, c: validate_question(result, c, kind="adapt_followup"), case)
        rows.append(row)

        row = await timed(
            "speculative_followup_quality",
            model,
            case["name"],
            followup.generate_speculative(
                partial_text=case["partial"],
                new_entities=case["expected_concepts"][:3],
                last_question="Walk me through your most important project.",
                persona="curious_lead",
                sprint=1,
                resume_context=resume_context,
                admission=case["name"] == "terse_honest_gap",
                focus_context="Stay attached to the exact claim currently being discussed.",
            ),
            50.0,
        )
        attach_score(row, validate_speculative, case)
        rows.append(row)

        row = await timed(
            "implementation_anchor_quality",
            model,
            case["name"],
            orch._extract_implementation_anchor("quality-deepdive", case["answer"], {"target_role": case["target_role"]}),
            50.0,
        )
        attach_score(row, validate_anchor, case)
        rows.append(row)

        cmap = build_coverage_map(case)
        row = await timed(
            "application_coverage_quality",
            model,
            case["name"],
            orch._evaluate_application_coverage(cmap, case["application_answer"]),
            50.0,
        )
        attach_score(row, validate_coverage, case)
        rows.append(row)

    for row in rows:
        row["repeat"] = repeat
    return rows


def preview(value: object) -> object:
    if isinstance(value, str):
        return value[:700]
    if isinstance(value, list):
        return value[:12]
    if isinstance(value, dict):
        if "claims" in value or "projects" in value:
            return {
                "candidate_name": value.get("candidate_name"),
                "claims": value.get("claims", [])[:5],
                "projects": value.get("projects", [])[:4],
                "experiences": value.get("experiences", [])[:4],
                "skills": value.get("skills", [])[:10],
                "tools": value.get("tools", [])[:10],
                "experience_tier": value.get("experience_tier"),
            }
        return value
    return value


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    by_task_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_case_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
        by_task_model.setdefault((row["task"], row["model"]), []).append(row)
        by_case_model.setdefault((row["case"], row["model"]), []).append(row)

    def pack(items: list[dict[str, Any]]) -> dict[str, Any]:
        scores = [int(row.get("score", 0)) for row in items]
        latencies = [int(row.get("elapsed_ms", 0)) for row in items]
        return {
            "passes": sum(1 for row in items if row["ok"] and row.get("score", 0) >= 80),
            "calls": len(items),
            "avg_score": round(statistics.mean(scores), 1) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "avg_latency_ms": round(statistics.mean(latencies)) if latencies else 0,
            "failures": sorted({failure for row in items for failure in row.get("failures", []) if failure})[:8],
        }

    return {
        "by_model": {model: pack(items) for model, items in by_model.items()},
        "by_task_model": {f"{task}::{model}": pack(items) for (task, model), items in sorted(by_task_model.items())},
        "by_case_model": {f"{case}::{model}": pack(items) for (case, model), items in sorted(by_case_model.items())},
    }


def write_reports(rows: list[dict[str, Any]]) -> None:
    full_rows = []
    for row in rows:
        copied = dict(row)
        copied["result_preview"] = preview(copied.pop("result", None))
        full_rows.append(copied)

    summary = summarize(full_rows)
    payload = {"summary": summary, "rows": full_rows}
    out_json = Path("/tmp/antigravity_small_model_quality_deepdive.json")
    out_md = Path("/tmp/antigravity_small_model_quality_deepdive.md")
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    lines = ["# Small Model Quality Deep Dive", ""]
    lines.append("Quality gate: a call only passes at score >= 80. Scores judge groundedness, golden-claim recall, noise leakage, hallucination risk, and interview usefulness.")
    lines.extend(["", "## Model Summary", "| Model | Passes | Calls | Avg Score | Min Score | Avg Latency ms | Failures |", "|---|---:|---:|---:|---:|---:|---|"])
    for model, item in summary["by_model"].items():
        lines.append(
            f"| `{model}` | {item['passes']} | {item['calls']} | {item['avg_score']:.1f} | {item['min_score']} | {item['avg_latency_ms']} | {'; '.join(item['failures'][:5])} |"
        )

    lines.extend(["", "## Task Summary", "| Task | Model | Passes | Calls | Avg Score | Min Score | Avg Latency ms | Failures |", "|---|---|---:|---:|---:|---:|---:|---|"])
    for key, item in summary["by_task_model"].items():
        task, model = key.split("::", 1)
        lines.append(
            f"| `{task}` | `{model}` | {item['passes']} | {item['calls']} | {item['avg_score']:.1f} | {item['min_score']} | {item['avg_latency_ms']} | {'; '.join(item['failures'][:5])} |"
        )

    lines.extend(["", "## Case Summary", "| Case | Model | Passes | Calls | Avg Score | Failures |", "|---|---|---:|---:|---:|---|"])
    for key, item in summary["by_case_model"].items():
        case, model = key.split("::", 1)
        lines.append(
            f"| `{case}` | `{model}` | {item['passes']} | {item['calls']} | {item['avg_score']:.1f} | {'; '.join(item['failures'][:5])} |"
        )

    lines.extend(["", "## Representative Outputs"])
    interesting_tasks = {
        "resume_parse_quality",
        "seed_question_quality",
        "clarification_quality",
        "adapt_followup_quality",
        "implementation_anchor_quality",
        "application_coverage_quality",
    }
    for row in full_rows:
        if row["repeat"] != 1 or row["task"] not in interesting_tasks:
            continue
        lines.append(f"\n### {row['case']} / {row['task']} / `{row['model']}`")
        lines.append(f"- Score: {row['score']} | Latency: {row['elapsed_ms']} ms | Failures: {', '.join(row.get('failures') or ['none'])}")
        lines.append("```json")
        lines.append(json.dumps(row.get("result_preview"), indent=2, ensure_ascii=True)[:1800])
        lines.append("```")

    lines.extend(["", f"JSON: `{out_json}`"])
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[SmallModelQuality] Wrote {out_json}")
    print(f"[SmallModelQuality] Wrote {out_md}")


async def main() -> None:
    models = [
        item.strip()
        for item in os.environ.get("SMALL_QUALITY_MODELS", ",".join(MODELS)).split(",")
        if item.strip()
    ]
    selected_names = {
        item.strip()
        for item in os.environ.get("SMALL_QUALITY_CASES", "").split(",")
        if item.strip()
    }
    cases = [case for case in CASES if not selected_names or case["name"] in selected_names]
    repeats = int(os.environ.get("SMALL_QUALITY_REPEATS", "1") or "1")

    rows: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        for model in models:
            print(f"[SmallModelQuality] Running {model} repeat {repeat}/{repeats}", flush=True)
            for case in cases:
                rows.extend(await run_model_case(model, case, repeat))

    write_reports(rows)
    summary = summarize(rows)["by_model"]
    for model, item in summary.items():
        print(
            f"[SmallModelQuality] {model}: {item['passes']}/{item['calls']} "
            f"quality passes, avg score {item['avg_score']}, avg latency {item['avg_latency_ms']}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
