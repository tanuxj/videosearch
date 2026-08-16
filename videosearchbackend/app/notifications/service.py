"""Notification business logic: record, list, mark read.

The create path is called from the indexing pipeline
(``app/videos/pipeline.py``) after a video settles on ``status == "ready"``;
everything else serves the frontend's bell (``GET /api/v1/notifications``
plus the two mark-read routes).
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification
from app.videos.models import Video

# How many notifications the bell lists at once; older ones age out of the
# response (they still exist in the DB until the video/account is deleted).
LIST_LIMIT = 50


async def create_notification(
    db: AsyncSession, *, user_id: uuid.UUID, video_id: uuid.UUID, kind: str = "indexed"
) -> None:
    """Record one event for one user — idempotent per (user, video, kind).

    Indexing can settle a video more than once (the audio-only shortcut, a
    re-run); the unique index turns repeats into a swallowed IntegrityError
    rather than a second ring of the bell. Runs its own commit so the caller
    (the pipeline) can't lose the video's ``ready`` status if this write
    fails — a missing notification is cosmetic, a stuck video is not.
    """
    db.add(Notification(user_id=user_id, video_id=video_id, kind=kind))
    try:
        await db.commit()
    except IntegrityError:
        # Already notified for this event — not an error.
        await db.rollback()


async def list_notifications(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = LIST_LIMIT
) -> list[tuple[Notification, str]]:
    """The user's notifications, newest first, with their video's name.

    The join to ``videos`` gives the bell the title to display without the
    frontend having to resolve ids against its own (possibly unfetched) list.
    """
    result = await db.execute(
        select(Notification, Video.name)
        .join(Video, Video.id == Notification.video_id)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """How many notifications are still unread — the bell's badge."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read.is_(False))
        )
        or 0
    )


async def mark_read(
    db: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification | None:
    """Mark one notification read; None when it isn't the caller's.

    The id filter keeps the lookup scoped to the caller, so a leaked id can
    never confirm someone else's notification exists — the route turns the
    None into a 404.
    """
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        return None
    notification.read = True
    await db.commit()
    return notification


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Mark everything read; returns how many rows flipped."""
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read.is_(False))
        .values(read=True)
    )
    await db.commit()
    return result.rowcount or 0
