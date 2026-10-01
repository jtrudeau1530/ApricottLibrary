"""Library-owned discovery and bounded schedules; preserve legacy jobs/media."""

from alembic import op
import sqlalchemy as sa

revision = "0004_library_discovery"
down_revision = "0003_discovery_stations"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "fetch_queue",
        sa.Column("provider_errors", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "discovery_station",
        sa.Column("generation_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("discovery_station", sa.Column("generation_message", sa.Text()))
    op.add_column("discovery_station", sa.Column("schedule_id", sa.String(64)))
    op.create_table(
        "discovery_schedule",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(64),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("max_runs", sa.Integer(), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
    )
    # Account for the known pre-correction generation call in legacy jobs.
    op.execute(
        "UPDATE discovery_station SET generation_calls=CASE WHEN EXISTS (SELECT 1 FROM discovery_track WHERE station_id=discovery_station.id) THEN 1 ELSE LEAST(attempts,3) END WHERE schedule_id IS NULL"
    )
    # A legacy pending Radio publish now finishes acquisition in Library only.
    op.execute(
        "UPDATE discovery_station SET publish_radio=false, status=CASE WHEN status IN ('syncing','sync_failed') THEN 'acquiring' ELSE status END"
    )


def downgrade():
    op.drop_table("discovery_schedule")
    for c in ("schedule_id", "generation_message", "generation_calls"):
        op.drop_column("discovery_station", c)
    op.drop_column("fetch_queue", "provider_errors")
