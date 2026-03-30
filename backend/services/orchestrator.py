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

    Two transcript paths:
      on_partial_transcript() → fires on every Deepgram interim result
                                 starts concept extraction immediately for predictive prep
      handle_transcript()     → fires on Deepgram final result
                                 runs full parallel agent pipeline → returns follow-up question
    """

    def __init__(self):
        self.session_manager = SessionManager()
        self.concept_agent = ConceptAgent()
        self.weakness_agent = WeaknessAgent()
        self.followup_agent = FollowUpAgent()
        self.discrepancy_agent = DiscrepancyAgent()

        # Prefetched follow-ups keyed by session_id — populated during partial transcript
        self._prefetched: dict[str, list[str]] = {}

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
            "last_question": "Tell me about the most technically complex project you've built.",
        }
        await self.session_manager.save_state(session_id, initial_state)
        return session_id

    async def on_partial_transcript(self, session_id: str, text: str):
        """
        Called on every Deepgram interim result while candidate is still speaking.
        Runs concept extraction immediately and prefetches likely follow-ups.
        This is the latency trick — work starts before the candidate finishes.
        """
        concepts = await self.concept_agent.extract(text)
        if concepts:
            # Speculatively prefetch follow-ups for detected concepts
            state = await self.session_manager.get_state(session_id)
            prefetched = await self.followup_agent.prefetch(concepts, state)
            self._prefetched[session_id] = prefetched

    async def handle_transcript(self, session_id: str, text: str) -> dict:
        """
        Called on Deepgram final transcript.
        Fires all agents in parallel. Uses prefetched follow-ups if available.
        """
        state = await self.session_manager.get_state(session_id)
        last_question = state.get("last_question", "")

        # Fire parallel agents — nothing blocks
        concepts, weakness, discrepancy = await asyncio.gather(
            self.concept_agent.extract(text),
            self.weakness_agent.detect(last_question, text),
            self.discrepancy_agent.check(state.get("resume", ""), text),
        )

        # Select follow-up: dynamic if weakness is HIGH, else use prefetched or precomputed
        if weakness.get("severity") == "high":
            followup = await self.followup_agent.generate(last_question, text, weakness)
        elif self._prefetched.get(session_id):
            followup = self._prefetched.pop(session_id)[0]
        else:
            followup = await self.followup_agent.get_precomputed(state)

        # Update state
        state["history"].append({
            "question": last_question,
            "answer": text,
            "weakness": weakness,
            "concepts": concepts,
        })
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
