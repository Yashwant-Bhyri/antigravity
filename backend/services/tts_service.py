import os
import asyncio
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import VoiceSettings


# eleven_turbo_v2_5 = lowest latency (~75ms first chunk), good quality
TTS_MODEL = "eleven_turbo_v2_5"
TTS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel — clear, professional, neutral accent

FILLER_PHRASES = [
    "Interesting.",
    "Got it.",
    "Alright.",
    "I see.",
    "Hmm.",
    "Right.",
]


class TTSService:
    """
    Streaming TTS via ElevenLabs (eleven_turbo_v2_5 model).

    Filler-first strategy:
      1. Immediately stream a filler phrase ("Interesting...", "Got it...")
      2. Stream the real follow-up question right after
      → Perceived latency drops to ~75ms even if LLM takes 500ms

    Usage:
        tts = TTSService()
        async for chunk in tts.stream("How would you handle cold start?"):
            await websocket.send_bytes(chunk)
    """

    def __init__(self):
        self._api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ["TTS_API_KEY"]
        self.client = AsyncElevenLabs(api_key=self._api_key)
        self._voice_settings = VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            use_speaker_boost=True,
        )

    async def stream(self, text: str):
        """
        Async generator that yields MP3 audio chunks.
        Caller is responsible for sending chunks to the client.
        """
        # No await needed before an async generator call
        async for chunk in self.client.text_to_speech.convert(
            voice_id=TTS_VOICE_ID,
            text=text,
            model_id=TTS_MODEL,
            voice_settings=self._voice_settings,
            output_format="mp3_44100_128",
        ):
            if chunk:
                yield chunk

    async def stream_with_filler(self, followup_text: str):
        """
        Streams a filler phrase immediately, then the real follow-up.
        Use this on every turn to mask agent processing latency.
        """
        import random
        filler = random.choice(FILLER_PHRASES)
        full_text = f"{filler} {followup_text}"
        async for chunk in self.stream(full_text):
            yield chunk
