# Phase 3: Jellyfin Catalog Proxy - Context

**Gathered:** 2026-05-30 (autonomous)

<domain>
Sidecar exposes normalized catalog, cover-art, audio, and storage endpoints. Jellyfin API key never reaches the browser. Audio supports Range requests so the HTML5 player can seek.
</domain>

<decisions>
- New `sidecar/app/jellyfin.py` — async httpx client; uses `X-Emby-Token` header (not `?api_key=` query — deprecated).
- Audio stream proxies Jellyfin `/Audio/{id}/universal?Container=ogg,opus,mp3&UserId=…` — actually use the simpler `/Audio/{id}/stream` with Range pass-through.
- Cover art proxies `/Items/{id}/Images/Primary?maxWidth=300` (small list thumb) and `?maxWidth=600` for detail.
- Catalog normalized output: `{id, title, artist, album, duration_seconds, album_art_url, added_at}`.
- Sort keys (CAT-03): map to Jellyfin `SortBy=SortName|Artist|Album|DateCreated`.
- Spotify track id (used for "already in library" check in search) lives in `song_metadata.spotify_track_id`. Phase 3 only reads — Phase 4 writes when a fetch completes successfully (TODO in queue_worker `_mark_complete` — added as a tech-debt note rather than implemented here, since we'd need Jellyfin → song_metadata reconciliation after rescan).
</decisions>

<code_context>
- httpx already pinned (used by Spotify client). Reuse for Jellyfin.
- StreamingResponse handles audio passthrough.
</code_context>

<specifics>
None.
</specifics>

<deferred>
- spotify_track_id → song_metadata reconciliation: needs a Phase 4 hook in queue_worker `_mark_complete` to look up the newly-scanned Jellyfin item and persist the mapping. Captured as tech debt in PLACEHOLDERS.md.
</deferred>
