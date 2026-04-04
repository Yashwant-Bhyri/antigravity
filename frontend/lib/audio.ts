import { createClient, LiveTranscriptionEvents } from "@deepgram/sdk";
import { CVSensor, VisionPrediction } from "./vision";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Deepgram browser-side ASR ────────────────────────────────────────────────

export enum FloorState {
  IDLE = "IDLE",
  USER_SPEAKING = "USER_SPEAKING",
  AI_THINKING = "AI_THINKING",
  AI_SPEAKING = "AI_SPEAKING",
}

const FLOOR_CONFIG = {
  bargeInVadMs: 250,
  bargeInMinChars: 8,
  silenceThresholdMs: 5000,
  ttsFadeOutMs: 100,
  // Vision Fusion Thresholds
  visionPredictionThreshold: 0.85, // score > 0.85 triggers early commit
  audioWeight: 0.3,
  lipClosureWeight: 0.4,
  gazeStabilityWeight: 0.3,
};

export class InterviewSession {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private dgConnection: ReturnType<ReturnType<typeof createClient>["listen"]["live"]> | null = null;
  private sessionId: string;

  // Multimodal Sensors
  private visionSensor: CVSensor | null = null;
  private videoElement: HTMLVideoElement | null = null;
  private lastSilenceStart: number = 0;
  private latestVision: VisionPrediction | null = null;
  private visionRafActive = false;

  // Utterance age gate — tracks when the first is_final landed for the current utterance
  private utteranceStartTime: number | null = null;

  // Floor Management
  public floor: FloorState = FloorState.IDLE;
  private currentAbortController: AbortController | null = null;

  // Barge-in VAD duration tracking
  private bargeInVadStart: number | null = null;

  // Utterance accumulation buffer.
  private utteranceBuffer: string[] = [];
  private utteranceFlushTimer: ReturnType<typeof setTimeout> | null = null;

  // NER entity buffer.
  private entityBuffer: Set<string> = new Set();

  onPartial: (text: string) => void = () => {};
  onFinal: (text: string, entities: string[]) => void = () => {};
  onBargeIn: () => void = () => {};
  onSilence: () => void = () => {};
  onFloorChange: (state: FloorState) => void = () => {};
  onError: (err: string) => void = () => {};

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  public transition(newState: FloorState) {
    if (this.floor === newState) return;
    this.floor = newState;
    this.onFloorChange(newState);
  }

  async start() {
    const { token } = await fetch(`${API}/deepgram_token`).then((r) => r.json());

    const dg = createClient(token);
    this.dgConnection = dg.listen.live({
      model: "nova-3",
      language: "en",
      encoding: "linear16",
      sample_rate: 16000,
      channels: 1,
      interim_results: true,
      vad_events: true,
      ner: true,
      endpointing: 1200,
      utterance_end_ms: 3000,
    });

    await new Promise<void>((resolve, reject) => {
      this.dgConnection!.on(LiveTranscriptionEvents.Open, () => resolve());
      this.dgConnection!.on(LiveTranscriptionEvents.Error, (e) => reject(e));
      setTimeout(() => reject(new Error("Deepgram connection timeout")), 8000);
    });

    this.transition(FloorState.USER_SPEAKING);

    // ── Transcript handler ────────────────────────────────────────────────────
    this.dgConnection.on(LiveTranscriptionEvents.Transcript, async (data) => {
      const text = data?.channel?.alternatives?.[0]?.transcript ?? "";
      
      // Update silence tracking
      if (text) {
        this.lastSilenceStart = performance.now();
      }

      // Barge-in Check (if AI is speaking)
      // Requires BOTH: sustained VAD for bargeInVadMs AND enough chars — prevents false triggers
      if (this.floor === FloorState.AI_SPEAKING) {
        if (text.length >= FLOOR_CONFIG.bargeInMinChars) {
          if (this.bargeInVadStart === null) {
            this.bargeInVadStart = performance.now();
          }
          const vadDuration = performance.now() - this.bargeInVadStart;
          if (vadDuration >= FLOOR_CONFIG.bargeInVadMs) {
            console.log(`[Audio] Barge-in confirmed (VAD: ${vadDuration.toFixed(0)}ms, chars: ${text.length})`);
            this.bargeInVadStart = null;
            this.currentAbortController?.abort();
            this.currentAbortController = null;
            this.transition(FloorState.USER_SPEAKING);
            this.onBargeIn();
            return;
          }
        } else {
          // Speech dropped below threshold — reset VAD timer
          this.bargeInVadStart = null;
        }
        return;
      }
      this.bargeInVadStart = null;

      if (data.is_final && text) {
        // Track when this utterance first started accumulating
        if (this.utteranceBuffer.length === 0) {
          this.utteranceStartTime = performance.now();
        }
        this.utteranceBuffer.push(text);

        const rawEntities: Array<{ label: string; value: string; confidence: number }> =
          data?.channel?.alternatives?.[0]?.entities ?? [];
        const newEntities = rawEntities
          .filter((e) => e.confidence >= 0.7)
          .map((e) => e.value.trim())
          .filter((v) => v.length > 1);
        newEntities.forEach((e) => this.entityBuffer.add(e));

        // Safety flush (forced — bypasses age gate)
        if (this.utteranceFlushTimer) clearTimeout(this.utteranceFlushTimer);
        this.utteranceFlushTimer = setTimeout(() => this._flushUtterance(true), 5000);

        const accumulated = this.utteranceBuffer.join(" ");
        this.onPartial(accumulated);

        // Fetch partial pre-fetch
        fetch(`${API}/partial_transcript`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: this.sessionId,
            transcript: accumulated,
            entities: [...this.entityBuffer],
          }),
        }).catch(() => {});

      } else if (text) {
        const accumulated = this.utteranceBuffer.join(" ");
        const display = accumulated ? `${accumulated} ${text}` : text;
        this.onPartial(display);
        
        if (this.floor === FloorState.IDLE || this.floor === FloorState.AI_THINKING) {
          this.transition(FloorState.USER_SPEAKING);
        }
      }

      // ─── Phase 2: Multimodal Signal Fusion ──────────────────────────────────
      // Vision can help us estimate turn-yield likelihood, but it must NOT directly
      // commit meaning. Direct CV-triggered flushes caused mid-thought fragments to
      // enter the LLM path while the user was still speaking.
      // Final meaning commit remains gated by Deepgram UtteranceEnd / safety flush.
      if (this.floor === FloorState.USER_SPEAKING && this.latestVision) {
        const vision = this.latestVision;
        const silenceMs = performance.now() - this.lastSilenceStart;
        const silenceSignal = Math.min(1, silenceMs / 2000);
        const score =
          (silenceSignal * FLOOR_CONFIG.audioWeight) +
          (vision.lipClosureScore * FLOOR_CONFIG.lipClosureWeight) +
          (vision.gazeStability * FLOOR_CONFIG.gazeStabilityWeight);

        if (score >= FLOOR_CONFIG.visionPredictionThreshold) {
          console.log(`[Vision] Turn likely ending (score: ${score.toFixed(2)}, silence: ${silenceMs}ms)`);
        }
      }
    });

    // ── UtteranceEnd ─────────────────────────────────────────────────────────
    // UtteranceEnd = Deepgram's VAD confirmed 3s of silence — always commit
    this.dgConnection.on(LiveTranscriptionEvents.UtteranceEnd, () => {
      if (this.utteranceFlushTimer) {
        clearTimeout(this.utteranceFlushTimer);
        this.utteranceFlushTimer = null;
      }
      this._flushUtterance(true);
    });

    this.dgConnection.on(LiveTranscriptionEvents.Error, (e) => {
      this.onError(String(e));
    });

    // Capture mic
    this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    const source = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.processor = this.audioContext.createScriptProcessor(2048, 1, 1);

    this.processor.onaudioprocess = (e) => {
      if (!this.dgConnection) return;
      const pcm16 = float32ToPcm16(e.inputBuffer.getChannelData(0));
      this.dgConnection.send(pcm16);
    };

    source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
  }

  public async startVision(video: HTMLVideoElement) {
    if (!this.visionSensor) {
      this.visionSensor = new CVSensor();
    }
    this.videoElement = video;
    this.visionRafActive = true;

    // RAF loop runs independently of transcript events — stores latest prediction
    // for synchronous reads in the transcript handler (no async await in hot path)
    const rafTick = () => {
      if (!this.visionRafActive || !this.visionSensor || !this.videoElement) return;
      this.visionSensor.getPrediction(this.videoElement)
        .then((pred) => {
          if (pred) this.latestVision = pred;
          if (this.visionRafActive) requestAnimationFrame(rafTick);
        })
        .catch(() => {
          if (this.visionRafActive) requestAnimationFrame(rafTick);
        });
    };
    requestAnimationFrame(rafTick);
    console.log("[Vision] AI Turn Prediction enabled via camera.");
  }

  private _flushUtterance(forced = false) {
    // Minimal age gate: block accidental sub-800ms flushes (e.g. CV noise on a single word).
    // CV fusion is the primary early-commit path — don't block it with a long gate.
    // Safety timer and UtteranceEnd bypass this via forced=true.
    if (!forced && this.utteranceStartTime !== null) {
      const elapsed = performance.now() - this.utteranceStartTime;
      if (elapsed < 800) return;
    }

    const fullText = this.utteranceBuffer.join(" ").trim();
    const entities = [...this.entityBuffer];
    this.utteranceBuffer = [];
    this.entityBuffer.clear();
    this.utteranceStartTime = null;

    // Reset silence tracker
    this.lastSilenceStart = performance.now();

    if (fullText) {
      this.transition(FloorState.AI_THINKING);
      this.onFinal(fullText, entities);
    } else if (this.floor === FloorState.USER_SPEAKING) {
      // If we got an UtteranceEnd but no text (silence), call onSilence
      this.onSilence();
    }
  }

  stop() {
    this.visionRafActive = false;
    this.latestVision = null;
    if (this.utteranceFlushTimer) {
      clearTimeout(this.utteranceFlushTimer);
      this.utteranceFlushTimer = null;
    }
    this.currentAbortController?.abort();
    this.currentAbortController = null;
    this.utteranceBuffer = [];
    this.utteranceStartTime = null;
    this.processor?.disconnect();
    this.mediaStream?.getTracks().forEach((t) => t.stop());
    if (this.audioContext && this.audioContext.state !== "closed") {
      this.audioContext.close();
    }
    this.dgConnection?.finish();
    this.processor = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.dgConnection = null;
    this.transition(FloorState.IDLE);
  }

  connectVisualizer(callback: (level: number) => void): () => void {
    if (!this.audioContext || !this.mediaStream) return () => {};
    const analyser = this.audioContext.createAnalyser();
    analyser.fftSize = 256;
    const source = this.audioContext.createMediaStreamSource(this.mediaStream);
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    let running = true;
    const loop = () => {
      if (!running) return;
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;
      callback(avg / 128);
      requestAnimationFrame(loop);
    };
    loop();
    return () => { running = false; };
  }

  public setAbortController(ac: AbortController) {
    this.currentAbortController = ac;
  }
}

// ─── Agent pipeline call ──────────────────────────────────────────────────────

export async function processTurn(
  sessionId: string,
  transcript: string,
  entities: string[] = [],
  turnId = "",
) {
  const res = await fetch(`${API}/process_turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      transcript,
      entities,
      turn_id: turnId,
    }),
  });
  if (!res.ok) throw new Error(`process_turn failed: ${res.status}`);
  return res.json();
}

// ─── TTS ──────────────────────────────────────────────────────────────────────

export async function prefetchAudio(text: string): Promise<string | null> {
  try {
    const res = await fetch(`${API}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) return null;
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

export async function playAudioUrl(
  url: string | null,
  text: string,
  signal?: AbortSignal,
): Promise<void> {
  if (!url) return speakWithBrowser(text, signal);

  const audio = new Audio(url);

  return new Promise((resolve) => {
    const onEnded = () => {
      URL.revokeObjectURL(url);
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };

    const onAbort = () => {
      audio.pause();
      audio.currentTime = 0;
      onEnded();
    };

    if (signal?.aborted) {
      onAbort();
      return;
    }

    signal?.addEventListener("abort", onAbort);
    audio.onended = onEnded;
    audio.onerror = onEnded;

    audio.play().catch(() => {
      signal?.removeEventListener("abort", onAbort);
      speakWithBrowser(text, signal).then(resolve);
    });
  });
}

export async function speakText(text: string, signal?: AbortSignal): Promise<void> {
  const url = await prefetchAudio(text);
  return playAudioUrl(url, text, signal);
}

function speakWithBrowser(text: string, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) {
      resolve();
      return;
    }

    const onAbort = () => {
      window.speechSynthesis.cancel();
      resolve();
    };

    if (signal?.aborted) {
      onAbort();
      return;
    }

    signal?.addEventListener("abort", onAbort);
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.95;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find((v) =>
      v.name.includes("Samantha") || v.name.includes("Karen") || v.name.includes("Google US English")
    );
    if (preferred) u.voice = preferred;

    u.onend = () => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };
    u.onerror = () => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };

    window.speechSynthesis.speak(u);
  });
}

// ─── Utility ──────────────────────────────────────────────────────────────────

function float32ToPcm16(float32: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < float32.length; i++) {
    const c = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, c * 0x7fff, true);
  }
  return buf;
}
