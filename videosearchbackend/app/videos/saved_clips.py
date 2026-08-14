"""Saved clips: scenes kept from an import.

`SavedClip` rows are created automatically after a URL import that carried a
prompt: the import job runs the same CLIP search the search page uses and
persists the best scenes, so the library can show them without a manual
search. Deleting a video cascades to its clips (the FK on `video_id`).

Kept free of FastAPI types, matching the video service's style: these
functions raise domain errors and the route layer decides the HTTP status.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.videos.models import SavedClip

logger = logging.getLogger(__name__)


class SavedClipNotFound(Exception):
    """No such clip, or it belongs to someone else (same 404)."""


async def list_clips(
    db: AsyncSession,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
) -> list[SavedClip]:
    """All saved clips on one of the user's videos, oldest first.

    The caller is expected to have already verified the video belongs to the
    user — the query scopes on `owner_id` anyway, so a leaked video id can
    never leak another user's clips.
    """
    result = await db.execute(
        select(SavedClip)
        .where(SavedClip.owner_id == owner_id, SavedClip.video_id == video_id)
        .order_by(SavedClip.created_at.asc())
    )
    return list(result.scalars())


async def save_clips(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
    prompt: str,
    clips: list[dict],
) -> list[SavedClip]:
    """Persist `clips` (dicts with start/end/frame/score) as saved scenes.

    `clips` must already be plain dicts — SQLAlchemy's mapper cannot infer
    pydantic models here, and callers (the auto-extract job) pass
    ``item.model_dump()`` output.
    """
    rows = [
        SavedClip(
            owner_id=owner_id,
            video_id=video_id,
            prompt=prompt,
            start=clip["start"],
            end=clip["end"],
            frame=clip["timestamp"],
            score=clip["score"],
        )
        for clip in clips
    ]
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    logger.info("Saved %d clips on video %s", len(rows), video_id)
    return rows


async def delete_clip(
    db: AsyncSession,
    owner_id: uuid.UUID,
    clip_id: uuid.UUID,
) -> None:
    clip = await db.get(SavedClip, clip_id)
    if clip is None or clip.owner_id != owner_id:
        raise SavedClipNotFound(clip_id)
    await db.delete(clip)
    await db.commit()
    logger.info("Saved clip deleted: %s", clip_id)
