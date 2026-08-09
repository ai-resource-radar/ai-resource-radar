# Uninstall

Stop and remove the macOS LaunchAgents first:

```bash
ai-radar service uninstall
python -m pip uninstall ai-resource-radar
```

Those commands intentionally retain local data. The default retained paths are:

- `~/Library/Application Support/AIResourceRadar/` — database, posters, locks, and backups.
- `~/Library/Logs/AIResourceRadar/` — service logs.
- macOS Keychain service `ai-resource-radar.openai`, account `default` — optional poster key.

To remove data completely, verify those exact paths and delete them manually after the services are
stopped. Remove the Keychain credential with `ai-radar poster key delete` before uninstalling the
Python package. Computer Health host data uses different paths and is not removed by the standalone
uninstaller.
