# Evidence

Raw artifacts supporting the validation reports in
[docs/archive/](../docs/archive/). These are logs, checkpoints, and example
run exports — not documentation themselves.

## Contents

- `cursor-full-restart-validation/` — raw logs (pre-shutdown process list, MCP
  reconnect log, a mid-run state checkpoint, a corruption note) from the full
  IDE cold-restart recovery test. Referenced from
  [docs/archive/FINAL_CURSOR_RESTART_ACCEPTANCE_REPORT.md](../docs/archive/FINAL_CURSOR_RESTART_ACCEPTANCE_REPORT.md).
- `dogfood-tasks/` — example manual-run and orchestrated-run exports, used as
  reference fixtures for the run-export format
  ([docs/run-export-format.md](../docs/run-export-format.md)) and the
  productivity study
  ([docs/productivity-study-results.md](../docs/productivity-study-results.md)).

The authoritative, current runtime state for any slice lives in
`.orchestrator_slice/` at the repository root (gitignored — it's generated,
not committed). Generate your own evidence for a given run with:

```bash
uv run slice inspect <slice>       # event stream / audit trail
uv run slice diagnostics <slice>   # blockers, pending work, evidence locations
uv run slice export <slice>        # reproducible run package
```

See [docs/diagnostics.md](../docs/diagnostics.md) for the full command
reference.
