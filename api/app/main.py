import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import run_migrations
from app.routers import briefs, search, speeches, voice_profiles
from app.vector_store import ensure_collection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_collection()
    # Migrate-on-boot is safe here only because the api is single-replica.
    # Scaling out makes this an explicit deploy step.
    await asyncio.to_thread(run_migrations)
    yield


app = FastAPI(title="writing-style API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_profiles.router)
app.include_router(speeches.router)
app.include_router(search.router)
app.include_router(briefs.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
