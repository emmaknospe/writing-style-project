"""Section sources: speech_type -> category, plus voice

The corpus reorganization replaced the hand-typed `speech_type` frontmatter
field with an LLM-assigned `category` (the document's form) and `voice` (how
much of the body is actually her own words). A section source snapshots the
Qdrant payload at attach time, so it follows the payload.

Rows written before this migration keep their old value under `category`;
`voice` is null for them until the source is re-attached.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table because SQLite cannot ALTER/RENAME a column in place --
    # Alembic rebuilds the table and copies the rows.
    with op.batch_alter_table("section_sources") as batch_op:
        batch_op.alter_column(
            "speech_type", new_column_name="category", existing_type=sa.String(100)
        )
        batch_op.add_column(sa.Column("voice", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("section_sources") as batch_op:
        batch_op.drop_column("voice")
        batch_op.alter_column(
            "category", new_column_name="speech_type", existing_type=sa.String(100)
        )
