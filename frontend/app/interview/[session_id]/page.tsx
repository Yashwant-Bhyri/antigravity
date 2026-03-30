"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { MicStreamer, speakText } from "@/lib/audio";
import { MicPulse, Waveform } from "@/components/Waveform";

type Message = {
  role: "ai" | "candidate";
  text: string;
  weakness?: { type: string; severity: string } | null;
};

type Phase = "idle" | "candidate_speaking" | "processing" | "ai_speaking";

const SPRINT_LABELS: Record<number, string> = {
  1: "Sprint 1 — Project Defense",
  2: "Sprint 2 — Foundations",
  3: "Sprint 3 — System Design",
};

export default function InterviewPage() {
  const { session_id } = useParams<{ session_id: string }>();
  const router = useRouter();

  const [messages, setMessages] = useState<Message[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [sprint, setSprint] = useState(1);
  const [isStarted, setIsStarted] = useState(false);
  const streamerRef = useRef<MicStreamer | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, partialTranscript]);

  const handleFollowup = useCallback(async (text: string, weakness: unknown) => {
    setPhase("ai_speaking");
    setPartialTranscript("");

    setMessages((prev) => [
      ...prev,
      {
        role: "ai",
        text,
        weakness: weakness as Message["weakness"],
      },
    ]);

    await speakText(text, true);
    setPhase("candidate_speaking");
  }, []);

  async function startInterview() {
    setIsStarted(true);
    setPhase("ai_speaking");

    // Fetch opening question
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/state/${session_id}`);
    const state = await res.json();
    const opening = state.last_question || "Tell me about your most complex project.";

    setMessages([{ role: "ai", text: opening }]);
    await speakText(opening, false);

    // Start mic streaming
    const streamer = new MicStreamer({
      onTranscriptPartial: (text) => {
        setPartialTranscript(text);
        setPhase("candidate_speaking");
      },
      onTranscriptFinal: (text) => {
        setPartialTranscript("");
        setMessages((prev) => [...prev, { role: "candidate", text }]);
        setPhase("processing");
      },
      onFollowup: handleFollowup,
    });

    streamerRef.current = streamer;
    await streamer.start(session_id);
    setPhase("candidate_speaking");
  }

  async function endInterview() {
    streamerRef.current?.stop();
    router.push(`/report/${session_id}`);
  }

  useEffect(() => {
    return () => streamerRef.current?.stop();
  }, []);

  return (
    <div className="min-h-screen bg-black text-white flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
        <div>
          <span className="font-semibold text-sm">Antigravity</span>
          <span className="ml-3 text-xs text-zinc-500">{SPRINT_LABELS[sprint]}</span>
        </div>
        <button
          onClick={endInterview}
          className="text-xs text-zinc-500 hover:text-red-400 transition"
        >
          End Interview
        </button>
      </header>

      {/* Transcript feed */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4 max-w-3xl mx-auto w-full">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "ai" ? "justify-start" : "justify-end"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "ai"
                  ? "bg-zinc-900 text-white"
                  : "bg-white text-black"
              }`}
            >
              {msg.text}
              {msg.weakness && msg.weakness.severity === "high" && (
                <div className="mt-2 text-xs text-red-400 opacity-60">
                  ⚠ {msg.weakness.type}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Live partial transcript */}
        {partialTranscript && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-zinc-800 text-zinc-400 italic">
              {partialTranscript}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Bottom controls */}
      <div className="border-t border-zinc-800 px-6 py-6">
        <div className="max-w-3xl mx-auto flex flex-col items-center gap-4">
          {/* Waveform — shows when AI is speaking */}
          <Waveform active={phase === "ai_speaking"} />

          {/* Status */}
          <p className="text-xs text-zinc-500 h-4">
            {phase === "idle" && "Press Begin to start"}
            {phase === "candidate_speaking" && "Listening..."}
            {phase === "processing" && "Analyzing..."}
            {phase === "ai_speaking" && "AI speaking..."}
          </p>

          {/* Mic button */}
          {!isStarted ? (
            <button
              onClick={startInterview}
              className="bg-white text-black font-semibold px-8 py-3 rounded-full hover:bg-zinc-200 transition"
            >
              Begin Interview
            </button>
          ) : (
            <MicPulse active={phase === "candidate_speaking"} />
          )}
        </div>
      </div>
    </div>
  );
}
