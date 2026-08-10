from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_resource_radar.public_site import PublicSiteError, _page_prices, build_public_site


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


def summary(status: str = "fresh") -> dict:
    return {
        "counts": {"active": 4},
        "last_refresh_at": NOW.isoformat(),
        "sources": {
            "total": 1,
            "fresh": int(status == "fresh"),
            "overdue": 0,
            "stale": 0,
            "verification_pending": 0,
            "failed": int(status == "failed"),
            "never": 0,
            "items": [{"source_id": "source", "name": "Source", "authority": "official_page", "cadence_hours": 24, "status": status, "last_success_at": NOW.isoformat()}],
        },
        "notifications": {"unread": 99},
        "storage": {"database_bytes": 999, "local_path": "/Users/private"},
    }


class PublicSiteTests(unittest.TestCase):
    def _build(self, root: Path, *, source_status: str = "fresh") -> dict:
        database = root / "radar.sqlite3"
        database.touch()
        resources = {"token": [offer("token", "token:free")], "gpu": [offer("gpu", "gpu:free")], "grant": [offer("grant", "grant:one")]}
        with patch("ai_resource_radar.public_site._page_offers", side_effect=lambda _p, *, kind, include_pricing: resources[kind]), patch(
            "ai_resource_radar.public_site._page_prices", side_effect=lambda _p, *, kind: [token_price()] if kind == "token" else [gpu_price()]
        ), patch("ai_resource_radar.public_site.list_changes", return_value=()), patch(
            "ai_resource_radar.public_site.radar_summary", return_value=summary(source_status)
        ):
            return build_public_site(database, root / "site", now=NOW)

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
            self.assertEqual(manifest["schema_version"], "1.0")
            self.assertEqual(manifest["dataset"], "ai-resource-radar-public")
            self.assertEqual(manifest["status"], "healthy")
            self.assertEqual(len(resources["items"]), len(csv_rows))
            self.assertTrue((site / "data/source-health.json").exists())
            self.assertNotIn("must-not-export", public_text)
            self.assertNotIn("/Users/private", public_text)
            self.assertNotIn("notifications", public_summary["radar"])
            self.assertNotIn("storage", public_summary["radar"])
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

    def test_price_pagination_reaches_total(self) -> None:
        first = {"total": 501, "prices": [{"price_id": str(i)} for i in range(500)]}
        second = {"total": 501, "prices": [{"price_id": "500"}]}
        with patch("ai_resource_radar.public_site.list_token_prices", side_effect=[first, second]) as call:
            rows = _page_prices(Path("ignored"), kind="token")
        self.assertEqual(len(rows), 501)
        self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
