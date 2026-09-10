"""
Tests for state projection and transition engine validation.
"""

from pathlib import Path
import pytest

from slice_orchestrator.policy import PolicyBundle
from slice_orchestrator.state_machine import (
    SliceRunState,
    TransitionEngine,
    TransitionError,
)


def test_transition_engine_rules():
    blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    bundle = PolicyBundle(blueprint_bundle)
    engine = TransitionEngine(bundle.transitions, bundle.slice_policy)

    # Initial transition
    to_state = engine.validate_transition(None, "RUN_OPENED", "CONTROL_OPERATOR", {})
    assert to_state == "PLANNING"

    # Illegal initial transition
    with pytest.raises(TransitionError):
        engine.validate_transition(None, "PLAN_PERSISTED", "PLANNER", {})

    # Legal planning to plan ready
    st = SliceRunState(slice="S99", run_id="r1", project_id="p1", state="PLANNING")
    to_state = engine.validate_transition(st, "PLAN_PERSISTED", "PLANNER", {})
    assert to_state == "PLAN_READY"

    # Illegal actor role
    with pytest.raises(TransitionError):
        engine.validate_transition(st, "PLAN_PERSISTED", "IMPLEMENTER", {})
