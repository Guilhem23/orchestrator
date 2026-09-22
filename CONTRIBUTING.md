# Contributing

Thanks for considering a contribution to Slice Orchestrator.

## Setup

```bash
uv sync --extra test
uv run slice doctor        # sanity-check your environment
uv run python3 -m pytest tests/ -q
```

## Before opening a PR

1. **Tests pass.** `uv run python3 -m pytest tests/ -q` must be green (240
   tests at the time of writing). Add tests for new behavior, especially
   around the state machine, gates, or MCP tool contracts — this project's
   value proposition is trustworthiness, so untested control-plane changes
   are a hard no.
2. **Docs stay in sync.** If you change a `slice_*` MCP tool's schema, the
   state machine, or the scope-manifest/gate logic, update the matching file
   in [`docs/`](docs/) in the same PR. A tool that silently diverges from its
   documented contract is exactly the kind of bug this project exists to
   prevent.
3. **Write-ups go in `docs/archive/`, not the root.** If your change is
   substantial enough to warrant a validation report or remediation
   write-up, add it to `docs/archive/` and link it from the relevant `docs/`
   page or [`docs/roadmap.md`](docs/roadmap.md) — keep the repository root
   limited to `README.md`, `LICENSE`, `CONTRIBUTING.md`, and `CHANGELOG.md`.
4. **No silent fallbacks.** This codebase deliberately fails loudly instead
   of degrading silently (e.g. no dummy-worker fallback in production, no
   empty scope manifest passing the gate). Keep that property.

## Reporting issues

Open a GitHub issue with:
- What you expected vs. what happened
- The `slice doctor` output
- Relevant `slice inspect <slice>` or `slice diagnostics <slice>` output if
  the issue involves a specific run

## Architecture questions

Read [`docs/multi-host-architecture.md`](docs/multi-host-architecture.md) and
[`docs/execution-modes.md`](docs/execution-modes.md) first — both are marked
authoritative/frozen and answer most "why is it built this way" questions.
