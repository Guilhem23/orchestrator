# Archive — Historical Reports Kept for Reference

This folder holds validation and remediation reports kept because either an
active doc still cites them as evidence, or they explain a security/design
decision — or the project's founding motivation — that is still in effect
today. Everything else from the project's earlier validation history was
removed as part of the pre-public cleanup; see `git log` for the full record
if you need it.

If you're new to the project, start with the [main README](../../README.md)
and [docs/](../) instead.

A few kept files link to companion reports (e.g. restart-track intermediate
reports, `MULTI_HOST_MCP_ARCHITECTURE.md`) that were removed in this cleanup
or renamed when `docs/` was created. Those links were fixed where the target
still exists under a new name; where the companion file was removed
entirely, the link is left as a historical pointer and won't resolve — the
file's own content is unaffected.

## Kept — cited as evidence from active docs

- [CURSOR_CHAT_LIVE_VALIDATION.md](CURSOR_CHAT_LIVE_VALIDATION.md) — the `S930` live-invocation proof for Cursor Chat, cited from `docs/roadmap.md` and `docs/mcp-host-compatibility.md`.
- [FINAL_CURSOR_RESTART_ACCEPTANCE_REPORT.md](FINAL_CURSOR_RESTART_ACCEPTANCE_REPORT.md) — the `S940` full-IDE-cold-restart recovery proof, cited from `docs/roadmap.md`. Its evidence table links to the raw logs under `evidence/cursor-full-restart-validation/`, which are kept for that reason.
- [MULTI_HOST_MCP_VALIDATION_REPORT.md](MULTI_HOST_MCP_VALIDATION_REPORT.md) — cited from `docs/roadmap.md` (item C, cross-host validation) as the sole active evidence for that item.
- [CLAUDE_CODE_NATIVE_VALIDATION.md](CLAUDE_CODE_NATIVE_VALIDATION.md) — the `S994` full-lifecycle-to-`COMPLETE` proof for Claude Code, cited from `docs/roadmap.md`, `docs/mcp-host-compatibility.md`, and `docs/productivity-study-analysis.md`.

## Kept — explains a still-active design/security decision

- [COMPOSITION_SECURITY_REMEDIATION.md](COMPOSITION_SECURITY_REMEDIATION.md) — documents the threat model behind the test-tampering and self-approval guards enforced by `slice_gate`/`slice_run_tests` today (an agent modifying/deleting authoritative tests, then self-approving as reviewer). These exact guards were independently re-triggered during the Claude Code validation above — the rationale here is still the reason they exist.
- [DOGFOOD_IMPLEMENTATION_REVIEW.md](DOGFOOD_IMPLEMENTATION_REVIEW.md) — founding review (2026-09-09) that found the project was narrative simulation rather than a real runtime, and motivated integrating the actual implementation. This is the origin of the project's core value proposition — event-sourced, independently-verified evidence instead of self-reported claims — and isn't superseded by anything else in this repo.
