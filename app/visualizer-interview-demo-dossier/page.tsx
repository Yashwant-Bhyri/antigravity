"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StageId = "seed" | "claim" | "brief" | "assembly" | "turn" | "room" | "report" | "simulation" | "close";

type Stage = {
  id: StageId;
  label: string;
  title: string;
  subtitle: string;
  progress: number;
  duration: number;
};

const STAGES: Stage[] = [
  {
    id: "seed",
    label: "Start",
    title: "Start interview simulation",
    subtitle: "Observe a Product Analyst being assessed.",
    progress: 0,
    duration: 2200,
  },
  {
    id: "claim",
    label: "Problem",
    title: "Hiring still relies on weak evidence.",
    subtitle: "The claim enters. The room tests it. The report explains what held up.",
    progress: 12,
    duration: 5600,
  },
  {
    id: "brief",
    label: "Evidence",
    title: "The room knows the candidate before the first question.",
    subtitle: "Role context, resume evidence, and room goals become a live interview brief.",
    progress: 25,
    duration: 5200,
  },
  {
    id: "assembly",
    label: "Room assembly",
    title: "The room assembles itself.",
    subtitle: "Presence, turn ownership, question, transcript, controls, and history form around the interview.",
    progress: 38,
    duration: 6200,
  },
  {
    id: "turn",
    label: "Floor transfer",
    title: "The floor moves visibly. No guessing who is on.",
    subtitle: "The candidate sees the active question, owns their answer, and can pause, repeat, or correct without breaking the assessment.",
    progress: 52,
    duration: 7600,
  },
  {
    id: "room",
    label: "Room",
    title: "The live room makes the interview legible.",
    subtitle: "Turn ownership, anchored question, live transcript, candidate controls. Nothing hidden.",
    progress: 65,
    duration: 6000,
  },
  {
    id: "report",
    label: "Decision package",
    title: "The transcript becomes a verdict.",
    subtitle: "Every claim is bounded: what was tested, what held up under follow-up, and what a human should clarify next.",
    progress: 78,
    duration: 6600,
  },
  {
    id: "simulation",
    label: "Simulation",
    title: "Beyond questions. Real work. Real evidence.",
    subtitle: "Engineering candidates solve realistic incidents, run tests, and leave behind an evidence trail.",
    progress: 90,
    duration: 5200,
  },
  {
    id: "close",
    label: "Close",
    title: "One system. Two surfaces.",
    subtitle: "Voice interviews that produce defensible evidence. Engineering simulations that produce observable work.",
    progress: 100,
    duration: 5200,
  },
];

const BRIEF_ROWS = [
  ["Candidate", "S. V. S. Apparao"],
  ["Role", "Product Analyst"],
  ["Experience signal", "Launch analytics, dashboard quality, stakeholder decisions"],
  ["Claim under test", "Owned launch analytics for product rollout"],
  ["Live scenario", "A conversion drop appears, but instrumentation may be unreliable"],
  ["Session goal", "Observe reasoning, recovery, and judgment under follow-up pressure"],
];

const REPORT_CARDS = [
  ["Role fit", "Scoped yes", "Strong for product analytics with metric-ambiguity scenarios."],
  ["Strongest signal", "Judgment under follow-up", "Separated real conversion movement from instrumentation noise."],
  ["Resume claim calibration", "Mostly supported", "Launch analytics ownership verified; governance depth partially tested."],
  ["Recommended follow-ups", "2 actionable asks", "One governance question and one dashboard-quality question for the onsite loop."],
];

function auraState(stage: StageId): AgentState {
  if (stage === "turn") return "speaking";
  if (stage === "assembly" || stage === "report") return "thinking";
  return "idle";
}

function TypeIn({
  text,
  speed = 34,
  delay = 0,
  active = true,
  className = "",
}: {
  text: string;
  speed?: number;
  delay?: number;
  active?: boolean;
  className?: string;
}) {
  const [count, setCount] = useState(active ? 0 : text.length);
  const [doneAt, setDoneAt] = useState<number | null>(null);

  useEffect(() => {
    if (!active) {
      setCount(text.length);
      return;
    }

    setCount(0);
    setDoneAt(null);
    let frame = 0;
    let start: number | null = null;
    const duration = (text.length / speed) * 1000;

    const tick = (now: number) => {
      if (start === null) start = now + delay;
      if (now < start) {
        frame = window.requestAnimationFrame(tick);
        return;
      }
      const elapsed = now - start;
      const next = Math.min(text.length, Math.floor((elapsed / duration) * text.length));
      setCount(next);
      if (next < text.length) {
        frame = window.requestAnimationFrame(tick);
      } else {
        setDoneAt(performance.now());
      }
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [active, delay, speed, text]);

  const showCursor = active && (count < text.length || doneAt === null || performance.now() - doneAt < 1200);

  return (
    <span className={`type-in ${className}`}>
      {text.slice(0, count)}
      {showCursor && <span className="type-cursor" />}
    </span>
  );
}

export default function DossierInterviewDemoPage() {
  const [stageIndex, setStageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [cursorBeat, setCursorBeat] = useState(0);
  const stage = STAGES[stageIndex];

  useEffect(() => {
    if (!isPlaying || stageIndex === STAGES.length - 1) return;
    const timer = window.setTimeout(() => {
      setStageIndex((current) => Math.min(STAGES.length - 1, current + 1));
    }, stage.duration);
    return () => window.clearTimeout(timer);
  }, [isPlaying, stage.duration, stageIndex]);

  useEffect(() => {
    setCursorBeat(0);
    if (!isPlaying) return;
    const interval = window.setInterval(() => {
      setCursorBeat((beat) => (beat + 1) % 6);
    }, 1120);
    return () => window.clearInterval(interval);
  }, [isPlaying, stage.id]);

  const style = useMemo(
    () => ({ "--progress": `${stage.progress}%`, "--beat": cursorBeat } as CSSProperties),
    [cursorBeat, stage.progress],
  );

  const goTo = (index: number) => {
    setIsPlaying(false);
    setStageIndex(index);
  };

  return (
    <main className="claude-demo" data-stage={stage.id} data-beat={cursorBeat} style={style}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=DM+Sans:wght@400;500;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');

        .claude-demo {
          --black: #030303;
          --cream: #f3eee4;
          --paper: #e8ddc8;
          --ink: #15120f;
          --muted: rgba(243,238,228,0.62);
          --dim: rgba(243,238,228,0.38);
          --line: rgba(243,238,228,0.12);
          --crail: #c15f3c;
          --amber: #d9a24d;
          --teal: #42d4e8;
          --green: #7fe2ae;
          min-height: 100svh;
          overflow: hidden;
          color: var(--cream);
          font-family: "DM Sans", var(--font-geist-sans), Inter, ui-sans-serif, system-ui, sans-serif;
          background:
            radial-gradient(52rem 32rem at 75% 20%, rgba(193,95,60,0.13), transparent 66%),
            radial-gradient(48rem 28rem at 18% 82%, rgba(66,212,232,0.1), transparent 66%),
            linear-gradient(180deg, #090807, #020202);
        }
        .claude-demo::before {
          content: "";
          position: fixed;
          inset: -20%;
          pointer-events: none;
          opacity: 0.075;
          background:
            linear-gradient(115deg, transparent 0 38%, rgba(243,238,228,0.08) 38.2% 38.7%, transparent 39% 100%),
            radial-gradient(circle, rgba(243,238,228,0.34) 0 1px, transparent 1.35px);
          background-size: auto, 34px 34px;
          mask-image: radial-gradient(ellipse at center, black 0 56%, transparent 80%);
        }
        h1, h2, h3, p { margin-top: 0; }
        button { font: inherit; }
        .viewport {
          position: relative;
          z-index: 1;
          min-height: 100svh;
          display: grid;
          place-items: center;
          padding: 22px 32px 54px;
        }
        .seed-pill {
          display: none;
          position: relative;
          min-width: min(440px, calc(100vw - 70px));
          height: 72px;
          justify-content: center;
          align-items: center;
          gap: 11px;
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 0 28px;
          background: rgba(8,8,8,0.9);
          box-shadow: 0 32px 90px rgba(0,0,0,0.42);
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: 24px;
          font-weight: 700;
          animation: seed-breathe 2.4s ease-in-out infinite;
        }
        .seed-pill::before {
          content: "";
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--crail);
          box-shadow: 0 0 24px rgba(193,95,60,0.72);
        }
        .seed-pill::before { display: none; }
        .seed-wrap {
          display: none;
          justify-items: center;
          gap: 18px;
        }
        .claude-demo[data-stage="seed"] .seed-wrap { display: grid; }
        .seed-arrow {
          margin-left: 8px;
          color: var(--amber);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 18px;
        }
        .seed-sub {
          margin: 0;
          color: rgba(243,238,228,0.52);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .seed-pill::after {
          content: "";
          position: absolute;
          inset: -28px;
          border-radius: inherit;
          background: radial-gradient(circle, rgba(193,95,60,0.14), transparent 64%);
          z-index: -1;
          animation: seed-halo 2.4s ease-in-out infinite;
        }
        @keyframes seed-breathe {
          0%, 100% { transform: scale(0.99); }
          50% { transform: scale(1.015); }
        }
        @keyframes seed-halo {
          0%, 100% { opacity: 0.42; transform: scale(0.9); }
          50% { opacity: 1; transform: scale(1.1); }
        }
        .claude-demo[data-stage="seed"] .seed-pill { display: flex; }
        .shell {
          width: min(1440px, calc(100vw - 64px));
          height: min(820px, calc(100svh - 108px));
          min-height: 620px;
          display: grid;
          grid-template-rows: auto 1fr;
          overflow: hidden;
          border: 1px solid var(--line);
          border-radius: 34px;
          background:
            radial-gradient(46rem 26rem at 78% 16%, rgba(193,95,60,0.1), transparent 62%),
            rgba(5,5,5,0.91);
          box-shadow: 0 44px 140px rgba(0,0,0,0.56), inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .claude-demo[data-stage="seed"] .shell { display: none; }
        .top {
          display: grid;
          grid-template-columns: minmax(0,1fr) 430px;
          gap: 28px;
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
          background: radial-gradient(circle at 36% 34%, rgba(193,95,60,0.62), rgba(193,95,60,0.08) 62%, rgba(0,0,0,0.84));
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.1), 0 0 34px rgba(193,95,60,0.15);
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
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 870;
          letter-spacing: 0.25em;
          text-transform: uppercase;
        }
        .brand h1 { margin: 5px 0 0; font-size: 26px; line-height: 1.05; font-weight: 620; }
        .chapters { display: grid; gap: 10px; }
        .chapter-labels {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          color: rgba(243,238,228,0.44);
          font-size: 9px;
          font-weight: 830;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .chapter-bar { height: 5px; border-radius: 999px; overflow: hidden; background: rgba(243,238,228,0.1); }
        .chapter-bar::after {
          content: "";
          display: block;
          width: var(--progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--crail), var(--amber), var(--teal), var(--green));
          transition: width 520ms ease;
        }
        .body {
          min-height: 0;
          display: grid;
          grid-template-columns: minmax(360px, 0.8fr) minmax(650px, 1.2fr);
          gap: 34px;
          align-items: center;
          padding: 40px 42px;
          overflow: hidden;
          animation: stage-enter 440ms cubic-bezier(.16, 1, .3, 1) both;
        }
        @keyframes stage-enter {
          from { opacity: 0; transform: translateY(14px) scale(0.99); filter: blur(2px); }
          to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
        }
        .hero h2 {
          max-width: 700px;
          margin: 14px 0 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: clamp(48px, 6vw, 86px);
          line-height: 0.92;
          letter-spacing: 0;
          font-weight: 700;
        }
        .hero p {
          max-width: 610px;
          margin: 24px 0 0;
          color: var(--muted);
          font-size: 16px;
          line-height: 1.55;
        }
        .visual { min-height: 0; display: grid; align-content: center; gap: 16px; }
        .claim-chain {
          display: grid;
          justify-items: center;
          gap: 12px;
        }
        .chain-card {
          width: min(640px, 100%);
          border: 1px solid var(--line);
          border-radius: 26px;
          padding: 22px 24px;
          background: rgba(255,255,255,0.045);
          transform: translateY(0);
          opacity: 0.48;
          transition: opacity 320ms ease, transform 380ms cubic-bezier(.2,.86,.18,1), border-color 320ms ease, box-shadow 320ms ease;
        }
        .chain-card strong {
          display: block;
          color: white;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: clamp(24px, 2.4vw, 34px);
          line-height: 1.02;
          letter-spacing: 0;
        }
        .chain-card p { margin: 12px 0 0; color: var(--muted); line-height: 1.45; }
        .chain-card:nth-child(1) { animation: chain-in 5.6s ease infinite; animation-delay: 0s; }
        .chain-card:nth-child(3) { animation: chain-in 5.6s ease infinite; animation-delay: 1.3s; }
        .chain-card:nth-child(5) { animation: chain-in 5.6s ease infinite; animation-delay: 3.2s; }
        .chain-card:nth-child(5) { border-color: rgba(127,226,174,0.24); }
        @keyframes chain-in {
          0%, 100% { opacity: 0.5; transform: translateY(0) scale(1); box-shadow: none; }
          18%, 45% { opacity: 1; transform: translateY(-6px) scale(1.025); border-color: rgba(243,238,228,0.34); box-shadow: 0 26px 70px rgba(0,0,0,0.32); }
        }
        .chain-arrow {
          width: 2px;
          height: 40px;
          border-radius: 999px;
          background: linear-gradient(180deg, var(--crail), var(--amber), var(--teal));
          transform-origin: top;
          animation: arrow-draw 5.6s ease infinite;
        }
        .chain-arrow.second { animation-delay: 1.8s; }
        @keyframes arrow-draw {
          0%, 15%, 100% { opacity: 0.18; transform: scaleY(0.2); }
          30%, 60% { opacity: 1; transform: scaleY(1); }
        }
        .brief {
          max-width: 780px;
          justify-self: end;
          border: 1px solid rgba(255,255,255,0.58);
          border-radius: 32px;
          padding: 30px;
          color: var(--ink);
          background: linear-gradient(180deg, var(--cream), var(--paper));
          box-shadow: 0 36px 120px rgba(0,0,0,0.38);
          animation: paper-in 520ms cubic-bezier(.2,.86,.18,1) both;
        }
        @keyframes paper-in {
          from { opacity: 0; transform: translateX(80px); }
          to { opacity: 1; transform: translateX(0); }
        }
        .brief h3 { margin: 0 0 18px; font-size: 27px; }
        .brief-head {
          display: flex;
          justify-content: space-between;
          gap: 20px;
          align-items: start;
          margin-bottom: 14px;
        }
        .brief-head h3 {
          margin: 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: 38px;
          line-height: .94;
          font-weight: 700;
        }
        .brief-aura {
          display: grid;
          justify-items: center;
          gap: 4px;
          color: rgba(20,17,15,0.54);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 8px;
          font-weight: 800;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .brief-row {
          display: grid;
          grid-template-columns: 180px minmax(0,1fr);
          gap: 20px;
          padding: 15px 0;
          border-top: 1px solid rgba(20,17,15,0.12);
          filter: blur(3px);
          opacity: 0.65;
          animation: scan-row 5.2s ease infinite;
        }
        .brief-row:nth-child(2) { animation-delay: 0.2s; }
        .brief-row:nth-child(3) { animation-delay: 0.55s; }
        .brief-row:nth-child(4) { animation-delay: 0.9s; }
        .brief-row:nth-child(5) { animation-delay: 1.25s; }
        .brief-row:nth-child(6) { animation-delay: 1.6s; }
        .brief-row:nth-child(7) { animation-delay: 1.95s; }
        @keyframes scan-row {
          0%, 100% { filter: blur(3px); opacity: 0.62; background: transparent; }
          12%, 28% { filter: blur(0); opacity: 1; background: rgba(217,162,77,0.08); }
        }
        .brief-row span:first-child {
          color: rgba(20,17,15,0.48);
          font-size: 11px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .brief-row span:last-child { font-size: 18px; font-weight: 760; line-height: 1.28; }
        .assembly-card {
          width: min(760px, 100%);
          justify-self: center;
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 30px;
          padding: 26px;
          background: rgba(0,0,0,0.6);
          box-shadow: 0 34px 110px rgba(0,0,0,0.38), inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .terminal-lines { display: grid; gap: 12px; margin: 24px 0; }
        .assembly-room {
          display: grid;
          grid-template-columns: 150px minmax(0,1fr);
          gap: 18px;
          align-items: center;
          margin: 18px 0 22px;
        }
        .assembly-aura {
          min-height: 168px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(217,162,77,0.18);
          border-radius: 28px;
          background:
            radial-gradient(130px at 50% 45%, rgba(217,162,77,0.16), transparent 70%),
            #030303;
          animation: assembly-aura-in 620ms cubic-bezier(.16,1,.3,1) both;
        }
        @keyframes assembly-aura-in {
          from { opacity: 0; transform: scale(.8); }
          to { opacity: 1; transform: scale(1); }
        }
        .assembly-map {
          display: grid;
          gap: 10px;
        }
        .assembly-piece {
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 18px;
          padding: 12px 14px;
          background: rgba(255,255,255,0.045);
          color: rgba(243,238,228,0.78);
          opacity: 0;
          transform: translateX(18px);
          animation: piece-in 420ms cubic-bezier(.16, 1, .3, 1) both;
        }
        .assembly-piece strong {
          display: block;
          color: white;
          font-size: 15px;
          line-height: 1.15;
        }
        .assembly-piece span {
          display: block;
          margin-top: 5px;
          color: rgba(243,238,228,.54);
          font-size: 13px;
          line-height: 1.3;
        }
        .assembly-piece:nth-child(1) { animation-delay: .55s; }
        .assembly-piece:nth-child(2) { animation-delay: .9s; }
        .assembly-piece:nth-child(3) { animation-delay: 1.25s; }
        .assembly-piece:nth-child(4) { animation-delay: 1.6s; }
        @keyframes piece-in {
          to { opacity: 1; transform: translateX(0); }
        }
        .terminal-line {
          display: grid;
          grid-template-columns: 12px minmax(0,1fr);
          gap: 11px;
          align-items: center;
          color: rgba(243,238,228,0.78);
          font-size: 15px;
          min-height: 24px;
        }
        .terminal-line::before {
          content: "";
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--green);
          box-shadow: 0 0 22px rgba(127,226,174,0.42);
        }
        .assembly-bottom {
          display: grid;
          grid-template-columns: 1fr 140px;
          gap: 18px;
          align-items: center;
        }
        .build-bar { height: 8px; border-radius: 999px; overflow: hidden; background: rgba(243,238,228,0.1); }
        .build-bar::after {
          content: "";
          display: block;
          height: 100%;
          width: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--crail), var(--amber), var(--teal), var(--green));
          transform-origin: left;
          animation: build-progress 6.2s ease both;
        }
        @keyframes build-progress {
          0% { transform: scaleX(0.06); }
          86% { transform: scaleX(0.84); }
          100% { transform: scaleX(1); }
        }
        .turn-theater {
          display: grid;
          grid-template-columns: 190px minmax(0,1fr) 190px;
          gap: 18px;
          border: 1px solid var(--line);
          border-radius: 34px;
          padding: 22px;
          background:
            radial-gradient(34rem 20rem at 18% 42%, rgba(193,95,60,0.12), transparent 62%),
            radial-gradient(34rem 20rem at 82% 58%, rgba(66,212,232,0.13), transparent 62%),
            rgba(255,255,255,0.035);
        }
        .turn-side, .turn-main {
          border: 1px solid var(--line);
          border-radius: 26px;
          background: rgba(0,0,0,0.48);
          padding: 18px;
        }
        .turn-side { display: grid; align-content: center; justify-items: center; gap: 14px; min-height: 380px; text-align: center; }
        .turn-side.ai { animation: ai-turn-glow 7.6s ease infinite; }
        .turn-side.candidate { animation: candidate-turn-glow 7.6s ease infinite; }
        @keyframes ai-turn-glow {
          0%, 44% { border-color: rgba(193,95,60,0.4); box-shadow: 0 0 36px rgba(193,95,60,0.14); opacity: 1; }
          54%, 100% { border-color: var(--line); box-shadow: none; opacity: 0.58; }
        }
        @keyframes candidate-turn-glow {
          0%, 44% { border-color: var(--line); box-shadow: none; opacity: 0.58; }
          54%, 100% { border-color: rgba(66,212,232,0.42); box-shadow: 0 0 36px rgba(66,212,232,0.14); opacity: 1; }
        }
        .candidate-avatar {
          display: grid;
          width: 78px;
          height: 78px;
          place-items: center;
          border-radius: 25px;
          background: rgba(66,212,232,0.1);
          font-weight: 850;
          font-size: 22px;
        }
        .turn-main {
          display: grid;
          grid-template-rows: auto 1fr auto;
          gap: 16px;
        }
        .turn-rail {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          gap: 14px;
          align-items: center;
        }
        .turn-rail span {
          height: 3px;
          border-radius: 999px;
          background: rgba(243,238,228,0.14);
        }
        .turn-rail span:first-child { animation: rail-ai 7.6s ease infinite; }
        .turn-rail span:last-child { animation: rail-candidate 7.6s ease infinite; }
        @keyframes rail-ai {
          0%, 48% { background: linear-gradient(90deg, var(--crail), var(--amber)); box-shadow: 0 0 26px rgba(193,95,60,0.18); }
          58%, 100% { background: rgba(243,238,228,0.14); box-shadow: none; }
        }
        @keyframes rail-candidate {
          0%, 48% { background: rgba(243,238,228,0.14); box-shadow: none; }
          58%, 100% { background: linear-gradient(90deg, var(--teal), var(--green)); box-shadow: 0 0 26px rgba(66,212,232,0.18); }
        }
        .turn-pill {
          border: 1px solid rgba(243,238,228,0.18);
          border-radius: 999px;
          padding: 10px 16px;
          background: #050505;
          color: white;
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .question-card, .answer-card {
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 24px;
          padding: 28px;
          background: #000;
        }
        .question-card {
          min-height: 205px;
          animation: question-pulse 2.6s ease-in-out infinite;
        }
        @keyframes question-pulse {
          0%, 100% { box-shadow: 0 0 28px rgba(193,95,60,0.12), inset 0 0 0 1px rgba(255,255,255,0.02); }
          50% { box-shadow: 0 0 52px rgba(193,95,60,0.22), inset 0 0 0 1px rgba(255,255,255,0.02); }
        }
        .label {
          display: block;
          margin-bottom: 14px;
          color: rgba(243,238,228,0.48);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
        .question-card p, .answer-card p {
          margin: 0;
          color: white;
          font-size: clamp(28px, 3vw, 45px);
          line-height: 1.03;
          font-weight: 850;
          letter-spacing: 0;
        }
        .answer-card {
          min-height: 128px;
          border-color: rgba(66,212,232,0.18);
        }
        .answer-card p {
          color: rgba(243,238,228,0.76);
          font-size: 20px;
          line-height: 1.35;
          font-weight: 520;
        }
        .room-artifact {
          display: grid;
          grid-template-columns: 240px minmax(540px,1fr) 240px;
          gap: 14px;
          border: 1px solid var(--line);
          border-radius: 31px;
          padding: 16px;
          background: rgba(0,0,0,0.46);
        }
        .room-panel {
          position: relative;
          min-width: 0;
          border: 1px solid var(--line);
          border-radius: 24px;
          padding: 16px;
          background: rgba(0,0,0,0.62);
        }
        .room-panel h3 { margin: 0; font-size: 19px; }
        .mini-aura, .mini-camera {
          min-height: 210px;
          display: grid;
          place-items: center;
          margin-top: 15px;
          border-radius: 20px;
          background: #020202;
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.08);
        }
        .mini-aura {
          min-height: 292px;
          background:
            radial-gradient(180px at 50% 45%, rgba(193,95,60,0.10), transparent 70%),
            #020202;
        }
        .room-panel:first-child {
          box-shadow: inset -18px 0 48px rgba(193,95,60,0.045);
        }
        .room-panel:last-child {
          box-shadow: inset 18px 0 48px rgba(66,212,232,0.045);
        }
        .mini-camera span {
          display: grid;
          width: 74px;
          height: 74px;
          place-items: center;
          border-radius: 24px;
          background: rgba(66,212,232,0.1);
          font-weight: 850;
        }
        .annotation {
          position: absolute;
          z-index: 5;
          max-width: 210px;
          border: 1px solid rgba(243,238,228,0.16);
          border-radius: 999px;
          padding: 9px 12px;
          color: rgba(243,238,228,0.78);
          background: rgba(0,0,0,0.74);
          font-size: 11px;
          line-height: 1.25;
          opacity: 0;
          transform: translateY(10px);
          animation: annotate-in 520ms ease both;
        }
        .annotation.left { left: 18px; bottom: 18px; animation-delay: 0.6s; }
        .annotation.center { left: 28px; bottom: 88px; animation-delay: 1s; }
        .annotation.right { left: 18px; bottom: 18px; animation-delay: 1.4s; }
        @keyframes annotate-in {
          to { opacity: 1; transform: translateY(0); }
        }
        .room-question {
          min-height: 210px;
          display: grid;
          align-content: center;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 24px;
          padding: 28px;
          background: #000;
          box-shadow: 0 0 32px rgba(193,95,60,0.14);
        }
        .room-question p {
          margin: 0;
          color: white;
          font-size: clamp(30px, 2.8vw, 44px);
          line-height: 1.02;
          font-weight: 850;
        }
        .answer-strip {
          margin-top: 13px;
          border: 1px solid rgba(66,212,232,0.18);
          border-radius: 18px;
          padding: 13px 15px;
          color: rgba(243,238,228,0.68);
          font-size: 14px;
        }
        .controls {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 14px;
        }
        .pill {
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 10px 13px;
          color: rgba(243,238,228,0.76);
          background: rgba(255,255,255,0.06);
        }
        .controls .pill {
          opacity: 0;
          transform: translateY(8px);
          animation: control-in 420ms ease both;
        }
        .controls .pill:nth-child(1) { animation-delay: 1.1s; }
        .controls .pill:nth-child(2) { animation-delay: 1.18s; }
        .controls .pill:nth-child(3) { animation-delay: 1.26s; }
        .controls .pill:nth-child(4) { animation-delay: 1.34s; }
        @keyframes control-in {
          to { opacity: 1; transform: translateY(0); }
        }
        .report-board {
          display: grid;
          grid-template-columns: 0.78fr 1.22fr;
          gap: 18px;
          align-items: stretch;
        }
        .verdict {
          position: relative;
          min-height: 430px;
          border: 1px solid rgba(255,255,255,0.52);
          border-radius: 32px;
          padding: 30px;
          color: var(--ink);
          background: linear-gradient(180deg, var(--cream), var(--paper));
          animation: verdict-in 520ms cubic-bezier(.2,.86,.18,1) both;
        }
        @keyframes verdict-in {
          from { opacity: 0; transform: translateX(-40px); }
          to { opacity: 1; transform: translateX(0); }
        }
        .verdict h3 {
          margin: 10px 0 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: clamp(48px, 5vw, 74px);
          line-height: 0.92;
          letter-spacing: 0;
          font-weight: 700;
        }
        .seal {
          position: absolute;
          right: 24px;
          top: 24px;
          width: 48px;
          height: 48px;
          display: grid;
          place-items: center;
          border-radius: 999px;
          color: var(--ink);
          background: radial-gradient(circle at 45% 38%, #f8d68b, var(--amber) 52%, #8e5d23);
          box-shadow: inset 0 0 0 1px rgba(20,17,15,0.2), 0 10px 26px rgba(20,17,15,0.18);
          font-family: "JetBrains Mono", ui-monospace, monospace;
          font-size: 16px;
          font-weight: 900;
          animation: seal-in 520ms .52s cubic-bezier(.16, 1, .3, 1) both;
        }
        @keyframes seal-in {
          from { opacity: 0; transform: rotate(-18deg) scale(0); }
          70% { opacity: 1; transform: rotate(4deg) scale(1.12); }
          to { transform: rotate(0) scale(1); }
        }
        .verdict p { color: rgba(20,17,15,0.62); line-height: 1.5; }
        .report-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0,1fr));
          gap: 13px;
        }
        .report-card {
          min-height: 185px;
          border: 1px solid var(--line);
          border-radius: 23px;
          padding: 19px;
          background: rgba(255,255,255,0.045);
          opacity: 0;
          transform: translateY(16px);
          animation: report-in 440ms ease both;
        }
        .report-card:nth-child(1) { animation-delay: 0.6s; }
        .report-card:nth-child(2) { animation-delay: 0.9s; }
        .report-card:nth-child(3) { animation-delay: 1.2s; }
        .report-card:nth-child(4) { animation-delay: 1.5s; }
        @keyframes report-in {
          to { opacity: 1; transform: translateY(0); }
        }
        .report-card strong { display: block; color: white; font-size: 21px; line-height: 1.1; }
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
        .report-card p { margin: 15px 0 0; color: var(--muted); line-height: 1.45; }
        .terminal {
          width: min(760px, 100%);
          justify-self: end;
          overflow: hidden;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 28px;
          background:
            repeating-linear-gradient(180deg, transparent 0 8px, rgba(255,255,255,0.018) 8px 9px),
            #080808;
          box-shadow: 0 34px 120px rgba(0,0,0,0.42);
          animation: terminal-in 520ms cubic-bezier(.2,.86,.18,1) both;
        }
        @keyframes terminal-in {
          from { opacity: 0; transform: translateX(80px); }
          to { opacity: 1; transform: translateX(0); }
        }
        .terminal-top {
          display: flex;
          gap: 7px;
          align-items: center;
          border-bottom: 1px solid var(--line);
          padding: 14px 16px;
          color: var(--muted);
          font-family: var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 13px;
        }
        .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--crail); }
        .dot:nth-child(2) { background: var(--amber); }
        .dot:nth-child(3) { background: var(--green); margin-right: 10px; }
        .terminal-body {
          padding: 24px;
          color: rgba(243,238,228,0.78);
          font-family: var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 15px;
          line-height: 1.7;
        }
        .fail { color: rgba(193,95,60,0.94); }
        .pass { color: rgba(127,226,174,0.84); }
        .highlight-line {
          display: block;
          margin: 6px -10px;
          border-left: 2px solid rgba(193,95,60,0.48);
          padding: 3px 10px;
          background: rgba(193,95,60,0.14);
          color: #ffd3c8;
        }
        .terminal-caption {
          padding: 0 24px 24px;
          color: rgba(243,238,228,0.72);
          font-size: 14px;
        }
        .close-card {
          justify-self: end;
          width: min(760px, 100%);
          border: 1px solid rgba(255,255,255,0.5);
          border-radius: 34px;
          padding: 36px;
          color: var(--ink);
          background: linear-gradient(180deg, var(--cream), var(--paper));
          box-shadow: 0 34px 120px rgba(0,0,0,0.38);
          animation: close-in 540ms ease both;
        }
        @keyframes close-in {
          from { opacity: 0; transform: scale(0.96); }
          to { opacity: 1; transform: scale(1); }
        }
        .close-card h3 {
          margin: 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: clamp(44px, 5vw, 74px);
          line-height: 0.94;
          letter-spacing: 0;
          font-weight: 520;
        }
        .close-grid {
          display: grid;
          grid-template-columns: 128px minmax(0,1fr);
          gap: 24px;
          align-items: center;
        }
        .close-aura {
          min-height: 142px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(20,17,15,0.12);
          border-radius: 28px;
          background: rgba(20,17,15,0.92);
        }
        .surface-list {
          display: grid;
          gap: 10px;
          margin-top: 22px;
        }
        .surface-row {
          border-top: 1px solid rgba(20,17,15,0.12);
          padding-top: 10px;
          color: rgba(20,17,15,0.7);
          font-size: 15px;
          line-height: 1.35;
        }
        .surface-row strong {
          display: block;
          color: var(--ink);
          font-size: 16px;
          margin-bottom: 3px;
        }
        .close-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }
        .close-actions .pill { color: var(--ink); border-color: rgba(20,17,15,0.18); background: rgba(255,255,255,0.5); }
        .close-actions .primary {
          color: var(--cream);
          background: var(--ink);
          animation: cta-pulse 2.4s ease-in-out infinite;
        }
        @keyframes cta-pulse {
          0%, 100% { box-shadow: 0 0 0 rgba(193,95,60,0); }
          50% { box-shadow: 0 0 28px rgba(193,95,60,0.22); }
        }
        .type-in { white-space: pre-wrap; }
        .type-cursor {
          display: inline-block;
          width: 0.08em;
          height: 0.95em;
          margin-left: 0.08em;
          vertical-align: -0.08em;
          background: currentColor;
          animation: blink 0.8s step-end infinite;
        }
        @keyframes blink { 50% { opacity: 0; } }
        .cursor {
          position: fixed;
          z-index: 50;
          width: 0;
          height: 0;
          pointer-events: none;
          opacity: 0;
          filter: drop-shadow(0 8px 14px rgba(0,0,0,0.45));
          animation: cursor-seed 1.7s cubic-bezier(.22,.8,.18,1) infinite;
        }
        .cursor::before {
          content: "";
          position: absolute;
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
          border-left: 11px solid #020202;
          border-top: 7.5px solid transparent;
          border-bottom: 7.5px solid transparent;
          transform: rotate(42deg);
        }
        .claude-demo[data-stage="seed"] .cursor { opacity: 1; animation-name: cursor-seed; }
        .claude-demo[data-stage="claim"] .cursor { opacity: 1; animation: cursor-claim 5.6s cubic-bezier(.22,.8,.18,1) infinite; }
        .claude-demo[data-stage="brief"] .cursor { opacity: 1; animation: cursor-brief 5.2s cubic-bezier(.22,.8,.18,1) infinite; }
        .claude-demo[data-stage="turn"] .cursor { opacity: 1; animation: cursor-turn 7.6s cubic-bezier(.22,.8,.18,1) infinite; }
        .claude-demo[data-stage="report"] .cursor { opacity: 1; animation: cursor-report 6.6s cubic-bezier(.22,.8,.18,1) infinite; }
        .claude-demo[data-stage="simulation"] .cursor { opacity: 1; animation: cursor-sim 5.2s cubic-bezier(.22,.8,.18,1) infinite; }
        .claude-demo[data-stage="close"] .cursor { opacity: 1; animation: cursor-close 5.2s cubic-bezier(.22,.8,.18,1) infinite; }
        @keyframes cursor-seed {
          0% { left: calc(50% + 130px); top: calc(50% + 8px); transform: scale(1); }
          70%, 100% { left: 50%; top: 50%; transform: scale(0.92); }
        }
        @keyframes cursor-claim {
          0%, 24% { left: calc(50% + 338px); top: calc(50% - 168px); }
          38%, 58% { left: calc(50% + 338px); top: calc(50% - 4px); }
          72%, 100% { left: calc(50% + 338px); top: calc(50% + 174px); }
        }
        @keyframes cursor-brief {
          0% { left: calc(50% + 500px); top: calc(50% - 214px); }
          20% { left: calc(50% + 285px); top: calc(50% - 168px); }
          42% { left: calc(50% + 285px); top: calc(50% - 40px); }
          68%, 100% { left: calc(50% + 285px); top: calc(50% + 126px); }
        }
        @keyframes cursor-turn {
          0%, 22% { left: calc(50% + 50px); top: calc(50% - 168px); }
          44%, 58% { left: calc(50% + 50px); top: calc(50% - 8px); }
          76%, 100% { left: calc(50% + 55px); top: calc(50% + 160px); }
        }
        @keyframes cursor-report {
          0%, 26% { left: calc(50% - 50px); top: calc(50% + 10px); }
          45%, 62% { left: calc(50% + 445px); top: calc(50% - 110px); }
          78%, 100% { left: calc(50% + 452px); top: calc(50% + 114px); }
        }
        @keyframes cursor-sim {
          0%, 38% { left: calc(50% + 460px); top: calc(50% + 12px); }
          70%, 100% { left: calc(50% + 360px); top: calc(50% + 92px); }
        }
        @keyframes cursor-close {
          0%, 100% { left: calc(50% + 330px); top: calc(50% + 152px); }
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
        .claude-demo[data-stage="seed"] .dots,
        .claude-demo[data-stage="seed"] .footer { display: none; }
        .dots button {
          width: 34px;
          height: 9px;
          padding: 0;
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          background: rgba(243,238,228,0.08);
        }
        .dots button.active { background: linear-gradient(90deg, var(--crail), var(--amber), var(--teal)); }
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
          width: 44px;
          height: 44px;
          padding: 0;
          color: rgba(243,238,228,0.76);
          background: rgba(255,255,255,0.075);
          backdrop-filter: blur(16px);
          font-size: 18px;
        }
        @media (max-width: 1120px) {
          .body, .report-board { grid-template-columns: 1fr; overflow: auto; }
          .room-artifact, .turn-theater { grid-template-columns: 1fr; }
          .room-artifact .room-panel:first-child,
          .room-artifact .room-panel:last-child { display: none; }
          .hero h2 { font-size: clamp(40px, 8vw, 68px); }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
        }
      `}</style>

      <section className="viewport">
        <div className="seed-wrap">
          <div className="seed-pill">
            <AgentAudioVisualizerAura size="icon" state="idle" color="#C15F3C" colorShift={0.12} themeMode="dark" />
            <span>{stage.title}</span>
            <span className="seed-arrow">→</span>
          </div>
          <p className="seed-sub">{stage.subtitle}</p>
        </div>
        <section className="shell" aria-label="Dossier-led Antigravity interview simulation">
          <header className="top">
            <div className="brand">
              <div className="mark" />
              <div>
                <p className="kicker">Antigravity</p>
                <h1>Interview simulation</h1>
              </div>
            </div>
            <div className="chapters">
              <div className="chapter-labels">
                <span>Problem</span>
                <span>Evidence</span>
                <span>Assembly</span>
                <span>Floor</span>
                <span>Room</span>
                <span>Verdict</span>
                <span>Simulation</span>
              </div>
              <div className="chapter-bar" />
            </div>
          </header>

          <section className="body" key={stage.id}>
            <div className="hero">
              <p className="kicker">{stage.label}</p>
              <h2>{stage.title}</h2>
              {stage.subtitle && <p>{stage.subtitle}</p>}
            </div>

            <div className="visual">
              {stage.id === "claim" && (
                <section className="claim-chain">
                  <article className="chain-card">
                    <span className="label">Resume claim</span>
                    <strong>Owned launch analytics</strong>
                    <p>Promising on paper. Still not proof of live judgment.</p>
                  </article>
                  <div className="chain-arrow" />
                  <article className="chain-card">
                    <span className="label">Live question</span>
                    <strong>
                      <TypeIn
                        active={stage.id === "claim"}
                        delay={1450}
                        speed={34}
                        text="How would you separate a real conversion drop from instrumentation noise?"
                      />
                    </strong>
                  </article>
                  <div className="chain-arrow second" />
                  <article className="chain-card">
                    <span className="label">Decision evidence</span>
                    <strong>Scoped yes · 2 follow-ups</strong>
                    <p>What was tested, what held up, and what to clarify next.</p>
                  </article>
                </section>
              )}

              {stage.id === "brief" && (
                <article className="brief">
                  <div className="brief-head">
                    <h3>Interview brief</h3>
                    <div className="brief-aura">
                      <AgentAudioVisualizerAura size="sm" state="thinking" color="#D9A24D" colorShift={0.12} themeMode="dark" />
                      <span>Preparing room</span>
                    </div>
                  </div>
                  {BRIEF_ROWS.map(([label, value]) => (
                    <div className="brief-row" key={label}>
                      <span>{label}</span>
                      <span>{value}</span>
                    </div>
                  ))}
                </article>
              )}

              {stage.id === "assembly" && (
                <article className="assembly-card">
                  <span className="label">Assembling room</span>
                  <div className="assembly-room">
                    <div className="assembly-aura">
                      <AgentAudioVisualizerAura size="md" state="thinking" color="#D9A24D" colorShift={0.16} themeMode="dark" />
                    </div>
                    <div className="assembly-map">
                      <div className="assembly-piece">
                        <strong>AI interviewer presence</strong>
                        <span>Abstract Aura, no fake human face.</span>
                      </div>
                      <div className="assembly-piece">
                        <strong>Turn rail and floor ownership</strong>
                        <span>Candidate knows when to listen, speak, pause, or recover.</span>
                      </div>
                      <div className="assembly-piece">
                        <strong>Anchored question and live answer</strong>
                        <span>The task stays stable while transcription moves below it.</span>
                      </div>
                      <div className="assembly-piece">
                        <strong>History and report contract</strong>
                        <span>Committed turns resolve into defensible hiring evidence.</span>
                      </div>
                    </div>
                  </div>
                  <div className="assembly-bottom">
                    <div className="build-bar" />
                    <span className="label">Room ready</span>
                  </div>
                </article>
              )}

              {stage.id === "turn" && (
                <section className="turn-theater">
                  <aside className="turn-side ai">
                    <AgentAudioVisualizerAura size="md" state={auraState(stage.id)} color="#C15F3C" colorShift={0.22} themeMode="dark" />
                    <strong>AI interviewer</strong>
                  </aside>
                  <section className="turn-main">
                    <div className="turn-rail"><span /><b className="turn-pill">Turn</b><span /></div>
                    <div className="question-card">
                      <span className="label">AI turn</span>
                      <p>
                        <TypeIn
                          active={stage.id === "turn"}
                          delay={400}
                          speed={38}
                          text="How would you separate a real conversion drop from instrumentation noise?"
                        />
                      </p>
                    </div>
                    <div className="answer-card">
                      <span className="label">Answering</span>
                      <p>
                        <TypeIn
                          active={stage.id === "turn"}
                          delay={4050}
                          speed={42}
                          text="I would compare raw event volume, schema changes, funnel step counts, and a holdout metric before calling it a product regression."
                        />
                      </p>
                    </div>
                  </section>
                  <aside className="turn-side candidate">
                    <div className="candidate-avatar">SV</div>
                    <strong>Candidate</strong>
                  </aside>
                </section>
              )}

              {stage.id === "room" && (
                <section className="room-artifact">
                  <aside className="room-panel">
                    <span className="label">AI interviewer</span>
                    <h3>Presence</h3>
                    <div className="mini-aura">
                      <AgentAudioVisualizerAura size="lg" state="speaking" color="#C15F3C" colorShift={0.18} themeMode="dark" />
                    </div>
                    <div className="annotation left">AI presence, never a fake face</div>
                  </aside>
                  <section className="room-panel">
                    <div className="turn-rail"><span /><b className="turn-pill">AI turn</b><span /></div>
                    <div className="room-question">
                      <span className="label">Interviewer&apos;s question</span>
                      <p>How would you separate a real conversion drop from instrumentation noise?</p>
                    </div>
                    <div className="annotation center">Question anchored; transcript below</div>
                    <div className="answer-strip">
                      <span className="label">Answering</span>
                      I would approach this by first cross-referencing the raw event-
                    </div>
                    <div className="controls">
                      <button className="pill" type="button">Repeat question</button>
                      <button className="pill" type="button">Need a moment</button>
                      <button className="pill" type="button">Fix last term</button>
                      <button className="pill" type="button">Full transcript</button>
                    </div>
                  </section>
                  <aside className="room-panel">
                    <span className="label">Candidate corner</span>
                    <h3>Camera and history</h3>
                    <div className="mini-camera"><span>SV</span></div>
                    <div className="annotation right">Camera and history without stealing focus</div>
                  </aside>
                </section>
              )}

              {stage.id === "report" && (
                <section className="report-board">
                  <article className="verdict">
                    <div className="seal">AG</div>
                    <span className="label">Decision package</span>
                    <h3>Scoped yes, with two follow-ups.</h3>
                    <p>The report tells the hiring team what was tested, what held up, and where a human interviewer should go next.</p>
                  </article>
                  <div className="report-grid">
                    {REPORT_CARDS.map(([title, value, body]) => (
                      <article className="report-card" key={title}>
                        <strong>{title}</strong>
                        <em>{value}</em>
                        <p>{body}</p>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {stage.id === "simulation" && (
                <article className="terminal">
                  <div className="terminal-top">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                    <span>payment_retry.test.ts</span>
                  </div>
                  <div className="terminal-body">
                    <div className="fail">FAIL payment_retry.spec.ts</div>
                    <div className="fail">  x should not double-charge on retry [16ms]</div>
                    <div>    Expected: 1 charge</div>
                    <span className="highlight-line">    Received: 2 charges</span>
                    <br />
                    <div className="pass">
                      <TypeIn
                        active={stage.id === "simulation"}
                        delay={2200}
                        speed={44}
                        text="// Fix: add idempotency key check before charge"
                      />
                    </div>
                  </div>
                  <div className="terminal-caption">For engineering roles: real code, real tests, observable judgment.</div>
                </article>
              )}

              {stage.id === "close" && (
                <article className="close-card">
                  <div className="close-grid">
                    <div className="close-aura">
                      <AgentAudioVisualizerAura size="md" state="idle" color="#7FE2AE" colorShift={0.1} themeMode="dark" />
                    </div>
                    <div>
                      <h3>One system. Two surfaces.</h3>
                      <div className="surface-list">
                        <div className="surface-row">
                          <strong>Voice interview</strong>
                          Resume → live room → decision package
                        </div>
                        <div className="surface-row">
                          <strong>Engineering simulation</strong>
                          Incident → real code → evidence ledger
                        </div>
                      </div>
                      <div className="close-actions">
                        <button className="pill primary" type="button">Open live room →</button>
                        <button className="pill" type="button">Engineering simulation</button>
                      </div>
                    </div>
                  </div>
                </article>
              )}
            </div>
          </section>
        </section>
        <div className="cursor" />
      </section>

      <nav className="dots" aria-label="Demo stages">
        {STAGES.map((item, index) => (
          <button
            aria-label={`Go to ${item.label}`}
            className={index === stageIndex ? "active" : ""}
            key={item.id}
            onClick={() => goTo(index)}
            type="button"
          />
        ))}
      </nav>

      <div className="footer">
        <button aria-label="Previous" type="button" onClick={() => goTo(Math.max(0, stageIndex - 1))}>←</button>
        <button aria-label={isPlaying ? "Pause" : "Play"} type="button" onClick={() => setIsPlaying((value) => !value)}>{isPlaying ? "Ⅱ" : "▶"}</button>
        <button aria-label="Next" type="button" onClick={() => goTo(Math.min(STAGES.length - 1, stageIndex + 1))}>→</button>
        <button aria-label="Restart" type="button" onClick={() => goTo(0)}>↺</button>
      </div>
    </main>
  );
}
