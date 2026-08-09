from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from ai_resource_radar.dashboard_state import AiRadarDashboard
from ai_resource_radar.runtime import FetchPayload, refresh
from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.sources import (
    OfferObservation,
    SOURCE_BY_ID,
    parse_source,
)
from ai_resource_radar.store import (
    SCHEMA_VERSION,
    _should_vacuum,
    begin_run,
    classify_offer,
    connect,
    enqueue_digest,
    ingest_source,
    list_changes,
    list_offers,
    maintain_storage,
    mark_notification,
    pending_notifications,
    radar_summary,
)


NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)


def official_html(source_id: str) -> bytes:
    samples = {
        "groq-free-limits": "Groq Rate Limits Free Plan Limits RPM RPD TPM TPD",
        "gemini-free-tier": "Gemini Developer API Pricing Free Tier Free of charge",
        "cloudflare-workers-ai": "Workers AI free allocation 10,000 Neurons per day",
        "huggingface-zerogpu": "ZeroGPU Free account 5 minutes daily GPU quota",
        "modal-pricing": "Modal Starter $30 / month free credit academic $10k grant",
        "colab-faq": "Colab free of charge access to GPUs and TPUs limits vary",
    }
    return f"<html><body><main>{samples[source_id]}</main></body></html>".encode()


def observation(
    *,
    offer_id: str = "gpu:test",
    quota: float = 30,
    verification: str = "official_page",
    mainland: str = "supported",
    card: str = "no",
) -> OfferObservation:
    return OfferObservation(
        offer_id=offer_id,
        provider="Test Compute",
        title="Monthly GPU Credit",
        kind="gpu",
        offer_type="recurring_free",
        quota_value=quota,
        quota_unit="USD compute credit",
        reset_period="monthly",
        estimated_usd_value=quota,
        requires_card=card,
        requires_phone="unknown",
        eligibility=None,
        mainland_status=mainland,
        expires_at=None,
        homepage_url="https://example.com/pricing",
        verification_level=verification,
        source_url="https://example.com/pricing",
        evidence_excerpt="Official free monthly credit.",
        details={},
    )


class AiRadarV2Tests(unittest.TestCase):
    def test_all_official_source_parsers_produce_normalized_offers(self) -> None:
        openrouter = json.dumps(
            {
                "data": [
                    {
                        "id": "test/model:free",
                        "name": "Test Free",
                        "pricing": {"prompt": "0", "completion": "0"},
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                        },
                    },
                    {
                        "id": "test/paid-image-model",
                        "name": "Paid Image Model",
                        "pricing": {
                            "prompt": "0",
                            "completion": "0",
                            "image_output": "0.01",
                        },
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["image"],
                        },
                    }
                ]
            }
        ).encode()
        records = parse_source(SOURCE_BY_ID["openrouter-models"], openrouter)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].provider, "OpenRouter")
        self.assertEqual(records[0].verification_level, "official_api")
        self.assertIn("50 次", records[0].details["benefit_summary"])
        self.assertEqual(len(records[0].details["usage_steps"]), 4)
        self.assertTrue(records[0].details["action_url"].startswith("https://"))

        for source_id in (
            "groq-free-limits",
            "gemini-free-tier",
            "cloudflare-workers-ai",
            "huggingface-zerogpu",
            "modal-pricing",
            "colab-faq",
        ):
            with self.subTest(source_id=source_id):
                records = parse_source(
                    SOURCE_BY_ID[source_id], official_html(source_id)
                )
                self.assertGreaterEqual(len(records), 1)
                self.assertTrue(
                    all(
                        item.verification_level == "official_page"
                        for item in records
                    )
                )
                self.assertTrue(records[0].details["benefit_summary"])
                self.assertGreaterEqual(len(records[0].details["usage_steps"]), 3)
                self.assertTrue(records[0].details["caveats"])

        lightning = parse_source(
            SOURCE_BY_ID["lightning-pricing"],
            json.dumps(
                {
                    "features": [
                        {"key": "included_credits", "limit": 15},
                        {"key": "concurrent_gpus", "limit": 2},
                    ]
                }
            ).encode(),
        )
        self.assertEqual(lightning[0].quota_value, 15)

        kaggle = parse_source(
            SOURCE_BY_ID["kaggle-gpu"],
            json.dumps(
                {
                    "pageContent": (
                        "<p>Kaggle provides free access to GPU.</p>"
                        "<p>The quota resets weekly and is 30 hours.</p>"
                    )
                }
            ).encode(),
        )
        self.assertEqual(kaggle[0].reset_period, "weekly")

    def test_paid_gpu_price_parsers_normalize_hourly_costs(self) -> None:
        modal = parse_source(
            SOURCE_BY_ID["modal-pricing"],
            b"""
            <main>Modal Starter $30 / month</main>
            <div class=\"line-item sample\"><p>Nvidia H100</p>
            <p class=\"price sample\">$0.001097 <span>/ sec</span></p></div>
            """,
        )
        modal_price = next(item for item in modal if item.offer_type == "pricing_reference")
        self.assertEqual(modal_price.details["gpu_model"], "H100")
        self.assertAlmostEqual(modal_price.details["hourly_usd"], 3.9492)

        runpod = parse_source(
            SOURCE_BY_ID["runpod-gpu-pricing"],
            json.dumps(
                {
                    "@context": "https://schema.org",
                    "@graph": [
                        {
                            "@type": "Product",
                            "name": "H100 PCIe GPU on Runpod",
                            "description": "On-demand H100 pricing.",
                            "offers": {
                                "offers": [
                                    {
                                        "name": "Community Cloud",
                                        "price": "1.99",
                                        "priceCurrency": "USD",
                                        "description": "H100 per-hour rate.",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ).join(("<script type=\"application/ld+json\">", "</script>")).encode(),
        )
        self.assertEqual(runpod[0].quota_value, 1.99)
        self.assertEqual(runpod[0].details["market_tier"], "Community Cloud")

        lambda_prices = parse_source(
            SOURCE_BY_ID["lambda-gpu-pricing"],
            b"""
            <table><tr data-plan=\"NVIDIA H100 SXM\"><th>NVIDIA H100 SXM</th>
            <td data-label=\"VRAM/GPU\">80 GB</td><td data-label=\"vCPUs\">26</td>
            <td data-label=\"PRICE/GPU/HR*\">$4.29</td></tr></table>
            """,
        )
        self.assertEqual(lambda_prices[0].details["vram_gb"], 80)
        self.assertEqual(lambda_prices[0].details["hourly_usd"], 4.29)

        vast = parse_source(
            SOURCE_BY_ID["vast-gpu-pricing"],
            b"<main>Live GPU Prices supply and demand Per-second billing</main>",
        )
        self.assertEqual(vast[0].details["price_mode"], "dynamic_market")

    def test_price_lists_use_transparent_token_and_gpu_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            token_source = SOURCE_BY_ID["pydantic-genai-prices"]
            token_records = parse_source(
                token_source,
                json.dumps(
                    [
                        {
                            "name": "Example AI",
                            "pricing_urls": ["https://example.com/pricing"],
                            "models": [
                                {
                                    "id": "example-fast",
                                    "name": "Example Fast",
                                    "context_window": 128000,
                                    "prices": {"input_mtok": 1, "output_mtok": 4},
                                },
                                {
                                    "id": "example-pro",
                                    "name": "Example Pro",
                                    "context_window": 1000000,
                                    "prices": {
                                        "input_mtok": 2,
                                        "output_mtok": 2,
                                        "cache_read_mtok": 0.2,
                                    },
                                }
                            ],
                        }
                    ]
                ).encode(),
            )
            gpu_source = SOURCE_BY_ID["runpod-gpu-pricing"]
            gpu_record = OfferObservation(
                offer_id="gpu:runpod-h100",
                provider="RunPod",
                title="H100 PCIe · Community Cloud",
                kind="gpu",
                offer_type="pricing_reference",
                quota_value=1.99,
                quota_unit="USD per GPU hour",
                reset_period=None,
                estimated_usd_value=1.99,
                requires_card="unknown",
                requires_phone="unknown",
                eligibility=None,
                mainland_status="unknown",
                expires_at=None,
                homepage_url=gpu_source.url,
                verification_level="official_page",
                source_url=gpu_source.url,
                evidence_excerpt="Official price.",
                details={
                    "gpu_model": "H100 PCIe",
                    "vram_gb": 80,
                    "hourly_usd": 1.99,
                    "billing_mode": "pod",
                    "market_tier": "Community Cloud",
                },
            )
            connection = connect(path)
            try:
                for source, records, digest in (
                    (token_source, token_records, "tokens"),
                    (gpu_source, (gpu_record,), "gpus"),
                ):
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
                        content_hash=digest,
                        baseline=baseline,
                    )
            finally:
                connection.close()

            tokens = list_token_prices(path)
            tokens_desc = list_token_prices(path, direction="desc")
            long_context = list_token_prices(path, min_context=200_000)
            cached = list_token_prices(path, cache="yes")
            low_input = list_token_prices(path, max_input=1)
            official_tokens = list_token_prices(path, verification="official")
            gpus = list_gpu_prices(path, hours=10)
            large_gpus = list_gpu_prices(path, min_vram=100)
            cheap_gpus = list_gpu_prices(path, max_hourly=1)
            pod_gpus = list_gpu_prices(path, billing_mode="pod")

        self.assertEqual(tokens["total"], 2)
        self.assertEqual(tokens["prices"][0]["typical_cost"], 2)
        self.assertEqual(tokens_desc["prices"][0]["model"], "Example Pro")
        self.assertEqual(long_context["prices"][0]["model"], "Example Pro")
        self.assertEqual(cached["prices"][0]["model"], "Example Pro")
        self.assertEqual(low_input["prices"][0]["model"], "Example Fast")
        self.assertEqual(official_tokens["total"], 0)
        self.assertEqual(gpus["prices"][0]["estimated_cost"], 19.9)
        self.assertAlmostEqual(gpus["prices"][0]["usd_per_vram_gb_hour"], 1.99 / 80)
        self.assertEqual(large_gpus["total"], 0)
        self.assertEqual(cheap_gpus["total"], 0)
        self.assertEqual(pod_gpus["total"], 1)

    def test_priority_is_transparent_and_mainland_aware(self) -> None:
        tier, reasons = classify_offer(observation())
        self.assertEqual(tier, "A")
        self.assertIn("无需信用卡", reasons)
        self.assertIn("周期性免费额度", reasons)

        tier, _ = classify_offer(observation(mainland="unsupported"))
        self.assertEqual(tier, "C")
        tier, _ = classify_offer(observation(verification="community"))
        self.assertEqual(tier, "D")

    def test_schema_v1_migrates_without_losing_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sources (
                        source_id TEXT PRIMARY KEY, name TEXT, url TEXT,
                        license TEXT, kind TEXT, etag TEXT, last_modified TEXT,
                        last_attempt_at TEXT, last_success_at TEXT, last_error_code TEXT
                    );
                    CREATE TABLE fetch_runs (
                        id INTEGER PRIMARY KEY, source_id TEXT, started_at TEXT,
                        finished_at TEXT, status TEXT, http_status INTEGER,
                        content_hash TEXT, item_count INTEGER, error_code TEXT
                    );
                    CREATE TABLE changes (
                        id INTEGER PRIMARY KEY, source_id TEXT, external_id TEXT,
                        detected_at TEXT, change_type TEXT, before_hash TEXT,
                        after_hash TEXT
                    );
                    INSERT INTO sources(source_id, name, url, license, kind)
                    VALUES ('legacy', 'Legacy', 'https://example.com', 'MIT', 'token');
                    INSERT INTO changes(
                        source_id, external_id, detected_at, change_type
                    ) VALUES ('legacy', 'old', '2025-01-01T00:00:00Z', 'added');
                    PRAGMA user_version = 1;
                    """
                )
            connection = connect(path)
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                legacy = connection.execute(
                    "SELECT name FROM sources WHERE source_id = 'legacy'"
                ).fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                changes_type = connection.execute(
                    "SELECT type FROM sqlite_master WHERE name = 'changes'"
                ).fetchone()[0]
                change_count = connection.execute(
                    "SELECT COUNT(*) FROM changes"
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(legacy, "Legacy")
        self.assertTrue({"offers", "offer_evidence", "offer_changes", "notifications"} <= tables)
        self.assertEqual(changes_type, "view")
        self.assertEqual(change_count, 0)

    def test_schema_v2_rebuilds_history_but_preserves_current_state(self) -> None:
        source = SOURCE_BY_ID["modal-pricing"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            connection = connect(path)
            try:
                run_id, baseline = begin_run(connection, source.id, NOW.isoformat())
                ingest_source(
                    connection,
                    source=source,
                    observations=(observation(),),
                    at=NOW.isoformat(),
                    run_id=run_id,
                    http_status=200,
                    etag='"keep-etag"',
                    last_modified="Tue, 29 Jul 2026 08:00:00 GMT",
                    content_hash="baseline",
                    baseline=baseline,
                )
                with connection:
                    connection.execute(
                        """
                        INSERT INTO offer_changes(
                            offer_id, detected_at, change_type, changed_fields_json,
                            before_json, after_json, importance, notification_eligible
                        ) VALUES ('gpu:test', ?, 'updated', '[\"quota_value\"]',
                                  '{\"quota_value\":20}', '{\"quota_value\":30}',
                                  'high', 1)
                        """,
                        (NOW.isoformat(),),
                    )
                    connection.execute(
                        """
                        INSERT INTO notifications(
                            created_at, dedupe_key, title, body, target_url, item_count
                        ) VALUES (?, 'legacy', 'Old', 'Old history', '/old', 1)
                        """,
                        (NOW.isoformat(),),
                    )
                    connection.execute("PRAGMA user_version = 2")
            finally:
                connection.close()

            connection = connect(path)
            try:
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("offers", "offer_evidence", "fetch_runs", "offer_changes", "notifications")
                }
                source_row = connection.execute(
                    "SELECT etag, last_modified FROM sources WHERE source_id = ?",
                    (source.id,),
                ).fetchone()
                metadata = {
                    row[0]: row[1]
                    for row in connection.execute(
                        "SELECT key, value FROM radar_metadata"
                    )
                }
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(counts["offers"], 1)
        self.assertEqual(counts["offer_evidence"], 1)
        self.assertEqual(counts["fetch_runs"], 0)
        self.assertEqual(counts["offer_changes"], 0)
        self.assertEqual(counts["notifications"], 0)
        self.assertEqual(source_row["etag"], '"keep-etag"')
        self.assertEqual(source_row["last_modified"], "Tue, 29 Jul 2026 08:00:00 GMT")
        self.assertIn("history_rebuilt_at", metadata)
        self.assertEqual(metadata["vacuum_pending"], "0")

    def test_baseline_is_silent_then_quota_change_queues_one_digest(self) -> None:
        source = SOURCE_BY_ID["modal-pricing"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            connection = connect(path)
            try:
                first_at = NOW.isoformat()
                run_id, baseline = begin_run(connection, source.id, first_at)
                ingest_source(
                    connection,
                    source=source,
                    observations=(observation(),),
                    at=first_at,
                    run_id=run_id,
                    http_status=200,
                    etag=None,
                    last_modified=None,
                    content_hash="one",
                    baseline=baseline,
                )
                self.assertIsNone(enqueue_digest(connection, at=first_at))
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM offer_changes").fetchone()[0],
                    0,
                )

                second_at = (NOW + timedelta(days=1)).isoformat()
                run_id, baseline = begin_run(connection, source.id, second_at)
                ingest_source(
                    connection,
                    source=source,
                    observations=(observation(quota=40),),
                    at=second_at,
                    run_id=run_id,
                    http_status=200,
                    etag=None,
                    last_modified=None,
                    content_hash="two",
                    baseline=baseline,
                )
                notification_id = enqueue_digest(connection, at=second_at)
                compact_change = connection.execute(
                    """
                    SELECT changed_fields_json, before_json, after_json
                    FROM offer_changes ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            pending = pending_notifications(path)
            self.assertIsNotNone(notification_id)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["item_count"], 1)
            self.assertTrue(mark_notification(path, pending[0]["id"], status="delivered"))
            self.assertEqual(pending_notifications(path), ())
            changed_fields = set(json.loads(compact_change["changed_fields_json"]))
            self.assertEqual(set(json.loads(compact_change["before_json"])), changed_fields)
            self.assertEqual(set(json.loads(compact_change["after_json"])), changed_fields)
            self.assertNotIn("details", compact_change["before_json"])

    def test_two_successful_misses_are_required_before_removal(self) -> None:
        source = SOURCE_BY_ID["openrouter-models"]
        payloads = iter(
            (
                FetchPayload(
                    200,
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "test/model:free",
                                    "name": "Test Free",
                                    "pricing": {"prompt": "0", "completion": "0"},
                                }
                            ]
                        }
                    ).encode(),
                ),
                FetchPayload(200, b'{"data": []}'),
                FetchPayload(200, b'{"data": []}'),
            )
        )

        def fetcher(source, etag, last_modified, timeout):
            del source, etag, last_modified, timeout
            return next(payloads)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            first = refresh(
                path,
                source_ids=(source.id,),
                now=NOW,
                force=True,
                fetcher=fetcher,
            )
            self.assertEqual(first.maintenance["status"], "completed")
            self.assertGreater(first.maintenance["database_bytes"], 0)
            second = refresh(
                path,
                source_ids=(source.id,),
                now=NOW + timedelta(days=1),
                force=True,
                fetcher=fetcher,
            )
            self.assertEqual(second.sources[0].removed, 0)
            self.assertEqual(len(list_offers(path)), 1)
            third = refresh(
                path,
                source_ids=(source.id,),
                now=NOW + timedelta(days=2),
                force=True,
                fetcher=fetcher,
            )

            self.assertEqual(third.sources[0].removed, 1)
            self.assertEqual(list_offers(path), ())
            self.assertEqual(list_changes(path)[0]["change_type"], "removed")
            connection = connect(path)
            try:
                removed = connection.execute(
                    """
                    SELECT before_json, after_json FROM offer_changes
                    WHERE change_type = 'removed' ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNone(removed["before_json"])
            self.assertIsNone(removed["after_json"])

    def test_storage_retention_preserves_important_free_history(self) -> None:
        source = SOURCE_BY_ID["modal-pricing"]
        price = replace(
            observation(offer_id="gpu:price"),
            title="H100 Price",
            offer_type="pricing_reference",
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            connection = connect(path)
            try:
                run_id, baseline = begin_run(connection, source.id, NOW.isoformat())
                ingest_source(
                    connection,
                    source=source,
                    observations=(observation(), price),
                    at=NOW.isoformat(),
                    run_id=run_id,
                    http_status=200,
                    etag=None,
                    last_modified=None,
                    content_hash="retention",
                    baseline=baseline,
                )
                old_run = (NOW - timedelta(days=91)).isoformat()
                boundary_run = (NOW - timedelta(days=90)).isoformat()
                old_history = (NOW - timedelta(days=366)).isoformat()
                boundary_history = (NOW - timedelta(days=365)).isoformat()
                with connection:
                    connection.executemany(
                        """
                        INSERT INTO fetch_runs(
                            source_id, started_at, finished_at, status, item_count
                        ) VALUES (?, ?, ?, 'success', 0)
                        """,
                        (
                            (source.id, old_run, old_run),
                            (source.id, boundary_run, boundary_run),
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO offer_changes(
                            offer_id, detected_at, change_type, changed_fields_json,
                            importance, notification_eligible
                        ) VALUES (?, ?, 'updated', '[]', ?, 0)
                        """,
                        (
                            ("gpu:test", old_history, "high"),
                            ("gpu:test", old_history, "normal"),
                            ("gpu:price", old_history, "high"),
                            ("gpu:test", boundary_history, "normal"),
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO notifications(
                            created_at, dedupe_key, title, body, target_url,
                            item_count, status, delivered_at, read_at
                        ) VALUES (?, ?, 'Notice', 'Body', '/ai-resources.html',
                                  1, ?, ?, ?)
                        """,
                        (
                            (old_history, "old-delivered", "delivered", old_history, None),
                            (old_history, "old-read", "read", old_history, old_history),
                            (old_history, "old-pending", "pending", None, None),
                            (boundary_history, "recent-delivered", "delivered", boundary_history, None),
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE offers SET status = 'inactive', last_changed_at = ?
                        WHERE offer_id = 'gpu:price'
                        """,
                        (old_history,),
                    )
                result = maintain_storage(connection, now=NOW)
                remaining_runs = connection.execute(
                    "SELECT started_at FROM fetch_runs ORDER BY started_at"
                ).fetchall()
                remaining_changes = connection.execute(
                    "SELECT offer_id, detected_at, importance FROM offer_changes ORDER BY id"
                ).fetchall()
                remaining_notifications = connection.execute(
                    "SELECT dedupe_key FROM notifications ORDER BY dedupe_key"
                ).fetchall()
                price_count = connection.execute(
                    "SELECT COUNT(*) FROM offers WHERE offer_id = 'gpu:price'"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(result.pruned_fetch_runs, 1)
        self.assertEqual(result.pruned_changes, 2)
        self.assertEqual(result.pruned_notifications, 2)
        self.assertEqual(result.pruned_offers, 1)
        self.assertIn(boundary_run, {row["started_at"] for row in remaining_runs})
        self.assertEqual(len(remaining_changes), 2)
        self.assertIn(("gpu:test", "high"), {(row["offer_id"], row["importance"]) for row in remaining_changes})
        self.assertEqual(
            {row["dedupe_key"] for row in remaining_notifications},
            {"old-pending", "recent-delivered"},
        )
        self.assertEqual(price_count, 0)

    def test_vacuum_policy_uses_threshold_limit_and_pending_retry(self) -> None:
        self.assertFalse(
            _should_vacuum(
                pending=False,
                deleted=10,
                current=NOW,
                last_vacuum=(NOW - timedelta(days=29)).isoformat(),
                free_bytes=1024 * 1024,
                free_ratio=0.5,
            )
        )
        self.assertTrue(
            _should_vacuum(
                pending=False,
                deleted=10,
                current=NOW,
                last_vacuum=(NOW - timedelta(days=30)).isoformat(),
                free_bytes=512 * 1024,
                free_ratio=0.01,
            )
        )
        self.assertTrue(
            _should_vacuum(
                pending=False,
                deleted=1,
                current=NOW,
                last_vacuum=None,
                free_bytes=1,
                free_ratio=0.20,
            )
        )
        self.assertTrue(
            _should_vacuum(
                pending=True,
                deleted=0,
                current=NOW,
                last_vacuum=NOW.isoformat(),
                free_bytes=0,
                free_ratio=0,
            )
        )

    def test_vacuum_deferral_does_not_fail_storage_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            connection = connect(path)
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO radar_metadata(key, value)
                        VALUES ('vacuum_pending', '1')
                        ON CONFLICT(key) DO UPDATE SET value = '1'
                        """
                    )
                with patch(
                    "ai_resource_radar.store._try_vacuum",
                    return_value="deferred",
                ):
                    result = maintain_storage(connection, now=NOW)
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            finally:
                connection.close()

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.vacuum_status, "deferred")
        self.assertEqual(result.error_code, "storage_vacuum_deferred")

    def test_listing_order_prefers_mainland_supported_a_tier(self) -> None:
        source = SOURCE_BY_ID["modal-pricing"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ai.sqlite3"
            connection = connect(path)
            try:
                run_id, baseline = begin_run(connection, source.id, NOW.isoformat())
                ingest_source(
                    connection,
                    source=source,
                    observations=(
                        observation(offer_id="gpu:unknown", mainland="unknown"),
                        observation(offer_id="gpu:supported", mainland="supported"),
                        observation(
                            offer_id="gpu:community", verification="community"
                        ),
                    ),
                    at=NOW.isoformat(),
                    run_id=run_id,
                    http_status=200,
                    etag=None,
                    last_modified=None,
                    content_hash="list",
                    baseline=baseline,
                )
            finally:
                connection.close()
            offers = list_offers(path)
            summary = radar_summary(path, now=NOW)

        self.assertEqual(offers[0]["offer_id"], "gpu:supported")
        self.assertEqual(offers[-1]["priority_tier"], "D")
        self.assertEqual(summary["counts"]["tier_a"], 2)

    def test_dashboard_rejects_concurrent_background_refresh(self) -> None:
        class FakeReport:
            failed_count = 0

            @staticmethod
            def to_dict() -> dict[str, object]:
                return {"schema_version": "2.0", "sources": []}

        entered = Event()
        release = Event()

        def slow_refresh(path: Path, *, force: bool) -> FakeReport:
            del path, force
            entered.set()
            release.wait(2)
            return FakeReport()

        with tempfile.TemporaryDirectory() as temp:
            dashboard = AiRadarDashboard(Path(temp) / "ai.sqlite3")
            with patch(
                "ai_resource_radar.dashboard_state.refresh",
                side_effect=slow_refresh,
            ):
                self.assertIsNotNone(dashboard.start_refresh())
                self.assertTrue(entered.wait(1))
                self.assertIsNone(dashboard.start_refresh())
                release.set()
                for _ in range(100):
                    if dashboard.refresh_status()["status"] == "completed":
                        break
                    time.sleep(0.01)

        self.assertEqual(dashboard.refresh_status()["status"], "completed")


if __name__ == "__main__":
    unittest.main()
