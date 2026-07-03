from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import MethodType

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.application_agent import ApplicationAgent
from backend.agents.followup_agent import FollowUpAgent
from backend.agents.question_repair_agent import QuestionRepairAgent
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension


class _FakeRepairLLM:
    def __init__(self, payload: dict, *, model: str = "gpt-oss-120b", backend: str = "cerebras_direct") -> None:
        self.payload = payload
        self.model = model
        self.backend = backend

    async def call(self, **_kwargs):
        return self.payload


class _FakeLLM:
    def __init__(self, question: str) -> None:
        self.question = question

    async def call(self, **_kwargs):
        return {"question": self.question}


class _FakeRepairAgent:
    def __init__(self, repaired_question: str) -> None:
        self.repaired_question = repaired_question
        self.calls: list[dict] = []

    async def repair(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "attempted": True,
            "accepted": True,
            "question": self.repaired_question,
            "repair_model": "gpt-oss-120b",
            "repair_backend": "cerebras_direct",
        }


async def test_question_repair_agent_prefers_shorter_cerebras_rewrite() -> None:
    agent = QuestionRepairAgent.__new__(QuestionRepairAgent)
    agent.llm = _FakeRepairLLM(
        {
            "question": (
                "Suppose the same retention model now has delayed refunds and a new paywall. "
                "What comparison would tell you whether conversion improved for the right reason?"
            )
        }
    )

    original = (
        "Suppose the same retention model now has delayed refunds, a new paywall, "
        "mixed acquisition channels, executive pressure, mobile rollout timing drift, "
        "partial instrumentation coverage, and conflicting conversion dashboards. "
        "What would you compare first to decide whether the launch actually worked, "
        "which segment changed for the right reason, and whether the dashboard lift "
        "came from behavior or from measurement drift?"
    )
    repaired = await agent.repair(
        question=original,
        route_kind="application_transfer",
        posture="application_transfer",
        turn_number=6,
        target_role="Product Analyst",
        signal_goal="Preserve the transfer scenario while shortening the spoken question.",
        anchor_context="Retention model, refunds, and paywall analysis.",
    )

    assert repaired["attempted"] is True
    assert repaired["accepted"] is True
    assert repaired["repair_backend"] == "cerebras_direct"
    assert repaired["repair_model"] == "gpt-oss-120b"
    assert len(repaired["question"].split()) < len(original.split())


async def test_question_repair_agent_repairs_coverage_depth_at_lower_threshold() -> None:
    agent = QuestionRepairAgent.__new__(QuestionRepairAgent)
    agent.llm = _FakeRepairLLM(
        {
            "question": (
                "What mechanism would you inspect first to tell whether behavior changed "
                "or the measurement frame drifted, or something else?"
            )
        }
    )

    original = (
        "Once that rollout starts drifting across channels, refund timing, event lag, delayed eligibility windows, "
        "and inconsistent cohort joins, what mechanism would you inspect first to decide whether the metric moved "
        "because of behavior change or because the measurement frame quietly changed underneath you?"
    )
    repaired = await agent.repair(
        question=original,
        route_kind="coverage_depth_probe",
        posture="coverage_depth_probe",
        turn_number=9,
        surface_kind="depth",
        expected_space=["event lag check", "cohort join audit"],
        target_role="Product Analyst",
        focus_label="Activation measurement",
        sub_focus_label="Measurement drift",
        signal_goal="Keep the coverage depth probe short and speakable without losing the target mechanism.",
        anchor_context="Activation analysis and rollout measurement.",
    )

    assert repaired["attempted"] is True
    assert repaired["accepted"] is True
    assert len(repaired["question"].split()) <= 30


async def test_question_repair_agent_adds_escape_hatch_for_transfer_lanes() -> None:
    agent = QuestionRepairAgent.__new__(QuestionRepairAgent)
    agent.llm = _FakeRepairLLM(
        {
            "question": (
                "What would you compare first to decide if the launch worked, which segment changed "
                "for the right reason, and whether the lift was behavior or measurement drift?"
            )
        }
    )

    original = (
        "Suppose the same retention model now has delayed refunds, a new paywall, mixed acquisition channels, "
        "executive pressure, mobile rollout timing drift, partial instrumentation coverage, and conflicting "
        "conversion dashboards. What would you compare first to decide whether the launch actually worked, "
        "which segment changed for the right reason, and whether the dashboard lift came from behavior or "
        "from measurement drift?"
    )
    repaired = await agent.repair(
        question=original,
        route_kind="application_transfer",
        posture="application_transfer",
        turn_number=6,
        target_role="Product Analyst",
        signal_goal="Preserve the transfer scenario while shortening the spoken question.",
        anchor_context="Retention model, refunds, and paywall analysis.",
    )

    assert repaired["attempted"] is True
    assert repaired["accepted"] is True
    assert "or something else?" in repaired["question"]


async def test_application_transfer_uses_shared_cerebras_repair_agent_first() -> None:
    agent = ApplicationAgent.__new__(ApplicationAgent)
    agent.last_repair_verification = {"repair_attempted": False}
    agent.question_repair_agent = _FakeRepairAgent(
        "Suppose the same onboarding analysis now covers a new paywall rollout. What comparison would tell you whether conversion improved for the right reason?"
    )

    async def verify(self, **kwargs):
        repaired = kwargs.get("repaired_question", "")
        return {
            "accepted": "paywall rollout" in repaired,
            "reason": "shared repair accepted",
            "risk_flags": [],
            "source": "test",
        }

    agent._verify_repaired_application_question = MethodType(verify, agent)
    agent._normalize_repaired_question = MethodType(lambda self, question: question, agent)

    repaired = await agent._repair_spoken_application_question(
        question=" ".join(["This application transfer question is intentionally overlong and awkward"] * 16) + "?",
        target_role="Product Analyst",
        implementation_anchor="Onboarding analysis and paywall experimentation.",
    )

    assert "paywall rollout" in repaired
    assert agent.last_repair_verification["repair_accepted"] is True
    assert agent.last_repair_verification["final_repair_label"] == "shared_cerebras_gpt_oss_repair_agent"
    assert agent.last_repair_verification["final_repair_backend"] == "cerebras_direct"


async def test_generate_coverage_surface_repairs_overlong_question() -> None:
    overlong = (
        "Suppose this rollout now spans web, iOS, Android, delayed refunds, mixed acquisition channels, "
        "partial instrumentation, executive pressure, uneven release timing, and cohort drift. "
        "What would you compare first before you trusted the reported activation lift across those groups?"
    )
    repaired = "What would you compare first to tell whether the activation lift is real across those rollout groups?"

    agent = FollowUpAgent.__new__(FollowUpAgent)
    agent.llm_fast = _FakeLLM(overlong)
    agent.question_repair_agent = _FakeRepairAgent(repaired)

    coverage_map = AnswerCoverageMap(
        application_question="Suppose the same activation analysis now spans a new rollout. What would you inspect first?",
        implementation_anchor="Activation analysis and rollout measurement.",
        dimensions=[
            CoverageDimension(
                id="cohort_truth",
                label="Cohort truth",
                description="Check whether they verify who entered the funnel.",
                expected_approaches=["cohort split", "denominator check"],
                surfacing_question="What would tell you whether the users entering the funnel changed before you trusted the lift?",
                weight=1.5,
                depth_eligible=False,
                surface_kind="breadth",
            )
        ],
        total_weight=1.5,
        coverage_confidence=0.72,
    )

    question = await agent.generate_coverage_surface(
        dimension_id="cohort_truth",
        coverage_map=coverage_map,
        state={
            "current_persona": "curious_lead",
            "target_role": "Product Analyst",
            "turn_count": 7,
            "current_answer_context": {"focus_label": "Activation measurement"},
        },
    )

    assert question == repaired
    assert len(agent.question_repair_agent.calls) == 1
    assert agent.question_repair_agent.calls[0]["route_kind"] == "coverage_surface"


async def test_generate_coverage_depth_probe_repairs_overlong_question() -> None:
    overlong = (
        "Once that rollout starts drifting across channels, refund timing, event lag, delayed eligibility windows, "
        "and inconsistent cohort joins, what mechanism would you inspect first to decide whether the metric moved "
        "because of behavior change or because the measurement frame quietly changed underneath you?"
    )
    repaired = "What mechanism would you inspect first to tell whether behavior changed or the measurement frame drifted?"

    agent = FollowUpAgent.__new__(FollowUpAgent)
    agent.llm_fast = _FakeLLM(overlong)
    agent.question_repair_agent = _FakeRepairAgent(repaired)

    coverage_map = AnswerCoverageMap(
        application_question="Suppose the same activation analysis now spans a new rollout. What would you inspect first?",
        implementation_anchor="Activation analysis and rollout measurement.",
        dimensions=[
            CoverageDimension(
                id="measurement_drift",
                label="Measurement drift",
                description="Check whether they can isolate behavior from instrumentation drift.",
                expected_approaches=["event lag check", "cohort join audit"],
                surfacing_question="What would make you distrust the metric before claiming the rollout worked?",
                weight=1.6,
                depth_eligible=True,
                surface_kind="depth",
            )
        ],
        total_weight=1.6,
        coverage_confidence=0.7,
    )

    question = await agent.generate_coverage_depth_probe(
        dimension_id="measurement_drift",
        coverage_map=coverage_map,
        candidate_surface_response="I would separate acquisition mix from actual behavior change and check whether event joins drifted.",
        state={
            "current_persona": "curious_lead",
            "target_role": "Product Analyst",
            "turn_count": 8,
            "current_answer_context": {"focus_label": "Activation measurement"},
            "application_transfer_arc": {"confirmed_depth_level": 2, "depth_allowed_terms": ["event joins"]},
        },
    )

    assert question == repaired
    assert len(agent.question_repair_agent.calls) == 1
    assert agent.question_repair_agent.calls[0]["route_kind"] == "coverage_depth_probe"


def main() -> None:
    asyncio.run(test_question_repair_agent_prefers_shorter_cerebras_rewrite())
    asyncio.run(test_question_repair_agent_repairs_coverage_depth_at_lower_threshold())
    asyncio.run(test_question_repair_agent_adds_escape_hatch_for_transfer_lanes())
    asyncio.run(test_application_transfer_uses_shared_cerebras_repair_agent_first())
    asyncio.run(test_generate_coverage_surface_repairs_overlong_question())
    asyncio.run(test_generate_coverage_depth_probe_repairs_overlong_question())
    print("question repair integration contracts passed")


if __name__ == "__main__":
    main()
