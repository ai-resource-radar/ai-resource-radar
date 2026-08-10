"""Poster fact selection, compacting and prompt construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.store import list_offers, radar_summary

from .constants import *  # noqa: F401,F403
def default_poster_root() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "AIResourceRadar"
        / "posters"
    )


@dataclass(frozen=True)
class PosterFact:
    kind: str
    provider: str
    title: str
    value: str
    instruction: str
    source_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "provider": self.provider,
            "title": self.title,
            "value": self.value,
            "instruction": self.instruction,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class PosterFacts:
    report_date: str
    refreshed_at: str
    active_count: int
    tier_a_count: int
    new_today_count: int
    facts: tuple[PosterFact, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "refreshed_at": self.refreshed_at,
            "active_count": self.active_count,
            "tier_a_count": self.tier_a_count,
            "new_today_count": self.new_today_count,
            "facts": [fact.to_dict() for fact in self.facts],
        }


def _benchmark_cases() -> tuple[tuple[str, PosterFacts], ...]:
    providers = (
        ("Groq", "免费模型 API", "每天 14400 次请求", "注册后创建 API Key"),
        ("Cloudflare", "Workers AI", "每天 10000 Neurons", "创建 Worker 后调用模型"),
        ("Modal", "GPU 免费额度", "每月 $30 credits", "注册并安装命令行工具"),
        ("OpenRouter", "Gemma 3 4B", "$0.05 / 百万 Token", "调用前核对输入输出单价"),
        ("Vast.ai", "RTX 4090", "$0.18 / GPU 小时", "租用前核对实例总价"),
    )
    variants = (
        ("2026-08-10", 1724, 24, 2),
        ("2026-08-11", 1731, 25, 0),
        ("2026-08-12", 1708, 23, 7),
        ("2026-08-13", 1740, 26, 1),
        ("2026-08-14", 1699, 22, 5),
        ("2026-08-15", 1752, 27, 3),
    )
    output: list[tuple[str, PosterFacts]] = []
    for index, (report_date, active, tier_a, new_today) in enumerate(variants, start=1):
        facts = tuple(
            PosterFact(
                kind=(
                    "免费资源"
                    if item_index <= 3
                    else "Token 价格"
                    if item_index == 4
                    else "GPU 价格"
                ),
                provider=provider,
                title=title,
                value=value,
                instruction=instruction,
                source_url="https://example.invalid/benchmark",
            )
            for item_index, (provider, title, value, instruction) in enumerate(
                providers, start=1
            )
        )
        output.append(
            (
                f"case-{index}",
                PosterFacts(
                    report_date=report_date,
                    refreshed_at=f"{report_date}T08:00:00+08:00",
                    active_count=active,
                    tier_a_count=tier_a,
                    new_today_count=new_today,
                    facts=facts,
                ),
            )
        )
    return tuple(output)


def _compact_number(value: Any, *, digits: int = 4) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _quota_text(offer: dict[str, Any]) -> str:
    value = offer.get("quota_value")
    unit = str(offer.get("quota_unit") or "免费额度")
    period = {
        "daily": "每天",
        "weekly": "每周",
        "monthly": "每月",
        "one_time": "一次性",
        "variable": "动态",
    }.get(str(offer.get("reset_period") or ""), "")
    if value is None:
        return f"{period} {unit}".strip()
    return f"{period} {_compact_number(value)} {unit}".strip()


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def select_poster_facts(path: Path, *, now: datetime | None = None) -> PosterFacts:
    current = (now or datetime.now().astimezone()).astimezone()
    offers = list_offers(
        path,
        verified_only=True,
        no_card=True,
        mainland=("supported", "unknown"),
        include_pricing=False,
        limit=500,
    )
    selected_free: list[PosterFact] = []
    providers: set[str] = set()
    for offer in offers:
        if offer.get("priority_tier") not in {"A", "B"}:
            continue
        provider = str(offer["provider"])
        if provider.casefold() in providers:
            continue
        details = offer.get("details") if isinstance(offer.get("details"), dict) else {}
        steps = details.get("usage_steps")
        instruction = (
            next(
                (
                    _short_text(step, 52)
                    for step in steps
                    if isinstance(step, str) and step.strip()
                ),
                "",
            )
            if isinstance(steps, list)
            else ""
        )
        if not instruction:
            instruction = _short_text(
                details.get("action_label") or offer.get("eligibility") or "打开官方页面注册使用",
                52,
            )
        selected_free.append(
            PosterFact(
                kind="免费资源",
                provider=provider,
                title=_short_text(offer["title"], 36),
                value=_short_text(_quota_text(offer), 40),
                instruction=instruction,
                source_url=str(offer["homepage_url"]),
            )
        )
        providers.add(provider.casefold())
        if len(selected_free) == 3:
            break
    if len(selected_free) < 3:
        raise RuntimeError("poster_insufficient_free_offers")

    token_payload = list_token_prices(
        path,
        sort="typical",
        direction="asc",
        limit=50,
        current=current.date(),
    )
    token_prices = [
        item
        for item in token_payload["prices"]
        if item.get("typical_cost") is not None
    ]
    if not token_prices:
        raise RuntimeError("poster_token_price_unavailable")
    token = token_prices[0]
    input_price = token.get("input_per_mtok")
    output_price = token.get("output_per_mtok")
    token_value = (
        f"输入 ${_compact_number(input_price)} / "
        f"输出 ${_compact_number(output_price)} / 百万 Token"
    )
    token_fact = PosterFact(
        kind="Token 价格",
        provider=str(token["provider"]),
        title=_short_text(token["model"], 36),
        value=token_value,
        instruction="适合文本任务，使用前再次核对官方账单口径",
        source_url=str(token["pricing_url"]),
    )

    gpu_payload = list_gpu_prices(
        path,
        sort="hourly",
        direction="asc",
        price_mode="fixed",
        hours=1,
        limit=100,
    )
    gpu_prices = [
        item for item in gpu_payload["prices"] if item.get("hourly_usd") is not None
    ]
    if not gpu_prices:
        raise RuntimeError("poster_gpu_price_unavailable")
    gpu = gpu_prices[0]
    gpu_fact = PosterFact(
        kind="GPU 价格",
        provider=str(gpu["provider"]),
        title=_short_text(gpu["gpu_model"], 36),
        value=f"${_compact_number(gpu['hourly_usd'])} / GPU 小时",
        instruction="不含存储、流量、税费和长期合约折扣",
        source_url=str(gpu["pricing_url"]),
    )

    summary = radar_summary(path, now=current)
    counts = summary.get("counts", {})
    return PosterFacts(
        report_date=current.date().isoformat(),
        refreshed_at=str(summary.get("last_refresh_at") or current.isoformat(timespec="seconds")),
        active_count=int(counts.get("active") or 0),
        tier_a_count=int(counts.get("tier_a") or 0),
        new_today_count=int(counts.get("new_today") or 0),
        facts=tuple([*selected_free, token_fact, gpu_fact]),
    )


def _compact_facts_for_model(facts: PosterFacts, model: str) -> PosterFacts:
    if model.casefold() != OPENCLAW_POSTER_MODEL.casefold():
        return facts
    return PosterFacts(
        report_date=facts.report_date,
        refreshed_at=facts.refreshed_at,
        active_count=facts.active_count,
        tier_a_count=facts.tier_a_count,
        new_today_count=facts.new_today_count,
        facts=tuple(
            PosterFact(
                kind=fact.kind,
                provider=_short_text(fact.provider, 18),
                title=_short_text(fact.title, 28),
                value=_short_text(fact.value, 36),
                instruction=_short_text(fact.instruction, 30),
                source_url=fact.source_url,
            )
            for fact in facts.facts
        ),
    )


def build_poster_prompt(
    facts: PosterFacts,
    *,
    correction_notes: tuple[str, ...] = (),
) -> str:
    lines = [
        "Use case: infographic-diagram",
        "Asset type: Chinese daily AI resource poster",
        "Primary request: 生成一张完整的竖版中文信息海报，所有排版、卡片、背景和文字都由图片模型一次完成。",
        "Style/medium: 深色科技编辑风格，深靛蓝背景，青绿色高光，高对比清晰中文，无人物、无商标、无二维码。",
        "Composition/framing: 竖版五张信息卡，前三张为免费资源，第四张为 Token 价格，第五张为 GPU 价格；留足安全边距。",
        "Text rules: 只能绘制下面提供的文字和序号 1–5，不得添加、改写或猜测任何金额、额度、日期、模型参数。",
        f'Text (verbatim): "{POSTER_TITLE}"',
        f'Text (verbatim): "{facts.report_date}"',
        (
            'Text (verbatim): "'
            f"资源 {facts.active_count} · A 级 {facts.tier_a_count} · 今日新增 {facts.new_today_count}"
            '"'
        ),
    ]
    for index, fact in enumerate(facts.facts, start=1):
        lines.extend(
            [
                f'Card {index} label (verbatim): "{fact.kind}"',
                f'Card {index} provider (verbatim): "{fact.provider}"',
                f'Card {index} title (verbatim): "{fact.title}"',
                f'Card {index} value (verbatim): "{fact.value}"',
                f'Card {index} action (verbatim): "{fact.instruction}"',
            ]
        )
    lines.extend(
        [
            f'Text (verbatim): "{POSTER_NOTICE}"',
            f'Text (verbatim): "数据截至 {facts.refreshed_at[:16].replace("T", " ")}"',
            "Constraints: 中文必须可读，数字必须逐字准确；不要生成来源网址、脚注编号、水印或额外装饰数字。",
            "Avoid: 模糊小字、伪造 Logo、英文乱码、随机统计图、人物、二维码、额外价格和额外额度。",
        ]
    )
    if correction_notes:
        lines.append(
            "Previous validation failures to correct exactly: "
            + "；".join(correction_notes[:12])
        )
    return "\n".join(lines)



__all__ = ["PosterFact", "PosterFacts", "_benchmark_cases", "_compact_facts_for_model", "_compact_number", "_quota_text", "_short_text", "build_poster_prompt", "default_poster_root", "select_poster_facts"]
