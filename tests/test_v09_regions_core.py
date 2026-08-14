"""v0.9 availability, signup-friction, migration, and locale contracts."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from ai_resource_radar.collection.models import OfferObservation
from ai_resource_radar.interfaces.http import route_radar_get
from ai_resource_radar.regions import parse_regions, resolve_country_filter
from ai_resource_radar.sources import SOURCES
from ai_resource_radar.store import begin_run, connect, ingest_source, list_offers


def _observation(
    offer_id: str,
    *,
    title: str = "Example Free API",
    availability_scope: str = "restricted",
    availability: dict[str, str] | None = None,
) -> OfferObservation:
    return OfferObservation(
        offer_id=offer_id,
        provider="Example",
        title=title,
        kind="token",
        offer_type="recurring_free",
        quota_value=10,
        quota_unit="requests",
        reset_period="daily",
        estimated_usd_value=None,
        requires_card="no",
        requires_phone="unknown",
        requires_identity_verification="not_required",
        requires_paid_topup="unknown",
        requires_waitlist="unknown",
        requires_organization="unknown",
        eligibility="Officially available to eligible accounts.",
        mainland_status="supported",
        expires_at=None,
        homepage_url="https://example.test/offer",
        verification_level="official_page",
        source_url="https://example.test/offer",
        evidence_excerpt="Official availability evidence.",
        details={},
        availability_scope=availability_scope,
        availability=availability or {"CN": "supported"},
    )


class RegionCoreTests(unittest.TestCase):
    def _database_with_offer(self, root: str) -> Path:
        path = Path(root) / "radar.sqlite3"
        connection = connect(path)
        source = SOURCES[0]
        run_id, baseline = begin_run(connection, source.id, "2026-08-14T00:00:00+00:00")
        ingest_source(
            connection,
            source=source,
            observations=(_observation("token:v09"),),
            at="2026-08-14T00:00:00+00:00",
            run_id=run_id,
            http_status=200,
            etag=None,
            last_modified=None,
            content_hash="fixture",
            baseline=baseline,
        )
        connection.close()
        return path

    def test_strict_iso2_presets_and_mutual_exclusion(self) -> None:
        self.assertTrue({"IS", "LI", "NO"} <= set(parse_regions("eu-eea")))
        self.assertEqual(parse_regions("southeast-asia")[0], "BN")
        self.assertEqual(resolve_country_filter(country="CN"), ("CN",))
        with self.assertRaisesRegex(ValueError, "invalid_country_filter"):
            resolve_country_filter(country="ZZ")
        with self.assertRaisesRegex(ValueError, "invalid_region_filter"):
            resolve_country_filter(region="made-up")
        with self.assertRaisesRegex(ValueError, "mutually_exclusive"):
            resolve_country_filter(country="CN", region="china")

    def test_country_filter_excludes_unknown_by_default_and_returns_contract(self) -> None:
        with TemporaryDirectory() as root:
            path = self._database_with_offer(root)
            connection = connect(path)
            source = SOURCES[0]
            run_id, baseline = begin_run(connection, source.id, "2026-08-14T01:00:00+00:00")
            ingest_source(
                connection,
                source=source,
                observations=(
                    _observation(
                        "token:unknown", title="A unknown availability",
                        availability={"US": "supported"},
                    ),
                ),
                at="2026-08-14T01:00:00+00:00",
                run_id=run_id,
                http_status=200,
                etag=None,
                last_modified=None,
                content_hash="unknown-fixture",
                baseline=baseline,
            )
            connection.close()
            result = list_offers(path, country="CN", locale="zh-CN")
            self.assertEqual(len(result), 1)
            item = result[0]
            self.assertEqual(item["availability_status"], "supported")
            self.assertEqual(
                set(item["signup_requirements"]),
                {"card", "phone", "identity_verification", "paid_topup", "waitlist", "organization"},
            )
            self.assertEqual(item["signup_requirements"]["card"], "not_required")
            self.assertEqual(
                set(item["availability"]),
                {"scope", "supported_countries", "unsupported_countries", "evidence"},
            )
            self.assertIn("zh-CN", item["presentations"])
            self.assertEqual(
                set(item["presentation"]),
                {"presentation", "title", "benefit_summary", "eligibility", "usage_steps", "limitations"},
            )
            self.assertFalse(list_offers(path, country="JP"))
            self.assertEqual(
                [item["offer_id"] for item in list_offers(path, country="CN", include_unknown_region=True)],
                ["token:v09", "token:unknown"],
            )

    def test_region_requires_every_member_and_legacy_mainland_is_exclusive(self) -> None:
        with TemporaryDirectory() as root:
            path = self._database_with_offer(root)
            self.assertFalse(list_offers(path, region="north-america"))
            self.assertEqual(
                list_offers(path, region="north-america", include_unknown_region=True)[0]["availability_status"],
                "unknown",
            )
            with self.assertRaisesRegex(ValueError, "mutually_exclusive"):
                list_offers(path, mainland=("supported",), country="CN")

    def test_explicit_unsupported_overrides_global_fallback(self) -> None:
        with TemporaryDirectory() as root:
            path = self._database_with_offer(root)
            connection = connect(path)
            source = SOURCES[0]
            run_id, baseline = begin_run(connection, source.id, "2026-08-15T00:00:00+00:00")
            ingest_source(
                connection,
                source=source,
                observations=(
                    _observation(
                        "token:global",
                        availability_scope="global",
                        availability={"US": "unsupported"},
                    ),
                ),
                at="2026-08-15T00:00:00+00:00",
                run_id=run_id,
                http_status=200,
                etag=None,
                last_modified=None,
                content_hash="global-fixture",
                baseline=baseline,
            )
            connection.close()
            us = list_offers(path, country="US", include_unknown_region=True)
            self.assertFalse(any(item["offer_id"] == "token:global" for item in us))
            global_cn = next(item for item in list_offers(path, country="CN") if item["offer_id"] == "token:global")
            self.assertEqual(global_cn["availability_status"], "supported")

    def test_default_official_presentations_are_bilingual_without_cjk_in_english(self) -> None:
        from ai_resource_radar.collection.parsers import _official_offer

        item = _official_offer(
            provider="Example", title="Example API", kind="token", offer_type="recurring_free",
            quota_value=1, quota_unit="request", reset_period="daily", estimated_usd_value=None,
            requires_card="no", eligibility="仅限新用户。", mainland_status="unknown",
            source_url="https://example.test", evidence_excerpt="fixture",
        )
        self.assertEqual(set(item.presentations), {"en", "zh-CN"})
        self.assertFalse(any(re.search(r"[\u3400-\u9fff]", value or "") for value in item.presentations["en"].values() if isinstance(value, str)))

    def test_cli_markdown_uses_requested_locale(self) -> None:
        from ai_resource_radar.cli import _list_markdown

        record = {
            "priority_tier": "A", "provider": "Example", "title": "中文标题",
            "quota_value": None, "requires_card": "no",
            "presentation": {"title": "Example free API"},
        }
        english = _list_markdown((record,), locale="en")
        chinese = _list_markdown((record,), locale="zh-CN")
        self.assertIn("AI Resource Radar", english)
        self.assertIn("No credit card required", english)
        self.assertNotRegex(english, r"[\u3400-\u9fff]")
        self.assertIn("AI 资源雷达", chinese)

    def test_v7_backfill_creates_only_supported_or_unsupported_cn_evidence(self) -> None:
        with TemporaryDirectory() as root:
            path = self._database_with_offer(root)
            raw = sqlite3.connect(path)
            raw.execute("DELETE FROM offer_availability")
            raw.execute("UPDATE offers SET availability_scope = 'unknown', mainland_status = 'supported'")
            raw.execute("DELETE FROM offer_changes")
            raw.execute("DELETE FROM notifications")
            raw.execute("DROP TABLE offer_presentations")
            raw.execute("DROP TABLE offer_availability")
            raw.execute("PRAGMA user_version = 7")
            raw.commit()
            raw.close()
            migrated = connect(path)
            try:
                self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 8)
                self.assertEqual(
                    migrated.execute(
                        "SELECT availability_status FROM offer_availability WHERE country_code = 'CN'"
                    ).fetchone()[0],
                    "supported",
                )
                self.assertEqual(migrated.execute("SELECT COUNT(*) FROM offer_changes").fetchone()[0], 0)
                self.assertEqual(migrated.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)
                presentations = migrated.execute(
                    "SELECT locale, benefit_summary FROM offer_presentations ORDER BY locale"
                ).fetchall()
                self.assertEqual({row[0] for row in presentations}, {"en", "zh-CN"})
                english = next(row[1] for row in presentations if row[0] == "en")
                self.assertNotRegex(english, r"[\u3400-\u9fff]")
            finally:
                migrated.close()

    def test_http_uses_structured_bad_filter_error(self) -> None:
        class Radar:
            def schema_error(self): return None
            def offers(self, **_filters): return ()

        response = route_radar_get(Radar(), "/api/ai-resources", "country=CN&region=china")
        self.assertEqual(response.status, 400)
        self.assertEqual(response.payload["error"], "invalid_ai_resource_filter")
        self.assertIn("code", response.payload)


if __name__ == "__main__":
    unittest.main()
