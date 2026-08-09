from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
import plistlib
import sqlite3
import socket
import subprocess
import sys
from typing import Any
from urllib.request import ProxyHandler, build_opener

from ai_resource_radar.native_helper import prepare_macos_helper
from ai_resource_radar.paths import default_database_path


DASHBOARD_LABEL = "com.xxy.ai-resource-radar.dashboard"
MENUBAR_LABEL = "com.xxy.ai-resource-radar.menubar"
DAILY_LABEL = "com.xxy.ai-resource-radar.daily"
COMPUTER_HEALTH_DAILY_LABEL = "com.xxy.computer-health-ai-radar"
BACKUP_RETENTION_DAYS = 7


@dataclass(frozen=True)
class ServiceResult:
    action: str
    dashboard: str
    menubar: str
    daily: str
    port: int
    hour: int
    minute: int


def _launch_agents() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist_path(label: str) -> Path:
    return _launch_agents() / f"{label}.plist"


def _logs() -> Path:
    path = Path.home() / "Library" / "Logs" / "AIResourceRadar"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _service_installed(label: str) -> bool:
    if _plist_path(label).exists():
        return True
    return Path("/bin/launchctl").is_file() and _launchctl(
        "print", f"{_domain()}/{label}"
    ).returncode == 0


def service_conflicts() -> tuple[dict[str, str], ...]:
    conflicts: list[dict[str, str]] = []
    if _service_installed(COMPUTER_HEALTH_DAILY_LABEL):
        conflicts.append(
            {
                "label": COMPUTER_HEALTH_DAILY_LABEL,
                "remediation": "computer-health ai-radar service uninstall",
            }
        )
    return tuple(conflicts)


def backup_database(
    database: Path,
    *,
    now: datetime | None = None,
) -> Path | None:
    """Create and verify an online SQLite backup before service replacement."""

    if not database.exists():
        return None
    current = (now or datetime.now().astimezone()).astimezone()
    backup_root = database.parent / "backups"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_root, 0o700)
    stamp = current.strftime("%Y%m%dT%H%M%S%f%z")
    destination = backup_root / f"{database.stem}-{stamp}{database.suffix}"
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    source_connection: sqlite3.Connection | None = None
    backup_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(
            f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=10
        )
        backup_connection = sqlite3.connect(temporary, timeout=10)
        source_connection.backup(backup_connection)
        result = backup_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).casefold() != "ok":
            raise sqlite3.DatabaseError("ai_radar_backup_integrity_failed")
        backup_connection.close()
        backup_connection = None
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except (OSError, sqlite3.Error) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("ai_radar_backup_failed") from exc
    finally:
        if backup_connection is not None:
            backup_connection.close()
        if source_connection is not None:
            source_connection.close()
    cutoff = current - timedelta(days=BACKUP_RETENTION_DAYS)
    for candidate in backup_root.glob(f"{database.stem}-*{database.suffix}"):
        if candidate == destination:
            continue
        try:
            modified = datetime.fromtimestamp(
                candidate.stat().st_mtime, tz=current.tzinfo
            )
            if modified < cutoff:
                candidate.unlink()
        except OSError:
            # Retention cleanup must not invalidate an already verified backup.
            continue
    return destination


# Compatibility alias for the v0.1 internal helper name used by tests/hosts.
_backup_database = backup_database


def _launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _write_plist(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".plist.tmp")
    with temporary.open("wb") as stream:
        plistlib.dump(payload, stream, sort_keys=True)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _bootstrap(path: Path, label: str, *, kickstart: bool = True) -> str:
    _launchctl("bootout", _domain(), str(path))
    result = _launchctl("bootstrap", _domain(), str(path))
    if result.returncode != 0:
        return "failed"
    if kickstart:
        _launchctl("kickstart", "-k", f"{_domain()}/{label}")
    return "running"


def _python_arguments(*arguments: str) -> list[str]:
    return [sys.executable, "-m", "ai_resource_radar.cli", *arguments]


def _dashboard_plist(port: int, database: Path) -> dict[str, Any]:
    logs = _logs()
    return {
        "Label": DASHBOARD_LABEL,
        "ProgramArguments": _python_arguments(
            "dashboard", "--port", str(port), "--database", str(database)
        ),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "dashboard.log"),
        "StandardErrorPath": str(logs / "dashboard-error.log"),
    }


def _menubar_plist(executable: Path) -> dict[str, Any]:
    logs = _logs()
    return {
        "Label": MENUBAR_LABEL,
        "ProgramArguments": [str(executable)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "StandardOutPath": str(logs / "menubar.log"),
        "StandardErrorPath": str(logs / "menubar-error.log"),
    }


def _daily_plist(
    database: Path,
    *,
    hour: int,
    minute: int,
) -> dict[str, Any]:
    logs = _logs()
    return {
        "Label": DAILY_LABEL,
        "ProgramArguments": _python_arguments(
            "daily", "--database", str(database)
        ),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(logs / "daily.log"),
        "StandardErrorPath": str(logs / "daily-error.log"),
    }


def _validate(port: int, hour: int, minute: int) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("invalid_dashboard_port")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("invalid_schedule_time")


def _responds(port: int) -> bool:
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/", timeout=1) as response:
            return response.status == 200 and b"AI" in response.read(4096)
    except OSError:
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def install(
    *,
    port: int = 18766,
    hour: int = 8,
    minute: int = 0,
    database: Path | None = None,
) -> ServiceResult:
    _validate(port, hour, minute)
    conflicts = service_conflicts()
    if conflicts:
        conflict = conflicts[0]
        raise RuntimeError(
            "ai_radar_service_conflict:"
            f"{conflict['label']}:run {conflict['remediation']}"
        )
    if _port_in_use(port) and not _responds(port):
        raise RuntimeError("dashboard_port_in_use")
    helper = prepare_macos_helper("macos_menubar.swift")
    if not helper.available or helper.executable is None:
        raise RuntimeError(helper.error or "menubar_helper_unavailable")
    db = database or default_database_path()
    _backup_database(db)
    dashboard_path = _plist_path(DASHBOARD_LABEL)
    menubar_path = _plist_path(MENUBAR_LABEL)
    daily_path = _plist_path(DAILY_LABEL)
    _write_plist(dashboard_path, _dashboard_plist(port, db))
    _write_plist(menubar_path, _menubar_plist(helper.executable))
    _write_plist(daily_path, _daily_plist(db, hour=hour, minute=minute))
    return ServiceResult(
        "install",
        _bootstrap(dashboard_path, DASHBOARD_LABEL),
        _bootstrap(menubar_path, MENUBAR_LABEL),
        _bootstrap(daily_path, DAILY_LABEL),
        port,
        hour,
        minute,
    )


def status(
    *,
    port: int = 18766,
    hour: int = 8,
    minute: int = 0,
) -> ServiceResult:
    _validate(port, hour, minute)
    values = {
        label: (
            "running"
            if _launchctl("print", f"{_domain()}/{label}").returncode == 0
            else "stopped"
        )
        for label in (DASHBOARD_LABEL, MENUBAR_LABEL, DAILY_LABEL)
    }
    if values[DASHBOARD_LABEL] == "running" and not _responds(port):
        values[DASHBOARD_LABEL] = "stopped"
    return ServiceResult(
        "status",
        values[DASHBOARD_LABEL],
        values[MENUBAR_LABEL],
        values[DAILY_LABEL],
        port,
        hour,
        minute,
    )


def uninstall(
    *,
    port: int = 18766,
    hour: int = 8,
    minute: int = 0,
) -> ServiceResult:
    _validate(port, hour, minute)
    for label in (DASHBOARD_LABEL, MENUBAR_LABEL, DAILY_LABEL):
        path = _plist_path(label)
        _launchctl("bootout", _domain(), str(path))
        path.unlink(missing_ok=True)
    return ServiceResult("uninstall", "stopped", "stopped", "stopped", port, hour, minute)
