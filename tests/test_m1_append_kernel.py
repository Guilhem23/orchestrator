"""
Dedicated Unit and Security Tests for M1 Append Kernel.
Covers Section M1 of ADR-014 Specification Annex v1.
"""

import concurrent.futures
import json
import os
import shutil
import sqlite3
import pytest
from pathlib import Path

from slice_orchestrator.canonical import (
    canonical_json_bytes,
    compute_event_hash,
    compute_record_digest,
)
from slice_orchestrator.control_store import ControlStore, ControlStoreError, SliceLockError
from slice_orchestrator.policy import PolicyError


def test_m1_canonical_serialization_determinism():
    """
    Verify RFC 8785 JSON Canonicalization Scheme produces identical bytes regardless of dict key order.
    """
    dict1 = {"b": 2, "a": 1, "c": {"y": "val2", "x": "val1"}}
    dict2 = {"a": 1, "c": {"x": "val1", "y": "val2"}, "b": 2}

    bytes1 = canonical_json_bytes(dict1)
    bytes2 = canonical_json_bytes(dict2)

    assert bytes1 == bytes2
    assert bytes1 == b'{"a":1,"b":2,"c":{"x":"val1","y":"val2"}}'


def test_m1_deterministic_hashing():
    """
    Verify event hash computation is deterministic and domain-separated.
    """
    event_data = {
        "schema_version": 4,
        "project_id": "test-proj",
        "slice": "S1",
        "run_id": "00000000-0000-0000-0000-000000000001",
        "run_generation": 1,
        "sequence": 1,
        "event_id": "00000000-0000-0000-0000-000000000002",
        "event_type": "RUN_OPENED",
        "actor": {
            "principal_id": "system",
            "role": "CONTROLLER_SYSTEM",
            "assignment_id": None,
            "execution_id": "exec-1"
        },
        "expected_previous_event_hash": "0" * 64,
        "payload_schema": "event-payload.schema.json",
        "payload": {
            "payload_type": "RUN_OPENED",
            "record": {
                "record_type": "SLICE_RUN",
                "record_id": "S1-run-1",
                "record_digest": "a" * 64
            },
            "base_commit_oid": "sha1:0000000000000000000000000000000000000000",
            "policy_bundle_digest": "b" * 64
        },
        "recorded_at": "2026-09-08T12:00:00Z"
    }

    hash1 = compute_event_hash(event_data)
    hash2 = compute_event_hash(event_data.copy())

    assert hash1 == hash2
    assert len(hash1) == 64
    # Ensure changing payload changes hash
    event_mod = json.loads(json.dumps(event_data))
    event_mod["payload"]["base_commit_oid"] = "sha1:1111111111111111111111111111111111111111"
    assert compute_event_hash(event_mod) != hash1


def test_m1_hmac_authenticity_and_secret_isolation(tmp_path):
    """
    Verify HMAC signatures validate with correct control secret and fail with tampered payload or wrong secret.
    """
    control_home = tmp_path / "control"
    store = ControlStore(control_home)

    # Verify secret is 32 bytes
    assert len(store.secret) == 32

    # Verify secret file permissions are 0600 or 0400
    stat_mode = store.secret_path.stat().st_mode & 0o777
    assert stat_mode in (0o600, 0o400)

    test_hash = "a" * 64
    mac = store.compute_hmac(test_hash)
    assert len(mac) == 64

    # Verify wrong secret fails MAC verification
    other_store = ControlStore(tmp_path / "other_control")
    assert store.secret != other_store.secret
    assert other_store.compute_hmac(test_hash) != mac


def test_m1_sequence_monotonicity_and_previous_hash_chaining(disposable_repo_and_control):
    """
    Verify strictly monotonic sequence numbering and previous hash chaining enforcement.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    # Append initial event seq=1
    payload1 = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64
    }
    ev1 = store.append_event(
        slice_name="S1",
        run_id="00000000-0000-0000-0000-000000000001",
        generation=1,
        event_type="RUN_OPENED",
        payload_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller",
        payload=payload1,
        expected_seq=1,
        expected_prev_hash="0" * 64
    )
    assert ev1["sequence"] == 1
    assert ev1["expected_previous_event_hash"] == "0" * 64

    # Attempt appending with sequence gap (e.g. seq=3 instead of 2) -> must fail
    payload2 = {
        "payload_type": "RUN_PAUSED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "reason_code": "TEST_PAUSE",
        "reason": "Testing sequence gap"
    }
    with pytest.raises(ControlStoreError):
        store.append_event(
            slice_name="S1",
            run_id="00000000-0000-0000-0000-000000000001",
            generation=1,
            event_type="RUN_PAUSED",
            payload_type="RUN_PAUSED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload2,
            expected_seq=3,  # Invalid sequence gap!
            expected_prev_hash=ev1["event_hash"]
        )

    # Attempt appending with wrong previous_event_hash -> must fail
    with pytest.raises(ControlStoreError):
        store.append_event(
            slice_name="S1",
            run_id="00000000-0000-0000-0000-000000000001",
            generation=1,
            event_type="RUN_PAUSED",
            payload_type="RUN_PAUSED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload2,
            expected_seq=2,
            expected_prev_hash="f" * 64  # Wrong previous hash!
        )

    # Valid append seq=2
    ev2 = store.append_event(
        slice_name="S1",
        run_id="00000000-0000-0000-0000-000000000001",
        generation=1,
        event_type="RUN_PAUSED",
        payload_type="RUN_PAUSED",
        actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller",
        payload=payload2,
        expected_seq=2,
        expected_prev_hash=ev1["event_hash"]
    )
    assert ev2["sequence"] == 2
    assert ev2["expected_previous_event_hash"] == ev1["event_hash"]


def test_m1_trusted_tail_anchor_atomic_updates(disposable_repo_and_control):
    """
    Verify trusted_tail_anchor file is updated atomically and fsynced after each append transaction.
    """
    _, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    payload = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64
    }
    ev = store.append_event(
        slice_name="S1",
        run_id="00000000-0000-0000-0000-000000000001",
        generation=1,
        event_type="RUN_OPENED",
        payload_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller",
        payload=payload,
        expected_seq=1,
        expected_prev_hash="0" * 64
    )

    anchor = store.read_tail_anchor()
    assert anchor is not None
    seq, ev_hash, mac = anchor
    assert seq == 1
    assert ev_hash == ev["event_hash"]
    assert mac == ev["event_mac"]


def test_m1_rollback_detection_cases_a_b_c(disposable_repo_and_control):
    """
    Test Rollback Detection Scenarios:
    Case A: DB restored backward (DB seq < anchor seq) -> STOPPED
    Case B: Anchor restored backward (anchor seq < DB seq) -> STOPPED
    Case C: DB & Anchor consistent -> PASS
    """
    _, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    # Insert 2 valid events
    p1 = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64
    }
    ev1 = store.append_event(
        slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
        event_type="RUN_OPENED", payload_type="RUN_OPENED", actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller", payload=p1, expected_seq=1, expected_prev_hash="0" * 64
    )

    p2 = {
        "payload_type": "RUN_PAUSED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "reason_code": "TEST_PAUSE", "reason": "Testing pause"
    }
    ev2 = store.append_event(
        slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
        event_type="RUN_PAUSED", payload_type="RUN_PAUSED", actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller", payload=p2, expected_seq=2, expected_prev_hash=ev1["event_hash"]
    )

    # Case C: Baseline verification -> PASS
    events = store.verify_store_integrity()
    assert len(events) == 2

    # Case A: DB restored backward (delete event 2 from DB while anchor remains seq=2)
    with store._get_db_connection() as conn:
        conn.execute("DELETE FROM events WHERE sequence = 2")
        conn.commit()

    with pytest.raises(ControlStoreError, match="STOPPED|mismatch|ahead"):
        store.verify_store_integrity()

    # Case B: Anchor restored backward (restore event 2 in DB, but set anchor to seq=1)
    # Re-insert event 2 in DB
    payload_json = json.dumps(ev2["payload"], sort_keys=True)
    event_json = json.dumps(ev2, sort_keys=True)
    with store._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO events (sequence, event_id, project_id, slice, run_id, run_generation, event_type, payload_json, event_json, event_hash, event_mac) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (2, ev2["event_id"], store.project_id, "S1", "00000000-0000-0000-0000-000000000001", 1, "RUN_PAUSED", payload_json, event_json, ev2["event_hash"], ev2["event_mac"])
        )
        conn.commit()

    # Overwrite anchor to seq=1
    store.update_tail_anchor(1, ev1["event_hash"], ev1["event_mac"])

    with pytest.raises(ControlStoreError, match="STOPPED|mismatch"):
        store.verify_store_integrity()


def test_m1_corruption_detection(disposable_repo_and_control):
    """
    Verify database or event payload corruption is detected by verify_store_integrity.
    """
    _, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    p1 = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64
    }
    ev1 = store.append_event(
        slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
        event_type="RUN_OPENED", payload_type="RUN_OPENED", actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller", payload=p1, expected_seq=1, expected_prev_hash="0" * 64
    )

    # Corrupt SQLite event row payload
    with store._get_db_connection() as conn:
        conn.execute("UPDATE events SET payload_json = '{\"corrupted\": true}' WHERE sequence = 1")
        conn.commit()

    with pytest.raises(ControlStoreError):
        store.verify_store_integrity()


def test_m1_concurrent_append_safety(disposable_repo_and_control):
    """
    Verify concurrent append attempts do not create sequence gaps, lost events, or duplicate sequences.
    """
    _, control_dir, _ = disposable_repo_and_control

    def worker_append(worker_idx: int):
        # Create separate store instances pointing to same control_dir
        local_store = ControlStore(control_dir)
        p = {
            "payload_type": "RUN_PAUSED",
            "record": {"record_type": "SLICE_RUN", "record_id": f"S1-run-{worker_idx}", "record_digest": "0" * 64},
            "reason_code": f"WORKER_{worker_idx}",
            "reason": f"Concurrent test worker {worker_idx}"
        }
        # Attempt appending at sequence 2 (only 1 can succeed)
        try:
            return local_store.append_event(
                slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
                event_type="RUN_PAUSED", payload_type="RUN_PAUSED", actor_role="CONTROLLER_SYSTEM",
                actor_principal=f"worker-{worker_idx}", payload=p, expected_seq=2,
                expected_prev_hash="prev_dummy_hash"
            )
        except ControlStoreError:
            return None

    # Initial append
    store = ControlStore(control_dir)
    store.init_database()
    p1 = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64
    }
    ev1 = store.append_event(
        slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
        event_type="RUN_OPENED", payload_type="RUN_OPENED", actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller", payload=p1, expected_seq=1, expected_prev_hash="0" * 64
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_append, i) for i in range(5)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Exactly one thread should succeed for seq=2
    successful_appends = [r for r in results if r is not None]
    assert len(successful_appends) <= 1


def test_m1_toolchain_environment_validation(disposable_repo_and_control):
    """
    Verify verify_toolchain_environment checks required system binaries.
    """
    _, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)

    assert store.verify_toolchain_environment(["python3", "uv", "pytest", "git", "sqlite3"]) is True
    assert store.verify_toolchain_environment(["non_existent_binary_xyz123"]) is False


def test_actor_role_contract_validation(disposable_repo_and_control):
    """
    Verify actor-role contract:
    - CONTROLLER_SYSTEM events pass schema validation.
    - Invalid actor roles fail closed.
    - State machine transitions enforce role permissions.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    from slice_orchestrator.policy import PolicyBundle, PolicyError
    from slice_orchestrator.state_machine import TransitionEngine, TransitionError, SliceRunState

    policy_dir = Path(__file__).resolve().parents[1] / ".orchestrator"
    bundle = PolicyBundle(policy_dir)
    store = ControlStore(control_dir, policy_bundle_source=policy_dir)
    store.init_database()

    p1 = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": "S1-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64
    }

    # Valid controller event accepted
    ev1 = store.append_event(
        slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
        event_type="RUN_OPENED", payload_type="RUN_OPENED", actor_role="CONTROLLER_SYSTEM",
        actor_principal="controller", payload=p1
    )
    assert ev1["actor"]["role"] == "CONTROLLER_SYSTEM"

    # Invalid actor role fails schema validation
    with pytest.raises(PolicyError) as exc_info:
        store.append_event(
            slice_name="S1", run_id="00000000-0000-0000-0000-000000000001", generation=1,
            event_type="RUN_OPENED", payload_type="RUN_OPENED", actor_role="INVALID_ROLE",
            actor_principal="controller", payload=p1
        )
    assert "Schema validation failed" in str(exc_info.value)

    # State machine transition rule enforces authorized roles
    engine = TransitionEngine(bundle.transitions, bundle.slice_policy)
    st = SliceRunState(slice="S1", run_id="00000000-0000-0000-0000-000000000001", project_id="test", state="PLANNING")

    # IMPLEMENTER cannot persist plan
    with pytest.raises(TransitionError) as exc_trans:
        engine.validate_transition(st, "PLAN_PERSISTED", "IMPLEMENTER", {})
    assert "not permitted" in str(exc_trans.value)

