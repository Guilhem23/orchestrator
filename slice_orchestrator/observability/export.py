"""Versioned immutable run export (JSON + Markdown)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slice_orchestrator.canonical import compute_record_digest
from slice_orchestrator.observability.metrics import MetricsEngine
from slice_orchestrator.observability.redaction import redact_value
from slice_orchestrator.observability.timeline import build_timeline

EXPORT_SCHEMA_VERSION = "run-export-v1"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _export_root(control_home: Path) -> Path:
    root = Path(control_home) / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_export_payload(controller: Any, slice_name: str) -> dict[str, Any]:
    store = controller.store
    state = controller.get_slice_state(slice_name)
    if not state:
        raise ValueError(f"No run found for slice {slice_name}")

    events = [e for e in store.verify_store_integrity() if e.get("slice") == slice_name]
    events = sorted(events, key=lambda e: e.get("sequence", 0))
    timeline = build_timeline(events, control_store=store)
    metrics = MetricsEngine(store).compute_for_slice(slice_name, run_id=state.run_id)

    objectives = []
    for obj in store.list_objectives(run_id=state.run_id, slice_name=slice_name):
        objectives.append(obj.to_dict() if hasattr(obj, "to_dict") else obj)

    work_items = []
    for wi in store.list_work_items(run_id=state.run_id, slice_name=slice_name):
        work_items.append(wi.to_dict() if hasattr(wi, "to_dict") else wi)

    plans = [p for p in store.list_records_by_type("PLAN") if p.get("slice") == slice_name or p.get("run_id") == state.run_id]
    assignments = []
    if hasattr(store, "list_assignments"):
        try:
            assignments = store.list_assignments(run_id=state.run_id)
        except Exception:
            assignments = []

    receipts = store.list_receipts(slice_name=slice_name, run_id=state.run_id)
    reviews = [
        r for r in store.list_records_by_type("REVIEW") + store.list_records_by_type("ARCHITECTURE_REVIEW")
        if r.get("slice") == slice_name or r.get("run_id") == state.run_id
    ]
    remediations = [
        r for r in store.list_records_by_type("REMEDIATION_PACKET")
        if r.get("slice") == slice_name or r.get("run_id") == state.run_id
    ]
    clarifications = [
        r for r in store.list_records_by_type("REQUIREMENT_CLARIFICATION")
        if r.get("slice") == slice_name or r.get("run_id") == state.run_id
    ]

    errors = [
        {
            "sequence": e.get("sequence"),
            "event_type": e.get("event_type"),
            "error_code": (e.get("payload") or {}).get("stop_reason_code")
            or (e.get("payload") or {}).get("failure_code"),
            "recorded_at": e.get("recorded_at"),
        }
        for e in events
        if e.get("event_type") in ("RUN_STOPPED", "COMMIT_FAILED_RECOVERABLE")
        or (isinstance(e.get("payload"), dict) and e["payload"].get("stop_reason_code"))
    ]

    worker_execs = [
        {
            "sequence": e.get("sequence"),
            "event_type": e.get("event_type"),
            "assignment_id": (e.get("actor") or {}).get("assignment_id")
            or (e.get("payload") or {}).get("assignment_id"),
            "role": (e.get("actor") or {}).get("role"),
            "recorded_at": e.get("recorded_at"),
        }
        for e in events
        if e.get("event_type") in (
            "ASSIGNMENT_ISSUED",
            "ASSIGNMENT_CONSUMED",
            "IMPLEMENTATION_ASSIGNED",
            "IMPLEMENTATION_WORKER_REASSIGNED",
        )
    ]

    integrity = {
        "event_count": len(events),
        "first_event_hash": events[0].get("event_hash") if events else None,
        "last_event_hash": events[-1].get("event_hash") if events else None,
        "stream_tail_hash": state.stream_tail_hash,
        "source_digest": metrics.get("source_digest"),
    }

    objective_text = None
    if objectives:
        objective_text = objectives[0].get("description") if isinstance(objectives[0], dict) else getattr(objectives[0], "description", None)

    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slice": slice_name,
        "run_id": state.run_id,
        "objective": objective_text,
        "requirements": clarifications,
        "plan": plans,
        "work_items": work_items,
        "assignments": assignments,
        "event_timeline": timeline,
        "events": events,
        "worker_executions": worker_execs,
        "tests": receipts,
        "reviews": reviews,
        "remediations": remediations,
        "gates": {
            "note": "Gate evaluation is read-only at runtime; finalize evidence via COMMIT/GOVERNANCE events",
            "commit_ready": state.state in ("COMMIT_READY", "COMPLETE"),
            "approved_revision_digest": state.approved_revision_digest,
            "workspace_revision_digest": state.workspace_revision_digest,
            "evidence_set_digest": state.evidence_set_digest,
        },
        "errors": errors,
        "metrics": metrics,
        "evidence_references": {
            "control_home": str(store.control_home),
            "database": str(store.db_path),
            "records": str(store.control_home / "records"),
        },
        "final_state": state.state,
        "integrity": integrity,
        "limitations": [
            "Export is a point-in-time observational snapshot.",
            "Secrets and full prompts are redacted.",
            "Worker summaries are not authoritative metrics.",
            "Host process restarts are not inferred as causality.",
        ],
    }
    redacted = redact_value(payload)
    # Integrity digest over redacted content excluding the digest field itself
    redacted["integrity"] = dict(redacted.get("integrity") or {})
    redacted["integrity"]["export_digest"] = compute_record_digest(
        {k: v for k, v in redacted.items() if k != "integrity"}
    )
    return redacted


def export_run(
    controller: Any,
    slice_name: str,
    *,
    fmt: str = "json",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Write a versioned immutable export. Never overwrites prior export directories.
    """
    store = controller.store
    payload = build_export_payload(controller, slice_name)
    stamp = _utc_stamp()
    root = Path(output_dir) if output_dir else _export_root(store.control_home)
    dest = root / slice_name / stamp
    if dest.exists():
        # Immutable: bump with counter rather than overwrite
        n = 1
        while (root / slice_name / f"{stamp}-{n}").exists():
            n += 1
        dest = root / slice_name / f"{stamp}-{n}"
    dest.mkdir(parents=True, exist_ok=False)

    json_path = dest / "run-export.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = {
        "slice": slice_name,
        "format": fmt,
        "directory": str(dest),
        "json_path": str(json_path),
        "export_digest": payload.get("integrity", {}).get("export_digest"),
        "schema_version": EXPORT_SCHEMA_VERSION,
    }

    if fmt == "markdown":
        md_path = dest / "run-export.md"
        md_path.write_text(_to_markdown(payload), encoding="utf-8")
        result["markdown_path"] = str(md_path)
    elif fmt != "json":
        raise ValueError(f"Unsupported export format: {fmt}")

    # Marker to discourage accidental mutation tooling
    (dest / "IMMUTABLE.txt").write_text(
        "This export directory is immutable. Do not overwrite. Create a new timestamped export instead.\n",
        encoding="utf-8",
    )
    return result


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Slice Run Export — {payload.get('slice')}",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Run ID: `{payload.get('run_id')}`",
        f"- Final state: `{payload.get('final_state')}`",
        f"- Exported at: `{payload.get('exported_at')}`",
        f"- Export digest: `{payload.get('integrity', {}).get('export_digest')}`",
        "",
        "## Objective",
        "",
        str(payload.get("objective") or "(none)"),
        "",
        "## Timeline summary",
        "",
        f"- Events: {payload.get('event_timeline', {}).get('event_count')}",
        f"- Outcome: {payload.get('event_timeline', {}).get('terminal_outcome')}",
        f"- Elapsed ms: {payload.get('event_timeline', {}).get('total_elapsed_ms')}",
        "",
        "## Metrics (with provenance status)",
        "",
    ]
    metrics = (payload.get("metrics") or {}).get("metrics") or {}
    for name, meta in sorted(metrics.items()):
        lines.append(f"- **{name}**: `{meta.get('value')}` ({meta.get('status')})")
    lines.extend(["", "## Limitations", ""])
    for lim in payload.get("limitations") or []:
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)
