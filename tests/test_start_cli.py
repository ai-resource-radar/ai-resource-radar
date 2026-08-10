from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from ai_resource_radar.cli import main


class StartCliTests(unittest.TestCase):
    def test_existing_snapshot_starts_without_refresh(self) -> None:
        with TemporaryDirectory() as temp, patch("ai_resource_radar.cli.radar_summary", return_value={"counts": {"active": 4}}), patch("ai_resource_radar.cli.refresh") as refresh, patch("ai_resource_radar.cli.serve", return_value=0) as serve:
            code = main(["start", "--database", str(Path(temp) / "radar.sqlite3"), "--port", "18766"])
        self.assertEqual(code, 0)
        refresh.assert_not_called()
        serve.assert_called_once()

    def test_first_run_refreshes_once_then_serves(self) -> None:
        report = Mock(); report.to_dict.return_value = {"summary": {"failed": 1}}
        with TemporaryDirectory() as temp, patch("ai_resource_radar.cli.radar_summary", side_effect=[{"counts": {"active": 0}}, {"counts": {"active": 2}}]), patch("ai_resource_radar.cli.refresh", return_value=report) as refresh, patch("ai_resource_radar.cli.serve", return_value=0):
            code = main(["start", "--database", str(Path(temp) / "radar.sqlite3"), "--timeout", "10"])
        self.assertEqual(code, 0)
        refresh.assert_called_once()

    def test_invalid_start_port_is_rejected_before_io(self) -> None:
        with patch("ai_resource_radar.cli.radar_summary") as summary:
            code = main(["start", "--port", "80"])
        self.assertEqual(code, 2)
        summary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
