# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-29)

**Core value:** A multi-user, synchronized catalog where any logged-in user can search, fetch, and curate music — and the queue/library they see is the same view everyone else sees.
**Current focus:** Milestone v1.0 — Library Web — all phases delivered (autonomous build, 2026-05-30); manual deployment validation pending.

## Current Position

Phase: 6 of 6 (Playlists + Admin UI) — complete
Plan: All 6 phases built inline (autonomous mode)
Status: Code shipped; awaiting deploy + human verification
Last activity: 2026-05-30 — Autonomous milestone build completed

Progress: [██████████] 100%

## Performance Metrics

| Phase | Status |
|-------|--------|
| 1 — Auth Foundation | ✓ Shipped |
| 2 — SSE Hub + Queue Worker | ✓ Shipped |
| 3 — Jellyfin Catalog Proxy | ✓ Shipped |
| 4 — Home Page + Search + Fetch UI | ✓ Shipped |
| 5 — Song Detail + Metadata Editing | ✓ Shipped |
| 6 — Playlists + Admin UI | ✓ Shipped |

## Accumulated Context

### Decisions logged during build

- Frontend: SvelteKit 2 + Svelte 5 + adapter-node + Tailwind 4 + virtual-list.
- Auth: cookie-table session in shared Postgres; sidecar middleware = single source of truth; SvelteKit `hooks.server.ts` reads `/api/auth/me` to populate `locals.user`.
- Queue: single-coroutine `asyncio.Task` worker started in FastAPI `lifespan`; `SELECT FOR UPDATE SKIP LOCKED`; stale-running rows reset on boot via heartbeat watchdog.
- SSE: in-process pub/sub via `set[asyncio.Queue]`; `X-Accel-Buffering: no` + 15s ping for Traefik compatibility.
- Audio: proxied through sidecar with Range passthrough; Jellyfin API key never reaches the browser.
- Metadata: three-write strategy — Postgres (`song_metadata`) + file tags (`mutagen`) + Jellyfin (`LockData: true`).
- Topology: single domain `library.zektek.us` with Traefik path-split (`/api/*` → sidecar, `/*` → frontend).

### Blockers/Concerns (carry to next session)

- All placeholder env vars MUST be replaced before first boot — see `PLACEHOLDERS.md`.
- Coolify domain config (Traefik path priority labels) needs the configuration captured in `PLACEHOLDERS.md`.
- Jellyfin `LockData` reliability is a known issue (GitHub #11656) — the three-write strategy mitigates but validate on the running Jellyfin version after deploy.
- Tech debt list at the bottom of `PLACEHOLDERS.md` — none of these block deploy.

## Session Continuity

Last session: 2026-05-30 (autonomous build)
Stopped at: All phases shipped, code committed. Next session: review build, run `docker compose build && up`, walk through human verification list in each phase's SUMMARY.md.
Resume file: `MILESTONE-SUMMARY.md` at repo root for a top-level handoff.
