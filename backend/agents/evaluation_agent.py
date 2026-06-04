import asyncio
import json
import os
from typing import Any

from backend.models.final_report import (
    build_final_evidence_packet,
    normalize_final_report_v2,
)
from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter


PER_ANSWER_PROMPT = """Evaluate this single interview answer.

Score the answer relative to the expected role/experience level provided.
Do not punish modest claims for lacking senior-level ownership. Reward honest clarification.

Scoring criteria:
1. Problem framing (0-2): Did they define the problem clearly before solving?
2. Logical reasoning (0-3): Is the reasoning coherent and stepwise?
3. Technical correctness (0-3): Are the technical facts accurate?
4. Production awareness (0-2): Do they consider real-world constraints?

Return JSON:
{
  "score": <total 0-10>,
  "breakdown": {
    "problem_framing": <0-2>,
    "logical_reasoning": <0-3>,
    "technical_correctness": <0-3>,
    "production_awareness": <0-2>
  },
  "confidence": <0.0-1.0>
}"""


_ANALYST_PER_ANSWER_PROMPT = """Evaluate this single interview answer for an analyst or product role.

Score the answer relative to the expected role/experience level provided.
Reward strong outcome reasoning, experimental thinking, and measurement validity.

Scoring criteria:
1. Problem framing (0-2): Did they clearly define the problem and its success metric?
2. Logical reasoning (0-3): Is the reasoning coherent? Do they establish cause vs correlation?
3. Measurement validity (0-3): Is the metric well-defined? Do they question baselines and denominators?
4. Business impact awareness (0-2): Do they connect analysis to business outcomes and stakeholder needs?

Return JSON:
{
  "score": <total 0-10>,
  "breakdown": {
    "problem_framing": <0-2>,
    "logical_reasoning": <0-3>,
    "measurement_validity": <0-3>,
    "business_impact_awareness": <0-2>
  },
  "confidence": <0.0-1.0>
}"""


FULL_INTERVIEW_PROMPT = """You are writing Antigravity's final interview report.

You receive a FINAL_EVIDENCE_PACKET. Treat it as the source of truth. The report is recruiter-facing, candidate-safe, and evidence-first.

Core philosophy:
- The report measures tested ability and role fit. It does not try to prove or disprove the resume as the main objective.
- Resume hype words such as architected, rebuilt, owned, engineered, orchestrated, optimized, launched, or led guide questioning depth, not final punishment.
- Claim risk is scoped to the specific claim unless broad, role-critical, tested failures support a wider conclusion.
- Do not average lenses mathematically. Synthesize contextually using role relevance, evidence depth, severity, and interview coverage.
- Preserve strongest verified and alternate-fit signals even when target-role fit is weak.
- Treat turn_evidence_trail as a sequence of local observations, not as an averaging machine. Use progression_summary to reason about improvement, decline, recovery after challenge, or repeated breakdown.
- If coverage_gate.passed is false, the final recommendation must be INSUFFICIENT_DATA and the prose must not sound like candidate-wide rejection.
- NO HIRE requires broad, tested, role-relevant failure and adequate interviewer quality.
- Do not call an interview tunneled merely because the same parent experience appears often. Treat it as tunneled only when the same sub-focus/surface or same weakness repeats without meaningful new evidence.

Evaluate through these lenses:
1. claim_integrity_lens: ownership, exaggeration, contradiction, claim substantiation.
2. role_technical_lens: target-role skill evidence.
3. reasoning_communication_lens: clarity, structure, adaptability, first-principles reasoning.
4. human_calibration_lens: honesty, nervousness vs evasion, level calibration, fairness limits.
5. transferable_strength_lens: where the candidate may genuinely be strong even if target-role fit is weak.

Return one complete JSON object with this shape:
{
  "hire_recommendation": "HIRE | MAYBE | NO HIRE | INSUFFICIENT_DATA",
  "overall_score": <0-10>,
  "confidence_score": <0.0-1.0>,
  "breakdown": {
    "reasoning": <0-10 | "inconclusive">,
    "technical_depth": <0-10 | "inconclusive">,
    "communication": <0-10 | "inconclusive">,
    "adaptability": <0-10 | "inconclusive">
  },
  "failure_surface": {"<tested domain>": <0.0-1.0>},
  "role_fit_profile": {
    "target_role_fit": "strong | mixed | weak | inconclusive",
    "best_fit_archetype": "...",
    "strongest_signal": "...",
    "largest_unresolved_risk": "...",
    "alternate_fit_notes": "..."
  },
  "ability_profile": {
    "strongest_verified_signal": "...",
    "weakest_verified_signal": "...",
    "alternate_fit_archetypes": ["..."],
    "target_role_fit": "strong | mixed | weak | inconclusive",
    "role_fit_explanation": "..."
  },
  "resume_claim_calibration": {
    "claims_tested": [],
    "claims_substantiated": [],
    "claims_partially_substantiated": [],
    "claims_not_substantiated": [],
    "claims_untested": [],
    "impact_on_verdict": "scoped | material | inconclusive"
  },
  "lens_findings": {
    "claim_integrity_lens": {"positive_signals": [], "negative_signals": [], "inconclusive_signals": [], "evidence_refs": [], "confidence": "low | medium | high", "summary": "..."},
    "role_technical_lens": {"positive_signals": [], "negative_signals": [], "inconclusive_signals": [], "evidence_refs": [], "confidence": "low | medium | high", "summary": "..."},
    "reasoning_communication_lens": {"positive_signals": [], "negative_signals": [], "inconclusive_signals": [], "evidence_refs": [], "confidence": "low | medium | high", "summary": "..."},
    "human_calibration_lens": {"positive_signals": [], "negative_signals": [], "inconclusive_signals": [], "evidence_refs": [], "confidence": "low | medium | high", "summary": "..."},
    "transferable_strength_lens": {"positive_signals": [], "negative_signals": [], "inconclusive_signals": [], "evidence_refs": [], "confidence": "low | medium | high", "summary": "..."}
  },
  "tested_strengths": ["..."],
  "tested_risks": ["..."],
  "risk_flags": ["..."],
  "strengths": ["..."],
  "claim_findings": [{"claim": "...", "status": "substantiated | partially_substantiated | not_substantiated | untested", "evidence_refs": [], "interpretation": "..."}],
  "claim_credibility_risk": {"level": "low | medium | high | not_tested", "detail": "..."},
  "untested_dimensions": ["..."],
  "recommended_followups": ["..."],
  "candidate_safe_summary": "...",
  "recruiter_summary": "..."
}"""


REPORT_REVIEW_PROMPT = """You are an independent report fairness reviewer.

You receive a FINAL_EVIDENCE_PACKET and a primary report draft. Do not rewrite the report.
Return advisory JSON only. Look for:
- unsupported NO HIRE or score,
- unfair harshness,
- broad rejection language from narrow evidence,
- missed strengths or alternate-fit signals,
- resume-hype over-punishment,
- mismatch between verdict, confidence, and prose.

Return JSON:
{
  "concerns": ["..."],
  "score_alignment": "aligned | too_low | too_high | unsupported",
  "tone_alignment": "fair | too_harsh | too_soft",
  "missed_strengths": ["..."],
  "confidence_band_adjustment": "none | widen | lower_point | raise_point"
}"""


def _build_verdict_explanation(
    coverage_portrait: dict | None,
    hire_recommendation: str,
    disengagement_triggered: bool,
) -> str:
    """One-sentence explanation of how the verdict was reached."""
    if disengagement_triggered:
        return "Verdict based on partial interview — candidate disengaged before full coverage was achieved."
    if coverage_portrait:
        score_pct = round(coverage_portrait.get("coverage_score", 0) * 100)
        n_voluntary = len(coverage_portrait.get("primary_domain", {}).get("voluntary_coverage", []))
        n_missed = len(coverage_portrait.get("primary_domain", {}).get("missed_coverage", []))
        return (
            f"LLM verdict informed by coverage portrait: {score_pct}% of expected dimensions addressed — "
            f"{n_voluntary} demonstrated voluntarily, {n_missed} not addressed when prompted."
        )
    return f"LLM contextual verdict: {hire_recommendation.lower()} based on the full transcript and weakness pattern."


def compute_hire_recommendation(
    overall_score: float,
    coverage_ratio: float,
    weakness_types: list[str],
    discrepancy_level: str = "none",
    disengagement_triggered: bool = False,
) -> str:
    """Deterministic hire recommendation — no LLM randomness."""
    if disengagement_triggered:
        return "INSUFFICIENT_DATA"
    if coverage_ratio < 0.35:
        return "INSUFFICIENT_DATA"
    if discrepancy_level == "confirmed":
        if overall_score >= 6.5:
            return "MAYBE"
        return "CLAIM_RISK_FLAG"
    if overall_score >= 8.0 and coverage_ratio >= 0.75:
        return "STRONG_HIRE"
    if overall_score >= 6.5 and coverage_ratio >= 0.55:
        return "HIRE"
    if overall_score >= 4.5 and coverage_ratio >= 0.35:
        return "MAYBE"
    if coverage_ratio >= 0.45:
        return "NO HIRE"
    return "INSUFFICIENT_DATA"


def _normalize_llm_hire_recommendation(value: object) -> str:
    """Keep the public verdict enum stable while preserving LLM authority."""
    raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    mapping = {
        "STRONG_HIRE": "HIRE",
        "HIRE": "HIRE",
        "MAYBE": "MAYBE",
        "NO_HIRE": "NO HIRE",
        "NOHIRE": "NO HIRE",
        "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
        "INSUFFICIENT": "INSUFFICIENT_DATA",
        "CLAIM_RISK_FLAG": "MAYBE",
    }
    return mapping.get(raw, "INSUFFICIENT_DATA")


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _substantive_answer_count(history: list[dict]) -> int:
    weak_phrases = {
        "i don't know",
        "not sure",
        "i do not know",
        "don't remember",
        "do not remember",
    }
    count = 0
    for turn in history:
        answer = str(turn.get("answer") or "").strip()
        words = answer.split()
        if len(words) >= 12 and not any(answer.lower() == phrase for phrase in weak_phrases):
            count += 1
    return count


def _apply_evaluation_sanity_calibration(
    result: dict,
    *,
    history: list[dict],
    per_answer_scores: list[dict] | None,
    coverage_verdict_ratio: float,
    coverage_portrait: dict | None,
) -> dict:
    """
    Guard against model verdict collapse.

    This does not turn weak candidates into hires. It prevents impossible outputs
    like score=0/NO HIRE after a complete, broad, substantive 15-turn interview.
    """
    calibrated = dict(result or {})
    score = _safe_float(calibrated.get("overall_score"), 0.0)
    recommendation = _normalize_llm_hire_recommendation(calibrated.get("hire_recommendation"))
    substantive = _substantive_answer_count(history)
    avg_answer_score = 0.0
    if per_answer_scores:
        vals = [_safe_float(item.get("score"), 0.0) for item in per_answer_scores if isinstance(item, dict)]
        if vals:
            avg_answer_score = sum(vals) / len(vals)

    broad_enough = (
        len(history) >= 12
        and substantive >= 8
        and coverage_verdict_ratio >= 0.25
        and bool(coverage_portrait)
    )
    if broad_enough and score < 3.0 and avg_answer_score >= 4.0:
        score = 4.0
        calibrated["overall_score"] = score
        if recommendation == "NO HIRE":
            calibrated["hire_recommendation"] = "MAYBE"
            recommendation = "MAYBE"
        flags = calibrated.get("risk_flags")
        if not isinstance(flags, list):
            flags = []
        flags.append(
            "Evaluator sanity calibration: broad interview evidence did not justify a near-zero score; unresolved risks remain scoped."
        )
        calibrated["risk_flags"] = flags

    if broad_enough and recommendation == "NO HIRE" and score >= 4.0:
        calibrated["hire_recommendation"] = "MAYBE"
        flags = calibrated.get("risk_flags")
        if not isinstance(flags, list):
            flags = []
        flags.append(
            "NO HIRE softened to MAYBE because evidence shows mixed/substantive signal rather than broad tested failure."
        )
        calibrated["risk_flags"] = flags

    return calibrated


def compute_confidence(
    coverage_ratio: float,
    questions_asked: int,
    disengagement_level: float = 0.0,
    discrepancy_level: str = "none",
) -> float:
    """Deterministic confidence score. 0.0–1.0."""
    base = min(1.0, coverage_ratio)
    if questions_asked < 5:
        base *= 0.6
    elif questions_asked < 8:
        base *= 0.8
    if disengagement_level >= 3.0:
        base *= 0.7
    elif disengagement_level >= 2.0:
        base *= 0.85
    if discrepancy_level == "confirmed":
        base = min(1.0, base + 0.1)
    return round(max(0.1, min(1.0, base)), 2)


def _build_calibration_context(
    target_role: str = "",
    years_experience: str = "",
    parsed_resume: dict | None = None,
) -> str:
    parsed_resume = parsed_resume or {}
    parts: list[str] = []

    if target_role:
        parts.append(f"Target role: {target_role}")
    if years_experience:
        parts.append(f"Expected years of experience: {years_experience}")

    experience_tier = parsed_resume.get("experience_tier")
    if experience_tier:
        parts.append(f"Resume-inferred experience tier: {experience_tier}")

    claims = parsed_resume.get("claims", [])
    if claims:
        formatted_claims = []
        for claim in claims[:5]:
            if isinstance(claim, dict):
                text = claim.get("text", "").strip()
                strength = claim.get("strength", "moderate")
                contribution = claim.get("contribution_type", "unspecified")
                if text:
                    formatted_claims.append(f"{text} [{strength}, {contribution}]")
            elif isinstance(claim, str) and claim.strip():
                formatted_claims.append(claim.strip())
        if formatted_claims:
            parts.append("Resume claims: " + "; ".join(formatted_claims))

    projects = parsed_resume.get("projects", [])
    if projects:
        summaries = []
        for project in projects[:3]:
            if not isinstance(project, dict):
                continue
            name = project.get("name", "Unnamed project")
            ownership = project.get("ownership_level", "unspecified")
            contribution = project.get("contribution_type", "unspecified")
            summaries.append(f"{name} [{ownership}, {contribution}]")
        if summaries:
            parts.append("Project ownership: " + "; ".join(summaries))

    prior_assessment_prompt = str(parsed_resume.get("prior_assessment_prompt", "") or "").strip()
    if prior_assessment_prompt:
        parts.append("Prior assessment context:\n" + prior_assessment_prompt[:1200])

    return "\n".join(parts) if parts else "No explicit calibration context provided."


class EvaluationAgent:
    """
    Two modes:

    score_answer() — per-answer scoring during the interview (3-pass averaged)
    score_full_interview() — called once at session end, evaluates entire transcript
    """

    def __init__(self):
        self.llm = LLMRouter(tier="large")  # strongest reasoning tier — accuracy matters here
        self.review_llm = LLMRouter(
            tier="small",
            model_override=os.getenv("OPENROUTER_REPORT_REVIEW_MODEL", "google/gemini-3.1-flash-lite"),
            timeout_override=float(os.getenv("REPORT_REVIEW_TIMEOUT_SECONDS", "25")),
        )

    async def score_answer(
        self,
        question: str,
        answer: str,
        target_role: str = "",
        years_experience: str = "",
    ) -> dict:
        """
        Multi-pass scoring for a single answer. 3 evaluations averaged
        to reduce LLM inconsistency.
        """
        scores = await asyncio.gather(
            self._score_once(question, answer, target_role=target_role, years_experience=years_experience),
            self._score_once(question, answer, target_role=target_role, years_experience=years_experience),
            self._score_once(question, answer, target_role=target_role, years_experience=years_experience),
        )
        valid = [s for s in scores if isinstance(s, dict) and "score" in s]
        if not valid:
            return {"score": 0, "breakdown": {}, "confidence": 0}

        avg_score = sum(s["score"] for s in valid) / len(valid)
        return {
            "score": round(avg_score, 2),
            "breakdown": valid[0].get("breakdown", {}),
            "confidence": sum(s.get("confidence", 0.5) for s in valid) / len(valid),
        }

    async def score_full_interview(
        self,
        history: list[dict],
        resume: str,
        weaknesses: list[dict],
        reasoning_signals: list[dict] | None = None,
        per_answer_scores: list[dict] | None = None,
        coverage_ratio: float | None = None,
        target_role: str = "",
        years_experience: str = "",
        parsed_resume: dict | None = None,
        coverage_map: dict | None = None,
        assessment_coverage: dict | None = None,
        discrepancy_level: str = "none",
        disengagement_level: float = 0.0,
        disengagement_triggered: bool = False,
    ) -> dict:
        """
        Final evaluation of the complete interview.
        Called once at session end. Uses the large reasoning tier for maximum accuracy.
        Incorporates reasoning behavior signals and per-answer scores for richer context.
        """
        coverage_portrait = None
        verdict_basis = "weakness_aggregation"
        coverage_verdict_ratio = coverage_ratio if coverage_ratio is not None else 0.5
        if coverage_map and isinstance(coverage_map, dict):
            try:
                from backend.models.coverage_map import AnswerCoverageMap
                cmap = AnswerCoverageMap.from_dict(coverage_map)
                cmap.compute_coverage_score()
                voluntary = [d.label for d in cmap.dimensions if d.coverage_state == "voluntary"]
                recovered = [d.label for d in cmap.dimensions if d.coverage_state in ("recovered_deep", "recovered_surface")]
                missed = [d.label for d in cmap.dimensions if d.coverage_state in ("missed", "not_evaluated")]
                incorrect = [d.label for d in cmap.dimensions if d.coverage_state == "incorrect"]
                coverage_portrait = {
                    "coverage_score": cmap.coverage_score,
                    "coverage_confidence": cmap.coverage_confidence,
                    "primary_domain": {
                        "voluntary_coverage": voluntary,
                        "recovered_coverage": recovered,
                        "missed_coverage": missed,
                        "incorrect_coverage": incorrect,
                        "domain_score": cmap.coverage_score,
                    },
                }
                coverage_verdict_ratio = cmap.coverage_score
                verdict_basis = "llm_contextual_with_coverage"
            except Exception:
                coverage_portrait = None
                verdict_basis = "weakness_aggregation"

        evidence_packet = build_final_evidence_packet(
            history=history,
            resume=resume,
            weaknesses=weaknesses,
            reasoning_signals=reasoning_signals,
            per_answer_scores=per_answer_scores,
            coverage_map=coverage_map,
            assessment_coverage=assessment_coverage,
            target_role=target_role,
            years_experience=years_experience,
            parsed_resume=parsed_resume,
            discrepancy_level=discrepancy_level,
            disengagement_level=disengagement_level,
            disengagement_triggered=disengagement_triggered,
        )

        user = "FINAL_EVIDENCE_PACKET:\n" + json.dumps(evidence_packet, ensure_ascii=True, indent=2)

        result = await self.llm.call(
            system=FULL_INTERVIEW_PROMPT,
            user=user,
            max_tokens=int(os.getenv("REPORT_MAX_TOKENS", "5000")),
            response_format=JSON_OBJECT_FORMAT,
            audit_call_name="EvaluationAgent.score_full_interview.report_v2",
            audit_metadata={
                "turns": len(history),
                "coverage_gate_passed": bool((evidence_packet.get("coverage_gate") or {}).get("passed")),
                "schema_version": "final_report_v2",
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError("EvaluationAgent returned non-JSON output.")

        # Coverage produces an advisory verdict only. The final recommendation and
        # confidence remain LLM-contextual because the evaluator sees the full transcript.
        llm_score = _safe_float(result.get("overall_score"), 0.0)
        _weakness_types = [w.get("type", "") for w in weaknesses if w.get("type")]
        coverage_advisory_recommendation = compute_hire_recommendation(
            overall_score=llm_score,
            coverage_ratio=coverage_verdict_ratio,
            weakness_types=_weakness_types,
            discrepancy_level=discrepancy_level,
            disengagement_triggered=disengagement_triggered,
        )
        coverage_advisory_confidence = compute_confidence(
            coverage_ratio=coverage_verdict_ratio,
            questions_asked=len(history),
            disengagement_level=disengagement_level,
            discrepancy_level=discrepancy_level,
        )
        result = _apply_evaluation_sanity_calibration(
            result,
            history=history,
            per_answer_scores=per_answer_scores,
            coverage_verdict_ratio=coverage_verdict_ratio,
            coverage_portrait=coverage_portrait,
        )
        normalized_recommendation = _normalize_llm_hire_recommendation(result.get("hire_recommendation"))
        if str(result.get("hire_recommendation", "")).strip().upper().replace(" ", "_") == "CLAIM_RISK_FLAG":
            flags = result.get("risk_flags")
            if not isinstance(flags, list):
                flags = []
            if "Claim risk flagged by evaluator" not in flags:
                flags.append("Claim risk flagged by evaluator")
            result["risk_flags"] = flags
        result["hire_recommendation"] = normalized_recommendation
        try:
            result["confidence_score"] = round(max(0.0, min(1.0, float(result.get("confidence_score", 0)))), 2)
        except (TypeError, ValueError):
            result["confidence_score"] = coverage_advisory_confidence

        result["coverage_portrait"] = coverage_portrait
        result["verdict_basis"] = verdict_basis
        result["coverage_verdict_advisory"] = {
            "hire_recommendation": coverage_advisory_recommendation,
            "confidence_score": coverage_advisory_confidence,
        }
        result["verdict_confidence_basis"] = _build_verdict_explanation(
            coverage_portrait, normalized_recommendation, disengagement_triggered
        )
        advisory_review = await self._advisory_review(evidence_packet, result)
        return normalize_final_report_v2(result, evidence_packet, advisory_review)

    async def _advisory_review(self, evidence_packet: dict[str, Any], primary_report: dict[str, Any]) -> dict[str, Any]:
        if str(os.getenv("ENABLE_REPORT_ADVISORY_REVIEW", "1")).lower() in {"0", "false", "no"}:
            return {"concerns": [], "model": "disabled"}
        try:
            payload = {
                "final_evidence_packet": evidence_packet,
                "primary_report": {
                    key: value
                    for key, value in primary_report.items()
                    if key not in {"final_evidence_packet"}
                },
            }
            review = await self.review_llm.call(
                system=REPORT_REVIEW_PROMPT,
                user=json.dumps(payload, ensure_ascii=True, indent=2),
                max_tokens=int(os.getenv("REPORT_REVIEW_MAX_TOKENS", "1200")),
                response_format=JSON_OBJECT_FORMAT,
                audit_call_name="EvaluationAgent.score_full_interview.advisory_review",
                audit_metadata={
                    "schema_version": "report_advisory_review_v1",
                    "coverage_gate_passed": bool((evidence_packet.get("coverage_gate") or {}).get("passed")),
                },
            )
            if isinstance(review, dict):
                review["model"] = self.review_llm.model
                return review
        except Exception:
            pass
        return {"concerns": [], "model": self.review_llm.model, "error": "review_unavailable"}

    async def _score_once(
        self,
        question: str,
        answer: str,
        target_role: str = "",
        years_experience: str = "",
    ) -> dict:
        calibration_context = _build_calibration_context(
            target_role=target_role,
            years_experience=years_experience,
        )
        _is_analyst = bool(target_role) and any(
            kw in target_role.lower()
            for kw in ("analyst", "pm ", "product manager", "data analyst", "business analyst")
        )
        system = _ANALYST_PER_ANSWER_PROMPT if _is_analyst else PER_ANSWER_PROMPT
        return await self.llm.call(
            system=system,
            user=(
                f"CALIBRATION CONTEXT:\n{calibration_context}\n\n"
                f"Question: {question}\n\nAnswer: {answer}"
            ),
            response_format=JSON_OBJECT_FORMAT,
        )
