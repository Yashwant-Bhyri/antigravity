"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { InterviewSession, processTurn, speakText, prefetchAudio, playAudioUrl, FloorState } from "@/lib/audio";
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
  const [showCamera, setShowCamera] = useState(false);

  const sessionRef = useRef<InterviewSession | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const prevSprintRef = useRef(1);
  const stopVisualizerRef = useRef<(() => void) | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const processingRef = useRef(false); // prevents concurrent onFinal handlers
  const currentTurnIdRef = useRef("");

  // Guard against malformed URLs (e.g. /interview/undefined)
  useEffect(() => {
    if (!session_id || session_id === "undefined") router.replace("/");
  }, [session_id, router]);

  // Auto-scroll
  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, partial]);

  // handleFollowup accepts a pre-fetched audioUrl so it can play immediately with zero lag.
  const handleFollowup = useCallback(async (
    result: Record<string, unknown>,
    preloadedAudioUrl: string | null,
    expectedTurnId: string,
  ) => {
    if (expectedTurnId !== currentTurnIdRef.current) {
      if (preloadedAudioUrl) URL.revokeObjectURL(preloadedAudioUrl);
      return;
    }

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

    // Show message and start audio simultaneously
    setMessages((prev) => [...prev, {
      role: "ai",
      text,
      severity: weakness?.severity,
    }]);
    setQuestionCount((c) => c + 1);

    // Create abort controller for interruption
    const ac = new AbortController();
    sessionRef.current?.setAbortController(ac);
    sessionRef.current?.transition(FloorState.AI_SPEAKING);

    try {
      await playAudioUrl(preloadedAudioUrl, text, ac.signal);
    } catch (e) {
      console.log("[UI] Audio play interrupted/failed", e);
    }

    if (expectedTurnId !== currentTurnIdRef.current) {
      return;
    }

    sessionRef.current?.transition(isComplete ? FloorState.IDLE : FloorState.USER_SPEAKING);

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

    // Fetch opening question
    const state = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/state/${session_id}`).then((r) => r.json());
    const opening = state.last_question;
    setSprint(state.current_sprint);
    setPersona(state.current_persona);

    const openingAudioUrl = await prefetchAudio(opening);
    setMessages([{ role: "ai", text: opening }]);

    // Boot Deepgram session
    const session = new InterviewSession(session_id);
    sessionRef.current = session;

    session.onFloorChange = (floor) => {
      if (floor === FloorState.USER_SPEAKING) setPhase("listening");
      else if (floor === FloorState.AI_THINKING) setPhase("thinking");
      else if (floor === FloorState.AI_SPEAKING) setPhase("speaking");
      else setPhase("idle");
    };

    session.onBargeIn = () => {
      console.log("[UI] Barge-in! Invalidating active turn.");
      currentTurnIdRef.current = crypto.randomUUID(); // Invalidate current turn
      setPartial("");
    };

    session.onSilence = async () => {
      console.log("[UI] User is silent. Nudging.");
      // Use floor state (ref-based, always current) not `phase` (stale React closure)
      if (processingRef.current || session.floor !== FloorState.USER_SPEAKING) return;
      
      const ac = new AbortController();
      session.setAbortController(ac);
      session.transition(FloorState.AI_SPEAKING);
      
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/tts_filler`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        await playAudioUrl(url, "Take your time, I'm listening.", ac.signal);
      } catch (e) {
        console.log("[UI] Silence nudge interrupted");
      }
      
      // transition() is a no-op if already USER_SPEAKING (barge-in already handled it)
      session.transition(FloorState.USER_SPEAKING);
    };

    session.onPartial = (text) => {
      setPartial(text);
    };

    session.onFinal = async (text, entities) => {
      if (processingRef.current) return;
      processingRef.current = true;

      const turnId = crypto.randomUUID();
      currentTurnIdRef.current = turnId;
      setPartial("");
      setMessages((prev) => [...prev, { role: "candidate", text }]);

      try {
        const result = await processTurn(session_id, text, entities, turnId);
        const responseTurnId = typeof result.turn_id === "string" ? result.turn_id : turnId;

        if (responseTurnId !== currentTurnIdRef.current) return;

        const audioUrl = await prefetchAudio(result.response as string);
        if (responseTurnId !== currentTurnIdRef.current) {
          if (audioUrl) URL.revokeObjectURL(audioUrl);
          return;
        }
        await handleFollowup(result, audioUrl, responseTurnId);
      } catch (e) {
        setError("Agent pipeline error. Check backend.");
        session.transition(FloorState.USER_SPEAKING);
      } finally {
        processingRef.current = false;
      }
    };

    session.onError = (err) => {
      setError(`Voice error: ${err}`);
    };

    try {
      await session.start();
      stopVisualizerRef.current = session.connectVisualizer((level) => setMicLevel(level));
      
      // Phase 2: Start Vision if enabled
      if (showCamera && videoRef.current) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: true });
          videoRef.current.srcObject = stream;
          await session.startVision(videoRef.current);
        } catch (vErr) {
          console.error("[UI] Camera permission denied or failed:", vErr);
        }
      }

      // Play opening question with the session's floor logic
      const ac = new AbortController();
      session.setAbortController(ac);
      session.transition(FloorState.AI_SPEAKING);
      await playAudioUrl(openingAudioUrl, opening, ac.signal);
      session.transition(FloorState.USER_SPEAKING);
    } catch (e) {
      setError(`Could not start mic: ${String(e)}`);
      setStarted(false);
      setPhase("idle");
    }
  }


  function endInterview() {
    currentTurnIdRef.current = crypto.randomUUID();
    stopVisualizerRef.current?.();
    sessionRef.current?.stop();
    
    // Stop camera
    if (videoRef.current?.srcObject) {
      (videoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
    }

    fetch(`${process.env.NEXT_PUBLIC_API_URL}/end_interview/${session_id}`, { method: "POST" });
    router.push(`/report/${session_id}`);
  }

  useEffect(() => {
    return () => {
      currentTurnIdRef.current = crypto.randomUUID();
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
          {/* Camera toggle */}
          {!started && (
            <button 
              onClick={() => setShowCamera(!showCamera)}
              className={`flex items-center gap-2 px-3 py-1 rounded-full border transition-all text-[11px] ${
                showCamera ? "bg-white/10 border-white/20 text-white" : "border-white/5 text-zinc-500 hover:border-white/10"
              }`}
            >
              <div className={`w-1.5 h-1.5 rounded-full ${showCamera ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]" : "bg-zinc-700"}`} />
              Lens Early-Turn {showCamera ? "ON" : "OFF"}
            </button>
          )}

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
        <div className="w-80 flex-shrink-0 border-r border-white/5 flex flex-col items-center justify-center gap-6 px-6">
          
          <div className="relative w-full aspect-square max-w-[200px] flex items-center justify-center">
             {/* Camera feed (background) */}
             {showCamera && (
                <div className="absolute inset-0 rounded-full overflow-hidden border border-white/5 bg-black/40 mix-blend-screen opacity-40 grayscale">
                   <video 
                     ref={videoRef}
                     autoPlay 
                     playsInline 
                     muted 
                     className="w-full h-full object-cover scale-x-[-1]"
                   />
                </div>
             )}
             <AIOrb state={phase} />
          </div>

          <div className="text-center space-y-1">
            <p className="text-xs font-medium text-zinc-300">
              {phase === "idle" && !started && "Ready"}
              {phase === "listening" && "Listening"}
              {phase === "thinking" && "Analyzing..."}
              {phase === "speaking" && "Speaking"}
            </p>
            {started && (
              <p className="text-[11px] text-zinc-600 font-mono tracking-wider">{PERSONA_DESC[persona]}</p>
            )}
          </div>

          {/* Mic waveform — only when listening */}
          {phase === "listening" && (
            <Waveform level={micLevel} active={true} />
          )}

          {started && showCamera && (
             <div className="mt-8 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/[0.05]">
                <p className="text-[9px] text-zinc-600 uppercase tracking-widest text-center">Lens Active</p>
                <div className="mt-1 flex items-center gap-1">
                   <div className="flex-1 h-[2px] bg-white/5 rounded-full overflow-hidden">
                      <div className="h-full bg-green-500/40 w-full animate-pulse" />
                   </div>
                </div>
             </div>
          )}
        </div>

        {/* ── Right: Transcript ── */}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {/* Subtle noise texture */}
          <div className="absolute inset-0 opacity-[0.03] pointer-events-none bg-[url('https://grainy-gradients.vercel.app/noise.svg')]" />
          
          <div
            ref={transcriptRef}
            className="flex-1 overflow-y-auto px-10 py-8 space-y-6 relative"
          >
            {!started && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center space-y-4 max-w-sm">
                  <div className="w-12 h-12 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mx-auto mb-6">
                    <span className="text-xl">∞</span>
                  </div>
                  <h2 className="text-lg font-medium text-zinc-200">Antigravity Protocol</h2>
                  <p className="text-zinc-500 text-sm leading-relaxed">
                    A real-time cognitive interrogation system. 3 sprints. No validation. Only the boundary of your reasoning exists here.
                  </p>
                  <p className="text-zinc-700 text-[10px] uppercase tracking-[0.2em] pt-4">Probe → Break → Analyze → Adapt</p>
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
               <MessageItem key={i} msg={msg} />
            ))}

            {/* Live partial */}
            {partial && (
              <div className="flex justify-end pr-4">
                <div className="max-w-[80%]">
                  <p className="text-[10px] text-zinc-600 uppercase tracking-widest mb-2 text-right">Accumulating</p>
                  <div className="rounded-2xl px-5 py-3.5 text-[13px] bg-white/[0.03] text-zinc-400 border border-white/[0.05] italic">
                    {partial}
                  </div>
                </div>
              </div>
            )}

            {complete && (
              <div className="text-center py-12 space-y-2 animate-in fade-in slide-in-from-bottom-2 duration-1000">
                <div className="inline-block px-3 py-1 rounded-full bg-green-500/10 border border-green-500/20 text-green-500 text-[10px] mb-2 uppercase tracking-widest">Complete</div>
                <p className="text-zinc-200 text-sm font-medium">Session Terminated.</p>
                <p className="text-zinc-500 text-[11px]">Compiling adversarial report and reasoning metrics...</p>
              </div>
            )}
          </div>

          {/* ── Bottom action bar ── */}
          <div className="border-t border-white/5 px-10 py-6 flex items-center justify-between bg-[#0a0a0a]/80 backdrop-blur-xl">
            {error && (
               <div className="flex items-center gap-2 text-red-400 text-[11px] animate-pulse">
                  <div className="w-1 ha-1 rounded-full bg-red-400" />
                  {error}
               </div>
            )}
            {!error && <span />}

            {!started ? (
              <button
                onClick={startInterview}
                className="ml-auto bg-white text-black text-[13px] font-semibold px-8 py-3 rounded-full hover:bg-zinc-100 transition-all hover:scale-105 active:scale-95 shadow-lg shadow-white/10"
              >
                Engage System →
              </button>
            ) : (
              <div className="ml-auto flex items-center gap-3 text-[11px] font-medium text-zinc-400">
                <div className="flex items-center gap-2">
                   {phase === "listening" && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
                   {phase === "thinking" && <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />}
                   {phase === "speaking" && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />}
                   <span className="uppercase tracking-widest text-[10px] text-zinc-500">
                     {phase === "listening" ? "Listening"
                      : phase === "thinking" ? "Reasoning"
                      : phase === "speaking" ? "Speaking"
                      : "Idle"}
                   </span>
                </div>
                <div className="h-4 w-px bg-white/10" />
                <span className="text-zinc-600 tabular-nums uppercase text-[10px]">Turn Trace: {currentTurnIdRef.current.slice(0, 8)}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageItem({ msg }: { msg: Message }) {
  if (msg.isSprintMarker) {
    return (
      <div className="flex items-center gap-6 py-6 px-10">
        <div className="flex-1 h-px bg-white/5" />
        <span className="text-[10px] text-zinc-600 uppercase tracking-[0.3em] font-medium">
          {msg.text}
        </span>
        <div className="flex-1 h-px bg-white/5" />
      </div>
    );
  }

  const isAI = msg.role === "ai";
  return (
    <div className={`flex ${isAI ? "justify-start" : "justify-end"} group animate-in fade-in slide-in-from-bottom-1 duration-500`}>
      <div className={`max-w-[85%] space-y-2`}>
        <div className={`flex items-center gap-2 ${isAI ? "" : "flex-row-reverse"}`}>
           <p className={`text-[10px] uppercase tracking-widest font-bold ${
             isAI ? "text-zinc-500" : "text-zinc-500"
           }`}>
             {isAI ? "Protocol" : "Candidate"}
           </p>
           {msg.severity === "high" && (
             <span className="text-[9px] bg-red-500/10 text-red-500 border border-red-500/20 px-1.5 py-0.5 rounded-md font-bold animate-pulse">BOUNDARY EXPOSED</span>
           )}
        </div>
        <div className={`rounded-3xl px-6 py-4.5 text-[14px] leading-[1.6] ${
          isAI
            ? "bg-white/[0.03] text-zinc-300 border border-white/[0.05] shadow-sm"
            : "bg-white/[0.07] text-white border border-white/[0.1] shadow-md"
        }`}>
          {msg.text}
        </div>
      </div>
    </div>
  );
}
