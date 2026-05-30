import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("sse_hub")

_subscribers: set[asyncio.Queue] = set()
_lock = asyncio.Lock()


async def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    async with _lock:
        _subscribers.add(q)
    log.info("SSE subscriber added (total=%d)", len(_subscribers))
    return q


async def unsubscribe(q: asyncio.Queue) -> None:
    async with _lock:
        _subscribers.discard(q)
    log.info("SSE subscriber removed (total=%d)", len(_subscribers))


async def publish(event_type: str, data: Any) -> None:
    payload = json.dumps({"type": event_type, "data": data}, default=str)
    dead: list[asyncio.Queue] = []
    async with _lock:
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _subscribers.discard(q)
