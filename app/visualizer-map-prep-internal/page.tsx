"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StageId = "seed" | "problem" | "thesis" | "evidence" | "builder" | "turns" | "room" | "report" | "close";

type Stage = {
  id: StageId;
  label: string;
  duration: number;
  progress: number;
  title: string;
  subtitle: string;
};

const STAGES: Stage[] = [
  {
    id: "seed",
    label: "Start",
    duration: 1300,
    progress: 0,
    title: "Start interview simulation",
    subtitle: "A focused demo of the full Antigravity interview loop.",
  },
  {
    id: "problem",
    label: "Why",
    duration: 3600,
    progress: 13,
    title: "Hiring still relies on weak evidence.",
    subtitle: "The resume sounds strong. The interview feels promising. The decision package is often too thin to defend.",
  },
  {
    id: "thesis",
    label: "Product loop",
    duration: 3600,
    progress: 28,
    title: "Antigravity turns the interview itself into the product.",
    subtitle: "The candidate experiences a clear live room. The hiring team gets comparable evidence from what actually happened.",
  },
  {
    id: "evidence",
    label: "Setup",
    duration: 3600,
    progress: 43,
    title: "The interview starts with role context, not generic questions.",
    subtitle: "The system frames the candidate, job, experience, and decision goal before the first live turn begins.",
  },
  {
    id: "builder",
    label: "Room build",
    duration: 3600,
    progress: 54,
    title: "The room assembles around the candidate experience.",
    subtitle: "Interviewer presence, turn-taking, transcript behavior, camera, controls, and report output become one coherent flow.",
  },
  {
    id: "turns",
    label: "Turns",
    duration: 3800,
    progress: 67,
    title: "The floor moves visibly between interviewer and candidate.",
    subtitle: "This is the core interaction promise: no guessing who owns the turn, no hidden state, no awkward dead air.",
  },
  {
    id: "room",
    label: "Live room",
    duration: 3800,
    progress: 80,
    title: "The live room makes the interview legible.",
    subtitle: "Turn ownership, question anchoring, candidate controls, camera, and history are visible without crowding the main task.",
  },
  {
    id: "report",
    label: "Report",
    duration: 4200,
    progress: 93,
    title: "The output is a decision package.",
    subtitle: "The report translates the conversation into role fit, strongest signal, claim calibration, coverage, and follow-ups.",
  },
  {
    id: "close",
    label: "Close",
    duration: 5200,
    progress: 100,
    title: "One flow: prepare, interview, decide.",
    subtitle: "A serious room for candidates. A defensible evidence package for hiring teams.",
  },
];

const EVIDENCE_PACKET = [
  ["Candidate", "S. V. S. Apparao"],
  ["Role", "Product Analyst"],
  ["Experience signal", "Launch analytics, dashboard quality, stakeholder decision support."],
  ["Live scenario", "A conversion drop appears, but the event instrumentation may be unreliable."],
  ["Interview goal", "Watch how the candidate reasons, asks clarifying questions, recovers, and communicates judgment."],
  ["Hiring output", "A decision package with role fit, strongest signal, tested risks, and follow-ups."],
];

const BUILDER_STEPS = [
  { title: "AI interviewer", impact: "A stateful presence asks, listens, reviews, and yields the floor." },
  { title: "Candidate corner", impact: "Camera, controls, and answer flow make the candidate feel oriented." },
  { title: "Anchored question", impact: "The current prompt stays central instead of disappearing into chat history." },
  { title: "Live transcription", impact: "Current answer text supports accessibility without becoming the whole interface." },
  { title: "Turn history", impact: "Committed Q/A context stays available without stealing focus." },
  { title: "Decision report", impact: "The interview resolves into evidence a hiring team can act on." },
];

const REPORT_CARDS = [
  { title: "Role fit", value: "Scoped yes", body: "Strong for product analytics roles with metric-quality ambiguity." },
  { title: "Strongest signal", value: "Judgment under follow-up", body: "Separated real conversion movement from event instrumentation noise." },
  { title: "Interview quality", value: "High coverage", body: "The room tested reasoning, communication, applied tradeoffs, and recovery." },
  { title: "Resume claim calibration", value: "Mostly supported", body: "Launch analytics ownership was supported; governance depth remains partially tested." },
  { title: "Tested strengths", value: "3 clear areas", body: "Metric diagnosis, stakeholder framing, and decision communication." },
  { title: "Scoped tested risks", value: "2 unresolved", body: "Ownership boundaries and monitoring thresholds need a human follow-up." },
  { title: "Knowledge coverage", value: "Transparent", body: "The report distinguishes tested knowledge from untested assumptions." },
  { title: "Recommended follow-ups", value: "Actionable", body: "Ask one governance follow-up and one dashboard-quality follow-up onsite." },
];

function auraFor(stage: StageId): AgentState {
  if (stage === "room") return "speaking";
  if (stage === "builder" || stage === "report") return "thinking";
  return "idle";
}

export default function InternalMapPrepPage() {
  const [stageIndex, setStageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const stage = STAGES[stageIndex];

  useEffect(() => {
    if (!isPlaying || stageIndex === STAGES.length - 1) return;
    const timer = window.setTimeout(() => {
      setStageIndex((current) => Math.min(STAGES.length - 1, current + 1));
    }, stage.duration);
    return () => window.clearTimeout(timer);
  }, [isPlaying, stage.duration, stageIndex]);

  const style = useMemo(
    () => ({ "--progress": `${stage.progress}%` }) as CSSProperties,
    [stage.progress],
  );

  const goTo = (index: number) => {
    setIsPlaying(false);
    setStageIndex(index);
  };

  return (
    <main className="internal-prep" data-stage={stage.id} style={style}>
      <style>{`
        .internal-prep {
          --black: #050505;
          --ink: #14110f;
          --cream: #f3eee4;
          --paper: #ece2d1;
          --muted: #b8b0a3;
          --crail: #c15f3c;
          --amber: #d9a24d;
          --teal: #31c5df;
          --green: #7fe2ae;
          min-height: 100vh;
          overflow: hidden;
          color: white;
          font-family: var(--font-geist-sans), Inter, ui-sans-serif, system-ui, sans-serif;
          background:
            radial-gradient(42rem 26rem at 72% 18%, rgba(193,95,60,0.16), transparent 62%),
            radial-gradient(40rem 26rem at 18% 82%, rgba(49,197,223,0.1), transparent 64%),
            linear-gradient(180deg, #0b0908 0%, #030303 100%);
        }
        .internal-prep::before {
          content: "";
          position: fixed;
          inset: -20%;
          pointer-events: none;
          background:
            linear-gradient(115deg, transparent 0 38%, rgba(243,238,228,0.05) 38.2% 38.8%, transparent 39% 100%),
            radial-gradient(circle, rgba(243,238,228,0.22) 0 1px, transparent 1.4px);
          background-size: auto, 34px 34px;
          opacity: 0.08;
          mask-image: radial-gradient(ellipse at center, black 0 58%, transparent 78%);
        }
        h1, h2, h3, p { margin-top: 0; }
        button { font: inherit; }
        .stage {
          position: relative;
          z-index: 1;
          min-height: 100svh;
          display: grid;
          place-items: center;
          padding: 22px 30px 52px;
        }
        .shell {
          width: min(1440px, calc(100vw - 60px));
          height: min(800px, calc(100svh - 104px));
          min-height: 560px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 34px;
          overflow: hidden;
          background:
            radial-gradient(50rem 22rem at 75% 10%, rgba(193,95,60,0.11), transparent 58%),
            rgba(8,8,8,0.92);
          box-shadow: 0 40px 130px rgba(0,0,0,0.62), inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .internal-prep[data-stage="seed"] .shell {
          width: 340px;
          height: 66px;
          min-height: 66px;
          border-radius: 999px;
        }
        .seed-pill {
          display: none;
          height: 66px;
          align-items: center;
          justify-content: center;
          gap: 10px;
          color: var(--cream);
          font-weight: 820;
        }
        .seed-pill::before {
          content: "";
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--crail);
          box-shadow: 0 0 28px rgba(193,95,60,0.62);
        }
        .internal-prep[data-stage="seed"] .seed-pill { display: flex; }
        .content { display: grid; grid-template-rows: auto 1fr; min-height: inherit; }
        .content { height: 100%; min-height: 0; }
        .internal-prep[data-stage="seed"] .content { display: none; }
        .top {
          display: grid;
          grid-template-columns: minmax(0,1fr) 360px;
          gap: 24px;
          align-items: center;
          padding: 22px 30px;
          border-bottom: 1px solid rgba(243,238,228,0.1);
        }
        .brand {
          display: flex;
          align-items: center;
          gap: 16px;
          min-width: 0;
        }
        .mark {
          width: 52px;
          height: 52px;
          border-radius: 18px;
          display: grid;
          place-items: center;
          background: radial-gradient(circle at 38% 36%, rgba(193,95,60,0.56), rgba(193,95,60,0.05) 62%, rgba(0,0,0,0.82));
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.1), 0 0 34px rgba(193,95,60,0.16);
        }
        .mark::after {
          content: "";
          width: 20px;
          height: 20px;
          border-radius: 50%;
          border: 3px solid white;
          border-left-color: transparent;
        }
        .kicker {
          margin: 0;
          color: rgba(243,238,228,0.58);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.25em;
          text-transform: uppercase;
        }
        .brand h1 {
          margin: 5px 0 0;
          font-size: 24px;
          line-height: 1.05;
        }
        .progress { display: grid; gap: 9px; color: rgba(243,238,228,0.58); font-size: 12px; }
        .progress-row { display: flex; justify-content: space-between; }
        .progress-bar { height: 7px; overflow: hidden; border-radius: 999px; background: rgba(243,238,228,0.12); }
        .progress-bar::after {
          content: "";
          display: block;
          width: var(--progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--crail), var(--amber), var(--teal));
          transition: width 520ms ease;
        }
        .body {
          display: grid;
          grid-template-columns: minmax(0, 0.95fr) minmax(360px, 1.2fr);
          gap: 28px;
          align-items: center;
          padding: 36px;
          min-height: 0;
          overflow: hidden;
        }
        .hero-copy h2 {
          margin: 12px 0 0;
          max-width: 660px;
          font-size: clamp(42px, 5.5vw, 82px);
          line-height: 0.93;
          letter-spacing: 0;
        }
        .hero-copy p {
          max-width: 600px;
          margin: 22px 0 0;
          color: rgba(243,238,228,0.66);
          font-size: 17px;
          line-height: 1.55;
        }
        .stage-count {
          display: inline-flex;
          margin-top: 28px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 999px;
          padding: 10px 13px;
          color: rgba(243,238,228,0.62);
          font-size: 12px;
          font-weight: 760;
        }
        .visual {
          min-height: 0;
          display: grid;
          align-content: center;
          gap: 16px;
        }
        .signal-flow {
          position: relative;
          display: grid;
          grid-template-columns: repeat(3, minmax(0,1fr));
          gap: 18px;
          align-items: stretch;
          min-height: 330px;
        }
        .signal-card {
          position: relative;
          z-index: 2;
          display: grid;
          align-content: space-between;
          min-height: 260px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 30px;
          padding: 24px;
          overflow: hidden;
          background:
            radial-gradient(22rem 16rem at 50% 0%, rgba(193,95,60,0.12), transparent 62%),
            rgba(255,255,255,0.045);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.018);
        }
        .signal-card.live {
          background:
            radial-gradient(22rem 16rem at 50% 0%, rgba(49,197,223,0.13), transparent 62%),
            rgba(255,255,255,0.045);
        }
        .signal-card.output {
          background:
            radial-gradient(22rem 16rem at 50% 0%, rgba(127,226,174,0.1), transparent 62%),
            rgba(255,255,255,0.045);
        }
        .signal-card .label { margin: 0 0 12px; }
        .signal-card strong {
          display: block;
          color: var(--cream);
          font-size: 28px;
          line-height: 1.02;
          letter-spacing: 0;
        }
        .signal-card p {
          margin: 20px 0 0;
          color: rgba(243,238,228,0.62);
          font-size: 14px;
          line-height: 1.48;
        }
        .signal-card .metric {
          display: inline-flex;
          width: fit-content;
          border: 1px solid rgba(217,162,77,0.28);
          border-radius: 999px;
          padding: 9px 12px;
          color: #ffd9a8;
          background: rgba(217,162,77,0.08);
          font-size: 11px;
          font-weight: 840;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .product-loop {
          position: relative;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
          min-height: 360px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 34px;
          padding: 24px;
          overflow: hidden;
          background:
            radial-gradient(30rem 18rem at 24% 18%, rgba(243,238,228,0.08), transparent 64%),
            radial-gradient(32rem 18rem at 78% 78%, rgba(49,197,223,0.12), transparent 64%),
            rgba(255,255,255,0.035);
        }
        .loop-left,
        .loop-right {
          position: relative;
          z-index: 2;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 26px;
          padding: 22px;
          background: rgba(0,0,0,0.38);
        }
        .loop-left strong,
        .loop-right strong {
          display: block;
          color: var(--cream);
          font-size: 24px;
          line-height: 1.06;
        }
        .loop-left p,
        .loop-right p {
          color: rgba(243,238,228,0.64);
          line-height: 1.5;
        }
        .mini-turns {
          display: grid;
          gap: 10px;
          margin-top: 22px;
        }
        .mini-turn {
          display: grid;
          grid-template-columns: 86px 1fr;
          gap: 12px;
          align-items: center;
        }
        .mini-turn span:first-child {
          color: rgba(243,238,228,0.46);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .mini-turn span:last-child {
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 999px;
          padding: 10px 13px;
          background: rgba(255,255,255,0.05);
          color: rgba(243,238,228,0.72);
          font-size: 13px;
        }
        .loop-output {
          display: grid;
          gap: 12px;
          margin-top: 18px;
        }
        .loop-output div {
          border: 1px solid rgba(49,197,223,0.18);
          border-radius: 18px;
          padding: 13px;
          background: rgba(49,197,223,0.055);
        }
        .loop-output b {
          display: block;
          color: #dffbff;
          font-size: 13px;
        }
        .loop-output span {
          display: block;
          margin-top: 4px;
          color: rgba(243,238,228,0.62);
          font-size: 12px;
          line-height: 1.35;
        }
        .builder-stage {
          position: relative;
          display: grid;
          grid-template-columns: 0.78fr 1.22fr;
          gap: 20px;
          align-items: stretch;
        }
        .builder-console {
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 30px;
          padding: 24px;
          background:
            linear-gradient(180deg, rgba(243,238,228,0.07), rgba(255,255,255,0.025)),
            rgba(0,0,0,0.42);
        }
        .builder-console h3 {
          margin: 0;
          color: var(--cream);
          font-size: 30px;
          line-height: 1;
        }
        .build-lines {
          display: grid;
          gap: 11px;
          margin-top: 22px;
        }
        .build-line {
          display: grid;
          grid-template-columns: 10px 1fr auto;
          gap: 10px;
          align-items: center;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 16px;
          padding: 11px 12px;
          color: rgba(243,238,228,0.7);
          background: rgba(255,255,255,0.04);
        }
        .build-line::before {
          content: "";
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: var(--amber);
          box-shadow: 0 0 18px rgba(217,162,77,0.36);
        }
        .build-line em {
          color: rgba(243,238,228,0.45);
          font-size: 10px;
          font-style: normal;
          font-weight: 860;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .builder-map.connected {
          position: relative;
          grid-template-columns: repeat(2, minmax(0,1fr));
        }
        .builder-map.connected::before {
          content: "";
          position: absolute;
          left: 18%;
          right: 18%;
          top: 50%;
          height: 2px;
          border-radius: 999px;
          background: linear-gradient(90deg, transparent, rgba(217,162,77,0.55), rgba(49,197,223,0.45), transparent);
          box-shadow: 0 0 20px rgba(217,162,77,0.16);
          animation: flow-pulse 2.6s ease-in-out infinite;
        }
        @keyframes flow-pulse {
          0%, 100% { opacity: 0.32; transform: scaleX(0.88); }
          50% { opacity: 1; transform: scaleX(1); }
        }
        .card-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0,1fr));
          gap: 14px;
        }
        .dark-card, .cream-card {
          border-radius: 26px;
          padding: 22px;
          min-height: 180px;
        }
        .dark-card {
          border: 1px solid rgba(243,238,228,0.12);
          background: rgba(255,255,255,0.045);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .dark-card strong, .cream-card strong { display: block; font-size: 21px; line-height: 1.05; }
        .dark-card em, .cream-card em {
          display: block;
          margin-top: 8px;
          color: var(--crail);
          font-size: 11px;
          font-style: normal;
          font-weight: 860;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .dark-card p, .cream-card p { margin: 18px 0 0; font-size: 14px; line-height: 1.5; }
        .dark-card p { color: rgba(243,238,228,0.64); }
        .cream-card {
          color: var(--ink);
          border: 1px solid rgba(255,255,255,0.5);
          background: linear-gradient(180deg, var(--cream), var(--paper));
          box-shadow: 0 26px 90px rgba(0,0,0,0.28);
        }
        .thesis-stack {
          display: grid;
          gap: 13px;
        }
        .thesis-row {
          display: grid;
          grid-template-columns: 150px 1fr;
          gap: 18px;
          align-items: start;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 22px;
          padding: 18px;
          background: rgba(255,255,255,0.045);
        }
        .thesis-row strong { color: var(--cream); font-size: 18px; }
        .thesis-row p { margin: 0; color: rgba(243,238,228,0.64); line-height: 1.5; }
        .paper {
          width: min(760px, 100%);
          justify-self: end;
          border-radius: 30px;
          padding: 26px;
          background: linear-gradient(180deg, var(--cream), var(--paper));
          color: var(--ink);
          box-shadow: 0 36px 120px rgba(0,0,0,0.36);
        }
        .paper h3 { margin: 0 0 18px; font-size: 26px; }
        .paper-row {
          display: grid;
          grid-template-columns: 180px 1fr;
          gap: 18px;
          padding: 14px 0;
          border-top: 1px solid rgba(20,17,15,0.12);
        }
        .paper-row span:first-child {
          color: rgba(20,17,15,0.46);
          font-size: 11px;
          font-weight: 860;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .paper-row span:last-child { font-weight: 720; line-height: 1.35; }
        .builder-map {
          display: grid;
          grid-template-columns: repeat(3, minmax(0,1fr));
          gap: 13px;
        }
        .builder-node {
          min-height: 138px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 23px;
          padding: 18px;
          background: rgba(255,255,255,0.045);
        }
        .builder-node strong { display: block; font-size: 18px; }
        .builder-node p { margin: 14px 0 0; color: rgba(243,238,228,0.62); font-size: 13px; line-height: 1.45; }
        .turn-sim {
          display: grid;
          gap: 18px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 32px;
          padding: 26px;
          background:
            radial-gradient(34rem 20rem at 18% 50%, rgba(193,95,60,0.12), transparent 62%),
            radial-gradient(34rem 20rem at 82% 50%, rgba(49,197,223,0.12), transparent 62%),
            rgba(255,255,255,0.04);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .turn-sim-stage {
          display: grid;
          grid-template-columns: 170px minmax(0,1fr) 170px;
          gap: 18px;
          align-items: center;
        }
        .turn-person {
          min-height: 180px;
          display: grid;
          align-content: center;
          justify-items: center;
          gap: 12px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 26px;
          background: rgba(0,0,0,0.38);
          color: rgba(243,238,228,0.74);
          text-align: center;
        }
        .turn-person strong {
          font-size: 15px;
        }
        .turn-avatar {
          display: grid;
          width: 72px;
          height: 72px;
          place-items: center;
          border-radius: 24px;
          background: rgba(255,255,255,0.06);
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.08);
          font-weight: 860;
        }
        .turn-person.ai .turn-avatar {
          background: rgba(193,95,60,0.12);
          color: #ffd9cb;
        }
        .turn-person.candidate .turn-avatar {
          background: rgba(49,197,223,0.12);
          color: #dffbff;
        }
        .turn-track {
          display: grid;
          gap: 16px;
        }
        .turn-rail {
          position: relative;
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          gap: 16px;
          align-items: center;
        }
        .turn-rail::before {
          content: "";
          position: absolute;
          left: 0;
          right: 0;
          top: 50%;
          height: 2px;
          transform: translateY(-50%);
          background: rgba(243,238,228,0.12);
        }
        .turn-beam {
          position: absolute;
          top: 50%;
          left: 7%;
          width: 44%;
          height: 3px;
          border-radius: 999px;
          transform: translateY(-50%);
          background: linear-gradient(90deg, var(--crail), var(--amber), var(--teal));
          box-shadow: 0 0 24px rgba(217,162,77,0.24);
          animation: floor-transfer 3.2s cubic-bezier(.2,.86,.18,1) infinite;
        }
        .turn-rail span {
          position: relative;
          z-index: 1;
          height: 2px;
        }
        .turn-rail strong {
          position: relative;
          z-index: 1;
          border: 1px solid rgba(243,238,228,0.16);
          border-radius: 999px;
          padding: 10px 18px;
          background: rgba(0,0,0,0.72);
          color: var(--cream);
          font-size: 11px;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
        .turn-caption {
          display: grid;
          grid-template-columns: repeat(3, minmax(0,1fr));
          gap: 10px;
        }
        .turn-caption div {
          min-height: 86px;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 18px;
          padding: 14px;
          background: rgba(0,0,0,0.3);
        }
        .turn-caption strong {
          display: block;
          color: var(--cream);
          font-size: 14px;
        }
        .turn-caption p {
          margin: 8px 0 0;
          color: rgba(243,238,228,0.6);
          font-size: 12px;
          line-height: 1.4;
        }
        @keyframes floor-transfer {
          0%, 24% {
            left: 5%;
            width: 28%;
            background: linear-gradient(90deg, var(--crail), var(--amber));
          }
          42%, 66% {
            left: 34%;
            width: 32%;
            background: linear-gradient(90deg, var(--amber), var(--teal));
          }
          78%, 100% {
            left: 67%;
            width: 28%;
            background: linear-gradient(90deg, var(--teal), var(--green));
          }
        }
        .room-artifact {
          display: grid;
          grid-template-columns: 190px minmax(0,1fr) 190px;
          gap: 14px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 30px;
          padding: 16px;
          background: rgba(0,0,0,0.42);
        }
        .room-panel {
          min-width: 0;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 24px;
          background: rgba(0,0,0,0.58);
          padding: 15px;
        }
        .room-panel h3 { margin: 0; font-size: 18px; }
        .mini-aura, .mini-camera {
          display: grid;
          min-height: 170px;
          margin-top: 14px;
          place-items: center;
          border-radius: 20px;
          background: #020202;
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.08);
        }
        .mini-camera span {
          display: grid;
          width: 72px;
          height: 72px;
          place-items: center;
          border-radius: 24px;
          background: rgba(49,197,223,0.1);
          color: var(--cream);
          font-size: 21px;
          font-weight: 840;
        }
        .turn-line {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          gap: 12px;
          align-items: center;
          margin-bottom: 18px;
        }
        .turn-line span { height: 2px; border-radius: 999px; background: rgba(243,238,228,0.16); }
        .turn-line span:first-child { background: linear-gradient(90deg, var(--crail), rgba(243,238,228,0.16)); }
        .turn-line strong {
          border: 1px solid rgba(193,95,60,0.3);
          border-radius: 999px;
          padding: 8px 13px;
          color: var(--cream);
          font-size: 10px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .question {
          border-radius: 24px;
          padding: 28px;
          background: #000;
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.08), 0 0 34px rgba(193,95,60,0.12);
        }
        .label {
          display: block;
          margin-bottom: 13px;
          color: rgba(243,238,228,0.5);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
        .question p {
          margin: 0;
          color: white;
          font-size: clamp(28px, 3.1vw, 46px);
          line-height: 1.03;
          font-weight: 850;
        }
        .answer-strip {
          margin-top: 13px;
          border: 1px solid rgba(49,197,223,0.18);
          border-radius: 18px;
          padding: 12px 14px;
          color: rgba(243,238,228,0.64);
          font-size: 13px;
        }
        .room-controls { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        .pill {
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 10px 13px;
          background: rgba(255,255,255,0.055);
          color: rgba(243,238,228,0.76);
        }
        .pill.primary { border-color: rgba(127,226,174,0.32); color: #dffff0; background: rgba(127,226,174,0.12); }
        .report-board {
          display: grid;
          grid-template-columns: 1.05fr 1fr;
          gap: 16px;
        }
        .verdict {
          min-height: 100%;
          border-radius: 30px;
          padding: 26px;
          color: var(--ink);
          background: linear-gradient(180deg, var(--cream), var(--paper));
        }
        .verdict h3 { margin: 8px 0 0; font-size: clamp(36px, 4.5vw, 66px); line-height: 0.92; }
        .verdict p { color: rgba(20,17,15,0.62); line-height: 1.5; }
        .report-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
        .report-item {
          min-height: 122px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 22px;
          padding: 17px;
          background: rgba(255,255,255,0.045);
        }
        .report-item strong { display: block; font-size: 17px; }
        .report-item em { display: block; margin-top: 7px; color: var(--amber); font-style: normal; font-size: 11px; font-weight: 860; letter-spacing: 0.14em; text-transform: uppercase; }
        .report-item p { margin: 12px 0 0; color: rgba(243,238,228,0.62); font-size: 12px; line-height: 1.45; }
        .internal-prep[data-stage="room"] .body,
        .internal-prep[data-stage="report"] .body {
          grid-template-columns: 1fr;
          align-items: stretch;
          grid-template-rows: auto minmax(0,1fr);
          gap: 16px;
          padding: 20px 30px 28px;
        }
        .internal-prep[data-stage="turns"] .body {
          grid-template-columns: minmax(340px, 0.62fr) minmax(640px, 1.1fr);
          gap: 30px;
          padding: 32px 36px;
        }
        .internal-prep[data-stage="turns"] .hero-copy h2 {
          max-width: 540px;
          font-size: clamp(44px, 4.4vw, 70px);
        }
        .internal-prep[data-stage="turns"] .visual {
          align-content: center;
        }
        .internal-prep[data-stage="room"] .hero-copy,
        .internal-prep[data-stage="report"] .hero-copy {
          display: grid;
          grid-template-columns: minmax(0,1fr) auto;
          align-items: end;
          column-gap: 24px;
          max-width: none;
        }
        .internal-prep[data-stage="room"] .hero-copy .kicker,
        .internal-prep[data-stage="report"] .hero-copy .kicker {
          grid-column: 1 / -1;
        }
        .internal-prep[data-stage="room"] .hero-copy h2,
        .internal-prep[data-stage="report"] .hero-copy h2 {
          max-width: 820px;
          font-size: clamp(34px, 3.7vw, 56px);
          line-height: 0.96;
        }
        .internal-prep[data-stage="room"] .hero-copy p,
        .internal-prep[data-stage="report"] .hero-copy p {
          max-width: 560px;
          margin: 0;
          font-size: 14px;
        }
        .internal-prep[data-stage="room"] .stage-count,
        .internal-prep[data-stage="report"] .stage-count {
          display: none;
        }
        .internal-prep[data-stage="room"] .visual,
        .internal-prep[data-stage="report"] .visual {
          min-height: 0;
          align-content: stretch;
          overflow: hidden;
        }
        .internal-prep[data-stage="room"] .room-artifact {
          height: 100%;
          grid-template-columns: 250px minmax(620px,1fr) 250px;
          min-height: 0;
          align-items: stretch;
        }
        .internal-prep[data-stage="room"] .mini-aura,
        .internal-prep[data-stage="room"] .mini-camera {
          min-height: 205px;
        }
        .internal-prep[data-stage="room"] .room-panel {
          display: grid;
          align-content: start;
        }
        .internal-prep[data-stage="room"] .room-panel:nth-child(2) {
          grid-template-rows: auto auto auto auto;
        }
        .internal-prep[data-stage="room"] .question {
          min-height: 205px;
          display: grid;
          align-content: center;
        }
        .internal-prep[data-stage="room"] .question p {
          max-width: 920px;
          font-size: clamp(32px, 3vw, 46px);
          line-height: 1.01;
        }
        .internal-prep[data-stage="room"] .room-controls {
          padding-bottom: 2px;
        }
        .internal-prep[data-stage="report"] .report-board {
          height: 100%;
          min-height: 0;
          grid-template-columns: 0.76fr 1.24fr;
          align-items: stretch;
        }
        .internal-prep[data-stage="report"] .verdict {
          min-height: 0;
        }
        .internal-prep[data-stage="report"] .verdict h3 {
          font-size: clamp(42px, 4vw, 62px);
        }
        .internal-prep[data-stage="report"] .report-grid {
          grid-template-columns: repeat(4, minmax(0,1fr));
          grid-auto-rows: minmax(0,1fr);
          min-height: 0;
          overflow: hidden;
        }
        .internal-prep[data-stage="report"] .report-item {
          min-height: 0;
          padding: 14px;
        }
        .internal-prep[data-stage="report"] .report-item strong {
          font-size: 15px;
          line-height: 1.12;
        }
        .internal-prep[data-stage="report"] .report-item em {
          margin-top: 6px;
          font-size: 9.5px;
        }
        .internal-prep[data-stage="report"] .report-item p {
          margin-top: 9px;
          font-size: 11.2px;
          line-height: 1.35;
        }
        .internal-prep[data-stage="report"] .footer {
          transform: scale(0.92);
          transform-origin: right bottom;
        }
        .close-card {
          justify-self: end;
          width: min(650px, 100%);
          border-radius: 34px;
          padding: 34px;
          color: var(--ink);
          background: linear-gradient(180deg, var(--cream), var(--paper));
          box-shadow: 0 34px 120px rgba(0,0,0,0.36);
        }
        .close-card h3 { margin: 0; font-size: clamp(42px, 5vw, 72px); line-height: 0.94; }
        .close-card p { margin: 18px 0 0; color: rgba(20,17,15,0.62); line-height: 1.55; }
        .close-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }
        .close-actions .pill { color: var(--ink); border-color: rgba(20,17,15,0.18); background: rgba(255,255,255,0.42); }
        .close-actions .primary { background: var(--ink); color: var(--cream); }
        .dots {
          position: fixed;
          left: 50%;
          bottom: 31px;
          z-index: 10;
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
        .dots button.active { background: linear-gradient(90deg, var(--crail), var(--amber)); }
        .footer {
          position: fixed;
          right: 28px;
          bottom: 22px;
          z-index: 10;
          display: flex;
          gap: 8px;
        }
        .footer button {
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 10px 13px;
          background: rgba(255,255,255,0.07);
          color: rgba(243,238,228,0.74);
          backdrop-filter: blur(16px);
        }
        .fake-cursor {
          position: fixed;
          left: 50%;
          top: 50%;
          z-index: 30;
          width: 22px;
          height: 22px;
          pointer-events: none;
          opacity: 0;
          filter: drop-shadow(0 8px 14px rgba(0,0,0,0.42));
          transition: transform 880ms cubic-bezier(.22,.8,.18,1), opacity 260ms ease;
        }
        .fake-cursor::before {
          content: "";
          position: absolute;
          width: 0;
          height: 0;
          border-left: 10px solid white;
          border-top: 7px solid transparent;
          border-bottom: 7px solid transparent;
          transform: rotate(42deg);
        }
        .fake-cursor::after {
          content: "";
          position: absolute;
          left: 1px;
          top: 2px;
          width: 0;
          height: 0;
          border-left: 7px solid #050505;
          border-top: 5px solid transparent;
          border-bottom: 5px solid transparent;
          transform: rotate(42deg);
        }
        .internal-prep[data-stage="seed"] .fake-cursor {
          opacity: 1;
          transform: translate(-18px, 58px);
        }
        .internal-prep[data-stage="problem"] .fake-cursor {
          opacity: 1;
          transform: translate(290px, -56px);
        }
        .internal-prep[data-stage="thesis"] .fake-cursor {
          opacity: 1;
          transform: translate(170px, 112px);
        }
        .internal-prep[data-stage="evidence"] .fake-cursor {
          opacity: 1;
          transform: translate(324px, -28px);
        }
        .internal-prep[data-stage="builder"] .fake-cursor {
          opacity: 1;
          transform: translate(362px, 124px);
        }
        .internal-prep[data-stage="turns"] .fake-cursor {
          opacity: 1;
          transform: translate(250px, -2px);
        }
        .internal-prep[data-stage="room"] .fake-cursor {
          opacity: 1;
          transform: translate(202px, 186px);
        }
        .internal-prep[data-stage="report"] .fake-cursor {
          opacity: 1;
          transform: translate(356px, 92px);
        }
        .internal-prep[data-stage="close"] .fake-cursor {
          opacity: 1;
          transform: translate(292px, 156px);
        }
        @media (max-width: 1120px) {
          .body, .report-board { grid-template-columns: 1fr; }
          .visual { min-height: auto; }
          .room-artifact { grid-template-columns: 1fr; }
          .room-artifact .room-panel:first-child, .room-artifact .room-panel:last-child { display: none; }
        }
        @media (max-width: 760px) {
          .stage { padding: 14px; }
          .shell { width: calc(100vw - 28px); border-radius: 26px; }
          .top { grid-template-columns: 1fr; padding: 20px; }
          .body { padding: 22px; }
          .card-grid, .builder-map, .report-grid { grid-template-columns: 1fr; }
          .paper-row { grid-template-columns: 1fr; gap: 6px; }
          .footer { right: 12px; bottom: 12px; }
          .dots { left: 14px; bottom: 18px; transform: none; }
          .dots button { width: 20px; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
        }
      `}</style>

      <section className="stage">
        <div className="shell">
          <div className="seed-pill">{stage.title}</div>
          <div className="content">
            <header className="top">
              <div className="brand">
                <div className="mark" />
                <div>
                  <p className="kicker">Antigravity interview</p>
                  <h1>Internal interview demo</h1>
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
              <div className="hero-copy">
                <p className="kicker">{stage.label}</p>
                <h2>{stage.title}</h2>
                <p>{stage.subtitle}</p>
                <span className="stage-count">{String(stageIndex + 1).padStart(2, "0")} / {String(STAGES.length).padStart(2, "0")}</span>
              </div>

              <div className="visual">
                {stage.id === "problem" && (
                  <section className="signal-flow" aria-label="From weak hiring evidence to live interview evidence">
                    <article className="signal-card input">
                      <span className="metric">Input</span>
                      <div>
                        <span className="label">Resume claim</span>
                        <strong>Owned launch analytics</strong>
                        <p>Looks promising on paper, but the team still cannot tell if the judgment survives a messy real situation.</p>
                      </div>
                    </article>
                    <article className="signal-card live">
                      <span className="metric">Live test</span>
                      <div>
                        <span className="label">Interview moment</span>
                        <strong>Metric drop under follow-up</strong>
                        <p>The room asks the next question from what the candidate just said, then watches how they recover.</p>
                      </div>
                    </article>
                    <article className="signal-card output">
                      <span className="metric">Output</span>
                      <div>
                        <span className="label">Decision evidence</span>
                        <strong>Scoped yes + follow-ups</strong>
                        <p>Hiring gets a bounded recommendation, what was tested, and the exact risks a human should clarify.</p>
                      </div>
                    </article>
                  </section>
                )}

                {stage.id === "thesis" && (
                  <section className="product-loop" aria-label="Live conversation becomes hiring output">
                    <article className="loop-left">
                      <span className="label">Candidate experience</span>
                      <strong>A live room that feels clear while the questions get harder.</strong>
                      <p>The candidate always knows the active question, whose turn it is, and how to pause, repeat, or correct the system.</p>
                      <div className="mini-turns">
                        <div className="mini-turn"><span>Orient</span><span>AI presence, camera, and turn rail establish the room</span></div>
                        <div className="mini-turn"><span>Answer</span><span>The candidate speaks while the question stays anchored</span></div>
                        <div className="mini-turn"><span>Recover</span><span>Repeat, pause, correction, and barge-in stay available</span></div>
                      </div>
                    </article>
                    <article className="loop-right">
                      <span className="label">Hiring outcome</span>
                      <strong>The live interaction becomes a decision package.</strong>
                      <p>Instead of a transcript dump, the team sees the strongest signal, what was tested, and what still needs a human follow-up.</p>
                      <div className="loop-output">
                        <div><b>Role fit</b><span>Scoped recommendation with confidence boundaries.</span></div>
                        <div><b>Strongest signal</b><span>The best observed reasoning moment, not a vague score.</span></div>
                        <div><b>Follow-up plan</b><span>Concrete open risks for recruiter or onsite loop.</span></div>
                      </div>
                    </article>
                  </section>
                )}

                {stage.id === "evidence" && (
                  <article className="paper">
                    <h3>Interview brief</h3>
                    {EVIDENCE_PACKET.map(([label, value]) => (
                      <div className="paper-row" key={label}>
                        <span>{label}</span>
                        <span>{value}</span>
                      </div>
                    ))}
                  </article>
                )}

                {stage.id === "builder" && (
                  <section className="builder-stage" aria-label="Interview map assembly simulation">
                    <article className="builder-console">
                      <span className="label">Experience assembly</span>
                      <h3>Assembling the live interview</h3>
                      <div className="build-lines">
                        <div className="build-line"><span>Candidate context</span><em>loaded</em></div>
                        <div className="build-line"><span>Live room layout</span><em>ready</em></div>
                        <div className="build-line"><span>Turn ownership</span><em>visible</em></div>
                        <div className="build-line"><span>Decision package</span><em>armed</em></div>
                      </div>
                    </article>
                    <div className="builder-map connected">
                      {BUILDER_STEPS.map((step) => (
                        <article className="builder-node" key={step.title}>
                          <strong>{step.title}</strong>
                          <p>{step.impact}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                )}

                {stage.id === "turns" && (
                  <section className="turn-sim">
                    <div className="turn-sim-stage">
                      <aside className="turn-person ai">
                        <div className="turn-avatar">AI</div>
                        <strong>Interviewer corner</strong>
                      </aside>
                      <div className="turn-track">
                        <div className="turn-rail">
                          <span />
                          <div className="turn-beam" />
                          <strong>Floor transfer</strong>
                          <span />
                        </div>
                        <div className="turn-caption">
                          <div>
                            <strong>Ask</strong>
                            <p>AI owns the floor while the question is spoken and anchored.</p>
                          </div>
                          <div>
                            <strong>Answer</strong>
                            <p>Candidate corner lights up while live transcription stays separate.</p>
                          </div>
                          <div>
                            <strong>Review</strong>
                            <p>The room shows a short review state before the next turn.</p>
                          </div>
                        </div>
                      </div>
                      <aside className="turn-person candidate">
                        <div className="turn-avatar">SV</div>
                        <strong>Candidate corner</strong>
                      </aside>
                    </div>
                  </section>
                )}

                {stage.id === "room" && (
                  <section className="room-artifact">
                    <aside className="room-panel">
                      <span className="label">AI interviewer</span>
                      <h3>Presence</h3>
                      <div className="mini-aura">
                        <AgentAudioVisualizerAura size="md" state={auraFor(stage.id)} color="#C15F3C" colorShift={0.24} themeMode="dark" />
                      </div>
                    </aside>
                    <section className="room-panel">
                      <div className="turn-line"><span /><strong>AI turn</strong><span /></div>
                      <div className="question">
                        <span className="label">Interviewer&apos;s question</span>
                        <p>How would you tell whether a conversion drop is real or instrumentation noise?</p>
                      </div>
                      <div className="answer-strip">
                        <span className="label">Candidate answer live transcription</span>
                        The answer appears below the anchored question and remains separate from committed history.
                      </div>
                      <div className="room-controls">
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
                    </aside>
                  </section>
                )}

                {stage.id === "report" && (
                  <section className="report-board">
                    <article className="verdict">
                      <p className="kicker">Decision package</p>
                      <h3>Scoped yes, with two follow-ups.</h3>
                      <p>The report tells the hiring team what was actually tested, what held up, and where a human interviewer should go next.</p>
                    </article>
                    <div className="report-grid">
                      {REPORT_CARDS.map((card) => (
                        <article className="report-item" key={card.title}>
                          <strong>{card.title}</strong>
                          <em>{card.value}</em>
                          <p>{card.body}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                )}

                {(stage.id === "close" || stage.id === "seed") && (
                  <article className="close-card">
                    <h3>Experience the full interview loop.</h3>
                    <p>Show the product as a live assessment room: clear for candidates, adaptive during the conversation, and defensible for hiring teams.</p>
                    <div className="close-actions">
                      <button className="pill primary" type="button">Open live room</button>
                      <button className="pill" type="button">Preview report model</button>
                    </div>
                  </article>
                )}
              </div>
            </section>
          </div>
        </div>
      </section>

      <div className="fake-cursor" aria-hidden="true" />

      <div className="dots" aria-label="Demo progress">
        {STAGES.map((item, index) => (
          <button
            aria-label={`Go to ${item.label}`}
            className={index <= stageIndex ? "active" : ""}
            key={item.id}
            onClick={() => goTo(index)}
            type="button"
          />
        ))}
      </div>

      <nav className="footer" aria-label="Demo controls">
        <button onClick={() => goTo(Math.max(0, stageIndex - 1))} type="button">Previous</button>
        <button onClick={() => setIsPlaying((current) => !current)} type="button">{isPlaying ? "Pause" : "Play"}</button>
        <button onClick={() => goTo(Math.min(STAGES.length - 1, stageIndex + 1))} type="button">Next</button>
        <button onClick={() => { setStageIndex(0); setIsPlaying(true); }} type="button">Restart</button>
      </nav>
    </main>
  );
}
