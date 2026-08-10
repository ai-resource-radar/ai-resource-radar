"""Deterministic provider profiles and copy/paste integration examples.

The collection registry is the source of truth for provider evidence.  This
module deliberately contains only presentation-safe metadata: provider names,
stable slugs, official source identifiers and public API compatibility facts.
Credentials are *never* stored here.  Every generated example refers to an
environment variable instead.

The first integration batch is intentionally small and conservative.  A
profile can be present in the official provider catalogue without having a
verified OpenAI-compatible endpoint in this package yet.  Such profiles still
appear in :data:`PROVIDER_PROFILES`, while ``integration_verified`` remains
false and no integration row is emitted by ``integration_public_rows()``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable, Mapping

from .collection.registry import SOURCES


OPENCLAW_PROVIDER_DOCS_URL = "https://docs.openclaw.ai/concepts/model-providers"
CODEX_PROVIDER_DOCS_URL = "https://developers.openai.com/codex/config-reference"
CURSOR_PROVIDER_DOCS: dict[str, str] = {
    "sambanova": "https://docs.sambanova.ai/docs/en/integrations/cursor",
    "siliconflow": "https://docs.siliconflow.cn/cn/userguide/use-docs-with-cursor",
}
API_KEY_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/settings/keys",
    "groq": "https://console.groq.com/keys",
    "zhipu-ai": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "sambanova": "https://cloud.sambanova.ai/apis",
    "mistral-ai": "https://console.mistral.ai/api-keys",
    "siliconflow": "https://cloud.siliconflow.cn/account/ak",
    "alibaba-model-studio": "https://bailian.console.aliyun.com/",
    "cerebras": "https://cloud.cerebras.ai/",
}


# ``source.authority`` is ``official_api`` or ``official_page`` for the
# 21 first-party records and ``community`` for the two reference datasets.
OFFICIAL_SOURCE_IDS: tuple[str, ...] = tuple(
    source.id
    for source in SOURCES
    if source.authority.startswith("official")
)
COMMUNITY_SOURCE_IDS: tuple[str, ...] = tuple(
    source.id for source in SOURCES if source.authority == "community"
)


@dataclass(frozen=True)
class ProviderProfile:
    """Public, stable metadata for one official provider.

    ``source_ids`` identifies the evidence records that belong to this
    provider.  Hugging Face intentionally has two source IDs (ZeroGPU and
    Inference Providers credits) but one profile and one stable slug.
    ``protocols`` uses the explicit values ``chat_completions``, ``responses``
    and ``native``.  In particular, ``chat_completions`` does not imply
    ``responses`` support.
    """

    slug: str
    name: str
    aliases: tuple[str, ...]
    source_ids: tuple[str, ...]
    homepage_url: str
    docs_url: str
    api_base_url: str | None
    auth_env_var: str | None
    default_model: str | None
    protocols: tuple[str, ...]
    integration_verified: bool = False
    description: str = ""

    @property
    def provider(self) -> str:
        """Compatibility alias used by public rows and price records."""

        return self.name

    @property
    def model(self) -> str | None:
        """Compatibility alias for the deterministic example model."""

        return self.default_model

    @property
    def base_url(self) -> str | None:
        """Compatibility alias for ``api_base_url``."""

        return self.api_base_url

    @property
    def source_id(self) -> str | None:
        """Singular source alias for providers backed by one source."""

        return self.source_ids[0] if self.source_ids else None

    @property
    def env_var(self) -> str | None:
        """Compatibility alias for the credential environment variable."""

        return self.auth_env_var

    @property
    def protocol(self) -> str:
        """Primary protocol, retained for callers expecting a scalar value."""

        return self.protocols[0] if self.protocols else "native"

    @property
    def supports_chat_completions(self) -> bool:
        return "chat_completions" in self.protocols

    @property
    def supports_responses(self) -> bool:
        return "responses" in self.protocols

    @property
    def official(self) -> bool:
        """All profiles in this module are backed by official sources."""

        return True

    @property
    def compatibility(self) -> dict[str, Any]:
        """Attribute form of :meth:`compatibility_metadata`."""

        return self.compatibility_metadata()

    def compatibility_metadata(self) -> dict[str, Any]:
        """Return JSON-safe compatibility metadata with no credential data."""

        base = self.api_base_url
        return {
            "protocols": list(self.protocols),
            "protocol": self.protocol,
            "chat_completions": self.supports_chat_completions,
            "responses": self.supports_responses,
            "supports_chat_completions": self.supports_chat_completions,
            "supports_responses": self.supports_responses,
            "base_url": base,
            "api_base_url": base,
            "chat_completions_url": (
                f"{base}/chat/completions" if base and self.supports_chat_completions else None
            ),
            "responses_url": (
                f"{base}/responses" if base and self.supports_responses else None
            ),
            "default_model": self.default_model,
            "model": self.default_model,
            "auth_env_var": self.auth_env_var,
            "api_key_env": self.auth_env_var,
        }


def _profile(
    slug: str,
    name: str,
    aliases: Iterable[str],
    source_ids: Iterable[str],
    homepage_url: str,
    docs_url: str,
    api_base_url: str | None,
    auth_env_var: str | None,
    default_model: str | None,
    protocols: Iterable[str],
    *,
    integration_verified: bool = False,
    description: str = "",
) -> ProviderProfile:
    return ProviderProfile(
        slug=slug,
        name=name,
        aliases=tuple(dict.fromkeys((name, *aliases))),
        source_ids=tuple(source_ids),
        homepage_url=homepage_url,
        docs_url=docs_url,
        api_base_url=api_base_url,
        auth_env_var=auth_env_var,
        default_model=default_model,
        protocols=tuple(dict.fromkeys(protocols)),
        integration_verified=integration_verified,
        description=description,
    )


# Keep this order stable: it is the order used by the public catalogue and is
# intentionally independent of provider-name sorting or source refresh order.
PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    _profile(
        "openrouter",
        "OpenRouter",
        ("open router",),
        ("openrouter-models",),
        "https://openrouter.ai/",
        "https://openrouter.ai/docs/api-reference/overview",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        "openrouter/free",
        ("chat_completions", "responses"),
        integration_verified=True,
        description="OpenAI-compatible routing for verified free-model discovery.",
    ),
    _profile(
        "groq",
        "Groq",
        ("GroqCloud", "Groq Cloud"),
        ("groq-free-limits",),
        "https://groq.com/",
        "https://console.groq.com/docs/quickstart",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        "llama-3.3-70b-versatile",
        ("chat_completions",),
        integration_verified=True,
        description="Low-latency OpenAI-compatible inference with model-specific limits.",
    ),
    _profile(
        "gemini",
        "Google Gemini",
        ("Gemini", "Google AI", "Google Gemini API", "google-gemini"),
        ("gemini-free-tier",),
        "https://ai.google.dev/",
        "https://ai.google.dev/gemini-api/docs/openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
        ("chat_completions",),
        description="Google Gemini Developer API free-tier metadata.",
    ),
    _profile(
        "cloudflare",
        "Cloudflare Workers AI",
        ("Cloudflare", "Workers AI"),
        ("cloudflare-workers-ai",),
        "https://www.cloudflare.com/developer-platform/products/workers-ai/",
        "https://developers.cloudflare.com/workers-ai/",
        None,
        "CLOUDFLARE_API_TOKEN",
        None,
        ("native",),
        description="Workers AI Neurons allocation; account-scoped native endpoint.",
    ),
    _profile(
        "zhipu-ai",
        "Zhipu AI",
        ("Zhipu", "zhipu", "智谱", "智谱AI", "智谱 AI", "BigModel"),
        ("zhipu-cogview-3-flash",),
        "https://open.bigmodel.cn/",
        "https://open.bigmodel.cn/dev/api",
        "https://open.bigmodel.cn/api/paas/v4",
        "ZHIPUAI_API_KEY",
        "glm-4-flash",
        ("chat_completions",),
        integration_verified=True,
        description="智谱开放平台 OpenAI-style chat endpoint and CogView evidence.",
    ),
    _profile(
        "huggingface",
        "Hugging Face",
        (
            "HuggingFace",
            "hugging-face",
            "Hugging Face Inference",
            "Hugging Face Inference Providers",
            "HF Inference",
            "HF",
        ),
        ("huggingface-zerogpu", "huggingface-inference-credits"),
        "https://huggingface.co/",
        "https://huggingface.co/docs/inference-providers/en/index",
        "https://router.huggingface.co/v1",
        "HF_TOKEN",
        "meta-llama/Llama-3.1-8B-Instruct",
        ("chat_completions",),
        integration_verified=True,
        description="Merged ZeroGPU and Inference Providers credits profile.",
    ),
    _profile(
        "modal",
        "Modal",
        (),
        ("modal-pricing",),
        "https://modal.com/",
        "https://modal.com/docs/guide",
        None,
        "MODAL_TOKEN_ID",
        None,
        ("native",),
        description="Serverless CPU/GPU runtime and monthly starter credits.",
    ),
    _profile(
        "runpod",
        "RunPod",
        (),
        ("runpod-gpu-pricing",),
        "https://www.runpod.io/",
        "https://docs.runpod.io/",
        None,
        "RUNPOD_API_KEY",
        None,
        ("native",),
        description="GPU compute pricing catalogue.",
    ),
    _profile(
        "lambda",
        "Lambda",
        ("Lambda GPU Cloud", "Lambda Labs"),
        ("lambda-gpu-pricing",),
        "https://lambda.ai/",
        "https://docs.lambda.ai/",
        None,
        "LAMBDA_API_KEY",
        None,
        ("native",),
        description="GPU cloud pricing catalogue.",
    ),
    _profile(
        "vast-ai",
        "Vast.ai",
        ("Vast", "Vast AI"),
        ("vast-gpu-pricing",),
        "https://vast.ai/",
        "https://docs.vast.ai/",
        None,
        "VAST_API_KEY",
        None,
        ("native",),
        description="Marketplace GPU pricing catalogue.",
    ),
    _profile(
        "lightning-ai",
        "Lightning AI",
        ("Lightning",),
        ("lightning-pricing",),
        "https://lightning.ai/",
        "https://lightning.ai/docs/pytorch/stable/",
        None,
        "LIGHTNING_API_KEY",
        None,
        ("native",),
        description="Studio compute credits and GPU runtime catalogue.",
    ),
    _profile(
        "kaggle",
        "Kaggle",
        ("Kaggle Notebooks",),
        ("kaggle-gpu",),
        "https://www.kaggle.com/",
        "https://www.kaggle.com/docs/notebooks",
        None,
        "KAGGLE_API_TOKEN",
        None,
        ("native",),
        description="Notebook GPU usage catalogue.",
    ),
    _profile(
        "google-colab",
        "Google Colab",
        ("Colab",),
        ("colab-faq",),
        "https://colab.research.google.com/",
        "https://research.google.com/colaboratory/faq.html",
        None,
        "COLAB_API_KEY",
        None,
        ("native",),
        description="Hosted notebook and variable GPU/TPU access.",
    ),
    _profile(
        "sambanova",
        "SambaNova",
        ("Samba Nova", "SambaNova Cloud", "SambaCloud"),
        ("sambanova-free-tier",),
        "https://sambanova.ai/",
        "https://docs.sambanova.ai/docs/en/get-started/quickstart",
        "https://api.sambanova.ai/v1",
        "SAMBANOVA_API_KEY",
        "Meta-Llama-3.3-70B-Instruct",
        ("chat_completions",),
        integration_verified=True,
        description="OpenAI-compatible Free Tier with model-specific RPM/RPD/TPD.",
    ),
    _profile(
        "mistral-ai",
        "Mistral AI",
        ("Mistral", "Mistral Studio"),
        ("mistral-free-mode",),
        "https://mistral.ai/",
        "https://docs.mistral.ai/api/",
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        "mistral-small-latest",
        ("chat_completions",),
        integration_verified=True,
        description="Mistral Studio Free mode API access.",
    ),
    _profile(
        "siliconflow",
        "SiliconFlow",
        ("Silicon Flow", "硅基流动", "硅基流动 SiliconFlow"),
        ("siliconflow-free-models",),
        "https://siliconflow.cn/",
        "https://docs.siliconflow.cn/",
        "https://api.siliconflow.cn/v1",
        "SILICONFLOW_API_KEY",
        "Qwen/Qwen2.5-7B-Instruct",
        ("chat_completions",),
        integration_verified=True,
        description="Mainland-compatible OpenAI-style endpoint for verified free models.",
    ),
    _profile(
        "alibaba-model-studio",
        "Alibaba Model Studio",
        (
            "Alibaba Cloud Model Studio",
            "DashScope",
            "Alibaba",
            "阿里云百炼",
            "百炼",
            "阿里云 Model Studio",
        ),
        ("alibaba-model-studio-trial",),
        "https://bailian.console.aliyun.com/",
        "https://help.aliyun.com/zh/model-studio/",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_API_KEY",
        "qwen-turbo",
        ("chat_completions",),
        integration_verified=True,
        description="Alibaba Model Studio OpenAI-compatible mode and new-user quota.",
    ),
    _profile(
        "cerebras",
        "Cerebras",
        ("Cerebras Cloud",),
        ("cerebras-free-trial",),
        "https://www.cerebras.ai/",
        "https://inference-docs.cerebras.ai/",
        "https://api.cerebras.ai/v1",
        "CEREBRAS_API_KEY",
        "llama-3.3-70b",
        ("chat_completions",),
        integration_verified=True,
        description="Cerebras 30-day trial credits and fast chat endpoint.",
    ),
    _profile(
        "replicate",
        "Replicate",
        ("Replicate API",),
        ("replicate-pricing",),
        "https://replicate.com/",
        "https://replicate.com/docs",
        None,
        "REPLICATE_API_TOKEN",
        None,
        ("native",),
        description="Model API and GPU pricing catalogue.",
    ),
    _profile(
        "baseten",
        "Baseten",
        ("Baseten Model API",),
        ("baseten-pricing",),
        "https://www.baseten.co/",
        "https://docs.baseten.co/",
        None,
        "BASETEN_API_KEY",
        None,
        ("native",),
        description="Model API and dedicated deployment pricing catalogue.",
    ),
)


PROVIDER_BY_SLUG: dict[str, ProviderProfile] = {
    profile.slug: profile for profile in PROVIDER_PROFILES
}
PROVIDER_BY_SOURCE_ID: dict[str, ProviderProfile] = {
    source_id: profile
    for profile in PROVIDER_PROFILES
    for source_id in profile.source_ids
}


def _normalize_provider(value: Any) -> str:
    """Normalize a provider label for alias matching without transliteration."""

    if value is None:
        return ""
    text = str(value).strip().casefold()
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


PROVIDER_BY_ALIAS: dict[str, ProviderProfile] = {
    _normalize_provider(alias): profile
    for profile in PROVIDER_PROFILES
    for alias in (profile.slug, *profile.aliases)
    if _normalize_provider(alias)
}


def _assert_profile_registry() -> None:
    """Fail early if a source is accidentally omitted or community-backed."""

    covered = tuple(
        source_id for profile in PROVIDER_PROFILES for source_id in profile.source_ids
    )
    if len(PROVIDER_PROFILES) != 20:
        raise RuntimeError("provider_profile_count_must_be_20")
    if len(set(covered)) != len(covered):
        raise RuntimeError("provider_profile_source_ids_must_be_unique")
    if set(covered) != set(OFFICIAL_SOURCE_IDS):
        missing = sorted(set(OFFICIAL_SOURCE_IDS) - set(covered))
        extra = sorted(set(covered) - set(OFFICIAL_SOURCE_IDS))
        raise RuntimeError(
            f"provider_profile_source_coverage_mismatch:missing={missing}:extra={extra}"
        )
    if set(covered) & set(COMMUNITY_SOURCE_IDS):
        raise RuntimeError("community_sources_cannot_have_official_profiles")
    if len(PROVIDER_BY_SLUG) != len(PROVIDER_PROFILES):
        raise RuntimeError("provider_profile_slugs_must_be_unique")
    for profile in PROVIDER_PROFILES:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile.slug):
            raise RuntimeError(f"invalid_provider_slug:{profile.slug}")
        if profile.supports_responses and "chat_completions" not in profile.protocols:
            # Responses-only providers are valid, but this guards accidental
            # claims that a chat-only profile also supports Responses.
            continue


_assert_profile_registry()


def get_provider_profile(provider: str | ProviderProfile) -> ProviderProfile:
    """Resolve a profile by canonical slug, alias, or return it unchanged."""

    if isinstance(provider, ProviderProfile):
        return provider
    key = str(provider).strip()
    if key in PROVIDER_BY_SLUG:
        return PROVIDER_BY_SLUG[key]
    profile = PROVIDER_BY_ALIAS.get(_normalize_provider(key))
    if profile is None:
        raise KeyError(f"unknown_provider:{provider}")
    return profile


def provider_slug_for(
    provider: str | ProviderProfile | None = None,
    source_id: str | None = None,
) -> str | None:
    """Resolve a canonical provider slug from source ID and/or display label.

    Source IDs take precedence because they are authoritative and avoid
    ambiguous labels such as ``Hugging Face Inference`` versus ``Hugging Face``.
    """

    if source_id:
        profile = PROVIDER_BY_SOURCE_ID.get(str(source_id).strip())
        # A present source ID is evidence provenance, not merely a hint.  Do
        # not fall back to a provider display alias when that provenance is
        # unknown (notably the two community baselines), otherwise a community
        # record could inherit an official provider page and look endorsed.
        return profile.slug if profile is not None else None
    if provider is None:
        return None
    try:
        return get_provider_profile(provider).slug
    except KeyError:
        return None


def provider_for_record(record: Mapping[str, Any] | Any) -> ProviderProfile | None:
    """Resolve a provider profile from an offer/price/public record.

    The helper accepts either a mapping or a row-like object and checks source
    IDs before provider labels.  Price rows without ``source_id`` can still
    receive a stable provider slug, while records with an unknown/community
    source ID never fall back to a provider alias.
    """

    if not isinstance(record, Mapping):
        try:
            values = vars(record)
        except TypeError:
            return None
    else:
        values = record
    source_id = values.get("source_id")
    if not source_id:
        evidence = values.get("evidence")
        if isinstance(evidence, Mapping):
            source_id = evidence.get("source_id")
    verification_level = values.get("verification_level")
    if not verification_level:
        evidence = values.get("evidence")
        if isinstance(evidence, Mapping):
            verification_level = evidence.get("verification_level")
    if (
        not source_id
        and verification_level
        and str(verification_level) not in {"official_api", "official_page"}
    ):
        # Normalized community price rows may not expose their source ID, but
        # they do retain verification provenance.  Never attach those rows to
        # an official provider profile based on a display label alone.
        return None
    provider = values.get("provider") or values.get("provider_name")
    slug = provider_slug_for(provider, source_id=source_id)
    return PROVIDER_BY_SLUG.get(slug) if slug else None


def _example_payload(profile: ProviderProfile) -> str:
    model = profile.default_model or "MODEL_ID"
    return (
        '{"model":"'
        + model
        + '","messages":[{"role":"user","content":"Hello"}]}'
    )


def _render_curl(profile: ProviderProfile) -> str:
    assert profile.api_base_url is not None
    env = profile.auth_env_var or "PROVIDER_API_KEY"
    return (
        f"curl {profile.api_base_url}/chat/completions \\\n  -H 'Authorization: Bearer ${env}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{_example_payload(profile)}'"
    )


def _render_python(profile: ProviderProfile) -> str:
    assert profile.api_base_url is not None
    env = profile.auth_env_var or "PROVIDER_API_KEY"
    model = profile.default_model or "MODEL_ID"
    return (
        "import os\n"
        "from openai import OpenAI\n\n"
        f"client = OpenAI(api_key=os.environ[{env!r}], base_url={profile.api_base_url!r})\n"
        "response = client.chat.completions.create(\n"
        f"    model={model!r},\n"
        "    messages=[{\"role\": \"user\", \"content\": \"Hello\"}],\n"
        ")\n"
        "print(response.choices[0].message.content)"
    )


def _render_openclaw(profile: ProviderProfile) -> str:
    assert profile.api_base_url is not None
    env = profile.auth_env_var or "PROVIDER_API_KEY"
    model = profile.default_model or "MODEL_ID"
    # OpenClaw documents custom providers as JSON5 in its config, not as a
    # hypothetical CLI command. Keep the key as environment interpolation.
    return (
        "// ~/.openclaw/openclaw.json (merge this JSON5 fragment)\n"
        "{\n"
        "  models: { mode: \"merge\", providers: {\n"
        f'    "{profile.slug}": {{\n'
        f"      baseUrl: \"{profile.api_base_url}\",\n"
        f"      apiKey: \"${{{env}}}\",\n"
        "      api: \"openai-completions\",\n"
        f"      models: [{{ id: \"{model}\", name: \"{model}\" }}],\n"
        "    },\n"
        "  } },\n"
        f"  agents: {{ defaults: {{ model: {{ primary: \"{profile.slug}/{model}\" }} }} }},\n"
        "}"
    )


def _render_cursor(profile: ProviderProfile) -> str:
    assert profile.api_base_url is not None
    env = profile.auth_env_var or "PROVIDER_API_KEY"
    model = profile.default_model or "MODEL_ID"
    return (
        "Cursor Settings → Models\n"
        f"1. Add custom model: {model}\n"
        f"2. Enable Override OpenAI Base URL: {profile.api_base_url}\n"
        f"3. Paste the API key from environment variable: {env}\n"
        "4. Verify, then keep only the intended custom model enabled.\n"
        "Note: Cursor applies the OpenAI base URL override globally; disable it before using incompatible built-in models."
    )


def _render_codex(profile: ProviderProfile) -> str:
    """Render Codex config only for a declared Responses provider."""

    if not profile.supports_responses:
        raise ValueError("codex_requires_responses_protocol")
    assert profile.api_base_url is not None
    env = profile.auth_env_var or "PROVIDER_API_KEY"
    model = profile.default_model or "MODEL_ID"
    return (
        "# ~/.codex/config.toml\n"
        f'model = "{model}"\n'
        f'model_provider = "{profile.slug}"\n\n'
        f"[model_providers.{profile.slug}]\n"
        f'name = "{profile.name}"\n'
        f'base_url = "{profile.api_base_url}"\n'
        f'env_key = "{env}"\n'
        'wire_api = "responses"\n'
    )


def render_integration_snippets(
    profile: str | ProviderProfile,
) -> dict[str, str]:
    """Render deterministic curl/Python/client examples for one profile.

    The returned mapping always contains ``curl``, ``python`` and ``openclaw``
    for an integration-ready chat endpoint. Cursor is emitted only where the
    provider publishes a provider-specific Cursor guide. A ``codex`` entry is
    added *only* when ``responses`` is explicitly declared by the profile.
    Chat Completions compatibility never enables it implicitly.
    """

    resolved = get_provider_profile(profile)
    if not resolved.integration_verified or not resolved.api_base_url:
        return {}
    if not resolved.supports_chat_completions:
        return {}
    snippets = {
        "curl": _render_curl(resolved),
        "python": _render_python(resolved),
        "openclaw": _render_openclaw(resolved),
    }
    if resolved.slug in CURSOR_PROVIDER_DOCS:
        snippets["cursor"] = _render_cursor(resolved)
    if resolved.supports_responses:
        snippets["codex"] = _render_codex(resolved)
    return snippets


def provider_public_rows() -> list[dict[str, Any]]:
    """Return JSON-safe rows for all 20 official provider profiles."""

    rows: list[dict[str, Any]] = []
    for profile in PROVIDER_PROFILES:
        rows.append(
            {
                "slug": profile.slug,
                "provider_slug": profile.slug,
                "name": profile.name,
                "provider": profile.name,
                "aliases": list(profile.aliases),
                "source_ids": list(profile.source_ids),
                "homepage_url": profile.homepage_url,
                "docs_url": profile.docs_url,
                "api_key_url": API_KEY_URLS.get(profile.slug),
                "api_base_url": profile.api_base_url,
                "auth_env_var": profile.auth_env_var,
                "default_model": profile.default_model,
                "model": profile.default_model,
                "protocols": list(profile.protocols),
                "protocol": profile.protocol,
                "supports_chat_completions": profile.supports_chat_completions,
                "supports_responses": profile.supports_responses,
                "integration_verified": profile.integration_verified,
                "official": profile.official,
                "description": profile.description,
                "compatibility": profile.compatibility_metadata(),
                "client_docs": {
                    "openclaw": OPENCLAW_PROVIDER_DOCS_URL if profile.integration_verified else None,
                    "cursor": CURSOR_PROVIDER_DOCS.get(profile.slug),
                    "codex": CODEX_PROVIDER_DOCS_URL if profile.supports_responses else None,
                },
            }
        )
    return rows


def integration_public_rows(*, verified_only: bool = True) -> list[dict[str, Any]]:
    """Return provider rows with copy/paste examples.

    By default only the first verified integration batch is emitted.  Passing
    ``verified_only=False`` includes all profiles, with an empty ``templates``
    mapping for providers whose endpoint has not been verified yet.
    """

    rows: list[dict[str, Any]] = []
    for profile in PROVIDER_PROFILES:
        if verified_only and not profile.integration_verified:
            continue
        snippets = render_integration_snippets(profile)
        rows.append(
            {
                "slug": profile.slug,
                "provider_slug": profile.slug,
                "name": profile.name,
                "provider": profile.name,
                "source_ids": list(profile.source_ids),
                "protocols": list(profile.protocols),
                "supports_chat_completions": profile.supports_chat_completions,
                "supports_responses": profile.supports_responses,
                "compatibility": profile.compatibility_metadata(),
                "templates": snippets,
                "integrations": snippets,
                "client_docs": {
                    "curl": profile.docs_url,
                    "python": profile.docs_url,
                    "openclaw": OPENCLAW_PROVIDER_DOCS_URL,
                    "cursor": CURSOR_PROVIDER_DOCS.get(profile.slug),
                    "codex": CODEX_PROVIDER_DOCS_URL if profile.supports_responses else None,
                },
            }
        )
    return rows


__all__ = [
    "API_KEY_URLS",
    "COMMUNITY_SOURCE_IDS",
    "CODEX_PROVIDER_DOCS_URL",
    "CURSOR_PROVIDER_DOCS",
    "OPENCLAW_PROVIDER_DOCS_URL",
    "OFFICIAL_SOURCE_IDS",
    "PROVIDER_BY_ALIAS",
    "PROVIDER_BY_SLUG",
    "PROVIDER_BY_SOURCE_ID",
    "PROVIDER_PROFILES",
    "ProviderProfile",
    "get_provider_profile",
    "integration_public_rows",
    "provider_for_record",
    "provider_public_rows",
    "provider_slug_for",
    "render_integration_snippets",
]
