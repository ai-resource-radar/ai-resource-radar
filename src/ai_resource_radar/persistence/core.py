from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from ai_resource_radar.sources import (
    OfferObservation,
    RadarSource,
    SOURCES,
    resolve_modalities,
    official_guide,
)


from .connection import SCHEMA_VERSION, UnsupportedSchemaError
from .connection import connect as _open_connection
from .maintenance import (
    ABANDONED_FETCH_RUN_MINUTES,
    CHANGE_RETENTION_DAYS,
    FETCH_RUN_RETENTION_DAYS,
    NOTIFICATION_RETENTION_DAYS,
    POSTER_RETENTION_DAYS,
    VACUUM_INTERVAL_DAYS,
    VACUUM_MIN_FREE_BYTES,
    VACUUM_MIN_FREE_RATIO,
    StorageMaintenanceResult,
    _should_vacuum,
    _try_vacuum,
    maintain_storage as _maintenance_storage,
    storage_summary,
)
from .migrations import (
    _backfill_modality_fields,
    _columns,
    _database_bytes,
    _decode_json_list,
    _json,
    _metadata_get,
    _metadata_set,
)
from .schema import _create_v7_schema, initialize as _schema_initialize
from .repository import (
    SOURCE_FRESHNESS_STATES,
    begin_run,
    classify_offer,
    enqueue_digest,
    finish_failure,
    finish_not_modified,
    finish_skipped,
    ingest_source,
    list_changes,
    list_offers,
    mark_notification,
    pending_notifications,
    radar_summary,
    source_cache,
    source_freshness_status,
    source_is_due,
    source_statuses,
)

_VERIFICATION_RANK = {"official_api": 0, "official_page": 1, "community": 2}
_TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
_MAINLAND_RANK = {"supported": 0, "unknown": 1, "unsupported": 2}


def _initialize(connection: sqlite3.Connection) -> bool:
    """Compatibility wrapper that preserves core-level monkeypatch hooks."""

    return _schema_initialize(
        connection,
        create_v7_schema=_create_v7_schema,
        backfill_modality_fields=_backfill_modality_fields,
    )


def connect(path: Path) -> sqlite3.Connection:
    """Open a database through the focused connection module."""

    return _open_connection(path, initialize=_initialize, vacuum=_try_vacuum)


def maintain_storage(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> StorageMaintenanceResult:
    """Run retention maintenance while honoring legacy patch points."""

    return _maintenance_storage(connection, now=now, vacuum=_try_vacuum)
