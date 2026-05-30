# Architecture Research

**Domain:** Self-hosted multi-user music library — SvelteKit frontend + FastAPI backend + Postgres + Jellyfin
**Researched:** 2026-05-29
**Confidence:** HIGH (most decisions derivable from first principles + verified patterns)

---

## Standard Architecture

### System Overview

```
                        COOLIFY REVERSE PROXY (Traefik)
                               |
          ┌────────────────────┼────────────────────┐
          │                    │                     │
   library.zektek.us    jellyfin.zektek.us    slskd.zektek.us
   (path-split below)         │                     │
          │                   │                     │
  ┌───────┴───────┐    ┌──────┴──────┐    ┌─────────┴────────┐
  │  /* → SK      │    │  Jellyfin   │    │      slskd       │
  │  /api/* → SC  │    │  :8096      │    │      :5030       │
  └───────────────┘    └─────────────┘    └──────────────────┘
          │
     ┌────┴──────────────────┐
     │                       │
┌────▼────┐           ┌──────▼─────┐
│SvelteKit│           │  Sidecar   │
│ :3000   │           │  FastAPI   │
│ (Node)  │           │  :8000     │
└─────────┘           └──────┬─────┘
                             │
             ┌───────────────┼───────────────┐
             │               │               │
       ┌─────▼────┐  ┌───────▼──────┐  ┌────▼────────┐
       │ Postgres │  │ Jellyfin API │  │ Spotify API │
       │ :5432    │  │ (internal)   │  │ (external)  │
       └──────────┘  └──────────────┘  └─────────────┘
```

**Communication rules:**
- Browsers talk to one domain: `library.zektek.us`
- Traefik splits on path prefix: `/* → SvelteKit`, `/api/* → sidecar`
- SvelteKit server-side (SSR, load functions, hooks) talks to sidecar at `http://sidecar:8000` (internal Docker network, no TLS, no round-trip through Traefik)
- Sidecar talks to Jellyfin at `http://jellyfin:8096` (internal, same compose network)
- Browsers never talk directly to sidecar, Postgres, or Jellyfin — everything proxied

---

## Component Boundaries

| Component | Owns | Does NOT Own |
|-----------|------|-------------|
| SvelteKit | Page rendering, client-side state, SSE event handling, cookie management, route protection | Business logic, Jellyfin calls, queue mutations, auth validation |
| Sidecar (FastAPI) | Auth (sessions, users), queue state, SSE hub, Jellyfin proxy, Spotify search, librespot downloads | HTML rendering, cookie parsing (passes tokens in Authorization header) |
| Postgres | Users, sessions, queue rows, fetch history, playlists | Audio files, Jellyfin catalog metadata |
| Jellyfin | Audio file serving, catalog metadata, library scanning, cover art | User accounts (Library users), queue state |

**Key boundary decision:** SvelteKit's server side is a thin proxy and renderer. It validates sessions via a call to the sidecar (or by decoding a session token), populates `event.locals.user`, then delegates all mutations to the sidecar over internal HTTP. No business logic lives in SvelteKit `+page.server.ts` files beyond "is the user allowed to see this, and what data does the page need."

---

## Answers to Each Architecture Question

### Q1: Queue Worker Location

**Decision: asyncio.Queue + single worker coroutine in FastAPI lifespan. No separate container. Celery/ARQ are overkill.**

Rationale: The queue requirement is strictly serial (one download at a time), in-process (needs access to the librespot session singleton and the SSE broadcaster), and low-volume (music downloads, not web-scale jobs). Adding a separate container (with RQ/Celery) means adding a Redis or RabbitMQ broker, a worker Dockerfile, and inter-process communication overhead — none of which buys anything for a single serial worker that already shares a process with the SSE hub.

The pattern uses FastAPI's `lifespan` context manager to start the worker at startup:

```python
fetch_queue: asyncio.Queue = asyncio.Queue()

@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(fetch_worker())
    yield
    worker_task.cancel()

async def fetch_worker():
    while True:
        job = await fetch_queue.get()
        try:
            await run_fetch(job)       # calls librespot in thread pool
        except Exception as e:
            await mark_failed(job, e)
        finally:
            fetch_queue.task_done()
```

The worker coroutine awaits the queue. Only one item runs at a time because there is one coroutine and it `await`s each job to completion before taking the next. No locks needed. `asyncio.create_task()` result is held in a module-level variable to prevent GC collection.

**What this does NOT handle:** If the sidecar restarts mid-download, the active job is lost. Mitigation: on startup, scan Postgres for any `status='running'` rows and reset them to `status='queued'` so they re-enter the queue. Do not try to resume partial downloads.

**Data in Postgres, not in the queue object:** The asyncio queue holds only a `job_id` (UUID). The worker fetches the full job record from Postgres. This means the queue is reconstructible after restart by loading all `status='queued'` rows in `created_at` order.

---

### Q2: SSE Fan-Out

**Decision: In-process asyncio pub/sub (connection manager with per-client asyncio.Queue). No Redis, no Postgres LISTEN/NOTIFY.**

There is one sidecar instance (Coolify single-replica compose service). All SSE connections land on the same process. A simple in-process broadcaster is sufficient and has zero external dependencies.

Pattern:

```python
class SSEBroadcaster:
    def __init__(self):
        self._clients: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._clients.discard(q)

    async def broadcast(self, event: dict):
        dead = set()
        for q in self._clients:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.add(q)   # slow/dead client, drop it
        self._clients -= dead

broadcaster = SSEBroadcaster()
```

SSE endpoint:

```python
@router.get("/events")
async def sse_stream(request: Request, user=Depends(require_session)):
    q = broadcaster.subscribe()
    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                event = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            broadcaster.unsubscribe(q)
    return StreamingResponse(generator(), media_type="text/event-stream")
```

The fetch worker calls `await broadcaster.broadcast({...})` after each state change (job started, progress update, job completed, library scan triggered).

**Why not Postgres LISTEN/NOTIFY:** LISTEN/NOTIFY is useful when multiple processes need to communicate or when you want the DB to be the source of notification truth. With a single-process sidecar, it adds a persistent listener connection, a psycopg async driver dependency, and a fanout wrapper class — all to replicate what a module-level dict of asyncio.Queues already does. Add it only if the sidecar ever scales to multiple replicas.

**Why not Redis Pub/Sub:** Same reasoning. Zero benefit for single-replica; adds an operational dependency.

---

### Q3: Auth Boundary

**Decision: Session validation lives in the sidecar as a dependency; SvelteKit hooks call the sidecar once per request to validate and populate locals.**

Two sub-patterns are viable. The recommended one for this stack:

**Signed session tokens (JWT or PASETO) stored in httpOnly cookies:**
1. Sidecar issues a signed token on login; stores session record in Postgres.
2. SvelteKit `hooks.server.ts` reads the cookie, sends it to `http://sidecar:8000/auth/me` (internal).
3. Sidecar validates signature + checks session is not revoked in Postgres, returns `{user_id, roles}`.
4. SvelteKit stores result in `event.locals.user`.
5. All `+page.server.ts` load functions and `+server.ts` API routes check `event.locals.user`.

**Server-to-server calls (SvelteKit → sidecar):** Use `handleFetch` in `hooks.server.ts` to inject the session token as a `Bearer` header on all internal fetch calls. This avoids cookie forwarding complexity — the browser cookie is only for browser→SvelteKit; SvelteKit→sidecar uses the token as a Bearer header.

```typescript
// hooks.server.ts
export const handle: Handle = async ({ event, resolve }) => {
    const token = event.cookies.get('session');
    if (token) {
        const res = await fetch('http://sidecar:8000/auth/me', {
            headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) event.locals.user = await res.json();
    }
    return resolve(event);
};

export const handleFetch: HandleFetch = async ({ request, fetch }) => {
    // Internal sidecar calls get the session token injected
    if (request.url.startsWith('http://sidecar:8000')) {
        request.headers.set('Authorization', `Bearer ${event.locals.token}`);
    }
    return fetch(request);
};
```

**Cookie scope:** With a single domain (`library.zektek.us`), set `cookie.domain=library.zektek.us`, `Secure`, `HttpOnly`, `SameSite=Lax`. The cookie is scoped to one domain, which is exactly right — the browser never needs to send it to `api.library.zektek.us` (that domain goes away in the single-domain topology).

**Sidecar middleware:** Protected sidecar endpoints use a `Depends(require_session)` FastAPI dependency that extracts the Bearer token and validates it. This is the authoritative validation point; SvelteKit's hook validation is for UX (redirect to login) only, not for security enforcement.

---

### Q4: Reverse Proxy / Domains

**Decision: Single domain `library.zektek.us` with path-split routing. `/api/*` → sidecar, `/*` → SvelteKit.**

**Why single domain wins:**
- Cookies work without any cross-domain configuration (`SameSite=Lax` is safe; no `SameSite=None`+Secure complexity)
- No CORS headers needed between SvelteKit and the sidecar from the browser's perspective (same origin)
- One SSL certificate
- Simpler mental model: the app is one thing at one URL

**Why separate subdomains lose:**
- Session cookie must be set on `.zektek.us` (root domain) to span subdomains, which means the cookie is also sent to `jellyfin.zektek.us` and `slskd.zektek.us` — a security smell
- CORS required for browser-side fetches from `library.zektek.us` to `api.library.zektek.us`
- `api.library.zektek.us` already exists but is currently only used for `curl`; retiring it is low-friction

**Traefik labels (in docker-compose.yaml):**

```yaml
services:
  sveltekit:
    labels:
      - traefik.enable=true
      - "traefik.http.routers.sk.rule=Host(`library.zektek.us`)"
      - "traefik.http.routers.sk.priority=1"
      - "traefik.http.services.sk.loadbalancer.server.port=3000"
      - "traefik.http.routers.sk.tls=true"
      - "traefik.http.routers.sk.tls.certresolver=letsencrypt"

  sidecar:
    labels:
      - traefik.enable=true
      - "traefik.http.routers.sc.rule=Host(`library.zektek.us`) && PathPrefix(`/api`)"
      - "traefik.http.routers.sc.priority=10"
      - "traefik.http.services.sc.loadbalancer.server.port=8000"
      - "traefik.http.routers.sc.tls=true"
      - "traefik.http.routers.sc.tls.certresolver=letsencrypt"
```

Higher priority on the sidecar router ensures `/api/*` matches before the catch-all SvelteKit router. The sidecar strips the `/api` prefix via a Traefik `StripPrefix` middleware or the sidecar mounts its routes under `/api` itself (the latter is simpler and avoids middleware config).

**Recommendation:** Mount all new sidecar routes under `/api/` prefix in FastAPI. Existing `api.library.zektek.us` routes can be preserved during transition via Coolify by keeping that domain pointed at the sidecar.

**ORIGIN env var for SvelteKit:** Set `ORIGIN=https://library.zektek.us` in the SvelteKit container so it generates correct absolute URLs.

---

### Q5: Jellyfin API Access

**Decision: Sidecar proxies all Jellyfin API calls. SvelteKit server-side never calls Jellyfin directly. Browser never calls Jellyfin.**

Rationale:
- The sidecar holds the Jellyfin API key as an environment variable; SvelteKit does not need it.
- Centralizing Jellyfin access in the sidecar means one place to add caching, error normalization, and response shaping.
- Jellyfin's response format is verbose and Jellyfin-specific; the sidecar translates it to the app's domain model (track objects with normalized fields).
- Jellyfin's internal URL (`http://jellyfin:8096`) is not routable from the browser; proxying is required anyway for catalog browsing.

The sidecar adds a new router (`sidecar/app/catalog.py`) with endpoints like:
- `GET /api/catalog/tracks` — lists all tracks (proxied + normalized from Jellyfin `/Users/{id}/Items`)
- `GET /api/catalog/tracks/{id}` — single track with metadata
- `GET /api/catalog/tracks/{id}/cover` — cover art proxy
- `GET /api/storage` — disk usage stats

The Jellyfin admin API key (not a user token) is used for these calls. It's set once in the sidecar's environment and never leaves the sidecar.

---

### Q6: Audio Streaming

**Decision: Sidecar issues a short-lived signed URL that SvelteKit renders into an `<audio src>`. The browser fetches audio via a sidecar proxy endpoint, which forwards the request to Jellyfin with the API key header.**

Why not `api_key` in the URL directly to Jellyfin:
- Jellyfin's `api_key` query parameter is deprecated and marked for removal in v12.0. The `Authorization` header is the supported path.
- Browsers cannot set the `Authorization` header on `<audio src>` requests — that's a direct resource load, not a fetch.
- Exposing the Jellyfin API key in a URL leaks it to browser history, proxy logs, and copy-paste.

The sidecar proxy endpoint:
```
GET /api/audio/{item_id}/stream
```

SvelteKit renders `<audio src="/api/audio/{id}/stream">`. The browser hits the sidecar (same domain, cookies included). The sidecar validates the session, then streams from Jellyfin using the `Authorization: MediaBrowser Token="{JELLYFIN_API_KEY}"` header. The sidecar passes through the `Content-Type`, `Content-Length`, and `Range` headers so seeking works.

For the song detail page's one-off playback, this is sufficient. Performance: Jellyfin serves OGG files (already final format, no transcoding), so the proxy just forwards bytes. At small user counts, this adds negligible latency.

**Short-lived URL alternative (future):** If seek performance degrades or large files cause sidecar memory pressure, switch to sidecar-issued signed URLs (HMAC + expiry + item_id) that the browser presents directly to a lightweight streaming endpoint. This avoids the sidecar buffering the full stream.

---

### Q7: Data Flow — "Add to Queue" → Download → Library Scan → UI Update

Complete sequence:

```
1. User clicks "Add to queue" on search result
   Browser → POST /api/queue  (with session cookie)

2. Sidecar validates session
   FastAPI dependency → Postgres: verify session token → return user record

3. Sidecar inserts queue row
   INSERT INTO fetch_queue (track_id, spotify_id, status='queued', requested_by, created_at)

4. Sidecar enqueues job ID
   fetch_queue.put_nowait(job_id)

5. Sidecar broadcasts queue-updated event to all SSE clients
   broadcaster.broadcast({type: 'queue_update', queue: [...]})
   → all connected browsers receive the event instantly
   → SvelteKit client updates queue display reactively

6. Sidecar returns 201 to browser
   {job_id, position_in_queue}

7. [Background] Worker coroutine picks up job_id
   UPDATE fetch_queue SET status='running' WHERE id=job_id
   broadcaster.broadcast({type: 'fetch_started', job_id, track})

8. Worker calls librespot in thread pool
   asyncio.to_thread(librespot_session.download_track, spotify_id, output_path)
   → streams OGG into /media/Artist/Album/Track.ogg

9. Worker triggers Jellyfin library scan
   POST http://jellyfin:8096/Library/Refresh  (with API key header)
   → Jellyfin scans /media, finds new file, indexes it

10. Worker marks job complete
    UPDATE fetch_queue SET status='done', completed_at=now()
    broadcaster.broadcast({type: 'fetch_complete', job_id, track})
    broadcaster.broadcast({type: 'library_updated'})

11. SvelteKit client receives 'library_updated' SSE event
    → refetches catalog data from /api/catalog/tracks
    → home page song list updates
```

**Jellyfin scan timing:** Jellyfin's `/Library/Refresh` is async — it queues an internal scan and returns immediately. The actual scan takes seconds to minutes depending on library size. Broadcasting `library_updated` immediately after triggering the scan may cause the client to refetch before Jellyfin has indexed the new track. Mitigation: poll `GET /api/catalog/tracks/{spotify_id}` from the client after receiving `fetch_complete` until the track appears (max 30s, 2s interval). Or: sidecar polls Jellyfin's task endpoint to detect scan completion before broadcasting `library_updated`.

---

### Q8: Component Boundaries and Build Order

#### Component Map

| Component | Location | Dependencies |
|-----------|----------|-------------|
| Postgres service | docker-compose.yaml | None |
| DB schema + migrations | `sidecar/migrations/` (Alembic) | Postgres |
| Auth endpoints (`/api/auth/*`) | `sidecar/app/auth_users.py` | Postgres (users, sessions) |
| Queue endpoints (`/api/queue/*`) | `sidecar/app/queue.py` | Postgres, auth, asyncio worker, broadcaster |
| Catalog endpoints (`/api/catalog/*`) | `sidecar/app/catalog.py` | Jellyfin API, auth |
| Audio proxy (`/api/audio/*`) | `sidecar/app/audio.py` | Jellyfin API, auth |
| SSE endpoint (`/api/events`) | `sidecar/app/sse.py` | broadcaster, auth |
| SvelteKit service | `frontend/` | Sidecar API (all of above) |

#### Build Order (strict dependency order)

**Step 1: Postgres + Schema**
Nothing else can be built without the DB. Add Postgres service to docker-compose.yaml. Add Alembic. Write initial migration: `users`, `sessions`, `fetch_queue`, `fetch_history`, `playlists`.

**Step 2: App-Native Auth (sidecar side)**
`POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`. Admin seed (first-run creates admin from env vars). `Depends(require_session)` FastAPI dependency. No SvelteKit yet — verify with curl.

**Step 3: SSE Hub + Queue Worker (sidecar side)**
`SSEBroadcaster` class. `asyncio.Queue` + worker coroutine in lifespan. `POST /api/queue` (add job). `GET /api/queue` (list). `GET /api/events` (SSE stream). Verify fan-out with two curl SSE connections open simultaneously.

**Step 4: Catalog + Audio Proxy (sidecar side)**
Jellyfin proxy endpoints. Audio streaming proxy. Storage stats endpoint. Verify with curl against the running compose stack.

**Step 5: SvelteKit service scaffold**
Add `frontend/` directory. `@sveltejs/adapter-node`. Docker image. Add to docker-compose.yaml. Wire Traefik labels for path routing. Verify `/` → SvelteKit, `/api/health` → sidecar.

**Step 6: Auth flows in SvelteKit**
`hooks.server.ts` session validation. Login page (`/login`). Route protection. `event.locals.user` populated on all protected routes.

**Step 7: Home page + queue UI**
Song list from `/api/catalog/tracks`. SSE connection for live updates. Queue display. "Add to queue" button wired to `POST /api/queue`.

**Step 8: Song detail + audio playback**
Song page with metadata. `<audio>` player via `/api/audio/{id}/stream`. Edit metadata form (`PATCH /api/catalog/tracks/{id}`).

**Step 9: Admin UI**
User management (create/list/disable users). Assign permissions. Storage stats.

---

## Recommended Project Structure

```
library/
├── sidecar/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── migrations/
│   │   └── versions/
│   └── app/
│       ├── main.py           # FastAPI instance, lifespan, router includes
│       ├── config.py         # Settings (add DB_URL, JELLYFIN_API_KEY, SESSION_SECRET)
│       ├── db.py             # SQLAlchemy engine, session factory, Base
│       ├── models.py         # ORM models: User, Session, FetchJob, Playlist
│       ├── auth_users.py     # /api/auth/* routes, session issuance, require_session dep
│       ├── queue.py          # /api/queue/* routes, fetch_worker coroutine
│       ├── sse.py            # /api/events SSE endpoint, SSEBroadcaster
│       ├── catalog.py        # /api/catalog/* Jellyfin proxy routes
│       ├── audio.py          # /api/audio/* streaming proxy
│       ├── spotify.py        # (existing) SpotifyClient
│       ├── librespot_session.py  # (existing) download_track
│       └── auth.py           # (existing, rename to auth_spotify.py to avoid collision)
├── frontend/
│   ├── Dockerfile            # FROM node:22-alpine, build + serve via adapter-node
│   ├── package.json
│   ├── svelte.config.js      # adapter-node
│   ├── vite.config.ts
│   └── src/
│       ├── app.html
│       ├── app.css
│       ├── hooks.server.ts   # session validation, handleFetch injection
│       ├── lib/
│       │   ├── server/
│       │   │   └── api.ts    # typed fetch wrapper for sidecar calls
│       │   ├── components/   # shared UI components
│       │   └── stores.ts     # SSE-fed client stores (queue, library state)
│       └── routes/
│           ├── +layout.server.ts   # user auth check, pass to layout
│           ├── +layout.svelte      # nav, SSE connection lifecycle
│           ├── login/
│           │   └── +page.svelte
│           ├── (app)/              # protected route group
│           │   ├── +layout.server.ts   # guard: redirect to /login if no user
│           │   ├── +page.svelte        # home: songs, queue, storage
│           │   ├── songs/[id]/
│           │   │   └── +page.svelte    # song detail + audio player
│           │   └── admin/
│           │       └── +page.svelte    # user management
│           └── api/                # SvelteKit API routes if needed (avoid: prefer sidecar)
├── docker-compose.yaml       # add: postgres, sveltekit services; update: sidecar labels
├── .env.example              # add: DB_URL, SESSION_SECRET, JELLYFIN_API_KEY
└── tools/
    └── get_credentials.py    # (existing)
```

---

## Patterns to Follow

### Pattern 1: SvelteKit as Thin Proxy, Not Business Logic Layer

SvelteKit `+page.server.ts` files should only: (1) check auth via locals, (2) fetch data from sidecar, (3) return it to the page. Never write DB queries, never call Jellyfin, never manipulate queue state directly from SvelteKit server code.

This keeps the sidecar as the single authoritative API surface and makes the frontend swappable.

### Pattern 2: SSE Client Lifecycle in Layout

Open the SSE connection in `+layout.svelte` `onMount()`, not in individual pages. This gives a single persistent connection for the app session. Reconnect with exponential backoff on disconnect (the browser `EventSource` API handles reconnection automatically for the standard SSE spec). Store events in Svelte stores so all pages react.

```typescript
// +layout.svelte
import { queueStore, libraryStore } from '$lib/stores';

onMount(() => {
    const es = new EventSource('/api/events');
    es.onmessage = (e) => {
        const event = JSON.parse(e.data);
        if (event.type === 'queue_update') queueStore.set(event.queue);
        if (event.type === 'library_updated') libraryStore.invalidate();
    };
    return () => es.close();
});
```

### Pattern 3: Queue State in Postgres, asyncio.Queue Holds Only IDs

The asyncio.Queue is an in-memory dispatch mechanism. Postgres is the source of truth. On startup, the lifespan loads all `status='queued'` rows ordered by `created_at` and re-enqueues them. This gives crash-recovery for free.

### Pattern 4: Jellyfin API Key — Never in Frontend

The Jellyfin API key lives only in the sidecar's environment. The SvelteKit frontend never sees it. All Jellyfin operations proxy through sidecar endpoints that enforce the app's own session auth first.

---

## Anti-Patterns

### Anti-Pattern 1: Browser Talking Directly to Jellyfin

What people do: Expose Jellyfin's URL to the frontend, let the browser call `/Audio/{id}/stream` directly with an embedded token.

Why wrong: Jellyfin API key leaks into browser (History, DevTools, logs). The `api_key` query parameter is deprecated in Jellyfin. Cross-origin issues arise if Jellyfin is on a different domain.

Do instead: All audio goes through `/api/audio/{id}/stream` on the sidecar, which proxies with the header-based auth.

### Anti-Pattern 2: Session Cookies Scoped to a Root Domain

What people do: Set `cookie.domain=.zektek.us` so the session cookie reaches both `library.zektek.us` and (via a hypothetical `api.library.zektek.us`).

Why wrong: The cookie also reaches `jellyfin.zektek.us` and `slskd.zektek.us`, which is unnecessary exposure.

Do instead: Use the single-domain topology so the cookie is scoped to exactly `library.zektek.us`.

### Anti-Pattern 3: SvelteKit API Routes Duplicating Sidecar Endpoints

What people do: Add `src/routes/api/queue/+server.ts` that re-implements queue logic in SvelteKit.

Why wrong: Splits business logic across two services, makes the sidecar non-authoritative, breaks future CLI or Radio access to the same API.

Do instead: SvelteKit's `/api/*` routes are handled by Traefik routing to the sidecar — SvelteKit never owns `/api/*`. All mutations go to the sidecar.

### Anti-Pattern 4: `asyncio.create_task()` Without a Strong Reference

What people do: `asyncio.create_task(fetch_worker())` without storing the result.

Why wrong: The garbage collector can collect the task coroutine if no reference is held.

Do instead: Store in a module-level variable: `_worker_task = asyncio.create_task(fetch_worker())`.

---

## Scaling Considerations

This is an admin tool for a small team. The architecture targets 1–10 simultaneous users.

| Scale | Architecture Adjustment Needed |
|-------|-------------------------------|
| 1–10 users | Current design. In-process SSE, single asyncio worker, one sidecar replica |
| 10–100 users | No changes needed. SSE fan-out handles dozens of connections trivially |
| 100+ users | Extract worker to separate container. Add Redis for pub/sub. Run multiple sidecar replicas behind Traefik load balancer. Not expected for this project |

The only realistic bottleneck at small scale is concurrent librespot downloads (which are already serialized by design) and Jellyfin scan times (which are independent of user count).

---

## Integration Points

### Internal (Docker Compose Network)

| Boundary | Direction | Protocol | Notes |
|----------|-----------|----------|-------|
| SvelteKit → Sidecar | server-side only | HTTP (internal) | `http://sidecar:8000` — no TLS, fast |
| Sidecar → Jellyfin | server-side only | HTTP (internal) | `http://jellyfin:8096` — admin API key |
| Sidecar → Postgres | server-side only | TCP | `postgresql://...@postgres:5432/library` |
| Browser → SvelteKit | via Traefik | HTTPS | Renders pages, `/` prefix |
| Browser → Sidecar | via Traefik `/api/*` | HTTPS | SSE + mutations |

### External Services

| Service | Used By | Auth Method | Notes |
|---------|---------|-------------|-------|
| Spotify Web API | Sidecar | Client Credentials (search) | Unchanged from existing |
| Spotify Premium (librespot) | Sidecar | Stored credentials.json | Unchanged from existing |
| Jellyfin API | Sidecar | Admin API key (header) | New; key never leaves sidecar |

---

## Coolify Deployment Topology

```
Coolify project: "Apricot Suite"
  └── Resource: "Library" (Docker Compose, git repo)
        ├── Service: jellyfin     → jellyfin.zektek.us (existing)
        ├── Service: slskd        → slskd.zektek.us (existing)
        ├── Service: sidecar      → library.zektek.us/api/* (new domain, existing service)
        ├── Service: sveltekit    → library.zektek.us/* (new service)
        └── Service: postgres     → no public domain (internal only)
```

Postgres has no Traefik labels — it is never publicly exposed. The sidecar's existing domain `api.library.zektek.us` can be retired (or preserved in parallel during the transition) once the frontend is live and all clients use `library.zektek.us`.

**New environment variables to add in Coolify UI:**
- `DATABASE_URL` — `postgresql+asyncpg://library:password@postgres:5432/library`
- `SESSION_SECRET` — 64-byte random hex (for signing session tokens)
- `JELLYFIN_API_KEY` — Jellyfin admin API key (generated in Jellyfin admin UI)
- `JELLYFIN_INTERNAL_URL` — `http://jellyfin:8096`
- `SVELTEKIT_ORIGIN` — `https://library.zektek.us`

---

## Sources

- FastAPI background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/
- FastAPI lifespan + asyncio.Queue pattern: https://oneuptime.com/blog/post/2026-01-25-background-task-processing-fastapi/view
- FastAPI asyncio task reference pitfall: https://dev.to/kaushikcoderpy/python-background-tasks-asyncio-traps-fastapi-celery-2026-381i
- FastAPI ARQ vs BackgroundTasks: https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/
- SSE + connection management in FastAPI: https://medium.com/@nandagopal05/server-sent-events-with-python-fastapi-f1960e0c8e4b
- Postgres LISTEN/NOTIFY + SSE pattern: https://medium.com/@diwasb54/real-time-communication-with-postgresql-listen-notify-and-fastapi-0bfedf66be13
- SvelteKit auth/hooks documentation: https://svelte.dev/docs/kit/auth
- SvelteKit hooks middleware patterns: https://teta.so/blog/sveltekit-hooks-middleware-auth-guards
- SvelteKit server-to-server fetch: https://dev.to/jiprochazka/sending-sveltekit-server-requests-with-httponly-cookies-56p6
- Jellyfin API authorization: https://gist.github.com/nielsvanvelzen/ea047d9028f676185832e51ffaf12a6f
- Jellyfin API overview: https://jmshrv.com/posts/jellyfin-api/
- Coolify Traefik path routing: https://coolify.io/docs/knowledge-base/proxy/traefik/overview
- SvelteKit adapter-node: https://kit.svelte.dev/docs/adapter-node

---

*Architecture research for: Apricot Library — SvelteKit + Postgres + SSE milestone*
*Researched: 2026-05-29*
