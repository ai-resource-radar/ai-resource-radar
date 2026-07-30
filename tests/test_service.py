from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_resource_radar.service import (
    DAILY_LABEL,
    DASHBOARD_LABEL,
    _daily_plist,
    _dashboard_plist,
)


class ServiceTests(unittest.TestCase):
    def test_daily_plist_chains_refresh_and_poster_at_calendar_time(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "radar.sqlite3"
            with patch("ai_resource_radar.service._logs", return_value=root):
                payload = _daily_plist(database, hour=8, minute=0)

        self.assertEqual(payload["Label"], DAILY_LABEL)
        self.assertEqual(payload["StartCalendarInterval"], {"Hour": 8, "Minute": 0})
        self.assertIn("daily", payload["ProgramArguments"])
        self.assertEqual(payload["ProgramArguments"][-1], str(database))
        self.assertNotIn("KeepAlive", payload)

    def test_dashboard_plist_is_loopback_service_command(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("ai_resource_radar.service._logs", return_value=root):
                payload = _dashboard_plist(18766, root / "radar.sqlite3")

        self.assertEqual(payload["Label"], DASHBOARD_LABEL)
        self.assertIn("dashboard", payload["ProgramArguments"])
        self.assertIn("18766", payload["ProgramArguments"])
        self.assertTrue(payload["KeepAlive"])


if __name__ == "__main__":
    unittest.main()
