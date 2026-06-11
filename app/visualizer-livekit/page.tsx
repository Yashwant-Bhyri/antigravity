"use client";

import { useEffect, useMemo, useState } from "react";
import type { AgentState } from "@livekit/components-react";
import { createLocalAudioTrack, type LocalAudioTrack } from "livekit-client";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

const PHASES: Array<{
  key: AgentState;
  label: string;
  route: string;
  prompt: string;
}> = [
  {
    key: "idle",
    label: "Idle",
    route: "Awaiting floor",
    prompt: "The interview field is quiet. The aura is present, but restrained.",
  },
  {
    key: "listening",
    label: "Listening",
    route: "Candidate floor",
    prompt: "Candidate signal is being captured. The agent presence should feel awake, not noisy.",
  },
  {
    key: "thinking",
    label: "Thinking",
    route: "Evidence synthesis",
    prompt: "The system is compressing the answer into a sharper next probe.",
  },
  {
    key: "speaking",
    label: "Speaking",
    route: "Agent floor",
    prompt: "The aura is now driven by the audio track. Use mic mode to test real voice response.",
  },
];

export default function LiveKitVisualizerPage() {
  const [state, setState] = useState<AgentState>("listening");
  const [audioTrack, setAudioTrack] = useState<LocalAudioTrack | undefined>();
  const [micStatus, setMicStatus] = useState("Mic off");
  const [colorShift, setColorShift] = useState(0.34);
  const [color, setColor] = useState<`#${string}`>("#1FD5F9");

  const active = useMemo(() => PHASES.find((phase) => phase.key === state) ?? PHASES[1], [state]);

  useEffect(() => {
    return () => {
      audioTrack?.stop();
    };
  }, [audioTrack]);

  async function toggleMic() {
    if (audioTrack) {
      audioTrack.stop();
      setAudioTrack(undefined);
      setMicStatus("Mic off");
      return;
    }

    try {
      setMicStatus("Requesting mic...");
      const track = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      });
      setAudioTrack(track);
      setState("speaking");
      setMicStatus("Mic driving Aura");
    } catch (error) {
      console.error(error);
      setMicStatus("Mic blocked");
    }
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[oklch(0.055_0.012_265)] text-white">
      <div className="pointer-events-none fixed inset-0 opacity-80">
        <div className="absolute left-1/2 top-[-12%] h-[36rem] w-[52rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,oklch(0.68_0.2_230_/_0.22),transparent_66%)] blur-3xl" />
        <div className="absolute bottom-[-18%] left-[8%] h-[32rem] w-[32rem] rounded-full bg-[radial-gradient(circle,oklch(0.78_0.18_160_/_0.13),transparent_68%)] blur-3xl" />
        <div className="absolute right-[-8%] top-[20%] h-[32rem] w-[32rem] rounded-full bg-[radial-gradient(circle,oklch(0.7_0.24_315_/_0.14),transparent_68%)] blur-3xl" />
      </div>

      <section className="relative mx-auto grid min-h-screen w-full max-w-7xl grid-cols-[360px_minmax(0,1fr)] gap-6 px-6 py-6 max-lg:grid-cols-1">
        <aside className="flex min-h-0 flex-col justify-between rounded-[28px] border border-white/10 bg-black/35 p-5 shadow-2xl backdrop-blur-2xl">
          <div>
            <div className="mb-6">
              <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-200/55">
                LiveKit Agents UI
              </p>
              <h1 className="text-3xl font-semibold leading-tight tracking-normal text-white">
                Real Aura component test
              </h1>
              <p className="mt-4 text-sm leading-7 text-white/58">
                This page uses the official LiveKit Agents UI Aura visualizer from the shadcn registry,
                not the static HTML canvas approximation.
              </p>
            </div>

            <div className="space-y-3">
              {PHASES.map((phase) => (
                <button
                  key={phase.key}
                  type="button"
                  onClick={() => setState(phase.key)}
                  className={[
                    "flex w-full items-center justify-between rounded-2xl border px-4 py-3 text-left transition",
                    state === phase.key
                      ? "border-cyan-300/45 bg-cyan-300/12 text-cyan-100 shadow-[0_0_28px_rgba(31,213,249,0.15)]"
                      : "border-white/8 bg-white/[0.035] text-white/55 hover:border-white/18 hover:text-white/80",
                  ].join(" ")}
                >
                  <span className="text-xs font-bold uppercase tracking-[0.2em]">{phase.label}</span>
                  <span className="h-2 w-2 rounded-full bg-current" />
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-4 pt-6">
            <button
              type="button"
              onClick={toggleMic}
              className="w-full rounded-2xl border border-cyan-200/30 bg-cyan-200/12 px-4 py-3 text-sm font-bold text-cyan-50 shadow-[0_0_32px_rgba(31,213,249,0.18)] transition hover:bg-cyan-200/18"
            >
              {audioTrack ? "Stop mic" : "Use mic for audio-reactive Aura"}
            </button>
            <div className="rounded-2xl border border-white/8 bg-white/[0.035] p-4">
              <div className="flex items-center justify-between gap-3 text-xs uppercase tracking-[0.18em] text-white/45">
                <span>Status</span>
                <span className="text-cyan-100">{micStatus}</span>
              </div>
              <div className="mt-4 space-y-3">
                <label className="block text-xs uppercase tracking-[0.18em] text-white/45">
                  Color shift
                </label>
                <input
                  value={colorShift}
                  onChange={(event) => setColorShift(Number(event.target.value))}
                  min="0"
                  max="1"
                  step="0.01"
                  type="range"
                  className="w-full accent-cyan-300"
                />
                <div className="grid grid-cols-4 gap-2">
                  {["#1FD5F9", "#6C5CFF", "#FF4FD8", "#6CFF9E"].map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-label={option}
                      onClick={() => setColor(option as `#${string}`)}
                      className={[
                        "h-9 rounded-xl border transition",
                        color === option ? "border-white/70" : "border-white/12",
                      ].join(" ")}
                      style={{ background: option }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </aside>

        <section className="relative min-h-0 overflow-hidden rounded-[32px] border border-white/10 bg-black/30 shadow-2xl backdrop-blur-2xl">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-200/45 to-transparent" />
          <div className="grid h-full min-h-[calc(100vh-48px)] grid-rows-[1fr_auto]">
            <div className="grid place-items-center px-6 py-10">
              <div className="relative grid place-items-center">
                <div className="absolute h-[34rem] w-[34rem] rounded-full bg-[radial-gradient(circle,rgba(31,213,249,0.12),transparent_64%)] blur-2xl" />
                <AgentAudioVisualizerAura
                  size="xl"
                  state={state}
                  audioTrack={audioTrack}
                  color={color}
                  colorShift={colorShift}
                  themeMode="dark"
                  className="relative z-10"
                />
              </div>
            </div>

            <div className="border-t border-white/10 bg-black/20 p-6">
              <div className="grid gap-4 md:grid-cols-[1fr_220px]">
                <div>
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.28em] text-cyan-200/55">
                    {active.route}
                  </p>
                  <p className="max-w-3xl text-2xl font-semibold leading-snug text-white">
                    {active.prompt}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/8 bg-white/[0.035] p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-white/38">
                    Component source
                  </p>
                  <p className="mt-2 text-sm leading-6 text-white/68">
                    `@agents-ui/agent-audio-visualizer-aura`, installed from LiveKit Agents UI.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}
