"""
CI / Pull Request Gatekeeper for Slice Orchestrator (Phase 3 - v4.3).

Verifies pull requests against Slice Orchestrator governance criteria:
1. Active / completed slice state is COMMIT_READY or COMPLETE.
2. Every modified file in the PR diff is permitted by the approved plan scope_manifest.
3. Authoritative test receipts are cryptographically intact (HMAC verified) and passing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slice_orchestrator.control_store import ControlStore, ControlStoreError
from slice_orchestrator.git_manager import run_git_cmd
from slice_orchestrator.path_semantics import match_path_pattern, normalize_repo_path


def _resolve_base_ref(repo_dir: Path, requested_base: str | None = None) -> str:
    """Detect candidate base ref (e.g. origin/main, main, or HEAD~1)."""
    if requested_base:
        return requested_base
    for candidate in ["origin/main", "origin/master", "main", "master", "HEAD~1"]:
        try:
            run_git_cmd(["rev-parse", "--verify", candidate], repo_dir, check=True)
            return candidate
        except Exception:
            continue
    return "HEAD~1"


def verify_pr_governance(
    repo_dir: Path,
    control_home: Path,
    base_ref: str | None = None,
    slice_name: str | None = None,
) -> dict[str, Any]:
    """
    Perform authoritative CI gate verification on the current branch / PR diff.
    """
    from slice_orchestrator.orchestrator import SliceRunController

    ctrl = SliceRunController(repo_dir=repo_dir, control_home=control_home)
    store = ctrl.store
    resolved_base = _resolve_base_ref(repo_dir, requested_base=base_ref)

    # 1. Determine target slice
    s_name = slice_name
    if not s_name:
        runs_dir = control_home / "runs"
        if runs_dir.is_dir():
            candidates = sorted([d.name for d in runs_dir.iterdir() if d.is_dir()], reverse=True)
            if candidates:
                s_name = candidates[0]
        if not s_name:
            # Fallback to events
            try:
                events = store.verify_store_integrity()
                if events:
                    s_name = events[-1].get("slice")
            except Exception:
                pass

    if not s_name:
        return {
            "passed": False,
            "slice": None,
            "reasons": ["NO_SLICE_RUN: No Slice Orchestrator run found in repository."],
            "summary_markdown": "### ❌ Slice CI Gate: FAILED\n\nNo Slice Orchestrator run found in `.orchestrator_slice/`.",
        }

    state = ctrl.get_slice_state(s_name)
    if not state:
        return {
            "passed": False,
            "slice": s_name,
            "reasons": [f"NO_SLICE_STATE: State for slice '{s_name}' could not be loaded."],
            "summary_markdown": f"### ❌ Slice CI Gate: FAILED\n\nState for slice `{s_name}` not found.",
        }

    reasons: list[str] = []
    scope_violations: list[str] = []
    verified_receipts_count = 0

    # 2. Check Slice State
    allowed_states = {"COMMIT_READY", "COMPLETE"}
    if state.state not in allowed_states:
        reasons.append(
            f"STATE_NOT_TERMINAL: Slice '{s_name}' is in state '{state.state}'. Expected COMMIT_READY or COMPLETE."
        )

    # 3. Check PR diff against Scope Manifest
    try:
        diff_output = run_git_cmd(["diff", "--name-only", f"{resolved_base}...HEAD"], repo_dir, check=False)
        if not diff_output.strip():
            # If symmetric diff returns empty, try two-dot diff
            diff_output = run_git_cmd(["diff", "--name-only", resolved_base, "HEAD"], repo_dir, check=False)
        all_diff_files = [f.strip() for f in diff_output.splitlines() if f.strip()]
    except Exception as exc:
        all_diff_files = []
        reasons.append(f"GIT_DIFF_ERROR: Failed to compute PR diff against '{resolved_base}': {exc}")

    # Exclude internal orchestrator control state from scope checks
    control_rel = ""
    try:
        control_rel = control_home.resolve().relative_to(repo_dir.resolve()).as_posix()
    except Exception:
        control_rel = ".orchestrator_slice"

    code_diff_files = [
        f for f in all_diff_files
        if not f.startswith(f"{control_rel}/") and f != control_rel and not f.startswith(".git/")
    ]

    # Retrieve scope manifest
    allow_patterns: list[str] = []
    plan_rec = None
    if state.approved_plan_digest:
        plan_rec = store.get_record(state.approved_plan_digest)
        if not plan_rec:
            for r in store.list_records_by_type("PLAN"):
                if r.get("record_digest") == state.approved_plan_digest or r.get("slice") == s_name:
                    plan_rec = r
                    break
    if not plan_rec:
        for r in store.list_records_by_type("PLAN"):
            if r.get("slice") == s_name:
                plan_rec = r
                break

    if plan_rec and "scope_manifest" in plan_rec:
        raw_allows = plan_rec["scope_manifest"].get("allow_paths", [])
        for item in raw_allows:
            pat = item.get("pattern") if isinstance(item, dict) else str(item)
            if pat:
                allow_patterns.append(pat)

    for changed in code_diff_files:
        norm = normalize_repo_path(changed)
        matched = False
        for pat in allow_patterns:
            if match_path_pattern(pat, norm):
                matched = True
                break
        if not matched:
            scope_violations.append(changed)

    if scope_violations:
        reasons.append(
            f"SCOPE_VIOLATION: PR touches {len(scope_violations)} file(s) outside allowed scope: {', '.join(scope_violations[:5])}"
        )

    # 4. Check HMAC verified test receipts
    receipts = store.list_receipts(slice_name=s_name, run_id=state.run_id)
    passing_verified = 0
    for rc in receipts:
        try:
            store.verify_test_receipt_integrity(
                rc,
                expected_slice=s_name,
                expected_run_id=state.run_id,
                require_passed=True,
            )
            passing_verified += 1
        except ControlStoreError:
            continue

    verified_receipts_count = passing_verified
    if passing_verified == 0:
        reasons.append("TEST_RECEIPT_MISSING: No HMAC-verified passing test receipt found for this run.")

    passed = len(reasons) == 0

    # Build markdown summary for PR Bot / CI logs
    md_lines = []
    if passed:
        md_lines.append(f"### ✅ Slice CI Gate: PASSED (Slice `{s_name}`)")
        md_lines.append(f"- **State**: `{state.state}`")
        md_lines.append(f"- **Base Ref**: `{resolved_base}`")
        md_lines.append(f"- **Modified Files**: {len(code_diff_files)} (all within approved scope)")
        md_lines.append(f"- **Verified Test Receipts**: {verified_receipts_count} (HMAC verified)")
    else:
        md_lines.append(f"### ❌ Slice CI Gate: FAILED (Slice `{s_name}`)")
        md_lines.append(f"- **State**: `{state.state}`")
        md_lines.append(f"- **Base Ref**: `{resolved_base}`")
        md_lines.append(f"- **Blockers ({len(reasons)})**:")
        for r in reasons:
            md_lines.append(f"  - 🚫 {r}")
        if scope_violations:
            md_lines.append(f"- **Unauthorized Touched Files**:")
            for sv in scope_violations:
                md_lines.append(f"  - `{sv}`")

    return {
        "passed": passed,
        "slice": s_name,
        "run_id": state.run_id,
        "state": state.state,
        "base_ref": resolved_base,
        "changed_files": code_diff_files,
        "scope_violations": scope_violations,
        "test_receipts_verified": verified_receipts_count,
        "reasons": reasons,
        "summary_markdown": "\n".join(md_lines),
    }
