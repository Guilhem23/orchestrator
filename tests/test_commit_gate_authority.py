"""Priority 2 — authoritative commit gate and receipt binding."""

from __future__ import annotations

import pytest

from slice_orchestrator.control_store import ControlStore, ControlStoreError
from slice_orchestrator.gates import GateError, GateEvaluator, run_control_test
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.state_machine import SliceRunState


def _commit_ready_state(slice_name: str, run_id: str, **kwargs) -> SliceRunState:
    defaults = dict(
        slice=slice_name,
        run_id=run_id,
        project_id="proj-1",
        state="COMMIT_READY",
        approved_plan_digest="a" * 64,
        latest_review_record_id="rev-1",
        workspace_revision_digest="b" * 64,
    )
    defaults.update(kwargs)
    return SliceRunState(**defaults)


def test_commit_gate_rejects_passed_false(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    test_file = repo_dir / "test_fail.py"
    test_file.write_text("def test_fail(): assert False\n", encoding="utf-8")
    receipt = run_control_test(
        {"test_id": "t", "command": "pytest test_fail.py -q", "expected_exit_code": 0},
        repo_dir, "tree-x", "rev-x", store, slice_name="S1", run_id="run-1",
    )
    assert receipt["passed"] is False
    with pytest.raises(ControlStoreError, match="failure"):
        store.verify_test_receipt_integrity(receipt, require_passed=True)


def test_commit_gate_rejects_missing_receipt(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    st = ctrl.open_run("S8")
    store = ctrl.store
    store.store_record("ADVERSARIAL_REVIEW", "rev-1", {
        "schema_version": 4,
        "record_type": "ADVERSARIAL_REVIEW",
        "verdict": "APPROVED",
        "blocking_finding_count": 0,
    })
    ev = GateEvaluator(repo_dir, store)
    res = ev.evaluate_commit_gate(_commit_ready_state("S8", st.run_id, workspace_revision_digest=None))
    assert res.passed is False
    assert "receipt" in res.reason.lower()


def test_commit_gate_rejects_stale_receipt(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    (repo_dir / "test_sample.py").write_text("def test_pass(): assert True\n", encoding="utf-8")
    receipt = run_control_test(
        {"test_id": "t", "command": "pytest test_sample.py -q"},
        repo_dir, "OLD-TREE", "OLD-REV", store, slice_name="S1", run_id="run-1",
    )
    assert receipt["passed"] is True
    with pytest.raises(ControlStoreError, match="tree"):
        store.verify_test_receipt_integrity(
            receipt, expected_slice="S1", expected_run_id="run-1",
            expected_tree="NEW-TREE", expected_digest="OLD-REV",
        )


def test_commit_gate_rejects_receipt_from_other_slice(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    (repo_dir / "test_sample.py").write_text("def test_pass(): assert True\n", encoding="utf-8")
    receipt = run_control_test(
        {"test_id": "t", "command": "pytest test_sample.py -q"},
        repo_dir, "tree-1", "rev-1", store, slice_name="S1", run_id="run-1",
    )
    with pytest.raises(ControlStoreError, match="slice"):
        store.verify_test_receipt_integrity(receipt, expected_slice="S2", expected_run_id="run-1")


def test_commit_gate_rejects_receipt_from_other_run(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    (repo_dir / "test_sample.py").write_text("def test_pass(): assert True\n", encoding="utf-8")
    receipt = run_control_test(
        {"test_id": "t", "command": "pytest test_sample.py -q"},
        repo_dir, "tree-1", "rev-1", store, slice_name="S1", run_id="run-1",
    )
    with pytest.raises(ControlStoreError, match="run"):
        store.verify_test_receipt_integrity(receipt, expected_slice="S1", expected_run_id="run-OTHER")


def test_commit_gate_rejects_empty_command(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    with pytest.raises(GateError, match="EMPTY_TEST_COMMAND"):
        run_control_test({"test_id": "t", "command": ""}, repo_dir, "t", "r", store)
    with pytest.raises(GateError, match="EMPTY_TEST_COMMAND"):
        run_control_test({"test_id": "t"}, repo_dir, "t", "r", store)


def test_commit_gate_rejects_expected_exit_code_abuse(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    with pytest.raises(GateError, match="EXPECTED_EXIT_CODE_ABUSE"):
        run_control_test(
            {"test_id": "t", "command": "python3 -c 'import sys; sys.exit(7)'", "expected_exit_code": 7},
            repo_dir, "t", "r", store,
        )


def test_commit_gate_rejects_fabricated_receipt(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    fake = {
        "schema_version": 4,
        "passed": True,
        "environment_digest": "deadbeef",
        "authorized_gate_execution": True,
        "slice": "S1",
        "run_id": "run-1",
        "candidate_tree_oid": "tree",
        "workspace_revision_digest": "rev",
    }
    with pytest.raises(ControlStoreError, match="signed|HMAC|fabricated"):
        store.verify_test_receipt_integrity(fake)


def test_complete_impossible_with_failed_tests(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    (repo_dir / "tests" / "test_ok.py").write_text("def test_ok(): assert False\n", encoding="utf-8")
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    final = ctrl.run_to_completion("S9")
    assert final.state == "FAILED"
    assert final.stop_reason_code == "TESTS_FAILED"
    events = [e["event_type"] for e in ctrl.store.get_events() if e["slice"] == "S9"]
    assert "COMMIT_RECORDED" not in events
    assert "GOVERNANCE_RECONCILED" not in events
