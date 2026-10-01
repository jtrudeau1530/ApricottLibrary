# Apricot Library

The library backend for the Apricot Suite — music storage, metadata, and downloads.

Companion to [Apricot Radio](https://github.com/jtrudeau1530/ApricottRadio). Radio streams; Library stores.

## AI station maker

Open **AI stations** from Library's home page (`/stations`), describe a vibe,
choose 5–50 songs, and press **Make station**. A persistent background job
generates suggestions, checks the complete Jellyfin catalog (including Library
metadata overrides) and the shared Library media files, then automatically
queues missing recordings. No per-song approval is needed. Jobs continue when
the page closes and resume after sidecar restarts.

Matching normalizes Unicode and punctuation while retaining recording-version
words such as live, remix and acoustic. Different-length recordings with the
same tags are reported as ambiguous rather than silently substituted. The
queue shares a canonical recording identity across AI stations, Spotify imports
and YouTube imports, using PostgreSQL locks and a unique constraint to prevent
new concurrent duplicate jobs. Existing queue history is reused; this migration
does not delete old duplicate files or queue rows.

Automatic acquisition reuses yt-dlp for public YouTube audio, accepts matching
Topic/official-audio results, validates the produced OGG and duration, writes
tags and artwork, and atomically imports the file without overwriting existing
audio. Spotify discovery is optional metadata enrichment; the station workflow
does not initiate Spotify/librespot downloads. Existing manually requested queue
work can be reused. The new public-source path does not use cookies, token
plugins, geographic bypass, DRM formats or access-control bypass. If a source is
restricted or no confident recording is found, that track fails visibly.

The UI distinguishes existing music, acquisition, files awaiting Jellyfin
indexing, verified imports, failures, and Radio sync. A playlist contains only
tracks confirmed by Jellyfin. A downloaded file that is not indexed within the
limit remains on disk and is reported as an import failure, never as a completed
station track. Artwork problems are reported separately from audio failures.
**Retry failed work** retries the station as a batch; **Retry Radio sync** leaves
the downloaded music and playlist intact.

Configure the Library sidecar environment (also passed through Compose):

| Variable | Purpose / default |
|---|---|
| `AI_BASE_URL` | OpenAI-compatible API root, default `https://api.openai.com/v1` |
| `AI_MODEL` | Required provider model name; no model is silently selected |
| `AI_API_KEY` | Provider key if required; may be empty for a local provider |
| `AI_MAX_COMPLETION_TOKENS` | Hard output token budget, default 2048; configurable from 256 to 8192 |
| `AI_TIMEOUT_SECONDS` | Generation timeout, default 90 |
| `ACQUISITION_CONCURRENCY` | Queue workers per sidecar process, default 2, maximum 4 |
| `ACQUISITION_MAX_ATTEMPTS` | Automatic download and job/sync retry limit, default 3 |
| `ACQUISITION_TIMEOUT_SECONDS` | Public download subprocess timeout, default 300 |
| `STATION_IMPORT_ATTEMPTS` | Jellyfin indexing polls per recording, default 20 at 15-second intervals |
| `RADIO_INTERNAL_URL` | Reachable Radio sidecar origin, without `/api` |
| `RADIO_LIBRARY_TOKEN` | Dedicated integration secret, identical on Library and Radio |
| `RADIO_PUBLIC_URL` | Optional Radio frontend origin for station links |

The AI endpoint must accept Chat Completions with JSON object mode. Responses
are validated locally; see the [official JSON-mode documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
Generation, network errors and Radio sync use bounded retries with backoff;
public downloads also have process-group cancellation so ffmpeg does not keep
running after timeout or shutdown. Each user may have three active station jobs.

For Radio station creation, configure `RADIO_LIBRARY_TOKEN` on Radio's
`radio-engine` service and use a reachable `RADIO_INTERNAL_URL` in Library. Both
services must mount the same media directory, writable in Library and readable
in Radio. The new `/api/library/stations/sync` endpoint validates and incrementally
indexes only the requested files using Radio's existing catalog helpers, then
adds them to an idempotent station associated with the Library job. Retries
preserve Radio operator edits and the station queue. Library and Radio currently
use different user/session tables: the authenticated Library owner's username
must match a Radio account with `station_manager` or `admin` role, and Radio's
station cap still applies. Jellyfin audio outside Library's shared media mount
can enter a Library playlist but cannot be synchronized to Radio through this
integration; the job reports that failure explicitly.

Without Radio configuration, the UI offers Library playlists. Radio integration
is disabled by default and uses its own service token, not the Radio bootstrap
admin token or forwarded session cookies. Keep API keys and integration secrets
in local/deployment environment settings.

### Prepared configuration (2026-10-01)

Library's ignored, owner-only `.env` selects `AI_MODEL=gpt-4o-mini`,
`AI_BASE_URL=https://api.openai.com/v1`, `AI_MAX_COMPLETION_TOKENS=2048`, and
`AI_TIMEOUT_SECONDS=45`. This older, non-reasoning model supports Chat
Completions and JSON object mode; no reasoning parameters are sent. Current
standard pricing is $0.15 per million input tokens and $0.60 per million output
tokens ([official model reference](https://developers.openai.com/api/docs/models/gpt-4o-mini)).
Its availability was confirmed using the configured account's read-only model
endpoint. No paid station generation was performed. Compact responses keep
reasons short; if a large station exceeds the budget, generation fails visibly
before acquisition. Request fewer songs or increase the environment limit.

`RADIO_INTERNAL_URL=http://radio-engine:8000` uses the actual Radio service alias
on the shared `coolify` Docker network. A request from the running Library
sidecar to its `/api/health` returned HTTP 200. Both live services already mount
the same host media directory; Radio reads it at `/library_media` and Library
writes it at `/media`. `RADIO_PUBLIC_URL=https://radio.zektek.us` supplies station
links. No new network or public port is needed in this Coolify environment.

The OpenAI key was reused from KTalk's existing backend credential without
changing KTalk. Library and Radio's ignored `.env` files have mode `0600` and
contain the same dedicated `RADIO_LIBRARY_TOKEN`; the OpenAI key is present only
in Library's file. These settings feed backend services through Compose; they
are not frontend build arguments. Preserve these files outside version control.
Coolify manages deployment variables separately: securely transfer Library's
AI and Radio settings to Library's runtime environment, and only the matching
`RADIO_LIBRARY_TOKEN` to Radio's runtime environment before an authorized
rollout. Keep both services attached to the existing shared `coolify` network.
Local `.env` files are not automatically uploaded to Coolify.

Configuration is prepared locally, not applied to the running containers.
Neither service was rebuilt, restarted or deployed. The new authenticated sync
endpoint, migrations, station generation, acquisition and playback still need
verification after an authorized rollout; the existing health endpoint alone
does not verify the new workflow.

Library migration `0003_discovery_stations` and Radio migration
`0012_library_station_jobs` run through the existing startup migration hooks.
The feature is implemented in source; no live providers, database migrations,
download/import cycle or Radio playback have been exercised as part of this
change. Tests were intentionally not run.

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
