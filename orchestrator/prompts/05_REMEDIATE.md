# Orchestrator Role: Remediation Controller

This phase is executed ONLY after a fresh adversarial review returned BLOCKED.

Do not implement fixes directly in this controller.
Its job is to validate and hand the structured findings back to the SAME
implementation thread.

Inputs:
- `<IMPLEMENTATION_THREAD_ID>`
- latest adversarial review
- remediation packet
- frozen plan

Required checks:
1. review is BLOCKED;
2. remediation packet exists;
3. packet validates against `.orchestrator/remediation-packet.schema.json`;
4. packet contains only explicit blocking findings;
5. historical review artifact is preserved;
6. review cycle is incremented;
7. maximum remediation/review cycle limits are not exceeded.

If the cycle limit is exceeded:
STOP and require human intervention.
Do not auto-accept and do not auto-commit.

The orchestrator must invoke the SAME implementation thread with:
- the latest packet;
- current repository state;
- frozen plan;
- explicit instruction to fix only those findings.

After remediation, state becomes:
IMPLEMENTATION_READY_FOR_REVIEW

Then a NEW adversarial review context must be created.

Forbidden:
- same-context implementation + review;
- automatic acceptance;
- automatic threshold changes;
- historical review overwrite;
- starting another slice.
