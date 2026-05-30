"""MusicBrainz + Cover Art Archive metadata enrichment.

Used after a YouTube download lands on disk — we have a rough artist/track
guess from the YouTube title parse, and we want clean album, year, genre,
and a real cover image. MusicBrainz is free, no auth, no app-level rate
limit beyond ~1 req/sec for anonymous clients (must send a real User-Agent
per their etiquette policy).
"""
from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlencode

import httpx

log = logging.getLogger("musicbrainz")

MB_BASE = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"
USER_AGENT = "ApricottLibrary/1.0 (https://github.com/jtrudeau1530/ApricottLibrary)"

# MusicBrainz asks for ≤1 req/sec from anonymous clients.
_MIN_INTERVAL = 1.05
_last_call_at: float = 0.0
_call_lock = asyncio.Lock()


async def _throttled_get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
    """Enforce the 1 req/sec etiquette globally across the whole sidecar."""
    global _last_call_at
    async with _call_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        resp = await client.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        _last_call_at = time.monotonic()
        return resp


def _escape_lucene(s: str) -> str:
    """Escape Lucene-special characters in a MusicBrainz query term."""
    out = []
    for ch in s:
        if ch in '+-&|!(){}[]^"~*?:\\/':
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _build_recording_query(artist: str, title: str) -> str:
    parts = [f'recording:"{_escape_lucene(title)}"']
    if artist and artist.lower() != "unknown":
        parts.append(f'artist:"{_escape_lucene(artist)}"')
    return " AND ".join(parts)


async def enrich(artist: str, title: str) -> dict | None:
    """Look up the best MusicBrainz recording for (artist, title).

    Returns a dict with any of the keys: artist, album, year, genres (list),
    artist_mbid, release_mbid, cover_url. Returns None if no match.
    """
    if not title:
        return None
    query = _build_recording_query(artist, title)
    params = {
        "query": query,
        "fmt": "json",
        "limit": "5",
        "inc": "releases artists tags",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await _throttled_get(client, f"{MB_BASE}/recording/", params=params)
        except Exception as exc:  # pragma: no cover
            log.warning("MusicBrainz search failed: %s", exc)
            return None
        if resp.status_code != 200:
            log.warning(
                "MusicBrainz search %s -> %s body=%s",
                urlencode(params), resp.status_code, resp.text[:200],
            )
            return None

        body = resp.json()
        recordings = body.get("recordings") or []
        if not recordings:
            return None
        best = recordings[0]

        out: dict = {}
        # Artist
        artist_credit = best.get("artist-credit") or []
        if artist_credit:
            out["artist"] = "".join(
                ac.get("name") or ac.get("artist", {}).get("name") or ""
                for ac in artist_credit
            ).strip() or None
            first_artist = artist_credit[0].get("artist") or {}
            out["artist_mbid"] = first_artist.get("id")

        # Pick the earliest official album release.
        releases = best.get("releases") or []
        chosen_release = _pick_release(releases)
        if chosen_release:
            out["album"] = chosen_release.get("title")
            out["release_mbid"] = chosen_release.get("id")
            date = chosen_release.get("date") or ""
            if date and len(date) >= 4 and date[:4].isdigit():
                out["year"] = int(date[:4])

        # Tags → genres (rough — MB tags are folksonomy)
        tags = best.get("tags") or []
        if tags:
            ranked = sorted(tags, key=lambda t: -(t.get("count") or 0))
            out["genres"] = [t.get("name") for t in ranked[:3] if t.get("name")]

        # Cover Art Archive
        if out.get("release_mbid"):
            cover = await _fetch_caa_front(client, out["release_mbid"])
            if cover:
                out["cover_url"] = cover

    return out or None


def _pick_release(releases: list[dict]) -> dict | None:
    """Pick the release likeliest to give us a real album cover.

    Heuristic: prefer Album over Single/EP/Compilation, prefer Official status,
    prefer earliest date. Falls back to the first release if no candidates fit.
    """
    if not releases:
        return None

    def score(r: dict) -> tuple:
        rg = r.get("release-group") or {}
        primary = (rg.get("primary-type") or "").lower()
        status = (r.get("status") or "").lower()
        date = r.get("date") or "9999"
        return (
            0 if primary == "album" else 1 if primary in ("ep",) else 2,
            0 if status == "official" else 1,
            date,
        )

    return sorted(releases, key=score)[0]


async def _fetch_caa_front(client: httpx.AsyncClient, release_mbid: str) -> str | None:
    """Return the direct front-cover URL from Cover Art Archive, if one exists."""
    url = f"{CAA_BASE}/release/{release_mbid}"
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
    except Exception as exc:  # pragma: no cover
        log.debug("CAA fetch %s failed: %s", release_mbid, exc)
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    for image in body.get("images", []):
        if image.get("front"):
            thumbs = image.get("thumbnails") or {}
            return thumbs.get("large") or thumbs.get("500") or image.get("image")
    return None
