from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ai_resource_radar.model_registry import get_image_model
from ai_resource_radar.poster import (
    GeneratedPoster,
    OPENCLAW_POSTER_MODEL,
    POSTER_HEIGHT,
    POSTER_NOTICE,
    POSTER_TITLE,
    POSTER_WIDTH,
    _benchmark_cases,
    _save_webp,
    configure_poster,
    poster_benchmark_status,
    review_poster_benchmark,
    run_poster_benchmark,
)
from ai_resource_radar.store import SCHEMA_VERSION, connect


DAY_ONE = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)


def benchmark_ocr_text(facts) -> str:
    lines = [
        POSTER_TITLE,
        facts.report_date,
        f"资源 {facts.active_count} A 级 {facts.tier_a_count} 今日新增 {facts.new_today_count}",
        f"数据截至 {facts.refreshed_at[:16].replace('T', ' ')}",
    ]
    lines.extend(
        value
        for card in facts.facts
        for value in (card.kind, card.provider, card.title, card.value, card.instruction)
    )
    lines.append(POSTER_NOTICE)
    return "\n".join(lines)


class CogViewFixtureGenerator:
    provider = "openclaw"
    model = OPENCLAW_POSTER_MODEL
    requires_api_key = False

    def __init__(self) -> None:
        image = Image.new("RGB", (864, 1152), "#132237")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        self.body = buffer.getvalue()
        self.requests = []

    def generate(self, request, *, api_key=None):
        self.requests.append(request)
        return GeneratedPoster(body=self.body, request_id=f"fixture-{len(self.requests)}")


class SequenceOCR:
    def __init__(self, values: list[str]) -> None:
        self.values = iter(values)
        self.seen: list[tuple[str, tuple[int, int]]] = []

    def recognize(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            self.seen.append((str(image.format), image.size))
        return next(self.values)


class V04PosterTests(unittest.TestCase):
    def test_cogview_uses_official_portrait_size_and_stays_ineligible(self) -> None:
        spec = get_image_model("openclaw", OPENCLAW_POSTER_MODEL)
        self.assertIn("864x1152", spec.capabilities["sizes"])
        self.assertEqual(spec.eligibility_mode, "local_benchmark")
        self.assertFalse(spec.formal_poster_eligible)

    def test_cogview_normalization_only_scales_and_never_crops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.png"
            target = Path(temp) / "target.webp"
            Image.new("RGB", (864, 1152), "#132237").save(source)
            _save_webp(source, target, strict_aspect=True)
            with Image.open(target) as normalized:
                self.assertEqual(normalized.size, (POSTER_WIDTH, POSTER_HEIGHT))

            Image.new("RGB", (864, 1100), "#132237").save(source)
            with self.assertRaisesRegex(
                RuntimeError, "poster_image_aspect_ratio_invalid"
            ):
                _save_webp(source, target, strict_aspect=True)

    def test_six_cases_require_two_days_and_manual_review(self) -> None:
        cases = _benchmark_cases()
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            root = Path(temp) / "posters"
            generator = CogViewFixtureGenerator()
            ocr = SequenceOCR([benchmark_ocr_text(facts) for _, facts in cases])

            first = run_poster_benchmark(
                database,
                now=DAY_ONE,
                cases=3,
                poster_root=root,
                generator=generator,
                ocr=ocr,
            )
            self.assertEqual(first["benchmark"]["passed_cases"], 3)
            self.assertEqual(first["benchmark"]["remaining_calls_today"], 0)
            self.assertFalse(first["benchmark"]["formal_poster_eligible"])
            with self.assertRaisesRegex(RuntimeError, "poster_daily_attempt_limit"):
                run_poster_benchmark(
                    database,
                    now=DAY_ONE,
                    cases=1,
                    poster_root=root,
                    generator=generator,
                    ocr=ocr,
                )

            second = run_poster_benchmark(
                database,
                now=DAY_ONE + timedelta(days=1),
                cases=3,
                poster_root=root,
                generator=generator,
                ocr=ocr,
            )
            status = second["benchmark"]
            self.assertEqual(status["passed_cases"], 6)
            self.assertTrue(status["ocr_passed"])
            self.assertTrue(status["two_days_passed"])
            self.assertEqual(status["reason"], "benchmark_manual_review_required")
            self.assertTrue(all(request.size == "864x1152" for request in generator.requests))
            self.assertTrue(all(item == ("WEBP", (POSTER_WIDTH, POSTER_HEIGHT)) for item in ocr.seen))

            reviewed = review_poster_benchmark(
                database,
                approve=True,
                notes="人工确认无重影、裁切或错位。",
                now=DAY_ONE + timedelta(days=1, hours=1),
            )
            self.assertTrue(reviewed["formal_poster_eligible"])
            configured = configure_poster(
                database,
                enabled=True,
                provider="openclaw",
                model=OPENCLAW_POSTER_MODEL,
            )
            self.assertTrue(configured["enabled"])
            self.assertTrue(configured["formal_poster_eligible"])

    def test_failed_ocr_does_not_qualify_and_extra_number_is_rejected(self) -> None:
        case_id, facts = _benchmark_cases()[0]
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            generator = CogViewFixtureGenerator()
            ocr = SequenceOCR([benchmark_ocr_text(facts) + "\n额外 999999 元"])
            result = run_poster_benchmark(
                database,
                now=DAY_ONE,
                cases=1,
                poster_root=Path(temp) / "posters",
                generator=generator,
                ocr=ocr,
            )
            self.assertEqual(result["results"][0]["case_id"], case_id)
            self.assertEqual(result["results"][0]["status"], "failed")
            self.assertEqual(result["benchmark"]["passed_cases"], 0)
            with self.assertRaisesRegex(ValueError, "poster_benchmark_incomplete"):
                review_poster_benchmark(database, approve=True, now=DAY_ONE)
            with self.assertRaisesRegex(ValueError, "poster_model_not_formal_eligible"):
                configure_poster(
                    database,
                    enabled=True,
                    provider="openclaw",
                    model=OPENCLAW_POSTER_MODEL,
                )

    def test_schema_six_migrates_to_seven_without_losing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            raw = sqlite3.connect(database)
            raw.execute("CREATE TABLE radar_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            raw.execute("INSERT INTO radar_metadata VALUES ('sentinel', 'keep')")
            raw.execute("PRAGMA user_version = 6")
            raw.commit()
            raw.close()

            migrated = connect(database)
            try:
                self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(migrated.execute("SELECT value FROM radar_metadata WHERE key='sentinel'").fetchone()[0], "keep")
                tables = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"tip_application_batches", "poster_model_benchmarks", "poster_model_reviews"} <= tables)
            finally:
                migrated.close()

    def test_schema_seven_objects_roll_back_together_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            raw = sqlite3.connect(database)
            raw.execute("CREATE TABLE radar_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            raw.execute("INSERT INTO radar_metadata VALUES ('sentinel', 'keep')")
            raw.execute("PRAGMA user_version = 6")
            raw.commit()
            raw.close()

            def interrupted(connection):
                connection.execute("CREATE TABLE should_rollback(value TEXT)")
                raise RuntimeError("simulated_v7_failure")

            with patch("ai_resource_radar.store._create_v7_schema", side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, "simulated_v7_failure"):
                    connect(database)
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("PRAGMA user_version").fetchone()[0], 6)
                self.assertIsNone(
                    check.execute(
                        "SELECT name FROM sqlite_master WHERE name='should_rollback'"
                    ).fetchone()
                )
                self.assertEqual(check.execute("SELECT value FROM radar_metadata WHERE key='sentinel'").fetchone()[0], "keep")
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
