"""Backward-compatible facade for :mod:`ai_resource_radar.tip_management`."""

from __future__ import annotations

import sys as _sys

from .tip_management import application as _implementation

_sys.modules[__name__] = _implementation
