import asyncio
from backend.models.llm_router import LLMRouter


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


FULL_INTERVIEW_PROMPT = """You are evaluating the complete transcript of a technical interview.

You will receive the full Q&A history, detected weaknesses, and a COVERAGE NOTE describing how broad the interview actually was, plus calibration context about the target role and expected experience level.

**Critical instruction:** Read the COVERAGE NOTE carefully. If the interview clustered heavily on one topic, your confidence score must reflect that narrow evidence base — do NOT assign high confidence when few dimensions were actually tested. Separate your claim-level concerns from your overall engineering judgment.
Score the candidate against the stated role/level, not against an implicit universal senior bar.

Produce a comprehensive evaluation with:

1. Overall score (0-10) — based only on what was actually tested
2. Per-dimension scores:
   - reasoning (0-10 | inconclusive): logical thinking, structured problem-solving
   - technical_depth (0-10 | inconclusive): correctness, specificity, production awareness
   - communication (0-10 | inconclusive): clarity, conciseness, structured answers
   - adaptability (0-10 | inconclusive): how they handled being challenged or wrong

3. Failure surface: for each technical domain mentioned, estimate knowledge failure point (0.0=strong, 1.0=completely failed)

4. Hire recommendation: HIRE | MAYBE | NO HIRE | INSUFFICIENT_DATA

5. Summary: 2-3 sentence honest assessment. If coverage was narrow, say so explicitly.

6. Claim credibility risk: separately assess only the specific resume claims that were tested.
   This is SEPARATE from the overall score — a candidate can have one inflated claim but still be
   a strong engineer overall. Do not let one bad claim drag down dimensions you didn't test.

7. Risk flags: scoped — distinguish "specific claim not substantiated" from "broad engineering weakness"

8. Strengths: what they demonstrably CAN do

Return JSON:
{
  "overall_score": <0-10>,
  "breakdown": {
    "reasoning": <0-10 | "inconclusive">,
    "technical_depth": <0-10 | "inconclusive">,
    "communication": <0-10 | "inconclusive">,
    "adaptability": <0-10 | "inconclusive">
  },
  "failure_surface": {
    "<domain>": <0.0-1.0>
  },
  "hire_recommendation": "HIRE | MAYBE | NO HIRE | INSUFFICIENT_DATA",
  "confidence_score": <0.0-1.0>,
  "summary": "...",
  "risk_flags": ["...", "..."],
  "strengths": ["...", "..."],
  "claim_credibility_risk": {
    "level": "low | medium | high | not_tested",
    "detail": "<one sentence: which claims held up, which didn't>"
  },
  "untested_dimensions": ["..."]
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
        discrepancy_level: str = "none",
        disengagement_level: float = 0.0,
        disengagement_triggered: bool = False,
    ) -> dict:
        """
        Final evaluation of the complete interview.
        Called once at session end. Uses the large reasoning tier for maximum accuracy.
        Incorporates reasoning behavior signals and per-answer scores for richer context.
        """
        transcript_lines = []
        for turn in history:
            sprint = turn.get("sprint", "?")
            persona = turn.get("persona", "?")
            transcript_lines.append(
                f"[Sprint {sprint} | {persona}]\n"
                f"Q: {turn.get('question', '')}\n"
                f"A: {turn.get('answer', '')}"
            )
        transcript = "\n\n".join(transcript_lines)

        weakness_summary = "\n".join(
            f"- {w.get('type','?')} ({w.get('severity','?')}): {w.get('weakness','')}"
            for w in weaknesses
        ) or "None detected."

        # Reasoning behavior aggregation
        reasoning_summary = ""
        if reasoning_signals:
            structures = [r.get("structure_score", 0) for r in reasoning_signals if r]
            avg_structure = sum(structures) / len(structures) if structures else 0
            adaptability_counts: dict[str, int] = {}
            for r in reasoning_signals:
                if r:
                    a = r.get("adaptability", "")
                    adaptability_counts[a] = adaptability_counts.get(a, 0) + 1
            dominant_adapt = max(adaptability_counts, key=adaptability_counts.get) if adaptability_counts else "unknown"
            reasoning_summary = (
                f"\nREASONING BEHAVIOR ({len(reasoning_signals)} turns):\n"
                f"- Avg structure score: {avg_structure:.1f}/3\n"
                f"- Dominant adaptability: {dominant_adapt}\n"
                f"- Clarification behavior: {reasoning_signals[0].get('clarification_behavior', 'unknown') if reasoning_signals else 'unknown'}"
            )

        # Per-answer score summary
        score_summary = ""
        if per_answer_scores:
            avg = sum(s.get("score", 0) for s in per_answer_scores) / len(per_answer_scores)
            score_summary = f"\nPER-ANSWER SCORES ({len(per_answer_scores)} scored): avg {avg:.1f}/10"

        # Coverage note — warns the LLM when evidence is narrow
        coverage_note = ""
        if weaknesses and len(history) > 3:
            unique_types = len({w.get("type") for w in weaknesses if w.get("type")})
            total = len(weaknesses)
            computed_ratio = unique_types / max(total, 1)
            ratio = coverage_ratio if coverage_ratio is not None else computed_ratio
            if ratio < 0.3:
                dominant = max(
                    {w.get("type", ""): weaknesses.count(w) for w in weaknesses},
                    key=lambda t: sum(1 for w in weaknesses if w.get("type") == t),
                    default="unknown",
                )
                coverage_note = (
                    f"\n\nCOVERAGE NOTE: {round(ratio * 100)}% of weakness types were unique across {total} detections. "
                    f"The interview clustered heavily on '{dominant}' failures. "
                    f"Dimensions NOT fully tested should not be rated low — mark them as inconclusive. "
                    f"Confidence score must reflect this narrow evidence base (suggest ≤ 0.6)."
                )

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
                coverage_note += (
                    f"\n\nCOVERAGE PORTRAIT NOTE: {round(cmap.coverage_score * 100)}% "
                    "of expected application-transfer dimensions were covered. "
                    f"Voluntary: {len(voluntary)}; recovered: {len(recovered)}; "
                    f"missed: {len(missed)}; incorrect: {len(incorrect)}. "
                    "Use this as important evidence, but make the final verdict from the full transcript context."
                )
            except Exception:
                coverage_portrait = None
                verdict_basis = "weakness_aggregation"

        calibration_context = _build_calibration_context(
            target_role=target_role,
            years_experience=years_experience,
            parsed_resume=parsed_resume,
        )

        user = f"""RESUME:
{resume[:1500]}

CALIBRATION CONTEXT:
{calibration_context}

INTERVIEW TRANSCRIPT ({len(history)} turns):
{transcript}

DETECTED WEAKNESSES:
{weakness_summary}{reasoning_summary}{score_summary}{coverage_note}

Evaluate the full interview."""

        result = await self.llm.call(system=FULL_INTERVIEW_PROMPT, user=user)
        if not isinstance(result, dict):
            return {
                "overall_score": 0,
                "breakdown": {},
                "failure_surface": {},
                "hire_recommendation": "INSUFFICIENT_DATA",
                "confidence_score": 0,
                "summary": "Evaluation failed — LLM did not return valid JSON.",
                "risk_flags": ["Evaluation pipeline error"],
                "strengths": [],
                "claim_credibility_risk": {"level": "not_tested", "detail": "Evaluation pipeline error."},
                "untested_dimensions": [],
                "verdict_basis": "error",
            }

        # Coverage produces an advisory verdict only. The final recommendation and
        # confidence remain LLM-contextual because the evaluator sees the full transcript.
        llm_score = float(result.get("overall_score") or 0)
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
        return result

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
        )
