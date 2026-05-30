# Requirements: Apricot Library

**Defined:** 2026-05-29
**Core Value:** A multi-user, synchronized catalog where any logged-in user can search, fetch, and curate music — and the queue/library they see is the same view everyone else sees.

## v1 Requirements

Requirements for the Library frontend milestone. Each maps to exactly one roadmap phase.

### Authentication

- [ ] **AUTH-01**: User can log in with username and password
- [ ] **AUTH-02**: User session persists across browser refresh via secure httpOnly cookie
- [ ] **AUTH-03**: User can log out from any page, immediately invalidating the session
- [ ] **AUTH-04**: Unauthenticated requests to any non-login route redirect to the login page
- [ ] **AUTH-05**: Sidecar API endpoints require a valid session (no anonymous access)
- [ ] **AUTH-06**: Session ID is regenerated on successful login (no session fixation)

### Admin

- [ ] **ADMIN-01**: A master admin account is provisioned on first boot from environment variables
- [ ] **ADMIN-02**: Admin can create new user accounts with username + initial password
- [ ] **ADMIN-03**: Admin can disable a user account (preserving fetch history attribution)
- [ ] **ADMIN-04**: Admin can reset any user's password
- [ ] **ADMIN-05**: Admin can grant or revoke permission flags per user (e.g. can-fetch, can-edit-metadata)
- [ ] **ADMIN-06**: Non-admin users cannot access admin pages or admin-only API routes

### Catalog

- [ ] **CAT-01**: Home page shows every song in the library, sourced from Jellyfin's REST API
- [ ] **CAT-02**: Catalog list uses virtual scrolling and stays responsive at 50k+ items
- [ ] **CAT-03**: User can sort the catalog by title, artist, album, or date added
- [ ] **CAT-04**: Each catalog row shows cover art (lazy-loaded), title, artist, album
- [ ] **CAT-05**: Home page lists playlists (global + the viewer's personal) with name, song count, thumbnail

### Search

- [ ] **SRCH-01**: User can search Spotify by typing in a search box on the home page
- [ ] **SRCH-02**: Results appear live with ≤300ms debounce; in-flight requests cancel on new keystroke
- [ ] **SRCH-03**: Each result shows track name, artist, and album cover
- [ ] **SRCH-04**: Result row indicates whether the track is already in the library or already in the queue
- [ ] **SRCH-05**: User can add a search result to the fetch queue with one click

### Fetch Queue

- [ ] **QUEUE-01**: Adding a search result enqueues a fetch row in Postgres attributed to the requesting user
- [ ] **QUEUE-02**: Backend worker processes the queue strictly FIFO, one fetch at a time
- [ ] **QUEUE-03**: Worker reuses the existing librespot download path to write 320kbps OGG into the Jellyfin media volume
- [ ] **QUEUE-04**: After a download completes, the worker triggers a Jellyfin library refresh for the affected folder
- [ ] **QUEUE-05**: Failed fetches are recorded with an error message and can be retried from the UI
- [ ] **QUEUE-06**: Queue rows persist across sidecar restarts; on boot, `status=queued` rows are reloaded into the worker
- [ ] **QUEUE-07**: User can view the queue (active item + ordered upcoming) on the home page
- [ ] **QUEUE-08**: User can view fetch history (completed + failed) with requester and timestamp

### Realtime Sync

- [ ] **RT-01**: Sidecar exposes an SSE endpoint authenticated via the session cookie
- [ ] **RT-02**: SSE events broadcast queue changes (`queue:added`, `queue:progress`, `queue:complete`, `queue:error`) to all connected clients
- [ ] **RT-03**: SSE events broadcast storage usage changes to all connected clients
- [ ] **RT-04**: Frontend reconnects automatically on dropped SSE connections
- [ ] **RT-05**: Frontend nav shows a live queue-count badge derived from SSE state

### Song Detail & Playback

- [ ] **SONG-01**: Clicking a catalog row opens a song detail page showing cover, title, artist, album, duration
- [ ] **SONG-02**: Song detail page can play the audio file (HTML5 `<audio>`, play/pause, scrubber, volume)
- [ ] **SONG-03**: Audio stream is proxied through the sidecar so the Jellyfin API key never reaches the browser
- [ ] **SONG-04**: Navigating away from the song detail page stops playback (no cross-page playback)

### Metadata Editing

- [ ] **META-01**: User with edit permission can open a metadata edit modal from the song detail page
- [ ] **META-02**: User can edit title, artist, album, and description
- [ ] **META-03**: Edits are persisted to the audio file tags (via `mutagen`) and to Jellyfin with `LockData: true`
- [ ] **META-04**: Edits are also recorded in Postgres so they survive any Jellyfin rescan that ignores the lock

### Playlists

- [ ] **PLST-01**: User can create a personal playlist with a name
- [ ] **PLST-02**: Admin can create a global playlist (visible to all users)
- [ ] **PLST-03**: Owner can add or remove songs from a playlist they own
- [ ] **PLST-04**: Admin can edit any global playlist; only owners can edit personal playlists
- [ ] **PLST-05**: Clicking a playlist on the home page opens a detail page listing its songs

### Storage

- [ ] **STOR-01**: Home page shows total media-volume capacity and current consumption
- [ ] **STOR-02**: Storage stats update live via SSE when a fetch completes

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Differentiators (post-v1)

- **Q2-01**: Admin can drag-reorder the queue
- **Q2-02**: Active fetch shows estimated time remaining
- **Q2-03**: Catalog has a search-within-library box (separate from Spotify search)
- **Q2-04**: Metadata edit modal can lookup MusicBrainz suggestions
- **Q2-05**: PWA install support for mobile home-screen launch

### Radio bridge

- **RAD-01**: Global playlists are exposed via a read-only API for the future Radio frontend

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Authentik / forward-auth | Replaced by app-native auth for full control over user model and permissions |
| Public signup / open registration | Private library; admin creates accounts only |
| Email verification + password-reset-by-email | No SMTP setup; admin resets passwords in-app |
| Per-user storage quotas | Trusted users; rely on requester attribution + social norms |
| MusicBrainz auto-tagging on download | False-positive risk; manual editing in v1, automation deferred to backend Phase 5 |
| Multi-source fallback UI (slskd, yt-dlp) | Backend Phase 5 concern; UI would create false affordance until backend supports it |
| Persistent cross-page playback queue | Radio handles continuous listening; Library is the back-room catalog |
| Social features (comments, ratings, scrobbling) | Out of scope for an admin catalog UI |
| Mobile-native app | Responsive web is sufficient for v1 |
| Light theme / theme switcher | One dark theme only in v1 |
| Advanced filter UI (genre, year, BPM) | Sort-only in v1; filtering requires reliable metadata first |
| Parallel fetch slots | One-at-a-time avoids Spotify session-suspension risk |
| Radio integration (stations, streams) | Separate milestone — Library ships first as the catalog source |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01 | Phase 1 | Built (verify on deploy) |
| AUTH-02 | Phase 1 | Built (verify on deploy) |
| AUTH-03 | Phase 1 | Built (verify on deploy) |
| AUTH-04 | Phase 1 | Built (verify on deploy) |
| AUTH-05 | Phase 1 | Built (verify on deploy) |
| AUTH-06 | Phase 1 | Built (verify on deploy) |
| ADMIN-01 | Phase 1 | Built (verify on deploy) |
| QUEUE-01 | Phase 2 | Built (verify on deploy) |
| QUEUE-02 | Phase 2 | Built (verify on deploy) |
| QUEUE-03 | Phase 2 | Built (verify on deploy) |
| QUEUE-04 | Phase 2 | Built (verify on deploy) |
| QUEUE-05 | Phase 2 | Built (verify on deploy) |
| QUEUE-06 | Phase 2 | Built (verify on deploy) |
| QUEUE-07 | Phase 2 | Built (verify on deploy) |
| QUEUE-08 | Phase 2 | Built (verify on deploy) |
| RT-01 | Phase 2 | Built (verify on deploy) |
| RT-02 | Phase 2 | Built (verify on deploy) |
| RT-03 | Phase 2 | Built (verify on deploy) |
| RT-04 | Phase 2 | Built (verify on deploy) |
| RT-05 | Phase 2 | Built (verify on deploy) |
| CAT-01 | Phase 3 | Built (verify on deploy) |
| CAT-02 | Phase 3 | Built (verify on deploy) |
| CAT-03 | Phase 3 | Built (verify on deploy) |
| CAT-04 | Phase 3 | Built (verify on deploy) |
| CAT-05 | Phase 3 | Built (verify on deploy) |
| STOR-01 | Phase 3 | Built (verify on deploy) |
| STOR-02 | Phase 3 | Built (verify on deploy) |
| SRCH-01 | Phase 4 | Built (verify on deploy) |
| SRCH-02 | Phase 4 | Built (verify on deploy) |
| SRCH-03 | Phase 4 | Built (verify on deploy) |
| SRCH-04 | Phase 4 | Built (verify on deploy) |
| SRCH-05 | Phase 4 | Built (verify on deploy) |
| SONG-01 | Phase 5 | Built (verify on deploy) |
| SONG-02 | Phase 5 | Built (verify on deploy) |
| SONG-03 | Phase 5 | Built (verify on deploy) |
| SONG-04 | Phase 5 | Built (verify on deploy) |
| META-01 | Phase 5 | Built (verify on deploy) |
| META-02 | Phase 5 | Built (verify on deploy) |
| META-03 | Phase 5 | Built (verify on deploy) |
| META-04 | Phase 5 | Built (verify on deploy) |
| PLST-01 | Phase 6 | Built (verify on deploy) |
| PLST-02 | Phase 6 | Built (verify on deploy) |
| PLST-03 | Phase 6 | Built (verify on deploy) |
| PLST-04 | Phase 6 | Built (verify on deploy) |
| PLST-05 | Phase 6 | Built (verify on deploy) |
| ADMIN-02 | Phase 6 | Built (verify on deploy) |
| ADMIN-03 | Phase 6 | Built (verify on deploy) |
| ADMIN-04 | Phase 6 | Built (verify on deploy) |
| ADMIN-05 | Phase 6 | Built (verify on deploy) |
| ADMIN-06 | Phase 6 | Built (verify on deploy) |

**Coverage:**
- v1 requirements: 50 mapped (header previously said 53 — recount confirmed 50 actual requirements in the file; no orphans found)
- Mapped to phases: 50/50
- Unmapped: 0

---
*Requirements defined: 2026-05-29*
*Last updated: 2026-05-29 after roadmap creation*
