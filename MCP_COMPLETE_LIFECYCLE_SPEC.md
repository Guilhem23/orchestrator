# MCP Complete Lifecycle Specification

## 1. Overview

This specification defines the complete end-to-end MCP workflow for the Slice Orchestrator, enabling Cursor Chat (and any MCP client) to drive a slice run from initial start to a terminal `COMPLETE` state exclusively using JSON-RPC tool calls.

No direct Python calls (such as `controller.step()`) are permitted or required.

## 2. Terminal State Lifecycle Sequence

The authoritative tool sequence for a complete slice lifecycle is:

```text
1. slice_start
   ↳ Initializes or opens a slice run in state PLANNING.

2. slice_context
   ↳ Retrieves workspace context, base commit OID, and current run state.

3. slice_grill
   ↳ Validates requirements, objectives, and prerequisite checks.

4. slice_plan
   ↳ Submits structured plan, scope manifest, and establishes baseline authoritative test manifest.
     Transitions to PLAN_READY.

5. slice_work_list
   ↳ Queries or creates DAG work items for the slice.

6. slice_dispatch (role="ARCHITECTURE_REVIEWER")
   ↳ Issues assignment for architecture review. Transitions to ARCHITECTURE_REVIEW.

7. slice_record_result (role="ARCHITECTURE_REVIEWER", verdict="APPROVED")
   ↳ Records architecture review approval. Transitions to ARCHITECTURE_APPROVED.

8. slice_dispatch (role="IMPLEMENTER")
   ↳ Issues implementation assignment to candidate worker. Transitions to IMPLEMENTATION.

9. [Candidate implementation changes made to workspace]

10. slice_record_result (role="IMPLEMENTER", success=True)
    ↳ Checkpoints context and captures candidate tree OID. Transitions to IMPLEMENTATION_READY_FOR_REVIEW.

11. slice_run_tests
    ↳ Executes authorized control tests against candidate code. Verifies that authoritative baseline tests
      are unmodified. Persists HMAC-signed test receipt bound to tree and revision digest.

12. slice_request_review (or slice_dispatch with role="ADVERSARIAL_REVIEWER")
    ↳ Issues adversarial review assignment to an independent reviewer principal.
      Transitions to ADVERSARIAL_REVIEW.

13. slice_record_result (role="ADVERSARIAL_REVIEWER", verdict="APPROVED")
    ↳ Records independent adversarial review verdict. Verifies reviewer independence (implementer != reviewer).
      Transitions to COMMIT_READY.

14. slice_gate
    ↳ Evaluates deterministic commit gate preconditions (receipt integrity, tree binding, test set digest,
      scope manifest, reviewer independence).

15. slice_finalize
    ↳ Validates commit gate and executes deterministic terminal transitions:
      COMMIT_READY → COMMITTED → GOVERNANCE_RECONCILIATION → COMPLETE.

16. slice_report
    ↳ Generates comprehensive final report from persisted event log and store records.
```

## 3. Detailed Specification for New MCP Tools

### 3.1 `slice_request_review`

* **Description**: Request an independent adversarial review assignment for a slice ready for review.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "slice": { "type": "string" },
      "slice_name": { "type": "string" },
      "reviewer_principal": { "type": "string" },
      "repo_dir": { "type": "string" }
    }
  }
  ```
* **Output Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "slice": { "type": "string" },
      "assignment_id": { "type": "string" },
      "role": { "type": "string" },
      "state": { "type": "string" }
    }
  }
  ```
* **State Transition**: `IMPLEMENTATION_READY_FOR_REVIEW → ADVERSARIAL_REVIEW`.
* **Security Rules**: Dispatches review to `reviewer_principal`. Rejects if slice is not in `IMPLEMENTATION_READY_FOR_REVIEW`.

---

### 3.2 `slice_gate`

* **Description**: Evaluate deterministic commit gate checks prior to finalization.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "slice": { "type": "string" },
      "slice_name": { "type": "string" },
      "repo_dir": { "type": "string" }
    }
  }
  ```
* **Output Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "slice": { "type": "string" },
      "passed": { "type": "boolean" },
      "reason": { "type": "string" },
      "candidate_tree_oid": { "type": ["string", "null"] },
      "workspace_revision_digest": { "type": ["string", "null"] },
      "evidence_set_digest": { "type": ["string", "null"] },
      "approved_revision_digest": { "type": ["string", "null"] }
    }
  }
  ```
* **Idempotency**: Read-only evaluation; safe to call repeatedly.

---

### 3.3 `slice_finalize`

* **Description**: Finalize an approved slice run and transition state to terminal `COMPLETE`.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "slice": { "type": "string" },
      "slice_name": { "type": "string" },
      "repo_dir": { "type": "string" }
    }
  }
  ```
* **Output Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "slice": { "type": "string" },
      "finalized": { "type": "boolean" },
      "state": { "type": "string" },
      "commit_oid": { "type": ["string", "null"] },
      "message": { "type": "string" }
    }
  }
  ```
* **State Transitions**: `COMMIT_READY → COMMITTED → GOVERNANCE_RECONCILIATION → COMPLETE`.
* **Idempotency**: If state is already `COMPLETE`, returns `finalized: true` without re-executing.
* **Failure Behavior**: If commit gate checks fail, returns `finalized: false`, records failure event, and preserves state for remediation.
