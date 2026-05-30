# Codebase Structure

**Analysis Date:** 2026-05-29

## Directory Layout

```
library/
├── .planning/                    # GSD planning artifacts
│   └── codebase/                 # Codebase analysis documents
├── sidecar/                      # FastAPI sidecar service
│   ├── Dockerfile                # Python 3.12 slim base + uvicorn
│   ├── requirements.txt           # Dependencies (fastapi, librespot, httpx)
│   ├── .dockerignore              # Build context exclusions
│   └── app/                       # Application code
│       ├── __init__.py            # Empty marker
│       ├── main.py                # FastAPI instance, root routes
│       ├── config.py              # Settings (Pydantic)
│       ├── auth.py                # Spotify OAuth + librespot endpoints
│       ├── spotify.py             # SpotifyClient class
│       └── librespot_session.py    # Session mgmt, download orchestration
├── tools/                         # Developer utilities
│   └── get_credentials.py         # Generates librespot credentials.json locally
├── docker-compose.yaml            # Service topology (Jellyfin, slskd, sidecar)
├── .env.example                   # Environment variable reference
├── .gitignore                     # Exclude .env, .venv, cache
├── README.md                      # User-facing quickstart + deployment guide
└── .git/                          # Version control
```

## Directory Purposes

**sidecar/:**
- Purpose: FastAPI web service wrapping Spotify search/auth and librespot streaming
- Contains: Python code (main.py, modules), Dockerfile, dependencies
- Key files: `sidecar/app/main.py` (entry point), `sidecar/app/auth.py` (OAuth), `sidecar/app/spotify.py` (search client)

**sidecar/app/:**
- Purpose: Application logic layer
- Contains: FastAPI routes, authentication handlers, metadata client, session management
- Key files: All modules are imported by main.py as routers or singletons

**tools/:**
- Purpose: One-off developer scripts, not part of the deployed service
- Contains: Credential generation helper
- Key files: `tools/get_credentials.py` (interactive, one-time use before first deployment)

**.planning/codebase/:**
- Purpose: Generated codebase analysis (ARCHITECTURE.md, STRUCTURE.md, etc.)
- Contains: Markdown documentation for GSD orchestrator
- Key files: Varies per analysis run (not committed; generated on demand)

## Key File Locations

**Entry Points:**
- `sidecar/app/main.py`: FastAPI instance creation, root route handlers (`/health`, `/search`, `/download`)
- `sidecar/Dockerfile`: Container entry: `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`

**Configuration:**
- `sidecar/app/config.py`: Environment variable binding (SPOTIFY_CLIENT_ID, MEDIA_PATH, etc.)
- `docker-compose.yaml`: Service definitions, volume mappings, port exposure, env var passing
- `.env.example`: Reference for all required environment variables

**Authentication & OAuth:**
- `sidecar/app/auth.py`: Spotify OAuth flows (login, callback, token refresh), librespot credential endpoints
- `tools/get_credentials.py`: Local credential generation (run outside container)

**Metadata & Search:**
- `sidecar/app/spotify.py`: SpotifyClient class for Web API calls (search, track lookup)
- `sidecar/app/main.py`: `/search` route handler

**Streaming & Downloads:**
- `sidecar/app/librespot_session.py`: Session management, download_track() function (sync, run via to_thread)
- `sidecar/app/main.py`: `/download/{track_id}` route handler

## Naming Conventions

**Files:**
- Python modules: lowercase with underscores (`spotify.py`, `librespot_session.py`, `config.py`)
- Configuration: UPPERCASE in environment, snake_case in Python code (`SPOTIFY_CLIENT_ID` env var → `spotify_client_id` in Settings)
- Credentials files: lowercase with underscores, .json extension (`spotify_tokens.json`, `librespot_credentials.json`)
- Docker files: `Dockerfile` (no extension), `docker-compose.yaml`

**Functions & Endpoints:**
- Python functions: lowercase with underscores (`download_track()`, `get_user_access_token()`, `_safe()`)
- Private helpers: leading underscore (`_safe_name`, `_to_track()`, `_token_file()`)
- HTTP routes: lowercase with slashes, kebab-case in auth paths (`/auth/spotify`, `/auth/librespot`)
- Parameters: snake_case in URLs and query strings (`GET /search?q=...&limit=20`)

**Variables:**
- Module-level singletons: lowercase (`spotify`, `settings`, `_session`, `_pending_states`)
- Type hints: Pascal case (Settings, SpotifyClient, HTTPException)
- Constants: UPPERCASE (`SCOPES`, `TOKEN_URL`, `STATE_TTL_SECONDS`, `VALID_TRACK_ID`)

**Directories:**
- Service containers: lowercase (`sidecar`, `tools`)
- Internal module dirs: lowercase (`app`, `codebase`)
- Planning dirs: `.planning` (dot prefix to hide from typical listings)

## Where to Add New Code

**New HTTP Endpoint:**
- Primary code: Add route handler to `sidecar/app/main.py` (if simple) or new module in `sidecar/app/`
- Routers: Define APIRouter in dedicated module (e.g., `sidecar/app/new_feature.py`), include in main.py via `app.include_router(...)`
- Tests: Not yet present; would go in `sidecar/tests/test_new_feature.py`

**New Authentication Flow:**
- Implementation: `sidecar/app/auth.py` (add new router and handlers)
- Secrets/tokens: Persist to `/data` directory (mounted sidecar-data volume) as JSON files
- Status endpoint: Add to librespot_router or new router for consistency

**Metadata/Search Enhancement:**
- Implementation: `sidecar/app/spotify.py` (add methods to SpotifyClient class)
- Usage: Import and call from route handlers in main.py
- Response normalization: Update `_to_track()` helper if schema changes

**Streaming/Download Fallback (Phase 5):**
- slskd integration: Add methods to librespot_session.py or new `sidecar/app/slskd.py`
- yt-dlp integration: Add methods to librespot_session.py or new `sidecar/app/yt_dlp.py`
- Route wiring: Update `/download/{track_id}` handler in main.py to try librespot first, then slskd, then yt-dlp

**Utilities/Helpers:**
- Shared functions: Add to existing module (e.g., path helpers in librespot_session.py)
- Cross-cutting: Consider new `sidecar/app/utils.py` if needed
- Note: `_safe()` function in main.py sanitizes filenames; reuse or extract if needed elsewhere

## Special Directories

**sidecar-data (Docker volume):**
- Purpose: Persist state across container restarts
- Contains: `spotify_tokens.json` (OAuth tokens), `librespot_credentials.json` (Spotify Premium creds)
- Generated: Yes (by sidecar container on first auth)
- Committed: No (volume, not in repo)

**MEDIA_PATH (host path, e.g. `/data/apricot/media`):**
- Purpose: Music library catalog, shared with Radio frontend and Jellyfin
- Contains: Downloaded tracks organized as `Artist/Album/Track.ogg`
- Generated: Yes (by sidecar `/download` endpoint)
- Committed: No (external mount, stable across deployments)

**DOWNLOADS_PATH (host path, e.g. `/data/apricot/downloads`):**
- Purpose: Staging area for Soulseek downloads (slskd)
- Contains: Uncurated downloads from P2P network
- Generated: Yes (by slskd daemon)
- Committed: No (external mount, separate from MEDIA_PATH on purpose)

**.venv-tools/ (Python venv):**
- Purpose: Local development environment for tools/
- Contains: Python packages, pip cache
- Generated: Yes (created by `python -m venv .venv-tools`)
- Committed: No (excluded in .gitignore)

## File Reference by Phase

**Phase 1-2 (Jellyfin + slskd):**
- `docker-compose.yaml` (services: jellyfin, slskd)
- `README.md` (quickstart, deployment)
- `.env.example` (Jellyfin/slskd env vars)

**Phase 3 (FastAPI sidecar):**
- `sidecar/app/main.py` (FastAPI instance, `/health`, `/search`)
- `sidecar/app/spotify.py` (SpotifyClient, search via Client Credentials)
- `sidecar/app/config.py` (Settings)
- `sidecar/Dockerfile` (uvicorn entry)

**Phase 4a (Spotify OAuth):**
- `sidecar/app/auth.py` (OAuth login/callback/status routes)
- `.env.example` (SPOTIFY_REDIRECT_URI)

**Phase 4b (librespot streaming):**
- `sidecar/app/librespot_session.py` (session mgmt, download_track)
- `sidecar/app/main.py` (/download/{track_id} route)
- `tools/get_credentials.py` (credential generation)
- `sidecar/requirements.txt` (librespot package)

**Phase 5 (Fallbacks, tagging) — not yet implemented:**
- `sidecar/app/slskd.py` (planned)
- `sidecar/app/yt_dlp.py` (planned)

---

*Structure analysis: 2026-05-29*
