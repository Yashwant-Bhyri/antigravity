import os
import asyncio
from pathlib import Path
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"
    env_local = project_root / ".env.local"
    inherited_env = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("OPENROUTER_", "ANTIGRAVITY_", "TTS_", "CARTESIA_", "ELEVENLABS_"))
    }

    loaded_any = False
    if env_file.exists():
        # Base defaults live in .env.
        load_dotenv(env_file, override=False)
        print(f"[System] Loaded base environment from {env_file}")
        loaded_any = True
    if env_local.exists():
        # Local/runtime overrides must win so key/model rotations can happen in one place
        # without silently losing to stale values in .env.
        load_dotenv(env_local, override=True)
        print(f"[System] Loaded override environment from {env_local}")
        loaded_any = True
    if not loaded_any:
        print("[System] No project-root .env file found; using inherited environment only")
    for key, value in inherited_env.items():
        if value:
            os.environ[key] = value
except ImportError:
    pass  # In Vercel/Docker, environment variables are injected natively; no dotenv needed
except Exception as e:
    print(f"[System] Warning: Error loading dotenv: {e}")
    pass  # In Vercel/Docker, environment variables are injected natively; no dotenv needed

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from backend.api.routes import router, tts_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-generate all filler phrase audio at startup so first interview is instant
    try:
        await tts_service.warm_filler_cache()
    except Exception:
        pass  # non-fatal — will generate lazily on first call

    # Apply tracked Postgres migrations. The recovery loop below retries this if
    # the database is temporarily unavailable during process startup.
    try:
        from backend.db.postgres import init_schema
        await init_schema()
    except Exception:
        pass

    stop_outbox = asyncio.Event()

    async def drain_outbox() -> None:
        from backend.db.postgres import init_schema, is_durability_ready
        from backend.services.provenhire_handoff import process_pending_handoff_deliveries
        while not stop_outbox.is_set():
            try:
                if not await is_durability_ready():
                    await init_schema()
                if await is_durability_ready():
                    await process_pending_handoff_deliveries()
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_outbox.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                continue

    outbox_task = asyncio.create_task(drain_outbox(), name="durability-recovery-outbox")

    async def recover_finalization_jobs() -> None:
        from backend.api.routes import orchestrator
        from backend.db.postgres import claim_finalization_jobs

        while not stop_outbox.is_set():
            try:
                jobs = await claim_finalization_jobs(limit=2)
                for job in jobs:
                    await orchestrator.recover_finalization_job(job)
            except Exception as exc:
                print(f"[FinalizationWorker] recovery sweep failed: {type(exc).__name__}: {exc}")
            try:
                await asyncio.wait_for(stop_outbox.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

    finalization_task = asyncio.create_task(
        recover_finalization_jobs(),
        name="durability-recovery-finalization",
    )
    yield
    stop_outbox.set()
    for task in (outbox_task, finalization_task):
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except Exception:
            task.cancel()
    try:
        from backend.db.postgres import close_pool
        await close_pool()
    except Exception:
        pass


app = FastAPI(
    title="Antigravity — Interview Assessment Engine",
    lifespan=lifespan,
)


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _internal_surfaces_enabled() -> bool:
    return _truthy_env(os.getenv("ANTIGRAVITY_ENABLE_INTERNAL_SURFACES"))


def _internal_route_token() -> str:
    return str(os.getenv("ANTIGRAVITY_INTERNAL_ROUTE_TOKEN") or "").strip()


def _is_internal_api_path(path: str, method: str) -> bool:
    if path.startswith("/api/replay/"):
        return True
    if path.startswith("/api/simulation/"):
        return True
    if path.startswith("/api/admin/"):
        return True
    if path.startswith("/api/phase_one_"):
        return True
    if path in {
        "/api/question_review_feedback",
        "/api/trial_batch_review",
        "/api/sessions",
    }:
        return True
    if path.startswith("/api/trial_review_bundle/"):
        return True
    if path.startswith("/api/llm_audit/"):
        return True
    if method.upper() == "GET" and (
        path.startswith("/api/telemetry/")
        or path.startswith("/api/state/")
    ):
        return True
    return False


async def _readiness_snapshot() -> tuple[dict, int]:
    from backend.db.postgres import get_pool
    from backend.state.session_manager import SessionManager

    checks: dict[str, dict[str, object]] = {}

    openrouter_ok = bool(str(os.getenv("OPENROUTER_API_KEY") or "").strip())
    deepgram_ok = bool(str(os.getenv("DEEPGRAM_API_KEY") or "").strip())
    tts_snapshot = tts_service.status_snapshot()
    tts_ok = bool(tts_snapshot.get("cartesia_configured") or tts_snapshot.get("elevenlabs_configured"))

    checks["openrouter"] = {
        "ok": openrouter_ok,
        "required": True,
        "detail": "configured" if openrouter_ok else "Missing OPENROUTER_API_KEY",
    }
    checks["deepgram"] = {
        "ok": deepgram_ok,
        "required": True,
        "detail": "configured" if deepgram_ok else "Missing DEEPGRAM_API_KEY",
    }
    checks["tts"] = {
        "ok": tts_ok,
        "required": True,
        "provider": tts_snapshot.get("provider"),
        "detail": (
            "configured"
            if tts_ok
            else "Neither CARTESIA_API_KEY nor ELEVENLABS_API_KEY is configured"
        ),
        "snapshot": tts_snapshot,
    }

    redis_ok = False
    redis_detail = ""
    try:
        session_manager = SessionManager()
        redis_ok = bool(await session_manager._redis_call(lambda: session_manager.redis.ping()))
        redis_detail = "pong" if redis_ok else "ping returned falsey result"
        try:
            await session_manager.redis.aclose()
        except Exception:
            pass
    except Exception as exc:
        redis_detail = f"{type(exc).__name__}: {exc}"
    checks["redis"] = {
        "ok": redis_ok,
        "required": True,
        "detail": redis_detail,
    }

    postgres_ok = False
    postgres_detail = ""
    try:
        pool = await get_pool()
        if pool is None:
            postgres_detail = "pool unavailable; DB-backed history/dashboard features degraded"
        else:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            postgres_ok = True
            postgres_detail = "query_ok"
    except Exception as exc:
        postgres_detail = f"{type(exc).__name__}: {exc}"
    checks["postgres"] = {
        "ok": postgres_ok,
        "required": _truthy_env(os.getenv("ANTIGRAVITY_REQUIRE_POSTGRES")),
        "detail": postgres_detail or "not_checked",
    }

    missing_critical = [name for name, item in checks.items() if item.get("required") and not item.get("ok")]
    degraded = [name for name, item in checks.items() if not item.get("required") and not item.get("ok")]
    ready = not missing_critical
    status = "ready" if ready and not degraded else "degraded" if ready else "not_ready"
    payload = {
        "status": status,
        "ready": ready,
        "missing_critical": missing_critical,
        "degraded": degraded,
        "checks": checks,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    return payload, 200 if ready else 503


# Add CORS so the frontend can talk to the backend
_cors_extra = [o.strip() for o in os.getenv("ANTIGRAVITY_CORS_ORIGINS", "").split(",") if o.strip()]
_frontend_url = (os.getenv("FRONTEND_URL") or "").strip()
_allow_origins = _cors_extra or [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:3010",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "http://127.0.0.1:3003",
    "http://127.0.0.1:3010",
    "https://provenhire.in",
    "https://www.provenhire.in",
]
if _frontend_url:
    _allow_origins.append(_frontend_url)
_allow_origins = list(dict.fromkeys(_allow_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_internal_surfaces(request: Request, call_next):
    path = request.url.path
    if not _is_internal_api_path(path, request.method):
        return await call_next(request)
    if _internal_surfaces_enabled():
        return await call_next(request)
    configured_token = _internal_route_token()
    provided_token = request.headers.get("X-Antigravity-Internal-Token", "").strip()
    if configured_token and provided_token == configured_token:
        return await call_next(request)
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "service": "antigravity-backend",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/readinessz")
async def readinessz():
    payload, status_code = await _readiness_snapshot()
    return JSONResponse(status_code=status_code, content=payload)


app.include_router(router, prefix="/api")
