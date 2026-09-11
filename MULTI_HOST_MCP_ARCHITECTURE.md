# Multi-Host MCP Architecture

**Status**: FROZEN — Authoritative multi-host architecture
**Date**: 2026-09-11
**Depends on**: [EXECUTION_MODES_ARCHITECTURE.md](EXECUTION_MODES_ARCHITECTURE.md), [MCP_COMPLETE_LIFECYCLE_SPEC.md](MCP_COMPLETE_LIFECYCLE_SPEC.md)

---

## 1. Architectural Decision

The Slice Orchestrator MCP layer is **host-agnostic**. Cursor Chat and Claude Code are both native MCP hosts for the same server and the same control plane.

```text
PRIMARY HOST:
Cursor Chat

SECONDARY COMPATIBLE HOST:
Claude Code

COMMON INTERFACE:
MCP server (stdio)

COMMON AUTHORITY:
Slice Orchestrator Control Plane
```

```text
Cursor Chat ─┐
             ├── stdio MCP server ── Slice Orchestrator Control Plane
Claude Code ─┘
```

### What remains distinct

| Role | Component | Nature |
|---|---|---|
| Native MCP host | Cursor Chat | Primary human-facing IDE host |
| Native MCP host | Claude Code | Secondary compatible host |
| External subprocess worker | Cursor CLI (`cursor-agent`) | Mode B worker |
| External subprocess worker | Claude CLI (`claude`) | Mode B worker |
| External subprocess worker | Gemini CLI | Mode B worker |
| Authority | Control Plane | Shared by all modes and hosts |

Native host integrations **must not** launch `cursor-agent` or `claude` as a second worker process.

> Cursor Chat and Claude Code are native MCP hosts for the Slice Orchestrator. Cursor CLI and Claude CLI are external subprocess workers. Native host integrations share one host-agnostic MCP server and one authoritative control plane, while client configuration and invocation evidence are validated independently.

---

## 2. Host-Agnostic MCP Contract

### 2.1 Tool inventory (identical for every host)

| Tool | Mutates | State impact |
|---|---|---|
| `slice_start` | ✅ | → PLANNING (or resume) |
| `slice_context` | ✗ | none |
| `slice_grill` | optional clarification record | none required |
| `slice_plan` | ✅ | → PLAN_READY |
| `slice_work_list` | ✅ (create/update) | none |
| `slice_dispatch` | ✅ | role-specific assigned state |
| `slice_record_result` | ✅ | role-specific ready/approved/blocked |
| `slice_run_tests` | ✅ | HMAC receipt persisted |
| `slice_status` | ✗ | none |
| `slice_report` | ✗ | none |
| `slice_request_review` | ✅ | → ADVERSARIAL_REVIEW |
| `slice_gate` | ✗ | evaluates commit gate |
| `slice_finalize` | ✅ | COMMIT_READY → COMPLETE |

Schemas, errors, transitions, and persistence behavior are defined in [CURSOR_MCP_TOOL_CONTRACT.md](CURSOR_MCP_TOOL_CONTRACT.md) and [MCP_COMPLETE_LIFECYCLE_SPEC.md](MCP_COMPLETE_LIFECYCLE_SPEC.md). The contract is host-independent; the Cursor-named file remains the canonical schema document for historical continuity.

### 2.2 Host metadata rules

- Optional tool argument: `host` (`cursor` | `claude-code` | `test` | `unknown`).
- Recorded only as `host_metadata` in responses/event payloads when provided.
- **Never** used for authorization, gate bypass, assignment privilege, or policy mutation.
- Uniform MCP principal: `mcp-host`. Operator/system events use `operator-local`.

### 2.3 Path resolution (host-independent)

When `repo_dir` is omitted, the tool layer resolves the repository root in order:

1. `SLICE_REPO_DIR`
2. `CLAUDE_PROJECT_DIR` (injected by Claude Code for stdio MCP)
3. `CURSOR_PROJECT_DIR` (if present)
4. `Path.cwd()`

Control state lives under `<repo>/.orchestrator_slice/` for all hosts.

### 2.4 Authority invariants (unchanged across hosts)

- Single-use assignments
- Fail-closed transitions
- Independent control tests with HMAC receipts
- Reviewer independence checks
- Terminal states immutable
- Client configuration cannot modify control-plane policy

---

## 3. Client Configuration Separation

| Host | Config file | Transport | Secrets allowed |
|---|---|---|---|
| Cursor Chat | `.cursor/mcp.json` | stdio | **No** |
| Claude Code | `.mcp.json` (project scope) | stdio | **No** |

Both configs invoke the same module:

```text
uv run python3 -m slice_orchestrator.mcp_server
```

Entrypoint alias: `slice-mcp` (from `pyproject.toml`).

---

## 4. Evidence Classification

| Class | Meaning | Proves client integration? |
|---|---|---|
| `IN_PROCESS_MCP_TEST` | Direct Python `mcp.list_tools` / `mcp.call_tool` | No |
| `RAW_STDIO_PROTOCOL_TEST` | Real server process over stdin/stdout JSON-RPC | No (protocol only) |
| `CURSOR_CHAT_INVOCATION` | Actual Cursor Chat tool calls with persisted evidence | Yes (Cursor) |
| `CLAUDE_CODE_INVOCATION` | Actual Claude Code tool calls with persisted evidence | Yes (Claude Code) |

Dummy workers, in-process tests, and generic stdio clients are **not** native host validation.

---

## 5. Complete MCP Lifecycle

```text
slice_start
→ slice_context
→ slice_grill
→ slice_plan
→ slice_work_list
→ slice_dispatch
→ slice_record_result
→ slice_run_tests
→ slice_request_review
→ slice_record_result
→ slice_gate
→ slice_finalize
→ slice_report
```

No `controller.step()` or other direct Python control-plane calls are required to reach terminal `COMPLETE`.

---

## 6. Security Boundary

```text
Host config (Cursor / Claude Code)
        │  registers transport + command only
        ▼
MCP stdio server
        │  host-agnostic tool surface
        ▼
tools.py
        │  no duplicated orchestration policy
        ▼
Control Plane (gates, events, HMAC, assignments)
```

Client configuration cannot alter policy bundles, gate rules, or secrets. Secrets must never appear in MCP config, logs, reports, or test artifacts.
