from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter
import re


PROMPT = """You are a resume parser. Extract structured data from the resume below.

IMPORTANT rules:
- Bullet points that wrap across lines belong to the same claim — join them.
- Do NOT classify contact info (email, phone, LinkedIn, GitHub, address) as a project or experience.
- Do NOT classify education entries (B.Tech, M.S., GPA lines) as projects.
- Skills and tools should contain individual technology names, not full sentences.
- Claims should be complete sentences (join line-wrapped bullet points into one claim).
- experience_tier: derive from explicit years of experience stated or implied by total career length.
  - 0–1 year → "junior"; 1–3 years → "mid"; 3+ years → "senior"

Extract:
- candidate_name (str): the person's full name from the top of the resume, or empty string if not found
- skills (list[str])
- tools (list[str])
- projects (list[object]) with name, description, technologies, ownership_level, contribution_type
- experiences (list[object]) with title, company, duration, contribution_type
- claims (list[object]) with text (complete sentence), project, strength, contribution_type
- experience_tier: "junior | mid | senior"

Return ONLY valid JSON (no markdown fences):
{
  "candidate_name": "...",
  "skills": [...],
  "projects": [{"name": "...", "description": "...", "technologies": ["..."], "ownership_level": "primary", "contribution_type": "built"}],
  "claims": [{"text": "...", "project": "...", "strength": "strong", "contribution_type": "built"}],
  "tools": [...],
  "experiences": [{"title": "...", "company": "...", "duration": "...", "contribution_type": "built"}],
  "experience": {"ml": 0, "swe": 0, "data_eng": 0},
  "experience_tier": "junior"
}"""


class ResumeAgent:
    """
    Parses resume at session start.
    Extracted data feeds into discrepancy detection and question personalization.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="small")

    def _join_continuation_lines(self, text: str) -> str:
        """Join bullet-point lines that wrap across lines due to PDF/text extraction."""
        lines = text.splitlines()
        result: list[str] = []
        bullet_chars = ("•", "-", "*", "◦", "–", "▪")
        header_keywords = re.compile(
            r"^(experience|education|skills|projects|summary|objective|certifications|"
            r"awards|publications|work history|technical|contact|languages)\b",
            re.IGNORECASE,
        )
        date_pattern = re.compile(r"^\d{4}|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE)
        for line in lines:
            stripped = line.strip()
            if not stripped:
                result.append(stripped)
                continue
            is_bullet = stripped[0] in bullet_chars
            is_header = bool(header_keywords.match(stripped))
            is_date = bool(date_pattern.match(stripped))
            is_new_section = is_bullet or is_header or is_date or (len(stripped) > 2 and stripped[0].isupper() and stripped.endswith(":"))
            if result and not is_new_section and result[-1] and not result[-1].endswith("."):
                result[-1] = result[-1].rstrip() + " " + stripped
            else:
                result.append(stripped)
        return "\n".join(result)

    def _derive_experience_tier(self, years_experience: str) -> str:
        """Derive experience tier from years_experience string (e.g. '0-1', '1-3', '3+')."""
        if not years_experience:
            return "junior"
        yl = years_experience.lower().strip()
        if any(kw in yl for kw in ("senior", "staff", "lead", "principal", "architect")):
            return "senior"
        # Extract first number
        nums = re.findall(r"\d+", yl)
        if nums:
            low = int(nums[0])
            if low >= 3:
                return "senior"
            if low >= 1:
                return "mid"
        return "junior"

    async def parse(
        self,
        resume_text: str,
        target_role: str = "",
        years_experience: str = "",
    ) -> dict:
        preprocessed = self._join_continuation_lines(resume_text)
        result = await self.llm.call(
            system=PROMPT,
            user=(
                f"Target role: {target_role or 'not provided'}\n"
                f"Expected years of experience: {years_experience or 'not provided'}\n\n"
                f"Resume:\n{preprocessed}"
            ),
            max_tokens=5000,
            response_format=JSON_OBJECT_FORMAT,
        )
        if not isinstance(result, dict):
            raise RuntimeError("ResumeAgent returned non-JSON output; refusing heuristic fallback.")
        for key in ("skills", "tools", "projects", "claims", "experiences"):
            if key not in result:
                raise RuntimeError(f"ResumeAgent output missing required key: {key}")
        for key in ("skills", "tools"):
            if not isinstance(result.get(key), list):
                raise RuntimeError(f"ResumeAgent output key '{key}' must be a list.")
        for key in ("projects", "claims", "experiences"):
            value = result.get(key)
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise RuntimeError(f"ResumeAgent output key '{key}' must be a list of objects.")
        # Ensure experience_tier uses years_experience as primary signal
        derived_tier = self._derive_experience_tier(years_experience)
        if derived_tier and years_experience:
            result["experience_tier"] = derived_tier
        return result
