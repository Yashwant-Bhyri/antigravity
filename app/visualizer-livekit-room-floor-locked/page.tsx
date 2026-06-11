"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  {
    question:
      "If the recommendation is delay, what would you monitor daily before reopening the launch decision?",
    answer:
      "I would monitor backend revenue, checkout reach, cohort retention, event loss rate, and segment-level movement against the predeclared guardrails.",
    said: "daily launch guardrails",
    testing: "monitoring plan",
  },
  {
    question: "What would make you trust the data enough to reverse your recommendation?",
    answer:
      "I would need agreement between server-side orders, payment intent reach, and corrected client events across the affected cohorts.",
    said: "independent metric agreement",
    testing: "reversal criteria",
  },
  {
    question:
      "Assume leadership asks for a single number. Which metric do you present and what caveat do you attach?",
    answer:
      "I would present backend-confirmed conversion lift with a caveat that client-side checkout telemetry was excluded until reconciliation is complete.",
    said: "single executive metric",
    testing: "executive communication",
  },
  {
    question: "How would you prevent this ambiguity from recurring in the next launch review?",
    answer:
      "I would define owner-approved metric contracts, alert on schema drift, and require server-side guardrail checks before experiment readout.",
    said: "metric governance",
    testing: "prevention system",
  },
  {
    question: "Final pass: what is your decision, confidence, and next action?",
    answer:
      "I would delay launch with medium-high confidence, fix instrumentation first, and schedule a time-boxed reread once the independent metrics align.",
    said: "final decision",
    testing: "decision synthesis",
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
    aura: "#FF9A3D",
    shift: 0.5,
    a: "oklch(0.74 0.18 50)",
    b: "oklch(0.7 0.16 32)",
    c: "oklch(0.68 0.11 76)",
    auraState: "speaking",
    label: "Question",
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
    label: "Your turn",
    title: "Listening to candidate's answer",
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
    label: "Complete",
    title: "Closing interview",
    caption: "The interview is closing and the report is being prepared.",
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function LiveKitRoomFloorPreviewPage() {
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
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraVisible, setCameraVisible] = useState(true);
  const [cameraError, setCameraError] = useState("");
  const [questionFontSize, setQuestionFontSize] = useState<number | null>(null);
  const questionCardRef = useRef<HTMLElement | null>(null);
  const questionTextRef = useRef<HTMLHeadingElement | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
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
        : "Turn";
  const activityText =
    phase === "asking"
      ? "AI interviewer is asking the question"
      : phase === "listening"
        ? "Candidate is speaking"
        : phase === "reviewing"
          ? "AI interviewer is thinking"
          : phase === "closing"
            ? "AI interviewer is closing the interview"
            : "Interview room is ready";
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
      stopCamera(false);
    };
  }, []);

  useLayoutEffect(() => {
    const card = questionCardRef.current;
    const text = questionTextRef.current;
    if (!card || !text) return;

    const fitQuestion = () => {
      const cardStyles = window.getComputedStyle(card);
      const availableWidth =
        card.clientWidth - parseFloat(cardStyles.paddingLeft) - parseFloat(cardStyles.paddingRight);
      const availableHeight =
        card.clientHeight - parseFloat(cardStyles.paddingTop) - parseFloat(cardStyles.paddingBottom);
      if (availableWidth <= 0 || availableHeight <= 0) return;

      const collapsedBoost = historyOpen ? 0 : 2;
      const bounds =
        questionDensity === "dense"
          ? { min: 17, max: 44 + collapsedBoost, line: 1.08 }
          : questionDensity === "compact"
            ? { min: 19, max: 52 + collapsedBoost, line: 1.06 }
            : questionDensity === "medium"
              ? { min: 22, max: 60 + collapsedBoost, line: 1.05 }
              : { min: 26, max: 64 + collapsedBoost, line: 1.04 };

      const previousFont = text.style.fontSize;
      const previousLine = text.style.lineHeight;
      const previousWidth = text.style.width;
      text.style.width = `${availableWidth}px`;
      text.style.lineHeight = String(bounds.line);

      let low = bounds.min;
      let high = bounds.max;
      let best = bounds.min;
      for (let i = 0; i < 9; i += 1) {
        const mid = (low + high) / 2;
        text.style.fontSize = `${mid}px`;
        const fits =
          text.scrollHeight <= availableHeight + 1 &&
          text.scrollWidth <= availableWidth + 1;
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
    return () => observer.disconnect();
  }, [displayedQuestion, historyOpen, questionDensity]);

  function clearTimers() {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    if (typingRef.current) window.clearInterval(typingRef.current);
    if (energyRef.current) window.clearInterval(energyRef.current);
    timerRef.current = null;
    typingRef.current = null;
    energyRef.current = null;
  }

  function startEnergy(kind: "ai" | "candidate" = "candidate") {
    if (energyRef.current) window.clearInterval(energyRef.current);
    let tick = 0;
    energyRef.current = window.setInterval(() => {
      tick += kind === "ai" ? 0.115 : 0.18;
      const base = kind === "ai" ? 0.28 : 0.2;
      const primary = kind === "ai" ? 0.18 : 0.42;
      const secondary = kind === "ai" ? 0.05 : 0.08;
      const next = base + Math.abs(Math.sin(tick)) * primary + Math.abs(Math.sin(tick * 0.43)) * secondary;
      setEnergy(clamp(next, 0.12, kind === "ai" ? 0.58 : 0.82));
    }, 80);
  }

  function stopEnergy(next = 0.18) {
    if (energyRef.current) window.clearInterval(energyRef.current);
    energyRef.current = null;
    setEnergy(next);
  }

  async function startCamera() {
    setCameraError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Camera is not available in this browser.");
      return;
    }

    try {
      stopCamera(false);
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          width: { ideal: 640 },
          height: { ideal: 360 },
          facingMode: "user",
        },
      });
      cameraStreamRef.current = stream;
      setCameraVisible(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setCameraOn(true);
    } catch {
      setCameraOn(false);
      setCameraVisible(true);
      setCameraError("Camera preview blocked. Mock presence remains active.");
    }
  }

  function stopCamera(updateState = true) {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    if (updateState) {
      setCameraOn(false);
      setCameraVisible(true);
    }
  }

  function toggleCamera() {
    if (!cameraOn) {
      void startCamera();
      return;
    }
    setCameraVisible((visible) => !visible);
  }

  function transitionPhase(nextPhase: Phase) {
    setPhase(nextPhase);
  }

  function ask(index = turnIndex) {
    clearTimers();
    setShowClosing(false);
    transitionPhase("asking");
    startEnergy("ai");
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
    startEnergy("candidate");

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
          grid-template-columns: minmax(250px, 310px) minmax(0, 1fr) minmax(280px, 330px);
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
          font-size: clamp(26px, 2.2vw, 32px);
          font-weight: 720;
          letter-spacing: 0;
          line-height: 1.08;
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
          grid-template-rows: auto minmax(0, 1fr) auto;
          align-self: stretch;
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
          animation: lk-stage-ripple 2.9s ease-in-out infinite;
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
          display: grid;
          grid-template-columns: 1fr;
          align-items: stretch;
          gap: 7px;
          border-bottom: 1px solid rgba(255,255,255,0.09);
          padding: 10px 22px 10px;
        }
        .lk-turn-summary {
          display: grid;
          justify-items: center;
          min-height: 6px;
        }
        .lk-stage-status {
          margin: 0;
          color: rgba(255,255,255,0.56);
          font-size: 13px;
          line-height: 1.2;
        }
        .lk-floorline {
          grid-column: 1 / -1;
          display: grid;
          grid-template-columns: minmax(108px, 148px) minmax(28px, 1fr) auto minmax(28px, 1fr) minmax(108px, 148px);
          align-items: center;
          gap: 10px;
          width: min(860px, 100%);
          margin: 6px auto 0;
        }
        .lk-floor-endpoint {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          width: 100%;
          min-height: 26px;
          border: 1px solid transparent;
          border-radius: 999px;
          padding: 4px 9px;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          white-space: nowrap;
          transition: color 180ms ease, border-color 180ms ease, background 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
        }
        .lk-corner-short {
          display: none;
        }
        .lk-floor-endpoint::before {
          content: "";
          height: 8px;
          width: 8px;
          border-radius: 999px;
          background: rgba(255,255,255,0.22);
          transition: background 180ms ease, box-shadow 180ms ease;
        }
        .lk-floor-endpoint.ai::before {
          background: rgba(255,154,61,0.34);
        }
        .lk-floor-endpoint.candidate::before {
          background: rgba(42,208,245,0.34);
        }
        .lk-room[data-floor="ai"] .lk-floor-endpoint.ai {
          color: rgba(255,255,255,0.82);
          border-color: rgba(255,154,61,0.28);
          background: rgba(255,154,61,0.075);
          box-shadow: 0 0 22px rgba(255,154,61,0.16);
        }
        .lk-room[data-floor="candidate"] .lk-floor-endpoint.candidate {
          color: rgba(255,255,255,0.82);
          border-color: rgba(42,208,245,0.28);
          background: rgba(42,208,245,0.07);
          box-shadow: 0 0 22px rgba(42,208,245,0.16);
        }
        .lk-room[data-floor="ai"] .lk-floor-endpoint.ai::before {
          background: rgba(255,154,61,0.94);
          box-shadow: 0 0 18px rgba(255,154,61,0.72);
        }
        .lk-room[data-floor="candidate"] .lk-floor-endpoint.candidate::before {
          background: rgba(42,208,245,0.94);
          box-shadow: 0 0 18px rgba(42,208,245,0.74);
        }
        .lk-floor-track {
          height: 3px;
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
          transform: scaleX(0);
          transition: transform 260ms cubic-bezier(.2,.8,.2,1);
        }
        .lk-floor-track.ai::before {
          background: linear-gradient(90deg, rgba(255,154,61,0.12), rgba(255,154,61,0.95));
          box-shadow: 0 0 16px rgba(255,154,61,0.58);
        }
        .lk-floor-track.candidate::before {
          background: linear-gradient(90deg, rgba(42,208,245,0.95), rgba(42,208,245,0.12));
          box-shadow: 0 0 16px rgba(42,208,245,0.6);
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
          min-height: 26px;
          min-width: 68px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 5px 10px;
          background: rgba(0,0,0,0.36);
          color: rgba(255,255,255,0.72);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          white-space: nowrap;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .lk-floor-center {
          display: flex;
          align-items: center;
          justify-content: center;
          min-width: 68px;
        }
        .lk-room[data-floor="ai"] .lk-floor-pill,
        .lk-room[data-floor="candidate"] .lk-floor-pill {
          border-color: rgba(255,255,255,0.15);
          color: rgba(255,255,255,0.88);
        }
        .lk-activity-box {
          display: inline-flex;
          width: fit-content;
          max-width: 100%;
          min-height: 34px;
          align-items: center;
          justify-self: center;
          gap: 10px;
          margin-top: 10px;
          border: 1px solid color-mix(in oklch, var(--mural-a) 20%, rgba(255,255,255,0.08));
          border-radius: 999px;
          padding: 7px 14px;
          background: rgba(0,0,0,0.32);
          color: rgba(255,255,255,0.76);
          font-size: 16px;
          font-weight: 800;
          line-height: 1.2;
          box-shadow: 0 0 22px color-mix(in oklch, var(--mural-a) 8%, transparent);
        }
        .lk-progress {
          display: flex;
          flex-shrink: 0;
          align-items: center;
          justify-content: center;
          gap: 4px;
          width: min(560px, 100%);
          min-width: 0;
        }
        .lk-progress span {
          flex: 1 1 10px;
          height: 4px;
          min-width: 8px;
          max-width: 24px;
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
          padding: clamp(8px, 1.1vw, 12px) clamp(20px, 3vw, 34px) 16px;
        }
        .lk-question-card {
          position: relative;
          display: flex;
          flex-direction: column;
          justify-content: center;
          height: clamp(156px, 20vh, 196px);
          align-items: stretch;
          overflow: hidden;
          border: 1px solid color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.08));
          border-radius: 28px;
          padding: clamp(14px, 1.8vw, 22px) clamp(18px, 2.6vw, 34px);
          background: #020304;
          box-shadow:
            inset 0 0 0 1px rgba(255,255,255,0.03),
            inset 0 0 28px rgba(255,255,255,0.018);
          backdrop-filter: none;
        }
        .lk-question-card.question-medium {
          height: clamp(168px, 21.5vh, 210px);
        }
        .lk-question-card.question-compact {
          height: clamp(184px, 23.5vh, 230px);
        }
        .lk-question-card.question-dense {
          height: clamp(198px, 25.5vh, 250px);
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
        .lk-question-label {
          position: absolute;
          top: clamp(12px, 1.5vw, 18px);
          left: clamp(18px, 2.6vw, 34px);
          z-index: 1;
          margin: 0;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.18em;
          line-height: 1;
          text-transform: uppercase;
        }
        .lk-question {
          position: relative;
          z-index: 1;
          width: 100%;
          max-width: 1040px;
          margin: 32px 0 0;
          font-size: clamp(34px, 3.12vw, 48px);
          font-weight: 750;
          letter-spacing: 0;
          line-height: 1.04;
        }
        .lk-question-ink {
          padding: 0;
          background: transparent;
          box-shadow: none;
          text-shadow: 0 2px 18px rgba(0,0,0,0.64);
        }
        .lk-workspace.history-collapsed .lk-question {
          max-width: 1140px;
          font-size: clamp(35px, 3.32vw, 50px);
        }
        .lk-workspace.history-collapsed .lk-question.medium {
          font-size: clamp(31px, 3.02vw, 45px);
        }
        .lk-workspace.history-collapsed .lk-question.compact {
          font-size: clamp(27px, 2.62vw, 39px);
        }
        .lk-workspace.history-collapsed .lk-question.dense {
          font-size: clamp(23px, 2.24vw, 34px);
        }
        .lk-question.medium {
          font-size: clamp(29px, 2.54vw, 39px);
          line-height: 1.05;
        }
        .lk-question.compact {
          font-size: clamp(25px, 2.14vw, 33px);
          line-height: 1.06;
        }
        .lk-question.dense {
          font-size: clamp(22px, 1.9vw, 30px);
          line-height: 1.08;
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
          min-height: 116px;
          max-height: 168px;
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
          display: grid;
          grid-template-rows: auto auto minmax(0, 1fr);
          gap: 12px;
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
        .lk-memory.collapsed .lk-candidate-camera {
          display: none;
        }
        .lk-memory.collapsed .lk-rail-toolbar {
          display: none;
        }
        .lk-rail-toolbar {
          display: flex;
          min-height: 34px;
          align-items: center;
          justify-content: flex-end;
        }
        .lk-candidate-camera {
          position: relative;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 24px;
          background: #030506;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
          transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
        }
        .lk-room[data-floor="candidate"] .lk-candidate-camera {
          border-color: color-mix(in oklch, var(--mural-a) 40%, rgba(255,255,255,0.1));
          box-shadow:
            0 0 28px color-mix(in oklch, var(--mural-a) 16%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.04);
        }
        .lk-camera-frame {
          position: relative;
          display: grid;
          aspect-ratio: 16 / 9;
          min-height: 150px;
          place-items: center;
          overflow: hidden;
          border-bottom: 1px solid rgba(255,255,255,0.07);
          background:
            radial-gradient(14rem 9rem at 50% 38%, color-mix(in oklch, var(--mural-a) 14%, transparent), transparent 62%),
            linear-gradient(135deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012)),
            #030506;
        }
        .lk-camera-frame::before {
          content: "";
          position: absolute;
          inset: 0;
          opacity: 0.16;
          background:
            linear-gradient(120deg, transparent 0 44%, rgba(255,255,255,0.18) 50%, transparent 58%),
            radial-gradient(circle at 50% 48%, transparent 0 45%, rgba(0,0,0,0.62) 78%);
        }
        .lk-camera-video {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0;
          transition: opacity 180ms ease;
        }
        .lk-candidate-camera.camera-on:not(.stream-hidden) .lk-camera-video {
          opacity: 1;
        }
        .lk-camera-avatar {
          position: relative;
          z-index: 1;
          display: grid;
          height: 74px;
          width: 74px;
          place-items: center;
          border: 1px solid color-mix(in oklch, var(--mural-a) 32%, rgba(255,255,255,0.12));
          border-radius: 24px;
          background: rgba(0,0,0,0.45);
          color: rgba(255,255,255,0.88);
          font-size: 20px;
          font-weight: 800;
          letter-spacing: 0.08em;
          box-shadow: 0 0 28px color-mix(in oklch, var(--mural-a) 14%, transparent);
        }
        .lk-candidate-camera.camera-on:not(.stream-hidden) .lk-camera-avatar {
          opacity: 0;
        }
        .lk-candidate-camera.stream-hidden .lk-camera-frame::after {
          content: "Camera preview hidden";
          position: absolute;
          right: 12px;
          bottom: 12px;
          z-index: 2;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 5px 8px;
          background: rgba(0,0,0,0.5);
          color: rgba(255,255,255,0.58);
          font-size: 10px;
          font-weight: 760;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .lk-camera-meta {
          display: grid;
          gap: 10px;
          padding: 12px;
        }
        .lk-camera-status {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          color: rgba(255,255,255,0.62);
          font-size: 12px;
          line-height: 1.4;
        }
        .lk-camera-status strong {
          color: rgba(255,255,255,0.86);
        }
        .lk-camera-action {
          min-height: 34px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 12px;
          background: rgba(255,255,255,0.052);
          color: rgba(255,255,255,0.74);
          cursor: pointer;
        }
        .lk-camera-error {
          margin: 0;
          color: rgba(255,190,196,0.72);
          font-size: 11px;
          line-height: 1.4;
        }
        .lk-memory-content {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          gap: 12px;
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
        @keyframes lk-stage-ripple {
          0%, 100% {
            opacity: calc(0.14 + var(--energy) * 0.06);
            transform: scaleX(1) translateY(0);
          }
          48% {
            opacity: calc(0.2 + var(--energy) * 0.08);
            transform: scaleX(1.012) translateY(-1px);
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
          .lk-floorline { gap: 6px; width: 100%; }
          .lk-floor-endpoint {
            gap: 6px;
            padding: 5px 7px;
            font-size: 9px;
            letter-spacing: 0.1em;
          }
          .lk-corner-full { display: none; }
          .lk-corner-short { display: inline; }
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
              <p className="lk-label">AI interviewer</p>
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
              <div className="lk-turn-summary">
                <div className="lk-progress" aria-label="Interview progress">
                  {TURNS.map((_, item) => (
                    <span key={item} className={item <= turnIndex ? "done" : ""} />
                  ))}
                </div>
              </div>
              <span className="lk-activity-box" aria-live="polite">
                <span className="lk-dot" />
                <span>{activityText}</span>
              </span>
              <div className="lk-floorline" aria-label={`Floor owner: ${floorLabel}`}>
                <span className="lk-floor-endpoint ai">
                  <span className="lk-corner-full">AI corner</span>
                  <span className="lk-corner-short">AI</span>
                </span>
                <span className="lk-floor-track ai" />
                <span className="lk-floor-center">
                  <span className="lk-floor-pill">Turn</span>
                </span>
                <span className="lk-floor-track candidate" />
                <span className="lk-floor-endpoint candidate">
                  <span className="lk-corner-full">Candidate corner</span>
                  <span className="lk-corner-short">You</span>
                </span>
              </div>
            </div>

            <div className="lk-stage-body">
              <article
                ref={questionCardRef}
                key={`${turnIndex}-${displayedQuestion}`}
                className={[
                  "lk-question-card",
                  `question-${questionDensity}`,
                  phase !== "ready" ? "sync-glow" : "",
                  phase === "asking" ? "focus-question" : "",
                ].join(" ")}
              >
                <p className="lk-question-label">Interviewer's question</p>
                <h2
                  ref={questionTextRef}
                  className={["lk-question", questionDensity].join(" ")}
                  style={questionFontSize ? { fontSize: `${questionFontSize}px` } : undefined}
                >
                  <span className="lk-question-ink">{displayedQuestion}</span>
                </h2>
              </article>

              <article className={["lk-answer-panel", liveTranscriptOpen ? "open" : ""].join(" ")}>
                <div className="lk-answer-inner">
                  <div className="lk-answer-header">
                    <p className="lk-label">
                      {liveTranscriptOpen
                        ? "Candidate answer live transcription"
                        : phase === "reviewing"
                          ? "Latest answer"
                          : "Current answer"}
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
                    {liveAnswer ||
                      (liveTranscriptOpen
                        ? "Live transcription will appear here while the candidate speaks."
                        : "Latest answer appears here without moving the question.")}
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
            {historyOpen && (
              <div className="lk-rail-toolbar">
                <button className="lk-history-toggle expanded" type="button" onClick={() => setHistoryOpen(false)}>
                  Collapse
                </button>
              </div>
            )}
            <section
              className={[
                "lk-candidate-camera",
                cameraOn ? "camera-on" : "",
                cameraOn && !cameraVisible ? "stream-hidden" : "",
              ].join(" ")}
            >
              <div className="lk-camera-frame">
                <video ref={videoRef} className="lk-camera-video" muted playsInline />
                <div className="lk-camera-avatar" aria-hidden="true">
                  SV
                </div>
              </div>
              <div className="lk-camera-meta">
                <div className="lk-camera-status">
                  <div>
                    <p className="lk-label">Candidate presence</p>
                    <strong>
                      {cameraOn && !cameraVisible
                        ? "Stream hidden"
                        : floorOwner === "candidate"
                          ? "Your floor is active"
                          : "Camera ready"}
                    </strong>
                  </div>
                  <span className="lk-dot" />
                </div>
                <button className="lk-camera-action" type="button" onClick={toggleCamera}>
                  {!cameraOn ? "Test camera" : cameraVisible ? "Hide stream" : "Show stream"}
                </button>
                {cameraError && <p className="lk-camera-error">{cameraError}</p>}
              </div>
            </section>
            <div className="lk-memory-content">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="lk-label">Turn history</p>
                  <p className="lk-stage-status">
                    Committed turns. Open full transcript for the whole interview.
                  </p>
                </div>
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
