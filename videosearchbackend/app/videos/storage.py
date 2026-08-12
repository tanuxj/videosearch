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
import os
import shutil
import tempfile
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

    @property
    def presign_enabled(self) -> bool:
        """True when the browser can PUT files straight to storage.

        Only the R2 backend can hand out presigned URLs — local disk has no
        endpoint for a browser to upload to, so clients must fall back to
        the multipart path.
        """
        return self._client is not None

    def presign_put(self, key: str, content_type: str | None, expires_in: int) -> str | None:
        """A short-lived URL the browser can PUT an object straight to.

        Returns None when presigned uploads are unavailable (local backend).
        """
        if self._client is None:
            return None
        assert self._bucket is not None
        return self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type or "application/octet-stream",
            },
            ExpiresIn=expires_in,
        )

    def object_size(self, key: str) -> int | None:
        """Byte size of the stored object, or None when it does not exist."""
        if self._client is not None:
            assert self._bucket is not None
            try:
                head = self._client.head_object(Bucket=self._bucket, Key=key)
                return int(head.get("ContentLength", 0))
            except ClientError as exc:
                status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                code = exc.response.get("Error", {}).get("Code", "")
                if status_code == 404 or code == "404":
                    return None
                raise
        path = self._local_path(key)
        return path.stat().st_size if path.exists() else None

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

    def save_path(self, key: str, path: Path, content_type: str | None) -> None:
        """Persist an already-local file under `key`.

        Used when the upload was staged to disk first; boto3's ``upload_file``
        handles its own file handle, so nothing here can be left half-read.
        """
        if self._client is not None:
            assert self._bucket is not None
            self._client.upload_file(
                str(path),
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type or "application/octet-stream"},
            )
        else:
            dest = self._local_path(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)

    def spill_to_temp(self, source, suffix: str = "") -> Path:
        """Copy an uploaded file-like to a temp file and return its path.

        Lets the indexing pipeline read bytes that are already on this machine
        instead of pulling the object back out of R2 — a local disk copy costs
        far less than the ~0.36 s/MB download it replaces. The caller owns the
        returned file and must delete it.

        Call this *before* handing the stream to ``save_file``: boto3 closes the
        file object it uploads from, and a closed SpooledTemporaryFile cannot be
        re-read ("seek of closed file").
        """
        source.seek(0)
        fd, name = tempfile.mkstemp(prefix="videosearch-upload-", suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise
        return Path(name)

    def get_local_path(self, key: str) -> Path:
        """A local filesystem path holding the object's bytes.

        Local backend: the stored file itself. R2 backend: a temp file the
        caller must delete (the indexing pipeline does this in a ``finally``).
        """
        if self._client is not None:
            assert self._bucket is not None
            fd, name = tempfile.mkstemp(prefix="videosearch-", suffix=Path(key).suffix)
            os.close(fd)
            self._client.download_file(self._bucket, key, name)
            return Path(name)
        return self._local_path(key)

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
