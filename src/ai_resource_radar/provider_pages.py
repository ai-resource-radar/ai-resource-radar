"""Static, crawlable provider pages for the public radar snapshot."""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, Mapping
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ai_resource_radar import __version__ as RADAR_PUBLIC_VERSION
from ai_resource_radar.provider_profiles import ProviderProfile, provider_for_record


GITHUB_ISSUES_URL = "https://github.com/ai-resource-radar/ai-resource-radar/issues/new"
MAX_REPORT_BODY = 1_600
_SENSITIVE_QUERY_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|token|secret|password|cookie|authorization|credential|signature)",
    re.IGNORECASE,
)


def provider_page_url(base_url: str, locale: str, slug: str) -> str:
    language = "en" if locale == "en" else "zh"
    return f"{base_url.rstrip('/')}/{language}/providers/{slug}/"


def public_https_url(value: Any) -> str:
    """Return a credential-free HTTPS URL suitable for public artifacts."""

    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    # Never retain URL userinfo.  Keep ordinary public query parameters (for
    # example OpenRouter's output_modalities) but remove credential-shaped
    # parameters and fragments before exporting or pre-filling an issue.
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return ""
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _SENSITIVE_QUERY_KEY.search(key)
        ],
        doseq=True,
    )
    return urlunparse(("https", f"{hostname}{port}", parsed.path, parsed.params, query, ""))[:1_000]


def _public_https(value: Any) -> str:
    """Compatibility alias for the provider renderer's internal callers."""

    return public_https_url(value)


def correction_report_url(
    record: Mapping[str, Any],
    *,
    provider: ProviderProfile | None = None,
    source_revision: str = "local",
) -> str:
    """Build a bounded, public-facts-only GitHub correction link."""

    resolved = provider or provider_for_record(record)
    provider_name = resolved.name if resolved else str(record.get("provider") or "Unknown")[:100]
    record_id = str(record.get("offer_id") or record.get("price_id") or "")[:160]
    evidence = record.get("evidence") if isinstance(record.get("evidence"), Mapping) else {}
    source = _public_https(
        evidence.get("source_url")
        or record.get("pricing_url")
        or record.get("homepage_url")
    )
    verified = str(
        evidence.get("observed_at")
        or record.get("verified_at")
        or record.get("last_seen_at")
        or ""
    )[:80]
    displayed = str(
        record.get("title")
        or record.get("model")
        or record.get("gpu_model")
        or ""
    ).replace("\n", " ")[:240]
    body = (
        f"Provider/profile: {provider_name}"
        f"\nRecord ID: {record_id or 'not available'}"
        f"\nDisplayed fact: {displayed or 'provider profile'}"
        f"\nOfficial source: {source or 'not available'}"
        f"\nLast verified: {verified or 'not available'}"
        f"\nRadar version/revision: {RADAR_PUBLIC_VERSION} / {source_revision[:64]}"
        "\n\nWhat is outdated or incorrect?\n"
        "\nPublic evidence for the correction:\n"
    )[:MAX_REPORT_BODY]
    return GITHUB_ISSUES_URL + "?" + urlencode(
        {
            "template": "data-correction.yml",
            "labels": "data-correction",
            "title": f"[data correction] {provider_name}"[:180],
            "body": body,
        }
    )


def decorate_provider_record(
    record: dict[str, Any],
    *,
    base_url: str,
    source_revision: str,
) -> dict[str, Any]:
    """Add stable public navigation without changing existing data fields."""

    profile = provider_for_record(record)
    result = dict(record)
    if profile is None:
        result["report_url"] = correction_report_url(
            result, source_revision=source_revision
        )
        return result
    result["provider_slug"] = profile.slug
    result["provider_urls"] = {
        "zh-CN": provider_page_url(base_url, "zh-CN", profile.slug),
        "en": provider_page_url(base_url, "en", profile.slug),
    }
    result["provider_url"] = result["provider_urls"]["zh-CN"]
    result["report_url"] = correction_report_url(
        result, provider=profile, source_revision=source_revision
    )
    return result


def _offer_type(value: Any, locale: str) -> str:
    labels = {
        "zh-CN": {
            "recurring_free": "周期免费",
            "variable_free": "浮动免费",
            "grant": "申请型资助",
            "one_time": "一次性试用",
            "one_time_trial": "一次性试用",
            "pricing_reference": "付费价格",
        },
        "en": {
            "recurring_free": "Recurring free",
            "variable_free": "Variable free",
            "grant": "Application grant",
            "one_time": "One-time trial",
            "one_time_trial": "One-time trial",
            "pricing_reference": "Paid pricing",
        },
    }
    return labels[locale].get(str(value), str(value or "—"))


def _quota(row: Mapping[str, Any], locale: str) -> str:
    value = row.get("quota_value")
    unit = str(row.get("quota_unit") or "").strip()
    period = str(row.get("reset_period") or "").strip()
    if value is None:
        return "以账号页面为准" if locale == "zh-CN" else "See account limits"
    return " ".join(part for part in (str(value), unit, period) if part)


def _presentation(row: Mapping[str, Any], locale: str) -> Mapping[str, Any]:
    catalog = row.get("presentations") or row.get("presentation")
    if not isinstance(catalog, Mapping):
        return {}
    value = catalog.get(locale)
    if isinstance(value, Mapping):
        return value
    # Do not fall through to a Chinese database policy body on English pages.
    # This deliberately boring copy is safe for legacy/public rows that have
    # not yet been enriched with bilingual presentation content.
    if locale == "en":
        return {
            "benefit_summary": "See the official page for the current public policy.",
            "usage_steps": ["Open the official page and follow the account instructions."],
        }
    return {}


def _offer_cards(rows: Iterable[Mapping[str, Any]], locale: str) -> str:
    cards: list[str] = []
    for row in rows:
        presentation = _presentation(row, locale)
        steps = presentation.get("usage_steps")
        first_step = str(steps[0]) if isinstance(steps, list) and steps else ""
        evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
        cards.append(
            '<article class="provider-offer">'
            f'<span class="provider-type">{escape(_offer_type(row.get("offer_type"), locale))}</span>'
            f'<h3>{escape(str(row.get("title") or "—"))}</h3>'
            f'<strong>{escape(_quota(row, locale))}</strong>'
            f'<p>{escape(str(presentation.get("benefit_summary") or ""))}</p>'
            f'<p><b>{"怎么领" if locale == "zh-CN" else "How to claim"}：</b>{escape(first_step or ("打开官方页面核验。" if locale == "zh-CN" else "Verify on the official page."))}</p>'
            f'<a href="{escape(_public_https(evidence.get("source_url") or row.get("homepage_url")), quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{"官方证据 ↗" if locale == "zh-CN" else "Official evidence ↗"}</a>'
            '</article>'
        )
    if cards:
        return "".join(cards)
    return f'<p class="provider-empty">{"当前没有可公开展示的有效政策记录。" if locale == "zh-CN" else "No active public policy record is available in this snapshot."}</p>'


def _price_rows(rows: Iterable[Mapping[str, Any]], locale: str, *, gpu: bool) -> str:
    output: list[str] = []
    for row in list(rows)[:30]:
        name = row.get("gpu_model") if gpu else row.get("model")
        if gpu:
            value = "—" if row.get("hourly_usd") is None else f'${float(row["hourly_usd"]):g}/h'
        else:
            left = "—" if row.get("input_per_mtok") is None else f'${float(row["input_per_mtok"]):g}'
            right = "—" if row.get("output_per_mtok") is None else f'${float(row["output_per_mtok"]):g}'
            value = f'{left} / {right} per 1M'
        output.append(
            f'<li><span>{escape(str(name or row.get("title") or "—"))}</span><strong>{escape(value)}</strong></li>'
        )
    return "".join(output) or f'<li>{"暂无价格行" if locale == "zh-CN" else "No price rows"}</li>'


def _integrations(row: Mapping[str, Any] | None, locale: str) -> str:
    if not row:
        return f'<p class="provider-empty">{"尚无经过官方兼容证据核验的接入示例。" if locale == "zh-CN" else "No integration example has passed the official compatibility gate yet."}</p>'
    templates = row.get("templates")
    docs = row.get("client_docs") if isinstance(row.get("client_docs"), Mapping) else {}
    if not isinstance(templates, Mapping) or not templates:
        return ""
    labels = {"curl": "curl", "python": "Python", "openclaw": "OpenClaw", "cursor": "Cursor", "codex": "Codex"}
    blocks: list[str] = []
    for client in ("curl", "python", "openclaw", "cursor", "codex"):
        snippet = templates.get(client)
        if not snippet:
            continue
        evidence = _public_https(docs.get(client))
        blocks.append(
            '<article class="integration-example">'
            f'<div><h3>{labels[client]}</h3>'
            + (f'<a href="{escape(evidence, quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{"兼容依据 ↗" if locale == "zh-CN" else "Compatibility evidence ↗"}</a>' if evidence else "")
            + '</div>'
            f'<button type="button" data-copy-target="snippet-{escape(str(row.get("slug")))}-{client}">{"复制" if locale == "zh-CN" else "Copy"}</button>'
            f'<pre id="snippet-{escape(str(row.get("slug")))}-{client}"><code>{escape(str(snippet))}</code></pre>'
            '</article>'
        )
    return "".join(blocks)


def render_provider_page(
    profile: ProviderProfile,
    *,
    locale: str,
    base_url: str,
    resources: list[dict[str, Any]],
    token_prices: list[dict[str, Any]],
    gpu_prices: list[dict[str, Any]],
    integration: Mapping[str, Any] | None,
    source_revision: str,
    analytics_script: str,
    csp: str,
) -> str:
    language = "en" if locale == "en" else "zh-CN"
    lang_path = "en" if locale == "en" else "zh"
    canonical = provider_page_url(base_url, locale, profile.slug)
    alternate_locale = "zh-CN" if locale == "en" else "en"
    alternate = provider_page_url(base_url, alternate_locale, profile.slug)
    own_resources = [row for row in resources if row.get("provider_slug") == profile.slug]
    own_token = [row for row in token_prices if row.get("provider_slug") == profile.slug]
    own_gpu = [row for row in gpu_prices if row.get("provider_slug") == profile.slug]
    report = correction_report_url(
        {"provider": profile.name, "homepage_url": profile.docs_url},
        provider=profile,
        source_revision=source_revision,
    )
    zh = locale != "en"
    description = (
        f"{profile.name} 的免费政策、价格、接入方式与官方核验证据。"
        if zh
        else f"Verified free policies, prices, integration examples, and official evidence for {profile.name}."
    )
    title = f"{profile.name} — {'免费政策与接入' if zh else 'free policy and integrations'}"
    source_ids = " · ".join(profile.source_ids)
    analytics = f"    {analytics_script}\n" if analytics_script else ""
    return f'''<!doctype html>
<html lang="{language}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">
    <title>{escape(title)}</title>
    <meta name="description" content="{escape(description, quote=True)}">
    <meta name="robots" content="index,follow">
    <link rel="canonical" href="{escape(canonical, quote=True)}">
    <link rel="alternate" hreflang="zh-CN" href="{escape(provider_page_url(base_url, 'zh-CN', profile.slug), quote=True)}">
    <link rel="alternate" hreflang="en" href="{escape(provider_page_url(base_url, 'en', profile.slug), quote=True)}">
    <link rel="alternate" hreflang="x-default" href="{escape(provider_page_url(base_url, 'en', profile.slug), quote=True)}">
    <meta property="og:type" content="website"><meta property="og:title" content="{escape(title, quote=True)}">
    <meta property="og:description" content="{escape(description, quote=True)}"><meta property="og:url" content="{escape(canonical, quote=True)}">
    <link rel="icon" href="../../../favicon.svg" type="image/svg+xml">
    <link rel="stylesheet" href="../../../styles.css"><link rel="stylesheet" href="../../../provider.css">
{analytics}  </head>
  <body>
    <a class="skip-link" href="#main">{'跳到内容' if zh else 'Skip to content'}</a>
    <header class="provider-header"><div class="shell provider-header-inner"><a class="brand" href="../../../"><span class="brand-mark">AI</span><span class="brand-copy"><strong>AI Resource Radar</strong><small>{'每日核验免费资源与价格' if zh else 'Daily-verified free resources and prices'}</small></span></a><a href="{escape(alternate, quote=True)}">{'English' if zh else '中文'}</a></div></header>
    <main id="main" class="shell provider-main" itemscope itemtype="https://schema.org/Service">
      <meta itemprop="name" content="{escape(profile.name, quote=True)}"><meta itemprop="url" content="{escape(profile.homepage_url, quote=True)}">
      <nav class="breadcrumb" aria-label="Breadcrumb"><a href="../../../">AI Resource Radar</a><span>›</span><span>{escape(profile.name)}</span></nav>
      <section class="provider-hero">
        <p class="eyebrow">OFFICIAL PROVIDER PROFILE · VERIFIED DAILY</p><h1>{escape(profile.name)}</h1><p>{escape(description)}</p>
        <div class="provider-actions"><a class="button button-primary" href="{escape(profile.homepage_url, quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{'打开官网 ↗' if zh else 'Official site ↗'}</a><a class="button button-quiet" href="{escape(profile.docs_url, quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{'官方文档 ↗' if zh else 'Official docs ↗'}</a><a class="button button-link" href="{escape(report, quote=True)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{'政策过期 / 数据有误' if zh else 'Report stale or incorrect data'}</a></div>
        <small>{'跟踪来源' if zh else 'Tracked sources'}：{escape(source_ids)} · revision {escape(source_revision[:12])}</small>
      </section>
      <section class="provider-section" aria-labelledby="offers"><div class="section-heading"><div><p class="section-kicker">FREE POLICY</p><h2 id="offers">{'免费政策与试用' if zh else 'Free policies and trials'}</h2></div></div><div class="provider-offer-grid">{_offer_cards(own_resources, locale)}</div></section>
      <section class="provider-section" aria-labelledby="prices"><div class="section-heading"><div><p class="section-kicker">NORMALIZED PRICES</p><h2 id="prices">{'价格基线' if zh else 'Price baseline'}</h2></div></div><div class="provider-price-grid"><article><h3>Token</h3><ul>{_price_rows(own_token, locale, gpu=False)}</ul></article><article><h3>GPU</h3><ul>{_price_rows(own_gpu, locale, gpu=True)}</ul></article></div></section>
      <section class="provider-section" aria-labelledby="integrations"><div class="section-heading"><div><p class="section-kicker">VERIFIED INTEGRATIONS</p><h2 id="integrations">{'可复制接入示例' if zh else 'Copyable integration examples'}</h2><p class="section-caption">{'只展示有明确协议和客户端依据的组合；不会读取或保存你的密钥。' if zh else 'Only combinations with explicit protocol and client evidence are shown. Keys are never read or stored.'}</p></div></div><div class="integration-grid">{_integrations(integration, locale)}</div></section>
    </main>
    <footer class="site-footer"><div class="shell footer-inner"><p>AI Resource Radar · {'公开只读快照，以官方页面为准。' if zh else 'Read-only snapshot; verify on the official page.'}</p><p><a href="../../../">{'返回雷达' if zh else 'Back to radar'}</a></p></div></footer>
    <script type="module" src="../../../provider.js"></script>
  </body>
</html>'''


__all__ = [
    "MAX_REPORT_BODY",
    "correction_report_url",
    "decorate_provider_record",
    "provider_page_url",
    "public_https_url",
    "render_provider_page",
]
