"""Stable CLI dispatcher used by both standalone and embedding hosts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CliContext:
    """Embedding defaults and host hooks for the stable Radar dispatcher."""

    database: Path | None = None
    dashboard_port: int = 18766
    poster_root: Path | None = None
    project_root: Path | None = None
    doctor: Callable[[Path], object] | None = None
    list_format: str = "json"


def run_cli(argv: list[str] | None = None, *, context: CliContext | None = None) -> int:
    from ai_resource_radar.cli import main

    return main(argv, context=context)


__all__ = ["CliContext", "run_cli"]
