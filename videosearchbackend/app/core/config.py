from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]

# Root of the backend project (two levels up from this file).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Obvious placeholder — refused outright when APP_ENV=production.
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


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

    # ── Authentication ───────────────────────────────────────────
    # Access tokens are short-lived JWTs held in memory by the client;
    # refresh tokens are opaque, stored hashed in Postgres and delivered
    # in an httpOnly cookie so JavaScript can never read them.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)

    refresh_cookie_name: str = "vs_refresh"
    # Cookie is scoped to the auth routes — it is never sent to any other
    # endpoint, so a leak in an unrelated handler cannot expose it.
    refresh_cookie_path: str = "/api/v1/auth"
    # Lax works across ports on the same site (localhost:5174 → :3006).
    # Deploying the API on a different registrable domain needs
    # "none" + secure=true.
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    refresh_cookie_secure: bool = False
    refresh_cookie_domain: str | None = None

    # ── Object storage (Cloudflare R2 / any S3 endpoint) ──────────
    # When configured, uploaded videos and thumbnails live in R2. Without
    # it the app falls back to the local `upload_dir` (dev/tests).
    r2_endpoint_url: str | None = None
    r2_bucket_name: str | None = None
    r2_region: str = "auto"
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None

    # Where uploads actually go: "r2" always uses the bucket, "local" always
    # uses the disk, "auto" (default) picks R2 when configured, else disk.
    # Tests force "local" so they never touch the real bucket.
    storage_backend: Literal["r2", "local", "auto"] = "auto"

    # Local fallback storage for when R2 is not configured.
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"

    # ── Edge streaming (Cloudflare Worker) ──────────────────────
    # When `stream_worker_base_url` is set, `GET /videos/{id}/stream-url`
    # returns a short-lived HMAC-signed URL served by the edge Worker
    # (videosearchworker/) instead of proxying video bytes through the API.
    # `stream_signing_secret` must match the Worker's STREAM_SIGN_SECRET.
    stream_worker_base_url: str | None = None
    stream_signing_secret: str = ""
    stream_url_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)

    # ── Indexing pipeline ───────────────────────────────────────
    # CLIP variant used to embed frames and prompts. Hugging Face model id
    # for sentence-transformers; downloads to the HF cache on first use.
    clip_model_name: str = "clip-ViT-B-32"
    # Load CLIP at startup on a background thread rather than on the first
    # upload/search. Tests turn this off so they don't pull ~1.2 GB of weights.
    prewarm_clip_model: bool = True
    # Start the indexing job automatically on upload. Tests flip this off
    # so uploads stay `processing` until the test runs the pipeline itself.
    index_on_upload: bool = True
    # Frames are sampled at this interval (seconds). 1.0 = one frame per second.
    frame_interval_seconds: float = 1.0
    # Rows per batch when writing embeddings to Postgres.
    index_batch_size: int = 128

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

    @model_validator(mode="after")
    def _reject_dev_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET is still the development placeholder. "
                "Set a strong random value, e.g. `openssl rand -hex 32`."
            )
        return self

    @property
    def async_database_url(self) -> str:
        """`DATABASE_URL` normalised to the asyncpg driver SQLAlchemy needs."""
        url = self.database_url
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):  # Heroku-style alias
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def access_token_ttl_seconds(self) -> int:
        return self.access_token_ttl_minutes * 60

    @property
    def refresh_token_ttl_seconds(self) -> int:
        return self.refresh_token_ttl_days * 24 * 60 * 60

    @property
    def storage_configured(self) -> bool:
        """True when all R2 credentials are present and non-empty."""
        return bool(
            self.r2_endpoint_url
            and self.r2_bucket_name
            and self.r2_access_key_id
            and self.r2_secret_access_key
        )

    @property
    def effective_storage_backend(self) -> str:
        """The backend that will actually be used, resolving `auto`."""
        if self.storage_backend == "auto":
            return "r2" if self.storage_configured else "local"
        return self.storage_backend


@lru_cache
def get_settings() -> Settings:
    """Return a cached `Settings` instance (reads `.env` once)."""
    return Settings()
