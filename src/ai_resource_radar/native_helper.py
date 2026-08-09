from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import os
from pathlib import Path
import platform
import subprocess


@dataclass(frozen=True)
class NativeHelperStatus:
    available: bool
    executable: Path | None
    error: str | None = None


def helper_root() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "AIResourceRadar"
        / "helpers"
    )


def _source_bytes(name: str) -> bytes:
    resource = files("ai_resource_radar").joinpath("native", name)
    return resource.read_bytes()


def prepare_macos_helper(
    name: str,
    *,
    root: Path | None = None,
) -> NativeHelperStatus:
    if platform.system() != "Darwin":
        return NativeHelperStatus(False, None, "unsupported_platform")
    try:
        source = _source_bytes(name)
    except (FileNotFoundError, OSError):
        return NativeHelperStatus(False, None, "helper_source_unavailable")
    digest = hashlib.sha256(source).hexdigest()[:16]
    target_root = root or helper_root()
    target = target_root / digest / name.removesuffix(".swift")
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target_root, 0o700)
        os.chmod(target.parent, 0o700)
        if target.is_file() and os.access(target, os.X_OK):
            return NativeHelperStatus(True, target)
        source_path = target.parent / name
        temporary = target.with_suffix(".tmp")
        module_cache = target.parent / "swift-module-cache"
        module_cache.mkdir(mode=0o700, exist_ok=True)
        os.chmod(module_cache, 0o700)
        source_path.write_bytes(source)
        os.chmod(source_path, 0o600)
        command = [
            "/usr/bin/swiftc",
            "-module-cache-path",
            str(module_cache),
            "-O",
            str(source_path),
            "-o",
            str(temporary),
        ]
        if name == "macos_menubar.swift":
            command.extend(["-framework", "AppKit"])
        elif name == "macos_poster_ocr.swift":
            command.extend(
                [
                    "-framework",
                    "Vision",
                    "-framework",
                    "ImageIO",
                    "-framework",
                    "CoreGraphics",
                ]
            )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            temporary.unlink(missing_ok=True)
            return NativeHelperStatus(False, None, "helper_compile_failed")
        os.chmod(temporary, 0o700)
        os.replace(temporary, target)
        return NativeHelperStatus(True, target)
    except subprocess.TimeoutExpired:
        return NativeHelperStatus(False, None, "helper_compile_timeout")
    except OSError:
        return NativeHelperStatus(False, None, "helper_compile_failed")
