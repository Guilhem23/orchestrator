# Knowledge Fabric / Slice Orchestrator — Decision Memory

## D-001 — Vertical slices are the primary architectural delivery boundary
The Knowledge Fabric program is delivered through bounded vertical slices. A slice has explicit scope, acceptance criteria, evidence, adversarial review, and commit/governance gates.

## D-002 — Backend dependency order is authoritative
The backend order is:

`S1 → S2 → S3 → S4 → S5 → S8 → S9 → S6 → S10 → S7`

S11 is a parallel operational track after S5. S12 is the final external/customer boundary.

Search must not precede S8 authorization and S9 immutable releases.

## D-003 — UI is a cross-cutting consumer track, not a new backend slice
The UI track is UI-0 through UI-5. It consumes accepted backend contracts and must never duplicate authorization, governance, effective-view, release, search, or authority logic.

## D-004 — Canonical knowledge is immutable
Canonical records are never mutated to represent corrections. Governance is represented separately.

## D-005 — Governance is explicit and auditable
Corrections, approvals, ownership, releases, publication and privileged operations must be explicit and auditable.

## D-006 — One Effective Knowledge Resolver
There is one authoritative effective-view resolution engine. Other layers delegate to it and do not reimplement authority composition.

## D-007 — One Knowledge Serving layer
Knowledge Serving is the authoritative handoff layer from governed knowledge to clients/agents. Search and future RAG must not become alternate serving/resolution engines.

## D-008 — Authorization before candidate discovery
Authorization must happen before search, record discovery, graph traversal, provenance tracing, or release access. Unauthorized resource existence should be hidden where required by policy.

## D-009 — Search is candidate generation, not truth
Search returns candidates and relevance metadata. It does not decide authority, governance, or effective truth.

## D-010 — RAG is a reasoning layer, never an authority engine
RAG/agents consume authorized candidates, Knowledge Serving outputs, effective knowledge and provenance. They do not modify canonical knowledge or define authority.

## D-011 — Immutable releases are the bridge to Search/RAG
Search and later RAG consume immutable S9 releases, not mutable working KB state.

## D-012 — AuthorityLevel is categorical
AuthorityLevel must never be treated as a scalar ranking, numeric precedence, or “highest authority wins” rule.

## D-013 — RBAC, KB permissions, AuthorityLevel and ApprovalPolicy are separate concepts
They must not be collapsed into one hierarchy.

## D-014 — Trusted actor/workspace context is server-side
`workspace_id`, `actor_id`, roles and permissions are never model-controlled authority inputs.

## D-015 — S8 enterprise identity uses a replaceable provider abstraction
Production identity is expected to use Microsoft Entra ID; local identity is for development/testing only under explicit safe configuration.

## D-016 — Ownership has one authoritative source
`kb_memberships(role='owner')` is the authoritative ownership state. Legacy `knowledge_bases.owners` is not authoritative.

## D-017 — Release creation is distinct from approval/publication
Release state transitions are explicit and governed. Creation does not imply publication.

## D-018 — Release snapshots are immutable and reproducible
A release is a frozen knowledge state with deterministic manifest/snapshot content and historical reproducibility.

## D-019 — Search index is a rebuildable derived projection
The immutable release is authoritative; the search index is derived and replaceable.

## D-020 — PostgreSQL FTS is preferred before adding external search infrastructure
For the current corpus, start with PostgreSQL FTS unless evidence proves that external search infrastructure is required.

## D-021 — Adversarial review is independent from implementation
The implementation worker may explain its work, but a fresh reviewer must independently inspect repository state, tests and evidence.

## D-022 — Review approval is revision-bound
A review approval is only valid for the exact reviewed repository state. Review, current working tree and staged tree must converge before commit.

## D-023 — Historical evidence is append-only
Previous review artifacts are never overwritten. New review cycles receive new versioned artifacts.

## D-024 — BLOCKED never auto-becomes APPROVED
Failure, max cycles, ambiguity, corrupted state or missing context must stop execution rather than silently authorize progress.

## D-025 — Workers are disposable; Slice Run is persistent
Workflow state and useful context must survive worker/model replacement. Chat history is not a governance primitive.

## D-026 — Work Items are execution units, not governance authorities
Objectives and Work Items refine execution but remain subordinate to Slice-level governance.

## D-027 — Convergence is deterministic conformance checking
Convergence checks plan/implementation/predicate compliance. It is not substantive acceptance and must not rely on LLM judgment.

## D-028 — Learning is informational
Learning records can preserve technical discoveries and rejected approaches, but cannot directly change policy, acceptance, or plan.

## D-029 — Exploration is bounded and non-authoritative
Exploration runs in disposable space and has no commit or governance authority.

## D-030 — The orchestrator should replace manual chat coordination
The intended UX is a command such as `slice run S6`. LLMs are workers behind the orchestrator rather than the primary workflow interface.

## D-031 — The orchestrator should act in the interest of the product outcome
Beyond mechanical execution, the orchestrator should actively preserve the finality stated in the approved plan, challenge unnecessary work, identify missing prerequisites, and keep the team focused on product value — without inventing requirements or overruling explicit governance.

## D-032 — The orchestrator may ask questions, but sparingly
Questions should be exceptional and targeted at genuine ambiguity, missing human decisions, conflicting requirements, or blocked execution. It should prefer investigation, evidence gathering and reversible exploration before asking the human.

## D-033 — Product judgment is separate from acceptance authority
The orchestrator may recommend priorities, sequencing, simplifications or clarifications. It must not self-approve architectural, security, governance or release acceptance.

## D-034 — Prefer the smallest mechanism that protects a real invariant
Avoid building a large agent platform when a local deterministic mechanism is sufficient.
