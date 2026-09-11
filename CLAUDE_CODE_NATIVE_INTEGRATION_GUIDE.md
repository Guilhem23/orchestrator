# Claude Code Native Integration Guide

**Status**: USER & DEVELOPER GUIDE — Claude Code secondary host
**Date**: 2026-09-11
**Version**: 1.0.0
**Architecture**: [MULTI_HOST_MCP_ARCHITECTURE.md](MULTI_HOST_MCP_ARCHITECTURE.md)

---

## 1. Role

Claude Code is a **secondary compatible native MCP host**.

- Uses the **same** stdio MCP server and tool contracts as Cursor Chat.
- Does **not** require separate `claude` CLI authentication beyond Claude Code’s normal auth.
- Must **not** launch `claude` as an external subprocess worker for native mode.
- Claude CLI remains a Mode B external worker adapter.

---

## 2. Project Configuration

Preferred project-scoped file: `.mcp.json` (committed, no secrets):

```json
{
  "mcpServers": {
    "slice-orchestrator": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "python3",
        "-m",
        "slice_orchestrator.mcp_server"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

Equivalent CLI registration (when `claude` CLI is installed):

```bash
claude mcp add --scope project slice-orchestrator -- \
  uv run python3 -m slice_orchestrator.mcp_server
```

Verify against the installed Claude Code version:

```bash
claude --version
claude mcp list
claude mcp get slice-orchestrator
```

> Note: In this workspace at validation time, the `claude` CLI was **not installed**, so the exact CLI subcommand behavior could not be executed here. The `.mcp.json` format follows the official Claude Code MCP documentation (`type: stdio`, project scope, `CLAUDE_PROJECT_DIR` injection).

---

## 3. Runtime Behavior Checklist

| Topic | Expected |
|---|---|
| Server name | `slice-orchestrator` |
| Transport | stdio |
| Command | `uv` + `run python3 -m slice_orchestrator.mcp_server` |
| Project root | Claude injects `CLAUDE_PROJECT_DIR` into the server env |
| Path resolution | tools prefer `CLAUDE_PROJECT_DIR` when `repo_dir` omitted |
| Environment isolation | No secrets in `.mcp.json` |
| Workspace trust | First interactive use requires project MCP approval |
| Clean checkout | `uv sync`; approve project MCP when prompted |
| `uv` unavailable | Server fails to start; install `uv` or adjust command to a venv python |
| Other working directory | Prefer launching Claude Code from the project root |

---

## 4. Validation Steps (when Claude Code is available)

1. Open the project in Claude Code.
2. Approve the project MCP server when prompted.
3. Run `/mcp` and confirm `slice-orchestrator` is connected.
4. Confirm tool discovery lists the 13 `slice_*` tools.
5. Execute: `slice_start`, `slice_context`, `slice_plan`, `slice_work_list`, `slice_status`, `slice_report` on a disposable slice.
6. Restart Claude Code and confirm persistence via `slice_status`.

Optional: pass `host="claude-code"` on mutating tools for metadata only.

---

## 5. What is NOT validation

- Generic `RAW_STDIO_PROTOCOL_TEST` subprocess clients
- In-process FastMCP tests
- Cursor Chat sessions
- Dummy workers

If Claude Code is unavailable, unauthenticated, or cannot load the server:

```text
CLAUDE CODE INVOCATION: UNVERIFIED
```
