# Changelog

High-level milestones. For the full detail behind any entry, see
[`docs/roadmap.md`](docs/roadmap.md) and the write-ups in
[`docs/archive/`](docs/archive/).

## Unreleased

- Repository cleanup for public release: root reduced to `README.md` +
  `LICENSE` + `CONTRIBUTING.md` + `CHANGELOG.md`; reference docs moved to
  `docs/`, historical validation/remediation reports moved to
  `docs/archive/`.
- Fixed a DX gap in `slice_plan`: the tool now documents the expected
  `scope_manifest.allow_paths` shape and returns a warning when the
  effective scope ends up empty, instead of silently rejecting later at
  `slice_gate` with no clear cause.

## Claude Code native compatibility validated

- Full slice lifecycle (`start` → `plan` → `dispatch` → `record_result` →
  `run_tests` → `request_review` → `gate` → `finalize`) executed live from
  Claude Code and reached `COMPLETE` with a real HMAC test receipt, at
  event-for-event parity with the Cursor Chat validation.
- See [`docs/archive/CLAUDE_CODE_NATIVE_VALIDATION.md`](docs/archive/CLAUDE_CODE_NATIVE_VALIDATION.md).

## Observability, governance profiles, and productivity study

- Added run diagnostics, timelines, metrics with provenance, and a
  reproducible run export format.
- Added a fast-track adaptive governance profile.
- Ran a paired agent-vs-agent productivity study across 10 dogfood tasks;
  concluded **insufficient evidence** for a human productivity claim (see
  [`docs/productivity-study-analysis.md`](docs/productivity-study-analysis.md)).

## Multi-host MCP support

- Extended the native-host model beyond Cursor Chat to a shared,
  host-agnostic control plane, with cross-host isolation tests and a
  composition security remediation for test provenance.

## Cursor Chat native integration validated

- Implemented Cursor Chat as a native MCP host sharing the same control
  plane and tool contract as the CLI.
- Validated live tool invocation end-to-end (`S930`) and a full IDE cold
  restart with state recovery (`S940`).

## Initial runtime integration

- Integrated the Slice Orchestrator runtime (event-sourced state machine,
  cryptographic event chaining, atomic locks, worker adapters, CLI, git
  integration, policy-based governance) from a historical design bundle
  into a real, executable implementation.
- Fixed two critical issues found during integration: a silent
  dummy-worker fallback in production code paths, and non-atomic file
  locks.
