from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
README_IMAGES = (
    "readme-public-overview.png",
    "readme-provider-openrouter.png",
    "readme-local-dashboard.png",
)
RAW_ASSET_ROOT = "https://raw.githubusercontent.com/ai-resource-radar/ai-resource-radar/main/docs/assets"


class ReadmeAssetTests(unittest.TestCase):
    def test_current_readme_images_are_fixed_size_pngs(self) -> None:
        for name in README_IMAGES:
            path = ASSETS / name
            self.assertTrue(path.is_file(), name)
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG", name)
                self.assertEqual(image.size, (1440, 1000), name)

    def test_bilingual_readmes_reference_only_current_product_images(self) -> None:
        for readme_name in ("README.md", "README.zh-CN.md"):
            text = (ROOT / readme_name).read_text(encoding="utf-8")
            for name in README_IMAGES:
                self.assertIn(f"{RAW_ASSET_ROOT}/{name}", text)
            self.assertNotIn("docs/assets/public-radar.png", text)
            self.assertNotIn("docs/assets/dashboard.png", text)
            self.assertNotIn("docs/assets/poster-sample.webp", text)

    def test_obsolete_product_images_are_removed(self) -> None:
        for name in ("public-radar.png", "dashboard.png", "poster-sample.webp"):
            self.assertFalse((ASSETS / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
