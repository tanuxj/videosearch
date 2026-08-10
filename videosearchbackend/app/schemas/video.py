from pydantic import BaseModel


class VideoItem(BaseModel):
    """A single video search result."""

    id: str
    title: str
    channel: str
    category: str
    duration: str
    views: int
    published: str


class SearchResponse(BaseModel):
    """Response envelope for the search endpoint."""

    query: str
    count: int
    items: list[VideoItem]
