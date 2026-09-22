"""Timeline reconstruction from persisted control-plane events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from slice_orchestrator.observability.model import EVENT_TO_PHASE, PHASE_BY_STATE, project_observable_event
from slice_orchestrator.state_machine import project_slice_run_state


def parse_ts(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def duration_ms_between(a: str | None, b: str | None) -> int | None:
    da = parse_ts(a)
    db = parse_ts(b)
    if da is None or db is None:
        return None
    delta = int((db - da).total_seconds() * 1000)
    if delta < 0:
        return None
    return delta


def _project_states_per_event(events: list[dict[str, Any]], control_store: Any = None) -> list[tuple[str | None, str | None]]:
    """Return (state_before, state_after) for each event index using projection prefixes."""
    pairs: list[tuple[str | None, str | None]] = []
    for idx in range(len(events)):
        before = project_slice_run_state(events[:idx], control_store) if idx else None
        after = project_slice_run_state(events[: idx + 1], control_store)
        pairs.append((before.state if before else None, after.state if after else None))
    return pairs


def build_timeline(
    events: list[dict[str, Any]],
    *,
    control_store: Any = None,
    phase_filter: str | None = None,
    errors_only: bool = False,
) -> dict[str, Any]:
    """
    Build ordered timeline with elapsed gaps, phase durations, retries, and terminal outcome.
    """
    ordered = sorted(events, key=lambda e: (e.get("sequence") is None, e.get("sequence", 0)))
    state_pairs = _project_states_per_event(ordered, control_store)
    entries: list[dict[str, Any]] = []
    prev_ts: str | None = None
    for ev, (before, after) in zip(ordered, state_pairs):
        gap = duration_ms_between(prev_ts, ev.get("recorded_at") or ev.get("timestamp"))
        view = project_observable_event(ev, state_before=before, state_after=after, duration_ms=gap)
        item = view.to_dict()
        item["elapsed_since_previous_ms"] = gap
        phase = view.phase or (PHASE_BY_STATE.get(after or "") if after else None)
        item["phase"] = phase
        if phase_filter and phase != phase_filter and EVENT_TO_PHASE.get(view.event_name) != phase_filter:
            prev_ts = view.timestamp or prev_ts
            continue
        if errors_only and not view.error_code and not (
            view.event_name in ("RUN_STOPPED", "COMMIT_FAILED_RECOVERABLE", "REVIEW_BLOCKED", "ARCHITECTURE_BLOCKED")
            or (view.result and str(view.result).upper() in ("FAILED", "ERROR", "BLOCKED"))
        ):
            prev_ts = view.timestamp or prev_ts
            continue
        entries.append(item)
        prev_ts = view.timestamp or prev_ts

    phase_durations = _calculate_phase_durations(ordered, state_pairs)
    retries = [
        e for e in ordered
        if e.get("event_type") in ("IMPLEMENTATION_WORKER_REASSIGNED", "CANDIDATE_INVALIDATED", "ACCEPTANCE_INVALIDATED")
    ]
    replacements = [e for e in ordered if e.get("event_type") == "IMPLEMENTATION_WORKER_REASSIGNED"]
    reviews = [
        e for e in ordered
        if e.get("event_type") in (
            "ADVERSARIAL_REVIEW_ASSIGNED", "REVIEW_ACCEPTED", "REVIEW_BLOCKED",
            "ARCHITECTURE_REVIEW_ASSIGNED", "ARCHITECTURE_APPROVED", "ARCHITECTURE_BLOCKED",
        )
    ]
    remediations = [e for e in ordered if e.get("event_type") in ("REMEDIATION_ASSIGNED", "REVIEW_BLOCKED")]
    transitions = [
        {"sequence": e.get("sequence"), "event_type": e.get("event_type"), "from": b, "to": a}
        for e, (b, a) in zip(ordered, state_pairs)
        if b != a
    ]

    final_state = state_pairs[-1][1] if state_pairs else None
    terminal_outcome = final_state if final_state in ("COMPLETE", "STOPPED", "FAILED") else "IN_PROGRESS"

    first_ts = ordered[0].get("recorded_at") if ordered else None
    last_ts = ordered[-1].get("recorded_at") if ordered else None
    total_elapsed = duration_ms_between(first_ts, last_ts)

    return {
        "event_count": len(ordered),
        "displayed_count": len(entries),
        "entries": entries,
        "phase_durations_ms": phase_durations,
        "retries": [{"sequence": e.get("sequence"), "event_type": e.get("event_type")} for e in retries],
        "worker_replacements": [
            {"sequence": e.get("sequence"), "event_type": e.get("event_type")} for e in replacements
        ],
        "reviews": [{"sequence": e.get("sequence"), "event_type": e.get("event_type")} for e in reviews],
        "remediations": [{"sequence": e.get("sequence"), "event_type": e.get("event_type")} for e in remediations],
        "state_transitions": transitions,
        "terminal_outcome": terminal_outcome,
        "final_state": final_state,
        "total_elapsed_ms": total_elapsed,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
    }


def _calculate_phase_durations(
    events: list[dict[str, Any]],
    state_pairs: list[tuple[str | None, str | None]],
) -> dict[str, Any]:
    """Accumulate time spent in each lifecycle phase from consecutive timestamps."""
    accum: dict[str, int] = {}
    unavailable_gaps = 0
    for idx in range(len(events) - 1):
        _before, after = state_pairs[idx]
        phase = PHASE_BY_STATE.get(after or "", EVENT_TO_PHASE.get(events[idx].get("event_type", ""), "unknown"))
        gap = duration_ms_between(
            events[idx].get("recorded_at") or events[idx].get("timestamp"),
            events[idx + 1].get("recorded_at") or events[idx + 1].get("timestamp"),
        )
        if gap is None:
            unavailable_gaps += 1
            continue
        accum[phase] = accum.get(phase, 0) + gap
    return {
        "by_phase": accum,
        "unavailable_gap_count": unavailable_gaps,
        "status": "MEASURED" if events and unavailable_gaps == 0 else (
            "DERIVED" if accum else "UNAVAILABLE"
        ),
    }
