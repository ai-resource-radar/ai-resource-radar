"""Small, deterministic Atom/RSS views of the public radar snapshot.

The public site is assembled from JSON-shaped projections rather than from the
SQLite database.  This module intentionally keeps that boundary: callers pass
the ``resources`` and ``changes`` public dictionaries and receive four static
XML strings.  The filtering here is a second, conservative publication gate;
community or unverified records never become feed entries merely because they
were present in an input dictionary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import xml.etree.ElementTree as ET

from ai_resource_radar.provider_pages import public_https_url


DEFAULT_BASE_URL = "https://ai-resource-radar.github.io/ai-resource-radar/"
MAX_ITEMS = 50
RECENT_DAYS = 30
EXPIRY_DAYS = 7
OFFICIAL_LEVELS = frozenset(
    {"official_api", "official_page", "official", "verified", "official_verified"}
)
IMPORTANT_FIELDS = frozenset(
    {
        "quota_value",
        "quota_unit",
        "reset_period",
        "requires_card",
        "expires_at",
        "status",
    }
)
IMPORTANT_CHANGE_TYPES = frozenset(
    {
        "quota_changed",
        "limits_changed",
        "restriction_changed",
        "restriction_change",
        "status_changed",
        "expiring",
    }
)
BASELINE_TYPES = frozenset({"baseline", "initial", "first_seen", "created"})
PRICE_FIELDS = frozenset(
    {
        "price",
        "price_changed",
        "input_per_mtok",
        "output_per_mtok",
        "cache_read_per_mtok",
        "cache_write_per_mtok",
        "hourly_usd",
        "estimated_usd_value",
        "currency",
        "typical_cost",
    }
)
_XML_NAMESPACE = "http://www.w3.org/2005/Atom"
_DROP_HASH_KEYS = frozenset({"id", "change_id", "database_id", "db_id"})
_PRIVATE_QUERY_KEY = re.compile(
    r"(?:user|email|uid|account|session|profile|workspace|tenant|member|customer|org|organization)",
    re.IGNORECASE,
)


def _as_items(value: Any, *, nested_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Extract public rows from a JSON-like wrapper without mutating it."""

    if isinstance(value, Mapping):
        for key in (*nested_keys, "items"):
            candidate = value.get(key)
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
                return [dict(item) for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                nested = _as_items(candidate, nested_keys=nested_keys)
                if nested:
                    return nested
        # A single public record is useful in small integrations and tests.
        record_markers = {
            "offer_id",
            "external_id",
            "provider",
            "title",
            "offer_type",
            "change_type",
            "detected_at",
            "expires_at",
        }
        if record_markers.intersection(value):
            return [dict(value)]
        # Be liberal with ``{"token": [...], "gpu": [...]}``-style input,
        # while never interpreting scalar metadata as a record.
        rows: list[dict[str, Any]] = []
        for candidate in value.values():
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
                rows.extend(dict(item) for item in candidate if isinstance(item, Mapping))
            elif isinstance(candidate, Mapping) and record_markers.intersection(candidate):
                rows.append(dict(candidate))
        return rows
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_time(value: datetime | None) -> datetime:
    parsed = _parse_time(value)
    return parsed or datetime.now(timezone.utc)


def _safe_base_url(value: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid_public_base_url")
    # Reconstruct the authority so a malformed/userinfo-bearing base cannot
    # leak into generated links.  Ports are retained only when parseable.
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError as exc:
        raise ValueError("invalid_public_base_url") from exc
    hostname = _clean_text(parsed.hostname, limit=255)
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    path = _clean_text(parsed.path or "/", limit=2_000)
    if not path.endswith("/"):
        path += "/"
    return urlunparse((parsed.scheme, f"{hostname}{port}", path, "", "", ""))


def _site_url(base_url: str, suffix: str = "") -> str:
    return base_url.rstrip("/") + "/" + suffix.lstrip("/")


def _safe_feed_url(value: Any) -> str:
    """Apply the shared URL policy plus a feed-specific privacy scrub."""

    safe = public_https_url(value)
    if not safe:
        return ""
    parsed = urlparse(safe)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not _PRIVATE_QUERY_KEY.search(key)
        ],
        doseq=True,
    )
    return urlunparse(("https", parsed.netloc, parsed.path, parsed.params, query, ""))[:1_000]


def _clean_text(value: Any, *, limit: int = 2_000) -> str:
    """Bound text and remove code points forbidden in XML 1.0."""

    text = "" if value is None else str(value)
    allowed: list[str] = []
    for char in text:
        code = ord(char)
        if code in (0x09, 0x0A, 0x0D) or code >= 0x20:
            # XML 1.0 also rejects surrogate code points.  They are rare in
            # Python strings but can arrive from a malformed upstream page.
            if not 0xD800 <= code <= 0xDFFF:
                allowed.append(char)
    return "".join(allowed)[:limit]


def _normalise(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Create a bounded canonical object for content-addressed IDs."""

    if depth > 5:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item).casefold()):
            child_key = str(raw_key)
            if child_key.casefold() in _DROP_HASH_KEYS:
                continue
            result[child_key[:80]] = _normalise(value[raw_key], key=child_key, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_normalise(item, depth=depth + 1) for item in value]
        # changed_fields is a set-like list in the public schema.  Sorting only
        # scalar values makes the ID independent of source ordering while
        # retaining order for structured before/after values.
        if all(isinstance(item, (str, int, float, bool, type(None))) for item in items):
            items.sort(key=lambda item: str(item))
        return items[:100]
    if isinstance(value, str):
        return _clean_text(value, limit=2_000).strip()
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clean_text(value, limit=500)


def _stable_id(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _normalise(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "urn:sha256:" + hashlib.sha256(canonical).hexdigest()


def _value(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _resource_key(item: Mapping[str, Any]) -> str:
    value = _value(item, "offer_id", "external_id", "resource_id")
    if value not in (None, ""):
        return "id:" + _clean_text(value, limit=300)
    provider = _clean_text(_value(item, "provider") or "", limit=200).casefold()
    title = _clean_text(_value(item, "title", "model", "gpu_model") or "", limit=300).casefold()
    return "name:" + provider + "|" + title if provider or title else ""


def _name_key(item: Mapping[str, Any]) -> str:
    provider = _clean_text(_value(item, "provider") or "", limit=200).casefold()
    title = _clean_text(_value(item, "title", "model", "gpu_model") or "", limit=300).casefold()
    return "name:" + provider + "|" + title if provider or title else ""


def _verification_values(item: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("verification_level", "verification_status", "verification", "authority", "source_authority"):
        value = item.get(key)
        if value not in (None, ""):
            values.append(str(value).strip().casefold())
    for key in ("evidence", "source"):
        nested = item.get(key)
        if isinstance(nested, Mapping):
            values.extend(_verification_values(nested))
    return values


def _is_publicly_verified(item: Mapping[str, Any], resource: Mapping[str, Any] | None = None) -> bool:
    values = _verification_values(item)
    if resource is not None:
        values.extend(_verification_values(resource))
    if values:
        # Any explicit non-official authority wins.  A row with both an
        # official evidence level and a community discovery marker remains
        # untrusted for this publication surface.
        if any(
            value in {"community", "unverified", "unknown", "pending", "verification_pending", "not_verified"}
            or "community" in value
            or "unverified" in value
            or "pending" in value
            or "未核验" in value
            or "未验证" in value
            for value in values
        ):
            return False
        return any(value in OFFICIAL_LEVELS for value in values)
    # list_changes historically omitted verification_level.  A/B is assigned
    # only to official, free offers, so it is the safe compatibility fallback
    # for changes (including removals whose resource is no longer active).
    tier = str(item.get("priority_tier") or (resource or {}).get("priority_tier") or "").strip().upper()
    return tier in {"A", "B"}


def _is_ab_tier(item: Mapping[str, Any], resource: Mapping[str, Any] | None = None) -> bool:
    """Reject an explicitly non-A/B row while tolerating old rows without tier."""

    raw = item.get("priority_tier")
    if raw in (None, "") and resource is not None:
        raw = resource.get("priority_tier")
    if raw in (None, ""):
        return True
    return str(raw).strip().upper() in {"A", "B"}


def _changed_fields(item: Mapping[str, Any]) -> set[str]:
    raw = _value(item, "changed_fields", "fields", "changed")
    values: set[str] = set()
    if isinstance(raw, str) and raw.lstrip()[:1] in {"[", "{"}:
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, (Mapping, list, tuple, set, frozenset)):
            raw = decoded
    if isinstance(raw, Mapping):
        values.update(str(key).strip().casefold() for key in raw)
    elif isinstance(raw, (list, tuple, set, frozenset)):
        values.update(str(value).strip().casefold() for value in raw)
    elif raw not in (None, ""):
        values.update(part.strip().casefold() for part in str(raw).split(","))
    # Some integrations provide before/after objects but no changed_fields.
    for key in ("before", "after", "before_json", "after_json"):
        nested = item.get(key)
        if isinstance(nested, Mapping):
            values.update(str(field).strip().casefold() for field in nested)
    return {value for value in values if value}


def _is_baseline(item: Mapping[str, Any]) -> bool:
    for key in (
        "baseline",
        "is_baseline",
        "initial_baseline",
        "first_seen",
        "is_initial",
        "is_first",
        "first_event",
        "initial",
    ):
        value = item.get(key)
        if value is True or value == 1 or (
            isinstance(value, str)
            and value.strip().casefold() in {"true", "yes", "1", "baseline", "initial"}
        ):
            return True
    change_type = str(item.get("change_type") or item.get("type") or "").strip().casefold()
    return change_type in BASELINE_TYPES


def _is_important_change(item: Mapping[str, Any]) -> bool:
    if _is_baseline(item):
        return False
    change_type = str(item.get("change_type") or item.get("type") or "").strip().casefold()
    fields = _changed_fields(item)
    if change_type in {"added", "removed"}:
        return True
    if change_type in IMPORTANT_CHANGE_TYPES:
        return True
    if fields and fields.issubset(PRICE_FIELDS):
        return False
    if str(item.get("importance") or "").strip().casefold() in {"high", "critical"}:
        return True
    if fields.intersection(IMPORTANT_FIELDS):
        return True
    # Generic updates with no allow-listed field are not useful in a public
    # feed, even when they are otherwise well-formed.
    return False


def _event_time(item: Mapping[str, Any], *, fallback: datetime) -> datetime:
    for key in ("detected_at", "changed_at", "updated_at", "observed_at", "created_at"):
        parsed = _parse_time(item.get(key))
        if parsed is not None:
            return parsed
    return fallback


def _display_name(item: Mapping[str, Any]) -> tuple[str, str]:
    provider = _clean_text(_value(item, "provider") or "AI Resource Radar", limit=200)
    title = _clean_text(_value(item, "title", "model", "gpu_model") or item.get("offer_id") or "Resource", limit=300)
    return provider, title


def _external_link(item: Mapping[str, Any], *, locale: str, base_url: str, anchor: str) -> str:
    # A decorated public resource may carry locale-specific provider URLs.
    urls = item.get("provider_urls")
    if isinstance(urls, Mapping):
        if locale == "en":
            candidate = urls.get("en")
        else:
            candidate = urls.get("zh-CN") or urls.get("zh")
        candidate = candidate or urls.get("zh-CN") or urls.get("zh") or urls.get("en")
        safe = _safe_feed_url(candidate)
        if safe:
            return safe
    for key in ("provider_url", "homepage_url", "url", "source_url", "pricing_url"):
        safe = _safe_feed_url(item.get(key))
        if safe:
            return safe
    slug = _value(item, "provider_slug", "slug")
    if slug:
        safe_slug = "".join(char for char in str(slug) if char.isalnum() or char in {"-", "_"})[:100]
        if safe_slug:
            return _site_url(base_url, f"{'en' if locale == 'en' else 'zh'}/providers/{safe_slug}/")
    return _site_url(base_url, anchor)


def _field_labels(fields: Iterable[str], *, locale: str) -> list[str]:
    labels = {
        "zh": {
            "quota_value": "额度数值",
            "quota_unit": "额度单位",
            "reset_period": "重置周期",
            "requires_card": "信用卡要求",
            "expires_at": "到期时间",
            "status": "状态",
        },
        "en": {
            "quota_value": "quota value",
            "quota_unit": "quota unit",
            "reset_period": "reset period",
            "requires_card": "card requirement",
            "expires_at": "expiry",
            "status": "status",
        },
    }
    table = labels["en" if locale == "en" else "zh"]
    return [table.get(field, field) for field in sorted(set(fields))]


def _prepare_entries(
    resources_value: Any,
    changes_value: Any,
    *,
    now: datetime,
    base_url: str,
) -> list[dict[str, Any]]:
    resources = _as_items(resources_value, nested_keys=("resources", "offers"))
    changes = _as_items(changes_value, nested_keys=("changes", "important_changes"))
    by_key = {_resource_key(resource): resource for resource in resources if _resource_key(resource)}
    by_name = {_name_key(resource): resource for resource in resources if _name_key(resource)}
    entries: list[dict[str, Any]] = []
    cutoff = now - timedelta(days=RECENT_DAYS)
    for change in changes:
        event_time = _event_time(change, fallback=now)
        if event_time < cutoff or event_time > now:
            continue
        key = _resource_key(change)
        source_has_id = _value(change, "offer_id", "external_id", "resource_id") not in (None, "")
        embedded = change.get("resource")
        resource = (
            by_key.get(key)
            or by_name.get(_name_key(change))
            or (dict(embedded) if isinstance(embedded, Mapping) else None)
        )
        if (
            not _is_ab_tier(change, resource)
            or not _is_publicly_verified(change, resource)
            or not _is_important_change(change)
        ):
            continue
        merged = dict(resource or {})
        merged.update({key: value for key, value in change.items() if value is not None})
        provider, title = _display_name(merged)
        fields = _changed_fields(change)
        change_type = str(change.get("change_type") or change.get("type") or "updated").strip().casefold()
        raw_fields = _value(change, "changed_fields", "fields", "changed")
        field_values = {
            field: _value(change, field) if _value(change, field) is not None else _value(resource or {}, field)
            for field in sorted(fields.intersection(IMPORTANT_FIELDS))
        }
        if isinstance(raw_fields, Mapping):
            field_values.update(
                {
                    field: raw_fields[field]
                    for field in fields.intersection(IMPORTANT_FIELDS)
                    if field in raw_fields
                }
            )
        payload = {
            "kind": "change",
            "offer_id": _value(change, "offer_id", "external_id") or _value(resource or {}, "offer_id", "external_id"),
            "provider": provider,
            "title": title,
            "change_type": change_type,
            "changed_fields": sorted(fields),
            "field_values": field_values,
            "before": change.get("before") or change.get("before_json"),
            "after": change.get("after") or change.get("after_json"),
            "detected_at": event_time.isoformat(),
        }
        stable_id = _stable_id(payload)
        entries.append(
            {
                "kind": "change",
                "stable_id": stable_id,
                "dedupe_key": key or stable_id,
                "source_has_id": source_has_id,
                "timestamp": event_time,
                "provider": provider,
                "title": title,
                "change_type": change_type,
                "fields": fields,
                "expires_at": _value(change, "expires_at") or _value(resource or {}, "expires_at"),
                "link_item": merged,
                "hash_payload": payload,
            }
        )

    changed_keys: set[str] = set()
    unidentified_changed_names: set[str] = set()
    for entry in entries:
        if entry["dedupe_key"]:
            changed_keys.add(entry["dedupe_key"])
        if not entry.get("source_has_id"):
            unidentified_changed_names.add(_name_key(entry["link_item"]))
    expiry_end = now + timedelta(days=EXPIRY_DAYS)
    for resource in resources:
        if (
            not _is_ab_tier(resource)
            or not _is_publicly_verified(resource)
            or _resource_key(resource) in changed_keys
            or (
                not _resource_key(resource).startswith("id:")
                and _name_key(resource) in unidentified_changed_names
            )
        ):
            continue
        status = str(resource.get("status") or "active").strip().casefold()
        if status in {"inactive", "removed", "expired", "disabled"}:
            continue
        expires = _parse_time(resource.get("expires_at"))
        if expires is None or expires < now or expires > expiry_end:
            continue
        provider, title = _display_name(resource)
        key = _resource_key(resource)
        payload = {
            "kind": "expiry",
            "offer_id": _value(resource, "offer_id", "external_id"),
            "provider": provider,
            "title": title,
            "expires_at": expires.isoformat(),
        }
        stable_id = _stable_id(payload)
        entries.append(
            {
                "kind": "expiry",
                "stable_id": stable_id,
                "dedupe_key": key or stable_id,
                "timestamp": now,
                "provider": provider,
                "title": title,
                "change_type": "expiring",
                "fields": {"expires_at"},
                "expires_at": expires.isoformat(),
                "link_item": resource,
                "hash_payload": payload,
            }
        )

    # Same normalized event may occur twice when a database row is joined with
    # more than one public evidence row.  Keep one before applying the cap.
    unique: dict[str, dict[str, Any]] = {}
    for entry in entries:
        unique.setdefault(entry["stable_id"], entry)
    entries = list(unique.values())
    entries.sort(key=lambda item: (-item["timestamp"].timestamp(), item["kind"], item["stable_id"]))
    return entries[:MAX_ITEMS]


def _entry_title(entry: Mapping[str, Any], *, locale: str) -> str:
    provider = entry["provider"]
    title = entry["title"]
    if entry["kind"] == "expiry":
        return f"即将到期：{provider} · {title}" if locale != "en" else f"Expiring soon: {provider} · {title}"
    labels = {"added": ("新增", "Added"), "removed": ("移除", "Removed")}
    label = labels.get(entry["change_type"], ("重要变化", "Important change"))[0 if locale != "en" else 1]
    return f"{label}：{provider} · {title}" if locale != "en" else f"{label}: {provider} · {title}"


def _entry_summary(entry: Mapping[str, Any], *, locale: str) -> str:
    if entry["kind"] == "expiry":
        expires = _clean_text(entry.get("expires_at") or "", limit=80)
        return (
            f"{entry['provider']} 的 {entry['title']} 将于 {expires} 到期。请在官方页面核验。"
            if locale != "en"
            else (
                f"{entry['provider']} · {entry['title']} expires at {expires}. "
                "Verify on the official page."
            )
        )
    labels = _field_labels(entry.get("fields", ()), locale=locale)
    if entry["change_type"] == "added":
        detail = "已加入公开资源目录。" if locale != "en" else "was added to the public resource catalog."
    elif entry["change_type"] == "removed":
        detail = (
            "已从公开资源目录移除。"
            if locale != "en"
            else "was removed from the public resource catalog."
        )
    else:
        detail = (
            "变化字段：" + "、".join(labels) + "。"
            if locale != "en"
            else "Changed fields: " + ", ".join(labels) + "."
        )
    return f"{entry['provider']} · {entry['title']} {detail}"


def _feed_meta(*, locale: str, base_url: str, kind: str) -> tuple[str, str, str, str]:
    chinese = locale != "en"
    title = (
        "AI Resource Radar 重要变化与到期提醒"
        if chinese
        else "AI Resource Radar important changes and expiry reminders"
    )
    description = (
        "最近 30 天的官方 A/B 资源重要变化，以及未来 7 天内到期提醒。"
        if chinese
        else "Official A/B resource changes from the last 30 days and expiry reminders for the next 7 days."
    )
    suffix = f"{'' if chinese else 'en/'}{'feed.xml' if kind == 'atom' else 'rss.xml'}"
    return title, description, _site_url(base_url, suffix), "zh-CN" if chinese else "en"


def _atom_xml(entries: Sequence[Mapping[str, Any]], *, locale: str, base_url: str, now: datetime) -> str:
    ET.register_namespace("", _XML_NAMESPACE)
    title, description, self_url, language = _feed_meta(locale=locale, base_url=base_url, kind="atom")
    root = ET.Element(f"{{{_XML_NAMESPACE}}}feed")
    _xml_add(root, "title", title)
    _xml_add(root, "id", self_url)
    _xml_add(root, "updated", _rfc3339(now))
    ET.SubElement(
        root,
        f"{{{_XML_NAMESPACE}}}link",
        href=_clean_text(self_url, limit=2_000),
        rel="self",
        type="application/atom+xml",
    )
    _xml_add(root, "subtitle", description)
    for entry in entries:
        node = ET.SubElement(root, f"{{{_XML_NAMESPACE}}}entry")
        _xml_add(node, "title", _entry_title(entry, locale=locale))
        _xml_add(node, "id", entry["stable_id"])
        href = _external_link(
            entry["link_item"],
            locale=locale,
            base_url=base_url,
            anchor="#changes" if entry["kind"] == "change" else "#resources",
        )
        ET.SubElement(
            node,
            f"{{{_XML_NAMESPACE}}}link",
            href=_clean_text(href, limit=2_000),
            rel="alternate",
        )
        timestamp = entry["timestamp"] if isinstance(entry["timestamp"], datetime) else now
        _xml_add(node, "updated", _rfc3339(timestamp))
        _xml_add(node, "published", _rfc3339(timestamp))
        _xml_add(node, "summary", _entry_summary(entry, locale=locale), type="text")
        category = "expiry" if entry["kind"] == "expiry" else "change"
        _xml_add(node, "category", category, term=category)
        if entry["kind"] == "expiry":
            _xml_add(node, "category", "expires_at", term="expires_at")
        if entry["kind"] == "change":
            for field in sorted(set(entry.get("fields", ())).intersection(IMPORTANT_FIELDS)):
                _xml_add(node, "category", field, term=field)
    return _xml_string(root)


def _rss_xml(entries: Sequence[Mapping[str, Any]], *, locale: str, base_url: str, now: datetime) -> str:
    title, description, self_url, language = _feed_meta(locale=locale, base_url=base_url, kind="rss")
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    _xml_add(channel, "title", title)
    _xml_add(channel, "link", _site_url(base_url, "en/" if locale == "en" else ""))
    _xml_add(channel, "description", description)
    _xml_add(channel, "language", language)
    _xml_add(channel, "lastBuildDate", format_datetime(now, usegmt=True))
    _xml_add(channel, "generator", "AI Resource Radar")
    _xml_add(channel, "docs", "https://www.rssboard.org/rss-specification")
    for entry in entries:
        node = ET.SubElement(channel, "item")
        _xml_add(node, "title", _entry_title(entry, locale=locale))
        href = _external_link(
            entry["link_item"],
            locale=locale,
            base_url=base_url,
            anchor="#changes" if entry["kind"] == "change" else "#resources",
        )
        _xml_add(node, "link", href)
        _xml_add(node, "guid", entry["stable_id"], isPermaLink="false")
        timestamp = entry["timestamp"] if isinstance(entry["timestamp"], datetime) else now
        _xml_add(node, "pubDate", format_datetime(timestamp, usegmt=True))
        _xml_add(node, "description", _entry_summary(entry, locale=locale))
        category = "expiry" if entry["kind"] == "expiry" else "change"
        _xml_add(node, "category", category)
        if entry["kind"] == "expiry":
            _xml_add(node, "category", "expires_at")
        if entry["kind"] == "change":
            for field in sorted(set(entry.get("fields", ())).intersection(IMPORTANT_FIELDS)):
                _xml_add(node, "category", field)
    return _xml_string(root)


def _xml_add(parent: ET.Element, tag: str, text: Any = None, **attrs: Any) -> ET.Element:
    safe_attrs = {key: _clean_text(value, limit=2_000) for key, value in attrs.items()}
    element = ET.SubElement(parent, tag, safe_attrs)
    element.text = _clean_text(text, limit=20_000)
    return element


def _xml_string(root: ET.Element) -> str:
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_public_feeds(
    resources: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    changes: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    base_url: str = DEFAULT_BASE_URL,
    now: datetime | None = None,
) -> dict[str, str]:
    """Render bilingual Atom and RSS strings from public JSON projections.

    The returned keys are stable and intentionally match the static paths used
    by the public site: ``feed.xml``, ``rss.xml``, ``en/feed.xml``, and
    ``en/rss.xml``.  Empty or missing inputs are valid and yield well-formed
    feeds with no ``entry``/``item`` children.
    """

    # Accept a complete public snapshot as a convenience for callers that
    # already hold ``{"resources": ..., "changes": ...}`` together.
    if changes is None and isinstance(resources, Mapping) and "changes" in resources:
        snapshot = resources
        resources = snapshot.get("resources")
        changes = snapshot.get("changes")
    safe_base = _safe_base_url(base_url)
    current = _current_time(now)
    entries = _prepare_entries(resources or {}, changes or {}, now=current, base_url=safe_base)
    return {
        "feed.xml": _atom_xml(entries, locale="zh-CN", base_url=safe_base, now=current),
        "rss.xml": _rss_xml(entries, locale="zh-CN", base_url=safe_base, now=current),
        "en/feed.xml": _atom_xml(entries, locale="en", base_url=safe_base, now=current),
        "en/rss.xml": _rss_xml(entries, locale="en", base_url=safe_base, now=current),
    }


# Names used by early integrations are kept as tiny aliases; all return the
# dictionary form above so callers cannot accidentally swap the four strings.
render_public_feeds = build_public_feeds
render_feeds = build_public_feeds


__all__ = [
    "DEFAULT_BASE_URL",
    "EXPIRY_DAYS",
    "IMPORTANT_FIELDS",
    "MAX_ITEMS",
    "RECENT_DAYS",
    "build_public_feeds",
    "render_feeds",
    "render_public_feeds",
]
