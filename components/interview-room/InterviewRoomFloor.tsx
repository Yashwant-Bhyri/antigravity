"use client";

import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

export type InterviewRoomPhase = "ready" | "asking" | "listening" | "reviewing" | "closing";
export type InterviewRoomFloorOwner = "ready" | "ai" | "candidate";

export type InterviewRoomCandidate = {
  name: string;
  role: string;
  experience: string;
};

export type InterviewRoomTurn = {
  question: string;
  answer: string;
  sprint?: number;
};

type BootMode = "new" | "resume" | "fresh" | null;

export type InterviewRoomFloorProps = {
  sessionId: string;
  candidate: InterviewRoomCandidate;
  phase: InterviewRoomPhase;
  floorOwner: InterviewRoomFloorOwner;
  started: boolean;
  complete: boolean;
  bootingMode: BootMode;
  existingTurns: number;
  showResumeGate: boolean;
  isCompletedSession: boolean;
  currentQuestion: string;
  liveTranscript: string;
  liveTranscriptOpen: boolean;
  committedTurns: InterviewRoomTurn[];
  progressCurrent: number;
  progressTotal?: number;
  micEnergy: number;
  error: string;
  cameraOn: boolean;
  cameraVisible: boolean;
  cameraError: string;
  historyOpen: boolean;
  fullTranscriptOpen: boolean;
  paused: boolean;
  confirmEndOpen: boolean;
  startCountdown: number | null;
  pauseUsesRemaining: number;
  videoRef: RefObject<HTMLVideoElement | null>;
  onStart: () => void;
  onResume: () => void;
  onStartFresh: () => void;
  onEnd: () => void;
  onConfirmEnd: () => void;
  onCancelEnd: () => void;
  onResumeFromPause: () => void;
  onToggleCameraPreview: () => void;
  onToggleHistory: () => void;
  onToggleFullTranscript: () => void;
  onToggleLiveTranscript: () => void;
  onNeedMoment: () => void;
  onRepeatQuestion: () => void;
};

const PHASE_MURAL: Record<
  InterviewRoomPhase,
  {
    aura: `#${string}`;
    shift: number;
    a: string;
    b: string;
    c: string;
    auraState: AgentState;
    status: string;
    title: string;
    caption: string;
  }
> = {
  ready: {
    aura: "#7AA7FF",
    shift: 0.16,
    a: "oklch(0.66 0.14 248)",
    b: "oklch(0.62 0.1 282)",
    c: "oklch(0.72 0.08 220)",
    auraState: "idle",
    status: "Ready",
    title: "Ready when you are",
    caption: "The room is quiet. Start when you are ready.",
  },
  asking: {
    aura: "#FF9A3D",
    shift: 0.48,
    a: "oklch(0.74 0.18 50)",
    b: "oklch(0.7 0.16 32)",
    c: "oklch(0.68 0.11 76)",
    auraState: "speaking",
    status: "Asking question",
    title: "Asking question",
    caption: "The interviewer owns the floor. Listen to the question.",
  },
  listening: {
    aura: "#1FD5F9",
    shift: 0.3,
    a: "oklch(0.72 0.19 222)",
    b: "oklch(0.66 0.13 278)",
    c: "oklch(0.76 0.14 154)",
    auraState: "listening",
    status: "Listening to candidate's answer",
    title: "Listening to candidate's answer",
    caption: "The question remains anchored while your answer flows below it.",
  },
  reviewing: {
    aura: "#FFBE59",
    shift: 0.44,
    a: "oklch(0.78 0.14 72)",
    b: "oklch(0.68 0.14 34)",
    c: "oklch(0.72 0.12 292)",
    auraState: "thinking",
    status: "Reviewing candidate's answer",
    title: "Reviewing candidate's answer",
    caption: "Answer received. The next question is being prepared.",
  },
  closing: {
    aura: "#6CFF9E",
    shift: 0.26,
    a: "oklch(0.76 0.15 154)",
    b: "oklch(0.68 0.13 204)",
    c: "oklch(0.78 0.1 92)",
    auraState: "thinking",
    status: "Closing interview",
    title: "Closing interview",
    caption: "The interview is closing and the report is being prepared.",
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function questionDensity(text: string) {
  if (text.length > 220) return "dense";
  if (text.length > 150) return "compact";
  if (text.length > 86) return "medium";
  return "short";
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "CA";
}

export function InterviewRoomFloor({
  sessionId,
  candidate,
  phase,
  floorOwner,
  started,
  complete,
  bootingMode,
  existingTurns,
  showResumeGate,
  isCompletedSession,
  currentQuestion,
  liveTranscript,
  liveTranscriptOpen,
  committedTurns,
  progressCurrent,
  progressTotal = 15,
  micEnergy,
  error,
  cameraOn,
  cameraVisible,
  cameraError,
  historyOpen,
  fullTranscriptOpen,
  paused,
  confirmEndOpen,
  startCountdown,
  pauseUsesRemaining,
  videoRef,
  onStart,
  onResume,
  onStartFresh,
  onEnd,
  onConfirmEnd,
  onCancelEnd,
  onResumeFromPause,
  onToggleCameraPreview,
  onToggleHistory,
  onToggleFullTranscript,
  onToggleLiveTranscript,
  onNeedMoment,
  onRepeatQuestion,
}: InterviewRoomFloorProps) {
  const mural = PHASE_MURAL[phase];
  const questionCardRef = useRef<HTMLElement | null>(null);
  const questionScrollRef = useRef<HTMLDivElement | null>(null);
  const questionTextRef = useRef<HTMLHeadingElement | null>(null);
  const answerTextRef = useRef<HTMLDivElement | null>(null);
  const [questionFontSize, setQuestionFontSize] = useState<number | null>(null);
  const colorShift = clamp(mural.shift + micEnergy * 0.08, 0.08, 0.64);
  const displayTurns = useMemo(
    () =>
      committedTurns
        .map((turn, index) => ({ ...turn, turnNumber: index + 1 }))
        .reverse(),
    [committedTurns],
  );
  const progressItems = Array.from({ length: progressTotal }, (_, index) => index);
  const activeQuestion =
    currentQuestion.trim() ||
    (complete
      ? "That gives me enough signal. I am closing the interview and preparing your report."
      : "When you are ready, start the live interview room.");
  const density = questionDensity(activeQuestion);
  const floorLabel =
    floorOwner === "candidate"
      ? "Candidate speaking"
      : floorOwner === "ai"
        ? "Interviewer asking"
        : "Turn";
  const activityText =
    phase === "asking"
      ? "Interviewer asking"
      : phase === "listening"
        ? "Candidate speaking"
        : phase === "reviewing"
          ? "Interviewer thinking"
          : phase === "closing"
            ? "Closing interview"
            : "Interview room is ready";
  const roomLocked = paused || confirmEndOpen || startCountdown !== null;

  useLayoutEffect(() => {
    const card = questionCardRef.current;
    const scroller = questionScrollRef.current;
    const text = questionTextRef.current;
    if (!card || !scroller || !text) return;

    const fitQuestion = () => {
      const availableWidth = scroller.clientWidth - 6;
      const availableHeight = scroller.clientHeight - 4;
      if (availableWidth <= 0 || availableHeight <= 0) return;

      const boost = historyOpen ? 0 : 3;
      const bounds =
        density === "dense"
          ? { min: 18, max: 36 + boost, line: 1.08 }
          : density === "compact"
            ? { min: 22, max: 44 + boost, line: 1.07 }
            : density === "medium"
              ? { min: 29, max: 54 + boost, line: 1.05 }
              : { min: 34, max: 62 + boost, line: 1.04 };

      const previousFont = text.style.fontSize;
      const previousLine = text.style.lineHeight;
      const previousWidth = text.style.width;
      text.style.width = `${availableWidth}px`;
      text.style.lineHeight = String(bounds.line);

      let low = bounds.min;
      let high = bounds.max;
      let best = bounds.min;
      for (let i = 0; i < 10; i += 1) {
        const mid = (low + high) / 2;
        text.style.fontSize = `${mid}px`;
        const fits = text.scrollHeight <= availableHeight - 2 && text.scrollWidth <= availableWidth;
        if (fits) {
          best = mid;
          low = mid;
        } else {
          high = mid;
        }
      }

      text.style.fontSize = previousFont;
      text.style.lineHeight = previousLine;
      text.style.width = previousWidth;
      setQuestionFontSize(Math.floor(best * 10) / 10);
    };

    fitQuestion();
    const observer = new ResizeObserver(fitQuestion);
    observer.observe(card);
    observer.observe(scroller);
    return () => observer.disconnect();
  }, [activeQuestion, density, historyOpen]);

  useLayoutEffect(() => {
    if (!questionScrollRef.current) return;
    questionScrollRef.current.scrollTop = 0;
  }, [activeQuestion]);

  useLayoutEffect(() => {
    const node = answerTextRef.current;
    if (!node || !liveTranscriptOpen) return;
    node.scrollTop = node.scrollHeight;
  }, [liveTranscript, liveTranscriptOpen]);

  return (
    <main
      className="lk-room"
      data-phase={phase}
      data-floor={floorOwner}
      data-locked={roomLocked ? "true" : "false"}
      style={
        {
          "--energy": clamp(micEnergy, 0, 1).toFixed(3),
          "--center-glow": `${0.13 + clamp(micEnergy, 0, 1) * 0.08}`,
          "--edge-glow": `${0.14 + clamp(micEnergy, 0, 1) * 0.07}`,
          "--caustic-opacity": `${0.05 + clamp(micEnergy, 0, 1) * 0.035}`,
          "--border-glow": `${22 + clamp(micEnergy, 0, 1) * 36}px`,
          "--mural-a": mural.a,
          "--mural-b": mural.b,
          "--mural-c": mural.c,
          "--floor-ai": "#FF9A3D",
          "--floor-candidate": "#1FD5F9",
        } as CSSProperties
      }
    >
      <style>{`
        .lk-room {
          min-height: 100vh;
          overflow: hidden;
          color: white;
          background:
            radial-gradient(74rem 44rem at 52% 46%, color-mix(in oklch, var(--mural-a) calc(var(--center-glow) * 100%), transparent), transparent 56%),
            radial-gradient(54rem 32rem at 52% 52%, color-mix(in oklch, var(--mural-c) 9%, transparent), transparent 62%),
            radial-gradient(44rem 30rem at 18% 8%, color-mix(in oklch, var(--mural-b) 5%, transparent), transparent 66%),
            linear-gradient(180deg, #071014, #020304 82%);
          isolation: isolate;
        }
        .lk-room::before {
          content: "";
          position: fixed;
          inset: -10%;
          z-index: 0;
          pointer-events: none;
          opacity: var(--caustic-opacity);
          mix-blend-mode: screen;
          filter: blur(10px);
          background:
            radial-gradient(42rem 24rem at 50% 46%, color-mix(in oklch, var(--mural-a) 48%, transparent), transparent 66%),
            repeating-linear-gradient(38deg, transparent 0 56px, color-mix(in oklch, var(--mural-c) 9%, transparent) 64px 69px, transparent 82px 142px, color-mix(in oklch, var(--mural-a) 7%, transparent) 154px 160px, transparent 176px 252px);
          mask-image:
            radial-gradient(ellipse at 50% 46%, black 0 45%, transparent 72%),
            linear-gradient(38deg, transparent 0 18%, black 30% 70%, transparent 86%);
          animation: lk-caustic-drift 18s ease-in-out infinite alternate;
        }
        .lk-room::after {
          content: "";
          position: fixed;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          opacity: 0.08;
          background:
            radial-gradient(circle at 50% 44%, transparent 0 42%, rgba(0,0,0,0.18) 72%, rgba(0,0,0,0.76) 100%),
            radial-gradient(circle, rgba(255,255,255,0.15) 0 1px, transparent 1.5px);
          background-size: auto, 30px 30px;
          mask-image: linear-gradient(180deg, black 0 72%, transparent 100%);
        }
        .lk-shell {
          position: relative;
          z-index: 2;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr);
          gap: 14px;
          width: min(1480px, calc(100vw - 32px));
          height: 100vh;
          min-height: 0;
          margin: 0 auto;
          padding: 18px 0;
        }
        .lk-topbar,
        .lk-glass {
          border: 1px solid rgba(255,255,255,0.1);
          background:
            linear-gradient(180deg, rgba(255,255,255,0.048), transparent 58%),
            rgba(4, 8, 10, 0.72);
          box-shadow:
            0 24px 80px rgba(0,0,0,0.34),
            0 0 var(--border-glow) color-mix(in oklch, var(--mural-a) 5%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.035);
          backdrop-filter: blur(22px) saturate(1.12);
        }
        .lk-topbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 18px;
          min-height: 78px;
          border-radius: 28px;
          padding: 15px 18px;
        }
        .lk-brand {
          display: flex;
          align-items: center;
          gap: 14px;
        }
        .lk-mark {
          display: grid;
          width: 42px;
          height: 42px;
          place-items: center;
          border-radius: 14px;
          background: radial-gradient(circle at 30% 24%, color-mix(in oklch, var(--mural-a) 82%, white 8%), #071014 72%);
          box-shadow: 0 0 30px color-mix(in oklch, var(--mural-a) 28%, transparent);
        }
        .lk-mark::after {
          content: "";
          height: 16px;
          width: 16px;
          border: 2px solid white;
          border-left-color: transparent;
          border-radius: 999px;
          transform: rotate(-35deg);
        }
        .lk-eyebrow,
        .lk-label {
          margin: 0;
          color: rgba(255,255,255,0.44);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.22em;
          line-height: 1;
          text-transform: uppercase;
        }
        .lk-title {
          margin: 7px 0 0;
          font-size: clamp(19px, 1.6vw, 25px);
          font-weight: 760;
          letter-spacing: 0;
        }
        .lk-chips {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 8px;
        }
        .lk-chip {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          min-height: 34px;
          border: 1px solid rgba(255,255,255,0.09);
          border-radius: 999px;
          padding: 7px 12px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.72);
          font-size: 12px;
          font-weight: 650;
        }
        .lk-dot {
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: var(--mural-a);
          box-shadow: 0 0 16px var(--mural-a);
        }
        .lk-workspace {
          display: grid;
          grid-template-columns: minmax(260px, 310px) minmax(0, 1fr) minmax(250px, 310px);
          align-items: stretch;
          gap: 14px;
          min-height: 0;
          overflow: hidden;
          transition: grid-template-columns 260ms ease;
        }
        .lk-workspace.history-collapsed {
          grid-template-columns: minmax(250px, 310px) minmax(0, 1fr) 72px;
        }
        .lk-glass {
          position: relative;
          overflow: hidden;
          border-radius: 30px;
        }
        .lk-presence,
        .lk-stage,
        .lk-memory {
          min-height: 0;
        }
        .lk-presence {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          gap: 16px;
          padding: 18px;
        }
        .lk-state-title {
          margin: 13px 0 0;
          font-size: clamp(26px, 2.2vw, 36px);
          font-weight: 760;
          line-height: 1.08;
          letter-spacing: 0;
        }
        .lk-aura-stage {
          display: grid;
          min-height: 300px;
          place-items: center;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 26px;
          background: rgba(0,0,0,0.28);
        }
        .lk-aura-wrap {
          width: min(86%, 260px);
          opacity: 0.94;
          transform: translateY(-10px) scale(1.04);
        }
        .lk-presence-note,
        .lk-signal {
          border: 1px solid rgba(255,255,255,0.075);
          border-radius: 18px;
          background: rgba(0,0,0,0.42);
          padding: 14px;
          color: rgba(255,255,255,0.68);
          font-size: 13px;
          line-height: 1.45;
        }
        .lk-signal {
          display: grid;
          gap: 9px;
        }
        .lk-meter {
          height: 7px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
        }
        .lk-meter span {
          display: block;
          width: calc(8% + var(--energy) * 72%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--mural-a), var(--mural-c));
          transition: width 120ms linear;
        }
        .lk-stage {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          align-self: stretch;
          box-shadow:
            0 0 calc(28px + var(--energy) * 18px) color-mix(in oklch, var(--mural-a) 12%, transparent),
            inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 10%, transparent);
        }
        .lk-stage-top {
          display: grid;
          gap: 0;
          padding: 7px 22px 8px;
          border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .lk-stage-top-inner {
          display: grid;
          gap: 2px;
          justify-self: center;
          justify-items: stretch;
          width: min(760px, calc(100% - 40px));
        }
        .lk-progress {
          display: flex;
          justify-self: center;
          width: 100%;
          justify-content: center;
          gap: 4px;
        }
        .lk-progress span {
          height: 4px;
          flex: 0 1 24px;
          width: clamp(10px, 2vw, 24px);
          border-radius: 999px;
          background: rgba(255,255,255,0.12);
        }
        .lk-progress span.done {
          background: var(--mural-a);
          box-shadow: 0 0 18px color-mix(in oklch, var(--mural-a) 40%, transparent);
        }
        .lk-floor {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
          align-items: center;
          gap: 20px;
          width: 100%;
          margin: 3px auto 0;
        }
        .lk-corner {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
          position: relative;
          color: rgba(255,255,255,0.42);
          font-size: 11px;
          font-weight: 850;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
        .lk-corner span {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          white-space: nowrap;
        }
        .lk-corner span::before {
          content: "";
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: rgba(255,255,255,0.16);
        }
        .lk-corner::before,
        .lk-corner::after {
          content: "";
          height: 3px;
          flex: 1;
          border-radius: 999px;
          background: rgba(255,255,255,0.1);
        }
        .lk-room[data-floor="ai"] .lk-corner.ai,
        .lk-room[data-floor="candidate"] .lk-corner.candidate {
          color: rgba(255,255,255,0.78);
        }
        .lk-room[data-floor="ai"] .lk-corner.ai span::before,
        .lk-room[data-floor="candidate"] .lk-corner.candidate span::before {
          background: var(--active-floor);
          box-shadow: 0 0 16px var(--active-floor), 0 0 34px var(--active-floor);
        }
        .lk-room[data-floor="ai"] .lk-corner.ai::before,
        .lk-room[data-floor="ai"] .lk-corner.ai::after,
        .lk-room[data-floor="candidate"] .lk-corner.candidate::before,
        .lk-room[data-floor="candidate"] .lk-corner.candidate::after {
          background: var(--active-floor);
          box-shadow: 0 0 18px var(--active-floor);
        }
        .lk-room[data-floor="ai"] {
          --active-floor: var(--floor-ai);
        }
        .lk-room[data-floor="candidate"] {
          --active-floor: var(--floor-candidate);
        }
        .lk-room[data-floor="ready"] {
          --active-floor: var(--mural-a);
        }
        .lk-floor-pill,
        .lk-activity-box {
          border: 1px solid color-mix(in oklch, var(--mural-a) 24%, rgba(255,255,255,0.12));
          border-radius: 999px;
          background: rgba(0,0,0,0.48);
          padding: 10px 18px;
          color: rgba(255,255,255,0.86);
          font-size: 12px;
          font-weight: 850;
          letter-spacing: 0.18em;
          text-align: center;
          text-transform: uppercase;
          box-shadow: 0 0 24px color-mix(in oklch, var(--mural-a) 12%, transparent);
        }
        .lk-floor-pill {
          padding: 7px 14px;
          font-size: 10.5px;
          letter-spacing: 0.15em;
        }
        .lk-activity-box {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          justify-self: center;
          width: fit-content;
          margin: 2px auto 0;
          padding: 8px 18px 8px 13px;
          letter-spacing: 0;
          text-transform: none;
          font-size: 15px;
          font-weight: 760;
          border-color: color-mix(in oklch, var(--active-floor) 42%, rgba(255,255,255,0.14));
          box-shadow:
            0 0 0 1px color-mix(in oklch, var(--active-floor) 8%, transparent),
            0 0 26px color-mix(in oklch, var(--active-floor) 18%, transparent);
        }
        .lk-activity-text {
          line-height: 1;
          white-space: nowrap;
        }
        .lk-activity-box .lk-dot {
          width: 12px;
          height: 12px;
          flex: 0 0 auto;
          background: var(--active-floor);
          box-shadow:
            0 0 0 4px color-mix(in oklch, var(--active-floor) 15%, transparent),
            0 0 18px var(--active-floor),
            0 0 34px color-mix(in oklch, var(--active-floor) 48%, transparent);
        }
        .lk-stage-body {
          display: grid;
          grid-template-rows: auto auto auto;
          align-content: start;
          gap: 12px;
          min-height: 0;
          overflow: hidden;
          padding: clamp(8px, 1.1vw, 12px) clamp(20px, 3vw, 34px) 12px;
          background:
            radial-gradient(46rem 18rem at 50% 14%, color-mix(in oklch, var(--mural-a) 8%, transparent), transparent 72%),
            linear-gradient(180deg, transparent, color-mix(in oklch, var(--mural-a) 4%, transparent));
        }
        .lk-question-card {
          position: relative;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr);
          height: clamp(178px, 22vh, 226px);
          align-items: stretch;
          overflow: hidden;
          border: 1px solid color-mix(in oklch, var(--mural-a) 20%, rgba(255,255,255,0.12));
          border-radius: 28px;
          background: #000;
          padding: clamp(16px, 2vw, 24px) clamp(22px, 3vw, 38px);
          box-shadow:
            0 0 0 1px rgba(255,255,255,0.025),
            0 0 44px color-mix(in oklch, var(--mural-a) 14%, transparent);
        }
        .lk-question-card::before {
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          border-radius: inherit;
          background:
            linear-gradient(180deg, rgba(255,255,255,0.018), transparent 30%),
            radial-gradient(42rem 18rem at 50% 0%, color-mix(in oklch, var(--mural-a) 3%, transparent), transparent 62%);
          opacity: 0.28;
        }
        .lk-question-card.sync-glow::before {
          opacity: 0.34;
        }
        .lk-question-card.question-medium {
          height: clamp(198px, 24vh, 246px);
        }
        .lk-question-card.question-compact {
          height: clamp(224px, 27vh, 276px);
        }
        .lk-question-card.question-dense {
          height: clamp(264px, 32vh, 332px);
        }
        .lk-question-label {
          position: relative;
          z-index: 2;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .lk-question-scroll {
          position: relative;
          z-index: 2;
          display: grid;
          align-items: center;
          min-height: 0;
          overflow: auto;
          padding: 10px 4px 4px 0;
          scrollbar-color: color-mix(in oklch, var(--mural-a) 42%, rgba(255,255,255,0.24)) transparent;
        }
        .lk-question-scroll::after {
          content: "";
          position: absolute;
          right: clamp(18px, 2.6vw, 34px);
          bottom: 0;
          left: clamp(18px, 2.6vw, 34px);
          height: 22px;
          pointer-events: none;
          background: linear-gradient(180deg, transparent, #000);
          opacity: 0.36;
        }
        .lk-question {
          width: 100%;
          margin: 0;
          font-size: clamp(34px, 3.25vw, 54px);
          font-weight: 780;
          letter-spacing: 0;
          line-height: 1.04;
          text-shadow: 0 2px 20px rgba(0,0,0,0.7);
        }
        .lk-question.medium { font-size: clamp(30px, 2.7vw, 44px); }
        .lk-question.compact { font-size: clamp(27px, 2.35vw, 38px); }
        .lk-question.dense { font-size: clamp(23px, 2vw, 32px); line-height: 1.08; }
        .lk-answer-panel {
          position: relative;
          overflow: hidden;
          height: 70px;
          min-height: 70px;
          max-height: 100%;
          border: 1px solid color-mix(in oklch, var(--mural-a) 12%, rgba(255,255,255,0.075));
          border-radius: 20px;
          background: rgba(0,0,0,0.22);
          transition: max-height 220ms ease;
        }
        .lk-answer-panel.open {
          height: min(132px, 16vh);
          min-height: 106px;
          max-height: 100%;
        }
        .lk-answer-inner {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr);
          height: 100%;
          min-height: 0;
          padding: 12px 16px;
        }
        .lk-answer-head {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: center;
          gap: 12px;
          min-height: 36px;
        }
        .lk-answer-toggle {
          position: static;
          justify-self: end;
          min-height: 30px;
          padding: 5px 10px;
          border-radius: 12px;
          font-size: 12px;
          line-height: 1;
          white-space: nowrap;
        }
        .lk-answer-text {
          display: block;
          margin: 8px 0 0;
          overflow: hidden;
          color: rgba(255,255,255,0.68);
          font-size: 15px;
          line-height: 1.42;
        }
        .lk-answer-panel.open .lk-answer-text {
          max-height: none;
          overflow: auto;
        }
        .lk-answer-panel:not(.open) .lk-answer-text {
          color: rgba(255,255,255,0.45);
          white-space: nowrap;
          text-overflow: ellipsis;
        }
        .lk-answer-placeholder {
          color: rgba(255,255,255,0.46);
        }
        .lk-caret {
          display: inline-block;
          width: 0.42em;
          height: 1em;
          margin-left: 3px;
          transform: translateY(0.16em);
          border-radius: 2px;
          background: var(--mural-a);
          animation: lk-blink 850ms step-end infinite;
        }
        .lk-actions {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 10px;
        }
        .lk-actions {
          border-top: 1px solid rgba(255,255,255,0.08);
          padding: 12px 20px;
        }
        .lk-btn {
          min-height: 40px;
          border: 1px solid rgba(255,255,255,0.11);
          border-radius: 14px;
          padding: 10px 14px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.78);
          cursor: pointer;
          font: inherit;
          transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
        }
        .lk-btn:hover {
          transform: translateY(-1px);
          border-color: color-mix(in oklch, var(--mural-a) 36%, white 6%);
          background: rgba(255,255,255,0.075);
        }
        .lk-btn.primary {
          border-color: color-mix(in oklch, var(--mural-a) 36%, transparent);
          background: color-mix(in oklch, var(--mural-a) 13%, rgba(255,255,255,0.05));
          color: white;
        }
        .lk-btn.danger {
          margin-left: auto;
          border-color: rgba(255,95,127,0.26);
          color: rgba(255,180,190,0.9);
        }
        .lk-btn:disabled {
          cursor: not-allowed;
          opacity: 0.48;
          transform: none;
        }
        .lk-memory {
          display: grid;
          grid-template-rows: auto auto auto minmax(0, 1fr) auto;
          gap: 10px;
          min-height: 0;
          overflow: hidden;
          padding: 14px;
        }
        .lk-memory.collapsed {
          display: block;
          padding: 0;
        }
        .lk-memory.collapsed > :not(.lk-history-toggle) {
          display: none;
        }
        .lk-history-toggle.collapsed {
          writing-mode: vertical-rl;
          text-orientation: mixed;
          width: 100%;
          height: 100%;
          min-height: 100%;
          padding: 16px 0;
          letter-spacing: 0.12em;
          font-size: 12.5px;
          font-weight: 700;
          text-transform: uppercase;
          display: grid;
          place-items: center;
          line-height: 1;
          border-radius: 30px;
        }
        .lk-camera {
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          background: #030506;
        }
        .lk-room[data-floor="candidate"] .lk-camera {
          border-color: color-mix(in oklch, var(--mural-a) 44%, rgba(255,255,255,0.12));
          box-shadow: 0 0 28px color-mix(in oklch, var(--mural-a) 16%, transparent);
        }
        .lk-camera-frame {
          position: relative;
          display: grid;
          height: clamp(154px, 18vh, 220px);
          place-items: center;
          align-content: center;
          overflow: hidden;
          background: radial-gradient(14rem 9rem at 50% 38%, color-mix(in oklch, var(--mural-a) 14%, transparent), transparent 62%), #030506;
        }
        .lk-camera-video {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0;
          transform: scaleX(-1);
          transition: opacity 180ms ease;
        }
        .lk-camera.camera-on:not(.hidden-preview) .lk-camera-video {
          opacity: 1;
        }
        .lk-avatar {
          position: relative;
          z-index: 1;
          display: grid;
          width: 86px;
          height: 86px;
          place-items: center;
          border: 1px solid color-mix(in oklch, var(--mural-a) 34%, rgba(255,255,255,0.12));
          border-radius: 24px;
          background: rgba(0,0,0,0.45);
          font-weight: 850;
        }
        .lk-camera.hidden-preview .lk-avatar {
          width: 82px;
          height: 82px;
          margin-top: 16px;
          border-radius: 26px;
          background:
            radial-gradient(circle at 50% 42%, color-mix(in oklch, var(--mural-a) 13%, transparent), transparent 70%),
            rgba(0,0,0,0.54);
          box-shadow:
            0 0 28px color-mix(in oklch, var(--mural-a) 14%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.035);
        }
        .lk-camera.camera-on:not(.hidden-preview) .lk-avatar {
          opacity: 0;
        }
        .lk-camera.hidden-preview .lk-camera-frame::after {
          content: "Preview hidden";
          position: absolute;
          left: 50%;
          top: 13px;
          transform: translateX(-50%);
          bottom: auto;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 5px 8px;
          background: rgba(0,0,0,0.52);
          color: rgba(255,255,255,0.62);
          font-size: 9px;
          font-weight: 760;
          letter-spacing: 0.1em;
          text-transform: uppercase;
        }
        .lk-camera-meta {
          display: grid;
          gap: 7px;
          padding: 8px;
        }
        .lk-memory-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          min-height: 0;
          overflow: auto;
          margin-top: 4px;
          padding-right: 3px;
          scrollbar-color: color-mix(in oklch, var(--mural-a) 42%, rgba(255,255,255,0.24)) rgba(255,255,255,0.05);
        }
        .lk-turn-card {
          border: 1px solid color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.08));
          border-radius: 20px;
          background: color-mix(in oklch, var(--mural-a) 8%, rgba(255,255,255,0.03));
          padding: 14px;
          color: rgba(255,255,255,0.66);
          font-size: 12px;
          line-height: 1.45;
        }
        .lk-turn-card p {
          margin: 8px 0 0;
        }
        .lk-turn-card strong {
          color: rgba(255,255,255,0.9);
        }
        .lk-turn-answer {
          display: none;
        }
        .lk-memory.full .lk-turn-answer {
          display: block;
        }
        .lk-empty,
        .lk-error,
        .lk-launch {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 24px;
          background: rgba(0,0,0,0.38);
          padding: 18px;
          color: rgba(255,255,255,0.68);
        }
        .lk-launch {
          max-width: 620px;
          margin: auto;
          padding: 34px;
          text-align: center;
        }
        .lk-launch h2 {
          margin: 0;
          font-size: clamp(32px, 4vw, 54px);
          letter-spacing: 0;
        }
        .lk-launch p {
          margin: 16px auto 0;
          max-width: 520px;
          line-height: 1.65;
        }
        .lk-error {
          border-color: rgba(255,118,118,0.25);
          color: rgba(255,196,196,0.86);
        }
        .lk-note {
          margin: 0;
          color: rgba(255,255,255,0.5);
        }
        .lk-memory-heading {
          display: grid;
          gap: 6px;
          min-height: 72px;
        }
        .lk-closing {
          position: fixed;
          inset: 0;
          z-index: 20;
          display: none;
          place-items: center;
          padding: 24px;
          background: radial-gradient(circle at 50% 44%, color-mix(in oklch, var(--mural-c) 18%, transparent), transparent 44%), rgba(0,0,0,0.58);
          backdrop-filter: blur(24px);
        }
        .lk-closing.open {
          display: grid;
        }
        .lk-closing-card {
          width: min(720px, 100%);
          border-radius: 30px;
          padding: 34px;
          text-align: center;
        }
        .lk-closing-card h2 {
          margin: 0;
          font-size: clamp(36px, 7vw, 70px);
          letter-spacing: 0;
          line-height: 1.06;
        }
        .lk-closing-card p {
          max-width: 560px;
          margin: 18px auto 0;
          color: rgba(255,255,255,0.66);
          font-size: 18px;
          line-height: 1.55;
        }
        .lk-freeze {
          position: fixed;
          inset: 0;
          z-index: 30;
          display: none;
          place-items: center;
          padding: 24px;
          background:
            radial-gradient(circle at 50% 40%, color-mix(in oklch, var(--mural-a) 20%, transparent), transparent 42%),
            rgba(0,0,0,0.68);
          backdrop-filter: blur(24px) saturate(1.08);
        }
        .lk-freeze.open {
          display: grid;
        }
        .lk-freeze-card {
          width: min(640px, 100%);
          border-radius: 30px;
          padding: 30px;
          text-align: center;
        }
        .lk-freeze-mark {
          display: inline-grid;
          width: 76px;
          height: 76px;
          margin-bottom: 18px;
          place-items: center;
          border: 1px solid color-mix(in oklch, var(--mural-a) 42%, rgba(255,255,255,0.14));
          border-radius: 24px;
          background: color-mix(in oklch, var(--mural-a) 12%, rgba(0,0,0,0.68));
          color: white;
          font-size: 32px;
          font-weight: 850;
          box-shadow: 0 0 42px color-mix(in oklch, var(--mural-a) 20%, transparent);
        }
        .lk-freeze-card h2 {
          margin: 0;
          font-size: clamp(30px, 4.4vw, 54px);
          line-height: 1.04;
          letter-spacing: 0;
        }
        .lk-freeze-card p {
          max-width: 520px;
          margin: 14px auto 0;
          color: rgba(255,255,255,0.68);
          font-size: 16px;
          line-height: 1.55;
        }
        .lk-freeze-actions {
          display: flex;
          flex-wrap: wrap;
          justify-content: center;
          gap: 12px;
          margin-top: 24px;
        }
        .lk-countdown {
          font-size: clamp(64px, 13vw, 140px);
          line-height: 0.85;
          letter-spacing: 0;
        }
        .lk-room[data-locked="true"] .lk-shell {
          filter: saturate(0.74) brightness(0.74);
        }
        @keyframes lk-caustic-drift {
          from { transform: translate3d(-1.5%, -1%, 0) rotate(-0.5deg); }
          to { transform: translate3d(1.5%, 1%, 0) rotate(0.5deg); }
        }
        @keyframes lk-blink {
          50% { opacity: 0; }
        }
        @media (max-width: 1120px) {
          .lk-room { overflow: auto; }
          .lk-shell { width: min(100vw - 20px, 900px); height: auto; min-height: 100vh; overflow: visible; }
          .lk-workspace,
          .lk-workspace.history-collapsed { grid-template-columns: 1fr; }
          .lk-presence,
          .lk-stage,
          .lk-memory { min-height: auto; }
          .lk-memory.collapsed { min-height: 80px; }
          .lk-memory.collapsed .lk-history-toggle { writing-mode: horizontal-tb; min-height: 40px; }
        }
        @media (prefers-reduced-motion: reduce) {
          .lk-room::before,
          .lk-caret { animation: none; }
          * { transition-duration: 0.01ms !important; }
        }
      `}</style>

      <div className="lk-shell">
        <header className="lk-topbar">
          <div className="lk-brand">
            <div className="lk-mark" aria-hidden="true" />
            <div>
              <p className="lk-eyebrow">Antigravity Interview</p>
              <h1 className="lk-title">
                {candidate.name} - {candidate.role}
              </h1>
            </div>
          </div>
          <div className="lk-chips">
            <span className="lk-chip">
              <span className="lk-dot" />
              <strong>{floorLabel}</strong>
            </span>
            <span className="lk-chip">{candidate.experience}</span>
            <span className="lk-chip">{started ? "Mic ready" : "Mic gated"}</span>
            <span className="lk-chip">Private session</span>
          </div>
        </header>

        <section className={`lk-workspace ${historyOpen ? "" : "history-collapsed"}`}>
          <aside className="lk-glass lk-presence">
            <div>
              <p className="lk-label">AI interviewer</p>
              <h2 className="lk-state-title">{mural.title}</h2>
            </div>

            <div className="lk-aura-stage">
              <div className="lk-aura-wrap">
                <AgentAudioVisualizerAura
                  size="lg"
                  state={mural.auraState}
                  color={mural.aura}
                  colorShift={colorShift}
                  themeMode="dark"
                />
              </div>
            </div>

            <div className="lk-presence-note">{mural.caption}</div>
            <div className="lk-signal">
              <div className="lk-answer-head">
                <p className="lk-label">Voice signal</p>
                <p className="lk-label">{phase === "listening" ? "Live" : mural.status}</p>
              </div>
              <div className="lk-meter">
                <span />
              </div>
            </div>
          </aside>

          <section className="lk-glass lk-stage">
            <div className="lk-stage-top">
              <div className="lk-stage-top-inner">
                <div className="lk-progress" aria-label={`Turn progress ${progressCurrent} of ${progressTotal}`}>
                  {progressItems.map((item) => (
                    <span key={item} className={item < progressCurrent ? "done" : ""} />
                  ))}
                </div>

                <div className="lk-floor">
                  <div className="lk-corner ai"><span>AI corner</span></div>
                  <div className="lk-floor-pill">Turn</div>
                  <div className="lk-corner candidate"><span>Candidate corner</span></div>
                </div>
                <div className="lk-activity-box">
                  <span className="lk-dot" />
                  <span className="lk-activity-text">{activityText}</span>
                </div>
              </div>
            </div>

            <div className="lk-stage-body">
              {showResumeGate ? (
                <div className="lk-launch">
                  <h2>{isCompletedSession ? "Interview complete" : "Session already has progress"}</h2>
                  <p>
                    {isCompletedSession
                      ? "This interview has already finished. View the report or start a fresh run from the same resume."
                      : `This session already has ${existingTurns} recorded turn${existingTurns === 1 ? "" : "s"}. Resume explicitly or start fresh.`}
                  </p>
                  <div className="lk-actions" style={{ justifyContent: "center", borderTop: 0, paddingBottom: 0 }}>
                    {!isCompletedSession && (
                      <button className="lk-btn primary" onClick={onResume} disabled={bootingMode !== null}>
                        {bootingMode === "resume" ? "Resuming..." : "Resume session"}
                      </button>
                    )}
                    <button className="lk-btn" onClick={onStartFresh} disabled={bootingMode !== null}>
                      {bootingMode === "fresh" ? "Starting fresh..." : "Start fresh run"}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <article
                    ref={questionCardRef}
                    className={[
                      "lk-question-card",
                      `question-${density}`,
                      phase !== "ready" ? "sync-glow" : "",
                      phase === "asking" ? "focus-question" : "",
                    ].join(" ")}
                  >
                    <p className="lk-question-label">Interviewer's question</p>
                    <div ref={questionScrollRef} className="lk-question-scroll" aria-label="Current interview question">
                      <h2
                        ref={questionTextRef}
                        className={`lk-question ${density}`}
                        style={questionFontSize ? { fontSize: `${questionFontSize}px` } : undefined}
                      >
                        <span className="lk-question-ink">{activeQuestion}</span>
                      </h2>
                    </div>
                  </article>

                  <section className={`lk-answer-panel ${liveTranscriptOpen ? "open" : ""}`}>
                    <div className="lk-answer-inner">
                      <div className="lk-answer-head">
                        <p className="lk-label">
                          {liveTranscriptOpen ? "Candidate answer live transcription" : "Current answer"}
                        </p>
                        <button className="lk-btn lk-answer-toggle" onClick={onToggleLiveTranscript}>
                          {liveTranscriptOpen ? "Hide live transcription" : "Show live transcription"}
                        </button>
                      </div>
                      <div ref={answerTextRef} className="lk-answer-text" aria-live="polite">
                        {liveTranscriptOpen ? (
                          <>
                            {liveTranscript || (
                              <span className="lk-answer-placeholder">
                                Latest answer appears here without moving the question.
                              </span>
                            )}
                            {phase === "listening" ? <span className="lk-caret" /> : null}
                          </>
                        ) : (
                          <span className="lk-answer-placeholder">
                            Live transcription is hidden.
                          </span>
                        )}
                      </div>
                    </div>
                  </section>

                  {error ? <div className="lk-error">{error}</div> : null}
                </>
              )}
            </div>

            <div className="lk-actions">
              <button className="lk-btn primary" onClick={started ? onRepeatQuestion : onStart} disabled={bootingMode !== null}>
                {started ? "Repeat question" : "Run session"}
              </button>
              <button className="lk-btn" onClick={onNeedMoment} disabled={!started || complete || pauseUsesRemaining <= 0 || roomLocked}>
                Need a moment{started && pauseUsesRemaining > 0 ? ` (${pauseUsesRemaining})` : ""}
              </button>
              <button className="lk-btn danger" onClick={onEnd} disabled={!started && !complete}>
                End interview
              </button>
            </div>
          </section>

          <aside className={`lk-glass lk-memory ${historyOpen ? "" : "collapsed"} ${fullTranscriptOpen ? "full" : ""}`}>
            <button
              className={`lk-btn lk-history-toggle ${historyOpen ? "" : "collapsed"}`}
              onClick={onToggleHistory}
            >
              {historyOpen ? "Collapse" : "Candidate Corner"}
            </button>

            <section className={`lk-camera ${cameraOn ? "camera-on" : ""} ${cameraVisible ? "" : "hidden-preview"}`}>
              <div className="lk-camera-frame">
                <video ref={videoRef} className="lk-camera-video" autoPlay playsInline muted />
                <div className="lk-avatar">{initials(candidate.name)}</div>
              </div>
              <div className="lk-camera-meta">
                <div className="lk-answer-head">
                  <p className="lk-label">Candidate camera</p>
                  <p className="lk-label">{cameraOn ? "On" : "Mock"}</p>
                </div>
                <button className="lk-btn" onClick={onToggleCameraPreview}>
                  {cameraVisible ? "Hide stream" : "Show stream"}
                </button>
                {cameraError ? <p className="lk-error">{cameraError}</p> : null}
              </div>
            </section>

            <div className="lk-memory-heading">
              <p className="lk-label">Question log</p>
              <p className="lk-note" style={{ lineHeight: 1.45 }}>
                {fullTranscriptOpen
                  ? "Full question and answer transcript, latest first."
                  : "Questions only, latest first. Open full transcript for answers."}
              </p>
            </div>

            <div className="lk-memory-list">
              {displayTurns.length ? (
                displayTurns.map((turn) => (
                  <article className="lk-turn-card" key={`${turn.turnNumber}-${turn.question}`}>
                    <p className="lk-label">
                      {turn.turnNumber === committedTurns.length ? "Latest question" : `Question ${turn.turnNumber}`}
                    </p>
                    <p>
                      {turn.question}
                    </p>
                    <p className="lk-turn-answer">
                      <strong>Answer:</strong> {turn.answer}
                    </p>
                  </article>
                ))
              ) : (
                <div className="lk-empty">
                  <p className="lk-label">Waiting</p>
                  <p>No answer has been committed yet.</p>
                </div>
              )}
            </div>

            <button className="lk-btn" onClick={onToggleFullTranscript}>
              {fullTranscriptOpen ? "Hide full transcript" : "Show full transcript"}
            </button>
          </aside>
        </section>

      </div>

      <section
        className={["lk-freeze", roomLocked ? "open" : ""].join(" ")}
        role="dialog"
        aria-modal="true"
        aria-label={
          confirmEndOpen
            ? "Confirm end interview"
            : paused
              ? "Interview paused"
              : "Interview starting"
        }
      >
        {startCountdown !== null ? (
          <article className="lk-freeze-card lk-glass">
            <div className="lk-freeze-mark lk-countdown">{startCountdown}</div>
            <p className="lk-eyebrow">Starting interview</p>
            <h2>Get ready</h2>
            <p>The room will begin with the interviewer’s first question.</p>
          </article>
        ) : confirmEndOpen ? (
          <article className="lk-freeze-card lk-glass">
            <div className="lk-freeze-mark">!</div>
            <p className="lk-eyebrow">End interview</p>
            <h2>Are you sure?</h2>
            <p>The room is frozen while you confirm. Ending now closes the interview and prepares the report from the conversation captured so far.</p>
            <div className="lk-freeze-actions">
              <button className="lk-btn" onClick={onCancelEnd}>
                Stay in interview
              </button>
              <button className="lk-btn danger" onClick={onConfirmEnd}>
                End interview
              </button>
            </div>
          </article>
        ) : paused ? (
          <article className="lk-freeze-card lk-glass">
            <div className="lk-freeze-mark">II</div>
            <p className="lk-eyebrow">Interview paused</p>
            <h2>Take your time</h2>
            <p>The room is holding your place. You have {pauseUsesRemaining} pause{pauseUsesRemaining === 1 ? "" : "s"} left after this.</p>
            <div className="lk-freeze-actions">
              <button className="lk-btn primary" onClick={onResumeFromPause}>
                Continue interview
              </button>
            </div>
          </article>
        ) : null}
      </section>

      <section className={["lk-closing", complete ? "open" : ""].join(" ")}>
        <article className="lk-closing-card lk-glass">
          <p className="lk-eyebrow">Interview complete</p>
          <h2>Report is being prepared</h2>
          <p>
            The room has captured the conversation. The live assessment is closing and the report will be
            ready after final review.
          </p>
        </article>
      </section>
    </main>
  );
}
