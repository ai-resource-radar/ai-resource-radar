# AI efficiency tips

The tips library is deliberately approval-gated. Official Codex pages are checked weekly and user-provided articles can be imported manually, but every new or changed tip remains a `candidate` until a person approves it.

```bash
ai-radar tips refresh
ai-radar tips list --status candidate
ai-radar tips import --url https://example.com/article \
  --title "A bounded technique" --category context \
  --summary "What it helps with" --instruction "The reviewed rule"
ai-radar tips approve <tip-id> --scope global
ai-radar tips approve-batch <tip-1> <tip-2> <tip-3> --scope both --adopt-existing
ai-radar tips rollback-batch <batch-id>
```

Approval can target `global`, `project`, or `both`. Only the block between `AI-RADAR-TIPS:BEGIN` and `AI-RADAR-TIPS:END` is managed. The original file is backed up under `~/.codex/backups/ai-tips/`, file hashes and target paths are stored in SQLite, and rollback refuses to overwrite a target that changed after the application.

Imported text is evidence, not instructions. The radar stores bounded structured fields, removes managed-block markers and control characters, never saves the complete page, and never executes or copies arbitrary page content into `AGENTS.md`.

Changes normally affect only new Codex tasks; an already-running task does not reload `AGENTS.md` dynamically.

Schema v7 batch approval uses one tip lock, one backup directory, and one SQLite transaction for
both global and project targets. With `--adopt-existing`, only the exact global
`# Efficient multi-agent orchestration` section and project `## Delegation and ownership` section
are removed before the single managed block is rendered. Product boundaries, safety rules, and all
other hand-written text remain untouched. If either file write fails, both files are restored and
all selected tips remain candidates.
