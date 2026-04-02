import os
from fastapi import APIRouter
from fastapi.responses import StreamingResponse, Response
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
    entities: list[str] = []  # NER entities extracted by Deepgram during transcription


class PartialRequest(BaseModel):
    session_id: str
    transcript: str
    entities: list[str] = []  # NER entities from current is_final fragment(s)


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
    """
    Browser sends is_final fragments + NER entities while candidate is still speaking.
    Entities fast-path the prefetch — no ConceptAgent LLM call needed.
    """
    await orchestrator.on_partial_transcript(data.session_id, data.transcript, entities=data.entities)
    return {"ok": True}


@router.post("/process_turn")
async def process_turn(data: TurnRequest):
    """
    Browser sends final transcript + NER entities → agents run → follow-up returned.
    Entities extracted by Deepgram during transcription — no extra LLM call needed for concept extraction.
    """
    result = await orchestrator.handle_transcript(data.session_id, data.transcript, entities=data.entities)
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

@router.get("/tts_filler")
async def get_filler():
    """
    Returns a random pre-cached filler phrase as MP3.
    Pre-generated at startup — responds in <10ms after warm-up.
    Frontend calls this IMMEDIATELY when candidate stops speaking,
    before/while the LLM pipeline runs, for true filler-first latency masking.
    """
    from fastapi import HTTPException
    try:
        audio_bytes = await tts_service.get_filler_audio()
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Filler TTS failed: {str(e)[:80]}")


@router.post("/tts")
async def synthesize_speech(data: TTSRequest):
    from fastapi import HTTPException

    # Always use plain stream() — fillers disabled.
    # Collect all chunks from a single ElevenLabs call (never call twice).
    chunks: list[bytes] = []
    try:
        async for chunk in tts_service.stream(data.text):
            if chunk:
                chunks.append(chunk)
        if not chunks:
            raise HTTPException(status_code=502, detail="TTS returned empty audio")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS unavailable: {str(e)[:120]}")

    async def audio_generator():
        for chunk in chunks:
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
