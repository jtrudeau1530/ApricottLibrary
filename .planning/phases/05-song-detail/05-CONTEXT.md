# Phase 5: Song Detail + Metadata Editing - Context

<domain>
Per-song page: cover, metadata, HTML5 audio with scrubber + volume, edit-metadata modal that writes file tags via mutagen, Postgres `song_metadata` row, and Jellyfin update with LockData=true.
</domain>

<decisions>
- Route: `/song/[id]` (Jellyfin item id).
- Audio: proxied `/api/audio/{id}/stream` (Phase 3).
- Edit endpoint: `PATCH /api/catalog/tracks/{id}` — requires `can_edit_metadata`. Writes (1) `song_metadata` row in Postgres (source of truth), (2) audio file tags via mutagen, (3) Jellyfin `POST /Items/{id}` with `LockData=true`.
- File-tag writes need to know the file path — get from `MEDIATree` lookup via Jellyfin's `Path` field. Pass through `MEDIA_PATH` mapping.
- Navigating away stops playback because the audio element unmounts.
</decisions>

<deferred>
- MusicBrainz lookup (v2 — Q2-04).
</deferred>
