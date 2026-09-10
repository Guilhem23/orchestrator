"""
Worker Protocol (slice-worker-v1) and Worker Backend Adapters.
"""

from __future__ import annotations

import hashlib
import json
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
    objective: dict[str, Any] | None = None
    work_item: dict[str, Any] | None = None
    learnings: list[dict[str, Any]] = field(default_factory=list)


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

    def __init__(self, fallback_to_dummy: bool = False):
        """
        Cursor worker adapter.
        
        WARNING: Real Cursor integration not implemented. 
        Set fallback_to_dummy=True EXPLICITLY for testing only.
        """
        self.fallback_to_dummy = fallback_to_dummy

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        if not self.fallback_to_dummy:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="exec-failed",
                worker_instance_id="cursor-unavailable",
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                error_message="UNAVAILABLE: Cursor worker adapter not implemented. Set fallback_to_dummy=True explicitly for testing only.",
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

    def __init__(self, fallback_to_dummy: bool = False):
        """
        Claude Code worker adapter.
        
        WARNING: Real Claude Code integration not implemented.
        Set fallback_to_dummy=True EXPLICITLY for testing only.
        """
        self.fallback_to_dummy = fallback_to_dummy

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        if not self.fallback_to_dummy:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="exec-failed",
                worker_instance_id="claude-unavailable",
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                error_message="UNAVAILABLE: Claude Code worker adapter not implemented. Set fallback_to_dummy=True explicitly for testing only.",
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

    def __init__(self, fallback_to_dummy: bool = False):
        """
        Gemini worker adapter.
        
        WARNING: Real Gemini integration not implemented.
        Set fallback_to_dummy=True EXPLICITLY for testing only.
        """
        self.fallback_to_dummy = fallback_to_dummy

    def run(self, bundle: WorkerInputBundle) -> WorkerResult:
        if not self.fallback_to_dummy:
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="exec-failed",
                worker_instance_id="gemini-unavailable",
                adapter_id=self.adapter_id,
                availability="UNAVAILABLE",
                error_message="UNAVAILABLE: Gemini worker adapter not implemented. Set fallback_to_dummy=True explicitly for testing only.",
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
        self.register(CursorWorkerAdapter(fallback_to_dummy=allow_dummy_fallback))
        self.register(ClaudeCodeWorkerAdapter(fallback_to_dummy=allow_dummy_fallback))
        self.register(GeminiWorkerAdapter(fallback_to_dummy=allow_dummy_fallback))

    def register(self, adapter: AbstractWorkerAdapter) -> None:
        self._adapters[adapter.adapter_id] = adapter

    def get(self, adapter_id: str) -> AbstractWorkerAdapter:
        if adapter_id not in self._adapters:
            return UnknownWorkerAdapter(adapter_id)
        return self._adapters[adapter_id]
