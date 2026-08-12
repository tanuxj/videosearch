"""Lazy CLIP embedder (sentence-transformers `clip-ViT-B-32`).

The model is ~600 MB and takes tens of seconds to load, so it must never be
imported eagerly: ``load()`` runs once, on first use, from whichever thread
needs it (the indexing background task or a search request). A lock guards
both the load and inference — torch CPU forward passes are not reentrant-safe
for concurrent calls on the same model instance.

Embeddings are L2-normalised, which is what makes pgvector's cosine distance
(`<=>`) a true similarity measure.

Vision input must be PIL Images: sentence-transformers' CLIP module branches
on ``isinstance(data, PIL.Image.Image)`` — a numpy array would silently be
treated as *text* and crash in the tokenizer.
"""

import logging
import threading
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_lock = threading.Lock()
_model: Any = None

# CLIP's vision tower takes 224x224. Its own processor resizes to this anyway,
# so handing it full-resolution frames pays PIL-conversion and (slow) processor
# resize cost for pixels that are about to be thrown away. Downscaling here with
# cv2 first measured ~4x faster end-to-end on a 720p batch.
_INPUT_SIZE = 224


def load() -> Any:
    """Return the shared model, downloading weights on first call.

    Tries the local HF cache first. sentence-transformers otherwise revalidates
    every file against huggingface.co on *each* load, even when the weights are
    already cached — and when that network is slow or blocked it burns five
    retries with backoff (~40 s) before falling back to the cache. Asking for
    cached files up front makes a warm start immediate and offline-safe; the
    online path still runs when nothing is cached yet.
    """
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                try:
                    _model = SentenceTransformer(
                        settings.clip_model_name, local_files_only=True
                    )
                    logger.info("CLIP loaded from local cache (no network)")
                except Exception:
                    logger.info("CLIP not in cache; downloading weights")
                    _model = SentenceTransformer(settings.clip_model_name)
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


def embed_images(images: list) -> list[list[float]]:
    """Embed a batch of decoded frames (RGB numpy arrays) into 512-d vectors.

    Frames are downscaled to 224x224 and converted to PIL Images first — CLIP's
    tokenizer only routes PIL.Image instances to the vision tower; numpy arrays
    would be misread as text.
    """
    pil_images = [_to_clip_input(frame) for frame in images]
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
