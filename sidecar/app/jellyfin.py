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
    item_id = item.get("Id")
    return {
        "id": item_id,
        "title": item.get("Name") or "",
        "artist": ", ".join(artists) if artists else "",
        "album": item.get("Album") or "",
        "duration_seconds": duration_seconds,
        "album_art_url": f"/api/catalog/cover/{item_id}" if item_id else None,
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
        "Fields": "Artists,Album,RunTimeTicks,DateCreated",
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


async def get_track(item_id: str) -> dict[str, Any] | None:
    url = f"{_base_url()}/Items/{quote(item_id)}"
    params = {"Fields": "Artists,Album,RunTimeTicks,DateCreated,Overview,Path"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params, headers=_headers())
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            log.warning("Jellyfin item %s returned %s", item_id, resp.status_code)
            return None
        body = resp.json()
    normalized = _normalize_track(body)
    normalized["description"] = body.get("Overview") or ""
    normalized["path"] = body.get("Path")
    normalized["_raw"] = body
    return normalized


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


def audio_url(item_id: str) -> str:
    # Jellyfin's /Audio/{id}/stream returns the raw file; Range supported.
    return f"{_base_url()}/Audio/{quote(item_id)}/stream"
