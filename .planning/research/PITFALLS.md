# Pitfalls Research

**Domain:** Multi-user self-hosted music library — SvelteKit frontend + FastAPI sidecar + Postgres + Jellyfin + SSE queue sync
**Researched:** 2026-05-29
**Confidence:** HIGH (stack-specific, verified against official docs and known Jellyfin/librespot issues)

---

## Critical Pitfalls

### Pitfall 1: Session ID Not Regenerated After Login (Session Fixation)

**What goes wrong:**
The app issues a session cookie before login (e.g., on first page load) and keeps the same session ID after the user authenticates. An attacker who knows that pre-auth session ID can wait for the victim to log in and then use the same ID to hijack the authenticated session.

**Why it happens:**
Developers build login as "check credentials, set a flag on the existing session." They forget that the session ID must change at the authentication boundary. This is especially easy to miss when building app-native auth for the first time after previously delegating to a proxy (Authentik).

**How to avoid:**
In the FastAPI session handler: immediately after verifying password and writing the user row, call `DELETE FROM sessions WHERE id = $old_id` and issue a brand-new session ID cookie. Never reuse a pre-auth session token. Use `secrets.token_urlsafe(32)` for all session IDs. Set `HttpOnly=True`, `Secure=True`, `SameSite=Lax` on the cookie.

**Warning signs:**
- Login handler that reads `request.cookies.get("session")` and mutates rather than replaces it
- Session table rows with a `created_at` before `last_login`
- No explicit `DELETE` from sessions on login path

**Phase to address:** Auth foundation phase (first phase of the frontend milestone — before any other routes exist)

---

### Pitfall 2: Dropping Authentik Without Locking Down the Sidecar API

**What goes wrong:**
Authentik was the auth gate. The plan is to replace it with app-native auth. During the transition — or if app-native auth is incomplete — every sidecar endpoint (`/search`, `/download/{track_id}`, `/auth/librespot/credentials`) remains fully public on `api.library.zektek.us`. Anyone who discovers the URL can trigger unlimited Spotify downloads, overwrite librespot credentials, or exhaust disk.

**Why it happens:**
The natural build order is "add auth to the frontend first, then add auth middleware to the sidecar." But the sidecar is public the entire time, so the window of exposure exists throughout development.

**How to avoid:**
Add a `require_session` FastAPI dependency to every existing sidecar route on day one of the auth phase — before building any frontend UI. The middleware can be a simple Postgres session lookup. Protect at least `/download` and `/auth/librespot/credentials` immediately; `/search` can follow. Do not rely on Coolify network-level isolation as a substitute.

**Warning signs:**
- `curl https://api.library.zektek.us/download/4uLU6hMCjMI75M1MUPLFn9` returns 200 without a cookie
- No auth middleware in `sidecar/app/main.py` dependency injection
- CONCERNS.md already flagged this — it is an active known vulnerability

**Phase to address:** Auth foundation phase — first commit before any UI work

---

### Pitfall 3: SSE Connections Not Cleaned Up on Client Disconnect

**What goes wrong:**
Each SSE connection is an open generator in the FastAPI process. When a browser tab closes or navigates away, the client drops the TCP connection, but the server generator keeps running — holding memory and a Postgres connection — until the worker process recycles or the next event tries to write to the dead socket and raises.

**Why it happens:**
FastAPI's `StreamingResponse` with an async generator looks clean on paper. The generator is only interrupted when the client disconnects and the framework's response writer raises `anyio.EndOfStream` or similar. If the generator never awaits anything after the disconnect, the coroutine hangs indefinitely. With heartbeats and no timeout, coroutines pile up across browser refreshes.

**How to avoid:**
Use `request.is_disconnected()` as the exit condition on every SSE loop iteration:

```python
async def event_generator(request: Request):
    while True:
        if await request.is_disconnected():
            break
        yield format_sse(get_queue_snapshot())
        await asyncio.sleep(15)  # heartbeat interval
```

Maintain a connection registry (asyncio `Event` or a set of queues per connected client) so that new queue events can push to all live connections rather than polling on a timer. Track open connection count in a Prometheus gauge or simple log line so leaks are visible.

**Warning signs:**
- FastAPI worker RSS grows over the course of a day without restarts
- `ps aux` shows async tasks accumulating in the sidecar container
- No `request.is_disconnected()` check in the SSE endpoint

**Phase to address:** SSE / real-time queue phase

---

### Pitfall 4: Reverse-Proxy Buffering Silently Eating SSE Events

**What goes wrong:**
Coolify uses Traefik as its reverse proxy. Traefik (like nginx) will buffer upstream responses by default. An SSE stream appears to work in local development (direct FastAPI), then appears broken in production — events are batched and delivered in bursts after 60-second proxy timeouts, or the connection drops silently.

**Why it happens:**
Developers test SSE locally without a proxy. The buffering behaviour only appears behind Traefik/nginx. The 60-second default `respondingTimeouts.writeTimeout` in Traefik will also kill idle SSE connections that have no recent events.

**How to avoid:**
In the FastAPI SSE endpoint, set response headers that tell Traefik to disable buffering:

```python
headers = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",   # Traefik respects this header
    "Connection": "keep-alive",
}
```

In Coolify's Traefik configuration, extend the write/idle timeouts via `--entrypoints.https.transport.respondingTimeouts.writeTimeout=0` (unlimited) for the SSE service label. Send a heartbeat comment (`": heartbeat\n\n"`) every 25 seconds so the proxy sees activity.

**Warning signs:**
- SSE works on `localhost` but events arrive in delayed batches in production
- Browser DevTools shows the EventSource connection closing after exactly 60 seconds
- No `X-Accel-Buffering: no` header in the SSE response

**Phase to address:** SSE / real-time queue phase — must be verified in the Coolify deployment environment, not just locally

---

### Pitfall 5: EventSource Cannot Send Auth Headers — Cookie Scope Mismatch Breaks It

**What goes wrong:**
`EventSource` is a browser API that does not support custom headers. Authentication for the SSE endpoint must use cookies, not `Authorization: Bearer`. If the session cookie is scoped to `library.zektek.us` but the SSE endpoint is at `api.library.zektek.us`, the browser will not send the cookie with the EventSource request — the connection succeeds as an anonymous request (or fails with 401 in a loop).

**Why it happens:**
SvelteKit SSR and client-side fetch can forward auth tokens as headers. Developers assume the same approach works for `EventSource`. It does not. Additionally, the FastAPI CORS middleware must allow credentials and explicitly whitelist the SvelteKit origin — using `*` for `allow_origins` with `allow_credentials=True` is rejected by browsers.

**How to avoid:**
Set the session cookie with `Domain=.zektek.us` (root domain with leading dot) so it is sent to both `library.zektek.us` and `api.library.zektek.us`. Configure FastAPI CORS middleware with `allow_origins=["https://library.zektek.us"]` and `allow_credentials=True`. In SvelteKit SSR load functions that call `api.library.zektek.us`, manually forward the `Cookie` header from the incoming request, since SvelteKit does not automatically share cookies across different origins even on the same root domain.

**Warning signs:**
- SSE endpoint receives no session cookie in production but does in localhost
- `EventSource` connection returns 401 silently (EventSource does not expose HTTP status to JS)
- FastAPI CORS middleware configured with `allow_origins=["*"]`

**Phase to address:** Auth foundation phase — cookie domain must be settled before SSE is built

---

### Pitfall 6: Queue "Claim Next Job" Race Condition

**What goes wrong:**
Two concurrent requests both read the queue and see the same `pending` job. Both mark it `in_progress`. The same track is downloaded twice, the second write either overwrites the first or collides at the filesystem path. The queue "worker" claim is not atomic.

**Why it happens:**
The natural implementation is `SELECT * FROM queue WHERE status='pending' ORDER BY created_at LIMIT 1` followed by `UPDATE queue SET status='in_progress'`. Between the SELECT and UPDATE, another coroutine (or a future second worker) claims the same row.

**How to avoid:**
Use `SELECT ... FOR UPDATE SKIP LOCKED` in a single transaction:

```sql
BEGIN;
SELECT id FROM queue
  WHERE status = 'pending'
  ORDER BY created_at
  LIMIT 1
  FOR UPDATE SKIP LOCKED;
UPDATE queue SET status = 'in_progress', started_at = now() WHERE id = $1;
COMMIT;
```

This is a Postgres primitive; `SKIP LOCKED` means "if the row is locked by another transaction, skip it." Combined with a single-worker architecture (one asyncio background task), race conditions are eliminated. Do not run multiple worker coroutines without this pattern.

**Warning signs:**
- Duplicate filenames appearing in the Jellyfin media volume
- Queue rows stuck in `in_progress` with no active download
- No `FOR UPDATE` in the queue claim query

**Phase to address:** Queue implementation phase

---

### Pitfall 7: Worker Crashes Mid-Download, Queue Stuck Forever

**What goes wrong:**
The download worker marks a job `in_progress`, calls librespot, and then the sidecar process restarts (OOM kill, deploy, crash). The row stays `in_progress` forever. The queue appears to have an active job but nothing is running. New jobs queue up behind it but never execute.

**Why it happens:**
There is no timeout on `in_progress` rows and no crash-recovery logic. A deploy of the sidecar container is sufficient to trigger this — the worker task is killed mid-download.

**How to avoid:**
Add a `heartbeat_at` column to the queue table. The worker updates it every 10 seconds while a download is running. A watchdog query (run at sidecar startup and periodically) resets any row where `status = 'in_progress' AND heartbeat_at < now() - interval '60 seconds'` back to `pending`. Implement a maximum retry count (`attempts` column, cap at 3) so a consistently-failing job does not loop forever.

**Warning signs:**
- Queue shows `in_progress` but no download is active (no librespot process, no log activity)
- Sidecar was restarted recently and queue never resumed
- No `started_at` or `heartbeat_at` column in the queue schema

**Phase to address:** Queue implementation phase — design the schema with heartbeat from day one

---

### Pitfall 8: Partial Audio File Appearing in Jellyfin Library

**What goes wrong:**
librespot writes a `.ogg` file to the shared media volume. Jellyfin's `FileSystemWatcher` detects the new file (with a ~45 second debounce) and begins scanning it. If the download is slow or is interrupted, Jellyfin ingests a partial/corrupt file. Jellyfin may show the track as playable when it is not, and may cache bad metadata that persists across subsequent correct downloads.

**Why it happens:**
The existing download code writes directly to the final path. There is no temp-file-then-rename pattern. Jellyfin's debounce reduces but does not eliminate the race.

**How to avoid:**
Write to a temp file in the same directory (e.g., `Artist/Album/.tmp_trackid.ogg`), then `os.rename()` (atomic on Linux, same filesystem) to the final path only on successful download. Jellyfin will only see the file after the rename. If the download fails, delete the temp file. The sidecar's startup watchdog should also delete any orphaned `.tmp_*` files in the media volume.

**Warning signs:**
- Jellyfin shows tracks with 0:00 duration
- Partial `.ogg` files exist without corresponding completed entries in the queue history table
- No temp-file pattern in `librespot_session.py`

**Phase to address:** Queue implementation phase — this is part of the download transaction pattern

---

### Pitfall 9: Jellyfin Metadata Scan Overwrites App-Edited Tags

**What goes wrong:**
A user edits a song's title/artist/album through the Library UI. The app writes the change to Postgres and calls the Jellyfin API to update the item. A Jellyfin scheduled library scan then re-reads the audio file tags and overwrites the Jellyfin item with whatever is in the embedded ID3/OGG tags — discarding the edit.

**Why it happens:**
Jellyfin's metadata provider order and lock behavior are complex. By default, embedded tags take priority over manually-edited metadata in music libraries. Without locking the item via the Jellyfin API, any rescan resets it. This is a confirmed known issue in Jellyfin 10.9+ where metadata locks are not always respected.

**How to avoid:**
After a metadata edit, use the Jellyfin API to both update the item (`POST /Items/{itemId}`) and lock the metadata fields (`LockData: true`, with the specific field providers locked). Also write the edited tags back into the audio file itself (using `mutagen` in the sidecar) so that even if Jellyfin rescans from the file, the tags match. Document clearly which is the source of truth: Postgres stores the user-intent, Jellyfin stores the rendered catalog, audio file tags are the durable fallback.

**Warning signs:**
- Song title reverts to original after a Jellyfin library scan
- Jellyfin API response shows `LockData: false` on edited items
- No `mutagen` or equivalent in sidecar dependencies

**Phase to address:** Song metadata editing phase

---

### Pitfall 10: librespot credentials.json World-Readable in Container

**What goes wrong:**
The sidecar writes `credentials.json` with default file permissions (644 — world-readable in the container). The sidecar currently runs as root in the container (no `user:` directive in Compose). If the container is compromised or if any other process in the container reads the file, the librespot auth token is exposed.

**Why it happens:**
Python's `Path.write_text()` does not set restrictive permissions. The CONCERNS.md audit already identified this. It is compounded by the sidecar running as root.

**How to avoid:**
After every write: `path.chmod(0o600)`. Add `user: "${PUID:-1000}:${PGID:-1000}"` to the sidecar service in `docker-compose.yaml` (matching Jellyfin and slskd). Additionally, use a Docker secret or a volume-mounted secret rather than the sidecar's application directory for the credentials file.

In a multi-user context, the librespot credentials are shared infrastructure (one Spotify Premium account for all downloads). They must not be exposable via any user-facing API endpoint. The upload endpoint (`POST /auth/librespot/credentials`) must require admin-level session authentication.

**Warning signs:**
- `ls -la` in the sidecar container shows `credentials.json` as `-rw-r--r--`
- `docker compose config` shows no `user:` on the sidecar service
- The credentials upload endpoint has no auth check (confirmed in CONCERNS.md)

**Phase to address:** Auth foundation phase — fix permissions and add auth before any frontend ships

---

### Pitfall 11: Spotify Client Secret Logged via httpx Debug

**What goes wrong:**
The sidecar passes `auth=(spotify_client_id, spotify_client_secret)` to httpx. If httpx debug logging is enabled (or if a logging framework captures request details), the Base64-encoded Basic Auth header appears in logs. The secret is recoverable by decoding it.

**Why it happens:**
Standard httpx logging and many structured logging integrations log full request headers. Developers enable debug logging to diagnose Spotify API issues and forget it logs credentials.

**How to avoid:**
Add an httpx event hook that redacts the `Authorization` header before logging:

```python
def redact_auth(request):
    request.headers["Authorization"] = "Basic [REDACTED]"

client = httpx.AsyncClient(event_hooks={"request": [redact_auth]})
```

Never set log level to DEBUG in the sidecar container in production. Store `SPOTIFY_CLIENT_SECRET` only in `.env` (already done); verify `.env` is in `.gitignore`.

**Warning signs:**
- `Authorization: Basic` visible in sidecar container logs
- Log level set to DEBUG in production `docker-compose.yaml`
- No `event_hooks` on the httpx client

**Phase to address:** Auth foundation phase — fix before deploying app-native auth (which adds more secrets to the mix)

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Storing session tokens in Postgres without expiry cleanup | Simpler to implement | Sessions table grows unbounded; stale rows slow lookups | Never — add a cleanup job or `TTL` at schema design time |
| Polling Jellyfin from SvelteKit home page on every load | No SSE complexity for catalog | Slow home page when Jellyfin is under load; blocks render | Never for the home page — cache in FastAPI with a short TTL |
| Single hardcoded admin account in `.env` | No user management to build | Cannot expand to multi-user without a rewrite | Only for a prototype, never for the shipped milestone |
| Skipping heartbeat on SSE | One less thing to implement | Proxy drops connections after 60s of silence; Traefik default | Never — add heartbeat on day one |
| Writing final audio file path directly (no temp rename) | Simpler download code | Partial files appear in Jellyfin; hard to clean up | Never — temp rename costs three lines of code |
| Using the Jellyfin admin API key for all catalog reads | No per-user auth complexity with Jellyfin | One leaked key = full Jellyfin admin access; key rotation breaks everything | Acceptable only if the key never leaves the sidecar backend |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Jellyfin REST API | Using the Jellyfin admin token in SvelteKit client-side code | Proxy all Jellyfin calls through the FastAPI sidecar; the Jellyfin API key must never leave the server |
| Jellyfin metadata | Assuming `POST /Items/{id}` persists through rescans | Also set `LockData: true` on the item and write tags back to the audio file via `mutagen` |
| Jellyfin library scan | Triggering a scan after download and assuming the new file appears immediately | Jellyfin debounces FSWatcher events ~45 seconds; the track may not appear for up to a minute after the download completes |
| librespot Rust binary | Assuming the Python librespot wrapper is stable | The Python wrapper (`librespot==0.0.10`) is pre-1.0 and Spotify has deprecated username/password auth; the Rust binary via subprocess is the validated path per project memory |
| Spotify Web API search | Passing the user's raw search string directly as a URL parameter | Validate/sanitize the query; the endpoint makes an outbound HTTP request — SSRF is not relevant here (Spotify is a fixed external host) but log injection via malformed queries is |
| EventSource (browser) | Passing `Authorization: Bearer` header to EventSource | EventSource sends no custom headers; rely exclusively on the session cookie for SSE authentication |
| Traefik (Coolify) | Testing SSE locally and assuming it works in production | Always test SSE through the Coolify deployment; Traefik buffering is invisible locally |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Fetching the full Jellyfin catalog on every home page load | Home page takes 2-5 seconds when the library is large | Cache the catalog response in FastAPI (in-memory or Postgres) with a 30-60 second TTL; invalidate on download completion | At ~200 tracks, noticeable; at 1000+ tracks, Jellyfin API response time degrades |
| N+1 Jellyfin API calls for cover art per song row | Home page makes one HTTP call per song to get cover art URL | Use Jellyfin's `Fields=PrimaryImageAspectRatio` in the bulk items endpoint to get image tags in one call; construct image URLs from the tag rather than fetching each | At 50+ songs per page |
| SSE broadcasting by polling Postgres on a timer per connection | DB query load scales linearly with connected users | Use a shared in-memory event bus (asyncio `Queue` per connection, fed by a single broadcaster task) | At 5+ simultaneous users |
| Argon2 with default memory parameter on a constrained container | Login takes 3-5 seconds or triggers OOM | Tune Argon2id: 19MB memory, 2 iterations, 1 thread (OWASP low-memory profile); benchmark on actual container; target 200-500ms | Immediately if container is limited to 256MB RAM and defaults are used |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `/download/{track_id}` accepts any string without format validation | Track ID used to construct a filesystem path; path traversal to read arbitrary files | Enforce `VALID_TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")`  (already exists) AND verify the resolved output path is within `settings.media_path` using `Path.resolve()` |
| Jellyfin API key in SvelteKit client bundle | Any user can extract the key and make admin Jellyfin calls directly | All Jellyfin calls must go through the FastAPI sidecar; never pass the Jellyfin API key to the frontend |
| Admin-only endpoints (user management, credentials upload) checked only by convention | A bug skips the admin check; any authenticated user becomes an admin | Use a FastAPI `Depends(require_admin)` dependency on every admin route; write an integration test that verifies a non-admin session gets 403 |
| Postgres exposed on a public port in Compose | Direct database access from outside the Docker network | Never bind Postgres to `0.0.0.0`; use Docker network isolation; verify `docker compose port` does not expose 5432 externally |
| `.env` file committed to git | Spotify credentials, DB password, session secret in the repository | Add `.env` to `.gitignore` now; run `git log --all --full-history -- .env` to verify it was never committed; add a pre-commit hook |
| Storing per-user "favourite" or playlist data without ownership check | User A can delete or edit User B's playlists | Every write query on user-owned data must include `AND user_id = $current_user_id`; never trust a `playlist_id` from the request body without verifying ownership |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No feedback between "Add to Queue" click and SSE confirmation | User clicks multiple times, adding the same track twice | Optimistically disable the button immediately on click; mark the track as "queued" in local state; confirm via SSE event |
| Queue shows "downloading…" after sidecar restart with no active worker | User thinks download is in progress; it is stuck | Queue UI must distinguish `in_progress` with a recent `heartbeat_at` vs. `in_progress` with a stale heartbeat; show "stalled" state and offer a retry action |
| Jellyfin scan delay means track doesn't appear immediately after download | User thinks download failed | Show a "Track added — may take up to a minute to appear in library" notice when a download completes; alternatively trigger a Jellyfin scan via the API after download |
| Login page redirects to home after auth but session cookie not yet propagated on SSR | Page flashes "not logged in" on first render | Use SvelteKit's `hooks.server.ts` to validate the session on every request; set the cookie before the redirect, not after |

---

## "Looks Done But Isn't" Checklist

- [ ] **Auth:** Session ID is regenerated on login — verify with `SELECT id FROM sessions` before and after login; they must differ
- [ ] **Auth:** Admin-only routes return 403 for a valid non-admin session — write a test with two session tokens
- [ ] **Auth:** Session cookie has `HttpOnly`, `Secure`, `SameSite=Lax` — inspect in DevTools Application > Cookies
- [ ] **SSE:** Events arrive in production through Coolify/Traefik — test with `curl -N --cookie "session=..." https://api.library.zektek.us/events`
- [ ] **SSE:** Connection count does not grow over time — watch worker RSS across 10 browser tab opens/closes
- [ ] **Queue:** `in_progress` row with no active worker is cleaned up within 60 seconds of sidecar restart — simulate by killing the sidecar mid-download
- [ ] **Download:** Partial files never appear in Jellyfin — kill the sidecar during an active download; verify no `.ogg` appears in the Jellyfin UI
- [ ] **Metadata edit:** Title change persists through a Jellyfin forced library scan — edit a track title, trigger `POST /Library/Refresh`, check the title 2 minutes later
- [ ] **Permissions:** `credentials.json` in the container is mode 600 — `docker exec <sidecar> ls -la /path/to/credentials.json`
- [ ] **Postgres:** Port 5432 is not externally exposed — `docker compose ps` and `nmap` the host

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Session fixation exploited (session hijacked) | MEDIUM | Rotate the session secret (invalidates all sessions), force re-login for all users, audit session table for anomalous IP switches |
| Queue stuck in `in_progress` forever | LOW | SQL: `UPDATE queue SET status='pending', attempts=attempts+1 WHERE status='in_progress' AND heartbeat_at < now() - interval '5 minutes'`; restart worker |
| Partial audio file ingested by Jellyfin | LOW | Delete the partial file from the media volume, re-queue the track, trigger a Jellyfin refresh for the album |
| Jellyfin metadata overwritten by rescan | MEDIUM | Re-apply edits from the Postgres `metadata_edits` table; write tags back to audio file with `mutagen`; lock the item in Jellyfin |
| librespot credentials overwritten by malicious upload | HIGH | Restore from the previous credentials backup; revoke the Spotify session from Spotify account settings; rotate all API keys |
| Spotify client secret exposed via logs | HIGH | Rotate the Spotify app secret immediately in the Spotify Developer Dashboard; update `.env` and redeploy; audit log archives for the window of exposure |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Session fixation | Auth foundation | Automated test: login twice, confirm different session IDs |
| Sidecar endpoints unprotected after dropping Authentik | Auth foundation (first task) | `curl` without cookie returns 401 on all protected routes |
| SSE connection leak | SSE / real-time queue | Monitor worker RSS over 1 hour of tab cycling |
| Traefik SSE buffering | SSE / real-time queue (deployed test) | Confirm events arrive within 1 second via Coolify URL |
| EventSource cookie scope mismatch | Auth foundation (cookie domain) | EventSource connects and receives events in production browser |
| Queue claim race condition | Queue implementation | `FOR UPDATE SKIP LOCKED` in claim query; load test with 2 concurrent requests |
| Worker crash leaves queue stuck | Queue implementation | Schema includes `heartbeat_at`; startup watchdog cleans stale jobs |
| Partial file in Jellyfin | Queue / download | Kill-during-download test; no partial file visible in Jellyfin |
| Jellyfin scan overwrites metadata edits | Metadata editing phase | Edit title, force scan, confirm title persists |
| credentials.json world-readable | Auth foundation | `ls -la` in container shows 600 |
| Spotify secret in httpx logs | Auth foundation | Log output contains `[REDACTED]` not the actual header value |

---

## Sources

- OWASP Session Management Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- CWE-384 Session Fixation / OWASP A07:2025: https://www.descope.com/learn/post/session-fixation
- Jellyfin metadata lock issues (GitHub #11656): https://github.com/jellyfin/jellyfin/issues/11656
- Jellyfin metadata overwrite forum thread: https://forum.jellyfin.org/t-jellyfin-overwriting-metadata
- Jellyfin temp file race condition fix (PR #12386): https://github.com/jellyfin/jellyfin/pull/12386
- Jellyfin audio scan regression 10.10.7 (Issue #13979): https://github.com/jellyfin/jellyfin/issues/13979
- PostgreSQL SKIP LOCKED for queues: https://parottasalna.com/2025/01/11/learning-notes-51-postgres-as-a-queue-using-skip-locked/
- Postgres as a job queue pitfalls: https://richyen.com/postgres/2026/05/04/postgres_job_queue.html
- SSE browser 6-connection limit (MDN): https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- SSE Nginx/Traefik buffering: https://oneuptime.com/blog/post/2025-12-16-server-sent-events-nginx/view
- Coolify gateway timeout configuration: https://coolify.io/docs/troubleshoot/applications/gateway-timeout
- librespot credentials.json world-readable issue: https://github.com/librespot-org/librespot/issues/360
- SvelteKit cross-subdomain cookie SSR issue: https://github.com/sveltejs/kit/issues/4750
- SvelteKit CSRF protection (CVE-2023-29008): https://github.com/advisories/GHSA-gv7g-x59x-wf8f
- OWASP Argon2id recommended parameters: https://guptadeepak.com/the-complete-guide-to-password-hashing-argon2-vs-bcrypt-vs-scrypt-vs-pbkdf2-2026/
- FastAPI SSE with request.is_disconnected(): https://fastapi.tiangolo.com/tutorial/server-sent-events/
- Path traversal in download APIs: https://www.apisec.ai/blog/path-traversal-in-apis-detection-and-prevention
- .planning/codebase/CONCERNS.md — existing security audit (2026-05-29)

---
*Pitfalls research for: SvelteKit + FastAPI + Postgres + Jellyfin multi-user music library with SSE queue*
*Researched: 2026-05-29*
