"""Poster providers, credentials and model configuration."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Protocol

from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ai_resource_radar.native_helper import prepare_macos_helper
from ai_resource_radar.model_registry import (
    IMAGE_MODELS,
    ImageModelSpec,
    find_image_model,
    get_image_model,
)
from ai_resource_radar.store import connect

from .constants import *  # noqa: F401,F403
from .facts import PosterFacts, _benchmark_cases
from .validation import PosterValidation

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
        request_urlopen = urlopen
        legacy_service = sys.modules.get("ai_resource_radar.posters.service")
        if legacy_service is not None:
            request_urlopen = getattr(legacy_service, "urlopen", request_urlopen)
        try:
            with request_urlopen(http_request, timeout=self.timeout) as response:
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
    runner: Any = None,
    binary_resolver: Any = None,
) -> tuple[bool, str | None]:
    resolve_binary = binary_resolver or _default_openclaw_binary
    run_command = runner or subprocess.run
    executable = str(binary) if binary is not None else resolve_binary()
    if not executable:
        return False, "openclaw_unavailable"
    try:
        completed = run_command(
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
    openclaw_checker: Any = None,
) -> tuple[bool, str | None]:
    if spec.provider == POSTER_PROVIDER:
        if (key_store or KeychainStore()).get() is not None:
            return True, None
        return False, "openai_keychain_credential_missing"
    if spec.provider == OPENCLAW_POSTER_PROVIDER:
        checker = openclaw_checker or _openclaw_provider_configured
        return checker(spec.model, binary=openclaw_binary)
    return False, "poster_provider_unsupported"


def poster_configuration(
    path: Path,
    *,
    key_store: KeyStore | None = None,
    openclaw_binary: str | Path | None = None,
    configuration_status: Any = None,
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
    status_resolver = configuration_status or _model_configuration_status
    configured, configuration_reason = status_resolver(
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
    configuration_status: Any = None,
) -> tuple[dict[str, Any], ...]:
    metadata = _read_poster_metadata(path)
    selected_provider = metadata.get(POSTER_PROVIDER_METADATA, POSTER_PROVIDER)
    selected_model = metadata.get(POSTER_MODEL_METADATA, POSTER_MODEL)
    result: list[dict[str, Any]] = []
    for spec in IMAGE_MODELS:
        status_resolver = configuration_status or _model_configuration_status
        configured, configuration_reason = status_resolver(
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
    configuration_status: Any = None,
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
    return poster_configuration(
        path,
        configuration_status=configuration_status,
    )


def test_poster_model(
    *,
    provider: str,
    model: str,
    output: Path,
    generator: PosterGenerator | None = None,
    key_store: KeyStore | None = None,
    openclaw_binary: str | Path | None = None,
    configuration_status: Any = None,
) -> dict[str, Any]:
    """Run one explicit capability smoke for a keyless, non-formal model.

    This deliberately cannot be used to bypass the formal-poster registry or
    the three-attempt daily budget for paid models.
    """

    spec = get_image_model(provider, model)
    if spec.formal_poster_eligible or spec.requires_api_key:
        raise ValueError("poster_model_test_requires_keyless_nonformal_model")
    status_resolver = configuration_status or _model_configuration_status
    configured, reason = status_resolver(
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



__all__ = ["DetectedImage", "GeneratedPoster", "KeyStore", "KeychainStore", "OCRProvider", "OpenAIImageGenerator", "OpenClawImageGenerator", "PosterGenerator", "PosterRequest", "PosterValidation", "_detect_image", "_read_image_file", "_default_openclaw_binary", "_model_configuration_status", "_model_is_formal_eligible", "_openclaw_error_code", "_openclaw_provider_configured", "configure_poster", "create_poster_generator", "list_poster_models", "poster_benchmark_status", "poster_configuration", "test_poster_model"]
