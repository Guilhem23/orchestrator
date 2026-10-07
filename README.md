# Slice Orchestrator

<p align="center">
  <strong>Deterministic Zero-Trust Governance for AI Coding Agents</strong><br>
  <em>Never let an AI agent hallucinate test passes, modify unapproved files, or tamper with your test suite again.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/MCP-14%20Tools%20Ready-6851FF?style=flat" alt="Model Context Protocol" />
  <img src="https://img.shields.io/badge/Tests-240%20Passed-brightgreen?style=flat" alt="240 Tests Passed" />
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

## ⚡ The Solution: Deterministic Control Plane

**Slice Orchestrator** is an out-of-process, deterministic control plane that sits between your AI assistant and your Git repository. It replaces wishful prompts with **mechanically enforced quality gates**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        GOVERNED SLICE LIFECYCLE                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│   PLANNING ──► ARCHITECTURE_REVIEW ──► IMPLEMENTATION                  │
│                                              │                         │
│                                              ▼                         │
│   COMPLETE ◄── COMMIT_GATE ◄── COMMIT_READY ◄── ADVERSARIAL_REVIEW     │
│                    ▲                                                   │
│                    └──── HMAC-signed test receipt bound to tree OID    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Guarantees

* 🔒 **Scope Manifest Enforcement**: The approved plan declares the exact file patterns the agent is permitted to touch. Any unauthorized addition, modification, or deletion is mechanically rejected at the commit gate.
* 📜 **Authoritative HMAC Test Receipts**: Test execution runs strictly through the control plane (`slice_run_tests`). Receipts are cryptographically bound to the exact candidate Git tree OID and workspace revision digest. Self-reported agent claims are treated as inert text.
* 🛡️ **Test-Tampering Guards**: Modifying or deleting existing baseline test files without plan re-approval triggers an immediate gate failure.
* 🕵️ **Independent Adversarial Review**: Work must be reviewed by an independent reviewer role before commit readiness. Self-approval by the implementer is rejected.
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
| **Crash Recovery** | Session lost on IDE quit or reload | **Durable SQLite State**: Resumes from exact state and sequence |
| **Audit Trail** | Ephemeral, lossy chat logs | **Immutable Event Stream**: Cryptographically chained audit trail |

---

## 🚀 One-Time Setup: Govern ANY Project in 60 Seconds

You do **not** need to install Slice Orchestrator as a dependency in your application, nor do you need to rewrite your project.

### Step 1: Clone Slice Orchestrator (Once on your machine)

```bash
git clone https://github.com/Guilhem23/orchestrator.git ~/slice-orchestrator
cd ~/slice-orchestrator
uv sync --extra test
uv run slice doctor
```
*(Confirms `19/19 passed`.)*

### Step 2: Enable Governance in Your Target Project

In the root of **any** existing project (Python, TypeScript, Go, Rust, etc.) where you want AI governance, add a project-scoped `.mcp.json`:

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

### Step 3: Add Runtime State to `.gitignore`

In your target project's `.gitignore`, add:
```gitignore
.orchestrator_slice/
```
*(This is where the target project's SQLite state store, local HMAC keys, and locks are kept.)*

### Step 4: Prompt Your Agent!

Open **Cursor** or **Claude Code** in your target project. Your assistant now has access to the 14 `slice_*` tools! Simply prompt:

> *"Use Slice Orchestrator to plan and implement slice S1: Add JWT authentication. Strictly follow the governed lifecycle from planning to commit gate."*

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

## 💻 CLI Reference

When you want to inspect or manage slices directly from your terminal:

```bash
# Sanity check your environment and cryptographic trust anchors
slice doctor

# Plan and inspect slices
slice plan S1 --repo-dir /path/to/repo
slice status S1
slice explain S1

# Drive slice autonomously
slice run S1

# Inspect governance, audit events, and metrics
slice inspect S1
slice diagnostics S1
slice timeline S1
slice export S1
slice metrics S1
```

Run `slice <command> --help` for full options.

---

## 🏢 Enterprise & Compliance Value

Slice Orchestrator was designed from the ground up to address emerging software supply chain and AI compliance standards:

* **EU AI Act & GPAI (Article 14 - Human Oversight & Traceability)**: Full auditability of all agent decisions, tools invoked, and verified diffs.
* **NIST Secure Software Development Framework (SSDF / SP 800-218)**: Prevents test tampering and verifies that delivered software strictly matches authorized change sets.
* **SOC 2 Type II & DORA (Digital Operational Resilience Act)**: Non-repudiable audit logs backed by SQLite and cryptographic chaining.

---

## 📁 Repository Layout

```
slice_orchestrator/     Core runtime (control store, state machine, gates, MCP server, CLI)
tests/                  240 tests (security, MCP protocol, cross-host isolation, recovery)
.orchestrator/          JSON schemas, transition policies, protocol specifications
docs/                   Architecture, host integration guides, and observability specs
docs/archive/           Curated historical validation & remediation audit reports
test-project/           Adversarial test fixtures for automated security regression suites
```

---

## 🧪 Running the Test Suite

Slice Orchestrator is backed by a comprehensive regression test suite (240 tests):

```bash
uv sync --extra test
uv run python3 -m pytest tests/ -q
```
```text
======================== 240 passed in 90.56s ========================
```

---

## 🗺️ Roadmap

See [docs/roadmap.md](docs/roadmap.md) and [docs/proposed-improvements.md](docs/proposed-improvements.md) for the active development plan:
* **v4.1**: Universal Polyglot Engine (`.slice.toml` for TypeScript/Node, Rust, Go).
* **v4.2**: One-Click Automated Remediation Dispatch.
* **v4.3**: GitHub Action Zero-Trust PR Gatekeeper (`action.yml`).
* **v4.4**: Enterprise Multi-Slice DAG Coordination.
* **v4.5**: Distribution via `uvx` / `pipx` for zero-clone 60-second onboarding.

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.
All control-plane changes must include automated regression tests and maintain fail-closed guarantees.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
