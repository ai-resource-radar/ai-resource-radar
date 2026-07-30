from __future__ import annotations

from pathlib import Path


def support_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "AIResourceRadar"


def default_database_path() -> Path:
    return support_root() / "radar.sqlite3"
