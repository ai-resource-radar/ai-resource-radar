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
from urllib.request import urlopen

from ai_resource_radar.locks import operation_lock
from ai_resource_radar.model_registry import ImageModelSpec, find_image_model, get_image_model
from ai_resource_radar.store import POSTER_RETENTION_DAYS, connect

from .constants import *  # noqa: F401,F403
from .benchmark import (
    prune_poster_benchmarks,
    review_poster_benchmark,
    run_poster_benchmark,
)
from .facts import (
    PosterFact,
    PosterFacts,
    _benchmark_cases,
    _compact_facts_for_model,
    _compact_number,
    _quota_text,
    _short_text,
    build_poster_prompt,
    default_poster_root,
    select_poster_facts,
)
from .provider import (
    GeneratedPoster,
    KeyStore,
    KeychainStore,
    OCRProvider,
    OpenAIImageGenerator,
    OpenClawImageGenerator,
    PosterGenerator,
    PosterRequest,
    _detect_image,
    _default_openclaw_binary,
    _model_configuration_status,
    _model_is_formal_eligible,
    _read_image_file,
    _openclaw_provider_configured,
    configure_poster,
    create_poster_generator,
    list_poster_models,
    poster_benchmark_status,
    poster_configuration,
    test_poster_model as _provider_test_poster_model,
)
from .report import (
    _candidate_suffix,
    _failure_response,
    _report_dict,
    _record_attempt_failure,
    _record_success,
    _reserve_attempt,
    _safe_error,
    _save_webp,
    _upsert_failure,
    daily_report_status,
    latest_daily_report,
    list_daily_reports,
    prune_daily_posters,
    resolve_daily_poster,
)
from .validation import MacOSVisionOCR, PosterValidation, validate_poster_text


def test_poster_model(**kwargs: Any) -> dict[str, Any]:
    """Compatibility wrapper that keeps service-level monkeypatches effective."""

    return _provider_test_poster_model(
        **kwargs,
        configuration_status=_model_configuration_status,
    )


test_poster_model.__test__ = False
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
