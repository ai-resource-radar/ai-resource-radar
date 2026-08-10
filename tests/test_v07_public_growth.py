from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from ai_resource_radar.provider_pages import MAX_REPORT_BODY, correction_report_url
from ai_resource_radar.provider_profiles import PROVIDER_PROFILES
from ai_resource_radar.public_site import build_public_site

from tests.test_public_site import NOW, gpu_price, offer, summary, token_price


class PublicGrowthTests(unittest.TestCase):
    def _build(self, root: Path, *, analytics_provider: str = "none") -> tuple[dict, Path]:
        database = root / "radar.sqlite3"
        database.touch()
        token = offer("token", "openrouter:free")
        token["provider"] = "OpenRouter"
        token["evidence"]["source_id"] = "openrouter-models"
        token["title"] = "OpenRouter free router"
        gpu = offer("gpu", "modal:free")
        gpu["provider"] = "Modal"
        gpu["evidence"]["source_id"] = "modal-pricing"
        grant = offer("grant", "modal:grant")
        grant["provider"] = "Modal"
        grant["evidence"]["source_id"] = "modal-pricing"
        resources = {"token": [token], "gpu": [gpu], "grant": [grant]}
        token_row = token_price()
        token_row["provider"] = "OpenRouter"
        gpu_row = gpu_price()
        gpu_row["provider"] = "Modal"
        with patch(
            "ai_resource_radar.public_site._page_offers",
            side_effect=lambda _p, *, kind, include_pricing: resources[kind],
        ), patch(
            "ai_resource_radar.public_site._page_prices",
            side_effect=lambda _p, *, kind: [token_row] if kind == "token" else [gpu_row],
        ), patch("ai_resource_radar.public_site.list_changes", return_value=()), patch(
            "ai_resource_radar.public_site.radar_summary", return_value=summary()
        ):
            manifest = build_public_site(
                database,
                root / "site",
                now=NOW,
                source_revision="v07-test",
                analytics_provider=analytics_provider,
            )
        return manifest, root / "site"

    def test_generates_twenty_bilingual_crawlable_provider_pages(self) -> None:
        with TemporaryDirectory() as temp:
            manifest, site = self._build(Path(temp))
            providers = json.loads((site / "data/providers.json").read_text(encoding="utf-8"))
            integrations = json.loads((site / "data/integrations.json").read_text(encoding="utf-8"))
            resources = json.loads((site / "data/resources.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "1.2")
            self.assertEqual(manifest["counts"]["providers"], 20)
            self.assertEqual(len(providers["items"]), 20)
            self.assertEqual(len(integrations["items"]), 9)
            for profile in PROVIDER_PROFILES:
                for language in ("zh", "en"):
                    page = site / language / "providers" / profile.slug / "index.html"
                    self.assertTrue(page.is_file(), page)
                    html = page.read_text(encoding="utf-8")
                    self.assertIn('rel="canonical"', html)
                    self.assertIn('hreflang="zh-CN"', html)
                    self.assertIn('hreflang="en"', html)
                    self.assertIn('itemscope itemtype="https://schema.org/Service"', html)
                    self.assertNotIn("data/resources.json", html)
            self.assertFalse((site / "zh/providers/mnfst-free-llm-apis").exists())
            self.assertFalse((site / "en/providers/pydantic-genai-prices").exists())
            self.assertEqual(sum(1 for _ in site.glob("*/providers/huggingface/index.html")), 2)
            first = resources["items"][0]
            self.assertIn(first["provider_slug"], {"openrouter", "modal"})
            self.assertIn("provider_urls", first)
            self.assertIn("data-correction", first["report_url"])
            sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(sitemap.count("<url>"), 41)

    def test_landing_payload_is_bounded_and_full_catalog_urls_remain(self) -> None:
        with TemporaryDirectory() as temp:
            _, site = self._build(Path(temp))
            critical = (
                "manifest.json", "summary.json", "source-health.json",
                "featured.json", "important-changes.json",
            )
            self.assertLess(sum((site / "data" / name).stat().st_size for name in critical), 150_000)
            for legacy in ("resources.json", "token-prices.json", "gpu-prices.json", "changes.json"):
                self.assertTrue((site / "data" / legacy).is_file())

    def test_report_prefill_is_bounded_and_excludes_private_fields(self) -> None:
        url = correction_report_url(
            {
                "provider": "OpenRouter",
                "offer_id": "offer-1",
                "title": "Free policy",
                "homepage_url": "https://openrouter.ai/docs",
                "api_key": "sk-must-not-leak",
                "local_path": "/Users/private/radar.sqlite3",
                "search_query": "private query",
            },
            source_revision="abc123",
        )
        query = parse_qs(urlparse(url).query)
        body = query["body"][0]
        self.assertLessEqual(len(body), MAX_REPORT_BODY)
        self.assertIn("offer-1", body)
        self.assertNotIn("sk-must-not-leak", body)
        self.assertNotIn("/Users/private", body)
        self.assertNotIn("private query", body)

    def test_report_prefill_strips_url_credentials_and_secret_query_values(self) -> None:
        url = correction_report_url(
            {
                "provider": "OpenRouter",
                "offer_id": "offer-2",
                "homepage_url": (
                    "https://user:password@openrouter.ai/docs?"
                    "output_modalities=all&api_key=sk-private&access_token=private"
                    "#account-fragment"
                ),
            },
            source_revision="abc123",
        )
        body = parse_qs(urlparse(url).query)["body"][0]
        self.assertIn("https://openrouter.ai/docs?output_modalities=all", body)
        self.assertNotIn("user:password", body)
        self.assertNotIn("sk-private", body)
        self.assertNotIn("access_token", body)
        self.assertNotIn("account-fragment", body)

    def test_cloudflare_beacon_is_present_once_on_each_generated_page(self) -> None:
        with TemporaryDirectory() as temp, patch.dict(
            "os.environ",
            {"AI_RADAR_CLOUDFLARE_ANALYTICS_TOKEN": "x" * 24},
        ):
            _, site = self._build(Path(temp), analytics_provider="cloudflare")
            for page in (site / "index.html", site / "zh/providers/openrouter/index.html"):
                html = page.read_text(encoding="utf-8")
                self.assertEqual(html.count("static.cloudflareinsights.com/beacon.min.js"), 1)
                self.assertIn("https://cloudflareinsights.com", html)


if __name__ == "__main__":
    unittest.main()
