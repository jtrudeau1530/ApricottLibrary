# Apricot Library

The library backend for the Apricot Suite — music storage, metadata, and downloads.

Companion to [Apricot Radio](https://github.com/jtrudeau1530/ApricottRadio). Radio streams; Library stores.

## Library-owned music discovery and acquisition

Open **Discover music** (`/discover`) to describe music to add to Library.
This creates an acquisition job, not a Radio station or an automatic playlist.
Library serves all music consumers. `/stations` redirects to discovery; legacy
jobs, playlists and downloaded media remain in place. The existing database
names `discovery_station`/`DiscoveryStation` are retained for compatibility.
Legacy pending Radio publication becomes Library acquisition only; Library no
longer calls Radio or needs its URL/token to discover or acquire music.

AI uses the existing inexpensive, non-reasoning `gpt-4o-mini` configuration and
Chat Completions JSON mode. It generates at most 20 suggestions per call and
up to three calls per job, including top-ups. Each call has a 2,048-output-token
cap. The call budget is persisted **before** requesting the provider, so restarts
and retries cannot spend it again. Deduplication runs between batches. A
50-song request may still fall short if the model returns duplicates, refuses,
truncates or invents unavailable recordings; the job reports its unique count
and why bounded generation stopped. A suggestion is never an acquired song.

The job checks the complete Jellyfin catalog and Library files before acquisition.
Canonical artist/title identities share PostgreSQL locks with manual imports.
Unicode/punctuation differences are normalized, while live/remix/acoustic and
featured-artist distinctions are retained. Known duration is checked; ambiguous
recordings are rejected. Spotify's existing OAuth/client configuration supplies
IDs, album, artwork and duration. It is discovery/metadata access, not a full-track
export API. The existing librespot session file is reported separately; the new
workflow does not decrypt Spotify streams or import previews as complete tracks.

Automatic acquisition tries the existing **slskd/Soulseek** service first, then
unrestricted public **YouTube** audio. Soulseek searches are capped at 100 files /
20 peer responses and two transfer attempts, with duration/file/tag validation.
YouTube checks up to ten candidates and tries at most two confident matches.
Recognized presentation decorations such as `Official Audio HD` are stripped;
recording-version distinctions remain. Artist-channel/Topic/official-audio
results also need matching artist/title and known duration. There is no cookie,
challenge-token, geographic, DRM or access-control bypass in this path.

Acquisition has a configurable overall provider timeout (default 300 seconds),
concurrency 2 (maximum 4), and at most three automatic queue attempts. Per-provider
codes/messages are persisted and shown even if a later fallback succeeds.
Readiness distinguishes configured tools from usable account/source access.
A bot challenge, authentication failure, offline Soulseek account, no confident
match and a missing shared download directory have different actionable errors.
Validated audio is tagged and atomically imported without overwriting media.
Existing MusicBrainz enrichment adds recording-matched genres/year/IDs and cover
art where available; Spotify artwork is reused. Jellyfin refresh/indexing must
confirm the recording before the UI reports a verified import. Art failures
remain warnings, separate from audio/import failures.

### Finite recurring Spotify discovery

The discovery page can save one campaign per user with a Spotify search query
(e.g. `genre:country year:2026`), song count, interval, maximum runs and enable flag.
Campaigns are disabled until explicitly enabled. Defaults are 20 songs every
24 hours for 30 runs. The deployment can set the minimum interval (6–168 hours;
default 24) and maximum campaign runs (1–365; default 30); each campaign is still
finite and returns at most 50 new suggestions per run. Each run reads at most
50 Spotify search results in five calls, excludes already present and previously
suggested recordings, and reports insufficient results. This searches for music
new to Library; it does not promise Spotify's unavailable recommendation APIs or
that each search result was newly released. No AI calls are made by the Spotify
campaign. Saving a campaign explicitly starts a new run budget. Stopping it
prevents future runs; already queued acquisition jobs continue.

The schedule and spent runs survive restarts. Next-run time is advanced before
provider I/O; missed intervals are not replayed. A user may have three active
acquisition jobs. A full queue skips that interval (counting it against the finite run budget), and provider failures remain
visible on the campaign rather than starting a retry storm.

### Backend runtime settings

| Setting | Default / purpose |
|---|---|
| `AI_MODEL`, `AI_BASE_URL`, `AI_API_KEY` | Keep model `gpt-4o-mini`, OpenAI API root, securely supplied backend key |
| `AI_MAX_COMPLETION_TOKENS` | 2048 per call; configurable 256–8192 |
| `AI_MAX_CALLS_PER_JOB`, `AI_BATCH_SIZE` | 3 calls (1–5), 20 suggestions (5–20) |
| `AI_TIMEOUT_SECONDS` | 90 by default; prepared local configuration uses 45 |
| `ACQUISITION_CONCURRENCY`, `ACQUISITION_MAX_ATTEMPTS` | 2 workers / 3 bounded automatic attempts |
| `ACQUISITION_TIMEOUT_SECONDS` | 300-second overall provider budget |
| `STATION_IMPORT_ATTEMPTS` | Legacy variable name: 20 Jellyfin indexing polls at 15 seconds |
| `SLSKD_INTERNAL_URL`, `SLSKD_USERNAME`, `SLSKD_PASSWORD` | Existing slskd origin/login; Compose reuses the configured backend credentials |
| `SLSKD_API_KEY` | Optional alternative to slskd login |
| `SLSKD_COMPLETE_PATH` | `/downloads/complete`, matching slskd's shared completed-download directory |
| `DISCOVERY_MIN_INTERVAL_HOURS`, `DISCOVERY_MAX_SCHEDULE_RUNS` | 24 hours / 30 runs |
| `LIBRARY_CATALOG_TOKEN` | Optional read-only service credential for any music consumer; never needed for discovery |

The optional `/api/consumer/catalog` read contract returns only indexed, validated,
mounted audio with relative paths and metadata. It accepts a dedicated backend
Bearer token and bounded pagination. Radio can consume it; Library does not need
Radio to operate. Local backend `.env` files remain ignored and owner-only, and
are not uploaded to Coolify automatically. Keys/tokens must stay in backend
runtime configuration, never frontend build arguments or source.

### Observed failure and verification limits

Production inspection confirmed one 50-request job saved 42 unique suggestions:
31 failed confident matching and 11 failed public extraction; all 42 used the
single YouTube path. Spotify supplied IDs for 24. The old generation logic
accepted an undersized unique result without topping up; raw responses were not
persisted, so the original model count versus duplicate count cannot be recovered.
A read-only YouTube search exposed the unhandled `Official Audio HD` decoration;
a separate metadata probe hit the host's bot challenge. Existing slskd authentication
and Soulseek connection/login succeeded but discovery never used that service.
Production slskd uses `/app/downloads` and `/app/incomplete`, outside the shared
`/downloads` mount. Readiness now detects this mismatch before requesting a
transfer. The completed path must be configured into the shared downloads mount;
the corrected Compose now sets completed/incomplete directories explicitly.

Correction migrations are additive (`0004_library_discovery` and Radio's
`0013_library_refresh`); no jobs/media are dropped. This correction has not been
committed, pushed, deployed or exercised through actual acquisition/import or
scheduled refresh. Syntax, app imports/OpenAPI, frontend type checks and secret
scans are static checks; no tests or production migrations were run.

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
Phase 3 ✓ — FastAPI sidecar with `/search` (Spotify Web API).
Phase 4a ✓ — Spotify OAuth Web API flow (`/auth/spotify/*`).
Phase 4b (current) — librespot wiring: `/auth/librespot/*` + working `/download/{track_id}` that streams 320kbps OGG to the Jellyfin media volume.
Phase 5 — slskd + yt-dlp fallback wiring; tagging refinement; Authentik forward-auth.

## Sidecar (Phase 3)

The sidecar lives in `./sidecar` and exposes a small HTTP API for the future custom Library frontend:

| Method | Path | Status | Purpose |
|---|---|---|---|
| GET | `/health` | ✓ | Container healthcheck |
| GET | `/search?q=...` | ✓ | Spotify Web API track search (metadata + cover art) |
| GET | `/auth/spotify/login` | ✓ | Start Spotify OAuth (Authorization Code flow, scope `streaming`) |
| GET | `/auth/spotify/callback` | ✓ | OAuth callback — exchanges code for tokens, persists to `/data` |
| GET | `/auth/spotify/status` | ✓ | Returns `{connected, scope, expires_at, expired}` |
| GET | `/auth/librespot/status` | ✓ | Whether `librespot_credentials.json` is present in the sidecar volume |
| POST | `/auth/librespot/credentials` | ✓ | Upload `credentials.json` produced by `tools/get_credentials.py` |
| POST | `/download/{track_id}` | ✓ | Streams 320kbps OGG via librespot, writes to `MEDIA_PATH/Artist/Album/Track.ogg` |

### One-time librespot setup

librespot needs Spotify Premium credentials. We can't run its OAuth flow from inside the server container (the callback assumes browser-and-process on the same host), so we generate `credentials.json` locally and upload it once:

```bash
pip install librespot
python3 tools/get_credentials.py
# Open the printed URL, sign in, authorize. credentials.json written to CWD.

curl -X POST https://api.library.zektek.us/auth/librespot/credentials \
     -H "content-type: application/json" \
     --data-binary @credentials.json
```

Verify: `curl https://api.library.zektek.us/auth/librespot/status` → `{"connected": true}`.

After that, `POST /download/{track_id}` works for any Spotify track ID returned by `/search`.

Search uses the Client Credentials flow (no user login needed). Downloads will use the Authorization Code flow against the user's Premium account — kick it off by visiting `/auth/spotify/login` in the browser. Tokens land in a persisted Docker volume (`sidecar-data`) and auto-refresh.
