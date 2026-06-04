import os
from pathlib import Path

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
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.api.routes import router, tts_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-generate all filler phrase audio at startup so first interview is instant
    try:
        await tts_service.warm_filler_cache()
    except Exception:
        pass  # non-fatal — will generate lazily on first call

    # Initialise Postgres schema (creates tables if not present) — best-effort
    try:
        from backend.db.postgres import init_schema
        await init_schema()
    except Exception:
        pass  # Postgres unavailable — sessions endpoint will return empty, interviews still work

    yield


app = FastAPI(
    title="Antigravity — Interview Assessment Engine",
    lifespan=lifespan,
)

# Add CORS so the frontend can talk to the backend
_cors_extra = [o.strip() for o in os.getenv("ANTIGRAVITY_CORS_ORIGINS", "").split(",") if o.strip()]
_frontend_url = (os.getenv("FRONTEND_URL") or "").strip()
_allow_origins = _cors_extra or [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "http://127.0.0.1:3003",
    "https://provenhire.in",
    "https://www.provenhire.in",
]
if _frontend_url:
    _allow_origins.append(_frontend_url)
_allow_origins = list(dict.fromkeys(_allow_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
