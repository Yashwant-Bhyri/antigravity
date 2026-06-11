import { getApiBaseUrl } from "./api";

const API = getApiBaseUrl();

export type VoiceRuntimeStatus =
  | "idle"
  | "deck_ready"
  | "speaking"
  | "listening"
  | "committing"
  | "recovering"
  | "stopped"
  | "error";

export type VoiceRuntimeEvent =
  | "repeat_requested"
  | "slow_down_requested"
  | "candidate_confused"
  | "candidate_interrupted_ai"
  | "ai_speech_interrupted"
  | "pause_requested"
  | "resume_requested"
  | "long_silence"
  | "unclear_audio"
  | "transcript_delta"
  | "transcript_final";

export type ActionDeckResponse = {
  action_deck: Record<string, unknown>;
  policy_decision: Record<string, unknown>;
};

export type SpokenQuestionCommit = {
  session_id: string;
  turn_id?: string;
  selected_move_id: string;
  backend_question: string;
  spoken_text: string;
  route_kind?: string;
  backend_intent_preserved?: boolean;
  spoken_at_ms?: number;
};

export type VoiceRuntimeCallbacks = {
  onStatus?: (status: VoiceRuntimeStatus) => void;
  onDeck?: (payload: ActionDeckResponse) => void;
  onPartialTranscript?: (text: string, itemId: string) => void;
  onFinalTranscript?: (text: string, itemId: string) => void;
  onError?: (error: Error) => void;
};

export interface VoiceRuntime {
  readonly sessionId: string;
  readonly provider: "openai";
  start(turnId?: string): Promise<ActionDeckResponse>;
  stop(): Promise<void>;
  fetchActionDeck(turnId?: string): Promise<ActionDeckResponse>;
  commitSpokenQuestion(commit: Omit<SpokenQuestionCommit, "session_id">): Promise<Record<string, unknown>>;
  postEvent(eventType: VoiceRuntimeEvent, payload?: Partial<{
    turnId: string;
    itemId: string;
    transcript: string;
    isFinal: boolean;
    snapshotSeq: number;
    metadata: Record<string, unknown>;
  }>): Promise<Record<string, unknown>>;
  commitTurn(payload: {
    transcript: string;
    turnId?: string;
    itemId?: string;
    entities?: string[];
    spokenQuestionTurnId?: string;
  }): Promise<Record<string, unknown>>;
  requestRecovery(reason: string, turnId?: string, metadata?: Record<string, unknown>): Promise<ActionDeckResponse>;
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
  }
  return payload as T;
}

export class OpenAIRealtimeInterviewSession implements VoiceRuntime {
  readonly provider = "openai" as const;
  readonly sessionId: string;
  private callbacks: VoiceRuntimeCallbacks;
  private status: VoiceRuntimeStatus = "idle";

  constructor(sessionId: string, callbacks: VoiceRuntimeCallbacks = {}) {
    this.sessionId = sessionId;
    this.callbacks = callbacks;
  }

  async start(turnId = ""): Promise<ActionDeckResponse> {
    try {
      const deck = await this.fetchActionDeck(turnId);
      this.setStatus("deck_ready");
      return deck;
    } catch (error) {
      this.fail(error);
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.setStatus("stopped");
  }

  async fetchActionDeck(turnId = ""): Promise<ActionDeckResponse> {
    const suffix = turnId ? `?turn_id=${encodeURIComponent(turnId)}` : "";
    const res = await fetch(`${API}/voice/action_deck/${encodeURIComponent(this.sessionId)}${suffix}`);
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
    const deck = payload as ActionDeckResponse;
    this.callbacks.onDeck?.(deck);
    return deck;
  }

  async commitSpokenQuestion(commit: Omit<SpokenQuestionCommit, "session_id">): Promise<Record<string, unknown>> {
    return postJson("/voice/spoken_question", {
      session_id: this.sessionId,
      ...commit,
    });
  }

  async postEvent(eventType: VoiceRuntimeEvent, payload: Partial<{
    turnId: string;
    itemId: string;
    transcript: string;
    isFinal: boolean;
    snapshotSeq: number;
    metadata: Record<string, unknown>;
  }> = {}): Promise<Record<string, unknown>> {
    const transcript = payload.transcript || "";
    if (eventType === "transcript_delta") this.callbacks.onPartialTranscript?.(transcript, payload.itemId || "");
    if (eventType === "transcript_final") this.callbacks.onFinalTranscript?.(transcript, payload.itemId || "");
    return postJson("/voice/event", {
      session_id: this.sessionId,
      event_type: eventType,
      provider: "openai",
      turn_id: payload.turnId || "",
      item_id: payload.itemId || "",
      transcript,
      is_final: Boolean(payload.isFinal),
      snapshot_seq: payload.snapshotSeq || 0,
      metadata: payload.metadata || {},
    });
  }

  async commitTurn(payload: {
    transcript: string;
    turnId?: string;
    itemId?: string;
    entities?: string[];
    spokenQuestionTurnId?: string;
  }): Promise<Record<string, unknown>> {
    this.setStatus("committing");
    try {
      const result = await postJson<Record<string, unknown>>("/voice/commit_turn", {
        session_id: this.sessionId,
        transcript: payload.transcript,
        turn_id: payload.turnId || "",
        item_id: payload.itemId || "",
        entities: payload.entities || [],
        spoken_question_turn_id: payload.spokenQuestionTurnId || "",
      });
      this.setStatus("deck_ready");
      return result;
    } catch (error) {
      this.fail(error);
      throw error;
    }
  }

  async requestRecovery(reason: string, turnId = "", metadata: Record<string, unknown> = {}): Promise<ActionDeckResponse> {
    this.setStatus("recovering");
    const response = await postJson<ActionDeckResponse>("/voice/recovery_deck", {
      session_id: this.sessionId,
      reason,
      turn_id: turnId,
      metadata,
    });
    this.callbacks.onDeck?.(response);
    return response;
  }

  private setStatus(status: VoiceRuntimeStatus) {
    this.status = status;
    this.callbacks.onStatus?.(status);
  }

  private fail(error: unknown) {
    this.setStatus("error");
    this.callbacks.onError?.(error instanceof Error ? error : new Error(String(error)));
  }
}
