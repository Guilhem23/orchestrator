"""
Worker Protocol (slice-worker-v1) and Worker Backend Adapters.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from slice_orchestrator.canonical import compute_record_digest


@dataclass
class WorkerInputBundle:
    assignment_id: str
    run_id: str
    slice: str
    role: str
    prompt: str
    base_commit_oid: str
    workspace_dir: Path
    output_dir: Path
    plan_text: str | None = None
    scope_manifest: dict[str, Any] | None = None
    test_plan: list[dict[str, Any]] | None = None
    role_context: dict[str, Any] | None = None
    remediation_packets: list[dict[str, Any]] = field(default_factory=list)
    candidate_tree_oid: str | None = None
    workspace_revision_digest: str | None = None
    evidence_set_digest: str | None = None
    context_pack_digest: str | None = None
    objective: dict[str, Any] | None = None
    work_item: dict[str, Any] | None = None
    learnings: list[dict[str, Any]] = field(default_factory=list)
    adapter_version: str = "1.0.0"
    worker_identity: str = "default-worker"


@dataclass
class WorkerResult:
    success: bool
    role: str
    execution_id: str
    worker_instance_id: str
    adapter_id: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    role_context_update: dict[str, Any] | None = None
    error_message: str | None = None
    availability: str = "AVAILABLE"  # AVAILABLE | UNAVAILABLE | TEST_ONLY
    test_only: bool = False
    failure_classification: str | None = None  # SUCCESS | UNAVAILABLE | TIMEOUT | NON_ZERO_EXIT | MALFORMED_RESULT | EXECUTION_ERROR | CANCELLED


class AbstractWorkerAdapter(ABC):
    """
    Abstract slice-worker-v1 adapter.
    """

    adapter_id: str = "abstract"

    @abstractmethod
    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        """
        Execute worker task for the given role within capability profile.
        """
        pass


class TestDummyWorkerAdapter(AbstractWorkerAdapter):
    """
    Predictable deterministic worker adapter used for unit/integration testing and dry-runs.
    """
    __test__ = False

    adapter_id: str = "dummy"

    def __init__(
        self,
        architecture_approval: bool = True,
        review_approval: bool = True,
        blocking_findings: list[dict[str, Any]] | None = None,
        custom_implementation_fn: Callable[[WorkerInputBundle], None] | None = None,
    ):
        self.architecture_approval = architecture_approval
        self.review_approval = review_approval
        self.blocking_findings = blocking_findings or []
        self.custom_implementation_fn = custom_implementation_fn

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        instance_id = f"worker-inst-{uuid.uuid4().hex[:8]}"

        if bundle.role == "PLANNER":
            plan_record_id = str(uuid.uuid4())
            plan_text = f"Plan for {bundle.slice}"
            plan_digest = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()

            scope_manifest = bundle.scope_manifest or {
                "schema_version": 4,
                "project_id": "governed-multikb-platform-blueprint",
                "slice": bundle.slice,
                "plan_revision": 0,
                "allow_paths": [
                    {"pattern": "src/**", "allowed_operations": ["add", "modify", "delete"]},
                    {"pattern": "tests/**", "allowed_operations": ["add", "modify", "delete"]},
                    {"pattern": "evidence/**", "allowed_operations": ["add", "modify", "delete"]}
                ]
            }
            scope_digest = compute_record_digest(scope_manifest)

            test_plan = bundle.test_plan or [
                {
                    "test_id": "test_unit",
                    "command": ["uv", "run", "pytest", "-q"],
                    "working_directory": ".",
                    "required": True,
                    "expected_exit_code": 0,
                    "allow_skips": False
                }
            ]
            test_plan_digest = compute_record_digest(test_plan)

            plan_record = {
                "schema_version": 4,
                "record_id": plan_record_id,
                "project_id": "governed-multikb-platform-blueprint",
                "slice": bundle.slice,
                "plan_revision": 0,
                "plan_digest": plan_digest,
                "scope_manifest": scope_manifest,
                "scope_manifest_digest": scope_digest,
                "test_plan": test_plan,
                "test_plan_digest": test_plan_digest,
                "base_commit_oid": bundle.base_commit_oid,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            return WorkerResult(
                success=True,
                role="PLANNER",
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                artifacts={"plan": plan_record},
                summary=f"[TEST-ONLY dummy] Created plan for {bundle.slice}",
                availability="TEST_ONLY",
                test_only=True,
            )

        elif bundle.role == "ARCHITECTURE_REVIEWER":
            arch_id = str(uuid.uuid4())
            arch_data = {
                "schema_version": 4,
                "record_type": "ARCHITECTURE_REVIEW",
                "architecture_review_id": arch_id,
                "slice": bundle.slice,
                "plan_revision": 0,
                "verdict": "APPROVED" if self.architecture_approval else "BLOCKED",
                "findings": [] if self.architecture_approval else [{"finding_id": "ARCH-01", "description": "Architecture flaw"}],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            return WorkerResult(
                success=True,
                role="ARCHITECTURE_REVIEWER",
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                artifacts={"architecture_review": arch_data},
                summary="[TEST-ONLY dummy] Architecture review completed",
                availability="TEST_ONLY",
                test_only=True,
            )

        elif bundle.role == "IMPLEMENTER":
            if self.custom_implementation_fn:
                self.custom_implementation_fn(bundle)
            else:
                src_dir = bundle.workspace_dir / "src"
                src_dir.mkdir(parents=True, exist_ok=True)
                (src_dir / "impl.py").write_text(f"# Implementation for {bundle.slice}\n")

            role_ctx_update = {
                "summary": f"Implemented vertical slice {bundle.slice}",
                "paths": ["src/impl.py"],
            }
            return WorkerResult(
                success=True,
                role="IMPLEMENTER",
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                summary=f"[TEST-ONLY dummy] Implementation completed for {bundle.slice}",
                role_context_update=role_ctx_update,
                availability="TEST_ONLY",
                test_only=True,
            )

        elif bundle.role == "ADVERSARIAL_REVIEWER":
            rev_id = str(uuid.uuid4())
            verdict = "APPROVED" if self.review_approval else "BLOCKED"
            findings = [] if self.review_approval else (self.blocking_findings or [{
                "finding_id": "FINDING-01",
                "description": "Defect found in adversarial review",
                "required_remediation": "Fix defect in src/impl.py"
            }])

            resolved_mapping = []
            if self.review_approval and bundle.remediation_packets:
                for pkt in bundle.remediation_packets:
                    for f_item in pkt.get("findings", []):
                        resolved_mapping.append({
                            "packet_id": pkt.get("remediation_packet_id"),
                            "finding_id": f_item.get("finding_id"),
                            "resolution_status": "VERIFIED_RESOLVED",
                            "evidence_reference": "receipts/test_unit.json"
                        })

            review_data = {
                "schema_version": 4,
                "record_type": "ADVERSARIAL_REVIEW",
                "review_id": rev_id,
                "slice": bundle.slice,
                "verdict": verdict,
                "blocking_finding_count": len(findings),
                "findings": findings,
                "verified_resolved_findings": resolved_mapping,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            return WorkerResult(
                success=True,
                role="ADVERSARIAL_REVIEWER",
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                artifacts={"review": review_data},
                summary=f"[TEST-ONLY dummy] Adversarial review verdict: {verdict}",
                availability="TEST_ONLY",
                test_only=True,
            )

        elif bundle.role in ("GOVERNANCE_AGENT", "REMEDIATOR", "EXPLORER"):
            gov_id = str(uuid.uuid4())
            gov_data = {
                "schema_version": 4,
                "record_type": bundle.role,
                "record_id": gov_id,
                "slice": bundle.slice,
                "status": "RECONCILED",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            if bundle.role == "REMEDIATOR":
                if self.custom_implementation_fn:
                    self.custom_implementation_fn(bundle)
                else:
                    src_dir = bundle.workspace_dir / "src"
                    src_dir.mkdir(parents=True, exist_ok=True)
                    (src_dir / "impl.py").write_text(f"# Remediation for {bundle.slice}\n")

            return WorkerResult(
                success=True,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                artifacts={bundle.role.lower(): gov_data},
                summary=f"[TEST-ONLY dummy] {bundle.role} completed for {bundle.slice}",
                availability="TEST_ONLY",
                test_only=True,
            )

        else:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                error_message=f"Unknown role {bundle.role}",
            )


DEFAULT_ENV_ALLOWLIST = [
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "PYTHONPATH", "USER"
]


def validate_worker_result_binding(
    bundle: WorkerInputBundle,
    result_payload: dict[str, Any],
    seen_assignments: set[str] | None = None,
) -> tuple[bool, str | None]:
    """
    Validates context and result binding for a worker execution result.
    Checks run_id, slice, assignment_id, role, candidate_tree_oid,
    workspace_revision_digest, context_pack_digest, duplicate assignment, and timestamps.
    """
    if not isinstance(result_payload, dict):
        return False, "Worker result payload is not a JSON object"

    required_fields = [
        "run_id", "slice", "assignment_id", "role",
        "worker_identity", "adapter_version"
    ]
    for field_name in required_fields:
        if field_name not in result_payload or result_payload[field_name] is None:
            return False, f"Missing required binding field {field_name!r}"

    if str(result_payload["run_id"]) != str(bundle.run_id):
        return False, f"Wrong run ID: expected {bundle.run_id!r}, got {result_payload['run_id']!r}"

    if str(result_payload["slice"]) != str(bundle.slice):
        return False, f"Wrong slice ID: expected {bundle.slice!r}, got {result_payload['slice']!r}"

    if str(result_payload["assignment_id"]) != str(bundle.assignment_id):
        return False, f"Wrong assignment ID: expected {bundle.assignment_id!r}, got {result_payload['assignment_id']!r}"

    if str(result_payload["role"]) != str(bundle.role):
        return False, f"Wrong role: expected {bundle.role!r}, got {result_payload['role']!r}"

    if bundle.candidate_tree_oid is not None:
        got_tree = result_payload.get("candidate_tree_oid")
        if str(got_tree) != str(bundle.candidate_tree_oid):
            return False, f"Stale candidate tree OID: expected {bundle.candidate_tree_oid!r}, got {got_tree!r}"

    if bundle.workspace_revision_digest is not None:
        got_ws = result_payload.get("workspace_revision_digest")
        if str(got_ws) != str(bundle.workspace_revision_digest):
            return False, f"Stale workspace revision digest: expected {bundle.workspace_revision_digest!r}, got {got_ws!r}"

    expected_cp = bundle.evidence_set_digest or bundle.context_pack_digest
    if expected_cp:
        got_cp = result_payload.get("context_pack_digest")
        if not got_cp:
            return False, f"Missing context_pack_digest: expected {expected_cp!r}"
        if str(got_cp) != str(expected_cp):
            return False, f"Missing or mismatched context pack digest: expected {expected_cp!r}, got {got_cp!r}"
    else:
        if "context_pack_digest" not in result_payload or not result_payload.get("context_pack_digest"):
            return False, "Missing context_pack_digest in worker result"

    if seen_assignments is not None:
        if bundle.assignment_id in seen_assignments:
            return False, f"Duplicate assignment ID or reused result: {bundle.assignment_id!r}"

    # Verify start/end timestamps if present
    start_time = result_payload.get("start_time")
    end_time = result_payload.get("end_time")
    if start_time and end_time:
        try:
            st = datetime.fromisoformat(str(start_time))
            et = datetime.fromisoformat(str(end_time))
            if et < st:
                return False, f"Invalid timestamps: end_time {end_time} is before start_time {start_time}"
        except ValueError:
            return False, f"Malformed timestamp format: start={start_time!r}, end={end_time!r}"

    return True, None


class SubprocessWorkerAdapter(AbstractWorkerAdapter):
    """
    Generic provider-neutral external subprocess worker adapter.
    Executes an external worker process using strict capability limits,
    isolated environment allowlisting, resource limits, and structured context binding.
    """

    adapter_id: str = "subprocess"

    def __init__(
        self,
        executable_path: str | Path | None = None,
        args: list[str] | None = None,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 10 * 1024 * 1024,
        env_allowlist: list[str] | None = None,
        adapter_id: str = "subprocess",
        adapter_version: str = "1.0.0",
        worker_identity: str = "generic-subprocess-worker",
    ):
        self.executable_path = executable_path
        self.args = args or []
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.env_allowlist = env_allowlist or DEFAULT_ENV_ALLOWLIST
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self.worker_identity = worker_identity
        self.seen_assignments: set[str] = set()

    def _resolve_executable(self) -> Path | None:
        if not self.executable_path:
            return None
        p = Path(self.executable_path)
        if p.is_file() and os.access(p, os.X_OK):
            return p.resolve()
        found = shutil.which(str(self.executable_path))
        if found:
            return Path(found).resolve()
        return None

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        instance_id = f"subprocess-{uuid.uuid4().hex[:8]}"
        start_time = datetime.now(timezone.utc).isoformat()

        exec_bin = self._resolve_executable()
        if exec_bin is None:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                failure_classification="UNAVAILABLE",
                error_message=f"UNAVAILABLE: Worker executable {self.executable_path!r} not found or not executable",
            )

        # Environment restriction
        isolated_env = {
            k: v for k, v in os.environ.items() if k in self.env_allowlist
        }

        # Prepare isolated work directory and input bundle file
        work_dir = bundle.workspace_dir
        output_dir = bundle.output_dir / "worker_runs" / bundle.assignment_id
        output_dir.mkdir(parents=True, exist_ok=True)

        expected_cp = bundle.evidence_set_digest or bundle.context_pack_digest or hashlib.sha256(b"context").hexdigest()

        input_payload = {
            "schema_version": 4,
            "assignment_id": bundle.assignment_id,
            "run_id": bundle.run_id,
            "slice": bundle.slice,
            "role": bundle.role,
            "prompt": bundle.prompt,
            "base_commit_oid": bundle.base_commit_oid,
            "candidate_tree_oid": bundle.candidate_tree_oid,
            "workspace_revision_digest": bundle.workspace_revision_digest,
            "context_pack_digest": expected_cp,
            "adapter_version": self.adapter_version,
            "worker_identity": self.worker_identity,
            "output_dir": str(output_dir.resolve()),
            "workspace_dir": str(work_dir.resolve()),
        }

        input_file = output_dir / "worker_input.json"
        input_file.write_text(json.dumps(input_payload, indent=2), encoding="utf-8")

        result_file = output_dir / "worker_result.json"

        cmd = [str(exec_bin)] + self.args + [str(input_file.resolve())]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(work_dir.resolve()),
                env=isolated_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return WorkerResult(
                    success=False,
                    role=bundle.role,
                    execution_id=exec_id,
                    worker_instance_id=instance_id,
                    adapter_id=self.adapter_id,
                    availability="AVAILABLE",
                    failure_classification="TIMEOUT",
                    error_message=f"TIMEOUT: Worker subprocess timed out after {self.timeout_seconds}s",
                )
            except Exception as exc:
                proc.kill()
                proc.communicate()
                return WorkerResult(
                    success=False,
                    role=bundle.role,
                    execution_id=exec_id,
                    worker_instance_id=instance_id,
                    adapter_id=self.adapter_id,
                    availability="AVAILABLE",
                    failure_classification="CANCELLED",
                    error_message=f"CANCELLED: Subprocess execution cancelled or interrupted: {exc}",
                )

        except Exception as exc:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                availability="AVAILABLE",
                failure_classification="EXECUTION_ERROR",
                error_message=f"EXECUTION_ERROR: Failed to launch worker process: {exc}",
            )

        end_time = datetime.now(timezone.utc).isoformat()

        # Check output size limits
        if len(stdout_bytes) > self.max_output_bytes or len(stderr_bytes) > self.max_output_bytes:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                availability="AVAILABLE",
                failure_classification="MALFORMED_RESULT",
                error_message=f"MALFORMED_RESULT: Worker output exceeded maximum allowed size of {self.max_output_bytes} bytes",
            )

        if proc.returncode != 0:
            stderr_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                availability="AVAILABLE",
                failure_classification="NON_ZERO_EXIT",
                error_message=f"NON_ZERO_EXIT: Subprocess exited with code {proc.returncode}: {stderr_msg}",
            )

        # Parse output JSON (either from result_file or stdout)
        payload = None
        if result_file.is_file():
            if result_file.stat().st_size > self.max_output_bytes:
                return WorkerResult(
                    success=False,
                    role=bundle.role,
                    execution_id=exec_id,
                    worker_instance_id=instance_id,
                    adapter_id=self.adapter_id,
                    availability="AVAILABLE",
                    failure_classification="MALFORMED_RESULT",
                    error_message=f"MALFORMED_RESULT: Result file exceeded maximum size {self.max_output_bytes} bytes",
                )
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception as exc:
                return WorkerResult(
                    success=False,
                    role=bundle.role,
                    execution_id=exec_id,
                    worker_instance_id=instance_id,
                    adapter_id=self.adapter_id,
                    availability="AVAILABLE",
                    failure_classification="MALFORMED_RESULT",
                    error_message=f"MALFORMED_RESULT: Failed to parse result JSON file: {exc}",
                )
        else:
            stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
            try:
                payload = json.loads(stdout_text)
            except Exception as exc:
                return WorkerResult(
                    success=False,
                    role=bundle.role,
                    execution_id=exec_id,
                    worker_instance_id=instance_id,
                    adapter_id=self.adapter_id,
                    availability="AVAILABLE",
                    failure_classification="MALFORMED_RESULT",
                    error_message=f"MALFORMED_RESULT: No result file and stdout is not valid JSON: {exc}",
                )

        if not isinstance(payload, dict):
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                availability="AVAILABLE",
                failure_classification="MALFORMED_RESULT",
                error_message="MALFORMED_RESULT: Result JSON payload must be an object",
            )

        # Fill default start_time / end_time / metadata if missing in payload
        if "start_time" not in payload:
            payload["start_time"] = start_time
        if "end_time" not in payload:
            payload["end_time"] = end_time
        if "adapter_version" not in payload:
            payload["adapter_version"] = self.adapter_version
        if "worker_identity" not in payload:
            payload["worker_identity"] = self.worker_identity

        # Validate Context and Result Binding
        valid, bind_err = validate_worker_result_binding(
            bundle, payload, seen_assignments=self.seen_assignments
        )
        if not valid:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=exec_id,
                worker_instance_id=instance_id,
                adapter_id=self.adapter_id,
                availability="AVAILABLE",
                failure_classification="MALFORMED_RESULT",
                error_message=f"MALFORMED_RESULT: Result binding validation failed: {bind_err}",
            )

        # Mark assignment as seen/consumed
        self.seen_assignments.add(bundle.assignment_id)

        # Check payload success
        is_success = bool(payload.get("success", True))
        if not is_success:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id=payload.get("execution_id", exec_id),
                worker_instance_id=payload.get("worker_instance_id", instance_id),
                adapter_id=self.adapter_id,
                artifacts=payload.get("artifacts", {}),
                summary=payload.get("summary", "Worker returned unsuccessful status"),
                error_message=payload.get("error_message", "Worker execution indicated failure"),
                availability="AVAILABLE",
                failure_classification="EXECUTION_ERROR",
            )

        return WorkerResult(
            success=True,
            role=bundle.role,
            execution_id=payload.get("execution_id", exec_id),
            worker_instance_id=payload.get("worker_instance_id", instance_id),
            adapter_id=self.adapter_id,
            artifacts=payload.get("artifacts", {}),
            summary=payload.get("summary", f"Subprocess worker completed for {bundle.role}"),
            role_context_update=payload.get("role_context_update"),
            availability="AVAILABLE",
            failure_classification="SUCCESS",
        )


class ManualWorkerAdapter(AbstractWorkerAdapter):
    adapter_id: str = "manual"

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        exec_id = f"exec-manual-{uuid.uuid4().hex[:8]}"
        instance_id = f"worker-manual-{uuid.uuid4().hex[:8]}"

        print("\n" + "=" * 60)
        print(f" MANUAL WORKER REQUIRED — ROLE: {bundle.role}")
        print("=" * 60)
        print(f"Run ID: {bundle.run_id}")
        print(f"Slice:  {bundle.slice}")
        print(f"Workspace Path: {bundle.workspace_dir}")
        print(f"Output Path:    {bundle.output_dir}")
        print("-" * 60)
        print("Prompt Instructions:")
        print(bundle.prompt)
        print("-" * 60)

        result_file = bundle.output_dir / "worker_result.json"
        if result_file.is_file():
            try:
                res_data = json.loads(result_file.read_text(encoding="utf-8"))
                return WorkerResult(
                    success=res_data.get("success", True),
                    role=bundle.role,
                    execution_id=exec_id,
                    worker_instance_id=instance_id,
                    adapter_id=self.adapter_id,
                    artifacts=res_data.get("artifacts", {}),
                    summary=res_data.get("summary", "Manual worker completed via result file"),
                    role_context_update=res_data.get("role_context_update"),
                )
            except Exception as exc:
                print(f"Error reading result file {result_file}: {exc}")

        return WorkerResult(
            success=False,
            role=bundle.role,
            execution_id=exec_id,
            worker_instance_id=instance_id,
            adapter_id=self.adapter_id,
            availability="UNAVAILABLE",
            error_message="Manual worker produced no worker_result.json; refusing implicit success",
        )


class CursorWorkerAdapter(AbstractWorkerAdapter):
    adapter_id: str = "cursor"

    def __init__(self, executable_path: str | Path | None = None, fallback_to_dummy: bool = False):
        """
        Cursor worker adapter.
        Uses SubprocessWorkerAdapter if executable_path is provided or CURSOR_WORKER_EXECUTABLE env var is set.
        """
        self.fallback_to_dummy = fallback_to_dummy
        self.executable_path = executable_path or os.environ.get("CURSOR_WORKER_EXECUTABLE")
        self._subprocess_adapter = SubprocessWorkerAdapter(
            executable_path=self.executable_path,
            adapter_id="cursor",
            worker_identity="cursor-worker",
        ) if self.executable_path else None

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        if self._subprocess_adapter and self._subprocess_adapter._resolve_executable():
            return self._subprocess_adapter.run(bundle)

        if not self.fallback_to_dummy:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="exec-failed",
                worker_instance_id="cursor-unavailable",
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                failure_classification="UNAVAILABLE",
                error_message="UNAVAILABLE: Cursor worker adapter executable not found or not configured; vendor adapter not implemented.",
            )

        # TESTING ONLY: Explicit fallback — visibly marked, never silent
        dummy = TestDummyWorkerAdapter()
        res = dummy.run(bundle)
        res.adapter_id = self.adapter_id
        res.availability = "TEST_ONLY"
        res.test_only = True
        res.summary = f"[TEST-ONLY dummy fallback for {self.adapter_id}] {res.summary}"
        return res


class ClaudeCodeWorkerAdapter(AbstractWorkerAdapter):
    adapter_id: str = "claude-code"

    def __init__(self, executable_path: str | Path | None = None, fallback_to_dummy: bool = False):
        """
        Claude Code worker adapter.
        Uses SubprocessWorkerAdapter if executable_path is provided or CLAUDE_WORKER_EXECUTABLE env var is set.
        """
        self.fallback_to_dummy = fallback_to_dummy
        self.executable_path = executable_path or os.environ.get("CLAUDE_WORKER_EXECUTABLE")
        self._subprocess_adapter = SubprocessWorkerAdapter(
            executable_path=self.executable_path,
            adapter_id="claude-code",
            worker_identity="claude-worker",
        ) if self.executable_path else None

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        if self._subprocess_adapter and self._subprocess_adapter._resolve_executable():
            return self._subprocess_adapter.run(bundle)

        if not self.fallback_to_dummy:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="exec-failed",
                worker_instance_id="claude-unavailable",
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                failure_classification="UNAVAILABLE",
                error_message="UNAVAILABLE: Claude Code worker adapter executable not found or not configured; vendor adapter not implemented.",
            )

        dummy = TestDummyWorkerAdapter()
        res = dummy.run(bundle)
        res.adapter_id = self.adapter_id
        res.availability = "TEST_ONLY"
        res.test_only = True
        res.summary = f"[TEST-ONLY dummy fallback for {self.adapter_id}] {res.summary}"
        return res


class GeminiWorkerAdapter(AbstractWorkerAdapter):
    adapter_id: str = "gemini"

    def __init__(self, executable_path: str | Path | None = None, fallback_to_dummy: bool = False):
        """
        Gemini worker adapter.
        Uses SubprocessWorkerAdapter if executable_path is provided or GEMINI_WORKER_EXECUTABLE env var is set.
        """
        self.fallback_to_dummy = fallback_to_dummy
        self.executable_path = executable_path or os.environ.get("GEMINI_WORKER_EXECUTABLE")
        self._subprocess_adapter = SubprocessWorkerAdapter(
            executable_path=self.executable_path,
            adapter_id="gemini",
            worker_identity="gemini-worker",
        ) if self.executable_path else None

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        if self._subprocess_adapter and self._subprocess_adapter._resolve_executable():
            return self._subprocess_adapter.run(bundle)

        if not self.fallback_to_dummy:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="exec-failed",
                worker_instance_id="gemini-unavailable",
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                failure_classification="UNAVAILABLE",
                error_message="UNAVAILABLE: Gemini worker adapter executable not found or not configured; vendor adapter not implemented.",
            )

        dummy = TestDummyWorkerAdapter()
        res = dummy.run(bundle)
        res.adapter_id = self.adapter_id
        res.availability = "TEST_ONLY"
        res.test_only = True
        res.summary = f"[TEST-ONLY dummy fallback for {self.adapter_id}] {res.summary}"
        return res


class UnknownWorkerAdapter(AbstractWorkerAdapter):
    """
    Adapter returned when an unknown vendor adapter ID is requested.
    Fails closed on execution without silent fallback.
    """

    def __init__(self, adapter_id: str):
        self.adapter_id = adapter_id

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        return WorkerResult(
            success=False,
            role=bundle.role,
            execution_id="exec-failed",
            worker_instance_id="unknown",
            adapter_id=self.adapter_id,
            availability="UNAVAILABLE",
            failure_classification="UNAVAILABLE",
            error_message=f"UNAVAILABLE: Unknown worker adapter {self.adapter_id!r}: execution denied",
        )


class WorkerRegistry:
    def __init__(self, allow_dummy_fallback: bool = False):
        """
        Worker adapter registry.
        
        Args:
            allow_dummy_fallback: If True, vendor adapters fall back to dummy for testing.
                                 Default False for production safety.
        """
        self._adapters: dict[str, AbstractWorkerAdapter] = {}
        self.register(TestDummyWorkerAdapter())
        self.register(ManualWorkerAdapter())
        self.register(SubprocessWorkerAdapter())
        self.register(CursorWorkerAdapter(fallback_to_dummy=allow_dummy_fallback))
        self.register(ClaudeCodeWorkerAdapter(fallback_to_dummy=allow_dummy_fallback))
        self.register(GeminiWorkerAdapter(fallback_to_dummy=allow_dummy_fallback))

    def register(self, adapter: AbstractWorkerAdapter) -> None:
        self._adapters[adapter.adapter_id] = adapter

    def get(self, adapter_id: str) -> AbstractWorkerAdapter:
        if adapter_id not in self._adapters:
            return UnknownWorkerAdapter(adapter_id)
        return self._adapters[adapter_id]
