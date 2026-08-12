from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_resource_radar.public_site import PublicSiteError, _page_prices, build_public_site
from ai_resource_radar.sources import SOURCES


NOW = datetime(2026, 8, 10, 8, 20, tzinfo=timezone.utc)


def offer(kind: str, offer_id: str) -> dict:
    return {
        "offer_id": offer_id,
        "provider": "Example AI",
        "title": f"Official {kind}",
        "kind": kind,
        "offer_type": "recurring_free" if kind != "grant" else "grant",
        "quota_value": 30,
        "quota_unit": "USD" if kind != "token" else "requests",
        "reset_period": "monthly",
        "estimated_usd_value": 30,
        "requires_card": "no",
        "requires_phone": "unknown",
        "eligibility": None,
        "mainland_status": "supported",
        "expires_at": None,
        "homepage_url": "https://example.com/free",
        "verification_level": "official_page",
        "priority_tier": "A",
        "priority_reasons": ["official"],
        "details": {"benefit_summary": "free", "api_key": "must-not-export"},
        "last_seen_at": NOW.isoformat(),
        "last_changed_at": NOW.isoformat(),
        "evidence": {
            "source_id": f"example-{kind}",
            "source_url": "https://example.com/evidence",
            "verification_level": "official_page",
            "evidence_excerpt": "Official public evidence.",
            "observed_at": NOW.isoformat(),
        },
    }


def token_price() -> dict:
    return {
        "price_id": "token:price",
        "provider": "Prices",
        "model": "Model",
        "input_per_mtok": 0.1,
        "output_per_mtok": 0.2,
        "typical_cost": 0.15,
        "currency": "USD",
        "pricing_url": "https://example.com/token-price",
        "verification_level": "community",
        "verified_at": NOW.isoformat(),
    }


def gpu_price() -> dict:
    return {
        "price_id": "gpu:price",
        "provider": "Compute",
        "title": "H100",
        "gpu_model": "H100",
        "hourly_usd": 1.5,
        "vram_gb": 80,
        "currency": "USD",
        "pricing_url": "https://example.com/gpu-price",
        "verification_level": "official_page",
        "verified_at": NOW.isoformat(),
    }


def summary(status: str = "fresh", *, source_count: int = 1, refreshed_at: datetime = NOW) -> dict:
    source_items = [
        {
            "source_id": (SOURCES[index].id if source_count == len(SOURCES) else f"source-{index}"),
            "name": (SOURCES[index].name if source_count == len(SOURCES) else f"Source {index}"),
            "authority": "official_page",
            "cadence_hours": 24,
            "status": status,
            "last_attempt_at": refreshed_at.isoformat(),
            "last_success_at": refreshed_at.isoformat(),
        }
        for index in range(source_count)
    ]
    return {
        "counts": {"active": 4},
        "last_refresh_at": refreshed_at.isoformat(),
        "sources": {
            "total": source_count,
            "fresh": source_count if status == "fresh" else 0,
            "overdue": 0,
            "stale": 0,
            "verification_pending": 0,
            "failed": source_count if status == "failed" else 0,
            "never": 0,
            "items": source_items,
        },
        "notifications": {"unread": 99},
        "storage": {"database_bytes": 999, "local_path": "/Users/private"},
    }


class PublicSiteTests(unittest.TestCase):
    def _build(
        self,
        root: Path,
        *,
        source_status: str = "fresh",
        source_count: int = 1,
        refreshed_at: datetime = NOW,
        refresh_report: dict | None = None,
        source_revision: str | None = None,
    ) -> dict:
        database = root / "radar.sqlite3"
        database.touch()
        resources = {"token": [offer("token", "token:free")], "gpu": [offer("gpu", "gpu:free")], "grant": [offer("grant", "grant:one")]}
        with patch("ai_resource_radar.public_site._page_offers", side_effect=lambda _p, *, kind, include_pricing: resources[kind]), patch(
            "ai_resource_radar.public_site._page_prices", side_effect=lambda _p, *, kind: [token_price()] if kind == "token" else [gpu_price()]
        ), patch("ai_resource_radar.public_site.list_changes", return_value=()), patch(
            "ai_resource_radar.public_site.radar_summary",
            return_value=summary(source_status, source_count=source_count, refreshed_at=refreshed_at),
        ):
            return build_public_site(
                database,
                root / "site",
                now=NOW,
                refresh_report=refresh_report,
                source_revision=source_revision,
            )

    @staticmethod
    def _refresh_report(*, status: str = "success", mode: str = "forced") -> dict:
        return {
            "generated_at": NOW.isoformat(),
            "refresh_mode": mode,
            "sources": [
                {"source_id": source.id, "status": status}
                for source in SOURCES
            ],
        }

    def test_exports_json_csv_hashes_and_excludes_private_state(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._build(root)
            site = root / "site"
            resources = json.loads((site / "data/resources.json").read_text())
            public_summary = json.loads((site / "data/summary.json").read_text())
            with (site / "data/resources.csv").open(newline="", encoding="utf-8") as handle:
                csv_rows = list(csv.DictReader(handle))
            public_text = "\n".join(path.read_text(encoding="utf-8") for path in (site / "data").rglob("*.json"))
            self.assertEqual(manifest["schema_version"], "1.3")
            self.assertEqual(manifest["dataset"], "ai-resource-radar-public")
            self.assertEqual(manifest["package_version"], "0.8.0")
            self.assertEqual(manifest["source_revision"], "local")
            self.assertEqual(manifest["refresh_mode"], "cadence")
            self.assertEqual(manifest["data_age_seconds"], 0)
            self.assertEqual(manifest["status"], "healthy")
            self.assertEqual(manifest["analytics_provider"], "none")
            self.assertEqual(manifest["search_console_provider"], "none")
            self.assertEqual(manifest["experiment_started_at"], "2026-08-12")
            self.assertTrue((site / "feed.xml").is_file())
            self.assertTrue((site / "rss.xml").is_file())
            self.assertTrue((site / "en/feed.xml").is_file())
            self.assertTrue((site / "en/rss.xml").is_file())
            self.assertNotIn("static.cloudflareinsights.com", (site / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(len(resources["items"]), len(csv_rows))
            self.assertTrue((site / "data/source-health.json").exists())
            self.assertNotIn("must-not-export", public_text)
            self.assertNotIn("/Users/private", public_text)
            self.assertNotIn("notifications", public_summary["radar"])
            self.assertNotIn("storage", public_summary["radar"])
            for name in ("cards.js", "cards.css", "dom.js", "formatters.js", "radar-tokens.css"):
                self.assertTrue((site / "shared" / name).is_file())
            for relative, expected in manifest["file_hashes"].items():
                self.assertEqual(hashlib.sha256((site / relative).read_bytes()).hexdigest(), expected)

    def test_failed_gate_preserves_existing_output(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "radar.sqlite3"; database.touch()
            output = root / "site"; output.mkdir(); (output / "sentinel").write_text("old")
            with patch("ai_resource_radar.public_site._page_offers", return_value=[]), patch("ai_resource_radar.public_site._page_prices", return_value=[]), patch("ai_resource_radar.public_site.list_changes", return_value=[]), patch("ai_resource_radar.public_site.radar_summary", return_value=summary()):
                with self.assertRaisesRegex(PublicSiteError, "publish_gate_failed"):
                    build_public_site(database, output, now=NOW)
            self.assertEqual((output / "sentinel").read_text(), "old")

    def test_source_failure_publishes_partial_snapshot(self) -> None:
        with TemporaryDirectory() as temp:
            manifest = self._build(Path(temp), source_status="failed")
        self.assertEqual(manifest["status"], "partial")

    def test_refresh_report_binds_revision_and_all_registered_sources(self) -> None:
        with TemporaryDirectory() as temp:
            manifest = self._build(
                Path(temp),
                source_count=len(SOURCES),
                refresh_report=self._refresh_report(),
                source_revision="abc123",
            )
        self.assertEqual(manifest["source_revision"], "abc123")
        self.assertEqual(manifest["refresh_mode"], "forced")
        self.assertEqual(manifest["refresh_started_at"], NOW.isoformat())
        self.assertEqual(manifest["source_health"]["total"], 23)
        self.assertEqual(manifest["data_age_seconds"], 0)

    def test_refresh_report_rejects_missing_source_and_preserves_old_site(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "site"
            output.mkdir()
            (output / "sentinel").write_text("old", encoding="utf-8")
            report = self._refresh_report()
            report["sources"].pop()
            with self.assertRaisesRegex(PublicSiteError, "incomplete_source_attempt"):
                self._build(
                    root,
                    source_count=len(SOURCES),
                    refresh_report=report,
                )
            self.assertEqual((output / "sentinel").read_text(encoding="utf-8"), "old")

    def test_forced_report_cannot_skip_and_data_must_be_fresh(self) -> None:
        skipped = self._refresh_report(status="skipped_not_due")
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PublicSiteError, "forced_refresh_skipped"):
                self._build(
                    Path(temp),
                    source_count=len(SOURCES),
                    refresh_report=skipped,
                )

    def test_refresh_report_requires_known_mode_and_exact_source_rows(self) -> None:
        invalid_mode = self._refresh_report(mode="unexpected")
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PublicSiteError, "invalid_refresh_report"):
                self._build(
                    Path(temp),
                    source_count=len(SOURCES),
                    refresh_report=invalid_mode,
                )
        duplicate = self._refresh_report()
        duplicate["sources"].append(dict(duplicate["sources"][0]))
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PublicSiteError, "incomplete_source_attempt"):
                self._build(
                    Path(temp),
                    source_count=len(SOURCES),
                    refresh_report=duplicate,
                )
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PublicSiteError, "data_too_old"):
                self._build(
                    Path(temp),
                    source_count=len(SOURCES),
                    refreshed_at=NOW - timedelta(minutes=31),
                    refresh_report=self._refresh_report(),
                )

    def test_single_source_failure_can_publish_partial_when_all_attempted(self) -> None:
        report = self._refresh_report()
        report["sources"][0]["status"] = "failed"
        with TemporaryDirectory() as temp:
            manifest = self._build(
                Path(temp),
                source_status="failed",
                source_count=len(SOURCES),
                refresh_report=report,
            )
        self.assertEqual(manifest["status"], "partial")

    def test_price_pagination_reaches_total(self) -> None:
        first = {"total": 501, "prices": [{"price_id": str(i)} for i in range(500)]}
        second = {"total": 501, "prices": [{"price_id": "500"}]}
        with patch("ai_resource_radar.public_site.list_token_prices", side_effect=[first, second]) as call:
            rows = _page_prices(Path("ignored"), kind="token")
        self.assertEqual(len(rows), 501)
        self.assertEqual(call.call_count, 2)

    def test_cloudflare_analytics_is_explicit_and_environment_only(self) -> None:
        token = "x" * 24
        with TemporaryDirectory() as temp, patch.dict(
            "os.environ", {"AI_RADAR_CLOUDFLARE_ANALYTICS_TOKEN": token}
        ):
            root = Path(temp)
            database = root / "radar.sqlite3"
            database.touch()
            resources = {
                "token": [offer("token", "token:free")],
                "gpu": [offer("gpu", "gpu:free")],
                "grant": [offer("grant", "grant:one")],
            }
            with patch(
                "ai_resource_radar.public_site._page_offers",
                side_effect=lambda _p, *, kind, include_pricing: resources[kind],
            ), patch(
                "ai_resource_radar.public_site._page_prices",
                side_effect=lambda _p, *, kind: [token_price()] if kind == "token" else [gpu_price()],
            ), patch("ai_resource_radar.public_site.list_changes", return_value=()), patch(
                "ai_resource_radar.public_site.radar_summary", return_value=summary()
            ):
                manifest = build_public_site(
                    database,
                    root / "site",
                    now=NOW,
                    analytics_provider="cloudflare",
                )
            html = (root / "site/index.html").read_text(encoding="utf-8")
            self.assertEqual(manifest["analytics_provider"], "cloudflare")
            self.assertEqual(html.count("static.cloudflareinsights.com/beacon.min.js"), 1)
            self.assertIn("https://cloudflareinsights.com", html)
            self.assertIn(token, html)
            self.assertNotIn('spa":true', html)

        with TemporaryDirectory() as temp, patch.dict("os.environ", {}, clear=True):
            root = Path(temp)
            database = root / "radar.sqlite3"
            database.touch()
            with self.assertRaisesRegex(PublicSiteError, "invalid_cloudflare"):
                build_public_site(
                    database,
                    root / "site",
                    now=NOW,
                    analytics_provider="cloudflare",
                )

    def test_google_search_console_is_environment_only_and_atomic(self) -> None:
        token = "google-site-verification-token-12345"
        with TemporaryDirectory() as temp, patch.dict(
            "os.environ", {"AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN": token}, clear=True
        ):
            root = Path(temp)
            manifest = self._build(root)
            # Rebuild through the same fixture patches with explicit Google mode.
            database = root / "radar.sqlite3"
            resources = {
                "token": [offer("token", "token:free")],
                "gpu": [offer("gpu", "gpu:free")],
                "grant": [offer("grant", "grant:one")],
            }
            with patch(
                "ai_resource_radar.public_site._page_offers",
                side_effect=lambda _p, *, kind, include_pricing: resources[kind],
            ), patch(
                "ai_resource_radar.public_site._page_prices",
                side_effect=lambda _p, *, kind: [token_price()] if kind == "token" else [gpu_price()],
            ), patch("ai_resource_radar.public_site.list_changes", return_value=()), patch(
                "ai_resource_radar.public_site.radar_summary", return_value=summary()
            ):
                manifest = build_public_site(
                    database,
                    root / "site",
                    now=NOW,
                    search_console_provider="google",
                )
            html = (root / "site/index.html").read_text(encoding="utf-8")
            public_data = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "site/data").rglob("*.json")
            )
            self.assertEqual(manifest["search_console_provider"], "google")
            self.assertEqual(html.count('name="google-site-verification"'), 1)
            self.assertIn(token, html)
            self.assertNotIn(token, public_data)

        with TemporaryDirectory() as temp, patch.dict("os.environ", {}, clear=True):
            root = Path(temp)
            database = root / "radar.sqlite3"
            database.touch()
            output = root / "site"
            output.mkdir()
            (output / "sentinel").write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(PublicSiteError, "invalid_google"):
                build_public_site(
                    database,
                    output,
                    now=NOW,
                    search_console_provider="google",
                )
            self.assertEqual((output / "sentinel").read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
