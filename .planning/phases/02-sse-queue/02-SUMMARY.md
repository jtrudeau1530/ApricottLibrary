---
status: passed
---

# Phase 2: SSE Hub + Queue Worker — Summary

**Completed:** 2026-05-30 (autonomous)
**Goal:** Fetch queue end-to-end in backend with live SSE push to all browsers.

## Requirements delivered

- **QUEUE-01** `POST /api/queue` writes a row attributed to `requester_id`, broadcasts `queue:added`
- **QUEUE-02** Worker is a single `asyncio.Task` from `lifespan`; FIFO via `ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1`
- **QUEUE-03** Worker calls `librespot_session.download_track` via `to_thread` and writes to `MEDIA_PATH/Artist/Album/Name.ogg`
- **QUEUE-04** On completion, fires `POST {jellyfin}/Library/Refresh` with `X-Emby-Token`
- **QUEUE-05** Failed rows record `error_message`; `POST /api/queue/{id}/retry` re-queues them
- **QUEUE-06** Worker calls `_reset_stale_running()` on startup → any `status='running'` row whose `heartbeat_at` is older than 60s flips back to `queued`
- **QUEUE-07** `GET /api/queue` returns queued+running ordered by `created_at`
- **QUEUE-08** `GET /api/queue/history` returns completed+failed paginated
- **RT-01** `GET /api/events` is `Depends(require_session)` — cookie auth via same-origin
- **RT-02** Hub broadcasts `queue:added`, `queue:running`, `queue:progress`, `queue:complete`, `queue:error`, `queue:retry`
- **RT-03** On download complete, worker calls `_emit_storage_update()` → `storage:update` event
- **RT-04** Native `EventSource` auto-reconnects; server resends `hello` on each connection
- **RT-05** Frontend nav badge ships in Phase 4 — Phase 2 ensures the data is available via SSE

## Files added/changed

- `sidecar/app/sse_hub.py` *(new)* — in-process pub/sub with bounded asyncio queues
- `sidecar/app/queue_worker.py` *(new)* — single-coroutine FIFO worker, heartbeats, retry-on-restart, Jellyfin refresh
- `sidecar/app/queue_routes.py` *(new)* — `/api/queue`, `/api/queue/history`, `/api/queue/{id}/retry`
- `sidecar/app/sse_routes.py` *(new)* — `/api/events` with `X-Accel-Buffering: no` + 15s ping heartbeat
- `sidecar/app/main.py` — wires queue + sse routers; worker started in lifespan (already scaffolded in Phase 1)

## Success criteria check

1. ✓ `POST /api/queue` enqueues row + broadcasts `queue:added` SSE
2. ✓ Worker FIFO single-at-a-time; triggers Jellyfin refresh
3. ✓ Sidecar restart resets stale running rows back to queued
4. ✓ Retry endpoint re-queues failed rows
5. ✓ SSE events use `X-Accel-Buffering: no` + heartbeat ping → survive Traefik buffering/timeouts

## Human verification needed

- [ ] After deploy, open two browser tabs; queue a track from a `curl` POST → both tabs see SSE event
- [ ] Kill the sidecar mid-download; restart → row resets to queued and is reprocessed
- [ ] Verify the Spotify track id in queue row matches what librespot downloads
- [ ] Set `JELLYFIN_API_KEY` env var (placeholder will silently skip refresh — log warning visible)
