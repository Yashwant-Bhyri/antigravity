"use client";

import { createClient, LiveTranscriptionEvents } from "@deepgram/sdk";
import { useEffect, useMemo, useRef, useState } from "react";
import { getApiBaseUrl } from "@/lib/api";

const API = getApiBaseUrl();

type ProviderStatus = {
  openai_configured: boolean;
  deepgram_configured: boolean;
  default_realtime_model: string;
  realtime_models: string[];
  default_transcribe_model: string;
  transcribe_models: string[];
  realtime_transcription_model: string;
};

type LabEvent = {
  id: string;
  ts: string;
  type: string;
  detail?: string;
};

function float32ToPcm16(float32: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

function nowLabel() {
  return new Date().toLocaleTimeString();
}

function shortJson(value: unknown) {
  try {
    return JSON.stringify(value).slice(0, 280);
  } catch {
    return String(value).slice(0, 280);
  }
}

export default function VoiceLabPage() {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [realtimeModel, setRealtimeModel] = useState("gpt-realtime-mini");
  const [transcribeModel, setTranscribeModel] = useState("gpt-4o-mini-transcribe");
  const [enableRealtime, setEnableRealtime] = useState(true);
  const [enableDeepgram, setEnableDeepgram] = useState(true);
  const [running, setRunning] = useState(false);
  const [deepgramRunning, setDeepgramRunning] = useState(false);
  const [realtimeRunning, setRealtimeRunning] = useState(false);
  const [recordingSample, setRecordingSample] = useState(false);
  const [error, setError] = useState("");
  const [candidatePartial, setCandidatePartial] = useState("");
  const [candidateFinal, setCandidateFinal] = useState("");
  const [deepgramPartial, setDeepgramPartial] = useState("");
  const [deepgramFinal, setDeepgramFinal] = useState("");
  const [realtimePartial, setRealtimePartial] = useState("");
  const [realtimeFinal, setRealtimeFinal] = useState("");
  const [aiTranscript, setAiTranscript] = useState("");
  const [openaiTranscribeText, setOpenaiTranscribeText] = useState("");
  const [functionCalls, setFunctionCalls] = useState(0);
  const [events, setEvents] = useState<LabEvent[]>([]);

  const micStreamRef = useRef<MediaStream | null>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const dgConnectionRef = useRef<any>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const deepgramSeqRef = useRef(0);
  const realtimeSeqRef = useRef(0);

  const candidateConsensus = useMemo(() => {
    return realtimeFinal || deepgramFinal || candidateFinal || openaiTranscribeText || "";
  }, [candidateFinal, deepgramFinal, openaiTranscribeText, realtimeFinal]);

  useEffect(() => {
    setSessionId(`voice-lab-${crypto.randomUUID()}`);
    refreshStatus();
    return () => {
      stopAll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshStatus() {
    try {
      const res = await fetch(`${API}/voice/status`, { cache: "no-store" });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.detail || `Status failed (${res.status})`);
      setStatus(payload);
      setRealtimeModel(payload.default_realtime_model || "gpt-realtime-mini");
      setTranscribeModel(payload.default_transcribe_model || "gpt-4o-mini-transcribe");
      appendEvent("status", `openai=${payload.openai_configured} deepgram=${payload.deepgram_configured}`);
    } catch (e) {
      setError(String(e));
    }
  }

  function appendEvent(type: string, detail = "") {
    setEvents((current) => [
      { id: crypto.randomUUID(), ts: nowLabel(), type, detail },
      ...current,
    ].slice(0, 120));
  }

  async function ensureMic() {
    if (micStreamRef.current) return micStreamRef.current;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone capture is not available in this browser.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    micStreamRef.current = stream;
    appendEvent("mic.opened");
    return stream;
  }

  async function startAll() {
    setError("");
    setCandidatePartial("");
    setCandidateFinal("");
    try {
      const stream = await ensureMic();
      setRunning(true);
      if (enableDeepgram) await startDeepgram(stream);
      if (enableRealtime) await startRealtime(stream);
    } catch (e) {
      setError(String(e));
      appendEvent("start.failed", String(e));
      stopAll();
    }
  }

  function stopAll() {
    stopRealtime();
    stopDeepgram();
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    setRunning(false);
    appendEvent("stopped");
  }

  async function startDeepgram(stream: MediaStream) {
    if (deepgramRunning || dgConnectionRef.current) return;
    if (!status?.deepgram_configured) throw new Error("Deepgram is not configured on the backend.");

    const { token } = await fetch(`${API}/deepgram_token`).then((r) => r.json());
    const dg = createClient(token);
    const connection = dg.listen.live({
      model: "nova-3",
      language: "en",
      encoding: "linear16",
      sample_rate: 16000,
      channels: 1,
      interim_results: true,
      vad_events: true,
      endpointing: 1500,
      utterance_end_ms: 2800,
      smart_format: true,
      punctuate: true,
    });
    dgConnectionRef.current = connection;

    await new Promise<void>((resolve, reject) => {
      connection.on(LiveTranscriptionEvents.Open, () => resolve());
      connection.on(LiveTranscriptionEvents.Error, (e: unknown) => reject(e));
      setTimeout(() => reject(new Error("Deepgram connection timeout")), 8000);
    });

    connection.on(LiveTranscriptionEvents.Transcript, (data: any) => {
      const text = String(data?.channel?.alternatives?.[0]?.transcript || "").trim();
      if (!text) return;
      const isFinal = Boolean(data?.is_final || data?.speech_final);
      if (isFinal) {
        setDeepgramFinal(text);
        setCandidateFinal(text);
        appendEvent("deepgram.final", text);
      } else {
        setDeepgramPartial(text);
        setCandidatePartial(text);
      }
      void postVoiceEvent("deepgram", isFinal ? "transcript_final" : "transcript_delta", text, isFinal);
    });
    connection.on(LiveTranscriptionEvents.UtteranceEnd, () => appendEvent("deepgram.utterance_end"));
    connection.on(LiveTranscriptionEvents.SpeechStarted, () => appendEvent("deepgram.speech_started"));
    connection.on(LiveTranscriptionEvents.Error, (e: unknown) => appendEvent("deepgram.error", String(e)));

    const audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event) => {
      if (!dgConnectionRef.current) return;
      const pcm16 = float32ToPcm16(event.inputBuffer.getChannelData(0));
      dgConnectionRef.current.send(pcm16);
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    audioContextRef.current = audioContext;
    processorRef.current = processor;
    setDeepgramRunning(true);
    appendEvent("deepgram.open");
  }

  function stopDeepgram() {
    processorRef.current?.disconnect();
    processorRef.current = null;
    audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
    dgConnectionRef.current?.finish?.();
    dgConnectionRef.current = null;
    setDeepgramRunning(false);
  }

  async function startRealtime(stream: MediaStream) {
    if (realtimeRunning || peerRef.current) return;
    if (!status?.openai_configured) throw new Error("OpenAI is not configured on the backend.");

    const peer = new RTCPeerConnection();
    const dc = peer.createDataChannel("oai-events");
    peerRef.current = peer;
    dataChannelRef.current = dc;

    peer.ontrack = (event) => {
      const [remoteStream] = event.streams;
      if (remoteAudioRef.current && remoteStream) {
        remoteAudioRef.current.srcObject = remoteStream;
        remoteAudioRef.current.play().catch(() => undefined);
      }
    };
    peer.onconnectionstatechange = () => {
      appendEvent("realtime.connection", peer.connectionState);
      if (peer.connectionState === "connected") {
        setRealtimeRunning(true);
      }
      if (peer.connectionState === "failed" || peer.connectionState === "disconnected") {
        setRealtimeRunning(false);
      }
    };
    dc.onopen = () => {
      appendEvent("realtime.data_channel_open", realtimeModel);
      sendRealtimeInstruction(
        "Say one short greeting, then ask: Walk me through a technical decision you made recently, and what tradeoff you were protecting.",
      );
    };
    dc.onmessage = (event) => {
      handleRealtimeEvent(event.data);
    };
    dc.onerror = () => appendEvent("realtime.data_channel_error");
    dc.onclose = () => appendEvent("realtime.data_channel_closed");

    stream.getAudioTracks().forEach((track) => peer.addTrack(track, stream));
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    const res = await fetch(`${API}/voice/openai/realtime_offer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        sdp: offer.sdp || "",
        model: realtimeModel,
        voice: "marin",
        vad_mode: "semantic_vad",
        vad_eagerness: "low",
      }),
    });
    const answerSdp = await res.text();
    if (!res.ok) throw new Error(answerSdp);
    await peer.setRemoteDescription({ type: "answer", sdp: answerSdp });
    appendEvent("realtime.offer_answered", realtimeModel);
  }

  function stopRealtime() {
    dataChannelRef.current?.close();
    dataChannelRef.current = null;
    peerRef.current?.getSenders().forEach((sender) => sender.track?.stop());
    peerRef.current?.close();
    peerRef.current = null;
    if (remoteAudioRef.current) remoteAudioRef.current.srcObject = null;
    setRealtimeRunning(false);
  }

  function sendRealtimeInstruction(instructions: string) {
    const dc = dataChannelRef.current;
    if (!dc || dc.readyState !== "open") {
      appendEvent("realtime.not_open");
      return;
    }
    dc.send(JSON.stringify({ type: "response.create", response: { instructions } }));
    appendEvent("realtime.response_create", instructions);
  }

  function sendFunctionCallTest() {
    sendRealtimeInstruction(
      "Call the report_voice_lab_signal function with event_type 'manual_function_test', confidence 0.91, and notes 'data channel function call path is being tested'. After the tool result, say one short confirmation.",
    );
  }

  function handleRealtimeEvent(raw: string) {
    let message: any = null;
    try {
      message = JSON.parse(raw);
    } catch {
      appendEvent("realtime.raw", raw.slice(0, 180));
      return;
    }
    const type = String(message?.type || "realtime.event");
    if (!type.includes("delta")) appendEvent(type, shortJson(message));

    const inputDelta = message?.delta || message?.transcript || "";
    if (type === "conversation.item.input_audio_transcription.delta") {
      const text = String(inputDelta || "");
      setRealtimePartial((current) => `${current}${text}`);
      setCandidatePartial((current) => `${current}${text}`);
      return;
    }
    if (type === "conversation.item.input_audio_transcription.completed") {
      const text = String(message?.transcript || "").trim();
      setRealtimeFinal(text);
      setCandidateFinal(text);
      void postVoiceEvent("openai", "transcript_final", text, true, message?.item_id);
      return;
    }
    if (type === "response.audio_transcript.delta") {
      setAiTranscript((current) => `${current}${String(message?.delta || "")}`);
      return;
    }
    if (type === "response.output_item.done" && message?.item?.type === "function_call") {
      handleRealtimeFunctionCall(message.item);
    }
    if (type === "response.function_call_arguments.done") {
      handleRealtimeFunctionCall(message);
    }
  }

  function handleRealtimeFunctionCall(item: any) {
    const callId = String(item?.call_id || "");
    const name = String(item?.name || "");
    if (!callId || name !== "report_voice_lab_signal") return;
    let args: Record<string, unknown> = {};
    try {
      args = JSON.parse(String(item?.arguments || "{}"));
    } catch {
      args = { raw_arguments: item?.arguments || "" };
    }
    setFunctionCalls((count) => count + 1);
    appendEvent("function_call.received", shortJson(args));
    const dc = dataChannelRef.current;
    if (!dc || dc.readyState !== "open") return;
    dc.send(JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: callId,
        output: JSON.stringify({
          ok: true,
          received_at: new Date().toISOString(),
          lab_session_id: sessionId,
          args,
        }),
      },
    }));
    dc.send(JSON.stringify({
      type: "response.create",
      response: { instructions: "Acknowledge the function-call result in one sentence." },
    }));
    appendEvent("function_call.output_sent", callId);
  }

  async function postVoiceEvent(provider: string, eventType: string, transcript: string, isFinal: boolean, itemId = "") {
    await fetch(`${API}/voice/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        event_type: eventType,
        provider,
        turn_id: "voice-lab-turn",
        item_id: itemId,
        transcript,
        is_final: isFinal,
        snapshot_seq: provider === "deepgram" ? ++deepgramSeqRef.current : ++realtimeSeqRef.current,
      }),
    }).catch(() => undefined);
  }

  async function captureOpenAiTranscribeSample() {
    setError("");
    setRecordingSample(true);
    try {
      const stream = await ensureMic();
      const recorder = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      const stopped = new Promise<Blob>((resolve) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
      });
      recorder.start();
      appendEvent("openai_transcribe.recording", "8 seconds");
      setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop();
      }, 8000);
      const blob = await stopped;
      const res = await fetch(
        `${API}/voice/openai/transcribe_audio/${encodeURIComponent(sessionId)}?model=${encodeURIComponent(transcribeModel)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": blob.type || "audio/webm",
            "X-Content-Type": blob.type || "audio/webm",
            "X-Filename": "voice-lab-sample.webm",
          },
          body: blob,
        },
      );
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `OpenAI transcription failed (${res.status})`);
      const text = String(payload?.transcript || "");
      setOpenaiTranscribeText(text);
      appendEvent("openai_transcribe.final", text);
    } catch (e) {
      setError(String(e));
      appendEvent("openai_transcribe.failed", String(e));
    } finally {
      setRecordingSample(false);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--ag-bg)] px-5 py-6 text-[var(--ag-text-0)] md:px-8">
      <audio ref={remoteAudioRef} autoPlay playsInline />
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <header className="flex flex-col gap-4 border-b border-[var(--ag-border)] pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-[var(--ag-blue)]">Antigravity</p>
            <h1 className="mt-2 text-3xl font-semibold">Voice Lab</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--ag-text-2)]">
              Isolated mic fan-out for OpenAI Realtime, OpenAI transcription, and Deepgram live partials.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="rounded-lg bg-[var(--ag-blue)] px-4 py-2 text-sm font-semibold text-white" onClick={running ? stopAll : startAll}>
              {running ? "Stop" : "Start Lab"}
            </button>
            <button className="rounded-lg border border-[var(--ag-border)] px-4 py-2 text-sm text-[var(--ag-text-1)]" onClick={refreshStatus}>
              Refresh
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-lg border border-[var(--ag-red)] bg-red-950/30 px-4 py-3 text-sm text-red-100">
            {error}
          </div>
        )}

        <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg border border-[var(--ag-border)] bg-[var(--ag-surface-0)] p-4">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--ag-text-2)]">Controls</h2>
            <div className="mt-4 grid gap-3">
              <label className="grid gap-1 text-sm">
                <span className="text-[var(--ag-text-2)]">Session</span>
                <input className="rounded-lg border border-[var(--ag-border)] bg-black/20 px-3 py-2 font-mono text-xs outline-none" value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-[var(--ag-text-2)]">Realtime model</span>
                <select className="rounded-lg border border-[var(--ag-border)] bg-black/20 px-3 py-2 outline-none" value={realtimeModel} onChange={(e) => setRealtimeModel(e.target.value)}>
                  {(status?.realtime_models || ["gpt-realtime-mini", "gpt-realtime"]).map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-[var(--ag-text-2)]">OpenAI transcribe model</span>
                <select className="rounded-lg border border-[var(--ag-border)] bg-black/20 px-3 py-2 outline-none" value={transcribeModel} onChange={(e) => setTranscribeModel(e.target.value)}>
                  {(status?.transcribe_models || ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"]).map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              <div className="grid gap-2 text-sm">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={enableRealtime} onChange={(e) => setEnableRealtime(e.target.checked)} />
                  <span>Fan out to OpenAI Realtime</span>
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={enableDeepgram} onChange={(e) => setEnableDeepgram(e.target.checked)} />
                  <span>Fan out to Deepgram live ASR</span>
                </label>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button className="rounded-lg border border-[var(--ag-border)] px-3 py-2 text-sm" onClick={() => sendRealtimeInstruction("Ask the candidate one concise product or engineering interview question.")}>
                  Ask Question
                </button>
                <button className="rounded-lg border border-[var(--ag-border)] px-3 py-2 text-sm" onClick={sendFunctionCallTest}>
                  Test Function
                </button>
                <button className="col-span-2 rounded-lg border border-[var(--ag-border)] px-3 py-2 text-sm" onClick={captureOpenAiTranscribeSample} disabled={recordingSample}>
                  {recordingSample ? "Recording 8s..." : "Capture GPT Transcribe Sample"}
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-[var(--ag-border)] bg-[var(--ag-surface-0)] p-4">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--ag-text-2)]">Status</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <StatusPill label="Mic" value={running ? "ON" : "IDLE"} active={running} />
              <StatusPill label="Realtime" value={realtimeRunning ? realtimeModel : "IDLE"} active={realtimeRunning} />
              <StatusPill label="Deepgram" value={deepgramRunning ? "LIVE" : "IDLE"} active={deepgramRunning} />
              <StatusPill label="Tools" value={`${functionCalls}`} active={functionCalls > 0} />
            </div>
            <div className="mt-4 rounded-lg border border-[var(--ag-border)] bg-black/20 p-3">
              <p className="font-mono text-xs uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Canonical candidate transcript</p>
              <p className="mt-2 min-h-16 text-sm leading-6 text-[var(--ag-text-1)]">{candidateConsensus || candidatePartial || "waiting"}</p>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <TranscriptPanel title="OpenAI Realtime Input" partial={realtimePartial} finalText={realtimeFinal} />
          <TranscriptPanel title="Deepgram Live Input" partial={deepgramPartial} finalText={deepgramFinal} />
          <TranscriptPanel title="OpenAI Batch Transcribe" partial={recordingSample ? "recording sample..." : ""} finalText={openaiTranscribeText} />
        </section>

        <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          <div className="rounded-lg border border-[var(--ag-border)] bg-[var(--ag-surface-0)] p-4">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--ag-text-2)]">AI spoken transcript</h2>
            <p className="mt-3 min-h-24 whitespace-pre-wrap text-sm leading-6 text-[var(--ag-text-1)]">{aiTranscript || "waiting"}</p>
          </div>
          <div className="rounded-lg border border-[var(--ag-border)] bg-[var(--ag-surface-0)] p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--ag-text-2)]">Event log</h2>
              <button className="rounded border border-[var(--ag-border)] px-2 py-1 text-xs" onClick={() => setEvents([])}>Clear</button>
            </div>
            <div className="mt-3 max-h-80 overflow-auto rounded-lg bg-black/20">
              {events.length === 0 ? (
                <p className="p-3 text-sm text-[var(--ag-text-3)]">waiting</p>
              ) : events.map((event) => (
                <div key={event.id} className="border-b border-[var(--ag-border)] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-[var(--ag-text-3)]">{event.ts}</span>
                    <span className="font-mono text-xs text-[var(--ag-blue)]">{event.type}</span>
                  </div>
                  {event.detail && <p className="mt-1 break-words text-xs leading-5 text-[var(--ag-text-2)]">{event.detail}</p>}
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function StatusPill({ label, value, active }: { label: string; value: string; active: boolean }) {
  return (
    <div className="rounded-lg border border-[var(--ag-border)] bg-black/20 px-3 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">{label}</p>
      <p className={active ? "mt-1 text-sm font-semibold text-[var(--ag-green)]" : "mt-1 text-sm font-semibold text-[var(--ag-text-2)]"}>{value}</p>
    </div>
  );
}

function TranscriptPanel({ title, partial, finalText }: { title: string; partial: string; finalText: string }) {
  return (
    <div className="rounded-lg border border-[var(--ag-border)] bg-[var(--ag-surface-0)] p-4">
      <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--ag-text-2)]">{title}</h2>
      <div className="mt-3 grid gap-3">
        <div className="rounded-lg border border-[var(--ag-border)] bg-black/20 p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Partial</p>
          <p className="mt-2 min-h-16 text-sm leading-6 text-[var(--ag-text-1)]">{partial || "waiting"}</p>
        </div>
        <div className="rounded-lg border border-[var(--ag-border)] bg-black/20 p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Final</p>
          <p className="mt-2 min-h-16 text-sm leading-6 text-[var(--ag-text-1)]">{finalText || "waiting"}</p>
        </div>
      </div>
    </div>
  );
}
