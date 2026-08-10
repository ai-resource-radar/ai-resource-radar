"""Persistence domain for the schema-v7 radar database.

``core`` is the staged implementation module.  The focused modules are
compatibility aliases so callers can depend on connection, schema, repository
or maintenance responsibilities independently while all code continues to
share one SQLite module namespace and one schema implementation.
"""

from .core import *  # noqa: F401,F403
