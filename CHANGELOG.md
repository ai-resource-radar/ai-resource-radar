# Changelog

## 0.4.0 — 2026-08-10

- Expand the deterministic registry from 15 to 23 sources with official SambaNova, Mistral,
  Hugging Face Inference, SiliconFlow, Alibaba Model Studio, Cerebras, Replicate, and Baseten adapters.
- Add official Token and GPU pricing rows for Replicate and Baseten, including normalized per-million
  Token and per-hour GPU units.
- Add schema v7 transactional tip-application batches, exact adoption of two legacy delegation
  sections, one backup set, audit records, failure restoration, and whole-batch rollback.
- Add a six-case, two-day CogView-3-Flash Chinese poster benchmark with a shared three-call daily
  budget, final-WebP OCR/numeric validation, and a mandatory human review gate.
- Request the official `864×1152` CogView portrait size and proportionally convert it to
  `1080×1440` WebP without adding or redrawing text.
- Add benchmark CLI/API/Dashboard controls while keeping the free poster disabled until every gate passes.

## 0.3.0 — 2026-08-10

- Add an approval-gated AI efficiency tips library with official Codex discovery and manual imports.
- Add schema v6 tip evidence, review history, AGENTS.md application audit, backups, and safe rollback.
- Add the `tips` CLI, local Dashboard/API view, and the user-provided Luna delegation workflow as the first candidate.
- Keep all tip discovery deterministic and prevent unreviewed web content from changing Codex instructions.
- Add a bilingual, interactive, read-only GitHub Pages radar with complete JSON/CSV exports,
  source-health badges, deterministic publication gates, and daily keyless refreshes.
- Add `ai-radar site build` and the one-command `uvx ai-resource-radar start --open` experience.
- Add public data privacy projection, full price pagination, Linux XDG paths, issue forms, a
  provider-adapter contribution path, and a review-only bilingual launch kit.

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
