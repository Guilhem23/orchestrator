# Slice Orchestrator

**A deterministic control plane for AI coding agents.** Slice Orchestrator
sits between your AI assistant (Cursor, Claude Code) and your repository,
enforcing a governed lifecycle — plan → implement → test → review → commit —
with cryptographic event logging, single-use assignments, and a scope
manifest that decides which files an agent is actually allowed to touch.

If you've ever had an agent silently expand scope, skip tests, or claim
success without proof, this is the missing layer: every state transition is
event-sourced and hash-chained, every test run produces an HMAC receipt, and
the commit gate mechanically checks the diff against an approved plan before
anything lands.

## Why

Coding agents are good at writing code and bad at knowing when to stop, what
they're allowed to change, and whether their own tests actually ran. Slice
Orchestrator doesn't replace the agent — it wraps a **slice** (one unit of
governed work) in a state machine the agent must satisfy:

```
PLANNING → ARCHITECTURE_REVIEW → IMPLEMENTATION → ADVERSARIAL_REVIEW
         → COMMIT_READY → GATE → COMPLETE
```

- **Scope manifest** — the approved plan declares exactly which paths may be
  added/modified/deleted; anything else is rejected at the commit gate.
- **Authoritative test receipts** — tests run through the control plane, not
  self-reported by the agent, and are bound to an HMAC receipt.
- **Test-tampering guards** — modifying or deleting a baseline test file
  without plan re-approval is rejected outright.
- **Event-sourced, hash-chained state** — every transition is an append-only,
  cryptographically chained event; state survives IDE restarts and crashes.
- **Host-agnostic** — one control plane, exposed as MCP tools, used
  identically by Cursor Chat and Claude Code (see
  [docs/mcp-host-compatibility.md](docs/mcp-host-compatibility.md)).

## Quickstart

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
git clone <this-repo>
cd orchestrator
uv sync --extra test
```

Check your environment is wired correctly:

```bash
uv run slice doctor
```

```
=== slice doctor ===
Status: ok
[PASS] package_installation: import slice_orchestrator
[PASS] git_repository: repo has .git
[PASS] event_chain_integrity: 2 events verified
[PASS] mcp_configuration: cursor=True project=True
...
Summary: 19/19 passed (0 errors, 0 warnings)
```

Start a slice against any git repository:

```bash
uv run slice --repo-dir /path/to/your/repo plan S1
```

```
Slice S1 initialized in state PLANNING [Profile: standard] (Run ID: 35a5c7f8-...)
```

```bash
uv run slice --repo-dir /path/to/your/repo status S1
```

```
Slice:             S1
State:             PLANNING
Generation:        1
Sequence:          3
```

Run the test suite (240 tests):

```bash
uv run python3 -m pytest tests/ -q
```

## Using it from an AI coding assistant

Slice Orchestrator exposes the same 14 `slice_*` tools over MCP to any
compatible host. A project-scoped `.mcp.json` is already committed here.

- **Cursor Chat** → [docs/cursor-integration.md](docs/cursor-integration.md)
- **Claude Code** → [docs/claude-code-integration.md](docs/claude-code-integration.md)

Both hosts share one project-local state store (`.orchestrator_slice/`); a
run started from one host can be inspected or resumed from the other. See
[docs/multi-host-architecture.md](docs/multi-host-architecture.md) for how
that works, and [docs/mcp-host-compatibility.md](docs/mcp-host-compatibility.md)
for live-invocation evidence on each host.

## CLI reference

```
slice plan <slice>          Initialize or plan a slice
slice status <slice>        Show current status
slice run <slice>           Autonomously drive slice to completion
slice inspect <slice>       Inspect event stream
slice explain <slice>       Explain current state, blockers, next action
slice pause / resume / stop / recover <slice>
slice work list|inspect|retry
slice explore               Launch exploration mode in isolated scratch space
slice doctor                Check installation, trust, and runtime health
slice diagnostics <slice>   Show blockers, pending work, evidence locations
slice timeline <slice>      Ordered event timeline with phase durations
slice export <slice>        Export a reproducible run package
slice compare               Compare manual vs. orchestrated run JSON files
slice metrics <slice>       Compute authoritative metrics with provenance
```

Run `slice <command> --help` for full options. Global flags (`--repo-dir`,
`--control-home`, `--adapter`) go **before** the subcommand.

## Repository layout

```
slice_orchestrator/     Runtime implementation (control store, state machine,
                         gates, dispatch, MCP server, CLI)
tests/                  240 tests (state machine, security, MCP protocol,
                         cross-host isolation, recovery, ...)
.orchestrator/          JSON schemas, transition policy, protocol docs
.mcp.json               Project-scoped MCP server registration
docs/                   Reference documentation (architecture, MCP contract,
                         observability, roadmap) — see docs/README.md
docs/archive/           Historical validation & remediation reports (audit
                         trail, not onboarding material)
orchestrator/           Method documentation for the orchestration approach
                         itself (prompts, decisions, review heuristics) —
                         informational, not the runtime (that's
                         slice_orchestrator/)
test-project/            Disposable fixture repo used to dogfood the
                         orchestrator (includes deliberately adversarial
                         fixtures for security tests)
evidence/                Raw supporting evidence referenced by docs/archive/
                         reports (logs, checkpoints, run exports)
```

## Project status

Slice Orchestrator is under active development. Current milestone status,
what's validated with live evidence, and what's explicitly still open are
tracked in [docs/roadmap.md](docs/roadmap.md). In short:

- ✅ Core runtime, state machine, and security model: implemented and tested
- ✅ Cursor Chat native integration: validated with live tool invocation and a full IDE restart
- ✅ Claude Code native integration: validated with live tool invocation through a complete lifecycle to `COMPLETE`
- ⚠️ Net human productivity benefit: **not yet established** — an initial
  agent-vs-agent study was inconclusive on real developer speedup (see
  [docs/productivity-study-analysis.md](docs/productivity-study-analysis.md));
  treat governance/traceability, not speed, as the current value proposition
- ⏳ Concurrent dual-host sessions and cross-client restart recovery: not yet validated

## Contributing

Issues and pull requests are welcome. Before opening a PR:

1. `uv run python3 -m pytest tests/ -q` — the full suite must pass
2. If you touch MCP tool schemas or the state machine, update the relevant
   doc in `docs/` in the same PR
3. Keep validation/remediation write-ups in `docs/archive/` rather than the
   repository root

## License

MIT — see [LICENSE](LICENSE).
