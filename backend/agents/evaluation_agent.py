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


FULL_INTERVIEW_PROMPT = """You are evaluating the complete transcript of a 30-minute technical interview.

You will receive the full Q&A history across 3 sprints and a list of detected weaknesses.

Produce a comprehensive evaluation with:

1. Overall score (0-10)
2. Per-dimension scores:
   - reasoning (0-10): logical thinking, structured problem-solving
   - technical_depth (0-10): correctness, specificity, production awareness
   - communication (0-10): clarity, conciseness, structured answers
   - adaptability (0-10): how they handled being challenged or wrong

3. Failure surface: for each technical domain mentioned, estimate their knowledge failure point (0.0=strong, 1.0=completely failed)

4. Hire recommendation: HIRE | MAYBE | NO HIRE

5. Summary: 2-3 sentence honest assessment

6. Risk flags: list of specific concerns

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
    ) -> dict:
        """
        Final evaluation of the complete interview.
        Called once at session end. Uses Opus for maximum accuracy.
        """
        # Format history into readable transcript
        transcript_lines = []
        for i, turn in enumerate(history):
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

        user = f"""RESUME:
{resume[:1000]}

INTERVIEW TRANSCRIPT ({len(history)} turns):
{transcript}

DETECTED WEAKNESSES:
{weakness_summary}

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
            "summary": "Evaluation failed.",
            "risk_flags": [],
            "strengths": [],
        }

    async def _score_once(self, question: str, answer: str) -> dict:
        return await self.llm.call(
            system=PER_ANSWER_PROMPT,
            user=f"Question: {question}\n\nAnswer: {answer}",
        )
