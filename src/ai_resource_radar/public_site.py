"""Build the public, read-only GitHub Pages snapshot.

The local SQLite database remains the source of truth.  This module exports a
small, deliberately allow-listed projection of it; no private state or raw
fetch response is copied to the public artifact.
"""

from __future__ import annotations

import csv
from datetime import datetime
import hashlib
from html import escape
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
from ai_resource_radar.public_feeds import build_public_feeds
from ai_resource_radar.regions import ISO2_CODES, REGION_MODEL_VERSION, REGION_PRESETS
from ai_resource_radar.scenario_pages import (
    SCENARIOS,
    build_scenario_pages,
)
from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.sources import SOURCES
from ai_resource_radar.store import (
    UnsupportedSchemaError,
    list_changes,
    list_offers,
    radar_summary,
)


PUBLIC_SCHEMA_VERSION = "1.4"
DATASET_ID = "ai-resource-radar-public"
EXPERIMENT_STARTED_AT = "2026-08-12"
MAX_PAGE = 500
FREE_OFFER_TYPES = {"recurring_free", "variable_free", "grant"}
OFFICIAL_LEVELS = {"official_api", "official_page"}
SAFE_URL_SCHEMES = {"https", "http"}
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|secret|password|cookie|authorization|account|session|credential|private[_-]?key|local[_-]?path)",
    re.IGNORECASE,
)
_ANALYTICS_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_GOOGLE_SITE_VERIFICATION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
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
    csp_pattern = r'(<meta http-equiv="Content-Security-Policy" content=")[^"]*(">)'
    if re.search(csp_pattern, content):
        content = re.sub(
            csp_pattern,
            lambda match: match.group(1) + csp + match.group(2),
            content,
            count=1,
        )
    else:
        content = content.replace(
            "</head>",
            f'    <meta http-equiv="Content-Security-Policy" content="{csp}">\n  </head>',
            1,
        )
    if script:
        content = content.replace("</head>", f"    {script}\n  </head>", 1)
    return content


def _search_console_markup(provider: str) -> str:
    """Return the public verification meta without persisting its source value.

    Google requires the verification value to be public in the built homepage.
    It is therefore accepted only from the environment and is intentionally
    omitted from manifests, logs, command arguments, and exported datasets.
    """

    if provider == "none":
        return ""
    if provider != "google":
        raise ValueError("invalid_search_console_provider")
    token = os.environ.get("AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN", "").strip()
    if not _GOOGLE_SITE_VERIFICATION_TOKEN.fullmatch(token):
        raise PublicSiteError("publish_gate_invalid_google_site_verification_token")
    return f'<meta name="google-site-verification" content="{token}">'


def _inject_search_console(content: str, *, markup: str) -> str:
    if not markup:
        return content
    return content.replace("</head>", f"    {markup}\n  </head>", 1)


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
    raw_availability = record.get("availability")
    if not isinstance(raw_availability, dict):
        raw_availability = {}
    supported_countries = raw_availability.get("supported_countries")
    unsupported_countries = raw_availability.get("unsupported_countries")
    if not isinstance(supported_countries, list):
        supported_countries = [
            code for code, status in raw_availability.items()
            if re.fullmatch(r"[A-Z]{2}", str(code)) and status == "supported"
        ]
    if not isinstance(unsupported_countries, list):
        unsupported_countries = [
            code for code, status in raw_availability.items()
            if re.fullmatch(r"[A-Z]{2}", str(code)) and status == "unsupported"
        ]
    if not supported_countries and not unsupported_countries:
        mainland = record.get("mainland_status")
        if mainland == "supported":
            supported_countries = ["CN"]
        elif mainland == "unsupported":
            unsupported_countries = ["CN"]
    public_availability = {
        "scope": record.get("availability_scope") or raw_availability.get("scope") or "unknown",
        "supported_countries": sorted({str(code) for code in supported_countries if str(code) in ISO2_CODES}),
        "unsupported_countries": sorted({str(code) for code in unsupported_countries if str(code) in ISO2_CODES}),
        "evidence": [],
    }
    for item in raw_availability.get("evidence") or []:
        if not isinstance(item, dict) or item.get("status") not in {"supported", "unsupported"}:
            continue
        country_code = str(item.get("country_code") or "")
        if country_code not in ISO2_CODES:
            continue
        public_availability["evidence"].append({
            "country_code": country_code,
            "status": item["status"],
            "source_url": _safe_url(item.get("source_url")),
            "evidence_excerpt": str(item.get("evidence_excerpt") or "")[:500],
            "verified_at": item.get("verified_at"),
        })
    signup = record.get("signup_requirements")
    if not isinstance(signup, dict):
        signup = {}
    def requirement(name: str, legacy: Any = None) -> str:
        value = signup.get(name)
        if value in {"required", "not_required", "unknown"}:
            return str(value)
        return {"yes": "required", "no": "not_required"}.get(legacy, "unknown")
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
        # v1.4 keeps availability and signup requirements as facts separate
        # from the human-facing presentation.  Preserve unknown values rather
        # than inferring an affirmative availability claim.
        "availability": public_availability,
        "availability_scope": public_availability["scope"],
        "signup_requirements": {
            "card": requirement("card", record.get("requires_card")),
            "phone": requirement("phone", record.get("requires_phone")),
            "identity_verification": requirement("identity_verification"),
            "paid_topup": requirement("paid_topup"),
            "waitlist": requirement("waitlist"),
            "organization": requirement("organization"),
        },
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
    presentations = presentation_for(localized_record)
    stored_presentations = record.get("presentations")
    if isinstance(stored_presentations, dict):
        # Persisted v0.9 presentation rows carry stable short summaries.  Add
        # them without replacing the richer, hand-written guide fields used by
        # existing cards; unknown shapes are deliberately ignored.
        for locale in ("en", "zh-CN"):
            stored = stored_presentations.get(locale)
            if not isinstance(stored, dict):
                continue
            merged = dict(presentations.get(locale) or {})
            summary = stored.get("benefit_summary") or stored.get("summary")
            if (
                isinstance(summary, str)
                and summary.strip()
                # Older collectors may have copied a Chinese eligibility
                # string into the default English presentation.  Do not make
                # that policy prose visible on English public pages.
                and not (locale == "en" and re.search(r"[\u3400-\u9fff]", summary))
            ):
                merged["benefit_summary"] = summary[:2_000]
            title = stored.get("title")
            if isinstance(title, str) and title.strip() and not (locale == "en" and re.search(r"[\u3400-\u9fff]", title)):
                merged["title"] = title[:500]
            eligibility = stored.get("eligibility")
            if isinstance(eligibility, str) and eligibility.strip() and not (locale == "en" and re.search(r"[\u3400-\u9fff]", eligibility)):
                merged["eligibility"] = eligibility[:2_000]
            for source_key, target_key in (("usage_steps", "usage_steps"), ("limitations", "limitations")):
                values = stored.get(source_key)
                if isinstance(values, list):
                    safe_values = [
                        str(value)[:1_000] for value in values
                        if isinstance(value, str) and value.strip()
                        and not (locale == "en" and re.search(r"[\u3400-\u9fff]", value))
                    ]
                    if safe_values:
                        merged[target_key] = safe_values[:20]
            presentations[locale] = merged
    # ``presentation`` is retained for v1.3 browser clients.  New consumers
    # should use the explicitly plural, locale-keyed field.
    public["presentations"] = presentations
    public["presentation"] = presentations
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
        "offer_type": row.get("offer_type"),
        "priority_tier": row.get("priority_tier"),
        "verification_level": row.get("verification_level"),
        "expires_at": row.get("expires_at"),
        "homepage_url": _safe_url(row.get("homepage_url")),
        "status": row.get("status"),
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


def _scenario_directory(pages: Iterable[Any], *, locale: str = "en") -> str:
    """Render crawlable homepage navigation for generated scenario pages."""

    by_slug = {
        page.slug: page
        for page in pages
        if getattr(page, "locale", None) == ("en" if locale == "en" else "zh-CN")
    }
    links: list[str] = []
    for definition in SCENARIOS:
        page = by_slug.get(definition.slug)
        if page is None:
            continue
        language_path = "en" if locale == "en" else "zh"
        relative = f"./{language_path}/scenarios/{definition.slug}/"
        links.append(
            '<a href="{}"><strong>{}</strong><small>{}</small></a>'.format(
                escape(relative, quote=True),
                escape(definition.en_title if locale == "en" else definition.zh_title),
                (f"{int(page.provider_count)} providers · {int(page.resource_count)} resources"
                 if locale == "en" else f"{int(page.provider_count)} 个服务商 · {int(page.resource_count)} 条资源"),
            )
        )
    if not links:
        return ""
    return (
        '<section class="scenario-directory" aria-labelledby="scenario-directory-title">'
        '<div class="section-heading compact"><div><p class="section-kicker">DECISION GUIDES</p>'
        f'<h2 id="scenario-directory-title">{"Find resources for your use case" if locale == "en" else "按你的实际需求找资源"}</h2></div>'
        f'<p>{"Officially verified · updated daily" if locale == "en" else "官方核验 · 每日更新 · 无需逐个翻官网"}</p></div>'
        f'<div class="scenario-directory-list">{"".join(links)}</div></section>'
    )


_ZH_HOMEPAGE_COPY = {
    "health.loading": "读取来源状态", "health.title": "来源核验状态",
    "header.github": "查看 GitHub",
    "nav.free": "免费资源", "nav.prices": "价格榜单",
    "view.recommended": "全部精选", "view.token": "免费 Token", "view.gpu": "免费 GPU",
    "view.grant": "资助活动", "view.tokenPrices": "Token 价格", "view.gpuPrices": "GPU 价格",
    "hero.title": "今天有哪些真正能领的免费 AI 资源？",
    "hero.description": "额度、门槛、领取步骤和官方证据一次看清。", "hero.updated": "数据核验时间",
    "featured.title": "今天最值得领", "featured.note": "不同供应商 · 无需信用卡优先",
    "changes.title": "最近重要变化", "catalog.title": "完整资源目录",
    "catalog.caption": "按供应商、核验、注册门槛和国家可用性筛选。",
    "download.json": "下载 JSON", "download.csv": "下载 CSV", "filters.search": "搜索",
    "filters.searchPlaceholder": "供应商、模型或关键词", "filters.provider": "供应商",
    "filters.allProviders": "全部供应商", "filters.verification": "核验", "filters.all": "全部",
    "filters.official": "仅官方", "filters.community": "社区或待核验", "filters.card": "信用卡",
    "filters.noCard": "无需信用卡", "filters.cardRequired": "需要或待确认",
    "filters.country": "国家代码", "filters.region": "区域预设", "filters.noRegion": "不选择区域",
    "filters.includeUnknownRegion": "包括地区未知",
    "filters.regionNote": "国家与区域互斥；默认只显示已确认支持的资源。",
    "filters.sort": "排序", "filters.clear": "清除筛选", "sort.recommended": "推荐度",
    "sort.updated": "更新时间", "sort.price": "价格从低", "sort.provider": "供应商",
    "status.loading": "正在读取公开数据…", "pager.previous": "上一页", "pager.next": "下一页",
    "footer.readOnly": "公开只读目录，不会代你注册、提交或读取账号。",
    "footer.changes": "变化数据", "footer.health": "来源健康", "footer.github": "GitHub 源码",
}


def _localize_homepage_zh(content: str, *, canonical: str) -> str:
    """Render the Chinese directory as real static HTML, not a JS-only skin."""

    content = content.replace('lang="en"', 'lang="zh-CN"', 1)
    content = content.replace(
        f'<link rel="canonical" href="{canonical}">',
        f'<link rel="canonical" href="{canonical}zh/">',
        1,
    ).replace(
        f'<meta property="og:url" content="{canonical}">',
        f'<meta property="og:url" content="{canonical}zh/">',
        1,
    )
    content = content.replace(
        "AI Resource Radar — verified free AI resources and prices",
        "AI Resource Radar — AI 免费资源与价格雷达",
    ).replace(
        "Daily-verified free AI tokens, GPU compute, grants, and token/GPU prices with requirements and official evidence.",
        "每天核验全球免费 AI Token、GPU、资助与价格，并展示注册门槛和官方证据。",
    ).replace(
        "See quotas, requirements, claim steps, and official evidence in one place.",
        "送什么、门槛是什么、怎么领、证据在哪里，一张卡片看清。",
    )
    content = content.replace(
        "Daily-verified free AI tokens, GPU compute and prices.",
        "每日核验免费 AI Token、GPU 算力与价格。",
    )
    content = content.replace("<strong>AI Resource Radar</strong>", "<strong>免费资源雷达</strong>", 1)
    content = content.replace('<a class="brand" href="./"', '<a class="brand" href="./zh/"', 1)
    content = content.replace(">Skip to content<", ">跳到内容<", 1)
    content = content.replace(">中文</button>", ">English</button>", 1)
    content = content.replace(
        'title="AI Resource Radar English updates"',
        'title="AI Resource Radar 中文更新"',
    ).replace(
        'title="AI Resource Radar English RSS"',
        'title="AI Resource Radar 中文 RSS"',
    )
    content = content.replace("./en/feed.xml", "./feed.xml").replace("./en/rss.xml", "./rss.xml")
    content = content.replace(">Atom feed<", ">Atom 订阅<").replace(">RSS feed<", ">RSS 订阅<")
    content = content.replace(
        "GitHub Watch (releases and maintenance)", "GitHub Watch（版本与维护动态）"
    ).replace(
        "JavaScript is required to read the static catalogue. Provider and scenario pages remain readable without JavaScript.",
        "需要启用 JavaScript 才能读取静态目录；服务商和场景页无需 JavaScript 也可阅读。",
    )
    for key, value in _ZH_HOMEPAGE_COPY.items():
        pattern = rf'(<[^>]+data-i18n="{re.escape(key)}"[^>]*>)(.*?)(</[^>]+>)'
        content = re.sub(pattern, lambda match: match.group(1) + value + match.group(3), content)
        placeholder_pattern = rf'(data-i18n-placeholder="{re.escape(key)}"[^>]*placeholder=")[^"]*(")'
        content = re.sub(placeholder_pattern, lambda match: match.group(1) + value + match.group(2), content)
    return content.replace("<head>", '<head>\n    <base href="../">', 1)


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
    search_console_provider: str = "none",
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
    search_console_markup = _search_console_markup(search_console_provider)
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
    scenario_pages = build_scenario_pages(
        resources,
        integrations,
        base_url=base_url,
        source_revision=revision,
        analytics_script=analytics_script,
        csp=analytics_csp,
        require_minimum=True,
        stylesheet_href=base_url.rstrip("/") + "/scenario.css",
    )
    scenario_urls = [page.url for page in scenario_pages]
    scenario_rows = []
    pages_by_slug: dict[str, list[Any]] = {}
    for page in scenario_pages:
        pages_by_slug.setdefault(page.slug, []).append(page)
    for definition in SCENARIOS:
        localized = pages_by_slug.get(definition.slug, [])
        if len(localized) != 2:
            continue
        representative = localized[0]
        scenario_rows.append(
            {
                "slug": definition.slug,
                "urls": {
                    "zh-CN": next(page.url for page in localized if page.locale == "zh-CN"),
                    "en": next(page.url for page in localized if page.locale == "en"),
                },
                "provider_count": representative.provider_count,
                "resource_count": representative.resource_count,
                "filter_summary": _jsonable(representative.filter_summary),
            }
        )
    data = {
        "manifest": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "dataset": DATASET_ID,
            "package_version": __version__,
            "default_language": "en",
            "supported_languages": ["en", "zh-CN"],
            "region_model_version": REGION_MODEL_VERSION,
            "region_presets": {key: list(value) for key, value in REGION_PRESETS.items()},
            "iso_country_codes": sorted(ISO2_CODES),
            "source_revision": revision,
            "analytics_provider": analytics_provider,
            "search_console_provider": search_console_provider,
            "experiment_started_at": EXPERIMENT_STARTED_AT,
            "scenario_pages": scenario_urls,
            "feeds": [
                base_url.rstrip("/") + "/feed.xml",
                base_url.rstrip("/") + "/rss.xml",
                base_url.rstrip("/") + "/en/feed.xml",
                base_url.rstrip("/") + "/en/rss.xml",
            ],
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
                "scenario_pages": len(scenario_urls),
                "official_verified_resources": sum(
                    row.get("verification_level") in OFFICIAL_LEVELS for row in resources
                ),
                "community_candidates": sum(
                    row.get("verification_level") not in OFFICIAL_LEVELS for row in resources
                ),
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
        "scenarios": {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": generated_at,
            "items": scenario_rows,
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
                content = _inject_search_console(
                    content, markup=search_console_markup
                )
            asset.write_text(content, encoding="utf-8")
        index_path = temp / "index.html"
        base_index_text = index_path.read_text(encoding="utf-8")
        index_text = re.sub(
            r"<!-- AI-RADAR-SCENARIOS:BEGIN -->.*?<!-- AI-RADAR-SCENARIOS:END -->",
            _scenario_directory(scenario_pages, locale="en"),
            base_index_text,
            count=1,
            flags=re.DOTALL,
        )
        index_path.write_text(index_text, encoding="utf-8")
        # The canonical public entry is English.  Retain the historic Chinese
        # snapshot at /zh/ without user profiling or persistent browser state.
        zh_dir = temp / "zh"
        zh_dir.mkdir(exist_ok=True)
        zh_index = _localize_homepage_zh(base_index_text, canonical=canonical)
        zh_index = re.sub(
            r"<!-- AI-RADAR-SCENARIOS:BEGIN -->.*?<!-- AI-RADAR-SCENARIOS:END -->",
            _scenario_directory(scenario_pages, locale="zh-CN"),
            zh_index,
            count=1,
            flags=re.DOTALL,
        )
        zh_dir.joinpath("index.html").write_text(zh_index, encoding="utf-8")
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
        for page in scenario_pages:
            language_path = "en" if page.locale == "en" else "zh"
            destination = temp / language_path / "scenarios" / page.slug
            destination.mkdir(parents=True, exist_ok=True)
            destination.joinpath("index.html").write_text(
                _inject_search_console(page.html, markup=""),
                encoding="utf-8",
            )
            confirmation = destination / "confirm"
            confirmation.mkdir()
            confirmation.joinpath("index.html").write_text(
                _inject_analytics(
                    page.confirmation_html,
                    provider=analytics_provider,
                ),
                encoding="utf-8",
            )
        sitemap_urls = [canonical, canonical + "zh/"] + [
            provider_page_url(base_url, locale, profile.slug)
            for profile in PROVIDER_PROFILES
            for locale in ("zh-CN", "en")
        ] + scenario_urls
        (temp / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"  <url><loc>{url}</loc></url>\n" for url in sitemap_urls)
            + "</urlset>\n",
            encoding="utf-8",
        )
        feeds = build_public_feeds(
            resources,
            changes,
            base_url=base_url,
            now=current,
        )
        for relative, content in feeds.items():
            destination = temp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
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
