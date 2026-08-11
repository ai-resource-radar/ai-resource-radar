"""Host-neutral HTTP routing for the local Radar API.

The standalone server and embedding applications share this module so that
validation, payloads, status codes, and error identifiers cannot drift.
Transport security and byte streaming remain the responsibility of the host.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib.parse import parse_qs

from ai_resource_radar import feature_flags as _feature_flags
from ai_resource_radar.feature_flags import poster_feature_error_payload


Query = Mapping[str, list[str]]


@dataclass(frozen=True)
class ApiResponse:
    status: int
    payload: object | None = None
    file_path: Path | None = None
    content_type: str | None = None
    disposition: str | None = None

    @classmethod
    def json(cls, status: int, payload: object) -> "ApiResponse":
        return cls(status=status, payload=payload)

    @classmethod
    def file(cls, path: Path) -> "ApiResponse":
        return cls(
            status=200,
            file_path=path,
            content_type="image/webp",
            disposition=f'inline; filename="{path.name}"',
        )


@runtime_checkable
class RadarDashboardPort(Protocol):
    """Public method boundary consumed by the HTTP router."""

    def schema_error(self) -> dict[str, Any] | None: ...
    def summary(self) -> dict[str, Any]: ...
    def offers(self, **filters: Any) -> tuple[dict[str, Any], ...]: ...
    def provider_profiles(self) -> dict[str, Any]: ...
    def changes(self, *, days: int, limit: int) -> tuple[dict[str, Any], ...]: ...
    def tips_summary(self) -> dict[str, Any]: ...
    def tips(self, **filters: Any) -> tuple[dict[str, Any], ...]: ...
    def tip(self, tip_id: str) -> dict[str, Any] | None: ...
    def import_tip(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def review_tip(self, tip_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def tip_applications(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]: ...
    def rollback_tip(self, application_id: int) -> dict[str, Any]: ...
    def refresh_tips(self, *, force: bool = False) -> dict[str, Any]: ...
    def token_prices(self, **filters: Any) -> dict[str, Any]: ...
    def gpu_prices(self, **filters: Any) -> dict[str, Any]: ...
    def poster_latest(self) -> dict[str, Any] | None: ...
    def poster_reports(self, *, days: int = 90) -> tuple[dict[str, Any], ...]: ...
    def poster_image(self, report_date: str) -> Path | None: ...
    def poster_status(self) -> dict[str, Any]: ...
    def start_poster_benchmark(self, *, cases: int = 3) -> dict[str, Any] | None: ...
    def review_poster_benchmark(self, *, approve: bool, notes: str = "") -> dict[str, Any]: ...
    def start_poster(self, *, force: bool = False) -> dict[str, Any] | None: ...
    def refresh_status(self) -> dict[str, Any]: ...
    def start_refresh(self, *, force: bool = True) -> dict[str, Any] | None: ...
    def pending_notifications(self, *, limit: int = 5) -> tuple[dict[str, Any], ...]: ...
    def mark_notification(self, notification_id: int, *, status: str) -> bool: ...


_API_PREFIXES = (
    "/api/ai-resources",
    "/api/ai-prices",
    "/api/ai-daily",
    "/api/ai-tips",
)


def is_radar_api_path(path: str) -> bool:
    return path.startswith(_API_PREFIXES)


def radar_post_body_limit(path: str) -> int | None:
    """Return the accepted body limit, or ``None`` for an unknown endpoint."""
    if path in {
        "/api/ai-resources/refresh",
        "/api/ai-daily/generate",
        "/api/ai-daily/benchmark",
        "/api/ai-daily/benchmark/review",
        "/api/ai-tips/import",
        "/api/ai-tips/refresh",
    }:
        return 16384 if path.startswith("/api/ai-tips") else 4096
    parts = path.strip("/").split("/")
    if (
        len(parts) == 5
        and parts[:3] == ["api", "ai-resources", "notifications"]
        and parts[4] in {"delivered", "read"}
    ):
        return 4096
    if (
        len(parts) == 4
        and parts[:2] == ["api", "ai-tips"]
        and parts[3] == "review"
    ) or (
        len(parts) == 5
        and parts[:3] == ["api", "ai-tips", "applications"]
        and parts[4] == "rollback"
    ):
        return 16384
    return None


def route_radar_get(
    radar: RadarDashboardPort,
    path: str,
    query: Query | str | None = None,
) -> ApiResponse | None:
    if not is_radar_api_path(path):
        return None
    schema_error = radar.schema_error()
    if schema_error is not None:
        return ApiResponse.json(503, schema_error)
    values = parse_qs(query or "") if isinstance(query, str) else (query or {})

    if path == "/api/ai-resources/summary":
        return ApiResponse.json(200, radar.summary())
    if path == "/api/ai-resources/providers":
        return ApiResponse.json(200, radar.provider_profiles())
    if path == "/api/ai-tips/summary":
        return ApiResponse.json(200, radar.tips_summary())
    if path == "/api/ai-tips":
        try:
            tips = radar.tips(
                status=_text(values, "status") or None,
                category=_text(values, "category") or None,
                risk=_text(values, "risk") or None,
                source=_text(values, "source") or None,
                scope=_text(values, "scope") or None,
                query=_text(values, "q") or None,
                limit=_int(values, "limit", 100),
                offset=_int(values, "offset", 0),
            )
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_ai_tip_filter"})
        return ApiResponse.json(
            200, {"schema_version": "1.0", "count": len(tips), "tips": tips}
        )
    if path == "/api/ai-tips/applications":
        try:
            applications = radar.tip_applications(limit=_int(values, "limit", 100))
        except (TypeError, ValueError):
            return ApiResponse.json(
                400, {"error": "invalid_ai_tip_application_filter"}
            )
        return ApiResponse.json(
            200, {"schema_version": "1.0", "applications": applications}
        )
    tip_parts = path.strip("/").split("/")
    if len(tip_parts) == 3 and tip_parts[:2] == ["api", "ai-tips"]:
        tip = radar.tip(tip_parts[2])
        if tip is None:
            return ApiResponse.json(404, {"error": "tip_not_found"})
        return ApiResponse.json(200, tip)
    if path == "/api/ai-resources":
        mainland_value = _text(values, "mainland")
        mainland = (
            tuple(item for item in mainland_value.split(",") if item)
            if mainland_value
            else None
        )
        try:
            resources = radar.offers(
                kind=_text(values, "kind") or None,
                verified_only=_text(values, "verified", "false") == "true",
                no_card=_text(values, "no_card", "false") == "true",
                free_image_generation=(
                    _text(values, "free_image_generation", "false") == "true"
                ),
                mainland=mainland,
                query=_text(values, "q") or None,
                limit=_int(values, "limit", 100),
                offset=_int(values, "offset", 0),
            )
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_ai_resource_filter"})
        return ApiResponse.json(
            200,
            {"schema_version": "2.0", "count": len(resources), "resources": resources},
        )
    if path == "/api/ai-resources/changes":
        try:
            changes = radar.changes(
                days=_int(values, "days", 30), limit=_int(values, "limit", 100)
            )
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_ai_change_filter"})
        return ApiResponse.json(
            200,
            {"schema_version": "2.0", "count": len(changes), "changes": changes},
        )
    if path == "/api/ai-prices/token":
        try:
            payload = radar.token_prices(
                query=_text(values, "q") or None,
                provider=_text(values, "provider") or None,
                sort=_text(values, "sort", "typical"),
                direction=_text(values, "direction", "asc"),
                min_context=_optional_int(values, "min_context"),
                max_input=_optional_float(values, "max_input"),
                max_output=_optional_float(values, "max_output"),
                max_typical=_optional_float(values, "max_typical"),
                verification=_text(values, "verification", "all"),
                cache=_text(values, "cache", "any"),
                limit=_int(values, "limit", 100),
                offset=_int(values, "offset", 0),
            )
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_token_price_filter"})
        return ApiResponse.json(200, payload)
    if path == "/api/ai-prices/gpu":
        try:
            payload = radar.gpu_prices(
                query=_text(values, "q") or None,
                provider=_text(values, "provider") or None,
                gpu_model=_text(values, "gpu") or None,
                sort=_text(values, "sort", "hourly"),
                direction=_text(values, "direction", "asc"),
                min_vram=_optional_float(values, "min_vram"),
                max_hourly=_optional_float(values, "max_hourly"),
                billing_mode=_text(values, "billing") or None,
                market_tier=_text(values, "tier") or None,
                price_mode=_text(values, "price_mode", "all"),
                hours=_float(values, "hours", 10.0),
                limit=_int(values, "limit", 100),
                offset=_int(values, "offset", 0),
            )
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_gpu_price_filter"})
        return ApiResponse.json(200, payload)
    if path == "/api/ai-resources/refresh":
        return ApiResponse.json(200, radar.refresh_status())
    if path == "/api/ai-resources/notifications/pending":
        return ApiResponse.json(
            200, {"notifications": radar.pending_notifications(limit=5)}
        )
    if path == "/api/ai-daily/latest":
        return ApiResponse.json(
            200, {"schema_version": "1.0", "report": radar.poster_latest()}
        )
    if path == "/api/ai-daily":
        try:
            reports = radar.poster_reports(days=_int(values, "days", 90))
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_daily_report_filter"})
        return ApiResponse.json(
            200,
            {"schema_version": "1.0", "count": len(reports), "reports": reports},
        )
    if path == "/api/ai-daily/status":
        return ApiResponse.json(200, radar.poster_status())
    if path == "/api/ai-daily/benchmark":
        status = radar.poster_status()
        return ApiResponse.json(
            200,
            {
                "schema_version": "1.0",
                "benchmark": status.get("benchmark"),
                "task": status.get("benchmark_task"),
            },
        )
    parts = path.strip("/").split("/")
    if len(parts) == 4 and parts[:2] == ["api", "ai-daily"] and parts[3] == "image":
        image = radar.poster_image(parts[2])
        if image is None:
            return ApiResponse.json(404, {"error": "daily_poster_not_found"})
        return ApiResponse.file(image)
    return ApiResponse.json(404, {"error": "not_found"})


def route_radar_post(
    radar: RadarDashboardPort, path: str, payload: object
) -> ApiResponse | None:
    if not is_radar_api_path(path):
        return None
    schema_error = radar.schema_error()
    if schema_error is not None:
        return ApiResponse.json(503, schema_error)
    if radar_post_body_limit(path) is None:
        return ApiResponse.json(404, {"error": "not_found"})

    if path == "/api/ai-resources/refresh":
        force = payload.get("force", True) if isinstance(payload, dict) else True
        if not isinstance(force, bool):
            return ApiResponse.json(400, {"error": "invalid_ai_refresh_request"})
        state = radar.start_refresh(force=force)
        if state is None:
            return ApiResponse.json(409, {"error": "ai_radar_refresh_already_running"})
        return ApiResponse.json(202, state)
    if path == "/api/ai-daily/generate":
        if not _feature_flags.POSTER_GENERATION_AVAILABLE:
            return ApiResponse.json(409, poster_feature_error_payload())
        force = payload.get("force", False) if isinstance(payload, dict) else False
        if not isinstance(force, bool):
            return ApiResponse.json(400, {"error": "invalid_daily_generate_request"})
        state = radar.start_poster(force=force)
        if state is None:
            return ApiResponse.json(409, {"error": "daily_poster_already_running"})
        return ApiResponse.json(202, state)
    if path == "/api/ai-daily/benchmark":
        if not _feature_flags.POSTER_GENERATION_AVAILABLE:
            return ApiResponse.json(409, poster_feature_error_payload())
        cases = payload.get("cases", 3) if isinstance(payload, dict) else 3
        if isinstance(cases, bool) or not isinstance(cases, int) or not 1 <= cases <= 3:
            return ApiResponse.json(400, {"error": "invalid_poster_benchmark_request"})
        state = radar.start_poster_benchmark(cases=cases)
        if state is None:
            return ApiResponse.json(409, {"error": "poster_benchmark_already_running"})
        return ApiResponse.json(202, state)
    if path == "/api/ai-daily/benchmark/review":
        if not _feature_flags.POSTER_GENERATION_AVAILABLE:
            return ApiResponse.json(409, poster_feature_error_payload())
        if not isinstance(payload, dict) or not isinstance(payload.get("approve"), bool):
            return ApiResponse.json(400, {"error": "invalid_poster_benchmark_review"})
        notes = payload.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 1000:
            return ApiResponse.json(400, {"error": "invalid_poster_benchmark_review"})
        try:
            result = radar.review_poster_benchmark(
                approve=payload["approve"], notes=notes
            )
        except ValueError as exc:
            return ApiResponse.json(400, {"error": str(exc)})
        return ApiResponse.json(200, result)
    if path == "/api/ai-tips/import":
        if not isinstance(payload, dict):
            return ApiResponse.json(400, {"error": "invalid_ai_tip_import"})
        try:
            tip = radar.import_tip(payload)
        except (TypeError, ValueError):
            return ApiResponse.json(400, {"error": "invalid_ai_tip_import"})
        return ApiResponse.json(201, tip)
    if path == "/api/ai-tips/refresh":
        force = payload.get("force", False) if isinstance(payload, dict) else False
        if not isinstance(force, bool):
            return ApiResponse.json(400, {"error": "invalid_ai_tip_refresh"})
        return ApiResponse.json(200, radar.refresh_tips(force=force))
    tip_parts = path.strip("/").split("/")
    if (
        len(tip_parts) == 4
        and tip_parts[:2] == ["api", "ai-tips"]
        and tip_parts[3] == "review"
    ):
        if not isinstance(payload, dict):
            return ApiResponse.json(400, {"error": "invalid_ai_tip_review"})
        try:
            tip = radar.review_tip(tip_parts[2], payload)
        except ValueError as exc:
            code = str(exc)
            return ApiResponse.json(
                404 if code == "tip_not_found" else 400, {"error": code}
            )
        return ApiResponse.json(200, tip)
    if (
        len(tip_parts) == 5
        and tip_parts[:3] == ["api", "ai-tips", "applications"]
        and tip_parts[4] == "rollback"
    ):
        try:
            application = radar.rollback_tip(int(tip_parts[3]))
        except (TypeError, ValueError) as exc:
            code = str(exc) or "invalid_tip_application_id"
            return ApiResponse.json(
                404 if "not_found" in code else 400, {"error": code}
            )
        return ApiResponse.json(200, application)
    parts = path.strip("/").split("/")
    if (
        len(parts) == 5
        and parts[:3] == ["api", "ai-resources", "notifications"]
        and parts[4] in {"delivered", "read"}
    ):
        try:
            notification_id = int(parts[3])
        except ValueError:
            return ApiResponse.json(400, {"error": "invalid_notification_id"})
        if not radar.mark_notification(notification_id, status=parts[4]):
            return ApiResponse.json(404, {"error": "notification_not_found"})
        return ApiResponse.json(200, {"status": parts[4]})
    return ApiResponse.json(404, {"error": "not_found"})


def _text(query: Query, key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _int(query: Query, key: str, default: int) -> int:
    value = _text(query, key)
    return int(value) if value else default


def _float(query: Query, key: str, default: float) -> float:
    value = _text(query, key)
    return float(value) if value else default


def _optional_int(query: Query, key: str) -> int | None:
    value = _text(query, key)
    return int(value) if value else None


def _optional_float(query: Query, key: str) -> float | None:
    value = _text(query, key)
    return float(value) if value else None


__all__ = [
    "ApiResponse",
    "RadarDashboardPort",
    "is_radar_api_path",
    "radar_post_body_limit",
    "route_radar_get",
    "route_radar_post",
]
