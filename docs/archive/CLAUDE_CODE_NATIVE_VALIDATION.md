# Claude Code Native Live Validation

**Date**: 2026-09-22
**Validation timestamp (UTC)**: `2026-09-22T07:47:01Z` → `2026-09-22T07:52:xxZ`
**Evidence class**: `CLAUDE_CODE_INVOCATION`
**Method**: Disposable slices `S999`/`S998`/`S997`/`S996`/`S995` driven **only** via Claude Code's native MCP tool calls (the `mcp__slice-orchestrator__*` tools loaded and invoked directly by Claude Code in this session, no subprocess, no `cursor-agent`, no dummy worker used as proof).

This mirrors the protocol and evidence structure of [CURSOR_CHAT_LIVE_VALIDATION.md](CURSOR_CHAT_LIVE_VALIDATION.md) so both hosts are comparable.

---

## 1. Connection and Discovery

| Check | Result | Evidence |
|---|---|---|
| MCP server connected | PASS | `slice-orchestrator` tools loaded and callable in Claude Code session |
| Tool discovery | PASS | 14 `slice_*` tools available: `slice_context`, `slice_dispatch`, `slice_finalize`, `slice_gate`, `slice_grill`, `slice_plan`, `slice_record_result`, `slice_remediate`, `slice_report`, `slice_request_review`, `slice_run_tests`, `slice_start`, `slice_status`, `slice_work_list` |
| Project MCP config | PASS | `.mcp.json` present, no separate `claude` CLI auth required |

---

## 2. Real Claude Code MCP Tool Invocations

Every call below was made through the live `mcp__slice-orchestrator__*` tools inside this Claude Code session, with `host="claude-code"` passed on mutating calls.

### Run A — `S999` (basic read/plan cycle, real orchestrator repo)

| # | Tool | Key result |
|---|---|---|
| 1 | `slice_start` | `run_id=90174bb9-...`, state=`PLANNING` |
| 2 | `slice_context` | objectives/role_context/scope_manifest returned |
| 3 | `slice_plan` | `plan_id=S999-plan-v1`, state=`PLAN_READY` |
| 4 | `slice_work_list` | 0 work items (plan had no items) |
| 5 | `slice_status` | `state=PLAN_READY`, legal transitions listed |
| 6 | `slice_report` | `verdict=IN_PROGRESS` |

### Run B — `S998` (disposable repo, test-modification guard)

Disposable repo seeded with a **pre-existing** `tests/test_calc.py`. Full path: `slice_grill → slice_plan → slice_dispatch(ARCHITECTURE_REVIEWER) → slice_record_result → slice_dispatch(IMPLEMENTER) → slice_record_result → slice_run_tests`.

`slice_run_tests` was **correctly rejected**:
```text
AUTHORITATIVE_TEST_MODIFIED: Test file 'tests/test_calc.py' present in baseline was modified without plan re-approval
```
This is a governance guard working as intended (anti test-tampering), not a defect.

### Run C — `S997` (disposable repo, deleted-baseline-file guard)

Retried with a repo whose baseline committed an empty `tests/.gitkeep`. Implementer deleted it while adding `tests/test_calc.py`. `slice_run_tests` was again **correctly rejected**:
```text
AUTHORITATIVE_TEST_DELETED: Test file 'tests/.gitkeep' present in baseline was deleted in candidate tree
```
Second confirmation that the control plane enforces test-integrity invariants live from Claude Code, exactly as it would from Cursor.

### Run D — `S996` / `S995` (clean disposable repo, lifecycle to gate — malformed plan scope)

Baseline with **no** pre-existing test file. Sequence executed successfully through `slice_gate`, which then rejected finalize:
```text
Scope or protected path check failed: Path modification 'src/calc.py' (status M) is not authorized by scope manifest
```
Initial root-cause note in this report claimed this was caused by a hardcoded path in `slice_orchestrator/dispatch.py:111-113,170-173`. **That was incorrect** — those values only populate the informational `scope_manifest` shown inside a role's context pack (advisory context for the IMPLEMENTER/ARCHITECTURE_REVIEWER view) and are **not** read by `slice_gate`. The real cause: the `slice_plan` calls in runs `S996`/`S995` passed `allowed_scope`/`files` keys, which `slice_plan` silently ignores. The gate reads `PLAN.scope_manifest.allow_paths` (see `slice_orchestrator/tools.py:395` and `slice_orchestrator/gates.py:387-425`) — since no `allow_paths` were ever persisted, the effective scope was empty and every modified path was correctly denied. This was an **operator/caller error in this validation**, not a control-plane defect. Corrected and re-run as Run E below.

### Run E — `S994` (clean disposable repo, correct `scope_manifest.allow_paths`, full lifecycle to COMPLETE)

Plan submitted with the tool's actual expected shape:
```json
{"scope_manifest": {"allow_paths": [
  {"pattern": "src/calc.py", "allowed_operations": ["modify"]},
  {"pattern": "tests/test_calc.py", "allowed_operations": ["add"]}
]}}
```

| # | Tool | Key result | Persisted? |
|---|---|---|---|
| 1 | `slice_start` | `run_id=6ecf9997-...`, state=`PLANNING` | Yes |
| 2 | `slice_plan` | `plan_id=S994-plan-v1`, state=`PLAN_READY` | Yes |
| 3 | `slice_dispatch` (ARCHITECTURE_REVIEWER) | assignment issued, state=`ARCHITECTURE_REVIEW` | Yes |
| 4 | `slice_record_result` (arch APPROVED) | state=`ARCHITECTURE_APPROVED` | Yes |
| 5 | `slice_dispatch` (IMPLEMENTER) | assignment issued, state=`IMPLEMENTATION` | Yes |
| 6 | `slice_record_result` (implementer) | state=`IMPLEMENTATION_READY_FOR_REVIEW`, candidate captured | Yes |
| 7 | `slice_run_tests` | **`tests_passed=true`**, `receipt_id=receipt-87aa5fc3` | Yes (HMAC receipt) |
| 8 | `slice_request_review` | reviewer=`claude-code-adversarial-reviewer-S994`, assignment issued | Yes |
| 9 | `slice_record_result` (review APPROVED) | state=`COMMIT_READY` | Yes |
| 10 | `slice_gate` | **`passed=true`**, `candidate_tree_oid=sha1:81d20f09...` | Evaluated |
| 11 | `slice_finalize` | **`finalized=true`, state=`COMPLETE`**, `commit_oid=sha1:81d20f09...` | Yes (`COMMIT_RECORDED`→`GOVERNANCE_RECONCILED`) |
| 12 | `slice_status` | `state=COMPLETE`, `is_terminal=true`, `sequence=21` | Read |
| 13 | `slice_report` | `verdict=COMPLETE`, `total_events=21`, `tests_passed=1`, `commits_made=1` | Read |

Real code was authored by the Implementer role and independently exercised by the authoritative `slice_run_tests` control-plane test runner (not a self-reported result): `src/calc.py::multiply` + `tests/test_calc.py::test_multiply`. Event count (21) and structure exactly mirror Cursor's `S930` evidence.

Note: `commit_oid` in this control plane is a content-addressed **candidate tree digest** (`git cat-file -t` confirms it is a `tree` object), not a live `git commit` applied to the disposable repo's branch — the same terminology and mechanism used in the Cursor `S930` evidence. Actual git-commit application is out of scope for this finding.

---

## 3. What This Proves

```text
CLAUDE CODE MCP CONNECTION: PASS
TOOL DISCOVERY (14 tools): PASS
REAL CLAUDE CODE TOOL INVOCATION: PASS
FULL LIFECYCLE PLANNING → ARCHITECTURE REVIEW → IMPLEMENTATION → AUTHORITATIVE TEST (HMAC RECEIPT)
  → ADVERSARIAL REVIEW → GATE → FINALIZE → COMPLETE: PASS (S994)
GOVERNANCE GUARDS (test tampering / deletion / scope enforcement) ENFORCED IDENTICALLY TO CURSOR: PASS
```

Claude Code natively lists, connects to, and drives `slice-orchestrator` end-to-end, reaching the same terminal `COMPLETE` state as Cursor's `S930` validation, with a real HMAC test receipt and 21 persisted events.

---

## 4. Follow-up Observation (Not a Blocker)

`slice_plan`'s tool description does not document the exact `scope_manifest.allow_paths` shape it expects, and silently ignores unrecognized keys (`allowed_scope`, `files`) instead of validating or erroring. This caused the false-positive "hardcoded path" diagnosis in an earlier draft of this report (Runs D). Suggested improvement: either validate the `plan` payload against a JSON schema and reject unknown/missing `scope_manifest.allow_paths`, or document the expected shape in the tool's MCP description so callers on any host don't silently produce an empty scope.

---

## 5. What This Does Not Prove

- Production readiness of the scope-manifest mechanism beyond this single successful `COMPLETE` run
- A full Claude Code process restart / persistence-after-restart (not exercised this session; state persistence *within* the session, across independent tool calls with no shared chat-derived state, was exercised repeatedly and is consistent with the mechanism validated for Cursor)
- Real `git commit` application (the control plane records a candidate-tree digest, matching Cursor's evidence terminology)

---

## 6. Verdicts

```text
CLAUDE CODE NATIVE CONNECTION: PASS
TOOL DISCOVERY: PASS
REAL CLAUDE CODE TOOL INVOCATION: PASS
COMPLETE MCP-ONLY LIFECYCLE TO COMPLETE WITH REAL TEST RECEIPT: PASS (S994)
GOVERNANCE GUARD PARITY WITH CURSOR: PASS
```

**Jalon B exit criteria** ([roadmap.md](../roadmap.md)):
- [x] Claude Code lists and connects to `slice-orchestrator`
- [x] Slice lifecycle tools succeed when invoked from Claude Code, up to and including `slice_finalize` → `COMPLETE`
- [x] No duplicated orchestration logic for Claude
