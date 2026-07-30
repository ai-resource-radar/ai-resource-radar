from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
from typing import Any

from ai_resource_radar.sources import gpu_vram
from ai_resource_radar.store import connect


TOKEN_SORTS = {"typical", "input", "output", "context", "provider"}
GPU_SORTS = {"hourly", "memory_value", "vram", "provider"}
SORT_DIRECTIONS = {"asc", "desc"}
VERIFICATION_FILTERS = {"all", "official", "community"}
CACHE_FILTERS = {"any", "yes", "no"}
PRICE_MODE_FILTERS = {"all", "fixed", "dynamic_market"}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _valid_bound(value: float | int | None) -> bool:
    return value is None or _finite_number(value) is not None


def _sort_items(
    items: list[dict[str, Any]],
    *,
    value: Any,
    direction: str,
) -> None:
    available = [item for item in items if value(item) is not None]
    missing = [item for item in items if value(item) is None]
    available.sort(
        key=lambda item: (value(item), str(item["provider"]).casefold(), str(item.get("model") or item.get("gpu_model") or "").casefold()),
        reverse=direction == "desc",
    )
    items[:] = available + missing


def _base_price(value: Any) -> float | None:
    direct = _finite_number(value)
    if direct is not None:
        return direct
    if isinstance(value, dict):
        return _finite_number(value.get("base"))
    return None


def _date_matches(constraint: dict[str, Any], current: date) -> bool:
    start = constraint.get("start_date")
    end = constraint.get("end_date")
    try:
        if start and current < date.fromisoformat(str(start)):
            return False
        if end and current >= date.fromisoformat(str(end)):
            return False
    except ValueError:
        return False
    return True


def _active_price_map(raw: Any, *, current: date) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, list):
        return {}
    selected: dict[str, Any] = {}
    dated: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("prices"), dict):
            continue
        constraint = item.get("constraint")
        if not constraint:
            selected.update(item["prices"])
        elif (
            isinstance(constraint, dict)
            and ("start_date" in constraint or "end_date" in constraint)
            and _date_matches(constraint, current)
        ):
            dated.append(item["prices"])
    for prices in dated:
        selected.update(prices)
    return selected


def _context_window(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return int(value)
    if isinstance(value, dict):
        base = value.get("base")
        if isinstance(base, (int, float)) and not isinstance(base, bool) and base > 0:
            return int(base)
    return None


def _pricing_rows(path: Path, *, kind: str) -> list[Any]:
    if not path.exists():
        return []
    connection = connect(path)
    try:
        return connection.execute(
            """
            SELECT offer_id, provider, title, quota_value, quota_unit,
                   homepage_url, verification_level, details_json,
                   eligibility, last_seen_at, last_changed_at
            FROM offers
            WHERE status = 'active' AND offer_type = 'pricing_reference'
              AND kind = ?
            """,
            (kind,),
        ).fetchall()
    finally:
        connection.close()


def list_token_prices(
    path: Path,
    *,
    query: str | None = None,
    provider: str | None = None,
    sort: str = "typical",
    direction: str = "asc",
    min_context: int | None = None,
    max_input: float | None = None,
    max_output: float | None = None,
    max_typical: float | None = None,
    verification: str = "all",
    cache: str = "any",
    limit: int = 100,
    offset: int = 0,
    current: date | None = None,
) -> dict[str, Any]:
    if (
        sort not in TOKEN_SORTS
        or direction not in SORT_DIRECTIONS
        or verification not in VERIFICATION_FILTERS
        or cache not in CACHE_FILTERS
        or not _valid_bound(min_context)
        or not _valid_bound(max_input)
        or not _valid_bound(max_output)
        or not _valid_bound(max_typical)
        or not 1 <= limit <= 500
        or not 0 <= offset <= 100_000
    ):
        raise ValueError("invalid_token_price_filter")
    today = current or date.today()
    needle = (query or "").strip().casefold()[:100]
    selected_provider = (provider or "").strip().casefold()[:100]
    rows = _pricing_rows(path, kind="token")
    providers = sorted({str(row["provider"]) for row in rows}, key=str.casefold)
    items: list[dict[str, Any]] = []
    for row in rows:
        if needle and needle not in f"{row['provider']} {row['title']}".casefold():
            continue
        if selected_provider and str(row["provider"]).casefold() != selected_provider:
            continue
        details = json.loads(row["details_json"])
        prices = _active_price_map(details.get("prices"), current=today)
        input_price = _base_price(prices.get("input_mtok"))
        output_price = _base_price(prices.get("output_mtok"))
        if input_price is None and output_price is None:
            continue
        typical = (
            input_price + output_price * 0.25
            if input_price is not None and output_price is not None
            else None
        )
        context_window = _context_window(details.get("context_window"))
        cache_read = _base_price(prices.get("cache_read_mtok"))
        cache_write = _base_price(prices.get("cache_write_mtok"))
        is_official = row["verification_level"] in {"official_api", "official_page"}
        has_cache = cache_read is not None or cache_write is not None
        if verification == "official" and not is_official:
            continue
        if verification == "community" and is_official:
            continue
        if cache == "yes" and not has_cache:
            continue
        if cache == "no" and has_cache:
            continue
        if min_context is not None and (context_window is None or context_window < min_context):
            continue
        if max_input is not None and (input_price is None or input_price > max_input):
            continue
        if max_output is not None and (output_price is None or output_price > max_output):
            continue
        if max_typical is not None and (typical is None or typical > max_typical):
            continue
        items.append(
            {
                "price_id": row["offer_id"],
                "provider": row["provider"],
                "model": row["title"],
                "model_id": details.get("model_id"),
                "input_per_mtok": input_price,
                "output_per_mtok": output_price,
                "cache_read_per_mtok": cache_read,
                "cache_write_per_mtok": cache_write,
                "has_cache_price": has_cache,
                "typical_cost": typical,
                "context_window": context_window,
                "currency": "USD",
                "pricing_url": row["homepage_url"],
                "verification_level": row["verification_level"],
                "verification_label": (
                    "官方价格"
                    if row["verification_level"] in {"official_api", "official_page"}
                    else "社区价格基线"
                ),
                "verified_at": row["last_seen_at"],
            }
        )

    if sort == "input":
        value = lambda item: item["input_per_mtok"]
    elif sort == "output":
        value = lambda item: item["output_per_mtok"]
    elif sort == "context":
        value = lambda item: item["context_window"]
    elif sort == "provider":
        value = lambda item: item["provider"].casefold()
    else:
        value = lambda item: item["typical_cost"]
    _sort_items(items, value=value, direction=direction)
    total = len(items)
    return {
        "schema_version": "1.0",
        "count": min(limit, max(0, total - offset)),
        "total": total,
        "providers": providers,
        "filters": {
            "sort": sort,
            "direction": direction,
            "min_context": min_context,
            "max_input": max_input,
            "max_output": max_output,
            "max_typical": max_typical,
            "verification": verification,
            "cache": cache,
        },
        "scenario": {
            "input_tokens": 1_000_000,
            "output_tokens": 250_000,
            "formula": "input_per_mtok + output_per_mtok × 0.25",
        },
        "prices": items[offset : offset + limit],
    }


def list_gpu_prices(
    path: Path,
    *,
    query: str | None = None,
    provider: str | None = None,
    gpu_model: str | None = None,
    sort: str = "hourly",
    direction: str = "asc",
    min_vram: float | None = None,
    max_hourly: float | None = None,
    billing_mode: str | None = None,
    market_tier: str | None = None,
    price_mode: str = "all",
    hours: float = 10,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if (
        sort not in GPU_SORTS
        or direction not in SORT_DIRECTIONS
        or price_mode not in PRICE_MODE_FILTERS
        or not _valid_bound(min_vram)
        or not _valid_bound(max_hourly)
        or not 0.1 <= hours <= 10_000
        or not 1 <= limit <= 500
        or not 0 <= offset <= 100_000
    ):
        raise ValueError("invalid_gpu_price_filter")
    needle = (query or "").strip().casefold()[:100]
    selected_provider = (provider or "").strip().casefold()[:100]
    selected_gpu = (gpu_model or "").strip().casefold()[:100]
    selected_billing = (billing_mode or "").strip().casefold()[:100]
    selected_tier = (market_tier or "").strip().casefold()[:100]
    rows = _pricing_rows(path, kind="gpu")
    normalized_rows: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for row in rows:
        details = json.loads(row["details_json"])
        model = str(details.get("gpu_model") or row["title"])
        normalized_rows.append(
            {
                "provider": str(row["provider"]),
                "gpu_model": model,
                "billing_mode": str(details.get("billing_mode") or "unknown"),
                "market_tier": str(details.get("market_tier") or "on-demand"),
                "price_mode": str(details.get("price_mode") or "fixed"),
            }
        )
        if needle and needle not in f"{row['provider']} {row['title']} {model}".casefold():
            continue
        if selected_provider and str(row["provider"]).casefold() != selected_provider:
            continue
        if selected_gpu and model.casefold() != selected_gpu:
            continue
        hourly = _finite_number(details.get("hourly_usd"))
        vram = _finite_number(details.get("vram_gb")) or gpu_vram(model)
        normalized_billing = str(details.get("billing_mode") or "unknown")
        normalized_tier = str(details.get("market_tier") or "on-demand")
        normalized_price_mode = str(details.get("price_mode") or "fixed")
        if selected_billing and normalized_billing.casefold() != selected_billing:
            continue
        if selected_tier and normalized_tier.casefold() != selected_tier:
            continue
        if price_mode != "all" and normalized_price_mode != price_mode:
            continue
        if min_vram is not None and (vram is None or vram < min_vram):
            continue
        if max_hourly is not None and (hourly is None or hourly > max_hourly):
            continue
        items.append(
            {
                "price_id": row["offer_id"],
                "provider": row["provider"],
                "title": row["title"],
                "gpu_model": model,
                "vram_gb": vram,
                "hourly_usd": hourly,
                "estimated_cost": hourly * hours if hourly is not None else None,
                "usd_per_vram_gb_hour": (
                    hourly / vram if hourly is not None and vram else None
                ),
                "billing_mode": normalized_billing,
                "market_tier": normalized_tier,
                "price_mode": normalized_price_mode,
                "price_note": details.get("price_note") or row["eligibility"],
                "currency": details.get("currency") or "USD",
                "pricing_url": row["homepage_url"],
                "verification_level": row["verification_level"],
                "verification_label": "官方价格",
                "verified_at": row["last_seen_at"],
            }
        )

    if sort == "memory_value":
        value = lambda item: item["usd_per_vram_gb_hour"]
    elif sort == "vram":
        value = lambda item: item["vram_gb"]
    elif sort == "provider":
        value = lambda item: item["provider"].casefold()
    else:
        value = lambda item: item["hourly_usd"]
    _sort_items(items, value=value, direction=direction)
    providers = sorted({item["provider"] for item in normalized_rows}, key=str.casefold)
    gpu_models = sorted({item["gpu_model"] for item in normalized_rows}, key=str.casefold)
    billing_modes = sorted({item["billing_mode"] for item in normalized_rows}, key=str.casefold)
    market_tiers = sorted({item["market_tier"] for item in normalized_rows}, key=str.casefold)
    total = len(items)
    return {
        "schema_version": "1.0",
        "count": min(limit, max(0, total - offset)),
        "total": total,
        "providers": providers,
        "gpu_models": gpu_models,
        "billing_modes": billing_modes,
        "market_tiers": market_tiers,
        "hours": hours,
        "filters": {
            "sort": sort,
            "direction": direction,
            "min_vram": min_vram,
            "max_hourly": max_hourly,
            "billing_mode": billing_mode,
            "market_tier": market_tier,
            "price_mode": price_mode,
        },
        "prices": items[offset : offset + limit],
    }
