"""App database schema: speeches composed of ordered sections, each section
citing sources that point at chunks of the corpus in Qdrant, plus reusable
voice profiles (prompt text describing a register to write in).

A note on section_sources: Qdrant point ids are
uuid5(namespace, f"{relpath}:{chunk_index}") -- see ingest/ingest_lib.py. That
id is stable across re-ingests only while the file path and chunk index hold.
Editing a document body shifts the word-window chunk boundaries and silently
repoints the same uuid at different text. So a source row stores the point id
*and* a snapshot of the quoted text and citation metadata taken at attach time:
the id re-finds the live chunk, the snapshot keeps the citation verifiable if
the corpus moves underneath it.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """A datetime column that always round-trips as timezone-aware UTC.

    SQLite's DATETIME stores no offset, so a tz-aware value written straight to
    a DateTime(timezone=True) column comes back naive -- meaning the same field
    serialized as "...Z" right after a write and as a bare local-looking
    timestamp on the next read. Normalize to UTC going in, re-stamp UTC coming
    out. On a backend that does keep the offset (Postgres timestamptz) both
    directions are no-ops.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    # Defaulted in Python rather than with func.now(): SQLite renders func.now()
    # as a naive local-time string, which round-trips wrong through a
    # timezone-aware column.
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class VoiceProfile(TimestampMixin, Base):
    """A named prompt describing a voice to write in."""

    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)


class Speech(TimestampMixin, Base):
    """A speech being drafted: an ordered list of sections."""

    __tablename__ = "speeches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    occasion: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SET NULL, not CASCADE: deleting a voice profile must never destroy drafts.
    voice_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True
    )

    sections: Mapped[list["Section"]] = relationship(
        back_populates="speech",
        cascade="all, delete-orphan",
        order_by="Section.position",
    )
    voice_profile: Mapped[VoiceProfile | None] = relationship()


class Section(TimestampMixin, Base):
    """One section of a speech: draft text plus the sources it draws on."""

    __tablename__ = "sections"
    __table_args__ = (
        # Deliberately a plain index, not unique. SQLite cannot defer a unique
        # check, so a unique (speech_id, position) would force reordering to
        # shuffle through temporary values. Contiguity is maintained by the
        # reorder/delete endpoints instead.
        Index("ix_sections_speech_position", "speech_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    speech_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speeches.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Author-entered note on what this section should accomplish. Free text, not
    # a derived classification -- see the corpus rule in CLAUDE.md.
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL means inherit the speech's profile.
    voice_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True
    )

    speech: Mapped[Speech] = relationship(back_populates="sections")
    sources: Mapped[list["SectionSource"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="SectionSource.position",
    )
    web_sources: Mapped[list["SectionWebSource"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="SectionWebSource.position",
    )
    voice_profile: Mapped[VoiceProfile | None] = relationship()


class SectionSource(Base):
    """A citation: a Qdrant chunk a section draws on, plus a snapshot of it."""

    __tablename__ = "section_sources"
    __table_args__ = (
        # Attaching the same chunk twice to one section is a no-op, not a dupe.
        UniqueConstraint("section_id", "qdrant_point_id", name="uq_section_source_point"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    section_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
    )
    qdrant_point_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Snapshot taken at attach time. Mirrors the payload ingest writes.
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    speech_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, nullable=False)

    section: Mapped[Section] = relationship(back_populates="sources")


class SectionWebSource(Base):
    """A web citation supporting a section.

    Separate from SectionSource rather than a nullable-point-id variant of it,
    because the two are verified in completely different ways: a corpus source
    is re-findable in Qdrant by id, a web source is a URL we can only check was
    actually returned by a search at the time it was written.
    """

    __tablename__ = "section_web_sources"
    __table_args__ = (
        UniqueConstraint("section_id", "url", name="uq_section_web_source_url"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    section_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    claim: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, nullable=False)

    section: Mapped[Section] = relationship(back_populates="web_sources")


class Brief(TimestampMixin, Base):
    """Turns a speech into an event brief: the prompt it came from, the
    surrounding matter that isn't a talking point, and the agent conversation.

    A brief *is* a speech -- the talking points are its sections and the
    citations are its section sources -- so this table only carries what the
    speech tables have nowhere to put.

    `status` drives the approval gate:
        researching -> outline_proposed -> drafting -> ready
    returning to `drafting` on each revision. Prose is only ever written in the
    `drafting` transition, which is what makes the gate structural rather than
    a matter of the model being asked nicely.
    """

    __tablename__ = "briefs"

    speech_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speeches.id", ondelete="CASCADE"), primary_key=True
    )
    event_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="researching")

    event_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    framing: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Newline-separated rather than JSON: they render as bullets and nothing
    # queries into them, and the rest of this schema keeps to plain columns.
    likely_questions: Mapped[str | None] = mapped_column(Text, nullable=True)
    gaps: Mapped[str | None] = mapped_column(Text, nullable=True)

    # pydantic-ai's own message history, verbatim from all_messages_json(), so a
    # later turn can continue the run without repeating the research. Opaque on
    # purpose: nothing here parses it, and its shape belongs to the library.
    agent_messages: Mapped[str | None] = mapped_column(Text, nullable=True)

    speech: Mapped[Speech] = relationship()
    messages: Mapped[list["BriefMessage"]] = relationship(
        back_populates="brief",
        cascade="all, delete-orphan",
        order_by="BriefMessage.position",
    )


class BriefMessage(Base):
    """One line of the visible transcript.

    Deliberately not derived from `Brief.agent_messages`: that blob is
    pydantic-ai's internal format, and the UI should not break when the library
    changes it. This is the display copy -- what a person said and what the
    agent said back, plus the activity lines worth keeping after a run.
    """

    __tablename__ = "brief_messages"
    __table_args__ = (
        Index("ix_brief_messages_brief_position", "brief_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    brief_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("briefs.speech_id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, nullable=False)

    brief: Mapped[Brief] = relationship(back_populates="messages")
