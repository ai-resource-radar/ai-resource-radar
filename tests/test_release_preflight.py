import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_preflight", ROOT / ".github/scripts/release_preflight.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReleasePreflightTests(unittest.TestCase):
    def test_versions_match_current_public_facade(self) -> None:
        version = MODULE.package_version(ROOT)
        self.assertRegex(version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(version, MODULE.facade_version(ROOT))

    def test_online_checks_are_opt_in_and_do_not_mutate(self) -> None:
        with mock.patch.object(MODULE, "online_checks") as online, mock.patch.object(
            MODULE, "local_checks", return_value=("v9.9.9", [MODULE.Check("local", "pass", "ok")])
        ):
            self.assertEqual(0, MODULE.main(["--repository", str(ROOT), "--json"]))
        online.assert_not_called()

    def test_failed_check_returns_nonzero(self) -> None:
        failed = MODULE.Check("remote_tag", "fail", "tag exists", "bump version")
        with mock.patch.object(MODULE, "local_checks", return_value=("v1.2.3", [failed])):
            self.assertEqual(1, MODULE.main(["--repository", str(ROOT), "--json"]))

    def test_full_checks_stop_after_first_failure(self) -> None:
        failed = mock.Mock(returncode=1, stdout="", stderr="test failure")
        with mock.patch.object(MODULE, "_run", return_value=failed) as run:
            checks = MODULE.run_full_checks(ROOT)
        self.assertEqual("fail", checks[0].status)
        self.assertEqual(1, run.call_count)
        pythonpath = run.call_args.kwargs["env"]["PYTHONPATH"]
        self.assertEqual(str(ROOT / "src"), pythonpath.split(MODULE.os.pathsep)[0])

    def test_pypi_network_failure_is_a_bounded_check(self) -> None:
        with mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"), mock.patch.object(
            MODULE, "_run", return_value=mock.Mock(returncode=0, stdout="larrynode\n", stderr="")
        ), mock.patch.object(
            MODULE,
            "_git",
            side_effect=["a" * 40, f"{'a' * 40}\trefs/heads/main", ""],
        ), mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=MODULE.urllib.error.URLError("temporary timeout"),
        ):
            checks = MODULE.online_checks(ROOT, "v9.9.9")

        self.assertEqual("fail", checks[-1].status)
        self.assertEqual("pypi_version", checks[-1].id)
        self.assertIn("could not be verified", checks[-1].summary)


if __name__ == "__main__":
    unittest.main()
