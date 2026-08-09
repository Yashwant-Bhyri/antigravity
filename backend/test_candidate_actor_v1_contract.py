"""Focused contract/regression tests for the isolated CandidateActorV1 trial.

These tests intentionally use deterministic local generators.  They do not
exercise the live backend or make provider calls.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from backend.services.candidate_actor_v1 import (
    ActorPromptError,
    BehaviorStateV1,
    CandidateActorV1,
    CandidateActorError,
    DisclosureGrantError,
    StaticActorGenerator,
    assert_actor_prompt_semantic_manifest,
    assert_safe_actor_turn_projection,
    build_actor_turn_prompt,
    build_trusted_actor_turn_projection,
    load_actor_private_projection,
    validate_actor_response_v1,
)


WORLD_IDS = (
    "world_01_product_analyst",
    "world_02_backend_engineer",
    "world_03_data_scientist",
    "world_04_junior_fullstack",
    "world_05_senior_pm",
)


class DynamicGenerator:
    provider = "fixture"
    model = "candidate-actor-contract-fixture"
    mode = "deterministic"
    deterministic_replay = True

    def __init__(self, callback):
        self.callback = callback
        self.prompts: list[dict[str, Any]] = []

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None):
        self.prompts.append(copy.deepcopy(dict(prompt)))
        return self.callback(prompt, len(self.prompts))


class RaisingGenerator:
    provider = "fixture"
    model = "raising-fixture"
    mode = "deterministic"
    deterministic_replay = True

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None):
        raise RuntimeError("fixture generation failure")


def _facts(prompt: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    projection = prompt["actor_turn_projection"]
    return {
        str(fact["fact_id"]): fact
        for fact in projection.get("granted_facts", [])
        if isinstance(fact, Mapping)
    }


def payload_for_prompt(
    prompt: Mapping[str, Any],
    *,
    fact_ids: list[str] | None = None,
    answer_text: str | None = None,
    boundary_action: str = "none",
    uncertainty: Mapping[str, Any] | None = None,
    correction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    facts = _facts(prompt)
    context = prompt["actor_turn_projection"]["turn_context"]
    selected = fact_ids if fact_ids is not None else list(context.get("newly_granted_fact_ids", []))
    if fact_ids is None and not selected and facts:
        selected = [sorted(facts)[0]]
    clauses: list[dict[str, Any]] = []
    if answer_text is None and selected:
        texts = []
        for fact_id in selected:
            fact = facts[fact_id]
            texts.append(str(fact["statement_text"]))
            clauses.append({"clause": str(fact["statement_text"]), "fact_ids": [fact_id]})
        answer_text = " ".join(texts)
    if answer_text is None:
        answer_text = "I don't know."
    return {
        "answer_text": answer_text,
        "factual_clauses": clauses,
        "disclosed_fact_ids": list(selected),
        "behavior_mode": str(
            prompt.get("behavior_state", {}).get("behavior_mode", "baseline")
        ),
        "boundary_action": boundary_action,
        "correction": dict(correction or {
            "is_correction": False,
            "superseded_fact_ids": [],
            "active_fact_ids": [],
        }),
        "uncertainty": dict(uncertainty or {"kind": "none", "text": ""}),
    }


def _run(coro):
    return asyncio.run(coro)


class CandidateActorContractTests(unittest.TestCase):
    def test_snapshot_compiles_and_public_request_api_cannot_accept_state(self):
        import backend.services.candidate_actor_v1 as actor_module

        for name in (
            "respond",
            "issue_turn",
            "respond_from_trusted_grant",
        ):
            parameters = set(inspect.signature(getattr(CandidateActorV1, name)).parameters)
            self.assertNotIn("already_revealed_fact_ids", parameters, name)
            self.assertNotIn("newly_granted_fact_ids", parameters, name)
            self.assertNotIn("actor_ledger", parameters, name)
        trusted_parameters = set(inspect.signature(build_trusted_actor_turn_projection).parameters)
        self.assertNotIn("already_revealed_fact_ids", trusted_parameters)
        self.assertNotIn("newly_granted_fact_ids", trusted_parameters)
        self.assertNotIn("actor_ledger", trusted_parameters)
        self.assertNotIn("actor_ledger", inspect.signature(build_actor_turn_prompt).parameters)
        self.assertTrue(hasattr(actor_module, "AppendOnlyDisclosureLedgerV1"))

    def test_failed_validation_releases_reservation_without_committing_disclosure(self):
        def callback(prompt, call_number):
            if call_number == 1:
                return payload_for_prompt(prompt, answer_text="FakeCo", fact_ids=[])
            return payload_for_prompt(prompt, fact_ids=["fact_identity_role"])

        generator = DynamicGenerator(callback)
        actor = CandidateActorV1.from_world("world_01_product_analyst", generator)
        first_prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="Tell me about your current role.",
        )
        rejected = _run(actor.respond(first_prompt))
        self.assertFalse(rejected.validation["canonical"])
        self.assertEqual(actor.ledger.records, ())
        self.assertIsNone(actor.ledger.pending)
        self.assertIn("released", [event["event_type"] for event in actor.ledger.events])

        retry_prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="Tell me about your current role.",
        )
        accepted = _run(actor.respond(retry_prompt))
        self.assertTrue(accepted.validation["canonical"])
        self.assertEqual([record.turn_number for record in actor.ledger.records], [0])
        self.assertEqual(actor.ledger.records[0].newly_granted_fact_ids, ("fact_identity_role",))

    def test_generator_exception_does_not_commit_or_advance_turn(self):
        actor = CandidateActorV1.from_world("world_02_backend_engineer", RaisingGenerator())
        prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="What do you work on?",
        )
        response = _run(actor.respond(prompt))
        self.assertFalse(response.validation["canonical"])
        self.assertEqual(actor.ledger.records, ())
        self.assertIsNone(actor.ledger.pending)
        self.assertEqual(actor.ledger.next_turn_number, 0)

    def test_turn_lifecycle_is_monotonic_and_history_is_ledger_owned(self):
        generator = DynamicGenerator(lambda prompt, _: payload_for_prompt(prompt))
        actor = CandidateActorV1.from_world("world_01_product_analyst", generator)
        first = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="What is your role?",
        )
        self.assertEqual(first["actor_ledger"]["turn_number"], 0)
        _run(actor.respond(first))
        second = actor.issue_turn(
            requested_fact_ids=["fact_career_motivation"],
            current_question="Why did you move into analytics?",
        )
        context = second["actor_turn_projection"]["turn_context"]
        self.assertEqual(context["turn_number"], 1)
        self.assertEqual(context["already_revealed_fact_ids"], ["fact_identity_role"])
        self.assertEqual(context["newly_granted_fact_ids"], ["fact_career_motivation"])
        self.assertEqual(second["actor_ledger"]["already_revealed_fact_ids"], ["fact_identity_role"])
        _run(actor.respond(second))
        self.assertEqual([record.turn_number for record in actor.ledger.records], [0, 1])
        with self.assertRaises(TypeError):
            actor.issue_turn(already_revealed_fact_ids=[], current_question="bad")

    def test_future_behavior_policy_is_not_passed_to_generator(self):
        generator = DynamicGenerator(lambda prompt, _: payload_for_prompt(prompt, fact_ids=[]))
        actor = CandidateActorV1.from_world("world_03_data_scientist", generator)
        prompt = actor.issue_turn(
            requested_fact_ids=[],
            current_question="What would you do first?",
            behavior_state=BehaviorStateV1(
                fatigue_phase="late",
                behavior_mode="late_boundary",
                turn_number=0,
                repeated_question_count=2,
                speaking_guidance="Keep the answer bounded.",
                response_guidance="Answer one layer.",
                correction_guidance="Correct a prior claim if granted.",
                contradiction_guidance="Reject an incorrect premise.",
            ),
        )
        response = _run(actor.respond(prompt))
        self.assertTrue(response.validation["canonical"])
        seen = generator.prompts[0]
        policy = seen["actor_turn_projection"]["behavior_policy"]
        self.assertEqual(set(policy), {"current_behavior"})
        self.assertNotIn("response_policies", json.dumps(seen))
        self.assertNotIn("fatigue_evolution", json.dumps(seen))
        self.assertEqual(policy["current_behavior"]["behavior_mode"], "late_boundary")

    def test_forbidden_key_and_semantic_hidden_fact_mutations_are_rejected(self):
        actor = CandidateActorV1.from_world("world_01_product_analyst", DynamicGenerator(lambda p, _: payload_for_prompt(p, fact_ids=[])))
        prompt = actor.issue_turn(requested_fact_ids=[], current_question="Tell me about yourself.")
        forbidden = copy.deepcopy(prompt["actor_turn_projection"])
        forbidden["evaluator_hidden_truth"] = {"fact_ai_segmentation": "hidden"}
        with self.assertRaises(ActorPromptError):
            assert_safe_actor_turn_projection(forbidden)

        hidden_id = copy.deepcopy(prompt["actor_turn_projection"])
        hidden_id["identity"]["hidden_fact_id"] = "fact_ai_segmentation"
        with self.assertRaises(ActorPromptError):
            assert_actor_prompt_semantic_manifest(hidden_id)

        private = load_actor_private_projection("world_01_product_analyst")
        hidden_text = next(
            fact["statement"]["text"]
            for fact in private["factual_truth"]
            if fact["fact_id"] == "fact_ai_segmentation"
        )
        hidden_text_projection = copy.deepcopy(prompt["actor_turn_projection"])
        hidden_text_projection["identity"]["biography"]["text"] += " " + hidden_text
        with self.assertRaises(ActorPromptError):
            assert_actor_prompt_semantic_manifest(hidden_text_projection)

    def test_resume_claim_is_unverified_and_cannot_cover_factual_speech(self):
        actor = CandidateActorV1.from_world("world_01_product_analyst", DynamicGenerator(lambda p, _: payload_for_prompt(p, fact_ids=[])))
        prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="What does your resume say about segmentation?",
        )
        attributed = {
            **payload_for_prompt(prompt, fact_ids=[], answer_text="My resume says I defined customer segments and campaign rules for lifecycle messaging."),
            "resume_claim_references": [{
                "claim_id": "claim_segments_rules",
                "reference_text": "My resume says I defined customer segments and campaign rules for lifecycle messaging.",
                "mode": "unverified_resume_claim",
            }],
        }
        validation = validate_actor_response_v1(prompt, attributed)
        self.assertTrue(validation.canonical, validation.errors)
        self.assertEqual(validation.disclosed_fact_ids, ())

        bare_claim = payload_for_prompt(
            prompt,
            fact_ids=[],
            answer_text="I defined customer segments and campaign rules.",
        )
        bare_validation = validate_actor_response_v1(prompt, bare_claim)
        self.assertFalse(bare_validation.canonical)
        self.assertTrue(any("uncited factual" in error for error in bare_validation.errors))

        embellished = copy.deepcopy(attributed)
        embellished["answer_text"] = (
            "My resume says I defined customer segments and campaign rules for lifecycle messaging, "
            "and I deployed Kubernetes."
        )
        embellished_validation = validate_actor_response_v1(prompt, embellished)
        self.assertFalse(embellished_validation.canonical)

    def test_conservative_support_rejects_typed_inventions_despite_generic_overlap(self):
        actor = CandidateActorV1.from_world("world_01_product_analyst", DynamicGenerator(lambda p, _: payload_for_prompt(p, fact_ids=[])))
        prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="Tell me about your role.",
        )
        cases = {
            "employer": "Priya works as a product analyst at FakeCo, a customer-engagement company.",
            "metric": "Priya increased repeat booking by 99%.",
            "technology": "Priya deployed Kubernetes for the engagement platform.",
            "ownership": "Priya solely owned the entire Looply platform.",
            "chronology": "Priya started at Looply in 2018.",
            "named_entity": "Priya partnered with Acme on the work.",
            "generic_overlap": "Priya did work on a project.",
        }
        for label, text in cases.items():
            payload = payload_for_prompt(
                prompt,
                fact_ids=["fact_identity_role"],
                answer_text=text,
            )
            validation = validate_actor_response_v1(prompt, payload)
            self.assertFalse(validation.canonical, label)

    def test_empty_factual_clauses_cannot_hide_one_token_propositions(self):
        actor = CandidateActorV1.from_world("world_02_backend_engineer", DynamicGenerator(lambda p, _: payload_for_prompt(p, fact_ids=[])))
        prompt = actor.issue_turn(requested_fact_ids=[], current_question="What did you use?")
        for answer in ("Kubernetes.", "11%.", "FakeCo.", "Owned."):
            payload = payload_for_prompt(prompt, fact_ids=[], answer_text=answer)
            validation = validate_actor_response_v1(prompt, payload)
            self.assertFalse(validation.canonical, answer)

    def test_ownership_boundary_and_honest_gap_are_valid_when_granted(self):
        def callback(prompt, _):
            ids = list(prompt["actor_turn_projection"]["turn_context"]["newly_granted_fact_ids"])
            action = "ownership_boundary" if ids == ["fact_team_context"] else (
                "honest_gap" if ids == ["fact_infrastructure_gap"] else "none"
            )
            uncertainty = {"kind": "unknown", "text": "I have not operated that layer."} if action == "honest_gap" else {"kind": "none", "text": ""}
            return payload_for_prompt(prompt, fact_ids=ids, boundary_action=action, uncertainty=uncertainty)

        actor = CandidateActorV1.from_world("world_01_product_analyst", DynamicGenerator(callback))
        first = actor.issue_turn(requested_fact_ids=["fact_identity_role"], current_question="Role?")
        self.assertTrue(_run(actor.respond(first)).validation["canonical"])
        team = actor.issue_turn(requested_fact_ids=["fact_team_context"], current_question="Who worked with you?")
        team_response = _run(actor.respond(team))
        self.assertTrue(team_response.validation["canonical"], team_response.validation)

        gap_actor = CandidateActorV1.from_world("world_04_junior_fullstack", DynamicGenerator(callback))
        gap_first = gap_actor.issue_turn(requested_fact_ids=["fact_identity_role"], current_question="Role?")
        self.assertTrue(_run(gap_actor.respond(gap_first)).validation["canonical"])
        gap = gap_actor.issue_turn(requested_fact_ids=["fact_infrastructure_gap"], current_question="How does Kubernetes schedule pods?")
        gap_response = _run(gap_actor.respond(gap))
        self.assertTrue(gap_response.validation["canonical"], gap_response.validation)

    def test_correction_supersedes_prior_active_fact_without_dishonesty_verdict(self):
        correction_holder: dict[str, Any] = {}

        def callback(prompt, call_number):
            if call_number < 3:
                return payload_for_prompt(prompt)
            return correction_holder["payload"]

        actor = CandidateActorV1.from_world(
            "world_02_backend_engineer",
            DynamicGenerator(callback),
        )
        first = actor.issue_turn(requested_fact_ids=["fact_resume_architected"], current_question="What did you architect?")
        self.assertTrue(_run(actor.respond(first)).validation["canonical"])
        second = actor.issue_turn(requested_fact_ids=["fact_architecture_boundary"], current_question="Who owned the architecture?")
        self.assertTrue(_run(actor.respond(second)).validation["canonical"])

        correction_prompt = actor.issue_turn(requested_fact_ids=[], current_question="Please clarify the resume wording.")
        correction = {
            "answer_text": (
                "My resume says I architected the multi-tenant shipment and billing platform. "
                "The architecture was agreed by a small backend group; Miguel authored the retry and state-transition design."
            ),
            "factual_clauses": [
                {
                    "clause": "My resume says I architected the multi-tenant shipment and billing platform.",
                    "fact_ids": ["fact_resume_architected"],
                },
                {
                    "clause": "The architecture was agreed by a small backend group; Miguel authored the retry and state-transition design.",
                    "fact_ids": ["fact_architecture_boundary"],
                },
            ],
            "disclosed_fact_ids": ["fact_architecture_boundary"],
            "behavior_mode": "correction",
            "boundary_action": "ownership_boundary",
            "correction": {
                "is_correction": True,
                "superseded_fact_ids": ["fact_resume_architected"],
                "active_fact_ids": ["fact_architecture_boundary"],
            },
            "uncertainty": {"kind": "none", "text": ""},
        }
        correction_holder["payload"] = correction
        validation = validate_actor_response_v1(correction_prompt, correction)
        self.assertTrue(validation.canonical, validation.errors)
        response = _run(actor.respond(correction_prompt))
        self.assertTrue(response.validation["canonical"], response.validation)
        self.assertEqual(actor.ledger.records[-1].superseded_fact_ids, ("fact_resume_architected",))
        self.assertEqual(actor.ledger.records[-1].active_fact_ids, ("fact_architecture_boundary",))

        dishonest = copy.deepcopy(correction)
        dishonest["answer_text"] += " I lied."
        dishonest_validation = validate_actor_response_v1(correction_prompt, dishonest)
        self.assertFalse(dishonest_validation.canonical)

    def test_protected_boundary_requires_safe_summary_and_never_exact_private_text(self):
        def callback(prompt, _):
            context = prompt["actor_turn_projection"]["turn_context"]
            ids = list(context["newly_granted_fact_ids"])
            protected = any(
                prompt_fact.get("disclosure", {}).get("eligibility") == "protected_summary"
                for prompt_fact in prompt["actor_turn_projection"]["granted_facts"]
                if isinstance(prompt_fact, Mapping)
            )
            return payload_for_prompt(
                prompt,
                fact_ids=ids,
                boundary_action="protected_boundary" if protected else "none",
            )

        actor = CandidateActorV1.from_world("world_01_product_analyst", DynamicGenerator(callback))
        for requested in (
            ["fact_identity_role"],
            ["fact_team_context"],
            ["fact_ai_platform_surface"],
        ):
            prompt = actor.issue_turn(requested_fact_ids=requested, current_question="Tell me about the product.")
            self.assertTrue(_run(actor.respond(prompt)).validation["canonical"])
        with self.assertRaises(DisclosureGrantError):
            actor.issue_turn(
                requested_fact_ids=["fact_protected_customer_rules"],
                current_question="What exact customer thresholds did you use?",
            )
        self.assertEqual(actor.ledger.next_turn_number, 3)

        safe_prompt = actor.issue_turn(
            requested_fact_ids=["fact_protected_customer_rules"],
            current_question="Can you share the exact customer threshold?",
            prohibited_reveal_fact_ids=["fact_protected_customer_rules"],
            authorized_safe_summary_fact_ids=["fact_protected_customer_rules"],
        )
        protected_fact = next(
            fact for fact in safe_prompt["actor_turn_projection"]["granted_facts"]
            if fact["fact_id"] == "fact_protected_customer_rules"
        )
        private = load_actor_private_projection("world_01_product_analyst")
        private_statement = next(
            fact["statement"]["text"]
            for fact in private["factual_truth"]
            if fact["fact_id"] == "fact_protected_customer_rules"
        )
        self.assertNotIn(private_statement, json.dumps(safe_prompt))
        self.assertEqual(protected_fact["disclosure"]["eligibility"], "protected_summary")
        response = _run(actor.respond(safe_prompt))
        self.assertTrue(response.validation["canonical"], response.validation)
        self.assertEqual(actor.ledger.records[-1].authorized_safe_summary_fact_ids, ("fact_protected_customer_rules",))


if __name__ == "__main__":
    unittest.main()
