import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from .models import User
from .sessions import require_session
from .sse_hub import publish, subscribe, unsubscribe

router = APIRouter(prefix="/api", tags=["sse"])

_HEARTBEAT_INTERVAL_SECONDS = 15.0


@router.get("/events")
async def events(request: Request, _user: User = Depends(require_session)):
    queue = await subscribe()

    async def event_generator() -> AsyncIterator[dict]:
        try:
            # Initial hello so the client knows the channel is live.
            yield {"event": "hello", "data": "{}"}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
                    yield {"event": "message", "data": payload}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            await unsubscribe(queue)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return EventSourceResponse(event_generator(), headers=headers)


@router.post("/events/test")
async def emit_test(_user: User = Depends(require_session)) -> dict:
    """Smoke-test endpoint — broadcasts a queue:hello event to all subscribers."""
    await publish("queue:hello", {"message": "hello from sidecar"})
    return {"published": True}
