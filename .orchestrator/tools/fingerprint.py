#!/usr/bin/env python3
"""
Repository Fingerprint Tool — Slice Orchestrator v3

Computes a deterministic revision fingerprint from the complete
relevant working-tree state.

The fingerprint captures:
  - Git HEAD
  - Working tree diff hash (tracked changes)
  - Untracked file hashes (relevant untracked files)
  - Repository status summary
  - Optional: reviewer artifact hash

This is the TOCTOU-prevention mechanism: the reviewed_revision_hash
recorded at review time MUST match the current_revision_hash at commit time.

Usage:
    python fingerprint.py                     # compute current fingerprint
    python fingerprint.py --compare <hash>    # compare against a stored hash
    python fingerprint.py --file <path>       # SHA-256 of a single file
    python fingerprint.py --evidence-dir <dir> # fingerprint all evidence files

Exit codes:
    0 = success (or MATCH for --compare)
    1 = MISMATCH (for --compare)
    2 = ERROR
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def run_git(*args: str) -> str:
    """Run a git command and return stripped stdout."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"ERROR:{e.returncode}:{e.stderr.strip()}"
    except FileNotFoundError:
        return "ERROR:git_not_found"


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_git_head() -> str:
    """Get current Git HEAD commit hash."""
    return run_git("rev-parse", "HEAD")


def get_working_tree_diff_hash() -> str:
    """SHA-256 of the working tree diff (tracked changes)."""
    diff = run_git("diff")
    return sha256_bytes(diff.encode("utf-8"))


def get_staged_diff_hash() -> str:
    """SHA-256 of the staged diff."""
    diff = run_git("diff", "--cached")
    return sha256_bytes(diff.encode("utf-8"))


def get_untracked_files_hash() -> str:
    """SHA-256 of all relevant untracked files (sorted, concatenated hashes)."""
    untracked = run_git("ls-files", "--others", "--exclude-standard")
    if not untracked or untracked.startswith("ERROR:"):
        return sha256_bytes(b"NO_UNTRACKED")

    file_hashes = []
    for fpath in sorted(untracked.splitlines()):
        fpath = fpath.strip()
        if not fpath or not os.path.isfile(fpath):
            continue
        fhash = sha256_file(fpath)
        file_hashes.append(f"{fpath}:{fhash}")

    combined = "\n".join(file_hashes)
    return sha256_bytes(combined.encode("utf-8"))


def get_repo_status() -> str:
    """Get repository status summary."""
    return run_git("status", "--porcelain")


def compute_revision_fingerprint() -> dict:
    """
    Compute the complete revision fingerprint.

    Returns a dict with individual components and the combined
    reviewed_revision_hash.
    """
    git_head = get_git_head()
    working_diff_hash = get_working_tree_diff_hash()
    staged_diff_hash = get_staged_diff_hash()
    untracked_hash = get_untracked_files_hash()
    status = get_repo_status()
    status_hash = sha256_bytes(status.encode("utf-8"))

    combined_input = "\n".join([
        f"git_head:{git_head}",
        f"working_diff:{working_diff_hash}",
        f"staged_diff:{staged_diff_hash}",
        f"untracked:{untracked_hash}",
        f"status:{status_hash}",
    ])
    revision_hash = sha256_bytes(combined_input.encode("utf-8"))

    return {
        "reviewed_revision_hash": revision_hash,
        "components": {
            "git_head": git_head,
            "working_tree_diff_hash": working_diff_hash,
            "staged_diff_hash": staged_diff_hash,
            "untracked_files_hash": untracked_hash,
            "status_hash": status_hash,
        },
        "status_porcelain": status,
    }


def compute_evidence_fingerprint(evidence_dir: str) -> dict:
    """
    Compute fingerprints for all files in an evidence directory.

    Returns dict mapping filename -> {sha256, size, path}.
    """
    evidence_path = Path(evidence_dir)
    if not evidence_path.is_dir():
        return {"error": f"Not a directory: {evidence_dir}"}

    fingerprints = {}
    for fpath in sorted(evidence_path.rglob("*")):
        if fpath.is_file():
            rel = str(fpath.relative_to(evidence_path))
            fingerprints[rel] = {
                "sha256": sha256_file(str(fpath)),
                "size": fpath.stat().st_size,
                "path": str(fpath),
            }

    return fingerprints


def compare_revision(stored_hash: str) -> dict:
    """
    Compare stored revision hash against current state.

    Returns dict with match (bool), stored, current, components.
    """
    current = compute_revision_fingerprint()
    match = current["reviewed_revision_hash"] == stored_hash

    return {
        "match": match,
        "stored_revision_hash": stored_hash,
        "current_revision_hash": current["reviewed_revision_hash"],
        "components": current["components"],
        "verdict": "MATCH" if match else "MISMATCH",
    }


def main():
    if len(sys.argv) == 1:
        result = compute_revision_fingerprint()
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if sys.argv[1] == "--compare" and len(sys.argv) == 3:
        result = compare_revision(sys.argv[2])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["match"] else 1)

    if sys.argv[1] == "--file" and len(sys.argv) == 3:
        fpath = sys.argv[2]
        if not os.path.isfile(fpath):
            print(json.dumps({"error": f"File not found: {fpath}"}))
            sys.exit(2)
        result = {
            "path": fpath,
            "sha256": sha256_file(fpath),
            "size": os.path.getsize(fpath),
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if sys.argv[1] == "--evidence-dir" and len(sys.argv) == 3:
        result = compute_evidence_fingerprint(sys.argv[2])
        print(json.dumps(result, indent=2))
        sys.exit(0)

    print(
        "Usage:\n"
        "  fingerprint.py                       # current revision fingerprint\n"
        "  fingerprint.py --compare <hash>      # compare against stored hash\n"
        "  fingerprint.py --file <path>         # SHA-256 of a single file\n"
        "  fingerprint.py --evidence-dir <dir>  # fingerprint evidence directory\n",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
