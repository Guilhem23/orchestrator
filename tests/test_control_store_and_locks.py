"""
Tests for control store SQLite event stream, HMAC verification, trusted tail anchor, and locks.
"""

from pathlib import Path
import tempfile
import pytest

from slice_orchestrator.control_store import (
    ControlStore,
    ControlStoreError,
    SliceLockManager,
)


def test_control_store_initialization_and_events():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"

        store = ControlStore(home)
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        # Append first event
        payload = {
            "payload_type": "RUN_OPENED",
            "record": {
                "record_type": "SLICE_RUN",
                "record_id": "run-1",
                "record_digest": "a" * 64,
            },
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": store.load_and_verify_policy_bundle().computed_digest,
        }

        tok_hash = store.set_ownership("S99", "run-1", 1, 1, "secret-token")
        ev1 = store.append_event(
            slice_name="S99",
            run_id="run-1",
            generation=1,
            event_type="RUN_OPENED",
            payload_type="RUN_OPENED",
            actor_role="CONTROL_OPERATOR",
            actor_principal="op",
            payload=payload,
            expected_seq=1,
            expected_prev_hash=None,
            token_hash=tok_hash,
        )

        assert ev1["sequence"] == 1
        anchor = store.read_tail_anchor()
        assert anchor is not None
        assert anchor[1] == ev1["event_hash"]

        # Verify stream integrity
        events = store.verify_store_integrity()
        assert len(events) == 1
        assert events[0]["slice"] == "S99"


def test_slice_lock_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_file = Path(tmpdir) / "test.lock"
        lock1 = SliceLockManager(lock_file)
        with lock1:
            assert lock_file.is_file()
