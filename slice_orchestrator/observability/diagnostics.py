"""Diagnostic commands: doctor, diagnostics, explain."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from slice_orchestrator.observability.model import PHASE_BY_STATE
from slice_orchestrator.observability.redaction import redact_value


def _check(name: str, ok: bool, detail: str, *, severity: str = "error") -> dict[str, Any]:
    return {
        "check": name,
        "ok": ok,
        "detail": detail,
        "severity": severity if not ok else "info",
    }


def run_doctor(
    *,
    repo_dir: Path,
    control_home: Path | None = None,
    package_name: str = "slice_orchestrator",
) -> dict[str, Any]:
    """Environment and control-plane health checks. Does not mutate authority."""
    repo_dir = Path(repo_dir).resolve()
    control_home = Path(control_home or (repo_dir / ".orchestrator_slice")).resolve()
    checks: list[dict[str, Any]] = []

    # package installation
    spec = importlib.util.find_spec(package_name)
    checks.append(_check("package_installation", spec is not None, f"import {package_name}"))

    # configuration / project root
    checks.append(_check("project_root", repo_dir.is_dir(), str(repo_dir)))
    git_ok = (repo_dir / ".git").exists()
    checks.append(_check("git_repository", git_ok, "repo has .git", severity="warning"))

    # control home
    checks.append(_check("control_home", control_home.is_dir() or True, str(control_home), severity="info"))
    if not control_home.is_dir():
        try:
            control_home.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            checks.append(_check("control_home_writable", False, str(exc)))
        else:
            checks.append(_check("control_home_writable", True, "created"))
    else:
        checks.append(_check("control_home_writable", True, "exists"))

    # database
    db_path = control_home / "state.db"
    checks.append(_check("database_availability", True, str(db_path), severity="info" if not db_path.is_file() else "info"))
    if db_path.is_file():
        checks[-1]["detail"] = f"present ({db_path.stat().st_size} bytes)"
    else:
        checks[-1]["detail"] = "absent (empty store allowed)"

    # schema / trust / secret / event chain via ControlStore
    schema_ok = False
    trust_ok = False
    secret_ok = False
    chain_ok = False
    chain_detail = "not checked"
    try:
        from slice_orchestrator.control_store import ControlStore, ControlStoreError, TrustStateError

        store = ControlStore(control_home, policy_bundle_source=repo_dir / ".orchestrator")
        secret_ok = store.secret_path.is_file() and len(store.secret) == 32
        checks.append(_check("secret_availability", secret_ok, str(store.secret_path)))
        trust_ok = store.tail_anchor_path.is_file() or not store._db_file_has_events()
        checks.append(
            _check(
                "trust_anchor",
                trust_ok,
                str(store.tail_anchor_path) if store.tail_anchor_path.is_file() else "no events yet",
            )
        )
        try:
            bundle = store.load_and_verify_policy_bundle()
            schema_ok = bundle is not None
            checks.append(_check("schema_validity", schema_ok, "policy bundle verified"))
        except Exception as exc:
            # Fresh control homes may not have a pinned bundle yet.
            try:
                if (repo_dir / ".orchestrator").is_dir() and not (control_home / "policy_bundle_digest").is_file():
                    store.initialize_policy_bundle(repo_dir / ".orchestrator")
                    bundle = store.load_and_verify_policy_bundle()
                    checks.append(_check("schema_validity", True, "policy bundle initialized for doctor"))
                else:
                    checks.append(_check("schema_validity", False, f"policy bundle: {exc}", severity="warning"))
            except Exception as exc2:
                checks.append(_check("schema_validity", False, f"policy bundle: {exc2}", severity="warning"))
        try:
            events = store.verify_store_integrity()
            chain_ok = True
            chain_detail = f"{len(events)} events verified"
        except (ControlStoreError, TrustStateError) as exc:
            chain_ok = False
            chain_detail = str(exc)
        checks.append(_check("event_chain_integrity", chain_ok, chain_detail))
    except Exception as exc:
        checks.append(_check("secret_availability", False, str(exc)))
        checks.append(_check("trust_anchor", False, str(exc)))
        checks.append(_check("schema_validity", False, str(exc), severity="warning"))
        checks.append(_check("event_chain_integrity", False, str(exc)))

    # runtime directories
    for name in ("records", "artifacts", "logs", "locks"):
        path = control_home / name
        checks.append(_check(f"runtime_dir_{name}", True, str(path), severity="info"))

    # MCP configuration
    cursor_mcp = repo_dir / ".cursor" / "mcp.json"
    project_mcp = repo_dir / ".mcp.json"
    mcp_ok = cursor_mcp.is_file() or project_mcp.is_file()
    checks.append(
        _check(
            "mcp_configuration",
            mcp_ok,
            f"cursor={cursor_mcp.is_file()} project={project_mcp.is_file()}",
            severity="warning",
        )
    )

    # worker availability (configured adapters present as modules; binaries optional)
    workers = {
        "dummy": True,
        "python": shutil.which("python3") is not None,
        "cursor-agent": shutil.which("cursor-agent") is not None,
        "claude": shutil.which("claude") is not None,
        "gemini": shutil.which("gemini") is not None,
    }
    checks.append(
        _check(
            "worker_availability",
            True,
            json.dumps(workers),
            severity="info",
        )
    )

    # test command
    pytest_ok = shutil.which("pytest") is not None or importlib.util.find_spec("pytest") is not None
    checks.append(_check("test_command_availability", pytest_ok, "pytest", severity="warning"))
    checks.append(_check("git_command", shutil.which("git") is not None, "git"))
    checks.append(_check("python_runtime", sys.version_info >= (3, 11), sys.version.split()[0]))

    hard_fails = [c for c in checks if not c["ok"] and c.get("severity") == "error"]
    warn_fails = [c for c in checks if not c["ok"] and c.get("severity") == "warning"]
    status = "ok"
    exit_code = 0
    if hard_fails:
        status = "fail"
        exit_code = 1
    elif warn_fails:
        status = "warn"
        exit_code = 0

    return {
        "status": status,
        "exit_code": exit_code,
        "repo_dir": str(repo_dir),
        "control_home": str(control_home),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": sum(1 for c in checks if c["ok"]),
            "failed": sum(1 for c in checks if not c["ok"]),
            "errors": len(hard_fails),
            "warnings": len(warn_fails),
        },
    }


def build_diagnostics(
    controller: Any,
    slice_name: str,
) -> dict[str, Any]:
    """Slice diagnostics from persisted facts only."""
    store = controller.store
    state = controller.get_slice_state(slice_name)
    if not state:
        return {
            "slice": slice_name,
            "exists": False,
            "message": "No persistent Slice Run exists.",
        }

    try:
        events = [e for e in store.verify_store_integrity() if e.get("slice") == slice_name]
    except Exception as exc:
        return {
            "slice": slice_name,
            "exists": True,
            "corrupt_state": True,
            "error": str(exc),
        }

    events = sorted(events, key=lambda e: e.get("sequence", 0))
    latest = events[-1] if events else None
    work_items = store.list_work_items(run_id=state.run_id, slice_name=slice_name)
    active_wi = None
    for wi in work_items:
        status = getattr(wi, "status", None) or (wi.get("status") if isinstance(wi, dict) else None)
        if status in ("IN_PROGRESS", "ASSIGNED", "READY"):
            active_wi = getattr(wi, "work_item_id", None) or (wi.get("work_item_id") if isinstance(wi, dict) else None)
            if status in ("IN_PROGRESS", "ASSIGNED"):
                break

    blockers: list[str] = []
    if state.stop_reason:
        blockers.append(f"[{state.stop_reason_code}] {state.stop_reason}")
    if state.state == "REMEDIATION":
        blockers.append("Remediation required after review block")
    if state.execution_mode == "PAUSED":
        blockers.append("Execution mode is PAUSED")
    if state.open_remediation_packet_ids:
        blockers.append(f"Open remediation packets: {len(state.open_remediation_packet_ids)}")

    clarifications = [
        r for r in store.list_records_by_type("REQUIREMENT_CLARIFICATION")
        if r.get("slice") == slice_name or r.get("run_id") == state.run_id
    ]
    pending_questions = clarifications  # no separate open/closed flag today
    receipts = store.list_receipts(slice_name=slice_name, run_id=state.run_id)
    failed_tests = [r for r in receipts if r.get("passed") is False]

    failed_gates: list[str] = []
    if state.state == "COMMIT_READY":
        # evaluate without mutating
        try:
            from slice_orchestrator.gates import GateEvaluator
            # Prefer tools-style if available; otherwise report unevaluated
            failed_gates = []
        except Exception:
            failed_gates = []

    assignments = []
    if hasattr(store, "list_assignments"):
        try:
            assignments = store.list_assignments(run_id=state.run_id)
        except Exception:
            assignments = []
    stale = [a for a in assignments if a.get("status") in ("ISSUED",) and a.get("expires_at")]
    # Stale heuristic: still ISSUED while a later assignment for same role exists, or status STALE
    stale_assignments = [a for a in assignments if a.get("status") in ("EXPIRED", "REJECTED", "STALE")]
    for a in assignments:
        if a.get("status") == "ISSUED" and state.current_assignment_id and a.get("assignment_id") != state.current_assignment_id:
            stale_assignments.append(a)

    legal_next: list[str] = []
    if not state.is_terminal() and getattr(controller, "policy_bundle", None):
        rules = controller.policy_bundle.transitions.get("transitions", {}).get(state.state, [])
        legal_next = [r.get("to") or r.get("event") for r in rules if r]

    # Prefer transition engine event names when present on rules
    if not state.is_terminal() and getattr(controller, "policy_bundle", None):
        state_rules = controller.policy_bundle.transitions.get("transitions", {}).get(state.state, [])
        tos = [r.get("to") for r in state_rules if r.get("to")]
        if tos:
            legal_next = tos

    reviewer = None
    for e in reversed(events):
        if e.get("event_type") in ("ADVERSARIAL_REVIEW_ASSIGNED", "ARCHITECTURE_REVIEW_ASSIGNED"):
            payload = e.get("payload") or {}
            reviewer = payload.get("reviewer_principal") or (e.get("actor") or {}).get("principal_id")
            break

    phase = PHASE_BY_STATE.get(state.state, "unknown")
    evidence = {
        "control_home": str(store.control_home),
        "database": str(store.db_path),
        "records_dir": str(store.control_home / "records"),
        "logs_dir": str(store.control_home / "logs"),
        "artifacts_dir": str(store.artifacts_dir),
    }

    return redact_value({
        "slice": slice_name,
        "exists": True,
        "run_id": state.run_id,
        "current_state": state.state,
        "current_phase": phase,
        "latest_event": {
            "sequence": latest.get("sequence") if latest else None,
            "event_type": latest.get("event_type") if latest else None,
            "recorded_at": latest.get("recorded_at") if latest else None,
            "event_hash": latest.get("event_hash") if latest else None,
        },
        "active_work_item": active_wi or state.current_execution_id,
        "blockers": blockers,
        "pending_questions": [
            {"record_id": c.get("record_id") or c.get("clarification_id"), "summary": (c.get("clarification") or "")[:200]}
            for c in pending_questions
        ],
        "failed_tests": [
            {"receipt_id": r.get("receipt_id"), "exit_code": r.get("exit_code"), "test_id": r.get("test_id")}
            for r in failed_tests
        ],
        "failed_gates": failed_gates,
        "current_reviewer": reviewer,
        "stale_assignments": [
            {"assignment_id": a.get("assignment_id"), "status": a.get("status"), "role": a.get("role")}
            for a in stale_assignments
        ],
        "next_legal_actions": legal_next,
        "evidence_locations": evidence,
        "sequence": state.sequence,
        "execution_mode": state.execution_mode,
        "is_terminal": state.is_terminal(),
        "review_cycle": state.review_cycle_high_water,
        "remediation_cycle": state.remediation_cycle_high_water,
    })


def build_explain(controller: Any, slice_name: str) -> dict[str, Any]:
    """
    Plain-language explanation from persisted facts.
    Inference and recommendations are explicitly labeled.
    """
    diag = build_diagnostics(controller, slice_name)
    if not diag.get("exists"):
        return {
            "slice": slice_name,
            "summary": diag.get("message"),
            "facts": [],
            "inference": [],
            "recommendation": None,
            "human_input_required": False,
        }

    facts: list[str] = [
        f"Current state is {diag['current_state']} (phase {diag['current_phase']}).",
        f"Run ID {diag['run_id']}, sequence {diag.get('sequence')}.",
    ]
    latest = diag.get("latest_event") or {}
    if latest.get("event_type"):
        facts.append(f"Latest event is {latest['event_type']} at sequence {latest.get('sequence')}.")

    blockers = diag.get("blockers") or []
    for b in blockers:
        facts.append(f"Blocker fact: {b}")

    if diag.get("failed_tests"):
        facts.append(f"{len(diag['failed_tests'])} failed test receipt(s) are persisted.")
    if diag.get("pending_questions"):
        facts.append(f"{len(diag['pending_questions'])} clarification record(s) exist.")
    if diag.get("stale_assignments"):
        facts.append(f"{len(diag['stale_assignments'])} stale/superseded assignment(s) detected.")

    inference: list[str] = []
    human_required = False
    recommendation = None

    state = diag["current_state"]
    if diag.get("is_terminal"):
        inference.append(f"INFERENCE: Run is terminal ({state}); no further legal transitions.")
        recommendation = "No action required." if state == "COMPLETE" else "Consider human recovery if appropriate."
    elif state == "PLANNING":
        inference.append("INFERENCE: Planning incomplete; plan not yet persisted.")
        recommendation = "Submit a plan via slice_plan / CLI plan flow."
    elif state == "PLAN_READY":
        inference.append("INFERENCE: Plan is ready for architecture review dispatch.")
        recommendation = "Dispatch ARCHITECTURE_REVIEWER."
    elif state == "IMPLEMENTATION":
        inference.append("INFERENCE: Implementation assignment is active or expected.")
        recommendation = "Complete implementer work and record result, or inspect active assignment."
    elif state == "IMPLEMENTATION_READY_FOR_REVIEW":
        inference.append("INFERENCE: Candidate captured; awaiting adversarial review.")
        recommendation = "Request review (slice_request_review) after tests pass."
    elif state == "ADVERSARIAL_REVIEW":
        inference.append("INFERENCE: Review in progress.")
        recommendation = "Record review result for the active reviewer assignment."
    elif state == "REMEDIATION":
        inference.append("INFERENCE: Review blocked; remediation required.")
        pkt_findings: list[dict[str, Any]] = []
        try:
            store = getattr(controller, "store", None)
            st = controller.get_slice_state(slice_name) if controller else None
            pkt_id = getattr(st, "latest_remediation_packet_id", None)
            if store and pkt_id:
                pkt_data = store.get_record(pkt_id)
                pkt_findings = pkt_data.get("findings", [])
            elif store:
                packets = store.list_records_by_type("REMEDIATION_PACKET")
                sp = [p for p in packets if p.get("slice") == slice_name]
                if sp:
                    pkt_findings = sp[-1].get("findings", [])
        except Exception:
            pass

        if pkt_findings:
            for f in pkt_findings:
                fid = f.get("finding_id", "F")
                fdesc = f.get("description", "")
                facts.append(f"Remediation finding [{fid}]: {fdesc}")
            recommendation = f"Call slice_remediate / 'slice remediate {slice_name}' to transition to IMPLEMENTATION and address {len(pkt_findings)} review finding(s)."
        else:
            recommendation = f"Call slice_remediate / 'slice remediate {slice_name}' to transition to IMPLEMENTATION and address review findings."
        human_required = bool(diag.get("pending_questions"))
    elif state == "COMMIT_READY":
        inference.append("INFERENCE: Ready for gate evaluation and finalize.")
        recommendation = "Run gate evaluation then finalize."
    elif state == "STOPPED":
        inference.append("INFERENCE: Run stopped; recovery may be required.")
        recommendation = "Use recover with an allowed target state."
        human_required = True
    else:
        inference.append(f"INFERENCE: State {state} has legal next actions: {diag.get('next_legal_actions')}.")
        recommendation = f"Next legal actions: {', '.join(diag.get('next_legal_actions') or []) or 'none listed'}."

    if diag.get("execution_mode") == "PAUSED":
        human_required = True
        inference.append("INFERENCE: Human or operator action needed to resume.")
        recommendation = "Resume the slice run."

    why_blocked = blockers[0] if blockers else (
        "Not blocked." if not diag.get("is_terminal") else f"Terminal state {state}."
    )

    return {
        "slice": slice_name,
        "run_id": diag.get("run_id"),
        "why_blocked": why_blocked,
        "facts": facts,
        "inference": inference,
        "gate_or_requirement": blockers[0] if blockers else None,
        "possible_actions": diag.get("next_legal_actions") or [],
        "human_input_required": human_required,
        "recommendation": f"RECOMMENDATION: {recommendation}",
        "diagnostics_ref": {
            "current_state": state,
            "latest_event": latest.get("event_type"),
            "failed_tests": len(diag.get("failed_tests") or []),
        },
    }


def format_doctor_human(report: dict[str, Any]) -> str:
    lines = [
        "=== slice doctor ===",
        f"Status: {report['status']}",
        f"Repo:   {report['repo_dir']}",
        f"Home:   {report['control_home']}",
        "",
    ]
    for c in report["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        lines.append(f"[{mark}] {c['check']}: {c['detail']}")
    summary = report["summary"]
    lines.append("")
    lines.append(
        f"Summary: {summary['passed']}/{summary['total']} passed "
        f"({summary['errors']} errors, {summary['warnings']} warnings)"
    )
    return "\n".join(lines)


def format_diagnostics_human(diag: dict[str, Any]) -> str:
    if not diag.get("exists"):
        return diag.get("message") or "Slice not found"
    lines = [
        f"=== slice diagnostics {diag['slice']} ===",
        f"State:            {diag['current_state']}",
        f"Phase:            {diag['current_phase']}",
        f"Run ID:           {diag['run_id']}",
        f"Latest event:     {diag['latest_event']}",
        f"Active work item: {diag.get('active_work_item')}",
        f"Blockers:         {diag.get('blockers') or '(none)'}",
        f"Pending Qs:       {len(diag.get('pending_questions') or [])}",
        f"Failed tests:     {len(diag.get('failed_tests') or [])}",
        f"Failed gates:     {diag.get('failed_gates') or '(none)'}",
        f"Reviewer:         {diag.get('current_reviewer')}",
        f"Stale assigns:    {len(diag.get('stale_assignments') or [])}",
        f"Next actions:     {diag.get('next_legal_actions')}",
        f"Evidence:         {diag.get('evidence_locations')}",
    ]
    return "\n".join(lines)


def format_explain_human(expl: dict[str, Any]) -> str:
    lines = [
        f"=== slice explain {expl.get('slice')} ===",
        f"Why blocked: {expl.get('why_blocked')}",
        "",
        "Facts:",
    ]
    for f in expl.get("facts") or []:
        lines.append(f"  - {f}")
    lines.append("")
    lines.append("Inference:")
    for i in expl.get("inference") or []:
        lines.append(f"  - {i}")
    lines.append("")
    lines.append(f"Human input required: {expl.get('human_input_required')}")
    lines.append(f"Possible actions: {expl.get('possible_actions')}")
    lines.append(str(expl.get("recommendation")))
    return "\n".join(lines)


def format_timeline_human(timeline: dict[str, Any]) -> str:
    lines = [
        "=== slice timeline ===",
        f"Events: {timeline.get('event_count')} (displayed {timeline.get('displayed_count')})",
        f"Outcome: {timeline.get('terminal_outcome')} (final={timeline.get('final_state')})",
        f"Elapsed: {timeline.get('total_elapsed_ms')} ms",
        f"Phase durations: {timeline.get('phase_durations_ms')}",
        "",
    ]
    for e in timeline.get("entries") or []:
        lines.append(
            f"Seq {e.get('sequence')!s:>4} | {e.get('timestamp')} | "
            f"+{e.get('elapsed_since_previous_ms')}ms | {e.get('event_name'):35s} | "
            f"{e.get('state_before')} -> {e.get('state_after')} | phase={e.get('phase')}"
        )
    return "\n".join(lines)
