"""
RFC 8785 JSON Canonicalization Scheme (JCS) and Digest Computation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


RECORD_PREFIX = b"slice-orchestrator-v4/record/v1\x00"
EVENT_PREFIX = b"slice-orchestrator-v4/event/v1\x00"


def canonical_json_bytes(data: Any) -> bytes:
    """
    Produce RFC 8785 canonical JSON bytes.
    Keys are sorted, no trailing/extra whitespace, UTF-8 encoded.
    """
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_record_digest(canonical_data: Any) -> str:
    """
    Compute record_digest = sha256("slice-orchestrator-v4/record/v1\\0" || canonical_json_bytes).
    """
    hasher = hashlib.sha256()
    hasher.update(RECORD_PREFIX)
    hasher.update(canonical_json_bytes(canonical_data))
    return hasher.hexdigest()


def compute_event_hash(event_dict_without_hash_mac: dict[str, Any]) -> str:
    """
    Compute event_hash = sha256("slice-orchestrator-v4/event/v1\\0" || canonical_json_bytes).
    """
    cleaned = {
        k: v for k, v in event_dict_without_hash_mac.items()
        if k not in ("event_hash", "event_mac", "hmac")
    }

    hasher = hashlib.sha256()
    hasher.update(EVENT_PREFIX)
    hasher.update(canonical_json_bytes(cleaned))
    return hasher.hexdigest()
