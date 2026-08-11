"""Object storage: Cloudflare R2 when configured, local disk otherwise.

The rest of the app talks to this module only through `storage` (a singleton)
and the small `*_sync` helpers, so swapping the backend later (S3, MinIO,
etc.) touches exactly one file.

Two operations matter today:

* ``save_file`` — stream an uploaded file to its final home.
* ``delete`` — remove an object (used when a video row is deleted, or when a
  failed upload must clean up after itself).

Playback is served by ``stream_response``: R2 objects are streamed through the
API so the Range headers the browser needs for seeking keep working behind the
CORS/credentials setup, and local files use Starlette's ``FileResponse`` which
already implements Range requests.
"""

import logging
from pathlib import Path

from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# boto3 is heavy and only needed for the R2 backend; import lazily so the API
# still boots (and tests still run) when R2 is not configured.
try:
    import boto3
except ImportError:  # pragma: no cover - only when boto3 is not installed
    boto3 = None  # type: ignore[assignment]


class Storage:
    """Minimal object-storage facade: save, delete, stream."""

    def __init__(self) -> None:
        self._client = None
        self._bucket: str | None = None
        self._backend = settings.effective_storage_backend

        if self._backend == "r2":
            if boto3 is None:
                raise RuntimeError("boto3 is required for the r2 storage backend")
            if not settings.storage_configured:
                raise RuntimeError("R2 storage selected but R2_* settings are incomplete")
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name=settings.r2_region,
                config=BotoConfig(signature_version="s3v4"),
            )
            self._bucket = settings.r2_bucket_name
            logger.info(
                "Object storage: Cloudflare R2 (bucket=%s, region=%s)",
                self._bucket,
                settings.r2_region,
            )
        else:
            self._root = settings.upload_dir
            logger.info("Object storage: local disk (%s)", self._root)

    @property
    def backend(self) -> str:
        return self._backend

    def _local_path(self, key: str) -> Path:
        """Resolve an object key under the upload root, refusing escapes."""
        root = self._root.resolve()
        candidate = (root / key).resolve()
        if not (candidate == root or root in candidate.parents):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage key",
            )
        return candidate

    def save_file(self, key: str, source, content_type: str | None) -> None:
        """Persist a file-like object under `key`.

        `source` may be a sync file-like (Starlette's SpooledTemporaryFile),
        which is what a multipart upload gives us.
        """
        if self._client is not None:
            assert self._bucket is not None
            self._client.upload_fileobj(
                source,
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type or "application/octet-stream"},
            )
        else:
            path = self._local_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)

    def delete(self, key: str) -> None:
        """Remove an object. Silent when it does not exist."""
        if self._client is not None:
            assert self._bucket is not None
            self._client.delete_object(Bucket=self._bucket, Key=key)
        else:
            self._local_path(key).unlink(missing_ok=True)

    def stream_response(
        self,
        key: str,
        media_type: str | None = None,
        range_header: str | None = None,
    ) -> StreamingResponse | FileResponse:
        """An HTTP response that streams the object, honouring Range headers.

        Video players *require* byte-range support to seek. R2 objects are
        proxied through the API: the browser's ``Range`` header is forwarded to
        R2, and the ``206 Partial Content`` / ``Content-Range`` response is
        passed back. Local files use FileResponse, which handles Range natively.
        """
        if self._client is not None:
            assert self._bucket is not None
            params = {"Bucket": self._bucket, "Key": key}
            if range_header:
                params["Range"] = range_header
            try:
                obj = self._client.get_object(**params)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if (
                    code in ("InvalidRange", "InvalidArgument")
                    or exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 416
                ):
                    raise HTTPException(
                        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                        detail="Requested byte range is not satisfiable",
                    ) from exc
                raise

            # boto3 does not surface the response status or headers on the
            # body object, but they are in ResponseMetadata.HTTPHeaders.
            http_headers = obj.get("ResponseMetadata", {}).get("HTTPHeaders", {})
            headers = {"Accept-Ranges": "bytes"}
            # Forward what a video player cares about: Content-Range, length
            # and type as answered by R2 (206 partial vs 200 full).
            for name in ("content-range", "content-length", "content-type"):
                if name in http_headers:
                    headers[name] = http_headers[name]
            return StreamingResponse(
                obj["Body"],
                status_code=obj.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                media_type=media_type or headers.get("content-type") or "video/mp4",
                headers=headers,
            )
        return FileResponse(
            self._local_path(key),
            media_type=media_type or "video/mp4",
            filename=Path(key).name,
            # Play inline, never download.
            content_disposition_type="inline",
        )


storage = Storage()
