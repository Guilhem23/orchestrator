@@
Crash A while ownership is active and restart. Expected: controller B cannot
silently take over. An authenticated `slice resume` may continue the same run
only after proving A no longer holds the OS lock, verifying all records and the
last atomic boundary, and appending RUN_RESUMED with a new lease. Ambiguity
causes STOPPED and explicit recovery.
@@
 ### AT-16 — Concurrent slices cannot race one authoritative ref
@@
 - no commit contains an unreviewed merge of both candidates.

### AT-17 — Slice Run autonomously owns the lifecycle

Invoke `slice run S6` with deterministic fake worker adapters and no follow-up
human workflow commands.

Expected:
- one persistent run record/event stream owns PLAN through GOVERNANCE;
- the controller, not workers, selects every next legal operation;
- worker output cannot choose a state, reset a cycle, accept, or commit;
- the run reaches COMPLETE or an explicit policy STOPPED condition.

### AT-18 — Implementation survives backend/session loss

Checkpoint implementation work, then terminate Cursor/Claude/fake worker
processes and remove their session handles. Resume each case with a different
compatible backend.

Expected:
- workflow state, plan revision, counters, open findings, and prior evidence do
  not reset;
- the new assignment binds the latest verified role-context digest;
- the replacement receives enough persisted context to continue without chat
  history;
- `IMPLEMENTATION_WORKER_REASSIGNED` is appended;
- corrupt, incomplete, or mismatched context causes STOPPED.

### AT-19 — Every adversarial cycle uses a fresh worker

Block one candidate, remediate, and submit a second candidate. Attempt to reuse
the prior assignment, execution ID, worker-instance ID, output capability, and
backend session in separate cases.

Expected:
- every reuse is rejected;
- each cycle has a new one-use assignment, execution, worker instance, and
  sandbox;
- using the same backend/model is permitted only through a fresh invocation;
- no implementation transcript is required or writable by the reviewer.

### AT-20 — Human inspection, pause, and resume preserve authority

At every nonterminal state, invoke status/inspect, pause after an atomic
operation, terminate the CLI, and resume.

Expected:
- status/inspect reconstruct verified run context without mutation;
- pause/resume changes execution mode but not workflow state or counters;
- resume launches the next legal operation from persisted artifacts/state;
- no chat/session is required;
- an ambiguous in-flight Git/control operation fails closed to recovery.
