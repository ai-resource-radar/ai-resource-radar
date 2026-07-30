from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_resource_radar.store import (
    mark_notification,
    pending_notifications,
)


def load_pending_notifications(
    path: Path, *, limit: int = 5
) -> tuple[dict[str, Any], ...]:
    return pending_notifications(path, limit=limit)


def notification_delivered(path: Path, notification_id: int) -> bool:
    return mark_notification(path, notification_id, status="delivered")


def notification_read(path: Path, notification_id: int) -> bool:
    return mark_notification(path, notification_id, status="read")
