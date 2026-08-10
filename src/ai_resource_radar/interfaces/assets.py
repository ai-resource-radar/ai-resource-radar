"""Safe access to the installed Dashboard assets."""

from __future__ import annotations

import mimetypes
from pathlib import Path


_ASSET_ROOT = Path(__file__).resolve().parents[1] / "web"
_SHARED_ASSET_ROOT = Path(__file__).resolve().parents[1] / "frontend_shared"
_LEGACY = {
    "/": "index.html",
    "/index.html": "index.html",
    "/ai-resources.html": "index.html",
    "/ai-resources.css": "ai-resources.css",
    "/ai-resources.js": "ai-resources.js",
    "/favicon.svg": "favicon.svg",
    "/radar-tokens.css": "radar-tokens.css",
    "/ui-modules.js": "ui-modules.js",
}


def resolve_dashboard_asset(path: str) -> tuple[Path, str] | None:
    root = _ASSET_ROOT
    relative = _LEGACY.get(path)
    if relative is None and path.startswith("/ai-radar-assets/"):
        relative = path.removeprefix("/ai-radar-assets/")
    if relative is None and path.startswith("/ai-radar-shared/"):
        root = _SHARED_ASSET_ROOT
        relative = path.removeprefix("/ai-radar-shared/")
    if relative is None:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in {
        "application/javascript",
        "image/svg+xml",
    }:
        content_type += "; charset=utf-8"
    return candidate, content_type


__all__ = ["resolve_dashboard_asset"]
