"""Priority 4 — first init vs missing/corrupt trust state fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from slice_orchestrator.control_store import ControlStore, TrustStateError


def test_first_initialization_creates_trust_state(tmp_path: Path):
    home = tmp_path / "fresh"
    store = ControlStore(home)
    assert store.trust_state_mode == TrustStateError.FIRST_INITIALIZATION
    assert store.secret_path.is_file()
    assert len(store.secret) == 32
    assert store.trust_init_marker.is_file()
    assert store.verify_store_integrity() == []


def test_missing_secret_fails_closed(tmp_path: Path):
    home = tmp_path / "ctrl"
    store = ControlStore(home)
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
    store.secret_path.unlink()
    with pytest.raises(TrustStateError) as exc:
        ControlStore(home)
    assert exc.value.code == TrustStateError.MISSING_TRUST_STATE


def test_missing_anchor_fails_closed(tmp_path: Path):
    home = tmp_path / "ctrl"
    store = ControlStore(home)
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
    assert store.tail_anchor_path.is_file()
    store.tail_anchor_path.unlink()
    with pytest.raises(TrustStateError) as exc:
        store.verify_store_integrity()
    assert exc.value.code == TrustStateError.MISSING_TRUST_STATE


def test_corrupted_anchor_fails_closed(tmp_path: Path):
    home = tmp_path / "ctrl"
    store = ControlStore(home)
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
    store.tail_anchor_path.write_text("not-a-valid-anchor\n", encoding="utf-8")
    with pytest.raises(TrustStateError) as exc:
        store.verify_store_integrity()
    assert exc.value.code == TrustStateError.MISSING_TRUST_STATE


def test_corrupted_secret_fails_closed(tmp_path: Path):
    home = tmp_path / "ctrl"
    ControlStore(home)
    (home / "control_secret.key").write_bytes(b"short")
    with pytest.raises(TrustStateError) as exc:
        ControlStore(home)
    assert exc.value.code == TrustStateError.CORRUPTION
    # secret must not have been silently rotated
    assert (home / "control_secret.key").read_bytes() == b"short"


def test_worker_cannot_recover_trust_state(tmp_path: Path):
    home = tmp_path / "ctrl"
    store = ControlStore(home)
    with pytest.raises(TrustStateError) as exc:
        store.recover_trust_state("worker-impl-1", "please recreate", "REBUILD_ANCHOR_FROM_DB")
    assert exc.value.code == TrustStateError.RECOVERY


def test_operator_recovery_is_auditable(tmp_path: Path):
    home = tmp_path / "ctrl"
    store = ControlStore(home)
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
    store.tail_anchor_path.unlink()
    audit = store.recover_trust_state("operator-local", "rebuild missing anchor", "REBUILD_ANCHOR_FROM_DB")
    assert audit["action"] == "REBUILD_ANCHOR_FROM_DB"
    assert store.tail_anchor_path.is_file()
    assert store.get_record(audit["recovery_id"]) is not None
    assert store.verify_store_integrity()
