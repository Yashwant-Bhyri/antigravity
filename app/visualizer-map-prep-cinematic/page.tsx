"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StageId =
  | "seed"
  | "toggle"
  | "console"
  | "folder"
  | "ready"
  | "building"
  | "steps"
  | "workspace"
  | "complete";

type Stage = {
  id: StageId;
  label: string;
  duration: number;
};

const STAGES: Stage[] = [
  { id: "seed", label: "Start", duration: 1400 },
  { id: "toggle", label: "Choose mode", duration: 1500 },
  { id: "console", label: "Set context", duration: 2800 },
  { id: "folder", label: "Attach evidence", duration: 1800 },
  { id: "ready", label: "Confirm setup", duration: 1700 },
  { id: "building", label: "Build map", duration: 2500 },
  { id: "steps", label: "Prepare room", duration: 3200 },
  { id: "workspace", label: "Reveal room", duration: 2600 },
  { id: "complete", label: "Ready", duration: 4200 },
];

const PREP_CARDS = [
  { title: "Resume evidence", body: "Claims, seniority, and role-specific proof points.", tone: "paper" },
  { title: "Probe surfaces", body: "Where product reasoning can fail under pressure.", tone: "dark" },
  { title: "Turn policy", body: "Question, answer, review, interruption, and recovery rhythm.", tone: "dark" },
  { title: "Room handoff", body: "The candidate enters a layout that already feels familiar.", tone: "teal" },
];

const MAP_STEPS = [
  "Read resume evidence",
  "Select adversarial probes",
  "Calibrate turn-taking",
  "Prepare room handoff",
];

const STEP_META: Record<StageId, { title: string; subtitle: string; progress: number }> = {
  seed: {
    title: "Interview",
    subtitle: "One calm entry point while the interview map is prepared.",
    progress: 0,
  },
  toggle: {
    title: "Map prep",
    subtitle: "Choose the prep path before the live room opens.",
    progress: 9,
  },
  console: {
    title: "Prepare S. V. S. Apparao",
    subtitle: "Resume evidence becomes interview strategy, not generic automation.",
    progress: 24,
  },
  folder: {
    title: "Evidence packet attached",
    subtitle: "The resume and role context are now persistent inputs to the map.",
    progress: 38,
  },
  ready: {
    title: "Ready to build",
    subtitle: "The setup is verified. Antigravity can construct the live interview room.",
    progress: 50,
  },
  building: {
    title: "Constructing interview map...",
    subtitle: "Probes, turn policy, and room handoff are being assembled.",
    progress: 68,
  },
  steps: {
    title: "Preparing the room",
    subtitle: "The map resolves into visible room behavior.",
    progress: 86,
  },
  workspace: {
    title: "Room taking shape",
    subtitle: "The preparation sequence lands into the interview interface.",
    progress: 96,
  },
  complete: {
    title: "Interview room ready",
    subtitle: "Enter with the layout already familiar.",
    progress: 100,
  },
};

function auraStateForStage(stage: StageId): AgentState {
  if (stage === "building" || stage === "steps" || stage === "workspace") return "thinking";
  if (stage === "complete") return "idle";
  return "connecting";
}

function checkedCountForStage(stageIndex: number) {
  if (stageIndex < 6) return 0;
  if (stageIndex === 6) return 3;
  return 4;
}

export default function CinematicMapPrepPage() {
  const [stageIndex, setStageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);

  const stage = STAGES[stageIndex];
  const meta = STEP_META[stage.id];
  const checkedCount = checkedCountForStage(stageIndex);
  const progress = meta.progress;

  useEffect(() => {
    if (!isPlaying || stageIndex === STAGES.length - 1) return;
    const timer = window.setTimeout(() => {
      setStageIndex((current) => Math.min(STAGES.length - 1, current + 1));
    }, stage.duration);
    return () => window.clearTimeout(timer);
  }, [isPlaying, stage.duration, stageIndex]);

  const stageStyle = useMemo(
    () =>
      ({
        "--progress": `${progress}%`,
        "--stage-index": stageIndex,
      }) as CSSProperties,
    [progress, stageIndex],
  );

  const goNext = () => {
    setIsPlaying(false);
    setStageIndex((current) => Math.min(STAGES.length - 1, current + 1));
  };

  const goPrevious = () => {
    setIsPlaying(false);
    setStageIndex((current) => Math.max(0, current - 1));
  };

  const restart = () => {
    setStageIndex(0);
    setIsPlaying(true);
  };

  return (
    <main className="cinematic-prep" data-stage={stage.id} style={stageStyle}>
      <style>{`
        .cinematic-prep {
          --ink: #020304;
          --deep: #061013;
          --glass: rgba(5, 12, 14, 0.78);
          --glass-strong: rgba(0, 0, 0, 0.72);
          --cream: #f1eadc;
          --cream-soft: #d8ccb8;
          --amber: #d9a24d;
          --orange: #c8753b;
          --teal: #31c5df;
          --green: #7fe2ae;
          --line: rgba(255, 255, 255, 0.1);
          min-height: 100vh;
          overflow: hidden;
          background:
            radial-gradient(42rem 26rem at 26% 78%, rgba(49,197,223,0.12), transparent 66%),
            radial-gradient(34rem 26rem at 77% 26%, rgba(216,162,77,0.12), transparent 66%),
            linear-gradient(180deg, #061014 0%, #010203 86%);
          color: white;
          font-family: var(--font-geist-sans), Inter, ui-sans-serif, system-ui, sans-serif;
          letter-spacing: 0;
          isolation: isolate;
        }
        .cinematic-prep::before {
          content: "";
          position: fixed;
          inset: -8%;
          z-index: 0;
          pointer-events: none;
          background:
            repeating-linear-gradient(34deg, transparent 0 56px, rgba(49,197,223,0.12) 57px 59px, transparent 60px 132px),
            radial-gradient(circle, rgba(255,255,255,0.13) 0 1px, transparent 1.5px);
          background-size: auto, 31px 31px;
          opacity: 0.1;
          mask-image: radial-gradient(ellipse at 50% 48%, black 0 58%, transparent 78%);
          transition: opacity 700ms ease, transform 900ms cubic-bezier(.2,.86,.18,1);
          transform: scale(1.08);
        }
        .cinematic-prep[data-stage="workspace"]::before,
        .cinematic-prep[data-stage="complete"]::before {
          opacity: 0.18;
          transform: scale(1);
        }
        .cinematic-prep::after {
          content: "";
          position: fixed;
          inset: 0;
          z-index: 1;
          pointer-events: none;
          background: radial-gradient(ellipse at 50% 52%, transparent 0 48%, rgba(0,0,0,0.7) 82%);
        }
        .cinematic-stage {
          position: relative;
          z-index: 2;
          display: grid;
          min-height: 100vh;
          place-items: center;
          padding: 26px;
        }
        .seed-shell {
          position: relative;
          display: grid;
          width: 156px;
          min-height: 56px;
          place-items: center;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.14);
          border-radius: 999px;
          background:
            linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.025)),
            rgba(2, 4, 5, 0.86);
          color: var(--cream);
          box-shadow: 0 24px 80px rgba(0,0,0,0.5), 0 0 42px rgba(49,197,223,0.08);
          transform-origin: 50% 42%;
          transition:
            width 760ms cubic-bezier(.2,.86,.18,1),
            min-height 760ms cubic-bezier(.2,.86,.18,1),
            border-radius 760ms cubic-bezier(.2,.86,.18,1),
            background 500ms ease,
            border-color 500ms ease,
            color 500ms ease,
            transform 900ms cubic-bezier(.2,.86,.18,1),
            box-shadow 700ms ease;
        }
        .seed-shell::before {
          content: "";
          position: absolute;
          inset: -45%;
          z-index: 0;
          pointer-events: none;
          background:
            radial-gradient(circle at 26% 42%, rgba(49,197,223,0.2), transparent 32%),
            radial-gradient(circle at 72% 58%, rgba(217,162,77,0.18), transparent 30%);
          opacity: 0.6;
          filter: blur(18px);
          transition: opacity 540ms ease;
        }
        .cinematic-prep[data-stage="toggle"] .seed-shell {
          width: 330px;
          box-shadow: 0 24px 80px rgba(0,0,0,0.5), 0 0 46px rgba(217,162,77,0.08);
        }
        .cinematic-prep[data-stage="console"] .seed-shell,
        .cinematic-prep[data-stage="folder"] .seed-shell,
        .cinematic-prep[data-stage="ready"] .seed-shell {
          width: min(840px, calc(100vw - 48px));
          min-height: 520px;
          border-radius: 34px;
          border-color: rgba(49,197,223,0.18);
          background:
            linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.025)),
            rgba(5, 12, 14, 0.84);
          color: white;
          box-shadow: 0 30px 110px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.035) inset;
          transform: translateY(-6px);
          backdrop-filter: blur(22px) saturate(1.12);
        }
        .cinematic-prep[data-stage="building"] .seed-shell {
          width: 380px;
          min-height: 220px;
          border-radius: 32px;
          border-color: rgba(217,162,77,0.2);
          background:
            radial-gradient(circle at 50% 26%, rgba(217,162,77,0.12), transparent 34%),
            rgba(0,0,0,0.82);
          box-shadow: 0 0 0 1px rgba(217,162,77,0.12), 0 28px 96px rgba(0,0,0,0.56);
        }
        .cinematic-prep[data-stage="steps"] .seed-shell {
          width: min(500px, calc(100vw - 48px));
          min-height: 390px;
          border-radius: 32px;
          border-color: rgba(127,226,174,0.18);
          background:
            linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03)),
            rgba(5,12,14,0.86);
          color: white;
        }
        .cinematic-prep[data-stage="workspace"] .seed-shell,
        .cinematic-prep[data-stage="complete"] .seed-shell {
          width: min(1480px, calc(100vw - 52px));
          min-height: min(790px, calc(100vh - 52px));
          border-radius: 38px;
          border-color: rgba(255,255,255,0.11);
          background:
            radial-gradient(60rem 34rem at 50% 46%, rgba(49,197,223,0.08), transparent 62%),
            rgba(3, 7, 8, 0.88);
          color: white;
          box-shadow: 0 36px 120px rgba(0,0,0,0.62), inset 0 0 0 1px rgba(255,255,255,0.04);
          backdrop-filter: blur(18px) saturate(1.08);
        }
        .seed-label {
          position: absolute;
          z-index: 2;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 9px;
          font-size: 15px;
          font-weight: 760;
          opacity: 1;
          transition: opacity 260ms ease, transform 420ms ease;
        }
        .seed-label::before {
          content: "";
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: linear-gradient(135deg, var(--amber), var(--teal));
          box-shadow: 0 0 18px rgba(49,197,223,0.34);
        }
        .cinematic-prep:not([data-stage="seed"]) .seed-label {
          opacity: 0;
          transform: translateY(-6px);
        }
        .mode-toggle {
          position: absolute;
          z-index: 2;
          inset: 7px;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
          opacity: 0;
          transition: opacity 260ms ease 160ms;
        }
        .cinematic-prep[data-stage="toggle"] .mode-toggle {
          opacity: 1;
        }
        .mode-pill {
          display: grid;
          place-items: center;
          border-radius: 999px;
          color: rgba(255,255,255,0.48);
          font-size: 14px;
          font-weight: 760;
        }
        .mode-pill.active {
          background: linear-gradient(180deg, rgba(241,234,220,0.95), rgba(216,204,184,0.92));
          color: #091012;
          box-shadow: 0 12px 34px rgba(217,162,77,0.14);
        }
        .console-content,
        .building-content,
        .step-content,
        .workspace-content {
          position: absolute;
          z-index: 2;
          inset: 0;
          opacity: 0;
          pointer-events: none;
          transition: opacity 520ms ease, transform 720ms cubic-bezier(.2,.86,.18,1);
        }
        .console-content {
          display: grid;
          grid-template-rows: auto 1fr auto;
          gap: 18px;
          padding: 28px;
          transform: translateY(16px);
        }
        .cinematic-prep[data-stage="console"] .console-content,
        .cinematic-prep[data-stage="folder"] .console-content,
        .cinematic-prep[data-stage="ready"] .console-content {
          opacity: 1;
          pointer-events: auto;
          transform: translateY(0);
        }
        .console-head {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 170px;
          align-items: start;
          gap: 26px;
        }
        .kicker {
          margin: 0 0 8px;
          color: rgba(151, 220, 229, 0.82);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.24em;
          text-transform: uppercase;
        }
        .console-title {
          margin: 0;
          max-width: 580px;
          color: white;
          font-size: 36px;
          line-height: 0.98;
          font-weight: 800;
        }
        .console-subtitle {
          max-width: 560px;
          margin: 12px 0 0;
          color: rgba(255,255,255,0.62);
          font-size: 14px;
          line-height: 1.48;
        }
        .map-core {
          display: grid;
          justify-items: center;
          gap: 8px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 24px;
          padding: 13px;
          background: rgba(0,0,0,0.34);
        }
        .tiny-progress {
          display: grid;
          width: 100%;
          gap: 7px;
          color: rgba(255,255,255,0.56);
          font-size: 11px;
          font-weight: 680;
          text-align: center;
        }
        .tiny-progress span:last-child {
          display: block;
          height: 5px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.11);
        }
        .tiny-progress span:last-child::after {
          content: "";
          display: block;
          width: var(--progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--amber), var(--teal));
          transition: width 480ms ease;
        }
        .prep-card-grid {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 11px;
        }
        .prep-card {
          min-height: 132px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 22px;
          padding: 16px;
          background: rgba(255,255,255,0.045);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
          transform: translateY(10px);
          opacity: 0;
          animation: card-in 560ms cubic-bezier(.2,.86,.18,1) forwards;
          animation-delay: calc(var(--card-index) * 80ms + 200ms);
        }
        .prep-card[data-tone="paper"] {
          background: linear-gradient(180deg, rgba(241,234,220,0.98), rgba(216,204,184,0.95));
          border-color: rgba(241,234,220,0.46);
          color: #071012;
        }
        .prep-card[data-tone="teal"] {
          background: linear-gradient(180deg, rgba(49,197,223,0.14), rgba(49,197,223,0.045));
          border-color: rgba(49,197,223,0.22);
        }
        .prep-card strong {
          display: block;
          color: inherit;
          font-size: 14px;
          line-height: 1.15;
        }
        .prep-card p {
          margin: 10px 0 0;
          color: rgba(255,255,255,0.6);
          font-size: 12px;
          line-height: 1.38;
        }
        .prep-card[data-tone="paper"] p {
          color: rgba(7,16,18,0.62);
        }
        .prompt-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 10px;
          align-items: center;
          padding: 10px;
          border: 1px solid rgba(255,255,255,0.11);
          border-radius: 24px;
          background: rgba(0,0,0,0.34);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .prompt-copy {
          display: flex;
          min-width: 0;
          align-items: center;
          gap: 9px;
          padding-left: 8px;
          color: rgba(255,255,255,0.84);
          font-size: 14px;
          font-weight: 560;
        }
        .prompt-chip {
          flex: 0 0 auto;
          border: 1px solid rgba(241,234,220,0.2);
          border-radius: 999px;
          padding: 7px 10px;
          background: rgba(241,234,220,0.1);
          color: rgba(241,234,220,0.86);
          font-size: 12px;
          font-weight: 730;
        }
        .go-button {
          border: 1px solid rgba(49,197,223,0.22);
          border-radius: 18px;
          padding: 13px 16px;
          background: rgba(49,197,223,0.12);
          color: #dffbff;
          font: inherit;
          font-weight: 780;
        }
        .evidence-sheet {
          position: absolute;
          left: 50%;
          top: 50%;
          z-index: 8;
          width: 430px;
          max-width: calc(100vw - 52px);
          border: 1px solid rgba(241,234,220,0.62);
          border-radius: 26px;
          padding: 18px;
          background: linear-gradient(180deg, rgba(241,234,220,0.98), rgba(216,204,184,0.96));
          color: #081013;
          box-shadow: 0 34px 110px rgba(0,0,0,0.42), 0 0 58px rgba(217,162,77,0.16);
          opacity: 0;
          transform: translate(-50%, -44%) scale(0.96);
          pointer-events: none;
          transition: opacity 360ms ease, transform 520ms cubic-bezier(.2,.86,.18,1);
        }
        .cinematic-prep[data-stage="folder"] .evidence-sheet {
          opacity: 1;
          transform: translate(-50%, -50%) scale(1);
        }
        .evidence-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
          margin-bottom: 18px;
        }
        .evidence-top p {
          margin: 0;
          color: rgba(8,16,19,0.52);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.22em;
          text-transform: uppercase;
        }
        .evidence-top strong {
          display: block;
          margin-top: 5px;
          font-size: 21px;
          line-height: 1.05;
        }
        .evidence-token {
          border-radius: 999px;
          padding: 8px 10px;
          background: #081013;
          color: white;
          font-size: 11px;
          font-weight: 780;
        }
        .evidence-list {
          display: grid;
          gap: 9px;
        }
        .evidence-item {
          display: grid;
          grid-template-columns: 118px 1fr;
          gap: 14px;
          border-radius: 16px;
          padding: 12px;
          background: rgba(255,255,255,0.42);
        }
        .evidence-item span:first-child {
          color: rgba(8,16,19,0.46);
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .evidence-item span:last-child {
          font-size: 13px;
          font-weight: 680;
          line-height: 1.32;
        }
        .building-content {
          display: grid;
          align-content: center;
          justify-items: center;
          gap: 14px;
          transform: scale(0.94);
        }
        .cinematic-prep[data-stage="building"] .building-content {
          opacity: 1;
          transform: scale(1);
        }
        .building-aura {
          position: relative;
          display: grid;
          width: 86px;
          height: 86px;
          place-items: center;
        }
        .building-aura::after {
          content: "*";
          position: absolute;
          inset: auto;
          display: grid;
          width: 30px;
          height: 30px;
          place-items: center;
          color: var(--amber);
          font-size: 34px;
          line-height: 1;
          animation: spin 2.2s linear infinite;
        }
        .building-title {
          margin: 0;
          font-size: 22px;
          font-weight: 780;
        }
        .building-subtitle {
          max-width: 260px;
          margin: 0 auto;
          color: rgba(255,255,255,0.58);
          font-size: 13px;
          line-height: 1.45;
          text-align: center;
        }
        .step-content {
          display: grid;
          grid-template-rows: auto 1fr;
          gap: 18px;
          padding: 28px;
          transform: translateY(16px);
        }
        .cinematic-prep[data-stage="steps"] .step-content {
          opacity: 1;
          transform: translateY(0);
        }
        .step-head h1 {
          margin: 0;
          color: white;
          font-size: 32px;
          line-height: 1;
          font-weight: 800;
        }
        .step-head p {
          margin: 10px 0 0;
          color: rgba(255,255,255,0.58);
          font-size: 13px;
          line-height: 1.4;
        }
        .check-list {
          display: grid;
          align-content: start;
          gap: 10px;
        }
        .check-item {
          display: grid;
          grid-template-columns: 30px 1fr;
          align-items: center;
          gap: 12px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 17px;
          padding: 12px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.7);
          font-size: 14px;
          font-weight: 690;
        }
        .check-dot {
          display: grid;
          width: 28px;
          height: 28px;
          place-items: center;
          border-radius: 50%;
          background: rgba(255,255,255,0.08);
          color: transparent;
          transform: scale(0.9);
          transition: background 260ms ease, color 260ms ease, transform 260ms ease;
        }
        .check-item.done {
          border-color: rgba(127,226,174,0.2);
          background: rgba(127,226,174,0.075);
          color: white;
        }
        .check-item.done .check-dot {
          background: var(--green);
          color: #04100a;
          transform: scale(1);
        }
        .workspace-content {
          display: grid;
          grid-template-rows: auto 1fr;
          gap: 18px;
          padding: 28px;
          transform: scale(1.04);
        }
        .cinematic-prep[data-stage="workspace"] .workspace-content,
        .cinematic-prep[data-stage="complete"] .workspace-content {
          opacity: 1;
          pointer-events: auto;
          transform: scale(1);
        }
        .room-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 18px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 26px;
          padding: 16px 18px;
          background: rgba(255,255,255,0.035);
        }
        .room-title h1 {
          margin: 4px 0 0;
          font-size: 22px;
          line-height: 1.1;
          font-weight: 760;
        }
        .room-title p,
        .panel-kicker {
          margin: 0;
          color: rgba(151,220,229,0.86);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.23em;
          text-transform: uppercase;
        }
        .room-status {
          display: grid;
          width: 388px;
          grid-template-columns: 1fr auto;
          align-items: center;
          gap: 14px;
        }
        .room-progress {
          display: grid;
          gap: 8px;
          color: rgba(255,255,255,0.58);
          font-size: 12px;
        }
        .room-progress-row {
          display: flex;
          justify-content: space-between;
        }
        .room-progress-bar {
          height: 7px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.1);
        }
        .room-progress-bar::after {
          content: "";
          display: block;
          width: var(--progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--amber), var(--teal), var(--green));
          transition: width 520ms ease;
        }
        .mini-stepper {
          min-width: 86px;
          border: 1px solid rgba(127,226,174,0.24);
          border-radius: 999px;
          padding: 10px 12px;
          background: rgba(127,226,174,0.1);
          color: #d7ffe7;
          font-size: 12px;
          font-weight: 820;
          text-align: center;
        }
        .room-grid {
          display: grid;
          min-height: 0;
          grid-template-columns: 320px minmax(0, 1fr) 320px;
          gap: 18px;
        }
        .room-panel {
          min-width: 0;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 30px;
          background: rgba(0,0,0,0.58);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.035);
        }
        .side-panel {
          display: grid;
          grid-template-rows: auto minmax(0,1fr) auto;
          gap: 14px;
          padding: 18px;
        }
        .panel-title {
          margin: 7px 0 0;
          color: white;
          font-size: 30px;
          line-height: 0.98;
          font-weight: 800;
        }
        .aura-stage,
        .camera-stage {
          display: grid;
          min-height: 300px;
          place-items: center;
          border-radius: 24px;
          background:
            radial-gradient(circle at 50% 48%, rgba(49,197,223,0.12), transparent 52%),
            #020303;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
        }
        .camera-avatar {
          display: grid;
          width: 86px;
          height: 86px;
          place-items: center;
          border-radius: 28px;
          background: linear-gradient(180deg, rgba(241,234,220,0.13), rgba(255,255,255,0.025));
          color: white;
          font-size: 24px;
          font-weight: 820;
          box-shadow: 0 0 0 1px rgba(255,255,255,0.1), 0 22px 50px rgba(0,0,0,0.45);
        }
        .side-caption {
          border-radius: 18px;
          padding: 14px;
          background: rgba(255,255,255,0.035);
          color: rgba(255,255,255,0.68);
          font-size: 13px;
          line-height: 1.45;
        }
        .center-panel {
          display: grid;
          grid-template-rows: auto auto minmax(0,1fr) auto;
        }
        .center-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          padding: 20px 22px 16px;
          border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .center-head h2 {
          margin: 0;
          color: white;
          font-size: 34px;
          line-height: 1;
          font-weight: 800;
        }
        .ready-badge {
          border-radius: 999px;
          padding: 10px 14px;
          background: rgba(127,226,174,0.12);
          color: #d7ffe7;
          font-size: 12px;
          font-weight: 820;
        }
        .floor-line {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          align-items: center;
          gap: 14px;
          padding: 16px 24px;
        }
        .floor-line span {
          height: 2px;
          border-radius: 999px;
          background: rgba(255,255,255,0.12);
        }
        .floor-line strong {
          border: 1px solid rgba(255,255,255,0.12);
          border-radius: 999px;
          padding: 9px 16px;
          color: rgba(255,255,255,0.76);
          font-size: 11px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .question-card {
          align-self: center;
          margin: 20px 28px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 30px;
          padding: clamp(30px, 4vw, 54px);
          background: #000;
          box-shadow: 0 0 52px rgba(49,197,223,0.08), inset 0 0 0 1px rgba(255,255,255,0.04);
        }
        .question-label {
          display: block;
          margin-bottom: 18px;
          color: rgba(151,220,229,0.78);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.24em;
          text-transform: uppercase;
        }
        .question-card p {
          margin: 0;
          max-width: 760px;
          color: white;
          font-size: clamp(42px, 4.7vw, 74px);
          line-height: 0.98;
          font-weight: 840;
          letter-spacing: 0;
        }
        .center-controls {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 18px 22px;
          border-top: 1px solid rgba(255,255,255,0.08);
        }
        .room-button {
          border: 1px solid rgba(255,255,255,0.12);
          border-radius: 17px;
          padding: 12px 16px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.74);
          font: inherit;
          font-size: 14px;
        }
        .room-button.primary {
          margin-left: auto;
          border-color: rgba(127,226,174,0.28);
          background: rgba(127,226,174,0.11);
          color: #d7ffe7;
        }
        .prep-footer {
          position: fixed;
          right: 28px;
          bottom: 24px;
          z-index: 12;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .footer-button {
          border: 1px solid rgba(255,255,255,0.12);
          border-radius: 999px;
          padding: 11px 14px;
          background: rgba(255,255,255,0.07);
          color: rgba(255,255,255,0.74);
          font: inherit;
          font-size: 13px;
          backdrop-filter: blur(16px);
        }
        .stage-dots {
          position: fixed;
          left: 50%;
          bottom: 31px;
          z-index: 12;
          display: flex;
          gap: 8px;
          transform: translateX(-50%);
        }
        .stage-dot {
          width: 34px;
          height: 9px;
          border: 1px solid rgba(255,255,255,0.12);
          border-radius: 999px;
          background: rgba(255,255,255,0.06);
        }
        .stage-dot.active {
          border-color: rgba(49,197,223,0.38);
          background: linear-gradient(90deg, var(--amber), var(--teal));
          box-shadow: 0 0 20px rgba(49,197,223,0.2);
        }
        .fake-cursor {
          position: fixed;
          left: 50%;
          top: 50%;
          z-index: 20;
          width: 22px;
          height: 22px;
          pointer-events: none;
          opacity: 0;
          filter: drop-shadow(0 8px 14px rgba(0,0,0,0.4));
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
        .cinematic-prep[data-stage="seed"] .fake-cursor {
          opacity: 1;
          transform: translate(-28px, 56px);
        }
        .cinematic-prep[data-stage="toggle"] .fake-cursor {
          opacity: 1;
          transform: translate(88px, 0);
        }
        .cinematic-prep[data-stage="console"] .fake-cursor {
          opacity: 1;
          transform: translate(-178px, -32px);
        }
        .cinematic-prep[data-stage="folder"] .fake-cursor {
          opacity: 1;
          transform: translate(130px, 36px);
        }
        .cinematic-prep[data-stage="ready"] .fake-cursor {
          opacity: 1;
          transform: translate(324px, 218px);
        }
        .cinematic-prep[data-stage="building"] .fake-cursor,
        .cinematic-prep[data-stage="steps"] .fake-cursor,
        .cinematic-prep[data-stage="workspace"] .fake-cursor,
        .cinematic-prep[data-stage="complete"] .fake-cursor {
          opacity: 0;
        }
        @keyframes card-in {
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        @media (max-width: 1100px) {
          .prep-card-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .room-grid {
            grid-template-columns: 250px minmax(0, 1fr);
          }
          .room-grid .side-panel:last-child {
            display: none;
          }
        }
        @media (max-width: 760px) {
          .cinematic-stage {
            padding: 14px;
          }
          .seed-shell {
            max-width: calc(100vw - 28px);
          }
          .cinematic-prep[data-stage="console"] .seed-shell,
          .cinematic-prep[data-stage="folder"] .seed-shell,
          .cinematic-prep[data-stage="ready"] .seed-shell {
            min-height: 680px;
            overflow: auto;
          }
          .console-content {
            padding: 16px;
          }
          .cinematic-prep[data-stage="console"] .console-content,
          .cinematic-prep[data-stage="folder"] .console-content,
          .cinematic-prep[data-stage="ready"] .console-content {
            position: relative;
          }
          .console-head {
            grid-template-columns: 1fr;
          }
          .map-core {
            display: none;
          }
          .console-title {
            font-size: 28px;
          }
          .prep-card-grid {
            grid-template-columns: 1fr;
          }
          .prompt-row {
            grid-template-columns: 1fr;
          }
          .prompt-copy {
            align-items: flex-start;
            flex-direction: column;
          }
          .cinematic-prep[data-stage="workspace"] .seed-shell,
          .cinematic-prep[data-stage="complete"] .seed-shell {
            width: calc(100vw - 28px);
            min-height: calc(100vh - 28px);
            overflow: auto;
            border-radius: 28px;
          }
          .workspace-content {
            padding: 14px;
          }
          .cinematic-prep[data-stage="workspace"] .workspace-content,
          .cinematic-prep[data-stage="complete"] .workspace-content {
            position: relative;
            min-height: 100%;
          }
          .room-top {
            align-items: flex-start;
            flex-direction: column;
            border-radius: 22px;
            padding: 14px;
          }
          .room-status {
            width: 100%;
            grid-template-columns: 1fr;
          }
          .room-grid {
            grid-template-columns: 1fr;
            min-height: auto;
          }
          .room-grid .side-panel:first-child {
            display: none;
          }
          .center-panel {
            min-height: 520px;
          }
          .center-head {
            align-items: flex-start;
            flex-direction: column;
            padding: 16px;
          }
          .center-head h2 {
            font-size: 26px;
          }
          .floor-line {
            padding: 12px 16px;
          }
          .question-card {
            margin: 12px 14px;
            padding: 26px 22px;
            border-radius: 24px;
          }
          .question-card p {
            font-size: clamp(30px, 12vw, 42px);
          }
          .center-controls {
            flex-wrap: wrap;
            padding: 14px;
          }
          .room-button.primary {
            margin-left: 0;
          }
          .prep-footer {
            right: 12px;
            bottom: 12px;
          }
          .stage-dots {
            left: 14px;
            bottom: 18px;
            transform: none;
          }
          .stage-dot {
            width: 20px;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 1ms !important;
            animation-iteration-count: 1 !important;
            scroll-behavior: auto !important;
            transition-duration: 1ms !important;
          }
        }
      `}</style>

      <section className="cinematic-stage" aria-label="Antigravity map preparation intro">
        <div className="seed-shell">
          <div className="seed-label">Interview</div>

          <div className="mode-toggle" aria-hidden={stage.id !== "toggle"}>
            <div className="mode-pill active">Map prep</div>
            <div className="mode-pill">Live room</div>
          </div>

          <section className="console-content" aria-hidden={!["console", "folder", "ready"].includes(stage.id)}>
            <div className="console-head">
              <div>
                <p className="kicker">Antigravity map builder</p>
                <h1 className="console-title">Prepare S. V. S. Apparao for Product Analyst</h1>
                <p className="console-subtitle">
                  The system converts resume evidence into probe surfaces, turn policy, and a room handoff the candidate can enter without confusion.
                </p>
              </div>
              <div className="map-core">
                <AgentAudioVisualizerAura
                  size="sm"
                  state="thinking"
                  color="#D9A24D"
                  colorShift={0.18}
                  themeMode="dark"
                />
                <div className="tiny-progress">
                  <span>{stage.label}</span>
                  <span />
                </div>
              </div>
            </div>

            <div className="prep-card-grid">
              {PREP_CARDS.map((card, index) => (
                <article
                  className="prep-card"
                  data-tone={card.tone}
                  key={card.title}
                  style={{ "--card-index": index } as CSSProperties}
                >
                  <strong>{card.title}</strong>
                  <p>{card.body}</p>
                </article>
              ))}
            </div>

            <div className="prompt-row">
              <div className="prompt-copy">
                <span>Build the interview map</span>
                <span className="prompt-chip">Resume evidence</span>
                <span className="prompt-chip">Product Analyst</span>
                <span className="prompt-chip">15-turn room</span>
              </div>
              <button className="go-button" type="button">Construct map</button>
            </div>
          </section>

          <section className="building-content" aria-hidden={stage.id !== "building"}>
            <div className="building-aura">
              <AgentAudioVisualizerAura
                size="sm"
                state="thinking"
                color="#D9A24D"
                colorShift={0.22}
                themeMode="dark"
              />
            </div>
            <h1 className="building-title">Constructing interview map...</h1>
            <p className="building-subtitle">Probes, turn policy, and room handoff are being assembled.</p>
          </section>

          <section className="step-content" aria-hidden={stage.id !== "steps"}>
            <div className="step-head">
              <p className="kicker">Room preparation</p>
              <h1>Preparing the room</h1>
              <p>The map resolves into visible interview behavior.</p>
            </div>
            <div className="check-list">
              {MAP_STEPS.map((item, index) => (
                <div className={`check-item ${index < checkedCount ? "done" : ""}`} key={item}>
                  <span className="check-dot">✓</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </section>

          <section
            className="workspace-content"
            aria-hidden={!["workspace", "complete"].includes(stage.id)}
          >
            <header className="room-top">
              <div className="room-title">
                <p>Antigravity interview</p>
                <h1>Preparing S. V. S. Apparao — Product Analyst</h1>
              </div>
              <div className="room-status">
                <div className="room-progress">
                  <div className="room-progress-row">
                    <span>{stage.id === "complete" ? "Room ready" : "Room forming"}</span>
                    <span>{progress}%</span>
                  </div>
                  <div className="room-progress-bar" />
                </div>
                <div className="mini-stepper">06 / 06</div>
              </div>
            </header>

            <div className="room-grid">
              <aside className="room-panel side-panel">
                <div>
                  <p className="panel-kicker">AI interviewer</p>
                  <h2 className="panel-title">Interviewer presence</h2>
                </div>
                <div className="aura-stage">
                  <AgentAudioVisualizerAura
                    size="lg"
                    state={auraStateForStage(stage.id)}
                    color={stage.id === "complete" ? "#7FE2AE" : "#D9A24D"}
                    colorShift={stage.id === "complete" ? 0.22 : 0.18}
                    themeMode="dark"
                  />
                </div>
                <p className="side-caption">The AI is represented as a stateful presence, not a fake human face.</p>
              </aside>

              <section className="room-panel center-panel">
                <div className="center-head">
                  <div>
                    <p className="panel-kicker">Interview map ready</p>
                    <h2>{meta.title}</h2>
                  </div>
                  <span className="ready-badge">Ready</span>
                </div>
                <div className="floor-line">
                  <span />
                  <strong>Turn</strong>
                  <span />
                </div>
                <div className="question-card">
                  <span className="question-label">Interviewer&apos;s question</span>
                  <p>When you are ready, begin the live interview.</p>
                </div>
                <div className="center-controls">
                  <button className="room-button" type="button">Repeat question</button>
                  <button className="room-button" type="button">Need a moment</button>
                  <button className="room-button" type="button">Fix last term</button>
                  <button className="room-button primary" type="button">Enter room</button>
                </div>
              </section>

              <aside className="room-panel side-panel">
                <div>
                  <p className="panel-kicker">Candidate corner</p>
                  <h2 className="panel-title">Camera and history</h2>
                </div>
                <div className="camera-stage">
                  <div className="camera-avatar">SV</div>
                </div>
                <p className="side-caption">
                  Candidate presence and turn history sit beside the stage without competing with the active question.
                </p>
              </aside>
            </div>
          </section>
        </div>

        <section className="evidence-sheet" aria-hidden={stage.id !== "folder"}>
          <div className="evidence-top">
            <div>
              <p>Evidence packet</p>
              <strong>S. V. S. Apparao</strong>
            </div>
            <span className="evidence-token">Attached</span>
          </div>
          <div className="evidence-list">
            <div className="evidence-item">
              <span>Role</span>
              <span>Product Analyst candidate</span>
            </div>
            <div className="evidence-item">
              <span>Probe lane</span>
              <span>Metrics, instrumentation, launch judgment</span>
            </div>
            <div className="evidence-item">
              <span>Room goal</span>
              <span>Test reasoning under live follow-up pressure</span>
            </div>
          </div>
        </section>

        <div className="fake-cursor" />
      </section>

      <div className="stage-dots" aria-label="Intro progress">
        {STAGES.map((item, index) => (
          <button
            aria-label={`Go to ${item.label}`}
            className={`stage-dot ${index <= stageIndex ? "active" : ""}`}
            key={item.id}
            onClick={() => {
              setIsPlaying(false);
              setStageIndex(index);
            }}
            type="button"
          />
        ))}
      </div>

      <nav className="prep-footer" aria-label="Intro controls">
        <button className="footer-button" onClick={goPrevious} type="button">Previous</button>
        <button className="footer-button" onClick={() => setIsPlaying((current) => !current)} type="button">
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button className="footer-button" onClick={goNext} type="button">Next</button>
        <button className="footer-button" onClick={restart} type="button">Restart</button>
      </nav>
    </main>
  );
}
