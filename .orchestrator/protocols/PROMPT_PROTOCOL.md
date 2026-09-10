@@
 Inputs:
 - immutable approved plan/scope export;
- implementation worker assignment ID;
- latest verified persistent IMPLEMENTATION role-context checkpoint;
 - authoritative remediation export when applicable.
@@
 Forbidden:
 - control-plane/Git metadata access;
 - modifying review/remediation authority;
 - self-approval, state mutation, governance, or commit.

Output:
- structured work result and a complete next role-context checkpoint. Do not
  assume this worker or chat will be available again.
@@
 Requirements:
 - inspect the candidate, Git identity, plan, tests, evidence, and packets
   directly;
- run in a new worker execution and one-use assignment for this review cycle;
