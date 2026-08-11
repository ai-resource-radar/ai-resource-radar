from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


GUARD = Path(__file__).parents[1] / ".github/scripts/pages_fallback_guard.py"
SPEC = importlib.util.spec_from_file_location("pages_fallback_guard", GUARD)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


NOW = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)


def manifest(refreshed_at: datetime, *, status: str = "healthy", stale: int = 0, never: int = 0) -> dict:
    return {
        "status": status,
        "radar_refreshed_at": refreshed_at.isoformat().replace("+00:00", "Z"),
        "source_health": {"total": 23, "stale": stale, "never": never},
    }


class PagesFallbackGuardTests(unittest.TestCase):
    def test_today_snapshot_within_four_hours_is_eligible(self) -> None:
        for status in ("healthy", "partial"):
            with self.subTest(status=status):
                self.assertTrue(
                    MODULE.evaluate(
                        manifest(NOW - timedelta(hours=4), status=status),
                        now=NOW,
                    )
                )

    def test_old_or_non_today_snapshot_runs_fallback(self) -> None:
        self.assertFalse(
            MODULE.evaluate(manifest(NOW - timedelta(hours=4, seconds=1)), now=NOW)
        )
        # 16:30 UTC is 00:30 in Shanghai; a three-hour-old UTC snapshot can
        # still be from yesterday in the publication timezone.
        near_midnight = datetime(2026, 8, 11, 16, 30, tzinfo=timezone.utc)
        yesterday = datetime(2026, 8, 11, 13, 30, tzinfo=timezone.utc)
        self.assertFalse(MODULE.evaluate(manifest(yesterday), now=near_midnight))

    def test_stale_or_never_sources_run_fallback(self) -> None:
        self.assertFalse(MODULE.evaluate(manifest(NOW - timedelta(hours=1), stale=1), now=NOW))
        self.assertFalse(MODULE.evaluate(manifest(NOW - timedelta(hours=1), never=1), now=NOW))

    def test_incomplete_source_set_runs_fallback(self) -> None:
        for total in (None, 22, 24, "23", True):
            with self.subTest(total=total):
                payload = manifest(NOW - timedelta(hours=1))
                if total is None:
                    payload["source_health"].pop("total")
                else:
                    payload["source_health"]["total"] = total
                self.assertFalse(MODULE.evaluate(payload, now=NOW))

    def test_abnormal_or_missing_manifest_fields_run_fallback(self) -> None:
        cases = (
            None,
            {},
            {"status": "failed"},
            {"status": "healthy", "radar_refreshed_at": NOW.isoformat()},
            {
                "status": "healthy",
                "radar_refreshed_at": NOW.isoformat(),
                "source_health": {"total": 23, "stale": 0},
            },
            {
                "status": "healthy",
                "radar_refreshed_at": "not-a-time",
                "source_health": {"stale": 0, "never": 0},
            },
            {
                "status": "healthy",
                "radar_refreshed_at": NOW.isoformat(),
                "source_health": {"stale": "0", "never": 0},
            },
            {
                "status": "healthy",
                "radar_refreshed_at": NOW.isoformat(),
                "source_health": {"stale": [], "never": 0},
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertFalse(MODULE.evaluate(payload, now=NOW))

    def test_future_snapshot_runs_fallback(self) -> None:
        self.assertFalse(MODULE.evaluate(manifest(NOW + timedelta(minutes=1)), now=NOW))

    def test_cli_reports_eligibility_and_rejection(self) -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            live_now = datetime.now(timezone.utc)
            path.write_text(json.dumps(manifest(live_now - timedelta(hours=1))), encoding="utf-8")
            eligible = subprocess.run(
                [sys.executable, str(GUARD), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(eligible.returncode, 0)
            self.assertEqual(eligible.stdout.strip(), "eligible")

            path.write_text("{not-json", encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(GUARD), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertEqual(rejected.stdout.strip(), "manifest_parse_failed")


if __name__ == "__main__":
    unittest.main()
