from __future__ import annotations

from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from ai_resource_radar import SCHEMA_VERSION, UnsupportedSchemaError, run_doctor
from ai_resource_radar.doctor import _package_version
from ai_resource_radar.locks import (
    OperationLockedError,
    operation_lock,
    operation_lock_status,
)
from ai_resource_radar.sources import (
    OfferObservation,
    SOURCE_BY_ID,
    parse_source,
)
from ai_resource_radar.store import (
    begin_run,
    classify_offer,
    connect,
    ingest_source,
    list_offers,
    radar_summary,
    source_freshness_status,
    source_statuses,
)


NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).with_name("fixtures")


def _offer(
    offer_id: str,
    *,
    details: dict[str, object],
    input_modalities: tuple[str, ...] = (),
    output_modalities: tuple[str, ...] = (),
) -> OfferObservation:
    return OfferObservation(
        offer_id=offer_id,
        provider="Migration Test",
        title=offer_id,
        kind="token",
        offer_type="recurring_free",
        quota_value=10,
        quota_unit="requests",
        reset_period="daily",
        estimated_usd_value=None,
        requires_card="no",
        requires_phone="unknown",
        eligibility=None,
        mainland_status="supported",
        expires_at=None,
        homepage_url="https://openrouter.ai/",
        verification_level="official_api",
        source_url="https://openrouter.ai/api/v1/models",
        evidence_excerpt="Fixture evidence.",
        details=details,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
    )


def _hold_operation_lock(database: str, ready: object) -> None:
    with operation_lock(Path(database), "refresh"):
        ready.set()
        time.sleep(30)


class CoreV02Tests(unittest.TestCase):
    @patch("ai_resource_radar.doctor.metadata.version", return_value="0.2.0")
    def test_doctor_prefers_runtime_source_version(self, installed_version) -> None:
        with patch("ai_resource_radar.__version__", "0.3.0"):
            self.assertEqual(_package_version(), "0.3.0")
        installed_version.assert_not_called()

    def test_zhipu_official_fixture_is_free_image_generation(self) -> None:
        source = SOURCE_BY_ID["zhipu-cogview-3-flash"]
        payload = (FIXTURES / "zhipu_cogview_3_flash.html").read_bytes()
        records = parse_source(source, payload)

        self.assertEqual(source.allowed_hosts, ("docs.bigmodel.cn",))
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.offer_type, "variable_free")
        self.assertIsNone(record.quota_value)
        self.assertEqual(record.requires_card, "no")
        self.assertEqual(record.mainland_status, "supported")
        self.assertEqual(record.input_modalities, ("text",))
        self.assertEqual(record.output_modalities, ("image",))

        tier, reasons = classify_offer(record)
        self.assertEqual(tier, "B")
        self.assertIn("免费图片输出能力已核验", reasons)

        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            try:
                run_id, baseline = begin_run(connection, source.id, NOW.isoformat())
                ingest_source(
                    connection,
                    source=source,
                    observations=records,
                    at=NOW.isoformat(),
                    run_id=run_id,
                    http_status=200,
                    etag=None,
                    last_modified=None,
                    content_hash="zhipu-fixture",
                    baseline=baseline,
                )
            finally:
                connection.close()
            offers = list_offers(database, free_image_generation=True)

        self.assertEqual(len(offers), 1)
        self.assertTrue(offers[0]["free_image_generation"])
        self.assertEqual(offers[0]["priority_tier"], "B")

    def test_zhipu_does_not_accept_unrelated_free_navigation_text(self) -> None:
        source = SOURCE_BY_ID["zhipu-cogview-3-flash"]
        payload = """
        <nav>免费模型目录</nav>
        <main>
          <h1>CogView-3-Flash</h1>
          <p>图像生成模型，价格与用量以控制台为准。</p>
        </main>
        """.encode()

        with self.assertRaisesRegex(ValueError, "official_page_structure_changed"):
            parse_source(source, payload)

    def test_zhipu_parser_detects_page_drift(self) -> None:
        source = SOURCE_BY_ID["zhipu-cogview-3-flash"]
        with self.assertRaisesRegex(ValueError, "official_page_structure_changed"):
            parse_source(source, b"<main>CogView model catalog</main>")

    def test_v4_to_v5_preserves_data_and_backfills_stable_fingerprints(self) -> None:
        source = SOURCE_BY_ID["openrouter-models"]
        vision = _offer(
            "token:vision-input",
            details={"modality": "text+image"},
        )
        generator = _offer(
            "token:image-output",
            details={"input_modalities": ["text"], "output_modalities": ["image"]},
        )
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            run_id, baseline = begin_run(connection, source.id, NOW.isoformat())
            ingest_source(
                connection,
                source=source,
                observations=(vision, generator),
                at=NOW.isoformat(),
                run_id=run_id,
                http_status=200,
                etag='"v4"',
                last_modified="Sun, 09 Aug 2026 08:00:00 GMT",
                content_hash="v4",
                baseline=baseline,
            )
            with connection:
                connection.execute(
                    "INSERT INTO notifications(created_at, dedupe_key, title, body, "
                    "target_url, item_count) VALUES (?, 'preserve', 't', 'b', '/', 1)",
                    (NOW.isoformat(),),
                )
                connection.execute(
                    "INSERT INTO daily_reports(report_date, status, attempt_count, "
                    "selected_facts_json, validation_json, updated_at) "
                    "VALUES ('2026-08-09', 'failed', 0, '{}', '{}', ?)",
                    (NOW.isoformat(),),
                )
                for column in (
                    "free_image_generation",
                    "output_modalities_json",
                    "input_modalities_json",
                ):
                    connection.execute(f"ALTER TABLE offers DROP COLUMN {column}")
                connection.execute("UPDATE offers SET fingerprint = 'legacy-v4'")
                connection.execute("PRAGMA user_version = 4")
            connection.close()

            migrated = connect(database)
            try:
                version = int(migrated.execute("PRAGMA user_version").fetchone()[0])
                rows = {
                    row["offer_id"]: row
                    for row in migrated.execute(
                        "SELECT offer_id, input_modalities_json, "
                        "output_modalities_json, free_image_generation, fingerprint "
                        "FROM offers"
                    )
                }
                preserved = {
                    "evidence": migrated.execute(
                        "SELECT COUNT(*) FROM offer_evidence"
                    ).fetchone()[0],
                    "notifications": migrated.execute(
                        "SELECT COUNT(*) FROM notifications WHERE dedupe_key='preserve'"
                    ).fetchone()[0],
                    "reports": migrated.execute(
                        "SELECT COUNT(*) FROM daily_reports"
                    ).fetchone()[0],
                }
                next_at = (NOW + timedelta(hours=1)).isoformat()
                run_id, baseline = begin_run(migrated, source.id, next_at)
                _, updated, _ = ingest_source(
                    migrated,
                    source=source,
                    observations=(vision, generator),
                    at=next_at,
                    run_id=run_id,
                    http_status=200,
                    etag='"v5"',
                    last_modified=None,
                    content_hash="v5",
                    baseline=baseline,
                )
            finally:
                migrated.close()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(rows["token:vision-input"]["input_modalities_json"], '["text","image"]')
        self.assertEqual(rows["token:vision-input"]["output_modalities_json"], "[]")
        self.assertEqual(rows["token:vision-input"]["free_image_generation"], 0)
        self.assertEqual(rows["token:image-output"]["free_image_generation"], 1)
        self.assertNotEqual(rows["token:image-output"]["fingerprint"], "legacy-v4")
        self.assertEqual(preserved, {"evidence": 2, "notifications": 1, "reports": 1})
        self.assertEqual(updated, 0)

    def test_existing_v5_is_read_without_rebuilding_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            with connection:
                connection.execute(
                    "INSERT INTO notifications(created_at, dedupe_key, title, body, "
                    "target_url, item_count) VALUES (?, 'v5', 't', 'b', '/', 1)",
                    (NOW.isoformat(),),
                )
            connection.close()
            reopened = connect(database)
            try:
                count = reopened.execute(
                    "SELECT COUNT(*) FROM notifications WHERE dedupe_key='v5'"
                ).fetchone()[0]
            finally:
                reopened.close()
        self.assertEqual(count, 1)

    def test_newer_schema_raises_public_versioned_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
            with self.assertRaises(UnsupportedSchemaError) as raised:
                connect(database)
        self.assertEqual(str(raised.exception), "ai_radar_schema_unsupported")
        self.assertEqual(raised.exception.database_version, SCHEMA_VERSION + 1)
        self.assertEqual(raised.exception.supported_version, SCHEMA_VERSION)

    def test_source_freshness_boundaries_and_failure_precedence(self) -> None:
        def status(age: timedelta, **options: object) -> str:
            value, _ = source_freshness_status(
                last_success_at=(NOW - age).isoformat(),
                cadence_hours=24,
                now=NOW,
                **options,
            )
            return value

        self.assertEqual(status(timedelta(hours=30)), "fresh")
        self.assertEqual(status(timedelta(hours=30, seconds=1)), "overdue")
        self.assertEqual(status(timedelta(hours=48)), "overdue")
        self.assertEqual(status(timedelta(hours=48, seconds=1)), "stale")
        self.assertEqual(
            status(
                timedelta(hours=1),
                last_error_code="official_page_structure_changed",
                last_result_status="verification_pending",
            ),
            "verification_pending",
        )
        self.assertEqual(
            status(
                timedelta(hours=1),
                last_error_code="timeout",
                last_result_status="failed",
            ),
            "failed",
        )
        never, age = source_freshness_status(
            last_success_at=None, cadence_hours=24, now=NOW
        )
        self.assertEqual((never, age), ("never", None))

    def test_summary_reports_real_freshness_and_oldest_official_age(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            with connection:
                connection.execute(
                    "UPDATE sources SET last_success_at = ?, last_attempt_at = ?, "
                    "last_error_code = NULL WHERE source_id = 'openrouter-models'",
                    ((NOW - timedelta(hours=4)).isoformat(), NOW.isoformat()),
                )
            connection.close()
            payload = radar_summary(database, now=NOW)

        self.assertEqual(payload["sources"]["fresh"], 1)
        self.assertEqual(payload["sources"]["healthy"], 1)
        self.assertEqual(payload["sources"]["never"], len(SOURCE_BY_ID) - 1)
        self.assertEqual(payload["sources"]["oldest_official_age_hours"], 4.0)

    def test_begin_run_preserves_previous_verification_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            source_id = "zhipu-cogview-3-flash"
            with connection:
                connection.execute(
                    "UPDATE sources SET last_success_at = ?, last_attempt_at = ?, "
                    "last_error_code = 'official_page_structure_changed' "
                    "WHERE source_id = ?",
                    ((NOW - timedelta(hours=1)).isoformat(), NOW.isoformat(), source_id),
                )
                connection.execute(
                    "INSERT INTO fetch_runs(source_id, started_at, finished_at, status, "
                    "error_code) VALUES (?, ?, ?, 'verification_pending', ?)",
                    (
                        source_id,
                        (NOW - timedelta(minutes=5)).isoformat(),
                        (NOW - timedelta(minutes=4)).isoformat(),
                        "official_page_structure_changed",
                    ),
                )

            begin_run(connection, source_id, NOW.isoformat())
            source_row = connection.execute(
                "SELECT last_error_code FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            status = next(
                item
                for item in source_statuses(connection, now=NOW)
                if item["source_id"] == source_id
            )
            connection.close()

        self.assertEqual(
            source_row["last_error_code"], "official_page_structure_changed"
        )
        self.assertEqual(status["status"], "verification_pending")

    def test_source_status_marks_abandoned_running_fetch_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            source_id = "openrouter-models"
            with connection:
                connection.execute(
                    "UPDATE sources SET last_success_at = ?, last_error_code = NULL "
                    "WHERE source_id = ?",
                    ((NOW - timedelta(hours=1)).isoformat(), source_id),
                )
            begin_run(
                connection,
                source_id,
                (NOW - timedelta(minutes=6)).isoformat(),
            )

            status = next(
                item
                for item in source_statuses(connection, now=NOW)
                if item["source_id"] == source_id
            )
            connection.close()

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["last_error_code"], "fetch_run_abandoned")

    def test_cross_process_lock_is_released_after_process_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            context = get_context("spawn")
            ready = context.Event()
            process = context.Process(
                target=_hold_operation_lock, args=(str(database), ready)
            )
            process.start()
            self.assertTrue(ready.wait(5))
            self.assertTrue(operation_lock_status(database, "refresh")["locked"])
            with self.assertRaises(OperationLockedError):
                with operation_lock(database, "refresh"):
                    pass
            process.terminate()
            process.join(5)
            self.assertFalse(process.is_alive())
            with operation_lock(database, "refresh"):
                self.assertTrue(True)

    def test_doctor_status_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            missing = run_doctor(
                database, check_services=False, check_conflicts=False, now=NOW
            )
            self.assertEqual(missing["overall"], "degraded")
            self.assertEqual(missing["exit_code"], 1)
            self.assertFalse(database.exists())

            connection = connect(database)
            with connection:
                connection.execute(
                    "UPDATE sources SET last_success_at = ?, last_attempt_at = ?, "
                    "last_error_code = NULL",
                    (NOW.isoformat(), NOW.isoformat()),
                )
            connection.close()
            healthy = run_doctor(
                database, check_services=False, check_conflicts=False, now=NOW
            )
            self.assertEqual(healthy["overall"], "healthy")
            self.assertEqual(healthy["exit_code"], 0)

    def test_doctor_degrades_when_lock_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch(
            "ai_resource_radar.doctor.operation_lock_status"
        ) as lock_status:
            database = Path(temp) / "radar.sqlite3"
            lock_status.side_effect = lambda _database, operation: {
                "operation": operation,
                "locked": False,
                "path": str(database.with_suffix(f".{operation}.lock")),
                "probe_error": "OSError" if operation == "refresh" else None,
            }
            report = run_doctor(
                database, check_services=False, check_conflicts=False, now=NOW
            )

        refresh_lock = next(
            check for check in report["checks"] if check["id"] == "refresh_lock"
        )
        self.assertEqual(refresh_lock["status"], "degraded")
        self.assertIn("Cannot inspect", refresh_lock["summary"])

    def test_doctor_treats_older_schema_as_migratable_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA user_version = 1")
            connection.close()
            os.chmod(database, 0o600)

            report = run_doctor(
                database, check_services=False, check_conflicts=False, now=NOW
            )

        self.assertEqual(report["overall"], "degraded")
        self.assertEqual(report["exit_code"], 1)
        self.assertFalse(any(check["status"] == "failed" for check in report["checks"]))
        sources = next(check for check in report["checks"] if check["id"] == "sources")
        self.assertEqual(sources["status"], "degraded")
        self.assertIn("migration", sources["summary"])

    def test_doctor_validates_selected_openclaw_model_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            with connection:
                connection.execute(
                    "UPDATE sources SET last_success_at = ?, last_attempt_at = ?, "
                    "last_error_code = NULL",
                    (NOW.isoformat(), NOW.isoformat()),
                )
                connection.executemany(
                    "INSERT INTO radar_metadata(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (
                        ("poster.enabled", "1"),
                        ("poster.provider", "openclaw"),
                        ("poster.model", "zai/cogview-3-flash"),
                    ),
                )
            connection.close()

            with patch(
                "ai_resource_radar.doctor.shutil.which", return_value="/usr/bin/true"
            ), patch(
                "ai_resource_radar.doctor._openclaw_provider_configured",
                return_value=(False, "openclaw_model_cogview-3-flash_not_configured"),
            ) as configured:
                report = run_doctor(
                    database, check_services=False, check_conflicts=False, now=NOW
                )

        provider = next(
            check for check in report["checks"] if check["id"] == "poster_provider"
        )
        self.assertEqual(provider["status"], "degraded")
        self.assertEqual(provider["details"]["model"], "zai/cogview-3-flash")
        self.assertEqual(
            provider["details"]["configuration_reason"],
            "openclaw_model_cogview-3-flash_not_configured",
        )
        configured.assert_called_once_with(
            "zai/cogview-3-flash", binary="/usr/bin/true"
        )


if __name__ == "__main__":
    unittest.main()
