"""Durable AI stations and acquisition identity/retry state."""

from alembic import op
import sqlalchemy as sa

revision = "0003_discovery_stations"
down_revision = "0002_fetch_queue_source"
branch_labels = depends_on = None


def upgrade():
    op.add_column("fetch_queue", sa.Column("identity_key", sa.String(64)))
    op.create_unique_constraint(
        "uq_fetch_queue_identity_key", "fetch_queue", ["identity_key"]
    )
    op.add_column(
        "fetch_queue", sa.Column("next_attempt_at", sa.DateTime(timezone=True))
    )
    op.add_column("fetch_queue", sa.Column("duration_seconds", sa.Integer()))
    op.add_column("fetch_queue", sa.Column("warning_message", sa.Text()))
    op.create_table(
        "discovery_station",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(64),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sync_attempts", sa.Integer(), nullable=False),
        sa.Column("publish_radio", sa.Boolean(), nullable=False),
        sa.Column("radio_station_id", sa.String(5)),
        sa.Column(
            "playlist_id",
            sa.String(64),
            sa.ForeignKey("playlist.id", ondelete="SET NULL"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discovery_station_status", "discovery_station", ["status"])
    op.create_table(
        "discovery_track",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "station_id",
            sa.String(64),
            sa.ForeignKey("discovery_station.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("artist", sa.String(512), nullable=False),
        sa.Column("album", sa.String(512), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "queue_id",
            sa.String(64),
            sa.ForeignKey("fetch_queue.id", ondelete="SET NULL"),
        ),
        sa.Column("jellyfin_item_id", sa.String(64)),
        sa.Column("relative_path", sa.Text()),
        sa.Column("match_source", sa.String(24)),
        sa.Column("import_attempts", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("station_id", "identity_key", name="uq_discovery_track"),
    )
    op.create_index("ix_discovery_track_station_id", "discovery_track", ["station_id"])


def downgrade():
    op.drop_table("discovery_track")
    op.drop_table("discovery_station")
    op.drop_constraint("uq_fetch_queue_identity_key", "fetch_queue", type_="unique")
    for col in (
        "warning_message",
        "duration_seconds",
        "next_attempt_at",
        "identity_key",
    ):
        op.drop_column("fetch_queue", col)
