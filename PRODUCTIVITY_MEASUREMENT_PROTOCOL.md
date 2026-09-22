# Productivity Measurement Protocol

**Status**: PROTOCOL DEFINED — initial multi-task study executed (see PRODUCTIVITY_STUDY_RESULTS.md); productivity claim still NOT AUTHORIZED  
**Comparison schema**: `productivity-comparison-v1`  
**CLI**: `slice compare --manual manual-run.json --orchestrated orchestrated-run.json`

---

## 1. Purpose

Compare:

```text
Cursor Chat alone
Cursor Chat + Slice Orchestrator
```

on **comparable disposable tasks**. A single run must not claim causality or productivity improvement.

---

## 2. Comparable fields

| Field | Notes |
|---|---|
| `task_identifier` | Stable task id from dogfood catalog |
| `task_complexity` | Catalog rating (S/M/L or 1–5) |
| `starting_revision` / `final_revision` | Git OIDs |
| `elapsed_time_ms` | Wall clock for task attempt |
| `human_active_time_ms` | Operator-attested or UNAVAILABLE |
| `human_waiting_time_ms` | From orchestrator metrics or UNAVAILABLE |
| `number_of_questions` | Human questions asked |
| `number_of_interruptions` | Pauses / context switches |
| `number_of_tool_calls` | IDE/MCP tool calls when measured |
| `number_of_context_reconstructions` | Context pack / re-brief events |
| `tests_added` / `tests_passed` | Test deltas and passes |
| `review_findings` / `remediation_cycles` | Quality loop |
| `defects_introduced` / `defects_detected` | Explicit; else UNAVAILABLE |
| `final_outcome` | COMPLETE / FAILED / abandoned |
| `developer_assessment` | Qualitative only; DECLARED |

Missing values must be `UNAVAILABLE`, never imputed.

---

## 3. Protocol steps

1. Select a task from [DOGFOOD_TASK_CATALOG.md](DOGFOOD_TASK_CATALOG.md).
2. Reset disposable repository to the listed starting revision.
3. Execute **manual** Cursor Chat attempt; record `manual-run.json`.
4. Reset to the same starting revision.
5. Execute **orchestrated** attempt via Slice Orchestrator MCP/CLI; `slice export` then map to comparison JSON (or fill `orchestrated-run.json` from export metrics).
6. Run `slice compare`.
7. Archive both JSON files + comparison output under a versioned evidence directory (not production repos).
8. Repeat across multiple tasks before any productivity claim.

---

## 4. Report contents

The comparison report includes:

* absolute values per field
* absolute and percent differences where both sides are numeric
* explicit `missing_data`
* confounding factors (familiarity, fatigue, model/version drift, single-run noise)
* qualitative observations
* hard-coded non-conclusion: no unsupported productivity claim

---

## 5. Confounding factors (minimum set)

* Single-run comparison cannot establish causality
* Task familiarity may differ between attempts
* Model / IDE / MCP versions may differ
* Human active time is often operator-attested (DECLARED)
* Orchestrator instrumentation may be richer than manual logging

---

## 6. When may we claim improvement?

Only after:

* ≥ the dogfood catalog’s success criteria for multi-task comparison
* consistent directionality across task types
* explicit handling of UNAVAILABLE fields
* no reliance on worker DECLARED summaries

Until then:

```text
PRODUCTIVITY CLAIM: NOT AUTHORIZED
```
