from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ai_resource_radar.cli import _parser as cli_parser, main as cli_main
from ai_resource_radar.locks import OperationLockedError, operation_lock
from ai_resource_radar.poster import (
    OPENCLAW_POSTER_MODEL,
    GeneratedPoster,
    KeychainStore,
    MAX_IMAGE_RESPONSE_BYTES,
    MAX_POSTER_ATTEMPTS_PER_DAY,
    OpenClawImageGenerator,
    OpenAIImageGenerator,
    POSTER_NOTICE,
    POSTER_TITLE,
    PosterFacts,
    PosterRequest,
    _detect_image,
    _read_image_file,
    configure_poster,
    daily_report_status,
    generate_daily_poster,
    latest_daily_report,
    list_daily_reports,
    list_poster_models,
    prune_daily_posters,
    select_poster_facts,
    test_poster_model,
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
    provider = "openai"
    model = "gpt-image-2"

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


class SquareGenerator(FakeGenerator):
    def __init__(self) -> None:
        super().__init__()
        image = Image.new("RGB", (1024, 1024), "#14231a")
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        self.body = buffer.getvalue()

    def generate(self, request, *, api_key: str) -> GeneratedPoster:
        generated = super().generate(request, api_key=api_key)
        return GeneratedPoster(
            body=generated.body,
            request_id=generated.request_id,
            media_type="image/png",
        )


class ZaiGenerator(FakeGenerator):
    provider = "openclaw"
    model = OPENCLAW_POSTER_MODEL
    requires_api_key = False


class UnknownGenerator(FakeGenerator):
    provider = "unregistered"
    model = "unreviewed-image-model"


class SequenceOCR:
    def __init__(self, values: list[str]) -> None:
        self.values = iter(values)
        self.calls = 0

    def recognize(self, image_path: Path) -> str:
        self.calls += 1
        self.last_path = image_path
        return next(self.values)


class InspectingOCR(SequenceOCR):
    def recognize(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            self.seen_format = image.format
            self.seen_size = image.size
        return super().recognize(image_path)


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
                for value in (
                    fact.kind,
                    fact.provider,
                    fact.title,
                    fact.value,
                    fact.instruction,
                )
            ),
            POSTER_NOTICE,
            f"数据截至 {facts.refreshed_at[:16].replace('T', ' ')}",
        ]
    )


class PosterTests(unittest.TestCase):
    def test_daily_cli_is_successful_when_source_failures_are_isolated(self) -> None:
        report = type(
            "Report",
            (),
            {"failed_count": 2, "to_dict": lambda self: {"failed_count": 2}},
        )()
        output = StringIO()
        with tempfile.TemporaryDirectory() as temp, patch(
            "ai_resource_radar.cli.refresh", return_value=report
        ), patch(
            "ai_resource_radar.cli.generate_daily_poster",
            return_value={"status": "disabled", "error_code": "poster_disabled"},
        ), patch(
            "ai_resource_radar.cli.daily_report_status", return_value={"enabled": False}
        ), redirect_stdout(output):
            exit_code = cli_main(
                ["daily", "--database", str(Path(temp) / "radar.sqlite3")]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["refresh"]["failed_count"], 2)

    def test_cli_exposes_doctor_and_poster_configuration_commands(self) -> None:
        doctor = cli_parser().parse_args(["doctor", "--json"])
        configure = cli_parser().parse_args(
            [
                "poster",
                "configure",
                "--provider",
                "openclaw",
                "--model",
                "zai/cogview-3-flash",
                "--enable",
            ]
        )
        generate = cli_parser().parse_args(
            ["poster", "generate", "--model", "gpt-image-2"]
        )
        model_test = cli_parser().parse_args(
            [
                "poster",
                "test-model",
                "--provider",
                "openclaw",
                "--model",
                "zai/cogview-3-flash",
                "--output",
                "zai-smoke.png",
            ]
        )

        self.assertTrue(doctor.json)
        self.assertEqual(configure.poster_action, "configure")
        self.assertTrue(configure.enable)
        self.assertEqual(generate.model, "gpt-image-2")
        self.assertEqual(model_test.poster_action, "test-model")

    def test_cli_returns_structured_error_for_newer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 99")
            connection.close()
            errors = StringIO()
            with redirect_stderr(errors):
                exit_code = cli_main(["list", "--database", str(path)])

        payload = json.loads(errors.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"], "ai_radar_schema_unsupported")
        self.assertEqual(payload["database_schema_version"], 99)
        self.assertEqual(payload["runtime_supported_schema_version"], 6)

    def test_cli_forwards_free_image_generation_filter(self) -> None:
        output = StringIO()
        with patch(
            "ai_resource_radar.cli.list_offers",
            return_value=(),
        ) as offers, redirect_stdout(output):
            exit_code = cli_main(["list", "--free-image-generation"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(offers.call_args.kwargs["free_image_generation"])

    def test_poster_generation_uses_cross_process_operation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            with operation_lock(path, "poster"), self.assertRaises(
                OperationLockedError
            ):
                generate_daily_poster(
                    path,
                    now=NOW,
                    generator=FakeGenerator(),
                    ocr=SequenceOCR([]),
                    key_store=FakeKeyStore(),
                )

    def test_openclaw_adapter_detects_actual_jpeg_output(self) -> None:
        image = Image.new("RGB", (720, 1440), "#14231a")
        buffer = BytesIO()
        image.save(buffer, format="JPEG")

        def run(command, **kwargs):
            del kwargs
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(buffer.getvalue())
            payload = {
                "ok": True,
                "outputs": [
                    {
                        "path": str(output),
                        "mimeType": "image/png",
                        "dimensions": {"width": 720, "height": 1440},
                    }
                ],
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with patch("ai_resource_radar.poster.subprocess.run", side_effect=run):
            generated = OpenClawImageGenerator(
                binary="/usr/bin/openclaw",
                timeout=1,
            ).generate(PosterRequest(prompt="日报"))

        self.assertEqual(generated.media_type, "image/jpeg")
        self.assertEqual((generated.width, generated.height), (720, 1440))

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
            ocr = InspectingOCR([valid_ocr_text(facts)])
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=poster_root,
                generator=generator,
                ocr=ocr,
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
            self.assertEqual(ocr.seen_format, "WEBP")
            self.assertEqual(ocr.seen_size, (1080, 1440))

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

    def test_rejects_wrong_aspect_ratio_before_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            generator = SquareGenerator()
            ocr = SequenceOCR([])
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=Path(temp) / "posters",
                generator=generator,
                ocr=ocr,
                key_store=FakeKeyStore(),
            )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_code"], "poster_image_aspect_ratio_invalid")
        self.assertEqual(generator.calls, MAX_POSTER_ATTEMPTS_PER_DAY)
        self.assertEqual(ocr.calls, 0)

    def test_zai_is_rejected_for_formal_poster_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            generator = ZaiGenerator()
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=Path(temp) / "posters",
                generator=generator,
                ocr=SequenceOCR([]),
                key_store=FakeKeyStore(),
            )

        self.assertEqual(report["error_code"], "poster_model_not_formal_eligible")
        self.assertEqual(report["provider"], "openclaw")
        self.assertEqual(report["model"], "zai/cogview-3-flash")
        self.assertEqual(generator.calls, 0)

    def test_zai_has_an_explicit_nonformal_capability_smoke(self) -> None:
        generator = ZaiGenerator()
        with tempfile.TemporaryDirectory() as temp, patch(
            "ai_resource_radar.poster._model_configuration_status",
            return_value=(True, None),
        ):
            result = test_poster_model(
                provider="openclaw",
                model="zai/cogview-3-flash",
                output=Path(temp) / "zai-smoke.requested",
                generator=generator,
            )
            image_path = Path(result["image_path"])
            mode = image_path.stat().st_mode & 0o777

        self.assertEqual(result["status"], "success")
        self.assertFalse(result["formal_poster_eligible"])
        self.assertEqual(result["media_type"], "image/png")
        self.assertEqual(image_path.suffix, ".png")
        self.assertEqual(mode, 0o600)
        self.assertEqual(generator.calls, 1)

    def test_failed_force_regeneration_preserves_published_poster_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            poster_root = Path(temp) / "posters"
            seed_offers(path)
            facts = select_poster_facts(path, now=NOW)
            published = generate_daily_poster(
                path,
                now=NOW,
                poster_root=poster_root,
                generator=FakeGenerator(),
                ocr=SequenceOCR([valid_ocr_text(facts)]),
                key_store=FakeKeyStore(),
            )
            failed = generate_daily_poster(
                path,
                force=True,
                now=NOW,
                poster_root=poster_root,
                generator=FakeGenerator(),
                ocr=SequenceOCR(["错误 901", "错误 902"]),
                key_store=FakeKeyStore(),
            )
            still_published = latest_daily_report(path)
            status = daily_report_status(
                path,
                key_store=FakeKeyStore(),
                current=NOW.date(),
            )

        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["preserved_published_report"])
        self.assertIsNotNone(still_published)
        assert still_published is not None
        for field in (
            "status",
            "provider",
            "model",
            "selected_facts",
            "validation",
            "image_path",
            "image_sha256",
        ):
            self.assertEqual(still_published[field], published[field])
        self.assertIsNone(still_published["error_code"])
        self.assertEqual(still_published["attempt_count"], 3)
        self.assertEqual(
            status["last_failure"]["error_code"], "poster_validation_failed"
        )

    def test_unregistered_generator_cannot_bypass_formal_model_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            generator = UnknownGenerator()
            report = generate_daily_poster(
                path,
                now=NOW,
                poster_root=Path(temp) / "posters",
                generator=generator,
                ocr=SequenceOCR([]),
                key_store=FakeKeyStore(),
            )

        self.assertEqual(report["error_code"], "poster_model_unsupported")
        self.assertEqual(generator.calls, 0)

    def test_provider_aware_status_and_model_registry(self) -> None:
        payload = {
            "providers": [
                {
                    "id": "zai",
                    "configured": True,
                    "selected": True,
                    "model": "cogview-3-flash",
                    "models": ["cogview-3-flash"],
                }
            ]
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with (
            tempfile.TemporaryDirectory() as temp,
            patch(
                "ai_resource_radar.poster.subprocess.run",
                return_value=completed,
            ),
            patch(
                "ai_resource_radar.poster._default_openclaw_binary",
                return_value="/usr/bin/openclaw",
            ),
        ):
            path = Path(temp) / "radar.sqlite3"
            configuration = configure_poster(
                path,
                enabled=True,
                provider="openclaw",
                model="zai/cogview-3-flash",
            )
            status = daily_report_status(
                path,
                key_store=FakeKeyStore(),
                current=NOW.date(),
                openclaw_binary="/usr/bin/openclaw",
            )
            models = list_poster_models(
                path,
                key_store=FakeKeyStore(),
                openclaw_binary="/usr/bin/openclaw",
            )

        self.assertTrue(configuration["configured"])
        self.assertTrue(status["enabled"])
        self.assertTrue(status["configured"])
        self.assertEqual(status["provider"], "openclaw")
        self.assertEqual(status["model"], "zai/cogview-3-flash")
        self.assertFalse(status["formal_poster_eligible"])
        self.assertEqual(status["reason"], "chinese_ocr_benchmark_failed")
        self.assertEqual(len(models), 2)
        self.assertEqual(sum(bool(item["selected"]) for item in models), 1)

    def test_openclaw_configuration_requires_the_registered_model(self) -> None:
        payload = {
            "providers": [
                {
                    "id": "zai",
                    "configured": True,
                    "models": ["another-image-model"],
                }
            ]
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with tempfile.TemporaryDirectory() as temp, patch(
            "ai_resource_radar.poster.subprocess.run", return_value=completed
        ):
            path = Path(temp) / "radar.sqlite3"
            configure_poster(
                path,
                enabled=True,
                provider="openclaw",
                model="zai/cogview-3-flash",
            )
            status = daily_report_status(
                path,
                key_store=FakeKeyStore(),
                current=NOW.date(),
                openclaw_binary="/usr/bin/openclaw",
            )

        self.assertFalse(status["configured"])
        self.assertEqual(
            status["configuration_reason"],
            "openclaw_model_cogview-3-flash_not_configured",
        )

    def test_disabled_poster_does_not_create_failure_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(
            KeychainStore,
            "get",
            return_value=None,
        ):
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            configure_poster(path, enabled=False)
            report = generate_daily_poster(path, now=NOW)
            connection = connect(path)
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM daily_reports"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(report["status"], "disabled")
        self.assertEqual(count, 0)

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

    def test_keychain_does_not_read_environment_fallback(self) -> None:
        completed = subprocess.CompletedProcess([], 44, "", "not found")
        with patch.dict(
            "os.environ",
            {"AI_RADAR_OPENAI_API_KEY": "must-not-be-read"},
        ), patch(
            "ai_resource_radar.poster.subprocess.run",
            return_value=completed,
        ):
            value = KeychainStore().get()

        self.assertIsNone(value)

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

    def test_validator_requires_titles_actions_and_refresh_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.sqlite3"
            seed_offers(path)
            facts = select_poster_facts(path, now=NOW)
            text = valid_ocr_text(facts)
            text = text.replace(facts.facts[0].title, "")
            text = text.replace(facts.facts[1].instruction, "")
            text = text.replace(
                f"数据截至 {facts.refreshed_at[:16].replace('T', ' ')}",
                "",
            )
            validation = validate_poster_text(text, facts)

        self.assertFalse(validation.valid)
        self.assertIn(facts.facts[0].title, validation.missing_anchors)
        self.assertIn(facts.facts[1].instruction, validation.missing_anchors)
        self.assertTrue(any(anchor.startswith("数据截至") for anchor in validation.missing_anchors))

    def test_image_guards_reject_oversized_files_and_pixels_before_load(self) -> None:
        class HugeImage:
            format = "PNG"
            size = (100_000, 100_000)
            loaded = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def load(self):
                self.loaded = True

        huge = HugeImage()
        with patch("PIL.Image.open", return_value=huge), self.assertRaisesRegex(
            RuntimeError, "poster_image_dimensions_invalid"
        ):
            _detect_image(b"not-decoded")
        self.assertFalse(huge.loaded)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "oversized.png"
            with path.open("wb") as stream:
                stream.seek(MAX_IMAGE_RESPONSE_BYTES)
                stream.write(b"x")
            with self.assertRaisesRegex(RuntimeError, "poster_response_too_large"):
                _read_image_file(path)

    def test_v3_to_current_preserves_existing_history_and_notifications(self) -> None:
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

            self.assertEqual(version, 6)
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
