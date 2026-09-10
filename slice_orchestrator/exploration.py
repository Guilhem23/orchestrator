"""
Exploration Mode for Method v4 Enhanced.
Runs investigation/prototyping in disposable scratch workspace.
Strict invariants: NO COMMIT, NO GOVERNANCE, NO PRODUCTION WORKSPACE WRITE.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slice_orchestrator.canonical import compute_record_digest
from slice_orchestrator.workers import WorkerInputBundle, WorkerRegistry


@dataclass
class ExplorationReport:
    schema_version: int = 4
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    exploration_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    slice: str = ""
    topic: str = ""
    scratch_workspace_path: str = ""
    findings: str = ""
    recommendation: str = ""
    evidence_references: list[str] = field(default_factory=list)
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "exploration_id": self.exploration_id,
            "run_id": self.run_id or str(uuid.uuid4()),
            "slice": self.slice,
            "topic": self.topic,
            "scratch_workspace_path": self.scratch_workspace_path,
            "findings": self.findings,
            "recommendation": self.recommendation,
            "evidence_references": self.evidence_references,
            "created_at": self.created_at,
        }


class ExplorationManager:
    """
    Manages Exploration Mode execution in isolated scratch directories.
    """

    def __init__(self, workspace_dir: Path, control_store: Any, worker_registry: WorkerRegistry | None = None):
        self.workspace_dir = workspace_dir.resolve()
        self.control_store = control_store
        self.worker_registry = worker_registry or WorkerRegistry()
        self.scratch_base = self.control_store.control_home / "scratch"
        self.scratch_base.mkdir(parents=True, exist_ok=True)

    def run_exploration(
        self,
        slice_name: str,
        topic: str,
        run_id: str | None = None,
        adapter_id: str = "dummy",
    ) -> ExplorationReport:
        exploration_id = str(uuid.uuid4())
        scratch_dir = self.scratch_base / f"exploration_{exploration_id[:8]}"
        scratch_dir.mkdir(parents=True, exist_ok=True)

        effective_run_id = run_id or str(uuid.uuid4())

        # Copy minimal read-only files if needed, or work entirely in scratch
        (scratch_dir / "README.md").write_text(f"# Exploration Scratch for Topic: {topic}\n")

        adapter = self.worker_registry.get(adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=str(uuid.uuid4()),
            run_id=effective_run_id,
            slice=slice_name,
            role="EXPLORER",
            prompt=f"Investigate topic: {topic}",
            base_commit_oid="sha1:0000000000000000000000000000000000000000",
            workspace_dir=scratch_dir,  # Isolated scratch workspace!
            output_dir=self.control_store.artifacts_dir,
        )

        result = adapter.run(bundle)

        findings = result.summary or f"Exploration of topic {topic} completed successfully."
        recommendation = f"Proceed with bounded Work Items for topic {topic} based on findings."

        report = ExplorationReport(
            exploration_id=exploration_id,
            run_id=effective_run_id,
            slice=slice_name,
            topic=topic,
            scratch_workspace_path=str(scratch_dir),
            findings=findings,
            recommendation=recommendation,
            evidence_references=[],
        )

        # Persist report record in control store
        self.control_store.store_record("EXPLORATION_REPORT", report.report_id, report.to_dict())
        return report
