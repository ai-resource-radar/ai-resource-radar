"""Retention, vacuum and storage-maintenance policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3
from typing import Any, Callable

from .migrations import _database_bytes, _metadata_get, _metadata_set

FETCH_RUN_RETENTION_DAYS = 90
CHANGE_RETENTION_DAYS = 365
NOTIFICATION_RETENTION_DAYS = 365
POSTER_RETENTION_DAYS = 90
ABANDONED_FETCH_RUN_MINUTES = 5
VACUUM_INTERVAL_DAYS = 30
VACUUM_MIN_FREE_BYTES = 512 * 1024
VACUUM_MIN_FREE_RATIO = 0.20


@dataclass(frozen=True)
class StorageMaintenanceResult:
    status: str
    pruned_fetch_runs: int = 0
    pruned_changes: int = 0
    pruned_notifications: int = 0
    pruned_offers: int = 0
    pruned_tip_evidence: int = 0
    pruned_tip_changes: int = 0
    pruned_tips: int = 0
    vacuum_status: str = "not_needed"
    database_bytes: int = 0
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pruned_fetch_runs": self.pruned_fetch_runs,
            "pruned_changes": self.pruned_changes,
            "pruned_notifications": self.pruned_notifications,
            "pruned_offers": self.pruned_offers,
            "pruned_tip_evidence": self.pruned_tip_evidence,
            "pruned_tip_changes": self.pruned_tip_changes,
            "pruned_tips": self.pruned_tips,
            "vacuum_status": self.vacuum_status,
            "database_bytes": self.database_bytes,
            "error_code": self.error_code,
        }

def _try_vacuum(
    connection: sqlite3.Connection,
    *,
    at: datetime,
    force: bool,
) -> str:
    if not force:
        return "not_needed"
    stamp = at.astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("VACUUM")
    except sqlite3.Error:
        try:
            with connection:
                _metadata_set(connection, "vacuum_pending", "1")
        except sqlite3.Error:
            pass
        return "deferred"
    with connection:
        _metadata_set(connection, "last_vacuum_at", stamp)
        _metadata_set(connection, "vacuum_pending", "0")
    return "completed"


def _should_vacuum(
    *,
    pending: bool,
    deleted: int,
    current: datetime,
    last_vacuum: str | None,
    free_bytes: int,
    free_ratio: float,
) -> bool:
    if pending:
        return True
    if deleted <= 0:
        return False
    due = True
    if last_vacuum:
        try:
            previous = datetime.fromisoformat(last_vacuum)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=current.tzinfo)
            due = current - previous.astimezone(current.tzinfo) >= timedelta(
                days=VACUUM_INTERVAL_DAYS
            )
        except ValueError:
            due = True
    return due and (
        free_bytes >= VACUUM_MIN_FREE_BYTES
        or free_ratio >= VACUUM_MIN_FREE_RATIO
    )


def maintain_storage(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
    vacuum: Callable[..., str] | None = None,
) -> StorageMaintenanceResult:
    vacuum = vacuum or _try_vacuum
    current = (now or datetime.now().astimezone()).astimezone()
    run_cutoff = (current - timedelta(days=FETCH_RUN_RETENTION_DAYS)).isoformat(
        timespec="seconds"
    )
    history_cutoff = (current - timedelta(days=CHANGE_RETENTION_DAYS)).isoformat(
        timespec="seconds"
    )
    notification_cutoff = (
        current - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    ).isoformat(timespec="seconds")
    try:
        with connection:
            run_cursor = connection.execute(
                "DELETE FROM fetch_runs WHERE julianday(started_at) < julianday(?)",
                (run_cutoff,),
            )
            change_cursor = connection.execute(
                """
                DELETE FROM offer_changes
                WHERE julianday(detected_at) < julianday(?)
                  AND NOT (
                    importance = 'high'
                    AND EXISTS (
                        SELECT 1 FROM offers o
                        WHERE o.offer_id = offer_changes.offer_id
                          AND o.offer_type != 'pricing_reference'
                    )
                  )
                """,
                (history_cutoff,),
            )
            notification_cursor = connection.execute(
                """
                DELETE FROM notifications
                WHERE status IN ('delivered', 'read')
                  AND julianday(COALESCE(read_at, delivered_at, created_at))
                      < julianday(?)
                """,
                (notification_cutoff,),
            )
            offer_cursor = connection.execute(
                """
                DELETE FROM offers
                WHERE status = 'inactive'
                  AND offer_type = 'pricing_reference'
                  AND julianday(last_changed_at) < julianday(?)
                  AND NOT EXISTS (
                      SELECT 1 FROM offer_changes c
                      WHERE c.offer_id = offers.offer_id
                  )
                """,
                (history_cutoff,),
            )
            tip_evidence_cursor = connection.execute(
                """
                DELETE FROM tip_evidence
                WHERE julianday(fetched_at) < julianday(?)
                  AND tip_id IN (
                    SELECT tip_id FROM tips WHERE status != 'approved'
                  )
                """,
                (history_cutoff,),
            )
            tip_change_cursor = connection.execute(
                """
                DELETE FROM tip_changes
                WHERE julianday(changed_at) < julianday(?)
                  AND importance != 'high'
                """,
                (history_cutoff,),
            )
            tip_cursor = connection.execute(
                """
                DELETE FROM tips
                WHERE status IN ('candidate', 'rejected', 'retired')
                  AND julianday(updated_at) < julianday(?)
                  AND NOT EXISTS (
                    SELECT 1 FROM tip_changes c
                    WHERE c.tip_id = tips.tip_id AND c.importance = 'high'
                  )
                """,
                (history_cutoff,),
            )
            _metadata_set(
                connection,
                "last_maintenance_at",
                current.isoformat(timespec="seconds"),
            )
        pruned_fetch_runs = max(0, run_cursor.rowcount)
        pruned_changes = max(0, change_cursor.rowcount)
        pruned_notifications = max(0, notification_cursor.rowcount)
        pruned_offers = max(0, offer_cursor.rowcount)
        pruned_tip_evidence = max(0, tip_evidence_cursor.rowcount)
        pruned_tip_changes = max(0, tip_change_cursor.rowcount)
        pruned_tips = max(0, tip_cursor.rowcount)
    except sqlite3.Error:
        return StorageMaintenanceResult(
            status="failed",
            database_bytes=_database_bytes(connection),
            error_code="storage_prune_failed",
        )

    deleted = (
        pruned_fetch_runs
        + pruned_changes
        + pruned_notifications
        + pruned_offers
        + pruned_tip_evidence
        + pruned_tip_changes
        + pruned_tips
    )
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    free_bytes = page_size * free_pages
    free_ratio = free_pages / page_count if page_count else 0.0
    last_vacuum = _metadata_get(connection, "last_vacuum_at")
    pending = _metadata_get(connection, "vacuum_pending") == "1"
    should_vacuum = _should_vacuum(
        pending=pending,
        deleted=deleted,
        current=current,
        last_vacuum=last_vacuum,
        free_bytes=free_bytes,
        free_ratio=free_ratio,
    )
    vacuum_status = vacuum(
        connection,
        at=current,
        force=should_vacuum,
    )
    return StorageMaintenanceResult(
        status="completed" if vacuum_status != "deferred" else "partial",
        pruned_fetch_runs=pruned_fetch_runs,
        pruned_changes=pruned_changes,
        pruned_notifications=pruned_notifications,
        pruned_offers=pruned_offers,
        pruned_tip_evidence=pruned_tip_evidence,
        pruned_tip_changes=pruned_tip_changes,
        pruned_tips=pruned_tips,
        vacuum_status=vacuum_status,
        database_bytes=_database_bytes(connection),
        error_code=("storage_vacuum_deferred" if vacuum_status == "deferred" else None),
    )


def storage_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "database_bytes": _database_bytes(connection),
        "retention": {
            "fetch_runs_days": FETCH_RUN_RETENTION_DAYS,
            "ordinary_changes_days": CHANGE_RETENTION_DAYS,
            "delivered_notifications_days": NOTIFICATION_RETENTION_DAYS,
            "daily_posters_days": POSTER_RETENTION_DAYS,
            "important_free_changes": "forever",
            "tip_candidates_days": CHANGE_RETENTION_DAYS,
            "approved_tips": "until_retired",
        },
        "posters": {
            "count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM daily_reports WHERE status = 'success'"
                ).fetchone()[0]
            ),
            "bytes": int(
                connection.execute(
                    "SELECT COALESCE(SUM(image_bytes), 0) FROM daily_reports "
                    "WHERE status = 'success'"
                ).fetchone()[0]
            ),
        },
        "tips": {
            "count": int(connection.execute("SELECT COUNT(*) FROM tips").fetchone()[0]),
            "approved": int(
                connection.execute(
                    "SELECT COUNT(*) FROM tips WHERE status = 'approved'"
                ).fetchone()[0]
            ),
        },
        "history_rebuilt_at": _metadata_get(connection, "history_rebuilt_at"),
        "schema_migrated_at": _metadata_get(connection, "schema_migrated_at"),
        "last_maintenance_at": _metadata_get(connection, "last_maintenance_at"),
        "last_vacuum_at": _metadata_get(connection, "last_vacuum_at"),
        "vacuum_pending": _metadata_get(connection, "vacuum_pending") == "1",
    }

__all__ = ["StorageMaintenanceResult", "maintain_storage", "storage_summary"]
