"""Backward-compatible facade for the application refresh orchestrator."""

from __future__ import annotations

import sys as _sys
from importlib import import_module as _import_module

_implementation = _import_module(".application.refresh", __package__)

_sys.modules[__name__] = _implementation
