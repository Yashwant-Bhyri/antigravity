class TTSService:
    """
    Streaming Text-to-Speech service.
    Starts speaking before full sentence is ready (filler-first strategy).
    Must be interruptible.
    """

    FILLERS = [
        "Interesting...",
        "Got it...",
        "Alright...",
        "Hmm...",
        "I see...",
    ]

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def stream(self, text: str):
        # TODO: integrate ElevenLabs / Cartesia streaming TTS
        raise NotImplementedError

    async def speak_filler(self):
        """Immediately output a filler to mask LLM latency."""
        import random
        filler = random.choice(self.FILLERS)
        await self.stream(filler)

    async def interrupt(self):
        """Stop current TTS output — user has started speaking."""
        raise NotImplementedError
