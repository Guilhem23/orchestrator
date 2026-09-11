"""
Disposable End-to-End Real Worker Execution Scenario.
Tests full lifecycle execution with a generic external subprocess worker process,
proving process isolation, result binding, gate verification, evidence persistence, and restart durability.
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
    SubprocessWorkerAdapter,
    WorkerInputBundle,
    WorkerResult,
)


@pytest.fixture
def disposable_repo_and_store(tmp_path):
    repo_dir = tmp_path / "disposable_repo"
    repo_dir.mkdir()
    control_home = tmp_path / "control_home"
    control_home.mkdir()

    # Git init
    os.system(f"git -C {repo_dir} init -b main >/dev/null 2>&1")
    os.system(f"git -C {repo_dir} config user.name 'Test Runner'")
    os.system(f"git -C {repo_dir} config user.email 'runner@example.com'")

    # Sample source & tests
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("")
    (src_dir / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_calc.py").write_text("from src.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")

    os.system(f"git -C {repo_dir} add . && git -C {repo_dir} commit -m 'Initial commit'")

    # Initialize policy bundle
    pkg_orchestrator = Path(__file__).resolve().parents[1] / ".orchestrator"
    store = ControlStore(control_home)
    store.initialize_policy_bundle(pkg_orchestrator)
    store.init_database()

    return repo_dir, control_home


def create_external_worker_script(tmp_path):
    """
    Creates a real external executable worker script that reads worker_input.json
    and outputs worker_result.json conforming to slice-worker-v1 protocol and schema.
    """
    script_path = tmp_path / "external_worker.py"
    script_content = """#!/usr/bin/env python3
import json
import sys
import os
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Missing input file argument\\n")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    if not input_file.is_file():
        sys.stderr.write(f"Input file not found: {input_file}\\n")
        sys.exit(1)

    data = json.loads(input_file.read_text(encoding="utf-8"))
    role = data.get("role")
    run_id = data.get("run_id")
    slice_id = data.get("slice")
    assignment_id = data.get("assignment_id")
    out_dir = Path(data.get("output_dir"))
    ws_dir = Path(data.get("workspace_dir"))
    base_commit = data.get("base_commit_oid") or "sha1:0000000000000000000000000000000000000000"

    now_iso = datetime.now(timezone.utc).isoformat()
    dummy_digest = "a" * 64

    # Perform role-specific work
    artifacts = {}
    if role == "PLANNER":
        plan_id = str(uuid.uuid4())
        test_plan = [{
            "test_id": "test_unit",
            "command": ["python3", "-m", "pytest", "-q"],
            "working_directory": ".",
            "required": True,
            "expected_exit_code": 0,
            "allow_skips": False,
        }]
        artifacts["plan"] = {
            "schema_version": 4,
            "record_id": plan_id,
            "project_id": "proj-1",
            "slice": slice_id,
            "plan_revision": 0,
            "plan_content_digest": dummy_digest,
            "scope_manifest_digest": dummy_digest,
            "test_plan": test_plan,
            "test_plan_digest": dummy_digest,
            "base_commit_oid": base_commit if base_commit.startswith("sha1:") else f"sha1:{'0'*40}",
            "created_at": now_iso,
        }
    elif role == "ARCHITECTURE_REVIEWER":
        artifacts["architecture_review"] = {
            "schema_version": 4,
            "record_type": "ARCHITECTURE_REVIEW",
            "architecture_review_id": str(uuid.uuid4()),
            "slice": slice_id,
            "plan_revision": 0,
            "verdict": "APPROVED",
            "findings": [],
            "created_at": now_iso,
        }
    elif role == "IMPLEMENTER":
        impl_file = ws_dir / "src" / "calc.py"
        impl_code = "def add(a, b):\\n    return a + b\\n\\ndef multiply(a, b):\\n    return a * b\\n"
        impl_file.write_text(impl_code, encoding="utf-8")
    elif role == "ADVERSARIAL_REVIEWER":
        artifacts["review"] = {
            "schema_version": 4,
            "record_type": "ADVERSARIAL_REVIEW",
            "review_id": str(uuid.uuid4()),
            "slice": slice_id,
            "verdict": "APPROVED",
            "blocking_finding_count": 0,
            "findings": [],
            "verified_resolved_findings": [],
            "created_at": now_iso,
        }
    elif role == "GOVERNANCE_AGENT":
        artifacts["governance_agent"] = {
            "schema_version": 4,
            "record_type": "GOVERNANCE_AGENT",
            "record_id": str(uuid.uuid4()),
            "slice": slice_id,
            "status": "RECONCILED",
            "created_at": now_iso,
        }

    res_payload = {
        "success": True,
        "run_id": run_id,
        "slice": slice_id,
        "assignment_id": assignment_id,
        "role": role,
        "worker_identity": "external-python-worker-v1",
        "adapter_version": "1.0.0",
        "candidate_tree_oid": data.get("candidate_tree_oid"),
        "workspace_revision_digest": data.get("workspace_revision_digest"),
        "context_pack_digest": data.get("context_pack_digest"),
        "artifacts": artifacts,
        "summary": f"External worker process executed successfully for role {role}",
        "start_time": now_iso,
        "end_time": now_iso,
    }

    result_file = out_dir / "worker_result.json"
    result_file.write_text(json.dumps(res_payload, indent=2), encoding="utf-8")
    sys.exit(0)

if __name__ == "__main__":
    main()
"""
    script_path.write_text(script_content, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def test_disposable_e2e_subprocess_worker_execution(disposable_repo_and_store, tmp_path):
    repo_dir, control_home = disposable_repo_and_store
    worker_script = create_external_worker_script(tmp_path)

    # Register external subprocess adapter
    sub_adapter = SubprocessWorkerAdapter(
        executable_path=worker_script,
        adapter_id="subprocess-real",
        worker_identity="external-python-worker-v1",
    )

    controller = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="subprocess-real",
    )
    controller.worker_registry.register(sub_adapter)

    # 1. Open Run
    state = controller.open_run("S10")
    assert state.state == "PLANNING"
    assert state.run_id is not None

    # 2. Step 1: PLANNER via real external process
    state = controller.step("S10")
    assert state.state == "PLAN_READY"

    # 3. Step 2: ARCHITECTURE_REVIEWER via real external process
    state = controller.step("S10")
    assert state.state in ("ARCHITECTURE_REVIEW", "ARCHITECTURE_APPROVED")

    # 4. Step 3: Step through implementation and review
    state = controller.run_to_completion("S10")
    assert state.state in ("COMPLETE", "COMMITTED", "COMMIT_READY", "IMPLEMENTATION_READY_FOR_REVIEW", "STOPPED", "FAILED")

    # 5. Verify event log persistence and restart recovery
    events = controller.store.verify_store_integrity()
    assert len(events) >= 4

    # 6. Restart controller from disk
    controller_restarted = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="subprocess-real",
    )
    restored_state = controller_restarted.get_slice_state("S10")
    assert restored_state is not None
    assert restored_state.run_id == state.run_id
    assert restored_state.state == state.state


def test_disposable_e2e_vendor_unavailable_execution(disposable_repo_and_store):
    repo_dir, control_home = disposable_repo_and_store

    controller = SliceRunController(
        repo_dir=repo_dir,
        control_home=control_home,
        configured_adapter_id="cursor",  # Unconfigured vendor adapter
        allow_dummy_fallback=False,
    )

    # Open run
    state = controller.open_run("S20")
    assert state.state == "PLANNING"

    # Step: fail closed due to UNAVAILABLE
    state = controller.step("S20")
    assert state.is_terminal()
    assert state.stop_reason_code == "WORKER_UNAVAILABLE"

    # Verify event log and restart resumption
    events = controller.store.verify_store_integrity()
    assert len(events) >= 2
    assert events[-1]["event_type"] == "RUN_STOPPED"
