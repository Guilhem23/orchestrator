"""
Disposable Real Development Scenario Test for Cursor-Native MVP

Executes an end-to-end real development task on a disposable repository using
the 10 Cursor-native MCP tools, verifying source diffs, test receipts,
persisted events, state database, and control-plane authority.
"""

from __future__ import annotations

import subprocess
import pytest
from pathlib import Path

from slice_orchestrator import tools
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.gates import GateEvaluator


def test_disposable_real_development_scenario(tmp_path: Path):
    repo_dir = tmp_path / "disposable_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    control_home = repo_dir / ".orchestrator_slice"
    control_home.mkdir(parents=True, exist_ok=True)

    # 1. Initialize Git repository
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.name", "Scenario Developer"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo_dir, check=True)

    # Copy policy bundle
    pkg_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    store_bundle = control_home / "policy_bundle"
    store_bundle.mkdir(parents=True, exist_ok=True)
    for f in pkg_bundle.glob("*"):
        if f.is_file():
            (store_bundle / f.name).write_bytes(f.read_bytes())

    # Create initial files
    (repo_dir / ".gitignore").write_text(".orchestrator_slice/\n__pycache__/\n")
    (repo_dir / "pyproject.toml").write_text("[project]\nname='calc'\n")
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "tests").mkdir(parents=True, exist_ok=True)

    calc_code = """def add(a: int, b: int) -> int:
    return a + b
"""
    (repo_dir / "src" / "calc.py").write_text(calc_code)

    test_code = """from src.calc import add

def test_add():
    assert add(2, 3) == 5
"""
    (repo_dir / "tests" / "test_calc.py").write_text(test_code)

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    slice_name = "S500"

    # Step 1: slice_start
    start_res = tools.slice_start(
        slice=slice_name,
        objective="Add type validation to add function in src/calc.py",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert start_res["slice"] == slice_name
    assert start_res["state"] == "PLANNING"
    assert start_res["is_new_run"] is True

    # Step 2: slice_context
    ctx = tools.slice_context(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert ctx["state"] == "PLANNING"
    assert ctx["context_pack_digest"] is not None

    # Step 3: slice_grill
    grill = tools.slice_grill(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert grill["grill_id"] is not None

    # Step 4: slice_plan
    plan_data = {
        "description": "Add type validation to add() in src/calc.py and add corresponding test",
        "scope_manifest": {"allow_paths": ["src/calc.py", "tests/test_calc.py"]},
        "work_items": [
            {
                "work_item_id": "S500-WI-1",
                "description": "Implement type checks in add()",
                "type": "implementation",
                "assigned_role": "IMPLEMENTER",
                "dependencies": [],
            }
        ],
    }
    plan_res = tools.slice_plan(
        slice=slice_name,
        plan=plan_data,
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert plan_res["state"] == "PLAN_READY"
    assert plan_res["work_items_created"] == 1

    # Step 5: slice_dispatch -> ARCHITECTURE_REVIEWER
    disp_arch = tools.slice_dispatch(slice=slice_name, role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    assert disp_arch["state"] == "ARCHITECTURE_REVIEW"

    # Step 6: slice_record_result -> ARCHITECTURE_APPROVED
    rec_arch = tools.slice_record_result(
        slice=slice_name,
        assignment_id=disp_arch["assignment_id"],
        success=True,
        summary="Architecture review passed.",
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert rec_arch["state"] == "ARCHITECTURE_APPROVED"

    # Step 7: slice_dispatch -> IMPLEMENTER
    disp_impl = tools.slice_dispatch(slice=slice_name, role="IMPLEMENTER", work_item_id="S500-WI-1", repo_dir=repo_dir, control_home=control_home)
    assert disp_impl["state"] == "IMPLEMENTATION"

    # REAL CODE ACTION: Modify source and test files
    updated_calc_code = """def add(a: int, b: int) -> int:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Inputs must be numeric")
    return a + b
"""
    (repo_dir / "src" / "calc.py").write_text(updated_calc_code)

    updated_test_code = """import pytest
from src.calc import add

def test_add():
    assert add(2, 3) == 5

def test_add_type_error():
    with pytest.raises(TypeError):
        add("2", 3)
"""
    (repo_dir / "tests" / "test_calc.py").write_text(updated_test_code)

    # Step 8: slice_record_result -> IMPLEMENTATION_COMPLETED & CANDIDATE_CAPTURED
    rec_impl = tools.slice_record_result(
        slice=slice_name,
        assignment_id=disp_impl["assignment_id"],
        success=True,
        summary="Added TypeError validation and test case.",
        role_context_update={"paths": ["src/calc.py", "tests/test_calc.py"]},
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert rec_impl["state"] == "IMPLEMENTATION_READY_FOR_REVIEW"
    assert rec_impl["candidate_captured"] is True

    # Step 9: slice_run_tests -> Run control test
    test_res = tools.slice_run_tests(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert test_res["tests_passed"] is True
    assert test_res["receipt_id"] is not None

    # Step 10: slice_dispatch -> ADVERSARIAL_REVIEWER
    disp_adv = tools.slice_dispatch(slice=slice_name, role="ADVERSARIAL_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    assert disp_adv["state"] == "ADVERSARIAL_REVIEW"

    # Step 11: slice_record_result -> REVIEW_ACCEPTED
    rec_adv = tools.slice_record_result(
        slice=slice_name,
        assignment_id=disp_adv["assignment_id"],
        success=True,
        summary="Adversarial review passed. Validation is robust.",
        artifacts={"verdict": "APPROVED", "reviewer_principal": "independent-reviewer"},
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert rec_adv["state"] == "COMMIT_READY"

    # Step 12: slice_gate & slice_finalize over MCP tools
    gate_res = tools.slice_gate(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert gate_res["passed"] is True, f"Gate failed with reason: {gate_res.get('reason')}"

    final_res = tools.slice_finalize(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert final_res["finalized"] is True
    assert final_res["state"] == "COMPLETE"

    # Step 13: slice_status & slice_report
    status = tools.slice_status(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert status["state"] == "COMPLETE"
    assert status["is_terminal"] is True

    report = tools.slice_report(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    assert report["final_state"] == "COMPLETE"
    assert report["verdict"] == "COMPLETE"
    assert report["tests_passed"] >= 1

    # Independent Verifications:
    # 1. Source diff check
    calc_content = (repo_dir / "src" / "calc.py").read_text()
    assert "TypeError" in calc_content

    # 2. Test diff check
    test_content = (repo_dir / "tests" / "test_calc.py").read_text()
    assert "test_add_type_error" in test_content

    # 3. State database check
    controller = SliceRunController(repo_dir=repo_dir, control_home=control_home)
    events = controller.store.get_events()
    slice_events = [e for e in events if e.get("slice") == slice_name]
    assert len(slice_events) >= 8

    # 4. HMAC receipt check
    receipts = controller.store.list_receipts(slice_name=slice_name)
    assert len(receipts) >= 1
    assert receipts[0]["passed"] is True
