# Changelog

All notable changes to **Slice Orchestrator** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — Target 1.0.0 (General Availability)

### Planned
- Hosted Cryptographic PR Verifier backend (GitHub App SaaS root-of-trust).
- Centralized Context Bus multi-tenant cloud service.
- Executive compliance dashboard (EU AI Act Article 14, SOC 2 Type II audit logs).

---

## [0.5.0] - 2026-10-08

### Added
- **Developer Armor & One-Click Auto-Fix**: Added `slice remediate --auto-fix` and `slice_remediate(auto_fix=True)` in MCP, automatically reverting tampered baseline tests and cleaning up unauthorized out-of-scope files.
- **Binary Mutant Arbitrage Engine**: Added `MutantArbitrageEngine` to replace subjective LLM debates with executable boundary and invariant unit tests evaluated strictly via binary exit codes (0/1).
- **Heterogeneous Inference Router**: Added `InferenceRouter` with cloud-first API defaults (Anthropic, OpenAI, Gemini) and transparent localhost Ollama/vLLM fallback in < 500 ms.
- **Enterprise Shared Context Bus**: Added `SharedContextBus` to synchronize agent memories, architectural decisions, and active scope locks across multi-developer teams.
- **Predictive Multi-Agent Git Conflict Engine**: Added `MultiAgentConflictEngine` detecting overlapping file modifications and predicting branch merge collisions before PR creation.
- **Viral Demo Command**: Added `slice demo` benchmarking live test tampering interception in 125 ms (< 200 ms requirement).
- **Release Automation**: Added `.github/workflows/publish.yml` with automated PyPI Trusted Publishing (OIDC).
- **Semantic Versioning Enforcement**: Added `.github/workflows/semver-check.yml` to mechanically guarantee SemVer 2.0.0 conformity across all commits.

### Changed
- Standardized release versioning to **Semantic Versioning (0.5.0)** for public open-source distribution.
- Unified master roadmap, architecture blueprint, and strategic plan into `docs/strategic-execution-plan.md`.
- Expanded automated regression test suite to **278 passed tests**.

---

## [0.4.0] - 2026-10-01

### Added
- **Multi-Slice Dependency DAG**: Added `slice graph` (ASCII & JSON) and `slice_dependencies` plan validation to block downstream slices until prerequisites reach `COMPLETE`.
- **Adaptive Governance Profiles**: Added `fast-track` governance profile for low-complexity bugfixes while maintaining full cryptographic anchoring.
- **Zero-Friction Project Onboarding**: Added `slice init` detecting language ecosystems and generating `.slice.toml`, `.mcp.json`, and `.gitignore` in under 3 seconds.

---

## [0.3.0] - 2026-09-25

### Added
- **Zero-Trust CI / PR Gatekeeper**: Added composite GitHub Action (`action.yml`) and CLI command `slice verify-pr` to verify Git diffs and HMAC test receipts on Pull Requests.
- **Structured Remediation Loop**: Added `slice remediate --prompt` generating copy-paste Markdown remediation context packets for implementer agents.
- **Resume with Packet**: Added `slice resume --with-packet` for frictionless state recovery from `REVIEW_BLOCKED` to `IMPLEMENTATION`.

---

## [0.2.0] - 2026-09-18

### Added
- **Universal Polyglot Engine (`.slice.toml`)**: Added target repository configuration support for Python, Node/TypeScript, Rust, and Go.
- **Dynamic Test Runner**: Replaced hardcoded test invocations with configurable commands, custom exit code assertions, and virtualenv auto-discovery.

---

## [0.1.0] - 2026-09-11

### Added
- **Core SDLC Governance Engine**: Initial public release of Slice Orchestrator.
- **14 Governed MCP Tools**: Full lifecycle from `slice_start` to `slice_finalize` compatible with Cursor Chat and Claude Code.
- **Deterministic Quality Gates**: Scope manifest AST enforcement and authoritative baseline test checksumming.
- **Immutable SQLite Control Store**: Crash-proof event sourcing with append-only HMAC-SHA256 signature chains.
