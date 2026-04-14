import os
import asyncio
import random
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import VoiceSettings


# eleven_turbo_v2_5 = lowest latency (~75ms first chunk), good quality
TTS_MODEL = "eleven_turbo_v2_5"
TTS_VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"  # Alice — clear, engaging, professional (free premade)

FILLER_PHRASES = [
    "Interesting.",
    "Got it.",
    "Alright.",
    "I see.",
    "Right.",
    "Sure.",
]


class TTSService:
    """
    Streaming TTS via ElevenLabs (eleven_turbo_v2_5 model).

    True filler-first strategy:
      The filler audio is pre-cached at startup — served in <10ms.
      Frontend fires GET /tts_filler immediately when candidate stops speaking,
      while simultaneously kicking off the LLM pipeline.
      Perceived response latency: ~75ms (filler playback) regardless of LLM speed.

    Usage:
        tts = TTSService()
        async for chunk in tts.stream("How would you handle cold start?"):
            await websocket.send_bytes(chunk)
    """

    def __init__(self):
        self._api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("TTS_API_KEY", "")
        self.client = AsyncElevenLabs(api_key=self._api_key)
        self._voice_settings = VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            use_speaker_boost=True,
        )
        # Pre-cached filler audio: phrase → bytes
        # Populated lazily on first use; once cached, /tts_filler returns in <10ms
        self._filler_cache: dict[str, bytes] = {}

    async def stream(self, text: str):
        """Async generator yielding MP3 chunks from ElevenLabs."""
        async for chunk in self.client.text_to_speech.convert(
            voice_id=TTS_VOICE_ID,
            text=text,
            model_id=TTS_MODEL,
            voice_settings=self._voice_settings,
            output_format="mp3_44100_128",
        ):
            if chunk:
                yield chunk

    async def get_filler_audio(self) -> bytes:
        """
        Returns pre-cached filler phrase audio.
        First call per phrase hits ElevenLabs (~75ms); subsequent calls are instant.
        Rotates through FILLER_PHRASES so the interviewer doesn't sound like a broken record.
        """
        phrase = random.choice(FILLER_PHRASES)
        if phrase not in self._filler_cache:
            chunks: list[bytes] = []
            async for chunk in self.stream(phrase):
                chunks.append(chunk)
            self._filler_cache[phrase] = b"".join(chunks)
        return self._filler_cache[phrase]

    async def stream_with_filler(self, followup_text: str):
        """
        Legacy method — streams filler + response as one combined string.
        Kept for compatibility; the preferred path is the parallel filler approach.
        """
        filler = random.choice(FILLER_PHRASES)
        full_text = f"{filler} {followup_text}"
        async for chunk in self.stream(full_text):
            yield chunk

    async def warm_filler_cache(self):
        """
        Pre-generates audio for all filler phrases at startup.
        Processed sequentially to avoid triggering ElevenLabs concurrency rate limits (429).
        """
        for phrase in FILLER_PHRASES:
            if phrase not in self._filler_cache:
                try:
                    await self._cache_phrase(phrase)
                    # Tiny sleep to ensure ElevenLabs has time to reset internal state
                    await asyncio.sleep(0.1)
                except Exception as e:
                    print(f"[TTS] Failed to pre-cache filler '{phrase}': {e}")

    async def _cache_phrase(self, phrase: str):
        chunks: list[bytes] = []
        async for chunk in self.stream(phrase):
            chunks.append(chunk)
        self._filler_cache[phrase] = b"".join(chunks)
