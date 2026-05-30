<!-- GSD:project-start source:PROJECT.md -->
## Project

**Apricot Library**

A self-hosted music library and "back room" catalog for the Apricot Suite. The Library stores every song (audio files + metadata), lets multiple logged-in users browse it Spotify-style, search Spotify for new songs and one-click queue them for download, and curate the catalog through playlists and metadata edits. Library is the source of truth that the future Apricot Radio frontend will read from.

**Core Value:** A multi-user, synchronized catalog where any logged-in user can search, fetch, and curate music — and the queue/library they see is the same view everyone else sees.

### Constraints

- **Tech stack**: SvelteKit frontend — user preference; aligns with the goal of a lightweight, server-friendly catalog UI.
- **Tech stack**: Postgres for app-state — multi-user, synchronized queue requires a real DB; sidecar already runs in Docker.
- **Tech stack**: FastAPI sidecar (existing) extended with auth/queue/SSE — avoid splitting the backend into multiple services.
- **Tech stack**: Jellyfin REST API as catalog source — don't re-implement library indexing; let Jellyfin own metadata.
- **Real-time**: SSE for server→client updates — one-way push fits queue/fetch/storage updates; simpler than WebSockets.
- **Deployment**: Coolify Docker Compose — frontend deploys as another service in the existing compose stack.
- **Auth**: No third-party auth provider — fully app-native; sessions in the app DB.
- **Repo**: Frontend lives in the existing Library repo (`https://github.com/jtrudeau1530/ApricottLibrary`), not a separate repo.
- **Authorship**: Commits authored solely by the user (no Claude co-author trailer) — per user preference.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.12 - FastAPI sidecar backend (async HTTP API for music search/download)
- YAML - docker-compose configuration and service definitions
## Runtime
- Python 3.12 (slim Docker image)
- Docker containers (orchestrated via docker-compose)
- pip
- Lockfile: `sidecar/requirements.txt` (pinned versions)
## Frameworks
- FastAPI 0.115.0 - HTTP API framework for the sidecar service
- Uvicorn 0.30.6 - ASGI application server (runs on port 8000)
- httpx 0.27.2 - Async HTTP client for Spotify Web API calls
- pydantic-settings 2.5.2 - Environment variable configuration management
- librespot 0.0.10 - Spotify audio streaming client (OGG Vorbis download)
## Key Dependencies
- librespot 0.0.10 - Streams tracks from Spotify Premium account as OGG Vorbis files; handles session management and credential storage
- httpx 0.27.2 - Makes authenticated requests to Spotify Web API and OAuth endpoints
- pydantic-settings 2.5.2 - Loads environment variables for API credentials and file paths
- uvicorn[standard] 0.30.6 - Includes uvloop and httptools for performance
## Configuration
- Loaded via Pydantic Settings from environment variables (docker-compose passes via `environment` section)
- Settings class: `sidecar/app/config.py` → `Settings` dataclass
- `SPOTIFY_CLIENT_ID` - Spotify app credentials (Client Credentials flow)
- `SPOTIFY_CLIENT_SECRET` - Spotify app secret
- `SPOTIFY_REDIRECT_URI` - OAuth callback URL (default: `https://api.library.zektek.us/auth/spotify/callback`)
- `DATA_PATH` - Container path for persisted token/credential files (default: `/data`)
- `MEDIA_PATH` - Host path mounted to `/media` in sidecar (where downloads land)
- `DOWNLOADS_PATH` - Host path mounted to `/downloads` (staging for non-library downloads)
- `TZ`, `PUID`, `PGID` - Host environment (timezone, user/group IDs)
- `jellyfin` - Music catalog/browser UI (port 8096)
- `slskd` - Soulseek P2P downloader daemon (ports 5030 web/REST, 50300 peer listen)
- `sidecar` - FastAPI service (port 8000, exposed via reverse proxy)
- `Dockerfile` (sidecar): Multi-stage not used; builds Python image with requirements
## Platform Requirements
- Python 3.12
- Docker + docker-compose
- pip for sidecar dependencies
- Docker engine (Coolify orchestrates via docker-compose)
- Outbound internet access for Spotify API (port 443/HTTPS)
- Outbound port 4070 for librespot connecting to Spotify access points
- Soulseek P2P (port 6234 default for P2P connections)
## Deployment Architecture
- `sidecar` depends_on `slskd` (waits for health before starting)
- All three services (jellyfin, slskd, sidecar) share named Docker volumes for persistence
- Media and downloads share host paths to enable cross-service file access
- Jellyfin: `curl http://localhost:8096/health`
- slskd: `wget http://localhost:5030/health`
- sidecar: `curl http://localhost:8000/health`
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Module files use lowercase with underscores: `config.py`, `librespot_session.py`, `spotify.py`
- No hyphens in filenames; underscores are preferred
- Descriptive names reflecting module responsibility
- Lowercase with underscores (snake_case) for all functions
- Public functions: no leading underscore (e.g., `search_tracks()`, `download_track()`)
- Private/internal functions: leading underscore (e.g., `_safe()`, `_get_token()`, `_prune_states()`)
- Async functions use `async def` keyword; names don't indicate async status
- Example: `async def search_tracks()` at `sidecar/app/spotify.py:40`
- Snake_case for local variables and module-level state
- Private module state uses leading underscore: `_session`, `_token`, `_pending_states`
- Configuration singleton: all caps for module-level constants (`VALID_TRACK_ID`, `AUTH_URL`, `SCOPES`, `STATE_TTL_SECONDS`)
- Type hints used throughout, especially for function parameters and returns
- Pydantic `BaseSettings` for configuration classes: `Settings` at `sidecar/app/config.py:4`
- Custom data transformation functions return plain dicts (not dataclasses): `_to_track()` returns `dict` at `sidecar/app/spotify.py:63`
- Type unions use pipe syntax: `str | None` at `sidecar/app/config.py:34`
## Code Style
- No explicit formatter configured (no `.eslintrc`, `.prettierrc`, `ruff.toml`, or `pyproject.toml`)
- Inferred style from codebase:
- No linting configuration file found
- Code follows PEP 8 conventions implicitly
- Import organization follows Python conventions (stdlib, third-party, local)
## Import Organization
- None detected; relative imports used exclusively
- Example: `from . import librespot_session` at `sidecar/app/main.py:7`
- Example: `from .config import settings` at `sidecar/app/spotify.py:6`
- Relative imports within same package (`.module`)
- Function imports alongside module imports: `from .auth import librespot_router, router as auth_router` at `sidecar/app/main.py:8-9`
- Import renamed for clarity: `router as auth_router`
## Error Handling
- FastAPI `HTTPException` used for API responses
- Try/except blocks catch specific exceptions:
- HTTP response status checks: `if resp.status_code != 200:` at `sidecar/app/auth.py:94`
- Return `None` for missing resources: `if resp.status_code == 404: return None` at `sidecar/app/spotify.py:57`
## Logging
- Module-level logger created per file: `log = logging.getLogger("librespot_session")` at `sidecar/app/librespot_session.py:12`
- Logging used for operational events (retries, warnings):
- Structured logging with %-formatting: `log.warning("message %s", variable)`
## Comments
- Function docstrings describe purpose and notable behavior
- Example: `"""Return a valid user access token, refreshing if expired. Used by /download."""` at `sidecar/app/auth.py:145`
- Inline comments explain algorithm or external API specifics (e.g., `VALID_TRACK_ID` regex, OAuth flow details)
- Inline comments for non-obvious logic: `# Keep within 30s of expiry threshold before refreshing` (implicit in code at `sidecar/app/spotify.py:20`)
- Not applicable; Python codebase uses docstrings instead
- Function docstrings use triple-quoted strings
- Brief one-line descriptions followed by optional detail
- Example: `"""Stream a track via librespot and write OGG Vorbis bytes to output_path. Sync; run via to_thread."""` at `sidecar/app/librespot_session.py:84`
## Function Design
- Functions kept relatively small (10-50 lines typical)
- Single responsibility: `_get_token()` handles token acquisition/refresh only
- Async operations broken into logical steps (e.g., `async def callback()` receives state parameter at `sidecar/app/auth.py:69`)
- Type hints on all parameters: `async def search(q: str = Query(...), limit: int = Query(20, ge=1, le=50))` at `sidecar/app/main.py:30-31`
- FastAPI Query/Path/Request dependencies used for route parameters
- Optional parameters use defaults: `limit: int = 20` at `sidecar/app/spotify.py:40`
- Type hints on all return values: `-> dict`, `-> str | None`, `-> Path`
- Async functions explicitly typed: `async def search_tracks(...) -> list[dict]:` at `sidecar/app/spotify.py:40`
- None used for missing/error cases: `-> dict | None` at `sidecar/app/spotify.py:51`
## Module Design
- Module-level singleton instances exported: `spotify = SpotifyClient()` at `sidecar/app/spotify.py:79`
- Module-level singleton configuration: `settings = Settings()` at `sidecar/app/config.py:16`
- Routers instantiated and included in app: `app.include_router(auth_router)` at `sidecar/app/main.py:14`
- Empty `__init__.py` files used: `sidecar/app/__init__.py` is blank
- No barrel file exports; submodules imported directly where needed
- Modules with leading underscore don't exist; "private" functions use underscore prefix instead
- Helper functions like `_safe()`, `_to_track()`, `_get_token()` private within their modules
## Async/Concurrency Patterns
- FastAPI endpoints are async: `async def search()` at `sidecar/app/main.py:30`
- Blocking operations delegated to thread pool: `await asyncio.to_thread(librespot_session.download_track, ...)` at `sidecar/app/main.py:49`
- Synchronous modules (e.g., librespot_session) designed to be callable from threads
- Threading locks used for session state: `_session_lock = Lock()` at `sidecar/app/librespot_session.py:14`
- Global mutable state protected: `with _session_lock:` at `sidecar/app/librespot_session.py:54`
## Configuration Management
- Pydantic `BaseSettings` class in `sidecar/app/config.py`
- Environment variables loaded automatically from `.env`
- Model config: `SettingsConfigDict(env_file=".env", extra="ignore")`
- Defaults provided for all settings
- Singleton instance: `settings = Settings()` instantiated once per app
- Configuration read from environment at app startup
- Example: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `MEDIA_PATH`, `DATA_PATH` at `sidecar/app/config.py:7-13`
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Three independent Docker Compose services: Jellyfin (catalog), slskd (peer downloads), sidecar (API + streaming)
- Sidecar acts as orchestration layer wrapping Spotify Web API and librespot streaming
- Shared volumes across services (media, downloads, sidecar-data) for inter-service communication
- FastAPI event loop wrapping synchronous librespot calls via thread pool
- Stateful session management for both Spotify OAuth and librespot credentials
## Layers
- Purpose: Music metadata catalog, UI, MusicBrainz integration, user browsing
- Location: External service (jellyfin/jellyfin:latest)
- Contains: Web UI (port 8096), REST API, library scanner
- Depends on: `/media` host volume for music files
- Used by: End users (browser), Radio frontend (API reads)
- Purpose: Soulseek P2P download daemon and fallback source
- Location: External service (slskd/slskd:latest)
- Contains: Web UI (port 5030), REST API, P2P network client
- Depends on: Soulseek P2P network, `/downloads` host volume
- Used by: Sidecar (future fallback wiring in Phase 5)
- Purpose: HTTP API for search (Spotify Web API), authentication (OAuth), and streaming (librespot)
- Location: `sidecar/app/main.py` (FastAPI app)
- Contains: Route handlers, request/response serialization, async orchestration
- Depends on: Spotify credentials, librespot session manager
- Used by: Future Radio frontend, future curated library UI
- Purpose: Manage both Spotify OAuth tokens and librespot credentials
- Location: `sidecar/app/auth.py` (Spotify OAuth), `sidecar/app/librespot_session.py` (credentials + streaming)
- Contains: OAuth state machines, token refresh logic, credential persistence
- Depends on: Spotify OAuth endpoints, librespot-python library
- Used by: Main routes (`/search`, `/download`), auth endpoint handlers
- Purpose: Spotify Web API search client, track metadata normalization
- Location: `sidecar/app/spotify.py`
- Contains: SpotifyClient singleton, search/track lookup, response transformation
- Depends on: Spotify Web API (public endpoints), httpx async client
- Used by: `/search` and `/download` routes
- Purpose: Environment-based settings injection
- Location: `sidecar/app/config.py`
- Contains: Pydantic Settings class, path resolution, credential keys
- Depends on: Environment variables from docker-compose.yaml
- Used by: All modules (imported as `settings` singleton)
## Data Flow
- **Spotify OAuth tokens**: Persisted to `/data/spotify_tokens.json` (sidecar-data volume), auto-refreshed on next use if within 30 seconds of expiry
- **librespot credentials**: Persisted to `/data/librespot_credentials.json`, triggers session reset on upload
- **librespot session**: Lazy singleton with thread lock, retries 5 times on AP connection failure, backoff 0.5s * attempt
- **Pending OAuth states**: In-memory dictionary with 10-minute TTL, pruned before each login
## Key Abstractions
- Purpose: Stateful client for Spotify Web API operations (search, track lookup)
- Examples: `sidecar/app/spotify.py` (SpotifyClient singleton instantiated as `spotify`)
- Pattern: Lazy token fetch with caching (30-second buffer before expiry); uses Client Credentials OAuth for public API access
- Purpose: Credentials management and streaming orchestration
- Examples: `sidecar/app/librespot_session.py` (module-level session singleton + lock)
- Pattern: Lazy session initialization from stored credentials file; thread-safe via Lock; retries transient connection errors; validates Spotify track IDs (regex: 22-char alphanumeric)
- Purpose: Keep user access tokens valid without manual re-auth
- Examples: `sidecar/app/auth.py:get_user_access_token()`, `auth.py:callback()`
- Pattern: Check expiry on access, refresh if within 30s of expiry, re-persist updated tokens
## Entry Points
- Location: `sidecar/app/main.py` (FastAPI instance)
- Triggers: Docker CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Responsibilities: Route registration, dependency injection, request handling
- Location: `GET /health`
- Triggers: Docker healthcheck probe (30s interval)
- Responsibilities: Return `{status: ok}` if service is responsive
- `sidecar/app/auth.py:router` (prefix `/auth/spotify`) — OAuth login, callback, status
- `sidecar/app/auth.py:librespot_router` (prefix `/auth/librespot`) — credentials upload, status
- Main routes in `main.py` — `/search`, `/download`, `/health`
## Error Handling
- **Invalid input:** `HTTPException(400, "...")` for malformed requests (e.g., invalid track ID format, missing OAuth state)
- **Auth failure:** `HTTPException(401, "...")` for missing/expired tokens, invalid credentials
- **Service unavailable:** `HTTPException(503, "...")` for missing Spotify config; `HTTPException(502, "...")` for librespot AP connection failure
- **Not found:** `HTTPException(404, "...")` for tracks not found on Spotify
- **Transient failures:** librespot retries 5 times with exponential backoff (0.5s * attempt); Spotify token refresh retries implicitly
## Cross-Cutting Concerns
- Spotify track IDs: Regex `^[A-Za-z0-9]{22}$` checked before librespot operations
- OAuth state: Must exist in pending states dict and not be expired
- Credentials shape: librespot requires "username" + ("credentials" OR "auth_data"/"auth_type")
- Query strings: Spotify search query min_length=1, limit bounded 1-50
- Spotify OAuth: Client Credentials (search, metadata) and Authorization Code (streaming, refresh)
- librespot credentials: Uploaded once, persisted, validated on each session init
- No container-to-container auth (Jellyfin, slskd) — internal network only; Authentik forward-auth handled at Coolify reverse proxy layer (not in this sidecar)
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
