# Phase 1: Auth Foundation - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Autonomous (decisions made under Claude's discretion per user standing instructions)

<domain>
## Phase Boundary

Establish app-native authentication that closes the unauthenticated-sidecar exposure window and gives the SvelteKit app working session management. Delivers: Postgres in compose; sidecar session middleware protecting every existing and new API route; a SvelteKit scaffold with login/logout flow; a master admin auto-provisioned on first boot from environment variables.

**Not in this phase:** user creation UI, admin pages, queue, SSE, catalog browse, song detail. Phase 1 ships only the locked-down API + a single working login page.

</domain>

<decisions>
## Implementation Decisions

### Stack Additions
- Add `postgres:16` service to `docker-compose.yaml` with a named volume `postgres-data`.
- Add `frontend` service running SvelteKit 2.x with `@sveltejs/adapter-node` 5.x in a Docker multi-stage build.
- Sidecar gains `psycopg[binary]` 3.x + `sqlalchemy[asyncio]` 2.x for Postgres access, `passlib[bcrypt]` for password hashing (existing librespot/spotify code is unchanged).
- Frontend uses `better-auth` 1.x with the Drizzle adapter and `drizzle-orm` + `drizzle-kit`. Postgres is the shared session store between SvelteKit and sidecar (sidecar reads the `session` table directly).

### Schema
- Single shared Postgres database, owned by the sidecar (migrations live in `sidecar/migrations/`, applied with Alembic).
- Tables created in Phase 1: `user`, `account`, `session`, `verification` (better-auth canonical names). Permission flags live on `user` as a `JSONB` column `permissions` (e.g. `{"can_fetch": true, "can_edit_metadata": false, "is_admin": false}`).
- Master admin is a row in `user` with `permissions.is_admin = true`, provisioned via an Alembic data migration on first boot when `APRICOT_ADMIN_USERNAME` + `APRICOT_ADMIN_PASSWORD` env vars are present and no admin exists yet.

### Auth Boundary
- SvelteKit hooks.server.ts validates the session cookie via `GET /api/auth/me` against the sidecar over the Docker internal network.
- Sidecar middleware (`Depends(require_session)`) reads the cookie directly from the shared `session` table — single source of truth, no JWT.
- Cookie name: `apricot_session`. Attributes: `HttpOnly; Secure; SameSite=Lax; Path=/`. Domain unscoped (single-host deploy).
- Login regenerates the session token (deletes the old row, inserts a new one) — closes session fixation.

### Routing & Domain
- Single domain `library.zektek.us` with Traefik path-split labels in compose: `/api/*` → sidecar (priority 10), `/*` → frontend (priority 1).
- Existing `api.library.zektek.us` cert stays valid during transition; can be retired after Phase 1 ships.
- Local dev: frontend on `:5173`, sidecar on `:8000`, Vite proxy `/api` → sidecar.

### Master Admin Provisioning
- Env vars: `APRICOT_ADMIN_USERNAME`, `APRICOT_ADMIN_PASSWORD` (raw — hashed at boot, never logged).
- Provisioning runs in the sidecar's FastAPI `lifespan` startup hook after migrations apply: if no row exists in `user` with `permissions.is_admin = true`, create one from env.
- If env vars are missing on first boot, sidecar logs a clear error and refuses to start — fail-safe over silent insecurity.

### Public Routes (Pre-Login Allow-List)
- `GET /api/health` — already public, stays public.
- `POST /api/auth/login` — public (the login endpoint itself).
- `POST /api/auth/logout` — requires session.
- `GET /api/auth/me` — requires session (used by SvelteKit hooks).
- Everything else (including the existing `/search`, `/download`, `/auth/spotify/*`, `/auth/librespot/*`) requires a valid session. **Critical:** the existing `/auth/librespot/credentials` endpoint moves behind admin-only middleware in this phase — closes the public credential upload hole flagged in CONCERNS.md.

### Frontend Surface for Phase 1
- One route only: `/login` (form: username + password, submits to `/api/auth/login`).
- One protected placeholder route: `/` — shows "Logged in as {username}" + a logout button. Real home page lands in Phase 4.
- Layout shell: dark theme, minimal CSS (Tailwind 4 added in Phase 4 — Phase 1 uses unstyled-but-functional).

### Placeholders (User to Provide Later)
- `APRICOT_ADMIN_USERNAME` — actual desired admin username (default placeholder: `admin`)
- `APRICOT_ADMIN_PASSWORD` — actual desired password (default placeholder: `change-me-on-first-boot`)
- `BETTER_AUTH_SECRET` — random 32-byte hex string for cookie signing (placeholder generated via openssl)
- `library.zektek.us` DNS A record + Coolify domain config — already exists per PROJECT.md (jellyfin/slskd already on `.zektek.us`)
- All placeholders captured in `PLACEHOLDERS.md` at repo root for one-shot replacement before deploy.

### Claude's Discretion
- Test framework: pytest 8 for sidecar (existing convention), vitest for frontend.
- Lint/format: ruff + black for Python (existing); prettier + eslint for SvelteKit (sane defaults).
- Phase 1 only ships a smoke test per endpoint + a single Playwright e2e covering "login → land → refresh → logout".

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets (from `.planning/codebase/`)
- `sidecar/app/main.py` — existing FastAPI app, already has `lifespan` (used by librespot init). Auth middleware slots in here.
- `sidecar/app/config.py` — `Settings` (pydantic-settings). Add `APRICOT_ADMIN_USERNAME`, `APRICOT_ADMIN_PASSWORD`, `DATABASE_URL`, `BETTER_AUTH_SECRET`.
- `sidecar/app/auth.py` — currently holds Spotify OAuth helpers. New session middleware will live in a new `sidecar/app/sessions.py` to avoid stepping on existing Spotify code.
- `sidecar/requirements.txt` — single-source dependency file; add new pins here.
- `docker-compose.yaml` — three services (jellyfin, slskd, sidecar). Add `postgres` + `frontend`.

### Established Patterns
- Configuration via pydantic `Settings` reading env vars (continue this for auth/admin env).
- FastAPI dependency injection for cross-cutting concerns (continue this for `Depends(require_session)`).
- Volumes mounted from compose-level paths (`MEDIA_PATH`, `DOWNLOADS_PATH`) — same pattern for `postgres-data`.
- No tests exist today per `.planning/codebase/TESTING.md`. Phase 1 introduces the test scaffolding.

### Integration Points
- Existing `/auth/librespot/*` endpoints must keep working for the existing librespot credential lifecycle — they're now protected, not removed.
- Existing `/search`, `/download` endpoints stay functionally identical, just gated.
- Jellyfin and slskd services are unchanged in this phase.

</code_context>

<specifics>
## Specific Ideas

User-stated requirements informing this phase:
- "Very secure session persistent login with a master admin account" — drives the auto-provisioned admin + session regeneration on login decisions.
- "User creation, user management, and permissions" — schema designed for v1 but user-management UI deferred to Phase 6.
- "No Authentik" — confirmed: no forward-auth, no IdP, single source of truth in our Postgres.

</specifics>

<deferred>
## Deferred Ideas

- User signup UI / email verification — out of scope per PROJECT.md (admin-only account creation).
- Password reset by email — out of scope (admin resets in-app, Phase 6).
- Magic link / OAuth providers — out of scope.
- Per-route permission enforcement UI / role display — schema ready, UI in Phase 6.
- Rate limiting on `/api/auth/login` — captured as Phase 1.5 candidate; implementing now would block "ship security-first" goal. Note added to PLACEHOLDERS / tech-debt list.

</deferred>
