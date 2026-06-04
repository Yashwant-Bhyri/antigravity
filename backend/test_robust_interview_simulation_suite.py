"""
Robust six-resume interview simulation suite.

This harness is intentionally integration-heavy:
- map-only policy simulation for all six stress resumes
- optional full 15-turn interview gate / full-suite simulation
- question-aware candidate answers instead of turn-index-only scripts

Run examples:
  SIM_MODE=map_only python3 -m backend.test_robust_interview_simulation_suite
  SIM_MODE=full_gate python3 -m backend.test_robust_interview_simulation_suite
  SIM_MODE=full_all python3 -m backend.test_robust_interview_simulation_suite

Useful knobs:
  SIM_TURNS=15
  SIM_IDLE_TIMEOUT=55
  SIM_CASE_KEYS=best_product,strong_ai
  SIM_FORCE_ALL=1
  SIM_ANSWER_MODE=llm|bank
  SIM_ANSWER_MODEL=google/gemini-3.1-flash-lite
  SIM_OUTPUT_PREFIX=/tmp/antigravity_robust_interview
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import backend.main  # noqa: F401 - loads runtime env without printing secrets
from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter, MODEL_TIERS
from backend.services import interview_map as interview_map_module
from backend.services.orchestrator import Orchestrator


BEST_PRODUCT_RESUME = """
S V S APPARAO
Product Analyst | 1 year | SQL, BigQuery, Mixpanel, AppsFlyer, A/B Testing

Experience
Product Analyst, Daily Mantra - AppsforBharat
- Increased user retention from 25% to 42% through A/B testing and product launches: Video, Today, and AI Guruji.
- Optimized trial-to-subscription conversion from 27% to 42% by reducing the free trial from 7 days to 1 day, while monitoring cancellation and refund guardrails.
- Increased Mantra Track End completion from 27.5% to 55.5% by launching Videos and Today experiments and improving the path from task discovery to listening completion.
- Architected the zero-to-one analytics event taxonomy for Daily Mantra: session flow, task discovery, track start/end, feature exposure, trial start, payment initiated, subscription success.
- Used BigQuery, SQL, Mixpanel, AppsFlyer, Google Sheets, and dashboard automation to support retention and conversion decisions.

Associate Business Analyst, AppsforBharat
- Automated AppsFlyer marketing dashboards across campaign, ad-set, spend, CAC, CPI, CPM, installs, and transactions.
- Created executive dashboards connecting impressions, transactions, and conversion for daily business decisions.

Computer Vision Intern, IIT Hyderabad
- Processed 400+ frames of road-system video using OpenCV and Python.
- Compared blob tracking, YOLO with SORT, and optical flow for vehicle motion direction and deployment suitability.
"""


STRONG_AI_ENGINEER_RESUME = """
K LATHA
AI Agent Development Engineer | 1.5 years | Python, TypeScript, Google ADK, Veo 3, TensorFlow Lite, MediaPipe

Experience
AI Systems Intern, PixelForge Labs
- Built an agentic AIGC video workflow using Google ADK and Veo 3 where users control character motion, camera framing, and scene continuity across sequential edits.
- Designed a prompt-control layer that translated UI controls into generation instructions while preserving seed lineage and scene state across edits.
- Added regression checks for state drift: identity preservation, unintended background changes, and multi-character consistency after repeated edits.
- Implemented a React + FastAPI review console for prompt versions, generated outputs, seed metadata, and human review labels.

TinyML Research Assistant, EdgeSound
- Integrated MediaPipe Audio features with a TensorFlow Lite Micro INT8 classifier for on-device sound-event detection.
- Profiled feature extraction, model invocation, memory footprint, and confidence behavior under noisy microphones.
- Reduced inference-loop overhead by removing redundant copies and bounding the audio windowing pipeline.

Benchmark Project
- Built SQL schemas and evaluation scripts tying multimodal evidence to generated query outputs, so model scores could be traced back to source evidence.
"""


AVERAGE_PARTIAL_RESUME = """
MEERA SHAH
Product Data Analyst | 2 years | SQL, dbt, Amplitude, Looker, Python

Experience
Product Data Analyst, SkillNest
- Built activation and lesson-completion dashboards for a learning app using Amplitude, Looker, SQL, and dbt.
- Helped define onboarding events: signup complete, first lesson start, first lesson complete, streak notification exposure, and subscription renewal.
- Supported an experiment that improved first-week lesson completion from 31% to 39%, but owned analysis more than event production.
- Created weekly retention reporting used by product managers to prioritize onboarding and reminder experiments.

Data Analyst, ShopLane
- Analyzed checkout drop-offs and coupon usage across web and mobile funnels.
- Built a refund-monitoring dashboard but relied on engineering for production data-quality fixes.

Projects
- Python notebook for cohort retention by acquisition channel.
- SQL data-quality checks for duplicate lesson-completion events.
"""


HONEST_GAP_RESUME = """
NISHA RAO
Product Analytics Engineer | 2.5 years | BigQuery, Segment, dbt, Mixpanel, Looker

Experience
Analytics Engineer, LoopCart
- Built checkout event instrumentation for cart, payment, retry, coupon, refund, and order-confirmed flows using Segment, BigQuery, and dbt.
- Claimed a 19% payment success lift from retry logic, but the experiment overlapped with a wallet SDK migration and some failure logging changed during rollout.
- Created a feature-flag dashboard for product managers and support teams.
- Owned event definitions and analysis queries; engineering owned some production dbt deployment and warehouse reliability work.

Growth Analyst, LearnPulse
- Analyzed activation drop-offs across onboarding and course-completion funnels.
- Shipped a weekly retention dashboard, but only partially owned the metric definitions.

Projects
- Fraud refund monitor using SQL anomaly rules and manual reviewer queues.
- Cohort model comparing new-user and returning-user behavior across subscription plans.
"""


TRAP_OVERCLAIM_RESUME = """
AARAV MALHOTRA
Senior Product Analyst | 4 years | AI, RAG, OCR, SQL, Growth, Dashboards

Experience
Product Analytics Lead, Northstar Commerce
- Reduced churn by 35% using an AI lifecycle model and personalized campaigns across buyer and seller cohorts.
- Built an executive AI dashboard combining RAG insights, OCR invoice extraction, growth analytics, and SQL reporting.
- Improved checkout conversion by 28% through funnel analysis, pricing experiments, and model-driven recommendations.
- Led cross-functional data strategy for retention, marketplace liquidity, seller quality, AI automation, and support operations.

Product Analyst, LearnTube
- Increased video completion and learning retention through engagement dashboards and AI-driven content recommendations.
- Claimed ownership across instrumentation, dashboarding, experimentation, OCR pipelines, and RAG analytics.

Skills
SQL, Python, RAG, OCR, LLMs, Mixpanel, Looker, Growth, AI Dashboards, Experimentation
"""


MESSY_NOISY_RESUME = """
RIYA K / data + product / maybe analytics engineer
email: riya-k-demo@example.com | links: github / notion / figma

EDUCATION
B.Tech IT 2022-2026, CGPA around 8

EXPERIENCE-ish
Growth/Analytics intern - BazaarNow? 2025
* helped with seller onboarding dashboard; events were not clean at first
* "improved activation 18%" - actually a weekly cohort dashboard showed better first listing completion after new checklist + support calls
* SQL + sheets + metabase + some python; pulled data from seller table, listing table, support tickets
* made PM view for: signup, KYC submit, first listing, listing approved, first order; some duplicate rows fixed later

Project - campus fintech app
* checkout funnel analysis, payment failures, refund tagging, razorpay logs; no production ownership
* suggested retry copy change; small sample, not statistically clean

Older stuff:
Marketing ops volunteer - campaign report, UTM cleanup, not much engineering
Computer vision mini project - pothole image classifier, copied starter notebook, not relevant to product analytics role

Skills mixed: SQL, Python pandas, Metabase, Excel, Mixpanel basics, event naming, cohort analysis, dashboards, messy data cleanup.
"""


MARKETPLACE_GROWTH_RESUME = """
TANVI MENON
Product Analytics Engineer | 2.8 years | SQL, BigQuery, dbt, Mixpanel, Looker, Python

Experience
Analytics Engineer, QuickKart Marketplace
- Built the seller onboarding event taxonomy: signup, KYC submit, first listing, listing approved, first order, support contact, refund, and buyer conversion.
- Reported seller activation improving from 22% to 38% after checklist, support-call, and KYC UX changes, but the rollout combined multiple interventions.
- Created BigQuery and dbt models joining seller events, support tickets, KYC status, listing approvals, first-order lag, refunds, and support SLA.
- Owned metric definitions, dashboard analysis, and stakeholder interpretation; platform engineering owned the event SDK and some dbt deployment/reliability work.
- Built a marketplace health dashboard covering seller activation, buyer conversion, first-order lag, refunds, support SLA, and cohort-level operational bottlenecks.
- Claimed "reduced first-order lag by 31%," but the rollout overlapped with seller-support staffing changes and routing-process changes.

Projects
- Side project: OCR invoice parser using Tesseract and Python; not production deployed and not part of QuickKart analytics.
- College CV project: pothole classifier from a starter notebook; useful learning project but not relevant to product analytics role.
"""


@dataclass(frozen=True)
class RobustCase:
    key: str
    label: str
    purpose: str
    target_role: str
    years_experience: str
    resume: str
    answer_profile: str
    expected_anchors: tuple[str, ...]
    expected_failure_probes: tuple[str, ...] = field(default_factory=tuple)
    expected_second_anchor_terms: tuple[str, ...] = field(default_factory=tuple)


CASES: tuple[RobustCase, ...] = (
    RobustCase(
        key="best_product",
        label="Best-case product analyst",
        purpose="How good can the system get on a strong Apparao-style product analytics candidate?",
        target_role="Product Analyst",
        years_experience="1",
        resume=BEST_PRODUCT_RESUME,
        answer_profile="best_product",
        expected_anchors=("retention", "conversion", "event taxonomy", "dashboard", "computer vision"),
        expected_failure_probes=("denominator", "causal", "guardrail", "feature exposure"),
    ),
    RobustCase(
        key="strong_ai",
        label="Strong technical AI engineer",
        purpose="Test non-product domain transfer, technical map anchors, and second-anchor pivoting.",
        target_role="AI Agent Development Engineer",
        years_experience="1.5",
        resume=STRONG_AI_ENGINEER_RESUME,
        answer_profile="strong_ai",
        expected_anchors=("AIGC video", "Google ADK", "Veo 3", "TinyML", "MediaPipe"),
        expected_failure_probes=("state drift", "seed", "latency", "confidence"),
    ),
    RobustCase(
        key="average_partial",
        label="Average partial product/data analyst",
        purpose="Measure normal-case quality with mixed specificity and partial ownership.",
        target_role="Product Data Analyst",
        years_experience="2",
        resume=AVERAGE_PARTIAL_RESUME,
        answer_profile="average_partial",
        expected_anchors=("lesson completion", "onboarding", "retention", "checkout", "refund"),
        expected_failure_probes=("ownership", "event production", "data quality", "metric definition"),
    ),
    RobustCase(
        key="honest_gap",
        label="Honest gap and corrected overclaim",
        purpose="Ensure self-correction and uncertainty narrow claims instead of triggering tunnel attacks.",
        target_role="Product Analytics Engineer",
        years_experience="2.5",
        resume=HONEST_GAP_RESUME,
        answer_profile="honest_gap",
        expected_anchors=("checkout", "payment success", "wallet SDK", "feature flag", "refund"),
        expected_failure_probes=("overlap", "attribution", "ownership", "logging"),
    ),
    RobustCase(
        key="trap_overclaim",
        label="Trap inflated-claim candidate",
        purpose="Worst-case robustness for vague buzzword claims, weak ownership, and verdict coverage gates.",
        target_role="Senior Product Analyst",
        years_experience="4",
        resume=TRAP_OVERCLAIM_RESUME,
        answer_profile="trap_overclaim",
        expected_anchors=("churn", "AI dashboard", "RAG", "OCR", "checkout conversion"),
        expected_failure_probes=("denominator", "ownership", "recall", "guardrail", "implementation"),
    ),
    RobustCase(
        key="messy_resume",
        label="Messy resume and noisy extraction",
        purpose="Validate launch readiness, role-relevant focus selection, and fair questioning on noisy formatting and mixed claims.",
        target_role="Product Data Analyst",
        years_experience="1",
        resume=MESSY_NOISY_RESUME,
        answer_profile="messy_resume",
        expected_anchors=("seller onboarding", "activation", "dashboard", "checkout", "refund"),
        expected_failure_probes=("duplicate rows", "sample size", "ownership", "role relevance", "metric definition"),
    ),
    RobustCase(
        key="marketplace_growth",
        label="Marketplace growth analytics engineer",
        purpose=(
            "Non-Apparao silverline case for role-relevant focus ranking, V2 ladder rhythm, "
            "application-transfer grounding, earned depth, reserve routing, honest correction, "
            "and Report V2 fairness."
        ),
        target_role="Product Analytics Engineer",
        years_experience="2.8",
        resume=MARKETPLACE_GROWTH_RESUME,
        answer_profile="marketplace_growth",
        expected_anchors=(
            "seller onboarding taxonomy",
            "activation denominator",
            "concurrent rollout attribution",
            "marketplace health dashboard",
            "first-order lag correction",
        ),
        expected_failure_probes=(
            "off-role OCR/CV demotion",
            "no hidden SDK/dbt ownership assumptions",
            "application-transfer grounding",
            "earned coverage depth probe",
            "reserve-map question if routing exhausts early",
        ),
        expected_second_anchor_terms=(
            "marketplace health",
            "dashboard",
            "buyer conversion",
            "refund",
            "support SLA",
            "operational bottleneck",
        ),
    ),
)


def _apply_simulation_model_policy() -> dict[str, str]:
    """
    Pin known-good models for this harness.

    The developer/local environment may point generic tiers at experimental or
    unavailable models. This suite is meant to test the policy below, so it uses
    SIM_* overrides and otherwise forces the known policy defaults in-process.
    """
    policy = {
        "small": os.environ.get("SIM_SMALL_MODEL", "google/gemini-3.1-flash-lite"),
        "medium": os.environ.get("SIM_MEDIUM_MODEL", "anthropic/claude-sonnet-4.6"),
        "large": os.environ.get("SIM_LARGE_MODEL", "anthropic/claude-sonnet-4.6"),
        "map_generator": os.environ.get("SIM_MAP_GENERATOR_MODEL", "google/gemini-3.5-flash"),
        "map_rescue": os.environ.get("SIM_MAP_RESCUE_MODEL", "anthropic/claude-sonnet-4.6"),
        "map_critic": os.environ.get("SIM_MAP_CRITIC_MODEL", "anthropic/claude-sonnet-4.6"),
        "map_audit": os.environ.get("SIM_MAP_AUDIT_MODEL", "deepseek/deepseek-v4-flash"),
    }
    MODEL_TIERS["small"] = policy["small"]
    MODEL_TIERS["medium"] = policy["medium"]
    MODEL_TIERS["large"] = policy["large"]
    interview_map_module._MAP_GENERATOR_MODEL = policy["map_generator"]
    interview_map_module._MAP_RESCUE_MODEL = policy["map_rescue"]
    interview_map_module._MAP_CRITIC_MODEL = policy["map_critic"]
    interview_map_module._MAP_AUDIT_MODEL = policy["map_audit"]
    return policy


ANSWER_PROFILES: dict[str, dict[str, str]] = {
    "best_product": {
        "intro": "I am a product analyst at AppsforBharat. My strongest work has been Daily Mantra event instrumentation, retention experiments, subscription conversion, and dashboard automation.",
        "primary_claim": "The strongest claim is the Daily Mantra event taxonomy. I defined session start, task discovery, mantra start, track end, feature exposure, trial start, payment initiated, and subscription success so retention and conversion experiments had stable denominators.",
        "concurrent_changes": "In that window Video and Today experiments were also live, so I would not attribute the full 27-to-42 jump to trial length alone. I split users by paywall exposure, feature exposure, acquisition cohort, and app version, then checked whether conversion moved inside the trial-start cohort after controlling for those launches.",
        "retention_experiment": "For retention, the cleanest experiment was Today entry-point exposure. I defined assignment at user level, exposure when the Today surface was actually seen, adoption as track_start from that surface, and success as D7 return plus Track End completion. The key guardrail was whether completion increased without hurting trial conversion.",
        "trial_causal": "To isolate trial length, I would compare only users who reached the paywall and started a trial, segment by acquisition source and app version, and inspect whether paid subscription rose while refund, cancellation, and D7 retention stayed within guardrails. If feature exposure explained the lift, the effect should disappear inside matched paywall cohorts.",
        "guardrail_thresholds": "I watched refund rate, same-cycle cancellation, support complaints, and D7 retention against the pre-change baseline. The practical rollback line was not one magic number; it was conversion lift disappearing or either refund/cancellation moving materially above the baseline confidence band for the paywall cohort.",
        "track_completion_denominator": "For the 55.5% Track End metric, the denominator was users or sessions that fired a valid track_start after task discovery, not all app opens. I excluded accidental starts below a minimum listening threshold and checked unique-user and session-level versions separately because repeat listeners can inflate completion.",
        "metric_denominator": "For retention, I separated assigned users, exposed users, and actual feature adopters. For conversion, the denominator was trial starters and the success event was paid subscription, with cancellation and refund rate as guardrails.",
        "event_taxonomy": "The biggest instrumentation risk was double counting repeated listens or feature exposure. I would store user, session, mantra id, feature surface, timestamp, and completion threshold so Track End meant real listening completion.",
        "application_transfer": "For social sharing, I would define share_start, share_success, external_open, recipient_install, recipient_track_start, and recipient_subscription. I would separate creator engagement from recipient acquisition, use holdouts where possible, and protect existing retention, refund, and cancellation guardrails.",
        "live_feature_transfer": "For the live audio feature, I would define live_session_join, meaningful_attendance, host_drop, user_drop, reconnect, completion, post-session track_start, and D7 return. I would not use attendance alone as retention; I would connect live participation to repeat listening and subscription outcomes.",
        "completion_definition": "For completion, I would not count a user who joins for ten seconds the same as one who meaningfully attends. I would set a threshold like 70-80% attendance or reaching the guided close, then report sensitivity at multiple thresholds so leadership sees whether the result depends on one arbitrary cutoff.",
        "session_end_diagnostics": "To understand why a user ended a session, I would inspect last event before exit, elapsed attendance, network reconnects, app backgrounding, host-side drop, content segment, chat or interaction state, and whether the user returned to on-demand listening afterward.",
        "live_retention_diagnostics": "If completion is healthy but retention is flat, I would split users by first-time versus returning, session topic, host, attendance depth, post-session action, and next-day return. That tells me whether live sessions are enjoyable once but not creating a habit loop.",
        "attribution_overlap": "I would use a share-link identifier and preserve campaign source, but I would still treat paid and organic overlap carefully. If a recipient had a paid click and a shared clip in the same window, I would report assisted conversion separately instead of forcing one last-touch winner.",
        "off_app_tracking": "Once the user moves to Instagram or WhatsApp, we lose viewer-level engagement unless the shared link brings them back. So success should not be external views alone; I would use return clicks, new installs from share links, recipient track_start, and downstream subscription as progressively stronger signals.",
        "telemetry_prioritization": "With a three-day deadline, must-have telemetry is share_created, share_channel, link_opened, install_or_return, track_started, and subscription outcome. Nice-to-have would be richer recipient journey details, but I would not block launch on those if the core attribution chain is intact.",
        "viral_success_metric": "The metric I would choose is recipient activation per sharing user: unique recipients who start a track divided by unique sharers. Button clicks alone are vanity; recipient track_start and later subscription show whether sharing creates real devotional usage.",
        "share_churn_lifecycle": "I would tag share-acquired users as a cohort and compare their D1, D7, track completion, and trial conversion against non-share cohorts with similar acquisition quality. If they spike on day one but churn before trial conversion, the feature is acquisition noise rather than durable value.",
        "coverage_surface": "I would check whether the metric moved because of actual behavior or because the denominator changed. Exposure and adoption must remain separate.",
        "coverage_depth": "The hardest boundary is attribution. Power users self-select into more devotional tasks, so I would compare cohorts by baseline engagement and not just post-launch usage.",
        "dashboard_second_anchor": "For AppsFlyer dashboards I automated campaign, ad-set, spend, CAC, CPI, CPM, installs, and transactions. The tricky part was attribution windows because subscription lag can make same-day CAC misleading.",
        "technical_second_anchor": "In the CV internship I compared blob tracking, YOLO with SORT, and optical flow across 400 road frames. The evaluation was about error type, compute cost, and deployment suitability.",
        "honest_gap": "I do not have perfect causal proof for every percentage point. The honest version is that I had stronger evidence for directional impact than exact decomposition of the full lift.",
        "contradiction": "If that sounds contradictory, I would narrow the claim: I owned the measurement setup and analysis, not every product change that contributed to the full retention lift.",
        "synthesis_close": "The common thread is measurement discipline: define the event, protect the denominator, inspect guardrails, and only then connect product changes to business outcomes. If we had more time, I would also show how the AppsFlyer dashboard reconciled spend lag with subscription lag.",
    },
    "strong_ai": {
        "intro": "I work on AI systems where the model is only one part of the product. My strongest work is controlled AIGC video editing and TinyML audio inference.",
        "primary_claim": "For the AIGC workflow, I built the control layer around Google ADK and Veo 3 so UI choices became structured generation instructions while keeping seed lineage and scene state across edits.",
        "metric_denominator": "The equivalent of a denominator was the evaluation set of edit attempts: identity preservation, scene consistency, unintended background change, and whether only the requested attribute changed.",
        "event_taxonomy": "I tracked prompt version, seed, previous scene state, edit command, generated output id, and review labels. Without that lineage, every failure looked like a subjective model-quality issue.",
        "application_transfer": "For a multi-character workflow, I would track state per character, preserve identity embeddings or references separately, and test sequential edits where one character changes while the other should remain stable.",
        "coverage_surface": "The first thing I would test is state drift after repeated edits. A system can look good on one generation but fail once users make a chain of edits.",
        "coverage_depth": "The boundary is conflicting constraints: if the user changes camera angle and character pose together, I need to know which instruction wins and whether the seed lineage still preserves identity.",
        "technical_second_anchor": "For TinyML, I profiled feature extraction, model invocation, memory use, and confidence under noisy microphones. The work was integration and profiling, not inventing DSP from scratch.",
        "dashboard_second_anchor": "For the benchmark project, I built SQL schemas tying multimodal evidence to generated query outputs so model scores could be traced to source evidence.",
        "honest_gap": "I would not claim I invented the DSP stack or Veo internals. My contribution was systems translation, profiling, and reliability around model behavior.",
        "contradiction": "If I phrased it as mapping UI sliders directly to latent vectors, I would correct that: it was more like structured instruction bundles and seed/context preservation.",
        "synthesis_close": "My strongest signal is turning AI model capability into reliable user-facing workflows with state, budgets, and failure checks.",
    },
    "average_partial": {
        "intro": "I am a product data analyst. I have worked on learning-app activation, lesson completion, retention dashboards, and some checkout analysis.",
        "primary_claim": "The strongest project was lesson-completion reporting. I helped define signup complete, first lesson start, first lesson complete, streak notification exposure, and subscription renewal.",
        "metric_denominator": "For first-week lesson completion, the denominator was new users who completed signup. I did not own every event firing rule, so I checked with engineering when event definitions changed.",
        "event_taxonomy": "I owned analysis queries and metric documentation more than production instrumentation. I could specify event needs, but engineering productionized several dbt and tracking changes.",
        "application_transfer": "For a marketplace, I would split buyer and seller activation, define first meaningful action for each side, and add guardrails like cancellation, refunds, or seller response time.",
        "coverage_surface": "I would check whether the improvement is from better onboarding or simply a higher-intent acquisition channel.",
        "coverage_depth": "The weak spot is data quality. Duplicate lesson-complete events or late-arriving mobile events could make completion look better than it really is.",
        "dashboard_second_anchor": "The refund dashboard was useful, but I relied on engineering for production data-quality fixes. My ownership was analysis, monitoring, and explaining patterns.",
        "technical_second_anchor": "I wrote SQL checks for duplicate lesson-completion events and Python notebooks for cohort retention by acquisition channel.",
        "honest_gap": "I am not fully confident on the event production details because I did not own the tracking SDK implementation.",
        "contradiction": "I would narrow the ownership claim: I owned metric definitions and analysis, not every production data pipeline.",
        "synthesis_close": "I am strongest when translating product questions into metrics and analysis; I am weaker on production data engineering ownership.",
    },
    "honest_gap": {
        "intro": "I worked on checkout analytics and event instrumentation. One claim on my resume needs careful wording because the wallet SDK migration overlapped with the retry experiment.",
        "primary_claim": "I owned checkout event definitions for cart, payment, retry, coupon, refund, and order-confirmed flows. I also wrote analysis queries around payment success.",
        "metric_denominator": "The 19% payment success lift may be overstated if the SDK migration changed failure logging. The denominator should be payment attempts, but logging changed during rollout.",
        "event_taxonomy": "I owned event definitions and some BigQuery/dbt work, but another engineer productionized parts of the warehouse pipeline.",
        "application_transfer": "In a new checkout flow, I would freeze event definitions before rollout, separate SDK migration from retry logic, and monitor payment success, refund rate, and duplicate-charge risk.",
        "coverage_surface": "I would first check whether failure events were logged consistently before and after migration. Otherwise success rate could improve just because failures disappeared.",
        "coverage_depth": "The hard boundary is counterfactual attribution. If two changes ship together, I would avoid claiming causal lift unless I can segment or find a holdout.",
        "dashboard_second_anchor": "The feature-flag dashboard helped product and support see rollout status, error rate, and user impact by cohort.",
        "technical_second_anchor": "The fraud refund monitor used SQL anomaly rules and reviewer queues. It was useful but fairly simple.",
        "honest_gap": "I do not know enough to defend the full 19% as causal. I can defend the instrumentation and analysis, but not the entire business lift.",
        "contradiction": "The corrected claim is that retry logic and SDK migration together coincided with better success. My owned work was measuring and surfacing that effect.",
        "synthesis_close": "The right verdict on me should reward honesty and instrumentation reasoning, but mark causal ownership as a risk.",
    },
    "trap_overclaim": {
        "intro": "I worked across AI dashboards, RAG, OCR, SQL, churn, checkout conversion, and growth analytics. I had broad ownership across many areas.",
        "primary_claim": "The churn reduction came from AI models and campaigns. I do not remember the exact denominator, but the dashboard trend was clear.",
        "metric_denominator": "I do not have the exact denominator or guardrails right now. The team looked at churn and it went down after the model was used.",
        "event_taxonomy": "There were many events in Mixpanel or Looker. I usually pulled what I needed from the data team rather than defining every event myself.",
        "application_transfer": "I would use AI personalization and dashboards for every user segment. The main metric would be growth and we would optimize the model over time.",
        "coverage_surface": "I would need to check the details. The project had a lot of moving parts and I do not remember every formula.",
        "coverage_depth": "I cannot explain the OCR or RAG pipeline in depth. I reviewed outputs and worked with the team, but I was not writing those systems.",
        "dashboard_second_anchor": "The executive dashboard showed business metrics. I helped interpret it, but the data platform team built much of it.",
        "technical_second_anchor": "For OCR and RAG, I mostly coordinated and reviewed product usefulness. I was not the primary implementation owner.",
        "honest_gap": "I do not have the exact details with me.",
        "contradiction": "If the resume says I built all of it end to end, that is too broad. I contributed to analysis and coordination more than implementation.",
        "synthesis_close": "Overall I had broad exposure, but I cannot defend the exact methods behind several claims.",
    },
    "messy_resume": {
        "intro": "My background is product data work with messy marketplace and checkout data. The strongest piece is seller onboarding analytics, not the older CV mini project.",
        "primary_claim": "For seller onboarding, I helped map signup, KYC submit, first listing, listing approval, and first order. The 18% activation improvement came from a weekly cohort dashboard after checklist and support-call changes, so I would not claim a clean experiment.",
        "metric_denominator": "The denominator was sellers who completed signup in that week, but I would separate signup-complete, KYC-submitted, and eligible-to-list sellers because duplicate seller rows and pending KYC could distort the activation rate.",
        "event_taxonomy": "The event taxonomy was basic but important: signup_complete, kyc_submit, listing_created, listing_approved, support_contact, first_order. I flagged duplicates and mismatched seller ids, but engineering helped fix upstream data issues.",
        "application_transfer": "For a new buyer onboarding flow, I would first define eligible users, activation event, duplicate handling, and guardrails like refund or support-contact rate, or something else tied to real buyer quality.",
        "coverage_surface": "I would check whether the metric improved because more sellers completed KYC or because the denominator removed sellers who were blocked from listing.",
        "coverage_depth": "The hardest boundary is noisy operational data. If support calls and checklist rollout happened together, I would describe it as a combined intervention unless I can segment by exposure.",
        "dashboard_second_anchor": "The Metabase dashboard was useful for PMs because it showed seller funnel steps and ticket volume in one place, but it was not a production-grade data platform.",
        "technical_second_anchor": "For checkout analysis, I looked at Razorpay failure logs, refund tags, and retry-copy timing. I did not own production payment code.",
        "honest_gap": "I would correct the resume wording: I helped measure and explain an activation improvement, but I did not prove the full 18% causal lift alone.",
        "contradiction": "If the resume makes the CV project look important, I would de-emphasize it. It was a starter notebook project and not relevant to this product analytics role.",
        "synthesis_close": "My strongest signal is practical product analytics with imperfect data: define the funnel, clean the denominator, explain uncertainty, and avoid overclaiming causality.",
    },
    "marketplace_growth": {
        "intro": "I am a product analytics engineer focused on marketplace activation and operational funnels. My strongest work is QuickKart seller onboarding: event taxonomy, activation measurement, and a marketplace health dashboard.",
        "primary_claim": "The core work was seller onboarding analytics. I defined the funnel from signup to KYC submit, first listing, listing approval, first order, support contact, refund, and buyer conversion, then connected those events to dashboard views for product and operations teams.",
        "metric_denominator": "For seller activation, the denominator was eligible sellers after signup. I separated sellers blocked at KYC, sellers who could list, and sellers who actually created a first listing, because mixing those groups would make the 22% to 38% improvement look cleaner than it was.",
        "concurrent_changes": "The improvement did not come from one clean experiment. Checklist changes, support calls, and KYC UX changes overlapped, so I would describe the 22% to 38% movement as a combined rollout effect unless we can segment exposure or find a holdout.",
        "event_taxonomy": "The taxonomy had signup_complete, kyc_submit, kyc_approved, listing_created, listing_approved, first_order, support_contact, refund_created, and buyer_conversion. The main data-quality risk was duplicate seller IDs and late KYC status updates.",
        "application_grounding": "My ownership was metric definitions, analysis workflow, dashboard interpretation, and some BigQuery/dbt modeling. I did not own the event SDK internals or the platform reliability layer, so I would stay at the analytics and workflow layer unless you want me to discuss handoff constraints.",
        "application_transfer": "If I applied this to buyer onboarding or subscription activation, I would define eligible users, first meaningful action, activation quality, and guardrails like refund, support contact, repeat use, or something else that proves the activation is durable.",
        "coverage_surface": "I would check whether the metric improved because seller behavior changed or because the eligible denominator changed. KYC-blocked sellers, support-call exposure, and listing approval delays have to be separated before claiming a product lift.",
        "coverage_depth": "I can partially answer this: I would segment sellers by support-call exposure and KYC path, but I would still need a cleaner holdout or pre/post design to separate support staffing from the checklist change.",
        "dashboard_second_anchor": "The marketplace health dashboard combined seller activation, buyer conversion, first-order lag, refunds, support SLA, and operational bottlenecks. Its value was reconciliation: product could see activation, while ops could see whether KYC or support queues caused lag.",
        "technical_second_anchor": "The OCR invoice parser was a side project with Tesseract and Python. It was not production deployed, so I would not treat it as a strong role-relevant anchor for this product analytics interview.",
        "honest_gap": "I would narrow the first-order lag claim. I can defend the measurement and dashboard work, but I cannot claim the full 31% reduction came only from my analytics because support staffing and routing changed too.",
        "contradiction": "If the resume sounds like I personally reduced lag by 31%, I would correct it: I measured and surfaced the reduction, helped teams diagnose bottlenecks, and tracked rollout effects, but I did not solely cause the entire lift.",
        "synthesis_close": "My strongest signal is marketplace analytics judgment: define the funnel, separate blocked users from eligible users, watch guardrails, and communicate uncertainty. My main limitation is that I should not overclaim causal ownership when operations changes overlap.",
    },
}


BUCKET_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("first_order_lag", ("first-order lag", "first order lag", "31%", "support staffing", "routing-process", "routing process")),
    ("seller_activation", ("seller activation", "seller onboarding", "first listing", "listing approved", "kyc", "eligible sellers")),
    ("support_confound", ("support call", "support-call", "support sla", "staffing", "operational bottleneck", "support queues")),
    ("marketplace_health_dashboard", ("marketplace health", "buyer conversion", "refunds", "support sla", "first-order lag", "first order lag")),
    ("offrole_ocr_side_project", ("ocr", "tesseract", "invoice parser", "pothole", "cv project", "computer vision")),
    ("live_retention_diagnostics", ("live session attendees", "aren't coming back", "retention is flat", "completion rate looks healthy")),
    ("live_feature_transfer", ("live audio", "guided meditation", "real instructor", "live session")),
    ("application_grounding", ("before i apply", "when you describe", "were you mainly", "specialized internals", "operating workflow", "decision logic")),
    ("application_transfer", ("imagine", "pm comes", "new live", "new social", "new scenario", "tomorrow")),
    ("concurrent_changes", ("what else shipped", "same window", "during that same window", "concurrent product", "other launches")),
    ("trial_causal", ("how do you know", "caused it", "rule out", "separated its effect", "product launches happening", "rather than the trial length", "trial length itself", "not something else", "7 days was the problem")),
    ("session_end_diagnostics", ("end their session", "ended their session", "particular moment", "why a user decided to end")),
    ("completion_definition", ("threshold for \"completion\"", "threshold for completion", "count as completion", "completion status", "should count")),
    ("retention_experiment", ("retention jump", "specific experiment", "personally designed")),
    ("guardrail_thresholds", ("threshold", "target", "actually watching", "did it move", "cancellation and refund")),
    ("track_completion_denominator", ("55.5", "completion rate", "track start/end", "track start", "track_end", "denominator for the 55")),
    ("attribution_overlap", ("overlap", "isolating the true impact", "paid", "organic", "last-touch", "attribution challenge")),
    ("off_app_tracking", ("instagram", "whatsapp", "external", "lost signals", "viewer engagement")),
    ("telemetry_prioritization", ("three-day deadline", "must-have", "can wait", "later sprint", "time pressure")),
    ("viral_success_metric", ("vanity", "button click", "specific metric", "truly succeeding", "driving value")),
    ("share_churn_lifecycle", ("share-driven users", "lifecycle", "churn", "before the trial ends")),
    ("metric_denominator", ("denominator", "baseline", "metric definition", "counted", "time window", "guardrail", "causal", "attribution")),
    ("event_taxonomy", ("event", "taxonomy", "tracking", "instrument", "schema", "firing", "track end", "payment initiated")),
    ("coverage_depth", ("break", "failure", "edge", "boundary", "wrong", "risk", "what would make", "counterfactual")),
    ("coverage_surface", ("exposure", "adoption", "valid", "verify", "check", "measure", "confidence")),
    ("dashboard_second_anchor", ("dashboard", "appsflyer", "campaign", "ad-set", "cac", "cpi", "cpm", "looker", "executive", "marketplace health")),
    ("technical_second_anchor", ("opencv", "yolo", "sort", "optical", "tinyml", "mediapipe", "tensorflow", "veo", "adk", "seed", "state drift", "rag", "ocr")),
    ("honest_gap", ("not sure", "do not know", "don't know", "honest", "gap", "didn't own", "ownership", "personally own")),
    ("contradiction", ("contradiction", "conflict", "inconsistent", "earlier", "resume says", "reconcile")),
    ("synthesis_close", ("wrap", "close", "final", "synthesis", "overall", "anything else", "last question")),
    ("primary_claim", ("walk me through", "tell me about", "strongest", "project", "claim", "built", "owned")),
    ("intro", ("introduce", "yourself", "background", "who you are")),
)

NON_SUBSTANTIVE_SIM_ROUTES = {
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


GENERIC_PATTERNS = (
    "tell me more",
    "can you elaborate",
    "walk me through that",
    "explain your work",
    "what did you do",
)


def _select_cases() -> list[RobustCase]:
    selected = {item.strip() for item in os.environ.get("SIM_CASE_KEYS", "").split(",") if item.strip()}
    cases = [case for case in CASES if not selected or case.key in selected]
    if not cases:
        raise RuntimeError(f"SIM_CASE_KEYS did not match any robust cases: {sorted(selected)}")
    return cases


def _answer_bucket(question: str) -> str:
    q = re.sub(r"\s+", " ", (question or "").lower())
    for bucket, terms in BUCKET_KEYWORDS:
        if any(term in q for term in terms):
            return bucket
    return "primary_claim"


def _answer_for(case: RobustCase, turn_index: int, question: str) -> tuple[str, str]:
    bucket = _answer_bucket(question)
    profile = ANSWER_PROFILES[case.answer_profile]
    if bucket in profile:
        return bucket, profile[bucket]
    if case.answer_profile == "marketplace_growth":
        if bucket in {"seller_activation", "support_confound"}:
            return bucket, profile["concurrent_changes"]
        if bucket == "first_order_lag":
            return bucket, profile["honest_gap"]
        if bucket == "marketplace_health_dashboard":
            return bucket, profile["dashboard_second_anchor"]
        if bucket == "offrole_ocr_side_project":
            return bucket, profile["technical_second_anchor"]
    if bucket == "application_grounding":
        return bucket, (
            "Mostly the decision logic and operating workflow, not specialized model or low-level internals. "
            "I can explain the metrics, state, review flow, tradeoffs, and failure checks, or something else around that layer."
        )
    return bucket, profile.get("primary_claim", profile["intro"])


def _answerer_behavior(case: RobustCase) -> str:
    return {
        "best_product": (
            "Strong product analyst. Answer directly with concrete metrics, denominators, "
            "guardrails, causal caution, and honest boundaries. Do not dodge."
        ),
        "strong_ai": (
            "Strong technical AI engineer. Give systems-level answers with state, latency, "
            "evaluation, implementation constraints, and honest ownership boundaries."
        ),
        "average_partial": (
            "Average partial candidate. Some answers are specific, but ownership is partial. "
            "Be honest where engineering or another team owned implementation."
        ),
        "honest_gap": (
            "Honest candidate correcting an overclaim. Narrow claims explicitly, explain what "
            "was owned, and avoid pretending causal proof exists when it does not."
        ),
        "trap_overclaim": (
            "Inflated-claim candidate. Sound plausible but often vague, missing denominators, "
            "unclear on ownership, and willing to narrow only when pressed."
        ),
        "messy_resume": (
            "Decent but imperfect noisy-resume candidate. Be specific about marketplace analytics, "
            "admit unclear causality and partial ownership, and de-emphasize off-role CV work."
        ),
        "marketplace_growth": (
            "Strong but calibrated marketplace product analytics engineer. Be concrete on funnels, "
            "denominators, dbt/BigQuery workflow, guardrails, and dashboard use. Correct overclaims "
            "around first-order lag and never claim event SDK or platform reliability ownership."
        ),
    }.get(case.answer_profile, "Answer as the candidate using only the case facts.")


def _answerer_case_packet(case: RobustCase) -> dict[str, Any]:
    profile = ANSWER_PROFILES[case.answer_profile]
    return {
        "case_key": case.key,
        "target_role": case.target_role,
        "years_experience": case.years_experience,
        "behavior": _answerer_behavior(case),
        "expected_anchors": list(case.expected_anchors),
        "expected_failure_probes": list(case.expected_failure_probes),
        "resume": case.resume.strip()[:5000],
        "answer_bank": profile,
    }


def _recent_turn_context(turns: list[dict[str, Any]], limit: int = 3) -> list[dict[str, str]]:
    recent: list[dict[str, str]] = []
    for turn in turns[-limit:]:
        recent.append({
            "question": str(turn.get("question") or "")[:600],
            "answer": str(turn.get("answer") or "")[:600],
            "route": str(turn.get("route_kind") or ""),
            "focus": str(turn.get("answered_focus_label") or turn.get("state_focus_label") or ""),
        })
    return recent


def _clean_answer_text(answer: object) -> str:
    text = re.sub(r"\s+", " ", str(answer or "").strip())
    text = re.sub(r"^```(?:json)?\s*", "", text).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    return text[:1400]


def _valid_simulated_answer(answer: str) -> bool:
    if len(answer.split()) < 12:
        return False
    lowered = answer.lower()
    if any(bad in lowered for bad in ("as an ai", "i cannot answer as", "not enough information in the prompt")):
        return False
    if answer.count("{") > 1 or answer.count("[") > 1:
        return False
    return True


async def _llm_answer_for(
    case: RobustCase,
    turn_index: int,
    question: str,
    turns: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any]]:
    """
    Cheap candidate simulator.

    It is intentionally constrained by the synthetic case packet. The point is
    not to make the candidate look good; it is to make the answer match the
    actual generated question while preserving the case's strong/weak/honest
    behavior profile.
    """
    fallback_bucket, fallback_answer = _answer_for(case, turn_index, question)
    mode = os.environ.get("SIM_ANSWER_MODE", "llm").strip().lower()
    if mode in {"bank", "static", "deterministic"}:
        return fallback_bucket, fallback_answer, {"mode": "bank", "fallback": False}

    answer_model = os.environ.get("SIM_ANSWER_MODEL", "google/gemini-3.1-flash-lite").strip()
    llm = LLMRouter("small", model_override=answer_model, timeout_override=float(os.environ.get("SIM_ANSWER_TIMEOUT", "25")))
    system = "\n".join([
        "You simulate one interview candidate answer for an automated interview QA harness.",
        "Stay strictly inside the provided resume/case facts and answer-bank facts.",
        "Answer the CURRENT QUESTION directly, in first person, as the candidate.",
        "Preserve the behavior profile: strong cases should be specific; trap cases can be vague; honest-gap cases should correct claims.",
        "Do not invent companies, metrics, tools, or achievements not present in the case packet.",
        "If the question asks for something unknown, answer with a narrow honest limitation and the closest relevant evidence.",
        "Avoid meta commentary. Do not mention the harness, model, prompt, rubric, or that you are simulating.",
        "Return JSON object only with keys: bucket, answer, edge_signal, rationale.",
    ])
    user_packet = {
        "turn": turn_index + 1,
        "current_question": question,
        "suggested_bucket": fallback_bucket,
        "suggested_answer_if_relevant": fallback_answer,
        "recent_turns_to_avoid_repetition": _recent_turn_context(turns),
        "case": _answerer_case_packet(case),
        "constraints": {
            "answer_words": "45-95 words unless the question is a closing question",
            "must_directly_address_question": True,
            "allowed_edge_signal": [
                "strong_direct",
                "partial_specific",
                "honest_gap",
                "evasive_vague",
                "contradiction_narrowed",
                "closing",
            ],
        },
    }
    started = time.perf_counter()
    try:
        raw = await llm.call(
            system=system,
            user=json.dumps(user_packet, ensure_ascii=True),
            max_tokens=int(os.environ.get("SIM_ANSWER_MAX_TOKENS", "650")),
            response_format=JSON_OBJECT_FORMAT,
            audit_call_name="RobustSimulation.answerer",
            audit_metadata={"case_key": case.key, "turn": turn_index + 1, "suggested_bucket": fallback_bucket},
        )
        if not isinstance(raw, dict):
            raise RuntimeError(f"answerer returned {type(raw).__name__}")
        answer = _clean_answer_text(raw.get("answer"))
        bucket = _clean_answer_text(raw.get("bucket")) or fallback_bucket
        if not _valid_simulated_answer(answer):
            raise RuntimeError("answerer returned invalid/too-thin answer")
        return bucket[:80], answer, {
            "mode": "llm",
            "model": answer_model,
            "fallback": False,
            "edge_signal": _clean_answer_text(raw.get("edge_signal"))[:80],
            "rationale": _clean_answer_text(raw.get("rationale"))[:220],
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return fallback_bucket, fallback_answer, {
            "mode": "llm",
            "model": answer_model,
            "fallback": True,
            "error_type": type(exc).__name__,
            "error": str(exc)[:220],
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }


def _entities_from_answer(answer: str) -> list[str]:
    known = [
        "SQL", "BigQuery", "Mixpanel", "AppsFlyer", "A/B", "YOLO", "SORT", "OpenCV",
        "TensorFlow Lite", "MediaPipe", "Google ADK", "Veo 3", "dbt", "Segment",
        "Amplitude", "Looker", "RAG", "OCR", "retention", "conversion", "refund",
        "wallet", "churn", "TinyML", "KYC", "seller onboarding", "first listing",
        "first order", "support SLA", "Tesseract", "QuickKart",
    ]
    lower = answer.lower()
    return [item for item in known if item.lower() in lower][:8]


def _clean_md(value: Any, limit: int = 220) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")[:limit]


def _focus_terms(case: RobustCase) -> set[str]:
    terms: set[str] = set()
    for anchor in (*case.expected_anchors, *case.expected_failure_probes):
        for token in re.findall(r"[a-z0-9]+", anchor.lower()):
            if len(token) > 3:
                terms.add(token)
    return terms


def _question_quality_score(question: str, case: RobustCase) -> tuple[int, list[str]]:
    q = re.sub(r"\s+", " ", str(question or "").strip())
    lower = q.lower()
    failures: list[str] = []
    words = q.split()
    if len(words) < 7:
        failures.append("too_short")
    if len(words) > 52:
        failures.append("too_long")
    if not (q.endswith("?") or lower.startswith(("walk me through", "tell me", "explain", "describe"))):
        failures.append("not_question_like")
    if any(pattern in lower for pattern in GENERIC_PATTERNS):
        failures.append("generic_or_robotic")
    if any(bad in lower for bad in ("lying", "fake", "caught", "prove you")):
        failures.append("hostile_tone")
    case_terms = _focus_terms(case)
    if case_terms and not any(term in lower for term in case_terms):
        failures.append("not_case_grounded")
    return max(0, 100 - 15 * len(failures)), failures


def _best_worst_questions(turns: list[dict[str, Any]], case: RobustCase) -> dict[str, list[dict[str, Any]]]:
    scored: list[dict[str, Any]] = []
    terminal_routes = {"warm_open", "synthesis_close", "graceful_exit", "complete"}
    for turn in turns:
        if str(turn.get("route_kind") or "") in terminal_routes:
            continue
        question = str(turn.get("ai_response") or "")
        if not question:
            continue
        score, failures = _question_quality_score(question, case)
        scored.append({
            "turn": turn.get("turn"),
            "score": score,
            "failures": failures,
            "route": turn.get("route_kind"),
            "focus": turn.get("state_focus_label"),
            "question": question,
        })
    return {
        "best": sorted(scored, key=lambda item: item["score"], reverse=True)[:3],
        "worst": sorted(scored, key=lambda item: item["score"])[:3],
    }


async def _wait_for_orchestrator_idle(orch: Orchestrator, session_id: str, timeout: float) -> None:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        in_flight = any(key[0] == session_id for key in orch._pipeline_inflight)
        turn_running = bool(orch._turn_pipeline_running.get(session_id))
        finalizing = session_id in orch._finalization_inflight
        hydrating = session_id in getattr(orch, "_hydration_inflight", set())
        if not in_flight and not turn_running and not finalizing and not hydrating:
            return
        await asyncio.sleep(1.0)


def _route_repetition(turns: list[dict[str, Any]]) -> dict[str, Any]:
    focus_keys = [
        str(t.get("answered_focus_key") or t.get("state_focus_key") or "")
        for t in turns
        if str(t.get("route_kind") or "").strip() not in NON_SUBSTANTIVE_SIM_ROUTES
        and str(t.get("answered_focus_key") or t.get("state_focus_key") or "")
    ]
    surface_keys = []
    for t in turns:
        if str(t.get("route_kind") or "").strip() in NON_SUBSTANTIVE_SIM_ROUTES:
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
    for focus_key in focus_keys:
        if focus_key == current:
            streak += 1
        else:
            current = focus_key
            streak = 1
        max_streak = max(max_streak, streak)
    max_surface_streak = 0
    current_surface = ""
    surface_streak = 0
    for surface_key in surface_keys:
        if surface_key == current_surface:
            surface_streak += 1
        else:
            current_surface = surface_key
            surface_streak = 1
        max_surface_streak = max(max_surface_streak, surface_streak)
    return {
        "focus_sequence": focus_keys,
        "surface_sequence": surface_keys,
        "focus_label_sequence": [
            str(t.get("answered_focus_label") or t.get("state_focus_label") or "")
            for t in turns
        ],
        "phase_sequence": [str(t.get("agenda_phase") or "") for t in turns],
        "route_sequence": [str(t.get("route_kind") or "") for t in turns],
        "max_same_focus_streak": max_streak,
        "max_same_surface_streak": max_surface_streak,
    }


def _generic_question_flags(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for turn in turns:
        q = str(turn.get("ai_response") or "")
        lower = q.lower()
        matched = [pattern for pattern in GENERIC_PATTERNS if pattern in lower]
        if matched:
            flags.append({"turn": turn.get("turn"), "patterns": matched, "question": q})
    return flags


def _map_adherence(turns: list[dict[str, Any]], focus_keys: set[str]) -> dict[str, Any]:
    map_backed_routes = {
        "trajectory_map_surface",
        "trajectory_map_mechanism",
        "trajectory_map_boundary",
        "trajectory_map_focus_pivot",
        "application_grounding",
        "application_transfer",
        "coverage_surface",
        "coverage_depth_probe",
        "second_anchor",
    }
    relevant = [t for t in turns if str(t.get("route_kind") or "") in map_backed_routes]
    if not relevant:
        return {"score": 0, "map_backed_turns": 0, "missing_focus_turns": [], "off_map_focus_turns": []}
    missing = [
        t.get("turn")
        for t in relevant
        if not str(t.get("answered_focus_key") or t.get("state_focus_key") or "").strip()
    ]
    off_map = [
        t.get("turn")
        for t in relevant
        if str(t.get("answered_focus_key") or t.get("state_focus_key") or "").strip()
        and str(t.get("answered_focus_key") or t.get("state_focus_key") or "").strip() not in focus_keys
    ]
    score = max(0, 100 - 20 * len(missing) - 10 * len(off_map))
    return {
        "score": score,
        "map_backed_turns": len(relevant),
        "missing_focus_turns": missing,
        "off_map_focus_turns": off_map,
    }


def _coverage_details(state: dict[str, Any]) -> dict[str, Any]:
    coverage_map = state.get("coverage_map") or {}
    dims = [d for d in (coverage_map.get("dimensions") or []) if isinstance(d, dict)] if isinstance(coverage_map, dict) else []
    evaluated = [
        d for d in dims
        if str(d.get("coverage_state") or "") in {"voluntary", "recovered_deep", "recovered_surface", "missed", "incorrect"}
    ]
    return {
        "dimension_count": len(dims),
        "evaluated_count": len(evaluated),
        "evaluated_dimensions": [
            {
                "id": d.get("id"),
                "label": d.get("label"),
                "state": d.get("coverage_state"),
                "surfacing_attempted": d.get("surfacing_attempted"),
            }
            for d in evaluated
        ],
    }


def _map_case_summary(case: RobustCase, state: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    interview_map = state.get("interview_trajectory_map") or {}
    validation = state.get("interview_map_validation") or {}
    focus_areas = [a for a in (interview_map.get("focus_areas") or []) if isinstance(a, dict)]
    quality_review = interview_map.get("quality_review") or {}
    audit_review = interview_map.get("focus_plan_audit_review") or interview_map.get("audit_review") or {}
    model_policy = interview_map.get("model_policy") or {}
    track_models = [str(a.get("track_model") or "") for a in focus_areas]
    rescue_used = any(model and model == model_policy.get("map_rescue_model") for model in track_models)
    primary_used = any(model and model == model_policy.get("map_generator_model") for model in track_models)
    audit_score = float(audit_review.get("overall_score") or 0) if isinstance(audit_review, dict) else 0.0
    sonnet_score = float(quality_review.get("overall_score") or 0) if isinstance(quality_review, dict) else 0.0
    disagreement = bool(audit_review) and abs(audit_score - sonnet_score) >= 1.5
    priority_reports = list(validation.get("focus_reports") or [])[:2]
    posture_counts: dict[str, int] = {}
    voice_complexity_counts: dict[str, int] = {}
    low_information_questions: list[dict[str, Any]] = []
    for area in focus_areas:
        for index, item in enumerate(area.get("question_ladder") or []):
            if not isinstance(item, dict):
                continue
            posture = str(item.get("posture") or "unknown").strip().lower() or "unknown"
            complexity = str(item.get("voice_complexity") or "unknown").strip().lower() or "unknown"
            information_gain = str(item.get("information_gain") or "medium").strip().lower()
            posture_counts[posture] = posture_counts.get(posture, 0) + 1
            voice_complexity_counts[complexity] = voice_complexity_counts.get(complexity, 0) + 1
            if information_gain in {"low", "trivia"}:
                low_information_questions.append({
                    "focus_key": area.get("focus_key"),
                    "path": f"question_ladder[{index}].main_question",
                    "posture": posture,
                    "question": item.get("main_question"),
                })
    return {
        "key": case.key,
        "label": case.label,
        "purpose": case.purpose,
        "ok": state.get("interview_map_status") == "ready",
        "elapsed_ms": elapsed_ms,
        "model_policy": model_policy,
        "primary_generator_used": primary_used,
        "sonnet_rescue_used": rescue_used,
        "deepseek_audit_present": bool(audit_review),
        "deepseek_sonnet_disagreement": disagreement,
        "audit_review": audit_review,
        "quality_review": quality_review,
        "map_quality_scorecard": interview_map.get("map_quality_scorecard") or {},
        "question_ladder_summary": {
            "posture_counts": posture_counts,
            "voice_complexity_counts": voice_complexity_counts,
            "low_information_questions": low_information_questions,
        },
        "repair_summary": interview_map.get("repair_summary") or {},
        "weight_calibration_warnings": interview_map.get("weight_calibration_warnings") or [],
        "latency_breakdown": interview_map.get("latency_breakdown") or {},
        "validation": validation,
        # Preserve the full runtime map for future no-credit replay. Earlier
        # artifacts only kept human summaries, which made it impossible to
        # distinguish true startup regressions from summary-field loss.
        "interview_trajectory_map": interview_map,
        "launch_ready": bool(interview_map.get("launch_ready")),
        "full_map_ready": bool(interview_map.get("full_map_ready")),
        "needs_async_hydration": bool(interview_map.get("needs_async_hydration")),
        "launch_focus_keys": list(interview_map.get("launch_focus_keys") or []),
        "pending_hydration_focus_keys": list(interview_map.get("pending_hydration_focus_keys") or []),
        "deferred_focus_plan": [
            {
                "label": area.get("label"),
                "focus_key": area.get("focus_key"),
                "coverage_value": area.get("coverage_value"),
                "sub_focuses": area.get("sub_focuses") or [],
            }
            for area in (interview_map.get("deferred_focus_plan") or [])
            if isinstance(area, dict)
        ],
        "map_quarantine": list(interview_map.get("map_quarantine") or []),
        "focus_count": len(focus_areas),
        "first_two_launch_ready": sum(1 for item in priority_reports if item.get("ready")) >= 2,
        "focus_areas": [
            {
                "label": area.get("label"),
                "focus_key": area.get("focus_key"),
                "coverage_value": area.get("coverage_value"),
                "sub_focuses": area.get("sub_focuses") or [],
                "track_source": area.get("track_source"),
                "track_model": area.get("track_model"),
                "track_latency_ms": area.get("track_latency_ms"),
                "generation_attempt_errors": area.get("generation_attempt_errors") or [],
                "track_generation_strategy": area.get("track_generation_strategy"),
                "repair_strategy": area.get("repair_strategy"),
                "repair_target_count": area.get("repair_target_count"),
                "repair_provenance": area.get("repair_provenance") or [],
                "dimensions": [
                    {
                        "id": dim.get("id"),
                        "label": dim.get("label"),
                        "signal_weight": dim.get("signal_weight"),
                    }
                    for dim in interview_map_module._track_dimensions(area)
                    if isinstance(dim, dict)
                ],
                "question_ladder": [
                    {
                        "posture": item.get("posture"),
                        "main_question": str(item.get("main_question") or "")[:260],
                        "signal_goal": item.get("signal_goal"),
                        "expected_space": item.get("expected_space") or [],
                        "follow_up_if_shallow": str(item.get("follow_up_if_shallow") or "")[:260],
                        "follow_up_if_strong": str(item.get("follow_up_if_strong") or "")[:260],
                        "information_gain": item.get("information_gain"),
                        "voice_complexity": item.get("voice_complexity"),
                    }
                    for item in (area.get("question_ladder") or [])
                    if isinstance(item, dict)
                ],
                "dimension_count": len(interview_map_module._track_dimensions(area)),
                "question_ladder_count": len(area.get("question_ladder") or []),
                "map_schema_version": area.get("map_schema_version"),
                "primary_question_contract": area.get("primary_question_contract"),
                "opener": interview_map_module._track_opener(area)[:260],
            }
            for area in focus_areas
        ],
    }


async def run_map_only_case(case: RobustCase) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        session_id = f"robust-map-{case.key}"
        interview_map = await interview_map_module.generate_interview_map(
            resume=case.resume,
            session_id=session_id,
            target_role=case.target_role,
        )
        validation = interview_map_module.validate_interview_map(
            interview_map,
            require_all_llm=False,
            min_llm_branch_ratio=0.72,
        )
        state = {
            "interview_map_status": "ready" if validation.get("priority_llm_ready_count", 0) >= 2 else "failed",
            "interview_trajectory_map": interview_map,
            "interview_map_validation": validation,
        }
        result = _map_case_summary(case, state, round((time.perf_counter() - started) * 1000))
        result["session_id"] = session_id
        return result
    except Exception as exc:
        return {
            "key": case.key,
            "label": case.label,
            "purpose": case.purpose,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:1800],
            "map_failure_diagnostics": getattr(exc, "diagnostics", {}) or {},
        }


def _full_quality_gate(result: dict[str, Any], *, required_turns: int, case: RobustCase | None = None) -> dict[str, Any]:
    failures: list[str] = []
    turns = result.get("turns") or []
    routes = [str(t.get("route_kind") or "") for t in turns]
    phases = [str(t.get("agenda_phase") or "") for t in turns]
    route_rep = result.get("route_repetition") or {}
    coverage = result.get("coverage_details") or {}
    final_eval = result.get("final_evaluation") or {}
    assessment = result.get("assessment_coverage") or {}
    early_close = bool((result.get("interview_agenda") or {}).get("close_reason"))
    app_turn = result.get("application_transfer_turn")
    second_anchor_turn = result.get("second_anchor_turn")

    if not result.get("ok"):
        failures.append(f"case_failed:{result.get('error_type')}")
    if not early_close and int(result.get("question_count") or 0) < required_turns:
        failures.append("question_count_below_required")
    if int(result.get("history_len") or 0) != int(result.get("question_count") or 0):
        failures.append("history_len_does_not_match_question_count")
    if result.get("finalization_status") != "complete" or not result.get("report_ready"):
        failures.append("report_not_ready_after_completion")
    if not result.get("map_first_two_launch_ready"):
        failures.append("first_two_map_tracks_not_launch_ready")
    effective_focus_streak = int(route_rep.get("max_same_focus_streak") or 0)
    if assessment.get("max_same_focus_streak") is not None:
        # Parent focus is an experience area. The anti-tunnel product rule is
        # about repeatedly drilling the same issue/surface, not fairly exploring
        # multiple high-value sub-focus surfaces inside one relevant role area.
        effective_focus_streak = min(
            effective_focus_streak,
            int(assessment.get("max_same_focus_streak") or effective_focus_streak),
        )
        if (
            int(assessment.get("distinct_surfaces") or 0) >= 3
            or int(assessment.get("high_value_surfaces_tested_count") or 0) >= 2
        ):
            effective_focus_streak = min(
                effective_focus_streak,
                int(assessment.get("max_same_surface_streak") or effective_focus_streak),
            )
    route_rep["effective_max_same_focus_streak"] = effective_focus_streak
    route_surface_streak = int(route_rep.get("max_same_surface_streak") or 0)
    if (
        int(assessment.get("distinct_surfaces") or 0) >= 3
        or int(route_rep.get("distinct_surfaces") or 0) >= 3
    ):
        surface_streaks = [
            value
            for value in (
                route_surface_streak,
                int(assessment.get("max_same_surface_streak") or 0),
            )
            if value > 0
        ]
        if surface_streaks:
            effective_focus_streak = min(effective_focus_streak, min(surface_streaks))
            route_rep["effective_max_same_focus_streak"] = effective_focus_streak
    if effective_focus_streak > 4 and (route_surface_streak <= 0 or route_surface_streak > 4):
        failures.append("max_same_focus_streak_exceeded")
    if (
        len(set([fk for fk in route_rep.get("focus_sequence", []) if fk])) < 2
        and int(assessment.get("distinct_surfaces") or 0) < 2
    ):
        failures.append("fewer_than_two_substantive_surfaces_tested")
    if not result.get("application_question_served"):
        failures.append("application_transfer_not_served")
    if app_turn is not None and not (5 <= int(app_turn) <= 7):
        failures.append(f"application_transfer_outside_turn_5_7:{app_turn}")
    if int(coverage.get("evaluated_count") or 0) < 1:
        failures.append("coverage_dimensions_not_evaluated")
    if second_anchor_turn is None and not early_close:
        failures.append("second_anchor_not_attempted")
    elif second_anchor_turn is not None and not (10 <= int(second_anchor_turn) <= 13):
        failures.append(f"second_anchor_outside_turn_10_13:{second_anchor_turn}")
    if case and case.expected_second_anchor_terms and second_anchor_turn is not None:
        second_anchor_terms = [str(term or "").lower() for term in case.expected_second_anchor_terms if str(term or "").strip()]
        second_anchor_text_parts: list[str] = []
        for turn in turns:
            if (
                str(turn.get("route_kind") or "") == "second_anchor"
                or str(turn.get("agenda_phase") or "") == "second_anchor"
            ):
                second_anchor_text_parts.extend(
                    str(turn.get(field) or "")
                    for field in (
                        "question",
                        "ai_response",
                        "answered_focus_label",
                        "answered_sub_focus_label",
                        "state_focus_label",
                        "state_sub_focus_label",
                    )
                )
        second_anchor_text = re.sub(r"\s+", " ", " ".join(second_anchor_text_parts).lower())
        if second_anchor_terms and not any(term in second_anchor_text for term in second_anchor_terms):
            failures.append("second_anchor_missing_expected_surface")
    if any(route == "sprint_opener" for route in routes[5:]):
        failures.append("late_generic_sprint_opener")
    if (result.get("map_adherence") or {}).get("missing_focus_turns"):
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
    if "application_transfer" in phases and not any("coverage" in p for p in phases):
        failures.append("coverage_phase_missing_after_application")
    return {"passed": not failures, "failures": failures}


async def run_full_case(case: RobustCase, *, max_turns: int) -> dict[str, Any]:
    orch = Orchestrator()
    idle_timeout = float(os.environ.get("SIM_IDLE_TIMEOUT", "55"))
    started = time.perf_counter()
    turns: list[dict[str, Any]] = []
    session_id = ""
    result: dict[str, Any] = {
        "key": case.key,
        "label": case.label,
        "purpose": case.purpose,
        "target_role": case.target_role,
        "years_experience": case.years_experience,
        "ok": False,
    }
    try:
        print(f"[RobustSim] Preparing map for {case.key}", flush=True)
        session_id = await orch.prepare_session_map(
            resume=case.resume,
            github_links=[],
            target_role=case.target_role,
            years_experience=case.years_experience,
        )
        print(
            f"[RobustSim] Map prepared for {case.key} session={session_id[:8]} "
            f"elapsed_ms={round((time.perf_counter() - started) * 1000)}",
            flush=True,
        )
        await orch.start_prepared_session(session_id)
        state = await orch.session_manager.get_state(session_id)
        interview_map = state.get("interview_trajectory_map") or {}
        focus_areas = [a for a in (interview_map.get("focus_areas") or []) if isinstance(a, dict)]
        focus_keys = {str(a.get("focus_key") or "") for a in focus_areas if str(a.get("focus_key") or "")}
        result.update({
            "session_id": session_id,
            "startup_elapsed_ms": round((time.perf_counter() - started) * 1000),
            "opening_question": state.get("last_question", ""),
            "map_policy_trace": interview_map.get("model_policy", {}),
            "map_quality_review": interview_map.get("quality_review", {}),
            "map_audit_review": interview_map.get("audit_review", {}),
            "map_validation": state.get("interview_map_validation", {}),
            "map_first_two_launch_ready": sum(
                1 for item in (state.get("interview_map_validation", {}).get("focus_reports") or [])[:2]
                if item.get("ready")
            ) >= 2,
            "map_focus_areas": [
                {
                    "label": area.get("label"),
                    "focus_key": area.get("focus_key"),
                    "track_source": area.get("track_source"),
                    "track_model": area.get("track_model"),
                    "dimension_count": len(interview_map_module._track_dimensions(area)),
                    "question_ladder_count": len(area.get("question_ladder") or []),
                    "map_schema_version": area.get("map_schema_version"),
                    "primary_question_contract": area.get("primary_question_contract"),
                    "opener": interview_map_module._track_opener(area)[:260],
                }
                for area in focus_areas
            ],
        })
        current_question = str(state.get("last_question") or "")

        for turn_index in range(max_turns):
            print(
                f"[RobustSim] Turn {turn_index + 1}/{max_turns} answering "
                f"question_chars={len(current_question)}",
                flush=True,
            )
            bucket, answer, answer_metadata = await _llm_answer_for(case, turn_index, current_question, turns)
            turn_id = f"robust-{case.key}-turn-{turn_index + 1}"
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
            turns.append({
                "turn": turn_index + 1,
                "question": current_question,
                "answer_bucket": bucket,
                "answer_metadata": answer_metadata,
                "answer": answer,
                "ai_response": response.get("response"),
                "route_kind": response.get("route_kind"),
                "agenda_phase": agenda.get("phase"),
                "agenda_reason": agenda.get("last_route_reason"),
                "answered_focus_key": answered_packet.get("focus_key"),
                "answered_focus_label": answered_packet.get("focus_label"),
                "answered_sub_focus_key": answered_packet.get("sub_focus_key"),
                "answered_sub_focus_label": answered_packet.get("sub_focus_label"),
                "coverage_dimension_id": answered_packet.get("coverage_dimension_id"),
                "coverage_dimension_label": answered_packet.get("coverage_dimension_label"),
                "question_posture": answered_packet.get("question_posture"),
                "signal_goal": answered_packet.get("signal_goal"),
                "expected_space": answered_packet.get("expected_space") or [],
                "information_gain": answered_packet.get("information_gain"),
                "voice_complexity": answered_packet.get("voice_complexity"),
                "state_focus_key": active_packet.get("focus_key"),
                "state_focus_label": active_packet.get("focus_label"),
                "state_sub_focus_key": active_packet.get("sub_focus_key"),
                "state_sub_focus_label": active_packet.get("sub_focus_label"),
                "weakness": response.get("weakness"),
                "discrepancy": response.get("discrepancy"),
                "question_count": response.get("question_count"),
                "latency_ms": round((time.perf_counter() - turn_started) * 1000),
            })
            print(
                f"[RobustSim] Turn {turn_index + 1} route={response.get('route_kind')} "
                f"latency_ms={turns[-1]['latency_ms']} next_chars={len(current_question)}",
                flush=True,
            )
            current_question = str(response.get("response") or "")
            await _wait_for_orchestrator_idle(orch, session_id, idle_timeout)
            turn_state = await orch.session_manager.get_state(session_id)
            turns[-1]["policy_check_after_staging"] = turn_state.get("last_policy_check", {})
            turns[-1]["policy_warning_codes"] = list(
                (turn_state.get("last_policy_check") or {}).get("primary_warning_codes") or []
            )
            if response.get("complete"):
                break

        await orch.end_session(session_id)
        await _wait_for_orchestrator_idle(orch, session_id, idle_timeout)
        final_state = await orch.session_manager.get_state(session_id)
        route_rep = _route_repetition(turns)
        coverage = _coverage_details(final_state)
        app_arc = final_state.get("application_transfer_arc") if isinstance(final_state.get("application_transfer_arc"), dict) else {}
        grounding_turns = [t["turn"] for t in turns if t.get("route_kind") == "application_grounding"]
        application_turns = [t["turn"] for t in turns if t.get("route_kind") == "application_transfer"]
        coverage_turns = [t["turn"] for t in turns if "coverage" in str(t.get("route_kind") or "")]
        second_anchor_turns = [
            t["turn"] for t in turns
            if str(t.get("route_kind") or "") == "second_anchor"
            or str(t.get("agenda_phase") or "") == "second_anchor"
        ]
        result.update({
            "ok": True,
            "turns": turns,
            "history_len": len(final_state.get("history", []) or []),
            "question_count": final_state.get("question_count"),
            "interview_trajectory_map": final_state.get("interview_trajectory_map", {}),
            "final_interview_map_validation": final_state.get("interview_map_validation", {}),
            "full_map_ready": bool((final_state.get("interview_trajectory_map") or {}).get("full_map_ready")),
            "pending_hydration_focus_keys": list((final_state.get("interview_trajectory_map") or {}).get("pending_hydration_focus_keys") or []),
            "map_quarantine": list((final_state.get("interview_trajectory_map") or {}).get("map_quarantine") or []),
            "application_question_served": bool(final_state.get("application_question_served")),
            "application_grounding_turn": grounding_turns[0] if grounding_turns else None,
            "application_transfer_arc": app_arc,
            "application_transfer_turn": application_turns[0] if application_turns else None,
            "application_transfer_repair_verification": final_state.get("application_transfer_repair_verification", {}),
            "coverage_turns": coverage_turns,
            "second_anchor_turn": second_anchor_turns[0] if second_anchor_turns else None,
            "coverage_details": coverage,
            "finalization_status": final_state.get("finalization_status"),
            "finalization_error": final_state.get("finalization_error", ""),
            "report_ready": final_state.get("report_ready"),
            "final_evaluation": final_state.get("final_evaluation", {}),
            "assessment_coverage": final_state.get("assessment_coverage", {}),
            "interview_agenda": final_state.get("interview_agenda", {}),
            "policy_checker_events": final_state.get("policy_checker_events", []),
            "policy_warning_count": final_state.get("policy_warning_count", 0),
            "policy_warning_codes": sorted({
                str(code)
                for event in (final_state.get("policy_checker_events") or [])
                if isinstance(event, dict)
                for code in (event.get("warning_codes") or [])
                if str(code)
            }),
            "route_repetition": route_rep,
            "posture_sequence": [str(t.get("question_posture") or "") for t in turns],
            "voice_complexity_distribution": {
                value: sum(1 for t in turns if str(t.get("voice_complexity") or "") == value)
                for value in sorted({str(t.get("voice_complexity") or "") for t in turns if t.get("voice_complexity")})
            },
            "generic_question_flags": _generic_question_flags(turns),
            "map_adherence": _map_adherence(turns, focus_keys),
            "question_quality": _best_worst_questions(turns, case),
        })
        result["quality_gate"] = _full_quality_gate(result, required_turns=max_turns, case=case)
        return result
    except Exception as exc:
        failed_session_id = str(getattr(exc, "session_id", "") or session_id or "")
        map_failure_diagnostics = getattr(exc, "diagnostics", {}) or {}
        failed_state_summary: dict[str, Any] = {}
        if failed_session_id and not map_failure_diagnostics:
            try:
                failed_state = await orch.session_manager.get_state(failed_session_id)
                map_failure_diagnostics = failed_state.get("interview_map_failure_diagnostics") or {}
                failed_map = failed_state.get("interview_trajectory_map") or {}
                failed_state_summary = {
                    "question_count": failed_state.get("question_count"),
                    "history_len": len(failed_state.get("history", []) or []),
                    "interview_complete": bool(failed_state.get("interview_complete")),
                    "finalization_status": failed_state.get("finalization_status"),
                    "finalization_error": failed_state.get("finalization_error", ""),
                    "report_ready": bool(failed_state.get("report_ready")),
                    "full_map_ready": bool(failed_map.get("full_map_ready")),
                    "pending_hydration_focus_keys": list(failed_map.get("pending_hydration_focus_keys") or []),
                    "map_quarantine": list(failed_map.get("map_quarantine") or []),
                    "application_transfer_repair_verification": failed_state.get("application_transfer_repair_verification", {}),
                    "application_transfer_arc": failed_state.get("application_transfer_arc", {}),
                    "interview_agenda": failed_state.get("interview_agenda", {}),
                }
            except Exception:
                map_failure_diagnostics = {}
        result.update({
            "ok": False,
            "session_id": failed_session_id,
            "startup_elapsed_ms": round((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:1800],
            "traceback": traceback.format_exc(limit=25),
            "map_failure_diagnostics": map_failure_diagnostics,
            "failed_state_summary": failed_state_summary,
            "turns": turns,
        })
        result["quality_gate"] = {"passed": False, "failures": [f"{type(exc).__name__}:{str(exc)[:180]}"]}
        return result


def _map_markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Robust Map Policy Simulation", ""]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("| Case | OK | ms | Focuses | First 2 Ready | Primary Used | Sonnet Rescue | DeepSeek Audit | Audit Disagree | Critic Score | Map Score | Repairs |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        review = r.get("quality_review") or {}
        lines.append(
            f"| {_clean_md(r.get('label'), 80)} | {r.get('ok')} | {r.get('elapsed_ms')} | "
            f"{r.get('focus_count', '')} | {r.get('first_two_launch_ready', '')} | "
            f"{r.get('primary_generator_used', '')} | {r.get('sonnet_rescue_used', '')} | "
            f"{r.get('deepseek_audit_present', '')} | {r.get('deepseek_sonnet_disagreement', '')} | "
            f"{review.get('overall_score', '')} | "
            f"{(r.get('map_quality_scorecard') or {}).get('overall_score', '')} | "
            f"{(r.get('repair_summary') or {}).get('count', 0)} |"
        )
    for r in results:
        lines.extend(["", f"## {_clean_md(r.get('label'), 120)}", ""])
        if not r.get("ok"):
            lines.append(f"- Error: `{r.get('error_type')}: {_clean_md(r.get('error'), 400)}`")
        if r.get("map_failure_diagnostics"):
            diag = r.get("map_failure_diagnostics") or {}
            lines.append(f"- Failure diagnostics: `{json.dumps(diag, ensure_ascii=True)[:1800]}`")
        lines.append(f"- Purpose: {_clean_md(r.get('purpose'), 400)}")
        lines.append(f"- Policy: `{json.dumps(r.get('model_policy') or {}, ensure_ascii=True)[:500]}`")
        lines.append(
            f"- Launch readiness: launch_ready=`{r.get('launch_ready')}` "
            f"full_map_ready=`{r.get('full_map_ready')}` "
            f"needs_async_hydration=`{r.get('needs_async_hydration')}` "
            f"pending=`{r.get('pending_hydration_focus_keys') or []}`"
        )
        if r.get("deferred_focus_plan"):
            lines.append("- Deferred focus plan:")
            for area in r.get("deferred_focus_plan", [])[:5]:
                lines.append(
                    f"  - `{area.get('focus_key')}` {_clean_md(area.get('label'), 140)} "
                    f"value=`{area.get('coverage_value')}`"
                )
        if r.get("map_quarantine"):
            lines.append(f"- Map quarantine: `{json.dumps(r.get('map_quarantine') or [], ensure_ascii=True)[:700]}`")
        audit_payload = r.get("audit_review") or {}
        audit_warnings = audit_payload.get("warnings") or audit_payload.get("issues") or []
        lines.append(f"- Audit warnings: `{json.dumps(audit_warnings, ensure_ascii=True)[:500]}`")
        ladder_summary = r.get("question_ladder_summary") or {}
        if ladder_summary:
            lines.append(
                "- Question ladder: "
                f"postures=`{json.dumps(ladder_summary.get('posture_counts') or {}, ensure_ascii=True)}` "
                f"voice=`{json.dumps(ladder_summary.get('voice_complexity_counts') or {}, ensure_ascii=True)}` "
                f"low_info={len(ladder_summary.get('low_information_questions') or [])}"
            )
        scorecard = r.get("map_quality_scorecard") or {}
        if scorecard:
            lines.append(
                "- Map quality scorecard: "
                f"overall=`{scorecard.get('overall_score')}` "
                f"boundary=`{scorecard.get('focus_boundary_score')}` "
                f"opener=`{scorecard.get('opener_score')}` "
                f"dimension=`{scorecard.get('dimension_depth_score')}` "
                f"readability=`{scorecard.get('readability_score')}`"
            )
            for label, key in (("Best questions", "top_3_best_questions"), ("Weakest questions", "top_3_weakest_questions")):
                questions = scorecard.get(key) or []
                if questions:
                    lines.append(f"- {label}:")
                    for q in questions[:3]:
                        lines.append(
                            f"  - `{q.get('score')}` `{q.get('focus_key')}` `{q.get('path')}` "
                            f"{_clean_md(q.get('question'), 260)}"
                        )
        if r.get("weight_calibration_warnings"):
            lines.append("- Weight calibration warnings:")
            for warning in r.get("weight_calibration_warnings", [])[:6]:
                lines.append(
                    f"  - `{warning.get('severity')}` `{warning.get('focus_key')}` "
                    f"{_clean_md(warning.get('warning'), 220)}"
                )
        repair_summary = r.get("repair_summary") or {}
        if repair_summary.get("count"):
            lines.append(f"- Repair summary: `{json.dumps({k: v for k, v in repair_summary.items() if k != 'repairs'}, ensure_ascii=True)[:500]}`")
            for repair in repair_summary.get("repairs", [])[:8]:
                lines.append(
                    f"  - `{repair.get('accepted_by')}` `{repair.get('focus_key')}` `{repair.get('path')}` "
                    f"{_clean_md(repair.get('repair_reason'), 240)}"
                )
        latency = r.get("latency_breakdown") or {}
        if latency:
            lines.append(f"- Latency total: `{latency.get('total_ms')}` ms")
            lines.append("- Latency breakdown:")
            for step in latency.get("steps", []) or []:
                extras = {
                    key: value
                    for key, value in step.items()
                    if key not in {"stage", "elapsed_ms", "track_latencies"}
                }
                lines.append(
                    f"  - `{step.get('stage')}`: `{step.get('elapsed_ms')}` ms"
                    + (f" `{json.dumps(extras, ensure_ascii=True)[:450]}`" if extras else "")
                )
                for track in step.get("track_latencies", []) or []:
                    lines.append(
                        f"    - `{track.get('focus_key')}` `{track.get('strategy')}` "
                        f"model=`{track.get('model')}` ms=`{track.get('elapsed_ms')}`"
                    )
        lines.append("- Focus areas:")
        for area in r.get("focus_areas", []) or []:
            lines.append(
                f"  - **{_clean_md(area.get('label'), 120)}** "
                f"`{area.get('focus_key')}` coverage_value=`{area.get('coverage_value')}` "
                f"model=`{area.get('track_model')}` track_ms=`{area.get('track_latency_ms')}` "
                f"strategy=`{area.get('track_generation_strategy') or area.get('repair_strategy')}` "
                f"dims={area.get('dimension_count')}: "
                f"{_clean_md(area.get('opener'), 240)}"
            )
            if area.get("generation_attempt_errors"):
                lines.append(
                    f"    - generation attempt errors: "
                    f"`{json.dumps(area.get('generation_attempt_errors') or [], ensure_ascii=True)[:700]}`"
                )
            for sf in area.get("sub_focuses", []) or []:
                if isinstance(sf, dict):
                    lines.append(
                        "    - surface "
                        f"`{_clean_md(sf.get('sub_focus_key'), 90)}` "
                        f"role={sf.get('role_relevance_weight')} "
                        f"profile={sf.get('profile_importance_weight')} "
                        f"evidence={sf.get('evidence_strength')} "
                        f"risk={sf.get('claim_risk')} "
                        f"value={sf.get('coverage_value')}: "
                        f"{_clean_md(sf.get('label'), 160)}"
                    )
                else:
                    lines.append(f"    - surface `{_clean_md(sf, 160)}`")
            if area.get("dimensions"):
                weights = [
                    f"{d.get('id')}={d.get('signal_weight')}"
                    for d in area.get("dimensions", []) or []
                ]
                lines.append(f"    - dimension weights: `{', '.join(weights)}`")
            if area.get("question_ladder"):
                lines.append("    - question ladder:")
                for item in area.get("question_ladder", [])[:6]:
                    lines.append(
                        f"      - `{item.get('posture')}` gain=`{item.get('information_gain')}` "
                        f"voice=`{item.get('voice_complexity')}` "
                        f"{_clean_md(item.get('main_question'), 240)}"
                    )
                    if item.get("expected_space"):
                        lines.append(f"        expected: `{json.dumps(item.get('expected_space') or [], ensure_ascii=True)[:240]}`")
                    if item.get("follow_up_if_shallow"):
                        lines.append(f"        shallow: {_clean_md(item.get('follow_up_if_shallow'), 220)}")
                    if item.get("follow_up_if_strong"):
                        lines.append(f"        strong: {_clean_md(item.get('follow_up_if_strong'), 220)}")
            for repair in area.get("repair_provenance", []) or []:
                lines.append(
                    f"    - repaired `{repair.get('path')}` by `{repair.get('accepted_by')}` "
                    f"model=`{repair.get('model')}` reason={_clean_md(repair.get('repair_reason'), 180)}"
                )
    return "\n".join(lines) + "\n"


def _full_markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Robust Full Interview Simulation", ""]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("| Case | OK | Gate | Qs | App Turn | Coverage Turns | Second Anchor | Streak | Verdict | Score |")
    lines.append("|---|---:|---:|---:|---:|---|---:|---:|---|---:|")
    for r in results:
        ev = r.get("final_evaluation") or {}
        rep = r.get("route_repetition") or {}
        lines.append(
            f"| {_clean_md(r.get('label'), 80)} | {r.get('ok')} | {(r.get('quality_gate') or {}).get('passed')} | "
            f"{r.get('question_count', len(r.get('turns') or []))} | {r.get('application_transfer_turn')} | "
            f"{r.get('coverage_turns', [])} | {r.get('second_anchor_turn')} | "
            f"{rep.get('effective_max_same_focus_streak', rep.get('max_same_focus_streak', ''))} | {ev.get('hire_recommendation', '')} | {ev.get('overall_score', '')} |"
        )
    for r in results:
        lines.extend(["", f"## {_clean_md(r.get('label'), 120)}", ""])
        lines.append(f"- Session: `{r.get('session_id', '')}`")
        if not r.get("ok") and r.get("error_type"):
            lines.append(f"- Error: `{r.get('error_type')}: {_clean_md(r.get('error'), 500)}`")
        if r.get("map_failure_diagnostics"):
            diag = r.get("map_failure_diagnostics") or {}
            lines.append(
                f"- Map failure diagnostics: cause=`{_clean_md(diag.get('cause'), 500)}` "
                f"models=`{json.dumps(diag.get('model_policy') or {}, ensure_ascii=True)[:500]}`"
            )
            repaired_review = diag.get("repaired_review") or {}
            pass_one_review = diag.get("pass_one_review") or {}
            lines.append(
                f"- Map readiness reviews: pass1_ready=`{pass_one_review.get('ready')}` "
                f"pass1_score=`{pass_one_review.get('overall_score')}` "
                f"repaired_ready=`{repaired_review.get('ready')}` "
                f"repaired_score=`{repaired_review.get('overall_score')}`"
            )
        lines.append(f"- Purpose: {_clean_md(r.get('purpose'), 500)}")
        lines.append(f"- Gate: `{json.dumps(r.get('quality_gate') or {}, ensure_ascii=True)}`")
        lines.append(f"- Map adherence: `{json.dumps(r.get('map_adherence') or {}, ensure_ascii=True)}`")
        lines.append(f"- Generic flags: `{json.dumps(r.get('generic_question_flags') or [], ensure_ascii=True)[:800]}`")
        lines.append(
            f"- Policy checker: warnings=`{r.get('policy_warning_count', 0)}` "
            f"codes=`{json.dumps(r.get('policy_warning_codes') or [], ensure_ascii=True)}`"
        )
        lines.append(f"- Coverage: `{json.dumps(r.get('coverage_details') or {}, ensure_ascii=True)[:900]}`")
        if r.get("application_transfer_repair_verification"):
            lines.append(
                f"- App-transfer repair verifier: "
                f"`{json.dumps(r.get('application_transfer_repair_verification') or {}, ensure_ascii=True)[:1000]}`"
            )
        if r.get("posture_sequence"):
            lines.append(f"- Posture sequence: `{json.dumps(r.get('posture_sequence') or [], ensure_ascii=True)}`")
        if r.get("voice_complexity_distribution"):
            lines.append(
                f"- Voice complexity: `{json.dumps(r.get('voice_complexity_distribution') or {}, ensure_ascii=True)}`"
            )
        answer_meta = [
            t.get("answer_metadata") or {}
            for t in (r.get("turns") or [])
            if isinstance(t.get("answer_metadata"), dict)
        ]
        if answer_meta:
            fallbacks = sum(1 for item in answer_meta if item.get("fallback"))
            modes = sorted({str(item.get("mode") or "") for item in answer_meta if item.get("mode")})
            edge_counts: dict[str, int] = {}
            for item in answer_meta:
                signal = str(item.get("edge_signal") or "unknown")
                edge_counts[signal] = edge_counts.get(signal, 0) + 1
            lines.append(
                f"- Answerer: modes=`{modes}` fallbacks=`{fallbacks}` edge_signals="
                f"`{json.dumps(edge_counts, ensure_ascii=True)[:500]}`"
            )
        lines.append("- Best questions:")
        for item in (r.get("question_quality") or {}).get("best", []):
            lines.append(f"  - T{item.get('turn')} score={item.get('score')}: {_clean_md(item.get('question'), 260)}")
        lines.append("- Worst questions:")
        for item in (r.get("question_quality") or {}).get("worst", []):
            lines.append(f"  - T{item.get('turn')} score={item.get('score')} failures={item.get('failures')}: {_clean_md(item.get('question'), 260)}")
        lines.append("")
        lines.append("| Turn | Phase | Posture | Route | Policy Warnings | Answered Focus | Surface/Dim | Next Focus | Bucket | Signal | Question | Candidate Answer | AI Next Question |")
        lines.append("|---:|---|---|---|---|---|---|---|---|---|---|---|---|")
        for t in r.get("turns", []) or []:
            meta = t.get("answer_metadata") or {}
            signal = str(meta.get("edge_signal") or ("fallback" if meta.get("fallback") else meta.get("mode") or ""))
            surface_label = (
                t.get("coverage_dimension_label")
                or t.get("answered_sub_focus_label")
                or t.get("answered_sub_focus_key")
                or ""
            )
            lines.append(
                f"| {t.get('turn')} | {_clean_md(t.get('agenda_phase'), 80)} | {_clean_md(t.get('question_posture'), 60)} | {_clean_md(t.get('route_kind'), 80)} | "
                f"{_clean_md(', '.join(t.get('policy_warning_codes') or []), 120)} | "
                f"{_clean_md(t.get('answered_focus_label'), 120)} | {_clean_md(surface_label, 120)} | {_clean_md(t.get('state_focus_label'), 120)} | {_clean_md(t.get('answer_bucket'), 80)} | {_clean_md(signal, 80)} | "
                f"{_clean_md(t.get('question'), 240)} | {_clean_md(t.get('answer'), 240)} | {_clean_md(t.get('ai_response'), 240)} |"
            )
    return "\n".join(lines) + "\n"


def _write_artifacts(kind: str, results: list[dict[str, Any]], markdown: str) -> tuple[Path, Path]:
    prefix = os.environ.get("SIM_OUTPUT_PREFIX", "/tmp/antigravity_robust_interview")
    json_path = Path(f"{prefix}_{kind}.json")
    md_path = Path(f"{prefix}_{kind}.md")
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    print(f"[RobustSim] Wrote {json_path}")
    print(f"[RobustSim] Wrote {md_path}")
    return json_path, md_path


async def run_map_only(cases: list[RobustCase]) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        print(f"[RobustSim] Map-only case: {case.label}", flush=True)
        results.append(await run_map_only_case(case))
    _write_artifacts("map_policy", results, _map_markdown(results))
    return results


async def run_full_gate(cases: list[RobustCase], *, max_turns: int) -> list[dict[str, Any]]:
    print(f"[RobustSim] Full gate case: {cases[0].label}", flush=True)
    results = [await run_full_case(cases[0], max_turns=max_turns)]
    _write_artifacts("full_gate", results, _full_markdown(results))
    return results


async def run_full_all(cases: list[RobustCase], *, max_turns: int) -> list[dict[str, Any]]:
    first = await run_full_gate(cases, max_turns=max_turns)
    gate_passed = bool((first[0].get("quality_gate") or {}).get("passed"))
    if not gate_passed and not os.environ.get("SIM_FORCE_ALL"):
        print("[RobustSim] Gate failed; not running remaining cases. Set SIM_FORCE_ALL=1 to override.", flush=True)
        _write_artifacts("full_all", first, _full_markdown(first))
        return first
    print("[RobustSim] Running remaining full cases concurrently.", flush=True)
    rest = await asyncio.gather(*[run_full_case(case, max_turns=max_turns) for case in cases[1:]])
    results = [*first, *rest]
    _write_artifacts("full_all", results, _full_markdown(results))
    return results


async def main() -> None:
    policy = _apply_simulation_model_policy()
    print(f"[RobustSim] Simulation model policy: {json.dumps(policy, ensure_ascii=True)}", flush=True)
    cases = _select_cases()
    mode = os.environ.get("SIM_MODE", "map_only").strip().lower()
    max_turns = int(os.environ.get("SIM_TURNS", "15") or "15")
    if mode == "map_only":
        await run_map_only(cases)
    elif mode == "full_gate":
        await run_full_gate(cases, max_turns=max_turns)
    elif mode == "full_all":
        await run_full_all(cases, max_turns=max_turns)
    elif mode == "both":
        map_results = await run_map_only(cases)
        failed_maps = [r for r in map_results if not r.get("ok")]
        if len(failed_maps) > 1 and not os.environ.get("SIM_FORCE_ALL"):
            print("[RobustSim] More than one map failed; stopping before full interviews.", flush=True)
            return
        await run_full_all(cases, max_turns=max_turns)
    else:
        raise RuntimeError("SIM_MODE must be one of: map_only, full_gate, full_all, both")


if __name__ == "__main__":
    asyncio.run(main())
