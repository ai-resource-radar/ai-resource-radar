"""Collection domain: source types, registry and strict payload parsers.

The package keeps the parser registry in one place while offering smaller
imports for callers that only need the source models or registry.
"""

from .models import OfferObservation, RadarSource, normalize_modalities, resolve_modalities
from .registry import OFFICIAL_GUIDES, SOURCE_BY_ID, SOURCES, official_guide
from .parsers import PARSERS, parse_source

__all__ = [
    "OfferObservation",
    "RadarSource",
    "normalize_modalities",
    "resolve_modalities",
    "OFFICIAL_GUIDES",
    "SOURCE_BY_ID",
    "SOURCES",
    "official_guide",
    "PARSERS",
    "parse_source",
]
