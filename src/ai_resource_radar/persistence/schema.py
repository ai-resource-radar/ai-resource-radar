"""Schema-v7 creation and transactional migration orchestration."""

from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any

from ai_resource_radar.sources import SOURCES
from .connection import SCHEMA_VERSION, UnsupportedSchemaError
from .migrations import _backfill_modality_fields, _columns, _metadata_set

def _create_v7_schema(connection: sqlite3.Connection) -> None:
    """Create schema-v7 objects inside the caller's migration transaction."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tip_application_batches (
            batch_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL CHECK(scope IN ('global', 'project', 'both')),
            tip_ids_json TEXT NOT NULL,
            targets_json TEXT NOT NULL DEFAULT '[]',
            removed_sections_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'applied'
                CHECK(status IN ('applied', 'failed', 'rolled_back')),
            error_code TEXT,
            applied_at TEXT NOT NULL,
            rolled_back_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS tip_application_batches_time
            ON tip_application_batches(applied_at DESC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS poster_model_benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_version TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            case_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('success', 'failed')),
            media_type TEXT,
            width INTEGER,
            height INTEGER,
            final_image_sha256 TEXT,
            validation_json TEXT NOT NULL DEFAULT '{}',
            image_path TEXT,
            error_code TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS poster_model_benchmarks_lookup
            ON poster_model_benchmarks(
                provider, model, benchmark_version, case_id, attempted_at DESC
            )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS poster_model_reviews (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            benchmark_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('approved', 'rejected')),
            reviewed_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(provider, model, benchmark_version)
        )
        """
    )
    if "application_batch_id" not in _columns(connection, "tip_applications"):
        connection.execute(
            "ALTER TABLE tip_applications ADD COLUMN application_batch_id TEXT"
        )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS tip_applications_batch
            ON tip_applications(application_batch_id, applied_at DESC)
        """
    )


def initialize(
    connection: sqlite3.Connection,
    *,
    create_v7_schema: Any = None,
    backfill_modality_fields: Any = None,
) -> bool:
    """Initialize or migrate a connection without changing schema-v7 policy.

    The callbacks keep the legacy ``ai_resource_radar.store`` monkeypatch
    contract intact while allowing the schema implementation to live here.
    """

    create_v7_schema = create_v7_schema or _create_v7_schema
    backfill_modality_fields = backfill_modality_fields or _backfill_modality_fields
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
        CREATE TABLE IF NOT EXISTS tips (
            tip_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            summary TEXT NOT NULL,
            instruction TEXT NOT NULL,
            example TEXT NOT NULL DEFAULT '',
            constraints_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'candidate'
                CHECK(status IN ('candidate', 'approved', 'rejected', 'retired')),
            risk_level TEXT NOT NULL DEFAULT 'medium'
                CHECK(risk_level IN ('low', 'medium', 'high')),
            source_type TEXT NOT NULL DEFAULT 'manual'
                CHECK(source_type IN ('official', 'manual', 'community')),
            source_url TEXT NOT NULL,
            source_title TEXT NOT NULL DEFAULT '',
            evidence_summary TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            verified_at TEXT,
            reviewed_at TEXT,
            approved_at TEXT,
            applied_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS tips_browse
            ON tips(status, category, risk_level, updated_at DESC);
        CREATE TABLE IF NOT EXISTS tip_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips(tip_id) ON DELETE CASCADE,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            etag TEXT,
            last_modified TEXT,
            content_hash TEXT NOT NULL,
            evidence_summary TEXT NOT NULL,
            parse_status TEXT NOT NULL DEFAULT 'success',
            error_code TEXT
        );
        CREATE INDEX IF NOT EXISTS tip_evidence_tip
            ON tip_evidence(tip_id, fetched_at DESC);
        CREATE TABLE IF NOT EXISTS tip_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips(tip_id) ON DELETE CASCADE,
            changed_at TEXT NOT NULL,
            change_type TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            importance TEXT NOT NULL DEFAULT 'normal'
        );
        CREATE INDEX IF NOT EXISTS tip_changes_time
            ON tip_changes(changed_at DESC, id DESC);
        CREATE TABLE IF NOT EXISTS tip_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips(tip_id) ON DELETE CASCADE,
            scope TEXT NOT NULL CHECK(scope IN ('global', 'project')),
            target_path TEXT NOT NULL,
            tip_version_hash TEXT NOT NULL,
            old_file_hash TEXT,
            new_file_hash TEXT,
            backup_path TEXT,
            status TEXT NOT NULL DEFAULT 'applied'
                CHECK(status IN ('applied', 'failed', 'rolled_back')),
            error_code TEXT,
            applied_at TEXT NOT NULL,
            rolled_back_at TEXT
        );
        CREATE INDEX IF NOT EXISTS tip_applications_tip
            ON tip_applications(tip_id, applied_at DESC);
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
    needs_v7_schema = previous_version < 7
    if (
        schema_migration
        or history_migration
        or needs_modality_backfill
        or needs_v7_schema
    ) and not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    with connection:
        if needs_v7_schema:
            create_v7_schema(connection)
        # ALTER, backfill, metadata and user_version form the transactional
        # schema migration. SQLite rolls the whole block back on failure.
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
            backfill_modality_fields(connection)
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



_initialize = initialize

__all__ = ["initialize", "_initialize", "_create_v7_schema"]
