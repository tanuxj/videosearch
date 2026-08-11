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

import threading
from typing import Any

from PIL import Image

from app.core.config import get_settings

settings = get_settings()

_lock = threading.Lock()
_model: Any = None


def load() -> Any:
    """Return the shared model, downloading weights on first call."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(settings.clip_model_name)
    return _model


def embed_images(images: list) -> list[list[float]]:
    """Embed a batch of decoded frames (RGB numpy arrays) into 512-d vectors.

    Frames are converted to PIL Images first — CLIP's tokenizer only routes
    PIL.Image instances to the vision tower; numpy arrays would be misread as
    text.
    """
    pil_images = [Image.fromarray(frame) for frame in images]
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
