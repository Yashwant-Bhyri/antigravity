import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.services.orchestrator import Orchestrator
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


class TurnRequest(BaseModel):
    session_id: str
    transcript: str


class PartialRequest(BaseModel):
    session_id: str
    transcript: str


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


@router.get("/deepgram_token")
async def get_deepgram_token():
    """Returns the Deepgram API key so the browser SDK can connect directly.
    Safe for this internal dev app — never expose in a public deployment."""
    return {"token": os.environ["DEEPGRAM_API_KEY"]}


@router.post("/partial_transcript")
async def partial_transcript(data: PartialRequest):
    """Browser sends partial transcripts for predictive prefetch (fire-and-forget)."""
    await orchestrator.on_partial_transcript(data.session_id, data.transcript)
    return {"ok": True}


@router.post("/process_turn")
async def process_turn(data: TurnRequest):
    """
    Browser sends final transcript → agents run → follow-up returned.
    This replaces the audio WebSocket relay entirely.
    Clean, simple, low latency.
    """
    result = await orchestrator.handle_transcript(data.session_id, data.transcript)
    return result


@router.post("/end_interview/{session_id}")
async def end_interview(session_id: str):
    final_state = await orchestrator.end_session(session_id)
    evaluation = final_state.get("final_evaluation", {})
    return {
        "session_id": session_id,
        "hire_recommendation": evaluation.get("hire_recommendation", "N/A"),
        "overall_score": evaluation.get("overall_score", 0),
        "summary": evaluation.get("summary", ""),
    }


# ─────────────────────────────────────────────
# TTS
# ─────────────────────────────────────────────

@router.post("/tts")
async def synthesize_speech(data: TTSRequest):
    from fastapi import HTTPException

    try:
        gen = tts_service.stream_with_filler(data.text) if data.use_filler else tts_service.stream(data.text)
        first_chunk = None
        async for chunk in gen:
            if chunk:
                first_chunk = chunk
                break
        if first_chunk is None:
            raise HTTPException(status_code=502, detail="TTS returned empty audio")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS unavailable: {str(e)[:120]}")

    async def audio_generator():
        yield first_chunk
        stream = tts_service.stream_with_filler(data.text) if data.use_filler else tts_service.stream(data.text)
        async for chunk in stream:
            if chunk:
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
        "overall_score": evaluation.get("overall_score"),
        "hire_recommendation": evaluation.get("hire_recommendation"),
        "confidence_score": evaluation.get("confidence_score"),
        "summary": evaluation.get("summary"),
        "strengths": evaluation.get("strengths", []),
        "risk_flags": evaluation.get("risk_flags", []),
        "scores": evaluation.get("breakdown", state.get("scores", {})),
        "failure_surface": evaluation.get("failure_surface", state.get("failure_surface", {})),
        "weakness_summary": weakness_by_type,
        "raw_weaknesses": weaknesses,
    }
