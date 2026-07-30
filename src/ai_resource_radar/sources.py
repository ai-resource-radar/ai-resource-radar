from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Any


@dataclass(frozen=True)
class RadarSource:
    id: str
    name: str
    url: str
    license: str
    kind: str
    authority: str
    cadence_hours: int
    format: str
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class OfferObservation:
    offer_id: str
    provider: str
    title: str
    kind: str
    offer_type: str
    quota_value: float | None
    quota_unit: str | None
    reset_period: str | None
    estimated_usd_value: float | None
    requires_card: str
    requires_phone: str
    eligibility: str | None
    mainland_status: str
    expires_at: str | None
    homepage_url: str
    verification_level: str
    source_url: str
    evidence_excerpt: str
    details: dict[str, Any]


SOURCES = (
    RadarSource(
        "openrouter-models",
        "OpenRouter Models",
        "https://openrouter.ai/api/v1/models?output_modalities=all",
        "official",
        "token",
        "official_api",
        24,
        "json",
        ("openrouter.ai",),
    ),
    RadarSource(
        "groq-free-limits",
        "Groq Free Plan Limits",
        "https://console.groq.com/docs/rate-limits",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("console.groq.com",),
    ),
    RadarSource(
        "gemini-free-tier",
        "Gemini Developer API Pricing",
        "https://ai.google.dev/gemini-api/docs/pricing",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("ai.google.dev",),
    ),
    RadarSource(
        "cloudflare-workers-ai",
        "Cloudflare Workers AI Pricing",
        "https://developers.cloudflare.com/workers-ai/platform/pricing/",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("developers.cloudflare.com",),
    ),
    RadarSource(
        "huggingface-zerogpu",
        "Hugging Face ZeroGPU",
        "https://huggingface.co/docs/hub/main/spaces-zerogpu",
        "official",
        "gpu",
        "official_page",
        24,
        "html",
        ("huggingface.co",),
    ),
    RadarSource(
        "modal-pricing",
        "Modal Pricing",
        "https://modal.com/pricing",
        "official",
        "gpu",
        "official_page",
        24,
        "html",
        ("modal.com",),
    ),
    RadarSource(
        "runpod-gpu-pricing",
        "RunPod GPU Pricing",
        "https://www.runpod.io/gpu-instance/pricing",
        "official",
        "pricing",
        "official_page",
        24,
        "html",
        ("www.runpod.io", "runpod.io"),
    ),
    RadarSource(
        "lambda-gpu-pricing",
        "Lambda GPU Cloud Pricing",
        "https://lambda.ai/service/gpu-cloud",
        "official",
        "pricing",
        "official_page",
        24,
        "html",
        ("lambda.ai",),
    ),
    RadarSource(
        "vast-gpu-pricing",
        "Vast.ai Live GPU Pricing",
        "https://vast.ai/pricing",
        "official",
        "pricing",
        "official_page",
        24,
        "html",
        ("vast.ai",),
    ),
    RadarSource(
        "lightning-pricing",
        "Lightning AI Pricing",
        "https://lightning.ai/v1/billing/subscription/quote?orgId=&tier=Free",
        "official",
        "gpu",
        "official_page",
        24,
        "json",
        ("lightning.ai",),
    ),
    RadarSource(
        "kaggle-gpu",
        "Kaggle GPU Usage",
        "https://www.kaggle.com/api/i/cms.LegacyCmsService/GetPage?slug=docs%2Fefficient-gpu-usage&isEditing=false",
        "official",
        "gpu",
        "official_page",
        24,
        "json",
        ("www.kaggle.com", "kaggle.com"),
    ),
    RadarSource(
        "colab-faq",
        "Google Colab FAQ",
        "https://research.google.com/colaboratory/faq.html",
        "official",
        "gpu",
        "official_page",
        24,
        "html",
        ("research.google.com",),
    ),
    RadarSource(
        "mnfst-free-llm-apis",
        "awesome-free-llm-apis",
        "https://raw.githubusercontent.com/mnfst/awesome-free-llm-apis/main/data.json",
        "CC0-1.0",
        "token",
        "community",
        168,
        "json",
        ("raw.githubusercontent.com",),
    ),
    RadarSource(
        "pydantic-genai-prices",
        "genai-prices",
        "https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data.json",
        "MIT",
        "pricing",
        "community",
        24,
        "json",
        ("raw.githubusercontent.com",),
    ),
)
SOURCE_BY_ID = {source.id: source for source in SOURCES}


OFFICIAL_GUIDES: dict[str, dict[str, Any]] = {
    "OpenRouter": {
        "benefit_summary": "每天共享 50 次免费请求，可直接调用带 :free 标记的模型；不是每个模型各 50 次。",
        "best_for": "快速试用不同厂商的文本、多模态和嵌入模型。",
        "action_label": "去创建 API Key",
        "action_url": "https://openrouter.ai/settings/keys",
        "usage_steps": [
            "注册或登录 OpenRouter。",
            "在 Keys 页面创建一个 API Key。",
            "选择带 :free 标记的模型，或使用 openrouter/free 路由。",
            "按 OpenAI 兼容接口发起请求，免费请求从共享日额度中扣除。",
        ],
        "caveats": [
            "50 次是免费模型共享日额度，不是每个模型分别计算。",
            "免费模型可能因上游容量临时不可用，购买额度后请求上限可能提高。",
        ],
    },
    "Groq": {
        "benefit_summary": "免费 API 按模型提供 RPM、RPD、TPM 和 TPD 限额，适合低延迟推理与开发测试。",
        "best_for": "需要高速文本生成、语音或开源模型 API 的开发测试。",
        "action_label": "去创建 API Key",
        "action_url": "https://console.groq.com/keys",
        "usage_steps": [
            "注册或登录 GroqCloud Console。",
            "在 API Keys 页面创建密钥。",
            "从免费计划限额表中选择适合的模型。",
            "使用官方 SDK 或 OpenAI 兼容接口调用，并在控制台查看用量。",
        ],
        "caveats": [
            "不同模型的每分钟、每日请求和 Token 限额不同。",
            "限额可能按组织和账号状态调整，以控制台显示为准。",
        ],
    },
    "Google Gemini": {
        "benefit_summary": "部分 Gemini 模型提供免费 API 层；可用模型和实际限额以 AI Studio 项目页面为准。",
        "best_for": "体验 Gemini 文本和多模态能力，或开发小流量原型。",
        "action_label": "打开 AI Studio",
        "action_url": "https://aistudio.google.com/apikey",
        "usage_steps": [
            "登录 Google AI Studio。",
            "创建或选择一个项目并生成 API Key。",
            "确认目标模型标有 Free Tier，并查看项目当前限额。",
            "使用 Gemini SDK 或 REST API 调用，在 AI Studio 监控用量。",
        ],
        "caveats": [
            "只有部分模型包含免费层，账号实际额度可能不同。",
            "官方地区政策未包含中国大陆，页面会默认过滤此项。",
        ],
    },
    "Cloudflare": {
        "benefit_summary": "Workers Free 计划每天赠送 10,000 Neurons，用于 Workers AI 模型推理。",
        "best_for": "把 AI 推理接入 Worker、边缘接口或轻量应用。",
        "action_label": "打开 Workers AI",
        "action_url": "https://dash.cloudflare.com/?to=/:account/ai/workers-ai",
        "usage_steps": [
            "注册或登录 Cloudflare Dashboard。",
            "进入 Workers AI，选择一个模型并创建调用。",
            "可以在控制台试运行，也可以通过 Worker、REST API 或 SDK 接入。",
            "用量从当日免费 Neurons 中扣除，并在 00:00 UTC 重置。",
        ],
        "caveats": [
            "Neurons 是按模型计算量计费的单位，不等于固定请求次数。",
            "不同模型每次推理消耗的 Neurons 不同。",
        ],
    },
    "Hugging Face": {
        "benefit_summary": "免费账号每天有 5 分钟 ZeroGPU 配额，可运行使用共享高显存 GPU 的 Space。",
        "best_for": "短时间体验图像、音频和生成式 AI Demo。",
        "action_label": "查看 ZeroGPU 指南",
        "action_url": "https://huggingface.co/docs/hub/main/spaces-zerogpu",
        "usage_steps": [
            "注册或登录 Hugging Face。",
            "打开一个标有 ZeroGPU 的 Space。",
            "按页面说明运行 GPU 功能；繁忙时需要排队。",
            "运行时间从每日配额扣除，次日恢复。",
        ],
        "caveats": [
            "免费账号每天只有 5 分钟，排队和冷启动时间会影响体验。",
            "自行托管 ZeroGPU Space 还受账号信誉和托管数量条件限制。",
        ],
    },
    "Modal": {
        "benefit_summary": "Starter 计划每月赠送 $30 云算力额度，可用于 CPU、GPU 和 Serverless 任务。",
        "best_for": "运行脚本、批处理、模型推理或短时 GPU 任务。",
        "action_label": "开始使用 Modal",
        "action_url": "https://modal.com/docs/guide",
        "usage_steps": [
            "注册 Modal 并创建 Starter 工作区。",
            "安装 Modal Python 包并在本机完成登录。",
            "按官方示例定义函数，需要 GPU 时指定 GPU 型号。",
            "运行任务，费用自动从每月 $30 免费额度中扣除。",
        ],
        "caveats": [
            "可运行多久取决于所选 CPU、GPU 型号和实际运行时间。",
            "免费额度按月恢复，使用前应在用量页面确认剩余额度。",
        ],
    },
    "Modal:grant": {
        "benefit_summary": "符合条件的研究生、实验室和研究人员可申请最高 $10,000 学术算力资助。",
        "best_for": "有明确研究项目、需要较大规模云算力的学术团队。",
        "action_label": "查看并申请资助",
        "action_url": "https://modal.com/pricing",
        "usage_steps": [
            "准备研究方向、预计算力用途和项目周期说明。",
            "打开 Modal 学术资助入口并提交申请。",
            "等待资格审核；获批后额度会发放到对应工作区。",
        ],
        "caveats": [
            "这不是注册即送，需要提交申请并通过审核。",
            "最终额度和适用范围以 Modal 审批结果为准。",
        ],
    },
    "Lightning AI": {
        "benefit_summary": "Free 计划每月赠送 $15 credits，可在 Studio 中用于 CPU 或 GPU 机器。",
        "best_for": "在云端 Notebook 或 Studio 中做实验和轻量训练。",
        "action_label": "打开 Lightning Studios",
        "action_url": "https://lightning.ai/studios",
        "usage_steps": [
            "注册或登录 Lightning AI。",
            "创建一个 Studio，并选择所需的机器类型。",
            "启动 Notebook、训练或推理任务。",
            "在账单与用量页面监控每月 credits，任务结束后及时停止机器。",
        ],
        "caveats": [
            "GPU 时长取决于机型单价，$15 不代表固定小时数。",
            "持续运行的 Studio 会继续消耗额度，使用后要停止实例。",
        ],
    },
    "Kaggle": {
        "benefit_summary": "Kaggle Notebooks 通常每周提供约 30 小时免费 GPU，官方说明额度可能随供需上浮。",
        "best_for": "Notebook 实验、课程练习、数据竞赛和中小规模训练。",
        "action_label": "创建 Kaggle Notebook",
        "action_url": "https://www.kaggle.com/code",
        "usage_steps": [
            "注册或登录 Kaggle。",
            "创建一个新的 Notebook。",
            "在 Notebook 设置中把 Accelerator 改为 GPU。",
            "启动会话并运行代码；不用时关闭会话以节省周额度。",
        ],
        "caveats": [
            "GPU 型号和可用性由平台分配，不能保证每次相同。",
            "每周额度可能随供需变化，准确剩余时间以 Notebook 页面为准。",
        ],
    },
    "Google Colab": {
        "benefit_summary": "免费使用托管 Notebook，并有机会连接 GPU 或 TPU；资源型号和使用时长不保证。",
        "best_for": "临时 Notebook、教学演示和不要求稳定算力的实验。",
        "action_label": "打开 Google Colab",
        "action_url": "https://colab.research.google.com/",
        "usage_steps": [
            "登录 Google 账号并打开 Colab。",
            "新建或打开一个 Notebook。",
            "在运行时设置中选择 GPU 或 TPU 加速器。",
            "连接运行时；如果免费资源不可用，需要稍后重试或改用 CPU。",
        ],
        "caveats": [
            "免费 GPU/TPU 不保证可用，型号、时长和限制会动态变化。",
            "官方地区政策未包含中国大陆，页面会默认过滤此项。",
        ],
    },
}


def official_guide(provider: str, offer_type: str) -> dict[str, Any]:
    """Return presentation guidance derived from the verified provider policy."""
    key = f"{provider}:grant" if offer_type == "grant" else provider
    return dict(OFFICIAL_GUIDES.get(key, {}))


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
) -> OfferObservation:
    normalized_details = (
        official_guide(provider, offer_type)
        if offer_type != "pricing_reference"
        else {}
    )
    normalized_details.update(details or {})
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
                    },
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
    "huggingface-zerogpu": parse_huggingface,
    "modal-pricing": parse_modal,
    "runpod-gpu-pricing": parse_runpod_pricing,
    "lambda-gpu-pricing": parse_lambda_pricing,
    "vast-gpu-pricing": parse_vast_pricing,
    "lightning-pricing": parse_lightning,
    "kaggle-gpu": parse_kaggle,
    "colab-faq": parse_colab,
    "mnfst-free-llm-apis": parse_mnfst,
    "pydantic-genai-prices": parse_prices,
}


def parse_source(
    source: RadarSource, payload: bytes
) -> tuple[OfferObservation, ...]:
    return PARSERS[source.id](payload, source)
