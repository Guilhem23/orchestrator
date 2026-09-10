# Adversarial Review Heuristics

These heuristics are distilled from the S4/S5/S8/S9 reviews and the orchestrator-method reviews.

## Trust and governance

- Is the claimed state actually authoritative, or only a writable file?
- Can an implementation agent modify the rules by which it is judged?
- Can approval be forged?
- Is acceptance tied to the exact reviewed revision?
- Can a later change survive an earlier approval?
- Can BLOCKED become COMMITTED through restart/retry/manual recovery?

## Data / authorization

- Does authorization happen before resource discovery?
- Can an alternate endpoint bypass the protected path?
- Can a missing context value accidentally mean “allow”?
- Can cross-workspace or cross-KB data leak?
- Does a cache make revocation stale?

## Persistence / concurrency

- Are there N+1 queries hidden behind ORM convenience?
- Does pagination happen before materialization?
- Are multiple pages evaluated in the same snapshot when required?
- Can two writers race on sequences or lifecycle transitions?
- Can restart produce a state that never legitimately existed?

## Evidence / benchmarks

- Does the benchmark actually measure the dataset described?
- Is the measured artifact the intended artifact?
- Is the benchmark using a real DB/engine rather than an in-memory shortcut?
- Do evidence counts match raw JUnit/test output?
- Are historical artifacts immutable?

## Product / architecture

- Are we solving the actual requirement or merely adding features?
- Is the architecture more complex than the current scale justifies?
- Is a derived projection accidentally becoming a source of truth?
- Is a future capability leaking prematurely into the current slice?
- Can we simplify while preserving the invariant?
