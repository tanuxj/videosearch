"""Signed playback URLs for the Cloudflare edge streaming Worker.

The Worker (`videosearchworker/src/index.ts`) serves an object only when the
request carries a valid HMAC-SHA256 signature over `"<key>:<expires>"`, so an
untrusted client cannot guess or replay a URL after it expires.

This module mints those signatures on the backend. Ownership is enforced at
mint time (`get_video` checks the owner), so the Worker itself does not need
the database.
"""

import hashlib
import hmac
import time

from app.core.config import get_settings

settings = get_settings()


def sign_stream_path(storage_key: str, secret: str, expires_at: int) -> str:
    """A signed worker path: `/stream/<key>?expires=..&sig=..`."""
    message = f"{storage_key}:{expires_at}"
    digest = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"/stream/{storage_key}?expires={expires_at}&sig={digest}"


def build_stream_url(storage_key: str) -> str | None:
    """The full signed edge URL for an object, or None when no Worker is set.

    None means the caller should fall back to proxying through the API, which
    keeps the app working before the Worker is deployed.
    """
    if not settings.stream_worker_base_url or not settings.stream_signing_secret:
        return None
    expires_at = int(time.time()) + settings.stream_url_ttl_seconds
    path = sign_stream_path(storage_key, settings.stream_signing_secret, expires_at)
    return f"{settings.stream_worker_base_url.rstrip('/')}{path}"
