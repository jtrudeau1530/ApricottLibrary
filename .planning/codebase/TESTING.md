# Testing Patterns

**Analysis Date:** 2026-05-29

## Test Framework

**Status:** No testing framework detected

**Runner:**
- Not applicable — no test suite exists
- No pytest, unittest, or other test runner installed
- No `conftest.py`, `pytest.ini`, or `setup.cfg` test configuration found

**Assertion Library:**
- Not applicable

**Run Commands:**
- None — tests do not exist

## Test File Organization

**Location:**
- No `tests/` or `test/` directory found in project root or `sidecar/` subdirectory

**Naming:**
- No test files exist (`*.test.py`, `*.spec.py`, `*_test.py`)

**Structure:**
- Not applicable

## Test Structure

**Suite Organization:**
- Not applicable — no tests written

**Patterns:**
- Not applicable

## Mocking

**Framework:**
- Not applicable — no mocking libraries detected

**Patterns:**
- Not applicable

**What to Mock:**
- Not applicable

**What NOT to Mock:**
- Not applicable

## Fixtures and Factories

**Test Data:**
- Not applicable

**Location:**
- Not applicable

## Coverage

**Requirements:** Not enforced

**View Coverage:**
- No coverage tools installed or configured

## Test Types

**Unit Tests:**
- None exist

**Integration Tests:**
- None exist

**E2E Tests:**
- Framework: Not used
- Manual testing via `curl` documented in README: `curl -X POST https://api.library.zektek.us/auth/librespot/credentials` at `README.md` line 100-105

## Manual Testing Patterns

The project uses curl-based manual testing for API verification:

**Spotify OAuth Flow:**
```bash
# Login
GET /auth/spotify/login

# Check status
GET /auth/spotify/status
# Response: {"connected": true|false, "scope": "...", "expires_at": ..., "expired": true|false}
```

**librespot Credentials:**
```bash
# Check librespot connection status
curl https://api.library.zektek.us/auth/librespot/status
# Response: {"connected": true|false}

# Upload credentials
curl -X POST https://api.library.zektek.us/auth/librespot/credentials \
     -H "content-type: application/json" \
     --data-binary @credentials.json
```

**Spotify Search:**
```bash
# Search tracks
GET /search?q=search+term&limit=20
# Response: {"query": "...", "count": N, "tracks": [...]}
```

**Track Download:**
```bash
# Download a track (requires valid Spotify token + librespot credentials)
POST /download/{track_id}
# Response: {"status": "downloaded", "track_id": "...", "path": "...", "metadata": {...}}
```

## Health Checks

**Docker Healthcheck:**
- Endpoint: `GET /health`
- Response: `{"status": "ok"}`
- Used by Docker Compose for service liveness check: `curl -fsS http://localhost:8000/health`
- Configured in `sidecar/Dockerfile` at line 21-24

## Known Testing Gaps

**Critical Gaps:**
- No unit tests for core functionality (Spotify API client, auth flows, track download)
- No integration tests for OAuth token refresh/expiry handling
- No tests for error handling in librespot session initialization (currently tested manually)
- No tests for API validation (e.g., invalid track IDs, missing query parameters)
- No mocking of external services (Spotify API, librespot session)

**Risk Areas Without Test Coverage:**
- `sidecar/app/auth.py` — OAuth token refresh logic, state expiry pruning, callback validation
- `sidecar/app/spotify.py` — Token caching and refresh, Spotify API response parsing
- `sidecar/app/librespot_session.py` — Session initialization retries, credential validation, connection error handling
- `sidecar/app/main.py` — File path sanitization, download coordination

**Recommended Testing Strategy:**

1. **Unit Tests** (pytest + pytest-asyncio):
   - Test token refresh logic with mocked `httpx.AsyncClient`
   - Test `_safe()` filename sanitization with edge cases
   - Test Spotify API response parsing (valid, malformed, error responses)
   - Test credential validation in `save_credentials()`
   - Test track ID validation regex

2. **Integration Tests**:
   - Mock OAuth token exchange; test full `/auth/spotify/callback` flow
   - Test librespot session init with mocked credentials file
   - Test `/download/{track_id}` with mocked Spotify API and librespot

3. **End-to-End Tests**:
   - Docker container healthcheck validation
   - Full OAuth flow with browser-based callback (manual or Selenium)

---

*Testing analysis: 2026-05-29*
