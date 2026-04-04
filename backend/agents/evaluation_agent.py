import asyncio
from backend.models.llm_router import LLMRouter


PER_ANSWER_PROMPT = """Evaluate this single interview answer.

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


FULL_INTERVIEW_PROMPT = """You are evaluating the complete transcript of a technical interview.

You will receive the full Q&A history, detected weaknesses, and a COVERAGE NOTE describing how broad the interview actually was.

**Critical instruction:** Read the COVERAGE NOTE carefully. If the interview clustered heavily on one topic, your confidence score must reflect that narrow evidence base — do NOT assign high confidence when few dimensions were actually tested. Separate your claim-level concerns from your overall engineering judgment.

Produce a comprehensive evaluation with:

1. Overall score (0-10) — based only on what was actually tested
2. Per-dimension scores:
   - reasoning (0-10): logical thinking, structured problem-solving
   - technical_depth (0-10): correctness, specificity, production awareness
   - communication (0-10): clarity, conciseness, structured answers
   - adaptability (0-10): how they handled being challenged or wrong

3. Failure surface: for each technical domain mentioned, estimate knowledge failure point (0.0=strong, 1.0=completely failed)

4. Hire recommendation: HIRE | MAYBE | NO HIRE

5. Summary: 2-3 sentence honest assessment. If coverage was narrow, say so explicitly.

6. Risk flags: be scoped — distinguish "specific claim not substantiated" from "broad engineering weakness"

7. Strengths: what they demonstrably CAN do

Return JSON:
{
  "overall_score": <0-10>,
  "breakdown": {
    "reasoning": <0-10>,
    "technical_depth": <0-10>,
    "communication": <0-10>,
    "adaptability": <0-10>
  },
  "failure_surface": {
    "<domain>": <0.0-1.0>
  },
  "hire_recommendation": "HIRE | MAYBE | NO HIRE",
  "confidence_score": <0.0-1.0>,
  "summary": "...",
  "risk_flags": ["...", "..."],
  "strengths": ["...", "..."]
}"""


class EvaluationAgent:
    """
    Two modes:

    score_answer() — per-answer scoring during the interview (3-pass averaged)
    score_full_interview() — called once at session end, evaluates entire transcript
    """

    def __init__(self):
        self.llm = LLMRouter(tier="large")  # Opus — accuracy matters here

    async def score_answer(self, question: str, answer: str) -> dict:
        """
        Multi-pass scoring for a single answer. 3 evaluations averaged
        to reduce LLM inconsistency.
        """
        scores = await asyncio.gather(
            self._score_once(question, answer),
            self._score_once(question, answer),
            self._score_once(question, answer),
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
    ) -> dict:
        """
        Final evaluation of the complete interview.
        Called once at session end. Uses Opus for maximum accuracy.
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

        user = f"""RESUME:
{resume[:1500]}

INTERVIEW TRANSCRIPT ({len(history)} turns):
{transcript}

DETECTED WEAKNESSES:
{weakness_summary}{reasoning_summary}{score_summary}{coverage_note}

Evaluate the full interview."""

        result = await self.llm.call(system=FULL_INTERVIEW_PROMPT, user=user)
        if isinstance(result, dict):
            return result
        return {
            "overall_score": 0,
            "breakdown": {},
            "failure_surface": {},
            "hire_recommendation": "N/A",
            "confidence_score": 0,
            "summary": "Evaluation failed — LLM did not return valid JSON.",
            "risk_flags": ["Evaluation pipeline error"],
            "strengths": [],
        }

    async def _score_once(self, question: str, answer: str) -> dict:
        return await self.llm.call(
            system=PER_ANSWER_PROMPT,
            user=f"Question: {question}\n\nAnswer: {answer}",
        )
