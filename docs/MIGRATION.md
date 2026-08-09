# Migrating to v0.2

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
