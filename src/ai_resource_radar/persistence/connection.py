"""SQLite connection lifecycle for the schema-v7 radar database."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable


SCHEMA_VERSION = 7


class UnsupportedSchemaError(sqlite3.DatabaseError):
    """Raised when a database is newer than this runtime understands."""

    def __init__(self, database_version: int, supported_version: int) -> None:
        super().__init__("ai_radar_schema_unsupported")
        self.database_version = int(database_version)
        self.supported_version = int(supported_version)


Initializer = Callable[[sqlite3.Connection], bool]
Vacuum = Callable[..., str]


def connect(
    path: Path,
    *,
    initialize: Initializer | None = None,
    vacuum: Vacuum | None = None,
) -> sqlite3.Connection:
    """Open a private SQLite database and run its transactional initializer.

    Imports are intentionally lazy so ``schema`` can import the schema version
    and exception from this module without creating an import cycle.
    """

    if initialize is None:
        from .schema import initialize as initialize
    if vacuum is None:
        from .maintenance import _try_vacuum as vacuum

    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(database, timeout=10)
    os.chmod(database, 0o600)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        migrated = initialize(connection)
    except Exception:
        connection.close()
        raise
    if migrated:
        vacuum(
            connection,
            at=datetime.now().astimezone(),
            force=True,
        )
    return connection


__all__ = ["SCHEMA_VERSION", "UnsupportedSchemaError", "connect"]
