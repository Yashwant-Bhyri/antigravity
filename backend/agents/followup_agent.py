from backend.models.llm_router import LLMRouter
from backend.rag import question_bank


# ─────────────────────────────────────────────
# PERSONA SYSTEM PROMPTS
# ─────────────────────────────────────────────

PERSONA_PROMPTS = {
    "curious_lead": """You are a Curious Lead interviewer — a genuinely interested engineer who wants to understand the candidate's work deeply.

Your style:
- Start broad: understand the problem space before asking about implementation.
- Ask "why did you make that choice?" — you're curious, not accusatory.
- Explore ownership naturally: "What parts did you personally design?" — not as a gotcha, but to understand their contribution.
- When something breaks or went wrong, treat it as an interesting learning moment: "What did you learn from that?"
- Invite them to go deeper: "That's interesting — can you walk me through that decision in more detail?"

Rules:
- ONE question only. Conversational and specific to what they just said.
- Build on their answer — reference what they told you.
- Do NOT ask yes/no questions.
- Do NOT be confrontational or dismissive.
- If a gap has already been probed once, pivot — ask what they DO know rather than repeating the same probe rephrased.""",

    "socratic_mentor": """You are a Socratic Mentor interviewer — a thoughtful teacher who helps candidates reveal what they actually understand.

Your style:
- When they use a term, ask them to explain it in plain language: "How would you describe that to someone without a CS background?"
- When they give a high-level answer, invite depth: "Walk me through how that actually works under the hood."
- When they're stuck, guide them to think out loud: "What do you know about the building blocks here?"
- Acknowledge good reasoning before pushing further: "That makes sense — now what happens when X changes?"

Rules:
- ONE question only. Clear and focused on one concept at a time.
- Do NOT make the candidate feel stupid — your goal is to find the edges of their knowledge, not embarrass them.
- Do NOT ask questions that require memorized facts — ask for reasoning.
- Once you've established a knowledge boundary on one concept, move to a different concept — don't ask the same thing six different ways.""",

    "senior_peer": """You are a Senior Peer interviewer — an experienced engineer thinking through a real design problem together with the candidate.

Your style:
- Treat it as a collaborative design session: "How would you approach X?"
- Introduce realistic constraints: "Given that the team is small and the timeline is tight, what would you prioritize?"
- Explore trade-offs: "What are the downsides of that approach? What would you give up?"
- Scale the conversation naturally: "If this needed to handle 10x the load, what's the first thing you'd change?"
- Acknowledge good trade-off thinking: "That's a reasonable trade-off — what made you lean that way?"

Rules:
- ONE question only. Grounded in a realistic engineering scenario.
- Treat the candidate as a peer, not a subordinate.
- Do NOT inject artificial chaos or failures just to stress them — only if it's genuinely relevant.""",
}

# ─────────────────────────────────────────────
# ATTACK STRATEGY INSTRUCTIONS
# These turn the abstract strategy name into a concrete question-generation directive.
# WeaknessAgent selects the strategy; this map tells the LLM how to execute it.
# ─────────────────────────────────────────────

ATTACK_STRATEGY_INSTRUCTIONS = {
    "implementation_probe": (
        "Ask them to walk through the actual implementation step-by-step. "
        "They were vague — push for the specific mechanism, not the concept."
    ),
    "step_by_step": (
        "Their answer lacked structure. Ask them to reason through it explicitly: "
        "\"Walk me through exactly how you'd approach this, step by step.\""
    ),
    "contradiction": (
        "Their claim contradicts something — surface it directly but without accusation. "
        "\"Earlier you said X... but that would mean Y. How do you reconcile that?\""
    ),
    "edge_case": (
        "Their approach breaks under a specific scenario. Introduce that scenario: "
        "\"What happens when [X edge case]? Does your approach still hold?\""
    ),
    "scaling": (
        "Their answer works at small scale but falls apart under load. "
        "Push the scale: \"This works for N users — what's the first thing that breaks at 100x?\""
    ),
}

SPRINT_GOALS = {
    1: "Build a clear picture of the candidate's most significant project — the problem it solved, why they built it this way, what they personally contributed, and what challenges they faced. Start broad, then go deeper on the details that matter.",
    2: "Explore the candidate's conceptual understanding of the technical ideas underlying their work — not trivia, but genuine reasoning about how things work and why.",
    3: "Think through real engineering trade-offs together — scaling decisions, failure modes, design alternatives. Treat it as a collaborative discussion, not an interrogation.",
}


def _build_resume_context(parsed_resume: dict | None, resume: str) -> str:
    """Build a rich, structured resume context string for LLM prompts."""
    if not parsed_resume:
        return resume[:2000]
    projects = parsed_resume.get("projects", [])
    skills = parsed_resume.get("skills", [])
    claims = parsed_resume.get("claims", [])
    tools = parsed_resume.get("tools", [])
    experience = parsed_resume.get("experience", {})
    ctx = f"Skills: {', '.join(skills[:15])}\n"
    ctx += f"Tools: {', '.join(tools[:10])}\n"
    if experience:
        ctx += f"Experience: {experience}\n"
    if projects:
        ctx += "Projects:\n" + "\n".join(
            f"  - {p.get('name', '')}: {p.get('description', '')} [{', '.join(p.get('technologies', [])[:5])}]"
            for p in projects[:5]
        ) + "\n"
    if claims:
        ctx += "Key claims: " + "; ".join(claims[:6])
    return ctx


class FollowUpAgent:
    """
    Generates the next interview question based on:
    - Detected weakness with specific attack strategy (targeted probe)
    - Resume discrepancy (direct confrontation challenge)
    - Sprint goal + persona (fresh question for normal progression)
    - Speculative prefetch from partial transcript (latency masking)

    All methods are context-aware: they use resume, history, sprint, and persona.
    """

    def __init__(self):
        self.llm = LLMRouter(tier="medium")

    async def generate(
        self,
        question: str,
        answer: str,
        weakness: dict,
        persona: str,
        resume: str,
        parsed_resume: dict | None = None,
    ) -> str:
        """
        High-severity weakness detected → generate a targeted probe.
        Uses the weakness type's specific attack strategy to drive the question.
        """
        system = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["curious_lead"])
        resume_context = _build_resume_context(parsed_resume, resume)

        attack_strategy = weakness.get("attack_strategy", "step_by_step")
        strategy_instruction = ATTACK_STRATEGY_INSTRUCTIONS.get(
            attack_strategy,
            ATTACK_STRATEGY_INSTRUCTIONS["step_by_step"]
        )

        user = f"""Candidate background:
{resume_context}

Previous question: {question}

Candidate's answer: {answer}

Weakness detected:
- Type: {weakness.get('type', 'unknown')}
- Gap: {weakness.get('weakness', '')}
- Attack strategy: {attack_strategy}
- How to execute it: {strategy_instruction}

Generate ONE follow-up question that executes this attack strategy.
Ground it in something specific from their resume or answer.
Output only the question."""

        result = await self.llm.call(system=system, user=user)
        return result if isinstance(result, str) else result.get("followup", str(result))

    async def generate_discrepancy_challenge(
        self,
        question: str,
        answer: str,
        discrepancy: dict,
        persona: str,
        resume: str,
        parsed_resume: dict | None = None,
    ) -> str:
        """
        Resume discrepancy detected → generate a direct but non-accusatory confrontation.
        The candidate said something that contradicts their resume claims.
        """
        system = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["curious_lead"])
        resume_context = _build_resume_context(parsed_resume, resume)

        user = f"""Candidate background:
{resume_context}

Previous question: {question}

Candidate's answer: {answer}

Discrepancy detected between their answer and their resume:
{discrepancy.get('description', '')}

Generate ONE question that surfaces this inconsistency — curious and direct, not accusatory.
The goal is to give them a chance to explain or clarify, not to catch them in a lie.
Reference the specific thing from their resume that conflicts.
Output only the question."""

        result = await self.llm.call(system=system, user=user)
        return result if isinstance(result, str) else result.get("question", str(result))

    async def generate_sprint_question(
        self,
        sprint: int,
        persona: str,
        resume: str,
        history: list[dict],
        weakness: dict | None = None,
        parsed_resume: dict | None = None,
    ) -> tuple[str, list[str]]:
        """
        Low/medium severity or clean answer → advance to the next question for this sprint.
        Generates a fresh question grounded in the candidate's actual resume and history.
        Returns (question_text, followups) — followups are the bank's pre-written deepening
        questions for the seed used, adapted to this candidate on the next turn.
        """
        covered = [h.get("question", "") for h in history[-6:]]
        covered_str = "\n".join(f"- {q}" for q in covered) if covered else "None yet."
        resume_context = _build_resume_context(parsed_resume, resume)

        # Retrieve 2 relevant questions from the bank as structural seeds.
        # The LLM adapts the best fit to this specific candidate — never used verbatim.
        rag_candidates = question_bank.retrieve(resume_context[:400], sprint=sprint, top_k=2)
        rag_context = ""
        # Capture followups from the best-matching seed for use as the next turn's deepening questions
        seed_followups: list[str] = []
        if rag_candidates:
            rag_context = "\n\nStructural question seeds (adapt to the candidate — do NOT copy verbatim):\n"
            rag_context += "\n".join(f"- {q['text']}" for q in rag_candidates)
            seed_followups = rag_candidates[0].get("followups", [])

        system = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["curious_lead"])
        user = f"""Sprint goal: {SPRINT_GOALS.get(sprint, '')}

Candidate background:
{resume_context}

Questions already asked (do NOT repeat these):
{covered_str}{rag_context}

Generate ONE new interview question that:
- Directly references something specific from their resume (a project by name, a technology they listed, a claim they made)
- Aligns with the sprint goal above
- Has not been covered already
- Fits your interviewer persona

Output only the question."""

        result = await self.llm.call(system=system, user=user)
        question = result if isinstance(result, str) else result.get("question", str(result))
        return question, seed_followups

    async def adapt_followup(
        self,
        raw_followup: str,
        question: str,
        answer: str,
        persona: str,
        resume_context: str,
    ) -> str:
        """
        Takes a raw follow-up template from the question bank and grounds it in the
        candidate's specific answer. Called between sprint questions to go one level deeper
        before advancing to the next topic.
        """
        system = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["curious_lead"])
        user = f"""The interview just covered this exchange:
Q: {question}
A: {answer[:400]}

Candidate background:
{resume_context[:300]}

Adapt this follow-up question so it references something specific from their answer above:
"{raw_followup}"

Output only the adapted question. ONE question, conversational."""

        result = await self.llm.call(system=system, user=user)
        # Fallback: use the raw template if LLM fails
        return result if isinstance(result, str) else raw_followup

    async def prefetch(self, concepts: list[str], state: dict) -> list[str]:
        """
        Speculatively generate follow-ups while the candidate is still speaking.
        Fires on interim results — the result is ready when the final transcript arrives.
        """
        if not concepts:
            return []

        persona = state.get("current_persona", "curious_lead")
        parsed_resume = state.get("parsed_resume", {})
        resume_context = _build_resume_context(parsed_resume, state.get("resume", ""))
        sprint = state.get("current_sprint", 1)

        system = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["curious_lead"])
        user = f"""Sprint {sprint} — {SPRINT_GOALS.get(sprint, '')}

Candidate background:
{resume_context[:600]}

The candidate is currently talking about: {', '.join(concepts[:3])}.

Generate 2 short follow-up questions that dig deeper, grounded in their specific background.
Output JSON: {{"questions": ["...", "..."]}}"""

        result = await self.llm.call(system=system, user=user)
        if isinstance(result, dict):
            return result.get("questions", [])
        return []
