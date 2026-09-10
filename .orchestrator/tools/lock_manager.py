#!/usr/bin/env python3
"""
Execution Lock Manager — Slice Orchestrator v3

Prevents two orchestrators from simultaneously controlling the same slice.

Lock file: .orchestrator/locks/<slice>.lock
Contains: owner, process identifier, started_at, state_revision.

A stale lock requires explicit recovery — never silent takeover.
Two active orchestrators for the same slice: STOPPED for both.

Usage:
    python lock_manager.py acquire <slice>
    python lock_manager.py release <slice>
    python lock_manager.py status <slice>
    python lock_manager.py force-release <slice> --reason <reason>

Exit codes:
    0 = success
    1 = lock conflict / already locked
    2 = error
"""

import json
import os
import sys
import time
from pathlib import Path

ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent
LOCKS_DIR = ORCHESTRATOR_ROOT / "locks"


def get_lock_path(slice_id: str) -> Path:
    """Get the lock file path for a slice."""
    return LOCKS_DIR / f"{slice_id}.lock"


def read_lock(slice_id: str) -> dict | None:
    """Read an existing lock file, or None if no lock."""
    lock_path = get_lock_path(slice_id)
    if not lock_path.exists():
        return None
    try:
        with open(lock_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"error": "corrupt_lock", "path": str(lock_path)}


def is_process_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def acquire_lock(slice_id: str) -> dict:
    """
    Attempt to acquire the orchestrator lock for a slice.

    Returns dict with: acquired (bool), lock_info, reason.
    """
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = get_lock_path(slice_id)

    existing = read_lock(slice_id)
    if existing and "error" not in existing:
        owner_pid = existing.get("pid")
        if owner_pid and is_process_alive(owner_pid):
            return {
                "acquired": False,
                "reason": "CONCURRENT_ORCHESTRATOR_DETECTED",
                "existing_lock": existing,
                "action": "STOPPED — concurrent orchestrator active. Manual resolution required.",
            }
        else:
            return {
                "acquired": False,
                "reason": "STALE_LOCK_DETECTED",
                "existing_lock": existing,
                "action": "Stale lock detected. Use force-release with explicit reason before re-acquiring.",
            }

    lock_info = {
        "slice": slice_id,
        "owner": os.environ.get("USER", "unknown"),
        "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hostname": os.environ.get("HOSTNAME", "unknown"),
    }

    try:
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as f:
            json.dump(lock_info, f, indent=2)
        return {
            "acquired": True,
            "lock_info": lock_info,
            "reason": "Lock acquired successfully",
        }
    except FileExistsError:
        return {
            "acquired": False,
            "reason": "RACE_CONDITION — lock file appeared during acquire",
            "action": "Retry or investigate concurrent orchestrator",
        }


def release_lock(slice_id: str) -> dict:
    """Release the lock for a slice (only if owned by current process)."""
    lock_path = get_lock_path(slice_id)
    existing = read_lock(slice_id)

    if not existing:
        return {"released": True, "reason": "No lock existed"}

    if existing.get("pid") != os.getpid():
        return {
            "released": False,
            "reason": f"Lock owned by pid {existing.get('pid')}, current pid {os.getpid()}",
            "action": "Use force-release for locks owned by other processes",
        }

    try:
        lock_path.unlink()
        return {"released": True, "reason": "Lock released by owner"}
    except OSError as e:
        return {"released": False, "reason": f"OS error: {e}"}


def force_release_lock(slice_id: str, reason: str) -> dict:
    """Force-release a lock with explicit reason (manual recovery)."""
    lock_path = get_lock_path(slice_id)
    existing = read_lock(slice_id)

    if not existing:
        return {"released": True, "reason": "No lock existed"}

    recovery_record = {
        "action": "force_release",
        "slice": slice_id,
        "previous_lock": existing,
        "released_by_pid": os.getpid(),
        "released_by_user": os.environ.get("USER", "unknown"),
        "released_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": reason,
    }

    recovery_dir = ORCHESTRATOR_ROOT / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    recovery_file = recovery_dir / f"{slice_id}-lock-recovery-{int(time.time())}.json"
    with open(recovery_file, "w") as f:
        json.dump(recovery_record, f, indent=2)

    try:
        lock_path.unlink()
        return {
            "released": True,
            "reason": f"Force-released: {reason}",
            "recovery_record": str(recovery_file),
        }
    except OSError as e:
        return {"released": False, "reason": f"OS error: {e}"}


def lock_status(slice_id: str) -> dict:
    """Check lock status for a slice."""
    existing = read_lock(slice_id)
    if not existing:
        return {"locked": False, "slice": slice_id}

    if "error" in existing:
        return {"locked": True, "corrupt": True, "slice": slice_id, "detail": existing}

    pid = existing.get("pid")
    alive = is_process_alive(pid) if pid else False

    return {
        "locked": True,
        "slice": slice_id,
        "owner_alive": alive,
        "stale": not alive,
        "lock_info": existing,
    }


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  lock_manager.py acquire <slice>\n"
            "  lock_manager.py release <slice>\n"
            "  lock_manager.py status <slice>\n"
            "  lock_manager.py force-release <slice> --reason <reason>\n",
            file=sys.stderr,
        )
        sys.exit(2)

    command = sys.argv[1]
    slice_id = sys.argv[2]

    if command == "acquire":
        result = acquire_lock(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("acquired") else 1)

    elif command == "release":
        result = release_lock(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("released") else 1)

    elif command == "status":
        result = lock_status(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    elif command == "force-release":
        reason = "unspecified"
        if "--reason" in sys.argv:
            idx = sys.argv.index("--reason")
            if idx + 1 < len(sys.argv):
                reason = sys.argv[idx + 1]
        result = force_release_lock(slice_id, reason)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("released") else 1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
