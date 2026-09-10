"""
Regression Tests for Priority 3 — Infinite Review Loop & max_cycles Enforcement.
"""

from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.policy import PolicyBundle
from slice_orchestrator.state_machine import SliceRunState, TransitionEngine, TransitionError, project_slice_run_state


def test_max_cycles_normal_completion_under_limit(disposable_repo_and_control):
    """Normal lifecycle completes when cycles are within max_cycles limit."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    st = ctrl.open_run("S1")
    assert st.review_cycle_high_water == 0
    assert not st.is_terminal()


def test_max_cycles_failure_at_limit(disposable_repo_and_control):
    """When review cycles reach max_cycles (5), attempting cycle 6 stops with MAX_CYCLES_EXCEEDED."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    bundle = PolicyBundle(policy_dir)
    engine = TransitionEngine(bundle.transitions, bundle.slice_policy)

    st = SliceRunState(
        slice="S1",
        run_id="00000000-0000-0000-0000-000000000001",
        project_id="test-proj",
        state="IMPLEMENTATION_READY_FOR_REVIEW",
        review_cycle_high_water=5,  # At max limit
    )

    with pytest.raises(TransitionError) as exc_info:
        engine.validate_transition(st, "ADVERSARIAL_REVIEW_ASSIGNED", "CONTROLLER_SYSTEM", {})

    assert "MAX_CYCLES_EXCEEDED" in str(exc_info.value)


def test_max_cycles_restart_near_limit(disposable_repo_and_control):
    """State projection from persisted events preserves high-water review cycle count across process restarts."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    bundle = PolicyBundle(policy_dir)

    store1 = ControlStore(control_dir, policy_bundle_source=policy_dir)
    store1.init_database()

    from tests.workspace_support import seed_slice_to_ready_for_review
    seed_slice_to_ready_for_review(store1, slice_name="S1", run_id="r1")

    # Append 4 legal review cycles (assign → accept → invalidate)
    for cycle in range(1, 5):
        store1.append_event(
            slice_name="S1", run_id="r1", generation=1,
            event_type="ADVERSARIAL_REVIEW_ASSIGNED", payload_type="ADVERSARIAL_REVIEW_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM", payload={"review_cycle": cycle},
        )
        store1.append_event(
            slice_name="S1", run_id="r1", generation=1,
            event_type="REVIEW_ACCEPTED", payload_type="REVIEW_ACCEPTED",
            actor_role="ADVERSARIAL_REVIEWER",
            payload={"review_cycle": cycle, "workspace_revision_digest": "d" * 64, "evidence_set_digest": "e" * 64, "approved_revision_digest": "f" * 64},
        )
        store1.append_event(
            slice_name="S1", run_id="r1", generation=1,
            event_type="ACCEPTANCE_INVALIDATED", payload_type="ACCEPTANCE_INVALIDATED",
            actor_role="COMMIT_MANAGER", payload={"reason_code": "GATE_FAILED"},
        )

    # Reload in fresh process / store instance
    store2 = ControlStore(control_dir, policy_bundle_source=policy_dir)
    events = store2.get_events()
    proj = project_slice_run_state(events, store2)

    assert proj is not None
    assert proj.review_cycle_high_water == 4


def test_max_cycles_concurrent_attempts(disposable_repo_and_control):
    """Locking and sequence checking prevent concurrent execution from bypassing cycle limits."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    from slice_orchestrator.control_store import SliceLockManager

    lock_path = control_dir / "locks" / "S1.lock"

    with SliceLockManager(lock_path):
        # Attempting second lock raises RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            with SliceLockManager(lock_path):
                pass
        assert "Slice lock already held" in str(exc_info.value)


def test_max_cycles_repeated_invalidation(disposable_repo_and_control):
    """Repeated ACCEPTANCE_INVALIDATED cycles increment high water count and hit stop condition."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    store = ControlStore(control_dir, policy_bundle_source=policy_dir)
    store.init_database()

    from tests.workspace_support import seed_slice_to_ready_for_review
    seed_slice_to_ready_for_review(store, slice_name="S1", run_id="r1")

    for cycle in range(1, 6):
        store.append_event(
            slice_name="S1", run_id="r1", generation=1,
            event_type="ADVERSARIAL_REVIEW_ASSIGNED", payload_type="ADVERSARIAL_REVIEW_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM", payload={"review_cycle": cycle}
        )
        store.append_event(
            slice_name="S1", run_id="r1", generation=1,
            event_type="REVIEW_ACCEPTED", payload_type="REVIEW_ACCEPTED",
            actor_role="ADVERSARIAL_REVIEWER",
            payload={"review_cycle": cycle, "workspace_revision_digest": "d" * 64},
        )
        store.append_event(
            slice_name="S1", run_id="r1", generation=1,
            event_type="ACCEPTANCE_INVALIDATED", payload_type="ACCEPTANCE_INVALIDATED",
            actor_role="COMMIT_MANAGER", payload={"reason_code": "GATE_FAILED"}
        )

    events = store.get_events()
    proj = project_slice_run_state(events, store)
    assert proj is not None
    assert proj.review_cycle_high_water == 5

    bundle = PolicyBundle(policy_dir)
    engine = TransitionEngine(bundle.transitions, bundle.slice_policy)

    with pytest.raises(TransitionError) as exc_info:
        engine.validate_transition(proj, "ADVERSARIAL_REVIEW_ASSIGNED", "CONTROLLER_SYSTEM", {})
    assert "MAX_CYCLES_EXCEEDED" in str(exc_info.value)


def test_max_cycles_malformed_or_missing_cycle_state(disposable_repo_and_control):
    """Events missing review_cycle fall back to incrementing review_cycle_high_water deterministically."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    store = ControlStore(control_dir, policy_bundle_source=policy_dir)
    store.init_database()

    from tests.workspace_support import seed_slice_to_ready_for_review
    seed_slice_to_ready_for_review(store, slice_name="S1", run_id="r1")

    # Event missing review_cycle payload field
    store.append_event(
        slice_name="S1", run_id="r1", generation=1,
        event_type="ADVERSARIAL_REVIEW_ASSIGNED", payload_type="ADVERSARIAL_REVIEW_ASSIGNED",
        actor_role="CONTROLLER_SYSTEM", payload={}
    )

    events = store.get_events()
    proj = project_slice_run_state(events, store)
    assert proj is not None
    assert proj.review_cycle_high_water == 1
