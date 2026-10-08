"""
Tests for Slice Orchestrator v5 Phase 2:
- Shared Context Bus (SharedContextBus)
- Predictive Multi-Agent Git Conflict Engine (MultiAgentConflictEngine)
- Enterprise Hosted Trust Anchor validation
"""

from pathlib import Path
import pytest

from slice_orchestrator.context_bus import SharedContextBus, SharedMemoryEntry
from slice_orchestrator.git_conflict_engine import MultiAgentConflictEngine, BranchScope


def test_shared_context_bus_broadcast_and_query(tmp_path: Path):
    bus_file = tmp_path / "enterprise_bus.sqlite"
    bus = SharedContextBus(bus_file)

    entry = SharedMemoryEntry(
        entry_id="mem_001",
        category="decision",
        author_agent="claude-code-worker-1",
        slice="S1",
        target_paths=["src/auth/token.py"],
        payload={"decision": "Use Ed25519 for JWT signatures"},
    )
    bus.broadcast_memory(entry)

    results = bus.query_memories(category="decision")
    assert len(results) == 1
    assert results[0].entry_id == "mem_001"
    assert results[0].payload["decision"] == "Use Ed25519 for JWT signatures"


def test_shared_context_bus_scope_contention(tmp_path: Path):
    bus_file = tmp_path / "enterprise_bus.sqlite"
    bus = SharedContextBus(bus_file)

    # Agent 1 locks auth module
    lock_entry = SharedMemoryEntry(
        entry_id="lock_s1",
        category="scope_lock",
        author_agent="agent-alpha",
        slice="S1",
        target_paths=["src/auth/jwt.py", "src/auth/models.py"],
        payload={"status": "in_progress"},
    )
    bus.broadcast_memory(lock_entry)

    # Agent 2 proposes overlapping slice S2
    warnings = bus.detect_scope_contention(
        current_slice="S2",
        current_agent="agent-beta",
        proposed_paths=["src/auth/jwt.py", "src/billing/checkout.py"],
    )
    assert len(warnings) == 1
    assert warnings[0].overlapping_paths == ["src/auth/jwt.py"]
    assert warnings[0].conflicting_slice == "S1"
    assert warnings[0].warning_type == "CONCURRENT_SCOPE_COLLISION"


def test_multi_agent_conflict_engine_predicts_overlaps(tmp_path: Path):
    engine = MultiAgentConflictEngine(tmp_path)

    branch_a = BranchScope(
        branch_name="feature/user-auth",
        slice="S1",
        agent_id="cursor-1",
        changed_files=["src/auth.py", "src/db.py"],
    )
    branch_b = BranchScope(
        branch_name="feature/payment-gate",
        slice="S2",
        agent_id="cursor-2",
        changed_files=["src/billing.py", "src/db.py"],  # Overlaps on src/db.py
    )
    branch_c = BranchScope(
        branch_name="feature/docs-update",
        slice="S3",
        agent_id="claude-1",
        changed_files=["docs/readme.md"],  # Clean
    )

    report = engine.analyze_branches([branch_a, branch_b, branch_c])
    assert report.total_branches_analyzed == 3
    assert report.conflict_count == 1
    pred = report.predictions[0]
    assert pred.has_conflict is True
    assert pred.conflicting_files == ["src/db.py"]
    assert "feature/user-auth" in pred.conflicting_branches
    assert "feature/payment-gate" in pred.conflicting_branches
