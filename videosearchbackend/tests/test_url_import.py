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


# ── expand_playlist ───────────────────────────────────────────


class _FakeYtDlp:
    """Stands in for yt_dlp.YoutubeDL with a canned `extract_info` result."""

    def __init__(self, info=None, *, raises: Exception | None = None) -> None:
        self._info = info
        self._raises = raises

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def extract_info(self, url, download=False):
        if self._raises is not None:
            raise self._raises
        return self._info


def _stub_ytdlp(monkeypatch: pytest.MonkeyPatch, fake: _FakeYtDlp) -> None:
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", lambda opts: fake)


def test_expand_playlist_returns_entry_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_ytdlp(
        monkeypatch,
        _FakeYtDlp(
            {
                "_type": "playlist",
                "entries": [
                    {"webpage_url": "https://youtube.com/watch?v=one"},
                    {"webpage_url": "https://youtube.com/watch?v=two"},
                ],
            }
        ),
    )
    assert url_import.expand_playlist("https://youtube.com/playlist?list=x") == [
        "https://youtube.com/watch?v=one",
        "https://youtube.com/watch?v=two",
    ]


def test_expand_playlist_caps_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_ytdlp(
        monkeypatch,
        _FakeYtDlp(
            {
                "_type": "playlist",
                "entries": [{"webpage_url": f"https://youtube.com/watch?v={i}"} for i in range(10)],
            }
        ),
    )
    assert len(url_import.expand_playlist("https://youtube.com/playlist?list=x", 3)) == 3


def test_expand_playlist_single_video_returns_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_ytdlp(
        monkeypatch,
        _FakeYtDlp({"_type": "video", "webpage_url": "https://youtube.com/watch?v=x"}),
    )
    assert url_import.expand_playlist("https://youtube.com/watch?v=x") == [
        "https://youtube.com/watch?v=x"
    ]


def test_expand_playlist_failure_falls_back_to_single(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_ytdlp(monkeypatch, _FakeYtDlp(raises=RuntimeError("boom")))
    assert url_import.expand_playlist("https://example.com/v.mp4") == ["https://example.com/v.mp4"]


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
            lambda video_id, url, *, prompt=None, clip_limit=0: started.append(
                (video_id, url, prompt, clip_limit)
            ),
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
        # job was handed (video_id, url) with no auto-extract prompt —
        # TestClient flushes background tasks after the response.
        listing = client.get("/api/v1/videos", headers=headers).json()
        assert [item["id"] for item in listing["items"]] == [body["id"]]
        assert [(str(v), u, p, c) for v, u, p, c in started] == [
            (body["id"], "https://example.com/big-buck-bunny.mp4", None, 0)
        ]

    def test_from_url_forwards_prompt_to_autoextract(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.videos import url_import

        monkeypatch.setattr(url_import, "validate_url", lambda raw: raw.strip())
        monkeypatch.setattr(
            url_import,
            "probe_url",
            lambda url, *, max_bytes: {
                "title": "Car chase",
                "ext": "mp4",
                "duration": 60,
                "size": 1234,
            },
        )
        started: list[tuple] = []
        monkeypatch.setattr(
            url_import,
            "import_video",
            lambda video_id, url, *, prompt=None, clip_limit=0: started.append(
                (video_id, prompt, clip_limit)
            ),
        )

        headers = self._auth_headers(client)
        response = client.post(
            "/api/v1/videos/from-url",
            headers=headers,
            json={
                "url": "https://example.com/chase.mp4",
                "prompt": "a red car driving on a highway",
                "clip_limit": 5,
            },
        )
        assert response.status_code == 201, response.text
        video_id, prompt, clip_limit = started[0]
        assert prompt == "a red car driving on a highway"
        assert clip_limit == 5

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


class TestFromUrlsApi:
    """Batch-import route tests — skipped unless a test database is configured."""

    pytestmark = needs_db

    @staticmethod
    def _auth_headers(client) -> dict[str, str]:
        response = client.post("/api/v1/auth/signup", json=SIGNUP)
        assert response.status_code == 201, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    @staticmethod
    def _patch_imports(monkeypatch: pytest.MonkeyPatch, started: list) -> None:
        """Fake the network: validation passes, playlists stay single, probe is
        instant, and the background job is captured instead of run."""
        monkeypatch.setattr(url_import, "validate_url", lambda raw: raw.strip())
        monkeypatch.setattr(url_import, "expand_playlist", lambda url, max_entries=50: [url])
        monkeypatch.setattr(
            url_import,
            "probe_url",
            lambda url, *, max_bytes: {
                "title": f"Video {url.rsplit('/', 1)[-1]}",
                "ext": "mp4",
                "duration": 60,
                "size": 1,
            },
        )
        monkeypatch.setattr(
            url_import,
            "import_video",
            lambda video_id, url, *, prompt=None, clip_limit=0: started.append(
                (video_id, url, prompt, clip_limit)
            ),
        )

    def test_from_urls_requires_auth(self, client) -> None:
        response = client.post(
            "/api/v1/videos/from-urls",
            json={"urls": ["https://example.com/v.mp4"]},
        )
        assert response.status_code == 401

    def test_from_urls_imports_each_url(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={"urls": ["https://a.com/one.mp4", "https://b.com/two.mp4"]},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["total"] == 2
        assert all(item["video"] is not None for item in body["items"])
        assert {item["video"]["status"] for item in body["items"]} == {"processing"}
        # Each URL got its own background import job.
        assert sorted(u for _, u, _, _ in started) == [
            "https://a.com/one.mp4",
            "https://b.com/two.mp4",
        ]

    def test_from_urls_reports_per_url_failures(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)

        def probe(url, *, max_bytes):
            if "bad" in url:
                raise url_import.UrlImportError("That link didn't resolve to a video.")
            return {
                "title": "Good",
                "ext": "mp4",
                "duration": 60,
                "size": 1,
            }

        monkeypatch.setattr(url_import, "probe_url", probe)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={"urls": ["https://a.com/good.mp4", "https://a.com/bad.mp4"]},
        )
        body = response.json()
        assert body["total"] == 1
        by_url = {item["url"]: item for item in body["items"]}
        assert by_url["https://a.com/bad.mp4"]["error"] == ("That link didn't resolve to a video.")
        assert by_url["https://a.com/bad.mp4"]["video"] is None
        assert by_url["https://a.com/good.mp4"]["video"] is not None
        assert len(started) == 1

    def test_from_urls_rejects_playlists_when_disabled(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Expansion is off by default — a channel/playlist link is refused
        # with a clear message instead of importing its videos.
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)

        def expand(url, max_entries=50):
            if "playlist" in url:
                return ["https://a.com/one.mp4", "https://a.com/two.mp4"]
            return [url]

        monkeypatch.setattr(url_import, "expand_playlist", expand)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={"urls": ["https://a.com/playlist?list=x"]},
        )
        body = response.json()
        assert body["total"] == 0
        assert body["items"][0]["error"] == (
            "Playlist and channel links aren't supported yet — paste individual "
            "video links instead."
        )
        assert len(started) == 0

    def test_from_urls_expands_playlists_when_enabled(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.videos import routes

        monkeypatch.setattr(routes.settings, "url_import_expand_playlists", True)
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)

        def expand(url, max_entries=50):
            if "playlist" in url:
                return ["https://a.com/one.mp4", "https://a.com/two.mp4"]
            return [url]

        monkeypatch.setattr(url_import, "expand_playlist", expand)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={"urls": ["https://a.com/playlist?list=x"]},
        )
        body = response.json()
        assert body["total"] == 2
        assert sorted(item["url"] for item in body["items"]) == [
            "https://a.com/one.mp4",
            "https://a.com/two.mp4",
        ]
        assert len(started) == 2

    def test_from_urls_dedupes_repeated_urls(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={"urls": ["https://a.com/one.mp4", "https://a.com/one.mp4"]},
        )
        body = response.json()
        assert body["total"] == 1
        assert len(started) == 1

    def test_from_urls_respects_batch_cap(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.videos import routes

        monkeypatch.setattr(routes.settings, "url_import_max_batch", 2)
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={
                "urls": [
                    "https://a.com/one.mp4",
                    "https://a.com/two.mp4",
                    "https://a.com/three.mp4",
                ]
            },
        )
        body = response.json()
        assert body["total"] == 2
        assert len(started) == 2

    def test_from_urls_passes_prompt_through(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        started: list[tuple] = []
        self._patch_imports(monkeypatch, started)
        headers = self._auth_headers(client)

        response = client.post(
            "/api/v1/videos/from-urls",
            headers=headers,
            json={
                "urls": ["https://a.com/one.mp4"],
                "prompt": "a red car driving on a highway",
                "clip_limit": 5,
            },
        )
        assert response.status_code == 201, response.text
        _, _, prompt, clip_limit = started[0]
        assert prompt == "a red car driving on a highway"
        assert clip_limit == 5


class TestImportVideoJob:
    """The background import job itself: download, store, index.

    Every other route test stubs `import_video` out, so this is where the job's
    own wiring is checked — in particular that storing to the bucket and
    indexing overlap, and that a video whose bytes never reached storage does
    not end up sitting there as `ready` with nothing to play.
    """

    pytestmark = needs_db

    @staticmethod
    def _reserve(client, monkeypatch: pytest.MonkeyPatch):
        """A `processing` video row, as `POST /videos/from-url` leaves one.

        Returns `(video_id, import_video)`. The route is stopped from launching
        the real job by patching the very attribute these tests then want to
        call, so the undecorated function comes back with the id.
        """
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
        real_import_video = url_import.import_video
        monkeypatch.setattr(url_import, "import_video", lambda *args, **kwargs: None)
        response = client.post("/api/v1/auth/signup", json=SIGNUP)
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        created = client.post(
            "/api/v1/videos/from-url",
            headers=headers,
            json={"url": "https://example.com/big-buck-bunny.mp4"},
        )
        assert created.status_code == 201, created.text
        return created.json()["id"], real_import_video

    @staticmethod
    def _fake_download(monkeypatch: pytest.MonkeyPatch) -> None:
        """Skip the network: drop a small file where the downloader would."""

        def download(url, dest_dir, *, max_bytes, format_spec):
            target = dest_dir / "clip.mp4"
            target.write_bytes(_FakeVideoHandler.body)
            return target, "Big Buck Bunny", "mp4"

        monkeypatch.setattr(url_import, "download_video", download)

    def test_storing_overlaps_indexing(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        """The upload to storage must not be a barrier in front of indexing.

        Deterministic rather than timing-based: the fake upload refuses to
        finish until indexing has started. Ordering the two sequentially cannot
        pass this — it would sit on the event until the timeout.
        """
        import uuid as uuid_module

        from app.videos import pipeline
        from app.videos.storage import storage

        video_id, import_video = self._reserve(client, monkeypatch)
        self._fake_download(monkeypatch)

        indexing_started = threading.Event()
        stored = threading.Event()

        def save_path(key, source, content_type):
            if not indexing_started.wait(timeout=10):
                raise AssertionError("storage upload was awaited before indexing began")
            stored.set()

        async def index_video(video_id, source_path=None, *, own_source=True):
            # The import still owns the file: the upload is reading it.
            assert own_source is False
            assert source_path is not None and source_path.exists()
            indexing_started.set()

        monkeypatch.setattr(storage, "save_path", save_path)
        monkeypatch.setattr(pipeline, "index_video", index_video)

        client.portal.call(import_video, uuid_module.UUID(video_id), "https://x/y.mp4")

        assert stored.is_set()

    def test_failed_storage_fails_an_already_indexed_video(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Indexing succeeding does not make an unstored video importable.

        Because the two now overlap, the upload can fail *after* indexing has
        marked the video ready — leaving a searchable video whose bytes are not
        in the bucket. That has to come back as `failed`.
        """
        import uuid as uuid_module

        from app.db.session import SessionFactory
        from app.videos import pipeline
        from app.videos.models import Video
        from app.videos.storage import storage

        video_id, import_video = self._reserve(client, monkeypatch)
        self._fake_download(monkeypatch)

        def save_path(key, source, content_type):
            raise RuntimeError("bucket unreachable")

        async def index_video(video_id, source_path=None, *, own_source=True):
            async with SessionFactory() as db:
                video = await db.get(Video, video_id)
                video.status = "ready"
                await db.commit()

        monkeypatch.setattr(storage, "save_path", save_path)
        monkeypatch.setattr(pipeline, "index_video", index_video)

        client.portal.call(import_video, uuid_module.UUID(video_id), "https://x/y.mp4")

        body = client.get(
            f"/api/v1/videos/{video_id}",
            headers=self._auth_headers_for(client),
        ).json()
        assert body["status"] == "failed"
        assert "bucket unreachable" in body["error"]

    @staticmethod
    def _auth_headers_for(client) -> dict[str, str]:
        """Log the reserved video's owner back in (signup already happened)."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
