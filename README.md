# Slice Orchestrator

<p align="center">
  <strong>Deterministic Full-Lifecycle SDLC Governance for AI Coding Agents</strong><br>
  <em>From Specification and Multi-Slice DAG to Tamper-Proof Cryptographic PR Gating.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/MCP-14%20Tools%20Ready-6851FF?style=flat" alt="Model Context Protocol" />
  <img src="https://img.shields.io/badge/Tests-262%20Passed-brightgreen?style=flat" alt="262 Tests Passed" />
  <img src="https://img.shields.io/badge/Security-HMAC--SHA256%20Chained-success?style=flat" alt="Cryptographic Security" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="MIT License" />
</p>

---

## 🛑 The Problem with Modern Coding Agents

AI coding assistants (Cursor, Claude Code, Devin, Copilot) are remarkably productive, but they lack **engineering discipline and mechanical accountability**:

* 🚨 **Scope Creep**: You asked for a 2-line bugfix; the agent casually modified 14 unrelated files and ran `git add .`.
* 🤥 **Hallucinated Completion**: The agent claims *"All 25 tests passed! Ready to merge!"* without having run a single command or while ignoring hidden failures.
* 🧪 **Test Tampering**: When a test fails, the agent secretly deletes assertions or mocks them out to turn the suite green.
* 💥 **Context Amnesia**: Your IDE crashes or you switch chat sessions, and the agent loses track of work items, re-doing changes or breaking Git history.
* 🛡️ **Failing Prompt Guardrails**: Natural language prompts like *"Please only touch file X"* or *"Never commit broken code"* routinely fail against prompt injection, context exhaustion, or instruction drift.

---

## ⚡ The Solution: Deterministic Full-Lifecycle SDLC

**Slice Orchestrator** is an out-of-process, deterministic control plane that sits between your AI assistant and your Git repository. It replaces wishful prompts with **mechanically enforced quality gates across the entire software development lifecycle**:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                        THE GOVERNED AGENTIC SDLC                               │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  1. SPECIFICATION & SCOPE     ──► 2. ARCHITECTURE REVIEW ──► 3. IMPLEMENTATION │
│     (Goal, non-goals, allow_paths)  (Independent review gate)   (Strict sandbox)│
│                                                                       │        │
│                                                                       ▼        │
│  6. MULTI-SLICE DAG & CI GATE ◄── 5. ADVERSARIAL REVIEW  ◄── 4. VERIFICATION   │
│     (slice graph / action.yml)      (Anti-hallucination)        (HMAC receipt) │
│            │                                                                   │
│            ▼                                                                   │
│  7. ATOMIC MERGE & RELEASE                                                     │
│     (COMPLETE state / reproducible provenance)                                 │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Key Guarantees

* 🔒 **Scope Manifest Enforcement**: The approved plan declares the exact file patterns the agent is permitted to touch. Any unauthorized addition, modification, or deletion is mechanically rejected at the commit gate.
* 📜 **Authoritative HMAC Test Receipts**: Test execution runs strictly through the control plane (`slice_run_tests`). Receipts are cryptographically bound to the exact candidate Git tree OID and workspace revision digest. Self-reported agent claims are treated as inert text.
* 🛡️ **Test-Tampering Guards**: Modifying or deleting existing baseline test files without plan re-approval triggers an immediate gate failure.
* 🕵️ **Independent Adversarial Review**: Work must be reviewed by an independent reviewer role before commit readiness. Self-approval by the implementer is rejected.
* 🔄 **Automated Remediation Loop**: Review blockers automatically generate structured remediation packets and copy-paste prompts (`slice remediate --prompt`).
* 🕸️ **Multi-Slice Dependency DAG**: Coordinate complex epics where Slice S2 depends on Slice S1; downstream slices are blocked from commit until prerequisites reach `COMPLETE`.
* 🤖 **CI & Pull Request Gatekeeper**: Includes a native GitHub Action (`action.yml`) and CLI command (`slice verify-pr`) to enforce governance before merge.
* 💾 **Crash-Proof Event Sourcing**: Every state transition is recorded in an append-only, HMAC-chained SQLite log. If your IDE restarts, the slice resumes instantly with zero lost context.
* 🔌 **Host-Agnostic Model Context Protocol (MCP)**: Exposes 14 standardized tools over stdio. Works identically with Cursor Chat and Claude Code.

---

## 📊 Standard AI Agent vs. Slice-Governed Agent

| Feature | Standard AI Coding Assistant | With Slice Orchestrator |
|---|---|---|
| **File Containment** | Prompts like *"don't edit other files"* (often ignored) | **Strict Scope Manifest**: Commit gate blocks unapproved file diffs |
| **Test Verification** | Agent claims *"Tests pass"* in markdown | **HMAC-Signed Receipts**: Verified execution via control-plane runner |
| **Test Integrity** | Agent can weaken or delete failing tests | **Tamper Detection**: Baseline tests are checksummed and protected |
| **Review Process** | Agent approves its own work | **Adversarial Separation**: Implementer cannot self-approve |
| **Bug Fixing** | Ad-hoc iterative prompt loops | **Structured Remediation**: Tracked cycles with context packets |
| **Complex Epics** | Fragile mega-prompts that hallucinate | **Multi-Slice DAG**: Explicit dependency tracking (`slice graph`) |
| **CI / PR Enforcement**| Manual code review fatigue | **Zero-Trust CI Gate**: Automated PR verification (`action.yml`) |
| **Crash Recovery** | Session lost on IDE quit or reload | **Durable SQLite State**: Resumes from exact state and sequence |
| **Audit Trail** | Ephemeral, lossy chat logs | **Immutable Event Stream**: Cryptographically chained audit trail |

---

## 🚀 One-Time Setup: Govern ANY Project in 60 Seconds

You do **not** need to rewrite your application or add vendor locks. Slice Orchestrator lives out-of-process.

### Option A: The 10-Second Instant Setup (`slice init`)

In your target project's root directory:
```bash
uv run --project ~/slice-orchestrator slice init
```
This automatically:
1. Detects your language ecosystem (Python, TypeScript/Node, Rust, Go).
2. Generates an optimized `.slice.toml` polyglot config.
3. Generates `.mcp.json` for immediate Cursor & Claude Code discovery.
4. Appends `.orchestrator_slice/` to `.gitignore`.

---

### Option B: Manual Setup

#### Step 1: Clone Slice Orchestrator (Once on your machine)

```bash
git clone https://github.com/Guilhem23/slice-orchestrator.git ~/slice-orchestrator
cd ~/slice-orchestrator
uv sync --extra test
uv run slice doctor
```
*(Confirms `19/19 passed`.)*

#### Step 2: Enable Governance in Your Target Project

In the root of your existing project, add `.mcp.json`:

```json
{
  "mcpServers": {
    "slice-orchestrator": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/slice-orchestrator",
        "python3",
        "-m",
        "slice_orchestrator.mcp_server"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

#### Step 3: Add Runtime State to `.gitignore`

In your target project's `.gitignore`:
```gitignore
.orchestrator_slice/
```

#### Step 4: Prompt Your Agent!

Open **Cursor** or **Claude Code** in your target project:

> *"Use Slice Orchestrator to plan and implement slice S1: Add user authentication. Strictly follow the governed lifecycle from planning to commit gate."*

👉 *For an automated copy-paste setup prompt, see [docs/integration-prompt.md](docs/integration-prompt.md).*

---

## 🛠️ The 14 Governed MCP Tools

Slice Orchestrator exposes a disciplined toolkit covering every phase of engineering:

| Tool | Phase | Purpose |
|---|---|---|
| `slice_start` | Initialization | Initialize a slice run with a defined governance profile |
| `slice_context` | Discovery | Inspect slice state, active assignments, and workspace digests |
| `slice_grill` | Requirements | Clarify ambiguities before code generation begins |
| `slice_plan` | Planning | Persist structured objective, test plan, and scope manifest |
| `slice_work_list` | Execution | List actionable tasks, dependencies, and execution status |
| `slice_dispatch` | Execution | Claim an assignment bound to an actor role |
| `slice_record_result`| Execution | Record worker artifacts, diffs, and learnings |
| `slice_run_tests` | Verification | Execute tests and issue a cryptographic HMAC receipt |
| `slice_status` | Observability | Query state machine status, sequence, and blocker flags |
| `slice_report` | Observability | Generate comprehensive governance summary |
| `slice_request_review`| Quality Gate | Request independent architecture or adversarial review |
| `slice_remediate` | Remediation | Process review findings and generate remediation tasks |
| `slice_gate` | Quality Gate | Evaluate deterministic preconditions for commit |
| `slice_finalize` | Delivery | Reconcile governance, record commit, and transition to `COMPLETE` |

---

## 💻 CLI Command Reference

Manage slices, inspect event streams, and visualize dependencies directly from your terminal:

```bash
# Setup & Health
slice init                        # 60-second zero-friction onboarding
slice doctor                      # Check trust anchors and toolchain health

# Planning & Execution
slice plan S1                     # Initialize and validate plan
slice status S1                   # Show state machine status
slice run S1                      # Autonomously drive slice to completion
slice resume S1 --with-packet     # Resume with full remediation context

# Remediation & Quality
slice remediate S1 --prompt       # Export copy-paste Markdown remediation prompt

# Multi-Slice DAG
slice graph                       # Display ASCII dependency tree of all slices
slice graph --json                # Machine-readable DAG nodes & edges

# CI & Pull Request Verification
slice verify-pr                   # Authoritative CI gatekeeper (diff, scope, HMAC)

# Audit, Observability & Metrics
slice explain S1                  # Deep diagnostic explain dump
slice timeline S1                 # Ordered event timeline with durations
slice inspect S1                  # Raw JSON event stream
slice export S1                   # Export reproducible run package
slice metrics S1                  # Authoritative provenance metrics
```

Run `slice <command> --help` for full options.

---

## 🛡️ GitHub Action CI Gatekeeper

Enforce zero-trust governance on AI-generated pull requests in CI by adding `.github/workflows/slice-gate.yml`:

```yaml
name: "Agent PR Governance Gate"

on:
  pull_request:
    branches: [main, master]

jobs:
  slice-gatekeeper:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code with Full History
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Verify Slice Governance
        uses: Guilhem23/slice-orchestrator@main
        with:
          base-ref: "origin/${{ github.base_ref }}"
```

---

## 🏢 Enterprise & Compliance Standards

Slice Orchestrator addresses emerging software supply chain and AI compliance frameworks out of the box:

* **EU AI Act & GPAI (Article 14 - Human Oversight & Traceability)**: Full auditability of all agent decisions, tools invoked, and verified diffs.
* **NIST Secure Software Development Framework (SSDF / SP 800-218)**: Prevents test tampering and verifies that delivered software strictly matches authorized change sets.
* **SOC 2 Type II & DORA (Digital Operational Resilience Act)**: Non-repudiable audit logs backed by SQLite and cryptographic chaining.

---

## 📁 Repository Layout

```
slice_orchestrator/     Core runtime (control store, state machine, gates, MCP server, CLI)
tests/                  262 tests (security, MCP protocol, cross-host isolation, DAG, recovery)
.orchestrator/          JSON schemas, transition policies, protocol specifications
docs/                   Architecture, host integration guides, and observability specs
docs/archive/           Curated historical validation & remediation audit reports
test-project/           Adversarial test fixtures for automated security regression suites
action.yml              Reusable GitHub Action composite gatekeeper
```

---

## 🧪 Running the Test Suite

Slice Orchestrator is backed by an automated regression test suite (262 tests):

```bash
uv sync --extra test
uv run python3 -m pytest tests/ -q
```
```text
======================== 262 passed in 114.58s ========================
```

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.
All control-plane changes must include automated regression tests and maintain fail-closed guarantees.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
