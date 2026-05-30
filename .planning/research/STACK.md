# Stack Research

**Domain:** Self-hosted multi-user music library frontend (SvelteKit + FastAPI sidecar + Postgres + Jellyfin)
**Researched:** 2026-05-29
**Confidence:** HIGH (most choices verified against current npm/PyPI releases and official docs)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| SvelteKit | 2.x (`@sveltejs/kit` 2.61.1) | Frontend framework | User constraint; lightweight SSR/SPA with built-in server routes that can proxy to sidecar, eliminating a separate CORS problem |
| `@sveltejs/adapter-node` | 5.5.4 | Docker deployment | Produces a standalone Node.js HTTP server; only adapter that works inside Coolify Docker Compose without a separate CDN |
| better-auth | 1.6.11 | App-native auth | Only third-party auth library with Svelte CLI integration and first-class SvelteKit hooks support; explicitly recommended on svelte.dev/docs/kit/auth; actively maintained (1.7 beta in progress) |
| Drizzle ORM | 0.45.2 | SvelteKit-side DB access | Type-safe, lightweight; better-auth's Svelte CLI add-on generates Drizzle schemas automatically; least ceremony for a small schema |
| drizzle-kit | latest | Schema migrations | Paired CLI for generating and running migrations from Drizzle schema files |
| Postgres | 16-alpine | App-state database | Multi-user sessions, queue, playlists, fetch history require a real RDBMS; alpine image is small and stable |
| FastAPI | 0.115.x (existing) | Backend sidecar — extended | Existing; extend with auth-adjacent endpoints (queue, SSE, Jellyfin proxy routes) |
| SQLAlchemy | 2.0.50 (`sqlalchemy[asyncio]`) | Sidecar ORM | Async-first in 2.x; pairs with psycopg for clean `async with session` patterns; avoids raw SQL string building |
| psycopg | 3.3.4 (`psycopg[binary,pool]`) | Python Postgres driver | Modern successor to psycopg2; natively async; single package covers both sync and async; SQLAlchemy 2 picks the right dialect automatically from `postgresql+psycopg://` URL |
| sse-starlette | 3.4.4 | SSE in FastAPI | Production-ready `EventSourceResponse`; handles disconnect, ping keepalive, graceful shutdown; last published May 2026 |
| argon2-cffi | 25.1.0 | Password hashing | Winner of the Password Hashing Competition; simple `PasswordHasher` API; only correct choice for new projects |
| httpx | 0.27.x (existing) | Jellyfin REST client | Already in the sidecar; no new dependency needed; use `AsyncClient` for catalog calls |

### Supporting Libraries (Frontend)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pg` (node-postgres) | ^8 | better-auth's native Postgres adapter | better-auth uses it internally when passed a `Pool`; install alongside Drizzle |
| `svelte` | 5.x | Component compiler | Ships with SvelteKit 2; Svelte 5 runes syntax is now stable and the default |
| `@better-auth/drizzle-adapter` | latest | Links better-auth schema to Drizzle | Lets `npx auth@latest migrate` generate Drizzle-compatible schema files instead of raw SQL |

### Supporting Libraries (Sidecar / FastAPI)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic` v2 | bundled with FastAPI | Queue/session request models | Already present; define `QueueItem`, `UserCreate`, `SessionPayload` Pydantic models |
| `psycopg-pool` | bundled with `psycopg[pool]` | Connection pooling | Use `AsyncConnectionPool` with a fixed pool size (4–8) inside FastAPI lifespan |
| `python-ulid` or `uuid` stdlib | — | Session/queue IDs | `uuid.uuid4()` from stdlib is sufficient; no new dep needed |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `drizzle-kit` | Schema generation and migrations | Run `npx drizzle-kit generate` then `npx drizzle-kit migrate` |
| `npx auth@latest` | Generate better-auth schema | Run once; outputs Drizzle schema for user/session tables |
| `vite` | SvelteKit dev server | Bundled with SvelteKit; no separate install |
| Node 22-alpine | Docker base image for frontend | LTS; smallest Alpine variant; matches adapter-node requirements |

---

## Installation

```bash
# Frontend — run from repo root or a /frontend subdirectory
npm create svelte@latest frontend  # choose "Skeleton project", TypeScript
cd frontend
npm install better-auth @better-auth/drizzle-adapter drizzle-orm pg
npm install -D drizzle-kit @types/pg
npm install @sveltejs/adapter-node

# Sidecar additions — add to sidecar/requirements.txt
sqlalchemy[asyncio]==2.0.50
psycopg[binary,pool]==3.3.4
sse-starlette==3.4.4
argon2-cffi==25.1.0
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| better-auth | Auth.js (NextAuth) | If you need OAuth providers heavily (GitHub, Google login) — better-auth handles those too, but Auth.js has more social provider examples |
| better-auth | Hand-rolled sessions | Only if you need a zero-dependency approach and are comfortable writing session middleware, CSRF logic, and cookie signing from scratch — adds 2–3 days of low-value work |
| better-auth | Lucia | **Do not use.** Lucia is deprecated as of late 2024; the author explicitly retired it and now maintains a reference implementation guide instead |
| psycopg (3) | asyncpg | asyncpg is ~5x faster in benchmarks but lacks SQLAlchemy 2 `create_engine` parity and requires `asyncpg://` dialect; psycopg 3 has native asyncio, SQLAlchemy 2 support, and simpler DBAPI compatibility |
| SQLAlchemy 2 async | raw asyncpg queries | Use raw asyncpg only if you need maximum throughput on a hot query path; the ORM overhead is irrelevant at this app's scale |
| Drizzle ORM | Prisma | Prisma requires a Rust query engine binary inside the container, adding ~100 MB; Drizzle is pure JS/TS and has zero binary deps |
| sse-starlette | Plain `StreamingResponse` | Plain `StreamingResponse` works but you must manually implement keepalive pings, disconnect detection, and SSE formatting; sse-starlette covers all of this |
| httpx (existing) | jellyfin-apiclient-python | `jellyfin-apiclient-python` is sync-only and extracted from Kodi — mismatched to an async FastAPI app; `jellyfin-api-client` (httpx-based) was archived Feb 2025; raw httpx with manual header auth is cleaner |
| Postgres 16-alpine | Postgres 17 | Either works; 16 is current LTS and more battle-tested on Coolify compose stacks |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Lucia auth | Deprecated and retired by its author in late 2024; no longer maintained | better-auth |
| Auth.js (for this use case) | Primarily designed around OAuth social login flows; rolling admin-created-only accounts with custom permissions requires fighting Auth.js's assumptions; absent from svelte.dev/docs/kit/auth | better-auth |
| Authentik forward-auth | Already dropped from PROJECT.md; requires external service, no fine-grained in-app permission model | better-auth with custom role plugin |
| `psycopg2` / `psycopg2-binary` | Sync-only; psycopg2-binary is known to conflict with system SSL libraries in Alpine Docker images | psycopg 3 (`psycopg[binary]`) |
| `jellyfin-api-client` (GeoffreyCoulaud) | Archived February 2025, no longer maintained | Raw httpx calls with `Authorization: MediaBrowser Token=...` header |
| `jellyfin-apiclient-python` | Sync-only (extracted from Kodi); incompatible with FastAPI's async event loop without thread offloading | Raw httpx `AsyncClient` |
| JWT for sessions | JWTs cannot be invalidated server-side; a revoked/banned user stays valid until token expiry; unsuitable for a multi-user admin app | DB-backed opaque session tokens (what better-auth uses by default) |
| WebSockets for queue sync | More complex to proxy behind Coolify/nginx; requires connection management logic; one-way updates don't need full-duplex | SSE via sse-starlette |
| Redis for queue state | Extra service, extra operational burden; Postgres with `SKIP LOCKED` or `FOR UPDATE` handles a serial job queue perfectly at this scale | Postgres queue table |

---

## Architecture Notes by Topic

### Auth Strategy

better-auth 1.6.x is the right call. Rationale:

1. **Official SvelteKit endorsement.** `svelte.dev/docs/kit/auth` names it by name with CLI integration; Auth.js is not mentioned.
2. **SvelteKit hooks integration.** `svelteKitHandler` mounts to `hooks.server.ts` in one import; session is available as `event.locals.user` anywhere in load functions and server routes.
3. **Postgres native adapter.** Pass a `pg.Pool` directly — no Prisma engine, no binary deps.
4. **Admin-only user creation.** better-auth's email/password plugin supports disabling public signup; user creation happens via an admin API route calling `auth.api.createUser(...)`.
5. **Session cookies.** better-auth sets `httpOnly`, `secure`, `sameSite=lax` session cookies by default; sessions are DB-backed opaque tokens, not JWTs.

Do not implement a custom session layer. better-auth's built-in session table + cookie handling covers the requirements exactly.

### Postgres in Coolify

Add a `postgres` service to the existing `docker-compose.yaml`. Coolify automatically networks all services in a compose file — the sidecar and frontend can reach Postgres at `postgres:5432` internally. No separate Coolify resource needed.

```yaml
postgres:
  image: postgres:16-alpine
  environment:
    POSTGRES_DB: apricot
    POSTGRES_USER: apricot
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  volumes:
    - postgres-data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U apricot"]
    interval: 10s
    timeout: 5s
    retries: 5
```

### Sidecar Postgres Connection

Use psycopg 3 + SQLAlchemy 2 async with a connection pool initialized in the FastAPI lifespan:

```python
# sidecar/app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    "postgresql+psycopg://apricot:password@postgres:5432/apricot",
    pool_size=5,
    max_overflow=10,
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

`psycopg` (not `asyncpg`) is chosen because it uses the same package for both sync and async, has better SQLAlchemy 2 dialect integration, and avoids the `asyncpg://` vs `postgresql+asyncpg://` URL confusion that trips up migrations.

### SSE Pattern

```python
# sidecar/app/routes/queue.py
from sse_starlette.sse import EventSourceResponse

@router.get("/queue/stream")
async def queue_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            queue_state = await get_queue_state(db)
            yield {"event": "queue_update", "data": queue_state.model_dump_json()}
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())
```

SvelteKit frontend consumes with native `EventSource` — no library needed. SSE reconnects automatically on network drop.

### Jellyfin REST API

Use the existing `httpx.AsyncClient` in the sidecar. Auth header format:

```python
headers = {
    "Authorization": 'MediaBrowser Client="ApricotLibrary", Device="Server", DeviceId="apricot-sidecar", Version="1.0", Token="{jellyfin_api_key}"'
}
```

Key catalog endpoints:
- `GET /Items?IncludeItemTypes=Audio&Recursive=true` — all songs
- `GET /Items/{itemId}` — song detail, metadata
- `GET /Items/{itemId}/Images/Primary` — cover art (redirect to Jellyfin URL directly in `<img src>`)
- `POST /Items/{itemId}` — metadata edit

**Audio playback in browser:** Do NOT proxy audio through the sidecar. Jellyfin serves audio directly. The sidecar returns a signed Jellyfin stream URL to the frontend:

```
https://jellyfin.zektek.us/Audio/{itemId}/universal?api_key={jellyfin_api_key}&container=ogg,mp3,flac
```

The `api_key` query parameter is acceptable for browser `<audio src>` elements where header injection is impossible. This is a Jellyfin-documented pattern. The Jellyfin API key is a server-scoped admin key stored in sidecar env vars, never exposed to the browser directly — the sidecar generates a short-lived playback URL or the frontend requests it from a sidecar endpoint that returns the URL.

### Deployment Topology (Coolify)

Two options — **recommend Option A**:

**Option A: Separate origins, CORS on sidecar (simpler)**
- Frontend: `library.zektek.us` (SvelteKit node, port 3000)
- Sidecar: `api.library.zektek.us` (FastAPI, port 8000, existing)
- Frontend calls sidecar via fetch with `credentials: 'include'`; sidecar sets `Access-Control-Allow-Origin: https://library.zektek.us` and `Access-Control-Allow-Credentials: true`
- FastAPI: `CORSMiddleware(allow_origins=["https://library.zektek.us"], allow_credentials=True)`

**Option B: Same origin via nginx path prefix (more complex)**
- Single domain `library.zektek.us`; nginx routes `/api/*` to sidecar, `/*` to SvelteKit
- Requires Coolify custom nginx config or a dedicated nginx service in compose
- FastAPI needs `root_path="/api"` to fix OpenAPI URL generation
- Eliminates CORS entirely but adds nginx complexity

For a Coolify-managed stack, **Option A is simpler** — Coolify already provisions separate reverse proxy entries per service. CORS configuration is a 5-line addition to `sidecar/app/main.py`.

### Session Cookie Strategy

better-auth handles this automatically:
- Cookie name: `better-auth.session_token` (configurable)
- Flags: `httpOnly=true`, `secure=true` (production), `sameSite=lax`
- Value: opaque random token (not JWT) stored in better-auth's `session` table in Postgres
- Expiry: 30-day default, sliding window on activity

The frontend never reads the session cookie value from JavaScript — it only sends it automatically with every `fetch` to the same origin (or cross-origin with `credentials: 'include'`).

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `@sveltejs/kit` 2.61.1 | `@sveltejs/adapter-node` 5.5.4 | adapter-node 5.x requires kit 2.x; verified |
| `svelte` 5.x | SvelteKit 2.x | Svelte 5 is the default; runes syntax stable |
| `better-auth` 1.6.11 | `drizzle-orm` 0.45.x, `pg` 8.x | Drizzle adapter tested on 0.44+ per official docs |
| `sqlalchemy` 2.0.50 | `psycopg` 3.3.4 | Use dialect `postgresql+psycopg://`; SQLAlchemy auto-selects async variant |
| `fastapi` 0.115.x | `sse-starlette` 3.4.4 | sse-starlette 3.x requires Python ≥3.10; FastAPI 0.115 ships with Starlette 0.40+ |
| `argon2-cffi` 25.1.0 | Python 3.12 (sidecar) | Supports Python 3.8–3.14; 3.12 is fine |

---

## Sources

- [better-auth SvelteKit integration docs](https://better-auth.com/docs/integrations/svelte-kit) — hooks.server.ts pattern, sveltekitCookies plugin — HIGH confidence
- [better-auth PostgreSQL adapter docs](https://better-auth.com/docs/adapters/postgresql) — pg Pool setup, Kysely-under-the-hood — HIGH confidence
- [svelte.dev/docs/kit/auth](https://svelte.dev/docs/kit/auth) — Official SvelteKit recommendation of better-auth — HIGH confidence
- [svelte.dev/docs/cli/better-auth](https://svelte.dev/docs/cli/better-auth) — Svelte CLI add-on details — HIGH confidence
- [sse-starlette PyPI](https://pypi.org/project/sse-starlette/) — version 3.4.4, May 2026, Python ≥3.10 — HIGH confidence
- [argon2-cffi PyPI](https://pypi.org/project/argon2-cffi/) — version 25.1.0, June 2025 — HIGH confidence
- [psycopg PyPI](https://pypi.org/project/psycopg/) — version 3.3.4, async support confirmed — HIGH confidence
- [SQLAlchemy PyPI](https://pypi.org/project/SQLAlchemy/) — version 2.0.50, asyncio extra, May 2026 — HIGH confidence
- [drizzle-orm npm](https://www.npmjs.com/package/drizzle-orm) — version 0.45.2 — HIGH confidence
- [@sveltejs/kit npm](https://www.npmjs.com/package/@sveltejs/kit) — version 2.61.1 — HIGH confidence
- [@sveltejs/adapter-node npm](https://www.npmjs.com/package/@sveltejs/adapter-node) — version 5.5.4 — HIGH confidence
- [better-auth npm](https://www.npmjs.com/package/better-auth) — version 1.6.11 — HIGH confidence
- [Jellyfin API overview](https://jmshrv.com/posts/jellyfin-api/) — audio stream endpoint, auth header format — MEDIUM confidence (community blog, cross-referenced with Jellyfin gist)
- [Jellyfin auth gist](https://gist.github.com/nielsvanvelzen/ea047d9028f676185832e51ffaf12a6f) — MediaBrowser Authorization header format — MEDIUM confidence

---

*Stack research for: Apricot Library — SvelteKit frontend milestone*
*Researched: 2026-05-29*
