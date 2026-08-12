"""Test-wide setup.

`APP_ENV` (and `DATABASE_URL`, when a test database is supplied) must be set
before `app.main` is imported: settings are cached and the engine is built at
import time.

Database-backed tests are skipped unless a reachable Postgres is configured:

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5544/videosearch_test uv run pytest

Point it at a **dedicated throwaway database**: these tests TRUNCATE between
cases. As a guard, they refuse to run at all if the target already contains
user rows, and they only drop the schema if they were the ones that created it.
"""

import asyncio
import os

os.environ["APP_ENV"] = "test"

_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
if _TEST_DB_URL:
    os.environ["DATABASE_URL"] = _TEST_DB_URL

# Tests must never touch a real object-storage bucket, their files go to a
# throwaway dir, and uploads must not auto-start the CLIP indexing job (the
# model is hundreds of MB and tests mock the embedder instead).
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), ".test-uploads"))
os.environ.setdefault("INDEX_ON_UPLOAD", "false")
# Startup would otherwise preload the real CLIP weights (~1.2 GB) as soon as a
# TestClient enters the app's lifespan.
os.environ.setdefault("PREWARM_CLIP_MODEL", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.metadata import Base  # noqa: E402
from app.db.session import SessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402


def _run(coro):
    """Run a coroutine in a throwaway loop, then empty the connection pool.

    Each `asyncio.run` gets a fresh event loop, and an asyncpg connection is
    bound to the loop that created it. Without disposing, the next loop would
    inherit dead pooled connections.
    """

    async def wrapper():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


def _database_available() -> bool:
    """True when the configured database accepts connections."""
    if not _TEST_DB_URL:
        return False

    async def probe() -> bool:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    try:
        return _run(probe())
    except Exception:
        return False


def _existing_user_rows() -> int | None:
    """Row count in `users`, or None when the table does not exist yet."""

    async def probe() -> int | None:
        async with engine.connect() as connection:
            exists = await connection.scalar(text("SELECT to_regclass('public.users')"))
            if exists is None:
                return None
            return await connection.scalar(text("SELECT count(*) FROM users"))

    try:
        return _run(probe())
    except Exception:
        return None


DB_AVAILABLE = _database_available()

# These tests TRUNCATE between cases, so a database holding real rows is off
# limits. Point TEST_DATABASE_URL at a dedicated throwaway database.
_EXISTING_ROWS = _existing_user_rows() if DB_AVAILABLE else None
DB_HAS_DATA = bool(_EXISTING_ROWS)
# Only tear down a schema this session created — never one that was already
# there (dropping a developer's dev schema out from under them is not the
# tests' business).
_SCHEMA_PREEXISTS = _EXISTING_ROWS is not None

if DB_HAS_DATA:
    _SKIP_REASON = (
        f"Refusing to run destructive tests against a database with data "
        f"({_EXISTING_ROWS} users). Point TEST_DATABASE_URL at a throwaway database."
    )
else:
    _SKIP_REASON = "Set TEST_DATABASE_URL to a reachable Postgres to run database tests"

# Applied to every test that needs real tables.
needs_db = pytest.mark.skipif(not DB_AVAILABLE or DB_HAS_DATA, reason=_SKIP_REASON)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Ensure the schema exists, dropping it again only if we created it."""
    if not DB_AVAILABLE or DB_HAS_DATA:
        yield
        return

    async def create() -> None:
        async with engine.begin() as connection:
            # users.id defaults to gen_random_uuid(); frames.embedding is a
            # pgvector column with an HNSW index.
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)

    async def drop() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    _run(create())
    yield
    if not _SCHEMA_PREEXISTS:
        _run(drop())


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Start every test from an empty users table (tokens cascade)."""
    if not DB_AVAILABLE or DB_HAS_DATA:
        yield
        return

    async def truncate() -> None:
        async with SessionFactory() as session:
            await session.execute(text("TRUNCATE users CASCADE"))
            await session.commit()

    _run(truncate())
    yield


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
