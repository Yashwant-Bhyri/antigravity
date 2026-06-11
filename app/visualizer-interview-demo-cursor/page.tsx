"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StageId = "seed" | "problem" | "loop" | "setup" | "build" | "turns" | "room" | "report" | "close";

type Stage = {
  id: StageId;
  label: string;
  title: string;
  subtitle: string;
  progress: number;
  duration: number;
  targets: string[];
};

const STAGES: Stage[] = [
  {
    id: "seed",
    label: "Start",
    title: "Start interview simulation",
    subtitle: "A guided product loop, driven by the cursor.",
    progress: 0,
    duration: 1700,
    targets: ["seed-pill"],
  },
  {
    id: "problem",
    label: "Problem",
    title: "Hiring still relies on weak evidence.",
    subtitle: "Antigravity turns polished claims into live evidence the hiring team can defend.",
    progress: 13,
    duration: 6500,
    targets: ["claim-card", "pressure-card", "evidence-card"],
  },
  {
    id: "loop",
    label: "Product loop",
    title: "The interview becomes the product experience.",
    subtitle: "A candidate answers in a calm room while the hiring team gets the evidence trail behind the answer.",
    progress: 25,
    duration: 6500,
    targets: ["loop-orient", "loop-answer", "loop-recover", "loop-output"],
  },
  {
    id: "setup",
    label: "Setup",
    title: "Role context becomes the first constraint.",
    subtitle: "The system starts from the candidate, role, decision goal, and measurable hiring question.",
    progress: 38,
    duration: 6200,
    targets: ["brief-role", "brief-scenario", "brief-goal"],
  },
  {
    id: "build",
    label: "Build",
    title: "The live room assembles before the call starts.",
    subtitle: "Interview presence, turn ownership, candidate controls, history, and report output land in one coherent flow.",
    progress: 51,
    duration: 6800,
    targets: ["piece-context", "piece-turn", "piece-room", "piece-report"],
  },
  {
    id: "turns",
    label: "Turns",
    title: "The floor moves visibly between AI and candidate.",
    subtitle: "The demo shows the core promise: no hidden state, no awkward dead air, no guessing who should speak.",
    progress: 64,
    duration: 6600,
    targets: ["turn-ai", "turn-center", "turn-candidate"],
  },
  {
    id: "room",
    label: "Live room",
    title: "The room keeps the task legible.",
    subtitle: "Question, answer, camera, controls, and history stay separated so the candidate can focus.",
    progress: 78,
    duration: 7600,
    targets: ["room-aura", "room-question", "room-live", "room-controls", "room-history"],
  },
  {
    id: "report",
    label: "Report",
    title: "The output is a decision package.",
    subtitle: "The hiring team sees what was tested, strongest signal, calibrated claims, and follow-ups.",
    progress: 92,
    duration: 7600,
    targets: ["report-verdict", "report-fit", "report-signal", "report-evidence"],
  },
  {
    id: "close",
    label: "Close",
    title: "One loop: claim, live test, decision evidence.",
    subtitle: "A serious room for candidates. A defensible package for hiring teams.",
    progress: 100,
    duration: 5200,
    targets: ["close-primary"],
  },
];

const PROBLEM_CARDS = [
  {
    id: "claim-card",
    tag: "Resume claim",
    title: "Owned launch analytics",
    body: "Looks credible on paper, but the team still cannot see judgment under ambiguity.",
  },
  {
    id: "pressure-card",
    tag: "Live pressure",
    title: "Metric drop under follow-up",
    body: "The room asks the next question from what the candidate just said, then watches recovery.",
  },
  {
    id: "evidence-card",
    tag: "Decision evidence",
    title: "Scoped yes + follow-ups",
    body: "Hiring gets a bounded recommendation, tested claims, and the exact risks to clarify.",
  },
];

const LOOP_ITEMS = [
  ["loop-orient", "Orient", "The candidate sees the interviewer presence, turn rail, and camera corner."],
  ["loop-answer", "Answer", "The question stays anchored while the answer appears below it."],
  ["loop-recover", "Recover", "Repeat, pause, correction, and transcript access stay one click away."],
  ["loop-output", "Output", "The live conversation becomes role fit, signal, and follow-up evidence."],
];

const BRIEF_ROWS = [
  ["brief-role", "Role", "Product Analyst"],
  ["brief-scenario", "Live scenario", "Conversion drops, but event instrumentation may be unreliable."],
  ["brief-goal", "Room goal", "Observe reasoning, clarification, tradeoffs, recovery, and communication."],
];

const BUILD_PIECES = [
  ["piece-context", "Candidate context", "Resume claims and role focus shape the room."],
  ["piece-turn", "Turn ownership", "AI and candidate floor states are visible."],
  ["piece-room", "Live room", "Question, answer, controls, camera, and history stay separated."],
  ["piece-report", "Decision package", "The session resolves into structured hiring evidence."],
];

const REPORT_CARDS = [
  ["report-fit", "Role fit", "Scoped yes", "Strong for product analytics roles with metric-quality ambiguity."],
  ["report-signal", "Strongest signal", "Judgment under follow-up", "Separated real conversion movement from instrumentation noise."],
  ["report-evidence", "Evidence trail", "Claim to answer", "Connects the resume claim to the exact live responses that supported it."],
  ["report-follow", "Follow-ups", "Two open risks", "Governance depth and dashboard ownership should be clarified in a human loop."],
];

function auraState(stage: StageId): AgentState {
  if (stage === "room" || stage === "turns") return "speaking";
  if (stage === "build" || stage === "report") return "thinking";
  return "idle";
}

function cubicPoint(start: number, c1: number, c2: number, end: number, t: number) {
  const inv = 1 - t;
  return inv ** 3 * start + 3 * inv ** 2 * t * c1 + 3 * inv * t ** 2 * c2 + t ** 3 * end;
}

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3;
}

export default function CursorDrivenInterviewDemoPage() {
  const [stageIndex, setStageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [activeTarget, setActiveTarget] = useState("seed-pill");
  const [cursor, setCursor] = useState({ x: 0, y: 0, visible: false, pressed: false });
  const cursorRef = useRef({ x: 0, y: 0 });
  const targetRefs = useRef(new Map<string, HTMLElement>());
  const stage = STAGES[stageIndex];
  const sequenceKey = `${stage.id}:${stageIndex}`;

  const registerTarget = useCallback((id: string) => {
    return (node: HTMLElement | null) => {
      if (node) {
        targetRefs.current.set(id, node);
      } else {
        targetRefs.current.delete(id);
      }
    };
  }, []);

  const moveCursorTo = useCallback((targetId: string, duration = 900) => {
    const target = targetRefs.current.get(targetId);
    if (!target) return window.setTimeout(() => undefined, duration);

    const rect = target.getBoundingClientRect();
    const start = { ...cursorRef.current };
    const end = {
      x: rect.left + rect.width * 0.52,
      y: rect.top + rect.height * 0.52,
    };
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const arc = Math.max(52, Math.min(180, Math.abs(dx) * 0.16 + Math.abs(dy) * 0.1));
    const c1 = { x: start.x + dx * 0.36, y: start.y + dy * 0.18 - arc };
    const c2 = { x: start.x + dx * 0.74, y: start.y + dy * 0.88 + arc * 0.36 };
    const startTime = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      const raw = Math.min(1, (now - startTime) / duration);
      const t = easeOutCubic(raw);
      const next = {
        x: cubicPoint(start.x, c1.x, c2.x, end.x, t),
        y: cubicPoint(start.y, c1.y, c2.y, end.y, t),
      };
      cursorRef.current = next;
      setCursor({ ...next, visible: true, pressed: raw > 0.82 && raw < 0.94 });
      if (raw < 1) {
        frame = window.requestAnimationFrame(tick);
      } else {
        setActiveTarget(targetId);
        setCursor((current) => ({ ...current, pressed: true }));
        window.setTimeout(() => setCursor((current) => ({ ...current, pressed: false })), 160);
      }
    };

    frame = window.requestAnimationFrame(tick);
    return window.setTimeout(() => {
      window.cancelAnimationFrame(frame);
    }, duration + 120);
  }, []);

  useEffect(() => {
    const firstTarget = targetRefs.current.get(stage.targets[0]);
    if (!firstTarget) return;
    const rect = firstTarget.getBoundingClientRect();
    const initial = {
      x: rect.left + rect.width * 0.5,
      y: rect.top + rect.height + 64,
    };
    cursorRef.current = initial;
    setCursor({ ...initial, visible: true, pressed: false });
    setActiveTarget(stage.targets[0]);
  }, [sequenceKey, stage.targets]);

  useEffect(() => {
    if (!isPlaying) return;
    let cancelled = false;
    const timers: number[] = [];

    const run = async () => {
      await new Promise((resolve) => timers.push(window.setTimeout(resolve, 260)));
      for (const target of stage.targets) {
        if (cancelled) return;
        moveCursorTo(target, stage.id === "seed" ? 420 : 820);
        await new Promise((resolve) => timers.push(window.setTimeout(resolve, stage.id === "seed" ? 720 : 1380)));
      }
      if (cancelled) return;
      timers.push(window.setTimeout(() => {
        setStageIndex((current) => Math.min(STAGES.length - 1, current + 1));
      }, Math.max(360, stage.duration - stage.targets.length * 1380)));
    };

    run();
    return () => {
      cancelled = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [isPlaying, moveCursorTo, sequenceKey, stage.duration, stage.id, stage.targets]);

  const rootStyle = useMemo(
    () => ({
      "--progress": `${stage.progress}%`,
      "--cursor-x": `${cursor.x}px`,
      "--cursor-y": `${cursor.y}px`,
    }) as CSSProperties,
    [cursor.x, cursor.y, stage.progress],
  );

  const setStage = (index: number) => {
    setIsPlaying(false);
    setStageIndex(index);
  };

  const isActive = (id: string) => activeTarget === id;
  const hasActiveIn = (ids: string[]) => ids.includes(activeTarget);

  return (
    <main className="cursor-demo" data-stage={stage.id} style={rootStyle}>
      <style>{`
        .cursor-demo {
          --black: #030303;
          --panel: rgba(13, 14, 14, 0.86);
          --line: rgba(245, 241, 232, 0.12);
          --cream: #f3eee4;
          --muted: rgba(243, 238, 228, 0.62);
          --dim: rgba(243, 238, 228, 0.38);
          --amber: #dba857;
          --orange: #c56f43;
          --teal: #42d4e8;
          --green: #7fe2ae;
          --danger: #ef7d69;
          min-height: 100svh;
          overflow: hidden;
          color: var(--cream);
          font-family: var(--font-geist-sans), Inter, ui-sans-serif, system-ui, sans-serif;
          background:
            radial-gradient(58rem 34rem at 82% 18%, rgba(197,111,67,0.12), transparent 66%),
            radial-gradient(48rem 30rem at 16% 82%, rgba(66,212,232,0.11), transparent 66%),
            linear-gradient(180deg, #080807, #020202);
        }
        .cursor-demo::before {
          content: "";
          position: fixed;
          inset: -20%;
          pointer-events: none;
          opacity: 0.08;
          background:
            linear-gradient(115deg, transparent 0 37%, rgba(243,238,228,0.08) 37.25% 37.7%, transparent 37.9% 100%),
            radial-gradient(circle, rgba(243,238,228,0.34) 0 1px, transparent 1.35px);
          background-size: auto, 34px 34px;
          mask-image: radial-gradient(ellipse at center, black 0 58%, transparent 80%);
        }
        .viewport {
          position: relative;
          z-index: 1;
          min-height: 100svh;
          display: grid;
          place-items: center;
          padding: 22px 32px 54px;
        }
        h1, h2, h3, p { margin-top: 0; }
        button { font: inherit; }
        .seed {
          display: none;
          min-width: 270px;
          justify-content: center;
          align-items: center;
          gap: 11px;
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 18px 26px;
          background: linear-gradient(180deg, rgba(255,255,255,0.09), rgba(255,255,255,0.04));
          box-shadow: 0 32px 90px rgba(0,0,0,0.42);
          font-weight: 850;
        }
        .seed::before {
          content: "";
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--green);
          box-shadow: 0 0 26px rgba(127,226,174,0.58);
        }
        .cursor-demo[data-stage="seed"] .seed { display: flex; }
        .shell {
          width: min(1460px, calc(100vw - 64px));
          height: min(820px, calc(100svh - 108px));
          min-height: 620px;
          display: grid;
          grid-template-rows: auto 1fr;
          border: 1px solid var(--line);
          border-radius: 34px;
          overflow: hidden;
          background:
            radial-gradient(48rem 26rem at 72% 16%, rgba(197,111,67,0.09), transparent 62%),
            rgba(5,5,5,0.9);
          box-shadow: 0 44px 140px rgba(0,0,0,0.56), inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .cursor-demo[data-stage="seed"] .shell { display: none; }
        .top {
          display: grid;
          grid-template-columns: minmax(0,1fr) 390px;
          gap: 24px;
          align-items: center;
          padding: 24px 32px;
          border-bottom: 1px solid var(--line);
        }
        .brand { display: flex; align-items: center; gap: 16px; min-width: 0; }
        .mark {
          width: 52px;
          height: 52px;
          display: grid;
          place-items: center;
          border-radius: 18px;
          background: radial-gradient(circle at 36% 34%, rgba(197,111,67,0.62), rgba(197,111,67,0.08) 62%, rgba(0,0,0,0.84));
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.1), 0 0 34px rgba(197,111,67,0.15);
        }
        .mark::after {
          content: "";
          width: 20px;
          height: 20px;
          border: 3px solid white;
          border-left-color: transparent;
          border-radius: 50%;
        }
        .kicker {
          margin: 0;
          color: rgba(243,238,228,0.54);
          font-size: 10px;
          font-weight: 870;
          letter-spacing: 0.25em;
          text-transform: uppercase;
        }
        .brand h1 { margin: 5px 0 0; font-size: 24px; line-height: 1.05; }
        .progress { display: grid; gap: 9px; color: var(--muted); font-size: 12px; }
        .progress-row { display: flex; justify-content: space-between; }
        .progress-bar { height: 7px; border-radius: 999px; overflow: hidden; background: rgba(243,238,228,0.11); }
        .progress-bar::after {
          content: "";
          display: block;
          width: var(--progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--orange), var(--amber), var(--teal), var(--green));
          transition: width 520ms ease;
        }
        .body {
          min-height: 0;
          display: grid;
          grid-template-columns: minmax(360px, 0.82fr) minmax(640px, 1.18fr);
          gap: 34px;
          align-items: center;
          padding: 40px 42px;
          overflow: hidden;
        }
        .hero h2 {
          max-width: 690px;
          margin: 14px 0 0;
          font-size: clamp(48px, 6vw, 90px);
          line-height: 0.92;
          letter-spacing: 0;
          font-weight: 560;
        }
        .hero p {
          max-width: 620px;
          margin: 24px 0 0;
          color: var(--muted);
          font-size: 17px;
          line-height: 1.55;
        }
        .stage-count {
          display: inline-flex;
          margin-top: 30px;
          border: 1px solid rgba(243,238,228,0.13);
          border-radius: 999px;
          padding: 10px 13px;
          color: var(--muted);
          font-size: 12px;
          font-weight: 760;
        }
        .visual { min-height: 0; display: grid; align-content: center; gap: 16px; }
        .target {
          transform: translateZ(0) scale(1);
          opacity: 1;
          transition:
            transform 460ms cubic-bezier(.2,.86,.18,1),
            opacity 360ms ease,
            border-color 360ms ease,
            filter 360ms ease,
            background 360ms ease;
          will-change: transform, opacity;
        }
        .target.is-active {
          transform: translateZ(0) scale(1.055);
          opacity: 1;
          z-index: 5;
          border-color: rgba(243,238,228,0.36) !important;
          filter: drop-shadow(0 26px 42px rgba(0,0,0,0.42));
        }
        .has-focus .target:not(.is-active) {
          transform: translateZ(0) scale(0.955);
          opacity: 0.45;
        }
        .signal-flow {
          display: grid;
          grid-template-columns: repeat(3, minmax(0,1fr));
          gap: 18px;
          min-height: 344px;
          align-items: stretch;
        }
        .signal-card {
          position: relative;
          display: grid;
          align-content: space-between;
          min-height: 286px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 31px;
          padding: 24px;
          overflow: hidden;
          background:
            radial-gradient(20rem 15rem at 50% 0%, rgba(197,111,67,0.12), transparent 62%),
            rgba(255,255,255,0.045);
        }
        .signal-card:nth-child(2) {
          background:
            radial-gradient(20rem 15rem at 50% 0%, rgba(66,212,232,0.12), transparent 62%),
            rgba(255,255,255,0.045);
        }
        .signal-card:nth-child(3) {
          background:
            radial-gradient(20rem 15rem at 50% 0%, rgba(127,226,174,0.11), transparent 62%),
            rgba(255,255,255,0.045);
        }
        .tag {
          width: fit-content;
          border: 1px solid rgba(219,168,87,0.28);
          border-radius: 999px;
          padding: 9px 12px;
          color: #ffe1ad;
          background: rgba(219,168,87,0.08);
          font-size: 11px;
          font-weight: 850;
          letter-spacing: 0.15em;
          text-transform: uppercase;
        }
        .signal-card strong,
        .loop-item strong,
        .piece strong,
        .report-card strong {
          display: block;
          color: white;
          font-size: 27px;
          line-height: 1.03;
          letter-spacing: 0;
        }
        .signal-card p,
        .loop-item p,
        .piece p,
        .report-card p {
          margin: 16px 0 0;
          color: rgba(243,238,228,0.64);
          font-size: 14px;
          line-height: 1.48;
        }
        .signal-card.is-active:nth-child(2)::after {
          content: "";
          position: absolute;
          left: 24px;
          right: 24px;
          bottom: 22px;
          height: 42px;
          border-radius: 14px;
          background:
            linear-gradient(135deg, transparent 0 46%, rgba(239,125,105,0.82) 46% 50%, transparent 50%),
            linear-gradient(90deg, rgba(66,212,232,0.18), rgba(239,125,105,0.2));
          animation: metric-shock 780ms ease both;
        }
        @keyframes metric-shock {
          from { opacity: 0; transform: translateY(8px) scaleX(0.86); }
          to { opacity: 1; transform: translateY(0) scaleX(1); }
        }
        .loop-board {
          display: grid;
          grid-template-columns: repeat(4, minmax(0,1fr));
          gap: 14px;
          border: 1px solid var(--line);
          border-radius: 34px;
          padding: 24px;
          background:
            radial-gradient(34rem 18rem at 50% 50%, rgba(66,212,232,0.09), transparent 72%),
            rgba(255,255,255,0.035);
        }
        .loop-item {
          min-height: 250px;
          border: 1px solid var(--line);
          border-radius: 25px;
          padding: 21px;
          background: rgba(0,0,0,0.44);
        }
        .loop-item .number {
          display: grid;
          width: 42px;
          height: 42px;
          place-items: center;
          margin-bottom: 26px;
          border-radius: 16px;
          color: #dfffff;
          background: rgba(66,212,232,0.12);
          font-weight: 850;
        }
        .brief {
          max-width: 800px;
          justify-self: end;
          border: 1px solid rgba(255,255,255,0.58);
          border-radius: 32px;
          padding: 30px;
          color: #16120f;
          background: linear-gradient(180deg, #f4efe4, #e7dcc8);
          box-shadow: 0 36px 120px rgba(0,0,0,0.38);
        }
        .brief h3 { margin: 0 0 18px; font-size: 27px; }
        .brief-row {
          display: grid;
          grid-template-columns: 170px minmax(0,1fr);
          gap: 20px;
          padding: 18px 0;
          border-top: 1px solid rgba(20,17,15,0.12);
        }
        .brief-row span:first-child {
          color: rgba(20,17,15,0.48);
          font-size: 11px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .brief-row span:last-child {
          font-size: 18px;
          font-weight: 760;
          line-height: 1.28;
        }
        .build-canvas {
          display: grid;
          grid-template-columns: 0.72fr 1.28fr;
          gap: 22px;
          align-items: stretch;
        }
        .assembly {
          border: 1px solid rgba(66,212,232,0.22);
          border-radius: 31px;
          padding: 25px;
          background:
            radial-gradient(28rem 18rem at 50% 30%, rgba(66,212,232,0.12), transparent 68%),
            rgba(0,0,0,0.5);
          min-height: 390px;
        }
        .assembly h3 { margin: 0; font-size: 29px; }
        .assembly-zone {
          display: grid;
          place-items: center;
          min-height: 250px;
          margin-top: 24px;
          border: 1px dashed rgba(243,238,228,0.18);
          border-radius: 26px;
          color: rgba(243,238,228,0.52);
        }
        .piece-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; }
        .piece {
          min-height: 174px;
          border: 1px solid var(--line);
          border-radius: 24px;
          padding: 20px;
          background: rgba(255,255,255,0.045);
        }
        .piece.is-active {
          transform: translate3d(-34px, -8px, 0) scale(1.05);
        }
        .turn-sim {
          display: grid;
          gap: 18px;
          border: 1px solid var(--line);
          border-radius: 34px;
          padding: 28px;
          background:
            radial-gradient(34rem 20rem at 18% 46%, rgba(197,111,67,0.12), transparent 62%),
            radial-gradient(34rem 20rem at 82% 48%, rgba(66,212,232,0.13), transparent 62%),
            rgba(255,255,255,0.035);
        }
        .turn-stage {
          display: grid;
          grid-template-columns: 190px minmax(0,1fr) 190px;
          gap: 18px;
          align-items: stretch;
        }
        .corner, .floor-center {
          min-height: 210px;
          border: 1px solid var(--line);
          border-radius: 28px;
          background: rgba(0,0,0,0.44);
          padding: 20px;
        }
        .corner {
          display: grid;
          align-content: center;
          justify-items: center;
          gap: 14px;
          text-align: center;
        }
        .avatar {
          display: grid;
          width: 76px;
          height: 76px;
          place-items: center;
          border-radius: 25px;
          background: rgba(255,255,255,0.06);
          font-weight: 850;
        }
        .corner.ai .avatar { color: #ffd7bf; background: rgba(197,111,67,0.12); }
        .corner.candidate .avatar { color: #dcfbff; background: rgba(66,212,232,0.12); }
        .corner strong { font-size: 15px; }
        .floor-center {
          display: grid;
          align-content: center;
          gap: 18px;
        }
        .floor-rail {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          align-items: center;
          gap: 16px;
        }
        .floor-rail span {
          height: 3px;
          border-radius: 999px;
          background: rgba(243,238,228,0.14);
        }
        .floor-rail b {
          border: 1px solid rgba(243,238,228,0.18);
          border-radius: 999px;
          padding: 10px 18px;
          background: #050505;
          font-size: 11px;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
        .floor-note {
          min-height: 76px;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 20px;
          padding: 16px;
          color: var(--muted);
          background: rgba(255,255,255,0.04);
        }
        .turn-stage:has(.ai.is-active) .floor-rail span:first-child,
        .turn-stage:has(.candidate.is-active) .floor-rail span:last-child,
        .turn-stage:has(.floor-center.is-active) .floor-rail span {
          background: linear-gradient(90deg, var(--orange), var(--amber), var(--teal));
          box-shadow: 0 0 24px rgba(219,168,87,0.22);
        }
        .room {
          display: grid;
          grid-template-columns: 245px minmax(560px,1fr) 245px;
          gap: 15px;
          border: 1px solid var(--line);
          border-radius: 31px;
          padding: 16px;
          background: rgba(0,0,0,0.46);
        }
        .room-panel {
          min-width: 0;
          border: 1px solid var(--line);
          border-radius: 24px;
          padding: 16px;
          background: rgba(0,0,0,0.62);
        }
        .mini-aura, .camera {
          min-height: 210px;
          display: grid;
          place-items: center;
          margin-top: 15px;
          border-radius: 20px;
          background: #020202;
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.08);
        }
        .camera span {
          display: grid;
          width: 74px;
          height: 74px;
          place-items: center;
          border-radius: 24px;
          background: rgba(66,212,232,0.1);
          font-size: 21px;
          font-weight: 850;
        }
        .room h3 { margin: 0; font-size: 19px; }
        .turn-line {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          align-items: center;
          gap: 12px;
          margin-bottom: 15px;
        }
        .turn-line span { height: 2px; border-radius: 999px; background: rgba(243,238,228,0.16); }
        .turn-line b {
          border: 1px solid rgba(66,212,232,0.28);
          border-radius: 999px;
          padding: 8px 14px;
          color: #dfffff;
          font-size: 10px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .question-card {
          min-height: 220px;
          display: grid;
          align-content: center;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 24px;
          padding: 28px;
          background: #000;
        }
        .label {
          display: block;
          margin-bottom: 13px;
          color: rgba(243,238,228,0.48);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
        .question-card p {
          margin: 0;
          color: white;
          font-size: clamp(30px, 3.1vw, 47px);
          line-height: 1.02;
          font-weight: 850;
          letter-spacing: 0;
        }
        .live-strip {
          margin-top: 13px;
          border: 1px solid rgba(66,212,232,0.18);
          border-radius: 18px;
          padding: 13px 15px;
          color: rgba(243,238,228,0.66);
          font-size: 13px;
          line-height: 1.45;
        }
        .controls { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        .pill {
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 10px 13px;
          color: rgba(243,238,228,0.76);
          background: rgba(255,255,255,0.06);
        }
        .history { display: grid; gap: 9px; margin-top: 14px; }
        .history-card {
          border: 1px solid rgba(66,212,232,0.14);
          border-radius: 16px;
          padding: 11px;
          color: rgba(243,238,228,0.7);
          background: rgba(66,212,232,0.055);
          font-size: 11px;
          line-height: 1.35;
        }
        .report {
          display: grid;
          grid-template-columns: 0.92fr 1.08fr;
          gap: 18px;
          align-items: stretch;
        }
        .verdict {
          min-height: 420px;
          border: 1px solid rgba(255,255,255,0.5);
          border-radius: 32px;
          padding: 30px;
          color: #17130f;
          background: linear-gradient(180deg, #f4efe4, #e8ddc8);
        }
        .verdict h3 {
          margin: 10px 0 0;
          font-size: clamp(46px, 5vw, 76px);
          line-height: 0.92;
          letter-spacing: 0;
          font-weight: 500;
        }
        .verdict p { color: rgba(20,17,15,0.62); line-height: 1.5; }
        .report-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0,1fr));
          gap: 13px;
        }
        .report-card {
          min-height: 170px;
          border: 1px solid var(--line);
          border-radius: 23px;
          padding: 18px;
          background: rgba(255,255,255,0.045);
        }
        .report-card em {
          display: block;
          margin-top: 8px;
          color: var(--amber);
          font-size: 11px;
          font-style: normal;
          font-weight: 860;
          letter-spacing: 0.15em;
          text-transform: uppercase;
        }
        .report-card.is-active {
          transform: translateZ(0) scale(1.06);
        }
        .close-card {
          justify-self: end;
          width: min(640px, 100%);
          border: 1px solid rgba(255,255,255,0.5);
          border-radius: 34px;
          padding: 36px;
          color: #17130f;
          background: linear-gradient(180deg, #f4efe4, #e8ddc8);
          box-shadow: 0 34px 120px rgba(0,0,0,0.38);
        }
        .close-card h3 {
          margin: 0;
          font-size: clamp(42px, 5vw, 72px);
          line-height: 0.94;
          letter-spacing: 0;
          font-weight: 520;
        }
        .close-card p { margin: 18px 0 0; color: rgba(20,17,15,0.64); line-height: 1.55; }
        .close-actions { display: flex; gap: 10px; margin-top: 25px; }
        .close-actions .pill { color: #17130f; border-color: rgba(20,17,15,0.18); background: rgba(255,255,255,0.5); }
        .close-actions .primary { color: var(--cream); background: #17130f; }
        .cursor {
          position: fixed;
          left: var(--cursor-x);
          top: var(--cursor-y);
          z-index: 50;
          width: 0;
          height: 0;
          opacity: 0;
          pointer-events: none;
          transform: translate3d(-2px, -2px, 0) scale(1);
          transition: opacity 180ms ease, transform 120ms ease;
          filter: drop-shadow(0 8px 14px rgba(0,0,0,0.45));
        }
        .cursor.is-visible { opacity: 1; }
        .cursor.is-pressed { transform: translate3d(-2px, -2px, 0) scale(0.88); }
        .cursor::before {
          content: "";
          position: absolute;
          width: 0;
          height: 0;
          border-left: 16px solid white;
          border-top: 11px solid transparent;
          border-bottom: 11px solid transparent;
          transform: rotate(42deg);
        }
        .cursor::after {
          content: "";
          position: absolute;
          left: 3px;
          top: 2px;
          width: 0;
          height: 0;
          border-left: 11px solid #020202;
          border-top: 7.5px solid transparent;
          border-bottom: 7.5px solid transparent;
          transform: rotate(42deg);
        }
        .dots {
          position: fixed;
          left: 50%;
          bottom: 31px;
          z-index: 20;
          display: flex;
          gap: 8px;
          transform: translateX(-50%);
        }
        .dots button {
          width: 34px;
          height: 9px;
          padding: 0;
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          background: rgba(243,238,228,0.08);
        }
        .dots button.active { background: linear-gradient(90deg, var(--orange), var(--amber), var(--teal)); }
        .footer {
          position: fixed;
          right: 28px;
          bottom: 22px;
          z-index: 20;
          display: flex;
          gap: 8px;
        }
        .footer button {
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 10px 14px;
          color: rgba(243,238,228,0.76);
          background: rgba(255,255,255,0.075);
          backdrop-filter: blur(16px);
        }
        .cursor-demo[data-stage="room"] .body,
        .cursor-demo[data-stage="report"] .body {
          grid-template-columns: 1fr;
          grid-template-rows: auto minmax(0,1fr);
          align-items: stretch;
          gap: 18px;
          padding: 22px 34px 30px;
        }
        .cursor-demo[data-stage="room"] .hero,
        .cursor-demo[data-stage="report"] .hero {
          display: grid;
          grid-template-columns: minmax(0,1fr) auto;
          align-items: end;
          column-gap: 24px;
        }
        .cursor-demo[data-stage="room"] .hero .kicker,
        .cursor-demo[data-stage="report"] .hero .kicker { grid-column: 1 / -1; }
        .cursor-demo[data-stage="room"] .hero h2,
        .cursor-demo[data-stage="report"] .hero h2 {
          max-width: 820px;
          font-size: clamp(34px, 3.7vw, 56px);
          line-height: 0.96;
        }
        .cursor-demo[data-stage="room"] .hero p,
        .cursor-demo[data-stage="report"] .hero p {
          max-width: 560px;
          margin: 0;
          font-size: 14px;
        }
        .cursor-demo[data-stage="room"] .stage-count,
        .cursor-demo[data-stage="report"] .stage-count { display: none; }
        @media (max-width: 1160px) {
          .body, .report, .build-canvas { grid-template-columns: 1fr; overflow: auto; }
          .room { grid-template-columns: 1fr; }
          .room .room-panel:first-child,
          .room .room-panel:last-child { display: none; }
          .signal-flow, .loop-board, .turn-stage { grid-template-columns: 1fr; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
        }
      `}</style>

      <section className="viewport">
        <div
          ref={registerTarget("seed-pill")}
          className={`seed target ${isActive("seed-pill") ? "is-active" : ""}`}
        >
          {stage.title}
        </div>

        <section className="shell" aria-label="Antigravity cursor-driven interview demo">
          <header className="top">
            <div className="brand">
              <div className="mark" />
              <div>
                <p className="kicker">Antigravity interview</p>
                <h1>Cursor-driven product demo</h1>
              </div>
            </div>
            <div className="progress">
              <div className="progress-row">
                <span>{stage.label}</span>
                <span>{stage.progress}%</span>
              </div>
              <div className="progress-bar" />
            </div>
          </header>

          <section className="body">
            <div className="hero">
              <p className="kicker">{stage.label}</p>
              <h2>{stage.title}</h2>
              <p>{stage.subtitle}</p>
              <span className="stage-count">{String(stageIndex + 1).padStart(2, "0")} / {String(STAGES.length).padStart(2, "0")}</span>
            </div>

            <div className="visual">
              {stage.id === "problem" && (
                <section className={`signal-flow ${hasActiveIn(PROBLEM_CARDS.map((card) => card.id)) ? "has-focus" : ""}`}>
                  {PROBLEM_CARDS.map((card) => (
                    <article
                      ref={registerTarget(card.id)}
                      className={`signal-card target ${isActive(card.id) ? "is-active" : ""}`}
                      key={card.id}
                    >
                      <span className="tag">{card.tag}</span>
                      <div>
                        <span className="label">Signal</span>
                        <strong>{card.title}</strong>
                        <p>{card.body}</p>
                      </div>
                    </article>
                  ))}
                </section>
              )}

              {stage.id === "loop" && (
                <section className={`loop-board ${hasActiveIn(LOOP_ITEMS.map(([id]) => id)) ? "has-focus" : ""}`}>
                  {LOOP_ITEMS.map(([id, title, body], index) => (
                    <article
                      ref={registerTarget(id)}
                      className={`loop-item target ${isActive(id) ? "is-active" : ""}`}
                      key={id}
                    >
                      <span className="number">{index + 1}</span>
                      <strong>{title}</strong>
                      <p>{body}</p>
                    </article>
                  ))}
                </section>
              )}

              {stage.id === "setup" && (
                <article className="brief">
                  <h3>Interview evidence brief</h3>
                  {BRIEF_ROWS.map(([id, label, value]) => (
                    <div
                      ref={registerTarget(id)}
                      className={`brief-row target ${isActive(id) ? "is-active" : ""}`}
                      key={id}
                    >
                      <span>{label}</span>
                      <span>{value}</span>
                    </div>
                  ))}
                </article>
              )}

              {stage.id === "build" && (
                <section className="build-canvas">
                  <aside className="assembly">
                    <span className="label">Assembly zone</span>
                    <h3>Constructing the assessment room</h3>
                    <div className="assembly-zone">cursor-selected pieces land here</div>
                  </aside>
                  <div className={`piece-grid ${hasActiveIn(BUILD_PIECES.map(([id]) => id)) ? "has-focus" : ""}`}>
                    {BUILD_PIECES.map(([id, title, body]) => (
                      <article
                        ref={registerTarget(id)}
                        className={`piece target ${isActive(id) ? "is-active" : ""}`}
                        key={id}
                      >
                        <span className="label">Room piece</span>
                        <strong>{title}</strong>
                        <p>{body}</p>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {stage.id === "turns" && (
                <section className="turn-sim">
                  <div className="turn-stage">
                    <aside
                      ref={registerTarget("turn-ai")}
                      className={`corner ai target ${isActive("turn-ai") ? "is-active" : ""}`}
                    >
                      <div className="avatar">AI</div>
                      <strong>AI corner</strong>
                      <p className="kicker">Interviewer turn</p>
                    </aside>
                    <div
                      ref={registerTarget("turn-center")}
                      className={`floor-center target ${isActive("turn-center") ? "is-active" : ""}`}
                    >
                      <div className="floor-rail"><span /><b>Turn</b><span /></div>
                      <div className="floor-note">The center rail explains who owns the floor without turning the room into a video call grid.</div>
                    </div>
                    <aside
                      ref={registerTarget("turn-candidate")}
                      className={`corner candidate target ${isActive("turn-candidate") ? "is-active" : ""}`}
                    >
                      <div className="avatar">SV</div>
                      <strong>Candidate corner</strong>
                      <p className="kicker">Candidate turn</p>
                    </aside>
                  </div>
                </section>
              )}

              {stage.id === "room" && (
                <section className="room">
                  <aside
                    ref={registerTarget("room-aura")}
                    className={`room-panel target ${isActive("room-aura") ? "is-active" : ""}`}
                  >
                    <span className="label">AI interviewer</span>
                    <h3>Presence</h3>
                    <div className="mini-aura">
                      <AgentAudioVisualizerAura size="md" state={auraState(stage.id)} color="#42D4E8" colorShift={0.22} themeMode="dark" />
                    </div>
                  </aside>
                  <section className="room-panel">
                    <div className="turn-line"><span /><b>Your turn</b><span /></div>
                    <div
                      ref={registerTarget("room-question")}
                      className={`question-card target ${isActive("room-question") ? "is-active" : ""}`}
                    >
                      <span className="label">Interviewer&apos;s question</span>
                      <p>How would you tell whether a conversion drop is real or instrumentation noise?</p>
                    </div>
                    <div
                      ref={registerTarget("room-live")}
                      className={`live-strip target ${isActive("room-live") ? "is-active" : ""}`}
                    >
                      <span className="label">Candidate answer live transcription</span>
                      I would compare upstream intent, backend order records, and client-side events before calling it a product issue.
                    </div>
                    <div
                      ref={registerTarget("room-controls")}
                      className={`controls target ${isActive("room-controls") ? "is-active" : ""}`}
                    >
                      <button className="pill" type="button">Repeat question</button>
                      <button className="pill" type="button">Need a moment</button>
                      <button className="pill" type="button">Fix last term</button>
                      <button className="pill" type="button">Full transcript</button>
                    </div>
                  </section>
                  <aside
                    ref={registerTarget("room-history")}
                    className={`room-panel target ${isActive("room-history") ? "is-active" : ""}`}
                  >
                    <span className="label">Candidate corner</span>
                    <h3>Camera and history</h3>
                    <div className="camera"><span>SV</span></div>
                    <div className="history">
                      <div className="history-card"><b>Latest turn</b><br />Q: Conversion drop or tracking noise?<br />A: Compare upstream and backend signals.</div>
                    </div>
                  </aside>
                </section>
              )}

              {stage.id === "report" && (
                <section className="report">
                  <article
                    ref={registerTarget("report-verdict")}
                    className={`verdict target ${isActive("report-verdict") ? "is-active" : ""}`}
                  >
                    <span className="label">Decision package</span>
                    <h3>Scoped yes, with two follow-ups.</h3>
                    <p>The report tells the hiring team what was actually tested, what held up, and where a human interviewer should go next.</p>
                  </article>
                  <div className={`report-grid ${hasActiveIn(REPORT_CARDS.map(([id]) => id)) ? "has-focus" : ""}`}>
                    {REPORT_CARDS.map(([id, title, value, body]) => (
                      <article
                        ref={registerTarget(id)}
                        className={`report-card target ${isActive(id) ? "is-active" : ""}`}
                        key={id}
                      >
                        <strong>{title}</strong>
                        <em>{value}</em>
                        <p>{body}</p>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {stage.id === "close" && (
                <article
                  ref={registerTarget("close-primary")}
                  className={`close-card target ${isActive("close-primary") ? "is-active" : ""}`}
                >
                  <h3>Show the loop. Then show the proof.</h3>
                  <p>The demo should make one thing undeniable: Antigravity does not automate interviews; it creates defensible hiring evidence from live judgment.</p>
                  <div className="close-actions">
                    <button className="pill primary" type="button">Open live room</button>
                    <button className="pill" type="button">Preview report</button>
                  </div>
                </article>
              )}
            </div>
          </section>
        </section>

        <div className={`cursor ${cursor.visible ? "is-visible" : ""} ${cursor.pressed ? "is-pressed" : ""}`} />
      </section>

      <nav className="dots" aria-label="Demo stages">
        {STAGES.map((item, index) => (
          <button
            aria-label={`Go to ${item.label}`}
            className={index === stageIndex ? "active" : ""}
            key={item.id}
            onClick={() => setStage(index)}
            type="button"
          />
        ))}
      </nav>

      <div className="footer">
        <button type="button" onClick={() => setStage(Math.max(0, stageIndex - 1))}>Previous</button>
        <button type="button" onClick={() => setIsPlaying((value) => !value)}>{isPlaying ? "Pause" : "Play"}</button>
        <button type="button" onClick={() => setStage(Math.min(STAGES.length - 1, stageIndex + 1))}>Next</button>
        <button type="button" onClick={() => setStage(0)}>Restart</button>
      </div>
    </main>
  );
}
