"""Application-level refresh orchestration.

``refresh`` deliberately remains the submodule attribute rather than being
shadowed by the function of the same name.  This keeps normal dotted imports
(``import ai_resource_radar.application.refresh``) stable while
``run_refresh`` offers an ergonomic package-level function alias.
"""

from . import refresh as refresh
from .refresh import FetchPayload, Fetcher, RefreshReport, RefreshSourceResult, fetch_source

run_refresh = refresh.refresh

__all__ = [
    "refresh",
    "run_refresh",
    "FetchPayload",
    "Fetcher",
    "RefreshReport",
    "RefreshSourceResult",
    "fetch_source",
]
