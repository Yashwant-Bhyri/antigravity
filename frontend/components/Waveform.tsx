"use client";

import { useEffect, useRef } from "react";

/** Animated waveform bars — pulses when AI is speaking, flat when idle */
export function Waveform({ active }: { active: boolean }) {
  const bars = 20;

  return (
    <div className="flex items-center justify-center gap-[3px] h-12">
      {Array.from({ length: bars }).map((_, i) => (
        <div
          key={i}
          className="w-1 bg-white rounded-full transition-all duration-100"
          style={{
            height: active
              ? `${Math.random() * 32 + 8}px`
              : "4px",
            opacity: active ? 1 : 0.2,
            animationDelay: `${i * 50}ms`,
          }}
        />
      ))}
    </div>
  );
}

/** Mic pulse ring — pulses when candidate is speaking */
export function MicPulse({ active }: { active: boolean }) {
  return (
    <div className="relative flex items-center justify-center">
      {active && (
        <div className="absolute w-20 h-20 rounded-full border border-white/30 animate-ping" />
      )}
      <div
        className={`w-16 h-16 rounded-full flex items-center justify-center transition-colors ${
          active ? "bg-white" : "bg-zinc-800 border border-zinc-600"
        }`}
      >
        <MicIcon active={active} />
      </div>
    </div>
  );
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg
      className={`w-7 h-7 ${active ? "text-black" : "text-zinc-400"}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <rect x="9" y="2" width="6" height="12" rx="3" strokeWidth={2} />
      <path d="M5 10a7 7 0 0014 0" strokeWidth={2} strokeLinecap="round" />
      <line x1="12" y1="21" x2="12" y2="17" strokeWidth={2} strokeLinecap="round" />
      <line x1="8" y1="21" x2="16" y2="21" strokeWidth={2} strokeLinecap="round" />
    </svg>
  );
}
