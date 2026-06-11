"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type Phase = "ready" | "asking" | "listening" | "reviewing" | "closing";

const CANDIDATE = {
  name: "S. V. S. Apparao",
  role: "Product Analyst",
  experience: "3 years experience",
};

const TURNS = [
  {
    question: "Make the leader-election answer concrete: where is the stale writer rejected?",
    answer:
      "I would enforce fencing at the storage write boundary, because clients and middle-tier services can be stale during recovery.",
    said: "storage write boundary",
    testing: "stale writer rejection",
  },
  {
    question:
      "Good. Now defend that choice when the old leader has lower latency to one replica than the new leader.",
    answer:
      "The lower latency does not matter if the write path checks a monotonic fencing token before accepting mutation.",
    said: "monotonic fencing token",
    testing: "delayed replica behavior",
  },
  {
    question:
      "Take that into a product analytics pipeline. Where would the same stale-write failure appear?",
    answer:
      "It appears when late events overwrite newer attribution state, so I would version aggregate writes and reject stale updates.",
    said: "late events and attribution state",
    testing: "application transfer",
  },
  {
    question:
      "If the dashboard shows a conversion drop, how would you separate a real product issue from bad event instrumentation?",
    answer:
      "I would compare raw event volume, schema changes, funnel step counts, and a holdout metric before calling it a product regression.",
    said: "conversion drop versus instrumentation",
    testing: "metric integrity",
  },
  {
    question:
      "You said holdout metric. Which one would you trust if the checkout event itself might be corrupted?",
    answer:
      "I would trust an upstream intent signal like payment-page reach plus backend order creation, then reconcile it against client-side checkout events.",
    said: "upstream intent and backend order creation",
    testing: "independent validation",
  },
  {
    question:
      "Now make it candidate-facing: how would you explain that uncertainty to a product manager without sounding vague?",
    answer:
      "I would say the drop is not decision-ready yet, show the two conflicting signals, and give a time-boxed validation plan.",
    said: "decision-ready uncertainty",
    testing: "stakeholder communication",
  },
  {
    question:
      "Suppose the PM wants to ship anyway. What evidence would make you push back?",
    answer:
      "I would push back if the affected segment is large, the instrumentation confidence is low, or backend revenue does not confirm the lift.",
    said: "ship decision evidence",
    testing: "decision boundary",
  },
  {
    question:
      "Take the same reasoning into retention. What would break if you used a simple seven-day return rate?",
    answer:
      "A simple return rate hides cohort mix, acquisition channel changes, seasonality, and whether the returning users performed the valuable action.",
    said: "retention cohort mix",
    testing: "metric definition",
  },
  {
    question:
      "What is the first probe you would run if one cohort improves but total retention gets worse?",
    answer:
      "I would check Simpson's paradox by splitting acquisition mix and cohort sizes, then compare weighted retention before and after the change.",
    said: "Simpson's paradox",
    testing: "segmentation reasoning",
  },
  {
    question:
      "Close the loop. What would you write in the final recommendation after this investigation?",
    answer:
      "I would recommend delaying the launch until instrumentation is reconciled, then ship only if backend revenue and cohort retention both support it.",
    said: "final recommendation",
    testing: "synthesis",
  },
];

const PHASE_MURAL: Record<
  Phase,
  {
    aura: `#${string}`;
    shift: number;
    a: string;
    b: string;
    c: string;
    auraState: AgentState;
    label: string;
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
    label: "Ready",
    title: "Ready when you are",
    caption: "The room is quiet. Start when you are ready.",
  },
  asking: {
    aura: "#FF4D6D",
    shift: 0.58,
    a: "oklch(0.66 0.22 18)",
    b: "oklch(0.7 0.18 342)",
    c: "oklch(0.68 0.13 286)",
    auraState: "speaking",
    label: "Question",
    title: "Asking",
    caption: "The interviewer owns the floor. Listen to the question.",
  },
  listening: {
    aura: "#1FD5F9",
    shift: 0.3,
    a: "oklch(0.72 0.19 222)",
    b: "oklch(0.66 0.13 278)",
    c: "oklch(0.76 0.14 154)",
    auraState: "listening",
    label: "Your turn",
    title: "Listening",
    caption: "The question remains anchored while your answer flows below it.",
  },
  reviewing: {
    aura: "#FFBE59",
    shift: 0.46,
    a: "oklch(0.78 0.14 72)",
    b: "oklch(0.68 0.14 34)",
    c: "oklch(0.72 0.12 292)",
    auraState: "thinking",
    label: "Reviewing",
    title: "Reviewing answer",
    caption: "Answer received. The next question is being prepared.",
  },
  closing: {
    aura: "#6CFF9E",
    shift: 0.26,
    a: "oklch(0.76 0.15 154)",
    b: "oklch(0.68 0.13 204)",
    c: "oklch(0.78 0.1 92)",
    auraState: "thinking",
    label: "Complete",
    title: "Closing",
    caption: "The interview is closing and the report is being prepared.",
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function LiveKitRoomPreviewPage() {
  const [phase, setPhase] = useState<Phase>("ready");
  const [turnIndex, setTurnIndex] = useState(0);
  const [liveAnswer, setLiveAnswer] = useState("");
  const [committed, setCommitted] = useState<typeof TURNS>([]);
  const [liveTranscriptOpen, setLiveTranscriptOpen] = useState(false);
  const [fullTranscriptOpen, setFullTranscriptOpen] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [energy, setEnergy] = useState(0.16);
  const [showClosing, setShowClosing] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const timerRef = useRef<number | null>(null);
  const typingRef = useRef<number | null>(null);
  const energyRef = useRef<number | null>(null);

  const mural = PHASE_MURAL[phase];
  const activeTurn = TURNS[Math.min(turnIndex, TURNS.length - 1)];
  const colorShift = clamp(mural.shift + energy * 0.1, 0.08, 0.68);
  const floorOwner = phase === "listening" ? "candidate" : phase === "ready" ? "ready" : "ai";
  const floorLabel =
    floorOwner === "candidate"
      ? "Candidate turn"
      : floorOwner === "ai"
        ? "Interviewer turn"
        : "Room ready";
  const displayedQuestion =
    phase === "ready"
      ? "When you are ready, start the live interview room."
      : phase === "closing"
        ? "That gives me enough signal. I am closing the interview and preparing your report."
        : activeTurn.question;
  const questionDensity =
    displayedQuestion.length > 110
      ? "dense"
      : displayedQuestion.length > 84
        ? "compact"
        : displayedQuestion.length > 64
          ? "medium"
          : "short";

  const recentTurns = useMemo(() => committed.slice(-4).reverse(), [committed]);
  const turnHistory = useMemo(
    () =>
      (fullTranscriptOpen ? [...committed].reverse() : recentTurns).map((turn, index, source) => ({
        turn,
        turnNumber: TURNS.findIndex((item) => item.question === turn.question) + 1 || source.length - index,
      })),
    [committed, fullTranscriptOpen, recentTurns],
  );

  useEffect(() => {
    return () => {
      clearTimers();
    };
  }, []);

  function clearTimers() {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    if (typingRef.current) window.clearInterval(typingRef.current);
    if (energyRef.current) window.clearInterval(energyRef.current);
    timerRef.current = null;
    typingRef.current = null;
    energyRef.current = null;
  }

  function startEnergy() {
    if (energyRef.current) window.clearInterval(energyRef.current);
    let tick = 0;
    energyRef.current = window.setInterval(() => {
      tick += 0.18;
      const next = 0.2 + Math.abs(Math.sin(tick)) * 0.42 + Math.abs(Math.sin(tick * 0.43)) * 0.08;
      setEnergy(clamp(next, 0.12, 0.82));
    }, 80);
  }

  function stopEnergy(next = 0.18) {
    if (energyRef.current) window.clearInterval(energyRef.current);
    energyRef.current = null;
    setEnergy(next);
  }

  function transitionPhase(nextPhase: Phase) {
    setPhase(nextPhase);
  }

  function ask(index = turnIndex) {
    clearTimers();
    setShowClosing(false);
    transitionPhase("asking");
    stopEnergy(0.34);
    setTurnIndex(Math.min(index, TURNS.length - 1));
    setLiveAnswer("");
    setLiveTranscriptOpen(false);
  }

  function listen(index = turnIndex, onDone?: () => void) {
    clearTimers();
    transitionPhase("listening");
    setTurnIndex(Math.min(index, TURNS.length - 1));
    setLiveAnswer("");
    setLiveTranscriptOpen(true);
    startEnergy();

    const words = TURNS[Math.min(index, TURNS.length - 1)].answer.split(" ");
    let cursor = 0;
    typingRef.current = window.setInterval(() => {
      cursor += 1;
      setLiveAnswer(words.slice(0, cursor).join(" "));
      if (cursor >= words.length) {
        if (typingRef.current) window.clearInterval(typingRef.current);
        typingRef.current = null;
        timerRef.current = window.setTimeout(() => onDone?.(), 650);
      }
    }, 105);
  }

  function review(index = turnIndex) {
    clearTimers();
    const safeIndex = Math.min(index, TURNS.length - 1);
    setCommitted((previous) => {
      const nextCommitted = [...previous];
      nextCommitted[safeIndex] = TURNS[safeIndex];
      return nextCommitted.filter(Boolean);
    });
    setTurnIndex(safeIndex);
    transitionPhase("reviewing");
    stopEnergy(0.28);
    setLiveTranscriptOpen(false);
  }

  function runSession() {
    clearTimers();
    setIsRunning(true);
    setCommitted([]);
    setTurnIndex(0);
    setLiveAnswer("");
    setLiveTranscriptOpen(false);
    setFullTranscriptOpen(false);
    setShowClosing(false);

    const runTurn = (index: number) => {
      if (index >= TURNS.length) {
        closeRoom();
        return;
      }
      ask(index);
      timerRef.current = window.setTimeout(() => {
        listen(index, () => {
          review(index);
          timerRef.current = window.setTimeout(() => runTurn(index + 1), 1600);
        });
      }, 1500);
    };

    runTurn(0);
  }

  function bargeIn() {
    clearTimers();
    setIsRunning(false);
    setLiveTranscriptOpen(true);
    listen(turnIndex, () => review(turnIndex));
  }

  function needMoment() {
    clearTimers();
    setIsRunning(false);
    transitionPhase("listening");
    stopEnergy(0.12);
    setLiveTranscriptOpen(true);
    setLiveAnswer("Take a moment. The room will hold the question here.");
  }

  function fixLastTerm() {
    if (!committed.length) {
      setLiveTranscriptOpen(true);
      setLiveAnswer("Correction appears after an answer is committed.");
      return;
    }
    const next = [...committed];
    const last = next[next.length - 1];
    next[next.length - 1] = {
      ...last,
      answer: last.answer.replace("storage write boundary", "storage write boundary (corrected term)"),
    };
    setCommitted(next);
    setLiveTranscriptOpen(true);
    setLiveAnswer(next[next.length - 1].answer);
  }

  function closeRoom() {
    clearTimers();
    setIsRunning(false);
    transitionPhase("closing");
    stopEnergy(0.2);
    setLiveTranscriptOpen(false);
    timerRef.current = window.setTimeout(() => setShowClosing(true), 700);
  }

  function resetPreview() {
    clearTimers();
    setIsRunning(false);
    transitionPhase("ready");
    setTurnIndex(0);
    setLiveAnswer("");
    setCommitted([]);
    setLiveTranscriptOpen(false);
    setFullTranscriptOpen(false);
    setHistoryOpen(true);
    setShowClosing(false);
    stopEnergy(0.16);
  }

  return (
    <main
      className="lk-room"
      data-phase={phase}
      data-floor={floorOwner}
      style={
        {
          "--energy": energy.toFixed(3),
          "--center-glow": `${0.13 + energy * 0.08}`,
          "--edge-glow": `${0.14 + energy * 0.07}`,
          "--caustic-opacity": `${0.05 + energy * 0.035}`,
          "--border-glow": `${22 + energy * 36}px`,
          "--mural-a": mural.a,
          "--mural-b": mural.b,
          "--mural-c": mural.c,
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
          z-index: 3;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          gap: 14px;
          width: min(1480px, calc(100vw - 32px));
          height: 100vh;
          margin: 0 auto;
          padding: 18px 0;
        }
        .lk-glass {
          position: relative;
          overflow: hidden;
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
        .lk-glass::before {
          content: "";
          position: absolute;
          inset: -2px;
          z-index: 0;
          pointer-events: none;
          border-radius: inherit;
          opacity: 0.52;
          background:
            radial-gradient(44rem 18rem at 50% -8%, color-mix(in oklch, var(--mural-a) 10%, transparent), transparent 70%),
            radial-gradient(28rem 18rem at -4% 54%, color-mix(in oklch, var(--mural-c) 5%, transparent), transparent 74%),
            radial-gradient(28rem 18rem at 104% 54%, color-mix(in oklch, var(--mural-a) 5%, transparent), transparent 74%);
        }
        .lk-glass > * {
          position: relative;
          z-index: 1;
        }
        .lk-topbar {
          display: flex;
          min-height: 72px;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          border-radius: 26px;
          padding: 15px 18px;
        }
        .lk-brand {
          display: flex;
          min-width: 0;
          align-items: center;
          gap: 14px;
        }
        .lk-mark {
          display: grid;
          height: 40px;
          width: 40px;
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
        .lk-eyebrow {
          margin: 0;
          color: color-mix(in oklch, var(--mural-a) 62%, white 10%);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.24em;
          text-transform: uppercase;
        }
        .lk-title {
          margin: 4px 0 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 21px;
          font-weight: 680;
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
          min-height: 34px;
          align-items: center;
          gap: 8px;
          border: 1px solid rgba(255,255,255,0.09);
          border-radius: 999px;
          padding: 7px 11px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.68);
          font-size: 12px;
        }
        .lk-dot {
          height: 8px;
          width: 8px;
          border-radius: 999px;
          background: color-mix(in oklch, var(--mural-a) 80%, white 8%);
          box-shadow: 0 0 18px color-mix(in oklch, var(--mural-a) 70%, transparent);
        }
        .lk-workspace {
          display: grid;
          min-height: 0;
          grid-template-columns: minmax(250px, 310px) minmax(0, 1fr) minmax(260px, 320px);
          align-items: stretch;
          gap: 14px;
          transition: grid-template-columns 260ms ease;
        }
        .lk-workspace.history-collapsed {
          grid-template-columns: minmax(250px, 310px) minmax(0, 1fr) 58px;
        }
        .lk-presence,
        .lk-stage,
        .lk-memory {
          min-height: 0;
          border-radius: 30px;
        }
        .lk-presence {
          display: grid;
          grid-template-rows: auto 1fr auto;
          gap: 14px;
          padding: 18px;
          transition: border-color 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
        }
        .lk-room[data-floor="candidate"] .lk-presence {
          opacity: 0.78;
        }
        .lk-room[data-floor="ai"] .lk-presence {
          border-color: color-mix(in oklch, var(--mural-a) 20%, rgba(255,255,255,0.08));
          box-shadow: 0 0 28px color-mix(in oklch, var(--mural-a) 8%, transparent);
        }
        .lk-label {
          margin: 0;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.22em;
          text-transform: uppercase;
        }
        .lk-state-title {
          margin: 7px 0 0;
          font-size: 24px;
          font-weight: 720;
          letter-spacing: 0;
        }
        .lk-aura-wrap {
          position: relative;
          display: grid;
          min-height: 322px;
          place-items: center;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 26px;
          background: rgba(0,0,0,0.28);
        }
        .lk-aura-wrap::before {
          content: none;
        }
        .lk-aura-caption {
          position: absolute;
          right: 14px;
          bottom: 14px;
          left: 14px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 18px;
          padding: 12px;
          background: rgba(0,0,0,0.36);
          color: rgba(255,255,255,0.66);
          font-size: 13px;
          line-height: 1.45;
        }
        .lk-meter {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          padding: 14px;
          background: rgba(255,255,255,0.04);
        }
        .lk-meter-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          color: rgba(255,255,255,0.44);
          font-size: 10px;
          font-weight: 820;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .lk-meter-bar {
          height: 8px;
          margin-top: 13px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
        }
        .lk-meter-fill {
          height: 100%;
          width: calc(var(--energy) * 100%);
          border-radius: inherit;
          background: linear-gradient(90deg, var(--mural-a), var(--mural-c), var(--mural-b));
          transition: width 180ms ease;
        }
        .lk-stage {
          position: relative;
          display: grid;
          grid-template-rows: auto auto auto;
          align-content: start;
          align-self: start;
          overflow: hidden;
          box-shadow:
            0 0 calc(28px + var(--energy) * 18px) color-mix(in oklch, var(--mural-a) 12%, transparent),
            inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 10%, transparent);
        }
        .lk-room:not([data-phase="ready"]) .lk-stage {
          animation: lk-stage-edge-sync 2.7s ease-in-out infinite;
        }
        .lk-stage::before {
          content: "";
          position: absolute;
          inset: -20px;
          z-index: 0;
          pointer-events: none;
          opacity: calc(0.18 + var(--energy) * 0.08);
          background:
            radial-gradient(56rem 18rem at 50% 0%, color-mix(in oklch, var(--mural-a) 18%, transparent), transparent 68%),
            radial-gradient(50rem 18rem at 50% 100%, color-mix(in oklch, var(--mural-c) 13%, transparent), transparent 72%),
            radial-gradient(16rem 40rem at 0% 48%, color-mix(in oklch, var(--mural-a) 12%, transparent), transparent 70%),
            radial-gradient(16rem 40rem at 100% 48%, color-mix(in oklch, var(--mural-c) 10%, transparent), transparent 70%);
          filter: blur(18px);
        }
        .lk-stage::after {
          content: "";
          position: absolute;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          border-radius: inherit;
          box-shadow:
            inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 16%, transparent),
            inset 0 0 44px color-mix(in oklch, var(--mural-a) 6%, transparent),
            0 0 34px color-mix(in oklch, var(--mural-a) 8%, transparent);
        }
        .lk-stage > * {
          position: relative;
          z-index: 1;
        }
        .lk-stage-top {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.09);
          padding: 20px 24px;
        }
        .lk-stage-status {
          margin: 8px 0 0;
          color: rgba(255,255,255,0.56);
          font-size: 14px;
          line-height: 1.5;
        }
        .lk-floorline {
          grid-column: 1 / -1;
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          align-items: center;
          gap: 10px;
          width: min(520px, 100%);
          margin-top: 13px;
        }
        .lk-floor-track {
          height: 2px;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
          overflow: hidden;
        }
        .lk-floor-track::before {
          content: "";
          display: block;
          height: 100%;
          width: 100%;
          border-radius: inherit;
          background: color-mix(in oklch, var(--mural-a) 72%, white 8%);
          transform: scaleX(0);
          transition: transform 220ms ease;
        }
        .lk-floor-track.ai::before {
          transform-origin: right;
        }
        .lk-floor-track.candidate::before {
          transform-origin: left;
        }
        .lk-room[data-floor="ai"] .lk-floor-track.ai::before,
        .lk-room[data-floor="candidate"] .lk-floor-track.candidate::before {
          transform: scaleX(1);
        }
        .lk-floor-pill {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 30px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 6px 11px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.64);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          white-space: nowrap;
        }
        .lk-room[data-floor="ai"] .lk-floor-pill,
        .lk-room[data-floor="candidate"] .lk-floor-pill {
          border-color: color-mix(in oklch, var(--mural-a) 28%, rgba(255,255,255,0.1));
          color: rgba(255,255,255,0.82);
        }
        .lk-progress {
          display: flex;
          flex-shrink: 0;
          align-items: center;
          gap: 6px;
        }
        .lk-progress span {
          height: 4px;
          width: 28px;
          border-radius: 999px;
          background: rgba(255,255,255,0.11);
        }
        .lk-progress span.done {
          background: color-mix(in oklch, var(--mural-a) 72%, white 8%);
          box-shadow: 0 0 18px color-mix(in oklch, var(--mural-a) 28%, transparent);
        }
        .lk-room[data-phase="asking"] .lk-memory,
        .lk-room[data-phase="asking"] .lk-answer-panel {
          opacity: 0.72;
        }
        .lk-stage-body {
          display: grid;
          grid-template-rows: auto auto auto;
          align-content: start;
          gap: 12px;
          min-height: 0;
          overflow: hidden;
          padding: clamp(14px, 2.2vw, 24px) clamp(20px, 3vw, 34px) 16px;
        }
        .lk-question-card {
          position: relative;
          display: flex;
          min-height: 0;
          align-items: center;
          overflow: hidden;
          border: 1px solid color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.08));
          border-radius: 28px;
          padding: clamp(18px, 2.25vw, 26px) clamp(22px, 3vw, 34px);
          background: #020304;
          box-shadow:
            inset 0 0 0 1px rgba(255,255,255,0.03),
            inset 0 0 38px rgba(255,255,255,0.025);
          backdrop-filter: none;
        }
        .lk-question-card.question-medium {
          min-height: 0;
        }
        .lk-question-card.question-compact {
          min-height: 0;
        }
        .lk-question-card.question-dense {
          min-height: 0;
        }
        .lk-question-card.focus-question {
          animation: lk-question-focus 960ms ease-out both;
          border-color: color-mix(in oklch, var(--mural-a) 42%, rgba(255,255,255,0.18));
        }
        .lk-question-card.sync-glow {
          border-color: color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.1));
        }
        .lk-question-card.focus-question.sync-glow {
          animation: lk-question-focus 760ms ease-out both;
        }
        .lk-question-card.focus-question .lk-question {
          animation: lk-question-settle 700ms cubic-bezier(.2,.8,.2,1) both;
        }
        .lk-question-card::before {
          content: none;
        }
        .lk-question-card::after {
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          border-radius: inherit;
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.08),
            inset 0 -1px 0 rgba(255,255,255,0.04);
        }
        .lk-question {
          position: relative;
          z-index: 1;
          max-width: 980px;
          margin: 0;
          font-size: clamp(30px, 3.35vw, 52px);
          font-weight: 750;
          letter-spacing: 0;
          line-height: 1.08;
        }
        .lk-question-ink {
          padding: 0;
          background: transparent;
          box-shadow: none;
          text-shadow: 0 2px 18px rgba(0,0,0,0.64);
        }
        .lk-workspace.history-collapsed .lk-question {
          max-width: 1140px;
          font-size: clamp(35px, 4.05vw, 62px);
        }
        .lk-workspace.history-collapsed .lk-question.medium {
          font-size: clamp(33px, 3.75vw, 58px);
        }
        .lk-workspace.history-collapsed .lk-question.compact {
          font-size: clamp(29px, 3.25vw, 50px);
        }
        .lk-workspace.history-collapsed .lk-question.dense {
          font-size: clamp(25px, 2.75vw, 42px);
        }
        .lk-question.medium {
          font-size: clamp(28px, 3vw, 46px);
        }
        .lk-question.compact {
          font-size: clamp(24px, 2.55vw, 39px);
          line-height: 1.1;
        }
        .lk-question.dense {
          font-size: clamp(21px, 2.2vw, 34px);
          line-height: 1.12;
        }
        .lk-answer-panel {
          overflow: hidden;
          max-height: 72px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          background:
            linear-gradient(180deg, rgba(255,255,255,0.04), transparent 64%),
            rgba(0,0,0,0.2);
          opacity: 1;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
          transition: max-height 280ms ease, border-color 180ms ease, background 180ms ease;
        }
        .lk-room[data-floor="candidate"] .lk-answer-panel {
          border-color: color-mix(in oklch, var(--mural-a) 34%, rgba(255,255,255,0.08));
          background:
            linear-gradient(180deg, color-mix(in oklch, var(--mural-a) 5%, transparent), transparent 68%),
            rgba(0,0,0,0.24);
          box-shadow:
            0 0 24px color-mix(in oklch, var(--mural-a) 10%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .lk-answer-panel.open {
          max-height: 158px;
          border-color: color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.08));
        }
        .lk-answer-inner {
          padding: 12px 16px;
        }
        .lk-answer-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
        }
        .lk-answer-toggle {
          flex-shrink: 0;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 6px 10px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.62);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          cursor: pointer;
        }
        .lk-answer-text {
          display: -webkit-box;
          max-height: 7.1em;
          margin: 9px 0 0;
          overflow: hidden;
          color: rgba(255,255,255,0.72);
          font-size: clamp(14px, 1.25vw, 17px);
          line-height: 1.42;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 1;
        }
        .lk-answer-panel.open .lk-answer-text {
          overflow: auto;
          -webkit-line-clamp: 5;
        }
        .lk-answer-text.live {
          color: rgba(255,255,255,0.6);
        }
        .lk-caret {
          display: inline-block;
          height: 1em;
          width: 0.42em;
          margin-left: 3px;
          transform: translateY(0.16em);
          border-radius: 2px;
          background: color-mix(in oklch, var(--mural-a) 82%, white 8%);
          animation: lk-blink 850ms step-end infinite;
        }
        .lk-review {
          display: none;
          border: 1px solid color-mix(in oklch, var(--mural-b) 18%, transparent);
          border-radius: 24px;
          padding: 18px 20px;
          background: rgba(255,255,255,0.04);
          color: rgba(255,255,255,0.72);
          font-size: 18px;
          line-height: 1.55;
        }
        .lk-review.open {
          display: block;
        }
        .lk-actions,
        .lk-dock {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          border-top: 1px solid rgba(255,255,255,0.09);
          padding: 16px 20px;
        }
        .lk-btn {
          min-height: 42px;
          border: 1px solid rgba(255,255,255,0.11);
          border-radius: 15px;
          padding: 10px 14px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.78);
          cursor: pointer;
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
          border-color: rgba(255,95,127,0.26);
          color: rgba(255,180,190,0.9);
        }
        .lk-memory {
          position: relative;
          display: flex;
          flex-direction: column;
          min-height: clamp(420px, calc(100vh - 220px), 640px);
          overflow: hidden;
          padding: 18px;
          transition: padding 220ms ease;
        }
        .lk-memory.collapsed {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 10px;
        }
        .lk-memory.collapsed .lk-memory-content {
          display: none;
        }
        .lk-memory-content {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          gap: 12px;
          flex: 1;
          height: 100%;
          min-height: 0;
        }
        .lk-history-toggle {
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.66);
          cursor: pointer;
        }
        .lk-history-toggle.expanded {
          min-height: 34px;
          padding: 7px 11px;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .lk-history-toggle.collapsed {
          display: grid;
          width: 38px;
          height: 78%;
          min-height: 220px;
          place-items: center;
          padding: 10px 0;
          writing-mode: vertical-rl;
          text-orientation: mixed;
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .lk-memory-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          min-height: 0;
          overflow: auto;
          padding-right: 3px;
          scrollbar-gutter: stable;
        }
        .lk-memory-list.full {
          padding-bottom: 4px;
        }
        .lk-memory .lk-btn {
          width: 100%;
          justify-content: center;
          text-align: center;
        }
        .lk-turn-card {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 14px;
          background: rgba(255,255,255,0.04);
        }
        .lk-memory-list.full .lk-turn-card {
          padding: 12px;
        }
        .lk-memory-list:not(.full) .lk-turn-card {
          padding: 10px 12px;
        }
        .lk-memory-list:not(.full) .lk-turn-card:not(.current) {
          opacity: 0.74;
        }
        .lk-memory-list:not(.full) .lk-turn-card p {
          display: -webkit-box;
          overflow: hidden;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
        }
        .lk-memory-list:not(.full) .lk-turn-card.current p {
          -webkit-line-clamp: 4;
        }
        .lk-turn-card.current {
          border-color: color-mix(in oklch, var(--mural-a) 26%, transparent);
          background: color-mix(in oklch, var(--mural-a) 7%, rgba(255,255,255,0.035));
        }
        .lk-turn-card small {
          display: block;
          margin-bottom: 7px;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .lk-turn-card p {
          margin: 0;
          color: rgba(255,255,255,0.66);
          font-size: 13px;
          line-height: 1.5;
        }
        .lk-dock {
          align-items: center;
          justify-content: space-between;
          min-height: 70px;
          border-radius: 26px;
          border-top: 1px solid rgba(255,255,255,0.1);
        }
        .lk-dock-group {
          display: flex;
          flex-wrap: wrap;
          gap: 9px;
        }
        .lk-note {
          color: rgba(255,255,255,0.48);
          font-size: 13px;
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
        @keyframes lk-caustic-drift {
          from { transform: translate3d(-1.4%, 1%, 0) rotate(-0.4deg) scale(1); }
          to { transform: translate3d(1.4%, -1%, 0) rotate(0.45deg) scale(1.025); }
        }
        @keyframes lk-fluid {
          from { transform: translate3d(-2%, 1%, 0) rotate(-1deg) scale(1); }
          to { transform: translate3d(2%, -1%, 0) rotate(1deg) scale(1.04); }
        }
        @keyframes lk-stage-edge-sync {
          0%, 100% {
            box-shadow:
              0 0 calc(26px + var(--energy) * 18px) color-mix(in oklch, var(--mural-a) 12%, transparent),
              0 0 calc(12px + var(--energy) * 12px) color-mix(in oklch, var(--mural-c) 8%, transparent),
              inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 10%, transparent),
              inset 0 0 42px color-mix(in oklch, var(--mural-a) 5%, transparent);
          }
          48% {
            box-shadow:
              0 0 calc(52px + var(--energy) * 28px) color-mix(in oklch, var(--mural-a) 24%, transparent),
              0 0 calc(22px + var(--energy) * 16px) color-mix(in oklch, var(--mural-c) 14%, transparent),
              inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 20%, transparent),
              inset 0 0 58px color-mix(in oklch, var(--mural-a) 8%, transparent);
          }
        }
        @keyframes lk-question-focus {
          0% {
            box-shadow:
              inset 0 0 0 1px rgba(255,255,255,0.03),
              inset 0 0 38px rgba(255,255,255,0.025);
          }
          42% {
            box-shadow:
              inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.04)),
              inset 0 0 42px rgba(255,255,255,0.035);
          }
          100% {
            box-shadow:
              inset 0 0 0 1px rgba(255,255,255,0.03),
              inset 0 0 38px rgba(255,255,255,0.025);
          }
        }
        @keyframes lk-question-settle {
          0% { opacity: 0.72; transform: translateY(6px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes lk-blink {
          50% { opacity: 0; }
        }
        @media (max-width: 1120px) {
          .lk-room { overflow: auto; }
          .lk-shell { height: auto; min-height: 100vh; }
          .lk-workspace,
          .lk-workspace.history-collapsed { grid-template-columns: 1fr; }
          .lk-presence { grid-template-columns: minmax(220px, 320px) 1fr; grid-template-rows: auto auto; align-items: stretch; }
          .lk-presence > header { grid-column: 1 / -1; }
          .lk-aura-wrap { min-height: 260px; }
          .lk-memory { max-height: 360px; }
          .lk-memory.collapsed { max-height: 86px; min-height: 70px; display: flex; padding: 12px; }
          .lk-history-toggle.collapsed {
            width: auto;
            height: auto;
            min-height: 34px;
            padding: 7px 11px;
            writing-mode: horizontal-tb;
          }
        }
        @media (max-width: 720px) {
          .lk-shell { width: min(100% - 18px, 1480px); padding: 9px 0; }
          .lk-topbar, .lk-dock { align-items: flex-start; flex-direction: column; }
          .lk-presence { display: block; }
          .lk-aura-wrap { margin-top: 14px; }
          .lk-stage-top { flex-direction: column; }
          .lk-stage-body { padding: 20px; }
          .lk-question,
          .lk-question.medium,
          .lk-question.compact,
          .lk-question.dense { font-size: clamp(23px, 8vw, 30px); }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 1ms !important;
            transition-duration: 1ms !important;
          }
        }
      `}</style>

      <div className="lk-shell">
        <header className="lk-topbar lk-glass">
          <div className="lk-brand">
            <div className="lk-mark" aria-hidden="true" />
            <div>
              <p className="lk-eyebrow">Antigravity Interview</p>
              <h1 className="lk-title">
                {CANDIDATE.name} - {CANDIDATE.role}
              </h1>
            </div>
          </div>
          <div className="lk-chips">
            <span className="lk-chip floor-chip">
              <span className="lk-dot" />
              <strong>{floorLabel}</strong>
            </span>
            <span className="lk-chip">{CANDIDATE.experience}</span>
            <span className="lk-chip">Mic ready</span>
            <span className="lk-chip">Private session</span>
          </div>
        </header>

        <section className={["lk-workspace", historyOpen ? "" : "history-collapsed"].join(" ")}>
          <aside className="lk-presence lk-glass">
            <header>
              <p className="lk-label">Interviewer presence</p>
              <h2 className="lk-state-title">{mural.title}</h2>
            </header>

            <div className="lk-aura-wrap">
              <AgentAudioVisualizerAura
                size="lg"
                state={mural.auraState}
                color={mural.aura}
                colorShift={colorShift}
                themeMode="dark"
                className="relative z-10"
              />
              <p className="lk-aura-caption">{mural.caption}</p>
            </div>

            <div className="lk-meter">
              <div className="lk-meter-row">
                <span>Voice signal</span>
                <span>{phase === "listening" ? "live" : mural.label}</span>
              </div>
              <div className="lk-meter-bar">
                <div className="lk-meter-fill" />
              </div>
            </div>
          </aside>

          <section className="lk-stage lk-glass">
            <div className="lk-stage-top">
              <div>
                <p className="lk-label">Current turn</p>
                <p className="lk-stage-status">
                  Turn {Math.min(turnIndex + 1, TURNS.length)} of {TURNS.length}. The question stays anchored while the answer moves below it.
                </p>
                <div className="lk-floorline" aria-label={`Floor owner: ${floorLabel}`}>
                  <span className="lk-floor-track ai" />
                  <span className="lk-floor-pill">{floorLabel}</span>
                  <span className="lk-floor-track candidate" />
                </div>
              </div>
              <div className="lk-progress" aria-label="Interview progress">
                {TURNS.map((_, item) => (
                  <span key={item} className={item <= turnIndex ? "done" : ""} />
                ))}
              </div>
            </div>

            <div className="lk-stage-body">
              <article
                key={`${turnIndex}-${displayedQuestion}`}
                className={[
                  "lk-question-card",
                  `question-${questionDensity}`,
                  phase !== "ready" ? "sync-glow" : "",
                  phase === "asking" ? "focus-question" : "",
                ].join(" ")}
              >
                <h2 className={["lk-question", questionDensity].join(" ")}>
                  <span className="lk-question-ink">{displayedQuestion}</span>
                </h2>
              </article>

              <article className={["lk-answer-panel", liveTranscriptOpen ? "open" : ""].join(" ")}>
                <div className="lk-answer-inner">
                  <div className="lk-answer-header">
                    <p className="lk-label">
                      {phase === "listening" ? "Live transcription" : phase === "reviewing" ? "Latest answer" : "Current answer"}
                    </p>
                    <button
                      className="lk-answer-toggle"
                      type="button"
                      onClick={() => setLiveTranscriptOpen((open) => !open)}
                    >
                      {liveTranscriptOpen ? "Hide live transcription" : "Show live transcription"}
                    </button>
                  </div>
                  <p className={["lk-answer-text", phase === "listening" ? "live" : ""].join(" ")}>
                    {liveAnswer || "Latest answer appears here without moving the question."}
                    {phase === "listening" && liveAnswer && <span className="lk-caret" />}
                  </p>
                </div>
              </article>

              <article className={["lk-review", phase === "reviewing" || phase === "closing" ? "open" : ""].join(" ")}>
                {phase === "closing"
                  ? "The room is settling. The candidate leaves with a clear report-preparation state."
                  : "Answer received. Preparing the next question from what was just said."}
              </article>
            </div>

            <div className="lk-actions">
              <button className="lk-btn primary" type="button" onClick={runSession}>
                {isRunning ? "Running" : "Run session"}
              </button>
              <button className="lk-btn" type="button" onClick={() => ask(turnIndex)}>
                Ask
              </button>
              <button className="lk-btn" type="button" onClick={() => listen(turnIndex, () => review(turnIndex))}>
                Candidate answer
              </button>
              <button className="lk-btn" type="button" onClick={() => review(turnIndex)}>
                Review
              </button>
              <button className="lk-btn" type="button" onClick={bargeIn}>
                Barge-in
              </button>
              <button className="lk-btn danger" type="button" onClick={closeRoom}>
                Close
              </button>
            </div>
          </section>

          <aside className={["lk-memory lk-glass", historyOpen ? "" : "collapsed"].join(" ")}>
            {!historyOpen && (
              <button className="lk-history-toggle collapsed" type="button" onClick={() => setHistoryOpen(true)}>
                Turn history
              </button>
            )}
            <div className="lk-memory-content">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="lk-label">Turn history</p>
                  <p className="lk-stage-status">
                    Committed turns. Open full transcript for the whole interview.
                  </p>
                </div>
                <button className="lk-history-toggle expanded" type="button" onClick={() => setHistoryOpen(false)}>
                  Collapse
                </button>
              </div>
              <div className={["lk-memory-list", fullTranscriptOpen ? "full" : ""].join(" ")}>
                {turnHistory.length === 0 ? (
                  <article className="lk-turn-card current">
                    <small>Waiting</small>
                    <p>No answer has been committed yet.</p>
                  </article>
                ) : (
                  turnHistory.map(({ turn, turnNumber }, index) => (
                    <article key={`${turn.question}-${index}`} className={["lk-turn-card", index === 0 ? "current" : ""].join(" ")}>
                      <small>
                        {fullTranscriptOpen
                          ? `Turn ${turnNumber}`
                          : index === 0
                            ? "Latest turn"
                            : "Prior turn"}
                      </small>
                      <p>
                        <strong className="text-white">Q:</strong> {turn.question}
                      </p>
                      <p className="mt-2">
                        <strong className="text-white">A:</strong> {turn.answer}
                      </p>
                    </article>
                  ))
                )}
              </div>
              <button className="lk-btn" type="button" onClick={() => setFullTranscriptOpen((open) => !open)}>
                {fullTranscriptOpen ? "Hide full transcript" : "Show full transcript"}
              </button>
            </div>
          </aside>
        </section>

        <footer className="lk-dock lk-glass">
          <div className="lk-dock-group">
            <button className="lk-btn" type="button" onClick={() => ask(turnIndex)}>
              Repeat question
            </button>
            <button className="lk-btn" type="button" onClick={needMoment}>
              Need a moment
            </button>
            <button className="lk-btn" type="button" onClick={fixLastTerm}>
              Fix last term
            </button>
          </div>
          <p className="lk-note">Prototype mode. Official LiveKit Aura, anchored question, transcript toggles below.</p>
          <div className="lk-dock-group">
            <button className="lk-btn danger" type="button" onClick={closeRoom}>
              End interview
            </button>
          </div>
        </footer>
      </div>

      <section className={["lk-closing", showClosing ? "open" : ""].join(" ")}>
        <article className="lk-closing-card lk-glass">
          <p className="lk-eyebrow">Interview complete</p>
          <h2>Report is being prepared</h2>
          <p>
            The room has captured the conversation. The live assessment is closing and the report will be
            ready after final review.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {["Fencing boundary", "Replication delay", "Failure semantics", "Application transfer"].map((topic) => (
              <span key={topic} className="lk-chip">
                {topic}
              </span>
            ))}
          </div>
          <div className="mt-7">
            <button className="lk-btn primary" type="button" onClick={resetPreview}>
              Reset preview
            </button>
          </div>
        </article>
      </section>
    </main>
  );
}
