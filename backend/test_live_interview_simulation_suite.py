"""
Live interview simulation suite for the Antigravity orchestrator.

This is an integration/stress harness, not a unit test:
- prepares the real interview map
- starts the real orchestrator session
- feeds controlled candidate answers through handle_transcript()
- waits for background pipelines between turns
- finalizes the session and writes a compact report to /tmp

Run:
  python3 -m backend.test_live_interview_simulation_suite

Knobs:
  SIM_TURNS=15
  SIM_IDLE_TIMEOUT=55
  SIM_FIRST_ONLY=1
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import backend.main  # noqa: F401 - load app env without printing secrets
from backend.services.interview_map import _track_dimensions, _track_opener
from backend.services.orchestrator import Orchestrator
from backend.test_model_bakeoff import MESSY_AI_RESUME


APPARAO_RESUME = """
S V S APPARAO
+91 6301567773 | apparaosiddapureddy08@gmail.com | LinkedIn | GitHub

Education
Indian Institute of Information Technology, Sri City
Bachelor of Technology in Computer Science and Engineering
CGPA: 7.51/10
2021-2025

Experience
Product Analyst
Daily Mantra, AppsforBharat
Dec 2024 - Present
SQL, Analytics, Product Optimization
- Increased user retention from 25% to 42% through strategic A/B testing and deployment features (Video, Today, AI Guruji), directly driving higher user engagement and repeat sessions.
- Optimized trial-to-subscription conversion rate from 27% to 42% by reducing trial period from 7 days to 1 day, significantly reducing cancellation rates and accelerating user commitment while maintaining premium feature positioning.
- Increased core "Mantra Track End" event completion rate from 27.5% to 55.5% (102% improvement) by launching Videos and Today experiments, which optimized the user journey from task discovery to mantra listening, driving higher engagement.
- Architected and implemented core analytics event tracking for Daily Mantra zero-to-one product, defining critical product events (session flow, user engagement, feature adoption, conversion funnel) enabling real-time product insights and experimentation; this event infrastructure powered all retention and conversion optimization experiments.

Associate Business Analyst
AppsforBharat
May 2024 - Nov 2024
SQL, Analytics, Dashboards
- Automated AppsFlyer Marketing Dashboards for 3 product teams (Chadhava, AIG, Mantra), delivering day-wise campaign and ad-set level insights (CAC, CPI, CPM, spend), reducing manual reporting time from 20 minutes to under 5 minutes with on-demand refresh capability.
- Created an Executive Business Dashboard integrating impressions, transactions, and conversions, giving daily visibility to business teams and boosting decision speed by 30%.
- Automated a Reactivation Dashboard to identify inactive transacting users, enabling targeted reactivation campaigns.

Computer Vision Intern
IIT Hyderabad
Jun 2024 - Aug 2024
OpenCV, Python, Machine Learning
- Processed and analyzed 400+ frames of highway road systems using OpenCV, Python, and Tkinter to evaluate road boundary conditions.
- Benchmarked three heuristic methods: blob tracking, YOLO with SORT, and optical flow, comparing error rates, computational complexity, and suitability for large-scale deployment.

Publications
- "Comparative Evaluation of Vehicle Direction and Motion Detection Methods for Multi-layer Contiguous Virtual Layer (MCVL)" accepted for oral presentation at CoMSO 2024.

Technical Skills
Analytics & Data Analysis: SQL, Python (Pandas, NumPy), Google BigQuery, Data Cleaning & Transformation
Product Analytics & Experimentation: A/B Testing, Event Tracking, Funnel Analysis, Mixpanel, AppsFlyer
Dashboarding & Visualization: Power BI, Google Sheets, Excel
Databases: MySQL, MongoDB, Google BigQuery
Automation & Tools: Google Apps Script, Git/GitHub, Jupyter Notebook
"""

SYNTHETIC_EDGE_RESUME = """
NISHA RAO
Product Analytics Engineer | 2.5 years

Experience
Analytics Engineer, LoopCart
- Built checkout event instrumentation for cart, payment, retry, coupon, and refund flows using BigQuery, Segment, and dbt.
- Claimed a 19% payment success lift from retry logic but also notes the experiment overlapped with a wallet SDK migration.
- Created a feature flag dashboard for product managers and support teams.

Growth Analyst, LearnPulse
- Analyzed activation drop-offs across onboarding and course-completion funnels.
- Shipped a weekly retention dashboard, but only partially owned the metric definitions.

Projects
- Fraud refund monitor using SQL anomaly rules and manual reviewer queues.
- Cohort model comparing new-user and returning-user behavior across subscription plans.

Skills
SQL, BigQuery, dbt, Mixpanel, Looker, Python, experimentation, event taxonomy
"""


def _load_resume_fixture(name: str) -> dict[str, str]:
    path = Path(__file__).resolve().parent / "runtime" / "qa_maps" / name
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SimCase:
    key: str
    label: str
    target_role: str
    years_experience: str
    resume: str
    answer_style: str


def _cases() -> list[SimCase]:
    riya = _load_resume_fixture("merit_product_analyst_riya_resume.json")
    aarav = _load_resume_fixture("trap_product_analyst_aarav_resume.json")
    return [
        SimCase(
            key="apparao_first_product_analyst",
            label="Apparao product analyst strong baseline",
            target_role="Product Analyst",
            years_experience="1",
            resume=APPARAO_RESUME,
            answer_style="apparao_strong",
        ),
        SimCase(
            key="riya_merit_strong_product_analyst",
            label="Riya strong product analyst",
            target_role=str(riya.get("target_role", "Product Analyst")),
            years_experience=str(riya.get("years_experience", "3")),
            resume=str(riya["resume"]),
            answer_style="riya_strong",
        ),
        SimCase(
            key="aarav_trap_vague_overclaim",
            label="Aarav trap/vague overclaim",
            target_role=str(aarav.get("target_role", "Product Analyst")),
            years_experience=str(aarav.get("years_experience", "4")),
            resume=str(aarav["resume"]),
            answer_style="aarav_bad",
        ),
        SimCase(
            key="messy_ai_engineer_strong",
            label="Messy AI engineer strong technical",
            target_role="AI Agent Development Engineer",
            years_experience="1",
            resume=MESSY_AI_RESUME,
            answer_style="ai_engineer_strong",
        ),
        SimCase(
            key="edge_terse_honest_gap",
            label="Terse answers, honest gaps, contradiction",
            target_role="Product Analyst",
            years_experience="2",
            resume=SYNTHETIC_EDGE_RESUME,
            answer_style="terse_honest",
        ),
    ]


ANSWER_BANK: dict[str, list[str]] = {
    "apparao_strong": [
        "I am a product analyst at AppsforBharat working on Daily Mantra. My main work has been instrumentation, funnel analysis, and experiments around retention and subscription conversion.",
        "For Daily Mantra I owned the event taxonomy from zero to one. I defined session start, mantra discovery, track start, track end, video engagement, Today feature exposure, trial start, payment initiated, and subscription success so that every retention experiment had a clean denominator.",
        "The 25% to 42% retention lift came from a mix of Video, Today, and AI Guruji experiments. I would not claim one feature alone caused all of it; the strongest evidence was cohort-level retention by exposure group and week, plus a pre/post comparison after we stabilized tracking.",
        "The trial reduction from seven days to one day improved conversion from 27% to 42%, but I watched cancellation and refund rates closely. The hypothesis was that the seven-day trial delayed commitment and attracted low-intent users, while the one-day trial forced an earlier premium decision.",
        "For Mantra Track End, the denominator was users who discovered a mantra task and started a track. The completion event fired only when listening crossed the completion threshold, not just when the page opened. The biggest instrumentation risk was double counting when users replayed the same mantra.",
        "If I had to redo it, I would separate feature exposure from feature adoption more cleanly. Some users saw Video or Today but did not actually use them, so intent and treatment assignment could get mixed if we were not careful.",
        "On AppsFlyer dashboards, I automated campaign, ad-set, spend, CAC, CPI, and CPM cuts. The hard part was keeping product teams aligned on attribution windows because a day-wise dashboard can mislead when installs and purchases lag campaign spend.",
        "For a new subscription product, I would first build the event taxonomy, then run a power check for the expected lift, define guardrails like refund rate and seven-day retention, and only then ship the experiment.",
    ],
    "riya_strong": [
        "I have been working on product analytics for checkout and retention funnels. Most of my work sits around event taxonomy, causal measurement, and making product decisions less anecdotal.",
        "At BrightCart I rebuilt checkout instrumentation so payment-start, payment-fail, retry-success, and order-confirmed were separate events. That let us isolate wallet verification as the drop-off rather than blaming the whole checkout page.",
        "The strongest evidence was that the drop concentrated after payment-start but before order-confirmed, and it was disproportionately high for a specific wallet verification path. We also checked that traffic mix and coupon exposure did not explain it.",
        "For the retention work, I separated lesson-start, lesson-complete, streak notification exposure, and subscription renewal. The biggest issue was historical backfill because some pre-migration lesson events were safe for trends but not cohort-level decisions.",
        "I do not treat A/B test lift as automatically causal. I look at randomization, exposure logging, denominator choice, sample ratio mismatch, and guardrails like refunds or support tickets.",
        "One mistake I made early was over-trusting a dashboard metric before checking event firing rules. After that I started documenting metric contracts with the engineering team.",
        "If I had to transfer this to a marketplace, I would split buyer and seller funnels, keep denominator definitions stable, segment by new versus returning users, and monitor guardrails like cancellation and dispute rate.",
        "The decision impact was practical: we stopped prioritizing generic checkout redesign and focused engineering effort on verification retries and recovery states.",
    ],
    "aarav_bad": [
        "I mostly did all the analytics end to end. I worked on AI dashboards, RAG, OCR, SQL, growth, videos, and executive systems, so I have broad ownership.",
        "For Northstar Commerce, I just looked at the dashboard and we improved conversion. I do not remember the exact denominator, but it was pretty obvious from the trend that the change worked.",
        "The 35% churn reduction came from the model and some lifecycle campaigns. I think the recall was around 44%, but that does not matter much because the business impact was still strong.",
        "For the video learning app, I tracked completion and engagement. The main thing was that users watched more, and we used SQL and some AI insights to decide the roadmap.",
        "I built the OCR and RAG analytics in the sense that I worked with the team and reviewed outputs. I was not writing every pipeline, but I understood the product logic.",
        "I do not have the exact event names. We had many events in Mixpanel or something similar, and I usually pulled what was needed from the data team.",
        "If this moved to a marketplace, I would use AI to personalize everything and make dashboards for buyer and seller behavior. The main metric would be growth.",
        "Honestly I would need to check the details. I handled a lot of projects, so I do not remember every formula right now.",
    ],
    "ai_engineer_strong": [
        "Recently I have worked on an AIGC video pipeline and a TinyML audio classifier. The common thread is taking model capabilities and turning them into constrained working systems.",
        "For the AIGC pipeline I built an agent workflow around Google ADK and Veo 3. The key problem was preserving seed consistency while translating user-facing controls into conditioning instructions that the generation step could actually use.",
        "The semantic UI-to-latent mapping was not a direct slider-to-vector mapping. I treated controls like motion intensity or composition as discrete instruction bundles, then tested whether seed regeneration preserved the intended edit without drifting unrelated attributes.",
        "The hardest bug was state drift across sequential edits. If the second edit did not inherit the right seed and conditioning context, the output looked like a new generation rather than a controlled edit.",
        "For TinyML, I used MediaPipe Audio features and a TensorFlow Lite Micro INT8 model. The latency target forced me to look at feature extraction windowing, model size, and avoiding unnecessary copies in the inference loop.",
        "I would not claim I invented the DSP stack. My work was integration and profiling: measuring where the 10 ms budget was spent and adjusting preprocessing and model invocation so inference stayed stable.",
        "If I had to transfer this to a noisy wearable, I would first validate feature drift across microphones, then add confidence thresholds, on-device buffering, and a path for uncertain classifications rather than pretending every clip is classifiable.",
        "The benchmark work was more about rebuilding the evaluation harness and SQL schemas so multimodal evidence could be tied to the generated query rather than just scoring the query text.",
    ],
    "terse_honest": [
        "I worked on checkout analytics and retention dashboards.",
        "Mostly events.",
        "I am not fully sure. The wallet migration overlapped with the retry test, so attribution was messy.",
        "Payment success.",
        "I did not own all of dbt. I owned the event definitions and some queries, but another engineer productionized parts of it.",
        "I would probably track refunds and failed retries. I do not know the exact modeling piece.",
        "Actually the 19% lift may be overstated if the SDK migration changed failure logging.",
        "For a marketplace I would split buyer and seller funnels, but I would need more context before choosing the primary metric.",
    ],
}


QUESTION_AWARE_ANSWERS: dict[str, dict[str, str]] = {
    "apparao_strong": {
        "intro": "I am a product analyst at AppsforBharat working on Daily Mantra. My strongest work has been event instrumentation, funnel analysis, retention experiments, and subscription conversion decisions.",
        "retention": "The 25% to 42% retention movement came from a portfolio of Video, Today, and AI Guruji experiments. I would not attribute all of it to one launch; I checked cohort retention by exposure, activation path, and week so the lift did not just come from a traffic mix shift.",
        "conversion": "For the trial change, the denominator was users who started a trial, and the success metric was paid subscription conversion with cancellation and refund rate as guardrails. The one-day trial increased commitment earlier, but I treated it as valid only because refund/cancel signals did not spike enough to erase the gain.",
        "event_taxonomy": "I defined events around session start, task discovery, mantra start, mantra track end, video exposure, Today exposure, trial start, payment initiated, and subscription success. The main risk was double counting repeated mantra listens, so completion needed a threshold and a stable user-session key.",
        "application": "I would first define the event contract and separate exposure from adoption. Then I would run a staged test with guardrails: seven-day retention, refund rate, support complaints, and subscription renewal. If a feature improves early completion but hurts renewal, I would not call it a win.",
        "coverage": "The failure mode I would watch is denominator contamination. Users who see a feature are not always users who use it, and power users self-select into more devotional tasks, so I would separate assignment, exposure, and actual usage in the analysis.",
        "dashboard": "For AppsFlyer dashboards, I automated campaign, ad-set, spend, CAC, CPI, and CPM views for product teams. The tricky part was attribution windows: same-day spend and install views can mislead if subscription or transaction lag differs by channel.",
        "cv": "In the CV internship I compared blob tracking, YOLO with SORT, and optical flow across road-frame sequences. The evaluation was about error profile, compute cost, and deployment suitability, not just which model looked best on a few frames.",
        "honest_gap": "I do not have perfect causal proof for every percentage point. The honest version is that I had stronger evidence for directional impact than for exact decomposition of the full lift.",
        "synthesis": "The common thread is measurement discipline: define the event, protect the denominator, inspect guardrails, and only then connect product changes to business outcomes.",
    },
    "riya_strong": {
        "intro": "I work on product analytics across checkout and retention funnels, mostly event taxonomy, causal measurement, and translating product questions into clean metric definitions.",
        "retention": "I separate activation, habit formation, and renewal because retention can improve for very different reasons. I would check cohort quality, exposure logging, and whether the same users also improved downstream paid behavior.",
        "conversion": "For checkout conversion, I split payment-start, payment-fail, retry-success, and order-confirmed. That helped isolate wallet verification as the real drop-off instead of blaming the entire page.",
        "event_taxonomy": "My metric contracts include event name, owner, firing rule, denominator, exclusions, and known backfill limits. That prevents dashboard numbers from becoming folklore.",
        "application": "I would transfer the same method by defining buyer and seller funnel events separately, then tracking guardrails like cancellation, dispute rate, support tickets, and payment retry abuse.",
        "coverage": "I would not trust lift until I checked randomization, sample-ratio mismatch, exposure-vs-adoption, and whether traffic mix changed during the test.",
        "dashboard": "Dashboards are useful only when the metric contract is stable. I usually include freshness, owner, and caveats so product teams know when not to over-read a chart.",
        "honest_gap": "A mistake I made early was trusting a dashboard metric before checking event firing. After that I started documenting metric contracts with engineering.",
        "synthesis": "The decision impact was practical: the team stopped prioritizing generic redesign and focused on retry and recovery states.",
    },
    "aarav_bad": {
        "intro": "I worked across analytics, AI dashboards, OCR, RAG, SQL, growth, and executive reporting, so I had broad ownership in many areas.",
        "retention": "We looked at retention in the dashboard and it improved. I do not remember the denominator, but the trend was clear enough.",
        "conversion": "Conversion improved because of the model and campaigns. I do not know the exact guardrails right now.",
        "event_taxonomy": "There were many events in Mixpanel or similar tools. I usually pulled what was needed from the data team.",
        "application": "I would use AI personalization and make dashboards for every funnel. The main metric would be growth.",
        "coverage": "I would need to check details. The project had a lot of moving parts and I do not remember every formula.",
        "dashboard": "The dashboard showed product and business metrics. I helped the team understand it, but I was not writing all the pipelines.",
        "honest_gap": "I do not have the exact details with me.",
        "synthesis": "Overall I contributed across many projects, but I cannot recall every implementation detail.",
    },
    "ai_engineer_strong": {
        "intro": "Recently I worked on an AIGC video pipeline and a TinyML audio classifier. The common thread is turning model capabilities into constrained working systems.",
        "application": "For a multi-character version, I would separate identity state per character, keep seed/context lineage per entity, and test whether edits preserve each identity when characters overlap in a frame.",
        "application_grounding": "Mostly operating workflow and state lineage, not model internals. I can explain review labels, prompt bundles, regression checks, and failure handling, but I did not own model weights.",
        "coverage": "The key risk is state drift across sequential edits. If the second edit does not inherit the right seed and conditioning context, the output becomes a new generation rather than a controlled edit.",
        "dashboard": "For TinyML, I tracked feature extraction time, model invocation time, memory footprint, and confidence behavior under noise instead of only reporting accuracy.",
        "honest_gap": "I would not claim I invented the DSP stack. My work was integration, profiling, and making the inference path meet the latency budget.",
        "synthesis": "My strongest signal is systems translation: constraints, budgets, state, and failure modes around AI model capabilities.",
    },
    "terse_honest": {
        "intro": "I worked on checkout analytics and retention dashboards.",
        "retention": "Mostly events and cohorts.",
        "conversion": "I am not fully sure because the wallet migration overlapped with the retry test.",
        "event_taxonomy": "I owned some event definitions and queries, but another engineer productionized parts of it.",
        "application": "I would track refunds and failed retries, but I do not know the exact modeling piece.",
        "coverage": "The 19% lift may be overstated if the SDK migration changed failure logging.",
        "dashboard": "For dashboards, I can define the metrics, but I would need engineering help on production data quality.",
        "honest_gap": "I do not know that part deeply enough to answer confidently.",
        "synthesis": "The honest summary is that I can reason about metrics, but some ownership claims need narrowing.",
    },
}


def _answer_bucket(question: str) -> str:
    q = question.lower()
    if any(k in q for k in ("introduce", "intro", "yourself", "who you are", "been up to")):
        return "intro"
    if any(k in q for k in ("before i apply", "were you mainly", "specialized internals", "operating workflow", "decision logic")):
        return "application_grounding"
    if any(k in q for k in ("trial", "subscription", "conversion", "cancel", "refund", "premium")):
        return "conversion"
    if any(k in q for k in ("retention", "repeat", "cohort", "daily mantra", "video", "today", "guruji")):
        return "retention"
    if any(k in q for k in ("imagine", "new product", "scenario", "transfer", "pm comes", "launching", "extend", "new constraint", "how would you adjust")):
        return "application"
    if any(k in q for k in ("event", "taxonomy", "tracking", "denominator", "metric", "instrument", "completion", "track end")):
        return "event_taxonomy"
    if any(k in q for k in ("guardrail", "failure", "break", "risk", "valid", "causal", "exposure", "adoption", "dimension")):
        return "coverage"
    if any(k in q for k in ("dashboard", "appsflyer", "campaign", "ad-set", "cac", "cpi", "cpm", "executive")):
        return "dashboard"
    if any(k in q for k in ("opencv", "yolo", "sort", "optical", "computer vision", "road", "frame", "vehicle")):
        return "cv"
    if any(k in q for k in ("don't know", "not sure", "honest", "gap", "didn't own", "ownership")):
        return "honest_gap"
    if any(k in q for k in ("wrap", "closing", "final", "synthesis", "overall", "anything else")):
        return "synthesis"
    return ""


def _answer_for(case: SimCase, turn_index: int, question: str) -> str:
    bucket = _answer_bucket(question)
    aware = QUESTION_AWARE_ANSWERS.get(case.answer_style, {})
    if bucket and aware.get(bucket):
        return aware[bucket]
    answers = ANSWER_BANK[case.answer_style]
    if turn_index < len(answers):
        return answers[turn_index]
    return aware.get("synthesis") or answers[-1]


def _entities_from_answer(answer: str) -> list[str]:
    known = [
        "SQL", "BigQuery", "Mixpanel", "AppsFlyer", "A/B", "YOLO", "SORT",
        "OpenCV", "TensorFlow Lite", "MediaPipe", "Google ADK", "Veo 3",
        "dbt", "Segment", "retention", "conversion", "refund", "wallet",
    ]
    lower = answer.lower()
    return [item for item in known if item.lower() in lower][:6]


async def _wait_for_orchestrator_idle(orch: Orchestrator, session_id: str, timeout: float) -> None:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        in_flight = any(key[0] == session_id for key in orch._pipeline_inflight)
        turn_running = bool(orch._turn_pipeline_running.get(session_id))
        finalizing = session_id in orch._finalization_inflight
        if not in_flight and not turn_running and not finalizing:
            return
        await asyncio.sleep(1.0)


def _route_repetition(turns: list[dict[str, Any]]) -> dict[str, Any]:
    non_substantive_routes = {
        "",
        "application_grounding",
        "complete",
        "echo_guard",
        "graceful_exit",
        "synthesis_close",
        "sprint_opener",
        "warm_open",
        "unknown",
    }
    focus_labels = [str(t.get("answered_focus_label") or t.get("state_focus_label") or t.get("focus_label") or "") for t in turns]
    non_empty = [
        f for f, t in zip(focus_labels, turns)
        if f and str(t.get("route_kind") or "").strip() not in non_substantive_routes
    ]
    surface_keys = []
    for t in turns:
        if str(t.get("route_kind") or "").strip() in non_substantive_routes:
            continue
        focus = str(t.get("answered_focus_key") or t.get("state_focus_key") or "").strip()
        if not focus:
            continue
        coverage_dim = str(t.get("coverage_dimension_id") or "").strip()
        sub_focus = str(t.get("answered_sub_focus_key") or t.get("state_sub_focus_key") or "").strip()
        if coverage_dim:
            surface_keys.append(f"{focus}::coverage::{coverage_dim}")
        elif sub_focus:
            surface_keys.append(f"{focus}::{sub_focus}")
        else:
            surface_keys.append(focus)
    max_streak = 0
    current = ""
    streak = 0
    for label in non_empty:
        if label == current:
            streak += 1
        else:
            current = label
            streak = 1
        max_streak = max(max_streak, streak)
    max_surface_streak = 0
    current_surface = ""
    surface_streak = 0
    for surface in surface_keys:
        if surface == current_surface:
            surface_streak += 1
        else:
            current_surface = surface
            surface_streak = 1
        max_surface_streak = max(max_surface_streak, surface_streak)
    return {
        "focus_sequence": non_empty,
        "surface_sequence": surface_keys,
        "max_same_focus_streak": max_streak,
        "max_same_surface_streak": max_surface_streak,
        "route_sequence": [t.get("route_kind") for t in turns],
    }


def _quality_gate(case_result: dict[str, Any], *, required_turns: int = 15) -> dict[str, Any]:
    failures: list[str] = []
    turns = case_result.get("turns") or []
    routes = [str(t.get("route_kind") or "") for t in turns]
    focus_keys = [
        str(t.get("answered_focus_key") or t.get("state_focus_key") or "")
        for t in turns
        if str(t.get("answered_focus_key") or t.get("state_focus_key") or "") not in ("", "general", "general_background", "general background")
    ]
    final_eval = case_result.get("final_evaluation") or {}
    assessment = case_result.get("assessment_coverage") or {}
    coverage_map = case_result.get("coverage_map") or {}
    coverage_dims = [
        d for d in (coverage_map.get("dimensions") or [])
        if isinstance(d, dict)
    ] if isinstance(coverage_map, dict) else []
    evaluated_dims = [
        d for d in coverage_dims
        if str(d.get("coverage_state") or "") in {"voluntary", "recovered_deep", "recovered_surface", "missed", "incorrect"}
    ]
    early_close = bool((case_result.get("interview_agenda") or {}).get("close_reason"))

    if not case_result.get("ok"):
        failures.append(f"case_failed:{case_result.get('error_type')}")
    if not early_close and int(case_result.get("question_count") or 0) < required_turns:
        failures.append("question_count_below_15")
    if int(case_result.get("history_len") or 0) != int(case_result.get("question_count") or 0):
        failures.append("history_len_does_not_match_question_count")
    if case_result.get("finalization_status") != "complete" or not case_result.get("report_ready"):
        failures.append("report_not_ready_after_completion")
    if not case_result.get("application_question_served"):
        failures.append("application_transfer_not_served")
    if not coverage_dims:
        failures.append("coverage_map_missing_dimensions")
    if not evaluated_dims:
        failures.append("coverage_dimensions_not_evaluated")
    if len(set(focus_keys)) < 2 and int(assessment.get("distinct_surfaces") or 0) < 2:
        failures.append("fewer_than_two_substantive_surfaces_tested")
    repetition = case_result.get("route_repetition") or {}
    effective_streak = int(repetition.get("max_same_focus_streak") or 0)
    if int(assessment.get("distinct_surfaces") or 0) >= 3:
        effective_streak = min(effective_streak, int(assessment.get("max_same_surface_streak") or effective_streak))
    if effective_streak > 4:
        failures.append("max_same_focus_streak_exceeded")
    if any(route == "sprint_opener" for route in routes[5:]):
        failures.append("late_generic_sprint_opener")
    if any(
        route in {"trajectory_map_surface", "trajectory_map_mechanism", "trajectory_map_boundary", "coverage_surface", "coverage_depth_probe", "application_grounding", "application_transfer", "second_anchor"}
        and not str(t.get("answered_focus_key") or t.get("state_focus_key") or "").strip()
        for route, t in zip(routes, turns)
    ):
        failures.append("map_backed_route_missing_focus")
    if final_eval.get("hire_recommendation") == "NO HIRE" and (
        (
            int(assessment.get("distinct_focuses") or 0) < 2
            and int(assessment.get("distinct_surfaces") or 0) < 2
        )
        or (
            float(assessment.get("dominant_focus_ratio") or 0) > 0.70
            and int(assessment.get("distinct_surfaces") or 0) < 3
        )
    ):
        failures.append("narrow_interview_returned_no_hire")

    return {
        "passed": not failures,
        "failures": failures,
        "required_turns": required_turns,
        "coverage_evaluated_dimensions": len(evaluated_dims),
        "distinct_focuses": len(set(focus_keys)),
    }


async def run_case(case: SimCase, *, max_turns: int) -> dict[str, Any]:
    orch = Orchestrator()
    idle_timeout = float(os.environ.get("SIM_IDLE_TIMEOUT", "55"))
    started = time.perf_counter()
    turns: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "key": case.key,
        "label": case.label,
        "target_role": case.target_role,
        "years_experience": case.years_experience,
        "ok": False,
    }
    try:
        session_id = await orch.prepare_session_map(
            resume=case.resume,
            github_links=[],
            target_role=case.target_role,
            years_experience=case.years_experience,
        )
        await orch.start_prepared_session(session_id)
        state = await orch.session_manager.get_state(session_id)
        result["session_id"] = session_id
        result["map_latency_note"] = "included in startup_elapsed_ms"
        result["map_validation"] = state.get("interview_map_validation", {})
        result["map_quality_review"] = (state.get("interview_trajectory_map") or {}).get("quality_review", {})
        result["map_focus_areas"] = [
            {
                "label": area.get("label"),
                "focus_key": area.get("focus_key"),
                "map_schema_version": area.get("map_schema_version"),
                "primary_question_contract": area.get("primary_question_contract"),
                "source": area.get("track_source"),
                "dimensions": len(_track_dimensions(area)),
                "question_ladder_count": len(area.get("question_ladder") or []),
                "opener": _track_opener(area)[:220],
            }
            for area in ((state.get("interview_trajectory_map") or {}).get("focus_areas") or [])
        ]

        current_question = state.get("last_question", "")
        result["opening_question"] = current_question

        for turn_index in range(max_turns):
            answer = _answer_for(case, turn_index, current_question)
            turn_id = f"{case.key}-turn-{turn_index + 1}"
            state_before = await orch.session_manager.get_state(session_id)
            answered_packet = state_before.get("active_question_packet") or {}
            turn_started = time.perf_counter()
            response = await orch.handle_transcript(
                session_id,
                answer,
                entities=_entities_from_answer(answer),
                turn_id=turn_id,
            )
            state_after = await orch.session_manager.get_state(session_id)
            active_packet = state_after.get("active_question_packet") or {}
            agenda = state_after.get("interview_agenda") or {}
            assessment_coverage = state_after.get("assessment_coverage") or {}
            turns.append({
                "turn": turn_index + 1,
                "question": current_question,
                "answer": answer,
                "answer_bucket": _answer_bucket(current_question),
                "ai_response": response.get("response"),
                "route_kind": response.get("route_kind"),
                "sprint": response.get("sprint"),
                "agenda_phase": agenda.get("phase"),
                "agenda_reason": agenda.get("last_route_reason"),
                "question_count": response.get("question_count"),
                "pivoting": response.get("pivoting"),
                "weakness": response.get("weakness"),
                "discrepancy": response.get("discrepancy"),
                "answered_focus_key": answered_packet.get("focus_key"),
                "answered_focus_label": answered_packet.get("focus_label"),
                "answered_sub_focus_key": answered_packet.get("sub_focus_key"),
                "answered_sub_focus_label": answered_packet.get("sub_focus_label"),
                "coverage_dimension_id": answered_packet.get("coverage_dimension_id"),
                "coverage_dimension_label": answered_packet.get("coverage_dimension_label"),
                "state_focus_key": active_packet.get("focus_key"),
                "state_focus_label": active_packet.get("focus_label"),
                "state_sub_focus_key": active_packet.get("sub_focus_key"),
                "state_sub_focus_label": active_packet.get("sub_focus_label"),
                "assessment_coverage": assessment_coverage,
                "latency_ms": round((time.perf_counter() - turn_started) * 1000),
            })
            current_question = str(response.get("response") or "")
            await _wait_for_orchestrator_idle(orch, session_id, idle_timeout)
            if response.get("complete"):
                break

        await orch.end_session(session_id)
        await _wait_for_orchestrator_idle(orch, session_id, idle_timeout)
        final_state = await orch.session_manager.get_state(session_id)
        result.update({
            "ok": True,
            "startup_elapsed_ms": round((time.perf_counter() - started) * 1000),
            "turns": turns,
            "history_len": len(final_state.get("history", []) or []),
            "question_count": final_state.get("question_count"),
            "weaknesses": final_state.get("weaknesses", []),
            "coverage_map": final_state.get("coverage_map"),
            "application_question_served": bool(final_state.get("application_question_served")),
            "application_transfer_arc": final_state.get("application_transfer_arc", {}),
            "application_transfer_error": final_state.get("application_transfer_error", ""),
            "finalization_status": final_state.get("finalization_status"),
            "report_ready": final_state.get("report_ready"),
            "final_evaluation": final_state.get("final_evaluation", {}),
            "assessment_coverage": final_state.get("assessment_coverage", {}),
            "interview_agenda": final_state.get("interview_agenda", {}),
            "route_repetition": _route_repetition(turns),
        })
        result["quality_gate"] = _quality_gate(result, required_turns=max_turns if max_turns >= 15 else 15)
    except Exception as exc:
        result.update({
            "ok": False,
            "startup_elapsed_ms": round((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:1800],
            "turns": turns,
        })
        result["quality_gate"] = {"passed": False, "failures": [f"{type(exc).__name__}:{str(exc)[:180]}"]}
    return result


def _quality_notes(case_result: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if not case_result.get("ok"):
        return [f"FAILED: {case_result.get('error_type')} - {case_result.get('error')}"]
    turns = case_result.get("turns") or []
    routes = [str(t.get("route_kind") or "") for t in turns]
    questions = [str(t.get("ai_response") or "") for t in turns]
    if any(route == "application_transfer" for route in routes):
        notes.append("Application transfer was served.")
    else:
        notes.append("Application transfer was not served within simulated turns.")
    max_streak = int((case_result.get("route_repetition") or {}).get("max_same_focus_streak", 0) or 0)
    notes.append(f"Max same-focus streak: {max_streak}.")
    genericish = [
        q for q in questions
        if "tell me more" in q.lower() or "walk me through" in q.lower()
    ]
    if genericish:
        notes.append(f"Generic/narrative phrasing observed in {len(genericish)} AI responses.")
    else:
        notes.append("No obvious generic 'tell me more/walk me through' response pattern.")
    final_eval = case_result.get("final_evaluation") or {}
    if final_eval:
        notes.append(
            f"Final verdict: {final_eval.get('hire_recommendation')} "
            f"score={final_eval.get('overall_score')} confidence={final_eval.get('confidence_score')}."
        )
    gate = case_result.get("quality_gate") or {}
    notes.append(f"15-turn quality gate: {gate.get('passed')} failures={gate.get('failures', [])}.")
    return notes


def _markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Antigravity Live Interview Simulation Suite", ""]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("| Case | OK | Gate | Questions | App transfer | Final status | Score | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---|---:|---|")
    for r in results:
        ev = r.get("final_evaluation") or {}
        lines.append(
            f"| {r.get('label')} | {r.get('ok')} | {(r.get('quality_gate') or {}).get('passed')} | "
            f"{r.get('question_count', len(r.get('turns', []) or []))} | "
            f"{r.get('application_question_served', False)} | {r.get('finalization_status', r.get('error_type', ''))} | "
            f"{ev.get('overall_score', '')} | {ev.get('hire_recommendation', '')} |"
        )
    for r in results:
        lines.extend(["", f"## {r.get('label')}", ""])
        lines.append(f"- Session: `{r.get('session_id', '')}`")
        lines.append(f"- OK: `{r.get('ok')}`")
        lines.append(f"- Startup elapsed: `{r.get('startup_elapsed_ms')} ms`")
        if not r.get("ok"):
            lines.append(f"- Error: `{r.get('error_type')}: {r.get('error')}`")
        lines.append("- Quality notes:")
        for note in _quality_notes(r):
            lines.append(f"  - {note}")
        lines.append("- Map focus areas:")
        for area in r.get("map_focus_areas", []) or []:
            lines.append(
                f"  - {area.get('label')} ({area.get('source')}, dims={area.get('dimensions')}): "
                f"{area.get('opener')}"
            )
        lines.append("")
        lines.append("| Turn | Phase | Route | Answered focus | Next focus | Bucket | Question | Candidate answer | AI next question |")
        lines.append("|---:|---|---|---|---|---|---|---|---|")
        for t in r.get("turns", []) or []:
            def clean(value: Any) -> str:
                return str(value or "").replace("\n", " ").replace("|", "/")[:240]
            lines.append(
                f"| {t.get('turn')} | {clean(t.get('agenda_phase'))} | {clean(t.get('route_kind'))} | "
                f"{clean(t.get('answered_focus_label'))} | {clean(t.get('state_focus_label'))} | {clean(t.get('answer_bucket'))} | "
                f"{clean(t.get('question'))} | {clean(t.get('answer'))} | {clean(t.get('ai_response'))} |"
            )
    return "\n".join(lines) + "\n"


async def main() -> None:
    max_turns = int(os.environ.get("SIM_TURNS", "15") or "15")
    cases = _cases()
    case_filter = {
        key.strip()
        for key in os.environ.get("SIM_CASE_KEYS", "").split(",")
        if key.strip()
    }
    if case_filter:
        cases = [case for case in cases if case.key in case_filter]
        if not cases:
            raise RuntimeError(f"SIM_CASE_KEYS did not match any cases: {sorted(case_filter)}")
    first = cases[0]
    print(f"[SimSuite] Running first gate case: {first.label}", flush=True)
    first_result = await run_case(first, max_turns=max_turns)
    results = [first_result]
    first_gate_passed = bool((first_result.get("quality_gate") or {}).get("passed"))
    if not first_result.get("ok") or not first_gate_passed or os.environ.get("SIM_FIRST_ONLY"):
        print("[SimSuite] First case did not pass or SIM_FIRST_ONLY set; not running remaining cases.", flush=True)
    else:
        print("[SimSuite] First case passed; running remaining 4 concurrently.", flush=True)
        rest = await asyncio.gather(*[run_case(case, max_turns=max_turns) for case in cases[1:]])
        results.extend(rest)

    out_json = Path("/tmp/antigravity_live_interview_sim_suite.json")
    out_md = Path("/tmp/antigravity_live_interview_sim_suite.md")
    out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    out_md.write_text(_markdown(results), encoding="utf-8")
    print(f"[SimSuite] Wrote {out_json}")
    print(f"[SimSuite] Wrote {out_md}")
    print(_markdown(results)[:12000])


if __name__ == "__main__":
    asyncio.run(main())
