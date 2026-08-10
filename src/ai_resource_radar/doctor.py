from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from importlib import metadata, resources
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
from typing import Any
from urllib.request import ProxyHandler, build_opener

from ai_resource_radar.locks import operation_lock_status
from ai_resource_radar.poster import _openclaw_provider_configured
from ai_resource_radar.service import (
    DAILY_LABEL,
    DASHBOARD_LABEL,
    MENUBAR_LABEL,
    _domain,
    _launchctl,
    _plist_path,
    service_conflicts,
)
from ai_resource_radar.store import SCHEMA_VERSION, source_statuses


DOCTOR_STATUSES = ("healthy", "degraded", "failed")
_EXIT_CODES = {"healthy": 0, "degraded": 1, "failed": 2}


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    status: str
    summary: str
    remediation: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DoctorReport:
    overall: str
    checks: tuple[DoctorCheck, ...]
    generated_at: str

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.overall]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "checks": [check.to_dict() for check in self.checks],
            "exit_code": self.exit_code,
            "generated_at": self.generated_at,
        }


def _check(
    identifier: str,
    status: str,
    summary: str,
    remediation: str | None = None,
    **details: Any,
) -> DoctorCheck:
    if status not in DOCTOR_STATUSES:
        raise ValueError("invalid_doctor_status")
    return DoctorCheck(identifier, status, summary, remediation, details)


def _overall(checks: list[DoctorCheck]) -> str:
    if any(check.status == "failed" for check in checks):
        return "failed"
    if any(check.status == "degraded" for check in checks):
        return "degraded"
    return "healthy"


def _package_version() -> str:
    try:
        from ai_resource_radar import __version__

        if __version__:
            return str(__version__)
    except (ImportError, AttributeError):
        pass
    try:
        return metadata.version("ai-resource-radar")
    except metadata.PackageNotFoundError:
        return "unknown"


def _poster_configuration(connection: sqlite3.Connection) -> tuple[bool, str, str]:
    try:
        rows = connection.execute(
            "SELECT key, value FROM radar_metadata WHERE key IN "
            "('poster.enabled', 'poster.provider', 'poster.model')"
        ).fetchall()
    except sqlite3.Error:
        return False, "openai", "gpt-image-2"
    values = {str(row[0]): str(row[1]) for row in rows}
    enabled = values.get("poster.enabled", "0").casefold() in {
        "1",
        "true",
        "yes",
        "enabled",
    }
    return (
        enabled,
        values.get("poster.provider", "openai").casefold(),
        values.get("poster.model", "gpt-image-2"),
    )


def _dashboard_check(port: int) -> DoctorCheck:
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(
            f"http://127.0.0.1:{port}/api/ai-resources/summary", timeout=1.5
        ) as response:
            body = json.loads(response.read(256 * 1024))
        if int(response.status) == 200 and isinstance(body, dict):
            return _check(
                "dashboard", "healthy", f"Dashboard responds on 127.0.0.1:{port}",
                port=port,
            )
        return _check(
            "dashboard",
            "degraded",
            f"Dashboard returned an unexpected response on port {port}",
            "Reinstall or restart the radar services.",
            port=port,
        )
    except Exception:
        return _check(
            "dashboard",
            "degraded",
            f"Dashboard is not responding on 127.0.0.1:{port}",
            "Run `ai-radar service install` or check the Dashboard log.",
            port=port,
        )


def _launch_agent_check(labels: tuple[str, ...]) -> DoctorCheck:
    if platform.system() != "Darwin":
        return _check(
            "launch_agents", "healthy", "LaunchAgents are not applicable on this platform",
            applicable=False,
        )
    states: dict[str, dict[str, Any]] = {}
    degraded = False
    for label in labels:
        result = _launchctl("print", f"{_domain()}/{label}")
        loaded = result.returncode == 0
        plist_exists = _plist_path(label).exists()
        exit_match = re.search(r"last exit code\s*=\s*(-?\d+)", result.stdout)
        last_exit = int(exit_match.group(1)) if exit_match else None
        states[label] = {
            "loaded": loaded,
            "plist_exists": plist_exists,
            "last_exit_code": last_exit,
        }
        if not loaded or not plist_exists or (last_exit not in {None, 0}):
            degraded = True
    return _check(
        "launch_agents",
        "degraded" if degraded else "healthy",
        "One or more LaunchAgents need attention"
        if degraded
        else "All radar LaunchAgents are loaded",
        "Run `ai-radar service install` and inspect LaunchAgent logs."
        if degraded
        else None,
        services=states,
    )


def _ocr_check(*, poster_enabled: bool) -> DoctorCheck:
    if not poster_enabled:
        return _check(
            "ocr", "healthy", "Poster generation is disabled; OCR is optional",
            enabled=False,
        )
    if platform.system() != "Darwin":
        return _check(
            "ocr",
            "degraded",
            "macOS Vision OCR is unavailable on this platform",
            "Run poster validation on macOS.",
            enabled=True,
        )
    try:
        source = resources.files("ai_resource_radar").joinpath(
            "native", "macos_poster_ocr.swift"
        )
        source_available = source.is_file()
    except (FileNotFoundError, OSError):
        source_available = False
    available = source_available and Path("/usr/bin/swiftc").is_file()
    return _check(
        "ocr",
        "healthy" if available else "degraded",
        "Vision OCR helper can be built"
        if available
        else "Vision OCR helper or Swift compiler is unavailable",
        "Reinstall the package on macOS with Xcode command-line tools."
        if not available
        else None,
        enabled=True,
    )


def _poster_provider_check(
    *, poster_enabled: bool, provider: str, model: str
) -> DoctorCheck:
    if not poster_enabled:
        return _check(
            "poster_provider",
            "healthy",
            "Poster generation is explicitly disabled",
            enabled=False,
            provider=provider,
            model=model,
        )
    if provider == "openclaw":
        candidates = (
            shutil.which("openclaw"),
            str(Path.home() / ".openclaw" / "bin" / "openclaw"),
            "/opt/homebrew/bin/openclaw",
            "/usr/local/bin/openclaw",
        )
        binary = next((item for item in candidates if item and Path(item).is_file()), None)
        if binary:
            configured, configuration_reason = _openclaw_provider_configured(
                model, binary=binary
            )
            if not configured:
                return _check(
                    "poster_provider",
                    "degraded",
                    f"OpenClaw model {model!r} is not configured",
                    "Configure the selected OpenClaw provider/model or disable poster generation.",
                    enabled=True,
                    provider=provider,
                    model=model,
                    binary=binary,
                    configuration_reason=configuration_reason,
                )
            return _check(
                "poster_provider",
                "healthy",
                f"OpenClaw model {model!r} is configured",
                enabled=True,
                provider=provider,
                model=model,
                binary=binary,
            )
        return _check(
            "poster_provider",
            "degraded",
            "OpenClaw is selected but its executable is unavailable",
            "Install OpenClaw or disable poster generation.",
            enabled=True,
            provider=provider,
            model=model,
        )
    if provider == "openai" and platform.system() == "Darwin":
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                "ai-resource-radar.openai",
                "-a",
                "default",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return _check(
                "poster_provider", "healthy", "OpenAI Keychain credential is configured",
                enabled=True, provider=provider, model=model,
            )
    return _check(
        "poster_provider",
        "degraded",
        f"Poster provider {provider!r} is not fully configured",
        "Configure the selected provider or disable poster generation.",
        enabled=True,
        provider=provider,
        model=model,
    )


def diagnose(
    database: Path,
    *,
    now: datetime | None = None,
    dashboard_port: int | None = 18766,
    launch_agent_labels: tuple[str, ...] | None = None,
    check_services: bool = True,
    check_conflicts: bool = True,
) -> DoctorReport:
    """Run deterministic diagnostics without migrating or creating the DB."""

    current = (now or datetime.now().astimezone()).astimezone()
    checks: list[DoctorCheck] = [
        _check(
            "package",
            "healthy",
            f"ai-resource-radar {_package_version()} supports schema {SCHEMA_VERSION}",
            version=_package_version(),
            supported_schema=SCHEMA_VERSION,
        )
    ]
    poster_enabled = False
    poster_provider = "openai"
    poster_model = "gpt-image-2"
    connection: sqlite3.Connection | None = None
    if not database.exists():
        checks.append(
            _check(
                "database",
                "degraded",
                "Radar database has not been initialized",
                "Run `ai-radar refresh` once.",
                path=str(database),
            )
        )
    else:
        try:
            connection = sqlite3.connect(
                f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=5
            )
            connection.row_factory = sqlite3.Row
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                checks.append(
                    _check(
                        "database_schema",
                        "failed",
                        f"Database schema {version} is newer than supported {SCHEMA_VERSION}",
                        "Upgrade ai-resource-radar before opening this database.",
                        database_schema=version,
                        supported_schema=SCHEMA_VERSION,
                    )
                )
            elif version < SCHEMA_VERSION:
                checks.append(
                    _check(
                        "database_schema",
                        "degraded",
                        f"Database schema {version} will migrate to {SCHEMA_VERSION}",
                        "Create a backup, then run `ai-radar refresh`.",
                        database_schema=version,
                        supported_schema=SCHEMA_VERSION,
                    )
                )
            else:
                checks.append(
                    _check(
                        "database_schema",
                        "healthy",
                        f"Database schema {version} is supported",
                        database_schema=version,
                        supported_schema=SCHEMA_VERSION,
                    )
                )
            integrity = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            checks.append(
                _check(
                    "database_integrity",
                    "healthy" if integrity.casefold() == "ok" else "failed",
                    "SQLite integrity check passed"
                    if integrity.casefold() == "ok"
                    else "SQLite integrity check failed",
                    "Restore the newest verified backup."
                    if integrity.casefold() != "ok"
                    else None,
                    result=integrity,
                )
            )
            mode = stat.S_IMODE(database.stat().st_mode)
            checks.append(
                _check(
                    "database_permissions",
                    "healthy" if mode == 0o600 else "degraded",
                    f"Database permissions are {mode:04o}",
                    f"Run `chmod 600 {database}`." if mode != 0o600 else None,
                    mode=f"{mode:04o}",
                )
            )
            if version == SCHEMA_VERSION:
                try:
                    statuses = source_statuses(connection, now=current)
                    counts = {
                        state: sum(item["status"] == state for item in statuses)
                        for state in (
                            "fresh", "overdue", "stale", "verification_pending",
                            "failed", "never",
                        )
                    }
                    degraded = any(
                        counts[state]
                        for state in (
                            "overdue", "stale", "verification_pending", "failed", "never"
                        )
                    )
                    checks.append(
                        _check(
                            "sources",
                            "degraded" if degraded else "healthy",
                            "Some sources are not fresh"
                            if degraded
                            else "All sources are fresh",
                            "Run `ai-radar refresh --force` and inspect failed sources."
                            if degraded
                            else None,
                            counts=counts,
                        )
                    )
                except sqlite3.Error:
                    checks.append(
                        _check(
                            "sources",
                            "failed",
                            "Source health tables cannot be read",
                            "Restore a valid database backup or rerun initialization.",
                        )
                    )
            elif version < SCHEMA_VERSION:
                checks.append(
                    _check(
                        "sources",
                        "degraded",
                        "Source freshness is available after the schema migration",
                        "Create a backup, then run `ai-radar refresh`.",
                        database_schema=version,
                        supported_schema=SCHEMA_VERSION,
                    )
                )
            poster_enabled, poster_provider, poster_model = _poster_configuration(
                connection
            )
        except (OSError, sqlite3.Error) as exc:
            checks.append(
                _check(
                    "database",
                    "failed",
                    "Radar database cannot be opened",
                    "Check the path, permissions, and restore from backup if needed.",
                    path=str(database),
                    error=type(exc).__name__,
                )
            )
        finally:
            if connection is not None:
                connection.close()

    for operation in ("refresh", "poster"):
        state = operation_lock_status(database, operation)
        locked = bool(state.get("locked"))
        probe_error = state.get("probe_error")
        if probe_error:
            lock_status = "degraded"
            lock_summary = f"Cannot inspect the {operation} operation lock"
            lock_remediation = "Check the database directory and lock-file permissions."
        elif locked:
            lock_status = "degraded"
            lock_summary = f"{operation.capitalize()} is currently running"
            lock_remediation = "Wait for the current process to finish and rerun Doctor."
        else:
            lock_status = "healthy"
            lock_summary = f"No active {operation} lock"
            lock_remediation = None
        checks.append(
            _check(
                f"{operation}_lock",
                lock_status,
                lock_summary,
                lock_remediation,
                **state,
            )
        )

    if check_services:
        if dashboard_port is not None:
            checks.append(_dashboard_check(dashboard_port))
        labels = launch_agent_labels or (DASHBOARD_LABEL, MENUBAR_LABEL, DAILY_LABEL)
        checks.append(_launch_agent_check(labels))
    if check_conflicts:
        conflicts = service_conflicts()
        checks.append(
            _check(
                "service_conflicts",
                "degraded" if conflicts else "healthy",
                "Another AI radar daily service is installed"
                if conflicts
                else "No conflicting AI radar service is installed",
                conflicts[0]["remediation"] if conflicts else None,
                conflicts=conflicts,
            )
        )
    checks.append(_ocr_check(poster_enabled=poster_enabled))
    checks.append(
        _poster_provider_check(
            poster_enabled=poster_enabled,
            provider=poster_provider,
            model=poster_model,
        )
    )
    return DoctorReport(
        overall=_overall(checks),
        checks=tuple(checks),
        generated_at=current.isoformat(timespec="seconds"),
    )


def run_doctor(database: Path, **options: Any) -> dict[str, Any]:
    """Stable dictionary facade used by CLI and host applications."""

    return diagnose(database, **options).to_dict()
