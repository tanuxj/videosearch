"""Search-history business logic.

Kept free of FastAPI types, matching the video service's style: these
functions raise domain errors and the route layer decides the HTTP status.
"""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.models import SearchRecord

logger = logging.getLogger(__name__)


class SearchHistoryNotFound(Exception):
    """No such history record, or it belongs to someone else (same 404)."""


async def list_history(db: AsyncSession, owner_id: uuid.UUID) -> list[SearchRecord]:
    result = await db.execute(
        select(SearchRecord)
        .where(SearchRecord.owner_id == owner_id)
        .order_by(SearchRecord.created_at.desc())
    )
    return list(result.scalars())


async def create_history(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
    prompt: str,
    clips: list[dict],
    expanded: bool,
    min_score: float | None,
) -> SearchRecord:
    """Persist a search the user just ran.

    `clips` must already be plain dicts — SQLAlchemy's JSONB serializer
    cannot encode pydantic models.
    """
    record = SearchRecord(
        owner_id=owner_id,
        video_id=video_id,
        prompt=prompt,
        clips=clips,
        expanded=expanded,
        min_score=min_score,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("Search history recorded: %s (video=%s)", record.id, video_id)
    return record


async def delete_history(db: AsyncSession, owner_id: uuid.UUID, record_id: uuid.UUID) -> None:
    record = await db.get(SearchRecord, record_id)
    if record is None or record.owner_id != owner_id:
        raise SearchHistoryNotFound(record_id)
    await db.delete(record)
    await db.commit()
    logger.info("Search history deleted: %s", record_id)


async def clear_history(db: AsyncSession, owner_id: uuid.UUID) -> int:
    """Delete every search record for the user; returns how many were removed."""
    result = await db.execute(delete(SearchRecord).where(SearchRecord.owner_id == owner_id))
    await db.commit()
    count = result.rowcount or 0
    logger.info("Search history cleared for user %s (%d records)", owner_id, count)
    return count
