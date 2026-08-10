from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/pages.yml"


class PagesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_daily_and_has_manual_force_input(self) -> None:
        self.assertRegex(self.text, r'cron:\s*["\']20 0 \* \* \*["\']')
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("force:", self.text)
        self.assertIn("type: boolean", self.text)

    def test_refresh_is_keyless_and_cache_is_only_ci_sqlite(self) -> None:
        self.assertIn("uses: actions/cache@v4", self.text)
        self.assertIn("path: .ci-cache/radar.sqlite3", self.text)
        self.assertIn("github.run_id", self.text)
        self.assertNotIn("cache: pip", self.text)
        self.assertIn("ai-radar refresh", self.text)
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("OPENAI_API_KEY", self.text)
        self.assertNotIn("ANTHROPIC_API_KEY", self.text)

    def test_build_gate_precedes_pages_upload_and_deploy(self) -> None:
        self.assertIn("ai-radar site build", self.text)
        self.assertIn("--base-url https://ai-resource-radar.github.io/ai-resource-radar/", self.text)
        self.assertIn("data/manifest.json", self.text)
        self.assertIn('status not in {"healthy", "partial"}', self.text)
        self.assertIn("uses: actions/upload-pages-artifact@v3", self.text)
        self.assertIn("uses: actions/deploy-pages@v4", self.text)
        self.assertRegex(self.text, r"deploy:\s*\n\s*needs: build")
        self.assertIn("environment:", self.text)
        self.assertIn("name: github-pages", self.text)
        self.assertIn("pages: write", self.text)
        self.assertIn("id-token: write", self.text)

        gate = self.text.index("Verify public site and publication gate")
        upload = self.text.index("Upload Pages artifact")
        self.assertLess(gate, upload)


if __name__ == "__main__":
    unittest.main()
