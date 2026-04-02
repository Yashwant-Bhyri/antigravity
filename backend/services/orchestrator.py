import asyncio
import time
import uuid
from backend.agents.concept_agent import ConceptAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.agents.followup_agent import FollowUpAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.evaluation_agent import EvaluationAgent
from backend.agents.resume_agent import ResumeAgent
from backend.agents.reasoning_behavior_agent import ReasoningBehaviorAgent
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
        "goal": "Understand the candidate's most significant project — the problem it solved, their personal contribution, and the key decisions they made.",
    },
    2: {
        "name": "Foundations",
        "persona": "socratic_mentor",
        "goal": "Explore the candidate's conceptual understanding of the technical ideas in their work — reasoning and intuition, not trivia.",
    },
    3: {
        "name": "System Design",
        "persona": "senior_peer",
        "goal": "Think through real engineering trade-offs together — scaling, failure modes, and design alternatives.",
    },
}

# Opening question per sprint — asked when sprint begins
SPRINT_OPENERS = {
    1: "Tell me about a project from your background that you're genuinely proud of — what problem were you trying to solve, and why did it matter?",
    2: "Let's talk about the technical concepts behind your work. Pick one idea at the core of what you've built — how would you explain it to someone encountering it for the first time?",
    3: "Let's think through a design problem. Imagine you're building a system to serve real-time predictions for millions of users — where would you start, and what are the hardest parts to get right?",
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
        self.resume_agent = ResumeAgent()
        self.reasoning_agent = ReasoningBehaviorAgent()

        # Prefetched follow-ups keyed by session_id
        self._prefetched: dict[str, list[str]] = {}

        # Per-answer scores accumulated throughout the interview (non-blocking, fired async)
        self._per_answer_scores: dict[str, list[dict]] = {}

    # ─────────────────────────────────────────────
    # SESSION LIFECYCLE
    # ─────────────────────────────────────────────

    async def start_session(self, resume: str, github_links: list[str]) -> str:
        session_id = str(uuid.uuid4())

        # Parse resume into structured data immediately — runs in parallel with state save
        parsed_resume = await self.resume_agent.parse(resume)
        if not isinstance(parsed_resume, dict):
            parsed_resume = {}

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
            "parsed_resume": parsed_resume,  # structured: skills, projects, claims, tools, experience
            "github_links": github_links,
            "skills": parsed_resume.get("skills", []),
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
        Incorporates accumulated per-answer scores and reasoning behavior signals.
        """
        state = await self.session_manager.get_state(session_id)
        state["interview_complete"] = True

        history = state.get("history", [])
        if history:
            # Aggregate reasoning behavior signals from all turns
            reasoning_signals = [
                h.get("reasoning_behavior", {})
                for h in history
                if isinstance(h.get("reasoning_behavior"), dict)
            ]

            # Accumulated per-answer scores (may be partial — background tasks)
            per_answer_scores = self._per_answer_scores.pop(session_id, [])

            evaluation = await self.evaluation_agent.score_full_interview(
                history=history,
                resume=state.get("resume", ""),
                weaknesses=state.get("weaknesses", []),
                reasoning_signals=reasoning_signals,
                per_answer_scores=per_answer_scores,
            )
            state["final_evaluation"] = evaluation
            state["scores"] = evaluation.get("breakdown", {})
            state["failure_surface"] = evaluation.get("failure_surface", {})

        await self.session_manager.save_state(session_id, state)
        self._prefetched.pop(session_id, None)
        self._last_prefetch_len.pop(session_id, None)
        return state

    async def _score_answer_async(self, session_id: str, question: str, answer: str):
        """
        Runs per-answer scoring in the background — does not block the response path.
        Accumulates scores for richer final evaluation context.
        """
        try:
            score = await self.evaluation_agent.score_answer(question, answer)
            if isinstance(score, dict) and "score" in score:
                if session_id not in self._per_answer_scores:
                    self._per_answer_scores[session_id] = []
                self._per_answer_scores[session_id].append({
                    "question": question[:100],
                    "score": score.get("score", 0),
                    "breakdown": score.get("breakdown", {}),
                })
        except Exception:
            pass  # non-fatal — final evaluation uses full transcript regardless

    # ─────────────────────────────────────────────
    # REAL-TIME TRANSCRIPT HANDLING
    # ─────────────────────────────────────────────

    # Tracks last partial length per session to throttle prefetch LLM calls
    _last_prefetch_len: dict[str, int] = {}

    async def on_partial_transcript(self, session_id: str, text: str, entities: list[str] | None = None):
        """
        Fires on every is_final fragment while candidate is still speaking.
        Two paths:
        - Deepgram NER entities provided → use them directly (zero extra LLM call)
        - No entities → fall back to ConceptAgent extraction (throttled to avoid hammering)
        """
        if entities:
            # Fast path: Deepgram already extracted entities — skip ConceptAgent entirely
            state = await self.session_manager.get_state(session_id)
            prefetched = await self.followup_agent.prefetch(entities, state)
            if prefetched:
                self._prefetched[session_id] = prefetched
            return

        # Slow path: no entities — throttle and run ConceptAgent
        last_len = self._last_prefetch_len.get(session_id, 0)
        if len(text) - last_len < 40:
            return
        self._last_prefetch_len[session_id] = len(text)

        concepts = await self.concept_agent.extract(text)
        if concepts:
            state = await self.session_manager.get_state(session_id)
            prefetched = await self.followup_agent.prefetch(concepts, state)
            if prefetched:
                self._prefetched[session_id] = prefetched

    async def handle_transcript(self, session_id: str, text: str, entities: list[str] | None = None) -> dict:
        """
        Fires on full utterance (UtteranceEnd) with the complete answer.
        Runs parallel agent pipeline. If Deepgram entities are provided, skips ConceptAgent
        and uses them directly — faster and more precise (entities surfaced during speech).
        """
        state = await self.session_manager.get_state(session_id)

        if state.get("interview_complete"):
            return {"response": "The interview has concluded. Thank you.", "complete": True}

        last_question = state.get("last_question", "")
        persona = state.get("current_persona", "curious_lead")
        sprint = state.get("current_sprint", 1)
        resume = state.get("resume", "")
        parsed_resume = state.get("parsed_resume", {})
        prior_weaknesses = state.get("weaknesses", [])

        was_challenged = bool(prior_weaknesses and prior_weaknesses[-1].get("severity") == "high")

        # ── Parallel agent execution ──────────────────────
        # When Deepgram NER entities are available, skip ConceptAgent — entities are
        # already precise technical terms (e.g. "Redis", "transformer", "async event loop")
        # extracted during transcription, cost zero extra latency.
        three_agents = asyncio.gather(
            self.weakness_agent.detect(last_question, text, sprint=sprint, prior_weaknesses=prior_weaknesses),
            self.discrepancy_agent.check(resume, text),
            self.reasoning_agent.evaluate(text, was_challenged=was_challenged),
        )

        if entities:
            (weakness, discrepancy, reasoning) = await three_agents
            concepts = entities
        else:
            concepts_result, (weakness, discrepancy, reasoning) = await asyncio.gather(
                self.concept_agent.extract(text),
                three_agents,
            )
            concepts = concepts_result

        # ── Kick off per-answer scoring async (non-blocking) ──
        # Fires in background — doesn't slow down the response path
        asyncio.create_task(self._score_answer_async(session_id, last_question, text))

        # ── Select follow-up: priority order ──────────────
        # 1. Resume discrepancy (high): confront it directly — highest priority signal
        # 2. Reasoning weakness (high): targeted probe with attack strategy
        # 3. Prefetched question: already generated while candidate was speaking
        # 4. Sprint question: fresh resume-grounded question for normal progression

        discrepancy_conflict = (
            isinstance(discrepancy, dict)
            and discrepancy.get("conflict")
            and discrepancy.get("severity") == "high"
        )

        if discrepancy_conflict:
            followup = await self.followup_agent.generate_discrepancy_challenge(
                question=last_question,
                answer=text,
                discrepancy=discrepancy,
                persona=persona,
                resume=resume,
                parsed_resume=parsed_resume,
            )
        elif weakness.get("severity") == "high":
            followup = await self.followup_agent.generate(
                question=last_question,
                answer=text,
                weakness=weakness,
                persona=persona,
                resume=resume,
                parsed_resume=parsed_resume,
            )
        elif self._prefetched.get(session_id):
            followup = self._prefetched.pop(session_id)[0]
        else:
            followup = await self.followup_agent.generate_sprint_question(
                sprint=sprint,
                persona=persona,
                resume=resume,
                parsed_resume=parsed_resume,
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
            "reasoning_behavior": reasoning,
            "sprint": sprint,
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
