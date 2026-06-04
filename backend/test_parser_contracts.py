"""
Contract checks for brittle parser/data-boundary behavior.

Run with:
  PYTHONPATH=. python3 backend/test_parser_contracts.py
"""

from __future__ import annotations

import asyncio

from backend.agents.application_agent import ApplicationAgent
from backend.agents.concept_agent import ConceptAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.followup_agent import (
    _clean_question_output,
    _extract_question_from_serialized_payload,
    _finalize_question_output,
)
from backend.agents.weakness_agent import WeaknessAgent
from backend.models.coverage_map import AnswerCoverageMap
from backend.services.interview_map import _coerce_critic_payload, _parse_dimension_output
from backend.state.candidate_state import CandidateState, check_topic_fatigue, get_topic_fatigue_ratio
from backend.state.interview_agenda import InterviewAgendaState


class _FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def call(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if isinstance(self.result, list):
            index = min(len(self.calls) - 1, len(self.result) - 1)
            return self.result[index]
        return self.result


def _assert_raises(fn, expected: str = "") -> None:
    try:
        fn()
    except Exception as exc:
        if expected and expected not in str(exc):
            raise AssertionError(f"Expected {expected!r} in {exc!r}") from exc
        return
    raise AssertionError("Expected function to raise.")


async def _assert_async_raises(coro, expected: str = "") -> None:
    try:
        await coro
    except Exception as exc:
        if expected and expected not in str(exc):
            raise AssertionError(f"Expected {expected!r} in {exc!r}") from exc
        return
    raise AssertionError("Expected coroutine to raise.")


def test_followup_question_payload_extraction() -> None:
    fenced = '```json\n{"question": "What moved conversion from 27% to 42%?"}\n```'
    assert _extract_question_from_serialized_payload(fenced) == "What moved conversion from 27% to 42%?"
    assert _clean_question_output(fenced) == "What moved conversion from 27% to 42%?"

    _assert_raises(
        lambda: _finalize_question_output("```json\n{\"note\": \"no actual question\"}\n```", "fallback disabled"),
        "invalid question output",
    )


def test_map_track_parser_repairs_truncated_object_without_fragment_parsing() -> None:
    raw = """
```json
{
  "opener": "At Daily Mantra, conversion moved from 27% to 42% — what changed in user behavior?",
  "dimensions": [
    {
      "id": "causal_lift",
      "label": "Causal lift",
      "resume_anchor": "trial conversion improvement",
      "surface": "What moved that lift?",
      "mechanism": "How did you separate pricing-period effects from feature or cohort effects?",
      "boundary": "What guardrail would make you reverse the change?",
      "signal_weight": 2.5
    },
    {
      "id": "denominator",
      "label": "Denominator",
      "resume_anchor": "trial conversion improvement",
      "surface": "Which users were in the denominator?",
      "mechanism": "How did you handle users who never saw the offer?",
      "boundary": "What denominator bug would fake the lift?",
      "signal_weight": 2.0
    },
    {
      "id": "guardrails",
      "label": "Guardrails",
      "resume_anchor": "trial conversion improvement",
      "surface": "What guardrails did you track?",
      "mechanism": "How did refund, churn, or complaint signals change the readout?",
      "boundary": "What would make the conversion win bad for the business?",
      "signal_weight": 2.0
    }
  ],
  "recovery": {
    "short_answer": "Which part of the conversion lift are you referring to?",
    "honest_gap": "Fair. Which part of the trial-period change did you personally analyze?",
    "claim_conflict": "Which part did you own versus inherit from the team?",
    "metric_risk": "What was the baseline and denominator?",
    "overclaim_risk": "What evidence proves the lift was causal?",
    "bridge": "Switching to dashboard automation — how did that decision loop differ?"
  }
"""
    parsed = _parse_dimension_output(raw, {"focus_key": "conversion", "label": "Conversion"})
    assert parsed["opener"].startswith("At Daily Mantra")
    assert len(parsed["dimensions"]) >= 2


def test_map_track_parser_backfills_legacy_recovery_from_ladder() -> None:
    raw = {
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": "When you moved the trial from 7 days to 1 day, were you improving paid conversion or testing urgency?",
                "signal_goal": "Frame the decision.",
                "expected_space": ["conversion", "trial quality", "urgency"],
                "follow_up_if_shallow": "Which of those was the main business reason?",
                "follow_up_if_strong": "What tradeoff made the choice risky?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "That 42% conversion number — what counted as conversion, and which users were in the denominator?",
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
                "main_question": "Which part are you most confident about: conversion improved, quality held, or the trial change caused the lift?",
                "signal_goal": "Synthesize confidence.",
                "expected_space": ["conversion", "quality", "causality"],
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
        ],
        "opener": "When you moved the trial from 7 days to 1 day, what decision were you trying to make?",
        "dimensions": [
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
        ],
        "recovery": {},
        "candidate_q4_options": ["What behavior changed after the trial became shorter?"],
    }
    parsed = _parse_dimension_output(raw, {"focus_key": "conversion", "label": "Conversion"})
    assert parsed["recovery"]["short_answer"] == "What did you personally calculate?", parsed["recovery"]
    assert parsed["recovery"]["metric_risk"].startswith("That 42% conversion"), parsed["recovery"]

    two_dim_raw = dict(raw)
    two_dim_raw["dimensions"] = raw["dimensions"][:2]
    two_dim_parsed = _parse_dimension_output(two_dim_raw, {"focus_key": "conversion", "label": "Conversion"})
    assert len(two_dim_parsed["dimensions"]) == 2, two_dim_parsed


def test_map_track_parser_prefers_ladder_over_weak_legacy_aliases() -> None:
    raw = {
        "opener": "When you shortened the trial, what decision were you trying to make?",
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": "When you shortened the trial, were you trying to improve conversion, reduce low-intent trials, test urgency, or something else?",
                "signal_goal": "Understand decision framing.",
                "expected_space": "conversion, trial quality, urgency, retention",
                "follow_up_if_shallow": "What guardrail would tell you the shorter trial was hurting user quality?",
                "follow_up_if_strong": "If refunds rose while conversion improved, how would you decide whether to keep the change?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "Which users were in the conversion denominator, and which users were excluded from that number?",
                "signal_goal": "Clarify denominator.",
                "expected_space": ["trial starters", "eligible users", "excluded users"],
                "follow_up_if_shallow": "What denominator bug would make the lift look better than it was?",
                "follow_up_if_strong": "How would you report the metric if eligibility changed mid-test?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": "How did you separate trial-length impact from other launches happening in the same window?",
                "signal_goal": "Explore causal reasoning.",
                "expected_space": ["feature exposure", "cohorts", "guardrails"],
                "follow_up_if_shallow": "Which comparison would reduce the biggest attribution doubt?",
                "follow_up_if_strong": "What would make you stop claiming causality?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "pressure",
                "main_question": "If conversion improved but cancellations increased, what would make you roll the change back?",
                "signal_goal": "Pressure-test guardrails.",
                "expected_space": ["refunds", "cancellations", "retention"],
                "follow_up_if_shallow": "What threshold would make the business tradeoff unacceptable?",
                "follow_up_if_strong": "How would you explain the decision to leadership?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "synthesize",
                "main_question": "Which part are you most confident about: conversion improved, guardrails stayed safe, your change caused it, or something else?",
                "signal_goal": "Synthesize certainty.",
                "expected_space": ["confidence", "uncertainty", "scope"],
                "follow_up_if_shallow": "Which part would you phrase more carefully on the resume?",
                "follow_up_if_strong": "What is still the biggest uncertainty?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
            {
                "posture": "recover",
                "main_question": "If you do not remember the exact setup, what part of the metric are you still confident about?",
                "signal_goal": "Recover honest signal.",
                "expected_space": ["knowns", "unknowns"],
                "follow_up_if_shallow": "Which detail would you verify before defending this claim?",
                "follow_up_if_strong": "What source would you check first?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
        ],
        "dimensions": [
            {"id": "bad_weight", "label": "Bad", "resume_anchor": "trial", "surface": "denominator", "mechanism": "cohort", "boundary": "rollback", "signal_weight": "high"},
            {"id": "bad_short", "label": "Bad2", "resume_anchor": "trial", "surface": "guardrail", "mechanism": "refunds", "boundary": "risk", "signal_weight": "medium"},
        ],
        "recovery": {},
        "candidate_q4_options": [],
    }
    parsed = _parse_dimension_output(raw, {
        "focus_key": "trial_conversion",
        "label": "Trial Conversion",
        "anchor_context": "trial conversion improvement",
    })
    assert parsed["question_ladder"], parsed
    assert len(parsed["dimensions"]) >= 2, parsed["dimensions"]
    assert all("?" in dim["surface"] for dim in parsed["dimensions"][:2]), parsed["dimensions"]
    assert parsed["dimensions"][0]["signal_weight"] >= 1.0, parsed["dimensions"]


def test_map_track_parser_coerces_recovery_object_fields() -> None:
    raw = {
        "opener": "When you shortened the trial, what decision were you trying to make?",
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": "When you shortened the trial, were you mainly improving conversion, reducing low-intent trials, testing urgency, or something else?",
                "signal_goal": "Frame decision.",
                "expected_space": ["conversion", "trial quality", "urgency"],
                "follow_up_if_shallow": "What was the main business reason?",
                "follow_up_if_strong": "Which guardrail made the decision risky?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "Which users were in the conversion denominator, and which users were excluded?",
                "signal_goal": "Clarify denominator.",
                "expected_space": ["eligible users", "trial starters"],
                "follow_up_if_shallow": "What denominator bug would inflate the lift?",
                "follow_up_if_strong": "How would you report the metric if eligibility changed?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": "What user behavior changed after the trial became shorter, beyond users paying earlier?",
                "signal_goal": "Explore behavior.",
                "expected_space": ["activation", "refunds", "retention"],
                "follow_up_if_shallow": "What signal showed user quality did not drop?",
                "follow_up_if_strong": "Which cohort check gave you confidence?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "pressure",
                "main_question": "If conversion improved but refunds increased, what would make you rethink the one-day trial?",
                "signal_goal": "Pressure guardrail.",
                "expected_space": ["refunds", "retention", "threshold"],
                "follow_up_if_shallow": "Which guardrail would matter most?",
                "follow_up_if_strong": "What threshold would trigger rollback?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
        ],
        "dimensions": [
            {
                "id": "denominator",
                "label": "Denominator",
                "resume_anchor": "trial conversion",
                "surface": "Which users were in the conversion denominator?",
                "mechanism": "How did you handle users who never reached the trial offer?",
                "boundary": "What denominator mistake would make the lift look fake?",
                "signal_weight": 3,
            },
            {
                "id": "guardrails",
                "label": "Guardrails",
                "resume_anchor": "trial conversion",
                "surface": "Which refund or cancellation guardrail mattered most?",
                "mechanism": "How did that guardrail affect the read of the lift?",
                "boundary": "What movement would make the business result unacceptable?",
                "signal_weight": 2.5,
            },
        ],
        "recovery": {
            "short_answer": {"question": "Which part of the trial change did you personally analyze?"},
            "honest_gap": {"main_question": "What part would you verify before defending the claim?"},
        },
        "candidate_q4_options": [{"question": "What behavior changed after the trial became shorter?"}],
    }
    parsed = _parse_dimension_output(raw, {"focus_key": "trial_conversion", "label": "Trial Conversion"})
    assert parsed["recovery"]["short_answer"].startswith("Which part"), parsed["recovery"]
    assert parsed["candidate_q4_options"] == ["What behavior changed after the trial became shorter?"], parsed["candidate_q4_options"]


def test_map_track_parser_coerces_ladder_text_shape_drift_before_schema_validation() -> None:
    raw = {
        "opener": {"question": "At QuickKart, seller activation moved from 22% to 38%; what decision were you trying to make?"},
        "dimensions": [
            {
                "id": "activation_denominator",
                "label": "Activation denominator",
                "resume_anchor": "seller activation improvement",
                "surface": {"question": "Which sellers were included in the 22% to 38% activation denominator?"},
                "mechanism": "How did you separate checklist, support-call, and KYC UX effects?",
                "boundary": "What result would make you stop claiming product lift?",
                "signal_weight": "high",
            },
            {
                "id": "support_confound",
                "label": "Support-call confound",
                "resume_anchor": "rollout overlapped with support calls",
                "surface": "How did support-call exposure change during the rollout?",
                "mechanism": {"text": "What segment would you check first to separate support from product changes?"},
                "boundary": "What evidence would make the activation readout too noisy?",
                "signal_weight": 2.5,
            },
        ],
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": {"question": "When seller activation moved from 22% to 38%, were you testing checklist quality, KYC friction, support nudges, or something else?"},
                "signal_goal": "Frame the decision.",
                "expected_space": [{"label": "checklist"}, {"text": "KYC friction"}, "support calls"],
                "follow_up_if_shallow": {"question": "Which of those was the main bet?"},
                "follow_up_if_strong": ["What tradeoff made that bet risky?"],
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "That activation number — what counted as activated, and which sellers were in the denominator?",
                "signal_goal": "Clarify denominator.",
                "expected_space": ["eligible sellers", "KYC blocked sellers", "time window"],
                "follow_up_if_shallow": "What was excluded from that denominator?",
                "follow_up_if_strong": "Which denominator would make the lift look weaker?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": "What seller behavior changed after checklist, support, and KYC changes shipped?",
                "signal_goal": "Explore behavior change.",
                "expected_space": ["listing approval", "first order", "support SLA"],
                "follow_up_if_shallow": "What signal showed seller quality did not drop?",
                "follow_up_if_strong": "What segment reduced the biggest attribution doubt?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "pressure",
                "main_question": "If activation improved but refunds rose, would you keep the marketplace change or rethink it?",
                "signal_goal": "Pressure-test guardrail judgment.",
                "expected_space": ["refunds", "buyer conversion", "seller quality"],
                "follow_up_if_shallow": {"text": "Which guardrail would matter most?"},
                "follow_up_if_strong": {"value": "What threshold would trigger rollback?"},
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "synthesize",
                "main_question": "Given the overlapping changes, what part of the activation lift would you claim carefully?",
                "signal_goal": "Synthesize confidence and limits.",
                "expected_space": ["claim boundary", "support confound", "product signal"],
                "follow_up_if_shallow": "What evidence supports that careful claim?",
                "follow_up_if_strong": "What extra split would make the claim stronger?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "recover",
                "main_question": "If you do not remember the exact split, what part of the activation analysis are you still confident about?",
                "signal_goal": "Recover honest evidence.",
                "expected_space": ["knowns", "unknowns"],
                "follow_up_if_shallow": "Which detail would you verify first?",
                "follow_up_if_strong": "Where would you look for that evidence?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
        ],
        "recovery": {},
        "candidate_q4_options": [],
    }

    parsed = _parse_dimension_output(raw, {
        "focus_key": "seller_activation_attribution",
        "label": "Seller Activation Attribution",
        "anchor_context": "QuickKart seller activation 22% to 38%",
    })

    assert parsed["question_ladder"][0]["main_question"].startswith("When seller activation")
    assert parsed["question_ladder"][0]["follow_up_if_shallow"] == "Which of those was the main bet?"
    assert parsed["question_ladder"][0]["follow_up_if_strong"] == "What tradeoff made that bet risky?"
    assert parsed["question_ladder"][0]["expected_space"] == ["checklist", "KYC friction", "support calls"]
    assert parsed["dimensions"][0]["signal_weight"] == 3.0


def test_map_track_parser_rejects_unsupported_hidden_internals() -> None:
    raw = {
        "opener": "When you built the video workflow, what part of the state layer did you personally own?",
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": "When you built the video workflow, were you mainly preserving scene state, improving review flow, reducing latency, or something else?",
                "signal_goal": "Frame scope.",
                "expected_space": ["scene state", "review flow", "latency"],
                "follow_up_if_shallow": "Which part did you personally handle?",
                "follow_up_if_strong": "What made the workflow hard to keep reliable?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "What data did you store between edits to preserve scene state across the workflow?",
                "signal_goal": "Clarify state.",
                "expected_space": ["seed", "prompt version", "scene state"],
                "follow_up_if_shallow": "Where did that state live?",
                "follow_up_if_strong": "How did you detect stale state?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": "How did you keep character identity stable without manually editing the latent space?",
                "signal_goal": "Explore unsupported internals.",
                "expected_space": ["identity", "state"],
                "follow_up_if_shallow": "What did you actually control?",
                "follow_up_if_strong": "What changed across edits?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "pressure",
                "main_question": "If repeated edits changed the background, how would you decide whether the issue came from state handling or model behavior?",
                "signal_goal": "Pressure-test failure modes.",
                "expected_space": ["state", "model behavior"],
                "follow_up_if_shallow": "What log would you check first?",
                "follow_up_if_strong": "How would you reproduce it?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "synthesize",
                "main_question": "Which part are you most confident about: state tracking, review labeling, regression checks, or something else?",
                "signal_goal": "Synthesize confidence.",
                "expected_space": ["state", "review", "regression"],
                "follow_up_if_shallow": "Which part had the clearest evidence?",
                "follow_up_if_strong": "What would you improve next?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
            {
                "posture": "recover",
                "main_question": "If you did not own the model internals, what part of the workflow did you directly build?",
                "signal_goal": "Recover ownership.",
                "expected_space": ["scope", "owned work"],
                "follow_up_if_shallow": "What did your code change?",
                "follow_up_if_strong": "Where did your ownership stop?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
        ],
        "dimensions": [
            {
                "id": "state",
                "label": "State",
                "resume_anchor": "video workflow",
                "surface": "What state did you store between edits?",
                "mechanism": "How did that state affect the next generation call?",
                "boundary": "What would break if the stored state became stale?",
                "signal_weight": 3,
            },
            {
                "id": "failure",
                "label": "Failure",
                "resume_anchor": "regression checks",
                "surface": "Which failure did your regression checks catch?",
                "mechanism": "How did you reproduce the failure across multiple edits?",
                "boundary": "What failure would make you stop trusting the workflow?",
                "signal_weight": 2.5,
            },
        ],
        "recovery": {},
        "candidate_q4_options": [],
    }
    awaitable = lambda: _parse_dimension_output(raw, {
        "focus_key": "aigc_workflow",
        "label": "AIGC Workflow",
        "resume_snippets": ["Built Google ADK and Veo 3 workflow preserving seed lineage and scene state."],
    })
    _assert_raises(awaitable, "unsupported hidden implementation assumptions")

    engine_param_raw = dict(raw)
    engine_param_raw["question_ladder"] = [dict(item) for item in raw["question_ladder"]]
    engine_param_raw["question_ladder"][2] = dict(engine_param_raw["question_ladder"][2])
    engine_param_raw["question_ladder"][2]["main_question"] = (
        "Which UI controls translated directly into Veo 3 engine parameters, and which needed agent interpretation?"
    )
    engine_param_raw["dimensions"] = [dict(item) for item in raw["dimensions"]]
    engine_param_raw["dimensions"][0] = dict(engine_param_raw["dimensions"][0])
    engine_param_raw["dimensions"][0]["mechanism"] = "How did direct engine parameters change between edits?"
    _assert_raises(
        lambda: _parse_dimension_output(engine_param_raw, {
            "focus_key": "aigc_workflow",
            "label": "AIGC Workflow",
            "resume_snippets": ["Built Google ADK and Veo 3 workflow preserving seed lineage and scene state."],
        }),
        "unsupported hidden implementation assumptions",
    )

    embedding_raw = dict(raw)
    embedding_raw["question_ladder"] = [dict(item) for item in raw["question_ladder"]]
    embedding_raw["question_ladder"][2] = dict(embedding_raw["question_ladder"][2])
    embedding_raw["question_ladder"][2]["main_question"] = (
        "How did your state drift checks detect identity preservation over repeated edits — did you calculate embedding distance from facial crops, use CLIP scores, or something else?"
    )
    _assert_raises(
        lambda: _parse_dimension_output(embedding_raw, {
            "focus_key": "aigc_workflow",
            "label": "AIGC Workflow",
            "resume_snippets": ["Built Google ADK and Veo 3 workflow preserving seed lineage and scene state."],
        }),
        "unsupported hidden implementation assumptions",
    )

    tinyml_raw = {
        "opener": "When you optimized the TinyML audio pipeline, what part of the inference loop were you trying to improve first?",
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": "In the TinyML audio pipeline, were you mainly reducing feature extraction time, model invocation time, memory copies, or something else?",
                "signal_goal": "Frame the optimization target.",
                "expected_space": ["feature extraction", "model invocation", "memory copies"],
                "follow_up_if_shallow": "Which part of the loop did you measure first?",
                "follow_up_if_strong": "What made that part the best place to optimize?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "What did the MediaPipe audio feature extractor output before the INT8 classifier consumed it?",
                "signal_goal": "Clarify the supported feature pipeline.",
                "expected_space": ["audio features", "classifier input", "pipeline boundary"],
                "follow_up_if_shallow": "What format reached the classifier?",
                "follow_up_if_strong": "How did that shape your memory budget?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": "How did you check whether model invocation or feature extraction was the bigger bottleneck?",
                "signal_goal": "Explore profiling method.",
                "expected_space": ["profiling", "loop timing", "bottleneck"],
                "follow_up_if_shallow": "What timing did you log?",
                "follow_up_if_strong": "What changed after you removed redundant copies?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
        ],
        "dimensions": [
            {
                "id": "feature_extraction",
                "label": "Feature Extraction Bottleneck",
                "resume_anchor": "Profiled feature extraction and model invocation.",
                "surface": "How did you separate feature extraction time from model invocation time?",
                "mechanism": "What did the feature extractor produce for the INT8 classifier?",
                "boundary": "What signal told you feature extraction was no longer the bottleneck?",
                "signal_weight": 3,
            },
            {
                "id": "memory_copies",
                "label": "Memory Copy Reduction",
                "resume_anchor": "Removed redundant copies and bounded the audio windowing pipeline.",
                "surface": "Where were redundant copies happening in the loop?",
                "mechanism": "How did bounding the audio window reduce memory pressure?",
                "boundary": "What failure would make the bounded window too aggressive?",
                "signal_weight": 2.5,
            },
        ],
        "recovery": {"short_answer": "Which part of the loop did you personally profile first?"},
        "candidate_q4_options": [],
    }
    parsed = _parse_dimension_output(tinyml_raw, {
        "focus_key": "tinyml_audio_pipeline",
        "label": "TinyML Audio Pipeline",
        "resume_snippets": [
            "Integrated MediaPipe Audio features with a TensorFlow Lite Micro INT8 classifier.",
            "Profiled feature extraction, model invocation, memory footprint, and confidence behavior under noisy microphones.",
        ],
    })
    assert parsed["question_ladder"], parsed
    assert len(parsed["dimensions"]) == 2, parsed["dimensions"]


def test_critic_payload_repair_and_shape_notes() -> None:
    repaired, notes = _coerce_critic_payload(
        '{"ready": true, "overall_score": 8.1, "issues": ["minor"], "repair_targets": []'
    )
    assert repaired["ready"] is True
    assert repaired["overall_score"] == 8.1
    assert notes == []

    unrecoverable, notes = _coerce_critic_payload(["bad", "shape"])
    assert unrecoverable["_critic_unrecoverable_shape"] is True
    assert notes


async def test_agent_shape_validation() -> None:
    concept = ConceptAgent.__new__(ConceptAgent)
    concept.llm = _FakeLLM({"concepts": "SQL"})
    await _assert_async_raises(concept.extract("SQL and dashboards"), "concepts")

    weakness = WeaknessAgent.__new__(WeaknessAgent)
    weakness.llm = _FakeLLM({
        "weakness": "vague",
        "type": "made_up_type",
        "severity": "high",
        "probe_direction": "clarification",
        "continue_probing": True,
    })
    normalized_weakness = await weakness.detect("Q?", "A")
    assert normalized_weakness["type"] == "ambiguous_but_promising", normalized_weakness
    assert "_normalization_warning" in normalized_weakness, normalized_weakness

    discrepancy = DiscrepancyAgent.__new__(DiscrepancyAgent)
    discrepancy.llm = _FakeLLM({
        "conflict_level": "maybe",
        "description": "unclear",
        "severity": "high",
    })
    await _assert_async_raises(discrepancy.check("resume", "answer"), "conflict_level")

    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": "Imagine your PM asks you to debug a conversion drop; where do you start?",
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "denominator",
                "label": "Denominator",
                "description": "Tests metric population clarity",
                "expected_approaches": "cohort analysis",
                "surfacing_question": "What population changed?",
                "weight": 2.0,
            }
        ],
    })
    await _assert_async_raises(
        application.generate("trial conversion lift", "product analytics", "Product Analyst", "1-3", []),
        "expected_approaches",
    )


async def test_application_question_repair_shortens_voice_overload() -> None:
    long_question = (
        "Imagine your PM comes tomorrow with a new onboarding funnel where attribution is delayed, "
        "trial eligibility changes by market, refunds are logged in a separate billing table, and the "
        "experiment runs while another activation feature is shipping; how would you decide whether the "
        "conversion lift came from the shorter trial, the new acquisition mix, the feature launch, or something else?"
    )
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": long_question,
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "denominator",
                "label": "Denominator",
                "description": "Tests metric population clarity",
                "expected_approaches": ["separate eligibility", "cohort denominator"],
                "surfacing_question": "What population changed in the denominator?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "guardrail",
                "label": "Guardrail",
                "description": "Tests whether user quality stayed safe",
                "expected_approaches": ["refunds", "retention"],
                "surfacing_question": "Which guardrail would show the conversion gain was unhealthy?",
                "surface_kind": "depth",
                "depth_eligible": True,
                "weight": 2.0,
            }
        ],
    })
    application.repair_llm = _FakeLLM({
        "question": (
            "Suppose trial eligibility and acquisition mix both changed during onboarding; "
            "how would you decide whether the conversion lift came from the shorter trial or something else?"
        )
    })
    application.verify_llm = _FakeLLM({
        "accepted": True,
        "reason": "preserves role relevance and answer space",
        "risk_flags": [],
    })
    application.last_repair_verification = {"repair_attempted": False}

    coverage = await application.generate(
        "trial conversion lift from reducing trial length",
        "product analytics",
        "Product Analyst",
        "1-3",
        [],
    )

    assert len(coverage.application_question) < len(long_question), coverage.application_question
    assert coverage.application_question.endswith("?"), coverage.application_question
    assert "something else" in coverage.application_question, coverage.application_question
    assert application.last_repair_verification["repair_accepted"] is True


async def test_application_question_repair_retries_after_verifier_rejection() -> None:
    long_question = (
        "Imagine your PM asks you to evaluate a new checkout experiment where the coupon flow changes, "
        "payment retries are enabled, app version adoption is uneven, and refunds arrive late in a separate "
        "billing table; how would you decide whether success improved because you personally rebuilt the "
        "retry implementation, because coupons changed, because acquisition quality changed, or because of "
        "something else?"
    )
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": long_question,
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "counterfactual",
                "label": "Counterfactual",
                "description": "Tests separation of overlapping checkout changes",
                "expected_approaches": ["cohort split", "guardrail review"],
                "surfacing_question": "What changed besides the retry flow?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "guardrail",
                "label": "Guardrail",
                "description": "Tests whether success was healthy",
                "expected_approaches": ["refunds", "failed payments"],
                "surfacing_question": "What guardrail would make the checkout improvement risky?",
                "surface_kind": "depth",
                "depth_eligible": True,
                "weight": 2.0,
            }
        ],
    })
    application.repair_llm = _FakeLLM([
        {
            "question": (
                "If checkout success improves after you personally rebuilt retry logic and coupons also changed, "
                "how would you prove which one caused it?"
            )
        },
        {
            "question": (
                "Suppose checkout success improves while retry logic, coupons, and acquisition mix all changed; "
                "how would you decide what moved the metric, or something else?"
            )
        },
    ])
    application.verify_llm = _FakeLLM([
        {
            "accepted": False,
            "reason": "adds a personal ownership claim",
            "risk_flags": ["unsupported_ownership"],
        },
        {
            "accepted": True,
            "reason": "preserves the overlapping-change assessment without unsupported ownership",
            "risk_flags": [],
        },
    ])
    application.last_repair_verification = {"repair_attempted": False}

    coverage = await application.generate(
        "checkout retry and coupon experiment analysis",
        "product analytics",
        "Product Analyst",
        "1-3",
        [],
    )

    assert "personally rebuilt" not in coverage.application_question
    assert "something else" in coverage.application_question
    assert application.last_repair_verification["repair_accepted"] is True
    assert len(application.last_repair_verification["attempts"]) == 2
    assert sum(1 for d in coverage.dimensions if d.depth_eligible) == 1


async def test_application_question_rejected_repairs_do_not_keep_overlong_original() -> None:
    long_question = (
        "Suppose you're building a multi-step AI agent where each step calls a different model, "
        "including a planner, an image generator, a code executor, a human-review console, and a "
        "versioned telemetry database, and you need consistency constraints to flow across all of "
        "those steps while retries, partial outputs, and latency spikes happen under load; how would "
        "you design the state handoff between every agent step, and what breaks first when the "
        "pipeline scales?"
    )
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": long_question,
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "state_handoff",
                "label": "State handoff",
                "description": "Tests state handoff reasoning.",
                "expected_approaches": ["state contract", "retry boundary"],
                "surfacing_question": "What state contract would you define first?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "failure_mode",
                "label": "Failure mode",
                "description": "Tests failure-mode reasoning.",
                "expected_approaches": ["partial output", "traceability"],
                "surfacing_question": "What failure mode would you test first?",
                "surface_kind": "depth",
                "depth_eligible": True,
                "weight": 2.0,
            },
        ],
    })
    application.repair_llm = _FakeLLM([
        {"question": long_question},
        {"question": "When state moves between planner, generator, and executor, do you pass latent vectors, config bundles, or trace IDs?"},
    ])
    application.verify_llm = _FakeLLM({})
    application.last_repair_verification = {"repair_attempted": False}

    await _assert_async_raises(
        application.generate(
            "agent workflow state control and review telemetry",
            "AI workflow",
            "AI Engineer",
            "1-3",
            [],
        ),
        "not safe to retain",
    )
    assert application.last_repair_verification["fallback_to_original"] is False
    assert "original_overlong" in application.last_repair_verification["final_risk_flags"]


async def test_application_question_uses_secondary_repair_model_before_fail_closed() -> None:
    long_question = (
        "Suppose seller activation improves after a checklist launch, support-call staffing changes, "
        "KYC UX updates, dashboard instrumentation changes, and a marketplace policy shift all happen "
        "inside the same month; how would you design the full attribution workflow, which tables would "
        "you query, what exact joins would you use, what guardrails would you monitor, and how would "
        "you explain every confidence limit to leadership?"
    )
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": long_question,
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "attribution_split",
                "label": "Attribution split",
                "description": "Tests attribution reasoning.",
                "expected_approaches": ["exposure split", "support-call confound"],
                "surfacing_question": "Which split would you check first?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "guardrail",
                "label": "Guardrail",
                "description": "Tests guardrail judgment.",
                "expected_approaches": ["seller quality", "refunds"],
                "surfacing_question": "What guardrail would make the lift dangerous?",
                "surface_kind": "depth",
                "depth_eligible": True,
                "weight": 2.0,
            },
        ],
    })
    application.repair_llm = _FakeLLM([
        {"question": long_question},
        {"question": "Which part are you most confident in?"},
    ])
    application.repair_fallback_llms = [{
        "label": "fallback_gpt54_mini",
        "model": "openai/gpt-5.4-mini",
        "llm": _FakeLLM({
            "question": (
                "Suppose seller activation improved while checklist changes and support calls both changed; "
                "which split would you check first to decide whether product work, support effort, or something else moved the result?"
            )
        }),
    }]
    application.verify_llm = _FakeLLM({
        "accepted": True,
        "reason": "fallback preserves attribution intent and answer space",
        "risk_flags": [],
    })
    application.last_repair_verification = {"repair_attempted": False}

    coverage = await application.generate(
        "seller activation improved while checklist, support calls, and KYC UX changed together",
        "marketplace analytics",
        "Product Analytics Engineer",
        "2-4",
        [],
    )

    assert "support calls both changed" in coverage.application_question
    assert application.last_repair_verification["repair_accepted"] is True
    assert application.last_repair_verification["final_repair_label"] == "fallback_gpt54_mini"
    assert application.last_repair_verification["attempts"][-1]["repair_model"] == "openai/gpt-5.4-mini"
    assert len(application.last_repair_verification["attempts"]) == 3


async def test_application_question_rejects_hidden_internal_assumptions() -> None:
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": "Suppose the video workflow drifts; how would you debug whether the identity embeddings or latent space caused it?",
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "state",
                "label": "State",
                "description": "Tests state tracking",
                "expected_approaches": ["state logs", "prompt versions"],
                "surfacing_question": "What workflow state would you check first?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "review",
                "label": "Review",
                "description": "Tests evaluation process",
                "expected_approaches": ["review labels", "regression examples"],
                "surfacing_question": "What review signal would tell you the workflow drifted?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
        ],
    })
    application.repair_llm = _FakeLLM({})
    application.verify_llm = _FakeLLM({})
    application.last_repair_verification = {"repair_attempted": False}

    await _assert_async_raises(
        application.generate(
            "video workflow with review labels and scene state",
            "AI workflow",
            "AI Engineer",
            "1-3",
            [],
        ),
        "hidden_implementation_assumption",
    )


async def test_application_question_allows_supported_schema_context() -> None:
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": (
            "Suppose seller activation drops after your dbt models change; would you first check "
            "database schema, join grain, support-call exposure, or something else?"
        ),
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "join_grain",
                "label": "Join grain",
                "description": "Tests whether the candidate can separate event and operational grains.",
                "expected_approaches": ["seller grain", "KYC status grain"],
                "surfacing_question": "What grain mismatch would make the activation drop look larger than it was?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "operational_confound",
                "label": "Operational confound",
                "description": "Tests whether support-call exposure is separated from product changes.",
                "expected_approaches": ["support-call split", "KYC UX split"],
                "surfacing_question": "How would you separate product changes from support-call exposure?",
                "surface_kind": "depth",
                "depth_eligible": True,
                "weight": 2.0,
            },
        ],
    })
    application.repair_llm = _FakeLLM({})
    application.verify_llm = _FakeLLM({})
    application.last_repair_verification = {"repair_attempted": False}

    coverage = await application.generate(
        "seller onboarding taxonomy and activation analysis",
        "BigQuery dbt marketplace analytics with seller events",
        "Product Analytics Engineer",
        "2.8",
        [
            "Created BigQuery/dbt models joining seller events, support tickets, KYC status, and listing approvals",
            "Owned metric definitions and analysis; platform engineering owned event SDK and dbt deployment",
        ],
    )

    assert coverage.application_question.endswith("?")
    assert "database schema" in coverage.application_question
    assert application.last_repair_verification["repair_attempted"] is False


async def test_application_question_repairs_hidden_internal_assumption_when_possible() -> None:
    application = ApplicationAgent.__new__(ApplicationAgent)
    application.llm = _FakeLLM({
        "application_question": (
            "Suppose a seller onboarding workflow drifts; how would you debug whether embeddings "
            "or latent space caused the activation issue?"
        ),
        "coverage_confidence": "0.8",
        "dimensions": [
            {
                "id": "workflow_signal",
                "label": "Workflow signal",
                "description": "Tests operating signal selection.",
                "expected_approaches": ["event chain", "support-call exposure"],
                "surfacing_question": "What workflow signal would you check first?",
                "surface_kind": "breadth",
                "depth_eligible": False,
                "weight": 2.0,
            },
            {
                "id": "guardrail",
                "label": "Guardrail",
                "description": "Tests whether quality guardrails are preserved.",
                "expected_approaches": ["refunds", "support SLA"],
                "surfacing_question": "Which guardrail would show the activation improvement was unhealthy?",
                "surface_kind": "depth",
                "depth_eligible": True,
                "weight": 2.0,
            },
        ],
    })
    application.repair_llm = _FakeLLM({
        "question": (
            "Suppose seller onboarding starts drifting after a workflow change; would you first check "
            "the event chain, support-call exposure, KYC status, or something else?"
        )
    })
    application.verify_llm = _FakeLLM({
        "accepted": True,
        "reason": "removes unsupported internal assumptions while preserving the assessment intent",
        "risk_flags": [],
    })
    application.last_repair_verification = {"repair_attempted": False}

    coverage = await application.generate(
        "seller onboarding workflow and activation analysis",
        "marketplace analytics",
        "Product Analytics Engineer",
        "2.8",
        ["Built seller onboarding event taxonomy and activation dashboard"],
    )

    assert "embedding" not in coverage.application_question.lower()
    assert "latent" not in coverage.application_question.lower()
    assert "something else" in coverage.application_question
    assert application.last_repair_verification["repair_accepted"] is True


def test_coverage_map_from_dict_is_tolerant_but_not_char_splitting() -> None:
    coverage = AnswerCoverageMap.from_dict({
        "application_question": "Q",
        "implementation_anchor": "A",
        "coverage_confidence": "bad-float",
        "total_weight": "bad-float",
        "grounding_needed": True,
        "grounding_question": "Were you handling the workflow layer, specialized internals, or something else?",
        "max_depth_level": "4",
        "depth_allowed_terms": ["embeddings", "", "state store"],
        "dimensions": [
            {
                "id": "d1",
                "expected_approaches": "not a list",
                "weight": "bad-float",
            }
        ],
    })
    assert coverage.coverage_confidence == 0.0
    assert coverage.total_weight == 1.5
    assert coverage.dimensions[0].expected_approaches == []
    assert coverage.dimensions[0].weight == 1.5
    assert coverage.grounding_needed is True
    assert coverage.grounding_question.startswith("Were you handling"), coverage.grounding_question
    assert coverage.max_depth_level == 4
    assert coverage.depth_allowed_terms == ["embeddings", "state store"]
    roundtrip = coverage.to_dict()
    assert roundtrip["grounding_needed"] is True
    assert roundtrip["max_depth_level"] == 4
    assert roundtrip["depth_allowed_terms"] == ["embeddings", "state store"]


def test_state_parsers_do_not_crash_on_bad_saved_shapes() -> None:
    agenda = InterviewAgendaState.from_dict({
        "phase": "unknown",
        "secondary_focus_queue": "not-a-list",
        "turns_by_focus": "not-a-dict",
        "phase_turn_count": "bad-int",
    })
    assert agenda.phase == "warm_open"
    assert agenda.secondary_focus_queue == []
    assert agenda.turns_by_focus == {}
    assert agenda.phase_turn_count == 0

    candidate = CandidateState.from_dict({
        "disengagement_level": "bad-float",
        "topic_fatigue": "not-a-dict",
        "topic_fatigue_threshold": "bad-int",
    })
    assert candidate.disengagement_level == 0.0
    assert candidate.topic_fatigue == {}
    assert candidate.topic_fatigue_threshold == 4
    state = {"candidate_state": {"topic_fatigue": {"focus": "bad-int"}, "topic_fatigue_threshold": "bad-int"}}
    assert check_topic_fatigue(state, "focus") is False
    assert get_topic_fatigue_ratio({"candidate_state": {"topic_fatigue": {"a": "bad", "b": 2}}}, "b") == 1.0


async def main() -> None:
    test_followup_question_payload_extraction()
    test_map_track_parser_repairs_truncated_object_without_fragment_parsing()
    test_map_track_parser_backfills_legacy_recovery_from_ladder()
    test_map_track_parser_prefers_ladder_over_weak_legacy_aliases()
    test_map_track_parser_coerces_recovery_object_fields()
    test_map_track_parser_coerces_ladder_text_shape_drift_before_schema_validation()
    test_map_track_parser_rejects_unsupported_hidden_internals()
    test_critic_payload_repair_and_shape_notes()
    await test_agent_shape_validation()
    await test_application_question_repair_shortens_voice_overload()
    await test_application_question_repair_retries_after_verifier_rejection()
    await test_application_question_rejected_repairs_do_not_keep_overlong_original()
    await test_application_question_uses_secondary_repair_model_before_fail_closed()
    await test_application_question_rejects_hidden_internal_assumptions()
    await test_application_question_allows_supported_schema_context()
    await test_application_question_repairs_hidden_internal_assumption_when_possible()
    test_coverage_map_from_dict_is_tolerant_but_not_char_splitting()
    test_state_parsers_do_not_crash_on_bad_saved_shapes()
    print("parser contract checks passed")


if __name__ == "__main__":
    asyncio.run(main())
