# Diagnostic Commands

**CLI entrypoint**: `slice` (`slice_orchestrator.cli`)

---

## `slice doctor`

Checks installation and control-plane health without mutating authority.

```bash
slice doctor
slice doctor --json
slice doctor --repo-dir /path/to/repo --control-home /path/to/.orchestrator_slice
```

Checks include: package install, project root, git repo, control home, database, schema/policy bundle, trust anchor, secret availability, event-chain integrity, runtime directories, MCP config presence, worker binary presence, pytest/git/python.

Exit codes:

* `0` — ok (warnings allowed)
* `1` — hard failure

---

## `slice diagnostics <slice>`

```bash
slice diagnostics S100
slice diagnostics S100 --json
```

Shows: current state, latest event, phase, active work item, blockers, pending clarifications, failed tests, failed gates, reviewer, stale assignments, next legal actions, evidence locations.

Exit codes: `0` ok, `1` missing slice, `2` corrupt state.

---

## `slice timeline <slice>`

```bash
slice timeline S100
slice timeline S100 --json
slice timeline S100 --phase implementation
slice timeline S100 --errors
```

Shows ordered events, timestamps, inter-event elapsed ms, phase durations, retries, worker replacements, reviews, remediations, state transitions, terminal outcome.

---

## `slice explain <slice>`

```bash
slice explain S100
slice explain S100 --json
slice explain S100 --legacy
```

Plain-language explanation from persisted facts. Labels:

* **Facts** — persisted state/events/receipts
* **INFERENCE:** — derived conclusions
* **RECOMMENDATION:** — suggested next action

Reports whether human input is required and lists possible actions.

---

## Related commands

```bash
slice metrics <slice>          # provenance-bearing metrics JSON
slice export <slice> --format json|markdown
slice compare --manual m.json --orchestrated o.json
```
