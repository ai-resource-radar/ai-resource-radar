# Security and privacy

- No user API keys are used by the radar collectors.
- The optional OpenAI key is stored in macOS Keychain and is never accepted through command-line arguments, environment variables, configuration files, SQLite, or logs.
- Secrets, cookies, database files, logs, and generated posters are excluded from Git.
- Fetching is limited to explicit HTTPS hosts, 16 MB per response, per-source timeouts, and isolated failures.
- The dashboard binds to loopback, validates Host and Origin, uses a restrictive CSP, and serves no third-party assets.
- SQLite and poster directories use private permissions.
- OCR runs locally with macOS Vision. OCR text is stored only as bounded validation metadata.
- OpenClaw remains responsible for credentials configured in OpenClaw. The radar stores only the non-sensitive provider/model selection and capability result.
- Every formal poster model must be explicitly eligible. Test-only models are rejected before a paid or quota-consuming request is made by the daily workflow.

Report vulnerabilities privately to the repository owner before opening a public issue containing sensitive details.
