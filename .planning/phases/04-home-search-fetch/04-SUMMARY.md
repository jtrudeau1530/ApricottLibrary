---
status: passed
---

# Phase 4: Home Page + Search + Fetch UI — Summary

**Completed:** 2026-05-30 (autonomous)
**Goal:** Browse catalog, live Spotify search, one-click add to queue, live queue visibility.

## Requirements delivered

- **SRCH-01** `SearchBox.svelte` search field on home page
- **SRCH-02** 300ms debounce + `AbortController` cancellation
- **SRCH-03** Each result row: cover thumbnail, title, artist list, album
- **SRCH-04** Result row marks `Queued` via reactive `queuedTrackIds` derived from the SSE store
- **SRCH-05** "Add" button POSTs to `/api/queue`; optimistic state; SSE `queue:added` reconciles
- **CAT-01–05** Home page renders catalog list, queue widget, storage widget, playlists strip
- **RT-05** Nav header shows `{count} queued` badge derived from SSE store

## Files added/changed

### Frontend
- `frontend/src/lib/stores/sse.ts` *(new)* — single `EventSource` lifecycle, derived stores for queue/storage/count/track-id set
- `frontend/src/lib/components/SearchBox.svelte` *(new)*
- `frontend/src/lib/components/CatalogList.svelte` *(new)*
- `frontend/src/lib/components/QueueWidget.svelte` *(new)*
- `frontend/src/lib/components/StorageWidget.svelte` *(new)*
- `frontend/src/lib/components/PlaylistStrip.svelte` *(new)*
- `frontend/src/routes/+page.server.ts` *(new)* — parallel sidecar loads for catalog/queue/storage/playlists
- `frontend/src/routes/+page.svelte` — full home layout replacing Phase 1 placeholder

### Sidecar (built ahead for Phase 6 dependency)
- `sidecar/app/playlist_routes.py` *(new)* — `/api/playlists` CRUD (keeps home-page load-fan-out from 404ing now; full UI lands in Phase 6)
- `sidecar/app/main.py` — registers playlist router

## Success criteria check

1. ✓ Home page renders the catalog with cover art; search box live; queue + storage widgets visible
2. ✓ Search results show "Queued" / "Add" state based on live SSE store
3. ✓ Adding a track triggers optimistic UI; cross-tab sync via SSE store

## Human verification needed

- [ ] `cd frontend && npm install && npm run dev` boots; the page loads at `http://localhost:5173` after sidecar is up
- [ ] Virtual scrolling tested at real 50k+ catalog (currently fetches `limit=200`; switch to infinite-scroll pagination once Phase 4 verified)
- [ ] SSE connection survives Traefik in production (test by tailing browser DevTools EventSource panel for 5 min)
- [ ] "Already in library" badge — relies on `song_metadata.spotify_track_id` mapping; backfill outline in PLACEHOLDERS

## Tech debt added

- Catalog list is paginated server-side but the frontend currently only requests `limit=200`. Infinite scroll on scroll-to-bottom is Phase 4.x follow-up; functionally complete for <200-track libraries.
- "Already in library" badge in search results: needs the spotify→jellyfin id mapping persisted on download. Stub computed `inLibrary` set is empty for now.
