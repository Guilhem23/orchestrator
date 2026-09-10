"""
Artifact Graph Store and Traceability for Method v4 Enhanced.
Stores artifact relationships in SQLite control plane for end-to-end traceability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from slice_orchestrator.canonical import compute_record_digest


VALID_ARTIFACT_NODE_TYPES = {
    "requirement",
    "plan",
    "objective",
    "work_item",
    "source_change",
    "test",
    "benchmark",
    "evidence",
    "remediation",
    "review",
    "gate",
    "commit",
    "governance",
}


@dataclass
class ArtifactGraphNode:
    artifact_id: str
    type: str  # enum from VALID_ARTIFACT_NODE_TYPES
    parent_artifact_ids: list[str] = field(default_factory=list)
    run_id: str = ""
    work_item_id: str = ""
    revision: int = 0
    hash: str = ""
    creator_role: str = "CONTROLLER_SYSTEM"
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.type not in VALID_ARTIFACT_NODE_TYPES:
            raise ValueError(f"Invalid ArtifactGraphNode type: {self.type}")
        if not self.hash:
            self.hash = self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "artifact_id": self.artifact_id,
            "type": self.type,
            "parent_artifact_ids": self.parent_artifact_ids,
            "run_id": self.run_id,
            "work_item_id": self.work_item_id,
            "revision": self.revision,
            "hash": self.hash,
            "created_at": self.created_at,
            "creator_role": self.creator_role,
        }

    def compute_hash(self) -> str:
        data = {
            "schema_version": 4,
            "artifact_id": self.artifact_id,
            "type": self.type,
            "parent_artifact_ids": sorted(self.parent_artifact_ids),
            "run_id": self.run_id,
            "work_item_id": self.work_item_id,
            "revision": self.revision,
            "creator_role": self.creator_role,
        }
        return compute_record_digest(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactGraphNode:
        return cls(
            artifact_id=data["artifact_id"],
            type=data["type"],
            parent_artifact_ids=data.get("parent_artifact_ids", []),
            run_id=data.get("run_id", ""),
            work_item_id=data.get("work_item_id", ""),
            revision=data.get("revision", 0),
            hash=data.get("hash", ""),
            creator_role=data.get("creator_role", "CONTROLLER_SYSTEM"),
            created_at=data.get("created_at"),
        )


class ArtifactGraphStore:
    """
    SQLite-backed Artifact Graph store for traceability and audit queries.
    NOTE: Artifact Graph nodes provide auditability only; they do not act as governance authority.
    """

    def __init__(self, control_store: Any):
        self.store = control_store

    def add_node(self, node: ArtifactGraphNode) -> None:
        parents_json = json.dumps(node.parent_artifact_ids, sort_keys=True)
        with self.store._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO artifact_graph_nodes (
                    artifact_id, type, parent_artifact_ids_json, run_id,
                    work_item_id, revision, hash, created_at, creator_role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    type=excluded.type,
                    parent_artifact_ids_json=excluded.parent_artifact_ids_json,
                    revision=excluded.revision,
                    hash=excluded.hash
                """,
                (
                    node.artifact_id,
                    node.type,
                    parents_json,
                    node.run_id,
                    node.work_item_id,
                    node.revision,
                    node.hash,
                    node.created_at,
                    node.creator_role,
                ),
            )
            conn.commit()

        # Store JSON record artifact as well
        self.store.store_record("ARTIFACT_GRAPH_NODE", f"graph-node-{node.artifact_id}", node.to_dict())

    def get_node(self, artifact_id: str) -> ArtifactGraphNode | None:
        with self.store._get_db_connection() as conn:
            cur = conn.execute("SELECT * FROM artifact_graph_nodes WHERE artifact_id = ?", (artifact_id,))
            row = cur.fetchone()
            if not row:
                return None
            return ArtifactGraphNode(
                artifact_id=row["artifact_id"],
                type=row["type"],
                parent_artifact_ids=json.loads(row["parent_artifact_ids_json"]),
                run_id=row["run_id"],
                work_item_id=row["work_item_id"],
                revision=row["revision"],
                hash=row["hash"],
                creator_role=row["creator_role"],
                created_at=row["created_at"],
            )

    def trace_ancestors(self, artifact_id: str) -> list[ArtifactGraphNode]:
        """
        Recursively trace ancestor nodes up to root requirements.
        """
        visited: set[str] = set()
        result: list[ArtifactGraphNode] = []
        queue = [artifact_id]

        while queue:
            curr_id = queue.pop(0)
            if curr_id in visited:
                continue
            visited.add(curr_id)

            node = self.get_node(curr_id)
            if node:
                result.append(node)
                for pid in node.parent_artifact_ids:
                    if pid not in visited:
                        queue.append(pid)

        return result

    def get_unfulfilled_requirements(self, run_id: str) -> list[str]:
        """
        Find requirement nodes in run_id that do not have downstream satisfied work items or commits.
        """
        with self.store._get_db_connection() as conn:
            cur = conn.execute(
                "SELECT artifact_id FROM artifact_graph_nodes WHERE run_id = ? AND type = 'requirement'",
                (run_id,),
            )
            req_rows = cur.fetchall()
            all_req_ids = [row["artifact_id"] for row in req_rows]

            cur_nodes = conn.execute(
                "SELECT artifact_id, parent_artifact_ids_json FROM artifact_graph_nodes WHERE run_id = ? AND type IN ('commit', 'work_item')",
                (run_id,),
            )
            fulfilled_reqs: set[str] = set()
            for row in cur_nodes.fetchall():
                node_id = row["artifact_id"]
                ancestors = self.trace_ancestors(node_id)
                for anc in ancestors:
                    if anc.type == "requirement":
                        fulfilled_reqs.add(anc.artifact_id)

            return [req_id for req_id in all_req_ids if req_id not in fulfilled_reqs]
