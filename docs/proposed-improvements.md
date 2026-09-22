# Proposed Improvements — Slice Orchestrator

This document synthesizes value analysis, empirical feedback (from the
project's productivity studies), and recommended improvement directions for
the **Slice Orchestrator (Method v4 Runtime)**.

---

## 1. Recap — Actual Value and Gains of the Tool

Per the project's measurements and studies (`PRODUCTIVITY_STUDY_RESULTS.md`
and `PRODUCTIVITY_STUDY_ANALYSIS.md`), the tool is not meant to accelerate
raw wall-clock execution time on micro-tasks, but to bring guarantees that
are otherwise missing in AI-governed software engineering:
* **Reliability and integrity**: Eliminates false positives ("*completion
  hallucinations*") through deterministic mechanical barriers (*quality
  gates*) validated against JSON schemas and real test results.
* **Adversarial auditability (*Adversarial Review*)**: Strict separation
  between the persistent implementation thread and an independent reviewer
  agent with a clean context, producing structured remediation packets.
* **Robust failure recovery (*Durable Multi-Session Recovery*)**: Immutable
  state storage backed by SQLite and cryptographic chaining (HMAC/SHA256),
  enabling instant resumption after an IDE restart or crash.
* **Git safety and scope containment (*Scope Containment*)**: Forbids
  `git add .`, strictly restricting changes to files declared in the
  slice's scope.
* **Requirements discipline (*Phase Grill*)**: Requires the AI to question
  the user about ambiguities before writing a single line of code.

---

## 2. Identified Trade-offs and Friction Points

1. **Overhead on micro-tasks**: Going through the full governance cycle
   (plan, gates, double review, validation) imposes roughly a 15x to 17x
   execution-time ratio compared to a direct one-line edit.
2. **Remediation-loop friction (UX)**: Resuming a slice after a
   `REVIEW_BLOCKED` status needs smoother operational handling so the
   cycle doesn't stall in a partial state.

---

## 3. Roadmap and Proposed Improvements

### A. Adaptive Governance (*Fast-Track vs Full-Governance*)
* **Observation**: Not all changes carry the same criticality. Applying
  the full heavy cycle to a one-line fix or a typo discourages adoption.
* **Proposal**:
  * **Fast-Track profile (simple tasks / complexity 1)**: Git scope
    validation + mandatory unit test pass, without requiring the full
    architecture review and independent adversarial review steps.
  * **Standard / Reinforced profile (complexity ≥ 2 or critical code)**:
    Current full cycle with adversarial review, strict schema validation,
    and cryptographic anchoring.

### B. Smoother Remediation Loop (*Remediation UX*)
* **Observation**: Experimental task DF-08 revealed friction when
  re-injecting remediation packets back into the implementation loop.
* **Proposal**:
  * Automate re-routing: on a review rejection, automatically generate a
    structured remediation prompt targeting the implementer's persistent
    thread directly.
  * Offer a simplified resume command (`slice_remediate` or
    `slice resume --with-packet`).

### C. Live Multi-Host Validation (*Live Cross-Host Sessions*)
* **Observation**: Although the MCP architecture is unified
  (`MULTI_HOST_MCP_ARCHITECTURE.md`), operational validation under real
  conditions is still centered on Cursor Chat.
* **Proposal**:
  * Finalize and test the native Claude Code integration
    (`CLAUDE_CODE_NATIVE_INTEGRATION_GUIDE.md`).
  * Validate collaborative/alternating workflows (start a slice in Cursor,
    resume or audit it in Claude Code on the same repository).
### D. Headless Mode and CI/CD Integration (Mode B)
* **Observation**: The autonomous subprocess mode is still mostly confined
  to local development.
* **Proposal**:
  * Create GitHub Actions / GitLab CI pipelines able to instantiate the
    orchestrator autonomously on Pull Requests.
  * Let agents running in CI analyze regressions and submit pre-validated
    fix slices.

### E. Slicing and Cross-Slice Dependency Management (Enterprise Scale)
* **Observation**: Vertical slices are currently managed as independent
  units.
* **Proposal**:
  * Add a dependency graph between functional slices (`slice_dependencies`).
  * Prevent merging a slice if its prerequisite slices have not reached
    the `COMPLETE` state.
