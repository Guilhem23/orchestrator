# Slice Orchestrator Constitution

You are operating inside a governed vertical-slice workflow.

The orchestrator coordinates work; it does not grant acceptance.

## Absolute rules

- Never silently broaden scope.
- Never declare a slice accepted unless the independent adversarial gate says `APPROVED`.
- Never override `BLOCKED` with judgement.
- Never overwrite historical review/evidence artifacts.
- Never start the next slice before the current slice is committed and governance is reconciled.
- Never use client/model context as trusted authorization input.
- Never use broad Git commands that can stage unrelated work.
- Stop and report when attribution or scope is ambiguous.

## Context portability

Assume the next agent has NO access to previous chat messages.
All necessary context MUST be available from repository files named in the prompt.

This constitution must work in Cursor, Claude Code, or manual execution.
