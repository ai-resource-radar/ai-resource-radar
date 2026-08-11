"""Runtime feature gates shared by the local poster surfaces.

The v0.7.1 release keeps the poster UI and all image-generation side effects
paused.  Keeping the state in one small, dependency-free module prevents the
CLI, Dashboard, and provider layer from drifting on the response contract.
"""

from __future__ import annotations

from typing import Any


POSTER_FEATURE_VISIBLE = False
POSTER_GENERATION_AVAILABLE = False
POSTER_FEATURE_REASON = "poster_feature_paused"


def poster_feature_status() -> dict[str, Any]:
    """Return the stable public poster availability contract."""

    return {
        "feature_visible": POSTER_FEATURE_VISIBLE,
        "generation_available": POSTER_GENERATION_AVAILABLE,
        "reason": POSTER_FEATURE_REASON,
    }


def poster_generation_available() -> bool:
    """Read the generation gate dynamically for tests and host overrides."""

    return bool(POSTER_GENERATION_AVAILABLE)


def poster_feature_error_payload(*, schema_version: str = "1.0") -> dict[str, Any]:
    """Return the structured error used by paused mutating endpoints."""

    return {
        "schema_version": schema_version,
        "error": POSTER_FEATURE_REASON,
        **poster_feature_status(),
    }


class PosterFeaturePausedError(RuntimeError):
    """Raised when a poster action would create an external side effect."""

    error_code = POSTER_FEATURE_REASON

    def __init__(self) -> None:
        super().__init__(self.error_code)


def require_poster_generation() -> None:
    """Fail before provider, OCR, Keychain, or filesystem work is attempted."""

    if not POSTER_GENERATION_AVAILABLE:
        raise PosterFeaturePausedError()


__all__ = [
    "POSTER_FEATURE_VISIBLE",
    "POSTER_GENERATION_AVAILABLE",
    "POSTER_FEATURE_REASON",
    "PosterFeaturePausedError",
    "poster_feature_error_payload",
    "poster_feature_status",
    "poster_generation_available",
    "require_poster_generation",
]
