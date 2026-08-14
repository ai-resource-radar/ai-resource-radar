"""Contracts introduced with the v0.5 internal package boundaries.

These tests intentionally exercise the legacy paths as well as the new focused
imports.  The compatibility facades use module aliases, so a caller patching a
legacy registry or helper must affect the implementation used by the runtime.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class CoreSplitTests(unittest.TestCase):
    def test_collection_facade_and_subpackages_share_identity(self) -> None:
        legacy = importlib.import_module("ai_resource_radar.sources")
        parsers = importlib.import_module("ai_resource_radar.collection.parsers")
        models = importlib.import_module("ai_resource_radar.collection.models")
        registry = importlib.import_module("ai_resource_radar.collection.registry")

        self.assertIs(legacy, parsers)
        self.assertIs(models.RadarSource, legacy.RadarSource)
        self.assertIs(models.OfferObservation, legacy.OfferObservation)
        self.assertIs(registry.SOURCES, legacy.SOURCES)
        self.assertIs(registry.SOURCE_BY_ID, legacy.SOURCE_BY_ID)

    def test_legacy_parser_monkeypatch_reaches_internal_registry(self) -> None:
        sources = importlib.import_module("ai_resource_radar.sources")
        source = sources.SOURCE_BY_ID["openrouter-models"]
        marker = object()

        def fake_parser(_payload: bytes, _source: object) -> tuple[object, ...]:
            return (marker,)

        with patch.object(sources, "PARSERS", {source.id: fake_parser}):
            self.assertEqual(sources.parse_source(source, b"ignored"), (marker,))

    def test_persistence_facade_exposes_focused_database_modules(self) -> None:
        legacy = importlib.import_module("ai_resource_radar.store")
        connection = importlib.import_module("ai_resource_radar.persistence.connection")
        schema = importlib.import_module("ai_resource_radar.persistence.schema")
        repository = importlib.import_module("ai_resource_radar.persistence.repository")
        maintenance = importlib.import_module("ai_resource_radar.persistence.maintenance")

        self.assertIsNot(legacy, connection)
        self.assertIsNot(legacy, schema)
        self.assertIsNot(legacy, repository)
        self.assertIsNot(legacy, maintenance)
        self.assertEqual(legacy.SCHEMA_VERSION, 8)
        self.assertIs(connection.UnsupportedSchemaError, legacy.UnsupportedSchemaError)
        self.assertIs(schema._create_v7_schema, legacy._create_v7_schema)
        self.assertIs(maintenance.StorageMaintenanceResult, legacy.StorageMaintenanceResult)
        self.assertIs(repository.ingest_source, legacy.ingest_source)

    def test_application_poster_and_tip_facades_keep_public_symbols(self) -> None:
        runtime = importlib.import_module("ai_resource_radar.runtime")
        refresh = importlib.import_module("ai_resource_radar.application.refresh")
        poster = importlib.import_module("ai_resource_radar.poster")
        provider = importlib.import_module("ai_resource_radar.posters.provider")
        facts = importlib.import_module("ai_resource_radar.posters.facts")
        tips = importlib.import_module("ai_resource_radar.tips")
        discovery = importlib.import_module("ai_resource_radar.tip_management.discovery")
        repository = importlib.import_module("ai_resource_radar.tip_management.repository")

        self.assertIs(runtime, refresh)
        self.assertIsNot(poster, provider)
        self.assertIsNot(poster, facts)
        self.assertIsNot(tips, discovery)
        self.assertIsNot(tips, repository)
        self.assertIs(runtime.RefreshReport, refresh.RefreshReport)
        self.assertIs(provider.OpenAIImageGenerator, poster.OpenAIImageGenerator)
        self.assertIs(facts.select_poster_facts, poster.select_poster_facts)
        self.assertIs(provider.PosterRequest, poster.PosterRequest)
        self.assertIs(facts.PosterFacts, poster.PosterFacts)
        self.assertIs(discovery.refresh_official_tips, tips.refresh_official_tips)
        self.assertIs(repository.add_tip, tips.add_tip)
        self.assertIs(repository.get_tip, tips.get_tip)

    def test_schema8_is_initialized_through_internal_connection(self) -> None:
        store = importlib.import_module("ai_resource_radar.store")
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "radar.sqlite3"
            connection = store.connect(path)
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(version, 8)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
