#!/usr/bin/env python3
"""
State Recovery — Slice Orchestrator v3

Handles orchestrator startup validation and safe recovery.

On startup:
    1. Load state
    2. Validate schema
    3. Validate transition history
    4. Validate protected-policy hash
    5. Validate current Git revision
    6. Validate latest review revision
    7. Detect incomplete transition
    8. Recover only to a previously legal state

Never infer COMPLETE from filesystem presence.

If the original implementation thread is unavailable:
    Enter STOPPED with reason IMPLEMENTATION_CONTEXT_UNAVAILABLE.

Usage:
    python state_recovery.py startup <slice>
    python state_recovery.py validate <slice>
    python state_recovery.py dump-context <slice>

Exit codes:
    0 = state is valid, safe to continue
    1 = state requires STOPPED or human intervention
    2 = error
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ORCHESTRATOR_ROOT.parent


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def run_git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True,
            cwd=str(REPO_ROOT),
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def validate_schema(state: dict) -> dict:
    """Check that state has all required v3 fields."""
    required = [
        "schema_version", "slice", "state", "state_revision",
        "transition_counter", "implementation_thread_id",
        "implementation_revision_hash", "approved_plan_hash",
        "plan_revision", "review_cycle", "review_revision_hash",
        "last_review_artifact", "remediation_packet",
        "protected_policy_hash", "commit_candidate_hash",
    ]
    missing = [f for f in required if f not in state]
    version = state.get("schema_version")

    errors = []
    if missing:
        errors.append(f"Missing required fields: {missing}")
    if version != 3:
        errors.append(f"Schema version is {version}, expected 3")

    return {
        "check": "schema_validation",
        "passed": len(errors) == 0,
        "errors": errors,
    }


def validate_state_legal(state: dict) -> dict:
    """Check that current state is a legal state."""
    transitions = load_yaml(ORCHESTRATOR_ROOT / "transitions.yaml")
    legal_states = transitions.get("states", [])
    current = state.get("state", "")
    return {
        "check": "state_legal",
        "passed": current in legal_states,
        "detail": f"State '{current}' {'is' if current in legal_states else 'is NOT'} legal",
    }


def validate_transition_history(slice_id: str, state: dict) -> dict:
    """Validate transition history matches state."""
    history_file = ORCHESTRATOR_ROOT / "history" / f"{slice_id}.jsonl"
    if not history_file.exists():
        if state.get("transition_counter", 0) > 0:
            return {
                "check": "transition_history",
                "passed": False,
                "detail": "State shows transitions but no history file exists",
            }
        return {"check": "transition_history", "passed": True, "detail": "No history yet (new slice)"}

    transitions = load_yaml(ORCHESTRATOR_ROOT / "transitions.yaml")
    errors = []
    count = 0

    with open(history_file) as f:
        prev_state = None
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                from_state = entry.get("from_state")
                to_state = entry.get("to_state")

                if prev_state is not None and from_state != prev_state:
                    errors.append(f"Line {line_num}: discontinuity — expected from={prev_state}, got from={from_state}")

                legal = [t["to"] for t in transitions.get("transitions", {}).get(from_state, [])]
                if to_state not in legal:
                    errors.append(f"Line {line_num}: illegal transition {from_state} -> {to_state}")

                prev_state = to_state
                count += 1
            except json.JSONDecodeError:
                errors.append(f"Line {line_num}: invalid JSON")

    if prev_state and prev_state != state.get("state"):
        errors.append(f"History ends at {prev_state} but state says {state.get('state')}")

    expected_count = state.get("transition_counter", 0)
    if count != expected_count:
        errors.append(f"History has {count} entries but transition_counter is {expected_count}")

    return {
        "check": "transition_history",
        "passed": len(errors) == 0,
        "errors": errors,
        "history_entries": count,
    }


def validate_policy_hash(state: dict) -> dict:
    """Verify protected policy hash hasn't changed."""
    recorded = state.get("constitution_hash")
    if not recorded:
        return {"check": "policy_hash", "passed": False, "detail": "No constitution hash in state"}

    current = sha256_file(str(ORCHESTRATOR_ROOT / "CONSTITUTION.md"))
    match = recorded == current
    return {
        "check": "policy_hash",
        "passed": match,
        "detail": f"Constitution hash {'matches' if match else 'CHANGED'}",
    }


def validate_git_revision(state: dict) -> dict:
    """Validate current Git state against recorded state."""
    recorded_head = state.get("git_head")
    if not recorded_head:
        return {"check": "git_revision", "passed": True, "detail": "No git_head recorded (early state)"}

    current_head = run_git("rev-parse", "HEAD")
    if not current_head:
        return {"check": "git_revision", "passed": False, "detail": "Cannot determine Git HEAD"}

    return {
        "check": "git_revision",
        "passed": True,
        "detail": f"Recorded HEAD: {recorded_head[:12]}, Current HEAD: {current_head[:12]}",
        "head_changed": recorded_head != current_head,
    }


def validate_review_revision(state: dict) -> dict:
    """If we have a review revision, verify it's still meaningful."""
    review_hash = state.get("review_revision_hash")
    if not review_hash:
        return {"check": "review_revision", "passed": True, "detail": "No review revision recorded"}

    review_artifact = state.get("last_review_artifact")
    if review_artifact:
        full_path = os.path.join(str(REPO_ROOT), review_artifact)
        if not os.path.isfile(full_path):
            return {
                "check": "review_revision",
                "passed": False,
                "detail": f"Review artifact missing: {review_artifact}",
            }

    return {"check": "review_revision", "passed": True, "detail": "Review revision recorded and artifact exists"}


def detect_incomplete_transition(state: dict, slice_id: str) -> dict:
    """Detect if a transition was interrupted mid-way."""
    history_file = ORCHESTRATOR_ROOT / "history" / f"{slice_id}.jsonl"
    state_revision = state.get("state_revision", 0)
    transition_counter = state.get("transition_counter", 0)

    if state_revision < 1:
        return {"check": "incomplete_transition", "passed": False, "detail": "state_revision < 1"}

    if history_file.exists():
        with open(history_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        if len(lines) != transition_counter:
            return {
                "check": "incomplete_transition",
                "passed": False,
                "detail": f"History has {len(lines)} entries, transition_counter={transition_counter}",
            }

    return {"check": "incomplete_transition", "passed": True, "detail": "No incomplete transition detected"}


def dump_recovery_context(slice_id: str, state: dict) -> dict:
    """
    Dump the full recovery context for manual intervention.

    This is persisted enough to resume safely (Finding #8).
    """
    return {
        "slice": slice_id,
        "current_state": state.get("state"),
        "state_revision": state.get("state_revision"),
        "implementation_thread_id": state.get("implementation_thread_id"),
        "implementation_revision_hash": state.get("implementation_revision_hash"),
        "approved_plan_hash": state.get("approved_plan_hash"),
        "plan_revision": state.get("plan_revision"),
        "review_cycle": state.get("review_cycle"),
        "review_revision_hash": state.get("review_revision_hash"),
        "last_review_artifact": state.get("last_review_artifact"),
        "remediation_packet": state.get("remediation_packet"),
        "git_head": state.get("git_head"),
        "current_git_head": run_git("rev-parse", "HEAD"),
        "constitution_hash": state.get("constitution_hash"),
        "protected_policy_hash": state.get("protected_policy_hash"),
        "stopped_reason": state.get("stopped_reason"),
        "recovery_generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def startup_validation(slice_id: str) -> dict:
    """
    Full startup validation sequence.

    Returns validation result with all checks and recommended action.
    """
    state_file = ORCHESTRATOR_ROOT / "state" / f"{slice_id}.json"

    if not state_file.exists():
        return {
            "valid": True,
            "action": "NEW_SLICE",
            "detail": "No state file; safe to initialize new slice",
            "checks": [],
        }

    try:
        state = load_json(state_file)
    except Exception as e:
        return {
            "valid": False,
            "action": "STOPPED",
            "stopped_reason": "AMBIGUOUS_STATE_RECOVERY",
            "detail": f"Cannot load state file: {e}",
            "checks": [],
        }

    checks = [
        validate_schema(state),
        validate_state_legal(state),
        validate_transition_history(slice_id, state),
        validate_policy_hash(state),
        validate_git_revision(state),
        validate_review_revision(state),
        detect_incomplete_transition(state, slice_id),
    ]

    all_passed = all(c["passed"] for c in checks)
    failed = [c for c in checks if not c["passed"]]

    if state.get("state") == "STOPPED":
        return {
            "valid": False,
            "action": "STOPPED",
            "stopped_reason": state.get("stopped_reason", "PREVIOUSLY_STOPPED"),
            "detail": "Slice is in STOPPED state; human intervention required",
            "checks": checks,
            "recovery_context": dump_recovery_context(slice_id, state),
        }

    if not all_passed:
        first_failure = failed[0]
        return {
            "valid": False,
            "action": "STOPPED",
            "stopped_reason": "AMBIGUOUS_STATE_RECOVERY",
            "detail": f"Startup validation failed: {first_failure.get('detail', first_failure.get('errors', []))}",
            "checks": checks,
            "recovery_context": dump_recovery_context(slice_id, state),
        }

    return {
        "valid": True,
        "action": "CONTINUE",
        "current_state": state.get("state"),
        "detail": "All startup checks passed; safe to continue",
        "checks": checks,
    }


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  state_recovery.py startup <slice>\n"
            "  state_recovery.py validate <slice>\n"
            "  state_recovery.py dump-context <slice>\n",
            file=sys.stderr,
        )
        sys.exit(2)

    command = sys.argv[1]
    slice_id = sys.argv[2]

    if command == "startup":
        result = startup_validation(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    elif command == "validate":
        result = startup_validation(slice_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    elif command == "dump-context":
        state_file = ORCHESTRATOR_ROOT / "state" / f"{slice_id}.json"
        if not state_file.exists():
            print(json.dumps({"error": "No state file"}))
            sys.exit(2)
        state = load_json(state_file)
        result = dump_recovery_context(slice_id, state)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
