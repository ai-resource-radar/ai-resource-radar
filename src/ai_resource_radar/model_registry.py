from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageModelSpec:
    """Static, non-secret capabilities for a supported image model."""

    provider: str
    model: str
    requires_api_key: bool
    capabilities: dict[str, Any]
    formal_poster_eligible: bool
    reason: str | None = None
    eligibility_mode: str = "static"

    def to_dict(
        self,
        *,
        configured: bool,
        selected: bool = False,
        configuration_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "capabilities": dict(self.capabilities),
            "configured": configured,
            "configuration_reason": configuration_reason,
            "selected": selected,
            "formal_poster_eligible": self.formal_poster_eligible,
            "reason": self.reason,
            "eligibility_mode": self.eligibility_mode,
        }


OPENAI_GPT_IMAGE_2 = ImageModelSpec(
    provider="openai",
    model="gpt-image-2",
    requires_api_key=True,
    capabilities={
        "image_generation": True,
        "input_modalities": ["text"],
        "output_modalities": ["image"],
        "sizes": ["1024x1024", "1088x1440", "1440x1088"],
        "formats": ["png", "jpeg", "webp"],
        "transport": "https",
    },
    formal_poster_eligible=True,
)


OPENCLAW_ZAI_COGVIEW_3_FLASH = ImageModelSpec(
    provider="openclaw",
    model="zai/cogview-3-flash",
    requires_api_key=False,
    capabilities={
        "image_generation": True,
        "input_modalities": ["text"],
        "output_modalities": ["image"],
        "sizes": [
            "1024x1024",
            "768x1344",
            "864x1152",
            "1344x768",
            "1152x864",
            "1440x720",
            "720x1440",
        ],
        "formats": ["jpeg", "png"],
        "transport": "openclaw",
        "upstream_provider": "zai",
    },
    formal_poster_eligible=False,
    reason="chinese_ocr_benchmark_required",
    eligibility_mode="local_benchmark",
)


IMAGE_MODELS: tuple[ImageModelSpec, ...] = (
    OPENAI_GPT_IMAGE_2,
    OPENCLAW_ZAI_COGVIEW_3_FLASH,
)


def get_image_model(provider: str, model: str) -> ImageModelSpec:
    normalized_provider = provider.strip().casefold()
    normalized_model = model.strip().casefold()
    for spec in IMAGE_MODELS:
        if (
            spec.provider.casefold() == normalized_provider
            and spec.model.casefold() == normalized_model
        ):
            return spec
    raise ValueError("poster_model_unsupported")


def find_image_model(model: str) -> ImageModelSpec:
    normalized_model = model.strip().casefold()
    matches = [spec for spec in IMAGE_MODELS if spec.model.casefold() == normalized_model]
    if len(matches) != 1:
        raise ValueError("poster_model_unsupported")
    return matches[0]
