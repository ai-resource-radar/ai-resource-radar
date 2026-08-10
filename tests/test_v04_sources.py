from __future__ import annotations

from pathlib import Path
import unittest

from ai_resource_radar.pricing import list_gpu_prices, list_token_prices
from ai_resource_radar.sources import SOURCE_BY_ID, SOURCES, parse_source
from ai_resource_radar.store import begin_run, classify_offer, connect, ingest_source


FIXTURES = Path(__file__).with_name("fixtures")
SOURCE_FIXTURES = {
    "sambanova-free-tier": "sambanova_free_tier.html",
    "mistral-free-mode": "mistral_free_mode.html",
    "huggingface-inference-credits": "huggingface_inference_credits.html",
    "siliconflow-free-models": "siliconflow_free_models.html",
    "alibaba-model-studio-trial": "alibaba_model_studio_trial.html",
    "cerebras-free-trial": "cerebras_free_trial.html",
    "replicate-pricing": "replicate_pricing.html",
    "baseten-pricing": "baseten_pricing.html",
}


class V04SourceTests(unittest.TestCase):
    def _records(self, source_id: str):
        source = SOURCE_BY_ID[source_id]
        return parse_source(source, (FIXTURES / SOURCE_FIXTURES[source_id]).read_bytes())

    def test_registry_has_23_sources_and_strict_hosts(self) -> None:
        self.assertEqual(len(SOURCES), 23)
        for source_id in SOURCE_FIXTURES:
            source = SOURCE_BY_ID[source_id]
            self.assertTrue(source.url.startswith("https://"))
            self.assertTrue(source.allowed_hosts)
            self.assertEqual(source.cadence_hours, 24)

    def test_free_policy_tiers_and_risks(self) -> None:
        samba = self._records("sambanova-free-tier")
        self.assertEqual(len(samba), 2)
        self.assertEqual(samba[0].details["rate_limits"], {"rpm": 20, "rpd": 20, "tpd": 200_000})
        self.assertEqual(classify_offer(samba[0])[0], "A")

        mistral = self._records("mistral-free-mode")[0]
        self.assertEqual((mistral.offer_type, mistral.quota_value), ("variable_free", None))
        self.assertEqual(classify_offer(mistral)[0], "B")

        huggingface = self._records("huggingface-inference-credits")[0]
        self.assertEqual((huggingface.quota_value, huggingface.reset_period), (0.10, "monthly"))
        self.assertEqual(classify_offer(huggingface)[0], "A")

        siliconflow = self._records("siliconflow-free-models")[0]
        self.assertTrue(siliconflow.details["identity_verification_required"])
        self.assertEqual(siliconflow.mainland_status, "supported")
        self.assertEqual(classify_offer(siliconflow)[0], "B")

        alibaba = self._records("alibaba-model-studio-trial")[0]
        self.assertEqual((alibaba.quota_value, alibaba.reset_period), (1_000_000, "90_days_once"))
        self.assertIn("自动按量扣费", alibaba.details["billing_risk"])
        self.assertEqual(classify_offer(alibaba)[0], "C")

        cerebras = self._records("cerebras-free-trial")[0]
        self.assertEqual((cerebras.requires_card, cerebras.estimated_usd_value), ("yes", 5))
        self.assertFalse(cerebras.details["permanently_free"])
        self.assertEqual(classify_offer(cerebras)[0], "C")

    def test_pricing_parsers_normalize_token_and_gpu_units(self) -> None:
        replicate = self._records("replicate-pricing")
        token = next(item for item in replicate if item.kind == "token")
        t4 = next(item for item in replicate if item.title == "T4 GPU")
        self.assertEqual(token.details["prices"], {"input_mtok": 3.0, "output_mtok": 15.0})
        self.assertEqual((t4.details["hourly_usd"], t4.details["vram_gb"]), (0.81, 16))

        baseten = self._records("baseten-pricing")
        glm = next(item for item in baseten if item.title == "GLM 4.7")
        h100 = next(item for item in baseten if item.title == "H100 GPU")
        trial = next(item for item in baseten if item.kind == "grant")
        self.assertEqual(glm.details["prices"]["cache_read_mtok"], 0.12)
        self.assertAlmostEqual(h100.details["hourly_usd"], 6.4998)
        self.assertIsNone(trial.quota_value)
        self.assertEqual(classify_offer(trial)[0], "C")

    def test_official_pricing_reaches_leaderboards(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "radar.sqlite3"
            connection = connect(database)
            try:
                for source_id in ("replicate-pricing", "baseten-pricing"):
                    source = SOURCE_BY_ID[source_id]
                    run_id, baseline = begin_run(connection, source_id, "2026-08-10T00:00:00+00:00")
                    ingest_source(
                        connection,
                        source=source,
                        observations=self._records(source_id),
                        at="2026-08-10T00:00:00+00:00",
                        run_id=run_id,
                        http_status=200,
                        etag=None,
                        last_modified=None,
                        content_hash=source_id,
                        baseline=baseline,
                    )
            finally:
                connection.close()
            token_prices = list_token_prices(database, verification="official")
            gpu_prices = list_gpu_prices(database)
        self.assertGreaterEqual(token_prices["total"], 3)
        self.assertGreaterEqual(gpu_prices["total"], 4)
        self.assertTrue(all(item["verification_label"] == "官方价格" for item in token_prices["prices"]))

    def test_all_new_parsers_reject_unrelated_pages(self) -> None:
        for source_id in SOURCE_FIXTURES:
            with self.subTest(source_id=source_id):
                with self.assertRaisesRegex(ValueError, "official_page_structure_changed"):
                    parse_source(SOURCE_BY_ID[source_id], b"<main>pricing is free for someone</main>")


if __name__ == "__main__":
    unittest.main()
