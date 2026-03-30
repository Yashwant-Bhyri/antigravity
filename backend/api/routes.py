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


# ─────────────────────────────────────────────
# INTERVIEW LIFECYCLE
# ─────────────────────────────────────────────

@router.post("/start_interview")
async def start_interview(data: StartInterviewRequest):
    session_id = await orchestrator.start_session(data.resume, data.github_links)
    state = await orchestrator.get_session_state(session_id)
    return {
        "session_id": session_id,
        "opening_question": state["last_question"],
        "sprint": state["current_sprint"],
        "sprint_name": state["sprint_name"],
    }


@router.post("/end_interview/{session_id}")
async def end_interview(session_id: str):
    """
    Called by frontend when candidate clicks 'End Interview' or timer runs out.
    Triggers full evaluation and writes final scores to state.
    """
    final_state = await orchestrator.end_session(session_id)
    evaluation = final_state.get("final_evaluation", {})
    return {
        "session_id": session_id,
        "hire_recommendation": evaluation.get("hire_recommendation", "N/A"),
        "overall_score": evaluation.get("overall_score", 0),
        "summary": evaluation.get("summary", ""),
    }


# ─────────────────────────────────────────────
# REAL-TIME AUDIO STREAM
# ─────────────────────────────────────────────

@router.websocket("/stream/{session_id}")
async def stream_audio(websocket: WebSocket, session_id: str):
    """
    WebSocket for real-time audio from the candidate's microphone.

    Frontend sends:  raw PCM16 audio bytes (16kHz, mono)
    Server sends:    JSON events
      {"type": "transcript_partial", "text": "..."}
      {"type": "transcript_final", "text": "..."}
      {"type": "followup", "text": "...", "weakness": {...}, "sprint": N, "sprint_name": "...", "complete": bool}
      {"type": "sprint_change", "sprint": N, "sprint_name": "..."}
    """
    await websocket.accept()

    async def on_partial(sid: str, text: str):
        await websocket.send_json({"type": "transcript_partial", "text": text})

    async def on_final(sid: str, text: str):
        await websocket.send_json({"type": "transcript_final", "text": text})
        result = await orchestrator.handle_transcript(sid, text)

        # Notify frontend of sprint change so UI can update the header
        prev_sprint = result.get("sprint")

        await websocket.send_json({
            "type": "followup",
            "text": result["response"],
            "weakness": result.get("weakness"),
            "concepts": result.get("concepts"),
            "sprint": result.get("sprint"),
            "sprint_name": result.get("sprint_name"),
            "persona": result.get("persona"),
            "question_count": result.get("question_count"),
            "complete": result.get("complete", False),
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


# ─────────────────────────────────────────────
# TTS
# ─────────────────────────────────────────────

@router.post("/tts")
async def synthesize_speech(data: TTSRequest):
    """HTTP streaming endpoint — returns MP3 audio stream."""
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


# ─────────────────────────────────────────────
# STATE & REPORTING
# ─────────────────────────────────────────────

@router.get("/state/{session_id}")
async def get_state(session_id: str):
    return await orchestrator.get_session_state(session_id)


@router.get("/report/{session_id}")
async def get_report(session_id: str):
    """
    Returns the full interview report.
    If interview is still in progress, returns partial data.
    If complete, includes final evaluation from EvaluationAgent.
    """
    state = await orchestrator.get_session_state(session_id)
    evaluation = state.get("final_evaluation") or {}
    weaknesses = state.get("weaknesses", [])

    weakness_by_type: dict[str, int] = {}
    for w in weaknesses:
        t = w.get("type", "unknown")
        weakness_by_type[t] = weakness_by_type.get(t, 0) + 1

    return {
        "session_id": session_id,
        "complete": state.get("interview_complete", False),
        "total_questions": state.get("question_count", 0),
        # From EvaluationAgent
        "overall_score": evaluation.get("overall_score"),
        "hire_recommendation": evaluation.get("hire_recommendation"),
        "confidence_score": evaluation.get("confidence_score"),
        "summary": evaluation.get("summary"),
        "strengths": evaluation.get("strengths", []),
        "risk_flags": evaluation.get("risk_flags", []),
        "scores": evaluation.get("breakdown", state.get("scores", {})),
        "failure_surface": evaluation.get("failure_surface", state.get("failure_surface", {})),
        # Weakness log
        "weakness_summary": weakness_by_type,
        "raw_weaknesses": weaknesses,
    }
