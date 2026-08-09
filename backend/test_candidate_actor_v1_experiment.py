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

from backend.services.candidate_actor_v1 import CandidateActorV1, BehaviorStateV1


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


if __name__ == "__main__":
    unittest.main()
