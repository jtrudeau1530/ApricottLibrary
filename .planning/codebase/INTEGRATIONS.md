# External Integrations

**Analysis Date:** 2026-05-29

## APIs & External Services

**Music Metadata & Search:**
- Spotify Web API - Track search, metadata, and cover art retrieval
  - SDK/Client: httpx (async HTTP requests)
  - Auth: OAuth 2.0 Client Credentials (public search) + Authorization Code (Premium streaming)
  - Endpoints: `https://accounts.spotify.com/api/token`, `https://api.spotify.com/v1/search`, `https://api.spotify.com/v1/tracks/{id}`
  - Configuration: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`
  - Implementation: `sidecar/app/spotify.py` (SpotifyClient class)

**Audio Download & Streaming:**
- Spotify Premium Account (via librespot) - 320 kbps OGG Vorbis streaming and download
  - SDK/Client: librespot 0.0.10 (Rust binding to Spotify's access protocol)
  - Auth: librespot credentials.json (generated locally, uploaded once)
  - Scope: `streaming` (required for downloading tracks)
  - Implementation: `sidecar/app/librespot_session.py`
  - Credentials file: `/data/librespot_credentials.json` (persisted in sidecar-data volume)

**P2P File Sharing (Fallback):**
- Soulseek P2P Network (via slskd) - Fallback for tracks unavailable on Spotify
  - Service: slskd container (self-hosted Soulseek daemon)
  - Port: 6234/TCP (P2P, optional), 5030/TCP (web UI + REST API)
  - Configuration: `SOULSEEK_USERNAME`, `SOULSEEK_PASSWORD` (free Soulseek account)
  - Web UI: http://localhost:5030 (credentials: `SLSKD_USERNAME`/`SLSKD_PASSWORD`)
  - Downloads land in: `DOWNLOADS_PATH` (keeps them separate from tagged library)

## Data Storage

**Databases:**
- Jellyfin built-in SQLite - Music library metadata, catalog
  - Connection: Local file-based (volume: `jellyfin-config:/config`)
  - Client: Jellyfin's internal ORM
  - Purpose: Album/artist/track catalog, user playback history, metadata

**File Storage:**
- Local filesystem - Shared host volumes
  - `MEDIA_PATH` (`/media` in sidecar) - Finished, tagged music library (Jellyfin reads; Library writes)
  - `DOWNLOADS_PATH` (`/downloads` in sidecar) - Staging area for Soulseek downloads (curated before moving to MEDIA_PATH)
  - `jellyfin-config` volume - Jellyfin configuration and database
  - `jellyfin-cache` volume - Jellyfin transcoding/cache
  - `slskd-config` volume - slskd configuration and indexes
  - `sidecar-data` volume - Persisted sidecar data (Spotify tokens, librespot credentials)

**Caching:**
- Redis: Not used
- In-memory: Spotify token caching within SpotifyClient (cached in `_token`, `_expires_at`)

## Authentication & Identity

**Auth Provider:**
- Spotify OAuth 2.0 (future integration with Authentik)
  - Flow 1: Client Credentials (public metadata search) - No user login
  - Flow 2: Authorization Code (Premium account downloads) - Browser-based OAuth
  - Flow 3: librespot stored credentials - One-time credential upload
  - Implementation: `sidecar/app/auth.py` (spotify OAuth router)
  - Tokens persisted to: `/data/spotify_tokens.json` (sidecar-data volume)

**Token Management:**
- Access token refresh: Auto-refreshes if expired more than 30s
- Refresh token stored: Yes (`refresh_token` in tokens.json)
- Scope required: `streaming user-read-private user-read-email`

**Note on Authentik:**
- README mentions "Authenticated through **Authentik** via forward-auth at the reverse proxy"
- Currently NOT integrated in this codebase (Phase 5)
- Will be wired in at Coolify reverse proxy layer, not in sidecar

## Monitoring & Observability

**Error Tracking:**
- None configured (future consideration)
- Errors raised as FastAPI HTTPException with status codes

**Logs:**
- Python logging module: `logging.getLogger("librespot_session")` in `sidecar/app/librespot_session.py`
- No log aggregation configured
- uvicorn logs to stdout (docker logs captures)

**Health Checks:**
- GET `/health` endpoint - Returns `{"status": "ok"}`
- Docker healthcheck: `curl http://localhost:8000/health` (30s interval)

## CI/CD & Deployment

**Hosting:**
- Coolify (Docker Compose from Git) - Orchestrates three services (jellyfin, slskd, sidecar)
- GitHub repo: `https://github.com/jtrudeau1530/ApricottLibrary`
- Deployment: Docker Compose reads `.env` from Coolify UI (not committed)

**CI Pipeline:**
- None configured
- Future: Pre-commit linting/formatting recommended

**Docker Images:**
- `jellyfin/jellyfin:latest` - Official Jellyfin image
- `slskd/slskd:latest` - Official slskd image
- `sidecar` - Built from `sidecar/Dockerfile` (Python 3.12-slim base)

## Environment Configuration

**Required env vars (from `.env.example`):**
- `SPOTIFY_CLIENT_ID` - Spotify app ID (get from https://developer.spotify.com/dashboard)
- `SPOTIFY_CLIENT_SECRET` - Spotify app secret
- `SPOTIFY_REDIRECT_URI` - OAuth callback (default: https://api.library.zektek.us/auth/spotify/callback)
- `SOULSEEK_USERNAME` - P2P account (free signup at slsknet.org)
- `SOULSEEK_PASSWORD` - P2P password
- `SLSKD_USERNAME` - Web UI auth (default: admin)
- `SLSKD_PASSWORD` - Web UI password (REQUIRED)
- `MEDIA_PATH` - Host path for library (e.g., /data/apricot/media)
- `DOWNLOADS_PATH` - Host path for download staging (e.g., /data/apricot/downloads)
- `JELLYFIN_URL` - Public URL Jellyfin advertises (e.g., https://jellyfin.zektek.us)
- `TZ`, `PUID`, `PGID` - Host identity

**Secrets location:**
- `.env` file (not in git; loaded by docker-compose)
- Spotify tokens: `/data/spotify_tokens.json` (sidecar-data volume, docker secret)
- librespot credentials: `/data/librespot_credentials.json` (sidecar-data volume, docker secret)

**No use of Vault/Secrets Manager:** Secrets stored in docker volumes (acceptable for self-hosted Coolify)

## Webhooks & Callbacks

**Incoming:**
- POST `/auth/librespot/credentials` - Accepts librespot credentials.json uploaded from client
- GET `/auth/spotify/callback` - Spotify OAuth callback (state validation, token exchange)

**Outgoing:**
- Coolify webhook for GitHub pushes (configured in repo settings, not in codebase)

## Service Communication

**Internal (within docker-compose):**
- sidecar → slskd: HTTP calls to `http://slskd:5030/api/...` (future phase, not currently wired)
- sidecar → Spotify: HTTPS to `api.spotify.com` (outbound internet)
- Jellyfin ← sidecar: No direct calls; sidecar writes to shared `/media` volume

**External (Coolify reverse proxy):**
- Jellyfin: `https://jellyfin.zektek.us` (mapped to port 8096)
- slskd: `https://slskd.zektek.us` (mapped to port 5030)
- sidecar: `https://api.library.zektek.us` (mapped to port 8000)

---

*Integration audit: 2026-05-29*
