import asyncio
import time
import uuid
from backend.db.postgres import persist_session
from backend.agents.concept_agent import ConceptAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.evaluation_agent import EvaluationAgent
from backend.agents.resume_agent import ResumeAgent
from backend.agents.reasoning_behavior_agent import ReasoningBehaviorAgent
from backend.state.session_manager import SessionManager


def _build_resume_context_for_followup(parsed_resume: dict | None, resume: str) -> str:
    """Thin wrapper so orchestrator can call the shared helper without circular imports."""
    return _build_resume_context(parsed_resume, resume)


# Fallback follow-ups used when the RAG bank returns no seed questions.
# Sprint-keyed so they stay contextually relevant even without a bank hit.
_FALLBACK_FOLLOWUPS: dict[int, list[str]] = {
    1: [
        "What would you do differently if you were starting this project from scratch today?",
        "What was the hardest part to get right, and how did you know when you'd actually solved it?",
    ],
    2: [
        "Where does your mental model of this concept start to break down?",
        "How would you explain the trade-off you just described to an engineer who hasn't worked in this space?",
    ],
    3: [
        "What's the first thing that breaks under load in the design you just described?",
        "What would you instrument to catch that failure before it hits production?",
    ],
}


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

        # Per-answer scores accumulated throughout the interview (non-blocking, fired async)
        self._per_answer_scores: dict[str, list[dict]] = {}

        # Entity accumulation from partial transcripts — consumed on full turn commit
        self._partial_entities: dict[str, set] = {}

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
            # Adversarialism guardrails — prevent infinite probe loops on the same gap
            "consecutive_high_weakness_count": 0,
            "last_weakness_type": None,
            # Follow-up sequencing — deepening questions from the question bank
            "current_question_followups": [],   # follow-up templates for the current sprint question
            "current_question_followup_asked": False,  # only one follow-up per sprint question
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

            # Coverage ratio: unique weakness types / total weaknesses.
            # Low ratio = interview was narrow; evaluation confidence should be capped.
            weaknesses = state.get("weaknesses", [])
            unique_types = len({w.get("type") for w in weaknesses if w.get("type")})
            coverage_ratio = unique_types / max(len(weaknesses), 1) if weaknesses else 1.0

            evaluation = await self.evaluation_agent.score_full_interview(
                history=history,
                resume=state.get("resume", ""),
                weaknesses=weaknesses,
                reasoning_signals=reasoning_signals,
                per_answer_scores=per_answer_scores,
                coverage_ratio=coverage_ratio,
            )
            state["final_evaluation"] = evaluation
            state["scores"] = evaluation.get("breakdown", {})
            state["failure_surface"] = evaluation.get("failure_surface", {})

        await self.session_manager.save_state(session_id, state)
        self._partial_entities.pop(session_id, None)

        # Persist to Postgres for recruiter dashboard — non-blocking, best-effort
        try:
            evaluation = state.get("final_evaluation") or {}
            duration = (time.time() - state.get("interview_start_time", time.time())) / 60
            asyncio.create_task(persist_session(
                session_id=session_id,
                resume_snippet=state.get("resume", "")[:200],
                hire_recommendation=evaluation.get("hire_recommendation", ""),
                overall_score=float(evaluation.get("overall_score") or 0),
                sprint_reached=int(state.get("current_sprint", 1)),
                duration_minutes=round(duration, 1),
            ))
        except Exception:
            pass  # Postgres failure never blocks the interview response

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

    async def on_partial_transcript(self, session_id: str, text: str, entities: list[str] | None = None):
        """
        Fires on every is_final fragment while candidate is still speaking.
        Timing/warmup only — NO LLM calls here.
        Entity accumulation happens client-side (Deepgram NER). Nothing is sent to agents
        until handle_transcript() fires on the full committed utterance.
        TODO: retrieval warmup — pre-fetch rubrics from RAG index using entities (CC-4/CX-2)
        """
        # Accumulate entities for use when the full turn arrives — no LLM spend
        if entities:
            existing = self._partial_entities.get(session_id, set())
            existing.update(entities)
            self._partial_entities[session_id] = existing

    async def handle_transcript(self, session_id: str, text: str, entities: list[str] | None = None, turn_id: str = "") -> dict:
        """
        Fires on full committed utterance with the complete answer.
        Merges any entities accumulated during partials with entities from the final turn.
        Runs parallel agent pipeline. turn_id is echoed back so the frontend can detect
        and discard stale responses (e.g. if user started speaking again before this resolved).
        """
        state = await self.session_manager.get_state(session_id)

        if state.get("interview_complete"):
            return {"response": "The interview has concluded. Thank you.", "complete": True, "turn_id": turn_id}

        # Merge entities from partial accumulation with any from the final turn
        accumulated = self._partial_entities.pop(session_id, set())
        if entities:
            accumulated.update(entities)
        entities = list(accumulated) if accumulated else entities

        last_question = state.get("last_question", "")
        persona = state.get("current_persona", "curious_lead")
        sprint = state.get("current_sprint", 1)
        resume = state.get("resume", "")
        parsed_resume = state.get("parsed_resume", {})
        prior_weaknesses = state.get("weaknesses", [])

        was_challenged = bool(prior_weaknesses and prior_weaknesses[-1].get("severity") == "high")

        # ── Parallel agent execution ──────────────────────
        # return_exceptions=True: individual agent failures get a fallback value instead
        # of crashing the entire turn. Without this, a single LLM API blip causes a 500
        # that shows "Agent pipeline error" in the frontend.
        _WEAKNESS_FALLBACK = {"weakness": "", "type": "vague", "severity": "low", "attack_strategy": "step_by_step"}
        _DISCREPANCY_FALLBACK = {"conflict": False, "description": "", "severity": "low"}
        _REASONING_FALLBACK = {"structure_score": 5, "adaptability": "flexible", "confidence_calibration": "calibrated"}

        async def _safe_weakness():
            try:
                return await self.weakness_agent.detect(last_question, text, sprint=sprint, prior_weaknesses=prior_weaknesses)
            except Exception as e:
                print(f"[Orchestrator] WeaknessAgent failed: {e}")
                return _WEAKNESS_FALLBACK

        async def _safe_discrepancy():
            try:
                return await self.discrepancy_agent.check(resume, text)
            except Exception as e:
                print(f"[Orchestrator] DiscrepancyAgent failed: {e}")
                return _DISCREPANCY_FALLBACK

        async def _safe_reasoning():
            try:
                return await self.reasoning_agent.evaluate(text, was_challenged=was_challenged)
            except Exception as e:
                print(f"[Orchestrator] ReasoningAgent failed: {e}")
                return _REASONING_FALLBACK

        three_agents = asyncio.gather(
            _safe_weakness(),
            _safe_discrepancy(),
            _safe_reasoning(),
        )

        if entities:
            (weakness, discrepancy, reasoning) = await three_agents
            concepts = entities
        else:
            async def _safe_concepts():
                try:
                    return await self.concept_agent.extract(text)
                except Exception as e:
                    print(f"[Orchestrator] ConceptAgent failed: {e}")
                    return []

            concepts_result, (weakness, discrepancy, reasoning) = await asyncio.gather(
                _safe_concepts(),
                three_agents,
            )
            concepts = concepts_result

        # ── Kick off per-answer scoring async (non-blocking) ──
        # Fires in background — doesn't slow down the response path
        asyncio.create_task(self._score_answer_async(session_id, last_question, text))

        # ── Honest admission soft-cap ─────────────────────
        # If ReasoningBehaviorAgent detects the candidate admitted a gap or self-corrected,
        # downgrade weakness severity to medium. Intellectual honesty is not evasion.
        # This routes Turn 7-style moments ("it's a glorified prompt optimizer") to curiosity
        # instead of another attack probe.
        reasoning_adaptability = reasoning.get("adaptability", "") if isinstance(reasoning, dict) else ""
        # Only soft-cap on explicit admitted_gap — "flexible" alone is normal good behavior,
        # not a reason to downgrade a legitimate weakness. WeaknessAgent prompt now handles
        # honest admission in its own classification; this is a safety-net cross-check only.
        honest_admission = reasoning_adaptability == "admitted_gap"
        if honest_admission and weakness.get("severity") == "high":
            weakness = {**weakness, "severity": "medium"}  # soft-cap, preserve all other fields

        # ── Consecutive weakness guardrail ────────────────
        # After 2 consecutive high-severity hits on the same weakness type, force a
        # sprint question. The signal is already captured — hammering it further adds
        # no new information and produces an interrogation instead of an interview.
        wtype = weakness.get("type") if weakness else None
        if weakness and weakness.get("severity") == "high":
            if wtype == state.get("last_weakness_type"):
                state["consecutive_high_weakness_count"] = state.get("consecutive_high_weakness_count", 0) + 1
            else:
                state["consecutive_high_weakness_count"] = 1
            state["last_weakness_type"] = wtype
        else:
            state["consecutive_high_weakness_count"] = 0
            state["last_weakness_type"] = None

        force_sprint_question = state.get("consecutive_high_weakness_count", 0) >= 2
        pivoting = force_sprint_question  # surfaced to frontend for subtle UI signal

        # ── Select follow-up: priority order ──────────────
        # 1. Resume discrepancy (high, not exhausted) → direct confrontation
        # 2. Reasoning weakness (high, not exhausted) → targeted probe
        # 3. Follow-up deepening question from question bank → go one level deeper on current topic
        # 4. Sprint question → advance to next topic

        discrepancy_conflict = (
            isinstance(discrepancy, dict)
            and discrepancy.get("conflict")
            and discrepancy.get("severity") == "high"
        )

        resume_context = _build_resume_context_for_followup(parsed_resume, resume)

        if discrepancy_conflict and not force_sprint_question:
            followup = await self.followup_agent.generate_discrepancy_challenge(
                question=last_question,
                answer=text,
                discrepancy=discrepancy,
                persona=persona,
                resume=resume,
                parsed_resume=parsed_resume,
            )
        elif weakness.get("severity") == "high" and not force_sprint_question:
            followup = await self.followup_agent.generate(
                question=last_question,
                answer=text,
                weakness=weakness,
                persona=persona,
                resume=resume,
                parsed_resume=parsed_resume,
            )
        elif (
            not state.get("current_question_followup_asked")
            and state.get("current_question_followups")
        ):
            # Ask a deepening follow-up from the question bank before advancing topics.
            # Adapts the raw template to what the candidate actually said.
            raw_followup = state["current_question_followups"].pop(0)
            followup = await self.followup_agent.adapt_followup(
                raw_followup=raw_followup,
                question=last_question,
                answer=text,
                persona=persona,
                resume_context=resume_context,
            )
            state["current_question_followup_asked"] = True
        else:
            sprint_result = await self.followup_agent.generate_sprint_question(
                sprint=sprint,
                persona=persona,
                resume=resume,
                parsed_resume=parsed_resume,
                history=state.get("history", []),
                weakness=weakness,
            )
            followup, seed_followups = sprint_result
            # Prefer bank follow-ups; fall back to sprint-keyed universal templates
            followups_to_store = seed_followups[:1] or _FALLBACK_FOLLOWUPS.get(sprint, [])[:1]
            state["current_question_followups"] = followups_to_store
            state["current_question_followup_asked"] = False

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
                "pivoting": False,
                "turn_id": turn_id,
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
            "pivoting": pivoting,  # True when system consciously moves on from an exhausted gap
            "turn_id": turn_id,
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
        # Reset weakness guard — new sprint, clean slate
        state["consecutive_high_weakness_count"] = 0
        state["last_weakness_type"] = None
        state["current_question_followups"] = []
        state["current_question_followup_asked"] = False

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
