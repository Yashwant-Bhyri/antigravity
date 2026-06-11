"use client";

import { useEffect, useRef } from "react";

const BAR_COUNT = 40;

export function Waveform({ level, active }: { level: number; active: boolean }) {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    barsRef.current.forEach((bar, i) => {
      if (!bar) return;
      const mid = BAR_COUNT / 2;
      const dist = Math.abs(i - mid) / mid;
      const base = active ? 10 : 5;
      const animated = active ? Math.abs(Math.sin(Date.now() / 180 + i * 0.55)) * level * 48 : 0;
      const height = Math.max(base, Math.round(base + animated * (1 - dist * 0.32)));
      bar.style.height = `${height}px`;
    });
  });

  return (
    <div className="flex h-12 items-center gap-[2px]">
      {Array.from({ length: BAR_COUNT }).map((_, i) => (
        <div
          key={i}
          ref={(el) => {
            barsRef.current[i] = el;
          }}
          className="w-[2.5px] rounded-full transition-[height,background] duration-100"
          style={{
            height: "6px",
            background: active
              ? `oklch(${0.72 - Math.abs(i - BAR_COUNT / 2) * 0.0025} ${0.16 + (i % 5) * 0.01} ${250 + (i - BAR_COUNT / 2) * 0.9})`
              : "oklch(0.24 0.01 265)",
            opacity: active ? 1 : 0.55,
          }}
        />
      ))}
    </div>
  );
}

function OrbIdleContent() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <circle cx="18" cy="18" r="5" stroke="oklch(0.38 0.04 265)" strokeWidth="1.5" />
      <circle cx="18" cy="18" r="11" stroke="oklch(0.24 0.03 265)" strokeWidth="0.75" strokeDasharray="2.5 4" />
      <circle cx="18" cy="18" r="2" fill="oklch(0.3 0.03 265)" />
    </svg>
  );
}

function OrbListeningContent() {
  return (
    <div className="flex h-[30px] items-end gap-[3px] pb-[3px]">
      {[0, 1, 2, 3, 4, 5, 6].map((i) => (
        <div
          key={i}
          className="w-[3px] rounded-[2px] bg-[oklch(0.92_0.006_260)]"
          style={{
            animation: `agWaveBar ${350 + i * 60}ms ease-in-out ${i * 50}ms infinite alternate`,
          }}
        />
      ))}
    </div>
  );
}

function OrbThinkingContent() {
  return (
    <div className="flex items-center gap-[6px]">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[7px] w-[7px] rounded-full bg-[var(--ag-amber)]"
          style={{ animation: `agBounce 900ms ease-in-out ${i * 200}ms infinite` }}
        />
      ))}
    </div>
  );
}

function OrbSpeakingContent() {
  return (
    <div className="relative flex h-11 w-11 items-center justify-center">
      {[14, 22, 30].map((r, i) => (
        <div
          key={i}
          className="absolute rounded-full"
          style={{
            width: r * 2,
            height: r * 2,
            border: `1.5px solid oklch(0.65 0.22 258 / ${0.75 - i * 0.22})`,
            animation: `agRingPulse ${700 + i * 250}ms ease-out ${i * 180}ms infinite`,
          }}
        />
      ))}
      <div className="h-2 w-2 rounded-full bg-[oklch(0.88_0.18_258)] shadow-[0_0_12px_oklch(0.65_0.22_258)]" />
    </div>
  );
}

export function AIOrb({ state }: { state: "idle" | "listening" | "thinking" | "speaking" }) {
  const orbConfig = {
    idle: {
      bg: "radial-gradient(ellipse at 34% 24%, oklch(0.32 0.055 258) 0%, oklch(0.14 0.02 265) 48%, oklch(0.055 0.014 270) 100%)",
      border: "1px solid oklch(0.27 0.03 265 / 0.9)",
      shadow: "none",
      glow: "transparent",
      rings: [] as string[],
    },
    listening: {
      bg: "radial-gradient(circle at 30% 24%, oklch(0.98 0.01 250) 0 7%, oklch(0.88 0.17 196) 16%, oklch(0.68 0.24 224) 36%, oklch(0.52 0.24 280) 62%, oklch(0.12 0.03 265) 100%)",
      border: "1px solid oklch(0.82 0.18 196 / 0.62)",
      shadow: "0 0 34px oklch(0.78 0.2 196 / 0.24), 0 0 96px oklch(0.62 0.24 250 / 0.16)",
      glow: "oklch(0.78 0.2 196 / 0.3)",
      rings: ["oklch(0.82 0.18 196 / 0.32)", "oklch(0.68 0.24 250 / 0.18)", "oklch(0.68 0.24 292 / 0.08)"],
    },
    thinking: {
      bg: "radial-gradient(circle at 32% 26%, oklch(0.96 0.08 78) 0 8%, oklch(0.82 0.18 68) 22%, oklch(0.58 0.2 54) 48%, oklch(0.22 0.08 286) 74%, oklch(0.1 0.024 265) 100%)",
      border: "1px solid oklch(0.78 0.18 68 / 0.58)",
      shadow: "0 0 34px oklch(0.74 0.18 68 / 0.24), 0 0 96px oklch(0.58 0.22 286 / 0.12)",
      glow: "oklch(0.74 0.18 68 / 0.28)",
      rings: [] as string[],
    },
    speaking: {
      bg: "radial-gradient(circle at 30% 22%, oklch(0.94 0.06 238) 0 7%, oklch(0.76 0.28 254) 22%, oklch(0.7 0.3 292) 48%, oklch(0.78 0.27 330) 68%, oklch(0.1 0.03 265) 100%)",
      border: "1px solid oklch(0.68 0.28 258 / 0.68)",
      shadow: "0 0 46px oklch(0.66 0.28 258 / 0.28), 0 0 118px oklch(0.72 0.27 315 / 0.16)",
      glow: "oklch(0.68 0.28 258 / 0.34)",
      rings: ["oklch(0.72 0.28 258 / 0.34)", "oklch(0.78 0.27 330 / 0.18)", "oklch(0.84 0.2 196 / 0.08)"],
    },
  } as const;

  const cfg = orbConfig[state] ?? orbConfig.idle;

  return (
    <div className="relative flex h-[220px] w-[220px] items-center justify-center" data-phase={state}>
      {cfg.glow !== "transparent" && (
        <div
          className="absolute inset-[-46px] rounded-full blur-[22px]"
          style={{
            background: `radial-gradient(ellipse at 50% 50%, ${cfg.glow}, transparent 65%)`,
          }}
        />
      )}
      {cfg.rings.map((color, i) => (
        <div
          key={`${state}-${i}`}
          className="absolute rounded-full"
          style={{
            inset: -(16 + i * 16),
            border: `1px solid ${color}`,
            animation: `agRingPulse ${1400 + i * 500}ms ease-out ${i * 350}ms infinite`,
          }}
        />
      ))}
      {state === "thinking" && (
        <div
          className="absolute inset-[-18px] rounded-full"
          style={{
            background:
              "conic-gradient(from 0deg, transparent 0 62deg, oklch(0.86 0.18 68 / 0.58) 82deg, transparent 112deg 360deg)",
            WebkitMask: "radial-gradient(circle, transparent 61%, #000 63%, #000 66%, transparent 68%)",
            mask: "radial-gradient(circle, transparent 61%, #000 63%, #000 66%, transparent 68%)",
            animation: "agSpin 3.2s linear infinite",
          }}
        />
      )}
      <div
        className="relative flex h-[164px] w-[164px] items-center justify-center overflow-hidden rounded-full transition-all duration-700"
        style={{
          background: cfg.bg,
          border: cfg.border,
          boxShadow: cfg.shadow,
        }}
      >
        <div
          className="pointer-events-none absolute inset-[-22%] opacity-0"
          style={{
            background:
              "linear-gradient(112deg, transparent 22%, rgba(255,255,255,0.42) 42%, transparent 62%)",
            animation: state === "thinking" ? "agThinkSweep 2.4s ease-in-out infinite" : "none",
            opacity: state === "thinking" ? 1 : 0,
          }}
        />
        <div
          className="pointer-events-none absolute inset-[-30%] opacity-0"
          style={{
            background:
              "radial-gradient(ellipse at 50% 50%, rgba(255,255,255,0.16), transparent 58%)",
            animation: state === "speaking" ? "agGlowFast 1.05s ease-in-out infinite" : "none",
            opacity: state === "speaking" ? 1 : 0,
          }}
        />
        <div
          className="pointer-events-none absolute left-[16%] top-[9%] h-[24%] w-[36%] rounded-full"
          style={{
            background: "radial-gradient(ellipse, rgba(255,255,255,0.22), transparent 80%)",
          }}
        />
        {state === "idle" && <OrbIdleContent />}
        {state === "listening" && <OrbListeningContent />}
        {state === "thinking" && <OrbThinkingContent />}
        {state === "speaking" && <OrbSpeakingContent />}
      </div>
    </div>
  );
}
