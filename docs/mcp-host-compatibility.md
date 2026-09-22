# MCP Host Compatibility Matrix

**Date**: 2026-09-11
**Architecture**: [multi-host-architecture.md](multi-host-architecture.md)

---

## 1. Host vs Worker Distinction

| Component | Class | Uses MCP server? | Spawns vendor CLI worker? |
|---|---|---|---|
| Cursor Chat | Primary native MCP host | Yes | No |
| Claude Code | Secondary native MCP host | Yes | No |
| Cursor CLI (`cursor-agent`) | External subprocess worker | No | N/A (is the worker) |
| Claude CLI (`claude`) | External subprocess worker | No | N/A (is the worker) |
| Gemini CLI | External subprocess worker | No | N/A (is the worker) |

---

## 2. Capability Matrix

| Capability | Cursor Chat | Claude Code | Shared control plane | Notes |
|---|---|---|---|---|
| MCP server discovery | Configured (`.cursor/mcp.json`) | Configured (`.mcp.json`) | Yes | Client load UNVERIFIED without live host |
| Tool discovery (13 tools) | Same contract | Same contract | Yes | Proven via RAW_STDIO + IN_PROCESS |
| `slice_start` | Supported | Supported | Yes | |
| `slice_context` | Supported | Supported | Yes | |
| `slice_grill` | Supported | Supported | Yes | |
| `slice_plan` | Supported | Supported | Yes | |
| `slice_work_list` | Supported | Supported | Yes | |
| `slice_dispatch` | Supported | Supported | Yes | |
| `slice_record_result` | Supported | Supported | Yes | Single-use assignments |
| `slice_run_tests` | Supported | Supported | Yes | Independent HMAC receipts |
| `slice_status` | Supported | Supported | Yes | `execution_mode=mcp-native` |
| `slice_report` | Supported | Supported | Yes | |
| `slice_request_review` | Supported | Supported | Yes | |
| `slice_gate` | Supported | Supported | Yes | |
| `slice_finalize` | Supported | Supported | Yes | Terminal COMPLETE |
| Host metadata | Optional `host=cursor` | Optional `host=claude-code` | Observational only | Never grants authority |
| Shared project state | `.orchestrator_slice/` | `.orchestrator_slice/` | Yes | Cross-host tests PASS |
| Requires `cursor-agent login` | **No** | N/A | — | |
| Requires extra `claude` CLI auth | N/A | **No** (beyond Claude Code normal auth) | — | |
| Live client invocation evidence | **PASS** (`S930`, `S940`) | **PASS** (`S999`–`S994`, full lifecycle to `COMPLETE` on `S994`) | — | See validation reports |

---

## 3. Configuration Comparison

| Item | Cursor Chat | Claude Code |
|---|---|---|
| Config path | `.cursor/mcp.json` | `.mcp.json` |
| Transport field | implied stdio | `"type": "stdio"` |
| Command | `uv` | `uv` |
| Module | `slice_orchestrator.mcp_server` | identical |
| Project dir env | cwd / optional `CURSOR_PROJECT_DIR` | `CLAUDE_PROJECT_DIR` injected |
| Secrets in config | Forbidden | Forbidden |

---

## 4. Test Evidence Classes

| Evidence class | Cursor Chat | Claude Code | Protocol |
|---|---|---|---|
| IN_PROCESS_MCP_TEST | Not client proof | Not client proof | PASS |
| RAW_STDIO_PROTOCOL_TEST | Not client proof | Not client proof | PASS |
| Cross-host isolation (tools) | Shared | Shared | PASS |
| CURSOR_CHAT_INVOCATION | PASS — [archive/CURSOR_CHAT_LIVE_VALIDATION.md](archive/CURSOR_CHAT_LIVE_VALIDATION.md) | — | — |
| CLAUDE_CODE_INVOCATION | — | PASS — [archive/CLAUDE_CODE_NATIVE_VALIDATION.md](archive/CLAUDE_CODE_NATIVE_VALIDATION.md) | — |

Both hosts reached `slice_finalize` → `COMPLETE` with a real HMAC test receipt in their respective validations (`S930` for Cursor, `S994` for Claude Code). A minor DX gap was found during the Claude Code validation: `slice_plan` doesn't document or validate the expected `scope_manifest.allow_paths` shape, so a caller passing an unrecognized key (`allowed_scope`, `files`) gets an empty effective scope and a confusing `slice_gate` rejection instead of a clear error. Tracked as a follow-up in [roadmap.md](roadmap.md).
