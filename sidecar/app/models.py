from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid4().hex


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return bool(self.permissions.get("is_admin"))

    @property
    def can_fetch(self) -> bool:
        return self.is_admin or bool(self.permissions.get("can_fetch", True))

    @property
    def can_edit_metadata(self) -> bool:
        return self.is_admin or bool(self.permissions.get("can_edit_metadata", False))


class Session(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    user: Mapped[User] = relationship(back_populates="sessions")


class FetchQueue(Base):
    __tablename__ = "fetch_queue"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="spotify", index=True)
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)
    spotify_track_id: Mapped[str | None] = mapped_column(String(32), index=True)
    track_name: Mapped[str] = mapped_column(String(512), nullable=False)
    artist_name: Mapped[str] = mapped_column(String(512), nullable=False)
    album_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    cover_url: Mapped[str | None] = mapped_column(Text)
    requester_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_path: Mapped[str | None] = mapped_column(Text)
    identity_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    warning_message: Mapped[str | None] = mapped_column(Text)
    provider_errors: Mapped[list] = mapped_column(JSON, default=list)


class SongMetadata(Base):
    """Apricot's own metadata view of a Jellyfin track — survives Jellyfin rescans that clobber edits."""

    __tablename__ = "song_metadata"

    jellyfin_item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spotify_track_id: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    artist: Mapped[str | None] = mapped_column(String(512))
    album: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)


class Playlist(Base):
    __tablename__ = "playlist"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    items: Mapped[list["PlaylistItem"]] = relationship(back_populates="playlist", cascade="all, delete-orphan")


class PlaylistItem(Base):
    __tablename__ = "playlist_item"
    __table_args__ = (UniqueConstraint("playlist_id", "jellyfin_item_id", name="uq_playlist_item"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlist.id", ondelete="CASCADE"), nullable=False)
    jellyfin_item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    playlist: Mapped[Playlist] = relationship(back_populates="items")


class DiscoveryStation(Base):
    __tablename__ = "discovery_station"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    prompt: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(120))
    requested_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0)
    generation_calls: Mapped[int] = mapped_column(Integer, default=0)
    generation_message: Mapped[str | None] = mapped_column(Text)
    schedule_id: Mapped[str | None] = mapped_column(String(64))
    publish_radio: Mapped[bool] = mapped_column(Boolean, default=True)
    radio_station_id: Mapped[str | None] = mapped_column(String(5))
    playlist_id: Mapped[str | None] = mapped_column(ForeignKey("playlist.id", ondelete="SET NULL"))
    error_message: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)


class DiscoveryTrack(Base):
    __tablename__ = "discovery_track"
    __table_args__ = (UniqueConstraint("station_id", "identity_key", name="uq_discovery_track"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    station_id: Mapped[str] = mapped_column(ForeignKey("discovery_station.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str] = mapped_column(String(512))
    album: Mapped[str] = mapped_column(String(512), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    identity_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="matching")
    queue_id: Mapped[str | None] = mapped_column(ForeignKey("fetch_queue.id", ondelete="SET NULL"))
    jellyfin_item_id: Mapped[str | None] = mapped_column(String(64))
    relative_path: Mapped[str | None] = mapped_column(Text)
    match_source: Mapped[str | None] = mapped_column(String(24))
    import_attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class DiscoverySchedule(Base):
    __tablename__ = "discovery_schedule"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(String(500))
    count: Mapped[int] = mapped_column(Integer, default=20)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    max_runs: Mapped[int] = mapped_column(Integer, default=30)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_error: Mapped[str | None] = mapped_column(Text)
