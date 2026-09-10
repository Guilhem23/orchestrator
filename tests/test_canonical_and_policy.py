"""
Tests for canonical RFC 8785 JCS, digest computation, and policy bundle verification.
"""

from pathlib import Path
import pytest
from slice_orchestrator.canonical import (
    canonical_json_bytes,
    compute_event_hash,
    compute_record_digest,
)
from slice_orchestrator.policy import (
    PolicyBundle,
    compute_policy_bundle_digest,
)


def test_canonical_json_bytes_ordering():
    data1 = {"b": 1, "a": 2}
    data2 = {"a": 2, "b": 1}
    assert canonical_json_bytes(data1) == canonical_json_bytes(data2)
    assert canonical_json_bytes(data1) == b'{"a":2,"b":1}'


def test_record_digest_consistency():
    record = {"schema_version": 4, "record_type": "TEST", "val": "hello"}
    d1 = compute_record_digest(record)
    d2 = compute_record_digest(record)
    assert d1 == d2
    assert len(d1) == 64


def test_policy_bundle_digest():
    blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    digest = compute_policy_bundle_digest(blueprint_bundle)
    assert len(digest) == 64

    bundle = PolicyBundle(blueprint_bundle)
    assert bundle.computed_digest == digest
    assert "states" in bundle.transitions
    assert "protected_patterns" in bundle.protected_files or "workspace_classes" in bundle.protected_files
