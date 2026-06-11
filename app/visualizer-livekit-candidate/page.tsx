"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";
import { createLocalAudioTrack, type LocalAudioTrack } from "livekit-client";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type Phase = "idle" | "listening" | "thinking" | "speaking" | "closing";

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext;
  }
}

const CANDIDATE = {
  name: "S. V. S. Apparao",
  experience: "3 years experience",
  role: "Product Analyst",
};

const PHASES: Array<{
  key: Phase;
  aura: AgentState;
  label: string;
  title: string;
  question: string;
  response: string;
}> = [
  {
    key: "idle",
    aura: "idle",
    label: "Idle",
    title: "Interview ready",
    question: "Your interview is ready to begin.",
    response: "Take a breath. When the first question appears, answer naturally.",
  },
  {
    key: "listening",
    aura: "listening",
    label: "Listening",
    title: "Your turn",
    question: "Make the leader-election answer concrete: where is the stale writer rejected?",
    response:
      "I would enforce fencing at the storage write boundary, because clients and middle-tier services can be stale during recovery.",
  },
  {
    key: "thinking",
    aura: "thinking",
    label: "Reviewing",
    title: "Answer received",
    question: "Thanks. Give me a moment while I review that answer.",
    response: "Storage-level fencing was clear. The next question should test what happens under delayed replication.",
  },
  {
    key: "speaking",
    aura: "speaking",
    label: "Question",
    title: "Follow-up question",
    question:
      "Good. Now defend that choice when the old leader has lower latency to one replica than the new leader.",
    response: "Listen fully, then answer with the failure mode you would protect against first.",
  },
  {
    key: "closing",
    aura: "thinking",
    label: "Closing",
    title: "Interview complete",
    question: "That gives me enough signal. I’m closing the interview and preparing your report.",
    response: "The session is complete. You’ll move to the results view once the report is ready.",
  },
];

const SCRIPT: Array<{ phase: Phase; delay: number; note: string }> = [
  { phase: "speaking", delay: 2200, note: "Question: Walk me through where ordering actually lives." },
  { phase: "listening", delay: 2600, note: "Candidate: Ordering is scoped per partition." },
  { phase: "thinking", delay: 1800, note: "Answer received." },
  { phase: "speaking", delay: 2600, note: "Question: What breaks first when a partition gets hot?" },
  { phase: "listening", delay: 2600, note: "Candidate: Throughput caps before correctness does." },
  { phase: "closing", delay: 2200, note: "Interview complete." },
];

const PHASE_MURALS: Record<Phase, {
  aura: `#${string}`;
  shift: number;
  a: string;
  b: string;
  c: string;
}> = {
  idle: {
    aura: "#7AA7FF",
    shift: 0.14,
    a: "oklch(0.66 0.14 248)",
    b: "oklch(0.62 0.1 282)",
    c: "oklch(0.72 0.08 220)",
  },
  listening: {
    aura: "#1FD5F9",
    shift: 0.28,
    a: "oklch(0.72 0.19 222)",
    b: "oklch(0.66 0.13 278)",
    c: "oklch(0.76 0.14 154)",
  },
  thinking: {
    aura: "#FFBE59",
    shift: 0.44,
    a: "oklch(0.78 0.14 72)",
    b: "oklch(0.68 0.14 34)",
    c: "oklch(0.72 0.12 292)",
  },
  speaking: {
    aura: "#FF4D6D",
    shift: 0.58,
    a: "oklch(0.66 0.22 18)",
    b: "oklch(0.7 0.18 342)",
    c: "oklch(0.68 0.13 286)",
  },
  closing: {
    aura: "#6CFF9E",
    shift: 0.24,
    a: "oklch(0.76 0.15 154)",
    b: "oklch(0.68 0.13 204)",
    c: "oklch(0.78 0.1 92)",
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function CandidateLiveKitPreviewPage() {
  const [phase, setPhase] = useState<Phase>("listening");
  const [audioTrack, setAudioTrack] = useState<LocalAudioTrack | undefined>();
  const [micStatus, setMicStatus] = useState("Mic off");
  const [voiceEnergy, setVoiceEnergy] = useState(0.12);
  const [isRunning, setIsRunning] = useState(false);
  const [notes, setNotes] = useState([
    "Question: Make the leader-election answer concrete.",
    "Candidate: I would enforce fencing at the storage write boundary.",
  ]);
  const [ripples, setRipples] = useState<Array<{ id: number; x: number; y: number }>>([]);

  const audioContextRef = useRef<AudioContext | null>(null);
  const audioTrackRef = useRef<LocalAudioTrack | undefined>(undefined);
  const animationRef = useRef<number | null>(null);
  const scriptTimerRef = useRef<number | null>(null);
  const scriptIndexRef = useRef(0);
  const rippleIdRef = useRef(0);
  const phaseRef = useRef<Phase>("listening");

  const active = useMemo(() => PHASES.find((item) => item.key === phase) ?? PHASES[1], [phase]);
  const auraState = audioTrack ? "speaking" : active.aura;
  const mural = PHASE_MURALS[phase];
  const colorShift = clamp(mural.shift + voiceEnergy * 0.16, 0.06, 0.68);

  useEffect(() => {
    return () => {
      stopMic();
      if (scriptTimerRef.current) window.clearTimeout(scriptTimerRef.current);
    };
  }, []);

  function transitionPhase(nextPhase: Phase, origin?: { x: number; y: number }) {
    const previousPhase = phaseRef.current;
    phaseRef.current = nextPhase;
    setPhase(nextPhase);

    if (previousPhase === nextPhase) return;
    const id = rippleIdRef.current + 1;
    rippleIdRef.current = id;
    setRipples((items) => [
      ...items.slice(-2),
      { id, x: origin?.x ?? 50, y: origin?.y ?? 48 },
    ]);
    window.setTimeout(() => {
      setRipples((items) => items.filter((item) => item.id !== id));
    }, 900);
  }

  function stopMic() {
    if (animationRef.current) window.cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
    audioTrackRef.current?.stop();
    audioTrackRef.current = undefined;
    setAudioTrack(undefined);
    audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
    setMicStatus("Mic off");
    setVoiceEnergy(0.12);
  }

  async function toggleMic() {
    if (audioTrack) {
      stopMic();
      return;
    }

    try {
      setMicStatus("Requesting mic...");
      const track = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      });
      audioTrackRef.current = track;
      setAudioTrack(track);
      setMicStatus("Mic test active");
      transitionPhase("speaking", { x: 32, y: 36 });

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      const audioContext = new AudioContextClass();
      audioContextRef.current = audioContext;
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.78;
      audioContext
        .createMediaStreamSource(new MediaStream([track.mediaStreamTrack]))
        .connect(analyser);

      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(data);
        let total = 0;
        for (let index = 0; index < data.length; index += 1) {
          total += data[index] / 255;
        }
        const energy = clamp((total / data.length) * 3.2, 0.08, 0.82);
        setVoiceEnergy(energy);
        animationRef.current = window.requestAnimationFrame(tick);
      };
      tick();
    } catch (error) {
      console.error(error);
      setMicStatus("Mic unavailable");
    }
  }

  function runConversation() {
    if (isRunning) {
      if (scriptTimerRef.current) window.clearTimeout(scriptTimerRef.current);
      scriptTimerRef.current = null;
      setIsRunning(false);
      return;
    }

    setIsRunning(true);
    scriptIndexRef.current = 0;
    const runNext = () => {
      const step = SCRIPT[scriptIndexRef.current];
      if (!step) {
        setIsRunning(false);
        return;
      }
      transitionPhase(step.phase);
      setNotes((items) => [...items.slice(-5), step.note]);
      scriptIndexRef.current += 1;
      scriptTimerRef.current = window.setTimeout(runNext, step.delay);
    };
    runNext();
  }

  return (
    <main
      className="candidate-preview min-h-screen overflow-hidden text-white"
      data-phase={phase}
      style={
        {
          "--energy": voiceEnergy.toFixed(3),
          "--aura-shift": colorShift.toFixed(3),
          "--glow": `${20 + voiceEnergy * 38}px`,
          "--field": `${0.22 + voiceEnergy * 0.22}`,
          "--ring": `${0.18 + voiceEnergy * 0.24}`,
          "--mural-a": mural.a,
          "--mural-b": mural.b,
          "--mural-c": mural.c,
        } as CSSProperties & Record<string, string>
      }
    >
      <style>{`
        .candidate-preview {
          transition: background 520ms ease;
          background:
            radial-gradient(circle at 48% -8%, color-mix(in oklch, var(--mural-a) calc(var(--field) * 100%), transparent), transparent 40%),
            radial-gradient(circle at 10% 24%, color-mix(in oklch, var(--mural-c) calc(var(--field) * 46%), transparent), transparent 30%),
            radial-gradient(circle at 92% 10%, color-mix(in oklch, var(--mural-b) calc(var(--field) * 42%), transparent), transparent 32%),
            linear-gradient(180deg, oklch(0.095 0.014 265), oklch(0.052 0.012 265));
        }
        .candidate-preview::before {
          content: "";
          position: fixed;
          inset: 0;
          pointer-events: none;
          opacity: 0.16;
          background-image:
            radial-gradient(circle, oklch(1 0 0 / 0.24) 0 1px, transparent 1.5px),
            linear-gradient(115deg, transparent 0 42%, color-mix(in oklch, var(--mural-a) 7%, transparent) 48%, transparent 58%);
          background-size: 28px 28px;
          mask-image: linear-gradient(180deg, black 0 70%, transparent 100%);
        }
        .candidate-preview::after {
          content: "";
          position: fixed;
          inset: -18%;
          pointer-events: none;
          opacity: calc(0.18 + var(--energy) * 0.18);
          mix-blend-mode: screen;
          filter: blur(12px);
          background:
            radial-gradient(38rem 18rem at 6% 96%, color-mix(in oklch, var(--mural-c) 24%, transparent), transparent 68%),
            radial-gradient(34rem 16rem at 94% 4%, color-mix(in oklch, var(--mural-a) 20%, transparent), transparent 70%),
            repeating-linear-gradient(
              38deg,
              transparent 0 42px,
              color-mix(in oklch, var(--mural-a) 11%, transparent) 52px 58px,
              transparent 70px 118px,
              color-mix(in oklch, var(--mural-c) 8%, transparent) 132px 138px,
              transparent 154px 220px
            );
          mask-image:
            radial-gradient(ellipse at 0% 100%, black 0 34%, transparent 58%),
            radial-gradient(ellipse at 100% 0%, black 0 30%, transparent 56%),
            linear-gradient(38deg, transparent 0 18%, black 32% 68%, transparent 84%);
          animation: ocean-caustics 12s ease-in-out infinite alternate;
        }
        .candidate-card {
          box-shadow:
            0 0 var(--glow) color-mix(in oklch, var(--mural-a) calc(var(--ring) * 100%), transparent),
            inset 0 0 0 1px oklch(1 0 0 / 0.07);
        }
        .candidate-ripple {
          position: fixed;
          left: calc(var(--x) * 1%);
          top: calc(var(--y) * 1%);
          width: 30vmax;
          aspect-ratio: 1;
          pointer-events: none;
          border-radius: 999px;
          transform: translate(-50%, -50%) scale(0.05);
          opacity: 0;
          mix-blend-mode: screen;
          filter: blur(6px);
          background:
            radial-gradient(circle, color-mix(in oklch, var(--mural-c) 28%, transparent), transparent 12%),
            radial-gradient(circle, transparent 22%, color-mix(in oklch, var(--mural-a) 22%, transparent) 28%, transparent 48%),
            conic-gradient(from 120deg, color-mix(in oklch, var(--mural-c) 22%, transparent), color-mix(in oklch, var(--mural-b) 20%, transparent), transparent, color-mix(in oklch, var(--mural-a) 28%, transparent));
          animation: candidate-ripple 900ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
          z-index: 1;
        }
        @keyframes candidate-ripple {
          0% { opacity: 0; transform: translate(-50%, -50%) scale(0.05); }
          16% { opacity: 0.55; }
          100% { opacity: 0; transform: translate(-50%, -50%) scale(2.35); }
        }
        @keyframes ocean-caustics {
          from {
            transform: translate3d(-1.5%, 1%, 0) rotate(-0.4deg) scale(1);
          }
          to {
            transform: translate3d(1.5%, -1%, 0) rotate(0.45deg) scale(1.025);
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .candidate-ripple,
          .candidate-preview::after {
            animation-duration: 1ms;
          }
        }
      `}</style>

      <div className="pointer-events-none fixed inset-0 z-[1] overflow-hidden" aria-hidden="true">
        {ripples.map((ripple) => (
          <span
            key={ripple.id}
            className="candidate-ripple"
            style={
              {
                "--x": ripple.x,
                "--y": ripple.y,
              } as CSSProperties & Record<string, number>
            }
          />
        ))}
      </div>

      <section className="relative z-[2] mx-auto flex min-h-screen w-full max-w-[1440px] flex-col gap-4 px-5 py-5">
        <header className="candidate-card rounded-[28px] border border-white/10 bg-black/30 px-5 py-4 backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-100/58">
                Antigravity Interview
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-normal">{CANDIDATE.name}</h1>
            </div>
            <div className="flex flex-wrap gap-2 text-sm text-white/72">
              <span className="rounded-full border border-white/10 bg-white/[0.055] px-4 py-2">
                {CANDIDATE.experience}
              </span>
              <span className="rounded-full border border-white/10 bg-white/[0.055] px-4 py-2">
                {CANDIDATE.role}
              </span>
              <span className="rounded-full border border-cyan-200/25 bg-cyan-200/10 px-4 py-2 text-cyan-50">
                {active.label}
              </span>
            </div>
          </div>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-[360px_minmax(0,1fr)] gap-4 max-lg:grid-cols-1">
          <aside className="candidate-card flex min-h-0 flex-col gap-4 rounded-[28px] border border-white/10 bg-black/30 p-5 backdrop-blur-xl">
            <div className="rounded-[24px] border border-white/10 bg-black/34 p-4">
              <div className="grid h-[300px] place-items-center overflow-hidden rounded-[20px] bg-black/28">
                <div className="relative grid h-full w-full place-items-center">
                  <div className="absolute h-[22rem] w-[22rem] rounded-full bg-[radial-gradient(circle,color-mix(in_oklch,var(--mural-a)_28%,transparent),transparent_68%)] blur-xl transition-colors duration-700" />
                  <AgentAudioVisualizerAura
                    size="lg"
                    state={auraState}
                    audioTrack={audioTrack}
                    color={mural.aura}
                    colorShift={colorShift}
                    themeMode="dark"
                    className="relative z-10"
                  />
                </div>
              </div>
              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  onClick={toggleMic}
                  className="flex-1 rounded-2xl border border-cyan-200/30 bg-cyan-200/12 px-4 py-3 text-xs font-bold uppercase tracking-[0.14em] text-cyan-50"
                >
                  {audioTrack ? "Stop mic" : "Test mic"}
                </button>
                <button
                  type="button"
                  onClick={() => transitionPhase("listening", { x: 28, y: 42 })}
                  className="flex-1 rounded-2xl border border-white/12 bg-white/[0.055] px-4 py-3 text-xs font-bold uppercase tracking-[0.14em] text-white/72"
                >
                  Reset
                </button>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/[0.04] p-4">
              <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.2em] text-white/42">
                <span>Microphone</span>
                <span className="text-cyan-100">{micStatus}</span>
              </div>
              <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-cyan-300 via-violet-300 to-fuchsia-300"
                  style={{ width: `${Math.round(voiceEnergy * 100)}%` }}
                />
              </div>
            </div>
          </aside>

          <main className="candidate-card grid min-h-0 grid-rows-[auto_1fr_auto] overflow-hidden rounded-[28px] border border-white/10 bg-black/30 backdrop-blur-xl">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.24em] text-cyan-100/54">
                  Current question
                </p>
                <p className="mt-2 text-sm text-white/54">{active.title}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {PHASES.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={(event) => {
                      const rect = event.currentTarget.getBoundingClientRect();
                      transitionPhase(item.key, {
                        x: ((rect.left + rect.width * 0.5) / window.innerWidth) * 100,
                        y: ((rect.top + rect.height * 0.5) / window.innerHeight) * 100,
                      });
                    }}
                    className={[
                      "rounded-full border px-3 py-2 text-[10px] font-bold uppercase tracking-[0.16em]",
                      phase === item.key
                        ? "border-cyan-200/50 bg-cyan-200/14 text-cyan-50"
                        : "border-white/10 bg-white/[0.035] text-white/46",
                    ].join(" ")}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <section className="grid min-h-0 gap-5 overflow-auto p-6">
              <article className="rounded-[28px] border border-white/10 bg-black/34 p-7">
                <p className="text-[10px] font-bold uppercase tracking-[0.24em] text-white/40">
                  Interviewer
                </p>
                <h2 className="mt-5 max-w-4xl text-5xl font-semibold leading-[1.05] tracking-normal max-md:text-3xl">
                  {active.question}
                </h2>
              </article>

              <article className="rounded-[28px] border border-white/10 bg-white/[0.04] p-6">
                <p className="text-[10px] font-bold uppercase tracking-[0.24em] text-white/40">
                  Your response
                </p>
                <p className="mt-4 max-w-3xl text-lg leading-8 text-white/72">{active.response}</p>
              </article>
            </section>

            <footer className="border-t border-white/10 p-5">
              <div className="grid grid-cols-[repeat(3,minmax(0,1fr))_220px] gap-3 max-md:grid-cols-1">
                <div className="rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3 text-center">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-white/36">Claim</p>
                  <p className="mt-2 text-sm text-white/68">Fencing boundary</p>
                </div>
                <div className="rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3 text-center">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-white/36">Gap</p>
                  <p className="mt-2 text-sm text-white/68">Replication delay</p>
                </div>
                <div className="rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3 text-center">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-white/36">Next probe</p>
                  <p className="mt-2 text-sm text-white/68">Failure semantics</p>
                </div>
                <button
                  type="button"
                  onClick={runConversation}
                  className="rounded-2xl border border-cyan-200/30 bg-cyan-200/12 px-5 py-3 text-xs font-bold uppercase tracking-[0.16em] text-cyan-50"
                >
                  {isRunning ? "Stop" : "Run conversation"}
                </button>
              </div>
            </footer>
          </main>
        </div>

        <section className="candidate-card rounded-[28px] border border-white/10 bg-black/30 p-5 backdrop-blur-xl">
          <div className="flex flex-wrap gap-3">
            {notes.map((note, index) => (
              <p key={`${note}-${index}`} className="rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3 text-sm text-white/58">
                {note}
              </p>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}
