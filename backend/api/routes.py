from fastapi import APIRouter
from pydantic import BaseModel
from backend.services.orchestrator import Orchestrator

router = APIRouter()
orchestrator = Orchestrator()


class StartInterviewRequest(BaseModel):
    resume: str
    github_links: list[str] = []


class SpeechInput(BaseModel):
    session_id: str
    text: str
    audio_chunk: bytes | None = None


@router.post("/start_interview")
async def start_interview(data: StartInterviewRequest):
    session_id = await orchestrator.start_session(data.resume, data.github_links)
    return {"session_id": session_id}


@router.post("/process_speech")
async def process_speech(data: SpeechInput):
    response = await orchestrator.handle_transcript(data.session_id, data.text)
    return response


@router.get("/get_state/{session_id}")
async def get_state(session_id: str):
    state = await orchestrator.get_session_state(session_id)
    return state
