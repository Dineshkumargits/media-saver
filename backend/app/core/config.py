"""Application configuration, loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Media Saver API"
    ENV: str = "development"

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Rate limiting (slowapi / limits syntax, e.g. "10/minute")
    RATE_LIMIT_EXTRACT: str = "20/minute"
    RATE_LIMIT_DOWNLOAD: str = "10/minute"
    RATE_LIMIT_DEFAULT: str = "60/minute"

    # yt-dlp
    YTDLP_SOCKET_TIMEOUT: int = 15
    YTDLP_COOKIES_FILE: str | None = None  # path to cookies.txt for gated content
    MAX_EXTRACT_CONCURRENCY: int = 8

    # Download streaming
    DOWNLOAD_CHUNK_SIZE: int = 1024 * 256  # 256 KB
    UPSTREAM_TIMEOUT_SECONDS: float = 30.0
    MAX_ALLOWED_FILESIZE_BYTES: int = 5 * 1024 * 1024 * 1024  # 5 GB safety cap

    # Instagram (instagrapi) session cache
    IG_USERNAME: str | None = None
    IG_PASSWORD: str | None = None
    IG_SESSION_PATH: str = "sessions/ig_session.json"

    # Security: only allow extraction from known-safe schemes/hosts patterns
    ALLOWED_URL_SCHEMES: tuple[str, ...] = ("http", "https")
    BLOCKED_HOST_SUFFIXES: tuple[str, ...] = (
        "localhost",
        ".local",
        ".internal",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
