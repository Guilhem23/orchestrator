"""Priority 1 — workspace-digest stability, invalidation, remediation, cycles, restart, concurrency."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from slice_orchestrator.control_store import SliceLockManager
from slice_orchestrator.git_manager import CandidateTreeBuilder, compute_workspace_revision_digest, get_git_object_format
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.workers import TestDummyWorkerAdapter, WorkerRegistry


def _ctrl(repo_dir: Path, control_dir: Path, adapter: TestDummyWorkerAdapter | None = None) -> SliceRunController:
    registry = WorkerRegistry(allow_dummy_fallback=False)
    if adapter:
        registry.register(adapter)
    return SliceRunController(
        repo_dir, control_dir, worker_registry=registry, configured_adapter_id="dummy"
    )


def test_workspace_digest_stability_unchanged_content(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = _ctrl(repo_dir, control_dir)
    final = ctrl.run_to_completion("S1")
    assert final.state == "COMPLETE"
    assert final.workspace_revision_digest
    events = [e["event_type"] for e in ctrl.store.get_events() if e["slice"] == "S1"]
    assert events.count("ACCEPTANCE_INVALIDATED") == 0
    assert "COMMIT_RECORDED" in events
    assert "COMPLETE" == final.state


def test_workspace_digest_recapture_excludes_control_home(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    in_repo_home = repo_dir / ".orchestrator_slice"
    in_repo_home.mkdir(exist_ok=True)
    builder = CandidateTreeBuilder(repo_dir, in_repo_home)
    from slice_orchestrator.git_manager import get_head_commit_oid
    base = get_head_commit_oid(repo_dir)
    first = builder.capture_candidate_tree(base)
    (in_repo_home / "records").mkdir(exist_ok=True)
    (in_repo_home / "records" / "noise.json").write_text("{}", encoding="utf-8")
    (repo_dir / "tests" / "__pycache__").mkdir(exist_ok=True)
    (repo_dir / "tests" / "__pycache__" / "x.pyc").write_bytes(b"x")
    second = builder.capture_candidate_tree(base)
    assert first == second


def test_intentional_post_review_modification_invalidates(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = _ctrl(repo_dir, control_dir)
    while True:
        st = ctrl.step("S2")
        if st.state == "COMMIT_READY":
            break
        if st.is_terminal():
            pytest.fail(f"Reached terminal {st.state} before COMMIT_READY")
    (repo_dir / "src" / "impl.py").write_text("# tampered after review\n", encoding="utf-8")
    st = ctrl.step("S2")
    assert st.state == "IMPLEMENTATION_READY_FOR_REVIEW"
    events = [e["event_type"] for e in ctrl.store.get_events() if e["slice"] == "S2"]
    assert "ACCEPTANCE_INVALIDATED" in events


def test_remediation_followed_by_new_review(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    blocked = TestDummyWorkerAdapter(review_approval=False, blocking_findings=[{
        "finding_id": "F1",
        "description": "fix me",
        "required_remediation": "edit impl",
    }])
    ctrl = _ctrl(repo_dir, control_dir, blocked)
    st = ctrl.open_run("S3")
    while st.state not in ("REMEDIATION", "FAILED", "STOPPED", "COMPLETE"):
        st = ctrl.step("S3")
    assert st.state == "REMEDIATION"
    ctrl.worker_registry.register(TestDummyWorkerAdapter(review_approval=True))
    final = ctrl.run_to_completion("S3")
    assert final.state == "COMPLETE"
    events = [e["event_type"] for e in ctrl.store.get_events() if e["slice"] == "S3"]
    assert "REVIEW_BLOCKED" in events
    assert "REMEDIATION_ASSIGNED" in events
    assert "REVIEW_ACCEPTED" in events


def test_repeated_invalidation_then_max_cycles(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = _ctrl(repo_dir, control_dir)

    def mutate(_bundle):
        src = _bundle.workspace_dir / "src"
        src.mkdir(exist_ok=True)
        (src / "impl.py").write_text(f"# mutate {id(_bundle)}\n", encoding="utf-8")

    # After each review, mutate again before the gate by wrapping step
    while True:
        st = ctrl.step("S4")
        if st.state == "COMMIT_READY":
            (repo_dir / "src" / "impl.py").write_text(f"# drift {st.sequence}\n", encoding="utf-8")
        if st.is_terminal():
            break
    assert st.state == "STOPPED"
    assert st.stop_reason_code == "MAX_CYCLES_EXCEEDED"


def test_restart_during_invalidation_loop(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl1 = _ctrl(repo_dir, control_dir)
    st = ctrl1.open_run("S5")
    while st.state != "COMMIT_READY":
        st = ctrl1.step("S5")
        if st.is_terminal():
            pytest.fail(st.state)
    (repo_dir / "src" / "impl.py").write_text("# restart-drift\n", encoding="utf-8")
    st = ctrl1.step("S5")
    assert st.state == "IMPLEMENTATION_READY_FOR_REVIEW"
    high = st.review_cycle_high_water
    ctrl2 = _ctrl(repo_dir, control_dir)
    st2 = ctrl2.get_slice_state("S5")
    assert st2 is not None
    assert st2.state == "IMPLEMENTATION_READY_FOR_REVIEW"
    assert st2.review_cycle_high_water == high
    final = ctrl2.run_to_completion("S5")
    assert final.state in ("COMPLETE", "STOPPED")


def test_max_cycle_enforcement_stops_run(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = _ctrl(repo_dir, control_dir)
    st = ctrl.open_run("S6")
    while not st.is_terminal():
        if st.state == "COMMIT_READY":
            (repo_dir / "src" / "impl.py").write_text(f"# {st.sequence}\n", encoding="utf-8")
        st = ctrl.step("S6")
    assert st.state == "STOPPED"
    assert st.stop_reason_code == "MAX_CYCLES_EXCEEDED"
    seq = st.sequence
    st2 = ctrl.step("S6")
    assert st2.state == "STOPPED"
    assert st2.sequence == seq


def test_concurrent_execution_lock(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    lock_path = control_dir / "locks" / "S7.lock"
    errors: list[str] = []

    def rival():
        try:
            with SliceLockManager(lock_path):
                pass
        except RuntimeError as exc:
            errors.append(str(exc))

    with SliceLockManager(lock_path):
        t = threading.Thread(target=rival)
        t.start()
        t.join(timeout=5)
    assert errors
    assert "Slice lock already held" in errors[0]
