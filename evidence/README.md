# Evidence Directory

This directory will contain **actual runtime evidence** from orchestrator executions.

## Runtime Evidence Location

**Actual runtime evidence** from the integrated orchestrator is in:

```
.orchestrator_slice/          # State files
├── state.db                  # SQLite event store (20KB)
├── trusted_tail_anchor       # Cryptographic chain anchor
├── locks/                    # Concurrency locks
└── control_secret.key        # HMAC secret

.git/                         # Git history
├── logs/                     # Git operation logs
└── refs/                     # Commit references
```

**Git commits** (actual execution evidence):
- `c7a7198` - Initial integration (271 files, 43,647 lines)
- `ca51e6c` - Integration completion
- `1369f23` - Integration summary
- `618beaa` - Bundle cleanup
- `c401303` - Gitignore update
- `0faf93a` - Documentation archive

**Run ID**: `b4c2d03c-c55f-42d2-a30a-ec6c2f7b6e01`  
**Event Hash**: `2e8be7e41976e04b4dba767c23a8133f63b550e9fbb142735211c676d70f3534`  
**Sequence**: 1  
**State**: PLANNING  

---

## How to Generate Real Evidence

To generate actual runtime evidence:

```bash
# Initialize a slice
python3 -m slice_orchestrator.cli plan S1

# Check status (generates query evidence)
python3 -m slice_orchestrator.cli status S1

# Inspect events (generates audit trail)
python3 -m slice_orchestrator.cli inspect S1

# Run test suite (requires pytest)
pytest tests/ -v --tb=short

# Full dogfood run (requires worker adapter or explicit dummy)
python3 -m slice_orchestrator.cli run S1 --adapter dummy
```

**Real evidence includes**:
- ✅ Timestamps (from file system, git, SQLite)
- ✅ Run IDs (UUIDs generated at runtime)
- ✅ Event hashes (cryptographic integrity)
- ✅ State files (persistent across processes)
- ✅ Git commits (traceable changes)
- ✅ Test results (pytest output)

---

## Summary

All runtime evidence is stored in:
- `.orchestrator_slice/` - State files and event store
- `.git/` - Git history with commits
- Test results - `pytest tests/` output

**For citations**: Use integration reports and actual runtime artifacts.

**See also**:
- [DOGFOOD_IMPLEMENTATION_REVIEW.md](../DOGFOOD_IMPLEMENTATION_REVIEW.md) - Analysis revealing simulations
- [INTEGRATION_SUMMARY.md](../INTEGRATION_SUMMARY.md) - Actual integration results
- [ORCHESTRATOR_INTEGRATION_REPORT.md](../ORCHESTRATOR_INTEGRATION_REPORT.md) - Full integration evidence
