"""Decide whether the scheduled Pages fallback may safely be skipped.

The guard is intentionally independent of the radar package.  It only reads
the public manifest and can therefore be tested with deterministic timestamps
without a database, network request, or repository credentials.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


FALLBACK_MAX_AGE = timedelta(hours=4)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_PARSE_FAILED = object()


def _reject(code: str) -> str:
    return code


def reason(payload: Any, now: datetime | None = None) -> str | None:
    """Return a rejection code, or ``None`` when the fallback may skip.

    ``now`` is injectable for deterministic tests and defaults to the current
    UTC instant.  A naive injected time is interpreted as UTC; manifest
    timestamps themselves must include an explicit offset.
    """

    if not isinstance(payload, Mapping):
        return _reject("manifest_not_an_object")

    if payload.get("status") not in {"healthy", "partial"}:
        return _reject("manifest_status_abnormal")

    health = payload.get("source_health")
    if not isinstance(health, Mapping) or "stale" not in health or "never" not in health:
        return _reject("manifest_source_health_missing")
    total = health.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total != 23:
        return _reject("manifest_source_count_abnormal")
    for key in ("stale", "never"):
        value = health.get(key)
        if isinstance(value, bool):
            has_bad_sources = value
        elif isinstance(value, (int, float)) and value >= 0:
            has_bad_sources = value != 0
        else:
            return _reject("manifest_source_health_abnormal")
        if has_bad_sources:
            return _reject("manifest_source_health_stale")

    refreshed_raw = payload.get("radar_refreshed_at")
    if not isinstance(refreshed_raw, str) or not refreshed_raw:
        return _reject("manifest_refresh_time_missing")
    try:
        refreshed = datetime.fromisoformat(refreshed_raw.replace("Z", "+00:00"))
    except ValueError:
        return _reject("manifest_refresh_time_invalid")
    if refreshed.tzinfo is None:
        return _reject("manifest_refresh_time_invalid")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_utc = current.astimezone(timezone.utc)
    refreshed_utc = refreshed.astimezone(timezone.utc)
    age = current_utc - refreshed_utc
    if age < timedelta(0):
        return _reject("manifest_refresh_time_in_future")
    if age > FALLBACK_MAX_AGE:
        return _reject("manifest_refresh_too_old")
    if refreshed_utc.astimezone(SHANGHAI).date() != current_utc.astimezone(SHANGHAI).date():
        return _reject("manifest_refresh_not_today")
    return None


def evaluate(payload: Any, now: datetime | None = None) -> bool:
    """Return ``True`` only when the live snapshot satisfies every criterion."""

    return reason(payload, now=now) is None


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _PARSE_FAILED


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: pages_fallback_guard.py MANIFEST", file=sys.stderr)
        return 2
    payload = _load(Path(args[0]))
    if payload is _PARSE_FAILED:
        print("manifest_parse_failed")
        return 1
    code = reason(payload)
    if code is None:
        print("eligible")
        return 0
    print(code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
