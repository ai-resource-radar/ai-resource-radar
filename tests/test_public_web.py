from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).parents[1] / "src/ai_resource_radar/public_web"
SHARED = ROOT.parent / "frontend_shared"


class PublicWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.shared_javascript = "\n".join(
            path.read_text(encoding="utf-8") for path in SHARED.glob("*.js")
        )

    def test_has_bilingual_read_only_views_and_csp(self) -> None:
        self.assertIn("Content-Security-Policy", self.html)
        for group in ("free", "prices"):
            self.assertIn(f'data-group="{group}"', self.html)
        for view in ("recommended", "token", "gpu", "grant", "token-prices", "gpu-prices"):
            self.assertIn(f'data-view="{view}"', self.html)
        self.assertNotIn('data-view="changes"', self.html)
        self.assertIn('./data/changes.json', self.html)
        self.assertIn("language-toggle", self.html)
        self.assertIn('class="github-cta"', self.html)
        self.assertIn('href="https://github.com/ai-resource-radar/ai-resource-radar"', self.html)
        self.assertIn('rel="noopener noreferrer"', self.html)
        self.assertIn('referrerpolicy="no-referrer"', self.html)
        self.assertNotIn("<form", self.html.lower())
        self.assertNotIn("加载更多", self.html)
        for pager_id in ("previous-page", "page-label", "next-page"):
            self.assertIn(f'id="{pager_id}"', self.html)

    def test_uses_static_relative_data_and_safe_dom_rendering(self) -> None:
        for name in ("manifest", "summary", "source-health", "resources", "token-prices", "gpu-prices", "changes"):
            self.assertIn(f'data/{name}.json', self.javascript)
        browser_code = self.javascript + self.shared_javascript
        self.assertIn("textContent", browser_code)
        self.assertNotIn("innerHTML", browser_code)
        self.assertNotIn("fetch(\"http", self.javascript)
        self.assertNotIn("method: \"POST\"", self.javascript)
        self.assertIn("noopener noreferrer", self.shared_javascript)
        self.assertIn('from "./shared/cards.js"', self.javascript)

    def test_assets_are_local_and_downloads_exist(self) -> None:
        self.assertIn('href="./styles.css"', self.html)
        self.assertIn('src="./app.js"', self.html)
        self.assertIn('@import url("./shared/radar-tokens.css")', (ROOT / "styles.css").read_text(encoding="utf-8"))
        for name in ("cards.js", "cards.css", "dom.js", "formatters.js", "radar-tokens.css"):
            self.assertTrue((SHARED / name).exists())
        self.assertIn("download-json", self.html)
        self.assertIn("download-csv", self.html)
        self.assertTrue((ROOT / "robots.txt").exists())
        self.assertTrue((ROOT / "sitemap.xml").exists())
        self.assertTrue((ROOT / "social-preview.png").exists())
        with Image.open(ROOT / "social-preview.png") as preview:
            self.assertEqual(preview.size, (1280, 640))
        self.assertIn('property="og:image"', self.html)
        self.assertIn("social-preview.png", self.html)
        for local_only in ("poster", "tips", "doctor", "manual-refresh"):
            self.assertNotIn(local_only, self.html.lower())


if __name__ == "__main__":
    unittest.main()
