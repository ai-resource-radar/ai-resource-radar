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
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable
from urllib.parse import urlparse

from ai_resource_radar import __version__
from ai_resource_radar.provider_pages import (
    decorate_provider_record,
    provider_page_url,
    public_https_url,
    render_provider_page,
)
from ai_resource_radar.provider_profiles import (
    PROVIDER_PROFILES,
    integration_public_rows,
    provider_public_rows,
)
from ai_resource_radar.public_locales import presentation_for
from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.sources import SOURCES
from ai_resource_radar.store import (
    UnsupportedSchemaError,
    list_changes,
    list_offers,
    radar_summary,
)


PUBLIC_SCHEMA_VERSION = "1.2"
DATASET_ID = "ai-resource-radar-public"
MAX_PAGE = 500
FREE_OFFER_TYPES = {"recurring_free", "variable_free", "grant"}
OFFICIAL_LEVELS = {"official_api", "official_page"}
SAFE_URL_SCHEMES = {"https", "http"}
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|secret|password|cookie|authorization|account|session|credential|private[_-]?key|local[_-]?path)",
    re.IGNORECASE,
)
_ANALYTICS_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_CLOUDFLARE_SCRIPT = "https://static.cloudflareinsights.com/beacon.min.js"


class PublicSiteError(RuntimeError):
    """Raised when a public snapshot must not replace the previous snapshot."""


def _analytics_markup(provider: str) -> tuple[str, str]:
    """Return an opt-in public beacon and the matching restrictive CSP.

    The token identifies a public hostname; it is deliberately accepted only
    through the environment so it cannot leak through process arguments. The
    local dashboard never calls this builder with analytics enabled.
    """

    if provider == "none":
        return "", (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'none'"
        )
    if provider != "cloudflare":
        raise ValueError("invalid_analytics_provider")
    token = os.environ.get("AI_RADAR_CLOUDFLARE_ANALYTICS_TOKEN", "").strip()
    if not _ANALYTICS_TOKEN.fullmatch(token):
        raise PublicSiteError("publish_gate_invalid_cloudflare_analytics_token")
    payload = json.dumps({"token": token, "spa": False}, separators=(",", ":"))
    script = (
        f'<script defer src="{_CLOUDFLARE_SCRIPT}" '
        f"data-cf-beacon='{payload}'></script>"
    )
    csp = (
        "default-src 'self'; script-src 'self' https://static.cloudflareinsights.com; "
        "style-src 'self'; img-src 'self' data:; "
        "connect-src 'self' https://cloudflareinsights.com; font-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'none'"
    )
    return script, csp


def _inject_analytics(content: str, *, provider: str) -> str:
    script, csp = _analytics_markup(provider)
    content = re.sub(
        r'(<meta http-equiv="Content-Security-Policy" content=")[^"]*(">)',
        lambda match: match.group(1) + csp + match.group(2),
        content,
        count=1,
    )
    if script:
        content = content.replace("</head>", f"    {script}\n  </head>", 1)
    return content


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _load_refresh_report(value: Path | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicSiteError("publish_gate_invalid_refresh_report") from exc
    if not isinstance(payload, dict):
        raise PublicSiteError("publish_gate_invalid_refresh_report")
    return payload


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
    return public_https_url(value) or None


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


def _featured_resources(resources: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    """Select a compact, deterministic landing-page subset.

    The browser can render the first useful viewport without downloading the
    full catalogue. The full resources URL remains unchanged for machines and
    for users who open a category view.
    """

    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    mainland_order = {"supported": 0, "unknown": 1, "unsupported": 2}
    ordered = sorted(
        (
            row
            for row in resources
            if row.get("verification_level") in OFFICIAL_LEVELS
            and row.get("priority_tier") in {"A", "B"}
            and row.get("requires_card") == "no"
            and row.get("mainland_status") in {"supported", "unknown"}
        ),
        key=lambda row: (
            tier_order.get(str(row.get("priority_tier")), 9),
            mainland_order.get(str(row.get("mainland_status")), 9),
            -(float(row.get("estimated_usd_value") or 0)),
            str(row.get("provider") or "").casefold(),
            str(row.get("offer_id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    providers: set[str] = set()
    for row in ordered:
        provider = str(row.get("provider") or "").casefold()
        if provider in providers:
            continue
        providers.add(provider)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


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
    source_revision: str | None = None,
    refresh_report: Path | dict[str, Any] | None = None,
    analytics_provider: str = "none",
) -> dict[str, Any]:
    """Atomically build a public static snapshot, preserving an old output on failure."""

    if not database.exists():
        raise PublicSiteError("publish_gate_failed:database_missing")
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in SAFE_URL_SCHEMES or not parsed_base.netloc:
        raise ValueError("invalid_public_base_url")
    # Validate configuration before reading or transforming the snapshot so a
    # production mistake preserves the prior atomic site untouched.
    analytics_script, analytics_csp = _analytics_markup(analytics_provider)
    current = (now or datetime.now().astimezone()).astimezone()
    generated_at = current.isoformat(timespec="seconds")
    report = _load_refresh_report(refresh_report)

    try:
        raw_catalog = [
            record
            for kind in ("token", "gpu", "grant")
            for record in _page_offers(database, kind=kind, include_pricing=False)
        ]
        raw_resources = [
            record for record in raw_catalog
            if record.get("offer_type") in FREE_OFFER_TYPES
        ]
        resources = [_resource(record) for record in raw_resources]
        provider_offers = [
            _resource(record)
            for record in raw_catalog
            if record.get("verification_level") in OFFICIAL_LEVELS
        ]
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
    revision = (source_revision or "local")[:64]
    resources = [
        decorate_provider_record(
            row, base_url=base_url, source_revision=revision
        )
        for row in resources
    ]
    provider_offers = [
        decorate_provider_record(
            row, base_url=base_url, source_revision=revision
        )
        for row in provider_offers
    ]
    token_prices = [
        decorate_provider_record(
            row, base_url=base_url, source_revision=revision
        )
        for row in token_prices
    ]
    gpu_prices = [
        decorate_provider_record(
            row, base_url=base_url, source_revision=revision
        )
        for row in gpu_prices
    ]
    providers = provider_public_rows()
    for row in providers:
        row["provider_urls"] = {
            "zh-CN": provider_page_url(base_url, "zh-CN", row["slug"]),
            "en": provider_page_url(base_url, "en", row["slug"]),
        }
    integrations = integration_public_rows()
    for row in integrations:
        row["provider_urls"] = {
            "zh-CN": provider_page_url(base_url, "zh-CN", row["slug"]),
            "en": provider_page_url(base_url, "en", row["slug"]),
        }
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
    last_refresh = _time(summary.get("last_refresh_at"))
    data_age_seconds = (
        max(0, int((current - last_refresh.astimezone(current.tzinfo)).total_seconds()))
        if last_refresh is not None
        else None
    )
    refresh_started_at = report.get("generated_at") if report else None
    refresh_mode = str(report.get("refresh_mode") or "cadence") if report else "cadence"
    if report is not None:
        if refresh_mode not in {"forced", "cadence"} or _time(refresh_started_at) is None:
            raise PublicSiteError("publish_gate_invalid_refresh_report")
        report_sources = report.get("sources")
        if not isinstance(report_sources, list):
            raise PublicSiteError("publish_gate_invalid_refresh_report")
        expected_ids = {source.id for source in SOURCES}
        attempted_ids = {
            str(item.get("source_id"))
            for item in report_sources
            if isinstance(item, dict) and item.get("source_id")
        }
        if attempted_ids != expected_ids or len(report_sources) != len(expected_ids):
            raise PublicSiteError("publish_gate_incomplete_source_attempt")
        if refresh_mode == "forced" and any(
            isinstance(item, dict) and item.get("status") == "skipped_not_due"
            for item in report_sources
        ):
            raise PublicSiteError("publish_gate_forced_refresh_skipped")
        if source_summary.get("total") != len(SOURCES):
            raise PublicSiteError("publish_gate_source_count_mismatch")
        attempt_times = [
            parsed
            for item in statuses
            for parsed in (_time(item.get("last_attempt_at")),)
            if parsed is not None
        ]
        if len(attempt_times) != len(SOURCES):
            raise PublicSiteError("publish_gate_incomplete_source_attempt")
        oldest_attempt = min(item.astimezone(current.tzinfo) for item in attempt_times)
        data_age_seconds = max(0, int((current - oldest_attempt).total_seconds()))
        if data_age_seconds > 30 * 60:
            raise PublicSiteError("publish_gate_data_too_old")
        if int(source_summary.get("stale") or 0) or int(source_summary.get("never") or 0):
            raise PublicSiteError("publish_gate_stale_sources")
    data = {
        "manifest": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "dataset": DATASET_ID,
            "package_version": __version__,
            "source_revision": revision,
            "analytics_provider": analytics_provider,
            "refresh_mode": refresh_mode,
            "refresh_started_at": refresh_started_at,
            "data_age_seconds": data_age_seconds,
            "status": status,
            "publishable": True,
            "generated_at": generated_at,
            "radar_refreshed_at": summary.get("last_refresh_at"),
            "counts": {
                "resources": len(resources),
                "token_prices": len(token_prices),
                "gpu_prices": len(gpu_prices),
                "changes": len(changes),
                "providers": len(providers),
                "integrations": len(integrations),
                "free_image_generation": sum(bool(row.get("free_image_generation")) for row in resources),
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
        "featured": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": _featured_resources(resources)},
        "token-prices": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": token_prices},
        "gpu-prices": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": gpu_prices},
        "changes": {"schema_version": PUBLIC_SCHEMA_VERSION, "generated_at": generated_at, "items": changes},
        "important-changes": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": generated_at,
            "items": [
                row
                for row in changes
                if row.get("importance") in {"high", "critical"}
                or row.get("change_type") in {"removed", "quota_changed", "limits_changed", "expiring"}
            ][:5],
        },
        "providers": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": generated_at,
            "items": providers,
        },
        "integrations": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": generated_at,
            "items": integrations,
        },
    }

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
    try:
        public_web = Path(__file__).with_name("public_web")
        if not public_web.is_dir():
            raise PublicSiteError("public_assets_missing")
        shutil.copytree(public_web, temp, dirs_exist_ok=True)
        shared_web = Path(__file__).with_name("frontend_shared")
        if not shared_web.is_dir():
            raise PublicSiteError("public_shared_assets_missing")
        shutil.copytree(shared_web, temp / "shared")
        canonical = base_url.rstrip("/") + "/"
        for asset in (*temp.glob("*.html"), *temp.glob("*.txt"), *temp.glob("*.xml")):
            content = asset.read_text(encoding="utf-8")
            content = content.replace(
                "https://ai-resource-radar.github.io/ai-resource-radar/", canonical
            )
            if asset.suffix == ".html":
                content = _inject_analytics(content, provider=analytics_provider)
            asset.write_text(content, encoding="utf-8")
        integrations_by_slug = {row["slug"]: row for row in integrations}
        for profile in PROVIDER_PROFILES:
            for locale, language_path in (("zh-CN", "zh"), ("en", "en")):
                destination = temp / language_path / "providers" / profile.slug
                destination.mkdir(parents=True, exist_ok=True)
                destination.joinpath("index.html").write_text(
                    render_provider_page(
                        profile,
                        locale=locale,
                        base_url=base_url,
                        resources=provider_offers,
                        token_prices=token_prices,
                        gpu_prices=gpu_prices,
                        integration=integrations_by_slug.get(profile.slug),
                        source_revision=revision,
                        analytics_script=analytics_script,
                        csp=analytics_csp,
                    ),
                    encoding="utf-8",
                )
        sitemap_urls = [canonical] + [
            provider_page_url(base_url, locale, profile.slug)
            for profile in PROVIDER_PROFILES
            for locale in ("zh-CN", "en")
        ]
        (temp / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"  <url><loc>{url}</loc></url>\n" for url in sitemap_urls)
            + "</urlset>\n",
            encoding="utf-8",
        )
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
