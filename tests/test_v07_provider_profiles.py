"""Contracts for the v0.7 official provider catalogue and snippets."""

from __future__ import annotations

import json
import re
import unittest

from ai_resource_radar.collection.registry import SOURCES
from ai_resource_radar.provider_profiles import (
    COMMUNITY_SOURCE_IDS,
    CURSOR_PROVIDER_DOCS,
    OFFICIAL_SOURCE_IDS,
    PROVIDER_BY_SOURCE_ID,
    PROVIDER_PROFILES,
    integration_public_rows,
    provider_for_record,
    provider_public_rows,
    provider_slug_for,
    render_integration_snippets,
)


class ProviderProfileTests(unittest.TestCase):
    def test_catalog_has_twenty_profiles_and_all_official_sources(self) -> None:
        self.assertEqual(len(PROVIDER_PROFILES), 20)
        self.assertEqual(
            set(OFFICIAL_SOURCE_IDS),
            {source.id for source in SOURCES if source.authority.startswith("official")},
        )
        covered = {source_id for profile in PROVIDER_PROFILES for source_id in profile.source_ids}
        self.assertEqual(covered, set(OFFICIAL_SOURCE_IDS))
        self.assertFalse(covered & set(COMMUNITY_SOURCE_IDS))
        self.assertEqual(
            PROVIDER_BY_SOURCE_ID["huggingface-zerogpu"].slug,
            PROVIDER_BY_SOURCE_ID["huggingface-inference-credits"].slug,
        )

    def test_slugs_are_stable_and_aliases_resolve(self) -> None:
        slugs = [profile.slug for profile in PROVIDER_PROFILES]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) for slug in slugs))
        self.assertEqual(provider_slug_for("智谱 AI"), "zhipu-ai")
        self.assertEqual(provider_slug_for("阿里云百炼"), "alibaba-model-studio")
        self.assertEqual(provider_slug_for("ignored", "huggingface-inference-credits"), "huggingface")

    def test_rows_are_json_safe_and_prices_without_source_id_map(self) -> None:
        rows = provider_public_rows()
        self.assertEqual(len(rows), 20)
        json.dumps(rows, ensure_ascii=False)
        self.assertEqual(
            provider_for_record({"provider": "Hugging Face Inference"}).slug,
            "huggingface",
        )
        self.assertEqual(
            provider_for_record({"provider": "Alibaba Cloud Model Studio"}).slug,
            "alibaba-model-studio",
        )
        self.assertIsNone(provider_for_record({"provider": "not-a-provider"}))
        self.assertIsNone(
            provider_for_record(
                {"provider": "OpenRouter", "source_id": "mnfst-free-llm-apis"}
            )
        )
        self.assertIsNone(
            provider_for_record(
                {"provider": "OpenRouter", "verification_level": "community"}
            )
        )
        self.assertEqual(
            provider_for_record(
                {"provider": "OpenRouter", "verification_level": "official_api"}
            ).slug,
            "openrouter",
        )

    def test_verified_batch_has_all_client_templates_and_env_only_secrets(self) -> None:
        rows = integration_public_rows()
        self.assertEqual(len(rows), 9)
        for row in rows:
            snippets = row["templates"]
            self.assertEqual({"curl", "python", "openclaw"} - set(snippets), set())
            if row["slug"] in CURSOR_PROVIDER_DOCS:
                self.assertIn("cursor", snippets)
            else:
                self.assertNotIn("cursor", snippets)
            profile = next(profile for profile in PROVIDER_PROFILES if profile.slug == row["slug"])
            env = profile.auth_env_var
            self.assertIsNotNone(env)
            self.assertIn(f'"{profile.slug}": {{', snippets["openclaw"])
            for snippet in snippets.values():
                self.assertIn(env, snippet)
                self.assertNotRegex(snippet, r"(?:sk|hf|gsk|AIza)[-_A-Za-z0-9]{12,}")
        self.assertIn("codex", render_integration_snippets("openrouter"))
        for slug in ("groq", "mistral-ai", "sambanova", "siliconflow", "zhipu-ai", "cerebras"):
            self.assertNotIn("codex", render_integration_snippets(slug))

    def test_codex_template_targets_user_config_and_declares_responses(self) -> None:
        snippet = render_integration_snippets("openrouter")["codex"]
        self.assertIn("~/.codex/config.toml", snippet)
        self.assertIn('wire_api = "responses"', snippet)
        self.assertIn('env_key = "OPENROUTER_API_KEY"', snippet)


if __name__ == "__main__":
    unittest.main()
