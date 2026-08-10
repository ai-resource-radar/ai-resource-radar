# Public Radar site

The public site is a static, read-only view of the latest **AI Resource Radar** snapshot:

- Live site: <https://ai-resource-radar.github.io/ai-resource-radar/>
- Machine-readable data: <https://ai-resource-radar.github.io/ai-resource-radar/data/manifest.json>
- Builder: `ai-radar site build --database PATH --output DIR --base-url URL`

The repository's Pages workflow runs the deterministic, keyless refresh at 00:20 UTC each day and
can also be started manually. It uses a CI-only SQLite cache to carry trusted values between runs;
the cache is not a user database and is never published.

## Public schema

`data/manifest.json` is the entry point. It is intentionally small and stable:

```json
{
  "schema_version": "1.0",
  "dataset": "ai-resource-radar-public",
  "status": "healthy",
  "generated_at": "2026-01-01T00:27:00Z",
  "radar_refreshed_at": "2026-01-01T00:25:00Z",
  "counts": {"resources": 0, "token_prices": 0, "gpu_prices": 0, "changes": 0},
  "source_health": {},
  "files": [
    "data/resources.json", "data/token-prices.json", "data/gpu-prices.json",
    "data/changes.json", "data/summary.json", "data/source-health.json"
  ],
  "file_hashes": {},
  "file_bytes": {}
}
```

`status` is `healthy` when all due sources completed, or `partial` when one or more sources
failed but the remaining trusted data is safe to show. A severe or untrustworthy build is not
publishable. `source_health` records bounded source counts; `data/source-health.json` contains the
per-source status and timestamp. Neither contains
request headers, response bodies, cookies, or account identifiers. `files` and `file_hashes` let a client
discover and verify the generated JSON without trusting page markup.

The data files use the same normalized vocabulary as the local radar, with a public-only subset.
Every tabular export has a same-named CSV companion; small status badges are emitted as
`data/badges/*.json` for README and monitoring integrations. Clients should discover exact filenames
from `manifest.files` rather than assuming a future badge name:

| File | Contents |
| --- | --- |
| `data/resources.json` (+ `.csv`) | Current token, GPU, and grant offers: stable ID, provider/title, kind, quota/unit, reset or expiry, card/phone/region requirements, verification level, source URL, and observed time. |
| `data/token-prices.json` (+ `.csv`) | Token input/output/cached prices normalized per 1M tokens, with provider/model, currency, source URL, and observed time. |
| `data/gpu-prices.json` (+ `.csv`) | GPU on-demand prices normalized per hour, with provider/model, currency, region, source URL, and observed time. |
| `data/changes.json` (+ `.csv`) | Bounded recent additions, removals, quota/price/restriction changes, source ID, and event time. |
| `data/summary.json` | Counts, update times, category totals, and the values needed for the public overview. |
| `data/source-health.json` | Per-source status, last successful observation, and bounded error code; never raw response data. |
| `data/badges/*.json` | Small generated status/count badges; each badge is derived from the manifest and is not an endorsement. |

Clients should ignore unknown fields and use `schema_version` and `dataset` to decide whether a
breaking change needs an adapter. A URL is labelled as `official` or `community` in its record:
official URLs support official verification, while community URLs are discovery baselines and must
not be read as provider policy. The public site is not an authority over any source's current terms.

## Privacy and safety

Only aggregate, public-source facts are exported. The site never publishes API keys, cookies,
account data, local filesystem paths, SQLite files, raw fetched pages, full request/response logs,
or poster-generation output. Source excerpts are bounded and are omitted from the public export
when they could identify a user. The local dashboard remains loopback-only.

The site has no login, form, analytics tracker, or remote script dependency. A consumer should
treat every offer as time-sensitive and follow the official URL before signing up or spending
money.

## Pages publication and failure policy

The workflow installs the package, restores only the CI SQLite snapshot, refreshes allow-listed
sources, and runs `site build` with the repository Pages base URL. It verifies a non-empty
`index.html` and `data/manifest.json`, then accepts only `healthy` or `partial` manifests. The
artifact is uploaded and deployed in a separate Pages job, so a build or gate failure cannot
replace the last deployed site.

One source failure is represented as `partial`; the parser keeps that source's last trusted value
and records its health while other sources continue. A schema error, missing required output, or
severe data-integrity threshold fails the build. A manual `force` run bypasses source cadence but
does not bypass parser validation or the publication gate. There are no credentials or AI calls in
this path.

For verifiable snapshots, download the files listed in `manifest.files` and verify their
`manifest.file_hashes` entries. Do not mirror the SQLite cache or infer a provider policy from a
single stale snapshot.
