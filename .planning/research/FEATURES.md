# Feature Research

**Domain:** Self-hosted multi-user music library admin UI (catalog + fetch queue + admin)
**Researched:** 2026-05-29
**Confidence:** MEDIUM-HIGH (cross-referenced Jellyfin, Navidrome, Funkwhale, Lidarr/Sonarr patterns + UX research; no direct usability study data)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete or broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Username + password login with session persistence | Every web app has this. No session = re-login on every page load. | LOW | Secure, HttpOnly cookies storing a session token. Admin-created accounts only (no public signup per PROJECT.md). |
| Master admin role + at least one subordinate role | Any multi-user system needs an admin who controls access. Flat "everyone is equal" breaks the moment you need to lock someone out. | LOW | Two roles suffices for v1: `admin` and `user`. Avoid RBAC complexity until a concrete third role is needed. |
| Admin can create, disable, and reset password for users | Admins expect to manage accounts without SSH/DB access. | LOW | Disable > delete (preserves fetch history attribution). Password reset = admin-sets-new-password flow, not email reset (admin-created model per PROJECT.md). |
| All-songs catalog view with sorting | The "what do we have?" question is the first thing any user asks. | MEDIUM | Sort by: title, artist, album, date added, duration. Jellyfin and Navidrome both consider this non-negotiable. Backend: Jellyfin REST API `/Items` endpoint. |
| Cover art displayed in catalog and song detail | Music without art feels like a filesystem listing. Users leave. | LOW | Pull from Jellyfin's image API. Lazy-load thumbnails in list view. Full art on detail page. |
| Virtual scrolling / windowed list for large catalogs | A library of 5k–50k songs will freeze the browser if rendered naively. | MEDIUM | Use `@humanspeak/svelte-virtual-list` (Svelte 5 compatible, supports dynamic item heights). Infinite scroll or windowing — not pagination; pagination breaks the "browsing" feel. |
| Live search-as-you-type (Spotify API) | Users expect instant feedback. A "search and wait" pattern feels broken by 2025 standards. | MEDIUM | 250–300ms debounce, minimum 2 chars, cancel in-flight requests on new keystroke, show calm loading indicator (not spinner flash). Cache last 20–50 queries for 60s. |
| One-click "add to fetch queue" from search results | The entire product value is "search → get it." Any friction between search result and queue is a UX failure. | LOW | Button state: idle → queued (immediate optimistic UI update via SSE reconciliation). Disable/grey out if track is already in library or already queued. |
| Fetch queue visible on the home page | Users want to know what's happening without hunting for a dedicated queue page. | MEDIUM | Home page widget: active item with progress bar + ordered list of queued items. Full queue page is a v1.x addition. |
| Real-time queue updates across browsers (SSE) | Two users adding to the queue simultaneously should see each other's additions instantly. Stale queue state causes duplicate requests. | MEDIUM | SSE endpoint broadcasting queue events: `queue:added`, `queue:progress`, `queue:complete`, `queue:error`. All connected clients subscribe. FastAPI `StreamingResponse` with `asyncio.Queue` fan-out. |
| Queue runs one fetch at a time, FIFO | Users expect orderly, predictable queue behavior. "Why is it downloading two things at once?" is a support burden. | LOW | Backend enforces serialization. Frontend shows queue position numbers. |
| Active fetch progress indicator | "Is it downloading?" is the most common question. Without progress, users assume it's broken and click again. | LOW | Percentage or byte progress via SSE `queue:progress` event. A simple progress bar suffices — byte/sec speed is a v1.x differentiator. |
| Song detail page with key metadata | Clicking a song should show what you'd expect: cover, title, artist, album, duration. | LOW | Pull from Jellyfin `/Items/{id}`. No database join required for read. |
| One-off audio playback on song detail | "Let me hear this before I decide if metadata is right" is a universal need. | MEDIUM | HTML5 `<audio>` element pointing at Jellyfin's stream URL. Play/pause + scrubber. No persistent playback queue — Radio handles that. Volume control is required; keyboard shortcuts (space = play/pause) are a differentiator. |
| Edit song metadata from the song page | Wrong artist/album tags are a constant problem with downloaded music. Users need in-app correction without SSH+beets. | MEDIUM | Modal (not in-place): title, artist, album, description. Writes back via Jellyfin API (or sidecar proxy). Triggers Jellyfin library rescan for the item. See PITFALLS for rescan timing issues. |
| Storage stats on home page | Self-hosters always worry about disk. "How full is the drive?" is a daily question. | LOW | Two numbers: total capacity + used. Source: sidecar reading `shutil.disk_usage()` on the media volume mount point. No per-user quotas in v1. |
| Playlist list on home page | Playlists are a primary organization primitive in every music UI (Navidrome, Funkwhale, Jellyfin). | LOW | Show playlist name, song count, thumbnail (first song art). Click → playlist detail view with song list. |
| Fetch history | "Did we already download this? When?" is asked constantly in a shared library. | LOW | History tab or page: completed fetches with timestamp, track name, requester, status (success/error). Separate from active queue. |

---

### Differentiators (Competitive Advantage)

Features that set this product apart from generic self-hosted tools. Not required for launch but vision-defining.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Requester attribution on queue items | "Who added this?" — in a shared library, accountability matters. Navidrome and Jellyfin don't show this because they're not fetch-queue tools. | LOW | Store `user_id` on queue rows. Display username next to queued item. Trivial with Postgres; powerful socially. |
| Duplicate detection before queuing | Prevent users from re-queuing a track already in the library. "It's already here, at /library/..." is far better than silent duplicate. | MEDIUM | On queue-add: check Jellyfin catalog for existing Spotify track ID match. Show "Already in library" with a link to the existing song instead of queuing. Requires storing Spotify track ID on library items (tag or sidecar DB). |
| Download speed / ETA during active fetch | Transforms a progress bar from "something is happening" to "I know when to come back." | LOW | librespot streams at ~320kbps predictable rate — ETA from file size + elapsed. Emit via SSE `queue:progress` event with `eta_seconds` field. |
| Queue reordering by admin | Admin can reprioritize the queue without canceling. "That new album should come first." | MEDIUM | Drag-to-reorder in queue UI (Svelte `@neodrag/svelte` or similar). Backend: `position` column on queue rows, PATCH endpoint to reorder. Enforce admin-only. |
| Error detail + retry per item | Lidarr's pattern: orange icon on failed item, hover for error message, retry button. Without this, failures disappear silently. | MEDIUM | SSE `queue:error` event with `error_message`. Failed items move to history with error state + retry button that re-enqueues. |
| "Already queued" state in search results | Instant feedback prevents double-queuing by impatient users. | LOW | SSE-synchronized queue state in frontend store. Search results check store membership and render "Queued" badge instead of add button. Flows naturally from the SSE state sync already required for table stakes. |
| Personal + global playlists | Navidrome makes playlists per-user by default. Having both a "Station: Indie Rock" (global, admin-curated) and "Jason's Late Night" (personal) is a natural split for a library that feeds a radio frontend. | MEDIUM | `playlists` table with `owner_id` nullable (NULL = global). Global playlists editable only by admin. Personal playlists editable by owner. Radio will later consume global playlists. |
| Fetch queue count badge in nav | A persistent notification: "3 items queued." Zero-friction awareness without opening the queue. | LOW | Derived from SSE queue state. Update the badge reactively. Common in Sonarr/Radarr-style UIs. |

---

### Anti-Features (Deliberately Not Building)

Things that seem reasonable but create bloat, maintenance burden, or scope drift.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Per-user storage quotas | "Fair usage" in a shared library. | Requires per-user download tracking, quota enforcement middleware, and UI for admins to set limits. Marginal value for a private install where all users are trusted. | Rely on social norms + requester attribution. Add quotas only if a specific conflict arises. |
| Email verification / password reset via email | "Standard" auth UX. | Requires SMTP server config, deliverability management, and complexity the admin-created-accounts model doesn't need. Per PROJECT.md: admin sets password, no public signup. | Admin resets password directly in the UI. |
| Public signup / open registration | "Make it easy for people to join." | Turns a private library into a public service. Spam, abuse, and unwanted growth. Incompatible with the "admin controls who has access" model. | Admin creates accounts for trusted users only. |
| MusicBrainz automatic tagging on download | "Auto-fix metadata on every fetch." | beets + MusicBrainz match rate is ~70–80% on well-known tracks, lower on obscure music. False positives corrupt metadata silently. Requires beets integration in sidecar, significant complexity. | Manual metadata editing on song page with optional MusicBrainz lookup by user request. Keep auto-tagging as a future Phase 5 backend feature, not frontend v1. |
| Multi-source fallback (slskd/yt-dlp) in queue UI | "What if librespot fails? Show me the Soulseek source." | Source arbitration logic is a backend Phase 5 concern per PROJECT.md. Exposing multi-source UI before the backend supports it is false affordance. | Queue shows source as "Spotify/librespot" only. Source column becomes meaningful in Phase 5. |
| Persistent playback queue / "now playing" across pages | "Like Spotify — keep playing as I browse." | Full cross-page audio state requires either a persistent layout shell with audio in a slot, or a service worker + MediaSession API. Significant complexity, and Radio is the product for that experience. | One-off playback on the song detail page only. Audio stops on navigation. Radio handles the continuous playback story. |
| Social features (comments, ratings, scrobbling) | "Community feel, Last.fm-style." | Adds a social layer that's out of scope for a library admin UI. Navidrome supports Last.fm scrobbling; Funkwhale has federation. Neither is core to Apricot's value. | Scrobbling is a v2+ consideration after Radio ships. |
| Mobile-native app | "Access from my phone." | Web-first is sufficient. SvelteKit + responsive CSS gets 80% of the way there. A native app is a separate milestone and product. | Responsive web design. PWA capability is a v1.x consideration. |
| Dark mode / theme switcher | "Users want dark mode." | CSS variable-based theming takes 2 days to do right and 2 months of maintenance when design evolves. | Ship one well-designed dark theme (Apricot Suite aesthetic). Light mode is a v2+ consideration. |
| Advanced filter UI (genre, year, BPM, key) | "Power user browsing." | Jellyfin's filter UI is notoriously confusing. Genre/year from Jellyfin API is inconsistently tagged across downloaded music. | Basic sort (title/artist/album/date added) in v1. Filters after metadata quality is ensured. |
| Concurrent fetch slots (parallel downloads) | "Speed up by downloading 3 at once." | Librespot's Spotify Premium session has rate limits and likely a concurrent stream limit. Parallel fetches risk session suspension. | One-at-a-time, FIFO. Queue is the ordering mechanism. |

---

## Feature Dependencies

```
Auth (login, session, roles)
    └──required by──> All other features (every page is gated)
    └──required by──> User attribution on queue items
    └──required by──> Personal playlists (owner_id)
    └──required by──> Admin-only queue reordering

SSE real-time state channel
    └──required by──> Fetch queue sync across browsers
    └──required by──> Active fetch progress indicator
    └──required by──> "Already queued" badge in search results
    └──required by──> Queue count badge in nav
    └──enhances──>    Storage stats (live update on completion)

Fetch queue (Postgres + backend worker)
    └──required by──> Queue display on home page
    └──required by──> Fetch history page
    └──required by──> Error detail + retry
    └──required by──> Queue reordering (admin)
    └──required by──> Requester attribution

Jellyfin catalog integration (REST API)
    └──required by──> All-songs catalog view
    └──required by──> Cover art
    └──required by──> Song detail page
    └──required by──> Duplicate detection before queuing
    └──required by──> One-off audio playback (stream URL)
    └──required by──> Metadata editing (write-back + rescan)

Spotify search (existing sidecar /search endpoint)
    └──required by──> Live search-as-you-type
    └──required by──> One-click add to queue

Playlists (Postgres playlist + membership tables)
    └──required by──> Playlist list on home page
    └──required by──> Personal vs global playlist split
    └──enhances──>    Radio frontend (consumes global playlists — future milestone)
```

### Dependency Notes

- **Auth required by everything:** No unauthenticated views exist in v1. Auth must be the first thing built, or all other frontend work requires mocking it.
- **SSE required by queue UX:** The "one-click add → instant feedback across all browsers" experience is only possible with the SSE channel. Building the queue UI without SSE produces a polling-based UI that will feel wrong and need a rewrite.
- **Jellyfin catalog integration required by duplicate detection:** The "already in library" check on queue-add requires a reliable way to query the catalog by Spotify track ID. This means the sidecar must store `spotify_track_id` as a tag or in its DB when a download completes, and that field must be queryable. This is a sidecar concern but must be designed in v1.
- **Fetch queue required by fetch history:** History is just the completed/failed rows of the queue table. Building queue persistence first gives history for free.

---

## MVP Definition

### Launch With (v1)

Minimum set needed to replace `curl` + Jellyfin native UI for the target users.

- [ ] Auth: login page, session persistence, admin + user roles, admin creates/disables users
- [ ] Home page: all-songs list (virtual scroll), cover art, sort controls, storage stats widget, active fetch + queue widget, playlist list
- [ ] Live Spotify search with debounce, one-click queue add, "already in library" / "already queued" states
- [ ] SSE channel: queue events fan-out to all connected clients
- [ ] Fetch queue: FIFO worker, progress via SSE, history tab, error state with retry
- [ ] Song detail page: metadata display, cover art, one-off playback (HTML5 audio + scrubber)
- [ ] Metadata editing: modal form for title/artist/album/description, write-back to Jellyfin
- [ ] Playlists: list on home, personal + global, basic add/remove songs

### Add After Validation (v1.x)

Add when core is confirmed working and the first real users are using it daily.

- [ ] Queue reordering by admin (drag-to-reorder) — add when queue contention becomes a real problem
- [ ] Download speed + ETA in progress indicator — add once SSE progress events are confirmed stable
- [ ] Fetch queue count badge in nav — add once nav structure is settled
- [ ] Full queue page (separate from home widget) — add when the home widget becomes too crowded
- [ ] Responsive / mobile-friendly layout pass — add after desktop is solid
- [ ] MusicBrainz lookup on metadata edit page — add as optional "suggest from MusicBrainz" button, not auto-apply

### Future Consideration (v2+)

Defer until Radio milestone ships and Library's role as the catalog backend is established.

- [ ] Scrobbling (Last.fm / ListenBrainz) — not needed until Radio creates playback events worth scrobbling
- [ ] Multi-source fetch UI (slskd/yt-dlp) — depends on Phase 5 backend work
- [ ] Per-user storage quotas — defer unless a conflict forces it
- [ ] PWA / offline capability — defer; web-first is sufficient
- [ ] Light mode theme — defer; dark theme ships first

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Auth + session | HIGH | LOW | P1 |
| All-songs catalog (virtual scroll) | HIGH | MEDIUM | P1 |
| Live Spotify search + queue add | HIGH | MEDIUM | P1 |
| SSE queue sync | HIGH | MEDIUM | P1 |
| Fetch queue display + progress | HIGH | MEDIUM | P1 |
| Song detail + one-off playback | HIGH | MEDIUM | P1 |
| Storage stats widget | MEDIUM | LOW | P1 |
| Metadata editing (modal) | MEDIUM | MEDIUM | P1 |
| Fetch history | MEDIUM | LOW | P1 |
| Playlists (list + detail) | MEDIUM | MEDIUM | P1 |
| Requester attribution | MEDIUM | LOW | P2 |
| Duplicate detection | HIGH | MEDIUM | P2 |
| Error detail + retry | HIGH | MEDIUM | P2 |
| Queue count badge in nav | LOW | LOW | P2 |
| "Already queued" badge in search | MEDIUM | LOW | P2 |
| Queue reordering (admin) | LOW | MEDIUM | P2 |
| Download ETA | LOW | LOW | P2 |
| MusicBrainz lookup (optional) | LOW | MEDIUM | P3 |
| Scrobbling | LOW | MEDIUM | P3 |
| Per-user quotas | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

| Feature | Jellyfin | Navidrome | Funkwhale | Lidarr/Sonarr | Apricot Library v1 |
|---------|----------|-----------|-----------|----------------|---------------------|
| Multi-user auth | Admin-created + optional LDAP | Admin-created, no signup | Admin + registration | Single-user admin | Admin-created only (no LDAP/SSO) |
| Role model | Admin / standard user (IsAdministrator flag) | Admin / regular user | Admin / moderator / member | Single admin only | Admin / user (flat, no RBAC) |
| Per-library access control | Yes (per-user toggle) | Yes (multi-library) | Yes (library follows) | N/A | No (single shared catalog) |
| Catalog browse | Grid + list, sort/filter | List, sort | Artist/album/genre browse | Artist → album tree | Virtual-scrolled list, sort |
| Virtual scrolling | No (pagination) | No (pagination) | No | No | Yes (differentiator) |
| Search | Local catalog only | Local catalog only | Local + federated | Local + indexer | Spotify API (external) |
| Live-as-you-type search | Yes (local) | Yes (local) | Yes (local) | No | Yes (Spotify API, debounced) |
| Download / fetch queue | No | No | No | Yes (album-centric) | Yes (track-centric, differentiator) |
| Real-time queue sync (SSE/WS) | WebSocket for playback | No | No | WebSocket (Radarr pattern) | SSE (all clients, differentiator) |
| Queue progress | No | No | No | Percentage bar | Percentage + ETA (v1.x) |
| Requester attribution | No | No | No | No | Yes (differentiator) |
| Duplicate detection | N/A | N/A | N/A | Yes (album level) | Yes (track level, differentiator) |
| Playback | Full streaming client | Full streaming client | Full streaming client | No | One-off only (Radio handles streaming) |
| Metadata editing | Yes (rich UI) | No (read-only) | Yes (in-page forms) | Via MusicBrainz Picard | Modal form, write-back to Jellyfin |
| Playlists | Yes (user-scoped) | Yes (user-scoped, smart playlists) | Yes (federated) | No | Global (admin) + personal (user) |
| Storage stats | Yes (dashboard) | No | No | System health page | Home page widget |
| Fetch history | N/A | Listening history | N/A | Activity tab with error icons | History tab, per-requester |

---

## Sources

- Navidrome features documentation: https://www.navidrome.org/docs/usage/features/
- Jellyfin user management docs: https://jellyfin.org/docs/general/server/users/
- Lidarr activity wiki: https://wiki.servarr.com/lidarr/activity
- Funkwhale 2.0 changelog (2025): https://docs.funkwhale.audio/develop/changelog.html
- "Self-Hosted Music Still Sucks in 2025" (Joe Karlsson): https://www.joekarlsson.com/blog/self-hosted-music-still-sucks-in-2025/
- In-app search UX (debounce, cache, relevance): https://koder.ai/blog/instant-in-app-search-ux
- SSE vs WebSockets for real-time UI: https://oneuptime.com/blog/post/2026-01-27-sse-vs-websockets/view
- svelte-virtual-list (Svelte 5): https://github.com/humanspeak/svelte-virtual-list
- sofarr SSE fan-out pattern: https://git.i3omb.com/Gandalf/sofarr

---
*Feature research for: Apricot Library frontend (catalog + fetch queue + admin)*
*Researched: 2026-05-29*
