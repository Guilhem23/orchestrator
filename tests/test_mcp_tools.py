"""
Tests for Cursor-Native MCP Tools (slice_orchestrator/tools.py)

Covers unit testing of all 10 tools, full lifecycle orchestration,
authority boundaries, and error handling.
"""

from __future__ import annotations

import pytest
import subprocess
import uuid
from pathlib import Path

from slice_orchestrator import tools
from slice_orchestrator.orchestrator import OrchestratorError


@pytest.fixture
def disposable_repo_and_control(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    control_home = tmp_path / "control"
    control_home.mkdir(parents=True, exist_ok=True)

    # Init git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Copy policy bundle
    pkg_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    store_bundle = control_home / "policy_bundle"
    store_bundle.mkdir(parents=True, exist_ok=True)
    for f in pkg_bundle.glob("*"):
        if f.is_file():
            (store_bundle / f.name).write_bytes(f.read_bytes())

    # Create dummy files and initial commit
    (repo_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "main.py").write_text("def hello(): return 'world'\n")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    return repo_dir, control_home


def test_slice_start_creates_and_resumes_run(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    # Start new slice run
    res1 = tools.slice_start(
        slice="S100",
        objective="Implement feature X",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert res1["slice"] == "S100"
    assert res1["state"] == "PLANNING"
    assert res1["is_new_run"] is True
    assert res1["run_id"] is not None

    # Resume existing run
    res2 = tools.slice_start(
        slice="S100",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert res2["slice"] == "S100"
    assert res2["run_id"] == res1["run_id"]
    assert res2["is_new_run"] is False


def test_slice_context_returns_structured_pack(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    tools.slice_start(slice="S101", objective="Test context", repo_dir=repo_dir, control_home=control_home)
    ctx = tools.slice_context(slice="S101", repo_dir=repo_dir, control_home=control_home)

    assert ctx["slice"] == "S101"
    assert ctx["state"] == "PLANNING"
    assert len(ctx["objectives"]) == 1
    assert "PLAN_READY" in ctx["legal_next_transitions"]
    assert ctx["context_pack_digest"] is not None


def test_slice_grill_analyzes_objectives(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    tools.slice_start(slice="S102", objective="", repo_dir=repo_dir, control_home=control_home)
    grill_res = tools.slice_grill(slice="S102", objective="", repo_dir=repo_dir, control_home=control_home)

    assert len(grill_res["questions"]) > 0
    assert grill_res["questions"][0]["category"] == "ambiguity"


def test_slice_plan_submits_plan_and_advances_state(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    tools.slice_start(slice="S103", objective="Plan test", repo_dir=repo_dir, control_home=control_home)

    plan_data = {
        "description": "Add new component Y",
        "scope_manifest": {"allow_paths": ["src/main.py"]},
        "work_items": [
            {
                "work_item_id": "S103-WI1",
                "description": "Implement Y in src/main.py",
                "assigned_role": "IMPLEMENTER",
                "dependencies": [],
            }
        ],
    }

    res = tools.slice_plan(
        slice="S103",
        plan=plan_data,
        repo_dir=repo_dir,
        control_home=control_home,
    )

    assert res["slice"] == "S103"
    assert res["state"] == "PLAN_READY"
    assert res["plan_revision"] == 1
    assert res["work_items_created"] == 1


def test_slice_work_list_manages_items(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    tools.slice_start(slice="S104", objective="Work item test", repo_dir=repo_dir, control_home=control_home)

    # Create work item
    tools.slice_work_list(
        slice="S104",
        action="create",
        work_item={
            "work_item_id": "WI-1",
            "description": "First task",
            "assigned_role": "IMPLEMENTER",
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # List items
    wl = tools.slice_work_list(slice="S104", action="list", repo_dir=repo_dir, control_home=control_home)
    assert len(wl["work_items"]) == 1
    assert wl["work_items"][0]["work_item_id"] == "WI-1"
    assert "WI-1" in wl["ready_items"]


def test_slice_full_lifecycle_flow(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    # 1. slice_start
    start_res = tools.slice_start(slice="S200", objective="Full flow test", repo_dir=repo_dir, control_home=control_home)
    assert start_res["state"] == "PLANNING"

    # 2. slice_context
    ctx = tools.slice_context(slice="S200", repo_dir=repo_dir, control_home=control_home)
    assert ctx["exists"] is not False

    # 3. slice_grill
    grill = tools.slice_grill(slice="S200", objective="Full flow test", repo_dir=repo_dir, control_home=control_home)
    assert grill["grill_id"] is not None

    # 4. slice_plan
    plan_res = tools.slice_plan(
        slice="S200",
        plan={"description": "Full flow plan", "work_items": [{"work_item_id": "WI-1", "description": "Do x"}]},
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert plan_res["state"] == "PLAN_READY"

    # 5. slice_dispatch -> ARCHITECTURE_REVIEWER
    disp_arch = tools.slice_dispatch(slice="S200", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    assert disp_arch["state"] == "ARCHITECTURE_REVIEW"

    # 6. slice_record_result -> ARCHITECTURE_REVIEW_ACCEPTED
    rec_arch = tools.slice_record_result(
        slice="S200",
        assignment_id=disp_arch["assignment_id"],
        success=True,
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert rec_arch["state"] == "ARCHITECTURE_APPROVED"

    # 7. slice_dispatch -> IMPLEMENTER
    disp_impl = tools.slice_dispatch(slice="S200", role="IMPLEMENTER", work_item_id="WI-1", repo_dir=repo_dir, control_home=control_home)
    assert disp_impl["state"] == "IMPLEMENTATION"

    # 8. slice_record_result -> IMPLEMENTATION_COMPLETED
    rec_impl = tools.slice_record_result(
        slice="S200",
        assignment_id=disp_impl["assignment_id"],
        success=True,
        summary="Implemented WI-1",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert rec_impl["state"] == "IMPLEMENTATION_READY_FOR_REVIEW"

    # 9. slice_run_tests
    test_res = tools.slice_run_tests(slice="S200", repo_dir=repo_dir, control_home=control_home)
    assert test_res["receipt_id"] is not None

    # 10. slice_dispatch -> ADVERSARIAL_REVIEWER
    disp_adv = tools.slice_dispatch(slice="S200", role="ADVERSARIAL_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    assert disp_adv["state"] == "ADVERSARIAL_REVIEW"

    # 11. slice_record_result -> ADVERSARIAL_REVIEW_ACCEPTED
    rec_adv = tools.slice_record_result(
        slice="S200",
        assignment_id=disp_adv["assignment_id"],
        success=True,
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert rec_adv["state"] == "COMMIT_READY"

    # 12. slice_status & slice_report
    status = tools.slice_status(slice="S200", repo_dir=repo_dir, control_home=control_home)
    assert status["state"] == "COMMIT_READY"

    report = tools.slice_report(slice="S200", repo_dir=repo_dir, control_home=control_home)
    assert report["slice"] == "S200"
    assert report["total_events"] > 5


def test_slice_record_result_rejects_stale_or_invalid_assignment(disposable_repo_and_control):
    repo_dir, control_home = disposable_repo_and_control

    tools.slice_start(slice="S300", objective="Security test", repo_dir=repo_dir, control_home=control_home)

    with pytest.raises(OrchestratorError, match="not found"):
        tools.slice_record_result(
            slice="S300",
            assignment_id="nonexistent-asgn-id",
            success=True,
            repo_dir=repo_dir,
            control_home=control_home,
        )
