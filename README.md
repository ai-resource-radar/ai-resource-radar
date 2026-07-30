# AI Resource Radar

[中文说明](README.zh-CN.md)

AI Resource Radar is a deterministic, local-first tracker for:

- free AI token/API tiers;
- free GPU compute and grant programs;
- normalized token and GPU price leaderboards;
- evidence-backed changes and local notifications;
- an optional daily poster generated as one complete image by GPT Image 2.

The default collection pipeline does **not** use AI, API keys, cookies, or account data. AI is only used by the optional poster feature. Poster text and numbers are checked locally with macOS Vision OCR before publication.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

ai-radar refresh
ai-radar dashboard --open
```

The standalone dashboard binds only to `127.0.0.1:18766`.

## Daily poster

The poster contains three verified free offers, one token price, and one GPU price. The model draws the entire poster; the application never overlays or rewrites its text. Invalid text or unexpected numbers trigger retries, with a hard limit of three image calls per day.

```bash
ai-radar poster key set
ai-radar poster generate
ai-radar poster latest
```

The OpenAI API key is entered with a hidden prompt and stored in macOS Keychain. It is never stored in SQLite, configuration files, logs, or Git. GPT Image 2 requires paid API access.

To install the dashboard, menu bar helper, and the 08:00 daily job:

```bash
ai-radar service install
ai-radar service status
```

## Data and privacy

- Official sources are refreshed every 24 hours; community discovery sources follow their configured cadence.
- HTTPS sources are allow-listed, limited to 16 MB, isolated on failure, and support ETag/Last-Modified.
- SQLite uses schema v4, file mode `0600`, 90/365-day history policies, and periodic VACUUM.
- Posters are retained for 90 days. Failed candidate images are deleted immediately.
- The dashboard accepts only loopback Host/Origin requests and serves no remote assets.

See [Architecture](docs/ARCHITECTURE.md), [Security](docs/SECURITY.md), and [Contributing](CONTRIBUTING.md).

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
node --check src/ai_resource_radar/web/ai-resources.js
```

Linux CI validates the deterministic core. macOS CI additionally compiles the Vision OCR and menu bar Swift helpers.

## License

MIT
