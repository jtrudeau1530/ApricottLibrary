# Apricot Library

The library backend for the Apricot Suite — music storage, metadata, and downloads.

Companion to [Apricot Radio](https://github.com/jtrudeau1530/ApricottRadio). Radio streams; Library stores.

## What it is

- **Jellyfin** as the music catalog, browser, and metadata source (built-in MusicBrainz integration).
- A custom **download sidecar** (forthcoming) wrapping OnTheSpot, slskd, and yt-dlp behind a single request API.
- Authenticated through **Authentik** via forward-auth at the reverse proxy.
- Radio reads from a shared media volume; Library is the only service that writes to it.

## Stack

| Component | Tool |
|---|---|
| Music catalog & UI | Jellyfin |
| Primary downloader | OnTheSpot (Spotify Premium → 320 kbps OGG) |
| Fallback downloader | slskd (self-hosted Soulseek) |
| Edge case downloader | yt-dlp (YouTube / SoundCloud / Bandcamp) |
| Tagging | Jellyfin built-in (MusicBrainz) |
| Auth | Authentik (forward-auth) |
| Hosting | Coolify (Docker Compose) |

## Quickstart (local)

1. Copy `.env.example` to `.env` and adjust values.
2. Create the directories referenced by `MEDIA_PATH` and `DOWNLOADS_PATH` if they don't exist.
3. `docker compose up -d`
4. Open Jellyfin at `http://localhost:8096`, complete first-run, point the music library at `/media`.
5. Open slskd at `http://localhost:5030`, log in with `SLSKD_USERNAME` / `SLSKD_PASSWORD`, confirm it has connected to the Soulseek network.

## Deployment (Coolify)

Library deploys to Coolify as a **Docker Compose from Git** resource:

1. Coolify → New Resource → Docker Compose → Public/Private Repository.
2. Repo: `https://github.com/jtrudeau1530/ApricottLibrary` · Branch: `main`.
3. Set env vars in Coolify's UI (do **not** commit `.env`):
   - `TZ`, `PUID`, `PGID` — host identity.
   - `JELLYFIN_URL` — the public URL Coolify serves Jellyfin from (e.g. `https://jellyfin.zektek.us`).
   - `MEDIA_PATH` — **must be an absolute host path** (e.g. `/data/apricot/media`). A relative path like `./media` will lose data on redeploy because Coolify checks the repo out to a fresh directory each time. The Apricot Radio service must mount this same path.
   - `DOWNLOADS_PATH` — **must be an absolute host path** (e.g. `/data/apricot/downloads`). Where slskd writes incoming Soulseek downloads. Kept separate from `MEDIA_PATH` so they can be curated before joining the library.
   - `SLSKD_USERNAME`, `SLSKD_PASSWORD` — slskd web UI / REST API auth.
   - `SOULSEEK_USERNAME`, `SOULSEEK_PASSWORD` — your Soulseek P2P account credentials.
4. **Per-service domains in Coolify** — this stack exposes two web UIs, each needs its own domain:
   - `jellyfin` service (port `8096`) → e.g. `jellyfin.zektek.us`.
   - `slskd` service (port `5030`) → e.g. `slskd.zektek.us`.
   Add the DNS A record before deploying so Let's Encrypt can issue the cert.
5. **Soulseek peer port `50300/tcp`** — slskd downloads work without this exposed (passive mode), but exposing it on the host firewall improves discovery/upload performance. Optional.
6. Coolify handles reverse proxy + TLS. Authentik is wired in via forward-auth at the proxy layer (configured separately in Coolify, not in this compose file).
7. Enable the GitHub webhook so pushes redeploy automatically.

## Status

Phase 1 ✓ — Jellyfin standalone deployed.
Phase 2 ✓ — slskd added to compose for Soulseek downloads.
Phase 3 (current) — FastAPI sidecar scaffold with Spotify Web API `/search` endpoint; `/download` stub.
Phase 4 — OnTheSpot integration (Spotify Premium primary downloader).
Phase 5 — slskd + yt-dlp fallback wiring; Authentik forward-auth.

## Sidecar (Phase 3)

The sidecar lives in `./sidecar` and exposes a small HTTP API for the future custom Library frontend:

| Method | Path | Status | Purpose |
|---|---|---|---|
| GET | `/health` | ✓ | Container healthcheck |
| GET | `/search?q=...` | ✓ | Spotify Web API track search (metadata + cover art) |
| POST | `/download/{track_id}` | stub (501) | Will trigger OnTheSpot download in Phase 4 |

Search uses the Client Credentials flow (no user login needed), so you only need a Spotify Developer app's Client ID + Secret. Create the app at <https://developer.spotify.com/dashboard> and set `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` in Coolify env vars.
