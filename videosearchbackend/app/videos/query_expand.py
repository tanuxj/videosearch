"""Expand a raw search prompt into CLIP-friendly visual descriptions.

CLIP (the embedding model) matches best when text names what's actually in a
shot — objects, people, setting, lighting, colours, action. Terse or
grammatically broken prompts ("car red road", "bhai car dikha") embed poorly
and miss real matches. This module is the optional "middleman" that rewrites a
prompt into a few short, visually-grounded variants; the search then embeds
every variant and takes each frame's best similarity across them.

When no LLM is configured (`LLM_API_KEY` unset) the raw prompt is returned
unchanged, so search still works without it — just with less recall on vague
queries.

The HTTP call uses ``urllib`` deliberately: the caller runs this on a worker
thread (``run_in_threadpool``), so a blocking stdlib request costs nothing and
no extra dependency is needed in the production image.
"""

import json
import logging
import urllib.request

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_SYSTEM_PROMPT = (
    "You expand one-line video-search queries into short descriptions a "
    "vision model (CLIP) can match against video frames. Fix grammar and fill "
    "in the visual details the words imply: objects, people, setting, "
    "lighting, colours, actions. Give 2–3 concise variants (8–18 words) that "
    "phrase the same moment differently, so at least one lands on the footage. "
    "Never invent a scene the query does not support. Answer with JSON only."
)

_USER_TEMPLATE = (
    "Rewrite this video-search query as {count} visual descriptions.\n"
    'Return JSON: {{"variants": ["…", "…"]}}\n'
    "Query: {query}"
)


def _parse_variants(content: str) -> list[str]:
    """Extract expanded variants from the model's JSON response."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Some providers ignore response_format and wrap in prose — grab the
        # first JSON array we can find.
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            data = {"variants": json.loads(content[start : end + 1])}
        except json.JSONDecodeError:
            return []
    variants = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(variants, list):
        return []
    cleaned = [v.strip() for v in variants if isinstance(v, str) and len(v.strip()) >= 6]
    return cleaned[: settings.llm_expand_prompts]


def expand_prompt(raw: str) -> list[str]:
    """Return expanded search variants, or ``[raw]`` when no LLM is configured.

    The raw prompt is always included first — it is the user's own intent and
    a faithful fallback if an expansion drifts. Never raises: any LLM failure
    degrades to the raw prompt.
    """
    if not settings.llm_api_key:
        return [raw]

    payload = {
        "model": settings.llm_model,
        "temperature": 0.4,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_TEMPLATE.format(count=settings.llm_expand_prompts, query=raw),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    # Accept either a bare endpoint (…/openai) or the full path
    # (…/openai/chat/completions) — don't double-append.
    base = settings.llm_base_url.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            body = json.loads(response.read())
        content = body["choices"][0]["message"]["content"]
        expanded = _parse_variants(content)
        if expanded:
            variants = [raw, *expanded]
            logger.info("Expanded search query: %r → %r", raw, variants)
            return variants
    except Exception as exc:  # noqa: BLE001 - any LLM hiccup degrades to raw
        logger.warning("Query expansion failed, using raw prompt: %s", exc)
    return [raw]
