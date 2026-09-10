#!/usr/bin/env python3
"""
Evidence Manager — Slice Orchestrator v3

Manages versioned, immutable evidence artifacts.
Enforces append-only semantics and hash verification.

Evidence naming convention:
    evidence/<slice>/<artifact>-v<N>.<ext>

Before creating new evidence, prior evidence hashes MUST be verified unchanged.
If historical evidence is altered: BLOCK.

Usage:
    python evidence_manager.py verify <slice>
    python evidence_manager.py fingerprint <slice>
    python evidence_manager.py next-version <slice> <artifact-prefix>
    python evidence_manager.py record-hashes <slice>
    python evidence_manager.py check-integrity <slice>

Exit codes:
    0 = PASS / success
    1 = FAIL / integrity violation
    2 = ERROR
"""

import hashlib
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ORCHESTRATOR_ROOT = REPO_ROOT / ".orchestrator"
EVIDENCE_ROOT = REPO_ROOT / "evidence"


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_evidence_dir(slice_id: str) -> Path:
    """Get the evidence directory for a slice."""
    return EVIDENCE_ROOT / slice_id


def get_hash_record_path(slice_id: str) -> Path:
    """Get the path to the evidence hash record for a slice."""
    return ORCHESTRATOR_ROOT / "evidence-hashes" / f"{slice_id}.json"


def fingerprint_evidence(slice_id: str) -> dict:
    """
    Compute fingerprints for all evidence files in a slice.

    Returns dict mapping relative_path -> {sha256, size, mtime}.
    """
    evidence_dir = get_evidence_dir(slice_id)
    if not evidence_dir.is_dir():
        return {}

    fingerprints = {}
    for fpath in sorted(evidence_dir.rglob("*")):
        if fpath.is_file():
            rel = str(fpath.relative_to(evidence_dir))
            stat = fpath.stat()
            fingerprints[rel] = {
                "sha256": sha256_file(fpath),
                "size": stat.st_size,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

    return fingerprints


def record_hashes(slice_id: str) -> dict:
    """Record current evidence hashes for future integrity checks."""
    fingerprints = fingerprint_evidence(slice_id)
    hash_record_path = get_hash_record_path(slice_id)
    hash_record_path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "slice": slice_id,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "file_count": len(fingerprints),
        "files": fingerprints,
    }

    with open(hash_record_path, "w") as f:
        json.dump(record, f, indent=2)

    return {
        "success": True,
        "slice": slice_id,
        "files_recorded": len(fingerprints),
        "record_path": str(hash_record_path),
    }


def check_integrity(slice_id: str) -> dict:
    """
    Verify that historical evidence has not been modified.

    Compares current hashes against recorded hashes.
    Any change in a previously-recorded file is a VIOLATION.
    New files are allowed (append-only).
    """
    hash_record_path = get_hash_record_path(slice_id)
    if not hash_record_path.exists():
        return {
            "valid": True,
            "slice": slice_id,
            "detail": "No hash record exists yet; nothing to verify",
            "violations": [],
        }

    try:
        with open(hash_record_path) as f:
            recorded = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {
            "valid": False,
            "slice": slice_id,
            "detail": f"Cannot load hash record: {e}",
            "violations": ["hash_record_corrupt"],
        }

    current = fingerprint_evidence(slice_id)
    recorded_files = recorded.get("files", {})

    violations = []
    for filename, recorded_info in recorded_files.items():
        if filename not in current:
            violations.append({
                "file": filename,
                "type": "DELETED",
                "detail": "Previously recorded file is missing",
                "recorded_hash": recorded_info["sha256"],
            })
        elif current[filename]["sha256"] != recorded_info["sha256"]:
            violations.append({
                "file": filename,
                "type": "MODIFIED",
                "detail": "File hash changed since recording",
                "recorded_hash": recorded_info["sha256"],
                "current_hash": current[filename]["sha256"],
            })

    return {
        "valid": len(violations) == 0,
        "slice": slice_id,
        "recorded_files": len(recorded_files),
        "current_files": len(current),
        "new_files": len(current) - len(set(current.keys()) & set(recorded_files.keys())),
        "violations": violations,
        "detail": "Integrity intact" if not violations else f"{len(violations)} violation(s) detected",
    }


def next_version(slice_id: str, prefix: str) -> dict:
    """
    Determine the next version number for a versioned artifact.

    Scans evidence/<slice>/ for files matching <prefix>-v<N>.*
    Returns the next N.
    """
    evidence_dir = get_evidence_dir(slice_id)
    if not evidence_dir.is_dir():
        return {"next_version": 1, "prefix": prefix, "slice": slice_id}

    pattern = re.compile(rf"^{re.escape(prefix)}-v(\d+)\.")
    max_version = 0

    for fpath in evidence_dir.iterdir():
        match = pattern.match(fpath.name)
        if match:
            v = int(match.group(1))
            max_version = max(max_version, v)

    return {
        "next_version": max_version + 1,
        "current_max": max_version,
        "prefix": prefix,
        "slice": slice_id,
    }


def verify_all(slice_id: str) -> dict:
    """Full evidence verification: integrity + fingerprints."""
    integrity = check_integrity(slice_id)
    fingerprints = fingerprint_evidence(slice_id)

    return {
        "slice": slice_id,
        "integrity": integrity,
        "fingerprints": fingerprints,
        "verdict": "PASS" if integrity["valid"] else "FAIL",
    }


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  evidence_manager.py verify <slice>\n"
            "  evidence_manager.py fingerprint <slice>\n"
            "  evidence_manager.py next-version <slice> <prefix>\n"
            "  evidence_manager.py record-hashes <slice>\n"
            "  evidence_manager.py check-integrity <slice>\n",
            file=sys.stderr,
        )
        sys.exit(2)

    command = sys.argv[1]
    slice_id = sys.argv[2]

    if command == "verify":
        result = verify_all(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)

    elif command == "fingerprint":
        result = fingerprint_evidence(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    elif command == "next-version":
        if len(sys.argv) < 4:
            print("Usage: evidence_manager.py next-version <slice> <prefix>", file=sys.stderr)
            sys.exit(2)
        result = next_version(slice_id, sys.argv[3])
        print(json.dumps(result, indent=2))
        sys.exit(0)

    elif command == "record-hashes":
        result = record_hashes(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    elif command == "check-integrity":
        result = check_integrity(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
