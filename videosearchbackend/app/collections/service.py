"""Collection CRUD and membership changes.

Kept free of FastAPI types, matching the video and saved-clip services: these
functions raise domain errors and the route layer decides the HTTP status.

Every query is scoped on `owner_id`, so a leaked collection or video id can
never read or mutate another user's library — the route layer's ownership
check is a second line of defence, not the only one.

Membership is read and written through explicit ``CollectionVideo`` queries
rather than a ``relationship(secondary=…)``. Under async SQLAlchemy a lazy
collection load raises rather than emitting SQL, so the explicit form is both
safer and cheaper here: the two access patterns the UI actually has
(collection → count, videos → their collection ids) are each one flat query.
"""

import logging
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import Collection, CollectionVideo
from app.videos.models import Video
from app.workspaces import service as workspaces_service

logger = logging.getLogger(__name__)


class CollectionNotFound(Exception):
    """No such collection, or it belongs to someone else (same 404)."""


class DuplicateCollectionName(Exception):
    """The owner already has a collection with that name (case-insensitive)."""


async def list_collections(db: AsyncSession, owner_id: uuid.UUID) -> list[tuple[Collection, int]]:
    """Every collection the user owns, with its video count, A–Z.

    An outer join so a freshly created, still-empty collection comes back with
    a count of 0 instead of vanishing from the sidebar.
    """
    result = await db.execute(
        select(Collection, func.count(CollectionVideo.video_id))
        .outerjoin(CollectionVideo, CollectionVideo.collection_id == Collection.id)
        .where(Collection.owner_id == owner_id)
        .group_by(Collection.id)
        .order_by(func.lower(Collection.name).asc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_collection(
    db: AsyncSession, owner_id: uuid.UUID, collection_id: uuid.UUID
) -> Collection:
    """Fetch one collection, enforcing ownership (404 either way)."""
    collection = await db.get(Collection, collection_id)
    if collection is None or collection.owner_id != owner_id:
        raise CollectionNotFound(collection_id)
    return collection


async def create_collection(db: AsyncSession, *, owner_id: uuid.UUID, name: str) -> Collection:
    """Open a new, empty collection.

    The name clash is caught from the database rather than pre-checked with a
    SELECT: the unique index is the real authority, and a check-then-insert
    would still race two concurrent creates against each other.
    """
    collection = Collection(owner_id=owner_id, name=name.strip())
    db.add(collection)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateCollectionName(name) from exc
    await db.refresh(collection)
    logger.info("Collection created: %s (%r)", collection.id, collection.name)
    return collection


async def rename_collection(
    db: AsyncSession,
    owner_id: uuid.UUID,
    collection_id: uuid.UUID,
    *,
    name: str,
) -> Collection:
    collection = await get_collection(db, owner_id, collection_id)
    collection.name = name.strip()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateCollectionName(name) from exc
    await db.refresh(collection)
    logger.info("Collection renamed: %s (%r)", collection_id, collection.name)
    return collection


async def delete_collection(
    db: AsyncSession, owner_id: uuid.UUID, collection_id: uuid.UUID
) -> None:
    """Delete the collection and its membership rows — never the videos."""
    collection = await get_collection(db, owner_id, collection_id)
    await db.delete(collection)
    await db.commit()
    logger.info("Collection deleted: %s", collection_id)


async def _owned_video_ids(
    db: AsyncSession, owner_id: uuid.UUID, video_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Narrow `video_ids` to the ones this user may file.

    "May file" is the same rule as "may see": their own videos plus videos
    in workspaces they belong to — a workspace member should be able to file
    a shared video into their own collections. Silently dropping the rest is
    deliberate: a bulk "add these 40 videos" where one id is stale (or not
    shared with them) should file the other 39, not 400 the whole request.
    """
    if not video_ids:
        return []
    workspace_ids = await workspaces_service.accessible_workspace_ids(db, owner_id)
    result = await db.execute(
        select(Video.id).where(
            Video.id.in_(video_ids),
            or_(
                Video.owner_id == owner_id,
                Video.workspace_id.in_(workspace_ids) if workspace_ids else False,
            ),
        )
    )
    return list(result.scalars())


async def add_videos(
    db: AsyncSession,
    owner_id: uuid.UUID,
    collection_id: uuid.UUID,
    video_ids: list[uuid.UUID],
) -> int:
    """File videos into a collection. Returns how many are now members.

    Idempotent: re-adding a video the collection already holds is a no-op
    (``ON CONFLICT DO NOTHING`` against the composite primary key), so the
    frontend can re-send a whole selection without checking first.
    """
    await get_collection(db, owner_id, collection_id)
    owned = await _owned_video_ids(db, owner_id, video_ids)
    if not owned:
        return 0

    await db.execute(
        pg_insert(CollectionVideo)
        .values([{"collection_id": collection_id, "video_id": vid} for vid in owned])
        .on_conflict_do_nothing(index_elements=["collection_id", "video_id"])
    )
    await db.commit()
    logger.info("Added %d videos to collection %s", len(owned), collection_id)
    return len(owned)


async def remove_videos(
    db: AsyncSession,
    owner_id: uuid.UUID,
    collection_id: uuid.UUID,
    video_ids: list[uuid.UUID],
) -> int:
    """Unfile videos from a collection. The videos themselves are untouched."""
    await get_collection(db, owner_id, collection_id)
    if not video_ids:
        return 0

    result = await db.execute(
        delete(CollectionVideo).where(
            CollectionVideo.collection_id == collection_id,
            CollectionVideo.video_id.in_(video_ids),
        )
    )
    await db.commit()
    removed = result.rowcount or 0
    logger.info("Removed %d videos from collection %s", removed, collection_id)
    return removed


async def collection_ids_for(
    db: AsyncSession, video_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Map each video id to the collections holding it.

    One query for the whole page of videos rather than one per card — the
    library grid would otherwise fire N round trips to draw its chips.
    Videos in no collection are absent from the map; callers default to [].
    """
    if not video_ids:
        return {}
    result = await db.execute(
        select(CollectionVideo.video_id, CollectionVideo.collection_id).where(
            CollectionVideo.video_id.in_(video_ids)
        )
    )
    mapping: dict[uuid.UUID, list[uuid.UUID]] = {}
    for video_id, collection_id in result.all():
        mapping.setdefault(video_id, []).append(collection_id)
    return mapping
