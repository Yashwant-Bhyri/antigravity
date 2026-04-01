import { createClient, LiveTranscriptionEvents } from "@deepgram/sdk";

const API = process.env.NEXT_PUBLIC_API_URL!;

// ─── Deepgram browser-side ASR ────────────────────────────────────────────────

export class InterviewSession {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private dgConnection: ReturnType<ReturnType<typeof createClient>["listen"]["live"]> | null = null;
  private sessionId: string;

  onPartial: (text: string) => void = () => {};
  onFinal: (text: string) => void = () => {};
  onError: (err: string) => void = () => {};

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  async start() {
    // Get Deepgram token from backend (keeps key server-side in prod)
    const { token } = await fetch(`${API}/deepgram_token`).then((r) => r.json());

    const dg = createClient(token);
    this.dgConnection = dg.listen.live({
      model: "nova-3",
      language: "en",
      encoding: "linear16",
      sample_rate: 16000,
      channels: 1,
      interim_results: true,
      endpointing: 300,
      utterance_end_ms: 1000,
    });

    // Wait for connection open
    await new Promise<void>((resolve, reject) => {
      this.dgConnection!.on(LiveTranscriptionEvents.Open, () => resolve());
      this.dgConnection!.on(LiveTranscriptionEvents.Error, (e) => reject(e));
      setTimeout(() => reject(new Error("Deepgram connection timeout")), 8000);
    });

    this.dgConnection.on(LiveTranscriptionEvents.Transcript, (data) => {
      const text = data?.channel?.alternatives?.[0]?.transcript ?? "";
      if (!text) return;

      if (data.is_final) {
        this.onFinal(text);
        // Fire partial to backend for predictive prefetch (non-blocking)
        fetch(`${API}/partial_transcript`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: this.sessionId, transcript: text }),
        }).catch(() => {});
      } else {
        this.onPartial(text);
      }
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

  stop() {
    this.processor?.disconnect();
    this.mediaStream?.getTracks().forEach((t) => t.stop());
    this.audioContext?.close();
    this.dgConnection?.finish();
    this.processor = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.dgConnection = null;
  }

  /** Connect mic level to a canvas for the live waveform visualizer */
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
      callback(avg / 128); // 0–1
      requestAnimationFrame(loop);
    };
    loop();
    return () => { running = false; };
  }
}

// ─── Agent pipeline call ──────────────────────────────────────────────────────

export async function processTurn(sessionId: string, transcript: string) {
  const res = await fetch(`${API}/process_turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, transcript }),
  });
  if (!res.ok) throw new Error(`process_turn failed: ${res.status}`);
  return res.json();
}

// ─── TTS ──────────────────────────────────────────────────────────────────────

export async function speakText(text: string, useFiller = true): Promise<void> {
  try {
    const res = await fetch(`${API}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_filler: useFiller }),
    });
    if (!res.ok) return speakWithBrowser(text);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    return new Promise((resolve) => {
      audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
      audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
      audio.play().catch(() => speakWithBrowser(text).then(resolve));
    });
  } catch {
    return speakWithBrowser(text);
  }
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
