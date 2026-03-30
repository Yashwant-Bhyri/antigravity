from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.services.orchestrator import Orchestrator
from backend.services.asr_service import ASRService
from backend.services.tts_service import TTSService

router = APIRouter()
orchestrator = Orchestrator()
tts_service = TTSService()


class StartInterviewRequest(BaseModel):
    resume: str
    github_links: list[str] = []


class TTSRequest(BaseModel):
    text: str
    use_filler: bool = True


@router.post("/start_interview")
async def start_interview(data: StartInterviewRequest):
    session_id = await orchestrator.start_session(data.resume, data.github_links)
    # Return the opening question so frontend can speak it immediately
    state = await orchestrator.get_session_state(session_id)
    opening = state.get("last_question", "")
    return {"session_id": session_id, "opening_question": opening}


@router.post("/tts")
async def synthesize_speech(data: TTSRequest):
    """
    HTTP streaming endpoint — returns MP3 audio stream.
    Frontend calls this after receiving a follow-up text from the WebSocket,
    then plays the audio through the browser's audio API.
    """
    async def audio_generator():
        if data.use_filler:
            async for chunk in tts_service.stream_with_filler(data.text):
                yield chunk
        else:
            async for chunk in tts_service.stream(data.text):
                yield chunk

    return StreamingResponse(
        audio_generator(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


@router.websocket("/stream/{session_id}")
async def stream_audio(websocket: WebSocket, session_id: str):
    """
    WebSocket for real-time audio input from the candidate's microphone.

    Frontend sends:  raw PCM16 audio bytes (16kHz mono)
    Server sends:    JSON events
      {"type": "transcript_partial", "text": "..."}   — show interim transcript
      {"type": "followup", "text": "...", "weakness": {...}}  — AI follow-up ready
      {"type": "error", "message": "..."}
    """
    await websocket.accept()

    async def on_partial(sid: str, text: str):
        await websocket.send_json({"type": "transcript_partial", "text": text})

    async def on_final(sid: str, text: str):
        await websocket.send_json({"type": "transcript_final", "text": text})
        result = await orchestrator.handle_transcript(sid, text)
        await websocket.send_json({
            "type": "followup",
            "text": result["response"],
            "weakness": result.get("weakness"),
            "concepts": result.get("concepts"),
        })

    asr = ASRService(on_partial=on_partial, on_final=on_final)
    await asr.connect(session_id)

    try:
        while True:
            audio_chunk = await websocket.receive_bytes()
            await asr.send_audio(session_id, audio_chunk)
    except WebSocketDisconnect:
        pass
    finally:
        await asr.disconnect(session_id)


@router.get("/state/{session_id}")
async def get_state(session_id: str):
    return await orchestrator.get_session_state(session_id)


@router.get("/report/{session_id}")
async def get_report(session_id: str):
    """Returns final interview report with scores, weaknesses, and hire recommendation."""
    state = await orchestrator.get_session_state(session_id)
    history = state.get("history", [])
    weaknesses = state.get("weaknesses", [])
    scores = state.get("scores", {})

    # Aggregate weakness types
    weakness_summary = {}
    for w in weaknesses:
        wtype = w.get("type", "unknown")
        weakness_summary[wtype] = weakness_summary.get(wtype, 0) + 1

    return {
        "session_id": session_id,
        "scores": scores,
        "weakness_summary": weakness_summary,
        "total_questions": len(history),
        "failure_surface": state.get("failure_surface", {}),
        "raw_weaknesses": weaknesses,
    }
