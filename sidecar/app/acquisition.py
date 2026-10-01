"""Automatic public-source acquisition, using Library's existing YouTube/tag/art stack."""

import asyncio
import base64
import os
import shutil
import tempfile
from pathlib import Path

from mutagen.oggvorbis import OggVorbis
from mutagen.flac import Picture
from sqlalchemy import update

from . import youtube
from .config import settings
from .db import SessionLocal
from .models import FetchQueue
from .track_matching import choose_match, matches, media_file, probe


class TrackUnavailable(RuntimeError):
    pass


def embed_cover(audio_path: Path) -> bool:
    cover = audio_path.parent / "cover.jpg"
    if not cover.is_file():
        return False
    data = cover.read_bytes()
    if data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    else:
        return False
    picture = Picture()
    picture.type, picture.mime, picture.data = 3, mime, data
    audio = OggVorbis(audio_path)
    if audio.get("metadata_block_picture"):
        return True
    audio["metadata_block_picture"] = [
        base64.b64encode(picture.write()).decode("ascii")
    ]
    audio.save()
    return True


async def finish_art(row: FetchQueue, target: Path, cover_url: str | None):
    from .queue_worker import _save_album_cover

    cover_ok = await _save_album_cover(target.parent, cover_url)
    embedded = False
    if cover_ok:
        try:
            embedded = await asyncio.to_thread(embed_cover, target)
        except Exception:
            pass
    warning = (
        None
        if embedded
        else (
            "Audio imported; artwork could not be embedded"
            if cover_ok
            else "Audio imported; album artwork was unavailable"
        )
    )
    async with SessionLocal() as db:
        await db.execute(
            update(FetchQueue)
            .where(FetchQueue.id == row.id)
            .values(warning_message=warning)
        )
        await db.commit()


async def acquire(row: FetchQueue) -> Path:
    # Import helpers lazily: the queue worker owns legacy metadata/art behavior.
    from .queue_worker import _safe, _heartbeat

    wanted = {
        "title": row.track_name,
        "artist": row.artist_name,
        "album": row.album_name,
        "duration_seconds": row.duration_seconds,
    }
    target = (
        Path(settings.media_path)
        / _safe(row.artist_name)[:100]
        / _safe(row.album_name or "Singles")[:100]
        / f"{_safe(row.track_name)[:120]} [{row.identity_key[:12]}].ogg"
    )
    if not target.resolve().is_relative_to(Path(settings.media_path).resolve()):
        raise RuntimeError("Media output path escaped the configured library")
    if target.exists():
        meta = await asyncio.to_thread(probe, target)
        if meta and matches(wanted, meta):
            await finish_art(row, target, row.cover_url)
            return target
        raise TrackUnavailable(
            "An existing output file could not be verified; it was preserved"
        )

    # Recheck the filesystem in case another import completed after station planning.
    from .track_matching import scan_media

    catalog = await asyncio.to_thread(scan_media, settings.media_path)
    local_match, ambiguous = choose_match(wanted, catalog)
    if ambiguous:
        raise TrackUnavailable(
            "Multiple different local recordings share these tags; no automatic match"
        )
    if local_match:
        return Path(local_match["path"])

    await _heartbeat(row.id, 10)
    stage_root = Path(settings.downloads_path)
    stage_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"discovery-{row.id}-", dir=stage_root
    ) as directory:
        staged = Path(directory) / "audio.ogg"
        try:
            async with asyncio.timeout(settings.acquisition_timeout_seconds):
                expected = await download_with_fallback(row, wanted, staged)
        except TimeoutError as exc:
            raise RuntimeError(
                "Overall audio-provider timeout reached; bounded retry may be used. See the per-provider attempt details."
            ) from exc
        meta = await asyncio.to_thread(probe, staged)
        if not meta or abs(meta["duration_seconds"] - expected) > max(
            5, expected * 0.03
        ):
            raise TrackUnavailable(
                "Acquired audio failed format/duration validation; it was not imported"
            )

        # Reuse Library's existing MusicBrainz enrichment without changing identity.
        from .musicbrainz import enrich

        enriched = None
        try:
            enriched = await enrich(row.artist_name, row.track_name)
        except Exception:
            pass
        if enriched and not row.cover_url:
            row.cover_url = enriched.get("cover_url")

        def tag_and_import():
            audio = OggVorbis(staged)
            audio["title"] = row.track_name
            audio["artist"] = row.artist_name
            audio["album"] = row.album_name or "Singles"
            audio["apricott_identity"] = row.identity_key
            if enriched:
                if enriched.get("genres"):
                    audio["genre"] = enriched["genres"]
                if enriched.get("year"):
                    audio["date"] = str(enriched["year"])
                if enriched.get("artist_mbid"):
                    audio["musicbrainz_artistid"] = enriched["artist_mbid"]
                if enriched.get("release_mbid"):
                    audio["musicbrainz_albumid"] = enriched["release_mbid"]
            if row.spotify_track_id:
                audio["spotify_track_id"] = row.spotify_track_id
            audio.save()
            # Resolve parents before writing, including existing symlinks.
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.resolve().is_relative_to(Path(settings.media_path).resolve()):
                raise RuntimeError("Media output path escaped the configured library")
            # Copy across volumes then atomically link into place without overwriting.
            fd, temporary = tempfile.mkstemp(dir=target.parent, suffix=".part")
            os.close(fd)
            try:
                shutil.copyfile(staged, temporary)
                os.link(temporary, target)
            except FileExistsError:
                existing = probe(target)
                if not existing or not matches(
                    {**wanted, "duration_seconds": expected}, existing
                ):
                    raise TrackUnavailable(
                        "Concurrent output did not match; existing file was preserved"
                    )
            finally:
                Path(temporary).unlink(missing_ok=True)

        await asyncio.to_thread(tag_and_import)
    if not media_file(target, settings.media_path):
        raise RuntimeError("Imported audio is missing")
    await _heartbeat(row.id, 90)
    await finish_art(row, target, row.cover_url)
    return target


async def download_with_fallback(row, wanted, staged):
    from . import soulseek
    from .providers import ProviderFailure, safe_error

    errors = [
        e
        for e in (row.provider_errors or [])
        if e.get("provider") == "spotify_metadata"
    ]

    async def record(entry):
        errors.append(entry)
        async with SessionLocal() as db:
            await db.execute(
                update(FetchQueue)
                .where(FetchQueue.id == row.id)
                .values(provider_errors=errors[-20:])
            )
            await db.commit()

    for provider in ("soulseek", "youtube"):
        staged.unlink(missing_ok=True)
        try:
            if provider == "soulseek":
                expected = await soulseek.download(wanted, staged)
            else:
                candidates = await youtube.search_public_audio(
                    row.artist_name, row.track_name
                )
                candidates = [
                    c
                    for c in candidates
                    if c["preferred"]
                    and matches(wanted, c)
                    and c.get("duration_seconds")
                    and 15 <= c["duration_seconds"] <= 3600
                ]
                _, ambiguous = choose_match(wanted, candidates)
                if ambiguous:
                    raise ProviderFailure(
                        "youtube",
                        "ambiguous",
                        "Different YouTube recordings share the title; no confident duration/version match.",
                    )
                if not candidates:
                    raise ProviderFailure(
                        "youtube",
                        "no_match",
                        "No YouTube result matched artist/title/version and known duration. Official, artist-channel or Topic evidence required.",
                    )
                expected = None
                for candidate in candidates[:2]:
                    staged.unlink(missing_ok=True)
                    try:
                        await youtube.download_public_audio(
                            candidate["source_id"], staged
                        )
                        expected = (
                            wanted.get("duration_seconds")
                            or candidate["duration_seconds"]
                        )
                        meta = await asyncio.to_thread(probe, staged)
                        if not meta or abs(meta["duration_seconds"] - expected) > max(
                            5, expected * 0.03
                        ):
                            raise ProviderFailure(
                                "youtube",
                                "duration_mismatch",
                                "YouTube output duration does not match the requested recording.",
                            )
                        break
                    except Exception as exc:
                        await record(safe_error(provider, exc))
                        expected = None
                if expected is None:
                    raise ProviderFailure(
                        "youtube",
                        "candidates_failed",
                        "Both matching YouTube candidates failed; see provider diagnostics.",
                    )
            meta = await asyncio.to_thread(probe, staged)
            if not meta or abs(meta["duration_seconds"] - expected) > max(
                5, expected * 0.03
            ):
                raise ProviderFailure(
                    provider,
                    "invalid_audio",
                    "Provider delivered invalid or different-duration audio.",
                )
            await record(
                {
                    "provider": provider,
                    "code": "acquired",
                    "message": "Audio validated before Library import.",
                    "retryable": False,
                }
            )
            async with SessionLocal() as db:
                await db.execute(
                    update(FetchQueue)
                    .where(FetchQueue.id == row.id)
                    .values(duration_seconds=round(expected))
                )
                await db.commit()
            return expected
        except Exception as exc:
            await record(safe_error(provider, exc))
    message = "No audio provider acquired this recording. " + " ".join(
        f"{e['provider']}: {e['message']}"
        for e in errors
        if e.get("code") != "acquired"
    )
    if any(e.get("retryable") for e in errors):
        raise RuntimeError(message)
    raise TrackUnavailable(message)
