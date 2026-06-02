from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "https://library.zektek.us/api/auth/spotify/callback"

    data_path: str = "/data"
    media_path: str = "/media"
    downloads_path: str = "/downloads"

    database_url: str = "postgresql+psycopg://apricot:apricot-dev-only-change-me@postgres:5432/apricot"

    apricot_admin_username: str = "admin"
    apricot_admin_password: str = "change-me-on-first-boot"

    session_cookie_name: str = "apricot_session"
    session_cookie_secure: bool = True
    session_ttl_days: int = 30
    # Scope the session cookie to *.zektek.us so the frontend on
    # library.zektek.us can read the cookie set by api.library.zektek.us.
    # Without this, browsers default to host-only - login POST succeeds
    # but the frontend never sees the cookie, so the UI silently appears
    # logged-out (no error shown either). Set to "" in dev/non-zektek
    # deployments to fall back to host-only behaviour.
    session_cookie_domain: str = ".zektek.us"

    jellyfin_internal_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str = "REPLACE_WITH_JELLYFIN_API_KEY"

    public_app_url: str = "https://library.zektek.us"

    # bgutil-pot-provider service URL — yt-dlp's plugin calls it to mint
    # PO Tokens for YouTube's SABR streaming path.
    bgutil_pot_url: str = "http://bgutil-pot:4416"


settings = Settings()
