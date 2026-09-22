# Observability Model

**Status**: AUTHORITATIVE for observational mapping  
**Date**: 2026-09-11  
**Authority boundary**: Observability observes; the control plane alone owns state, transitions, gates, receipts, and authorization.

---

## 1. Separation of concerns

```text
Control Plane:     owns state, transitions, gates, receipts, authorization
Observability:     observes and reports what happened
LLM / Worker:      may explain or estimate; never authoritative metrics
```

Metrics and diagnostics are derived primarily from:

* persisted control-plane events
* independently verified test receipts
* assignments, reviews, gates
* workspace / tree metadata and timestamps
* Git diffs (when computed at export time)
* human interaction records where available

Worker-written summaries are **never** authoritative.

---

## 2. Observable event view

Each observational view may include:

| Field | Meaning |
|---|---|
| `event_name` | Control-plane `event_type` or record-derived concept |
| `source` | `control_plane_event` / `record` / `derived` |
| `timestamp` | `recorded_at` |
| `run_id` / `slice_id` | Run and slice identifiers |
| `work_item_id` / `assignment_id` | When present in actor/payload |
| `actor` / `host` | Principal; optional observational `host_metadata` |
| `state_before` / `state_after` | Projection before/after event |
| `duration` | Elapsed ms since previous event (nullable) |
| `result` / `error_code` | Verdict or stop/failure code |
| `revision` | Plan revision when present |
| `tree_digest` / `workspace_digest` | Candidate/tree and workspace digests |

---

## 3. Concept → existing control-plane sources

Redundant authoritative events are **not** added when existing events/records already cover the concept.

| Observable concept | Primary sources |
|---|---|
| run creation | `RUN_OPENED` |
| requirement clarification | `REQUIREMENT_CLARIFICATION` records (`slice_grill`) |
| question creation | clarification / `DECISION_REQUIRED` records |
| human answer | clarification / `DECISION_ANSWER` records |
| context creation | `CONTEXT_PACK_GENERATED` |
| plan creation | `PLAN_PERSISTED` |
| plan revision | `PLAN_REVISED`, `PLAN_REVISION_REQUESTED` |
| work-item creation | `WORK_ITEM` records with plan events |
| work-item dispatch | `ASSIGNMENT_ISSUED`, `*_ASSIGNED` |
| worker start | assignment-issued / role-assigned events |
| worker completion | `ASSIGNMENT_CONSUMED`, `CANDIDATE_CAPTURED` |
| worker failure | `RUN_STOPPED` with `WORKER_*` codes |
| worker replacement | `IMPLEMENTATION_WORKER_REASSIGNED` |
| result recording | consume / approve / block / candidate events |
| test start / completion | signed `TEST_RECEIPT` (`started_at` / `completed_at`) |
| review start / completion | `*_REVIEW_ASSIGNED`, `REVIEW_*`, `ARCHITECTURE_*` |
| remediation | `REMEDIATION_ASSIGNED`, `REVIEW_BLOCKED`, packets |
| gate evaluation | read-only `slice_gate`; evidence on commit path |
| finalization | `COMMIT_*`, `GOVERNANCE_*` |
| run completion | `GOVERNANCE_RECONCILED` → `COMPLETE` |
| run failure / cancellation | `RUN_STOPPED`, `FAILED` |
| restart / recovery | `RUN_PAUSED` / `RUN_RESUMED` / `HUMAN_RECOVERY_OPENED` |

Canonical mapping lives in `slice_orchestrator/observability/model.py` (`OBSERVABLE_CONCEPT_SOURCES`).

---

## 4. Structured logs

* Format: JSON Lines + human-readable companion
* Location: `<control_home>/logs/` (under `.orchestrator_slice/`, gitignored)
* Correlate via `sequence` and `event_hash`
* Not authoritative for state
* Secrets and full prompts redacted by default
* Filterable by run, slice, phase, severity, time
* Logging failures raise `LoggingError` and must not imply control success

---

## 5. Reconstruction guarantee

Given an intact control store (verified event chain + records), a Slice Run can be reconstructed via:

```bash
slice timeline <slice> --json
slice diagnostics <slice> --json
slice metrics <slice>
slice export <slice> --format json
```

Logs improve operability but are not required for authoritative reconstruction.
