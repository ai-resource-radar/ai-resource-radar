from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_resource_radar.native_helper import prepare_macos_helper


class NativeHelperTests(unittest.TestCase):
    def test_helper_uses_private_module_cache_and_reuses_binary(self) -> None:
        calls: list[list[str]] = []

        def compile_helper(command: list[str], **_: object) -> object:
            calls.append(command)
            Path(command[command.index("-o") + 1]).write_bytes(b"helper")
            return type("Completed", (), {"returncode": 0})()

        with TemporaryDirectory() as directory, patch(
            "ai_resource_radar.native_helper.platform.system", return_value="Darwin"
        ), patch(
            "ai_resource_radar.native_helper._source_bytes", return_value=b"source"
        ), patch(
            "ai_resource_radar.native_helper.subprocess.run",
            side_effect=compile_helper,
        ):
            root = Path(directory) / "helpers"
            first = prepare_macos_helper("macos_menubar.swift", root=root)
            second = prepare_macos_helper("macos_menubar.swift", root=root)
            cache = Path(calls[0][calls[0].index("-module-cache-path") + 1])
            cache_mode = cache.stat().st_mode & 0o777

        self.assertTrue(first.available)
        self.assertEqual(first.executable, second.executable)
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.name, "swift-module-cache")
        self.assertEqual(cache_mode, 0o700)


if __name__ == "__main__":
    unittest.main()
