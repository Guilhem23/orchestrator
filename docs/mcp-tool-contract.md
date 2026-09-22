# Cursor MCP Tool Contract

**Status**: AUTHORITATIVE SPECIFICATION — Host-agnostic MCP tool interface
**Date**: 2026-09-11
**Version**: 2.0.0
**Applies to**: Cursor Chat (primary) and Claude Code (secondary) via the same stdio MCP server

---

## 1. Overview

This document specifies the JSON input/output contract for the Model Context Protocol (MCP) tools provided by the Slice Orchestrator (`slice_orchestrator.mcp_server`).

Both Cursor Chat and Claude Code invoke these tools over `stdio` transport. Behavior is host-independent. Optional `host` metadata (`cursor` | `claude-code` | …) may be supplied on tools that accept it; it is observational only and **never** grants authority.

All parameters support both standard names (`slice` or `slice_name`, `objective` or `description`) for ergonomic conversational tool calls.

---

## 2. Tool Contracts

### 2.1 `slice_start`

Creates a new slice run or resumes an existing one.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier matching `^S[0-9]+$` (e.g., `"S100"`).
  - `objective` or `description` (`string`, optional): High-level goal.
  - `base_commit` (`string`, optional): Specific Git commit OID.
  - `repo_dir` (`string`, optional): Working directory.

* **Output**:
  ```json
  {
    "slice": "S100",
    "slice_name": "S100",
    "run_id": "060d4b1a-...",
    "status": "PLANNING",
    "state": "PLANNING",
    "generation": 1,
    "sequence": 1,
    "base_commit_oid": "38bc4be...",
    "is_new_run": true,
    "objective": "Add input validation",
    "next_action": "Submit an execution plan using slice_plan..."
  }
  ```

---

### 2.2 `slice_context`

Retrieves a structured context pack grounding Cursor Chat in repository and slice state.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `include_plan` (`boolean`, default: `true`): Include plan records.
  - `include_work_items` (`boolean`, default: `true`): Include work items.
  - `include_remediation` (`boolean`, default: `true`): Include remediation packets.
  - `include_role_context` (`boolean`, default: `true`): Include role context.

* **Output**:
  ```json
  {
    "slice": "S100",
    "exists": true,
    "run_id": "060d4b1a-...",
    "state": "PLANNING",
    "plan_summary": "Validation plan",
    "plan_revision": 1,
    "objectives": [...],
    "work_items": [...],
    "open_remediation_packets": [],
    "repository_facts": {
      "head_commit_oid": "38bc4be...",
      "workspace_revision_digest": "a1b2c3d...",
      "repo_dir": "/path/to/repo"
    },
    "legal_next_transitions": ["PLAN_READY", "STOPPED"],
    "context_pack_digest": "e3b0c44..."
  }
  ```

---

### 2.3 `slice_grill`

Challenges objectives to surface ambiguities, risks, and missing prerequisites before planning.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `objective` or `objective_description` (`string`, optional): Objective description.
  - `requirement_clarification` (`string`, optional): Human/LLM clarification text.

* **Output**:
  ```json
  {
    "slice": "S100",
    "grill_id": "grill-a1b2c3d4",
    "questions": [
      {
        "question_id": "q_missing_objective",
        "question": "What is the specific objective?",
        "why_blocked": "Objective text is empty.",
        "facts": ["No objective text provided."],
        "options": ["Provide objective description"],
        "recommendation": "Specify concise objective.",
        "impact": "Cannot form plan without objective.",
        "category": "ambiguity",
        "severity": "blocking"
      }
    ],
    "prerequisite_checks": [
      {
        "check_id": "test_suite_configured",
        "description": "Verify test suite exists",
        "status": "pass"
      }
    ],
    "risk_summary": "Low risk."
  }
  ```

---

### 2.4 `slice_plan`

Submits or revises a structured execution plan.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `plan` (`object`, required): Structured plan containing `description`, `scope_manifest`, `work_items`.
  - `is_revision` (`boolean`, default: `false`): Mark as plan revision.

* **Output**:
  ```json
  {
    "slice": "S100",
    "plan_id": "S100-plan-v1",
    "plan_digest": "c7a3b4...",
    "plan_revision": 1,
    "state": "PLAN_READY",
    "work_items_created": 1,
    "next_action": "Dispatch architecture reviewer...",
    "message": "Plan revision 1 successfully persisted."
  }
  ```

---

### 2.5 `slice_work_list`

Lists, creates, updates, or inspects work items in a slice.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `action` (`string`, default: `"list"`): One of `"list"`, `"create"`, `"update"`, `"inspect"`.
  - `work_item` (`object`, optional): Required for `"create"`/`"update"`.

* **Output**:
  ```json
  {
    "slice": "S100",
    "objectives": [...],
    "work_items": [
      {
        "work_item_id": "S100-WI-1",
        "title": "Implement input validation",
        "assigned_role": "IMPLEMENTER",
        "status": "READY",
        "dependencies": [],
        "blockers": []
      }
    ],
    "ready_items": ["S100-WI-1"],
    "message": "Retrieved 1 work item(s). 1 ready for execution."
  }
  ```

---

### 2.6 `slice_dispatch`

Issues a role execution assignment and transitions state.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `role` (`string`, optional): One of `"ARCHITECTURE_REVIEWER"`, `"IMPLEMENTER"`, `"ADVERSARIAL_REVIEWER"`, `"REMEDIATOR"`.
  - `work_item_id` (`string`, optional): Target work item ID.

* **Output**:
  ```json
  {
    "slice": "S100",
    "assignment_id": "8f3a1234-...",
    "execution_id": "exec-a1b2c3d4",
    "role": "IMPLEMENTER",
    "work_item_id": "S100-WI-1",
    "state": "IMPLEMENTATION",
    "context_pack_digest": "f4e5d6...",
    "prompt": "Execute IMPLEMENTER task for slice S100...",
    "message": "Assignment 8f3a1234-... issued for role IMPLEMENTER."
  }
  ```

---

### 2.7 `slice_record_result`

Binds worker or Cursor-subtask result to control plane.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `assignment_id` (`string`, required): Single-use assignment ID.
  - `success` (`boolean`, default: `true`): Execution status.
  - `summary` (`string`, optional): Summary of work done.
  - `artifacts` (`object`, optional): Role artifacts (e.g., `{"verdict": "APPROVED"}`).
  - `role_context_update` (`object`, optional): Updated context paths.

* **Output**:
  ```json
  {
    "slice": "S100",
    "state": "IMPLEMENTATION_READY_FOR_REVIEW",
    "result_accepted": true,
    "context_checkpointed": true,
    "candidate_captured": true,
    "next_action": "Current state is IMPLEMENTATION_READY_FOR_REVIEW...",
    "message": "Result for assignment 8f3a1234-... successfully recorded."
  }
  ```

---

### 2.8 `slice_run_tests`

Executes control test suite independently and persists HMAC-signed receipt.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `test_ids` (`array`, optional): Specific test identifiers.

* **Output**:
  ```json
  {
    "slice": "S100",
    "tests_passed": true,
    "test_results": [
      {
        "test_id": "default_control_test",
        "passed": true,
        "exit_code": 0,
        "duration_seconds": 0.45
      }
    ],
    "receipt_id": "receipt-a1b2c3d4",
    "receipt_digest": "e7f8a9...",
    "message": "Control test execution completed and HMAC receipt persisted."
  }
  ```

---

### 2.9 `slice_status`

Queries concise state, progress, and next legal actions.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `verbose` (`boolean`, default: `false`): Include detailed event history.

* **Output**:
  ```json
  {
    "slice": "S100",
    "exists": true,
    "run_id": "060d4b1a-...",
    "state": "IMPLEMENTATION_READY_FOR_REVIEW",
    "objective": "Add input validation",
    "current_work_item": "S100-WI-1",
    "blockers": [],
        "execution_mode": "mcp-native",
    "generation": 1,
    "sequence": 6,
    "plan_revision": 1,
    "review_cycle": 1,
    "remediation_cycle": 0,
    "is_terminal": false,
    "legal_next_transitions": ["ADVERSARIAL_REVIEW", "STOPPED"],
    "next_action": "In state IMPLEMENTATION_READY_FOR_REVIEW..."
  }
  ```

---

### 2.10 `slice_report`

Generates a human-facing summary report of a slice run.

* **Inputs**:
  - `slice` or `slice_name` (`string`, required): Slice identifier.
  - `include_event_history` (`boolean`, default: `false`): Include event stream.
  - `include_evidence` (`boolean`, default: `true`): Include evidence summary.

* **Output**:
  ```json
  {
    "slice": "S100",
    "run_id": "060d4b1a-...",
    "objective": "Add input validation",
    "final_state": "COMPLETE",
    "total_events": 12,
    "plan_revisions": 1,
    "review_cycles": 1,
    "remediation_cycles": 0,
    "tests_executed": 2,
    "tests_passed": 2,
    "commits_made": 1,
    "evidence_location": "/path/to/repo/.orchestrator_slice",
    "verdict": "COMPLETE",
    "recommended_next_action": "Slice completed successfully.",
    "message": "Slice S100 report generated."
  }
  ```

---

## 3. Authority & Error Boundaries

- **Single-use assignments**: `slice_record_result` consumes assignments; attempts to re-use an assignment fail closed with `OrchestratorError` / `ControlStoreError`.
- **Schema validation**: Invalid slice names or payloads raise `PolicyError` or `ValidationError`.
- **Fail-closed gate check**: Invalid transitions raise `TransitionError` and leave control state unmodified.
- **Host metadata**: Optional `host` never bypasses gates, assignments, or terminal immutability.
- **Lifecycle completion**: Use `slice_request_review`, `slice_gate`, and `slice_finalize` to reach terminal `COMPLETE` without direct Python `controller.step()` calls.

### 2.11 `slice_request_review`

Issues an independent adversarial review assignment.

* **Inputs**: `slice`/`slice_name`, optional `reviewer_principal`, optional `repo_dir`, optional `host`.
* **Transition**: `IMPLEMENTATION_READY_FOR_REVIEW` → `ADVERSARIAL_REVIEW`.

### 2.12 `slice_gate`

Evaluates deterministic commit gate preconditions (read-only evaluation).

* **Inputs**: `slice`/`slice_name`, optional `repo_dir`.
* **Output**: `passed`, `reason`, digest fields, `next_action`.

### 2.13 `slice_finalize`

Finalizes `COMMIT_READY` → `COMPLETE` after gate success.

* **Inputs**: `slice`/`slice_name`, optional `commit_message`, optional `repo_dir`.
* **Idempotent** if already `COMPLETE`.
