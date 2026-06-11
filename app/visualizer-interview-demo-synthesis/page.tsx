"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type StageId =
  | "seed"
  | "claim"
  | "brief"
  | "assembly"
  | "floor"
  | "room"
  | "report"
  | "simulation"
  | "synthesis";

type Stage = {
  id: StageId;
  label: string;
  title: string;
  subtitle: string;
  progress: number;
  duration: number;
};

type CursorStep = {
  target: string;
  active?: string;
  duration: number;
  hold?: number;
  click?: boolean;
};

type CursorPoint = {
  x: number;
  y: number;
  click: boolean;
  visible: boolean;
};

const STAGES: Stage[] = [
  {
    id: "seed",
    label: "Start",
    title: "Start interview simulation",
    subtitle: "One guided loop from claim to live room to decision evidence.",
    progress: 0,
    duration: 2600,
  },
  {
    id: "claim",
    label: "Claim",
    title: "A resume claim is not evidence. This is.",
    subtitle: "The system converts a polished claim into a live test and a bounded hiring signal.",
    progress: 12,
    duration: 7400,
  },
  {
    id: "brief",
    label: "Brief",
    title: "The room starts from role context.",
    subtitle: "The interview is grounded in the candidate, the role, and the decision the hiring team must make.",
    progress: 24,
    duration: 6800,
  },
  {
    id: "assembly",
    label: "Build",
    title: "The interview map compiles into a room.",
    subtitle: "Resume evidence becomes claim surfaces, live scenarios, turn policy, and report contract.",
    progress: 36,
    duration: 7600,
  },
  {
    id: "floor",
    label: "Turns",
    title: "Floor ownership is visible.",
    subtitle: "The system shows who owns the turn, when the candidate is answering, and when the interviewer is thinking.",
    progress: 49,
    duration: 7200,
  },
  {
    id: "room",
    label: "Room",
    title: "The live room keeps pressure legible.",
    subtitle: "Question, answer, controls, camera, and history stay in clear zones while the conversation moves.",
    progress: 62,
    duration: 7600,
  },
  {
    id: "report",
    label: "Report",
    title: "The transcript becomes a decision package.",
    subtitle: "The buyer gets a verdict, calibrated claims, tested strengths, scoped risks, and useful follow-ups.",
    progress: 76,
    duration: 7600,
  },
  {
    id: "simulation",
    label: "Simulation",
    title: "The same evidence model extends into real work.",
    subtitle: "For engineering roles, candidates act inside a workbench: code, tests, terminal output, and recovery.",
    progress: 89,
    duration: 7000,
  },
  {
    id: "synthesis",
    label: "Synthesis",
    title: "One system. Two surfaces.",
    subtitle: "A calm candidate room on one side. A defensible hiring package on the other.",
    progress: 100,
    duration: 6200,
  },
];

const CURSOR_SCRIPT: Record<StageId, CursorStep[]> = {
  seed: [{ target: "seed-pill", active: "seed-pill", duration: 900, hold: 360, click: true }],
  claim: [
    { target: "claim-resume", active: "claim-resume", duration: 980, hold: 620 },
    { target: "claim-question", active: "claim-question", duration: 980, hold: 900 },
    { target: "claim-decision", active: "claim-decision", duration: 920, hold: 960, click: true },
  ],
  brief: [
    { target: "brief-candidate", active: "brief-candidate", duration: 620, hold: 300 },
    { target: "brief-role", active: "brief-role", duration: 620, hold: 300 },
    { target: "brief-signal", active: "brief-signal", duration: 620, hold: 340 },
    { target: "brief-claim", active: "brief-claim", duration: 620, hold: 360 },
    { target: "brief-scenario", active: "brief-scenario", duration: 780, hold: 760 },
    { target: "brief-goal", active: "brief-goal", duration: 640, hold: 520, click: true },
  ],
  assembly: [
    { target: "build-0", active: "build-0", duration: 620, hold: 250 },
    { target: "build-1", active: "build-1", duration: 620, hold: 250 },
    { target: "build-2", active: "build-2", duration: 620, hold: 250 },
    { target: "build-3", active: "build-3", duration: 620, hold: 250 },
    { target: "build-4", active: "build-4", duration: 620, hold: 650, click: true },
  ],
  floor: [
    { target: "floor-ai", active: "floor-ai", duration: 820, hold: 620 },
    { target: "floor-rail", active: "floor-rail", duration: 780, hold: 680 },
    { target: "floor-candidate", active: "floor-candidate", duration: 850, hold: 700 },
    { target: "floor-rail", active: "floor-rail", duration: 760, hold: 480, click: true },
  ],
  room: [
    { target: "room-question", active: "room-question", duration: 860, hold: 680 },
    { target: "room-transcript", active: "room-transcript", duration: 760, hold: 760 },
    { target: "room-repeat", active: "room-repeat", duration: 620, hold: 420, click: true },
    { target: "room-history", active: "room-history", duration: 780, hold: 760 },
    { target: "room-collapse", active: "room-collapse", duration: 620, hold: 540, click: true },
  ],
  report: [
    { target: "report-verdict", active: "report-verdict", duration: 880, hold: 780 },
    { target: "report-role", active: "report-role", duration: 700, hold: 480 },
    { target: "report-signal", active: "report-signal", duration: 700, hold: 480 },
    { target: "report-risk", active: "report-risk", duration: 700, hold: 480 },
    { target: "report-coverage", active: "report-coverage", duration: 700, hold: 680, click: true },
  ],
  simulation: [
    { target: "sim-code", active: "sim-code", duration: 820, hold: 640 },
    { target: "sim-failure", active: "sim-failure", duration: 820, hold: 760 },
    { target: "sim-diff", active: "sim-diff", duration: 820, hold: 780, click: true },
  ],
  synthesis: [
    { target: "surface-candidate", active: "surface-candidate", duration: 900, hold: 640 },
    { target: "surface-report", active: "surface-report", duration: 1050, hold: 760 },
    { target: "surface-candidate", active: "surface-candidate", duration: 1050, hold: 520 },
    { target: "surface-report", active: "surface-report", duration: 1050, hold: 840, click: true },
  ],
};

const BRIEF_ROWS = [
  ["brief-candidate", "Candidate", "S. V. S. Apparao"],
  ["brief-role", "Role", "Product Analyst"],
  ["brief-signal", "Experience signal", "Launch analytics, dashboard quality, stakeholder decisions"],
  ["brief-claim", "Claim under test", "Owned launch analytics for a product rollout"],
  ["brief-scenario", "Live scenario", "A conversion drop appears, but instrumentation may be unreliable"],
  ["brief-goal", "Session goal", "Observe reasoning, recovery, judgment, and communication under follow-up"],
];

const BUILD_STEPS = [
  ["Reading resume evidence", "claims, seniority, role proof"],
  ["Extracting claim surfaces", "what must hold up live"],
  ["Selecting test scenario", "metric drop under ambiguity"],
  ["Installing turn policy", "ask, answer, pause, recover"],
  ["Preparing report contract", "role fit, signals, risks, follow-ups"],
];

const REPORT_CARDS = [
  ["report-role", "Role fit calibration", "Scoped yes", "Strong for product analytics work with metric-quality ambiguity."],
  ["report-signal", "Strongest signal", "Judgment under follow-up", "Separated real conversion movement from event instrumentation noise."],
  ["report-risk", "Scoped tested risks", "2 unresolved", "Ownership boundaries and monitoring thresholds need human follow-up."],
  ["report-coverage", "Knowledge coverage", "Transparent", "The report separates tested knowledge from untested assumptions."],
];

const SIM_LINES = [
  "if conversion_drop > threshold:",
  "    compare(cohort, event_version, release_window)",
  "    assert dashboard.grain == decision_grain",
  "    explain(confounders, recovery_plan)",
];

function auraState(stage: StageId, activeKey: string): AgentState {
  if (stage === "room" || activeKey === "floor-ai") return "speaking";
  if (stage === "assembly" || stage === "report" || activeKey === "floor-rail") return "thinking";
  return "idle";
}

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3);
}

function cubicPoint(
  start: { x: number; y: number },
  c1: { x: number; y: number },
  c2: { x: number; y: number },
  end: { x: number; y: number },
  t: number,
) {
  const inv = 1 - t;
  return {
    x:
      inv * inv * inv * start.x +
      3 * inv * inv * t * c1.x +
      3 * inv * t * t * c2.x +
      t * t * t * end.x,
    y:
      inv * inv * inv * start.y +
      3 * inv * inv * t * c1.y +
      3 * inv * t * t * c2.y +
      t * t * t * end.y,
  };
}

function isInside(point: { x: number; y: number }, rect?: DOMRect) {
  if (!rect) return false;
  return point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom;
}

function TypeLine({ active, text }: { active: boolean; text: string }) {
  const [count, setCount] = useState(active ? 0 : text.length);

  useEffect(() => {
    if (!active) {
      setCount(text.length);
      return;
    }

    setCount(0);
    let frame = 0;
    let start: number | null = null;
    const duration = Math.max(420, text.length * 26);

    const tick = (now: number) => {
      if (start === null) start = now;
      const progress = Math.min(1, (now - start) / duration);
      setCount(Math.floor(progress * text.length));
      if (progress < 1) frame = window.requestAnimationFrame(tick);
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [active, text]);

  return (
    <span>
      {text.slice(0, count)}
      {active && count < text.length && <span className="type-caret" />}
    </span>
  );
}

export default function SynthesisInterviewDemoPage() {
  const [stageIndex, setStageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [activeKey, setActiveKey] = useState("");
  const [visitedKeys, setVisitedKeys] = useState<string[]>([]);
  const [cursor, setCursor] = useState<CursorPoint>({ x: 0, y: 0, click: false, visible: false });
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const rootRef = useRef<HTMLElement | null>(null);
  const rectCache = useRef<Map<string, DOMRect>>(new Map());
  const cursorPosition = useRef({ x: 0, y: 0 });

  const stage = STAGES[stageIndex];
  const script = CURSOR_SCRIPT[stage.id];
  const completeCount = useMemo(
    () => visitedKeys.filter((key) => key.startsWith("build-")).length,
    [visitedKeys],
  );

  useEffect(() => {
    setPrefersReducedMotion(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);

  useEffect(() => {
    if (!isPlaying || stageIndex === STAGES.length - 1) return;
    const timer = window.setTimeout(() => {
      setStageIndex((current) => Math.min(STAGES.length - 1, current + 1));
    }, stage.duration);
    return () => window.clearTimeout(timer);
  }, [isPlaying, stage.duration, stageIndex]);

  useEffect(() => {
    setActiveKey("");
    setVisitedKeys([]);

    const cacheRects = () => {
      const next = new Map<string, DOMRect>();
      rootRef.current?.querySelectorAll<HTMLElement>("[data-target]").forEach((element) => {
        const key = element.dataset.target;
        if (key) next.set(key, element.getBoundingClientRect());
      });
      rectCache.current = next;
    };

    cacheRects();
    const resize = () => cacheRects();
    window.addEventListener("resize", resize);

    if (prefersReducedMotion) {
      const last = script[script.length - 1];
      const rect = rectCache.current.get(last.target);
      if (rect) {
        const point = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        cursorPosition.current = point;
        setCursor({ ...point, click: false, visible: true });
      }
      setActiveKey(last.active ?? last.target);
      setVisitedKeys(script.map((step) => step.active ?? step.target));
      return () => window.removeEventListener("resize", resize);
    }

    let cancelled = false;
    let frame = 0;
    const initial = cursorPosition.current.x
      ? cursorPosition.current
      : { x: window.innerWidth * 0.78, y: window.innerHeight * 0.78 };
    cursorPosition.current = initial;
    setCursor({ ...initial, click: false, visible: true });

    const runStep = (index: number, start: { x: number; y: number }) => {
      if (cancelled || index >= script.length) return;

      cacheRects();
      const step = script[index];
      const rect = rectCache.current.get(step.target);
      const end = rect
        ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
        : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const arc = Math.min(160, Math.max(64, Math.abs(dx) * 0.16 + Math.abs(dy) * 0.08));
      const c1 = { x: start.x + dx * 0.32, y: start.y - arc };
      const c2 = { x: start.x + dx * 0.72, y: end.y + arc * 0.52 };
      let hasCollided = false;
      let startTime: number | null = null;

      const tick = (now: number) => {
        if (cancelled) return;
        if (startTime === null) startTime = now;
        const elapsed = now - startTime;
        const raw = Math.min(1, elapsed / step.duration);
        const eased = easeOutCubic(raw);
        const point = cubicPoint(start, c1, c2, end, eased);
        cursorPosition.current = point;
        const collided = isInside(point, rect) || raw > 0.78;

        if (collided && !hasCollided) {
          hasCollided = true;
          const active = step.active ?? step.target;
          setActiveKey(active);
          setVisitedKeys((current) => (current.includes(active) ? current : [...current, active]));
        }

        setCursor({
          ...point,
          click: Boolean(step.click && raw > 0.84 && raw < 0.94),
          visible: true,
        });

        if (raw < 1) {
          frame = window.requestAnimationFrame(tick);
        } else {
          window.setTimeout(() => runStep(index + 1, end), step.hold ?? 260);
        }
      };

      frame = window.requestAnimationFrame(tick);
    };

    window.setTimeout(() => {
      if (!cancelled) runStep(0, initial);
    }, 120);

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
    };
  }, [prefersReducedMotion, script, stage.id]);

  const style = useMemo(
    () =>
      ({
        "--progress": `${stage.progress}%`,
        "--build-progress": `${Math.min(100, (completeCount / BUILD_STEPS.length) * 100)}%`,
        "--cursor-x": `${cursor.x}px`,
        "--cursor-y": `${cursor.y}px`,
      }) as CSSProperties,
    [completeCount, cursor.x, cursor.y, stage.progress],
  );

  const goTo = (index: number) => {
    setIsPlaying(false);
    setStageIndex(index);
  };

  return (
    <main ref={rootRef} className="synthesis-demo" data-stage={stage.id} style={style}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=DM+Sans:wght@400;500;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');

        .synthesis-demo {
          --black: #030303;
          --cream: #f3eee4;
          --paper: #e8ddc8;
          --ink: #15120f;
          --muted: rgba(243,238,228,0.64);
          --dim: rgba(243,238,228,0.38);
          --line: rgba(243,238,228,0.13);
          --crail: #c15f3c;
          --amber: #d9a24d;
          --teal: #42d4e8;
          --green: #7fe2ae;
          min-height: 100svh;
          overflow: hidden;
          color: var(--cream);
          font-family: "DM Sans", var(--font-geist-sans), Inter, ui-sans-serif, system-ui, sans-serif;
          background:
            radial-gradient(58rem 32rem at 76% 18%, rgba(193,95,60,0.14), transparent 64%),
            radial-gradient(46rem 28rem at 16% 82%, rgba(66,212,232,0.1), transparent 66%),
            linear-gradient(180deg, #090807, #020202);
        }
        .synthesis-demo::before {
          content: "";
          position: fixed;
          inset: -18%;
          pointer-events: none;
          opacity: 0.075;
          background:
            linear-gradient(116deg, transparent 0 38%, rgba(243,238,228,0.08) 38.2% 38.7%, transparent 39% 100%),
            radial-gradient(circle, rgba(243,238,228,0.32) 0 1px, transparent 1.35px);
          background-size: auto, 34px 34px;
          mask-image: radial-gradient(ellipse at center, black 0 56%, transparent 80%);
        }
        .synthesis-demo[data-stage="report"] {
          background:
            radial-gradient(50rem 30rem at 72% 22%, rgba(217,162,77,0.16), transparent 64%),
            linear-gradient(180deg, #070605, #020202);
        }
        .synthesis-demo * { box-sizing: border-box; }
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
        .seed-wrap {
          display: none;
          place-items: center;
          gap: 18px;
        }
        .synthesis-demo[data-stage="seed"] .seed-wrap { display: grid; }
        .seed-pill {
          position: relative;
          min-width: min(440px, calc(100vw - 70px));
          height: 72px;
          display: flex;
          justify-content: center;
          align-items: center;
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 0 30px;
          background: rgba(8,8,8,0.91);
          box-shadow: 0 32px 90px rgba(0,0,0,0.42);
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: 25px;
          font-weight: 700;
          animation: seed-breathe 2.4s ease-in-out infinite;
        }
        .seed-pill::after {
          content: "";
          position: absolute;
          inset: -28px;
          border-radius: inherit;
          background: radial-gradient(circle, rgba(193,95,60,0.16), transparent 64%);
          z-index: -1;
          animation: seed-halo 2.4s ease-in-out infinite;
        }
        .seed-sub {
          margin: 0;
          color: rgba(243,238,228,0.52);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        @keyframes seed-breathe {
          0%, 100% { transform: scale(0.99); }
          50% { transform: scale(1.015); }
        }
        @keyframes seed-halo {
          0%, 100% { opacity: 0.42; transform: scale(0.9); }
          50% { opacity: 1; transform: scale(1.1); }
        }
        .shell {
          width: min(1480px, calc(100vw - 64px));
          height: min(830px, calc(100svh - 108px));
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
        .synthesis-demo[data-stage="seed"] .shell { display: none; }
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
          font-weight: 800;
          letter-spacing: 0.24em;
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
          grid-template-columns: minmax(360px, 0.78fr) minmax(650px, 1.22fr);
          gap: 34px;
          align-items: center;
          padding: 38px 42px;
          overflow: hidden;
          animation: stage-enter 440ms cubic-bezier(.16, 1, .3, 1) both;
        }
        @keyframes stage-enter {
          from { opacity: 0; transform: translateY(14px) scale(0.99); filter: blur(2px); }
          to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
        }
        .hero h2 {
          max-width: 720px;
          margin: 14px 0 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: clamp(50px, 5.9vw, 88px);
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
        .count {
          display: inline-flex;
          min-width: 70px;
          justify-content: center;
          margin-top: 34px;
          padding: 10px 15px;
          border: 1px solid var(--line);
          border-radius: 999px;
          color: rgba(243,238,228,0.62);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 12px;
          font-weight: 800;
        }
        .canvas { min-width: 0; min-height: 0; }
        .claim-stack {
          position: relative;
          display: grid;
          gap: 18px;
          max-width: 720px;
          margin-left: auto;
        }
        .claim-link {
          position: absolute;
          left: 34px;
          top: 102px;
          bottom: 102px;
          width: 2px;
          border-radius: 999px;
          background: linear-gradient(180deg, rgba(217,162,77,0.7), rgba(66,212,232,0.64), rgba(127,226,174,0.72));
          transform-origin: top;
          transform: scaleY(0.25);
          opacity: 0.2;
          transition: transform 620ms ease, opacity 420ms ease;
        }
        .claim-card {
          position: relative;
          display: grid;
          grid-template-columns: 96px 1fr;
          gap: 18px;
          align-items: center;
          min-height: 142px;
          padding: 22px 24px 22px 30px;
          border: 1px solid rgba(243,238,228,0.13);
          border-radius: 28px;
          background: linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
          transform: translateZ(0) scale(1);
          opacity: 0.62;
          transition: transform 420ms cubic-bezier(.16,1,.3,1), opacity 320ms ease, border-color 320ms ease, background 320ms ease;
        }
        .claim-card.active {
          opacity: 1;
          transform: translateZ(0) scale(1.045);
          border-color: color-mix(in srgb, var(--accent), white 12%);
          background:
            radial-gradient(18rem 14rem at 88% 18%, color-mix(in srgb, var(--accent), transparent 80%), transparent 62%),
            linear-gradient(145deg, rgba(255,255,255,0.11), rgba(255,255,255,0.045));
          box-shadow: 0 28px 70px rgba(0,0,0,0.38);
          z-index: 2;
        }
        .claim-card.defocus {
          opacity: 0.34;
          transform: translateZ(0) scale(0.95);
        }
        .claim-card.active ~ .claim-card { opacity: 0.44; }
        .claim-orb {
          width: 74px;
          height: 74px;
          border-radius: 24px;
          display: grid;
          place-items: center;
          color: var(--ink);
          background: var(--paper);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 12px;
          font-weight: 900;
          letter-spacing: 0.13em;
          text-transform: uppercase;
        }
        .claim-card h3 { margin: 0; font-size: 31px; line-height: 1.04; letter-spacing: 0; }
        .claim-card p { margin: 12px 0 0; color: var(--muted); line-height: 1.45; font-size: 15px; }
        .claim-card.active .claim-orb { background: var(--accent); color: #080706; box-shadow: 0 0 30px color-mix(in srgb, var(--accent), transparent 35%); }
        .claim-stack:has(.claim-card.active) .claim-link { transform: scaleY(1); opacity: 0.7; }
        .brief-paper {
          width: min(760px, 100%);
          margin-left: auto;
          padding: 30px;
          border-radius: 30px;
          color: var(--ink);
          background:
            linear-gradient(140deg, rgba(255,255,255,0.68), transparent 40%),
            linear-gradient(180deg, #f3eee4, #dfd3be);
          box-shadow: 0 38px 110px rgba(0,0,0,0.38), inset 0 0 0 1px rgba(255,255,255,0.56);
        }
        .paper-head {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 18px;
          padding-bottom: 18px;
          border-bottom: 1px solid rgba(20,17,15,0.13);
        }
        .paper-head h3 {
          margin: 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: 34px;
          line-height: 0.98;
        }
        .paper-chip {
          border: 1px solid rgba(20,17,15,0.13);
          border-radius: 999px;
          padding: 10px 14px;
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .brief-rows { display: grid; gap: 10px; padding-top: 20px; }
        .brief-row {
          display: grid;
          grid-template-columns: 190px 1fr;
          gap: 18px;
          align-items: center;
          min-height: 60px;
          padding: 15px 18px;
          border: 1px solid rgba(20,17,15,0.08);
          border-radius: 18px;
          background: rgba(255,255,255,0.32);
          filter: blur(1.6px);
          opacity: 0.54;
          transform: translateZ(0) scale(0.985);
          transition: transform 320ms ease, opacity 320ms ease, filter 320ms ease, background 320ms ease;
        }
        .brief-row.active, .brief-row.visited {
          filter: blur(0);
          opacity: 1;
          transform: translateZ(0) scale(1);
        }
        .brief-row.active {
          background: rgba(217,162,77,0.22);
          box-shadow: 0 14px 30px rgba(88,58,18,0.12);
        }
        .brief-label {
          color: rgba(20,17,15,0.52);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 900;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .brief-value { font-size: 17px; line-height: 1.3; font-weight: 700; }
        .terminal {
          width: min(820px, 100%);
          margin-left: auto;
          border: 1px solid rgba(127,226,174,0.18);
          border-radius: 30px;
          background:
            radial-gradient(28rem 20rem at 86% 22%, rgba(127,226,174,0.09), transparent 62%),
            #020403;
          box-shadow: 0 36px 100px rgba(0,0,0,0.44), inset 0 0 0 1px rgba(255,255,255,0.025);
          overflow: hidden;
        }
        .terminal-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 18px;
          padding: 18px 22px;
          border-bottom: 1px solid rgba(127,226,174,0.12);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .build-progress {
          width: 220px;
          height: 5px;
          border-radius: 999px;
          background: rgba(243,238,228,0.1);
          overflow: hidden;
        }
        .build-progress::after {
          content: "";
          display: block;
          width: var(--build-progress);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--amber), var(--green));
          transition: width 380ms ease;
        }
        .terminal-body {
          display: grid;
          grid-template-columns: 1fr 250px;
          gap: 26px;
          padding: 28px;
        }
        .build-lines { display: grid; gap: 14px; }
        .build-line {
          display: grid;
          grid-template-columns: 18px 1fr;
          gap: 14px;
          align-items: start;
          padding: 15px;
          border: 1px solid rgba(243,238,228,0.08);
          border-radius: 16px;
          background: rgba(255,255,255,0.025);
          opacity: 0.46;
          transform: translateZ(0) translateX(-8px);
          transition: transform 320ms ease, opacity 320ms ease, border-color 320ms ease;
        }
        .build-line.visited {
          opacity: 1;
          transform: translateZ(0) translateX(0);
          border-color: rgba(127,226,174,0.25);
        }
        .dot {
          width: 11px;
          height: 11px;
          margin-top: 4px;
          border-radius: 50%;
          background: rgba(243,238,228,0.18);
        }
        .build-line.visited .dot { background: var(--green); box-shadow: 0 0 18px rgba(127,226,174,0.56); }
        .build-main {
          margin: 0;
          color: rgba(243,238,228,0.9);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 14px;
          font-weight: 800;
        }
        .build-sub {
          margin: 5px 0 0;
          color: rgba(243,238,228,0.48);
          font-size: 13px;
        }
        .aura-stage {
          min-height: 390px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(243,238,228,0.08);
          border-radius: 24px;
          background: radial-gradient(circle at center, rgba(217,162,77,0.12), transparent 66%);
          overflow: hidden;
        }
        .floor-map {
          display: grid;
          grid-template-columns: minmax(190px, 0.82fr) minmax(340px, 1.25fr) minmax(190px, 0.82fr);
          gap: 18px;
          width: min(860px, 100%);
          margin-left: auto;
        }
        .floor-zone {
          min-height: 470px;
          display: grid;
          align-content: start;
          gap: 16px;
          padding: 22px;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 28px;
          background: rgba(255,255,255,0.035);
          opacity: 0.58;
          transform: translateZ(0) scale(0.97);
          transition: opacity 360ms ease, transform 360ms ease, border-color 360ms ease, background 360ms ease;
        }
        .floor-zone.active, .floor-zone.visited {
          opacity: 1;
          transform: translateZ(0) scale(1);
          border-color: rgba(127,226,174,0.25);
        }
        .floor-zone.active { background: rgba(255,255,255,0.06); box-shadow: 0 26px 70px rgba(0,0,0,0.34); }
        .zone-head {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 14px;
        }
        .zone-title {
          margin: 0;
          color: rgba(243,238,228,0.58);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 900;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .check {
          width: 22px;
          height: 22px;
          display: grid;
          place-items: center;
          border-radius: 50%;
          color: #04130b;
          background: rgba(243,238,228,0.16);
          font-size: 13px;
          opacity: 0.38;
          transform: scale(0.7);
          transition: transform 240ms ease, opacity 240ms ease, background 240ms ease;
        }
        .visited .check { opacity: 1; transform: scale(1); background: var(--green); }
        .floor-zone h3 { margin: 0; font-size: 25px; line-height: 1.05; }
        .floor-zone p { margin: 0; color: var(--muted); line-height: 1.45; font-size: 14px; }
        .turn-rail {
          display: grid;
          align-content: center;
          gap: 18px;
          text-align: center;
        }
        .rail-line {
          position: relative;
          height: 9px;
          border-radius: 999px;
          background: rgba(243,238,228,0.12);
          overflow: hidden;
        }
        .rail-line::after {
          content: "";
          position: absolute;
          top: 0;
          bottom: 0;
          width: 44%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--amber), var(--teal));
          transform: translateX(8%);
          transition: transform 440ms ease;
        }
        .floor-map:has(.candidate-active) .rail-line::after { transform: translateX(122%); }
        .room-preview {
          width: min(880px, 100%);
          margin-left: auto;
          display: grid;
          grid-template-columns: 190px minmax(320px, 1fr) 210px;
          gap: 16px;
          padding: 18px;
          border: 1px solid rgba(243,238,228,0.11);
          border-radius: 30px;
          background: rgba(255,255,255,0.035);
          box-shadow: 0 36px 100px rgba(0,0,0,0.38);
        }
        .room-panel, .question-column, .history-panel {
          min-height: 520px;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 24px;
          background: #030303;
          padding: 18px;
        }
        .room-panel { display: grid; align-content: start; gap: 18px; }
        .mini-aura {
          min-height: 178px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(243,238,228,0.08);
          border-radius: 20px;
          background: radial-gradient(circle at center, rgba(66,212,232,0.11), transparent 62%);
        }
        .question-column { display: grid; grid-template-rows: auto 1fr auto; gap: 14px; }
        .turn-pill {
          justify-self: center;
          display: inline-flex;
          align-items: center;
          gap: 12px;
          border: 1px solid rgba(66,212,232,0.22);
          border-radius: 999px;
          padding: 9px 15px;
          color: var(--cream);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 900;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .room-question {
          min-height: 270px;
          display: grid;
          align-content: center;
          padding: 24px;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 22px;
          background: #000;
          transition: border-color 260ms ease, transform 260ms ease;
        }
        .room-question.active, .transcript-box.active, .history-panel.active {
          border-color: rgba(66,212,232,0.34);
          transform: translateZ(0) scale(1.015);
        }
        .room-question h3 {
          margin: 8px 0 0;
          color: white;
          font-size: clamp(38px, 3.6vw, 58px);
          line-height: 0.96;
          letter-spacing: 0;
        }
        .transcript-box {
          min-height: 105px;
          border: 1px solid rgba(66,212,232,0.13);
          border-radius: 18px;
          padding: 16px;
          transition: border-color 260ms ease, transform 260ms ease;
        }
        .transcript-box p { margin: 8px 0 0; color: var(--muted); line-height: 1.45; font-size: 13px; }
        .controls { display: flex; flex-wrap: wrap; gap: 10px; }
        .control {
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 999px;
          padding: 11px 14px;
          color: rgba(243,238,228,0.72);
          background: rgba(255,255,255,0.06);
          transition: transform 220ms ease, border-color 220ms ease, color 220ms ease;
        }
        .control.active {
          transform: translateZ(0) scale(1.06);
          border-color: rgba(127,226,174,0.34);
          color: var(--cream);
        }
        .history-panel { display: grid; align-content: start; gap: 14px; }
        .camera {
          min-height: 155px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(243,238,228,0.08);
          border-radius: 20px;
          background: radial-gradient(circle at center, rgba(66,212,232,0.12), transparent 64%), #030303;
        }
        .avatar {
          width: 66px;
          height: 66px;
          display: grid;
          place-items: center;
          border-radius: 22px;
          color: var(--cream);
          background: #081516;
          font-size: 24px;
          font-weight: 900;
        }
        .history-item {
          border: 1px solid rgba(243,238,228,0.08);
          border-radius: 15px;
          padding: 13px;
          color: var(--muted);
          font-size: 12px;
          line-height: 1.45;
        }
        .collapse-btn {
          justify-self: start;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 999px;
          padding: 10px 13px;
          color: rgba(243,238,228,0.7);
          background: rgba(255,255,255,0.05);
        }
        .collapse-btn.active { border-color: rgba(127,226,174,0.34); color: var(--cream); transform: scale(1.04); }
        .report-board {
          width: min(860px, 100%);
          margin-left: auto;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
          align-items: stretch;
        }
        .verdict {
          grid-row: span 2;
          min-height: 545px;
          padding: 32px;
          border-radius: 34px;
          color: var(--ink);
          background:
            linear-gradient(145deg, rgba(255,255,255,0.72), transparent 46%),
            linear-gradient(180deg, #f3eee4, #ded2bd);
          box-shadow: 0 34px 100px rgba(0,0,0,0.42);
          transition: transform 360ms ease, box-shadow 360ms ease;
        }
        .verdict.active {
          transform: translateZ(0) scale(1.035);
          box-shadow: 0 42px 120px rgba(217,162,77,0.22);
        }
        .verdict h3 {
          margin: 18px 0 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: clamp(60px, 5.4vw, 92px);
          line-height: 0.9;
          letter-spacing: 0;
        }
        .verdict p {
          max-width: 440px;
          margin: 22px 0 0;
          color: rgba(20,17,15,0.62);
          font-size: 17px;
          line-height: 1.45;
        }
        .report-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
        .report-card {
          min-height: 178px;
          padding: 22px;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 24px;
          background: rgba(255,255,255,0.07);
          opacity: 0;
          transform: translateY(18px) scale(0.96);
          transition: transform 360ms cubic-bezier(.16,1,.3,1), opacity 360ms ease, border-color 260ms ease;
        }
        .report-card.visited, .report-card.active {
          opacity: 1;
          transform: translateY(0) scale(1);
        }
        .report-card.active {
          border-color: rgba(127,226,174,0.34);
          transform: translateY(-4px) scale(1.025);
        }
        .report-card h3 { margin: 0; font-size: 20px; line-height: 1.12; }
        .report-card strong {
          display: block;
          margin-top: 14px;
          color: var(--amber);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 12px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .report-card p { margin: 13px 0 0; color: var(--muted); line-height: 1.45; font-size: 13px; }
        .sim-workbench {
          width: min(900px, 100%);
          margin-left: auto;
          display: grid;
          grid-template-columns: minmax(390px, 1.1fr) minmax(280px, 0.9fr);
          gap: 18px;
        }
        .code-pane, .test-pane, .diff-pane {
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 24px;
          background: #020403;
          overflow: hidden;
          box-shadow: 0 30px 90px rgba(0,0,0,0.34);
        }
        .pane-title {
          margin: 0;
          padding: 15px 17px;
          border-bottom: 1px solid rgba(243,238,228,0.08);
          color: rgba(243,238,228,0.52);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 10px;
          font-weight: 900;
          letter-spacing: 0.15em;
          text-transform: uppercase;
        }
        .code-lines { display: grid; padding: 18px; gap: 10px; }
        .code-line {
          padding: 10px 12px;
          border-radius: 12px;
          color: rgba(243,238,228,0.72);
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 13px;
          transition: background 240ms ease, color 240ms ease, transform 240ms ease;
        }
        .code-line.active {
          color: var(--green);
          background: rgba(127,226,174,0.1);
          transform: translateX(5px);
        }
        .test-pane { min-height: 260px; }
        .failure {
          margin: 18px;
          padding: 17px;
          border: 1px solid rgba(193,95,60,0.22);
          border-radius: 18px;
          background: rgba(193,95,60,0.08);
          color: #ffb59c;
          font-family: "JetBrains Mono", var(--font-geist-mono), ui-monospace, monospace;
          font-size: 12px;
          line-height: 1.5;
          transition: transform 260ms ease, border-color 260ms ease;
        }
        .failure.active {
          transform: scale(1.04);
          border-color: rgba(193,95,60,0.52);
        }
        .diff-pane {
          grid-column: 1 / -1;
          padding-bottom: 18px;
        }
        .diff-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 14px;
          padding: 18px;
        }
        .diff-card {
          min-height: 125px;
          border: 1px solid rgba(243,238,228,0.08);
          border-radius: 16px;
          padding: 16px;
          color: var(--muted);
          font-size: 13px;
          line-height: 1.45;
          transition: transform 260ms ease, border-color 260ms ease;
        }
        .diff-card.active {
          transform: scale(1.025);
          border-color: rgba(127,226,174,0.28);
        }
        .synthesis-board {
          width: min(930px, 100%);
          margin-left: auto;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
        }
        .surface {
          min-height: 560px;
          border: 1px solid rgba(243,238,228,0.11);
          border-radius: 30px;
          padding: 22px;
          background: rgba(255,255,255,0.045);
          transition: transform 360ms ease, opacity 360ms ease, border-color 360ms ease;
        }
        .surface.active {
          transform: translateZ(0) scale(1.025);
          border-color: rgba(127,226,174,0.34);
        }
        .surface.dim { opacity: 0.56; }
        .surface.report {
          color: var(--ink);
          background: linear-gradient(180deg, #f3eee4, #e1d5bf);
        }
        .surface h3 {
          margin: 0;
          font-family: "Cormorant Garamond", Georgia, serif;
          font-size: 38px;
          line-height: 0.95;
        }
        .surface p { margin: 14px 0 0; color: var(--muted); line-height: 1.45; }
        .surface.report p { color: rgba(20,17,15,0.62); }
        .mini-room {
          margin-top: 22px;
          display: grid;
          grid-template-columns: 110px 1fr;
          gap: 14px;
        }
        .mini-question, .mini-card {
          border-radius: 18px;
          padding: 16px;
          border: 1px solid rgba(243,238,228,0.1);
          background: #020202;
          color: var(--cream);
        }
        .mini-question strong { display: block; margin-top: 8px; font-size: 24px; line-height: 1; }
        .surface-report-card {
          margin-top: 22px;
          border: 1px solid rgba(20,17,15,0.1);
          border-radius: 20px;
          padding: 20px;
          background: rgba(255,255,255,0.4);
          transition: transform 320ms ease, background 320ms ease;
        }
        .surface.report.active .surface-report-card {
          transform: scale(1.035);
          background: rgba(127,226,174,0.24);
        }
        .cursor {
          position: fixed;
          z-index: 30;
          left: 0;
          top: 0;
          width: 34px;
          height: 34px;
          pointer-events: none;
          opacity: 0;
          transform: translate3d(var(--cursor-x), var(--cursor-y), 0);
          transition: opacity 160ms ease;
        }
        .cursor.visible { opacity: 1; }
        .cursor-shape {
          position: absolute;
          left: -4px;
          top: -2px;
          width: 0;
          height: 0;
          border-left: 11px solid transparent;
          border-right: 11px solid transparent;
          border-bottom: 25px solid white;
          transform: rotate(-36deg);
          filter: drop-shadow(0 8px 16px rgba(0,0,0,0.5));
        }
        .cursor-shape::after {
          content: "";
          position: absolute;
          left: -8px;
          top: 4px;
          width: 0;
          height: 0;
          border-left: 8px solid transparent;
          border-right: 8px solid transparent;
          border-bottom: 19px solid #050505;
        }
        .cursor.clicking::after {
          content: "";
          position: absolute;
          left: -19px;
          top: -17px;
          width: 46px;
          height: 46px;
          border: 2px solid rgba(243,238,228,0.72);
          border-radius: 50%;
          animation: click-pulse 420ms ease-out both;
        }
        @keyframes click-pulse {
          from { opacity: 0.9; transform: scale(0.45); }
          to { opacity: 0; transform: scale(1.35); }
        }
        .type-caret {
          display: inline-block;
          width: 7px;
          height: 1em;
          margin-left: 3px;
          vertical-align: -0.15em;
          background: var(--green);
          animation: blink 0.8s step-end infinite;
        }
        @keyframes blink { 50% { opacity: 0; } }
        .controls-bar {
          position: fixed;
          right: 28px;
          bottom: 26px;
          z-index: 40;
          display: flex;
          gap: 10px;
        }
        .nav-button {
          border: 1px solid rgba(243,238,228,0.14);
          border-radius: 999px;
          padding: 14px 18px;
          color: rgba(243,238,228,0.72);
          background: rgba(18,18,18,0.78);
          backdrop-filter: blur(14px);
          cursor: pointer;
        }
        .nav-button:hover { color: var(--cream); border-color: rgba(243,238,228,0.26); }
        .dots {
          position: fixed;
          left: 50%;
          bottom: 34px;
          z-index: 25;
          display: flex;
          gap: 10px;
          transform: translateX(-50%);
        }
        .dot-nav {
          width: 44px;
          height: 8px;
          border: 1px solid rgba(243,238,228,0.1);
          border-radius: 999px;
          background: rgba(243,238,228,0.08);
        }
        .dot-nav.active {
          background: linear-gradient(90deg, var(--amber), var(--teal));
        }
        .mini-brand {
          position: fixed;
          left: 32px;
          bottom: 28px;
          z-index: 20;
          width: 50px;
          height: 50px;
          display: grid;
          place-items: center;
          border: 1px solid rgba(243,238,228,0.12);
          border-radius: 50%;
          color: white;
          background: rgba(0,0,0,0.62);
          font-size: 21px;
          font-weight: 800;
        }
        @media (max-width: 1100px) {
          .shell { height: auto; min-height: calc(100svh - 108px); overflow-y: auto; }
          .top, .body { grid-template-columns: 1fr; }
          .body { align-items: start; }
          .hero h2 { font-size: clamp(44px, 10vw, 72px); }
          .claim-stack, .brief-paper, .terminal, .floor-map, .room-preview, .report-board, .sim-workbench, .synthesis-board { margin-left: 0; width: 100%; }
          .floor-map, .room-preview, .report-board, .sim-workbench, .synthesis-board { grid-template-columns: 1fr; }
          .verdict { min-height: auto; grid-row: auto; }
          .room-panel, .question-column, .history-panel, .surface { min-height: auto; }
          .dots { display: none; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 1ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 1ms !important;
            scroll-behavior: auto !important;
          }
        }
      `}</style>

      <div className="viewport">
        <div className="seed-wrap">
          <div className="seed-pill" data-target="seed-pill">
            Start interview simulation
          </div>
          <p className="seed-sub">Cursor-driven product loop</p>
        </div>

        <section className="shell" aria-label="Antigravity synthesis demo">
          <header className="top">
            <div className="brand">
              <div className="mark" aria-hidden="true" />
              <div>
                <p className="kicker">Antigravity interview</p>
                <h1>Unified product demo synthesis</h1>
              </div>
            </div>
            <div className="chapters">
              <div className="chapter-labels">
                <span>{stage.label}</span>
                <span>{stage.progress}%</span>
              </div>
              <div className="chapter-bar" />
            </div>
          </header>

          <div className="body" key={stage.id}>
            <section className="hero">
              <p className="kicker">{stage.label}</p>
              <h2>{stage.title}</h2>
              <p>{stage.subtitle}</p>
              <span className="count">
                {String(stageIndex + 1).padStart(2, "0")} / {String(STAGES.length).padStart(2, "0")}
              </span>
            </section>

            <section className="canvas">{renderStage(stage.id, activeKey, visitedKeys, completeCount)}</section>
          </div>
        </section>
      </div>

      <div className={`cursor ${cursor.visible ? "visible" : ""} ${cursor.click ? "clicking" : ""}`} aria-hidden="true">
        <div className="cursor-shape" />
      </div>

      <div className="mini-brand" aria-hidden="true">
        N
      </div>

      <div className="dots" aria-hidden="true">
        {STAGES.map((item, index) => (
          <button
            key={item.id}
            className={`dot-nav ${index <= stageIndex ? "active" : ""}`}
            onClick={() => goTo(index)}
            title={item.label}
          />
        ))}
      </div>

      <nav className="controls-bar" aria-label="Demo controls">
        <button className="nav-button" onClick={() => goTo(Math.max(0, stageIndex - 1))}>
          Previous
        </button>
        <button className="nav-button" onClick={() => setIsPlaying((current) => !current)}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button className="nav-button" onClick={() => goTo(Math.min(STAGES.length - 1, stageIndex + 1))}>
          Next
        </button>
        <button
          className="nav-button"
          onClick={() => {
            setIsPlaying(false);
            setStageIndex(0);
          }}
        >
          Restart
        </button>
      </nav>
    </main>
  );
}

function renderStage(stage: StageId, activeKey: string, visitedKeys: string[], completeCount: number) {
  if (stage === "claim") return <ClaimStage activeKey={activeKey} />;
  if (stage === "brief") return <BriefStage activeKey={activeKey} visitedKeys={visitedKeys} />;
  if (stage === "assembly") return <AssemblyStage activeKey={activeKey} visitedKeys={visitedKeys} completeCount={completeCount} />;
  if (stage === "floor") return <FloorStage activeKey={activeKey} visitedKeys={visitedKeys} />;
  if (stage === "room") return <RoomStage activeKey={activeKey} />;
  if (stage === "report") return <ReportStage activeKey={activeKey} visitedKeys={visitedKeys} />;
  if (stage === "simulation") return <SimulationStage activeKey={activeKey} />;
  if (stage === "synthesis") return <SynthesisStage activeKey={activeKey} />;
  return null;
}

function ClaimStage({ activeKey }: { activeKey: string }) {
  const cards = [
    {
      key: "claim-resume",
      tag: "Input",
      title: "Owned launch analytics",
      body: "Looks promising on paper, but the team cannot yet tell whether the judgment survives a messy real situation.",
      accent: "#d9a24d",
    },
    {
      key: "claim-question",
      tag: "Live test",
      title: "Metric drop under follow-up",
      body: "The room asks the next question from what the candidate just said, then watches how they recover.",
      accent: "#42d4e8",
    },
    {
      key: "claim-decision",
      tag: "Output",
      title: "Scoped yes + follow-ups",
      body: "Hiring gets a bounded recommendation, what was tested, and the exact risks a human should clarify.",
      accent: "#7fe2ae",
    },
  ];

  return (
    <div className="claim-stack">
      <div className="claim-link" />
      {cards.map((card) => (
        <article
          key={card.key}
          className={`claim-card ${activeKey === card.key ? "active" : ""} ${activeKey && activeKey !== card.key ? "defocus" : ""}`}
          data-target={card.key}
          style={{ "--accent": card.accent } as CSSProperties}
        >
          <div className="claim-orb">{card.tag}</div>
          <div>
            <p className="kicker">{card.key === "claim-question" && activeKey === card.key ? "Interviewer pressure" : card.tag}</p>
            <h3>
              {card.key === "claim-question" ? (
                <TypeLine active={activeKey === card.key} text={card.title} />
              ) : (
                card.title
              )}
            </h3>
            <p>{card.body}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function BriefStage({ activeKey, visitedKeys }: { activeKey: string; visitedKeys: string[] }) {
  return (
    <div className="brief-paper">
      <div className="paper-head">
        <h3>Interview brief</h3>
        <span className="paper-chip">Role-grounded</span>
      </div>
      <div className="brief-rows">
        {BRIEF_ROWS.map(([key, label, value]) => (
          <div
            key={key}
            className={`brief-row ${activeKey === key ? "active" : ""} ${visitedKeys.includes(key) ? "visited" : ""}`}
            data-target={key}
          >
            <span className="brief-label">{label}</span>
            <span className="brief-value">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AssemblyStage({
  activeKey,
  visitedKeys,
  completeCount,
}: {
  activeKey: string;
  visitedKeys: string[];
  completeCount: number;
}) {
  return (
    <div className="terminal">
      <div className="terminal-top">
        <span>Antigravity interview map</span>
        <div className="build-progress" aria-label={`${completeCount} of ${BUILD_STEPS.length} build steps complete`} />
      </div>
      <div className="terminal-body">
        <div className="build-lines">
          {BUILD_STEPS.map(([title, subtitle], index) => {
            const key = `build-${index}`;
            const active = activeKey === key;
            const visited = visitedKeys.includes(key);
            return (
              <div key={key} className={`build-line ${visited ? "visited" : ""}`} data-target={key}>
                <span className="dot" />
                <div>
                  <p className="build-main">
                    {active ? <TypeLine active text={title} /> : title}
                  </p>
                  <p className="build-sub">{subtitle}</p>
                </div>
              </div>
            );
          })}
        </div>
        <div className="aura-stage">
          <AgentAudioVisualizerAura
            size="lg"
            state={auraState("assembly", activeKey)}
            color={completeCount >= BUILD_STEPS.length ? "#7fe2ae" : "#d9a24d"}
            colorShift={0.08}
          />
        </div>
      </div>
    </div>
  );
}

function FloorStage({ activeKey, visitedKeys }: { activeKey: string; visitedKeys: string[] }) {
  const candidateActive = activeKey === "floor-candidate";

  return (
    <div className={`floor-map ${candidateActive ? "candidate-active" : ""}`}>
      <div
        className={`floor-zone ${activeKey === "floor-ai" ? "active" : ""} ${visitedKeys.includes("floor-ai") ? "visited" : ""}`}
        data-target="floor-ai"
      >
        <div className="zone-head">
          <p className="zone-title">AI corner</p>
          <span className="check">OK</span>
        </div>
        <div className="aura-stage" style={{ minHeight: 230 }}>
          <AgentAudioVisualizerAura size="md" state={auraState("floor", activeKey)} color="#d9a24d" colorShift={0.07} />
        </div>
        <h3>Interviewer presence locked</h3>
        <p>The AI asks, listens, reviews, and yields the floor without becoming a fake human face.</p>
      </div>

      <div
        className={`floor-zone turn-rail ${activeKey === "floor-rail" ? "active" : ""} ${visitedKeys.includes("floor-rail") ? "visited" : ""}`}
        data-target="floor-rail"
      >
        <div className="zone-head">
          <p className="zone-title">Turn rail</p>
          <span className="check">OK</span>
        </div>
        <h3>{candidateActive ? "Candidate turn" : "AI turn"}</h3>
        <div className="rail-line" />
        <p>The beam makes floor ownership visible, so the conversation feels structured instead of awkward.</p>
      </div>

      <div
        className={`floor-zone ${activeKey === "floor-candidate" ? "active" : ""} ${visitedKeys.includes("floor-candidate") ? "visited" : ""}`}
        data-target="floor-candidate"
      >
        <div className="zone-head">
          <p className="zone-title">Candidate corner</p>
          <span className="check">OK</span>
        </div>
        <div className="camera">
          <div className="avatar">SV</div>
        </div>
        <h3>Candidate telemetry locked</h3>
        <p>Camera, transcription, and history are present without crowding the active question.</p>
      </div>
    </div>
  );
}

function RoomStage({ activeKey }: { activeKey: string }) {
  return (
    <div className="room-preview">
      <aside className="room-panel">
        <p className="kicker">AI interviewer</p>
        <h3>Presence</h3>
        <div className="mini-aura">
          <AgentAudioVisualizerAura size="md" state={auraState("room", activeKey)} color="#42d4e8" colorShift={0.08} />
        </div>
      </aside>

      <section className="question-column">
        <div className="turn-pill">Candidate turn</div>
        <article className={`room-question ${activeKey === "room-question" ? "active" : ""}`} data-target="room-question">
          <p className="kicker">Interviewer&apos;s question</p>
          <h3>Walk me through one product decision where the data was not clean.</h3>
        </article>
        <article className={`transcript-box ${activeKey === "room-transcript" ? "active" : ""}`} data-target="room-transcript">
          <p className="kicker">Candidate answer live transcription</p>
          <p>
            Current answer appears here while committed history stays separate. The candidate can focus on answering,
            not chasing the interface.
          </p>
        </article>
        <div className="controls">
          <button className={`control ${activeKey === "room-repeat" ? "active" : ""}`} data-target="room-repeat">
            Repeat question
          </button>
          <button className="control">Need a moment</button>
          <button className="control">Fix last term</button>
          <button className="control">End interview</button>
        </div>
      </section>

      <aside className={`history-panel ${activeKey === "room-history" ? "active" : ""}`} data-target="room-history">
        <p className="kicker">Candidate corner</p>
        <h3>Camera and history</h3>
        <div className="camera">
          <div className="avatar">SV</div>
        </div>
        <div className="history-item">Q1 asked. Candidate clarified metric grain before answering.</div>
        <div className="history-item">Q2 follow-up ready. Full transcript available on demand.</div>
        <button className={`collapse-btn ${activeKey === "room-collapse" ? "active" : ""}`} data-target="room-collapse">
          Collapse side panel
        </button>
      </aside>
    </div>
  );
}

function ReportStage({ activeKey, visitedKeys }: { activeKey: string; visitedKeys: string[] }) {
  return (
    <div className="report-board">
      <article className={`verdict ${activeKey === "report-verdict" ? "active" : ""}`} data-target="report-verdict">
        <p className="kicker">Decision package</p>
        <h3>Scoped yes, with two follow-ups.</h3>
        <p>
          The report tells the hiring team what was actually tested, what held up, and where a human interviewer
          should go next.
        </p>
      </article>
      <div className="report-cards">
        {REPORT_CARDS.map(([key, title, value, body]) => (
          <article
            key={key}
            className={`report-card ${activeKey === key ? "active" : ""} ${visitedKeys.includes(key) ? "visited" : ""}`}
            data-target={key}
          >
            <h3>{title}</h3>
            <strong>{value}</strong>
            <p>{body}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function SimulationStage({ activeKey }: { activeKey: string }) {
  return (
    <div className="sim-workbench">
      <section className="code-pane">
        <p className="pane-title">Incident workbench</p>
        <div className="code-lines" data-target="sim-code">
          {SIM_LINES.map((line, index) => (
            <code key={line} className={`code-line ${activeKey === "sim-code" && index === 2 ? "active" : ""}`}>
              {line}
            </code>
          ))}
        </div>
      </section>
      <section className="test-pane">
        <p className="pane-title">Hidden test signal</p>
        <div className={`failure ${activeKey === "sim-failure" ? "active" : ""}`} data-target="sim-failure">
          test_dashboard_grain FAILED
          <br />
          Expected decision grain to match metric grain before recommendation.
        </div>
      </section>
      <section className="diff-pane">
        <p className="pane-title">Candidate recovery diff</p>
        <div className="diff-grid" data-target="sim-diff">
          <div className="diff-card">Before: candidate treats the metric drop as real without validating instrumentation.</div>
          <div className={`diff-card ${activeKey === "sim-diff" ? "active" : ""}`}>
            After: candidate checks event version, cohort, grain, and release window before advising action.
          </div>
        </div>
      </section>
    </div>
  );
}

function SynthesisStage({ activeKey }: { activeKey: string }) {
  return (
    <div className="synthesis-board">
      <section
        className={`surface candidate ${activeKey === "surface-candidate" ? "active" : "dim"}`}
        data-target="surface-candidate"
      >
        <p className="kicker">Candidate surface</p>
        <h3>Calm under pressure.</h3>
        <p>The candidate sees a professional room: clear question, visible turn, live transcription, and humane controls.</p>
        <div className="mini-room">
          <div className="mini-aura">
            <AgentAudioVisualizerAura size="sm" state={auraState("room", activeKey)} color="#42d4e8" colorShift={0.08} />
          </div>
          <div className="mini-question">
            <span className="kicker">Current question</span>
            <strong>How did you know the metric moved?</strong>
          </div>
        </div>
      </section>

      <section className={`surface report ${activeKey === "surface-report" ? "active" : "dim"}`} data-target="surface-report">
        <p className="kicker">Hiring team surface</p>
        <h3>Evidence that travels.</h3>
        <p>The buyer receives a decision package, not a raw transcript or a generic AI score.</p>
        <div className="surface-report-card">
          <p className="kicker">Updated evidence card</p>
          <h3 style={{ fontSize: 34 }}>Judgment under follow-up</h3>
          <p>Candidate separated instrument noise from business movement and named the next human follow-up.</p>
        </div>
      </section>
    </div>
  );
}
