import json
import logging
import re
import time
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from .config import settings

log = logging.getLogger("librespot_session")

_session_lock = Lock()
_session = None

VALID_TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")


def credentials_path() -> Path:
    return Path(settings.data_path) / "librespot_credentials.json"


def has_credentials() -> bool:
    return credentials_path().exists()


def save_credentials(content: dict) -> None:
    if not isinstance(content, dict) or "username" not in content:
        raise HTTPException(400, "Invalid credentials shape — missing 'username'")
    if "credentials" not in content and "auth_data" not in content:
        raise HTTPException(
            400,
            "Invalid credentials shape — expected 'credentials' (librespot-python format) "
            "or 'auth_data' + 'auth_type' (Rust librespot format)",
        )
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content))
    _reset_session()


def _reset_session() -> None:
    global _session
    with _session_lock:
        _session = None


def _get_session():
    """Return a librespot Session, building it lazily from credentials.json. Retries
    on transient AP connection failures (Spotify's ApResolver sometimes hands back
    an unreachable address)."""
    global _session
    with _session_lock:
        if _session is not None:
            return _session
        if not has_credentials():
            raise HTTPException(
                401,
                "librespot credentials not present. POST /auth/librespot/credentials with your credentials.json.",
            )
        from librespot.core import Session

        last_err: Exception | None = None
        for attempt in range(1, 6):
            try:
                _session = Session.Builder().stored_file(str(credentials_path())).create()
                if attempt > 1:
                    log.info("librespot session ok on attempt %d", attempt)
                return _session
            except (ConnectionRefusedError, ConnectionError, OSError) as e:
                last_err = e
                log.warning("librespot session attempt %d failed: %s", attempt, e)
                time.sleep(0.5 * attempt)
        raise HTTPException(
            502,
            f"Could not connect to any Spotify access point after 5 attempts. "
            f"Last error: {last_err!r}. If this is persistent, the Coolify host "
            f"may be blocking outbound port 4070.",
        )


def download_track(spotify_track_id: str, output_path: Path) -> Path:
    """Stream a track via librespot and write OGG Vorbis bytes to output_path. Sync; run via to_thread.

    Retries once on 'Failed fetching audio key' — that error typically means the
    Spotify session has degraded after rapid sequential downloads. Resetting and
    rebuilding the session clears it.
    """
    if not VALID_TRACK_ID.match(spotify_track_id):
        raise HTTPException(400, f"Invalid Spotify track id: {spotify_track_id!r}")

    from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
    from librespot.metadata import TrackId

    track_id = TrackId.from_uri(f"spotify:track:{spotify_track_id}")
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            session = _get_session()
            stream = session.content_feeder().load(
                track_id, VorbisOnlyAudioQuality(AudioQuality.VERY_HIGH), False, None
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("wb") as f:
                while True:
                    chunk = stream.input_stream.stream().read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
            return output_path
        except Exception as exc:
            last_err = exc
            msg = str(exc).lower()
            transient = "audio key" in msg or "fetching audio key" in msg or "aes key" in msg
            if not transient or attempt == 3:
                raise
            log.warning(
                "Audio-key fetch failed for %s on attempt %d (%s) — resetting session and retrying",
                spotify_track_id, attempt, exc,
            )
            _reset_session()
            time.sleep(2.0 * attempt)
    # Unreachable — loop either returns or raises.
    raise last_err if last_err else RuntimeError("download_track exited loop unexpectedly")
