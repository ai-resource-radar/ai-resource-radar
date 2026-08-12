# Contributing

Thanks for helping keep the radar accurate and useful. Please read the [Code of
Conduct](CODE_OF_CONDUCT.md) first, then create a focused branch and a small pull request.

## A lightweight provider adapter

For a new provider, use this path instead of adding a one-off scraper:

1. Open a source request with one official, public HTTPS page or API and the exact quota, price,
   eligibility, reset, region, and expiry facts it states.
2. Add one `RadarSource` entry in `src/ai_resource_radar/sources.py`. Keep the host allow-list,
   terms/license, cadence, and source kind explicit.
3. Add a narrow parser function that returns normalized `OfferObservation` values. Reuse the
   existing normalization helpers; do not copy a full web page into the repository.
4. Add a minimal fixture and tests for the happy path, a missing/changed field, and a source-level
   failure. A parser drift must preserve the last trusted value and mark that source for review.
5. Run the focused tests and include the public source URL in the pull request. Do not add login
   automation, private endpoints, referral links, or an AI call to the default collection path.

The adapter should be independently failure-safe: one timeout or shape change must not erase data
from another provider. Community lists may discover candidates, but only an official source can
support an officially verified offer.

## Public site and documentation

The Pages site is built from the normalized snapshot; it is not a second radar implementation. Keep
the output contract in [PUBLIC_SITE.md](docs/PUBLIC_SITE.md), and preserve the `healthy`/`partial`
publication gate. If a severe integrity check fails, the workflow must leave the previously
deployed site untouched. Draft launch copy belongs in [LAUNCH_KIT.md](docs/LAUNCH_KIT.md) and is
never an automatic post.

## Checks before opening a PR

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/ai_resource_radar/web/ai-resources.js
```

When changing native macOS helpers, run the corresponding Swift compile check. Never commit API
keys, cookies, account data, databases, logs, generated posters, or private source responses.

## Maintainer release preflight

The maintainer can validate a future release without opening a browser or changing remote state:

```bash
python3 .github/scripts/release_preflight.py
python3 .github/scripts/release_preflight.py --online --full
```

The default command is local and read-only. `--online` only checks the existing GitHub CLI/keyring
identity, `origin/main`, tag availability, and PyPI version availability. `--full` runs the Python
and JavaScript checks. The command never logs in, creates or moves a tag, pushes, or publishes;
those remain separate, explicit maintainer actions after `main` CI is green.
