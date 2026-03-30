from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from backend.services.orchestrator import Orchestrator
from backend.services.asr_service import ASRService

router = APIRouter()
orchestrator = Orchestrator()


class StartInterviewRequest(BaseModel):
    resume: str
    github_links: list[str] = []


@router.post("/start_interview")
async def start_interview(data: StartInterviewRequest):
    session_id = await orchestrator.start_session(data.resume, data.github_links)
    return {"session_id": session_id}


@router.websocket("/stream/{session_id}")
async def stream_audio(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time audio streaming.

    Frontend connects here and sends raw PCM16 audio chunks (16kHz, mono).
    ASR service forwards to Deepgram → fires partial/final transcript callbacks
    → orchestrator runs agent pipeline → sends follow-up text back to frontend.

    Message format from server: {"type": "followup" | "partial", "text": "..."}
    """
    await websocket.accept()

    asr = ASRService(
        on_partial=orchestrator.on_partial_transcript,
        on_final=_make_final_handler(websocket, session_id),
    )

    await asr.connect(session_id)

    try:
        while True:
            audio_chunk = await websocket.receive_bytes()
            await asr.send_audio(session_id, audio_chunk)
    except WebSocketDisconnect:
        pass
    finally:
        await asr.disconnect(session_id)


def _make_final_handler(websocket: WebSocket, session_id: str):
    """Returns the on_final callback for this WebSocket session."""
    async def on_final(sid: str, text: str):
        result = await orchestrator.handle_transcript(sid, text)
        await websocket.send_json({
            "type": "followup",
            "text": result["response"],
            "weakness": result.get("weakness"),
        })
    return on_final


@router.get("/state/{session_id}")
async def get_state(session_id: str):
    return await orchestrator.get_session_state(session_id)
