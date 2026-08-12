from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/pages.yml"


class V080SearchConsoleWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        cls.public_site = (ROOT / "docs/PUBLIC_SITE.md").read_text(encoding="utf-8")
        cls.privacy = (ROOT / "docs/PRIVACY.md").read_text(encoding="utf-8")
        cls.changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_production_maps_only_the_approved_search_console_secret(self) -> None:
        self.assertIn(
            "AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN: ${{ secrets.GOOGLE_SITE_VERIFICATION_TOKEN }}",
            self.workflow,
        )
        self.assertIn("--search-console-provider google", self.workflow)
        self.assertNotIn('echo "$AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN"', self.workflow)
        self.assertNotIn("cat $AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN", self.workflow)
        self.assertNotIn("secrets.OPENAI_API_KEY", self.workflow)
        self.assertNotIn("secrets.ANTHROPIC_API_KEY", self.workflow)

    def test_publication_gate_requires_v08_routes_and_manifest_markers(self) -> None:
        for marker in (
            'payload.get("search_console_provider") != "google"',
            'payload.get("scenario_pages")',
            'scenario_count',
            'int(scenario_count or 0) != 12',
            'payload.get("feeds")',
            'feed_count',
            'feed_count != 4',
            'payload.get("experiment_started_at")',
            '"feed.xml", "rss.xml", "en/feed.xml", "en/rss.xml"',
            'name="google-site-verification"',
            'pages_gate_search_console_marker',
        ):
            self.assertIn(marker, self.workflow)

    def test_docs_describe_feeds_and_non_conversion_experiment(self) -> None:
        for text in (self.readme, self.readme_zh, self.public_site, self.privacy):
            self.assertIn("30", text)
            self.assertRegex(text.lower(), r"confirm|确认")
            self.assertRegex(text.lower(), r"not an exact|不是精确|不等于")
        self.assertIn("scenario_pages", self.public_site)
        self.assertIn("feeds", self.public_site)
        self.assertIn("0.8.0", self.changelog)

    def test_package_version_is_v080(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        facade = (ROOT / "src/ai_resource_radar/__init__.py").read_text(encoding="utf-8")
        self.assertIn('version = "0.8.0"', pyproject)
        self.assertIn('__version__ = "0.8.0"', facade)
        self.assertIn('"schema_version": "1.3"', self.public_site)


if __name__ == "__main__":
    unittest.main()
