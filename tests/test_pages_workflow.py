from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/pages.yml"


class PagesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_daily_and_has_manual_force_input(self) -> None:
        self.assertIn("push:", self.text)
        self.assertRegex(self.text, r"branches:\s*\n\s*- main")
        self.assertRegex(self.text, r'cron:\s*["\']37 0 \* \* \*["\']')
        self.assertRegex(self.text, r'cron:\s*["\']17 3 \* \* \*["\']')
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("force:", self.text)
        self.assertIn("type: boolean", self.text)
        self.assertRegex(self.text, r"force:\s*\n(?:\s+.*\n)*?\s+default: true")
        self.assertIn("github.event_name != 'workflow_dispatch' || inputs.force", self.text)

    def test_fallback_checks_live_manifest_before_skipping(self) -> None:
        self.assertIn("fallback_check:", self.text)
        self.assertIn("outputs:", self.text)
        self.assertIn("skip: ${{ steps.check.outputs.skip }}", self.text)
        self.assertIn("reason: ${{ steps.check.outputs.reason }}", self.text)
        self.assertIn("EVENT_SCHEDULE: ${{ github.event.schedule }}", self.text)
        self.assertIn("FALLBACK_CRON: \"17 3 * * *\"", self.text)
        self.assertIn(
            "https://ai-resource-radar.github.io/ai-resource-radar/data/manifest.json",
            self.text,
        )
        self.assertIn("curl --fail --silent --show-error --location --max-time 30", self.text)
        self.assertIn("python3 .github/scripts/pages_fallback_guard.py live-manifest.json", self.text)
        self.assertIn("manifest_parse_failed", self.text)
        self.assertIn("manifest_fetch_failed", self.text)
        self.assertIn("exit 0", self.text)

        self.assertIn("needs: fallback_check", self.text)
        self.assertIn(
            "if: needs.fallback_check.result == 'success' && needs.fallback_check.outputs.skip != 'true'",
            self.text,
        )
        self.assertIn("needs.build.result == 'success'", self.text)

    def test_refresh_is_keyless_and_cache_is_only_ci_sqlite(self) -> None:
        self.assertIn("uses: actions/cache@v4", self.text)
        self.assertIn("path: .ci-cache/radar.sqlite3", self.text)
        self.assertIn("github.run_id", self.text)
        self.assertNotIn("cache: pip", self.text)
        self.assertIn("ai-radar refresh", self.text)
        self.assertIn('refresh_args+=(--force)', self.text)
        self.assertIn('payload["refresh_mode"]', self.text)
        self.assertIn('RADAR_FORCE', self.text)
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("OPENAI_API_KEY", self.text)
        self.assertNotIn("ANTHROPIC_API_KEY", self.text)

    def test_build_gate_precedes_pages_upload_and_deploy(self) -> None:
        self.assertIn("ai-radar site build", self.text)
        self.assertIn("--base-url https://ai-resource-radar.github.io/ai-resource-radar/", self.text)
        self.assertIn('--source-revision "${GITHUB_SHA}"', self.text)
        self.assertIn("--refresh-report refresh-report.json", self.text)
        self.assertIn("data/manifest.json", self.text)
        self.assertIn('status not in {"healthy", "partial"}', self.text)
        self.assertIn("uses: actions/upload-pages-artifact@v3", self.text)
        self.assertIn("uses: actions/deploy-pages@v4", self.text)
        self.assertRegex(
            self.text,
            r"deploy:\s*\n\s*needs:\s*\n\s*- fallback_check\s*\n\s*- build",
        )
        self.assertIn("environment:", self.text)
        self.assertIn("name: github-pages", self.text)
        self.assertIn("pages: write", self.text)
        self.assertIn("id-token: write", self.text)
        self.assertIn("pages_gate_revision_mismatch", self.text)
        self.assertIn("pages_gate_data_too_old", self.text)
        self.assertIn("pages_gate_missing_refresh_report", self.text)
        self.assertIn("pages_gate_source_attempts", self.text)
        self.assertIn("len(report_sources) != 23", self.text)
        self.assertIn("health.get(\"total\") != 23", self.text)
        self.assertIn('health.get("stale") or health.get("never")', self.text)

        gate = self.text.index("Verify public site and publication gate")
        upload = self.text.index("Upload Pages artifact")
        self.assertLess(gate, upload)


if __name__ == "__main__":
    unittest.main()
