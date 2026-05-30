"""fetch_queue: add source + source_id, allow nullable spotify_track_id

Revision ID: 0002_fetch_queue_source
Revises: 0001_initial
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_fetch_queue_source"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fetch_queue",
        sa.Column("source", sa.String(16), nullable=False, server_default=sa.text("'spotify'")),
    )
    op.add_column("fetch_queue", sa.Column("source_id", sa.String(64), nullable=True))
    op.execute("UPDATE fetch_queue SET source_id = spotify_track_id WHERE source_id IS NULL")
    op.alter_column("fetch_queue", "spotify_track_id", nullable=True)
    op.create_index("ix_fetch_queue_source_id", "fetch_queue", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_fetch_queue_source_id", table_name="fetch_queue")
    op.alter_column("fetch_queue", "spotify_track_id", nullable=False)
    op.drop_column("fetch_queue", "source_id")
    op.drop_column("fetch_queue", "source")
