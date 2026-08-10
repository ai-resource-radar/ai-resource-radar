"""Backward-compatible facade for :mod:`ai_resource_radar.posters`."""

from __future__ import annotations

import sys as _sys

from .posters import service as _implementation

_sys.modules[__name__] = _implementation
