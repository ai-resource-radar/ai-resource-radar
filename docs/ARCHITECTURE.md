# Architecture

The project has two deliberately separated paths:

1. **Deterministic radar** — allow-listed fetchers parse official/community sources, normalize offers, rank them with transparent A–D tiers, detect changes, and store compact evidence in SQLite.
2. **Optional poster** — deterministic selectors choose five facts, a provider adapter generates one complete image, and local OCR validates exact anchors before an atomic publish.

Core modules:

- `sources`, `runtime`, `store`: acquisition, parsing, migrations, evidence, changes, notifications, and retention.
- `pricing`: normalized token and GPU price queries.
- `poster`: provider protocol, GPT Image 2 adapter, Keychain access, five-fact selection, OCR validation, retries, and WebP storage.
- `dashboard`, `dashboard_state`: loopback-only APIs and local static UI.
- `service`: macOS LaunchAgents for the dashboard, menu bar, and daily workflow.

SQLite schema v4 keeps current offers/evidence, compact change history, notifications, source cache metadata, and one daily report row per date. Failed candidate images are temporary files and are never retained.
