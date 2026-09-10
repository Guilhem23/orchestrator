#!/usr/bin/env python3
"""
Deterministic State Transition Checker — Slice Orchestrator v3

Validates that a requested state transition is legal according to
.orchestrator/transitions.yaml.

This is a DETERMINISTIC tool. It MUST NOT be an LLM.
It MUST NOT invent acceptance or override the transition table.

Usage:
    python transition_checker.py <current_state> <requested_state>
    python transition_checker.py --validate-history <slice>

Exit codes:
    0 = PASS (transition is legal)
    1 = FAIL (transition is illegal)
    2 = ERROR (configuration or input error)
"""

import json
import sys
from pathlib import Path

import yaml

ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent
TRANSITIONS_FILE = ORCHESTRATOR_ROOT / "transitions.yaml"


def load_transitions() -> dict:
    """Load the formal transition table."""
    if not TRANSITIONS_FILE.exists():
        print(f"ERROR: Transition table not found: {TRANSITIONS_FILE}", file=sys.stderr)
        sys.exit(2)
    with open(TRANSITIONS_FILE) as f:
        return yaml.safe_load(f)


def get_legal_targets(table: dict, current_state: str) -> list[str]:
    """Return the list of legal target states from current_state."""
    transitions = table.get("transitions", {})
    state_transitions = transitions.get(current_state, [])
    return [t["to"] for t in state_transitions]


def is_terminal(table: dict, state: str) -> bool:
    """Check if a state is terminal (no outgoing transitions)."""
    return state in table.get("terminal_states", [])


def validate_transition(current_state: str, requested_state: str) -> dict:
    """
    Validate a single state transition.

    Returns:
        dict with keys: valid (bool), current, requested, legal_targets, reason
    """
    table = load_transitions()

    all_states = table.get("states", [])

    if current_state not in all_states:
        return {
            "valid": False,
            "current": current_state,
            "requested": requested_state,
            "legal_targets": [],
            "reason": f"Unknown current state: {current_state}",
        }

    if requested_state not in all_states:
        return {
            "valid": False,
            "current": current_state,
            "requested": requested_state,
            "legal_targets": [],
            "reason": f"Unknown requested state: {requested_state}",
        }

    if is_terminal(table, current_state):
        return {
            "valid": False,
            "current": current_state,
            "requested": requested_state,
            "legal_targets": [],
            "reason": f"{current_state} is a terminal state; no transitions allowed",
        }

    legal = get_legal_targets(table, current_state)

    if requested_state in legal:
        return {
            "valid": True,
            "current": current_state,
            "requested": requested_state,
            "legal_targets": legal,
            "reason": "Transition is legal",
        }
    else:
        return {
            "valid": False,
            "current": current_state,
            "requested": requested_state,
            "legal_targets": legal,
            "reason": (
                f"ILLEGAL TRANSITION: {current_state} -> {requested_state}. "
                f"Legal targets from {current_state}: {legal}"
            ),
        }


def validate_history(slice_id: str) -> dict:
    """
    Validate the complete transition history for a slice.

    Returns dict with: valid (bool), errors (list), transition_count (int)
    """
    history_file = ORCHESTRATOR_ROOT / "history" / f"{slice_id}.jsonl"
    if not history_file.exists():
        return {
            "valid": False,
            "errors": [f"History file not found: {history_file}"],
            "transition_count": 0,
        }

    table = load_transitions()
    errors = []
    count = 0

    with open(history_file) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"Line {line_num}: invalid JSON")
                continue

            from_state = entry.get("from_state")
            to_state = entry.get("to_state")

            if from_state is None or to_state is None:
                errors.append(f"Line {line_num}: missing from_state or to_state")
                continue

            legal = get_legal_targets(table, from_state)
            if to_state not in legal:
                errors.append(
                    f"Line {line_num}: ILLEGAL {from_state} -> {to_state} "
                    f"(legal: {legal})"
                )
            count += 1

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "transition_count": count,
    }


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--validate-history":
        result = validate_history(sys.argv[2])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    if len(sys.argv) != 3:
        print(
            "Usage: transition_checker.py <current_state> <requested_state>",
            file=sys.stderr,
        )
        print(
            "       transition_checker.py --validate-history <slice>",
            file=sys.stderr,
        )
        sys.exit(2)

    current_state = sys.argv[1]
    requested_state = sys.argv[2]

    result = validate_transition(current_state, requested_state)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
