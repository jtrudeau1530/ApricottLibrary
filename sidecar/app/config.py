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

    jellyfin_internal_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str = "REPLACE_WITH_JELLYFIN_API_KEY"

    public_app_url: str = "https://library.zektek.us"


settings = Settings()
