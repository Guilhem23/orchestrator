# Productivity Study Results

**Status**: EXECUTED on disposable fixtures  
**Protocol**: [PRODUCTIVITY_MEASUREMENT_PROTOCOL.md](PRODUCTIVITY_MEASUREMENT_PROTOCOL.md)  
**Catalog**: [DOGFOOD_TASK_CATALOG.md](DOGFOOD_TASK_CATALOG.md)  
**Raw data**: [PRODUCTIVITY_STUDY_DATA.json](PRODUCTIVITY_STUDY_DATA.json)  
**Analysis**: [PRODUCTIVITY_STUDY_ANALYSIS.md](PRODUCTIVITY_STUDY_ANALYSIS.md)  
**Observability baseline**: `f1aa3443ac7397940a4bcc7b10ccd4181bf0ef6d`

## Conditions

| Condition | Definition |
|---|---|
| CONTROL | Cursor Chat-style direct implementation (no Slice Orchestrator control plane) |
| TREATMENT | Same developer agent + Slice Orchestrator tools API (control-plane lifecycle) |

Developer, model session, fixture family, and acceptance intent held constant. CONTROL always ran before TREATMENT for each task (order effect documented).

## Per-task outcomes

| Task | Complexity | CONTROL outcome | CONTROL elapsed ms | TREATMENT outcome | TREATMENT elapsed ms | TREATMENT tool_calls |
|---|---|---|---|---|---|---|
| DF-01 Small bug fix | 1 | COMPLETE | 155 | COMPLETE | 2723 | 14 |
| DF-02 Feature addition | 1 | COMPLETE | 163 | COMPLETE | 2708 | 14 |
| DF-03 Refactoring | 2 | COMPLETE | 164 | COMPLETE | 2714 | 14 |
| DF-04 Incomplete requirements | 3 | ABANDONED_PENDING_CLARIFICATION | 159 | ABANDONED_PENDING_CLARIFICATION | 585 | 4 |
| DF-05 Clarification required | 2 | COMPLETE | 154 | COMPLETE | 2706 | 14 |
| DF-06 Interrupted task | 2 | COMPLETE | 152 | COMPLETE | 2942 | 14 |
| DF-07 Failed test + remediation | 3 | COMPLETE | 299 | COMPLETE | 3034 | 15 |
| DF-08 Review finding | 3 | COMPLETE | 152 | PARTIAL | 1926 | 12 |
| DF-09 Worker failure / unavailable | 2 | FAILED | 148 | FAILED | 1183 | 8 |
| DF-10 Multi-session recovery | 4 | COMPLETE | 149 | COMPLETE | 2952 | 15 |

## Aggregate (COMPLETE–COMPLETE pairs only, n=7)

| Metric | Value |
|---|---|
| Mean elapsed delta (T − C) | +2649 ms |
| Median elapsed delta (T − C) | +2568 ms |
| Mean ratio T/C | ~16.8× |
| Median ratio T/C | ~17.6× |

Do **not** interpret these ratios as human productivity claims. Both sides are agent-automated on tiny fixtures; TREATMENT includes full governance lifecycle overhead.

## Quality / process highlights

* DF-04: both conditions correctly refused silent scope invention.
* DF-07: both recorded a remediation cycle after a failing test path.
* DF-09: both ended FAILED without false COMPLETE; TREATMENT exported failure-path metrics.
* DF-06 / DF-10: TREATMENT exercised pause/resume and context reconstruction via control store.
* DF-08 TREATMENT: PARTIAL — review-blocked remount path did not reach finalize in this harness.

## Exports

All ten TREATMENT runs produced export digests (recorded in `PRODUCTIVITY_STUDY_DATA.json`). Runtime packages live under gitignored `evidence/dogfood-tasks/study-runs/`.

## Claim authorization

```text
PRODUCTIVITY CLAIM: NOT AUTHORIZED
OVERALL PRODUCTIVITY CONCLUSION: OBSERVED TRADE-OFF / INSUFFICIENT EVIDENCE for human speedup
```
