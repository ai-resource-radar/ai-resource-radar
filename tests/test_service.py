from __future__ import annotations

from pathlib import Path
import os
import sqlite3
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from ai_resource_radar.service import (
    DAILY_LABEL,
    DASHBOARD_LABEL,
    COMPUTER_HEALTH_DAILY_LABEL,
    _backup_database,
    _daily_plist,
    _dashboard_plist,
    install,
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

    def test_online_backup_is_verified_private_and_prunes_old_backups(self) -> None:
        now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "radar.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE sample(value TEXT)")
                connection.execute("INSERT INTO sample VALUES ('preserved')")
            backup_root = root / "backups"
            backup_root.mkdir()
            old = backup_root / "radar-20260101T000000.sqlite3"
            old.write_bytes(b"old")
            old_time = (now - timedelta(days=8)).timestamp()
            os.utime(old, (old_time, old_time))

            backup = _backup_database(database, now=now)

            self.assertIsNotNone(backup)
            assert backup is not None
            with sqlite3.connect(backup) as restored:
                value = restored.execute("SELECT value FROM sample").fetchone()[0]
            mode = backup.stat().st_mode & 0o777
            self.assertFalse(old.exists())

        self.assertEqual(value, "preserved")
        self.assertEqual(mode, 0o600)

    def test_invalid_database_aborts_backup(self) -> None:
        with TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            database.write_text("not sqlite", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "ai_radar_backup_failed"):
                _backup_database(database)
            backups = list((database.parent / "backups").glob("*"))
        self.assertEqual(backups, [])

    def test_install_rejects_computer_health_daily_service_with_remediation(self) -> None:
        conflict = (
            {
                "label": COMPUTER_HEALTH_DAILY_LABEL,
                "remediation": "computer-health ai-radar service uninstall",
            },
        )
        with patch("ai_resource_radar.service.service_conflicts", return_value=conflict), patch(
            "ai_resource_radar.service.prepare_macos_helper"
        ) as helper:
            with self.assertRaisesRegex(
                RuntimeError, "computer-health ai-radar service uninstall"
            ):
                install()
        helper.assert_not_called()

    def test_backup_failure_stops_install_before_plists_are_replaced(self) -> None:
        helper_status = Mock(available=True, executable=Path("/tmp/radar-helper"))
        with patch("ai_resource_radar.service.service_conflicts", return_value=()), patch(
            "ai_resource_radar.service._port_in_use", return_value=False
        ), patch(
            "ai_resource_radar.service.prepare_macos_helper",
            return_value=helper_status,
        ), patch(
            "ai_resource_radar.service._backup_database",
            side_effect=RuntimeError("ai_radar_backup_failed"),
        ), patch("ai_resource_radar.service._write_plist") as write_plist:
            with self.assertRaisesRegex(RuntimeError, "ai_radar_backup_failed"):
                install(database=Path("/tmp/existing-radar.sqlite3"))
        write_plist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
