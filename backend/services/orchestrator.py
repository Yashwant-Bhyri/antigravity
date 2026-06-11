import asyncio
import os
import re
import time
import uuid
from backend.db.postgres import persist_session
from backend.services.provenhire_handoff import notify_handoff_complete, notify_handoff_failed
from backend.agents.concept_agent import ConceptAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.evaluation_agent import EvaluationAgent
from backend.agents.resume_agent import ResumeAgent
from backend.agents.reasoning_behavior_agent import ReasoningBehaviorAgent
from backend.agents.policy_checker_agent import PolicyCheckerAgent
from backend.services.interview_map import (
    _MAP_MIN_FOCUS_AREAS as MAP_STARTUP_FOCUS_AREAS,
    _track_candidate_q4_options,
    _track_dimensions,
    _track_opener,
    _track_recovery,
    MapPreparationError,
    generate_interview_map,
    get_focus_area_context,
    hydrate_interview_map_tracks,
    select_from_trajectory_map,
    select_from_trajectory_map_detailed,
    validate_interview_map,
)
from backend.services.interview_telemetry import interview_telemetry
from backend.services.question_quality import check_question_readiness
from backend.state.interview_agenda import (
    FOCUS_RATIO_CAP,
    FOCUS_RATIO_MIN_EVIDENCE_TURNS,
    FOCUS_STREAK_CAP,
    MAX_COVERAGE_OPENINGS,
    MIN_COVERAGE_OPENINGS_BEFORE_STREAK_PIVOT,
    MIN_COMPLETION_TURNS,
    PRIMARY_FOCUS_MIN_EVIDENCE_TURNS,
    anchor_surface_candidates,
    distinct_substantive_focus_count,
    distinct_substantive_surface_count,
    dominant_focus_ratio,
    ensure_interview_agenda,
    focus_label as agenda_focus_label,
    initial_interview_agenda,
    least_used_focus,
    max_same_focus_streak,
    max_same_surface_streak,
    next_secondary_surface,
    surfaces_by_focus,
    weighted_surface_coverage,
)
from backend.state.candidate_state import detect_communication_mode
from backend.state.session_manager import SessionManager


def _build_resume_context_for_followup(parsed_resume: dict | None, resume: str) -> str:
    """Thin wrapper so orchestrator can call the shared helper without circular imports."""
    return _build_resume_context(parsed_resume, resume)


def _build_focus_prompt_pack(
    interview_map: dict,
    *,
    focus_key: str,
    last_question: str = "",
    answer: str = "",
    history: list[dict] | None = None,
) -> dict:
    area = get_focus_area_context(
        interview_map,
        focus_key=focus_key,
        query_text=f"{last_question} {answer}",
        history=history or [],
        limit=3,
    )
    if not area:
        return {
            "focus_key": focus_key,
            "focus_label": "",
            "resume_snippets": [],
            "prompt_context": "",
        }
    return area


_ADMISSION_SIGNALS = re.compile(
    r"\b(i don'?t know|i'?m not sure|i didn'?t (write|build|implement|code)|"
    r"to be honest|actually i|i should (mention|clarify|be honest)|"
    r"i'?m not (certain|familiar|sure)|i haven'?t|i can'?t (explain|tell)|"
    r"i was just|i only|it'?s basically|it'?s just|i mean it'?s not really|"
    r"i don'?t (really|actually) know|"
    # ownership-gap patterns
    r"my (teammate|team member|colleague|manager|lead) (did|handled|wrote|built|implemented|owned)|"
    r"(someone else|another (engineer|person|team)) (did|handled|wrote|built)|"
    r"i (joined|came in|came on) (after|later|once)|"
    r"i (wasn'?t|was not) (involved|part of|around)|"
    r"i (didn'?t really|don'?t really) (understand|know|get)|"
    r"(we had|there was) a (library|framework|tool|service) (that|which) (handled|did|took care)|"
    r"i (mostly|mainly|primarily|just) (used|called|integrated)|"
    r"it was (already|pre-?built|set up) (before|when) i"
    r")\b",
    re.IGNORECASE,
)


_SKIP_SIGNALS = re.compile(
    r"\b(skip (this|that|it|the question)|move on|next question|can we move on|"
    r"let'?s move on|let'?s skip|can you skip|pass on this|i'?d rather (not|skip)|"
    r"next (please|topic)|different question|different topic|another topic|something else|"
    r"move to something|change (the )?topic|switch topics|change the subject)\b",
    re.IGNORECASE,
)

_SOCIAL_DEFLECTION_SIGNALS = re.compile(
    r"\b(that'?s a great question|interesting question|good question|"
    r"wow (that'?s|what a)|i appreciate (you asking|the question)|"
    r"i'?m good|i'?m okay|i'?m fine|don'?t worry|no no no|thank you i'?m good|"
    r"good without answering|i'?m good without answering|never mind|that'?s fine)\b",
    re.IGNORECASE,
)


def _looks_like_skip_request(text: str) -> bool:
    """Detect explicit skip/move-on signals — forces immediate focus rotation."""
    return bool(_SKIP_SIGNALS.search(text))


def _looks_like_admission(text: str) -> bool:
    """Detect honesty/gap signals in partial transcript — triggers speculative pivot."""
    return bool(_ADMISSION_SIGNALS.search(text))


def _detect_communication_mode(turn0_text: str, turn1_text: str) -> str:
    """Run on first two answers. Returns communication_mode: 'normal' | 'simplified' | 'narrative_only'."""
    return detect_communication_mode(turn0_text, turn1_text)


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


def _classify_anchor_confidence(anchor: str, phase2_text: str) -> str:
    """
    Classify implementation anchor quality from first-person markers.
    high: first-person + specific artifact
    medium: correct vocabulary but no specific artifact
    low: system-language or generic
    """
    anchor_lower = anchor.lower()
    first_person = ("i wrote", "i built", "i had to", "i figured", "i implemented", "i designed")
    if any(m in anchor_lower for m in first_person):
        return "high"
    generic = ("we handled", "it was", "the system", "we made sure", "was handled")
    if any(m in anchor_lower for m in generic):
        return "low"
    return "medium"


def _focus_key(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return key or "general"


def _resume_focus_candidates(parsed_resume: dict | None, resume: str) -> list[tuple[str, str, set[str]]]:
    parsed_resume = parsed_resume or {}
    candidates: list[tuple[str, str, set[str]]] = []
    token_stopwords = {
        "project", "projects", "engineer", "engineering", "assistant", "intern",
        "built", "build", "using", "with", "present", "current", "custom",
        "production", "ready", "system", "experience", "worked",
        "for", "from", "into", "onto", "over", "under", "about", "after",
        "before", "during", "when", "while", "that", "this", "these", "those",
        "just", "than", "then", "them", "they", "their", "your", "what",
        "which", "where", "would", "could", "should", "have", "had",
        "into", "across", "through",
    }
    candidate_map: dict[str, dict] = {}

    def _tokens_from(*sources: object) -> set[str]:
        tokens: set[str] = set()
        for source in sources:
            normalized = _normalize_transcript(str(source or ""))
            for token in normalized.split(" "):
                if len(token) <= 2 or token in token_stopwords:
                    continue
                tokens.add(token)
        return tokens

    def _ensure_candidate(label: str, *sources: object) -> None:
        clean_label = str(label or "").strip()
        key = _focus_key(clean_label)
        if not clean_label or not key:
            return
        entry = candidate_map.setdefault(key, {"label": clean_label[:80], "tokens": set()})
        entry["tokens"].update(_tokens_from(clean_label, *sources))

    claims_by_project: dict[str, list[str]] = {}
    for claim in parsed_resume.get("claims", []):
        if not isinstance(claim, dict):
            continue
        project = str(claim.get("project", "") or "").strip()
        text = str(claim.get("text", "") or "").strip()
        if project and text:
            claims_by_project.setdefault(project.lower(), []).append(text)

    for project in parsed_resume.get("projects", []):
        if not isinstance(project, dict):
            continue
        name = str(project.get("name", "") or "").strip()
        if not name:
            continue
        project_claims = claims_by_project.get(name.lower(), [])
        _ensure_candidate(
            name,
            project.get("description", ""),
            " ".join(project.get("technologies", []) or []),
            " ".join(project_claims),
        )

    for exp in parsed_resume.get("experiences", []):
        if not isinstance(exp, dict):
            continue
        company = str(exp.get("company", "") or "").strip()
        title = str(exp.get("title", "") or "").strip()
        if company and title:
            label = f"{title} at {company}"
        else:
            label = company or title
        if not label:
            continue
        _ensure_candidate(
            label,
            exp.get("description", ""),
            exp.get("duration", ""),
            title,
            company,
        )

    if not candidate_map:
        for line in resume.splitlines():
            stripped = line.strip()
            if "@" in stripped or "intern" in stripped.lower() or "research assistant" in stripped.lower():
                label = stripped.split("@")[0].strip(" :-")
                _ensure_candidate(label, stripped)

    for key, entry in candidate_map.items():
        tokens = entry["tokens"]
        if not tokens:
            continue
        candidates.append((entry["label"], key, tokens))
    return candidates


def _infer_focus(
    question: str,
    answer: str,
    parsed_resume: dict | None,
    resume: str,
    trajectory_focus_areas: list[dict] | None = None,
) -> tuple[str, str]:
    combined = _normalize_transcript(f"{question} {answer}")
    combined_tokens = set(token for token in combined.split(" ") if len(token) > 2)

    def _area_focus_text(area: dict) -> str:
        sub_focus_parts: list[str] = []
        for item in area.get("sub_focuses") or []:
            if isinstance(item, dict):
                sub_focus_parts.extend(
                    str(item.get(key) or "")
                    for key in (
                        "label",
                        "sub_focus_key",
                        "why_priority",
                        "role_relevance_weight",
                        "profile_importance_weight",
                        "evidence_strength",
                        "claim_risk",
                        "coverage_value",
                    )
                )
                sub_focus_parts.extend(str(s or "") for s in (item.get("source_snippets") or []))
            else:
                sub_focus_parts.append(str(item or ""))
        parts: list[str] = [
            str(area.get("label") or ""),
            str(area.get("focus_key") or "").replace("_", " "),
            str(area.get("anchor_context") or ""),
            str(area.get("why_priority") or ""),
            _track_opener(area),
            " ".join(sub_focus_parts),
            " ".join(str(item) for item in (area.get("resume_snippets") or []) if item),
            " ".join(_track_candidate_q4_options(area)),
        ]
        for item in area.get("question_ladder") or []:
            if isinstance(item, dict):
                parts.extend(
                    str(item.get(key) or "")
                    for key in ("posture", "main_question", "signal_goal", "expected_space")
                )
        for dim in _track_dimensions(area):
            if not isinstance(dim, dict):
                continue
            parts.extend(
                str(dim.get(key) or "")
                for key in (
                    "id",
                    "label",
                    "description",
                    "resume_anchor",
                    "surface",
                    "mechanism",
                    "boundary",
                )
            )
        recovery = _track_recovery(area)
        parts.extend(str(value or "") for value in recovery.values())
        return " ".join(parts)

    # Prefer trajectory map focus areas when available — they are already semantically
    # named and avoid location-name false positives from raw resume parsing.
    if trajectory_focus_areas:
        best_label = ""
        best_key = ""
        best_score = 0
        for area in trajectory_focus_areas:
            fa_label = str(area.get("label") or "")
            fa_key = str(area.get("focus_key") or "")
            if not fa_key:
                continue
            area_tokens = set(
                t for t in _normalize_transcript(_area_focus_text(area)).split(" ")
                if len(t) > 2
            )
            score = len(area_tokens & combined_tokens)
            if score > best_score:
                best_score = score
                best_label = fa_label
                best_key = fa_key
        if best_score > 0:
            return best_key, best_label

    return "general", "general background"


def _sub_focus_key(label: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (label or "").lower())
        if len(token) > 2
    ]
    return "_".join(tokens[:8])


def _infer_sub_focus(
    interview_map: dict | None,
    focus_key: str,
    question: str,
    answer: str = "",
) -> tuple[str, str]:
    focus_key = str(focus_key or "").strip()
    if not focus_key or focus_key in {"general", "general_background", "general background"}:
        return "", ""

    combined = _normalize_transcript(f"{question} {answer}")
    combined_tokens = set(token for token in combined.split(" ") if len(token) > 2)
    if not combined_tokens:
        return "", ""

    focus_areas = ((interview_map or {}).get("focus_areas") or []) if isinstance(interview_map, dict) else []
    area = next(
        (
            candidate for candidate in focus_areas
            if isinstance(candidate, dict)
            and str(candidate.get("focus_key") or "").strip() == focus_key
        ),
        None,
    )
    if not isinstance(area, dict):
        return "", ""

    candidates: list[dict[str, str]] = []
    for sub_focus in area.get("sub_focuses") or []:
        if isinstance(sub_focus, dict):
            label = str(
                sub_focus.get("label")
                or sub_focus.get("name")
                or sub_focus.get("surface")
                or sub_focus.get("sub_focus")
                or sub_focus.get("sub_focus_label")
                or sub_focus.get("sub_focus_key")
                or ""
            ).strip()
            key = str(sub_focus.get("sub_focus_key") or sub_focus.get("key") or sub_focus.get("id") or "").strip()
            text = " ".join(
                [
                    label,
                    key.replace("_", " "),
                    str(sub_focus.get("why_priority") or ""),
                    str(sub_focus.get("role_relevance_weight") or ""),
                    str(sub_focus.get("profile_importance_weight") or ""),
                    str(sub_focus.get("evidence_strength") or ""),
                    str(sub_focus.get("claim_risk") or ""),
                    str(sub_focus.get("coverage_value") or ""),
                    " ".join(str(s or "") for s in (sub_focus.get("source_snippets") or [])),
                ]
            )
        else:
            label = str(sub_focus or "").strip()
            key = ""
            text = label
        key = key or _sub_focus_key(label)
        if label and key:
            candidates.append({"key": key, "label": label, "text": text})

    if not candidates:
        for dim in _track_dimensions(area):
            if not isinstance(dim, dict):
                continue
            label = str(dim.get("label") or dim.get("id") or "").strip()
            key = _sub_focus_key(label or str(dim.get("id") or ""))
            text = " ".join(
                str(dim.get(field) or "")
                for field in ("id", "label", "description", "resume_anchor", "surface", "mechanism", "boundary")
            )
            if label and key:
                candidates.append({"key": key, "label": label, "text": text})

    if not candidates:
        return "", ""

    best: dict[str, str] | None = None
    best_score = 0.0
    for candidate in candidates:
        candidate_tokens = set(
            token for token in _normalize_transcript(candidate.get("text", "")).split(" ")
            if len(token) > 2
        )
        if not candidate_tokens:
            continue
        overlap = len(candidate_tokens & combined_tokens)
        density = overlap / max(len(candidate_tokens), 1)
        exact_bonus = 1.5 if candidate["label"].lower() in f"{question} {answer}".lower() else 0.0
        score = overlap + density + exact_bonus
        if score > best_score:
            best = candidate
            best_score = score

    if best and best_score > 0:
        return best["key"], best["label"]
    if len(candidates) == 1:
        only = candidates[0]
        return only["key"], only["label"]
    return "", ""


def _seed_relevant_to_answer(
    seeded_question: str,
    answer: str,
    entities: list[str],
    parsed_resume: dict | None,
    resume: str,
) -> bool:
    """
    Returns True if a pre-seeded question (generated from resume before any candidate answer)
    is topically aligned with what the candidate actually talked about in their first answer.

    The seed is generated from resume alone and defaults to the most prominent claim.
    If the candidate's first answer introduces a different project or topic, the seed
    will steer Turn 2 into an irrelevant lane — this check prevents that.
    """
    answer_focus_key, _ = _infer_focus("", answer, parsed_resume, resume)
    if answer_focus_key in ("general", "general background"):
        return True  # Can't determine focus — keep seed

    q_focus_key, _ = _infer_focus(seeded_question, "", parsed_resume, resume)
    if q_focus_key == answer_focus_key:
        return True

    # Entity-level check: any named entity from the answer appearing in the seeded question
    if entities:
        q_norm = _normalize_transcript(seeded_question)
        for entity in entities:
            e_norm = _normalize_transcript(entity)
            if e_norm and len(e_norm) > 2 and e_norm in q_norm:
                return True

    return False


def _is_substantive_answer(text: str) -> bool:
    cleaned = _normalize_transcript(text)
    if not cleaned or _looks_like_admission(text):
        return False
    words = [word for word in cleaned.split(" ") if word]
    return len(words) >= 18


def _collect_overprobed_topics(history: list[dict], current_focus_label: str = "") -> list[str]:
    counts: dict[str, int] = {}
    # Topics with confirmed honest admissions are terminal dead-ends — exclude immediately
    # regardless of probe count. Candidate explicitly said they don't know; asking again wastes time.
    admitted_topics: set[str] = set()
    for turn in history:
        label = turn.get("focus_label") or ""
        if label:
            counts[label] = counts.get(label, 0) + 1
            rb = turn.get("reasoning_behavior")
            if isinstance(rb, dict) and rb.get("adaptability") == "admitted_gap" and rb.get("structure_score", 5) <= 1:
                admitted_topics.add(label)
    if current_focus_label:
        counts[current_focus_label] = counts.get(current_focus_label, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    overprobed = [label for label, count in ranked if count >= 2][:3]
    # Merge admitted topics first so they're at the top of the avoid list
    merged = list(dict.fromkeys(list(admitted_topics) + overprobed))
    return merged[:5]


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


def _should_prioritize_bank_followup(
    prepped_context: dict,
    queued_followups: list[str],
    active_packet: dict | None = None,
) -> bool:
    """
    Decide when a stored deepening follow-up should beat the pre-generated next question.

    We only let bank follow-ups jump the queue when the staged response is a generic
    sprint-advance / breadth-pivot style question. Direct contradiction, clarification,
    or strong weakness probes still take precedence.
    """
    if not queued_followups:
        return False

    active_route_kind = ""
    if isinstance(active_packet, dict):
        active_route_kind = str(active_packet.get("route_kind", "") or "")
    if active_route_kind == "unknown":
        return False

    route_kind = prepped_context.get("route_kind")
    if route_kind in ("discrepancy_challenge", "clarification_fast", "depth_probe", "complete"):
        return False
    if prepped_context.get("pivoting"):
        return False

    weakness = prepped_context.get("weakness")
    if isinstance(weakness, dict) and weakness.get("severity") == "high":
        return False

    return True


def _short_answer_rescue_eligible(text: str) -> bool:
    words = [word for word in _normalize_transcript(text).split(" ") if word]
    return 1 <= len(words) <= 18


def _is_generic_fasttrack_route(route_kind: object) -> bool:
    return str(route_kind or "") in {"sprint_seed", "legacy_agenda_backup", "unknown"}


def _is_close_route(route_kind: object) -> bool:
    return str(route_kind or "") in {"synthesis_close", "graceful_exit", "complete"}


def _application_transfer_served(state: dict | None) -> bool:
    if not isinstance(state, dict):
        return False
    if bool(state.get("application_question_served")):
        return True
    for turn in state.get("history", []) or []:
        route = str(turn.get("route_kind") or turn.get("answered_route_kind") or "").strip()
        if route == "application_transfer":
            return True
    return False


def _question_already_asked(candidate: str, history: list[dict], window: int = 15) -> bool:
    """
    Returns True if this exact question text was already served in this session.
    Normalised comparison — strips punctuation/case so minor rephrasing is NOT blocked,
    but verbatim repeated templates ARE caught.
    """
    if not candidate:
        return False
    normalized = _normalize_transcript(candidate)
    if not normalized:
        return False
    for turn in history[-window:]:
        asked = _normalize_transcript(str(turn.get("question", "") or ""))
        if asked and asked == normalized:
            return True
    return False


def _safe_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_followups(followups: list[str] | None, limit: int = 2) -> list[str]:
    cleaned: list[str] = []
    for followup in _safe_list(followups):
        text = str(followup).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:limit]


def _build_question_packet(
    *,
    question_text: str,
    sprint: int,
    route_kind: str,
    parsed_resume: dict | None,
    resume: str,
    followups: list[str] | None = None,
    pivoting: bool = False,
    weakness: dict | None = None,
    discrepancy: dict | None = None,
    source_turn_number: int = 0,
    focus_key_override: str = "",
    focus_label_override: str = "",
    sub_focus_key_override: str = "",
    sub_focus_label_override: str = "",
    question_posture: str = "",
    signal_goal: str = "",
    expected_space: list[str] | None = None,
    information_gain: str = "",
    voice_complexity: str = "",
    ladder_field: str = "",
    surface_kind: str = "",
    coverage_dimension_id: str = "",
    coverage_dimension_label: str = "",
) -> dict:
    followup_templates = _normalize_followups(followups)
    if focus_key_override or focus_label_override:
        focus_key = focus_key_override or _focus_key(focus_label_override)
        focus_label = focus_label_override or focus_key_override
    else:
        focus_key, focus_label = _infer_focus(question_text, "", parsed_resume, resume)
    focus_required = str(route_kind or "").startswith("trajectory_map_") or str(route_kind or "") in {
        "application_anchor_recovery",
        "application_grounding",
        "application_transfer",
        "coverage_surface",
        "coverage_depth_probe",
        "reserve_map_question",
        "second_anchor",
        "third_surface_probe",
        "focus_pivot",
    }
    if focus_required and focus_key in {"", "general", "general_background", "general background"}:
        raise RuntimeError(f"{route_kind} question packet missing map focus attribution.")
    sub_focus_key = str(sub_focus_key_override or "").strip()
    sub_focus_label = str(sub_focus_label_override or "").strip()
    expected_space_limited = list(expected_space or [])[:4]
    try:
        checker_turn_number = int(source_turn_number or 0)
    except (TypeError, ValueError):
        checker_turn_number = 0
    question_quality = check_question_readiness(
        question_text,
        route_kind=str(route_kind or ""),
        posture=str(question_posture or "").strip(),
        turn_number=checker_turn_number,
        surface_kind=str(surface_kind or "").strip(),
        expected_space=expected_space_limited,
    )
    return {
        "question_text": question_text,
        "route_kind": route_kind,
        "sprint": sprint,
        "focus_key": focus_key,
        "focus_label": focus_label,
        "sub_focus_key": sub_focus_key,
        "sub_focus_label": sub_focus_label,
        "question_posture": str(question_posture or "").strip(),
        "signal_goal": str(signal_goal or "").strip(),
        "expected_space": expected_space_limited,
        "covered_expected_space": [],
        "missing_expected_space": expected_space_limited,
        "information_gain": str(information_gain or "").strip(),
        "voice_complexity": str(voice_complexity or "").strip(),
        "ladder_field": str(ladder_field or "").strip(),
        "surface_kind": str(surface_kind or "").strip(),
        "coverage_dimension_id": str(coverage_dimension_id or "").strip(),
        "coverage_dimension_label": str(coverage_dimension_label or "").strip(),
        "followups": followup_templates,
        "asked_followup_count": 0,
        "max_followups": len(followup_templates),
        "pivoting": pivoting,
        "weakness": weakness,
        "discrepancy": discrepancy,
        "source_turn_number": source_turn_number,
        "question_quality": question_quality,
        "question_quality_flags": question_quality.get("flag_codes", []),
    }


def _clone_question_packet(packet: dict | None) -> dict:
    if not isinstance(packet, dict):
        return {}
    cloned = dict(packet)
    cloned["followups"] = _normalize_followups(packet.get("followups"), limit=10)
    return cloned


def _question_packet_ladder_kwargs(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}
    return {
        "question_posture": str(result.get("question_posture") or ""),
        "signal_goal": str(result.get("signal_goal") or ""),
        "expected_space": list(result.get("expected_space") or [])[:4],
        "information_gain": str(result.get("information_gain") or ""),
        "voice_complexity": str(result.get("voice_complexity") or ""),
        "ladder_field": str(result.get("ladder_field") or ""),
        "surface_kind": str(result.get("surface_kind") or ""),
    }


def _coverage_dimension_packet_kwargs(coverage_map: dict | None, dimension_id: str) -> dict:
    dimension_id = str(dimension_id or "").strip()
    if not dimension_id or not isinstance(coverage_map, dict):
        return {}
    for dim in coverage_map.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        if str(dim.get("id") or dim.get("dimension_id") or "").strip() == dimension_id:
            return {
                "coverage_dimension_id": dimension_id,
                "coverage_dimension_label": str(dim.get("label") or dimension_id).strip(),
                "signal_goal": str(dim.get("description") or "").strip(),
                "expected_space": list(dim.get("expected_approaches") or [])[:4],
                "information_gain": "high" if float(dim.get("weight") or 0) >= 2.0 else "medium",
                "voice_complexity": "medium",
            }
    return {"coverage_dimension_id": dimension_id, "coverage_dimension_label": dimension_id}


def _route_surface_key(focus_key: str, sub_focus_key: str = "", coverage_dimension_id: str = "") -> str:
    focus = str(focus_key or "").strip()
    if not focus:
        return ""
    coverage = str(coverage_dimension_id or "").strip()
    if coverage:
        return f"{focus}::coverage::{coverage}"
    sub = str(sub_focus_key or "").strip()
    return f"{focus}::{sub}" if sub else focus


def _history_surface_keys(history: list[dict]) -> set[str]:
    keys: set[str] = set()
    for turn in history or []:
        focus = str(turn.get("focus_key") or "").strip()
        if not focus or focus in {"general", "general_background", "general background"}:
            continue
        key = _route_surface_key(
            focus,
            str(turn.get("sub_focus_key") or "").strip(),
            str(turn.get("coverage_dimension_id") or "").strip(),
        )
        if key:
            keys.add(key)
    return keys


def _reserve_from_coverage(state: dict, history: list[dict]) -> dict | None:
    coverage_map = state.get("coverage_map")
    if not isinstance(coverage_map, dict):
        return None
    focus_key = str(
        state.get("application_transfer_fallback_focus_key")
        or (state.get("interview_agenda") or {}).get("current_focus_key")
        or ""
    ).strip()
    focus_label = str(
        state.get("application_transfer_fallback_focus_label")
        or agenda_focus_label(state.get("interview_trajectory_map") or {}, focus_key)
        or focus_key
    ).strip()
    if not focus_key:
        return None
    asked = _history_surface_keys(history)
    dims = [
        dim for dim in coverage_map.get("dimensions") or []
        if isinstance(dim, dict)
        and str(dim.get("id") or dim.get("dimension_id") or "").strip()
    ]
    dims.sort(key=lambda dim: float(dim.get("weight") or 0), reverse=True)
    for dim in dims:
        dim_id = str(dim.get("id") or dim.get("dimension_id") or "").strip()
        if _route_surface_key(focus_key, coverage_dimension_id=dim_id) in asked:
            continue
        question = str(dim.get("surfacing_question") or "").strip()
        if not question or _question_already_asked(question, history):
            continue
        return {
            "question": question,
            "route_kind": "coverage_surface",
            "focus_key": focus_key,
            "focus_label": focus_label,
            "coverage_dimension_id": dim_id,
            "coverage_dimension_label": str(dim.get("label") or dim_id).strip(),
            "question_posture": "explore",
            "signal_goal": str(dim.get("description") or f"Reserve coverage: {dim_id}").strip(),
            "expected_space": list(dim.get("expected_approaches") or [])[:4],
            "information_gain": "high" if float(dim.get("weight") or 0) >= 2.0 else "medium",
            "voice_complexity": "medium",
            "reason": "reserve_unasked_coverage_dimension",
        }
    return None


def _select_reserve_question(state: dict, history: list[dict], *, avoid_focus: str = "") -> dict | None:
    """Select a map-grounded reserve question before early close.

    This is deliberately not a generic fallback bank. It only uses already
    generated map/coverage material and refuses repeated surfaces/questions.
    """
    coverage_reserve = _reserve_from_coverage(state, history)
    if coverage_reserve:
        return coverage_reserve

    interview_map = state.get("interview_trajectory_map") or {}
    focus_areas = interview_map.get("focus_areas") if isinstance(interview_map, dict) else []
    if not isinstance(focus_areas, list):
        return None
    asked_questions = [str(turn.get("question") or "") for turn in history or []]
    asked_surfaces = _history_surface_keys(history)
    avoid_focus = str(avoid_focus or "").strip()

    ordered_areas = [
        area for area in focus_areas
        if isinstance(area, dict)
        and str(area.get("focus_key") or "").strip()
        and str(area.get("focus_key") or "").strip() != avoid_focus
    ] + [
        area for area in focus_areas
        if isinstance(area, dict)
        and str(area.get("focus_key") or "").strip() == avoid_focus
    ]

    for area in ordered_areas:
        focus_key = str(area.get("focus_key") or "").strip()
        if not focus_key:
            continue
        focus_label = str(area.get("label") or focus_key).strip()
        sub_focuses = area.get("sub_focuses") if isinstance(area.get("sub_focuses"), list) else []
        primary_sub_focus = ""
        primary_sub_label = ""
        if sub_focuses:
            sf = next((item for item in sub_focuses if isinstance(item, dict)), None)
            if isinstance(sf, dict):
                primary_sub_focus = str(sf.get("sub_focus_key") or sf.get("key") or sf.get("id") or "").strip()
                primary_sub_label = str(sf.get("label") or sf.get("name") or primary_sub_focus).strip()
        ladder = area.get("question_ladder") if isinstance(area.get("question_ladder"), list) else []
        for item in ladder:
            if not isinstance(item, dict):
                continue
            posture = str(item.get("posture") or "").strip()
            if posture in {"recover"}:
                continue
            question = str(item.get("main_question") or "").strip()
            if not question or not question.endswith("?"):
                continue
            if _question_already_asked(question, history) or question in asked_questions:
                continue
            sub_key = str(item.get("sub_focus_key") or primary_sub_focus).strip()
            sub_label = str(item.get("sub_focus_label") or primary_sub_label).strip()
            surface = _route_surface_key(focus_key, sub_key)
            if surface and surface in asked_surfaces and posture not in {"synthesize"}:
                continue
            return {
                "question": question,
                "route_kind": "reserve_map_question",
                "focus_key": focus_key,
                "focus_label": focus_label,
                "sub_focus_key": sub_key,
                "sub_focus_label": sub_label,
                "question_posture": posture or "explore",
                "signal_goal": str(item.get("signal_goal") or "Reserve map-grounded question").strip(),
                "expected_space": list(item.get("expected_space") or [])[:4],
                "information_gain": str(item.get("information_gain") or "medium").strip(),
                "voice_complexity": str(item.get("voice_complexity") or "medium").strip(),
                "reason": "reserve_unasked_ladder_question",
            }
        for question in _track_candidate_q4_options(area):
            question = str(question or "").strip()
            if not question or not question.endswith("?") or _question_already_asked(question, history):
                continue
            return {
                "question": question,
                "route_kind": "reserve_map_question",
                "focus_key": focus_key,
                "focus_label": focus_label,
                "sub_focus_key": primary_sub_focus,
                "sub_focus_label": primary_sub_label,
                "question_posture": "synthesize",
                "signal_goal": "Reserve high-signal map question before close",
                "expected_space": [],
                "information_gain": "high",
                "voice_complexity": "medium",
                "reason": "reserve_candidate_q4_option",
            }
    return None


THIRD_SURFACE_ROUTE_KIND = "third_surface_probe"
THIRD_SURFACE_MAX_DEFAULT = 1
THIRD_SURFACE_MAX_WITH_TRIGGER = 2


def _map_quarantine_focus_keys(interview_map: dict | None) -> set[str]:
    if not isinstance(interview_map, dict):
        return set()
    return {
        str(item.get("focus_key") or "").strip()
        for item in (interview_map.get("map_quarantine") or [])
        if isinstance(item, dict) and str(item.get("focus_key") or "").strip()
    }


def _focus_area_by_key(interview_map: dict | None, focus_key: str) -> dict:
    focus_key = str(focus_key or "").strip()
    if not focus_key or not isinstance(interview_map, dict):
        return {}
    for area in interview_map.get("focus_areas") or []:
        if isinstance(area, dict) and str(area.get("focus_key") or "").strip() == focus_key:
            return area
    return {}


def _third_surface_probe_turns(history: list[dict]) -> list[dict]:
    return [
        turn for turn in history or []
        if str(turn.get("route_kind") or "").strip() == THIRD_SURFACE_ROUTE_KIND
    ]


_THIRD_SURFACE_DEPTH_TRIGGER = re.compile(
    r"\b("
    r"segment(?:ed|ing|s)?|selection bias|comparable|confound(?:er|ing)?|"
    r"multiple changes|overlap(?:ped|ping)?|shipped together|support calls?|"
    r"denominator|guardrail|refunds?|sla|lag|late[- ]arriving|grain|dedup|"
    r"engineering handled|owned by|not fully prove|cannot prove|can't prove|"
    r"disagreement|looked healthy|business deteriorat"
    r")\b",
    re.IGNORECASE,
)


def _third_surface_depth_triggered(answer: str, history: list[dict]) -> bool:
    if not history:
        return False
    last_route = str(history[-1].get("route_kind") or "").strip()
    if last_route != THIRD_SURFACE_ROUTE_KIND:
        return False
    return bool(_THIRD_SURFACE_DEPTH_TRIGGER.search(str(answer or "")))


def _third_surface_budget_available(history: list[dict], answer: str) -> bool:
    count = len(_third_surface_probe_turns(history))
    if count < THIRD_SURFACE_MAX_DEFAULT:
        return True
    if count < THIRD_SURFACE_MAX_WITH_TRIGGER and _third_surface_depth_triggered(answer, history):
        return True
    return False


def _third_surface_question_is_usable(result: dict, history: list[dict], *, turn_number: int) -> tuple[bool, dict]:
    question = str(result.get("question") or "").strip()
    quality = check_question_readiness(
        question,
        route_kind=THIRD_SURFACE_ROUTE_KIND,
        posture=str(result.get("question_posture") or "").strip(),
        turn_number=turn_number,
        surface_kind=str(result.get("surface_kind") or "").strip(),
        expected_space=list(result.get("expected_space") or [])[:4],
    )
    bad_codes = set(quality.get("flag_codes") or [])
    hard_block_codes = {
        "self_rating_certainty",
        "bad_synthesis_self_rating",
        "low_signal_implementation_recall",
        "low_signal_ownership_recall",
        "low_signal_event_property_recall",
        "generic_framework_abstraction",
        "generic_low_context_prompt",
        "compound_chain",
        "multiple_question_marks",
        "missing_question_mark",
        "truncated_question",
        "severely_overlong_question",
    }
    lowered = question.lower()
    abstract_claiming = bool(
        re.search(
            r"\b(careful not to claim|avoid claiming|what should we not|what would you not|not claim from this result)\b",
            lowered,
        )
    )
    usable = (
        bool(question)
        and not _question_already_asked(question, history)
        and not bool(quality.get("should_block"))
        and not bool(bad_codes & hard_block_codes)
        and not abstract_claiming
    )
    return usable, quality


def _third_surface_candidate_score(candidate: dict, *, launch_keys: set[str], avoid_focus: str) -> tuple:
    focus_key = str(candidate.get("focus_key") or "").strip()
    value = _safe_float(candidate.get("coverage_value"), 1.5)
    role = _safe_float(candidate.get("role_relevance_weight"), 1.5)
    profile = _safe_float(candidate.get("profile_importance_weight"), 1.5)
    evidence = _safe_float(candidate.get("evidence_strength"), 1.5)
    weighted = (value * 0.45) + (role * 0.25) + (profile * 0.15) + (evidence * 0.15)
    is_deferred_focus = focus_key not in launch_keys
    same_focus = focus_key == str(avoid_focus or "").strip()
    return (
        0 if is_deferred_focus else 1,
        1 if same_focus else 0,
        -weighted,
        int(candidate.get("map_order") or 0),
    )


def _select_third_surface_probe(
    state: dict,
    history: list[dict],
    *,
    sprint: int,
    avoid_focus: str = "",
    answer: str = "",
    entities: list[str] | None = None,
    admission: bool = False,
    has_discrepancy: bool = False,
    turn_number: int = 0,
) -> dict | None:
    """Select one bounded, high-signal probe for a deferred/third surface.

    This is not a generic filler bank. It only uses accepted LLM-authored map
    material, refuses quarantined/pending tracks, and gives the surface one turn
    by default. A second turn is allowed only if the first answer exposes a
    concrete unresolved signal such as confounding, denominator risk, or
    ownership boundary.
    """
    if not _third_surface_budget_available(history, answer):
        return None
    interview_map = state.get("interview_trajectory_map") or {}
    if not isinstance(interview_map, dict):
        return None
    launch_keys = {
        str(key or "").strip()
        for key in (interview_map.get("launch_focus_keys") or [])
        if str(key or "").strip()
    }
    quarantine_keys = _map_quarantine_focus_keys(interview_map)
    asked_surfaces = _history_surface_keys(history)
    used_third_surfaces = {
        _route_surface_key(
            str(turn.get("focus_key") or "").strip(),
            str(turn.get("sub_focus_key") or "").strip(),
            str(turn.get("coverage_dimension_id") or "").strip(),
        )
        for turn in _third_surface_probe_turns(history)
    }
    candidates = []
    for candidate in anchor_surface_candidates(interview_map):
        focus_key = str(candidate.get("focus_key") or "").strip()
        surface_key = str(candidate.get("surface_key") or "").strip()
        if not focus_key or not surface_key:
            continue
        if focus_key in quarantine_keys:
            continue
        if surface_key in asked_surfaces or surface_key in used_third_surfaces:
            continue
        if _safe_float(candidate.get("coverage_value"), 1.5) < 2.0:
            continue
        area = _focus_area_by_key(interview_map, focus_key)
        track_source = str(area.get("track_source") or "").strip()
        if track_source == "quarantined" or bool(area.get("pending_hydration")):
            continue
        if track_source and track_source not in {"llm", "launch_lite", "launch_track_lite"}:
            continue
        if not area.get("question_ladder"):
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: _third_surface_candidate_score(item, launch_keys=launch_keys, avoid_focus=avoid_focus))

    for candidate in candidates:
        result = select_from_trajectory_map_detailed(
            interview_map,
            sprint=sprint,
            focus_key=str(candidate.get("focus_key") or "").strip(),
            answer=answer,
            entities=entities or [],
            history=history,
            admission=admission,
            has_discrepancy=has_discrepancy,
            depth=2,
            preferred_sub_focus_key=str(candidate.get("sub_focus_key") or "").strip(),
            preferred_surface_kind=str(candidate.get("surface_kind") or "").strip(),
        )
        if not result:
            continue
        usable, quality = _third_surface_question_is_usable(result, history, turn_number=turn_number)
        if not usable:
            continue
        result["route_kind"] = THIRD_SURFACE_ROUTE_KIND
        result.setdefault("focus_key", str(candidate.get("focus_key") or "").strip())
        result.setdefault("focus_label", str(candidate.get("focus_label") or result.get("focus_key") or "").strip())
        result.setdefault("sub_focus_key", str(candidate.get("sub_focus_key") or "").strip())
        result.setdefault("sub_focus_label", str(candidate.get("sub_focus_label") or "").strip())
        result.setdefault("surface_kind", str(candidate.get("surface_kind") or "").strip())
        result["surface_key"] = str(candidate.get("surface_key") or "").strip()
        result["third_surface_probe"] = True
        result["third_surface_budget_used"] = len(_third_surface_probe_turns(history)) + 1
        result["question_quality"] = quality
        result["reason"] = (
            "third_surface_depth_trigger"
            if _third_surface_depth_triggered(answer, history)
            else "third_surface_high_signal_exposure"
        )
        return result
    return None


def _reselect_second_anchor_for_surface(
    state: dict,
    history: list[dict],
    *,
    sprint: int,
    target: dict | None = None,
    avoid_focus: str = "",
    answer: str = "",
    entities: list[str] | None = None,
    admission: bool = False,
    has_discrepancy: bool = False,
) -> dict | None:
    """Recover a second-anchor question without losing the semantic target.

    When a prepped second-anchor packet is deduped away, falling back to a
    generic map question can silently return to the old surface. This helper
    reselects from the intended focus/sub-focus/surface first, then picks the
    next best secondary surface if that exact target is spent.
    """
    attempted_surfaces: set[str] = set(_second_anchor_surface_keys(history))
    target = dict(target or {})
    if target.get("surface_key"):
        target_queue: list[dict] = [target]
    else:
        target_queue = []

    max_attempts = max(3, len(anchor_surface_candidates(state.get("interview_trajectory_map") or {})) + 1)
    for _ in range(max_attempts):
        if target_queue:
            target = dict(target_queue.pop(0) or {})
        else:
            target = next_secondary_surface(
                state,
                avoid_focus=avoid_focus,
                avoid_surfaces=attempted_surfaces,
            )
        if not target:
            return None

        target_surface = str(target.get("surface_key") or "").strip()
        if target_surface and target_surface in attempted_surfaces:
            continue
        if target_surface:
            attempted_surfaces.add(target_surface)

        focus_key = str(target.get("focus_key") or "").strip()
        if not focus_key:
            continue

        result = select_from_trajectory_map_detailed(
            state.get("interview_trajectory_map", {}),
            sprint=sprint,
            focus_key=focus_key,
            answer=answer,
            entities=entities or [],
            history=history,
            admission=admission,
            has_discrepancy=has_discrepancy,
            preferred_sub_focus_key=str(target.get("sub_focus_key") or "").strip(),
            preferred_surface_kind=str(target.get("surface_kind") or "").strip(),
        )
        if not result:
            continue
        question = str(result.get("question") or "").strip()
        if not question or _question_already_asked(question, history):
            continue
        result["route_kind"] = "second_anchor"
        result.setdefault("focus_key", focus_key)
        result.setdefault("focus_label", str(target.get("focus_label") or focus_key).strip())
        result.setdefault("sub_focus_key", str(target.get("sub_focus_key") or "").strip())
        result.setdefault("sub_focus_label", str(target.get("sub_focus_label") or "").strip())
        result.setdefault("surface_kind", str(target.get("surface_kind") or "").strip())
        result["second_anchor_target"] = target
        return result
    return None


def _second_anchor_surface_keys(history: list[dict]) -> set[str]:
    keys: set[str] = set()
    for turn in _second_anchor_turns(history):
        focus = str(turn.get("focus_key") or "").strip()
        if not focus:
            continue
        surface = str(turn.get("surface_key") or "").strip()
        if not surface:
            surface = _route_surface_key(
                focus,
                str(turn.get("sub_focus_key") or "").strip(),
                str(turn.get("coverage_dimension_id") or "").strip(),
            )
        if surface:
            keys.add(surface)
    return keys


def _second_anchor_target_from_packet(packet: dict | None) -> dict:
    if not isinstance(packet, dict):
        return {}
    focus_key = str(packet.get("focus_key") or "").strip()
    sub_focus_key = str(packet.get("sub_focus_key") or "").strip()
    surface_key = str(packet.get("surface_key") or "").strip() or _route_surface_key(focus_key, sub_focus_key)
    return {
        "focus_key": focus_key,
        "focus_label": str(packet.get("focus_label") or focus_key).strip(),
        "sub_focus_key": sub_focus_key,
        "sub_focus_label": str(packet.get("sub_focus_label") or "").strip(),
        "surface_kind": str(packet.get("surface_kind") or "").strip(),
        "surface_key": surface_key,
    }


def _second_anchor_packet_block_reason(packet: dict | None, history: list[dict], ecount: int = 0) -> str:
    if not isinstance(packet, dict):
        return ""
    route_kind = str(packet.get("route_kind") or "").strip()
    if route_kind != "second_anchor":
        return ""
    turns = _second_anchor_turns(history)
    if len(turns) >= SECOND_ANCHOR_MAX_TURNS:
        return "second_anchor_total_budget_exhausted"
    if ecount >= SECOND_ANCHOR_CLOSE_FLOOR:
        return "evidence_budget_exhausted"
    target = _second_anchor_target_from_packet(packet)
    focus_key = str(target.get("focus_key") or "").strip()
    if focus_key and _second_anchor_focus_count(history, focus_key) >= SECOND_ANCHOR_MAX_PER_FOCUS:
        return "second_anchor_focus_budget_exhausted"
    surface_key = str(target.get("surface_key") or "").strip()
    if surface_key and surface_key in _second_anchor_surface_keys(history):
        return "second_anchor_surface_already_used"
    return ""


def _packet_followups_remaining(packet: dict | None) -> list[str]:
    if not isinstance(packet, dict):
        return []
    followups = _normalize_followups(packet.get("followups"), limit=10)
    asked = _coerce_positive_int(packet.get("asked_followup_count", 0), default=0)
    if asked <= 0:
        asked = 0
    max_followups = _coerce_positive_int(packet.get("max_followups", len(followups)), default=len(followups))
    limit = min(max_followups, len(followups))
    if asked >= limit:
        return []
    return followups[asked:limit]


def _packet_has_followups(packet: dict | None) -> bool:
    return bool(_packet_followups_remaining(packet))


# ─────────────────────────────────────────────
# SPRINT CONFIG
# ─────────────────────────────────────────────
QUESTIONS_PER_SPRINT = 5
MAP_PREP_TIMEOUT_SECONDS = float(os.getenv("MAP_PREP_TIMEOUT_SECONDS", "300"))
MAP_PREP_GENERATE_TIMEOUT_SECONDS = float(os.getenv("MAP_PREP_GENERATE_TIMEOUT_SECONDS", "300"))
MAP_PREP_MIN_LLM_BRANCH_RATIO = 0.72
MAP_PREP_MAX_HYDRATION_PASSES = int(os.getenv("MAP_PREP_MAX_HYDRATION_PASSES", "20"))
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
    1: "Hey, thanks so much for coming in — really glad to have you here. Let's start easy. Just give me a quick intro about yourself — who you are, what you've been up to lately, whatever feels natural.",
    2: "Let's talk about the technical concepts behind your work. Pick one idea at the core of what you've built — how would you explain it to someone encountering it for the first time?",
    3: "Staying with the system you just described, what would become the first real scaling or reliability bottleneck if usage jumped sharply?",
}

NON_EVIDENCE_ROUTE_KINDS = {
    "",
    "application_grounding",
    "complete",
    "echo_guard",
    "graceful_exit",
    "sprint_opener",
    "warm_open",
    "unknown",
}

MIN_APPLICATION_TRANSFER_EVALUATED_DIMENSIONS = 2
MIN_APPLICATION_TRANSFER_DEPTH_PROBES = 1


def _application_anchor_recovery_question(focus_label: str = "") -> str:
    focus = str(focus_label or "").strip()
    if focus:
        return (
            f"Before I move this to a new scenario, what is one concrete decision, "
            f"metric, or tradeoff from your {focus} work that you personally handled?"
        )
    return (
        "Before I move this to a new scenario, what is one concrete decision, "
        "metric, or tradeoff from this work that you personally handled?"
    )


def _ensure_application_transfer_arc(state: dict) -> dict:
    arc = state.get("application_transfer_arc")
    if not isinstance(arc, dict):
        arc = {}
    defaults = {
        "grounding_needed": False,
        "grounding_served": False,
        "grounding_done": False,
        "grounding_question": "",
        "grounding_answer": "",
        "main_transfer_served": False,
        "surface_count": 0,
        "depth_count": 0,
        "confirmed_depth_level": 2,
        "max_depth_level": 3,
        "depth_allowed_terms": [],
        "arc_complete": False,
    }
    merged = {**defaults, **arc}
    merged["depth_allowed_terms"] = [
        str(item).strip()
        for item in list(merged.get("depth_allowed_terms") or [])[:12]
        if str(item).strip()
    ]
    try:
        merged["confirmed_depth_level"] = max(1, min(4, int(merged.get("confirmed_depth_level") or 2)))
    except (TypeError, ValueError):
        merged["confirmed_depth_level"] = 2
    try:
        merged["max_depth_level"] = max(1, min(4, int(merged.get("max_depth_level") or 3)))
    except (TypeError, ValueError):
        merged["max_depth_level"] = 3
    state["application_transfer_arc"] = merged
    return merged


def _coverage_grounding_question(state: dict) -> str:
    coverage_map = state.get("coverage_map")
    if not isinstance(coverage_map, dict):
        return ""
    return str(coverage_map.get("grounding_question") or "").strip()


def _application_grounding_needed(state: dict) -> bool:
    arc = _ensure_application_transfer_arc(state)
    coverage_map = state.get("coverage_map")
    coverage_needs_grounding = bool(
        isinstance(coverage_map, dict)
        and coverage_map.get("grounding_needed")
        and _coverage_grounding_question(state)
    )
    if coverage_needs_grounding:
        arc["grounding_needed"] = True
        arc["grounding_question"] = _coverage_grounding_question(state)
        try:
            arc["max_depth_level"] = max(1, min(4, int(coverage_map.get("max_depth_level") or arc.get("max_depth_level") or 3)))
        except (TypeError, ValueError):
            arc["max_depth_level"] = 3
        arc["depth_allowed_terms"] = [
            str(item).strip()
            for item in list(coverage_map.get("depth_allowed_terms") or arc.get("depth_allowed_terms") or [])[:12]
            if str(item).strip()
        ]
    return bool(arc.get("grounding_needed") and not arc.get("grounding_done"))


def _application_grounding_ready(state: dict) -> bool:
    return (
        not _application_transfer_served(state)
        and bool(state.get("prepped_application_question"))
        and bool((state.get("candidate_state") or {}).get("implementation_anchor"))
        and _evidence_question_count(state) >= 3
        and _application_grounding_needed(state)
    )


def _application_anchor_recovery_ready(state: dict) -> bool:
    return (
        not _application_transfer_served(state)
        and not bool((state.get("candidate_state") or {}).get("implementation_anchor"))
        and _evidence_question_count(state) >= 5
        and not bool(state.get("application_anchor_recovery_served"))
    )


def _infer_grounding_depth(answer: str, max_depth_level: int = 3) -> tuple[int, list[str]]:
    text = str(answer or "").lower()
    level = 2
    terms: list[str] = []
    if re.search(r"\b(human review|manual review|review labels|regression|orchestration|workflow|middleware|prompt bundle|state store|schema|dashboard|metric|event|guardrail)\b", text):
        level = max(level, 2)
    if re.search(r"\b(edge case|failure|retry|fallback|lock|transaction|reconciliation|consistency|queue|partition|attribution|causal|denominator)\b", text):
        level = max(level, 3)
    specialized_terms = (
        "embedding", "embeddings", "clip", "latent", "diffusion", "sampler",
        "model weight", "model weights", "optimizer", "training loop", "engine parameter",
        "isolation level", "lock internals", "memory layout",
    )
    for term in specialized_terms:
        if term in text:
            terms.append(term)
    if terms or re.search(r"\b(model internals|internal parameters|low-level internals|specialized internals)\b", text):
        level = 4
    if re.search(r"\b(not|didn'?t|did not|wasn'?t|was not|no)\b.{0,50}\b(embedding|latent|model internals|engine parameter|weights|clip)\b", text):
        level = min(level, 2)
    level = max(1, min(max_depth_level, level))
    return level, list(dict.fromkeys(terms))[:10]


def _evidence_question_count(state: dict) -> int:
    return _coerce_positive_int(
        state.get("evidence_question_count", state.get("question_count", 0)),
        default=0,
    )


def _counts_toward_evidence_budget(route_kind: object) -> bool:
    return str(route_kind or "").strip() not in NON_EVIDENCE_ROUTE_KINDS


def _application_transfer_ready(state: dict) -> bool:
    if _application_transfer_served(state) or not state.get("prepped_application_question"):
        return False
    candidate_state = state.get("candidate_state") or {}
    if not candidate_state.get("implementation_anchor"):
        return False
    if _application_grounding_needed(state):
        return False
    return _evidence_question_count(state) >= 3


def _should_prepare_application_transfer(state: dict) -> bool:
    if _application_transfer_served(state) or state.get("prepped_application_question"):
        return False
    candidate_state = state.get("candidate_state") or {}
    if candidate_state.get("implementation_anchor"):
        return False
    return _evidence_question_count(state) >= 3


def _coverage_map_progress(coverage_map: dict | None) -> dict:
    dims = (coverage_map or {}).get("dimensions", []) if isinstance(coverage_map, dict) else []
    if not isinstance(dims, list):
        dims = []
    evaluated_states = {"voluntary", "recovered_deep", "recovered_surface", "missed", "incorrect"}
    evaluated = [
        d for d in dims
        if isinstance(d, dict) and str(d.get("coverage_state") or "") in evaluated_states
    ]
    surfaced = [
        d for d in dims
        if isinstance(d, dict) and bool(d.get("surfacing_attempted"))
    ]
    unresolved = [
        d for d in dims
        if isinstance(d, dict)
        and str(d.get("coverage_state") or "not_evaluated") == "not_evaluated"
        and not bool(d.get("surfacing_attempted"))
    ]
    try:
        score = float((coverage_map or {}).get("coverage_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "dimensions": len(dims),
        "evaluated": len(evaluated),
        "surfaced": len(surfaced),
        "unresolved": len(unresolved),
        "score": score,
    }


def _minimum_application_coverage_dimensions(coverage_map: dict | None) -> int:
    progress = _coverage_map_progress(coverage_map)
    if progress["dimensions"] <= 0:
        return 0
    return min(MIN_APPLICATION_TRANSFER_EVALUATED_DIMENSIONS, progress["dimensions"])


def _select_earned_coverage_depth_dimension(coverage_map: dict | None, state: dict) -> dict | None:
    if not isinstance(coverage_map, dict):
        return None
    arc = _ensure_application_transfer_arc(state)
    if int(arc.get("depth_count") or 0) >= MIN_APPLICATION_TRANSFER_DEPTH_PROBES:
        return None
    if int(arc.get("confirmed_depth_level") or 2) < 2:
        return None
    agenda = ensure_interview_agenda(state)
    used = agenda.get("coverage_depth_used") if isinstance(agenda.get("coverage_depth_used"), dict) else {}
    candidates: list[tuple[float, dict]] = []
    for dim in coverage_map.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        dim_id = str(dim.get("id") or dim.get("dimension_id") or "").strip()
        if not dim_id or used.get(dim_id):
            continue
        if not bool(dim.get("depth_eligible")):
            continue
        coverage_state = str(dim.get("coverage_state") or "not_evaluated").strip()
        if coverage_state not in {"voluntary", "recovered_surface"}:
            continue
        try:
            weight = float(dim.get("weight") or dim.get("signal_weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        candidates.append((weight, dim))
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def _coverage_depth_route_allowed(coverage_map: dict | None, state: dict) -> bool:
    progress = _coverage_map_progress(coverage_map)
    min_evaluated = _minimum_application_coverage_dimensions(coverage_map)
    if min_evaluated <= 0 or progress["evaluated"] < min_evaluated:
        return False
    return _select_earned_coverage_depth_dimension(coverage_map, state) is not None


def _mark_coverage_depth_probe(state: dict, coverage_map_obj: object, dimension: object) -> None:
    dim_id = str(getattr(dimension, "id", "") or "").strip()
    if not dim_id:
        return
    agenda_state = ensure_interview_agenda(state)
    used = agenda_state.get("coverage_depth_used") if isinstance(agenda_state.get("coverage_depth_used"), dict) else {}
    used[dim_id] = True
    agenda_state["coverage_depth_used"] = used
    agenda_state["phase"] = "coverage_depth"
    state["interview_agenda"] = agenda_state

    arc = _ensure_application_transfer_arc(state)
    arc["depth_count"] = int(arc.get("depth_count") or 0) + 1
    state["application_transfer_arc"] = arc
    state["_last_coverage_dim_id"] = dim_id
    state["_last_coverage_recovery_depth"] = "surface"
    if hasattr(coverage_map_obj, "to_dict"):
        state["coverage_map"] = coverage_map_obj.to_dict()


def _assessment_coverage(state: dict) -> dict:
    history = state.get("history", []) or []
    interview_map = state.get("interview_trajectory_map") or {}
    pending_hydration = list(interview_map.get("pending_hydration_focus_keys") or []) if isinstance(interview_map, dict) else []
    map_quarantine = list(interview_map.get("map_quarantine") or []) if isinstance(interview_map, dict) else []
    coverage = _coverage_map_progress(state.get("coverage_map"))
    distinct_focuses = distinct_substantive_focus_count(history)
    distinct_surfaces = distinct_substantive_surface_count(history)
    surface_groups = surfaces_by_focus(history)
    weighted_surfaces = weighted_surface_coverage(state.get("interview_trajectory_map") or {}, history)
    max_streak = max_same_focus_streak(history)
    max_surface_streak = max_same_surface_streak(history)
    focus_ratio = dominant_focus_ratio(history)
    application_served = _application_transfer_served(state)
    application_arc = _ensure_application_transfer_arc(state)
    min_application_coverage = _minimum_application_coverage_dimensions(state.get("coverage_map"))
    depth_candidate_available = _select_earned_coverage_depth_dimension(state.get("coverage_map"), state) is not None
    breadth_viable = distinct_focuses >= 2 or distinct_surfaces >= 2
    full_breadth_viable = (
        distinct_focuses >= 3
        or distinct_surfaces >= 3
        or weighted_surfaces["high_value_tested_count"] >= 2
        or bool((state.get("candidate_state") or {}).get("forced_exit_triggered"))
    )
    minimum_viable = (
        application_served
        and coverage["evaluated"] >= max(1, min_application_coverage)
        and breadth_viable
    )
    full_eligible = (
        len(history) >= MIN_COMPLETION_TURNS
        and application_served
        and coverage["evaluated"] >= max(1, min_application_coverage)
        and not depth_candidate_available
        and full_breadth_viable
        and max_surface_streak <= FOCUS_STREAK_CAP
    )
    return {
        "application_transfer_served": application_served,
        "application_transfer_arc": application_arc,
        "application_grounding_needed": bool(application_arc.get("grounding_needed")),
        "application_grounding_done": bool(application_arc.get("grounding_done")),
        "application_arc_surface_count": int(application_arc.get("surface_count") or 0),
        "application_arc_depth_count": int(application_arc.get("depth_count") or 0),
        "application_arc_confirmed_depth_level": int(application_arc.get("confirmed_depth_level") or 2),
        "coverage_dimensions": coverage["dimensions"],
        "coverage_evaluated_dimensions": coverage["evaluated"],
        "coverage_min_evaluated_dimensions": min_application_coverage,
        "coverage_depth_probe_available": depth_candidate_available,
        "coverage_surfaced_dimensions": coverage["surfaced"],
        "coverage_score": coverage["score"],
        "distinct_focuses": distinct_focuses,
        "distinct_surfaces": distinct_surfaces,
        "surfaces_by_focus": surface_groups,
        "weighted_surface_coverage": weighted_surfaces,
        "weighted_surface_coverage_ratio": weighted_surfaces["ratio"],
        "weighted_surface_tested_value": weighted_surfaces["tested_weight"],
        "weighted_surface_total_value": weighted_surfaces["total_weight"],
        "high_value_surfaces_tested": weighted_surfaces["high_value_tested"],
        "high_value_surfaces_tested_count": weighted_surfaces["high_value_tested_count"],
        "high_value_surfaces_available_count": weighted_surfaces["high_value_available_count"],
        "breadth_viable": breadth_viable,
        "full_breadth_viable": full_breadth_viable,
        "max_same_focus_streak": max_streak,
        "max_same_surface_streak": max_surface_streak,
        "dominant_focus_ratio": focus_ratio,
        "map_launch_ready": bool(interview_map.get("launch_ready")) if isinstance(interview_map, dict) else False,
        "full_map_ready": bool(interview_map.get("full_map_ready")) if isinstance(interview_map, dict) else False,
        "needs_async_hydration": bool(interview_map.get("needs_async_hydration")) if isinstance(interview_map, dict) else False,
        "pending_hydration_focus_count": len(pending_hydration),
        "pending_hydration_focus_keys": pending_hydration[:8],
        "map_quarantine_count": len(map_quarantine),
        "minimum_viable_completion": minimum_viable,
        "full_completion_eligible": full_eligible,
        "history_len": len(history),
    }


def _apply_hard_coverage_gate(evaluation: dict, coverage: dict, *, discrepancy_level: str = "none") -> dict:
    gated = dict(evaluation or {})
    risk_flags = list(gated.get("risk_flags") or [])
    existing_gate = dict(gated.get("coverage_gate") or {})
    gate_reasons: list[str] = list(existing_gate.get("reasons") or [])

    if not coverage.get("application_transfer_served"):
        gate_reasons.append("application_transfer_not_served")
    min_coverage = max(1, int(coverage.get("coverage_min_evaluated_dimensions") or 1))
    if coverage.get("coverage_evaluated_dimensions", 0) < min_coverage:
        gate_reasons.append("coverage_dimensions_not_evaluated")
    if coverage.get("coverage_depth_probe_available"):
        gate_reasons.append("application_transfer_depth_probe_not_served")
    if coverage.get("distinct_focuses", 0) < 2 and coverage.get("distinct_surfaces", 0) < 2:
        gate_reasons.append("fewer_than_two_substantive_surfaces_tested")
    if (
        coverage.get("high_value_surfaces_available_count", 0) > 0
        and coverage.get("high_value_surfaces_tested_count", 0) < 1
    ):
        gate_reasons.append("no_high_value_role_relevant_surface_tested")
    if (
        coverage.get("dominant_focus_ratio", 0.0) > 0.70
        and coverage.get("distinct_focuses", 0) < 3
        and coverage.get("distinct_surfaces", 0) < 3
        and coverage.get("high_value_surfaces_tested_count", 0) < 2
    ):
        gate_reasons.append("interview_tunneled_on_one_focus")
    if coverage.get("max_same_surface_streak", 0) > FOCUS_STREAK_CAP:
        gate_reasons.append("same_surface_streak_exceeded")

    if gate_reasons:
        gate_reasons = list(dict.fromkeys(str(reason) for reason in gate_reasons if str(reason).strip()))
        prior = str(gated.get("hire_recommendation") or "INSUFFICIENT_DATA")
        gated["hire_recommendation"] = "INSUFFICIENT_DATA"
        gated["overall_score"] = min(_safe_float(gated.get("overall_score"), 0.0), 5.0)
        gated["confidence_score"] = min(_safe_float(gated.get("confidence_score"), 0.5), 0.45)
        gated["verdict_basis"] = "hard_coverage_gate"
        gated["coverage_gate"] = {
            **existing_gate,
            "passed": False,
            "reasons": gate_reasons,
            "prior_hire_recommendation": prior,
            "assessment_coverage": coverage,
        }
        risk_flags.append(
            "Assessment coverage was too narrow for a definitive hire/no-hire verdict."
        )
        if discrepancy_level == "confirmed":
            risk_flags.append(
                "Confirmed claim risk observed, but final verdict remains insufficient-data because coverage was narrow."
            )
        summary = str(gated.get("summary") or "").strip()
        gate_summary = (
            "The interview did not gather enough broad evidence for a definitive verdict; "
            "treat this as an incomplete assessment rather than a candidate-wide rejection."
        )
        gated["summary"] = summary if summary.startswith(gate_summary) else f"{gate_summary} {summary}".strip()
        gated["candidate_safe_summary"] = gated["summary"]
        gated["recruiter_summary"] = gated.get("recruiter_summary") or gated["summary"]
    else:
        gated["coverage_gate"] = {
            **existing_gate,
            "passed": True,
            "reasons": [],
            "assessment_coverage": coverage,
        }
        gated["verdict_basis"] = gated.get("verdict_basis") or "llm_contextual_with_hard_coverage_gate"

    gated["risk_flags"] = list(dict.fromkeys(str(flag) for flag in risk_flags if str(flag).strip()))
    return gated


def _agenda_projected_history(state: dict, current_focus_key: str, current_focus_label: str) -> list[dict]:
    projected = list(state.get("history", []) or [])
    if current_focus_key:
        projected.append({"focus_key": current_focus_key, "focus_label": current_focus_label})
    return projected


def _focus_turn_count(history: list[dict], focus_key: str) -> int:
    focus_key = str(focus_key or "").strip()
    if not focus_key:
        return 0
    return sum(1 for turn in history if str(turn.get("focus_key") or "").strip() == focus_key)


def _focus_evidence_turn_count(history: list[dict]) -> int:
    return sum(1 for turn in history if str(turn.get("focus_key") or "").strip())


def _should_force_focus_ratio_rotation(state: dict, history: list[dict], current_focus_key: str) -> bool:
    """
    Ratio-based anti-tunneling is only valid once we have enough focus evidence.
    With one or two answered focus turns, every active focus looks dominant by
    definition; firing here caused premature pivots into lower-relevance work.
    """
    current_focus_key = str(current_focus_key or "").strip()
    if not current_focus_key:
        return False
    focus_evidence_turns = _focus_evidence_turn_count(history)
    if focus_evidence_turns < FOCUS_RATIO_MIN_EVIDENCE_TURNS:
        return False

    agenda = ensure_interview_agenda(state)
    primary_focus_key = str(agenda.get("primary_focus_key") or "").strip()
    if (
        current_focus_key == primary_focus_key
        and _focus_turn_count(history, current_focus_key) < PRIMARY_FOCUS_MIN_EVIDENCE_TURNS
    ):
        return False

    same_focus_total = _focus_turn_count(history, current_focus_key)
    return (same_focus_total / max(focus_evidence_turns, 1)) > FOCUS_RATIO_CAP


def _coverage_route_allowed(state: dict, *, current_focus_key: str = "", current_focus_label: str = "") -> bool:
    if not _application_transfer_served(state) or not isinstance(state.get("coverage_map"), dict):
        return False
    progress = _coverage_map_progress(state.get("coverage_map"))
    if progress["dimensions"] <= 0:
        return False
    if (
        progress["evaluated"] >= progress["dimensions"]
        and progress["dimensions"] > 0
        and not _coverage_depth_route_allowed(state.get("coverage_map"), state)
    ):
        return False
    agenda = ensure_interview_agenda(state)
    opening_count = int(agenda.get("coverage_opening_count") or 0)
    if opening_count >= MAX_COVERAGE_OPENINGS and not bool(state.get("_last_coverage_dim_id")):
        return False
    projected_history = _agenda_projected_history(state, current_focus_key, current_focus_label)
    if (
        opening_count >= MIN_COVERAGE_OPENINGS_BEFORE_STREAK_PIVOT
        and max_same_focus_streak(projected_history) > FOCUS_STREAK_CAP
        and not bool(state.get("_last_coverage_dim_id"))
    ):
        return False
    return True


def _route_phase_from_kind(route_kind: str) -> str:
    route_kind = str(route_kind or "")
    if route_kind == "application_anchor_recovery":
        return "application_transfer"
    if route_kind == "application_grounding":
        return "application_transfer"
    if route_kind == "application_transfer":
        return "application_transfer"
    if route_kind == "coverage_depth_probe":
        return "coverage_depth"
    if route_kind == "coverage_surface":
        return "coverage_surface"
    if route_kind in {"reserve_map_question", THIRD_SURFACE_ROUTE_KIND}:
        return "primary_depth"
    if route_kind in {"second_anchor", "trajectory_map_bridge"}:
        return "second_anchor"
    if route_kind in {"graceful_exit", "synthesis_close"}:
        return "synthesis_close"
    if route_kind in {"sprint_opener", "warm_open", "seed_first_followup"}:
        return "warm_open"
    return "primary_depth"


SECOND_ANCHOR_MAX_TURNS = 3
SECOND_ANCHOR_MAX_PER_FOCUS = 2
SECOND_ANCHOR_CLOSE_FLOOR = 12
SYNTHESIS_START_FLOOR = 13
SECOND_ANCHOR_START_FLOOR = 10


def _next_visible_turn_number(state: dict, history: list[dict]) -> int:
    """Return the 1-based visible question number for the next interviewer turn."""
    # Background staging can observe ``question_count`` ahead of the answered
    # history because the fast path increments it before the candidate answers
    # the next question. Agenda timing floors are about visible answered turns,
    # so history length is the stable source of truth here.
    return len(history or []) + 1


def _second_anchor_turns(history: list[dict]) -> list[dict]:
    turns: list[dict] = []
    for turn in history:
        route = str(turn.get("route_kind") or "").strip()
        phase = str(turn.get("agenda_phase") or "").strip()
        if route:
            if route == "second_anchor":
                turns.append(turn)
        elif phase == "second_anchor":
            turns.append(turn)
    return turns


def _second_anchor_budget_exhausted(history: list[dict], ecount: int) -> bool:
    return len(_second_anchor_turns(history)) >= SECOND_ANCHOR_MAX_TURNS or ecount >= SECOND_ANCHOR_CLOSE_FLOOR


def _second_anchor_focus_count(history: list[dict], focus_key: str) -> int:
    focus_key = str(focus_key or "").strip()
    if not focus_key:
        return 0
    return sum(
        1 for turn in _second_anchor_turns(history)
        if str(turn.get("focus_key") or "").strip() == focus_key
    )


def _synthesis_close_count(history: list[dict]) -> int:
    return sum(
        1 for turn in history
        if str(turn.get("route_kind") or turn.get("agenda_phase") or "") in {"synthesis_close", "graceful_exit"}
        or str(turn.get("agenda_phase") or "") == "synthesis_close"
    )


def _select_agenda_decision(
    state: dict,
    *,
    history: list[dict],
    current_focus_key: str,
    current_focus_label: str,
    answered_route_kind: str,
    weakness: dict | None,
    discrepancy_conflict: bool,
    honest_admission: bool,
    force_focus_rotation: bool,
) -> dict:
    agenda = ensure_interview_agenda(state)
    projected_history = _agenda_projected_history(state, current_focus_key, current_focus_label)
    ecount = _evidence_question_count(state)
    next_visible_turn = _next_visible_turn_number(state, history)
    weakness_continue = True
    if isinstance(weakness, dict) and "continue_probing" in weakness:
        weakness_continue = bool(weakness.get("continue_probing"))

    if answered_route_kind == "application_grounding":
        return {
            "phase": "application_transfer",
            "route": "application_transfer",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_grounding_answered_transfer_ready",
            "allow_same_focus_probe": False,
        }

    if answered_route_kind == "application_anchor_recovery" and _application_transfer_ready(state):
        return {
            "phase": "application_transfer",
            "route": "application_transfer",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_anchor_recovery_answered_transfer_ready",
            "allow_same_focus_probe": False,
        }

    if answered_route_kind == "application_transfer":
        return {
            "phase": "coverage_surface",
            "route": "coverage",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_answer_requires_coverage",
            "allow_same_focus_probe": False,
        }

    if state.get("_next_route_hint") in {"graceful_exit", "confession_pivot"}:
        return {
            "phase": "synthesis_close" if state.get("_next_route_hint") == "graceful_exit" else agenda.get("phase", "primary_depth"),
            "route": str(state.get("_next_route_hint")),
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": f"route_hint_{state.get('_next_route_hint')}",
            "allow_same_focus_probe": False,
        }

    if answered_route_kind in {"synthesis_close", "graceful_exit"} or _synthesis_close_count(history) > 0:
        return {
            "phase": "synthesis_close",
            "route": "graceful_exit",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "final_synthesis_already_served",
            "allow_same_focus_probe": False,
        }

    if _coverage_route_allowed(
        state,
        current_focus_key=current_focus_key,
        current_focus_label=current_focus_label,
    ):
        return {
            "phase": "coverage_surface",
            "route": "coverage",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "coverage_required_after_application_transfer",
            "allow_same_focus_probe": False,
        }

    if _application_transfer_served(state):
        if _second_anchor_budget_exhausted(history, ecount):
            if next_visible_turn >= SYNTHESIS_START_FLOOR:
                return {
                    "phase": "synthesis_close",
                    "route": "synthesis_close",
                    "focus_key": current_focus_key,
                    "focus_label": current_focus_label,
                    "reason": "second_anchor_budget_exhausted",
                    "allow_same_focus_probe": False,
                }
            return {
                "phase": "primary_depth",
                "route": "phase_depth",
                "focus_key": current_focus_key,
                "focus_label": current_focus_label,
                "reason": "second_anchor_budget_wait_until_synthesis_floor",
                "allow_same_focus_probe": False,
            }
        second_anchor_counts: dict[str, int] = {}
        for turn in _second_anchor_turns(history):
            focus = str(turn.get("focus_key") or "").strip()
            if focus:
                second_anchor_counts[focus] = second_anchor_counts.get(focus, 0) + 1
        if second_anchor_counts:
            exhausted = list(agenda.get("exhausted_focus_keys") or [])
            for focus, count in second_anchor_counts.items():
                if count >= SECOND_ANCHOR_MAX_PER_FOCUS and focus not in exhausted:
                    exhausted.append(focus)
            agenda["exhausted_focus_keys"] = exhausted
            state["interview_agenda"] = agenda
        if not second_anchor_counts and next_visible_turn < SECOND_ANCHOR_START_FLOOR:
            return {
                "phase": "primary_depth",
                "route": "phase_depth",
                "focus_key": current_focus_key,
                "focus_label": current_focus_label,
                "reason": "second_anchor_wait_until_floor",
                "allow_same_focus_probe": False,
            }
        next_surface = next_secondary_surface(state, avoid_focus=current_focus_key)
        next_focus = str(next_surface.get("focus_key") or "").strip()
        next_label = str(next_surface.get("focus_label") or next_focus).strip()
        if next_focus:
            if not second_anchor_counts and next_visible_turn < SECOND_ANCHOR_START_FLOOR:
                return {
                    "phase": "primary_depth",
                    "route": "phase_depth",
                    "focus_key": current_focus_key,
                    "focus_label": current_focus_label,
                    "reason": "second_anchor_wait_until_visible_turn_floor",
                    "allow_same_focus_probe": False,
                }
            return {
                "phase": "second_anchor",
                "route": "second_anchor",
                "focus_key": next_focus,
                "focus_label": next_label,
                "sub_focus_key": str(next_surface.get("sub_focus_key") or "").strip(),
                "sub_focus_label": str(next_surface.get("sub_focus_label") or "").strip(),
                "surface_kind": str(next_surface.get("surface_kind") or "").strip(),
                "surface_key": str(next_surface.get("surface_key") or "").strip(),
                "reason": "coverage_complete_or_capped_pivot_second_anchor",
                "allow_same_focus_probe": False,
            }
        if next_visible_turn < SYNTHESIS_START_FLOOR:
            next_focus, next_label = least_used_focus(state, avoid_focus=current_focus_key)
            if (
                next_visible_turn >= SECOND_ANCHOR_START_FLOOR
                and next_focus
                and _second_anchor_focus_count(history, next_focus) < SECOND_ANCHOR_MAX_PER_FOCUS
            ):
                return {
                    "phase": "second_anchor",
                    "route": "second_anchor",
                    "focus_key": next_focus,
                    "focus_label": next_label,
                    "reason": "least_used_focus_rotation_before_close",
                    "allow_same_focus_probe": False,
                }
            return {
                "phase": "primary_depth",
                "route": "phase_depth",
                "focus_key": current_focus_key,
                "focus_label": current_focus_label,
                "reason": "no_secondary_focus_before_synthesis_floor_continue_grounded_depth",
                "allow_same_focus_probe": False,
            }
        return {
            "phase": "synthesis_close",
            "route": "synthesis_close",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "no_secondary_focus_available",
            "allow_same_focus_probe": False,
        }

    if _application_grounding_ready(state):
        return {
            "phase": "application_transfer",
            "route": "application_grounding",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_grounding_needed",
            "allow_same_focus_probe": False,
        }

    if _application_anchor_recovery_ready(state):
        return {
            "phase": "application_transfer",
            "route": "application_anchor_recovery",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_anchor_recovery_needed",
            "allow_same_focus_probe": False,
        }

    if _application_transfer_ready(state):
        return {
            "phase": "application_transfer",
            "route": "application_transfer",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_transfer_ready",
            "allow_same_focus_probe": False,
        }

    if ecount >= 5 and (state.get("application_transfer_error") or not (state.get("candidate_state") or {}).get("implementation_anchor")):
        return {
            "phase": "application_transfer",
            "route": "application_transfer_blocked",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "application_transfer_required_but_not_ready",
            "allow_same_focus_probe": False,
        }

    focus_evidence_turns = _focus_evidence_turn_count(projected_history)
    current_focus_turns = _focus_turn_count(history, current_focus_key)
    primary_focus_key = str(agenda.get("primary_focus_key") or "").strip()
    before_primary_floor = (
        bool(primary_focus_key)
        and current_focus_key == primary_focus_key
        and current_focus_turns < PRIMARY_FOCUS_MIN_EVIDENCE_TURNS
    )
    same_focus_streak_trigger = max_same_focus_streak(projected_history) > FOCUS_STREAK_CAP
    dominant_ratio_trigger = (
        focus_evidence_turns >= FOCUS_RATIO_MIN_EVIDENCE_TURNS
        and dominant_focus_ratio(projected_history) > FOCUS_RATIO_CAP
    )
    anti_tunnel_trigger = force_focus_rotation or same_focus_streak_trigger or dominant_ratio_trigger
    candidate_gap_trigger = honest_admission or not weakness_continue

    if (
        (anti_tunnel_trigger and not before_primary_floor)
        or candidate_gap_trigger
    ):
        next_surface = next_secondary_surface(state, avoid_focus=current_focus_key)
        next_focus = str(next_surface.get("focus_key") or "").strip()
        next_label = str(next_surface.get("focus_label") or next_focus).strip()
        if next_focus:
            exhausted = list(agenda.get("exhausted_focus_keys") or [])
            if current_focus_key and current_focus_key not in exhausted:
                exhausted.append(current_focus_key)
            agenda["exhausted_focus_keys"] = exhausted
            state["interview_agenda"] = agenda
            reason = "candidate_gap_pivot" if candidate_gap_trigger and not anti_tunnel_trigger else "anti_tunnel_or_candidate_gap_pivot"
            return {
                "phase": "second_anchor" if ecount >= 6 else "primary_depth",
                "route": "focus_pivot",
                "focus_key": next_focus,
                "focus_label": next_label,
                "sub_focus_key": str(next_surface.get("sub_focus_key") or "").strip(),
                "sub_focus_label": str(next_surface.get("sub_focus_label") or "").strip(),
                "surface_kind": str(next_surface.get("surface_kind") or "").strip(),
                "surface_key": str(next_surface.get("surface_key") or "").strip(),
                "reason": reason,
                "allow_same_focus_probe": False,
            }

    if discrepancy_conflict:
        return {
            "phase": agenda.get("phase") or "primary_depth",
            "route": "discrepancy_challenge",
            "focus_key": current_focus_key,
            "focus_label": current_focus_label,
            "reason": "confirmed_discrepancy_budget_available",
            "allow_same_focus_probe": True,
        }

    return {
        "phase": "primary_depth" if ecount < 13 else "synthesis_close",
        "route": "phase_depth",
        "focus_key": current_focus_key or agenda.get("primary_focus_key", ""),
        "focus_label": current_focus_label or agenda_focus_label(state.get("interview_trajectory_map") or {}, agenda.get("primary_focus_key", "")),
        "reason": "phase_depth_allowed",
        "allow_same_focus_probe": True,
    }


def _closing_phase(current_sprint: int, sprint_question_count: int) -> str:
    if current_sprint != 3:
        return ""
    remaining = max(QUESTIONS_PER_SPRINT - sprint_question_count, 0)
    if remaining == 2:
        return "last_two"
    if remaining == 1:
        return "final_question"
    return ""


def _decorate_closing_question(question: str, closing_phase: str) -> str:
    if not question.strip():
        return question
    lowered = question.lower()
    if closing_phase == "last_two":
        if lowered.startswith("we're heading into the last two questions"):
            return question
        return (
            "We're heading into the last two questions, so I want to end on the most revealing parts of your experience. "
            f"{question}"
        )
    if closing_phase == "final_question":
        if lowered.startswith("we're on the final question now"):
            return question
        return (
            "We're on the final question now, so I want to leave you with one thoughtful closing scenario. "
            f"{question}"
        )
    return question


def _coerce_positive_int(value: object, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _staged_answer_version(item: dict) -> int:
    analysis = item.get("analysis", {})
    analysis_version = analysis.get("answer_version") if isinstance(analysis, dict) else None
    return _coerce_positive_int(item.get("answer_version", analysis_version), default=1)


def _is_superseded_staged_item(item: dict, latest_turn_versions: dict[str, int]) -> bool:
    turn_id = item.get("turn_id")
    if not turn_id:
        return False
    staged_version = _staged_answer_version(item)
    latest_version = _coerce_positive_int(
        latest_turn_versions.get(turn_id),
        default=staged_version,
    )
    return staged_version < latest_version


def _upsert_turn_skeleton(
    state: dict,
    *,
    turn_id: str,
    question: str,
    answer: str,
    sprint: int,
    persona: str,
    focus_key: str,
    focus_label: str,
    route_kind: str,
    answer_version: int,
    sub_focus_key: str = "",
    sub_focus_label: str = "",
    surface_kind: str = "",
    question_posture: str = "",
    signal_goal: str = "",
    expected_space: list[str] | None = None,
    covered_expected_space: list[str] | None = None,
    missing_expected_space: list[str] | None = None,
    coverage_dimension_id: str = "",
    coverage_dimension_label: str = "",
) -> None:
    """
    Write immediate conversational memory for the just-committed candidate answer.

    This happens in the fast path before the full background analysis completes so
    continuity does not depend on delayed staging. The background pipeline later
    enriches this same turn record in-place by `turn_id`.
    """
    if not turn_id:
        return

    history = state.setdefault("history", [])
    existing = next((item for item in history if item.get("turn_id") == turn_id), None)
    payload = {
        "turn_id": turn_id,
        "question": question,
        "answer": answer,
        "weakness": None,
        "concepts": [],
        "discrepancy": None,
        "reasoning_behavior": None,
        "sprint": sprint,
        "persona": persona,
        "focus_key": focus_key,
        "focus_label": focus_label,
        "sub_focus_key": sub_focus_key,
        "sub_focus_label": sub_focus_label,
        "surface_kind": str(surface_kind or "").strip(),
        "question_posture": question_posture,
        "signal_goal": signal_goal,
        "expected_space": list(expected_space or [])[:4],
        "covered_expected_space": list(covered_expected_space or [])[:4],
        "missing_expected_space": list(missing_expected_space or expected_space or [])[:4],
        "coverage_dimension_id": str(coverage_dimension_id or "").strip(),
        "coverage_dimension_label": str(coverage_dimension_label or "").strip(),
        "answer_version": answer_version,
        "route_kind": route_kind,
        "analysis_status": "pending",
    }

    if existing:
        existing.update(payload)
    else:
        history.append(payload)


class Orchestrator:
    """
    The Interview Controller — two-track response architecture.

    ┌─ FAST TRACK (handle_transcript) ──────────────────────────── ~300-500ms ─┐
    │  1. Consume staged analysis from previous background run                  │
    │     → apply to canonical state (history, weaknesses, candidate_model)     │
    │  2. Serve fast response — priority:                                        │
    │     a) prepped_next_question (adversarial probe, instant, no LLM)         │
    │     b) bank follow-up via adapt_followup() (Haiku, ~300ms)                │
    │     c) fail closed when neither map nor staged LLM question is available  │
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

    def __init__(self, tts_service=None):
        self.session_manager = SessionManager()
        self.concept_agent = ConceptAgent()
        self.weakness_agent = WeaknessAgent()
        self.followup_agent = FollowUpAgent()
        self.discrepancy_agent = DiscrepancyAgent()
        self.evaluation_agent = EvaluationAgent()
        self.resume_agent = ResumeAgent()
        self.reasoning_agent = ReasoningBehaviorAgent()
        self.policy_checker_agent = PolicyCheckerAgent()
        self.tts_service = tts_service  # Optional — enables audio pre-generation

        # In-memory inflight guard for _run_background_pipeline.
        # Keyed by (session_id, turn_id, answer_version) so exact duplicate work is
        # suppressed while same-turn revisions remain allowed to run.
        self._pipeline_inflight: set[tuple[str, str, int]] = set()
        # Tracks which turn_ids currently have ANY pipeline in flight per session.
        # Prevents STT revision explosions: if a pipeline is already running for a
        # given (session_id, turn_id), subsequent revisions skip launching a new one.
        self._turn_pipeline_running: dict[str, set[str]] = {}  # session_id → set[turn_id]

        self._per_answer_scores: dict[str, list[dict]] = {}
        self._partial_entities: dict[str, set] = {}
        self._partial_snapshot_meta: dict[str, dict] = {}
        self._speculative_locks: dict[str, asyncio.Lock] = {}
        self._finalization_inflight: set[str] = set()
        self._hydration_inflight: set[str] = set()

    async def _trace(self, session_id: str, event: str, **fields) -> None:
        await interview_telemetry.log(session_id, event, source="backend.orchestrator", **fields)

    # ─────────────────────────────────────────────
    # SESSION LIFECYCLE
    # ─────────────────────────────────────────────

    async def start_session(
        self,
        resume: str,
        github_links: list[str],
        target_role: str = "",
        years_experience: str = "",
        prior_assessment_context: dict | None = None,
        prior_assessment_prompt: str = "",
    ) -> str:
        session_id = await self.prepare_session_map(
            resume,
            github_links,
            target_role=target_role,
            years_experience=years_experience,
            prior_assessment_context=prior_assessment_context,
            prior_assessment_prompt=prior_assessment_prompt,
        )
        await self.start_prepared_session(session_id)
        return session_id

    def _build_initial_state(
        self,
        *,
        session_id: str,
        resume: str,
        github_links: list[str],
        parsed_resume: dict,
        target_role: str,
        years_experience: str,
        prior_assessment_context: dict | None,
        prior_assessment_prompt: str,
    ) -> dict:
        # Do NOT pre-load generic follow-ups into the opening packet. _seed_first_question
        # runs after the map is prepared and writes a resume-grounded follow-up to
        # prepped_next_question. Generic follow-ups in the opening packet would fire via
        # should_use_packet_followup BEFORE the seed arrives, shadowing it.
        opening_followups: list[str] = []
        opening_packet = _build_question_packet(
            question_text=SPRINT_OPENERS[1],
            sprint=1,
            route_kind="warm_open",
            parsed_resume=parsed_resume,
            resume=resume,
            followups=opening_followups,
            source_turn_number=0,
        )

        return {
            "session_id": session_id,
            "current_sprint": 1,
            "current_persona": "curious_lead",
            "sprint_name": SPRINTS[1]["name"],
            "question_count": 0,
            "evidence_question_count": 0,
            "sprint_question_count": 0,
            "interview_start_time": None,
            "interview_started": False,
            "interview_complete": False,
            "finalization_status": "idle",
            "finalization_error": "",
            "report_ready": False,
            "resume": resume,
            "parsed_resume": parsed_resume,
            "github_links": github_links,
            "target_role": target_role,
            "years_experience": years_experience,
            "prior_assessment_context": prior_assessment_context or {},
            "prior_assessment_prompt": prior_assessment_prompt.strip(),
            "skills": parsed_resume.get("skills", []),
            "scores": {},
            "weaknesses": [],
            "history": [],
            "failure_surface": {},
            "final_evaluation": None,
            "last_question": SPRINT_OPENERS[1],
            "consecutive_high_weakness_count": 0,
            "last_weakness_type": None,
            "current_question_followups": list(opening_followups),
            "current_question_followup_asked": False,
            "active_question_packet": opening_packet,
            "prepped_next_packet": {},
            "candidate_model": {
                "project_map": {},
                "established_facts": [],
                "probed_weaknesses": [],
            },
            "prepped_next_question": None,
            "prepped_next_question_turn_number": 0,
            "prepped_next_context": {},
            "prepped_turn_queue": [],
            "speculative_cache": {},
            "current_answer_turn_id": "",
            "current_answer_question": "",
            "current_answer_response": "",
            "current_answer_context": {},
            "current_answer_turn_number": 0,
            "current_answer_version": 0,
            "latest_turn_versions": {},
            "interview_trajectory_map": {},
            "interview_map_status": "preparing",
            "interview_map_error": "",
            "interview_map_validation": {},
            "interview_map_prepared_at": None,
            "interview_agenda": initial_interview_agenda({}),
            "candidate_state": {
                "disengagement_level": 0.0,
                "consecutive_no_content": 0,
                "explicit_skip_count": 0,
                "social_deflection_count": 0,
                "incoherence_count": 0,
                "communication_mode": "normal",
                "topic_fatigue": {},
                "topic_question_counts": {},
                "forced_exit_triggered": False,
                "phase": "orientation",
                "anchor_confidence": None,
                "implementation_anchor": None,
                "second_domain_surfaced": None,
                "_save_face_pivot_used": False,
            },
            "application_transfer_arc": _ensure_application_transfer_arc({}),
        }

    async def prepare_session_map(
        self,
        resume: str,
        github_links: list[str],
        target_role: str = "",
        years_experience: str = "",
        prior_assessment_context: dict | None = None,
        prior_assessment_prompt: str = "",
    ) -> str:
        session_id = str(uuid.uuid4())
        started_at = time.perf_counter()

        parsed_resume = await self.resume_agent.parse(
            resume,
            target_role=target_role,
            years_experience=years_experience,
        )
        if not isinstance(parsed_resume, dict):
            raise RuntimeError("Resume parsing returned non-JSON output; refusing empty parsed_resume fallback.")
        if isinstance(prior_assessment_context, dict) and prior_assessment_context:
            parsed_resume["prior_assessment_context"] = prior_assessment_context
        if prior_assessment_prompt.strip():
            parsed_resume["prior_assessment_prompt"] = prior_assessment_prompt.strip()

        state = self._build_initial_state(
            session_id=session_id,
            resume=resume,
            github_links=github_links,
            parsed_resume=parsed_resume,
            target_role=target_role,
            years_experience=years_experience,
            prior_assessment_context=prior_assessment_context,
            prior_assessment_prompt=prior_assessment_prompt,
        )
        await self.session_manager.save_state(session_id, state)
        await self._trace(
            session_id,
            "session_initialized",
            resume_chars=len(resume),
            github_links=len(github_links),
            target_role=target_role,
            years_experience=years_experience,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )

        map_result = await self._build_interview_map(session_id, max_wait_seconds=MAP_PREP_TIMEOUT_SECONDS)
        if not map_result:
            verified_state = await self.session_manager.get_state(session_id)
            error = str(verified_state.get("interview_map_error", "") or "").strip() or "Interview map preparation failed"
            raise RuntimeError(error)
        return session_id

    async def start_prepared_session(self, session_id: str) -> str:
        started_at = time.perf_counter()
        state = await self.session_manager.get_state(session_id)
        map_status = str(state.get("interview_map_status", "") or "")
        if map_status != "ready":
            error = str(state.get("interview_map_error", "") or "").strip()
            raise RuntimeError(error or f"Interview map status is '{map_status}', not ready")

        focus_areas = ((state.get("interview_trajectory_map") or {}).get("focus_areas", []) or [])
        if not focus_areas:
            raise RuntimeError("Interview map missing after preparation")
        ensure_interview_agenda(state)

        if not state.get("prepped_next_question"):
            await self._seed_first_question(session_id)

        state = await self.session_manager.get_state(session_id)

        # Q0 = broad story opener (Phase 1, Q1). The map's directional opener fires at Q2
        # once the candidate has told their story and _seed_first_question has seeded Q1.
        first_map_opener = _track_opener(focus_areas[0]) if focus_areas and isinstance(focus_areas[0], dict) else ""
        if first_map_opener:
            composed_opener = SPRINT_OPENERS[1]
            state["last_question"] = composed_opener
            state["active_question_packet"] = _build_question_packet(
                question_text=composed_opener,
                sprint=1,
                route_kind="warm_open",
                parsed_resume=state.get("parsed_resume"),
                resume=state.get("resume", ""),
                followups=[],
                source_turn_number=0,
            )

        state["interview_started"] = True
        state["interview_start_time"] = time.time()
        await self.session_manager.save_state(session_id, state)
        await self._trace(
            session_id,
            "session_started",
            focus_areas=len(focus_areas),
            llm_focuses=int((state.get("interview_map_validation") or {}).get("llm_focus_count", 0) or 0),
            rich_focuses=int((state.get("interview_map_validation") or {}).get("rich_focus_count", 0) or 0),
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )
        return session_id

    async def end_session(self, session_id: str) -> dict:
        started_at = time.perf_counter()
        state = await self.session_manager.get_state(session_id)

        # Idempotency guard — evaluation already ran (orchestrator auto-called us at
        # turn completion); a second call from the UI's /end_interview would re-pop
        # per_answer_scores (now empty) and overwrite the real evaluation with zeros.
        if state.get("final_evaluation") and state.get("interview_complete"):
            if state.get("finalization_status") != "complete" or not state.get("report_ready"):
                state["finalization_status"] = "complete"
                state["finalization_error"] = ""
                state["report_ready"] = True
                await self.session_manager.save_state(session_id, state)
            return state

        if state.get("finalization_status") == "running" or session_id in self._finalization_inflight:
            started_running_at = _safe_float(state.get("finalization_started_at"), 0.0)
            stale_after_seconds = float(os.getenv("FINALIZATION_STALE_AFTER_SECONDS", "240"))
            if started_running_at and time.time() - started_running_at < stale_after_seconds:
                for _ in range(240):
                    await asyncio.sleep(0.5)
                    latest = await self.session_manager.get_state(session_id)
                    if latest.get("final_evaluation") and latest.get("interview_complete"):
                        if latest.get("finalization_status") != "complete" or not latest.get("report_ready"):
                            latest["finalization_status"] = "complete"
                            latest["finalization_error"] = ""
                            latest["report_ready"] = True
                            await self.session_manager.save_state(session_id, latest)
                        return latest
                    if latest.get("finalization_status") in {"complete", "failed"}:
                        return latest
                return await self.session_manager.get_state(session_id)

        self._finalization_inflight.add(session_id)
        state["interview_complete"] = True
        state["finalization_status"] = "running"
        state["finalization_started_at"] = time.time()
        state["finalization_error"] = ""
        state["report_ready"] = False
        await self.session_manager.save_state(session_id, state)

        # Flush any staged analysis that hasn't been consumed so evaluation sees complete history
        queue = state.pop("prepped_turn_queue", [])
        legacy_staged = state.pop("prepped_turn_analysis", None)
        legacy_metadata = state.pop("prepped_next_metadata", {})
        if legacy_staged and legacy_staged.get("session_id") == session_id:
            queue.append({
                "turn_id": legacy_staged.get("turn_id", ""),
                "turn_number": legacy_staged.get("turn_number", state.get("question_count", 0)),
                "answer_version": legacy_staged.get("answer_version", 1),
                "analysis": legacy_staged,
                "metadata": legacy_metadata,
            })
        latest_turn_versions = dict(state.get("latest_turn_versions", {}))
        for item in sorted(
            queue,
            key=lambda queued: (
                queued.get("turn_number", 0),
                _staged_answer_version(queued),
            ),
        ):
            if _is_superseded_staged_item(item, latest_turn_versions):
                continue
            analysis = item.get("analysis", {})
            if analysis.get("session_id") == session_id:
                self._apply_staged_analysis(state, analysis, item.get("metadata", {}))
                applied_turn_id = item.get("turn_id")
                if applied_turn_id:
                    latest_turn_versions.pop(applied_turn_id, None)
        state.pop("prepped_next_question", None)
        state.pop("prepped_next_question_turn_number", None)
        state.pop("prepped_next_context", None)
        state.pop("prepped_next_packet", None)
        state.pop("speculative_cache", None)
        state.pop("latest_turn_versions", None)

        history = state.get("history", [])
        if len(history) > int(state.get("question_count") or 0):
            state["question_count"] = len(history)
        if len(history) > int(state.get("evidence_question_count") or 0):
            state["evidence_question_count"] = max(
                int(state.get("evidence_question_count") or 0),
                sum(
                    1
                    for turn in history
                    if _counts_toward_evidence_budget(turn.get("route_kind"))
                ),
            )
        if history:
            reasoning_signals = [
                h.get("reasoning_behavior", {})
                for h in history
                if isinstance(h.get("reasoning_behavior"), dict)
            ]
            per_answer_scores = self._per_answer_scores.pop(session_id, [])
            weaknesses = state.get("weaknesses", [])
            state["assessment_coverage"] = _assessment_coverage(state)
            coverage_ratio = float(state["assessment_coverage"].get("coverage_score") or 0.0)
            if coverage_ratio <= 0:
                coverage_ratio = 0.25 if _application_transfer_served(state) else 0.0

            # Aggregate discrepancy_level from history — "confirmed" if any turn had a confirmed conflict
            _has_confirmed_discrepancy = any(
                isinstance(h.get("discrepancy"), dict)
                and h["discrepancy"].get("conflict_level") == "confirmed"
                for h in history
            )
            _discrepancy_level = "confirmed" if _has_confirmed_discrepancy else "none"

            _candidate_state = state.get("candidate_state") or {}
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
                coverage_map=state.get("coverage_map"),
                assessment_coverage=state["assessment_coverage"],
                discrepancy_level=_discrepancy_level,
                disengagement_level=_safe_float(_candidate_state.get("disengagement_level"), 0.0),
                disengagement_triggered=bool(_candidate_state.get("forced_exit_triggered", False)),
            )
            evaluation = _apply_hard_coverage_gate(
                evaluation,
                state["assessment_coverage"],
                discrepancy_level=_discrepancy_level,
            )
            state["final_evaluation"] = evaluation
            state["scores"] = evaluation.get("breakdown", {})
            state["failure_surface"] = evaluation.get("failure_surface", {})
        else:
            state["assessment_coverage"] = _assessment_coverage(state)
            state["final_evaluation"] = {
                "schema_version": "final_report_v2",
                "overall_score": 0,
                "breakdown": {
                    "reasoning": "inconclusive",
                    "technical_depth": "inconclusive",
                    "communication": "inconclusive",
                    "adaptability": "inconclusive",
                },
                "failure_surface": {},
                "hire_recommendation": "INSUFFICIENT_DATA",
                "confidence_score": 0.1,
                "summary": "No candidate answers were captured, so the interview cannot produce a substantive assessment.",
                "risk_flags": ["Interview completed without captured candidate turns."],
                "strengths": [],
                "claim_credibility_risk": {
                    "level": "not_tested",
                    "detail": "No resume claims were tested.",
                },
                "untested_dimensions": ["all"],
                "coverage_gate": {
                    "passed": False,
                    "reasons": ["empty_history"],
                    "assessment_coverage": state["assessment_coverage"],
                },
                "interview_quality": {
                    "score": 0.0,
                    "band": "poor",
                    "fairness_warnings": ["empty_history"],
                    "tunneling_detected": False,
                },
                "confidence_band": {"low": 0.0, "point": 0.0, "high": 1.0},
                "role_fit_profile": {
                    "target_role_fit": "inconclusive",
                    "best_fit_archetype": "unclear",
                    "strongest_signal": "",
                    "largest_unresolved_risk": "No candidate answers were captured.",
                    "alternate_fit_notes": "",
                },
                "ability_profile": {
                    "strongest_verified_signal": "",
                    "weakest_verified_signal": "",
                    "alternate_fit_archetypes": [],
                    "target_role_fit": "inconclusive",
                    "role_fit_explanation": "No evidence was captured.",
                },
                "resume_claim_calibration": {
                    "claims_tested": [],
                    "claims_substantiated": [],
                    "claims_partially_substantiated": [],
                    "claims_not_substantiated": [],
                    "claims_untested": [],
                    "impact_on_verdict": "inconclusive",
                },
                "lens_findings": {},
                "tested_strengths": [],
                "tested_risks": ["Interview completed without captured candidate turns."],
                "claim_findings": [],
                "recommended_followups": ["Repeat the interview with captured candidate answers."],
                "candidate_safe_summary": "No candidate answers were captured, so the interview cannot produce a substantive assessment.",
                "recruiter_summary": "No candidate answers were captured, so the interview cannot produce a substantive assessment.",
                "review_reconciliation": {
                    "reviewer_concerns": [],
                    "accepted_changes": ["Empty interview guard applied."],
                    "rejected_changes": [],
                    "review_model": "not_run",
                },
                "verdict_basis": "empty_interview_guard",
            }
            state["scores"] = state["final_evaluation"]["breakdown"]
            state["failure_surface"] = {}

        state["finalization_status"] = "complete"
        state["finalization_error"] = ""
        state["report_ready"] = bool(state.get("final_evaluation"))
        if state["interview_complete"] and state["finalization_status"] == "complete" and not state["report_ready"]:
            state["finalization_status"] = "failed"
            state["finalization_error"] = "Finalization completed without a report."
        should_trace_session_end = not bool(state.get("session_end_trace_emitted"))
        state["session_end_trace_emitted"] = True
        await self.session_manager.save_state(session_id, state)
        self._finalization_inflight.discard(session_id)
        self._partial_entities.pop(session_id, None)
        self._partial_snapshot_meta.pop(session_id, None)
        if should_trace_session_end:
            await self._trace(
                session_id,
                "session_ended",
                question_count=state.get("question_count", 0),
                history_len=len(state.get("history", [])),
                sprint=state.get("current_sprint", 1),
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )

        try:
            evaluation = state.get("final_evaluation") or {}
            duration = (time.time() - state.get("interview_start_time", time.time())) / 60
            weaknesses = state.get("weaknesses", [])
            weakness_by_type: dict[str, int] = {}
            for w in weaknesses:
                t = w.get("type", "unknown")
                weakness_by_type[t] = weakness_by_type.get(t, 0) + 1
            _parsed = state.get("parsed_resume") or {}
            full_report = {
                "session_id": session_id,
                "complete": True,
                "candidate_name": _parsed.get("candidate_name", ""),
                "target_role": state.get("target_role", ""),
                "years_experience": state.get("years_experience", ""),
                "total_questions": state.get("question_count", 0),
                "overall_score": evaluation.get("overall_score"),
                "hire_recommendation": evaluation.get("hire_recommendation"),
                "confidence_score": evaluation.get("confidence_score"),
                "schema_version": evaluation.get("schema_version", "legacy_report"),
                "confidence_band": evaluation.get("confidence_band"),
                "summary": evaluation.get("summary"),
                "strengths": evaluation.get("strengths", []),
                "risk_flags": evaluation.get("risk_flags", []),
                "untested_dimensions": evaluation.get("untested_dimensions", []),
                "claim_credibility_risk": evaluation.get("claim_credibility_risk", {"level": "not_tested", "detail": ""}),
                "coverage_gate": evaluation.get("coverage_gate"),
                "interview_quality": evaluation.get("interview_quality"),
                "role_fit_profile": evaluation.get("role_fit_profile"),
                "ability_profile": evaluation.get("ability_profile"),
                "resume_claim_calibration": evaluation.get("resume_claim_calibration"),
                "lens_findings": evaluation.get("lens_findings"),
                "tested_strengths": evaluation.get("tested_strengths", []),
                "tested_risks": evaluation.get("tested_risks", []),
                "claim_findings": evaluation.get("claim_findings", []),
                "recommended_followups": evaluation.get("recommended_followups", []),
                "candidate_safe_summary": evaluation.get("candidate_safe_summary", evaluation.get("summary")),
                "recruiter_summary": evaluation.get("recruiter_summary", evaluation.get("summary")),
                "review_reconciliation": evaluation.get("review_reconciliation"),
                "scores": evaluation.get("breakdown", state.get("scores", {})),
                "failure_surface": evaluation.get("failure_surface", state.get("failure_surface", {})),
                "weakness_summary": weakness_by_type,
                "raw_weaknesses": weaknesses,
                "coverage_portrait": evaluation.get("coverage_portrait"),
                "coverage_verdict_advisory": evaluation.get("coverage_verdict_advisory"),
                "verdict_basis": evaluation.get("verdict_basis"),
                "verdict_confidence_basis": evaluation.get("verdict_confidence_basis"),
            }
            asyncio.create_task(persist_session(
                session_id=session_id,
                resume_snippet=state.get("resume", "")[:200],
                hire_recommendation=evaluation.get("hire_recommendation", ""),
                overall_score=_safe_float(evaluation.get("overall_score"), 0.0),
                sprint_reached=_coerce_positive_int(state.get("current_sprint", 1), default=1),
                duration_minutes=round(duration, 1),
                full_report=full_report,
            ))
            external_handoff = state.get("external_handoff") or {}
            handoff_id = str(external_handoff.get("handoff_id") or "")
            if handoff_id:
                asyncio.create_task(notify_handoff_complete(handoff_id, session_id, full_report))
        except Exception:
            pass

        return state

    async def start_finalization_background(self, session_id: str) -> dict:
        state = await self.session_manager.get_state(session_id)
        if state.get("final_evaluation") and state.get("interview_complete"):
            state["finalization_status"] = "complete"
            state["finalization_error"] = ""
            state["report_ready"] = True
            await self.session_manager.save_state(session_id, state)
            return state

        state["interview_complete"] = True
        state["finalization_status"] = "running"
        state["finalization_error"] = ""
        state["report_ready"] = False
        await self.session_manager.save_state(session_id, state)

        if session_id not in self._finalization_inflight:
            self._finalization_inflight.add(session_id)
            asyncio.create_task(self._finalize_session_worker(session_id))
        return state

    async def _finalize_session_worker(self, session_id: str) -> None:
        try:
            await self.end_session(session_id)
        except Exception as exc:
            try:
                state = await self.session_manager.get_state(session_id)
                state["interview_complete"] = True
                state["finalization_status"] = "failed"
                state["finalization_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                state["report_ready"] = False
                await self.session_manager.save_state(session_id, state)
                await self._trace(
                    session_id,
                    "session_finalization_failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
                external_handoff = state.get("external_handoff") or {}
                handoff_id = str(external_handoff.get("handoff_id") or "")
                if handoff_id:
                    asyncio.create_task(notify_handoff_failed(handoff_id, session_id, str(exc)[:500]))
            except Exception:
                pass
        finally:
            self._finalization_inflight.discard(session_id)

    async def _score_answer_async(
        self,
        session_id: str,
        question: str,
        answer: str,
        *,
        turn_id: str = "",
        turn_number: int = 0,
        route_kind: str = "",
        focus_key: str = "",
        focus_label: str = "",
        sub_focus_key: str = "",
        sub_focus_label: str = "",
        weakness: dict | None = None,
        reasoning: dict | None = None,
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
                    "turn_id": turn_id,
                    "turn_number": turn_number,
                    "question": question[:100],
                    "answer_excerpt": answer[:240],
                    "route_kind": route_kind,
                    "focus_key": focus_key,
                    "focus_label": focus_label,
                    "sub_focus_key": sub_focus_key,
                    "sub_focus_label": sub_focus_label,
                    "score": score.get("score", 0),
                    "breakdown": score.get("breakdown", {}),
                    "confidence": score.get("confidence", 0.0),
                    "weakness_type": weakness.get("type") if isinstance(weakness, dict) else "",
                    "weakness_severity": weakness.get("severity") if isinstance(weakness, dict) else "",
                    "reasoning_structure_score": reasoning.get("structure_score") if isinstance(reasoning, dict) else None,
                    "reasoning_adaptability": reasoning.get("adaptability") if isinstance(reasoning, dict) else "",
                })
        except Exception:
            pass

    async def _extract_implementation_anchor(
        self,
        session_id: str,
        phase2_text: str,
        state: dict,
    ) -> str | None:
        """Extract the strongest grounded transfer anchor from Phase 2 narration."""
        if not phase2_text or len(phase2_text.split()) < 10:
            return None
        from backend.models.llm_router import LLMRouter
        llm = LLMRouter(tier="small")
        prompt = (
            "From the following interview response, extract the strongest grounded transfer anchor "
            "for an application-transfer question. Prefer live evidence: a decision, metric, "
            "product/technical tradeoff, system behavior, role-relevant scope, or explicit ownership "
            "only when the candidate actually stated it. Do not make ownership the main criterion. "
            "Do not invent hidden implementation details. If ownership is unclear, phrase it as "
            "the work or claim they discussed rather than what they personally built. Return one sentence. "
            "If no concrete grounded transfer anchor exists, "
            f"return empty string.\n\nCandidate said:\n{phase2_text[:1200]}"
        )
        try:
            result = await llm.call(system="You extract grounded transfer anchors from interview responses without adding unsupported implementation assumptions.", user=prompt, max_tokens=150)
            text = result if isinstance(result, str) else str(result)
            text = text.strip().strip('"').strip()
            if re.search(
                r"\b(no specific implementation|contains no specific|provided no specific|no concrete technical|no implementation detail|lack of concrete)\b",
                text,
                flags=re.IGNORECASE,
            ):
                return None
            return text if len(text) > 20 else None
        except Exception as e:
            print(f"[Orchestrator] _extract_implementation_anchor failed: {e}")
            raise

    def _select_resume_application_anchor(self, state: dict, current_focus_key: str = "") -> dict:
        """
        Select a role-relevant map/resume anchor only after the primary live-answer
        application-transfer path has failed. This is not a deterministic question
        fallback; it only chooses the claim that the LLM must transfer from.
        """
        interview_map = state.get("interview_trajectory_map") or {}
        focus_areas = interview_map.get("focus_areas") or []
        if not isinstance(focus_areas, list):
            focus_areas = []

        target_role = str(state.get("target_role") or "").lower()
        role_terms = {
            token for token in re.findall(r"[a-z0-9]+", target_role)
            if len(token) > 2 and token not in {"the", "and", "for", "with", "role"}
        }
        current_focus_key = str(current_focus_key or "").strip()

        scored: list[tuple[float, int, dict]] = []
        for index, area in enumerate(focus_areas):
            if not isinstance(area, dict):
                continue
            focus_key = str(area.get("focus_key") or "").strip()
            if not focus_key or focus_key in {"general", "general_background", "general background"}:
                continue
            label = str(area.get("label") or focus_key).strip()
            anchor_context = str(area.get("anchor_context") or "").strip()
            opener = _track_opener(area)
            snippets = [str(s).strip() for s in (area.get("resume_snippets") or []) if str(s).strip()]
            haystack = " ".join([label, anchor_context, opener, *snippets]).lower()
            score = 0.0
            # Current focus is useful context, but it must not overpower the
            # map-authored role relevance and coverage value.
            if focus_key == current_focus_key:
                score += 1.0
            score += max(0, 4 - index) * 0.75
            if str(area.get("track_source") or area.get("source") or "").lower() == "llm":
                score += 2.0
            score += min(len(_track_dimensions(area)), 5) * 0.4
            score += sum(1.0 for term in role_terms if term in haystack)
            sub_focuses = area.get("sub_focuses") or []
            if isinstance(sub_focuses, list) and sub_focuses:
                role_weights: list[float] = []
                coverage_values: list[float] = []
                for surface in sub_focuses:
                    if not isinstance(surface, dict):
                        continue
                    try:
                        role_weights.append(float(surface.get("role_relevance_weight") or surface.get("role_relevance") or 1.5))
                    except (TypeError, ValueError):
                        role_weights.append(1.5)
                    try:
                        coverage_values.append(float(surface.get("coverage_value") or surface.get("priority_weight") or 1.5))
                    except (TypeError, ValueError):
                        coverage_values.append(1.5)
                if role_weights:
                    score += max(0.0, min(3.0, max(role_weights))) * 1.4
                    if max(role_weights) < 1.5:
                        score -= 1.5
                if coverage_values:
                    score += max(0.0, min(3.0, max(coverage_values))) * 1.2
                    if max(coverage_values) < 1.5:
                        score -= 1.0
            if any(char.isdigit() for char in haystack):
                score += 1.0
            scored.append((score, -index, area))

        if not scored:
            parsed_resume = state.get("parsed_resume") or {}
            claims = []
            for claim in parsed_resume.get("claims") or []:
                if isinstance(claim, dict):
                    text = str(claim.get("text") or "").strip()
                    if text:
                        claims.append(text)
                elif isinstance(claim, str) and claim.strip():
                    claims.append(claim.strip())
            if claims:
                return {
                    "anchor": claims[0],
                    "candidate_domain": state.get("target_role", ""),
                    "resume_snippets": claims[:5],
                    "focus_key": "",
                    "focus_label": "Resume claim fallback",
                    "anchor_source": "resume_focus_fallback",
                }
            return {}

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        area = scored[0][2]
        label = str(area.get("label") or area.get("focus_key") or "resume focus").strip()
        snippets = [str(s).strip() for s in (area.get("resume_snippets") or []) if str(s).strip()]
        anchor_parts = [
            label,
            str(area.get("anchor_context") or "").strip(),
            _track_opener(area),
        ]
        anchor = " — ".join(part for part in anchor_parts if part)
        if snippets:
            anchor = f"{anchor}\nEvidence snippets:\n" + "\n".join(f"- {s}" for s in snippets[:3])
        return {
            "anchor": anchor[:1600],
            "candidate_domain": label,
            "resume_snippets": snippets[:5],
            "focus_key": str(area.get("focus_key") or ""),
            "focus_label": label,
            "anchor_source": "resume_focus_fallback",
        }

    async def _generate_application_transfer(
        self,
        session_id: str,
        state: dict,
        *,
        allow_resume_anchor_fallback: bool = False,
        current_focus_key: str = "",
    ) -> None:
        """Background task: generate application transfer question + coverage map."""
        try:
            cs = state.get("candidate_state") or {}
            anchor = cs.get("implementation_anchor")
            anchor_source = "live_answer"
            fallback_anchor = {}
            if not anchor:
                if not allow_resume_anchor_fallback:
                    return
                fallback_anchor = self._select_resume_application_anchor(state, current_focus_key=current_focus_key)
                anchor = fallback_anchor.get("anchor")
                if not anchor:
                    return
                anchor_source = fallback_anchor.get("anchor_source", "resume_focus_fallback")

            from backend.agents.application_agent import ApplicationAgent
            agent = ApplicationAgent()
            parsed_resume = state.get("parsed_resume") or {}
            resume_snippets = []
            for claim in (parsed_resume.get("claims") or [])[:5]:
                if isinstance(claim, dict):
                    t = claim.get("text", "").strip()
                    if t:
                        resume_snippets.append(t)
                elif isinstance(claim, str) and claim.strip():
                    resume_snippets.append(claim.strip())
            if fallback_anchor.get("resume_snippets"):
                resume_snippets = list(fallback_anchor.get("resume_snippets") or []) + resume_snippets

            target_role = str(state.get("target_role") or "").strip()
            _candidate_domain = " / ".join(
                part for part in [
                    target_role,
                    str(fallback_anchor.get("candidate_domain") or "").strip(),
                ]
                if part
            )
            if not _candidate_domain:
                _history = state.get("history", [])
                for _h in reversed(_history):
                    if _h.get("focus_label") or _h.get("focus_key"):
                        _candidate_domain = str(_h.get("focus_label") or _h.get("focus_key") or "")
                        break

            coverage_map = await agent.generate(
                implementation_anchor=anchor,
                candidate_domain=_candidate_domain,
                target_role=state.get("target_role", ""),
                years_experience=state.get("years_experience", "mid"),
                resume_snippets=resume_snippets,
                anchor_source=anchor_source,
            )
            fresh_state = await self.session_manager.get_state(session_id)
            if _application_transfer_served(fresh_state):
                await self._trace(
                    session_id,
                    "application_transfer_generation_discarded_after_served",
                    anchor_source=anchor_source,
                    dims=len(coverage_map.dimensions),
                )
                return
            if not fresh_state.get("interview_complete"):
                if anchor_source == "resume_focus_fallback":
                    fresh_state.setdefault("candidate_state", {})["implementation_anchor"] = anchor
                    fresh_state.setdefault("candidate_state", {})["anchor_confidence"] = "fallback_resume_claim"
                    fresh_state["application_transfer_anchor_source"] = anchor_source
                    fresh_state["application_transfer_fallback_focus_key"] = fallback_anchor.get("focus_key", "")
                    fresh_state["application_transfer_fallback_focus_label"] = fallback_anchor.get("focus_label", "")
                fresh_state["coverage_map"] = coverage_map.to_dict()
                fresh_state["prepped_application_question"] = coverage_map.application_question
                arc = _ensure_application_transfer_arc(fresh_state)
                arc["grounding_needed"] = bool(coverage_map.grounding_needed and coverage_map.grounding_question)
                arc["grounding_question"] = coverage_map.grounding_question if arc["grounding_needed"] else ""
                arc["max_depth_level"] = coverage_map.max_depth_level
                arc["depth_allowed_terms"] = list(coverage_map.depth_allowed_terms or [])[:12]
                fresh_state["application_transfer_arc"] = arc
                repair_verification = getattr(agent, "last_repair_verification", {}) or {}
                if isinstance(repair_verification, dict):
                    fresh_state["application_transfer_repair_verification"] = repair_verification
                fresh_state.pop("application_transfer_error", None)
                await self.session_manager.save_state(session_id, fresh_state)
                print(f"[AppTransfer] Coverage map staged for {session_id} — {len(coverage_map.dimensions)} dims")
                await self._trace(session_id, "application_transfer_staged",
                                  dims=len(coverage_map.dimensions),
                                  anchor_chars=len(anchor),
                                  anchor_source=anchor_source,
                                  repair_attempted=bool(repair_verification.get("repair_attempted")) if isinstance(repair_verification, dict) else False,
                                  repair_accepted=repair_verification.get("repair_accepted") if isinstance(repair_verification, dict) else None,
                                  repair_attempts=len(repair_verification.get("attempts") or []) if isinstance(repair_verification, dict) else 0)
        except Exception as e:
            print(f"[Orchestrator] Application transfer generation failed: {e}")
            try:
                fresh_state = await self.session_manager.get_state(session_id)
                fresh_state["application_transfer_error"] = f"{type(e).__name__}: {str(e)[:300]}"
                await self.session_manager.save_state(session_id, fresh_state)
            except Exception:
                pass
            raise

    async def _generate_live_q4_candidates(
        self, session_id: str, q3_answer: str, state: dict
    ) -> None:
        """Generate 1-2 live Q4 candidates anchored to what the candidate said in Q3."""
        try:
            focus_areas = (state.get("interview_map") or {}).get("focus_areas") or []
            primary_anchor = ""
            if focus_areas:
                primary_anchor = (focus_areas[0].get("anchor_context") or "").strip()

            target_role = state.get("target_role", "")
            from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter
            prompt = (
                f"You are generating adaptive follow-up questions for a technical interview.\n\n"
                f"Role: {target_role}\n"
                f"Resume anchor claim: {primary_anchor}\n\n"
                f"The candidate just answered the opening question. They said:\n{q3_answer}\n\n"
                f"Generate 2 targeted follow-up questions for the Q4 slot. Rules:\n"
                f"- Each question must reference something SPECIFIC the candidate just said (a number, system name, approach, or claim they made)\n"
                f"- Each question must follow this pattern: [specific thing they said] + [consequence, challenge, or probe]\n"
                f"- Questions must sound like a senior practitioner asking them — not an AI\n"
                f"- Do NOT ask memory questions ('what was the first...'), do NOT name solutions ('did you use caching?')\n"
                f"- One question should probe depth of what they described; one should probe a gap or assumption in what they said\n"
                f"- Max 35 words each\n\n"
                f"Return JSON: {{\"live_q4_candidates\": [\"question 1\", \"question 2\"]}}"
            )
            raw = await LLMRouter(tier="small").call(
                system="You generate precise, human-sounding follow-up interview questions.",
                user=prompt,
                max_tokens=300,
                response_format=JSON_OBJECT_FORMAT,
            )
            if not isinstance(raw, dict):
                raise RuntimeError("Live Q4 generation returned non-JSON output.")
            candidates = raw.get("live_q4_candidates") or []
            if not candidates:
                raise RuntimeError("Live Q4 generation returned no candidates.")
            current_state = await self.session_manager.get_state(session_id)
            current_state["live_q4_candidates"] = [str(c) for c in candidates[:2]]
            await self.session_manager.save_state(session_id, current_state)
        except Exception as e:
            print(f"[Orchestrator] Live Q4 generation failed: {e}")
            raise

    async def _evaluate_coverage_dimension(
        self,
        dimension_id: str,
        coverage_map_dict: dict,
        candidate_response: str,
    ) -> tuple[str, str | None]:
        """
        Returns (coverage_state, recovery_depth).
        coverage_state: "voluntary" | "recovered_deep" | "recovered_surface" | "missed" | "incorrect"
        recovery_depth: "deep" | "surface" | None
        """
        from backend.models.coverage_map import AnswerCoverageMap
        from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter
        cmap = AnswerCoverageMap.from_dict(coverage_map_dict)
        dim = next((d for d in cmap.dimensions if d.id == dimension_id), None)
        if not dim:
            return "missed", None

        llm = LLMRouter(tier="small")
        approaches = ", ".join(dim.expected_approaches[:3]) if dim.expected_approaches else "any valid approach"
        prompt = (
            f"Interview dimension: {dim.label}\n"
            f"Description: {dim.description}\n"
            f"Expected approaches (any of these count): {approaches}\n\n"
            f"Candidate response: {candidate_response[:600]}\n\n"
            "Did the candidate address this dimension?\n"
            "- full: addressed with specific reasoning, mechanism, or concrete operating detail\n"
            "- partial: named the concept but did not explain it concretely\n"
            "- not_covered: didn't address it at all when prompted\n"
            "- incorrect: addressed it but with a conceptual error\n"
            "Use semantic matching — different terminology is fine if the concept is correct.\n"
            'Return JSON: {"coverage": "full|partial|not_covered|incorrect", "reason": "one line"}'
        )
        try:
            result = await llm.call(
                system="You evaluate whether a candidate's answer addresses a specific technical dimension.",
                user=prompt,
                max_tokens=100,
                response_format=JSON_OBJECT_FORMAT,
            )
            if not isinstance(result, dict):
                raise RuntimeError("Coverage dimension evaluator returned non-JSON output.")
            coverage = result.get("coverage", "not_covered")
        except Exception:
            raise

        state_map: dict[str, tuple[str, str | None]] = {
            "full":        ("recovered_deep",    "deep"),
            "partial":     ("recovered_surface", "surface"),
            "not_covered": ("missed",            None),
            "incorrect":   ("incorrect",         None),
        }
        return state_map.get(coverage, ("missed", None))

    async def _evaluate_application_coverage(
        self,
        coverage_map_dict: dict,
        candidate_response: str,
    ) -> dict[str, str]:
        """
        Classify the application-transfer answer against all dimensions in one call.
        Returns dimension_id -> coverage_state, with full answers marked voluntary.
        """
        from backend.models.coverage_map import AnswerCoverageMap
        from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter

        cmap = AnswerCoverageMap.from_dict(coverage_map_dict)
        if not cmap.dimensions:
            return {}

        dimensions_payload = [
            {
                "id": d.id,
                "label": d.label,
                "description": d.description,
                "expected_approaches": d.expected_approaches[:3],
            }
            for d in cmap.dimensions
        ]
        prompt = (
            "The candidate just answered an application-transfer question.\n"
            "Classify which expected dimensions they addressed without being prompted dimension-by-dimension.\n\n"
            f"Application question: {cmap.application_question}\n"
            f"Grounded transfer anchor: {cmap.implementation_anchor}\n"
            f"Dimensions: {dimensions_payload}\n\n"
            f"Candidate response:\n{candidate_response[:1400]}\n\n"
            "For each dimension, classify coverage as:\n"
            "- full: addressed with specific reasoning, mechanism, or concrete operating detail\n"
            "- partial: gestured at the concept but did not explain it concretely\n"
            "- not_covered: did not address it\n"
            "- incorrect: addressed it with a conceptual error\n"
            'Return JSON only: {"dimensions":[{"id":"...","coverage":"full|partial|not_covered|incorrect"}]}'
        )
        try:
            result = await LLMRouter(tier="small").call(
                system="You evaluate coverage of an interview answer against expected dimensions.",
                user=prompt,
                max_tokens=700,
                response_format=JSON_OBJECT_FORMAT,
            )
            if not isinstance(result, dict):
                raise RuntimeError("Application coverage evaluator returned non-JSON output.")
            rows = result.get("dimensions") or []
            if not isinstance(rows, list):
                raise RuntimeError("Application coverage evaluator returned invalid dimensions list.")
        except Exception:
            raise

        mapped: dict[str, str] = {}
        state_map = {
            "full": "voluntary",
            # Application-transfer answers are the baseline pass. If the answer
            # only gestures at a dimension or misses it, leave it available for
            # a later explicit surfacing question instead of marking it missed.
            "partial": "not_evaluated",
            "not_covered": "not_evaluated",
            "incorrect": "incorrect",
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            dim_id = str(row.get("id", "")).strip()
            coverage = str(row.get("coverage", "not_covered")).strip()
            if dim_id:
                mapped[dim_id] = state_map.get(coverage, "missed")
        return mapped

    # ─────────────────────────────────────────────
    # REAL-TIME TRANSCRIPT HANDLING
    # ─────────────────────────────────────────────

    async def on_partial_transcript(
        self,
        session_id: str,
        text: str,
        entities: list[str] | None = None,
        turn_id: str = "",
        is_final: bool = True,
        snapshot_seq: int = 0,
    ):
        """
        Fires on throttled live transcript snapshots while the candidate is speaking.

        Two jobs:
        1. Entity accumulation — merged into full turn at handle_transcript time
        2. Speculative question generation (event-driven, Haiku only):
           - New entity detected → generate entity-anchored follow-up
           - Admission/gap signal detected → generate exploratory pivot question
           - Longer rolling transcript snapshot → refresh the "best available so far"
             speculative follow-up while the candidate is still talking
           NO canonical state written here. Codex invariant holds.
        """
        if not turn_id or not text:
            return

        cleaned = text.strip()
        if not cleaned:
            return

        snapshot_meta = self._partial_snapshot_meta.get(session_id)
        if snapshot_meta and snapshot_meta.get("turn_id") == turn_id:
            last_seq = int(snapshot_meta.get("snapshot_seq", 0) or 0)
            if snapshot_seq and snapshot_seq < last_seq:
                await self._trace(
                    session_id,
                    "partial_snapshot_dropped_stale",
                    turn_id=turn_id,
                    snapshot_seq=snapshot_seq,
                    last_snapshot_seq=last_seq,
                    is_final=is_final,
                    level="warn",
                )
                return

        self._partial_snapshot_meta[session_id] = {
            "turn_id": turn_id,
            "snapshot_seq": snapshot_seq,
            "is_final": is_final,
            "transcript_chars": len(cleaned),
        }

        existing = self._partial_entities.get(session_id, set())

        new_entities: set[str] = set()
        if entities:
            new_entities = set(entities) - existing
            existing.update(entities)
            self._partial_entities[session_id] = existing

        admission = _looks_like_admission(cleaned)

        # Fire speculative if:
        # a) new named entity detected, OR
        # b) admission/gap signal, OR
        # c) rolling transcript has enough substance to ground a better follow-up
        #    — covers the common case where Deepgram NER misses technical jargon
        word_count = len(cleaned.split())
        periodic_trigger_words = 16 if not is_final else 20
        periodic_trigger = word_count >= periodic_trigger_words and not admission and not new_entities

        if new_entities or admission or periodic_trigger:
            asyncio.create_task(
                self._run_speculative_generation(
                    session_id=session_id,
                    partial_text=cleaned,
                    new_entities=new_entities,
                    admission=admission,
                    turn_id=turn_id,
                    is_final=is_final,
                    snapshot_seq=snapshot_seq,
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
          2. Serve fast response (prepped probe → bank follow-up → map-backed question)
          3. Update canonical counters
          4. Kick off background pipeline (runs during candidate's next answer)
          5. Return immediately
        """
        started_at = time.perf_counter()
        state = await self.session_manager.get_state(session_id)
        await self._trace(
            session_id,
            "fasttrack_start",
            turn_id=turn_id,
            transcript_chars=len(text),
            transcript_words=len(text.split()),
            entities_count=len(entities or []),
            question_count=state.get("question_count", 0),
            sprint=state.get("current_sprint", 1),
        )

        if state.get("interview_complete"):
            return {"response": "The interview has concluded. Thank you.", "complete": True, "turn_id": turn_id}

        if (
            state.get("application_transfer_error")
            and not _application_transfer_served(state)
            and _evidence_question_count(state) >= 5
        ):
            if _application_anchor_recovery_ready(state):
                pass
            elif not state.get("application_transfer_fallback_attempted"):
                state["application_transfer_fallback_attempted"] = True
                await self.session_manager.save_state(session_id, state)
                agenda = ensure_interview_agenda(state)
                await self._generate_application_transfer(
                    session_id,
                    state,
                    allow_resume_anchor_fallback=True,
                    current_focus_key=str(agenda.get("current_focus_key") or ""),
                )
                state = await self.session_manager.get_state(session_id)
            if _application_anchor_recovery_ready(state):
                pass
            elif not _application_transfer_ready(state) and not _application_grounding_ready(state):
                raise RuntimeError(
                    "Application transfer failed before the agenda deadline: "
                    f"{str(state.get('application_transfer_error'))[:300]}"
                )
        if (
            not _application_transfer_served(state)
            and not state.get("prepped_application_question")
            and _evidence_question_count(state) >= 5
            and not state.get("application_transfer_floor_recovery_attempted")
        ):
            state["application_transfer_floor_recovery_attempted"] = True
            await self.session_manager.save_state(session_id, state)
            agenda = ensure_interview_agenda(state)
            await self._trace(
                session_id,
                "application_transfer_floor_recovery_started",
                evidence_question_count=_evidence_question_count(state),
                current_focus_key=str(agenda.get("current_focus_key") or ""),
            )
            await self._generate_application_transfer(
                session_id,
                state,
                allow_resume_anchor_fallback=True,
                current_focus_key=str(agenda.get("current_focus_key") or ""),
            )
            state = await self.session_manager.get_state(session_id)
        is_turn_revision = bool(turn_id and turn_id == state.get("current_answer_turn_id"))
        current_answer_version = (
            state.get("current_answer_version", 0) + 1
            if is_turn_revision
            else 1
        )
        latest_turn_versions = dict(state.get("latest_turn_versions", {}))
        if turn_id:
            latest_turn_versions[turn_id] = current_answer_version

        # Merge entities from partial accumulation
        accumulated = self._partial_entities.pop(session_id, set())
        partial_snapshot_meta = self._partial_snapshot_meta.get(session_id)
        if partial_snapshot_meta and partial_snapshot_meta.get("turn_id") == turn_id:
            self._partial_snapshot_meta.pop(session_id, None)
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
            await self._trace(
                session_id,
                "fasttrack_echo_guard",
                turn_id=turn_id,
                route_kind="echo_guard",
                transcript_chars=len(text),
                question_chars=len(last_question),
                level="warn",
            )
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
                "route_kind": "echo_guard",
                "turn_id": turn_id,
            }

        # Skip / social-deflection detection — runs before consuming staged analysis
        _candidate_state_snap = dict(state.get("candidate_state") or {})
        if _looks_like_skip_request(text):
            _candidate_state_snap["explicit_skip_count"] = _candidate_state_snap.get("explicit_skip_count", 0) + 1
            _candidate_state_snap["disengagement_level"] = min(
                5.0, _candidate_state_snap.get("disengagement_level", 0.0) + 2.0
            )
            state["candidate_state"] = _candidate_state_snap
            state["_force_focus_rotation"] = True
            await self.session_manager.save_state(session_id, state)
            await self._trace(
                session_id,
                "fasttrack_skip_detected",
                turn_id=turn_id,
                skip_count=_candidate_state_snap["explicit_skip_count"],
            )
        elif bool(_SOCIAL_DEFLECTION_SIGNALS.search(text)):
            _candidate_state_snap["social_deflection_count"] = _candidate_state_snap.get("social_deflection_count", 0) + 1
            _candidate_state_snap["disengagement_level"] = min(
                5.0, _candidate_state_snap.get("disengagement_level", 0.0) + 1.0
            )
            state["candidate_state"] = _candidate_state_snap
            await self.session_manager.save_state(session_id, state)

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
                "answer_version": legacy_staged.get("answer_version", 1),
                "analysis": legacy_staged,
                "metadata": legacy_metadata,
            })

        ready_items: list[dict] = []
        deferred_items: list[dict] = []
        dropped_superseded = 0
        for item in queue:
            if _is_superseded_staged_item(item, latest_turn_versions):
                print(
                    f"[FastTrack] Dropping superseded staged analysis for turn_id "
                    f"{item.get('turn_id')} v{_staged_answer_version(item)}"
                )
                dropped_superseded += 1
                continue
            if turn_id and item.get("turn_id") == turn_id:
                deferred_items.append(item)
            else:
                ready_items.append(item)

        for item in sorted(
            ready_items,
            key=lambda queued: (
                queued.get("turn_number", 0),
                _staged_answer_version(queued),
            ),
        ):
            analysis = item.get("analysis", {})
            if analysis.get("session_id") == session_id:
                self._apply_staged_analysis(state, analysis, item.get("metadata", {}))
                applied_turn_id = item.get("turn_id")
                if applied_turn_id:
                    latest_turn_versions.pop(applied_turn_id, None)
        if deferred_items:
            state["prepped_turn_queue"] = deferred_items
        else:
            state.pop("prepped_turn_queue", None)
        await self._trace(
            session_id,
            "fasttrack_stage_consume",
            turn_id=turn_id,
            is_revision=is_turn_revision,
            ready_items=len(ready_items),
            deferred_items=len(deferred_items),
            dropped_superseded=dropped_superseded,
        )

        active_packet = _clone_question_packet(state.get("active_question_packet"))
        if not active_packet and last_question:
            active_packet = _build_question_packet(
                question_text=last_question,
                sprint=sprint,
                route_kind="unknown",
                parsed_resume=parsed_resume,
                resume=resume,
                followups=list(state.get("current_question_followups") or []),
                source_turn_number=max(state.get("question_count", 0), 0),
            )
        answered_route_kind_for_count = str((active_packet or {}).get("route_kind", "") or "")
        if answered_route_kind_for_count == "application_grounding" and not is_turn_revision:
            arc = _ensure_application_transfer_arc(state)
            depth_level, allowed_terms = _infer_grounding_depth(
                text,
                max_depth_level=int(arc.get("max_depth_level") or 3),
            )
            existing_terms = list(arc.get("depth_allowed_terms") or [])
            arc.update({
                "grounding_answer": text[:800],
                "grounding_done": True,
                "confirmed_depth_level": depth_level,
                "depth_allowed_terms": list(dict.fromkeys(existing_terms + allowed_terms))[:12],
            })
            state["application_transfer_arc"] = arc
            state.setdefault("candidate_state", {})["application_transfer_depth_level"] = depth_level
            state.setdefault("candidate_state", {})["application_transfer_depth_terms"] = arc["depth_allowed_terms"]
            await self._trace(
                session_id,
                "application_grounding_answered",
                turn_id=turn_id,
                depth_level=depth_level,
                allowed_terms=arc["depth_allowed_terms"],
            )

        _traj_focus_areas = ((state.get("interview_trajectory_map") or {}).get("focus_areas") or []) or None
        # C-2 fix: propagate focus_key from the active_question_packet when it's already known.
        # The packet was built when the question was staged — it has the authoritative focus_key.
        # Only fall back to _infer_focus() if the packet has no useful focus_key.
        _pkt_focus_key = str(active_packet.get("focus_key") or "") if active_packet else ""
        _pkt_focus_label = str(active_packet.get("focus_label") or "") if active_packet else ""
        _pkt_sub_focus_key = str(active_packet.get("sub_focus_key") or "") if active_packet else ""
        _pkt_sub_focus_label = str(active_packet.get("sub_focus_label") or "") if active_packet else ""
        if _pkt_focus_key and _pkt_focus_key not in ("general", "general_background", "general background"):
            current_focus_key = _pkt_focus_key
            current_focus_label = _pkt_focus_label or _pkt_focus_key
        else:
            current_focus_key, current_focus_label = _infer_focus(last_question, text, parsed_resume, resume, trajectory_focus_areas=_traj_focus_areas)
        if _pkt_sub_focus_key:
            current_sub_focus_key = _pkt_sub_focus_key
            current_sub_focus_label = _pkt_sub_focus_label or _pkt_sub_focus_key
        else:
            current_sub_focus_key, current_sub_focus_label = _infer_sub_focus(
                state.get("interview_trajectory_map", {}),
                current_focus_key,
                last_question,
                text,
            )
        focus_prompt_pack = _build_focus_prompt_pack(
            state.get("interview_trajectory_map", {}),
            focus_key=current_focus_key,
            last_question=last_question,
            answer=text,
            history=state.get("history", []),
        )
        if not is_turn_revision:
            _upsert_turn_skeleton(
                state,
                turn_id=turn_id,
                question=last_question,
                answer=text,
                sprint=sprint,
                persona=persona,
                focus_key=current_focus_key,
                focus_label=current_focus_label,
                sub_focus_key=current_sub_focus_key,
                sub_focus_label=current_sub_focus_label,
                surface_kind=str(active_packet.get("surface_kind") or ""),
                route_kind=active_packet.get("route_kind", "unknown"),
                answer_version=current_answer_version,
                question_posture=str(active_packet.get("question_posture") or ""),
                signal_goal=str(active_packet.get("signal_goal") or ""),
                expected_space=list(active_packet.get("expected_space") or [])[:4],
                covered_expected_space=list(active_packet.get("covered_expected_space") or [])[:4],
                missing_expected_space=list(active_packet.get("missing_expected_space") or active_packet.get("expected_space") or [])[:4],
                coverage_dimension_id=str(active_packet.get("coverage_dimension_id") or ""),
                coverage_dimension_label=str(active_packet.get("coverage_dimension_label") or ""),
            )

        # ── Step 2: Determine fast response ──────────────────────────────────
        # Priority:
        # a) current question packet follow-up — deterministic deepening before topic advance
        # b) prepped_next_packet — background-prepared next main question
        # c) speculative_cache — entity/admission-triggered Haiku question from partials
        # d) fail closed when no LLM/map-authored question exists
        prepped_q = None
        prepped_context: dict = {}
        prepped_packet: dict = {}
        if is_turn_revision:
            prepped_q = state.get("current_answer_response")
            prepped_context = state.get("current_answer_context", {})
        else:
            prepped_q = state.get("prepped_next_question")
            prepped_context = state.get("prepped_next_context", {})
            prepped_packet = _clone_question_packet(state.get("prepped_next_packet"))
            seed_turn_number = state.get("prepped_next_question_turn_number")
            application_already_served = _application_transfer_served(state)
            if str(prepped_context.get("route_kind") or "").strip() == "application_transfer" and application_already_served:
                prepped_q = None
                prepped_context = {}
                prepped_packet = {}
                state.pop("prepped_next_question", None)
                state.pop("prepped_next_question_turn_number", None)
                state.pop("prepped_next_context", None)
                state.pop("prepped_next_packet", None)
            application_anchor_recovery_q = ""
            if _application_anchor_recovery_ready(state):
                application_anchor_recovery_q = _application_anchor_recovery_question(current_focus_label)
            application_q = ""
            application_grounding_q = ""
            if _application_grounding_ready(state):
                application_grounding_q = str(
                    (_ensure_application_transfer_arc(state).get("grounding_question") or _coverage_grounding_question(state))
                ).strip()
            if (
                state.get("prepped_application_question")
                and not application_already_served
                and _application_transfer_ready(state)
            ):
                application_q = str(state.get("prepped_application_question") or "").strip()
            coverage_q = ""
            coverage_route_kind = "coverage_surface"
            coverage_packet_kwargs: dict = {}
            if (
                answered_route_kind_for_count == "application_transfer"
                and _application_transfer_served(state)
                and isinstance(state.get("coverage_map"), dict)
                and _coverage_route_allowed(
                    state,
                    current_focus_key=current_focus_key,
                    current_focus_label=current_focus_label,
                )
            ):
                from backend.models.coverage_map import AnswerCoverageMap as _ACMap

                _cmap = _ACMap.from_dict(state["coverage_map"])
                _unsurfaced = _cmap.unsurfaced_dimensions()
                if _unsurfaced:
                    _unsurfaced.sort(key=lambda _d: _d.weight, reverse=True)
                    _next_dim = _unsurfaced[0]
                    _next_dim.surfacing_attempted = True
                    agenda_state = ensure_interview_agenda(state)
                    agenda_state["phase"] = "coverage_surface"
                    agenda_state["coverage_opening_count"] = int(agenda_state.get("coverage_opening_count") or 0) + 1
                    agenda_state["last_route_reason"] = "fast_coverage_after_application_transfer"
                    state["interview_agenda"] = agenda_state
                    arc = _ensure_application_transfer_arc(state)
                    arc["surface_count"] = int(arc.get("surface_count") or 0) + 1
                    state["application_transfer_arc"] = arc
                    state["_last_coverage_dim_id"] = _next_dim.id
                    state["_last_coverage_recovery_depth"] = None
                    state["coverage_map"] = _cmap.to_dict()
                    coverage_q = await self.followup_agent.generate_coverage_surface(
                        dimension_id=_next_dim.id,
                        coverage_map=_cmap,
                        state=state,
                    )
                    coverage_packet_kwargs = {
                        "coverage_dimension_id": _next_dim.id,
                        "coverage_dimension_label": _next_dim.label,
                        "question_posture": "explore",
                        "signal_goal": f"Surface application-transfer coverage: {_next_dim.label}",
                        "expected_space": list(_next_dim.expected_approaches or [])[:4],
                    }
                else:
                    _depth_dim_dict = _select_earned_coverage_depth_dimension(_cmap.to_dict(), state)
                    _depth_dim = None
                    if _depth_dim_dict:
                        _depth_id = str(_depth_dim_dict.get("id") or _depth_dim_dict.get("dimension_id") or "").strip()
                        _depth_dim = next((_d for _d in _cmap.dimensions if _d.id == _depth_id), None)
                    if _depth_dim is not None:
                        _mark_coverage_depth_probe(state, _cmap, _depth_dim)
                        coverage_q = await self.followup_agent.generate_coverage_depth_probe(
                            dimension_id=_depth_dim.id,
                            coverage_map=_cmap,
                            candidate_surface_response=_depth_dim.candidate_response or text,
                            state=state,
                        )
                        coverage_route_kind = "coverage_depth_probe"
                        coverage_packet_kwargs = {
                            "coverage_dimension_id": _depth_dim.id,
                            "coverage_dimension_label": _depth_dim.label,
                            "question_posture": "pressure",
                            "signal_goal": f"Light depth check for application-transfer coverage: {_depth_dim.label}",
                            "expected_space": list(_depth_dim.expected_approaches or [])[:4],
                        }

            closing_started = (
                _is_close_route(active_packet.get("route_kind"))
                or _synthesis_close_count(state.get("history", [])) > 0
                or _is_close_route(prepped_context.get("route_kind"))
            )
            if coverage_q:
                closing_started = False
            if closing_started and not _is_close_route(prepped_context.get("route_kind")):
                close_count = _synthesis_close_count(state.get("history", []))
                prepped_q = await self.followup_agent.generate_graceful_close(state, close_count)
                prepped_context = {
                    "pivoting": True,
                    "route_kind": "graceful_exit" if close_count else "synthesis_close",
                    "weakness": None,
                    "discrepancy": None,
                }
                prepped_packet = _build_question_packet(
                    question_text=prepped_q,
                    sprint=sprint,
                    route_kind=prepped_context["route_kind"],
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    pivoting=True,
                    source_turn_number=state.get("question_count", 0),
                    focus_key_override=current_focus_key,
                    focus_label_override=current_focus_label,
                )
                application_q = ""
                print(f"[FastTrack] Closing flow protected from map/generic promotion for {session_id}")

            if prepped_q and seed_turn_number == 0:
                if not _seed_relevant_to_answer(prepped_q, text, entities or [], parsed_resume, resume):
                    print(f"[FastTrack] Seed discarded — topic mismatch with first answer for {session_id}")
                    prepped_q = None
                    prepped_context = {}
                    prepped_packet = {}
            if (
                not closing_started
                and not application_anchor_recovery_q
                and not application_grounding_q
                and not application_q
                and not coverage_q
                and seed_turn_number == 0
                and current_focus_key not in ("general", "general background")
            ):
                trajectory_seed = select_from_trajectory_map_detailed(
                    state.get("interview_trajectory_map", {}),
                    sprint=sprint,
                    focus_key=current_focus_key,
                    answer=text,
                    entities=entities or [],
                    history=state.get("history", []),
                    admission=_looks_like_admission(text),
                    has_discrepancy=False,
                )
                if trajectory_seed:
                    trajectory_question = trajectory_seed["question"]
                    trajectory_route_kind = trajectory_seed["route_kind"]
                    trajectory_focus_key = trajectory_seed["focus_key"]
                    trajectory_focus_label = trajectory_seed["focus_label"]
                    seeded_focus_key, _ = _infer_focus(prepped_q or "", "", parsed_resume, resume)
                    if trajectory_focus_key == current_focus_key and seeded_focus_key != current_focus_key:
                        prepped_q = trajectory_question
                        prepped_context = {
                            "pivoting": trajectory_route_kind == "trajectory_map_bridge",
                            "route_kind": trajectory_route_kind,
                            "weakness": None,
                            "discrepancy": None,
                        }
                        prepped_packet = _build_question_packet(
                            question_text=prepped_q,
                            sprint=sprint,
                            route_kind=trajectory_route_kind,
                            parsed_resume=parsed_resume,
                            resume=resume,
                            followups=[],
                            pivoting=trajectory_route_kind == "trajectory_map_bridge",
                            source_turn_number=state.get("question_count", 0),
                            focus_key_override=trajectory_focus_key,
                            focus_label_override=trajectory_focus_label,
                            **_question_packet_ladder_kwargs(trajectory_seed),
                        )
                        print(f"[FastTrack] Trajectory map replaced seed for {session_id}")

        pivoting = prepped_context.get("pivoting", False)
        served_route_kind = prepped_context.get("route_kind")
        served_weakness: dict | None = None
        served_discrepancy: dict | None = None

        spec = state.get("speculative_cache", {})
        if spec.get("turn_id") and spec.get("turn_id") != turn_id:
            state["speculative_cache"] = {}
            spec = {}

        admission = _looks_like_admission(text)
        trajectory_admission = None
        if not is_turn_revision and admission and not locals().get("closing_started"):
            trajectory_admission = select_from_trajectory_map_detailed(
                state.get("interview_trajectory_map", {}),
                sprint=sprint,
                focus_key=current_focus_key,
                answer=text,
                entities=entities or [],
                history=state.get("history", []),
                admission=True,
                has_discrepancy=bool(served_discrepancy),
                branch_hint="if_honest_gap",
            )

        current_packet_followups = _packet_followups_remaining(active_packet)
        should_use_packet_followup = (
            not is_turn_revision
            and not bool(locals().get("closing_started"))
            and bool(current_packet_followups)
            and not active_packet.get("pivoting")
            and not trajectory_admission
            and not bool(locals().get("application_anchor_recovery_q"))
            and not bool(locals().get("application_grounding_q"))
            and not bool(locals().get("application_q"))
            and not bool(locals().get("coverage_q"))
            and _should_prioritize_bank_followup(prepped_context, current_packet_followups, active_packet)
        )

        if should_use_packet_followup:
            raw_followup = current_packet_followups[0]
            fast_response = await self.followup_agent.adapt_followup(
                raw_followup=raw_followup,
                question=last_question,
                answer=text,
                persona=persona,
                resume_context=resume_context,
                focus_context=focus_prompt_pack.get("prompt_context", ""),
                resume_snippets=focus_prompt_pack.get("resume_snippets", []),
            )
            active_packet["asked_followup_count"] = active_packet.get("asked_followup_count", 0) + 1
            active_packet["question_text"] = fast_response
            active_packet["route_kind"] = "bank_followup_fast"
            served_weakness = None
            served_discrepancy = None
            served_route_kind = "bank_followup_fast"
            pivoting = False
            print(f"[FastTrack] Active-packet follow-up served for {session_id}")

        else:
            if locals().get("application_anchor_recovery_q"):
                prepped_q = application_anchor_recovery_q
                prepped_context = {
                    "pivoting": False,
                    "route_kind": "application_anchor_recovery",
                    "weakness": None,
                    "discrepancy": None,
                }
                prepped_packet = _build_question_packet(
                    question_text=prepped_q,
                    sprint=sprint,
                    route_kind="application_anchor_recovery",
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    source_turn_number=state.get("question_count", 0),
                    focus_key_override=current_focus_key,
                    focus_label_override=current_focus_label,
                    question_posture="clarify",
                    signal_goal="Recover one grounded transfer anchor from vague early answers before using resume fallback.",
                    expected_space=["decision", "metric", "tradeoff", "personal contribution"],
                    information_gain="high",
                    voice_complexity="low",
                )
                served_route_kind = "application_anchor_recovery"
                pivoting = False
                state["application_anchor_recovery_served"] = True
                state.pop("prepped_next_question", None)
                state.pop("prepped_next_question_turn_number", None)
                state.pop("prepped_next_context", None)
                state.pop("prepped_next_packet", None)
                print(f"[FastTrack] Application-transfer anchor recovery promoted for {session_id}")

            elif locals().get("application_grounding_q"):
                prepped_q = application_grounding_q
                prepped_context = {
                    "pivoting": False,
                    "route_kind": "application_grounding",
                    "weakness": None,
                    "discrepancy": None,
                }
                _coverage_focus = str(
                    state.get("application_transfer_fallback_focus_key")
                    or current_focus_key
                    or ""
                ).strip()
                _coverage_label = str(
                    state.get("application_transfer_fallback_focus_label")
                    or current_focus_label
                    or "Application Transfer"
                ).strip()
                prepped_packet = _build_question_packet(
                    question_text=prepped_q,
                    sprint=sprint,
                    route_kind="application_grounding",
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    source_turn_number=state.get("question_count", 0),
                    focus_key_override=_coverage_focus,
                    focus_label_override=_coverage_label,
                    question_posture="clarify",
                    signal_goal="Calibrate which depth layer the candidate actually worked at before application transfer.",
                    expected_space=["decision/framing", "operating workflow", "specialized internals", "something else"],
                )
                served_route_kind = "application_grounding"
                pivoting = False
                arc = _ensure_application_transfer_arc(state)
                arc["grounding_served"] = True
                state["application_transfer_arc"] = arc
                state.pop("prepped_next_question", None)
                state.pop("prepped_next_question_turn_number", None)
                state.pop("prepped_next_context", None)
                state.pop("prepped_next_packet", None)
                print(f"[FastTrack] Application-transfer grounding promoted for {session_id}")

            elif locals().get("application_q"):
                prepped_q = application_q
                prepped_context = {
                    "pivoting": False,
                    "route_kind": "application_transfer",
                    "weakness": None,
                    "discrepancy": None,
                }
                _coverage_focus = str(
                    state.get("application_transfer_fallback_focus_key")
                    or current_focus_key
                    or ""
                ).strip()
                _coverage_label = str(
                    state.get("application_transfer_fallback_focus_label")
                    or current_focus_label
                    or "Application Transfer"
                ).strip()
                prepped_packet = _build_question_packet(
                    question_text=prepped_q,
                    sprint=sprint,
                    route_kind="application_transfer",
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    source_turn_number=state.get("question_count", 0),
                    focus_key_override=_coverage_focus,
                    focus_label_override=_coverage_label,
                )
                served_route_kind = "application_transfer"
                pivoting = False
                state["application_question_served"] = True
                arc = _ensure_application_transfer_arc(state)
                arc["main_transfer_served"] = True
                state["application_transfer_arc"] = arc
                state.pop("prepped_application_question", None)
                state.pop("prepped_next_question", None)
                state.pop("prepped_next_question_turn_number", None)
                state.pop("prepped_next_context", None)
                state.pop("prepped_next_packet", None)
                print(f"[FastTrack] Application-transfer question promoted for {session_id}")

            elif locals().get("coverage_q"):
                prepped_q = coverage_q
                prepped_context = {
                    "pivoting": False,
                    "route_kind": coverage_route_kind,
                    "weakness": None,
                    "discrepancy": None,
                }
                prepped_packet = _build_question_packet(
                    question_text=prepped_q,
                    sprint=sprint,
                    route_kind=coverage_route_kind,
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    source_turn_number=state.get("question_count", 0),
                    focus_key_override=current_focus_key,
                    focus_label_override=current_focus_label,
                    **coverage_packet_kwargs,
                )
                served_route_kind = coverage_route_kind
                pivoting = False
                state.pop("prepped_next_question", None)
                state.pop("prepped_next_question_turn_number", None)
                state.pop("prepped_next_context", None)
                state.pop("prepped_next_packet", None)
                print(f"[FastTrack] Coverage promoted immediately after application transfer for {session_id}")

            generic_prepped_fasttrack = bool(prepped_q) and _is_generic_fasttrack_route(
                prepped_context.get("route_kind")
            )

            if trajectory_admission and (not prepped_q or generic_prepped_fasttrack):
                prepped_q = trajectory_admission["question"]
                trajectory_route_kind = trajectory_admission["route_kind"]
                prepped_context = {
                    "pivoting": trajectory_route_kind == "trajectory_map_bridge",
                    "route_kind": trajectory_route_kind,
                    "weakness": None,
                    "discrepancy": None,
                }
                served_route_kind = trajectory_route_kind
                prepped_packet = _build_question_packet(
                    question_text=prepped_q,
                    sprint=sprint,
                    route_kind=trajectory_route_kind,
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    pivoting=trajectory_route_kind == "trajectory_map_bridge",
                    source_turn_number=state.get("question_count", 0),
                    focus_key_override=trajectory_admission["focus_key"],
                    focus_label_override=trajectory_admission["focus_label"],
                    **_question_packet_ladder_kwargs(trajectory_admission),
                )
                generic_prepped_fasttrack = False
                print(f"[FastTrack] Trajectory-map honesty probe promoted for {session_id}")

            if generic_prepped_fasttrack:
                if (
                    spec.get("best_ready_question")
                    and spec.get("sprint") == sprint
                    and spec.get("turn_id") == turn_id
                ):
                    prepped_q = spec["best_ready_question"]
                    state["speculative_cache"] = {}
                    prepped_context = {
                        "pivoting": False,
                        "route_kind": "speculative_fast",
                        "weakness": None,
                        "discrepancy": None,
                    }
                    served_route_kind = "speculative_fast"
                    prepped_packet = _build_question_packet(
                        question_text=prepped_q,
                        sprint=sprint,
                        route_kind="speculative_fast",
                        parsed_resume=parsed_resume,
                        resume=resume,
                        followups=[],
                        source_turn_number=state.get("question_count", 0),
                    )
                    generic_prepped_fasttrack = False
                    print(
                        f"[FastTrack] Promoted speculative candidate over generic staged fallback for {session_id}"
                    )
                else:
                    trajectory_generic = select_from_trajectory_map_detailed(
                        state.get("interview_trajectory_map", {}),
                        sprint=sprint,
                        focus_key=current_focus_key,
                        answer=text,
                        entities=entities or [],
                        history=state.get("history", []),
                        admission=admission,
                        has_discrepancy=bool(served_discrepancy),
                    )
                    if trajectory_generic:
                        prepped_q = trajectory_generic["question"]
                        trajectory_route_kind = trajectory_generic["route_kind"]
                        prepped_context = {
                            "pivoting": trajectory_route_kind == "trajectory_map_bridge",
                            "route_kind": trajectory_route_kind,
                            "weakness": None,
                            "discrepancy": None,
                        }
                        served_route_kind = trajectory_route_kind
                        prepped_packet = _build_question_packet(
                            question_text=prepped_q,
                            sprint=sprint,
                            route_kind=trajectory_route_kind,
                            parsed_resume=parsed_resume,
                            resume=resume,
                            followups=[],
                            pivoting=trajectory_route_kind == "trajectory_map_bridge",
                            source_turn_number=state.get("question_count", 0),
                            focus_key_override=trajectory_generic["focus_key"],
                            focus_label_override=trajectory_generic["focus_label"],
                            **_question_packet_ladder_kwargs(trajectory_generic),
                        )
                        generic_prepped_fasttrack = False
                        print(
                            f"[FastTrack] Trajectory map promoted over generic staged fallback for {session_id}"
                        )

            if not prepped_q:
                if (
                    spec.get("best_ready_question")
                    and spec.get("sprint") == sprint
                    and spec.get("turn_id") == turn_id
                ):
                    prepped_q = spec["best_ready_question"]
                    state["speculative_cache"] = {}
                    prepped_context = {
                        "pivoting": False,
                        "route_kind": "speculative_fast",
                        "weakness": None,
                        "discrepancy": None,
                    }
                    prepped_packet = _build_question_packet(
                        question_text=prepped_q,
                        sprint=sprint,
                        route_kind="speculative_fast",
                        parsed_resume=parsed_resume,
                        resume=resume,
                        followups=[],
                        source_turn_number=state.get("question_count", 0),
                    )
                    print(f"[FastTrack] Speculative candidate promoted for {session_id}")

            rescued = False
            should_try_short_answer_rescue = (
                not is_turn_revision
                and not bool(locals().get("closing_started"))
                and _short_answer_rescue_eligible(text)
                and (not prepped_q or generic_prepped_fasttrack)
            )
            if should_try_short_answer_rescue:
                # ── 1. Instant: trajectory map short-answer track (no latency) ──
                traj_short = select_from_trajectory_map_detailed(
                    state.get("interview_trajectory_map", {}),
                    sprint=sprint,
                    focus_key=current_focus_key,
                    answer=text,
                    entities=entities or [],
                    history=state.get("history", []),
                    admission=admission,
                    has_discrepancy=bool(served_discrepancy),
                    branch_hint="if_short_answer",
                )
                if traj_short:
                    fast_response = traj_short["question"]
                    served_route_kind = traj_short["route_kind"]
                    served_weakness = None
                    served_discrepancy = None
                    active_packet = _build_question_packet(
                        question_text=fast_response,
                        sprint=sprint,
                        route_kind=served_route_kind,
                        parsed_resume=parsed_resume,
                        resume=resume,
                        followups=[],
                        source_turn_number=state.get("question_count", 0),
                        focus_key_override=traj_short["focus_key"],
                        focus_label_override=traj_short["focus_label"],
                        **_question_packet_ladder_kwargs(traj_short),
                    )
                    pivoting = False
                    rescued = True
                    await self._trace(
                        session_id,
                        "trajectory_map_short_answer_served",
                        turn_id=turn_id,
                        word_count=len(text.split()),
                        route_kind=served_route_kind,
                        focus_key=current_focus_key,
                    )
                    print(f"[FastTrack] Trajectory-map short-answer served ({served_route_kind}) for {session_id}")

                # ── 2. Live Haiku rescue — only when map didn't help ──────────
                if not rescued:
                    try:
                        await self._trace(
                            session_id,
                            "short_answer_rescue_attempt",
                            turn_id=turn_id,
                            word_count=len(text.split()),
                            generic_prepped_fasttrack=generic_prepped_fasttrack,
                        )
                        rescue_decision = await asyncio.wait_for(
                            self.followup_agent.generate_speculative(
                                partial_text=text,
                                new_entities=entities or [],
                                last_question=last_question,
                                persona=persona,
                                sprint=sprint,
                                resume_context=resume_context,
                                admission=admission,
                                current_best_question="",
                                short_answer_rescue=True,
                                focus_context=focus_prompt_pack.get("prompt_context", ""),
                                resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                            ),
                            timeout=1.6,
                        )
                        rescue_question = str(rescue_decision.get("question", "") or "").strip()
                        if rescue_question:
                            fast_response = rescue_question
                            served_weakness = None
                            served_discrepancy = None
                            served_route_kind = "short_answer_rescue"
                            active_packet = _build_question_packet(
                                question_text=fast_response,
                                sprint=sprint,
                                route_kind=served_route_kind,
                                parsed_resume=parsed_resume,
                                resume=resume,
                                followups=[],
                                source_turn_number=state.get("question_count", 0),
                            )
                            pivoting = False
                            rescued = True
                            await self._trace(
                                session_id,
                                "short_answer_rescue_succeeded",
                                turn_id=turn_id,
                                word_count=len(text.split()),
                                rescue_question_chars=len(rescue_question),
                                generic_prepped_fasttrack=generic_prepped_fasttrack,
                            )
                            print(f"[FastTrack] Short-answer rescue served for {session_id}")
                    except asyncio.TimeoutError:
                        await self._trace(
                            session_id,
                            "short_answer_rescue_timed_out",
                            turn_id=turn_id,
                            word_count=len(text.split()),
                            generic_prepped_fasttrack=generic_prepped_fasttrack,
                            level="warn",
                        )
                        print(f"[FastTrack] Short-answer rescue timed out for {session_id}")
                    except Exception as e:
                        await self._trace(
                            session_id,
                            "short_answer_rescue_failed",
                            turn_id=turn_id,
                            word_count=len(text.split()),
                            generic_prepped_fasttrack=generic_prepped_fasttrack,
                            level="warn",
                            error_type=type(e).__name__,
                            error=str(e)[:300],
                        )
                        print(f"[FastTrack] Short-answer rescue failed for {session_id}: {e}")

            # Dedup guard: if the prepped question was already served this session,
            # discard it so we don't repeat the same text back-to-back.
            if prepped_q and not rescued and not is_turn_revision:
                if _question_already_asked(prepped_q, state.get("history", [])):
                    if str(prepped_context.get("route_kind") or "") in {"synthesis_close", "graceful_exit"}:
                        calibration_q = (
                            "One final calibration before we wrap: what is the strongest part of your experience "
                            "that you think this interview has not fairly tested yet?"
                        )
                        final_wrap_q = (
                            "That wraps up our interview. Thanks for walking through the details. "
                            "Your report is being generated now."
                        )
                        prepped_q = calibration_q
                        if _question_already_asked(calibration_q, state.get("history", [])):
                            prepped_q = final_wrap_q
                        if prepped_packet:
                            prepped_packet["question_text"] = prepped_q
                    elif str(prepped_context.get("route_kind") or prepped_packet.get("route_kind") or "") == "second_anchor":
                        second_anchor_target = {
                            "focus_key": str(prepped_packet.get("focus_key") or "").strip(),
                            "focus_label": str(prepped_packet.get("focus_label") or "").strip(),
                            "sub_focus_key": str(prepped_packet.get("sub_focus_key") or "").strip(),
                            "sub_focus_label": str(prepped_packet.get("sub_focus_label") or "").strip(),
                            "surface_kind": str(prepped_packet.get("surface_kind") or "").strip(),
                            "surface_key": _route_surface_key(
                                str(prepped_packet.get("focus_key") or "").strip(),
                                str(prepped_packet.get("sub_focus_key") or "").strip(),
                            ),
                        }
                        replacement = _reselect_second_anchor_for_surface(
                            state,
                            state.get("history", []),
                            sprint=sprint,
                            target=second_anchor_target,
                            avoid_focus=str((active_packet or {}).get("focus_key") or current_focus_key or ""),
                            answer=text,
                            entities=entities or [],
                            admission=admission,
                            has_discrepancy=bool(served_discrepancy),
                        )
                        if replacement and not _question_already_asked(replacement.get("question", ""), state.get("history", [])):
                            prepped_q = replacement["question"]
                            prepped_context["route_kind"] = "second_anchor"
                            prepped_packet = _build_question_packet(
                                question_text=prepped_q,
                                sprint=sprint,
                                route_kind="second_anchor",
                                parsed_resume=parsed_resume,
                                resume=resume,
                                followups=[],
                                source_turn_number=state.get("question_count", 0),
                                focus_key_override=str(replacement.get("focus_key") or "").strip(),
                                focus_label_override=str(replacement.get("focus_label") or "").strip(),
                                sub_focus_key_override=str(replacement.get("sub_focus_key") or "").strip(),
                                sub_focus_label_override=str(replacement.get("sub_focus_label") or "").strip(),
                                **_question_packet_ladder_kwargs(replacement),
                            )
                            state["prepped_next_question"] = prepped_q
                            state["prepped_next_context"] = prepped_context
                            state["prepped_next_packet"] = prepped_packet
                            print(f"[FastTrack] Dedup: reselected second-anchor surface for {session_id}")
                        else:
                            print(f"[FastTrack] Dedup: second-anchor replacement unavailable — discarding for {session_id}")
                            prepped_q = None
                            state.pop("prepped_next_question", None)
                            state.pop("prepped_next_question_turn_number", None)
                            state.pop("prepped_next_context", None)
                            state.pop("prepped_next_packet", None)
                            prepped_context = {}
                            prepped_packet = {}
                    else:
                        print(f"[FastTrack] Dedup: prepped_q already in history — discarding for {session_id}")
                        prepped_q = None
                        state.pop("prepped_next_question", None)
                        state.pop("prepped_next_question_turn_number", None)
                        state.pop("prepped_next_context", None)
                        state.pop("prepped_next_packet", None)
                        prepped_context = {}
                        prepped_packet = {}

            if prepped_q and not rescued and not is_turn_revision:
                prepped_route = str(prepped_context.get("route_kind") or prepped_packet.get("route_kind") or "").strip()
                if prepped_route == "second_anchor":
                    history_now = list(state.get("history", []) or [])
                    block_reason = _second_anchor_packet_block_reason(
                        prepped_packet,
                        history_now,
                        _evidence_question_count(state),
                    )
                    if block_reason:
                        replacement = _reselect_second_anchor_for_surface(
                            state,
                            history_now,
                            sprint=sprint,
                            target=_second_anchor_target_from_packet(prepped_packet),
                            avoid_focus=str((active_packet or {}).get("focus_key") or current_focus_key or ""),
                            answer=text,
                            entities=entities or [],
                            admission=admission,
                            has_discrepancy=bool(served_discrepancy),
                        )
                        if replacement and not _question_already_asked(replacement.get("question", ""), history_now):
                            replacement_packet = _build_question_packet(
                                question_text=replacement["question"],
                                sprint=sprint,
                                route_kind="second_anchor",
                                parsed_resume=parsed_resume,
                                resume=resume,
                                followups=[],
                                source_turn_number=state.get("question_count", 0),
                                focus_key_override=str(replacement.get("focus_key") or "").strip(),
                                focus_label_override=str(replacement.get("focus_label") or "").strip(),
                                sub_focus_key_override=str(replacement.get("sub_focus_key") or "").strip(),
                                sub_focus_label_override=str(replacement.get("sub_focus_label") or "").strip(),
                                **_question_packet_ladder_kwargs(replacement),
                            )
                            if not _second_anchor_packet_block_reason(
                                replacement_packet,
                                history_now,
                                _evidence_question_count(state),
                            ):
                                prepped_q = replacement["question"]
                                prepped_context["route_kind"] = "second_anchor"
                                prepped_packet = replacement_packet
                                state["prepped_next_question"] = prepped_q
                                state["prepped_next_context"] = prepped_context
                                state["prepped_next_packet"] = prepped_packet
                                await self._trace(
                                    session_id,
                                    "second_anchor_reselected_before_serve",
                                    turn_id=turn_id,
                                    reason=block_reason,
                                    replacement_focus_key=str(replacement.get("focus_key") or ""),
                                    replacement_sub_focus_key=str(replacement.get("sub_focus_key") or ""),
                                )
                                print(f"[FastTrack] Retired stale second-anchor packet and reselected surface for {session_id}")
                            else:
                                replacement = None
                        if not replacement:
                            reserve_result = _select_reserve_question(
                                state,
                                history_now,
                                avoid_focus=str((prepped_packet or {}).get("focus_key") or current_focus_key or ""),
                            )
                            next_visible_turn = _next_visible_turn_number(state, history_now)
                            if reserve_result and next_visible_turn < SYNTHESIS_START_FLOOR:
                                prepped_q = reserve_result["question"]
                                prepped_context = {
                                    "pivoting": False,
                                    "route_kind": reserve_result["route_kind"],
                                    "weakness": None,
                                    "discrepancy": None,
                                }
                                prepped_packet = _build_question_packet(
                                    question_text=prepped_q,
                                    sprint=sprint,
                                    route_kind=reserve_result["route_kind"],
                                    parsed_resume=parsed_resume,
                                    resume=resume,
                                    followups=[],
                                    source_turn_number=state.get("question_count", 0),
                                    focus_key_override=str(reserve_result.get("focus_key") or "").strip(),
                                    focus_label_override=str(reserve_result.get("focus_label") or "").strip(),
                                    sub_focus_key_override=str(reserve_result.get("sub_focus_key") or "").strip(),
                                    sub_focus_label_override=str(reserve_result.get("sub_focus_label") or "").strip(),
                                    **_question_packet_ladder_kwargs(reserve_result),
                                )
                                await self._trace(
                                    session_id,
                                    "second_anchor_replaced_with_reserve_before_serve",
                                    turn_id=turn_id,
                                    reason=block_reason,
                                    reserve_focus_key=str(reserve_result.get("focus_key") or ""),
                                )
                            else:
                                close_count = _synthesis_close_count(history_now)
                                prepped_q = await self.followup_agent.generate_graceful_close(state, close_count)
                                prepped_context = {
                                    "pivoting": True,
                                    "route_kind": "graceful_exit" if close_count else "synthesis_close",
                                    "weakness": None,
                                    "discrepancy": None,
                                }
                                prepped_packet = _build_question_packet(
                                    question_text=prepped_q,
                                    sprint=sprint,
                                    route_kind=prepped_context["route_kind"],
                                    parsed_resume=parsed_resume,
                                    resume=resume,
                                    followups=[],
                                    source_turn_number=state.get("question_count", 0),
                                )
                                await self._trace(
                                    session_id,
                                    "second_anchor_replaced_with_close_before_serve",
                                    turn_id=turn_id,
                                    reason=block_reason,
                                    close_route=prepped_context["route_kind"],
                                )
                            state["prepped_next_question"] = prepped_q
                            state["prepped_next_context"] = prepped_context
                            state["prepped_next_packet"] = prepped_packet

            if prepped_q and not rescued:
                fast_response = prepped_q
                served_weakness = prepped_context.get("weakness")
                served_discrepancy = prepped_context.get("discrepancy")
                if not served_route_kind:
                    served_route_kind = "prepped_next_question"
                active_packet = prepped_packet or _build_question_packet(
                    question_text=fast_response,
                    sprint=sprint,
                    route_kind=served_route_kind,
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=[],
                    pivoting=prepped_context.get("pivoting", False),
                    weakness=served_weakness,
                    discrepancy=served_discrepancy,
                    source_turn_number=state.get("question_count", 0),
                )
                state.pop("prepped_next_question", None)
                state.pop("prepped_next_question_turn_number", None)
                state.pop("prepped_next_context", None)
                state.pop("prepped_next_packet", None)
                print(f"[FastTrack] {served_route_kind} ready — serving instantly for {session_id}")

            elif not rescued:
                    if bool(locals().get("closing_started")):
                        raise RuntimeError(
                            "Closing flow has started but no close packet was available; refusing map fallback."
                        )
                    # ── 1. Trajectory map — resume-grounded, instant ──────────
                    traj_result = select_from_trajectory_map_detailed(
                        state.get("interview_trajectory_map", {}),
                        sprint=sprint,
                        focus_key=current_focus_key,
                        answer=text,
                        entities=entities or [],
                        history=state.get("history", []),
                        admission=admission,
                        has_discrepancy=bool(served_discrepancy),
                    )
                    if traj_result:
                        fast_response = traj_result["question"]
                        served_route_kind = traj_result["route_kind"]
                        active_packet = _build_question_packet(
                            question_text=fast_response,
                            sprint=sprint,
                            route_kind=served_route_kind,
                            parsed_resume=parsed_resume,
                            resume=resume,
                            followups=[],
                            pivoting=served_route_kind == "trajectory_map_bridge",
                            source_turn_number=state.get("question_count", 0),
                            focus_key_override=traj_result["focus_key"],
                            focus_label_override=traj_result["focus_label"],
                            **_question_packet_ladder_kwargs(traj_result),
                        )
                        await self._trace(
                            session_id,
                            "trajectory_map_served",
                            turn_id=turn_id,
                            route_kind=served_route_kind,
                            focus_key=current_focus_key,
                        )
                        print(f"[FastTrack] Trajectory map served ({served_route_kind}) for {session_id}")
                    else:
                        completion_coverage = _assessment_coverage(state)
                        history_now = state.get("history", []) or []
                        if completion_coverage.get("minimum_viable_completion") and len(history_now) >= SECOND_ANCHOR_START_FLOOR:
                            close_count = _synthesis_close_count(history_now)
                            fast_response = await self.followup_agent.generate_graceful_close(state, close_count)
                            served_route_kind = "graceful_exit" if close_count else "synthesis_close"
                            active_packet = _build_question_packet(
                                question_text=fast_response,
                                sprint=sprint,
                                route_kind=served_route_kind,
                                parsed_resume=parsed_resume,
                                resume=resume,
                                followups=[],
                                pivoting=True,
                                source_turn_number=state.get("question_count", 0),
                            )
                            await self._trace(
                                session_id,
                                "map_exhausted_closed_without_generic_fallback",
                                turn_id=turn_id,
                                route_kind=served_route_kind,
                                history_len=len(history_now),
                                coverage=completion_coverage,
                            )
                            print(f"[FastTrack] Map exhausted; closing without generic fallback for {session_id}")
                        else:
                            raise RuntimeError(
                                "No prepared or trajectory-map question available; refusing generic sprint fallback."
                            )

                    served_weakness = None
                    served_discrepancy = None
                    # No generic follow-ups chained off a fallback — the BGPipeline will generate
                    # a proper question packet after this answer. Chaining fallbacks creates a generic
                    # loop that's worse than waiting for the background pipeline.
                    pivoting = False

        await self._trace(
            session_id,
            "fasttrack_response_selected",
            turn_id=turn_id,
            is_revision=is_turn_revision,
            route_kind=served_route_kind,
            pivoting=bool(pivoting),
            current_packet_followups_remaining=len(_packet_followups_remaining(active_packet)),
            had_prepped=bool(prepped_q),
            had_speculative=bool(spec.get("best_ready_question")) if isinstance(spec, dict) else False,
            weakness_type=served_weakness.get("type") if isinstance(served_weakness, dict) else None,
            weakness_severity=served_weakness.get("severity") if isinstance(served_weakness, dict) else None,
            discrepancy_conflict=served_discrepancy.get("conflict_level") if isinstance(served_discrepancy, dict) else None,
        )

        # ── Step 3: Update canonical state ───────────────────────────────────
        # Only counters and current question. History/weaknesses/candidate_model
        # are updated when staged analysis is consumed (Step 1).
        current_turn_number = state.get("current_answer_turn_number", state.get("question_count", 0))
        if not is_turn_revision:
            state["question_count"] = state.get("question_count", 0) + 1
            if _counts_toward_evidence_budget(answered_route_kind_for_count):
                state["evidence_question_count"] = _evidence_question_count(state) + 1
                state["sprint_question_count"] = state.get("sprint_question_count", 0) + 1
            else:
                state["evidence_question_count"] = _evidence_question_count(state)
            state["last_question"] = fast_response
            current_turn_number = state["question_count"]

            advanced, _ = await self._maybe_advance_sprint(
                state,
                answered_question=last_question,
                current_answer=text,
            )
            if advanced:
                persona = state["current_persona"]
                if active_packet:
                    active_packet["sprint"] = state["current_sprint"]
        else:
            state["last_question"] = fast_response

        closing_phase = _closing_phase(
            state.get("current_sprint", 1),
            state.get("sprint_question_count", 0),
        )
        if closing_phase and not is_turn_revision:
            turn_in_close = 0 if closing_phase == "last_two" else 1
            fast_response = await self.followup_agent.generate_graceful_close(state, turn_in_close)
            state["last_question"] = fast_response
            if active_packet:
                active_packet["question_text"] = fast_response

        state["active_question_packet"] = _clone_question_packet(active_packet)
        state["current_question_followups"] = _packet_followups_remaining(active_packet)
        state["current_question_followup_asked"] = not _packet_has_followups(active_packet)
        state["current_answer_turn_id"] = turn_id
        state["current_answer_question"] = last_question
        state["current_answer_response"] = fast_response
        state["current_answer_context"] = {
            "pivoting": pivoting,
            "route_kind": served_route_kind,
            "weakness": served_weakness,
            "discrepancy": served_discrepancy,
            "answer_version": current_answer_version,
            "packet_focus_key": active_packet.get("focus_key", ""),
            "packet_focus_label": active_packet.get("focus_label", ""),
            "surface_kind": active_packet.get("surface_kind", ""),
            "question_posture": active_packet.get("question_posture", ""),
            "signal_goal": active_packet.get("signal_goal", ""),
            "expected_space": list(active_packet.get("expected_space") or [])[:4],
            "covered_expected_space": list(active_packet.get("covered_expected_space") or [])[:4],
            "missing_expected_space": list(active_packet.get("missing_expected_space") or active_packet.get("expected_space") or [])[:4],
            "coverage_dimension_id": str(active_packet.get("coverage_dimension_id") or ""),
            "coverage_dimension_label": str(active_packet.get("coverage_dimension_label") or ""),
            "closing_phase": closing_phase,
        }
        state["current_answer_turn_number"] = current_turn_number
        state["current_answer_version"] = current_answer_version
        state["latest_turn_versions"] = latest_turn_versions

        # Communication mode detection — runs once after the first two committed answers.
        if current_turn_number == 2 and not is_turn_revision:
            _hist = state.get("history", [])
            _cs = state.setdefault("candidate_state", {})
            if len(_hist) >= 2 and not _cs.get("_communication_mode_checked"):
                _t0 = _hist[-2].get("answer", "") if _hist else ""
                _t1 = _hist[-1].get("answer", "") or text
                _mode = _detect_communication_mode(_t0, _t1)
                _cs["_communication_mode_checked"] = True
                if _mode != "normal":
                    _cs["communication_mode"] = _mode
                    await self._trace(session_id, "communication_mode_detected", mode=_mode, turn=current_turn_number)

        complete = self._is_complete(state)
        await self.session_manager.save_state(session_id, state)

        if complete:
            await self.start_finalization_background(session_id)
            await self._trace(
                session_id,
                "fasttrack_complete",
                turn_id=turn_id,
                route_kind="complete",
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
            return {
                "response": "That wraps up our interview. Thanks for walking through the details. Your report is being generated now.",
                "sprint": state["current_sprint"],
                "persona": persona,
                "complete": True,
                "report_ready": False,
                "finalization_status": "running",
                "pivoting": False,
                "weakness": None,
                "discrepancy": None,
                "route_kind": "complete",
                "turn_id": turn_id,
                "closing_phase": "complete",
                "questions_remaining": 0,
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
                answer_version=current_answer_version,
            )
        )

        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        print(f"[FastTrack] {served_route_kind or 'unknown'} served in {elapsed_ms}ms for {session_id}")
        await self._trace(
            session_id,
            "fasttrack_done",
            turn_id=turn_id,
            route_kind=served_route_kind,
            sprint=state["current_sprint"],
            question_count=state["question_count"],
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
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
            "route_kind": served_route_kind,
            "turn_id": turn_id,
            "closing_phase": closing_phase,
            "questions_remaining": max(
                QUESTIONS_PER_SPRINT - state.get("sprint_question_count", 0),
                0,
            ) if state.get("current_sprint") == 3 else None,
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
        existing_turn = next((item for item in history if item.get("turn_id") == existing_turn_id), None)
        already_complete = bool(existing_turn and existing_turn.get("analysis_status") == "complete")

        payload = {
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
            "sub_focus_key": staged.get("sub_focus_key", ""),
            "sub_focus_label": staged.get("sub_focus_label", ""),
            "surface_kind": staged.get("surface_kind", ""),
            "question_posture": staged.get("question_posture", ""),
            "signal_goal": staged.get("signal_goal", ""),
            "expected_space": list(staged.get("expected_space") or [])[:4],
            "covered_expected_space": list(staged.get("covered_expected_space") or [])[:4],
            "missing_expected_space": list(staged.get("missing_expected_space") or staged.get("expected_space") or [])[:4],
            "coverage_dimension_id": str(staged.get("coverage_dimension_id") or ""),
            "coverage_dimension_label": str(staged.get("coverage_dimension_label") or ""),
            "answer_version": staged.get("answer_version", 1),
            "route_kind": metadata.get("route_kind", "unknown"),
            "analysis_status": "complete",
        }

        if existing_turn:
            existing_turn.update(payload)
        else:
            history.append(payload)

        if not already_complete:
            agenda = ensure_interview_agenda(state)
            focus_key = str(payload.get("focus_key") or "").strip()
            if focus_key and focus_key not in ("general", "general_background", "general background"):
                agenda["current_focus_key"] = focus_key
                turns_by_focus = dict(agenda.get("turns_by_focus") or {})
                turns_by_focus[focus_key] = int(turns_by_focus.get(focus_key, 0) or 0) + 1
                agenda["turns_by_focus"] = turns_by_focus
                sub_focus_key = str(payload.get("sub_focus_key") or "").strip()
                surface_key = f"{focus_key}::{sub_focus_key}" if sub_focus_key else focus_key
                turns_by_surface = dict(agenda.get("turns_by_surface") or {})
                turns_by_surface[surface_key] = int(turns_by_surface.get(surface_key, 0) or 0) + 1
                agenda["turns_by_surface"] = turns_by_surface
                exhausted = list(agenda.get("exhausted_focus_keys") or [])
                surface_breadth = len(surfaces_by_focus(history).get(focus_key, []))
                if (
                    turns_by_focus[focus_key] >= FOCUS_STREAK_CAP
                    and surface_breadth < 2
                    and focus_key not in exhausted
                ):
                    exhausted.append(focus_key)
                agenda["exhausted_focus_keys"] = exhausted

                cs = state.setdefault("candidate_state", {})
                fatigue = dict(cs.get("topic_fatigue") or {})
                counts = dict(cs.get("topic_question_counts") or {})
                fatigue[focus_key] = int(fatigue.get(focus_key, 0) or 0) + 1
                counts[focus_key] = int(counts.get(focus_key, 0) or 0) + 1
                cs["topic_fatigue"] = fatigue
                cs["topic_question_counts"] = counts

            agenda["phase"] = metadata.get("agenda_phase") or _route_phase_from_kind(metadata.get("route_kind", ""))
            agenda["last_route_reason"] = metadata.get("agenda_reason") or metadata.get("route_kind", "unknown")
            agenda["phase_turn_count"] = int(agenda.get("phase_turn_count") or 0) + 1
            state["interview_agenda"] = agenda
            state["assessment_coverage"] = _assessment_coverage(state)
            state["interview_agenda"]["completion_eligible"] = bool(
                state["assessment_coverage"].get("full_completion_eligible")
                or state["assessment_coverage"].get("minimum_viable_completion")
            )

        # Append weakness to ledger
        weakness = staged.get("weakness")
        if weakness and weakness.get("type") and not already_complete:
            state["weaknesses"].append(weakness)

        # Apply candidate memory updates
        cm_updates = staged.get("candidate_model_updates", {})
        cm = state.get("candidate_model", {"project_map": {}, "established_facts": [], "probed_weaknesses": []})
        if not already_complete:
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

        asyncio.create_task(
            interview_telemetry.log(
                state.get("session_id", "unknown"),
                "staged_analysis_applied",
                source="backend.orchestrator",
                turn_id=existing_turn_id,
                route_kind=metadata.get("route_kind", "unknown"),
                weakness_type=weakness.get("type") if isinstance(weakness, dict) else None,
                weakness_severity=weakness.get("severity") if isinstance(weakness, dict) else None,
                discrepancy_conflict=staged.get("discrepancy", {}).get("conflict_level")
                if isinstance(staged.get("discrepancy"), dict)
                else None,
                already_complete=already_complete,
            )
        )

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
        answer_version: int,
    ) -> None:
        """
        Full reasoning pipeline — runs during the candidate's answer to the fast follow-up.

        Runs all agents in parallel, applies all guardrails, generates the next adversarial
        question via the full FollowUpAgent priority chain.

        INVARIANT: canonical state fields (history, question_count, last_question, weaknesses,
        sprint counters, candidate_model) are NEVER mutated here. All outputs are staged in
        prepped_* fields and consumed atomically at the start of the next handle_transcript.
        """
        pipeline_key = (
            session_id,
            turn_id or f"turn-{turn_number}",
            answer_version,
        )
        await self._trace(
            session_id,
            "bgpipeline_start",
            turn_id=turn_id,
            turn_number=turn_number,
            answer_version=answer_version,
            transcript_chars=len(text),
            transcript_words=len(text.split()),
            entities_count=len(entities or []),
        )

        # Exact-duplicate guard: suppress identical (session, turn, version) triple.
        if pipeline_key in self._pipeline_inflight:
            print(
                f"[BGPipeline] Concurrent duplicate skipped (inflight) for "
                f"turn_id {turn_id} v{answer_version}"
            )
            await self._trace(
                session_id,
                "bgpipeline_skipped_duplicate",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                level="warn",
            )
            return
        # Revision-explosion guard: if any version of this turn is already running,
        # skip. The running pipeline will produce a stale-superseded result (discarded
        # at consumption) which is cheaper than running 14 concurrent LLM pipelines
        # for the same turn when STT fragments a single utterance.
        running_for_session = self._turn_pipeline_running.setdefault(session_id, set())
        if turn_id and turn_id in running_for_session:
            print(
                f"[BGPipeline] Revision skipped — turn_id {turn_id} already in flight "
                f"(v{answer_version} suppressed)"
            )
            await self._trace(
                session_id,
                "bgpipeline_skipped_revision_inflight",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                level="warn",
            )
            return
        self._pipeline_inflight.add(pipeline_key)
        if turn_id:
            running_for_session.add(turn_id)

        started_at = time.perf_counter()
        try:
            state = await self.session_manager.get_state(session_id)

            if state.get("interview_complete"):
                return

            existing_queue = state.get("prepped_turn_queue", [])
            if any(
                item.get("turn_id") == turn_id
                and _staged_answer_version(item) == answer_version
                for item in existing_queue
            ):
                print(
                    f"[BGPipeline] Skipping already-staged duplicate for "
                    f"turn_id {turn_id} v{answer_version} / {session_id}"
                )
                await self._trace(
                    session_id,
                    "bgpipeline_skipped_already_staged",
                    turn_id=turn_id,
                    turn_number=turn_number,
                    answer_version=answer_version,
                    level="warn",
                )
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
            history = [
                item
                for item in state.get("history", [])
                if item.get("turn_id") != turn_id
            ]
            current_turn_skeleton = next(
                (
                    item for item in state.get("history", [])
                    if item.get("turn_id") == turn_id
                ),
                {},
            )
            answered_route_kind = (
                current_turn_skeleton.get("route_kind")
                or (state.get("current_answer_context") or {}).get("route_kind")
                or ""
            )

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
            _trajectory_map = state.get("interview_trajectory_map") or {}
            _weakness_focus_areas = [
                {"focus_key": fa.get("focus_key", ""), "label": fa.get("label", "")}
                for fa in (_trajectory_map.get("focus_areas") or [])
                if fa.get("focus_key")
            ] or None

            async def _safe_weakness():
                weak_started = time.perf_counter()
                result = await self.weakness_agent.detect(
                    last_question, text, sprint=sprint,
                    prior_weaknesses=prior_weaknesses,
                    memory_context=memory_context,
                    parsed_resume=parsed_resume,
                    target_role=target_role,
                    years_experience=years_experience,
                    focus_areas=_weakness_focus_areas,
                )
                return result, round((time.perf_counter() - weak_started) * 1000, 3)

            async def _safe_discrepancy():
                disc_started = time.perf_counter()
                result = await self.discrepancy_agent.check(resume, text, memory_context=memory_context)
                return result, round((time.perf_counter() - disc_started) * 1000, 3)

            async def _safe_reasoning():
                reasoning_started = time.perf_counter()
                result = await self.reasoning_agent.evaluate(text, was_challenged=was_challenged)
                return result, round((time.perf_counter() - reasoning_started) * 1000, 3)

            if entities:
                (weakness, weakness_ms), (discrepancy, discrepancy_ms), (reasoning, reasoning_ms) = await asyncio.gather(
                    _safe_weakness(), _safe_discrepancy(), _safe_reasoning()
                )
                concepts = entities
                concepts_ms = 0.0
            else:
                async def _safe_concepts():
                    concept_started = time.perf_counter()
                    result = await self.concept_agent.extract(text)
                    return result, round((time.perf_counter() - concept_started) * 1000, 3)
                (concepts_result, concepts_ms), ((weakness, weakness_ms), (discrepancy, discrepancy_ms), (reasoning, reasoning_ms)) = await asyncio.gather(
                    _safe_concepts(),
                    asyncio.gather(_safe_weakness(), _safe_discrepancy(), _safe_reasoning()),
                )
                concepts = concepts_result

            await self._trace(
                session_id,
                "bgpipeline_agents_complete",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                concepts_count=len(concepts or []),
                concepts_ms=concepts_ms,
                weakness_ms=weakness_ms,
                discrepancy_ms=discrepancy_ms,
                reasoning_ms=reasoning_ms,
            )

            # Per-answer scoring — fire and forget, never blocks anything
            asyncio.create_task(
                self._score_answer_async(
                    session_id,
                    last_question,
                    text,
                    turn_id=turn_id,
                    turn_number=turn_number,
                    route_kind=answered_route_kind,
                    focus_key=current_turn_skeleton.get("focus_key") or "",
                    focus_label=current_turn_skeleton.get("focus_label") or "",
                    sub_focus_key=current_turn_skeleton.get("sub_focus_key") or "",
                    sub_focus_label=current_turn_skeleton.get("sub_focus_label") or "",
                    weakness=weakness if isinstance(weakness, dict) else None,
                    reasoning=reasoning if isinstance(reasoning, dict) else None,
                    target_role=target_role,
                    years_experience=years_experience,
                )
            )

            # ── STAR-lite extraction after enough evidence-bearing turns ──────
            # Extract implementation_anchor from the candidate's narration turns
            # and kick off application transfer question generation in background.
            if _should_prepare_application_transfer(state):
                _phase2_answers = [
                    h.get("answer", "")
                    for h in history[-2:]
                    if h.get("answer")
                ]
                _phase2_answers.append(text)
                phase2_text = " ".join(_phase2_answers)
                anchor = await self._extract_implementation_anchor(session_id, phase2_text, state)
                if anchor:
                    cs = state.setdefault("candidate_state", {})
                    cs["implementation_anchor"] = anchor
                    cs["anchor_confidence"] = _classify_anchor_confidence(anchor, phase2_text)
                    # Persist anchor immediately — pipeline re-reads state later and would lose it
                    _anchor_save_state = await self.session_manager.get_state(session_id)
                    _anchor_save_state.setdefault("candidate_state", {})["implementation_anchor"] = anchor
                    _anchor_save_state.setdefault("candidate_state", {})["anchor_confidence"] = cs["anchor_confidence"]
                    await self.session_manager.save_state(session_id, _anchor_save_state)
                    await self._generate_application_transfer(session_id, state)
                    await self._trace(session_id, "star_lite_anchor_extracted",
                                      turn_number=turn_number,
                                      anchor_confidence=cs["anchor_confidence"],
                                      anchor_chars=len(anchor))

            # live_q4_candidates generation disabled — generated but never consumed by route selection.
            # Re-enable once the route selector reads state["live_q4_candidates"] for Q4 serving.

            # ── Honest admission soft-cap ─────────────────────────────────────
            reasoning_adaptability = reasoning.get("adaptability", "") if isinstance(reasoning, dict) else ""
            honest_admission = reasoning_adaptability == "admitted_gap"
            if honest_admission and weakness.get("severity") == "high":
                weakness = {**weakness, "severity": "medium"}

            # D3: Persist ReasoningBehaviorAgent tone signal for followup_agent next turn
            if isinstance(reasoning, dict) and reasoning.get("adaptability"):
                state["_reasoning_tone_signal"] = reasoning.get("adaptability", "")

            # C-2 fix: WeaknessAgent inferred_focus_key is most specific → use first.
            # Fall back to active_question_packet.focus_key (already known from staging).
            # Only call _infer_focus() as last resort when neither is available.
            _valid_focus_keys = {
                str(fa.get("focus_key", "") or "").strip()
                for fa in (_weakness_focus_areas or [])
                if str(fa.get("focus_key", "") or "").strip()
            }
            _llm_focus_key = (weakness.get("inferred_focus_key") or "").strip() if isinstance(weakness, dict) else ""
            if _llm_focus_key and _llm_focus_key not in _valid_focus_keys:
                _llm_focus_key = ""
            _active_pkt = state.get("active_question_packet") or {}
            _pkt_focus_key_bg = str(_active_pkt.get("focus_key") or "").strip()
            _pkt_focus_label_bg = str(_active_pkt.get("focus_label") or "").strip()
            if _llm_focus_key:
                current_focus_key = _llm_focus_key
                current_focus_label = next(
                    (fa.get("label", _llm_focus_key) for fa in (_weakness_focus_areas or []) if fa.get("focus_key") == _llm_focus_key),
                    _llm_focus_key,
                )
            elif _pkt_focus_key_bg and _pkt_focus_key_bg not in ("general", "general_background", "general background"):
                current_focus_key = _pkt_focus_key_bg
                current_focus_label = _pkt_focus_label_bg or _pkt_focus_key_bg
            else:
                current_focus_key, current_focus_label = _infer_focus(
                    last_question,
                    text,
                    parsed_resume,
                    resume,
                    trajectory_focus_areas=_weakness_focus_areas,
                )
            _pkt_sub_focus_key_bg = str(_active_pkt.get("sub_focus_key") or "").strip()
            _pkt_sub_focus_label_bg = str(_active_pkt.get("sub_focus_label") or "").strip()
            if _pkt_sub_focus_key_bg:
                answered_sub_focus_key = _pkt_sub_focus_key_bg
                answered_sub_focus_label = _pkt_sub_focus_label_bg or _pkt_sub_focus_key_bg
            else:
                answered_sub_focus_key, answered_sub_focus_label = _infer_sub_focus(
                    state.get("interview_trajectory_map", {}),
                    current_focus_key,
                    last_question,
                    text,
                )
            answered_focus_key = current_focus_key
            answered_focus_label = current_focus_label
            focus_prompt_pack = _build_focus_prompt_pack(
                state.get("interview_trajectory_map", {}),
                focus_key=current_focus_key,
                last_question=last_question,
                answer=text,
                history=history,
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
            # Prevent topic tunneling: if the last N turns all touched the same
            # resume claim / project, force a pivot — regardless of weakness type.
            # Uses topic focus keys from history, not weakness type repetition.
            weakness_type = weakness.get("type") if isinstance(weakness, dict) else None

            # ── C-3 fix: Bridge trigger by focus-area exhaustion ─────────────
            # Old logic required same weakness TYPE to repeat — weakness types often
            # change turn-to-turn so the count never reached 3. New logic counts
            # medium/high weaknesses by inferred_focus_key from the ledger.
            # If 3+ weaknesses share the same focus area → force bridge regardless
            # of weakness type cycling.
            wtype = weakness_type
            if weakness and weakness.get("severity") in ("high", "medium"):
                new_consecutive = state.get("consecutive_high_weakness_count", 0) + 1
            else:
                new_consecutive = 0
                wtype = None

            # Focus-area saturation check: count weaknesses with same inferred_focus_key
            _current_inferred_fk = (weakness.get("inferred_focus_key") or current_focus_key or "").strip() if isinstance(weakness, dict) else current_focus_key or ""
            _ledger_focus_hits = sum(
                1 for w in state.get("weaknesses", [])
                if isinstance(w, dict)
                and (w.get("inferred_focus_key") or "").strip() == _current_inferred_fk
                and w.get("severity") in ("medium", "high")
                and _current_inferred_fk
            )
            # Hard cap: no focus area gets more than 5 turns total in history
            _history_focus_turns = sum(1 for t in history if t.get("focus_key") == current_focus_key)
            _history_focus_surfaces = len(surfaces_by_focus(history).get(current_focus_key, []))

            # Do not use the global consecutive weakness count as a focus-rotation
            # trigger. Three weak answers across three different topics should not
            # masquerade as topic tunneling; focus-specific ledger/history counts
            # are the only safe rotation signal here.
            focus_turn_cap_hit = _history_focus_turns >= 5 and _history_focus_surfaces < 2
            force_sprint_question = _ledger_focus_hits >= 3 or focus_turn_cap_hit
            pivoting = force_sprint_question

            # ── Skip signal / forced rotation ────────────────────────────────
            if state.get("_force_focus_rotation"):
                force_sprint_question = True
                pivoting = True
                state.pop("_force_focus_rotation", None)

            # ── Topic fatigue ratio ─────────────────────────────────────────
            # Keep this aligned with the agenda controller. The denominator must
            # be focus-bearing evidence turns, not total question count; warm
            # openers and empty/inferred turns distort the ratio badly.
            if _should_force_focus_ratio_rotation(state, history, current_focus_key):
                force_sprint_question = True
                pivoting = True

            # ── Disengagement thresholds ─────────────────────────────────────
            candidate_state = state.get("candidate_state") or {}
            disengagement_level = float(candidate_state.get("disengagement_level", 0.0))

            if disengagement_level >= 2.0 and not candidate_state.get("_save_face_pivot_used"):
                state.setdefault("candidate_state", {})["_save_face_pivot_used"] = True
                state["_next_route_hint"] = "confession_pivot"

            if disengagement_level >= 3.0:
                force_sprint_question = True
                pivoting = True

            if disengagement_level >= 4.0:
                state.setdefault("candidate_state", {})["communication_mode"] = "simplified"

            if disengagement_level >= 5.0 and not candidate_state.get("forced_exit_triggered"):
                state.setdefault("candidate_state", {})["forced_exit_triggered"] = True
                state["_next_route_hint"] = "graceful_exit"

            # ── Sprint 3 strategy remap ───────────────────────────────────────
            if sprint == 3 and weakness and weakness.get("probe_direction") in ("implementation_probe", "step_by_step"):
                weakness = {**weakness, "probe_direction": "scaling"}

            # ── Full priority chain → generates the next adversarial question ─
            discrepancy_conflict = (
                isinstance(discrepancy, dict)
                and discrepancy.get("conflict_level") == "confirmed"
                and discrepancy.get("severity") in ("medium", "high")
            )
            # same_focus_recent: how many of the last 3 turns shared this exact topic key
            # Threshold: 2 turns on same topic → already probed enough, move on
            # Exception: confirmed discrepancy on this topic is worth one extra press
            repeated_focus = (
                same_focus_recent >= 2
                and not discrepancy_conflict
                and isinstance(weakness, dict)
                and weakness.get("severity") == "high"
                and not substantive_recovery
            )
            contradiction_budget_exhausted = discrepancy_conflict and same_focus_confirmed >= 2 and not substantive_recovery
            deflection_budget_exhausted = weakness_type == "deflection" and same_focus_deflections >= 2
            if repeated_focus or contradiction_budget_exhausted or deflection_budget_exhausted:
                force_sprint_question = True
                pivoting = True
            # ambiguous_but_promising always demands clarification first — the type's semantics
            # require it regardless of what probe_direction the LLM emitted.
            if isinstance(weakness, dict) and weakness.get("type") == "ambiguous_but_promising":
                weakness = {**weakness, "probe_direction": "clarification",
                            "severity": weakness.get("severity") or "medium"}

            clarification_probe = (
                isinstance(weakness, dict)
                and weakness.get("probe_direction") in ("clarification", "ownership_probe")
                and weakness.get("severity") in ("medium", "high")
            )
            deep_probe = (
                isinstance(weakness, dict)
                and weakness.get("severity") == "high"
                and weakness.get("probe_direction") not in ("clarification", "ownership_probe")
                and turn_number >= 2
            )
            agenda_decision = _select_agenda_decision(
                state,
                history=history,
                current_focus_key=current_focus_key,
                current_focus_label=current_focus_label,
                answered_route_kind=answered_route_kind,
                weakness=weakness if isinstance(weakness, dict) else None,
                discrepancy_conflict=discrepancy_conflict,
                honest_admission=honest_admission,
                force_focus_rotation=bool(force_sprint_question),
            )
            agenda_phase = str(agenda_decision.get("phase") or "primary_depth")
            agenda_route = str(agenda_decision.get("route") or "phase_depth")
            agenda_reason = str(agenda_decision.get("reason") or agenda_route)
            selected_focus_key = str(agenda_decision.get("focus_key") or current_focus_key or "").strip()
            selected_focus_label = str(agenda_decision.get("focus_label") or current_focus_label or selected_focus_key).strip()
            selected_sub_focus_key = str(agenda_decision.get("sub_focus_key") or "").strip()
            selected_sub_focus_label = str(agenda_decision.get("sub_focus_label") or "").strip()
            selected_surface_kind = str(agenda_decision.get("surface_kind") or "").strip()
            selected_surface_key = str(agenda_decision.get("surface_key") or "").strip()
            if selected_focus_key and selected_focus_key != current_focus_key:
                current_focus_key = selected_focus_key
                current_focus_label = selected_focus_label
                focus_prompt_pack = _build_focus_prompt_pack(
                    state.get("interview_trajectory_map", {}),
                    focus_key=current_focus_key,
                    last_question=last_question,
                    answer=text,
                    history=history,
                )
                force_sprint_question = True
                pivoting = True
            if not bool(agenda_decision.get("allow_same_focus_probe", True)):
                clarification_probe = False
                deep_probe = False
            if agenda_route == "application_transfer_blocked":
                latest_app_state = await self.session_manager.get_state(session_id)
                if _application_transfer_served(latest_app_state) or latest_app_state.get("interview_complete"):
                    return
                if _application_transfer_ready(latest_app_state):
                    state = latest_app_state
                    agenda_route = "application_transfer"
                    agenda_phase = "application_transfer"
                    agenda_reason = "stale_pipeline_observed_application_transfer_ready"
            if agenda_route == "application_transfer_blocked":
                if not state.get("application_transfer_fallback_attempted"):
                    state["application_transfer_fallback_attempted"] = True
                    state["application_transfer_error"] = state.get("application_transfer_error") or (
                        "Primary application transfer anchor was not grounded in live answers."
                    )
                    await self.session_manager.save_state(session_id, state)
                    await self._generate_application_transfer(
                        session_id,
                        state,
                        allow_resume_anchor_fallback=True,
                        current_focus_key=current_focus_key,
                    )
                    state = await self.session_manager.get_state(session_id)
                    if _application_transfer_ready(state):
                        agenda_route = "application_transfer"
                        agenda_phase = "application_transfer"
                        agenda_reason = "resume_focus_fallback_application_transfer_ready"
                if agenda_route == "application_transfer_blocked":
                    error = state.get("application_transfer_error") or "Application transfer required by agenda but no grounded application question is ready."
                    state["application_transfer_error"] = str(error)
                    await self.session_manager.save_state(session_id, state)
                    raise RuntimeError(str(error))
            resume_context = _build_resume_context_for_followup(parsed_resume, resume)
            seed_followups: list[str] = []
            route_kind = "legacy_agenda_backup"
            trajectory_hint = select_from_trajectory_map_detailed(
                state.get("interview_trajectory_map", {}),
                sprint=sprint,
                focus_key=current_focus_key,
                answer=text,
                entities=entities or [],
                history=history,
                admission=honest_admission,
                has_discrepancy=discrepancy_conflict,
            )

            # If this answer was to the application-transfer question, score the
            # whole answer against the coverage lattice before selecting the next
            # coverage-guided follow-up.
            if answered_route_kind == "application_transfer" and isinstance(state.get("coverage_map"), dict):
                try:
                    _app_coverage = await self._evaluate_application_coverage(
                        state["coverage_map"],
                        text,
                    )
                    if _app_coverage:
                        from backend.models.coverage_map import AnswerCoverageMap as _ACMap
                        _app_cmap = _ACMap.from_dict(state["coverage_map"])
                        for _d in _app_cmap.dimensions:
                            if _d.id in _app_coverage:
                                _d.coverage_state = _app_coverage[_d.id]
                                _d.candidate_response = text[:500]
                        _app_cmap.compute_coverage_score()
                        state["coverage_map"] = _app_cmap.to_dict()
                        state["_last_coverage_dim_id"] = None
                        state["_last_coverage_recovery_depth"] = None
                        await self._trace(
                            session_id,
                            "application_coverage_evaluated",
                            turn_id=turn_id,
                            covered=sum(1 for v in _app_coverage.values() if v == "voluntary"),
                            dimensions=len(_app_cmap.dimensions),
                            coverage_score=round(_app_cmap.coverage_score, 3),
                        )
                except Exception as e:
                    await self._trace(
                        session_id,
                        "application_coverage_eval_failed",
                        turn_id=turn_id,
                        error_type=type(e).__name__,
                        error=str(e)[:300],
                        level="warn",
                    )
                    raise

            # ── Coverage routing after application transfer ───────────────────
            # When an AnswerCoverageMap exists and no forced rotation is active,
            # surface unsurfaced dimensions in weight order before normal routing.
            _coverage_question: str | None = None
            _coverage_route_kind: str | None = None
            if (
                _application_transfer_served(state)
                and state.get("coverage_map")
                and not state.get("_next_route_hint")
                and agenda_route == "coverage"
            ):
                from backend.models.coverage_map import AnswerCoverageMap as _ACMap
                _cmap = _ACMap.from_dict(state["coverage_map"])
                _last_dim_id = state.get("_last_coverage_dim_id")
                _last_recovery = state.get("_last_coverage_recovery_depth")

                if _last_dim_id and _last_recovery == "surface":
                    # Candidate named the concept on surface — one depth probe to confirm mechanism.
                    # text here is their response to the depth probe question asked last turn.
                    _cov_state, _ = await self._evaluate_coverage_dimension(
                        _last_dim_id, state["coverage_map"], text
                    )
                    for _d in _cmap.dimensions:
                        if _d.id == _last_dim_id:
                            _d.coverage_state = _cov_state
                            break
                    state["coverage_map"] = _cmap.to_dict()
                    state["_last_coverage_dim_id"] = None
                    state["_last_coverage_recovery_depth"] = None
                    # Fall through — no _coverage_question set; normal routing handles this turn.

                elif _last_dim_id:
                    # Classify the candidate's response to the previous surfacing question.
                    _cov_state, _rec_depth = await self._evaluate_coverage_dimension(
                        _last_dim_id, state["coverage_map"], text
                    )
                    _dim_depth_eligible = False
                    for _d in _cmap.dimensions:
                        if _d.id == _last_dim_id:
                            _dim_depth_eligible = bool(getattr(_d, "depth_eligible", False))
                            _d.coverage_state = _cov_state
                            break
                    state["coverage_map"] = _cmap.to_dict()

                    _arc = _ensure_application_transfer_arc(state)
                    _confirmed_depth = int(_arc.get("confirmed_depth_level") or 2)
                    if _rec_depth == "surface" and _dim_depth_eligible and int(_arc.get("depth_count") or 0) < 2 and _confirmed_depth >= 2:
                        # Named the concept without mechanism — generate depth probe next turn.
                        _dim = next((_d for _d in _cmap.dimensions if _d.id == _last_dim_id), None)
                        if _dim is not None:
                            _mark_coverage_depth_probe(state, _cmap, _dim)
                        # Generate the depth probe now so it's ready.
                        _coverage_question = await self.followup_agent.generate_coverage_depth_probe(
                            dimension_id=_last_dim_id,
                            coverage_map=_cmap,
                            candidate_surface_response=text,
                            state=state,
                        )
                        _coverage_route_kind = "coverage_depth_probe"
                    else:
                        # Dim fully resolved — clear state and surface next unsurfaced dim.
                        state["_last_coverage_dim_id"] = None
                        state["_last_coverage_recovery_depth"] = None
                        _unsurfaced = _cmap.unsurfaced_dimensions()
                        if _unsurfaced:
                            _unsurfaced.sort(key=lambda _d: _d.weight, reverse=True)
                            _next_dim = _unsurfaced[0]
                            _next_dim.surfacing_attempted = True
                            agenda_state = ensure_interview_agenda(state)
                            agenda_state["coverage_opening_count"] = int(agenda_state.get("coverage_opening_count") or 0) + 1
                            state["interview_agenda"] = agenda_state
                            _arc = _ensure_application_transfer_arc(state)
                            _arc["surface_count"] = int(_arc.get("surface_count") or 0) + 1
                            state["application_transfer_arc"] = _arc
                            state["_last_coverage_dim_id"] = _next_dim.id
                            state["coverage_map"] = _cmap.to_dict()
                            _coverage_question = await self.followup_agent.generate_coverage_surface(
                                dimension_id=_next_dim.id,
                                coverage_map=_cmap,
                                state=state,
                            )
                            _coverage_route_kind = "coverage_surface"
                        else:
                            _depth_dim_dict = _select_earned_coverage_depth_dimension(_cmap.to_dict(), state)
                            _depth_dim = None
                            if _depth_dim_dict:
                                _depth_id = str(_depth_dim_dict.get("id") or _depth_dim_dict.get("dimension_id") or "").strip()
                                _depth_dim = next((_d for _d in _cmap.dimensions if _d.id == _depth_id), None)
                            if _depth_dim is not None:
                                _mark_coverage_depth_probe(state, _cmap, _depth_dim)
                                _coverage_question = await self.followup_agent.generate_coverage_depth_probe(
                                    dimension_id=_depth_dim.id,
                                    coverage_map=_cmap,
                                    candidate_surface_response=_depth_dim.candidate_response or text,
                                    state=state,
                                )
                                _coverage_route_kind = "coverage_depth_probe"

                else:
                    # No previous dim in flight — surface the highest-weight unsurfaced dim.
                    _unsurfaced = _cmap.unsurfaced_dimensions()
                    if _unsurfaced:
                        _unsurfaced.sort(key=lambda _d: _d.weight, reverse=True)
                        _next_dim = _unsurfaced[0]
                        _next_dim.surfacing_attempted = True
                        agenda_state = ensure_interview_agenda(state)
                        agenda_state["coverage_opening_count"] = int(agenda_state.get("coverage_opening_count") or 0) + 1
                        state["interview_agenda"] = agenda_state
                        _arc = _ensure_application_transfer_arc(state)
                        _arc["surface_count"] = int(_arc.get("surface_count") or 0) + 1
                        state["application_transfer_arc"] = _arc
                        state["_last_coverage_dim_id"] = _next_dim.id
                        state["_last_coverage_recovery_depth"] = None
                        state["coverage_map"] = _cmap.to_dict()
                        _coverage_question = await self.followup_agent.generate_coverage_surface(
                            dimension_id=_next_dim.id,
                            coverage_map=_cmap,
                            state=state,
                        )
                        _coverage_route_kind = "coverage_surface"
                    else:
                        _depth_dim_dict = _select_earned_coverage_depth_dimension(_cmap.to_dict(), state)
                        _depth_dim = None
                        if _depth_dim_dict:
                            _depth_id = str(_depth_dim_dict.get("id") or _depth_dim_dict.get("dimension_id") or "").strip()
                            _depth_dim = next((_d for _d in _cmap.dimensions if _d.id == _depth_id), None)
                        if _depth_dim is not None:
                            _mark_coverage_depth_probe(state, _cmap, _depth_dim)
                            _coverage_question = await self.followup_agent.generate_coverage_depth_probe(
                                dimension_id=_depth_dim.id,
                                coverage_map=_cmap,
                                candidate_surface_response=_depth_dim.candidate_response or text,
                                state=state,
                            )
                            _coverage_route_kind = "coverage_depth_probe"

            # ── Route hint overrides (confession pivot / graceful exit) ─────────
            route_hint = state.pop("_next_route_hint", None)
            selected_map_result: dict | None = None
            if agenda_route == "application_anchor_recovery" and _application_anchor_recovery_ready(state) and not route_hint:
                next_question = _application_anchor_recovery_question(current_focus_label)
                route_kind = "application_anchor_recovery"
                pivoting = False
                state["application_anchor_recovery_served"] = True
            elif agenda_route == "application_grounding" and _application_grounding_ready(state) and not route_hint:
                arc = _ensure_application_transfer_arc(state)
                next_question = str(arc.get("grounding_question") or _coverage_grounding_question(state) or "").strip()
                if not next_question:
                    raise RuntimeError("Agenda selected application grounding but no grounding question was available.")
                route_kind = "application_grounding"
                pivoting = False
                arc["grounding_served"] = True
                state["application_transfer_arc"] = arc
            elif agenda_route == "application_transfer" and state.get("prepped_application_question") and not route_hint:
                next_question = str(state.get("prepped_application_question") or "").strip()
                if not next_question:
                    raise RuntimeError("Agenda selected application transfer but staged question was empty.")
                route_kind = "application_transfer"
                pivoting = False
            elif _coverage_question and _coverage_route_kind and not route_hint:
                next_question = _coverage_question
                route_kind = _coverage_route_kind
                pivoting = False
            elif agenda_route == "coverage" and not route_hint:
                next_visible_turn = _next_visible_turn_number(state, history)
                next_surface = next_secondary_surface(state, avoid_focus=current_focus_key)
                next_focus = str(next_surface.get("focus_key") or "").strip()
                next_label = str(next_surface.get("focus_label") or next_focus).strip()
                if not next_focus:
                    grounded_result = trajectory_hint
                    if (
                        grounded_result
                        and grounded_result.get("focus_key")
                        and grounded_result.get("focus_key") != current_focus_key
                    ):
                        grounded_result = None
                    if not grounded_result:
                        grounded_result = select_from_trajectory_map_detailed(
                            state.get("interview_trajectory_map", {}),
                            sprint=sprint,
                            focus_key=current_focus_key,
                            answer=text,
                            entities=entities or [],
                            history=history,
                            admission=honest_admission,
                            has_discrepancy=discrepancy_conflict,
                        )
                    if grounded_result and next_visible_turn < SYNTHESIS_START_FLOOR:
                        next_question = grounded_result["question"]
                        selected_map_result = grounded_result
                        route_kind = grounded_result["route_kind"]
                        agenda_phase = "primary_depth"
                    else:
                        third_surface_result = (
                            _select_third_surface_probe(
                                state,
                                history,
                                sprint=sprint,
                                avoid_focus=current_focus_key,
                                answer=text,
                                entities=entities or [],
                                admission=honest_admission,
                                has_discrepancy=discrepancy_conflict,
                                turn_number=turn_number,
                            )
                            if next_visible_turn < SYNTHESIS_START_FLOOR
                            else None
                        )
                        reserve_result = None
                        if not third_surface_result and next_visible_turn < SYNTHESIS_START_FLOOR:
                            reserve_result = _select_reserve_question(state, history, avoid_focus=current_focus_key)
                        if third_surface_result:
                            next_question = third_surface_result["question"]
                            selected_map_result = third_surface_result
                            route_kind = THIRD_SURFACE_ROUTE_KIND
                            agenda_phase = "primary_depth"
                        elif reserve_result:
                            next_question = reserve_result["question"]
                            selected_map_result = reserve_result
                            route_kind = reserve_result["route_kind"]
                            agenda_phase = "primary_depth"
                        else:
                            next_question = await self.followup_agent.generate_graceful_close(state, 0)
                            route_kind = "synthesis_close"
                            agenda_phase = "synthesis_close"
                else:
                    current_focus_key = next_focus
                    current_focus_label = next_label
                    focus_prompt_pack = _build_focus_prompt_pack(
                        state.get("interview_trajectory_map", {}),
                        focus_key=current_focus_key,
                        last_question=last_question,
                        answer=text,
                        history=history,
                    )
                    second_anchor_result = select_from_trajectory_map_detailed(
                        state.get("interview_trajectory_map", {}),
                        sprint=sprint,
                        focus_key=current_focus_key,
                        answer=text,
                        entities=entities or [],
                        history=history,
                        admission=honest_admission,
                        has_discrepancy=discrepancy_conflict,
                        preferred_sub_focus_key=str(next_surface.get("sub_focus_key") or "").strip(),
                        preferred_surface_kind=str(next_surface.get("surface_kind") or "").strip(),
                    )
                    third_surface_result = None
                    if bool(_second_anchor_turns(history)):
                        third_surface_result = _select_third_surface_probe(
                            state,
                            history,
                            sprint=sprint,
                            avoid_focus=answered_focus_key or current_focus_key,
                            answer=text,
                            entities=entities or [],
                            admission=honest_admission,
                            has_discrepancy=discrepancy_conflict,
                            turn_number=turn_number,
                        )
                    if third_surface_result and (
                        next_visible_turn >= SECOND_ANCHOR_START_FLOOR
                        or bool(_second_anchor_turns(history))
                    ):
                        next_question = third_surface_result["question"]
                        selected_map_result = third_surface_result
                        route_kind = THIRD_SURFACE_ROUTE_KIND
                        agenda_phase = "primary_depth"
                    elif second_anchor_result and (
                        next_visible_turn >= SECOND_ANCHOR_START_FLOOR
                        or bool(_second_anchor_turns(history))
                    ):
                        next_question = second_anchor_result["question"]
                        selected_map_result = second_anchor_result
                        selected_map_result["second_anchor_target"] = next_surface
                        route_kind = "second_anchor"
                        agenda_phase = "second_anchor"
                    else:
                        if next_visible_turn < SYNTHESIS_START_FLOOR:
                            current_focus_key = selected_focus_key or answered_focus_key or current_focus_key
                            current_focus_label = selected_focus_label or answered_focus_label or current_focus_label
                            grounded_result = select_from_trajectory_map_detailed(
                                state.get("interview_trajectory_map", {}),
                                sprint=sprint,
                                focus_key=current_focus_key,
                                answer=text,
                                entities=entities or [],
                                history=history,
                                admission=honest_admission,
                                has_discrepancy=discrepancy_conflict,
                            )
                            if grounded_result:
                                next_question = grounded_result["question"]
                                selected_map_result = grounded_result
                                route_kind = grounded_result["route_kind"]
                                agenda_phase = "primary_depth"
                            else:
                                third_surface_result = _select_third_surface_probe(
                                    state,
                                    history,
                                    sprint=sprint,
                                    avoid_focus=current_focus_key,
                                    answer=text,
                                    entities=entities or [],
                                    admission=honest_admission,
                                    has_discrepancy=discrepancy_conflict,
                                    turn_number=turn_number,
                                )
                                reserve_result = None
                                if not third_surface_result:
                                    reserve_result = _select_reserve_question(
                                        state,
                                        history,
                                        avoid_focus=current_focus_key,
                                    )
                                if third_surface_result:
                                    next_question = third_surface_result["question"]
                                    selected_map_result = third_surface_result
                                    route_kind = THIRD_SURFACE_ROUTE_KIND
                                    agenda_phase = "primary_depth"
                                elif reserve_result:
                                    next_question = reserve_result["question"]
                                    selected_map_result = reserve_result
                                    route_kind = reserve_result["route_kind"]
                                    agenda_phase = "primary_depth"
                                else:
                                    next_question = await self.followup_agent.generate_graceful_close(state, 0)
                                    route_kind = "synthesis_close"
                                    agenda_phase = "synthesis_close"
                        else:
                            next_question = await self.followup_agent.generate_graceful_close(state, 0)
                            route_kind = "synthesis_close"
                            agenda_phase = "synthesis_close"
                pivoting = True
            elif agenda_route in {"second_anchor", "focus_pivot"} and not route_hint:
                next_visible_turn = _next_visible_turn_number(state, history)
                second_anchor_target = {
                    "focus_key": current_focus_key,
                    "focus_label": current_focus_label,
                    "sub_focus_key": selected_sub_focus_key,
                    "sub_focus_label": selected_sub_focus_label,
                    "surface_kind": selected_surface_kind,
                    "surface_key": selected_surface_key,
                }
                third_surface_result = None
                if bool(_second_anchor_turns(history)):
                    third_surface_result = _select_third_surface_probe(
                        state,
                        history,
                        sprint=sprint,
                        avoid_focus=answered_focus_key or current_focus_key,
                        answer=text,
                        entities=entities or [],
                        admission=honest_admission,
                        has_discrepancy=discrepancy_conflict,
                        turn_number=turn_number,
                    )
                second_anchor_result = None if third_surface_result else _reselect_second_anchor_for_surface(
                    state,
                    history,
                    sprint=sprint,
                    target=second_anchor_target,
                    avoid_focus=answered_focus_key or "",
                    answer=text,
                    entities=entities or [],
                    admission=honest_admission,
                    has_discrepancy=discrepancy_conflict,
                )
                if third_surface_result and (
                    next_visible_turn >= SECOND_ANCHOR_START_FLOOR
                    or bool(_second_anchor_turns(history))
                ):
                    next_question = third_surface_result["question"]
                    selected_map_result = third_surface_result
                    route_kind = THIRD_SURFACE_ROUTE_KIND
                    agenda_phase = "primary_depth"
                elif second_anchor_result and (
                    next_visible_turn >= SECOND_ANCHOR_START_FLOOR
                    or bool(_second_anchor_turns(history))
                ):
                    next_question = second_anchor_result["question"]
                    route_kind = "second_anchor" if agenda_route == "second_anchor" or agenda_phase == "second_anchor" else "trajectory_map_focus_pivot"
                    selected_map_result = second_anchor_result
                else:
                    if next_visible_turn < SYNTHESIS_START_FLOOR:
                        grounded_result = select_from_trajectory_map_detailed(
                            state.get("interview_trajectory_map", {}),
                            sprint=sprint,
                            focus_key=answered_focus_key or current_focus_key,
                            answer=text,
                            entities=entities or [],
                            history=history,
                            admission=honest_admission,
                            has_discrepancy=discrepancy_conflict,
                        )
                        if grounded_result:
                            next_question = grounded_result["question"]
                            selected_map_result = grounded_result
                            route_kind = grounded_result["route_kind"]
                            agenda_phase = "primary_depth"
                        else:
                            third_surface_result = _select_third_surface_probe(
                                state,
                                history,
                                sprint=sprint,
                                avoid_focus=current_focus_key,
                                answer=text,
                                entities=entities or [],
                                admission=honest_admission,
                                has_discrepancy=discrepancy_conflict,
                                turn_number=turn_number,
                            )
                            reserve_result = None
                            if not third_surface_result:
                                reserve_result = _select_reserve_question(
                                    state,
                                    history,
                                    avoid_focus=current_focus_key,
                                )
                            if third_surface_result:
                                next_question = third_surface_result["question"]
                                selected_map_result = third_surface_result
                                route_kind = THIRD_SURFACE_ROUTE_KIND
                                agenda_phase = "primary_depth"
                            elif reserve_result:
                                next_question = reserve_result["question"]
                                selected_map_result = reserve_result
                                route_kind = reserve_result["route_kind"]
                                agenda_phase = "primary_depth"
                            else:
                                next_question = await self.followup_agent.generate_graceful_close(state, 0)
                                route_kind = "synthesis_close"
                                agenda_phase = "synthesis_close"
                    else:
                        next_question = await self.followup_agent.generate_graceful_close(state, 0)
                        route_kind = "synthesis_close"
                        agenda_phase = "synthesis_close"
                pivoting = True
            elif agenda_route == "synthesis_close" and not route_hint:
                next_visible_turn = _next_visible_turn_number(state, history)
                third_surface_result = (
                    _select_third_surface_probe(
                        state,
                        history,
                        sprint=sprint,
                        avoid_focus=current_focus_key,
                        answer=text,
                        entities=entities or [],
                        admission=honest_admission,
                        has_discrepancy=discrepancy_conflict,
                        turn_number=turn_number,
                    )
                    if next_visible_turn < SYNTHESIS_START_FLOOR
                    else None
                )
                reserve_result = None
                if not third_surface_result and next_visible_turn < SYNTHESIS_START_FLOOR:
                    reserve_result = _select_reserve_question(state, history, avoid_focus=current_focus_key)
                if third_surface_result:
                    next_question = third_surface_result["question"]
                    selected_map_result = third_surface_result
                    route_kind = THIRD_SURFACE_ROUTE_KIND
                    agenda_phase = "primary_depth"
                elif reserve_result:
                    next_question = reserve_result["question"]
                    selected_map_result = reserve_result
                    route_kind = reserve_result["route_kind"]
                    agenda_phase = "primary_depth"
                else:
                    close_count = _synthesis_close_count(history)
                    next_question = await self.followup_agent.generate_graceful_close(state, close_count)
                    route_kind = "graceful_exit" if close_count else "synthesis_close"
                pivoting = True
            elif agenda_route == "graceful_exit" and not route_hint:
                next_question = "Thanks, that gives me enough signal for now. We'll wrap here and generate the interview report."
                route_kind = "graceful_exit"
                pivoting = True
            elif route_hint == "confession_pivot":
                next_question = await self.followup_agent.generate_confession_pivot(
                    target_role=target_role,
                    resume_context=resume_context,
                )
                route_kind = "confession_pivot"
            elif route_hint == "graceful_exit":
                next_question = "Thanks, that gives me enough signal for now. We'll wrap here and generate the interview report."
                route_kind = "graceful_exit"
            elif discrepancy_conflict and not force_sprint_question:
                next_question = await self.followup_agent.generate_discrepancy_challenge(
                    question=last_question, answer=text, discrepancy=discrepancy,
                    persona=persona, resume=resume, parsed_resume=parsed_resume,
                    focus_context=focus_prompt_pack.get("prompt_context", ""),
                    resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                )
                route_kind = "discrepancy_challenge"

            elif clarification_probe and not force_sprint_question:
                next_question = await self.followup_agent.generate_clarification(
                    question=last_question,
                    answer=text,
                    weakness=weakness,
                    persona=persona,
                    resume=resume,
                    parsed_resume=parsed_resume,
                    focus_context=focus_prompt_pack.get("prompt_context", ""),
                    resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                )
                route_kind = "clarification_fast"

            elif deep_probe and not force_sprint_question:
                _tone_signal = str(state.pop("_reasoning_tone_signal", "") or "")
                next_question = await self.followup_agent.generate(
                    question=last_question, answer=text, weakness=weakness,
                    persona=persona, resume=resume, parsed_resume=parsed_resume,
                    focus_context=focus_prompt_pack.get("prompt_context", ""),
                    resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                    communication_mode=str((state.get("candidate_state") or {}).get("communication_mode", "normal")),
                    tone_signal=_tone_signal,
                )
                route_kind = "depth_probe"

            elif state.get("current_question_followups") and not _is_generic_fasttrack_route(
                (state.get("active_question_packet") or {}).get("route_kind")
            ):
                # A bank follow-up is queued — adapt it for the next turn
                raw_followup = state["current_question_followups"][0]  # peek only, don't pop
                next_question = await self.followup_agent.adapt_followup(
                    raw_followup=raw_followup,
                    question=last_question,
                    answer=text,
                    persona=persona,
                    resume_context=resume_context,
                    focus_context=focus_prompt_pack.get("prompt_context", ""),
                    resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                )
                route_kind = "bank_followup_fast"

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
                    focus_context=focus_prompt_pack.get("prompt_context", ""),
                    resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                    trajectory_hint_question=(trajectory_hint or {}).get("question", ""),
                    pivoting_hint=pivoting,
                )
                next_question, seed_followups = sprint_result
                route_kind = "legacy_agenda_backup"

            await self._trace(
                session_id,
                "bgpipeline_route_selected",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                route_kind=route_kind,
                pivoting=bool(pivoting),
                force_sprint_question=bool(force_sprint_question),
                repeated_focus=bool(repeated_focus),
                contradiction_budget_exhausted=bool(contradiction_budget_exhausted),
                deflection_budget_exhausted=bool(deflection_budget_exhausted),
                same_focus_recent=same_focus_recent,
                same_focus_confirmed=same_focus_confirmed,
                same_focus_deflections=same_focus_deflections,
                # C-3/C-4 additions: focus-area exhaustion signals
                focus_key=current_focus_key,
                answered_focus_key=answered_focus_key,
                ledger_focus_hits=_ledger_focus_hits,
                history_focus_turns=_history_focus_turns,
                history_focus_surfaces=_history_focus_surfaces,
                inferred_focus_key=_current_inferred_fk,
                consecutive_high_weakness_count=new_consecutive,
                weakness_type=weakness.get("type") if isinstance(weakness, dict) else None,
                weakness_severity=weakness.get("severity") if isinstance(weakness, dict) else None,
                discrepancy_conflict=discrepancy.get("conflict_level") if isinstance(discrepancy, dict) else None,
                followups_to_seed=len(seed_followups),
                agenda_phase=agenda_phase,
                agenda_route=agenda_route,
                agenda_reason=agenda_reason,
            )
            print(
                f"[BGPipeline] Turn {turn_number} → {route_kind} | "
                f"focus={current_focus_key!r} ledger_hits={_ledger_focus_hits} "
                f"hist_turns={_history_focus_turns} consec={new_consecutive} "
                f"pivot={pivoting}"
            )

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
            if route_kind == "bank_followup_fast":
                followups_to_store = list(state.get("current_question_followups", []))[1:3]
            elif route_kind in {"sprint_seed", "legacy_agenda_backup"}:
                followups_to_store = seed_followups[:2]
            else:
                followups_to_store = []

            # ── Write to staging fields only ──────────────────────────────────
            # Re-read state to pick up any handle_transcript changes since we started
            # (sprint advancement, question_count increment). This ensures our save
            # doesn't overwrite canonical counters with stale values.
            background_state_patch = {
                key: state.get(key)
                for key in (
                    "application_transfer_arc",
                    "coverage_map",
                    "_last_coverage_dim_id",
                    "_last_coverage_recovery_depth",
                    "interview_agenda",
                    "assessment_coverage",
                )
                if key in state
            }
            background_candidate_patch = {
                key: value
                for key, value in dict(state.get("candidate_state") or {}).items()
                if key in {
                    "implementation_anchor",
                    "anchor_confidence",
                    "application_transfer_depth_level",
                    "application_transfer_depth_terms",
                    "_save_face_pivot_used",
                    "communication_mode",
                    "forced_exit_triggered",
                }
            }
            state = await self.session_manager.get_state(session_id)

            if state.get("interview_complete"):
                return  # Interview ended while we were processing — discard

            if background_state_patch:
                state.update(background_state_patch)
            if background_candidate_patch:
                state.setdefault("candidate_state", {}).update(background_candidate_patch)

            # A slow background pipeline can decide to stage application transfer
            # after the fast path has already served it. Do not let stale work
            # re-stage the same application question; move directly into coverage
            # when an answer coverage map exists.
            if route_kind == "application_transfer" and _application_transfer_served(state):
                if isinstance(state.get("coverage_map"), dict):
                    from backend.models.coverage_map import AnswerCoverageMap as _ACMap

                    _cmap = _ACMap.from_dict(state["coverage_map"])
                    _unsurfaced = _cmap.unsurfaced_dimensions()
                    if _unsurfaced:
                        _unsurfaced.sort(key=lambda _d: _d.weight, reverse=True)
                        _next_dim = _unsurfaced[0]
                        _next_dim.surfacing_attempted = True
                        agenda_state = ensure_interview_agenda(state)
                        agenda_state["phase"] = "coverage_surface"
                        agenda_state["coverage_opening_count"] = int(agenda_state.get("coverage_opening_count") or 0) + 1
                        agenda_state["last_route_reason"] = "stale_application_transfer_stage_redirected_to_coverage"
                        state["interview_agenda"] = agenda_state
                        _arc = _ensure_application_transfer_arc(state)
                        _arc["surface_count"] = int(_arc.get("surface_count") or 0) + 1
                        state["application_transfer_arc"] = _arc
                        state["_last_coverage_dim_id"] = _next_dim.id
                        state["_last_coverage_recovery_depth"] = None
                        state["coverage_map"] = _cmap.to_dict()
                        next_question = await self.followup_agent.generate_coverage_surface(
                            dimension_id=_next_dim.id,
                            coverage_map=_cmap,
                            state=state,
                        )
                        route_kind = "coverage_surface"
                        agenda_phase = "coverage_surface"
                        agenda_reason = "stale_application_transfer_stage_redirected_to_coverage"
                        pivoting = False
                    else:
                        _depth_dim_dict = _select_earned_coverage_depth_dimension(_cmap.to_dict(), state)
                        _depth_dim = None
                        if _depth_dim_dict:
                            _depth_id = str(_depth_dim_dict.get("id") or _depth_dim_dict.get("dimension_id") or "").strip()
                            _depth_dim = next((_d for _d in _cmap.dimensions if _d.id == _depth_id), None)
                        if _depth_dim is not None:
                            _mark_coverage_depth_probe(state, _cmap, _depth_dim)
                            next_question = await self.followup_agent.generate_coverage_depth_probe(
                                dimension_id=_depth_dim.id,
                                coverage_map=_cmap,
                                candidate_surface_response=_depth_dim.candidate_response,
                                state=state,
                            )
                            route_kind = "coverage_depth_probe"
                            agenda_phase = "coverage_depth"
                            agenda_reason = "stale_application_transfer_stage_redirected_to_depth_probe"
                            pivoting = False
                        else:
                            return
                else:
                    return

            latest_turn_versions = dict(state.get("latest_turn_versions", {}))
            latest_known_version = _coerce_positive_int(
                latest_turn_versions.get(turn_id),
                default=answer_version,
            )
            if turn_id and answer_version < latest_known_version:
                print(
                    f"[BGPipeline] Discarding stale revision for turn_id {turn_id}: "
                    f"v{answer_version} < latest v{latest_known_version}"
                )
                await self._trace(
                    session_id,
                    "bgpipeline_discarded_stale_revision",
                    turn_id=turn_id,
                    turn_number=turn_number,
                    answer_version=answer_version,
                    latest_known_version=latest_known_version,
                    level="warn",
                )
                return

            if route_kind == "second_anchor":
                history_now = list(state.get("history", []) or history or [])
                provisional_packet = {
                    "route_kind": "second_anchor",
                    "focus_key": str((selected_map_result or {}).get("focus_key") or current_focus_key or "").strip(),
                    "focus_label": str((selected_map_result or {}).get("focus_label") or current_focus_label or "").strip(),
                    "sub_focus_key": str((selected_map_result or {}).get("sub_focus_key") or selected_sub_focus_key or "").strip(),
                    "sub_focus_label": str((selected_map_result or {}).get("sub_focus_label") or selected_sub_focus_label or "").strip(),
                    "surface_kind": str((selected_map_result or {}).get("surface_kind") or selected_surface_kind or "").strip(),
                }
                block_reason = _second_anchor_packet_block_reason(
                    provisional_packet,
                    history_now,
                    _evidence_question_count(state),
                )
                if block_reason:
                    replacement = _reselect_second_anchor_for_surface(
                        state,
                        history_now,
                        sprint=sprint,
                        target=_second_anchor_target_from_packet(provisional_packet),
                        avoid_focus=answered_focus_key or current_focus_key or "",
                        answer=text,
                        entities=entities or [],
                        admission=honest_admission,
                        has_discrepancy=discrepancy_conflict,
                    )
                    replacement_packet = {
                        "route_kind": "second_anchor",
                        "focus_key": str((replacement or {}).get("focus_key") or "").strip(),
                        "focus_label": str((replacement or {}).get("focus_label") or "").strip(),
                        "sub_focus_key": str((replacement or {}).get("sub_focus_key") or "").strip(),
                        "sub_focus_label": str((replacement or {}).get("sub_focus_label") or "").strip(),
                        "surface_kind": str((replacement or {}).get("surface_kind") or "").strip(),
                    }
                    if (
                        replacement
                        and not _question_already_asked(str(replacement.get("question") or ""), history_now)
                        and not _second_anchor_packet_block_reason(
                            replacement_packet,
                            history_now,
                            _evidence_question_count(state),
                        )
                    ):
                        next_question = str(replacement.get("question") or "").strip()
                        selected_map_result = replacement
                        route_kind = "second_anchor"
                        agenda_phase = "second_anchor"
                        agenda_reason = f"second_anchor_reselected_after_{block_reason}"
                        pivoting = True
                        await self._trace(
                            session_id,
                            "second_anchor_reselected_before_stage",
                            turn_id=turn_id,
                            turn_number=turn_number,
                            reason=block_reason,
                            replacement_focus_key=str(replacement.get("focus_key") or ""),
                            replacement_sub_focus_key=str(replacement.get("sub_focus_key") or ""),
                        )
                    else:
                        reserve_result = _select_reserve_question(
                            state,
                            history_now,
                            avoid_focus=str(provisional_packet.get("focus_key") or current_focus_key or ""),
                        )
                        next_visible_turn = _next_visible_turn_number(state, history_now)
                        if reserve_result and next_visible_turn < SYNTHESIS_START_FLOOR:
                            next_question = reserve_result["question"]
                            selected_map_result = reserve_result
                            route_kind = reserve_result["route_kind"]
                            agenda_phase = "primary_depth"
                            agenda_reason = f"second_anchor_retired_to_reserve_after_{block_reason}"
                            pivoting = True
                            await self._trace(
                                session_id,
                                "second_anchor_replaced_with_reserve_before_stage",
                                turn_id=turn_id,
                                turn_number=turn_number,
                                reason=block_reason,
                                reserve_focus_key=str(reserve_result.get("focus_key") or ""),
                            )
                        else:
                            close_count = _synthesis_close_count(history_now)
                            next_question = await self.followup_agent.generate_graceful_close(state, close_count)
                            selected_map_result = None
                            route_kind = "graceful_exit" if close_count else "synthesis_close"
                            agenda_phase = "synthesis_close"
                            agenda_reason = f"second_anchor_retired_to_close_after_{block_reason}"
                            pivoting = True
                            await self._trace(
                                session_id,
                                "second_anchor_replaced_with_close_before_stage",
                                turn_id=turn_id,
                                turn_number=turn_number,
                                reason=block_reason,
                                close_route=route_kind,
                            )

            queue = [
                item
                for item in state.get("prepped_turn_queue", [])
                if not (
                    item.get("turn_id") == turn_id
                    and _staged_answer_version(item) <= answer_version
                )
            ]
            queue.append({
                "turn_id": turn_id,
                "turn_number": turn_number,
                "answer_version": answer_version,
                "analysis": {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "turn_number": turn_number,
                    "answer_version": answer_version,
                    "question": last_question,
                    "answer": text,
                    "weakness": weakness,
                    "concepts": concepts,
                    "discrepancy": discrepancy,
                    "reasoning_behavior": reasoning,
                    "sprint": sprint,
                    "persona": persona,
                    "focus_key": answered_focus_key,
                    "focus_label": answered_focus_label,
                    "sub_focus_key": answered_sub_focus_key,
                    "sub_focus_label": answered_sub_focus_label,
                    "surface_kind": str((state.get("current_answer_context") or {}).get("surface_kind") or ""),
                    "coverage_dimension_id": str((state.get("current_answer_context") or {}).get("coverage_dimension_id") or ""),
                    "coverage_dimension_label": str((state.get("current_answer_context") or {}).get("coverage_dimension_label") or ""),
                    "candidate_model_updates": candidate_model_updates,
                },
                "metadata": {
                    "pivoting": pivoting,
                    "route_kind": route_kind,
                    "consecutive_high_weakness_count": new_consecutive,
                    "last_weakness_type": wtype,
                    "current_question_followups": followups_to_store,
                    "current_question_followup_asked": False,
                    "answer_version": answer_version,
                    "agenda_phase": agenda_phase,
                    "agenda_reason": agenda_reason,
                },
            })
            state["prepped_turn_queue"] = queue

            if turn_number >= state.get("prepped_next_question_turn_number", 0):
                packet_extra: dict = {}
                if route_kind == "application_anchor_recovery":
                    packet_extra.update({
                        "question_posture": "clarify",
                        "signal_goal": "Recover one grounded transfer anchor from vague early answers before using resume fallback.",
                        "expected_space": [
                            "decision",
                            "metric",
                            "tradeoff",
                            "personal contribution",
                        ],
                        "information_gain": "high",
                        "voice_complexity": "low",
                    })
                if route_kind == "application_grounding":
                    packet_extra.update({
                        "question_posture": "clarify",
                        "signal_goal": "Calibrate which depth layer the candidate actually worked at before application transfer.",
                        "expected_space": [
                            "decision/framing",
                            "operating workflow",
                            "specialized internals",
                            "something else",
                        ],
                    })
                selected_coverage_dimension_id = (
                    str((selected_map_result or {}).get("coverage_dimension_id") or "").strip()
                    or str(state.get("_last_coverage_dim_id") or "").strip()
                )
                if route_kind in {"coverage_surface", "coverage_depth_probe"}:
                    packet_extra.update(
                        _coverage_dimension_packet_kwargs(
                            state.get("coverage_map"),
                            selected_coverage_dimension_id,
                        )
                    )
                packet_focus_key = str(
                    (selected_map_result or {}).get("focus_key")
                    or current_focus_key
                    or ""
                ).strip()
                packet_focus_label = str(
                    (selected_map_result or {}).get("focus_label")
                    or current_focus_label
                    or ""
                ).strip()
                next_sub_focus_key = str((selected_map_result or {}).get("sub_focus_key") or "").strip()
                next_sub_focus_label = str((selected_map_result or {}).get("sub_focus_label") or "").strip()
                if not next_sub_focus_key and route_kind not in {"coverage_surface", "coverage_depth_probe"}:
                    next_sub_focus_key, next_sub_focus_label = _infer_sub_focus(
                        state.get("interview_trajectory_map", {}),
                        packet_focus_key,
                        next_question,
                        "",
                    )
                if route_kind in {"coverage_surface", "coverage_depth_probe"} and selected_coverage_dimension_id:
                    packet_extra.setdefault("coverage_dimension_id", selected_coverage_dimension_id)
                    packet_extra.setdefault(
                        "coverage_dimension_label",
                        str((selected_map_result or {}).get("coverage_dimension_label") or selected_coverage_dimension_id),
                    )
                packet_extra = {
                    **_question_packet_ladder_kwargs(selected_map_result),
                    **packet_extra,
                }
                packet_extra.setdefault(
                    "question_posture",
                    str((selected_map_result or {}).get("question_posture") or ""),
                )
                state["prepped_next_question"] = next_question
                state["prepped_next_question_turn_number"] = turn_number
                state["prepped_next_context"] = {
                    "pivoting": pivoting,
                    "route_kind": route_kind,
                    "weakness": weakness,
                    "discrepancy": discrepancy,
                    "turn_id": turn_id,
                    "answer_version": answer_version,
                }
                state["prepped_next_packet"] = _build_question_packet(
                    question_text=next_question,
                    sprint=sprint,
                    route_kind=route_kind,
                    parsed_resume=parsed_resume,
                    resume=resume,
                    followups=followups_to_store,
                    pivoting=pivoting,
                    weakness=weakness,
                    discrepancy=discrepancy,
                    source_turn_number=turn_number,
                    focus_key_override=packet_focus_key,
                    focus_label_override=packet_focus_label,
                    sub_focus_key_override=next_sub_focus_key,
                    sub_focus_label_override=next_sub_focus_label,
                    **packet_extra,
                )
            policy_check = self.policy_checker_agent.check(
                state,
                next_packet=state.get("prepped_next_packet") or {},
                next_route_kind=route_kind,
                agenda_phase=agenda_phase,
                agenda_reason=agenda_reason,
                turn_number=turn_number,
            )
            state["last_policy_check"] = policy_check
            policy_events = [
                item for item in state.get("policy_checker_events", [])
                if isinstance(item, dict)
            ]
            policy_events.append(
                {
                    "turn_id": turn_id,
                    "turn_number": turn_number,
                    "answer_version": answer_version,
                    "route_kind": route_kind,
                    "agenda_phase": agenda_phase,
                    "policy_status": policy_check.get("policy_status"),
                    "warning_codes": list(policy_check.get("primary_warning_codes") or []),
                    "warnings": list(policy_check.get("warnings") or [])[:5],
                    "metrics": dict(policy_check.get("metrics") or {}),
                }
            )
            state["policy_checker_events"] = policy_events[-50:]
            state["policy_warning_count"] = sum(
                len(item.get("warnings") or [])
                for item in state["policy_checker_events"]
                if isinstance(item, dict)
            )
            await self._trace(
                session_id,
                "policy_checker_warning" if policy_check.get("warnings") else "policy_checker_ok",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                route_kind=route_kind,
                agenda_phase=agenda_phase,
                policy_status=policy_check.get("policy_status"),
                warning_codes=list(policy_check.get("primary_warning_codes") or []),
                metrics=dict(policy_check.get("metrics") or {}),
            )
            state["prepped_turn_analysis"] = {
                "session_id": session_id,
                "turn_id": turn_id,
                "turn_number": turn_number,
                "answer_version": answer_version,
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
                "sub_focus_key": answered_sub_focus_key,
                "sub_focus_label": answered_sub_focus_label,
                "surface_kind": str((state.get("current_answer_context") or {}).get("surface_kind") or ""),
                "question_posture": str((state.get("current_answer_context") or {}).get("question_posture") or ""),
                "signal_goal": str((state.get("current_answer_context") or {}).get("signal_goal") or ""),
                "expected_space": list((state.get("current_answer_context") or {}).get("expected_space") or [])[:4],
                "covered_expected_space": list((state.get("current_answer_context") or {}).get("covered_expected_space") or [])[:4],
                "missing_expected_space": list((state.get("current_answer_context") or {}).get("missing_expected_space") or [])[:4],
                "coverage_dimension_id": str((state.get("current_answer_context") or {}).get("coverage_dimension_id") or ""),
                "coverage_dimension_label": str((state.get("current_answer_context") or {}).get("coverage_dimension_label") or ""),
                "candidate_model_updates": candidate_model_updates,
                "policy_check": policy_check,
            }
            state["prepped_next_metadata"] = {
                "pivoting": pivoting,
                "route_kind": route_kind,
                "consecutive_high_weakness_count": new_consecutive,
                "last_weakness_type": wtype,
                "current_question_followups": followups_to_store,
                "current_question_followup_asked": False,
                "answer_version": answer_version,
                "agenda_phase": agenda_phase,
                "agenda_reason": agenda_reason,
                "policy_check": policy_check,
            }

            await self.session_manager.save_state(session_id, state)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            print(f"[BGPipeline] Turn {turn_number} complete — {route_kind} staged in {elapsed_ms}ms for {session_id}")
            await self._trace(
                session_id,
                "bgpipeline_staged",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                route_kind=route_kind,
                followups_staged=len(followups_to_store),
                prepped_question_chars=len(next_question),
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                agenda_phase=agenda_phase,
                agenda_reason=agenda_reason,
            )

            # Pre-generate TTS audio for the staged question so the /tts call
            # on the next turn hits cache instead of waiting for live synthesis.
            if self.tts_service:
                await self._trace(
                    session_id,
                    "bgpipeline_tts_pregen_dispatched",
                    turn_id=turn_id,
                    turn_number=turn_number,
                    answer_version=answer_version,
                    route_kind=route_kind,
                )
                asyncio.create_task(self.tts_service.pre_generate(session_id, next_question))

        except Exception as e:
            print(f"[BGPipeline] Failed for session {session_id}: {e}")
            await self._trace(
                session_id,
                "bgpipeline_failed",
                turn_id=turn_id,
                turn_number=turn_number,
                answer_version=answer_version,
                level="error",
                error_type=type(e).__name__,
                error=str(e)[:300],
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
            raise
        finally:
            # Always release the inflight slot so exact-version retries can rerun if needed.
            self._pipeline_inflight.discard(pipeline_key)
            # Release turn-level guard so the next distinct turn can run.
            self._turn_pipeline_running.get(session_id, set()).discard(turn_id)

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
        started_at = time.perf_counter()
        try:
            state = await self.session_manager.get_state(session_id)
            resume_context = _build_resume_context_for_followup(
                state.get("parsed_resume"), state.get("resume", "")
            )
            seed_followups: list[str] = []
            question = await asyncio.wait_for(
                self.followup_agent.generate_seed_question(
                    sprint=1,
                    persona="curious_lead",
                    resume_context=resume_context,
                ),
                timeout=8.0,
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
                "route_kind": "seed_first_followup",
                "weakness": None,
                "discrepancy": None,
                "turn_id": "",
            }
            state["prepped_next_packet"] = _build_question_packet(
                question_text=question,
                sprint=1,
                route_kind="seed_first_followup",
                parsed_resume=state.get("parsed_resume"),
                resume=state.get("resume", ""),
                followups=seed_followups[:2],
                source_turn_number=0,
            )
            await self.session_manager.save_state(session_id, state)
            print(f"[Seed] Turn 1 follow-up pre-seeded for {session_id}")
            await self._trace(
                session_id,
                "seed_first_question_ready",
                route_kind="seed_first_followup",
                question_chars=len(question),
                followups_seeded=len(seed_followups[:2]),
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
        except Exception as e:
            print(f"[Seed] Failed to pre-seed first question: {e}")
            await self._trace(
                session_id,
                "seed_first_question_failed",
                level="warn",
                error_type=type(e).__name__,
                error=str(e)[:300],
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
            raise

    async def _build_interview_map(self, session_id: str, max_wait_seconds: float = MAP_PREP_TIMEOUT_SECONDS) -> bool:
        """
        Strict map-preparation phase.

        Product contract:
        - build the interview map before the interview can start
        - keep hydrating until the map is rich and validated, or fail preparation
        - no deterministic fallback: an invalid LLM map fails startup
        """
        started_at = time.perf_counter()
        try:
            state = await self.session_manager.get_state(session_id)
            if state.get("interview_map_status") == "ready" and state.get("interview_trajectory_map"):
                return True
            resume = state.get("resume", "")
            deadline = time.perf_counter() + max_wait_seconds
            map_source = "llm"
            state["interview_map_status"] = "preparing"
            state["interview_map_error"] = ""
            await self.session_manager.save_state(session_id, state)
            interview_map = await asyncio.wait_for(
                generate_interview_map(
                    resume=resume,
                    session_id=session_id,
                    target_role=state.get("target_role", ""),
                ),
                timeout=min(MAP_PREP_GENERATE_TIMEOUT_SECONDS, max_wait_seconds),
            )
            if not interview_map:
                await self._trace(session_id, "interview_map_empty", level="warn",
                              elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3))
                return False

            validation = validate_interview_map(
                interview_map,
                require_all_llm=False,
                min_llm_branch_ratio=MAP_PREP_MIN_LLM_BRANCH_RATIO,
            )
            # Synchronous fix-up only for the startup-critical priority areas (0-1).
            # Remaining areas (2-4) are fired as background tasks to not block interview start.
            focus_reports = list(validation.get("focus_reports", []) or [])
            priority_unready = [
                str(r.get("focus_key", "") or "")
                for r in focus_reports[:MAP_STARTUP_FOCUS_AREAS]
                if not bool(r.get("ready")) and str(r.get("focus_key", "") or "")
            ]
            background_unready = [
                str(r.get("focus_key", "") or "")
                for r in focus_reports[MAP_STARTUP_FOCUS_AREAS:]
                if not bool(r.get("ready")) and str(r.get("focus_key", "") or "")
            ]
            pending_async_hydration = [
                str(key)
                for key in (interview_map.get("pending_hydration_focus_keys", []) or [])
                if str(key)
            ]

            hydration_passes = 0
            while priority_unready and time.perf_counter() < deadline and hydration_passes < MAP_PREP_MAX_HYDRATION_PASSES:
                hydrated = await hydrate_interview_map_tracks(
                    interview_map=interview_map,
                    resume=resume,
                    session_id=session_id,
                    focus_keys=priority_unready,
                )
                hydration_passes += 1
                interview_map = hydrated if isinstance(hydrated, dict) else interview_map
                validation = validate_interview_map(
                    interview_map,
                    require_all_llm=False,
                    min_llm_branch_ratio=MAP_PREP_MIN_LLM_BRANCH_RATIO,
                )
                focus_reports = list(validation.get("focus_reports", []) or [])
                priority_unready = [
                    str(r.get("focus_key", "") or "")
                    for r in focus_reports[:MAP_STARTUP_FOCUS_AREAS]
                    if not bool(r.get("ready")) and str(r.get("focus_key", "") or "")
                ]
                await self._trace(
                    session_id,
                    "interview_map_hydration_pass",
                    pass_number=hydration_passes,
                    pending_focuses=len(priority_unready),
                    llm_focuses=int(validation.get("llm_focus_count", 0) or 0),
                    rich_focuses=int(validation.get("rich_focus_count", 0) or 0),
                    ready=bool(validation.get("ready")),
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                )

            # Fire remaining areas after the launch map is saved below. Starting
            # the task before persistence can race and make hydration read an
            # empty session map, silently losing deferred surfaces.
            background_targets = pending_async_hydration or background_unready

            state = await self.session_manager.get_state(session_id)
            if state.get("interview_complete"):
                return False
            state["interview_trajectory_map"] = interview_map
            state["interview_map_validation"] = validation
            state["interview_agenda"] = initial_interview_agenda(interview_map)

            focus_count = len(interview_map.get("focus_areas", []))
            preview = [
                {
                    "label": str(area.get("label", "") or ""),
                    "focus_key": str(area.get("focus_key", "") or ""),
                    "opener": _track_opener(area),
                    "dimension_count": len(_track_dimensions(area)),
                    "track_source": str(area.get("track_source", "") or ""),
                    "track_schema": str(area.get("track_schema", "") or ""),
                    "map_schema_version": str(area.get("map_schema_version", "") or ""),
                    "primary_question_contract": str(area.get("primary_question_contract", "") or ""),
                    "llm_branch_count": int(area.get("llm_branch_count", 0) or 0),
                }
                for area in interview_map.get("focus_areas", [])[:3]
            ]

            if validation.get("ready"):
                state["interview_map_status"] = "ready"
                state["interview_map_error"] = ""
                state["interview_map_prepared_at"] = time.time()
                await self.session_manager.save_state(session_id, state)
                if background_targets:
                    self._hydration_inflight.add(session_id)
                    asyncio.create_task(
                        self._hydrate_interview_map(session_id, background_targets),
                        name=f"hydrate_bg_{session_id[:8]}",
                    )
                await self._trace(
                    session_id,
                    "interview_map_ready",
                    map_source=map_source,
                    focus_areas=focus_count,
                    llm_focuses=int(validation.get("llm_focus_count", 0) or 0),
                    rich_focuses=int(validation.get("rich_focus_count", 0) or 0),
                    launch_ready=bool(interview_map.get("launch_ready")),
                    full_map_ready=bool(interview_map.get("full_map_ready")),
                    pending_async_hydration=len(pending_async_hydration),
                    focus_preview=preview,
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                )
                return focus_count > 0

            errors = list(validation.get("errors", []) or [])
            state["interview_map_status"] = "failed"
            state["interview_map_error"] = "; ".join(errors[:4]) or "Interview map did not reach validated ready state."
            await self.session_manager.save_state(session_id, state)
            await self._trace(
                session_id,
                "interview_map_validation_failed",
                level="warn",
                map_source=map_source,
                focus_areas=focus_count,
                llm_focuses=int(validation.get("llm_focus_count", 0) or 0),
                rich_focuses=int(validation.get("rich_focus_count", 0) or 0),
                error_count=len(errors),
                first_error=errors[0][:200] if errors else "",
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
            return False
        except Exception as e:
            error_text = str(e).strip() or type(e).__name__
            diagnostics = getattr(e, "diagnostics", {}) if isinstance(e, MapPreparationError) else {}
            try:
                setattr(e, "session_id", session_id)
                if diagnostics:
                    setattr(e, "diagnostics", diagnostics)
            except Exception:
                pass
            print(f"[TrajectoryMap] Build failed for {session_id[:8]}: {error_text}")
            try:
                state = await self.session_manager.get_state(session_id)
                state["interview_map_status"] = "failed"
                state["interview_map_error"] = error_text[:300]
                if diagnostics:
                    state["interview_map_failure_diagnostics"] = diagnostics
                await self.session_manager.save_state(session_id, state)
            except Exception:
                pass
            await self._trace(session_id, "interview_map_failed", level="warn",
                              error=error_text[:200],
                              has_diagnostics=bool(diagnostics),
                              diagnostic_cause=(diagnostics.get("cause", "")[:200] if isinstance(diagnostics, dict) else ""),
                              elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3))
            raise

    async def _hydrate_interview_map(self, session_id: str, focus_keys: list[str]) -> None:
        started_at = time.perf_counter()
        try:
            state = await self.session_manager.get_state(session_id)
            if state.get("interview_complete"):
                return
            interview_map = state.get("interview_trajectory_map", {})
            if not interview_map:
                return
            hydrated = await hydrate_interview_map_tracks(
                interview_map=interview_map,
                resume=state.get("resume", ""),
                session_id=session_id,
                focus_keys=focus_keys,
            )
            if not isinstance(hydrated, dict):
                return
            state = await self.session_manager.get_state(session_id)
            if state.get("interview_complete"):
                return
            state["interview_trajectory_map"] = hydrated
            state["interview_map_validation"] = validate_interview_map(
                hydrated,
                require_all_llm=False,
                min_llm_branch_ratio=MAP_PREP_MIN_LLM_BRANCH_RATIO,
            )
            ensure_interview_agenda(state)
            await self.session_manager.save_state(session_id, state)
            remaining = list(hydrated.get("pending_hydration_focus_keys", []) or [])
            await self._trace(
                session_id,
                "interview_map_hydrated",
                hydrated_focuses=max(len(focus_keys) - len(remaining), 0),
                remaining_focuses=len(remaining),
                quarantined_focuses=len(hydrated.get("map_quarantine", []) or []),
                full_map_ready=bool(hydrated.get("full_map_ready")),
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
        except Exception as exc:
            await self._trace(
                session_id,
                "interview_map_hydration_failed",
                level="warn",
                error_type=type(exc).__name__,
                error=str(exc)[:300],
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
        finally:
            self._hydration_inflight.discard(session_id)

    async def _run_speculative_generation(
        self,
        session_id: str,
        partial_text: str,
        new_entities: set,
        admission: bool = False,
        turn_id: str = "",
        is_final: bool = True,
        snapshot_seq: int = 0,
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
                # Use the active packet's known focus rather than noisy text inference.
                # Text inference can drift and re-emit the current opener as a "new" candidate.
                active_packet = state.get("active_packet") or {}
                focus_key = (
                    str(active_packet.get("focus_key_override") or active_packet.get("focus_key") or "").strip()
                    or _infer_focus(
                        state.get("last_question", ""),
                        partial_text,
                        state.get("parsed_resume"),
                        state.get("resume", ""),
                    )[0]
                )
                focus_prompt_pack = _build_focus_prompt_pack(
                    state.get("interview_trajectory_map", {}),
                    focus_key=focus_key,
                    last_question=state.get("last_question", ""),
                    answer=partial_text,
                    history=state.get("history", []),
                )
                # Include last_question as a synthetic already-asked guard so we never
                # re-emit the active opener (it's not in history yet during partial transcripts).
                last_q = state.get("last_question", "")
                history_with_current = list(state.get("history", []))
                if last_q:
                    history_with_current = history_with_current + [{"question": last_q}]
                map_candidate = select_from_trajectory_map_detailed(
                    state.get("interview_trajectory_map", {}),
                    sprint=sprint,
                    focus_key=focus_key,
                    answer=partial_text,
                    entities=list(new_entities),
                    history=history_with_current,
                    admission=admission,
                    has_discrepancy=False,
                    branch_hint="if_honest_gap" if admission else "",
                )
                cache = state.get("speculative_cache", {})
                now = time.time()
                current_best_question = ""

                if cache.get("turn_id") and cache.get("turn_id") != turn_id:
                    cache = {}
                else:
                    current_best_question = str(cache.get("best_ready_question", "") or "").strip()

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
                    "last_snapshot_seq": snapshot_seq,
                    "last_snapshot_is_final": is_final,
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
                current_best_question=current_best_question,
                focus_context=focus_prompt_pack.get("prompt_context", ""),
                resume_snippets=focus_prompt_pack.get("resume_snippets", []),
                current_map_candidate=(map_candidate or {}).get("question", ""),
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

                resolved_question = str(question.get("question", "") or "").strip()
                if question.get("action") == "keep" and cache.get("best_ready_question"):
                    resolved_question = str(cache.get("best_ready_question", "") or "").strip()

                state["speculative_cache"] = {
                    **cache,
                    "best_ready_question": resolved_question or str(cache.get("best_ready_question", "") or ""),
                    "last_snapshot_seq": snapshot_seq,
                    "last_snapshot_is_final": is_final,
                    "last_refine_action": question.get("action", "replace"),
                    "inflight": False,
                }
                await self.session_manager.save_state(session_id, state)
            trigger = "admission" if admission else f"entities: {new_entities}"
            if not new_entities and not admission:
                trigger = "rolling_interim" if not is_final else "final_snapshot"
            print(
                f"[Speculative] v{version} staged ({trigger}, action={question.get('action', 'replace')}) "
                f"for {session_id}"
            )

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

        Sprints are persona/pressure stages only. The interview agenda is owned by
        the trajectory map, application-transfer, coverage, and weakness routes; this
        method must never inject or overwrite the next question.
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
        state["persona_transition_note"] = (
            f"Sprint {prior_sprint} complete; persona advanced to {next_persona}. "
            "Next question remains owned by the active agenda route."
        )
        return True, ""

    def _is_complete(self, state: dict) -> bool:
        """Interview ends when sprint 3 is exhausted, 30 minutes elapsed, or terminal admission."""
        if state.get("question_count", 0) <= 0:
            return False
        if state.get("question_count", 0) >= MIN_COMPLETION_TURNS:
            state["assessment_coverage"] = _assessment_coverage(state)
            agenda = ensure_interview_agenda(state)
            agenda["phase"] = "complete"
            agenda["completion_eligible"] = True
            agenda["close_reason"] = "15_turn_cap"
            state["interview_agenda"] = agenda
            return True
        if state["current_sprint"] == 3 and state["sprint_question_count"] >= QUESTIONS_PER_SPRINT:
            state["assessment_coverage"] = _assessment_coverage(state)
            return True
        elapsed_minutes = (time.time() - state["interview_start_time"]) / 60
        if elapsed_minutes >= MAX_INTERVIEW_MINUTES:
            state["assessment_coverage"] = _assessment_coverage(state)
            return True
        # Terminal admission: 2+ consecutive turns where candidate explicitly admitted they
        # cannot answer (admitted_gap with structure_score == 0). Continuing past this point
        # produces a degraded experience — evaluation already has enough signal.
        history = state.get("history", [])
        if len(history) >= 2:
            last_two = history[-2:]
            if all(
                isinstance(h.get("reasoning_behavior"), dict)
                and h["reasoning_behavior"].get("adaptability") == "admitted_gap"
                and h["reasoning_behavior"].get("structure_score", 5) <= 1
                for h in last_two
            ):
                print(f"[Complete] Terminal admission detected after {len(history)} turns — ending interview")
                return True
        return False

    async def get_session_state(self, session_id: str) -> dict:
        return await self.session_manager.get_state(session_id)
