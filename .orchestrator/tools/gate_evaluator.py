#!/usr/bin/env python3
"""
Deterministic Gate Evaluator — Slice Orchestrator v3

Independently verifies all mechanical preconditions for a state transition.
This is a DETERMINISTIC tool. It MUST NOT be an LLM.
It MUST NOT invent acceptance.

The adversarial reviewer remains the authority for substantive judgment.
This evaluator checks only mechanical/structural facts.

Usage:
    python gate_evaluator.py <slice> [--state-file <path>]

Output: JSON with verdict PASS or FAIL and detailed check results.

Exit codes:
    0 = PASS
    1 = FAIL
    2 = ERROR
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ORCHESTRATOR_ROOT.parent


def sha256_file(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def load_yaml(path: Path) -> dict:
    """Load a YAML file."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path) -> dict:
    """Load a JSON file."""
    with open(path) as f:
        return json.load(f)


def run_git(*args: str) -> str:
    """Run a git command."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def check_legal_transition(state: dict, transitions: dict) -> dict:
    """Check that the current state is reachable and valid."""
    current = state.get("state", "")
    all_states = transitions.get("states", [])
    return {
        "check": "legal_state",
        "passed": current in all_states,
        "detail": f"State '{current}' {'is' if current in all_states else 'is NOT'} in legal state list",
    }


def check_review_artifact_exists(state: dict) -> dict:
    """Check that the review artifact file exists."""
    path = state.get("last_review_artifact")
    if not path:
        return {"check": "review_artifact_exists", "passed": False, "detail": "No review artifact path in state"}
    exists = os.path.isfile(os.path.join(str(REPO_ROOT), path))
    return {
        "check": "review_artifact_exists",
        "passed": exists,
        "detail": f"Review artifact {'exists' if exists else 'MISSING'}: {path}",
    }


def check_review_verdict(state: dict) -> dict:
    """Check that review says APPROVED."""
    verdict = state.get("last_review_verdict")
    return {
        "check": "review_verdict_approved",
        "passed": verdict == "APPROVED",
        "detail": f"Review verdict: {verdict}",
    }


def check_blocking_findings(state: dict) -> dict:
    """Check blocking_findings == 0."""
    count = state.get("blocking_findings", -1)
    return {
        "check": "blocking_findings_zero",
        "passed": count == 0,
        "detail": f"Blocking findings: {count}",
    }


def check_required_tests(slice_id: str) -> dict:
    """Check that required tests exist and pass (via make test)."""
    evidence_dir = REPO_ROOT / "evidence" / slice_id
    test_results = sorted(evidence_dir.glob("test-results-v*.json")) if evidence_dir.is_dir() else []

    if not test_results:
        return {"check": "required_tests", "passed": False, "detail": "No test result artifacts found"}

    latest = test_results[-1]
    try:
        data = load_json(latest)
        passed = data.get("all_passed", False)
        skipped = data.get("skipped", 0)
        return {
            "check": "required_tests",
            "passed": passed and skipped == 0,
            "detail": f"Tests passed: {passed}, skipped: {skipped} (from {latest.name})",
        }
    except (json.JSONDecodeError, KeyError) as e:
        return {"check": "required_tests", "passed": False, "detail": f"Error reading test results: {e}"}


def check_evidence_pack(slice_id: str) -> dict:
    """Check that evidence pack exists and is internally consistent."""
    evidence_dir = REPO_ROOT / "evidence" / slice_id
    if not evidence_dir.is_dir():
        return {"check": "evidence_pack_exists", "passed": False, "detail": f"Evidence directory missing: {evidence_dir}"}

    files = list(evidence_dir.iterdir())
    if not files:
        return {"check": "evidence_pack_exists", "passed": False, "detail": "Evidence directory is empty"}

    return {
        "check": "evidence_pack_exists",
        "passed": True,
        "detail": f"Evidence directory has {len(files)} files",
    }


def check_revision_match(state: dict) -> dict:
    """Check reviewed_revision_hash == current revision hash."""
    reviewed = state.get("review_revision_hash")
    if not reviewed:
        return {"check": "revision_match", "passed": False, "detail": "No review_revision_hash in state"}

    try:
        fp_tool = ORCHESTRATOR_ROOT / "tools" / "fingerprint.py"
        result = subprocess.run(
            [sys.executable, str(fp_tool)],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        )
        current = json.loads(result.stdout)
        current_hash = current.get("reviewed_revision_hash", "")
        match = reviewed == current_hash
        return {
            "check": "revision_match",
            "passed": match,
            "detail": f"reviewed={reviewed[:16]}... current={current_hash[:16]}... {'MATCH' if match else 'MISMATCH'}",
        }
    except Exception as e:
        return {"check": "revision_match", "passed": False, "detail": f"Fingerprint computation error: {e}"}


def check_protected_files(state: dict) -> dict:
    """Check no protected files were modified by the implementation agent."""
    try:
        protected = load_yaml(ORCHESTRATOR_ROOT / "protected-files.yaml")
    except Exception as e:
        return {"check": "protected_files", "passed": False, "detail": f"Cannot load protected-files.yaml: {e}"}

    diff_files = run_git("diff", "--name-only", "HEAD").splitlines()
    staged_files = run_git("diff", "--cached", "--name-only").splitlines()
    changed = set(diff_files + staged_files)

    immutable_patterns = []
    for cls_name, cls_def in protected.get("file_classes", {}).items():
        if cls_def.get("immutable_during_run", False) or cls_def.get("immutable", False):
            immutable_patterns.extend(cls_def.get("patterns", []))

    violations = []
    for f in changed:
        for pattern in immutable_patterns:
            from fnmatch import fnmatch
            if fnmatch(f, pattern):
                violations.append(f"{f} matches immutable pattern {pattern}")

    return {
        "check": "protected_files",
        "passed": len(violations) == 0,
        "detail": f"Violations: {violations}" if violations else "No protected file violations",
    }


def check_scope(slice_id: str) -> dict:
    """Check scope against slice manifest if present."""
    manifest_path = REPO_ROOT / ".slice-manifest.yaml"
    if not manifest_path.exists():
        manifest_path = ORCHESTRATOR_ROOT / "manifests" / f".slice-manifest-{slice_id}.yaml"
    if not manifest_path.exists():
        return {"check": "scope_check", "passed": True, "detail": "No slice manifest; scope check skipped"}

    try:
        manifest = load_yaml(manifest_path)
    except Exception as e:
        return {"check": "scope_check", "passed": False, "detail": f"Cannot load manifest: {e}"}

    allowed = set()
    for key in ("allowed_source_paths", "allowed_test_paths", "allowed_evidence_paths",
                "allowed_dependency_files", "explicitly_justified_shared_files"):
        for pattern in manifest.get(key, []):
            allowed.add(pattern)

    staged = run_git("diff", "--cached", "--name-only").splitlines()
    violations = []
    for f in staged:
        f = f.strip()
        if not f:
            continue
        matched = False
        from fnmatch import fnmatch
        for pattern in allowed:
            if fnmatch(f, pattern):
                matched = True
                break
        if not matched:
            violations.append(f)

    return {
        "check": "scope_check",
        "passed": len(violations) == 0,
        "detail": f"Out-of-scope files: {violations}" if violations else "All staged files within scope",
    }


def check_policy_hash(state: dict) -> dict:
    """Check that protected policy hashes haven't changed since startup."""
    recorded = state.get("protected_policy_hash")
    constitution_recorded = state.get("constitution_hash")

    if not recorded or not constitution_recorded:
        return {"check": "policy_hash", "passed": False, "detail": "No policy hashes recorded in state"}

    constitution_current = sha256_file(str(ORCHESTRATOR_ROOT / "CONSTITUTION.md"))

    if constitution_current != constitution_recorded:
        return {
            "check": "policy_hash",
            "passed": False,
            "detail": f"CONSTITUTION.md hash changed: recorded={constitution_recorded[:16]}... current={constitution_current[:16]}...",
        }

    return {"check": "policy_hash", "passed": True, "detail": "Policy hashes unchanged"}


def check_plan_unchanged(state: dict) -> dict:
    """Verify architecture plan hasn't changed without explicit PLAN_REVISION."""
    plan_hash = state.get("approved_plan_hash")
    plan_path = state.get("plan_path")

    if not plan_hash or not plan_path:
        return {"check": "plan_unchanged", "passed": False, "detail": "No approved plan hash or path"}

    full_path = os.path.join(str(REPO_ROOT), plan_path)
    if not os.path.isfile(full_path):
        return {"check": "plan_unchanged", "passed": False, "detail": f"Plan file missing: {plan_path}"}

    current_hash = sha256_file(full_path)
    match = plan_hash == current_hash

    return {
        "check": "plan_unchanged",
        "passed": match,
        "detail": f"Plan {'unchanged' if match else 'CHANGED without PLAN_REVISION'}",
    }


def evaluate_commit_gate(slice_id: str, state: dict) -> dict:
    """
    Run the full commit-gate evaluation.

    Returns dict with:
      - verdict: PASS or FAIL
      - checks: list of individual check results
      - summary: human-readable summary
    """
    transitions = load_yaml(ORCHESTRATOR_ROOT / "transitions.yaml")

    checks = [
        check_legal_transition(state, transitions),
        check_review_artifact_exists(state),
        check_review_verdict(state),
        check_blocking_findings(state),
        check_required_tests(slice_id),
        check_evidence_pack(slice_id),
        check_revision_match(state),
        check_protected_files(state),
        check_scope(slice_id),
        check_policy_hash(state),
        check_plan_unchanged(state),
    ]

    all_passed = all(c["passed"] for c in checks)
    failed = [c for c in checks if not c["passed"]]

    return {
        "verdict": "PASS" if all_passed else "FAIL",
        "slice": slice_id,
        "state": state.get("state", "UNKNOWN"),
        "checks_total": len(checks),
        "checks_passed": sum(1 for c in checks if c["passed"]),
        "checks_failed": len(failed),
        "checks": checks,
        "failed_checks": failed,
        "summary": "All gate checks passed" if all_passed else f"{len(failed)} gate check(s) failed",
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: gate_evaluator.py <slice> [--state-file <path>]", file=sys.stderr)
        sys.exit(2)

    slice_id = sys.argv[1]

    state_file = None
    if "--state-file" in sys.argv:
        idx = sys.argv.index("--state-file")
        if idx + 1 < len(sys.argv):
            state_file = sys.argv[idx + 1]

    if not state_file:
        state_file = str(ORCHESTRATOR_ROOT / "state" / f"{slice_id}.json")

    if not os.path.isfile(state_file):
        print(json.dumps({"verdict": "FAIL", "error": f"State file not found: {state_file}"}))
        sys.exit(1)

    try:
        state = load_json(Path(state_file))
    except Exception as e:
        print(json.dumps({"verdict": "FAIL", "error": f"Cannot load state: {e}"}))
        sys.exit(1)

    result = evaluate_commit_gate(slice_id, state)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
