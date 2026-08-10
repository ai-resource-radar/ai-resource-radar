from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1] / "src/ai_resource_radar/public_web"


class PublicWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_has_bilingual_read_only_views_and_csp(self) -> None:
        self.assertIn("Content-Security-Policy", self.html)
        for tab in ("recommended", "token", "gpu", "grant", "token-prices", "gpu-prices", "changes", "about"):
            self.assertIn(f'data-tab="{tab}"', self.html)
        self.assertIn("language-toggle", self.html)
        self.assertNotIn("<form", self.html.lower())

    def test_uses_static_relative_data_and_safe_dom_rendering(self) -> None:
        for name in ("manifest", "summary", "source-health", "resources", "token-prices", "gpu-prices", "changes"):
            self.assertIn(f'data/{name}.json', self.javascript)
        self.assertIn("textContent", self.javascript)
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("fetch(\"http", self.javascript)
        self.assertNotIn("method: \"POST\"", self.javascript)
        self.assertIn("noopener noreferrer", self.javascript)

    def test_assets_are_local_and_downloads_exist(self) -> None:
        self.assertIn('href="./styles.css"', self.html)
        self.assertIn('src="./app.js"', self.html)
        self.assertIn("download-json", self.html)
        self.assertIn("download-csv", self.html)
        self.assertTrue((ROOT / "robots.txt").exists())
        self.assertTrue((ROOT / "sitemap.xml").exists())
        self.assertTrue((ROOT / "social-preview.png").exists())
        self.assertIn('property="og:image"', self.html)
        self.assertIn("social-preview.png", self.html)


if __name__ == "__main__":
    unittest.main()
