"""Notification routes: the bell's list and mark-read endpoints.

Read-only except for marking read — notifications are written by the indexing
pipeline, never by an API caller.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import MessageResponse
from app.notifications import service as notifications_service
from app.notifications.schemas import NotificationListOut, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=NotificationListOut,
    summary="List my notifications",
    description=(
        "The caller's notifications, newest first, plus the unread count "
        "for the bell's badge."
    ),
)
async def list_notifications(user: CurrentUser, db: DbSession) -> NotificationListOut:
    rows = await notifications_service.list_notifications(db, user.id)
    unread = await notifications_service.unread_count(db, user.id)
    return NotificationListOut(
        items=[
            NotificationOut(
                id=notification.id,
                kind=notification.kind,
                read=notification.read,
                created_at=notification.created_at,
                video_id=notification.video_id,
                video_name=name,
            )
            for notification, name in rows
        ],
        unread=unread,
    )


@router.post(
    "/read-all",
    response_model=MessageResponse,
    summary="Mark all notifications read",
    description="Clears the bell's badge in one call.",
)
async def mark_all_read(user: CurrentUser, db: DbSession) -> MessageResponse:
    count = await notifications_service.mark_all_read(db, user.id)
    return MessageResponse(detail=f"Marked {count} notifications read")


@router.post(
    "/{notification_id}/read",
    response_model=MessageResponse,
    summary="Mark one notification read",
    responses={404: {"description": "Notification not found"}},
)
async def mark_read(
    user: CurrentUser, db: DbSession, notification_id: uuid.UUID
) -> MessageResponse:
    notification = await notifications_service.mark_read(db, user.id, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return MessageResponse(detail="Marked read")
