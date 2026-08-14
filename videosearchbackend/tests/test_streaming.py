"""Unit tests for the edge-streaming URL signing (no database needed)."""

import hashlib
import hmac

from app.videos import streaming


def test_sign_stream_path_is_hmac_sha256_over_key_and_expiry() -> None:
    key = "owner-id/video-id.mp4"
    expires = 1_800_000_000
    secret = "top-secret"

    path = streaming.sign_stream_path(key, secret, expires)

    expected = hmac.new(
        secret.encode(),
        f"{key}:{expires}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert path == f"/stream/{key}?expires={expires}&sig={expected}"


def test_sign_stream_path_differs_across_expiry() -> None:
    key = "owner-id/video-id.mp4"
    secret = "top-secret"
    a = streaming.sign_stream_path(key, secret, 1_000)
    b = streaming.sign_stream_path(key, secret, 1_001)
    assert a != b


def test_sign_stream_path_differs_across_keys() -> None:
    secret = "top-secret"
    a = streaming.sign_stream_path("owner-a/video.mp4", secret, 1_000)
    b = streaming.sign_stream_path("owner-b/video.mp4", secret, 1_000)
    assert a != b


def test_build_stream_url_returns_none_without_worker_config(
    monkeypatch,
) -> None:
    monkeypatch.setattr(streaming.settings, "stream_worker_base_url", None)
    monkeypatch.setattr(streaming.settings, "stream_signing_secret", "")
    assert streaming.build_stream_url("owner/video.mp4") is None


def test_build_stream_url_mints_a_signed_url(monkeypatch) -> None:
    monkeypatch.setattr(streaming.settings, "stream_worker_base_url", "https://edge.example.com")
    monkeypatch.setattr(streaming.settings, "stream_signing_secret", "secret")
    monkeypatch.setattr(streaming.settings, "stream_url_ttl_seconds", 60)

    url = streaming.build_stream_url("owner/video.mp4")
    assert url is not None
    assert url.startswith("https://edge.example.com/stream/owner/video.mp4?")
    assert "expires=" in url
    assert "sig=" in url


def test_build_stream_url_strips_trailing_slash_from_base(monkeypatch) -> None:
    monkeypatch.setattr(streaming.settings, "stream_worker_base_url", "https://edge.example.com/")
    monkeypatch.setattr(streaming.settings, "stream_signing_secret", "secret")

    url = streaming.build_stream_url("owner/video.mp4")
    assert url is not None
    assert "//stream/" not in url
