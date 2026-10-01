"""Backend provider readiness and redacted, actionable diagnostics."""

import asyncio
import importlib.util
import shutil
import time
from pathlib import Path
import httpx
from fastapi import HTTPException
from .config import settings


class ProviderFailure(RuntimeError):
    def __init__(self, provider, code, message, retryable=False):
        self.provider, self.code, self.retryable = provider, code, retryable
        super().__init__(message)


def safe_error(provider, exc):
    if isinstance(exc, ProviderFailure):
        return {
            "provider": provider,
            "code": exc.code,
            "message": str(exc),
            "retryable": exc.retryable,
        }
    status = (
        exc.status_code
        if isinstance(exc, HTTPException)
        else getattr(getattr(exc, "response", None), "status_code", None)
    )
    code = (
        f"http_{status}"
        if status
        else (
            "timeout"
            if isinstance(exc, (TimeoutError, httpx.TimeoutException))
            else "unavailable"
        )
    )
    message = "Provider unavailable; check backend connection and configuration."
    if status in (401, 403):
        message = "Provider authentication/access denied; reconnect or check runtime credentials."
    elif status == 429:
        message = "Provider rate limited; wait before retrying."
    elif code == "timeout":
        message = "Provider timed out; a later bounded retry may succeed."
    return {
        "provider": provider,
        "code": code,
        "message": message,
        "retryable": status == 429 or status is None or status >= 500,
    }


_token = ""
_until = 0
_auth_lock = asyncio.Lock()


async def slskd_headers():
    global _token, _until
    if settings.slskd_api_key:
        return {"X-API-Key": settings.slskd_api_key}
    if not settings.slskd_password:
        raise ProviderFailure(
            "soulseek",
            "not_configured",
            "Set Library SLSKD_PASSWORD (same configured slskd web credential) or SLSKD_API_KEY.",
        )
    async with _auth_lock:
        if time.monotonic() >= _until:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    settings.slskd_internal_url.rstrip("/") + "/api/v0/session",
                    json={
                        "username": settings.slskd_username,
                        "password": settings.slskd_password,
                    },
                )
            r.raise_for_status()
            _token = r.json()["token"]
            _until = time.monotonic() + 600
    return {"Authorization": "Bearer " + _token}


async def slskd_request(method, path, **kwargs):
    global _until
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.request(
            method,
            settings.slskd_internal_url.rstrip("/") + "/api/v0" + path,
            headers=await slskd_headers(),
            **kwargs,
        )
    if r.status_code == 401:
        _until = 0
    r.raise_for_status()
    return r.json() if r.content else None


async def require_slskd_shared_directory():
    options = await slskd_request("GET", "/options")
    download_dir = (options.get("directories") or {}).get("downloads")
    if not download_dir or Path(download_dir) != Path(settings.slskd_complete_path):
        raise ProviderFailure(
            "soulseek",
            "shared_path_configuration",
            "slskd completed downloads are not configured at SLSKD_COMPLETE_PATH. Set SLSKD_DOWNLOADS_DIR=/downloads/complete on slskd and mount the same downloads volume in Library. Existing downloads are preserved.",
        )


async def provider_readiness():
    result = [
        {
            "provider": "spotify_metadata",
            "ready": bool(
                settings.spotify_client_id and settings.spotify_client_secret
            ),
            "capability": "discovery / IDs / duration / artwork; not a full-audio download API",
        },
        {
            "provider": "spotify_audio",
            "ready": False,
            "capability": "Existing librespot session present"
            if (Path(settings.data_path) / "librespot_credentials.json").exists()
            else "No audio session configured",
            "message": "Spotify metadata credentials do not grant an export API. Automatic discovery does not decrypt Spotify streams or treat previews as complete songs.",
        },
        {
            "provider": "youtube",
            "ready": bool(
                importlib.util.find_spec("yt_dlp") and shutil.which("ffmpeg")
            ),
            "capability": "Unrestricted public audio only; configured tools do not guarantee source access",
        },
    ]
    try:
        state = await slskd_request("GET", "/server")
        ready = bool(state.get("isConnected") and state.get("isLoggedIn"))
        if ready:
            await require_slskd_shared_directory()
        result.append(
            {
                "provider": "soulseek",
                "ready": ready,
                "capability": "Peer-provided audio files",
                "message": "Connected and logged in; completed downloads must be mounted at SLSKD_COMPLETE_PATH."
                if ready
                else "slskd is not connected/logged in; check Soulseek login and outbound connectivity.",
            }
        )
    except Exception as e:
        result.append(
            {"provider": "soulseek", "ready": False, **safe_error("soulseek", e)}
        )
    return result
