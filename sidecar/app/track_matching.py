"""Conservative recording matching: punctuation/Unicode normalization, no fuzzy guessing."""

import hashlib
import re
import unicodedata
from pathlib import Path

from mutagen import File as AudioFile


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def identity_key(artist: str, title: str) -> str:
    # Keep version words (live/remix/acoustic/etc.) and featured artists.
    return hashlib.sha256(
        f"{normalize(artist)}\n{normalize(title)}".encode()
    ).hexdigest()


def matches(wanted: dict, candidate: dict) -> bool:
    artists = candidate.get("artists") or [candidate.get("artist", "")]
    if normalize(wanted["artist"]) not in {normalize(a) for a in artists}:
        return False
    if normalize(wanted["title"]) != normalize(
        candidate.get("title") or candidate.get("name") or ""
    ):
        return False
    expected, actual = wanted.get("duration_seconds"), candidate.get("duration_seconds")
    if (
        expected
        and actual
        and abs(float(expected) - float(actual)) > max(5, float(expected) * 0.03)
    ):
        return False
    return True


def choose_match(wanted: dict, candidates: list[dict]) -> tuple[dict | None, bool]:
    matching = [c for c in candidates if matches(wanted, c)]
    album = normalize(wanted.get("album") or "")
    album_matches = [
        c for c in matching if album and normalize(c.get("album") or "") == album
    ]
    if album_matches:
        matching = album_matches
    durations = [
        float(c["duration_seconds"]) for c in matching if c.get("duration_seconds")
    ]
    # Different-length recordings with indistinguishable tags need attention,
    # even if picking the first search result would be convenient.
    if durations and max(durations) - min(durations) > max(5, min(durations) * 0.03):
        return None, True
    return (matching[0] if matching else None), False


def media_file(path: str | Path, root: str | Path) -> Path | None:
    root = Path(root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def probe(path: Path) -> dict | None:
    try:
        audio = AudioFile(path, easy=True)
        if audio is None or audio.info.length <= 0:
            return None
        tags = audio.tags or {}

        def first(key):
            values = tags.get(key) or []
            return str(values[0]) if values else ""

        return {
            "title": first("title"),
            "artist": first("artist"),
            "album": first("album"),
            "genres": list(tags.get("genre") or []),
            "duration_seconds": audio.info.length,
            "path": str(path),
        }
    except Exception:
        return None


def scan_media(root: str) -> list[dict]:
    results = []
    for path in Path(root).rglob("*"):
        if path.suffix.lower() not in {".ogg", ".flac", ".mp3", ".m4a", ".wav"}:
            continue
        safe = media_file(path, root)
        meta = probe(safe) if safe else None
        if meta:
            results.append(meta)
    return results
