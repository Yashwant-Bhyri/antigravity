#!/usr/bin/env python3
"""Materialize physically separate CandidateWorldV1 projections.

The base worlds are immutable inputs.  Actor and interviewer views are
redacted copies with deliberately different shapes; evaluator-only material
is retained only in the evaluator projection.  The command refuses to
overwrite projection files unless --force is supplied.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
WORLD_DIR = ROOT / "worlds"
PROJECTION_DIR = ROOT / "projections"
MANIFEST_PATH = ROOT / "projection_manifest.json"

BEHAVIOR_CLASSES = {
    "broad": "Answer at a high level; expand only when the question identifies one concrete artifact, decision, or boundary.",
    "sharp": "Give concrete detail for the requested eligible artifact, sequence, decision, or boundary.",
    "repeated": "Do not invent novelty. Briefly restate the known answer, name the missing focus, or ask to move on.",
    "unfair": "State the knowledge, ownership, memory, or confidentiality boundary and offer a fair abstraction.",
    "ambiguous": "Name the ambiguity and answer one reasonable interpretation or ask which interpretation matters.",
    "compound": "Answer one bounded component, state what remains outside scope, and do not fabricate the rest.",
    "irrelevant": "Answer naturally if the topic is eligible, but do not infer that it has special hiring importance.",
    "ownership": "State the narrow personal, team, partner, and unowned boundaries without widening any layer.",
}

def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def text_of(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    if isinstance(value, str):
        return value
    return ""


def projection_text(value: Any) -> str:
    """Return source text verbatim; projection boundaries never rewrite prose."""
    return text_of(value)


def safe_cited_text(value: Any) -> dict[str, Any]:
    return {"text": projection_text(value)}


def identity_view(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": identity["name"],
        "pronouns": identity["pronouns"],
        "location": identity["location"],
        "years_experience": identity["years_experience"],
        "current_title": identity["current_title"],
        "biography": safe_cited_text(identity["biography"]),
        "non_evaluative_identity_note": identity["non_evaluative_identity_note"],
    }


def role_view(role: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": role["title"],
        "level": role["level"],
        "role_family": role["role_family"],
        "hiring_context": safe_cited_text(role["hiring_context"]),
        "responsibilities": [safe_cited_text(item) for item in role["responsibilities"]],
    }


def resume_view(resume: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": resume["text"],
        "claims": [
            {
                "claim_id": claim["claim_id"],
                "claim_text": claim["claim_text"],
                "claim_type": claim["claim_type"],
            }
            for claim in resume["claims"]
        ],
    }


def eligible_fact_view(fact: dict[str, Any], eligible_ids: set[str]) -> dict[str, Any]:
    ownership = fact["ownership"]
    disclosure = fact["disclosure"]
    return {
        "fact_id": fact["fact_id"],
        "label": projection_text(fact["label"]),
        "statement_text": projection_text(fact["statement"]),
        "category": fact["category"],
        "ownership": {
            "status": ownership["status"],
            "scope": projection_text(ownership["scope"]),
            "boundary_text": projection_text(ownership["boundary_text"]),
            "owned_by": projection_text(ownership["owned_by"]),
            "ownership_evidence_ids": [
                item for item in ownership.get("ownership_evidence_ids", []) if item in eligible_ids
            ],
        },
        "disclosure": {
            "eligibility": disclosure["eligibility"],
            "prerequisite_fact_ids": [item for item in disclosure.get("prerequisite_fact_ids", []) if item in eligible_ids],
            "earliest_turn": disclosure["earliest_turn"],
            "reveal_trigger": projection_text(disclosure["reveal_trigger"]),
            "candidate_can_volunteer": disclosure["candidate_can_volunteer"],
            "allowed_summary": projection_text(disclosure["allowed_summary"]),
            "prohibited_expansion": [projection_text(item) for item in disclosure.get("prohibited_expansion", [])],
        },
    }


def behavior_view(profile: dict[str, Any], eligible_ids: set[str]) -> dict[str, Any]:
    """Keep behavioral variation while removing fact-specific future instructions."""
    source_text = json.dumps(profile, ensure_ascii=False).lower()
    if "nervous" in source_text or "anxious" in source_text or "shutdown" in source_text:
        style = "Nervous and brief early; concrete detail becomes easier after a bounded, non-leading prompt."
        short_behavior = "A broad or multi-part question may receive a very short answer or a pause."
    elif "fluent" in source_text or "conceptual" in source_text:
        style = "Fluent and conceptually expansive; concrete detail becomes stronger under a falsifiable prompt."
        short_behavior = "A confident headline may come before the supporting caveat or example."
    elif "composed" in source_text or "persuasive" in source_text:
        style = "Composed and decision-oriented; precise detail is available when asked for one metric, tradeoff, or boundary."
        short_behavior = "A confident headline may precede denominator, comparison, or ownership detail."
    elif "defensive" in source_text or "guarded" in source_text:
        style = "Direct when concrete and briefly guarded around disputed scope; engagement improves after a fair boundary reset."
        short_behavior = "A scope challenge may receive a qualified or guarded headline before the narrower boundary."
    else:
        style = "Calm and concise; the headline comes first and concrete detail follows a bounded evidence question."
        short_behavior = "A broad question may receive only the first salient layer until the focus is narrowed."

    result: dict[str, Any] = {
        "baseline": {
            "style": style,
            "truth_rule": "Behavior may vary with the question and fatigue, but facts and ownership never change.",
        },
        "speaking_pattern": style,
        "short_answer_behavior": {
            "condition": "The interviewer asks a broad, abstract, repeated, or compound question.",
            "behavior": short_behavior,
            "actor_must_not_infer": [
                "Do not disclose a hidden fact merely because the interviewer wants more evidence.",
                "Do not treat a short answer as permission to invent or widen ownership.",
            ],
        },
        "response_policies": [],
        "correction_behavior": {
            "condition": "An earlier statement is too broad, incomplete, or contradicted by a fair new detail.",
            "behavior": "Narrow or correct the statement, preserve what was true, and state the relevant ownership or memory boundary.",
            "actor_must_not_infer": ["A candid correction is not an automatic dishonesty confession."],
        },
        "contradiction_behavior": {
            "condition": "The interviewer supplies an incorrect premise about ownership, capability, sequence, or a protected detail.",
            "behavior": "Reject only the incorrect premise, state the eligible boundary, and return to the concrete work that can be described.",
            "actor_must_not_infer": ["Do not accept interviewer-supplied facts that are not independently eligible."],
        },
        "fatigue_phases": [
            {"phase": "early", "observable_behavior": "Speech follows the baseline style and may be less detailed before a fair focus is established."},
            {"phase": "middle", "observable_behavior": "A fair bounded exchange may improve detail; the actor still answers only from eligible facts."},
            {"phase": "late", "observable_behavior": "Repetition or unfair pressure may shorten answers or increase frustration without changing truth."},
        ],
    }
    generic_conditions = {
        "broad": "The interviewer asks for a broad overview or combines several layers.",
        "sharp": "The interviewer asks for one concrete artifact, sequence, decision, or boundary.",
        "repeated": "The interviewer repeats an unresolved question without narrowing its focus.",
        "unfair": "The interviewer requests protected, unowned, unavailable, or unsupported detail.",
        "ambiguous": "The question has more than one reasonable interpretation.",
        "compound": "The question combines multiple components or ownership layers.",
        "irrelevant": "The question concerns a side topic or curiosity outside the main role evidence.",
        "ownership": "The interviewer asks who owned which layer or decision.",
    }
    for policy in profile.get("response_policies", []):
        question_class = policy["question_class"]
        result["response_policies"].append({
            "policy_id": policy["policy_id"],
            "question_class": question_class,
            "condition": generic_conditions.get(question_class, generic_conditions["broad"]),
            "answer_shape": BEHAVIOR_CLASSES.get(question_class, BEHAVIOR_CLASSES["broad"]),
            "visible_fact_ids": [item for item in policy.get("fact_ids", []) if item in eligible_ids],
        })
    return result


def private_fact_view(fact: dict[str, Any]) -> dict[str, Any]:
    """Candidate truth and disclosure metadata, with evaluator scoring removed."""
    return {
        "fact_id": fact["fact_id"],
        "label": fact["label"],
        "statement": copy.deepcopy(fact["statement"]),
        "category": fact["category"],
        "truth_status": fact["truth_status"],
        "ownership": copy.deepcopy(fact["ownership"]),
        "disclosure": copy.deepcopy(fact["disclosure"]),
        "relations": copy.deepcopy(fact.get("relations", [])),
    }


def private_behavior_model(profile: dict[str, Any]) -> dict[str, Any]:
    """Retain candidate behavior, excluding interviewer-facing strategy notes."""
    result = copy.deepcopy(profile)
    result.pop("fairness_notes", None)
    for phase in result.get("fatigue_evolution", []):
        phase.pop("fair_interviewer_response", None)
        phase.pop("invalid_interviewer_response", None)
    return result


def actor_private_projection(world: dict[str, Any]) -> dict[str, Any]:
    return {
        "projection_schema_version": "candidate_projection_v1",
        "projection_type": "actor_private",
        "world_id": world["world_id"],
        "identity": identity_view(world["identity"]),
        "role_context": role_view(world["target_role"]),
        "resume": resume_view(world["resume"]),
        "factual_truth": [private_fact_view(fact) for fact in world["evidence_units"]],
        "protected_boundaries": [
            {
                "boundary_id": boundary["boundary_id"],
                "description": copy.deepcopy(boundary["description"]),
                "fact_ids": copy.deepcopy(boundary.get("fact_ids", [])),
                "eligible_behavior": boundary["eligible_behavior"],
            }
            for boundary in world["protected_boundaries"]
        ],
        "behavior_model": private_behavior_model(world["candidate_behavior_profile"]),
        "actor_constraints": [
            "Use only facts admitted by the trusted disclosure controller for the current turn.",
            "Preserve every fact's statement, ownership boundary, and disclosure restriction.",
            "Never invent facts, widen ownership, or disclose protected values.",
            "A candid correction supersedes the prior claim without creating an automatic deception confession.",
        ],
    }


def actor_turn_prompt_projection(
    world: dict[str, Any],
    turn_number: int,
    already_revealed_fact_ids: set[str],
    newly_granted_fact_ids: set[str],
) -> dict[str, Any]:
    granted_ids = set(already_revealed_fact_ids) | set(newly_granted_fact_ids)
    return {
        "projection_schema_version": "candidate_projection_v1",
        "projection_type": "actor_turn_prompt",
        "world_id": world["world_id"],
        "identity": identity_view(world["identity"]),
        "role_context": role_view(world["target_role"]),
        "resume": resume_view(world["resume"]),
        "turn_context": {
            "turn_number": turn_number,
            "already_revealed_fact_ids": sorted(already_revealed_fact_ids),
            "newly_granted_fact_ids": sorted(newly_granted_fact_ids),
            "granted_fact_ids": sorted(granted_ids),
            "controller_authority": "trusted_disclosure_controller_only",
            "question_semantics_used": False,
        },
        "granted_facts": [
            eligible_fact_view(fact, granted_ids)
            for fact in world["evidence_units"]
            if fact["fact_id"] in granted_ids
        ],
        "behavior_policy": behavior_view(world["candidate_behavior_profile"], granted_ids),
        "actor_constraints": [
            "Use only granted_fact_ids for factual speech and machine-readable citations.",
            "Do not self-unlock a fact from the question, a leading premise, or general model knowledge.",
            "Preserve visible ownership and protected boundaries exactly.",
            "If a fact is not granted, say that it is unknown, unavailable, or outside ownership when appropriate.",
        ],
    }


def interviewer_projection(world: dict[str, Any]) -> dict[str, Any]:
    return {
        "projection_schema_version": "candidate_projection_v1",
        "projection_type": "interviewer_visible",
        "world_id": world["world_id"],
        "resume": resume_view(world["resume"]),
        "conversation_events": [],
    }


def evaluator_projection(world: dict[str, Any]) -> dict[str, Any]:
    facts = copy.deepcopy(world["evidence_units"])
    fact_ids = [fact["fact_id"] for fact in facts]
    return {
        "projection_schema_version": "candidate_projection_v1",
        "projection_type": "evaluator_only",
        "world_id": world["world_id"],
        "frozen_truth": copy.deepcopy(world),
        "evidence_graph": {
            "fact_ids": fact_ids,
            "evidence_units": facts,
            "relationships": [
                {
                    "source_fact_id": fact["fact_id"],
                    "relations": copy.deepcopy(fact.get("relations", [])),
                }
                for fact in facts
            ],
        },
        "attribution_rules": [
            {
                "rule_id": "ownership_is_fact_scoped",
                "text": "Use each evidence unit's ownership status, scope, boundary, and owner exactly; paraphrase cannot widen it.",
                "fact_ids": fact_ids,
            },
            {
                "rule_id": "truth_status_is_typed",
                "text": "Distinguish true, qualified, protected, unavailable, unknown, and superseded evidence rather than collapsing them into a verdict.",
                "fact_ids": fact_ids,
            },
            {
                "rule_id": "correction_updates_active_truth",
                "text": "Apply explicit correction and supersession relationships before interpreting a contradiction; a candid correction is not automatically deception.",
                "fact_ids": fact_ids,
            },
            {
                "rule_id": "interviewer_failure_is_separate",
                "text": "When the frozen world marks an area protected, unowned, untested, or missed because of interviewer behavior, preserve that distinction in the evidence profile.",
                "fact_ids": fact_ids,
            },
        ],
        "acceptable_move_sets": {
            "families": copy.deepcopy(world["acceptable_move_families"]),
            "junctions": copy.deepcopy(world["representative_junctions"]),
            "emergent_surfaces": copy.deepcopy(world["emergent_surfaces"]),
        },
        "invalid_reality_violations": copy.deepcopy(world["hard_invalid_moves"]),
        "sufficiency_conditions": copy.deepcopy(world["evidence_sufficiency"]),
    }


def write_json(path: Path, value: dict[str, Any], force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing projection: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_paths() -> list[Path]:
    paths = list(sorted(WORLD_DIR.glob("world_*.json")))
    paths.extend(
        ROOT / name
        for name in (
            "candidate_world_v1.schema.json",
            "projection_v1.schema.json",
            "materialize_projections.py",
            "disclosure_controller.py",
            "validate_actor_response.py",
            "check_projections.py",
        )
    )
    return paths


def projection_paths() -> list[Path]:
    return sorted(path for path in PROJECTION_DIR.glob("*/*.json") if path.is_file())


def build_manifest() -> dict[str, Any]:
    return {
        "manifest_version": "candidate_projection_manifest_v1",
        "purpose": "Reproducible, isolated CandidateWorldV1 projection freeze.",
        "materializer": "materialize_projections.py",
        "verify_command": "python3 data/candidate_worlds/luna_trial_v1/materialize_projections.py --verify",
        "source_files": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in source_paths()
        },
        "projection_files": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in projection_paths()
        },
        "projection_counts": {
            "worlds": 5,
            "actor_private": len(list((PROJECTION_DIR / "actor_private").glob("*.json"))),
            "actor_turn_prompt": len(list((PROJECTION_DIR / "actor").glob("*.json"))),
            "interviewer": len(list((PROJECTION_DIR / "interviewer").glob("*.json"))),
            "evaluator": len(list((PROJECTION_DIR / "evaluator").glob("*.json"))),
        },
        "manifest_hash_policy": "The manifest intentionally excludes its own hash to avoid circular self-reference.",
    }


def verify_manifest() -> int:
    if not MANIFEST_PATH.exists():
        print(f"FAIL projection manifest missing: {MANIFEST_PATH}")
        return 1
    manifest = load_json(MANIFEST_PATH)
    expected_sources = {str(path.relative_to(ROOT)): sha256(path) for path in source_paths()}
    expected_projections = {str(path.relative_to(ROOT)): sha256(path) for path in projection_paths()}
    errors: list[str] = []
    if manifest.get("source_files") != expected_sources:
        errors.append("source file hash/list drift")
    if manifest.get("projection_files") != expected_projections:
        errors.append("projection file hash/list drift")
    if errors:
        print(f"FAIL projection manifest verification: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"PASS projection manifest verified sources={len(expected_sources)} projections={len(expected_projections)} writes=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite projection files")
    parser.add_argument("--verify", action="store_true", help="verify manifest hashes without writing")
    args = parser.parse_args()
    if args.verify:
        if args.force:
            raise SystemExit("--verify and --force are mutually exclusive")
        return verify_manifest()
    worlds = sorted(WORLD_DIR.glob("world_*.json"))
    if len(worlds) != 5:
        raise SystemExit(f"expected 5 base worlds, found {len(worlds)}")
    for path in worlds:
        world = load_json(path)
        stem = path.stem
        initial_grants = {
            fact["fact_id"]
            for fact in world["evidence_units"]
            if fact["disclosure"]["eligibility"] == "eligible"
            and fact["disclosure"]["earliest_turn"] <= 0
            and not fact["disclosure"].get("prerequisite_fact_ids")
        }
        write_json(PROJECTION_DIR / "actor_private" / f"{stem}.json", actor_private_projection(world), args.force)
        write_json(
            PROJECTION_DIR / "actor" / f"{stem}.json",
            actor_turn_prompt_projection(world, 0, set(), initial_grants),
            args.force,
        )
        write_json(PROJECTION_DIR / "interviewer" / f"{stem}.json", interviewer_projection(world), args.force)
        write_json(PROJECTION_DIR / "evaluator" / f"{stem}.json", evaluator_projection(world), args.force)
        print(f"MATERIALIZED {world['world_id']}")
    if MANIFEST_PATH.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing manifest: {MANIFEST_PATH}; rerun with --force")
    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(build_manifest(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"MANIFEST {MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
