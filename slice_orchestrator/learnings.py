"""
Learning Ledger Model and Store for Method v4 Enhanced.
Persists informational technical discoveries under control home learnings/.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slice_orchestrator.canonical import compute_record_digest


@dataclass
class LearningRecord:
    learning_id: str
    source_work_item: str
    author_role: str
    statement: str
    confidence: float
    evidence_reference: str
    timestamp: str | None = None
    hash: str | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.hash:
            self.hash = self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "learning_id": self.learning_id,
            "source_work_item": self.source_work_item,
            "timestamp": self.timestamp,
            "author_role": self.author_role,
            "statement": self.statement,
            "confidence": self.confidence,
            "evidence_reference": self.evidence_reference,
        }

    def compute_hash(self) -> str:
        return compute_record_digest(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningRecord:
        return cls(
            learning_id=data.get("learning_id", str(uuid.uuid4())),
            source_work_item=data["source_work_item"],
            author_role=data.get("author_role", "UNKNOWN"),
            statement=data["statement"],
            confidence=data.get("confidence", 1.0),
            evidence_reference=data.get("evidence_reference", "0" * 64),
            timestamp=data.get("timestamp"),
            hash=data.get("hash"),
        )


class LearningLedger:
    """
    Manages informational immutable learning records under control home.
    NOTE: Learning records grant NO governance authority.
    """

    def __init__(self, control_store: Any):
        self.store = control_store
        self.learnings_dir = self.store.control_home / "learnings"
        self.learnings_dir.mkdir(parents=True, exist_ok=True)

    def record_learning(self, record: LearningRecord) -> str:
        data = record.to_dict()

        # Save to records DB & artifacts
        digest = self.store.store_record("LEARNING", record.learning_id, data)

        # Save copy under learnings/ directory
        file_path = self.learnings_dir / f"learning_{record.learning_id}.json"
        file_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

        # Save in SQLite learnings table
        with self.store._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO learnings (
                    learning_id, source_work_item, author_role, statement,
                    confidence, evidence_reference, created_at, hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learning_id) DO UPDATE SET
                    statement=excluded.statement,
                    confidence=excluded.confidence
                """,
                (
                    record.learning_id,
                    record.source_work_item,
                    record.author_role,
                    record.statement,
                    record.confidence,
                    record.evidence_reference,
                    record.timestamp,
                    digest,
                ),
            )
            conn.commit()

        return digest

    def list_learnings(self, source_work_item: str | None = None) -> list[LearningRecord]:
        with self.store._get_db_connection() as conn:
            if source_work_item:
                cur = conn.execute(
                    "SELECT * FROM learnings WHERE source_work_item = ? ORDER BY created_at ASC",
                    (source_work_item,),
                )
            else:
                cur = conn.execute("SELECT * FROM learnings ORDER BY created_at ASC")

            rows = cur.fetchall()
            results = []
            for row in rows:
                rec_dict = self.store.get_record(row["learning_id"])
                if rec_dict:
                    results.append(LearningRecord.from_dict(rec_dict))
                else:
                    results.append(
                        LearningRecord(
                            learning_id=row["learning_id"],
                            source_work_item=row["source_work_item"],
                            author_role=row["author_role"],
                            statement=row["statement"],
                            confidence=row["confidence"],
                            evidence_reference=row["evidence_reference"],
                            timestamp=row["created_at"],
                            hash=row["hash"],
                        )
                    )
            return results
