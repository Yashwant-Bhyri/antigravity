#!/usr/bin/env python3
"""Recursive projection, trust-boundary, disclosure, and coherence checks."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from disclosure_controller import DisclosureError, issue_actor_turn, validate_grant
from materialize_projections import eligible_fact_view
from validate_actor_response import validate_response


ROOT = Path(__file__).resolve().parent
WORLD_DIR = ROOT / "worlds"
PROJECTION_DIR = ROOT / "projections"
SCHEMA_PATH = ROOT / "projection_v1.schema.json"
FACT_ID_RE = re.compile(r"\bfact_[a-z0-9_]+\b")

EVALUATOR_ONLY_KEYS = {
    "hiring_hypotheses", "latent_capability_profile", "target_role", "must_test_dimensions",
    "role_relevance", "discriminative_value", "evidence_properties", "confidence", "evaluator_note",
    "evaluator_hidden_truth", "emergent_surfaces", "irrelevant_temptations", "absorption_rules",
    "answer_realizations", "representative_junctions", "acceptable_move_families", "hard_invalid_moves",
    "evidence_sufficiency", "acceptable_move_sets", "invalid_reality_violations", "sufficiency_conditions",
    "attribution_rules", "correct_evidence_profile", "uncertainty_map", "verdict", "expected_report",
    "final_hiring_assessment", "opportunity_cost", "valid_action_families", "fair_interviewer_response",
    "invalid_interviewer_response", "fairness_notes", "report_effect",
}

ACTOR_TURN_FORBIDDEN_KEYS = EVALUATOR_ONLY_KEYS | {
    "factual_truth", "behavior_model", "truth_status", "relations", "protected_boundaries",
}

ACTOR_PRIVATE_FORBIDDEN_KEYS = EVALUATOR_ONLY_KEYS | {
    "candidate_behavior_profile",
}

INTERVIEWER_FORBIDDEN_KEYS = EVALUATOR_ONLY_KEYS | {
    "identity", "role_context", "turn_context", "runtime_turn", "runtime_eligible_fact_ids",
    "granted_facts", "behavior_policy", "behavior_model", "actor_constraints", "factual_truth",
    "protected_boundaries", "frozen_truth", "evidence_graph",
}


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def walk_keys(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, key, child
            yield from walk_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, f"{path}[{index}]")


def serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def scalar_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_strings(child)


def fact_ids(value: Any) -> set[str]:
    return set(FACT_ID_RE.findall(serialized(value)))


def exact_keys(value: Any, expected: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        add_error(errors, f"{path} must be an object")
        return
    actual = set(value)
    if actual != expected:
        add_error(errors, f"{path} keys mismatch missing={sorted(expected - actual)} extra={sorted(actual - expected)}")


def validate_base(errors: list[str]) -> dict[str, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "validate_trial.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        add_error(errors, "base validator failed:\n" + (result.stdout + result.stderr).strip())
    worlds: dict[str, dict[str, Any]] = {}
    for path in sorted(WORLD_DIR.glob("world_*.json")):
        world = load(path)
        worlds[world["world_id"]] = world
    if len(worlds) != 5:
        add_error(errors, f"expected 5 base worlds, found {len(worlds)}")
    return worlds


def validate_schema(value: Any, path: Path, schema: dict[str, Any], errors: list[str]) -> None:
    validator = Draft202012Validator(schema)
    for problem in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        location = ".".join(str(item) for item in problem.path) or "$"
        message = problem.message
        if problem.validator == "oneOf" and problem.context:
            branches = []
            for child in problem.context:
                child_location = ".".join(str(item) for item in child.path) or "$"
                branches.append(f"{child_location}:{child.message[:120]}")
            message += " branches=" + " | ".join(branches)
        if len(message) > 320:
            message = message[:320] + "..."
        add_error(errors, f"schema:{path.relative_to(ROOT)}:{location}:{message}")


def mutation_negative_private_behavior(value: dict[str, Any], schema: dict[str, Any], label: str, errors: list[str]) -> None:
    """Prove each private behavior container rejects an unexpected nested key."""
    behavior = value.get("behavior_model", {})
    targets: list[tuple[str, int | None]] = [
        ("short_answer_behavior", None),
        ("correction_behavior", None),
        ("contradiction_behavior", None),
    ]
    targets.extend(("response_policies", index) for index in range(len(behavior.get("response_policies", []))))
    targets.extend(("fatigue_evolution", index) for index in range(len(behavior.get("fatigue_evolution", []))))
    validator = Draft202012Validator(schema)
    for field, index in targets:
        mutated = copy.deepcopy(value)
        target = mutated["behavior_model"][field]
        if index is not None:
            target = target[index]
        target["__unexpected_nested__"] = True
        if validator.is_valid(mutated):
            suffix = f"[{index}]" if index is not None else ""
            add_error(errors, f"schema-mutation:{label}:unexpected key accepted at behavior_model.{field}{suffix}")


def check_no_forbidden_keys(value: Any, forbidden: set[str], label: str, errors: list[str]) -> None:
    for location, key, _ in walk_keys(value):
        if key in forbidden:
            add_error(errors, f"{label}:forbidden key {location}.{key}")


def check_no_evaluator_ids_or_text(value: Any, world: dict[str, Any], label: str, errors: list[str]) -> None:
    """Check exact metadata identifiers/text, never token-substitute natural prose."""
    evaluator_ids: set[str] = set()
    for group, key in ((world["acceptable_move_families"], "move_family_id"), (world["hard_invalid_moves"], "invalid_move_id"), (world["representative_junctions"], "junction_id"), (world["emergent_surfaces"], "surface_id")):
        evaluator_ids.update(item[key] for item in group if key in item)
    evaluator_ids.update(item["condition_id"] for item in world["evidence_sufficiency"]["conditions"])
    evaluator_ids.update(item["dimension_id"] for item in world["evaluator_hidden_truth"].get("correct_evidence_profile", []))
    for item in world["evaluator_hidden_truth"].get("uncertainty_map", []):
        if isinstance(item, dict) and isinstance(item.get("uncertainty_id"), str):
            evaluator_ids.add(item["uncertainty_id"])
    scalar_values = set(scalar_strings(value))
    for identifier in sorted(evaluator_ids):
        if identifier in scalar_values:
            add_error(errors, f"{label}:evaluator-only identifier leaked: {identifier}")

    rendered = serialized(value)
    evaluator_texts: list[str] = []
    for fact in world["evidence_units"]:
        if isinstance(fact.get("evaluator_note"), str):
            evaluator_texts.append(fact["evaluator_note"])
    for key in ("hiring_hypotheses", "latent_capability_profile", "emergent_surfaces", "irrelevant_temptations", "absorption_rules", "representative_junctions", "acceptable_move_families", "hard_invalid_moves", "evidence_sufficiency", "evaluator_hidden_truth"):
        evaluator_texts.extend(exact_strings(world.get(key)))
    for text in evaluator_texts:
        if len(text) >= 30 and text in rendered:
            add_error(errors, f"{label}:evaluator-only exact text leaked: {text[:80]}")


def exact_strings(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        result.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            result.extend(exact_strings(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(exact_strings(child))
    return result


def check_text_integrity(world: dict[str, Any], projection: dict[str, Any], label: str, errors: list[str]) -> None:
    identity = projection["identity"]
    role = projection["role_context"]
    if identity["biography"]["text"] != world["identity"]["biography"]["text"]:
        add_error(errors, f"{label}:biography text changed")
    if role["hiring_context"]["text"] != world["target_role"]["hiring_context"]["text"]:
        add_error(errors, f"{label}:hiring context text changed")
    expected_responsibilities = [item["text"] for item in world["target_role"]["responsibilities"]]
    actual_responsibilities = [item["text"] for item in role["responsibilities"]]
    if actual_responsibilities != expected_responsibilities:
        add_error(errors, f"{label}:role responsibility text changed")
    if projection["resume"]["text"] != world["resume"]["text"]:
        add_error(errors, f"{label}:resume text changed")
    natural_text = "\n".join([identity["biography"]["text"], role["hiring_context"]["text"], *actual_responsibilities])
    if "[later detail]" in natural_text or "later detail" in natural_text:
        add_error(errors, f"{label}:natural context contains token-redaction corruption")


def validate_private(world: dict[str, Any], value: dict[str, Any], path: Path, schema: dict[str, Any], errors: list[str]) -> None:
    label = f"actor_private:{path.name}"
    exact_keys(value, {"projection_schema_version", "projection_type", "world_id", "identity", "role_context", "resume", "factual_truth", "protected_boundaries", "behavior_model", "actor_constraints"}, "$", errors)
    check_no_forbidden_keys(value, ACTOR_PRIVATE_FORBIDDEN_KEYS, label, errors)
    if value.get("projection_type") != "actor_private" or value.get("world_id") != world["world_id"]:
        add_error(errors, f"{label}:type or world mismatch")
    check_text_integrity(world, value, label, errors)
    expected_ids = {fact["fact_id"] for fact in world["evidence_units"]}
    actual_ids = {fact.get("fact_id") for fact in value.get("factual_truth", [])}
    if actual_ids != expected_ids:
        add_error(errors, f"{label}:factual truth fact IDs mismatch")
    for private_fact in value.get("factual_truth", []):
        fact_id = private_fact.get("fact_id")
        source = next((fact for fact in world["evidence_units"] if fact["fact_id"] == fact_id), None)
        if source is None:
            continue
        if private_fact.get("label") != source["label"] or private_fact.get("statement") != source["statement"]:
            add_error(errors, f"{label}:{fact_id}:factual text changed")
        if "confidence" in private_fact or "role_relevance" in private_fact or "discriminative_value" in private_fact or "evidence_properties" in private_fact or "evaluator_note" in private_fact:
            add_error(errors, f"{label}:{fact_id}:evaluator fields retained")
    if "fair_interviewer_response" in serialized(value) or "invalid_interviewer_response" in serialized(value) or "fairness_notes" in serialized(value):
        add_error(errors, f"{label}:interviewer strategy leaked into actor-private behavior")
    check_no_evaluator_ids_or_text(value, world, label, errors)
    mutation_negative_private_behavior(value, schema, label, errors)


def validate_turn(world: dict[str, Any], value: dict[str, Any], path: Path, errors: list[str]) -> None:
    label = f"actor_turn:{path.name}"
    exact_keys(value, {"projection_schema_version", "projection_type", "world_id", "identity", "role_context", "resume", "turn_context", "granted_facts", "behavior_policy", "actor_constraints"}, "$", errors)
    check_no_forbidden_keys(value, ACTOR_TURN_FORBIDDEN_KEYS, label, errors)
    if value.get("projection_type") != "actor_turn_prompt" or value.get("world_id") != world["world_id"]:
        add_error(errors, f"{label}:type or world mismatch")
    check_text_integrity(world, value, label, errors)
    context = value.get("turn_context", {})
    already = set(context.get("already_revealed_fact_ids", []))
    newly = set(context.get("newly_granted_fact_ids", []))
    granted = set(context.get("granted_fact_ids", []))
    if granted != already | newly or already & newly:
        add_error(errors, f"{label}:turn grant ledger is inconsistent")
    base_ids = {fact["fact_id"] for fact in world["evidence_units"]}
    if not granted.issubset(base_ids):
        add_error(errors, f"{label}:unknown granted IDs {sorted(granted - base_ids)}")
    actual_ids = {fact.get("fact_id") for fact in value.get("granted_facts", [])}
    if actual_ids != granted:
        add_error(errors, f"{label}:granted fact list does not match grant ledger")
    for turn_fact in value.get("granted_facts", []):
        source = next((fact for fact in world["evidence_units"] if fact["fact_id"] == turn_fact.get("fact_id")), None)
        if source is None:
            continue
        if turn_fact.get("label") != source["label"] or turn_fact.get("statement_text") != source["statement"]["text"]:
            add_error(errors, f"{label}:{turn_fact.get('fact_id')}:granted factual text changed")
        if "truth_status" in turn_fact or "relations" in turn_fact or "confidence" in turn_fact:
            add_error(errors, f"{label}:{turn_fact.get('fact_id')}:private/evaluator field leaked")
    visible_behavior_ids = fact_ids(value.get("behavior_policy"))
    if not visible_behavior_ids.issubset(granted):
        add_error(errors, f"{label}:behavior policy cites ungranted facts {sorted(visible_behavior_ids - granted)}")
    check_no_evaluator_ids_or_text(value, world, label, errors)


def validate_interviewer(world: dict[str, Any], value: dict[str, Any], path: Path, errors: list[str]) -> None:
    label = f"interviewer:{path.name}"
    exact_keys(value, {"projection_schema_version", "projection_type", "world_id", "resume", "conversation_events"}, "$", errors)
    check_no_forbidden_keys(value, INTERVIEWER_FORBIDDEN_KEYS, label, errors)
    if value.get("projection_type") != "interviewer_visible" or value.get("world_id") != world["world_id"]:
        add_error(errors, f"{label}:type or world mismatch")
    if value.get("resume", {}).get("text") != world["resume"]["text"]:
        add_error(errors, f"{label}:resume text changed")
    if fact_ids(value):
        add_error(errors, f"{label}:fact IDs leaked into interviewer projection")
    check_no_evaluator_ids_or_text(value, world, label, errors)


def validate_evaluator(world: dict[str, Any], value: dict[str, Any], path: Path, errors: list[str]) -> None:
    label = f"evaluator:{path.name}"
    if value.get("projection_type") != "evaluator_only" or value.get("world_id") != world["world_id"]:
        add_error(errors, f"{label}:type or world mismatch")
    if value.get("frozen_truth") != world:
        add_error(errors, f"{label}:frozen_truth is not an exact copy")
    if value.get("acceptable_move_sets", {}).get("families") != world["acceptable_move_families"] or value.get("acceptable_move_sets", {}).get("junctions") != world["representative_junctions"] or value.get("acceptable_move_sets", {}).get("emergent_surfaces") != world["emergent_surfaces"]:
        add_error(errors, f"{label}:move metadata changed")
    if value.get("invalid_reality_violations") != world["hard_invalid_moves"] or value.get("sufficiency_conditions") != world["evidence_sufficiency"]:
        add_error(errors, f"{label}:invalid/sufficiency metadata changed")


def validate_controller_and_response(world: dict[str, Any], actor_turn: dict[str, Any], errors: list[str]) -> None:
    label = world["world_id"]
    facts = {fact["fact_id"]: fact for fact in world["evidence_units"]}
    initial = {
        fact_id for fact_id, fact in facts.items()
        if fact["disclosure"]["eligibility"] == "eligible"
        and fact["disclosure"]["earliest_turn"] <= 0
        and not fact["disclosure"].get("prerequisite_fact_ids")
    }
    try:
        prompt = issue_actor_turn(world, 0, [], sorted(initial))
        if prompt != actor_turn:
            add_error(errors, f"controller:{label}:materialized turn prompt differs from controller output")
    except DisclosureError as error:
        add_error(errors, f"controller:{label}:initial grant rejected: {error}")
    protected = next((fact["fact_id"] for fact in world["evidence_units"] if fact["disclosure"]["eligibility"] == "protected"), None)
    if protected:
        try:
            validate_grant(world, 0, [], [protected])
            add_error(errors, f"controller:{label}:protected fact was grantable")
        except DisclosureError:
            pass
    gated = next((fact for fact in world["evidence_units"] if fact["disclosure"].get("prerequisite_fact_ids") or fact["disclosure"]["earliest_turn"] > 0), None)
    if gated:
        try:
            validate_grant(world, 0, [], [gated["fact_id"]])
            add_error(errors, f"controller:{label}:gated fact was grantable at turn zero")
        except DisclosureError:
            pass
    granted = set(actor_turn["turn_context"]["granted_fact_ids"])
    valid_response = {
        "answer_text": "I can describe that part.",
        "factual_clauses": [{"clause": "that part", "fact_ids": [sorted(granted)[0]]}] if granted else [],
        "disclosed_fact_ids": [sorted(granted)[0]] if granted else [],
        "behavior_mode": "concise",
        "boundary_action": "none",
        "correction": {"is_correction": False, "superseded_fact_ids": [], "active_fact_ids": []},
        "uncertainty": {"kind": "none", "text": ""},
    }
    if validate_response(actor_turn, valid_response):
        add_error(errors, f"response:{label}:valid in-scope response rejected")
    hidden = next((fact["fact_id"] for fact in world["evidence_units"] if fact["fact_id"] not in granted), None)
    if hidden:
        invalid_response = copy.deepcopy(valid_response)
        invalid_response["factual_clauses"] = [{"clause": "hidden", "fact_ids": [hidden]}]
        if not validate_response(actor_turn, invalid_response):
            add_error(errors, f"response:{label}:out-of-scope citation accepted")


def main() -> int:
    errors: list[str] = []
    worlds = validate_base(errors)
    schema = load(SCHEMA_PATH)
    for world_id, world in sorted(worlds.items()):
        stem = world_id
        paths = {
            "private": PROJECTION_DIR / "actor_private" / f"{stem}.json",
            "turn": PROJECTION_DIR / "actor" / f"{stem}.json",
            "interviewer": PROJECTION_DIR / "interviewer" / f"{stem}.json",
            "evaluator": PROJECTION_DIR / "evaluator" / f"{stem}.json",
        }
        loaded: dict[str, dict[str, Any]] = {}
        for kind, path in paths.items():
            if not path.exists():
                add_error(errors, f"missing:{path.relative_to(ROOT)}")
                continue
            value = load(path)
            loaded[kind] = value
            validate_schema(value, path, schema, errors)
        if "private" in loaded:
            validate_private(world, loaded["private"], paths["private"], schema, errors)
        if "turn" in loaded:
            validate_turn(world, loaded["turn"], paths["turn"], errors)
            validate_controller_and_response(world, loaded["turn"], errors)
        if "interviewer" in loaded:
            validate_interviewer(world, loaded["interviewer"], paths["interviewer"], errors)
        if "evaluator" in loaded:
            validate_evaluator(world, loaded["evaluator"], paths["evaluator"], errors)
    if errors:
        print(f"FAIL projection/leakage validation: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS base_worlds=5 schema=5 reference_prerequisite=5")
    print("PASS actor_private=5 actor_turn_prompt=5 interviewer=5 evaluator=5")
    print("PASS recursive_boundary_checks=0 forbidden_key_leakage=0 evaluator_metadata_leakage=0")
    print("PASS disclosure_controller=5 response_citation_scope=5 natural_text_coherence=5")
    print("SUMMARY projection_errors=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
