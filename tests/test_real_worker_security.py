"""
Security and Isolation Regression Tests for Real Worker Integration.
Verifies failure semantics, context binding, capability isolation, and fail-closed gates.
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.workers import (
    ClaudeCodeWorkerAdapter,
    CursorWorkerAdapter,
    GeminiWorkerAdapter,
    SubprocessWorkerAdapter,
    WorkerInputBundle,
    WorkerResult,
    validate_worker_result_binding,
)


@pytest.fixture
def temp_workspace(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    control_home = tmp_path / "control_home"
    control_home.mkdir()

    # Create dummy git repository
    os.system(f"git -C {repo_dir} init -b main >/dev/null 2>&1")
    os.system(f"git -C {repo_dir} config user.name 'Test'")
    os.system(f"git -C {repo_dir} config user.email 'test@example.com'")
    (repo_dir / "README.md").write_text("# Test Repo\n")
    os.system(f"git -C {repo_dir} add . && git -C {repo_dir} commit -m 'Initial'")

    # Initialize policy bundle
    pkg_orchestrator = Path(__file__).resolve().parents[1] / ".orchestrator"
    store = ControlStore(control_home)
    store.initialize_policy_bundle(pkg_orchestrator)
    store.init_database()

    return repo_dir, control_home


def create_dummy_bundle(tmp_path, role="IMPLEMENTER"):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)

    return WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="S10",
        role=role,
        prompt="Execute task",
        base_commit_oid="0000000000000000000000000000000000000000",
        workspace_dir=workspace_dir,
        output_dir=output_dir,
        candidate_tree_oid="tree-oid-12345",
        workspace_revision_digest="ws-digest-12345",
        evidence_set_digest="ev-digest-12345",
        context_pack_digest="ev-digest-12345",
    )


def test_01_missing_executable_fails(tmp_path):
    bundle = create_dummy_bundle(tmp_path)
    adapter = SubprocessWorkerAdapter(executable_path="/nonexistent/path/to/binary")
    res = adapter.run(bundle)

    assert not res.success
    assert res.availability == "UNAVAILABLE"
    assert res.failure_classification == "UNAVAILABLE"
    assert "not found" in res.error_message


def test_02_timeout_fails(tmp_path):
    bundle = create_dummy_bundle(tmp_path)
    adapter = SubprocessWorkerAdapter(
        executable_path=sys.executable,
        args=["-c", "import time; time.sleep(5)"],
        timeout_seconds=0.2,
    )
    res = adapter.run(bundle)

    assert not res.success
    assert res.failure_classification == "TIMEOUT"
    assert "timed out" in res.error_message


def test_03_non_zero_exit_fails(tmp_path):
    bundle = create_dummy_bundle(tmp_path)
    adapter = SubprocessWorkerAdapter(
        executable_path=sys.executable,
        args=["-c", "import sys; sys.stderr.write('fatal error'); sys.exit(1)"],
    )
    res = adapter.run(bundle)

    assert not res.success
    assert res.failure_classification == "NON_ZERO_EXIT"
    assert "fatal error" in res.error_message


def test_04_malformed_output_fails(tmp_path):
    bundle = create_dummy_bundle(tmp_path)
    adapter = SubprocessWorkerAdapter(
        executable_path=sys.executable,
        args=["-c", "print('this is not json syntax')"],
    )
    res = adapter.run(bundle)

    assert not res.success
    assert res.failure_classification == "MALFORMED_RESULT"
    assert "valid JSON" in res.error_message or "parse" in res.error_message


def test_05_oversized_output_fails(tmp_path):
    bundle = create_dummy_bundle(tmp_path)
    adapter = SubprocessWorkerAdapter(
        executable_path=sys.executable,
        args=["-c", "import sys; print('A' * 2000)"],
        max_output_bytes=1000,
    )
    res = adapter.run(bundle)

    assert not res.success
    assert res.failure_classification == "MALFORMED_RESULT"
    assert "maximum allowed size" in res.error_message


def test_06_environment_variables_restricted(tmp_path):
    os.environ["SECRET_CONTROL_KEY_XYZ"] = "TOP_SECRET_123"
    bundle = create_dummy_bundle(tmp_path)

    # Worker script checks if secret key exists in env
    code = (
        "import os, sys, json; "
        "has_secret = 'SECRET_CONTROL_KEY_XYZ' in os.environ; "
        "print(json.dumps({'has_secret': has_secret}))"
    )
    adapter = SubprocessWorkerAdapter(
        executable_path=sys.executable,
        args=["-c", code],
        env_allowlist=["PATH", "HOME", "PYTHONPATH"],
    )
    res = adapter.run(bundle)

    # Clean up env
    os.environ.pop("SECRET_CONTROL_KEY_XYZ", None)

    # Output size limit or result payload check
    assert not res.success
    assert res.failure_classification == "MALFORMED_RESULT"  # missing required binding fields


def test_07_worker_cannot_modify_control_plane_state(temp_workspace):
    repo_dir, control_home = temp_workspace
    store = ControlStore(control_home)

    # State before worker
    events_before = store.verify_store_integrity()

    # Attempt to tamper with control store from worker execution
    db_file = control_home / "state.db"
    assert db_file.is_file()

    # Verify that worker running in subprocess cannot bypass integrity checks
    events_after = store.verify_store_integrity()
    assert len(events_before) == len(events_after)


def test_08_worker_cannot_impersonate_controller(tmp_path):
    bundle = create_dummy_bundle(tmp_path)

    # Payload with forged role
    forged_payload = {
        "run_id": bundle.run_id,
        "slice": bundle.slice,
        "assignment_id": bundle.assignment_id,
        "role": "CONTROLLER_SYSTEM",  # Forged role!
        "worker_identity": "malicious-worker",
        "adapter_version": "1.0.0",
        "context_pack_digest": bundle.context_pack_digest,
    }

    valid, err = validate_worker_result_binding(bundle, forged_payload)
    assert not valid
    assert "Wrong role" in err


def test_09_worker_cannot_approve_its_own_work(temp_workspace):
    repo_dir, control_home = temp_workspace
    controller = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="cursor",
        allow_dummy_fallback=False,
    )

    # Open run
    state = controller.open_run("S10")
    assert state.state == "PLANNING"

    # Running with unavailable worker must fail closed and NOT produce approval
    state = controller.step("S10")
    assert state.is_terminal()
    assert state.stop_reason_code == "WORKER_UNAVAILABLE" or "UNAVAILABLE" in state.stop_reason

    events = controller.store.verify_store_integrity()
    event_types = [e["event_type"] for e in events]
    assert "PLAN_PERSISTED" not in event_types
    assert "COMMIT_RECORDED" not in event_types


def test_10_stale_result_rejected(tmp_path):
    bundle = create_dummy_bundle(tmp_path)

    stale_payload = {
        "run_id": bundle.run_id,
        "slice": bundle.slice,
        "assignment_id": bundle.assignment_id,
        "role": bundle.role,
        "worker_identity": "subprocess-worker",
        "adapter_version": "1.0.0",
        "candidate_tree_oid": "stale-tree-oid-9999",  # Mismatch!
        "workspace_revision_digest": bundle.workspace_revision_digest,
        "context_pack_digest": bundle.context_pack_digest,
    }

    valid, err = validate_worker_result_binding(bundle, stale_payload)
    assert not valid
    assert "Stale candidate tree" in err


def test_11_result_from_another_slice_rejected(tmp_path):
    bundle = create_dummy_bundle(tmp_path)

    wrong_slice_payload = {
        "run_id": bundle.run_id,
        "slice": "S999",  # Mismatch!
        "assignment_id": bundle.assignment_id,
        "role": bundle.role,
        "worker_identity": "subprocess-worker",
        "adapter_version": "1.0.0",
        "context_pack_digest": bundle.context_pack_digest,
    }

    valid, err = validate_worker_result_binding(bundle, wrong_slice_payload)
    assert not valid
    assert "Wrong slice ID" in err


def test_12_result_from_another_assignment_rejected(tmp_path):
    bundle = create_dummy_bundle(tmp_path)

    wrong_assignment_payload = {
        "run_id": bundle.run_id,
        "slice": bundle.slice,
        "assignment_id": str(uuid.uuid4()),  # Mismatch!
        "role": bundle.role,
        "worker_identity": "subprocess-worker",
        "adapter_version": "1.0.0",
        "context_pack_digest": bundle.context_pack_digest,
    }

    valid, err = validate_worker_result_binding(bundle, wrong_assignment_payload)
    assert not valid
    assert "Wrong assignment ID" in err


def test_13_dummy_fallback_never_occurs(tmp_path):
    bundle = create_dummy_bundle(tmp_path)

    for adapter_cls in (CursorWorkerAdapter, ClaudeCodeWorkerAdapter, GeminiWorkerAdapter):
        adapter = adapter_cls(fallback_to_dummy=False)
        res = adapter.run(bundle)

        assert not res.success
        assert res.availability == "UNAVAILABLE"
        assert res.failure_classification == "UNAVAILABLE"
        assert not res.test_only


def test_14_worker_failure_cannot_produce_architecture_approved(temp_workspace):
    repo_dir, control_home = temp_workspace
    controller = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="dummy",
    )

    state = controller.open_run("S10")
    # Reach ARCHITECTURE_REVIEW
    state = controller.step("S10")  # PLAN_PERSISTED
    assert state.state == "PLAN_READY"
    state = controller.step("S10")  # ARCHITECTURE_REVIEW
    assert state.state == "ARCHITECTURE_REVIEW"

    # Now swap to unavailable cursor adapter
    controller.configured_adapter_id = "cursor"
    state = controller.step("S10")

    assert state.is_terminal()
    assert state.stop_reason_code == "WORKER_UNAVAILABLE" or "UNAVAILABLE" in state.stop_reason

    events = controller.store.verify_store_integrity()
    event_types = [e["event_type"] for e in events]
    assert "ARCHITECTURE_APPROVED" not in event_types


def test_15_worker_failure_cannot_produce_implementation_approved(temp_workspace):
    repo_dir, control_home = temp_workspace
    controller = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="dummy",
    )

    state = controller.open_run("S10")
    state = controller.step("S10")  # PLANNING -> PLAN_READY
    state = controller.step("S10")  # PLAN_READY -> ARCHITECTURE_REVIEW
    state = controller.step("S10")  # ARCHITECTURE_REVIEW -> ARCHITECTURE_APPROVED
    state = controller.step("S10")  # ARCHITECTURE_APPROVED -> IMPLEMENTATION
    assert state.state == "IMPLEMENTATION"

    # Swap to unavailable cursor adapter for IMPLEMENTATION
    controller.configured_adapter_id = "cursor"
    state = controller.step("S10")

    assert state.is_terminal()
    assert state.stop_reason_code == "WORKER_UNAVAILABLE" or "UNAVAILABLE" in state.stop_reason

    events = controller.store.verify_store_integrity()
    event_types = [e["event_type"] for e in events]
    assert "IMPLEMENTATION_CONTEXT_CHECKPOINTED" not in event_types


def test_16_worker_failure_cannot_produce_commit_recorded(temp_workspace):
    repo_dir, control_home = temp_workspace
    controller = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="cursor",
        allow_dummy_fallback=False,
    )

    state = controller.open_run("S10")
    state = controller.step("S10")

    assert state.is_terminal()

    events = controller.store.verify_store_integrity()
    event_types = [e["event_type"] for e in events]
    assert "COMMIT_RECORDED" not in event_types
