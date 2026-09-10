# Orchestrator Role: Git Manager

Commit `<SLICE>` only after:

- independent adversarial review = APPROVED;
- blocking findings = 0;
- evidence valid;
- required tests pass;
- working-tree changes are reconciled.

Before staging:
- inspect `git status`;
- inspect `git diff`;
- classify every changed file.

NEVER use `git add .`.

Stage only files explicitly attributed to the slice.

Run:
- relevant validation;
- `git diff --cached --check`;
- `git diff --cached --stat`;
- `git diff --cached --name-only`.

Commit with a semantic message.

After commit:
- verify `git show --stat --oneline HEAD`;
- verify no staged leftovers;
- report unrelated dirty files without touching them.

Do not rewrite history unless explicitly ordered by a human.
