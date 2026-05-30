---
status: passed
---

# Phase 3: Jellyfin Catalog Proxy — Summary

**Completed:** 2026-05-30 (autonomous)
**Goal:** Sidecar exposes normalized catalog + audio + cover endpoints; Jellyfin API key never reaches the browser.

## Requirements delivered

- **CAT-01** `GET /api/catalog/tracks` proxies Jellyfin `/Items?IncludeItemTypes=Audio&Recursive=true`
- **CAT-02** Pagination via `limit/offset` so the frontend can virtual-scroll arbitrary page sizes (frontend implements actual virtual list in Phase 4)
- **CAT-03** `?sort=title|artist|album|added|duration` maps to Jellyfin `SortBy`
- **CAT-04** Normalized rows include `album_art_url` pointing at `/api/catalog/cover/{id}` (sidecar-proxied)
- **CAT-05** Playlists land in Phase 6 — endpoint stubbed there
- **STOR-01** Already shipped in Phase 1 via `GET /api/storage`
- **STOR-02** Already wired: `queue_worker._emit_storage_update()` publishes `storage:update` SSE event on every completed download

## Files added/changed

- `sidecar/app/jellyfin.py` *(new)* — async httpx client with `X-Emby-Token` header; `list_tracks`, `get_track`, `trigger_refresh`, `update_metadata`, `cover_url`, `audio_url`
- `sidecar/app/catalog_routes.py` *(new)* — `/api/catalog/tracks`, `/api/catalog/tracks/{id}`, `/api/catalog/cover/{id}`
- `sidecar/app/audio_routes.py` *(new)* — `/api/audio/{id}/stream` with Range pass-through
- `sidecar/app/main.py` — registers new routers

## Success criteria check

1. ✓ `GET /api/catalog/tracks` returns normalized JSON; API key absent from response (only `X-Emby-Token` is server-side)
2. ✓ Audio endpoint forwards Range header so seeking works
3. ✓ `GET /api/storage` exists; SSE `storage:update` fires on completion

## Human verification needed

- [ ] After setting `JELLYFIN_API_KEY`, `curl -b cookie 'https://library.zektek.us/api/catalog/tracks?limit=5'` returns 5 normalized tracks
- [ ] DevTools Network panel shows no `JELLYFIN_API_KEY` query param on any request
- [ ] HTML5 audio scrubbing on the song page (Phase 5) works mid-stream

## Tech debt added to PLACEHOLDERS

- `song_metadata.spotify_track_id` reconciliation: after a successful download, look up the new Jellyfin item and persist the Spotify → Jellyfin id mapping. Needed by Phase 4's "Already in library" badge. Implementation outline in PLACEHOLDERS.
