"""CRUD for voice profiles -- named prompts describing a register to write in."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import VoiceProfile
from app.schemas import VoiceProfileCreate, VoiceProfileRead, VoiceProfileUpdate

router = APIRouter(prefix="/api/voice-profiles", tags=["voice-profiles"])


async def _get_or_404(session: AsyncSession, profile_id: str) -> VoiceProfile:
    profile = await session.get(VoiceProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="voice profile not found")
    return profile


@router.get("", response_model=list[VoiceProfileRead])
async def list_voice_profiles(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(VoiceProfile).order_by(VoiceProfile.name))
    return list(result.scalars())


@router.post("", response_model=VoiceProfileRead, status_code=201)
async def create_voice_profile(
    payload: VoiceProfileCreate, session: AsyncSession = Depends(get_session)
):
    profile = VoiceProfile(**payload.model_dump())
    session.add(profile)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a voice profile named {payload.name!r} already exists"
        ) from exc
    await session.commit()
    return profile


@router.get("/{profile_id}", response_model=VoiceProfileRead)
async def get_voice_profile(profile_id: str, session: AsyncSession = Depends(get_session)):
    return await _get_or_404(session, profile_id)


@router.patch("/{profile_id}", response_model=VoiceProfileRead)
async def update_voice_profile(
    profile_id: str,
    payload: VoiceProfileUpdate,
    session: AsyncSession = Depends(get_session),
):
    profile = await _get_or_404(session, profile_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="that voice profile name is taken") from exc
    await session.commit()
    return profile


@router.delete("/{profile_id}", status_code=204)
async def delete_voice_profile(profile_id: str, session: AsyncSession = Depends(get_session)):
    """Delete a profile. Speeches and sections using it keep their text and fall
    back to no profile (the FK is ON DELETE SET NULL)."""
    profile = await _get_or_404(session, profile_id)
    await session.delete(profile)
    await session.commit()
