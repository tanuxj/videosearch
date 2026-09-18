"""Florence-2: dense frame captions at index time + phrase grounding on demand.

One small model (MIT-licensed, 0.23B params, CPU-friendly) does both jobs the
search product needs beyond embeddings:

* **Captions** (`caption_frames`) — a dense description of what a frame shows,
  written at index time and stored on the frame row. Captions are embedded
  with the text tower and searched text↔text, which is far more discriminative
  than CLIP's text↔image: relational prompts like "the guy with long hair
  standing next to the car" match a sentence that *says* that, where an image
  embedding only gestures at the whole scene.
* **Grounding** (`locate_phrase`) — given one frame and a phrase, return
  bounding boxes for where that phrase's object appears. This is what draws
  the box on the lightbox frame when a user asks "where is the red car?".

The model is loaded once and shared (same discipline as the embedder: never on
import, guarded by a lock, warmable at startup). Tasks are passed as prompt
tokens — Florence-2 is trained on task-prefix prompts like
``<MORE_DETAILED_CAPTION>`` and ``<CAPTION_TO_PHRASE_GROUNDING>`` and returns
parsed structures for them via `post_process_generation`.

Everything here is best-effort by design: captioning slows indexing, so the
pipeline skips it (leaving `caption` null) if the model is unavailable rather
than failing the index.
"""

import logging
import re
import threading
from typing import Any

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_lock = threading.Lock()
_model: Any = None
_processor: Any = None
_device: str = "cpu"

# Florence-2 task tokens used here. The detailed-caption task produces the
# long-form descriptions caption search wants; the grounding task consumes a
# phrase and returns boxes.
_CAPTION_TASK = "<MORE_DETAILED_CAPTION>"
_GROUND_TASK = "<CAPTION_TO_PHRASE_GROUNDING>"

# `<CAPTION_TO_PHRASE_GROUNDING>phrase` — the model echoes the task token back
# in its output; the parser strips whichever one it used.
_GROUND_PREFIX = re.compile(r"^(?:<CAPTION_TO_PHRASE_GROUNDING>|<OD>)\s*", re.IGNORECASE)


def _ensure_model() -> tuple[Any, Any]:
    """Load Florence-2 + processor, downloading weights on first call.

    Caller must hold `_lock`. Same cache-first discipline as the embedder so a
    warm start is offline-safe. Returns (model, processor) on `self._device`.
    """
    global _model, _processor, _device
    if _model is not None:
        return _model, _processor

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    # Florence-2's remote-code class predates transformers' newer
    # attention-implementation refactor and crashes under the "sdpa"/"auto"
    # default (`AttributeError: ... has no attribute '_supports_sdpa'`) —
    # forcing eager attention sidesteps the incompatible capability check.
    # CPU-only anyway, so there is no speed to give up.
    try:
        _processor = AutoProcessor.from_pretrained(
            settings.florence_model_name, local_files_only=True, trust_remote_code=True
        )
        _model = AutoModelForCausalLM.from_pretrained(
            settings.florence_model_name,
            local_files_only=True,
            trust_remote_code=True,
            attn_implementation="eager",
        )
        logger.info("Florence-2 loaded from local cache (no network)")
    except Exception:
        logger.info("Florence-2 not in cache; downloading weights")
        _processor = AutoProcessor.from_pretrained(
            settings.florence_model_name, trust_remote_code=True
        )
        _model = AutoModelForCausalLM.from_pretrained(
            settings.florence_model_name,
            trust_remote_code=True,
            attn_implementation="eager",
        )

    # fp32 on CPU: Florence-2 is small enough that half precision is not worth
    # the accuracy loss on CPU, and the API's indexing box has no GPU contract.
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _model = _model.to(_device).eval()
    return _model, _processor


def _run(image: Any, prompt: str, max_new_tokens: int = 256) -> str:
    """One generate() call: image + task-prefixed prompt → raw output text."""
    import torch

    model, processor = _ensure_model()
    inputs = processor(text=prompt, images=image, return_tensors="pt").to(_device)
    with torch.no_grad():
        generated = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=max_new_tokens,
            num_beams=1,  # beam search triples CPU time for marginal quality here
            do_sample=False,
        )
    return processor.batch_decode(generated, skip_special_tokens=False)[0]


def _to_pil(frame: np.ndarray) -> Any:
    """RGB numpy frame → PIL (Florence-2's processor takes PIL images)."""
    from PIL import Image

    return Image.fromarray(frame)


def caption_frames(frames: list[np.ndarray]) -> list[str]:
    """Dense captions for a batch of RGB frames, input order preserved."""
    if not frames:
        return []
    pil_frames = [_to_pil(frame) for frame in frames]
    with _lock:
        return [
            _run(image, _CAPTION_TASK).replace(_CAPTION_TASK, "").strip()
            for image in pil_frames
        ]


def locate_phrase(frame: np.ndarray, phrase: str) -> list[list[float]]:
    """Bounding boxes (x1, y1, x2, y2 in 0–1 coords) where `phrase` appears.

    Returns an empty list when the model finds nothing — the caller decides
    whether that is a 404 or just no overlay. Boxes are normalised so the
    frontend can draw them at any thumbnail size.
    """
    pil_frame = _to_pil(frame)
    with _lock:
        raw = _run(pil_frame, f"{_GROUND_TASK}{phrase}", max_new_tokens=128)

    text = _GROUND_PREFIX.sub("", raw).strip()
    if not text:
        return []
    try:
        parsed = _processor.post_process_generation(
            text, task=_GROUND_TASK, image_size=(pil_frame.width, pil_frame.height)
        )
    except Exception:
        # Malformed generation (rare, but a truncated decode can do it) is a
        # "found nothing", not a crash.
        logger.debug("Florence-2 grounding output unparsable: %r", raw)
        return []

    boxes = parsed.get(_GROUND_TASK) or []
    return [[float(v) for v in box] for box in boxes]


def prewarm() -> None:
    """Load the model if captioning or grounding is configured on."""
    if settings.captions_enabled or settings.grounding_enabled:
        with _lock:
            _ensure_model()


def model_ready() -> bool:
    """True when the weights are resident — used to skip captioning cheaply."""
    return _model is not None
