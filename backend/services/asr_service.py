import os
import asyncio
from typing import Callable, Awaitable
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)


# Deepgram connection config — matches the sample from the API key setup
DEEPGRAM_OPTIONS = LiveOptions(
    model="nova-3",
    language="en",
    encoding="linear16",
    sample_rate=16000,
    channels=1,
    endpointing=False,        # we handle turn detection ourselves
    interim_results=True,     # fire on partial transcripts for predictive prep
    utterance_end_ms=1000,    # silence threshold to mark end of utterance
    vad_events=True,          # voice activity detection events
)


class ASRService:
    """
    Streaming ASR via Deepgram WebSocket (nova-3 model).

    Fires two callbacks:
      on_partial(text) → called on every interim result (for predictive turn prep)
      on_final(text)   → called on final transcript (triggers full agent pipeline)

    Usage:
        asr = ASRService(
            on_partial=orchestrator.on_partial_transcript,
            on_final=orchestrator.handle_transcript,
        )
        await asr.connect(session_id)
        await asr.send_audio(chunk)   # feed raw PCM16 chunks from mic
        await asr.disconnect()
    """

    def __init__(
        self,
        on_partial: Callable[[str, str], Awaitable[None]],
        on_final: Callable[[str, str], Awaitable[None]],
    ):
        self.on_partial = on_partial   # (session_id, text)
        self.on_final = on_final       # (session_id, text)
        self._api_key = os.environ["DEEPGRAM_API_KEY"]
        self._connections: dict[str, object] = {}  # session_id → live connection

    async def connect(self, session_id: str):
        """Open a Deepgram WebSocket for a session."""
        client = DeepgramClient(
            self._api_key,
            DeepgramClientOptions(options={"keepalive": "true"}),
        )
        connection = client.listen.asyncwebsocket.v("1")

        # Wire Deepgram events to our callbacks
        async def _on_transcript(self_dg, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if not sentence:
                return
            if result.is_final:
                await on_final(session_id, sentence)
            else:
                await on_partial(session_id, sentence)

        async def _on_error(self_dg, error, **kwargs):
            print(f"[ASR] Deepgram error for session {session_id}: {error}")

        # Need to capture outer `on_final` and `on_partial` in closures
        on_final = self.on_final
        on_partial = self.on_partial

        connection.on(LiveTranscriptionEvents.Transcript, _on_transcript)
        connection.on(LiveTranscriptionEvents.Error, _on_error)

        started = await connection.start(DEEPGRAM_OPTIONS)
        if not started:
            raise RuntimeError(f"Failed to start Deepgram connection for session {session_id}")

        self._connections[session_id] = connection
        print(f"[ASR] Connected for session {session_id}")

    async def send_audio(self, session_id: str, chunk: bytes):
        """Feed a raw PCM16 audio chunk into the stream."""
        conn = self._connections.get(session_id)
        if conn:
            await conn.send(chunk)

    async def disconnect(self, session_id: str):
        """Close the Deepgram WebSocket for a session."""
        conn = self._connections.pop(session_id, None)
        if conn:
            await conn.finish()
            print(f"[ASR] Disconnected session {session_id}")
