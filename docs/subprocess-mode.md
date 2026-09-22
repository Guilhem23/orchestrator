# Subprocess Mode Specification

**Status**: IMPLEMENTED — Validated with 17 security tests and 180+ regression tests
**Date**: 2026-09-11
**Depends on**: [execution-modes.md](execution-modes.md)

---

## 1. Purpose

The subprocess execution mode provides headless, CI/CD, server-side, asynchronous, and local-model execution of Slice Orchestrator workflows. It is a **complementary** execution backend for use cases where interactive Cursor Chat is not available or not appropriate.

This mode is **not** the primary human development experience. See [execution-modes.md](execution-modes.md) for the primary mode (Cursor-native).

---

## 2. Architecture

```text
CLI / CI / scheduler
  ↓
Slice Orchestrator (autonomous run loop)
  ↓
DispatchManager → WorkerRegistry → WorkerAdapter
  ↓
SubprocessWorkerAdapter
  ↓
spawn isolated external process
  ↓
External Worker CLI (cursor-agent, claude, gemini, local script)
  ↓
worker_result.json or stdout JSON
  ↓
validate_worker_result_binding()
  ↓
Control Plane state transition
```

---

## 3. CLI Invocation

### Commands

```bash
# Initialize a slice
slice --adapter subprocess plan S6

# Drive to completion autonomously
slice --adapter cursor run S6

# Check status
slice status S6

# Inspect event stream
slice inspect S6 --json

# Explain current state and next actions
slice explain S6

# Pause execution
slice pause S6 --reason "Waiting for review"

# Resume execution
slice --adapter cursor resume S6 --run

# Stop execution
slice stop S6 --reason "Blocking issue found"

# Recover from STOPPED state
slice recover S6 --target-state IMPLEMENTATION --reason "Fixed blocker"

# List work items
slice work list S6

# Launch exploration (disposable scratch space)
slice --adapter cursor explore S6 --topic "API design options"
```

### Adapter selection

The `--adapter` flag selects the worker backend:

| Adapter ID | Backend | Authentication |
|---|---|---|
| `dummy` | In-process deterministic test worker | None (test-only) |
| `subprocess` | Generic external process | Executable path |
| `cursor` | Cursor Agent CLI (`cursor-agent`) | `cursor-agent login` or `CURSOR_API_KEY` |
| `claude-code` | Claude Code CLI (`claude`) | Anthropic API key |
| `gemini` | Gemini CLI (`gemini`) | Google API key |
| `manual` | Human writes `worker_result.json` | None |

---

## 4. Worker Authentication

### Environment variables

| Variable | Worker | Purpose |
|---|---|---|
| `CURSOR_WORKER_EXECUTABLE` | cursor | Path to `cursor-agent` binary |
| `CLAUDE_WORKER_EXECUTABLE` | claude-code | Path to `claude` binary |
| `GEMINI_WORKER_EXECUTABLE` | gemini | Path to `gemini` binary |

### Authentication requirements

- **cursor-agent**: Requires `cursor-agent login` or `CURSOR_API_KEY` environment variable. Without authentication, the binary exits with code 1 and error "Authentication required".
- **claude**: Requires Anthropic API key in environment or config.
- **gemini**: Requires Google API key in environment or config.
- **subprocess** (generic): Requires an executable path. No vendor-specific auth.

### Fail-closed behavior

If authentication is missing or fails:
- The worker process exits with a non-zero code.
- `SubprocessWorkerAdapter` captures the error and returns `failure_classification="NON_ZERO_EXIT"`.
- The orchestrator halts the run with a clear error message.
- **No silent dummy fallback occurs.**

---

## 5. Environment Isolation

### Allowed environment variables

Workers receive only these variables from the host environment:

```python
DEFAULT_ENV_ALLOWLIST = [
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "PYTHONPATH", "USER"
]
```

All other variables are stripped, including:
- `CONTROL_SECRET` (control-plane HMAC key)
- `DATABASE_URL` or other service credentials
- Custom API keys not in the allowlist

### Directory isolation

- Input payload: `output_dir/worker_runs/<assignment_id>/worker_input.json`
- Result payload: `output_dir/worker_runs/<assignment_id>/worker_result.json`
- Workers operate within `workspace_dir` but cannot modify control-plane state files.

---

## 6. Timeout and Output Limits

| Parameter | Default | Configurable |
|---|---|---|
| `timeout_seconds` | 30s | Per adapter constructor |
| `max_output_bytes` | 10 MB | Per adapter constructor |

### Timeout behavior

When a subprocess exceeds `timeout_seconds`:
1. `subprocess.TimeoutExpired` is raised.
2. The process is killed (`proc.kill()`).
3. The adapter returns `failure_classification="TIMEOUT"`, `success=False`.
4. The orchestrator halts the run.

### Output limit behavior

If stdout, stderr, or `worker_result.json` exceeds `max_output_bytes`:
1. The adapter returns `failure_classification="MALFORMED_RESULT"`, `success=False`.
2. The orchestrator halts the run.

---

## 7. Worker Result Binding

Every worker result is validated by `validate_worker_result_binding()`:

### Required fields

```text
run_id              — Must match the input bundle
slice               — Must match the input bundle
assignment_id       — Must match the input bundle
role                — Must match the input bundle
worker_identity     — Must be present
adapter_version     — Must be present
```

### Context alignment checks

```text
candidate_tree_oid          — Must match if set in input
workspace_revision_digest   — Must match if set in input
context_pack_digest         — Must match evidence_set_digest or context_pack_digest
```

### Duplicate protection

```text
assignment_id must not have been previously consumed (seen_assignments set)
```

### Timestamp validation

```text
start_time and end_time must be valid ISO-8601
end_time >= start_time
```

### Binding failure

Any mismatch causes:
- `failure_classification="MALFORMED_RESULT"`
- `success=False`
- Descriptive error message identifying the specific mismatch

---

## 8. Failure Semantics

Every subprocess execution is classified into exactly one category:

| Classification | Trigger | Recoverable |
|---|---|---|
| `SUCCESS` | Exit 0 + valid JSON + binding pass | Yes (normal) |
| `UNAVAILABLE` | Binary not found or not executable | No (config) |
| `TIMEOUT` | Process exceeded `timeout_seconds` | Retry possible |
| `NON_ZERO_EXIT` | Process exited with code ≠ 0 | Depends on error |
| `MALFORMED_RESULT` | Invalid JSON, schema error, binding failure, oversized output | No (worker bug) |
| `EXECUTION_ERROR` | OS-level failure to launch process | No (env issue) |
| `CANCELLED` | Process interrupted or signalled | Retry possible |

### Fail-closed guarantee

- Failures are **never** converted to `SUCCESS`.
- Missing workers are **never** replaced by dummy fallback (unless `fallback_to_dummy=True` is explicitly set for testing).
- Failed workers halt the run with `RUN_STOPPED` event and clear `reason_code`.

---

## 9. Headless and CI Use Cases

### CI pipeline example

```yaml
# GitLab CI example
slice-orchestrator:
  stage: validate
  script:
    - export PYTHONPATH=$(pwd):$PYTHONPATH
    - export CURSOR_WORKER_EXECUTABLE=/usr/local/bin/cursor-agent
    - export CURSOR_API_KEY=$CI_CURSOR_API_KEY
    - slice --adapter cursor run S6
  artifacts:
    paths:
      - .orchestrator_slice/
    when: always
```

### Batch execution

```bash
for slice in S1 S2 S3; do
    slice --adapter subprocess run "$slice" || echo "FAILED: $slice"
done
```

### Scheduled execution

Subprocess mode supports cron or scheduler invocation:
- State persists across invocations in `.orchestrator_slice/state.db`
- Pause/resume allows multi-session execution
- Atomic locks prevent concurrent corruption

---

## 10. Local-Model Use Cases

Subprocess mode supports local LLM workers:

```bash
# Configure a local model worker
export LOCAL_WORKER_EXECUTABLE=/path/to/my-local-worker.py

# Use generic subprocess adapter
slice --adapter subprocess run S6
```

The local worker script must:
1. Read `worker_input.json` from the path passed as its first argument.
2. Execute the assigned task.
3. Write `worker_result.json` to the `output_dir` specified in the input.
4. Return structured JSON conforming to `validate_worker_result_binding()`.

---

## 11. Worker Replacement

If a worker fails or is replaced between sessions:
1. The control plane preserves all persisted state.
2. The new worker receives the current context pack (plan, work items, role context, remediation packets) via `WorkerInputBundle`.
3. The `candidate_tree_oid` and `workspace_revision_digest` in the bundle allow the new worker to verify it has the correct workspace state.
4. Stale results from the old worker are rejected by binding validation.

### Context preservation

Role context is checkpointed after each successful execution:
- `IMPLEMENTATION_CONTEXT_CHECKPOINTED` event persists the implementation thread's context.
- The context includes work journal, paths modified, and artifact references.
- A new worker can read this context to continue from where the previous worker left off.

---

## 12. Independent Review

In subprocess mode:
- The implementation worker and the adversarial reviewer are **always** separate worker invocations.
- The adversarial reviewer receives a fresh context (not the implementation thread's internal reasoning).
- Review artifacts are persisted independently.
- The control plane verifies that review results come from the reviewer role, not the implementer.

---

## 13. Current Implementation Status

| Component | Status | Test Coverage |
|---|---|---|
| `SubprocessWorkerAdapter` | ✅ Implemented | 17 security tests |
| `CursorWorkerAdapter` (CLI subprocess) | ✅ Implemented | Fail-closed verified |
| `ClaudeCodeWorkerAdapter` | ✅ Implemented | Fail-closed verified |
| `GeminiWorkerAdapter` | ✅ Implemented | Fail-closed verified |
| `ManualWorkerAdapter` | ✅ Implemented | Basic test |
| `TestDummyWorkerAdapter` | ✅ Implemented | Test-only, explicitly marked |
| `validate_worker_result_binding()` | ✅ Implemented | 6 binding tests |
| Worker registry | ✅ Implemented | Registration verified |
| Environment isolation | ✅ Implemented | Secret leak test |
| Timeout enforcement | ✅ Implemented | Timeout test |
| Output limit enforcement | ✅ Implemented | Oversized output test |

### Vendor CLI availability (current environment)

| Worker | Binary Found | Authenticated | End-to-End Verified |
|---|---|---|---|
| cursor-agent | ✅ Found | ❌ Not logged in | ❌ Unverified |
| claude | ❌ Not found | N/A | ❌ Unverified |
| gemini | ❌ Not found | N/A | ❌ Unverified |

---

## 14. Hardening Roadmap

Per [roadmap.md](roadmap.md), subprocess mode hardening is Phase E:

1. Authenticate `cursor-agent` in a dedicated runner environment.
2. Execute end-to-end slice with real Cursor CLI worker.
3. Add CI integration tests against vendor CLIs.
4. Implement configurable timeout escalation per role.
5. Add structured logging for CI artifact collection.
6. Test concurrent slice execution with lock contention.
7. Add worker health-check probe (pre-execution availability check).

---

## 15. Acceptance Criteria

The subprocess mode is accepted when:

- [x] Explicit worker authentication (env var or login)
- [x] Isolated process execution (restricted environment)
- [x] Fail-closed failures (no silent dummy, no implicit success)
- [x] Result binding validation (context/digest checks)
- [ ] Headless execution verified end-to-end with real worker
- [x] Reproducibility from persisted state (SQLite event store)
- [ ] CI compatibility verified in pipeline
- [x] Independent review (fresh reviewer per cycle)
- [x] No silent dummy fallback (8+ security tests)

**Current verdict**: **PARTIAL** — Framework implemented and tested; end-to-end with real vendor CLI worker is unverified.

---

**Specification created**: 2026-09-11
**Authority**: Documents the existing subprocess mode implementation.
