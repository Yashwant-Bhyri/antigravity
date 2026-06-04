from __future__ import annotations

import re
import time
from typing import Any

from backend.models.action_deck import (
    ActionDeck,
    ActionMove,
    DeliveryPolicy,
    SpokenQuestionCommit,
    VoicePolicyDecision,
)


BLOCKING_WARNING_DECISIONS = {
    "same_surface_streak": "REQUIRE_PIVOT",
    "late_generic_route": "REQUIRE_PIVOT",
    "map_focus_missing": "FAIL_CLOSED",
    "coverage_skipped_after_application": "REQUIRE_PIVOT",
    "second_anchor_overused": "REQUIRE_PIVOT",
    "second_anchor_streak": "REQUIRE_PIVOT",
}

RECOVERY_REASONS = {
    "map_not_ready",
    "empty_deck",
    "policy_blocked_move",
    "same_surface_streak",
    "second_anchor_streak",
    "unclear_audio",
    "candidate_interrupted_ai",
    "candidate_confused",
    "long_silence",
    "provider_disconnect",
    "spoken_commit_missing",
    "semantic_drift_rejected",
    "duplicate_closing",
}

INTERACTION_EVENTS = {
    "repeat_requested",
    "slow_down_requested",
    "candidate_confused",
    "candidate_interrupted_ai",
    "ai_speech_interrupted",
    "pause_requested",
    "resume_requested",
    "long_silence",
    "unclear_audio",
}


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _slug(value: object) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "move"


def _word_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(token) > 2
    }


def _jaccard(a: str, b: str) -> float:
    left = _word_set(a)
    right = _word_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _move_type(route_kind: str, question: str) -> str:
    route = route_kind.strip()
    if route in {"complete"}:
        return "closing"
    if route in {"echo_guard", "recovery", "voice_recovery"}:
        return "recovery"
    if route in {"operational", "voice_operational"}:
        return "operational"
    if route in {"repeat", "rephrase", "slow_down", "pause"}:
        return "interaction"
    if not question:
        return "recovery"
    return "assessment"


def _counts_as_assessment(move_type: str, route_kind: str) -> bool:
    if move_type in {"interaction", "recovery", "operational"}:
        return False
    if route_kind in {"complete", "echo_guard"}:
        return False
    return True


def _question_terms(question: str) -> list[str]:
    tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]*", question) if len(token) > 3]
    keep: list[str] = []
    for token in tokens:
        lower = token.lower()
        if lower in {"what", "when", "where", "which", "would", "could", "should", "your", "that", "this", "with", "from", "into", "were", "have", "does"}:
            continue
        if token not in keep:
            keep.append(token)
        if len(keep) >= 5:
            break
    return keep


class VoicePolicyKernel:
    """Backend-owned policy surface for Realtime voice delivery."""

    def compile_action_deck(self, state: dict[str, Any], *, turn_id: str = "") -> ActionDeck:
        session_id = str(state.get("session_id") or "")
        status = "ready"
        degraded_reason = ""

        map_status = str(state.get("interview_map_status") or "").strip()
        if not state.get("interview_started") and map_status not in {"ready", "prepared", ""}:
            status = "no_launch"
            degraded_reason = "map_not_ready"
        elif map_status in {"failed", "error"}:
            status = "failed_closed"
            degraded_reason = "map_not_ready"

        packet = self._selected_packet(state)
        selected_move = self._move_from_packet(packet, state, source="active_question_packet") if packet else None
        if not selected_move:
            status = "empty" if status == "ready" else status
            degraded_reason = degraded_reason or "empty_deck"

        policy_check = state.get("last_policy_check") if isinstance(state.get("last_policy_check"), dict) else {}
        warnings = list(policy_check.get("warnings") or [])
        constraints = [
            {
                "code": str(warning.get("code") or ""),
                "severity": str(warning.get("severity") or ""),
                "suggested_action": str(warning.get("suggested_action") or ""),
            }
            for warning in warnings
            if isinstance(warning, dict)
        ]

        deck = ActionDeck(
            deck_id=f"deck_{session_id}_{int(time.time() * 1000)}",
            session_id=session_id,
            turn_id=turn_id or str(state.get("current_answer_turn_id") or ""),
            status=status,
            selected_move=selected_move,
            reserve_moves=self._reserve_moves(state),
            recovery_moves=self._recovery_moves(state, degraded_reason),
            delivery_policy=self._delivery_policy(selected_move),
            candidate_state_summary=self._candidate_summary(state),
            policy_constraints=constraints,
            do_not_do=[
                "Do not invent technical interview questions outside approved moves.",
                "Do not reveal route kind, score, weakness, map, policy, or evaluator state.",
                "Do not add a second follow-up without a new backend deck.",
                "Do not treat confusion, repeat, slowdown, pause, or bad audio as assessment evidence.",
                "Do not continue after FAIL_CLOSED.",
            ],
            small_resume_snippet_cards=self._resume_cards(state),
            expires_after_turn=int(state.get("question_count") or 0) + 1,
            degraded_reason=degraded_reason,
        )
        state["active_action_deck"] = deck.model_dump()
        return deck

    def decide(
        self,
        state: dict[str, Any],
        deck: ActionDeck,
        *,
        event_type: str = "",
        require_spoken_question: bool = False,
    ) -> VoicePolicyDecision:
        move = deck.selected_move
        warnings = deck.policy_constraints
        warning_codes = [warning.get("code", "") for warning in warnings]

        if deck.status in {"no_launch", "failed_closed"}:
            return self._decision("FAIL_CLOSED", deck, "map_not_ready", warnings=warnings)
        if deck.status == "empty" or not move:
            return self._decision("REQUIRE_RECOVERY", deck, "empty_deck", recovery_reason="empty_deck", warnings=warnings)
        if require_spoken_question and move.counts_as_assessment_turn and not self.has_spoken_commit_for_current_question(state):
            return self._decision(
                "REQUIRE_RECOVERY",
                deck,
                "spoken_commit_missing",
                recovery_reason="spoken_commit_missing",
                warnings=warnings,
            )
        if event_type in INTERACTION_EVENTS:
            if event_type in {"candidate_confused", "repeat_requested", "slow_down_requested"}:
                return self._decision("REQUIRE_REPHRASE", deck, event_type, warnings=warnings)
            return self._decision("ALLOW_INTERACTION", deck, event_type, warnings=warnings)

        duplicate_close = self._is_duplicate_closing(state, move)
        if duplicate_close:
            return self._decision(
                "REQUIRE_RECOVERY",
                deck,
                "duplicate_closing",
                recovery_reason="duplicate_closing",
                warnings=warnings,
            )

        for code in warning_codes:
            decision = BLOCKING_WARNING_DECISIONS.get(code)
            if decision:
                return self._decision(
                    decision,
                    deck,
                    code,
                    recovery_reason=code if decision in {"REQUIRE_RECOVERY", "FAIL_CLOSED"} else "",
                    blocked_warning_codes=[code],
                    warnings=warnings,
                )

        if self._needs_rephrase(move):
            return self._decision("REQUIRE_REPHRASE", deck, "delivery_complexity_or_grammar", warnings=warnings)

        if move.move_type in {"interaction", "operational"}:
            return self._decision("ALLOW_INTERACTION", deck, "non_counting_move", warnings=warnings)
        if move.move_type == "recovery":
            return self._decision("REQUIRE_RECOVERY", deck, "recovery_move", recovery_reason="policy_blocked_move", warnings=warnings)
        return self._decision("ALLOW_ASSESSMENT", deck, "approved_assessment_move", warnings=warnings)

    def commit_spoken_question(
        self,
        state: dict[str, Any],
        commit: SpokenQuestionCommit,
    ) -> tuple[SpokenQuestionCommit, VoicePolicyDecision | None]:
        deck = self._deck_from_state(state)
        move = self._find_move(deck, commit.selected_move_id)
        backend_question = _clean_text(commit.backend_question or (move.question if move else ""))
        spoken_text = _clean_text(commit.spoken_text)
        drift_score = _jaccard(backend_question, spoken_text)
        preserve_ok = True
        if move:
            preserve_ok = all(term.lower() in spoken_text.lower() for term in move.must_preserve[:3])

        intent_preserved = bool(spoken_text) and bool(backend_question) and drift_score >= 0.35 and preserve_ok
        updated = commit.model_copy(
            update={
                "backend_question": backend_question,
                "spoken_text": spoken_text,
                "route_kind": commit.route_kind or (move.route_kind if move else ""),
                "backend_intent_preserved": intent_preserved,
                "semantic_drift_score": round(drift_score, 4),
                "spoken_at_ms": commit.spoken_at_ms or int(time.time() * 1000),
            }
        )

        if not intent_preserved:
            decision = self._decision(
                "REQUIRE_RECOVERY",
                deck,
                "semantic_drift_rejected",
                recovery_reason="semantic_drift_rejected",
            )
            state.setdefault("voice_policy_events", []).append(decision.model_dump())
            return updated, decision

        commits = [item for item in state.get("spoken_question_commits", []) if isinstance(item, dict)]
        commits.append(updated.model_dump())
        state["spoken_question_commits"] = commits[-100:]
        state["last_question"] = spoken_text
        state["current_answer_response"] = spoken_text
        active_packet = state.get("active_question_packet")
        if isinstance(active_packet, dict):
            active_packet["question_text"] = spoken_text
        state["voice_last_spoken_question"] = updated.model_dump()
        return updated, None

    def has_spoken_commit_for_current_question(self, state: dict[str, Any]) -> bool:
        last_question = _clean_text(state.get("last_question") or state.get("current_answer_response") or "")
        if not last_question:
            return False
        for commit in reversed(state.get("spoken_question_commits") or []):
            if not isinstance(commit, dict):
                continue
            if _clean_text(commit.get("spoken_text")) == last_question:
                return True
        return False

    def recovery_deck(self, state: dict[str, Any], reason: str, *, turn_id: str = "") -> ActionDeck:
        reason = reason if reason in RECOVERY_REASONS else "policy_blocked_move"
        deck = self.compile_action_deck(state, turn_id=turn_id)
        deck.status = "degraded"
        deck.degraded_reason = reason
        deck.selected_move = deck.recovery_moves[0] if deck.recovery_moves else None
        if not deck.selected_move:
            deck.status = "failed_closed"
            deck.degraded_reason = "empty_deck"
        state["active_action_deck"] = deck.model_dump()
        return deck

    def _decision(
        self,
        status: str,
        deck: ActionDeck,
        reason_code: str,
        *,
        recovery_reason: str = "",
        blocked_warning_codes: list[str] | None = None,
        warnings: list[dict[str, Any]] | None = None,
    ) -> VoicePolicyDecision:
        move = deck.selected_move
        return VoicePolicyDecision(
            status=status,  # type: ignore[arg-type]
            reason_code=reason_code,
            selected_move_id=move.move_id if move else "",
            recovery_reason=recovery_reason,
            requires_spoken_commit=bool(move and move.counts_as_assessment_turn and status == "ALLOW_ASSESSMENT"),
            one_question_only=deck.delivery_policy.one_question_only,
            max_sentences=deck.delivery_policy.max_sentences,
            instructions=self._instructions(status, reason_code),
            blocked_warning_codes=list(blocked_warning_codes or []),
            warnings=list(warnings or []),
        )

    def _instructions(self, status: str, reason_code: str) -> str:
        if status == "ALLOW_ASSESSMENT":
            return "Speak exactly one approved assessment move, then wait for the candidate."
        if status == "ALLOW_INTERACTION":
            return "Handle the operational interaction without advancing assessment state."
        if status == "REQUIRE_REPHRASE":
            return "Simplify or repeat the same backend-approved question; do not add a new probe."
        if status == "REQUIRE_CONTINUATION":
            return "Ask one short same-turn continuation from the approved move only."
        if status == "REQUIRE_PIVOT":
            return "Do not ask the selected move; request or use a distinct approved reserve/recovery move."
        if status == "REQUIRE_RECOVERY":
            return f"Use a recovery move for {reason_code}; do not evaluate candidate content yet."
        if status == "REQUIRE_PAUSE":
            return "Pause the interview and wait for backend or user recovery."
        return "Fail closed; do not continue the live interview."

    def _selected_packet(self, state: dict[str, Any]) -> dict[str, Any]:
        active = state.get("active_question_packet")
        if isinstance(active, dict) and _clean_text(active.get("question_text")):
            return active
        prepped = state.get("prepped_next_packet")
        if isinstance(prepped, dict) and _clean_text(prepped.get("question_text")):
            return prepped
        question = _clean_text(state.get("last_question"))
        if question:
            return {
                "question_text": question,
                "route_kind": state.get("current_answer_context", {}).get("route_kind", "unknown")
                if isinstance(state.get("current_answer_context"), dict)
                else "unknown",
            }
        return {}

    def _move_from_packet(self, packet: dict[str, Any], state: dict[str, Any], *, source: str) -> ActionMove | None:
        question = _clean_text(packet.get("question_text") or packet.get("question"))
        if not question:
            return None
        route_kind = str(packet.get("route_kind") or "unknown")
        move_type = _move_type(route_kind, question)
        move_id = f"{source}_{_slug(route_kind)}_{_slug(packet.get('focus_key') or 'general')}"
        voice_complexity = str(packet.get("voice_complexity") or "")
        policy_risk = "high" if route_kind in {"legacy_agenda_backup", "sprint_seed"} else "medium" if voice_complexity == "medium" else "low"
        return ActionMove(
            move_id=move_id,
            move_type=move_type,  # type: ignore[arg-type]
            question=question,
            counts_as_assessment_turn=_counts_as_assessment(move_type, route_kind),
            route_kind=route_kind,
            agenda_phase=str(packet.get("agenda_phase") or state.get("interview_agenda", {}).get("phase") or ""),
            focus_key=str(packet.get("focus_key") or ""),
            focus_label=str(packet.get("focus_label") or ""),
            coverage_dimension_id=str(packet.get("coverage_dimension_id") or ""),
            coverage_dimension_label=str(packet.get("coverage_dimension_label") or ""),
            question_posture=str(packet.get("question_posture") or ""),
            signal_goal=str(packet.get("signal_goal") or ""),
            expected_space=[str(item) for item in list(packet.get("expected_space") or [])[:4]],
            voice_complexity=voice_complexity,
            allowed_rephrase_scope="simplify" if voice_complexity == "medium" else "light",
            must_preserve=_question_terms(question),
            invalid_if=["already_answered", "policy_blocked", "candidate_confused_without_rephrase"],
            policy_risk=policy_risk,  # type: ignore[arg-type]
            source=source,
        )

    def _reserve_moves(self, state: dict[str, Any]) -> list[ActionMove]:
        moves: list[ActionMove] = []
        prepped = state.get("prepped_next_packet")
        if isinstance(prepped, dict) and _clean_text(prepped.get("question_text")):
            move = self._move_from_packet(prepped, state, source="prepped_next_packet")
            if move:
                moves.append(move)
        active = state.get("active_question_packet")
        followups = active.get("followups") if isinstance(active, dict) else []
        for idx, followup in enumerate(followups or []):
            text = _clean_text(followup)
            if not text:
                continue
            packet = dict(active or {})
            packet["question_text"] = text
            packet["route_kind"] = packet.get("route_kind") or "interaction_followup"
            move = self._move_from_packet(packet, state, source=f"followup_{idx}")
            if move:
                moves.append(move)
        return moves[:4]

    def _recovery_moves(self, state: dict[str, Any], degraded_reason: str = "") -> list[ActionMove]:
        last_question = _clean_text(state.get("last_question") or state.get("current_answer_response"))
        reason = degraded_reason or "policy_blocked_move"
        question = "I need a moment to recover the interview state before we continue."
        if reason in {"candidate_confused", "semantic_drift_rejected"} and last_question:
            question = f"Let me ask that more simply: {last_question}"
        elif reason in {"candidate_interrupted_ai", "unclear_audio"} and last_question:
            question = f"I may have cut that off. Let me restate it: {last_question}"
        elif reason == "long_silence":
            question = "Take your time. If it helps, answer with the concrete example first."
        elif last_question:
            question = f"Let's reset this cleanly. {last_question}"
        return [
            ActionMove(
                move_id=f"recovery_{_slug(reason)}",
                move_type="recovery",
                question=question,
                counts_as_assessment_turn=False,
                route_kind="voice_recovery",
                allowed_rephrase_scope="simplify",
                must_preserve=_question_terms(last_question),
                policy_risk="low",
                source="recovery_deck",
            )
        ]

    def _delivery_policy(self, move: ActionMove | None) -> DeliveryPolicy:
        max_sentences = 2
        if move and move.voice_complexity == "medium":
            max_sentences = 3
        if move and move.move_type in {"interaction", "recovery", "operational"}:
            max_sentences = 1
        return DeliveryPolicy(max_sentences=max_sentences)

    def _candidate_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate = state.get("candidate_state") if isinstance(state.get("candidate_state"), dict) else {}
        return {
            "engagement": candidate.get("engagement", "normal"),
            "communication_mode": candidate.get("communication_mode", "normal"),
            "confidence_signal": candidate.get("confidence_signal", "unclear"),
            "topic_fatigue": candidate.get("topic_fatigue", "unknown"),
            "question_count": state.get("question_count", 0),
        }

    def _resume_cards(self, state: dict[str, Any]) -> list[dict[str, str]]:
        cards: list[dict[str, str]] = []
        target_role = _clean_text(state.get("target_role"))
        if target_role:
            cards.append({"id": "target_role", "text": target_role[:160]})
        parsed = state.get("parsed_resume") if isinstance(state.get("parsed_resume"), dict) else {}
        skills = parsed.get("skills") if isinstance(parsed.get("skills"), list) else []
        if skills:
            cards.append({"id": "skills", "text": ", ".join(str(skill) for skill in skills[:8])[:220]})
        return cards[:3]

    def _deck_from_state(self, state: dict[str, Any]) -> ActionDeck:
        raw = state.get("active_action_deck")
        if isinstance(raw, dict):
            try:
                return ActionDeck.model_validate(raw)
            except Exception:
                pass
        return self.compile_action_deck(state)

    def _find_move(self, deck: ActionDeck, move_id: str) -> ActionMove | None:
        for move in [deck.selected_move, *deck.reserve_moves, *deck.recovery_moves]:
            if move and move.move_id == move_id:
                return move
        return deck.selected_move

    def _needs_rephrase(self, move: ActionMove) -> bool:
        words = move.question.split()
        if len(words) > 80:
            return True
        if len(words) > 55 and move.voice_complexity not in {"medium", "high"}:
            return True
        lower = move.question.lower()
        return " did as " in lower or " which exact table fields did as " in lower

    def _is_duplicate_closing(self, state: dict[str, Any], move: ActionMove) -> bool:
        if move.route_kind not in {"complete", "synthesis_close", "graceful_exit"}:
            return False
        history = [turn for turn in state.get("history", []) if isinstance(turn, dict)]
        if not history:
            return False
        tail_routes = [str(turn.get("route_kind") or "") for turn in history[-2:]]
        if move.route_kind == "complete" and tail_routes and tail_routes[-1] == "complete":
            return True
        if move.route_kind == "synthesis_close" and tail_routes.count("synthesis_close") >= 1:
            return True
        return False
