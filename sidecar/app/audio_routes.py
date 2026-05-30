import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import jellyfin
from .config import settings
from .models import User
from .sessions import require_session

router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.get("/{item_id}/stream")
async def stream_audio(
    item_id: str,
    request: Request,
    _user: User = Depends(require_session),
) -> StreamingResponse:
    """Proxy Jellyfin's raw audio stream so the API key never reaches the browser.

    Forwards Range header so the HTML5 audio scrubber works.
    """
    url = jellyfin.audio_url(item_id)
    upstream_headers = {"X-Emby-Token": settings.jellyfin_api_key}
    range_header = request.headers.get("range")
    if range_header:
        upstream_headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=None)
    req = client.build_request("GET", url, headers=upstream_headers)
    resp = await client.send(req, stream=True)
    if resp.status_code not in (200, 206):
        await resp.aclose()
        await client.aclose()
        raise HTTPException(resp.status_code, "Audio unavailable")

    media_type = resp.headers.get("content-type") or "application/octet-stream"
    pass_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() in {"content-length", "content-range", "accept-ranges", "etag", "last-modified"}
    }

    async def body():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=resp.status_code,
        media_type=media_type,
        headers=pass_headers,
    )
