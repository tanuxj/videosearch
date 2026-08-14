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

    # How long a presigned direct-upload URL stays valid (seconds). Large
    # files can take a while to push from the browser to the bucket.
    presign_url_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)

    # Hard ceiling on a single video upload (bytes). The browser streams
    # straight to storage on the presigned path, so this mainly protects the
    # multipart fallback (which buffers through the API). Files above 5 GiB go
    # through R2's presigned multipart upload automatically — see
    # `POST /videos/presign/multipart`.
    max_upload_bytes: int = Field(default=10 * 1024**3, ge=1)

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
    # "onnx" runs the CLIP vision tower through onnxruntime (~1.4x faster on
    # CPU, identical vectors, lighter load); "torch" keeps the classic eager
    # path. Falls back to torch automatically if the export fails.
    clip_backend: Literal["onnx", "torch"] = "onnx"
    # Load CLIP at startup on a background thread rather than on the first
    # upload/search. Tests turn this off so they don't pull ~1.2 GB of weights.
    prewarm_clip_model: bool = True
    # Start the indexing job automatically on upload. Tests flip this off
    # so uploads stay `processing` until the test runs the pipeline itself.
    index_on_upload: bool = True
    # Whether the local CLIP frame index is built at all.
    #
    # Distinct from `index_on_upload`, which decides if the pipeline runs:
    # this decides whether the *frame embedding* part of it runs. Turning it
    # off leaves transcription and the Twelve Labs index working — they are
    # the parts that do not spend minutes of local CPU — so a video is ready
    # in the time it takes someone else's GPUs to do the work. Search must
    # then use `engine=twelvelabs`, since no local vectors will exist.
    clip_index_enabled: bool = True
    # Frames are sampled at this interval (seconds). 1.0 = one frame per second.
    frame_interval_seconds: float = 1.0
    # Scene-aware sampling: a sampled frame is embedded only when its picture
    # actually changed versus the last kept frame, so long static-heavy files
    # (movies, talks) index a fraction of the frames with no real search loss.
    # A frame is kept when its mean absolute pixel difference (0–255, measured
    # on a small grayscale proxy) reaches `scene_threshold`, or when
    # `scene_max_gap_seconds` have passed since the last keep (so slow pans and
    # zooms still contribute frames). Set `scene_aware_sampling` to false for
    # the old fixed-rate behaviour.
    scene_aware_sampling: bool = True
    scene_threshold: float = Field(default=8.0, ge=0.0, le=255.0)
    scene_max_gap_seconds: float = Field(default=6.0, ge=0.5, le=3600.0)
    # Rows per batch when writing embeddings to Postgres.
    index_batch_size: int = 128

    # ── Semantic search ────────────────────────────────────────
    # Minimum cosine similarity (0–1) between the prompt embedding and a frame
    # for it to count as a match. CLIP's text↔image similarity for unrelated
    # content clusters around 0.2, so 0.24 is a safe floor for real matches;
    # below it a search returns zero scenes instead of the video's least-bad
    # frames. Raise it for stricter results, lower it if real matches are
    # being missed on your footage.
    search_min_similarity: float = Field(default=0.24, ge=0.0, le=1.0)
    # Consecutive matching frames closer than this (seconds) are merged into a
    # single scene, so a multi-second moment reads as one clip with a real
    # start and end rather than several overlapping single-frame windows.
    search_merge_window_seconds: float = Field(default=2.0, ge=0.0)

    # ── LLM query expansion (the "middleman") ──────────────────
    # CLIP matches best when text names what's visible — objects, setting,
    # colours, action. Terse or broken-English prompts embed poorly. When
    # `llm_api_key` is set, each search prompt is rewritten + expanded by an
    # OpenAI-compatible chat model into a few visually-grounded variants, and
    # every variant is embedded (per-frame similarity = the best of them), so
    # vague phrasing still lands. Without a key, the raw prompt is used as-is.
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # How many extra expanded variants to generate (on top of the raw prompt).
    llm_expand_prompts: int = Field(default=2, ge=0, le=5)
    llm_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)

    # ── Transcription (speech → text) ───────────────────────────
    # Whisper-family ASR over any OpenAI-compatible `/audio/transcriptions`
    # endpoint. Groq is the default host: `whisper-large-v3-turbo` transcribes
    # an hour of audio in well under a minute, which is what makes the
    # transcript land while frame indexing is still running.
    #
    # Transcription is off until `stt_api_key` is set — videos then carry
    # `transcript_status="skipped"` and the app behaves exactly as before.
    stt_api_key: str | None = None
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_model: str = "whisper-large-v3-turbo"
    # ISO-639-1 hint (e.g. "en"). Leave unset for automatic detection — the
    # model reports what it heard and it is stored on the video row.
    stt_language: str | None = None
    stt_timeout_seconds: float = Field(default=300.0, ge=5.0, le=1800.0)
    # Audio is split into chunks of this many seconds before upload. Keeps
    # every request under the provider's file-size cap and lets long videos
    # transcribe in parallel instead of end to end.
    stt_chunk_seconds: float = Field(default=600.0, ge=30.0, le=3600.0)
    # Chunks transcribed concurrently. Above ~4 most providers rate-limit
    # rather than go faster.
    stt_max_concurrency: int = Field(default=4, ge=1, le=16)
    # Mono, 16 kHz — Whisper resamples to this anyway, so sending more is
    # upload time for nothing.
    stt_audio_bitrate: str = "16k"
    # Whisper emits confident-sounding text over silence and music. Segments
    # whose no-speech probability is above this are dropped rather than shown
    # to the user as real dialogue.
    stt_no_speech_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    # ── Twelve Labs (Marengo) — alternative index ───────────────
    # A managed, video-native alternative to the local CLIP index. Runs in
    # parallel with it rather than replacing it, so the two can be compared on
    # real footage. Off until `twelvelabs_api_key` is set.
    twelvelabs_api_key: str | None = None
    twelvelabs_base_url: str = "https://api.twelvelabs.io/v1.3"
    twelvelabs_model: str = "marengo3.0"
    # Bind to an index by name so a fresh environment needs no manual setup;
    # set `twelvelabs_index_id` to pin an existing one instead.
    twelvelabs_index_name: str = "videosearch"
    twelvelabs_index_id: str | None = None
    # Modalities Marengo searches. CLIP is visual-only, so `audio` is exactly
    # the capability worth measuring the difference on.
    #
    # Deliberately a comma-separated **string** rather than a `list[str]`:
    # pydantic-settings JSON-decodes complex types straight from the
    # environment *before* any field validator runs, so `visual,audio` in a
    # compose file fails to parse and takes the whole app down at import time.
    # Parsed by `twelvelabs_modalities` instead.
    twelvelabs_search_options: str = "visual,audio"
    twelvelabs_timeout_seconds: float = Field(default=120.0, ge=5.0, le=900.0)
    # Start a remote index automatically on upload, alongside the CLIP pass.
    # Off by default: it spends the account's indexing minutes on every video,
    # which should be a deliberate choice rather than a surprise.
    twelvelabs_index_on_upload: bool = False
    # Polling cadence and ceiling while waiting for remote indexing.
    twelvelabs_poll_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    twelvelabs_max_wait_seconds: float = Field(default=3600.0, ge=60.0, le=21_600.0)

    # ── URL import (paste-a-link) ───────────────────────────────
    # Let users index videos by pasting a URL (YouTube, Twitch, Zoom,
    # Vimeo, or a direct video file link). The backend downloads the video
    # with yt-dlp (or a plain HTTP download for direct file URLs), stores it
    # like an upload, then runs the normal indexing pipeline.
    url_import_enabled: bool = True
    # Cap on a URL-downloaded video (bytes). Defaults to the same 10 GiB
    # ceiling as file uploads — the user chose no separate cap.
    url_import_max_bytes: int = Field(default=10 * 1024**3, ge=1)
    # yt-dlp format preference. A single progressive MP4 plays in browsers
    # without an ffmpeg merge step; anything else is a fallback (webm plays,
    # mkv indexes but may not play back in the app).
    url_import_format: str = "b[ext=mp4]/b"
    # How long the pre-download metadata probe (yt-dlp extract_info) may run
    # before the request fails. Keeps a slow or unresponsive site from
    # hanging the paste-a-link call.
    url_import_probe_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    # SSRF guard: URLs whose host resolves to a private/loopback/link-local
    # address are rejected so the backend cannot be made to fetch internal
    # services. Tests flip this on so they can point imports at a local
    # fixture server.
    url_import_allow_private: bool = False
    # Most videos a single `POST /videos/from-urls` request will reserve,
    # after playlist/channel expansion. A channel with hundreds of uploads
    # imports its newest N rather than everything.
    url_import_max_batch: int = Field(default=50, ge=1, le=500)
    # Whether a pasted playlist/channel link expands into its individual
    # videos. Off by default: importing dozens of videos from one link is too
    # big a job to start from a paste, so such links are rejected with a
    # clear message instead. Flip on to re-enable expansion.
    url_import_expand_playlists: bool = False

    # ── Postgres database (spawned by docker-compose) ────────────
    # The compose stack passes these to the container; when running the
    # app locally they default to the same dev values.
    database_url: str = "postgresql://videosearch:videosearch@localhost:5432/videosearch"
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "videosearch"
    postgres_user: str = "videosearch"
    postgres_password: str = "videosearch"

    @property
    def twelvelabs_configured(self) -> bool:
        """True when the Twelve Labs index is usable."""
        return bool(self.twelvelabs_api_key)

    @property
    def twelvelabs_modalities(self) -> list[str]:
        """`twelvelabs_search_options` parsed into the modalities to search."""
        return [item.strip() for item in self.twelvelabs_search_options.split(",") if item.strip()]

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
    def transcription_configured(self) -> bool:
        """True when an ASR endpoint is available to transcribe audio with."""
        return bool(self.stt_api_key and self.stt_base_url and self.stt_model)

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
