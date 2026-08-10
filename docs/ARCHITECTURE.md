# Architecture

The project has two deliberately separated paths:

1. **Deterministic radar** — allow-listed fetchers parse official/community sources, normalize offers, rank them with transparent A–D tiers, detect changes, and store compact evidence in SQLite.
2. **Optional poster** — deterministic selectors choose five facts, a provider adapter generates one complete image, and local OCR validates exact anchors before an atomic publish.

Core modules:

- `sources`, `runtime`, `store`: acquisition, parsing, migrations, evidence, changes, notifications, and retention.
- `pricing`: normalized token and GPU price queries.
- `model_registry`, `poster`: provider/model capabilities, formal-poster eligibility, GPT Image 2 and OpenClaw adapters, Keychain access, five-fact selection, final-WebP OCR validation, retries, and storage.
- `doctor`, `locks`: version/schema/freshness diagnostics and process-safe refresh/poster/tip locks.
- `tips`: deterministic official discovery, manual candidates, approval, managed AGENTS.md application, audit, and rollback.
- `dashboard`, `dashboard_state`: loopback-only APIs and local static UI.
- `service`: macOS LaunchAgents for the dashboard, menu bar, and daily workflow.

SQLite schema v7 adds transactional multi-tip application batches and the local poster benchmark/review audit while preserving all v6 resources, modalities, notifications, daily reports, tips, and evidence. CogView benchmark images are generated at the official 864×1152 portrait size, proportionally normalized to 1080×1440 WebP, and validated on the final file. Failed candidate images are temporary files and are never retained.

`ai-resource-radar` is the sole implementation of the radar core. A host such as Computer Health may provide its own paths, port, and LaunchAgent labels, but must call this package rather than copy collectors or storage code. Lock files live next to the selected database so different entry points coordinate on the same resource.
