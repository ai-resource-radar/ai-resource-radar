"""Stable collection value objects and modality normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
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


def default_presentations(
    *, provider: str, title: str, eligibility: str | None = None
) -> dict[str, dict[str, str]]:
    """Build deterministic, offline-safe default EN and zh-CN presentations."""

    has_cjk_eligibility = bool(eligibility and re.search(r"[\u3400-\u9fff]", eligibility))
    has_cjk_title = bool(re.search(r"[\u3400-\u9fff]", title))
    english_provider = "Official provider" if re.search(r"[\u3400-\u9fff]", provider) else provider
    english_title = f"{english_provider} official offer" if has_cjk_title else title
    english_summary = (
        "Official offer details are verified from the source."
        if has_cjk_eligibility else eligibility or "Official offer details are verified from the source."
    )
    chinese_title = title if has_cjk_title else f"{title} 免费资源"
    chinese_summary = (
        eligibility
        if eligibility and re.search(r"[\u3400-\u9fff]", eligibility)
        else f"{provider} 的官方资源；请以来源页面中的资格与额度说明为准。"
    )
    return {
        "en": {
            "title": english_title,
            "benefit_summary": english_summary,
            "eligibility": (
                "See the official source for eligibility."
                if has_cjk_eligibility else eligibility or "See the official source for eligibility."
            ),
            "usage_steps": (),
            "limitations": (),
        },
        "zh-CN": {
            "title": chinese_title,
            "benefit_summary": chinese_summary,
            "eligibility": (
                eligibility if has_cjk_eligibility else "请以官方来源中的资格说明为准。"
            ),
            "usage_steps": (),
            "limitations": (),
        },
    }


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
    # The old card and phone fields remain first-class public fields.  The
    # v0.9 fields complete the six tri-state signup-friction dimensions.
    requires_identity_verification: str = "unknown"
    requires_paid_topup: str = "unknown"
    requires_waitlist: str = "unknown"
    requires_organization: str = "unknown"
    availability_scope: str = "unknown"
    # Country records only contain affirmative supported/unsupported evidence;
    # unknown is represented by an absent record and the enclosing scope.
    availability: dict[str, str] = field(default_factory=dict)
    presentations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def signup_requirements(self) -> dict[str, str]:
        """Return the stable six-field tri-state signup requirement map."""

        return {
            "card": _legacy_requirement(self.requires_card),
            "phone": _legacy_requirement(self.requires_phone),
            "identity_verification": self.requires_identity_verification,
            "paid_topup": self.requires_paid_topup,
            "waitlist": self.requires_waitlist,
            "organization": self.requires_organization,
        }


def _legacy_requirement(value: str) -> str:
    return {"yes": "required", "no": "not_required", "unknown": "unknown"}.get(
        value, "unknown"
    )


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


__all__ = [
    "OfferObservation",
    "RadarSource",
    "default_presentations",
    "normalize_modalities",
    "resolve_modalities",
]
