# Architecture

The project has two deliberately separated paths:

1. **Deterministic radar** — allow-listed fetchers parse official/community sources, normalize offers, rank them with transparent A–D tiers, detect changes, and store compact evidence in SQLite.
2. **Optional poster** — deterministic selectors choose five facts, a provider adapter generates one complete image, and local OCR validates exact anchors before an atomic publish.

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

SQLite schema v7 adds transactional multi-tip application batches and the local poster benchmark/review audit while preserving all v6 resources, modalities, notifications, daily reports, tips, and evidence. CogView benchmark images are generated at the official 864×1152 portrait size, proportionally normalized to 1080×1440 WebP, and validated on the final file. Failed candidate images are temporary files and are never retained.

`ai-resource-radar` is the sole implementation of the radar core. A host such as Computer Health may provide its own paths, port, and LaunchAgent labels, but must call this package rather than copy collectors or storage code. Lock files live next to the selected database so different entry points coordinate on the same resource.
