"""initial schema — user, session, fetch_queue, song_metadata, playlist, playlist_item

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "session",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_session_user_id", "session", ["user_id"])
    op.create_index("ix_session_expires_at", "session", ["expires_at"])

    op.create_table(
        "fetch_queue",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("spotify_track_id", sa.String(32), nullable=False),
        sa.Column("track_name", sa.String(512), nullable=False),
        sa.Column("artist_name", sa.String(512), nullable=False),
        sa.Column("album_name", sa.String(512), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text()),
        sa.Column("requester_id", sa.String(64), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("output_path", sa.Text()),
    )
    op.create_index("ix_fetch_queue_spotify_track_id", "fetch_queue", ["spotify_track_id"])
    op.create_index("ix_fetch_queue_status", "fetch_queue", ["status"])
    op.create_index("ix_fetch_queue_created_at", "fetch_queue", ["created_at"])

    op.create_table(
        "song_metadata",
        sa.Column("jellyfin_item_id", sa.String(64), primary_key=True),
        sa.Column("spotify_track_id", sa.String(32)),
        sa.Column("title", sa.String(512)),
        sa.Column("artist", sa.String(512)),
        sa.Column("album", sa.String(512)),
        sa.Column("description", sa.Text()),
        sa.Column("updated_by", sa.String(64), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_song_metadata_spotify_track_id", "song_metadata", ["spotify_track_id"])

    op.create_table(
        "playlist",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("user.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "playlist_item",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("playlist_id", sa.String(64), sa.ForeignKey("playlist.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jellyfin_item_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("playlist_id", "jellyfin_item_id", name="uq_playlist_item"),
    )


def downgrade() -> None:
    op.drop_table("playlist_item")
    op.drop_table("playlist")
    op.drop_index("ix_song_metadata_spotify_track_id", table_name="song_metadata")
    op.drop_table("song_metadata")
    op.drop_index("ix_fetch_queue_created_at", table_name="fetch_queue")
    op.drop_index("ix_fetch_queue_status", table_name="fetch_queue")
    op.drop_index("ix_fetch_queue_spotify_track_id", table_name="fetch_queue")
    op.drop_table("fetch_queue")
    op.drop_index("ix_session_expires_at", table_name="session")
    op.drop_index("ix_session_user_id", table_name="session")
    op.drop_table("session")
    op.drop_table("user")
