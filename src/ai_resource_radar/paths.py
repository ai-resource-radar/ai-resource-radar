from __future__ import annotations

import os
from pathlib import Path
import sys


def support_root() -> Path:
    # Keep the established macOS path so upgrades do not fork the user's
    # existing database.  On Linux, follow XDG conventions; if an older
    # checkout already created the macOS-style path, continue using it.
    legacy = Path.home() / "Library" / "Application Support" / "AIResourceRadar"
    if sys.platform == "darwin" or legacy.exists():
        return legacy
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return root / "ai-resource-radar"


def default_database_path() -> Path:
    return support_root() / "radar.sqlite3"
