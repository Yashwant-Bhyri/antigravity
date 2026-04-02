import { createClient, LiveTranscriptionEvents } from "@deepgram/sdk";

const API = process.env.NEXT_PUBLIC_API_URL!;

// ─── Deepgram browser-side ASR ────────────────────────────────────────────────

export class InterviewSession {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private dgConnection: ReturnType<ReturnType<typeof createClient>["listen"]["live"]> | null = null;
  private sessionId: string;

  // Utterance accumulation buffer.
  // Deepgram fires is_final multiple times within one answer (every ~1s of silence).
  // We collect every is_final fragment here and only call onFinal when UtteranceEnd fires,
  // meaning the person is truly done speaking (2.5s of silence), not just pausing mid-thought.
  private utteranceBuffer: string[] = [];
  private utteranceFlushTimer: ReturnType<typeof setTimeout> | null = null;

  // NER entity buffer — accumulates Deepgram-extracted entities across all is_final fragments.
  // Entities (technology names, product names, etc.) surface the "heart" of the answer —
  // the 2-3 sentences where the candidate actually delivers technical substance.
  private entityBuffer: Set<string> = new Set();

  onPartial: (text: string) => void = () => {};
  onFinal: (text: string, entities: string[]) => void = () => {};
  onError: (err: string) => void = () => {};

  constructor(sessionId: string) {
    this.sessionId = sessionId;
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
      // NER: extract named entities (technologies, products, orgs) from each is_final fragment.
      // These surface the technically dense parts of the answer for targeted follow-up generation.
      ner: true,
      // endpointing: how long silence makes a fragment is_final (within an utterance)
      endpointing: 1200,
      // utterance_end_ms: real "done speaking" gate — triggers UtteranceEnd
      utterance_end_ms: 2500,
    });

    await new Promise<void>((resolve, reject) => {
      this.dgConnection!.on(LiveTranscriptionEvents.Open, () => resolve());
      this.dgConnection!.on(LiveTranscriptionEvents.Error, (e) => reject(e));
      setTimeout(() => reject(new Error("Deepgram connection timeout")), 8000);
    });

    // ── Transcript handler ────────────────────────────────────────────────────
    // is_final: a stable sub-utterance fragment — accumulate it, don't send yet
    // interim: live display + prefetch, nothing more
    this.dgConnection.on(LiveTranscriptionEvents.Transcript, (data) => {
      const text = data?.channel?.alternatives?.[0]?.transcript ?? "";
      if (!text) return;

      if (data.is_final) {
        // Accumulate the transcript fragment
        this.utteranceBuffer.push(text);

        // Extract NER entities from this fragment.
        // Filter to high-confidence entities — these are the technical keywords
        // the candidate actually said (technologies, products, concepts).
        const rawEntities: Array<{ label: string; value: string; confidence: number }> =
          data?.channel?.alternatives?.[0]?.entities ?? [];
        const newEntities = rawEntities
          .filter((e) => e.confidence >= 0.7)
          .map((e) => e.value.trim())
          .filter((v) => v.length > 1);
        newEntities.forEach((e) => this.entityBuffer.add(e));

        // Safety net: if UtteranceEnd never fires, flush after 5s
        if (this.utteranceFlushTimer) clearTimeout(this.utteranceFlushTimer);
        this.utteranceFlushTimer = setTimeout(() => this._flushUtterance(), 5000);

        // Show accumulating transcript
        const accumulated = this.utteranceBuffer.join(" ");
        this.onPartial(accumulated);

        // Fire prefetch with accumulated transcript + entities gathered so far.
        // Entities take the NER fast-path on the backend (no ConceptAgent LLM call).
        const entitySnapshot = [...this.entityBuffer];
        fetch(`${API}/partial_transcript`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: this.sessionId,
            transcript: accumulated,
            entities: entitySnapshot,
          }),
        }).catch(() => {});

      } else {
        // Interim: show live text appended after confirmed fragments
        const accumulated = this.utteranceBuffer.join(" ");
        const display = accumulated ? `${accumulated} ${text}` : text;
        this.onPartial(display);
      }
    });

    // ── UtteranceEnd: the real "done speaking" signal ────────────────────────
    // Fires after utterance_end_ms (2500ms) of silence.
    // This is when we send the full accumulated answer to the AI.
    this.dgConnection.on(LiveTranscriptionEvents.UtteranceEnd, () => {
      if (this.utteranceFlushTimer) {
        clearTimeout(this.utteranceFlushTimer);
        this.utteranceFlushTimer = null;
      }
      this._flushUtterance();
    });

    this.dgConnection.on(LiveTranscriptionEvents.Error, (e) => {
      this.onError(String(e));
    });

    // Capture mic → stream PCM16 to Deepgram
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

  private _flushUtterance() {
    const fullText = this.utteranceBuffer.join(" ").trim();
    const entities = [...this.entityBuffer];
    this.utteranceBuffer = [];
    this.entityBuffer.clear();
    if (fullText) {
      this.onFinal(fullText, entities);
    }
  }

  stop() {
    if (this.utteranceFlushTimer) {
      clearTimeout(this.utteranceFlushTimer);
      this.utteranceFlushTimer = null;
    }
    this.utteranceBuffer = [];
    this.processor?.disconnect();
    this.mediaStream?.getTracks().forEach((t) => t.stop());
    this.audioContext?.close();
    this.dgConnection?.finish();
    this.processor = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.dgConnection = null;
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
}

// ─── Agent pipeline call ──────────────────────────────────────────────────────

export async function processTurn(sessionId: string, transcript: string, entities: string[] = []) {
  const res = await fetch(`${API}/process_turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, transcript, entities }),
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

export async function playAudioUrl(url: string | null, text: string): Promise<void> {
  if (!url) return speakWithBrowser(text);
  const audio = new Audio(url);
  return new Promise((resolve) => {
    audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
    audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
    audio.play().catch(() => { URL.revokeObjectURL(url); speakWithBrowser(text).then(resolve); });
  });
}

export async function speakText(text: string): Promise<void> {
  const url = await prefetchAudio(text);
  return playAudioUrl(url, text);
}

function speakWithBrowser(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) { resolve(); return; }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.95;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find((v) =>
      v.name.includes("Samantha") || v.name.includes("Karen") || v.name.includes("Google US English")
    );
    if (preferred) u.voice = preferred;
    u.onend = () => resolve();
    u.onerror = () => resolve();
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
