# Apricot Library — Placeholders

Items left as placeholders during autonomous milestone build (2026-05-30). Replace these with real values before deploy.

## Required before first boot

| Env var | Purpose | Placeholder | Where used |
|---|---|---|---|
| `APRICOT_ADMIN_USERNAME` | Master admin username | `admin` | sidecar startup (`sidecar/app/admin_provision.py`) |
| `APRICOT_ADMIN_PASSWORD` | Master admin password (raw — hashed at boot) | `change-me-on-first-boot` | sidecar startup |
| `BETTER_AUTH_SECRET` | 32-byte hex secret for cookie signing | `REPLACE_WITH_OPENSSL_RAND_HEX_32` | frontend env (`frontend/.env`) |
| `POSTGRES_PASSWORD` | Postgres superuser password | `apricot-dev-only-change-me` | docker-compose |
| `POSTGRES_USER` | Postgres user | `apricot` | docker-compose |
| `POSTGRES_DB` | Postgres database name | `apricot` | docker-compose |
| `DATABASE_URL` | Async DSN for sidecar | `postgresql+psycopg://apricot:apricot-dev-only-change-me@postgres:5432/apricot` | sidecar |
| `JELLYFIN_API_KEY` | Jellyfin admin API key (created in Jellyfin Dashboard → Advanced → API Keys) | `REPLACE_WITH_JELLYFIN_API_KEY` | sidecar Phase 3 |
| `JELLYFIN_INTERNAL_URL` | Internal URL for sidecar → Jellyfin | `http://jellyfin:8096` | sidecar Phase 3 |
| `PUBLIC_APP_URL` | Public origin for cookies/redirects | `https://library.zektek.us` | frontend |

Generate `BETTER_AUTH_SECRET` with:
```bash
openssl rand -hex 32
```

## Coolify / DNS tasks

- [ ] Add DNS A record for `library.zektek.us` pointing at the Coolify host
- [ ] In Coolify, configure the new `frontend` service domain as `library.zektek.us` (port 3000)
- [ ] Update `sidecar` service in Coolify to receive traffic at the `/api/*` path on `library.zektek.us` (priority 10, higher than frontend's `/*`) — see `docker-compose.yaml` Traefik labels
- [ ] `api.library.zektek.us` can keep serving the sidecar in parallel during the transition; retire after Phase 4 is live
- [ ] Set all env vars above in Coolify (do NOT commit `.env` — only `.env.example`)
- [ ] Create a Jellyfin API key in Dashboard → Advanced → API Keys (Phase 3 requirement)

## Coolify storage

- [ ] Confirm `MEDIA_PATH` and `DOWNLOADS_PATH` are still pointing at the persistent host paths (already configured in earlier phases)
- [ ] Postgres uses a Coolify-managed named volume — no extra storage step needed unless you want to mount a host path

## Deferred / tech debt (not blocking)

- [ ] Rate limiting on `/api/auth/login` (suggest `slowapi`) — deferred from Phase 1
- [ ] Per-route permission enforcement UI / role display — schema ready, UI in Phase 6
- [ ] Light theme — dark only in v1
- [ ] PWA install support — v1.x candidate
- [ ] Soulseek peer port `50300/tcp` exposure — optional, already in compose comments

## Manual deployment validation (post-build)

After replacing placeholders and deploying:

1. `curl https://library.zektek.us/api/health` → `{"status":"ok"}`
2. `curl https://library.zektek.us/api/search?q=test` → `401 Unauthorized` (auth gate works)
3. Visit `https://library.zektek.us` in browser → see login page
4. Log in as the master admin → see home placeholder
5. Refresh browser → still logged in (session persistence)
6. Log out → redirected to login
7. (Phase 4+) Add a Spotify track from search → all open browser tabs receive an SSE event within ~1s
8. (Phase 5+) Open a song → audio plays via the sidecar proxy (Jellyfin API key never appears in DevTools Network)
