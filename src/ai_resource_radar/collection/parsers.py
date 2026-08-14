from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Any

from .models import (
    OfferObservation,
    RadarSource,
    default_presentations,
    normalize_modalities,
    resolve_modalities,
)
from .registry import OFFICIAL_GUIDES, SOURCE_BY_ID, SOURCES, official_guide




class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "svg", "noscript"}:
            self._hidden += 1
        elif tag in {"p", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._hidden:
            self._hidden -= 1
        elif tag in {"p", "li", "tr", "td", "th", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_text(payload: bytes) -> str:
    parser = _VisibleTextParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _offer_id(provider: str, title: str, kind: str) -> str:
    digest = hashlib.sha256(
        f"{provider.casefold()}\x1f{title.casefold()}\x1f{kind}".encode()
    ).hexdigest()[:20]
    return f"{kind}:{digest}"


def _excerpt(text: str, needle: str, radius: int = 220) -> str:
    index = text.casefold().find(needle.casefold())
    if index < 0:
        return text[: min(440, len(text))]
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    return text[start:end][:500].strip()


def _require(text: str, *needles: str) -> None:
    folded = text.casefold()
    if not all(needle.casefold() in folded for needle in needles):
        raise ValueError("official_page_structure_changed")


def _official_offer(
    *,
    provider: str,
    title: str,
    kind: str,
    offer_type: str,
    quota_value: float | None,
    quota_unit: str | None,
    reset_period: str | None,
    estimated_usd_value: float | None,
    requires_card: str,
    eligibility: str | None,
    mainland_status: str,
    source_url: str,
    evidence_excerpt: str,
    details: dict[str, Any] | None = None,
    input_modalities: Any = None,
    output_modalities: Any = None,
    availability_scope: str | None = None,
    availability: dict[str, str] | None = None,
    requires_identity_verification: str = "unknown",
    requires_paid_topup: str = "unknown",
    requires_waitlist: str = "unknown",
    requires_organization: str = "unknown",
    presentations: dict[str, dict[str, Any]] | None = None,
) -> OfferObservation:
    normalized_details = (
        official_guide(provider, offer_type)
        if offer_type != "pricing_reference"
        else {}
    )
    normalized_details.update(details or {})
    resolved_inputs, resolved_outputs = resolve_modalities(
        normalized_details,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
    )
    return OfferObservation(
        offer_id=_offer_id(provider, title, kind),
        provider=provider,
        title=title,
        kind=kind,
        offer_type=offer_type,
        quota_value=quota_value,
        quota_unit=quota_unit,
        reset_period=reset_period,
        estimated_usd_value=estimated_usd_value,
        requires_card=requires_card,
        requires_phone="unknown",
        eligibility=eligibility,
        mainland_status=mainland_status,
        expires_at=None,
        homepage_url=source_url,
        verification_level="official_api"
        if source_url.startswith("https://openrouter.ai/api/")
        else "official_page",
        source_url=source_url,
        evidence_excerpt=evidence_excerpt[:500],
        details=normalized_details,
        input_modalities=resolved_inputs,
        output_modalities=resolved_outputs,
        requires_identity_verification=requires_identity_verification,
        requires_paid_topup=requires_paid_topup,
        requires_waitlist=requires_waitlist,
        requires_organization=requires_organization,
        # Existing source parsers only make an explicit China-mainland claim.
        # Preserve that claim as one country record; later source additions can
        # provide a broader availability map without changing this helper.
        availability_scope=availability_scope or (
            "restricted" if mainland_status in {"supported", "unsupported"} else "unknown"
        ),
        availability=availability or (
            {"CN": mainland_status}
            if mainland_status in {"supported", "unsupported"}
            else {}
        ),
        presentations=presentations
        or default_presentations(
            provider=provider, title=title, eligibility=eligibility
        ),
    )


def parse_openrouter(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    data = json.loads(payload)
    models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(models, list):
        raise ValueError("invalid_openrouter_models")
    output: list[OfferObservation] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        pricing = model.get("pricing")
        if not isinstance(model_id, str) or not isinstance(pricing, dict):
            continue
        if not model_id.endswith(":free") and model_id != "openrouter/free":
            continue
        title = str(model.get("name") or model_id)[:240]
        output.append(
            _official_offer(
                provider="OpenRouter",
                title=title,
                kind="token",
                offer_type="recurring_free",
                quota_value=50,
                quota_unit="requests",
                reset_period="daily",
                estimated_usd_value=None,
                requires_card="no",
                eligibility="免费模型共享每日请求额度；购买额度后上限可能提高。",
                mainland_status="unknown",
                source_url=source.url,
                evidence_excerpt=f"{model_id} is exposed as a zero-price/free model.",
                details={
                    "model_id": model_id,
                    "context_length": model.get("context_length"),
                    "input_modalities": (model.get("architecture") or {}).get(
                        "input_modalities"
                    ),
                    "output_modalities": (model.get("architecture") or {}).get(
                        "output_modalities"
                    ),
                    "pricing": pricing,
                },
                input_modalities=(model.get("architecture") or {}).get(
                    "input_modalities"
                ),
                output_modalities=(model.get("architecture") or {}).get(
                    "output_modalities"
                ),
            )
        )
    return tuple(output)


def parse_groq(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Free Plan", "Rate Limits")
    return (
        _official_offer(
            provider="Groq",
            title="Groq Free Plan API",
            kind="token",
            offer_type="recurring_free",
            quota_value=None,
            quota_unit="model-specific RPM/RPD/TPM/TPD",
            reset_period="daily",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="额度按模型和组织变化，以官方 Free Plan Limits 表为准。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "Free Plan"),
        ),
    )


def parse_gemini(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Gemini", "Free Tier")
    return (
        _official_offer(
            provider="Google Gemini",
            title="Gemini Developer API Free Tier",
            kind="token",
            offer_type="recurring_free",
            quota_value=None,
            quota_unit="model-specific requests/tokens",
            reset_period="daily",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="仅部分模型；实际项目额度以 Google AI Studio 为准。",
            mainland_status="unsupported",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "Free Tier"),
        ),
    )


def parse_cloudflare(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Workers AI", "10,000", "Neurons")
    return (
        _official_offer(
            provider="Cloudflare",
            title="Workers AI Free Allocation",
            kind="token",
            offer_type="recurring_free",
            quota_value=10000,
            quota_unit="neurons",
            reset_period="daily",
            estimated_usd_value=0.11,
            requires_card="no",
            eligibility="Workers Free 计划；每日 00:00 UTC 重置。",
            mainland_status="supported",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "10,000"),
        ),
    )


def parse_zhipu_cogview(
    payload: bytes, source: RadarSource
) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    # Keep the free-policy assertion tied to the model's official heading. A
    # generic ``免费`` elsewhere in the page (for example, site navigation)
    # must not be enough to keep an offer officially verified.
    _require(text, "CogView-3-Flash", "免费图像生成模型")
    return (
        _official_offer(
            provider="Zhipu AI",
            title="CogView-3-Flash Free Image API",
            kind="token",
            offer_type="variable_free",
            quota_value=None,
            quota_unit="account rate limit",
            reset_period="variable",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="免费，但官方未公布固定日额度，以账号速率限制为准。",
            mainland_status="supported",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "CogView-3-Flash"),
            details={
                "model_id": "cogview-3-flash",
                "api_endpoint": "https://open.bigmodel.cn/api/paas/v4/images/generations",
                "quota_note": "官方未公布固定日额度，以账号速率限制为准。",
            },
            input_modalities=("text",),
            output_modalities=("image",),
        ),
    )


def parse_huggingface(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "ZeroGPU", "Free account", "5 minutes")
    return (
        _official_offer(
            provider="Hugging Face",
            title="ZeroGPU Free Account",
            kind="gpu",
            offer_type="recurring_free",
            quota_value=5,
            quota_unit="GPU minutes",
            reset_period="daily",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="免费账号每日额度；良好账号可免费托管最多 2 个 ZeroGPU Space。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "5 minutes"),
            details={"vram_gb": [48, 96], "gpu": "RTX Pro 6000 Blackwell"},
        ),
    )


def parse_modal(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Starter", "$30", "month")
    starter = _official_offer(
        provider="Modal",
        title="Modal Starter Monthly Credit",
        kind="gpu",
        offer_type="recurring_free",
        quota_value=30,
        quota_unit="USD compute credit",
        reset_period="monthly",
        estimated_usd_value=30,
        requires_card="no",
        eligibility="Starter 计划；具体 GPU 时长取决于所选 GPU 单价。",
        mainland_status="unknown",
        source_url=source.url,
        evidence_excerpt=_excerpt(text, "$30"),
    )
    offers = [starter]
    if "$10k" in text or "10k" in text.casefold():
        offers.append(
            _official_offer(
                provider="Modal",
                title="Modal Academic Compute Grant",
                kind="grant",
                offer_type="grant",
                quota_value=10000,
                quota_unit="USD compute credit",
                reset_period="one_time",
                estimated_usd_value=10000,
                requires_card="unknown",
                eligibility="研究生、实验室和研究人员需提交申请。",
                mainland_status="unknown",
                source_url=source.url,
                evidence_excerpt=_excerpt(text, "$10k"),
            )
        )
    raw_html = payload.decode("utf-8", errors="replace")
    gpu_rows = re.findall(
        r'<div class="line-item[^"]*">\s*<p[^>]*>([^<]+)</p>'
        r'.*?<p class="price[^>]*">\$([0-9.]+)\s*'
        r'<span[^>]*>/\s*(sec|hour)',
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for raw_name, raw_price, unit in gpu_rows:
        name = unescape(raw_name).strip().removeprefix("Nvidia ")
        per_hour = float(raw_price) * (3600 if unit.casefold() == "sec" else 1)
        vram = gpu_vram(name)
        offers.append(
            _official_offer(
                provider="Modal",
                title=f"{name} Serverless GPU",
                kind="gpu",
                offer_type="pricing_reference",
                quota_value=round(per_hour, 4),
                quota_unit="USD per GPU hour",
                reset_period=None,
                estimated_usd_value=round(per_hour, 4),
                requires_card="unknown",
                eligibility="按秒计费；榜单统一折算为单 GPU 每小时价格。",
                mainland_status="unknown",
                source_url=source.url,
                evidence_excerpt=f"Official Modal price: ${raw_price} per {unit} for {name}.",
                details={
                    "gpu_model": name,
                    "vram_gb": vram,
                    "hourly_usd": round(per_hour, 4),
                    "original_price": float(raw_price),
                    "original_unit": f"USD per {unit}",
                    "billing_mode": "serverless",
                    "market_tier": "on-demand",
                    "currency": "USD",
                },
            )
        )
    return tuple(offers)


GPU_VRAM_GB = {
    "B300": 288,
    "B200": 180,
    "H200": 141,
    "H100": 80,
    "H100 SXM": 80,
    "H100 PCIe": 80,
    "H100 NVL": 94,
    "GH200": 96,
    "RTX PRO 6000": 96,
    "RTX Pro 6000": 96,
    "RTX 6000 Ada": 48,
    "RTX A5000": 24,
    "RTX A6000": 48,
    "RTX 3090": 24,
    "RTX 4090": 24,
    "RTX 5090": 32,
    "A40": 48,
    "L40": 48,
    "A100, 80 GB": 80,
    "A100, 40 GB": 40,
    "A100 SXM": 80,
    "A100 PCIe": 40,
    "A6000": 48,
    "L40S": 48,
    "A10": 24,
    "L4": 24,
    "T4": 16,
    "V100": 16,
    "Quadro RTX 6000": 24,
}


def gpu_vram(name: str) -> float | None:
    explicit = re.search(r"(?:,|\()\s*(\d+(?:\.\d+)?)\s*(?:GB|GiB)", name, re.I)
    if explicit:
        return float(explicit.group(1))
    return GPU_VRAM_GB.get(name)


def _json_ld_documents(payload: bytes) -> tuple[Any, ...]:
    raw_html = payload.decode("utf-8", errors="replace")
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    documents: list[Any] = []
    for script in scripts:
        try:
            documents.append(json.loads(unescape(script)))
        except json.JSONDecodeError:
            continue
    return tuple(documents)


def parse_runpod_pricing(
    payload: bytes, source: RadarSource
) -> tuple[OfferObservation, ...]:
    products: list[dict[str, Any]] = []
    for document in _json_ld_documents(payload):
        graph = document.get("@graph") if isinstance(document, dict) else None
        if not isinstance(graph, list):
            continue
        products.extend(
            item
            for item in graph
            if isinstance(item, dict)
            and item.get("@type") == "Product"
            and isinstance(item.get("offers"), dict)
        )
    output: list[OfferObservation] = []
    for product in products:
        product_name = str(product.get("name") or "")
        name = re.sub(r"\s+GPU on Runpod$", "", product_name).strip()
        aggregate = product["offers"]
        quotes = aggregate.get("offers")
        if not name or not isinstance(quotes, list):
            continue
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            tier = str(quote.get("name") or "On-demand")[:80]
            try:
                hourly = float(quote["price"])
            except (KeyError, TypeError, ValueError):
                continue
            output.append(
                _official_offer(
                    provider="RunPod",
                    title=f"{name} · {tier}",
                    kind="gpu",
                    offer_type="pricing_reference",
                    quota_value=hourly,
                    quota_unit="USD per GPU hour",
                    reset_period=None,
                    estimated_usd_value=hourly,
                    requires_card="unknown",
                    eligibility="RunPod Cloud GPU 按需价；实际可用区域和库存会变化。",
                    mainland_status="unknown",
                    source_url=source.url,
                    evidence_excerpt=str(quote.get("description") or product.get("description") or "")[:500],
                    details={
                        "gpu_model": name,
                        "vram_gb": gpu_vram(name),
                        "hourly_usd": hourly,
                        "original_price": hourly,
                        "original_unit": "USD per GPU hour",
                        "billing_mode": "pod",
                        "market_tier": tier,
                        "currency": str(quote.get("priceCurrency") or "USD"),
                    },
                )
            )
    if not output:
        raise ValueError("official_page_structure_changed")
    return tuple(output)


def parse_lambda_pricing(
    payload: bytes, source: RadarSource
) -> tuple[OfferObservation, ...]:
    raw_html = payload.decode("utf-8", errors="replace")
    matches = re.findall(
        r'<tr[^>]*data-plan="([^"]+)"[^>]*>.*?'
        r'<td data-label="VRAM/GPU">([^<]+)</td>.*?'
        r'<td data-label="PRICE/GPU/HR\*">\$([0-9.]+)</td>',
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    grouped: dict[tuple[str, float], list[float]] = {}
    for raw_name, raw_vram, raw_price in matches:
        name = unescape(raw_name).strip().removeprefix("NVIDIA ").removeprefix("Tesla ")
        vram_match = re.search(r"([0-9.]+)", unescape(raw_vram))
        if not vram_match:
            continue
        key = (name, float(vram_match.group(1)))
        grouped.setdefault(key, []).append(float(raw_price))
    output: list[OfferObservation] = []
    for (name, vram), prices in grouped.items():
        hourly = max(prices)
        output.append(
            _official_offer(
                provider="Lambda",
                title=f"{name} {vram:g} GB",
                kind="gpu",
                offer_type="pricing_reference",
                quota_value=hourly,
                quota_unit="USD per GPU hour",
                reset_period=None,
                estimated_usd_value=hourly,
                requires_card="unknown",
                eligibility="标准单 GPU 按需价；多 GPU 集群可能有更低的每 GPU 单价，税费另计。",
                mainland_status="unknown",
                source_url=source.url,
                evidence_excerpt=f"Official Lambda price table lists {name} {vram:g} GB at up to ${hourly:g}/GPU/hr.",
                details={
                    "gpu_model": name,
                    "vram_gb": vram,
                    "hourly_usd": hourly,
                    "original_price": hourly,
                    "original_unit": "USD per GPU hour",
                    "billing_mode": "instance",
                    "market_tier": "on-demand",
                    "currency": "USD",
                    "multi_gpu_lowest_hourly_usd": min(prices),
                },
            )
        )
    if not output:
        raise ValueError("official_page_structure_changed")
    return tuple(output)


def parse_vast_pricing(
    payload: bytes, source: RadarSource
) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Live GPU Prices", "supply and demand", "Per-second billing")
    return (
        _official_offer(
            provider="Vast.ai",
            title="Live GPU Marketplace",
            kind="gpu",
            offer_type="pricing_reference",
            quota_value=None,
            quota_unit="live marketplace price",
            reset_period=None,
            estimated_usd_value=None,
            requires_card="unknown",
            eligibility="市场实时定价；按需、可中断和预留实例价格随供需变化。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "Live GPU Prices"),
            details={
                "gpu_model": "Multiple GPU types",
                "vram_gb": None,
                "hourly_usd": None,
                "billing_mode": "marketplace",
                "market_tier": "live market",
                "currency": "USD",
                "price_mode": "dynamic_market",
                "price_note": "需进入 Vast.ai 实时市场按 GPU、地区和可靠性查询。",
            },
        ),
    )


def parse_lightning(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    data = json.loads(payload)
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise ValueError("official_page_structure_changed")
    included = next(
        (
            feature.get("limit")
            for feature in features
            if isinstance(feature, dict)
            and feature.get("key") == "included_credits"
        ),
        None,
    )
    if not isinstance(included, (int, float)) or included <= 0:
        raise ValueError("official_page_structure_changed")
    return (
        _official_offer(
            provider="Lightning AI",
            title="Lightning Free Monthly Credits",
            kind="gpu",
            offer_type="recurring_free",
            quota_value=float(included),
            quota_unit="USD compute credit",
            reset_period="monthly",
            estimated_usd_value=float(included),
            requires_card="no",
            eligibility="Free 计划包含的 credits；实际 GPU 时长取决于机型和价格。",
            mainland_status="unknown",
            source_url="https://lightning.ai/pricing",
            evidence_excerpt=(
                f"Official Free subscription quote reports included_credits={included}."
            ),
            details={"evidence_api": source.url},
        ),
    )


def parse_kaggle(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    data = json.loads(payload)
    content = data.get("pageContent") if isinstance(data, dict) else None
    if not isinstance(content, str):
        raise ValueError("official_page_structure_changed")
    text = html_text(content.encode())
    _require(text, "free access", "GPU", "30 hours")
    return (
        _official_offer(
            provider="Kaggle",
            title="Kaggle Notebooks Free GPU",
            kind="gpu",
            offer_type="recurring_free",
            quota_value=30,
            quota_unit="GPU hours",
            reset_period="weekly",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="官方说明通常为每周 30 小时，可能随供需上浮。",
            mainland_status="unknown",
            source_url="https://www.kaggle.com/docs/efficient-gpu-usage",
            evidence_excerpt=_excerpt(text, "30 hours"),
            details={"gpu": "NVIDIA Tesla P100", "evidence_api": source.url},
        ),
    )


def parse_colab(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "free of charge", "GPUs", "TPUs")
    return (
        _official_offer(
            provider="Google Colab",
            title="Colab Free GPU/TPU Runtime",
            kind="gpu",
            offer_type="variable_free",
            quota_value=None,
            quota_unit="variable GPU/TPU access",
            reset_period="variable",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="资源不保证且额度动态变化；必须遵守 notebook 交互和反滥用限制。",
            mainland_status="unsupported",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "free of charge"),
        ),
    )


def parse_sambanova(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "SambaNova", "Free Tier", "no payment method", "RPM", "RPD", "TPD")
    free_section = text[text.casefold().find("production model rate limits") :]
    matches = re.findall(
        r"((?:DeepSeek|Meta|OpenAI|Google)\s+)?"
        r"([A-Za-z0-9][A-Za-z0-9._-]{2,80})\s+20\s+20\s+200(?:,?000|K)\b",
        free_section,
        flags=re.IGNORECASE,
    )
    model_ids = list(dict.fromkeys(model_id for _, model_id in matches))
    if not model_ids:
        raise ValueError("official_page_structure_changed")
    return tuple(
        _official_offer(
            provider="SambaNova",
            title=f"{model_id} Free Tier",
            kind="token",
            offer_type="recurring_free",
            quota_value=200_000,
            quota_unit="tokens per model",
            reset_period="daily",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="账号未绑定付款方式时自动使用 Free Tier。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=f"Official Free Tier: {model_id}, 20 RPM, 20 RPD, 200000 TPD.",
            details={"model_id": model_id, "rate_limits": {"rpm": 20, "rpd": 20, "tpd": 200_000}},
            input_modalities=("text",),
            output_modalities=("text",),
        )
        for model_id in model_ids
    )


def parse_mistral_free_mode(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Free mode", "no credit card required", "Usage and rate limits apply")
    return (
        _official_offer(
            provider="Mistral AI",
            title="Mistral Studio Free Mode",
            kind="token",
            offer_type="variable_free",
            quota_value=None,
            quota_unit="account-defined API quota",
            reset_period="account_defined",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="API 默认开放；具体用量与速率限制以 Studio 账号为准。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "no credit card required"),
            input_modalities=("text",),
            output_modalities=("text",),
        ),
    )


def parse_huggingface_inference_credits(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Free Credits to Get Started", "Free Users", "$0.10", "subject to change")
    return (
        _official_offer(
            provider="Hugging Face Inference",
            title="Monthly Inference Providers Credits",
            kind="token",
            offer_type="recurring_free",
            quota_value=0.10,
            quota_unit="USD inference credit",
            reset_period="monthly",
            estimated_usd_value=0.10,
            requires_card="no",
            eligibility="免费用户；额度仅用于通过 Hugging Face 路由的请求，官方注明可能调整。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "Free Users"),
            details={"quota_subject_to_change": True},
            input_modalities=("text", "image", "audio"),
            output_modalities=("text", "image", "audio", "video"),
        ),
    )


def parse_siliconflow_free_models(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "免费模型Rate Limits", "实名认证", "免费模型调用免费", "调用消耗是 0")
    return (
        _official_offer(
            provider="SiliconFlow",
            title="SiliconFlow Free Models",
            kind="token",
            offer_type="variable_free",
            quota_value=None,
            quota_unit="model-specific fixed rate limit",
            reset_period="model_defined",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="完成实名认证；选择模型广场中未带 Pro/ 前缀的免费模型。",
            mainland_status="supported",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "免费模型调用免费"),
            details={"identity_verification_required": True},
            input_modalities=("text", "image", "audio"),
            output_modalities=("text", "image", "audio"),
        ),
    )


def parse_alibaba_model_studio_trial(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "新人免费额度", "90 天", "通常为 100 万 Token", "免费额度用完即停")
    return (
        _official_offer(
            provider="Alibaba Model Studio",
            title="Model Studio New-user Token Quota",
            kind="token",
            offer_type="one_time",
            quota_value=1_000_000,
            quota_unit="tokens per participating model",
            reset_period="90_days_once",
            estimated_usd_value=None,
            requires_card="no",
            eligibility="首次开通、华北 2（北京）地域；每个参与模型额度独立，通常 100 万 Token。",
            mainland_status="supported",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "通常为 100 万 Token"),
            details={
                "identity_verification_required": True,
                "billing_risk": "已认证账号额度耗尽后可能自动按量扣费；应开启免费额度用完即停。",
                "free_quota_stop_available": True,
            },
            input_modalities=("text",),
            output_modalities=("text",),
        ),
    )


def parse_cerebras_trial(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Free Trial tier", "$5 in free credits", "verified payment method", "expire 30 days")
    return (
        _official_offer(
            provider="Cerebras",
            title="Cerebras 30-day Free Trial",
            kind="token",
            offer_type="one_time",
            quota_value=5,
            quota_unit="USD inference credit",
            reset_period="30_days_once",
            estimated_usd_value=5,
            requires_card="yes",
            eligibility="新账号需添加已验证付款方式；credits 30 天后到期。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "$5 in free credits"),
            details={"permanently_free": False},
            input_modalities=("text", "image"),
            output_modalities=("text",),
        ),
    )


def _token_price_offer(*, provider: str, model: str, source: RadarSource, input_mtok: float, output_mtok: float, cache_read_mtok: float | None = None, excerpt: str) -> OfferObservation:
    prices: dict[str, float] = {"input_mtok": round(input_mtok, 8), "output_mtok": round(output_mtok, 8)}
    if cache_read_mtok is not None:
        prices["cache_read_mtok"] = round(cache_read_mtok, 8)
    return _official_offer(
        provider=provider,
        title=model,
        kind="token",
        offer_type="pricing_reference",
        quota_value=input_mtok,
        quota_unit="USD per million input tokens",
        reset_period=None,
        estimated_usd_value=None,
        requires_card="yes",
        eligibility="官方按量价格；不标记为免费。",
        mainland_status="unknown",
        source_url=source.url,
        evidence_excerpt=excerpt,
        details={"model_id": model, "prices": prices},
        input_modalities=("text",),
        output_modalities=("text",),
    )


def _gpu_price_offer(*, provider: str, model: str, vram_gb: float | None, hourly_usd: float, original_price: float, original_unit: str, source: RadarSource, excerpt: str) -> OfferObservation:
    return _official_offer(
        provider=provider,
        title=f"{model} GPU",
        kind="gpu",
        offer_type="pricing_reference",
        quota_value=round(hourly_usd, 6),
        quota_unit="USD per GPU hour",
        reset_period=None,
        estimated_usd_value=round(hourly_usd, 6),
        requires_card="yes",
        eligibility="官方按量 GPU 价格；不标记为免费。",
        mainland_status="unknown",
        source_url=source.url,
        evidence_excerpt=excerpt,
        details={
            "gpu_model": model,
            "vram_gb": vram_gb,
            "hourly_usd": round(hourly_usd, 6),
            "original_price": original_price,
            "original_unit": original_unit,
            "billing_mode": "on-demand",
            "market_tier": "on-demand",
            "price_mode": "fixed",
            "currency": "USD",
        },
    )


def parse_replicate_pricing(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Some models are billed by input and output", "Hardware pricing", "GPU RAM")
    raw_html = payload.decode("utf-8", errors="replace")
    token_matches: list[tuple[str, str, str]] = []
    for model, fragment in re.findall(
        r'<a\s+href="https://replicate\.com/([a-z0-9._-]+/[a-z0-9._-]+)"[^>]*>(.*?)</a>',
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        fragment_text = html_text(fragment.encode())
        output_match = re.search(
            r"\$\s*([0-9.]+)\s*/\s*thousand output tokens",
            fragment_text,
            flags=re.IGNORECASE,
        )
        input_match = re.search(
            r"\$\s*([0-9.]+)\s*/\s*million input tokens",
            fragment_text,
            flags=re.IGNORECASE,
        )
        if output_match and input_match:
            token_matches.append(
                (model, output_match.group(1), input_match.group(1))
            )
    offers: list[OfferObservation] = []
    for model, output_per_ktok, input_price in token_matches:
        offers.append(
            _token_price_offer(
                provider="Replicate",
                model=model,
                source=source,
                input_mtok=float(input_price),
                output_mtok=float(output_per_ktok) * 1000,
                excerpt=f"Official example: {model}, ${input_price}/M input and ${output_per_ktok}/K output tokens.",
            )
        )
    hardware = text[text.find("Hardware pricing") :]
    gpu_rows = re.findall(
        r"(?:(\d+)x\s+)?(Nvidia\s+(?:A100 \(80GB\)|H100|H200|L40S|T4)\s+GPU)\s+"
        r"(gpu-[a-z0-9-]+)\s+\$\s*([0-9.]+)\s*/sec\s+\$\s*([0-9.]+)\s*/hr",
        hardware,
        flags=re.IGNORECASE,
    )
    gpu_matches = list(
        {
            hardware_id: (raw_name, hardware_id, per_second, per_hour)
            for count, raw_name, hardware_id, per_second, per_hour in gpu_rows
            if not count
        }.values()
    )
    for raw_name, hardware_id, per_second, per_hour in gpu_matches:
        model = re.sub(r"^Nvidia\s+|\s+GPU$|\s*\(80GB\)", "", raw_name, flags=re.I)
        offers.append(
            _gpu_price_offer(
                provider="Replicate",
                model=model,
                vram_gb=gpu_vram(raw_name) or gpu_vram(model),
                hourly_usd=float(per_hour),
                original_price=float(per_second),
                original_unit="USD per second",
                source=source,
                excerpt=f"Official hardware row {hardware_id}: ${per_second}/sec, ${per_hour}/hr.",
            )
        )
    if not token_matches or not gpu_matches:
        raise ValueError("official_page_structure_changed")
    return tuple(offers)


def parse_baseten_pricing(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    text = html_text(payload)
    _require(text, "Price per 1M tokens", "Dedicated Deployments", "Price per Minute", "new Baseten accounts come with credits")
    model_section = text[text.find("Price per 1M tokens") : text.find("Dedicated Deployments")]
    if "Output" in model_section:
        model_section = model_section.split("Output", 1)[1]
    token_matches = re.findall(
        r"(?P<model>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)\s+"
        r"(?P=model)\s+\$(?P<input>[0-9.]+)\s+\$(?P=input)\s+"
        r"(?:\$(?P<cache>[0-9.]+)\s+\$(?P=cache)|-\s+-)\s+"
        r"\$(?P<output>[0-9.]+)\s+Try Model API",
        model_section,
    )
    offers: list[OfferObservation] = []
    for raw_model, input_price, cache_price, output_price in token_matches:
        model = re.sub(r"^(?:Model Input Cache Input Output|Try)\s+", "", raw_model).strip()
        offers.append(
            _token_price_offer(
                provider="Baseten",
                model=model,
                source=source,
                input_mtok=float(input_price),
                cache_read_mtok=float(cache_price) if cache_price else None,
                output_mtok=float(output_price),
                excerpt=f"Official Model API row: {model}, ${input_price}/M input, ${output_price}/M output.",
            )
        )
    gpu_section = text[text.find("Dedicated Deployments") : text.find("CPU Instances")]
    gpu_matches = re.findall(
        r"\b(T4|L4|A10G|A100|H100 MIG|H100|B200)\s+([0-9]+)\s+GiB\s+(?:VRAM|VM)\s+\$([0-9.]+)",
        gpu_section,
    )
    for model, vram, per_minute in gpu_matches:
        minute = float(per_minute)
        offers.append(
            _gpu_price_offer(
                provider="Baseten",
                model=model,
                vram_gb=float(vram),
                hourly_usd=minute * 60,
                original_price=minute,
                original_unit="USD per minute",
                source=source,
                excerpt=f"Official dedicated deployment row: {model} ${per_minute}/minute.",
            )
        )
    offers.append(
        _official_offer(
            provider="Baseten",
            title="New-account Experiment Credits",
            kind="grant",
            offer_type="one_time",
            quota_value=None,
            quota_unit="USD credits (amount not published)",
            reset_period="one_time",
            estimated_usd_value=None,
            requires_card="unknown",
            eligibility="仅新账号；官方未公布固定 credits 金额。",
            mainland_status="unknown",
            source_url=source.url,
            evidence_excerpt=_excerpt(text, "new Baseten accounts come with credits"),
        )
    )
    if not token_matches or not gpu_matches:
        raise ValueError("official_page_structure_changed")
    return tuple(offers)


def parse_mnfst(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    data = json.loads(payload)
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, list):
        raise ValueError("invalid_mnfst_catalog")
    output: list[OfferObservation] = []
    for provider in providers:
        if not isinstance(provider, dict) or not isinstance(provider.get("name"), str):
            continue
        provider_name = provider["name"][:200]
        homepage = str(provider.get("url") or source.url)[:2048]
        output.append(
            OfferObservation(
                offer_id=_offer_id(provider_name, provider_name, "token"),
                provider=provider_name,
                title=provider_name,
                kind="token",
                offer_type="recurring_free",
                quota_value=None,
                quota_unit=None,
                reset_period="unknown",
                estimated_usd_value=None,
                requires_card="unknown",
                requires_phone="unknown",
                eligibility=str(provider.get("description") or "")[:500] or None,
                mainland_status="unknown",
                expires_at=None,
                homepage_url=homepage,
                verification_level="community",
                source_url=source.url,
                evidence_excerpt=str(provider.get("description") or "")[:500],
                details={"record_type": "provider"},
            )
        )
        models = provider.get("models")
        if not isinstance(models, list) or not models:
            models = [{"id": provider_name, "name": provider_name}]
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            title = str(model.get("name") or model["id"])[:240]
            output.append(
                OfferObservation(
                    offer_id=_offer_id(provider_name, title, "token"),
                    provider=provider_name,
                    title=title,
                    kind="token",
                    offer_type="recurring_free",
                    quota_value=None,
                    quota_unit=str(model.get("rateLimit") or "")[:200] or None,
                    reset_period="unknown",
                    estimated_usd_value=None,
                    requires_card="unknown",
                    requires_phone="unknown",
                    eligibility=str(provider.get("description") or "")[:500] or None,
                    mainland_status="unknown",
                    expires_at=None,
                    homepage_url=homepage,
                    verification_level="community",
                    source_url=source.url,
                    evidence_excerpt=str(provider.get("description") or "")[:500],
                    details={
                        "model_id": model["id"],
                        "context": model.get("context"),
                        "max_output": model.get("maxOutput"),
                        "modality": model.get("modality"),
                    },
                    input_modalities=model.get("modality"),
                )
            )
    if not output:
        raise ValueError("empty_mnfst_catalog")
    return tuple(output)


def parse_prices(payload: bytes, source: RadarSource) -> tuple[OfferObservation, ...]:
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("invalid_genai_prices")
    output: list[OfferObservation] = []
    for provider in data:
        if not isinstance(provider, dict):
            continue
        provider_name = provider.get("name")
        models = provider.get("models")
        if not isinstance(provider_name, str) or not isinstance(models, list):
            continue
        urls = provider.get("pricing_urls")
        homepage = (
            urls[0]
            if isinstance(urls, list) and urls and isinstance(urls[0], str)
            else source.url
        )
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            title = str(model.get("name") or model["id"])[:240]
            output.append(
                OfferObservation(
                    offer_id=_offer_id(provider_name, title, "token"),
                    provider=provider_name[:200],
                    title=title,
                    kind="token",
                    offer_type="pricing_reference",
                    quota_value=None,
                    quota_unit=None,
                    reset_period=None,
                    estimated_usd_value=None,
                    requires_card="unknown",
                    requires_phone="unknown",
                    eligibility=None,
                    mainland_status="unknown",
                    expires_at=None,
                    homepage_url=homepage[:2048],
                    verification_level="community",
                    source_url=source.url,
                    evidence_excerpt="Community-maintained model pricing reference.",
                    details={
                        "model_id": model["id"],
                        "prices": model.get("prices"),
                        "context_window": model.get("context_window"),
                        "input_modalities": model.get("input_modalities"),
                        "output_modalities": model.get("output_modalities"),
                        "modality": model.get("modality"),
                    },
                    input_modalities=model.get("input_modalities"),
                    output_modalities=model.get("output_modalities"),
                )
            )
    if not output:
        raise ValueError("empty_genai_prices")
    return tuple(output)


PARSERS = {
    "openrouter-models": parse_openrouter,
    "groq-free-limits": parse_groq,
    "gemini-free-tier": parse_gemini,
    "cloudflare-workers-ai": parse_cloudflare,
    "zhipu-cogview-3-flash": parse_zhipu_cogview,
    "huggingface-zerogpu": parse_huggingface,
    "modal-pricing": parse_modal,
    "runpod-gpu-pricing": parse_runpod_pricing,
    "lambda-gpu-pricing": parse_lambda_pricing,
    "vast-gpu-pricing": parse_vast_pricing,
    "lightning-pricing": parse_lightning,
    "kaggle-gpu": parse_kaggle,
    "colab-faq": parse_colab,
    "sambanova-free-tier": parse_sambanova,
    "mistral-free-mode": parse_mistral_free_mode,
    "huggingface-inference-credits": parse_huggingface_inference_credits,
    "siliconflow-free-models": parse_siliconflow_free_models,
    "alibaba-model-studio-trial": parse_alibaba_model_studio_trial,
    "cerebras-free-trial": parse_cerebras_trial,
    "replicate-pricing": parse_replicate_pricing,
    "baseten-pricing": parse_baseten_pricing,
    "mnfst-free-llm-apis": parse_mnfst,
    "pydantic-genai-prices": parse_prices,
}


def parse_source(
    source: RadarSource, payload: bytes
) -> tuple[OfferObservation, ...]:
    return PARSERS[source.id](payload, source)
