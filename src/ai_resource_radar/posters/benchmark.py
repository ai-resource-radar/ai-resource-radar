"""Poster model benchmark execution and review helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ai_resource_radar.locks import operation_lock
from ai_resource_radar.model_registry import get_image_model
from ai_resource_radar.store import connect

from .constants import *  # noqa: F401,F403
from .facts import _benchmark_cases, _compact_facts_for_model, build_poster_prompt, default_poster_root
from .provider import (
    DetectedImage,
    OCRProvider,
    PosterGenerator,
    PosterRequest,
    _detect_image,
    _model_configuration_status,
    create_poster_generator,
    poster_benchmark_status,
)
from .report import _safe_error, _save_webp
from .validation import MacOSVisionOCR, PosterValidation, validate_poster_text


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


__all__ = [
    "prune_poster_benchmarks",
    "run_poster_benchmark",
    "review_poster_benchmark",
]
