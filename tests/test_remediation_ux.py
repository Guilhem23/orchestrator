"""
Tests for Phase 2 (v4.2) Remediation UX enhancements:
- slice remediate --prompt outputs actionable Markdown prompt with findings
- slice resume on a REMEDIATION slice automatically invokes remediation workflow
- slice resume --with-packet displays structured remediation packet context
"""

from __future__ import annotations

import json
from pathlib import Path

from slice_orchestrator.cli import main
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.tools import (
    slice_start,
    slice_plan,
    slice_dispatch,
    slice_record_result,
    slice_run_tests,
    slice_request_review,
)


def _setup_blocked_slice(repo_dir: Path, control_home: Path, slice_name: str = "S90"):
    slice_start(slice=slice_name, objective="UX Remediation verification", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice=slice_name,
        plan={
            "description": "Remediation plan",
            "scope_manifest": {"allow_paths": ["src/**", "tests/**"]},
        },
        repo_dir=repo_dir,
        control_home=control_home,
    )
    # Arch review
    disp_arch = slice_dispatch(slice=slice_name, role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=slice_name,
        assignment_id=disp_arch["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        summary="Arch ok",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    # Implementation
    disp_impl = slice_dispatch(slice=slice_name, role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "demo.py").write_text("# Demo code\n")
    slice_run_tests(slice=slice_name, repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=slice_name,
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Impl done",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    # Review blocked
    rev = slice_request_review(slice=slice_name, reviewer_principal="adversarial-reviewer", repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=slice_name,
        assignment_id=rev["assignment_id"],
        artifacts={
            "verdict": "BLOCKED",
            "reviewer_principal": "adversarial-reviewer",
            "findings": [
                {
                    "finding_id": "UX-FIND-01",
                    "description": "Missing input validation in demo.py",
                    "required_remediation": "Validate input before processing",
                }
            ],
        },
        summary="Review blocked with findings",
        repo_dir=repo_dir,
        control_home=control_home,
    )


def test_cli_remediate_prompt_flag(disposable_repo_and_control, monkeypatch, capsys):
    repo_dir, control_home, _ = disposable_repo_and_control
    _setup_blocked_slice(repo_dir, control_home, "S90")

    monkeypatch.chdir(repo_dir)
    ret = main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "remediate", "S90",
        "--prompt",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "transitioned to IMPLEMENTATION" in out
    assert "UX-FIND-01" in out
    assert "=== Copy-Paste Prompt for Agent ===" in out
    assert "Remediation assignment" in out
    assert "Missing input validation in demo.py" in out


def test_cli_resume_auto_delegates_to_remediate(disposable_repo_and_control, monkeypatch, capsys):
    repo_dir, control_home, _ = disposable_repo_and_control
    _setup_blocked_slice(repo_dir, control_home, "S91")

    ctrl = SliceRunController(repo_dir, control_home)
    state = ctrl.get_slice_state("S91")
    assert state.state == "REMEDIATION"

    monkeypatch.chdir(repo_dir)
    # Running `slice resume S91` on REMEDIATION state should auto-trigger remediation
    ret = main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "resume", "S91",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "is currently in REMEDIATION. Initiating remediation workflow..." in out
    assert "transitioned to IMPLEMENTATION" in out

    # Verify slice is now in IMPLEMENTATION
    updated_state = ctrl.get_slice_state("S91")
    assert updated_state.state == "IMPLEMENTATION"


def test_cli_resume_with_packet_flag(disposable_repo_and_control, monkeypatch, capsys):
    repo_dir, control_home, _ = disposable_repo_and_control
    _setup_blocked_slice(repo_dir, control_home, "S92")

    ctrl = SliceRunController(repo_dir, control_home)
    # First remediate to move to IMPLEMENTATION
    main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "remediate", "S92",
    ])
    capsys.readouterr()

    # Now pause slice
    main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "pause", "S92",
    ])
    capsys.readouterr()

    # Resume with --with-packet
    ret = main([
        "--repo-dir", str(repo_dir),
        "--control-home", str(control_home),
        "resume", "S92",
        "--with-packet",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "=== Remediation Context Packet ===" in out
    assert "Cycle: 1" in out
