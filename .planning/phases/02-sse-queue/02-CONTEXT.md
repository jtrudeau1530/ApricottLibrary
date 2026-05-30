# Phase 2: SSE Hub + Queue Worker - Context

**Gathered:** 2026-05-30 (autonomous)
**Status:** Ready for planning

<domain>
## Phase Boundary

Fetch queue is operational end-to-end in the backend. Anyone can POST a Spotify track id → it is enqueued in Postgres → a single in-process worker picks it up, runs the existing librespot download, triggers a Jellyfin library refresh, and broadcasts SSE events that every connected browser (gated by session cookie) receives within a second.

**Not in this phase:** any frontend UI for the queue (Phase 4), Jellyfin proxy/catalog reads (Phase 3), metadata edits (Phase 5).
</domain>

<decisions>
## Implementation Decisions

### Worker
- Single in-process `asyncio.Task` started in FastAPI `lifespan`.
- Polls Postgres for the oldest `status='queued'` row with `SELECT … ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1`.
- Updates row to `status='running'`, sets `started_at`, sets `heartbeat_at` every 5s while downloading.
- On crash/restart: any `status='running'` row whose `heartbeat_at` is older than 60s is reset to `queued` on worker startup.
- One retry max per item (`attempts <= 1`); user can retry from API beyond that.

### Pub/sub
- `SSEHub` with a module-level `set[asyncio.Queue]` of subscriber queues.
- `publish(event_type, data)` puts JSON onto every subscriber's queue.
- Connection endpoint creates a queue, registers it, streams from it via `sse-starlette` `EventSourceResponse`, deregisters on disconnect.
- Heartbeats every 15s (ping comment) so Traefik doesn't close the connection at 60s.
- `X-Accel-Buffering: no` header on the SSE response (Coolify/Traefik pass-through).

### Events
- `queue:added` {id, track, artist, album, position, requester}
- `queue:progress` {id, percent}
- `queue:complete` {id, output_path}
- `queue:error` {id, error_message}
- `storage:update` {total_bytes, used_bytes, percent_used}
- `queue:retry` {id}

### Auth on SSE
- The SSE endpoint uses the same `Depends(require_session)` — cookie is sent by `EventSource` automatically because it's same-origin (single library.zektek.us domain).

### API surface (Phase 2)
- `POST /api/queue` — enqueue {spotify_track_id, track_name, artist_name, album_name, cover_url} → 202 with queue row
- `GET /api/queue` — list queued + running rows in order
- `GET /api/queue/history` — completed + failed rows, newest first, with pagination
- `POST /api/queue/{id}/retry` — resets a failed row back to queued
- `GET /api/events` — SSE stream

</decisions>

<code_context>
- Existing `librespot_session.download_track(track_id, output_path)` is the function the worker reuses. It is synchronous; worker calls it via `asyncio.to_thread`.
- Existing `spotify.get_track(track_id)` resolves metadata when enqueue request doesn't include it.
</code_context>

<specifics>
- Duplicate detection on enqueue: if any prior `fetch_queue` row with same `spotify_track_id` has `status in ('queued','running')` → return 409.
- "Already in library" check is deferred to Phase 3 (needs Jellyfin lookup).
</specifics>

<deferred>
- Drag-reorder admin endpoint (v2 — Q2-01).
- ETA computation (v2 — Q2-02).
</deferred>
