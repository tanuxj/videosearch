"""URL import: index a video from a pasted link.

Flow behind ``POST /videos/from-url`` and ``POST /videos/from-urls``:

    validate_url()     scheme + SSRF guard (private hosts refused)
    expand_playlist()  resolve a playlist/channel link into its videos
    probe_url()        yt-dlp extract_info(download=False) → title, ext,
                       duration, size; falls back to a plain HTTP probe for
                       direct file links
    create_url_video() reserves a `processing` row with the right key ext
    import_video()     background task: download → save to storage → run the
                       normal indexing pipeline → (optional) auto-save the
                       best scenes matching the import's prompt as clips

Download strategy:

* **yt-dlp first.** Handles YouTube, Twitch, Zoom (public recordings), Vimeo
  and ~1700 other sites, and prefers a single progressive MP4 so the result
  plays in browsers without an ffmpeg merge step.
* **Direct HTTP fallback.** When yt-dlp fails (or the link is a plain media
  file), stream the bytes ourselves with a hard size cap.

Safety:

* Only ``http(s)`` links, and the host must resolve to a public address — the
  backend must never be coaxed into fetching internal services (SSRF).
  ``URL_IMPORT_ALLOW_PRIVATE=true`` lifts that for tests, which point imports
  at a local fixture server.
* Every download enforces the configured byte cap, both up front (from the
  probe's reported size) and during the transfer.
"""

import asyncio
import ipaddress
import logging
import shutil
import socket
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.videos import pipeline, search, service
from app.videos.models import Video
from app.videos.saved_clips import save_clips
from app.videos.storage import storage

logger = logging.getLogger(__name__)

# A browser-ish user agent: several hosts (YouTube CDNs, some plain file
# servers) refuse the default urllib UA.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DIRECT_EXT_BY_TYPE = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "video/x-m4v": "m4v",
}


class UrlImportError(Exception):
    """The URL is invalid, unreachable, or not a video we can index."""


class _AbortDownload(Exception):
    """Internal: a download crossed the size cap; yt-dlp aborts the transfer."""


def _human_bytes(n: int) -> str:
    value = n / (1024**3)
    if value >= 1:
        return f"{value:g} GiB"
    return f"{n / (1024**2):g} MiB"


def _brief(exc: Exception) -> str:
    return str(exc)[:300]


# ── Validation + SSRF guard ──────────────────────────────────


def validate_url(raw: str) -> str:
    """Normalise and sanity-check a pasted link; raise ``UrlImportError``.

    Enforces http(s) and, unless ``url_import_allow_private`` is set, refuses
    hosts that resolve to a non-public address. Returns the trimmed URL.
    """
    url = raw.strip()
    if not url:
        raise UrlImportError("Paste a video link to index it.")
    if len(url) > 2048:
        raise UrlImportError("That link is too long to be a video URL.")

    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise UrlImportError("That doesn't look like a valid URL.") from exc

    if parsed.scheme not in ("http", "https"):
        raise UrlImportError("Only http:// and https:// video links are supported.")
    if not parsed.hostname:
        raise UrlImportError("That URL has no host.")

    if not get_settings().url_import_allow_private:
        _reject_private_host(parsed.hostname)
    return url


def _reject_private_host(hostname: str) -> None:
    """Refuse hosts that resolve to a private/loopback/link-local address.

    A server that fetches arbitrary URLs is a free SSRF gadget: a user could
    point it at 127.0.0.1, 169.254.169.254 (cloud metadata) or an internal
    service. Any non-global address is refused, not just loopback.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UrlImportError("That link's host can't be reached.") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise UrlImportError(
                "That link points at a private or local address, which this server won't fetch."
            )


# ── Metadata probe ───────────────────────────────────────────


def probe_url(url: str, *, max_bytes: int) -> dict:
    """Learn title/extension/duration/size of a link without downloading it.

    Tries yt-dlp first (site extractors), then a plain HTTP probe for direct
    media files. Raises ``UrlImportError`` when neither can read it as a
    video. Runs in a worker thread (network I/O); the route caps it with a
    timeout.
    """
    try:
        return _probe_with_ytdlp(url, max_bytes=max_bytes)
    except UrlImportError:
        raise
    except Exception as exc:  # noqa: BLE001 - any extractor failure → fallback
        logger.info("yt-dlp probe failed for %s: %s", url, _brief(exc))
        direct = _probe_direct(url)
        if direct is not None:
            return direct
        raise UrlImportError(
            "Couldn't read that link as a video. Make sure it points at a "
            "watchable video (or a direct .mp4/.webm file)."
        ) from exc


def _probe_with_ytdlp(url: str, *, max_bytes: int) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }
    ) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise UrlImportError("That link didn't resolve to a video.")
    if info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise UrlImportError("That link is a playlist with no videos.")
        info = entries[0]
    if info.get("is_live"):
        raise UrlImportError("Live streams can't be indexed — they have no end.")
    if info.get("vcodec") == "none":
        raise UrlImportError("That link is audio-only — there's no video to index.")

    size = info.get("filesize") or info.get("filesize_approx")
    if size and size > max_bytes:
        raise UrlImportError(
            f"That video is larger than the {_human_bytes(max_bytes)} import limit."
        )

    return {
        "title": str(info.get("title") or ""),
        "ext": str(info.get("ext") or _ext_from_url(url)),
        "duration": info.get("duration"),
        "size": size,
    }


def _probe_direct(url: str) -> dict | None:
    """Probe a plain file URL: content type + size via a ranged GET.

    Returns None when the server refuses or the response isn't media. A
    ``Range: bytes=0-0`` request keeps the transfer to a single byte on
    servers that honour ranges; on those that don't, we just close after
    reading the headers.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if not content_type.startswith(("video/", "application/octet-stream")):
                return None
            ext = _DIRECT_EXT_BY_TYPE.get(content_type) or _ext_from_url(resp.geturl())
            size: int | None = None
            content_range = resp.headers.get("Content-Range", "")
            if "/" in content_range:
                try:
                    size = int(content_range.rsplit("/", 1)[1])
                except ValueError:
                    size = None
            if size is None and resp.headers.get("Content-Length", "").isdigit():
                size = int(resp.headers["Content-Length"])
    except Exception:  # noqa: BLE001 - unreachable/non-HTTP: caller decides
        return None

    title = Path(urllib.parse.urlparse(url).path).name or "video"
    return {"title": title, "ext": ext, "duration": None, "size": size}


def _ext_from_url(url: str) -> str:
    ext = Path(urllib.parse.urlparse(url).path).suffix.lstrip(".").lower()
    return ext if ext else "mp4"


def expand_playlist(url: str, max_entries: int = 50) -> list[str]:
    """Resolve a playlist/channel link into its individual video URLs.

    Uses yt-dlp's flat extraction (metadata only, no media downloaded), so a
    channel or playlist URL turns into the list of videos inside it — capped
    at `max_entries` to keep huge channels bounded. Anything else (a plain
    video link, a direct file URL, or a link yt-dlp can't expand) returns
    ``[url]``: the caller then treats it as a single video, and the normal
    probe reports any real error. Never raises.
    """
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": False,
                "extract_flat": True,
                "playlistend": max(1, max_entries),
                "skip_download": True,
            }
        ) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:  # noqa: BLE001 - unreadable link → treat as a single video
        return [url]

    if info is None or info.get("_type") != "playlist":
        return [url]
    entries = [entry for entry in (info.get("entries") or []) if entry]
    if not entries:
        return [url]
    urls = []
    for entry in entries:
        candidate = str(entry.get("webpage_url") or entry.get("url") or url)
        if candidate.startswith(("http://", "https://")):
            urls.append(candidate)
    return urls[: max(1, max_entries)] or [url]


# ── Download ─────────────────────────────────────────────────


def download_video(
    url: str,
    dest_dir: Path,
    *,
    max_bytes: int,
    format_spec: str,
) -> tuple[Path, str, str]:
    """Download `url` into `dest_dir`; return `(path, title, ext)`.

    yt-dlp first; falls back to a direct HTTP download when the extractor
    fails. A size-limit breach raises ``UrlImportError`` either way — the
    fallback is not attempted then, because it would hit the same cap.
    """
    try:
        return _download_with_ytdlp(url, dest_dir, max_bytes=max_bytes, format_spec=format_spec)
    except UrlImportError:
        raise
    except Exception as exc:  # noqa: BLE001 - extractor/download failure → fallback
        logger.info("yt-dlp download failed for %s: %s", url, _brief(exc))
        shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        direct = _download_direct(url, dest_dir, max_bytes=max_bytes)
        if direct is None:
            raise UrlImportError(
                "Couldn't download that link as a video. It may be private, "
                "geo-blocked, or behind a login — try a direct .mp4/.webm URL."
            ) from exc
        return direct


def _download_with_ytdlp(
    url: str,
    dest_dir: Path,
    *,
    max_bytes: int,
    format_spec: str,
) -> tuple[Path, str, str]:
    import yt_dlp

    over_limit = {"hit": False}

    def _hook(status: dict) -> None:
        if status.get("status") != "downloading":
            return
        downloaded = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        if downloaded > max_bytes or (total and total > max_bytes):
            # The flag is checked after the download call because yt-dlp may
            # wrap the hook's exception (DownloadError), which is not
            # reliably distinguishable by type.
            over_limit["hit"] = True
            raise _AbortDownload()

    opts = {
        "outtmpl": str(dest_dir / "%(title).120s [%(id)s].%(ext)s"),
        # Prefer a single progressive MP4: plays in browsers with no ffmpeg
        # merge step. `b` (any single file) is the fallback.
        "format": format_spec,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "progress_hooks": [_hook],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
        except Exception:
            if over_limit["hit"]:
                raise UrlImportError(
                    f"That video is larger than the {_human_bytes(max_bytes)} import limit."
                ) from None
            raise

    files = [
        path
        for path in dest_dir.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not files:
        raise UrlImportError("The download produced no video file.")
    path = files[0]
    ext = path.suffix.lstrip(".").lower() or "mp4"
    return path, path.stem, ext


def _download_direct(url: str, dest_dir: Path, *, max_bytes: int) -> tuple[Path, str, str] | None:
    """Stream a plain media file into `dest_dir` with a hard size cap."""
    info = _probe_direct(url)
    if info is None:
        return None
    ext = info["ext"] or "mp4"
    dest = dest_dir / f"video.{ext}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as resp, dest.open("wb") as out:
            total = 0
            while chunk := resp.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise UrlImportError(
                        f"That video is larger than the {_human_bytes(max_bytes)} import limit."
                    )
                out.write(chunk)
    except UrlImportError:
        dest.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001 - transfer failed → caller surfaces the error
        dest.unlink(missing_ok=True)
        return None
    return dest, dest.stem, ext


# ── Background import task ───────────────────────────────────


async def import_video(
    video_id: uuid.UUID,
    url: str,
    *,
    prompt: str | None = None,
    clip_limit: int = 0,
) -> None:
    """Download a pasted URL, store it, then run the normal pipeline.

    Mirrors the upload flow: the file lands in the same storage the video row
    already points at, then ``pipeline.index_video`` extracts and embeds
    frames. When `prompt` is set (and `clip_limit` > 0), the best matching
    scenes are auto-saved as clips once indexing finishes. Any failure before
    indexing marks the video ``failed`` with a readable message instead of
    leaving it stuck in ``processing``.
    """
    path: Path | None = None
    tmp_dir: Path | None = None
    try:
        path, tmp_dir = await _download_and_store(video_id, url)
        # `source_path` transfers ownership: the pipeline deletes it when
        # done (or fails), exactly like a staged upload.
        await pipeline.index_video(video_id, source_path=path)
        if prompt and clip_limit > 0:
            await _autoextract_clips(video_id, prompt, clip_limit)
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded
        logger.exception("URL import failed for video %s", video_id)
        if path is not None:
            path.unlink(missing_ok=True)
        await _mark_failed(video_id, str(exc))
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _autoextract_clips(video_id: uuid.UUID, prompt: str, limit: int) -> None:
    """Run a search on the freshly indexed video and keep the best scenes.

    Uses the exact same ranking as the search page (``run_clip_search``), so
    an auto-saved clip is what a manual search would have surfaced. Best-
    effort: any failure here — an LLM hiccup, an embedding error — must not
    fail the import; the video itself indexed fine and stays searchable.
    """
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None or video.status != "ready":
                return
            result = await search.run_clip_search(
                db,
                video_id,
                prompt,
                limit=limit,
                duration_seconds=video.duration_seconds,
            )
            if not result.items:
                logger.info("Auto-extract found no scene matching %r on video %s", prompt, video_id)
                return
            saved = await save_clips(
                db,
                owner_id=video.owner_id,
                video_id=video_id,
                prompt=prompt,
                clips=[item.model_dump() for item in result.items],
            )
            logger.info("Auto-extracted %d clips for video %s", len(saved), video_id)
    except Exception:  # noqa: BLE001 - best effort; the video stays indexed
        logger.exception("Auto-extract failed for video %s — the video stays indexed", video_id)


async def _download_and_store(video_id: uuid.UUID, url: str) -> tuple[Path, Path]:
    """Download `url` to a temp dir and persist it under the video's key.

    Returns ``(local_path, temp_dir)`` — the caller hands `local_path` to the
    pipeline (which deletes it) and owns cleaning up `temp_dir`.
    """
    settings = get_settings()
    tmp_dir = Path(tempfile.mkdtemp(prefix="videosearch-url-"))
    try:
        path, title, ext = await asyncio.to_thread(
            download_video,
            url,
            tmp_dir,
            max_bytes=settings.url_import_max_bytes,
            format_spec=settings.url_import_format,
        )
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    async with SessionFactory() as db:
        video = await db.get(Video, video_id)
        if video is None or video.status != "processing":
            raise UrlImportError("This video is no longer being imported.")

        # The container can differ from the probe's guess (e.g. a site that
        # serves HLS as .ts). Nothing is stored under the old key yet, so
        # correcting it here is safe and keeps streaming types right. The key
        # keeps its random component — only the extension changes.
        ext = (ext or "mp4").lower().lstrip(".") or "mp4"
        if f".{ext}" != Path(video.storage_key).suffix.lower():
            video.storage_key = str(Path(video.storage_key).with_suffix(f".{ext}"))

        content_type = service.MEDIA_TYPES.get(f".{ext}", "video/mp4")
        await asyncio.to_thread(storage.save_path, video.storage_key, path, content_type)
        video.name = service.display_name(title, ext)
        video.size_bytes = path.stat().st_size
        await db.commit()
        logger.info(
            "URL import stored video %s: %s (%d bytes)",
            video.id,
            video.name,
            video.size_bytes,
        )
    return path, tmp_dir


async def _mark_failed(video_id: uuid.UUID, message: str) -> None:
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is not None and video.status == "processing":
                video.status = "failed"
                video.error = message[:500]
                await db.commit()
    except Exception:  # pragma: no cover - best effort
        logger.exception("Could not mark video %s as failed", video_id)
