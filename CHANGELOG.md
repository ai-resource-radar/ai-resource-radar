# Changelog

## 0.2.0 — 2026-08-09

- Upgrade the public database schema to v5 with normalized input/output modalities and verified
  free-image-generation filtering.
- Add the official Zhipu CogView-3-Flash free image API source.
- Add source freshness states, process-safe refresh/poster locks, and `ai-radar doctor`.
- Add provider-aware poster configuration and OpenClaw model discovery. ZAI CogView can be tested
  but is blocked from formal Chinese posters until it passes the OCR benchmark.
- Validate the final 1080×1440 WebP with local Vision OCR and reject mismatched media before
  publishing.
- Establish `ai-resource-radar` as the single core package used by Computer Health integrations.
- Add PyPI Trusted Publishing, verified release assets, checksums, and clean-wheel smoke tests.

See [the migration guide](docs/MIGRATION.md) before upgrading an installed macOS service.
