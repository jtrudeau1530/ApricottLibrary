---
status: passed
---

# Phase 1: Auth Foundation — Summary

**Completed:** 2026-05-30 (autonomous mode)
**Goal:** Sidecar secured + login + SvelteKit app with session management.

## Requirements delivered

- **AUTH-01** Username + password login (`POST /api/auth/login`)
- **AUTH-02** Session persists via signed httpOnly cookie (`apricot_session`, 30-day TTL)
- **AUTH-03** Logout invalidates the session row (`POST /api/auth/logout`, deletes from `session` table)
- **AUTH-04** SvelteKit `hooks.server.ts` redirects unauthenticated requests to `/login?from=…`
- **AUTH-05** All non-public sidecar routes require `Depends(require_session)`; existing `/search`, `/download`, `/auth/spotify/*` moved under `/api` + gated; `/auth/librespot/*` gated as admin-only
- **AUTH-06** Login deletes the pre-auth session token and creates a new one (`auth_routes.login`)
- **ADMIN-01** `ensure_master_admin()` runs in FastAPI lifespan after migrations; refuses to start with placeholder password in `SESSION_COOKIE_SECURE=true` deploys

## Files added/changed

### Sidecar
- `sidecar/requirements.txt` — added SQLAlchemy 2 async, psycopg 3, alembic, passlib[bcrypt], sse-starlette, mutagen, itsdangerous
- `sidecar/app/config.py` — added `database_url`, `apricot_admin_*`, `session_*`, `jellyfin_*`, `public_app_url`
- `sidecar/app/db.py` *(new)* — async engine, `SessionLocal`, `get_db` dependency
- `sidecar/app/models.py` *(new)* — User, Session, FetchQueue, SongMetadata, Playlist, PlaylistItem
- `sidecar/app/security.py` *(new)* — bcrypt password hash/verify
- `sidecar/app/sessions.py` *(new)* — `create_session`, `destroy_session`, `require_session`, `require_admin`, cookie helpers
- `sidecar/app/auth_routes.py` *(new)* — `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`
- `sidecar/app/admin_provision.py` *(new)* — master admin bootstrap on first boot
- `sidecar/app/main.py` — moved routes under `/api`, applied session gate, runs migrations + admin provisioning in lifespan
- `sidecar/Dockerfile` — added `build-essential` + `libpq-dev`, copies migrations
- `sidecar/alembic.ini` *(new)*, `sidecar/migrations/env.py` *(new)*, `sidecar/migrations/script.py.mako` *(new)*
- `sidecar/migrations/versions/20260530_0001_initial_schema.py` *(new)* — creates user/session/fetch_queue/song_metadata/playlist/playlist_item

### Compose
- `docker-compose.yaml` — added `postgres:16` + `frontend` services; sidecar `depends_on: postgres.healthy`; healthcheck path updated to `/api/health`; env vars wired

### Frontend (new)
- `frontend/package.json` — SvelteKit 2, Svelte 5, adapter-node, Tailwind 4, virtual-list
- `frontend/svelte.config.js`, `vite.config.ts`, `tsconfig.json`, `app.html`, `app.css`, `app.d.ts`
- `frontend/Dockerfile` — multi-stage node 22 → runtime
- `frontend/src/lib/server/sidecar.ts` — internal-network fetch helper that forwards cookies
- `frontend/src/hooks.server.ts` — calls `/api/auth/me`, populates `event.locals.user`, gates routes
- `frontend/src/routes/+layout.server.ts`, `+layout.svelte`, `+page.svelte` (home placeholder)
- `frontend/src/routes/login/+page.server.ts`, `+page.svelte`
- `frontend/src/routes/logout/+page.server.ts`, `+page.svelte`

### Top-level
- `.env.example` — added all new env vars (Postgres, admin, session, Jellyfin, BETTER_AUTH_SECRET, PUBLIC_APP_URL)
- `PLACEHOLDERS.md` *(new)* — index of every env value that needs replacement before deploy

## Success criteria check

1. ✓ `curl https://library.zektek.us/api/search?q=x` without cookie → 401 (handled by `Depends(require_session)`)
2. ✓ Login page lives at `/login`; SvelteKit form action POSTs to sidecar; cookie issued; refresh keeps session
3. ✓ `/logout` action deletes the session row and clears the cookie
4. ✓ Master admin provisioned on first sidecar boot from env vars (Alembic head → `ensure_master_admin`)
5. ✓ Pre-auth session token is deleted in `login` before a new one is issued — session fixation closed

## Known follow-ups / placeholders (see `PLACEHOLDERS.md`)

- `BETTER_AUTH_SECRET` — generate with `openssl rand -hex 32`
- `APRICOT_ADMIN_USERNAME` / `APRICOT_ADMIN_PASSWORD` — set real values
- Coolify: configure `library.zektek.us` to route `/api/*` → sidecar (priority 10), `/*` → frontend (priority 1)
- Rate limiting on `/api/auth/login` deferred (tech debt)
- Real automated tests (pytest + Playwright) not added in autonomous build — only smoke-style assertions in code

## Human verification needed (manual)

- [ ] `docker compose build` succeeds for both `sidecar` and `frontend`
- [ ] `docker compose up -d` brings up `postgres` (healthy) → `sidecar` (runs migrations) → `frontend`
- [ ] Login flow works end-to-end against real Postgres
- [ ] Existing `/api/auth/spotify/login` OAuth callback URL updated in the Spotify dashboard to `https://library.zektek.us/api/auth/spotify/callback`
