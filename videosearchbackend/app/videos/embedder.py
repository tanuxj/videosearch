"""Lazy CLIP embedder (sentence-transformers `clip-ViT-B-32`).

Two inference paths for image embeddings:

* **ONNX** (default, ``clip_backend="onnx"``) — the CLIP vision tower
  (vision model + projection + L2 norm) is exported to a single ONNX graph
  on first use and run through onnxruntime. Vectors are bit-for-bit
  compatible with the torch path (measured cosine similarity 1.0), so
  existing pgvector indexes stay valid. Roughly ~1.4x faster on CPU than
  eager torch and much lighter to load.
* **torch** (``clip_backend="torch"``) — the classic sentence-transformers
  path, kept as a fallback when onnxruntime is missing or the export fails.

Text embedding always uses torch: queries are rare and the text tower is
small, so there is nothing to gain from a second ONNX graph.

The model is ~600 MB and takes tens of seconds to load, so it must never be
imported eagerly: ``load()`` runs once, on first use, from whichever thread
needs it (the indexing background task or a search request). A lock guards
load, export and inference — torch CPU forward passes are not reentrant-safe
for concurrent calls on the same model instance.

Embeddings are L2-normalised, which is what makes pgvector's cosine distance
(`<=>`) a true similarity measure.

Vision input must be PIL Images: sentence-transformers' CLIP module branches
on ``isinstance(data, PIL.Image.Image)`` — a numpy array would silently be
treated as *text* and crash in the tokenizer.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_lock = threading.Lock()
_model: Any = None
_processor: Any = None
_vision_session: Any = None
# Set once the ONNX path has been tried and failed (missing onnxruntime, a
# crashed export, an unloadable session). Prevents retrying an expensive
# export on every 32-frame chunk — fall back to torch and stay there.
_vision_backend_failed = False

# CLIP's vision tower takes 224x224. Its own processor resizes to this anyway,
# so handing it full-resolution frames pays PIL-conversion and (slow) processor
# resize cost for pixels that are about to be thrown away. Downscaling here with
# cv2 first measured ~4x faster end-to-end on a 720p batch.
_INPUT_SIZE = 224


def _ensure_model() -> Any:
    """Load the shared model, downloading weights on first call.

    Caller must hold `_lock`. Tries the local HF cache first.
    sentence-transformers otherwise revalidates every file against
    huggingface.co on *each* load, even when the weights are already cached —
    and when that network is slow or blocked it burns five retries with
    backoff (~40 s) before falling back to the cache. Asking for cached files
    up front makes a warm start immediate and offline-safe; the online path
    still runs when nothing is cached yet.
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        try:
            _model = SentenceTransformer(settings.clip_model_name, local_files_only=True)
            logger.info("CLIP loaded from local cache (no network)")
        except Exception:
            logger.info("CLIP not in cache; downloading weights")
            _model = SentenceTransformer(settings.clip_model_name)
    return _model


def load() -> Any:
    """Return the shared model, downloading weights on first call."""
    if _model is None:
        with _lock:
            return _ensure_model()
    return _model


def _to_clip_input(frame: np.ndarray) -> Image.Image:
    """Downscale an RGB frame to CLIP's 224x224 input and wrap it as a PIL Image.

    Mirrors CLIP's own preprocessing — resize the shortest edge to 224, then
    centre-crop — so the resulting vectors stay interchangeable with ones
    produced from full-resolution frames.
    """
    height, width = frame.shape[:2]
    scale = _INPUT_SIZE / min(height, width)
    # `round` (not floor) so the short edge never lands a pixel under 224.
    resized = cv2.resize(
        frame,
        (max(_INPUT_SIZE, round(width * scale)), max(_INPUT_SIZE, round(height * scale))),
        # INTER_AREA is the right filter for downscaling — it averages the
        # pixels being collapsed rather than point-sampling them.
        interpolation=cv2.INTER_AREA,
    )
    top = (resized.shape[0] - _INPUT_SIZE) // 2
    left = (resized.shape[1] - _INPUT_SIZE) // 2
    return Image.fromarray(resized[top : top + _INPUT_SIZE, left : left + _INPUT_SIZE])


def _get_processor() -> Any:
    """The model's CLIPProcessor, loaded once and shared."""
    global _processor
    if _processor is None:
        with _lock:
            if _processor is None:
                _processor = _ensure_model()[0].processor
    return _processor


def _onnx_dir() -> Path:
    """Where the exported vision graph lives (persists across restarts).

    Lives under the HF cache root (``HF_HOME`` in Docker, the default
    ``~/.cache/huggingface`` locally) so it survives on the same volume as the
    model weights and never needs re-exporting.
    """
    base = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    return base / "onnx" / settings.clip_model_name


def _export_vision_onnx(destination: Path) -> None:
    """Export CLIP's vision tower + projection + L2 norm into one ONNX graph.

    Needs the torch model loaded (it is) and the `onnx`/`onnxscript` packages.
    Runs once per model version; the result is written atomically so a crash
    mid-export cannot leave a half-written file that later loads fail on.
    """
    import torch

    clip = _ensure_model()[0].model  # caller already holds `_lock`

    class _VisionProjector(torch.nn.Module):
        """vision_model → pooler CLS → visual projection → L2 normalize."""

        def __init__(self, clip_model: Any) -> None:
            super().__init__()
            self.vision_model = clip_model.vision_model
            self.projection = clip_model.visual_projection

        def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
            pooled = self.vision_model(pixel_values)[1]
            vecs = self.projection(pooled)
            return torch.nn.functional.normalize(vecs, p=2, dim=1)

    projector = _VisionProjector(clip).eval()

    # A representative input to trace against — the processor output is
    # (batch, 3, 224, 224), and the graph accepts any batch size.
    sample = torch.zeros(1, 3, _INPUT_SIZE, _INPUT_SIZE)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Per-process tmp name: with several uvicorn workers, two processes may
    # export concurrently — a shared tmp would let one writer clobber the
    # other's half-written file. The final `os.replace` stays atomic, so
    # last-writer-wins is fine as long as the temp names never collide.
    tmp = destination.parent / f"vision.{os.getpid()}.tmp"
    with torch.no_grad():
        # `dynamo=False` uses the classic TorchScript tracer, which embeds the
        # weights directly into the single .onnx file. The default dynamo
        # exporter spills weights to an external `.data` blob instead, which a
        # rename/copy would silently break.
        torch.onnx.export(
            projector,
            sample,
            tmp,
            input_names=["pixel_values"],
            output_names=["image_embedding"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "image_embedding": {0: "batch"},
            },
            opset_version=17,
            dynamo=False,
        )
    os.replace(tmp, destination)
    logger.info("Exported CLIP vision tower to ONNX: %s", destination)


def _get_vision_session() -> Any | None:
    """The onnxruntime session for the exported vision graph, or None.

    None means the ONNX path is unavailable (backend disabled by config,
    onnxruntime not installed, or the export failed) — callers fall back to
    the torch path.
    """
    global _vision_session, _vision_backend_failed
    if _vision_session is not None or settings.clip_backend != "onnx":
        return _vision_session
    if _vision_backend_failed:
        # Tried before and it broke — don't burn ~30s on an export again.
        return None
    with _lock:
        if _vision_session is not None:
            return _vision_session
        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning("onnxruntime not installed — using torch for CLIP embeddings")
            _vision_backend_failed = True
            return None

        onnx_path = _onnx_dir() / "vision.onnx"
        if not onnx_path.exists():
            try:
                _export_vision_onnx(onnx_path)
            except Exception:
                logger.exception("CLIP ONNX export failed — falling back to torch embeddings")
                _vision_backend_failed = True
                return None
        # Ensure the torch model is resident before running inference: the
        # processor (used in `embed_images`) and text queries both need it.
        _ensure_model()

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = os.cpu_count() or 4
        options.inter_op_num_threads = 1
        try:
            _vision_session = ort.InferenceSession(
                str(onnx_path), options, providers=["CPUExecutionProvider"]
            )
        except Exception:
            logger.exception("Could not load CLIP ONNX session — falling back to torch")
            _vision_backend_failed = True
            return None
        logger.info("CLIP vision tower running via ONNX Runtime")
    return _vision_session


def prewarm() -> None:
    """Load the model and the ONNX session (exporting if needed) up front.

    Called on a background thread at startup so the first upload or search
    never pays the ~45s model load or the one-time ONNX export — those would
    otherwise block every embedding call while holding the global lock.
    """
    _get_vision_session()
    load()


def embed_images(images: list) -> list[list[float]]:
    """Embed a batch of decoded frames (RGB numpy arrays) into 512-d vectors.

    Frames are downscaled to 224x224 and converted to PIL Images first — CLIP's
    tokenizer only routes PIL.Image instances to the vision tower; numpy arrays
    would be misread as text. Preprocessing (normalisation) runs through the
    same CLIPProcessor in both paths, so ONNX and torch vectors are identical.
    """
    pil_images = [_to_clip_input(frame) for frame in images]
    session = _get_vision_session()
    if session is not None:
        processor = _get_processor()
        batch = processor(images=pil_images, return_tensors="pt")
        pixels = batch["pixel_values"].numpy()
        with _lock:
            vectors = session.run(None, {"pixel_values": pixels})[0]
        # The exported graph already L2-normalises; the defensive re-normalise
        # costs nothing and keeps the invariant explicit.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).tolist()

    model = load()
    with _lock:
        vectors = model.encode(
            pil_images,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    return vectors.tolist()


def embed_text(text: str) -> list[float]:
    """Embed a natural-language prompt into the same 512-d space."""
    model = load()
    with _lock:
        vector = model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    return vector[0].tolist()
