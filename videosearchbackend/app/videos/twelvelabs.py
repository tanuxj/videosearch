"""Twelve Labs (Marengo) client — an alternative to the local CLIP index.

Why this exists: CLIP embedding runs at ~5 frames/sec on CPU, so indexing is
~81% embedding time and a feature-length film takes ~45 minutes. Marengo is a
video-native model on managed GPUs that indexes far faster, and understands
motion across frames rather than scoring stills independently.

This is deliberately **parallel to** the CLIP path, not a replacement. Both can
index the same video and the search route picks between them, so their results
can be compared on real footage before anything is ripped out.

Design notes:

* **Bytes never pass through this backend.** ``POST /assets`` accepts
  ``method=url``, so we hand Twelve Labs a short-lived presigned R2 URL and
  they pull it directly. Uploading the file ourselves would mean downloading
  1.4 GB from R2 only to push it straight back out.
* **urllib, not a new dependency.** Matches ``query_expand.py`` and
  ``transcribe.py``: callers run these on a worker thread, so a blocking
  stdlib request costs nothing and the production image stays as it is.
* **Multipart everywhere.** Both ``/assets`` and ``/search`` are
  ``multipart/form-data`` (not JSON) per the v1.3 OpenAPI spec, and
  ``search_options`` is a *repeated* field rather than a JSON array.

API surface used (base ``https://api.twelvelabs.io/v1.3``, ``x-api-key`` auth):

    POST /indexes                              create an index
    GET  /indexes                              find an existing one by name
    POST /assets                    multipart  register a video from a URL
    POST /indexes/{id}/indexed-assets          start indexing that asset
    GET  /indexes/{id}/indexed-assets/{id}     poll until ready
    POST /search                    multipart  natural-language search
"""

import json
import logging
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Same reason as transcribe.py: urllib's default `Python-urllib/3.x` is
# blocked by several providers' bot protection.
_USER_AGENT = "videosearch/0.1 (+https://github.com/tanuxj/videosearch)"


class TwelveLabsError(Exception):
    """A Twelve Labs API call failed."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One matching moment, shaped like the app's existing clip results.

    Note there is no similarity score: Marengo 3.0 returns **`rank`** (1 =
    best) and nothing comparable to CLIP's cosine value. Callers that need a
    score have to derive one from the ordering — see `rank_score`.

    `transcription` is the speech inside the matched moment, which is often
    the reason it matched at all and is worth surfacing to the user.
    """

    video_id: str
    start: float
    end: float
    rank: int
    transcription: str | None = None


def rank_score(rank: int) -> float:
    """A descending 0–1 stand-in for the similarity Marengo does not return.

    The UI draws confidence bars relative to the best hit in the set, so what
    matters is that this is monotonic in rank, not that it means anything in
    absolute terms. Deliberately *not* presented anywhere as a similarity.
    """
    return round(1.0 / max(1, rank), 4)


def _form(fields: list[tuple[str, str]]) -> tuple[bytes, str]:
    """Encode ``(name, value)`` pairs as multipart/form-data.

    A list of pairs rather than a dict because `search_options` is sent as the
    same field name repeated once per modality — a dict would silently keep
    only the last one.
    """
    boundary = f"----videosearch{secrets.token_hex(16)}"
    body = bytearray()
    for name, value in fields:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    form: list[tuple[str, str]] | None = None,
) -> Any:
    """Call the API and return the decoded JSON body."""
    if not settings.twelvelabs_api_key:
        raise TwelveLabsError("TWELVELABS_API_KEY is not configured")

    url = f"{settings.twelvelabs_base_url.rstrip('/')}{path}"
    headers = {"x-api-key": settings.twelvelabs_api_key, "User-Agent": _USER_AGENT}

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data, content_type = _form(form)
        headers["Content-Type"] = content_type

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=settings.twelvelabs_timeout_seconds) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise TwelveLabsError(f"{method} {path} failed ({exc.code}): {detail}") from exc
    except Exception as exc:  # noqa: BLE001 - network, timeout, bad JSON
        raise TwelveLabsError(f"{method} {path} failed: {exc}") from exc


# ── Indexes ────────────────────────────────────────────────────


def find_index(name: str) -> str | None:
    """Return the id of the index called ``name``, or None if there isn't one."""
    body = _request("GET", "/indexes")
    for item in body.get("data") or []:
        if item.get("index_name") == name:
            return item.get("_id") or item.get("id")
    return None


def create_index(name: str) -> str:
    """Create an index configured for visual + audio search."""
    body = _request(
        "POST",
        "/indexes",
        json_body={
            "index_name": name,
            "models": [
                {
                    # `model_options` are the modalities Marengo analyses.
                    # Both, because the whole point of comparing against CLIP
                    # is that CLIP is visual-only and cannot hear anything.
                    "model_name": settings.twelvelabs_model,
                    "model_options": ["visual", "audio"],
                }
            ],
        },
    )
    index_id = body.get("_id") or body.get("id")
    if not index_id:
        raise TwelveLabsError(f"Index creation returned no id: {body}")
    logger.info("Created Twelve Labs index %s (%s)", name, index_id)
    return index_id


def ensure_index() -> str:
    """The index id to use, creating the index on first run.

    An explicit `TWELVELABS_INDEX_ID` wins; otherwise look up (or create) one
    named `TWELVELABS_INDEX_NAME`. Indexes are cheap and their model config is
    immutable, so binding to a name rather than hardcoding an id keeps a fresh
    environment working with no manual setup step.
    """
    if settings.twelvelabs_index_id:
        return settings.twelvelabs_index_id
    name = settings.twelvelabs_index_name
    return find_index(name) or create_index(name)


# ── Ingest ─────────────────────────────────────────────────────


def create_asset_from_url(url: str, filename: str | None = None) -> str:
    """Register a remote video and return its asset id.

    ``url`` is a presigned R2 link — Twelve Labs fetches the object directly,
    so the file never round-trips through this backend.
    """
    fields = [("method", "url"), ("url", url)]
    if filename:
        fields.append(("filename", filename[:120]))
    body = _request("POST", "/assets", form=fields)
    asset_id = body.get("_id") or body.get("id") or body.get("asset_id")
    if not asset_id:
        raise TwelveLabsError(f"Asset creation returned no id: {body}")
    return asset_id


def asset(asset_id: str) -> dict:
    """Current state of an uploaded asset.

    Creating an asset from a URL only *starts* the transfer — they fetch and
    probe the file asynchronously, and indexing it before that finishes is
    rejected with ``parameter_invalid: Asset is currently being processed``.
    So this has to be polled to ``ready`` first; asset preparation and index
    building are two separate waits, not one.
    """
    return _request("GET", f"/assets/{asset_id}")


def index_asset(index_id: str, asset_id: str) -> str:
    """Start indexing an asset into an index; returns the indexed-asset id."""
    body = _request(
        "POST",
        f"/indexes/{index_id}/indexed-assets",
        json_body={"asset_id": asset_id},
    )
    indexed_id = body.get("_id") or body.get("id") or body.get("indexed_asset_id")
    if not indexed_id:
        raise TwelveLabsError(f"Indexing returned no id: {body}")
    return indexed_id


def indexed_asset(index_id: str, indexed_asset_id: str) -> dict:
    """Current state of an indexing job — poll this until it settles."""
    return _request("GET", f"/indexes/{index_id}/indexed-assets/{indexed_asset_id}")


# Terminal states, lowercased. The API has used several spellings across
# versions, so match generously rather than pin one and hang forever on a
# synonym.
DONE_STATUSES = {"ready", "completed", "complete", "done", "indexed"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}


def job_state(state: dict) -> tuple[str, str | None]:
    """``(status, remote_video_id)`` from an indexed-asset payload.

    The provider's video id only appears once indexing completes, and has
    moved between field names — check the plausible ones rather than assume.
    """
    status = str(state.get("status") or state.get("state") or "").lower()
    video_id = (
        state.get("video_id")
        or state.get("_id")
        or state.get("id")
        or state.get("indexed_asset_id")
    )
    return status, str(video_id) if video_id else None


# ── Search ─────────────────────────────────────────────────────


def search(index_id: str, query: str, limit: int = 10) -> list[SearchHit]:
    """Natural-language search over an index, newest-best first.

    `group_by=clip` returns individual moments rather than whole videos, which
    is the shape this app already renders — a start/end range to seek to.
    """
    fields: list[tuple[str, str]] = [
        ("index_id", index_id),
        ("query_text", query),
        ("group_by", "clip"),
        ("page_limit", str(limit)),
    ]
    # Repeated field, one per modality — see `_form`.
    for option in settings.twelvelabs_modalities:
        fields.append(("search_options", option))

    body = _request("POST", "/search", form=fields)
    hits: list[SearchHit] = []
    for position, item in enumerate(body.get("data") or [], start=1):
        if not isinstance(item, dict):
            continue
        start = float(item.get("start") or 0.0)
        end = float(item.get("end") or start)
        transcription = str(item.get("transcription") or "").strip()
        hits.append(
            SearchHit(
                video_id=str(item.get("video_id") or item.get("asset_id") or ""),
                start=start,
                end=end,
                # Fall back to position: results arrive best-first, so the
                # ordering carries the ranking even if the field is absent.
                rank=int(item.get("rank") or position),
                transcription=transcription or None,
            )
        )
    return hits
