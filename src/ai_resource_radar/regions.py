"""Country and region-preset normalization for offer availability.

The storage layer deliberately deals in ISO 3166-1 alpha-2 country codes.  A
small set of named presets is useful at the API boundary, but is expanded
before a query reaches SQLite so unknown labels can never silently broaden a
result set.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


# Kept local instead of depending on an optional country-data package.  The
# codes are the current ISO 3166-1 alpha-2 assigned set (plus no aliases).
ISO2_CODES = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI "
    "BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN "
    "CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK "
    "FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM "
    "HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN "
    "KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK "
    "ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP "
    "NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
    "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF "
    "TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI "
    "VN VU WF WS YE YT ZA ZM ZW".split()
)
REGION_MODEL_VERSION = "2026-08-14.v1"

REGION_PRESETS: dict[str, tuple[str, ...]] = {
    "china": ("CN",),
    "mainland": ("CN",),
    "mainland-china": ("CN",),
    "us": ("US",),
    "uk": ("GB",),
    "india": ("IN",),
    "east-asia": ("CN", "HK", "JP", "KR", "MO", "MN", "TW"),
    "apac": (
        "AU", "BN", "CN", "FJ", "HK", "ID", "IN", "JP", "KH", "KR",
        "LA", "LK", "MM", "MO", "MY", "NZ", "PH", "PK", "SG", "TH",
        "TW", "VN",
    ),
    "north-america": ("CA", "MX", "US"),
    "latin-america": (
        "AR", "BO", "BR", "CL", "CO", "CR", "DO", "EC", "GT", "HN",
        "MX", "NI", "PA", "PE", "PR", "PY", "SV", "UY", "VE",
    ),
    "eu": (
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    ),
    "eea": (
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IS", "IE", "IT", "LV", "LI", "LT", "LU",
        "MT", "NL", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    ),
    "eu-eea": (
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IS", "IE", "IT", "LV", "LI", "LT", "LU",
        "MT", "NL", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    ),
    "southeast-asia": (
        "BN", "KH", "ID", "LA", "MY", "MM", "PH", "SG", "TH", "TL", "VN",
    ),
}


def _tokens(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else value
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise ValueError("invalid_region_filter")
        result.extend(token for token in re.split(r"[\s,]+", item.strip()) if token)
    return tuple(result)


def normalize_country(value: str) -> str:
    """Return one strict ISO2 code; aliases and unknown values are rejected."""

    country = value.strip().upper()
    if country not in ISO2_CODES:
        raise ValueError("invalid_country_filter")
    return country


def normalize_region(value: str) -> tuple[str, ...]:
    """Expand exactly one named preset into its ISO2 members."""

    key = value.strip().casefold().replace("_", "-")
    try:
        return REGION_PRESETS[key]
    except KeyError as exc:
        raise ValueError("invalid_region_filter") from exc


def parse_countries(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """Parse a comma-separated/iterable country filter without guessing."""

    return tuple(dict.fromkeys(normalize_country(item) for item in _tokens(value)))


def parse_regions(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """Expand named region presets, preserving a deterministic unique order."""

    expanded: list[str] = []
    for item in _tokens(value):
        expanded.extend(normalize_region(item))
    return tuple(dict.fromkeys(expanded))


def resolve_country_filter(
    *,
    country: str | Iterable[str] | None = None,
    region: str | Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Combine strict country codes and strict named presets."""

    countries = parse_countries(country)
    regions = parse_regions(region)
    if countries and regions:
        raise ValueError("country_region_mutually_exclusive")
    return countries or regions


__all__ = [
    "ISO2_CODES",
    "REGION_MODEL_VERSION",
    "REGION_PRESETS",
    "normalize_country",
    "normalize_region",
    "parse_countries",
    "parse_regions",
    "resolve_country_filter",
]
