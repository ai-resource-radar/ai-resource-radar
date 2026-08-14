from __future__ import annotations

from pathlib import Path
import unittest

from ai_resource_radar.provider_pages import render_provider_page
from ai_resource_radar.provider_profiles import PROVIDER_PROFILES
from ai_resource_radar.public_site import PUBLIC_SCHEMA_VERSION, _resource
from ai_resource_radar.scenario_pages import render_scenario_page


ROOT = Path(__file__).parents[1] / "src" / "ai_resource_radar"


class PublicI18nV09Tests(unittest.TestCase):
    def test_manifest_resource_contract_is_bilingual_and_structured(self) -> None:
        record = {
            "offer_id": "example:free",
            "provider": "Example",
            "title": "Example free API",
            "kind": "token",
            "offer_type": "recurring_free",
            "requires_card": "no",
            "requires_phone": "unknown",
            "eligibility": "仅限中国大陆用户",  # Legacy source prose.
            "mainland_status": "unknown",
            "verification_level": "official_page",
            "priority_tier": "A",
            "evidence": {"source_id": "example", "source_url": "https://example.com"},
        }
        exported = _resource(record)
        self.assertEqual(PUBLIC_SCHEMA_VERSION, "1.4")
        self.assertIn("availability", exported)
        self.assertIn("signup_requirements", exported)
        self.assertIn("presentations", exported)
        self.assertIn("en", exported["presentations"])

    def test_english_static_pages_use_english_default_and_no_legacy_policy_body(self) -> None:
        row = {
            "offer_id": "example:free",
            "provider": "Example",
            "title": "Example free API",
            "kind": "token",
            "offer_type": "recurring_free",
            "requires_card": "no",
            "mainland_status": "supported",
            "verification_level": "official_page",
            "priority_tier": "A",
            "eligibility": "仅限中国大陆用户",
            "homepage_url": "https://example.com",
        }
        page = render_scenario_page(
            "free-ai-api-no-card", [row], locale="en",
            base_url="https://radar.example/", require_minimum=False,
        )
        self.assertIn('hreflang="x-default" href="https://radar.example/en/scenarios/', page)
        self.assertNotIn("仅限中国大陆用户", page)
        provider = render_provider_page(
            PROVIDER_PROFILES[0], locale="en", base_url="https://radar.example/",
            resources=[], token_prices=[], gpu_prices=[], integration=None,
            source_revision="test", analytics_script="", csp="default-src 'self'",
        )
        self.assertIn('hreflang="x-default" href="https://radar.example/en/providers/', provider)

    def test_frontend_locale_and_geography_are_explicit_url_state(self) -> None:
        public_html = (ROOT / "public_web" / "index.html").read_text(encoding="utf-8")
        public_js = (ROOT / "public_web" / "app.js").read_text(encoding="utf-8")
        dashboard_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        router_js = (ROOT / "web" / "modules" / "state-router.js").read_text(encoding="utf-8")
        resources_js = (ROOT / "web" / "modules" / "views" / "resources.js").read_text(encoding="utf-8")
        dashboard_js = (ROOT / "web" / "modules" / "legacy-dashboard.js").read_text(encoding="utf-8")
        dashboard_i18n = (ROOT / "web" / "modules" / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', public_html)
        self.assertNotIn("localStorage", public_js)
        self.assertIn('params.get("lang")', public_js)
        for control in ("country-filter", "region-filter", "include-unknown-region"):
            self.assertIn(control, dashboard_html)
        for parameter in ("country", "region", "include_unknown_region"):
            self.assertIn(parameter, router_js)
            self.assertIn(parameter, resources_js)
        for control in ("country-filter", "region-filter", "include-unknown-region"):
            self.assertIn(control, public_html)
        self.assertIn('url.searchParams.set("country"', public_js)
        self.assertIn('url.searchParams.set("include_unknown"', public_js)
        self.assertIn("matchesSelectedAvailability", public_js)
        self.assertNotIn('localStorage', public_js)
        self.assertIn("Promise.all([loadProviderProfiles(), registryRecommended()]).finally(loadCurrentView)", dashboard_js)
        self.assertNotIn("navigator.language", dashboard_i18n)
        self.assertNotIn("localStorage", dashboard_i18n)


if __name__ == "__main__":
    unittest.main()
