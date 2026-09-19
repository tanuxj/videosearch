"""`Video.processing_seconds` — the "processed in 2m 14s" reading.

Pure unit tests on the property, no database: the three states it can be in
are what the UI branches on, and each has to stay distinguishable.
"""

from datetime import UTC, datetime, timedelta

from app.videos.models import Video


def _video(started: datetime | None, completed: datetime | None) -> Video:
    return Video(processing_started_at=started, processing_completed_at=completed)


def test_none_before_indexing_starts() -> None:
    assert _video(None, None).processing_seconds is None


def test_none_while_still_running() -> None:
    """Started but not finished is None, not "now minus start".

    The client shows a live counter for this case and nothing at all for a
    video that predates the timing columns — collapsing the two into one
    value would make those indistinguishable.
    """
    assert _video(datetime.now(UTC), None).processing_seconds is None


def test_none_when_only_a_completion_was_recorded() -> None:
    """Half a pair is not a duration — a completion with no start is unusable."""
    assert _video(None, datetime.now(UTC)).processing_seconds is None


def test_elapsed_once_both_are_stamped() -> None:
    started = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    video = _video(started, started + timedelta(minutes=2, seconds=14))
    assert video.processing_seconds == 134.0


def test_sub_second_precision_is_kept() -> None:
    """A short video's duration must not round away to 0."""
    started = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    video = _video(started, started + timedelta(milliseconds=750))
    assert video.processing_seconds == 0.75
