# Technology Stack

**Analysis Date:** 2026-05-29

## Languages

**Primary:**
- Python 3.12 - FastAPI sidecar backend (async HTTP API for music search/download)

**Secondary:**
- YAML - docker-compose configuration and service definitions

## Runtime

**Environment:**
- Python 3.12 (slim Docker image)
- Docker containers (orchestrated via docker-compose)

**Package Manager:**
- pip
- Lockfile: `sidecar/requirements.txt` (pinned versions)

## Frameworks

**Core:**
- FastAPI 0.115.0 - HTTP API framework for the sidecar service
- Uvicorn 0.30.6 - ASGI application server (runs on port 8000)

**Authentication & Integration:**
- httpx 0.27.2 - Async HTTP client for Spotify Web API calls
- pydantic-settings 2.5.2 - Environment variable configuration management
- librespot 0.0.10 - Spotify audio streaming client (OGG Vorbis download)

## Key Dependencies

**Critical:**
- librespot 0.0.10 - Streams tracks from Spotify Premium account as OGG Vorbis files; handles session management and credential storage
- httpx 0.27.2 - Makes authenticated requests to Spotify Web API and OAuth endpoints
- pydantic-settings 2.5.2 - Loads environment variables for API credentials and file paths

**Infrastructure:**
- uvicorn[standard] 0.30.6 - Includes uvloop and httptools for performance

## Configuration

**Environment:**
- Loaded via Pydantic Settings from environment variables (docker-compose passes via `environment` section)
- Settings class: `sidecar/app/config.py` → `Settings` dataclass

**Required Environment Variables:**
- `SPOTIFY_CLIENT_ID` - Spotify app credentials (Client Credentials flow)
- `SPOTIFY_CLIENT_SECRET` - Spotify app secret
- `SPOTIFY_REDIRECT_URI` - OAuth callback URL (default: `https://api.library.zektek.us/auth/spotify/callback`)
- `DATA_PATH` - Container path for persisted token/credential files (default: `/data`)
- `MEDIA_PATH` - Host path mounted to `/media` in sidecar (where downloads land)
- `DOWNLOADS_PATH` - Host path mounted to `/downloads` (staging for non-library downloads)
- `TZ`, `PUID`, `PGID` - Host environment (timezone, user/group IDs)

**Docker Services (compose file: `docker-compose.yaml`):**
- `jellyfin` - Music catalog/browser UI (port 8096)
- `slskd` - Soulseek P2P downloader daemon (ports 5030 web/REST, 50300 peer listen)
- `sidecar` - FastAPI service (port 8000, exposed via reverse proxy)

**Build Configuration:**
- `Dockerfile` (sidecar): Multi-stage not used; builds Python image with requirements

## Platform Requirements

**Development:**
- Python 3.12
- Docker + docker-compose
- pip for sidecar dependencies

**Production:**
- Docker engine (Coolify orchestrates via docker-compose)
- Outbound internet access for Spotify API (port 443/HTTPS)
- Outbound port 4070 for librespot connecting to Spotify access points
- Soulseek P2P (port 6234 default for P2P connections)

## Deployment Architecture

**Service Dependencies (compose):**
- `sidecar` depends_on `slskd` (waits for health before starting)
- All three services (jellyfin, slskd, sidecar) share named Docker volumes for persistence
- Media and downloads share host paths to enable cross-service file access

**Healthchecks:**
- Jellyfin: `curl http://localhost:8096/health`
- slskd: `wget http://localhost:5030/health`
- sidecar: `curl http://localhost:8000/health`

---

*Stack analysis: 2026-05-29*
