# Method v4 Deterministic Path Semantics

Identifier: `git_pathspec_v1`

This is a deliberately restricted, controller-owned glob language. It is not
the full Git pathspec language and MUST NOT be delegated to shell expansion.

## Canonical paths

- Paths are repository-root-relative UTF-8 strings normalized to Unicode NFC.
- `/` is the only separator.
- Matching is case-sensitive on every host.
- Absolute paths, `.`/`..` segments, empty segments, NUL/control characters,
  backslashes, and trailing `/` are rejected.
- The controller rejects two repository paths that collide after NFC
  normalization or case folding, even on a case-sensitive host.
- Symlinks are matched as Git entries. Matching never follows a symlink.
- Submodules, nested Git repositories, sparse-checkout ambiguity, and
  implementation-supplied `.git` files/directories are rejected unless a future
  policy version defines them explicitly.

## Pattern grammar

Supported:

- literal UTF-8 characters other than glob metacharacters;
- `*` inside one segment, matching zero or more non-`/` characters;
- a complete `**` segment, matching zero or more complete path segments.

Forbidden:

- `?`, character classes, brace expansion, extglob, negation;
- Git pathspec magic such as `:(...)`, `:/`, attributes, or exclude rules;
- shell variables, command substitution, escapes, and platform-specific
  separators;
- catch-all patterns `*`, `**`, and `**/*`.

Patterns are compiled by the controller, not passed to a shell or Git.

## Classification

- Every changed path must match exactly one effective allow rule after protected
  deny rules are applied.
- Protected deny rules always win.
- Multiple matching allow rules are valid only when category and operation sets
  are identical; otherwise classification is ambiguous and fails closed.
- A rename is evaluated as delete permission on the source plus add permission
  on the destination.
- A mode change requires `mode_change` permission even when content is
  unchanged.
- Type changes between file, symlink, directory, and Git special entry require
  delete plus add permission and may still be denied by protected policy.

## Diff input

Scope validation consumes the controller-computed complete diff between the
trusted base tree and captured candidate tree. It never trusts status text,
an implementation index, or a list supplied by an agent.

## Portability

The same normalized path list and policy must produce the same classification
on Linux, macOS, Windows, Cursor, Claude Code, and manual runs. If the host
cannot represent or preserve a canonical path safely, capture fails closed.
