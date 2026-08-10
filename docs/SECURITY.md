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
- Imported tip text is untrusted data, never executable instructions. Only validated structured fields can enter the generated AGENTS.md template.
- Tip approval can target only the exact global or current-project AGENTS.md. Writes are locked, backed up, atomic, hash-audited, and rollback refuses a target changed since application.
- Local builds and the loopback Dashboard never include analytics. Production Pages may include one Cloudflare Web Analytics beacon when explicitly enabled at build time; it uses no cookies, user IDs, custom events, search text, or account data and cannot block the radar UI.
- Public correction links contain only bounded provider/record IDs, official URLs, verification times, and source revision. They exclude local paths, keys, cookies, account fields, and search input.

Report vulnerabilities privately to the repository owner before opening a public issue containing sensitive details.
