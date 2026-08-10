"""Backward-compatible facade for :mod:`ai_resource_radar.persistence`."""

from __future__ import annotations

import sys as _sys

from .persistence import core as _implementation

_sys.modules[__name__] = _implementation
