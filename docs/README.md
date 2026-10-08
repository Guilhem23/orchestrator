# Documentation

Reference documentation for Slice Orchestrator. Start with the [main
README](../README.md) for installation and a quickstart; come here for
depth.

## Architecture

- [multi-host-architecture.md](multi-host-architecture.md) — how one control plane serves multiple native MCP hosts (Cursor, Claude Code) without duplicated orchestration logic
- [execution-modes.md](execution-modes.md) — native MCP host mode vs. external subprocess worker mode (authoritative spec)
- [subprocess-mode.md](subprocess-mode.md) — Mode B: driving external vendor CLIs (`cursor-agent`, `claude`, `gemini`) as workers
- [mcp-lifecycle-spec.md](mcp-lifecycle-spec.md) — the full slice lifecycle state machine as exposed over MCP

## MCP integration

- [mcp-tool-contract.md](mcp-tool-contract.md) — authoritative host-agnostic tool interface (the 14 `slice_*` tools)
- [mcp-host-compatibility.md](mcp-host-compatibility.md) — capability matrix and live-invocation evidence for each supported host
- [cursor-integration.md](cursor-integration.md) — set up and validate Cursor Chat as a native host
- [claude-code-integration.md](claude-code-integration.md) — set up and validate Claude Code as a native host
- [integration-prompt.md](integration-prompt.md) — copy-paste prompt for registering Slice Orchestrator against a *different* target repository (external checkout, `uv run --project`)

## Observability & measurement

- [observability.md](observability.md) — what the control plane records and why
- [metrics.md](metrics.md) — authoritative metric catalog
- [run-export-format.md](run-export-format.md) — exported run format for external analysis
- [diagnostics.md](diagnostics.md) — commands for inspecting a slice's state and event history
- [dogfood-task-catalog.md](dogfood-task-catalog.md) — the task set used for internal dogfooding
- [productivity-protocol.md](productivity-protocol.md) — measurement protocol for orchestrated vs. manual development
- [productivity-study-results.md](productivity-study-results.md) / [productivity-study-analysis.md](productivity-study-analysis.md) — results of the first study (empirical baseline measurements)

## Project direction & Masterplan

- [strategic-execution-plan.md](strategic-execution-plan.md) — Master architecture, completed v0.5 capabilities, remaining intentions, and 90-day GTM roadmap

## Historical record

- [archive/](archive/) — validation reports, remediation reports, and acceptance reviews from earlier phases of the project. Useful for audit trail and "why was this decision made", not for onboarding.
