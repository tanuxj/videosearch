import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import health, search
from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import session as db_session
from app.history.routes import router as history_router
from app.videos import embedder
from app.videos.routes import router as videos_router
from app.videos.search import router as clip_search_router

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    logger.info(
        "%s starting (env=%s, debug=%s)", settings.app_name, settings.app_env, settings.app_debug
    )
    # Non-fatal: the API still boots so /health and /docs stay reachable and
    # the failure shows up as one clear log line instead of a stack trace per
    # request.
    if await db_session.ping():
        logger.info("Database connection OK")

    # Importing torch and loading CLIP costs ~45 s cold. Doing it here on a
    # background thread means the first upload or search does not pay for it,
    # while /health and /docs stay reachable throughout. Deliberately not
    # awaited: a slow or failed load must not stop the API from booting.
    warmup_task: asyncio.Task | None = None
    if settings.prewarm_clip_model:

        async def _prewarm() -> None:
            started = time.perf_counter()
            try:
                # Also exports + loads the ONNX vision session when enabled,
                # so the one-time ~30s export never lands on a user request.
                await asyncio.to_thread(embedder.prewarm)
                logger.info("CLIP model ready in %.1fs", time.perf_counter() - started)
            except Exception:  # noqa: BLE001 - degraded, not fatal
                logger.exception("CLIP model preload failed; will retry on first use")

        warmup_task = asyncio.create_task(_prewarm())

    yield

    if warmup_task is not None and not warmup_task.done():
        warmup_task.cancel()
    await db_session.dispose()
    logger.info("%s shutting down", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Backend API for the VideoSearch frontend.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health"])
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(videos_router, prefix=settings.api_v1_prefix)
app.include_router(clip_search_router, prefix=settings.api_v1_prefix)
app.include_router(history_router, prefix=settings.api_v1_prefix)
app.include_router(search.router, prefix=settings.api_v1_prefix, tags=["search"])


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
        "auth": f"{settings.api_v1_prefix}/auth/login",
        "search": f"{settings.api_v1_prefix}/search?q=typescript",
    }
