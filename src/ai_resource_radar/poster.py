from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
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
from ai_resource_radar.locks import operation_lock
from ai_resource_radar.model_registry import (
    IMAGE_MODELS,
    ImageModelSpec,
    find_image_model,
    get_image_model,
)


POSTER_TITLE = "AI 免费资源雷达日报"
POSTER_NOTICE = "数据以官方页面为准"
POSTER_PROVIDER = "openai"
POSTER_MODEL = "gpt-image-2"
OPENCLAW_POSTER_PROVIDER = "openclaw"
OPENCLAW_POSTER_MODEL = "zai/cogview-3-flash"
POSTER_QUALITY = "medium"
POSTER_REQUEST_SIZE = "1088x1440"
POSTER_WIDTH = 1080
POSTER_HEIGHT = 1440
MAX_POSTER_ATTEMPTS_PER_DAY = 3
MAX_IMAGE_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 32 * 1024 * 1024
KEYCHAIN_SERVICE = "ai-resource-radar.openai"
KEYCHAIN_ACCOUNT = "default"
OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations"
OPENCLAW_BINARY_ENV = "AI_RADAR_OPENCLAW_BIN"
POSTER_PROVIDER_METADATA = "poster.provider"
POSTER_MODEL_METADATA = "poster.model"
POSTER_ENABLED_METADATA = "poster.enabled"
POSTER_LAST_FAILURE_CODE_METADATA = "poster.last_failure.code"
POSTER_LAST_FAILURE_DATE_METADATA = "poster.last_failure.date"
POSTER_LAST_FAILURE_AT_METADATA = "poster.last_failure.at"
POSTER_ASPECT_RATIO_TOLERANCE = 0.08
POSTER_BENCHMARK_VERSION = "zh-poster-v1"
POSTER_BENCHMARK_CASE_COUNT = 6
POSTER_BENCHMARK_IMAGE_RETENTION_DAYS = 7


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
    width: int | None = None
    height: int | None = None


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
    requires_api_key: bool

    def generate(
        self, request: PosterRequest, *, api_key: str | None
    ) -> GeneratedPoster: ...


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
    requires_api_key = True

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

    def generate(
        self, request: PosterRequest, *, api_key: str | None
    ) -> GeneratedPoster:
        if not api_key:
            raise RuntimeError("poster_not_configured")
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
                "User-Agent": "AIResourceRadar/0.2",
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


@dataclass(frozen=True)
class DetectedImage:
    media_type: str
    suffix: str
    width: int
    height: int


def _detect_image(body: bytes, *, require_poster_ratio: bool = False) -> DetectedImage:
    if not body or len(body) > MAX_IMAGE_RESPONSE_BYTES:
        raise RuntimeError("poster_api_invalid_image")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError("poster_image_processing_unavailable") from exc
    try:
        with Image.open(BytesIO(body)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise RuntimeError("poster_image_dimensions_invalid")
            image.load()
    except RuntimeError:
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise RuntimeError("poster_api_invalid_image") from exc
    formats = {
        "JPEG": ("image/jpeg", ".jpg"),
        "PNG": ("image/png", ".png"),
        "WEBP": ("image/webp", ".webp"),
    }
    if image_format not in formats or width <= 0 or height <= 0:
        raise RuntimeError("poster_api_invalid_image")
    if require_poster_ratio:
        expected = POSTER_WIDTH / POSTER_HEIGHT
        actual = width / height
        if abs(actual - expected) / expected > POSTER_ASPECT_RATIO_TOLERANCE:
            raise RuntimeError("poster_image_aspect_ratio_invalid")
    media_type, suffix = formats[image_format]
    return DetectedImage(
        media_type=media_type,
        suffix=suffix,
        width=width,
        height=height,
    )


def _read_image_file(path: Path) -> bytes:
    """Read an image output without ever buffering an oversized file."""

    try:
        if path.stat().st_size > MAX_IMAGE_RESPONSE_BYTES:
            raise RuntimeError("poster_response_too_large")
        with path.open("rb") as stream:
            body = stream.read(MAX_IMAGE_RESPONSE_BYTES + 1)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError("poster_openclaw_invalid_response") from exc
    if len(body) > MAX_IMAGE_RESPONSE_BYTES:
        raise RuntimeError("poster_response_too_large")
    return body


def _default_openclaw_binary() -> str | None:
    configured = os.environ.get(OPENCLAW_BINARY_ENV)
    candidates = [
        configured,
        shutil.which("openclaw"),
        str(Path.home() / ".openclaw" / "bin" / "openclaw"),
        "/opt/homebrew/bin/openclaw",
        "/usr/local/bin/openclaw",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def _openclaw_error_code(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".casefold()
    if any(
        marker in text
        for marker in ("401", "403", "unauthorized", "forbidden", "auth")
    ):
        return "poster_auth_failed"
    if any(marker in text for marker in ("429", "rate limit", "rate_limit")):
        return "poster_rate_limited"
    if any(
        marker in text
        for marker in ("quota", "billing", "insufficient", "credit", "payment")
    ):
        return "poster_quota_unavailable"
    return "poster_openclaw_failed"


class OpenClawImageGenerator:
    """Use OpenClaw's image capability without reading provider credentials."""

    provider = OPENCLAW_POSTER_PROVIDER
    requires_api_key = False

    def __init__(
        self,
        *,
        model: str = OPENCLAW_POSTER_MODEL,
        binary: str | Path | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.model = model
        self.binary = str(binary) if binary is not None else _default_openclaw_binary()
        self.timeout = timeout

    def generate(
        self, request: PosterRequest, *, api_key: str | None = None
    ) -> GeneratedPoster:
        del api_key
        if not self.binary:
            raise RuntimeError("poster_openclaw_unavailable")
        with tempfile.TemporaryDirectory(prefix=".ai-radar-openclaw-") as directory:
            root = Path(directory).resolve()
            requested_output = root / "poster.png"
            requested_size = (
                "864x1152"
                if self.model.casefold() == OPENCLAW_POSTER_MODEL.casefold()
                else request.size
            )
            command = [
                self.binary,
                "infer",
                "image",
                "generate",
                "--model",
                self.model,
                "--prompt",
                request.prompt,
                "--output",
                str(requested_output),
                "--output-format",
                "png",
                "--quality",
                request.quality,
                "--count",
                "1",
                "--timeout-ms",
                str(max(1, int(self.timeout * 1000))),
                "--size",
                requested_size,
                "--json",
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout + 15,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("poster_api_timeout") from exc
            except OSError as exc:
                raise RuntimeError("poster_openclaw_unavailable") from exc
            if completed.returncode != 0:
                raise RuntimeError(
                    _openclaw_error_code(completed.stdout, completed.stderr)
                )
            try:
                payload = json.loads(completed.stdout)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("poster_openclaw_invalid_response") from exc
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise RuntimeError(
                    _openclaw_error_code(completed.stdout, completed.stderr)
                )

            output_path = requested_output
            outputs = payload.get("outputs")
            if isinstance(outputs, list):
                for item in outputs:
                    if not isinstance(item, dict) or not isinstance(
                        item.get("path"), str
                    ):
                        continue
                    candidate = Path(item["path"]).expanduser()
                    if not candidate.is_absolute():
                        candidate = Path.cwd() / candidate
                    try:
                        resolved = candidate.resolve()
                    except OSError:
                        continue
                    if resolved.is_relative_to(root):
                        output_path = resolved
                        break
            body = _read_image_file(output_path)
            detected = _detect_image(body)
            request_id = payload.get("request_id") or payload.get("requestId")
            return GeneratedPoster(
                body=body,
                request_id=request_id if isinstance(request_id, str) else None,
                media_type=detected.media_type,
                width=detected.width,
                height=detected.height,
            )


def create_poster_generator(
    provider: str | None = None,
    model: str | None = None,
) -> PosterGenerator:
    if provider is None and model is not None:
        spec = find_image_model(model)
    else:
        selected_provider = provider or POSTER_PROVIDER
        default_model = (
            OPENCLAW_POSTER_MODEL
            if selected_provider.casefold() == OPENCLAW_POSTER_PROVIDER
            else POSTER_MODEL
        )
        spec = get_image_model(selected_provider, model or default_model)
    if spec.provider == POSTER_PROVIDER:
        return OpenAIImageGenerator(model=spec.model)
    if spec.provider == OPENCLAW_POSTER_PROVIDER:
        return OpenClawImageGenerator(model=spec.model)
    raise ValueError("poster_provider_unsupported")


def _openclaw_provider_configured(
    model: str,
    *,
    binary: str | Path | None = None,
) -> tuple[bool, str | None]:
    executable = str(binary) if binary is not None else _default_openclaw_binary()
    if not executable:
        return False, "openclaw_unavailable"
    try:
        completed = subprocess.run(
            [executable, "infer", "image", "providers", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "openclaw_provider_status_unavailable"
    if completed.returncode != 0:
        return False, "openclaw_provider_status_unavailable"
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return False, "openclaw_provider_status_unavailable"

    upstream = model.split("/", 1)[0].casefold()
    requested_model = model.split("/", 1)[-1].casefold()

    def configured(value: Any, *, parent_key: str = "") -> bool:
        if isinstance(value, list):
            return any(configured(item, parent_key=parent_key) for item in value)
        if not isinstance(value, dict):
            return False
        identity = next(
            (
                str(value[key]).casefold()
                for key in ("id", "provider", "provider_id", "name")
                if isinstance(value.get(key), str)
            ),
            parent_key.casefold(),
        )
        configured_value = value.get("configured")
        is_configured = configured_value is True or (
            isinstance(configured_value, str)
            and configured_value.casefold() == "true"
        )
        models = value.get("models")
        model_available = isinstance(models, list) and any(
            isinstance(item, str)
            and item.casefold() in {model.casefold(), requested_model}
            for item in models
        )
        if identity == upstream and is_configured and model_available:
            return True
        return any(
            configured(child, parent_key=str(key))
            for key, child in value.items()
            if isinstance(child, (dict, list))
        )

    if configured(payload):
        return True, None
    return False, f"openclaw_model_{requested_model}_not_configured"


def _read_poster_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    connection = connect(path)
    try:
        rows = connection.execute(
            "SELECT key, value FROM radar_metadata WHERE key IN (?, ?, ?)",
            (
                POSTER_PROVIDER_METADATA,
                POSTER_MODEL_METADATA,
                POSTER_ENABLED_METADATA,
            ),
        ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}
    finally:
        connection.close()


def poster_benchmark_status(
    path: Path,
    *,
    provider: str = OPENCLAW_POSTER_PROVIDER,
    model: str = OPENCLAW_POSTER_MODEL,
    now: datetime | None = None,
) -> dict[str, Any]:
    spec = get_image_model(provider, model)
    current = (now or datetime.now().astimezone()).astimezone()
    today = current.date().isoformat()
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT * FROM poster_model_benchmarks
            WHERE provider = ? AND model = ? AND benchmark_version = ?
            ORDER BY attempted_at DESC, id DESC
            """,
            (spec.provider, spec.model, POSTER_BENCHMARK_VERSION),
        ).fetchall()
        latest: dict[str, Any] = {}
        for row in rows:
            latest.setdefault(str(row["case_id"]), row)
        passed = [row for row in latest.values() if row["status"] == "success"]
        successful_dates = sorted({str(row["run_date"]) for row in passed})
        review = connection.execute(
            """
            SELECT * FROM poster_model_reviews
            WHERE provider = ? AND model = ? AND benchmark_version = ?
            """,
            (spec.provider, spec.model, POSTER_BENCHMARK_VERSION),
        ).fetchone()
        benchmark_attempts_today = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM poster_model_benchmarks
                WHERE run_date = ?
                """,
                (today,),
            ).fetchone()[0]
        )
        report = connection.execute(
            "SELECT attempt_count FROM daily_reports WHERE report_date = ?", (today,)
        ).fetchone()
        daily_attempts = int(report[0]) if report else 0
    finally:
        connection.close()
    ocr_passed = len(passed) == POSTER_BENCHMARK_CASE_COUNT
    two_days_passed = len(successful_dates) >= 2
    review_status = str(review["status"]) if review else "pending"
    eligible = ocr_passed and two_days_passed and review_status == "approved"
    if not ocr_passed:
        reason = (
            "chinese_ocr_benchmark_failed"
            if any(row["status"] == "failed" for row in latest.values())
            else "chinese_ocr_benchmark_required"
        )
    elif not two_days_passed:
        reason = "benchmark_two_days_required"
    elif review_status != "approved":
        reason = "benchmark_manual_review_required"
    else:
        reason = None
    attempts_today = benchmark_attempts_today + daily_attempts
    cases = []
    for case_id, _facts in _benchmark_cases():
        row = latest.get(case_id)
        cases.append(
            {
                "case_id": case_id,
                "status": str(row["status"]) if row else "pending",
                "attempted_at": row["attempted_at"] if row else None,
                "error_code": row["error_code"] if row else None,
                "image_path": row["image_path"] if row else None,
            }
        )
    return {
        "schema_version": "1.0",
        "benchmark_version": POSTER_BENCHMARK_VERSION,
        "provider": spec.provider,
        "model": spec.model,
        "required_cases": POSTER_BENCHMARK_CASE_COUNT,
        "passed_cases": len(passed),
        "successful_dates": successful_dates,
        "two_days_passed": two_days_passed,
        "ocr_passed": ocr_passed,
        "manual_review_status": review_status,
        "manual_review_at": review["reviewed_at"] if review else None,
        "formal_poster_eligible": eligible,
        "reason": reason,
        "attempts_today": attempts_today,
        "remaining_calls_today": max(
            0, MAX_POSTER_ATTEMPTS_PER_DAY - attempts_today
        ),
        "cases": cases,
    }


def _effective_model_payload(
    path: Path,
    spec: ImageModelSpec,
    *,
    configured: bool,
    selected: bool,
    configuration_reason: str | None,
) -> dict[str, Any]:
    payload = spec.to_dict(
        configured=configured,
        selected=selected,
        configuration_reason=configuration_reason,
    )
    if spec.eligibility_mode == "local_benchmark":
        benchmark = poster_benchmark_status(
            path, provider=spec.provider, model=spec.model
        )
        payload["formal_poster_eligible"] = benchmark["formal_poster_eligible"]
        payload["reason"] = benchmark["reason"]
        payload["benchmark"] = benchmark
    return payload


def _model_is_formal_eligible(path: Path, spec: ImageModelSpec) -> bool:
    if spec.eligibility_mode != "local_benchmark":
        return spec.formal_poster_eligible
    return bool(
        poster_benchmark_status(path, provider=spec.provider, model=spec.model)[
            "formal_poster_eligible"
        ]
    )


def _model_configuration_status(
    spec: ImageModelSpec,
    *,
    key_store: KeyStore | None = None,
    openclaw_binary: str | Path | None = None,
) -> tuple[bool, str | None]:
    if spec.provider == POSTER_PROVIDER:
        if (key_store or KeychainStore()).get() is not None:
            return True, None
        return False, "openai_keychain_credential_missing"
    if spec.provider == OPENCLAW_POSTER_PROVIDER:
        return _openclaw_provider_configured(spec.model, binary=openclaw_binary)
    return False, "poster_provider_unsupported"


def poster_configuration(
    path: Path,
    *,
    key_store: KeyStore | None = None,
    openclaw_binary: str | Path | None = None,
) -> dict[str, Any]:
    metadata = _read_poster_metadata(path)
    provider = metadata.get(POSTER_PROVIDER_METADATA, POSTER_PROVIDER)
    model = metadata.get(POSTER_MODEL_METADATA, POSTER_MODEL)
    enabled = metadata.get(POSTER_ENABLED_METADATA, "0") == "1"
    try:
        spec = get_image_model(provider, model)
    except ValueError:
        return {
            "enabled": enabled,
            "configured": False,
            "provider": provider,
            "model": model,
            "capabilities": {},
            "formal_poster_eligible": False,
            "reason": "poster_model_unsupported",
            "configuration_reason": "poster_model_unsupported",
        }
    configured, configuration_reason = _model_configuration_status(
        spec,
        key_store=key_store,
        openclaw_binary=openclaw_binary,
    )
    return {
        "enabled": enabled,
        **_effective_model_payload(
            path,
            spec,
            configured=configured,
            selected=True,
            configuration_reason=configuration_reason,
        ),
    }


def list_poster_models(
    path: Path,
    *,
    key_store: KeyStore | None = None,
    openclaw_binary: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    metadata = _read_poster_metadata(path)
    selected_provider = metadata.get(POSTER_PROVIDER_METADATA, POSTER_PROVIDER)
    selected_model = metadata.get(POSTER_MODEL_METADATA, POSTER_MODEL)
    result: list[dict[str, Any]] = []
    for spec in IMAGE_MODELS:
        configured, configuration_reason = _model_configuration_status(
            spec,
            key_store=key_store,
            openclaw_binary=openclaw_binary,
        )
        result.append(
            _effective_model_payload(
                path,
                spec,
                configured=configured,
                selected=(
                    spec.provider == selected_provider and spec.model == selected_model
                ),
                configuration_reason=configuration_reason,
            )
        )
    return tuple(result)


def configure_poster(
    path: Path,
    *,
    enabled: bool,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    current = _read_poster_metadata(path)
    selected_provider = provider or current.get(
        POSTER_PROVIDER_METADATA, POSTER_PROVIDER
    )
    selected_model = model or current.get(POSTER_MODEL_METADATA, POSTER_MODEL)
    spec = get_image_model(selected_provider, selected_model)
    if enabled and not _model_is_formal_eligible(path, spec):
        raise ValueError("poster_model_not_formal_eligible")
    connection = connect(path)
    try:
        values = (
            (POSTER_PROVIDER_METADATA, spec.provider),
            (POSTER_MODEL_METADATA, spec.model),
            (POSTER_ENABLED_METADATA, "1" if enabled else "0"),
        )
        with connection:
            connection.executemany(
                """
                INSERT INTO radar_metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                values,
            )
    finally:
        connection.close()
    return poster_configuration(path)


def test_poster_model(
    *,
    provider: str,
    model: str,
    output: Path,
    generator: PosterGenerator | None = None,
    key_store: KeyStore | None = None,
    openclaw_binary: str | Path | None = None,
) -> dict[str, Any]:
    """Run one explicit capability smoke for a keyless, non-formal model.

    This deliberately cannot be used to bypass the formal-poster registry or
    the three-attempt daily budget for paid models.
    """

    spec = get_image_model(provider, model)
    if spec.formal_poster_eligible or spec.requires_api_key:
        raise ValueError("poster_model_test_requires_keyless_nonformal_model")
    configured, reason = _model_configuration_status(
        spec,
        key_store=key_store,
        openclaw_binary=openclaw_binary,
    )
    if not configured:
        raise RuntimeError(reason or "poster_model_not_configured")
    image_generator = generator or create_poster_generator(spec.provider, spec.model)
    if (
        image_generator.provider != spec.provider
        or image_generator.model != spec.model
    ):
        raise ValueError("poster_test_generator_mismatch")
    generated = image_generator.generate(
        PosterRequest(
            prompt=(
                "Create one simple abstract blue and green capability-test image. "
                "No people, logos, QR codes, numbers, or text."
            )
        ),
        api_key=None,
    )
    detected = _detect_image(generated.body)
    requested = output.expanduser().resolve()
    if requested.exists() and requested.is_dir():
        safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", spec.model).strip("-")
        target = requested / f"{safe_model}{detected.suffix}"
    else:
        target = requested.with_suffix(detected.suffix)
    if target.exists():
        raise RuntimeError("poster_test_output_exists")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(generated.body)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "schema_version": "1.0",
        "status": "success",
        "provider": spec.provider,
        "model": spec.model,
        "formal_poster_eligible": False,
        "media_type": detected.media_type,
        "width": detected.width,
        "height": detected.height,
        "image_path": str(target),
        "image_sha256": hashlib.sha256(generated.body).hexdigest(),
        "request_id": generated.request_id,
    }


# This is a public capability-test API, not a pytest test function. Test modules
# import it directly, so explicitly opt it out of pytest's name-based discovery.
test_poster_model.__test__ = False


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


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s·•|｜:：,，。.;；'\"“”‘’()（）/\\_-]+", "", normalized)


_NUMBER_RE = re.compile(r"[$¥]?\d+(?:[.,]\d+)?")


def validate_poster_text(text: str, facts: PosterFacts) -> PosterValidation:
    statistics = (
        f"资源 {facts.active_count} · A 级 {facts.tier_a_count} · "
        f"今日新增 {facts.new_today_count}"
    )
    refreshed = f"数据截至 {facts.refreshed_at[:16].replace('T', ' ')}"
    required = [
        POSTER_TITLE,
        facts.report_date,
        statistics,
        POSTER_NOTICE,
        refreshed,
        *(
            anchor
            for fact in facts.facts
            for anchor in (
                fact.kind,
                fact.provider,
                fact.title,
                fact.value,
                fact.instruction,
            )
        ),
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
    openclaw_binary: str | Path | None = None,
) -> dict[str, Any]:
    configuration = poster_configuration(
        path,
        key_store=key_store,
        openclaw_binary=openclaw_binary,
    )
    today = (current or date.today()).isoformat()
    report = None
    last_failure = None
    if path.exists():
        connection = connect(path)
        try:
            row = connection.execute(
                "SELECT * FROM daily_reports WHERE report_date = ?", (today,)
            ).fetchone()
            report = _report_dict(row) if row else None
            failure_rows = connection.execute(
                "SELECT key, value FROM radar_metadata WHERE key IN (?, ?, ?)",
                (
                    POSTER_LAST_FAILURE_CODE_METADATA,
                    POSTER_LAST_FAILURE_DATE_METADATA,
                    POSTER_LAST_FAILURE_AT_METADATA,
                ),
            ).fetchall()
            failure_values = {
                str(item["key"]): str(item["value"]) for item in failure_rows
            }
            if failure_values.get(POSTER_LAST_FAILURE_CODE_METADATA):
                last_failure = {
                    "error_code": failure_values[POSTER_LAST_FAILURE_CODE_METADATA],
                    "report_date": failure_values.get(
                        POSTER_LAST_FAILURE_DATE_METADATA
                    ),
                    "failed_at": failure_values.get(POSTER_LAST_FAILURE_AT_METADATA),
                }
        finally:
            connection.close()
    benchmark_spec = get_image_model(OPENCLAW_POSTER_PROVIDER, OPENCLAW_POSTER_MODEL)
    if (
        configuration.get("provider") == benchmark_spec.provider
        and configuration.get("model") == benchmark_spec.model
    ):
        benchmark_configured = bool(configuration.get("configured"))
        benchmark_configuration_reason = configuration.get("configuration_reason")
    else:
        # Do not make every status request spawn OpenClaw when another model is
        # selected. Selecting CogView while disabled is explicit and cheap.
        benchmark_configured = False
        benchmark_configuration_reason = "poster_benchmark_model_not_selected"
    benchmark = poster_benchmark_status(
        path,
        provider=benchmark_spec.provider,
        model=benchmark_spec.model,
    )
    benchmark.update(
        {
            "configured": benchmark_configured,
            "configuration_reason": benchmark_configuration_reason,
        }
    )
    return {
        "schema_version": "1.1",
        **configuration,
        "benchmark": benchmark,
        "quality": POSTER_QUALITY,
        "max_attempts_per_day": MAX_POSTER_ATTEMPTS_PER_DAY,
        "today": report,
        "latest": latest_daily_report(path),
        "last_failure": last_failure,
    }


def _record_last_failure_metadata(
    connection: Any,
    *,
    report_date: str,
    error_code: str,
    at: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO radar_metadata(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (
            (POSTER_LAST_FAILURE_CODE_METADATA, error_code),
            (POSTER_LAST_FAILURE_DATE_METADATA, report_date),
            (POSTER_LAST_FAILURE_AT_METADATA, at),
        ),
    )


def _clear_last_failure_metadata(connection: Any) -> None:
    connection.execute(
        "DELETE FROM radar_metadata WHERE key IN (?, ?, ?)",
        (
            POSTER_LAST_FAILURE_CODE_METADATA,
            POSTER_LAST_FAILURE_DATE_METADATA,
            POSTER_LAST_FAILURE_AT_METADATA,
        ),
    )


def _failure_response(
    path: Path,
    *,
    report_date: str,
    provider: str,
    model: str,
    error_code: str,
) -> dict[str, Any]:
    current = latest_daily_report(path, success_only=False)
    if current is not None and current.get("status") != "success":
        return current
    return {
        "schema_version": "1.1",
        "report_date": report_date,
        "status": "failed",
        "provider": provider,
        "model": model,
        "attempt_count": int(current.get("attempt_count") or 0) if current else 0,
        "error_code": error_code,
        "preserved_published_report": bool(current),
        "published_report_date": current.get("report_date") if current else None,
    }


def _upsert_failure(
    path: Path,
    *,
    report_date: str,
    at: str,
    error_code: str,
    facts: PosterFacts | None = None,
    provider: str = POSTER_PROVIDER,
    model: str = POSTER_MODEL,
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
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.status
                        ELSE 'failed'
                    END,
                    error_code = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.error_code
                        ELSE excluded.error_code
                    END,
                    provider = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.provider
                        ELSE excluded.provider
                    END,
                    model = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.model
                        ELSE excluded.model
                    END,
                    selected_facts_json = CASE
                        WHEN daily_reports.image_path IS NOT NULL
                            OR excluded.selected_facts_json = '{}'
                        THEN daily_reports.selected_facts_json
                        ELSE excluded.selected_facts_json
                    END,
                    updated_at = CASE
                        WHEN daily_reports.image_path IS NOT NULL THEN daily_reports.updated_at
                        ELSE excluded.updated_at
                    END
                """,
                (
                    report_date,
                    at,
                    facts.refreshed_at if facts else None,
                    provider,
                    model,
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
            _record_last_failure_metadata(
                connection,
                report_date=report_date,
                error_code=error_code,
                at=at,
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
            benchmark_attempts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM poster_model_benchmarks WHERE run_date = ?",
                    (facts.report_date,),
                ).fetchone()[0]
            )
            allowed_daily_attempts = max(
                0, MAX_POSTER_ATTEMPTS_PER_DAY - benchmark_attempts
            )
            if allowed_daily_attempts == 0:
                return None
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
                    generated_at = CASE WHEN image_path IS NULL THEN ? ELSE generated_at END,
                    radar_refreshed_at = CASE
                        WHEN image_path IS NULL THEN ? ELSE radar_refreshed_at END,
                    provider = CASE WHEN image_path IS NULL THEN ? ELSE provider END,
                    model = CASE WHEN image_path IS NULL THEN ? ELSE model END,
                    quality = CASE WHEN image_path IS NULL THEN ? ELSE quality END,
                    selected_facts_json = CASE
                        WHEN image_path IS NULL THEN ? ELSE selected_facts_json END,
                    prompt_sha256 = CASE
                        WHEN image_path IS NULL THEN ? ELSE prompt_sha256 END,
                    error_code = CASE WHEN image_path IS NULL THEN NULL ELSE error_code END,
                    updated_at = CASE WHEN image_path IS NULL THEN ? ELSE updated_at END
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
                    allowed_daily_attempts,
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
                    validation_json = CASE
                        WHEN image_path IS NULL THEN ? ELSE validation_json END,
                    error_code = CASE
                        WHEN image_path IS NULL THEN ? ELSE error_code END,
                    request_id = CASE
                        WHEN image_path IS NULL THEN ? ELSE request_id END,
                    updated_at = CASE
                        WHEN image_path IS NULL THEN ? ELSE updated_at END
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
            _record_last_failure_metadata(
                connection,
                report_date=report_date,
                error_code=error_code,
                at=at,
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
    provider: str,
    model: str,
    prompt_sha256: str,
) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET status = 'success', generated_at = ?, radar_refreshed_at = ?,
                    provider = ?, model = ?, quality = ?,
                    selected_facts_json = ?, prompt_sha256 = ?, validation_json = ?,
                    image_path = ?, image_sha256 = ?, image_bytes = ?,
                    error_code = NULL, request_id = ?, updated_at = ?
                WHERE report_date = ?
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
                    prompt_sha256,
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
            _clear_last_failure_metadata(connection)
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


def _save_webp(
    source: Path,
    target: Path,
    *,
    strict_aspect: bool = False,
) -> tuple[str, int]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("poster_image_processing_unavailable") from exc
    temporary = target.with_suffix(".webp.tmp")
    try:
        with Image.open(source) as image:
            image.load()
            rgb = image.convert("RGB")
            if strict_aspect:
                # CogView's official 864x1152 canvas is already 3:4.  Keep the
                # entire model output and only scale it; never crop, pad, or
                # stretch a benchmark-qualified daily poster.
                if rgb.width * POSTER_HEIGHT != rgb.height * POSTER_WIDTH:
                    raise RuntimeError("poster_image_aspect_ratio_invalid")
                normalized = rgb.resize(
                    (POSTER_WIDTH, POSTER_HEIGHT),
                    resample=Image.Resampling.LANCZOS,
                )
            else:
                normalized = ImageOps.fit(
                    rgb,
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


def prune_poster_benchmarks(
    path: Path,
    *,
    poster_root: Path | None = None,
    now: datetime | None = None,
) -> int:
    root = (poster_root or default_poster_root()).resolve()
    cutoff = (
        (now or datetime.now().astimezone())
        - timedelta(days=POSTER_BENCHMARK_IMAGE_RETENTION_DAYS)
    ).isoformat(timespec="seconds")
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT id, image_path FROM poster_model_benchmarks
            WHERE attempted_at < ? AND image_path IS NOT NULL
            """,
            (cutoff,),
        ).fetchall()
        removed = 0
        with connection:
            for row in rows:
                candidate = (root / str(row["image_path"])).resolve()
                if candidate.is_relative_to(root):
                    candidate.unlink(missing_ok=True)
                connection.execute(
                    "UPDATE poster_model_benchmarks SET image_path = NULL WHERE id = ?",
                    (row["id"],),
                )
                removed += 1
        return removed
    finally:
        connection.close()


def run_poster_benchmark(
    path: Path,
    *,
    provider: str = OPENCLAW_POSTER_PROVIDER,
    model: str = OPENCLAW_POSTER_MODEL,
    cases: int = 3,
    now: datetime | None = None,
    poster_root: Path | None = None,
    generator: PosterGenerator | None = None,
    ocr: OCRProvider | None = None,
    openclaw_binary: str | Path | None = None,
) -> dict[str, Any]:
    if not 1 <= cases <= MAX_POSTER_ATTEMPTS_PER_DAY:
        raise ValueError("invalid_poster_benchmark_case_count")
    spec = get_image_model(provider, model)
    if spec.eligibility_mode != "local_benchmark" or spec.requires_api_key:
        raise ValueError("poster_model_benchmark_not_supported")
    current = (now or datetime.now().astimezone()).astimezone()
    with operation_lock(path, "poster"):
        before = poster_benchmark_status(
            path, provider=spec.provider, model=spec.model, now=current
        )
        remaining = int(before["remaining_calls_today"])
        if remaining <= 0:
            raise RuntimeError("poster_daily_attempt_limit")
        image_generator = generator
        if image_generator is None:
            configured, reason = _model_configuration_status(
                spec, openclaw_binary=openclaw_binary
            )
            if not configured:
                raise RuntimeError(reason or "poster_model_not_configured")
            image_generator = create_poster_generator(spec.provider, spec.model)
        if (
            image_generator.provider != spec.provider
            or image_generator.model != spec.model
        ):
            raise ValueError("poster_test_generator_mismatch")
        ocr_provider = ocr or MacOSVisionOCR()
        root = (poster_root or default_poster_root()).resolve()
        benchmark_root = root / "benchmarks"
        benchmark_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(benchmark_root, 0o700)
        prune_poster_benchmarks(path, poster_root=root, now=current)
        passed_ids = {
            str(item["case_id"])
            for item in before["cases"]
            if item["status"] == "success"
        }
        pending = [
            (case_id, facts)
            for case_id, facts in _benchmark_cases()
            if case_id not in passed_ids
        ]
        selected = pending[: min(cases, remaining)]
        results: list[dict[str, Any]] = []
        for case_id, facts in selected:
            attempted_at = datetime.now().astimezone().isoformat(timespec="seconds")
            candidate: Path | None = None
            normalized: Path | None = None
            target: Path | None = None
            validation: PosterValidation | None = None
            detected: DetectedImage | None = None
            image_hash: str | None = None
            error_code: str | None = None
            try:
                generated = image_generator.generate(
                    PosterRequest(
                        prompt=build_poster_prompt(facts),
                        size="864x1152",
                    ),
                    api_key=None,
                )
                detected = _detect_image(
                    generated.body, require_poster_ratio=True
                )
                descriptor, candidate_name = tempfile.mkstemp(
                    prefix=f".{case_id}-",
                    suffix=detected.suffix,
                    dir=benchmark_root,
                )
                candidate = Path(candidate_name)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(generated.body)
                os.chmod(candidate, 0o600)
                normalized_descriptor, normalized_name = tempfile.mkstemp(
                    prefix=f".{case_id}-final-",
                    suffix=".webp",
                    dir=benchmark_root,
                )
                os.close(normalized_descriptor)
                normalized = Path(normalized_name)
                normalized.unlink(missing_ok=True)
                image_hash, _image_bytes = _save_webp(
                    candidate,
                    normalized,
                    strict_aspect=True,
                )
                recognized = ocr_provider.recognize(normalized)
                validation = validate_poster_text(recognized, facts)
                if not validation.valid:
                    raise RuntimeError("poster_validation_failed")
                target = (
                    benchmark_root
                    / f"{POSTER_BENCHMARK_VERSION}-{case_id}-{image_hash}.webp"
                )
                os.replace(normalized, target)
                normalized = None
                status = "success"
            except Exception as exc:
                status = "failed"
                error_code = _safe_error(exc)
            finally:
                if candidate is not None:
                    candidate.unlink(missing_ok=True)
                if normalized is not None:
                    normalized.unlink(missing_ok=True)
                if status == "failed" and target is not None:
                    target.unlink(missing_ok=True)
            connection = connect(path)
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO poster_model_benchmarks(
                            benchmark_version, provider, model, case_id,
                            run_date, attempted_at, status, media_type, width,
                            height, final_image_sha256, validation_json,
                            image_path, error_code
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            POSTER_BENCHMARK_VERSION,
                            spec.provider,
                            spec.model,
                            case_id,
                            current.date().isoformat(),
                            attempted_at,
                            status,
                            detected.media_type if detected else None,
                            POSTER_WIDTH if status == "success" else None,
                            POSTER_HEIGHT if status == "success" else None,
                            image_hash if status == "success" else None,
                            json.dumps(
                                validation.to_dict() if validation else {},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            str(target.relative_to(root))
                            if status == "success" and target is not None
                            else None,
                            error_code,
                        ),
                    )
            finally:
                connection.close()
            results.append(
                {
                    "case_id": case_id,
                    "status": status,
                    "error_code": error_code,
                    "image_path": str(target) if status == "success" and target else None,
                }
            )
        return {
            "schema_version": "1.0",
            "results": results,
            "benchmark": poster_benchmark_status(
                path, provider=spec.provider, model=spec.model, now=current
            ),
        }


def review_poster_benchmark(
    path: Path,
    *,
    provider: str = OPENCLAW_POSTER_PROVIDER,
    model: str = OPENCLAW_POSTER_MODEL,
    approve: bool,
    notes: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    spec = get_image_model(provider, model)
    if spec.eligibility_mode != "local_benchmark":
        raise ValueError("poster_model_benchmark_not_supported")
    current = (now or datetime.now().astimezone()).astimezone()
    before = poster_benchmark_status(
        path, provider=spec.provider, model=spec.model, now=current
    )
    if approve and not (
        before["ocr_passed"] and before["two_days_passed"]
    ):
        raise ValueError("poster_benchmark_incomplete")
    clean_notes = " ".join(str(notes).split())[:500]
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO poster_model_reviews(
                    provider, model, benchmark_version, status, reviewed_at,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, model, benchmark_version) DO UPDATE SET
                    status = excluded.status,
                    reviewed_at = excluded.reviewed_at,
                    notes = excluded.notes
                """,
                (
                    spec.provider,
                    spec.model,
                    POSTER_BENCHMARK_VERSION,
                    "approved" if approve else "rejected",
                    current.isoformat(timespec="seconds"),
                    clean_notes,
                ),
            )
    finally:
        connection.close()
    return poster_benchmark_status(
        path, provider=spec.provider, model=spec.model, now=current
    )


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


def _generate_daily_poster_unlocked(
    path: Path,
    *,
    force: bool = False,
    now: datetime | None = None,
    poster_root: Path | None = None,
    generator: PosterGenerator | None = None,
    ocr: OCRProvider | None = None,
    key_store: KeyStore | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now().astimezone()).astimezone()
    at = current.isoformat(timespec="seconds")
    report_date = current.date().isoformat()
    configuration = poster_configuration(path, key_store=key_store)
    explicit_selection = provider is not None or model is not None
    selected_provider = provider or str(configuration["provider"])
    if provider is not None and model is None:
        selected_model = (
            OPENCLAW_POSTER_MODEL
            if provider.casefold() == OPENCLAW_POSTER_PROVIDER
            else POSTER_MODEL
        )
    else:
        selected_model = model or str(configuration["model"])

    image_generator: PosterGenerator
    model_spec: ImageModelSpec | None = None
    if generator is None:
        if not bool(configuration["enabled"]) and not explicit_selection:
            return {
                "schema_version": "1.1",
                "status": "disabled",
                "provider": selected_provider,
                "model": selected_model,
                "error_code": "poster_disabled",
            }
        try:
            if provider is None and model is not None:
                model_spec = find_image_model(model)
                selected_provider = model_spec.provider
                selected_model = model_spec.model
            else:
                model_spec = get_image_model(selected_provider, selected_model)
            image_generator = create_poster_generator(
                model_spec.provider,
                model_spec.model,
            )
        except ValueError as exc:
            error_code = _safe_error(exc)
            _upsert_failure(
                path,
                report_date=report_date,
                at=at,
                error_code=error_code,
                provider=selected_provider,
                model=selected_model,
            )
            return _failure_response(
                path,
                report_date=report_date,
                provider=selected_provider,
                model=selected_model,
                error_code=error_code,
            )
    else:
        image_generator = generator
        selected_provider = image_generator.provider
        selected_model = image_generator.model
        try:
            model_spec = get_image_model(selected_provider, selected_model)
        except ValueError:
            _upsert_failure(
                path,
                report_date=report_date,
                at=at,
                error_code="poster_model_unsupported",
                provider=selected_provider,
                model=selected_model,
            )
            return _failure_response(
                path,
                report_date=report_date,
                provider=selected_provider,
                model=selected_model,
                error_code="poster_model_unsupported",
            )

    if model_spec is not None and not _model_is_formal_eligible(path, model_spec):
        _upsert_failure(
            path,
            report_date=report_date,
            at=at,
            error_code="poster_model_not_formal_eligible",
            provider=model_spec.provider,
            model=model_spec.model,
        )
        return _failure_response(
            path,
            report_date=report_date,
            provider=model_spec.provider,
            model=model_spec.model,
            error_code="poster_model_not_formal_eligible",
        )

    api_key: str | None = None
    if getattr(image_generator, "requires_api_key", True):
        api_key = (key_store or KeychainStore()).get()
        if not api_key:
            _upsert_failure(
                path,
                report_date=report_date,
                at=at,
                error_code="poster_not_configured",
                provider=selected_provider,
                model=selected_model,
            )
            return _failure_response(
                path,
                report_date=report_date,
                provider=selected_provider,
                model=selected_model,
                error_code="poster_not_configured",
            )

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
    previous_image: Path | None = None
    if existing and existing.get("status") == "success" and existing.get("image_path"):
        candidate = (root / str(existing["image_path"])).resolve()
        if candidate.is_relative_to(root.resolve()):
            previous_image = candidate

    try:
        facts = select_poster_facts(path, now=current)
        facts = _compact_facts_for_model(facts, selected_model)
    except Exception as exc:
        error_code = _safe_error(exc)
        _upsert_failure(
            path,
            report_date=report_date,
            at=at,
            error_code=error_code,
            provider=selected_provider,
            model=selected_model,
        )
        return _failure_response(
            path,
            report_date=report_date,
            provider=selected_provider,
            model=selected_model,
            error_code=error_code,
        )

    ocr_provider = ocr or MacOSVisionOCR()
    correction_notes: tuple[str, ...] = ()
    last_error_code = "poster_generation_failed"
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
            last_error_code = "poster_daily_attempt_limit"
            _upsert_failure(
                path,
                report_date=report_date,
                at=datetime.now().astimezone().isoformat(timespec="seconds"),
                error_code="poster_daily_attempt_limit",
                facts=facts,
                provider=image_generator.provider,
                model=image_generator.model,
            )
            break
        generated: GeneratedPoster | None = None
        validation: PosterValidation | None = None
        candidate: Path | None = None
        normalized: Path | None = None
        target: Path | None = None
        try:
            generated = image_generator.generate(
                PosterRequest(prompt=prompt),
                api_key=api_key,
            )
            detected = _detect_image(
                generated.body,
                require_poster_ratio=True,
            )
            descriptor, candidate_name = tempfile.mkstemp(
                prefix=f".{report_date}-{attempt}-",
                suffix=detected.suffix,
                dir=root,
            )
            candidate = Path(candidate_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(generated.body)
            os.chmod(candidate, 0o600)
            normalized_descriptor, normalized_name = tempfile.mkstemp(
                prefix=f".{report_date}-{attempt}-final-",
                suffix=".webp",
                dir=root,
            )
            os.close(normalized_descriptor)
            normalized = Path(normalized_name)
            normalized.unlink(missing_ok=True)
            image_hash, image_bytes = _save_webp(
                candidate,
                normalized,
                strict_aspect=(selected_model == OPENCLAW_POSTER_MODEL),
            )
            recognized = ocr_provider.recognize(normalized)
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
            target = root / f"{report_date}-{image_hash}.webp"
            os.replace(normalized, target)
            normalized = None
            success_at = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                _record_success(
                    path,
                    facts=facts,
                    validation=validation,
                    relative_image_path=target.name,
                    image_sha256=image_hash,
                    image_bytes=image_bytes,
                    request_id=generated.request_id,
                    at=success_at,
                    provider=image_generator.provider,
                    model=image_generator.model,
                    prompt_sha256=prompt_hash,
                )
            except Exception:
                if previous_image is None or target != previous_image:
                    target.unlink(missing_ok=True)
                raise
            if previous_image is not None and previous_image != target:
                try:
                    previous_image.unlink(missing_ok=True)
                except OSError:
                    pass
            return latest_daily_report(path, success_only=False) or {}
        except Exception as exc:
            error_code = _safe_error(exc)
            last_error_code = error_code
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
                "poster_openclaw_unavailable",
                "poster_openclaw_invalid_response",
            }:
                break
            if attempt >= MAX_POSTER_ATTEMPTS_PER_DAY:
                break
        finally:
            if candidate is not None:
                candidate.unlink(missing_ok=True)
            if normalized is not None:
                normalized.unlink(missing_ok=True)
    return _failure_response(
        path,
        report_date=report_date,
        provider=image_generator.provider,
        model=image_generator.model,
        error_code=last_error_code,
    )


def generate_daily_poster(
    path: Path,
    *,
    force: bool = False,
    now: datetime | None = None,
    poster_root: Path | None = None,
    generator: PosterGenerator | None = None,
    ocr: OCRProvider | None = None,
    key_store: KeyStore | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    with operation_lock(path, "poster"):
        return _generate_daily_poster_unlocked(
            path,
            force=force,
            now=now,
            poster_root=poster_root,
            generator=generator,
            ocr=ocr,
            key_store=key_store,
            provider=provider,
            model=model,
        )
