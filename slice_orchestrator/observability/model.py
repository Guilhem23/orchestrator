"""
Observability event model.

Maps control-plane events and records to observable concepts without
introducing redundant authoritative events.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Observable concept → existing control-plane sources (events and/or records).
# Do not invent parallel authoritative event types when these already cover the need.
OBSERVABLE_CONCEPT_SOURCES: dict[str, dict[str, Any]] = {
    "run_creation": {"events": ["RUN_OPENED"], "records": []},
    "requirement_clarification": {
        "events": [],
        "records": ["REQUIREMENT_CLARIFICATION"],
        "note": "Persisted via slice_grill clarification records, not a transition event",
    },
    "question_creation": {
        "events": [],
        "records": ["DECISION_REQUIRED", "REQUIREMENT_CLARIFICATION"],
        "note": "HumanDecisionManager may raise questions; grill stores clarification records",
    },
    "human_answer": {
        "events": [],
        "records": ["DECISION_ANSWER", "REQUIREMENT_CLARIFICATION"],
    },
    "context_creation": {"events": ["CONTEXT_PACK_GENERATED"], "records": ["CONTEXT_PACK"]},
    "plan_creation": {"events": ["PLAN_PERSISTED"], "records": ["PLAN"]},
    "plan_revision": {"events": ["PLAN_REVISED", "PLAN_REVISION_REQUESTED"], "records": ["PLAN"]},
    "work_item_creation": {
        "events": ["PLAN_PERSISTED", "PLAN_REVISED"],
        "records": ["WORK_ITEM"],
        "note": "Work items are records created alongside plan persistence",
    },
    "work_item_dispatch": {
        "events": [
            "ASSIGNMENT_ISSUED",
            "IMPLEMENTATION_ASSIGNED",
            "ARCHITECTURE_REVIEW_ASSIGNED",
            "ADVERSARIAL_REVIEW_ASSIGNED",
            "REMEDIATION_ASSIGNED",
        ],
        "records": [],
    },
    "worker_start": {
        "events": [
            "ASSIGNMENT_ISSUED",
            "IMPLEMENTATION_ASSIGNED",
            "ARCHITECTURE_REVIEW_ASSIGNED",
            "ADVERSARIAL_REVIEW_ASSIGNED",
            "REMEDIATION_ASSIGNED",
        ],
        "records": [],
    },
    "worker_completion": {"events": ["ASSIGNMENT_CONSUMED", "CANDIDATE_CAPTURED"], "records": []},
    "worker_failure": {
        "events": ["RUN_STOPPED"],
        "payload_codes": ["WORKER_FAILED", "WORKER_UNAVAILABLE", "IMPLEMENTATION_FAILED", "MALFORMED_WORKER_OUTPUT"],
        "records": [],
    },
    "worker_replacement": {"events": ["IMPLEMENTATION_WORKER_REASSIGNED"], "records": []},
    "result_recording": {
        "events": [
            "ASSIGNMENT_CONSUMED",
            "CANDIDATE_CAPTURED",
            "ARCHITECTURE_APPROVED",
            "ARCHITECTURE_BLOCKED",
            "REVIEW_ACCEPTED",
            "REVIEW_BLOCKED",
        ],
        "records": [],
    },
    "test_start": {
        "events": [],
        "records": ["TEST_RECEIPT"],
        "fields": ["started_at"],
        "note": "Derived from independently signed TEST_RECEIPT records",
    },
    "test_completion": {
        "events": [],
        "records": ["TEST_RECEIPT"],
        "fields": ["completed_at", "passed", "exit_code"],
    },
    "review_start": {"events": ["ADVERSARIAL_REVIEW_ASSIGNED", "ARCHITECTURE_REVIEW_ASSIGNED"], "records": []},
    "review_completion": {
        "events": ["REVIEW_ACCEPTED", "REVIEW_BLOCKED", "ARCHITECTURE_APPROVED", "ARCHITECTURE_BLOCKED"],
        "records": ["REVIEW", "ARCHITECTURE_REVIEW"],
    },
    "remediation": {"events": ["REMEDIATION_ASSIGNED", "REVIEW_BLOCKED"], "records": ["REMEDIATION_PACKET"]},
    "gate_evaluation": {
        "events": [],
        "records": [],
        "note": "slice_gate is read-only evaluation; evidence appears via COMMIT_RECORDED / gate digests on finalize",
    },
    "finalization": {
        "events": ["COMMIT_RECORDED", "GOVERNANCE_STARTED", "GOVERNANCE_COMMIT_RECORDED", "GOVERNANCE_RECONCILED"],
        "records": ["COMMIT", "GOVERNANCE"],
    },
    "run_completion": {"events": ["GOVERNANCE_RECONCILED"], "terminal_states": ["COMPLETE"]},
    "run_failure": {
        "events": ["RUN_STOPPED", "COMMIT_FAILED_RECOVERABLE"],
        "terminal_states": ["FAILED", "STOPPED"],
    },
    "restart": {
        "events": ["RUN_PAUSED", "RUN_RESUMED", "HUMAN_RECOVERY_OPENED"],
        "note": "Process/MCP/Cursor restarts are inferred from recovery evidence + gaps, not host heartbeats",
    },
    "recovery": {"events": ["HUMAN_RECOVERY_OPENED", "RUN_RESUMED"], "records": ["RECOVERY"]},
    "cancellation": {"events": ["RUN_STOPPED"], "records": []},
}

PHASE_BY_STATE: dict[str, str] = {
    "UNINITIALIZED": "init",
    "PLANNING": "planning",
    "PLAN_READY": "planning",
    "PLAN_REVISION": "planning",
    "ARCHITECTURE_REVIEW": "architecture_review",
    "ARCHITECTURE_APPROVED": "architecture_review",
    "IMPLEMENTATION": "implementation",
    "IMPLEMENTATION_READY_FOR_REVIEW": "implementation",
    "ADVERSARIAL_REVIEW": "review",
    "REMEDIATION": "remediation",
    "COMMIT_READY": "finalization",
    "COMMITTED": "finalization",
    "GOVERNANCE_RECONCILIATION": "finalization",
    "COMPLETE": "complete",
    "STOPPED": "stopped",
    "FAILED": "failed",
}

EVENT_TO_PHASE: dict[str, str] = {
    "RUN_OPENED": "planning",
    "PLAN_PERSISTED": "planning",
    "PLAN_REVISED": "planning",
    "PLAN_REVISION_REQUESTED": "planning",
    "ARCHITECTURE_REVIEW_ASSIGNED": "architecture_review",
    "ARCHITECTURE_APPROVED": "architecture_review",
    "ARCHITECTURE_BLOCKED": "planning",
    "IMPLEMENTATION_ASSIGNED": "implementation",
    "IMPLEMENTATION_CONTEXT_CHECKPOINTED": "implementation",
    "IMPLEMENTATION_WORKER_REASSIGNED": "implementation",
    "CANDIDATE_CAPTURED": "implementation",
    "CANDIDATE_INVALIDATED": "implementation",
    "ADVERSARIAL_REVIEW_ASSIGNED": "review",
    "REVIEW_ACCEPTED": "finalization",
    "REVIEW_BLOCKED": "remediation",
    "REMEDIATION_ASSIGNED": "remediation",
    "COMMIT_RECORDED": "finalization",
    "GOVERNANCE_STARTED": "finalization",
    "GOVERNANCE_COMMIT_RECORDED": "finalization",
    "GOVERNANCE_RECONCILED": "complete",
    "RUN_STOPPED": "stopped",
    "RUN_PAUSED": "paused",
    "RUN_RESUMED": "resumed",
    "HUMAN_RECOVERY_OPENED": "recovery",
    "ASSIGNMENT_ISSUED": "assignment",
    "ASSIGNMENT_CONSUMED": "assignment",
    "CONTEXT_PACK_GENERATED": "context",
}


@dataclass
class ObservableEventView:
    """Normalized observational view over a persisted control-plane event."""

    event_name: str
    source: str
    timestamp: str | None
    run_id: str | None
    slice_id: str | None
    work_item_id: str | None
    assignment_id: str | None
    actor: str | None
    host: str | None
    state_before: str | None
    state_after: str | None
    duration_ms: int | None
    result: str | None
    error_code: str | None
    revision: int | None
    tree_digest: str | None
    workspace_digest: str | None
    sequence: int | None = None
    phase: str | None = None
    event_hash: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_get(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    rec = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    for key in keys:
        if key in rec and rec[key] is not None:
            return rec[key]
    return None


def project_observable_event(
    event: dict[str, Any],
    *,
    state_before: str | None = None,
    state_after: str | None = None,
    duration_ms: int | None = None,
) -> ObservableEventView:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
    host = payload.get("host_metadata") or payload.get("host")
    error_code = (
        payload.get("stop_reason_code")
        or payload.get("failure_code")
        or payload.get("error_code")
        or payload.get("reason_code")
    )
    result = payload.get("result") or payload.get("verdict") or payload.get("status")
    if error_code and not result:
        result = "error"
    ev_type = str(event.get("event_type") or "UNKNOWN")
    return ObservableEventView(
        event_name=ev_type,
        source="control_plane_event",
        timestamp=event.get("recorded_at") or event.get("timestamp"),
        run_id=event.get("run_id"),
        slice_id=event.get("slice"),
        work_item_id=_payload_get(payload, "work_item_id", "target_item_id"),
        assignment_id=actor.get("assignment_id") or _payload_get(payload, "assignment_id"),
        actor=actor.get("principal_id") or actor.get("role"),
        host=host,
        state_before=state_before,
        state_after=state_after,
        duration_ms=duration_ms,
        result=str(result) if result is not None else None,
        error_code=str(error_code) if error_code is not None else None,
        revision=payload.get("plan_revision") or payload.get("revision"),
        tree_digest=_payload_get(payload, "candidate_tree_oid", "tree_oid", "commit_oid"),
        workspace_digest=_payload_get(payload, "workspace_revision_digest"),
        sequence=event.get("sequence"),
        phase=EVENT_TO_PHASE.get(ev_type),
        event_hash=event.get("event_hash"),
        extras={
            "actor_role": actor.get("role"),
            "execution_id": actor.get("execution_id"),
            "payload_type": payload.get("payload_type"),
        },
    )
