"""Build the public, read-only GitHub Pages snapshot.

The local SQLite database remains the source of truth.  This module exports a
small, deliberately allow-listed projection of it; no private state or raw
fetch response is copied to the public artifact.
"""

from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable
from urllib.parse import urlparse

from ai_resource_radar.public_locales import presentation_for
from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.store import (
    UnsupportedSchemaError,
    list_changes,
    list_offers,
    radar_summary,
)


PUBLIC_SCHEMA_VERSION = "1.0"
DATASET_ID = "ai-resource-radar-public"
MAX_PAGE = 500
FREE_OFFER_TYPES = {"recurring_free", "variable_free", "grant"}
OFFICIAL_LEVELS = {"official_api", "official_page"}
SAFE_URL_SCHEMES = {"https", "http"}
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|secret|password|cookie|authorization|account|session|credential|private[_-]?key|local[_-]?path)",
    re.IGNORECASE,
)


class PublicSiteError(RuntimeError):
    """Raised when a public snapshot must not replace the previous snapshot."""


def _jsonable(value: Any, *, depth: int = 0) -> Any:
    """Bound nested source data without carrying secrets or huge blobs."""

    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY.search(key_text):
                continue
            result[key_text[:80]] = _jsonable(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return value[:2_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def _safe_url(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme not in SAFE_URL_SCHEMES or not parsed.netloc:
        return None
    return text[:2_000]


def _evidence(record: dict[str, Any]) -> dict[str, Any] | None:
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return None
    return {
        "source_id": str(evidence.get("source_id") or "")[:120],
        "source_url": _safe_url(evidence.get("source_url")),
        "verification_level": str(evidence.get("verification_level") or "")[:40],
        "evidence_excerpt": str(evidence.get("evidence_excerpt") or "")[:500],
        "observed_at": evidence.get("observed_at"),
    }


def _resource(record: dict[str, Any]) -> dict[str, Any]:
    evidence = _evidence(record)
    public = {
        "offer_id": record.get("offer_id"),
        "provider": record.get("provider"),
        "title": record.get("title"),
        "kind": record.get("kind"),
        "offer_type": record.get("offer_type"),
        "quota_value": record.get("quota_value"),
        "quota_unit": record.get("quota_unit"),
        "reset_period": record.get("reset_period"),
        "estimated_usd_value": record.get("estimated_usd_value"),
        "requires_card": record.get("requires_card"),
        "requires_phone": record.get("requires_phone"),
        "eligibility": record.get("eligibility"),
        "mainland_status": record.get("mainland_status"),
        "expires_at": record.get("expires_at"),
        "homepage_url": _safe_url(record.get("homepage_url") or record.get("url")),
        "verification_level": record.get("verification_level"),
        "priority_tier": record.get("priority_tier"),
        "priority_reasons": _jsonable(record.get("priority_reasons") or []),
        "input_modalities": _jsonable(record.get("input_modalities") or []),
        "output_modalities": _jsonable(record.get("output_modalities") or []),
        "free_image_generation": bool(record.get("free_image_generation")),
        "first_seen_at": record.get("first_seen_at"),
        "last_seen_at": record.get("last_seen_at"),
        "last_changed_at": record.get("last_changed_at"),
        "evidence": evidence,
    }
    details = record.get("details")
    if isinstance(details, dict):
        public["details"] = _jsonable(details)
    source_id = evidence.get("source_id") if evidence else None
    localized_record = {**public, "source_id": source_id}
    public["presentation"] = presentation_for(localized_record)
    return public


def _page_offers(path: Path, *, kind: str | None, include_pricing: bool) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = list_offers(
            path,
            kind=kind,
            limit=MAX_PAGE,
            offset=offset,
            include_pricing=include_pricing,
        )
        if not page:
            break
        output.extend(page)
        if len(page) < MAX_PAGE:
            break
        offset += len(page)
    return output


def _page_prices(path: Path, *, kind: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    offset = 0
    function = list_token_prices if kind == "token" else list_gpu_prices
    while True:
        page = function(path, limit=MAX_PAGE, offset=offset)
        rows = page.get("prices") or []
        if not rows:
            break
        output.extend(rows)
        if offset + len(rows) >= int(page.get("total") or len(output)):
            break
        offset += len(rows)
    return output


def _public_price(row: dict[str, Any], *, kind: str) -> dict[str, Any]:
    allowed = (
        (
            "price_id", "provider", "model", "model_id", "input_per_mtok",
            "output_per_mtok", "cache_read_per_mtok", "cache_write_per_mtok",
            "has_cache_price", "typical_cost", "context_window", "currency",
            "pricing_url", "verification_level", "verification_label", "verified_at",
        )
        if kind == "token"
        else (
            "price_id", "provider", "title", "gpu_model", "vram_gb", "hourly_usd",
            "estimated_cost", "usd_per_vram_gb_hour", "billing_mode", "market_tier",
            "price_mode", "price_note", "currency", "pricing_url", "verification_level",
            "verification_label", "verified_at",
        )
    )
    result = {key: _jsonable(row.get(key)) for key in allowed if key in row}
    result["pricing_url"] = _safe_url(result.get("pricing_url"))
    result["presentation"] = presentation_for(
        {"kind": kind, "offer_type": "pricing_reference"}
    )
    return result


def _public_change(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "offer_id": row.get("offer_id"),
        "detected_at": row.get("detected_at"),
        "change_type": row.get("change_type"),
        "changed_fields": _jsonable(row.get("changed_fields") or {}),
        "importance": row.get("importance"),
        "provider": row.get("provider"),
        "title": row.get("title"),
        "kind": row.get("kind"),
        "priority_tier": row.get("priority_tier"),
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _csv_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "" if value is None else str(value)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys or ["value"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in writer.fieldnames})


def _files_and_hashes(root: Path) -> tuple[list[str], dict[str, str], dict[str, int]]:
    files: list[str] = []
    hashes: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "data/manifest.json":
            continue
        data = path.read_bytes()
        files.append(relative)
        hashes[relative] = hashlib.sha256(data).hexdigest()
        sizes[relative] = len(data)
    return files, hashes, sizes


def _gate(resources: list[dict[str, Any]], token_prices: list[dict[str, Any]], gpu_prices: list[dict[str, Any]]) -> dict[str, Any]:
    free = [row for row in resources if row.get("offer_type") in FREE_OFFER_TYPES]
    official_free = [row for row in free if row.get("verification_level") in OFFICIAL_LEVELS]
    official_token = sum(row.get("kind") == "token" for row in official_free)
    official_gpu = sum(row.get("kind") == "gpu" for row in official_free)
    missing: list[str] = []
    if not official_token:
        missing.append("official_free_token")
    if not official_gpu:
        missing.append("official_free_gpu")
    if not token_prices:
        missing.append("token_prices")
    if not gpu_prices:
        missing.append("gpu_prices")
    return {
        "publishable": not missing,
        "missing": missing,
        "official_free_token": official_token,
        "official_free_gpu": official_gpu,
        "free_resources": len(free),
    }


def build_public_site(
    database: Path,
    output: Path,
    *,
    base_url: str = "https://ai-resource-radar.github.io/ai-resource-radar/",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically build a public static snapshot, preserving an old output on failure."""

    if not database.exists():
        raise PublicSiteError("publish_gate_failed:database_missing")
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in SAFE_URL_SCHEMES or not parsed_base.netloc:
        raise ValueError("invalid_public_base_url")
    current = (now or datetime.now().astimezone()).astimezone()
    generated_at = current.isoformat(timespec="seconds")

    try:
        raw_resources = [
            record
            for kind in ("token", "gpu", "grant")
            for record in _page_offers(database, kind=kind, include_pricing=False)
            if record.get("offer_type") in FREE_OFFER_TYPES
        ]
        resources = [_resource(record) for record in raw_resources]
        token_prices = [_public_price(row, kind="token") for row in _page_prices(database, kind="token")]
        gpu_prices = [_public_price(row, kind="gpu") for row in _page_prices(database, kind="gpu")]
        changes = [_public_change(row) for row in list_changes(database, days=30, limit=MAX_PAGE)]
        summary = radar_summary(database, now=current)
    except UnsupportedSchemaError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PublicSiteError(f"public_export_failed:{type(exc).__name__}") from exc

    gate = _gate(resources, token_prices, gpu_prices)
    if not gate["publishable"]:
        raise PublicSiteError("publish_gate_failed:" + ",".join(gate["missing"]))
    source_summary = summary.get("sources") or {}
    statuses = list(source_summary.get("items") or [])
    public_source_summary = {
        key: _jsonable(source_summary.get(key))
        for key in (
            "total",
            "healthy",
            "fresh",
            "overdue",
            "stale",
            "verification_pending",
            "failed",
            "never",
            "status_counts",
            "oldest_official_verified_at",
            "oldest_official_age_hours",
        )
        if key in source_summary
    }
    degraded = any(item.get("status") != "fresh" for item in statuses)
    status = "partial" if degraded else "healthy"
    data = {
        "manifest": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "dataset": DATASET_ID,
            "status": status,
            "publishable": True,
            "generated_at": generated_at,
            "radar_refreshed_at": summary.get("last_refresh_at"),
            "counts": {
                "resources": len(resources),
                "token_prices": len(token_prices),
                "gpu_prices": len(gpu_prices),
                "changes": len(changes),
                **gate,
            },
            "source_health": {
                "total": source_summary.get("total", 0),
                "fresh": source_summary.get("fresh", 0),
                "overdue": source_summary.get("overdue", 0),
                "stale": source_summary.get("stale", 0),
                "verification_pending": source_summary.get("verification_pending", 0),
                "failed": source_summary.get("failed", 0),
                "never": source_summary.get("never", 0),
            },
            "files": [],
            "file_hashes": {},
            "file_bytes": {},
        },
        "summary": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": generated_at,
            "radar": {
                "schema_version": summary.get("schema_version"),
                "counts": _jsonable(summary.get("counts") or {}),
                "last_refresh_at": summary.get("last_refresh_at"),
                "sources": public_source_summary,
            },
            "gate": gate,
        },
        "source-health": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": generated_at,
            "items": [
                {
                    key: item.get(key)
                    for key in (
                        "source_id", "name", "authority", "cadence_hours", "status",
                        "last_attempt_at", "last_success_at", "last_error_code", "age_hours",
                    )
                }
                for item in statuses
            ],
        },
        "resources": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": resources},
        "token-prices": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": token_prices},
        "gpu-prices": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": gpu_prices},
        "changes": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": changes},
    }

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
    try:
        public_web = Path(__file__).with_name("public_web")
        if not public_web.is_dir():
            raise PublicSiteError("public_assets_missing")
        shutil.copytree(public_web, temp, dirs_exist_ok=True)
        canonical = base_url.rstrip("/") + "/"
        for asset in (*temp.glob("*.html"), *temp.glob("*.txt"), *temp.glob("*.xml")):
            content = asset.read_text(encoding="utf-8")
            content = content.replace(
                "https://ai-resource-radar.github.io/ai-resource-radar/", canonical
            )
            asset.write_text(content, encoding="utf-8")
        data_dir = temp / "data"
        data_dir.mkdir()
        for name, payload in data.items():
            _write_json(data_dir / f"{name}.json", payload)
        _write_csv(data_dir / "resources.csv", resources)
        _write_csv(data_dir / "token-prices.csv", token_prices)
        _write_csv(data_dir / "gpu-prices.csv", gpu_prices)
        _write_csv(data_dir / "changes.csv", changes)
        badges = temp / "data" / "badges"
        badges.mkdir()
        badge_rows = {
            "updated": ("updated", generated_at[:10], "blue"),
            "sources": ("sources", f"{source_summary.get('fresh', 0)}/{source_summary.get('total', 0)} fresh", "brightgreen" if not degraded else "yellow"),
            "coverage": ("coverage", f"{len(resources)} resources", "brightgreen"),
        }
        for filename, (label, message, color) in badge_rows.items():
            _write_json(badges / f"{filename}.json", {"schemaVersion": 1, "label": label, "message": message, "color": color})
        files, hashes, sizes = _files_and_hashes(temp)
        data["manifest"]["files"] = files
        data["manifest"]["file_hashes"] = hashes
        data["manifest"]["file_bytes"] = sizes
        _write_json(data_dir / "manifest.json", data["manifest"])
        if output.exists():
            backup = output.with_name(output.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            output.replace(backup)
            try:
                temp.replace(output)
            except Exception:
                # A failed replacement must never turn a valid previous site
                # into a missing directory.
                if not output.exists() and backup.exists():
                    backup.replace(output)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            temp.replace(output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return data["manifest"]


__all__ = ["DATASET_ID", "PUBLIC_SCHEMA_VERSION", "PublicSiteError", "build_public_site"]
