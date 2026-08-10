"""Backward-compatible facade for the collection package.

The implementation lives in :mod:`ai_resource_radar.collection.parsers`.
This module intentionally aliases the implementation module instead of using a
``from ... import *`` re-export.  The alias keeps legacy monkeypatches and
module-level registries (notably ``PARSERS`` and ``SOURCE_BY_ID``) identical to
the objects used by the refresh runtime.
"""

from __future__ import annotations

import sys as _sys

from .collection import parsers as _implementation

_sys.modules[__name__] = _implementation
