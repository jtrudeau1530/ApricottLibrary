import logging
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from .auth import get_user_access_token
from .config import settings

log = logging.getLogger("spotify")

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

    async def _bearer(self) -> str:
        """User OAuth token (preferred — Spotify deprecated client-credentials for search).
        Falls back to client credentials only as a last resort, so older deploys keep working.
        """
        try:
            return await get_user_access_token()
        except HTTPException as exc:
            # No user token connected yet — try client credentials as fallback.
            log.info("User token unavailable (%s); falling back to client credentials.", exc.detail)
            return await self._get_token()

    async def search_tracks(self, query: str, limit: int = 20) -> list[dict]:
        token = await self._bearer()
        safe_limit = max(1, min(int(limit), 50))
        resp = await self._client.get(
            SEARCH_URL,
            params={"q": query, "type": "track", "limit": str(safe_limit)},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            log.warning(
                "Spotify search url=%s status=%s body=%s",
                resp.request.url, resp.status_code, resp.text[:300],
            )
            hint = ""
            if resp.status_code in (401, 403):
                hint = " (token rejected — try /api/auth/spotify/login to reconnect)"
            elif resp.status_code == 400 and "limit" in resp.text.lower():
                hint = " (Spotify rejects client-credentials tokens here — connect your account at /api/auth/spotify/login)"
            raise HTTPException(
                status_code=502,
                detail=f"Spotify search failed ({resp.status_code}){hint}: {resp.text[:200]}",
            )
        items = resp.json().get("tracks", {}).get("items", [])
        return [_to_track(item) for item in items]

    async def debug_search(self, query: str, limit: int = 20) -> dict:
        """Diagnostic — returns the literal URL we built + Spotify's full response."""
        token = await self._bearer()
        safe_limit = max(1, min(int(limit), 50))
        resp = await self._client.get(
            SEARCH_URL,
            params={"q": query, "type": "track", "limit": str(safe_limit)},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        return {
            "sent_url": str(resp.request.url),
            "sent_headers": dict(resp.request.headers),
            "status_code": resp.status_code,
            "response_headers": dict(resp.headers),
            "body": resp.text[:1000],
            "token_prefix": (token or "")[:12] + "…",
            "client_id_set": bool(settings.spotify_client_id),
            "client_secret_set": bool(settings.spotify_client_secret),
        }

    async def get_track(self, track_id: str) -> dict | None:
        token = await self._bearer()
        resp = await self._client.get(
            TRACK_URL.format(id=track_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Spotify track lookup failed ({resp.status_code}): {resp.text[:200]}",
            )
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
