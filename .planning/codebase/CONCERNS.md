# Codebase Concerns

**Analysis Date:** 2026-05-29

## Security

### No Authentication on Sidecar API Endpoints

**Risk:** All sidecar endpoints (`/search`, `/download`, `/auth/*`) are publicly exposed with no authentication gate.

**Files:** 
- `sidecar/app/main.py` (lines 29-56: endpoints)
- `sidecar/app/auth.py` (lines 48-176: auth routers)

**Current mitigation:** README mentions "Authentik is wired in via forward-auth at the proxy layer" but also states "Authentik was planned but is now being dropped per project direction." No auth is currently enforced in the application code.

**Impact:** 
- `/search` leaks Spotify metadata without authentication
- `/download/{track_id}` can trigger unlimited audio downloads (resource exhaustion)
- `/auth/librespot/credentials` accepts unauthenticated credential uploads
- `/auth/spotify/login` and `/callback` have no CSRF protection beyond a simple in-memory state store

**Recommendations:**
1. Add authentication requirement at application level (don't rely on proxy-level only)
2. Implement CSRF token validation for OAuth flows
3. Rate limit `/search` and `/download` endpoints
4. Add request origin validation for credential endpoints
5. Consider implementing API key or Bearer token requirement

### Credentials.json Upload Without Validation

**Risk:** `POST /auth/librespot/credentials` accepts raw JSON from request body with minimal validation.

**Files:** `sidecar/app/auth.py` (lines 134-141)

**Current validation:**
```python
if not isinstance(content, dict) or "username" not in content:
    raise HTTPException(400, "Invalid credentials shape — missing 'username'")
if "credentials" not in content and "auth_data" not in content:
    raise HTTPException(...)
```

**Problems:**
1. No size limit on upload (could exhaust disk)
2. No validation of credential format or authenticity
3. No logging of credential changes
4. No backup mechanism before overwrite

**Recommendations:**
1. Add max size validation (e.g., 100KB)
2. Validate that credentials.json actually parses as valid librespot format
3. Log all credential updates with timestamp
4. Keep a backup of previous credentials
5. Require authentication for this endpoint

### State Token Memory Leak

**Risk:** OAuth state tokens stored in in-memory dictionary without cleanup guarantee.

**Files:** `sidecar/app/auth.py` (lines 21, 41-45, 53-55, 79)

**Pattern:**
```python
_pending_states: dict[str, float] = {}

def _prune_states() -> None:
    now = time.time()
    expired = [s for s, exp in _pending_states.items() if exp < now]
    for s in expired:
        _pending_states.pop(s, None)

@router.get("/login")
async def login() -> RedirectResponse:
    _prune_states()  # Only called on login, not on callback
```

**Problems:**
1. `_prune_states()` only called on `/login`, not on `/callback`
2. Tokens with valid state expire after 600s, but dictionary is never cleaned if `/callback` fails
3. Long-running process could accumulate thousands of tokens
4. No limit on dictionary size

**Recommendations:**
1. Call `_prune_states()` on `/callback` as well
2. Add a maximum dictionary size check
3. Consider using Redis or session store instead of in-memory dict
4. Log state pruning events

### Spotify Client Credentials Passed as Plain Text in Code

**Risk:** `spotify_client_id` and `spotify_client_secret` are passed directly in HTTP Basic Auth.

**Files:**
- `sidecar/app/spotify.py` (line 32: Client Credentials flow)
- `sidecar/app/auth.py` (lines 91, 161: Authorization Code flow)

**Current handling:**
```python
auth=(settings.spotify_client_id, settings.spotify_client_secret)
```

**Problems:**
1. Credentials appear in HTTP Basic Auth header (base64-encoded, not encrypted)
2. If HTTP client logs requests, credentials could be logged
3. Connection is HTTPS but no certificate pinning

**Recommendations:**
1. Add httpx event hooks to redact credentials from any logging
2. Consider certificate pinning for Spotify API endpoints
3. Document that credentials should be treated as secrets
4. Monitor for accidental credential logging in logs

## Credentials and Secrets Handling

### Token Files Written with Default Permissions

**Risk:** Token files written with potentially world-readable permissions.

**Files:**
- `sidecar/app/auth.py` (lines 28-31: `_save_tokens`)
- `sidecar/app/librespot_session.py` (lines 37-39: `save_credentials`)

**Pattern:**
```python
def _save_tokens(data: dict) -> None:
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))  # No mode specified
```

**Problems:**
1. Default umask may create files readable by other users in container
2. No explicit `chmod 0o600` to restrict to owner only
3. Docker container runs as `PUID:PGID`, but no verification these are appropriate

**Impact:** Other processes in container or host could read Spotify tokens and librespot credentials.

**Recommendations:**
1. Explicitly set file permissions after write:
   ```python
   path.write_text(...)
   path.chmod(0o600)
   ```
2. Add verification in tests that files are created with restrictive permissions
3. Document security implications in README

## Error Handling

### Generic Exception Catch in Credentials Endpoint

**Risk:** Broad exception handling masks potential issues.

**Files:** `sidecar/app/auth.py` (lines 135-140)

**Code:**
```python
try:
    body = await request.json()
except Exception as e:
    raise HTTPException(400, f"Body must be JSON: {e}")
```

**Problems:**
1. Catches all exceptions (including system errors, not just JSON parse)
2. Exposes exception details in HTTP response (information disclosure)
3. No logging of which exception type occurred

**Recommendations:**
1. Catch specific exceptions: `except (json.JSONDecodeError, ValueError) as e:`
2. Log the exception internally but return generic message to client
3. Return different HTTP status for actual errors (500) vs bad request (400)

### Incomplete Error Handling in Download Flow

**Risk:** Download endpoint doesn't handle all failure modes.

**Files:** `sidecar/app/main.py` (lines 38-56)

**Problems:**
1. If `spotify.get_track()` returns metadata but download fails, endpoint returns 200 with partial response
2. No validation that output directory is writable before calling download
3. No cleanup if download partially succeeds then fails
4. `librespot_session.download_track()` called via `to_thread()` but exceptions may not surface to HTTP response

**Recommendations:**
1. Add pre-flight validation: check directory writable, available disk space
2. Implement transaction-like behavior: write to temp file, move to final location on success
3. Verify exceptions from threaded downloads bubble up correctly
4. Return appropriate HTTP error codes for different failure modes

### Librespot Session Connection Retries Without Circuit Breaker

**Risk:** Aggressive retry loop with exponential backoff but no circuit breaker.

**Files:** `sidecar/app/librespot_session.py` (lines 49-80)

**Pattern:**
```python
for attempt in range(1, 6):
    try:
        _session = Session.Builder().stored_file(...).create()
        return _session
    except (ConnectionRefusedError, ConnectionError, OSError) as e:
        time.sleep(0.5 * attempt)
```

**Problems:**
1. 5 attempts with max 2.5s sleep means endpoint blocks for ~5 seconds on connection failure
2. No circuit breaker: repeated downloads will hammer Spotify AP even if network is down
3. Only retries on connection errors, not on auth/invalid credential errors

**Recommendations:**
1. Add circuit breaker pattern or fallback after N consecutive failures
2. Set timeout on Session.create() to avoid indefinite hangs
3. Distinguish between retriable (connection) and non-retriable (auth) errors
4. Log retry attempts with backoff values

## Missing Tests and Coverage

### No Test Suite

**Risk:** Entire sidecar codebase has zero test coverage.

**Files:** No tests found in `sidecar/` directory

**Untested areas:**
- OAuth token refresh logic (`sidecar/app/auth.py`: lines 144-175)
- Credentials validation and save (`sidecar/app/librespot_session.py`: lines 28-40)
- Track download and file write (`sidecar/app/librespot_session.py`: lines 83-104)
- Spotify API search and metadata (`sidecar/app/spotify.py`: lines 40-60)
- State token pruning (`sidecar/app/auth.py`: lines 41-45)

**Impact:**
- OAuth refresh token expiry edge cases not caught
- Credentials upload can silently fail or corrupt file
- Download path traversal vulnerabilities not caught
- Spotify API error responses not handled consistently

**Recommendations:**
1. Add unit tests for token refresh expiry calculation
2. Add integration tests for OAuth callback flow (with mock Spotify API)
3. Add tests for credentials save/load roundtrip
4. Test download file path safety (no traversal)
5. Mock librespot Session to test error handling
6. Target 80%+ coverage for `sidecar/app/`

## File Permission and PUID/PGID Issues

### PUID/PGID Not Enforced for Sidecar

**Risk:** Docker Compose specifies `PUID:PGID` for `jellyfin` and `slskd` but not for `sidecar`.

**Files:** `docker-compose.yaml` (lines 6, 26 have user directive; line 49+ sidecar does not)

**Current state:**
```yaml
jellyfin:
  user: "${PUID:-1000}:${PGID:-1000}"  # ✓ has PUID:PGID

sidecar:
  # No user directive — runs as root or default Python user in container
```

**Problems:**
1. Sidecar container may run as root
2. Credentials and token files written by root-owned process
3. If compromised, attacker has root access in sidecar container
4. Jellyfin/slskd can't read files written by root-owned sidecar

**Impact:** 
- Cross-container file access issues (shared media volume)
- Security: sidecar compromise = full container root access
- Download files may have wrong ownership

**Recommendations:**
1. Add `user: "${PUID:-1000}:${PGID:-1000}"` to sidecar service in docker-compose.yaml
2. Verify output files can be read by other containers
3. Document PUID/PGID setup in README

## Dependency Risks

### Librespot Python Package Maintenance

**Risk:** `librespot==0.0.10` is a Python wrapper around Spotify's protocol, maintenance status unclear.

**Files:** `sidecar/requirements.txt` (line 5)

**Concerns:**
1. Version 0.0.10 is pre-1.0, indicates alpha/unstable status
2. No pin suffix (e.g., `~=0.0.10`), so patch updates could introduce breaking changes
3. Relies on Spotify's private protocol — Spotify could change it anytime
4. Project memory notes "librespot-python OAuth is dead end" — unclear if this is the actual issue fixed

**Recommendations:**
1. Research current librespot-python maintenance status
2. Add version constraint comment explaining why 0.0.10 is pinned
3. Document fallback plan if librespot breaks (e.g., switch to Rust binary via subprocess)
4. Monitor GitHub repo for breaking changes

### No Dependency Lock File in VCS

**Risk:** No `poetry.lock`, `pip.lock`, or `requirements.lock` committed to git.

**Files:** `sidecar/requirements.txt` lists specific versions but no lock file

**Problems:**
1. Transitive dependencies can change without notice
2. Dockerfile always does `pip install -r requirements.txt`, so minor version bumps can sneak in
3. Reproducing exact build in 6 months may fail

**Recommendations:**
1. Generate lock file: `pip freeze > sidecar/requirements.lock`
2. Commit lock file to git
3. Update CI to install from lock file
4. Document lock file update procedure

## Fragile Areas

### Hardcoded Paths and Assumptions

**Risk:** Download path construction assumes flat artist/album structure.

**Files:** `sidecar/app/main.py` (lines 44-47)

**Pattern:**
```python
artist = _safe(meta["artists"][0] if meta["artists"] else "Unknown")
album = _safe(meta["album"] or "Unknown")
output_path = Path(settings.media_path) / artist / album / f"{name}.ogg"
```

**Problems:**
1. Takes only first artist (fails for collaborations)
2. No duplicate detection (multiple tracks with same name overwrite)
3. No normalization of artist/album names (e.g., "The Beatles" vs "Beatles, The")
4. Path sanitization is basic: `_SAFE_NAME.sub("_", name)` may create collisions

**Recommendations:**
1. Use Spotify track ID in filename as secondary key to prevent collisions
2. Consider using MusicBrainz MBID for canonical artist/album names
3. Document path structure expectations in README
4. Add test fixtures for problematic metadata (special chars, missing fields)

### State Machine Implicit Behavior

**Risk:** Multiple ways to be "connected" but not all checked in download flow.

**Files:**
- `/auth/spotify/status` checks token file
- `/download` uses `get_user_access_token()` which checks token and refreshes
- `/search` uses separate Client Credentials token

**Problems:**
1. No central "readiness" check before download
2. If Spotify user tokens expire and refresh fails, `/status` might show `connected: true` but download fails
3. librespot credentials and Spotify Web API tokens are independent; one can be invalid while other is valid

**Recommendations:**
1. Add comprehensive `/status` endpoint that checks all prerequisites:
   - Spotify Client Credentials valid
   - Spotify user token valid (or can refresh)
   - librespot credentials present
2. Return detailed status object with per-component health
3. Document state machine in README

### Regex for Track ID Validation

**Risk:** Track ID validation regex assumes Spotify format but format could change.

**Files:** `sidecar/app/librespot_session.py` (line 17)

**Pattern:**
```python
VALID_TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")
```

**Problems:**
1. If Spotify changes track ID format, silently fails
2. Hard-coded length assumption
3. No documentation of where this format comes from

**Recommendations:**
1. Add comment explaining track ID format source
2. Consider fetching format rules from Spotify API
3. Add test case documenting expected formats
4. Plan for format migration path

## Deployment and Scaling

### Relative Path Defaults Will Lose Data on Redeploy

**Risk:** While README warns about this for Coolify, the defaults in docker-compose.yaml still use relative paths.

**Files:** `docker-compose.yaml` (lines 13, 39, 63)

**Pattern:**
```yaml
- ${MEDIA_PATH:-./media}:/media  # Default is relative!
- ${DOWNLOADS_PATH:-./downloads}:/downloads
```

**Problems:**
1. Developer who doesn't read README and skips `.env` setup will lose data
2. Running `docker compose up` in different directories will use different volumes

**Recommendations:**
1. Add explicit error if MEDIA_PATH/DOWNLOADS_PATH use relative paths
2. Update compose file to fail-fast on relative path
3. Add validation in sidecar startup to warn about relative mount paths

### Spotify Redirect URI Hardcoded in Code

**Risk:** `SPOTIFY_REDIRECT_URI` hardcoded as default in `sidecar/app/config.py`.

**Files:** `sidecar/app/config.py` (line 9)

**Default:**
```python
spotify_redirect_uri: str = "https://api.library.zektek.us/auth/spotify/callback"
```

**Problems:**
1. Only works for specific deployment
2. Local development requires setting env var
3. If domain changes, OAuth flow breaks until env var updated

**Recommendations:**
1. Remove default or use placeholder like `https://api.example.com/auth/spotify/callback`
2. Add validation that redirect URI matches request origin
3. Document in README that redirect URI must match deployment domain exactly

---

*Security audit and technical debt analysis: 2026-05-29*
