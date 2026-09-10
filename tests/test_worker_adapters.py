"""
Tests for worker protocol, dummy adapter, manual adapter, Cursor adapter, Claude adapter, and Gemini adapter.
"""

from pathlib import Path
import tempfile
import pytest

from slice_orchestrator.workers import (
    ClaudeCodeWorkerAdapter,
    CursorWorkerAdapter,
    GeminiWorkerAdapter,
    ManualWorkerAdapter,
    TestDummyWorkerAdapter,
    WorkerInputBundle,
    WorkerRegistry,
)


def test_test_dummy_worker_adapter():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        adapter = TestDummyWorkerAdapter()
        bundle = WorkerInputBundle(
            assignment_id="a1",
            run_id="r1",
            slice="S99",
            role="PLANNER",
            prompt="Plan task",
            base_commit_oid="sha1:" + "0" * 40,
            workspace_dir=tmp,
            output_dir=tmp,
        )
        res = adapter.run(bundle)
        assert res.success
        assert res.role == "PLANNER"
        assert "plan" in res.artifacts


def test_manual_worker_adapter(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        adapter = ManualWorkerAdapter()
        bundle = WorkerInputBundle(
            assignment_id="a1",
            run_id="r1",
            slice="S99",
            role="IMPLEMENTER",
            prompt="Implement task",
            base_commit_oid="sha1:" + "0" * 40,
            workspace_dir=tmp,
            output_dir=tmp,
        )
        res = adapter.run(bundle)
        assert res.success is False
        assert res.availability == "UNAVAILABLE"
        captured = capsys.readouterr()
        assert "MANUAL WORKER REQUIRED" in captured.out


def test_worker_registry():
    registry = WorkerRegistry()
    assert registry.get("dummy") is not None
    assert registry.get("cursor") is not None
    assert registry.get("claude") is not None
    assert registry.get("gemini") is not None
    assert registry.get("manual") is not None
