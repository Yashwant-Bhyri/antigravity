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
