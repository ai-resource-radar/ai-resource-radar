"""Static, crawlable scenario pages for the public radar snapshot.

The public site exporter passes already-sanitised rows to this module.  The
selection rules live here so a community record cannot be promoted by the
page renderer and so the same rules can be exercised with small fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .provider_pages import public_https_url


OFFICIAL_LEVELS = frozenset({"official_api", "official_page"})
PRIORITY_LEVELS = frozenset({"A", "B"})
FREE_OFFER_TYPES = frozenset({"recurring_free", "variable_free", "grant"})
SCENARIO_PAGE_MIN_RESOURCES = 3
SCENARIO_PAGE_MIN_PROVIDERS = 3


@dataclass(frozen=True)
class ScenarioDefinition:
    """Stable copy and selection predicate for one scenario page."""

    slug: str
    zh_title: str
    en_title: str
    zh_description: str
    en_description: str
    kind: str = "token"
    free_image: bool = False
    requires_card: str | None = None
    recurring: bool = False
    mainland_supported: bool = False
    openai_compatible: bool = False

    def title(self, locale: str) -> str:
        return self.en_title if _locale(locale) == "en" else self.zh_title

    def description(self, locale: str) -> str:
        return self.en_description if _locale(locale) == "en" else self.zh_description


# Keep this order and the slugs stable.  They are part of the public URL
# contract and are intentionally not derived from translated copy.
SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition(
        "free-ai-api-no-card", "无需信用卡的免费 AI API", "Free AI APIs with no card",
        "只展示无需信用卡、官方已核验的免费 AI API。",
        "Officially verified free AI APIs that do not require a card.",
        requires_card="no",
    ),
    ScenarioDefinition(
        "recurring-free-ai-api", "可持续周期免费的 AI API", "Recurring-free AI APIs",
        "按周期恢复额度的免费 AI API，适合持续试用。",
        "Free AI APIs whose allowance renews on a recurring schedule.", recurring=True,
    ),
    ScenarioDefinition(
        "free-gpu-compute", "免费 GPU 计算", "Free GPU compute",
        "官方已核验的免费 GPU 计算、试用和额度。",
        "Officially verified free GPU compute, trials and credits.", kind="gpu",
    ),
    ScenarioDefinition(
        "mainland-supported-free-ai-api", "中国大陆可用的免费 AI API",
        "Free AI APIs supported in mainland China",
        "严格依据官方 supported 标记筛选中国大陆可用的免费 AI API。",
        "Free AI APIs selected only when the official mainland status is supported.",
        mainland_supported=True,
    ),
    ScenarioDefinition(
        "free-image-generation-api", "免费图像生成 API", "Free image-generation APIs",
        "明确提供免费图像生成能力的官方 API。",
        "Official APIs with an explicitly verified free image-generation capability.", free_image=True,
    ),
    ScenarioDefinition(
        "openai-compatible-free-ai-api", "兼容 OpenAI Chat Completions 的免费 AI API",
        "Free AI APIs compatible with OpenAI Chat Completions",
        "仅收录已核验 chat_completions 协议的免费 API。",
        "Only free APIs with verified chat_completions compatibility are included.", openai_compatible=True,
    ),
)

SCENARIO_BY_SLUG: dict[str, ScenarioDefinition] = {item.slug: item for item in SCENARIOS}
# Descriptive alias for callers that prefer the longer name.
SCENARIO_DEFINITIONS = SCENARIOS
SCENARIO_SLUGS: tuple[str, ...] = tuple(item.slug for item in SCENARIOS)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ScenarioPageError(ValueError):
    """Raised when a scenario cannot satisfy its public publication gate."""


def _locale(locale: str) -> str:
    return "en" if str(locale or "").lower().startswith("en") else "zh-CN"


def get_scenario(slug: str | ScenarioDefinition) -> ScenarioDefinition:
    """Resolve a scenario definition by its stable slug."""

    if isinstance(slug, ScenarioDefinition):
        return slug
    key = str(slug or "").strip()
    try:
        return SCENARIO_BY_SLUG[key]
    except KeyError as exc:
        raise ScenarioPageError(f"unknown_scenario:{key}") from exc


def scenario_page_url(base_url: str, locale: str, slug: str) -> str:
    """Return a canonical bilingual scenario URL."""

    definition = get_scenario(slug)
    language = "en" if _locale(locale) == "en" else "zh"
    return f"{str(base_url).rstrip('/')}/{language}/scenarios/{definition.slug}/"


def scenario_confirmation_url(base_url: str, locale: str, slug: str) -> str:
    """Return the noindex confirmation URL for a scenario."""

    definition = get_scenario(slug)
    language = "en" if _locale(locale) == "en" else "zh"
    return f"{str(base_url).rstrip('/')}/{language}/scenarios/{definition.slug}/confirm/"


def _value(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key, default)
    if value is None and key == "verification_level":
        evidence = row.get("evidence")
        if isinstance(evidence, Mapping):
            return evidence.get(key, default)
    return value


def _is_active(row: Mapping[str, Any]) -> bool:
    """Apply the active gate while remaining compatible with public rows."""

    # _resource in older public snapshots omits database status.  Missing
    # status consequently means the row is from the active projection;
    # explicit inactive values are always rejected.
    status = row.get("status")
    if status is not None and str(status).strip().lower() not in {"active", "current"}:
        return False
    if "is_active" in row:
        value = row.get("is_active")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "active"}
        return bool(value)
    if "active" in row:
        value = row.get("active")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "active"}
        return bool(value)
    return True


def _official_a_or_b_active(row: Mapping[str, Any]) -> bool:
    return (
        _is_active(row)
        and str(_value(row, "verification_level") or "") in OFFICIAL_LEVELS
        and str(row.get("priority_tier") or "").upper() in PRIORITY_LEVELS
    )


def _free(row: Mapping[str, Any]) -> bool:
    offer_type = str(row.get("offer_type") or "").strip().lower()
    if offer_type:
        return offer_type in FREE_OFFER_TYPES
    # Some direct callers provide only a boolean free marker.  It is accepted
    # only when no contradictory offer type is present.
    marker = row.get("free")
    if isinstance(marker, str):
        marker = marker.strip().lower() in {"1", "true", "yes", "free"}
    return bool(marker)


def _is_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _provider_key(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("provider_slug") or "").strip()
    if explicit:
        return explicit.casefold()
    provider = str(row.get("provider") or "").strip()
    if provider:
        try:
            from .provider_profiles import provider_slug_for

            resolved = provider_slug_for(provider=provider)
        except (ImportError, AttributeError):
            resolved = None
        if resolved:
            return resolved.casefold()
    return provider.casefold()


def _canonical_provider_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from .provider_profiles import provider_slug_for

        resolved = provider_slug_for(provider=text)
    except (ImportError, AttributeError):
        resolved = None
    return str(resolved or text).casefold()


def _safe_external_url(value: Any) -> str:
    """Return a credential-free HTTPS URL for an external link."""

    return public_https_url(value)


def _presentation(row: Mapping[str, Any], locale: str) -> Mapping[str, Any]:
    catalog = row.get("presentations") or row.get("presentation")
    if not isinstance(catalog, Mapping):
        return {}
    value = catalog.get(locale)
    if isinstance(value, Mapping):
        return value
    # A few older direct fixtures use ``zh`` as their key.
    value = catalog.get("zh") if locale != "en" else catalog.get("en")
    if isinstance(value, Mapping):
        return value
    if locale == "en":
        return {
            "benefit_summary": "See the official page for the current public policy.",
            "usage_steps": ["Open the official page and follow the account instructions."],
        }
    return {}


def _evidence(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("evidence")
    return value if isinstance(value, Mapping) else {}


def _observed_at(row: Mapping[str, Any]) -> str:
    evidence = _evidence(row)
    return str(
        evidence.get("observed_at")
        or row.get("verified_at")
        or row.get("last_seen_at")
        or ""
    ).strip()


def _materialize_rows(value: Iterable[Mapping[str, Any]] | Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Accept a plain list or one of the public ``{"items": [...]}`` wrappers."""

    if isinstance(value, Mapping):
        candidate = value.get("items")
        if isinstance(candidate, (list, tuple)):
            return [item for item in candidate if isinstance(item, Mapping)]
        return [value] if any(key in value for key in ("offer_id", "price_id", "provider")) else []
    return [item for item in value if isinstance(item, Mapping)]


def _integration_provider_keys(
    integrations: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> set[str]:
    if integrations is None:
        return set()
    if isinstance(integrations, Mapping):
        values: Iterable[Any] = integrations.get("items", integrations.values())
    else:
        values = integrations
    keys: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        if any(key in item for key in ("integration_verified", "verified", "active")):
            verified = item.get("integration_verified", item.get("verified", item.get("active")))
        else:
            # ``integration_public_rows`` omits a redundant boolean but emits
            # templates only for its verified-only projection.
            verified = bool(item.get("templates") or item.get("integrations"))
        if isinstance(verified, str):
            verified = verified.strip().lower() in {"1", "true", "yes", "verified", "active"}
        if not verified:
            continue
        protocols: list[str] = []
        raw_protocols = item.get("protocols")
        if isinstance(raw_protocols, (list, tuple, set)):
            protocols.extend(str(value).strip().lower() for value in raw_protocols)
        if item.get("protocol"):
            protocols.append(str(item["protocol"]).strip().lower())
        compatibility = item.get("compatibility")
        if isinstance(compatibility, Mapping):
            if compatibility.get("chat_completions") or compatibility.get("supports_chat_completions"):
                protocols.append("chat_completions")
            raw = compatibility.get("protocols")
            if isinstance(raw, (list, tuple, set)):
                protocols.extend(str(value).strip().lower() for value in raw)
        if "chat_completions" not in protocols and not item.get("supports_chat_completions"):
            continue
        key = _canonical_provider_value(item.get("provider_slug") or item.get("slug") or item.get("provider"))
        if key:
            keys.add(key)
    return keys


def _row_chat_compatible(row: Mapping[str, Any]) -> bool:
    """Accept explicit row compatibility metadata for direct callers."""

    verified = row.get("integration_verified", row.get("verified", False))
    if isinstance(verified, str):
        verified = verified.strip().lower() in {"1", "true", "yes", "verified", "active"}
    if not verified:
        return False
    protocols: list[str] = []
    raw = row.get("protocols")
    if isinstance(raw, (list, tuple, set)):
        protocols.extend(str(value).strip().lower() for value in raw)
    if row.get("protocol"):
        protocols.append(str(row["protocol"]).strip().lower())
    compatibility = row.get("compatibility")
    if isinstance(compatibility, Mapping):
        if compatibility.get("chat_completions") or compatibility.get("supports_chat_completions"):
            return True
        raw = compatibility.get("protocols")
        if isinstance(raw, (list, tuple, set)):
            protocols.extend(str(value).strip().lower() for value in raw)
    return "chat_completions" in protocols or bool(row.get("supports_chat_completions"))


def scenario_rows(
    scenario: str | ScenarioDefinition,
    resources: Iterable[Mapping[str, Any]],
    *,
    integrations: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    require_minimum: bool = False,
) -> list[dict[str, Any]]:
    """Filter resources according to one scenario's publication rules.

    Returned rows are shallow copies and are sorted deterministically by
    provider, title and offer ID.  ``require_minimum`` is useful to publication
    callers; tests and dashboards can inspect a smaller result set by leaving
    it false.
    """

    definition = get_scenario(scenario)
    chat_providers = _integration_provider_keys(integrations)
    selected: list[dict[str, Any]] = []
    for item in _materialize_rows(resources):
        row = dict(item)
        if not _official_a_or_b_active(row) or not _free(row):
            continue
        if str(row.get("kind") or "").strip().lower() != definition.kind:
            continue
        if definition.requires_card is not None and str(row.get("requires_card") or "").lower() != definition.requires_card:
            continue
        if definition.recurring and str(row.get("offer_type") or "").lower() != "recurring_free":
            continue
        # The historical mainland scenario is now the CN specialization of
        # the generic country model.  Legacy rows remain readable, but an
        # explicit schema-v8 country assertion takes precedence.
        if definition.mainland_supported and _country_status(row, "CN") != "supported":
            continue
        if definition.free_image and not _is_true(row.get("free_image_generation")):
            continue
        if definition.openai_compatible:
            provider = _provider_key(row)
            compatible = provider in chat_providers
            if not compatible and integrations is None:
                compatible = _row_chat_compatible(row)
                if not compatible:
                    # The canonical provider registry is an additional safe
                    # fallback for callers that pass public resources but no
                    # separate integrations projection.
                    try:
                        from .provider_profiles import PROVIDER_BY_SLUG

                        profile = PROVIDER_BY_SLUG.get(provider)
                    except (ImportError, AttributeError):
                        profile = None
                    compatible = bool(
                        profile
                        and profile.integration_verified
                        and profile.supports_chat_completions
                    )
            if not provider or not compatible:
                continue
        selected.append(row)
    selected.sort(
        key=lambda row: (
            str(row.get("provider") or row.get("provider_slug") or "").casefold(),
            str(row.get("title") or "").casefold(),
            str(row.get("offer_id") or row.get("price_id") or ""),
        )
    )
    if require_minimum:
        _ensure_minimum(definition, selected)
    return selected


def _country_status(row: Mapping[str, Any], country: str) -> str:
    availability = row.get("availability")
    if isinstance(availability, Mapping):
        supported = {
            str(value).strip().upper()
            for value in availability.get("supported_countries", ())
        }
        unsupported = {
            str(value).strip().upper()
            for value in availability.get("unsupported_countries", ())
        }
        code = country.strip().upper()
        if code in unsupported:
            return "unsupported"
        if code in supported:
            return "supported"
        if str(availability.get("scope") or "").strip().lower() == "global":
            return "supported"
        # A schema-v8 projection is authoritative even when it contains no
        # assertion for this country; absence means unknown.
        return "unknown"
    return str(row.get("mainland_status") or "unknown").strip().lower()


def aggregate_providers(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate scenario rows by provider without losing resource evidence."""

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _provider_key(row)
        if not key:
            continue
        bucket = grouped.setdefault(
            key,
            {
                "provider": row.get("provider") or row.get("provider_slug") or key,
                "provider_slug": row.get("provider_slug"),
                "resources": [],
                "resource_count": 0,
            },
        )
        bucket["resources"].append(dict(row))
        bucket["resource_count"] = len(bucket["resources"])
    return sorted(grouped.values(), key=lambda item: str(item["provider"]).casefold())


aggregate_provider_rows = aggregate_providers


def _ensure_minimum(definition: ScenarioDefinition, rows: Sequence[Mapping[str, Any]]) -> None:
    providers = {_provider_key(row) for row in rows if _provider_key(row)}
    if len(rows) < SCENARIO_PAGE_MIN_RESOURCES or len(providers) < SCENARIO_PAGE_MIN_PROVIDERS:
        raise ScenarioPageError(
            f"scenario_minimum_not_met:{definition.slug}:resources={len(rows)}:providers={len(providers)}"
        )


def scenario_catalog(
    resources: Iterable[Mapping[str, Any]],
    *,
    integrations: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    require_minimum: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Build scenario result sets keyed by stable slug.

    With ``require_minimum=True`` sparse scenarios are omitted, matching the
    publication behavior; single-page rendering remains strict and raises.
    """

    snapshot = _materialize_rows(resources)
    integration_snapshot: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = integrations
    if integrations is not None and not isinstance(integrations, Mapping):
        integration_snapshot = [item for item in integrations if isinstance(item, Mapping)]
    catalog: dict[str, list[dict[str, Any]]] = {}
    for definition in SCENARIOS:
        rows = scenario_rows(definition, snapshot, integrations=integration_snapshot)
        if require_minimum:
            try:
                _ensure_minimum(definition, rows)
            except ScenarioPageError:
                continue
        catalog[definition.slug] = rows
    return catalog


def _ensure_base_url(base_url: str) -> str:
    text = str(base_url or "").strip()
    return text.rstrip("/") + "/"


def _json_ld(
    definition: ScenarioDefinition,
    rows: Sequence[Mapping[str, Any]],
    *,
    locale: str,
    canonical: str,
    base_url: str,
) -> str:
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        item_url = _safe_external_url(row.get("homepage_url") or row.get("url"))
        entry: dict[str, Any] = {
            "@type": "ListItem",
            "position": index,
            "name": str(row.get("title") or row.get("provider") or ""),
        }
        if item_url:
            entry["url"] = item_url
        items.append(entry)
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "AI Resource Radar",
                "item": _ensure_base_url(base_url),
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": definition.title(locale),
                "item": canonical,
            },
        ],
    }
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": definition.title(locale),
        "itemListElement": items,
    }
    payload = json.dumps([breadcrumb, item_list], ensure_ascii=False, separators=(",", ":"))
    # Keep JSON-LD parseable while preventing an untrusted value from closing
    # the script element.  JSON unicode escapes preserve the original value
    # after the browser parses the JSON (HTML entities would not).
    return payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_scenario_page(
    scenario: str | ScenarioDefinition,
    resources: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    *,
    locale: str,
    base_url: str,
    integrations: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    require_minimum: bool = True,
    stylesheet_href: str = "/scenario.css",
) -> str:
    """Render one bilingual, no-JS-required scenario page."""

    definition = get_scenario(scenario)
    language = _locale(locale)
    rows = scenario_rows(
        definition,
        resources or [],
        integrations=integrations,
        require_minimum=require_minimum,
    )
    canonical = scenario_page_url(base_url, language, definition.slug)
    providers = aggregate_providers(rows)
    feed_prefix = "en/" if language == "en" else ""
    feed_base = _ensure_base_url(base_url)
    labels = {
        "provider": "供应商" if language != "en" else "Provider",
        "benefit": "送什么" if language != "en" else "What you get",
        "threshold": "门槛" if language != "en" else "Requirements",
        "steps": "怎么领" if language != "en" else "How to claim",
        "evidence": "官方证据 / 核验时间" if language != "en" else "Official evidence / verified",
        "unknown": "以官方页面为准" if language != "en" else "See the official page",
        "all": "查看该供应商全部资源" if language != "en" else "View all resources from this provider",
        "connect": "我已成功接入" if language != "en" else "I successfully connected",
    }

    def resource_markup(row: Mapping[str, Any], *, detail: bool = False) -> str:
        presentation = _presentation(row, language)
        title = escape(str(row.get("title") or row.get("model") or row.get("gpu_model") or "—"))
        provider = escape(str(row.get("provider") or row.get("provider_slug") or "—"))
        service_url = _safe_external_url(row.get("homepage_url") or row.get("url"))
        service_meta = f'<meta itemprop="url" content="{escape(service_url, quote=True)}">' if service_url else ""
        benefit = str(presentation.get("benefit_summary") or row.get("benefit_summary") or labels["unknown"])
        threshold_parts: list[str] = []
        card = row.get("requires_card")
        phone = row.get("requires_phone")
        availability = row.get("availability")
        # Eligibility from older datasets can be free-form Chinese policy
        # prose.  English pages only render it when an explicitly English
        # presentation is available.
        eligibility = row.get("eligibility") if language != "en" else None
        if card:
            threshold_parts.append(("无需信用卡" if language != "en" and str(card) == "no" else "No card" if language == "en" and str(card) == "no" else f"Card: {card}"))
        if phone and str(phone).lower() not in {"unknown", "none", ""}:
            threshold_parts.append(("无需手机号" if language != "en" and str(phone) == "no" else f"Phone: {phone}"))
        if isinstance(availability, Mapping):
            scope = str(availability.get("scope") or "unknown").strip().lower()
            availability_labels = {
                "global": ("官方标注为全球可用", "Officially marked global"),
                "restricted": ("存在地区限制", "Regional restrictions apply"),
                "unknown": ("地区可用性待官方确认", "Regional availability unknown"),
            }
            zh_label, en_label = availability_labels.get(
                scope, availability_labels["unknown"]
            )
            threshold_parts.append(en_label if language == "en" else zh_label)
        elif row.get("mainland_status"):
            # Compatibility-only presentation for older public snapshots.
            status = str(row.get("mainland_status")).strip().lower()
            legacy_labels = {
                "supported": ("中国可用", "China supported"),
                "unknown": ("中国可用性待确认", "China availability unknown"),
                "unsupported": ("中国不支持", "China unsupported"),
            }
            zh_label, en_label = legacy_labels.get(status, legacy_labels["unknown"])
            threshold_parts.append(en_label if language == "en" else zh_label)
        if eligibility:
            threshold_parts.append(str(eligibility))
        separator = "；" if language != "en" else "; "
        threshold = separator.join(threshold_parts) or labels["unknown"]
        raw_steps = presentation.get("usage_steps")
        steps = [str(item) for item in raw_steps if item] if isinstance(raw_steps, (list, tuple)) else []
        steps_markup = "".join(f"<li>{escape(item)}</li>" for item in steps) or f"<li>{escape(labels['unknown'])}</li>"
        evidence = _evidence(row)
        evidence_url = _safe_external_url(evidence.get("source_url") or row.get("homepage_url") or row.get("url"))
        observed = _observed_at(row)
        if evidence_url:
            evidence_markup = f'<a href="{escape(evidence_url, quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{escape(labels["evidence"])}</a>'
        else:
            evidence_markup = escape(labels["evidence"])
        verification_level = str(evidence.get("verification_level") or row.get("verification_level") or "").strip()
        if verification_level:
            evidence_markup += f'<span>{escape(verification_level)}</span>'
        if observed:
            evidence_markup += f'<time datetime="{escape(observed, quote=True)}">{escape(observed)}</time>'
        quota_parts = [str(row.get("quota_value") or ""), str(row.get("quota_unit") or ""), str(row.get("reset_period") or "")]
        quota = " ".join(part for part in quota_parts if part)
        css_class = "scenario-resource scenario-resource-detail" if detail else "scenario-resource"
        return (
            f'<li class="{css_class}" itemscope itemtype="https://schema.org/Service">'
            f'<h3 itemprop="name">{title}</h3>'
            f'{service_meta}'
            f'<p class="scenario-provider"><span>{escape(labels["provider"])}:</span> <span itemprop="provider">{provider}</span></p>'
            f'<div class="scenario-fact"><strong>{escape(labels["benefit"])}</strong><p>{escape(benefit)}</p></div>'
            f'<div class="scenario-fact"><strong>{escape(labels["threshold"])}</strong><p>{escape(threshold)}</p></div>'
            f'<div class="scenario-fact"><strong>{escape(labels["steps"])}</strong><ol>{steps_markup}</ol></div>'
            f'<div class="scenario-fact scenario-evidence"><strong>{escape(labels["evidence"])}</strong><p>{evidence_markup}</p></div>'
            + (f'<p class="scenario-quota">{escape(quota)}</p>' if quota else "")
            + '</li>'
        )

    provider_cards: list[str] = []
    for item in providers:
        provider_name = escape(str(item.get("provider") or "—"))
        provider_rows = item.get("resources") or []
        representative = resource_markup(provider_rows[0]) if provider_rows else ""
        details_rows = "".join(resource_markup(row, detail=True) for row in provider_rows)
        provider_cards.append(
            '<article class="scenario-provider-card">'
            f'<h3 class="scenario-provider-heading">{provider_name} <span>({item["resource_count"]})</span></h3>'
            f'<ul class="scenario-representative">{representative}</ul>'
            f'<details><summary>{escape(labels["all"])}</summary><ol class="scenario-resource-details">{details_rows}</ol></details>'
            '</article>'
        )
    provider_items: list[str] = []
    for item in providers:
        first = item["resources"][0] if item["resources"] else {}
        href = _safe_external_url(first.get("homepage_url") or first.get("url")) or "#"
        provider_items.append(
            f'<li><a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{escape(str(item.get("provider") or "—"))}</a> '
            f'<span>({item["resource_count"]})</span></li>'
        )
    provider_list = "".join(provider_items)
    breadcrumb_label = "场景" if language != "en" else "Scenarios"
    html_lang = "en" if language == "en" else "zh-CN"
    policy_note = (
        '<p class="scenario-policy">Protocol: chat_completions</p>'
        if definition.openai_compatible
        else ""
    )
    schema = _json_ld(
        definition,
        rows,
        locale=language,
        canonical=canonical,
        base_url=base_url,
    )
    return (
        '<!doctype html>\n'
        f'<html lang="{html_lang}">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <title>{escape(definition.title(language))} · AI Resource Radar</title>\n'
        f'  <meta name="description" content="{escape(definition.description(language), quote=True)}">\n'
        '  <meta name="robots" content="index,follow">\n'
        f'  <link rel="canonical" href="{escape(canonical, quote=True)}">\n'
        f'  <link rel="alternate" hreflang="zh-CN" href="{escape(scenario_page_url(base_url, "zh-CN", definition.slug), quote=True)}">\n'
        f'  <link rel="alternate" hreflang="en" href="{escape(scenario_page_url(base_url, "en", definition.slug), quote=True)}">\n'
        f'  <link rel="alternate" hreflang="x-default" href="{escape(scenario_page_url(base_url, "en", definition.slug), quote=True)}">\n'
        f'  <link rel="alternate" type="application/atom+xml" title="AI Resource Radar Atom" href="{escape(feed_base + feed_prefix + "feed.xml", quote=True)}">\n'
        f'  <link rel="alternate" type="application/rss+xml" title="AI Resource Radar RSS" href="{escape(feed_base + feed_prefix + "rss.xml", quote=True)}">\n'
        f'  <link rel="stylesheet" href="{escape(stylesheet_href, quote=True)}">\n'
        f'  <script type="application/ld+json">{schema}</script>\n'
        '</head>\n'
        '<body>\n'
        f'  <main class="scenario-page" data-scenario-slug="{escape(definition.slug, quote=True)}">\n'
        f'    <nav aria-label="breadcrumb"><a href="{escape(_ensure_base_url(base_url), quote=True)}">AI Resource Radar</a> / <span>{escape(breadcrumb_label)}</span> / <span>{escape(definition.title(language))}</span></nav>\n'
        f'    <header><h1>{escape(definition.title(language))}</h1><p>{escape(definition.description(language))}</p>{policy_note}</header>\n'
        f'    <section aria-labelledby="scenario-providers"><h2 id="scenario-providers">{escape("供应商聚合" if language != "en" else "Providers")}</h2><ul class="scenario-providers">{provider_list}</ul></section>\n'
        f'    <section aria-labelledby="scenario-resources"><h2 id="scenario-resources">{escape("符合条件的资源" if language != "en" else "Matching resources")}</h2><div class="scenario-provider-cards">{"".join(provider_cards)}</div></section>\n'
        f'    <p class="scenario-confirm-link"><a href="{escape(scenario_confirmation_url(base_url, language, definition.slug), quote=True)}">{escape(labels["connect"])}</a></p>\n'
        f'    <noscript><p>{escape("本页内容无需 JavaScript 即可阅读。" if language != "en" else "This page is fully readable without JavaScript.")}</p></noscript>\n'
        '  </main>\n'
        '</body>\n'
        '</html>\n'
    )


def render_scenario_confirmation_page(
    scenario: str | ScenarioDefinition,
    *,
    locale: str,
    base_url: str,
    stylesheet_href: str = "/scenario.css",
) -> str:
    """Render a bilingual noindex confirmation page containing one slug only."""

    definition = get_scenario(scenario)
    language = _locale(locale)
    canonical = scenario_confirmation_url(base_url, language, definition.slug)
    html_lang = "en" if language == "en" else "zh-CN"
    message = (
        "感谢你自愿确认已成功接入此场景。"
        if language != "en"
        else "Thank you for voluntarily confirming that you connected successfully through this scenario."
    )
    # Confirmation HTML deliberately contains no catalogue data and no other
    # scenario slugs, so crawlers cannot mistake it for a duplicate page.
    return (
        '<!doctype html>\n'
        f'<html lang="{html_lang}">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="robots" content="noindex,follow">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <title>{escape(definition.title(language))}</title>\n'
        f'  <link rel="canonical" href="{escape(canonical, quote=True)}">\n'
        f'  <link rel="alternate" hreflang="zh-CN" href="{escape(scenario_confirmation_url(base_url, "zh-CN", definition.slug), quote=True)}">\n'
        f'  <link rel="alternate" hreflang="en" href="{escape(scenario_confirmation_url(base_url, "en", definition.slug), quote=True)}">\n'
        f'  <link rel="alternate" hreflang="x-default" href="{escape(scenario_confirmation_url(base_url, "en", definition.slug), quote=True)}">\n'
        f'  <link rel="stylesheet" href="{escape(stylesheet_href, quote=True)}">\n'
        '</head>\n'
        f'<body><main class="scenario-confirmation" data-scenario-slug="{escape(definition.slug, quote=True)}"><p>{escape(message)}</p><code>{escape(definition.slug)}</code><p><a href="{escape(scenario_page_url(base_url, language, definition.slug), quote=True)}">{escape("返回场景页" if language != "en" else "Return to scenario")}</a></p></main></body>\n'
        '</html>\n'
    )


def render_scenario_confirmation_pages(
    scenario: str | ScenarioDefinition,
    *,
    base_url: str,
    stylesheet_href: str = "/scenario.css",
) -> dict[str, str]:
    """Return ``{"zh-CN": html, "en": html}`` for one scenario."""

    return {
        locale: render_scenario_confirmation_page(
            scenario,
            locale=locale,
            base_url=base_url,
            stylesheet_href=stylesheet_href,
        )
        for locale in ("zh-CN", "en")
    }


# Short aliases make integration code/readers concise without changing the
# explicit names above.
render_confirmation_page = render_scenario_confirmation_page
render_confirmation_pages = render_scenario_confirmation_pages


@dataclass(frozen=True)
class ScenarioPage:
    """One rendered locale page and its noindex confirmation companion."""

    slug: str
    locale: str
    url: str
    html: str
    provider_count: int
    resource_count: int
    filter_summary: Mapping[str, Any]
    confirmation_url: str
    confirmation_html: str


def build_scenario_pages(
    resources: Iterable[Mapping[str, Any]],
    integrations: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    *,
    base_url: str,
    source_revision: str | None = None,
    analytics_script: str = "",
    csp: str = "",
    require_minimum: bool = True,
    stylesheet_href: str = "/scenario.css",
) -> tuple[ScenarioPage, ...]:
    """Render all six scenarios in both locales for ``public_site``.

    ``source_revision``, ``analytics_script`` and ``csp`` are accepted as
    integration hooks so a caller can attach its existing publication metadata
    without coupling this module to a specific exporter.  Analytics is never
    inserted automatically; when supplied, it is placed immediately before
    ``</head>`` and the caller remains responsible for its safety policy.
    """

    snapshot = _materialize_rows(resources)
    integration_snapshot: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = integrations
    if integrations is not None and not isinstance(integrations, Mapping):
        integration_snapshot = [item for item in integrations if isinstance(item, Mapping)]
    catalog: dict[str, list[dict[str, Any]]] = {}
    for definition in SCENARIOS:
        rows = scenario_rows(definition, snapshot, integrations=integration_snapshot)
        if require_minimum:
            try:
                _ensure_minimum(definition, rows)
            except ScenarioPageError:
                # A thin scenario is not published at all; this keeps one
                # sparse category from making the entire static site fail.
                continue
        catalog[definition.slug] = rows
    pages: list[ScenarioPage] = []
    for definition in SCENARIOS:
        if definition.slug not in catalog:
            continue
        rows = catalog[definition.slug]
        providers = aggregate_providers(rows)
        for locale in ("zh-CN", "en"):
            html = render_scenario_page(
                definition,
                locale=locale,
                base_url=base_url,
                resources=rows,
                integrations=integration_snapshot,
                require_minimum=False,
                stylesheet_href=stylesheet_href,
            )
            if analytics_script:
                html = html.replace("</head>", f"{analytics_script}\n</head>", 1)
            if csp:
                html = html.replace(
                    '<meta charset="utf-8">',
                    f'<meta charset="utf-8">\n  <meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">',
                    1,
                )
            pages.append(
                ScenarioPage(
                    slug=definition.slug,
                    locale=locale,
                    url=scenario_page_url(base_url, locale, definition.slug),
                    html=html,
                    provider_count=len(providers),
                    resource_count=len(rows),
                    filter_summary={
                        "scenario": definition.slug,
                        "kind": definition.kind,
                        "offer_types": sorted(FREE_OFFER_TYPES),
                        "verification_levels": sorted(OFFICIAL_LEVELS),
                        "priority_tiers": sorted(PRIORITY_LEVELS),
                        "active": True,
                        "requires_card": definition.requires_card,
                        "recurring": definition.recurring,
                        "country": "CN" if definition.mainland_supported else None,
                        "free_image_generation": definition.free_image,
                        "protocol": "chat_completions" if definition.openai_compatible else None,
                        "source_revision": str(source_revision or "local")[:64],
                    },
                    confirmation_url=scenario_confirmation_url(base_url, locale, definition.slug),
                    confirmation_html=render_scenario_confirmation_page(
                        definition,
                        locale=locale,
                        base_url=base_url,
                        stylesheet_href=stylesheet_href,
                    ),
                )
            )
    return tuple(pages)


__all__ = [
    "OFFICIAL_LEVELS",
    "PRIORITY_LEVELS",
    "SCENARIO_BY_SLUG",
    "SCENARIO_DEFINITIONS",
    "SCENARIO_PAGE_MIN_PROVIDERS",
    "SCENARIO_PAGE_MIN_RESOURCES",
    "SCENARIO_SLUGS",
    "SCENARIOS",
    "ScenarioDefinition",
    "ScenarioPage",
    "ScenarioPageError",
    "aggregate_providers",
    "aggregate_provider_rows",
    "build_scenario_pages",
    "get_scenario",
    "render_scenario_confirmation_page",
    "render_scenario_confirmation_pages",
    "render_confirmation_page",
    "render_confirmation_pages",
    "render_scenario_page",
    "scenario_catalog",
    "scenario_confirmation_url",
    "scenario_page_url",
    "scenario_rows",
]
