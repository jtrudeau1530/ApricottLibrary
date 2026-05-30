import logging
from typing import Any
from urllib.parse import quote

import httpx

from .config import settings

log = logging.getLogger("jellyfin")

_SORT_MAP = {
    "title": "SortName",
    "artist": "Artists,SortName",
    "album": "Album,SortName",
    "added": "DateCreated",
    "duration": "Runtime",
}


def _base_url() -> str:
    return settings.jellyfin_internal_url.rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "X-Emby-Token": settings.jellyfin_api_key,
        "Accept": "application/json",
    }


def _normalize_track(item: dict) -> dict[str, Any]:
    runtime_ticks = item.get("RunTimeTicks") or 0
    duration_seconds = round(runtime_ticks / 10_000_000) if runtime_ticks else None
    artists = item.get("Artists") or []
    if not artists:
        album_artists = item.get("AlbumArtists") or []
        artists = [a.get("Name") for a in album_artists if a.get("Name")]
    item_id = item.get("Id")
    album_id = item.get("AlbumId")
    has_track_image = bool((item.get("ImageTags") or {}).get("Primary"))
    if has_track_image and item_id:
        cover_target = item_id
    elif album_id:
        cover_target = album_id
    else:
        cover_target = item_id
    return {
        "id": item_id,
        "title": item.get("Name") or "",
        "artist": ", ".join(artists) if artists else "",
        "album": item.get("Album") or "",
        "duration_seconds": duration_seconds,
        "album_art_url": f"/api/catalog/cover/{cover_target}" if cover_target else None,
        "added_at": item.get("DateCreated"),
    }


async def list_tracks(
    sort: str = "added",
    descending: bool = True,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
) -> dict[str, Any]:
    """Pull a page of audio items from Jellyfin and normalize to Apricot shape."""
    sort_by = _SORT_MAP.get(sort, "DateCreated")
    params: dict[str, Any] = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": "Artists,AlbumArtists,Album,AlbumId,RunTimeTicks,DateCreated,ImageTags",
        "SortBy": sort_by,
        "SortOrder": "Descending" if descending else "Ascending",
        "Limit": limit,
        "StartIndex": offset,
    }
    if search:
        params["SearchTerm"] = search

    url = f"{_base_url()}/Items"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params, headers=_headers())
        if resp.status_code != 200:
            log.warning("Jellyfin Items returned %s: %s", resp.status_code, resp.text[:200])
            return {"count": 0, "total": 0, "items": []}
        body = resp.json()
    items = [_normalize_track(i) for i in body.get("Items", [])]
    return {
        "count": len(items),
        "total": body.get("TotalRecordCount", len(items)),
        "items": items,
    }


_TRACK_FIELDS = (
    "Artists,AlbumArtist,AlbumArtists,Album,AlbumId,"
    "RunTimeTicks,DateCreated,Overview,Path,"
    "Genres,Tags,ProductionYear,PremiereDate,IndexNumber,ParentIndexNumber,"
    "ImageTags,BackdropImageTags,AlbumPrimaryImageTag,"
    "ArtistItems,AlbumArtists,ProviderIds,"
    "ParentLogoItemId,ParentLogoImageTag,"
    "ParentBackdropItemId,ParentBackdropImageTags"
)


async def get_track(item_id: str) -> dict[str, Any] | None:
    """Use /Items?Ids= (works without UserId scope, unlike /Items/{id} in 10.9+)."""
    url = f"{_base_url()}/Items"
    params = {
        "Ids": item_id,
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": _TRACK_FIELDS,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params, headers=_headers())
        if resp.status_code != 200:
            log.warning("Jellyfin item lookup %s returned %s: %s", item_id, resp.status_code, resp.text[:200])
            return None
        body = resp.json()
    items = body.get("Items") or []
    if not items:
        return None
    raw = items[0]
    normalized = _normalize_track(raw)
    normalized["description"] = raw.get("Overview") or ""
    normalized["path"] = raw.get("Path")
    normalized["_raw"] = raw
    return normalized


async def get_item(item_id: str, fields: str = _TRACK_FIELDS) -> dict[str, Any] | None:
    url = f"{_base_url()}/Items"
    params = {"Ids": item_id, "Recursive": "true", "Fields": fields}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params, headers=_headers())
        if resp.status_code != 200:
            return None
        body = resp.json()
    items = body.get("Items") or []
    return items[0] if items else None


async def get_album_tracks(album_id: str) -> list[dict[str, Any]]:
    url = f"{_base_url()}/Items"
    params = {
        "ParentId": album_id,
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "SortBy": "ParentIndexNumber,IndexNumber,SortName",
        "Fields": "RunTimeTicks,IndexNumber,ParentIndexNumber",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params, headers=_headers())
        if resp.status_code != 200:
            return []
        body = resp.json()
    return body.get("Items") or []


async def get_song_view(item_id: str) -> dict[str, Any] | None:
    """Fully composed song-detail view: track + album + artist enrichment."""
    track = await get_track(item_id)
    if track is None:
        return None
    raw = track["_raw"]

    album_id = raw.get("AlbumId")
    album_raw: dict[str, Any] | None = None
    album_tracks: list[dict[str, Any]] = []
    if album_id:
        album_raw = await get_item(album_id, fields="Genres,Tags,ProductionYear,RunTimeTicks,ChildCount,Overview")
        album_tracks = await get_album_tracks(album_id)

    # Resolve the artist id through every fallback Jellyfin gives us, since
    # tagless OGGs leave ArtistItems empty even when Jellyfin inferred the artist
    # from the folder structure.
    artist_item_id: str | None = None
    for items_field in ("ArtistItems", "AlbumArtists"):
        items = raw.get(items_field) or []
        if items:
            artist_item_id = items[0].get("Id")
            break
    if not artist_item_id:
        artist_item_id = (
            raw.get("ParentBackdropItemId")
            or raw.get("ParentLogoItemId")
            or (album_raw or {}).get("ParentBackdropItemId")
            or (album_raw or {}).get("ParentLogoItemId")
        )
    # If album exists, check its AlbumArtists too as a last resort.
    if not artist_item_id and album_raw:
        for items_field in ("AlbumArtists", "ArtistItems"):
            items = album_raw.get(items_field) or []
            if items:
                artist_item_id = items[0].get("Id")
                break

    artist_raw: dict[str, Any] | None = None
    if artist_item_id:
        artist_raw = await get_item(
            artist_item_id,
            fields="Genres,Tags,BackdropImageTags,ImageTags,Overview,ProductionYear",
        )

    album_total_ticks = sum(t.get("RunTimeTicks") or 0 for t in album_tracks) if album_tracks else (
        (album_raw or {}).get("RunTimeTicks") or 0
    )
    album_duration_seconds = round(album_total_ticks / 10_000_000) if album_total_ticks else None
    track_count = (album_raw or {}).get("ChildCount") or len(album_tracks) or 1

    genres = (album_raw or {}).get("Genres") or raw.get("Genres") or []
    tags = list((album_raw or {}).get("Tags") or [])
    provider_ids = (album_raw or {}).get("ProviderIds") or raw.get("ProviderIds") or {}
    for key in provider_ids:
        if key.lower() == "musicbrainzalbum":
            tags.append("MusicBrainz Album")
        elif key.lower() == "musicbrainzalbumartist":
            tags.append("MusicBrainz Album Artist")
        elif key.lower() == "musicbrainzreleasegroup":
            tags.append("MusicBrainz Release Group")
        elif key.lower() == "theaudiodbalbum":
            tags.append("TheAudioDb Album")
    # de-dup preserving order
    seen: set[str] = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    year = (album_raw or {}).get("ProductionYear") or raw.get("ProductionYear")
    premiere = raw.get("PremiereDate")
    if not year and premiere:
        try:
            year = int(premiere[:4])
        except (TypeError, ValueError):
            year = None

    has_backdrop = bool(
        ((artist_raw or {}).get("BackdropImageTags"))
        or raw.get("ParentBackdropImageTags")
    )
    has_logo = bool(
        ((artist_raw or {}).get("ImageTags") or {}).get("Logo")
        or raw.get("ParentLogoImageTag")
    )
    backdrop_url = (
        f"/api/catalog/backdrop/{artist_item_id}" if artist_item_id and has_backdrop else None
    )
    logo_url = f"/api/catalog/logo/{artist_item_id}" if artist_item_id and has_logo else None

    cover_target = album_id
    if not cover_target or not (album_raw or raw.get("AlbumPrimaryImageTag")):
        cover_target = item_id
    cover_url_path = f"/api/catalog/cover/{cover_target}?max_width=900" if cover_target else None

    # Artist display name: track Artists → AlbumArtists → artist item Name → path inference.
    artist_name = track["artist"]
    if not artist_name:
        album_artists = raw.get("AlbumArtists") or (album_raw or {}).get("AlbumArtists") or []
        if album_artists:
            artist_name = ", ".join(a.get("Name", "") for a in album_artists if a.get("Name"))
    if not artist_name and artist_raw:
        artist_name = artist_raw.get("Name") or ""

    sibling_tracks = [
        {
            "id": t.get("Id"),
            "title": t.get("Name") or "",
            "index": t.get("IndexNumber"),
            "disc": t.get("ParentIndexNumber"),
            "duration_seconds": round((t.get("RunTimeTicks") or 0) / 10_000_000) if t.get("RunTimeTicks") else None,
            "is_current": t.get("Id") == item_id,
        }
        for t in album_tracks
    ] or [
        {
            "id": item_id,
            "title": track["title"],
            "index": raw.get("IndexNumber"),
            "disc": raw.get("ParentIndexNumber"),
            "duration_seconds": track["duration_seconds"],
            "is_current": True,
        }
    ]

    return {
        "track": {
            "id": track["id"],
            "title": track["title"],
            "artist": artist_name,
            "album": track["album"],
            "duration_seconds": track["duration_seconds"],
            "index": raw.get("IndexNumber"),
            "disc": raw.get("ParentIndexNumber"),
            "description": track["description"],
        },
        "album": {
            "id": album_id,
            "name": track["album"] or "Unknown album",
            "track_count": track_count,
            "duration_seconds": album_duration_seconds,
            "year": year,
            "cover_url": cover_url_path,
            "description": (album_raw or {}).get("Overview") or "",
        },
        "artist": {
            "id": artist_item_id,
            "name": artist_name,
            "backdrop_url": backdrop_url,
            "logo_url": logo_url,
        },
        "genres": genres,
        "tags": tags,
        "siblings": sibling_tracks,
    }


async def trigger_refresh() -> None:
    """Best-effort full-library refresh after a download."""
    url = f"{_base_url()}/Library/Refresh"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, headers=_headers())
    except Exception as exc:  # pragma: no cover
        log.warning("Jellyfin refresh failed: %s", exc)


async def update_metadata(item_id: str, payload: dict[str, Any]) -> bool:
    """POST /Items/{id} — Jellyfin metadata update. Pass `LockData=true` to keep edits.

    Jellyfin expects a full item shape; the caller should compose by GETting first then merging.
    """
    url = f"{_base_url()}/Items/{quote(item_id)}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        if resp.status_code not in (200, 204):
            log.warning("Jellyfin metadata update %s failed (%s): %s", item_id, resp.status_code, resp.text[:200])
            return False
    return True


def cover_url(item_id: str, max_width: int = 300) -> str:
    return f"{_base_url()}/Items/{quote(item_id)}/Images/Primary?maxWidth={max_width}"


def backdrop_url(item_id: str, max_width: int = 1600) -> str:
    return f"{_base_url()}/Items/{quote(item_id)}/Images/Backdrop?maxWidth={max_width}"


def logo_url(item_id: str, max_width: int = 800) -> str:
    return f"{_base_url()}/Items/{quote(item_id)}/Images/Logo?maxWidth={max_width}"


def audio_url(item_id: str) -> str:
    # /Items/{id}/Download streams the original file (no transcoding negotiation,
    # supports Range, content-type set from the file extension).
    return f"{_base_url()}/Items/{quote(item_id)}/Download?Static=true"
