"""Unit tests for the CLIP embedder's backend selection and fallback.

The real model is ~600 MB and must not load in tests, so these verify the
*scheduling logic* only: the ONNX path is used when a session is available,
and the torch path when it is not. Both paths run through mocks.
"""

from pathlib import Path

import numpy as np
import pytest

from app.videos import embedder


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test starts with a cold embedder (no cached model/session)."""
    embedder._model = None
    embedder._processor = None
    embedder._vision_session = None
    embedder._vision_backend_failed = False
    yield
    embedder._model = None
    embedder._processor = None
    embedder._vision_session = None
    embedder._vision_backend_failed = False


class _FakeProcessor:
    """CLIPProcessor stand-in: returns a (3, 224, 224) pixel_values tensor."""

    def __init__(self, batch: int) -> None:
        self.batch = batch

    def __call__(self, images, return_tensors: str = "pt"):
        import torch

        return {"pixel_values": torch.zeros(self.batch, 3, 224, 224)}


class _FakeModel:
    """Stands in for the sentence-transformers model."""

    def __init__(self, batch: int = 3) -> None:
        class _Module:
            def __init__(self, n: int) -> None:
                self.processor = _FakeProcessor(n)

        self.modules = [_Module(batch)]
        self.encoded: list | None = None

    def __getitem__(self, index: int):
        return self.modules[index]

    def encode(self, images, **kwargs):
        self.encoded = images
        # 512-d, already-normalized-ish (embedder normalises again).
        return np.zeros((len(images), 512), dtype=np.float32)


class _FakeSession:
    """Stands in for the onnxruntime InferenceSession."""

    def __init__(self, batch: int) -> None:
        self.batch = batch

    def run(self, _, feeds):
        assert set(feeds) == {"pixel_values"}
        return [np.full((self.batch, 512), 0.5, dtype=np.float32)]


def _fake_frames(n: int = 3) -> list:
    return [np.zeros((64, 64, 3), dtype=np.uint8) for _ in range(n)]


def _tmp_onnx_dir() -> Path:
    """A scratch dir for the negative-cache test (never touches the real cache)."""
    import tempfile

    return Path(tempfile.mkdtemp(prefix="onnx-test-"))


def test_torch_path_used_when_backend_is_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "clip_backend", "torch")
    fake = _FakeModel()
    monkeypatch.setattr(embedder, "_ensure_model", lambda: fake)

    vecs = embedder.embed_images(_fake_frames())

    # Torch path: model.encode was called with PIL images.
    assert fake.encoded is not None
    assert len(vecs) == 3
    assert all(len(v) == 512 for v in vecs)


def test_torch_path_used_when_onnx_session_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "clip_backend", "onnx")
    fake = _FakeModel()
    monkeypatch.setattr(embedder, "_ensure_model", lambda: fake)
    # Session never materialises (e.g. onnxruntime missing / export failed).
    monkeypatch.setattr(embedder, "_get_vision_session", lambda: None)

    vecs = embedder.embed_images(_fake_frames())

    assert fake.encoded is not None
    assert len(vecs) == 3


def test_onnx_path_used_when_session_available(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "clip_backend", "onnx")
    fake = _FakeModel(batch=3)
    monkeypatch.setattr(embedder, "_ensure_model", lambda: fake)
    monkeypatch.setattr(embedder, "_get_vision_session", lambda: _FakeSession(batch=3))

    vecs = embedder.embed_images(_fake_frames())

    # ONNX path: the model's encode() is NOT called; vectors come from the
    # session and are L2-normalised by the embedder.
    assert fake.encoded is None
    assert len(vecs) == 3
    norms = [np.linalg.norm(v) for v in vecs]
    assert all(abs(n - 1.0) < 1e-5 for n in norms)


def test_get_vision_session_none_when_backend_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "clip_backend", "torch")
    assert embedder._get_vision_session() is None


def test_failed_export_is_negative_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed ONNX export must not be retried on every embed call."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "clip_backend", "onnx")
    monkeypatch.setattr(embedder, "_onnx_dir", lambda: _tmp_onnx_dir())

    calls = {"n": 0}

    def _boom(destination):
        calls["n"] += 1
        raise RuntimeError("export boom")

    monkeypatch.setattr(embedder, "_export_vision_onnx", _boom)

    assert embedder._get_vision_session() is None
    assert embedder._vision_backend_failed is True
    # Second call skips the export entirely (no re-attempt, no re-lock cost).
    assert embedder._get_vision_session() is None
    assert calls["n"] == 1


def test_prewarm_loads_session_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "clip_backend", "onnx")
    fake = _FakeModel(batch=3)
    monkeypatch.setattr(embedder, "_ensure_model", lambda: fake)
    monkeypatch.setattr(embedder, "_get_vision_session", lambda: _FakeSession(batch=3))

    embedder.prewarm()

    # Both paths were touched without error — nothing to assert beyond no raise.
    assert embedder._get_vision_session() is not None
