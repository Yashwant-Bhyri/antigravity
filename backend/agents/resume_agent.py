from backend.models.llm_router import LLMRouter


PROMPT = """You are a resume parser.

Extract from the resume:
- skills (list)
- projects (list with name, description, technologies)
- claims (what they say they built or did)
- tools used (list)
- years of experience per domain

Return JSON:
{
  "skills": [...],
  "projects": [...],
  "claims": [...],
  "tools": [...],
  "experience": {"ml": X, "swe": X, "data_eng": X}
}
"""


class ResumeAgent:
    """
    Parses resume at session start.
    Extracted data feeds into discrepancy detection and question personalization.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="small")

    async def parse(self, resume_text: str) -> dict:
        return await self.llm.call(
            system=PROMPT,
            user=f"Resume:\n{resume_text}",
        )
