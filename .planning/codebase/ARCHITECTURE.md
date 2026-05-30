# Architecture

**Analysis Date:** 2026-05-29

## Pattern Overview

**Overall:** Multi-service containerized backend with a sidecar microservice pattern

**Key Characteristics:**
- Three independent Docker Compose services: Jellyfin (catalog), slskd (peer downloads), sidecar (API + streaming)
- Sidecar acts as orchestration layer wrapping Spotify Web API and librespot streaming
- Shared volumes across services (media, downloads, sidecar-data) for inter-service communication
- FastAPI event loop wrapping synchronous librespot calls via thread pool
- Stateful session management for both Spotify OAuth and librespot credentials

## Layers

**Catalog Layer (Jellyfin):**
- Purpose: Music metadata catalog, UI, MusicBrainz integration, user browsing
- Location: External service (jellyfin/jellyfin:latest)
- Contains: Web UI (port 8096), REST API, library scanner
- Depends on: `/media` host volume for music files
- Used by: End users (browser), Radio frontend (API reads)

**Download Service Layer (slskd):**
- Purpose: Soulseek P2P download daemon and fallback source
- Location: External service (slskd/slskd:latest)
- Contains: Web UI (port 5030), REST API, P2P network client
- Depends on: Soulseek P2P network, `/downloads` host volume
- Used by: Sidecar (future fallback wiring in Phase 5)

**API/Streaming Layer (Sidecar):**
- Purpose: HTTP API for search (Spotify Web API), authentication (OAuth), and streaming (librespot)
- Location: `sidecar/app/main.py` (FastAPI app)
- Contains: Route handlers, request/response serialization, async orchestration
- Depends on: Spotify credentials, librespot session manager
- Used by: Future Radio frontend, future curated library UI

**Authentication Layer:**
- Purpose: Manage both Spotify OAuth tokens and librespot credentials
- Location: `sidecar/app/auth.py` (Spotify OAuth), `sidecar/app/librespot_session.py` (credentials + streaming)
- Contains: OAuth state machines, token refresh logic, credential persistence
- Depends on: Spotify OAuth endpoints, librespot-python library
- Used by: Main routes (`/search`, `/download`), auth endpoint handlers

**Metadata/Search Layer:**
- Purpose: Spotify Web API search client, track metadata normalization
- Location: `sidecar/app/spotify.py`
- Contains: SpotifyClient singleton, search/track lookup, response transformation
- Depends on: Spotify Web API (public endpoints), httpx async client
- Used by: `/search` and `/download` routes

**Configuration Layer:**
- Purpose: Environment-based settings injection
- Location: `sidecar/app/config.py`
- Contains: Pydantic Settings class, path resolution, credential keys
- Depends on: Environment variables from docker-compose.yaml
- Used by: All modules (imported as `settings` singleton)

## Data Flow

**Search Flow (Spotify Web API):**

1. Client calls `GET /search?q=album&limit=20`
2. Main route handler (`main.py`) invokes `spotify.search_tracks()`
3. SpotifyClient checks cached token; if missing or expired, requests new one via Client Credentials OAuth
4. Issues search request to `https://api.spotify.com/v1/search` with Bearer token
5. Response items transformed to track dicts (id, name, artists, album, duration, cover_url, etc.)
6. Returns `{query, count, tracks: [...]}`

**Authentication Flow (Spotify OAuth):**

1. Client navigates to `GET /auth/spotify/login`
2. Handler generates random state token, stores in memory with 10-minute TTL, redirects to Spotify authorize endpoint
3. User authorizes, Spotify redirects to `/auth/spotify/callback` with code + state
4. Handler validates state (present, not expired), exchanges code for tokens via Token URL
5. Tokens (access, refresh, expiry, scope) persisted to `/data/spotify_tokens.json`
6. Client receives HTML confirmation; future downloads use persisted refresh token

**Download Flow (librespot streaming):**

1. Client calls `POST /download/{track_id}` (e.g., `POST /download/4cOdK2wGLETKBW3PvgPWqLv`)
2. Main handler fetches track metadata from Spotify (GET `/v1/tracks/{id}`)
3. Derives artist/album/title, constructs output path: `{MEDIA_PATH}/Artist/Album/Track.ogg`
4. Offloads to thread pool: `asyncio.to_thread(librespot_session.download_track, ...)`
5. Thread acquires librespot session (lazy-init from credentials.json, retry on connection failure)
6. Creates TrackId from Spotify track URI, fetches audio stream via librespot content feeder
7. Streams VorbisOnlyAudioQuality (VERY_HIGH = 320kbps) chunks to output file
8. Returns `{status, track_id, path (relative to media root), metadata}`

**Librespot Credential Setup (one-time):**

1. Developer runs `python3 tools/get_credentials.py` locally
2. Script builds librespot session with OAuth callback
3. User opens printed Spotify auth URL, authorizes
4. Local callback captures credentials, writes to `credentials.json`
5. Developer uploads via `curl -X POST /auth/librespot/credentials --data-binary @credentials.json`
6. Handler validates shape (requires username + auth_data/credentials), persists to `/data/librespot_credentials.json`
7. Resets session singleton so next download request rebuilds from new credentials

**State Management:**

- **Spotify OAuth tokens**: Persisted to `/data/spotify_tokens.json` (sidecar-data volume), auto-refreshed on next use if within 30 seconds of expiry
- **librespot credentials**: Persisted to `/data/librespot_credentials.json`, triggers session reset on upload
- **librespot session**: Lazy singleton with thread lock, retries 5 times on AP connection failure, backoff 0.5s * attempt
- **Pending OAuth states**: In-memory dictionary with 10-minute TTL, pruned before each login

## Key Abstractions

**SpotifyClient:**
- Purpose: Stateful client for Spotify Web API operations (search, track lookup)
- Examples: `sidecar/app/spotify.py` (SpotifyClient singleton instantiated as `spotify`)
- Pattern: Lazy token fetch with caching (30-second buffer before expiry); uses Client Credentials OAuth for public API access

**librespot_session:**
- Purpose: Credentials management and streaming orchestration
- Examples: `sidecar/app/librespot_session.py` (module-level session singleton + lock)
- Pattern: Lazy session initialization from stored credentials file; thread-safe via Lock; retries transient connection errors; validates Spotify track IDs (regex: 22-char alphanumeric)

**Token Refresh Mechanism:**
- Purpose: Keep user access tokens valid without manual re-auth
- Examples: `sidecar/app/auth.py:get_user_access_token()`, `auth.py:callback()`
- Pattern: Check expiry on access, refresh if within 30s of expiry, re-persist updated tokens

## Entry Points

**HTTP Server:**
- Location: `sidecar/app/main.py` (FastAPI instance)
- Triggers: Docker CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Responsibilities: Route registration, dependency injection, request handling

**Health Check:**
- Location: `GET /health`
- Triggers: Docker healthcheck probe (30s interval)
- Responsibilities: Return `{status: ok}` if service is responsive

**Routers (attached to main app):**
- `sidecar/app/auth.py:router` (prefix `/auth/spotify`) — OAuth login, callback, status
- `sidecar/app/auth.py:librespot_router` (prefix `/auth/librespot`) — credentials upload, status
- Main routes in `main.py` — `/search`, `/download`, `/health`

## Error Handling

**Strategy:** Synchronous validation on input; async await on external calls; HTTP exception mapping with descriptive messages

**Patterns:**

- **Invalid input:** `HTTPException(400, "...")` for malformed requests (e.g., invalid track ID format, missing OAuth state)
- **Auth failure:** `HTTPException(401, "...")` for missing/expired tokens, invalid credentials
- **Service unavailable:** `HTTPException(503, "...")` for missing Spotify config; `HTTPException(502, "...")` for librespot AP connection failure
- **Not found:** `HTTPException(404, "...")` for tracks not found on Spotify
- **Transient failures:** librespot retries 5 times with exponential backoff (0.5s * attempt); Spotify token refresh retries implicitly

## Cross-Cutting Concerns

**Logging:** Standard Python logging module; librespot_session logs to logger "librespot_session" (retry attempts, warnings on connection failure)

**Validation:**
- Spotify track IDs: Regex `^[A-Za-z0-9]{22}$` checked before librespot operations
- OAuth state: Must exist in pending states dict and not be expired
- Credentials shape: librespot requires "username" + ("credentials" OR "auth_data"/"auth_type")
- Query strings: Spotify search query min_length=1, limit bounded 1-50

**Authentication:**
- Spotify OAuth: Client Credentials (search, metadata) and Authorization Code (streaming, refresh)
- librespot credentials: Uploaded once, persisted, validated on each session init
- No container-to-container auth (Jellyfin, slskd) — internal network only; Authentik forward-auth handled at Coolify reverse proxy layer (not in this sidecar)

---

*Architecture analysis: 2026-05-29*
