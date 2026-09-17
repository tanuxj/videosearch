"""Enforce the homepage trial's 30-minute deletion promise.

`apply_trial_expiry` (app.auth.guest) stamps every trial-created video with
`expires_at`; this module is the enforcement half. `purge_expired_trials`
sweeps for rows past their deadline and deletes each one through the same
`delete_video` service a user's own delete button calls — so the stored
object, frame vectors, transcript segments and saved clips all go with it,
in exactly the code path the rest of the app trusts. No bespoke deletion
logic here: the trial reuses the product's own.

`start_trial_purger` runs that sweep on a loop inside the API process. The
interval is deliberately slower than the TTL (minutes, not seconds): the
promise the UI makes is "deleted after 30 minutes", so a minute-scale drift
between deadline and actual deletion is honest, and a tight loop would spend
a connection on a query that is almost always empty. Failures are logged and
absorbed — a purge miss must never take the API down; the next sweep simply
catches up. Videos whose indexing was still running at their deadline are
purged mid-flight too: a trial that outlives its promise is exactly the
leak this exists to prevent.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.videos import service as videos_service
from app.videos.models import Video

logger = logging.getLogger(__name__)


async def purge_expired_trials() -> int:
    """Delete every video past its `expires_at`; return how many went.

    Each row is deleted through `videos_service.delete_video` so storage
    cleanup matches user-initiated deletes exactly. Rows are collected
    first, then deleted one by one on fresh loads: a video vanishing
    mid-sweep (a user beating the clock with their own delete, or the
    pipeline failing the row) must not abort the batch.
    """
    async with SessionFactory() as db:
        # Candidates: every row whose deadline has passed. The partial index
        # on expires_at keeps this a sliver-of-table read even as the videos
        # table grows; the second check below re-verifies per row so a video
        # stamped (or saved) between this select and its delete is never
        # purged early.
        now = datetime.now(UTC)
        result = await db.execute(
            select(Video.id).where(
                Video.expires_at.is_not(None), Video.expires_at <= now
            )
        )
        ids = list(result.scalars().all())

    purged = 0
    for video_id in ids:
        try:
            async with SessionFactory() as db:
                video = await db.get(Video, video_id)
                if video is None:
                    continue
                # Only rows actually past the deadline — the select above is
                # just the candidate set, so a video stamped between sweep and
                # delete keeps its full TTL.
                if not video.past_expiry():
                    continue
                await videos_service.delete_video(db, video.owner_id, video.id)
                purged += 1
        except Exception:  # noqa: BLE001 - one bad row must not stop the sweep
            logger.exception("Trial purge failed for video %s", video_id)
    return purged


async def _purge_loop() -> None:
    settings = get_settings()
    while True:
        try:
            count = await purge_expired_trials()
            if count:
                logger.info("Trial purge removed %d expired video(s)", count)
        except Exception:  # noqa: BLE001 - never let the loop die
            logger.exception("Trial purge sweep failed")
        await asyncio.sleep(settings.trial_purge_interval_seconds)


def start_trial_purger() -> asyncio.Task[None]:
    """Start the background purge loop. Call once from the app lifespan."""
    settings = get_settings()
    if not settings.trial_sessions_enabled:
        # Open-access deployments have no trial/full boundary, and nothing
        # stamps expiry — a purger would only be an idle timer.
        task = asyncio.create_task(asyncio.sleep(0))
        task.cancel()
        return task
    return asyncio.create_task(_purge_loop())
