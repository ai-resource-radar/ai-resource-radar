from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
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


SCHEMA_VERSION = 5
FETCH_RUN_RETENTION_DAYS = 90
CHANGE_RETENTION_DAYS = 365
NOTIFICATION_RETENTION_DAYS = 365
POSTER_RETENTION_DAYS = 90
ABANDONED_FETCH_RUN_MINUTES = 5
VACUUM_INTERVAL_DAYS = 30
VACUUM_MIN_FREE_BYTES = 512 * 1024
VACUUM_MIN_FREE_RATIO = 0.20
_VERIFICATION_RANK = {"official_api": 0, "official_page": 1, "community": 2}
_TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
_MAINLAND_RANK = {"supported": 0, "unknown": 1, "unsupported": 2}


class UnsupportedSchemaError(sqlite3.DatabaseError):
    def __init__(self, database_version: int, supported_version: int) -> None:
        super().__init__("ai_radar_schema_unsupported")
        self.database_version = int(database_version)
        self.supported_version = int(supported_version)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


@dataclass(frozen=True)
class StorageMaintenanceResult:
    status: str
    pruned_fetch_runs: int = 0
    pruned_changes: int = 0
    pruned_notifications: int = 0
    pruned_offers: int = 0
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
            "vacuum_status": self.vacuum_status,
            "database_bytes": self.database_bytes,
            "error_code": self.error_code,
        }


def _metadata_get(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM radar_metadata WHERE key = ?", (key,)
    ).fetchone()
    return str(row[0]) if row else None


def _metadata_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO radar_metadata(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _database_bytes(connection: sqlite3.Connection) -> int:
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    return page_size * page_count


def _decode_json_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _backfill_modality_fields(connection: sqlite3.Connection) -> None:
    """Populate schema-v5 modality columns without misclassifying vision.

    The canonical fingerprint is recalculated so that the next successful
    refresh does not report a synthetic update caused only by the migration.
    """

    required = {
        "input_modalities_json",
        "output_modalities_json",
        "free_image_generation",
    }
    if not required <= _columns(connection, "offers"):
        return
    rows = connection.execute("SELECT * FROM offers").fetchall()
    for row in rows:
        try:
            details = json.loads(row["details_json"] or "{}")
        except (TypeError, ValueError):
            details = {}
        if not isinstance(details, dict):
            details = {}
        inputs, outputs = resolve_modalities(details)
        inputs = inputs or _decode_json_list(row["input_modalities_json"])
        outputs = outputs or _decode_json_list(row["output_modalities_json"])
        free_image = (
            str(row["kind"]) == "token"
            and str(row["offer_type"]) in {"recurring_free", "variable_free"}
            and "image" in outputs
        )
        try:
            reasons = json.loads(row["priority_reasons_json"] or "[]")
        except (TypeError, ValueError):
            reasons = []
        payload = {
            "offer_id": row["offer_id"],
            "provider": row["provider"],
            "title": row["title"],
            "kind": row["kind"],
            "offer_type": row["offer_type"],
            "quota_value": row["quota_value"],
            "quota_unit": row["quota_unit"],
            "reset_period": row["reset_period"],
            "estimated_usd_value": row["estimated_usd_value"],
            "requires_card": row["requires_card"],
            "requires_phone": row["requires_phone"],
            "eligibility": row["eligibility"],
            "mainland_status": row["mainland_status"],
            "expires_at": row["expires_at"],
            "homepage_url": row["homepage_url"],
            "verification_level": row["verification_level"],
            "priority_tier": row["priority_tier"],
            "priority_reasons": reasons,
            "details": details,
            "input_modalities": list(inputs),
            "output_modalities": list(outputs),
            "free_image_generation": free_image,
        }
        fingerprint = hashlib.sha256(_json(payload).encode()).hexdigest()
        connection.execute(
            """
            UPDATE offers SET input_modalities_json = ?,
                output_modalities_json = ?, free_image_generation = ?,
                fingerprint = ? WHERE offer_id = ?
            """,
            (
                _json(list(inputs)),
                _json(list(outputs)),
                int(free_image),
                fingerprint,
                row["offer_id"],
            ),
        )


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        migrated = _initialize(connection)
    except Exception:
        connection.close()
        raise
    if migrated:
        _try_vacuum(
            connection,
            at=datetime.now().astimezone(),
            force=True,
        )
    return connection


def _initialize(connection: sqlite3.Connection) -> bool:
    previous_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if previous_version > SCHEMA_VERSION:
        raise UnsupportedSchemaError(previous_version, SCHEMA_VERSION)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            license TEXT NOT NULL,
            kind TEXT NOT NULL,
            etag TEXT,
            last_modified TEXT,
            last_attempt_at TEXT,
            last_success_at TEXT,
            last_error_code TEXT
        );
        CREATE TABLE IF NOT EXISTS fetch_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL REFERENCES sources(source_id),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            http_status INTEGER,
            content_hash TEXT,
            item_count INTEGER NOT NULL DEFAULT 0,
            error_code TEXT
        );
        """
    )
    source_columns = _columns(connection, "sources")
    for name, declaration in (
        ("authority", "TEXT NOT NULL DEFAULT 'community'"),
        ("cadence_hours", "INTEGER NOT NULL DEFAULT 24"),
        ("format", "TEXT NOT NULL DEFAULT 'json'"),
        ("consecutive_failures", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in source_columns:
            connection.execute(f"ALTER TABLE sources ADD COLUMN {name} {declaration}")
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS fetch_runs_source_started
            ON fetch_runs(source_id, started_at DESC);
        CREATE TABLE IF NOT EXISTS offers (
            offer_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            offer_type TEXT NOT NULL,
            quota_value REAL,
            quota_unit TEXT,
            reset_period TEXT,
            estimated_usd_value REAL,
            requires_card TEXT NOT NULL,
            requires_phone TEXT NOT NULL,
            eligibility TEXT,
            mainland_status TEXT NOT NULL,
            expires_at TEXT,
            homepage_url TEXT NOT NULL,
            verification_level TEXT NOT NULL,
            priority_tier TEXT NOT NULL,
            priority_reasons_json TEXT NOT NULL,
            details_json TEXT NOT NULL,
            input_modalities_json TEXT NOT NULL DEFAULT '[]',
            output_modalities_json TEXT NOT NULL DEFAULT '[]',
            free_image_generation INTEGER NOT NULL DEFAULT 0
                CHECK(free_image_generation IN (0, 1)),
            fingerprint TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_changed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS offers_browse
            ON offers(status, priority_tier, kind, mainland_status, provider);
        CREATE TABLE IF NOT EXISTS offer_evidence (
            source_id TEXT NOT NULL REFERENCES sources(source_id),
            offer_id TEXT NOT NULL REFERENCES offers(offer_id) ON DELETE CASCADE,
            source_url TEXT NOT NULL,
            verification_level TEXT NOT NULL,
            evidence_excerpt TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            missing_success_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            PRIMARY KEY(source_id, offer_id)
        );
        CREATE TABLE IF NOT EXISTS offer_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            change_type TEXT NOT NULL,
            changed_fields_json TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            importance TEXT NOT NULL,
            notification_eligible INTEGER NOT NULL DEFAULT 0,
            notification_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS offer_changes_detected
            ON offer_changes(detected_at DESC, id DESC);
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            target_url TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            delivered_at TEXT,
            read_at TEXT
        );
        CREATE INDEX IF NOT EXISTS notifications_status
            ON notifications(status, created_at);
        CREATE TABLE IF NOT EXISTS radar_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_reports (
            report_date TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('running', 'success', 'failed')),
            generated_at TEXT,
            radar_refreshed_at TEXT,
            provider TEXT NOT NULL DEFAULT 'openai',
            model TEXT NOT NULL DEFAULT 'gpt-image-2',
            quality TEXT NOT NULL DEFAULT 'medium',
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            selected_facts_json TEXT NOT NULL DEFAULT '{}',
            prompt_sha256 TEXT,
            validation_json TEXT NOT NULL DEFAULT '{}',
            image_path TEXT,
            image_sha256 TEXT,
            image_bytes INTEGER NOT NULL DEFAULT 0 CHECK(image_bytes >= 0),
            error_code TEXT,
            request_id TEXT,
            notified_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS daily_reports_status_date
            ON daily_reports(status, report_date DESC);
        """
    )
    offer_columns = _columns(connection, "offers")
    modality_columns = {
        "input_modalities_json",
        "output_modalities_json",
        "free_image_generation",
    }
    needs_modality_backfill = not modality_columns <= offer_columns
    changes_object = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = 'changes'"
    ).fetchone()
    if changes_object is None:
        connection.execute(
            """
            CREATE VIEW changes AS
            SELECT id, offer_id AS external_id, detected_at, change_type,
                   NULL AS before_hash, NULL AS after_hash
            FROM offer_changes
            """
        )
    history_migration = 0 < previous_version < 3
    schema_migration = 0 < previous_version < SCHEMA_VERSION
    if (
        schema_migration or history_migration or needs_modality_backfill
    ) and not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    with connection:
        # ALTER, backfill, metadata and user_version form the transactional
        # v4 -> v5 migration. SQLite rolls the whole block back on failure.
        for name, declaration in (
            ("input_modalities_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("output_modalities_json", "TEXT NOT NULL DEFAULT '[]'"),
            (
                "free_image_generation",
                "INTEGER NOT NULL DEFAULT 0 "
                "CHECK(free_image_generation IN (0, 1))",
            ),
        ):
            if name not in offer_columns:
                connection.execute(
                    f"ALTER TABLE offers ADD COLUMN {name} {declaration}"
                )
        if schema_migration or needs_modality_backfill:
            _backfill_modality_fields(connection)
        if history_migration:
            if changes_object is not None and changes_object["type"] == "table":
                connection.execute("DROP TABLE changes")
                connection.execute(
                    """
                    CREATE VIEW changes AS
                    SELECT id, offer_id AS external_id, detected_at, change_type,
                           NULL AS before_hash, NULL AS after_hash
                    FROM offer_changes
                    """
                )
            connection.execute("DELETE FROM offer_changes")
            connection.execute("DELETE FROM notifications")
            connection.execute("DELETE FROM fetch_runs")
            connection.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('changes', 'offer_changes', 'notifications', 'fetch_runs')"
            )
            migrated_at = datetime.now().astimezone().isoformat(timespec="seconds")
            _metadata_set(connection, "history_rebuilt_at", migrated_at)
            _metadata_set(connection, "vacuum_pending", "1")
        if schema_migration:
            _metadata_set(
                connection,
                "schema_migrated_at",
                datetime.now().astimezone().isoformat(timespec="seconds"),
            )
        connection.executemany(
            """
            INSERT INTO sources(
                source_id, name, url, license, kind, authority, cadence_hours, format
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name = excluded.name,
                url = excluded.url,
                license = excluded.license,
                kind = excluded.kind,
                authority = excluded.authority,
                cadence_hours = excluded.cadence_hours,
                format = excluded.format
            """,
            [
                (
                    source.id,
                    source.name,
                    source.url,
                    source.license,
                    source.kind,
                    source.authority,
                    source.cadence_hours,
                    source.format,
                )
                for source in SOURCES
            ],
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return schema_migration or history_migration


def source_cache(
    connection: sqlite3.Connection, source_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT etag, last_modified, last_success_at, cadence_hours
        FROM sources WHERE source_id = ?
        """,
        (source_id,),
    ).fetchone()


def source_is_due(
    cache: sqlite3.Row | None, *, now: datetime, force: bool
) -> bool:
    if force or cache is None or not cache["last_success_at"]:
        return True
    try:
        last = datetime.fromisoformat(str(cache["last_success_at"]))
    except ValueError:
        return True
    return now.astimezone() - last.astimezone() >= timedelta(
        hours=int(cache["cadence_hours"])
    )


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
) -> StorageMaintenanceResult:
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
            _metadata_set(
                connection,
                "last_maintenance_at",
                current.isoformat(timespec="seconds"),
            )
        pruned_fetch_runs = max(0, run_cursor.rowcount)
        pruned_changes = max(0, change_cursor.rowcount)
        pruned_notifications = max(0, notification_cursor.rowcount)
        pruned_offers = max(0, offer_cursor.rowcount)
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
    vacuum_status = _try_vacuum(
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
        "history_rebuilt_at": _metadata_get(connection, "history_rebuilt_at"),
        "schema_migrated_at": _metadata_get(connection, "schema_migrated_at"),
        "last_maintenance_at": _metadata_get(connection, "last_maintenance_at"),
        "last_vacuum_at": _metadata_get(connection, "last_vacuum_at"),
        "vacuum_pending": _metadata_get(connection, "vacuum_pending") == "1",
    }


def begin_run(
    connection: sqlite3.Connection, source_id: str, started_at: str
) -> tuple[int, bool]:
    baseline = (
        connection.execute(
            """
            SELECT COUNT(*) FROM fetch_runs
            WHERE source_id = ? AND status IN ('success', 'not_modified')
            """,
            (source_id,),
        ).fetchone()[0]
        == 0
    )
    with connection:
        connection.execute(
            """
            UPDATE sources
            SET last_attempt_at = ?
            WHERE source_id = ?
            """,
            (started_at, source_id),
        )
        cursor = connection.execute(
            """
            INSERT INTO fetch_runs(source_id, started_at, status)
            VALUES (?, ?, 'running')
            """,
            (source_id, started_at),
        )
    return int(cursor.lastrowid), baseline


def finish_skipped(
    connection: sqlite3.Connection, source_id: str, at: str
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO fetch_runs(
                source_id, started_at, finished_at, status, item_count
            )
            VALUES (?, ?, ?, 'skipped_not_due', 0)
            """,
            (source_id, at, at),
        )


def finish_not_modified(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    run_id: int,
    at: str,
) -> int:
    with connection:
        connection.execute(
            """
            UPDATE sources
            SET last_success_at = ?, last_error_code = NULL, consecutive_failures = 0
            WHERE source_id = ?
            """,
            (at, source_id),
        )
        connection.execute(
            """
            UPDATE offer_evidence SET observed_at = ?
            WHERE source_id = ? AND is_active = 1
            """,
            (at, source_id),
        )
        connection.execute(
            """
            UPDATE fetch_runs
            SET finished_at = ?, status = 'not_modified', http_status = 304
            WHERE id = ?
            """,
            (at, run_id),
        )
    return int(
        connection.execute(
            """
            SELECT COUNT(*) FROM offer_evidence
            WHERE source_id = ? AND is_active = 1
            """,
            (source_id,),
        ).fetchone()[0]
    )


def finish_failure(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    run_id: int,
    at: str,
    error_code: str,
    verification_pending: bool,
) -> None:
    status = "verification_pending" if verification_pending else "failed"
    with connection:
        connection.execute(
            """
            UPDATE sources
            SET last_error_code = ?, consecutive_failures = consecutive_failures + 1
            WHERE source_id = ?
            """,
            (error_code, source_id),
        )
        connection.execute(
            """
            UPDATE fetch_runs
            SET finished_at = ?, status = ?, error_code = ?
            WHERE id = ?
            """,
            (at, status, error_code, run_id),
        )


def classify_offer(observation: OfferObservation) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    official = observation.verification_level in {"official_api", "official_page"}
    _, output_modalities = resolve_modalities(
        observation.details,
        output_modalities=observation.output_modalities,
    )
    free_image_generation = (
        observation.offer_type in {"recurring_free", "variable_free"}
        and observation.kind == "token"
        and "image" in output_modalities
    )
    if observation.offer_type == "pricing_reference":
        if official:
            return "D", ("官方价格已核验；不参与免费资源等级",)
        return "D", ("社区维护的价格基线；等待官方逐项核验",)
    if not official:
        return "D", ("仅社区或价格线索，尚未由官方免费规则核验",)
    reasons.append("官方来源已核验")
    if observation.requires_card == "no":
        reasons.append("无需信用卡")
    elif observation.requires_card == "yes":
        reasons.append("需要信用卡")
    else:
        reasons.append("信用卡要求待确认")
    if observation.mainland_status == "supported":
        reasons.append("官方信息未显示中国大陆限制")
    elif observation.mainland_status == "unsupported":
        reasons.append("中国大陆不在官方支持范围")
    else:
        reasons.append("中国大陆可用性待确认")
    if observation.offer_type == "recurring_free":
        reasons.append("周期性免费额度")
    elif observation.offer_type == "variable_free":
        reasons.append("免费但额度与资源动态变化")
    elif observation.offer_type == "grant":
        reasons.append("需要资格申请")
    if free_image_generation:
        reasons.append("免费图片输出能力已核验")
    if (
        observation.requires_card == "no"
        and observation.offer_type == "recurring_free"
        and observation.quota_value is not None
        and observation.mainland_status != "unsupported"
    ):
        return "A", tuple(reasons)
    if (
        observation.requires_card == "no"
        and observation.mainland_status != "unsupported"
        and observation.offer_type in {"recurring_free", "variable_free"}
    ):
        return "B", tuple(reasons)
    return "C", tuple(reasons)


def _offer_payload(
    observation: OfferObservation, tier: str, reasons: tuple[str, ...]
) -> dict[str, Any]:
    input_modalities, output_modalities = resolve_modalities(
        observation.details,
        input_modalities=observation.input_modalities,
        output_modalities=observation.output_modalities,
    )
    free_image_generation = (
        observation.offer_type in {"recurring_free", "variable_free"}
        and observation.kind == "token"
        and "image" in output_modalities
    )
    return {
        "offer_id": observation.offer_id,
        "provider": observation.provider,
        "title": observation.title,
        "kind": observation.kind,
        "offer_type": observation.offer_type,
        "quota_value": observation.quota_value,
        "quota_unit": observation.quota_unit,
        "reset_period": observation.reset_period,
        "estimated_usd_value": observation.estimated_usd_value,
        "requires_card": observation.requires_card,
        "requires_phone": observation.requires_phone,
        "eligibility": observation.eligibility,
        "mainland_status": observation.mainland_status,
        "expires_at": observation.expires_at,
        "homepage_url": observation.homepage_url,
        "verification_level": observation.verification_level,
        "priority_tier": tier,
        "priority_reasons": reasons,
        "details": observation.details,
        "input_modalities": list(input_modalities),
        "output_modalities": list(output_modalities),
        "free_image_generation": free_image_generation,
    }


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in before
        if before.get(key) != after.get(key)
    )


def _eligible_change(
    *, change_type: str, tier: str, fields: list[str], baseline: bool
) -> tuple[str, bool]:
    if baseline or tier not in {"A", "B"}:
        return "normal", False
    important_fields = {
        "quota_value",
        "quota_unit",
        "reset_period",
        "requires_card",
        "expires_at",
        "status",
    }
    if change_type in {"added", "removed"}:
        return "high", True
    eligible = bool(set(fields) & important_fields)
    return ("high" if eligible else "normal"), eligible


def ingest_source(
    connection: sqlite3.Connection,
    *,
    source: RadarSource,
    observations: tuple[OfferObservation, ...],
    at: str,
    run_id: int,
    http_status: int,
    etag: str | None,
    last_modified: str | None,
    content_hash: str,
    baseline: bool,
) -> tuple[int, int, int]:
    unique = {item.offer_id: item for item in observations}
    added = updated = removed = 0
    with connection:
        existing_evidence = {
            row["offer_id"]: row
            for row in connection.execute(
                """
                SELECT offer_id, content_hash, missing_success_count, is_active
                FROM offer_evidence WHERE source_id = ?
                """,
                (source.id,),
            )
        }
        for offer_id, observation in unique.items():
            tier, reasons = classify_offer(observation)
            payload = _offer_payload(observation, tier, reasons)
            payload_json = _json(payload)
            fingerprint = hashlib.sha256(payload_json.encode()).hexdigest()
            current = connection.execute(
                "SELECT * FROM offers WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            incoming_rank = _VERIFICATION_RANK[observation.verification_level]
            current_rank = (
                _VERIFICATION_RANK.get(str(current["verification_level"]), 9)
                if current
                else 9
            )
            can_replace = current is None or incoming_rank <= current_rank
            change_type: str | None = None
            fields: list[str] = []
            before_json: str | None = None
            after_json: str | None = None
            if current is None:
                added += 1
                change_type = "added"
            elif current["status"] != "active":
                added += 1
                change_type = "added"
            elif can_replace and current["fingerprint"] != fingerprint:
                before = {
                    key: current[key]
                    for key in (
                        "provider",
                        "title",
                        "kind",
                        "offer_type",
                        "quota_value",
                        "quota_unit",
                        "reset_period",
                        "estimated_usd_value",
                        "requires_card",
                        "requires_phone",
                        "eligibility",
                        "mainland_status",
                        "expires_at",
                        "homepage_url",
                        "verification_level",
                        "priority_tier",
                    )
                }
                before["input_modalities"] = list(
                    _decode_json_list(current["input_modalities_json"])
                )
                before["output_modalities"] = list(
                    _decode_json_list(current["output_modalities_json"])
                )
                before["free_image_generation"] = bool(
                    current["free_image_generation"]
                )
                fields = _changed_fields(before, payload)
                if fields:
                    updated += 1
                    change_type = "updated"
                    before_json = _json(
                        {field: before.get(field) for field in fields}
                    )
                    after_json = _json(
                        {field: payload.get(field) for field in fields}
                    )
            if current is None:
                connection.execute(
                    """
                    INSERT INTO offers(
                        offer_id, provider, title, kind, offer_type, quota_value,
                        quota_unit, reset_period, estimated_usd_value, requires_card,
                        requires_phone, eligibility, mainland_status, expires_at,
                        homepage_url, verification_level, priority_tier,
                        priority_reasons_json, details_json, input_modalities_json,
                        output_modalities_json, free_image_generation, fingerprint,
                        status,
                        first_seen_at, last_seen_at, last_changed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?,
                            'active', ?, ?, ?)
                    """,
                    (
                        offer_id,
                        observation.provider,
                        observation.title,
                        observation.kind,
                        observation.offer_type,
                        observation.quota_value,
                        observation.quota_unit,
                        observation.reset_period,
                        observation.estimated_usd_value,
                        observation.requires_card,
                        observation.requires_phone,
                        observation.eligibility,
                        observation.mainland_status,
                        observation.expires_at,
                        observation.homepage_url,
                        observation.verification_level,
                        tier,
                        _json(reasons),
                        _json(observation.details),
                        _json(payload["input_modalities"]),
                        _json(payload["output_modalities"]),
                        int(payload["free_image_generation"]),
                        fingerprint,
                        at,
                        at,
                        at,
                    ),
                )
            elif can_replace:
                connection.execute(
                    """
                    UPDATE offers SET
                        provider = ?, title = ?, kind = ?, offer_type = ?,
                        quota_value = ?, quota_unit = ?, reset_period = ?,
                        estimated_usd_value = ?, requires_card = ?,
                        requires_phone = ?, eligibility = ?, mainland_status = ?,
                        expires_at = ?, homepage_url = ?, verification_level = ?,
                        priority_tier = ?, priority_reasons_json = ?,
                        details_json = ?, input_modalities_json = ?,
                        output_modalities_json = ?, free_image_generation = ?,
                        fingerprint = ?, status = 'active',
                        last_seen_at = ?,
                        last_changed_at = CASE WHEN fingerprint != ? OR status != 'active'
                            THEN ? ELSE last_changed_at END
                    WHERE offer_id = ?
                    """,
                    (
                        observation.provider,
                        observation.title,
                        observation.kind,
                        observation.offer_type,
                        observation.quota_value,
                        observation.quota_unit,
                        observation.reset_period,
                        observation.estimated_usd_value,
                        observation.requires_card,
                        observation.requires_phone,
                        observation.eligibility,
                        observation.mainland_status,
                        observation.expires_at,
                        observation.homepage_url,
                        observation.verification_level,
                        tier,
                        _json(reasons),
                        _json(observation.details),
                        _json(payload["input_modalities"]),
                        _json(payload["output_modalities"]),
                        int(payload["free_image_generation"]),
                        fingerprint,
                        at,
                        fingerprint,
                        at,
                        offer_id,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE offers SET last_seen_at = ? WHERE offer_id = ?",
                    (at, offer_id),
                )
            evidence_payload = {
                "source_url": observation.source_url,
                "verification_level": observation.verification_level,
                "evidence_excerpt": observation.evidence_excerpt,
            }
            evidence_hash = hashlib.sha256(_json(evidence_payload).encode()).hexdigest()
            connection.execute(
                """
                INSERT INTO offer_evidence(
                    source_id, offer_id, source_url, verification_level,
                    evidence_excerpt, content_hash, observed_at,
                    missing_success_count, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT(source_id, offer_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    verification_level = excluded.verification_level,
                    evidence_excerpt = excluded.evidence_excerpt,
                    content_hash = excluded.content_hash,
                    observed_at = excluded.observed_at,
                    missing_success_count = 0,
                    is_active = 1
                """,
                (
                    source.id,
                    offer_id,
                    observation.source_url,
                    observation.verification_level,
                    observation.evidence_excerpt[:500],
                    evidence_hash,
                    at,
                ),
            )
            if change_type and not baseline:
                importance, eligible = _eligible_change(
                    change_type=change_type,
                    tier=tier,
                    fields=fields,
                    baseline=baseline,
                )
                connection.execute(
                    """
                    INSERT INTO offer_changes(
                        offer_id, detected_at, change_type, changed_fields_json,
                        before_json, after_json, importance, notification_eligible
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        offer_id,
                        at,
                        change_type,
                        _json(fields),
                        before_json,
                        after_json,
                        importance,
                        1 if eligible else 0,
                    ),
                )
        seen = set(unique)
        for offer_id, evidence in existing_evidence.items():
            if offer_id in seen or not evidence["is_active"]:
                continue
            missing_count = int(evidence["missing_success_count"]) + 1
            connection.execute(
                """
                UPDATE offer_evidence
                SET missing_success_count = ?, observed_at = ?,
                    is_active = CASE WHEN ? >= 2 THEN 0 ELSE 1 END
                WHERE source_id = ? AND offer_id = ?
                """,
                (missing_count, at, missing_count, source.id, offer_id),
            )
            if missing_count < 2:
                continue
            active_count = connection.execute(
                """
                SELECT COUNT(*) FROM offer_evidence
                WHERE offer_id = ? AND is_active = 1
                """,
                (offer_id,),
            ).fetchone()[0]
            offer = connection.execute(
                "SELECT * FROM offers WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            if active_count or offer is None or offer["status"] != "active":
                continue
            removed += 1
            connection.execute(
                """
                UPDATE offers SET status = 'inactive', last_changed_at = ?
                WHERE offer_id = ?
                """,
                (at, offer_id),
            )
            importance, eligible = _eligible_change(
                change_type="removed",
                tier=str(offer["priority_tier"]),
                fields=["status"],
                baseline=baseline,
            )
            if not baseline:
                connection.execute(
                    """
                    INSERT INTO offer_changes(
                        offer_id, detected_at, change_type, changed_fields_json,
                        before_json, after_json, importance, notification_eligible
                    )
                    VALUES (?, ?, 'removed', ?, NULL, NULL, ?, ?)
                    """,
                    (
                        offer_id,
                        at,
                        _json(["status"]),
                        importance,
                        1 if eligible else 0,
                    ),
                )
        connection.execute(
            """
            UPDATE sources SET
                etag = ?, last_modified = ?, last_success_at = ?,
                last_error_code = NULL, consecutive_failures = 0
            WHERE source_id = ?
            """,
            (etag, last_modified, at, source.id),
        )
        connection.execute(
            """
            UPDATE fetch_runs SET
                finished_at = ?, status = 'success', http_status = ?,
                content_hash = ?, item_count = ?
            WHERE id = ?
            """,
            (at, http_status, content_hash, len(unique), run_id),
        )
    return added, updated, removed


def enqueue_digest(connection: sqlite3.Connection, *, at: str) -> int | None:
    rows = connection.execute(
        """
        SELECT c.id, c.change_type, c.offer_id, o.provider, o.title, o.priority_tier
        FROM offer_changes c
        LEFT JOIN offers o ON o.offer_id = c.offer_id
        WHERE c.detected_at = ? AND c.notification_eligible = 1
          AND c.notification_id IS NULL
        ORDER BY CASE o.priority_tier WHEN 'A' THEN 0 ELSE 1 END, c.id
        """,
        (at,),
    ).fetchall()
    if not rows:
        return None
    change_ids = [int(row["id"]) for row in rows]
    dedupe_key = hashlib.sha256(
        ",".join(str(item) for item in change_ids).encode()
    ).hexdigest()
    labels = [
        f"{row['provider']} · {row['title']}"
        for row in rows[:3]
        if row["provider"] and row["title"]
    ]
    suffix = f"；另有 {len(rows) - 3} 条" if len(rows) > 3 else ""
    body = "；".join(labels) + suffix
    with connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO notifications(
                created_at, dedupe_key, title, body, target_url, item_count
            )
            VALUES (?, ?, ?, ?, '/ai-resources.html#changes', ?)
            """,
            (at, dedupe_key, f"AI 资源雷达：{len(rows)} 条重要变化", body, len(rows)),
        )
        if cursor.rowcount == 0:
            return None
        notification_id = int(cursor.lastrowid)
        placeholders = ",".join("?" for _ in change_ids)
        connection.execute(
            f"""
            UPDATE offer_changes SET notification_id = ?
            WHERE id IN ({placeholders})
            """,
            (notification_id, *change_ids),
        )
    return notification_id


def _offer_dict(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    evidence = connection.execute(
        """
        SELECT source_id, source_url, verification_level, evidence_excerpt, observed_at
        FROM offer_evidence
        WHERE offer_id = ? AND is_active = 1
        ORDER BY CASE verification_level
            WHEN 'official_api' THEN 0 WHEN 'official_page' THEN 1 ELSE 2 END,
            observed_at DESC
        LIMIT 1
        """,
        (row["offer_id"],),
    ).fetchone()
    details = (
        official_guide(str(row["provider"]), str(row["offer_type"]))
        if row["verification_level"] in {"official_api", "official_page"}
        and row["offer_type"] != "pricing_reference"
        else {}
    )
    details.update(json.loads(row["details_json"]))
    input_modalities = _decode_json_list(
        row["input_modalities_json"] if "input_modalities_json" in row.keys() else None
    )
    output_modalities = _decode_json_list(
        row["output_modalities_json"] if "output_modalities_json" in row.keys() else None
    )
    resolved_inputs, resolved_outputs = resolve_modalities(
        details,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
    )
    free_image_generation = (
        bool(row["free_image_generation"]) and str(row["kind"]) == "token"
        if "free_image_generation" in row.keys()
        else str(row["kind"]) == "token"
        and str(row["offer_type"]) in {"recurring_free", "variable_free"}
        and "image" in resolved_outputs
    )
    return {
        "offer_id": row["offer_id"],
        "external_id": row["offer_id"],
        "provider": row["provider"],
        "title": row["title"],
        "kind": row["kind"],
        "offer_type": row["offer_type"],
        "quota_value": row["quota_value"],
        "quota_unit": row["quota_unit"],
        "reset_period": row["reset_period"],
        "estimated_usd_value": row["estimated_usd_value"],
        "requires_card": row["requires_card"],
        "requires_phone": row["requires_phone"],
        "eligibility": row["eligibility"],
        "mainland_status": row["mainland_status"],
        "expires_at": row["expires_at"],
        "homepage_url": row["homepage_url"],
        "url": row["homepage_url"],
        "verification_level": row["verification_level"],
        "verification_status": row["verification_level"],
        "priority_tier": row["priority_tier"],
        "priority_reasons": json.loads(row["priority_reasons_json"]),
        "input_modalities": list(resolved_inputs),
        "output_modalities": list(resolved_outputs),
        "free_image_generation": free_image_generation,
        "details": details,
        "status": row["status"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "last_changed_at": row["last_changed_at"],
        "evidence": dict(evidence) if evidence else None,
    }


def list_offers(
    path: Path,
    *,
    kind: str | None = None,
    verified_only: bool = False,
    no_card: bool = False,
    mainland: tuple[str, ...] | None = None,
    query: str | None = None,
    free_image_generation: bool = False,
    limit: int = 100,
    offset: int = 0,
    include_inactive: bool = False,
    include_pricing: bool = True,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= 500 or not 0 <= offset <= 100_000:
        raise ValueError("invalid_offer_pagination")
    if kind is not None and kind not in {"token", "gpu", "grant"}:
        raise ValueError("invalid_offer_kind")
    if not path.exists():
        return ()
    connection = connect(path)
    try:
        clauses = ["1 = 1"]
        parameters: list[Any] = []
        if not include_inactive:
            clauses.append("status = 'active'")
        if not include_pricing:
            clauses.append("offer_type != 'pricing_reference'")
        if kind:
            clauses.append("kind = ?")
            parameters.append(kind)
        if verified_only:
            clauses.append("verification_level IN ('official_api', 'official_page')")
        if no_card:
            clauses.append("requires_card = 'no'")
        if free_image_generation:
            clauses.append("free_image_generation = 1")
        if mainland:
            valid = tuple(item for item in mainland if item in _MAINLAND_RANK)
            if not valid:
                raise ValueError("invalid_mainland_filter")
            clauses.append(f"mainland_status IN ({','.join('?' for _ in valid)})")
            parameters.extend(valid)
        if query:
            clauses.append("(provider LIKE ? OR title LIKE ?)")
            token = f"%{query[:100]}%"
            parameters.extend((token, token))
        parameters.extend((limit, offset))
        rows = connection.execute(
            f"""
            SELECT * FROM offers
            WHERE {' AND '.join(clauses)}
            ORDER BY
                CASE priority_tier
                    WHEN 'A' THEN 0 WHEN 'B' THEN 1
                    WHEN 'C' THEN 2 ELSE 3 END,
                CASE mainland_status
                    WHEN 'supported' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END,
                CASE requires_card
                    WHEN 'no' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END,
                COALESCE(estimated_usd_value, -1) DESC,
                last_changed_at DESC,
                provider COLLATE NOCASE,
                title COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            parameters,
        ).fetchall()
        return tuple(_offer_dict(connection, row) for row in rows)
    finally:
        connection.close()


SOURCE_FRESHNESS_STATES = (
    "fresh",
    "overdue",
    "stale",
    "verification_pending",
    "failed",
    "never",
)


def _source_time(value: Any, *, current: datetime) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=current.tzinfo)
    return parsed.astimezone(current.tzinfo)


def source_freshness_status(
    *,
    last_success_at: str | None,
    cadence_hours: int,
    last_error_code: str | None = None,
    last_result_status: str | None = None,
    now: datetime | None = None,
) -> tuple[str, float | None]:
    """Classify one source using the documented cadence-aware boundaries."""

    current = (now or datetime.now().astimezone()).astimezone()
    success = _source_time(last_success_at, current=current)
    age_hours = (
        max(0.0, (current - success).total_seconds() / 3600)
        if success is not None
        else None
    )
    if last_error_code:
        if last_result_status == "verification_pending":
            return "verification_pending", age_hours
        return "failed", age_hours
    if success is None:
        return "never", None
    assert age_hours is not None
    cadence = max(1, int(cadence_hours))
    if age_hours <= cadence + 6:
        return "fresh", age_hours
    if age_hours <= cadence * 2:
        return "overdue", age_hours
    return "stale", age_hours


def source_statuses(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], ...]:
    current = (now or datetime.now().astimezone()).astimezone()
    rows = connection.execute(
        """
        SELECT s.*,
            (
                SELECT f.status FROM fetch_runs f
                WHERE f.source_id = s.source_id
                  AND f.status IN (
                    'success', 'not_modified', 'verification_pending', 'failed'
                  )
                ORDER BY f.id DESC LIMIT 1
            ) AS last_result_status,
            (
                SELECT f.status FROM fetch_runs f
                WHERE f.source_id = s.source_id
                ORDER BY f.id DESC LIMIT 1
            ) AS latest_run_status,
            (
                SELECT f.started_at FROM fetch_runs f
                WHERE f.source_id = s.source_id
                ORDER BY f.id DESC LIMIT 1
            ) AS latest_run_started_at
        FROM sources s
        ORDER BY CASE s.authority WHEN 'community' THEN 1 ELSE 0 END,
                 s.name COLLATE NOCASE
        """
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        latest_run_started_at = _source_time(
            row["latest_run_started_at"], current=current
        )
        abandoned_run = (
            row["latest_run_status"] == "running"
            and latest_run_started_at is not None
            and current - latest_run_started_at
            >= timedelta(minutes=ABANDONED_FETCH_RUN_MINUTES)
        )
        effective_error_code = (
            "fetch_run_abandoned" if abandoned_run else row["last_error_code"]
        )
        effective_result_status = (
            "failed" if abandoned_run else row["last_result_status"]
        )
        status, age_hours = source_freshness_status(
            last_success_at=row["last_success_at"],
            cadence_hours=int(row["cadence_hours"]),
            last_error_code=effective_error_code,
            last_result_status=effective_result_status,
            now=current,
        )
        output.append(
            {
                "source_id": row["source_id"],
                "name": row["name"],
                "authority": row["authority"],
                "cadence_hours": int(row["cadence_hours"]),
                "status": status,
                "last_attempt_at": row["last_attempt_at"],
                "last_success_at": row["last_success_at"],
                "last_error_code": effective_error_code,
                "age_hours": round(age_hours, 2) if age_hours is not None else None,
            }
        )
    return tuple(output)


def _empty_source_summary() -> dict[str, Any]:
    counts = {state: 0 for state in SOURCE_FRESHNESS_STATES}
    counts["never"] = len(SOURCES)
    return {
        "total": len(SOURCES),
        "healthy": 0,
        "failed": 0,
        **counts,
        "status_counts": counts,
        "oldest_official_verified_at": None,
        "oldest_official_age_hours": None,
        "items": (),
    }


def radar_summary(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now().astimezone()).astimezone()
    if not path.exists():
        return {
            "schema_version": "2.0",
            "counts": {"active": 0, "tier_a": 0, "new_today": 0, "expiring": 0},
            "sources": _empty_source_summary(),
            "notifications": {"unread": 0},
            "last_refresh_at": None,
            "storage": {
                "database_bytes": 0,
                "retention": {
                    "fetch_runs_days": FETCH_RUN_RETENTION_DAYS,
                    "ordinary_changes_days": CHANGE_RETENTION_DAYS,
                    "delivered_notifications_days": NOTIFICATION_RETENTION_DAYS,
                    "daily_posters_days": POSTER_RETENTION_DAYS,
                    "important_free_changes": "forever",
                },
                "posters": {"count": 0, "bytes": 0},
                "history_rebuilt_at": None,
                "schema_migrated_at": None,
                "last_maintenance_at": None,
                "last_vacuum_at": None,
                "vacuum_pending": False,
            },
        }
    connection = connect(path)
    try:
        today = current.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        expiry = (current + timedelta(days=7)).date().isoformat()
        counts = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status = 'active' AND priority_tier = 'A' THEN 1 ELSE 0 END) AS tier_a,
                SUM(CASE WHEN first_seen_at >= ? THEN 1 ELSE 0 END) AS new_today,
                SUM(CASE WHEN status = 'active' AND expires_at IS NOT NULL
                    AND expires_at <= ? THEN 1 ELSE 0 END) AS expiring
            FROM offers
            """,
            (today, expiry),
        ).fetchone()
        source_row = connection.execute(
            "SELECT MAX(last_attempt_at) AS last_refresh_at FROM sources"
        ).fetchone()
        statuses = source_statuses(connection, now=current)
        status_counts = {
            state: sum(item["status"] == state for item in statuses)
            for state in SOURCE_FRESHNESS_STATES
        }
        official_times = [
            parsed
            for item in statuses
            if item["authority"] != "community"
            for parsed in (
                _source_time(item["last_success_at"], current=current),
            )
            if parsed is not None
        ]
        oldest_official = min(official_times) if official_times else None
        unread = connection.execute(
            "SELECT COUNT(*) FROM notifications WHERE status != 'read'"
        ).fetchone()[0]
        return {
            "schema_version": "2.0",
            "counts": {
                "active": int(counts["active"] or 0),
                "tier_a": int(counts["tier_a"] or 0),
                "new_today": int(counts["new_today"] or 0),
                "expiring": int(counts["expiring"] or 0),
            },
            "sources": {
                "total": len(statuses),
                "healthy": status_counts["fresh"],
                "failed": (
                    status_counts["failed"]
                    + status_counts["verification_pending"]
                ),
                **status_counts,
                "status_counts": status_counts,
                "oldest_official_verified_at": (
                    oldest_official.isoformat(timespec="seconds")
                    if oldest_official
                    else None
                ),
                "oldest_official_age_hours": (
                    round(
                        max(
                            0.0,
                            (current - oldest_official).total_seconds() / 3600,
                        ),
                        2,
                    )
                    if oldest_official
                    else None
                ),
                "items": statuses,
            },
            "notifications": {"unread": int(unread)},
            "last_refresh_at": source_row["last_refresh_at"],
            "storage": storage_summary(connection),
        }
    finally:
        connection.close()


def list_changes(
    path: Path, *, days: int = 30, limit: int = 100
) -> tuple[dict[str, Any], ...]:
    if not 1 <= days <= 365 or not 1 <= limit <= 500:
        raise ValueError("invalid_change_filter")
    if not path.exists():
        return ()
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT c.id, c.offer_id, c.detected_at, c.change_type,
                   c.changed_fields_json, c.importance,
                   o.provider, o.title, o.kind, o.priority_tier
            FROM offer_changes c
            LEFT JOIN offers o ON o.offer_id = c.offer_id
            WHERE c.detected_at >= ?
            ORDER BY c.detected_at DESC, c.id DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return tuple(
            {
                **dict(row),
                "changed_fields": json.loads(row["changed_fields_json"]),
            }
            for row in rows
        )
    finally:
        connection.close()


def pending_notifications(
    path: Path, *, limit: int = 5
) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= 20 or not path.exists():
        return ()
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT id, created_at, title, body, target_url, item_count, status
            FROM notifications
            WHERE status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(dict(row) for row in rows)
    finally:
        connection.close()


def mark_notification(path: Path, notification_id: int, *, status: str) -> bool:
    if status not in {"delivered", "read"} or not path.exists():
        return False
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    connection = connect(path)
    try:
        with connection:
            if status == "delivered":
                cursor = connection.execute(
                    """
                    UPDATE notifications
                    SET status = CASE WHEN status = 'read' THEN 'read' ELSE 'delivered' END,
                        delivered_at = COALESCE(delivered_at, ?)
                    WHERE id = ?
                    """,
                    (now, notification_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE notifications
                    SET status = 'read', read_at = ?,
                        delivered_at = COALESCE(delivered_at, ?)
                    WHERE id = ?
                    """,
                    (now, now, notification_id),
                )
        return cursor.rowcount == 1
    finally:
        connection.close()
