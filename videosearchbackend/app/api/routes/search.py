from fastapi import APIRouter, Query

from app.schemas.video import SearchResponse, VideoItem

router = APIRouter()

# Demo catalog — replace with a real video search integration
# (e.g. the YouTube Data API) in production.
_DEMO_VIDEOS: list[VideoItem] = [
    VideoItem(
        id="v1",
        title="Build a Video Search Engine with TypeScript — Full Walkthrough",
        channel="CodeCraft",
        category="JavaScript",
        duration="24:12",
        views=2_400_000,
        published="3 days ago",
    ),
    VideoItem(
        id="v2",
        title="React 19 New Features Explained with Live Examples",
        channel="Frontend Focus",
        category="React",
        duration="18:47",
        views=1_150_000,
        published="9 days ago",
    ),
    VideoItem(
        id="v3",
        title="Neural Networks from Scratch in 20 Minutes",
        channel="AI Academy",
        category="AI",
        duration="20:05",
        views=890_000,
        published="2 days ago",
    ),
    VideoItem(
        id="v4",
        title="TypeScript Tips: 10 Tricks You Wish You Knew Earlier",
        channel="CodeCraft",
        category="JavaScript",
        duration="10:26",
        views=1_900_000,
        published="1 day ago",
    ),
    VideoItem(
        id="v5",
        title="How Transformers Actually Work (Fully Illustrated)",
        channel="AI Academy",
        category="AI",
        duration="32:51",
        views=5_600_000,
        published="27 days ago",
    ),
]


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search videos",
    description="Returns matching videos for a search query (demo catalog).",
)
def search_videos(
    q: str = Query(default="", max_length=200, description="Search query"),
    limit: int = Query(default=12, ge=1, le=50, description="Max results"),
) -> SearchResponse:
    query = q.strip().lower()
    if not query:
        items = _DEMO_VIDEOS
    else:
        items = [
            video
            for video in _DEMO_VIDEOS
            if query in video.title.lower() or query in video.channel.lower()
        ]
    return SearchResponse(query=q.strip(), count=len(items), items=items[:limit])
