"""Lazy vision-language embedder: CLIP or SigLIP 2, chosen by config.

Two models behind one interface (`embedding_model` setting):

* **clip** — sentence-transformers `clip-ViT-B-32`, 512-d. The original
  pipeline; fast on CPU.
* **siglip2** — Google `siglip2-base-patch16-224`, 768-d. Better retrieval
  and fine-grained detail (its training includes a localization-aware
  loss). Loaded through transformers directly — sentence-transformers'
  CLIP module assumes the CLIP architecture, and SigLIP's sigmoid loss and
  different processor do not fit it.

Two inference paths for image embeddings:

* **ONNX** (default, ``clip_backend="onnx"``) — the vision tower (vision
  model + projection + L2 norm) is exported to a single ONNX graph on first
  use and run through onnxruntime. Vectors match the torch path to within
  float noise. Roughly ~1.4x faster on CPU than eager torch and much
  lighter to load.
* **torch** (``clip_backend="torch"``) — the eager path, kept as a fallback
  when onnxruntime is missing or the export fails.

Text embedding always uses torch: queries are rare and the text tower is
small, so there is nothing to gain from a second ONNX graph.

The model is ~600 MB and takes tens of seconds to load, so it must never be
imported eagerly: ``load()`` runs once, on first use, from whichever thread
needs it (the indexing background task or a search request). A lock guards
load and export, and the torch forward pass — torch CPU inference is not
reentrant-safe for concurrent calls on the same model instance. ONNX Runtime
sessions *are* safe to ``run`` from several threads, and are deliberately not
locked: two videos indexing at once would otherwise serialise on it, as would a
search arriving mid-index.

Embeddings are L2-normalised, which is what makes pgvector's cosine distance
(`<=>`) a true similarity measure.

The input size differs per model (CLIP and SigLIP2-base both take 224px, but
the constant is read from the loaded processor rather than assumed) and the
pipeline consumes `embedder.INPUT_SIZE`, so a model swap needs no pipeline
code change. Switching models changes the embedding space — vectors must be
re-indexed (migration 0014 + re-upload or re-run of the pipeline).
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

#
# SigLIP 2 (HF `siglip2-base-patch16-224`): 768-d image/text vectors.
# Kept beside CLIP's 512 so the frames.embedding column can be resized by
# migration (and so `EMBEDDING_DIM` in models.py can be derived).
#
MODEL_DIMS = {"clip": 512, "siglip2": 768}
MODEL_IDS = {
    "clip": settings.clip_model_name,
    "siglip2": settings.siglip_model_name,
}

#: Vision input size of the configured model. CLIP ViT-B/32 is always 224;
#: SigLIP 2's varies by checkpoint, so it is parsed off the configured id.
#: Resolved at import because the model cannot change within a process — the
#: pipeline builds its ffmpeg scale filter from this at import time too.
INPUT_SIZE = settings.siglip_input_size if settings.embedding_model == "siglip2" else 224

# Backwards-compatible alias — the pipeline used to import CLIP_INPUT_SIZE.
CLIP_INPUT_SIZE = INPUT_SIZE
_INPUT_SIZE = INPUT_SIZE

# Per-model image normalisation, used only as a fallback: `_normalization`
# reads these off the real processor when it can, so a model swap cannot
# silently desync the numpy preprocessor from what the graph was traced on.
# CLIP's are OpenAI's published values; SigLIP normalises to [-1, 1].
_FALLBACK_NORMALIZATION = {
    "clip": (
        (0.48145466, 0.4578275, 0.40821073),
        (0.26862954, 0.26130258, 0.27577711),
    ),
    "siglip2": ((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
}

# (mean, std) broadcast to (1, 3, 1, 1), resolved once on first use.
_norm_cache: tuple[np.ndarray, np.ndarray] | None = None


def _ensure_model() -> Any:
    """Load the shared model, downloading weights on first call.

    Caller must hold `_lock`. For **clip** the value is a sentence-transformers
    ``(model, processor)`` tuple, exactly as before. For **siglip2** it is the
    HF `SiglipModel` itself (the processor is loaded separately in
    `_get_processor`, because SigLIP has no sentence-transformers wrapper).

    Both paths try the local HF cache first: transformers otherwise revalidates
    every file against huggingface.co on *each* load, even when the weights are
    already cached — and when that network is slow or blocked it burns five
    retries with backoff (~40 s) before falling back to the cache. Asking for
    cached files up front makes a warm start immediate and offline-safe; the
    online path still runs when nothing is cached yet.
    """
    global _model
    if _model is not None:
        return _model
    if settings.embedding_model == "siglip2":
        from transformers import AutoModel

        model_id = MODEL_IDS["siglip2"]
        try:
            _model = AutoModel.from_pretrained(model_id, local_files_only=True)
            logger.info("SigLIP 2 loaded from local cache (no network)")
        except Exception:
            logger.info("SigLIP 2 not in cache; downloading weights")
            _model = AutoModel.from_pretrained(model_id)
        _model.eval()
        return _model

    from sentence_transformers import SentenceTransformer

    try:
        _model = SentenceTransformer(settings.clip_model_name, local_files_only=True)
        logger.info("CLIP loaded from local cache (no network)")
    except Exception:
        logger.info("CLIP not in cache; downloading weights")
        _model = SentenceTransformer(settings.clip_model_name)
    return _model


def _core_model() -> Any:
    """The underlying HF model (CLIPModel or SiglipModel), for ONNX export.

    sentence-transformers wraps CLIPModel as ``(core_model, processor)``;
    SigLIP 2 is loaded as the bare HF model. The ONNX exporter only needs the
    core vision tower, and this is the one accessor that works for both.
    """
    model = _ensure_model()
    if settings.embedding_model == "siglip2":
        return model
    return model[0].model  # SentenceTransformer -> (CLIPModel, processor)


def load() -> Any:
    """Return the shared model, downloading weights on first call."""
    if _model is None:
        with _lock:
            return _ensure_model()
    return _model


def to_clip_frame(frame: np.ndarray) -> np.ndarray:
    """Downscale an RGB frame to the model's square input (`INPUT_SIZE`).

    Mirrors the processors' own preprocessing — resize the shortest edge to
    the input size, then centre-crop — so the resulting vectors stay
    interchangeable with ones produced from full-resolution frames. A frame
    that is already at that size (the indexing pipeline's decoder emits them
    that way) passes through untouched.
    """
    height, width = frame.shape[:2]
    if height == _INPUT_SIZE and width == _INPUT_SIZE:
        return frame
    scale = _INPUT_SIZE / min(height, width)
    # `round` (not floor) so the short edge never lands a pixel short.
    resized = cv2.resize(
        frame,
        (max(_INPUT_SIZE, round(width * scale)), max(_INPUT_SIZE, round(height * scale))),
        # INTER_AREA is the right filter for downscaling — it averages the
        # pixels being collapsed rather than point-sampling them.
        interpolation=cv2.INTER_AREA,
    )
    top = (resized.shape[0] - _INPUT_SIZE) // 2
    left = (resized.shape[1] - _INPUT_SIZE) // 2
    return resized[top : top + _INPUT_SIZE, left : left + _INPUT_SIZE]


def _to_clip_input(frame: np.ndarray) -> Image.Image:
    """`to_clip_frame`, wrapped as the PIL Image the CLIP module requires."""
    return Image.fromarray(to_clip_frame(frame))


def _image_stats(processor: Any) -> tuple[tuple, tuple]:
    """(image_mean, image_std) off a processor, whatever shape it comes in.

    `AutoProcessor` for SigLIP exposes them directly; CLIPProcessor keeps them
    on its nested `image_processor`. Falls back to the per-model constants
    when neither has them (a stand-in processor in tests, say).
    """
    for candidate in (processor, getattr(processor, "image_processor", None)):
        mean = getattr(candidate, "image_mean", None)
        std = getattr(candidate, "image_std", None)
        if mean is not None and std is not None:
            return tuple(mean), tuple(std)
    return _FALLBACK_NORMALIZATION[settings.embedding_model]


def _normalization() -> tuple[np.ndarray, np.ndarray]:
    """Mean and std shaped (1, 3, 1, 1), ready to broadcast over a batch."""
    global _norm_cache
    if _norm_cache is None:
        mean, std = _image_stats(_get_processor())
        _norm_cache = (
            np.asarray(mean, dtype=np.float32).reshape(1, 3, 1, 1),
            np.asarray(std, dtype=np.float32).reshape(1, 3, 1, 1),
        )
    return _norm_cache


def _preprocess(frames: list[np.ndarray]) -> np.ndarray:
    """RGB uint8 frames → the (batch, 3, S, S) float32 tensor the graph takes.

    This is what the HF processor does — resize/crop to the input size,
    rescale by 1/255, normalise — done in numpy over the whole batch instead
    of per frame through PIL. The indexing pipeline's decoder already emits
    frames at exactly the input size, so `to_clip_frame` is a no-op there and
    every PIL Image built on that path was pure overhead: an object per frame,
    a resize that changed nothing, and a second pass to get back to an array.
    Frames that *are* off-size (the torch fallback's callers, grounding) still
    go through the same scale-and-centre-crop, so the vectors are unchanged.
    """
    mean, std = _normalization()
    # (N, S, S, 3) uint8 → (N, 3, S, S) float32, contiguous for onnxruntime.
    stacked = np.stack([to_clip_frame(frame) for frame in frames])
    pixels = np.ascontiguousarray(stacked.transpose(0, 3, 1, 2), dtype=np.float32)
    pixels /= 255.0
    pixels -= mean
    pixels /= std
    return pixels


def _get_processor() -> Any:
    """The model's processor, loaded once and shared.

    CLIP's comes attached to the sentence-transformers wrapper; SigLIP 2's is
    loaded directly (AutoProcessor handles the SigLIP2 image mean/std and
    tokenizer in one object).
    """
    global _processor
    if _processor is None:
        with _lock:
            if _processor is None:
                if settings.embedding_model == "siglip2":
                    from transformers import AutoProcessor

                    try:
                        _processor = AutoProcessor.from_pretrained(
                            MODEL_IDS["siglip2"], local_files_only=True
                        )
                    except Exception:
                        _processor = AutoProcessor.from_pretrained(MODEL_IDS["siglip2"])
                else:
                    _processor = _ensure_model()[0].processor
    return _processor


def _onnx_dir() -> Path:
    """Where the exported vision graph lives (persists across restarts).

    Lives under the HF cache root (``HF_HOME`` in Docker, the default
    ``~/.cache/huggingface`` locally) so it survives on the same volume as the
    model weights and never needs re-exporting.
    """
    base = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    # Keyed by the *checkpoint*, not the model family: two SigLIP 2
    # checkpoints are both `embedding_model="siglip2"` but have different
    # input resolutions and weights, and keying on the family name would hand
    # a patch32-256 run the patch16-224 graph exported before it. Slashes in
    # the id become a nested path, which is what HF ids look like anyway.
    return base / "onnx" / MODEL_IDS[settings.embedding_model].replace("/", "--")


def _export_vision_onnx(destination: Path) -> None:
    """Export the vision tower (+ projection, for CLIP) + L2 norm into one ONNX graph.

    CLIPModel and SiglipModel both expose `vision_model` and both pool with
    their CLS token (`pooler_output`), but only CLIP projects that pooled
    output into the joint embedding space with a separate `visual_projection`
    layer — SigLIP has no such layer at all: its vision tower's hidden size
    already *is* the joint embedding dim, and `SiglipModel.get_image_features`
    returns `pooler_output` untouched. Applying a CLIP-style projection to it
    would be wrong even if the attribute existed. Needs the torch model loaded
    (it is) and the `onnx`/`onnxscript` packages. Runs once per model version;
    the result is written atomically so a crash mid-export cannot leave a
    half-written file that later loads fail on.
    """
    import torch

    clip = _core_model()  # caller already holds `_lock`
    is_siglip = settings.embedding_model == "siglip2"

    class _VisionProjector(torch.nn.Module):
        """vision_model → pooler CLS → (CLIP only: visual projection) → L2 normalize."""

        def __init__(self, clip_model: Any) -> None:
            super().__init__()
            self.vision_model = clip_model.vision_model
            self.projection = None if is_siglip else clip_model.visual_projection

        def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
            outputs = self.vision_model(pixel_values)
            pooled = outputs.pooler_output
            vecs = pooled if self.projection is None else self.projection(pooled)
            return torch.nn.functional.normalize(vecs, p=2, dim=1)

    projector = _VisionProjector(clip).eval()

    # A representative input to trace against — the processor output is
    # (batch, 3, INPUT_SIZE, INPUT_SIZE), and the graph accepts any batch size.
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
    logger.info("Exported %s vision tower to ONNX: %s", settings.embedding_model, destination)


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
        # Not every core: the decoder needs some, and they run concurrently.
        options.intra_op_num_threads = settings.resolved_embed_threads
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
    """Embed a batch of decoded frames (RGB numpy arrays) into unit vectors.

    The ONNX path preprocesses in numpy (`_preprocess`) — same resize, rescale
    and normalisation the processor applies, over the whole batch at once.
    The torch paths still build PIL Images, because the processors' tokenizers
    only route PIL.Image instances to the vision tower and would misread a
    numpy array as text. Both produce the same vectors.
    """
    session = _get_vision_session()
    if session is not None:
        pixels = _preprocess(images)
        # Unlocked on purpose: `InferenceSession.run` is thread-safe, and the
        # indexing pipeline calls this from its own embed thread.
        vectors = session.run(None, {"pixel_values": pixels})[0]
        # The exported graph already L2-normalises; the defensive re-normalise
        # costs nothing and keeps the invariant explicit.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).tolist()

    # Torch fallback. CLIP goes through sentence-transformers' encode();
    # SigLIP 2 has no wrapper, so the forward pass runs explicitly: processor
    # → vision tower → pooler → L2 norm, matching the ONNX graph. No
    # projection step — unlike CLIP, SigLIP has no `visual_projection`; its
    # vision tower's pooled output already sits in the joint embedding space
    # (see `SiglipModel.get_image_features`, which returns it untouched).
    if settings.embedding_model == "siglip2":
        import torch

        model = _ensure_model()
        processor = _get_processor()
        batch = processor(
            images=[_to_clip_input(frame) for frame in images], return_tensors="pt"
        )
        with _lock, torch.no_grad():
            outputs = model.vision_model(**batch)
            vectors = torch.nn.functional.normalize(outputs.pooler_output, p=2, dim=1)
        return vectors.numpy().tolist()

    model = load()
    with _lock:
        vectors = model.encode(
            [_to_clip_input(frame) for frame in images],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    return vectors.tolist()


def embed_text(text: str) -> list[float]:
    """Embed a natural-language prompt into the model's text space."""
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed several prompts in one batch (used by caption search too).

    Caption search embeds every caption at index time, so this is the batched
    form `embed_text` also routes through — one tokenizer pass and one forward
    per batch instead of per string.
    """
    if settings.embedding_model == "siglip2":
        import torch

        model = _ensure_model()
        processor = _get_processor()
        batch = processor(
            text=texts, return_tensors="pt", padding="max_length", truncation=True
        )
        with _lock, torch.no_grad():
            outputs = model.get_text_features(
                input_ids=batch["input_ids"],
                attention_mask=batch.get("attention_mask"),
            )
            vectors = torch.nn.functional.normalize(outputs, p=2, dim=1)
        return vectors.numpy().tolist()

    model = load()
    with _lock:
        vectors = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    return vectors.tolist()
