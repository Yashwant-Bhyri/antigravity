"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSurface } from "@/components/design-system";
import { AIOrb } from "@/components/Waveform";
import { getApiBaseUrl } from "@/lib/api";
import { playAudioUrl, prefetchAudio } from "@/lib/audio";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), { ssr: false });

type StageKey = "understanding" | "planning" | "implementation" | "validation" | "reflection";
type VoiceStatus = "off" | "connecting" | "live" | "error";

type VoiceConfig = {
  openai_realtime_configured: boolean;
  openai_realtime_model: string;
  gemini_live_configured: boolean;
  gemini_live_model: string;
  deepgram_configured: boolean;
  deepgram_simulation_model: string;
  tts: {
    provider: string;
    cartesia_configured: boolean;
    elevenlabs_configured: boolean;
    last_error: string;
  };
};

type GeminiLiveSession = {
  close: () => void;
  sendClientContent: (params: { turns: string; turnComplete: boolean }) => void;
  sendRealtimeInput: (params: { audio?: { data: string; mimeType: string }; audioStreamEnd?: boolean }) => void;
};

type AudioContextConstructor = typeof AudioContext;

type Stage = {
  key: StageKey;
  label: string;
  interviewer: string;
  candidate_task: string;
};

type TestDetail = {
  name: string;
  status: "pass" | "fail";
  visibility?: "public" | "hidden";
};

type TestResult = {
  passed: number;
  failed: number;
  total: number;
  public_passed?: number;
  public_total?: number;
  hidden_passed?: number;
  hidden_total?: number;
  details: TestDetail[];
  stdout: string;
  stderr: string;
  runtime_ms: number;
  timed_out: boolean;
};

type Twist = {
  id: string;
  title: string;
  body: string;
  interviewer_prompt: string;
};

type SimulationReport = {
  title: string;
  summary: string;
  overall_score: number;
  breakdown: Record<string, number>;
  strengths: string[];
  risks: string[];
  what_proved: string[];
  what_not_proved: string[];
  key_quotes: string[];
  unresolved: string[];
  hiring_signal: string;
  hiring_label: string;
  hiring_narrative: string;
  reasoning_signal?: {
    label: string;
    status: string;
    quality: number;
    shallow: boolean;
    summary: string;
  };
  overclaim_detected: boolean;
  twist_was_injected: boolean;
  event_timeline: Array<{ ts: string; text: string }>;
  test_result: TestResult;
};

type GateStatus = {
  issues_by_stage: Record<StageKey, string[]>;
  current_issues: string[];
  can_advance: boolean;
  can_run_tests: boolean;
  can_finalize: boolean;
  code_changed: boolean;
  evidence_label: string;
};

type SimulationState = {
  session_id: string;
  scenario: {
    title: string;
    role_signal: string;
    objective: string;
    constraints: string[];
    incident: string;
    twist?: Twist;
  };
  stages: Stage[];
  stage_requirements: Record<StageKey, string>;
  current_stage: StageKey;
  interviewer_message: string;
  starter_code: string;
  code: string;
  notes: Record<StageKey, string>;
  baseline_result: TestResult | null;
  test_result: TestResult | null;
  test_runs: TestResult[];
  telemetry: Array<{ at: number; event: string; detail: string }>;
  report: SimulationReport | null;
  complete: boolean;
  twist: Twist | null;
  twist_injected: boolean;
  gate_status: GateStatus;
};

const STAGE_KEYS: StageKey[] = ["understanding", "planning", "implementation", "validation", "reflection"];

const emptyNotes: Record<StageKey, string> = {
  understanding: "",
  planning: "",
  implementation: "",
  validation: "",
  reflection: "",
};

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(payload?.detail || `Request failed (${res.status})`);
  }
  return payload as T;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`);
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(payload?.detail || `Request failed (${res.status})`);
  }
  return payload as T;
}

async function postSdpOffer(path: string, body: unknown): Promise<string> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload?.detail || `Request failed (${res.status})`);
  }
  return res.text();
}

function cleanError(error: unknown) {
  return String(error instanceof Error ? error.message : error)
    .replace(/^Error:\s*/i, "")
    .trim();
}

function formatEventTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function statusPalette(status: "pass" | "fail") {
  return status === "pass"
    ? "border-[oklch(0.76_0.16_155_/_0.28)] bg-[oklch(0.76_0.16_155_/_0.08)] text-[var(--ag-green)]"
    : "border-[oklch(0.66_0.21_24_/_0.28)] bg-[oklch(0.66_0.21_24_/_0.08)] text-[var(--ag-red)]";
}

function metricLabel(key: string) {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function pcm16ToBase64(samples: Float32Array) {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return window.btoa(binary);
}

const AG_DARK_THEME = {
  base: "vs-dark" as const, inherit: true,
  rules: [
    { token: "keyword", foreground: "7c9ef5" },
    { token: "string", foreground: "98c87a" },
    { token: "comment", foreground: "4a5068", fontStyle: "italic" },
    { token: "number", foreground: "e5a663" },
  ],
  colors: {
    "editor.background": "#090b12", "editor.foreground": "#b8bdd4",
    "editor.lineHighlightBackground": "#ffffff07", "editor.selectionBackground": "#3c82f630",
    "editorLineNumber.foreground": "#2e3349", "editorLineNumber.activeForeground": "#555e7a",
    "editorIndentGuide.background1": "#1e2236", "editorCursor.foreground": "#7c9ef5",
    "editor.wordHighlightBackground": "#3c82f618",
  },
};

const EDITOR_OPTIONS = {
  fontSize: 13, lineHeight: 24, minimap: { enabled: false },
  scrollBeyondLastLine: false, wordWrap: "off" as const,
  fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Menlo', monospace",
  fontLigatures: true, renderLineHighlight: "line" as const,
  padding: { top: 20, bottom: 20 },
  scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 },
  overviewRulerLanes: 0, hideCursorInOverviewRuler: true,
  contextmenu: false, ariaLabel: "payment.mjs code editor",
  tabSize: 2, insertSpaces: true, detectIndentation: false,
};

export default function SimulationPage() {
  const [sim, setSim] = useState<SimulationState | null>(null);
  const [notes, setNotes] = useState<Record<StageKey, string>>(emptyNotes);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>("off");
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [voiceError, setVoiceError] = useState("");
  const [voiceEvents, setVoiceEvents] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const [recording, setRecording] = useState(false);
  const [showStdout, setShowStdout] = useState(false);
  const [geminiLive, setGeminiLive] = useState(false);
  const [geminiConnecting, setGeminiConnecting] = useState(false);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const geminiMicStreamRef = useRef<MediaStream | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const geminiSessionRef = useRef<GeminiLiveSession | null>(null);
  const geminiAudioContextRef = useRef<AudioContext | null>(null);
  const geminiInputAudioContextRef = useRef<AudioContext | null>(null);
  const geminiInputProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const geminiInputSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const geminiNextPlayTimeRef = useRef(0);

  const stageIndex = sim ? Math.max(0, STAGE_KEYS.indexOf(sim.current_stage)) : 0;
  const stage = sim?.stages.find((item) => item.key === sim.current_stage) ?? null;
  const testResult = sim?.test_result ?? null;
  const report = sim?.report ?? null;
  const gateStatus = sim?.gate_status ?? null;
  const currentNoteWords = useMemo(() => {
    if (!sim) return 0;
    return (notes[sim.current_stage] || "").trim().split(/\s+/).filter(Boolean).length;
  }, [notes, sim]);
  const codeChanged = useMemo(() => {
    if (!sim) return false;
    return code.replace(/\s+/g, "") !== sim.starter_code.replace(/\s+/g, "");
  }, [code, sim]);
  const canMoveNext = Boolean(sim && stageIndex < STAGE_KEYS.length - 1 && sim.current_stage !== "implementation");
  const canRunTests = Boolean(
    sim
      && ["implementation", "validation"].includes(sim.current_stage)
      && codeChanged
      && (notes.implementation || "").trim().split(/\s+/).filter(Boolean).length >= 12
      && (gateStatus?.issues_by_stage.understanding?.length ?? 0) === 0
      && (gateStatus?.issues_by_stage.planning?.length ?? 0) === 0,
  );
  const canFinalize = Boolean(sim && sim.current_stage === "reflection" && sim.test_result && codeChanged);
  const orbState = running ? "thinking" : testResult?.failed ? "thinking" : testResult?.passed === testResult?.total ? "speaking" : "idle";
  const assessmentNotes = useMemo(() => {
    const clean = error.trim();
    if (clean) return [clean];
    return (gateStatus?.current_issues ?? []).slice(0, 3);
  }, [error, gateStatus]);

  useEffect(() => {
    apiGet<VoiceConfig>("/simulation/voice_status")
      .then(setVoiceConfig)
      .catch(() => undefined);
    return () => {
      geminiSessionRef.current?.close();
      geminiAudioContextRef.current?.close().catch(() => undefined);
      geminiInputProcessorRef.current?.disconnect();
      geminiInputSourceRef.current?.disconnect();
      geminiInputAudioContextRef.current?.close().catch(() => undefined);
      geminiMicStreamRef.current?.getTracks().forEach((track) => track.stop());
      dataChannelRef.current?.close();
      peerRef.current?.close();
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    const handler = (event: Event) => {
      const nextCode = (event as CustomEvent<string>).detail;
      if (typeof nextCode === "string") setCode(nextCode);
    };
    window.addEventListener("antigravity:set-simulation-code", handler);
    return () => window.removeEventListener("antigravity:set-simulation-code", handler);
  }, []);

  function appendVoiceEvent(event: string) {
    setVoiceEvents((current) => [event, ...current].slice(0, 6));
  }

  function stopRealtimeVoice() {
    dataChannelRef.current?.close();
    peerRef.current?.close();
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    dataChannelRef.current = null;
    peerRef.current = null;
    micStreamRef.current = null;
    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = null;
    }
    setVoiceStatus("off");
  }

  function playGeminiPcm24k(base64Audio: string) {
    if (!base64Audio) return;
    const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext;
    if (!AudioContextCtor) throw new Error("Web Audio is not available in this browser.");
    const ctx = geminiAudioContextRef.current ?? new AudioContextCtor({ sampleRate: 24000 });
    geminiAudioContextRef.current = ctx;

    const binary = window.atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const view = new DataView(bytes.buffer);
    const sampleCount = Math.floor(bytes.byteLength / 2);
    const buffer = ctx.createBuffer(1, sampleCount, 24000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < sampleCount; i += 1) {
      channel[i] = Math.max(-1, Math.min(1, view.getInt16(i * 2, true) / 32768));
    }

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime + 0.02, geminiNextPlayTimeRef.current);
    source.start(startAt);
    geminiNextPlayTimeRef.current = startAt + buffer.duration;
  }

  function stopGeminiLive() {
    endGeminiTurn();
    geminiSessionRef.current?.close();
    geminiSessionRef.current = null;
    setGeminiConnecting(false);
    appendVoiceEvent("gemini.closed");
  }

  function endGeminiTurn() {
    geminiInputProcessorRef.current?.disconnect();
    geminiInputSourceRef.current?.disconnect();
    geminiInputAudioContextRef.current?.close().catch(() => undefined);
    geminiMicStreamRef.current?.getTracks().forEach((track) => track.stop());
    geminiInputProcessorRef.current = null;
    geminiInputSourceRef.current = null;
    geminiInputAudioContextRef.current = null;
    geminiMicStreamRef.current = null;
    try {
      geminiSessionRef.current?.sendRealtimeInput({ audioStreamEnd: true });
      appendVoiceEvent("gemini.turn.end");
    } catch {
      // Session may already be closed.
    }
    setGeminiLive(false);
  }

  async function startGeminiLiveMic() {
    if (!sim) return;
    setGeminiConnecting(true);
    setVoiceError("");
    appendVoiceEvent("gemini.connecting");
    try {
      const config = await apiGet<VoiceConfig>("/simulation/voice_status");
      setVoiceConfig(config);
      if (!config.gemini_live_configured) {
        throw new Error("GEMINI_API_KEY is not configured on the backend.");
      }
      const tokenPayload = await apiPost<{ token: string; model: string }>("/simulation/gemini_live_token/" + sim.session_id, {});
      const { GoogleGenAI, Modality } = await import("@google/genai");
      const ai = new GoogleGenAI({
        apiKey: tokenPayload.token,
        httpOptions: { apiVersion: "v1alpha" },
      });

      const responseQueue: unknown[] = [];
      const session = await ai.live.connect({
        model: tokenPayload.model,
        config: {
          responseModalities: [Modality.AUDIO],
          inputAudioTranscription: {},
          outputAudioTranscription: {},
        },
        callbacks: {
          onopen: () => appendVoiceEvent("gemini.open"),
          onmessage: (message: unknown) => {
            responseQueue.push(message);
            const msg = message as {
              data?: string;
              serverContent?: {
                modelTurn?: { parts?: Array<{ inlineData?: { data?: string }; text?: string }> };
                inputTranscription?: { text?: string };
                outputTranscription?: { text?: string };
                turnComplete?: boolean;
              };
            };
            const inlineAudio =
              msg.data ||
              msg.serverContent?.modelTurn?.parts?.find((part) => part.inlineData?.data)?.inlineData?.data ||
              "";
            if (inlineAudio) playGeminiPcm24k(inlineAudio);
            const inputTranscript = msg.serverContent?.inputTranscription?.text;
            if (inputTranscript) appendVoiceEvent(`heard: ${inputTranscript.slice(0, 42)}`);
            const transcript = msg.serverContent?.outputTranscription?.text;
            if (transcript) appendVoiceEvent(`gemini: ${transcript.slice(0, 42)}`);
          },
          onerror: (event: { message?: string; error?: unknown }) => {
            setVoiceError(`Gemini Live error: ${event.message || String(event.error || "unknown")}`);
            appendVoiceEvent("gemini.error");
          },
          onclose: () => {
            appendVoiceEvent("gemini.closed");
            setGeminiLive(false);
            setGeminiConnecting(false);
          },
        },
      });
      geminiSessionRef.current = session;

      const currentNote = notes[sim.current_stage] || "";
      const failingChecks = sim.test_result?.details.filter((d) => d.status === "fail").map((d) => d.name) ?? [];
      const testSummary = sim.test_result
        ? `${sim.test_result.passed}/${sim.test_result.total} checks passing (${sim.test_result.hidden_passed ?? 0}/${sim.test_result.hidden_total ?? 0} hidden)`
        : "Tests not run yet.";
      const gateIssues = gateStatus?.current_issues ?? [];
      const message = [
        "SYSTEM CONTEXT — private interviewer brief. Do not read this out.",
        `Simulation: Payment Retry Safety — ${sim.scenario.title}`,
        `Stage: ${sim.current_stage} (${stage?.label})`,
        `Interviewer written prompt: ${sim.interviewer_message}`,
        "",
        `Candidate worklog (this stage):\n${currentNote || "(empty — candidate has not written anything yet)"}`,
        "",
        `Validation: ${testSummary}`,
        failingChecks.length ? `Failing checks: ${failingChecks.join(", ")}` : "All visible checks passing.",
        sim.twist_injected
          ? "\nPRODUCTION TWIST ACTIVE: A charge.succeeded webhook arrived for a payment the candidate's code marked as 'failed' after a timeout. Two charges now exist for the same operation. Ask about this if the candidate hasn't addressed it."
          : "",
        gateIssues.length ? `\nCurrent stage gate issues (what the candidate still needs to demonstrate): ${gateIssues.join("; ")}` : "",
        "",
        "ROLE: You are the live interviewer. Speak one concise technical nudge or question. Do NOT reveal code. Do NOT say 'great job' vacuously. React to what you just heard from the candidate.",
      ].filter((s) => s !== undefined).join("\n");

      session.sendClientContent({ turns: message, turnComplete: false });

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone capture is not available in this browser.");
      }
      const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext;
      if (!AudioContextCtor) throw new Error("Web Audio is not available in this browser.");
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const inputContext = new AudioContextCtor();
      const source = inputContext.createMediaStreamSource(micStream);
      const processor = inputContext.createScriptProcessor(4096, 1, 1);
      const sampleRate = inputContext.sampleRate;
      let lastSent = 0;
      processor.onaudioprocess = (event) => {
        const now = performance.now();
        if (now - lastSent < 90) return;
        lastSent = now;
        const channel = event.inputBuffer.getChannelData(0);
        try {
          session.sendRealtimeInput({
            audio: {
              data: pcm16ToBase64(channel),
              mimeType: `audio/pcm;rate=${sampleRate}`,
            },
          });
        } catch (e) {
          setVoiceError(`Gemini mic stream failed: ${String(e)}`);
        }
      };
      source.connect(processor);
      processor.connect(inputContext.destination);
      geminiMicStreamRef.current = micStream;
      geminiInputAudioContextRef.current = inputContext;
      geminiInputSourceRef.current = source;
      geminiInputProcessorRef.current = processor;
      setGeminiLive(true);
      appendVoiceEvent("gemini.listening");
      window.setTimeout(() => {
        if (responseQueue.length === 0) appendVoiceEvent("gemini.waiting");
      }, 2500);
    } catch (e) {
      stopGeminiLive();
      setVoiceError(String(e));
    } finally {
      setGeminiConnecting(false);
    }
  }

  async function startAudioRecording() {
    if (!sim) return;
    setVoiceError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        throw new Error("Browser audio recording is not available here.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      micStreamRef.current = stream;
      recordedChunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordedChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(recordedChunksRef.current, { type });
        stream.getTracks().forEach((track) => track.stop());
        micStreamRef.current = null;
        void uploadAudioBlob(blob, type);
      };
      recorder.start();
      setRecording(true);
      appendVoiceEvent("recording.started");
    } catch (e) {
      setRecording(false);
      setVoiceError(String(e));
    }
  }

  function stopAudioRecording() {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
    setRecording(false);
    appendVoiceEvent("recording.stopped");
  }

  async function startRealtimeVoice() {
    if (!sim) return;
    setVoiceStatus("connecting");
    setVoiceError("");
    try {
      const config = await apiGet<VoiceConfig>("/simulation/voice_status");
      setVoiceConfig(config);
      if (!config.openai_realtime_configured) {
        throw new Error("OPENAI_API_KEY is not configured on the backend. Add it to .env.local and restart uvicorn to enable the live realtime interviewer.");
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone capture is not available in this browser.");
      }

      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const peer = new RTCPeerConnection();
      const dataChannel = peer.createDataChannel("oai-events");

      peerRef.current = peer;
      micStreamRef.current = micStream;
      dataChannelRef.current = dataChannel;

      peer.ontrack = (event) => {
        const [remoteStream] = event.streams;
        if (remoteAudioRef.current && remoteStream) {
          remoteAudioRef.current.srcObject = remoteStream;
          remoteAudioRef.current.play().catch(() => undefined);
        }
      };

      peer.onconnectionstatechange = () => {
        appendVoiceEvent(`connection.${peer.connectionState}`);
        if (peer.connectionState === "connected") setVoiceStatus("live");
        if (peer.connectionState === "failed" || peer.connectionState === "disconnected") {
          setVoiceStatus("error");
          setVoiceError("Realtime voice disconnected. The typed workbench is still available.");
        }
      };

      dataChannel.onopen = () => {
        appendVoiceEvent("voice.connected");
        dataChannel.send(
          JSON.stringify({
            type: "response.create",
            response: {
              instructions:
                "Greet the candidate in one sentence, then ask what they are inspecting in the payment retry handler right now.",
            },
          }),
        );
      };
      dataChannel.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message?.type) appendVoiceEvent(message.type);
        } catch {
          appendVoiceEvent("voice.event");
        }
      };

      micStream.getTracks().forEach((track) => peer.addTrack(track, micStream));
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const answerSdp = await postSdpOffer("/simulation/realtime_offer", {
        session_id: sim.session_id,
        stage_key: sim.current_stage,
        sdp: offer.sdp ?? "",
        voice: "marin",
      });
      await peer.setRemoteDescription({ type: "answer", sdp: answerSdp });
    } catch (e) {
      stopRealtimeVoice();
      setVoiceStatus("error");
      setVoiceError(String(e));
    }
  }

  async function uploadAudioNote(file: File | null) {
    if (!sim || !file) return;
    await uploadAudioBlob(file, file.type || "application/octet-stream", file.name);
  }

  async function uploadAudioBlob(blob: Blob, mediaType: string, filename = "recorded-note.webm") {
    if (!sim) return;
    setTranscribing(true);
    setError("");
    try {
      const res = await fetch(`${getApiBaseUrl()}/simulation/transcribe_audio/${sim.session_id}`, {
        method: "POST",
        headers: {
          "Content-Type": mediaType || "application/octet-stream",
          "X-Content-Type": mediaType || "application/octet-stream",
          "X-Filename": filename,
        },
        body: blob,
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `Audio transcription failed (${res.status})`);
      const transcript = String(payload?.transcript || "").trim();
      if (!transcript) throw new Error("No transcript was detected in that audio file.");
      const model = String(payload?.model || "deepgram");
      setNotes((current) => {
        const currentNote = current[sim.current_stage] || "";
        const prefix = currentNote.trim() ? `${currentNote.trim()}\n\n` : "";
        return { ...current, [sim.current_stage]: `${prefix}[audio note · ${model}] ${transcript}` };
      });
      appendVoiceEvent(`transcribed.${model}`);
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setTranscribing(false);
    }
  }

  async function startSimulation() {
    setLoading(true);
    setError("");
    try {
      const started = await apiPost<SimulationState>("/simulation/start", {});
      setSim(started);
      setNotes(started.notes ?? emptyNotes);
      setCode(started.code);
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setLoading(false);
    }
  }

  async function moveStage(nextStage: StageKey) {
    if (!sim) return;
    setError("");
    try {
      const updated = await apiPost<SimulationState>("/simulation/interviewer_turn", {
        session_id: sim.session_id,
        stage_key: nextStage,
        code,
        notes,
      });
      setSim(updated);
      setNotes(updated.notes ?? notes);
      setCode(updated.code);
      if (dataChannelRef.current?.readyState === "open") {
        dataChannelRef.current.send(
          JSON.stringify({
            type: "response.create",
            response: {
              instructions: `The candidate moved to the ${nextStage} stage. Ask one concise, stage-appropriate question without revealing the solution.`,
            },
          }),
        );
      }
    } catch (e) {
      setError(cleanError(e));
    }
  }

  async function speakInterviewer() {
    if (!sim?.interviewer_message) return;
    setSpeaking(true);
    setVoiceError("");
    const controller = new AbortController();
    const maxSpeakMs = Math.min(10_000, Math.max(3500, sim.interviewer_message.length * 45));
    const timeout = window.setTimeout(() => controller.abort(), maxSpeakMs);
    try {
      const url = await prefetchAudio(sim.interviewer_message, sim.session_id);
      await playAudioUrl(url, sim.interviewer_message, controller.signal);
    } catch (e) {
      setVoiceError(`Prompt audio unavailable: ${String(e).replace(/^Error:\s*/, "")}`);
    } finally {
      window.clearTimeout(timeout);
      setSpeaking(false);
    }
  }

  async function runTests() {
    if (!sim) return;
    setRunning(true);
    setError("");
    try {
      const updated = await apiPost<SimulationState>("/simulation/run_tests", {
        session_id: sim.session_id,
        code,
        notes,
      });
      setSim(updated);
      setNotes(updated.notes ?? notes);
      setCode(updated.code);
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setRunning(false);
    }
  }

  async function finalize() {
    if (!sim) return;
    setRunning(true);
    setError("");
    try {
      const updated = await apiPost<SimulationState>("/simulation/finalize", {
        session_id: sim.session_id,
        code,
        notes,
      });
      setSim(updated);
      setNotes(updated.notes ?? notes);
      setCode(updated.code);
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setRunning(false);
    }
  }

  function updateNote(value: string) {
    if (!sim) return;
    setNotes((current) => ({ ...current, [sim.current_stage]: value }));
  }

  return (
    <main className="ag-shell min-h-screen px-4 py-5 text-[var(--ag-text-0)] md:px-6">
      <div className="relative z-10 mx-auto flex w-full max-w-[1680px] flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <AGLogo />
          <div className="flex flex-wrap items-center gap-2">
            <AGChip active>Engineering Simulation</AGChip>
            <AGChip>10 Runtime Checks</AGChip>
            <AGChip>Hidden Safety Suite</AGChip>
            {sim?.complete && sim.report && (
              <a
                href={`/simulation/report/${sim.session_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-xl border border-[var(--ag-border)] px-3 py-2 text-sm text-[var(--ag-text-1)] transition hover:border-[var(--ag-border-strong)]"
              >
                📎 Share Report
              </a>
            )}
            <AGButton variant="secondary" href="/simulation/admin">Admin</AGButton>
          </div>
        </header>

        {!sim ? (
          <section className="grid min-h-[calc(100vh-6.5rem)] gap-5 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="flex flex-col justify-center gap-5">
              <div className="space-y-4">
                <AGSectionLabel>Simulation V1</AGSectionLabel>
                <h1 className="max-w-3xl text-5xl font-semibold leading-[1.02] tracking-[-0.055em] md:text-7xl">
                  Payment reliability, tested under real failure pressure.
                </h1>
                <p className="max-w-2xl text-base leading-8 text-[var(--ag-text-2)]">
                  A backend engineering case where the candidate reads an incident, states invariants,
                  edits the handler, runs public and hidden tests, and defends the production tradeoffs.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <AGButton onClick={startSimulation} disabled={loading}>
                  {loading ? "Starting..." : "Start Simulation"}
                </AGButton>
                <AGButton variant="secondary" href="/simulation/inventory">
                  Inventory Race →
                </AGButton>
                <AGButton variant="secondary" href="/">
                  Back to Antigravity
                </AGButton>
              </div>
              {error && <p className="text-sm text-[var(--ag-red)]">{error}</p>}
            </div>
            <AGSurface className="flex min-h-[520px] items-center justify-center px-6 py-6">
              <div className="relative flex w-full max-w-xl flex-col items-center gap-6 text-center">
                <AIOrb state="speaking" />
                <div>
                  <AGSectionLabel>Interviewer Presence</AGSectionLabel>
                  <p className="mt-3 text-xl leading-8 text-[var(--ag-text-1)]">
                    “I’m going to watch how you reason through the incident. Show the invariant, patch the
                    unsafe path, then prove it survives retries, conflicts, failures, and races.”
                  </p>
                </div>
              </div>
            </AGSurface>
          </section>
        ) : (
          <section className="flex min-h-[calc(100vh-6rem)] overflow-hidden rounded-2xl border border-[var(--ag-border)]">

            {/* ── Interview Channel (left) ─────────────────────────── */}
            <div className="flex w-[360px] shrink-0 flex-col border-r border-[var(--ag-border)] bg-[var(--ag-surface-0)]">

              {/* Interviewer presence */}
              <div className="border-b border-[var(--ag-border)] px-5 py-5">
                <div className="flex items-start gap-3">
                  <AIOrb state={orbState} />
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">
                      Assessment Lead · {stage?.label ?? sim.current_stage}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[var(--ag-text-0)]">{sim.interviewer_message}</p>
                  </div>
                </div>
                {stage && (
                  <p className="mt-3 text-xs leading-5 text-[var(--ag-text-2)]">{stage.candidate_task}</p>
                )}
              </div>

              {/* Stage rail — compact pills */}
              <div className="flex items-center gap-1 border-b border-[var(--ag-border)] px-5 py-3">
                {sim.stages.map((item, index) => {
                  const active = item.key === sim.current_stage;
                  const done = index < stageIndex;
                  const locked = index > stageIndex;
                  const stageIssues = gateStatus?.issues_by_stage[item.key as StageKey] ?? [];
                  const gatePass = done && !stageIssues.length;
                  return (
                    <button
                      key={item.key}
                      disabled={locked}
                      onClick={() => moveStage(item.key)}
                      title={`${item.label}${stageIssues.length ? ": " + stageIssues.join(" ") : ""}`}
                      className={`flex h-8 flex-1 items-center justify-center rounded-lg border text-[10px] font-mono transition ${
                        active
                          ? "border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-[var(--ag-text-0)]"
                          : gatePass
                            ? "border-[oklch(0.76_0.16_155_/_0.25)] bg-[oklch(0.76_0.16_155_/_0.06)] text-[var(--ag-green)]"
                            : done
                              ? "border-[oklch(0.85_0.17_85_/_0.25)] bg-[oklch(0.85_0.17_85_/_0.05)] text-[oklch(0.85_0.17_85)]"
                              : "cursor-not-allowed border-[var(--ag-border)] text-[var(--ag-text-3)] opacity-40"
                      }`}
                    >
                      {gatePass ? "✓" : `0${index + 1}`}
                    </button>
                  );
                })}
              </div>

              {/* Required artifact + gate */}
              <div className="border-b border-[var(--ag-border)] px-5 py-4">
                <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Required Artifact</p>
                <p className="mt-2 text-xs leading-5 text-[var(--ag-text-2)]">{sim.stage_requirements?.[sim.current_stage]}</p>
                {assessmentNotes.length > 0 ? (
                  <div className="mt-2 space-y-1">
                    {assessmentNotes.map((issue) => (
                      <p key={issue} className="text-xs leading-5 text-[var(--ag-amber)]">↳ {issue}</p>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-[var(--ag-green)]">Gate satisfied ✓</p>
                )}
              </div>

              {/* Worklog — flex-grows */}
              <div className="flex flex-1 flex-col px-5 py-5">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Candidate Worklog</p>
                  <div className="flex gap-3 font-mono text-[10px] text-[var(--ag-text-3)]">
                    <span>runs.{sim.test_runs.length}</span>
                    <span>{currentNoteWords}w</span>
                  </div>
                </div>
                <textarea
                  aria-label={`${stage?.label ?? "Candidate"} worklog`}
                  value={notes[sim.current_stage] ?? ""}
                  onChange={(event) => updateNote(event.target.value)}
                  placeholder="Think out loud — reasoning here is scored alongside your code."
                  className="mt-3 flex-1 resize-none bg-transparent text-sm leading-7 text-[var(--ag-text-0)] outline-none placeholder:text-[var(--ag-text-3)] focus:outline-none"
                />
                {report?.overclaim_detected && (
                  <p className="mt-2 text-xs text-[oklch(0.75_0.18_40)]">⚠ Overclaiming detected in candidate notes.</p>
                )}
              </div>

              {/* Telemetry — compact at bottom */}
              {sim.telemetry.length > 0 && (
                <div className="ag-scrollbar max-h-[120px] overflow-y-auto border-t border-[var(--ag-border)] px-5 py-3">
                  {sim.telemetry.slice(-4).map((event) => (
                    <div key={`${event.at}-${event.event}`} className="flex gap-2 py-0.5">
                      <span className="shrink-0 font-mono text-[9px] text-[var(--ag-text-3)]">{formatEventTime(event.at)}</span>
                      <span className="text-[10px] leading-4 text-[var(--ag-text-3)]">{event.detail}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Nav */}
              <div className="flex items-center gap-2 border-t border-[var(--ag-border)] px-5 py-4">
                <AGButton
                  variant="secondary"
                  disabled={stageIndex === 0}
                  onClick={() => moveStage(STAGE_KEYS[Math.max(0, stageIndex - 1)])}
                >
                  Back
                </AGButton>
                {!sim.complete && (
                  <AGButton
                    disabled={!canMoveNext}
                    onClick={() => moveStage(STAGE_KEYS[Math.min(STAGE_KEYS.length - 1, stageIndex + 1)])}
                  >
                    Next Stage
                  </AGButton>
                )}
                {error && <p className="ml-1 truncate text-xs text-[var(--ag-red)]">{error}</p>}
              </div>
            </div>

            {/* ── Technical Workspace (right) ──────────────────────── */}
            <div className="flex flex-1 flex-col min-h-0 overflow-hidden">

              {/* Workspace header */}
              <div className="flex items-center gap-3 border-b border-[var(--ag-border)] px-6 py-3">
                <h1 className="truncate text-sm font-semibold tracking-[-0.02em]">{sim.scenario.title}</h1>
                <span className="shrink-0 rounded-full border border-[var(--ag-border)] px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--ag-text-3)]">
                  {gateStatus?.evidence_label ?? "Evidence incomplete"}
                </span>
                {sim.twist_injected && (
                  <span className="shrink-0 rounded-md border border-[oklch(0.75_0.18_40_/_0.3)] bg-[oklch(0.75_0.18_40_/_0.07)] px-2 py-0.5 font-mono text-[10px] text-[oklch(0.75_0.18_40)]">
                    Production twist active
                  </span>
                )}
                <div className="ml-auto flex shrink-0 items-center gap-2">
                  {testResult?.stdout && (
                    <AGButton variant="secondary" onClick={() => setShowStdout((v) => !v)}>
                      {showStdout ? "Hide Output" : "Show Output"}
                    </AGButton>
                  )}
                  <AGButton variant="secondary" disabled={running || !canRunTests} onClick={runTests}>
                    {running ? "Running..." : "Run Tests"}
                  </AGButton>
                  <AGButton disabled={running || !canFinalize} onClick={finalize}>
                    Finalize
                  </AGButton>
                </div>
              </div>

              {/* Stage-adaptive content */}
              {sim.complete && report ? (

                /* ── COMPLETE: Inline report ── */
                <div className="ag-scrollbar flex-1 overflow-y-auto px-8 py-8">
                  <div className="max-w-2xl space-y-6">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Final Report</p>
                    </div>
                    <div className="flex items-end gap-4">
                      <p className="font-mono text-7xl font-semibold tracking-[-0.07em]">{report.overall_score}</p>
                      <div className="pb-2">
                        <div className={`inline-block rounded-lg border px-3 py-1.5 text-xs font-semibold tracking-wide ${
                          report.hiring_signal === "strong_hire"
                            ? "border-[oklch(0.76_0.16_155_/_0.35)] bg-[oklch(0.76_0.16_155_/_0.12)] text-[var(--ag-green)]"
                            : report.hiring_signal === "hire_with_followup"
                              ? "border-[oklch(0.8_0.15_200_/_0.3)] bg-[oklch(0.8_0.15_200_/_0.08)] text-[oklch(0.75_0.15_200)]"
                              : report.hiring_signal === "no_hire" || report.hiring_signal === "weak"
                                ? "border-[oklch(0.66_0.21_24_/_0.3)] bg-[oklch(0.66_0.21_24_/_0.08)] text-[var(--ag-red)]"
                                : "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-2)]"
                        }`}>
                          {report.hiring_label ?? report.hiring_signal}
                        </div>
                        <p className="mt-1 text-xs text-[var(--ag-text-3)]">final score · Assessment Report</p>
                      </div>
                    </div>
                    <p className="text-sm leading-7 text-[var(--ag-text-2)]">{report.summary}</p>
                    {report.reasoning_signal && (
                      <div className={`rounded-xl border px-4 py-3 ${
                        report.reasoning_signal.shallow
                          ? "border-[oklch(0.75_0.18_40_/_0.32)] bg-[oklch(0.75_0.18_40_/_0.08)]"
                          : "border-[oklch(0.76_0.16_155_/_0.28)] bg-[oklch(0.76_0.16_155_/_0.07)]"
                      }`}>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">
                          Reasoning Quality / Authorship Signal
                        </p>
                        <div className="mt-2 flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-[var(--ag-text-0)]">{report.reasoning_signal.status}</p>
                          <span className="font-mono text-xs text-[var(--ag-text-2)]">{report.reasoning_signal.quality}/100</span>
                        </div>
                        <p className="mt-2 text-xs leading-5 text-[var(--ag-text-2)]">{report.reasoning_signal.summary}</p>
                      </div>
                    )}
                    <div className="space-y-3">
                      {Object.entries(report.breakdown).map(([key, value]) => (
                        <div key={key}>
                          <div className="flex justify-between text-xs text-[var(--ag-text-2)]">
                            <span>{metricLabel(key)}</span>
                            <span>{value}</span>
                          </div>
                          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
                            <div className="h-full rounded-full bg-[var(--ag-blue)]" style={{ width: `${value}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                    {report.what_proved?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-green)]">What Was Proved</p>
                        <ul className="mt-2 space-y-1.5">
                          {report.what_proved.map((item) => (
                            <li key={item} className="flex gap-2 text-xs leading-5 text-[var(--ag-text-2)]">
                              <span className="mt-0.5 text-[var(--ag-green)]">✓</span>{item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.what_not_proved?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-red)]">What Remains Unproven</p>
                        <ul className="mt-2 space-y-1.5">
                          {report.what_not_proved.map((item) => (
                            <li key={item} className="flex gap-2 text-xs leading-5 text-[var(--ag-text-2)]">
                              <span className="mt-0.5 text-[var(--ag-red)]">○</span>{item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.key_quotes?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Candidate Quotes</p>
                        <div className="mt-2 space-y-2">
                          {report.key_quotes.map((quote) => (
                            <blockquote key={quote} className="border-l-2 border-[var(--ag-border-strong)] pl-3 text-xs italic leading-5 text-[var(--ag-text-2)]">
                              {quote}
                            </blockquote>
                          ))}
                        </div>
                      </div>
                    )}
                    {report.event_timeline?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Session Timeline</p>
                        <div className="mt-2 space-y-2">
                          {report.event_timeline.map((entry, i) => (
                            <div key={i} className="flex gap-3 border-l border-[var(--ag-border)] pl-3">
                              <span className="shrink-0 font-mono text-[10px] text-[var(--ag-text-3)]">{entry.ts}</span>
                              <span className="text-xs leading-5 text-[var(--ag-text-2)]">{entry.text}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {report.twist_was_injected && (
                      <p className="text-[10px] text-[oklch(0.75_0.18_40)]">↳ Production twist was injected during this session.</p>
                    )}
                  </div>
                </div>

              ) : sim.current_stage === "understanding" ? (

                /* ── UNDERSTANDING: Case brief reading view ── */
                <div className="ag-scrollbar flex-1 overflow-y-auto px-8 py-8">
                  <div className="max-w-2xl space-y-6">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Incident Brief</p>
                      <p className="mt-3 whitespace-pre-line text-base leading-8 text-[var(--ag-text-0)]">{sim.scenario.incident}</p>
                    </div>
                    <div className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4">
                      <p className="font-mono text-[10px] uppercase text-[var(--ag-text-3)]">Role Signal</p>
                      <p className="mt-2 text-sm leading-6 text-[var(--ag-text-1)]">{sim.scenario.role_signal}</p>
                    </div>
                    <div>
                      <p className="font-mono text-[10px] uppercase text-[var(--ag-text-3)]">Constraints</p>
                      <div className="mt-3 space-y-2">
                        {sim.scenario.constraints.map((c) => (
                          <div key={c} className="flex gap-3 text-sm leading-6 text-[var(--ag-text-2)]">
                            <span className="mt-0.5 shrink-0 text-[var(--ag-text-3)]">→</span>
                            <span>{c}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

              ) : sim.current_stage === "planning" ? (

                /* ── PLANNING: Constraints reference + code ── */
                <div className="flex flex-1 min-h-0">
                  <div className="ag-scrollbar w-[300px] shrink-0 overflow-y-auto border-r border-[var(--ag-border)] px-6 py-6">
                    <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Constraints</p>
                    <div className="mt-4 space-y-3">
                      {sim.scenario.constraints.map((c) => (
                        <div key={c} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-3 text-xs leading-5 text-[var(--ag-text-2)]">
                          {c}
                        </div>
                      ))}
                    </div>
                    <div className="mt-6">
                      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Objective</p>
                      <p className="mt-2 text-xs leading-5 text-[var(--ag-text-2)]">{sim.scenario.objective}</p>
                    </div>
                  </div>
                  <div className="flex flex-1 flex-col min-h-0">
                    <p className="border-b border-[var(--ag-border)] px-4 py-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">
                      payment.mjs · starter reference
                    </p>
                    <div className="min-h-0 flex-1">
                      <MonacoEditor
                        height="100%"
                        language="javascript"
                        value={code}
                        onChange={(value) => setCode(value ?? "")}
                        theme="ag-dark"
                        beforeMount={(monaco) => monaco.editor.defineTheme("ag-dark", AG_DARK_THEME)}
                        options={EDITOR_OPTIONS}
                      />
                    </div>
                  </div>
                </div>

              ) : (

                /* ── IMPLEMENTATION / VALIDATION / REFLECTION: Code-first ── */
                <div className="flex flex-1 flex-col min-h-0">
                  <div className="flex items-center border-b border-[var(--ag-border)] px-4 py-2">
                    <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">
                      payment.mjs · idempotency boundary
                    </p>
                  </div>
                  <div className="min-h-0 flex-1">
                    <MonacoEditor
                      height="100%"
                      language="javascript"
                      value={code}
                      onChange={(value) => setCode(value ?? "")}
                      theme="ag-dark"
                      beforeMount={(monaco) => monaco.editor.defineTheme("ag-dark", AG_DARK_THEME)}
                      options={EDITOR_OPTIONS}
                    />
                  </div>

                  {/* Test results — appears after Run Tests */}
                  {testResult && (
                    <div className="border-t border-[var(--ag-border)]">
                      <div className="flex items-center gap-4 px-5 py-3">
                        <p className="font-mono text-xs text-[var(--ag-text-2)]">
                          {testResult.passed}/{testResult.total} checks passing
                        </p>
                        <div className="flex gap-3 text-xs text-[var(--ag-text-3)]">
                          <span>public {testResult.public_passed ?? 0}/{testResult.public_total ?? 0}</span>
                          <span>hidden {testResult.hidden_passed ?? 0}/{testResult.hidden_total ?? 0}</span>
                          <span>{testResult.runtime_ms}ms</span>
                        </div>
                      </div>
                      <div className="ag-scrollbar max-h-52 overflow-y-auto px-5 pb-4">
                        <div className="grid gap-2 sm:grid-cols-2">
                          {testResult.details.map((detail) => (
                            <div key={detail.name} className={`rounded-xl border px-3 py-2.5 ${statusPalette(detail.status)}`}>
                              <div className="flex items-start justify-between gap-2">
                                <p className="text-xs leading-5 text-[var(--ag-text-1)]">{detail.name}</p>
                                <span className="shrink-0 font-mono text-[9px] uppercase opacity-70">
                                  {detail.visibility === "hidden" ? "hidden " : ""}{detail.status}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {showStdout && testResult?.stdout && (
                    <div className="max-h-44 overflow-y-auto border-t border-[var(--ag-border)] bg-[oklch(0.06_0.01_265)] px-5 py-4">
                      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">Test Runner Output</p>
                      <pre className="whitespace-pre-wrap font-mono text-[11px] leading-5 text-[var(--ag-text-2)]">{testResult.stdout}</pre>
                      {testResult.stderr && (
                        <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-5 text-[var(--ag-red)]">{testResult.stderr}</pre>
                      )}
                    </div>
                  )}

                  {/* Twist alert */}
                  {sim.twist_injected && sim.twist && (
                    <div className="border-t border-[oklch(0.75_0.18_40_/_0.35)] bg-[oklch(0.75_0.18_40_/_0.06)] px-5 py-4">
                      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[oklch(0.75_0.18_40)]">{sim.twist.title}</p>
                      <p className="mt-2 whitespace-pre-line text-sm leading-7 text-[var(--ag-text-1)]">{sim.twist.body}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
