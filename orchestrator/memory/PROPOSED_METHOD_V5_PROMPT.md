# Prompt — Method v5 Product-Oriented Orchestrator Enhancement

Method v4 Enhanced is APPROVED and its control-plane security model is authoritative.

We now want to refine the METHOD so the eventual Slice Orchestrator behaves not only as a workflow supervisor, but also as a lightweight Product Owner / Scrum Master for AI-assisted software development.

This is a METHOD DESIGN task only.

Do NOT implement runtime code.
Do NOT modify S1–S9.
Do NOT commit.

## Goal

The user should eventually be able to run:

    slice run S6

and have the orchestrator autonomously drive the development lifecycle while acting in the interest of the product outcome defined by the approved plan.

The orchestrator should:

- understand the approved plan's finality and objectives;
- create and manage useful Work Items;
- maintain progress and sequencing;
- challenge unnecessary complexity and low-value work;
- identify missing prerequisites;
- use exploration before asking the human when uncertainty is bounded;
- proactively surface risks and trade-offs;
- ask the human only when an autonomous decision would be unsafe or would create a material product/architecture/scope decision.

## Critical boundary

The orchestrator MAY:
- plan;
- decompose;
- prioritize within approved scope;
- recommend;
- investigate;
- benchmark;
- challenge;
- ask concise questions.

The orchestrator MUST NOT:
- invent requirements;
- silently change the approved plan;
- redefine acceptance;
- approve itself;
- weaken security or governance;
- redefine AuthorityLevel;
- bypass S8/S9/S5/S4 boundaries;
- commit without deterministic gates;
- turn Learning into policy without explicit promotion;
- use a reviewer worker as an authority substitute.

## 1. Product Objective Model

Extend Objectives so each important objective can contain:

- outcome statement;
- user/product value;
- source requirements;
- success criteria;
- acceptance predicates;
- dependencies;
- non-goals;
- risks;
- current confidence.

Distinguish:

Product Outcome
≠
Implementation Task
≠
Acceptance Gate

Do not allow the LLM to silently alter any of these authoritative fields.

## 2. Work Item Prioritization

Define a deterministic + advisory prioritization model.

Work Item priority should consider:
- objective contribution;
- dependency criticality;
- blocker reduction;
- risk reduction;
- product value;
- cost/effort.

Do NOT create a fake mathematical precision if the underlying data is qualitative.

Priority recommendations are advisory.

## 3. PO / SM Operating Loop

Add a lightweight operating loop:

Observe
→ Understand
→ Prioritize
→ Execute
→ Verify
→ Re-plan locally
→ Escalate only when needed

The local re-planning must remain inside the approved plan.

Material scope/architecture changes require PLAN_REVISION.

## 4. Proactive Blocker Resolution

Before asking the user, the orchestrator should attempt:

1. repository inspection;
2. existing decision lookup;
3. contract/test lookup;
4. bounded exploration;
5. reversible experiment;
6. alternative implementation within approved scope.

Only then ask the user if still blocked.

## 5. Question Budget

Introduce a configurable question policy.

Default:
- avoid questions when evidence can resolve the issue;
- ask at most one focused question per unresolved decision point;
- bundle related questions;
- provide context and the exact decision needed.

Classify:

QUESTION_REQUIRED
QUESTION_RECOMMENDED
QUESTION_OPTIONAL

Only QUESTION_REQUIRED pauses autonomous execution by default.

## 6. Decision Proposal

When a human decision is required, the orchestrator should produce:

Decision needed:
Context:
What was checked:
Options:
Recommendation:
Impact:
Why autonomous resolution is unsafe:

Keep it short.

## 7. Product / Engineering Tension

The orchestrator must be able to identify:

Technically correct
but
Product incomplete

and:

Product useful
but
Architecture unsafe

It should surface the tension rather than silently choose one side.

## 8. Strategic Challenge Worker

Evaluate whether a separate non-authoritative role is useful:

ARCHITECT_ADVISOR

Its mission:
- challenge direction;
- compare alternatives;
- identify unnecessary complexity;
- question assumptions.

It must never approve or commit.

Keep it optional and low-frequency.

## 9. Learning Loop

Extend the Learning Ledger with:

observation
→ evidence
→ implication
→ recommendation

But preserve the rule:

Learning ≠ Policy
Learning ≠ Requirement
Learning ≠ Acceptance

Promotion to durable project guidance requires explicit control-plane approval or PLAN_REVISION as appropriate.

## 10. Product Health / Run Health

Add a small set of derived indicators:

- objective progress;
- blocker count;
- unresolved decisions;
- scope drift;
- convergence status;
- review cycle;
- work-item retry rate;
- risk trend.

Do not create vanity metrics.

## 11. Human Interaction

Human intervention should be rare.

The orchestrator should ask when:
- a genuine product choice is missing;
- requirements conflict;
- security/governance cannot be safely inferred;
- a material architectural choice changes the approved plan;
- an external dependency cannot be obtained safely;
- recovery is ambiguous.

Do not ask for:
- routine implementation choices;
- information already in the repository;
- trivial naming/style decisions;
- decisions recoverable through exploration.

## 12. Method Integrity

All Method v4 guarantees remain unchanged:

- control plane authority;
- persistent Slice Run;
- disposable workers;
- fresh adversarial review;
- deterministic gates;
- revision pinning;
- protected files;
- evidence integrity;
- Git safety;
- governance sequencing.

The PO/SM capability must be subordinate to these.

## 13. MVP vs Future

Define clearly:

MUST HAVE:
- product objective representation;
- work-item prioritization;
- blocker detection;
- bounded proactive investigation;
- question policy;
- concise decision proposal.

SHOULD HAVE:
- strategic architecture advisor;
- product/run health indicators;
- learning promotion workflow.

DEFER:
- predictive project management;
- autonomous roadmap creation;
- autonomous product requirement invention;
- fully automated stakeholder negotiation.

## 14. Acceptance Questions

The enhanced method is acceptable only if:

1. the orchestrator can act proactively without inventing authority;
2. product goals remain traceable to the approved plan;
3. Work Items remain subordinate to Slice governance;
4. questions are rare and decision-focused;
5. the orchestrator can distinguish uncertainty from true blockers;
6. human decisions are explicit and auditable;
7. strategic advice is separate from acceptance authority;
8. no PO/SM behavior weakens the control-plane trust model.

Create the updated method proposal and an independent review checklist.

Do not implement the runtime.
Do not commit.
Do not start S6.

Finish with:

Method v5 product-oriented proposal: yes
Runtime modified: no
S1–S9 modified: no
Git commit created: no
Ready for focused adversarial review: yes
