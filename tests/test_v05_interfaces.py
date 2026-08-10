from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from ai_resource_radar.interfaces.assets import resolve_dashboard_asset
from ai_resource_radar.interfaces.cli import CliContext, run_cli
from ai_resource_radar.interfaces.http import (
    RadarDashboardPort,
    radar_post_body_limit,
    route_radar_get,
    route_radar_post,
)
from ai_resource_radar.dashboard_state import AiRadarDashboard


class InterfaceContractTests(unittest.TestCase):
    def test_http_router_has_a_runtime_checkable_dashboard_port(self) -> None:
        radar = MagicMock()
        radar.schema_error.return_value = None
        radar.summary.return_value = {"counts": {"active": 4}}

        response = route_radar_get(radar, "/api/ai-resources/summary", "")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["counts"]["active"], 4)
        with TemporaryDirectory() as temp:
            self.assertTrue(
                isinstance(
                    AiRadarDashboard(Path(temp) / "radar.sqlite3"),
                    RadarDashboardPort,
                )
            )

    def test_http_router_preserves_errors_and_post_limits(self) -> None:
        radar = MagicMock()
        radar.schema_error.return_value = None
        radar.start_refresh.return_value = None

        response = route_radar_post(
            radar, "/api/ai-resources/refresh", {"force": True}
        )

        self.assertEqual(response.status, 409)
        self.assertEqual(response.payload["error"], "ai_radar_refresh_already_running")
        self.assertEqual(radar_post_body_limit("/api/ai-tips/import"), 16384)
        self.assertIsNone(radar_post_body_limit("/api/ai-tips/unknown/deep/path"))

    def test_installed_asset_resolver_rejects_path_traversal(self) -> None:
        asset = resolve_dashboard_asset("/ai-resources.html")
        self.assertIsNotNone(asset)
        self.assertEqual(asset[0].name, "index.html")
        self.assertIsNone(
            resolve_dashboard_asset("/ai-radar-assets/../../pyproject.toml")
        )

    def test_cli_context_overrides_database_and_project_root(self) -> None:
        with TemporaryDirectory() as temp:
            database = Path(temp) / "host.sqlite3"
            project_root = Path(temp) / "project"
            project_root.mkdir()
            output = io.StringIO()
            with (
                patch("ai_resource_radar.cli.seed_initial_tips"),
                patch(
                    "ai_resource_radar.cli.approve_tip_batch",
                    return_value={"batch_id": "batch-v05"},
                ) as approve,
                redirect_stdout(output),
            ):
                exit_code = run_cli(
                    [
                        "tips",
                        "approve-batch",
                        "tip-a",
                        "tip-b",
                        "--scope",
                        "both",
                        "--adopt-existing",
                    ],
                    context=CliContext(
                        database=database,
                        project_root=project_root,
                    ),
                )

        self.assertEqual(exit_code, 0)
        approve.assert_called_once_with(
            database,
            ["tip-a", "tip-b"],
            scope="both",
            adopt_existing=True,
            project_root=project_root,
        )

    def test_cli_keeps_host_markdown_and_output_compatibility(self) -> None:
        records = (
            {
                "priority_tier": "A",
                "provider": "Example",
                "title": "Free API",
                "quota_value": 100.0,
                "quota_unit": "requests/day",
                "requires_card": "no",
            },
        )
        with TemporaryDirectory() as temp:
            output = Path(temp) / "offers.md"
            with patch("ai_resource_radar.cli.list_offers", return_value=records):
                exit_code = run_cli(
                    ["list", "--output", str(output)],
                    context=CliContext(
                        database=Path(temp) / "radar.sqlite3",
                        list_format="markdown",
                    ),
                )
            rendered = output.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("# AI 资源雷达", rendered)
        self.assertIn("Example / Free API", rendered)


if __name__ == "__main__":
    unittest.main()
