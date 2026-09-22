# Run Export Format

**Schema**: `run-export-v1`  
**Module**: `slice_orchestrator/observability/export.py`

---

## Commands

```bash
slice export <slice> --format json
slice export <slice> --format markdown
slice export <slice> --format json --output /path/to/exports
```

Default output root: `<control_home>/exports/<slice>/<UTC-timestamp>/`  
If the directory exists, a numeric suffix is used. Prior exports are never overwritten. Each directory includes `IMMUTABLE.txt`.

---

## Package contents

| Section | Description |
|---|---|
| `schema_version` | `run-export-v1` |
| `objective` / `requirements` | Objectives + clarification records |
| `plan` / `work_items` / `assignments` | Persisted records |
| `event_timeline` / `events` | Ordered timeline + redacted events |
| `worker_executions` | Assignment lifecycle events |
| `tests` / `reviews` / `remediations` | Receipts and review/remediation records |
| `gates` | Digest/evidence summary (evaluation remains control-plane) |
| `errors` | Stop/failure events |
| `metrics` | Full provenance-bearing metrics report |
| `evidence_references` | Control-home paths |
| `final_state` | Projected terminal/current state |
| `integrity` | Event hashes, stream tail, `export_digest` |
| `limitations` | Explicit non-claims |

---

## Guarantees

* Readable without the original database (self-contained JSON)
* Event order preserved
* Secrets / MACs / full prompts redacted
* `export_digest` binds redacted payload content
* Markdown companion summarizes timeline + metrics for humans
