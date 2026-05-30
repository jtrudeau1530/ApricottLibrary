# Project Research Summary

**Project:** Apricot Library — SvelteKit Frontend Milestone
**Domain:** Self-hosted multi-user music library admin UI (catalog + fetch queue + admin)
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

Apricot Library is a specialized admin UI for a self-hosted music catalog — not a generic CRUD app. Its defining characteristic is a synchronized, multi-user fetch queue backed by SSE push events that keeps every connected browser in sync as songs are downloaded from Spotify via librespot. The backend (Jellyfin + FastAPI sidecar + librespot) is already deployed and validated. The frontend milestone is about adding auth, a web UI, and the Postgres app-state layer that makes multi-user synchronization possible. The recommended approach is a thin SvelteKit frontend that delegates all business logic to the existing FastAPI sidecar, with Postgres added to the compose stack for users, sessions, queue, and playlists.

The most important architectural decision is the path-split single-domain topology: `library.zektek.us` routes `/*` to SvelteKit and `/api/*` to the sidecar via Traefik. This eliminates CORS complexity, keeps session cookies scoped to a single domain, and avoids the EventSource-cannot-send-auth-headers pitfall that breaks SSE when subdomains are involved. Auth is built app-native using better-auth, the officially-endorsed SvelteKit auth library, backed by Postgres opaque session tokens. SvelteKit is a thin renderer; the sidecar is the single authoritative API surface.

The critical risks are all front-loaded in the auth and queue phases. The existing sidecar has no auth middleware — its download and credentials endpoints are currently unprotected since Authentik was dropped. That exposure must be closed in the first commit of the auth phase, before any frontend UI exists. The queue implementation has three independent failure modes (race conditions on job claim, stuck `in_progress` rows after restarts, partial audio files in Jellyfin from non-atomic writes) that all require explicit design choices at schema time. SSE has its own operational requirement: it must be tested through the Coolify/Traefik stack, not just locally, because Traefik's response buffering silently eats SSE events and the 60-second write timeout kills idle connections without a heartbeat header.

## Key Findings

### Recommended Stack

The stack is constrained by the project's existing choices (SvelteKit, FastAPI, Coolify Docker Compose, Jellyfin) and validated by research. The critical additions are Postgres 16-alpine to the compose stack, better-auth 1.6.x for SvelteKit-native auth, Drizzle ORM for the frontend-side schema, psycopg 3 + SQLAlchemy 2 async for the sidecar, and sse-starlette for the SSE hub. All packages were verified against current PyPI/npm releases as of 2026-05-29.

**Core technologies:**
- SvelteKit 2.x + `@sveltejs/adapter-node` 5.5.4: frontend framework + Docker deployment — user constraint, official SvelteKit recommendation
- better-auth 1.6.11: app-native auth — only SvelteKit-endorsed auth library; admin-only account creation, DB-backed opaque sessions, no JWTs
- Drizzle ORM 0.45.2: SvelteKit-side DB access — zero binary deps (unlike Prisma), better-auth Drizzle adapter generates schema automatically
- Postgres 16-alpine: app-state DB — multi-user sessions, queue, playlists, fetch history require a real RDBMS
- FastAPI 0.115.x (existing): sidecar — extended with auth endpoints, queue worker, SSE hub, Jellyfin proxy routes
- SQLAlchemy 2.0.50 async + psycopg 3.3.4: sidecar ORM + DB driver — async-first, SQLAlchemy 2 dialect support, avoids psycopg2 Alpine conflicts
- sse-starlette 3.4.4: SSE in FastAPI — production-ready `EventSourceResponse` with disconnect detection and keepalive
- argon2-cffi 25.1.0: password hashing — PHC winner, OWASP-recommended parameters required for constrained containers

**What not to use:** Lucia auth (deprecated 2024), Auth.js (OAuth-first, fights admin-created-accounts model), psycopg2 (sync-only, Alpine SSL conflicts), jellyfin-api-client (archived Feb 2025), JWT sessions (cannot be invalidated server-side), Redis or Celery for the queue (overkill for one serial worker), WebSockets for queue sync (SSE is sufficient for one-way push).

### Expected Features

Auth is a hard prerequisite for every other feature. No unauthenticated views exist. Building any other UI before auth is functional means mocking it and rewriting later. SSE is equally foundational — the queue UI requires real-time push from day one; a polling-based interim will feel wrong and need a rewrite. These two dependencies collapse the traditional "start with the visuals" approach into a backend-first build order.

**Must have (table stakes — v1 launch):**
- Auth: login page, sessions, admin + user roles, admin creates/disables users
- All-songs catalog with virtual scrolling (5k–50k songs; `@humanspeak/svelte-virtual-list`, Svelte 5 compatible)
- Live Spotify search-as-you-type (250ms debounce, query cancellation, 60s cache)
- One-click "add to fetch queue" with optimistic UI update
- SSE queue sync across all connected browsers (queue:added, queue:progress, queue:complete, queue:error)
- Fetch queue display on home page: active item with progress bar + ordered queue list
- FIFO serial queue worker (one download at a time)
- Song detail page: cover art, metadata, one-off HTML5 audio playback via sidecar proxy
- Metadata editing modal: title/artist/album/description, write-back to Jellyfin + mutagen tag write
- Storage stats widget (disk usage from `shutil.disk_usage()`)
- Playlist list: global (admin) + personal (user), basic add/remove
- Fetch history: completed/failed rows, timestamp, requester, status

**Should have (v1.x — after core is stable):**
- Requester attribution on queue items (store `user_id` on queue rows)
- Duplicate detection before queuing (check Jellyfin catalog by Spotify track ID)
- Error detail + retry per failed queue item
- "Already queued" badge in search results (derived from SSE queue state store)
- Queue count badge in nav
- Queue reordering by admin (drag-to-reorder, admin-only)
- Download speed + ETA in progress indicator

**Defer (v2+):**
- Scrobbling (Last.fm / ListenBrainz) — depends on Radio milestone for playback events
- Multi-source fetch UI (slskd/yt-dlp) — Phase 5 backend dependency
- Per-user storage quotas — social norms + attribution handle this at small scale
- PWA / offline capability
- Light mode theme (ship one dark theme)
- Advanced filter UI (genre, year, BPM) — metadata quality must be ensured first

### Architecture Approach

The system uses a single-domain path-split topology: Traefik routes `library.zektek.us/api/*` (priority 10) to the FastAPI sidecar and `library.zektek.us/*` (priority 1) to SvelteKit. SvelteKit is a thin renderer — all mutations and business logic live in the sidecar. The sidecar owns auth, queue state, SSE fan-out, Jellyfin proxy, and Spotify search. Postgres holds users, sessions, queue rows, history, and playlists. Jellyfin holds audio files, catalog metadata, and cover art. Browsers never talk directly to the sidecar, Postgres, or Jellyfin.

**Major components:**
1. SvelteKit (Node, port 3000) — page rendering, client-side SSE event handling, route protection, session cookie management; no business logic
2. FastAPI sidecar (port 8000) — auth endpoints, queue worker (asyncio lifespan task), SSEBroadcaster (in-process asyncio pub/sub), Jellyfin catalog proxy, audio streaming proxy, Spotify search
3. Postgres (port 5432, internal only) — users, sessions, fetch_queue, fetch_history, playlists; queue rows are the source of truth; asyncio.Queue holds only job IDs for dispatch
4. Jellyfin (port 8096, internal only) — catalog, cover art, audio file serving, library scanning

**Build order:** Postgres + schema → sidecar auth middleware → SSE hub + queue worker → Jellyfin catalog proxy + audio proxy → SvelteKit scaffold + Traefik wiring → SvelteKit auth flows → home page + queue UI → song detail + audio player → admin UI. Each step is independently testable with curl before the next begins.

### Critical Pitfalls

1. **Sidecar endpoints unprotected after dropping Authentik** — Add `require_session` FastAPI dependency to all existing sidecar routes (especially `/download` and `/auth/librespot/credentials`) in the first commit of the auth phase, before any UI work. Do not assume Coolify network isolation is a substitute.

2. **Session fixation on login** — After verifying credentials, DELETE the old session row and issue a brand-new token with `secrets.token_urlsafe(32)`. Never mutate an existing session on the login path.

3. **SSE events silently swallowed by Traefik** — Set `X-Accel-Buffering: no`, `Cache-Control: no-cache, no-transform`, and a 25-second heartbeat comment in every SSE response. Set Traefik write timeout to 0 for the SSE route. Test SSE only through the deployed Coolify URL, not localhost.

4. **EventSource cannot send auth headers — cookie domain must cover SSE endpoint** — With single-domain topology, this is resolved automatically. Do not introduce a separate `api.library.zektek.us` SSE endpoint; the session cookie must be in scope for the EventSource URL.

5. **Queue stuck `in_progress` after sidecar restart** — Add `heartbeat_at` column to the queue schema from day one. Startup watchdog: reset any row where `status='in_progress' AND heartbeat_at < now() - interval '60 seconds'` back to `pending`. Also: write downloads to a temp file (`.tmp_<jobid>.ogg`) and `os.rename()` to final path only on success — prevents partial files appearing in Jellyfin.

6. **Jellyfin metadata scan overwrites app-edited tags** — After any metadata edit: call `POST /Items/{id}` to update Jellyfin, set `LockData: true` on the item, and write tags back to the audio file with `mutagen`. Jellyfin rescans from file tags; without the file write, edits revert.

7. **`asyncio.create_task()` without a strong reference** — Store the worker task in a module-level variable: `_worker_task = asyncio.create_task(fetch_worker())`. Without it, the GC can collect the coroutine silently.

## Implications for Roadmap

Based on the dependency graph (auth → everything, SSE → queue UX, Postgres schema → queue + history, Jellyfin proxy → catalog) and pitfall-to-phase mapping, the natural phase structure has six phases:

### Phase 1: Auth Foundation + Security Hardening
**Rationale:** Auth is required by every other feature. The existing sidecar has unprotected endpoints (active security issue). Both problems must be solved before any UI ships — exposing the frontend before locking the API would compound the current exposure.
**Delivers:** Postgres service in compose, initial schema (users, sessions), all sidecar routes protected by `require_session`, admin-seeded from env, login/logout/me endpoints, `credentials.json` chmod 600, httpx auth header redaction, session fixation fix.
**Addresses:** Auth (table stakes), security hardening (active CONCERNS.md items)
**Avoids:** Pitfalls 1 (session fixation), 2 (unprotected sidecar), 10 (world-readable credentials), 11 (Spotify secret in logs)
**Research flag:** No — better-auth integration is well-documented (official SvelteKit endorsement + working examples)

### Phase 2: SvelteKit Scaffold + Auth Flows
**Rationale:** Once the sidecar auth API exists and is verified with curl, the SvelteKit frontend can be wired up. Traefik path-split routing must be established before any page development begins — routing determines cookie scope, which determines SSE viability.
**Delivers:** SvelteKit service in compose, Traefik path-split labels, `hooks.server.ts` session validation, login page, route protection, `event.locals.user` on all protected routes.
**Uses:** SvelteKit 2.x, adapter-node 5.5.4, better-auth 1.6.11, Drizzle ORM
**Avoids:** Pitfall 5 (cookie domain / EventSource scope) — resolved by single-domain topology settled here
**Research flag:** No — standard SvelteKit auth hook patterns are well-documented

### Phase 3: SSE Hub + Queue Worker + Postgres Queue Schema
**Rationale:** The queue schema, SSE broadcaster, and asyncio worker are tightly coupled — they share the same Postgres tables, the same in-process broadcaster, and the same lifespan. Build them together rather than in isolation to avoid interface mismatches. The queue schema must include `heartbeat_at` and `attempts` from day one (not retrofitted).
**Delivers:** `SSEBroadcaster` class, asyncio worker coroutine in lifespan, `fetch_queue` + `fetch_history` Postgres tables (with `heartbeat_at`, `attempts`, `requested_by`), `POST /api/queue`, `GET /api/queue`, `GET /api/events` SSE endpoint, startup watchdog for stale jobs.
**Avoids:** Pitfalls 3 (SSE connection leak), 4 (Traefik SSE buffering), 6 (queue race condition with `FOR UPDATE SKIP LOCKED`), 7 (worker crash leaves queue stuck)
**Research flag:** No — asyncio queue + SSEBroadcaster patterns are fully specified in ARCHITECTURE.md

### Phase 4: Jellyfin Catalog Proxy + Audio Streaming
**Rationale:** Catalog and audio proxy depend on auth (to validate the sidecar session before proxying) but not on the queue worker. Separating this phase keeps Jellyfin integration testable in isolation before it's wired into the home page.
**Delivers:** `/api/catalog/tracks` (normalized from Jellyfin `/Users/{id}/Items`), `/api/catalog/tracks/{id}`, `/api/catalog/tracks/{id}/cover`, `/api/audio/{id}/stream` (sidecar proxy with Range header pass-through), `/api/storage` (disk usage).
**Avoids:** Pitfall 8 (partial audio in Jellyfin — temp-file/rename pattern in download code), anti-pattern of browser talking directly to Jellyfin
**Notes:** Jellyfin's `api_key` query parameter is deprecated in v12+; use `Authorization: MediaBrowser Token=...` header exclusively via sidecar proxy.
**Research flag:** No — Jellyfin REST API patterns are documented; audio proxy with Range support is standard

### Phase 5: Home Page + Queue UI + SSE Client
**Rationale:** With sidecar APIs (auth, catalog, queue, SSE, audio) fully operational, the SvelteKit client-side UI can be built against real endpoints. Virtual scrolling, the SSE-fed queue widget, and the search-to-queue flow all land here.
**Delivers:** Home page (all-songs virtual scroll, cover art, sort controls), live Spotify search (250ms debounce, query cancellation), one-click queue add (optimistic UI), SSE EventSource in `+layout.svelte` (single persistent connection, Svelte stores), queue widget (active item + progress bar + ordered list), storage stats widget, playlist list.
**Uses:** `@humanspeak/svelte-virtual-list`, native `EventSource`, Svelte 5 stores
**Avoids:** UX pitfall of no feedback between click and SSE confirmation (optimistic disable on click), polling-based queue UI (SSE replaces polling entirely)
**Research flag:** No — virtual scroll and SSE client patterns are standard; svelte-virtual-list is verified Svelte 5 compatible

### Phase 6: Song Detail, Metadata Editing + Admin UI
**Rationale:** Song detail and metadata editing require the catalog proxy (Phase 4) and auth (Phase 1). Admin user management is gated on auth roles. These features are less coupled to each other but both require the complete foundation.
**Delivers:** Song detail page (cover art, metadata, HTML5 audio player via `/api/audio/{id}/stream`), metadata edit modal (title/artist/album/description, `PATCH /api/catalog/tracks/{id}`, Jellyfin write + `LockData: true` + mutagen tag write), fetch history page, admin user management (create/disable users, list users, password reset).
**Avoids:** Pitfall 9 (Jellyfin scan overwrites metadata edits) — requires mutagen + LockData combo
**Research flag:** MAYBE — Jellyfin's `LockData` behavior is a confirmed known issue (GitHub #11656); test against the running Jellyfin instance before finalizing the metadata write strategy.

### Phase Ordering Rationale

- Phases 1-2 are strictly sequential: sidecar auth must exist before SvelteKit can validate sessions.
- Phase 3 follows Phase 2 because the SSE endpoint requires session auth (`Depends(require_session)` on `/api/events`).
- Phase 4 is independent of Phase 3 but requires Phase 1. It can run in parallel with Phase 3 if capacity allows.
- Phases 5-6 are both blocked on all prior phases. Phase 5 (home page) unlocks more user-visible value than Phase 6 and ships first.
- The build-order discipline (verify each phase with curl before building the next) is not optional — it is the mechanism that avoids late integration failures.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 6 (metadata editing):** Jellyfin's `LockData` behavior is a confirmed known issue with version-specific regressions. Validate the `POST /Items/{id}` + `LockData: true` + mutagen combo against the actual running Jellyfin version before finalizing the implementation design.

Phases with well-documented patterns (skip research-phase):
- **Phase 1 (auth):** better-auth SvelteKit integration has official docs, CLI integration, and working examples.
- **Phase 2 (SvelteKit scaffold):** adapter-node, hooks.server.ts, and Traefik path-split labels are all documented.
- **Phase 3 (SSE + queue):** asyncio.Queue + SSEBroadcaster + `FOR UPDATE SKIP LOCKED` patterns are fully specified.
- **Phase 4 (Jellyfin proxy):** Jellyfin REST API endpoints and auth header format are documented.
- **Phase 5 (home page):** virtual scroll, SSE EventSource, and Svelte 5 stores are standard patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All packages verified against current npm/PyPI releases. Version compatibility table confirmed. No deprecated or archived packages in the recommended set. |
| Features | MEDIUM-HIGH | Cross-referenced against Jellyfin, Navidrome, Funkwhale, and Lidarr patterns. No direct usability study data; feature priority is informed by competitor analysis and domain expertise. |
| Architecture | HIGH | Derivable from first principles; patterns verified against FastAPI, SvelteKit, and Traefik docs. Single-domain path-split topology is the unambiguous right call given the constraints. |
| Pitfalls | HIGH | Stack-specific, verified against official docs and confirmed GitHub issues (Jellyfin #11656, librespot credentials world-readable). CONCERNS.md pre-existing audit aligns with research findings. |

**Overall confidence:** HIGH

### Gaps to Address

- **Jellyfin `LockData` reliability:** The metadata lock behavior has version-specific regressions. Confirmed issue but exact workaround depends on the running Jellyfin version. Test before finalizing Phase 6 design.
- **Traefik SSE timeout configuration in Coolify:** The specific Coolify UI path for setting `respondingTimeouts.writeTimeout=0` on a per-service label was not verified against the running Coolify version. Verify in Phase 3 deployed testing.
- **Jellyfin scan timing after download:** The polling strategy (poll `/api/catalog/tracks/{spotify_id}` for up to 30s after `fetch_complete`) is a mitigation, not a guarantee. Validate actual debounce time against the running Jellyfin instance.
- **Duplicate detection schema:** Storing `spotify_track_id` on library items must be designed into the Phase 3 schema even though duplicate detection is a v1.x feature. The column must exist from the start.

## Sources

### Primary (HIGH confidence)
- [better-auth SvelteKit integration docs](https://better-auth.com/docs/integrations/svelte-kit) — hooks.server.ts pattern, sveltekitCookies plugin
- [better-auth PostgreSQL adapter docs](https://better-auth.com/docs/adapters/postgresql) — pg Pool setup
- [svelte.dev/docs/kit/auth](https://svelte.dev/docs/kit/auth) — official SvelteKit recommendation of better-auth
- [sse-starlette PyPI](https://pypi.org/project/sse-starlette/) — version 3.4.4, May 2026
- [psycopg PyPI](https://pypi.org/project/psycopg/) — version 3.3.4, async support
- [SQLAlchemy PyPI](https://pypi.org/project/SQLAlchemy/) — version 2.0.50, asyncio extra
- [drizzle-orm npm](https://www.npmjs.com/package/drizzle-orm) — version 0.45.2
- [@sveltejs/kit npm](https://www.npmjs.com/package/@sveltejs/kit) — version 2.61.1
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [PostgreSQL SKIP LOCKED for queues](https://parottasalna.com/2025/01/11/learning-notes-51-postgres-as-a-queue-using-skip-locked/)
- [FastAPI lifespan + asyncio.Queue pattern](https://oneuptime.com/blog/post/2026-01-25-background-task-processing-fastapi/view)

### Secondary (MEDIUM confidence)
- [Jellyfin API overview](https://jmshrv.com/posts/jellyfin-api/) — audio stream endpoint, auth header format
- [Jellyfin auth gist](https://gist.github.com/nielsvanvelzen/ea047d9028f676185832e51ffaf12a6f) — MediaBrowser Authorization header format
- [SSE vs WebSockets for real-time UI](https://oneuptime.com/blog/post/2026-01-27-sse-vs-websockets/view)
- [svelte-virtual-list (Svelte 5)](https://github.com/humanspeak/svelte-virtual-list)
- Navidrome, Funkwhale, Lidarr feature documentation — competitor feature analysis
- [SSE Nginx/Traefik buffering](https://oneuptime.com/blog/post/2025-12-16-server-sent-events-nginx/view)

### Tertiary (confirmed issues, external)
- [Jellyfin metadata lock issue #11656](https://github.com/jellyfin/jellyfin/issues/11656) — LockData not always respected
- [librespot credentials.json world-readable #360](https://github.com/librespot-org/librespot/issues/360)
- .planning/codebase/CONCERNS.md — pre-existing security audit (aligns with research)

---
*Research completed: 2026-05-29*
*Ready for roadmap: yes*
