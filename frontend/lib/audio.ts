/**
 * Audio capture + streaming utilities.
 * Captures mic input as PCM16 at 16kHz (matches Deepgram config) and
 * streams raw chunks over a WebSocket.
 */

const SAMPLE_RATE = 16000;
const CHUNK_DURATION_MS = 100; // send a chunk every 100ms

export class MicStreamer {
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private ws: WebSocket | null = null;
  private onTranscriptPartial: (text: string) => void;
  private onFollowup: (text: string, weakness: unknown) => void;
  private onTranscriptFinal: (text: string) => void;

  constructor(callbacks: {
    onTranscriptPartial: (text: string) => void;
    onTranscriptFinal: (text: string) => void;
    onFollowup: (text: string, weakness: unknown) => void;
  }) {
    this.onTranscriptPartial = callbacks.onTranscriptPartial;
    this.onTranscriptFinal = callbacks.onTranscriptFinal;
    this.onFollowup = callbacks.onFollowup;
  }

  async start(sessionId: string) {
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL}/stream/${sessionId}`;
    this.ws = new WebSocket(wsUrl);

    await new Promise<void>((resolve, reject) => {
      this.ws!.onopen = () => resolve();
      this.ws!.onerror = () => reject(new Error("WebSocket failed to connect"));
    });

    // Handle messages from server
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "transcript_partial") {
        this.onTranscriptPartial(msg.text);
      } else if (msg.type === "transcript_final") {
        this.onTranscriptFinal(msg.text);
      } else if (msg.type === "followup") {
        this.onFollowup(msg.text, msg.weakness);
      }
    };

    // Capture mic
    this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

    // Resample to 16kHz and convert to PCM16
    this.audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    const source = this.audioContext.createMediaStreamSource(this.mediaStream);
    const bufferSize = Math.floor((SAMPLE_RATE * CHUNK_DURATION_MS) / 1000);
    this.processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);

    this.processor.onaudioprocess = (e) => {
      if (this.ws?.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const pcm16 = float32ToPcm16(float32);
      this.ws.send(pcm16);
    };

    source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
  }

  stop() {
    this.processor?.disconnect();
    this.mediaStream?.getTracks().forEach((t) => t.stop());
    this.audioContext?.close();
    this.ws?.close();
    this.processor = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.ws = null;
  }
}

/** Float32 PCM → Int16 PCM */
function float32ToPcm16(float32: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, clamped * 0x7fff, true);
  }
  return buffer;
}

/** Fetch TTS audio from backend and play it through browser */
export async function speakText(text: string, useFiller = true): Promise<void> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, use_filler: useFiller }),
  });

  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  return new Promise((resolve) => {
    audio.onended = () => {
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.play();
  });
}
