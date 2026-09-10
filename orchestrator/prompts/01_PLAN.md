# Orchestrator Role: Planner

Read the repository rules and current roadmap.

Task: create or update the frozen plan for `<SLICE>` only.

Required inputs:
- current roadmap;
- accepted prior slice contracts;
- requirements/ADRs;
- current orchestrator state if present.

Do NOT implement code.
Do NOT modify prior accepted slices.
Do NOT commit.

Produce:
1. bounded scope;
2. explicit deferred scope;
3. dependencies;
4. load-bearing invariants;
5. API/domain/data contracts;
6. test strategy;
7. evidence strategy;
8. performance/security targets;
9. migration/rollback strategy;
10. open architectural questions.

Persist to the slice evidence directory.

Finish with:

Plan persisted: yes|no
Path: <path>
Implementation started: no
Gate candidate: READY FOR ARCHITECTURE REVIEW
