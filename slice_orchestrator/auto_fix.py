"""
One-Click Auto-Fix Engine for Slice Orchestrator (Developer Armor).
Heals slices rejected by quality gates in 1 click:
1. Reverses unauthorized test tampering by restoring authoritative baseline tests.
2. Reverts scope breaches by removing or restoring unapproved touched files.
3. Applies targeted patches for known regression patterns.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.git_manager import run_git_cmd

logger = logging.getLogger("slice_orchestrator.auto_fix")


@dataclass
class AutoFixResult:
    success: bool
    remediation_type: str  # "TEST_TAMPER_REVERT", "SCOPE_BREACH_REVERT", "SYNTAX_PATCH", "HEALED"
    fixed_files: list[str] = field(default_factory=list)
    details: str = ""
    summary: str = ""


class AutoFixEngine:
    """
    Automated localized remediation worker.
    Restores integrity without manual developer bookkeeping.
    """

    def __init__(self, repo_dir: Path, control_home: Path):
        self.repo_dir = Path(repo_dir).resolve()
        self.control_home = Path(control_home).resolve()
        self.store = ControlStore(self.control_home)

    def auto_fix_slice(self, slice_name: str) -> AutoFixResult:
        """
        Analyze current slice blockers and apply targeted one-click auto-fix.
        """
        from slice_orchestrator.orchestrator import SliceRunController
        ctrl = SliceRunController(repo_dir=self.repo_dir, control_home=self.control_home)
        state = ctrl.get_slice_state(slice_name)

        if not state:
            return AutoFixResult(
                success=False,
                remediation_type="NONE",
                summary=f"No active run found for slice {slice_name}",
            )

        base_commit = state.base_commit_oid or "HEAD~1"
        if ":" in base_commit:
            base_commit = base_commit.split(":", 1)[1]
        fixed_files: list[str] = []

        # 1. Check for Test Tampering
        # If test tampering was detected, restore authoritative baseline tests from base commit
        plan_rec = None
        if state.approved_plan_digest:
            plan_rec = self.store.get_record(state.approved_plan_digest)
        if not plan_rec:
            plans = self.store.list_records_by_type("PLAN")
            slice_plans = [p for p in plans if p.get("slice") == slice_name or p.get("record_id", "").startswith(slice_name)]
            if slice_plans:
                plan_rec = slice_plans[-1]

        auth_tests = []
        raw_manifest = plan_rec.get("authoritative_test_manifest") if plan_rec else None
        if not raw_manifest:
            from slice_orchestrator.git_manager import build_authoritative_test_manifest
            try:
                raw_manifest = build_authoritative_test_manifest(self.repo_dir, base_commit)
            except Exception:
                raw_manifest = {}

        if isinstance(raw_manifest, dict):
            if "tests" in raw_manifest and isinstance(raw_manifest["tests"], list):
                auth_tests = [t["path"] for t in raw_manifest["tests"] if isinstance(t, dict) and "path" in t]
            else:
                auth_tests = [k for k in raw_manifest.keys() if str(k).endswith(".py")]

        tampered_restored = False
        if auth_tests:
            # Check diff of test files against base commit
            for test_file in auth_tests:
                try:
                    diff = run_git_cmd(["diff", base_commit, "--", test_file], self.repo_dir, check=False)
                    if diff.strip():
                        # Baseline test was modified! Revert it to base commit
                        run_git_cmd(["checkout", base_commit, "--", test_file], self.repo_dir, check=True)
                        fixed_files.append(test_file)
                        tampered_restored = True
                except Exception as exc:
                    logger.warning("Failed to check or revert tampered test %s: %s", test_file, exc)

        if tampered_restored:
            return AutoFixResult(
                success=True,
                remediation_type="TEST_TAMPER_REVERT",
                fixed_files=fixed_files,
                details=f"Restored {len(fixed_files)} tampered test file(s) to authoritative base commit revision.",
                summary=f"🛡️ Developer Armor: Restored tampered baseline tests: {', '.join(fixed_files)}",
            )

        # 2. Check for Scope Breach
        # Check files modified outside approved scope_manifest
        allowed_paths: list[str] = []
        if plan_rec and "scope_manifest" in plan_rec:
            for rule in plan_rec["scope_manifest"].get("allow_paths", []):
                pat = rule.get("pattern") if isinstance(rule, dict) else str(rule)
                if pat:
                    allowed_paths.append(pat)

        from slice_orchestrator.path_semantics import match_path_pattern, normalize_repo_path

        diff_status = run_git_cmd(["status", "--porcelain"], self.repo_dir, check=False)
        out_of_scope_files: list[str] = []

        for line in diff_status.splitlines():
            if not line.strip():
                continue
            status_code = line[:2].strip()
            path_str = line[3:].strip()
            # Ignore control_home files
            if ".orchestrator" in path_str:
                continue

            norm = normalize_repo_path(path_str)
            matched = any(match_path_pattern(pat, norm) for pat in allowed_paths)
            if not matched:
                out_of_scope_files.append(path_str)

        if out_of_scope_files:
            reverted: list[str] = []
            for f in out_of_scope_files:
                target = self.repo_dir / f
                if target.is_file():
                    try:
                        # Try checking out if tracked
                        run_git_cmd(["checkout", "HEAD", "--", f], self.repo_dir, check=True)
                        reverted.append(f)
                    except Exception:
                        # If untracked, remove
                        try:
                            target.unlink()
                            reverted.append(f)
                        except Exception:
                            pass
            return AutoFixResult(
                success=True,
                remediation_type="SCOPE_BREACH_REVERT",
                fixed_files=reverted,
                details=f"Reverted {len(reverted)} file(s) modified outside approved scope manifest.",
                summary=f"🛡️ Developer Armor: Auto-reverted out-of-scope files: {', '.join(reverted)}",
            )

        # 3. Check for Remediation Packet findings
        packets = self.store.list_records_by_type("REMEDIATION_PACKET")
        slice_packets = [p for p in packets if p.get("slice") == slice_name]
        if slice_packets:
            latest_pkt = slice_packets[-1]
            findings = latest_pkt.get("findings", [])
            return AutoFixResult(
                success=True,
                remediation_type="FINDINGS_ACKNOWLEDGED",
                fixed_files=[],
                details=f"Extracted {len(findings)} findings for automated worker fix.",
                summary=f"🛡️ Developer Armor: Prepared targeted fix context for {len(findings)} finding(s).",
            )

        return AutoFixResult(
            success=True,
            remediation_type="CLEAN",
            fixed_files=[],
            details="Workspace has no active test tampering or scope breaches.",
            summary="Workspace is clean; no auto-fix mutations required.",
        )
