"""Poster generation domain.

Focused provider, facts, validation, benchmark and reporting imports alias the
service module during the incremental migration.  Keeping a shared module
namespace preserves existing provider monkeypatches and metadata contracts.
"""

from .service import *  # noqa: F401,F403
