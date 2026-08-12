# Changelog

## 0.8.0 — 2026-08-12

- Add six bilingual, crawlable scenario pages and four public Atom/RSS feed endpoints with stable
  hash IDs, bounded source evidence, and safe same-origin or official-source links.
- Add production Google Search Console site verification as a fail-closed `site build` option while
  keeping local builds at `--search-console-provider none`; the token is rendered only in Google's
  required public homepage marker and never enters manifests, feeds, logs, or workflow output.
- Record `scenario_pages`, `feeds`, `search_console_provider`, and `experiment_started_at` in the
  public manifest. The 30-day discovery experiment uses aggregate gates—10/12 scenario pages
  indexed, three intent categories exposed, and one click or bounded confirmation signal—and does
  not claim exact user conversion.
- Keep SQLite schema v7 and collection, storage, API, CLI, Dashboard, release, tag, and PyPI
  behavior compatible.

## 0.7.3 — 2026-08-12

- Prepare the project for brand-owned public distribution without changing collection, storage,
  API, CLI, Dashboard, or schema-v7 behavior.
- Replace personal repository, Pages, issue, and package author metadata with the AI Resource Radar
  contributor identity; future releases use a project-owned GitHub noreply address.
- Add release privacy checks for new commits, package metadata, local paths, personal email patterns,
  and image metadata while retaining historical provenance unchanged.

## 0.7.2 — 2026-08-11

- Refresh the English and Chinese READMEs with current public-radar, provider-profile, and local
  Dashboard screenshots captured from the same 23-source data snapshot.
- Remove obsolete v0.3 Dashboard artwork and the paused poster sample from the public repository.
- Keep SQLite schema v7 and all collection, CLI, API, Dashboard, and service behavior unchanged.

## 0.7.1 — 2026-08-11

- Pause the local Dashboard poster surface: its navigation and controls are removed, and legacy
  poster links now return to the recommended free-resources view without requesting poster APIs.
- Keep poster backend routes, stored reports, and the schema-v7 history available for compatibility;
  the public site continues to expose only free resources and price rankings.
- Bump the package and stable facade version to 0.7.1.

## 0.7.0 — 2026-08-10

- Generate 20 canonical, bilingual official-provider profiles with stable URLs, canonical/hreflang
  metadata, current free policies, normalized prices, official evidence, and crawlable static HTML.
- Add conservative, deterministic curl/Python/OpenClaw examples for nine verified endpoints,
  provider-documented Cursor guidance for SambaNova and SiliconFlow, and Codex configuration only
  for the explicitly verified OpenRouter Responses API.
- Keep the landing payload small with `featured.json` and `important-changes.json`; load the full
  resource, Token-price, and GPU-price datasets only when their views are opened.
- Add card-level public data-correction links and an Issue form while filtering private fields and
  preserving all existing JSON/CSV URLs.
- Add opt-in, public-site-only Cloudflare Web Analytics with no cookies or custom events. Local
  builds and the loopback Dashboard remain analytics-free.
- Extend public manifest schema 1.2 with provider/integration datasets while keeping SQLite schema v7.

## 0.6.1 — 2026-08-10

- Use one shared dependency-free design layer for the local Dashboard and public site, including
  semantic tokens, safe links, formatters, and the offer card that explains what you get, the
  entry requirements, the first claim step, and official evidence.
- Simplify the public site to two primary destinations: Free Resources and Price Rankings. Keep
  important changes on the recommended overview only and replace progressive loading with explicit
  previous/page/next pagination.
- Bind every Pages snapshot to package version, source revision, refresh mode, refresh start time,
  and data age in public manifest schema 1.1 while keeping existing JSON/CSV URLs compatible.
- Force all 23 allow-listed sources on `main` pushes and scheduled Pages builds. Reject snapshots
  older than 30 minutes or with missing, stale, or never-attempted sources; isolated source failures
  may still publish a clearly marked partial snapshot.

## 0.6.0 — 2026-08-10

- Redesign the local Dashboard around four clear destinations: Free Resources, Price Rankings,
  Daily Poster, and Tips. Recent changes remain available from the overview without competing for
  a primary navigation slot.
- Show exactly what each free offer provides, its entry requirements, the first claim step, and
  explicit claim/detail actions. Render price rankings in compact desktop rows and responsive
  mobile cards, with 20-row progressive loading instead of hundreds of DOM nodes at once.
- Add a compact first screen, progressive price filters, actionable source health, and mobile-safe
  navigation without a catch-all “More” menu.
- Add native ES module and layered CSS boundaries, keyboard-visible focus, dialog focus return,
  request cancellation, URL state, reduced-motion support, and a visually aligned public snapshot.
- Make the standalone package the only source of Dashboard assets and HTTP/CLI behavior; embedding
  hosts now supply only paths, ports, runtime labels, and host diagnostics.
- Split collection, persistence, refresh orchestration, posters, and tip management behind stable
  legacy module facades. SQLite remains schema v7 and existing JSON/error contracts remain intact.
- Add a host-neutral `RadarDashboardPort`, shared HTTP router, safe nested asset resolver, and
  context-aware CLI dispatcher.

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
