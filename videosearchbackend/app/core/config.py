from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]

# Root of the backend project (two levels up from this file).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "VideoSearch API"
    app_env: AppEnv = "development"
    app_debug: bool = False

    # Server bind settings (used by the `videosearch-api` CLI entry point)
    host: str = "127.0.0.1"
    port: int = Field(default=3006, ge=1, le=65535)

    api_v1_prefix: str = "/api/v1"

    # Browser origins allowed to call this API. Accepts a JSON array
    # (CORS_ORIGINS=["http://a","http://b"]) or a comma-separated list.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ]
    )

    log_level: str = "INFO"

    # ── Postgres database (spawned by docker-compose) ────────────
    # The compose stack passes these to the container; when running the
    # app locally they default to the same dev values.
    database_url: str = "postgresql://videosearch:videosearch@localhost:5432/videosearch"
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "videosearch"
    postgres_user: str = "videosearch"
    postgres_password: str = "videosearch"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached `Settings` instance (reads `.env` once)."""
    return Settings()
