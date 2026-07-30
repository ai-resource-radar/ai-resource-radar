from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any, Iterator


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
    name: str = "macos_sampler.swift",
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
        source_path.write_bytes(source)
        os.chmod(source_path, 0o600)
        command = ["/usr/bin/swiftc", "-O", str(source_path), "-o", str(temporary)]
        if name == "macos_sampler.swift":
            command.extend(["-framework", "CoreWLAN"])
        elif name == "macos_menubar.swift":
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


def start_macos_sampler(
    *,
    duration_seconds: int,
    resource_interval_seconds: int,
    wifi_interval_seconds: int,
    process_name: str,
    interface: str | None,
) -> tuple[subprocess.Popen[str] | None, str | None]:
    status = prepare_macos_helper()
    if not status.available or status.executable is None:
        return None, status.error
    try:
        process = subprocess.Popen(
            [
                str(status.executable),
                "--duration",
                str(duration_seconds),
                "--resource-interval",
                str(resource_interval_seconds),
                "--wifi-interval",
                str(wifi_interval_seconds),
                "--process",
                process_name,
                "--interface",
                interface or "",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return process, None
    except OSError:
        return None, "helper_start_failed"


def iter_helper_payloads(process: subprocess.Popen[str]) -> Iterator[dict[str, Any]]:
    if process.stdout is None:
        return
    for line in process.stdout:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") in {
            "system",
            "rate",
            "wifi",
        }:
            yield payload
