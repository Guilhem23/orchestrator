# Cursor Chat Live Validation

**Date**: 2026-09-11  
**Validation timestamp (UTC)**: `2026-09-11T14:35:25Z` → `2026-09-11T14:36:36Z`  
**Evidence class**: `CURSOR_CHAT_INVOCATION`  
**Namespace**: `project-0-orchestrator-slice-orchestrator`  
**namespaceStatus at start**: `ready`  
**Method**: Disposable slice `S930` driven **only** via Cursor Chat MCP tools (`CallDynamicTool`). No `controller.step()`, no CLI worker, no `cursor-agent`, no dummy worker used as proof.

---

## 1. Connection and Discovery

| Check | Result | Evidence |
|---|---|---|
| MCP server connected | PASS | `namespaceStatus: ready` |
| Server identifier | PASS | `project-0-orchestrator-slice-orchestrator` / `slice-orchestrator` |
| Tool discovery | PASS | All 13 `slice_*` tools listed in live catalog |
| Disconnect during run | None | Tools remained callable through finalize + recovery queries |

Discovered tools:

```text
slice_start, slice_context, slice_grill, slice_plan, slice_work_list,
slice_dispatch, slice_record_result, slice_run_tests, slice_request_review,
slice_gate, slice_finalize, slice_status, slice_report
```

---

## 2. Disposable Project

| Field | Value |
|---|---|
| `repo_dir` | `/home/guilhem/workspace/orchestrator/evidence/cursor-live-validation/disposable-S930` |
| Slice | `S930` |
| Objective | Add `multiply(a,b)` to `calc` with unit test |
| Base commit | `sha1:8412faaf423bd3d880425c4423974151a07dbb1e` |
| Control home | `.../disposable-S930/.orchestrator_slice` |
| `host` metadata | `cursor` (observational only) |

Candidate edits (Chat file edits, not MCP):

- `src/calc.py` — added `multiply`
- `tests/test_calc.py` — added `test_multiply`

---

## 3. Real Cursor MCP Tool Invocations

Every step below was invoked through the live Cursor MCP namespace.

| # | Tool | Key result | Persisted? |
|---|---|---|---|
| 1 | `slice_start` | `run_id=1d2826ca-2fc3-473c-b0a2-8cebd27ae725`, state=`PLANNING` | Yes (`RUN_OPENED`) |
| 2 | `slice_context` | objectives present; state=`PLANNING` | Read |
| 3 | `slice_grill` | prerequisite `test_suite_configured=pass` | Clarification record |
| 4 | `slice_plan` | `plan_id=S930-plan-v1`, state=`PLAN_READY`, 1 work item | Yes (`PLAN_PERSISTED`) |
| 5 | `slice_work_list` | `S930-WI-1` READY | Read |
| 6 | `slice_dispatch` (ARCHITECTURE_REVIEWER) | `assignment_id=36d64347-...`, state=`ARCHITECTURE_REVIEW` | Yes |
| 7 | `slice_record_result` (arch APPROVED) | state=`ARCHITECTURE_APPROVED` | Yes |
| 8 | `slice_dispatch` (IMPLEMENTER / `S930-WI-1`) | `assignment_id=152dad79-...`, state=`IMPLEMENTATION` | Yes |
| 9 | `slice_record_result` (implementer) | state=`IMPLEMENTATION_READY_FOR_REVIEW`, candidate captured | Yes |
| 10 | `slice_run_tests` | `tests_passed=true`, `receipt_id=receipt-6e4e7619` | Yes (HMAC receipt) |
| 11 | `slice_request_review` | reviewer=`cursor-adversarial-reviewer-S930`, `assignment_id=0bc2a45b-...` | Yes |
| 12 | `slice_record_result` (review APPROVED) | state=`COMMIT_READY` | Yes (`REVIEW_ACCEPTED`) |
| 13 | `slice_gate` | `passed=true` | Evaluated |
| 14 | `slice_finalize` | `finalized=true`, state=`COMPLETE`, commit_oid=`sha1:94d7128d...` | Yes (`COMMIT_RECORDED`…`GOVERNANCE_RECONCILED`) |
| 15 | `slice_report` | `final_state=COMPLETE`, `total_events=21` | Read |

### Identifiers

| Kind | Value |
|---|---|
| Run ID | `1d2826ca-2fc3-473c-b0a2-8cebd27ae725` |
| Plan ID | `S930-plan-v1` |
| Work item | `S930-WI-1` |
| Arch assignment | `36d64347-11a5-4989-9bb4-5e3b10cb45ce` |
| Impl assignment | `152dad79-0696-4c5c-94c5-082625b16178` |
| Review assignment | `0bc2a45b-e05b-4db5-a884-5fefc0a6a9c8` |
| Test receipt | `receipt-6e4e7619` |
| Review record | `rev-410a820b` |
| Candidate / commit OID | `sha1:94d7128d9cc8cec59b8e956393bdcc29c38e737d` |

---

## 4. Control Database Evidence

Path: `evidence/cursor-live-validation/disposable-S930/.orchestrator_slice/state.db`

Queried after finalize (Python `sqlite3` API):

| Table | Count / notes |
|---|---|
| `events` | **21** events for run `1d2826ca-...` |
| `assignments` | **3** rows, all `CONSUMED` |
| `records/` | plan, objective, work item, receipt, review, clarification |

Event sequence (authoritative):

```text
1  RUN_OPENED
2  PLAN_PERSISTED
3  CONTEXT_PACK_GENERATED
4  ASSIGNMENT_ISSUED
5  ARCHITECTURE_REVIEW_ASSIGNED
6  ASSIGNMENT_CONSUMED
7  ARCHITECTURE_APPROVED
8  CONTEXT_PACK_GENERATED
9  ASSIGNMENT_ISSUED
10 IMPLEMENTATION_ASSIGNED
11 ASSIGNMENT_CONSUMED
12 IMPLEMENTATION_CONTEXT_CHECKPOINTED
13 CANDIDATE_CAPTURED
14 CONTEXT_PACK_GENERATED
15 ASSIGNMENT_ISSUED
16 ADVERSARIAL_REVIEW_ASSIGNED
17 ASSIGNMENT_CONSUMED
18 REVIEW_ACCEPTED
19 COMMIT_RECORDED
20 GOVERNANCE_STARTED
21 GOVERNANCE_RECONCILED
```

Multiple event payloads include `"host_metadata": "cursor"` without granting authority.

---

## 5. Persistence / Session Recovery Simulation

A full Cursor Desktop process restart was **not** performed. Recovery was validated by treating subsequent MCP calls as a **new logical Cursor session**: only `slice` + `repo_dir` were supplied (no reliance on chat history for authoritative state).

| Recovery call | Result |
|---|---|
| `slice_status` | `exists=true`, `state=COMPLETE`, `run_id` match, `sequence=21`, `last_event=GOVERNANCE_RECONCILED`, `is_terminal=true` |
| `slice_context` | Restored plan summary, work items, same `run_id`, terminal state |
| `slice_report` (prior) | 21-event history from store |

Recovery source: persisted `.orchestrator_slice/state.db` + records — **not** chat transcript.

```text
PERSISTENCE: PASS
SESSION RECOVERY: PASS (logical new-session via MCP; not a full IDE process restart)
```

---

## 6. What This Does Not Prove

- Production readiness of the uncommitted packaging baseline  
- Claude Code native mode (still deferred)  
- Statistical productivity benefit  
- Literal Cursor application restart / crash recovery (only logical new-session MCP recovery)

---

## 7. Verdicts

```text
CURSOR MCP CONNECTION: PASS
TOOL DISCOVERY: PASS
REAL CURSOR TOOL INVOCATION: PASS
COMPLETE MCP LIFECYCLE: PASS
PERSISTENCE: PASS
SESSION RECOVERY: PASS
PRODUCTION READINESS: NOT READY
```

### Rationale

- **PASS** for connection, discovery, real Cursor tool calls, complete MCP-only lifecycle to `COMPLETE`, and control-plane persistence with recoverable status/context.  
- **NOT READY** for production: MCP sources remain largely uncommitted; this is one disposable validation; full IDE restart not exercised; broader hardening/commit baseline still required.
