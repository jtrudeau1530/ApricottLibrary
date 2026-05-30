# Roadmap: Apricot Library (v1.0 — Library Web)

## Overview

The backend is already deployed and validated (Phases 1–4b, shipped before GSD initialization). This roadmap covers the frontend milestone: building auth, a SvelteKit web UI, and the Postgres app-state layer that makes multi-user synchronization possible. The build order is dictated by hard dependencies — auth locks down the currently-unprotected sidecar, SSE + the queue worker deliver the synchronized fetch experience, and the catalog proxy + home page complete the Spotify-style browsing surface. Admin UI and playlists ship last, after the core experience is solid.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Auth Foundation** - Lock down the sidecar, add Postgres + app-native auth, wire SvelteKit scaffold with login/logout and route protection
- [x] **Phase 2: SSE Hub + Queue Worker** - Postgres queue schema, asyncio worker, SSE broadcaster, and all queue/realtime API endpoints
- [x] **Phase 3: Jellyfin Catalog Proxy** - Sidecar endpoints that normalize Jellyfin's catalog, cover art, audio streaming, and storage stats
- [x] **Phase 4: Home Page + Search + Fetch UI** - The SvelteKit home page: virtual-scroll song list, live Spotify search, one-click queue add, SSE-fed queue widget, storage stats
- [x] **Phase 5: Song Detail + Metadata Editing** - Song detail page with HTML5 audio playback, metadata edit modal with Jellyfin + mutagen write-back
- [x] **Phase 6: Playlists + Admin UI** - Playlist creation/management and the admin user-management pages

## Phase Details

### Phase 1: Auth Foundation
**Goal**: The sidecar is secured and users can log in; the SvelteKit app exists with working session management
**Depends on**: Nothing (first phase)
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06, ADMIN-01
**Success Criteria** (what must be TRUE):
  1. Any unauthenticated request to a sidecar API endpoint (including `/download` and `/auth/librespot/credentials`) returns 401 — verifiable with `curl` without a session cookie
  2. User can visit `library.zektek.us`, see a login page, enter credentials, and land on the home page with a session cookie that persists across browser refresh
  3. User can log out from any page and the session is immediately invalidated (subsequent requests redirect to login)
  4. On first sidecar startup, the master admin account is automatically provisioned from environment variables with no manual intervention
  5. A fresh login issues a session ID that differs from any pre-auth session (session fixation cannot occur)
**Plans**: TBD

### Phase 2: SSE Hub + Queue Worker
**Goal**: The fetch queue is operational end-to-end in the backend — tracks can be enqueued, downloaded, and all connected browsers receive live updates
**Depends on**: Phase 1
**Requirements**: QUEUE-01, QUEUE-02, QUEUE-03, QUEUE-04, QUEUE-05, QUEUE-06, QUEUE-07, QUEUE-08, RT-01, RT-02, RT-03, RT-04, RT-05
**Success Criteria** (what must be TRUE):
  1. Posting a track ID to `POST /api/queue` creates a Postgres row attributed to the requesting user and immediately broadcasts a `queue:added` SSE event to all connected clients — verifiable with two `curl` SSE connections open simultaneously
  2. The worker processes queue items strictly one at a time in FIFO order, downloads 320kbps OGG into the Jellyfin media volume, and triggers a Jellyfin library refresh on completion
  3. If the sidecar restarts mid-download, the in-progress row is reset to pending within 60 seconds of restart (heartbeat watchdog fires), and the queue resumes from where it left off
  4. Failed fetches are recorded with an error message and status in Postgres; they can be retried via API
  5. SSE events arrive in the deployed Coolify environment (through Traefik) within one second — not just on localhost
**Plans**: TBD

### Phase 3: Jellyfin Catalog Proxy
**Goal**: The sidecar exposes normalized catalog, audio, and storage endpoints that the frontend can call without ever touching Jellyfin directly or knowing its API key
**Depends on**: Phase 1
**Requirements**: CAT-01, CAT-02, CAT-03, CAT-04, CAT-05, STOR-01, STOR-02
**Success Criteria** (what must be TRUE):
  1. `GET /api/catalog/tracks` returns a normalized list of all songs from Jellyfin (including cover art URLs, title, artist, album) — verifiable with `curl` using a valid session token
  2. `GET /api/audio/{id}/stream` proxies audio from Jellyfin with correct `Content-Type`, `Content-Length`, and `Range` header pass-through so that seeking works in a browser `<audio>` element
  3. `GET /api/storage` returns current disk capacity and consumption figures derived from `shutil.disk_usage()` on the Jellyfin media volume
  4. The Jellyfin API key is never present in any response body, URL, or browser-visible header
**Plans**: TBD

### Phase 4: Home Page + Search + Fetch UI
**Goal**: Users can browse the full music catalog, search Spotify for new tracks, and add them to the fetch queue — with live queue status visible to everyone simultaneously
**Depends on**: Phase 2, Phase 3
**Requirements**: SRCH-01, SRCH-02, SRCH-03, SRCH-04, SRCH-05
**Success Criteria** (what must be TRUE):
  1. The home page renders all songs in the library with cover art, title, artist, and album; the list stays responsive (no jank, no full-page reloads) at 50k+ items via virtual scrolling
  2. Typing in the search box shows Spotify results live within 300ms (debounced); each result indicates whether the track is already in the library or queue
  3. Clicking "Add to queue" on a search result immediately disables the button (optimistic update) and the queue widget on the home page updates for all connected users within one second via SSE — no page refresh required
  4. The home page queue widget shows the active download (with progress) and the ordered list of upcoming tracks; the storage stats widget shows current disk usage; the nav badge shows live queue count
  5. Navigating away and back to the home page does not break the SSE connection or duplicate the queue display
**Plans**: TBD

### Phase 5: Song Detail + Metadata Editing
**Goal**: Users can click any song to view its details, play it, and (with permission) edit its metadata with changes that survive a Jellyfin rescan
**Depends on**: Phase 3, Phase 4
**Requirements**: SONG-01, SONG-02, SONG-03, SONG-04, META-01, META-02, META-03, META-04
**Success Criteria** (what must be TRUE):
  1. Clicking a catalog row opens a song detail page showing cover art, title, artist, album, and duration
  2. The song plays via an HTML5 audio player (play/pause, scrubber, volume) with the audio streamed through the sidecar proxy — the Jellyfin API key does not appear in any network request visible to the browser
  3. Navigating away from the song detail page stops playback; the audio does not continue in the background
  4. A user with edit permission can open the metadata modal, change title/artist/album/description, save, and the change is reflected immediately in Jellyfin and survives a forced Jellyfin library rescan (mutagen tag write + `LockData: true` combo)
**Plans**: TBD

### Phase 6: Playlists + Admin UI
**Goal**: Admins can manage users and permissions; all users can create and curate playlists
**Depends on**: Phase 4, Phase 5
**Requirements**: PLST-01, PLST-02, PLST-03, PLST-04, PLST-05, ADMIN-02, ADMIN-03, ADMIN-04, ADMIN-05, ADMIN-06
**Success Criteria** (what must be TRUE):
  1. Admin can create a new user account (with username + initial password), disable an existing account, reset any user's password, and grant or revoke the `can-fetch` and `can-edit-metadata` permission flags — all from an admin UI page
  2. A non-admin user cannot access the admin page or call admin-only API routes (returns 403 for valid non-admin sessions)
  3. Any user can create a personal playlist, add and remove songs from it; only the owner can edit it
  4. Admin can create a global playlist visible to all users; only admins can edit global playlists
  5. Clicking a playlist on the home page opens a detail page listing its songs in order

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

Note: Phase 3 has no dependency on Phase 2 (only on Phase 1) and can be developed in parallel with Phase 2 if capacity allows.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Auth Foundation | 0/TBD | Not started | - |
| 2. SSE Hub + Queue Worker | 0/TBD | Not started | - |
| 3. Jellyfin Catalog Proxy | 0/TBD | Not started | - |
| 4. Home Page + Search + Fetch UI | 0/TBD | Not started | - |
| 5. Song Detail + Metadata Editing | 0/TBD | Not started | - |
| 6. Playlists + Admin UI | 0/TBD | Not started | - |
