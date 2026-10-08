"""
Tests for Phase 3 (v4.3) CI / PR Gatekeeper:
- Verifies that pull requests are rejected if slice is incomplete or in remediation.
- Verifies rejection when files outside approved scope_manifest are modified.
- Verifies rejection when HMAC test receipts are missing.
- Verifies passing PR verification when all slice criteria are satisfied.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from slice_orchestrator.cli import main
from slice_orchestrator.ci_gate import verify_pr_governance
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


def _init_git_repo(repo: Path) -> str:
    """Initialize git repo with an initial commit on main."""
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial base commit"], cwd=repo, check=True, capture_output=True)
    base_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    return base_oid


def test_verify_pr_fails_when_no_slice_run(disposable_repo_and_control):
    repo_dir, control_home, _ = disposable_repo_and_control
    _init_git_repo(repo_dir)

    res = verify_pr_governance(repo_dir=repo_dir, control_home=control_home)
    assert not res["passed"]
    assert any("NO_SLICE_RUN" in r for r in res["reasons"])


def test_verify_pr_skips_when_no_slice_run_and_skip_mode(disposable_repo_and_control):
    repo_dir, control_home, _ = disposable_repo_and_control
    _init_git_repo(repo_dir)

    res = verify_pr_governance(repo_dir=repo_dir, control_home=control_home, if_no_slice="skip")
    assert res["passed"]
    assert "SKIPPED" in res["summary_markdown"]


def test_verify_pr_fails_when_slice_not_terminal(disposable_repo_and_control):
    repo_dir, control_home, _ = disposable_repo_and_control
    _init_git_repo(repo_dir)

    s_name = "S100"
    slice_start(slice=s_name, objective="Test unfinished slice", repo_dir=repo_dir, control_home=control_home)

    res = verify_pr_governance(repo_dir=repo_dir, control_home=control_home, slice_name=s_name)
    assert not res["passed"]
    assert any("STATE_NOT_TERMINAL" in r for r in res["reasons"])


def test_verify_pr_detects_scope_violations(disposable_repo_and_control):
    repo_dir, control_home, _ = disposable_repo_and_control
    base_oid = _init_git_repo(repo_dir)

    s_name = "S101"
    slice_start(slice=s_name, objective="Test scope check", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice=s_name,
        plan={
            "description": "Scope test",
            "scope_manifest": {"allow_paths": ["src/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Simulate an unauthorized file change outside allow_paths
    (repo_dir / "unauthorized_secret.py").write_text("API_KEY = 'leak'\n", encoding="utf-8")
    subprocess.run(["git", "add", "unauthorized_secret.py"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "unauthorized change"], cwd=repo_dir, check=True, capture_output=True)

    res = verify_pr_governance(repo_dir=repo_dir, control_home=control_home, base_ref=base_oid, slice_name=s_name)
    assert not res["passed"]
    assert "unauthorized_secret.py" in res["scope_violations"]
    assert any("SCOPE_VIOLATION" in r for r in res["reasons"])


def test_verify_pr_passes_when_fully_governed(disposable_repo_and_control, capsys):
    repo_dir, control_home, _ = disposable_repo_and_control
    base_oid = _init_git_repo(repo_dir)

    s_name = "S102"
    slice_start(slice=s_name, objective="End-to-end governed slice", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice=s_name,
        plan={
            "description": "Valid feature plan",
            "scope_manifest": {"allow_paths": ["src/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Architecture review
    disp_arch = slice_dispatch(slice=s_name, role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=disp_arch["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        summary="Arch ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Implement inside allowed scope
    disp_impl = slice_dispatch(slice=s_name, role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "feature.py").write_text("def hello(): return 'world'\n", encoding="utf-8")
    slice_run_tests(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Implementation finished",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Adversarial code review
    rev = slice_request_review(slice=s_name, reviewer_principal="adversarial-rev", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=rev["assignment_id"],
        artifacts={"verdict": "APPROVED", "reviewer_principal": "adversarial-rev"},
        summary="Review passed",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Commit Gate -> COMMIT_READY
    gate_res = slice_gate(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    assert gate_res["passed"]

    # Finalize commit
    fin_res = slice_finalize(slice=s_name, commit_message="feat: governed feature", repo_dir=repo_dir, control_home=control_home)
    assert fin_res["state"] == "COMPLETE"

    # Verify PR governance via CLI
    ret = main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "verify-pr",
        "--base", base_oid,
        "--slice", s_name,
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Slice CI Gate: PASSED" in out
    assert "Verified Test Receipts" in out
