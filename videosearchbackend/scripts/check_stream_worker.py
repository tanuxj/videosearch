"""Health-check the Cloudflare streaming Worker end to end.

Answers "is the deployed Worker actually working?" without hand-computing
HMACs. It signs URLs with the backend's own `STREAM_SIGNING_SECRET`, so a
passing run also proves the Worker's `STREAM_SIGN_SECRET` matches.

    uv run python scripts/check_stream_worker.py
    uv run python scripts/check_stream_worker.py --key <owner>/<file>.mp4

With no --key it picks the newest `ready` video from the database. Checks that
need a real object are skipped if there is nothing to stream.

Reading the results:

* 403 on an unsigned/expired/tampered URL — signature enforcement works.
* 404 (not 403) on a correctly signed but missing key — the secrets match and
  the Worker reached R2. **403 here means the secrets differ**; re-run
  `npx wrangler secret put STREAM_SIGN_SECRET` with the backend's value.
* 206 + Content-Range on a Range request — `<video>` seeking works.
"""

import argparse
import asyncio
import sys
import time
import urllib.error
import urllib.request

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionFactory, engine
from app.videos.models import Video
from app.videos.streaming import sign_stream_path

settings = get_settings()

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    icon = {PASS: "[ok]", FAIL: "[!!]", SKIP: "[--]"}[status]
    print(f"  {icon} {name}{f' — {detail}' if detail else ''}")


# Cloudflare's browser-integrity check blocks the default `Python-urllib/x.y`
# agent at the edge with `403 error code: 1010` — before the request reaches
# the Worker. That looks exactly like a signature rejection, so send a normal
# User-Agent and never debug this Worker with a default Python client.
USER_AGENT = "Mozilla/5.0 (compatible; VideoSearch-HealthCheck/1.0)"


def fetch(url: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    """Return (status, headers, body_length). Never raises on an HTTP error."""
    request = urllib.request.Request(
        url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read() if method == "GET" else b""
            return response.status, dict(response.headers), len(body)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), 0
    except urllib.error.URLError as error:
        print(f"     network error: {error.reason}")
        return 0, {}, 0


def signed(key: str, ttl: int = 300) -> str:
    base = (settings.stream_worker_base_url or "").rstrip("/")
    return base + sign_stream_path(key, settings.stream_signing_secret, int(time.time()) + ttl)


async def newest_ready_key() -> tuple[str, int] | None:
    async with SessionFactory() as session:
        result = await session.execute(
            select(Video.storage_key, Video.size_bytes)
            .where(Video.status == "ready")
            .order_by(Video.created_at.desc())
            .limit(1)
        )
        row = result.first()
    await engine.dispose()
    return (row[0], row[1]) if row else None


def check_configuration() -> bool:
    print("Configuration")
    if not settings.stream_worker_base_url:
        record(FAIL, "STREAM_WORKER_BASE_URL set", "empty — the API will stream bytes itself")
        return False
    record(PASS, "STREAM_WORKER_BASE_URL", settings.stream_worker_base_url)

    if not settings.stream_signing_secret:
        record(FAIL, "STREAM_SIGNING_SECRET set", "empty — cannot mint signed URLs")
        return False
    record(PASS, "STREAM_SIGNING_SECRET", f"{len(settings.stream_signing_secret)} chars")
    return True


def check_rejections(base: str) -> None:
    print("\nSignature enforcement (all of these must be refused)")
    probe = "no-such-owner/no-such-video.mp4"

    status, _, _ = fetch(f"{base}/stream/{probe}")
    record(PASS if status == 403 else FAIL, "unsigned request rejected", f"HTTP {status}")

    status, _, _ = fetch(f"{base}/stream/{probe}?expires=99999999999&sig=deadbeef")
    record(PASS if status == 403 else FAIL, "bad signature rejected", f"HTTP {status}")

    expired = base + sign_stream_path(probe, settings.stream_signing_secret, int(time.time()) - 60)
    status, _, _ = fetch(expired)
    record(PASS if status == 403 else FAIL, "expired signature rejected", f"HTTP {status}")

    # A signature is bound to its key, so moving it to another path must fail.
    other = sign_stream_path("other/key.mp4", settings.stream_signing_secret, int(time.time()) + 300)
    tampered = f"{base}/stream/{probe}?{other.split('?', 1)[1]}"
    status, _, _ = fetch(tampered)
    record(PASS if status == 403 else FAIL, "signature bound to its key", f"HTTP {status}")


def check_secret_and_binding() -> None:
    print("\nShared secret and R2 binding")
    status, _, _ = fetch(signed("no-such-owner/no-such-video.mp4"))
    if status == 404:
        record(PASS, "valid signature accepted, R2 reached", "HTTP 404 for a missing object")
    elif status == 403:
        record(FAIL, "valid signature REJECTED", "Worker secret != backend STREAM_SIGNING_SECRET")
    else:
        record(FAIL, "unexpected response", f"HTTP {status}")


def check_streaming(key: str, size: int) -> None:
    print(f"\nStreaming a real object ({key.split('/')[-1]}, {size:,} bytes)")
    url = signed(key)

    status, headers, _ = fetch(url, method="HEAD")
    served = int(headers.get("Content-Length", 0) or 0)
    record(
        PASS if status == 200 and served == size else FAIL,
        "HEAD returns the whole object",
        f"HTTP {status}, Content-Length {served:,}",
    )
    record(
        PASS if headers.get("Accept-Ranges") == "bytes" else FAIL,
        "Accept-Ranges: bytes advertised",
        headers.get("Accept-Ranges", "missing"),
    )

    window = min(102_400, max(size - 1, 1))
    status, headers, length = fetch(url, headers={"Range": f"bytes=0-{window - 1}"})
    expected = f"bytes 0-{window - 1}/{size}"
    ok = status == 206 and headers.get("Content-Range") == expected and length == window
    record(ok and PASS or FAIL, "Range request seeks (206)", f"HTTP {status}, {length:,} bytes")

    if size > 1_000_000:
        offset = size // 2
        status, headers, length = fetch(url, headers={"Range": f"bytes={offset}-{offset + 99}"})
        ok = status == 206 and length == 100
        record(ok and PASS or FAIL, "mid-file seek", headers.get("Content-Range", f"HTTP {status}"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", help="Object key to stream, instead of the newest ready video")
    args = parser.parse_args()

    print(f"Checking {settings.stream_worker_base_url or '(not configured)'}\n")

    if not check_configuration():
        return 1

    base = settings.stream_worker_base_url.rstrip("/")
    check_rejections(base)
    check_secret_and_binding()

    if args.key:
        target: tuple[str, int] | None = (args.key, 0)
    else:
        try:
            target = asyncio.run(newest_ready_key())
        except Exception as exc:
            print(f"\n  (could not reach the database: {exc})")
            target = None

    if target is None:
        print("\nStreaming a real object")
        record(SKIP, "no ready video found", "upload one, or pass --key")
    else:
        key, size = target
        if size == 0:  # --key given: ask the Worker how big it is
            _, headers, _ = fetch(signed(key), method="HEAD")
            size = int(headers.get("Content-Length", 0) or 0)
        check_streaming(key, size)

    failures = [name for status, name, _ in _results if status == FAIL]
    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {', '.join(failures)}")
        return 1
    skipped = sum(1 for status, _, _ in _results if status == SKIP)
    print(f"All checks passed{f' ({skipped} skipped)' if skipped else ''}. The Worker is serving.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
