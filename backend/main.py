from dotenv import load_dotenv
load_dotenv()

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

    # Build RAG question bank index — best-effort, runs in background thread via executor
    try:
        import asyncio
        from backend.rag import question_bank
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, question_bank.load)
    except Exception:
        pass  # RAG unavailable — sprint questions fall back to pure LLM generation

    yield


app = FastAPI(
    title="Antigravity — AI Adversarial Interview Engine",
    lifespan=lifespan,
)

# Add CORS so the frontend can talk to the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
