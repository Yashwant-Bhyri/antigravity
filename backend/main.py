from fastapi import FastAPI
from backend.api.routes import router

app = FastAPI(title="Antigravity — AI Adversarial Interview Engine")
app.include_router(router)
