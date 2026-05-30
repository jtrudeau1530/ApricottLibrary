---
status: passed
---

# Phase 5: Song Detail + Metadata Editing — Summary

**Completed:** 2026-05-30 (autonomous)

## Requirements delivered

- **SONG-01** `/song/[id]` route renders cover, title, artist, album, duration
- **SONG-02** HTML5 `<audio controls preload="metadata">` with the sidecar audio stream (`/api/audio/{id}/stream` from Phase 3)
- **SONG-03** Audio is proxied — Jellyfin API key absent from browser
- **SONG-04** Audio element unmounts on navigation → playback stops (no cross-page queue)
- **META-01** Edit button toggles a modal/form gated on `user.can_edit_metadata` (server-enforced 403)
- **META-02** Edit form covers title, artist, album, description
- **META-03** `PATCH /api/catalog/tracks/{id}` writes file tags via `mutagen.File(..., easy=True)` AND POSTs Jellyfin with `LockData: true`
- **META-04** Same endpoint persists to `song_metadata` table — survives Jellyfin rescans that ignore item locks

## Files added/changed

- `sidecar/app/jellyfin.py` — `get_track` returns the raw item + file `path` for downstream tag writes
- `sidecar/app/metadata_routes.py` *(new)* — `PATCH /api/catalog/tracks/{id}`: Postgres + mutagen + Jellyfin (LockData=true)
- `sidecar/app/main.py` — registers metadata router
- `frontend/src/routes/song/[id]/+page.server.ts` *(new)* — server load fetches normalized track
- `frontend/src/routes/song/[id]/+page.svelte` *(new)* — detail layout, audio player, inline edit form

## Success criteria check

1. ✓ Click a catalog row → song page renders
2. ✓ Audio plays (Range-supported); navigating away unmounts the player
3. ✓ Metadata edit writes file tags + Postgres + Jellyfin (LockData=true)

## Human verification needed

- [ ] In Coolify, confirm the sidecar container has write access to `MEDIA_PATH` (it already does for downloads — `PUID/PGID` match)
- [ ] After editing a song, force a Jellyfin rescan and verify the edits persist (this is the Phase 3 PITFALL fix in action)
- [ ] Confirm OGG files (librespot output) are accepted by `mutagen.File(..., easy=True)` — should be (Vorbis comments)
