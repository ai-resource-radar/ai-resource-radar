# Architecture

The supported user path is deliberately narrow, while compatibility code remains isolated:

1. **Deterministic radar** — allow-listed fetchers parse official/community sources, normalize offers, rank them with transparent A–D tiers, detect changes, and store compact evidence in SQLite. This powers the local Dashboard and the public free-resource/price snapshot.
2. **Retained poster backend** — the historical provider, OCR, report, and API paths remain isolated for stored-report and host compatibility. The v0.7.3 Dashboard does not expose or request them; legacy poster routes return to the recommended radar view.

Core modules:

- `collection`: source models, the 23-source registry, allow-listed acquisition metadata, and
  source-specific parsers. The historical `sources` path is a compatibility facade.
- `persistence`: schema v7, migrations, repositories, evidence, changes, and retention. The
  historical `store` path remains compatible.
- `application`: refresh orchestration, failure isolation, change detection, and maintenance.
  The historical `runtime` path remains compatible.
- `pricing`: normalized token and GPU price queries.
- `posters`: provider/model capabilities, formal-poster eligibility, GPT Image 2 and OpenClaw
  adapters, Keychain access, fact selection, final-WebP OCR validation, benchmark, and records.
- `doctor`, `locks`: version/schema/freshness diagnostics and process-safe refresh/poster/tip locks.
- `tip_management`: deterministic official discovery, manual candidates, approval, managed
  AGENTS.md application, audit, and rollback.
- `interfaces`: a stable CLI dispatcher, host-neutral Dashboard port/router, and safe static-asset
  resolver shared by standalone and embedded servers.
- `dashboard`, `dashboard_state`: loopback transport and stateful background-task facade.
- `service`: macOS LaunchAgents for the dashboard, menu bar, and daily workflow.

The browser UI is dependency-free. Native modules separate API cancellation, URL state,
formatters, components, and view renderers; CSS is split into token, base, layout, component,
view, and responsive layers. Legacy `/ai-resources.js` and `/ai-resources.css` remain entry points.

SQLite schema v7 adds transactional multi-tip application batches and retains the local poster
benchmark/review audit while preserving all v6 resources, modalities, notifications, daily reports,
tips, and evidence. The v0.7.3 Dashboard does not start poster generation or load poster images;
existing reports and audit rows remain readable through backend compatibility paths.

`ai-resource-radar` is the sole implementation of the radar core. A host such as Computer Health may provide its own paths, port, and LaunchAgent labels, but must call this package rather than copy collectors or storage code. Lock files live next to the selected database so different entry points coordinate on the same resource.
