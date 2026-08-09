#!/usr/bin/env python3
"""Read-only validator for the isolated Luna CandidateWorldV1 trial."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "candidate_world_v1.schema.json"
INDEX_PATH = ROOT / "world_index.json"
EXPECTED_WORLD_IDS = (
    "world_01_product_analyst",
    "world_02_backend_engineer",
    "world_03_data_scientist",
    "world_04_junior_fullstack",
    "world_05_senior_pm",
)
REQUIRED_ARTIFACTS = (
    ROOT / "README.md",
    ROOT / "authoring_calibration.md",
    ROOT / "candidate_world_v1.schema.json",
    ROOT / "actor_contract.md",
    ROOT / "world_index.json",
    ROOT / "reviewer_scorecard.md",
    ROOT / "audits" / "world_01_audit.md",
    ROOT / "audits" / "world_02_audit.md",
    ROOT / "audits" / "world_03_audit.md",
    ROOT / "audits" / "world_04_audit.md",
    ROOT / "audits" / "world_05_audit.md",
    ROOT / "audits" / "cross_world_audit.md",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"top-level JSON value must be an object: {path}")
    return value


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def all_fact_references(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "target_fact_id" and isinstance(child, str):
                yield child_path, child
            elif key in {
                "fact_ids",
                "ownership_evidence_ids",
                "prerequisite_fact_ids",
                "allowed_disclosure",
                "observed_fact_ids",
            } and isinstance(child, list):
                for index, fact_id in enumerate(child):
                    if isinstance(fact_id, str):
                        yield f"{child_path}[{index}]", fact_id
            elif key == "evidence_needed" and isinstance(child, list):
                for group_index, group in enumerate(child):
                    if isinstance(group, list):
                        for fact_index, fact_id in enumerate(group):
                            if isinstance(fact_id, str):
                                yield f"{child_path}[{group_index}][{fact_index}]", fact_id
            yield from all_fact_references(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from all_fact_references(child, f"{path}[{index}]")


def find_prerequisite_cycle(prerequisites: dict[str, set[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(fact_id: str) -> list[str]:
        if fact_id in visiting:
            start = stack.index(fact_id)
            return stack[start:] + [fact_id]
        if fact_id in visited:
            return []
        visiting.add(fact_id)
        stack.append(fact_id)
        for dependency in prerequisites.get(fact_id, set()):
            cycle = visit(dependency)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(fact_id)
        visited.add(fact_id)
        return []

    for candidate in prerequisites:
        cycle = visit(candidate)
        if cycle:
            return cycle
    return []


def transitive_prerequisites(fact_id: str, prerequisites: dict[str, set[str]]) -> set[str]:
    result: set[str] = set()
    pending = list(prerequisites.get(fact_id, set()))
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(prerequisites.get(dependency, set()))
    return result


def validate_world(
    world: dict[str, Any],
    world_path: Path,
    schema_validator: Draft202012Validator,
) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    schema_errors = sorted(schema_validator.iter_errors(world), key=lambda item: list(item.absolute_path))
    for error in schema_errors:
        location = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path
        )
        errors.append(f"schema:{location}:{error.message}")

    facts = world.get("evidence_units", [])
    fact_ids = [item.get("fact_id") for item in facts if isinstance(item, dict)]
    fact_set = {item for item in fact_ids if isinstance(item, str)}
    if len(fact_ids) != len(fact_set):
        errors.append("references:duplicate_fact_id")

    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            continue
        fact_id = fact.get("fact_id")
        statement = fact.get("statement", {})
        statement_ids = statement.get("fact_ids", []) if isinstance(statement, dict) else []
        if fact_id and fact_id not in statement_ids:
            errors.append(f"citations:$.evidence_units[{index}].statement:must cite its own fact_id")

    for reference_path, fact_id in all_fact_references(world):
        if fact_id not in fact_set:
            errors.append(f"references:{reference_path}:unknown fact_id {fact_id}")

    for object_path, value in walk(world):
        if isinstance(value, dict) and set(value) == {"text", "fact_ids"}:
            fact_refs = value.get("fact_ids")
            if not isinstance(fact_refs, list) or not fact_refs:
                errors.append(f"citations:{object_path}:cited text has no fact_ids")

    prerequisites: dict[str, set[str]] = {}
    unavailable: set[str] = set()
    protected: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict) or not isinstance(fact.get("fact_id"), str):
            continue
        fact_id = fact["fact_id"]
        disclosure = fact.get("disclosure", {})
        dependencies = set(disclosure.get("prerequisite_fact_ids", [])) if isinstance(disclosure, dict) else set()
        prerequisites[fact_id] = dependencies
        if fact_id in dependencies:
            errors.append(f"reveal:{fact_id}:self prerequisite")
        eligibility = disclosure.get("eligibility") if isinstance(disclosure, dict) else None
        if eligibility == "unavailable":
            unavailable.add(fact_id)
        if eligibility == "protected":
            protected.add(fact_id)

    cycle = find_prerequisite_cycle(prerequisites)
    if cycle:
        errors.append(f"reveal:prerequisite_cycle:{' -> '.join(cycle)}")

    answers = world.get("answer_realizations", [])
    answer_ids: set[str] = set()
    event_ids: set[str] = set()
    for index, answer in enumerate(answers):
        if not isinstance(answer, dict):
            continue
        answer_id = answer.get("answer_id")
        event_id = answer.get("disclosure_event")
        if answer_id in answer_ids:
            errors.append(f"answers:duplicate answer_id {answer_id}")
        if event_id in event_ids:
            errors.append(f"answers:duplicate disclosure_event {event_id}")
        if isinstance(answer_id, str):
            answer_ids.add(answer_id)
        if isinstance(event_id, str):
            event_ids.add(event_id)
        cited = set(answer.get("fact_ids", []))
        if not cited:
            errors.append(f"answers:$.answer_realizations[{index}]:no fact_ids")
        if cited & unavailable:
            errors.append(
                f"answers:{answer_id}:cites unavailable facts {sorted(cited & unavailable)}"
            )
        required: set[str] = set()
        for fact_id in cited:
            required |= transitive_prerequisites(fact_id, prerequisites)
        missing = required - cited
        if missing:
            errors.append(f"reveal:{answer_id}:missing prerequisite citations {sorted(missing)}")
        if cited & protected and answer.get("behavior_label") != "protected_boundary":
            errors.append(
                f"protected:{answer_id}:protected fact cited without protected_boundary behavior"
            )

    relations_seen: set[tuple[str, str, str]] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        source = fact.get("fact_id")
        for relation in fact.get("relations", []):
            if not isinstance(relation, dict):
                continue
            target = relation.get("target_fact_id")
            relation_type = relation.get("type")
            key = (str(source), str(relation_type), str(target))
            if source == target:
                errors.append(f"relations:{source}:self relation {relation_type}")
            if key in relations_seen:
                errors.append(f"relations:{source}:duplicate {relation_type} -> {target}")
            relations_seen.add(key)

    move_families = world.get("acceptable_move_families", [])
    family_ids = {
        item.get("family_id") for item in move_families if isinstance(item, dict) and isinstance(item.get("family_id"), str)
    }
    if len(family_ids) != len(move_families):
        errors.append("moves:duplicate or missing family_id")
    invalid_moves = world.get("hard_invalid_moves", [])
    invalid_ids = {
        item.get("move_id") for item in invalid_moves if isinstance(item, dict) and isinstance(item.get("move_id"), str)
    }
    if len(invalid_ids) != len(invalid_moves):
        errors.append("moves:duplicate or missing move_id")

    for surface in world.get("emergent_surfaces", []):
        for family_id in surface.get("valid_action_families", []):
            if family_id not in family_ids:
                errors.append(f"moves:{surface.get('surface_id')}:unknown family {family_id}")
    for junction in world.get("representative_junctions", []):
        for family_id in junction.get("reasonable_move_family_ids", []):
            if family_id not in family_ids:
                errors.append(f"moves:{junction.get('junction_id')}:unknown family {family_id}")
    for family in move_families:
        for move_id in family.get("hard_invalid_move_ids", []):
            if move_id not in invalid_ids:
                errors.append(f"moves:{family.get('family_id')}:unknown invalid move {move_id}")
    for invalid in invalid_moves:
        for family_id in invalid.get("fair_alternative_family_ids", []):
            if family_id not in family_ids:
                errors.append(f"moves:{invalid.get('move_id')}:unknown alternative family {family_id}")

    target_dimensions = {
        item.get("dimension_id")
        for item in world.get("target_role", {}).get("must_test_dimensions", [])
        if isinstance(item, dict)
    }
    hidden_dimensions = {
        item.get("dimension_id")
        for item in world.get("evaluator_hidden_truth", {}).get("correct_evidence_profile", [])
        if isinstance(item, dict)
    }
    unknown_dimensions = hidden_dimensions - target_dimensions
    if unknown_dimensions:
        errors.append(f"dimensions:hidden profile uses unknown dimensions {sorted(unknown_dimensions)}")

    expected_id = world_path.stem
    if world.get("world_id") != expected_id:
        errors.append(f"identity:world_id {world.get('world_id')} does not match filename {expected_id}")

    stats = {
        "facts": len(fact_set),
        "answers": len(answers),
        "junctions": len(world.get("representative_junctions", [])),
        "families": len(family_ids),
        "protected_facts": len(protected),
    }
    return errors, stats


def validate_index(index: dict[str, Any], worlds: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    entries = index.get("worlds", [])
    if index.get("world_count") != len(EXPECTED_WORLD_IDS):
        errors.append(f"index:world_count expected {len(EXPECTED_WORLD_IDS)}")
    entry_ids = [item.get("world_id") for item in entries if isinstance(item, dict)]
    if tuple(entry_ids) != EXPECTED_WORLD_IDS:
        errors.append(f"index:world order or ids mismatch: {entry_ids}")
    if set(worlds) != set(EXPECTED_WORLD_IDS):
        errors.append(f"index:loaded world ids mismatch: {sorted(worlds)}")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        world_id = entry.get("world_id")
        relative_path = entry.get("path")
        if not isinstance(relative_path, str) or not (ROOT / relative_path).is_file():
            errors.append(f"index:{world_id}:missing path {relative_path}")
        audit_path = entry.get("audit_path")
        if not isinstance(audit_path, str) or not (ROOT / audit_path).is_file():
            errors.append(f"index:{world_id}:missing audit {audit_path}")
        if world_id in worlds:
            role = worlds[world_id].get("target_role", {}).get("title")
            if entry.get("target_role") != role:
                errors.append(f"index:{world_id}:target role mismatch")
    dimensions = index.get("coverage_dimensions", [])
    if len(dimensions) != len(set(dimensions)):
        errors.append("index:duplicate coverage dimension")
    matrix = index.get("coverage_matrix", {})
    if set(matrix) != set(EXPECTED_WORLD_IDS):
        errors.append("index:coverage matrix world ids mismatch")
    for world_id, row in matrix.items():
        if set(row) != set(dimensions):
            errors.append(f"index:{world_id}:coverage columns mismatch")
        if not all(isinstance(value, bool) for value in row.values()):
            errors.append(f"index:{world_id}:coverage values must be boolean")
    return errors


def main() -> int:
    errors: list[str] = []
    for artifact in REQUIRED_ARTIFACTS:
        if not artifact.is_file():
            errors.append(f"artifact:missing {artifact.relative_to(ROOT)}")

    try:
        schema = load_json(SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001 - report exact validation blocker
        print(f"FAIL schema: {type(exc).__name__}: {exc}")
        return 1

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    try:
        index = load_json(INDEX_PATH)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL index parse: {type(exc).__name__}: {exc}")
        return 1

    worlds: dict[str, dict[str, Any]] = {}
    world_stats: dict[str, dict[str, int]] = {}
    for world_id in EXPECTED_WORLD_IDS:
        world_path = ROOT / "worlds" / f"{world_id}.json"
        if not world_path.is_file():
            errors.append(f"artifact:missing {world_path.relative_to(ROOT)}")
            continue
        try:
            world = load_json(world_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"json:{world_id}:{type(exc).__name__}:{exc}")
            continue
        worlds[world_id] = world
        world_errors, stats = validate_world(world, world_path, validator)
        world_stats[world_id] = stats
        errors.extend(f"{world_id}:{message}" for message in world_errors)

    errors.extend(validate_index(index, worlds))

    if errors:
        print(f"FAIL CandidateWorldV1 trial validation: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    for world_id in EXPECTED_WORLD_IDS:
        stats = world_stats[world_id]
        print(
            "PASS "
            f"{world_id}: schema=pass references=pass reveal=pass citations=pass "
            f"facts={stats['facts']} answers={stats['answers']} "
            f"junctions={stats['junctions']} families={stats['families']} "
            f"protected_facts={stats['protected_facts']}"
        )
    print("PASS world_index: files=5 ids=5 coverage_rows=5 audits=5")
    print("PASS required_artifacts: complete")
    print("SUMMARY worlds=5 schema_pass=5 reference_pass=5 reveal_pass=5 citation_pass=5 errors=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
