"""
Work Item Model and DAG Supervisor for Method v4 Enhanced.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from slice_orchestrator.canonical import compute_record_digest


VALID_WORK_ITEM_TYPES = {
    "analysis",
    "implementation",
    "test",
    "remediation",
    "review-support",
    "exploration",
}

VALID_WORK_ITEM_STATUSES = {
    "PENDING",
    "READY",
    "IN_PROGRESS",
    "CONVERGENCE_CHECK",
    "SATISFIED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
}


@dataclass
class WorkItem:
    work_item_id: str
    run_id: str
    objective_id: str
    description: str
    type: str  # analysis, implementation, test, remediation, review-support, exploration
    dependencies: list[str] = field(default_factory=list)
    allowed_scope: list[str] = field(default_factory=list)
    assigned_role: str = "IMPLEMENTER"
    worker_execution_id: str = ""
    status: str = "PENDING"  # PENDING, READY, IN_PROGRESS, CONVERGENCE_CHECK, SATISFIED, BLOCKED, FAILED, CANCELLED
    attempt_count: int = 0
    worker_execution_ids: list[str] = field(default_factory=list)
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    acceptance_predicates: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    hash: str | None = None

    def __post_init__(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = now_iso
        if self.type not in VALID_WORK_ITEM_TYPES:
            raise ValueError(f"Invalid WorkItem type: {self.type}")
        if self.status not in VALID_WORK_ITEM_STATUSES:
            raise ValueError(f"Invalid WorkItem status: {self.status}")
        if not self.worker_execution_ids and self.worker_execution_id:
            self.worker_execution_ids = [self.worker_execution_id]
        if not self.hash:
            self.hash = self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "work_item_id": self.work_item_id,
            "run_id": self.run_id,
            "objective_id": self.objective_id,
            "description": self.description,
            "type": self.type,
            "dependencies": self.dependencies,
            "allowed_scope": self.allowed_scope,
            "assigned_role": self.assigned_role,
            "worker_execution_id": self.worker_execution_id,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "worker_execution_ids": self.worker_execution_ids,
            "input_artifacts": self.input_artifacts,
            "output_artifacts": self.output_artifacts,
            "acceptance_predicates": self.acceptance_predicates,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def compute_hash(self) -> str:
        return compute_record_digest(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkItem:
        return cls(
            work_item_id=data["work_item_id"],
            run_id=data.get("run_id", ""),
            objective_id=data.get("objective_id", ""),
            description=data["description"],
            type=data["type"],
            dependencies=data.get("dependencies", []),
            allowed_scope=data.get("allowed_scope", []),
            assigned_role=data.get("assigned_role", "IMPLEMENTER"),
            worker_execution_id=data.get("worker_execution_id", ""),
            status=data.get("status", "PENDING"),
            attempt_count=data.get("attempt_count", 0),
            worker_execution_ids=data.get("worker_execution_ids", []),
            input_artifacts=data.get("input_artifacts", []),
            output_artifacts=data.get("output_artifacts", []),
            acceptance_predicates=data.get("acceptance_predicates", []),
            revision=data.get("revision", 0),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            hash=data.get("hash"),
        )


class WorkItemDAGSupervisor:
    """
    Supervisor for Work Item Directed Acyclic Graphs (DAG).
    Provides topological validation, cycle detection (Kahn's algorithm),
    and readiness derivation.
    """

    def validate_dag_acyclic(self, work_items: list[WorkItem]) -> None:
        valid, err = self.validate_dag(work_items)
        if not valid:
            raise ValueError(f"DAG validation failed: {err}")

    def validate_dag(self, work_items: list[WorkItem]) -> tuple[bool, str | None]:
        """
        Validate DAG for missing dependencies and cycles.
        """
        item_map = {item.work_item_id: item for item in work_items}

        # 1. Reject missing dependencies
        for item in work_items:
            for dep in item.dependencies:
                if dep not in item_map:
                    return False, f"WorkItem {item.work_item_id} has unknown dependency {dep!r}"

        # 2. Cycle detection using Kahn's algorithm
        in_degree = {item.work_item_id: 0 for item in work_items}
        graph: dict[str, list[str]] = {item.work_item_id: [] for item in work_items}

        for item in work_items:
            for dep in item.dependencies:
                graph[dep].append(item.work_item_id)
                in_degree[item.work_item_id] += 1

        queue = deque([node_id for node_id, deg in in_degree.items() if deg == 0])
        visited_count = 0

        while queue:
            node_id = queue.popleft()
            visited_count += 1
            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(work_items):
            return False, "Cycle detected in WorkItem dependencies"

        return True, None

    def topological_sort(self, work_items: list[WorkItem]) -> list[WorkItem]:
        valid, err = self.validate_dag(work_items)
        if not valid:
            raise ValueError(f"Cannot sort invalid DAG: {err}")

        item_map = {item.work_item_id: item for item in work_items}
        in_degree = {item.work_item_id: len(item.dependencies) for item in work_items}
        graph: dict[str, list[str]] = {item.work_item_id: [] for item in work_items}

        for item in work_items:
            for dep in item.dependencies:
                graph[dep].append(item.work_item_id)

        queue = deque([node_id for node_id, deg in in_degree.items() if deg == 0])
        result: list[WorkItem] = []

        while queue:
            node_id = queue.popleft()
            result.append(item_map[node_id])
            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def derive_readiness(self, work_items: list[WorkItem]) -> list[WorkItem]:
        """
        Derive READY status for PENDING work items whose parent dependencies are all SATISFIED.
        Does NOT alter non-PENDING work items.
        """
        item_map = {item.work_item_id: item for item in work_items}
        updated_items: list[WorkItem] = []

        for item in work_items:
            if item.status == "PENDING":
                all_deps_satisfied = True
                for dep in item.dependencies:
                    parent = item_map.get(dep)
                    if not parent or parent.status != "SATISFIED":
                        all_deps_satisfied = False
                        break

                if all_deps_satisfied:
                    item.status = "READY"
                    item.updated_at = datetime.now(timezone.utc).isoformat()
            updated_items.append(item)

        return updated_items

    def get_next_ready_work_item(self, work_items: list[WorkItem]) -> WorkItem | None:
        """
        Return the next READY item for sequential execution according to topological order.
        """
        updated = self.derive_readiness(work_items)
        sorted_items = self.topological_sort(updated)
        for item in sorted_items:
            if item.status == "READY":
                return item
        return None
