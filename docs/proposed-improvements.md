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

---

## 4. Actionable Development Plan (v4.1 → v4.5)

To transition Slice Orchestrator from a validated core prototype into a market-ready, widely adopted standard for AI agent governance, execution is organized into five prioritized implementation phases:

### Phase 1 — Universal Polyglot Engine (`.slice.toml`)
* **Goal**: Enable Slice Orchestrator to govern repositories in any language (TypeScript/Node, Rust, Go, Python, Java) without hardcoded pytest assumptions.
* **Key Deliverables**:
  1. Target project configuration schema: `.slice.toml` / `.orchestrator.yaml` specifying `test_command` (e.g. `npm test`, `cargo test`, `pytest`), `lint_command`, and `default_scope`.
  2. Dynamic test runner: replace hardcoded Python/pytest invocations in `gates.py` and `orchestrator.py` with project-level configuration fallback.
  3. Support for custom exit code assertions and test report parsers.
* **Exit Criteria**: End-to-end slice completion with HMAC test receipt on a non-Python repository (e.g. Node/TypeScript or Rust project).

### Phase 2 — Frictionless Remediation Loop (UX Polish)
* **Goal**: Eliminate operational drag when an adversarial review or gate check blocks a slice.
* **Key Deliverables**:
  1. `slice_remediate` automated prompt generation: automatically package failed test outputs, linter errors, and adversarial review finding packets into a copy-pasteable or directly dispatched prompt for the implementer agent.
  2. Interactive CLI helper: `slice resume --with-packet <packet-id>` to transition from `REVIEW_BLOCKED` back to `IMPLEMENTATION` with zero manual bookkeeping.
* **Exit Criteria**: A developer can resolve an adversarial review finding in a single prompt cycle without inspecting SQLite records.

### Phase 3 — GitHub Action & CI Zero-Trust PR Gatekeeper
* **Goal**: Provide automated, server-side mechanical enforcement in CI/CD pipelines so PRs created by AI agents cannot bypass governance.
* **Key Deliverables**:
  1. Official GitHub Action (`action.yml`): runs `slice gate --verify-pr` on Pull Requests.
  2. Scope Diff Checker: checks that git diff between PR branch and base branch strictly conforms to the approved slice's `scope_manifest`.
  3. HMAC Receipt Verification: blocks PR merge if candidate tree OID is not backed by an authorized test receipt.
  4. Rich PR sticky comment summarizing slice status, scope diff, and cryptographic audit proofs.
* **Exit Criteria**: A demo repository where an agent opening an unauthorized PR with out-of-scope edits is blocked by GitHub Actions.

### Phase 4 — Multi-Slice Functional DAG (Enterprise Scale)
* **Goal**: Support complex features spanning multiple interdependent vertical slices.
* **Key Deliverables**:
  1. Slice dependency declaration: `slice_dependencies = ["S1", "S2"]` in objective and plan schemas.
  2. Cross-slice verification in `GateEvaluator`: reject transitioning slice `S3` to `COMMIT_READY` if prerequisite slices have not reached `COMPLETE`.
  3. Visual DAG command: `slice graph` rendering visual dependency trees in terminal/Markdown.
* **Exit Criteria**: Coordinated execution of a 3-slice feature where downstream slices safely wait for upstream governance reconciliation.

### Phase 5 — Packaging, Distribution & 60-Second Onboarding (`uvx` / `pipx`)
* **Goal**: Maximize developer adoption by eliminating the need to clone a separate repository just to run the MCP server.
* **Key Deliverables**:
  1. PyPI publication: `pip install slice-orchestrator` / `uvx slice-orchestrator`.
  2. Zero-clone MCP configuration:
     ```json
     {
       "mcpServers": {
         "slice-orchestrator": {
           "command": "uvx",
           "args": ["slice-orchestrator", "mcp"]
         }
       }
     }
     ```
  3. One-line repository bootstrap: `uvx slice-orchestrator init` (creates `.mcp.json` and updates `.gitignore` automatically).
* **Exit Criteria**: Any developer can add full agent governance to their repository with a single command in under 60 seconds.
