#!/usr/bin/env python3
"""Validate that an actor response cites only facts granted for its turn."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_response(prompt: dict[str, Any], response: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if prompt.get("projection_type") != "actor_turn_prompt":
        errors.append("prompt is not an actor_turn_prompt projection")
        return errors
    required_prompt = {"turn_context", "granted_facts"}
    missing_prompt = required_prompt - set(prompt)
    if missing_prompt:
        errors.append(f"prompt missing fields: {sorted(missing_prompt)}")
        return errors
    granted = set(prompt["turn_context"].get("granted_fact_ids", []))
    prompt_fact_ids = {fact.get("fact_id") for fact in prompt["granted_facts"]}
    if prompt_fact_ids != granted:
        errors.append("prompt granted_fact_ids do not match granted_facts")

    required_response = {
        "answer_text",
        "factual_clauses",
        "disclosed_fact_ids",
        "behavior_mode",
        "boundary_action",
        "correction",
        "uncertainty",
    }
    missing = required_response - set(response)
    if missing:
        errors.append(f"response missing fields: {sorted(missing)}")
        return errors

    cited: set[str] = set()
    for index, clause in enumerate(response["factual_clauses"]):
        if not isinstance(clause, dict) or not isinstance(clause.get("fact_ids"), list):
            errors.append(f"factual_clauses[{index}] must contain a fact_ids array")
            continue
        cited.update(clause["fact_ids"])
    disclosed = set(response.get("disclosed_fact_ids", []))
    correction = response.get("correction", {})
    if isinstance(correction, dict):
        cited.update(correction.get("superseded_fact_ids", []))
        cited.update(correction.get("active_fact_ids", []))
    if not cited.issubset(granted):
        errors.append(f"response cites facts not granted for this turn: {sorted(cited - granted)}")
    if not disclosed.issubset(granted):
        errors.append(f"response discloses facts not granted for this turn: {sorted(disclosed - granted)}")
    if not cited.issubset(disclosed | granted):
        errors.append("response citation scope is inconsistent")
    if not isinstance(response.get("answer_text"), str):
        errors.append("answer_text must be a string")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--response", type=Path, help="JSON response path; otherwise read stdin")
    args = parser.parse_args()
    prompt = load(args.prompt)
    response = load(args.response) if args.response else json.load(sys.stdin)
    errors = validate_response(prompt, response)
    if errors:
        print(f"FAIL actor response validation: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"PASS actor response citations within granted set ({len(prompt['turn_context']['granted_fact_ids'])} granted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
