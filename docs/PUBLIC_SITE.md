# Public Radar site

The public site is a static, read-only view of the latest **AI Resource Radar** snapshot:

- Live site: <https://ai-resource-radar.github.io/ai-resource-radar/>
- Machine-readable data: <https://ai-resource-radar.github.io/ai-resource-radar/data/manifest.json>
- English entry: <https://ai-resource-radar.github.io/ai-resource-radar/>
- Chinese entry: <https://ai-resource-radar.github.io/ai-resource-radar/zh/>
- English Atom/RSS: `/en/feed.xml` and `/en/rss.xml`
- Chinese-compatible Atom/RSS: `/feed.xml` and `/rss.xml`
- Builder: `ai-radar site build --database PATH --output DIR --base-url URL`
- Search Console option: `--search-console-provider none|google` (local default: `none`)
- Provider pages: `/zh/providers/<slug>/` and `/en/providers/<slug>/`
- Scenario pages: `/zh/scenarios/<slug>/` and `/en/scenarios/<slug>/`

The repository's Pages workflow runs the deterministic, keyless primary refresh at 00:37 UTC each
day and after every push to `main`. A fallback run starts at 03:17 UTC: it fetches the live manifest
and skips refresh and deployment only when that manifest reports a healthy or partial snapshot
refreshed today in Asia/Shanghai, no `stale`/`never` sources, and an age of at most four hours.
Fetch, parse, missing, old, or abnormal fallback data instead runs the normal refresh. Whenever a
refresh runs, primary, fallback, and push events force all 23 registered sources even when a CI-only
SQLite cache is restored. Manual runs force by default and expose an explicit `force=false`
diagnostic opt-out. The cache carries last trusted values between runs; it is not a user database
and is never published.

## Public schema

`data/manifest.json` is the entry point. It is intentionally small and stable:

```json
{
  "schema_version": "1.4",
  "dataset": "ai-resource-radar-public",
  "package_version": "0.9.0",
  "default_language": "en",
  "supported_languages": ["en", "zh-CN"],
  "region_model_version": "2026-08-14.v1",
  "region_presets": {"eu-eea": ["AT", "BE", "..."], "southeast-asia": ["BN", "KH", "..."]},
  "source_revision": "0123456789abcdef",
  "refresh_mode": "forced",
  "refresh_started_at": "2026-01-01T00:24:00Z",
  "data_age_seconds": 120,
  "analytics_provider": "none",
  "search_console_provider": "none",
  "experiment_started_at": "2026-08-12",
  "scenario_pages": [
    "zh/scenarios/<slug>/", "en/scenarios/<slug>/"
  ],
  "feeds": ["feed.xml", "rss.xml", "en/feed.xml", "en/rss.xml"],
  "status": "healthy",
  "generated_at": "2026-01-01T00:27:00Z",
  "radar_refreshed_at": "2026-01-01T00:25:00Z",
  "counts": {"resources": 0, "official_verified_resources": 0, "community_candidates": 0, "token_prices": 0, "gpu_prices": 0, "changes": 0},
  "source_health": {},
  "files": [
    "data/resources.json", "data/token-prices.json", "data/gpu-prices.json",
    "data/changes.json", "data/summary.json", "data/source-health.json",
    "data/featured.json", "data/important-changes.json",
    "data/providers.json", "data/integrations.json", "data/scenarios.json"
  ],
  "file_hashes": {},
  "file_bytes": {}
}
```

`status` is `healthy` when all sources are fresh, or `partial` when one or more sources failed or
need verification but the remaining trusted data is safe to show. A severe or untrustworthy build
is not publishable. For CI-bound builds, `source_revision` identifies the exact source commit,
`refresh_mode` records whether cadence was bypassed, and `data_age_seconds` must not exceed 1,800.
All 23 registered source IDs must occur in the refresh report; `stale` and `never` are rejected.
`source_health` records bounded source counts; `data/source-health.json` contains the per-source
status and timestamp. Neither contains
request headers, response bodies, cookies, or account identifiers. `files` and `file_hashes` let a client
discover and verify the generated JSON without trusting page markup.

The data files use the same normalized vocabulary as the local radar, with a public-only subset.
Every tabular export has a same-named CSV companion; small status badges are emitted as
`data/badges/*.json` for README and monitoring integrations. Clients should discover exact filenames
from `manifest.files` rather than assuming a future badge name:

| File | Contents |
| --- | --- |
| `data/resources.json` (+ `.csv`) | Current token, GPU, and grant offers: stable ID, provider/title, kind, quota/unit, reset or expiry, six tri-state signup requirements, ISO country facts, bilingual presentations, verification level, source URL, and observed time. |
| `data/token-prices.json` (+ `.csv`) | Token input/output/cached prices normalized per 1M tokens, with provider/model, currency, source URL, and observed time. |
| `data/gpu-prices.json` (+ `.csv`) | GPU on-demand prices normalized per hour, with provider/model, currency, region, source URL, and observed time. |
| `data/changes.json` (+ `.csv`) | Bounded recent additions, removals, quota/price/restriction changes, source ID, and event time. |
| `data/summary.json` | Counts, update times, category totals, and the values needed for the public overview. |
| `data/source-health.json` | Per-source status, last successful observation, and bounded error code; never raw response data. |
| `data/featured.json` | A compact, deterministic set of official A/B no-card resources for the first viewport. |
| `data/important-changes.json` | At most five high-signal removals, quota/restriction changes, or expiry events. |
| `data/providers.json` | Twenty canonical official-provider profiles, stable slugs, official URLs, protocol capabilities, and bilingual page URLs. |
| `data/integrations.json` | Conservative environment-variable-only templates and the official protocol/client evidence used to enable them. |
| `data/scenarios.json` | Six bilingual scenario definitions with route URLs, bounded counts, and filter summaries; confirmation routes remain `noindex`. |
| `data/badges/*.json` | Small generated status/count badges; each badge is derived from the manifest and is not an endorsement. |

The manifest also lists the twelve localized scenario routes in `scenario_pages` and the four public
feed routes in `feeds`. The JSON example above abbreviates the route list; production output contains
all entries. Scenario pages are static, crawlable views for six bounded intents, published under
`/zh/scenarios/<slug>/` and `/en/scenarios/<slug>/`. They link back to the same public catalogue and
official evidence, but do not personalize content or promise that an offer remains available.

## Feeds and safe links

The root Atom and RSS documents `/feed.xml` and `/rss.xml` remain Chinese-compatible stable URLs;
the English homepage auto-discovers `/en/feed.xml` and `/en/rss.xml`. They expose only public
resources and bounded recent changes. Each
entry uses a stable hash identifier rather than a SQLite row ID and includes an observed time and a
safe same-origin or official-source URL. Source text, request headers, cookies, account fields, and
local paths are never copied into a feed. Consumers should treat every item as a time-sensitive
snapshot, follow the official URL before acting, and avoid interpreting an entry as a guarantee of
quota, price, eligibility, or availability.

GitHub Watch is reserved for release and maintenance activity. It is not the daily resource feed and
does not change the public data contract.

## Search Console verification and the 30-day experiment

Local builds use `--search-console-provider none`. Production Pages passes
`--search-console-provider google`; the builder reads only
`AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN` from the environment. A missing or malformed production
token is a publication error raised by `site build` before the new directory replaces the previous
one. The token is serialized only in Google's required public homepage verification meta marker; it
is omitted from JSON, XML, logs, and workflow output. Google Search Console is an ownership/indexing
aid, not a collection source and not a user-tracking feature.

`experiment_started_at` records the start of a bounded 30-day discovery experiment. At the end of the
window, the project checks three gates: at least 10 of 12 scenario pages indexed, exposure in three
intent categories, and at least one click or bounded confirmation signal. These are aggregate reach
signals only. A confirmation is not an exact signup, purchase, or other conversion measurement, and
the public site exports no user identity or per-user journey.

Clients should ignore unknown fields and use `schema_version` and `dataset` to decide whether a
breaking change needs an adapter. A URL is labelled as `official` or `community` in its record:
official URLs support official verification, while community URLs are discovery baselines and must
not be read as provider policy. The public site is not an authority over any source's current terms.

## Privacy and safety

Only aggregate, public-source facts are exported. The site never publishes API keys, cookies,
account data, local filesystem paths, SQLite files, raw fetched pages, full request/response logs,
or poster-generation output. Source excerpts are bounded and are omitted from the public export
when they could identify a user. The local dashboard remains loopback-only.

The site has no login or data-submission form. Local builds default to `--analytics-provider none`
and `--search-console-provider none`, and contain no remote script. Production Pages uses
`--analytics-provider cloudflare` only when the repository variable
`CLOUDFLARE_WEB_ANALYTICS_TOKEN` is present, and passes `--search-console-provider google` only for
the production ownership check. The build then adds one Cloudflare Web Analytics beacon per page and
a narrowly matching CSP. It uses no cookies, local storage, fingerprinting, user IDs, custom events,
search/filter text, keys, or account data. If the beacon is blocked, all radar content and navigation
continue to work. Cloudflare supplies aggregate page path, referrer, device/browser, country, and
performance dimensions and retains the aggregate data under its Web Analytics policy. Google Search
Console receives aggregate indexing/search reporting for the verified public property; its site
verification token is read only from the build environment and appears only in Google's required
public homepage marker; it is not logged or copied to feeds.

The canonical `/` landing page is English and `/zh/` is Chinese. Language selection is never inferred
from IP address or browser settings. Country and region choices live only in the shareable query URL;
the site uses no cookie or local storage. The landing page fetches only the manifest, summary, source health, featured resources, and bounded
important changes. Full resources and price datasets load when the corresponding view is opened and
are cached for the current browser session. Existing full JSON/CSV URLs remain stable for machine
consumers, and the four Atom/RSS feeds expose the same public-only projection with stable hash IDs.
A consumer should still treat every offer as time-sensitive and follow the official URL before
signing up or spending money.

Every official provider profile and each of the six scenario pages is pre-rendered as crawlable HTML
in Chinese and English. Critical policy, price, evidence, and integration content does not depend on
JavaScript. Community discovery sources do not receive official provider profiles. Correction links
open a public GitHub Issue with bounded public facts only; users must remove any private account
evidence before submitting. Scenario pages and feeds are discovery surfaces, not exact conversion
instrumentation; a click or confirmation signal in the 30-day experiment cannot be read as a verified
signup or purchase.

## Pages publication and failure policy

The workflow installs the package, restores only the CI SQLite snapshot, force-refreshes every
allow-listed source, and runs `site build` with both the repository revision and refresh report. It
also requires the public Cloudflare site token and maps the repository's
`GOOGLE_SITE_VERIFICATION_TOKEN` secret to `AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN` before building
production Pages. `site build` itself rejects a missing or malformed Google token and keeps the
previous output atomically. The workflow never prints either token; the Google token appears only in
the required public homepage verification marker. It verifies a non-empty
`index.html` and `data/manifest.json`, exactly 23 source attempts in the current refresh report, data
age of at most 30 minutes, no `stale`/`never` source, and a matching Git revision. It then accepts
only `healthy` or `partial` manifests, provider/integration datasets, all 12 scenario pages, all four
feeds, the production Search Console marker, and exactly one analytics beacon in the root page. The
artifact is uploaded and deployed in a separate Pages job, so a build or gate failure—and a fallback
skip—cannot replace the last deployed site.

One source failure is represented as `partial`; the parser keeps that source's last trusted value
and records its health while other sources continue. A schema error, missing required output, or
severe data-integrity threshold fails the build. Turning off force for a manual diagnostic never
bypasses parser validation or the publication gate. There are no credentials or AI calls in this
path.

For verifiable snapshots, download the files listed in `manifest.files` and verify their
`manifest.file_hashes` entries. Do not mirror the SQLite cache or infer a provider policy from a
single stale snapshot.
