# Security and privacy

- No user API keys are used by the radar collectors.
- The optional OpenAI key is stored in macOS Keychain and is never accepted as a command-line argument.
- Secrets, cookies, database files, logs, and generated posters are excluded from Git.
- Fetching is limited to explicit HTTPS hosts, 16 MB per response, per-source timeouts, and isolated failures.
- The dashboard binds to loopback, validates Host and Origin, uses a restrictive CSP, and serves no third-party assets.
- SQLite and poster directories use private permissions.
- OCR runs locally with macOS Vision. OCR text is stored only as bounded validation metadata.

Report vulnerabilities privately to the repository owner before opening a public issue containing sensitive details.
