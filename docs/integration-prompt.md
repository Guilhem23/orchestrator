# Integration Prompt — Bringing Slice Orchestrator into Another Repository

Copy the block below into a chat session (Claude Code or Cursor Chat) opened
in the **target repository** you want to govern with Slice Orchestrator.
Fill in `<ORCHESTRATOR_PATH>` first.

This assumes Slice Orchestrator is a local checkout (not yet published as a
package registry dependency — see [roadmap.md](roadmap.md)). Once it ships
as an installable package, step 1 below simplifies to a normal dependency
add and this doc should be updated accordingly.

---

```
Set up Slice Orchestrator as an MCP server for this repository.

Slice Orchestrator lives at <ORCHESTRATOR_PATH> (a separate git checkout,
not a dependency of this project). Do the following:

1. Confirm <ORCHESTRATOR_PATH> exists, contains slice_orchestrator/, and
   `uv run --project <ORCHESTRATOR_PATH> python3 -m slice_orchestrator.mcp_server --help`
   (or equivalent) starts without import errors.

2. Create a project-scoped `.mcp.json` in this repository's root:

   {
     "mcpServers": {
       "slice-orchestrator": {
         "type": "stdio",
         "command": "uv",
         "args": [
           "run", "--project", "<ORCHESTRATOR_PATH>",
           "python3", "-m", "slice_orchestrator.mcp_server"
         ],
         "env": { "PYTHONUNBUFFERED": "1" }
       }
     }
   }

   Use an absolute path for <ORCHESTRATOR_PATH>. Do not put secrets in this
   file — there are none to put.

3. Add `.orchestrator_slice/` to this repository's `.gitignore` if not
   already present (that's where per-project run state — SQLite event
   store, HMAC secret, locks — will be created; it must never be committed).

4. Tell me which MCP host you're validating from (Claude Code or Cursor
   Chat) and confirm the tool discovery step from that host's guide in
   the orchestrator repo (docs/claude-code-integration.md or
   docs/cursor-integration.md) — specifically the "connected" check and the
   `slice_*` tool count.

5. Run a disposable validation slice against THIS repository, not the
   orchestrator's own repo:
   - slice_start (repo_dir = this repo's absolute path if the host's
     CLAUDE_PROJECT_DIR/CURSOR_PROJECT_DIR isn't already this repo)
   - slice_context
   - slice_status
   Confirm state lands under this repo's .orchestrator_slice/, not under
   <ORCHESTRATOR_PATH>/.orchestrator_slice/.

6. Report: did each step work as documented, or did something require an
   undocumented workaround? That gap is itself the useful finding — tell
   me exactly what diverged from docs/claude-code-integration.md or
   docs/cursor-integration.md so those docs can be corrected.

Do not commit anything in this repository as part of this setup beyond
.mcp.json and the .gitignore entry, and only after I confirm.
```
