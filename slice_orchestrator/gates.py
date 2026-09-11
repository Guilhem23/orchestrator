"""
Gate Evaluator and Control-Plane Test Receipt Runner for Method v4.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import platform
import shlex
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from slice_orchestrator.canonical import canonical_json_bytes, compute_record_digest
from slice_orchestrator.control_store import ControlStore, ControlStoreError
from slice_orchestrator.git_manager import (
    CandidateTreeBuilder,
    ScopeManifestValidator,
    build_authoritative_test_manifest,
    compute_workspace_revision_digest,
    get_git_object_format,
    get_head_commit_oid,
    verify_authoritative_tests_unmodified,
)
from slice_orchestrator.state_machine import SliceRunState


class GateError(ValueError):
    """Raised when gate evaluation or authorized test execution is rejected."""
    pass


FAILURE_CODES = frozenset({
    "TESTS_FAILED",
    "WORKER_FAILED",
    "WORKER_UNAVAILABLE",
    "PLANNER_FAILED",
    "IMPLEMENTATION_FAILED",
    "MALFORMED_WORKER_OUTPUT",
})


@dataclass
class GateEvaluationResult:
    passed: bool
    reason: str
    workspace_revision_digest: str | None = None
    evidence_set_digest: str | None = None
    approved_revision_digest: str | None = None
    candidate_tree_oid: str | None = None


@dataclass
class TestExecutionResult:
    argv: list[str]
    requested_command: str
    stdout_text: str
    stderr_text: str
    exit_code: int
    passed: bool
    started_at: str
    completed_at: str


def compute_environment_digest() -> str:
    payload = "\n".join([
        sys.executable,
        sys.version,
        platform.platform(),
        platform.machine(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_toolchain_digest(argv: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()


def normalize_test_command(test_def: dict[str, Any]) -> list[str]:
    """
    Parse a test command as an argv list. Rejects empty commands.
    Does not execute a shell and does not silently drop arguments.
    """
    if "command" not in test_def or test_def.get("command") is None:
        raise GateError("EMPTY_TEST_COMMAND: test command is missing")

    cmd = test_def.get("command")
    if isinstance(cmd, (list, tuple)):
        argv = [str(x) for x in cmd]
    elif isinstance(cmd, str):
        if not cmd.strip():
            raise GateError("EMPTY_TEST_COMMAND: test command is empty")
        argv = shlex.split(cmd)
    else:
        raise GateError("INVALID_TEST_COMMAND: command must be a string or argv list")

    if not argv or not str(argv[0]).strip():
        raise GateError("EMPTY_TEST_COMMAND: test command is empty")
    return argv


def resolve_test_argv(argv: list[str]) -> list[str]:
    """
    Resolve a portable pytest invocation without lying about the recorded command.
    Only the bare token 'pytest' is rewritten to an executable argv; arguments are kept.
    """
    resolved = list(argv)
    if resolved[0] == "pytest":
        which = shutil.which("pytest")
        if which:
            resolved[0] = which
        else:
            resolved = [sys.executable, "-m", "pytest"] + resolved[1:]
    return resolved


def execute_control_test(test_def: dict[str, Any], repo_dir: Path) -> TestExecutionResult:
    """
    Execute a required test command fail-closed. Never uses shell=True.
    Caller-controlled expected_exit_code cannot weaken the gate: only exit 0 passes.
    """
    expected_exit = test_def.get("expected_exit_code", 0)
    if expected_exit not in (None, 0):
        raise GateError(
            "EXPECTED_EXIT_CODE_ABUSE: caller-controlled expected_exit_code "
            f"{expected_exit!r} cannot weaken validation; required tests must exit 0"
        )

    requested_argv = normalize_test_command(test_def)
    argv = resolve_test_argv(requested_argv)
    requested_command = test_def["command"] if isinstance(test_def.get("command"), str) else " ".join(requested_argv)

    start_time = datetime.now(timezone.utc).isoformat()
    stdout_text = ""
    stderr_text = ""
    exit_code = 127
    passed = False

    try:
        res = subprocess.run(
            argv,
            shell=False,
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        stdout_text = res.stdout or ""
        stderr_text = res.stderr or ""
        exit_code = res.returncode
        passed = exit_code == 0
    except FileNotFoundError as exc:
        stdout_text = ""
        stderr_text = f"EXECUTION_ERROR: FileNotFoundError: {exc}"
        exit_code = 127
        passed = False
    except subprocess.TimeoutExpired as exc:
        stdout_text = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8") if exc.stdout else "")
        stderr_text = f"TIMEOUT: Test execution timed out after 15s. {exc.stderr or ''}"
        exit_code = 124
        passed = False
    except Exception as exc:
        stdout_text = ""
        stderr_text = f"EXECUTION_ERROR: {type(exc).__name__}: {str(exc)}"
        exit_code = 1
        passed = False

    end_time = datetime.now(timezone.utc).isoformat()
    return TestExecutionResult(
        argv=argv,
        requested_command=requested_command,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        exit_code=exit_code,
        passed=passed,
        started_at=start_time,
        completed_at=end_time,
    )


def persist_signed_receipt(
    execution: TestExecutionResult,
    test_def: dict[str, Any],
    repo_dir: Path,
    candidate_tree_oid: str,
    workspace_revision_digest: str,
    control_store: ControlStore,
    slice_name: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Persist an HMAC-signed receipt bound to slice/run/tree/workspace digest."""
    test_id = test_def.get("test_id", f"test-{uuid.uuid4().hex[:6]}")
    receipt_id = f"receipt-{uuid.uuid4().hex[:8]}"
    gate_execution_id = str(uuid.uuid4())

    receipt_data = {
        "schema_version": 4,
        "record_type": "TEST_RECEIPT",
        "receipt_id": receipt_id,
        "test_id": test_id,
        "slice": slice_name,
        "run_id": run_id,
        "candidate_tree_oid": candidate_tree_oid,
        "workspace_revision_digest": workspace_revision_digest,
        "command": execution.requested_command,
        "executed_argv": execution.argv,
        "working_directory": str(repo_dir),
        "environment_digest": compute_environment_digest(),
        "toolchain_digest": compute_toolchain_digest(execution.argv),
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "exit_code": execution.exit_code,
        "expected_exit_code": 0,
        "passed": execution.passed,
        "passed_count": 1 if execution.passed else 0,
        "failed_count": 0 if execution.passed else 1,
        "skipped_count": 0,
        "stdout_digest": hashlib.sha256(execution.stdout_text.encode("utf-8")).hexdigest(),
        "stderr_digest": hashlib.sha256(execution.stderr_text.encode("utf-8")).hexdigest(),
        "produced_artifact_digests": [],
        "gate_execution_id": gate_execution_id,
        "authorized_gate_execution": True,
    }
    receipt_data["receipt_mac"] = control_store.sign_receipt(receipt_data)
    digest = control_store.store_record("TEST_RECEIPT", receipt_id, receipt_data)
    receipt_data["record_digest"] = digest
    return receipt_data


def run_control_test(
    test_def: dict[str, Any],
    repo_dir: Path,
    candidate_tree_oid: str,
    workspace_revision_digest: str,
    control_store: ControlStore,
    slice_name: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute a required test command and record a schema-compliant signed test receipt.
    Fails closed on empty command, expected-exit abuse, command-not-found, timeout,
    non-zero exit, exceptions, or missing toolchain.
    """
    execution = execute_control_test(test_def, repo_dir)
    return persist_signed_receipt(
        execution,
        test_def,
        repo_dir,
        candidate_tree_oid,
        workspace_revision_digest,
        control_store,
        slice_name=slice_name,
        run_id=run_id,
    )


class GateEvaluator:
    """
    Evaluates mechanical preconditions for COMMIT_READY -> COMMIT_RECORDED transition.
    """

    def __init__(self, repo_dir: Path, control_store: ControlStore):
        self.repo_dir = repo_dir.resolve()
        self.control_store = control_store

    def evaluate_commit_gate(self, state: SliceRunState) -> GateEvaluationResult:
        """
        Deterministically validate all preconditions for commit.
        A passing, tree-bound, HMAC-signed receipt is mandatory.
        """
        if state.state == "FAILED" or (
            state.state == "STOPPED" and (state.stop_reason_code or "") in FAILURE_CODES
        ):
            return GateEvaluationResult(
                passed=False,
                reason=f"Terminal failure state {state.state} ({state.stop_reason_code})",
            )

        if state.state != "COMMIT_READY":
            return GateEvaluationResult(passed=False, reason=f"State is {state.state}, expected COMMIT_READY")

        if not state.latest_review_record_id:
            return GateEvaluationResult(passed=False, reason="Missing latest review record ID")

        if not state.approved_plan_digest:
            return GateEvaluationResult(passed=False, reason="Missing current approved plan")

        review_rec = self.control_store.get_record(state.latest_review_record_id)
        if not review_rec:
            return GateEvaluationResult(passed=False, reason=f"Review record {state.latest_review_record_id} not found in store")

        if review_rec.get("verdict") != "APPROVED":
            return GateEvaluationResult(passed=False, reason=f"Review verdict is {review_rec.get('verdict')}, expected APPROVED")

        # Check reviewer independence and self-approval
        impl_principal = review_rec.get("implementer_principal")
        rev_principal = review_rec.get("reviewer_principal")
        if impl_principal and rev_principal and impl_principal == rev_principal:
            return GateEvaluationResult(
                passed=False,
                reason=f"SELF_APPROVAL_REJECTED: Implementer '{impl_principal}' cannot act as adversarial reviewer",
            )
        if review_rec.get("is_self_approved"):
            return GateEvaluationResult(
                passed=False,
                reason="SELF_APPROVAL_REJECTED: Review was self-approved by implementer actor",
            )

        if review_rec.get("blocking_finding_count", 0) != 0:
            return GateEvaluationResult(
                passed=False, reason=f"Review has {review_rec.get('blocking_finding_count')} blocking findings"
            )

        if state.open_remediation_packet_ids:
            resolved_mappings = review_rec.get("verified_resolved_findings", [])
            resolved_packet_ids = {m.get("packet_id") for m in resolved_mappings}
            for pkt_id in state.open_remediation_packet_ids:
                if pkt_id not in resolved_packet_ids:
                    return GateEvaluationResult(
                        passed=False, reason=f"Open remediation packet {pkt_id} is not verified resolved"
                    )

        pb = self.control_store.load_and_verify_policy_bundle()

        builder = CandidateTreeBuilder(self.repo_dir, self.control_store.control_home)
        base_commit = state.base_commit_oid or get_head_commit_oid(self.repo_dir)
        captured_tree_oid = builder.capture_candidate_tree(base_commit)

        git_fmt = get_git_object_format(self.repo_dir)
        current_workspace_rev_digest = compute_workspace_revision_digest(
            project_id=state.project_id,
            git_object_format=git_fmt,
            base_commit_oid=base_commit,
            candidate_tree_oid=captured_tree_oid,
            plan_revision=state.plan_revision,
            plan_digest=state.approved_plan_digest or "",
            scope_manifest_digest=state.scope_manifest_digest or "",
            required_test_plan_digest=state.required_test_plan_digest or "",
            policy_bundle_digest=pb.computed_digest,
        )

        if state.workspace_revision_digest and current_workspace_rev_digest != state.workspace_revision_digest:
            return GateEvaluationResult(
                passed=False,
                reason=(
                    f"Workspace revision mismatch! Current: {current_workspace_rev_digest[:12]}, "
                    f"Accepted: {state.workspace_revision_digest[:12]}"
                ),
                workspace_revision_digest=current_workspace_rev_digest,
                candidate_tree_oid=captured_tree_oid,
            )

        receipt = self._require_bound_passing_receipt(state, captured_tree_oid, current_workspace_rev_digest)
        if isinstance(receipt, GateEvaluationResult):
            return receipt

        # Verify authoritative control test provenance and immutability
        plan_rec = None
        if state.approved_plan_digest:
            plan_rec = self.control_store.get_record(state.approved_plan_digest)
            if not plan_rec:
                for r in self.control_store.list_records_by_type("PLAN"):
                    if (r.get("record_digest") == state.approved_plan_digest
                        or r.get("plan_id") == state.approved_plan_digest
                        or r.get("record_id") == state.approved_plan_digest
                        or r.get("slice") == state.slice):
                        plan_rec = r
                        break

        auth_manifest = None
        allowed_mods = []
        if plan_rec:
            if plan_rec.get("authoritative_test_manifest"):
                auth_manifest = plan_rec["authoritative_test_manifest"]
            scope_m = plan_rec.get("scope_manifest", {})
            for rule in scope_m.get("allow_paths", []):
                pat = rule.get("pattern") if isinstance(rule, dict) else str(rule)
                if pat:
                    allowed_mods.append(pat)

        if not auth_manifest:
            auth_manifest = build_authoritative_test_manifest(self.repo_dir, base_commit)

        test_ok, test_fail_reason = verify_authoritative_tests_unmodified(
            self.repo_dir, base_commit, auth_manifest, allowed_modifications=allowed_mods
        )
        if not test_ok:
            return GateEvaluationResult(
                passed=False,
                reason=test_fail_reason,
                workspace_revision_digest=current_workspace_rev_digest,
                candidate_tree_oid=captured_tree_oid,
            )

        diff_entries = builder.compute_base_to_candidate_diff(base_commit, captured_tree_oid)
        scope_manifest_rec = None
        if state.approved_plan_digest:
            plan_rec = self.control_store.get_record(state.approved_plan_digest)
            if plan_rec:
                scope_manifest_rec = plan_rec.get("scope_manifest")
            if scope_manifest_rec is None:
                # approved_plan_digest is a digest; locate the plan record by digest
                for rec in self.control_store.list_records_by_type("PLAN"):
                    if rec.get("record_digest") == state.approved_plan_digest or rec.get("plan_digest") == state.approved_plan_digest:
                        scope_manifest_rec = rec.get("scope_manifest")
                        break

        if scope_manifest_rec:
            val = ScopeManifestValidator(scope_manifest_rec, pb.protected_files)
            try:
                val.check_diff(diff_entries)
            except Exception as exc:
                return GateEvaluationResult(passed=False, reason=f"Scope or protected path check failed: {exc}")

        return GateEvaluationResult(
            passed=True,
            reason="All deterministic gate checks passed",
            workspace_revision_digest=current_workspace_rev_digest,
            evidence_set_digest=state.evidence_set_digest,
            approved_revision_digest=state.approved_revision_digest,
            candidate_tree_oid=captured_tree_oid,
        )

    def _require_bound_passing_receipt(
        self,
        state: SliceRunState,
        captured_tree_oid: str,
        current_workspace_rev_digest: str,
    ) -> dict[str, Any] | GateEvaluationResult:
        receipts = self.control_store.list_receipts(slice_name=state.slice, run_id=state.run_id)
        if not receipts:
            return GateEvaluationResult(passed=False, reason="Missing authorized test receipt")

        bound: list[dict[str, Any]] = []
        for receipt in receipts:
            try:
                self.control_store.verify_test_receipt_integrity(
                    receipt,
                    expected_slice=state.slice,
                    expected_run_id=state.run_id,
                    expected_tree=captured_tree_oid,
                    expected_digest=current_workspace_rev_digest,
                    require_passed=True,
                )
                bound.append(receipt)
            except ControlStoreError:
                continue

        if not bound:
            return GateEvaluationResult(
                passed=False,
                reason=(
                    "No authorized passing test receipt bound to the current candidate tree "
                    "and workspace revision digest"
                ),
            )
        return bound[-1]
