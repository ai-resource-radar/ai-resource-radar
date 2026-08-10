"""Daily poster report persistence, retention and image publication."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from ai_resource_radar.model_registry import get_image_model
from ai_resource_radar.store import POSTER_RETENTION_DAYS, connect

from .constants import *  # noqa: F401,F403
from .facts import PosterFacts, default_poster_root
from .provider import KeyStore, poster_benchmark_status, poster_configuration
from .validation import PosterValidation
def _report_dict(row: Any) -> dict[str, Any]:
    payload = dict(row)
    for source, target in (
        ("selected_facts_json", "selected_facts"),
        ("validation_json", "validation"),
    ):
        raw = payload.pop(source, "{}")
        try:
            payload[target] = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            payload[target] = {}
    payload["image_url"] = (
        f"/api/ai-daily/{payload['report_date']}/image"
        if payload.get("status") == "success" and payload.get("image_path")
        else None
    )
    return payload


def list_daily_reports(
    path: Path,
    *,
    days: int = POSTER_RETENTION_DAYS,
    limit: int = POSTER_RETENTION_DAYS,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= days <= POSTER_RETENTION_DAYS or not 1 <= limit <= POSTER_RETENTION_DAYS:
        raise ValueError("invalid_daily_report_filter")
    if not path.exists():
        return ()
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT * FROM daily_reports
            WHERE report_date >= ?
            ORDER BY report_date DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return tuple(_report_dict(row) for row in rows)
    finally:
        connection.close()


def latest_daily_report(
    path: Path,
    *,
    success_only: bool = True,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    connection = connect(path)
    try:
        clause = "WHERE status = 'success'" if success_only else ""
        row = connection.execute(
            f"SELECT * FROM daily_reports {clause} ORDER BY report_date DESC LIMIT 1"
        ).fetchone()
        return _report_dict(row) if row else None
    finally:
        connection.close()


def daily_report_status(
    path: Path,
    *,
    key_store: KeyStore | None = None,
    current: date | None = None,
    openclaw_binary: str | Path | None = None,
) -> dict[str, Any]:
    configuration = poster_configuration(
        path,
        key_store=key_store,
        openclaw_binary=openclaw_binary,
    )
    today = (current or date.today()).isoformat()
    report = None
    last_failure = None
    if path.exists():
        connection = connect(path)
        try:
            row = connection.execute(
                "SELECT * FROM daily_reports WHERE report_date = ?", (today,)
            ).fetchone()
            report = _report_dict(row) if row else None
            failure_rows = connection.execute(
                "SELECT key, value FROM radar_metadata WHERE key IN (?, ?, ?)",
                (
                    POSTER_LAST_FAILURE_CODE_METADATA,
                    POSTER_LAST_FAILURE_DATE_METADATA,
                    POSTER_LAST_FAILURE_AT_METADATA,
                ),
            ).fetchall()
            failure_values = {
                str(item["key"]): str(item["value"]) for item in failure_rows
            }
            if failure_values.get(POSTER_LAST_FAILURE_CODE_METADATA):
                last_failure = {
                    "error_code": failure_values[POSTER_LAST_FAILURE_CODE_METADATA],
                    "report_date": failure_values.get(
                        POSTER_LAST_FAILURE_DATE_METADATA
                    ),
                    "failed_at": failure_values.get(POSTER_LAST_FAILURE_AT_METADATA),
                }
        finally:
            connection.close()
    benchmark_spec = get_image_model(OPENCLAW_POSTER_PROVIDER, OPENCLAW_POSTER_MODEL)
    if (
        configuration.get("provider") == benchmark_spec.provider
        and configuration.get("model") == benchmark_spec.model
    ):
        benchmark_configured = bool(configuration.get("configured"))
        benchmark_configuration_reason = configuration.get("configuration_reason")
    else:
        # Do not make every status request spawn OpenClaw when another model is
        # selected. Selecting CogView while disabled is explicit and cheap.
        benchmark_configured = False
        benchmark_configuration_reason = "poster_benchmark_model_not_selected"
    benchmark = poster_benchmark_status(
        path,
        provider=benchmark_spec.provider,
        model=benchmark_spec.model,
    )
    benchmark.update(
        {
            "configured": benchmark_configured,
            "configuration_reason": benchmark_configuration_reason,
        }
    )
    return {
        "schema_version": "1.1",
        **configuration,
        "benchmark": benchmark,
        "quality": POSTER_QUALITY,
        "max_attempts_per_day": MAX_POSTER_ATTEMPTS_PER_DAY,
        "today": report,
        "latest": latest_daily_report(path),
        "last_failure": last_failure,
    }


def _record_last_failure_metadata(
    connection: Any,
    *,
    report_date: str,
    error_code: str,
    at: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO radar_metadata(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (
            (POSTER_LAST_FAILURE_CODE_METADATA, error_code),
            (POSTER_LAST_FAILURE_DATE_METADATA, report_date),
            (POSTER_LAST_FAILURE_AT_METADATA, at),
        ),
    )


def _clear_last_failure_metadata(connection: Any) -> None:
    connection.execute(
        "DELETE FROM radar_metadata WHERE key IN (?, ?, ?)",
        (
            POSTER_LAST_FAILURE_CODE_METADATA,
            POSTER_LAST_FAILURE_DATE_METADATA,
            POSTER_LAST_FAILURE_AT_METADATA,
        ),
    )


def _failure_response(
    path: Path,
    *,
    report_date: str,
    provider: str,
    model: str,
    error_code: str,
) -> dict[str, Any]:
    current = latest_daily_report(path, success_only=False)
    if current is not None and current.get("status") != "success":
        return current
    return {
        "schema_version": "1.1",
        "report_date": report_date,
        "status": "failed",
        "provider": provider,
        "model": model,
        "attempt_count": int(current.get("attempt_count") or 0) if current else 0,
        "error_code": error_code,
        "preserved_published_report": bool(current),
        "published_report_date": current.get("report_date") if current else None,
    }


def _upsert_failure(
    path: Path,
    *,
    report_date: str,
    at: str,
    error_code: str,
    facts: PosterFacts | None = None,
    provider: str = POSTER_PROVIDER,
    model: str = POSTER_MODEL,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO daily_reports(
                    report_date, status, generated_at, radar_refreshed_at,
                    provider, model, quality, selected_facts_json,
                    validation_json, error_code, updated_at
                )
                VALUES (?, 'failed', ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    status = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.status
                        ELSE 'failed'
                    END,
                    error_code = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.error_code
                        ELSE excluded.error_code
                    END,
                    provider = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.provider
                        ELSE excluded.provider
                    END,
                    model = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.model
                        ELSE excluded.model
                    END,
                    selected_facts_json = CASE
                        WHEN daily_reports.image_path IS NOT NULL
                            OR excluded.selected_facts_json = '{}'
                        THEN daily_reports.selected_facts_json
                        ELSE excluded.selected_facts_json
                    END,
                    updated_at = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.updated_at
                        ELSE excluded.updated_at
                    END
                """,
                (
                    report_date,
                    at,
                    facts.refreshed_at if facts else None,
                    provider,
                    model,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict() if facts else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    error_code,
                    at,
                ),
            )
            _record_last_failure_metadata(
                connection,
                report_date=report_date,
                error_code=error_code,
                at=at,
            )
    finally:
        connection.close()


def _reserve_attempt(
    path: Path,
    *,
    facts: PosterFacts,
    prompt_hash: str,
    at: str,
    provider: str,
    model: str,
) -> int | None:
    connection = connect(path)
    try:
        with connection:
            benchmark_attempts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM poster_model_benchmarks WHERE run_date = ?",
                    (facts.report_date,),
                ).fetchone()[0]
            )
            allowed_daily_attempts = max(
                0, MAX_POSTER_ATTEMPTS_PER_DAY - benchmark_attempts
            )
            if allowed_daily_attempts == 0:
                return None
            connection.execute(
                """
                INSERT INTO daily_reports(
                    report_date, status, generated_at, radar_refreshed_at,
                    provider, model, quality, attempt_count, selected_facts_json,
                    prompt_sha256, validation_json, updated_at
                )
                VALUES (?, 'running', ?, ?, ?, ?, ?, 0, ?, ?, '{}', ?)
                ON CONFLICT(report_date) DO NOTHING
                """,
                (
                    facts.report_date,
                    at,
                    facts.refreshed_at,
                    provider,
                    model,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict(), ensure_ascii=False, separators=(",", ":")
                    ),
                    prompt_hash,
                    at,
                ),
            )
            cursor = connection.execute(
                """
                UPDATE daily_reports
                SET attempt_count = attempt_count + 1,
                    status = CASE WHEN image_path IS NULL THEN 'running' ELSE status END,
                    generated_at = CASE WHEN image_path IS NULL THEN ? ELSE generated_at END,
                    radar_refreshed_at = CASE
                        WHEN image_path IS NULL THEN ? ELSE radar_refreshed_at END,
                    provider = CASE WHEN image_path IS NULL THEN ? ELSE provider END,
                    model = CASE WHEN image_path IS NULL THEN ? ELSE model END,
                    quality = CASE WHEN image_path IS NULL THEN ? ELSE quality END,
                    selected_facts_json = CASE
                        WHEN image_path IS NULL THEN ? ELSE selected_facts_json END,
                    prompt_sha256 = CASE
                        WHEN image_path IS NULL THEN ? ELSE prompt_sha256 END,
                    error_code = CASE WHEN image_path IS NULL THEN NULL ELSE error_code END,
                    updated_at = CASE WHEN image_path IS NULL THEN ? ELSE updated_at END
                WHERE report_date = ? AND attempt_count < ?
                """,
                (
                    at,
                    facts.refreshed_at,
                    provider,
                    model,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict(), ensure_ascii=False, separators=(",", ":")
                    ),
                    prompt_hash,
                    at,
                    facts.report_date,
                    allowed_daily_attempts,
                ),
            )
            if cursor.rowcount != 1:
                return None
            return int(
                connection.execute(
                    "SELECT attempt_count FROM daily_reports WHERE report_date = ?",
                    (facts.report_date,),
                ).fetchone()[0]
            )
    finally:
        connection.close()


def _record_attempt_failure(
    path: Path,
    *,
    report_date: str,
    validation: PosterValidation | None,
    error_code: str,
    request_id: str | None,
    at: str,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET status = CASE WHEN image_path IS NULL THEN 'failed' ELSE status END,
                    validation_json = CASE
                        WHEN image_path IS NULL THEN ? ELSE validation_json END,
                    error_code = CASE
                        WHEN image_path IS NULL THEN ? ELSE error_code END,
                    request_id = CASE
                        WHEN image_path IS NULL THEN ? ELSE request_id END,
                    updated_at = CASE
                        WHEN image_path IS NULL THEN ? ELSE updated_at END
                WHERE report_date = ?
                """,
                (
                    json.dumps(
                        validation.to_dict() if validation else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    error_code,
                    request_id,
                    at,
                    report_date,
                ),
            )
            _record_last_failure_metadata(
                connection,
                report_date=report_date,
                error_code=error_code,
                at=at,
            )
    finally:
        connection.close()


def _record_success(
    path: Path,
    *,
    facts: PosterFacts,
    validation: PosterValidation,
    relative_image_path: str,
    image_sha256: str,
    image_bytes: int,
    request_id: str | None,
    at: str,
    provider: str,
    model: str,
    prompt_sha256: str,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET status = 'success', generated_at = ?, radar_refreshed_at = ?,
                    provider = ?, model = ?, quality = ?,
                    selected_facts_json = ?, prompt_sha256 = ?, validation_json = ?,
                    image_path = ?, image_sha256 = ?, image_bytes = ?,
                    error_code = NULL, request_id = ?, updated_at = ?
                WHERE report_date = ?
                """,
                (
                    at,
                    facts.refreshed_at,
                    provider,
                    model,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict(), ensure_ascii=False, separators=(",", ":")
                    ),
                    prompt_sha256,
                    json.dumps(
                        validation.to_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    relative_image_path,
                    image_sha256,
                    image_bytes,
                    request_id,
                    at,
                    facts.report_date,
                ),
            )
            _clear_last_failure_metadata(connection)
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO notifications(
                    created_at, dedupe_key, title, body, target_url, item_count
                )
                VALUES (?, ?, 'AI 雷达日报已生成', ?, ?, 1)
                """,
                (
                    at,
                    f"daily-poster:{facts.report_date}",
                    f"{facts.report_date} 的纯图片日报已通过文字与数字校验。",
                    "/ai-resources.html#poster",
                ),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "UPDATE daily_reports SET notified_at = ? WHERE report_date = ?",
                    (at, facts.report_date),
                )
    finally:
        connection.close()


def _save_webp(
    source: Path,
    target: Path,
    *,
    strict_aspect: bool = False,
) -> tuple[str, int]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("poster_image_processing_unavailable") from exc
    temporary = target.with_suffix(".webp.tmp")
    try:
        with Image.open(source) as image:
            image.load()
            rgb = image.convert("RGB")
            if strict_aspect:
                # CogView's official 864x1152 canvas is already 3:4.  Keep the
                # entire model output and only scale it; never crop, pad, or
                # stretch a benchmark-qualified daily poster.
                if rgb.width * POSTER_HEIGHT != rgb.height * POSTER_WIDTH:
                    raise RuntimeError("poster_image_aspect_ratio_invalid")
                normalized = rgb.resize(
                    (POSTER_WIDTH, POSTER_HEIGHT),
                    resample=Image.Resampling.LANCZOS,
                )
            else:
                normalized = ImageOps.fit(
                    rgb,
                    (POSTER_WIDTH, POSTER_HEIGHT),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
            normalized.save(temporary, format="WEBP", quality=90, method=6)
        body = temporary.read_bytes()
        if not body:
            raise RuntimeError("poster_image_processing_failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return hashlib.sha256(body).hexdigest(), len(body)
    except (OSError, ValueError) as exc:
        raise RuntimeError("poster_image_processing_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_suffix(media_type: str) -> str:
    return ".jpg" if media_type == "image/jpeg" else ".png"


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    if re.fullmatch(r"[a-z0-9_]{3,80}", value):
        return value
    return "poster_generation_failed"


def prune_daily_posters(
    path: Path,
    *,
    poster_root: Path | None = None,
    now: datetime | None = None,
) -> int:
    if not path.exists():
        return 0
    root = poster_root or default_poster_root()
    current = (now or datetime.now().astimezone()).astimezone()
    cutoff = (current.date() - timedelta(days=POSTER_RETENTION_DAYS)).isoformat()
    connection = connect(path)
    try:
        rows = connection.execute(
            "SELECT report_date, image_path FROM daily_reports WHERE report_date < ?",
            (cutoff,),
        ).fetchall()
        root_resolved = root.resolve()
        for row in rows:
            relative = row["image_path"]
            if not relative:
                continue
            candidate = (root / str(relative)).resolve()
            if candidate.is_relative_to(root_resolved):
                candidate.unlink(missing_ok=True)
        with connection:
            cursor = connection.execute(
                "DELETE FROM daily_reports WHERE report_date < ?", (cutoff,)
            )
        return max(0, cursor.rowcount)
    finally:
        connection.close()


def resolve_daily_poster(
    path: Path,
    report_date: str,
    *,
    poster_root: Path | None = None,
) -> Path | None:
    try:
        date.fromisoformat(report_date)
    except ValueError:
        return None
    if not path.exists():
        return None
    connection = connect(path)
    try:
        row = connection.execute(
            """
            SELECT image_path FROM daily_reports
            WHERE report_date = ? AND status = 'success'
            """,
            (report_date,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or not row["image_path"]:
        return None
    root = (poster_root or default_poster_root()).resolve()
    image = (root / str(row["image_path"])).resolve()
    if not image.is_relative_to(root) or not image.is_file():
        return None
    return image



__all__ = ["_candidate_suffix", "_clear_last_failure_metadata", "_failure_response", "_record_attempt_failure", "_record_last_failure_metadata", "_record_success", "_report_dict", "_reserve_attempt", "_safe_error", "_save_webp", "_upsert_failure", "daily_report_status", "latest_daily_report", "list_daily_reports", "prune_daily_posters", "resolve_daily_poster"]
