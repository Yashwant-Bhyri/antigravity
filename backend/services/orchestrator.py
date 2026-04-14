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
_WEAKNESS_FALLBACK    = {"weakness": "", "type": "vague", "severity": "low", "attack_strategy": "clarification"}
_DISCREPANCY_FALLBACK = {"conflict_level": "none", "description": "", "severity": "low"}
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


def _focus_key(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return key or "general"


def _resume_focus_candidates(parsed_resume: dict | None, resume: str) -> list[tuple[str, str, set[str]]]:
    parsed_resume = parsed_resume or {}
    candidates: list[tuple[str, str, set[str]]] = []
    raw_labels: list[str] = []

    for project in parsed_resume.get("projects", []):
        if isinstance(project, dict) and project.get("name"):
            raw_labels.append(str(project["name"]))
    for exp in parsed_resume.get("experiences", []):
        if not isinstance(exp, dict):
            continue
        for value in (exp.get("company"), exp.get("title")):
            if value:
                raw_labels.append(str(value))
    for claim in parsed_resume.get("claims", []):
        if isinstance(claim, dict):
            for value in (claim.get("project"), claim.get("text")):
                if value:
                    raw_labels.append(str(value))

    if not raw_labels:
        for line in resume.splitlines():
            stripped = line.strip()
            if "@" in stripped or "intern" in stripped.lower() or "research assistant" in stripped.lower():
                raw_labels.append(stripped.split("@")[0].strip(" :-"))

    seen: set[str] = set()
    for label in raw_labels:
        key = _focus_key(label)
        if not key or key in seen:
            continue
        tokens = {
            token
            for token in _normalize_transcript(label).split(" ")
            if len(token) > 2 and token not in {"project", "engineer", "assistant", "intern"}
        }
        if not tokens:
            continue
        candidates.append((label[:80], key, tokens))
        seen.add(key)
    return candidates


def _infer_focus(question: str, answer: str, parsed_resume: dict | None, resume: str) -> tuple[str, str]:
    combined = _normalize_transcript(f"{question} {answer}")
    combined_tokens = set(token for token in combined.split(" ") if len(token) > 2)

    best_label = ""
    best_key = ""
    best_score = 0
    for label, key, tokens in _resume_focus_candidates(parsed_resume, resume):
        score = len(tokens & combined_tokens)
        if score > best_score:
            best_score = score
            best_label = label
            best_key = key

    if best_score > 0:
        return best_key, best_label

    if "internship" in combined or "resume" in combined:
        return "resume_background", "resume/background"
    if "python" in combined or "c++" in combined:
        return "python_cpp", "Python/C++"
    if "system" in combined or "scale" in combined or "load" in combined:
        return "system_design", "system design"
    if "concept" in combined or "explain" in combined:
        return "foundations", "foundations"
    return "general", "general background"


def _is_substantive_answer(text: str) -> bool:
    cleaned = _normalize_transcript(text)
    if not cleaned or _looks_like_admission(text):
        return False
    words = [word for word in cleaned.split(" ") if word]
    return len(words) >= 18


def _collect_overprobed_topics(history: list[dict], current_focus_label: str = "") -> list[str]:
    counts: dict[str, int] = {}
    for turn in history:
        label = turn.get("focus_label") or ""
        if label:
            counts[label] = counts.get(label, 0) + 1
    if current_focus_label:
        counts[current_focus_label] = counts.get(current_focus_label, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [label for label, count in ranked if count >= 2][:3]


def _build_continuity_brief(
    history: list[dict],
    candidate_model: dict,
    current_question: str = "",
    current_answer: str = "",
    current_focus_label: str = "",
) -> str:
    lines: list[str] = []

    substantive_turns = [turn for turn in history if _is_substantive_answer(turn.get("answer", ""))]
    if substantive_turns:
        turn = substantive_turns[-1]
        lines.append(
            f"Last substantive thread: {turn.get('question', '')[:110]} -> {turn.get('answer', '')[:180]}"
        )

    if current_question and current_answer and _is_substantive_answer(current_answer):
        lines.append(f"Most recent answer to build from: {current_question[:110]} -> {current_answer[:180]}")

    established = candidate_model.get("established_facts", []) if isinstance(candidate_model, dict) else []
    if established:
        lines.append("Established facts: " + "; ".join(established[-2:]))

    if current_focus_label and current_focus_label != "general background":
        lines.append(f"Current thread label: {current_focus_label}")

    return "\n".join(f"- {line}" for line in lines if line)


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
        self._speculative_locks: dict[str, asyncio.Lock] = {}

    # ─────────────────────────────────────────────
    # SESSION LIFECYCLE
    # ─────────────────────────────────────────────

    async def start_session(
        self,
        resume: str,
        github_links: list[str],
        target_role: str = "",
        years_experience: str = "",
    ) -> str:
        session_id = str(uuid.uuid4())

        parsed_resume = await self.resume_agent.parse(
            resume,
            target_role=target_role,
            years_experience=years_experience,
        )
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
            "target_role": target_role,
            "years_experience": years_experience,
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
            # prepped_turn_queue      — ordered queue of completed background analyses
            #                           (each item contains analysis + metadata + turn_number)
            #                           consumed on later real turns / session end
            # prepped_next_context    — metadata attached to prepped_next_question
            "prepped_next_question": None,
            "prepped_next_question_turn_number": 0,
            "prepped_next_context": {},
            "prepped_turn_queue": [],
            # ── Speculative cache — partial-STT driven, Haiku only ────────────
            # Written ONLY by _run_speculative_generation (event-driven on partials).
            # Consumed in the fast path if no canonical prepped_next_question exists.
            # NEVER writes canonical state (Codex invariant extends here too).
            "speculative_cache": {},
            # Tracks the most recent candidate answer turn currently being resolved.
            # If the frontend submits another chunk with the same turn_id before the
            # AI has truly moved on, we treat it as a same-turn revision, not a
            # brand-new interview turn.
            "current_answer_turn_id": "",
            "current_answer_question": "",
            "current_answer_response": "",
            "current_answer_context": {},
            "current_answer_turn_number": 0,
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
        queue = state.pop("prepped_turn_queue", [])
        legacy_staged = state.pop("prepped_turn_analysis", None)
        legacy_metadata = state.pop("prepped_next_metadata", {})
        if legacy_staged and legacy_staged.get("session_id") == session_id:
            queue.append({
                "turn_id": legacy_staged.get("turn_id", ""),
                "turn_number": legacy_staged.get("turn_number", state.get("question_count", 0)),
                "analysis": legacy_staged,
                "metadata": legacy_metadata,
            })
        for item in sorted(queue, key=lambda queued: queued.get("turn_number", 0)):
            analysis = item.get("analysis", {})
            if analysis.get("session_id") == session_id:
                self._apply_staged_analysis(state, analysis, item.get("metadata", {}))
        state.pop("prepped_next_question", None)
        state.pop("prepped_next_question_turn_number", None)
        state.pop("prepped_next_context", None)
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
                target_role=state.get("target_role", ""),
                years_experience=state.get("years_experience", ""),
                parsed_resume=state.get("parsed_resume", {}),
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

    async def _score_answer_async(
        self,
        session_id: str,
        question: str,
        answer: str,
        target_role: str = "",
        years_experience: str = "",
    ):
        """Per-answer scoring — fired from background pipeline, never blocks response path."""
        try:
            score = await self.evaluation_agent.score_answer(
                question,
                answer,
                target_role=target_role,
                years_experience=years_experience,
            )
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

    async def on_partial_transcript(
        self,
        session_id: str,
        text: str,
        entities: list[str] | None = None,
        turn_id: str = "",
    ):
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
                        turn_id=turn_id,
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
                    turn_id=turn_id,
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

        is_turn_revision = bool(turn_id and turn_id == state.get("current_answer_turn_id"))

        # Merge entities from partial accumulation
        accumulated = self._partial_entities.pop(session_id, set())
        if entities:
            accumulated.update(entities)
        entities = list(accumulated) if accumulated else entities

        last_question = (
            state.get("current_answer_question", "")
            if is_turn_revision and state.get("current_answer_question")
            else state.get("last_question", "")
        )
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
        queue = state.pop("prepped_turn_queue", [])
        legacy_staged = state.pop("prepped_turn_analysis", None)
        legacy_metadata = state.pop("prepped_next_metadata", {})
        if legacy_staged and legacy_staged.get("session_id") == session_id:
            queue.append({
                "turn_id": legacy_staged.get("turn_id", ""),
                "turn_number": legacy_staged.get("turn_number", state.get("question_count", 0)),
                "analysis": legacy_staged,
                "metadata": legacy_metadata,
            })

        ready_items: list[dict] = []
        deferred_items: list[dict] = []
        for item in queue:
            if turn_id and item.get("turn_id") == turn_id:
                deferred_items.append(item)
            else:
                ready_items.append(item)

        for item in sorted(ready_items, key=lambda queued: queued.get("turn_number", 0)):
            analysis = item.get("analysis", {})
            if analysis.get("session_id") == session_id:
                self._apply_staged_analysis(state, analysis, item.get("metadata", {}))
        if deferred_items:
            state["prepped_turn_queue"] = deferred_items

        # ── Step 2: Determine fast response ──────────────────────────────────
        # Priority:
        # a) prepped_next_question — adversarial probe from canonical bg pipeline (instant)
        # b) speculative_cache — entity/admission-triggered Haiku question from partials (instant)
        # c) bank follow-up adapted via adapt_followup Haiku call (~300ms)
        # d) sprint fallback template (instant, no LLM)
        prepped_q = None
        prepped_context: dict = {}
        if is_turn_revision:
            prepped_q = state.get("current_answer_response")
            prepped_context = state.get("current_answer_context", {})
        else:
            prepped_q = state.pop("prepped_next_question", None)
            prepped_context = state.pop("prepped_next_context", {})
            state.pop("prepped_next_question_turn_number", None)

        pivoting = prepped_context.get("pivoting", False)

        spec = state.get("speculative_cache", {})
        if spec.get("turn_id") and spec.get("turn_id") != turn_id:
            state["speculative_cache"] = {}
            spec = {}

        # Promote speculative candidate if no canonical probe and both sprint and turn still match
        if not prepped_q:
            if (
                spec.get("best_ready_question")
                and spec.get("sprint") == sprint
                and spec.get("turn_id") == turn_id
            ):
                prepped_q = spec["best_ready_question"]
                state["speculative_cache"] = {}  # consume and clear
                print(f"[FastTrack] Speculative candidate promoted for {session_id}")

        if prepped_q:
            fast_response = prepped_q
            served_weakness = prepped_context.get("weakness")
            served_discrepancy = prepped_context.get("discrepancy")
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
            served_discrepancy = None
            print(f"[FastTrack] Bank follow-up adapted for {session_id}")

        else:
            # No bank follow-up queued and no prepped question — use sprint fallback
            # Should be rare once the background pipeline is running steadily
            fallbacks = _FALLBACK_FOLLOWUPS.get(sprint, ["Walk me through your thinking on that."])
            fast_response = fallbacks[0]
            served_weakness = None
            served_discrepancy = None
            print(f"[FastTrack] Sprint fallback served for {session_id}")

        # ── Step 3: Update canonical state ───────────────────────────────────
        # Only counters and current question. History/weaknesses/candidate_model
        # are updated when staged analysis is consumed (Step 1).
        current_turn_number = state.get("current_answer_turn_number", state.get("question_count", 0))
        if not is_turn_revision:
            state["question_count"] = state.get("question_count", 0) + 1
            state["sprint_question_count"] = state.get("sprint_question_count", 0) + 1
            state["last_question"] = fast_response
            current_turn_number = state["question_count"]

            advanced, sprint_opener = await self._maybe_advance_sprint(
                state,
                answered_question=last_question,
                current_answer=text,
            )
            if advanced:
                fast_response = sprint_opener
                state["last_question"] = fast_response
        else:
            state["last_question"] = fast_response

        state["current_answer_turn_id"] = turn_id
        state["current_answer_question"] = last_question
        state["current_answer_response"] = fast_response
        state["current_answer_context"] = {
            "pivoting": pivoting,
            "weakness": served_weakness,
            "discrepancy": served_discrepancy,
        }
        state["current_answer_turn_number"] = current_turn_number

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
                turn_number=current_turn_number,
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
            "discrepancy": served_discrepancy,
            "turn_id": turn_id,
        }

    def _apply_staged_analysis(self, state: dict, staged: dict, metadata: dict) -> None:
        """
        Apply a background pipeline's analysis to canonical session state.
        Called ONLY at the start of handle_transcript — never inside the background pipeline.

        Updates: history, weaknesses, candidate_model, consecutive weakness guard,
                 follow-up sequencing state.
        """
        history = state.setdefault("history", [])
        existing_turn_id = staged.get("turn_id")
        if existing_turn_id and any(h.get("turn_id") == existing_turn_id for h in history):
            return

        # Append turn record to history
        history.append({
            "turn_id": existing_turn_id,
            "question": staged.get("question", ""),
            "answer": staged.get("answer", ""),
            "weakness": staged.get("weakness"),
            "concepts": staged.get("concepts", []),
            "discrepancy": staged.get("discrepancy"),
            "reasoning_behavior": staged.get("reasoning_behavior"),
            "sprint": staged.get("sprint", state.get("current_sprint", 1)),
            "persona": staged.get("persona", state.get("current_persona", "curious_lead")),
            "focus_key": staged.get("focus_key", ""),
            "focus_label": staged.get("focus_label", ""),
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
        turn_number: int,
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
            target_role = state.get("target_role", "")
            years_experience = state.get("years_experience", "")
            prior_weaknesses = state.get("weaknesses", [])
            candidate_model = state.get("candidate_model", {"project_map": {}, "established_facts": [], "probed_weaknesses": []})
            was_challenged = bool(prior_weaknesses and prior_weaknesses[-1].get("severity") == "high")
            history = state.get("history", [])

            # Memory context for agents — what's been established and probed so far
            established_facts = candidate_model.get("established_facts", [])
            probed_weaknesses_list = candidate_model.get("probed_weaknesses", [])
            memory_context = ""
            if established_facts:
                memory_context += "Already established as true:\n" + "\n".join(f"- {f}" for f in established_facts[-4:]) + "\n"
            if probed_weaknesses_list:
                memory_context += "Already probed (avoid repeating):\n" + "\n".join(f"- {p}" for p in probed_weaknesses_list[-4:]) + "\n"
            if history:
                prior_claims = [
                    f"- Q: {h.get('question', '')[:90]} | A: {h.get('answer', '')[:160]}"
                    for h in history[-3:]
                    if h.get("answer")
                ]
                if prior_claims:
                    memory_context += "Candidate claims from prior turns:\n" + "\n".join(prior_claims)

            # ── Parallel agent execution ──────────────────────────────────────
            async def _safe_weakness():
                try:
                    return await self.weakness_agent.detect(
                        last_question, text, sprint=sprint,
                        prior_weaknesses=prior_weaknesses,
                        memory_context=memory_context,
                        parsed_resume=parsed_resume,
                        target_role=target_role,
                        years_experience=years_experience,
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
            asyncio.create_task(
                self._score_answer_async(
                    session_id,
                    last_question,
                    text,
                    target_role=target_role,
                    years_experience=years_experience,
                )
            )

            # ── Honest admission soft-cap ─────────────────────────────────────
            reasoning_adaptability = reasoning.get("adaptability", "") if isinstance(reasoning, dict) else ""
            honest_admission = reasoning_adaptability == "admitted_gap"
            if honest_admission and weakness.get("severity") == "high":
                weakness = {**weakness, "severity": "medium"}

            current_focus_key, current_focus_label = _infer_focus(
                last_question,
                text,
                parsed_resume,
                resume,
            )
            same_focus_history = [
                turn for turn in history
                if turn.get("focus_key") == current_focus_key
            ]
            same_focus_recent = sum(
                1 for turn in history[-3:]
                if turn.get("focus_key") == current_focus_key
            )
            same_focus_confirmed = sum(
                1
                for turn in same_focus_history
                if isinstance(turn.get("discrepancy"), dict)
                and turn["discrepancy"].get("conflict_level") == "confirmed"
            )
            same_focus_deflections = sum(
                1
                for turn in same_focus_history
                if isinstance(turn.get("weakness"), dict)
                and turn["weakness"].get("type") == "deflection"
            )
            substantive_recovery = _is_substantive_answer(text) and weakness.get("type") != "deflection"
            continuity_brief = _build_continuity_brief(
                history=history,
                candidate_model=candidate_model,
                current_question=last_question,
                current_answer=text,
                current_focus_label=current_focus_label,
            )
            overprobed_topics = _collect_overprobed_topics(history, current_focus_label=current_focus_label)

            # ── Breadth guard ────────────────────────────────────────────────
            # Preserve coverage by avoiding too many turns on the same weakness family
            # unless we have a confirmed contradiction worth pressing further.
            weakness_type = weakness.get("type") if isinstance(weakness, dict) else None
            recent_same_focus = 0
            if weakness_type:
                for prior in prior_weaknesses[-3:]:
                    if prior.get("type") == weakness_type:
                        recent_same_focus += 1

            # ── Consecutive weakness guardrail ────────────────────────────────
            wtype = weakness_type
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
                and discrepancy.get("conflict_level") == "confirmed"
                and discrepancy.get("severity") in ("medium", "high")
            )
            repeated_focus = recent_same_focus >= 2 and not discrepancy_conflict
            contradiction_budget_exhausted = discrepancy_conflict and same_focus_confirmed >= 2 and not substantive_recovery
            deflection_budget_exhausted = weakness_type == "deflection" and same_focus_deflections >= 2
            if repeated_focus or contradiction_budget_exhausted or deflection_budget_exhausted:
                force_sprint_question = True
                pivoting = True
            clarification_probe = (
                isinstance(weakness, dict)
                and weakness.get("attack_strategy") in ("clarification", "ownership_probe")
                and weakness.get("severity") in ("medium", "high")
            )
            resume_context = _build_resume_context_for_followup(parsed_resume, resume)
            seed_followups: list[str] = []

            if discrepancy_conflict and not force_sprint_question:
                next_question = await self.followup_agent.generate_discrepancy_challenge(
                    question=last_question, answer=text, discrepancy=discrepancy,
                    persona=persona, resume=resume, parsed_resume=parsed_resume,
                )

            elif (weakness.get("severity") == "high" or clarification_probe) and not force_sprint_question:
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
                    history=history,
                    weakness=weakness,
                    transition_brief=continuity_brief,
                    avoid_topics=overprobed_topics,
                )
                next_question, seed_followups = sprint_result

            # ── Candidate model updates (no LLM call) ────────────────────────
            candidate_model_updates: dict[str, list] = {"established_facts": [], "probed_weaknesses": []}

            if isinstance(discrepancy, dict) and discrepancy.get("conflict_level") == "none" and discrepancy.get("description"):
                fact = discrepancy["description"][:120].rstrip(".") + f" (confirmed Turn {turn_number})"
                if fact not in candidate_model.get("established_facts", []):
                    candidate_model_updates["established_facts"].append(fact)

            if weakness and weakness.get("type") and weakness.get("weakness"):
                probe_note = f"{weakness['type']}: {weakness['weakness'][:80]} (Turn {turn_number})"
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

            queue = [
                item
                for item in state.get("prepped_turn_queue", [])
                if item.get("turn_id") != turn_id
            ]
            queue.append({
                "turn_id": turn_id,
                "turn_number": turn_number,
                "analysis": {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "turn_number": turn_number,
                    "question": last_question,
                    "answer": text,
                    "weakness": weakness,
                    "concepts": concepts,
                    "discrepancy": discrepancy,
                    "reasoning_behavior": reasoning,
                    "sprint": sprint,
                    "persona": persona,
                    "focus_key": current_focus_key,
                    "focus_label": current_focus_label,
                    "candidate_model_updates": candidate_model_updates,
                },
                "metadata": {
                    "pivoting": pivoting,
                    "consecutive_high_weakness_count": new_consecutive,
                    "last_weakness_type": wtype,
                    "current_question_followups": followups_to_store,
                    "current_question_followup_asked": False,
                },
            })
            state["prepped_turn_queue"] = queue

            if turn_number >= state.get("prepped_next_question_turn_number", 0):
                state["prepped_next_question"] = next_question
                state["prepped_next_question_turn_number"] = turn_number
                state["prepped_next_context"] = {
                    "pivoting": pivoting,
                    "weakness": weakness,
                    "discrepancy": discrepancy,
                    "turn_id": turn_id,
                }
            state["prepped_turn_analysis"] = {
                "session_id": session_id,
                "turn_id": turn_id,
                "turn_number": turn_number,
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
            print(f"[BGPipeline] Turn {turn_number} complete — adversarial probe staged for {session_id}")

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
            if (
                state.get("interview_complete")
                or state.get("prepped_next_question")
                or state.get("question_count", 0) > 0
                or state.get("current_sprint", 1) != 1
                or state.get("last_question") != SPRINT_OPENERS[1]
            ):
                return
            state["prepped_next_question"] = question
            state["prepped_next_question_turn_number"] = 0
            state["prepped_next_context"] = {
                "pivoting": False,
                "weakness": None,
                "discrepancy": None,
                "turn_id": "",
            }
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
        turn_id: str = "",
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
            if not turn_id:
                return

            lock = self._speculative_locks.setdefault(session_id, asyncio.Lock())
            async with lock:
                state = await self.session_manager.get_state(session_id)
                if state.get("interview_complete"):
                    return

                sprint = state.get("current_sprint", 1)
                persona = state.get("current_persona", "curious_lead")
                resume_context = _build_resume_context_for_followup(
                    state.get("parsed_resume"), state.get("resume", "")
                )
                cache = state.get("speculative_cache", {})
                now = time.time()

                if cache.get("turn_id") and cache.get("turn_id") != turn_id:
                    cache = {}

                if cache.get("inflight") and cache.get("turn_id") == turn_id:
                    return

                if now - cache.get("last_trigger_time", 0.0) < 1.0:
                    return

                version = cache.get("speculation_version", 0) + 1
                state["speculative_cache"] = {
                    **cache,
                    "turn_id": turn_id,
                    "sprint": sprint,
                    "speculation_version": version,
                    "last_trigger_time": now,
                    "inflight": True,
                }
                await self.session_manager.save_state(session_id, state)

            question = await self.followup_agent.generate_speculative(
                partial_text=partial_text,
                new_entities=list(new_entities),
                last_question=state.get("last_question", ""),
                persona=persona,
                sprint=sprint,
                resume_context=resume_context,
                admission=admission,
            )

            # Re-read under the same session lock — only write if still the same active answer turn
            async with lock:
                state = await self.session_manager.get_state(session_id)
                if state.get("interview_complete"):
                    return
                cache = state.get("speculative_cache", {})
                if state.get("current_sprint", 1) != sprint:
                    return  # Sprint advanced while we were generating — discard
                if cache.get("turn_id") != turn_id:
                    return
                if cache.get("speculation_version") != version:
                    return
                if not cache.get("inflight"):
                    return

                state["speculative_cache"] = {
                    **cache,
                    "best_ready_question": question,
                    "inflight": False,
                }
                await self.session_manager.save_state(session_id, state)
            trigger = "admission" if admission else f"entities: {new_entities}"
            print(f"[Speculative] v{version} staged ({trigger}) for {session_id}")

        except Exception as e:
            print(f"[Speculative] Failed for {session_id}: {e}")

    # ─────────────────────────────────────────────
    # SPRINT LOGIC
    # ─────────────────────────────────────────────

    async def _maybe_advance_sprint(
        self,
        state: dict,
        answered_question: str = "",
        current_answer: str = "",
    ) -> tuple[bool, str]:
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
        if current_answer and answered_question:
            answered_focus_key, answered_focus_label = _infer_focus(
                answered_question,
                current_answer,
                state.get("parsed_resume"),
                state.get("resume", ""),
            )
            prior_sprint_history = prior_sprint_history + [{
                "question": answered_question,
                "answer": current_answer,
                "sprint": prior_sprint,
                "focus_key": answered_focus_key,
                "focus_label": answered_focus_label,
            }]

        continuity_brief = _build_continuity_brief(
            history=prior_sprint_history,
            candidate_model=state.get("candidate_model", {}),
            current_question=answered_question,
            current_answer=current_answer,
        )
        avoid_topics = _collect_overprobed_topics(prior_sprint_history)

        try:
            opener = await self.followup_agent.generate_sprint_opener(
                sprint=next_sprint,
                persona=next_persona,
                resume=state.get("resume", ""),
                parsed_resume=state.get("parsed_resume"),
                prior_sprint_history=prior_sprint_history,
                transition_brief=continuity_brief,
                avoid_topics=avoid_topics,
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
