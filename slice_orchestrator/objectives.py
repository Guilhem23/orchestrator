"""
Objective Model and Persistence for Method v4 Enhanced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from slice_orchestrator.canonical import compute_record_digest


@dataclass
class Objective:
    objective_id: str
    run_id: str
    slice: str
    description: str
    source_requirements: list[str]
    acceptance_predicates: list[dict[str, Any]]
    dependencies: list[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING, IN_PROGRESS, SATISFIED, FAILED
    plan_revision: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    hash: str | None = None

    def __post_init__(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = now_iso
        if not self.hash:
            self.hash = self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "objective_id": self.objective_id,
            "run_id": self.run_id,
            "slice": self.slice,
            "description": self.description,
            "source_requirements": self.source_requirements,
            "acceptance_predicates": self.acceptance_predicates,
            "dependencies": self.dependencies,
            "status": self.status,
            "plan_revision": self.plan_revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.plan_revision,
        }

    def compute_hash(self) -> str:
        return compute_record_digest(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Objective:
        return cls(
            objective_id=data["objective_id"],
            run_id=data.get("run_id", ""),
            slice=data["slice"],
            description=data["description"],
            source_requirements=data.get("source_requirements", []),
            acceptance_predicates=data.get("acceptance_predicates", []),
            dependencies=data.get("dependencies", []),
            status=data.get("status", "PENDING"),
            plan_revision=data.get("plan_revision", data.get("revision", 0)),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            hash=data.get("hash"),
        )
