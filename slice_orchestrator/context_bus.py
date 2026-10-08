"""
Enterprise Shared Context Bus for Slice Orchestrator (v0.5).
Synchronizes agent memories, active slice locks, and architectural decisions
across engineering teams to eliminate duplicate work and cross-agent hallucination.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("slice_orchestrator.context_bus")


@dataclass
class SharedMemoryEntry:
    entry_id: str
    category: str  # "decision", "pattern", "scope_lock", "warning"
    author_agent: str
    slice: str
    target_paths: list[str]
    payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConflictWarning:
    slice: str
    conflicting_slice: str
    author_agent: str
    overlapping_paths: list[str]
    warning_type: str  # "CONCURRENT_SCOPE_COLLISION", "CONTRADICTORY_DECISION"
    message: str


class SharedContextBus:
    """
    Enterprise coordination bus backed by shared SQLite database or network socket.
    Maintains cross-agent memories and path contention locks.
    """

    def __init__(self, bus_path: Path):
        self.bus_path = Path(bus_path).resolve()
        self.bus_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.bus_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shared_memories (
                    entry_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    author_agent TEXT NOT NULL,
                    slice TEXT NOT NULL,
                    target_paths TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def broadcast_memory(self, entry: SharedMemoryEntry) -> None:
        """Broadcast a memory, architectural decision, or path lock to the bus."""
        with sqlite3.connect(self.bus_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO shared_memories
                (entry_id, category, author_agent, slice, target_paths, payload, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.category,
                    entry.author_agent,
                    entry.slice,
                    json.dumps(entry.target_paths),
                    json.dumps(entry.payload),
                    entry.timestamp,
                ),
            )
            conn.commit()

    def query_memories(
        self,
        category: str | None = None,
        slice_name: str | None = None,
    ) -> list[SharedMemoryEntry]:
        """Query broadcast memories matching criteria."""
        query = "SELECT entry_id, category, author_agent, slice, target_paths, payload, timestamp FROM shared_memories WHERE 1=1"
        params: list[Any] = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if slice_name:
            query += " AND slice = ?"
            params.append(slice_name)
        query += " ORDER BY timestamp DESC"

        with sqlite3.connect(self.bus_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        entries: list[SharedMemoryEntry] = []
        for row in rows:
            entries.append(
                SharedMemoryEntry(
                    entry_id=row[0],
                    category=row[1],
                    author_agent=row[2],
                    slice=row[3],
                    target_paths=json.loads(row[4]),
                    payload=json.loads(row[5]),
                    timestamp=row[6],
                )
            )
        return entries

    def detect_scope_contention(
        self,
        current_slice: str,
        current_agent: str,
        proposed_paths: list[str],
    ) -> list[ConflictWarning]:
        """
        Check for concurrent slices touching overlapping files.
        """
        warnings: list[ConflictWarning] = []
        active_entries = self.query_memories(category="scope_lock")

        for entry in active_entries:
            if entry.slice == current_slice:
                continue

            overlaps = [p for p in proposed_paths if p in entry.target_paths]
            if overlaps:
                warnings.append(
                    ConflictWarning(
                        slice=current_slice,
                        conflicting_slice=entry.slice,
                        author_agent=entry.author_agent,
                        overlapping_paths=overlaps,
                        warning_type="CONCURRENT_SCOPE_COLLISION",
                        message=(
                            f"Slice '{current_slice}' touches {overlaps} which is actively claimed "
                            f"by slice '{entry.slice}' (agent '{entry.author_agent}')"
                        ),
                    )
                )

        return warnings
