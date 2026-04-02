"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { InterviewSession, processTurn, speakText, prefetchAudio, playAudioUrl } from "@/lib/audio";
import { AIOrb, Waveform } from "@/components/Waveform";

type Phase = "idle" | "listening" | "thinking" | "speaking";

type Message = {
  role: "ai" | "candidate";
  text: string;
  severity?: string;
  isSprintMarker?: boolean;
  sprint?: number;
};

const SPRINT_LABELS: Record<number, string> = {
  1: "Project Defense",
  2: "Foundations",
  3: "System Design",
};

const PERSONA_DESC: Record<string, string> = {
  curious_lead: "Challenging your ownership",
  socratic_mentor: "Testing first principles",
  senior_peer: "Stress-testing your design",
};

export default function InterviewPage() {
  const { session_id } = useParams<{ session_id: string }>();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [partial, setPartial] = useState("");
  const [sprint, setSprint] = useState(1);
  const [persona, setPersona] = useState("curious_lead");
  const [questionCount, setQuestionCount] = useState(0);
  const [micLevel, setMicLevel] = useState(0);
  const [started, setStarted] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");

  const sessionRef = useRef<InterviewSession | null>(null);
  const prevSprintRef = useRef(1);
  const stopVisualizerRef = useRef<(() => void) | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const processingRef = useRef(false); // prevents concurrent onFinal handlers

  // Guard against malformed URLs (e.g. /interview/undefined)
  useEffect(() => {
    if (!session_id || session_id === "undefined") router.replace("/");
  }, [session_id, router]);

  // Auto-scroll
  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, partial]);

  // handleFollowup accepts a pre-fetched audioUrl so it can play immediately with zero lag.
  // Audio is fetched during the LLM pipeline (while filler plays) — not here.
  const handleFollowup = useCallback(async (
    result: Record<string, unknown>,
    preloadedAudioUrl: string | null,
  ) => {
    const text = result.response as string;
    const newSprint = result.sprint as number;
    const newPersona = result.persona as string;
    const isComplete = result.complete as boolean;
    const weakness = result.weakness as { severity?: string } | null;

    // Sprint transition marker
    if (newSprint !== prevSprintRef.current) {
      prevSprintRef.current = newSprint;
      setSprint(newSprint);
      setPersona(newPersona);
      setMessages((prev) => [...prev, {
        role: "ai",
        text: `Sprint ${newSprint} — ${SPRINT_LABELS[newSprint]}`,
        isSprintMarker: true,
        sprint: newSprint,
      }]);
    }

    // Show message and start audio simultaneously — audio is already fetched
    setMessages((prev) => [...prev, {
      role: "ai",
      text,
      severity: weakness?.severity,
    }]);
    setQuestionCount((c) => c + 1);
    setPhase("speaking");
    await playAudioUrl(preloadedAudioUrl, text);
    setPhase(isComplete ? "idle" : "listening");

    if (isComplete) {
      setComplete(true);
      sessionRef.current?.stop();
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/end_interview/${session_id}`, { method: "POST" });
      setTimeout(() => router.push(`/report/${session_id}`), 2500);
    }
  }, [session_id, router]);

  async function startInterview() {
    setError("");
    setStarted(true);
    setPhase("speaking");

    // Fetch opening question and pre-fetch audio in parallel
    const state = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/state/${session_id}`).then((r) => r.json());
    const opening = state.last_question;
    setSprint(state.current_sprint);
    setPersona(state.current_persona);

    const openingAudioUrl = await prefetchAudio(opening);
    setMessages([{ role: "ai", text: opening }]);
    await playAudioUrl(openingAudioUrl, opening);

    // Boot Deepgram session
    const session = new InterviewSession(session_id);
    sessionRef.current = session;

    session.onPartial = (text) => {
      setPartial(text);
      setPhase("listening");
    };

    session.onFinal = async (text, entities) => {
      if (processingRef.current) return; // drop utterance if still processing previous
      processingRef.current = true;

      setPartial("");
      setMessages((prev) => [...prev, { role: "candidate", text }]);
      setPhase("thinking");

      try {
        const result = await processTurn(session_id, text, entities);
        // Prefetch audio while still in thinking state, then show message + play together
        const audioUrl = await prefetchAudio(result.response as string);
        await handleFollowup(result, audioUrl);
      } catch (e) {
        setError("Agent pipeline error. Check backend.");
        setPhase("listening");
      } finally {
        processingRef.current = false;
      }
    };

    session.onError = (err) => {
      setError(`Voice error: ${err}`);
    };

    try {
      await session.start();
      // Wire mic level to visualizer
      stopVisualizerRef.current = session.connectVisualizer((level) => setMicLevel(level));
      setPhase("listening");
    } catch (e) {
      setError(`Could not start mic: ${String(e)}`);
      setStarted(false);
      setPhase("idle");
    }
  }

  function endInterview() {
    stopVisualizerRef.current?.();
    sessionRef.current?.stop();
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/end_interview/${session_id}`, { method: "POST" });
    router.push(`/report/${session_id}`);
  }

  useEffect(() => {
    return () => {
      stopVisualizerRef.current?.();
      sessionRef.current?.stop();
    };
  }, []);

  const progressPct = Math.min((questionCount / 15) * 100, 100);

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white flex flex-col select-none">

      {/* ── Top bar ── */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-white/5">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold tracking-tight">Antigravity</span>
          {started && (
            <span className="text-xs px-2 py-0.5 rounded-md bg-white/5 text-zinc-400">
              Sprint {sprint} — {SPRINT_LABELS[sprint]}
            </span>
          )}
        </div>

        <div className="flex items-center gap-4">
          {/* Progress bar */}
          {started && (
            <div className="flex items-center gap-2">
              <div className="w-20 h-[3px] bg-white/10 rounded-full overflow-hidden">
                <div
                  className="h-full bg-white/60 rounded-full transition-all duration-700"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="text-[11px] text-zinc-600 tabular-nums">{questionCount}/15</span>
            </div>
          )}
          {started && !complete && (
            <button onClick={endInterview} className="text-[11px] text-zinc-600 hover:text-red-400 transition-colors">
              End
            </button>
          )}
        </div>
      </header>

      {/* ── Main ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Left: AI panel ── */}
        <div className="w-72 flex-shrink-0 border-r border-white/5 flex flex-col items-center justify-center gap-6 px-6">
          <AIOrb state={phase} />

          <div className="text-center space-y-1">
            <p className="text-xs font-medium text-zinc-300">
              {phase === "idle" && !started && "Ready"}
              {phase === "listening" && "Listening"}
              {phase === "thinking" && "Analyzing..."}
              {phase === "speaking" && "Speaking"}
            </p>
            {started && (
              <p className="text-[11px] text-zinc-600">{PERSONA_DESC[persona]}</p>
            )}
          </div>

          {/* Mic waveform — only when listening */}
          {phase === "listening" && (
            <Waveform level={micLevel} active={true} />
          )}
        </div>

        {/* ── Right: Transcript ── */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div
            ref={transcriptRef}
            className="flex-1 overflow-y-auto px-8 py-6 space-y-5"
          >
            {!started && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center space-y-2">
                  <p className="text-zinc-500 text-sm">30 minutes. 3 sprints. No hints.</p>
                  <p className="text-zinc-700 text-xs">Probe → Break → Analyze → Adapt</p>
                </div>
              </div>
            )}

            {messages.map((msg, i) => {
              if (msg.isSprintMarker) {
                return (
                  <div key={i} className="flex items-center gap-4 py-1">
                    <div className="flex-1 h-px bg-white/5" />
                    <span className="text-[11px] text-zinc-600 uppercase tracking-widest">
                      {msg.text}
                    </span>
                    <div className="flex-1 h-px bg-white/5" />
                  </div>
                );
              }

              return (
                <div
                  key={i}
                  className={`flex ${msg.role === "ai" ? "justify-start" : "justify-end"}`}
                >
                  <div className={`max-w-[85%] space-y-1`}>
                    <p className={`text-[11px] uppercase tracking-widest mb-1 ${
                      msg.role === "ai" ? "text-zinc-600" : "text-zinc-600 text-right"
                    }`}>
                      {msg.role === "ai" ? "INTERVIEWER" : "YOU"}
                    </p>
                    <div className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
                      msg.role === "ai"
                        ? "bg-white/[0.04] text-zinc-200 border border-white/[0.06]"
                        : "bg-white/[0.08] text-white border border-white/[0.10]"
                    }`}>
                      {msg.text}
                    </div>
                    {msg.severity === "high" && (
                      <p className="text-[10px] text-red-500/70 px-1">⚠ Weak point detected</p>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Live partial */}
            {partial && (
              <div className="flex justify-end">
                <div className="max-w-[85%]">
                  <p className="text-[11px] text-zinc-600 uppercase tracking-widest mb-1 text-right">YOU</p>
                  <div className="rounded-xl px-4 py-3 text-sm bg-white/[0.03] text-zinc-500 border border-white/[0.05] italic">
                    {partial}
                  </div>
                </div>
              </div>
            )}

            {complete && (
              <div className="text-center py-8 space-y-1">
                <p className="text-zinc-400 text-sm">Interview complete.</p>
                <p className="text-zinc-600 text-xs">Generating your report...</p>
              </div>
            )}
          </div>

          {/* ── Bottom action bar ── */}
          <div className="border-t border-white/5 px-8 py-5 flex items-center justify-between">
            {error && <p className="text-red-400 text-xs">{error}</p>}
            {!error && <span />}

            {!started ? (
              <button
                onClick={startInterview}
                className="ml-auto bg-white text-black text-sm font-semibold px-6 py-2.5 rounded-full hover:bg-zinc-100 transition-colors"
              >
                Begin Interview →
              </button>
            ) : (
              <div className="ml-auto flex items-center gap-2 text-xs text-zinc-600">
                {phase === "listening" && <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse inline-block" />}
                {phase === "thinking" && <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse inline-block" />}
                {phase === "speaking" && <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse inline-block" />}
                <span>
                  {phase === "listening" ? "Listening — speak now"
                   : phase === "thinking" ? "Analyzing your answer..."
                   : phase === "speaking" ? "AI speaking..."
                   : ""}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
