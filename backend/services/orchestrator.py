import asyncio
import re
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


# Fallback follow-ups: sprint-keyed templates used when no prepped question exists and the
# bank has nothing queued. No LLM call — served instantly as a last resort.
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

# Agent fallbacks — individual agent crash → use these so one LLM blip doesn't kill the turn
_WEAKNESS_FALLBACK    = {"weakness": "", "type": "vague", "severity": "low", "attack_strategy": "step_by_step"}
_DISCREPANCY_FALLBACK = {"conflict": False, "description": "", "severity": "low"}
_REASONING_FALLBACK   = {"structure_score": 5, "adaptability": "flexible", "confidence_calibration": "calibrated"}


_ADMISSION_SIGNALS = re.compile(
    r"\b(i don'?t know|i'?m not sure|i didn'?t (write|build|implement|code)|"
    r"to be honest|actually i|i should (mention|clarify|be honest)|"
    r"i'?m not (certain|familiar|sure)|i haven'?t|i can'?t (explain|tell)|"
    r"i was just|i only|it'?s basically|it'?s just|i mean it'?s not really|"
    r"i don'?t (really|actually) know)\b",
    re.IGNORECASE,
)


def _looks_like_admission(text: str) -> bool:
    """Detect honesty/gap signals in partial transcript — triggers speculative pivot."""
    return bool(_ADMISSION_SIGNALS.search(text))


def _normalize_transcript(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()


def _looks_like_question_echo(answer: str, question: str) -> bool:
    """
    Defensive filter for speaker bleed / browser-TTS feedback loops.
    If the "candidate answer" is mostly just the interviewer's question repeated back,
    do not let it consume a turn or drive the agent pipeline.
    """
    normalized_answer = _normalize_transcript(answer)
    normalized_question = _normalize_transcript(question)

    if not normalized_answer or not normalized_question:
        return False
    if len(normalized_answer) < 18:
        return False
    if normalized_question.startswith(normalized_answer):
        return True

    answer_words = [w for w in normalized_answer.split(" ") if len(w) > 2]
    question_word_set = {w for w in normalized_question.split(" ") if len(w) > 2}
    if len(answer_words) < 4:
        return False

    overlapping = [w for w in answer_words if w in question_word_set]
    overlap_ratio = len(overlapping) / max(len(answer_words), 1)
    novel_words = [w for w in answer_words if w not in question_word_set]
    return overlap_ratio >= 0.85 and len(novel_words) <= 2


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

SPRINT_OPENERS = {
    1: "Tell me about a project from your background that you're genuinely proud of — what problem were you trying to solve, and why did it matter?",
    2: "Let's talk about the technical concepts behind your work. Pick one idea at the core of what you've built — how would you explain it to someone encountering it for the first time?",
    3: "Let's think through a design problem. Imagine you're building a system to serve real-time predictions for millions of users — where would you start, and what are the hardest parts to get right?",
}


class Orchestrator:
    """
    The Interview Controller — two-track response architecture.

    ┌─ FAST TRACK (handle_transcript) ──────────────────────────── ~300-500ms ─┐
    │  1. Consume staged analysis from previous background run                  │
    │     → apply to canonical state (history, weaknesses, candidate_model)     │
    │  2. Serve fast response — priority:                                        │
    │     a) prepped_next_question (adversarial probe, instant, no LLM)         │
    │     b) bank follow-up via adapt_followup() (Haiku, ~300ms)                │
    │     c) sprint fallback template (instant, no LLM)                         │
    │  3. Update canonical counters (question_count, sprint_question_count)      │
    │  4. Kick off background pipeline as asyncio.create_task                   │
    │  5. Return — candidate hears a response in ≤500ms                         │
    └────────────────────────────────────────────────────────────────────────────┘

    ┌─ SLOW TRACK (_run_background_pipeline) ──────────── runs during candidate ─┐
    │  Full WeaknessAgent + DiscrepancyAgent + ReasoningBehaviorAgent in parallel │
    │  → all guardrails applied (honest admission, consecutive guard, S3 remap)   │
    │  → full FollowUpAgent priority chain → adversarial probe for next turn      │
    │  Writes ONLY to staging fields. Never touches canonical state.              │
    │  (Codex invariant: one path mutates canonical state per committed answer)   │
    └────────────────────────────────────────────────────────────────────────────┘

    Net effect: zero dead air. Full adversarial analysis runs during the candidate's
    answer to the fast follow-up. Adversarial probe arrives instantly on the next turn.
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

        self._per_answer_scores: dict[str, list[dict]] = {}
        self._partial_entities: dict[str, set] = {}

    # ─────────────────────────────────────────────
    # SESSION LIFECYCLE
    # ─────────────────────────────────────────────

    async def start_session(self, resume: str, github_links: list[str]) -> str:
        session_id = str(uuid.uuid4())

        parsed_resume = await self.resume_agent.parse(resume)
        if not isinstance(parsed_resume, dict):
            parsed_resume = {}

        state = {
            "session_id": session_id,
            "current_sprint": 1,
            "current_persona": "curious_lead",
            "sprint_name": SPRINTS[1]["name"],
            "question_count": 0,
            "sprint_question_count": 0,
            "interview_start_time": time.time(),
            "interview_complete": False,
            "resume": resume,
            "parsed_resume": parsed_resume,
            "github_links": github_links,
            "skills": parsed_resume.get("skills", []),
            "scores": {},
            "weaknesses": [],
            "history": [],
            "failure_surface": {},
            "final_evaluation": None,
            "last_question": SPRINT_OPENERS[1],
            "consecutive_high_weakness_count": 0,
            "last_weakness_type": None,
            "current_question_followups": [],
            "current_question_followup_asked": False,
            "candidate_model": {
                "project_map": {},
                "established_facts": [],
                "probed_weaknesses": [],
            },
            # ── Two-track staging fields ──────────────────────────────────────
            # Written ONLY by _run_background_pipeline.
            # Consumed atomically at the START of the next handle_transcript call.
            # Never written by the fast path (Codex invariant).
            #
            # prepped_next_question   — adversarial probe from full pipeline, served instantly
            # prepped_turn_analysis   — full agent output for the turn processed in background
            #                           applied to history/weaknesses when consumed next turn
            # prepped_next_metadata   — guard state + follow-up sequencing from background run
            "prepped_next_question": None,
            "prepped_turn_analysis": None,
            "prepped_next_metadata": {},
            # ── Speculative cache — partial-STT driven, Haiku only ────────────
            # Written ONLY by _run_speculative_generation (event-driven on partials).
            # Consumed in the fast path if no canonical prepped_next_question exists.
            # NEVER writes canonical state (Codex invariant extends here too).
            "speculative_cache": {},
        }
        await self.session_manager.save_state(session_id, state)

        # Pre-seed the first follow-up question from resume so Turn 1 never hits
        # the generic fallback. Runs as a background task — completes well before
        # the candidate finishes answering the sprint opener (~3-5s TTS + answer time).
        asyncio.create_task(self._seed_first_question(session_id))

        return session_id

    async def end_session(self, session_id: str) -> dict:
        state = await self.session_manager.get_state(session_id)
        state["interview_complete"] = True

        # Flush any staged analysis that hasn't been consumed so evaluation sees complete history
        staged = state.pop("prepped_turn_analysis", None)
        if staged and staged.get("session_id") == session_id:
            self._apply_staged_analysis(state, staged, state.pop("prepped_next_metadata", {}))
        state.pop("prepped_next_question", None)
        state.pop("prepped_next_metadata", None)
        state.pop("speculative_cache", None)

        history = state.get("history", [])
        if history:
            reasoning_signals = [
                h.get("reasoning_behavior", {})
                for h in history
                if isinstance(h.get("reasoning_behavior"), dict)
            ]
            per_answer_scores = self._per_answer_scores.pop(session_id, [])
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
            pass

        return state

    async def _score_answer_async(self, session_id: str, question: str, answer: str):
        """Per-answer scoring — fired from background pipeline, never blocks response path."""
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
            pass

    # ─────────────────────────────────────────────
    # REAL-TIME TRANSCRIPT HANDLING
    # ─────────────────────────────────────────────

    async def on_partial_transcript(self, session_id: str, text: str, entities: list[str] | None = None):
        """
        Fires on every is_final fragment while candidate is still speaking.

        Two jobs:
        1. Entity accumulation — merged into full turn at handle_transcript time
        2. Speculative question generation (event-driven, Haiku only):
           - New entity detected → generate entity-anchored follow-up
           - Admission/gap signal detected → generate exploratory pivot question
           NO canonical state written here. Codex invariant holds.
        """
        existing = self._partial_entities.get(session_id, set())

        if entities:
            new_entities = set(entities) - existing
            existing.update(entities)
            self._partial_entities[session_id] = existing

            # Event trigger: new named entity → speculative follow-up prep
            if new_entities and text:
                asyncio.create_task(
                    self._run_speculative_generation(
                        session_id=session_id,
                        partial_text=text,
                        new_entities=new_entities,
                        admission=False,
                    )
                )

        # Admission/gap signal — pivot to exploratory follow-up regardless of entities
        if text and _looks_like_admission(text):
            asyncio.create_task(
                self._run_speculative_generation(
                    session_id=session_id,
                    partial_text=text,
                    new_entities=set(),
                    admission=True,
                )
            )

    async def handle_transcript(
        self,
        session_id: str,
        text: str,
        entities: list[str] | None = None,
        turn_id: str = "",
    ) -> dict:
        """
        FAST PATH — returns in ~300-500ms regardless of full pipeline latency.

        On every committed utterance:
          1. Consume staged analysis from previous background run → apply to canonical state
          2. Serve fast response (prepped probe → bank follow-up → sprint fallback)
          3. Update canonical counters
          4. Kick off background pipeline (runs during candidate's next answer)
          5. Return immediately
        """
        state = await self.session_manager.get_state(session_id)

        if state.get("interview_complete"):
            return {"response": "The interview has concluded. Thank you.", "complete": True, "turn_id": turn_id}

        # Merge entities from partial accumulation
        accumulated = self._partial_entities.pop(session_id, set())
        if entities:
            accumulated.update(entities)
        entities = list(accumulated) if accumulated else entities

        last_question = state.get("last_question", "")
        sprint = state.get("current_sprint", 1)
        persona = state.get("current_persona", "curious_lead")
        parsed_resume = state.get("parsed_resume", {})
        resume = state.get("resume", "")
        resume_context = _build_resume_context_for_followup(parsed_resume, resume)

        # Ghost-VAD / echo filter — discard answers that are just the AI's question echoed back
        if _looks_like_question_echo(text, last_question):
            return {
                "response": "Your audio sounded like it picked up my question instead of your answer. Start again from the top and give me your answer in your own words.",
                "sprint": sprint,
                "sprint_name": state["sprint_name"],
                "persona": persona,
                "question_count": state["question_count"],
                "complete": False,
                "pivoting": False,
                "weakness": None,
                "discrepancy": None,
                "turn_id": turn_id,
            }

        # ── Step 1: Consume staged analysis from previous turn ────────────────
        # Background pipeline writes turn N's full analysis here.
        # Applied at the START of turn N+1 — never inside the background pipeline.
        # This is the single path that mutates canonical state per committed answer.
        staged_analysis = state.pop("prepped_turn_analysis", None)
        staged_metadata = state.pop("prepped_next_metadata", {})
        if staged_analysis and staged_analysis.get("session_id") == session_id:
            self._apply_staged_analysis(state, staged_analysis, staged_metadata)

        # ── Step 2: Determine fast response ──────────────────────────────────
        # Priority:
        # a) prepped_next_question — adversarial probe from canonical bg pipeline (instant)
        # b) speculative_cache — entity/admission-triggered Haiku question from partials (instant)
        # c) bank follow-up adapted via adapt_followup Haiku call (~300ms)
        # d) sprint fallback template (instant, no LLM)
        prepped_q = state.pop("prepped_next_question", None)
        pivoting = staged_metadata.get("pivoting", False)

        # Promote speculative candidate if no canonical probe and sprint still matches
        if not prepped_q:
            spec = state.get("speculative_cache", {})
            if spec.get("best_ready_question") and spec.get("sprint") == sprint:
                prepped_q = spec["best_ready_question"]
                state["speculative_cache"] = {}  # consume and clear
                print(f"[FastTrack] Speculative candidate promoted for {session_id}")

        if prepped_q:
            fast_response = prepped_q
            # Pass weakness that triggered this probe to frontend (for "BOUNDARY EXPOSED" badge)
            served_weakness = staged_analysis.get("weakness") if staged_analysis else None
            print(f"[FastTrack] Adversarial probe ready — serving instantly for {session_id}")

        elif (
            state.get("current_question_followups")
            and not state.get("current_question_followup_asked")
        ):
            # Adapt a pre-written bank template to the candidate's actual answer
            raw_followup = state["current_question_followups"].pop(0)
            fast_response = await self.followup_agent.adapt_followup(
                raw_followup=raw_followup,
                question=last_question,
                answer=text,
                persona=persona,
                resume_context=resume_context,
            )
            state["current_question_followup_asked"] = True
            served_weakness = None
            print(f"[FastTrack] Bank follow-up adapted for {session_id}")

        else:
            # No bank follow-up queued and no prepped question — use sprint fallback
            # Should be rare once the background pipeline is running steadily
            fallbacks = _FALLBACK_FOLLOWUPS.get(sprint, ["Walk me through your thinking on that."])
            fast_response = fallbacks[0]
            served_weakness = None
            print(f"[FastTrack] Sprint fallback served for {session_id}")

        # ── Step 3: Update canonical state ───────────────────────────────────
        # Only counters and current question. History/weaknesses/candidate_model
        # are updated when staged analysis is consumed (Step 1).
        state["question_count"] = state.get("question_count", 0) + 1
        state["sprint_question_count"] = state.get("sprint_question_count", 0) + 1
        state["last_question"] = fast_response

        advanced, sprint_opener = await self._maybe_advance_sprint(state, current_answer=text)
        if advanced:
            fast_response = sprint_opener
            state["last_question"] = fast_response

        complete = self._is_complete(state)
        await self.session_manager.save_state(session_id, state)

        if complete:
            await self.end_session(session_id)
            return {
                "response": "That wraps up our interview. Well done for getting through all three sprints. Your report is being generated now.",
                "sprint": state["current_sprint"],
                "persona": persona,
                "complete": True,
                "pivoting": False,
                "weakness": None,
                "discrepancy": None,
                "turn_id": turn_id,
            }

        # ── Step 4: Kick off background pipeline ─────────────────────────────
        # Runs during candidate's answer to fast_response.
        # Writes only to staging fields — canonical state never touched there.
        asyncio.create_task(
            self._run_background_pipeline(
                session_id=session_id,
                text=text,
                entities=entities,
                last_question=last_question,
                turn_id=turn_id,
            )
        )

        return {
            "response": fast_response,
            "sprint": state["current_sprint"],
            "sprint_name": state["sprint_name"],
            "persona": persona,
            "question_count": state["question_count"],
            "complete": False,
            "pivoting": pivoting,
            # Weakness that generated this question (from previous background run)
            # Allows frontend to show "BOUNDARY EXPOSED" on adversarial probes
            "weakness": served_weakness,
            "discrepancy": staged_analysis.get("discrepancy") if staged_analysis else None,
            "turn_id": turn_id,
        }

    def _apply_staged_analysis(self, state: dict, staged: dict, metadata: dict) -> None:
        """
        Apply a background pipeline's analysis to canonical session state.
        Called ONLY at the start of handle_transcript — never inside the background pipeline.

        Updates: history, weaknesses, candidate_model, consecutive weakness guard,
                 follow-up sequencing state.
        """
        turn_num = state.get("question_count", 0)

        # Append turn record to history
        state["history"].append({
            "question": staged.get("question", ""),
            "answer": staged.get("answer", ""),
            "weakness": staged.get("weakness"),
            "concepts": staged.get("concepts", []),
            "discrepancy": staged.get("discrepancy"),
            "reasoning_behavior": staged.get("reasoning_behavior"),
            "sprint": staged.get("sprint", state.get("current_sprint", 1)),
            "persona": staged.get("persona", state.get("current_persona", "curious_lead")),
        })

        # Append weakness to ledger
        weakness = staged.get("weakness")
        if weakness and weakness.get("type"):
            state["weaknesses"].append(weakness)

        # Apply candidate memory updates
        cm_updates = staged.get("candidate_model_updates", {})
        cm = state.get("candidate_model", {"project_map": {}, "established_facts": [], "probed_weaknesses": []})
        for fact in cm_updates.get("established_facts", []):
            if fact not in cm["established_facts"]:
                cm["established_facts"].append(fact)
        for probe in cm_updates.get("probed_weaknesses", []):
            cm["probed_weaknesses"].append(probe)
        cm["probed_weaknesses"] = cm["probed_weaknesses"][-8:]
        state["candidate_model"] = cm

        # Restore weakness guard state from background run
        if "consecutive_high_weakness_count" in metadata:
            state["consecutive_high_weakness_count"] = metadata["consecutive_high_weakness_count"]
            state["last_weakness_type"] = metadata.get("last_weakness_type")

        # Restore follow-up sequencing — only if background generated a sprint question
        # (discrepancy/weakness probes don't generate new bank follow-ups)
        if "current_question_followups" in metadata:
            state["current_question_followups"] = metadata["current_question_followups"]
            state["current_question_followup_asked"] = metadata.get("current_question_followup_asked", False)

    # ─────────────────────────────────────────────
    # BACKGROUND PIPELINE
    # ─────────────────────────────────────────────

    async def _run_background_pipeline(
        self,
        session_id: str,
        text: str,
        entities: list[str] | None,
        last_question: str,
        turn_id: str,
    ) -> None:
        """
        Full reasoning pipeline — runs during the candidate's answer to the fast follow-up.

        Runs all agents in parallel, applies all guardrails, generates the next adversarial
        question via the full FollowUpAgent priority chain.

        INVARIANT: canonical state fields (history, question_count, last_question, weaknesses,
        sprint counters, candidate_model) are NEVER mutated here. All outputs are staged in
        prepped_* fields and consumed atomically at the start of the next handle_transcript.
        """
        try:
            state = await self.session_manager.get_state(session_id)

            if state.get("interview_complete"):
                return

            sprint = state.get("current_sprint", 1)
            persona = state.get("current_persona", "curious_lead")
            resume = state.get("resume", "")
            parsed_resume = state.get("parsed_resume", {})
            prior_weaknesses = state.get("weaknesses", [])
            candidate_model = state.get("candidate_model", {"project_map": {}, "established_facts": [], "probed_weaknesses": []})
            was_challenged = bool(prior_weaknesses and prior_weaknesses[-1].get("severity") == "high")

            # Memory context for agents — what's been established and probed so far
            established_facts = candidate_model.get("established_facts", [])
            probed_weaknesses_list = candidate_model.get("probed_weaknesses", [])
            memory_context = ""
            if established_facts:
                memory_context += "Already established as true:\n" + "\n".join(f"- {f}" for f in established_facts[-4:]) + "\n"
            if probed_weaknesses_list:
                memory_context += "Already probed (avoid repeating):\n" + "\n".join(f"- {p}" for p in probed_weaknesses_list[-4:])

            # ── Parallel agent execution ──────────────────────────────────────
            async def _safe_weakness():
                try:
                    return await self.weakness_agent.detect(
                        last_question, text, sprint=sprint,
                        prior_weaknesses=prior_weaknesses,
                        memory_context=memory_context,
                    )
                except Exception as e:
                    print(f"[BGPipeline] WeaknessAgent failed: {e}")
                    return _WEAKNESS_FALLBACK

            async def _safe_discrepancy():
                try:
                    return await self.discrepancy_agent.check(resume, text, memory_context=memory_context)
                except Exception as e:
                    print(f"[BGPipeline] DiscrepancyAgent failed: {e}")
                    return _DISCREPANCY_FALLBACK

            async def _safe_reasoning():
                try:
                    return await self.reasoning_agent.evaluate(text, was_challenged=was_challenged)
                except Exception as e:
                    print(f"[BGPipeline] ReasoningAgent failed: {e}")
                    return _REASONING_FALLBACK

            if entities:
                weakness, discrepancy, reasoning = await asyncio.gather(
                    _safe_weakness(), _safe_discrepancy(), _safe_reasoning()
                )
                concepts = entities
            else:
                async def _safe_concepts():
                    try:
                        return await self.concept_agent.extract(text)
                    except Exception:
                        return []
                concepts_result, (weakness, discrepancy, reasoning) = await asyncio.gather(
                    _safe_concepts(),
                    asyncio.gather(_safe_weakness(), _safe_discrepancy(), _safe_reasoning()),
                )
                concepts = concepts_result

            # Per-answer scoring — fire and forget, never blocks anything
            asyncio.create_task(self._score_answer_async(session_id, last_question, text))

            # ── Honest admission soft-cap ─────────────────────────────────────
            reasoning_adaptability = reasoning.get("adaptability", "") if isinstance(reasoning, dict) else ""
            honest_admission = reasoning_adaptability == "admitted_gap"
            if honest_admission and weakness.get("severity") == "high":
                weakness = {**weakness, "severity": "medium"}

            # ── Consecutive weakness guardrail ────────────────────────────────
            wtype = weakness.get("type") if weakness else None
            if weakness and weakness.get("severity") == "high":
                if wtype == state.get("last_weakness_type"):
                    new_consecutive = state.get("consecutive_high_weakness_count", 0) + 1
                else:
                    new_consecutive = 1
            else:
                new_consecutive = 0
                wtype = None

            force_sprint_question = new_consecutive >= 2
            pivoting = force_sprint_question

            # ── Sprint 3 strategy remap ───────────────────────────────────────
            if sprint == 3 and weakness and weakness.get("attack_strategy") in ("implementation_probe", "step_by_step"):
                weakness = {**weakness, "attack_strategy": "scaling"}

            # ── Full priority chain → generates the next adversarial question ─
            discrepancy_conflict = (
                isinstance(discrepancy, dict)
                and discrepancy.get("conflict")
                and discrepancy.get("severity") == "high"
            )
            resume_context = _build_resume_context_for_followup(parsed_resume, resume)
            seed_followups: list[str] = []

            if discrepancy_conflict and not force_sprint_question:
                next_question = await self.followup_agent.generate_discrepancy_challenge(
                    question=last_question, answer=text, discrepancy=discrepancy,
                    persona=persona, resume=resume, parsed_resume=parsed_resume,
                )

            elif weakness.get("severity") == "high" and not force_sprint_question:
                next_question = await self.followup_agent.generate(
                    question=last_question, answer=text, weakness=weakness,
                    persona=persona, resume=resume, parsed_resume=parsed_resume,
                )

            elif (
                not state.get("current_question_followup_asked")
                and state.get("current_question_followups")
            ):
                # A bank follow-up is queued — adapt it for the next turn
                raw_followup = state["current_question_followups"][0]  # peek only, don't pop
                next_question = await self.followup_agent.adapt_followup(
                    raw_followup=raw_followup,
                    question=last_question,
                    answer=text,
                    persona=persona,
                    resume_context=resume_context,
                )

            else:
                sprint_result = await self.followup_agent.generate_sprint_question(
                    sprint=sprint,
                    persona=persona,
                    resume=resume,
                    parsed_resume=parsed_resume,
                    history=state.get("history", []),
                    weakness=weakness,
                )
                next_question, seed_followups = sprint_result

            # ── Candidate model updates (no LLM call) ────────────────────────
            turn_num = state.get("question_count", 0)
            candidate_model_updates: dict[str, list] = {"established_facts": [], "probed_weaknesses": []}

            if isinstance(discrepancy, dict) and not discrepancy.get("conflict") and discrepancy.get("description"):
                fact = discrepancy["description"][:120].rstrip(".") + f" (confirmed Turn {turn_num})"
                if fact not in candidate_model.get("established_facts", []):
                    candidate_model_updates["established_facts"].append(fact)

            if weakness and weakness.get("type") and weakness.get("weakness"):
                probe_note = f"{weakness['type']}: {weakness['weakness'][:80]} (Turn {turn_num})"
                candidate_model_updates["probed_weaknesses"].append(probe_note)

            # Follow-up sequencing metadata — passed to _apply_staged_analysis on next turn
            followups_to_store = seed_followups[:1] or _FALLBACK_FOLLOWUPS.get(sprint, [])[:1]

            # ── Write to staging fields only ──────────────────────────────────
            # Re-read state to pick up any handle_transcript changes since we started
            # (sprint advancement, question_count increment). This ensures our save
            # doesn't overwrite canonical counters with stale values.
            state = await self.session_manager.get_state(session_id)

            if state.get("interview_complete"):
                return  # Interview ended while we were processing — discard

            state["prepped_next_question"] = next_question
            state["prepped_turn_analysis"] = {
                "session_id": session_id,
                "question": last_question,
                "answer": text,
                "weakness": weakness,
                "concepts": concepts,
                "discrepancy": discrepancy,
                "reasoning_behavior": reasoning,
                "sprint": sprint,
                "persona": persona,
                "candidate_model_updates": candidate_model_updates,
            }
            state["prepped_next_metadata"] = {
                "pivoting": pivoting,
                "consecutive_high_weakness_count": new_consecutive,
                "last_weakness_type": wtype,
                "current_question_followups": followups_to_store,
                "current_question_followup_asked": False,
            }

            await self.session_manager.save_state(session_id, state)
            print(f"[BGPipeline] Turn {turn_num} complete — adversarial probe staged for {session_id}")

        except Exception as e:
            # Non-fatal: next turn gracefully falls back to bank follow-up or sprint fallback
            print(f"[BGPipeline] Failed for session {session_id}: {e}")

    # ─────────────────────────────────────────────
    # SPECULATIVE + SEEDING
    # ─────────────────────────────────────────────

    async def _seed_first_question(self, session_id: str) -> None:
        """
        Fires once as asyncio.create_task at session start.
        Generates a resume-grounded first follow-up via Haiku and stores it as
        prepped_next_question — so Turn 1's fast path never hits the generic fallback.

        Completes in ~300ms, well within the sprint opener TTS + candidate answer time (~10-30s).
        """
        try:
            state = await self.session_manager.get_state(session_id)
            resume_context = _build_resume_context_for_followup(
                state.get("parsed_resume"), state.get("resume", "")
            )
            question = await self.followup_agent.generate_seed_question(
                sprint=1,
                persona="curious_lead",
                resume_context=resume_context,
            )
            # Re-read before saving — don't overwrite any parallel changes
            state = await self.session_manager.get_state(session_id)
            if state.get("interview_complete") or state.get("prepped_next_question"):
                return
            state["prepped_next_question"] = question
            await self.session_manager.save_state(session_id, state)
            print(f"[Seed] Turn 1 follow-up pre-seeded for {session_id}")
        except Exception as e:
            print(f"[Seed] Failed to pre-seed first question: {e}")

    async def _run_speculative_generation(
        self,
        session_id: str,
        partial_text: str,
        new_entities: set,
        admission: bool = False,
    ) -> None:
        """
        Event-driven speculative question generation on partial transcripts.
        Haiku only. Writes ONLY to speculative_cache — never canonical state.

        Versioned: only the newest job can write. Stale jobs from slower LLM
        calls are silently dropped. Sprint-tagged: discarded if sprint advances
        before the job completes.

        Throttled: min 1s between calls to prevent entity-churn thrash.
        """
        try:
            state = await self.session_manager.get_state(session_id)
            if state.get("interview_complete"):
                return

            # Throttle
            cache = state.get("speculative_cache", {})
            if time.time() - cache.get("last_trigger_time", 0.0) < 1.0:
                return

            sprint = state.get("current_sprint", 1)
            persona = state.get("current_persona", "curious_lead")
            resume_context = _build_resume_context_for_followup(
                state.get("parsed_resume"), state.get("resume", "")
            )
            version = cache.get("speculation_version", 0) + 1

            question = await self.followup_agent.generate_speculative(
                partial_text=partial_text,
                new_entities=list(new_entities),
                last_question=state.get("last_question", ""),
                persona=persona,
                sprint=sprint,
                resume_context=resume_context,
                admission=admission,
            )

            # Re-read — only write if still latest version and sprint unchanged
            state = await self.session_manager.get_state(session_id)
            if state.get("interview_complete"):
                return
            if state.get("current_sprint", 1) != sprint:
                return  # Sprint advanced while we were generating — discard
            current_version = state.get("speculative_cache", {}).get("speculation_version", 0)
            if version <= current_version:
                return  # A newer job already wrote — discard

            state["speculative_cache"] = {
                "best_ready_question": question,
                "speculation_version": version,
                "last_trigger_time": time.time(),
                "sprint": sprint,
            }
            await self.session_manager.save_state(session_id, state)
            trigger = "admission" if admission else f"entities: {new_entities}"
            print(f"[Speculative] v{version} staged ({trigger}) for {session_id}")

        except Exception as e:
            print(f"[Speculative] Failed for {session_id}: {e}")

    # ─────────────────────────────────────────────
    # SPRINT LOGIC
    # ─────────────────────────────────────────────

    async def _maybe_advance_sprint(self, state: dict, current_answer: str = "") -> tuple[bool, str]:
        """
        Advance sprint if current one is exhausted. Mutates state in place.

        Sprint openers are generated dynamically — Haiku call (~300ms) with the last
        sprint's history + resume context. Falls back to static SPRINT_OPENERS if the
        LLM call fails.
        """
        if state["sprint_question_count"] < QUESTIONS_PER_SPRINT:
            return False, ""

        next_sprint = state["current_sprint"] + 1
        if next_sprint > 3:
            return False, ""

        prior_sprint = state["current_sprint"]
        next_persona = SPRINTS[next_sprint]["persona"]

        state["current_sprint"] = next_sprint
        state["current_persona"] = next_persona
        state["sprint_name"] = SPRINTS[next_sprint]["name"]
        state["sprint_question_count"] = 0
        state["consecutive_high_weakness_count"] = 0
        state["last_weakness_type"] = None
        state["current_question_followups"] = []
        state["current_question_followup_asked"] = False

        # Pull the turns from the sprint we're leaving — used as context for the opener.
        # The current turn's analysis is still in the background pipeline (not yet in history),
        # so we synthesize a partial record for it using what we do have: the last question
        # asked and the candidate's current answer.
        history = state.get("history", [])
        prior_sprint_history = [h for h in history if h.get("sprint") == prior_sprint]
        if current_answer and state.get("last_question"):
            prior_sprint_history = prior_sprint_history + [{
                "question": state["last_question"],
                "answer": current_answer,
                "sprint": prior_sprint,
            }]

        try:
            opener = await self.followup_agent.generate_sprint_opener(
                sprint=next_sprint,
                persona=next_persona,
                resume=state.get("resume", ""),
                parsed_resume=state.get("parsed_resume"),
                prior_sprint_history=prior_sprint_history,
            )
        except Exception as e:
            print(f"[SprintOpener] LLM failed for sprint {next_sprint}, using static fallback: {e}")
            opener = SPRINT_OPENERS[next_sprint]

        state["last_question"] = opener
        return True, opener

    def _is_complete(self, state: dict) -> bool:
        """Interview ends when sprint 3 is exhausted or 30 minutes elapsed."""
        if state["current_sprint"] == 3 and state["sprint_question_count"] >= QUESTIONS_PER_SPRINT:
            return True
        elapsed_minutes = (time.time() - state["interview_start_time"]) / 60
        return elapsed_minutes >= MAX_INTERVIEW_MINUTES

    async def get_session_state(self, session_id: str) -> dict:
        return await self.session_manager.get_state(session_id)
