"""Speeches, their ordered sections, and the corpus sources each section cites."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import vector_store
from app.db import get_session
from app.models import Section, SectionSource, Speech, VoiceProfile
from app.schemas import (
    SectionCreate,
    SectionRead,
    SectionReorder,
    SectionSourceCreate,
    SectionSourceRead,
    SectionUpdate,
    SpeechCreate,
    SpeechRead,
    SpeechSummary,
    SpeechUpdate,
    VoiceProfileRead,
)

router = APIRouter(prefix="/api", tags=["speeches"])


async def _check_voice_profile(session: AsyncSession, profile_id: str | None) -> None:
    """Fail loudly on an unknown profile id rather than letting the FK raise a
    generic IntegrityError at flush time."""
    if profile_id is None:
        return
    if await session.get(VoiceProfile, profile_id) is None:
        raise HTTPException(status_code=400, detail=f"unknown voice_profile_id {profile_id!r}")


async def _load_speech(session: AsyncSession, speech_id: str) -> Speech:
    """Load a speech with its sections and their sources eagerly.

    The eager load is required, not an optimization: a lazy load triggered while
    serializing the response would raise MissingGreenlet under the async session.
    """
    result = await session.execute(
        select(Speech)
        .where(Speech.id == speech_id)
        .options(selectinload(Speech.sections).selectinload(Section.sources))
    )
    speech = result.scalar_one_or_none()
    if speech is None:
        raise HTTPException(status_code=404, detail="speech not found")
    return speech


def _speech_read(speech: Speech) -> SpeechRead:
    read = SpeechRead.model_validate(speech)
    read.section_count = len(speech.sections)
    return read


async def _get_section(session: AsyncSession, section_id: str) -> Section:
    result = await session.execute(
        select(Section).where(Section.id == section_id).options(selectinload(Section.sources))
    )
    section = result.scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="section not found")
    return section


async def _renumber_sections(session: AsyncSession, speech_id: str) -> None:
    """Rewrite positions to a contiguous 0..n-1 in current order."""
    result = await session.execute(
        select(Section).where(Section.speech_id == speech_id).order_by(Section.position)
    )
    for index, section in enumerate(result.scalars()):
        section.position = index


# --- speeches ---------------------------------------------------------------


@router.get("/speeches", response_model=list[SpeechSummary])
async def list_speeches(session: AsyncSession = Depends(get_session)):
    """Summaries only -- no section bodies, which keeps the list cheap."""
    result = await session.execute(
        select(Speech, func.count(Section.id))
        .outerjoin(Section, Section.speech_id == Speech.id)
        .group_by(Speech.id)
        .order_by(Speech.updated_at.desc())
    )
    summaries = []
    for speech, section_count in result.all():
        summary = SpeechSummary.model_validate(speech)
        summary.section_count = section_count
        summaries.append(summary)
    return summaries


@router.post("/speeches", response_model=SpeechRead, status_code=201)
async def create_speech(payload: SpeechCreate, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump(exclude={"sections"})
    await _check_voice_profile(session, data["voice_profile_id"])

    speech = Speech(**data)
    for index, section_payload in enumerate(payload.sections):
        await _check_voice_profile(session, section_payload.voice_profile_id)
        speech.sections.append(Section(position=index, **section_payload.model_dump()))

    session.add(speech)
    await session.commit()
    return _speech_read(await _load_speech(session, speech.id))


@router.get("/speeches/{speech_id}", response_model=SpeechRead)
async def get_speech(speech_id: str, session: AsyncSession = Depends(get_session)):
    return _speech_read(await _load_speech(session, speech_id))


@router.patch("/speeches/{speech_id}", response_model=SpeechRead)
async def update_speech(
    speech_id: str, payload: SpeechUpdate, session: AsyncSession = Depends(get_session)
):
    speech = await _load_speech(session, speech_id)
    changes = payload.model_dump(exclude_unset=True)
    if "voice_profile_id" in changes:
        await _check_voice_profile(session, changes["voice_profile_id"])
    for field, value in changes.items():
        setattr(speech, field, value)
    await session.commit()
    return _speech_read(speech)


@router.delete("/speeches/{speech_id}", status_code=204)
async def delete_speech(speech_id: str, session: AsyncSession = Depends(get_session)):
    """Deletes the speech's sections and their sources too, by FK cascade."""
    speech = await _load_speech(session, speech_id)
    await session.delete(speech)
    await session.commit()


# --- sections ---------------------------------------------------------------


@router.post("/speeches/{speech_id}/sections", response_model=SectionRead, status_code=201)
async def create_section(
    speech_id: str, payload: SectionCreate, session: AsyncSession = Depends(get_session)
):
    """Append a section at the end of the speech."""
    await _load_speech(session, speech_id)
    await _check_voice_profile(session, payload.voice_profile_id)

    next_position = await session.scalar(
        select(func.coalesce(func.max(Section.position) + 1, 0)).where(
            Section.speech_id == speech_id
        )
    )
    section = Section(speech_id=speech_id, position=next_position, **payload.model_dump())
    session.add(section)
    await session.commit()
    return await _get_section(session, section.id)


@router.put("/speeches/{speech_id}/sections/order", response_model=list[SectionRead])
async def reorder_sections(
    speech_id: str, payload: SectionReorder, session: AsyncSession = Depends(get_session)
):
    """Reassign positions 0..n-1 from the given order.

    section_ids must be exactly the speech's sections -- a partial list would
    leave the remainder in an ambiguous order, so it is rejected rather than
    guessed at.
    """
    speech = await _load_speech(session, speech_id)
    by_id = {section.id: section for section in speech.sections}
    if set(payload.section_ids) != set(by_id) or len(payload.section_ids) != len(by_id):
        raise HTTPException(
            status_code=400,
            detail="section_ids must list each of this speech's sections exactly once",
        )
    for index, section_id in enumerate(payload.section_ids):
        by_id[section_id].position = index
    await session.commit()
    return [by_id[section_id] for section_id in payload.section_ids]


@router.get("/sections/{section_id}", response_model=SectionRead)
async def get_section(section_id: str, session: AsyncSession = Depends(get_session)):
    return await _get_section(session, section_id)


@router.patch("/sections/{section_id}", response_model=SectionRead)
async def update_section(
    section_id: str, payload: SectionUpdate, session: AsyncSession = Depends(get_session)
):
    section = await _get_section(session, section_id)
    changes = payload.model_dump(exclude_unset=True)
    if "voice_profile_id" in changes:
        await _check_voice_profile(session, changes["voice_profile_id"])
    for field, value in changes.items():
        setattr(section, field, value)
    await session.commit()
    return section


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section(section_id: str, session: AsyncSession = Depends(get_session)):
    section = await _get_section(session, section_id)
    speech_id = section.speech_id
    await session.delete(section)
    await session.flush()
    await _renumber_sections(session, speech_id)
    await session.commit()


@router.get("/sections/{section_id}/voice", response_model=VoiceProfileRead)
async def get_section_voice(section_id: str, session: AsyncSession = Depends(get_session)):
    """The profile that actually applies here: the section's own, else the
    speech's. Keeps the inheritance rule on the server so callers don't each
    reimplement it."""
    section = await _get_section(session, section_id)
    profile_id = section.voice_profile_id
    if profile_id is None:
        speech = await session.get(Speech, section.speech_id)
        profile_id = speech.voice_profile_id if speech else None
    if profile_id is None:
        raise HTTPException(status_code=404, detail="no voice profile set on section or speech")
    profile = await session.get(VoiceProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="voice profile not found")
    return profile


# --- section sources --------------------------------------------------------


@router.post("/sections/{section_id}/sources", response_model=SectionSourceRead)
async def attach_source(
    section_id: str,
    payload: SectionSourceCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Cite a corpus chunk in this section.

    Unset snapshot fields are filled from the live Qdrant payload. The snapshot
    matters because point ids are derived from file path + chunk index: re-ingesting
    an edited document can repoint the same id at different text, and the stored
    copy is what keeps the citation checkable afterwards.
    """
    section = await _get_section(session, section_id)

    existing = next(
        (s for s in section.sources if s.qdrant_point_id == payload.qdrant_point_id), None
    )
    if existing is not None:
        response.status_code = 200
        return existing

    hits = await asyncio.to_thread(vector_store.get_by_ids, [payload.qdrant_point_id])
    if not hits:
        raise HTTPException(
            status_code=404,
            detail=f"no corpus chunk with point id {payload.qdrant_point_id!r}",
        )
    hit = hits[0]

    supplied = payload.model_dump(exclude_unset=True, exclude={"qdrant_point_id"})
    snapshot = {
        "quoted_text": hit.get("text") or "",
        "source_file": hit.get("source_file"),
        "chunk_index": hit.get("chunk_index"),
        "title": hit.get("title"),
        "speaker": hit.get("speaker"),
        "date": hit.get("date"),
        "speech_type": hit.get("speech_type"),
        "source_url": hit.get("source_url"),
        "relevance_score": None,
    }
    snapshot.update({k: v for k, v in supplied.items() if v is not None})

    next_position = await session.scalar(
        select(func.coalesce(func.max(SectionSource.position) + 1, 0)).where(
            SectionSource.section_id == section_id
        )
    )
    source = SectionSource(
        section_id=section_id,
        qdrant_point_id=payload.qdrant_point_id,
        position=next_position,
        **snapshot,
    )
    session.add(source)
    await session.commit()
    response.status_code = 201
    return source


@router.delete("/sections/{section_id}/sources/{source_id}", status_code=204)
async def detach_source(
    section_id: str, source_id: str, session: AsyncSession = Depends(get_session)
):
    source = await session.get(SectionSource, source_id)
    if source is None or source.section_id != section_id:
        raise HTTPException(status_code=404, detail="source not found on this section")
    await session.delete(source)
    await session.commit()
