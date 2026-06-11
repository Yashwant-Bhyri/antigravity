"use client";

import { useEffect, useMemo, useState } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StepId = "presence" | "question" | "answer" | "floor" | "controls" | "ready";

const STEPS: Array<{
  id: StepId;
  eyebrow: string;
  title: string;
  body: string;
  phase: "preparing" | "asking" | "listening" | "reviewing" | "ready";
  owner: "ai" | "candidate" | "neutral";
  auraState: AgentState;
  auraColor: `#${string}`;
  shift: number;
}> = [
  {
    id: "presence",
    eyebrow: "Room calibration",
    title: "Meet your AI interviewer",
    body: "The Aura shows when the interviewer is present, asking, listening, or reviewing.",
    phase: "preparing",
    owner: "ai",
    auraState: "connecting",
    auraColor: "#D8A75A",
    shift: 0.24,
  },
  {
    id: "question",
    eyebrow: "Current question",
    title: "The question stays anchored",
    body: "Your main prompt remains fixed so you can keep reasoning without hunting for context.",
    phase: "asking",
    owner: "ai",
    auraState: "speaking",
    auraColor: "#E0A15B",
    shift: 0.32,
  },
  {
    id: "answer",
    eyebrow: "Live answer",
    title: "Your answer appears below",
    body: "Live transcription is current-turn only. The committed transcript is kept separately.",
    phase: "listening",
    owner: "candidate",
    auraState: "listening",
    auraColor: "#4FB7D4",
    shift: 0.28,
  },
  {
    id: "floor",
    eyebrow: "Turn ownership",
    title: "Know whose floor it is",
    body: "AI corner and candidate corner change together so interruptions and turns feel explicit.",
    phase: "reviewing",
    owner: "candidate",
    auraState: "thinking",
    auraColor: "#D6B263",
    shift: 0.34,
  },
  {
    id: "controls",
    eyebrow: "Candidate controls",
    title: "You keep control",
    body: "Repeat the question, take a moment, fix a term, or end the interview from one stable bar.",
    phase: "preparing",
    owner: "neutral",
    auraState: "idle",
    auraColor: "#6DA8C8",
    shift: 0.18,
  },
  {
    id: "ready",
    eyebrow: "Interview map ready",
    title: "Your room is ready",
    body: "The map is prepared. Enter the interview with the layout already familiar.",
    phase: "ready",
    owner: "neutral",
    auraState: "idle",
    auraColor: "#77D9A8",
    shift: 0.2,
  },
];

const MAP_STATUS = [
  "Reading resume signals",
  "Selecting probe surfaces",
  "Building follow-up paths",
  "Preparing turn strategy",
  "Room ready",
];

export default function MapPrepIntroPrototype() {
  const [stepIndex, setStepIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [mapProgress, setMapProgress] = useState(7);

  const step = STEPS[stepIndex];
  const progress = Math.max(mapProgress, Math.round(((stepIndex + 1) / STEPS.length) * 100));
  const statusIndex = Math.min(MAP_STATUS.length - 1, Math.floor((progress / 100) * MAP_STATUS.length));

  const activeQuestion = useMemo(() => {
    if (step.id === "ready") return "When you are ready, begin the live interview.";
    if (step.id === "controls") return "If you need a moment, the room can hold the current question.";
    if (step.id === "floor") return "Good. Now defend that choice when the old leader has lower latency.";
    return "Make the leader-election answer concrete: where is the stale writer rejected?";
  }, [step.id]);

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => {
      setStepIndex((current) => (current + 1) % STEPS.length);
    }, 3900);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setMapProgress((current) => {
        const target = Math.round(((stepIndex + 1) / STEPS.length) * 100);
        if (current >= 100) return 100;
        return Math.min(100, Math.max(current + 2, Math.min(target, current + 6)));
      });
    }, 380);
    return () => window.clearInterval(timer);
  }, [stepIndex]);

  const goToStep = (nextIndex: number) => {
    setIsPlaying(false);
    setStepIndex((nextIndex + STEPS.length) % STEPS.length);
  };

  return (
    <main className="prep-room" data-step={step.id} data-phase={step.phase} data-owner={step.owner}>
      <style>{`
        .prep-room {
          min-height: 100vh;
          overflow: hidden;
          color: #f7fbff;
          background:
            radial-gradient(60rem 42rem at 50% 44%, rgba(41, 134, 150, 0.16), transparent 62%),
            radial-gradient(34rem 30rem at 12% 50%, rgba(216, 167, 90, 0.08), transparent 68%),
            radial-gradient(34rem 30rem at 88% 52%, rgba(79, 183, 212, 0.08), transparent 68%),
            linear-gradient(180deg, #071012, #020304 86%);
          font-family: var(--font-geist-sans), system-ui, sans-serif;
          isolation: isolate;
        }
        .prep-room::before {
          content: "";
          position: fixed;
          inset: -10%;
          z-index: 0;
          pointer-events: none;
          opacity: 0.08;
          background:
            repeating-linear-gradient(34deg, transparent 0 52px, rgba(132, 199, 210, 0.22) 60px 63px, transparent 74px 146px),
            radial-gradient(circle, rgba(255,255,255,0.14) 0 1px, transparent 1.5px);
          background-size: auto, 30px 30px;
          mask-image: radial-gradient(ellipse at 50% 45%, black 0 46%, transparent 74%);
          animation: prep-drift 18s ease-in-out infinite alternate;
        }
        .prep-shell {
          position: relative;
          z-index: 2;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr);
          gap: 18px;
          width: min(1420px, calc(100vw - 36px));
          height: 100vh;
          margin: 0 auto;
          padding: 22px 0;
        }
        .prep-top {
          display: flex;
          min-height: 74px;
          align-items: center;
          justify-content: space-between;
          gap: 18px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 28px;
          padding: 16px 18px;
          background: rgba(4, 8, 10, 0.7);
          box-shadow: 0 24px 80px rgba(0,0,0,0.3), inset 0 0 0 1px rgba(255,255,255,0.035);
          backdrop-filter: blur(22px) saturate(1.12);
        }
        .prep-brand {
          display: flex;
          min-width: 0;
          align-items: center;
          gap: 14px;
        }
        .prep-mark {
          display: grid;
          height: 42px;
          width: 42px;
          place-items: center;
          border-radius: 15px;
          background: radial-gradient(circle at 30% 24%, rgba(216,167,90,0.84), #071014 72%);
          box-shadow: 0 0 26px rgba(216,167,90,0.18);
        }
        .prep-mark::after {
          content: "";
          height: 16px;
          width: 16px;
          border: 2px solid white;
          border-left-color: transparent;
          border-radius: 999px;
          transform: rotate(-35deg);
        }
        .prep-eyebrow {
          margin: 0;
          color: rgba(156, 211, 218, 0.86);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.24em;
          text-transform: uppercase;
        }
        .prep-title {
          margin: 4px 0 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 21px;
          font-weight: 720;
          letter-spacing: 0;
        }
        .prep-loader {
          display: grid;
          width: min(440px, 38vw);
          gap: 8px;
        }
        .prep-loader-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
          color: rgba(255,255,255,0.58);
          font-size: 12px;
        }
        .prep-bar {
          height: 8px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
        }
        .prep-bar span {
          display: block;
          height: 100%;
          width: var(--progress);
          border-radius: inherit;
          background: linear-gradient(90deg, #d8a75a, #4fb7d4, #77d9a8);
          box-shadow: 0 0 18px rgba(79,183,212,0.28);
          transition: width 420ms ease;
        }
        .prep-grid {
          display: grid;
          min-height: 0;
          grid-template-columns: minmax(260px, 330px) minmax(0, 1fr) minmax(260px, 330px);
          gap: 16px;
        }
        .prep-panel {
          position: relative;
          min-height: 0;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 32px;
          background: rgba(4, 8, 10, 0.72);
          box-shadow: 0 24px 80px rgba(0,0,0,0.34), inset 0 0 0 1px rgba(255,255,255,0.035);
          backdrop-filter: blur(22px) saturate(1.12);
        }
        .prep-panel::before {
          content: "";
          position: absolute;
          inset: -2px;
          z-index: 0;
          pointer-events: none;
          opacity: 0.46;
          background:
            radial-gradient(30rem 16rem at 50% -5%, rgba(79,183,212,0.08), transparent 70%),
            radial-gradient(20rem 14rem at 0% 50%, rgba(216,167,90,0.06), transparent 74%),
            radial-gradient(20rem 14rem at 100% 50%, rgba(79,183,212,0.06), transparent 74%);
        }
        .prep-panel > * {
          position: relative;
          z-index: 1;
        }
        .prep-left,
        .prep-right {
          display: grid;
          grid-template-rows: auto 1fr auto;
          gap: 14px;
          padding: 18px;
        }
        .prep-room[data-owner="ai"] .prep-left {
          border-color: rgba(216,167,90,0.22);
          box-shadow: -18px 0 42px -32px rgba(216,167,90,0.22), 0 24px 80px rgba(0,0,0,0.34);
        }
        .prep-room[data-owner="candidate"] .prep-right {
          border-color: rgba(79,183,212,0.22);
          box-shadow: 18px 0 42px -32px rgba(79,183,212,0.22), 0 24px 80px rgba(0,0,0,0.34);
        }
        .prep-section-title {
          margin: 6px 0 0;
          font-size: clamp(25px, 2.1vw, 32px);
          font-weight: 760;
          line-height: 1.08;
        }
        .prep-aura-box,
        .prep-camera-box {
          display: grid;
          min-height: 340px;
          place-items: center;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 26px;
          background: #030506;
        }
        .prep-aura-caption,
        .prep-camera-caption {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 19px;
          padding: 13px;
          background: rgba(0,0,0,0.35);
          color: rgba(255,255,255,0.64);
          font-size: 13px;
          line-height: 1.45;
        }
        .prep-camera-box {
          background:
            radial-gradient(14rem 9rem at 50% 38%, rgba(79,183,212,0.14), transparent 62%),
            linear-gradient(135deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012)),
            #030506;
        }
        .prep-avatar {
          display: grid;
          height: 86px;
          width: 86px;
          place-items: center;
          border: 1px solid rgba(79,183,212,0.28);
          border-radius: 28px;
          background: rgba(0,0,0,0.46);
          box-shadow: 0 0 26px rgba(79,183,212,0.16);
          font-size: 22px;
          font-weight: 850;
          letter-spacing: 0.08em;
        }
        .prep-stage {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
        }
        .prep-stage-top {
          display: grid;
          gap: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.09);
          padding: 18px 24px;
        }
        .prep-step-card {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 24px;
          align-items: start;
        }
        .prep-step-title {
          margin: 8px 0 0;
          font-size: clamp(30px, 3vw, 48px);
          font-weight: 780;
          letter-spacing: 0;
          line-height: 1.02;
        }
        .prep-step-body {
          max-width: 670px;
          margin: 12px 0 0;
          color: rgba(255,255,255,0.62);
          font-size: 16px;
          line-height: 1.48;
        }
        .prep-step-count {
          display: inline-grid;
          min-width: 84px;
          place-items: center;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 8px 12px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.58);
          font-size: 12px;
          font-weight: 760;
        }
        .prep-floor {
          display: grid;
          grid-template-columns: minmax(100px, 150px) minmax(40px, 1fr) auto minmax(40px, 1fr) minmax(100px, 150px);
          align-items: center;
          gap: 12px;
          width: min(820px, 100%);
          margin: 0 auto;
        }
        .prep-corner,
        .prep-turn-pill {
          display: inline-flex;
          min-height: 34px;
          align-items: center;
          justify-content: center;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 8px 12px;
          background: rgba(0,0,0,0.34);
          color: rgba(255,255,255,0.55);
          font-size: 11px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          white-space: nowrap;
        }
        .prep-track {
          height: 3px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
        }
        .prep-track span {
          display: block;
          height: 100%;
          width: 100%;
          border-radius: inherit;
          transform: scaleX(0);
          transition: transform 360ms cubic-bezier(.2,.8,.2,1);
        }
        .prep-ai-track span {
          transform-origin: right;
          background: linear-gradient(90deg, rgba(216,167,90,0.08), rgba(216,167,90,0.86));
        }
        .prep-candidate-track span {
          transform-origin: left;
          background: linear-gradient(90deg, rgba(79,183,212,0.86), rgba(79,183,212,0.08));
        }
        .prep-room[data-owner="ai"] .prep-ai-corner,
        .prep-room[data-owner="candidate"] .prep-candidate-corner {
          color: rgba(255,255,255,0.84);
          border-color: rgba(255,255,255,0.18);
          box-shadow: 0 0 20px rgba(255,255,255,0.08);
        }
        .prep-room[data-owner="ai"] .prep-ai-track span,
        .prep-room[data-owner="candidate"] .prep-candidate-track span {
          transform: scaleX(1);
        }
        .prep-stage-body {
          display: grid;
          align-content: center;
          gap: 14px;
          padding: 28px 34px;
        }
        .prep-question-card {
          border: 1px solid rgba(255,255,255,0.09);
          border-radius: 28px;
          padding: clamp(22px, 3vw, 38px);
          background: #010202;
          box-shadow: 0 0 34px rgba(79,183,212,0.08), inset 0 0 0 1px rgba(255,255,255,0.035);
          transition: border-color 220ms ease, box-shadow 220ms ease, transform 220ms ease;
        }
        .prep-room[data-step="question"] .prep-question-card,
        .prep-room[data-step="ready"] .prep-question-card {
          border-color: rgba(216,167,90,0.2);
          box-shadow: 0 0 42px rgba(216,167,90,0.12), inset 0 0 0 1px rgba(255,255,255,0.035);
          transform: translateY(-2px);
        }
        .prep-question-label {
          margin: 0 0 22px;
          color: rgba(255,255,255,0.46);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.24em;
          text-transform: uppercase;
        }
        .prep-question {
          margin: 0;
          font-size: clamp(34px, 4.1vw, 60px);
          font-weight: 820;
          letter-spacing: 0;
          line-height: 1.03;
        }
        .prep-answer-card {
          overflow: hidden;
          max-height: 78px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          padding: 14px 16px;
          background: rgba(0,0,0,0.22);
          transition: border-color 220ms ease, box-shadow 220ms ease, max-height 220ms ease;
        }
        .prep-room[data-step="answer"] .prep-answer-card,
        .prep-room[data-step="floor"] .prep-answer-card {
          max-height: 128px;
          border-color: rgba(79,183,212,0.22);
          box-shadow: 0 0 26px rgba(79,183,212,0.1);
        }
        .prep-answer-text {
          margin: 9px 0 0;
          color: rgba(255,255,255,0.68);
          font-size: clamp(15px, 1.4vw, 18px);
          line-height: 1.42;
        }
        .prep-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          border-top: 1px solid rgba(255,255,255,0.08);
          padding: 18px 22px;
        }
        .prep-control {
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 16px;
          padding: 12px 15px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.72);
          font: inherit;
          font-size: 14px;
          cursor: pointer;
        }
        .prep-room[data-step="controls"] .prep-control {
          border-color: rgba(255,255,255,0.18);
          box-shadow: 0 0 18px rgba(255,255,255,0.08);
        }
        .prep-control.primary {
          margin-left: auto;
          border-color: rgba(119,217,168,0.26);
          background: rgba(119,217,168,0.09);
          color: rgba(230,255,241,0.92);
          text-decoration: none;
        }
        .prep-nav {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 16px 18px 0;
        }
        .prep-step-dots {
          display: flex;
          gap: 8px;
        }
        .prep-step-dot {
          height: 8px;
          width: 34px;
          border: 0;
          border-radius: 999px;
          background: rgba(255,255,255,0.12);
          cursor: pointer;
        }
        .prep-step-dot.active {
          background: linear-gradient(90deg, #d8a75a, #4fb7d4);
          box-shadow: 0 0 12px rgba(79,183,212,0.28);
        }
        .prep-nav-actions {
          display: flex;
          gap: 8px;
        }
        .prep-nav button {
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 9px 12px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.7);
          font: inherit;
          font-size: 12px;
          cursor: pointer;
        }
        @keyframes prep-drift {
          from { transform: translate3d(-1%, -1%, 0) rotate(-1deg); }
          to { transform: translate3d(1%, 1%, 0) rotate(1deg); }
        }
        @media (max-width: 1100px) {
          .prep-shell { height: auto; min-height: 100vh; }
          .prep-grid { grid-template-columns: 1fr; }
          .prep-left, .prep-right { min-height: 420px; }
          .prep-loader { width: min(440px, 46vw); }
        }
        @media (max-width: 720px) {
          .prep-shell { width: min(100vw - 20px, 1420px); padding: 10px 0; }
          .prep-top { align-items: flex-start; flex-direction: column; }
          .prep-loader { width: 100%; }
          .prep-step-card { grid-template-columns: 1fr; }
          .prep-floor { grid-template-columns: 1fr; justify-items: center; }
          .prep-track { width: 120px; }
          .prep-stage-body { padding: 18px; }
          .prep-question { font-size: clamp(30px, 10vw, 44px); }
        }
        @media (prefers-reduced-motion: reduce) {
          .prep-room::before,
          * {
            animation: none !important;
            transition-duration: 0.001ms !important;
          }
        }
      `}</style>

      <div className="prep-shell">
        <header className="prep-top">
          <div className="prep-brand">
            <div className="prep-mark" aria-hidden="true" />
            <div>
              <p className="prep-eyebrow">Antigravity interview</p>
              <h1 className="prep-title">Preparing S. V. S. Apparao — Product Analyst</h1>
            </div>
          </div>
          <div className="prep-loader" style={{ "--progress": `${progress}%` } as React.CSSProperties}>
            <div className="prep-loader-row">
              <span>{MAP_STATUS[statusIndex]}</span>
              <span>{progress}%</span>
            </div>
            <div className="prep-bar" aria-label="Interview map preparation progress">
              <span />
            </div>
          </div>
        </header>

        <section className="prep-grid">
          <aside className="prep-panel prep-left">
            <div>
              <p className="prep-eyebrow">AI interviewer</p>
              <h2 className="prep-section-title">
                {step.owner === "ai" ? "Interviewer has the floor" : "Interviewer presence"}
              </h2>
            </div>
            <div className="prep-aura-box">
              <AgentAudioVisualizerAura
                size="lg"
                state={step.auraState}
                color={step.auraColor}
                colorShift={step.shift}
              />
            </div>
            <p className="prep-aura-caption">
              The interviewer is represented as an abstract presence, not a fake human face.
            </p>
          </aside>

          <section className="prep-panel prep-stage">
            <div className="prep-stage-top">
              <div className="prep-step-card">
                <div>
                  <p className="prep-eyebrow">{step.eyebrow}</p>
                  <h2 className="prep-step-title">{step.title}</h2>
                  <p className="prep-step-body">{step.body}</p>
                </div>
                <span className="prep-step-count">
                  {String(stepIndex + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")}
                </span>
              </div>
              <div className="prep-floor" aria-label="Turn ownership preview">
                <span className="prep-corner prep-ai-corner">AI corner</span>
                <span className="prep-track prep-ai-track"><span /></span>
                <span className="prep-turn-pill">Turn</span>
                <span className="prep-track prep-candidate-track"><span /></span>
                <span className="prep-corner prep-candidate-corner">Candidate corner</span>
              </div>
            </div>

            <div className="prep-stage-body">
              <article className="prep-question-card">
                <p className="prep-question-label">Interviewer's question</p>
                <h3 className="prep-question">{activeQuestion}</h3>
              </article>
              <article className="prep-answer-card">
                <p className="prep-eyebrow">Candidate answer live transcription</p>
                <p className="prep-answer-text">
                  {step.id === "answer" || step.id === "floor"
                    ? "I would enforce fencing at the storage write boundary because older replicas can still accept stale writes."
                    : "Your live answer appears here during your turn."}
                </p>
              </article>
            </div>

            <div className="prep-actions">
              <button className="prep-control" type="button">Repeat question</button>
              <button className="prep-control" type="button">Need a moment</button>
              <button className="prep-control" type="button">Fix last term</button>
              <button className="prep-control" type="button">End interview</button>
              <a className="prep-control primary" href="/visualizer-livekit-room-floor">
                Enter room
              </a>
            </div>
          </section>

          <aside className="prep-panel prep-right">
            <div>
              <p className="prep-eyebrow">Candidate corner</p>
              <h2 className="prep-section-title">
                {step.owner === "candidate" ? "Candidate has the floor" : "Camera and history"}
              </h2>
            </div>
            <div className="prep-camera-box">
              <div className="prep-avatar">SV</div>
            </div>
            <p className="prep-camera-caption">
              Candidate presence and turn history sit beside the stage without competing with the active question.
            </p>
          </aside>
        </section>

        <footer className="prep-nav">
          <div className="prep-step-dots" aria-label="Walkthrough steps">
            {STEPS.map((item, index) => (
              <button
                key={item.id}
                className={["prep-step-dot", index === stepIndex ? "active" : ""].join(" ")}
                type="button"
                aria-label={`Show ${item.title}`}
                onClick={() => goToStep(index)}
              />
            ))}
          </div>
          <div className="prep-nav-actions">
            <button type="button" onClick={() => goToStep(stepIndex - 1)}>Previous</button>
            <button type="button" onClick={() => setIsPlaying((playing) => !playing)}>
              {isPlaying ? "Pause" : "Play"}
            </button>
            <button type="button" onClick={() => goToStep(stepIndex + 1)}>Next</button>
          </div>
        </footer>
      </div>
    </main>
  );
}
