"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StageId = "seed" | "details" | "expect" | "rhythm" | "controls" | "camera" | "room" | "ready";

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
    label: "Preview",
    duration: 1300,
    progress: 0,
    title: "Interview preview",
    subtitle: "A short walkthrough before the live interview begins.",
  },
  {
    id: "details",
    label: "Details",
    duration: 3200,
    progress: 15,
    title: "First, confirm the basics.",
    subtitle: "The interview is tailored to your role and background so the questions stay relevant.",
  },
  {
    id: "expect",
    label: "Expect",
    duration: 3600,
    progress: 32,
    title: "What the conversation will feel like.",
    subtitle: "You will talk through your experience, explain your reasoning, and apply your judgment to practical situations.",
  },
  {
    id: "rhythm",
    label: "Turns",
    duration: 3400,
    progress: 48,
    title: "The room will show whose turn it is.",
    subtitle: "When the interviewer is speaking, listen. When it is your turn, answer naturally.",
  },
  {
    id: "controls",
    label: "Controls",
    duration: 3400,
    progress: 64,
    title: "You have simple controls.",
    subtitle: "Use them if you missed a question, need a moment, or want to correct a term.",
  },
  {
    id: "camera",
    label: "Camera",
    duration: 3200,
    progress: 78,
    title: "Camera and history stay on the side.",
    subtitle: "They are available when needed, but the current question remains the center of the interview.",
  },
  {
    id: "room",
    label: "Room",
    duration: 4200,
    progress: 92,
    title: "Here is the live room.",
    subtitle: "The interviewer presence, question, answer transcription, camera, and history all stay in clear zones.",
  },
  {
    id: "ready",
    label: "Ready",
    duration: 5200,
    progress: 100,
    title: "You are ready to begin.",
    subtitle: "Close the demo and enter the live interview when you are ready.",
  },
];

const DETAILS = [
  ["Candidate", "S. V. S. Apparao"],
  ["Role", "Product Analyst"],
  ["Experience", "3 years"],
  ["Recent work", "Product analytics, launch decisions, event instrumentation"],
  ["Interview focus", "Explain your decisions clearly and reason through follow-up questions"],
];

const EXPECTATIONS = [
  { title: "Your experience", body: "You may begin with projects, responsibilities, and decisions you have actually owned." },
  { title: "Deeper reasoning", body: "The interviewer may ask follow-up questions so you can show how you think." },
  { title: "Applied judgment", body: "You may be asked to apply your answer to a realistic work situation and explain the tradeoff." },
];

const CONTROL_CARDS = [
  { title: "Repeat question", body: "Hear the current question again if you missed part of it." },
  { title: "Need a moment", body: "Take a short pause without losing your place." },
  { title: "Fix last term", body: "Correct a name, tool, company, or technical term." },
  { title: "End interview", body: "Close the interview only when you intentionally want to stop." },
];

const CAMERA_CARDS = [
  { title: "Camera preview", body: "Your camera remains available for the live interview." },
  { title: "Hide stream", body: "Hide the preview locally while keeping the session ready." },
  { title: "Turn history", body: "Past questions and answers are stored separately from the live answer." },
  { title: "Full transcript", body: "Open the full record when you need context, then return to focus." },
];

function auraFor(stage: StageId): AgentState {
  if (stage === "room") return "speaking";
  if (stage === "rhythm") return "listening";
  return "idle";
}

export default function CandidateMapPrepPage() {
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
    <main className="candidate-prep" data-stage={stage.id} style={style}>
      <style>{`
        .candidate-prep {
          --black: #050606;
          --cream: #f3eee4;
          --paper: #ece2d1;
          --muted: #b8b0a3;
          --teal: #31c5df;
          --green: #7fe2ae;
          --amber: #d9a24d;
          min-height: 100vh;
          overflow: hidden;
          color: white;
          font-family: var(--font-geist-sans), Inter, ui-sans-serif, system-ui, sans-serif;
          background:
            radial-gradient(42rem 28rem at 74% 18%, rgba(49,197,223,0.14), transparent 62%),
            radial-gradient(38rem 26rem at 20% 82%, rgba(127,226,174,0.1), transparent 64%),
            linear-gradient(180deg, #071112 0%, #030404 100%);
        }
        .candidate-prep::before {
          content: "";
          position: fixed;
          inset: -20%;
          pointer-events: none;
          background: radial-gradient(circle, rgba(243,238,228,0.18) 0 1px, transparent 1.5px);
          background-size: 34px 34px;
          opacity: 0.07;
          mask-image: radial-gradient(ellipse at center, black 0 58%, transparent 78%);
        }
        h1, h2, h3, p { margin-top: 0; }
        button { font: inherit; }
        .stage {
          position: relative;
          z-index: 1;
          min-height: 100vh;
          display: grid;
          place-items: center;
          padding: 34px;
        }
        .shell {
          width: min(1380px, calc(100vw - 68px));
          min-height: min(760px, calc(100vh - 92px));
          overflow: hidden;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 34px;
          background:
            radial-gradient(50rem 24rem at 72% 12%, rgba(49,197,223,0.12), transparent 60%),
            rgba(5,8,9,0.92);
          box-shadow: 0 40px 130px rgba(0,0,0,0.62), inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .candidate-prep[data-stage="seed"] .shell {
          width: 210px;
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
          border-radius: 999px;
          background: var(--teal);
          box-shadow: 0 0 28px rgba(49,197,223,0.62);
        }
        .candidate-prep[data-stage="seed"] .seed-pill { display: flex; }
        .content { display: grid; grid-template-rows: auto 1fr; min-height: inherit; }
        .candidate-prep[data-stage="seed"] .content { display: none; }
        .top {
          display: grid;
          grid-template-columns: minmax(0,1fr) 360px;
          gap: 24px;
          align-items: center;
          padding: 26px 30px;
          border-bottom: 1px solid rgba(243,238,228,0.1);
        }
        .brand { display: flex; align-items: center; gap: 16px; min-width: 0; }
        .mark {
          width: 52px;
          height: 52px;
          border-radius: 18px;
          display: grid;
          place-items: center;
          background: radial-gradient(circle at 38% 36%, rgba(49,197,223,0.56), rgba(49,197,223,0.05) 62%, rgba(0,0,0,0.82));
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.1), 0 0 34px rgba(49,197,223,0.16);
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
          color: rgba(188,234,240,0.75);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.25em;
          text-transform: uppercase;
        }
        .brand h1 { margin: 5px 0 0; font-size: 24px; line-height: 1.05; }
        .progress { display: grid; gap: 9px; color: rgba(243,238,228,0.58); font-size: 12px; }
        .progress-row { display: flex; justify-content: space-between; }
        .progress-bar { height: 7px; overflow: hidden; border-radius: 999px; background: rgba(243,238,228,0.12); }
        .progress-bar::after {
          content: "";
          display: block;
          width: var(--progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--teal), var(--green));
          transition: width 520ms ease;
        }
        .body {
          display: grid;
          grid-template-columns: minmax(0, 0.92fr) minmax(380px, 1.18fr);
          gap: 28px;
          align-items: center;
          padding: 36px;
        }
        .copy h2 {
          margin: 12px 0 0;
          max-width: 660px;
          font-size: clamp(42px, 5.5vw, 82px);
          line-height: 0.93;
          letter-spacing: 0;
        }
        .copy p {
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
        .visual { min-height: 470px; display: grid; align-content: center; gap: 16px; }
        .paper {
          width: min(760px, 100%);
          justify-self: end;
          border-radius: 30px;
          padding: 26px;
          color: #14110f;
          background: linear-gradient(180deg, var(--cream), var(--paper));
          box-shadow: 0 36px 120px rgba(0,0,0,0.36);
        }
        .paper h3 { margin: 0 0 18px; font-size: 26px; }
        .paper-row {
          display: grid;
          grid-template-columns: 170px 1fr;
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
        .cards {
          display: grid;
          grid-template-columns: repeat(3, minmax(0,1fr));
          gap: 14px;
        }
        .card {
          min-height: 176px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 26px;
          padding: 22px;
          background: rgba(255,255,255,0.045);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .card strong { display: block; font-size: 22px; line-height: 1.05; }
        .card p { margin: 18px 0 0; color: rgba(243,238,228,0.64); font-size: 14px; line-height: 1.5; }
        .turn-card {
          display: grid;
          gap: 22px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 30px;
          padding: 30px;
          background: rgba(255,255,255,0.045);
        }
        .turn-line {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          gap: 14px;
          align-items: center;
        }
        .turn-line span { height: 3px; border-radius: 999px; background: rgba(243,238,228,0.14); }
        .turn-line span.active { background: linear-gradient(90deg, transparent, var(--teal)); box-shadow: 0 0 22px rgba(49,197,223,0.24); }
        .turn-line strong {
          border: 1px solid rgba(49,197,223,0.24);
          border-radius: 999px;
          padding: 10px 16px;
          color: var(--cream);
          font-size: 11px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .turn-explain {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .turn-explain div {
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 22px;
          padding: 18px;
          background: rgba(0,0,0,0.3);
        }
        .turn-explain strong { display: block; margin-bottom: 8px; }
        .turn-explain p { margin: 0; color: rgba(243,238,228,0.62); line-height: 1.5; }
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
        .label {
          display: block;
          margin-bottom: 13px;
          color: rgba(188,234,240,0.72);
          font-size: 10px;
          font-weight: 860;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        }
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
        .room-turn {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          gap: 12px;
          align-items: center;
          margin-bottom: 18px;
        }
        .room-turn span { height: 2px; border-radius: 999px; background: rgba(243,238,228,0.14); }
        .room-turn span:last-child { background: linear-gradient(90deg, rgba(243,238,228,0.14), var(--teal)); }
        .room-turn strong {
          border: 1px solid rgba(49,197,223,0.26);
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
          box-shadow: inset 0 0 0 1px rgba(243,238,228,0.08), 0 0 34px rgba(49,197,223,0.12);
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
        .ready-card {
          justify-self: end;
          width: min(650px, 100%);
          border-radius: 34px;
          padding: 34px;
          color: #14110f;
          background: linear-gradient(180deg, var(--cream), var(--paper));
          box-shadow: 0 34px 120px rgba(0,0,0,0.36);
        }
        .ready-card h3 { margin: 0; font-size: clamp(42px, 5vw, 72px); line-height: 0.94; }
        .ready-card p { margin: 18px 0 0; color: rgba(20,17,15,0.62); line-height: 1.55; }
        .ready-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }
        .ready-actions .pill { color: #14110f; border-color: rgba(20,17,15,0.18); background: rgba(255,255,255,0.42); }
        .ready-actions .primary { background: #14110f; color: var(--cream); }
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
        .dots button.active { background: linear-gradient(90deg, var(--teal), var(--green)); }
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
        @media (max-width: 1120px) {
          .body { grid-template-columns: 1fr; }
          .visual { min-height: auto; }
          .room-artifact { grid-template-columns: 1fr; }
          .room-artifact .room-panel:first-child, .room-artifact .room-panel:last-child { display: none; }
        }
        @media (max-width: 760px) {
          .stage { padding: 14px; }
          .shell { width: calc(100vw - 28px); border-radius: 26px; }
          .top { grid-template-columns: 1fr; padding: 20px; }
          .body { padding: 22px; }
          .cards, .turn-explain { grid-template-columns: 1fr; }
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
                  <h1>Candidate walkthrough</h1>
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
              <div className="copy">
                <p className="kicker">{stage.label}</p>
                <h2>{stage.title}</h2>
                <p>{stage.subtitle}</p>
                <span className="stage-count">{String(stageIndex + 1).padStart(2, "0")} / {String(STAGES.length).padStart(2, "0")}</span>
              </div>

              <div className="visual">
                {stage.id === "details" && (
                  <article className="paper">
                    <h3>Your interview setup</h3>
                    {DETAILS.map(([label, value]) => (
                      <div className="paper-row" key={label}>
                        <span>{label}</span>
                        <span>{value}</span>
                      </div>
                    ))}
                  </article>
                )}

                {stage.id === "expect" && (
                  <div className="cards">
                    {EXPECTATIONS.map((item) => (
                      <article className="card" key={item.title}>
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                      </article>
                    ))}
                  </div>
                )}

                {stage.id === "rhythm" && (
                  <section className="turn-card">
                    <div className="turn-line"><span /><strong>Turn</strong><span className="active" /></div>
                    <div className="turn-explain">
                      <div>
                        <strong>Interviewer&apos;s turn</strong>
                        <p>The interviewer is speaking or preparing the next question. Listen until the room moves the floor to you.</p>
                      </div>
                      <div>
                        <strong>Your turn</strong>
                        <p>The candidate side lights up. Answer naturally; the room will keep your live transcription below the question.</p>
                      </div>
                    </div>
                  </section>
                )}

                {stage.id === "controls" && (
                  <div className="cards">
                    {CONTROL_CARDS.map((item) => (
                      <article className="card" key={item.title}>
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                      </article>
                    ))}
                  </div>
                )}

                {stage.id === "camera" && (
                  <div className="cards">
                    {CAMERA_CARDS.map((item) => (
                      <article className="card" key={item.title}>
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                      </article>
                    ))}
                  </div>
                )}

                {stage.id === "room" && (
                  <section className="room-artifact">
                    <aside className="room-panel">
                      <span className="label">AI interviewer</span>
                      <h3>Presence</h3>
                      <div className="mini-aura">
                        <AgentAudioVisualizerAura size="md" state={auraFor(stage.id)} color="#31C5DF" colorShift={0.24} themeMode="dark" />
                      </div>
                    </aside>
                    <section className="room-panel">
                      <div className="room-turn"><span /><strong>Your turn</strong><span /></div>
                      <div className="question">
                        <span className="label">Interviewer&apos;s question</span>
                        <p>Walk me through one product decision where the data was not clean.</p>
                      </div>
                      <div className="answer-strip">
                        <span className="label">Candidate answer live transcription</span>
                        Your answer appears here while the question stays anchored above it.
                      </div>
                      <div className="room-controls">
                        <button className="pill" type="button">Repeat question</button>
                        <button className="pill" type="button">Need a moment</button>
                        <button className="pill" type="button">Fix last term</button>
                        <button className="pill" type="button">Hide stream</button>
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

                {(stage.id === "ready" || stage.id === "seed") && (
                  <article className="ready-card">
                    <h3>Begin when you feel ready.</h3>
                    <p>The interview will keep the current question centered, show your turn clearly, and give you simple controls if you need them.</p>
                    <div className="ready-actions">
                      <button className="pill primary" type="button">Engage interview</button>
                      <button className="pill" type="button">Close demo</button>
                    </div>
                  </article>
                )}
              </div>
            </section>
          </div>
        </div>
      </section>

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
