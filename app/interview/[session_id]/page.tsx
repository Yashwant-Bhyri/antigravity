"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { InterviewSession, processTurn, prefetchAudio, prefetchFillerAudio, playAudioUrl, FloorState, trackInterviewEvent } from "@/lib/audio";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSeverityPip, AGSprintDivider, AGSurface } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";
import { AIOrb, Waveform } from "@/components/Waveform";

type Phase = "idle" | "listening" | "thinking" | "speaking";

type Message = {
  role: "ai" | "candidate";
  text: string;
  severity?: string;
  isSprintMarker?: boolean;
  isPivotMarker?: boolean;
  sprint?: number;
};

type SessionHistoryEntry = {
  question: string;
  answer: string;
  weakness?: { severity?: string } | null;
  sprint?: number;
};

type SessionSnapshot = {
  question_count?: number;
  interview_complete?: boolean;
  resume?: string;
  github_links?: string[];
  target_role?: string;
  years_experience?: string;
  current_sprint?: number;
  current_persona?: string;
  last_question?: string;
  history?: SessionHistoryEntry[];
  interview_trajectory_map?: { focus_areas?: unknown[] };
  external_handoff?: {
    provider?: string;
    handoff_id?: string;
    provenhire_interview_id?: string;
    return_url?: string;
  };
};

type AnswerDraft = {
  turnId: string;
  textParts: string[];
  entitySet: Set<string>;
  submittedText: string | null;
  pendingRevision: boolean;
  requestVersion: number;
  messageIndex: number | null;
  commitTimer: ReturnType<typeof setTimeout> | null;
};

const SPRINT_LABELS: Record<number, string> = {
  1: "Project Defense",
  2: "Foundations",
  3: "System Design",
};

const PERSONA_DESC: Record<string, string> = {
  curious_lead: "Challenging your ownership",
  socratic_mentor: "Testing first principles",
  senior_peer: "Stress-testing your design",
};

const API = getApiBaseUrl();
// Small settle window so duplicate/late flushes on the same natural answer still
// merge before we call processTurn.
const ANSWER_SETTLE_MS = 700;
const TTS_HOLD_CAP_MS = 2500;

function buildMessagesFromHistory(history: SessionHistoryEntry[] = []): Message[] {
  const restored: Message[] = [];
  let lastSprint = 1;

  history.forEach((turn, index) => {
    const turnSprint = turn.sprint ?? lastSprint;

    if (index > 0 && turnSprint !== lastSprint) {
      restored.push({
        role: "ai",
        text: `Sprint ${turnSprint} — ${SPRINT_LABELS[turnSprint]}`,
        isSprintMarker: true,
        sprint: turnSprint,
      });
    }

    restored.push({ role: "ai", text: turn.question, severity: turn.weakness?.severity });
    restored.push({ role: "candidate", text: turn.answer });
    lastSprint = turnSprint;
  });

  return restored;
}

export default function InterviewPage() {
  const { session_id } = useParams<{ session_id: string }>();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [partial, setPartial] = useState("");
  const [sprint, setSprint] = useState(1);
  const [persona, setPersona] = useState("curious_lead");
  const [questionCount, setQuestionCount] = useState(0);
  const [micLevel, setMicLevel] = useState(0);
  const [started, setStarted] = useState(false);
  const [complete, setComplete] = useState(false);
  const [nearEnd, setNearEnd] = useState(false);
  const [error, setError] = useState("");
  const [showCamera, setShowCamera] = useState(true);
  const [sessionSnapshot, setSessionSnapshot] = useState<SessionSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [bootingMode, setBootingMode] = useState<"new" | "resume" | "fresh" | null>(null);

  const sessionRef = useRef<InterviewSession | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const prevSprintRef = useRef(1);
  const stopVisualizerRef = useRef<(() => void) | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const processingRef = useRef(false);
  const currentTurnIdRef = useRef("");
  const answerDraftRef = useRef<AnswerDraft | null>(null);
  // Set true when we have a real end-of-utterance confirmation. That lets us skip
  // the defensive TTS hold on normal turns while still protecting safety-timeout flushes.
  const silenceConfirmedRef = useRef(false);
  // Timestamp when the current turn was committed (for TTS hold cap).
  const commitTimeRef = useRef(0);

  const clearAnswerDraft = useCallback(() => {
    const draft = answerDraftRef.current;
    if (draft?.commitTimer) clearTimeout(draft.commitTimer);
    answerDraftRef.current = null;
  }, []);

  const getExternalReturnUrl = useCallback(() => {
    const fromState = sessionSnapshot?.external_handoff?.return_url?.trim();
    if (fromState) return fromState;
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(`ag:return-url:${session_id}`) || "";
  }, [sessionSnapshot, session_id]);

  const beginUserTurn = useCallback((session: InterviewSession | null) => {
    if (!session) return;
    clearAnswerDraft();
    silenceConfirmedRef.current = false;
    commitTimeRef.current = 0;
    const turnId = crypto.randomUUID();
    currentTurnIdRef.current = turnId;
    session.setActiveTurnId(turnId);
    session.transition(FloorState.USER_SPEAKING);
  }, [clearAnswerDraft]);

  // Guard against malformed URLs (e.g. /interview/undefined)
  useEffect(() => {
    if (!session_id || session_id === "undefined") router.replace("/");
  }, [session_id, router]);

  const stopCameraStream = useCallback(() => {
    if (videoRef.current?.srcObject) {
      (videoRef.current.srcObject as MediaStream).getTracks().forEach((track) => track.stop());
      videoRef.current.srcObject = null;
    }
  }, []);

  const ensureMediaPermissions = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser cannot request microphone and camera permissions.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    stream.getTracks().forEach((track) => track.stop());
  }, []);

  const teardownActiveSession = useCallback(() => {
    currentTurnIdRef.current = crypto.randomUUID();
    clearAnswerDraft();
    stopVisualizerRef.current?.();
    stopVisualizerRef.current = null;
    sessionRef.current?.stop();
    sessionRef.current = null;
    stopCameraStream();
  }, [clearAnswerDraft, stopCameraStream]);

  const resetInterviewUi = useCallback(() => {
    setPhase("idle");
    setMessages([]);
    setPartial("");
    setSprint(1);
    setPersona("curious_lead");
    setQuestionCount(0);
    setMicLevel(0);
    setStarted(false);
    setComplete(false);
    setError("");
    prevSprintRef.current = 1;
    processingRef.current = false;
    clearAnswerDraft();
  }, [clearAnswerDraft]);

  const fetchSessionSnapshot = useCallback(async (): Promise<SessionSnapshot | null> => {
    if (!session_id || session_id === "undefined") return null;

    const res = await fetch(`${API}/state/${session_id}`, { cache: "no-store" });
    if (res.status === 404) {
      router.replace("/");
      return null;
    }
    if (!res.ok) {
      throw new Error(`Could not load session ${session_id}: ${res.status}`);
    }
    return res.json();
  }, [router, session_id]);

  useEffect(() => {
    let cancelled = false;

    async function loadSnapshot() {
      if (!session_id || session_id === "undefined") return;

      teardownActiveSession();
      resetInterviewUi();
      setBootingMode(null);
      setSessionSnapshot(null);
      setSnapshotLoading(true);

      try {
        const snapshot = await fetchSessionSnapshot();
        if (!cancelled && snapshot) {
          setSessionSnapshot(snapshot);
        }
      } catch (e) {
        if (!cancelled) {
          setError(`Could not load interview state: ${String(e)}`);
        }
      } finally {
        if (!cancelled) setSnapshotLoading(false);
      }
    }

    loadSnapshot();

    return () => {
      cancelled = true;
      teardownActiveSession();
    };
  }, [fetchSessionSnapshot, resetInterviewUi, session_id, teardownActiveSession]);

  // Notify parent frame (e.g. ProvenHire iframe wrapper) that this page is ready.
  // The parent responds with PROVENHIRE_AUTH carrying the user's JWT.
  useEffect(() => {
    if (snapshotLoading) return;
    if (window.parent !== window) {
      window.parent.postMessage({ type: "ANTIGRAVITY_READY" }, "*");
    }
  }, [snapshotLoading]);

  // Auto-scroll
  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, partial]);

  // handleFollowup accepts a pre-fetched audioUrl so it can play immediately with zero lag.
  const handleFollowup = useCallback(async (
    result: Record<string, unknown>,
    preloadedAudioUrl: string | null,
    expectedTurnId: string,
  ) => {
    if (expectedTurnId !== currentTurnIdRef.current) {
      trackInterviewEvent(session_id, "ui_followup_discarded_stale", {
        turn_id: expectedTurnId,
      }, "frontend.ui", "warn");
      if (preloadedAudioUrl) URL.revokeObjectURL(preloadedAudioUrl);
      return;
    }

    if (sessionRef.current?.floor === FloorState.USER_SPEAKING) {
      trackInterviewEvent(session_id, "ui_followup_discarded_user_speaking", {
        turn_id: expectedTurnId,
      }, "frontend.ui", "warn");
      if (preloadedAudioUrl) URL.revokeObjectURL(preloadedAudioUrl);
      return;
    }

    const text = result.response as string;
    const newSprint = result.sprint as number;
    const newPersona = result.persona as string;
    const isComplete = result.complete as boolean;
    const weakness = result.weakness as { severity?: string } | null;
    const pivoting = result.pivoting as boolean;
    const backendQuestionCount = typeof result.question_count === "number" ? result.question_count : null;

    if (backendQuestionCount !== null && backendQuestionCount >= 13 && !isComplete) {
      setNearEnd(true);
    }

    // ── Silence confirmation hold ─────────────────────────────────────────────
    // Normal path: a Deepgram UtteranceEnd-backed final marks the turn as settled,
    // so we can speak immediately. Safety-timeout flushes stay defensive: hold
    // playback until we either see true silence confirmation or the cap elapses.
    // UI state is only committed after this resolves so phantom questions do not
    // appear if the turn gets reopened mid-hold.
    if (!silenceConfirmedRef.current) {
      const holdStartedAt = performance.now();
      const elapsed = performance.now() - commitTimeRef.current;
      const remaining = Math.max(0, TTS_HOLD_CAP_MS - elapsed);
      if (remaining > 0) {
        await new Promise<void>((resolve) => {
          const interval = setInterval(() => {
            const speaking = sessionRef.current?.floor === FloorState.USER_SPEAKING;
            const done = silenceConfirmedRef.current || speaking ||
              (performance.now() - commitTimeRef.current >= TTS_HOLD_CAP_MS);
            if (done) { clearInterval(interval); resolve(); }
          }, 40);
          setTimeout(() => { clearInterval(interval); resolve(); }, remaining);
        });
        trackInterviewEvent(session_id, "ui_followup_hold_resolved", {
          turn_id: expectedTurnId,
          hold_ms: Math.round(performance.now() - holdStartedAt),
          silence_confirmed: silenceConfirmedRef.current,
          floor_after_hold: sessionRef.current?.floor ?? "unknown",
        }, "frontend.ui");
      }
    }

    // Bail if candidate started speaking during the hold window.
    // Re-read floor into a local var — TypeScript narrows the ref type after the
    // early guard above and won't re-widen it across the await boundary.
    const floorAfterHold = sessionRef.current?.floor as FloorState | undefined;
    if (floorAfterHold === FloorState.USER_SPEAKING) {
      trackInterviewEvent(session_id, "ui_followup_revoked_during_hold", {
        turn_id: expectedTurnId,
      }, "frontend.ui", "warn");
      if (preloadedAudioUrl) URL.revokeObjectURL(preloadedAudioUrl);
      return;
    }
    if (expectedTurnId !== currentTurnIdRef.current) {
      trackInterviewEvent(session_id, "ui_followup_stale_after_hold", {
        turn_id: expectedTurnId,
      }, "frontend.ui", "warn");
      if (preloadedAudioUrl) URL.revokeObjectURL(preloadedAudioUrl);
      return;
    }

    // Commit all UI state only after hold confirmed and turn is not revoked.
    // Pivot marker, sprint transition, AI message, and questionCount all go here
    // to prevent phantom UI entries if the turn was revoked mid-hold.
    if (pivoting) {
      setMessages((prev) => [...prev, {
        role: "ai",
        text: "Moving to a different area.",
        isPivotMarker: true,
      }]);
    }

    if (newSprint !== prevSprintRef.current) {
      prevSprintRef.current = newSprint;
      setSprint(newSprint);
      setPersona(newPersona);
      setMessages((prev) => [...prev, {
        role: "ai",
        text: `Sprint ${newSprint} — ${SPRINT_LABELS[newSprint]}`,
        isSprintMarker: true,
        sprint: newSprint,
      }]);
    }

    setMessages((prev) => [...prev, {
      role: "ai",
      text,
      severity: weakness?.severity,
    }]);
    setQuestionCount((c) => c + 1);

    // Create abort controller for interruption
    const ac = new AbortController();
    sessionRef.current?.setAbortController(ac);
    sessionRef.current?.setActivePlaybackText(text);
    sessionRef.current?.transition(FloorState.AI_SPEAKING);

    try {
      await playAudioUrl(preloadedAudioUrl, text, ac.signal);
    } catch (e) {
      console.log("[UI] Audio play interrupted/failed", e);
      trackInterviewEvent(session_id, "ui_followup_playback_error", {
        turn_id: expectedTurnId,
        error: String(e),
      }, "frontend.ui", "warn");
    }

    if (expectedTurnId !== currentTurnIdRef.current) {
      return;
    }

    // Drain period: keep floor in AI_SPEAKING for 300ms after audio ends.
    // This prevents room reverb / speaker bleed from being picked up by the mic
    // and transcribed as the candidate's answer (acoustic feedback loop).
    // The utteranceBuffer is cleared on transition to AI_THINKING/AI_SPEAKING,
    // so any reverb captured during this window is discarded on the next transition.
    await new Promise<void>((r) => setTimeout(r, 300));

    if (expectedTurnId !== currentTurnIdRef.current) {
      return;
    }

    if (isComplete) {
      sessionRef.current?.transition(FloorState.IDLE);
      setNearEnd(false);
      setComplete(true);
      setSessionSnapshot((prev) => ({ ...(prev ?? {}), interview_complete: true }));
      sessionRef.current?.stop();
      await fetch(`${API}/end_interview/${session_id}`, { method: "POST" });
      trackInterviewEvent(session_id, "ui_interview_complete", {
        turn_id: expectedTurnId,
        sprint: newSprint,
      }, "frontend.ui");
      const returnUrl = getExternalReturnUrl();
      if (returnUrl) {
        window.setTimeout(() => {
          window.location.assign(returnUrl);
        }, 3500);
      }
    } else {
      beginUserTurn(sessionRef.current);
    }
  }, [beginUserTurn, getExternalReturnUrl, session_id]);

  const commitAnswerDraft = useCallback(async (session: InterviewSession, turnId: string) => {
    const draft = answerDraftRef.current;
    if (!draft || draft.turnId !== turnId) return;

    if (draft.commitTimer) {
      clearTimeout(draft.commitTimer);
      draft.commitTimer = null;
    }

    if (processingRef.current) {
      draft.pendingRevision = true;
      return;
    }

    const mergedText = draft.textParts.join(" ").replace(/\s+/g, " ").trim();
    if (!mergedText) return;

    processingRef.current = true;
    draft.pendingRevision = false;
    draft.submittedText = mergedText;
    draft.requestVersion += 1;
    commitTimeRef.current = performance.now();
    const requestVersion = draft.requestVersion;
    const mergedEntities = [...draft.entitySet];

    let nextMessageIndex = draft.messageIndex;
    setMessages((prev) => {
      if (
        draft.messageIndex !== null &&
        prev[draft.messageIndex] &&
        prev[draft.messageIndex].role === "candidate"
      ) {
        const updated = [...prev];
        updated[draft.messageIndex] = { role: "candidate", text: mergedText };
        return updated;
      }
      nextMessageIndex = prev.length;
      return [...prev, { role: "candidate", text: mergedText }];
    });
    draft.messageIndex = nextMessageIndex ?? draft.messageIndex;
    setPartial("");
    session.transition(FloorState.AI_THINKING);
    const turnStartAt = performance.now();
    trackInterviewEvent(session_id, "ui_turn_commit", {
      turn_id: turnId,
      request_version: requestVersion,
      chars: mergedText.length,
      words: mergedText.split(/\s+/).filter(Boolean).length,
      entities_count: mergedEntities.length,
    }, "frontend.ui");

    const isRevisionStale = () => {
      const liveDraft = answerDraftRef.current;
      return Boolean(
        liveDraft &&
        liveDraft.turnId === turnId &&
        liveDraft.requestVersion === requestVersion &&
        liveDraft.pendingRevision &&
        liveDraft.submittedText !== liveDraft.textParts.join(" ").replace(/\s+/g, " ").trim()
      );
    };

    let routeKind = "unknown";

    try {
      const processStartAt = performance.now();
      const result = await processTurn(session_id, mergedText, mergedEntities, turnId);
      const processMs = performance.now() - processStartAt;
      const staleBecauseOfRevision = isRevisionStale();
      if (staleBecauseOfRevision) {
        trackInterviewEvent(session_id, "ui_turn_stale_after_process", {
          turn_id: turnId,
          request_version: requestVersion,
          process_ms: Math.round(processMs),
        }, "frontend.ui", "warn");
        return;
      }

      const responseTurnId = typeof result.turn_id === "string" ? result.turn_id : turnId;
      routeKind = typeof result.route_kind === "string" ? result.route_kind : routeKind;
      if (responseTurnId !== currentTurnIdRef.current) return;

      const prefetchStartAt = performance.now();
      const audioUrl = await prefetchAudio(result.response as string, session_id);
      const prefetchMs = performance.now() - prefetchStartAt;
      const staleAfterPrefetch = isRevisionStale();
      if (staleAfterPrefetch || responseTurnId !== currentTurnIdRef.current) {
        trackInterviewEvent(session_id, "ui_turn_stale_after_prefetch", {
          turn_id: turnId,
          request_version: requestVersion,
          prefetch_ms: Math.round(prefetchMs),
          route_kind: routeKind,
        }, "frontend.ui", "warn");
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        return;
      }

      console.info(
        `[Latency] ${routeKind} ready in ${Math.round(performance.now() - turnStartAt)}ms `
        + `(process=${Math.round(processMs)}ms, tts_prefetch=${Math.round(prefetchMs)}ms)`
      );
      trackInterviewEvent(session_id, "ui_turn_ready", {
        turn_id: turnId,
        request_version: requestVersion,
        route_kind: routeKind,
        total_ms: Math.round(performance.now() - turnStartAt),
        process_ms: Math.round(processMs),
        tts_prefetch_ms: Math.round(prefetchMs),
        has_audio: Boolean(audioUrl),
      }, "frontend.ui");

      clearAnswerDraft();
      await handleFollowup(result, audioUrl, responseTurnId);
    } catch {
      setError("Agent pipeline error. Check backend.");
      trackInterviewEvent(session_id, "ui_turn_pipeline_error", {
        turn_id: turnId,
        request_version: requestVersion,
      }, "frontend.ui", "error");
      beginUserTurn(session);
    } finally {
      processingRef.current = false;
      const pendingDraft = answerDraftRef.current;
      if (
        pendingDraft &&
        pendingDraft.turnId === turnId &&
        pendingDraft.pendingRevision
      ) {
        pendingDraft.pendingRevision = false;
        pendingDraft.commitTimer = setTimeout(() => {
          void commitAnswerDraft(session, turnId);
        }, 150);
      }
    }
  }, [beginUserTurn, clearAnswerDraft, handleFollowup, session_id]);

  const queueAnswerChunk = useCallback((
    session: InterviewSession,
    text: string,
    entities: string[],
  ) => {
    const cleaned = text.trim();
    if (!cleaned) return;

    const turnId = session.getActiveTurnId() || crypto.randomUUID();
    session.setActiveTurnId(turnId);
    currentTurnIdRef.current = turnId;

    let draft = answerDraftRef.current;
    if (!draft || draft.turnId !== turnId) {
      clearAnswerDraft();
      draft = {
        turnId,
        textParts: [],
        entitySet: new Set<string>(),
        submittedText: null,
        pendingRevision: false,
        requestVersion: 0,
        messageIndex: null,
        commitTimer: null,
      };
      answerDraftRef.current = draft;
    }

    const previousPart = draft.textParts[draft.textParts.length - 1];
    if (previousPart !== cleaned) {
      draft.textParts.push(cleaned);
    }
    entities.forEach((entity) => draft!.entitySet.add(entity));
    setPartial(draft.textParts.join(" "));

    // Same-turn revision: candidate resumed speaking after a forced safety flush.
    // Reset silence confirmation so the next follow-up remains defensive until we
    // see a true end-of-utterance for the revised answer.
    if (draft.submittedText !== null && silenceConfirmedRef.current) {
      silenceConfirmedRef.current = false;
      commitTimeRef.current = performance.now();
      trackInterviewEvent(session_id, "ui_turn_reopened_same_turn", {
        turn_id: turnId,
        parts: draft.textParts.length,
      }, "frontend.ui");
    }

    if (draft.commitTimer) clearTimeout(draft.commitTimer);
    draft.commitTimer = setTimeout(() => {
      void commitAnswerDraft(session, turnId);
    }, ANSWER_SETTLE_MS);
  }, [clearAnswerDraft, commitAnswerDraft]);

  async function bootInterview(state: SessionSnapshot, mode: "new" | "resume") {
    trackInterviewEvent(session_id, "ui_boot_interview", {
      mode,
      existing_turns: state.question_count ?? 0,
      completed: Boolean(state.interview_complete),
    }, "frontend.ui");
    setError("");
    setStarted(true);
    setComplete(false);
    setBootingMode(mode);

    const opening = state.last_question || "";
    const nextSprint = state.current_sprint ?? 1;
    const nextPersona = state.current_persona ?? "curious_lead";
    const existingCount = state.question_count ?? 0;

    setSprint(nextSprint);
    setPersona(nextPersona);
    prevSprintRef.current = nextSprint;
    setQuestionCount(existingCount);

    if (mode === "resume") {
      const restored = buildMessagesFromHistory(state.history ?? []);
      const lastAskedQuestion = state.history?.length ? state.history[state.history.length - 1]?.question : "";
      const shouldAppendPendingQuestion = Boolean(opening && opening !== lastAskedQuestion);
      setMessages([
        ...restored,
        ...(shouldAppendPendingQuestion ? [{ role: "ai" as const, text: opening }] : []),
      ]);
    } else {
      setMessages(opening ? [{ role: "ai", text: opening }] : []);
    }

    const openingAudioUrl = opening ? await prefetchAudio(opening) : null;

    const session = new InterviewSession(session_id);
    sessionRef.current = session;

    session.onFloorChange = (floor) => {
      if (floor === FloorState.USER_SPEAKING) setPhase("listening");
      else if (floor === FloorState.AI_THINKING) setPhase("thinking");
      else if (floor === FloorState.AI_SPEAKING) setPhase("speaking");
      else setPhase("idle");
    };

    session.onBargeIn = () => {
      console.log("[UI] Barge-in! Invalidating active turn.");
      trackInterviewEvent(session_id, "ui_barge_in", {}, "frontend.ui", "warn");
      clearAnswerDraft();
      currentTurnIdRef.current = crypto.randomUUID();
      session.setActiveTurnId(currentTurnIdRef.current);
      setPartial("");
    };

    session.onSilence = async () => {
      // UtteranceEnd fired with an empty buffer after a safety-timeout commit.
      // This is the late "yes, they really stopped" signal that releases the hold.
      if (session.floor === FloorState.AI_THINKING) {
        console.log("[UI] UtteranceEnd confirmed after safety timeout, releasing TTS hold.");
        silenceConfirmedRef.current = true;
        trackInterviewEvent(session_id, "ui_silence_confirmed", {}, "frontend.ui");
        return;
      }

      console.log("[UI] User is silent. Nudging.");
      if (processingRef.current || session.floor !== FloorState.USER_SPEAKING) return;
      trackInterviewEvent(session_id, "ui_silence_nudge", {
        floor: session.floor,
      }, "frontend.ui");

      const ac = new AbortController();
      // Use pre-cached filler audio — avoids a live /tts round-trip for the nudge
      const { url: nudgeUrl, text: nudgeText } = await prefetchFillerAudio();
      session.setAbortController(ac);
      session.setActivePlaybackText(nudgeText);
      session.transition(FloorState.AI_SPEAKING);

      try {
        await playAudioUrl(nudgeUrl, nudgeText, ac.signal);
      } catch {
        console.log("[UI] Silence nudge interrupted");
      }

      beginUserTurn(session);
    };

    session.onPartial = (text) => {
      setPartial(text);
    };

    session.onFinal = async (text, entities, metadata) => {
      silenceConfirmedRef.current = metadata?.reason === "utterance_end";
      queueAnswerChunk(session, text, entities);
    };

    session.onError = (err) => {
      setError(`Voice error: ${err}`);
      trackInterviewEvent(session_id, "ui_voice_error", {
        error: err,
      }, "frontend.ui", "error");
    };

    try {
      await session.start();
      stopVisualizerRef.current = session.connectVisualizer((level) => setMicLevel(level));

      if (showCamera && videoRef.current) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: true });
          videoRef.current.srcObject = stream;
          await session.startVision(videoRef.current);
        } catch (vErr) {
          console.error("[UI] Camera permission denied or failed:", vErr);
        }
      }

      if (opening) {
        const ac = new AbortController();
        session.setAbortController(ac);
        session.setActivePlaybackText(opening);
        session.transition(FloorState.AI_SPEAKING);
        await playAudioUrl(openingAudioUrl, opening, ac.signal);
        beginUserTurn(session);
      } else {
        beginUserTurn(session);
      }
    } catch (e) {
      setError(`Could not start mic: ${String(e)}`);
      trackInterviewEvent(session_id, "ui_boot_failed", {
        mode,
        error: String(e),
      }, "frontend.ui", "error");
      setStarted(false);
      setPhase("idle");
    } finally {
      setBootingMode(null);
    }
  }

  async function startInterview() {
    try {
      await ensureMediaPermissions();
      const state = await fetchSessionSnapshot();
      if (!state) return;

      if ((state.question_count ?? 0) > 0 || state.interview_complete) {
        setSessionSnapshot(state);
        return;
      }

      if (!state.interview_trajectory_map?.focus_areas?.length) {
        throw new Error("Interview trajectory map missing from session startup state");
      }

      await bootInterview(state, "new");
    } catch (e) {
      setError(`Could not start interview: ${String(e)}`);
      setBootingMode(null);
    }
  }

  async function resumeInterview() {
    try {
      await ensureMediaPermissions();
      const state = await fetchSessionSnapshot();
      if (!state) return;
      await bootInterview(state, "resume");
    } catch (e) {
      setError(`Could not resume interview: ${String(e)}`);
      setBootingMode(null);
    }
  }

  async function startFreshInterview() {
    const resume = sessionSnapshot?.resume?.trim();
    if (!resume) {
      router.replace("/");
      return;
    }

    setError("");
    setBootingMode("fresh");
    teardownActiveSession();
    resetInterviewUi();

    try {
      await ensureMediaPermissions();
      const prepareRes = await fetch(`${API}/prepare_interview_map`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume,
          github_links: sessionSnapshot?.github_links ?? [],
          target_role: sessionSnapshot?.target_role ?? "",
          years_experience: sessionSnapshot?.years_experience ?? "",
        }),
      });
      const prepareData = await prepareRes.json().catch(() => ({}));
      if (!prepareRes.ok) {
        throw new Error(prepareData?.detail || `Server error ${prepareRes.status}`);
      }
      if (prepareData?.map_status !== "ready") {
        throw new Error("Interview map did not reach ready state.");
      }

      const startRes = await fetch(`${API}/start_interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prepared_session_id: prepareData.session_id,
        }),
      });
      const startData = await startRes.json().catch(() => ({}));
      if (!startRes.ok) throw new Error(startData?.detail || `Server error ${startRes.status}`);
      router.replace(`/interview/${startData.session_id}`);
    } catch (e) {
      setError(`Could not start a fresh run: ${String(e)}`);
      setBootingMode(null);
    }
  }


  async function endInterview() {
    teardownActiveSession();
    trackInterviewEvent(session_id, "ui_end_interview_clicked", {}, "frontend.ui");

    // Await end_interview so the report is persisted before navigation.
    // Navigation happens regardless of failure — report page handles partial data gracefully.
    try {
      await fetch(`${API}/end_interview/${session_id}`, { method: "POST" });
    } catch {
      // non-fatal — navigate anyway, report will show partial state
    }
    const returnUrl = getExternalReturnUrl();
    if (returnUrl) window.location.assign(returnUrl);
    else router.push(`/report/${session_id}`);
  }

  useEffect(() => {
    return () => {
      teardownActiveSession();
    };
  }, [teardownActiveSession]);

  const progressPct = Math.min((questionCount / 15) * 100, 100);
  const existingTurns = sessionSnapshot?.question_count ?? 0;
  const hasExistingProgress = existingTurns > 0;
  const isCompletedSession = Boolean(sessionSnapshot?.interview_complete);
  const showResumeGate = !started && !snapshotLoading && (hasExistingProgress || isCompletedSession);
  const phaseLabel =
    phase === "listening"
      ? "Listening"
      : phase === "thinking"
      ? "Analyzing"
      : phase === "speaking"
      ? "Speaking"
      : started
      ? "Idle"
      : "Ready";
  const phaseDotClass =
    phase === "listening"
      ? "bg-[oklch(0.87_0.01_260)] shadow-[0_0_12px_oklch(0.87_0.01_260)]"
      : phase === "thinking"
      ? "bg-[var(--ag-amber)] shadow-[0_0_12px_var(--ag-amber)]"
      : phase === "speaking"
      ? "bg-[var(--ag-blue)] shadow-[0_0_12px_var(--ag-blue)]"
      : "bg-[var(--ag-text-3)]";

  return (
    <div className="ag-shell min-h-screen select-none px-4 py-4 text-[var(--ag-text-0)] md:px-6 xl:h-screen xl:overflow-hidden">
      <div className="flex min-h-[calc(100vh-2rem)] flex-col gap-4 xl:h-[calc(100vh-2rem)] xl:min-h-0">
        <header className="flex flex-col gap-4 rounded-2xl border border-[var(--ag-border)] bg-[oklch(0.1_0.014_265_/_0.82)] px-5 py-4 backdrop-blur-xl md:flex-row md:items-center md:justify-between xl:shrink-0">
          <div className="flex flex-wrap items-center gap-3">
            <AGLogo compact />
            {started && <AGChip active>S{sprint} · {SPRINT_LABELS[sprint]}</AGChip>}
            {sessionSnapshot?.target_role && <AGChip>{sessionSnapshot.target_role}</AGChip>}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {!started && (
              <button
                onClick={() => setShowCamera(!showCamera)}
                className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-all ${
                  showCamera
                    ? "border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-[var(--ag-text-0)]"
                    : "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-2)]"
                }`}
              >
                <span className={`h-2 w-2 rounded-full ${showCamera ? "bg-[var(--ag-green)]" : "bg-[var(--ag-text-3)]"}`} />
                Lens Early-Turn {showCamera ? "ON" : "OFF"}
              </button>
            )}

            {started && (
              <div className="flex items-center gap-3 rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-2">
                <div className="h-[4px] w-24 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
                  <div
                    className="h-full rounded-full bg-[var(--ag-blue)] transition-all duration-700"
                    style={{ width: `${progressPct}%`, boxShadow: "0 0 14px var(--ag-blue)" }}
                  />
                </div>
                <span className="font-mono text-xs text-[var(--ag-text-3)]">{questionCount}/15</span>
              </div>
            )}

            {started && !complete && (
              <AGButton variant="ghost" onClick={endInterview} className="px-3 py-2 text-xs">
                End session
              </AGButton>
            )}
          </div>
        </header>

        <div className="grid flex-1 gap-4 xl:min-h-0 xl:grid-cols-[340px_minmax(0,1fr)]">
          <AGSurface className="flex flex-col items-center justify-between gap-4 px-5 py-5 xl:sticky xl:top-4 xl:h-full xl:min-h-0 xl:overflow-hidden">
            <div className="w-full space-y-4">
              <div className="space-y-2">
                <AGSectionLabel>Live Interrogator</AGSectionLabel>
                <p className="text-sm leading-7 text-[var(--ag-text-2)]">
                  Real-time cognitive pressure loop. No validation. No hints. Just the boundary of what is actually defensible.
                </p>
              </div>

              <div className="relative flex min-h-[220px] items-center justify-center rounded-[28px] border border-[var(--ag-border)] bg-[linear-gradient(180deg,oklch(0.11_0.016_265_/_0.88),oklch(0.08_0.012_265_/_0.96))]">
                <AIOrb state={phase} />
              </div>

              {showCamera && (
                <div className="overflow-hidden rounded-2xl border border-[var(--ag-border)] bg-black/40">
                  <div className="flex items-center justify-between border-b border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-2">
                    <AGSectionLabel>Camera Stream</AGSectionLabel>
                    <span className="h-2 w-2 rounded-full bg-[var(--ag-green)] shadow-[0_0_12px_var(--ag-green)]" />
                  </div>
                  <div className="aspect-video max-h-[150px] bg-black">
                    <video
                      ref={videoRef}
                      autoPlay
                      playsInline
                      muted
                      className="h-full w-full scale-x-[-1] object-cover"
                    />
                  </div>
                </div>
              )}

              <div className="space-y-3 text-center">
                <div className="flex items-center justify-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${phaseDotClass}`} style={{ animation: started ? "agBlink 2s ease-in-out infinite" : "none" }} />
                  <span className="text-sm font-semibold text-[var(--ag-text-0)]">{phaseLabel}</span>
                </div>
                <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">
                  {PERSONA_DESC[persona]}
                </p>
              </div>

              <div className="flex min-h-[48px] items-center justify-center">
                {phase === "listening" ? (
                  <Waveform level={micLevel} active />
                ) : (
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                    Waiting for the next turn boundary
                  </p>
                )}
              </div>
            </div>

            <div className="w-full space-y-4">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <AGSectionLabel>Sprint Progress</AGSectionLabel>
                  <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                    Turn {questionCount}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {[1, 2, 3].map((stage) => (
                    <div key={stage} className="flex-1">
                      <div
                        className="h-1.5 rounded-full transition-all"
                        style={{
                          background:
                            stage < sprint
                              ? "var(--ag-blue)"
                              : stage === sprint
                              ? "linear-gradient(90deg, var(--ag-blue), oklch(0.82 0.14 72))"
                              : "var(--ag-surface-2)",
                          boxShadow: stage === sprint ? "0 0 12px var(--ag-blue)" : "none",
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              {showCamera && (
                <div className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-3">
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">Lens Active</p>
                  <p className="mt-2 text-xs leading-6 text-[var(--ag-text-2)]">
                    Early-turn camera signal is enabled for the voice floor manager.
                  </p>
                </div>
              )}
            </div>
          </AGSurface>

          <AGSurface className="flex min-h-[680px] flex-col overflow-hidden xl:min-h-0">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--ag-border)] px-6 py-5">
              <div>
                <AGSectionLabel>Live Transcript</AGSectionLabel>
                <p className="mt-2 text-sm text-[var(--ag-text-2)]">
                  Session {session_id.slice(0, 8)} · {started ? "interview active" : "awaiting launch"}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <AGChip active={phase === "listening"}>{phase === "listening" ? "Open Mic" : "Mic gated"}</AGChip>
                <AGChip>{currentTurnIdRef.current ? currentTurnIdRef.current.slice(0, 8) : "pending"}</AGChip>
              </div>
            </div>

            <div ref={transcriptRef} className="ag-scrollbar min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-6">
              {!started && !showResumeGate && (
                <div className="flex h-full min-h-[420px] items-center justify-center">
                  <div className="max-w-lg text-center">
                    <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-xl text-[var(--ag-blue)]">
                      ∞
                    </div>
                    <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[var(--ag-text-0)]">
                      Antigravity Protocol
                    </h2>
                    <p className="mt-4 text-sm leading-7 text-[var(--ag-text-2)]">
                      A voice-native interview system built to test ownership, fundamentals, and systems reasoning under live pressure.
                    </p>
                    <p className="mt-6 font-mono text-[10px] uppercase tracking-[0.24em] text-[var(--ag-text-3)]">
                      Probe → Break → Analyze → Adapt
                    </p>
                  </div>
                </div>
              )}

              {showResumeGate && (
                <div className="flex min-h-[420px] items-center justify-center">
                  <AGSurface className="max-w-xl px-8 py-8 text-center">
                    <AGSectionLabel>{isCompletedSession ? "Completed Session" : "Existing Session"}</AGSectionLabel>
                    <h2 className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-[var(--ag-text-0)]">
                      {isCompletedSession
                        ? "This interview already finished."
                        : "This interview URL already has progress."}
                    </h2>
                    <p className="mt-4 text-sm leading-7 text-[var(--ag-text-2)]">
                      {isCompletedSession
                        ? "Reopening this route should not silently restart the session. View the report or spin up a fresh run from the same resume."
                        : `This session already has ${existingTurns} recorded turn${existingTurns === 1 ? "" : "s"}. Resume it explicitly or start a fresh run from the same resume.`}
                    </p>

                    <div className="mt-6 flex flex-col gap-3">
                      {!isCompletedSession && (
                        <AGButton onClick={resumeInterview} disabled={bootingMode !== null} className="w-full">
                          {bootingMode === "resume" ? "Resuming…" : "Resume Session"}
                        </AGButton>
                      )}
                      {isCompletedSession && (
                        <AGButton
                          onClick={() => {
                            const returnUrl = getExternalReturnUrl();
                            if (returnUrl) window.location.assign(returnUrl);
                            else router.push(`/report/${session_id}`);
                          }}
                          disabled={bootingMode !== null}
                          className="w-full"
                        >
                          {getExternalReturnUrl() ? "Return to ProvenHire" : "View Report"}
                        </AGButton>
                      )}
                      <AGButton
                        onClick={startFreshInterview}
                        disabled={bootingMode !== null}
                        variant="secondary"
                        className="w-full"
                      >
                        {bootingMode === "fresh" ? "Starting Fresh…" : "Start Fresh Run"}
                      </AGButton>
                    </div>
                  </AGSurface>
                </div>
              )}

              {messages.map((msg, i) => (
                <MessageItem key={i} msg={msg} />
              ))}

              {partial && (
                <div className="flex justify-end">
                  <div className="max-w-[82%] rounded-[22px] border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-5 py-4">
                    <p className="mb-2 text-right font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                      Accumulating
                    </p>
                    <p className="text-sm italic leading-7 text-[var(--ag-text-2)]">{partial}</p>
                  </div>
                </div>
              )}

              {nearEnd && !complete && (
                <div className="rounded-xl border border-[oklch(0.8_0.16_72_/_0.24)] bg-[oklch(0.8_0.16_72_/_0.08)] px-4 py-3 text-sm text-[var(--ag-amber)]">
                  Two questions remaining. The interview is closing in on its final boundary check.
                </div>
              )}

              {complete && (
                <div className="py-8 text-center">
                  <AGChip active>Complete</AGChip>
                  <p className="mt-4 text-lg font-semibold text-[var(--ag-text-0)]">
                    Thank you for attending the interview.
                  </p>
                  <p className="mx-auto mt-3 max-w-md text-sm leading-7 text-[var(--ag-text-2)]">
                    The live interrogation is over. Exit this screen whenever you are ready and review the full report.
                  </p>
                  <div className="mt-6 flex justify-center">
                    <AGButton
                      onClick={() => {
                        const returnUrl = getExternalReturnUrl();
                        if (returnUrl) window.location.assign(returnUrl);
                        else router.push(`/report/${session_id}`);
                      }}
                    >
                      {getExternalReturnUrl() ? "Return to ProvenHire →" : "View Report →"}
                    </AGButton>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-col gap-4 border-t border-[var(--ag-border)] px-6 py-5 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1">
                {error ? (
                  <p className="text-sm text-[var(--ag-red)]">{error}</p>
                ) : (
                  <p className="text-sm text-[var(--ag-text-2)]">
                    {started
                      ? "Stay natural. The system will pick up the next turn when your utterance settles."
                      : "The transcript pane will activate once the live interview loop starts."}
                  </p>
                )}
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                  Turn Trace · {currentTurnIdRef.current ? currentTurnIdRef.current.slice(0, 8) : "waiting"}
                </p>
              </div>

              {!started ? (
                <AGButton
                  onClick={startInterview}
                  disabled={snapshotLoading || bootingMode !== null || showResumeGate}
                  className="w-full md:w-auto"
                >
                  {snapshotLoading ? "Loading…" : bootingMode === "new" ? "Preparing interview…" : "Engage System →"}
                </AGButton>
              ) : (
                <div className="flex items-center gap-3 rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-3">
                  <span className={`h-2 w-2 rounded-full ${phaseDotClass}`} style={{ animation: "agBlink 2s ease-in-out infinite" }} />
                  <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                    {phase === "listening" ? "Listening" : phase === "thinking" ? "Reasoning" : phase === "speaking" ? "Speaking" : "Idle"}
                  </span>
                </div>
              )}
            </div>
          </AGSurface>
        </div>
      </div>
    </div>
  );
}

function MessageItem({ msg }: { msg: Message }) {
  if (msg.isSprintMarker) {
    return <AGSprintDivider sprint={msg.sprint ?? 1} label={SPRINT_LABELS[msg.sprint ?? 1]} />;
  }

  if (msg.isPivotMarker) {
    return (
      <div className="flex items-center gap-3 py-1">
        <div className="h-px flex-1 bg-[var(--ag-border)]" />
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
          pivoting focus area
        </span>
        <div className="h-px flex-1 bg-[var(--ag-border)]" />
      </div>
    );
  }

  const isAI = msg.role === "ai";
  return (
    <div className={`flex ${isAI ? "justify-start" : "justify-end"}`}>
      <div className="max-w-[84%] space-y-2">
        <div className={`flex items-center gap-2 ${isAI ? "" : "justify-end"}`}>
          {isAI && msg.severity && <AGSeverityPip severity={msg.severity} />}
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
            {isAI ? "Interrogator" : "Candidate"}
          </p>
          {msg.severity === "high" && (
            <span className="rounded-md border border-[oklch(0.66_0.21_24_/_0.28)] bg-[oklch(0.66_0.21_24_/_0.1)] px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--ag-red)]">
              Boundary Exposed
            </span>
          )}
        </div>
        <div
          className={`rounded-[22px] border px-5 py-4 text-sm leading-7 ${
            isAI
              ? "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-1)]"
              : "border-[var(--ag-border-strong)] bg-[oklch(0.68_0.19_255_/_0.08)] text-[var(--ag-text-0)]"
          }`}
          style={
            isAI && msg.severity && msg.severity !== "low"
              ? { borderLeftWidth: "2px", borderLeftColor: msg.severity === "high" ? "var(--ag-red)" : "var(--ag-amber)" }
              : undefined
          }
        >
          {msg.text}
        </div>
      </div>
    </div>
  );
}
