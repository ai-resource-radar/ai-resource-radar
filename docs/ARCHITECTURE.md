# Architecture

The project has two deliberately separated paths:

1. **Deterministic radar** — allow-listed fetchers parse official/community sources, normalize offers, rank them with transparent A–D tiers, detect changes, and store compact evidence in SQLite.
2. **Optional poster** — deterministic selectors choose five facts, a provider adapter generates one complete image, and local OCR validates exact anchors before an atomic publish.

Core modules:

- `sources`, `runtime`, `store`: acquisition, parsing, migrations, evidence, changes, notifications, and retention.
- `pricing`: normalized token and GPU price queries.
- `model_registry`, `poster`: provider/model capabilities, formal-poster eligibility, GPT Image 2 and OpenClaw adapters, Keychain access, five-fact selection, final-WebP OCR validation, retries, and storage.
- `doctor`, `locks`: version/schema/freshness diagnostics and process-safe refresh/poster locks.
- `dashboard`, `dashboard_state`: loopback-only APIs and local static UI.
- `service`: macOS LaunchAgents for the dashboard, menu bar, and daily workflow.

SQLite schema v5 adds normalized input/output modalities and the derived `free_image_generation` flag while preserving current offers/evidence, compact change history, notifications, source cache metadata, and one daily report row per date. Failed candidate images are temporary files and are never retained.

`ai-resource-radar` is the sole implementation of the radar core. A host such as Computer Health may provide its own paths, port, and LaunchAgent labels, but must call this package rather than copy collectors or storage code. Lock files live next to the selected database so different entry points coordinate on the same resource.
