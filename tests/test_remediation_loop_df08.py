"""
Tests for remediation loop fluidification and DF-08 review-blocked resolution.
Verifies that review-blocked slices generate structured remediation packets,
disallow erroneous review requests with helpful guidance, and smoothly resume
implementation via slice_remediate and the CLI.
"""

from __future__ import annotations

import argparse
import pytest
from pathlib import Path

from slice_orchestrator.orchestrator import OrchestratorError, SliceRunController
from slice_orchestrator.tools import (
    slice_start,
    slice_plan,
    slice_dispatch,
    slice_record_result,
    slice_run_tests,
    slice_request_review,
    slice_remediate,
    slice_gate,
    slice_finalize,
)
from slice_orchestrator.cli import cmd_remediate
from slice_orchestrator.observability.diagnostics import build_explain


def test_slice_record_result_creates_remediation_packet_on_blocked_review(disposable_repo_and_control):
    """
    Recording a BLOCKED review result must persist a REMEDIATION_PACKET record,
    create a remediation work item, populate state.latest_remediation_packet_id,
    and return an actionable next_action directing to slice_remediate.
    """
    repo_dir, control_home, _ = disposable_repo_and_control
    s_name = "S80"

    slice_start(slice=s_name, objective="Test remediation creation", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice=s_name,
        plan={
            "description": "Remediation test plan",
            "scope_manifest": {"allow_paths": ["src/**", "tests/**"]},
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
        summary="Arch approved",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Implementation
    disp_impl = slice_dispatch(slice=s_name, role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "impl.py").write_text("# initial impl\n")
    slice_run_tests(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Initial implementation done",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Adversarial review dispatch
    rev_res = slice_request_review(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    assert rev_res["role"] == "ADVERSARIAL_REVIEWER"
    asgn_id = rev_res["assignment_id"]

    # Record BLOCKED review result with findings
    findings = [{
        "finding_id": "FINDING-DF08",
        "description": "Missing edge-case validation in src/impl.py",
        "required_remediation": "Add validation for empty input",
    }]
    block_res = slice_record_result(
        slice=s_name,
        assignment_id=asgn_id,
        artifacts={"verdict": "BLOCKED", "findings": findings},
        summary="Edge case missing",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    assert block_res["state"] == "REMEDIATION"
    assert "remediation_packet" in block_res
    assert block_res["remediation_packet"]["findings"] == findings
    assert "slice_remediate" in block_res["next_action"]

    # Verify controller state projection
    ctrl = SliceRunController(repo_dir=repo_dir, control_home=control_home)
    updated_st = ctrl.get_slice_state(s_name)
    assert updated_st.state == "REMEDIATION"
    assert updated_st.remediation_cycle_high_water == 1
    assert updated_st.latest_remediation_packet_id is not None
    assert updated_st.latest_remediation_packet_id in updated_st.open_remediation_packet_ids

    # Verify remediation work item creation
    work_items = ctrl.store.list_work_items(updated_st.run_id)
    rem_items = [wi for wi in work_items if wi.type == "remediation"]
    assert len(rem_items) >= 1
    assert rem_items[0].status == "READY"


def test_erroneous_review_request_from_remediation_provides_helpful_error(disposable_repo_and_control):
    """
    Attempting to request or dispatch an adversarial review directly from REMEDIATION
    must be blocked with an informative message explaining how to remediate first.
    """
    repo_dir, control_home, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir=repo_dir, control_home=control_home, configured_adapter_id="dummy")

    # Step to REMEDIATION using dummy adapter forced blocked review
    from slice_orchestrator.workers import TestDummyWorkerAdapter
    ctrl.worker_registry.register(TestDummyWorkerAdapter(review_approval=False, blocking_findings=[{
        "finding_id": "F1", "description": "Bug found"
    }]))

    ctrl.open_run("S81")
    ctrl.step("S81")  # PLAN_READY
    ctrl.step("S81")  # ARCHITECTURE_REVIEW
    ctrl.step("S81")  # ARCHITECTURE_APPROVED
    ctrl.step("S81")  # IMPLEMENTATION
    ctrl.step("S81")  # IMPLEMENTATION_READY_FOR_REVIEW
    ctrl.step("S81")  # ADVERSARIAL_REVIEW
    st = ctrl.step("S81")  # REMEDIATION
    assert st.state == "REMEDIATION"

    # 1. slice_request_review must fail with guidance
    with pytest.raises(OrchestratorError, match="Cannot request review from state 'REMEDIATION'.*slice_remediate"):
        slice_request_review(slice="S81", repo_dir=repo_dir, control_home=control_home)

    # 2. slice_dispatch(role='ADVERSARIAL_REVIEWER') must fail with guidance
    with pytest.raises(OrchestratorError, match="Cannot dispatch ADVERSARIAL_REVIEWER directly from state 'REMEDIATION'.*slice_remediate"):
        slice_dispatch(slice="S81", role="ADVERSARIAL_REVIEWER", repo_dir=repo_dir, control_home=control_home)


def test_slice_remediate_transitions_to_implementation_with_prompt(disposable_repo_and_control):
    """
    Calling slice_remediate on a REMEDIATION slice transitions state to IMPLEMENTATION,
    binds the remediation assignment, and provides structured prompt context.
    """
    repo_dir, control_home, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir=repo_dir, control_home=control_home, configured_adapter_id="dummy")

    from slice_orchestrator.workers import TestDummyWorkerAdapter
    ctrl.worker_registry.register(TestDummyWorkerAdapter(review_approval=False, blocking_findings=[{
        "finding_id": "F1",
        "description": "Missing bounds check",
        "required_remediation": "Add range check 0 <= x <= 100",
    }]))

    ctrl.open_run("S82")
    ctrl.step("S82")  # PLAN_READY
    ctrl.step("S82")  # ARCHITECTURE_REVIEW
    ctrl.step("S82")  # ARCHITECTURE_APPROVED
    ctrl.step("S82")  # IMPLEMENTATION
    ctrl.step("S82")  # IMPLEMENTATION_READY_FOR_REVIEW
    ctrl.step("S82")  # ADVERSARIAL_REVIEW
    ctrl.step("S82")  # REMEDIATION

    # Test slice explain surfaces the finding and remediation action
    expl = build_explain(ctrl, "S82")
    assert any("Missing bounds check" in f for f in expl["facts"])
    assert "slice_remediate" in expl["recommendation"]

    # Call slice_remediate
    res = slice_remediate(slice="S82", repo_dir=repo_dir, control_home=control_home)
    assert res["state"] == "IMPLEMENTATION"
    assert res["remediation_cycle"] == 1
    assert any(f["finding_id"] == "F1" for f in res["findings"])
    assert "Missing bounds check" in res["prompt"]

    # Verify controller state updated
    st = ctrl.get_slice_state("S82")
    assert st.state == "IMPLEMENTATION"


def test_cli_remediate_command(disposable_repo_and_control, capsys):
    """
    The CLI command `slice remediate <slice>` must transition REMEDIATION -> IMPLEMENTATION
    and display the active findings.
    """
    repo_dir, control_home, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir=repo_dir, control_home=control_home, configured_adapter_id="dummy")

    from slice_orchestrator.workers import TestDummyWorkerAdapter
    ctrl.worker_registry.register(TestDummyWorkerAdapter(review_approval=False, blocking_findings=[{
        "finding_id": "CLI-FINDING",
        "description": "Fix typo in docstring",
        "required_remediation": "Correct spelling of orchestrator",
    }]))

    ctrl.open_run("S83")
    ctrl.step("S83")
    ctrl.step("S83")
    ctrl.step("S83")
    ctrl.step("S83")
    ctrl.step("S83")
    ctrl.step("S83")
    ctrl.step("S83")  # REMEDIATION

    args = argparse.Namespace(
        slice="S83",
        adapter="dummy",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    code = cmd_remediate(args)
    assert code == 0

    out = capsys.readouterr().out
    assert "transitioned to IMPLEMENTATION" in out
    assert "CLI-FINDING" in out
    assert "Fix typo in docstring" in out


def test_full_df08_remediation_lifecycle_to_complete(disposable_repo_and_control):
    """
    End-to-end integration test reproducing the exact DF-08 scenario:
    1. Initial implementation blocked by adversarial review.
    2. Resumed cleanly with slice_remediate.
    3. Remediated candidate passes second adversarial review.
    4. Deterministic gate passes and slice reaches terminal COMPLETE.
    """
    repo_dir, control_home, _ = disposable_repo_and_control
    s_name = "S84"

    slice_start(slice=s_name, objective="DF-08 lifecycle reproduction", repo_dir=repo_dir, control_home=control_home)
    slice_plan(
        slice=s_name,
        plan={
            "description": "DF-08 test",
            "scope_manifest": {"allow_paths": ["src/**", "tests/**"]},
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

    # Initial implementation
    disp_impl = slice_dispatch(slice=s_name, role="IMPLEMENTER", repo_dir=repo_dir, control_home=control_home)
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "impl.py").write_text("# Initial incomplete implementation\n")
    slice_run_tests(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=disp_impl["assignment_id"],
        artifacts={},
        summary="Implemented v1",
        repo_dir=repo_dir,
        control_home=control_home,
    )

    # Review 1 -> BLOCKED (Finding DF08-01)
    rev1 = slice_request_review(slice=s_name, reviewer_principal="reviewer-alice", repo_dir=repo_dir, control_home=control_home)
    block_res = slice_record_result(
        slice=s_name,
        assignment_id=rev1["assignment_id"],
        artifacts={
            "verdict": "BLOCKED",
            "reviewer_principal": "reviewer-alice",
            "findings": [{
                "finding_id": "DF08-01",
                "description": "Edge case missing",
                "required_remediation": "Add edge case handling in src/impl.py",
            }],
        },
        summary="Rejected on edge case",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert block_res["state"] == "REMEDIATION"

    # Resume via slice_remediate
    rem_res = slice_remediate(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    assert rem_res["state"] == "IMPLEMENTATION"
    rem_asgn_id = rem_res["assignment_id"]

    # Remediate code
    (repo_dir / "src" / "impl.py").write_text("# Remediated: edge case handled!\ndef solve(x):\n    return x or 0\n")

    # Capture remediated candidate
    slice_run_tests(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    slice_record_result(
        slice=s_name,
        assignment_id=rem_asgn_id,
        artifacts={},
        summary="Remediation completed and verified",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    ctrl = SliceRunController(repo_dir=repo_dir, control_home=control_home)
    st = ctrl.get_slice_state(s_name)
    assert st.state == "IMPLEMENTATION_READY_FOR_REVIEW"

    # Review 2 -> APPROVED (distinct reviewer Bob)
    rev2 = slice_request_review(slice=s_name, reviewer_principal="reviewer-bob", repo_dir=repo_dir, control_home=control_home)
    appr_res = slice_record_result(
        slice=s_name,
        assignment_id=rev2["assignment_id"],
        artifacts={
            "verdict": "APPROVED",
            "reviewer_principal": "reviewer-bob",
        },
        summary="Remediation verified, edge case resolved",
        repo_dir=repo_dir,
        control_home=control_home,
    )
    assert appr_res["state"] == "COMMIT_READY"

    # Commit gate
    gate_res = slice_gate(slice=s_name, repo_dir=repo_dir, control_home=control_home)
    assert gate_res["passed"] is True

    # Finalize to COMPLETE
    fin_res = slice_finalize(slice=s_name, commit_message="feat: DF-08 completed slice", repo_dir=repo_dir, control_home=control_home)
    assert fin_res["state"] == "COMPLETE"

    # Verify event chain
    events = ctrl.store.verify_store_integrity()
    s_events = [e for e in events if e["slice"] == s_name]
    event_types = [e["event_type"] for e in s_events]

    assert "REVIEW_BLOCKED" in event_types
    assert "REMEDIATION_ASSIGNED" in event_types
    assert "REVIEW_ACCEPTED" in event_types
    assert "COMMIT_RECORDED" in event_types
    assert "GOVERNANCE_RECONCILED" in event_types
