from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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

    library_catalog_token: str = ""

    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_max_completion_tokens: int = Field(default=2048, ge=256, le=8192)
    ai_max_calls_per_job: int = Field(default=3, ge=1, le=5)
    ai_batch_size: int = Field(default=20, ge=5, le=20)
    ai_timeout_seconds: int = Field(default=90, ge=10, le=180)
    acquisition_concurrency: int = Field(default=2, ge=1, le=4)
    acquisition_max_attempts: int = Field(default=3, ge=1, le=5)
    acquisition_timeout_seconds: int = Field(default=300, ge=30, le=900)
    station_import_attempts: int = Field(default=20, ge=1, le=60)
    slskd_internal_url: str = "http://slskd:5030"
    slskd_username: str = "admin"
    slskd_password: str = ""
    slskd_api_key: str = ""
    slskd_complete_path: str = "/downloads/complete"
    discovery_min_interval_hours: int = Field(default=24, ge=6, le=168)
    discovery_max_schedule_runs: int = Field(default=30, ge=1, le=365)


settings = Settings()
