#!/usr/bin/env python3
"""Trusted, explicit disclosure controller for CandidateWorldV1 actor turns.

The controller accepts fact IDs from an external trusted caller.  It never
receives or interprets question semantics, so the actor cannot unlock facts by
asking for them, following a leading premise, or relying on general knowledge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from materialize_projections import WORLD_DIR, actor_turn_prompt_projection, load_json, write_json


class DisclosureError(ValueError):
    pass


def _fact_map(world: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {fact["fact_id"]: fact for fact in world["evidence_units"]}


def _as_set(values: Iterable[str], label: str) -> set[str]:
    result = list(values)
    if len(result) != len(set(result)):
        raise DisclosureError(f"{label} contains duplicate fact IDs")
    return set(result)


def validate_grant(
    world: dict[str, Any],
    turn_number: int,
    already_revealed_fact_ids: Iterable[str],
    newly_granted_fact_ids: Iterable[str],
) -> tuple[set[str], set[str]]:
    if turn_number < 0:
        raise DisclosureError("turn_number must be non-negative")
    facts = _fact_map(world)
    already = _as_set(already_revealed_fact_ids, "already_revealed_fact_ids")
    newly = _as_set(newly_granted_fact_ids, "newly_granted_fact_ids")
    unknown = (already | newly) - set(facts)
    if unknown:
        raise DisclosureError(f"unknown fact IDs: {sorted(unknown)}")
    overlap = already & newly
    if overlap:
        raise DisclosureError(f"new facts already revealed: {sorted(overlap)}")

    for label, ids in (("already revealed", already), ("newly granted", newly)):
        for fact_id in sorted(ids):
            fact = facts[fact_id]
            disclosure = fact["disclosure"]
            eligibility = disclosure["eligibility"]
            if eligibility in {"protected", "unavailable"}:
                raise DisclosureError(f"{label} fact is protected or unavailable: {fact_id}")
            if disclosure["earliest_turn"] > turn_number:
                raise DisclosureError(
                    f"{label} fact is not available at turn {turn_number}: {fact_id}"
                )
            prerequisites = set(disclosure.get("prerequisite_fact_ids", []))
            if not prerequisites.issubset(already):
                missing = sorted(prerequisites - already)
                raise DisclosureError(f"{label} fact missing already-revealed prerequisites for {fact_id}: {missing}")
            if label == "newly granted" and eligibility not in {"eligible", "conditional"}:
                raise DisclosureError(f"newly granted fact has unsupported eligibility {eligibility}: {fact_id}")

    return already, newly


def issue_actor_turn(
    world: dict[str, Any],
    turn_number: int,
    already_revealed_fact_ids: Iterable[str],
    newly_granted_fact_ids: Iterable[str],
) -> dict[str, Any]:
    already, newly = validate_grant(
        world,
        turn_number,
        already_revealed_fact_ids,
        newly_granted_fact_ids,
    )
    return actor_turn_prompt_projection(world, turn_number, already, newly)


def parse_world(world_id: str) -> dict[str, Any]:
    path = WORLD_DIR / f"{world_id}.json"
    if not path.exists():
        raise DisclosureError(f"unknown world: {world_id}")
    return load_json(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--turn", type=int, required=True)
    parser.add_argument("--already-revealed", nargs="*", default=[])
    parser.add_argument("--grant", nargs="*", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true", help="allow --output to overwrite")
    args = parser.parse_args()
    try:
        prompt = issue_actor_turn(
            parse_world(args.world_id),
            args.turn,
            args.already_revealed,
            args.grant,
        )
        rendered = json.dumps(prompt, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            write_json(args.output, prompt, args.force)
        else:
            print(rendered, end="")
        return 0
    except DisclosureError as error:
        print(f"FAIL disclosure: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
