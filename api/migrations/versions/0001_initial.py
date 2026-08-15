"""Initial app database: voice profiles, speeches, sections, section sources

Revision ID: 0001
Revises:
Create Date: 2026-08-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_voice_profiles_name"),
    )

    op.create_table(
        "speeches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("occasion", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("voice_profile_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_speeches_voice_profile",
            ondelete="SET NULL",
        ),
    )

    op.create_table(
        "sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("speech_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(500), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("voice_profile_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["speech_id"], ["speeches.id"], name="fk_sections_speech", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_sections_voice_profile",
            ondelete="SET NULL",
        ),
    )
    # Plain index, not unique -- reordering reassigns positions in one pass and
    # SQLite cannot defer a unique check to the end of the transaction.
    op.create_index("ix_sections_speech_position", "sections", ["speech_id", "position"])

    op.create_table(
        "section_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("section_id", sa.String(36), nullable=False),
        sa.Column("qdrant_point_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quoted_text", sa.Text(), nullable=False),
        sa.Column("source_file", sa.String(500), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("speaker", sa.String(200), nullable=True),
        sa.Column("date", sa.String(10), nullable=True),
        sa.Column("speech_type", sa.String(100), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name="fk_section_sources_section", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("section_id", "qdrant_point_id", name="uq_section_source_point"),
    )


def downgrade() -> None:
    op.drop_table("section_sources")
    op.drop_index("ix_sections_speech_position", table_name="sections")
    op.drop_table("sections")
    op.drop_table("speeches")
    op.drop_table("voice_profiles")
