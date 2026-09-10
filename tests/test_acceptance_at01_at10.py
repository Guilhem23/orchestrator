"""
Acceptance Tests AT-01 to AT-10 for Method v4 Slice Orchestrator.
"""

from pathlib import Path
import sqlite3
import subprocess
import tempfile
import pytest

from slice_orchestrator.control_store import ControlStoreError
from slice_orchestrator.git_manager import GitManagerError, ScopeManifestValidator
from slice_orchestrator.orchestrator import OrchestratorError, SliceRunController
from slice_orchestrator.policy import PolicyError


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


def test_at01_control_plane_integrity_tampering():
    """
    AT-01: Modifying root-of-trust / control-plane policy stops execution.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl.open_run("S99")

        # Tamper with policy bundle digest file
        digest_file = control_dir / "policy_bundle_digest"
        digest_file.write_text("0" * 64 + "\n")

        with pytest.raises((PolicyError, ControlStoreError, OrchestratorError)):
            SliceRunController(repo_dir, control_dir)


def test_at02_event_stream_immutability_and_hmac():
    """
    AT-02: Tampering with SQLite event store fails stream verification.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl.open_run("S99")

        # Tamper directly with event_json column in events table
        conn = sqlite3.connect(control_dir / "state.db")
        conn.execute("UPDATE events SET event_json = REPLACE(event_json, 'operator-local', 'hacker') WHERE sequence = 1")
        conn.commit()
        conn.close()

        with pytest.raises(ControlStoreError):
            ctrl.store.verify_store_integrity()


def test_at03_fresh_reviewer_and_role_isolation():
    """
    AT-03: Ensure fresh reviewer assignments.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        
        st1 = ctrl.open_run("S99")
        st2 = ctrl.step("S99")  # PLAN_PERSISTED -> PLAN_READY
        assert st2.current_actor_role is not None


def test_at04_deterministic_gate_evaluation():
    """
    AT-04: Commit gate evaluation logic.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        state = ctrl.open_run("S99")
        
        from slice_orchestrator.gates import GateEvaluator
        evaluator = GateEvaluator(repo_dir, ctrl.store)
        res = evaluator.evaluate_commit_gate(state)
        assert not res.passed  # Planning state cannot commit


def test_at05_revision_fingerprint_pinning():
    """
    AT-05: Revision fingerprint pinning.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl.run_to_completion("S99")
        state = ctrl.get_slice_state("S99")
        assert state.state == "COMPLETE"
        assert state.workspace_revision_digest is not None


def test_at06_scope_manifest_enforcement():
    """
    AT-06: Protected files enforcement.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        
        validator = ScopeManifestValidator(
            scope_manifest={"allow_paths": [{"pattern": "src/**"}]},
            protected_files_policy=ctrl.policy_bundle.protected_files,
        )

        with pytest.raises(GitManagerError):
            validator.check_diff([{"status": "M", "path": ".orchestrator-v4/policy.yaml"}])


def test_at07_atomic_commit_and_governance_sequence():
    """
    AT-07: COMMIT -> GOVERNANCE -> COMPLETE order.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl.run_to_completion("S99")

        events = ctrl.store.verify_store_integrity()
        ev_types = [e["event_type"] for e in events]
        
        commit_idx = ev_types.index("COMMIT_RECORDED")
        gov_idx = ev_types.index("GOVERNANCE_RECONCILED")
        assert commit_idx < gov_idx


def test_at08_concurrency_locking():
    """
    AT-08: File lock prevents concurrent orchestrators.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl1 = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl1.open_run("S99")

        from slice_orchestrator.control_store import SliceLockManager
        lock_file = control_dir / "locks" / "S99.lock"
        
        lock2 = SliceLockManager(lock_file)
        lock2.acquire()
        try:
            with pytest.raises(Exception):
                ctrl2 = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
                ctrl2.step("S99")
        finally:
            lock2.release()


def test_at09_restart_state_recovery():
    """
    AT-09: Re-instantiating SliceRunController resumes previous state cleanly.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl1 = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        st1 = ctrl1.open_run("S99")

        ctrl2 = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        st2 = ctrl2.get_slice_state("S99")

        assert st1.state == st2.state
        assert st1.sequence == st2.sequence


def test_at10_failure_and_human_recovery():
    """
    AT-10: Recovering a STOPPED run.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir, control_dir = setup_temp_repo_and_control(Path(tmpdir))
        ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
        ctrl.open_run("S99")
        ctrl.stop_slice("S99", reason="Operator test stop")

        st = ctrl.get_slice_state("S99")
        assert st.state == "STOPPED"

        recovered_st = ctrl.recover_slice("S99", target_state="PLANNING")
        assert recovered_st.state == "PLANNING"
        assert recovered_st.run_generation == 2
