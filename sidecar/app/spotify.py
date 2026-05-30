import time

import httpx
from fastapi import HTTPException

from .config import settings

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
TRACK_URL = "https://api.spotify.com/v1/tracks/{id}"


class SpotifyClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._client = httpx.AsyncClient(timeout=10.0)

    async def _get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 30:
            return self._token

        if not settings.spotify_client_id or not settings.spotify_client_secret:
            raise HTTPException(
                status_code=503,
                detail="Spotify credentials not configured",
            )

        resp = await self._client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Spotify token request failed ({resp.status_code}): {resp.text[:200]}",
            )
        payload = resp.json()
        self._token = payload["access_token"]
        self._expires_at = time.time() + payload["expires_in"]
        return self._token

    async def search_tracks(self, query: str, limit: int = 20) -> list[dict]:
        token = await self._get_token()
        resp = await self._client.get(
            SEARCH_URL,
            params={"q": query, "type": "track", "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Spotify search failed ({resp.status_code}): {resp.text[:200]}",
            )
        items = resp.json().get("tracks", {}).get("items", [])
        return [_to_track(item) for item in items]

    async def get_track(self, track_id: str) -> dict | None:
        token = await self._get_token()
        resp = await self._client.get(
            TRACK_URL.format(id=track_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _to_track(resp.json())


def _to_track(item: dict) -> dict:
    album = item.get("album", {}) or {}
    images = album.get("images", []) or []
    return {
        "id": item["id"],
        "name": item["name"],
        "artists": [a["name"] for a in item.get("artists", [])],
        "album": album.get("name"),
        "duration_ms": item.get("duration_ms"),
        "explicit": item.get("explicit", False),
        "isrc": (item.get("external_ids") or {}).get("isrc"),
        "cover_url": images[0]["url"] if images else None,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
    }


spotify = SpotifyClient()
