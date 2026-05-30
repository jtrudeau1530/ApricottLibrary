import json
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import librespot_session
from .config import settings

router = APIRouter(prefix="/auth/spotify", tags=["auth"])

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = "streaming user-read-private user-read-email playlist-read-private playlist-read-collaborative"
STATE_TTL_SECONDS = 600

_pending_states: dict[str, float] = {}


def _token_file() -> Path:
    return Path(settings.data_path) / "spotify_tokens.json"


def _save_tokens(data: dict) -> None:
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _load_tokens() -> dict | None:
    path = _token_file()
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _prune_states() -> None:
    now = time.time()
    expired = [s for s, exp in _pending_states.items() if exp < now]
    for s in expired:
        _pending_states.pop(s, None)


@router.get("/login")
async def login() -> RedirectResponse:
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        raise HTTPException(503, "Spotify credentials not configured")

    _prune_states()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time() + STATE_TTL_SECONDS

    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": SCOPES,
        "state": state,
        "show_dialog": "false",
    }
    return RedirectResponse(f"{AUTH_URL}?{urllib.parse.urlencode(params)}")


@router.get("/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        raise HTTPException(400, f"Spotify auth error: {error}")
    if not code or not state:
        raise HTTPException(400, "Missing code or state")

    expiry = _pending_states.pop(state, None)
    if expiry is None or time.time() > expiry:
        raise HTTPException(400, "Invalid or expired state")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
            },
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"Token exchange failed: {resp.text}")

    payload = resp.json()
    tokens = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + payload["expires_in"],
        "scope": payload.get("scope"),
        "token_type": payload.get("token_type", "Bearer"),
    }
    _save_tokens(tokens)

    return HTMLResponse(
        "<h1>Spotify connected.</h1>"
        "<p>You can close this tab. The Library will use this account for downloads.</p>"
    )


@router.get("/status")
async def status() -> dict:
    tokens = _load_tokens()
    if not tokens:
        return {"connected": False}
    return {
        "connected": True,
        "scope": tokens.get("scope"),
        "expires_at": tokens["expires_at"],
        "expired": tokens["expires_at"] < time.time(),
    }


librespot_router = APIRouter(prefix="/auth/librespot", tags=["auth"])


@librespot_router.get("/status")
async def librespot_status() -> dict:
    return {"connected": librespot_session.has_credentials()}


@librespot_router.post("/credentials")
async def librespot_credentials(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(400, f"Body must be JSON: {e}")
    librespot_session.save_credentials(body)
    return {"status": "saved"}


async def get_user_access_token() -> str:
    """Return a valid user access token, refreshing if expired. Used by /download."""
    tokens = _load_tokens()
    if not tokens:
        raise HTTPException(401, "Spotify account not connected. Visit /auth/spotify/login.")

    if tokens["expires_at"] > time.time() + 30:
        return tokens["access_token"]

    refresh = tokens.get("refresh_token")
    if not refresh:
        raise HTTPException(401, "No refresh token; reconnect at /auth/spotify/login.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh},
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )

    if resp.status_code != 200:
        raise HTTPException(401, f"Refresh failed; reconnect at /auth/spotify/login: {resp.text}")

    payload = resp.json()
    tokens["access_token"] = payload["access_token"]
    tokens["expires_at"] = time.time() + payload["expires_in"]
    if "refresh_token" in payload:
        tokens["refresh_token"] = payload["refresh_token"]
    if "scope" in payload:
        tokens["scope"] = payload["scope"]
    _save_tokens(tokens)
    return tokens["access_token"]
