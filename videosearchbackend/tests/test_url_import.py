"""Tests for URL import: validation, probing, downloading and the API route.

The unit tests (validation, probe, download) run without a database; the
route tests are skipped unless TEST_DATABASE_URL points at a reachable
Postgres (see tests/conftest.py). URL_IMPORT_ALLOW_PRIVATE is left at its
default (false) so the SSRF guard is exercised, except where a test
explicitly lifts it for a local fixture server.
"""

import http.server
import threading
from contextlib import suppress
from types import SimpleNamespace

import pytest

from app.videos import url_import
from app.videos.url_import import UrlImportError, download_video, probe_url, validate_url

# ── Fixture: a local HTTP server serving a fake MP4 ────────────


class _FakeVideoHandler(http.server.BaseHTTPRequestHandler):
    body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        # The probe closes early after reading headers — a broken pipe is
        # expected, not an error.
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(self.body)

    do_HEAD = do_GET

    def log_message(self, *args) -> None:  # pragma: no cover - silence noise
        pass


@pytest.fixture()
def media_server() -> str:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeVideoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/clip.mp4"
    server.shutdown()
    thread.join()


def _allow_private(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests point probes/downloads at a local server — lift the SSRF guard."""
    monkeypatch.setattr(
        url_import,
        "get_settings",
        lambda: SimpleNamespace(url_import_allow_private=True),
    )


def _no_ytdlp(*args, **kwargs):
    raise RuntimeError("yt-dlp unavailable in this test")


# ── validate_url ───────────────────────────────────────────────


def test_validate_url_rejects_non_http() -> None:
    for bad in ("ftp://example.com/video.mp4", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(UrlImportError, match="http"):
            validate_url(bad)


def test_validate_url_rejects_empty() -> None:
    with pytest.raises(UrlImportError):
        validate_url("   ")


def test_validate_url_rejects_private_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def _loopback_only(host, *args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(url_import.socket, "getaddrinfo", _loopback_only)
    with pytest.raises(UrlImportError, match="private or local"):
        validate_url("http://127.0.0.1:8080/video.mp4")


def test_validate_url_rejects_link_local_metadata_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def _metadata_host(host, *args, **kwargs):
        return [(2, 1, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(url_import.socket, "getaddrinfo", _metadata_host)
    with pytest.raises(UrlImportError, match="private or local"):
        validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_accepts_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def _public(host, *args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(url_import.socket, "getaddrinfo", _public)
    assert validate_url("  https://example.com/video.mp4  ") == "https://example.com/video.mp4"


def test_validate_url_allows_private_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_private(monkeypatch)
    assert validate_url("http://127.0.0.1:8080/video.mp4") == "http://127.0.0.1:8080/video.mp4"


# ── probe_url ──────────────────────────────────────────────────


def test_probe_direct_media(media_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_private(monkeypatch)
    # yt-dlp's generic extractor handles plain file URLs too, so force the
    # direct-probe fallback to exercise that branch deterministically.
    monkeypatch.setattr(url_import, "_probe_with_ytdlp", _no_ytdlp)
    info = probe_url(media_server, max_bytes=10 * 1024**3)
    assert info["ext"] == "mp4"
    assert info["title"] == "clip.mp4"
    assert info["duration"] is None
    assert info["size"] == len(_FakeVideoHandler.body)


def test_probe_rejects_audio_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_dlp

    class _AudioOnly:
        def __init__(self, opts) -> None:
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extract_info(self, url, download=False):
            return {"title": "Podcast", "ext": "m4a", "vcodec": "none"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _AudioOnly)
    with pytest.raises(UrlImportError, match="audio-only"):
        probe_url("https://example.com/podcast", max_bytes=1000)


def test_probe_rejects_live_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_dlp

    class _Live:
        def __init__(self, opts) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extract_info(self, url, download=False):
            return {"title": "Live now", "ext": "mp4", "is_live": True}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _Live)
    with pytest.raises(UrlImportError, match="Live streams"):
        probe_url("https://twitch.tv/someone", max_bytes=1000)


def test_probe_rejects_oversize_from_filesize(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_dlp

    class _Big:
        def __init__(self, opts) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extract_info(self, url, download=False):
            return {"title": "Big", "ext": "mp4", "filesize_approx": 9999}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _Big)
    with pytest.raises(UrlImportError, match="larger than"):
        probe_url("https://example.com/big", max_bytes=64)


# ── download_video ─────────────────────────────────────────────


def test_download_direct_file(media_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _allow_private(monkeypatch)
    monkeypatch.setattr(url_import, "_download_with_ytdlp", _no_ytdlp)

    path, title, ext = download_video(
        media_server,
        tmp_path,
        max_bytes=10 * 1024**3,
        format_spec="b[ext=mp4]/b",
    )
    assert path.read_bytes() == _FakeVideoHandler.body
    assert ext == "mp4"
    assert title == "video"


def test_download_enforces_size_cap(
    media_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _allow_private(monkeypatch)
    monkeypatch.setattr(url_import, "_download_with_ytdlp", _no_ytdlp)

    with pytest.raises(UrlImportError, match="larger than"):
        download_video(media_server, tmp_path, max_bytes=64, format_spec="b[ext=mp4]/b")
    # No partial file is left behind.
    assert list(tmp_path.iterdir()) == []


# ── API route (needs a database) ───────────────────────────────

from tests.conftest import needs_db  # noqa: E402

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}


class TestFromUrlApi:
    """Route tests — skipped unless a test database is configured."""

    pytestmark = needs_db

    @staticmethod
    def _auth_headers(client) -> dict[str, str]:
        response = client.post("/api/v1/auth/signup", json=SIGNUP)
        assert response.status_code == 201, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_from_url_requires_auth(self, client) -> None:
        response = client.post(
            "/api/v1/videos/from-url", json={"url": "https://example.com/video.mp4"}
        )
        assert response.status_code == 401

    def test_from_url_rejects_non_http(self, client) -> None:
        headers = self._auth_headers(client)
        response = client.post(
            "/api/v1/videos/from-url",
            headers=headers,
            json={"url": "ftp://example.com/v.mp4"},
        )
        assert response.status_code == 422

    def test_from_url_rejects_private_host(self, client) -> None:
        headers = self._auth_headers(client)
        response = client.post(
            "/api/v1/videos/from-url",
            headers=headers,
            json={"url": "http://127.0.0.1:9/v.mp4"},
        )
        assert response.status_code == 422
        assert "private or local" in response.json()["detail"]

    def test_from_url_reserves_video_and_enqueues_import(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.videos import url_import

        # No network in tests: the probe is faked and validation just passes.
        monkeypatch.setattr(url_import, "validate_url", lambda raw: raw.strip())
        monkeypatch.setattr(
            url_import,
            "probe_url",
            lambda url, *, max_bytes: {
                "title": "Big Buck Bunny",
                "ext": "mp4",
                "duration": 600,
                "size": 1234,
            },
        )
        started: list[tuple] = []
        monkeypatch.setattr(
            url_import,
            "import_video",
            lambda video_id, url: started.append((video_id, url)),
        )

        headers = self._auth_headers(client)
        response = client.post(
            "/api/v1/videos/from-url",
            headers=headers,
            json={"url": "https://example.com/big-buck-bunny.mp4"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "processing"
        assert body["name"] == "Big Buck Bunny.mp4"
        assert body["size_bytes"] == 0
        assert "storage_key" not in body

        # The row is listed like any other video, and the background import
        # job was handed (video_id, url) — TestClient flushes background
        # tasks after the response.
        listing = client.get("/api/v1/videos", headers=headers).json()
        assert [item["id"] for item in listing["items"]] == [body["id"]]
        assert [(str(v), u) for v, u in started] == [
            (body["id"], "https://example.com/big-buck-bunny.mp4")
        ]

    def test_from_url_409_when_disabled(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.videos import routes

        monkeypatch.setattr(routes.settings, "url_import_enabled", False)
        headers = self._auth_headers(client)
        response = client.post(
            "/api/v1/videos/from-url",
            headers=headers,
            json={"url": "https://example.com/v.mp4"},
        )
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"]
