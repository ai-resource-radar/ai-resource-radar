from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Protocol
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.store import (
    POSTER_RETENTION_DAYS,
    connect,
    list_offers,
    radar_summary,
)
from ai_resource_radar.native_helper import prepare_macos_helper


POSTER_TITLE = "AI 免费资源雷达日报"
POSTER_NOTICE = "数据以官方页面为准"
POSTER_PROVIDER = "openai"
POSTER_MODEL = "gpt-image-2"
POSTER_QUALITY = "medium"
POSTER_REQUEST_SIZE = "1088x1440"
POSTER_WIDTH = 1080
POSTER_HEIGHT = 1440
MAX_POSTER_ATTEMPTS_PER_DAY = 3
MAX_IMAGE_RESPONSE_BYTES = 32 * 1024 * 1024
KEYCHAIN_SERVICE = "ai-resource-radar.openai"
KEYCHAIN_ACCOUNT = "default"
OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations"


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


@dataclass(frozen=True)
class PosterRequest:
    prompt: str
    size: str = POSTER_REQUEST_SIZE
    quality: str = POSTER_QUALITY


@dataclass(frozen=True)
class GeneratedPoster:
    body: bytes
    request_id: str | None = None
    media_type: str = "image/png"


@dataclass(frozen=True)
class PosterValidation:
    valid: bool
    missing_anchors: tuple[str, ...]
    unexpected_numbers: tuple[str, ...]
    recognized_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "missing_anchors": list(self.missing_anchors),
            "unexpected_numbers": list(self.unexpected_numbers),
            "recognized_text": self.recognized_text[:20_000],
        }


class PosterGenerator(Protocol):
    provider: str
    model: str

    def generate(self, request: PosterRequest, *, api_key: str) -> GeneratedPoster: ...


class OCRProvider(Protocol):
    def recognize(self, image_path: Path) -> str: ...


class KeyStore(Protocol):
    def get(self) -> str | None: ...


class KeychainStore:
    def __init__(
        self,
        *,
        service: str = KEYCHAIN_SERVICE,
        account: str = KEYCHAIN_ACCOUNT,
    ) -> None:
        self.service = service
        self.account = account

    def get(self) -> str | None:
        environment_key = os.environ.get("AI_RADAR_OPENAI_API_KEY")
        if environment_key:
            return environment_key.strip() or None
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-a",
                    self.account,
                    "-s",
                    self.service,
                    "-w",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def set(self, secret: str) -> None:
        value = secret.strip()
        if not value:
            raise ValueError("poster_api_key_empty")
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/security",
                    "add-generic-password",
                    "-U",
                    "-a",
                    self.account,
                    "-s",
                    self.service,
                    "-l",
                    "AI Resource Radar · OpenAI",
                    "-w",
                ],
                input=f"{value}\n",
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("poster_keychain_unavailable") from exc
        if completed.returncode != 0:
            raise RuntimeError("poster_keychain_write_failed")

    def delete(self) -> bool:
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/security",
                    "delete-generic-password",
                    "-a",
                    self.account,
                    "-s",
                    self.service,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    def configured(self) -> bool:
        return self.get() is not None


class OpenAIImageGenerator:
    provider = POSTER_PROVIDER

    def __init__(
        self,
        *,
        model: str = POSTER_MODEL,
        endpoint: str = OPENAI_IMAGE_ENDPOINT,
        timeout: float = 120.0,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or parsed.hostname not in {"api.openai.com"}:
            raise ValueError("poster_endpoint_not_allowlisted")
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout

    def generate(self, request: PosterRequest, *, api_key: str) -> GeneratedPoster:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": request.prompt,
                "size": request.size,
                "quality": request.quality,
                "output_format": "png",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        http_request = Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AIResourceRadar/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout) as response:
                raw = response.read(MAX_IMAGE_RESPONSE_BYTES + 1)
                if len(raw) > MAX_IMAGE_RESPONSE_BYTES:
                    raise RuntimeError("poster_response_too_large")
                request_id = response.headers.get("x-request-id")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                code = "poster_auth_failed"
            elif exc.code == 429:
                code = "poster_rate_limited"
            elif exc.code in {402, 422}:
                code = "poster_quota_unavailable"
            else:
                code = "poster_api_failed"
            raise RuntimeError(code) from exc
        except TimeoutError as exc:
            raise RuntimeError("poster_api_timeout") from exc
        except OSError as exc:
            raise RuntimeError("poster_api_unavailable") from exc
        try:
            decoded = json.loads(raw)
            item = decoded["data"][0]
            encoded = item.get("b64_json")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError
            body = base64.b64decode(encoded, validate=True)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("poster_api_invalid_response") from exc
        if not body or len(body) > MAX_IMAGE_RESPONSE_BYTES:
            raise RuntimeError("poster_api_invalid_image")
        return GeneratedPoster(body=body, request_id=request_id)


class MacOSVisionOCR:
    def recognize(self, image_path: Path) -> str:
        helper = prepare_macos_helper("macos_poster_ocr.swift")
        if not helper.available or helper.executable is None:
            raise RuntimeError(helper.error or "poster_ocr_unavailable")
        try:
            completed = subprocess.run(
                [str(helper.executable), str(image_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("poster_ocr_timeout") from exc
        except OSError as exc:
            raise RuntimeError("poster_ocr_unavailable") from exc
        if completed.returncode != 0:
            raise RuntimeError("poster_ocr_failed")
        try:
            payload = json.loads(completed.stdout)
            text = payload["text"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("poster_ocr_invalid_response") from exc
        if not isinstance(text, str):
            raise RuntimeError("poster_ocr_invalid_response")
        return text


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


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s·•|｜:：,，。.;；'\"“”‘’()（）/\\_-]+", "", normalized)


_NUMBER_RE = re.compile(r"[$¥]?\d+(?:[.,]\d+)?")


def validate_poster_text(text: str, facts: PosterFacts) -> PosterValidation:
    required = [
        POSTER_TITLE,
        facts.report_date,
        POSTER_NOTICE,
        *(fact.provider for fact in facts.facts),
        *(fact.value for fact in facts.facts),
    ]
    normalized_text = _normalize_text(text)
    missing = tuple(
        anchor for anchor in required if _normalize_text(anchor) not in normalized_text
    )
    allowed_numbers: set[str] = {"1", "2", "3", "4", "5"}
    for value in [
        facts.report_date,
        facts.refreshed_at[:16],
        str(facts.active_count),
        str(facts.tier_a_count),
        str(facts.new_today_count),
        *(
            value
            for fact in facts.facts
            for value in (
                fact.provider,
                fact.title,
                fact.value,
                fact.instruction,
            )
        ),
    ]:
        allowed_numbers.update(
            match.group(0).replace(",", "").lstrip("$¥")
            for match in _NUMBER_RE.finditer(value)
        )
    observed_numbers = {
        match.group(0).replace(",", "").lstrip("$¥")
        for match in _NUMBER_RE.finditer(text)
    }
    unexpected = tuple(sorted(observed_numbers - allowed_numbers))
    return PosterValidation(
        valid=not missing and not unexpected,
        missing_anchors=missing,
        unexpected_numbers=unexpected,
        recognized_text=text,
    )


def _report_dict(row: Any) -> dict[str, Any]:
    payload = dict(row)
    for source, target in (
        ("selected_facts_json", "selected_facts"),
        ("validation_json", "validation"),
    ):
        raw = payload.pop(source, "{}")
        try:
            payload[target] = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            payload[target] = {}
    payload["image_url"] = (
        f"/api/ai-daily/{payload['report_date']}/image"
        if payload.get("status") == "success" and payload.get("image_path")
        else None
    )
    return payload


def list_daily_reports(
    path: Path,
    *,
    days: int = POSTER_RETENTION_DAYS,
    limit: int = POSTER_RETENTION_DAYS,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= days <= POSTER_RETENTION_DAYS or not 1 <= limit <= POSTER_RETENTION_DAYS:
        raise ValueError("invalid_daily_report_filter")
    if not path.exists():
        return ()
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT * FROM daily_reports
            WHERE report_date >= ?
            ORDER BY report_date DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return tuple(_report_dict(row) for row in rows)
    finally:
        connection.close()


def latest_daily_report(
    path: Path,
    *,
    success_only: bool = True,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    connection = connect(path)
    try:
        clause = "WHERE status = 'success'" if success_only else ""
        row = connection.execute(
            f"SELECT * FROM daily_reports {clause} ORDER BY report_date DESC LIMIT 1"
        ).fetchone()
        return _report_dict(row) if row else None
    finally:
        connection.close()


def daily_report_status(
    path: Path,
    *,
    key_store: KeyStore | None = None,
    current: date | None = None,
) -> dict[str, Any]:
    store = key_store or KeychainStore()
    today = (current or date.today()).isoformat()
    report = None
    if path.exists():
        connection = connect(path)
        try:
            row = connection.execute(
                "SELECT * FROM daily_reports WHERE report_date = ?", (today,)
            ).fetchone()
            report = _report_dict(row) if row else None
        finally:
            connection.close()
    return {
        "schema_version": "1.0",
        "configured": store.get() is not None,
        "provider": POSTER_PROVIDER,
        "model": POSTER_MODEL,
        "quality": POSTER_QUALITY,
        "max_attempts_per_day": MAX_POSTER_ATTEMPTS_PER_DAY,
        "today": report,
        "latest": latest_daily_report(path),
    }


def _upsert_failure(
    path: Path,
    *,
    report_date: str,
    at: str,
    error_code: str,
    facts: PosterFacts | None = None,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO daily_reports(
                    report_date, status, generated_at, radar_refreshed_at,
                    provider, model, quality, selected_facts_json,
                    validation_json, error_code, updated_at
                )
                VALUES (?, 'failed', ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    status = CASE
                        WHEN daily_reports.status = 'success' THEN 'success'
                        ELSE 'failed'
                    END,
                    error_code = excluded.error_code,
                    selected_facts_json = CASE
                        WHEN excluded.selected_facts_json = '{}' THEN daily_reports.selected_facts_json
                        ELSE excluded.selected_facts_json
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    report_date,
                    at,
                    facts.refreshed_at if facts else None,
                    POSTER_PROVIDER,
                    POSTER_MODEL,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict() if facts else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    error_code,
                    at,
                ),
            )
    finally:
        connection.close()


def _reserve_attempt(
    path: Path,
    *,
    facts: PosterFacts,
    prompt_hash: str,
    at: str,
    provider: str,
    model: str,
) -> int | None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO daily_reports(
                    report_date, status, generated_at, radar_refreshed_at,
                    provider, model, quality, attempt_count, selected_facts_json,
                    prompt_sha256, validation_json, updated_at
                )
                VALUES (?, 'running', ?, ?, ?, ?, ?, 0, ?, ?, '{}', ?)
                ON CONFLICT(report_date) DO NOTHING
                """,
                (
                    facts.report_date,
                    at,
                    facts.refreshed_at,
                    provider,
                    model,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict(), ensure_ascii=False, separators=(",", ":")
                    ),
                    prompt_hash,
                    at,
                ),
            )
            cursor = connection.execute(
                """
                UPDATE daily_reports
                SET attempt_count = attempt_count + 1,
                    status = CASE WHEN image_path IS NULL THEN 'running' ELSE status END,
                    generated_at = ?, radar_refreshed_at = ?, provider = ?,
                    model = ?, quality = ?, selected_facts_json = ?,
                    prompt_sha256 = ?, error_code = NULL, updated_at = ?
                WHERE report_date = ? AND attempt_count < ?
                """,
                (
                    at,
                    facts.refreshed_at,
                    provider,
                    model,
                    POSTER_QUALITY,
                    json.dumps(
                        facts.to_dict(), ensure_ascii=False, separators=(",", ":")
                    ),
                    prompt_hash,
                    at,
                    facts.report_date,
                    MAX_POSTER_ATTEMPTS_PER_DAY,
                ),
            )
            if cursor.rowcount != 1:
                return None
            return int(
                connection.execute(
                    "SELECT attempt_count FROM daily_reports WHERE report_date = ?",
                    (facts.report_date,),
                ).fetchone()[0]
            )
    finally:
        connection.close()


def _record_attempt_failure(
    path: Path,
    *,
    report_date: str,
    validation: PosterValidation | None,
    error_code: str,
    request_id: str | None,
    at: str,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET status = CASE WHEN image_path IS NULL THEN 'failed' ELSE status END,
                    validation_json = ?, error_code = ?, request_id = ?,
                    updated_at = ?
                WHERE report_date = ?
                """,
                (
                    json.dumps(
                        validation.to_dict() if validation else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    error_code,
                    request_id,
                    at,
                    report_date,
                ),
            )
    finally:
        connection.close()


def _record_success(
    path: Path,
    *,
    facts: PosterFacts,
    validation: PosterValidation,
    relative_image_path: str,
    image_sha256: str,
    image_bytes: int,
    request_id: str | None,
    at: str,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET status = 'success', generated_at = ?, validation_json = ?,
                    image_path = ?, image_sha256 = ?, image_bytes = ?,
                    error_code = NULL, request_id = ?, updated_at = ?
                WHERE report_date = ?
                """,
                (
                    at,
                    json.dumps(
                        validation.to_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    relative_image_path,
                    image_sha256,
                    image_bytes,
                    request_id,
                    at,
                    facts.report_date,
                ),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO notifications(
                    created_at, dedupe_key, title, body, target_url, item_count
                )
                VALUES (?, ?, 'AI 雷达日报已生成', ?, ?, 1)
                """,
                (
                    at,
                    f"daily-poster:{facts.report_date}",
                    f"{facts.report_date} 的纯图片日报已通过文字与数字校验。",
                    "/ai-resources.html#poster",
                ),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "UPDATE daily_reports SET notified_at = ? WHERE report_date = ?",
                    (at, facts.report_date),
                )
    finally:
        connection.close()


def _save_webp(source: Path, target: Path) -> tuple[str, int]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("poster_image_processing_unavailable") from exc
    temporary = target.with_suffix(".webp.tmp")
    try:
        with Image.open(source) as image:
            image.load()
            normalized = ImageOps.fit(
                image.convert("RGB"),
                (POSTER_WIDTH, POSTER_HEIGHT),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            normalized.save(temporary, format="WEBP", quality=90, method=6)
        body = temporary.read_bytes()
        if not body:
            raise RuntimeError("poster_image_processing_failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return hashlib.sha256(body).hexdigest(), len(body)
    except (OSError, ValueError) as exc:
        raise RuntimeError("poster_image_processing_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_suffix(media_type: str) -> str:
    return ".jpg" if media_type == "image/jpeg" else ".png"


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    if re.fullmatch(r"[a-z0-9_]{3,80}", value):
        return value
    return "poster_generation_failed"


def prune_daily_posters(
    path: Path,
    *,
    poster_root: Path | None = None,
    now: datetime | None = None,
) -> int:
    if not path.exists():
        return 0
    root = poster_root or default_poster_root()
    current = (now or datetime.now().astimezone()).astimezone()
    cutoff = (current.date() - timedelta(days=POSTER_RETENTION_DAYS)).isoformat()
    connection = connect(path)
    try:
        rows = connection.execute(
            "SELECT report_date, image_path FROM daily_reports WHERE report_date < ?",
            (cutoff,),
        ).fetchall()
        root_resolved = root.resolve()
        for row in rows:
            relative = row["image_path"]
            if not relative:
                continue
            candidate = (root / str(relative)).resolve()
            if candidate.is_relative_to(root_resolved):
                candidate.unlink(missing_ok=True)
        with connection:
            cursor = connection.execute(
                "DELETE FROM daily_reports WHERE report_date < ?", (cutoff,)
            )
        return max(0, cursor.rowcount)
    finally:
        connection.close()


def resolve_daily_poster(
    path: Path,
    report_date: str,
    *,
    poster_root: Path | None = None,
) -> Path | None:
    try:
        date.fromisoformat(report_date)
    except ValueError:
        return None
    if not path.exists():
        return None
    connection = connect(path)
    try:
        row = connection.execute(
            """
            SELECT image_path FROM daily_reports
            WHERE report_date = ? AND status = 'success'
            """,
            (report_date,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or not row["image_path"]:
        return None
    root = (poster_root or default_poster_root()).resolve()
    image = (root / str(row["image_path"])).resolve()
    if not image.is_relative_to(root) or not image.is_file():
        return None
    return image


def generate_daily_poster(
    path: Path,
    *,
    force: bool = False,
    now: datetime | None = None,
    poster_root: Path | None = None,
    generator: PosterGenerator | None = None,
    ocr: OCRProvider | None = None,
    key_store: KeyStore | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now().astimezone()).astimezone()
    at = current.isoformat(timespec="seconds")
    report_date = current.date().isoformat()
    root = poster_root or default_poster_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    prune_daily_posters(path, poster_root=root, now=current)
    existing = None
    if path.exists():
        connection = connect(path)
        try:
            row = connection.execute(
                "SELECT * FROM daily_reports WHERE report_date = ?", (report_date,)
            ).fetchone()
            existing = _report_dict(row) if row else None
        finally:
            connection.close()
    if existing and existing["status"] == "success" and not force:
        return existing

    store = key_store or KeychainStore()
    api_key = store.get()
    if not api_key:
        _upsert_failure(
            path,
            report_date=report_date,
            at=at,
            error_code="poster_not_configured",
        )
        return latest_daily_report(path, success_only=False) or {}

    try:
        facts = select_poster_facts(path, now=current)
    except Exception as exc:
        _upsert_failure(
            path,
            report_date=report_date,
            at=at,
            error_code=_safe_error(exc),
        )
        return latest_daily_report(path, success_only=False) or {}

    image_generator = generator or OpenAIImageGenerator()
    ocr_provider = ocr or MacOSVisionOCR()
    correction_notes: tuple[str, ...] = ()
    while True:
        prompt = build_poster_prompt(facts, correction_notes=correction_notes)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        attempt = _reserve_attempt(
            path,
            facts=facts,
            prompt_hash=prompt_hash,
            at=datetime.now().astimezone().isoformat(timespec="seconds"),
            provider=image_generator.provider,
            model=image_generator.model,
        )
        if attempt is None:
            _upsert_failure(
                path,
                report_date=report_date,
                at=datetime.now().astimezone().isoformat(timespec="seconds"),
                error_code="poster_daily_attempt_limit",
                facts=facts,
            )
            break
        generated: GeneratedPoster | None = None
        validation: PosterValidation | None = None
        candidate: Path | None = None
        try:
            generated = image_generator.generate(
                PosterRequest(prompt=prompt),
                api_key=api_key,
            )
            descriptor, candidate_name = tempfile.mkstemp(
                prefix=f".{report_date}-{attempt}-",
                suffix=_candidate_suffix(generated.media_type),
                dir=root,
            )
            candidate = Path(candidate_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(generated.body)
            os.chmod(candidate, 0o600)
            recognized = ocr_provider.recognize(candidate)
            validation = validate_poster_text(recognized, facts)
            if not validation.valid:
                correction_notes = tuple(
                    [
                        *(
                            f"缺少或写错：{anchor}"
                            for anchor in validation.missing_anchors
                        ),
                        *(
                            f"删除额外数字：{number}"
                            for number in validation.unexpected_numbers
                        ),
                    ]
                )
                raise RuntimeError("poster_validation_failed")
            target = root / f"{report_date}.webp"
            image_hash, image_bytes = _save_webp(candidate, target)
            success_at = datetime.now().astimezone().isoformat(timespec="seconds")
            _record_success(
                path,
                facts=facts,
                validation=validation,
                relative_image_path=target.name,
                image_sha256=image_hash,
                image_bytes=image_bytes,
                request_id=generated.request_id,
                at=success_at,
            )
            return latest_daily_report(path, success_only=False) or {}
        except Exception as exc:
            error_code = _safe_error(exc)
            _record_attempt_failure(
                path,
                report_date=report_date,
                validation=validation,
                error_code=error_code,
                request_id=generated.request_id if generated else None,
                at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            if error_code in {
                "poster_auth_failed",
                "poster_quota_unavailable",
                "poster_not_configured",
                "poster_image_processing_unavailable",
                "poster_ocr_unavailable",
                "unsupported_platform",
            }:
                break
        finally:
            if candidate is not None:
                candidate.unlink(missing_ok=True)
    return latest_daily_report(path, success_only=False) or {}
