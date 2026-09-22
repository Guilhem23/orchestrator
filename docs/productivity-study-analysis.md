# Productivity Study Analysis

## 1. Study Design

Paired comparison of ten disposable dogfood tasks from [dogfood-task-catalog.md](dogfood-task-catalog.md) under:

* **CONTROL** — Cursor Chat alone (direct edits + pytest; no orchestrator control plane)
* **TREATMENT** — Cursor Chat + Slice Orchestrator tools API (same authority plane as MCP)

Protocol: [productivity-protocol.md](productivity-protocol.md).  
Measurement schema fields use `UNAVAILABLE` when not instrumented. Worker summaries are never authoritative.

Statistical note: n=10 tasks, single agent, fixed order. No inferential tests; no significance claims.

## 2. Task Population

| ID | Type | Complexity |
|---|---|---|
| DF-01 | Small bug fix | 1 |
| DF-02 | Feature addition | 1 |
| DF-03 | Refactoring | 2 |
| DF-04 | Incomplete requirements | 3 |
| DF-05 | Clarification required | 2 |
| DF-06 | Interrupted task | 2 |
| DF-07 | Failed test and remediation | 3 |
| DF-08 | Review finding | 3 |
| DF-09 | Worker failure / unavailable backend | 2 |
| DF-10 | Multi-session recovery | 4 |

Fixture: disposable `calc` repositories seeded per task (bug, clean, or duplicated-logic). Not production codebases.

## 3. Control Condition

Direct implementation by the same agent process: edit sources/tests, run pytest, optionally pause/clarify as the task requires. No `slice_*` control-plane calls. IDE/MCP tool-call counts mostly `UNAVAILABLE`.

## 4. Treatment Condition

Full orchestrator lifecycle where applicable: `slice_start` → context → grill → plan → architecture → implement → tests → adversarial review → gate → finalize. Variants: pause/resume (DF-06/10), fail-then-remediate tests (DF-07), review block (DF-08), worker failure record (DF-09), clarification stop (DF-04).

Authoritative TREATMENT metrics/export digests come from the control store and `slice export`, not from worker prose.

## 5. Raw Measurements

See [productivity-study-data.json](productivity-study-data.json) and the summary table in [productivity-study-results.md](productivity-study-results.md).

Comparable wall-clock samples (ms):

| Task | CONTROL elapsed | TREATMENT elapsed |
|---|---|---|
| DF-01 | 155 | 2723 |
| DF-02 | 163 | 2708 |
| DF-03 | 164 | 2714 |
| DF-04 | 159 | 585 |
| DF-05 | 154 | 2706 |
| DF-06 | 152 | 2942 |
| DF-07 | 299 | 3034 |
| DF-08 | 152 | 1926 |
| DF-09 | 148 | 1183 |
| DF-10 | 149 | 2952 |

## 6. Aggregate Results

**Outcome counts**

| Condition | COMPLETE | PARTIAL | ABANDONED_PENDING_CLARIFICATION | FAILED |
|---|---|---|---|---|
| CONTROL | 8 | 0 | 1 | 1 |
| TREATMENT | 7 | 1 | 1 | 1 |

**Elapsed time on COMPLETE–COMPLETE pairs only (n=7)**  
Tasks: DF-01, DF-02, DF-03, DF-05, DF-06, DF-07, DF-10.

| Statistic | Value |
|---|---|
| Mean (T − C) | +2649 ms |
| Median (T − C) | +2568 ms |
| Mean T/C ratio | ~16.8 |
| Median T/C ratio | ~17.6 |

Normalization: clarification, failure, and partial tasks are **not** pooled into the speed ratio. DF-04/08/09 are reported separately as process/quality outcomes.

## 7. Quality Results

* Functional correctness on green tasks: both conditions produced passing pytest for COMPLETE outcomes.
* Defect/remediation instrumentation: DF-07 recorded remediation on both sides.
* Review-finding path: CONTROL completed after self-remediation; TREATMENT reached PARTIAL after `REVIEW_BLOCKED` (re-dispatch/finalize not completed in harness).
* No false COMPLETE on DF-09 in either condition.

**Verdict**: **NO CLEAR DIFFERENCE** on final functional quality for simple COMPLETE tasks; **OBSERVED TRADE-OFF** on review-friction (DF-08).

## 8. Human Interaction Results

* TREATMENT consistently surfaced grill/clarification (`human_questions ≥ 1` when grill ran).
* CONTROL recorded explicit questions on DF-04 (2) and DF-05 (1).
* CONTROL tool_calls largely `UNAVAILABLE`; TREATMENT tool_calls typically 14–15 on happy paths.

**Verdict**: **OBSERVED ADVANTAGE** for TREATMENT on structured clarification visibility; not proof of less human effort overall.

## 9. Recovery Results

* DF-06 / DF-10 TREATMENT: pause/resume and context reconstruction recorded; COMPLETE achieved.
* CONTROL simulated interruption/context notes without control-store recovery guarantees.

**Verdict**: **OBSERVED ADVANTAGE** for TREATMENT on recoverable multi-session state *for orchestrated runs*; CONTROL has no durable control-plane recovery to compare symmetrically.

## 10. Process Overhead

TREATMENT wall time is dominated by mandatory governance steps (plan, dual reviews, gates, finalize) even when the code change is one function. On these micro-fixtures, overhead dominates useful work by roughly an order of magnitude.

**Verdict**: **OBSERVED TRADE-OFF** — stronger process guarantees at clear elapsed-time cost on small tasks.

## 11. Confounding Factors

* Same agent for both conditions; CONTROL-then-TREATMENT order increases TREATMENT familiarity.
* Agent automation ≠ interactive human developer effort.
* Fixture tasks are tiny; overhead/work ratio will differ on larger slices.
* CONTROL lacks comparable tool-call and waiting instrumentation.
* Pause/worker-failure paths are control-plane exercises, not live IDE crash/network outages.
* Single sample per task; no counterbalanced order.

## 12. Missing or Unreliable Data

* Many CONTROL `tool_calls` / `context_reconstruction` values: `UNAVAILABLE`.
* `developer_assessment` mostly `UNAVAILABLE` (not used as authority).
* `defects_introduced` generally `UNAVAILABLE`.
* TREATMENT `human_active_time_ms` approximated as elapsed − tool waiting.
* DF-08 TREATMENT finalize path incomplete → PARTIAL.

## 13. Observed Conclusions

| Question | Conclusion |
|---|---|
| Faster wall-clock on micro-tasks? | **OBSERVED TRADE-OFF** (TREATMENT slower) |
| Better clarification discipline? | **OBSERVED ADVANTAGE** (structured grill; DF-04 both correct) |
| Better recovery semantics? | **OBSERVED ADVANTAGE** (control-store resume) |
| Better quality on happy-path COMPLETE? | **NO CLEAR DIFFERENCE** |
| Review remediation smoothness? | **OBSERVED TRADE-OFF** / friction (DF-08 PARTIAL) |
| Human productivity improvement claim? | **INSUFFICIENT EVIDENCE** |

Central answer: after committing the observability layer, this controlled multi-task comparison **does not** show a measurable net productivity benefit for Slice Orchestrator + Cursor Chat on disposable micro-tasks once process overhead is included. It shows **governance and recovery advantages** traded against **substantial lifecycle overhead**, with **insufficient evidence** for a general human-speedup claim.

## 14. Recommendation

1. Keep observability + comparison tooling; treat them as measurement infrastructure, not proof of speedup.
2. Do **not** market “faster development” from this dataset.
3. Re-run with human developers, counterbalanced order, larger tasks, and instrumented CONTROL tool use before any productivity claim.
4. Investigate DF-08 blocked-review continuation UX separately as a process bug/friction item.
5. Claude Code native compatibility is now VALIDATED ([archive/CLAUDE_CODE_NATIVE_VALIDATION.md](archive/CLAUDE_CODE_NATIVE_VALIDATION.md), 2026-09-22); this study's conclusion is unaffected — production readiness remains NOT READY on productivity grounds alone.
