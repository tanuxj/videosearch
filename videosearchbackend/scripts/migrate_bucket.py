"""Copy every object referenced by the videos table from one R2 bucket to another.

    uv run python scripts/migrate_bucket.py --source safeguard --dest searchinvideo
    uv run python scripts/migrate_bucket.py --source safeguard --dest searchinvideo --apply

Dry run by default. Keys are preserved exactly, so `videos.storage_key` stays
valid and nothing needs re-indexing — the only change is which bucket the
backend and the streaming Worker point at.

Copies happen server-side (`CopyObject`), so no bytes travel via this machine.
Every copy is verified by comparing size and ETag against the source, and the
originals are left untouched so a rollback is just reverting the config.
"""

import argparse
import asyncio
import sys

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from sqlalchemy import select

import app.db.metadata  # noqa: F401 — registers models so FKs resolve
from app.core.config import get_settings
from app.db.session import SessionFactory, engine
from app.videos.models import Video

settings = get_settings()


def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name=settings.r2_region,
        config=BotoConfig(signature_version="s3v4"),
    )


async def referenced_keys() -> list[tuple[str, str]]:
    """Every (key, label) the database expects to find in storage."""
    async with SessionFactory() as session:
        rows = (await session.execute(select(Video))).scalars().all()
        keys = []
        for video in rows:
            keys.append((video.storage_key, f"{video.name} [{video.status}]"))
            if video.poster_key:
                keys.append((video.poster_key, f"{video.name} (poster)"))
    await engine.dispose()
    return keys


def head(s3, bucket: str, key: str) -> dict | None:
    try:
        response = s3.head_object(Bucket=bucket, Key=key)
    except ClientError:
        return None
    return {"size": response["ContentLength"], "etag": response["ETag"].strip('"')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--apply", action="store_true", help="Actually copy (default: dry run)")
    args = parser.parse_args()

    if args.source == args.dest:
        print("source and dest are the same bucket")
        return 1

    s3 = client()
    keys = asyncio.run(referenced_keys())
    print(f"{len(keys)} object(s) referenced by the database\n")

    copied = skipped = missing = failed = 0
    total_bytes = 0

    for key, label in keys:
        source = head(s3, args.source, key)
        if source is None:
            print(f"  [--] MISSING in {args.source}: {label}")
            missing += 1
            continue

        existing = head(s3, args.dest, key)
        if existing and existing["size"] == source["size"]:
            print(f"  [ok] already in {args.dest}: {label} ({source['size']:,} B)")
            skipped += 1
            continue

        if not args.apply:
            print(f"  [->] would copy: {label} ({source['size']:,} B)")
            copied += 1
            total_bytes += source["size"]
            continue

        try:
            s3.copy_object(
                Bucket=args.dest,
                Key=key,
                CopySource={"Bucket": args.source, "Key": key},
            )
        except ClientError as exc:
            print(f"  [!!] COPY FAILED: {label} — {exc.response['Error']['Code']}")
            failed += 1
            continue

        # Verify against the source rather than trusting the copy.
        check = head(s3, args.dest, key)
        if check is None:
            print(f"  [!!] copied but not readable back: {label}")
            failed += 1
        elif check["size"] != source["size"]:
            print(
                f"  [!!] SIZE MISMATCH: {label} — {source['size']:,} → {check['size']:,}"
            )
            failed += 1
        elif check["etag"] != source["etag"]:
            # Differing ETags with identical sizes can be legitimate for
            # multipart objects, so report rather than fail outright.
            print(f"  [ok] copied (etag differs, size matches): {label} ({check['size']:,} B)")
            copied += 1
            total_bytes += check["size"]
        else:
            print(f"  [ok] copied + verified: {label} ({check['size']:,} B)")
            copied += 1
            total_bytes += check["size"]

    verb = "would copy" if not args.apply else "copied"
    print(
        f"\n{verb}: {copied} ({total_bytes:,} bytes) | already present: {skipped} | "
        f"missing at source: {missing} | failed: {failed}"
    )
    if not args.apply:
        print("Dry run — re-run with --apply to perform the copy.")
    elif failed == 0:
        print(f"\nSource objects left untouched in '{args.source}' for rollback.")
        print("Next: set R2_BUCKET_NAME and the Worker's bucket_name to the new bucket.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
