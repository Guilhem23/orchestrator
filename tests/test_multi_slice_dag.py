"""
Tests for Phase 4 (v4.4) Enterprise Multi-Slice DAG:
- Verifies that gate fails when prerequisite slice is incomplete (DAG_DEPENDENCY_UNSATISFIED).
- Verifies that gate passes once prerequisite slice reaches COMPLETE.
- Verifies `slice graph` CLI command output and JSON representation.
"""

from __future__ import annotations

import json
from pathlib import Path

from slice_orchestrator.cli import main
from slice_orchestrator.tools import (
    slice_start,
    slice_plan,
    slice_dispatch,
    slice_record_result,
    slice_run_tests,
    slice_request_review,
    slice_gate,
    slice_finalize,
)


def _complete_slice(repo_dir: Path, control_home: Path, s_name: str, file_rel: str):
    """Drive a simple slice to COMPLETE state."""
    slice_start(slice=s_name, objective=f"Complete {s_name}", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice=s_name,
        plan={
            "description": f"Plan for {s_name}",
            "scope_manifest": {"allow_paths": ["src/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )
    disp_arch = slice_dispatch(slice=s_name, role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=disp_arch["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        summary="Arch ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    disp_impl = slice_dispatch(slice=s_name, role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    fpath = repo_dir / file_rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(f"# Implemented {s_name}\n")
    slice_run_tests(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Impl ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    rev = slice_request_review(slice=s_name, reviewer_principal="rev-tester", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=rev["assignment_id"],
        artifacts={"verdict": "APPROVED", "reviewer_principal": "rev-tester"},
        summary="Rev ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    gate = slice_gate(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    assert gate["passed"], f"Gate failed for {s_name}: {gate.get('reason')}"
    fin = slice_finalize(slice=s_name, commit_message=f"feat: complete {s_name}", repo_dir=repo_dir, control_home=control_home)
    assert fin["state"] == "COMPLETE"


def test_dag_dependency_blocks_gate_when_prerequisite_incomplete(disposable_repo_and_control):
    repo_dir, control_home, _ = disposable_repo_and_control

    # 1. Start Slice S110, but do not complete it (leave in PLANNING)
    slice_start(slice="S110", objective="Prerequisite foundation", repo_dir=repo_dir, control_home=control_home)

    # 2. Start Slice S120 which depends on Slice S110
    slice_start(slice="S120", objective="Dependent feature", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice="S120",
        plan={
            "description": "Plan for S120 with dependency on S110",
            "slice_dependencies": ["S110"],
            "scope_manifest": {"allow_paths": ["src/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )
    disp_arch = slice_dispatch(slice="S120", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice="S120",
        assignment_id=disp_arch["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        summary="Arch ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    disp_impl = slice_dispatch(slice="S120", role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "b.py").write_text("# Feature B\n")
    slice_run_tests(slice="S120", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice="S120",
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Impl ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    rev = slice_request_review(slice="S120", reviewer_principal="rev-tester", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice="S120",
        assignment_id=rev["assignment_id"],
        artifacts={"verdict": "APPROVED", "reviewer_principal": "rev-tester"},
        summary="Rev ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # 3. Gate evaluation on S120 must fail closed because S110 is not COMPLETE
    gate_res = slice_gate(slice="S120", repo_dir=repo_dir, control_home=control_home)
    assert not gate_res["passed"]
    assert "DAG_DEPENDENCY_UNSATISFIED" in gate_res["reason"]
    assert "Prerequisite slice 'S110'" in gate_res["reason"]


def test_dag_dependency_passes_when_prerequisite_is_complete(disposable_repo_and_control):
    repo_dir, control_home, _ = disposable_repo_and_control

    # 1. First complete S110
    _complete_slice(repo_dir, control_home, "S110", "src/a.py")

    # 2. Then drive S120 which depends on S110
    slice_start(slice="S120", objective="Dependent feature", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice="S120",
        plan={
            "description": "Plan for S120 with dependency on completed S110",
            "slice_dependencies": ["S110"],
            "scope_manifest": {"allow_paths": ["src/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )
    disp_arch = slice_dispatch(slice="S120", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice="S120",
        assignment_id=disp_arch["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        summary="Arch ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    disp_impl = slice_dispatch(slice="S120", role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "b.py").write_text("# Feature B\n")
    slice_run_tests(slice="S120", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice="S120",
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Impl ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    rev = slice_request_review(slice="S120", reviewer_principal="rev-tester", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice="S120",
        assignment_id=rev["assignment_id"],
        artifacts={"verdict": "APPROVED", "reviewer_principal": "rev-tester"},
        summary="Rev ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # 3. Gate evaluation on S120 must pass because S110 is COMPLETE
    gate_res = slice_gate(slice="S120", repo_dir=repo_dir, control_home=control_home)
    assert gate_res["passed"]
    assert gate_res["reason"] == "All deterministic gate checks passed"


def test_cli_graph_command(disposable_repo_and_control, capsys):
    repo_dir, control_home, _ = disposable_repo_and_control

    # Create slice S1 and slice S2 (depends on S1)
    slice_start(slice="S1", objective="Slice 1", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice="S1",
        plan={"description": "Plan 1", "scope_manifest": {"allow_paths": ["src/**"]}},
        repo_dir=repo_dir,
        control_home=control_home,
    )

    slice_start(slice="S2", objective="Slice 2", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice="S2",
        plan={
            "description": "Plan 2",
            "slice_dependencies": ["S1"],
            "scope_manifest": {"allow_paths": ["src/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Test human graph output
    ret = main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "graph",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Multi-Slice Dependency DAG" in out
    assert "S1" in out
    assert "S2 (depends on: S1)" in out

    # Test JSON graph output
    ret_json = main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "graph",
        "--json",
    ])
    assert ret_json == 0
    raw_json = capsys.readouterr().out
    data = json.loads(raw_json)
    assert "nodes" in data
    assert "edges" in data
    assert any(e["from"] == "S1" and e["to"] == "S2" for e in data["edges"])
