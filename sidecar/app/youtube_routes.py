"""YouTube playlist import — enumerate via yt-dlp, match against Spotify search
for clean metadata, queue with source='youtube' so the worker dispatches to
yt-dlp instead of librespot.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import youtube
from .db import get_db
from .models import FetchQueue, User
from .sessions import require_session
from .sse_hub import publish

log = logging.getLogger("youtube_routes")

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


@router.get("/debug/formats/{video_id}")
async def debug_formats(
    video_id: str,
    _user: User = Depends(require_session),
) -> dict:
    """Return the raw format list yt-dlp sees for one video.

    'Requested format is not available' means our selector matched none of
    the formats the chosen player_client returned — this lets us inspect
    exactly what's on offer so we can adjust the selector or the client.
    """
    info: dict | None = None
    error_message: str | None = None
    try:
        info = await asyncio.to_thread(_raw_formats, video_id)
    except Exception as exc:
        error_message = repr(exc)
    formats = (info or {}).get("formats") or []
    audio_only = [
        f for f in formats if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")
    ]
    return {
        "error": error_message,
        "title": (info or {}).get("title"),
        "uploader": (info or {}).get("uploader"),
        "format_count": len(formats),
        "audio_only_count": len(audio_only),
        "formats": [
            {
                "id": f.get("format_id"),
                "ext": f.get("ext"),
                "acodec": f.get("acodec"),
                "vcodec": f.get("vcodec"),
                "abr": f.get("abr"),
                "tbr": f.get("tbr"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "protocol": f.get("protocol"),
                "format_note": f.get("format_note"),
            }
            for f in formats[:40]
        ],
    }


def _raw_formats(video_id: str, *, use_cookies: bool = True, client: str | None = None) -> dict | None:
    import yt_dlp

    opts = {
        **youtube._yt_dlp_common_opts(),
        "skip_download": True,
        "ignoreerrors": False,
    }
    if not use_cookies:
        opts.pop("cookiefile", None)
    if client:
        # Replace only the youtube clients; keep the PoT plugin base_url.
        existing = opts.get("extractor_args") or {}
        existing = {**existing, "youtube": {"player_client": [client]}}
        opts["extractor_args"] = existing
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)


@router.get("/debug/verbose/{video_id}")
async def debug_verbose(
    video_id: str,
    _user: User = Depends(require_session),
) -> dict:
    """Run yt-dlp with verbose=True and capture all log output — lets us see
    whether the bgutil PoT plugin is actually being called and what tokens
    it returns (or what error it reports)."""
    import io
    import logging as _logging
    import yt_dlp

    buf = io.StringIO()
    handler = _logging.StreamHandler(buf)
    handler.setLevel(_logging.DEBUG)
    root_logger = _logging.getLogger()
    prev_level = root_logger.level
    root_logger.addHandler(handler)
    root_logger.setLevel(_logging.DEBUG)

    captured_messages: list[str] = []

    class _CapturingLogger:
        def debug(self, msg): captured_messages.append(f"DEBUG: {msg}")
        def info(self, msg): captured_messages.append(f"INFO: {msg}")
        def warning(self, msg): captured_messages.append(f"WARNING: {msg}")
        def error(self, msg): captured_messages.append(f"ERROR: {msg}")

    error_message: str | None = None
    format_count = 0
    try:
        opts = {
            **youtube._yt_dlp_common_opts(),
            "skip_download": True,
            "ignoreerrors": False,
            "verbose": True,
            "logger": _CapturingLogger(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(
                ydl.extract_info,
                f"https://www.youtube.com/watch?v={video_id}",
                False,
            )
        format_count = len((info or {}).get("formats") or [])
    except Exception as exc:
        error_message = str(exc)[:400]
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(prev_level)

    pot_relevant = [m for m in captured_messages if "pot" in m.lower() or "bgutil" in m.lower() or "token" in m.lower()]
    return {
        "format_count": format_count,
        "error": error_message,
        "pot_relevant_log_lines": pot_relevant[:50],
        "total_log_lines": len(captured_messages),
        "log_tail": captured_messages[-30:],
    }


@router.get("/debug/pot")
async def debug_pot(_user: User = Depends(require_session)) -> dict:
    """Health-check the bgutil-pot-provider sidecar service + show which
    yt-dlp plugins (specifically the PoT provider) are actually loaded.
    """
    import importlib
    import httpx
    from .config import settings as _settings

    pot_url = _settings.bgutil_pot_url
    ping: dict = {"url": pot_url}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{pot_url}/ping")
            ping["status_code"] = resp.status_code
            ping["body"] = resp.text[:300]
    except Exception as exc:
        ping["error"] = str(exc)[:200]

    plugin_info: dict = {}
    # The plugin is published as 'bgutil-ytdlp-pot-provider' on PyPI but
    # installs into the yt_dlp_plugins.extractor namespace under names like
    # 'getpot_bgutil_http' and 'getpot_bgutil_script'.
    for modname in (
        "yt_dlp_plugins.extractor.getpot_bgutil_http",
        "yt_dlp_plugins.extractor.getpot_bgutil_script",
        "yt_dlp_plugins.extractor.getpot_bgutil",
        "bgutil_ytdlp_pot_provider",
    ):
        try:
            mod = importlib.import_module(modname)
            plugin_info[modname] = {
                "import_ok": True,
                "version": getattr(mod, "__version__", "unknown"),
                "path": getattr(mod, "__file__", None),
            }
        except Exception as exc:
            plugin_info[modname] = {"import_ok": False, "error": str(exc)[:160]}

    # Walk the plugin directory to see what's actually on disk.
    import os
    plugin_dir_listing: dict = {}
    for d in [
        "/usr/local/lib/python3.12/site-packages/yt_dlp_plugins",
        "/usr/local/lib/python3.12/site-packages/yt_dlp_plugins/extractor",
    ]:
        try:
            plugin_dir_listing[d] = sorted(os.listdir(d))
        except Exception as exc:
            plugin_dir_listing[d] = f"error: {exc}"

    yt_dlp_plugins: list[str] = []
    try:
        from yt_dlp.plugins import directories  # type: ignore
        yt_dlp_plugins.append(f"plugin_dirs={list(directories())}")
    except Exception as exc:
        yt_dlp_plugins.append(f"directories error: {exc}")
    try:
        from yt_dlp.utils._utils import bug_reports_message  # noqa: F401
        import yt_dlp
        yt_dlp_plugins.append(f"yt_dlp version={yt_dlp.version.__version__}")
    except Exception as exc:
        yt_dlp_plugins.append(f"version probe error: {exc}")

    # Also try to enumerate registered PoT providers (if the framework exists)
    pot_providers: list[str] = []
    try:
        from yt_dlp.extractor.youtube.pot._registry import _ptp_registry  # type: ignore
        pot_providers = [str(p) for p in _ptp_registry]
    except Exception as exc:
        pot_providers.append(f"registry probe error: {exc}")

    return {
        "ping": ping,
        "plugin_info": plugin_info,
        "plugin_dir_listing": plugin_dir_listing,
        "yt_dlp_info": yt_dlp_plugins,
        "registered_pot_providers": pot_providers,
    }


@router.get("/debug/matrix/{video_id}")
async def debug_matrix(
    video_id: str,
    _user: User = Depends(require_session),
) -> dict:
    """Try every reasonable (cookies?, client) combo and report which one
    actually returns formats. Helps pinpoint whether cookies are the problem,
    a specific client is the problem, or the video really is PO-token-only.
    """
    combos: list[tuple[bool, str]] = [
        (False, "web"),
        (False, "tv_simply"),
        (False, "mweb"),
        (False, "ios"),
        (True, "web"),
        (True, "tv_simply"),
        (True, "mweb"),
        (True, "ios"),
    ]
    results: list[dict] = []
    for use_cookies, client in combos:
        try:
            info = await asyncio.to_thread(_raw_formats, video_id, use_cookies=use_cookies, client=client)
            formats = (info or {}).get("formats") or []
            audio_only = [
                f for f in formats
                if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")
            ]
            results.append({
                "cookies": use_cookies,
                "client": client,
                "ok": True,
                "format_count": len(formats),
                "audio_only_count": len(audio_only),
                "title": (info or {}).get("title"),
            })
        except Exception as exc:
            results.append({
                "cookies": use_cookies,
                "client": client,
                "ok": False,
                "error": str(exc)[:200],
            })
    return {"video_id": video_id, "cookies_uploaded": youtube.has_cookies(), "results": results}


@router.get("/debug")
async def debug_enumerate(
    url: str,
    _user: User = Depends(require_session),
) -> dict:
    """Diagnostic — runs yt-dlp against `url` and returns the raw extracted
    payload plus the normalized URL we'll actually use. Helps figure out
    whether yt-dlp can see the playlist at all (and if cookies are working).
    """
    normalized = youtube._normalize_playlist_url(url)
    has_cookies = youtube.has_cookies()
    info: dict | None = None
    error_message: str | None = None
    try:
        info = await asyncio.to_thread(_raw_extract, normalized)
    except Exception as exc:
        error_message = repr(exc)

    return {
        "input_url": url,
        "normalized_url": normalized,
        "cookies_present": has_cookies,
        "error": error_message,
        "type": (info or {}).get("_type") if info else None,
        "title": (info or {}).get("title") if info else None,
        "entry_count": len((info or {}).get("entries") or []) if info else 0,
        "first_entry_keys": (
            list(((info or {}).get("entries") or [{}])[0].keys())
            if info and info.get("entries")
            else None
        ),
        "playlist_id": (info or {}).get("id") if info else None,
        "uploader": (info or {}).get("uploader") if info else None,
    }


def _raw_extract(url: str) -> dict | None:
    import yt_dlp

    opts = {
        **youtube._yt_dlp_common_opts(),
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": False,  # surface errors so we see them
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


class PlaylistRequest(BaseModel):
    url: str = Field(min_length=10, max_length=500)


class YoutubeResolvedTrack(BaseModel):
    video_id: str
    track_name: str
    artist_name: str
    album_name: str = ""
    cover_url: str | None = None
    youtube_title: str


class YoutubeEnqueueRequest(BaseModel):
    tracks: list[YoutubeResolvedTrack] = Field(min_length=1, max_length=1000)


def _resolve_one(entry: dict) -> YoutubeResolvedTrack:
    """Parse a YouTube entry into a best-guess artist/track.

    Pure local parse — no external metadata lookup. The queue worker does the
    rich enrichment (MusicBrainz + Cover Art Archive) after download, so the
    preview stays instant and we don't burn rate-limit budget on tracks the
    user might never queue.
    """
    raw_title = entry.get("title") or ""
    channel = entry.get("channel") or ""
    artist_guess, track_guess = youtube.parse_title(raw_title, channel)
    return YoutubeResolvedTrack(
        video_id=entry["video_id"],
        track_name=track_guess,
        artist_name=artist_guess,
        album_name="",
        cover_url=entry.get("thumbnail"),
        youtube_title=raw_title,
    )


@router.post("/preview")
async def preview_playlist(
    body: PlaylistRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_session),
) -> dict:
    try:
        entries = await asyncio.to_thread(youtube.enumerate_playlist, body.url)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Could not read playlist: {exc}",
        )
    if not entries:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Playlist has no videos (or is private / unavailable).",
        )

    resolved = [_resolve_one(e) for e in entries]

    video_ids = [t.video_id for t in resolved]
    # Two-bucket dedup: queued/running -> already_queued (still in flight),
    # complete -> already_in_library (file already fetched). Previously the
    # complete bucket was missed entirely, so re-importing the same YouTube
    # playlist after the first run had finished would re-enqueue every
    # track and produce duplicate library files.
    rows = (
        await db.execute(
            select(FetchQueue.source_id, FetchQueue.status).where(
                FetchQueue.source == "youtube",
                FetchQueue.source_id.in_(video_ids),
                FetchQueue.status.in_(["queued", "running", "complete"]),
            )
        )
    ).all()
    queued_set = {sid for sid, st in rows if st in ("queued", "running")}
    library_set = {sid for sid, st in rows if st == "complete"}

    items = [
        {
            **t.model_dump(),
            "already_queued": t.video_id in queued_set,
            "already_in_library": t.video_id in library_set,
        }
        for t in resolved
    ]

    return {
        "found": len(entries),
        "queued_count": sum(1 for it in items if it["already_queued"]),
        "library_count": sum(1 for it in items if it["already_in_library"]),
        "tracks": items,
    }


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_resolved(
    body: YoutubeEnqueueRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")

    video_ids = [t.video_id for t in body.tracks]
    # Skip anything queued/running (still in flight) AND anything already
    # downloaded (status='complete'). Without the complete-bucket check,
    # re-importing a playlist after its first run produces duplicate
    # library files since the second pass sees an empty queue and treats
    # every video as fresh.
    rows = (
        await db.execute(
            select(FetchQueue.source_id, FetchQueue.status).where(
                FetchQueue.source == "youtube",
                FetchQueue.source_id.in_(video_ids),
                FetchQueue.status.in_(["queued", "running", "complete"]),
            )
        )
    ).all()
    queued_set = {sid for sid, st in rows if st in ("queued", "running")}
    library_set = {sid for sid, st in rows if st == "complete"}

    enqueued = 0
    skipped_queued = 0
    skipped_library = 0
    new_rows: list[FetchQueue] = []
    for t in body.tracks:
        if t.video_id in library_set:
            skipped_library += 1
            continue
        if t.video_id in queued_set:
            skipped_queued += 1
            continue
        new_rows.append(
            FetchQueue(
                source="youtube",
                source_id=t.video_id,
                spotify_track_id=None,
                track_name=t.track_name or t.youtube_title or "Unknown",
                artist_name=t.artist_name or "Unknown",
                album_name=t.album_name or "",
                cover_url=t.cover_url,
                requester_id=user.id,
            )
        )
        queued_set.add(t.video_id)
        enqueued += 1

    if new_rows:
        db.add_all(new_rows)
        await db.commit()
        for r in new_rows:
            await publish(
                "queue:added",
                {
                    "id": r.id,
                    "source": r.source,
                    "source_id": r.source_id,
                    "spotify_track_id": r.spotify_track_id,
                    "track_name": r.track_name,
                    "artist_name": r.artist_name,
                    "album_name": r.album_name,
                    "cover_url": r.cover_url,
                    "requester_id": r.requester_id,
                    "requester_username": user.username,
                    "status": r.status,
                    "progress": 0,
                    "error_message": None,
                    "attempts": 0,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "started_at": None,
                    "completed_at": None,
                },
            )

    return {
        "enqueued": enqueued,
        "skipped_queued": skipped_queued,
        "skipped_library": skipped_library,
    }
