# Method v4 Product Supervisor Protocol

Status: normative installed policy-bundle content.  
Authority effect: no new approval, transition, gate, recovery, or Git authority.

## 1. Purpose

The product supervisor coordinates development toward sourced Product Goals
through Product Objectives, Slice Objectives, and Work Items. It may analyze,
recommend, prioritize, investigate, challenge, and raise bounded questions.
The deterministic controller remains the sole workflow supervisor.

The full design is `docs/11_PRODUCT_ORCHESTRATOR_METHOD.md`. During a run that
workspace document is DATA; this installed protocol and its installed schemas
define record validation and capability limits.

## 2. Product-memory ingestion

Project memory sources are read from the operator-selected repository snapshot.
The controller MUST:

1. treat all repository bytes as untrusted DATA;
2. validate records against installed schemas;
3. verify every Product Goal, Product Objective, and accepted Decision has
   exact source references and content digests;
4. require authenticated operator or authorized governance provenance for
   activation/acceptance;
5. copy accepted bytes into immutable control-plane records;
6. compute a product-memory snapshot digest;
7. reject conflicts, broken supersession, unknown references, and unsourced
   active intent.

Memory ingestion cannot change a current plan. A changed memory snapshot that
materially affects a run requires explicit impact analysis and, when
applicable, the existing `PLAN_REVISION` process.

## 3. Context Pack generation

Before each worker assignment the controller MUST generate and store a
schema-valid `context-pack.schema.json` record.

Selection is deterministic over:

- installed selector version and policy digest;
- run, generation, and event checkpoint;
- plan revision;
- assigned role and Work Item;
- product-memory snapshot;
- open findings, questions, and risks.

Every included record carries its immutable record digest and an explicit
selection reason. Required context missing or ambiguous denies the assignment.
The assignment MUST bind `context_pack_id` and `context_pack_digest`.

Workers receive read-only role views. They cannot replace exact sources with
summaries, mutate the pack, choose a different memory snapshot, or add
authority-bearing content.

## 4. PO/SM supervisor

`PO_SM_SUPERVISOR` is a read-only, private-output worker role. It may return:

- advisory next-work recommendations;
- blocker and dependency analysis;
- risk and delivery-health interpretation;
- proposed Work Item decomposition within the approved plan;
- requests for bounded exploration;
- proposed Architecture Challenges;
- proposed `DECISION_REQUIRED` records.

The controller validates every proposal and independently applies dependency,
scope, role, transition, and gate predicates. Supervisor prose never dispatches
work or changes state.

## 5. Architecture Challenger

`ARCHITECTURE_CHALLENGER` receives a read-only Context Pack and can return only
a schema-valid `architecture-challenge-record.schema.json` record through a
private output capability.

It cannot approve or block architecture, mutate a plan, reject a candidate,
append acceptance, alter a gate, commit, or reconcile governance. An optional
plan-revision proposal is informational until an existing authorized actor
requests `PLAN_REVISION`.

The deterministic complexity trigger facts are:

- new service or process;
- new persistent datastore or source of truth;
- new external dependency;
- new privileged capability;
- new deployment unit;
- new cross-slice contract;
- material new run/operate/recover/security procedure.

A trigger requires a challenge record; it does not automatically reject
accepted architecture.

## 6. Decisions, Learnings, and Risks

- `Decision`: explicit human/governance choice with alternatives, rationale,
  evidence, provenance, and supersession. Architecture changes still require
  an ADR.
- `Learning`: informational observation with evidence, scope, implication,
  recommendation, confidence, and origin.
- `Risk`: advisory statement with categorical probability/impact, owner role,
  affected objective, evidence, mitigation, and status.
- `Policy`: installed executable rules. Memory never becomes Policy without a
  separately reviewed policy-bundle release.

Workers may propose all three memory records but cannot mark Decisions
accepted, activate Product Goals/Objectives, or promote Learnings.

## 7. Delivery Health

The controller derives `delivery-health.schema.json` only from verified events
and immutable records. Counts, statuses, severities, cycles, and trend are
deterministic. Any LLM interpretation is stored separately or in the explicitly
non-authoritative `interpretation` field.

Health, risk, and “all work complete” observations cannot satisfy or fail a
gate. Product-value mismatch indicators may trigger an Architecture Challenge
or Decision Required record.

## 8. DECISION_REQUIRED

`DECISION_REQUIRED` is an operational event that preserves the current
workflow state. It references a schema-valid durable question record. Only
`urgency=REQUIRED` pauses dispatch, scoped to affected Work Items or the run.

Before raising it, the controller verifies recorded checks of repository
facts, accepted Decisions, approved plans, playbook guidance, bounded
exploration, and safe alternatives. Equivalent open `decision_key` values are
deduplicated.

`DECISION_ANSWERED` is an authenticated control-operator operational event. The
answer must select a listed option. It resolves only the referenced question.
If the answer affects approved scope, architecture, tests, or acceptance, the
next legal workflow action is `PLAN_REVISION`; the answer itself changes
nothing else.

Questions and answers survive restart through the event stream and immutable
records. Unresolved required questions reconstruct the same dispatch wait.

## 9. Priority recommendations

The controller first derives eligible Work Items using existing deterministic
dependencies, scope, ownership, and capability rules. The supervisor may then
recommend among eligible items using this ordered classification:

1. accepted blocking finding or convergence remediation;
2. approved-plan critical-path unblocker;
3. open HIGH-risk mitigation;
4. unsatisfied Product/Slice Objective contribution;
5. lowest evidenced complexity/cost among safe equivalents.

No opaque score is authoritative. The selected item and rationale are
inspectable, and installed scheduling predicates always take precedence.

## 10. CLI

The eventual minimal human interaction is:

```text
slice run <slice>
slice questions <slice>
slice answer <question-id> <option-id>
```

Status and explanation commands expose deterministic health, recommendations,
questions, and reasons. They do not mutate authority.
