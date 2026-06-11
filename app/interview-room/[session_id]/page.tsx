"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import {
  FloorState,
  InterviewSession,
  playAudioUrl,
  prefetchAudio,
  prefetchFillerAudio,
  processTurn,
  trackInterviewEvent,
} from "@/lib/audio";
import { getApiBaseUrl } from "@/lib/api";
import {
  InterviewRoomFloor,
  type InterviewRoomCandidate,
  type InterviewRoomPhase,
  type InterviewRoomTurn,
} from "@/components/interview-room/InterviewRoomFloor";

type SessionHistoryEntry = {
  turn_id?: string;
  question: string;
  answer: string;
  sprint?: number;
};

type SessionSnapshot = {
  session_id?: string;
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
  parsed_resume?: {
    name?: string;
    candidate_name?: string;
    full_name?: string;
  };
  interview_trajectory_map?: { focus_areas?: unknown[] };
  external_handoff?: {
    return_url?: string;
  };
};

type AnswerDraft = {
  turnId: string;
  question: string;
  revisionOfTurnId: string;
  revisionQuestion: string;
  textParts: string[];
  entitySet: Set<string>;
  submittedText: string | null;
  pendingRevision: boolean;
  requestVersion: number;
  commitTimer: ReturnType<typeof setTimeout> | null;
};

type LastCommittedAnswer = {
  turnId: string;
  question: string;
  answer: string;
};

type PendingFollowup = {
  turnId: string;
  question: string;
  result: Record<string, unknown>;
};

type RoomLock = "none" | "starting" | "paused" | "confirm_end";

const API = getApiBaseUrl();
const ANSWER_SETTLE_MS = 700;
const TTS_HOLD_CAP_MS = 2500;
const PROGRESS_TOTAL_TURNS = 15;
const FOLLOWUP_ACK_TEXTS = [
  "Got it. Moving to the next question.",
  "Thanks, I have that. Let's continue.",
  "Okay, that's recorded. Here's the next question.",
  "Understood. Moving forward.",
  "Thanks, I captured that. Let's keep going.",
  "Got it. Let's move to the next question.",
  "Okay. I'll take that as your answer and continue.",
];
const LATE_FOLLOWUP_ACK_TEXT = "Thanks. We are in the last couple of questions now. Moving to the next one.";
const CLOSING_ACK_TEXT = "Got it. Your interview is closing now. You can relax while I prepare the report.";
const REPEAT_LEAD_IN_TEXT = "I'll repeat the question once again for you.";
const PAUSE_TEXT = "Of course. Take your time. Whenever you're ready, come back and continue the interview.";
const MAX_PAUSE_USES = 3;

function normalizeTurn(entry: SessionHistoryEntry): InterviewRoomTurn {
  return {
    question: String(entry.question || ""),
    answer: String(entry.answer || ""),
    sprint: entry.sprint,
  };
}

function candidateFromSnapshot(snapshot: SessionSnapshot | null): InterviewRoomCandidate {
  const parsed = snapshot?.parsed_resume || {};
  const name =
    parsed.name?.trim() ||
    parsed.candidate_name?.trim() ||
    parsed.full_name?.trim() ||
    "Candidate";
  return {
    name,
    role: snapshot?.target_role?.trim() || "Candidate",
    experience: snapshot?.years_experience?.trim() || "Experience not specified",
  };
}

function rectSnapshot(selector: string) {
  const element = document.querySelector(selector);
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  return {
    selector,
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    bottom: Math.round(rect.bottom),
    right: Math.round(rect.right),
  };
}

function overlaps(a: ReturnType<typeof rectSnapshot>, b: ReturnType<typeof rectSnapshot>) {
  if (!a || !b) return false;
  return !(a.right <= b.x || b.right <= a.x || a.bottom <= b.y || b.bottom <= a.y);
}

function getFollowupAck(
  rotationIndex: number,
  backendQuestionCount: number | null,
  isComplete: boolean,
) {
  if (isComplete) {
    return {
      key: "static:followup_ack:closing",
      text: CLOSING_ACK_TEXT,
      nextRotationIndex: rotationIndex,
    };
  }

  if (backendQuestionCount !== null && backendQuestionCount >= PROGRESS_TOTAL_TURNS - 2) {
    return {
      key: "static:followup_ack:late",
      text: LATE_FOLLOWUP_ACK_TEXT,
      nextRotationIndex: rotationIndex,
    };
  }

  const index = rotationIndex % FOLLOWUP_ACK_TEXTS.length;
  return {
    key: `static:followup_ack:${index}`,
    text: FOLLOWUP_ACK_TEXTS[index],
    nextRotationIndex: rotationIndex + 1,
  };
}

export default function LiveInterviewRoomPage() {
  const { session_id } = useParams<{ session_id: string }>();
  const router = useRouter();

  const [phase, setPhase] = useState<InterviewRoomPhase>("ready");
  const [started, setStarted] = useState(false);
  const [complete, setComplete] = useState(false);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [bootingMode, setBootingMode] = useState<"new" | "resume" | "fresh" | null>(null);
  const [sessionSnapshot, setSessionSnapshot] = useState<SessionSnapshot | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [liveTranscript, setLiveTranscript] = useState("");
  const [liveTranscriptOpen, setLiveTranscriptOpen] = useState(false);
  const [committedTurns, setCommittedTurns] = useState<InterviewRoomTurn[]>([]);
  const [questionCount, setQuestionCount] = useState(0);
  const [micEnergy, setMicEnergy] = useState(0.12);
  const [error, setError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(true);
  const [fullTranscriptOpen, setFullTranscriptOpen] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraVisible, setCameraVisible] = useState(true);
  const [cameraError, setCameraError] = useState("");
  const [roomLock, setRoomLock] = useState<RoomLock>("none");
  const [startCountdown, setStartCountdown] = useState<number | null>(null);
  const [pauseUsesRemaining, setPauseUsesRemaining] = useState(MAX_PAUSE_USES);

  const sessionRef = useRef<InterviewSession | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const stopVisualizerRef = useRef<(() => void) | null>(null);
  const processingRef = useRef(false);
  const answerDraftRef = useRef<AnswerDraft | null>(null);
  const currentTurnIdRef = useRef("");
  const activeQuestionRef = useRef("");
  const lastCommittedAnswerRef = useRef<LastCommittedAnswer | null>(null);
  const pendingFollowupRef = useRef<PendingFollowup | null>(null);
  const continuationTurnIdRef = useRef("");
  const retainedAudioRef = useRef<Map<string, string>>(new Map());
  const retainedAudioPromisesRef = useRef<Map<string, Promise<string | null>>>(new Map());
  const silenceConfirmedRef = useRef(false);
  const commitTimeRef = useRef(0);
  const playbackSeqRef = useRef(0);
  const completeRef = useRef(false);
  const roomLockRef = useRef<RoomLock>("none");
  const lockWaitersRef = useRef<Array<() => void>>([]);
  const floorBeforeLockRef = useRef<FloorState | null>(null);
  const followupAckRotationRef = useRef(0);

  const candidate = candidateFromSnapshot(sessionSnapshot);
  const existingTurns = sessionSnapshot?.question_count ?? 0;
  const isCompletedSession = Boolean(sessionSnapshot?.interview_complete);
  const showResumeGate =
    !started &&
    !snapshotLoading &&
    (isCompletedSession || existingTurns > 0);
  const progressCurrent = Math.min(
    complete ? committedTurns.length : committedTurns.length + (started ? 1 : 0),
    PROGRESS_TOTAL_TURNS,
  );
  const floorOwner =
    phase === "listening" ? "candidate" : phase === "ready" ? "ready" : "ai";

  useEffect(() => {
    activeQuestionRef.current = currentQuestion;
  }, [currentQuestion]);

  useEffect(() => {
    completeRef.current = complete;
  }, [complete]);

  const setRoomLockState = useCallback((nextLock: RoomLock) => {
    roomLockRef.current = nextLock;
    setRoomLock(nextLock);
    sessionRef.current?.setInputFrozen(nextLock !== "none" && nextLock !== "starting");
    if (nextLock === "none") {
      const waiters = lockWaitersRef.current.splice(0);
      waiters.forEach((resolve) => resolve());
    }
  }, []);

  const waitUntilUnlocked = useCallback(() => {
    if (roomLockRef.current === "none") return Promise.resolve();
    return new Promise<void>((resolve) => {
      lockWaitersRef.current.push(resolve);
    });
  }, []);

  const runStartCountdown = useCallback(async () => {
    setRoomLockState("starting");
    for (const value of [3, 2, 1]) {
      setStartCountdown(value);
      await new Promise<void>((resolve) => window.setTimeout(resolve, 760));
    }
    setStartCountdown(null);
    setRoomLockState("none");
  }, [setRoomLockState]);

  const clearAnswerDraft = useCallback(() => {
    const draft = answerDraftRef.current;
    if (draft?.commitTimer) clearTimeout(draft.commitTimer);
    answerDraftRef.current = null;
  }, []);

  const getRetainedAudio = useCallback((key: string, text: string) => {
    const cached = retainedAudioRef.current.get(key);
    if (cached) return Promise.resolve(cached);

    const pending = retainedAudioPromisesRef.current.get(key);
    if (pending) return pending;

    const promise = prefetchAudio(text, session_id)
      .then((url) => {
        if (url) retainedAudioRef.current.set(key, url);
        retainedAudioPromisesRef.current.delete(key);
        return url;
      })
      .catch(() => {
        retainedAudioPromisesRef.current.delete(key);
        return null;
      });
    retainedAudioPromisesRef.current.set(key, promise);
    return promise;
  }, [session_id]);

  const stopCameraStream = useCallback(() => {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraOn(false);
  }, []);

  const teardownActiveSession = useCallback(() => {
    currentTurnIdRef.current = crypto.randomUUID();
    clearAnswerDraft();
    stopVisualizerRef.current?.();
    stopVisualizerRef.current = null;
    sessionRef.current?.stop();
    sessionRef.current = null;
    retainedAudioRef.current.forEach((url) => URL.revokeObjectURL(url));
    retainedAudioRef.current.clear();
    retainedAudioPromisesRef.current.clear();
    stopCameraStream();
  }, [clearAnswerDraft, stopCameraStream]);

  const resetLiveState = useCallback(() => {
    setPhase("ready");
    setStarted(false);
    setComplete(false);
    completeRef.current = false;
    setCurrentQuestion("");
    setLiveTranscript("");
    setLiveTranscriptOpen(false);
    setCommittedTurns([]);
    setQuestionCount(0);
    setMicEnergy(0.12);
    setError("");
    setFullTranscriptOpen(false);
    setRoomLockState("none");
    setStartCountdown(null);
    setPauseUsesRemaining(MAX_PAUSE_USES);
    processingRef.current = false;
    pendingFollowupRef.current = null;
    continuationTurnIdRef.current = "";
    followupAckRotationRef.current = 0;
    clearAnswerDraft();
  }, [clearAnswerDraft, setRoomLockState]);

  const getExternalReturnUrl = useCallback(() => {
    const fromState = sessionSnapshot?.external_handoff?.return_url?.trim();
    if (fromState) return fromState;
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(`ag:return-url:${session_id}`) || "";
  }, [sessionSnapshot, session_id]);

  const fetchSessionSnapshot = useCallback(async (): Promise<SessionSnapshot | null> => {
    if (!session_id || session_id === "undefined") return null;
    const res = await fetch(`${API}/state/${encodeURIComponent(session_id)}`, { cache: "no-store" });
    if (res.status === 404) {
      router.replace("/");
      return null;
    }
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(payload?.detail || `Could not load session ${session_id}: ${res.status}`);
    }
    return payload as SessionSnapshot;
  }, [router, session_id]);

  const applySnapshot = useCallback((snapshot: SessionSnapshot) => {
    const completed = Boolean(snapshot.interview_complete);
    const history = snapshot.history || [];
    setSessionSnapshot(snapshot);
    setCommittedTurns(history.map(normalizeTurn));
    setQuestionCount(snapshot.question_count ?? history.length);
    setComplete(completed);
    completeRef.current = completed;
    const latestAnswered = [...history].reverse().find((item) => String(item.answer || "").trim());
    if (latestAnswered) {
      lastCommittedAnswerRef.current = {
        turnId: String(latestAnswered.turn_id || ""),
        question: String(latestAnswered.question || ""),
        answer: String(latestAnswered.answer || ""),
      };
    }
    if (completed) setPhase("closing");
    if (snapshot.last_question) {
      setCurrentQuestion(snapshot.last_question);
    }
  }, []);

  const refreshCommittedState = useCallback(async () => {
    const fresh = await fetchSessionSnapshot();
    if (fresh) applySnapshot(fresh);
    return fresh;
  }, [applySnapshot, fetchSessionSnapshot]);

  useEffect(() => {
    if (!session_id || session_id === "undefined") {
      router.replace("/");
      return;
    }

    let cancelled = false;
    async function load() {
      teardownActiveSession();
      resetLiveState();
      setBootingMode(null);
      setSessionSnapshot(null);
      setSnapshotLoading(true);
      try {
        const snapshot = await fetchSessionSnapshot();
        if (!cancelled && snapshot) applySnapshot(snapshot);
      } catch (err) {
        if (!cancelled) setError(`Could not load interview state: ${String(err)}`);
      } finally {
        if (!cancelled) setSnapshotLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
      teardownActiveSession();
    };
  }, [applySnapshot, fetchSessionSnapshot, resetLiveState, router, session_id, teardownActiveSession]);

  useEffect(() => {
    if (snapshotLoading) return;
    if (window.parent !== window) {
      window.parent.postMessage({ type: "ANTIGRAVITY_READY" }, "*");
    }
  }, [snapshotLoading]);

  useEffect(() => {
    if (!session_id?.startsWith("replay_")) return;
    const timer = window.setTimeout(() => {
      const questionCard = rectSnapshot(".lk-question-card");
      const questionText = rectSnapshot(".lk-question");
      const answerPanel = rectSnapshot(".lk-answer-panel");
      const activityPill = rectSnapshot(".lk-activity-box");
      const floorRail = rectSnapshot(".lk-floor");
      const rightRail = rectSnapshot(".lk-memory");
      const camera = rectSnapshot(".lk-camera");
      void fetch(`${API}/replay/qa_capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id,
          event_type: "layout_snapshot",
          payload: {
            phase,
            floor_owner: floorOwner,
            started,
            complete,
            history_open: historyOpen,
            live_transcript_open: liveTranscriptOpen,
            question_chars: currentQuestion.length,
            live_transcript_chars: liveTranscript.length,
            viewport: {
              width: window.innerWidth,
              height: window.innerHeight,
              device_pixel_ratio: window.devicePixelRatio,
            },
            boxes: {
              question_card: questionCard,
              question_text: questionText,
              answer_panel: answerPanel,
              activity_pill: activityPill,
              floor_rail: floorRail,
              right_rail: rightRail,
              camera,
            },
            overlaps: {
              question_answer: overlaps(questionCard, answerPanel),
              question_right_rail: overlaps(questionCard, rightRail),
              activity_question: overlaps(activityPill, questionCard),
            },
          },
        }),
      }).catch(() => undefined);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [
    complete,
    currentQuestion,
    floorOwner,
    historyOpen,
    liveTranscript,
    liveTranscriptOpen,
    phase,
    session_id,
    started,
  ]);

  const beginUserTurn = useCallback((session: InterviewSession | null) => {
    if (!session) return;
    pendingFollowupRef.current = null;
    continuationTurnIdRef.current = "";
    clearAnswerDraft();
    silenceConfirmedRef.current = false;
    commitTimeRef.current = 0;
    const turnId = crypto.randomUUID();
    currentTurnIdRef.current = turnId;
    session.setActiveTurnId(turnId);
    setLiveTranscript("");
    setLiveTranscriptOpen(true);
    session.transition(FloorState.USER_SPEAKING);
  }, [clearAnswerDraft]);

  const handleFollowup = useCallback(async (
    result: Record<string, unknown>,
    preloadedAudioUrl: string | null,
    expectedTurnId: string,
  ) => {
    if (expectedTurnId !== currentTurnIdRef.current) {
      return;
    }
    if (sessionRef.current?.floor === FloorState.USER_SPEAKING) {
      return;
    }

    if (!silenceConfirmedRef.current) {
      const holdStartedAt = performance.now();
      const remaining = Math.max(0, TTS_HOLD_CAP_MS - (performance.now() - commitTimeRef.current));
      if (remaining > 0) {
        await new Promise<void>((resolve) => {
          const interval = setInterval(() => {
            const speaking = sessionRef.current?.floor === FloorState.USER_SPEAKING;
            const expired = performance.now() - commitTimeRef.current >= TTS_HOLD_CAP_MS;
            if (silenceConfirmedRef.current || speaking || expired) {
              clearInterval(interval);
              resolve();
            }
          }, 40);
          setTimeout(() => {
            clearInterval(interval);
            resolve();
          }, remaining);
        });
        trackInterviewEvent(session_id, "room_followup_hold_resolved", {
          turn_id: expectedTurnId,
          hold_ms: Math.round(performance.now() - holdStartedAt),
          silence_confirmed: silenceConfirmedRef.current,
        }, "frontend.room");
      }
    }

    const latestFloor = sessionRef.current?.floor as FloorState | undefined;
    if (
      expectedTurnId !== currentTurnIdRef.current ||
      latestFloor === FloorState.USER_SPEAKING
    ) {
      return;
    }

    await waitUntilUnlocked();
    if (expectedTurnId !== currentTurnIdRef.current) {
      return;
    }

    const text = String(result.response || "");
    const isComplete = Boolean(result.complete);
    const backendQuestionCount =
      typeof result.question_count === "number" ? result.question_count : null;

    if (backendQuestionCount !== null) setQuestionCount(backendQuestionCount);
    if (text) {
      pendingFollowupRef.current = {
        turnId: expectedTurnId,
        question: text,
        result,
      };
    }
    setCurrentQuestion(text);
    setLiveTranscript("");
    setLiveTranscriptOpen(false);

    const ac = new AbortController();
    const playbackSeq = ++playbackSeqRef.current;
    sessionRef.current?.setAbortController(ac);
    sessionRef.current?.transition(FloorState.AI_SPEAKING);

    try {
      const ack = getFollowupAck(followupAckRotationRef.current, backendQuestionCount, isComplete);
      followupAckRotationRef.current = ack.nextRotationIndex;
      const ackUrl = await getRetainedAudio(ack.key, ack.text);
      if (playbackSeq !== playbackSeqRef.current) return;
      if (expectedTurnId !== currentTurnIdRef.current) return;
      sessionRef.current?.setActivePlaybackText(ack.text);
      await playAudioUrl(ackUrl, ack.text, ac.signal, { revokeObjectUrl: false });
      if (playbackSeq !== playbackSeqRef.current) return;
      if (expectedTurnId !== currentTurnIdRef.current) return;
      sessionRef.current?.setActivePlaybackText(text);
      await playAudioUrl(preloadedAudioUrl, text, ac.signal, { revokeObjectUrl: false });
    } catch (err) {
      trackInterviewEvent(session_id, "room_followup_playback_error", {
        turn_id: expectedTurnId,
        error: String(err),
      }, "frontend.room", "warn");
    }

    if (playbackSeq !== playbackSeqRef.current) return;
    if (expectedTurnId !== currentTurnIdRef.current) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 300));
    if (playbackSeq !== playbackSeqRef.current) return;
    if (expectedTurnId !== currentTurnIdRef.current) return;

    if (isComplete) {
      completeRef.current = true;
      setPhase("closing");
      setComplete(true);
      setSessionSnapshot((prev) => ({ ...(prev || {}), interview_complete: true }));
      sessionRef.current?.transition(FloorState.IDLE);
      sessionRef.current?.stop();
      await fetch(`${API}/end_interview/${encodeURIComponent(session_id)}`, { method: "POST" }).catch(() => undefined);
      const returnUrl = getExternalReturnUrl();
      if (returnUrl) {
        window.setTimeout(() => window.location.assign(returnUrl), 3500);
      }
    } else {
      beginUserTurn(sessionRef.current);
    }
  }, [beginUserTurn, getExternalReturnUrl, getRetainedAudio, session_id, waitUntilUnlocked]);

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
    const committedQuestion = draft.question || activeQuestionRef.current;

    setLiveTranscript(mergedText);
    session.transition(FloorState.AI_THINKING);
    trackInterviewEvent(session_id, "room_turn_commit", {
      turn_id: turnId,
      request_version: requestVersion,
      chars: mergedText.length,
      words: mergedText.split(/\s+/).filter(Boolean).length,
      entities_count: mergedEntities.length,
    }, "frontend.room");

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

    try {
      const result = await processTurn(session_id, mergedText, mergedEntities, turnId, {
        revisionOfTurnId: draft.revisionOfTurnId,
        revisionQuestion: draft.revisionQuestion,
      });
      if (isRevisionStale()) return;
      const responseTurnId = typeof result.turn_id === "string" ? result.turn_id : turnId;
      if (responseTurnId !== currentTurnIdRef.current) return;

      setCommittedTurns((prev) => {
        const next = [...prev];
        const existingIndex = next.findLastIndex((item) => item.question === committedQuestion);
        if (existingIndex >= 0) {
          next[existingIndex] = { ...next[existingIndex], answer: mergedText };
        } else {
          next.push({ question: committedQuestion, answer: mergedText });
        }
        return next;
      });
      lastCommittedAnswerRef.current = {
        turnId,
        question: committedQuestion,
        answer: mergedText,
      };
      setQuestionCount((count) => Math.max(count, committedTurns.length + 1));
      void refreshCommittedState().catch(() => undefined);

      const pendingFollowup = pendingFollowupRef.current;
      const nextText = String(result.response || pendingFollowup?.question || "");
      const followupResult =
        !result.response && pendingFollowup?.question
          ? { ...pendingFollowup.result, response: pendingFollowup.question, turn_id: responseTurnId }
          : result;
      const audioUrl = await getRetainedAudio(`question:${nextText}`, nextText);
      if (isRevisionStale() || responseTurnId !== currentTurnIdRef.current) {
        return;
      }

      clearAnswerDraft();
      await handleFollowup(followupResult, audioUrl, responseTurnId);
    } catch (err) {
      setError("Agent pipeline error. Check backend.");
      trackInterviewEvent(session_id, "room_turn_pipeline_error", {
        turn_id: turnId,
        request_version: requestVersion,
        error: String(err),
      }, "frontend.room", "error");
      beginUserTurn(session);
    } finally {
      processingRef.current = false;
      const pendingDraft = answerDraftRef.current;
      if (pendingDraft && pendingDraft.turnId === turnId && pendingDraft.pendingRevision) {
        pendingDraft.pendingRevision = false;
        pendingDraft.commitTimer = setTimeout(() => {
          void commitAnswerDraft(session, turnId);
        }, 150);
      }
    }
  }, [beginUserTurn, clearAnswerDraft, committedTurns.length, getRetainedAudio, handleFollowup, refreshCommittedState, session_id]);

  const queueAnswerChunk = useCallback((
    session: InterviewSession,
    text: string,
    entities: string[],
    settleMs: number | null = ANSWER_SETTLE_MS,
    questionOverride = "",
    revisionOfTurnId = "",
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
        question: questionOverride || activeQuestionRef.current,
        revisionOfTurnId,
        revisionQuestion: questionOverride || "",
        textParts: [],
        entitySet: new Set<string>(),
        submittedText: null,
        pendingRevision: false,
        requestVersion: 0,
        commitTimer: null,
      };
      answerDraftRef.current = draft;
    }

    const previousPart = draft.textParts[draft.textParts.length - 1];
    if (previousPart !== cleaned) draft.textParts.push(cleaned);
    entities.forEach((entity) => draft!.entitySet.add(entity));
    setLiveTranscript(draft.textParts.join(" "));

    if (draft.submittedText !== null && silenceConfirmedRef.current) {
      silenceConfirmedRef.current = false;
      commitTimeRef.current = performance.now();
      trackInterviewEvent(session_id, "room_turn_reopened_same_turn", {
        turn_id: turnId,
      }, "frontend.room");
    }

    if (draft.commitTimer) clearTimeout(draft.commitTimer);
    if (settleMs !== null) {
      draft.commitTimer = setTimeout(() => {
        void commitAnswerDraft(session, turnId);
      }, settleMs);
    } else {
      draft.commitTimer = null;
    }
  }, [clearAnswerDraft, commitAnswerDraft, session_id]);

  const reopenPreviousAnswerForContinuation = useCallback((session: InterviewSession | null) => {
    if (!session) return null;
    const continuation = lastCommittedAnswerRef.current;
    const canContinuePrevious =
      session.floor === FloorState.AI_THINKING ||
      session.floor === FloorState.AI_SPEAKING ||
      (Boolean(continuation?.turnId) && continuation?.turnId === currentTurnIdRef.current);
    if (
      !continuation?.question ||
      !canContinuePrevious ||
      !continuation.answer.trim()
    ) {
      return null;
    }

    clearAnswerDraft();
    const revisionTurnId = continuation.turnId || currentTurnIdRef.current || crypto.randomUUID();
    session.setActiveTurnId(revisionTurnId);
    currentTurnIdRef.current = revisionTurnId;
    continuationTurnIdRef.current = revisionTurnId;
    setCurrentQuestion(continuation.question);
    queueAnswerChunk(session, continuation.answer, [], null, continuation.question, continuation.turnId || revisionTurnId);
    return { ...continuation, turnId: revisionTurnId };
  }, [clearAnswerDraft, queueAnswerChunk]);

  async function attachCamera(session: InterviewSession) {
    setCameraError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Camera is not available in this browser.");
      return;
    }

    try {
      stopCameraStream();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          width: { ideal: 640 },
          height: { ideal: 360 },
          facingMode: "user",
        },
      });
      cameraStreamRef.current = stream;
      setCameraOn(true);
      setCameraVisible(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
        await session.startVision(videoRef.current).catch(() => undefined);
      }
    } catch {
      setCameraOn(false);
      setCameraVisible(true);
      setCameraError("Camera preview blocked. Mock presence remains active.");
    }
  }

  async function ensureMediaPermissions() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser cannot request microphone and camera permissions.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    stream.getTracks().forEach((track) => track.stop());
  }

  async function bootInterview(snapshot: SessionSnapshot, mode: "new" | "resume") {
    setBootingMode(mode);
    setError("");
    setStarted(true);
    setComplete(false);
    completeRef.current = false;
    const opening = snapshot.last_question || "";
    setCurrentQuestion(opening);
    setCommittedTurns((snapshot.history || []).map(normalizeTurn));
    setQuestionCount(snapshot.question_count ?? (snapshot.history || []).length);

    trackInterviewEvent(session_id, "room_boot_interview", {
      mode,
      existing_turns: snapshot.question_count ?? 0,
      completed: Boolean(snapshot.interview_complete),
    }, "frontend.room");

    FOLLOWUP_ACK_TEXTS.forEach((text, index) => {
      void getRetainedAudio(`static:followup_ack:${index}`, text);
    });
    void getRetainedAudio("static:followup_ack:late", LATE_FOLLOWUP_ACK_TEXT);
    void getRetainedAudio("static:followup_ack:closing", CLOSING_ACK_TEXT);
    void getRetainedAudio("static:repeat_lead_in", REPEAT_LEAD_IN_TEXT);
    void getRetainedAudio("static:pause", PAUSE_TEXT);
    const openingAudioUrl = opening ? await getRetainedAudio(`question:${opening}`, opening) : null;
    const session = new InterviewSession(session_id);
    sessionRef.current = session;

    session.onFloorChange = (floor) => {
      if (roomLockRef.current !== "none") return;
      if (floor === FloorState.USER_SPEAKING) setPhase("listening");
      else if (floor === FloorState.AI_THINKING) setPhase("reviewing");
      else if (floor === FloorState.AI_SPEAKING) setPhase("asking");
      else setPhase(completeRef.current ? "closing" : "ready");
    };

    session.onBargeIn = (initialText) => {
      if (roomLockRef.current !== "none") return;
      playbackSeqRef.current += 1;
      const continuation = reopenPreviousAnswerForContinuation(session);
      if (!continuation) {
        clearAnswerDraft();
        currentTurnIdRef.current = crypto.randomUUID();
        session.setActiveTurnId(currentTurnIdRef.current);
        setLiveTranscript("");
      }
      setLiveTranscriptOpen(true);
      const cleanedInitialText = initialText?.trim() || "";
      if (cleanedInitialText && continuation) {
        setLiveTranscript(`${continuation.answer} ${cleanedInitialText}`.replace(/\s+/g, " ").trim());
      } else if (cleanedInitialText) {
        queueAnswerChunk(session, cleanedInitialText, [], null);
      }
      trackInterviewEvent(session_id, "room_barge_in", {
        seeded_chars: cleanedInitialText.length,
        continuation: Boolean(continuation),
      }, "frontend.room", "warn");
    };

    session.onSilence = async () => {
      if (roomLockRef.current !== "none") return;
      if (session.floor === FloorState.AI_THINKING) {
        silenceConfirmedRef.current = true;
        trackInterviewEvent(session_id, "room_silence_confirmed", {}, "frontend.room");
        return;
      }
      if (processingRef.current || session.floor !== FloorState.USER_SPEAKING) return;
      const ac = new AbortController();
      const playbackSeq = ++playbackSeqRef.current;
      const { url: nudgeUrl, text: nudgeText } = await prefetchFillerAudio();
      session.setAbortController(ac);
      session.setActivePlaybackText(nudgeText);
      session.transition(FloorState.AI_SPEAKING);
      try {
        await playAudioUrl(nudgeUrl, nudgeText, ac.signal);
      } catch {
        // interruption is expected on barge-in
      }
      if (playbackSeq !== playbackSeqRef.current) return;
      beginUserTurn(session);
    };

    session.onPartial = (text) => {
      if (roomLockRef.current !== "none") return;
      if (session.floor === FloorState.AI_THINKING) {
        const continuation = reopenPreviousAnswerForContinuation(session);
        session.transition(FloorState.USER_SPEAKING);
        if (continuation) {
          setLiveTranscript(`${continuation.answer} ${text}`.replace(/\s+/g, " ").trim());
          setLiveTranscriptOpen(true);
          trackInterviewEvent(session_id, "room_handoff_speech_continuation", {
            turn_id: continuation.turnId,
            chars: text.length,
            source: "partial",
          }, "frontend.room", "warn");
          return;
        }
      }
      setLiveTranscript(text);
    };

    session.onFinal = (text, entities, metadata) => {
      if (roomLockRef.current !== "none") return;
      const floorBeforeFlush = metadata?.floorBeforeFlush;
      if (
        floorBeforeFlush === FloorState.AI_THINKING ||
        continuationTurnIdRef.current === session.getActiveTurnId()
      ) {
        const continuation = reopenPreviousAnswerForContinuation(session);
        session.transition(FloorState.USER_SPEAKING);
        if (continuation) {
          trackInterviewEvent(session_id, "room_handoff_speech_continuation", {
            turn_id: continuation.turnId,
            chars: text.length,
            source: "final",
          }, "frontend.room", "warn");
        }
      }
      silenceConfirmedRef.current = metadata?.reason === "utterance_end";
      queueAnswerChunk(session, text, entities);
    };

    session.onError = (err) => {
      setError(`Voice error: ${err}`);
      trackInterviewEvent(session_id, "room_voice_error", { error: err }, "frontend.room", "error");
    };

    try {
      await session.start();
      stopVisualizerRef.current = session.connectVisualizer((level) => setMicEnergy(Math.max(0.05, Math.min(1, level))));
      await attachCamera(session);

      if (opening) {
        const ac = new AbortController();
        const playbackSeq = ++playbackSeqRef.current;
        session.setAbortController(ac);
        session.setActivePlaybackText(opening);
        session.transition(FloorState.AI_SPEAKING);
        await playAudioUrl(openingAudioUrl, opening, ac.signal, { revokeObjectUrl: false });
        if (playbackSeq !== playbackSeqRef.current) return;
        beginUserTurn(session);
      } else {
        beginUserTurn(session);
      }
    } catch (err) {
      setError(`Could not start interview room: ${String(err)}`);
      setStarted(false);
      setPhase("ready");
      trackInterviewEvent(session_id, "room_boot_failed", {
        mode,
        error: String(err),
      }, "frontend.room", "error");
    } finally {
      setBootingMode(null);
    }
  }

  async function startInterview() {
    try {
      await ensureMediaPermissions();
      const snapshot = await fetchSessionSnapshot();
      if (!snapshot) return;
      applySnapshot(snapshot);

      if ((snapshot.question_count ?? 0) > 0 || snapshot.interview_complete) {
        return;
      }
      if (!snapshot.interview_trajectory_map?.focus_areas?.length) {
        throw new Error("Interview trajectory map missing from session startup state");
      }
      await runStartCountdown();
      await bootInterview(snapshot, "new");
    } catch (err) {
      setError(`Could not start interview: ${String(err)}`);
      setBootingMode(null);
    }
  }

  async function resumeInterview() {
    try {
      await ensureMediaPermissions();
      const snapshot = await fetchSessionSnapshot();
      if (!snapshot) return;
      applySnapshot(snapshot);
      await runStartCountdown();
      await bootInterview(snapshot, "resume");
    } catch (err) {
      setError(`Could not resume interview: ${String(err)}`);
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
    resetLiveState();

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
      if (!prepareRes.ok) throw new Error(prepareData?.detail || `Server error ${prepareRes.status}`);
      if (prepareData?.map_status !== "ready") throw new Error("Interview map did not reach ready state.");

      const startRes = await fetch(`${API}/start_interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prepared_session_id: prepareData.session_id }),
      });
      const startData = await startRes.json().catch(() => ({}));
      if (!startRes.ok) throw new Error(startData?.detail || `Server error ${startRes.status}`);
      router.replace(`/interview-room/${startData.session_id}`);
    } catch (err) {
      setError(`Could not start a fresh run: ${String(err)}`);
      setBootingMode(null);
    }
  }

  async function confirmEndInterview() {
    teardownActiveSession();
    completeRef.current = true;
    setRoomLockState("none");
    setPhase("closing");
    setComplete(true);
    try {
      await fetch(`${API}/end_interview/${encodeURIComponent(session_id)}`, { method: "POST" });
    } catch {
      // Report page can still show partial state.
    }
    const returnUrl = getExternalReturnUrl();
    if (returnUrl) window.location.assign(returnUrl);
    else router.push(`/report/${session_id}`);
  }

  function requestEndInterview() {
    if (!started && !complete) return;
    const session = sessionRef.current;
    floorBeforeLockRef.current = session?.floor ?? null;
    playbackSeqRef.current += 1;
    session?.abortActivePlayback();
    const draft = answerDraftRef.current;
    if (draft?.commitTimer) {
      clearTimeout(draft.commitTimer);
      draft.commitTimer = null;
    }
    setRoomLockState("confirm_end");
    trackInterviewEvent(session_id, "room_end_confirm_open", {
      floor_before_lock: floorBeforeLockRef.current,
    }, "frontend.room");
  }

  function cancelEndInterview() {
    setRoomLockState("none");
    const session = sessionRef.current;
    const previousFloor = floorBeforeLockRef.current;
    floorBeforeLockRef.current = null;
    if (!session || completeRef.current) return;
    if (previousFloor === FloorState.AI_THINKING) {
      session.transition(FloorState.AI_THINKING);
      return;
    }
    if (previousFloor === FloorState.AI_SPEAKING) {
      void repeatQuestion();
      return;
    }
    if (previousFloor === FloorState.USER_SPEAKING) {
      setLiveTranscriptOpen(true);
      session.transition(FloorState.USER_SPEAKING);
      return;
    }
    beginUserTurn(session);
  }

  async function repeatQuestion() {
    const session = sessionRef.current;
    const question = activeQuestionRef.current;
    if (!started || complete || !session || !question || roomLockRef.current !== "none") return;
    session.abortActivePlayback();
    const playbackSeq = ++playbackSeqRef.current;
    const ac = new AbortController();
    session.setAbortController(ac);
    session.transition(FloorState.AI_SPEAKING);
    const [leadInUrl, questionUrl] = await Promise.all([
      getRetainedAudio("static:repeat_lead_in", REPEAT_LEAD_IN_TEXT),
      getRetainedAudio(`question:${question}`, question),
    ]);
    if (playbackSeq !== playbackSeqRef.current) return;
    session.setActivePlaybackText(REPEAT_LEAD_IN_TEXT);
    await playAudioUrl(leadInUrl, REPEAT_LEAD_IN_TEXT, ac.signal, { revokeObjectUrl: false }).catch(() => undefined);
    if (playbackSeq !== playbackSeqRef.current) return;
    session.setActivePlaybackText(question);
    await playAudioUrl(questionUrl, question, ac.signal, { revokeObjectUrl: false }).catch(() => undefined);
    if (playbackSeq !== playbackSeqRef.current) return;
    beginUserTurn(session);
  }

  async function needMoment() {
    if (!started || complete || pauseUsesRemaining <= 0 || roomLockRef.current !== "none") return;
    const session = sessionRef.current;
    if (!session) return;
    floorBeforeLockRef.current = session.floor;
    setPauseUsesRemaining((remaining) => Math.max(0, remaining - 1));
    playbackSeqRef.current += 1;
    session.abortActivePlayback();
    const draft = answerDraftRef.current;
    if (draft?.commitTimer) {
      clearTimeout(draft.commitTimer);
      draft.commitTimer = null;
    }
    setLiveTranscriptOpen(false);
    setRoomLockState("paused");
    roomLockRef.current = "paused";
    trackInterviewEvent(session_id, "room_pause_started", {
      pauses_remaining_after: Math.max(0, pauseUsesRemaining - 1),
      floor_before_lock: floorBeforeLockRef.current,
    }, "frontend.room");

    const ac = new AbortController();
    const playbackSeq = ++playbackSeqRef.current;
    session.setAbortController(ac);
    session.setActivePlaybackText(PAUSE_TEXT);
    session.transition(FloorState.AI_SPEAKING);
    const pauseUrl = await getRetainedAudio("static:pause", PAUSE_TEXT);
    if (playbackSeq !== playbackSeqRef.current || roomLockRef.current !== "paused") return;
    await playAudioUrl(pauseUrl, PAUSE_TEXT, ac.signal, { revokeObjectUrl: false }).catch(() => undefined);
    if (playbackSeq === playbackSeqRef.current && roomLockRef.current === "paused") {
      session.transition(FloorState.IDLE);
    }
  }

  function resumeFromPause() {
    if (roomLockRef.current !== "paused") return;
    setRoomLockState("none");
    const session = sessionRef.current;
    const previousFloor = floorBeforeLockRef.current;
    floorBeforeLockRef.current = null;
    if (!session || completeRef.current) return;
    if (previousFloor === FloorState.AI_SPEAKING) {
      void repeatQuestion();
      return;
    }
    if (previousFloor === FloorState.AI_THINKING) {
      session.transition(FloorState.AI_THINKING);
      return;
    }
    if (previousFloor === FloorState.USER_SPEAKING) {
      setLiveTranscriptOpen(true);
      session.transition(FloorState.USER_SPEAKING);
      return;
    }
    beginUserTurn(session);
  }

  function toggleCameraPreview() {
    setCameraVisible((visible) => !visible);
  }

  return (
    <InterviewRoomFloor
      sessionId={session_id}
      candidate={candidate}
      phase={phase}
      floorOwner={floorOwner}
      started={started}
      complete={complete}
      bootingMode={bootingMode}
      existingTurns={existingTurns}
      showResumeGate={showResumeGate}
      isCompletedSession={isCompletedSession}
      currentQuestion={currentQuestion}
      liveTranscript={liveTranscript}
      liveTranscriptOpen={liveTranscriptOpen}
      committedTurns={committedTurns}
      progressCurrent={progressCurrent}
      progressTotal={PROGRESS_TOTAL_TURNS}
      micEnergy={micEnergy}
      error={error}
      cameraOn={cameraOn}
      cameraVisible={cameraVisible}
      cameraError={cameraError}
      historyOpen={historyOpen}
      fullTranscriptOpen={fullTranscriptOpen}
      paused={roomLock === "paused"}
      confirmEndOpen={roomLock === "confirm_end"}
      startCountdown={startCountdown}
      pauseUsesRemaining={pauseUsesRemaining}
      videoRef={videoRef}
      onStart={startInterview}
      onResume={resumeInterview}
      onStartFresh={startFreshInterview}
      onEnd={requestEndInterview}
      onConfirmEnd={() => void confirmEndInterview()}
      onCancelEnd={cancelEndInterview}
      onResumeFromPause={resumeFromPause}
      onToggleCameraPreview={toggleCameraPreview}
      onToggleHistory={() => setHistoryOpen((open) => !open)}
      onToggleFullTranscript={() => setFullTranscriptOpen((open) => !open)}
      onToggleLiveTranscript={() => setLiveTranscriptOpen((open) => !open)}
      onNeedMoment={() => void needMoment()}
      onRepeatQuestion={() => void repeatQuestion()}
    />
  );
}
