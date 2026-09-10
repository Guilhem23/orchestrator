"""
Regression Tests for Priority 2 — M5 Proof Verification Fail-Closed Behavior.
"""

from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.gates import run_control_test, GateError, GateEvaluator, GateEvaluationResult
from slice_orchestrator.state_machine import SliceRunState


def test_proof_verification_genuine_passing_tests(disposable_repo_and_control):
    """Scenario 6: Genuine passing tests produce passed=True receipt."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    # Create a passing test file
    test_file = repo_dir / "test_sample.py"
    test_file.write_text("def test_pass(): assert True\n")

    test_def = {"test_id": "test_pass", "command": "pytest test_sample.py -q", "expected_exit_code": 0}
    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is True
    assert receipt["exit_code"] == 0


def test_proof_verification_genuine_failing_tests(disposable_repo_and_control):
    """Scenario 7: Genuine failing tests produce passed=False receipt."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    # Create a failing test file
    test_file = repo_dir / "test_sample.py"
    test_file.write_text("def test_fail(): assert False\n")

    test_def = {"test_id": "test_fail", "command": "pytest test_sample.py -q", "expected_exit_code": 0}
    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is False
    assert receipt["exit_code"] != 0


def test_proof_verification_missing_binary(disposable_repo_and_control):
    """Scenario 1: Missing command/binary produces failed receipt (exit code 127)."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    test_def = {"test_id": "test_missing", "command": "nonexistent_binary_cmd_xyz123 --test", "expected_exit_code": 0}
    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is False
    assert receipt["exit_code"] != 0


def test_proof_verification_timeout(disposable_repo_and_control, monkeypatch):
    """Scenario 2: Test execution timeout produces failed receipt."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    # Execute sleep command with 1s timeout
    test_def = {"test_id": "test_timeout", "command": "sleep 30", "expected_exit_code": 0}
    
    import subprocess
    orig_run = subprocess.run
    def fast_timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep 30", timeout=1)

    monkeypatch.setattr(subprocess, "run", fast_timeout_run)

    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is False
    assert receipt["exit_code"] == 124


def test_proof_verification_test_command_failure(disposable_repo_and_control):
    """Scenario 3: Non-zero exit code produces failed receipt."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    test_def = {"test_id": "test_cmd_fail", "command": "python3 -c 'import sys; sys.exit(1)'", "expected_exit_code": 0}
    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is False
    assert receipt["exit_code"] == 1


def test_proof_verification_thrown_exception(disposable_repo_and_control, monkeypatch):
    """Scenario 4: Thrown exception during subprocess execution produces failed receipt."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    def raise_runtime_error(*args, **kwargs):
        raise RuntimeError("Subprocess execution engine internal crash")

    import subprocess
    monkeypatch.setattr(subprocess, "run", raise_runtime_error)

    test_def = {"test_id": "test_exception", "command": "python3 -c 'print(1)'", "expected_exit_code": 0}
    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is False
    assert receipt["exit_code"] == 1


def test_proof_verification_malformed_output(disposable_repo_and_control, monkeypatch):
    """Scenario 5: Malformed output or unexpected exit code fails closed."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    test_def = {"test_id": "test_malformed", "command": "python3 -c 'import sys; sys.exit(99)'", "expected_exit_code": 0}
    receipt = run_control_test(test_def, repo_dir, "tree-1", "rev-1", store)

    assert receipt["passed"] is False
    assert receipt["exit_code"] == 99


def test_proof_verification_empty_command_rejected(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    with pytest.raises(GateError, match="EMPTY_TEST_COMMAND"):
        run_control_test({"test_id": "empty", "command": ""}, repo_dir, "tree-1", "rev-1", store)


def test_proof_verification_expected_exit_code_abuse(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    with pytest.raises(GateError, match="EXPECTED_EXIT_CODE_ABUSE"):
        run_control_test(
            {"test_id": "abuse", "command": "python3 -c 'import sys; sys.exit(7)'", "expected_exit_code": 7},
            repo_dir, "tree-1", "rev-1", store,
        )
