# Orchestrator Role: Governance Reconciliation

Run ONLY after an independent adversarial review returned APPROVED and before the next slice is planned.

Verify the accepted slice commit and current repository state.

Update only the current-state governance artifacts needed to reflect:
- slice complete;
- acceptance status;
- commit hash;
- next planned slice.

Preserve historical records.
Do not rewrite review history.
Do not change implementation behavior.
Do not start the next slice.
Do not commit unless explicitly requested by the orchestration workflow.

Keep unrelated IEEE/test knowledge-base state machines separate from Knowledge Fabric roadmap state.
