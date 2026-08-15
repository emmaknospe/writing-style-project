"""Event briefs: research, an approved outline, then drafted talking points.

The flow is a two-phase gate. A first message researches and proposes an
outline, written to the DB as real sections with headings but no text. The user
edits that outline with the ordinary section endpoints in `speeches.py` --
retitle, reorder, delete, add -- and then approves, which drafts prose over
whatever the outline now says. Revisions after that re-draft.

Both agent-running endpoints stream Server-Sent Events. They are POSTs, so the
browser reads them with `fetch` + `ReadableStream` rather than `EventSource`,
which is GET-only.
"""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic_ai import AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessagesTypeAdapter,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartEndEvent,
    PartStartEvent,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent import draft_agent, outline_agent, verify_corpus_citations
from app.agent_outputs import BriefOutline, DraftedPoints
from app.db import SessionLocal, get_session
from app.models import Brief, BriefMessage, Section, SectionSource, SectionWebSource, Speech
from app.schemas import BriefCreate, BriefMessageSend, BriefRead, BriefSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/briefs", tags=["briefs"])


# --- helpers ----------------------------------------------------------------


def _lines(value: str | None) -> list[str]:
    return [line for line in (value or "").splitlines() if line.strip()]


def _joined(values: list[str] | None) -> str | None:
    return "\n".join(values) if values else None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _load_brief(session: AsyncSession, brief_id: str) -> Brief:
    """Load a brief with its speech, sections, sources and transcript eagerly.

    The eager load is required, not an optimization: a lazy load triggered while
    serializing the response would raise MissingGreenlet under the async session.
    """
    result = await session.execute(
        select(Brief)
        .where(Brief.speech_id == brief_id)
        .options(
            selectinload(Brief.messages),
            selectinload(Brief.speech)
            .selectinload(Speech.sections)
            .selectinload(Section.sources),
            selectinload(Brief.speech)
            .selectinload(Speech.sections)
            .selectinload(Section.web_sources),
        )
    )
    brief = result.scalar_one_or_none()
    if brief is None:
        raise HTTPException(status_code=404, detail="brief not found")
    return brief


def _to_read(brief: Brief) -> BriefRead:
    return BriefRead(
        speech_id=brief.speech_id,
        title=brief.speech.title,
        event_prompt=brief.event_prompt,
        status=brief.status,
        created_at=brief.created_at,
        updated_at=brief.updated_at,
        event_summary=brief.event_summary,
        framing=brief.framing,
        likely_questions=_lines(brief.likely_questions),
        gaps=_lines(brief.gaps),
        points=list(brief.speech.sections),
        messages=list(brief.messages),
    )


async def _add_message(session: AsyncSession, brief: Brief, role: str, content: str) -> None:
    result = await session.execute(
        select(BriefMessage.position)
        .where(BriefMessage.brief_id == brief.speech_id)
        .order_by(BriefMessage.position.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    session.add(
        BriefMessage(
            brief_id=brief.speech_id,
            position=0 if last is None else last + 1,
            role=role,
            content=content,
        )
    )


# --- CRUD -------------------------------------------------------------------


@router.post("", response_model=BriefRead, status_code=201)
async def create_brief(payload: BriefCreate, session: AsyncSession = Depends(get_session)):
    """Open a brief. Nothing is researched until the first message is sent."""
    speech = Speech(title=payload.prompt.strip()[:200] or "Untitled brief", occasion=payload.prompt)
    session.add(speech)
    await session.flush()

    brief = Brief(speech_id=speech.id, event_prompt=payload.prompt, status="researching")
    session.add(brief)
    await _add_message(session, brief, "user", payload.prompt)
    await session.commit()

    return _to_read(await _load_brief(session, speech.id))


@router.get("", response_model=list[BriefSummary])
async def list_briefs(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Brief, Speech.title)
        .join(Speech, Speech.id == Brief.speech_id)
        .order_by(Brief.updated_at.desc())
    )
    return [
        BriefSummary(
            speech_id=brief.speech_id,
            title=title,
            event_prompt=brief.event_prompt,
            status=brief.status,
            created_at=brief.created_at,
            updated_at=brief.updated_at,
        )
        for brief, title in result.all()
    ]


@router.get("/{brief_id}", response_model=BriefRead)
async def get_brief(brief_id: str, session: AsyncSession = Depends(get_session)):
    return _to_read(await _load_brief(session, brief_id))


# --- the streamed agent runs ------------------------------------------------


def _activity(event) -> dict[str, Any] | None:
    """Translate one pydantic-ai run event into a line for the activity feed.

    Web search is server-side, so it arrives as native tool parts rather than
    through a tool function. Its arguments are streamed as JSON deltas *after*
    the part starts, so the query is only complete at `PartEndEvent` -- reading
    it at `PartStartEvent` yields an empty query.
    """
    if isinstance(event, FunctionToolCallEvent) and event.part.tool_name == "search_corpus":
        args = event.part.args
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {"kind": "corpus_search", "query": (args or {}).get("query", "")}

    if isinstance(event, FunctionToolResultEvent) and event.part.tool_name == "search_corpus":
        content = event.part.content
        found = 0 if not isinstance(content, str) or "No relevant passages" in content else (
            content.count("\n---\n") + 1
        )
        return {"kind": "corpus_result", "count": found}

    # The call part and the return part are read at different points on
    # purpose. A call's arguments stream in as JSON deltas, so the query is
    # only complete at PartEndEvent. A result block arrives whole, so it is
    # readable at PartStartEvent -- and matching each on exactly one event kind
    # keeps a part that emits both from producing a duplicate line.
    if isinstance(event, PartEndEvent):
        part = event.part
        if isinstance(part, NativeToolCallPart) and part.tool_name == "web_search":
            args = part.args
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            return {"kind": "web_search", "query": (args or {}).get("query", "")}

    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, NativeToolReturnPart) and part.tool_name == "web_search":
            content = part.content
            return {"kind": "web_result", "count": len(content) if isinstance(content, list) else 0}

    return None


def _stream(agent, prompt: str, brief_id: str, apply, message_history=None):
    """Run `agent`, streaming activity, then hand the result to `apply`.

    `apply` persists in its own session: the request-scoped session from
    `Depends(get_session)` is closed by FastAPI when the handler returns, which
    for a StreamingResponse is *before* the body is consumed.
    """

    async def generate() -> AsyncIterator[str]:
        try:
            result = None
            async with agent.run_stream_events(
                prompt, message_history=message_history
            ) as events:
                async for event in events:
                    if isinstance(event, AgentRunResultEvent):
                        result = event.result
                        continue
                    line = _activity(event)
                    if line is not None:
                        yield _sse("activity", line)

            if result is None:  # pragma: no cover - defensive
                yield _sse("error", {"detail": "the run produced no result"})
                return

            async with SessionLocal() as session:
                brief = await _load_brief(session, brief_id)
                payload = await apply(session, brief, result)
                await session.commit()
                fresh = _to_read(await _load_brief(session, brief_id))

            yield _sse(payload["event"], json.loads(fresh.model_dump_json()))
            yield _sse("done", {"status": fresh.status})
        except Exception as exc:  # noqa: BLE001 - surfaced to the client below
            logger.exception("brief run failed")
            yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx buffers proxied responses by default, which would hold the
            # whole feed until the run finished. proxy_buffering is off in
            # frontend/nginx.conf; this covers any other proxy in front.
            "X-Accel-Buffering": "no",
        },
    )


async def _apply_outline(session: AsyncSession, brief: Brief, result) -> dict[str, str]:
    """Replace the outline with the proposed points. Headings only -- no prose."""
    outline: BriefOutline = result.output

    for section in list(brief.speech.sections):
        await session.delete(section)
    await session.flush()

    for position, point in enumerate(outline.proposed_points):
        session.add(
            Section(
                speech_id=brief.speech_id,
                position=position,
                heading=point.headline,
                text="",
                intent=point.rationale,
            )
        )

    brief.event_summary = outline.event_summary
    brief.framing = outline.framing
    brief.likely_questions = _joined(outline.likely_questions)
    brief.gaps = _joined(outline.gaps)
    brief.status = "outline_proposed"
    brief.agent_messages = result.all_messages_json().decode()

    summary = "\n".join(
        [f"{i + 1}. {p.headline} — {p.rationale}" for i, p in enumerate(outline.proposed_points)]
    )
    body = f"{outline.framing}\n\n{summary}"
    if outline.questions_for_user:
        body += "\n\nBefore I draft:\n" + "\n".join(f"- {q}" for q in outline.questions_for_user)
    await _add_message(session, brief, "agent", body)

    return {"event": "outline"}


async def _apply_draft(session: AsyncSession, brief: Brief, result) -> dict[str, str]:
    """Write prose and citations onto the approved outline sections."""
    drafted: DraftedPoints = result.output
    sections = list(brief.speech.sections)

    for section, point in zip(sections, drafted.points):
        section.text = point.talking_point

        for source in list(section.sources):
            await session.delete(source)
        for web in list(section.web_sources):
            await session.delete(web)
        await session.flush()

        verified, _, _ = await asyncio.to_thread(verify_corpus_citations, point.corpus_support)
        for position, source in enumerate(verified):
            session.add(SectionSource(section_id=section.id, position=position, **source))

        allowed = _searched_web_urls(result.all_messages())
        kept: list = []
        seen_urls: set[str] = set()
        for citation in point.web_context:
            # Same rule as corpus sources: one row per (section, url), and the
            # model does repeat a URL under a single point.
            if citation.url not in allowed or citation.url in seen_urls:
                continue
            seen_urls.add(citation.url)
            kept.append(citation)
        dropped = len(point.web_context) - len(kept)
        if dropped:
            logger.warning(
                "dropped %d web citation(s): not returned by web search, or duplicated", dropped
            )
        for position, citation in enumerate(kept):
            session.add(
                SectionWebSource(
                    section_id=section.id,
                    position=position,
                    url=citation.url,
                    title=citation.title,
                    claim=citation.claim,
                )
            )

    if drafted.framing:
        brief.framing = drafted.framing
    if drafted.likely_questions:
        brief.likely_questions = _joined(drafted.likely_questions)
    if drafted.gaps:
        brief.gaps = _joined(drafted.gaps)
    brief.status = "ready"
    brief.agent_messages = result.all_messages_json().decode()

    await _add_message(
        session, brief, "agent", f"Drafted {len(drafted.points)} talking point(s)."
    )
    return {"event": "brief"}


def _searched_web_urls(messages: list) -> set[str]:
    """URLs Anthropic's web search actually returned during this run.

    Server-side results arrive as `NativeToolReturnPart`s in the message
    history -- the only place they can be read back. `content` is Anthropic's
    raw payload: normally a list of result dicts, but an error (e.g.
    `max_uses_exceeded`) yields a single object instead, hence the guards.
    """
    urls: set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", []):
            if not isinstance(part, NativeToolReturnPart) or part.tool_name != "web_search":
                continue
            if not isinstance(part.content, list):
                continue
            for entry in part.content:
                if isinstance(entry, dict) and entry.get("url"):
                    urls.add(entry["url"])
    return urls


def _history(brief: Brief):
    if not brief.agent_messages:
        return None
    return ModelMessagesTypeAdapter.validate_json(brief.agent_messages)


@router.post("/{brief_id}/messages")
async def send_message(
    brief_id: str, payload: BriefMessageSend, session: AsyncSession = Depends(get_session)
):
    """Send a message. Researches an outline first; revises the brief after."""
    brief = await _load_brief(session, brief_id)
    await _add_message(session, brief, "user", payload.message)
    await session.commit()

    history = _history(brief)
    # On the very first run there is no history, so the event description lives
    # only in `event_prompt` -- send it, or the agent researches nothing and
    # reports that it has not been told what the event is.
    prompt = (
        payload.message
        if history
        else f"The event:\n{brief.event_prompt}\n\n{payload.message}"
    )

    if brief.status in ("researching", "outline_proposed"):
        return _stream(outline_agent, prompt, brief_id, _apply_outline, history)
    return _stream(
        draft_agent,
        f"{prompt}\n\n{_outline_text(brief)}",
        brief_id,
        _apply_draft,
        history,
    )


def _outline_text(brief: Brief) -> str:
    """The outline as it now stands, so the draft pass sees the user's edits."""
    points = "\n".join(
        f"{i + 1}. {s.heading}" + (f" — {s.intent}" if s.intent else "")
        for i, s in enumerate(brief.speech.sections)
    )
    return f"The approved outline, as the user left it:\n{points}"


@router.post("/{brief_id}/approve")
async def approve(brief_id: str, session: AsyncSession = Depends(get_session)):
    """Draft prose over the outline as the user has edited it."""
    brief = await _load_brief(session, brief_id)
    if not brief.speech.sections:
        raise HTTPException(status_code=400, detail="the outline has no points to draft")

    # Status advances in _apply_draft, which only runs on success. Setting it
    # here would strand a failed run in `drafting` with empty points -- the
    # sidebar would show a blank brief instead of the outline you can retry.
    await _add_message(session, brief, "user", "Approved the outline — draft it.")
    await session.commit()

    return _stream(draft_agent, _outline_text(brief), brief_id, _apply_draft, _history(brief))
