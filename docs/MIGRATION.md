# Migrating installed services

## v0.7.0 to v0.7.1

This release does not change SQLite schema v7 or move any database, poster, report, or cache
paths. The local Dashboard no longer exposes the poster view; old `#poster`, `?view=poster`, and
`?tab=poster` links normalize to the recommended free-resources view without calling poster APIs.
Poster backend routes and stored history remain available for compatibility. The public static site
continues to publish only free-resource and price views.

## v0.4 to v0.6

v0.6 keeps SQLite schema v7, so opening an existing database performs no data migration. The
change is architectural: local Dashboard assets, API routing, and CLI dispatch now come from the
standalone package. Embedding hosts should pin the matching package version and provide only their
database/poster paths, port, project root, and host diagnostics.

Existing `/ai-resources.html`, `/ai-resources.css`, `/ai-resources.js`, API payloads, error codes,
database locations, and LaunchAgent labels remain compatible. Nested browser modules are served
under `/ai-radar-assets/`; custom hosts must pass that prefix through the safe asset resolver.
Reinstall an existing service after upgrading so its immutable runtime bundle contains the new
modules and nested browser assets.

## v0.3 to v0.4

Stop or reinstall the service with the host-specific installer so it can create the normal online
backup before the first v0.4 open. Schema v6 migrates to v7 transactionally. Existing resources,
source caches, evidence, changes, notifications, daily reports, and tips are retained; the new
objects only add tip application batches and poster benchmark/review audit.

CogView remains disabled after upgrade. Run `ai-radar poster benchmark` on at least two natural
days, confirm 6/6 final-WebP OCR results, then run `ai-radar poster benchmark review --approve`.
Only after that gate can `poster configure --provider openclaw --model zai/cogview-3-flash --enable`
succeed. v0.4 never falls back to a paid OpenAI image request.

The initial three delegation tips can be adopted atomically with `tips approve-batch ... --scope
both --adopt-existing`. That command removes only the two documented legacy delegation sections,
creates private backups, and records a batch ID for whole-group rollback.

## Standalone v0.1 users

1. Stop the services with `ai-radar service uninstall`.
2. Back up `~/Library/Application Support/AIResourceRadar/radar.sqlite3`.
3. Run `python -m pip install --upgrade ai-resource-radar`.
4. Run `ai-radar doctor`, then `ai-radar refresh`.
5. Reinstall services with `ai-radar service install`.

If v0.1 read OpenAI credentials from `AI_RADAR_OPENAI_API_KEY`, run `ai-radar poster key set`
before enabling posters. v0.2 intentionally ignores API keys in environment variables and reads
the OpenAI credential only from macOS Keychain.

The first v0.2 open migrates schema v4 to v5 in one SQLite transaction. Current offers, evidence,
changes, notifications, source cache state, and daily reports are retained. New modality fields are
backfilled deterministically. The database stays in its existing location.

## Computer Health host users

Computer Health keeps its existing database, poster directory, dashboard port `18765`, and service
labels. It supplies those paths to the same `ai-resource-radar` package; it does not create a second
standalone database. Do not install the standalone daily LaunchAgent on the same account. Both
installers reject the conflicting service and show the matching uninstall command.

An unsupported newer database is never downgraded. The CLI reports
`ai_radar_schema_unsupported`; the dashboard returns the same structured error with HTTP 503.

## Recovery

Installation creates a timestamped online SQLite backup before replacing a runtime. Backups are
kept for seven days. Restoring a backup requires stopping the dashboard and daily services first;
never copy only the main `.sqlite3` file while a WAL connection is active.
