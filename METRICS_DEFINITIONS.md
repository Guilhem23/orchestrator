# Metrics Definitions

**Status**: AUTHORITATIVE metric catalog for observability  
**Engine**: `slice_orchestrator/observability/metrics.py`  
**Provenance statuses**: `MEASURED` | `DERIVED` | `ESTIMATED` | `DECLARED` | `UNAVAILABLE`

Rules:

* `DECLARED` cannot support authoritative conclusions
* `ESTIMATED` must include assumptions
* `UNAVAILABLE` remains explicit (never fabricated)
* Worker reports cannot change authoritative metrics
* Same verified event chain → reproducible metric values

---

## Provenance envelope

```json
{
  "metric": "review_cycles",
  "value": 2,
  "source_event_range": [12, 28],
  "source_digest": "...",
  "calculated_at": "...",
  "status": "MEASURED",
  "authoritative": true,
  "limitations": ["..."]
}
```

---

## Execution metrics

| Metric | Definition | Sources | Calculation | Limitations | Auth? |
|---|---|---|---|---|---|
| `total_elapsed_time_ms` | Wall clock first→last event | all events | timestamp delta | Ignores host downtime without events | Yes if MEASURED |
| `active_execution_time_ms` | Sum of non-paused phase gaps | events + projection | phase gap sum | Attribution by projected state | Yes if DERIVED |
| `human_waiting_time_ms` | Time in paused phase | `RUN_PAUSED` gaps | phase duration | Grill waits without pause → UNAVAILABLE | No |
| `time_per_lifecycle_phase_ms` | Per-phase gap totals | events | ordered gaps | Missing timestamps → gaps skipped | Yes |
| `time_per_work_item_ms` | Per WI duration | assignments | pairing | Often UNAVAILABLE | — |
| `time_per_worker_ms` | Worker process time | — | — | UNAVAILABLE (not instrumented) | — |
| `time_per_review_ms` | Assign→accept/block | review events | sequential pairs | Multiple cycles approximated | Yes |
| `time_per_remediation_ms` | Remediation assign→next | remediation events | next-event gap | Coarse | Yes |
| `number_of_transitions` | State-changing events | projection pairs | count `before≠after` | Side events excluded | Yes |
| `number_of_retries` | Invalidations / reassign | retry-class events | count | Heuristic set | Yes |
| `number_of_restarts` | Recovery + resume | `HUMAN_RECOVERY_OPENED`, `RUN_RESUMED` | count | Not OS/MCP/Cursor restart | Yes |

---

## Interaction metrics

| Metric | Definition | Sources | Status notes |
|---|---|---|---|
| `human_questions` | Clarification records | `REQUIREMENT_CLARIFICATION` | MEASURED/DERIVED |
| `questions_answered_from_repository_facts` | Classified grill answers | — | UNAVAILABLE |
| `questions_genuinely_requiring_human_input` | Human-only questions | — | UNAVAILABLE |
| `human_answers` | Answer records | clarifications | DERIVED (conflated today) |
| `human_interruptions` | Pauses | `RUN_PAUSED` | MEASURED |
| `time_waiting_for_human_ms` | Pause waiting | paused phase | DERIVED/UNAVAILABLE |
| `context_reconstruction_events` | Context packs | `CONTEXT_PACK_GENERATED` | MEASURED |
| `number_of_mcp_tool_calls` | Host-tagged events | `host_metadata` | DERIVED/UNAVAILABLE (incomplete) |

---

## Worker metrics

| Metric | Sources | Auth? |
|---|---|---|
| `worker_executions` | `ASSIGNMENT_ISSUED` | Yes |
| `worker_failures` | `RUN_STOPPED` + `WORKER_FAILED` | Yes |
| `worker_timeouts` | stop codes containing TIMEOUT | Yes / UNAVAILABLE |
| `worker_replacements` | `IMPLEMENTATION_WORKER_REASSIGNED` | Yes |
| `worker_unavailable_events` | `WORKER_UNAVAILABLE` | Yes |
| `worker_result_validation_failures` | `MALFORMED_WORKER_OUTPUT` | Yes |
| `stale_assignments_rejected` | assignment status | Yes |
| `assignments_consumed` | `ASSIGNMENT_CONSUMED` | Yes |

---

## Quality metrics

| Metric | Sources | Notes |
|---|---|---|
| `tests_executed` / `passed` / `failed` | signed `TEST_RECEIPT` | Authoritative |
| `test_retries` | receipt count heuristic | DERIVED |
| `reviews_executed` | review-assigned events | Authoritative |
| `review_findings` (+ critical/major/minor) | review records | MEASURED when findings present |
| `remediation_cycles` | state high-water / packets | Authoritative |
| `defects_detected_before_review` | failed receipts | DERIVED approximation |
| `defects_detected_during_review` | findings | DERIVED |
| `defects_escaping_review` | — | UNAVAILABLE |
| `authoritative_test_changes` | — | UNAVAILABLE |
| `out_of_scope_changes` | — | UNAVAILABLE |
| `review_cycle_high_water` | projected state | Authoritative |

---

## Recovery metrics

| Metric | Status |
|---|---|
| `process_restarts` / `mcp_restarts` / `cursor_restarts` | UNAVAILABLE (external attestation) |
| `successful_recoveries` | DERIVED from recovery/resume events |
| `failed_recoveries` | UNAVAILABLE |
| `work_items_resumed` | DERIVED |
| `context_losses` | UNAVAILABLE |
| `stale_assignments_rejected` | MEASURED when assignments listed |

---

## Change metrics

| Metric | Status |
|---|---|
| `files_changed` / `lines_added` / `lines_deleted` | UNAVAILABLE unless export-time git diff added |
| `commits` | MEASURED from commit events |
| `candidate_tree_changes` | MEASURED from `CANDIDATE_CAPTURED` |
| `rework_changes` | DERIVED from invalidation/remediation |
| `final_commit_oid` | MEASURED when present on state |
