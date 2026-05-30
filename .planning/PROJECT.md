# Apricot Library

## What This Is

A self-hosted music library and "back room" catalog for the Apricot Suite. The Library stores every song (audio files + metadata), lets multiple logged-in users browse it Spotify-style, search Spotify for new songs and one-click queue them for download, and curate the catalog through playlists and metadata edits. Library is the source of truth that the future Apricot Radio frontend will read from.

## Core Value

A multi-user, synchronized catalog where any logged-in user can search, fetch, and curate music — and the queue/library they see is the same view everyone else sees.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. Existing backend (Phases 1–4b, tracked informally before GSD initialization). -->

- ✓ Jellyfin music catalog deployed via Docker Compose with shared media volume — existing
- ✓ slskd (Soulseek client) deployed alongside Jellyfin — existing
- ✓ FastAPI sidecar service with `/health`, `/search` (Spotify Web API), `/auth/spotify/*` OAuth flow — existing
- ✓ librespot-based `/download/{track_id}` streaming 320kbps OGG into the Jellyfin media volume — existing
- ✓ One-time librespot credential upload flow (`tools/get_credentials.py` + `POST /auth/librespot/credentials`) — existing
- ✓ Deployed to Coolify at `jellyfin.zektek.us`, `slskd.zektek.us`, `api.library.zektek.us` — existing

### Active

<!-- Frontend milestone (v1.0 — Library Web). Building toward these. -->

- [ ] App-native authentication with master admin and admin-created users (no Authentik)
- [ ] Session persistence across browser refresh; secure session cookies
- [ ] Admin can create users, manage users, assign per-user permissions
- [ ] Spotify-style home page showing all songs in the library
- [ ] Home page shows storage capacity and current consumption
- [ ] Home page shows active fetches and the queued fetch list
- [ ] Home page lists playlists (global + per-user)
- [ ] Live search-as-you-type for songs not yet in the library (Spotify Web API)
- [ ] One-button "add to fetch queue" from search results
- [ ] Fetch queue synchronized in real time across all logged-in users (SSE)
- [ ] Queue runs one fetch at a time, oldest-first
- [ ] Song detail page with cover art, artist, album, length, and one-off playback
- [ ] Edit song metadata (title, artist, album, description) from song page
- [ ] Backend reads Jellyfin REST API as the catalog source of truth
- [ ] Postgres database stores users, sessions, queue, fetch history, playlists

### Out of Scope

<!-- Explicit boundaries with reasoning. -->

- Authentik forward-auth — replaced by app-native auth for full control over user model and permissions
- Radio frontend integration — separate milestone; Library ships first as the catalog source
- slskd / yt-dlp fallback wiring — backend Phase 5 work, not part of this frontend milestone
- Mobile app — web-first; native mobile is a future consideration
- Email verification / password reset flows — admin-created accounts only in v1; no public signup
- Per-song streaming to external clients beyond the song page — Radio handles streaming consumption
- Multi-disc / multi-room playback queues — single one-off playback only on the song page

## Context

**Existing backend.** The Library backend (Jellyfin + slskd + FastAPI sidecar) is already deployed to Coolify and validated through manual download flows. Spotify Premium downloads via librespot work end-to-end. There is no frontend yet; users currently interact with the sidecar by `curl`-ing endpoints and with Jellyfin directly via its native UI.

**Catalog topology.** Jellyfin owns metadata, library scanning, cover art, and audio file serving. The new frontend will read from Jellyfin's REST API rather than re-indexing the filesystem. The sidecar's job grows to host the frontend's app-state (users, queue, playlists, edits) plus the existing search/download endpoints.

**Multi-user model.** This is the admin interface for the future Radio app. Users created here will eventually be the same identity used to manage Radio stations. The Library is the back room; Radio is the storefront.

**Sync requirements.** Multiple users may be browsing simultaneously and adding to the fetch queue. Queue state, active fetch progress, and storage stats must all be visible in real time without polling.

**Prior phases (informal).** Phases 1–4b shipped before this `.planning/` directory existed; they're captured in `README.md` and now in `.planning/codebase/` documents.

## Constraints

- **Tech stack**: SvelteKit frontend — user preference; aligns with the goal of a lightweight, server-friendly catalog UI.
- **Tech stack**: Postgres for app-state — multi-user, synchronized queue requires a real DB; sidecar already runs in Docker.
- **Tech stack**: FastAPI sidecar (existing) extended with auth/queue/SSE — avoid splitting the backend into multiple services.
- **Tech stack**: Jellyfin REST API as catalog source — don't re-implement library indexing; let Jellyfin own metadata.
- **Real-time**: SSE for server→client updates — one-way push fits queue/fetch/storage updates; simpler than WebSockets.
- **Deployment**: Coolify Docker Compose — frontend deploys as another service in the existing compose stack.
- **Auth**: No third-party auth provider — fully app-native; sessions in the app DB.
- **Repo**: Frontend lives in the existing Library repo (`https://github.com/jtrudeau1530/ApricottLibrary`), not a separate repo.
- **Authorship**: Commits authored solely by the user (no Claude co-author trailer) — per user preference.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| SvelteKit for the frontend | User preference; lightweight, server-friendly | — Pending |
| App-native auth (drop Authentik) | Full control over multi-user model and per-user permissions; simpler stack | — Pending |
| Postgres for app-state | Multi-user sync queue and sessions need a real DB | — Pending |
| Jellyfin REST API as catalog source | Avoid re-indexing; Jellyfin owns metadata/scanning/covers | — Pending |
| SSE (not WebSockets) for real-time | One-way server→client updates, simpler under proxies, built-in browser support | — Pending |
| Extend existing sidecar (don't add a new service) | Backend already has Spotify/librespot logic; co-locate auth/queue there | — Pending |
| Frontend lives in same repo as backend | Single deploy unit via Coolify compose | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-29 after initialization*
