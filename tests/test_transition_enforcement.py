"""Priority 3 — append_event enforces the state machine."""

from __future__ import annotations

import concurrent.futures

import pytest

from slice_orchestrator.control_store import ControlStore, ControlStoreError
from tests.workspace_support import seed_slice_to_ready_for_review


def _store(control_dir, policy_dir):
    store = ControlStore(control_dir, policy_bundle_source=policy_dir)
    store.init_database()
    return store


def test_illegal_transition_rejected(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    policy_dir = repo_dir.parents[0]
    # policy lives in the project bundle
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
    )
    with pytest.raises(ControlStoreError, match="Illegal transition"):
        store.append_event(
            slice_name="S1", run_id="r1", event_type="COMMIT_RECORDED",
            actor_role="COMMIT_MANAGER",
            payload={"payload_type": "COMMIT_RECORDED"},
        )


def test_terminal_state_immutable(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
    )
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_STOPPED",
        actor_role="CONTROLLER_SYSTEM",
        payload={"payload_type": "RUN_STOPPED", "reason_code": "OPERATOR_STOP", "reason": "stop"},
    )
    with pytest.raises(ControlStoreError, match="terminal"):
        store.append_event(
            slice_name="S1", run_id="r1", event_type="PLAN_PERSISTED",
            actor_role="PLANNER",
            payload={"payload_type": "PLAN_PERSISTED", "plan_revision": 2},
        )


def test_sequence_replay_rejected(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
        expected_seq=1,
    )
    with pytest.raises(ControlStoreError, match="sequence"):
        store.append_event(
            slice_name="S1", run_id="r1", event_type="RUN_PAUSED",
            actor_role="CONTROL_OPERATOR",
            payload={"payload_type": "RUN_PAUSED", "reason_code": "X", "reason": "x"},
            expected_seq=1,
        )


def test_wrong_run_rejected(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="run-aaa", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
    )
    with pytest.raises(ControlStoreError, match="Run identifier"):
        store.append_event(
            slice_name="S1", run_id="run-bbb", event_type="PLAN_PERSISTED",
            actor_role="PLANNER",
            payload={"payload_type": "PLAN_PERSISTED", "plan_revision": 1},
        )


def test_unauthorized_actor_rejected(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
    )
    with pytest.raises(ControlStoreError, match="not permitted|Illegal"):
        store.append_event(
            slice_name="S1", run_id="r1", event_type="PLAN_PERSISTED",
            actor_role="IMPLEMENTER",
            payload={"payload_type": "PLAN_PERSISTED", "plan_revision": 1},
        )


def test_implementer_cannot_stop_run(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
    )
    with pytest.raises(ControlStoreError, match="not permitted"):
        store.append_event(
            slice_name="S1", run_id="r1", event_type="RUN_STOPPED",
            actor_role="IMPLEMENTER",
            payload={"payload_type": "RUN_STOPPED", "reason_code": "X", "reason": "no"},
        )


def test_direct_append_event_cannot_bypass(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    store.append_event(
        slice_name="S1", run_id="r1", event_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": "x", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": "0" * 64,
        },
    )
    with pytest.raises(ControlStoreError, match="Illegal transition"):
        store.append_event(
            slice_name="S1", run_id="r1", event_type="GOVERNANCE_RECONCILED",
            actor_role="GOVERNANCE_AGENT",
            payload={"payload_type": "GOVERNANCE_RECONCILED"},
        )


def test_concurrent_transition_attempts(disposable_repo_and_control):
    from pathlib import Path
    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    _, control_dir, _ = disposable_repo_and_control
    store = _store(control_dir, policy_dir)
    seed_slice_to_ready_for_review(store, slice_name="S1", run_id="r1")

    def worker(idx: int):
        local = ControlStore(control_dir, policy_bundle_source=policy_dir)
        try:
            return local.append_event(
                slice_name="S1", run_id="r1",
                event_type="ADVERSARIAL_REVIEW_ASSIGNED",
                actor_role="CONTROLLER_SYSTEM",
                payload={"review_cycle": idx},
            )
        except ControlStoreError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(worker, i) for i in range(4)]]
    successes = [r for r in results if r is not None]
    assert len(successes) == 1
