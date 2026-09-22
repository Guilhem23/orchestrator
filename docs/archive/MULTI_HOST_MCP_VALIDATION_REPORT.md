# Multi-Host MCP Validation Report

**Date**: 2026-09-11
**Branch**: `feature/mcp-composition-security-remediation`
**Validation timestamp (UTC)**: `2026-09-11T12:10:08Z`
**Method**: Audit existing implementation; host-agnostic remediation; automated protocol/isolation tests; honest live-client evidence check. Uncommitted work preserved; no commit performed.

---

## 1. Architectural Decision

Confirmed and documented in [multi-host-architecture.md](../multi-host-architecture.md):

```text
PRIMARY HOST:           Cursor Chat
SECONDARY HOST:         Claude Code
COMMON INTERFACE:       stdio MCP server
COMMON AUTHORITY:       Slice Orchestrator Control Plane
```

Native hosts share one server and one control plane. Cursor CLI and Claude CLI remain external subprocess workers and are not used by native MCP mode.

---

## 2. Host-Agnostic MCP Contract

| Item | Status | Evidence |
|---|---|---|
| Identical tool surface for all hosts | PASS | 13 tools in `mcp_server.py`; stdio `tools/list` |
| Optional `host` metadata only | PASS | `tools._normalize_host_metadata`; never used for auth |
| Uniform principal `mcp-host` | PASS | Replaced prior hard-coded `cursor-native` |
| Path env resolution | PASS | `CLAUDE_PROJECT_DIR` / `SLICE_REPO_DIR` / cwd |
| No control-plane fork per client | PASS | Single `tools.py` + control plane |

Core + lifecycle tools:

```text
slice_start, slice_context, slice_grill, slice_plan, slice_work_list,
slice_dispatch, slice_record_result, slice_run_tests, slice_status, slice_report,
slice_request_review, slice_gate, slice_finalize
```

---

## 3. Cursor Configuration

| Check | Result |
|---|---|
| `.cursor/mcp.json` present | Yes |
| Command | `uv run python3 -m slice_orchestrator.mcp_server` |
| Secrets in config | None |
| Absolute developer paths | None |
| Fresh-checkout dependency | Requires `uv` + `uv sync` |
| Live Cursor registry entry | **Absent** — `~/.cursor/projects/.../mcps/` has browser/atlassian/gitlab only; no `slice-orchestrator` |
| Dynamic tool catalog `slice\|orchestrat` | **Zero matches** in this session |

Configuration is correct on disk. Configuration ≠ invocation.

---

## 4. Claude Code Configuration

| Check | Result |
|---|---|
| Project `.mcp.json` present | Yes (`type: stdio`, same command) |
| Secrets | None |
| Format vs Claude Code docs | Matches documented project-scope stdio shape |
| `claude` CLI available | **No** (`claude not found`) |
| `claude mcp add/list` executed | **Not possible** in this environment |
| Live Claude Code `/mcp` | **UNVERIFIED** |

---

## 5. Protocol-Level Tests

| Class | File | Result |
|---|---|---|
| `IN_PROCESS_MCP_TEST` | `tests/test_mcp_server_protocol.py` | PASS (3) |
| `RAW_STDIO_PROTOCOL_TEST` | `tests/test_mcp_stdio_protocol.py` | PASS (4) |
| Cross-host isolation | `tests/test_mcp_cross_host_isolation.py` | PASS (5) |
| Tool unit/lifecycle | `tests/test_mcp_tools.py` | PASS (7) |

**19/19 MCP-focused tests PASS** at `2026-09-11T12:10:08Z`.

RAW_STDIO coverage includes handshake, tool discovery, unknown tools, malformed JSON survival, restart persistence, and complete lifecycle through `slice_finalize` → `COMPLETE`.

In-process tests are **not** labeled as stdio/ClientSession/client invocation.

---

## 6. Cursor Chat Validation

```text
CURSOR CHAT INVOCATION: UNVERIFIED
```

| Capability | Status | Evidence |
|---|---|---|
| MCP server discovery | UNVERIFIED | Config exists; Cursor live registry lacks server |
| Tool discovery | UNVERIFIED | No Cursor tool catalog entries |
| Slice start → report | UNVERIFIED | No Cursor-originated events |
| Persistence after Cursor restart | UNVERIFIED | No Cursor session evidence |

---

## 7. Claude Code Validation

```text
CLAUDE CODE INVOCATION: UNVERIFIED
```

| Capability | Status | Evidence |
|---|---|---|
| MCP registration / `/mcp` | UNVERIFIED | `claude` CLI not installed |
| Tool discovery | UNVERIFIED | — |
| Slice start → report | UNVERIFIED | — |
| Persistence after restart | UNVERIFIED | — |

Generic stdio tests are **not** counted as Claude Code validation.

---

## 8. Complete Lifecycle

| Item | Status | Evidence |
|---|---|---|
| MCP-only path to `COMPLETE` | PASS | `slice_gate` + `slice_finalize` exist; stdio lifecycle test |
| No required `controller.step()` | PASS | Spec + stdio test |
| Terminal state explicit | PASS | `COMPLETE` after finalize |

---

## 9. Cross-Host Isolation

| Check | Status | Evidence |
|---|---|---|
| Shared project-local state | PASS | `test_shared_state_across_host_metadata` |
| Host cannot impersonate for privilege | PASS | Finalize rejected in PLANNING regardless of host label |
| Host identity does not bypass authority | PASS | Same |
| Assignment single-use across hosts | PASS | Replay under `claude-code` after `cursor` consume rejected |
| Terminal immutability | PASS | Plan after COMPLETE rejected |
| `CLAUDE_PROJECT_DIR` resolution | PASS | Env preferred over cwd |
| Concurrent live dual-host sessions | UNVERIFIED | No live clients |

---

## 10. Persistence and Resume

| Check | Status | Evidence |
|---|---|---|
| Stdio server restart restores state | PASS | `test_stdio_protocol_restart_and_persistence` |
| Cursor restart resume | UNVERIFIED | No Cursor evidence |
| Claude Code restart resume | UNVERIFIED | No Claude Code evidence |

---

## 11. Remaining Limitations

1. Live Cursor Chat invocation not demonstrated in this environment.
2. Claude Code / `claude` CLI unavailable here — project config prepared but unexecuted.
3. Cursor MCP auto-discovery may require manual reload; registry still missing server.
4. Productivity comparison (roadmap D) not started.
5. Prior hard-coded `cursor-native` principal removed; historical docs may still say “Cursor-native” for Mode A branding — architecture now multi-host.

---

## 12. Final Verdict

### Capability table

| Capability | Cursor Chat | Claude Code | Evidence | Status |
|---|---|---|---|---|
| MCP server discovery | Config only | Config only | `.cursor/mcp.json`, `.mcp.json`; no live registry | UNVERIFIED (clients) / PASS (config) |
| Tool discovery | UNVERIFIED | UNVERIFIED | stdio list PASS | PARTIAL |
| Slice start | UNVERIFIED | UNVERIFIED | tools + stdio PASS | PARTIAL |
| Context retrieval | UNVERIFIED | UNVERIFIED | tools + stdio PASS | PARTIAL |
| Planning | UNVERIFIED | UNVERIFIED | tools + stdio PASS | PARTIAL |
| Work-item management | UNVERIFIED | UNVERIFIED | tools PASS | PARTIAL |
| Result recording | UNVERIFIED | UNVERIFIED | tools + isolation PASS | PARTIAL |
| Independent tests | UNVERIFIED | UNVERIFIED | tools + stdio PASS | PARTIAL |
| Gate/finalization | UNVERIFIED | UNVERIFIED | tools + stdio PASS | PARTIAL |
| Persistence | UNVERIFIED (clients) | UNVERIFIED (clients) | stdio restart PASS | PARTIAL |
| Final report | UNVERIFIED | UNVERIFIED | tools + stdio PASS | PARTIAL |

### Verdict lines

```text
MCP SERVER:                 PASS
CURSOR NATIVE MODE:         UNVERIFIED
CLAUDE CODE NATIVE MODE:    UNVERIFIED
COMMON CONTROL PLANE:       PASS
STDIO PROTOCOL:             PASS
COMPLETE LIFECYCLE:         PASS
CROSS-HOST ISOLATION:       PARTIAL
CURSOR PRODUCTIVITY:        UNVERIFIED
CLAUDE CODE PRODUCTIVITY:   UNVERIFIED
PRODUCTION READINESS:       NOT READY
```

### Rationale

- **PASS** for server, control plane, stdio protocol, and MCP-complete lifecycle: independently reproduced with process-level and tool-level tests.
- **UNVERIFIED** for both native modes: no actual Cursor Chat or Claude Code tool-call evidence.
- **PARTIAL** for cross-host isolation: automated shared-state/authority tests pass; live dual-host validation missing.
- **NOT READY** for production until at least one live native host (priority: Cursor Chat) is evidenced end-to-end.
