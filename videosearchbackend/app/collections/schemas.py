"""Request and response models for the collection routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.collections.models import NAME_MAX_LENGTH


class CollectionOut(BaseModel):
    """A collection plus how many videos are filed in it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # Filled in by the route from the same query that loaded the row, so the
    # sidebar can show "Lectures · 12" without a second request per entry.
    video_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollectionListOut(BaseModel):
    items: list[CollectionOut]
    count: int = Field(description="Number of collections returned.")


class CollectionCreateIn(BaseModel):
    """A new, empty collection. Names are unique per user, ignoring case."""

    name: str = Field(
        min_length=1,
        max_length=NAME_MAX_LENGTH,
        examples=["Lectures"],
    )


class CollectionUpdateIn(BaseModel):
    """A new name for an existing collection."""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH, examples=["Archive"])


class CollectionVideosIn(BaseModel):
    """Videos to file into (or out of) a collection.

    Ids the user doesn't own are skipped rather than rejected — one stale id in
    a bulk selection shouldn't sink the other thirty-nine. `count` in the
    response says how many actually landed.
    """

    video_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class CollectionVideosOut(BaseModel):
    """How many memberships the request actually changed."""

    count: int = Field(description="Videos added to, or removed from, the collection.")
