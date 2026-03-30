import asyncio
import uuid
from backend.agents.concept_agent import ConceptAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.agents.followup_agent import FollowUpAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.state.session_manager import SessionManager


class Orchestrator:
    """
    Core brain of the interview system.
    Manages session state, triggers parallel agents,
    selects responses, enforces interview flow.
    """

    def __init__(self):
        self.session_manager = SessionManager()
        self.concept_agent = ConceptAgent()
        self.weakness_agent = WeaknessAgent()
        self.followup_agent = FollowUpAgent()
        self.discrepancy_agent = DiscrepancyAgent()

    async def start_session(self, resume: str, github_links: list[str]) -> str:
        session_id = str(uuid.uuid4())
        initial_state = {
            "session_id": session_id,
            "current_module": "project_defense",
            "current_sprint": 1,
            "resume": resume,
            "github_links": github_links,
            "skills": [],
            "scores": {},
            "weaknesses": [],
            "history": [],
            "confidence_scores": {},
            "failure_surface": {},
        }
        await self.session_manager.save_state(session_id, initial_state)
        return session_id

    async def handle_transcript(self, session_id: str, text: str) -> dict:
        state = await self.session_manager.get_state(session_id)
        last_question = state.get("last_question", "")

        # Fire parallel agents
        concept_task = self.concept_agent.extract(text)
        weakness_task = self.weakness_agent.detect(last_question, text)
        discrepancy_task = self.discrepancy_agent.check(state.get("resume", ""), text)

        concepts, weakness, discrepancy = await asyncio.gather(
            concept_task, weakness_task, discrepancy_task
        )

        if weakness.get("severity") == "high":
            followup = await self.followup_agent.generate(last_question, text, weakness)
        else:
            followup = await self.followup_agent.get_precomputed(state)

        # Update state
        state["history"].append({"question": last_question, "answer": text, "weakness": weakness})
        state["last_question"] = followup
        if weakness:
            state["weaknesses"].append(weakness)

        await self.session_manager.save_state(session_id, state)

        return {
            "response": followup,
            "concepts": concepts,
            "weakness": weakness,
            "discrepancy": discrepancy,
        }

    async def get_session_state(self, session_id: str) -> dict:
        return await self.session_manager.get_state(session_id)
