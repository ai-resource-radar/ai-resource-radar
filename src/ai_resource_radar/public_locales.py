"""Stable, hand-written presentation copy for the public radar export.

The database remains the canonical source of facts.  This module only adds a
small presentation layer to public records; it deliberately does not attempt
to translate dynamic provider/model names or source content.
"""

from __future__ import annotations

from typing import Any


SUPPORTED_LOCALES = ("zh-CN", "en")
DEFAULT_LOCALE = "zh-CN"
FALLBACK_LOCALE = "en"


def _guide(
    zh_benefit: str,
    en_benefit: str,
    zh_best_for: str,
    en_best_for: str,
    zh_steps: tuple[str, ...],
    en_steps: tuple[str, ...],
    zh_caveats: tuple[str, ...],
    en_caveats: tuple[str, ...],
    zh_action: str,
    en_action: str,
) -> dict[str, dict[str, Any]]:
    return {
        "zh-CN": {
            "benefit_summary": zh_benefit,
            "best_for": zh_best_for,
            "usage_steps": list(zh_steps),
            "caveats": list(zh_caveats),
            "action_label": zh_action,
        },
        "en": {
            "benefit_summary": en_benefit,
            "best_for": en_best_for,
            "usage_steps": list(en_steps),
            "caveats": list(en_caveats),
            "action_label": en_action,
        },
    }


# Keys are intentionally stable provider/source identifiers rather than
# generated prose.  The provider and title checks below provide compatibility
# with old databases that predate ``offer_evidence.source_id``.
_BUILTIN_GUIDES: dict[str, dict[str, dict[str, Any]]] = {
    "openrouter-models": _guide(
        "通过 OpenRouter 访问免费模型共享额度。",
        "Access free models on OpenRouter with a shared free allowance.",
        "快速比较多个开源模型",
        "Comparing several open models quickly",
        ("打开官方模型目录。", "选择标记为 free 的模型。", "按页面提示创建 API key。"),
        ("Open the official model catalog.", "Choose a model marked free.", "Create an API key as instructed."),
        ("共享额度和模型列表会变化。",),
        ("Shared limits and the model list can change.",),
        "打开官方页面",
        "Open official page",
    ),
    "groq-free-limits": _guide(
        "Groq Free Plan 提供按模型区分的免费 API 速率额度。",
        "Groq Free Plan provides model-specific free API rate limits.",
        "低延迟文本推理原型",
        "Low-latency text inference prototypes",
        ("查看 Free Plan Limits 表。", "选择符合速率限制的模型。", "创建 Groq API key 并调用 API。"),
        ("Read the Free Plan Limits table.", "Choose a model that fits the limits.", "Create a Groq API key and call the API."),
        ("RPM/RPD/TPM/TPD 会按模型变化。",),
        ("RPM/RPD/TPM/TPD vary by model.",),
        "查看官方限制",
        "View official limits",
    ),
    "gemini-free-tier": _guide(
        "Gemini Developer API 为部分模型提供免费层。",
        "The Gemini Developer API offers a free tier for selected models.",
        "快速构建多模态原型",
        "Fast multimodal prototypes",
        ("打开 Google AI Studio。", "选择支持免费层的模型。", "按项目页面显示的配额调用 API。"),
        ("Open Google AI Studio.", "Choose a model with a free tier.", "Use the quota shown for your project."),
        ("免费层仅覆盖部分模型，地区和项目规则可能不同。",),
        ("The free tier covers selected models; region and project rules may differ.",),
        "查看免费层",
        "View free tier",
    ),
    "cloudflare-workers-ai": _guide(
        "Workers AI Free 计划每天提供固定 Neurons 分配。",
        "Workers AI Free provides a daily Neurons allocation.",
        "边缘侧 AI 推理和轻量应用",
        "Edge inference and lightweight apps",
        ("创建 Cloudflare 账户。", "启用 Workers AI。", "在每日配额内部署或调用模型。"),
        ("Create a Cloudflare account.", "Enable Workers AI.", "Deploy or call a model within the daily allocation."),
        ("额度按 UTC 每日重置，模型消耗不同。",),
        ("The allocation resets daily in UTC and model usage differs.",),
        "查看官方额度",
        "View official allocation",
    ),
    "zhipu-cogview-3-flash": _guide(
        "CogView-3-Flash 提供官方免费图像生成 API。",
        "CogView-3-Flash provides an official free image-generation API.",
        "中文提示词图像生成",
        "Image generation from Chinese prompts",
        ("注册并创建智谱 API key。", "调用图像生成接口。", "按控制台返回结果下载图片。"),
        ("Register and create a Zhipu API key.", "Call the image-generation endpoint.", "Download the image returned by the console."),
        ("官方未公布固定日额度，以账号速率限制为准。",),
        ("No fixed daily quota is published; account rate limits apply.",),
        "开始图像生成",
        "Start image generation",
    ),
    "huggingface-zerogpu": _guide(
        "ZeroGPU 为免费账户提供每日 GPU 分钟额度。",
        "ZeroGPU gives free accounts a daily GPU-minute allowance.",
        "试用开源模型和 Spaces",
        "Trying open models and Spaces",
        ("登录 Hugging Face。", "打开 ZeroGPU Space。", "在每日 GPU 分钟内运行任务。"),
        ("Sign in to Hugging Face.", "Open a ZeroGPU Space.", "Run jobs within the daily GPU-minute allowance."),
        ("可用 GPU 和托管权限取决于账户状态。",),
        ("Available GPUs and hosting permissions depend on account status.",),
        "打开 ZeroGPU",
        "Open ZeroGPU",
    ),
    "modal-pricing": _guide(
        "Modal Starter 每月提供 GPU 计算额度。",
        "Modal Starter includes monthly GPU compute credit.",
        "短期 GPU 任务和 Serverless 原型",
        "Short GPU jobs and serverless prototypes",
        ("创建 Modal 账户。", "选择 Starter 计划。", "按 GPU 单价消耗每月计算额度。"),
        ("Create a Modal account.", "Choose the Starter plan.", "Use the monthly credit at the selected GPU rate."),
        ("额度按所选 GPU 单价折算，计划条款可能更新。",),
        ("Credit duration depends on the selected GPU rate and plan terms may change.",),
        "查看 Modal 计划",
        "View Modal plan",
    ),
    "modal-academic-grant": _guide(
        "Modal Academic Compute Grant 面向研究者提供一次性计算资助。",
        "Modal Academic Compute Grant offers one-time compute support for researchers.",
        "学术研究和实验项目",
        "Academic research and experiments",
        ("确认申请资格。", "准备研究项目说明。", "通过官方页面提交申请。"),
        ("Check eligibility.", "Prepare a research-project description.", "Submit an application through the official page."),
        ("需要审核，资助金额和资格以官方申请结果为准。",),
        ("Approval is required; amount and eligibility follow the official application.",),
        "申请资助",
        "Apply for grant",
    ),
    "lightning-pricing": _guide(
        "Lightning AI 免费层提供有限 GPU 云端额度。",
        "Lightning AI's free tier provides limited cloud GPU capacity.",
        "快速试验 Lightning Studios",
        "Quick experiments in Lightning Studios",
        ("创建 Lightning AI 账户。", "打开 Studio 或 GPU 云页面。", "按免费层额度运行短任务。"),
        ("Create a Lightning AI account.", "Open a Studio or cloud GPU page.", "Run short jobs within the free-tier allowance."),
        ("免费额度、排队和 GPU 类型取决于当前计划。",),
        ("Free capacity, queueing, and GPU types depend on the current plan.",),
        "查看免费层",
        "View free tier",
    ),
    "kaggle-gpu": _guide(
        "Kaggle Notebooks 提供受限的免费 GPU 会话。",
        "Kaggle Notebooks provides limited free GPU sessions.",
        "公开数据集实验和 Notebook 原型",
        "Experiments with public datasets and notebook prototypes",
        ("登录 Kaggle。", "创建或打开 Notebook。", "在配额和会话时长内选择 GPU。"),
        ("Sign in to Kaggle.", "Create or open a Notebook.", "Select a GPU within the quota and session limits."),
        ("GPU 类型、时长和周配额会变化，空闲会话可能被回收。",),
        ("GPU type, duration, and weekly quota can change; idle sessions may be reclaimed.",),
        "打开 Kaggle GPU",
        "Open Kaggle GPU",
    ),
    "colab-faq": _guide(
        "Google Colab 提供按账户和资源供给变化的免费 GPU 运行时。",
        "Google Colab offers free GPU runtimes subject to account and capacity limits.",
        "交互式 Notebook 和教学实验",
        "Interactive notebooks and teaching experiments",
        ("打开 Google Colab。", "创建 Notebook 并选择 GPU 运行时。", "在可用会话时间内运行代码。"),
        ("Open Google Colab.", "Create a notebook and choose a GPU runtime.", "Run code within the available session time."),
        ("免费 GPU 不保证随时可用，运行时会话和配额由 Colab 决定。",),
        ("Free GPUs are not guaranteed; Colab controls runtime sessions and quotas.",),
        "打开 Colab",
        "Open Colab",
    ),
}


def _generic(kind: str, *, pricing: bool = False) -> dict[str, dict[str, Any]]:
    if pricing:
        return _guide(
            "公开价格基线，实际账单请以供应商页面为准。",
            "A public pricing baseline; verify billing on the provider page.",
            "比较价格和规格",
            "Comparing prices and specifications",
            ("查看价格行。", "按模型或 GPU 筛选。", "打开供应商页面复核。"),
            ("Review the price rows.", "Filter by model or GPU.", "Verify details on the provider page."),
            ("价格、库存和区域可用性会变化。",),
            ("Prices, inventory, and regional availability can change.",),
            "查看价格",
            "View pricing",
        )
    labels = {
        "token": (
            "公开的 Token 免费额度。",
            "A public free-token allowance.",
            "文本或多模态 API 原型",
            "Text or multimodal API prototypes",
            "打开官方页面",
            "Open official page",
        ),
        "gpu": (
            "公开的 GPU 免费额度或试用。",
            "A public GPU free allowance or trial.",
            "试用 GPU 计算",
            "Trying GPU compute",
            "打开官方页面",
            "Open official page",
        ),
        "grant": (
            "公开的计算资助或申请机会。",
            "A public compute grant or application opportunity.",
            "研究项目申请",
            "Research-project applications",
            "查看申请要求",
            "View requirements",
        ),
    }
    zh, en, zh_best, en_best, zh_action, en_action = labels.get(
        kind, labels["token"]
    )
    return _guide(
        zh,
        en,
        zh_best,
        en_best,
        ("查看供应商页面。", "确认资格和额度。", "按官方说明开始使用。"),
        ("Open the provider page.", "Confirm eligibility and limits.", "Start according to the official instructions."),
        ("动态条目仅保留规范名称和通用提示。",),
        ("Dynamic entries retain canonical names and generic guidance.",),
        zh_action,
        en_action,
    )


def _stable_key(record: dict[str, Any]) -> tuple[str, str, str]:
    provider = str(record.get("provider") or "").casefold()
    title = str(record.get("title") or "").casefold()
    source = str(record.get("source_id") or "").casefold()
    return source, title, provider


def presentation_for(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return deterministic bilingual presentation copy for one public row."""

    source, title, provider = _stable_key(record)
    kind = str(record.get("kind") or "token")
    offer_type = str(record.get("offer_type") or "")
    pricing = offer_type == "pricing_reference"
    if pricing:
        return _generic(kind, pricing=True)
    if str(record.get("verification_level") or "") not in {
        "official_api",
        "official_page",
    }:
        return _generic(kind)

    # Exact source/offer mappings are preferred.  The provider/title fallback
    # keeps records from pre-v0.3 databases stable when evidence is absent.
    if "academic" in title and provider == "modal":
        return _BUILTIN_GUIDES["modal-academic-grant"]
    if source in _BUILTIN_GUIDES:
        return _BUILTIN_GUIDES[source]
    provider_keys = {
        "openrouter": "openrouter-models",
        "groq": "groq-free-limits",
        "google gemini": "gemini-free-tier",
        "cloudflare": "cloudflare-workers-ai",
        "zhipu ai": "zhipu-cogview-3-flash",
        "hugging face": "huggingface-zerogpu",
        "modal": "modal-pricing",
        "lightning ai": "lightning-pricing",
        "kaggle": "kaggle-gpu",
        "google colab": "colab-faq",
    }
    key = provider_keys.get(provider)
    if key:
        return _BUILTIN_GUIDES[key]
    return _generic(kind)


def localized_presentation(
    record: dict[str, Any], *, locale: str = DEFAULT_LOCALE
) -> dict[str, Any]:
    """Return one locale's copy with an explicit fallback for unknown locales."""

    catalog = presentation_for(record)
    selected = locale if locale in SUPPORTED_LOCALES else FALLBACK_LOCALE
    return dict(catalog.get(selected) or catalog[FALLBACK_LOCALE])


__all__ = [
    "DEFAULT_LOCALE",
    "FALLBACK_LOCALE",
    "SUPPORTED_LOCALES",
    "localized_presentation",
    "presentation_for",
]
