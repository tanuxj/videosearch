"""Background reconciliation for direct-to-storage uploads.

A browser that uploads straight to R2 and then dies — closed tab, lost
network, crashed — never calls `POST /videos/{id}/complete`. Its row would sit
`pending` forever with a perfectly good file behind it.

This sweep asks storage instead of the client, which settles it either way:
object present means the upload landed (promote and index), absent means it
never happened (drop the row). `complete` therefore only buys latency; this is
what makes the flow correct.
"""

import asyncio
import contextlib
import logging

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.videos import pipeline
from app.videos import service as videos_service

logger = logging.getLogger(__name__)
settings = get_settings()


async def sweep_once() -> tuple[int, int]:
    """Run one reconcile pass. Returns (promoted, discarded)."""
    async with SessionFactory() as session:
        promoted, discarded = await videos_service.sweep_pending_uploads(session)

    # Index outside the session that promoted them: each job opens its own.
    for video_id in promoted:
        if settings.index_on_upload:
            asyncio.create_task(pipeline.index_video(video_id))

    return len(promoted), discarded


async def sweeper_loop(stop: asyncio.Event) -> None:
    """Sweep on an interval until `stop` is set."""
    interval = settings.pending_sweep_interval_minutes * 60
    logger.info("Pending-upload sweeper running every %d min", interval // 60)

    while not stop.is_set():
        # Waiting on the event (rather than sleeping) makes shutdown immediate.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
        if stop.is_set():
            return
        try:
            promoted, discarded = await sweep_once()
            if promoted or discarded:
                logger.info("Pending-upload sweep: %d promoted, %d discarded", promoted, discarded)
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("Pending-upload sweep failed; will retry next interval")
