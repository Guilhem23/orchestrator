"""
Tests for Fast-Track Governance Mode (Adaptive Governance).
Verifies that low-complexity tasks can bypass heavy external review cycles
while strictly maintaining mechanical test verification and scope containment.
"""

from __future__ import annotations

import subprocess
import pytest
from pathlib import Path

from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.state_machine import TransitionError
from slice_orchestrator.tools import (
    slice_plan,
    slice_dispatch,
    slice_record_result,
    slice_run_tests,
    slice_fast_track_certify,
    slice_gate,
    slice_finalize,
)


def test_fast_track_direct_plan_to_implementation(disposable_repo_and_control):
    """
    In fast-track mode, PLAN_READY transitions directly to IMPLEMENTATION without ARCHITECTURE_REVIEW.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    state = ctrl.open_run("S50", profile="fast-track")
    assert state.profile == "fast-track"
    assert state.state == "PLANNING"

    # Step through planning
    state = ctrl.step("S50")
    assert state.state == "PLAN_READY"
    assert state.profile == "fast-track"

    # Next step must transition directly to IMPLEMENTATION (skipping ARCHITECTURE_REVIEW)
    state = ctrl.step("S50")
    assert state.state == "IMPLEMENTATION"
    assert state.current_actor_role == "CONTROLLER_SYSTEM"


def test_standard_mode_rejects_skipping_architecture_review(disposable_repo_and_control):
    """
    In standard mode, PLAN_READY cannot transition directly to IMPLEMENTATION.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    state = ctrl.open_run("S51", profile="standard")
    assert state.profile == "standard"
    state = ctrl.step("S51")
    assert state.state == "PLAN_READY"

    # Attempting to assign implementer directly in standard mode must fail
    with pytest.raises(TransitionError, match="only permitted for 'fast-track' profile"):
        ctrl.transition_engine.validate_transition(
            state,
            "IMPLEMENTATION_ASSIGNED",
            "CONTROLLER_SYSTEM",
            {"assignment_id": "as-1", "principal_id": "impl-1"},
        )


def test_fast_track_auto_review_to_commit_ready(disposable_repo_and_control):
    """
    In fast-track mode, IMPLEMENTATION_READY_FOR_REVIEW transitions directly to COMMIT_READY.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    ctrl.open_run("S52", profile="fast-track")
    ctrl.step("S52")  # PLAN_READY
    ctrl.step("S52")  # IMPLEMENTATION
    ctrl.step("S52")  # IMPLEMENTATION_READY_FOR_REVIEW

    state = ctrl.get_slice_state("S52")
    assert state.state == "IMPLEMENTATION_READY_FOR_REVIEW"

    # In fast-track, stepping from IMPLEMENTATION_READY_FOR_REVIEW triggers deterministic certification
    state = ctrl.step("S52")
    assert state.state == "COMMIT_READY"


def test_standard_mode_rejects_skipping_adversarial_review(disposable_repo_and_control):
    """
    In standard mode, IMPLEMENTATION_READY_FOR_REVIEW cannot transition directly to COMMIT_READY via REVIEW_ACCEPTED.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    ctrl.open_run("S53", profile="standard")
    ctrl.step("S53")  # PLAN_READY
    ctrl.step("S53")  # ARCHITECTURE_REVIEW
    ctrl.step("S53")  # ARCHITECTURE_APPROVED
    ctrl.step("S53")  # IMPLEMENTATION
    ctrl.step("S53")  # IMPLEMENTATION_READY_FOR_REVIEW

    state = ctrl.get_slice_state("S53")
    assert state.state == "IMPLEMENTATION_READY_FOR_REVIEW"

    # Attempting direct REVIEW_ACCEPTED in standard mode must fail
    with pytest.raises(TransitionError, match="only permitted for 'fast-track' profile"):
        ctrl.transition_engine.validate_transition(
            state,
            "REVIEW_ACCEPTED",
            "CONTROLLER_SYSTEM",
            {"verdict": "APPROVED"},
        )


def test_fast_track_complete_lifecycle(disposable_repo_and_control):
    """
    Autonomously drives a fast-track slice to COMPLETE and verifies commit & sequence efficiency.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    ctrl.open_run("S54", profile="fast-track")
    final_state = ctrl.run_to_completion("S54")

    assert final_state.state == "COMPLETE"
    assert final_state.profile == "fast-track"
    assert final_state.committed_implementation_oid is not None

    # Verify event count is lean (~10 events vs standard ~20)
    events = [e for e in ctrl.store.get_events() if e["slice"] == "S54"]
    event_types = [e["event_type"] for e in events]

    assert "ARCHITECTURE_REVIEW_ASSIGNED" not in event_types
    assert "ADVERSARIAL_REVIEW_ASSIGNED" not in event_types
    assert "COMMIT_RECORDED" in event_types
    assert "GOVERNANCE_RECONCILED" in event_types


def test_fast_track_gate_rejects_unauthorized_scope(disposable_repo_and_control):
    """
    Even in fast-track mode, the commit gate strictly rejects files modified outside the scope manifest.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    ctrl.open_run("S55", profile="fast-track")
    ctrl.step("S55")  # PLAN_READY
    ctrl.step("S55")  # IMPLEMENTATION

    # Write a file outside the declared scope manifest
    unauthorized_file = repo_dir / "unauthorized_leak.py"
    unauthorized_file.write_text("SECRET_KEY = 'leaked'\n")

    # Step to IMPLEMENTATION_READY_FOR_REVIEW (tests still pass, but candidate captures rogue file)
    ctrl.step("S55")

    # Fast-track certifier or controller step moves to COMMIT_READY
    ctrl.step("S55")

    state = ctrl.get_slice_state("S55")
    assert state.state == "COMMIT_READY"

    # Commit gate evaluation must FAIL on unauthorized scope
    from slice_orchestrator.gates import GateEvaluator
    evaluator = GateEvaluator(repo_dir, ctrl.store)
    gate_res = evaluator.evaluate_commit_gate(state)

    assert not gate_res.passed
    assert "Scope or protected path check failed" in gate_res.reason
