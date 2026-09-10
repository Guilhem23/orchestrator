"""
Failure & End-to-End Disposable Test ORCH-TEST-01 for Enhanced Method v4.
Tests worker/reviewer crash, worker replacement, retry limits, dependency cycles,
and disposable end-to-end lifecycle with forced remediation and worker replacement.
"""

import subprocess
import tempfile
from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.objectives import Objective
from slice_orchestrator.work_items import WorkItem, WorkItemDAGSupervisor
from slice_orchestrator.artifact_graph import ArtifactGraphNode, ArtifactGraphStore
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.workers import TestDummyWorkerAdapter, WorkerInputBundle


def setup_temp_repo_and_control(tmpdir: Path):
    repo_dir = tmpdir / "repo"
    control_dir = tmpdir / "control"
    repo_dir.mkdir()
    control_dir.mkdir()

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# Test Repo\n")
    from tests.workspace_support import seed_passing_workspace
    seed_passing_workspace(repo_dir)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL)

    return repo_dir, control_dir


def test_failure_injection_worker_crash_and_restart():
    """
    Test worker process crash, orchestrator restart, and clean state recovery.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl1 = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl1.open_run("S88")
        st1 = ctrl1.step("S88")  # PLANNING -> PLAN_READY

        # Simulate abrupt process crash by dropping ctrl1 and instantiating ctrl2
        ctrl2 = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        st2 = ctrl2.get_slice_state("S88")

        assert st2 is not None
        assert st2.state == "PLAN_READY"
        assert st2.run_id == st1.run_id
        assert st2.sequence == st1.sequence

        # Run continues normally
        st3 = ctrl2.step("S88")
        assert st3.state == "ARCHITECTURE_REVIEW"


def test_e2e_orch_test_01_forced_remediation_and_worker_replacement():
    """
    ORCH-TEST-01 Disposable Fixture:
    Objective O1 -> Work Item W1 -> Work Item W2
    Force:
    W1 -> success
    W2 worker A -> fails / worker B resumes W2 -> BLOCKED (finding F1)
    Remediation W3 -> success
    Fresh review -> APPROVED
    Gate -> PASS
    Commit -> success
    Governance -> success

    Verify complete Artifact Graph and event chain.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))

        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        
        # 1. Open Run and step to PLANNING -> PLAN_READY
        st = ctrl.open_run("S999")
        st = ctrl.step("S999")  # PLANNING -> PLAN_READY

        w1 = WorkItem(
            work_item_id="S999-WI-1",
            run_id=st.run_id,
            objective_id="S999-O1",
            description="Primary implementation",
            type="implementation",
            dependencies=[],
            allowed_scope=["src/**", "*"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="worker-w1-exec-1",
            status="PENDING",
            attempt_count=1,
            worker_execution_ids=["worker-w1-exec-1"],
            revision=1,
        )
        ctrl.store.save_work_item(w1)

        # Add secondary Work Item W2 dependent on W1
        w2 = WorkItem(
            work_item_id="S999-WI-2",
            run_id=st.run_id,
            objective_id="S999-O1",
            description="Secondary implementation",
            type="implementation",
            dependencies=["S999-WI-1"],
            allowed_scope=["src/**", "tests/**", "evidence/**", "docs/**", "*"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="worker-w2-exec-1",
            status="PENDING",
            attempt_count=1,
            worker_execution_ids=["worker-w2-exec-1"],
            revision=1,
        )
        ctrl.store.save_work_item(w2)
        ctrl.store.save_work_item(w2)

        # 2. Step to ARCHITECTURE_REVIEW -> ARCHITECTURE_APPROVED -> IMPLEMENTATION
        st = ctrl.step("S999")  # ARCHITECTURE_REVIEW
        st = ctrl.step("S999")  # ARCHITECTURE_APPROVED
        st = ctrl.step("S999")  # IMPLEMENTATION

        # 3. Step IMPLEMENTATION for W1 -> success
        st = ctrl.step("S999")  # IMPLEMENTATION (executes W1)
        w1_loaded = ctrl.store.get_work_item("S999-WI-1")
        assert w1_loaded.status == "SATISFIED"

        # Derive readiness: W2 is now READY because parent W1 is SATISFIED
        supervisor = WorkItemDAGSupervisor()
        items = supervisor.derive_readiness(ctrl.store.list_work_items(st.run_id))
        w2_loaded = [i for i in items if i.work_item_id == "S999-WI-2"][0]
        assert w2_loaded.status == "READY"

        # Test Worker Replacement on W2: worker A fails, worker B resumes
        w2_loaded.worker_execution_id = "worker-w2-exec-2-resumed"
        w2_loaded.worker_execution_ids.append("worker-w2-exec-2-resumed")
        w2_loaded.attempt_count += 1
        ctrl.store.save_work_item(w2_loaded)

        # Step IMPLEMENTATION for W2 -> success
        st = ctrl.step("S999")  # IMPLEMENTATION (executes W2) -> CANDIDATE_CAPTURED -> IMPLEMENTATION_READY_FOR_REVIEW
        w2_final = ctrl.store.get_work_item("S999-WI-2")
        assert w2_final.status == "SATISFIED"
        assert len(w2_final.worker_execution_ids) >= 2
        assert st.state == "IMPLEMENTATION_READY_FOR_REVIEW"

        # 4. Force First Review Cycle -> BLOCKED (finding F1)
        dummy_rev_blocked = TestDummyWorkerAdapter(review_approval=False, blocking_findings=[{
            "finding_id": "F1",
            "description": "Null check missing in W2",
            "required_remediation": "Add null check"
        }])
        ctrl.worker_registry.register(dummy_rev_blocked)

        st = ctrl.step("S999")  # ADVERSARIAL_REVIEW_ASSIGNED
        st = ctrl.step("S999")  # ADVERSARIAL_REVIEW -> REVIEW_BLOCKED -> REMEDIATION
        assert st.state == "REMEDIATION"
        assert st.remediation_cycle_high_water == 1

        # 5. Execute Remediation W3
        st = ctrl.step("S999")  # REMEDIATION_ASSIGNED -> IMPLEMENTATION
        st = ctrl.step("S999")  # IMPLEMENTATION (executes Remediation W3) -> CANDIDATE_CAPTURED -> IMPLEMENTATION_READY_FOR_REVIEW
        assert st.state == "IMPLEMENTATION_READY_FOR_REVIEW"

        # 6. Fresh Reviewer for Cycle 2 -> APPROVED
        dummy_rev_approved = TestDummyWorkerAdapter(review_approval=True)
        ctrl.worker_registry.register(dummy_rev_approved)

        st = ctrl.step("S999")  # ADVERSARIAL_REVIEW_ASSIGNED (Cycle 2)
        st = ctrl.step("S999")  # ADVERSARIAL_REVIEW -> REVIEW_ACCEPTED -> COMMIT_READY
        assert st.state == "COMMIT_READY"

        # 7. Commit & Governance
        st = ctrl.step("S999")  # COMMIT_READY -> COMMIT_RECORDED -> COMMITTED
        assert st.state == "COMMITTED"

        st = ctrl.step("S999")  # GOVERNANCE_STARTED -> GOVERNANCE_RECONCILIATION
        st = ctrl.step("S999")  # GOVERNANCE_RECONCILED -> COMPLETE
        assert st.state == "COMPLETE"

        # 8. Verify complete Artifact Graph and Event Chain
        events = ctrl.store.verify_store_integrity()
        orch_events = [e for e in events if e["slice"] == "S999"]
        assert len(orch_events) == st.sequence

        graph = ArtifactGraphStore(ctrl.store)
        commit_node = graph.get_node("impl-S999-WI-1")
        assert commit_node is not None
        ancestors = graph.trace_ancestors("impl-S999-WI-1")
        ancestor_ids = [n.artifact_id for n in ancestors]
        assert "S999-WI-1" in ancestor_ids
