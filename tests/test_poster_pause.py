from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from ai_resource_radar.cli import main as cli_main
from ai_resource_radar.doctor import diagnose
from ai_resource_radar.feature_flags import PosterFeaturePausedError
from ai_resource_radar.interfaces.http import route_radar_post
from ai_resource_radar.poster import (
    configure_poster,
    daily_report_status,
    generate_daily_poster,
    list_poster_models,
)
from ai_resource_radar.store import connect


class _NoopRadar:
    def schema_error(self):
        return None

    def start_poster(self, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("paused route started poster")

    def start_poster_benchmark(self, **kwargs):  # pragma: no cover
        raise AssertionError("paused route started benchmark")

    def review_poster_benchmark(self, **kwargs):  # pragma: no cover
        raise AssertionError("paused route reviewed benchmark")


class _RefreshReport:
    failed_count = 0

    def to_dict(self):
        return {"failed_count": self.failed_count}


class PosterPauseTests(unittest.TestCase):
    def test_status_and_models_are_read_only_and_unified(self) -> None:
        with TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connect(database).close()
            with patch("ai_resource_radar.poster.KeychainStore.get") as key_get, patch(
                "ai_resource_radar.poster._openclaw_provider_configured"
            ) as provider_probe:
                status = daily_report_status(database)
                models = list_poster_models(database)

        self.assertFalse(status["feature_visible"])
        self.assertFalse(status["generation_available"])
        self.assertEqual(status["reason"], "poster_feature_paused")
        self.assertTrue(models)
        self.assertTrue(
            all(
                item["feature_visible"] is False
                and item["generation_available"] is False
                and item["reason"] == "poster_feature_paused"
                for item in models
            )
        )
        key_get.assert_not_called()
        provider_probe.assert_not_called()

    def test_mutating_service_actions_fail_before_external_work(self) -> None:
        with TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            with patch("ai_resource_radar.poster.KeychainStore.get") as key_get, patch(
                "ai_resource_radar.poster.create_poster_generator"
            ) as create_generator:
                with self.assertRaisesRegex(PosterFeaturePausedError, "poster_feature_paused"):
                    generate_daily_poster(database)
                with self.assertRaisesRegex(PosterFeaturePausedError, "poster_feature_paused"):
                    configure_poster(
                        database,
                        enabled=True,
                        provider="openai",
                        model="gpt-image-2",
                    )

        key_get.assert_not_called()
        create_generator.assert_not_called()

    def test_paused_http_mutations_return_structured_conflict(self) -> None:
        for path, payload in (
            ("/api/ai-daily/generate", {}),
            ("/api/ai-daily/benchmark", {"cases": 1}),
            ("/api/ai-daily/benchmark/review", {"approve": True}),
        ):
            response = route_radar_post(_NoopRadar(), path, payload)
            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual(response.status, 409)
            self.assertEqual(
                response.payload,
                {
                    "schema_version": "1.0",
                    "error": "poster_feature_paused",
                    "feature_visible": False,
                    "generation_available": False,
                    "reason": "poster_feature_paused",
                },
            )

    def test_daily_cli_refreshes_without_calling_poster(self) -> None:
        with TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            output = StringIO()
            with patch("ai_resource_radar.cli.refresh", return_value=_RefreshReport()), patch(
                "ai_resource_radar.cli.refresh_official_tips",
                return_value={"failed": False},
            ), patch("ai_resource_radar.cli.generate_daily_poster") as generate, patch(
                "ai_resource_radar.cli.daily_report_status",
                return_value={"reason": "poster_feature_paused"},
            ), redirect_stdout(output):
                result = cli_main(["daily", "--database", str(database)])

        self.assertEqual(result, 0)
        generate.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["poster"]["reason"], "poster_feature_paused")

    def test_doctor_skips_ocr_and_provider_probes_when_paused(self) -> None:
        with TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            with connection:
                connection.execute(
                    "INSERT INTO radar_metadata(key, value) VALUES ('poster.enabled', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
            with patch("ai_resource_radar.doctor._openclaw_provider_configured") as probe:
                report = diagnose(database, check_services=False, check_conflicts=False)

        ocr = next(check for check in report.checks if check.id == "ocr")
        provider = next(check for check in report.checks if check.id == "poster_provider")
        self.assertEqual(ocr.status, "healthy")
        self.assertEqual(provider.status, "healthy")
        self.assertEqual(ocr.details["reason"], "poster_feature_paused")
        self.assertEqual(provider.details["reason"], "poster_feature_paused")
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
