from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from ai_resource_radar.dashboard import create_server
from ai_resource_radar.locks import operation_lock
from ai_resource_radar.store import SCHEMA_VERSION


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.server = create_server(
            port=0,
            database=Path(self.temporary.name) / "radar.sqlite3",
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        response_headers = dict(response.getheaders())
        connection.close()
        return response.status, response_headers, payload

    def test_local_page_and_read_only_apis(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("免费资源雷达", body.decode())
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

        status, headers, body = self.request("GET", "/ai-radar-shared/cards.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertIn("createOfferCard", body.decode())

        status, _, _ = self.request("GET", "/ai-radar-shared/../../pyproject.toml")
        self.assertEqual(status, 404)

        status, _, body = self.request("GET", "/api/ai-resources/summary")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["counts"]["active"], 0)

        status, _, body = self.request("GET", "/api/ai-daily/latest")
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["report"])

        with patch(
            "ai_resource_radar.poster.KeychainStore.get",
            return_value=None,
        ):
            status, _, body = self.request("GET", "/api/ai-daily/status")
        daily_status = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(daily_status["provider"], "openai")
        self.assertEqual(daily_status["model"], "gpt-image-2")
        self.assertFalse(daily_status["configured"])
        self.assertTrue(daily_status["formal_poster_eligible"])
        self.assertEqual(daily_status["benchmark"]["benchmark_version"], "zh-poster-v1")
        self.assertEqual(daily_status["benchmark"]["passed_cases"], 0)
        self.assertEqual(daily_status["benchmark"]["remaining_calls_today"], 3)

        status, _, body = self.request("GET", "/api/ai-daily?days=0")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_daily_report_filter")

    def test_free_image_generation_filter_is_forwarded(self) -> None:
        with patch.object(self.server.radar, "offers", return_value=()) as offers:
            status, _, body = self.request(
                "GET",
                "/api/ai-resources?free_image_generation=true",
            )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["count"], 0)
        self.assertTrue(offers.call_args.kwargs["free_image_generation"])

    def test_tips_api_seeds_imports_and_rejects_candidate(self) -> None:
        status, _, body = self.request("GET", "/api/ai-tips/summary")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["counts"]["candidate"], 1)

        payload = {
            "title": "核验技巧",
            "category": "verification",
            "summary": "先核对来源。",
            "instruction": "批准前检查官方资料。",
            "source_url": "https://example.com/tip",
        }
        status, _, body = self.request(
            "POST",
            "/api/ai-tips/import",
            body=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 201)
        tip = json.loads(body)
        self.assertEqual(tip["status"], "candidate")

        status, _, body = self.request(
            "POST",
            f"/api/ai-tips/{tip['tip_id']}/review",
            body=b'{"action":"reject"}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "rejected")

    def test_rejects_untrusted_host_and_concurrent_tasks(self) -> None:
        status, _, body = self.request(
            "GET",
            "/api/ai-resources/summary",
            headers={"Host": "example.com"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "local_request_required")

        with patch.object(self.server.radar, "start_poster", return_value=None):
            status, _, body = self.request(
                "POST",
                "/api/ai-daily/generate",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "daily_poster_already_running")

    def test_benchmark_api_validates_budget_and_manual_review(self) -> None:
        status, _, body = self.request(
            "POST",
            "/api/ai-daily/benchmark",
            body=b'{"cases":4}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_poster_benchmark_request")

        with patch.object(self.server.radar, "start_poster_benchmark", return_value={"task": "running"}) as start:
            status, _, _ = self.request(
                "POST",
                "/api/ai-daily/benchmark",
                body=b'{"cases":2}',
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 202)
        start.assert_called_once_with(cases=2)

        with patch.object(
            self.server.radar,
            "review_poster_benchmark",
            return_value={"formal_poster_eligible": True},
        ) as review:
            status, _, body = self.request(
                "POST",
                "/api/ai-daily/benchmark/review",
                body=json.dumps({"approve": True, "notes": "人工检查通过"}).encode(),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["formal_poster_eligible"])
        review.assert_called_once_with(approve=True, notes="人工检查通过")

    def test_newer_database_schema_returns_structured_503(self) -> None:
        database = self.server.radar.path
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA user_version = 99")
        finally:
            connection.close()

        status, _, body = self.request("GET", "/api/ai-resources/summary")
        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "ai_radar_schema_unsupported")
        self.assertEqual(payload["database_schema_version"], 99)
        self.assertEqual(payload["runtime_supported_schema_version"], SCHEMA_VERSION)

        status, _, body = self.request(
            "POST",
            "/api/ai-daily/generate",
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 503)
        self.assertEqual(
            json.loads(body)["error"],
            "ai_radar_schema_unsupported",
        )

    def test_external_poster_lock_maps_to_conflict(self) -> None:
        with operation_lock(self.server.radar.path, "poster"):
            status, _, body = self.request(
                "POST",
                "/api/ai-daily/generate",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "daily_poster_already_running")


if __name__ == "__main__":
    unittest.main()
