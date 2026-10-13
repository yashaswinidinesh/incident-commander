from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.models.base import engine
from app.models.models import *  # noqa: F401,F403 — ensures all models registered
from sqlalchemy import text
from app.api.v1.endpoints.incidents import router as incidents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        from app.models.base import Base
        from app.models import models  # noqa
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Incident Commander", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents_router, prefix="/api/v1/incidents", tags=["incidents"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "incident-commander"}
