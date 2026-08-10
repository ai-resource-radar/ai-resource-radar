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
    # These fields deliberately distinguish accepting images (vision input)
    # from generating images (image output).
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()


_MODALITY_ALIASES = {
    "images": "image",
    "image-generation": "image",
    "image_generation": "image",
    "text-to-image": "image",
    "text_to_image": "image",
    "embedding": "embeddings",
}


def normalize_modalities(value: Any) -> tuple[str, ...]:
    """Return a stable, lowercase modality tuple from catalog values."""

    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    normalized: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        for token in re.split(r"\s*(?:\+|,|/|\||;)\s*", item.strip()):
            token = token.casefold().replace(" ", "-")
            if not token:
                continue
            token = _MODALITY_ALIASES.get(token, token)
            if token not in normalized:
                normalized.append(token)
    return tuple(normalized)


def resolve_modalities(
    details: dict[str, Any] | None = None,
    *,
    input_modalities: Any = None,
    output_modalities: Any = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve explicit modality fields and conservative catalog fallbacks.

    A generic ``modality`` field is used only as an input hint. This prevents a
    vision model from being incorrectly advertised as an image generator.
    """

    details = details or {}
    inputs = normalize_modalities(input_modalities)
    if not inputs:
        inputs = normalize_modalities(
            details.get("input_modalities", details.get("input_modality"))
        )
    if not inputs:
        inputs = normalize_modalities(details.get("modality"))
    outputs = normalize_modalities(output_modalities)
    if not outputs:
        outputs = normalize_modalities(
            details.get("output_modalities", details.get("output_modality"))
        )
    return inputs, outputs


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
        "zhipu-cogview-3-flash",
        "Zhipu AI CogView-3-Flash",
        "https://docs.bigmodel.cn/cn/guide/models/free/cogview-3-flash",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("docs.bigmodel.cn",),
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
        "sambanova-free-tier",
        "SambaNova Free Tier Limits",
        "https://docs.sambanova.ai/docs/en/models/rate-limits",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("docs.sambanova.ai",),
    ),
    RadarSource(
        "mistral-free-mode",
        "Mistral Studio Free Mode",
        "https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("docs.mistral.ai",),
    ),
    RadarSource(
        "huggingface-inference-credits",
        "Hugging Face Inference Credits",
        "https://huggingface.co/docs/inference-providers/en/pricing",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("huggingface.co",),
    ),
    RadarSource(
        "siliconflow-free-models",
        "SiliconFlow Free Models",
        "https://docs.siliconflow.cn/cn/userguide/rate-limits/rate-limit-and-upgradation",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("docs.siliconflow.cn",),
    ),
    RadarSource(
        "alibaba-model-studio-trial",
        "Alibaba Model Studio New-user Quota",
        "https://help.aliyun.com/zh/model-studio/new-free-quota/",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("help.aliyun.com",),
    ),
    RadarSource(
        "cerebras-free-trial",
        "Cerebras Free Trial",
        "https://inference-docs.cerebras.ai/support/rate-limits",
        "official",
        "token",
        "official_page",
        24,
        "html",
        ("inference-docs.cerebras.ai",),
    ),
    RadarSource(
        "replicate-pricing",
        "Replicate Pricing",
        "https://replicate.com/pricing",
        "official",
        "pricing",
        "official_page",
        24,
        "html",
        ("replicate.com",),
    ),
    RadarSource(
        "baseten-pricing",
        "Baseten Pricing",
        "https://www.baseten.co/pricing/",
        "official",
        "pricing",
        "official_page",
        24,
        "html",
        ("www.baseten.co", "baseten.co"),
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
    "Zhipu AI": {
        "benefit_summary": "CogView-3-Flash 提供官方免费的文生图 API；官方未公布固定日额度，以账号速率限制为准。",
        "best_for": "中文提示词的图片生成、原型验证和低成本 API 接入。",
        "action_label": "打开智谱 API 控制台",
        "action_url": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "usage_steps": [
            "注册或登录智谱开放平台。",
            "在 API Keys 页面创建密钥。",
            "调用图像生成接口并选择 cogview-3-flash 模型。",
            "在控制台查看账号当前速率限制和使用情况。",
        ],
        "caveats": [
            "模型免费，但官方未公布固定每日额度。",
            "实际可用频率以账号显示的速率限制为准。",
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
    "SambaNova": {
        "benefit_summary": "未绑定付款方式的账号自动使用 Free Tier；官方按模型给出 RPM、RPD 和每日 Token 上限。",
        "best_for": "免费试用高速开源大模型 API，并明确控制每日请求与 Token 用量。",
        "action_label": "打开 SambaCloud",
        "action_url": "https://cloud.sambanova.ai/",
        "usage_steps": [
            "注册 SambaCloud，保持账号不绑定付款方式。",
            "创建 API Key，并在官方免费层表中选择模型。",
            "通过 OpenAI 兼容接口调用。",
            "读取响应中的限流头，避免超过 RPM、RPD 或 TPD。",
        ],
        "caveats": [
            "免费层限制按模型执行，任一 RPM、RPD 或 TPD 先达到都会限流。",
            "预览模型可能短期下架，不应作为生产依赖。",
        ],
    },
    "Mistral AI": {
        "benefit_summary": "Studio Free mode 默认开放 API，无需信用卡；用量和限速以账号控制台为准。",
        "best_for": "快速测试 Mistral 文本模型和 OpenAI 兼容 API。",
        "action_label": "打开 Mistral Studio",
        "action_url": "https://console.mistral.ai/",
        "usage_steps": [
            "注册或登录 Mistral Studio。",
            "在 API Keys 页面创建密钥。",
            "确认工作区处于 Free mode。",
            "使用官方 SDK 或兼容接口调用，并在控制台查看实际限额。",
        ],
        "caveats": [
            "官方未在该页面公布统一固定额度，不同账号显示可能不同。",
            "Free mode 仍受用量和速率限制。",
        ],
    },
    "Hugging Face Inference": {
        "benefit_summary": "免费用户每月获得 $0.10 Inference Providers credits，额度会自动用于 Hugging Face 路由请求。",
        "best_for": "用一个 Hugging Face Token 小量体验多个推理提供商。",
        "action_label": "打开 Inference Providers",
        "action_url": "https://huggingface.co/settings/inference-providers",
        "usage_steps": [
            "注册或登录 Hugging Face。",
            "创建 User Access Token。",
            "使用 InferenceClient 并通过 Hugging Face 路由目标模型。",
            "在账单页查看本月 credits 和消耗。",
        ],
        "caveats": [
            "免费用户月额度目前为 $0.10，官方明确注明可能调整。",
            "使用自带 Provider Key 时不会消耗这笔 Hugging Face credits。",
        ],
    },
    "SiliconFlow": {
        "benefit_summary": "完成实名认证后可调用平台免费模型，调用费用为 0；固定限速按具体模型展示。",
        "best_for": "中国大陆开发者试用文本、嵌入、重排和部分多模态 API。",
        "action_label": "打开模型广场",
        "action_url": "https://cloud.siliconflow.cn/models",
        "usage_steps": [
            "注册 SiliconFlow 并完成实名认证。",
            "在模型广场选择未带 Pro/ 前缀的免费模型。",
            "创建 API Key 后按官方接口调用。",
            "在模型详情中查看该模型固定 Rate Limits。",
        ],
        "caveats": [
            "必须实名认证后才能使用全部免费模型。",
            "免费模型固定限额因模型而异，官方总览未公布统一额度。",
        ],
    },
    "Alibaba Model Studio": {
        "benefit_summary": "首次开通百炼后，各参与模型通常各有 100 万 Token、90 天有效的一次性新人额度。",
        "best_for": "在中国大陆测试通义及百炼模型 API。",
        "action_label": "打开百炼免费额度",
        "action_url": "https://bailian.console.aliyun.com/?tab=model#/model-market/free-quota",
        "usage_steps": [
            "在华北 2（北京）地域首次开通阿里云百炼。",
            "在免费额度页确认具体模型的额度与到期日。",
            "开启“免费额度用完即停”，再创建 API Key 调用。",
            "持续查看剩余额度，避免过期或耗尽后的按量费用。",
        ],
        "caveats": [
            "这是 90 天一次性新人额度，不会重置或补发。",
            "已认证账号默认可能在额度耗尽后继续扣费，应主动开启用完即停。",
        ],
    },
    "Cerebras": {
        "benefit_summary": "添加已验证付款方式后获得 $5 credits，30 天到期；不是周期性永久免费层。",
        "best_for": "短期评估 Cerebras 高速推理 API。",
        "action_label": "打开 Cerebras Cloud",
        "action_url": "https://cloud.cerebras.ai/",
        "usage_steps": [
            "注册 Cerebras Cloud。",
            "添加并验证付款方式以激活 Free Trial。",
            "创建 API Key，并在 30 天内使用 $5 credits。",
            "额度用完后停止；只有主动购买 credits 才会继续。",
        ],
        "caveats": [
            "必须验证付款方式，未验证时 Playground 和 API 不可用。",
            "官方明确没有永久免费层，$5 credits 在 30 天后失效。",
        ],
    },
    "Baseten": {
        "benefit_summary": "新账号有未公布金额的实验 credits；正式服务按 Model API Token 或 GPU 分钟计费。",
        "best_for": "试用预优化 Model API 或部署自定义 GPU 推理。",
        "action_label": "打开 Baseten",
        "action_url": "https://app.baseten.co/",
        "usage_steps": [
            "注册 Baseten 并在账号内确认新用户 credits。",
            "选择 Model API 或 GPU 实例。",
            "调用前核对每百万 Token 或每分钟 GPU 单价。",
            "实验结束后检查 credits 与账单。",
        ],
        "caveats": [
            "官方确认有新账号 credits，但没有公开固定金额。",
            "credits 用尽后按公开价格计费，不属于永久免费层。",
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
    input_modalities: Any = None,
    output_modalities: Any = None,
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
