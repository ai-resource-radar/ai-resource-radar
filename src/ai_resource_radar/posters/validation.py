"""Poster image/OCR and text validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any
import unicodedata

from ai_resource_radar.native_helper import prepare_macos_helper

from .constants import *  # noqa: F401,F403
from .facts import PosterFacts


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



__all__ = ["MacOSVisionOCR", "PosterValidation", "_normalize_text", "_NUMBER_RE", "validate_poster_text"]
