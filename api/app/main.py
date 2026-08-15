import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic_ai.messages import NativeToolReturnPart

from app.agent import BriefDeps, brief_agent
from app.config import settings
from app.schemas import BriefRequest, TalkingPointsBrief
from app.vector_store import ensure_collection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_collection()
    yield


app = FastAPI(title="writing-style API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _searched_web_urls(messages: list) -> set[str]:
    """URLs that Anthropic's web search actually returned during this run.

    Web search is server-side, so its results arrive as `NativeToolReturnPart`s
    in the message history rather than through a tool function we control --
    this is the only place they can be read back. `content` is Anthropic's raw
    result payload: normally a list of result dicts, but an error (e.g.
    `max_uses_exceeded`) instead yields a single object, hence the isinstance
    guards rather than a bare comprehension.
    """
    urls: set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", []):
            if not isinstance(part, NativeToolReturnPart):
                continue
            if part.tool_name != "web_search":
                continue
            content = part.content
            if not isinstance(content, list):
                continue
            for result in content:
                if isinstance(result, dict) and result.get("url"):
                    urls.add(result["url"])
    return urls


def _drop_unbacked_web_citations(brief: TalkingPointsBrief, messages: list) -> None:
    """Discard web citations whose URL never appeared in a search result.

    The corpus half of this check lives in the agent's output validator, which
    has `BriefDeps` in scope. Web results have no equivalent hook, so the
    filtering happens here, where the message history is available.
    """
    allowed = _searched_web_urls(messages)
    dropped = 0
    for point in brief.points:
        kept = [c for c in point.web_context if c.url in allowed]
        dropped += len(point.web_context) - len(kept)
        point.web_context = kept
    if dropped:
        logger.warning(
            "dropped %d web citation(s) with URLs not returned by web search", dropped
        )


@app.post("/api/talking-points", response_model=TalkingPointsBrief)
async def talking_points(payload: BriefRequest) -> TalkingPointsBrief:
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt must not be empty")

    # Stateless by design: a brief is one prompt in, one brief out. There is no
    # conversation history to carry, so there is no session store to leak.
    deps = BriefDeps()

    try:
        result = await brief_agent.run(payload.prompt, deps=deps)
    except Exception as exc:
        logging.exception("agent run failed")
        raise HTTPException(status_code=502, detail="upstream model error") from exc

    brief = result.output
    _drop_unbacked_web_citations(brief, result.all_messages())
    return brief
