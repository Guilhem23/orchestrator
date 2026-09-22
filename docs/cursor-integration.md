# Cursor Native Integration Guide

**Status**: USER & DEVELOPER GUIDE — Cursor Chat primary host
**Date**: 2026-09-11
**Version**: 2.0.0
**Architecture**: [multi-host-architecture.md](multi-host-architecture.md)

---

## 1. Role

Cursor Chat is the **primary native MCP host** for the Slice Orchestrator.

- Cursor Chat invokes the MCP server over stdio.
- Cursor Chat does **not** require `cursor-agent login` for this mode.
- `cursor-agent` / Cursor CLI remains a separate **external subprocess worker** (Mode B).

---

## 2. Exact Cursor Configuration

Project-scoped file: `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "slice-orchestrator": {
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

### Checklist

| Check | Expected |
|---|---|
| Command | `uv` on PATH |
| Args | `run python3 -m slice_orchestrator.mcp_server` |
| Working directory | Cursor workspace root (project checkout) |
| Environment | `PYTHONUNBUFFERED=1` only; no secrets |
| Absolute developer paths | Avoided |
| Fresh checkout | `uv sync` then reopen Cursor / reload MCP |
| Outside repository | Tools that omit `repo_dir` resolve via cwd / env; prefer opening the project root |

Alternative entrypoint after install:

```bash
uv run slice-mcp
```

---

## 3. Setup Steps

```bash
uv sync
```

1. Confirm `.cursor/mcp.json` exists at the project root.
2. Open the project in Cursor Desktop.
3. Reload MCP servers (or restart Cursor).
4. Confirm `slice-orchestrator` appears in Cursor MCP settings with tools visible.
5. In Chat, ask to start a disposable slice (e.g. `S101`).

Presence of `.cursor/mcp.json` alone does **not** prove Cursor invocation.

---

## 4. Lifecycle in Cursor Chat

```text
slice_start → slice_context → slice_grill → slice_plan → slice_work_list
→ slice_dispatch → (Cursor edits) → slice_record_result → slice_run_tests
→ slice_request_review → slice_record_result → slice_gate → slice_finalize
→ slice_report
```

Optional: pass `host="cursor"` on mutating tools for observational metadata only.

---

## 5. Persistence

State persists under `.orchestrator_slice/`. After restarting Cursor, call `slice_status` / `slice_report` with the same slice id to resume. Chat history is not authoritative.

---

## 6. Validation Evidence Required for PASS

Independently verifiable:

- MCP server listed in Cursor’s live registry for this workspace
- Tool call timestamps / transcripts
- Persisted events with run and slice IDs
- Generated state under `.orchestrator_slice/`

If those are missing, status must remain:

```text
CURSOR CHAT INVOCATION: UNVERIFIED
```
