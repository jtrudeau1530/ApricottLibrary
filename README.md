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
2. Create the media directory referenced by `MEDIA_PATH` if it doesn't exist.
3. `docker compose up -d`
4. Open Jellyfin at `http://localhost:8096`, complete first-run, point the music library at `/media`.

## Deployment (Coolify)

Library deploys to Coolify as a **Docker Compose from Git** resource:

1. Coolify → New Resource → Docker Compose → Public/Private Repository.
2. Repo: `https://github.com/jtrudeau1530/ApricottLibrary` · Branch: `main`.
3. Set env vars in Coolify's UI (do **not** commit `.env`):
   - `TZ`, `PUID`, `PGID` — host identity.
   - `JELLYFIN_URL` — the public URL Coolify will serve Jellyfin from.
   - `MEDIA_PATH` — **must be an absolute host path** (e.g. `/data/apricot/media`). A relative path like `./media` will lose data on redeploy because Coolify checks the repo out to a fresh directory each time. The Apricot Radio service must mount this same path.
4. Coolify handles the reverse proxy + TLS. Authentik is wired in via forward-auth at the proxy layer (configured separately in Coolify, not in this compose file).
5. Enable the GitHub webhook so pushes redeploy automatically.

## Status

Phase 1 (current): Jellyfin standalone.
Phase 2: slskd added to compose.
Phase 3: FastAPI download sidecar with request API.
Phase 4: OnTheSpot integration (Spotify primary).
Phase 5: yt-dlp edge cases + Authentik forward-auth.
