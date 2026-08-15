import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent import chat_agent
from app.config import settings
from app.db import run_migrations
from app.routers import search, speeches, voice_profiles
from app.vector_store import ensure_collection

logging.basicConfig(level=logging.INFO)

# In-memory per-session conversation history. Single-process, non-persistent —
# fine for one API replica; move to Redis/a DB keyed by session_id if the API
# is ever scaled out or needs restart-durability.
_SESSIONS: dict[str, list] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_collection()
    # Migrate-on-boot is safe here only because the api is single-replica (see
    # the _SESSIONS note above). Scaling out makes this an explicit deploy step.
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


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    session_id = payload.session_id or str(uuid.uuid4())
    history = _SESSIONS.get(session_id, [])

    try:
        result = await chat_agent.run(payload.message, message_history=history)
    except Exception as exc:
        logging.exception("agent run failed")
        raise HTTPException(status_code=502, detail="upstream model error") from exc

    _SESSIONS[session_id] = result.all_messages()

    return ChatResponse(reply=result.output, session_id=session_id)
