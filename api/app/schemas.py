"""Request/response models for the drafting API.

Kept separate from app/models.py so the wire format can diverge from the
storage schema (e.g. section_count on a list row, nested sources on a read).
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SpeechStatus = Literal["draft", "review", "final"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- voice profiles ---------------------------------------------------------


class VoiceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    prompt: str = Field(min_length=1)


class VoiceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    prompt: str | None = Field(default=None, min_length=1)


class VoiceProfileRead(ORMModel):
    id: str
    name: str
    description: str | None
    prompt: str
    created_at: datetime
    updated_at: datetime


# --- section sources --------------------------------------------------------


class SectionSourceCreate(BaseModel):
    """Attach a corpus chunk to a section.

    Only qdrant_point_id is required: anything left unset is filled in from the
    live Qdrant payload. Callers holding a search hit can pass the snapshot
    fields directly to record exactly what they saw, including the score.
    """

    qdrant_point_id: str
    quoted_text: str | None = None
    source_file: str | None = None
    chunk_index: int | None = None
    title: str | None = None
    speaker: str | None = None
    date: str | None = None
    category: str | None = None
    voice: str | None = None
    source_url: str | None = None
    relevance_score: float | None = None


class SectionSourceRead(ORMModel):
    id: str
    section_id: str
    qdrant_point_id: str
    position: int
    quoted_text: str
    source_file: str | None
    chunk_index: int | None
    title: str | None
    speaker: str | None
    date: str | None
    category: str | None
    voice: str | None
    source_url: str | None
    relevance_score: float | None
    created_at: datetime


# --- sections ---------------------------------------------------------------


class SectionCreate(BaseModel):
    heading: str | None = None
    text: str = ""
    intent: str | None = None
    voice_profile_id: str | None = None


class SectionUpdate(BaseModel):
    heading: str | None = None
    text: str | None = None
    intent: str | None = None
    voice_profile_id: str | None = None


class SectionRead(ORMModel):
    id: str
    speech_id: str
    position: int
    heading: str | None
    text: str
    intent: str | None
    voice_profile_id: str | None
    created_at: datetime
    updated_at: datetime
    sources: list[SectionSourceRead] = []


class SectionReorder(BaseModel):
    section_ids: list[str] = Field(min_length=1)


# --- speeches ---------------------------------------------------------------


class SpeechCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    occasion: str | None = None
    event_date: date | None = None
    status: SpeechStatus = "draft"
    notes: str | None = None
    voice_profile_id: str | None = None
    sections: list[SectionCreate] = []


class SpeechUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    occasion: str | None = None
    event_date: date | None = None
    status: SpeechStatus | None = None
    notes: str | None = None
    voice_profile_id: str | None = None


class SpeechSummary(ORMModel):
    id: str
    title: str
    occasion: str | None
    event_date: date | None
    status: str
    notes: str | None
    voice_profile_id: str | None
    created_at: datetime
    updated_at: datetime
    section_count: int = 0


class SpeechRead(SpeechSummary):
    sections: list[SectionRead] = []


# --- search -----------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)


class SearchHit(BaseModel):
    """A corpus chunk, shaped so it can be posted straight back as a
    SectionSourceCreate."""

    id: str
    score: float
    text: str | None = None
    title: str | None = None
    speaker: str | None = None
    date: str | None = None
    category: str | None = None
    voice: str | None = None
    source_url: str | None = None
    source_file: str | None = None
    chunk_index: int | None = None
