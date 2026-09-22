"""Authoritative metrics engine with provenance.

Metrics are derived from persisted control-plane events, verified receipts,
assignments, reviews, gates, and timestamps — never from worker-written summaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from slice_orchestrator.canonical import compute_record_digest
from slice_orchestrator.observability.timeline import build_timeline, duration_ms_between, parse_ts


class MetricStatus(str, Enum):
    MEASURED = "MEASURED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    DECLARED = "DECLARED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class MetricProvenance:
    metric: str
    value: Any
    source_event_range: list[int] | None
    source_digest: str | None
    calculated_at: str
    status: MetricStatus
    assumptions: list[str] | None = None
    limitations: list[str] | None = None
    authoritative: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, MetricStatus) else str(self.status)
        return data


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _range(events: list[dict[str, Any]]) -> list[int] | None:
    seqs = [e.get("sequence") for e in events if isinstance(e.get("sequence"), int)]
    if not seqs:
        return None
    return [min(seqs), max(seqs)]


def _digest_events(events: list[dict[str, Any]]) -> str:
    payload = [
        {
            "sequence": e.get("sequence"),
            "event_type": e.get("event_type"),
            "event_hash": e.get("event_hash"),
            "recorded_at": e.get("recorded_at"),
        }
        for e in events
    ]
    return compute_record_digest(payload)


class MetricsEngine:
    """Compute run metrics with explicit provenance and trust status."""

    SCHEMA_VERSION = "observability-metrics-v1"

    def __init__(self, control_store: Any):
        self.store = control_store

    def compute_for_slice(self, slice_name: str, *, run_id: str | None = None) -> dict[str, Any]:
        try:
            all_events = self.store.verify_store_integrity()
        except Exception as exc:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "slice": slice_name,
                "error": f"corrupt_or_unreadable_state: {exc}",
                "metrics": {},
                "status": MetricStatus.UNAVAILABLE.value,
            }

        events = [e for e in all_events if e.get("slice") == slice_name]
        if run_id:
            events = [e for e in events if e.get("run_id") == run_id]
        if not events:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "slice": slice_name,
                "run_id": run_id,
                "metrics": {},
                "status": MetricStatus.UNAVAILABLE.value,
                "message": "No events for slice",
            }

        run_id = run_id or events[0].get("run_id")
        events = sorted(events, key=lambda e: e.get("sequence", 0))
        timeline = build_timeline(events, control_store=self.store)
        receipts = self.store.list_receipts(slice_name=slice_name, run_id=run_id)
        assignments = self._list_assignments(run_id)
        work_items = self.store.list_work_items(run_id=run_id, slice_name=slice_name)
        reviews = self.store.list_records_by_type("REVIEW") + self.store.list_records_by_type("ARCHITECTURE_REVIEW")
        reviews = [r for r in reviews if r.get("slice") == slice_name or r.get("run_id") == run_id]
        remediations = [
            r for r in self.store.list_records_by_type("REMEDIATION_PACKET")
            if r.get("slice") == slice_name or r.get("run_id") == run_id
        ]
        clarifications = [
            r for r in self.store.list_records_by_type("REQUIREMENT_CLARIFICATION")
            if r.get("slice") == slice_name or r.get("run_id") == run_id
        ]
        state = None
        try:
            from slice_orchestrator.state_machine import project_slice_run_state
            state = project_slice_run_state(events, self.store)
        except Exception:
            state = None

        metrics: dict[str, dict[str, Any]] = {}
        metrics.update(self._execution_metrics(events, timeline, state))
        metrics.update(self._interaction_metrics(events, clarifications, timeline))
        metrics.update(self._worker_metrics(events, assignments))
        metrics.update(self._quality_metrics(events, receipts, reviews, remediations, state))
        metrics.update(self._recovery_metrics(events, assignments))
        metrics.update(self._change_metrics(events, state))

        return {
            "schema_version": self.SCHEMA_VERSION,
            "slice": slice_name,
            "run_id": run_id,
            "calculated_at": _now(),
            "source_event_range": _range(events),
            "source_digest": _digest_events(events),
            "metrics": metrics,
            "notes": [
                "DECLARED values must not be used for authoritative conclusions.",
                "Worker-written summaries are never sources for authoritative metrics.",
                "Missing instrumentation yields UNAVAILABLE rather than fabricated numbers.",
            ],
        }

    def _metric(
        self,
        name: str,
        value: Any,
        events: list[dict[str, Any]],
        status: MetricStatus,
        *,
        authoritative: bool = False,
        assumptions: list[str] | None = None,
        limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        prov = MetricProvenance(
            metric=name,
            value=value,
            source_event_range=_range(events) if events else None,
            source_digest=_digest_events(events) if events else None,
            calculated_at=_now(),
            status=status,
            assumptions=assumptions,
            limitations=limitations,
            authoritative=authoritative and status in (MetricStatus.MEASURED, MetricStatus.DERIVED),
        )
        return prov.to_dict()

    def _execution_metrics(
        self,
        events: list[dict[str, Any]],
        timeline: dict[str, Any],
        state: Any,
    ) -> dict[str, dict[str, Any]]:
        total = timeline.get("total_elapsed_ms")
        phase = timeline.get("phase_durations_ms", {})
        transitions = timeline.get("state_transitions") or []
        retries = timeline.get("retries") or []
        recoveries = [e for e in events if e.get("event_type") == "HUMAN_RECOVERY_OPENED"]
        pauses = [e for e in events if e.get("event_type") == "RUN_PAUSED"]
        resumes = [e for e in events if e.get("event_type") == "RUN_RESUMED"]

        active = phase.get("by_phase", {}) if isinstance(phase, dict) else {}
        active_sum = sum(v for k, v in active.items() if k not in ("paused", "stopped", "failed"))
        human_wait = active.get("paused")  # PAUSED gaps only; otherwise UNAVAILABLE below

        out: dict[str, dict[str, Any]] = {
            "total_elapsed_time_ms": self._metric(
                "total_elapsed_time_ms",
                total,
                events,
                MetricStatus.MEASURED if total is not None else MetricStatus.UNAVAILABLE,
                authoritative=True,
                limitations=["Wall-clock between first and last event timestamps only"],
            ),
            "active_execution_time_ms": self._metric(
                "active_execution_time_ms",
                active_sum if active else None,
                events,
                MetricStatus.DERIVED if active else MetricStatus.UNAVAILABLE,
                authoritative=True,
                limitations=["Sum of inter-event gaps attributed to non-paused phases"],
            ),
            "human_waiting_time_ms": self._metric(
                "human_waiting_time_ms",
                human_wait if human_wait is not None else None,
                pauses + resumes,
                MetricStatus.DERIVED if human_wait is not None else MetricStatus.UNAVAILABLE,
                authoritative=False,
                limitations=[
                    "Only RUN_PAUSED phase gaps are measured; grill/decision wait without pause is UNAVAILABLE",
                ],
            ),
            "time_per_lifecycle_phase_ms": self._metric(
                "time_per_lifecycle_phase_ms",
                active if active else None,
                events,
                MetricStatus(phase.get("status", "UNAVAILABLE")) if isinstance(phase, dict) else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "number_of_transitions": self._metric(
                "number_of_transitions",
                len(transitions),
                events,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "number_of_retries": self._metric(
                "number_of_retries",
                len(retries),
                events,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "number_of_restarts": self._metric(
                "number_of_restarts",
                len(recoveries) + len(resumes),
                recoveries + resumes,
                MetricStatus.DERIVED,
                authoritative=True,
                limitations=["Counts HUMAN_RECOVERY_OPENED + RUN_RESUMED; host process restarts not instrumented"],
            ),
        }

        # Per work item / worker / review / remediation durations where assignment timestamps exist
        out["time_per_work_item_ms"] = self._metric(
            "time_per_work_item_ms",
            None,
            events,
            MetricStatus.UNAVAILABLE,
            limitations=["Per-work-item wall clocks require assignment+completion pairing not always present"],
        )
        out["time_per_worker_ms"] = self._metric(
            "time_per_worker_ms",
            None,
            events,
            MetricStatus.UNAVAILABLE,
            limitations=["Worker process timing is not persisted independently of assignments"],
        )
        review_assign = [e for e in events if e.get("event_type") == "ADVERSARIAL_REVIEW_ASSIGNED"]
        review_done = [e for e in events if e.get("event_type") in ("REVIEW_ACCEPTED", "REVIEW_BLOCKED")]
        review_times = []
        for a in review_assign:
            for d in review_done:
                if d.get("sequence", 0) > a.get("sequence", 0):
                    ms = duration_ms_between(a.get("recorded_at"), d.get("recorded_at"))
                    if ms is not None:
                        review_times.append(ms)
                    break
        out["time_per_review_ms"] = self._metric(
            "time_per_review_ms",
            review_times or None,
            review_assign + review_done,
            MetricStatus.DERIVED if review_times else MetricStatus.UNAVAILABLE,
            authoritative=True,
        )
        rem_assign = [e for e in events if e.get("event_type") == "REMEDIATION_ASSIGNED"]
        rem_times = []
        for a in rem_assign:
            # next candidate or review after remediation
            later = [e for e in events if e.get("sequence", 0) > a.get("sequence", 0)]
            if later:
                ms = duration_ms_between(a.get("recorded_at"), later[0].get("recorded_at"))
                if ms is not None:
                    rem_times.append(ms)
        out["time_per_remediation_ms"] = self._metric(
            "time_per_remediation_ms",
            rem_times or None,
            rem_assign,
            MetricStatus.DERIVED if rem_times else MetricStatus.UNAVAILABLE,
            authoritative=True,
        )
        return out

    def _interaction_metrics(
        self,
        events: list[dict[str, Any]],
        clarifications: list[dict[str, Any]],
        timeline: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        host_events = [
            e for e in events
            if isinstance(e.get("payload"), dict) and e["payload"].get("host_metadata")
        ]
        context_events = [e for e in events if e.get("event_type") == "CONTEXT_PACK_GENERATED"]
        pauses = [e for e in events if e.get("event_type") == "RUN_PAUSED"]
        return {
            "human_questions": self._metric(
                "human_questions",
                len(clarifications),
                events,
                MetricStatus.MEASURED if clarifications else MetricStatus.DERIVED,
                authoritative=True,
                limitations=["Counts REQUIREMENT_CLARIFICATION records; DecisionRequired schemas may exist unused"],
            ),
            "questions_answered_from_repository_facts": self._metric(
                "questions_answered_from_repository_facts",
                None,
                events,
                MetricStatus.UNAVAILABLE,
                limitations=["No authoritative classification of grill answers vs repo facts"],
            ),
            "questions_genuinely_requiring_human_input": self._metric(
                "questions_genuinely_requiring_human_input",
                None,
                events,
                MetricStatus.UNAVAILABLE,
            ),
            "human_answers": self._metric(
                "human_answers",
                len(clarifications),
                events,
                MetricStatus.DERIVED,
                authoritative=False,
                limitations=["Clarification records conflate questions and answers today"],
            ),
            "human_interruptions": self._metric(
                "human_interruptions",
                len(pauses),
                pauses,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "time_waiting_for_human_ms": self._metric(
                "time_waiting_for_human_ms",
                (timeline.get("phase_durations_ms") or {}).get("by_phase", {}).get("paused"),
                pauses,
                MetricStatus.DERIVED if pauses else MetricStatus.UNAVAILABLE,
                authoritative=False,
            ),
            "context_reconstruction_events": self._metric(
                "context_reconstruction_events",
                len(context_events),
                context_events,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "number_of_mcp_tool_calls": self._metric(
                "number_of_mcp_tool_calls",
                len(host_events) if host_events else None,
                host_events,
                MetricStatus.DERIVED if host_events else MetricStatus.UNAVAILABLE,
                authoritative=False,
                limitations=[
                    "Derived from events carrying host_metadata only; not a complete MCP call counter",
                ],
            ),
        }

    def _worker_metrics(
        self,
        events: list[dict[str, Any]],
        assignments: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        issued = [e for e in events if e.get("event_type") == "ASSIGNMENT_ISSUED"]
        consumed = [e for e in events if e.get("event_type") == "ASSIGNMENT_CONSUMED"]
        replacements = [e for e in events if e.get("event_type") == "IMPLEMENTATION_WORKER_REASSIGNED"]
        stopped = [e for e in events if e.get("event_type") == "RUN_STOPPED"]
        failures = []
        timeouts = []
        unavailable = []
        for e in stopped:
            payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            code = payload.get("stop_reason_code") or payload.get("failure_code")
            if code == "WORKER_FAILED":
                failures.append(e)
            elif code == "WORKER_UNAVAILABLE":
                unavailable.append(e)
            elif code and "TIMEOUT" in str(code).upper():
                timeouts.append(e)
        stale_rejected = [a for a in assignments if a.get("status") in ("EXPIRED", "REJECTED", "STALE")]
        return {
            "worker_executions": self._metric(
                "worker_executions",
                len(issued),
                issued,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "worker_failures": self._metric(
                "worker_failures",
                len(failures),
                failures,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "worker_timeouts": self._metric(
                "worker_timeouts",
                len(timeouts),
                timeouts,
                MetricStatus.MEASURED if timeouts else MetricStatus.UNAVAILABLE,
                authoritative=True,
                limitations=["Timeouts only counted when stop_reason_code contains TIMEOUT"],
            ),
            "worker_replacements": self._metric(
                "worker_replacements",
                len(replacements),
                replacements,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "worker_unavailable_events": self._metric(
                "worker_unavailable_events",
                len(unavailable),
                unavailable,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "worker_result_validation_failures": self._metric(
                "worker_result_validation_failures",
                len([e for e in stopped if (e.get("payload") or {}).get("stop_reason_code") == "MALFORMED_WORKER_OUTPUT"]),
                stopped,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "stale_assignments_rejected": self._metric(
                "stale_assignments_rejected",
                len(stale_rejected),
                [],
                MetricStatus.MEASURED if assignments else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "assignments_consumed": self._metric(
                "assignments_consumed",
                len(consumed),
                consumed,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
        }

    def _quality_metrics(
        self,
        events: list[dict[str, Any]],
        receipts: list[dict[str, Any]],
        reviews: list[dict[str, Any]],
        remediations: list[dict[str, Any]],
        state: Any,
    ) -> dict[str, dict[str, Any]]:
        passed = [r for r in receipts if r.get("passed") is True]
        failed = [r for r in receipts if r.get("passed") is False]
        review_events = [
            e for e in events
            if e.get("event_type") in ("ADVERSARIAL_REVIEW_ASSIGNED", "ARCHITECTURE_REVIEW_ASSIGNED")
        ]
        findings_critical = findings_major = findings_minor = 0
        findings_total = 0
        for rev in reviews:
            findings = rev.get("findings") or rev.get("issues") or []
            if isinstance(findings, list):
                findings_total += len(findings)
                for f in findings:
                    sev = str((f or {}).get("severity", "")).upper() if isinstance(f, dict) else ""
                    if sev in ("CRITICAL", "BLOCKER"):
                        findings_critical += 1
                    elif sev in ("MAJOR", "HIGH"):
                        findings_major += 1
                    elif sev in ("MINOR", "LOW", "NIT"):
                        findings_minor += 1
        test_retries = max(0, len(receipts) - 1) if len(receipts) > 1 else 0
        return {
            "tests_executed": self._metric(
                "tests_executed", len(receipts), events, MetricStatus.MEASURED, authoritative=True,
                limitations=["Counts signed TEST_RECEIPT records only"],
            ),
            "tests_passed": self._metric(
                "tests_passed", len(passed), events, MetricStatus.MEASURED, authoritative=True,
            ),
            "tests_failed": self._metric(
                "tests_failed", len(failed), events, MetricStatus.MEASURED, authoritative=True,
            ),
            "test_retries": self._metric(
                "test_retries", test_retries, events, MetricStatus.DERIVED, authoritative=True,
                limitations=["Approximate: total receipts minus one when multiple receipts exist"],
            ),
            "reviews_executed": self._metric(
                "reviews_executed", len(review_events), review_events, MetricStatus.MEASURED, authoritative=True,
            ),
            "review_findings": self._metric(
                "review_findings", findings_total, [], MetricStatus.MEASURED if reviews else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "critical_findings": self._metric(
                "critical_findings", findings_critical, [], MetricStatus.MEASURED if reviews else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "major_findings": self._metric(
                "major_findings", findings_major, [], MetricStatus.MEASURED if reviews else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "minor_findings": self._metric(
                "minor_findings", findings_minor, [], MetricStatus.MEASURED if reviews else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "remediation_cycles": self._metric(
                "remediation_cycles",
                getattr(state, "remediation_cycle_high_water", len(remediations)) if state else len(remediations),
                events,
                MetricStatus.MEASURED,
                authoritative=True,
            ),
            "defects_detected_before_review": self._metric(
                "defects_detected_before_review", len(failed), events, MetricStatus.DERIVED, authoritative=True,
                limitations=["Approximated as failed control-test receipts before review"],
            ),
            "defects_detected_during_review": self._metric(
                "defects_detected_during_review",
                findings_total,
                [],
                MetricStatus.DERIVED if reviews else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
            "defects_escaping_review": self._metric(
                "defects_escaping_review",
                None,
                events,
                MetricStatus.UNAVAILABLE,
                limitations=["Requires post-complete defect tracking outside the control plane"],
            ),
            "authoritative_test_changes": self._metric(
                "authoritative_test_changes",
                None,
                events,
                MetricStatus.UNAVAILABLE,
                limitations=["Requires explicit protected-test diff instrumentation in export path"],
            ),
            "out_of_scope_changes": self._metric(
                "out_of_scope_changes",
                None,
                events,
                MetricStatus.UNAVAILABLE,
                limitations=["Scope violations are gate failures; dedicated counter not yet persisted"],
            ),
            "review_cycle_high_water": self._metric(
                "review_cycle_high_water",
                getattr(state, "review_cycle_high_water", None) if state else None,
                events,
                MetricStatus.MEASURED if state else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
        }

    def _recovery_metrics(
        self,
        events: list[dict[str, Any]],
        assignments: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        recoveries = [e for e in events if e.get("event_type") == "HUMAN_RECOVERY_OPENED"]
        resumes = [e for e in events if e.get("event_type") == "RUN_RESUMED"]
        context = [e for e in events if e.get("event_type") == "CONTEXT_PACK_GENERATED"]
        stale = [a for a in assignments if a.get("status") in ("EXPIRED", "REJECTED", "STALE")]
        return {
            "process_restarts": self._metric(
                "process_restarts", None, events, MetricStatus.UNAVAILABLE,
                limitations=["OS/process restarts are not control-plane events"],
            ),
            "mcp_restarts": self._metric(
                "mcp_restarts", None, events, MetricStatus.UNAVAILABLE,
                limitations=["MCP process restarts require external evidence files"],
            ),
            "cursor_restarts": self._metric(
                "cursor_restarts", None, events, MetricStatus.UNAVAILABLE,
                limitations=["Cursor IDE restarts require operator attestation evidence"],
            ),
            "successful_recoveries": self._metric(
                "successful_recoveries",
                len(recoveries) + len(resumes),
                recoveries + resumes,
                MetricStatus.DERIVED,
                authoritative=True,
            ),
            "failed_recoveries": self._metric(
                "failed_recoveries",
                None,
                events,
                MetricStatus.UNAVAILABLE,
            ),
            "work_items_resumed": self._metric(
                "work_items_resumed",
                len(resumes),
                resumes,
                MetricStatus.DERIVED,
                authoritative=False,
            ),
            "context_losses": self._metric(
                "context_losses",
                None,
                context,
                MetricStatus.UNAVAILABLE,
                limitations=["Context regeneration is not equivalent to context loss"],
            ),
            "stale_assignments_rejected": self._metric(
                "stale_assignments_rejected",
                len(stale),
                [],
                MetricStatus.MEASURED if assignments else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
        }

    def _change_metrics(self, events: list[dict[str, Any]], state: Any) -> dict[str, dict[str, Any]]:
        commits = [e for e in events if e.get("event_type") in ("COMMIT_RECORDED", "GOVERNANCE_COMMIT_RECORDED")]
        candidates = [e for e in events if e.get("event_type") == "CANDIDATE_CAPTURED"]
        return {
            "files_changed": self._metric(
                "files_changed", None, events, MetricStatus.UNAVAILABLE,
                limitations=["Requires git diff against base_commit; computed optionally at export time"],
            ),
            "lines_added": self._metric(
                "lines_added", None, events, MetricStatus.UNAVAILABLE,
            ),
            "lines_deleted": self._metric(
                "lines_deleted", None, events, MetricStatus.UNAVAILABLE,
            ),
            "commits": self._metric(
                "commits", len(commits), commits, MetricStatus.MEASURED, authoritative=True,
            ),
            "candidate_tree_changes": self._metric(
                "candidate_tree_changes", len(candidates), candidates, MetricStatus.MEASURED, authoritative=True,
            ),
            "rework_changes": self._metric(
                "rework_changes",
                len([e for e in events if e.get("event_type") in ("CANDIDATE_INVALIDATED", "REMEDIATION_ASSIGNED")]),
                events,
                MetricStatus.DERIVED,
                authoritative=True,
            ),
            "final_commit_oid": self._metric(
                "final_commit_oid",
                getattr(state, "committed_implementation_oid", None) if state else None,
                commits,
                MetricStatus.MEASURED if state and getattr(state, "committed_implementation_oid", None) else MetricStatus.UNAVAILABLE,
                authoritative=True,
            ),
        }

    def _list_assignments(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []
        if hasattr(self.store, "list_assignments"):
            try:
                return list(self.store.list_assignments(run_id=run_id))
            except Exception:
                return []
        # Fallback: scan ASSIGNMENT_ISSUED payloads + get_assignment
        try:
            events = self.store.verify_store_integrity()
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for e in events:
            if e.get("run_id") != run_id:
                continue
            if e.get("event_type") != "ASSIGNMENT_ISSUED":
                continue
            payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            aid = payload.get("assignment_id") or (e.get("actor") or {}).get("assignment_id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            row = self.store.get_assignment(aid)
            if row:
                out.append(row)
        return out
