from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import sqlite3
from threading import Lock, Thread
from typing import Any

from ai_resource_radar.runtime import refresh
from ai_resource_radar.locks import OperationLockedError, operation_lock_status
from ai_resource_radar.feature_flags import (
    poster_feature_status,
    require_poster_generation,
)
from ai_resource_radar.notifications import (
    load_pending_notifications,
    notification_delivered,
    notification_read,
)
from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.provider_profiles import (
    integration_public_rows,
    provider_public_rows,
)
from ai_resource_radar.poster import (
    daily_report_status,
    generate_daily_poster,
    latest_daily_report,
    list_daily_reports,
    poster_benchmark_status,
    review_poster_benchmark,
    resolve_daily_poster,
    run_poster_benchmark,
)
from ai_resource_radar.store import (
    SCHEMA_VERSION,
    list_changes,
    list_offers,
    radar_summary,
)
from ai_resource_radar.tips import (
    add_tip,
    get_tip,
    list_tip_applications,
    list_tips,
    refresh_official_tips,
    review_tip,
    rollback_tip_application,
    seed_initial_tips,
    tips_summary,
)


@dataclass
class AiRadarDashboard:
    path: Path
    poster_root: Path | None = None
    project_root: Path | None = None
    default_locale: str = "en"
    _lock: Lock = field(default_factory=Lock)
    _state: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "report": None,
            "error": None,
        }
    )
    _poster_state: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "report": None,
            "error": None,
        }
    )
    _benchmark_state: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "report": None,
            "error": None,
        }
    )

    def summary(self) -> dict[str, Any]:
        payload = radar_summary(self.path)
        payload["default_locale"] = (
            self.default_locale if self.default_locale in {"en", "zh-CN"} else "en"
        )
        payload["supported_locales"] = ["en", "zh-CN"]
        return payload

    def schema_error(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=2,
            )
            try:
                database_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None
        if database_version <= SCHEMA_VERSION:
            return None
        return {
            "error": "ai_radar_schema_unsupported",
            "database_schema_version": database_version,
            "runtime_supported_schema_version": SCHEMA_VERSION,
        }

    def offers(self, **filters: Any) -> tuple[dict[str, Any], ...]:
        filters.setdefault("include_pricing", False)
        return list_offers(self.path, **filters)

    def provider_profiles(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "providers": provider_public_rows(),
            "integrations": integration_public_rows(),
        }

    def changes(self, *, days: int, limit: int) -> tuple[dict[str, Any], ...]:
        return list_changes(self.path, days=days, limit=limit)

    def tips_summary(self) -> dict[str, Any]:
        seed_initial_tips(self.path)
        return tips_summary(self.path)

    def tips(self, **filters: Any) -> tuple[dict[str, Any], ...]:
        return list_tips(self.path, **filters)

    def tip(self, tip_id: str) -> dict[str, Any] | None:
        return get_tip(self.path, tip_id)

    def import_tip(self, payload: dict[str, Any]) -> dict[str, Any]:
        return add_tip(
            self.path,
            title=payload.get("title", ""),
            category=payload.get("category", ""),
            summary=payload.get("summary", ""),
            instruction=payload.get("instruction", ""),
            source_url=payload.get("source_url", ""),
            source_type=payload.get("source_type", "manual"),
            source_title=payload.get("source_title", ""),
            example=payload.get("example", ""),
            constraints=payload.get("constraints", ()),
            tags=payload.get("tags", ()),
            evidence_summary=payload.get("evidence_summary", ""),
            risk_level=payload.get("risk_level", "medium"),
        )

    def review_tip(self, tip_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return review_tip(
            self.path,
            tip_id,
            action=payload.get("action", ""),
            scope=payload.get("scope"),
            reason=payload.get("reason", ""),
            project_root=self.project_root,
        )

    def tip_applications(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        return list_tip_applications(self.path, limit=limit)

    def rollback_tip(self, application_id: int) -> dict[str, Any]:
        return rollback_tip_application(
            self.path, application_id, project_root=self.project_root
        )

    def refresh_tips(self, *, force: bool = False) -> dict[str, Any]:
        return refresh_official_tips(self.path, force=force)

    def token_prices(self, **filters: Any) -> dict[str, Any]:
        return list_token_prices(self.path, **filters)

    def gpu_prices(self, **filters: Any) -> dict[str, Any]:
        return list_gpu_prices(self.path, **filters)

    def poster_latest(self) -> dict[str, Any] | None:
        return latest_daily_report(self.path)

    def poster_reports(self, *, days: int = 90) -> tuple[dict[str, Any], ...]:
        return list_daily_reports(self.path, days=days)

    def poster_image(self, report_date: str) -> Path | None:
        return resolve_daily_poster(
            self.path,
            report_date,
            poster_root=self.poster_root,
        )

    def poster_status(self) -> dict[str, Any]:
        with self._lock:
            task = dict(self._poster_state)
            benchmark_task = dict(self._benchmark_state)
        return {
            **daily_report_status(self.path),
            "task": task,
            "benchmark_task": benchmark_task,
        }

    def poster_feature(self) -> dict[str, Any]:
        """Expose the immutable poster feature gate to host routers."""

        return poster_feature_status()

    def start_poster_benchmark(self, *, cases: int = 3) -> dict[str, Any] | None:
        require_poster_generation()
        with self._lock:
            if self._benchmark_state["status"] == "running" or bool(
                operation_lock_status(self.path, "poster")["locked"]
            ):
                return None
            started = datetime.now().astimezone().isoformat(timespec="seconds")
            self._benchmark_state = {
                "status": "running",
                "started_at": started,
                "finished_at": None,
                "report": None,
                "error": None,
            }
        Thread(target=self._run_poster_benchmark, args=(cases,), daemon=True).start()
        return self.poster_status()

    def _run_poster_benchmark(self, cases: int) -> None:
        try:
            payload = run_poster_benchmark(
                self.path,
                cases=cases,
                poster_root=self.poster_root,
            )
            status = "completed"
            error = None
        except (OperationLockedError, RuntimeError, ValueError) as exc:
            payload = None
            status = "failed"
            error = str(exc)
        except Exception:
            payload = None
            status = "failed"
            error = "poster_benchmark_failed"
        finished = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock:
            self._benchmark_state = {
                "status": status,
                "started_at": self._benchmark_state["started_at"],
                "finished_at": finished,
                "report": payload,
                "error": error,
            }

    def review_poster_benchmark(
        self, *, approve: bool, notes: str = ""
    ) -> dict[str, Any]:
        require_poster_generation()
        return review_poster_benchmark(
            self.path,
            approve=approve,
            notes=notes,
        )

    def start_poster(self, *, force: bool = False) -> dict[str, Any] | None:
        require_poster_generation()
        with self._lock:
            if self._poster_state["status"] == "running" or bool(
                operation_lock_status(self.path, "poster")["locked"]
            ):
                return None
            started = datetime.now().astimezone().isoformat(timespec="seconds")
            self._poster_state = {
                "status": "running",
                "started_at": started,
                "finished_at": None,
                "report": None,
                "error": None,
            }
        Thread(target=self._run_poster, args=(force,), daemon=True).start()
        return self.poster_status()

    def _run_poster(self, force: bool) -> None:
        try:
            payload = generate_daily_poster(
                self.path,
                force=force,
                poster_root=self.poster_root,
            )
            status = "completed" if payload.get("status") == "success" else "failed"
            error = payload.get("error_code") if status == "failed" else None
        except OperationLockedError as exc:
            payload = None
            status = "failed"
            error = str(exc)
        except Exception:
            payload = None
            status = "failed"
            error = "poster_generation_failed"
        finished = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock:
            self._poster_state = {
                "status": status,
                "started_at": self._poster_state["started_at"],
                "finished_at": finished,
                "report": payload,
                "error": error,
            }

    def refresh_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start_refresh(self, *, force: bool = True) -> dict[str, Any] | None:
        with self._lock:
            if self._state["status"] == "running" or bool(
                operation_lock_status(self.path, "refresh")["locked"]
            ):
                return None
            started = datetime.now().astimezone().isoformat(timespec="seconds")
            self._state = {
                "status": "running",
                "started_at": started,
                "finished_at": None,
                "report": None,
                "error": None,
            }
        Thread(target=self._run_refresh, args=(force,), daemon=True).start()
        return self.refresh_status()

    def _run_refresh(self, force: bool) -> None:
        try:
            report = refresh(self.path, force=force)
            payload = report.to_dict()
            status = "completed" if not report.failed_count else "partial"
            error = None
        except OperationLockedError as exc:
            payload = None
            status = "failed"
            error = str(exc)
        except Exception:
            payload = None
            status = "failed"
            error = "ai_radar_refresh_failed"
        finished = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock:
            self._state = {
                "status": status,
                "started_at": self._state["started_at"],
                "finished_at": finished,
                "report": payload,
                "error": error,
            }

    def pending_notifications(self, *, limit: int = 5) -> tuple[dict[str, Any], ...]:
        return load_pending_notifications(self.path, limit=limit)

    def mark_notification(self, notification_id: int, *, status: str) -> bool:
        if status == "delivered":
            return notification_delivered(self.path, notification_id)
        if status == "read":
            return notification_read(self.path, notification_id)
        return False
