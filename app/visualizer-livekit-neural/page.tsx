"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";
import { createLocalAudioTrack, type LocalAudioTrack } from "livekit-client";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

type Phase = "idle" | "listening" | "thinking" | "speaking" | "closing";
type PaletteKey = "gemini" | "cyan" | "violet" | "rose" | "green" | "amber";

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
};

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext;
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

const PHASES: Array<{
  key: Phase;
  aura: AgentState;
  label: string;
  route: string;
  signal: string;
  copy: string;
  candidate: string;
}> = [
  {
    key: "idle",
    aura: "idle",
    label: "Idle",
    route: "Awaiting floor",
    signal: "Ready",
    copy: "The interview field is quiet. The Aura is alive, but barely moving.",
    candidate: "Say a command like listening, thinking, speaking, cyan, rose, or finale.",
  },
  {
    key: "listening",
    aura: "listening",
    label: "Listening",
    route: "Candidate floor",
    signal: "Live capture",
    copy: "Make the leader-election answer concrete: where is the stale writer rejected?",
    candidate:
      "I would enforce fencing at the storage write boundary, because clients and middle-tier services can be stale during recovery.",
  },
  {
    key: "thinking",
    aura: "thinking",
    label: "Thinking",
    route: "Evidence synthesis",
    signal: "Gap isolated",
    copy: "The candidate named the right boundary. The next probe should test the failure semantics.",
    candidate: "Captured: storage-level fencing. Missing: what happens during delayed replication.",
  },
  {
    key: "speaking",
    aura: "speaking",
    label: "Speaking",
    route: "Agent floor",
    signal: "Probe outbound",
    copy: "Good. Now defend that choice when the old leader has lower latency to one replica than the new leader.",
    candidate: "The agent owns the floor. The Aura should expand outward with audio energy.",
  },
  {
    key: "closing",
    aura: "thinking",
    label: "Closing",
    route: "Final synthesis",
    signal: "Evidence sealed",
    copy: "That gives me enough signal. I am closing the loop and turning the conversation into an evidence report.",
    candidate: "Motion slows, evidence locks, and the final UI handoff is ready.",
  },
];

const PALETTES: Record<
  PaletteKey,
  {
    label: string;
    color: `#${string}`;
    a: string;
    b: string;
    c: string;
  }
> = {
  gemini: {
    label: "Gemini",
    color: "#1FD5F9",
    a: "oklch(0.72 0.2 222)",
    b: "oklch(0.72 0.24 304)",
    c: "oklch(0.8 0.16 154)",
  },
  cyan: {
    label: "Cyan",
    color: "#1FD5F9",
    a: "oklch(0.76 0.18 220)",
    b: "oklch(0.7 0.16 190)",
    c: "oklch(0.92 0.08 230)",
  },
  violet: {
    label: "Violet",
    color: "#7A5CFF",
    a: "oklch(0.67 0.25 285)",
    b: "oklch(0.75 0.2 230)",
    c: "oklch(0.78 0.18 318)",
  },
  rose: {
    label: "Rose",
    color: "#FF4FD8",
    a: "oklch(0.72 0.25 332)",
    b: "oklch(0.75 0.2 292)",
    c: "oklch(0.78 0.15 28)",
  },
  green: {
    label: "Green",
    color: "#6CFF9E",
    a: "oklch(0.78 0.18 150)",
    b: "oklch(0.76 0.15 188)",
    c: "oklch(0.86 0.13 112)",
  },
  amber: {
    label: "Amber",
    color: "#FFBE59",
    a: "oklch(0.82 0.16 74)",
    b: "oklch(0.74 0.18 28)",
    c: "oklch(0.9 0.12 102)",
  },
};

const SCRIPT: Array<{ phase: Phase; delay: number; text: string }> = [
  { phase: "speaking", delay: 2200, text: "Walk me through where ordering actually lives." },
  { phase: "listening", delay: 2600, text: "Candidate signal comes in. Voice energy pulls the field brighter." },
  { phase: "thinking", delay: 2200, text: "The answer is compressed into a sharper failure probe." },
  { phase: "speaking", delay: 2600, text: "What breaks first if one partition becomes hot while the rest stay flat?" },
  { phase: "closing", delay: 2200, text: "Evidence sealed. The interface prepares the report handoff." },
];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function LiveKitNeuralInterviewPage() {
  const [phase, setPhase] = useState<Phase>("listening");
  const [paletteKey, setPaletteKey] = useState<PaletteKey>("gemini");
  const [audioTrack, setAudioTrack] = useState<LocalAudioTrack | undefined>();
  const [micStatus, setMicStatus] = useState("Mic off");
  const [voiceEnergy, setVoiceEnergy] = useState(0.18);
  const [colorShift, setColorShift] = useState(0.22);
  const [transcript, setTranscript] = useState([
    "Antigravity AI: Make the leader-election answer concrete: where is the stale writer rejected?",
    "Candidate: I would enforce fencing at the storage write boundary.",
  ]);
  const [commandLog, setCommandLog] = useState("Say: listening, thinking, speaking, cyan, violet, rose, green, amber, gemini, finale.");
  const [isRecognizing, setIsRecognizing] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [ripples, setRipples] = useState<Array<{ id: number; phase: Phase; x: number; y: number }>>([]);

  const audioContextRef = useRef<AudioContext | null>(null);
  const audioTrackRef = useRef<LocalAudioTrack | undefined>(undefined);
  const animationRef = useRef<number | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const scriptTimerRef = useRef<number | null>(null);
  const scriptIndexRef = useRef(0);
  const rippleIdRef = useRef(0);
  const phaseRef = useRef<Phase>("listening");

  const active = useMemo(() => PHASES.find((item) => item.key === phase) ?? PHASES[1], [phase]);
  const palette = PALETTES[paletteKey];
  const auraState = audioTrack ? "speaking" : active.aura;

  useEffect(() => {
    return () => {
      stopMic();
      stopRecognition();
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
    const x = origin?.x ?? 50 + (id % 5 - 2) * 9;
    const y = origin?.y ?? 48 + (id % 3 - 1) * 11;
    setRipples((items) => [...items.slice(-5), { id, phase: nextPhase, x, y }]);
    window.setTimeout(() => {
      setRipples((items) => items.filter((item) => item.id !== id));
    }, 1250);
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
    setVoiceEnergy(0.18);
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
      transitionPhase("speaking", { x: 27, y: 38 });
      setMicStatus("Mic driving Aura and neural colors");

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        setMicStatus("Audio analysis unavailable");
        return;
      }
      const audioContext = new AudioContextClass();
      audioContextRef.current = audioContext;
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.72;
      const source = audioContext.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        analyser.getByteFrequencyData(data);
        let total = 0;
        let high = 0;
        for (let index = 0; index < data.length; index += 1) {
          const value = data[index] / 255;
          total += value;
          if (index > data.length * 0.38) high += value;
        }
        const energy = clamp((total / data.length) * 3.8, 0.08, 1);
        const brightness = clamp(high / data.length * 7.5, 0, 1);
        setVoiceEnergy(energy);
        setColorShift(clamp(0.12 + energy * 0.42 + brightness * 0.18, 0.08, 0.82));
        animationRef.current = window.requestAnimationFrame(tick);
      };
      tick();
    } catch (error) {
      console.error(error);
      setMicStatus("Mic blocked");
    }
  }

  function applyCommand(rawCommand: string) {
    const command = rawCommand.toLowerCase();
    const phaseMatch = PHASES.find((item) => command.includes(item.key));
    const paletteMatch = (Object.keys(PALETTES) as PaletteKey[]).find((key) => command.includes(key));

    if (phaseMatch) transitionPhase(phaseMatch.key);
    if (paletteMatch) setPaletteKey(paletteMatch);
    if (command.includes("finale") || command.includes("final")) transitionPhase("closing", { x: 50, y: 54 });
    if (command.includes("stop mic")) stopMic();
    if (command.includes("start mic")) void toggleMic();

    const applied = [
      phaseMatch ? phaseMatch.label : null,
      paletteMatch ? PALETTES[paletteMatch].label : null,
      command.includes("finale") ? "Finale" : null,
    ].filter(Boolean);
    setCommandLog(applied.length ? `Voice command applied: ${applied.join(" + ")}` : `Heard: ${rawCommand}`);
    setTranscript((items) => [...items.slice(-6), `Voice command: ${rawCommand}`]);
  }

  function toggleRecognition() {
    if (isRecognizing) {
      stopRecognition();
      return;
    }

    const Recognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setCommandLog("Speech recognition is not available in this browser. Use the buttons instead.");
      return;
    }

    const recognition = new Recognition() as SpeechRecognitionLike;
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      const latest = event.results[event.results.length - 1]?.[0]?.transcript?.trim();
      if (latest) applyCommand(latest);
    };
    recognition.onerror = () => setCommandLog("Voice command recognition hit a browser error.");
    recognition.onend = () => setIsRecognizing(false);
    recognition.start();
    recognitionRef.current = recognition;
    setIsRecognizing(true);
    setCommandLog("Listening for voice commands...");
  }

  function stopRecognition() {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setIsRecognizing(false);
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
      setTranscript((items) => [...items.slice(-6), `${PHASES.find((item) => item.key === step.phase)?.label}: ${step.text}`]);
      scriptIndexRef.current += 1;
      scriptTimerRef.current = window.setTimeout(runNext, step.delay);
    };
    runNext();
  }

  return (
    <main
      className="lk-neural-page min-h-screen overflow-hidden text-white"
      data-phase={phase}
      style={
        {
          "--voice-energy": voiceEnergy.toFixed(3),
          "--mix-a": `${16 + voiceEnergy * 22}%`,
          "--mix-b": `${10 + voiceEnergy * 18}%`,
          "--mix-c": `${8 + voiceEnergy * 18}%`,
          "--field-opacity": `${0.34 + voiceEnergy * 0.34}`,
          "--field-blur": `${8 + voiceEnergy * 18}px`,
          "--field-scale": `${1 + voiceEnergy * 0.035}`,
          "--scatter-size": `${22 - voiceEnergy * 8}px`,
          "--scatter-opacity": `${0.08 + voiceEnergy * 0.28}`,
          "--border-glow": `${24 + voiceEnergy * 72}px`,
          "--phase-a": palette.a,
          "--phase-b": palette.b,
          "--phase-c": palette.c,
        } as CSSProperties & Record<string, string>
      }
    >
      <style>{`
        .lk-neural-page {
          background:
            radial-gradient(circle at 48% -8%, color-mix(in oklch, var(--phase-a) var(--mix-a), transparent), transparent 36%),
            radial-gradient(circle at 16% 22%, color-mix(in oklch, var(--phase-c) var(--mix-c), transparent), transparent 28%),
            radial-gradient(circle at 88% 10%, color-mix(in oklch, var(--phase-b) var(--mix-b), transparent), transparent 30%),
            linear-gradient(180deg, oklch(0.09 0.014 265), oklch(0.045 0.012 265));
        }
        .lk-neural-page::before {
          content: "";
          position: fixed;
          inset: -12%;
          pointer-events: none;
          background:
            radial-gradient(circle at 50% 42%, color-mix(in oklch, var(--phase-a) var(--mix-b), transparent), transparent 42%),
            repeating-linear-gradient(90deg, transparent 0 38px, oklch(1 0 0 / 0.025) 39px 40px);
          opacity: var(--field-opacity);
          filter: blur(var(--field-blur));
          transform: scale(var(--field-scale));
        }
        .lk-energy-border {
          box-shadow:
            0 0 var(--border-glow) color-mix(in oklch, var(--phase-a) var(--mix-a), transparent),
            inset 0 0 0 1px oklch(1 0 0 / 0.08);
        }
        .lk-scatter {
          background-image: radial-gradient(circle, oklch(1 0 0 / 0.28) 0 1px, transparent 1.5px);
          background-size: var(--scatter-size) var(--scatter-size);
          opacity: var(--scatter-opacity);
          mask-image: radial-gradient(circle at center, black 0 54%, transparent 78%);
        }
        .lk-ripple {
          position: fixed;
          left: calc(var(--ripple-x) * 1%);
          top: calc(var(--ripple-y) * 1%);
          width: 34vmax;
          aspect-ratio: 1;
          pointer-events: none;
          border-radius: 999px;
          transform: translate(-50%, -50%) scale(0.04);
          opacity: 0;
          mix-blend-mode: screen;
          filter: blur(8px) saturate(1.35);
          background:
            radial-gradient(circle, oklch(1 0 0 / 0.48) 0 2%, transparent 7%),
            radial-gradient(circle, transparent 0 24%, color-mix(in oklch, var(--ripple-a) 34%, transparent) 28%, transparent 44%),
            conic-gradient(from 120deg, color-mix(in oklch, var(--ripple-a) 62%, transparent), color-mix(in oklch, var(--ripple-b) 48%, transparent), color-mix(in oklch, var(--ripple-c) 42%, transparent), transparent, color-mix(in oklch, var(--ripple-a) 55%, transparent));
          animation: lk-hue-ripple 1250ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
          z-index: 1;
        }
        .lk-ripple::after {
          content: "";
          position: absolute;
          inset: 18%;
          border-radius: inherit;
          border: 1px solid color-mix(in oklch, var(--ripple-c) 48%, transparent);
          box-shadow:
            0 0 44px color-mix(in oklch, var(--ripple-a) 24%, transparent),
            inset 0 0 28px color-mix(in oklch, var(--ripple-b) 18%, transparent);
        }
        @keyframes lk-hue-ripple {
          0% {
            opacity: 0;
            transform: translate(-50%, -50%) scale(0.04) rotate(0deg);
          }
          12% {
            opacity: calc(0.48 + var(--voice-energy) * 0.34);
          }
          72% {
            opacity: calc(0.18 + var(--voice-energy) * 0.18);
          }
          100% {
            opacity: 0;
            transform: translate(-50%, -50%) scale(2.9) rotate(18deg);
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .lk-ripple {
            animation-duration: 1ms;
          }
        }
      `}</style>

      <div className="pointer-events-none fixed inset-0 lk-scatter" />
      <div className="pointer-events-none fixed inset-0 z-[1] overflow-hidden" aria-hidden="true">
        {ripples.map((ripple) => {
          const ripplePalette =
            ripple.phase === "thinking"
              ? PALETTES.amber
              : ripple.phase === "speaking"
                ? PALETTES.violet
                : ripple.phase === "closing"
                  ? PALETTES.rose
                  : ripple.phase === "idle"
                    ? PALETTES.cyan
                    : palette;
          return (
            <span
              key={ripple.id}
              className="lk-ripple"
              style={
                {
                  "--ripple-x": ripple.x,
                  "--ripple-y": ripple.y,
                  "--ripple-a": ripplePalette.a,
                  "--ripple-b": ripplePalette.b,
                  "--ripple-c": ripplePalette.c,
                } as CSSProperties & Record<string, string | number>
              }
            />
          );
        })}
      </div>

      <section className="relative z-[2] mx-auto grid min-h-screen w-full max-w-[1480px] grid-cols-[360px_minmax(0,1fr)_340px] gap-5 px-5 py-5 max-xl:grid-cols-[340px_minmax(0,1fr)] max-lg:grid-cols-1">
        <aside className="lk-energy-border flex min-h-0 flex-col gap-4 rounded-[28px] border border-white/10 bg-black/34 p-5 backdrop-blur-2xl">
          <div>
            <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-200/58">
              Live Interrogator
            </p>
            <h1 className="text-3xl font-semibold leading-tight">Neural Aura Preview</h1>
            <p className="mt-4 text-sm leading-7 text-white/58">
              Same interview canvas, official LiveKit Aura instead of the orb. Mic energy drives the Aura and the surrounding Gemini-style color field.
            </p>
          </div>

          <div className="rounded-3xl border border-white/10 bg-black/35 p-4">
            <div className="grid place-items-center overflow-hidden rounded-[24px] bg-black/40 py-4">
              <div className="relative grid h-[286px] w-full place-items-center">
                <div className="absolute h-[22rem] w-[22rem] rounded-full bg-[radial-gradient(circle,color-mix(in_oklch,var(--phase-a)_24%,transparent),transparent_66%)] blur-2xl" />
                <AgentAudioVisualizerAura
                  size="lg"
                  state={auraState}
                  audioTrack={audioTrack}
                  color={palette.color}
                  colorShift={colorShift}
                  themeMode="dark"
                  className="relative z-10"
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={toggleMic}
                className="rounded-2xl border border-cyan-200/30 bg-cyan-200/12 px-3 py-3 text-xs font-bold uppercase tracking-[0.14em] text-cyan-50"
              >
                {audioTrack ? "Stop mic" : "Use mic"}
              </button>
              <button
                type="button"
                onClick={toggleRecognition}
                className="rounded-2xl border border-white/12 bg-white/[0.055] px-3 py-3 text-xs font-bold uppercase tracking-[0.14em] text-white/76"
              >
                {isRecognizing ? "Stop voice" : "Voice cmd"}
              </button>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/[0.035] p-4">
            <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.2em] text-white/42">
              <span>Mic</span>
              <span className="text-cyan-100">{micStatus}</span>
            </div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-gradient-to-r from-cyan-300 via-violet-400 to-fuchsia-300"
                style={{ width: `${Math.round(voiceEnergy * 100)}%` }}
              />
            </div>
            <p className="mt-4 text-xs leading-6 text-white/50">{commandLog}</p>
          </div>

          <div className="grid grid-cols-3 gap-2 xl:hidden">
            {(Object.keys(PALETTES) as PaletteKey[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setPaletteKey(key)}
                className={[
                  "rounded-2xl border px-2 py-3 text-[10px] font-bold uppercase tracking-[0.12em] transition",
                  paletteKey === key
                    ? "border-white/55 bg-white/12 text-white"
                    : "border-white/10 bg-white/[0.035] text-white/50 hover:text-white/84",
                ].join(" ")}
              >
                {PALETTES[key].label}
              </button>
            ))}
          </div>
        </aside>

        <section className="lk-energy-border relative min-h-0 overflow-hidden rounded-[32px] border border-white/10 bg-black/28 backdrop-blur-2xl">
          <div className="grid h-full min-h-[calc(100vh-40px)] grid-rows-[auto_1fr_auto]">
            <header className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-5 max-md:flex-col max-md:items-stretch">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-200/58">
                  Conversation Field
                </p>
                <p className="mt-2 text-sm text-white/54">The active probe stays central; the Aura is the agent presence.</p>
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
                      "rounded-full border px-3 py-2 text-[10px] font-bold uppercase tracking-[0.16em] transition",
                      phase === item.key
                        ? "border-cyan-200/50 bg-cyan-200/14 text-cyan-50"
                        : "border-white/10 bg-white/[0.035] text-white/48 hover:text-white/82",
                    ].join(" ")}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </header>

            <div className="grid place-items-center px-8 py-8">
              <article className="relative w-full max-w-4xl overflow-hidden rounded-[32px] border border-white/10 bg-black/38 p-8 shadow-2xl">
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,color-mix(in_oklch,var(--phase-a)_16%,transparent),transparent_46%)]" />
                <div className="relative">
                  <div className="flex items-center justify-between gap-4 text-[10px] font-bold uppercase tracking-[0.24em] text-white/42">
                    <span>{active.route}</span>
                    <span>{active.signal}</span>
                  </div>
                  <h2 className="mt-8 text-5xl font-semibold leading-[1.05] tracking-normal max-md:text-3xl">
                    {active.copy}
                  </h2>
                  <div className="mt-8 rounded-3xl border border-white/10 bg-white/[0.045] p-5">
                    <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-cyan-200/54">
                      Live candidate signal
                    </p>
                    <p className="mt-3 text-lg leading-8 text-white/72">{active.candidate}</p>
                  </div>
                </div>
              </article>
            </div>

            <footer className="flex items-center justify-between gap-4 border-t border-white/10 px-6 py-5 max-md:flex-col max-md:items-stretch">
              <div className="grid grid-cols-3 gap-3 text-center max-md:grid-cols-1">
                {["Claim", "Gap", "Next probe"].map((label, index) => (
                  <div key={label} className="rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3">
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-white/36">{label}</p>
                    <p className="mt-2 text-sm text-white/68">
                      {index === 0 ? "Fencing boundary" : index === 1 ? "Replication delay" : "Failure semantics"}
                    </p>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={runConversation}
                className="rounded-2xl border border-cyan-200/30 bg-cyan-200/12 px-5 py-3 text-xs font-bold uppercase tracking-[0.16em] text-cyan-50"
              >
                {isRunning ? "Stop simulation" : "Run conversation"}
              </button>
            </footer>
          </div>
        </section>

        <aside className="lk-energy-border flex min-h-0 flex-col gap-4 rounded-[28px] border border-white/10 bg-black/34 p-5 backdrop-blur-2xl max-xl:hidden">
          <div>
            <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-200/58">
              Neural Color Control
            </p>
            <p className="text-sm leading-7 text-white/58">
              Use buttons or voice commands. Mic energy continuously adjusts glow strength and Aura color shift.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {(Object.keys(PALETTES) as PaletteKey[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setPaletteKey(key)}
                className={[
                  "rounded-2xl border px-3 py-3 text-xs font-bold uppercase tracking-[0.14em] transition",
                  paletteKey === key
                    ? "border-white/55 bg-white/12 text-white"
                    : "border-white/10 bg-white/[0.035] text-white/50 hover:text-white/84",
                ].join(" ")}
              >
                {PALETTES[key].label}
              </button>
            ))}
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/[0.035] p-4">
            <div className="flex justify-between text-[10px] font-bold uppercase tracking-[0.2em] text-white/42">
              <span>Color shift</span>
              <span className="text-cyan-100">{colorShift.toFixed(2)}</span>
            </div>
            <input
              value={colorShift}
              min="0"
              max="1"
              step="0.01"
              onChange={(event) => setColorShift(Number(event.target.value))}
              className="mt-4 w-full accent-cyan-300"
              type="range"
            />
          </div>

          <div className="min-h-0 flex-1 overflow-hidden rounded-3xl border border-white/10 bg-white/[0.035]">
            <div className="border-b border-white/10 px-4 py-3 text-[10px] font-bold uppercase tracking-[0.22em] text-white/42">
              Transcript
            </div>
            <div className="max-h-[48vh] space-y-3 overflow-auto p-4">
              {transcript.map((item, index) => (
                <p key={`${item}-${index}`} className="rounded-2xl border border-white/8 bg-black/24 p-3 text-sm leading-6 text-white/62">
                  {item}
                </p>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}
