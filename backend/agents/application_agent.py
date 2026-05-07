from __future__ import annotations

from backend.models.llm_router import LLMRouter
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension


APPLICATION_SYSTEM = """You are designing an application transfer question for a technical interview.

Given what a candidate just described building, you must:
1. Create ONE application transfer question — a new scenario in the same domain with ONE new constraint.
2. Generate 4-6 dimensions that a strong answer should address.

Rules for the application question:
- MUST reference the implementation_anchor specifically (name what they said they built)
- Adjacent constraint — same domain, ONE meaningful shift (batch→real-time, single-user→multi-tenant, controlled→adversarial)
- Situational framing: "Imagine your PM comes to you tomorrow and says..."
- Multiple valid implementation approaches must exist
- Calibrate to experience: junior→surface design; senior→failure modes and boundary conditions

Rules for dimensions:
- 4-6 dimensions maximum
- Each dimension: a distinct aspect of a strong answer to the application question
- expected_approaches: 2-3 valid implementations for this dimension (candidate doesn't need to name these, just address the concept)
- surfacing_question: a single exploratory prompt that names the SITUATION, not the SOLUTION
  - Wrong: "Did you consider caching?" (names the solution)
  - Right: "What happens when the pipeline falls behind real-time?" (names the problem space)
- weight: 1.0-3.0 based on importance to role fitness

Return JSON only:
{
  "application_question": "string",
  "adjacent_constraint": "string (what changed)",
  "anchor_reference": "string (the specific thing from their answer the question references)",
  "coverage_confidence": 0.0-1.0,
  "dimensions": [
    {
      "id": "snake_case_id",
      "label": "short label",
      "description": "what this dimension tests",
      "expected_approaches": ["approach_a", "approach_b"],
      "surfacing_question": "the single exploratory prompt for this dimension",
      "weight": 1.5
    }
  ]
}"""


class ApplicationAgent:
    def __init__(self) -> None:
        self.llm = LLMRouter(tier="medium")

    async def generate(
        self,
        implementation_anchor: str,
        candidate_domain: str,
        target_role: str,
        years_experience: str,
        resume_snippets: list[str],
    ) -> AnswerCoverageMap | None:
        """
        Generate an application transfer question and AnswerCoverageMap.
        Returns None on LLM failure — caller must handle gracefully.
        """
        resume_context = "\n".join(f"- {s}" for s in (resume_snippets or [])[:5])
        user = (
            f"Target role: {target_role or 'not specified'}\n"
            f"Experience level: {years_experience or 'mid'}\n"
            f"Candidate domain: {candidate_domain or 'not specified'}\n\n"
            f"Resume context:\n{resume_context or '(none)'}\n\n"
            f"Implementation anchor (what they said they built):\n{implementation_anchor}\n\n"
            "Generate the application transfer question and coverage map."
        )
        try:
            result = await self.llm.call(system=APPLICATION_SYSTEM, user=user, max_tokens=1500)
            if not isinstance(result, dict):
                return None

            app_question = str(result.get("application_question", "")).strip()
            if not app_question:
                return None

            raw_dims = result.get("dimensions") or []
            dims: list[CoverageDimension] = []
            for d in raw_dims:
                if not isinstance(d, dict):
                    continue
                dim_id = str(d.get("id", "")).strip()
                label = str(d.get("label", "")).strip()
                if not dim_id:
                    continue
                try:
                    weight = float(d.get("weight", 1.5))
                except (TypeError, ValueError):
                    weight = 1.5
                dims.append(CoverageDimension(
                    id=dim_id,
                    label=label or dim_id,
                    description=str(d.get("description", "")),
                    expected_approaches=list(d.get("expected_approaches") or []),
                    surfacing_question=str(d.get("surfacing_question", "")),
                    weight=weight,
                ))

            if not dims:
                return None

            return AnswerCoverageMap(
                application_question=app_question,
                implementation_anchor=implementation_anchor,
                dimensions=dims,
                total_weight=sum(d.weight for d in dims),
                coverage_confidence=float(result.get("coverage_confidence") or 0.5),
            )
        except Exception as e:
            print(f"[ApplicationAgent] Generation failed: {e}")
            return None
