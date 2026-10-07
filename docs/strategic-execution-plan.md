# Strategic Execution Plan (Order: 4 ➔ 5 ➔ 2 ➔ 1 ➔ 3)

> **Document Objective**: Operational blueprint translating market feedback, developer adoption friction, and enterprise B2B sales requirements into an actionable, phased implementation roadmap for Slice Orchestrator.

---

## Executive Summary & Sequence Rationale

The execution sequence follows an unforgiving product-market law:
```
[Phase 1] Token Economy & Agent Docility (Fix the product physics & UX first)
    │
    ▼
[Phase 2] Enterprise Business Model & GTM (Define how value is captured & monetized)
    │
    ▼
[Phase 3] Dual-Persona Alignment (Equip the Developer champion & reassure the CISO buyer)
    │
    ▼
[Phase 4] Zero-Clone PyPI & uvx Distribution (Open top-of-funnel viral distribution)
    │
    ▼
[Phase 5] Visual Proof & "Show, Don't Tell" (Maximize landing page conversion with shockproof proof)
```

---

## Phase 1 (Action #4): Agent Docility, Zero-Panic Guidance & Token Economy

### 1. Problem Statement
When LLM agents (Claude 3.7 Sonnet, GPT-4o, DeepSeek) encounter strict state machine errors (e.g. `TransitionError`, `GateError`), they frequently fail blindly, looping through arbitrary MCP tool calls, re-reading massive message context, and burning $1.00–$3.00 of API tokens per slice in wasted retries.

### 2. Objectives & Metrics
* **First-Turn Recovery Rate**: 100% of state-machine or policy rejections must tell the agent the exact tool and payload to invoke next.
* **Token Overhead Reduction**: Reduce average MCP round-trip token waste by **>60%**.
* **Zero Loop Panic**: Eliminate hallucinated recovery loops when a slice hits `BLOCKED` or `REMEDIATION`.

### 3. Deliverables & Technical Architecture
1. **Universal Structured Error Schema (`NextActionGuidance`)**:
   * Wrap all MCP and controller error outputs with actionable recovery fields:
     ```json
     {
       "error": "Cannot request review in state 'IMPLEMENTATION'.",
       "current_state": "IMPLEMENTATION",
       "legal_next_states": ["IMPLEMENTATION_READY_FOR_REVIEW"],
       "recommended_next_tool": "slice_run_tests",
       "required_arguments": { "slice": "S1" },
       "reason": "Deterministic gate requires an authoritative test receipt before review can be requested."
     }
     ```
   * Update `slice_orchestrator/tools.py` and `slice_orchestrator/mcp_server.py` to systematically wrap exceptions with `recovery_hint` and `next_recommended_tool`.
2. **Compact Agent Instruction Manifesto (`.slice/AGENT_RULES.md` / System Prompt)**:
   * Provide a hyper-dense (<40 lines) deterministic state sequence algorithm for agents.
   * Auto-inject this instruction file into MCP tool descriptions or project context during `slice init`.
3. **Macro-Tools / Fast-Track Compression**:
   * For non-critical bug fixes, empower `slice_fast_track_certify` to combine candidate capture, test receipt execution, and commit gate in a single round-trip.

### 4. Definition of Done (Exit Criteria)
* Automated test verifying that every invalid transition error returns a valid `recommended_next_tool` and `recovery_hint`.
* Token benchmark demonstrating a zero-panic recovery on intentional state errors.

---

## Phase 2 (Action #5): Enterprise Business Model & B2B Commercial Architecture

### 1. Problem Statement
Slice Orchestrator is 100% MIT-licensed and operates entirely locally via SQLite. Without a clear commercial capture layer, large enterprises and scale-ups can deploy it across 500 engineers with zero revenue returned to the project.

### 2. Commercial Tiering Model
```
┌────────────────────────────────────────────────────────────────────────┐
│                      SLICE ORCHESTRATOR TIERS                          │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Slice Open Core (MIT) - FREE FOR DEVELOPERS                         │
│    - Local CLI, 14 MCP tools, SQLite audit log, local HMAC receipts.   │
│                                                                        │
│ 2. Slice Teams & Enterprise - $19 / seat / month                       │
│    - Centralized GitHub App & CI Policy Engine.                        │
│    - Org-wide Scope Manifest rules (block PRs touching sensitive dirs).│
│    - Unified Manager Dashboard (track agent velocity vs code rot).    │
│                                                                        │
│ 3. Slice Compliance & Audit - $15k - $50k / year                       │
│    - EU AI Act (Art. 14) & SOC 2 Type II 1-click cryptographic audit.  │
│    - Non-repudiation export packages with hardware signature support.  │
└────────────────────────────────────────────────────────────────────────┘
```

### 3. Technical Deliverables for Commercial Readiness
1. **Portable Verification Evidence (`slice export --bundle-json`)**:
   * Decouple CI verification from local SQLite databases.
   * Enable agents to export a lightweight JSON cryptographic evidence bundle (`.slice-evidence.json`) committed into Git, allowing remote CI runners to verify HMACs without checking in `.orchestrator_slice/`.
2. **Commercial Bridge & Telemetry Interface (Opt-In)**:
   * Define clear webhook/export interfaces to pipe audit metrics into external security information and event management (SIEM) systems (Datadog, Splunk).

### 4. Definition of Done (Exit Criteria)
* `docs/pricing-and-architecture.md` published detailing the tiering, security boundaries, and enterprise readiness roadmap.
* Portable evidence bundle exporter implemented and covered by unit tests.

---

## Phase 3 (Action #2): Dual-Persona Alignment (Developer vs CISO/VP Eng)

### 1. Problem Statement
The developer fears speed bumps; the VP of Engineering fears catastrophic code rot. If the marketing speaks only to the dev, management won't buy. If it speaks only to the CISO, devs will resist adopting it.

### 2. Persona Alignment Strategy

| Angle | Developer Champion (User) | VP Engineering / CISO (Buyer) |
|---|---|---|
| **Core Fear** | "The orchestrator will slow my AI down." | "Junior devs will merge unreviewed AI hallucinations." |
| **Value Hook** | **The Shield**: "Get your PRs approved in 2 minutes because test receipts and scope are mathematically proven." | **The Guardrail**: "100% mechanical containment against scope creep, test tampering, and EU AI Act violations." |
| **Day-to-Day** | Frictionless: `slice init` runs once, agent handles tools. | Auditable: GitHub Actions gate fails closed on tampering. |

### 3. Deliverables
1. **Targeted Documentation Sections**:
   * Create `docs/enterprise-security.md` with compliance mappings (EU AI Act Art. 14, NIST SSDF SP 800-218, SOC 2).
   * Create `docs/developer-quickstart.md` emphasizing speed, clean PR approvals, and crash recovery.
2. **PR Bot Feedback Polish**:
   * Ensure `slice verify-pr` comments on GitHub PRs with clean, professional status badges that make engineering managers smile and approve instantly.

---

## Phase 4 (Action #1): Zero-Clone PyPI & `uvx` Instant Distribution

### 1. Problem Statement
Currently, a developer must clone the orchestrator repository to their machine to run `slice init`. This adds minutes of friction and kills 85% of top-of-funnel developer adoption.

### 2. Objectives
* Allow any developer globally to govern their repository in under 5 seconds with zero prerequisites other than `uv` or `pipx`:
  ```bash
  uvx slice-orchestrator init
  # or
  pipx run slice-orchestrator init
  ```

### 3. Deliverables
1. **PyPI Publishing Automation (`.github/workflows/publish-pypi.yml`)**:
   * Build clean wheel and source distributions via `uv build` / `hatchling`.
   * Automate Trusted Publishing (OIDC) to PyPI upon GitHub release tags (`v4.5.0`).
2. **Self-Contained Entrypoint & Binary Validation**:
   * Verify that `slice init` invoked via `uvx slice-orchestrator init` functions cleanly on cold directories without requiring external checkout paths.

### 4. Definition of Done (Exit Criteria)
* Successful release on PyPI.
* End-to-end verification that `uvx slice-orchestrator --version` and `uvx slice-orchestrator init` execute in a blank container in under 5 seconds.

---

## Phase 5 (Action #3): Visual Proof & "Show, Don't Tell" Asset Pipeline

### 1. Problem Statement
Engineers and tech leads scan GitHub READMEs for 5–10 seconds before deciding whether to star, try, or close the tab. Dense text does not convert. A visual demonstration of an agent being caught and blocked red-handed converts instantly.

### 2. Deliverables
1. **Automated VHS / Terminal Recording Script (`demo/demo_gate_tampering.tape`)**:
   * Use Charm's `vhs` or `terminalizer` to record a reproducible, crisp, high-framerate terminal animation:
     1. Prompt: *"Agent, fix bug in auth.py."*
     2. Agent sneaky action: Deletes failing test assertion in `tests/test_auth.py`.
     3. Execution: `slice_run_tests` / `slice_gate`.
     4. Result: **`[COMMIT GATE REJECTED]`** (Red alert: `TEST_TAMPERING_DETECTED - baseline test checksum mismatch`).
     5. Agent remediation: Restores test and fixes code properly.
     6. Result: **`[COMMIT GATE PASSED]`** (Green check with HMAC receipt).
2. **README Hero Placement**:
   * Embed the generated GIF/SVG directly below the main title and badge strip in `README.md`.

### 3. Definition of Done (Exit Criteria)
* Animated GIF (`assets/demo-tamper-proof.gif`) generated, compressed (<2.5 MB), and rendered in `README.md`.
