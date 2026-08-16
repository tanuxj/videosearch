"""Response models for the notifications routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: uuid.UUID
    # One of app.notifications.models.NOTIFICATION_KINDS — `indexed` today.
    kind: str
    read: bool
    created_at: datetime
    video_id: uuid.UUID
    # Resolved by the service so the bell can render without a second fetch.
    video_name: str


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    # The bell's badge — a separate count call would double every poll.
    unread: int
