from __future__ import annotations

import unittest

from ai_resource_radar.scenario_pages import (
    SCENARIO_SLUGS,
    ScenarioPageError,
    aggregate_providers,
    build_scenario_pages,
    render_scenario_confirmation_page,
    render_scenario_page,
    scenario_rows,
)


BASE_URL = "https://example.test/radar/"


def resource(provider: str, *, kind: str = "token", **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "offer_id": f"{provider}:{kind}",
        "provider": provider,
        "provider_slug": provider.casefold(),
        "title": f"{provider} free",
        "kind": kind,
        "offer_type": "recurring_free",
        "verification_level": "official_page",
        "priority_tier": "A",
        "status": "active",
        "requires_card": "no",
        "mainland_status": "supported",
        "free_image_generation": False,
        "quota_value": 10,
        "quota_unit": "requests",
        "reset_period": "daily",
        "homepage_url": "https://example.test/" + provider,
        "presentation": {
            "zh-CN": {
                "benefit_summary": "每周期返还免费额度",
                "usage_steps": ["打开官方页面", "创建 API key", "调用接口"],
            },
            "en": {
                "benefit_summary": "A recurring free allowance",
                "usage_steps": ["Open the official page", "Create an API key", "Call the endpoint"],
            },
        },
        "evidence": {
            "source_url": "https://example.test/evidence/" + provider,
            "observed_at": "2026-08-12T00:00:00Z",
        },
    }
    row.update(overrides)
    return row


class ScenarioPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resources = [
            resource("Alpha", free_image_generation=True),
            resource("Beta", free_image_generation=True),
            resource("Gamma", free_image_generation=True),
            resource("Delta", kind="gpu", free_image_generation=False),
            resource("Epsilon", kind="gpu", free_image_generation=False),
            resource("Zeta", kind="gpu", free_image_generation=False),
        ]
        self.integrations = [
            {"provider_slug": name, "integration_verified": True, "protocols": ["chat_completions"]}
            for name in ("alpha", "beta", "gamma")
        ]

    def test_stable_scenario_slugs_and_minimum_gate(self) -> None:
        self.assertEqual(
            SCENARIO_SLUGS,
            (
                "free-ai-api-no-card",
                "recurring-free-ai-api",
                "free-gpu-compute",
                "mainland-supported-free-ai-api",
                "free-image-generation-api",
                "openai-compatible-free-ai-api",
            ),
        )
        rows = scenario_rows("free-ai-api-no-card", self.resources)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(aggregate_providers(rows)), 3)
        with self.assertRaises(ScenarioPageError):
            scenario_rows("free-gpu-compute", self.resources[:2], require_minimum=True)

    def test_gates_reject_community_c_tier_inactive_and_non_mainland(self) -> None:
        rows = self.resources + [
            resource("Community", verification_level="community"),
            resource("Tier C", priority_tier="C"),
            resource("Inactive", status="inactive"),
            resource("Unsupported", mainland_status="unsupported"),
        ]
        selected = scenario_rows("mainland-supported-free-ai-api", rows)
        self.assertEqual({item["provider"] for item in selected}, {"Alpha", "Beta", "Gamma"})

    def test_openai_requires_verified_chat_completions(self) -> None:
        no_protocol = scenario_rows("openai-compatible-free-ai-api", self.resources)
        self.assertEqual(no_protocol, [])
        selected = scenario_rows(
            "openai-compatible-free-ai-api",
            self.resources,
            integrations=self.integrations,
        )
        self.assertEqual(len(selected), 3)
        rejected = scenario_rows(
            "openai-compatible-free-ai-api",
            self.resources,
            integrations=[{"provider_slug": "alpha", "integration_verified": False, "protocols": ["chat_completions"]}],
        )
        self.assertEqual(rejected, [])
        self.assertEqual(
            scenario_rows(
                "openai-compatible-free-ai-api",
                self.resources,
                integrations=[{"provider_slug": "alpha", "protocols": ["chat_completions"]}],
            ),
            [],
        )
        self.assertEqual(
            scenario_rows(
                "openai-compatible-free-ai-api",
                self.resources,
                integrations=[{"provider_slug": "alpha", "integration_verified": True, "protocols": ["responses"]}],
            ),
            [],
        )

    def test_bilingual_html_has_seo_schema_and_escaped_content(self) -> None:
        rows = [resource("<Provider>", title="<Unsafe>", homepage_url="https://example.test/<x>")]
        rows.extend(resource(name) for name in ("Beta", "Gamma"))
        html = render_scenario_page(
            "free-ai-api-no-card",
            locale="en",
            base_url=BASE_URL,
            resources=rows,
        )
        self.assertIn('rel="canonical"', html)
        self.assertIn('hreflang="zh-CN"', html)
        self.assertIn('hreflang="en"', html)
        self.assertIn("BreadcrumbList", html)
        self.assertIn("ItemList", html)
        self.assertIn("\\u003cUnsafe\\u003e", html)
        self.assertNotIn("<Unsafe>", html)
        self.assertIn("What you get", html)
        self.assertIn("Requirements", html)
        self.assertIn("How to claim", html)
        self.assertIn("Official evidence / verified", html)
        self.assertIn("I successfully connected", html)
        self.assertIn("<details>", html)
        self.assertIn("<noscript>", html)
        self.assertNotIn("data/resources.json", html)

    def test_external_links_strip_credentials_and_json_ld_is_safe(self) -> None:
        rows = [
            resource(
                "Unsafe",
                homepage_url="https://user:password@example.test/api?api_key=secret&ok=1",
            ),
            resource("Beta"),
            resource("Gamma"),
        ]
        html = render_scenario_page(
            "free-ai-api-no-card",
            locale="en",
            base_url=BASE_URL,
            resources=rows,
        )
        self.assertNotIn("user:password", html)
        self.assertNotIn("api_key=secret", html)
        self.assertIn("https://example.test/api?ok=1", html)

    def test_confirmation_is_noindex_and_contains_only_its_slug(self) -> None:
        slug = "free-gpu-compute"
        html = render_scenario_confirmation_page(slug, locale="zh-CN", base_url=BASE_URL)
        self.assertIn('name="robots" content="noindex,follow"', html)
        self.assertIn("感谢你自愿确认已成功接入", html)
        self.assertIn("返回场景页", html)
        self.assertIn(slug, html)
        for other in SCENARIO_SLUGS:
            if other != slug:
                self.assertNotIn(other, html)

    def test_build_api_returns_twelve_pages_with_companions(self) -> None:
        pages = build_scenario_pages(self.resources, self.integrations, base_url=BASE_URL)
        self.assertEqual(len(pages), 12)
        self.assertEqual({page.slug for page in pages}, set(SCENARIO_SLUGS))
        self.assertEqual({page.locale for page in pages}, {"zh-CN", "en"})
        self.assertTrue(all(page.provider_count >= 3 and page.resource_count >= 3 for page in pages))
        self.assertTrue(all('noindex,follow' in page.confirmation_html for page in pages))

    def test_build_api_skips_thin_scenarios_in_both_locales(self) -> None:
        thin = [dict(row, free_image_generation=False) for row in self.resources]
        pages = build_scenario_pages(thin, self.integrations, base_url=BASE_URL)
        self.assertNotIn("free-image-generation-api", {page.slug for page in pages})
        self.assertEqual(len(pages), 10)


if __name__ == "__main__":
    unittest.main()
