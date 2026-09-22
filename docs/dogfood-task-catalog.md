# Dogfood Task Catalog

**Purpose**: Small repeatable disposable-task set for observability and productivity comparison.  
**Constraint**: Do **not** use production repositories for initial experiments.

Each task defines objective, repository fixture, starting revision policy, expected scope, tests, complexity, comparison protocol, and success criteria.

---

## Shared fixture

| Field | Value |
|---|---|
| Base fixture | Disposable git repo seeded like `tests/workspace_support.seed_passing_workspace` |
| Suggested root | `evidence/dogfood-tasks/fixtures/` (local; runtime trees gitignored when under evidence disposables) |
| Starting revision | Fresh commit after fixture seed; record OID per experiment |
| Comparison protocol | [productivity-protocol.md](productivity-protocol.md) |

---

## Tasks

### DF-01 — Small bug fix

| Field | Value |
|---|---|
| Objective | Fix off-by-one in `add(a, b)` helper returning `a + b + 1` |
| Repository | Disposable calc fixture |
| Starting revision | Seed commit with deliberate bug + failing test |
| Expected scope | Single module + its unit test |
| Tests | `test_add` must pass |
| Complexity | S (1) |
| Success criteria | Bug fixed; tests green; orchestrated export shows test receipt |

### DF-02 — Feature addition

| Field | Value |
|---|---|
| Objective | Add `multiply(a, b)` with unit test |
| Repository | Disposable calc fixture |
| Starting revision | Clean seed |
| Expected scope | `calc` module + tests |
| Tests | `test_multiply` |
| Complexity | S (1) |
| Success criteria | Feature present; tests pass; COMPLETE reachable under orchestrator |

### DF-03 — Refactoring

| Field | Value |
|---|---|
| Objective | Extract pure helper without behavior change |
| Repository | Disposable calc fixture with duplicated logic |
| Starting revision | Seed with duplication |
| Expected scope | Refactor only; tests unchanged behaviorally |
| Tests | Existing suite remains green |
| Complexity | M (2) |
| Success criteria | No functional delta; review finds no regressions |

### DF-04 — Incomplete requirements

| Field | Value |
|---|---|
| Objective | Ambiguous “improve calculator UX” with no acceptance tests specified |
| Repository | Disposable calc fixture |
| Starting revision | Clean seed |
| Expected scope | Clarification before implementation |
| Tests | None until clarified |
| Complexity | M (3) |
| Success criteria | Orchestrator surfaces grill/clarification; manual run records questions; no silent scope invention in comparison notes |

### DF-05 — Clarification required

| Field | Value |
|---|---|
| Objective | “Support division” without specifying integer vs float or zero handling |
| Repository | Disposable calc fixture |
| Starting revision | Clean seed |
| Expected scope | Clarification record then implementation |
| Tests | Agreed after clarification |
| Complexity | M (2) |
| Success criteria | Human question + answer recorded; metrics show questions ≥ 1 when instrumentation present |

### DF-06 — Interrupted task

| Field | Value |
|---|---|
| Objective | Mid-implementation pause then resume |
| Repository | Disposable feature task (DF-02 variant) |
| Starting revision | Clean seed |
| Expected scope | Same as feature add |
| Tests | Feature tests |
| Complexity | M (2) |
| Success criteria | `RUN_PAUSED`/`RUN_RESUMED` or operator pause attested; timeline shows gap; recovery continues |

### DF-07 — Failed test and remediation

| Field | Value |
|---|---|
| Objective | Implement feature that initially fails control tests, then remediate |
| Repository | Disposable fixture |
| Starting revision | Clean seed |
| Expected scope | Implementation + fix |
| Tests | Control pytest suite |
| Complexity | M (3) |
| Success criteria | Failed receipt then passed receipt; remediation/retry metrics non-zero |

### DF-08 — Review finding

| Field | Value |
|---|---|
| Objective | Produce candidate that review blocks (e.g., missing edge case), then remediate |
| Repository | Disposable fixture |
| Starting revision | Clean seed |
| Expected scope | Implementation + remediation |
| Tests | Suite green after remediation |
| Complexity | M (3) |
| Success criteria | `REVIEW_BLOCKED` → remediation → later accept; findings counted when recorded |

### DF-09 — Worker failure / unavailable backend

| Field | Value |
|---|---|
| Objective | Drive assignment while worker backend unavailable |
| Repository | Disposable fixture |
| Starting revision | Clean seed |
| Expected scope | Failure handling only |
| Tests | N/A |
| Complexity | M (2) |
| Success criteria | `WORKER_UNAVAILABLE` or `WORKER_FAILED` stop code; metrics reflect failure; no false COMPLETE |

### DF-10 — Multi-session recovery

| Field | Value |
|---|---|
| Objective | Park mid-slice; new session resumes from control store only |
| Repository | Disposable fixture |
| Starting revision | Clean seed; park after implementation assign |
| Expected scope | Resume + complete |
| Tests | Suite after resume |
| Complexity | L (4) |
| Success criteria | Same `run_id`/sequence recovered; timeline continuous; export integrity holds |

---

## Aggregate success criteria for productivity claims

* All DF-01…DF-10 executed at least once in orchestrated mode with exports
* Manual counterparts recorded for DF-01…DF-05 minimum
* Comparison reports archived with missing data explicit
* No productivity conclusion until multi-task protocol satisfied
