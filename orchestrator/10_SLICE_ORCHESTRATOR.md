# Slice Orchestrator — Governance and Execution Method

## Purpose

The Slice Orchestrator coordinates the lifecycle of a Knowledge Fabric vertical slice without replacing independent acceptance authority.

It is a workflow controller, not an autonomous product owner.

## Platform neutrality

The method MUST work with at least:
- Cursor Agent / Cursor CLI-style workflows;
- Claude Code / Claude-style agent sessions;
- manual execution.

It communicates through repository files, deterministic commands, and explicit state. No proprietary agent API is required.

## Persistent implementation thread

Each slice has ONE persistent implementation thread identified in state:

`implementation_thread_id`

The same thread is reused across all remediation cycles.

Purpose:
- preserve code context;
- preserve debugging context;
- preserve test history;
- preserve implementation decisions;
- reduce repeated repository rediscovery.

The adversarial reviewer is ALWAYS a fresh context per review cycle.

Thus:

```text
                 ┌────────────────────┐
                 │ Persistent          │
                 │ Implementation      │
                 │ Thread              │
                 └─────────┬──────────┘
                           │
                    implement / fix
                           │
                           ▼
                 ┌────────────────────┐
                 │ Fresh Adversarial  │
                 │ Review vN          │
                 └─────────┬──────────┘
                           │
                 ┌─────────┴─────────┐
                 │                   │
              APPROVED            BLOCKED
                 │                   │
                 ▼                   ▼
              COMMIT        remediation packet
                                     │
                                     ▼
                          SAME implementation thread
                                     │
                                     ▼
                              Fresh review vN+1
```

## Core lifecycle

```text
PLANNING
  -> PLAN_READY
  -> ARCHITECTURE_REVIEW
  -> ARCHITECTURE_APPROVED
  -> IMPLEMENTATION
  -> IMPLEMENTATION_READY_FOR_REVIEW
  -> ADVERSARIAL_REVIEW
      -> BLOCKED -> REMEDIATION -> IMPLEMENTATION -> ADVERSARIAL_REVIEW
      -> APPROVED -> COMMIT_READY
  -> COMMITTED
  -> GOVERNANCE_RECONCILIATION
  -> COMPLETE
```

No transition may skip a gate.

`BLOCKED -> COMMITTED` is forbidden.
`IMPLEMENTATION -> COMMITTED` is forbidden.
`ADVERSARIAL_REVIEW(APPROVED)` is required before commit.

## Structured remediation packet

When a review is BLOCKED, the reviewer creates:

```text
evidence/<slice>/remediation-packet-vN.json
```

The packet contains, for every blocking finding:
- stable finding ID;
- severity;
- exact location;
- description;
- violated invariant;
- required regression test;
- expected property;
- forbidden changes.

The implementation agent receives this packet in its existing persistent thread.

The orchestrator never paraphrases or weakens findings.

## Cycle limits

The orchestrator MUST enforce a maximum review/remediation cycle count.

When the limit is reached:

```text
STOP
↓
human intervention
```

Never auto-approve after repeated failures.

## Acceptance authority

A deterministic gate evaluator may verify mechanical facts:

- review = APPROVED;
- blocking_findings = 0;
- required tests not skipped;
- evidence valid;
- scope valid.

It MUST NOT reinterpret a reviewer verdict or manufacture approval.

## Historical evidence

Historical review artifacts are append-only.

Never overwrite prior review files.

Every review cycle creates a new review artifact and corresponding acceptance metrics.

## Git safety

The Git manager must:
- classify every changed file;
- stage only declared slice scope;
- never use `git add .`;
- never reset or discard unrelated work;
- stop when attribution is ambiguous.

## State

Per-slice state:

`.orchestrator/state/<slice>.json`

It records facts including:
- slice;
- state;
- plan path;
- implementation thread ID;
- review cycle;
- last review path/thread;
- remediation packet path;
- blocking finding count;
- commit permission/hash.

## Safety

Stop rather than guess when:
- slice ownership is ambiguous;
- required artifacts are missing;
- repository contains unrelated dirty changes that cannot be attributed;
- review is BLOCKED;
- required test fails/is skipped;
- plan and implementation diverge;
- cycle limit is reached;
- Git attribution is unclear.

## Governance

The Governance Agent runs only after commit and acceptance. It updates current-state roadmap metadata and preserves historical evidence. It does not implement code and does not decide acceptance.
