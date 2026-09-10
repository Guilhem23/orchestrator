# Orchestrator Dogfood Test Project

A tiny generic project deliberately designed to exercise the development
orchestrator rather than Knowledge Fabric.

## Product intent

Build a small configuration service that validates configuration files and
provides a deterministic JSON report.

## Constraints

- Keep the implementation simple.
- No external services.
- No database.
- No network access required.
- Maintain backwards compatibility for the CLI.
- Tests are part of the acceptance evidence.

## Deliberate challenges

The project contains a few planted problems:

1. A hidden bug in configuration validation.
2. An unnecessary architectural opening that can tempt over-engineering.
3. A documentation requirement that is intentionally underspecified.
4. A safe opportunity to improve test coverage.

The orchestrator should discover these through its normal process rather than
being told exactly how to fix them.
