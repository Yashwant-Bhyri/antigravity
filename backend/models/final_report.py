from __future__ import annotations

import json
import re
from typing import Any


STRONG_CLAIM_VERBS = {
    "architected",
    "rebuilt",
    "built",
    "owned",
    "orchestrated",
    "engineered",
    "optimized",
    "led",
    "launched",
    "designed",
    "implemented",
    "created",
    "increased",
    "reduced",
}

PUNITIVE_PATTERNS = (
    "bad candidate",
    "no demonstrable understanding",
    "severe inability",
    "severely unable",
    "utterly failing",
    "utterly failed",
    "completely failed",
    "zero ability",
    "zero understanding",
    "failed the interview",
    "absolute lack",
)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def short_text(value: Any, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def normalize_verdict(value: Any) -> str:
    raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    mapping = {
        "STRONG_HIRE": "HIRE",
        "HIRE": "HIRE",
        "MAYBE": "MAYBE",
        "NO_HIRE": "NO HIRE",
        "NOHIRE": "NO HIRE",
        "INSUFFICIENT": "INSUFFICIENT_DATA",
        "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
        "CLAIM_RISK_FLAG": "MAYBE",
    }
    return mapping.get(raw, "INSUFFICIENT_DATA")


def _token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", text.lower())
        if token not in {"the", "and", "for", "with", "from", "that", "this", "into", "using"}
    }


def _overlap_ratio(left: str, right: str) -> float:
    lset = _token_set(left)
    rset = _token_set(right)
    if not lset or not rset:
        return 0.0
    return len(lset & rset) / max(1, min(len(lset), len(rset)))


def _claim_texts_from_resume(parsed_resume: dict | None, resume: str) -> list[dict[str, Any]]:
    parsed_resume = parsed_resume or {}
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in parsed_resume.get("claims") or []:
        if isinstance(raw, dict):
            text = short_text(raw.get("text") or raw.get("claim") or "", 360)
            if not text:
                continue
            item = dict(raw)
            item["text"] = text
        elif isinstance(raw, str) and raw.strip():
            item = {"text": short_text(raw, 360)}
        else:
            continue
        key = item["text"].lower()
        if key not in seen:
            seen.add(key)
            claims.append(item)

    for line in str(resume or "").splitlines():
        cleaned = short_text(line, 360)
        lower = cleaned.lower()
        if not cleaned or len(cleaned.split()) < 5:
            continue
        if not any(verb in lower for verb in STRONG_CLAIM_VERBS):
            continue
        key = lower
        if key in seen:
            continue
        seen.add(key)
        claims.append({"text": cleaned, "source": "resume_line"})
        if len(claims) >= 12:
            break
    return claims[:12]


def _claim_hype_level(text: str) -> str:
    lower = text.lower()
    strong_hits = [verb for verb in STRONG_CLAIM_VERBS if verb in lower]
    has_metric = bool(re.search(r"\b\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?x\b", lower))
    if len(strong_hits) >= 2 or (strong_hits and has_metric):
        return "high"
    if strong_hits or has_metric:
        return "medium"
    return "low"


def _extract_tested_claims(
    claims: list[dict[str, Any]],
    history: list[dict],
    weaknesses: list[dict],
) -> dict[str, list[dict[str, Any]]]:
    transcript = "\n".join(
        f"{turn.get('question', '')}\n{turn.get('answer', '')}"
        for turn in history
    )
    weakness_text = "\n".join(
        f"{item.get('weakness', '')} {item.get('type', '')}"
        for item in weaknesses
        if isinstance(item, dict)
    )
    tested: list[dict[str, Any]] = []
    untested: list[dict[str, Any]] = []
    for claim in claims:
        text = str(claim.get("text") or "")
        tested_score = _overlap_ratio(text, transcript)
        claim_numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
        transcript_numbers = set(re.findall(r"\d+(?:\.\d+)?", transcript))
        shared_metric = bool(claim_numbers & transcript_numbers)
        risk_score = _overlap_ratio(text, weakness_text)
        item = {
            "claim": text,
            "hype_level": _claim_hype_level(text),
            "tested": tested_score >= 0.12 or shared_metric,
            "evidence_strength": "partial" if (tested_score >= 0.12 or shared_metric) else "untested",
            "claim_risk": "material" if risk_score >= 0.20 else "unknown",
        }
        if item["tested"]:
            tested.append(item)
        else:
            untested.append(item)
    return {"tested": tested[:8], "untested": untested[:8]}


def build_interview_quality(assessment_coverage: dict | None) -> dict[str, Any]:
    coverage = assessment_coverage or {}
    reasons: list[str] = []
    score = 1.0
    distinct_surfaces = int(coverage.get("distinct_surfaces") or 0)
    high_value_tested = int(coverage.get("high_value_surfaces_tested_count") or 0)
    dominant_focus_high = safe_float(coverage.get("dominant_focus_ratio"), 0.0) > 0.70
    surface_streak_high = int(coverage.get("max_same_surface_streak") or 0) > 4
    parent_focus_dominant_but_broad = (
        dominant_focus_high
        and distinct_surfaces >= 3
        and high_value_tested >= 2
        and not surface_streak_high
    )

    if not coverage.get("application_transfer_served"):
        score -= 0.25
        reasons.append("application_transfer_not_served")
    if int(coverage.get("coverage_evaluated_dimensions") or 0) < 1:
        score -= 0.22
        reasons.append("coverage_dimensions_not_evaluated")
    if int(coverage.get("distinct_focuses") or 0) < 2 and int(coverage.get("distinct_surfaces") or 0) < 2:
        score -= 0.22
        reasons.append("too_few_role_surfaces_tested")
    if dominant_focus_high and not parent_focus_dominant_but_broad:
        score -= 0.14
        reasons.append("dominant_focus_ratio_high")
    elif parent_focus_dominant_but_broad:
        reasons.append("dominant_parent_focus_with_broad_surface_coverage")
    if surface_streak_high:
        score -= 0.14
        reasons.append("same_surface_streak_high")
    if (
        int(coverage.get("high_value_surfaces_available_count") or 0) > 0
        and int(coverage.get("high_value_surfaces_tested_count") or 0) < 1
    ):
        score -= 0.15
        reasons.append("no_high_value_role_relevant_surface_tested")

    score = round(clamp(score, 0.05, 1.0), 2)
    if score >= 0.82:
        band = "strong"
    elif score >= 0.65:
        band = "usable"
    elif score >= 0.45:
        band = "limited"
    else:
        band = "poor"
    return {
        "score": score,
        "band": band,
        "map_adherence": "not_measured",
        "role_relevance": "limited" if "no_high_value_role_relevant_surface_tested" in reasons else "usable",
        "coverage_breadth": "usable" if coverage.get("breadth_viable") else "limited",
        "tunneling_detected": any(
            reason in reasons for reason in ("dominant_focus_ratio_high", "same_surface_streak_high")
        ),
        "fairness_warnings": reasons,
    }


def build_pre_report_coverage_gate(
    assessment_coverage: dict | None,
    *,
    interview_quality: dict | None = None,
    discrepancy_level: str = "none",
) -> dict[str, Any]:
    coverage = assessment_coverage or {}
    quality = interview_quality or build_interview_quality(coverage)
    reasons: list[str] = []

    if not coverage.get("application_transfer_served"):
        reasons.append("application_transfer_not_served")
    if int(coverage.get("coverage_evaluated_dimensions") or 0) < 1:
        reasons.append("coverage_dimensions_not_evaluated")
    if int(coverage.get("distinct_focuses") or 0) < 2 and int(coverage.get("distinct_surfaces") or 0) < 2:
        reasons.append("fewer_than_two_substantive_surfaces_tested")
    if (
        int(coverage.get("high_value_surfaces_available_count") or 0) > 0
        and int(coverage.get("high_value_surfaces_tested_count") or 0) < 1
    ):
        reasons.append("no_high_value_role_relevant_surface_tested")
    if (
        safe_float(coverage.get("dominant_focus_ratio"), 0.0) > 0.70
        and int(coverage.get("distinct_focuses") or 0) < 3
        and int(coverage.get("distinct_surfaces") or 0) < 3
        and int(coverage.get("high_value_surfaces_tested_count") or 0) < 2
    ):
        reasons.append("interview_tunneled_on_one_focus")
    if int(coverage.get("max_same_surface_streak") or 0) > 4:
        reasons.append("same_surface_streak_exceeded")
    if safe_float(quality.get("score"), 1.0) < 0.45:
        reasons.append("interviewer_quality_too_low")

    return {
        "passed": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "assessment_coverage": coverage,
        "interview_quality": quality,
        "discrepancy_level": discrepancy_level,
    }


def _focus_summaries(history: list[dict]) -> dict[str, Any]:
    focus_counts: dict[str, int] = {}
    surface_counts: dict[str, int] = {}
    for turn in history:
        focus = str(turn.get("focus_label") or turn.get("focus_key") or "").strip()
        if focus:
            focus_counts[focus] = focus_counts.get(focus, 0) + 1
        surface = str(turn.get("sub_focus_label") or turn.get("sub_focus_key") or "").strip()
        if surface:
            surface_counts[surface] = surface_counts.get(surface, 0) + 1
    return {
        "focus_counts": focus_counts,
        "surface_counts": surface_counts,
        "tested_focuses": sorted(focus_counts, key=focus_counts.get, reverse=True),
        "tested_surfaces": sorted(surface_counts, key=surface_counts.get, reverse=True),
    }


def _infer_honest_admissions(history: list[dict]) -> list[dict[str, Any]]:
    patterns = (
        "i don't know",
        "i do not know",
        "not sure",
        "i didn't own",
        "i did not own",
        "to be precise",
        "i should clarify",
        "i was not responsible",
        "i don't remember",
        "i do not remember",
    )
    admissions: list[dict[str, Any]] = []
    for index, turn in enumerate(history, start=1):
        answer = str(turn.get("answer") or "")
        lower = answer.lower()
        if any(pattern in lower for pattern in patterns):
            admissions.append({
                "turn": index,
                "answer_excerpt": short_text(answer, 280),
                "interpretation": "honest_limit_or_claim_narrowing",
            })
    return admissions[:6]


def _infer_transferable_strength(history: list[dict], per_answer_scores: list[dict] | None) -> dict[str, Any]:
    score_by_turn = {}
    for fallback_index, item in enumerate(per_answer_scores or [], start=1):
        if not isinstance(item, dict):
            continue
        turn_number = int(safe_float(item.get("turn_number"), fallback_index))
        score_by_turn[turn_number] = safe_float(item.get("score"), 0.0)
    best_turn = 0
    best_score = -1.0
    for turn_num, score in score_by_turn.items():
        if score > best_score:
            best_score = score
            best_turn = turn_num
    if best_turn and best_score >= 6.0 and best_turn <= len(history):
        turn = history[best_turn - 1]
        focus = turn.get("sub_focus_label") or turn.get("focus_label") or turn.get("focus_key") or "tested area"
        return {
            "strongest_verified_signal": f"Best observed signal was in {focus}.",
            "evidence_turns": [best_turn],
            "confidence": "medium" if best_score < 8.0 else "high",
            "alternate_fit_archetypes": [str(focus)],
        }
    focus_summary = _focus_summaries(history)
    top_focus = (focus_summary.get("tested_surfaces") or focus_summary.get("tested_focuses") or ["unclear"])[0]
    return {
        "strongest_verified_signal": f"Most tested signal was around {top_focus}.",
        "evidence_turns": [],
        "confidence": "low",
        "alternate_fit_archetypes": [] if top_focus == "unclear" else [str(top_focus)],
    }


def _answer_pattern(score: float, item: dict[str, Any]) -> str:
    weakness_type = str(item.get("weakness_type") or "").strip()
    severity = str(item.get("weakness_severity") or "").strip()
    if weakness_type in {"deflection", "contradiction"} or severity == "high":
        return "challenged_or_unresolved"
    if score >= 7.5:
        return "specific_strong"
    if score >= 6.0:
        return "usable_with_gaps"
    if score >= 4.0:
        return "partial_or_shallow"
    return "weak_or_evasive"


def _recovery_signal(answer: str, previous_score: float | None, score: float) -> bool:
    lower = answer.lower()
    honest_or_corrective = any(
        phrase in lower
        for phrase in (
            "to clarify",
            "i should clarify",
            "i was wrong",
            "i don't know",
            "i do not know",
            "not sure",
            "i didn't own",
            "i did not own",
            "the denominator",
            "guardrail",
        )
    )
    improved = previous_score is not None and score - previous_score >= 1.5
    return honest_or_corrective or improved


def _role_relevance(item: dict[str, Any]) -> str:
    route = str(item.get("route_kind") or "")
    if route in {"application_transfer", "coverage_surface", "coverage_depth", "second_anchor"}:
        return "high"
    if item.get("focus_key") or item.get("sub_focus_key"):
        return "medium"
    return "unknown"


def build_turn_evidence_trail(history: list[dict], per_answer_scores: list[dict] | None) -> list[dict[str, Any]]:
    trail: list[dict[str, Any]] = []
    previous_score: float | None = None
    for fallback_index, item in enumerate(per_answer_scores or [], start=1):
        if not isinstance(item, dict):
            continue
        turn_number = int(safe_float(item.get("turn_number"), fallback_index))
        score = round(safe_float(item.get("score"), 0.0), 2)
        history_turn = history[turn_number - 1] if 0 < turn_number <= len(history) else {}
        answer = str(item.get("answer_excerpt") or history_turn.get("answer") or "")
        route = str(item.get("route_kind") or history_turn.get("route_kind") or "")
        focus_label = str(item.get("sub_focus_label") or item.get("focus_label") or history_turn.get("sub_focus_label") or history_turn.get("focus_label") or "")
        pattern = _answer_pattern(score, item)
        recovery = _recovery_signal(answer, previous_score, score)
        note_bits = []
        if focus_label:
            note_bits.append(f"Local evidence in {focus_label}")
        note_bits.append(pattern.replace("_", " "))
        if recovery:
            note_bits.append("shows recovery or calibration signal")
        trail.append({
            "turn": turn_number,
            "turn_id": item.get("turn_id") or history_turn.get("turn_id") or "",
            "local_score": score,
            "confidence": round(safe_float(item.get("confidence"), 0.0), 2),
            "question_context": route or "unknown",
            "focus_key": item.get("focus_key") or history_turn.get("focus_key") or "",
            "focus_label": item.get("focus_label") or history_turn.get("focus_label") or "",
            "sub_focus_key": item.get("sub_focus_key") or history_turn.get("sub_focus_key") or "",
            "sub_focus_label": item.get("sub_focus_label") or history_turn.get("sub_focus_label") or "",
            "answer_pattern": pattern,
            "recovery_signal": recovery,
            "role_relevance": _role_relevance(item),
            "weakness_type": item.get("weakness_type") or "",
            "weakness_severity": item.get("weakness_severity") or "",
            "reasoning_structure_score": item.get("reasoning_structure_score"),
            "reasoning_adaptability": item.get("reasoning_adaptability") or "",
            "note": "; ".join(note_bits),
        })
        previous_score = score
    return sorted(trail, key=lambda row: int(row.get("turn") or 0))


def build_progression_summary(turn_evidence_trail: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [safe_float(item.get("local_score"), 0.0) for item in turn_evidence_trail]
    if not scores:
        return {
            "trajectory": "not_measured",
            "recovery_after_challenge": "not_tested",
            "adaptability_signal": "No per-turn evidence trail was available.",
            "confidence_effect": "neutral",
        }
    midpoint = max(1, len(scores) // 2)
    first_avg = sum(scores[:midpoint]) / len(scores[:midpoint])
    second_avg = sum(scores[midpoint:]) / len(scores[midpoint:]) if scores[midpoint:] else first_avg
    delta = second_avg - first_avg
    if delta >= 1.0:
        trajectory = "improved"
    elif delta <= -1.0:
        trajectory = "declined"
    elif max(scores) - min(scores) >= 2.5:
        trajectory = "inconsistent"
    else:
        trajectory = "flat"

    recovery_count = sum(1 for item in turn_evidence_trail if item.get("recovery_signal"))
    challenged_count = sum(
        1
        for item in turn_evidence_trail
        if item.get("weakness_severity") in {"medium", "high"}
        or item.get("answer_pattern") == "challenged_or_unresolved"
    )
    if challenged_count <= 0:
        recovery = "not_tested"
    elif recovery_count / max(challenged_count, 1) >= 0.5:
        recovery = "strong"
    elif recovery_count:
        recovery = "partial"
    else:
        recovery = "weak"

    if trajectory == "improved" or recovery in {"strong", "partial"}:
        effect = "raises"
    elif trajectory == "declined" and recovery == "weak":
        effect = "lowers"
    else:
        effect = "neutral"
    return {
        "trajectory": trajectory,
        "first_half_average": round(first_avg, 2),
        "second_half_average": round(second_avg, 2),
        "recovery_after_challenge": recovery,
        "recovery_signal_count": recovery_count,
        "challenged_turn_count": challenged_count,
        "adaptability_signal": (
            "Use this as a trajectory signal, not as an averaged verdict. "
            "Local scores are context-limited and should be reconciled with coverage and interviewer quality."
        ),
        "confidence_effect": effect,
    }


def build_final_evidence_packet(
    *,
    history: list[dict],
    resume: str,
    weaknesses: list[dict],
    reasoning_signals: list[dict] | None = None,
    per_answer_scores: list[dict] | None = None,
    coverage_map: dict | None = None,
    assessment_coverage: dict | None = None,
    target_role: str = "",
    years_experience: str = "",
    parsed_resume: dict | None = None,
    discrepancy_level: str = "none",
    disengagement_level: float = 0.0,
    disengagement_triggered: bool = False,
) -> dict[str, Any]:
    parsed_resume = parsed_resume or {}
    claims = _claim_texts_from_resume(parsed_resume, resume)
    claim_groups = _extract_tested_claims(claims, history, weaknesses)
    focus_summary = _focus_summaries(history)
    interview_quality = build_interview_quality(assessment_coverage)
    coverage_gate = build_pre_report_coverage_gate(
        assessment_coverage,
        interview_quality=interview_quality,
        discrepancy_level=discrepancy_level,
    )
    turns = []
    for index, turn in enumerate(history, start=1):
        turns.append({
            "turn": index,
            "question": short_text(turn.get("question"), 650),
            "answer": short_text(turn.get("answer"), 900),
            "focus_key": turn.get("focus_key") or "",
            "focus_label": turn.get("focus_label") or "",
            "sub_focus_key": turn.get("sub_focus_key") or "",
            "sub_focus_label": turn.get("sub_focus_label") or "",
            "route_kind": turn.get("route_kind") or turn.get("answered_route_kind") or "",
        })

    avg_answer_score = None
    if per_answer_scores:
        vals = [safe_float(item.get("score"), 0.0) for item in per_answer_scores if isinstance(item, dict)]
        if vals:
            avg_answer_score = round(sum(vals) / len(vals), 2)
    turn_evidence_trail = build_turn_evidence_trail(history, per_answer_scores)
    progression_summary = build_progression_summary(turn_evidence_trail)

    risk_signals = [
        {
            "type": item.get("type", "unknown"),
            "severity": item.get("severity", "unknown"),
            "weakness": short_text(item.get("weakness"), 360),
            "focus_key": item.get("inferred_focus_key") or item.get("focus_key") or "",
        }
        for item in weaknesses[:12]
        if isinstance(item, dict)
    ]
    honest_admissions = _infer_honest_admissions(history)

    return {
        "schema_version": "final_evidence_packet_v1",
        "target_role": target_role,
        "years_experience": years_experience,
        "candidate_name": parsed_resume.get("candidate_name", ""),
        "resume_claim_calibration": {
            "claims_tested": claim_groups["tested"],
            "claims_untested": claim_groups["untested"],
            "hype_terms": sorted({
                verb
                for claim in claims
                for verb in STRONG_CLAIM_VERBS
                if verb in str(claim.get("text", "")).lower()
            }),
            "principle": "Resume intensity guides questioning depth; final judgment is based on tested performance.",
        },
        "interview_quality": interview_quality,
        "coverage_gate": coverage_gate,
        "coverage_map": coverage_map or {},
        "coverage_summary": assessment_coverage or {},
        "focus_summary": focus_summary,
        "turns": turns,
        "risk_signals": risk_signals,
        "honest_admissions": honest_admissions,
        "reasoning_signal_count": len(reasoning_signals or []),
        "avg_answer_score": avg_answer_score,
        "turn_evidence_trail": turn_evidence_trail,
        "progression_summary": progression_summary,
        "discrepancy_level": discrepancy_level,
        "disengagement": {
            "level": disengagement_level,
            "triggered": disengagement_triggered,
        },
        "ability_profile_hint": _infer_transferable_strength(history, per_answer_scores),
        "report_instructions": {
            "do_not_average_lenses": True,
            "do_not_generalize_from_one_claim": True,
            "do_not_punish_resume_hype_beyond_scoped_claim_risk": True,
            "preserve_alternate_fit_signal": True,
            "narrow_coverage_requires_insufficient_data": not coverage_gate["passed"],
        },
    }


def build_confidence_band(score: float, confidence: float, coverage_gate: dict, interview_quality: dict) -> dict[str, float]:
    quality = safe_float(interview_quality.get("score"), 0.7)
    base_spread = 1.0 + (1.0 - clamp(confidence, 0.0, 1.0)) * 2.0 + (1.0 - quality) * 1.25
    if not (coverage_gate or {}).get("passed", True):
        base_spread += 0.75
    return {
        "low": round(clamp(score - base_spread, 0.0, 10.0), 1),
        "point": round(clamp(score, 0.0, 10.0), 1),
        "high": round(clamp(score + base_spread, 0.0, 10.0), 1),
    }


def _contains_punitive_candidate_wide_language(text: str) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in PUNITIVE_PATTERNS)


def _summary_looks_incomplete(text: str) -> bool:
    stripped = (text or "").strip()
    words = re.findall(r"\b[\w'-]+\b", stripped)
    if not stripped or len(words) < 18:
        return True
    if stripped.endswith("..."):
        return False
    last_word = words[-1].lower() if words else ""
    dangling_words = {
        "and",
        "but",
        "while",
        "because",
        "although",
        "with",
        "without",
        "to",
        "for",
        "from",
        "as",
        "that",
        "the",
        "a",
        "an",
        "they",
        "he",
        "she",
        "it",
        "this",
        "which",
    }
    return bool(last_word in dangling_words and not stripped.endswith((".", "!", "?")))


def _fallback_summary(
    *,
    verdict: str,
    evidence_packet: dict,
    coverage_gate: dict,
    ability_profile: dict,
    risk_flags: list[str],
) -> str:
    role = str(evidence_packet.get("target_role") or "the target role").strip() or "the target role"
    strongest = str(ability_profile.get("strongest_verified_signal") or "").strip()
    if not strongest:
        strength_hint = evidence_packet.get("ability_profile_hint") or {}
        strongest = str(strength_hint.get("strongest_verified_signal") or "the strongest tested evidence was limited").strip()
    risk = risk_flags[0] if risk_flags else str(ability_profile.get("weakest_verified_signal") or "").strip()
    if not risk:
        risk = "the remaining risks should be resolved through targeted follow-up"
    if not coverage_gate.get("passed", True):
        reasons = ", ".join(coverage_gate.get("reasons") or ["coverage limits"])
        return (
            "The interview did not gather enough broad evidence for a definitive hire/no-hire verdict. "
            f"Current limitations: {reasons}. The strongest available signal was {strongest}. "
            "Risks should be read as scoped findings from the tested areas, not as a candidate-wide rejection."
        )
    return (
        f"For {role}, the evidence supports a {verdict.replace('_', ' ')} recommendation with scoped confidence. "
        f"The strongest tested signal was {strongest}. The main unresolved risk is {risk}. "
        "This assessment is based on interview performance and coverage quality, not resume wording alone."
    )


def _scoped_risk_flag(flag: Any, *, gate_passed: bool) -> str:
    text = short_text(flag, 420)
    if not text:
        return ""
    if gate_passed:
        return text
    if _contains_punitive_candidate_wide_language(text):
        return "Limited-evidence risk: a tested area raised concern, but coverage was not broad enough to generalize candidate-wide."
    if text.lower().startswith("limited-evidence risk:"):
        return text
    return f"Limited-evidence risk: {text}"


def _default_role_fit(verdict: str, gate_passed: bool) -> str:
    if not gate_passed:
        return "inconclusive"
    if verdict == "HIRE":
        return "strong"
    if verdict == "MAYBE":
        return "mixed"
    if verdict == "NO HIRE":
        return "weak"
    return "inconclusive"


def normalize_final_report_v2(
    report: dict[str, Any],
    evidence_packet: dict[str, Any],
    advisory_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(report or {})
    coverage_gate = evidence_packet.get("coverage_gate") or {}
    interview_quality = evidence_packet.get("interview_quality") or {}
    gate_passed = bool(coverage_gate.get("passed"))
    verdict = normalize_verdict(normalized.get("hire_recommendation"))
    score = clamp(safe_float(normalized.get("overall_score"), 0.0), 0.0, 10.0)
    confidence = clamp(safe_float(normalized.get("confidence_score"), 0.5), 0.0, 1.0)
    normalization_changes: list[str] = []

    if not gate_passed:
        verdict = "INSUFFICIENT_DATA"
        score = min(score if score > 0 else 5.0, 5.0)
        confidence = min(confidence, 0.45)

    if safe_float(interview_quality.get("score"), 1.0) < 0.45 and verdict == "NO HIRE":
        verdict = "INSUFFICIENT_DATA"
        confidence = min(confidence, 0.45)

    summary = short_text(
        normalized.get("candidate_safe_summary")
        or normalized.get("recruiter_summary")
        or normalized.get("summary"),
        1200,
    )
    if not gate_passed and (not summary or _contains_punitive_candidate_wide_language(summary)):
        reasons = ", ".join(coverage_gate.get("reasons") or ["coverage limits"])
        summary = (
            "The interview did not gather enough broad evidence for a definitive hire/no-hire verdict. "
            f"Current limitations: {reasons}. Any risks below should be read as scoped findings from the tested areas, not as a candidate-wide rejection."
        )

    risk_flags = normalized.get("risk_flags")
    if not isinstance(risk_flags, list):
        risk_flags = []
    risk_flags = [
        scoped
        for scoped in (_scoped_risk_flag(flag, gate_passed=gate_passed) for flag in risk_flags)
        if scoped
    ]
    if not gate_passed and "Assessment coverage was too narrow for a definitive hire/no-hire verdict." not in risk_flags:
        risk_flags.append("Assessment coverage was too narrow for a definitive hire/no-hire verdict.")

    strengths = normalized.get("strengths")
    if not isinstance(strengths, list):
        strengths = []
    tested_strengths = normalized.get("tested_strengths")
    if not isinstance(tested_strengths, list):
        tested_strengths = strengths[:]
    tested_risks = normalized.get("tested_risks")
    if not isinstance(tested_risks, list):
        tested_risks = risk_flags[:]

    ability_profile = normalized.get("ability_profile")
    if not isinstance(ability_profile, dict):
        ability_profile = {}
    ability_profile = {
        "strongest_verified_signal": ability_profile.get("strongest_verified_signal")
        or (evidence_packet.get("ability_profile_hint") or {}).get("strongest_verified_signal")
        or "",
        "weakest_verified_signal": ability_profile.get("weakest_verified_signal") or "",
        "alternate_fit_archetypes": ability_profile.get("alternate_fit_archetypes")
        or (evidence_packet.get("ability_profile_hint") or {}).get("alternate_fit_archetypes")
        or [],
        "target_role_fit": ability_profile.get("target_role_fit") or _default_role_fit(verdict, gate_passed),
        "role_fit_explanation": ability_profile.get("role_fit_explanation")
        or "Role fit is based on tested evidence and coverage quality, not resume wording alone.",
    }

    role_fit_profile = normalized.get("role_fit_profile")
    if not isinstance(role_fit_profile, dict):
        role_fit_profile = {}
    role_fit_profile = {
        "target_role_fit": role_fit_profile.get("target_role_fit") or ability_profile["target_role_fit"],
        "best_fit_archetype": role_fit_profile.get("best_fit_archetype")
        or (ability_profile.get("alternate_fit_archetypes") or ["unclear"])[0],
        "strongest_signal": role_fit_profile.get("strongest_signal") or ability_profile["strongest_verified_signal"],
        "largest_unresolved_risk": role_fit_profile.get("largest_unresolved_risk") or (risk_flags[0] if risk_flags else ""),
        "alternate_fit_notes": role_fit_profile.get("alternate_fit_notes") or "",
    }

    alternate_fit_present = bool(
        ability_profile.get("strongest_verified_signal")
        and ability_profile.get("alternate_fit_archetypes")
    )
    if gate_passed and verdict == "NO HIRE" and score >= 6.0 and alternate_fit_present:
        verdict = "MAYBE"
        confidence = min(confidence, 0.75)
        risk_note = "Target-role risk remains, but verified adjacent strengths prevent a flat candidate-wide rejection."
        if risk_note not in risk_flags:
            risk_flags.append(risk_note)
        normalization_changes.append(
            "Verdict softened from NO HIRE to MAYBE because the report score and verified alternate-fit evidence contradicted a flat rejection."
        )

    resume_claim_calibration = normalized.get("resume_claim_calibration")
    if not isinstance(resume_claim_calibration, dict):
        resume_claim_calibration = {}
    evidence_claims = evidence_packet.get("resume_claim_calibration") or {}
    resume_claim_calibration = {
        "claims_tested": resume_claim_calibration.get("claims_tested") or evidence_claims.get("claims_tested") or [],
        "claims_substantiated": resume_claim_calibration.get("claims_substantiated") or [],
        "claims_partially_substantiated": resume_claim_calibration.get("claims_partially_substantiated") or [],
        "claims_not_substantiated": resume_claim_calibration.get("claims_not_substantiated") or [],
        "claims_untested": resume_claim_calibration.get("claims_untested") or evidence_claims.get("claims_untested") or [],
        "impact_on_verdict": resume_claim_calibration.get("impact_on_verdict") or ("scoped" if gate_passed else "inconclusive"),
        "principle": evidence_claims.get("principle"),
    }

    lens_findings = normalized.get("lens_findings")
    if not isinstance(lens_findings, dict):
        lens_findings = {}
    for lens in (
        "claim_integrity_lens",
        "role_technical_lens",
        "reasoning_communication_lens",
        "human_calibration_lens",
        "transferable_strength_lens",
    ):
        lens_findings.setdefault(lens, {
            "positive_signals": [],
            "negative_signals": [],
            "inconclusive_signals": [],
            "evidence_refs": [],
            "confidence": "low" if not gate_passed else "medium",
            "summary": "",
        })

    honest_admissions = evidence_packet.get("honest_admissions") or []
    if honest_admissions:
        human_lens = lens_findings.setdefault("human_calibration_lens", {})
        positive_signals = human_lens.get("positive_signals")
        if not isinstance(positive_signals, list):
            positive_signals = []
        human_text = json.dumps(human_lens, ensure_ascii=True).lower()
        if not any(term in human_text for term in ("honest", "narrow", "clarif", "candid", "integrity", "calibrat")):
            positive_signals.append("Candidate honestly narrowed or clarified claim ownership during the interview.")
            human_lens["positive_signals"] = positive_signals
            refs = human_lens.get("evidence_refs")
            if not isinstance(refs, list):
                refs = []
            for admission in honest_admissions[:2]:
                turn = admission.get("turn") if isinstance(admission, dict) else None
                if turn and turn not in refs:
                    refs.append(turn)
            human_lens["evidence_refs"] = refs
            summary_text = str(human_lens.get("summary") or "").strip()
            if not summary_text:
                human_lens["summary"] = "The candidate showed positive calibration by narrowing or clarifying the scope of their claims."
            normalization_changes.append("Honest claim-narrowing signal preserved in the human calibration lens.")

    if _summary_looks_incomplete(summary):
        summary = _fallback_summary(
            verdict=verdict,
            evidence_packet=evidence_packet,
            coverage_gate=coverage_gate,
            ability_profile=ability_profile,
            risk_flags=risk_flags,
        )
        normalization_changes.append("Incomplete report summary replaced with evidence-packet summary.")

    reviewer_concerns = []
    if isinstance(advisory_review, dict):
        raw_concerns = advisory_review.get("concerns") or advisory_review.get("reviewer_concerns") or []
        if isinstance(raw_concerns, list):
            reviewer_concerns = [short_text(item, 300) for item in raw_concerns if str(item).strip()]
    accepted_changes = normalization_changes[:]
    if not gate_passed:
        accepted_changes.append("Coverage gate applied before final prose; verdict/prose constrained to insufficient data.")
    if risk_flags != normalized.get("risk_flags"):
        accepted_changes.append("Risk language scoped to tested evidence.")
    rejected_changes = []
    if reviewer_concerns and not accepted_changes:
        rejected_changes.append("Reviewer concerns were recorded as advisory; deterministic gates did not require a report change.")
    review_reconciliation = normalized.get("review_reconciliation")
    if not isinstance(review_reconciliation, dict):
        review_reconciliation = {}
    review_reconciliation = {
        "reviewer_concerns": review_reconciliation.get("reviewer_concerns") or reviewer_concerns,
        "accepted_changes": review_reconciliation.get("accepted_changes") or accepted_changes,
        "rejected_changes": review_reconciliation.get("rejected_changes") or rejected_changes,
        "review_model": review_reconciliation.get("review_model") or (advisory_review or {}).get("model", ""),
    }

    normalized.update({
        "schema_version": "final_report_v2",
        "hire_recommendation": verdict,
        "overall_score": round(score, 1),
        "confidence_score": round(confidence, 2),
        "confidence_band": normalized.get("confidence_band")
        if isinstance(normalized.get("confidence_band"), dict)
        else build_confidence_band(score, confidence, coverage_gate, interview_quality),
        "coverage_gate": coverage_gate,
        "interview_quality": interview_quality,
        "role_fit_profile": role_fit_profile,
        "ability_profile": ability_profile,
        "resume_claim_calibration": resume_claim_calibration,
        "lens_findings": lens_findings,
        "tested_strengths": tested_strengths,
        "tested_risks": tested_risks,
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "strengths": strengths,
        "claim_findings": normalized.get("claim_findings") if isinstance(normalized.get("claim_findings"), list) else [],
        "recommended_followups": normalized.get("recommended_followups") if isinstance(normalized.get("recommended_followups"), list) else [],
        "candidate_safe_summary": summary,
        "recruiter_summary": short_text(normalized.get("recruiter_summary") or summary, 1400),
        "summary": summary,
        "review_reconciliation": review_reconciliation,
        "final_evidence_packet": evidence_packet,
    })
    normalized.setdefault("untested_dimensions", [])
    normalized.setdefault("breakdown", {
        "reasoning": "inconclusive",
        "technical_depth": "inconclusive",
        "communication": "inconclusive",
        "adaptability": "inconclusive",
    })
    normalized.setdefault("failure_surface", {})
    normalized.setdefault("claim_credibility_risk", {"level": "not_tested", "detail": ""})
    return normalized
