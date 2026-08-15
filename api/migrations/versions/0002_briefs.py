"""Event briefs: brief metadata, transcript, and web citations

A brief is a speech -- its talking points are sections and its corpus
citations are section_sources -- so this adds only what those tables have
nowhere to put: the originating prompt and approval status, the surrounding
matter that isn't a talking point, the visible transcript, and web citations
(which section_sources cannot hold, its qdrant_point_id being NOT NULL).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefs",
        # speech_id is the primary key, not a separate id: a brief extends
        # exactly one speech and has no identity apart from it.
        sa.Column("speech_id", sa.String(36), primary_key=True),
        sa.Column("event_prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="researching"),
        sa.Column("event_summary", sa.Text(), nullable=True),
        sa.Column("framing", sa.Text(), nullable=True),
        # Newline-separated lists; see models.py for why these aren't JSON.
        sa.Column("likely_questions", sa.Text(), nullable=True),
        sa.Column("gaps", sa.Text(), nullable=True),
        sa.Column("agent_messages", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["speech_id"], ["speeches.id"], name="fk_briefs_speech", ondelete="CASCADE"
        ),
    )

    op.create_table(
        "brief_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brief_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brief_id"], ["briefs.speech_id"], name="fk_brief_messages_brief", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_brief_messages_brief_position", "brief_messages", ["brief_id", "position"])

    op.create_table(
        "section_web_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("section_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("claim", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name="fk_section_web_sources_section",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("section_id", "url", name="uq_section_web_source_url"),
    )


def downgrade() -> None:
    op.drop_table("section_web_sources")
    op.drop_index("ix_brief_messages_brief_position", table_name="brief_messages")
    op.drop_table("brief_messages")
    op.drop_table("briefs")
