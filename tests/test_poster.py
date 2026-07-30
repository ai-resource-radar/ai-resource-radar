from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ai_resource_radar.poster import (
    GeneratedPoster,
    KeychainStore,
    MAX_POSTER_ATTEMPTS_PER_DAY,
    OpenAIImageGenerator,
    POSTER_NOTICE,
    POSTER_TITLE,
    PosterFacts,
    PosterRequest,
    generate_daily_poster,
    latest_daily_report,
    list_daily_reports,
    prune_daily_posters,
    select_poster_facts,
    validate_poster_text,
)
from ai_resource_radar.store import connect


NOW = datetime(2026, 7, 30, 8, 15, tzinfo=timezone.utc)


class FakeKeyStore:
    def __init__(self, key: str | None = "test-key") -> None:
        self.key = key

    def get(self) -> str | None:
        return self.key


class FakeGenerator:
    provider = "fake"
    model = "fake-image"

    def __init__(self) -> None:
        self.calls = 0
        image = Image.new("RGB", (1088, 1440), "#14231a")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        self.body = buffer.getvalue()

    def generate(self, request, *, api_key: str) -> GeneratedPoster:
        self.calls += 1
        self.last_prompt = request.prompt
        self.last_key = api_key
        return GeneratedPoster(
            body=self.body,
            request_id=f"request-{self.calls}",
        )


class SequenceOCR:
    def __init__(self, values: list[str]) -> None:
        self.values = iter(values)
        self.calls = 0

    def recognize(self, image_path: Path) -> str:
        self.calls += 1
        self.last_path = image_path
        return next(self.values)


def _offer_values(
    offer_id: str,
    provider: str,
    title: str,
    *,
    kind: str,
    offer_type: str,
    quota_value: float | None = None,
    quota_unit: str | None = None,
    details: dict | None = None,
) -> tuple:
    timestamp = NOW.isoformat()
    return (
        offer_id,
        provider,
        title,
        kind,
        offer_type,
        quota_value,
        quota_unit,
        "monthly",
        10.0,
        "no",
        "no",
        "公开注册",
        "unknown",
        None,
        f"https://example.com/{offer_id}",
        "official_page",
        "A",
        '["官方核验"]',
        json.dumps(details or {}, ensure_ascii=False),
        f"fingerprint-{offer_id}",
        "active",
        timestamp,
        timestamp,
        timestamp,
    )


def seed_offers(path: Path) -> None:
    connection = connect(path)
    try:
        rows = [
            _offer_values(
                "free-1",
                "Alpha AI",
                "Alpha Free",
                kind="token",
                offer_type="recurring_free",
                quota_value=100,
                quota_unit="requests",
                details={"usage_steps": ["注册账号并创建 API Key"]},
            ),
            _offer_values(
                "free-2",
                "Beta Compute",
                "Beta GPU",
                kind="gpu",
                offer_type="recurring_free",
                quota_value=5,
                quota_unit="GPU hours",
                details={"usage_steps": ["创建免费工作区"]},
            ),
            _offer_values(
                "free-3",
                "Gamma Cloud",
                "Gamma Grant",
                kind="grant",
                offer_type="grant",
                quota_value=20,
                quota_unit="USD compute credit",
                details={"usage_steps": ["填写公开申请表"]},
            ),
            _offer_values(
                "token-price",
                "Cheap Token",
                "Cheap Text Model",
                kind="token",
                offer_type="pricing_reference",
                details={
                    "model_id": "cheap-text",
                    "context_window": 128000,
                    "prices": {"input_mtok": 0.1, "output_mtok": 0.2},
                },
            ),
            _offer_values(
                "gpu-price",
                "Cheap GPU",
                "A100",
                kind="gpu",
                offer_type="pricing_reference",
                details={
                    "gpu_model": "A100",
                    "hourly_usd": 0.25,
                    "vram_gb": 80,
                    "billing_mode": "per-second",
                    "market_tier": "on-demand",
                    "price_mode": "fixed",
                },
            ),
        ]
        with connection:
            connection.executemany(
                """
                INSERT INTO offers(
                    offer_id, provider, title, kind, offer_type,
                    quota_value, quota_unit, reset_period, estimated_usd_value,
                    requires_card, requires_phone, eligibility, mainland_status,
                    expires_at, homepage_url, verification_level, priority_tier,
                    priority_reasons_json, details_json, fingerprint, status,
                    first_seen_at, last_seen_at, last_changed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    finally:
        connection.close()


def valid_ocr_text(facts: PosterFacts) -> str:
    return "\n".join(
        [
            POSTER_TITLE,
            facts.report_date,
            f"资源 {facts.active_count} A 级 {facts.tier_a_count} 今日新增 {facts.new_today_count}",
            *(
                value
                for fact in facts.facts
                for value in (fact.provider, fact.title, fact.value, fact.instruction)
            ),
            POSTER_NOTICE,
            f"数据截至 {facts.refreshed_at[:16].replace('T', ' ')}",
        ]
    )


class PosterTests(unittest.TestCase):
    def test_openai_adapter_sends_medium_portrait_request_and_reads_base64(self) -> None:
        encoded = base64.b64encode(b"image-bytes").decode()

        class Response:
            headers = {"x-request-id": "request-123"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                self.limit = limit
                return json.dumps({"data": [{"b64_json": encoded}]}).encode()

        with patch(
            "ai_resource_radar.poster.urlopen", return_value=Response()
        ) as open_url:
            generated = OpenAIImageGenerator().generate(
                PosterRequest(prompt="精确中文"),
                api_key="secret-key",
            )

        request = open_url.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["model"], "gpt-image-2")
        self.assertEqual(body["quality"], "medium")
        self.assertEqual(body["size"], "1088x1440")
        self.assertEqual(generated.body, b"image-bytes")
        self.assertEqual(generated.request_id, "request-123")

    def test_keychain_write_passes_secret_on_stdin_not_process_arguments(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch(
            "ai_resource_radar.poster.subprocess.run",
            return_value=completed,
        ) as run:
            KeychainStore().set("secret-key")

        command = run.call_args.args[0]
        self.assertNotIn("secret-key", command)
        self.assertEqual(run.call_args.kwargs["input"], "secret-key\n")

    def test_selects_three_free_offers_and_two_price_leaders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            facts = select_poster_facts(path, now=NOW)

        self.assertEqual(len(facts.facts), 5)
        self.assertEqual([item.kind for item in facts.facts[:3]], ["免费资源"] * 3)
        self.assertEqual(facts.facts[3].provider, "Cheap Token")
        self.assertIn("$0.1", facts.facts[3].value)
        self.assertEqual(facts.facts[4].provider, "Cheap GPU")
        self.assertEqual(facts.facts[4].value, "$0.25 / GPU 小时")

    def test_success_saves_only_validated_webp_and_notification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "radar.sqlite3"
            poster_root = root / "posters"
            seed_offers(path)
            facts = select_poster_facts(path, now=NOW)
            generator = FakeGenerator()
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=poster_root,
                generator=generator,
                ocr=SequenceOCR([valid_ocr_text(facts)]),
                key_store=FakeKeyStore(),
            )
            connection = connect(path)
            try:
                notification_count = connection.execute(
                    "SELECT COUNT(*) FROM notifications WHERE dedupe_key = ?",
                    (f"daily-poster:{facts.report_date}",),
                ).fetchone()[0]
            finally:
                connection.close()

            image_path = poster_root / report["image_path"]
            self.assertEqual(report["status"], "success")
            self.assertEqual(report["attempt_count"], 1)
            self.assertTrue(image_path.is_file())
            with Image.open(image_path) as image:
                self.assertEqual(image.size, (1080, 1440))
                self.assertEqual(image.format, "WEBP")
            self.assertEqual(notification_count, 1)
            self.assertEqual(list(poster_root.glob("*.png")), [])

    def test_validation_retries_twice_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "radar.sqlite3"
            seed_offers(path)
            facts = select_poster_facts(path, now=NOW)
            generator = FakeGenerator()
            ocr = SequenceOCR(["错误海报 999", "仍然错误 998", valid_ocr_text(facts)])

            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=root / "posters",
                generator=generator,
                ocr=ocr,
                key_store=FakeKeyStore(),
            )

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["attempt_count"], MAX_POSTER_ATTEMPTS_PER_DAY)
        self.assertEqual(generator.calls, MAX_POSTER_ATTEMPTS_PER_DAY)
        self.assertIn("Previous validation failures", generator.last_prompt)

    def test_three_invalid_images_stop_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "radar.sqlite3"
            seed_offers(path)
            generator = FakeGenerator()
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=root / "posters",
                generator=generator,
                ocr=SequenceOCR(["错误 901", "错误 902", "错误 903"]),
                key_store=FakeKeyStore(),
            )
            second = generate_daily_poster(
                path,
                now=NOW,
                poster_root=root / "posters",
                generator=generator,
                ocr=SequenceOCR(["不会调用"]),
                key_store=FakeKeyStore(),
            )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(second["error_code"], "poster_daily_attempt_limit")
        self.assertEqual(generator.calls, MAX_POSTER_ATTEMPTS_PER_DAY)
        self.assertIsNone(latest_daily_report(path))

    def test_missing_key_records_unconfigured_without_consuming_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=Path(temp) / "posters",
                generator=FakeGenerator(),
                ocr=SequenceOCR([]),
                key_store=FakeKeyStore(None),
            )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_code"], "poster_not_configured")
        self.assertEqual(report["attempt_count"], 0)

    def test_validator_rejects_unexpected_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            facts = select_poster_facts(path, now=NOW)
            validation = validate_poster_text(
                valid_ocr_text(facts) + "\n额外优惠 $999",
                facts,
            )

        self.assertFalse(validation.valid)
        self.assertIn("999", validation.unexpected_numbers)

    def test_v3_to_v4_preserves_existing_history_and_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            connection = connect(path)
            with connection:
                connection.execute(
                    """
                    INSERT INTO notifications(
                        created_at, dedupe_key, title, body, target_url, item_count
                    ) VALUES (?, 'keep-me', 'title', 'body', '/', 1)
                    """,
                    (NOW.isoformat(),),
                )
                connection.execute("DROP TABLE daily_reports")
                connection.execute("PRAGMA user_version = 3")
            connection.close()

            migrated = connect(path)
            try:
                version = migrated.execute("PRAGMA user_version").fetchone()[0]
                notification_count = migrated.execute(
                    "SELECT COUNT(*) FROM notifications WHERE dedupe_key = 'keep-me'"
                ).fetchone()[0]
                daily_table = migrated.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'daily_reports'"
                ).fetchone()[0]
            finally:
                migrated.close()

        self.assertEqual(version, 4)
        self.assertEqual(notification_count, 1)
        self.assertEqual(daily_table, 1)

    def test_prune_removes_old_database_row_and_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "radar.sqlite3"
            poster_root = root / "posters"
            poster_root.mkdir()
            image = poster_root / "2026-01-01.webp"
            image.write_bytes(b"old")
            connection = connect(path)
            with connection:
                connection.execute(
                    """
                    INSERT INTO daily_reports(
                        report_date, status, generated_at, provider, model,
                        quality, attempt_count, selected_facts_json,
                        validation_json, image_path, image_bytes, updated_at
                    ) VALUES (
                        '2026-01-01', 'success', ?, 'fake', 'fake', 'medium',
                        1, '{}', '{}', '2026-01-01.webp', 3, ?
                    )
                    """,
                    (NOW.isoformat(), NOW.isoformat()),
                )
            connection.close()

            deleted = prune_daily_posters(
                path,
                poster_root=poster_root,
                now=NOW,
            )

        self.assertEqual(deleted, 1)
        self.assertFalse(image.exists())
        self.assertEqual(list_daily_reports(path), ())


if __name__ == "__main__":
    unittest.main()
