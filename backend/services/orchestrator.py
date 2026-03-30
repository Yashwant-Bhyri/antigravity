import asyncio
import time
import uuid
from backend.agents.concept_agent import ConceptAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.agents.followup_agent import FollowUpAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.evaluation_agent import EvaluationAgent
from backend.state.session_manager import SessionManager


# ─────────────────────────────────────────────
# SPRINT CONFIG
# ─────────────────────────────────────────────
QUESTIONS_PER_SPRINT = 5
MAX_INTERVIEW_MINUTES = 30

SPRINTS = {
    1: {
        "name": "Project Defense",
        "persona": "curious_lead",
        "goal": "Verify the candidate actually built what they claim. Attack ownership, design decisions, and failure modes.",
    },
    2: {
        "name": "Foundations",
        "persona": "socratic_mentor",
        "goal": "Evaluate core conceptual understanding. Push until first principles are tested.",
    },
    3: {
        "name": "System Design",
        "persona": "senior_peer",
        "goal": "Evaluate real-world engineering thinking. Inject chaos. Force trade-off decisions.",
    },
}

# Opening question per sprint — asked when sprint begins
SPRINT_OPENERS = {
    1: "Let's start with your most technically complex project. Walk me through what you built.",
    2: "Let's shift gears. I want to test your fundamentals. Explain to me, from first principles, how gradient descent works.",
    3: "Final stretch — system design. Design a system that serves 1 million ML predictions per day. Start wherever you want.",
}


class Orchestrator:
    """
    The Interview Controller — the central brain.

    Manages:
    - Sprint progression (1 → 2 → 3, 5 questions each)
    - Persona switching (Curious Lead → Socratic Mentor → Senior Peer)
    - Parallel agent dispatch on every turn
    - Predictive prefetch during partial transcripts
    - Interview termination + full evaluation
    """

    def __init__(self):
        self.session_manager = SessionManager()
        self.concept_agent = ConceptAgent()
        self.weakness_agent = WeaknessAgent()
        self.followup_agent = FollowUpAgent()
        self.discrepancy_agent = DiscrepancyAgent()
        self.evaluation_agent = EvaluationAgent()

        # Prefetched follow-ups keyed by session_id
        self._prefetched: dict[str, list[str]] = {}

    # ─────────────────────────────────────────────
    # SESSION LIFECYCLE
    # ─────────────────────────────────────────────

    async def start_session(self, resume: str, github_links: list[str]) -> str:
        session_id = str(uuid.uuid4())
        state = {
            "session_id": session_id,
            # Sprint tracking
            "current_sprint": 1,
            "current_persona": "curious_lead",
            "sprint_name": SPRINTS[1]["name"],
            "question_count": 0,
            "sprint_question_count": 0,
            # Timing
            "interview_start_time": time.time(),
            "interview_complete": False,
            # Candidate data
            "resume": resume,
            "github_links": github_links,
            "skills": [],
            # Scores & analysis
            "scores": {},
            "weaknesses": [],
            "history": [],
            "failure_surface": {},
            "final_evaluation": None,
            # Current state
            "last_question": SPRINT_OPENERS[1],
        }
        await self.session_manager.save_state(session_id, state)
        return session_id

    async def end_session(self, session_id: str) -> dict:
        """
        Called when interview ends (time up, all sprints done, or candidate ends it).
        Runs full evaluation across entire history and writes final scores to state.
        """
        state = await self.session_manager.get_state(session_id)
        state["interview_complete"] = True

        history = state.get("history", [])
        if history:
            evaluation = await self.evaluation_agent.score_full_interview(
                history=history,
                resume=state.get("resume", ""),
                weaknesses=state.get("weaknesses", []),
            )
            state["final_evaluation"] = evaluation
            state["scores"] = evaluation.get("breakdown", {})
            state["failure_surface"] = evaluation.get("failure_surface", {})

        await self.session_manager.save_state(session_id, state)
        return state

    # ─────────────────────────────────────────────
    # REAL-TIME TRANSCRIPT HANDLING
    # ─────────────────────────────────────────────

    async def on_partial_transcript(self, session_id: str, text: str):
        """
        Fires on every Deepgram interim result while candidate is still speaking.
        Runs concept extraction immediately and speculatively prefetches follow-ups.
        This is the latency trick — work starts before the candidate finishes.
        """
        concepts = await self.concept_agent.extract(text)
        if concepts:
            state = await self.session_manager.get_state(session_id)
            prefetched = await self.followup_agent.prefetch(concepts, state)
            self._prefetched[session_id] = prefetched

    async def handle_transcript(self, session_id: str, text: str) -> dict:
        """
        Fires on Deepgram final transcript.
        Runs full parallel agent pipeline, advances sprint if needed,
        terminates interview if complete.
        """
        state = await self.session_manager.get_state(session_id)

        if state.get("interview_complete"):
            return {"response": "The interview has concluded. Thank you.", "complete": True}

        last_question = state.get("last_question", "")
        persona = state.get("current_persona", "curious_lead")

        # ── Parallel agent execution ──────────────────────
        concepts, weakness, discrepancy = await asyncio.gather(
            self.concept_agent.extract(text),
            self.weakness_agent.detect(last_question, text),
            self.discrepancy_agent.check(state.get("resume", ""), text),
        )

        # ── Select follow-up ──────────────────────────────
        if weakness.get("severity") == "high":
            # High severity: generate targeted probe
            followup = await self.followup_agent.generate(
                question=last_question,
                answer=text,
                weakness=weakness,
                persona=persona,
                resume=state.get("resume", ""),
            )
        elif self._prefetched.get(session_id):
            followup = self._prefetched.pop(session_id)[0]
        else:
            # Low/medium severity: advance to next question for this sprint
            followup = await self.followup_agent.generate_sprint_question(
                sprint=state["current_sprint"],
                persona=persona,
                resume=state.get("resume", ""),
                history=state.get("history", []),
                weakness=weakness,
            )

        # ── Update state ──────────────────────────────────
        state["history"].append({
            "question": last_question,
            "answer": text,
            "weakness": weakness,
            "concepts": concepts,
            "discrepancy": discrepancy,
            "sprint": state["current_sprint"],
            "persona": persona,
        })
        if weakness and weakness.get("type"):
            state["weaknesses"].append(weakness)

        state["question_count"] += 1
        state["sprint_question_count"] += 1
        state["last_question"] = followup

        # ── Sprint progression ────────────────────────────
        advanced, sprint_followup = await self._maybe_advance_sprint(state)
        if advanced:
            followup = sprint_followup

        # ── Termination check ─────────────────────────────
        complete = self._is_complete(state)

        await self.session_manager.save_state(session_id, state)

        if complete:
            await self.end_session(session_id)
            return {
                "response": "That wraps up our interview. Well done for getting through all three sprints. Your report is being generated now.",
                "concepts": concepts,
                "weakness": weakness,
                "sprint": state["current_sprint"],
                "persona": persona,
                "complete": True,
            }

        return {
            "response": followup,
            "concepts": concepts,
            "weakness": weakness,
            "discrepancy": discrepancy,
            "sprint": state["current_sprint"],
            "sprint_name": state["sprint_name"],
            "persona": persona,
            "question_count": state["question_count"],
            "complete": False,
        }

    # ─────────────────────────────────────────────
    # SPRINT LOGIC
    # ─────────────────────────────────────────────

    async def _maybe_advance_sprint(self, state: dict) -> tuple[bool, str]:
        """
        Checks if current sprint is exhausted. If so, advances sprint and
        returns the opening question for the new sprint.
        Mutates state in place.
        """
        if state["sprint_question_count"] < QUESTIONS_PER_SPRINT:
            return False, ""

        next_sprint = state["current_sprint"] + 1
        if next_sprint > 3:
            return False, ""

        state["current_sprint"] = next_sprint
        state["current_persona"] = SPRINTS[next_sprint]["persona"]
        state["sprint_name"] = SPRINTS[next_sprint]["name"]
        state["sprint_question_count"] = 0

        opener = SPRINT_OPENERS[next_sprint]
        state["last_question"] = opener

        return True, opener

    def _is_complete(self, state: dict) -> bool:
        """Interview ends when sprint 3 is exhausted or 30 minutes elapsed."""
        if state["current_sprint"] == 3 and state["sprint_question_count"] >= QUESTIONS_PER_SPRINT:
            return True
        elapsed_minutes = (time.time() - state["interview_start_time"]) / 60
        if elapsed_minutes >= MAX_INTERVIEW_MINUTES:
            return True
        return False

    async def get_session_state(self, session_id: str) -> dict:
        return await self.session_manager.get_state(session_id)
