import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import time
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from backend.services.orchestrator import Orchestrator
from backend.services.interview_telemetry import interview_telemetry
from backend.services.provenhire_handoff import consume_launch_token, notify_handoff_started, notify_handoff_failed
from backend.services.replay_interview_service import replay_interview_service
from backend.services.simulation_service import simulation_service
from backend.services.inventory_simulation_service import inventory_simulation_service
from backend.services.tts_service import TTSService
from backend.services.voice_agent_gateway import VoiceAgentGateway
from backend.models.action_deck import (
    RecoveryDeckRequest,
    SpokenQuestionCommit,
    VoiceCommitTurnRequest,
    VoiceEvent,
)

router = APIRouter()
tts_service = TTSService()
orchestrator = Orchestrator(tts_service=tts_service)
voice_gateway = VoiceAgentGateway(orchestrator)


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _require_turn_id(value: str) -> str:
    turn_id = str(value or "").strip()
    if not turn_id:
        raise HTTPException(status_code=422, detail="turn_id is required for a stable answer identity")
    return turn_id


def _trajectory_preview_opener(area: dict) -> str:
    ladder = area.get("question_ladder") if isinstance(area.get("question_ladder"), list) else []
    for posture in ("frame", "clarify"):
        for item in ladder:
            if isinstance(item, dict) and str(item.get("posture") or "").lower() == posture:
                question = str(item.get("main_question") or "").strip()
                if question:
                    return question
    compat = area.get("legacy_compat") if isinstance(area.get("legacy_compat"), dict) else {}
    return str(compat.get("opener") or area.get("opener") or "").strip()


def _trajectory_preview_dimension_count(area: dict) -> int:
    dims = area.get("assessment_dimensions")
    if not isinstance(dims, list):
        compat = area.get("legacy_compat") if isinstance(area.get("legacy_compat"), dict) else {}
        dims = compat.get("dimensions") if isinstance(compat.get("dimensions"), list) else area.get("dimensions", [])
    return len(dims or [])


class StartInterviewRequest(BaseModel):
    prepared_session_id: str = ""
    resume: str = ""
    github_links: list[str] = Field(default_factory=list)
    target_role: str = ""
    years_experience: str = ""
    prior_assessment_context: dict = Field(default_factory=dict)
    prior_assessment_prompt: str = ""


class PrepareInterviewMapRequest(BaseModel):
    resume: str
    github_links: list[str] = Field(default_factory=list)
    target_role: str = ""
    years_experience: str = ""
    prior_assessment_context: dict = Field(default_factory=dict)
    prior_assessment_prompt: str = ""


class TTSRequest(BaseModel):
    text: str
    session_id: str = ""
    use_filler: bool = True


class TurnRequest(BaseModel):
    session_id: str
    transcript: str
    entities: list[str] = Field(default_factory=list)  # NER entities extracted by Deepgram during transcription
    turn_id: str = ""          # Frontend-generated UUID; echoed back for stale response detection
    revision_of_turn_id: str = ""  # Optional: this final transcript amends an earlier answered turn.
    revision_question: str = ""    # Optional: question text for the amended turn, used by replay/history repair.


class PartialRequest(BaseModel):
    session_id: str
    transcript: str
    entities: list[str] = Field(default_factory=list)  # Best-known entities from the live transcript snapshot
    turn_id: str = ""         # Frontend-generated UUID for the active candidate answer turn
    is_final: bool = True     # Deepgram is_final block vs throttled interim snapshot
    snapshot_seq: int = 0     # Monotonic client-side sequence for stale-snapshot protection


class TelemetryEventRequest(BaseModel):
    session_id: str
    event: str
    source: str = "frontend"
    level: str = "info"
    fields: dict = Field(default_factory=dict)


class ReplayStartRequest(BaseModel):
    case_id: str
    max_turns: int = 0


class ReplayQaCaptureRequest(BaseModel):
    session_id: str
    event_type: str
    payload: dict = Field(default_factory=dict)


class ProvenHireHandoffConsumeRequest(BaseModel):
    token: str


class SimulationStartRequest(BaseModel):
    candidate_context: dict = Field(default_factory=dict)


class SimulationInterviewerTurnRequest(BaseModel):
    session_id: str
    stage_key: str = ""
    note: str = ""
    code: str = ""
    notes: dict[str, str] = Field(default_factory=dict)


class SimulationRunTestsRequest(BaseModel):
    session_id: str
    code: str
    notes: dict[str, str] = Field(default_factory=dict)


class SimulationFinalizeRequest(BaseModel):
    session_id: str
    code: str = ""
    notes: dict[str, str] = Field(default_factory=dict)


class SimulationRealtimeOfferRequest(BaseModel):
    session_id: str
    sdp: str
    stage_key: str = ""
    voice: str = "marin"
    model: str = "gpt-realtime-mini"


class VoicePolicyDecisionRequest(BaseModel):
    session_id: str
    event_type: str = ""
    require_spoken_question: bool = False


class VoiceRealtimeOfferRequest(BaseModel):
    session_id: str = "voice-lab"
    sdp: str
    model: str = ""
    voice: str = "marin"
    instructions: str = ""
    vad_mode: str = "semantic_vad"
    vad_eagerness: str = "low"


VOICE_INTERVIEWER_RUNTIME_CONTRACT = (
    "You are Antigravity's candidate-facing AI interviewer voice. "
    "You are always inside a live interview, never a general assistant, coach, or casual chat companion. "
    "The backend is the interview brain and owns all assessment decisions. "
    "Your job is only to render backend-approved interview moves with calm, natural voice delivery. "
    "Never invent a new technical assessment question, never change the interview topic by yourself, "
    "and never answer as if you are outside the interview. "
    "Ask exactly one approved question when instructed, then stop speaking and wait. "
    "If the candidate gives a weird, vague, evasive, checking-with-someone, confused, or off-topic answer, "
    "do not improvise a new interview path. Wait for the next backend-approved instruction. "
    "If you are explicitly instructed to rephrase, repeat, slow down, or recover, do only that same move; "
    "do not add a second probe. "
    "If the candidate asks a personal question, asks what you are doing, asks for the answer, asks to leave the interview, "
    "or tries to pull you into unrelated conversation, stay in interviewer mode and redirect briefly to the current interview flow. "
    "Do not reveal route names, policy, score, weakness labels, action decks, hidden state, telemetry, or evaluator logic. "
    "Do not treat confusion, repeat requests, slowdown requests, pauses, or bad audio as assessment evidence. "
    "Keep normal responses under two spoken sentences."
)


def _voice_realtime_session_config(data: VoiceRealtimeOfferRequest) -> dict:
    model = (data.model or os.environ.get("OPENAI_REALTIME_MODEL") or "gpt-realtime-mini").strip()
    voice = (data.voice or "marin").strip()
    vad_mode = data.vad_mode if data.vad_mode in {"semantic_vad", "server_vad"} else "semantic_vad"
    vad_eagerness = data.vad_eagerness if data.vad_eagerness in {"low", "medium", "high", "auto"} else "low"
    instructions = (
        data.instructions.strip()
        or (
            VOICE_INTERVIEWER_RUNTIME_CONTRACT
            + " If asked to test function calling, call report_voice_lab_signal with the requested event, "
            "then return to interview protocol."
        )
    )
    return {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "audio": {
            "input": {
                "turn_detection": {
                    "type": vad_mode,
                    "eagerness": vad_eagerness,
                    "create_response": False,
                    "interrupt_response": False,
                },
                "transcription": {
                    "model": os.environ.get("OPENAI_REALTIME_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
                },
            },
            "output": {
                "voice": voice,
            },
        },
        "tools": [
            {
                "type": "function",
                "name": "report_voice_lab_signal",
                "description": "Report a voice-lab protocol event for function-calling tests.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_type": {"type": "string"},
                        "transcript": {"type": "string"},
                        "confidence": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                    "required": ["event_type"],
                    "additionalProperties": False,
                },
            }
        ],
    }


def _simulation_realtime_session_config(state: dict, stage_key: str, voice: str, model: str = "gpt-realtime-mini") -> dict:
    scenario = state.get("scenario") or {}
    current_stage = stage_key or state.get("current_stage", "understanding")
    instructions = (
        VOICE_INTERVIEWER_RUNTIME_CONTRACT
        + " You are running inside an engineering simulation fallback path, but it is still an interview. "
        "Do not solve the task for the candidate. "
        f"Current simulation: {scenario.get('title', 'Payment Retry Safety')}. "
        f"Objective: {scenario.get('objective', '')} "
        f"Current stage: {current_stage}. "
        "When instructed to ask, ask only the provided move. "
        "When the candidate is stuck, wait for backend recovery or an explicit approved recovery instruction."
    )
    return {
        "type": "realtime",
        "model": (model or os.environ.get("OPENAI_REALTIME_MODEL") or "gpt-realtime-mini").strip(),
        "instructions": instructions,
        "audio": {
            "input": {
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "low",
                    "create_response": False,
                    "interrupt_response": False,
                },
                "transcription": {
                    "model": os.environ.get("OPENAI_REALTIME_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
                },
            },
            "output": {
                "voice": voice or "marin",
            },
        },
    }


# ─────────────────────────────────────────────
# ENGINEERING SIMULATION
# ─────────────────────────────────────────────

@router.get("/simulation/voice_status")
async def get_simulation_voice_status():
    return {
        "openai_realtime_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "openai_realtime_model": os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-mini"),
        "gemini_live_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        "gemini_live_model": os.environ.get("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"),
        "deepgram_configured": bool(os.environ.get("DEEPGRAM_API_KEY", "").strip()),
        "deepgram_simulation_model": os.environ.get("DEEPGRAM_SIMULATION_MODEL", "flux-general-en"),
        "tts": tts_service.status_snapshot(),
    }


@router.post("/simulation/start")
async def start_simulation(_: SimulationStartRequest):
    try:
        return await simulation_service.start_session()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not start simulation: {str(e)[:160]}")


@router.get("/simulation/state/{session_id}")
async def get_simulation_state(session_id: str):
    try:
        state = await simulation_service.get_state(session_id)
        return simulation_service.public_state(state)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {session_id}")


@router.get("/simulation/report/{session_id}")
async def get_simulation_report(session_id: str):
    for svc in (simulation_service, inventory_simulation_service):
        try:
            return await svc.get_report(session_id)
        except KeyError:
            continue
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
    raise HTTPException(status_code=404, detail=f"Simulation session not found: {session_id}")


@router.get("/simulation/sessions")
async def list_simulation_sessions():
    try:
        payment, inventory = await asyncio.wait_for(
            asyncio.gather(
                simulation_service.list_sessions(),
                inventory_simulation_service.list_sessions(),
            ),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Simulation session index timed out.")
    combined = payment + inventory
    combined.sort(key=lambda s: s.get("updated_at") or 0, reverse=True)
    return combined


@router.post("/simulation/inventory/start")
async def start_inventory_simulation():
    try:
        return await inventory_simulation_service.start_session()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not start simulation: {str(e)[:160]}")


@router.post("/simulation/inventory/interviewer_turn")
async def inventory_simulation_interviewer_turn(data: SimulationInterviewerTurnRequest):
    try:
        return await inventory_simulation_service.interviewer_turn(
            data.session_id,
            stage_key=data.stage_key,
            note=data.note or "",
            code=data.code or "",
            notes=data.notes or {},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/simulation/inventory/run_tests")
async def run_inventory_simulation_tests(data: SimulationRunTestsRequest):
    try:
        return await inventory_simulation_service.run_tests(
            data.session_id,
            code=data.code,
            notes=data.notes or {},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/simulation/inventory/finalize")
async def finalize_inventory_simulation(data: SimulationFinalizeRequest):
    try:
        return await inventory_simulation_service.finalize(
            data.session_id,
            code=data.code or "",
            notes=data.notes or {},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/simulation/interviewer_turn")
async def simulation_interviewer_turn(data: SimulationInterviewerTurnRequest):
    try:
        return await simulation_service.interviewer_turn(
            data.session_id,
            stage_key=data.stage_key,
            note=data.note,
            code=data.code,
            notes=data.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {data.session_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not update simulation: {str(e)[:160]}")


@router.post("/simulation/run_tests")
async def run_simulation_tests(data: SimulationRunTestsRequest):
    try:
        return await simulation_service.run_tests(
            data.session_id,
            code=data.code,
            notes=data.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {data.session_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Simulation test run failed: {str(e)[:160]}")


@router.post("/simulation/finalize")
async def finalize_simulation(data: SimulationFinalizeRequest):
    try:
        return await simulation_service.finalize(
            data.session_id,
            code=data.code,
            notes=data.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {data.session_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not finalize simulation: {str(e)[:160]}")


@router.post("/simulation/transcribe_audio/{session_id}")
async def transcribe_simulation_audio(session_id: str, request: Request):
    api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="DEEPGRAM_API_KEY is not configured")

    try:
        await simulation_service.get_state(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {session_id}")

    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if len(audio) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file is too large for this prototype")

    media_type = request.headers.get("x-content-type") or request.headers.get("content-type") or "audio/webm"
    requested_model = os.environ.get("DEEPGRAM_SIMULATION_MODEL", "flux-general-en").strip() or "flux-general-en"
    started = time.perf_counter()

    async def _transcribe_flux(model: str) -> str:
        import websockets

        url = f"wss://api.deepgram.com/v2/listen?model={model}"
        turn_transcripts: dict[int, str] = {}
        latest_transcript = ""

        async with websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {api_key}"},
            open_timeout=10,
            max_size=8 * 1024 * 1024,
        ) as websocket:
            async def _receive() -> None:
                nonlocal latest_transcript
                async for raw in websocket:
                    try:
                        message = json.loads(raw)
                    except Exception:
                        continue
                    transcript = str(message.get("transcript") or "").strip()
                    if not transcript and isinstance(message.get("channel"), dict):
                        transcript = str(
                            (message.get("channel", {}).get("alternatives") or [{}])[0].get("transcript") or ""
                        ).strip()
                    if not transcript:
                        continue
                    latest_transcript = transcript
                    turn_index = int(message.get("turn_index", 0) or 0)
                    turn_transcripts[turn_index] = transcript

            receive_task = asyncio.create_task(_receive())
            try:
                chunk_size = 16_000
                chunk_delay = 0.18 if "wav" in media_type.lower() else 0.1
                for offset in range(0, len(audio), chunk_size):
                    await websocket.send(audio[offset:offset + chunk_size])
                    # Flux is a conversational streaming model; pacing containerized
                    # audio near real time produces more reliable turn transcripts
                    # than dumping a full file over the socket as fast as possible.
                    await asyncio.sleep(chunk_delay)
                await websocket.send(json.dumps({"type": "CloseStream"}))
                await asyncio.sleep(3.0)
            finally:
                await websocket.close()
                try:
                    await asyncio.wait_for(receive_task, timeout=2.0)
                except Exception:
                    receive_task.cancel()

        joined = " ".join(turn_transcripts[index] for index in sorted(turn_transcripts)).strip()
        return joined or latest_transcript.strip()

    async def _transcribe_prerecorded(model: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=45.0, write=15.0, pool=20.0)) as client:
            return await client.post(
                f"https://api.deepgram.com/v1/listen?model={model}&smart_format=true&punctuate=true",
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": media_type,
                },
                content=audio,
            )

    model_used = requested_model
    transcript = ""
    if requested_model.startswith("flux-"):
        try:
            transcript = await _transcribe_flux(requested_model)
            if not transcript:
                raise RuntimeError("Deepgram Flux returned an empty transcript")
        except Exception as exc:
            await interview_telemetry.log(
                session_id,
                "simulation.audio_transcription_flux_fallback",
                source="backend.api",
                level="warning",
                detail=str(exc)[:220].replace("\n", " "),
            )
            model_used = "nova-3"
    if not transcript:
        response = await _transcribe_prerecorded(model_used)

        if response.status_code >= 400:
            detail = response.text[:260].replace("\n", " ")
            await interview_telemetry.log(
                session_id,
                "simulation.audio_transcription_failed",
                source="backend.api",
                level="error",
                status=response.status_code,
                detail=detail,
            )
            raise HTTPException(status_code=502, detail=f"Deepgram transcription failed: {detail}")

        payload = response.json()
        transcript = (
            payload.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        ).strip()
    if requested_model.startswith("flux-") and model_used == requested_model and transcript:
        await interview_telemetry.log(
            session_id,
            "simulation.audio_transcription_flux_used",
            source="backend.api",
            model=model_used,
            bytes=len(audio),
        )
    await interview_telemetry.log(
        session_id,
        "simulation.audio_transcribed",
        source="backend.api",
        bytes=len(audio),
        model=model_used,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return {
        "transcript": transcript,
        "provider": "deepgram",
        "model": model_used,
        "media_type": media_type,
        "bytes": len(audio),
    }


@router.post("/simulation/gemini_live_token/{session_id}")
async def create_gemini_live_token(session_id: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")

    try:
        state = await simulation_service.get_state(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {session_id}")

    model = os.environ.get("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025").strip()
    scenario = state.get("scenario") or {}
    stage = state.get("current_stage", "understanding")
    system_instruction = (
        "You are the live interviewer inside an engineering simulation workbench. "
        "Be concise, calm, technically sharp, and candidate-supportive. "
        "Do not reveal the final code solution. Give one small nudge or one focused question at a time. "
        f"Simulation: {scenario.get('title', 'Payment Retry Safety')}. "
        f"Objective: {scenario.get('objective', '')} "
        f"Current stage: {stage}. "
        "Keep every spoken response under 18 seconds."
    )

    try:
        from google import genai

        client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
        now = datetime.now(timezone.utc)
        token = client.auth_tokens.create(
            config={
                "uses": 1,
                "expire_time": now + timedelta(minutes=30),
                "new_session_expire_time": now + timedelta(minutes=1),
                "live_connect_constraints": {
                    "model": model,
                    "config": {
                        "response_modalities": ["AUDIO"],
                        "input_audio_transcription": {},
                        "output_audio_transcription": {},
                        "temperature": 0.55,
                        "system_instruction": system_instruction,
                    },
                },
                "http_options": {"api_version": "v1alpha"},
            }
        )
    except Exception as e:
        await interview_telemetry.log(
            session_id,
            "simulation.gemini_live_token_failed",
            source="backend.api",
            level="error",
            detail=str(e)[:220],
        )
        raise HTTPException(status_code=502, detail=f"Could not create Gemini Live token: {str(e)[:180]}")

    await interview_telemetry.log(
        session_id,
        "simulation.gemini_live_token_created",
        source="backend.api",
        model=model,
    )
    return {
        "token": token.name,
        "model": model,
        "expires_in_seconds": 1800,
        "new_session_expires_in_seconds": 60,
    }


@router.post("/simulation/realtime_offer")
async def create_simulation_realtime_offer(data: SimulationRealtimeOfferRequest):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    if not data.sdp.strip():
        raise HTTPException(status_code=400, detail="SDP offer is required")

    try:
        state = await simulation_service.get_state(data.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {data.session_id}")

    stage_key = data.stage_key or state.get("current_stage", "understanding")
    safety_id = hashlib.sha256(f"simulation:{data.session_id}".encode("utf-8")).hexdigest()
    session_config = _simulation_realtime_session_config(state, stage_key, data.voice, data.model)
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=25.0, write=8.0, pool=20.0)) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={
                "Authorization": f"Bearer {api_key}",
                "OpenAI-Safety-Identifier": safety_id,
            },
            files={
                "sdp": (None, data.sdp, "application/sdp"),
                "session": (None, json.dumps(session_config), "application/json"),
            },
        )

    if response.status_code >= 400:
        detail = response.text[:260].replace("\n", " ")
        await interview_telemetry.log(
            data.session_id,
            "simulation.realtime_offer_failed",
            source="backend.api",
            level="error",
            status=response.status_code,
            detail=detail,
        )
        raise HTTPException(status_code=502, detail=f"OpenAI Realtime offer failed: {detail}")

    await interview_telemetry.log(
        data.session_id,
        "simulation.realtime_offer_created",
        source="backend.api",
        stage=stage_key,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return Response(content=response.text, media_type="application/sdp")


@router.post("/simulation/voice_event")
async def record_simulation_voice_event(data: VoiceEvent):
    try:
        state = await simulation_service.get_state(data.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Simulation session not found: {data.session_id}")

    recorded_at_ms = int(time.time() * 1000)
    event = data.model_dump()
    event["recorded_at_ms"] = recorded_at_ms
    state.setdefault("voice_events", []).append(event)
    state["voice_events"] = state["voice_events"][-300:]
    if data.transcript:
        state["latest_voice_transcript"] = {
            "provider": data.provider,
            "event_type": data.event_type,
            "transcript": data.transcript,
            "is_final": data.is_final,
            "turn_id": data.turn_id,
            "item_id": data.item_id,
            "recorded_at_ms": recorded_at_ms,
        }
    simulation_service._record_local(
        state,
        f"voice.{data.event_type}",
        f"{data.provider} {data.event_type}",
        provider=data.provider,
        turn_id=data.turn_id,
        item_id=data.item_id,
        is_final=data.is_final,
        transcript_chars=len(data.transcript or ""),
        snapshot_seq=data.snapshot_seq,
    )
    await simulation_service._save(state)
    await interview_telemetry.log(
        data.session_id,
        "simulation.voice_event",
        source="backend.api",
        provider=data.provider,
        event_type=data.event_type,
        turn_id=data.turn_id,
        item_id=data.item_id,
        is_final=data.is_final,
        transcript_chars=len(data.transcript or ""),
        snapshot_seq=data.snapshot_seq,
    )
    return {"ok": True, "recorded_at_ms": recorded_at_ms}


# ─────────────────────────────────────────────
# INTERVIEW LIFECYCLE
# ─────────────────────────────────────────────

@router.post("/prepare_interview_map")
async def prepare_interview_map(data: PrepareInterviewMapRequest):
    started = time.perf_counter()
    try:
        session_id = await orchestrator.prepare_session_map(
            data.resume,
            data.github_links,
            target_role=data.target_role,
            years_experience=data.years_experience,
            prior_assessment_context=data.prior_assessment_context,
            prior_assessment_prompt=data.prior_assessment_prompt,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    state = await orchestrator.get_session_state(session_id)
    interview_map = state.get("interview_trajectory_map") or {}
    focus_areas = interview_map.get("focus_areas", []) or []
    validation = state.get("interview_map_validation") or {}
    trajectory_focus_preview = [
        {
            "label": str(area.get("label", "") or ""),
            "focus_key": str(area.get("focus_key", "") or ""),
            "track_source": str(area.get("track_source", "") or ""),
            "track_schema": str(area.get("track_schema", "") or ""),
            "map_schema_version": str(area.get("map_schema_version", "") or ""),
            "primary_question_contract": str(area.get("primary_question_contract", "") or ""),
            "legacy_fields_authority": str(area.get("legacy_fields_authority", "") or ""),
            "llm_branch_count": int(area.get("llm_branch_count", 0) or 0),
            "opener": _trajectory_preview_opener(area),
            "dimension_count": _trajectory_preview_dimension_count(area),
            "resume_snippets": [str(snippet) for snippet in (area.get("resume_snippets") or [])[:2]],
        }
        for area in focus_areas[:4]
    ]
    await interview_telemetry.log(
        session_id,
        "api.prepare_interview_map",
        source="backend.api",
        resume_chars=len(data.resume),
        github_links=len(data.github_links),
        target_role=data.target_role,
        years_experience=data.years_experience,
        focus_areas=len(focus_areas),
        llm_focuses=int(validation.get("llm_focus_count", 0) or 0),
        rich_focuses=int(validation.get("rich_focus_count", 0) or 0),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return {
        "session_id": session_id,
        "map_status": state.get("interview_map_status", ""),
        "map_validation": validation,
        "trajectory_focus_areas": len(focus_areas),
        "trajectory_focus_preview": trajectory_focus_preview,
    }

@router.post("/start_interview")
async def start_interview(data: StartInterviewRequest):
    started = time.perf_counter()
    try:
        if data.prepared_session_id.strip():
            session_id = await orchestrator.start_prepared_session(data.prepared_session_id.strip())
        else:
            session_id = await orchestrator.start_session(
                data.resume,
                data.github_links,
                target_role=data.target_role,
                years_experience=data.years_experience,
                prior_assessment_context=data.prior_assessment_context,
                prior_assessment_prompt=data.prior_assessment_prompt,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    state = await orchestrator.get_session_state(session_id)
    focus_areas = ((state.get("interview_trajectory_map") or {}).get("focus_areas", []) or [])
    trajectory_focus_preview = [
        {
            "label": str(area.get("label", "") or ""),
            "focus_key": str(area.get("focus_key", "") or ""),
            "track_schema": str(area.get("track_schema", "") or ""),
            "map_schema_version": str(area.get("map_schema_version", "") or ""),
            "primary_question_contract": str(area.get("primary_question_contract", "") or ""),
            "legacy_fields_authority": str(area.get("legacy_fields_authority", "") or ""),
            "opener": _trajectory_preview_opener(area),
            "dimension_count": _trajectory_preview_dimension_count(area),
            "resume_snippets": [str(snippet) for snippet in (area.get("resume_snippets") or [])[:2]],
        }
        for area in focus_areas[:3]
    ]
    response = {
        "session_id": session_id,
        "opening_question": state["last_question"],
        "sprint": state["current_sprint"],
        "sprint_name": state["sprint_name"],
        "trajectory_focus_areas": len(focus_areas),
        "trajectory_focus_preview": trajectory_focus_preview,
    }
    await interview_telemetry.log(
        session_id,
        "api.start_interview",
        source="backend.api",
        resume_chars=len(data.resume),
        github_links=len(data.github_links),
        target_role=data.target_role,
        years_experience=data.years_experience,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return response


@router.post("/provenhire_handoff/consume")
async def consume_provenhire_handoff(data: ProvenHireHandoffConsumeRequest):
    started = time.perf_counter()
    token = data.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Launch token is required")

    try:
        handoff = await consume_launch_token(token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not validate ProvenHire handoff: {str(e)[:160]}")

    handoff_id = str(handoff.get("handoff_id") or "")
    existing_session_id = str(handoff.get("antigravity_session_id") or "")
    if existing_session_id:
        try:
            state = await orchestrator.get_session_state(existing_session_id)
            return {
                "handoff_id": handoff_id,
                "session_id": existing_session_id,
                "opening_question": state.get("last_question", ""),
                "sprint": state.get("current_sprint", 1),
                "sprint_name": state.get("sprint_name", ""),
                "return_url": handoff.get("return_url") or "",
                "resumed": True,
            }
        except KeyError:
            pass

    try:
        prepared_session_id = await orchestrator.prepare_session_map(
            str(handoff.get("resume") or ""),
            [str(link) for link in (handoff.get("github_links") or [])],
            target_role=str(handoff.get("target_role") or ""),
            years_experience=str(handoff.get("years_experience") or ""),
            prior_assessment_context=handoff.get("prior_assessment_context") or {},
            prior_assessment_prompt=str(handoff.get("prior_assessment_prompt") or ""),
        )
        session_id = await orchestrator.start_prepared_session(prepared_session_id)
        state = await orchestrator.get_session_state(session_id)
        state["external_handoff"] = {
            "provider": "provenhire",
            "handoff_id": handoff_id,
            "provenhire_interview_id": handoff.get("provenhire_interview_id") or "",
            "return_url": handoff.get("return_url") or "",
        }
        await orchestrator.session_manager.save_state(session_id, state)
        asyncio.create_task(notify_handoff_started(handoff_id, session_id))
    except Exception as e:
        if handoff_id:
            try:
                asyncio.create_task(notify_handoff_failed(handoff_id, "none", str(e)[:500]))
            except Exception:
                pass
        raise HTTPException(status_code=503, detail=f"Could not start Antigravity handoff: {str(e)[:160]}")

    await interview_telemetry.log(
        session_id,
        "api.provenhire_handoff_consume",
        source="backend.api",
        handoff_id=handoff_id,
        target_role=str(handoff.get("target_role") or ""),
        years_experience=str(handoff.get("years_experience") or ""),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return {
        "handoff_id": handoff_id,
        "session_id": session_id,
        "opening_question": state.get("last_question", ""),
        "sprint": state.get("current_sprint", 1),
        "sprint_name": state.get("sprint_name", ""),
        "return_url": handoff.get("return_url") or "",
        "resumed": False,
    }


@router.get("/interview_map_status/{session_id}")
async def get_interview_map_status(session_id: str):
    try:
        state = await orchestrator.get_session_state(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    interview_map = state.get("interview_trajectory_map") or {}
    focus_areas = interview_map.get("focus_areas", []) or []
    return {
        "session_id": session_id,
        "map_status": state.get("interview_map_status", ""),
        "map_error": state.get("interview_map_error", ""),
        "map_validation": state.get("interview_map_validation", {}),
        "trajectory_focus_areas": len(focus_areas),
        "trajectory_focus_preview": [
            {
                "label": str(area.get("label", "") or ""),
                "focus_key": str(area.get("focus_key", "") or ""),
                "track_source": str(area.get("track_source", "") or ""),
                "llm_branch_count": int(area.get("llm_branch_count", 0) or 0),
            }
            for area in focus_areas[:4]
        ],
    }


@router.get("/deepgram_token")
async def get_deepgram_token():
    """Returns the Deepgram API key so the browser SDK can connect directly.
    Safe for this internal dev app — never expose in a public deployment."""
    return {"token": os.environ["DEEPGRAM_API_KEY"]}


@router.post("/partial_transcript")
async def partial_transcript(data: PartialRequest):
    """
    Browser sends throttled live transcript snapshots while the candidate is speaking.
    These are speculative-only: they help prep the best available follow-up, but never
    become canonical interview history or evaluation input.
    """
    started = time.perf_counter()
    turn_id = _require_turn_id(data.turn_id)
    if replay_interview_service.is_replay_session(data.session_id):
        try:
            result = await replay_interview_service.partial_transcript(
                data.session_id,
                data.transcript,
                entities=data.entities,
                turn_id=turn_id,
                is_final=data.is_final,
                snapshot_seq=data.snapshot_seq,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Replay session not found: {data.session_id}")
        await interview_telemetry.log(
            data.session_id,
            "api.partial_transcript",
            source="backend.api",
            turn_id=turn_id,
            is_final=data.is_final,
            snapshot_seq=data.snapshot_seq,
            transcript_chars=len(data.transcript),
            transcript_words=len(data.transcript.split()),
            entities_count=len(data.entities),
            replay=True,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return result

    await orchestrator.on_partial_transcript(
        data.session_id,
        data.transcript,
        entities=data.entities,
        turn_id=turn_id,
        is_final=data.is_final,
        snapshot_seq=data.snapshot_seq,
    )
    await interview_telemetry.log(
        data.session_id,
        "api.partial_transcript",
        source="backend.api",
        turn_id=turn_id,
        is_final=data.is_final,
        snapshot_seq=data.snapshot_seq,
        transcript_chars=len(data.transcript),
        transcript_words=len(data.transcript.split()),
        entities_count=len(data.entities),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return {"ok": True}


@router.post("/process_turn")
async def process_turn(data: TurnRequest):
    """
    Browser sends final transcript + NER entities → agents run → follow-up returned.
    Entities extracted by Deepgram during transcription — no extra LLM call needed for concept extraction.
    """
    started = time.perf_counter()
    turn_id = _require_turn_id(data.turn_id)
    if replay_interview_service.is_replay_session(data.session_id):
        try:
            result = await replay_interview_service.process_turn(
                data.session_id,
                data.transcript,
                entities=data.entities,
                turn_id=turn_id,
                revision_of_turn_id=data.revision_of_turn_id,
                revision_question=data.revision_question,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Replay session not found: {data.session_id}")
        await interview_telemetry.log(
            data.session_id,
            "api.process_turn",
            source="backend.api",
            turn_id=turn_id,
            transcript_chars=len(data.transcript),
            transcript_words=len(data.transcript.split()),
            entities_count=len(data.entities),
            route_kind=result.get("route_kind"),
            complete=bool(result.get("complete")),
            question_count=result.get("question_count"),
            replay=True,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return result

    result = await orchestrator.handle_transcript(data.session_id, data.transcript, entities=data.entities, turn_id=turn_id)
    await interview_telemetry.log(
        data.session_id,
        "api.process_turn",
        source="backend.api",
        turn_id=turn_id,
        transcript_chars=len(data.transcript),
        transcript_words=len(data.transcript.split()),
        entities_count=len(data.entities),
        route_kind=result.get("route_kind"),
        complete=bool(result.get("complete")),
        question_count=result.get("question_count"),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return result


@router.get("/voice/action_deck/{session_id}")
async def voice_action_deck(session_id: str, turn_id: str = ""):
    """
    Compile the compact backend-approved ActionDeck that Realtime is allowed to see.
    This is the only interview-intelligence payload for voice mode.
    """
    try:
        return await voice_gateway.action_deck(session_id, turn_id=turn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.post("/voice/policy_decision")
async def voice_policy_decision(data: VoicePolicyDecisionRequest):
    """Return the Voice Policy Kernel's decision for the current deck/state."""
    try:
        return await voice_gateway.policy_decision(
            data.session_id,
            event_type=data.event_type,
            require_spoken_question=data.require_spoken_question,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {data.session_id}")


@router.post("/voice/spoken_question")
async def voice_spoken_question(data: SpokenQuestionCommit):
    """
    Commit the exact wording Realtime spoke before a candidate answer can be evaluated.
    The evaluator follows this committed wording, not a stale backend draft.
    """
    try:
        result = await voice_gateway.spoken_question(data)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {data.session_id}")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/voice/event")
async def voice_event(data: VoiceEvent):
    """
    Record voice-provider events. Partial transcripts are speculative-only and never
    mutate evaluator state.
    """
    try:
        return await voice_gateway.event(data)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {data.session_id}")


@router.post("/voice/commit_turn")
async def voice_commit_turn(data: VoiceCommitTurnRequest):
    """
    Commit a final Realtime transcript. Assessment commits are blocked unless the
    matching spoken question has already been committed.
    """
    data.turn_id = _require_turn_id(data.turn_id)
    try:
        result = await voice_gateway.commit_turn(data)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {data.session_id}")
    if result.get("blocked"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/voice/recovery_deck")
async def voice_recovery_deck(data: RecoveryDeckRequest):
    """Return a formal recovery deck for interruption, unclear audio, policy blocks, or degraded state."""
    try:
        return await voice_gateway.recovery_deck(data)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {data.session_id}")


@router.get("/voice/status")
async def voice_status():
    """Expose voice-lab provider readiness without leaking credentials."""
    return {
        "openai_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "deepgram_configured": bool(os.environ.get("DEEPGRAM_API_KEY", "").strip()),
        "default_realtime_model": os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-mini"),
        "realtime_models": ["gpt-realtime-mini", "gpt-realtime-2", "gpt-realtime"],
        "default_transcribe_model": os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
        "transcribe_models": ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
        "realtime_transcription_model": os.environ.get("OPENAI_REALTIME_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
    }


@router.post("/voice/openai/realtime_offer")
async def voice_openai_realtime_offer(data: VoiceRealtimeOfferRequest):
    """Create an OpenAI Realtime WebRTC SDP answer for the isolated voice lab."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    if not data.sdp.strip():
        raise HTTPException(status_code=400, detail="SDP offer is required")

    session_id = data.session_id or "voice-lab"
    safety_id = hashlib.sha256(f"voice-lab:{session_id}".encode("utf-8")).hexdigest()
    session_config = _voice_realtime_session_config(data)
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=25.0, write=8.0, pool=20.0)) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={
                "Authorization": f"Bearer {api_key}",
                "OpenAI-Safety-Identifier": safety_id,
            },
            files={
                "sdp": (None, data.sdp, "application/sdp"),
                "session": (None, json.dumps(session_config), "application/json"),
            },
        )

    if response.status_code >= 400:
        detail = response.text[:260].replace("\n", " ")
        await interview_telemetry.log(
            session_id,
            "voice_lab.realtime_offer_failed",
            source="backend.api",
            level="error",
            status=response.status_code,
            detail=detail,
            model=session_config.get("model"),
        )
        raise HTTPException(status_code=502, detail=f"OpenAI Realtime offer failed: {detail}")

    await interview_telemetry.log(
        session_id,
        "voice_lab.realtime_offer_created",
        source="backend.api",
        model=session_config.get("model"),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return Response(content=response.text, media_type="application/sdp")


@router.post("/voice/openai/transcribe_audio/{session_id}")
async def voice_openai_transcribe_audio(session_id: str, request: Request, model: str = ""):
    """Transcribe a captured mic sample through OpenAI's batch transcription endpoint."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if len(audio) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds OpenAI transcription upload limits")

    selected_model = (model or os.environ.get("OPENAI_TRANSCRIBE_MODEL") or "gpt-4o-mini-transcribe").strip()
    if selected_model not in {"gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"}:
        raise HTTPException(status_code=400, detail=f"Unsupported transcription model: {selected_model}")

    media_type = request.headers.get("x-content-type") or request.headers.get("content-type") or "audio/webm"
    filename = request.headers.get("x-filename") or "voice-lab-sample.webm"
    prompt = request.headers.get("x-transcription-prompt") or (
        "Technical interview voice-lab audio. Preserve product, analytics, engineering, and model names."
    )
    started = time.perf_counter()

    files = {
        "file": (filename, audio, media_type),
        "model": (None, selected_model),
        "response_format": (None, "json"),
    }
    if selected_model != "whisper-1":
        files["prompt"] = (None, prompt)

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=45.0, write=20.0, pool=20.0)) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
        )

    if response.status_code >= 400:
        detail = response.text[:260].replace("\n", " ")
        await interview_telemetry.log(
            session_id,
            "voice_lab.openai_transcribe_failed",
            source="backend.api",
            level="error",
            status=response.status_code,
            detail=detail,
            model=selected_model,
        )
        raise HTTPException(status_code=502, detail=f"OpenAI transcription failed: {detail}")

    payload = response.json()
    transcript = str(payload.get("text") or "").strip()
    await interview_telemetry.log(
        session_id,
        "voice_lab.openai_transcribed",
        source="backend.api",
        model=selected_model,
        bytes=len(audio),
        transcript_chars=len(transcript),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return {
        "transcript": transcript,
        "provider": "openai",
        "model": selected_model,
        "media_type": media_type,
        "bytes": len(audio),
        "raw": payload,
    }


@router.post("/end_interview/{session_id}")
async def end_interview(session_id: str):
    started = time.perf_counter()
    if replay_interview_service.is_replay_session(session_id):
        try:
            response = await replay_interview_service.end_interview(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Replay session not found: {session_id}")
        await interview_telemetry.log(
            session_id,
            "api.end_interview",
            source="backend.api",
            question_count=response.get("question_count", 0),
            hire_recommendation=response.get("hire_recommendation"),
            overall_score=response.get("overall_score"),
            replay=True,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response

    try:
        final_state = await orchestrator.start_finalization_background(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    evaluation = final_state.get("final_evaluation") or {}
    response = {
        "session_id": session_id,
        "complete": bool(final_state.get("interview_complete")),
        "report_ready": bool(final_state.get("report_ready")),
        "finalization_status": final_state.get("finalization_status", "running"),
        "hire_recommendation": evaluation.get("hire_recommendation", "N/A"),
        "overall_score": evaluation.get("overall_score", 0),
        "summary": evaluation.get("summary", ""),
    }
    await interview_telemetry.log(
        session_id,
        "api.end_interview",
        source="backend.api",
        question_count=final_state.get("question_count", 0),
        history_len=len(final_state.get("history", [])),
        hire_recommendation=evaluation.get("hire_recommendation"),
        overall_score=evaluation.get("overall_score"),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return response


# ─────────────────────────────────────────────
# TTS
# ─────────────────────────────────────────────

@router.get("/tts_filler")
async def get_filler():
    """
    Returns a random pre-cached filler phrase from the release-safe default pool.
    Pre-generated at startup — responds in <10ms after warm-up.
    """
    from fastapi import HTTPException
    started = time.perf_counter()
    try:
        phrase, audio_bytes, media_type, provider_used = await tts_service.get_filler_payload()
        await interview_telemetry.log(
            "system",
            "api.tts_filler",
            source="backend.api",
            provider=provider_used,
            media_type=media_type,
            text=phrase,
            audio_bytes=len(audio_bytes),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={"X-Filler-Text": phrase, "X-TTS-Provider": provider_used},
        )
    except Exception as e:
        print(f"[TTS] Filler generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Filler TTS failed: {str(e)[:80]}")


@router.get("/tts_health")
async def get_tts_health():
    return tts_service.status_snapshot()


@router.post("/telemetry")
async def record_telemetry_event(data: TelemetryEventRequest):
    await interview_telemetry.log(
        data.session_id,
        data.event,
        source=data.source,
        level=data.level,
        **(data.fields or {}),
    )
    return {"ok": True}


@router.get("/telemetry/{session_id}")
async def get_telemetry(session_id: str, limit: int = 400):
    return await interview_telemetry.summarize(session_id, limit=limit)


@router.get("/replay/cases")
async def list_replay_cases():
    return await replay_interview_service.list_cases()


@router.post("/replay/start")
async def start_replay_case(data: ReplayStartRequest):
    try:
        return await replay_interview_service.start_case(data.case_id, max_turns=data.max_turns)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Replay case not found: {data.case_id}")


@router.post("/replay/qa_capture")
async def record_replay_qa_capture(data: ReplayQaCaptureRequest):
    try:
        return await replay_interview_service.record_capture(data.session_id, data.event_type, data.payload)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Replay session not found: {data.session_id}")


@router.get("/replay/qa_report/{session_id}")
async def get_replay_qa_report(session_id: str, write_files: bool = True):
    try:
        return await replay_interview_service.qa_report(session_id, write_files=write_files)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Replay session not found: {session_id}")


@router.post("/tts")
async def synthesize_speech(data: TTSRequest):
    from fastapi import HTTPException

    started = time.perf_counter()

    # Fast path: return pre-generated audio if available
    if data.session_id:
        cached = tts_service.get_prepped(data.session_id, data.text)
        if cached:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            print(f"[TTS] Cache served in {elapsed_ms}ms")
            audio_bytes, media_type, provider_used = cached
            await interview_telemetry.log(
                data.session_id,
                "api.tts",
                source="backend.api",
                text_chars=len(data.text),
                source_kind="prepped",
                provider=provider_used,
                media_type=media_type,
                audio_bytes=len(audio_bytes),
                elapsed_ms=elapsed_ms,
            )
            return Response(
                content=audio_bytes,
                media_type=media_type,
                headers={
                    "Cache-Control": "no-cache",
                    "X-TTS-Source": "prepped",
                    "X-TTS-Provider": provider_used,
                },
            )

    # Slow path: live synthesis
    import asyncio as _asyncio
    try:
        audio_bytes, media_type, provider_used = await tts_service.synthesize(data.text)
        if not audio_bytes:
            print(f"[TTS] Provider {tts_service.provider} returned zero bytes for text: '{data.text[:30]}...'")
            raise HTTPException(status_code=502, detail="TTS returned empty audio")
    except HTTPException:
        raise
    except _asyncio.CancelledError:
        # Client disconnected or worker is shutting down (e.g. reload).
        # Re-raise so uvicorn handles the cancellation cleanly — do NOT wrap in 502.
        print(f"[TTS] Request cancelled (client disconnect or server reload)")
        await interview_telemetry.log(
            data.session_id or "system",
            "api.tts_cancelled",
            source="backend.api",
            level="warn",
            text_chars=len(data.text),
        )
        raise
    except Exception as e:
        import traceback
        print(f"[TTS] Synthesis failed — provider={tts_service.provider}, type={type(e).__name__}, msg={str(e)[:300]}")
        traceback.print_exc()
        await interview_telemetry.log(
            data.session_id or "system",
            "api.tts_failed",
            source="backend.api",
            level="error",
            text_chars=len(data.text),
            provider=tts_service.provider,
            error_type=type(e).__name__,
            error=str(e)[:300],
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        raise HTTPException(status_code=502, detail=f"TTS unavailable: {str(e)[:120]}")

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    print(f"[TTS] Live synthesis via provider={provider_used} in {elapsed_ms}ms ({len(audio_bytes)} bytes)")
    await interview_telemetry.log(
        data.session_id or "system",
        "api.tts",
        source="backend.api",
        text_chars=len(data.text),
        source_kind="live",
        provider=provider_used,
        media_type=media_type,
        audio_bytes=len(audio_bytes),
        elapsed_ms=elapsed_ms,
    )

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache",
            "X-TTS-Source": "live",
            "X-TTS-Provider": provider_used,
        },
    )


# ─────────────────────────────────────────────
# STATE & REPORTING
# ─────────────────────────────────────────────

@router.get("/sessions")
async def get_sessions():
    """All completed interviews for recruiter dashboard."""
    from backend.db.postgres import list_sessions
    rows = await list_sessions()
    result = []
    for r in rows:
        # Unpack full_report JSONB so dashboard fields are top-level
        full_report = r.get("full_report") or {}
        if isinstance(full_report, str):
            try:
                full_report = json.loads(full_report)
            except json.JSONDecodeError:
                full_report = {}
        if not isinstance(full_report, dict):
            full_report = {}
        row = {**r, **full_report}
        # Top-level columns win over full_report on name collision for stable fields
        row["session_id"] = r.get("session_id")
        row["hire_recommendation"] = r.get("hire_recommendation") or full_report.get("hire_recommendation")
        row["overall_score"] = r.get("overall_score") or full_report.get("overall_score")
        row["sprint_reached"] = r.get("sprint_reached") or full_report.get("sprint_reached")
        row["duration_minutes"] = r.get("duration_minutes") or full_report.get("duration_minutes")
        row["resume_snippet"] = r.get("resume_snippet") or full_report.get("resume_snippet")
        row["total_questions"] = row.get("total_questions") or 0
        row["scores"] = row.get("scores") if isinstance(row.get("scores"), dict) else {}
        row["weakness_summary"] = row.get("weakness_summary") if isinstance(row.get("weakness_summary"), dict) else {}
        row["raw_weaknesses"] = row.get("raw_weaknesses") if isinstance(row.get("raw_weaknesses"), list) else []
        row["failure_surface"] = row.get("failure_surface") if isinstance(row.get("failure_surface"), dict) else {}
        row["coverage_portrait"] = _as_dict(row.get("coverage_portrait"))
        row["coverage_score"] = row["coverage_portrait"].get("coverage_score")
        row["coverage_verdict_advisory"] = row.get("coverage_verdict_advisory")
        row["candidate_name"] = row.get("candidate_name") or full_report.get("candidate_name") or ""
        row["verdict_basis"] = row.get("verdict_basis")
        row["verdict_confidence_basis"] = row.get("verdict_confidence_basis")
        if hasattr(row.get("created_at"), "isoformat"):
            row["created_at"] = row["created_at"].isoformat()
        result.append(row)
    return result


@router.get("/state/{session_id}")
async def get_state(session_id: str):
    if replay_interview_service.is_replay_session(session_id):
        try:
            return await replay_interview_service.get_state(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Replay session not found: {session_id}")

    try:
        return await orchestrator.get_session_state(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.get("/report/{session_id}")
async def get_report(session_id: str):
    if replay_interview_service.is_replay_session(session_id):
        try:
            state = await replay_interview_service.get_state(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Replay session not found: {session_id}")
        evaluation = _as_dict(state.get("final_evaluation"))
        evaluation.setdefault("session_id", session_id)
        evaluation.setdefault("complete", bool(state.get("interview_complete")))
        evaluation.setdefault("candidate_name", _as_dict(state.get("parsed_resume")).get("name", "Candidate"))
        evaluation.setdefault("total_questions", state.get("question_count", 0))
        evaluation.setdefault("summary", evaluation.get("summary", "Replay report loaded from saved artifact."))
        evaluation.setdefault("schema_version", evaluation.get("schema_version", "replay_report"))
        evaluation.setdefault("replay", True)
        return evaluation

    try:
        state = await orchestrator.get_session_state(session_id)
    except KeyError:
        # Redis expired or service restarted — try Postgres durable store before 404ing.
        from backend.db.postgres import get_session_report
        pg_report = await get_session_report(session_id)
        if pg_report:
            pg_report.setdefault("session_id", session_id)
            pg_report.setdefault("complete", True)
            pg_report.setdefault("candidate_name", "")
            pg_report.setdefault("total_questions", 0)
            pg_report.setdefault("strengths", [])
            pg_report.setdefault("risk_flags", [])
            pg_report.setdefault("untested_dimensions", [])
            pg_report.setdefault("scores", {})
            pg_report.setdefault("failure_surface", {})
            pg_report.setdefault("weakness_summary", {})
            pg_report.setdefault("raw_weaknesses", [])
            pg_report.setdefault("claim_credibility_risk", {"level": "not_tested", "detail": ""})
            pg_report.setdefault("coverage_portrait", None)
            pg_report.setdefault("coverage_verdict_advisory", None)
            pg_report.setdefault("verdict_basis", None)
            pg_report.setdefault("verdict_confidence_basis", None)
            pg_report.setdefault("schema_version", pg_report.get("schema_version", "legacy_report"))
            pg_report.setdefault("confidence_band", None)
            pg_report.setdefault("coverage_gate", None)
            pg_report.setdefault("interview_quality", None)
            pg_report.setdefault("role_fit_profile", None)
            pg_report.setdefault("ability_profile", None)
            pg_report.setdefault("resume_claim_calibration", None)
            pg_report.setdefault("lens_findings", None)
            pg_report.setdefault("tested_strengths", [])
            pg_report.setdefault("tested_risks", [])
            pg_report.setdefault("claim_findings", [])
            pg_report.setdefault("recommended_followups", [])
            pg_report.setdefault("candidate_safe_summary", pg_report.get("summary"))
            pg_report.setdefault("recruiter_summary", pg_report.get("summary"))
            pg_report.setdefault("review_reconciliation", None)
            return pg_report
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    evaluation = _as_dict(state.get("final_evaluation"))
    report_ready = bool(state.get("report_ready") and evaluation)
    weaknesses = _as_list(state.get("weaknesses"))

    weakness_by_type: dict[str, int] = {}
    for w in weaknesses:
        if isinstance(w, dict):
            t = str(w.get("type", "unknown") or "unknown")
        else:
            t = "unknown"
        weakness_by_type[t] = weakness_by_type.get(t, 0) + 1

    _parsed_resume = _as_dict(state.get("parsed_resume"))
    candidate_name = str(_parsed_resume.get("candidate_name") or "").strip()

    return {
        "session_id": session_id,
        "complete": report_ready,
        "interview_complete": state.get("interview_complete", False),
        "report_ready": report_ready,
        "finalization_status": state.get("finalization_status", "idle"),
        "finalization_error": state.get("finalization_error", ""),
        "candidate_name": candidate_name,
        "target_role": state.get("target_role", ""),
        "years_experience": state.get("years_experience", ""),
        "total_questions": state.get("question_count", 0),
        "overall_score": evaluation.get("overall_score"),
        "hire_recommendation": evaluation.get("hire_recommendation"),
        "confidence_score": evaluation.get("confidence_score"),
        "schema_version": evaluation.get("schema_version", "legacy_report"),
        "confidence_band": evaluation.get("confidence_band"),
        "summary": evaluation.get("summary"),
        "strengths": evaluation.get("strengths", []),
        "risk_flags": evaluation.get("risk_flags", []),
        "untested_dimensions": evaluation.get("untested_dimensions", []),
        "claim_credibility_risk": evaluation.get("claim_credibility_risk", {"level": "not_tested", "detail": ""}),
        "coverage_gate": evaluation.get("coverage_gate"),
        "interview_quality": evaluation.get("interview_quality"),
        "role_fit_profile": evaluation.get("role_fit_profile"),
        "ability_profile": evaluation.get("ability_profile"),
        "resume_claim_calibration": evaluation.get("resume_claim_calibration"),
        "lens_findings": evaluation.get("lens_findings"),
        "tested_strengths": evaluation.get("tested_strengths", []),
        "tested_risks": evaluation.get("tested_risks", []),
        "claim_findings": evaluation.get("claim_findings", []),
        "recommended_followups": evaluation.get("recommended_followups", []),
        "candidate_safe_summary": evaluation.get("candidate_safe_summary", evaluation.get("summary")),
        "recruiter_summary": evaluation.get("recruiter_summary", evaluation.get("summary")),
        "review_reconciliation": evaluation.get("review_reconciliation"),
        "scores": evaluation.get("breakdown", state.get("scores", {})),
        "failure_surface": evaluation.get("failure_surface", state.get("failure_surface", {})),
        "weakness_summary": weakness_by_type,
        "raw_weaknesses": weaknesses,
        "coverage_portrait": evaluation.get("coverage_portrait"),
        "coverage_verdict_advisory": evaluation.get("coverage_verdict_advisory"),
        "verdict_basis": evaluation.get("verdict_basis"),
        "verdict_confidence_basis": evaluation.get("verdict_confidence_basis"),
    }


@router.get("/admin/redis-dump")
async def redis_dump(request: Request):
    """Admin endpoint — scans all Redis keys and returns live session data."""
    _admin_secret = os.environ.get("ANTIGRAVITY_ADMIN_SECRET", "") or os.environ.get("ANTIGRAVITY_WEBHOOK_SECRET", "")
    _provided = request.headers.get("X-Admin-Secret", "")
    if not _admin_secret:
        raise HTTPException(status_code=503, detail="Admin endpoint not configured")
    if not hmac.compare_digest(_admin_secret, _provided):
        raise HTTPException(status_code=401, detail="Unauthorized")
    import redis.asyncio as aioredis
    import json as _json

    redis_url = (
        os.environ.get("KV_URL")
        or os.environ.get("REDIS_URL")
        or os.environ.get("STORAGE_URL")
        or "redis://localhost:6379"
    )
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        keys = []
        async for key in r.scan_iter("*", count=200):
            keys.append(key)

        results = []
        for key in keys:
            try:
                raw = await r.get(key)
                ttl = await r.ttl(key)
                if raw is None:
                    continue
                try:
                    data = _json.loads(raw)
                except Exception:
                    data = raw
                results.append({"key": key, "ttl_seconds": ttl, "data": data})
            except Exception as e:
                results.append({"key": key, "error": str(e)})

        return {"total_keys": len(results), "sessions": results}
    finally:
        await r.aclose()
