"""Structured operational logging (JSON Lines + human-readable).

Logs correlate with persisted control-plane events but are never authoritative.
Logging failures must not create false success for control operations.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from slice_orchestrator.canonical import compute_record_digest
from slice_orchestrator.observability.redaction import redact_value


class LoggingError(RuntimeError):
    """Raised when structured logging fails; callers must not treat as success."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OperationalLogger:
    """Append-only JSONL + optional human summary log under control home."""

    def __init__(self, control_home: Path, *, run_id: str | None = None):
        self.control_home = Path(control_home)
        self.logs_dir = self.control_home / "logs"
        self.run_id = run_id
        self._lock = threading.Lock()
        self._jsonl_path = self.logs_dir / "operational.jsonl"
        self._human_path = self.logs_dir / "operational.txt"

    def ensure_dirs(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        event_type: str,
        run_id: str | None = None,
        slice_id: str | None = None,
        actor: str | None = None,
        state_before: str | None = None,
        state_after: str | None = None,
        duration_ms: int | None = None,
        result: str | None = None,
        error_code: str | None = None,
        severity: str = "info",
        phase: str | None = None,
        sequence: int | None = None,
        event_hash: str | None = None,
        extras: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": timestamp or _utc_now(),
            "run_id": run_id or self.run_id,
            "slice_id": slice_id,
            "event_type": event_type,
            "actor": actor,
            "state_before": state_before,
            "state_after": state_after,
            "duration_ms": duration_ms,
            "result": result,
            "error_code": error_code,
            "severity": severity,
            "phase": phase,
            "sequence": sequence,
            "event_hash": event_hash,
        }
        if extras:
            entry["extras"] = redact_value(extras)
        entry = redact_value(entry)
        try:
            self.ensure_dirs()
            line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            human = (
                f"{entry['timestamp']} [{entry.get('severity')}] "
                f"slice={entry.get('slice_id')} run={entry.get('run_id')} "
                f"seq={entry.get('sequence')} {entry.get('event_type')} "
                f"{entry.get('state_before')}->{entry.get('state_after')} "
                f"result={entry.get('result')} error={entry.get('error_code')} "
                f"duration_ms={entry.get('duration_ms')}"
            )
            with self._lock:
                with open(self._jsonl_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                    fh.flush()
                with open(self._human_path, "a", encoding="utf-8") as fh:
                    fh.write(human + "\n")
                    fh.flush()
        except OSError as exc:
            raise LoggingError(f"Failed to write operational log: {exc}") from exc
        return entry

    def emit_from_event(
        self,
        event: dict[str, Any],
        *,
        state_before: str | None = None,
        state_after: str | None = None,
        duration_ms: int | None = None,
        severity: str | None = None,
    ) -> dict[str, Any]:
        from slice_orchestrator.observability.model import project_observable_event

        view = project_observable_event(
            event,
            state_before=state_before,
            state_after=state_after,
            duration_ms=duration_ms,
        )
        sev = severity or ("error" if view.error_code else "info")
        return self.emit(
            event_type=view.event_name,
            run_id=view.run_id,
            slice_id=view.slice_id,
            actor=view.actor,
            state_before=view.state_before,
            state_after=view.state_after,
            duration_ms=view.duration_ms,
            result=view.result,
            error_code=view.error_code,
            severity=sev,
            phase=view.phase,
            sequence=view.sequence,
            event_hash=view.event_hash,
            timestamp=view.timestamp,
            extras={"work_item_id": view.work_item_id, "assignment_id": view.assignment_id},
        )

    def read_entries(
        self,
        *,
        run_id: str | None = None,
        slice_id: str | None = None,
        phase: str | None = None,
        severity: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._jsonl_path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id is not None and item.get("run_id") != run_id:
                continue
            if slice_id is not None and item.get("slice_id") != slice_id:
                continue
            if phase is not None and item.get("phase") != phase:
                continue
            if severity is not None and item.get("severity") != severity:
                continue
            ts = item.get("timestamp")
            if since and (not ts or ts < since):
                continue
            if until and (not ts or ts > until):
                continue
            entries.append(item)
        return entries


def correlate_logs_with_events(
    log_entries: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Correlate log lines to persisted events by sequence and/or event_hash."""
    events_by_seq = {e.get("sequence"): e for e in events if e.get("sequence") is not None}
    events_by_hash = {e.get("event_hash"): e for e in events if e.get("event_hash")}
    matched = 0
    unmatched: list[dict[str, Any]] = []
    for entry in log_entries:
        seq = entry.get("sequence")
        eh = entry.get("event_hash")
        if (seq is not None and seq in events_by_seq) or (eh and eh in events_by_hash):
            matched += 1
        else:
            unmatched.append({"sequence": seq, "event_hash": eh, "event_type": entry.get("event_type")})
    payload = {
        "matched": matched,
        "unmatched_count": len(unmatched),
        "unmatched": unmatched[:50],
    }
    payload["correlation_digest"] = compute_record_digest(payload)
    return payload
