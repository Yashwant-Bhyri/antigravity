class ASRService:
    """
    Streaming Automatic Speech Recognition.
    Connects to Deepgram WebSocket and streams partial + final transcripts.
    Target latency: <100ms per chunk.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def stream(self, audio_chunk: bytes) -> dict:
        # TODO: integrate Deepgram streaming WebSocket
        # Returns: {"type": "partial" | "final", "text": "..."}
        raise NotImplementedError

    async def on_partial(self, text: str):
        # Fired on every partial transcript — triggers predictive turn prep
        raise NotImplementedError

    async def on_final(self, text: str):
        # Fired on final transcript — triggers full orchestrator pipeline
        raise NotImplementedError
