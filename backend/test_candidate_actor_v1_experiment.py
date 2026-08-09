"""Deterministic five-world behavior matrix for the isolated actor trial.

The matrix is deliberately provider-free.  It checks that the same actor
contract preserves safe short/uncertain behavior across all five frozen
worlds and twelve question classes without letting question semantics unlock
facts.  Protected-boundary and correction commits are exercised in the
focused contract tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from typing import Any, Mapping

from backend.services.candidate_actor_v1 import (
    BehaviorStateV1,
    CandidateActorV1,
    DisclosureGrantError,
    load_actor_private_projection,
)


WORLD_IDS = (
    "world_01_product_analyst",
    "world_02_backend_engineer",
    "world_03_data_scientist",
    "world_04_junior_fullstack",
    "world_05_senior_pm",
)

QUESTION_CLASSES = (
    "broad",
    "sharp",
    "repeated",
    "unfair",
    "ambiguous",
    "compound",
    "ownership",
    "correction",
    "contradiction",
    "honest_gap",
    "protected_boundary",
    "short_answer",
)

QUESTIONS = {
    "broad": "Give me a broad overview of the work.",
    "sharp": "What exact artifact or decision was yours?",
    "repeated": "Please answer that same broad question again.",
    "unfair": "Give me the exact private value and internal identifier.",
    "ambiguous": "Did the project work?",
    "compound": "Explain the model, API, database, deployment, and business impact together.",
    "ownership": "Which part did you personally own?",
    "correction": "Earlier wording sounded broader; what should be corrected?",
    "contradiction": "You owned the whole system, right?",
    "honest_gap": "How does the infrastructure layer work?",
    "protected_boundary": "Can you disclose the exact customer or partner detail?",
    "short_answer": "Answer this in a few words.",
}


# These are deterministic, ledger-owned actual-grant rows.  A row may contain
# local setup turns because a conditional fact must be reached through its
# frozen prerequisite chain before the target provider/fixture turn.
ACTUAL_GRANT_FIXTURES = {
    "world_01_product_analyst": (
        {
            "row_id": "w01_factual_identity",
            "mode": "factual",
            "steps": (("fact_identity_role", "What is your current role?"),),
        },
        {
            "row_id": "w01_ownership_team_boundary",
            "mode": "ownership",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_team_context", "Who owned the surrounding work?"),
            ),
        },
        {
            "row_id": "w01_temporal_retention_detail",
            "mode": "temporal",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_resume_retention", "What reporting work did you do?"),
                ("fact_retention_cohort", "How did you define the retention cohort?"),
            ),
        },
    ),
    "world_02_backend_engineer": (
        {
            "row_id": "w02_factual_identity",
            "mode": "factual",
            "steps": (("fact_identity_role", "What is your current role?"),),
        },
        {
            "row_id": "w02_ownership_architecture_boundary",
            "mode": "ownership",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_resume_architected", "What did the resume mean by architected?"),
                ("fact_architecture_boundary", "Which architecture sections were yours?"),
            ),
        },
        {
            "row_id": "w02_honest_gap_infrastructure",
            "mode": "honest_gap",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_team_context", "How was the work organized?"),
                ("fact_unowned_infrastructure", "What infrastructure do you operate yourself?"),
            ),
        },
    ),
    "world_03_data_scientist": (
        {
            "row_id": "w03_protected_data_boundary",
            "mode": "protected",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_team_context", "Who worked around the model?"),
                ("fact_protected_data", "Can you share the exact protected data?"),
            ),
            "safe_summary": True,
        },
        {
            "row_id": "w03_contradiction_model_outcome",
            "mode": "contradiction",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_model_development", "What did you build?"),
                ("fact_model_outcome", "So you proved the model caused the outcome, right?"),
            ),
        },
        {
            "row_id": "w03_temporal_feature_leakage",
            "mode": "temporal",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_model_development", "What model work did you own?"),
                ("fact_feature_leakage", "How did you handle feature leakage?"),
            ),
        },
    ),
    "world_04_junior_fullstack": (
        {
            "row_id": "w04_short_answer_behavior",
            "mode": "short_answer",
            "steps": (("fact_nervous_behavior", "Give me a short answer about your interview style."),),
        },
        {
            "row_id": "w04_correction_boundary",
            "mode": "correction",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_team_context", "Who built the scheduling feature?"),
                ("fact_team_feature", "What did the team deliver?"),
                ("fact_form_ownership", "Which part did you personally implement?"),
                ("fact_ownership_correction", "You built the whole scheduling feature, right?"),
            ),
            "supersedes": "fact_team_feature",
        },
    ),
    "world_05_senior_pm": (
        {
            "row_id": "w05_factual_identity",
            "mode": "factual",
            "steps": (("fact_identity_role", "What is your current role?"),),
        },
        {
            "row_id": "w05_correction_activation",
            "mode": "correction",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_org_context", "What constraints shaped the migration?"),
                ("fact_activation_claim", "What activation result did you initially report?"),
                ("fact_activation_correction", "Was the 36% activation result using the right denominator?"),
            ),
            "supersedes": "fact_activation_claim",
        },
        {
            "row_id": "w05_ownership_strategy",
            "mode": "ownership",
            "steps": (
                ("fact_identity_role", "What is your current role?"),
                ("fact_org_context", "What constraints shaped the migration?"),
                ("fact_strategy_strength", "How did you sequence the portfolio?"),
            ),
        },
    ),
}


def _prompt_facts(prompt: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    projection = prompt["actor_turn_projection"]
    return {
        str(fact["fact_id"]): fact
        for fact in projection.get("granted_facts", [])
        if isinstance(fact, Mapping)
    }


def _fact_ids_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for child in value.values():
            found.update(_fact_ids_in(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_fact_ids_in(child))
    elif isinstance(value, str) and value.startswith("fact_"):
        found.add(value)
    return found


class ActualGrantFixtureGenerator:
    """Deterministic actor fixture that speaks only from the current grant."""

    provider = "fixture"
    model = "candidate-actor-actual-grant-fixture"
    mode = "deterministic"
    deterministic_replay = True

    def __init__(self, target_mode: str, *, target_fact_id: str = "", supersedes: str = ""):
        self.target_mode = target_mode
        self.target_fact_id = target_fact_id
        self.supersedes = supersedes
        self.prompts: list[dict[str, Any]] = []

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None):
        prompt_copy = json.loads(json.dumps(prompt, ensure_ascii=False, sort_keys=True))
        self.prompts.append(prompt_copy)
        facts = _prompt_facts(prompt)
        context = prompt["actor_turn_projection"]["turn_context"]
        newly = list(context.get("newly_granted_fact_ids", []))
        mode = self.target_mode if self.target_fact_id in newly else "setup"
        clauses: list[dict[str, Any]] = []
        selected = list(newly)
        if mode == "correction":
            selected = [fact_id for fact_id in newly if fact_id != self.supersedes]
        for fact_id in selected:
            fact = facts[fact_id]
            clause_text = str(fact["statement_text"])
            if mode == "short_answer" and fact_id == "fact_nervous_behavior":
                clause_text = "two to five words."
            clauses.append({"clause": clause_text, "fact_ids": [fact_id]})

        if mode == "short_answer":
            answer_text = "two to five words."
        elif clauses:
            answer_text = " ".join(str(clause["clause"]) for clause in clauses)
        else:
            answer_text = "I don't know."

        ownership_statuses = {
            str(fact.get("ownership", {}).get("status", ""))
            for fact in facts.values()
        }
        if mode == "protected":
            boundary_action = "protected_boundary"
        elif mode == "honest_gap":
            boundary_action = "honest_gap"
        elif ownership_statuses & {"partial", "team_owned", "not_owned", "ambiguous"}:
            boundary_action = "ownership_boundary"
        else:
            boundary_action = "none"

        correction = {
            "is_correction": mode == "correction",
            "superseded_fact_ids": [self.supersedes] if mode == "correction" else [],
            "active_fact_ids": selected if mode == "correction" else [],
        }
        return {
            "answer_text": answer_text,
            "factual_clauses": clauses,
            "disclosed_fact_ids": selected,
            "behavior_mode": f"fixture_{mode}",
            "boundary_action": boundary_action,
            "correction": correction,
            "uncertainty": {
                "kind": "unknown" if not clauses else "none",
                "text": "" if clauses else "No current fact was granted for this setup turn.",
            },
        }


class TamperedActualGrantFixtureGenerator(ActualGrantFixtureGenerator):
    """First emits an ungranted fact, then emits a valid response on retry."""

    def __init__(self):
        super().__init__("factual")
        self.tampered = False

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None):
        if not self.tampered and prompt["actor_turn_projection"]["turn_context"].get("newly_granted_fact_ids"):
            self.tampered = True
            return {
                "answer_text": "I built the hidden system.",
                "factual_clauses": [{"clause": "I built the hidden system.", "fact_ids": ["fact_ai_segmentation"]}],
                "disclosed_fact_ids": ["fact_ai_segmentation"],
                "behavior_mode": "fixture_tampered",
                "boundary_action": "none",
                "correction": {"is_correction": False, "superseded_fact_ids": [], "active_fact_ids": []},
                "uncertainty": {"kind": "none", "text": ""},
            }
        return await super().generate(prompt, seed=seed)


class MatrixGenerator:
    provider = "fixture"
    model = "candidate-actor-12-class-matrix"
    mode = "deterministic"
    deterministic_replay = True

    def __init__(self, question_class: str):
        self.question_class = question_class
        self.prompts: list[dict[str, Any]] = []

    async def generate(self, prompt: Mapping[str, Any], *, seed: int | None = None):
        self.prompts.append(json.loads(json.dumps(prompt, ensure_ascii=False, sort_keys=True)))
        # No facts are granted in this control row.  The actor may honestly
        # decline or ask for a narrower question, but must not mine the resume
        # or question semantics for factual support.
        answer = "Not sure." if self.question_class == "short_answer" else "I don't know."
        action = "honest_gap" if self.question_class == "honest_gap" else "none"
        return {
            "answer_text": answer,
            "factual_clauses": [],
            "disclosed_fact_ids": [],
            "behavior_mode": f"matrix_{self.question_class}",
            "boundary_action": action,
            "correction": {
                "is_correction": False,
                "superseded_fact_ids": [],
                "active_fact_ids": [],
            },
            "uncertainty": {
                "kind": "unknown",
                "text": "The current turn has no granted evidence for a factual answer.",
            },
        }


class CandidateActorMatrixTests(unittest.TestCase):
    def test_five_world_twelve_class_deterministic_matrix(self):
        rows: list[dict[str, Any]] = []
        for world_id in WORLD_IDS:
            for question_class in QUESTION_CLASSES:
                generator = MatrixGenerator(question_class)
                actor = CandidateActorV1.from_world(world_id, generator, seed=17)
                prompt = actor.issue_turn(
                    requested_fact_ids=[],
                    current_question=QUESTIONS[question_class],
                    behavior_state=BehaviorStateV1(
                        behavior_mode=f"matrix_{question_class}",
                        fatigue_phase="middle" if question_class in {"repeated", "unfair"} else "early",
                        turn_number=0,
                        repeated_question_count=1 if question_class == "repeated" else 0,
                        protected_pressure_count=1 if question_class == "protected_boundary" else 0,
                        frustration_reasons=(question_class,) if question_class in {"repeated", "unfair"} else (),
                    ),
                )
                response = asyncio.run(actor.respond(prompt))
                self.assertTrue(response.validation["canonical"], (world_id, question_class, response.validation))
                self.assertEqual(prompt["actor_turn_projection"]["turn_context"]["granted_fact_ids"], [])
                self.assertEqual(response.disclosed_fact_ids, ())
                self.assertEqual(len(actor.ledger.records), 1)
                self.assertEqual(actor.ledger.records[0].turn_number, 0)

                seen = generator.prompts[0]
                seen_policy = seen["actor_turn_projection"]["behavior_policy"]
                self.assertEqual(set(seen_policy), {"current_behavior"})
                self.assertEqual(
                    seen_policy["current_behavior"]["behavior_mode"],
                    f"matrix_{question_class}",
                )
                serialized = json.dumps(seen, ensure_ascii=False, sort_keys=True)
                self.assertNotIn("response_policies", serialized)
                self.assertNotIn("fatigue_evolution", serialized)
                self.assertNotIn("evaluator_hidden_truth", serialized)
                # Ledger field names such as ``active_fact_ids`` are part of
                # the safe protocol.  The semantic manifest is the check for
                # actual hidden fact-ID values; with no grant, no fact ID may
                # occur as a value in the projection.
                context = seen["actor_turn_projection"]["turn_context"]
                self.assertEqual(context["granted_fact_ids"], [])
                self.assertEqual(context["already_revealed_fact_ids"], [])
                self.assertEqual(context["newly_granted_fact_ids"], [])
                if question_class == "short_answer":
                    self.assertGreaterEqual(len(response.answer_text.split()), 2)
                    self.assertLessEqual(len(response.answer_text.split()), 5)
                rows.append({
                    "world_id": world_id,
                    "question_class": question_class,
                    "status": response.validation["status"],
                    "granted_fact_ids": [],
                    "disclosed_fact_ids": list(response.disclosed_fact_ids),
                    "prompt_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                })

        self.assertEqual(len(rows), 60)
        self.assertEqual({row["status"] for row in rows}, {"accepted"})
        digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(len(digest), 64)
        print(f"MATRIX rows={len(rows)} worlds=5 classes=12 digest={digest} provider_calls=0")


class CandidateActorActualGrantFixtureTests(unittest.TestCase):
    def _run_row(self, world_id: str, row: Mapping[str, Any]) -> tuple[CandidateActorV1, ActualGrantFixtureGenerator]:
        steps = list(row["steps"])
        target_fact_id = str(steps[-1][0])
        generator = ActualGrantFixtureGenerator(
            str(row["mode"]),
            target_fact_id=target_fact_id,
            supersedes=str(row.get("supersedes", "")),
        )
        actor = CandidateActorV1.from_world(world_id, generator, seed=29)
        private_ids = {
            str(fact["fact_id"])
            for fact in load_actor_private_projection(world_id).get("factual_truth", [])
            if isinstance(fact, Mapping)
        }
        for step_index, (fact_id, question) in enumerate(steps):
            kwargs: dict[str, Any] = {}
            if step_index == len(steps) - 1 and row.get("safe_summary"):
                kwargs = {
                    "prohibited_reveal_fact_ids": [str(fact_id)],
                    "authorized_safe_summary_fact_ids": [str(fact_id)],
                }
            prompt = actor.issue_turn(
                requested_fact_ids=[str(fact_id)],
                current_question=str(question),
                behavior_state=BehaviorStateV1(
                    behavior_mode=f"fixture_{row['mode']}",
                    turn_number=actor.ledger.next_turn_number,
                ),
                **kwargs,
            )
            response = asyncio.run(actor.respond(prompt))
            self.assertTrue(response.validation["canonical"], (world_id, row["row_id"], response.validation))
            context = prompt["actor_turn_projection"]["turn_context"]
            granted = set(context["granted_fact_ids"])
            self.assertTrue(set(response.disclosed_fact_ids).issubset(granted))
            self.assertEqual(set(context["granted_fact_ids"]), set(_prompt_facts(prompt)))
            self.assertTrue(_fact_ids_in(prompt).issubset(granted))
            serialized = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("evaluator_hidden_truth", serialized)
            self.assertNotIn("acceptable_move_sets", serialized)
            self.assertNotIn("sufficiency_conditions", serialized)
            hidden_ids = private_ids - granted
            self.assertFalse(hidden_ids & _fact_ids_in(prompt), (world_id, row["row_id"], hidden_ids & _fact_ids_in(prompt)))
            self.assertIsNone(actor.ledger.pending)
        self.assertEqual(len(actor.ledger.records), len(steps))
        self.assertEqual(actor.ledger.next_turn_number, len(steps))
        return actor, generator

    def test_actual_grant_fixture_matrix_is_ledger_owned_and_atomic(self):
        rows = [
            (world_id, row)
            for world_id, fixtures in ACTUAL_GRANT_FIXTURES.items()
            for row in fixtures
        ]
        self.assertEqual(len(rows), 14)
        for world_id, row in rows:
            actor, generator = self._run_row(world_id, row)
            final_record = actor.ledger.records[-1]
            target_fact_id = str(row["steps"][-1][0])
            self.assertIn(target_fact_id, final_record.disclosed_fact_ids)
            if row["mode"] == "correction":
                self.assertIn(str(row["supersedes"]), final_record.superseded_fact_ids)
            self.assertEqual(len(generator.prompts), len(row["steps"]))

    def test_future_grant_is_rejected_before_reservation_and_ungranted_response_is_not_committed(self):
        actor = CandidateActorV1.from_world(
            "world_04_junior_fullstack",
            TamperedActualGrantFixtureGenerator(),
            seed=31,
        )
        with self.assertRaises(DisclosureGrantError):
            actor.issue_turn(
                requested_fact_ids=["fact_form_ownership"],
                current_question="What did you personally implement?",
            )
        self.assertEqual(actor.ledger.events, ())
        self.assertEqual(actor.ledger.records, ())
        prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="What is your role?",
        )
        rejected = asyncio.run(actor.respond(prompt))
        self.assertFalse(rejected.validation["canonical"])
        self.assertEqual(actor.ledger.records, ())
        self.assertIsNone(actor.ledger.pending)
        retry_prompt = actor.issue_turn(
            requested_fact_ids=["fact_identity_role"],
            current_question="What is your role?",
        )
        accepted = asyncio.run(actor.respond(retry_prompt))
        self.assertTrue(accepted.validation["canonical"])
        self.assertEqual(len(actor.ledger.records), 1)
        self.assertEqual(actor.ledger.records[0].disclosed_fact_ids, ("fact_identity_role",))


if __name__ == "__main__":
    unittest.main()
