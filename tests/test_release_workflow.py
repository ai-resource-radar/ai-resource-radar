from pathlib import Path
import unittest


class ReleaseWorkflowTests(unittest.TestCase):
    def test_generated_poster_ignore_does_not_hide_source_package(self) -> None:
        root = Path(__file__).parents[1]
        ignore = (root / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("/posters/", ignore.splitlines())
        self.assertNotIn("posters/", ignore.splitlines())
        self.assertTrue((root / "src/ai_resource_radar/posters/service.py").is_file())

    def test_publish_waits_for_core_macos_and_secret_gates(self) -> None:
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("needs: [core, macos, secrets]", workflow)
        self.assertIn("needs: build", workflow)
        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("gitleaks/gitleaks-action", workflow)
        self.assertIn("macos_poster_ocr.swift", workflow)
        self.assertIn("src/ai_resource_radar/frontend_shared", workflow)
        for name in ("cards.js", "cards.css", "dom.js", "formatters.js", "radar-tokens.css"):
            self.assertIn(name, workflow)

    def test_release_checksums_use_downloaded_asset_basenames(self) -> None:
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("(cd dist && sha256sum *.whl *.tar.gz > SHA256SUMS)", workflow)
        self.assertGreaterEqual(workflow.count("sha256sum -c SHA256SUMS"), 2)
        self.assertIn("path: dist/SHA256SUMS", workflow)


if __name__ == "__main__":
    unittest.main()
