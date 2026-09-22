# Execution Modes Architecture

**Status**: FROZEN — Authoritative architectural specification
**Date**: 2026-09-11
**Supersedes**: Implicit single-mode (subprocess-only) architecture

---

## 1. Architectural Decision

The Slice Orchestrator supports explicit execution modes that share a single control-plane authority. Native MCP hosts are host-agnostic at the tool layer:

```text
PRIMARY NATIVE MCP HOST:     Cursor Chat
SECONDARY NATIVE MCP HOST:   Claude Code
COMMON INTERFACE:            stdio MCP server
EXTERNAL SUBPROCESS WORKERS: Cursor CLI / Claude CLI / Gemini CLI
COMMON AUTHORITY:            Slice Orchestrator Control Plane
```

```text
┌─────────────────────────────────────────────────────────┐
│                                                         │
│           Slice Orchestrator Control Plane               │
│                                                         │
│  Objectives · Plans · Work Items · State Transitions     │
│  Gates · Evidence · HMAC/Hash-Chain · Commit Authority   │
│                                                         │
├─────────────────────┬───────────────────────────────────┤
│                     │                                   │
│   MODE A            │   MODE B                          │
│   Native MCP hosts  │   External Subprocess             │
│                     │                                   │
│   Cursor Chat       │   CLI / CI / scheduler            │
│   Claude Code       │   ↕ Run loop                      │
│   ↕ MCP/tools       │   SubprocessWorkerAdapter          │
│   Control Plane     │   ↕ isolated process              │
│   ↕ structured      │   External CLI / local worker      │
│   Host agents       │                                   │
│                     │                                   │
└─────────────────────┴───────────────────────────────────┘
```

See [multi-host-architecture.md](multi-host-architecture.md) for the frozen multi-host contract.

---

## 2. Mode A — Cursor-Native Orchestration (PRIMARY)

### Overview

The human works inside Cursor Chat. The orchestrator is exposed as MCP tools (or equivalent local functions). Cursor is both the LLM host and the agent execution environment. The orchestrator does not spawn Cursor — Cursor invokes the orchestrator.

### Flow

```text
Human
  ↓  describes objective
Cursor Chat
  ↓  invokes MCP/tool
Slice Orchestrator Control Plane
  ↓  persists state, validates transitions
MCP/tool response (structured JSON)
  ↓  returned to Cursor Chat
Cursor or Cursor-managed agent
  ↓  executes subtask (implementation, review)
slice_record_result
  ↓  binds result to control plane
Control Plane
  ↓  evaluates gates, runs independent tests
Cursor Chat
  ↓  receives summary
Human
  ↓  reviews, decides, continues
```

### Properties

| Property | Value |
|---|---|
| Primary interface | Cursor Chat |
| LLM host | Cursor |
| Orchestrator invocation | MCP/tool calls from within Cursor |
| Worker spawning | None (Cursor executes subtasks directly) |
| Separate `cursor-agent login` | **Not required** |
| Human interaction model | Collaborative, conversational |
| Headless execution | Limited (requires Cursor session) |
| State persistence | SQLite event store (same as Mode B) |
| Control-plane authority | Fully preserved |

### Cursor Chat's role

- **Primary human interface**: The human communicates through Cursor Chat.
- **LLM host**: Cursor provides the language model that reasons about the plan, implementation, and review.
- **Agent runtime**: Cursor executes subtasks (e.g., code implementation) using its own agent capabilities and subagents.
- **Tool caller**: Cursor invokes orchestrator tools to manage lifecycle state.

### Orchestrator's role

- **State authority**: Owns the event-sourced state machine and all transitions.
- **Plan persistence**: Stores plans, work items, objectives, and context.
- **Gate evaluation**: Independently evaluates commit gates, cycle limits, and acceptance criteria.
- **Test execution**: Runs independent control tests (not delegated to the LLM).
- **Evidence management**: Persists receipts, review artifacts, and cryptographic anchors.
- **Structured context provider**: Returns typed JSON to Cursor Chat for each tool call.

### MCP/tool boundary

Each tool is a read or mutate operation on the control plane. Tools:
- Accept structured JSON input
- Return structured JSON output
- Enforce authority restrictions (no tool can approve its own work)
- Validate state transitions before applying them
- Are idempotent or explicitly state-mutating

### How objectives are created

The human describes an objective in natural language. Cursor Chat invokes `slice_start` with a slice name and optional description. The control plane creates a `SLICE_RUN` record and transitions to `PLANNING`.

### How context is retrieved

Cursor Chat invokes `slice_context` to receive a structured context pack containing: current state, plan summary, work item status, open remediation packets, relevant file paths, and previous role context. This gives the LLM grounded, non-hallucinated context.

### How plans are returned

After reasoning about context, Cursor Chat invokes `slice_plan` to submit a structured plan. The control plane validates and persists the plan, creates the objective, and transitions to `PLAN_READY`.

### How work items are created

The plan submission may include an initial work item decomposition. Alternatively, Cursor Chat invokes `slice_work_list` with `action: "create"` to add work items to the plan. Work items are stored in the control plane.

### How Cursor executes subtasks

When a work item is dispatched (via `slice_dispatch`), Cursor Chat uses its own agent capabilities — including subagents — to execute the assigned task. The orchestrator does not spawn Cursor; Cursor is already running.

### How results are recorded

After completing a subtask, Cursor Chat invokes `slice_record_result` with the assignment ID, execution summary, and artifacts. The control plane validates result binding (context digests, assignment matching) and transitions state.

### How tests and reviews are requested

Cursor Chat invokes `slice_run_tests` to trigger independent test execution by the control plane. The control plane runs `execute_control_test` (e.g., `pytest -q`) and persists HMAC-signed receipts. The LLM does not run or fake tests.

### How state and evidence are persisted

All state changes are recorded as append-only events in the SQLite store with cryptographic hash chaining. Receipts, review artifacts, and plans are stored as JSON records with computed digests.

### How final summaries are returned to chat

Cursor Chat invokes `slice_report` to receive a structured summary of the slice run: states visited, tests executed, findings, remediation cycles, and final verdict. The human reviews this in Cursor Chat.

### How the control plane remains authoritative

The control plane validates every state transition. No tool can bypass a gate, manufacture approval, or skip a required review. The LLM/agent is a proposal generator, not an authority.

---

## 3. Mode B — External Subprocess Orchestration (SECONDARY)

### Overview

The orchestrator is invoked from the CLI, a CI pipeline, or a scheduler. It drives an autonomous run loop, dispatching work to external subprocess workers. Workers are headless CLI processes.

### Flow

```text
CLI / CI / scheduler
  ↓  slice run S6
Slice Orchestrator (run loop)
  ↓  dispatch to worker adapter
SubprocessWorkerAdapter
  ↓  spawn isolated process
External Worker CLI (cursor-agent, claude, gemini, local)
  ↓  execute task, produce result JSON
SubprocessWorkerAdapter
  ↓  validate result binding
Slice Orchestrator
  ↓  evaluate gates, persist state
CLI output / CI artifacts
```

### Properties

| Property | Value |
|---|---|
| Primary interface | CLI / CI / scheduler |
| LLM host | External worker process |
| Orchestrator invocation | `slice run S6` or programmatic call |
| Worker spawning | `SubprocessWorkerAdapter` spawns isolated processes |
| Worker authentication | Required (env var, login, or API key) |
| Human interaction model | Operational, observational |
| Headless execution | Native |
| State persistence | SQLite event store (same as Mode A) |
| Control-plane authority | Fully preserved |

### CLI invocation

```bash
# Plan a slice
slice plan S6

# Drive to completion with a specific worker
slice --adapter cursor run S6

# Check status
slice status S6

# Inspect event stream
slice inspect S6 --json
```

### Worker authentication

External CLI workers require their own authentication:
- `cursor-agent`: requires `cursor-agent login` or `CURSOR_API_KEY`
- `claude`: requires Anthropic API key
- `gemini`: requires Google API key
- `subprocess`: requires executable path

This authentication is **not** required for Mode A (Cursor-native).

### Environment isolation

Workers run in a restricted environment:
- Only `DEFAULT_ENV_ALLOWLIST` variables are passed (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `PYTHONPATH`, `USER`)
- Control-plane secrets are never leaked to worker processes
- Input/output is isolated to `output_dir/worker_runs/<assignment_id>/`

### Timeout and output limits

- `timeout_seconds`: default 30s, configurable per adapter
- `max_output_bytes`: default 10 MB
- Exceeding limits → `TIMEOUT` or `MALFORMED_RESULT` failure classification

### Worker result binding

The `validate_worker_result_binding()` function verifies:
- `run_id`, `slice`, `assignment_id`, `role` match the input bundle
- `candidate_tree_oid` and `workspace_revision_digest` match (if set)
- `context_pack_digest` matches
- No duplicate assignment consumption
- Timestamp validity

### Failure semantics

Every execution attempt is classified into exactly one of:
- `SUCCESS`
- `UNAVAILABLE` (missing binary)
- `TIMEOUT`
- `NON_ZERO_EXIT`
- `MALFORMED_RESULT`
- `EXECUTION_ERROR`
- `CANCELLED`

Failures are **fail-closed** and are never converted into `SUCCESS`.

### Headless and CI use cases

Subprocess mode is designed for:
- Continuous integration pipelines
- Scheduled batch execution
- Server-side orchestration
- Automated regression testing with real workers
- Local-model execution (e.g., Ollama, local LLM via subprocess)

### Worker replacement

If a worker fails or is replaced, the control plane preserves all state. A new worker receives the current context pack (plan, work items, role context, remediation packets) and can resume from the last persisted state.

### Independent review

Adversarial review always uses a fresh context per review cycle. The reviewer cannot see the implementation thread's internal reasoning. Review artifacts are persisted as independent evidence.

---

## 4. Common Control-Plane Contract

Both modes share identical governance through the Slice Orchestrator Control Plane.

### Shared primitives

```text
Objectives              — High-level slice goals
Requirements            — Source requirements per objective
Plans                   — Versioned plan records with digests
Work Items              — DAG of tasks with dependencies and status
Assignments             — Role-bound execution assignments
Context Packs           — Checkpointed role context with digests
State Transitions       — Event-sourced FSM (PLANNING → COMPLETE)
Worker Result Binding   — Context/digest validation on every result
Test Receipts           — HMAC-signed, independently executed
Independent Review      — Fresh adversarial review per cycle
Remediation             — Structured packets with finding tracking
Gates                   — Commit gate, acceptance gate, cycle limits
Evidence                — Append-only artifacts with receipt chain
HMAC/Hash-Chain         — Cryptographic event chaining
Concurrency Control     — Atomic file locks (fcntl.flock)
Commit Authorization    — Control plane only, never worker/LLM
```

### Authority invariant (non-negotiable)

```text
LLM / Worker:
    reasons, proposes, executes assigned work, reports results

Control Plane:
    owns authority, transitions, evidence validity, gates, and commit authorization
```

### State lifecycle (identical in both modes)

```text
PLANNING
  → PLAN_READY
  → ARCHITECTURE_REVIEW
  → ARCHITECTURE_APPROVED
  → IMPLEMENTATION
  → IMPLEMENTATION_READY_FOR_REVIEW
  → ADVERSARIAL_REVIEW
      → BLOCKED → REMEDIATION → IMPLEMENTATION → ADVERSARIAL_REVIEW
      → APPROVED → COMMIT_READY
  → COMMITTED
  → GOVERNANCE_RECONCILIATION
  → COMPLETE
```

### Policy enforcement

Both modes enforce:
- `max_review_cycles` (default 5)
- `max_remediation_cycles` (default 5)
- `stop_on_max_cycles: true`
- `never_commit_on_blocked_gate: true`
- `require_fresh_adversarial_context: true`

### Persistence

Both modes write to the same SQLite event store:
- `.orchestrator_slice/state.db`
- `.orchestrator_slice/trusted_tail_anchor`
- `.orchestrator_slice/control_secret.key`
- `.orchestrator_slice/locks/`

### Event chaining

Every event is cryptographically chained using HMAC:
```text
event_hash = HMAC(control_secret, serialize(event_payload + previous_hash))
```

This chain is verified on every state reconstruction.

---

## 5. What Each Mode Is NOT

### Mode A is NOT

- A subprocess that spawns `cursor-agent` CLI
- A headless automation pipeline
- A replacement for Mode B in CI/CD contexts
- A way to bypass control-plane authority
- Dependent on `cursor-agent login`

### Mode B is NOT

- The primary human development experience
- "Cursor-native orchestration"
- A replacement for Mode A in interactive development
- A way to bypass control-plane authority
- The same as Cursor Chat integration

### The CursorWorkerAdapter is NOT

- Cursor-native integration (it is subprocess-mode integration)
- The primary way to use the orchestrator with Cursor
- Required for Mode A
- A substitute for MCP tools

---

## 6. Conclusion

> The Slice Orchestrator's primary product experience is Cursor-native orchestration through Cursor Chat and MCP/equivalent tools. The external subprocess adapter is a complementary execution backend for headless, CI/CD, asynchronous, server-side, and local-model use cases. Both modes share the same control-plane authority, persistence, evidence, gates, and security invariants.

---

**Architecture frozen**: 2026-09-11
**Authority**: This document is the authoritative specification for the two-mode architecture.
