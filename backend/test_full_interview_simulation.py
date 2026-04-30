"""
Adversarial end-to-end interview simulation for the standalone Antigravity repo.

This is intentionally deeper than a smoke test:
- prepares an interview map from a full resume
- starts the interview from the prepared session
- sends partial transcript snapshots and final turns
- optionally exercises TTS on served questions
- ends the interview and pulls state/report/telemetry
- grades the run against product expectations

Run with:
  python -m backend.test_full_interview_simulation

Optional:
  python -m backend.test_full_interview_simulation --resume-file /path/to/resume.txt
  python -m backend.test_full_interview_simulation --scenario honest_boundary
  python -m backend.test_full_interview_simulation --skip-tts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE = os.environ.get("ANTIGRAVITY_SIM_BASE", "http://127.0.0.1:8000/api")

DEFAULT_RESUME = """
(+86) 15914122353 | 123040005@link.cuhk.edu.cn | 2001 Longxiang Boulevard, Longgang District, Shenzhen

The Chinese University of Hong Kong, Shenzhen (B.Eng. in Computer Science and Engineering) | 2023-2027
- Full Admission Excellence Scholarship - School of Data Science, CUHK-SZ
- 2024 Guangdong Government Outstanding International Student Scholarship
- 2025 Leading Academic Peer Advisor @ School of Data Science, CUHK-SZ

TECHNICAL SKILLS:
Top Skills: Python, C++, SQL Hybrid, RISC-V, Git, Docker, Google GCP, AWS Deployment, Linux, Deployment Testing
AI Skills: OpenClaw, Google ADK, Agent System design, Prompt-Engineering, Fine-tuning, RL, Model Inference, TinyML

EXPERIENCE:
AI Agent Development Engineer [Intern] : AIGC Algorithms - Wondershare Filmora @ Shenzhen | Jan 2026 - Present
- Architected and prototyped an end-to-end agent-based AIGC video generation and editing pipeline on Google ADK by implementing a unified seed-based generation workflow. Leveraged seed diffusion for regeneration with targeted prompt steering to deliver real-time AI editing functionality with character identity, scene geometry, and narrative coherence across edits. Reduced API token overhead by about 40 percent and per-generation cost by about 35 percent versus full Veo-3 resampling.
- Engineered an ML feature-map control system that translates orthogonal control axes (exposure, lighting tone, motion energy, transition speed, color palette, etc.) into pixel-level semantic generation instructions for Google Veo 3 seed-regeneration, enabling targeted edits to specific video frame segments without disturbing the video manifold.
- Built a semantic UI-to-latent translation interface that maps intuitive editing controls (sliders, palettes, tone adjustments) to diffusion conditioning prompt signals enabling non-technical users to use AI editing features to perform controlled semantic AI-video regeneration for multimodal alignment across video, music, and transitions while minimizing token-heavy LLM orchestration.

AI Engineer Intern : AI Model Developer - Optek Microelectronics @ Shenzhen, China | 2025 Jul - Sep
- Engineered a full-stack TinyML Audio Classification Pipeline by integrating MediaPipe Audio for real-time feature extraction (log-Mel spectrograms, MFCCs), TensorFlow Lite-Micro INT8 for quantized inference, and Edge Impulse for SDK deployment, achieving 95 percent plus classification accuracy on AudioSet and UrbanSound8K.
- Optimized and delivered a custom classifier for a 700 MHz DSP plus 16 MB NPU in the proprietary XNCC development environment, accomplishing less than 10 ms latency, 200 KB runtime footprint, and 4x model compression via INT8 quantization and pruning for scalable low-power AI application.

Research Assistant : HKU-COLUMBIA-ALIBABA-CUHKSZ @ BIRD Vision | 2025 Jun - Sep
- Reconstructed an advanced multi-modal benchmark framework that pioneered the BIRD-SQL dataset by integrating vision plus NLP annotation for advanced database queries and designing evaluation protocols to identify model failure points.
- Designed relational DB schemas, and created complex hybrid SQL queries to introduce reasoning challenges for vision-language models. Primarily involved in robust benchmark construction, using schema-aware prompt engineering, OCR validation, and annotating complex multimodal inputs.

Research Assistant - AI Model Benchmark Optimization @ CUHKSZ Natural Language Processing Group | 2024
- Assisted to automate critical data-driven Python pipelines (Pandas, NumPy, Scikit-learn) for hallucination detection and data grounding index, reducing factual deviation by 31 percent in benchmarked outputs. Engineered systematic benchmarking for 200 plus LLM response pairs, boosting truth-layer accuracy by 25 percent.

Research Assistant - Algorithmic Performance Optimization | 2024
- Worked on a novel script framework to quantitatively optimize algorithmic augmented data retrieval (RAG) performance of an ALLaVA vision-language model. Improved algorithmic data retrieval by 46 percent and optimized workflow operations of a 1.3M-sampled labeled evaluation database.
""".strip()


@dataclass
class TurnPlan:
    label: str
    final_answer: str
    partials: list[str] = field(default_factory=list)
    expectation: str = ""


@dataclass
class Scenario:
    slug: str
    title: str
    description: str
    target_role: str
    years_experience: str
    turns: list[TurnPlan]
    expected_positive_routes: list[str] = field(default_factory=list)
    expected_negative_routes: list[str] = field(default_factory=list)
    expect_partial_activity: bool = False
    expect_tts_cache_hits: bool = True
    expect_challenge_by_end: bool = False
    expect_honesty_respect: bool = False


SCENARIOS: list[Scenario] = [
    Scenario(
        slug="story_depth",
        title="Story First Then Depth",
        description=(
            "Starts with a real Filmora implementation story, then narrows into mechanism, drift, "
            "and measurement. This checks whether the map opens directionally and then deepens "
            "without collapsing into generic fallback."
        ),
        target_role="AI Agent Development Engineer",
        years_experience="0-1",
        expected_positive_routes=[
            "trajectory_map_followup",
            "bank_followup_fast",
            "attack_probe",
        ],
        expected_negative_routes=["sprint_fallback"],
        expect_partial_activity=True,
        turns=[
            TurnPlan(
                label="filmora_story",
                partials=[
                    "At Filmora I worked on the seed-based AIGC editing flow. The user would start from a seed clip, then regenerate only selected segments instead of resampling the whole video.",
                    "My part was mainly the orchestration path around seed regeneration, prompt steering, and the control mapping that let the product ask for lighting or motion changes without destroying identity.",
                ],
                final_answer=(
                    "The most concrete piece I owned was the seed-based regeneration workflow on top of Google ADK. "
                    "We were trying to preserve character identity and scene geometry while still letting users push "
                    "lighting, motion energy, or transition speed. The first hard choice was separating user-facing "
                    "controls from the latent instructions, because if we passed the UI signal too literally the edits "
                    "looked unstable across chained regenerations."
                ),
                expectation="Should stay on the Wondershare focus and respond with a guided technical follow-up.",
            ),
            TurnPlan(
                label="filmora_failure_mode",
                final_answer=(
                    "The biggest failure mode was seed drift after multiple edit hops. By the second or third targeted "
                    "regeneration, identity would start to wobble or the scene framing would slide, so we had to log "
                    "those failure cases and rebalance the control axes rather than just push stronger prompts."
                ),
                expectation="Should probe mechanism or debugging, not bail into a generic sprint question.",
            ),
            TurnPlan(
                label="filmora_measurement",
                final_answer=(
                    "The 35 to 40 percent savings claim came from internal logs comparing seed-based regeneration "
                    "against full Veo-3 style resampling on the same edit intents. It was directional product evidence, "
                    "not a formal academic experiment, but it was enough to influence the workflow choice."
                ),
                expectation="Should either validate the measurement or press on rigor and limits.",
            ),
        ],
    ),
    Scenario(
        slug="honest_boundary",
        title="Honest Boundary Handling",
        description=(
            "Candidate is specific but openly marks ownership boundaries. This checks whether the system respects "
            "honesty and keeps probing usefully without immediately turning adversarial."
        ),
        target_role="AI Engineer Intern",
        years_experience="0-1",
        expected_positive_routes=[
            "trajectory_map_honesty_probe",
            "trajectory_map_followup",
            "bank_followup_fast",
            "clarification_fast",
        ],
        expected_negative_routes=["discrepancy_challenge"],
        expect_honesty_respect=True,
        turns=[
            TurnPlan(
                label="tinyml_story",
                final_answer=(
                    "On the TinyML pipeline I owned feature extraction, quantization experiments, and on-device "
                    "validation. The deployment constraint was the 700 MHz DSP plus 16 MB NPU, so most of the work "
                    "was around keeping the runtime footprint small while still preserving useful audio features."
                ),
                expectation="Should go deeper on implementation or tradeoffs inside the candidate's stated boundary.",
            ),
            TurnPlan(
                label="honest_gap",
                final_answer=(
                    "I did not write the low-level DSP kernel from scratch, and I was not the person scheduling vendor "
                    "ops on the NPU. My boundary was the feature path, quantization behavior, and validating that the "
                    "model still held up once it was actually running on device."
                ),
                expectation="Should recognize honest scoping and probe adjacent understanding rather than accuse.",
            ),
            TurnPlan(
                label="boundary_admission",
                final_answer=(
                    "If you want the proprietary XNCC scheduling details, that is where my knowledge boundary starts. "
                    "What I can explain clearly is what changed when the quantized model degraded and how we verified "
                    "whether the issue came from features versus inference."
                ),
                expectation="Should either pivot productively or ask for the explainable part, not recycle a generic attack.",
            ),
        ],
    ),
    Scenario(
        slug="conflict_pressure",
        title="Overclaim Then Correction",
        description=(
            "Candidate starts with a broad ownership claim, then partially walks it back. This tests discrepancy "
            "pressure, contradiction handling, and whether the runtime sharpens appropriately by the end."
        ),
        target_role="AI Agent Development Engineer",
        years_experience="0-1",
        expected_positive_routes=[
            "trajectory_map_challenge",
            "discrepancy_challenge",
            "attack_probe",
            "trajectory_map_followup",
        ],
        expected_negative_routes=[],
        expect_challenge_by_end=True,
        turns=[
            TurnPlan(
                label="broad_claim",
                partials=[
                    "At Filmora I more or less built the whole AI editing stack end to end, from the orchestration path down to the control logic and much of the evaluation loop.",
                ],
                final_answer=(
                    "I pretty much built the whole Filmora stack end to end. I was involved in the agent workflow, "
                    "the control mapping, the UI semantics, and a lot of the quality logic around regeneration."
                ),
                expectation="Should tolerate the first broad answer but start narrowing toward concrete ownership.",
            ),
            TurnPlan(
                label="claim_walkback",
                final_answer=(
                    "To be precise, the ADK scaffolding and some of the video generation backend already existed. "
                    "My most concrete ownership was the unified seed-based regeneration workflow and the mapping layer "
                    "that translated product controls into prompt or conditioning signals."
                ),
                expectation="Should now notice the tension and ask for concrete evidence or exact boundaries.",
            ),
            TurnPlan(
                label="measurement_softening",
                final_answer=(
                    "The cost and token numbers were from internal product logging, not a formal offline benchmark, "
                    "and they were strongest on the targeted edit cases rather than every generation path."
                ),
                expectation="Should challenge rigor, edge conditions, or the confidence level of the claim.",
            ),
        ],
    ),
    Scenario(
        slug="topic_switch_minimalism",
        title="Topic Switch And Minimal Answers",
        description=(
            "Candidate switches topics and then answers tersely. This checks bridge behavior, short-answer rescue, "
            "partial transcript handling, and whether the runtime maintains focus continuity."
        ),
        target_role="AI/ML Engineer",
        years_experience="0-1",
        expected_positive_routes=[
            "trajectory_map_bridge",
            "trajectory_map_opener",
            "trajectory_map_short_answer_rescue",
            "bank_followup_fast",
            "clarification_fast",
        ],
        expected_negative_routes=["sprint_fallback"],
        expect_partial_activity=True,
        turns=[
            TurnPlan(
                label="bird_sql_story",
                partials=[
                    "On the BIRD-SQL benchmark work I was constructing harder multimodal cases where OCR noise and schema complexity made the SQL generation task much more realistic.",
                    "A lot of the work was around designing evaluation surfaces and annotating the cases so we could actually tell whether a model failed because of vision grounding or database reasoning.",
                ],
                final_answer=(
                    "The BIRD-SQL work was less about model training and more about building the benchmark surface well. "
                    "I was creating schema-aware examples, hybrid SQL cases, and evaluation logic that exposed where a "
                    "vision-language model was actually failing."
                ),
                expectation="Should ask a grounded benchmark follow-up first.",
            ),
            TurnPlan(
                label="topic_switch",
                final_answer="Also the audio classifier had tighter constraints. That one was really about memory budget.",
                expectation="Should either bridge to the TinyML focus cleanly or rescue the abrupt switch intelligently.",
            ),
            TurnPlan(
                label="minimal_short",
                final_answer="Latency.",
                expectation="Should rescue the short answer instead of dropping to generic fallback.",
            ),
            TurnPlan(
                label="minimal_honest",
                final_answer="I did not own the vendor runtime piece.",
                expectation="Should preserve focus and keep the probe useful after a terse honesty answer.",
            ),
        ],
    ),
]


def _normalize_label(label: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", label.lower()) if len(token) > 2]


def _jaccard(a: str, b: str) -> float:
    ta = set(_normalize_label(a))
    tb = set(_normalize_label(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _duplicate_focus_pairs(labels: list[str]) -> list[tuple[str, str, float]]:
    pairs: list[tuple[str, str, float]] = []
    for i, left in enumerate(labels):
        for right in labels[i + 1 :]:
            score = _jaccard(left, right)
            if score >= 0.55:
                pairs.append((left, right, round(score, 3)))
    return pairs


async def _json_get(client: httpx.AsyncClient, url: str) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = await client.get(url)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    response.raise_for_status()
    return response.json(), elapsed_ms


async def _json_post(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = await client.post(url, json=payload)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    response.raise_for_status()
    return response.json(), elapsed_ms


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    response = await client.request(method, url, json=json_payload)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text}
    return response.status_code, body, elapsed_ms


async def _tts_probe(
    client: httpx.AsyncClient,
    base_url: str,
    session_id: str,
    text: str,
    *,
    settle_s: float = 1.1,
) -> dict[str, Any]:
    await asyncio.sleep(settle_s)
    started = time.perf_counter()
    response = await client.post(
        f"{base_url}/tts",
        json={"text": text, "session_id": session_id, "use_filler": False},
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    response.raise_for_status()
    return {
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
        "provider": response.headers.get("X-TTS-Provider", ""),
        "source": response.headers.get("X-TTS-Source", ""),
        "media_type": response.headers.get("content-type", ""),
        "audio_bytes": len(response.content),
    }


def _load_resume(path: str | None) -> str:
    if not path:
        return DEFAULT_RESUME
    return Path(path).read_text(encoding="utf-8").strip()


def _scenario_lookup(slug: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.slug == slug:
            return scenario
    raise KeyError(slug)


def _summarize_trace_activity(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    partial_events = [
        event for event in trace_events if "partial" in str(event.get("event", ""))
    ]
    speculative_events = [
        event for event in trace_events if "speculative" in str(event.get("event", ""))
    ]
    stale_partials = [
        event for event in trace_events if event.get("event") == "partial_snapshot_dropped_stale"
    ]
    return {
        "partial_event_count": len(partial_events),
        "speculative_event_count": len(speculative_events),
        "stale_partial_count": len(stale_partials),
    }


def _evaluate_scenario(
    scenario: Scenario,
    *,
    prepare_ms: float,
    start_ms: float,
    focus_labels: list[str],
    map_validation: dict[str, Any],
    turn_results: list[dict[str, Any]],
    telemetry: dict[str, Any],
    tts_results: list[dict[str, Any]],
    trace_activity: dict[str, Any],
) -> dict[str, Any]:
    passes: list[str] = []
    warnings: list[str] = []
    failures: list[str] = []

    if prepare_ms <= 150000:
        passes.append(f"map prep under target: {prepare_ms:.0f}ms")
    else:
        warnings.append(f"map prep slow: {prepare_ms:.0f}ms")

    if start_ms <= 5000:
        passes.append(f"prepared launch quick: {start_ms:.0f}ms")
    else:
        warnings.append(f"prepared launch slower than expected: {start_ms:.0f}ms")

    if int(map_validation.get("priority_llm_ready_count", 0) or 0) >= 2:
        passes.append("top 2 priority tracks marked ready")
    else:
        failures.append("top 2 priority tracks were not both ready")

    dupes = _duplicate_focus_pairs(focus_labels)
    if dupes:
        warnings.append(
            "possible duplicate focus areas: "
            + "; ".join(f"{left} <> {right} ({score})" for left, right, score in dupes[:3])
        )
    else:
        passes.append("no strong duplicate focus labels detected")

    served_routes = [str(item.get("route_kind", "") or "") for item in turn_results]
    if any(route == "sprint_fallback" for route in served_routes[1:]):
        failures.append("generic sprint_fallback appeared after the interview was already underway")
    else:
        passes.append("no sprint_fallback after the first answered turn")

    positive_hit = any(route in set(scenario.expected_positive_routes) for route in served_routes)
    if positive_hit:
        passes.append("saw at least one route kind aligned with the scenario's intent")
    else:
        warnings.append(
            "did not observe any of the preferred route kinds: "
            + ", ".join(scenario.expected_positive_routes)
        )

    negative_hit = any(route in set(scenario.expected_negative_routes) for route in served_routes)
    if negative_hit:
        warnings.append(
            "observed a discouraged route kind: "
            + ", ".join(route for route in served_routes if route in set(scenario.expected_negative_routes))
        )

    drift_events = [
        item
        for item in turn_results
        if item.get("focus_drift")
    ]
    if drift_events:
        warnings.append(f"focus drift detected on {len(drift_events)} turn(s)")
    else:
        passes.append("focus continuity looked stable turn-to-turn")

    if scenario.expect_partial_activity:
        if trace_activity["partial_event_count"] > 0 and trace_activity["speculative_event_count"] > 0:
            passes.append("partial transcript path produced speculative activity")
        else:
            warnings.append("partial transcript path did not show clear speculative activity")

    if scenario.expect_tts_cache_hits:
        prepped_hits = sum(1 for item in tts_results if item.get("source") == "prepped")
        if prepped_hits:
            passes.append(f"TTS pre-generation was reused {prepped_hits} time(s)")
        else:
            warnings.append("no TTS prepped cache hits were observed")

    if scenario.expect_honesty_respect:
        if any(route == "discrepancy_challenge" for route in served_routes[:2]):
            failures.append("honest boundary case escalated into discrepancy challenge too early")
        else:
            passes.append("honesty case avoided early discrepancy challenge")

    if scenario.expect_challenge_by_end:
        if any(route in {"discrepancy_challenge", "attack_probe", "trajectory_map_challenge"} for route in served_routes):
            passes.append("conflict case eventually triggered pressure or challenge")
        else:
            warnings.append("conflict case never escalated into a strong challenge route")

    telemetry_issues = telemetry.get("issues") or []
    if telemetry_issues:
        warnings.append(f"telemetry captured {len(telemetry_issues)} issue-ish event(s)")
    else:
        passes.append("telemetry summary had no issue-level events")

    return {
        "passes": passes,
        "warnings": warnings,
        "failures": failures,
        "served_routes": served_routes,
    }


async def run_scenario(
    scenario: Scenario,
    *,
    base_url: str,
    resume: str,
    include_tts: bool,
    prepare_retries: int,
) -> dict[str, Any]:
    timeout = httpx.Timeout(connect=10.0, read=360.0, write=60.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        prepare_payload = {
            "resume": resume,
            "target_role": scenario.target_role,
            "years_experience": scenario.years_experience,
            "github_links": [],
        }
        prepare_attempts: list[dict[str, Any]] = []
        prepared: dict[str, Any] = {}
        prepare_ms = 0.0
        prepare_ok = False
        for attempt in range(1, max(prepare_retries, 1) + 1):
            try:
                prepared, prepare_ms = await _json_post(client, f"{base_url}/prepare_interview_map", prepare_payload)
                prepare_attempts.append({"attempt": attempt, "status_code": 200, "elapsed_ms": prepare_ms})
                prepare_ok = True
                break
            except httpx.HTTPStatusError as exc:
                body = {}
                try:
                    body = exc.response.json()
                except Exception:
                    body = {"raw_text": exc.response.text}
                prepare_attempts.append(
                    {
                        "attempt": attempt,
                        "status_code": exc.response.status_code,
                        "elapsed_ms": round(exc.response.elapsed.total_seconds() * 1000, 3)
                        if exc.response.elapsed
                        else None,
                        "detail": body,
                    }
                )
            except httpx.ReadTimeout:
                prepare_attempts.append(
                    {
                        "attempt": attempt,
                        "status_code": 599,
                        "elapsed_ms": None,
                        "detail": {"error": "read_timeout"},
                    }
                )
            if attempt < max(prepare_retries, 1):
                await asyncio.sleep(2.0)

        if not prepare_ok:
            return {
                "scenario": asdict(scenario),
                "prepare_ms": None,
                "start_ms": None,
                "end_ms": None,
                "prepared_session_id": "",
                "session_id": "",
                "map_status": "failed",
                "map_validation": {},
                "focus_preview": [],
                "focus_labels": [],
                "opening_question": "",
                "turns": [],
                "tts_results": [],
                "end_response": {},
                "report": {},
                "telemetry": {},
                "trace_activity": {},
                "state_snapshot": {},
                "prepare_attempts": prepare_attempts,
                "evaluation": {
                    "passes": [],
                    "warnings": [
                        f"prepare_interview_map failed after {len(prepare_attempts)} attempt(s)"
                    ],
                    "failures": [
                        f"startup blocked before interview launch: {prepare_attempts[-1].get('detail')}"
                    ],
                    "served_routes": [],
                },
            }

        prepared_session_id = prepared["session_id"]

        status, _ = await _json_get(client, f"{base_url}/interview_map_status/{prepared_session_id}")
        start_payload = {"prepared_session_id": prepared_session_id}
        start_status_code, started, start_ms = await _request_json(
            client,
            "POST",
            f"{base_url}/start_interview",
            json_payload=start_payload,
        )
        if start_status_code >= 400:
            return {
                "scenario": asdict(scenario),
                "prepare_ms": prepare_ms,
                "start_ms": start_ms,
                "end_ms": None,
                "prepared_session_id": prepared_session_id,
                "session_id": "",
                "map_status": prepared.get("map_status"),
                "map_validation": prepared.get("map_validation", {}),
                "focus_preview": prepared.get("trajectory_focus_preview", []),
                "focus_labels": [
                    str(item.get("label", "") or "")
                    for item in prepared.get("trajectory_focus_preview", [])
                ],
                "opening_question": "",
                "turns": [],
                "tts_results": [],
                "end_response": {},
                "report": {},
                "telemetry": {},
                "trace_activity": {},
                "state_snapshot": {},
                "prepare_attempts": prepare_attempts,
                "evaluation": {
                    "passes": [],
                    "warnings": [],
                    "failures": [
                        f"start_interview failed with {start_status_code}: {started}"
                    ],
                    "served_routes": [],
                },
            }
        session_id = started["session_id"]

        state_after_start, _ = await _json_get(client, f"{base_url}/state/{session_id}")
        focus_preview = started.get("trajectory_focus_preview", []) or []
        focus_labels = [str(item.get("label", "") or "") for item in focus_preview]

        tts_results: list[dict[str, Any]] = []
        if include_tts and started.get("opening_question"):
            tts_info = await _tts_probe(client, base_url, session_id, started["opening_question"])
            tts_results.append({"turn": 0, "question": started["opening_question"][:120], **tts_info})

        turn_results: list[dict[str, Any]] = []
        for idx, turn in enumerate(scenario.turns, start=1):
            turn_id = f"{scenario.slug}-t{idx}"
            for seq, partial in enumerate(turn.partials, start=1):
                _, partial_ms = await _json_post(
                    client,
                    f"{base_url}/partial_transcript",
                    {
                        "session_id": session_id,
                        "transcript": partial,
                        "turn_id": turn_id,
                        "is_final": False,
                        "snapshot_seq": seq,
                        "entities": [],
                    },
                )
                await asyncio.sleep(1.1 if seq == len(turn.partials) else 0.25)
            if turn.partials:
                state_with_partials, _ = await _json_get(client, f"{base_url}/state/{session_id}")
                speculative_cache = state_with_partials.get("speculative_cache", {}) or {}
            else:
                speculative_cache = {}

            processed, process_ms = await _json_post(
                client,
                f"{base_url}/process_turn",
                {
                    "session_id": session_id,
                    "transcript": turn.final_answer,
                    "turn_id": turn_id,
                    "entities": [],
                },
            )
            state_after_turn, _ = await _json_get(client, f"{base_url}/state/{session_id}")
            history = state_after_turn.get("history", []) or []
            last_turn = history[-1] if history else {}
            active_packet = state_after_turn.get("active_question_packet") or {}
            route_kind = str(processed.get("route_kind", processed.get("served_route_kind", "")) or "")
            history_focus_key = str(last_turn.get("focus_key", "") or "")
            packet_focus_key = str(active_packet.get("focus_key", "") or "")
            focus_drift = bool(
                history_focus_key
                and packet_focus_key
                and route_kind != "trajectory_map_bridge"
                and history_focus_key != packet_focus_key
            )

            turn_record = {
                "turn_number": idx,
                "turn_label": turn.label,
                "expectation": turn.expectation,
                "route_kind": route_kind,
                "response": str(processed.get("response", "") or ""),
                "process_ms": process_ms,
                "question_count": processed.get("question_count"),
                "history_focus_key": history_focus_key,
                "history_focus_label": str(last_turn.get("focus_label", "") or ""),
                "packet_focus_key": packet_focus_key,
                "packet_focus_label": str(active_packet.get("focus_label", "") or ""),
                "focus_drift": focus_drift,
                "speculative_ready_before_final": bool(speculative_cache.get("best_ready_question")),
            }
            turn_results.append(turn_record)

            if include_tts and turn_record["response"]:
                tts_info = await _tts_probe(client, base_url, session_id, turn_record["response"])
                tts_results.append({"turn": idx, "question": turn_record["response"][:120], **tts_info})

        ended, end_ms = await _json_post(client, f"{base_url}/end_interview/{session_id}", {})
        report, _ = await _json_get(client, f"{base_url}/report/{session_id}")
        telemetry, _ = await _json_get(client, f"{base_url}/telemetry/{session_id}?limit=250")
        trace_path = telemetry.get("trace_path", "")
        trace_events: list[dict[str, Any]] = []
        if trace_path and Path(trace_path).exists():
            for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    trace_events.append(parsed)

        trace_activity = _summarize_trace_activity(trace_events)
        evaluation = _evaluate_scenario(
            scenario,
            prepare_ms=prepare_ms,
            start_ms=start_ms,
            focus_labels=focus_labels,
            map_validation=prepared.get("map_validation", {}),
            turn_results=turn_results,
            telemetry=telemetry,
            tts_results=tts_results,
            trace_activity=trace_activity,
        )

        return {
            "scenario": asdict(scenario),
            "prepare_ms": prepare_ms,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "prepared_session_id": prepared_session_id,
            "session_id": session_id,
            "map_status": prepared.get("map_status"),
            "map_validation": prepared.get("map_validation", {}),
            "focus_preview": focus_preview,
            "focus_labels": focus_labels,
            "opening_question": started.get("opening_question", ""),
            "turns": turn_results,
            "tts_results": tts_results,
            "end_response": ended,
            "report": report,
            "telemetry": telemetry,
            "trace_activity": trace_activity,
            "prepare_attempts": prepare_attempts,
            "evaluation": evaluation,
            "state_snapshot": {
                "question_count": state_after_start.get("question_count", 0),
                "current_sprint": state_after_start.get("current_sprint", 0),
            },
        }


def _print_scenario_summary(result: dict[str, Any]) -> None:
    scenario = result["scenario"]
    evaluation = result["evaluation"]
    prepare_ms = result.get("prepare_ms")
    start_ms = result.get("start_ms")
    end_ms = result.get("end_ms")
    print("\n" + "=" * 84)
    print(f"{scenario['title']} [{scenario['slug']}]")
    print("=" * 84)
    print(f"Session: {result['session_id']}")
    prep_label = f"{prepare_ms:.0f}ms" if isinstance(prepare_ms, (int, float)) else "n/a"
    start_label = f"{start_ms:.0f}ms" if isinstance(start_ms, (int, float)) else "n/a"
    end_label = f"{end_ms:.0f}ms" if isinstance(end_ms, (int, float)) else "n/a"
    print(f"Map prep: {prep_label} | Start: {start_label} | End: {end_label}")
    print(f"Map status: {result['map_status']}")
    print(
        "Priority ready: "
        f"{result['map_validation'].get('priority_llm_ready_count')} "
        f"/ {result['map_validation'].get('priority_focus_count')}"
    )
    if result.get("prepare_attempts"):
        print("Prepare attempts:")
        for attempt in result["prepare_attempts"]:
            print(
                f"  - attempt {attempt.get('attempt')}: status={attempt.get('status_code')} "
                f"elapsed={attempt.get('elapsed_ms')}"
            )
    print("Focus labels:")
    for label in result["focus_labels"]:
        print(f"  - {label}")
    print("Route sequence:")
    for turn in result["turns"]:
        print(
            f"  T{turn['turn_number']}: {turn['route_kind']} "
            f"(process={turn['process_ms']:.0f}ms, focus={turn['history_focus_label'] or turn['history_focus_key']})"
        )
    if result["tts_results"]:
        sources = {}
        for item in result["tts_results"]:
            key = f"{item.get('provider')}/{item.get('source')}"
            sources[key] = sources.get(key, 0) + 1
        print("TTS probes:")
        for key, count in sorted(sources.items()):
            print(f"  - {key}: {count}")
    print("Passes:")
    for line in evaluation["passes"]:
        print(f"  - {line}")
    if evaluation["warnings"]:
        print("Warnings:")
        for line in evaluation["warnings"]:
            print(f"  - {line}")
    if evaluation["failures"]:
        print("Failures:")
        for line in evaluation["failures"]:
            print(f"  - {line}")


def _build_overall_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    prep_times = [float(item["prepare_ms"]) for item in results if isinstance(item.get("prepare_ms"), (int, float))]
    start_times = [float(item["start_ms"]) for item in results if isinstance(item.get("start_ms"), (int, float))]
    turn_times = [
        float(turn["process_ms"])
        for item in results
        for turn in item["turns"]
    ]
    warnings = sum(len(item["evaluation"]["warnings"]) for item in results)
    failures = sum(len(item["evaluation"]["failures"]) for item in results)
    route_counts: dict[str, int] = {}
    for item in results:
        for route in item["evaluation"]["served_routes"]:
            route_counts[route] = route_counts.get(route, 0) + 1
    return {
        "scenario_count": len(results),
        "avg_prepare_ms": round(statistics.mean(prep_times), 3) if prep_times else 0.0,
        "max_prepare_ms": round(max(prep_times), 3) if prep_times else 0.0,
        "avg_start_ms": round(statistics.mean(start_times), 3) if start_times else 0.0,
        "avg_turn_ms": round(statistics.mean(turn_times), 3) if turn_times else 0.0,
        "max_turn_ms": round(max(turn_times), 3) if turn_times else 0.0,
        "warnings": warnings,
        "failures": failures,
        "route_counts": route_counts,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run an adversarial end-to-end Antigravity interview simulation.")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="API base URL, default: %(default)s")
    parser.add_argument("--resume-file", default="", help="Optional path to a resume text file")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario slug(s) to run")
    parser.add_argument("--skip-tts", action="store_true", help="Skip /tts probes")
    parser.add_argument("--prepare-retries", type=int, default=2, help="How many times to retry map prep before marking startup as failed")
    args = parser.parse_args()

    resume = _load_resume(args.resume_file or None)
    if args.scenario:
        scenarios = [_scenario_lookup(slug) for slug in args.scenario]
    else:
        scenarios = SCENARIOS

    timeout = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        health, _ = await _json_get(client, f"{args.base_url}/tts_health")
        print("Backend reachable. TTS health:")
        print(json.dumps(health, indent=2))

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        print("\nRunning scenario:", scenario.slug)
        result = await run_scenario(
            scenario,
            base_url=args.base_url,
            resume=resume,
            include_tts=not args.skip_tts,
            prepare_retries=args.prepare_retries,
        )
        results.append(result)
        _print_scenario_summary(result)

    overall = _build_overall_summary(results)
    print("\n" + "#" * 84)
    print("OVERALL SUMMARY")
    print("#" * 84)
    print(json.dumps(overall, indent=2))

    output_dir = Path(__file__).resolve().parent / "runtime" / "simulation_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"full-e2e-simulation-{timestamp}.json"
    output_path.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "resume_chars": len(resume),
                "overall": overall,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved report to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
