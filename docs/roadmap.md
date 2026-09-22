# Orchestrator Roadmap

**Status**: REBASELINED — Multi-host MCP (Cursor primary, Claude Code secondary)
**Date**: 2026-09-11
**Depends on**: [multi-host-architecture.md](multi-host-architecture.md), [execution-modes.md](execution-modes.md)

---

## Priority Order (CURRENT)

```text
A. Cursor-native integration
B. Claude Code native compatibility
C. Cross-host validation
D. Productivity comparison
E. External subprocess workers
```

Native Claude Code support is **not** a separate orchestration architecture. It reuses the same host-agnostic MCP server and control plane.

---

## A. Cursor-native integration

**Status**: VALIDATED (live Cursor Chat + operator cold restart) — production criteria still open

```text
Cursor Chat live invocation: PASS
Full IDE process restart: PASS (operator; slice S940)
Claude Code native validation: PASS (slices S999/S998/S997/S996/S995)
Production readiness: NOT READY
```

Evidence: [archive/CURSOR_CHAT_LIVE_VALIDATION.md](archive/CURSOR_CHAT_LIVE_VALIDATION.md) (slice `S930`);  
[archive/FINAL_CURSOR_RESTART_ACCEPTANCE_REPORT.md](archive/FINAL_CURSOR_RESTART_ACCEPTANCE_REPORT.md) (slice `S940`, full IDE cold restart by operator).

### Deliverables

- [x] Host-agnostic MCP server (`slice_orchestrator/mcp_server.py`)
- [x] Tool layer (`slice_orchestrator/tools.py`) including gate/finalize
- [x] `.cursor/mcp.json`
- [x] [cursor-integration.md](cursor-integration.md)
- [x] RAW_STDIO + IN_PROCESS tests (explicitly classified)
- [x] Live Cursor Chat invocation evidence (discovery → report → persistence) — `S930`
- [x] Full Cursor IDE cold restart recovery evidence — `S940` (operator outside agent)

### Exit criteria

- [x] Tools invocable over stdio without `cursor-agent login`
- [x] Cursor Chat MCP registry shows `slice-orchestrator` with tool calls recorded
- [x] Control-plane authority preserved
- [x] Full Cursor IDE process restart recovery validated (operator attestation + S940)
- [ ] Production operational criteria (Claude Code + stronger productivity evidence)

---

## B. Claude Code native compatibility

**Status**: VALIDATED (live Claude Code tool invocation, full lifecycle to `COMPLETE`)

```text
Claude Code native invocation: PASS
Tool discovery (14 slice_* tools): PASS
Full lifecycle to COMPLETE with real HMAC test receipt: PASS (slice S994, 21 events)
```

Evidence: [archive/CLAUDE_CODE_NATIVE_VALIDATION.md](archive/CLAUDE_CODE_NATIVE_VALIDATION.md) (slices `S999`/`S998`/`S997`/`S996`/`S995`/`S994`, disposable repos).

### Deliverables

- [x] Project `.mcp.json` (stdio, no secrets)
- [x] [claude-code-integration.md](claude-code-integration.md)
- [x] Same tool contract as Cursor
- [x] Live Claude Code `/mcp` + tool invocation evidence — [archive/CLAUDE_CODE_NATIVE_VALIDATION.md](archive/CLAUDE_CODE_NATIVE_VALIDATION.md)

### Exit criteria

- [x] Claude Code lists and connects `slice-orchestrator`
- [x] Disposable slice lifecycle tools succeed from Claude Code
- [x] No duplicated orchestration logic for Claude

### Follow-up (minor DX gap, not a Jalon B blocker, host-independent)

- [ ] `slice_plan`'s MCP tool description doesn't document the expected `scope_manifest.allow_paths` shape and silently ignores unrecognized keys (`allowed_scope`, `files`) instead of validating. Caused a false-positive "hardcoded path" misdiagnosis during this validation before the correct shape was found by reading `tools.py`/`gates.py`. Suggest documenting the shape in the tool description or schema-validating `plan` input.

---

## C. Cross-host validation

**Status**: PARTIAL — automated isolation tests PASS; live dual-host sessions UNVERIFIED

### Deliverables

- [x] [multi-host-architecture.md](multi-host-architecture.md)
- [x] [mcp-host-compatibility.md](mcp-host-compatibility.md)
- [x] `tests/test_mcp_cross_host_isolation.py`
- [x] [archive/MULTI_HOST_MCP_VALIDATION_REPORT.md](archive/MULTI_HOST_MCP_VALIDATION_REPORT.md)
- [ ] Concurrent live Cursor + Claude Code session evidence

### Exit criteria

- [x] Shared project-local state model
- [x] Host metadata cannot bypass authority
- [x] Assignment single-use across host labels
- [ ] Live dual-host persistence after restart of each client

---

## D. Productivity comparison

**Status**: STUDY EXECUTED — no productivity speedup claim authorized

Observability layer, metrics engine, export, and `slice compare` are implemented. Multi-task dogfood study results: [productivity-study-results.md](productivity-study-results.md), [productivity-study-analysis.md](productivity-study-analysis.md). Conclusion: observed process/recovery trade-offs; **INSUFFICIENT EVIDENCE** for net human productivity improvement.

### Deliverables

- [x] Observability model + diagnostic CLI
- [x] Metrics with provenance
- [x] Run export + comparison format
- [x] Dogfood task catalog
- [x] Multi-task manual vs orchestrated study executed


---

## E. External subprocess workers

**Status**: EXISTING / HARDEN

Mode B remains for CI/headless:

- Cursor CLI / `cursor-agent`
- Claude CLI
- Gemini CLI
- Dummy / local workers

Roadmap items: authentication for real vendor CLIs, CI packaging, and productivity comparison against native hosts. Native hosts must never be implemented by wrapping these CLIs.

---

## Explicit non-goals

- Separate control planes per host
- Client-specific gate/policy forks
- Treating stdio protocol tests as Cursor or Claude Code validation
- Requiring `cursor-agent login` for Cursor Chat native mode
