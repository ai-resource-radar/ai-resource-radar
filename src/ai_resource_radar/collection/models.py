"""Stable collection value objects and modality normalization."""

from __future__ import annotations

from dataclasses import dataclass
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


__all__ = ["OfferObservation", "RadarSource", "normalize_modalities", "resolve_modalities"]
