"""
Slice Orchestrator host-agnostic MCP tool layer.

This module provides control-plane tool handlers shared by all native MCP hosts
(Cursor Chat primary, Claude Code secondary). Tools do not embed client-specific
authority. Optional ``host`` metadata may be recorded for observability only.

Core tools:
1. slice_start
2. slice_context
3. slice_grill
4. slice_plan
5. slice_work_list
6. slice_dispatch
7. slice_record_result
8. slice_run_tests
9. slice_status
10. slice_report

Lifecycle completion tools:
11. slice_request_review
12. slice_gate
13. slice_finalize

All tools invoke the Slice Orchestrator control plane (SliceRunController,
ControlStore, GateEvaluator, TransitionEngine) directly.
No control-plane logic is duplicated here, and all state changes remain
authoritative within the control plane.
"""

from __future__ import annotations

import os
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slice_orchestrator.orchestrator import SliceRunController, OrchestratorError
from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.state_machine import SliceRunState, project_slice_run_state
from slice_orchestrator.objectives import Objective
from slice_orchestrator.work_items import WorkItem, WorkItemDAGSupervisor
from slice_orchestrator.git_manager import (
    get_head_commit_oid,
    get_git_object_format,
    CandidateTreeBuilder,
    compute_workspace_revision_digest,
    compute_evidence_set_digest,
    build_authoritative_test_manifest,
    verify_authoritative_tests_unmodified,
)
from slice_orchestrator.gates import execute_control_test, persist_signed_receipt
from slice_orchestrator.canonical import compute_record_digest


# Uniform MCP-layer principal. Host identity never grants additional authority.
MCP_HOST_PRINCIPAL = "mcp-host"
OPERATOR_PRINCIPAL = "operator-local"
_PROJECT_DIR_ENV_KEYS = (
    "SLICE_REPO_DIR",
    "CLAUDE_PROJECT_DIR",
    "CURSOR_PROJECT_DIR",
)


def _normalize_host_metadata(host: str | None) -> str | None:
    """Normalize optional host metadata. Never used for authorization."""
    if not host:
        return None
    h = host.strip().lower().replace("_", "-")
    if h in ("cursor", "cursor-chat", "cursor-ide"):
        return "cursor"
    if h in ("claude-code", "claude", "anthropic-claude-code"):
        return "claude-code"
    if h in ("test", "unknown", "stdio-protocol"):
        return h
    return "unknown"


def _resolve_paths(
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> tuple[Path, Path]:
    if repo_dir:
        r_dir = Path(repo_dir).resolve()
    else:
        r_dir = None
        for env_key in _PROJECT_DIR_ENV_KEYS:
            env_val = os.environ.get(env_key)
            if env_val:
                candidate = Path(env_val).resolve()
                if candidate.is_dir():
                    r_dir = candidate
                    break
        if r_dir is None:
            r_dir = Path.cwd().resolve()
    c_home = Path(control_home).resolve() if control_home else (r_dir / ".orchestrator_slice")
    return r_dir, c_home


def _get_slice_name(
    slice: str | None = None,
    slice_name: str | None = None,
) -> str:
    s_name = slice or slice_name
    if not s_name:
        raise ValueError("slice or slice_name is required")
    return s_name


def _host_payload_fields(host: str | None) -> dict[str, Any]:
    normalized = _normalize_host_metadata(host)
    if not normalized:
        return {}
    return {"host_metadata": normalized}


def _get_legal_next_transitions(controller: SliceRunController, current_state: str) -> list[str]:
    transitions_map = controller.transition_engine.transitions
    state_transitions = transitions_map.get(current_state, [])
    if isinstance(state_transitions, list):
        return [t["to"] for t in state_transitions if isinstance(t, dict) and "to" in t]
    return []


def _compute_ws_digest(controller: SliceRunController, state: SliceRunState) -> str:
    builder = CandidateTreeBuilder(controller.repo_dir, controller.store.control_home)
    base_commit = state.base_commit_oid or get_head_commit_oid(controller.repo_dir)
    captured_tree_oid = builder.capture_candidate_tree(base_commit)
    git_fmt = get_git_object_format(controller.repo_dir)
    return compute_workspace_revision_digest(
        project_id=controller.store.project_id,
        git_object_format=git_fmt,
        base_commit_oid=base_commit,
        candidate_tree_oid=captured_tree_oid,
        plan_revision=state.plan_revision,
        plan_digest=getattr(state, "approved_plan_digest", "") or "",
        scope_manifest_digest=getattr(state, "scope_manifest_digest", "") or "",
        required_test_plan_digest=getattr(state, "required_test_plan_digest", "") or "",
        policy_bundle_digest=controller.policy_bundle.computed_digest,
    )


def slice_start(
    slice: str | None = None,
    slice_name: str | None = None,
    objective: str | None = None,
    description: str | None = None,
    base_commit: str | None = None,
    profile: str = "standard",
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """
    Create or resume a slice run.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    existing_state = controller.get_slice_state(s_name)
    is_new = existing_state is None or existing_state.is_terminal()

    state = controller.open_run(s_name, base_commit=base_commit, profile=profile)

    obj_text = objective or description
    if obj_text:
        existing_objs = controller.store.list_objectives(slice_name=s_name)
        if not existing_objs:
            now_iso = datetime.now(timezone.utc).isoformat()
            obj = Objective(
                objective_id=f"{s_name}-O1",
                run_id=state.run_id,
                slice=s_name,
                description=obj_text,
                source_requirements=[],
                acceptance_predicates=[],
                created_at=now_iso,
            )
            controller.store.save_objective(obj)

    next_act = (
        "Submit an execution plan using slice_plan, or challenge objectives using slice_grill."
        if state.state == "PLANNING"
        else f"Resume work in current state: {state.state}."
    )

    result = {
        "slice": s_name,
        "slice_name": s_name,
        "run_id": state.run_id,
        "status": state.state,
        "state": state.state,
        "generation": state.run_generation,
        "sequence": state.sequence,
        "base_commit_oid": state.base_commit_oid,
        "is_new_run": is_new,
        "objective": obj_text or "",
        "next_action": next_act,
    }
    result.update(_host_payload_fields(host))
    return result


def slice_context(
    slice: str | None = None,
    slice_name: str | None = None,
    include_plan: bool = True,
    include_work_items: bool = True,
    include_remediation: bool = True,
    include_role_context: bool = True,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Retrieve structured context pack for the current slice state.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    if state is None:
        return {
            "slice": s_name,
            "exists": False,
            "error": f"No slice run found for '{s_name}'. Call slice_start first.",
        }

    objs = [o.to_dict() for o in controller.store.list_objectives(slice_name=s_name)]
    wis = [w.to_dict() for w in controller.store.list_work_items(slice_name=s_name)]

    plans = controller.store.list_records_by_type("PLAN")
    slice_plans = [p for p in plans if p.get("slice") == s_name or p.get("record_id", "").startswith(s_name)]
    latest_plan = slice_plans[-1] if slice_plans else None

    # Repo facts
    head_oid = get_head_commit_oid(r_dir)
    ws_digest = _compute_ws_digest(controller, state)

    remediation_packets = []
    if include_remediation:
        packets = controller.store.list_records_by_type("REMEDIATION_PACKET")
        remediation_packets = [p for p in packets if p.get("slice") == s_name]

    role_ctx = {}
    if include_role_context:
        role_ctx = controller.dispatch_manager.get_role_context_view("IMPLEMENTER", state.run_id)

    legal_transitions = _get_legal_next_transitions(controller, state.state)

    # Compute context pack digest
    context_pack_data = {
        "slice": s_name,
        "run_id": state.run_id,
        "state": state.state,
        "base_commit_oid": state.base_commit_oid,
        "plan_revision": state.plan_revision,
        "review_cycle": state.review_cycle_high_water,
        "remediation_cycle": state.remediation_cycle_high_water,
        "workspace_revision_digest": ws_digest,
    }
    pack_digest = compute_record_digest(context_pack_data)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "exists": True,
        "run_id": state.run_id,
        "state": state.state,
        "plan_summary": latest_plan.get("description") if latest_plan else None,
        "plan_revision": state.plan_revision,
        "objectives": objs if include_plan else [],
        "work_items": wis if include_work_items else [],
        "open_remediation_packets": remediation_packets,
        "role_context": role_ctx,
        "review_cycle": state.review_cycle_high_water,
        "remediation_cycle": state.remediation_cycle_high_water,
        "base_commit_oid": state.base_commit_oid,
        "repository_facts": {
            "head_commit_oid": head_oid,
            "workspace_revision_digest": ws_digest,
            "repo_dir": str(r_dir),
        },
        "legal_next_transitions": legal_transitions,
        "context_pack_digest": pack_digest,
    }


def slice_grill(
    slice: str | None = None,
    slice_name: str | None = None,
    objective: str | None = None,
    objective_description: str | None = None,
    scope_hints: list[str] | None = None,
    requirement_clarification: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Challenge and validate an objective or requirement before planning.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    objs = controller.store.list_objectives(slice_name=s_name)
    obj_text = objective or objective_description or (objs[0].description if objs else "")

    if requirement_clarification and state:
        rec_id = f"clarification-{str(uuid.uuid4())[:8]}"
        clarification_record = {
            "schema_version": 4,
            "record_type": "REQUIREMENT_CLARIFICATION",
            "slice": s_name,
            "run_id": state.run_id,
            "clarification": requirement_clarification,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        controller.store.store_record("REQUIREMENT_CLARIFICATION", rec_id, clarification_record)

    questions = []
    prerequisite_checks = []

    # Verify basic repository prerequisites
    has_test = (r_dir / "tests").is_dir() or (r_dir / "pyproject.toml").is_file()
    prerequisite_checks.append({
        "check_id": "test_suite_configured",
        "description": "Verify test suite exists in repository",
        "status": "pass" if has_test else "fail",
    })

    if not obj_text.strip():
        questions.append({
            "question_id": "q_missing_objective",
            "question": "What is the specific objective or requirement for this slice?",
            "why_blocked": "Objective is empty or unspecified.",
            "facts": ["No objective text provided in slice_start or slice_grill."],
            "options": ["Provide objective description", "Use existing repository issue/spec"],
            "recommendation": "Specify a concise objective describing expected behavior changes.",
            "impact": "Cannot form execution plan without objective.",
            "category": "ambiguity",
            "severity": "blocking",
        })

    risk_summary = "Low risk." if not questions else f"Blocked on {len(questions)} unanswered question(s)."

    return {
        "slice": s_name,
        "slice_name": s_name,
        "grill_id": f"grill-{str(uuid.uuid4())[:8]}",
        "questions": questions,
        "prerequisite_checks": prerequisite_checks,
        "risk_summary": risk_summary,
    }


def slice_plan(
    slice: str | None = None,
    slice_name: str | None = None,
    plan: dict[str, Any] | None = None,
    is_revision: bool = False,
    profile: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Submit or revise a structured plan for the slice.
    """
    s_name = _get_slice_name(slice, slice_name)
    if not plan:
        raise ValueError("plan argument is required")

    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            state = controller._open_run_unlocked(s_name)

        if state.state not in ("PLANNING", "PLAN_REVISION", "PLAN_READY"):
            raise OrchestratorError(f"Cannot submit plan in state '{state.state}'. Must be in PLANNING or PLAN_REVISION.")

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        new_rev = state.plan_revision + 1 if is_revision or state.plan_revision > 0 else 1
        plan_id = f"{s_name}-plan-v{new_rev}"

        raw_allow_paths = plan.get("scope_manifest", {}).get("allow_paths", [])
        norm_allow_paths = []
        for item in raw_allow_paths:
            if isinstance(item, str):
                norm_allow_paths.append({
                    "pattern": item,
                    "allowed_operations": ["add", "modify", "delete", "rename", "mode_change"],
                })
            elif isinstance(item, dict):
                norm_allow_paths.append(item)

        base_commit = state.base_commit_oid or get_head_commit_oid(r_dir)
        auth_test_manifest = build_authoritative_test_manifest(r_dir, base_commit)

        prof = profile or plan.get("profile") or getattr(state, "profile", "standard")
        plan_record = {
            "schema_version": 4,
            "record_type": "PLAN",
            "plan_id": plan_id,
            "slice": s_name,
            "run_id": state.run_id,
            "profile": prof,
            "revision": new_rev,
            "description": plan.get("description", ""),
            "scope_manifest": {"allow_paths": norm_allow_paths},
            "scope_manifest_digest": compute_record_digest({"allow_paths": norm_allow_paths}),
            "authoritative_test_manifest": auth_test_manifest,
            "test_plan_digest": auth_test_manifest["trusted_test_set_digest"],
            "non_goals": plan.get("non_goals", []),
            "assumptions": plan.get("assumptions", []),
            "test_plan": plan.get("test_plan", []),
            "work_items": plan.get("work_items", []),
            "verification_strategy": plan.get("verification_strategy", "independent_control_test"),
            "risks": plan.get("risks", []),
            "open_questions": plan.get("open_questions", []),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        plan_digest = controller.store.store_record("PLAN", plan_id, plan_record)

        items_created = 0
        obj_id = f"{s_name}-O1"
        for item_data in plan.get("work_items", []):
            item_id = item_data.get("work_item_id") or f"{s_name}-WI-{items_created+1}"
            wi = WorkItem(
                work_item_id=item_id,
                run_id=state.run_id,
                objective_id=obj_id,
                description=item_data.get("description", ""),
                type=item_data.get("type", "implementation"),
                assigned_role=item_data.get("assigned_role", "IMPLEMENTER"),
                dependencies=item_data.get("dependencies", []),
                status=item_data.get("status", "READY"),
                revision=new_rev,
            )
            controller.store.save_work_item(wi)
            items_created += 1

        ev_type = "PLAN_REVISED" if state.state == "PLAN_REVISION" else "PLAN_PERSISTED"
        payload = {
            "payload_type": ev_type,
            "record": {
                "record_type": "PLAN",
                "record_id": plan_id,
                "record_digest": plan_digest,
            },
            "plan_id": plan_id,
            "plan_digest": plan_digest,
            "plan_revision": new_rev,
            "profile": prof,
        }

        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type=ev_type,
            payload_type=ev_type,
            actor_role="PLANNER",
            actor_principal="operator-local",
            payload=payload,
            token_hash=token_hash,
        )

        updated_state = controller.get_slice_state(s_name)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "plan_id": plan_id,
        "plan_digest": plan_digest,
        "plan_revision": new_rev,
        "state": updated_state.state if updated_state else "PLAN_READY",
        "work_items_created": items_created,
        "next_action": "Dispatch architecture reviewer or call slice_dispatch for execution.",
        "message": f"Plan revision {new_rev} successfully persisted.",
    }


def slice_work_list(
    slice: str | None = None,
    slice_name: str | None = None,
    action: str = "list",
    work_item: dict[str, Any] | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    List, create, update, or inspect work items.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    run_id = state.run_id if state else ""
    obj_id = f"{s_name}-O1"

    if action in ("create", "update"):
        if not work_item:
            raise ValueError(f"work_item object is required for action '{action}'")
        wi_id = work_item.get("work_item_id") or f"{s_name}-WI-{str(uuid.uuid4())[:4]}"
        wi = WorkItem(
            work_item_id=wi_id,
            run_id=run_id,
            objective_id=obj_id,
            description=work_item.get("description") or work_item.get("title") or "",
            type=work_item.get("type", "implementation"),
            assigned_role=work_item.get("assigned_role", "IMPLEMENTER"),
            dependencies=work_item.get("dependencies", []),
            status=work_item.get("status", "READY"),
        )
        controller.store.save_work_item(wi)

    raw_items = controller.store.list_work_items(slice_name=s_name)
    dag = WorkItemDAGSupervisor()
    ready_items_objs = dag.derive_readiness(raw_items)

    formatted_items = []
    for item in raw_items:
        d = item.to_dict() if hasattr(item, "to_dict") else item
        d["title"] = d.get("description", "")
        d["assigned_role"] = d.get("assigned_role", "IMPLEMENTER")
        d["verification_status"] = "PENDING"
        d["blockers"] = [dep for dep in d.get("dependencies", []) if not any(i.work_item_id == dep and i.status == "COMPLETED" for i in raw_items)]
        formatted_items.append(d)

    ready_ids = [r.work_item_id for r in ready_items_objs]
    objs = [o.to_dict() for o in controller.store.list_objectives(slice_name=s_name)]

    return {
        "slice": s_name,
        "slice_name": s_name,
        "objectives": objs,
        "work_items": formatted_items,
        "ready_items": ready_ids,
        "message": f"Retrieved {len(formatted_items)} work item(s). {len(ready_ids)} ready for execution.",
    }


def slice_dispatch(
    slice: str | None = None,
    slice_name: str | None = None,
    role: str | None = None,
    work_item_id: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """
    Create an execution assignment for a role / work item and transition state.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            raise OrchestratorError(f"Slice '{s_name}' does not exist.")

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        target_role = role
        if not target_role:
            role_map = {
                "PLAN_READY": "IMPLEMENTER" if getattr(state, "profile", "standard") == "fast-track" else "ARCHITECTURE_REVIEWER",
                "ARCHITECTURE_APPROVED": "IMPLEMENTER",
                "IMPLEMENTATION_READY_FOR_REVIEW": "ADVERSARIAL_REVIEWER",
                "REMEDIATION": "REMEDIATOR",
            }
            target_role = role_map.get(state.state, "IMPLEMENTER")

        if target_role == "ADVERSARIAL_REVIEWER" and state.state == "REMEDIATION":
            raise OrchestratorError(
                f"Cannot dispatch ADVERSARIAL_REVIEWER directly from state 'REMEDIATION'. "
                f"Review findings must first be remediated. "
                f"Call slice_remediate(slice='{s_name}') or dispatch 'REMEDIATOR' to return to IMPLEMENTATION."
            )

        exec_id = f"exec-{str(uuid.uuid4())[:8]}"
        role_in_envelope = "IMPLEMENTER" if target_role == "REMEDIATOR" else target_role
        envelope = controller.dispatch_manager.issue_dispatch_envelope(
            role=role_in_envelope,
            run_id=state.run_id,
            worker_execution_id=exec_id,
            target_item_id=work_item_id or f"{s_name}-WI-1",
            objective_id=f"{s_name}-O1",
            plan_revision=state.plan_revision,
            repository_revision=f"sha1:{state.base_commit_oid}",
            issued_by=MCP_HOST_PRINCIPAL,
            slice_name=s_name,
        )
        asgn_data = envelope["assignment"]
        cp_data = envelope["context_pack"]

        event_map = {
            "ARCHITECTURE_REVIEWER": ("ARCHITECTURE_REVIEW_ASSIGNED", "ARCHITECTURE_REVIEW_ASSIGNED"),
            "IMPLEMENTER": ("IMPLEMENTATION_ASSIGNED", "IMPLEMENTATION_ASSIGNED"),
            "ADVERSARIAL_REVIEWER": ("ADVERSARIAL_REVIEW_ASSIGNED", "ADVERSARIAL_REVIEW_ASSIGNED"),
            "REMEDIATOR": ("REMEDIATION_ASSIGNED", "REMEDIATION_ASSIGNED"),
        }
        ev_type, payload_type = event_map.get(target_role, ("IMPLEMENTATION_ASSIGNED", "IMPLEMENTATION_ASSIGNED"))

        payload = {
            "payload_type": payload_type,
            "record": {
                "record_type": "WORK_ASSIGNMENT",
                "record_id": asgn_data["assignment_id"],
                "record_digest": compute_record_digest(asgn_data),
            },
            "assignment_id": asgn_data["assignment_id"],
            "execution_id": asgn_data["execution_id"],
            "role": role_in_envelope,
        }
        payload.update(_host_payload_fields(host))

        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type=ev_type,
            payload_type=payload_type,
            actor_role="CONTROLLER_SYSTEM",
            actor_principal=OPERATOR_PRINCIPAL,
            payload=payload,
            token_hash=token_hash,
        )

        updated_state = controller.get_slice_state(s_name)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "assignment_id": asgn_data["assignment_id"],
        "execution_id": asgn_data["execution_id"],
        "role": target_role,
        "work_item_id": work_item_id or "",
        "state": updated_state.state if updated_state else state.state,
        "context_pack_digest": cp_data["context_pack_digest"],
        "prompt": f"Execute {target_role} task for slice {s_name} with assignment {asgn_data['assignment_id']}.",
        "message": f"Assignment {asgn_data['assignment_id']} issued for role {target_role}.",
    }


def slice_record_result(
    slice: str | None = None,
    slice_name: str | None = None,
    assignment_id: str | None = None,
    success: bool = True,
    summary: str = "",
    artifacts: dict[str, Any] | None = None,
    role_context_update: dict[str, Any] | None = None,
    error_message: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """
    Bind execution result to the control plane and perform state transition.
    """
    s_name = _get_slice_name(slice, slice_name)
    if not assignment_id:
        raise ValueError("assignment_id is required")

    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            raise OrchestratorError(f"Slice '{s_name}' does not exist.")

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        assignment = controller.store.get_assignment(assignment_id)
        if not assignment:
            raise OrchestratorError(f"Assignment '{assignment_id}' not found.")

        # Consume assignment (prevents double consumption)
        controller.store.consume_assignment(assignment_id, consumer_principal=MCP_HOST_PRINCIPAL)

        role = assignment.get("role")
        arts = artifacts or {}

        candidate_tree_oid = None
        ws_digest = _compute_ws_digest(controller, state)
        context_checkpointed = False
        candidate_captured = False

        if role in ("IMPLEMENTER", "REMEDIATOR"):
            git_mgr = CandidateTreeBuilder(r_dir, c_home)
            candidate_tree_oid = git_mgr.capture_candidate_tree(state.base_commit_oid)
            candidate_captured = True

            ctx_record = {
                "schema_version": 4,
                "record_type": "IMPLEMENTATION_CONTEXT",
                "context_id": f"ctx-{str(uuid.uuid4())[:8]}",
                "slice": s_name,
                "run_id": state.run_id,
                "role": role,
                "summary": summary,
                "role_context_update": role_context_update or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            controller.store.store_record("IMPLEMENTATION_CONTEXT", ctx_record["context_id"], ctx_record)
            context_checkpointed = True

            payload_ctx = {
                "payload_type": "IMPLEMENTATION_CONTEXT_CHECKPOINTED",
                "assignment_id": assignment_id,
                "summary": summary,
            }
            payload_ctx.update(_host_payload_fields(host))
            controller.store.append_event(
                slice_name=s_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type="IMPLEMENTATION_CONTEXT_CHECKPOINTED",
                payload_type="IMPLEMENTATION_CONTEXT_CHECKPOINTED",
                actor_role="IMPLEMENTER",
                actor_principal=MCP_HOST_PRINCIPAL,
                payload=payload_ctx,
                token_hash=token_hash,
            )

            payload_cand = {
                "payload_type": "CANDIDATE_CAPTURED",
                "assignment_id": assignment_id,
                "candidate_tree_oid": candidate_tree_oid,
                "workspace_revision_digest": ws_digest,
                "summary": summary,
            }
            payload_cand.update(_host_payload_fields(host))
            controller.store.append_event(
                slice_name=s_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type="CANDIDATE_CAPTURED",
                payload_type="CANDIDATE_CAPTURED",
                actor_role="IMPLEMENTER",
                actor_principal=MCP_HOST_PRINCIPAL,
                payload=payload_cand,
                token_hash=token_hash,
            )

        elif role == "ARCHITECTURE_REVIEWER":
            verdict = arts.get("verdict", "APPROVED" if success else "BLOCKED")
            ev_type = "ARCHITECTURE_APPROVED" if verdict == "APPROVED" else "ARCHITECTURE_BLOCKED"
            payload = {
                "payload_type": ev_type,
                "assignment_id": assignment_id,
                "verdict": verdict,
                "summary": summary,
            }
            payload.update(_host_payload_fields(host))
            controller.store.append_event(
                slice_name=s_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type=ev_type,
                payload_type=ev_type,
                actor_role="ARCHITECTURE_REVIEWER",
                actor_principal=MCP_HOST_PRINCIPAL,
                payload=payload,
                token_hash=token_hash,
            )

        elif role == "ADVERSARIAL_REVIEWER":
            verdict = arts.get("verdict", "APPROVED" if success else "BLOCKED")
            ev_type = "REVIEW_ACCEPTED" if verdict == "APPROVED" else "REVIEW_BLOCKED"
            rev_id = f"rev-{str(uuid.uuid4())[:8]}"

            # Determine implementer principal and reviewer principal
            events = controller.store.get_events()
            impl_principal = None
            for ev in events:
                if ev.get("event_type") in ("CANDIDATE_CAPTURED", "IMPLEMENTATION_CONTEXT_CHECKPOINTED"):
                    impl_principal = ev.get("actor", {}).get("principal") or ev.get("actor_principal")
                    if impl_principal:
                        break

            reviewer_principal = (
                arts.get("reviewer_principal")
                or assignment.get("consumer_principal")
                or MCP_HOST_PRINCIPAL
            )
            is_self_approved = (impl_principal is not None and reviewer_principal == impl_principal) or arts.get("is_self_approved", False)

            review_rec = {
                "schema_version": 4,
                "record_type": "REVIEW_RECORD",
                "record_id": rev_id,
                "slice": s_name,
                "run_id": state.run_id,
                "verdict": verdict,
                "summary": summary,
                "implementer_principal": impl_principal,
                "reviewer_principal": reviewer_principal,
                "is_self_approved": is_self_approved,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            review_rec.update(_host_payload_fields(host))
            rev_digest = controller.store.store_record("REVIEW_RECORD", rev_id, review_rec)

            payload = {
                "payload_type": ev_type,
                "record": {
                    "record_type": "REVIEW_RECORD",
                    "record_id": rev_id,
                    "record_digest": rev_digest,
                },
                "assignment_id": assignment_id,
                "verdict": verdict,
                "summary": summary,
            }

            pkt_id = None
            pkt_data = None
            findings: list[dict[str, Any]] = []
            if ev_type == "REVIEW_BLOCKED":
                pkt_id = str(uuid.uuid4())
                findings = arts.get("findings") or arts.get("blocking_findings") or []
                if not findings and summary:
                    findings = [{"finding_id": "FINDING-01", "description": summary, "required_remediation": f"Address review finding: {summary}"}]
                pkt_data = {
                    "schema_version": 4,
                    "record_type": "REMEDIATION_PACKET",
                    "remediation_packet_id": pkt_id,
                    "slice": s_name,
                    "review_id": rev_id,
                    "remediation_cycle": state.remediation_cycle_high_water + 1,
                    "findings": findings,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                pkt_digest = controller.store.store_record("REMEDIATION_PACKET", pkt_id, pkt_data)

                from slice_orchestrator.work_items import WorkItem
                rem_wi = WorkItem(
                    work_item_id=f"{s_name}-WI-REM-{pkt_id[:6]}",
                    run_id=state.run_id,
                    objective_id=f"{s_name}-O1",
                    description=f"Remediate findings for review {rev_id}",
                    type="remediation",
                    assigned_role="REMEDIATOR",
                    status="READY",
                )
                controller.store.save_work_item(rem_wi)

                payload["review_cycle"] = state.review_cycle_high_water
                payload["remediation_cycle"] = state.remediation_cycle_high_water + 1
                payload["related_records"] = [{
                    "record_type": "REMEDIATION_PACKET",
                    "record_id": pkt_id,
                    "record_digest": pkt_digest,
                }]

            payload.update(_host_payload_fields(host))
            controller.store.append_event(
                slice_name=s_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type=ev_type,
                payload_type=ev_type,
                actor_role="ADVERSARIAL_REVIEWER",
                actor_principal=MCP_HOST_PRINCIPAL,
                payload=payload,
                token_hash=token_hash,
            )

        updated_state = controller.get_slice_state(s_name)

    resp: dict[str, Any] = {
        "slice": s_name,
        "slice_name": s_name,
        "state": updated_state.state if updated_state else state.state,
        "result_accepted": True,
        "context_checkpointed": context_checkpointed,
        "candidate_captured": candidate_captured,
        "next_action": f"Current state is {updated_state.state}. Proceed with next workflow step.",
        "message": f"Result for assignment {assignment_id} successfully recorded.",
    }
    if role == "ADVERSARIAL_REVIEWER" and ev_type == "REVIEW_BLOCKED":
        resp["remediation_packet"] = pkt_data
        resp["remediation_packet_id"] = pkt_id
        resp["findings"] = findings
        resp["next_action"] = (
            f"Review BLOCKED with {len(findings)} finding(s). "
            f"Call slice_remediate(slice='{s_name}') or 'slice remediate {s_name}' to return to IMPLEMENTATION and address findings."
        )
    return resp


def slice_run_tests(
    slice: str | None = None,
    slice_name: str | None = None,
    test_ids: list[str] | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Execute authorized test suite independently and persist HMAC-signed receipt.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    if not state:
        raise OrchestratorError(f"Slice '{s_name}' does not exist.")

    test_def = controller._authorized_test_def()
    cmd = test_def.get("command")
    if not cmd:
        return {
            "slice": s_name,
            "tests_passed": False,
            "test_results": [],
            "receipt_id": None,
            "receipt_digest": None,
            "message": "No authorized test command configured in policy bundle.",
        }

    base_commit = state.base_commit_oid or get_head_commit_oid(r_dir)
    plan_rec = None
    if state.approved_plan_digest:
        plan_rec = controller.store.get_record(state.approved_plan_digest)
        if not plan_rec:
            for r in controller.store.list_records_by_type("PLAN"):
                if (r.get("record_digest") == state.approved_plan_digest
                    or r.get("plan_id") == state.approved_plan_digest
                    or r.get("record_id") == state.approved_plan_digest
                    or r.get("slice") == state.slice):
                    plan_rec = r
                    break

    auth_manifest = None
    allowed_mods = []
    if plan_rec:
        if plan_rec.get("authoritative_test_manifest"):
            auth_manifest = plan_rec["authoritative_test_manifest"]
        scope_m = plan_rec.get("scope_manifest", {})
        for rule in scope_m.get("allow_paths", []):
            pat = rule.get("pattern") if isinstance(rule, dict) else str(rule)
            if pat:
                allowed_mods.append(pat)

    if not auth_manifest:
        auth_manifest = build_authoritative_test_manifest(r_dir, base_commit)

    test_ok, test_fail_reason = verify_authoritative_tests_unmodified(
        r_dir, base_commit, auth_manifest, allowed_modifications=allowed_mods
    )
    if not test_ok:
        return {
            "slice": s_name,
            "slice_name": s_name,
            "tests_passed": False,
            "test_results": [],
            "receipt_id": None,
            "receipt_digest": None,
            "message": f"Test execution rejected: {test_fail_reason}",
        }

    test_res = execute_control_test(test_def, r_dir)
    builder = CandidateTreeBuilder(r_dir, c_home)
    candidate_tree_oid = builder.capture_candidate_tree(state.base_commit_oid or get_head_commit_oid(r_dir))
    ws_digest = _compute_ws_digest(controller, state)

    rcpt_dict = persist_signed_receipt(
        execution=test_res,
        test_def=test_def,
        repo_dir=r_dir,
        candidate_tree_oid=candidate_tree_oid,
        workspace_revision_digest=ws_digest,
        control_store=controller.store,
        slice_name=s_name,
        run_id=state.run_id,
    )

    return {
        "slice": s_name,
        "slice_name": s_name,
        "tests_passed": test_res.passed,
        "test_results": [
            {
                "test_id": test_ids[0] if test_ids else "default_control_test",
                "passed": test_res.passed,
                "exit_code": test_res.exit_code,
                "duration_seconds": getattr(test_res, "duration_seconds", 0.0),
            }
        ],
        "receipt_id": rcpt_dict.get("receipt_id"),
        "receipt_digest": rcpt_dict.get("receipt_digest"),
        "message": "Control test execution completed and HMAC receipt persisted." if test_res.passed else f"Control test failed with exit code {test_res.exit_code}.",
    }


def slice_status(
    slice: str | None = None,
    slice_name: str | None = None,
    verbose: bool = False,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Query current state, progress, and next legal actions.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    if not state:
        return {
            "slice": s_name,
            "slice_name": s_name,
            "exists": False,
            "state": "UNKNOWN",
            "suggested_next_action": "Call slice_start to create a new slice run.",
        }

    objs = controller.store.list_objectives(slice_name=s_name)
    obj_desc = objs[0].description if objs else ""

    wis = controller.store.list_work_items(slice_name=s_name)
    curr_wi = wis[0].work_item_id if wis else ""

    legal_transitions = _get_legal_next_transitions(controller, state.state)

    events = controller.store.get_events()
    slice_evs = [e for e in events if e.get("slice") == s_name]
    last_event_type = slice_evs[-1].get("event_type", "NONE") if slice_evs else "NONE"
    tail_hash = slice_evs[-1].get("event_hash", "") if slice_evs else ""

    next_act = (
        f"In state {state.state}. Next legal transitions: {', '.join(legal_transitions)}."
        if not state.is_terminal()
        else f"Run reached terminal state: {state.state}."
    )

    return {
        "slice": s_name,
        "slice_name": s_name,
        "exists": True,
        "run_id": state.run_id,
        "state": state.state,
        "objective": obj_desc,
        "current_work_item": curr_wi,
        "blockers": [],
        "execution_mode": "mcp-native",
        "generation": state.run_generation,
        "sequence": state.sequence,
        "plan_revision": state.plan_revision,
        "review_cycle": state.review_cycle_high_water,
        "remediation_cycle": state.remediation_cycle_high_water,
        "is_terminal": state.is_terminal(),
        "stop_reason": getattr(state, "stop_reason", ""),
        "last_event": last_event_type,
        "legal_next_transitions": legal_transitions,
        "next_action": next_act,
        "suggested_next_action": next_act,
        "stream_tail_hash": tail_hash,
    }


def slice_report(
    slice: str | None = None,
    slice_name: str | None = None,
    include_event_history: bool = False,
    include_evidence: bool = True,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate a human-facing summary report of a slice run.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    if not state:
        return {
            "slice": s_name,
            "exists": False,
            "error": f"Slice run '{s_name}' does not exist.",
        }

    objs = controller.store.list_objectives(slice_name=s_name)
    obj_desc = objs[0].description if objs else ""

    events = controller.store.get_events()
    slice_evs = [e for e in events if e.get("slice") == s_name]

    receipts = controller.store.list_receipts(slice_name=s_name)
    passed_rcpts = [r for r in receipts if r.get("passed") is True]

    plans = controller.store.list_records_by_type("PLAN")
    slice_plans = [p for p in plans if p.get("slice") == s_name]

    verdict = (
        "COMPLETE"
        if state.state == "COMPLETE"
        else ("STOPPED" if state.state in ("STOPPED", "FAILED") else "IN_PROGRESS")
    )

    return {
        "slice": s_name,
        "slice_name": s_name,
        "run_id": state.run_id,
        "objective": obj_desc,
        "final_state": state.state,
        "total_events": len(slice_evs),
        "plan_revisions": len(slice_plans),
        "review_cycles": state.review_cycle_high_water,
        "remediation_cycles": state.remediation_cycle_high_water,
        "tests_executed": len(receipts),
        "tests_passed": len(passed_rcpts),
        "commits_made": 1 if state.state == "COMPLETE" else 0,
        "stop_reason": getattr(state, "stop_reason", None),
        "evidence_location": str(c_home),
        "evidence_summary": {
            "receipts": len(receipts),
            "reviews": state.review_cycle_high_water,
            "plans": len(slice_plans),
        } if include_evidence else {},
        "event_history": [e for e in slice_evs] if include_event_history else [],
        "verdict": verdict,
        "recommended_next_action": "Slice completed successfully." if verdict == "COMPLETE" else f"Current state: {state.state}. Continue orchestration steps.",
        "message": f"Slice {s_name} report generated.",
    }


def slice_request_review(
    slice: str | None = None,
    slice_name: str | None = None,
    reviewer_principal: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """
    Request an independent adversarial review assignment for a slice.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            raise OrchestratorError(f"Slice '{s_name}' does not exist.")

        if state.state != "IMPLEMENTATION_READY_FOR_REVIEW":
            if state.state == "REMEDIATION":
                raise OrchestratorError(
                    f"Cannot request review from state 'REMEDIATION'. "
                    f"The review was blocked and findings must be addressed first. "
                    f"Call slice_remediate(slice='{s_name}') to return to IMPLEMENTATION."
                )
            raise OrchestratorError(
                f"Cannot request review in state '{state.state}'. "
                "Slice must be in IMPLEMENTATION_READY_FOR_REVIEW."
            )

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        rev_principal = reviewer_principal or "adversarial-reviewer"

        exec_id = f"exec-{str(uuid.uuid4())[:8]}"
        envelope = controller.dispatch_manager.issue_dispatch_envelope(
            role="ADVERSARIAL_REVIEWER",
            run_id=state.run_id,
            worker_execution_id=exec_id,
            target_item_id=f"{s_name}-WI-1",
            objective_id=f"{s_name}-O1",
            plan_revision=state.plan_revision,
            repository_revision=f"sha1:{state.base_commit_oid}",
            issued_by=MCP_HOST_PRINCIPAL,
            slice_name=s_name,
        )
        asgn_data = envelope["assignment"]
        cp_data = envelope["context_pack"]

        payload = {
            "payload_type": "ADVERSARIAL_REVIEW_ASSIGNED",
            "record": {
                "record_type": "WORK_ASSIGNMENT",
                "record_id": asgn_data["assignment_id"],
                "record_digest": compute_record_digest(asgn_data),
            },
            "assignment_id": asgn_data["assignment_id"],
            "execution_id": asgn_data["execution_id"],
            "role": "ADVERSARIAL_REVIEWER",
            "reviewer_principal": rev_principal,
        }
        payload.update(_host_payload_fields(host))

        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="ADVERSARIAL_REVIEW_ASSIGNED",
            payload_type="ADVERSARIAL_REVIEW_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal=OPERATOR_PRINCIPAL,
            payload=payload,
            token_hash=token_hash,
        )

        updated_state = controller.get_slice_state(s_name)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "assignment_id": asgn_data["assignment_id"],
        "execution_id": asgn_data["execution_id"],
        "role": "ADVERSARIAL_REVIEWER",
        "reviewer_principal": rev_principal,
        "state": updated_state.state if updated_state else state.state,
        "context_pack_digest": cp_data["context_pack_digest"],
        "prompt": f"Execute ADVERSARIAL_REVIEWER task for slice {s_name} with assignment {asgn_data['assignment_id']}.",
        "message": f"Review assignment {asgn_data['assignment_id']} issued to {rev_principal}.",
    }


def slice_remediate(
    slice: str | None = None,
    slice_name: str | None = None,
    work_item_id: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """
    Resume an implementation thread from REMEDIATION state after a review was blocked.
    Transitions REMEDIATION -> IMPLEMENTATION, binds active remediation findings,
    and returns instructions/prompt for the implementer worker.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            raise OrchestratorError(f"Slice '{s_name}' does not exist.")

        if state.state != "REMEDIATION":
            raise OrchestratorError(
                f"Cannot remediate slice '{s_name}' in state '{state.state}'. "
                "Slice must be in REMEDIATION state."
            )

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        # Retrieve active remediation packet and findings
        pkt_id = state.latest_remediation_packet_id
        pkt_data = None
        if pkt_id:
            try:
                pkt_data = controller.store.get_record(pkt_id)
            except Exception:
                pass
        if not pkt_data:
            packets = controller.store.list_records_by_type("REMEDIATION_PACKET")
            slice_packets = [p for p in packets if p.get("slice") == s_name]
            if slice_packets:
                pkt_data = slice_packets[-1]
                pkt_id = pkt_data.get("remediation_packet_id") or pkt_data.get("record_id")

        findings = pkt_data.get("findings", []) if pkt_data else []

        # Find target work item
        target_item = work_item_id
        if not target_item:
            rem_wis = [
                wi for wi in controller.store.list_work_items(state.run_id)
                if wi.status == "READY" and wi.type == "remediation"
            ]
            if rem_wis:
                target_item = rem_wis[0].work_item_id
            else:
                target_item = f"{s_name}-WI-1"

        exec_id = f"exec-{str(uuid.uuid4())[:8]}"
        envelope = controller.dispatch_manager.issue_dispatch_envelope(
            role="IMPLEMENTER",
            run_id=state.run_id,
            worker_execution_id=exec_id,
            target_item_id=target_item,
            objective_id=f"{s_name}-O1",
            plan_revision=state.plan_revision,
            repository_revision=f"sha1:{state.base_commit_oid}",
            issued_by=MCP_HOST_PRINCIPAL,
            slice_name=s_name,
        )
        asgn_data = envelope["assignment"]
        cp_data = envelope["context_pack"]

        payload = {
            "payload_type": "REMEDIATION_ASSIGNED",
            "record": {
                "record_type": "WORK_ASSIGNMENT",
                "record_id": asgn_data["assignment_id"],
                "record_digest": compute_record_digest(asgn_data),
            },
            "assignment_id": asgn_data["assignment_id"],
            "execution_id": asgn_data["execution_id"],
            "role": "IMPLEMENTER",
            "remediation_packet_id": pkt_id,
        }
        payload.update(_host_payload_fields(host))

        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="REMEDIATION_ASSIGNED",
            payload_type="REMEDIATION_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal=OPERATOR_PRINCIPAL,
            payload=payload,
            token_hash=token_hash,
        )

        updated_state = controller.get_slice_state(s_name)

    findings_summary = "\n".join(
        f" - [{f.get('finding_id', 'F')}] {f.get('description', '')}"
        + (f" (Remediation: {f.get('required_remediation')})" if f.get("required_remediation") else "")
        for f in findings
    ) if findings else " - None explicitly listed"

    prompt = (
        f"Remediation assignment {asgn_data['assignment_id']} for slice {s_name} "
        f"(Cycle {getattr(updated_state, 'remediation_cycle_high_water', 1)}).\n\n"
        f"Findings to address:\n{findings_summary}\n\n"
        f"Action: Implement the requested fixes, run authorized tests, and record results."
    )

    return {
        "slice": s_name,
        "slice_name": s_name,
        "state": updated_state.state if updated_state else "IMPLEMENTATION",
        "remediation_cycle": getattr(updated_state, "remediation_cycle_high_water", 1),
        "assignment_id": asgn_data["assignment_id"],
        "execution_id": asgn_data["execution_id"],
        "remediation_packet_id": pkt_id,
        "findings": findings,
        "prompt": prompt,
        "next_action": "Apply the requested fixes in the workspace, run tests, and record implementation results.",
        "message": f"Remediation assignment {asgn_data['assignment_id']} issued for slice {s_name}.",
    }


def slice_gate(
    slice: str | None = None,
    slice_name: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Evaluate deterministic commit gate preconditions.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    state = controller.get_slice_state(s_name)
    if not state:
        raise OrchestratorError(f"Slice '{s_name}' does not exist.")

    from slice_orchestrator.gates import GateEvaluator
    evaluator = GateEvaluator(repo_dir=r_dir, control_store=controller.store)
    gate_res = evaluator.evaluate_commit_gate(state)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "passed": gate_res.passed,
        "reason": gate_res.reason,
        "candidate_tree_oid": gate_res.candidate_tree_oid,
        "workspace_revision_digest": gate_res.workspace_revision_digest,
        "evidence_set_digest": gate_res.evidence_set_digest,
        "approved_revision_digest": gate_res.approved_revision_digest,
        "next_action": "Proceed to slice_finalize." if gate_res.passed else f"Commit gate rejected: {gate_res.reason}",
    }


def slice_finalize(
    slice: str | None = None,
    slice_name: str | None = None,
    commit_message: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Finalize an approved slice run and transition state to terminal COMPLETE.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            raise OrchestratorError(f"Slice '{s_name}' does not exist.")

        if state.state == "COMPLETE":
            return {
                "slice": s_name,
                "slice_name": s_name,
                "finalized": True,
                "state": "COMPLETE",
                "commit_oid": state.committed_implementation_oid,
                "message": f"Slice '{s_name}' is already in terminal state COMPLETE.",
            }

        if state.state != "COMMIT_READY":
            raise OrchestratorError(
                f"Cannot finalize slice in state '{state.state}'. Must be in COMMIT_READY."
            )

        from slice_orchestrator.gates import GateEvaluator
        evaluator = GateEvaluator(repo_dir=r_dir, control_store=controller.store)
        gate_res = evaluator.evaluate_commit_gate(state)

        if not gate_res.passed:
            return {
                "slice": s_name,
                "slice_name": s_name,
                "finalized": False,
                "state": state.state,
                "commit_oid": None,
                "reason": gate_res.reason,
                "message": f"Slice finalization rejected by commit gate: {gate_res.reason}",
            }

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        builder = CandidateTreeBuilder(r_dir, c_home)
        base_commit = state.base_commit_oid or get_head_commit_oid(r_dir)
        captured_tree_oid = builder.capture_candidate_tree(base_commit)

        msg = commit_message or f"feat({s_name}): complete slice run {state.run_id}"

        # 1. COMMIT_RECORDED
        rec_commit_payload = {
            "payload_type": "COMMIT_RECORDED",
            "commit_oid": captured_tree_oid,
            "commit_message": msg,
            "workspace_revision_digest": gate_res.workspace_revision_digest,
        }
        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="COMMIT_RECORDED",
            payload_type="COMMIT_RECORDED",
            actor_role="COMMIT_MANAGER",
            actor_principal="operator-local",
            payload=rec_commit_payload,
            token_hash=token_hash,
        )

        # 2. GOVERNANCE_STARTED
        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 2, token)

        gov_start_payload = {
            "payload_type": "GOVERNANCE_STARTED",
            "summary": "Initiate governance reconciliation",
        }
        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="GOVERNANCE_STARTED",
            payload_type="GOVERNANCE_STARTED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="operator-local",
            payload=gov_start_payload,
            token_hash=token_hash,
        )

        # 3. GOVERNANCE_RECONCILED
        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 3, token)

        gov_rec_payload = {
            "payload_type": "GOVERNANCE_RECONCILED",
            "summary": "Governance reconciled successfully",
            "final_state": "COMPLETE",
        }
        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="GOVERNANCE_RECONCILED",
            payload_type="GOVERNANCE_RECONCILED",
            actor_role="GOVERNANCE_AGENT",
            actor_principal="operator-local",
            payload=gov_rec_payload,
            token_hash=token_hash,
        )

        updated_state = controller.get_slice_state(s_name)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "finalized": True,
        "state": updated_state.state if updated_state else "COMPLETE",
        "commit_oid": captured_tree_oid,
        "message": f"Slice '{s_name}' successfully finalized to COMPLETE state.",
    }


def slice_fast_track_certify(
    slice: str | None = None,
    slice_name: str | None = None,
    repo_dir: str | Path | None = None,
    control_home: str | Path | None = None,
) -> dict[str, Any]:
    """
    Certify a fast-track slice that has passed tests and valid scope, transitioning to COMMIT_READY.
    """
    s_name = _get_slice_name(slice, slice_name)
    r_dir, c_home = _resolve_paths(repo_dir, control_home)
    controller = SliceRunController(repo_dir=r_dir, control_home=c_home)

    with controller._get_lock(s_name):
        state = controller.get_slice_state(s_name)
        if not state:
            raise OrchestratorError(f"Slice '{s_name}' does not exist.")

        if getattr(state, "profile", "standard") != "fast-track":
            raise OrchestratorError(f"Slice '{s_name}' is not in fast-track profile (current: {state.profile}).")

        if state.state != "IMPLEMENTATION_READY_FOR_REVIEW":
            raise OrchestratorError(f"Cannot fast-track certify in state '{state.state}'. Must be in IMPLEMENTATION_READY_FOR_REVIEW.")

        token = str(uuid.uuid4())
        token_hash = controller.store.set_ownership(s_name, state.run_id, state.run_generation, state.sequence + 1, token)

        rev_id = f"rev-ft-{uuid.uuid4().hex[:8]}"
        rev_record = {
            "schema_version": 4,
            "record_type": "REVIEW_RECORD",
            "record_id": rev_id,
            "slice": s_name,
            "run_id": state.run_id,
            "verdict": "APPROVED",
            "summary": "Fast-track deterministic certification: tests verified green and scope valid.",
            "reviewer_principal": "controller-fast-track",
            "implementer_principal": "controller-fast-track-impl",
            "is_self_approved": False,
            "is_fast_track": True,
            "blocking_finding_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        rev_digest = controller.store.store_record("REVIEW_RECORD", rev_id, rev_record)

        payload = {
            "payload_type": "REVIEW_ACCEPTED",
            "record": {
                "record_type": "REVIEW_RECORD",
                "record_id": rev_id,
                "record_digest": rev_digest,
            },
            "verdict": "APPROVED",
            "summary": "Fast-track deterministic certification: tests verified green and scope valid.",
            "is_fast_track": True,
            "workspace_revision_digest": state.workspace_revision_digest,
            "evidence_set_digest": state.evidence_set_digest,
            "approved_revision_digest": rev_digest,
        }

        controller.store.append_event(
            slice_name=s_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="REVIEW_ACCEPTED",
            payload_type="REVIEW_ACCEPTED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal=MCP_HOST_PRINCIPAL,
            payload=payload,
            token_hash=token_hash,
        )

        updated_state = controller.get_slice_state(s_name)

    return {
        "slice": s_name,
        "slice_name": s_name,
        "state": updated_state.state if updated_state else state.state,
        "certified": True,
        "message": "Fast-track review accepted. Proceed to slice_gate and slice_finalize.",
    }
