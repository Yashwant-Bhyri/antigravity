"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { MicStreamer, speakText } from "@/lib/audio";
import { MicPulse, Waveform } from "@/components/Waveform";

type Message = {
  role: "ai" | "candidate";
  text: string;
  weakness?: { type: string; severity: string } | null;
  sprint?: number;
};

type Phase = "idle" | "candidate_speaking" | "processing" | "ai_speaking";

const SPRINT_LABELS: Record<number, string> = {
  1: "Sprint 1 — Project Defense",
  2: "Sprint 2 — Foundations",
  3: "Sprint 3 — System Design",
};

const PERSONA_LABELS: Record<string, string> = {
  curious_lead: "Curious Lead",
  socratic_mentor: "Socratic Mentor",
  senior_peer: "Senior Peer",
};

export default function InterviewPage() {
  const { session_id } = useParams<{ session_id: string }>();
  const router = useRouter();

  const [messages, setMessages] = useState<Message[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [sprint, setSprint] = useState(1);
  const [persona, setPersona] = useState("curious_lead");
  const [questionCount, setQuestionCount] = useState(0);
  const [isStarted, setIsStarted] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const streamerRef = useRef<MicStreamer | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevSprintRef = useRef(1);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, partialTranscript]);

  const handleComplete = useCallback(async (sessionId: string) => {
    setIsComplete(true);
    streamerRef.current?.stop();
    // Trigger backend evaluation
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/end_interview/${sessionId}`, {
      method: "POST",
    });
    setTimeout(() => router.push(`/report/${sessionId}`), 3000);
  }, [router]);

  const handleFollowup = useCallback(async (
    text: string,
    weakness: unknown,
    newSprint: number,
    newPersona: string,
    complete: boolean,
    sessionId: string,
  ) => {
    setPhase("ai_speaking");
    setPartialTranscript("");

    // Sprint change announcement
    if (newSprint !== prevSprintRef.current) {
      prevSprintRef.current = newSprint;
      setSprint(newSprint);
      setPersona(newPersona);
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          text: `— ${SPRINT_LABELS[newSprint]} —`,
          sprint: newSprint,
        },
      ]);
    }

    setMessages((prev) => [
      ...prev,
      { role: "ai", text, weakness: weakness as Message["weakness"], sprint: newSprint },
    ]);

    await speakText(text, !complete);
    setPhase(complete ? "idle" : "candidate_speaking");

    if (complete) {
      await handleComplete(sessionId);
    }
  }, [handleComplete]);

  async function startInterview() {
    setIsStarted(true);
    setPhase("ai_speaking");

    const state = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL}/state/${session_id}`
    ).then((r) => r.json());

    const opening = state.last_question || "Tell me about your most complex project.";
    setSprint(state.current_sprint || 1);
    setPersona(state.current_persona || "curious_lead");

    setMessages([{ role: "ai", text: opening, sprint: 1 }]);
    await speakText(opening, false);

    const streamer = new MicStreamer({
      onTranscriptPartial: (text) => {
        setPartialTranscript(text);
        setPhase("candidate_speaking");
      },
      onTranscriptFinal: (text) => {
        setPartialTranscript("");
        setMessages((prev) => [...prev, { role: "candidate", text }]);
        setPhase("processing");
        setQuestionCount((c) => c + 1);
      },
      onFollowup: (text, weakness, newSprint, newPersona, complete) =>
        handleFollowup(text, weakness, newSprint ?? sprint, newPersona ?? persona, complete ?? false, session_id),
    });

    streamerRef.current = streamer;
    await streamer.start(session_id);
    setPhase("candidate_speaking");
  }

  async function endInterview() {
    streamerRef.current?.stop();
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/end_interview/${session_id}`, {
      method: "POST",
    });
    router.push(`/report/${session_id}`);
  }

  useEffect(() => {
    return () => streamerRef.current?.stop();
  }, []);

  const progressPercent = Math.min((questionCount / 15) * 100, 100);

  return (
    <div className="min-h-screen bg-black text-white flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
        <div className="flex items-center gap-4">
          <span className="font-semibold text-sm">Antigravity</span>
          <span className="text-xs text-zinc-500">{SPRINT_LABELS[sprint]}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
            {PERSONA_LABELS[persona]}
          </span>
        </div>
        <div className="flex items-center gap-4">
          {/* Progress bar */}
          <div className="hidden sm:flex items-center gap-2">
            <div className="w-24 h-1 bg-zinc-800 rounded-full">
              <div
                className="h-1 bg-white rounded-full transition-all duration-500"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <span className="text-xs text-zinc-600">{questionCount}/15</span>
          </div>
          {!isComplete && (
            <button
              onClick={endInterview}
              className="text-xs text-zinc-500 hover:text-red-400 transition"
            >
              End
            </button>
          )}
        </div>
      </header>

      {/* Transcript feed */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4 max-w-3xl mx-auto w-full">
        {messages.map((msg, i) => {
          // Sprint divider
          if (msg.role === "ai" && msg.text.startsWith("—")) {
            return (
              <div key={i} className="flex items-center gap-3 py-2">
                <div className="flex-1 h-px bg-zinc-800" />
                <span className="text-xs text-zinc-500">{msg.text}</span>
                <div className="flex-1 h-px bg-zinc-800" />
              </div>
            );
          }

          return (
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
                {msg.weakness?.severity === "high" && (
                  <div className="mt-2 text-xs text-red-400 opacity-60">
                    ⚠ {msg.weakness.type?.replace(/_/g, " ")}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Live partial transcript */}
        {partialTranscript && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-zinc-800 text-zinc-400 italic">
              {partialTranscript}
            </div>
          </div>
        )}

        {isComplete && (
          <div className="text-center py-6 text-zinc-500 text-sm">
            Interview complete. Generating your report...
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Bottom controls */}
      <div className="border-t border-zinc-800 px-6 py-6">
        <div className="max-w-3xl mx-auto flex flex-col items-center gap-4">
          <Waveform active={phase === "ai_speaking"} />

          <p className="text-xs text-zinc-500 h-4">
            {phase === "idle" && !isStarted && "Press Begin to start"}
            {phase === "idle" && isStarted && ""}
            {phase === "candidate_speaking" && "Listening..."}
            {phase === "processing" && "Analyzing..."}
            {phase === "ai_speaking" && "AI speaking..."}
          </p>

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
