import { createClient, LiveTranscriptionEvents } from "@deepgram/sdk";
import { CVSensor, VisionPrediction } from "./vision";
import { getApiBaseUrl } from "./api";

const API = getApiBaseUrl();
const PROCESS_TURN_TIMEOUT_MS = 50_000;
const TTS_TIMEOUT_MS = 20_000;
const FILLER_TTS_TIMEOUT_MS = 10_000;

function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const signal = init.signal;
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return fetch(input, { ...init, signal: controller.signal }).finally(() => clearTimeout(timeout));
}

export function trackInterviewEvent(
  sessionId: string,
  event: string,
  fields: Record<string, unknown> = {},
  source = "frontend.audio",
  level = "info",
) {
  if (!sessionId) return;
  fetch(`${API}/telemetry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    keepalive: true,
    body: JSON.stringify({
      session_id: sessionId,
      event,
      source,
      level,
      fields: {
        client_ts_ms: Math.round(performance.now()),
        ...fields,
      },
    }),
  }).catch(() => {});
}

// ─── Deepgram browser-side ASR ────────────────────────────────────────────────

export enum FloorState {
  IDLE = "IDLE",
  USER_SPEAKING = "USER_SPEAKING",
  AI_THINKING = "AI_THINKING",
  AI_SPEAKING = "AI_SPEAKING",
}

const FLOOR_CONFIG = {
  bargeInVadMs: 250,
  bargeInLockMs: 500,
  aiEchoCooldownMs: 1000,
  bargeInMinChars: 8,
  silenceThresholdMs: 5000,
  ttsFadeOutMs: 100,
  interimSnapshotThrottleMs: 350,
  utteranceSafetyTimeoutMs: 30000,
  // Vision Fusion Thresholds
  visionPredictionThreshold: 0.85, // high score marks likely turn-yield; it does not commit meaning
  audioWeight: 0.3,
  lipClosureWeight: 0.4,
  gazeStabilityWeight: 0.3,
};

function normalizeSpeechText(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isLikelyEchoSnippet(snippet: string, source: string): boolean {
  if (!snippet || !source) return false;
  if (snippet.length < 8) return false;
  if (source.includes(snippet)) return true;

  const words = snippet.split(" ").filter((w) => w.length > 2);
  if (words.length < 2) return false;

  const overlap = words.filter((w) => source.includes(w)).length;
  return overlap >= Math.max(2, Math.ceil(words.length * 0.6));
}

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

  // Floor Management
  public floor: FloorState = FloorState.IDLE;
  private currentAbortController: AbortController | null = null;
  private aiSpeakingStartedAt: number | null = null;
  private activeAiTextNorm = "";
  private recentAiTextNorm = "";
  private recentAiEndedAt: number | null = null;
  private activeTurnId = "";

  // Barge-in VAD duration tracking
  private bargeInVadStart: number | null = null;

  // Utterance accumulation buffer.
  private utteranceBuffer: string[] = [];
  private utteranceFlushTimer: ReturnType<typeof setTimeout> | null = null;

  // NER entity buffer.
  private entityBuffer: Set<string> = new Set();
  private lastPartialSnapshotSentAt = 0;
  private lastPartialSnapshotText = "";
  private partialSnapshotSeq = 0;

  onPartial: (text: string) => void = () => {};
  onFinal: (
    text: string,
    entities: string[],
    metadata?: { reason: "utterance_end" | "safety_timeout"; forced: boolean },
  ) => void = () => {};
  onBargeIn: () => void = () => {};
  onSilence: () => void = () => {};
  onFloorChange: (state: FloorState) => void = () => {};
  onError: (err: string) => void = () => {};

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  public setActiveTurnId(turnId: string) {
    this.activeTurnId = turnId;
  }

  public getActiveTurnId(): string {
    return this.activeTurnId;
  }

  public transition(newState: FloorState) {
    if (this.floor === newState) return;
    const previous = this.floor;

    if (this.floor === FloorState.AI_SPEAKING && newState !== FloorState.AI_SPEAKING) {
      if (this.activeAiTextNorm) {
        this.recentAiTextNorm = this.activeAiTextNorm;
        this.recentAiEndedAt = performance.now();
      }
      this.activeAiTextNorm = "";
    }

    this.floor = newState;
    this.aiSpeakingStartedAt = newState === FloorState.AI_SPEAKING ? performance.now() : null;
    this.bargeInVadStart = null;
    this.onFloorChange(newState);
    trackInterviewEvent(this.sessionId, "floor_transition", {
      from: previous,
      to: newState,
    });

    // When AI takes the floor, discard any buffered speech fragments.
    // This prevents TTS reverb (picked up during the echo drain window) from
    // contaminating the candidate's next real answer.
    if (newState === FloorState.AI_SPEAKING || newState === FloorState.AI_THINKING) {
      this.utteranceBuffer = [];
      this.entityBuffer.clear();
      if (this.utteranceFlushTimer) {
        clearTimeout(this.utteranceFlushTimer);
        this.utteranceFlushTimer = null;
      }
    }
  }

  async start() {
    const { token } = await fetch(`${API}/deepgram_token`).then((r) => r.json());
    trackInterviewEvent(this.sessionId, "audio_session_start");

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
      endpointing: 1500,
      utterance_end_ms: 2800,
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

      if (text && this.isLikelyAiEcho(text)) {
        this.bargeInVadStart = null;
        return;
      }
      
      // Update silence tracking
      if (text) {
        this.lastSilenceStart = performance.now();
      }

      // Barge-in Check (if AI is speaking)
      // Requires BOTH: sustained VAD for bargeInVadMs AND enough chars — prevents false triggers
      if (this.floor === FloorState.AI_SPEAKING) {
        const sinceAiStarted = this.aiSpeakingStartedAt === null
          ? Number.POSITIVE_INFINITY
          : performance.now() - this.aiSpeakingStartedAt;

        // Ignore the first few hundred milliseconds of ASR after TTS starts.
        // Without this lock, speaker bleed or the candidate's trailing syllable
        // can trigger a fake barge-in before the AI question has even landed.
        if (sinceAiStarted < FLOOR_CONFIG.bargeInLockMs) {
          return;
        }

        if (text.length >= FLOOR_CONFIG.bargeInMinChars) {
          if (this.bargeInVadStart === null) {
            this.bargeInVadStart = performance.now();
          }
          const vadDuration = performance.now() - this.bargeInVadStart;
          if (vadDuration >= FLOOR_CONFIG.bargeInVadMs) {
            console.log(`[Audio] Barge-in confirmed (VAD: ${vadDuration.toFixed(0)}ms, chars: ${text.length})`);
            trackInterviewEvent(this.sessionId, "barge_in_confirmed", {
              vad_ms: Math.round(vadDuration),
              chars: text.length,
            });
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
        this.utteranceBuffer.push(text);

        const rawEntities: Array<{ label: string; value: string; confidence: number }> =
          data?.channel?.alternatives?.[0]?.entities ?? [];
        const newEntities = rawEntities
          .filter((e) => e.confidence >= 0.7)
          .map((e) => e.value.trim())
          .filter((v) => v.length > 1);
        newEntities.forEach((e) => this.entityBuffer.add(e));

        const accumulated = this.utteranceBuffer.join(" ");
        const wordCount = accumulated.split(/\s+/).filter(Boolean).length;
        if (this.utteranceFlushTimer) clearTimeout(this.utteranceFlushTimer);
        this.utteranceFlushTimer = setTimeout(
          () => this._flushUtterance("safety_timeout", true),
          FLOOR_CONFIG.utteranceSafetyTimeoutMs,
        );

        trackInterviewEvent(this.sessionId, "final_fragment", {
          chars: text.length,
          words: text.split(/\s+/).filter(Boolean).length,
          accumulated_words: wordCount,
          entities_count: newEntities.length,
          snapshot_kind: "final_block",
        });

        this.onPartial(accumulated);
        this.sendPartialTranscript(accumulated, [...this.entityBuffer], true);

      } else if (text) {
        const accumulated = this.utteranceBuffer.join(" ");
        const display = accumulated ? `${accumulated} ${text}` : text;
        this.onPartial(display);
        this.sendPartialTranscript(display, [...this.entityBuffer], false);
        
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
      trackInterviewEvent(this.sessionId, "utterance_end");
      this._flushUtterance("utterance_end", true);
    });

    this.dgConnection.on(LiveTranscriptionEvents.Error, (e) => {
      this.onError(String(e));
    });

    // Capture mic — echo cancellation is critical: without it, TTS audio bleeds into
    // the mic and Deepgram transcribes the AI's own voice as the candidate's answer.
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
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

  public setActivePlaybackText(text: string | null) {
    this.activeAiTextNorm = text ? normalizeSpeechText(text) : "";
    if (text) {
      this.recentAiTextNorm = "";
      this.recentAiEndedAt = null;
    }
  }

  private isLikelyAiEcho(text: string): boolean {
    const normalized = normalizeSpeechText(text);
    if (!normalized) return false;

    if (this.activeAiTextNorm && isLikelyEchoSnippet(normalized, this.activeAiTextNorm)) {
      return true;
    }

    if (
      this.recentAiTextNorm &&
      this.recentAiEndedAt !== null &&
      performance.now() - this.recentAiEndedAt <= FLOOR_CONFIG.aiEchoCooldownMs &&
      isLikelyEchoSnippet(normalized, this.recentAiTextNorm)
    ) {
      return true;
    }

    return false;
  }

  private _flushUtterance(reason: "utterance_end" | "safety_timeout", forced = false) {
    const fullText = this.utteranceBuffer.join(" ").trim();
    const entities = [...this.entityBuffer];
    this.utteranceBuffer = [];
    this.entityBuffer.clear();

    // Reset silence tracker
    this.lastSilenceStart = performance.now();

    if (fullText) {
      trackInterviewEvent(this.sessionId, "utterance_flushed", {
        reason,
        forced,
        chars: fullText.length,
        words: fullText.split(/\s+/).filter(Boolean).length,
        entities_count: entities.length,
      });
      this.transition(FloorState.AI_THINKING);
      this.onFinal(fullText, entities, { reason, forced });
    } else if (this.floor === FloorState.USER_SPEAKING || this.floor === FloorState.AI_THINKING) {
      // Empty buffer on UtteranceEnd: candidate is confirmed done.
      // USER_SPEAKING → genuine silence nudge path.
      // AI_THINKING → a safety-timeout flush already committed the turn; this is the
      //               late confirmation that releases the defensive TTS hold.
      trackInterviewEvent(this.sessionId, "utterance_empty_flush", {
        reason,
        forced,
        floor: this.floor,
      });
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
    this.aiSpeakingStartedAt = null;
    this.activeTurnId = "";
    this.activeAiTextNorm = "";
    this.recentAiTextNorm = "";
    this.recentAiEndedAt = null;
    this.utteranceBuffer = [];
    this.lastPartialSnapshotSentAt = 0;
    this.lastPartialSnapshotText = "";
    this.partialSnapshotSeq = 0;
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

  private sendPartialTranscript(transcript: string, entities: string[], isFinal: boolean) {
    const cleaned = transcript.trim();
    if (!cleaned) return;

    const now = performance.now();
    if (!isFinal) {
      const changedMeaningfully = cleaned.length >= this.lastPartialSnapshotText.length + 12;
      const throttled = now - this.lastPartialSnapshotSentAt < FLOOR_CONFIG.interimSnapshotThrottleMs;
      if (!changedMeaningfully || throttled) return;
    }

    this.lastPartialSnapshotSentAt = now;
    this.lastPartialSnapshotText = cleaned;
    this.partialSnapshotSeq += 1;

    trackInterviewEvent(this.sessionId, "partial_snapshot_sent", {
      is_final: isFinal,
      chars: cleaned.length,
      words: cleaned.split(/\s+/).filter(Boolean).length,
      snapshot_seq: this.partialSnapshotSeq,
    });

    fetch(`${API}/partial_transcript`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: this.sessionId,
        transcript: cleaned,
        entities,
        turn_id: this.activeTurnId,
        is_final: isFinal,
        snapshot_seq: this.partialSnapshotSeq,
      }),
    }).catch(() => {});
  }
}

// ─── Agent pipeline call ──────────────────────────────────────────────────────

export async function processTurn(
  sessionId: string,
  transcript: string,
  entities: string[] = [],
  turnId = "",
) {
  const startedAt = performance.now();
  const res = await fetchWithTimeout(`${API}/process_turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      transcript,
      entities,
      turn_id: turnId,
    }),
  }, PROCESS_TURN_TIMEOUT_MS);
  if (!res.ok) {
    trackInterviewEvent(sessionId, "frontend_process_turn_failed", {
      turn_id: turnId,
      status: res.status,
      elapsed_ms: Math.round(performance.now() - startedAt),
    }, "frontend.audio", "error");
    throw new Error(`process_turn failed: ${res.status}`);
  }
  const payload = await res.json();
  trackInterviewEvent(sessionId, "frontend_process_turn", {
    turn_id: turnId,
    transcript_chars: transcript.length,
    transcript_words: transcript.split(/\s+/).filter(Boolean).length,
    entities_count: entities.length,
    route_kind: payload?.route_kind ?? null,
    elapsed_ms: Math.round(performance.now() - startedAt),
  });
  return payload;
}

// ─── TTS ──────────────────────────────────────────────────────────────────────

export async function prefetchAudio(text: string, sessionId?: string): Promise<string | null> {
  if (!text) return null;
  console.log(`[TTS] Prefetching: "${text.slice(0, 30)}..."`);
  const startedAt = performance.now();
  try {
    const res = await fetchWithTimeout(`${API}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, session_id: sessionId ?? "" }),
    }, TTS_TIMEOUT_MS);
    if (!res.ok) {
      console.warn(`[TTS] ElevenLabs returned ${res.status}. Fallback: browser TTS.`);
      trackInterviewEvent(sessionId ?? "system", "frontend_tts_prefetch_failed", {
        status: res.status,
        text_chars: text.length,
        elapsed_ms: Math.round(performance.now() - startedAt),
      }, "frontend.audio", "warn");
      return null;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    console.log(`[TTS] Prefetch successful. ObjectURL: ${url}`);
    trackInterviewEvent(sessionId ?? "system", "frontend_tts_prefetch", {
      text_chars: text.length,
      provider: res.headers.get("X-TTS-Provider"),
      source_kind: res.headers.get("X-TTS-Source"),
      content_type: res.headers.get("Content-Type"),
      audio_bytes: blob.size,
      elapsed_ms: Math.round(performance.now() - startedAt),
    });
    return url;
  } catch (e) {
    console.warn("[TTS] ElevenLabs fetch failed. Fallback: browser TTS.", e);
    trackInterviewEvent(sessionId ?? "system", "frontend_tts_prefetch_failed", {
      text_chars: text.length,
      error: String(e),
      elapsed_ms: Math.round(performance.now() - startedAt),
    }, "frontend.audio", "warn");
    return null;
  }
}

export async function prefetchFillerAudio(): Promise<{ url: string | null; text: string }> {
  const fallbackText = "Interesting.";
  const startedAt = performance.now();
  try {
    const res = await fetchWithTimeout(`${API}/tts_filler`, {}, FILLER_TTS_TIMEOUT_MS);
    const fillerText = res.headers.get("X-Filler-Text")?.trim() || fallbackText;
    if (!res.ok) {
      console.warn(`[TTS] Filler fetch returned ${res.status}. Falling back to browser TTS filler.`);
      trackInterviewEvent("system", "frontend_tts_filler_failed", {
        status: res.status,
        elapsed_ms: Math.round(performance.now() - startedAt),
      }, "frontend.audio", "warn");
      return { url: null, text: fillerText };
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    trackInterviewEvent("system", "frontend_tts_filler", {
      provider: res.headers.get("X-TTS-Provider"),
      content_type: res.headers.get("Content-Type"),
      filler_text: fillerText,
      audio_bytes: blob.size,
      elapsed_ms: Math.round(performance.now() - startedAt),
    });
    return { url, text: fillerText };
  } catch (e) {
    console.warn("[TTS] Filler fetch failed. Falling back to browser TTS filler.", e);
    trackInterviewEvent("system", "frontend_tts_filler_failed", {
      error: String(e),
      elapsed_ms: Math.round(performance.now() - startedAt),
    }, "frontend.audio", "warn");
    return { url: null, text: fallbackText };
  }
}

export async function playAudioUrl(
  url: string | null,
  text: string,
  signal?: AbortSignal,
): Promise<void> {
  if (!url) return speakWithBrowser(text, signal);

  const audio = new Audio(url);
  audio.preload = "auto";
  const startedAt = performance.now();

  return new Promise((resolve) => {
    let started = false;
    const onEnded = () => {
      URL.revokeObjectURL(url);
      signal?.removeEventListener("abort", onAbort);
      trackInterviewEvent("system", "frontend_audio_playback_done", {
        text_chars: text.length,
        elapsed_ms: Math.round(performance.now() - startedAt),
      });
      resolve();
    };

    const onAbort = () => {
      audio.pause();
      audio.currentTime = 0;
      trackInterviewEvent("system", "frontend_audio_playback_aborted", {
        text_chars: text.length,
        elapsed_ms: Math.round(performance.now() - startedAt),
      }, "frontend.audio", "warn");
      onEnded();
    };

    if (signal?.aborted) {
      onAbort();
      return;
    }

    const startPlayback = () => {
      if (started) return;
      started = true;
      signal?.addEventListener("abort", onAbort);
      audio.onended = onEnded;
      audio.onerror = onEnded;

      audio.play().catch((err) => {
        console.warn("[Audio] ElevenLabs playback failed, falling back to browser TTS:", err);
        if (url) URL.revokeObjectURL(url);
        signal?.removeEventListener("abort", onAbort);
        trackInterviewEvent("system", "frontend_audio_playback_fallback", {
          text_chars: text.length,
          error: String(err),
          elapsed_ms: Math.round(performance.now() - startedAt),
        }, "frontend.audio", "warn");
        speakWithBrowser(text, signal).then(resolve);
      });
    };

    if (audio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      startPlayback();
      return;
    }

    const onReady = () => {
      audio.removeEventListener("loadeddata", onReady);
      audio.removeEventListener("canplaythrough", onReady);
      startPlayback();
    };
    audio.addEventListener("loadeddata", onReady, { once: true });
    audio.addEventListener("canplaythrough", onReady, { once: true });
    setTimeout(onReady, 250);
  });
}

export async function speakText(text: string, signal?: AbortSignal): Promise<void> {
  const url = await prefetchAudio(text);
  return playAudioUrl(url, text, signal);
}

// Chrome/macOS SpeechSynthesis truncates long utterances (>~200 chars) — it skips
// the beginning. Fix: chunk into sentences and speak sequentially.
function speakWithBrowser(text: string, signal?: AbortSignal): Promise<void> {
  if (!window.speechSynthesis) return Promise.resolve();
  console.warn(`[TTS] ElevenLabs unavailable. Using browser fallback for: "${text.slice(0, 30)}..."`);

  if (window.speechSynthesis.speaking) {
    console.log("[TTS] Browser is currently speaking. Cancelling previous to start new.");
    window.speechSynthesis.cancel();
  }

  // Split on sentence boundaries, keeping the delimiter attached to the sentence.
  const sentences = text.match(/[^.!?]+[.!?]*/g) ?? [text];

  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find((v) =>
    v.name.includes("Samantha") || v.name.includes("Karen") || v.name.includes("Google US English")
  );

  const speakOne = (chunk: string): Promise<void> =>
    new Promise((resolve) => {
      if (signal?.aborted) { resolve(); return; }

      const u = new SpeechSynthesisUtterance(chunk.trim());
      u.rate = 0.95;
      if (preferred) u.voice = preferred;

      const onAbort = () => { window.speechSynthesis.cancel(); resolve(); };
      signal?.addEventListener("abort", onAbort);
      
      u.onstart = () => console.log(`[TTS] Browser started speaking: "${chunk.slice(0, 20)}..."`);
      u.onend = () => { signal?.removeEventListener("abort", onAbort); resolve(); };
      u.onerror = (e) => { 
        console.error("[TTS] Browser Speech Error:", e);
        signal?.removeEventListener("abort", onAbort); 
        resolve(); 
      };
      
      window.speechSynthesis.speak(u);
    });

  return sentences.reduce(
    (chain, sentence) => chain.then(() => {
      if (signal?.aborted) return;
      return speakOne(sentence);
    }),
    Promise.resolve() as Promise<void>,
  );
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
