"""Collection routes: create, rename, delete, and file videos in or out.

Collections are how a growing library stays navigable. They are many-to-many,
so the same video can sit in "Lectures" and "To review" at once — the UI can
present them as folders or as tags without the backend caring which.

Deleting a collection never deletes its videos; see ``models.py`` for the
cascade rules.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import MessageResponse
from app.collections import service as collections_service
from app.collections.schemas import (
    CollectionCreateIn,
    CollectionListOut,
    CollectionOut,
    CollectionUpdateIn,
    CollectionVideosIn,
    CollectionVideosOut,
)

router = APIRouter(prefix="/collections", tags=["collections"])


def _duplicate_name(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"You already have a collection called “{name}”.",
    )


def _not_found(collection_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Collection {collection_id} not found",
    )


@router.get(
    "",
    response_model=CollectionListOut,
    summary="List collections",
    description="Every collection you own, alphabetically, each with its video count.",
)
async def list_collections(user: CurrentUser, db: DbSession) -> CollectionListOut:
    rows = await collections_service.list_collections(db, user.id)
    items = [
        CollectionOut.model_validate(collection).model_copy(update={"video_count": count})
        for collection, count in rows
    ]
    return CollectionListOut(items=items, count=len(items))


@router.post(
    "",
    response_model=CollectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a collection",
    description="Opens an empty collection. Names are unique per user, ignoring case.",
    responses={409: {"description": "You already have a collection with that name"}},
)
async def create_collection(
    user: CurrentUser, db: DbSession, payload: CollectionCreateIn
) -> CollectionOut:
    try:
        collection = await collections_service.create_collection(
            db, owner_id=user.id, name=payload.name
        )
    except collections_service.DuplicateCollectionName as exc:
        raise _duplicate_name(payload.name) from exc
    return CollectionOut.model_validate(collection)


@router.patch(
    "/{collection_id}",
    response_model=CollectionOut,
    summary="Rename a collection",
    responses={
        404: {"description": "No such collection"},
        409: {"description": "You already have a collection with that name"},
    },
)
async def rename_collection(
    user: CurrentUser,
    db: DbSession,
    collection_id: uuid.UUID,
    payload: CollectionUpdateIn,
) -> CollectionOut:
    try:
        collection = await collections_service.rename_collection(
            db, user.id, collection_id, name=payload.name
        )
    except collections_service.CollectionNotFound as exc:
        raise _not_found(collection_id) from exc
    except collections_service.DuplicateCollectionName as exc:
        raise _duplicate_name(payload.name) from exc
    return CollectionOut.model_validate(collection)


@router.delete(
    "/{collection_id}",
    response_model=MessageResponse,
    summary="Delete a collection",
    description=(
        "Removes the collection and its membership rows. The videos inside it "
        "are left untouched and stay in your library."
    ),
    responses={404: {"description": "No such collection"}},
)
async def delete_collection(
    user: CurrentUser, db: DbSession, collection_id: uuid.UUID
) -> MessageResponse:
    try:
        await collections_service.delete_collection(db, user.id, collection_id)
    except collections_service.CollectionNotFound as exc:
        raise _not_found(collection_id) from exc
    return MessageResponse(detail="Collection deleted")


@router.post(
    "/{collection_id}/videos",
    response_model=CollectionVideosOut,
    summary="Add videos to a collection",
    description=(
        "Files the given videos into the collection. Re-adding a video that is "
        "already a member is a no-op, and ids you don't own are skipped — the "
        "response says how many landed."
    ),
    responses={404: {"description": "No such collection"}},
)
async def add_videos(
    user: CurrentUser,
    db: DbSession,
    collection_id: uuid.UUID,
    payload: CollectionVideosIn,
) -> CollectionVideosOut:
    try:
        count = await collections_service.add_videos(db, user.id, collection_id, payload.video_ids)
    except collections_service.CollectionNotFound as exc:
        raise _not_found(collection_id) from exc
    return CollectionVideosOut(count=count)


# POST rather than DELETE: the payload is a list of ids, and request bodies on
# DELETE are poorly supported by proxies and `fetch` alike.
@router.post(
    "/{collection_id}/videos/remove",
    response_model=CollectionVideosOut,
    summary="Remove videos from a collection",
    description=(
        "Unfiles the given videos. The videos themselves are not deleted — they "
        "stay in your library, just not in this collection."
    ),
    responses={404: {"description": "No such collection"}},
)
async def remove_videos(
    user: CurrentUser,
    db: DbSession,
    collection_id: uuid.UUID,
    payload: CollectionVideosIn,
) -> CollectionVideosOut:
    try:
        count = await collections_service.remove_videos(
            db, user.id, collection_id, payload.video_ids
        )
    except collections_service.CollectionNotFound as exc:
        raise _not_found(collection_id) from exc
    return CollectionVideosOut(count=count)
