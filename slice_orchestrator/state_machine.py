"""
Deterministic State Machine Projection and Transition Checker for Method v4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class TransitionError(ValueError):
    """Raised when a state transition or predicate check fails."""
    pass


@dataclass
class SliceRunState:
    slice: str
    run_id: str
    project_id: str
    state: str = "UNINITIALIZED"
    run_generation: int = 1
    sequence: int = 0
    stream_tail_hash: str = "0" * 64
    plan_revision: int = 0
    review_cycle_high_water: int = 0
    remediation_cycle_high_water: int = 0
    execution_mode: str = "RUNNING"  # RUNNING | PAUSED
    profile: str = "standard"  # standard | fast-track

    base_commit_oid: str | None = None
    policy_bundle_digest: str | None = None

    current_actor_role: str | None = None
    current_worker: str | None = None
    current_assignment_id: str | None = None
    current_execution_id: str | None = None

    approved_plan_digest: str | None = None
    scope_manifest_digest: str | None = None
    required_test_plan_digest: str | None = None

    architecture_approved: bool = False

    candidate_record_id: str | None = None
    workspace_revision_digest: str | None = None
    evidence_set_digest: str | None = None
    approved_revision_digest: str | None = None

    latest_role_context_digest: str | None = None
    latest_review_record_id: str | None = None
    latest_remediation_packet_id: str | None = None
    open_remediation_packet_ids: list[str] = field(default_factory=list)

    committed_implementation_oid: str | None = None
    committed_governance_oid: str | None = None

    stop_reason_code: str | None = None
    stop_reason: str | None = None

    FAILURE_REASON_CODES = frozenset({
        "TESTS_FAILED",
        "WORKER_FAILED",
        "WORKER_UNAVAILABLE",
        "PLANNER_FAILED",
        "IMPLEMENTATION_FAILED",
        "MALFORMED_WORKER_OUTPUT",
    })

    def is_terminal(self) -> bool:
        return self.state in ("COMPLETE", "STOPPED", "FAILED")


def project_slice_run_state(events: list[dict[str, Any]], control_store: Any = None) -> SliceRunState | None:
    """
    Rebuild state projection deterministically from verified event chain.
    """
    if not events:
        return None

    first_ev = events[0]
    proj = SliceRunState(
        slice=first_ev["slice"],
        run_id=first_ev["run_id"],
        project_id=first_ev["project_id"],
        run_generation=first_ev["run_generation"],
    )

    for ev in events:
        proj.sequence = ev["sequence"]
        proj.stream_tail_hash = ev["event_hash"]
        proj.run_generation = ev["run_generation"]

        ev_type = ev["event_type"]
        actor = ev["actor"]
        payload = ev["payload"]

        proj.current_actor_role = actor["role"]
        proj.current_assignment_id = actor.get("assignment_id")
        proj.current_execution_id = actor.get("execution_id")

        if ev_type == "RUN_OPENED":
            proj.state = "PLANNING"
            proj.base_commit_oid = payload["base_commit_oid"]
            proj.policy_bundle_digest = payload["policy_bundle_digest"]
            if "profile" in payload:
                proj.profile = payload["profile"]

        elif ev_type == "PLANNER_ASSIGNED":
            proj.state = "PLANNING"

        elif ev_type == "PLAN_PERSISTED":
            proj.state = "PLAN_READY"
            proj.plan_revision = payload.get("plan_revision", proj.plan_revision + 1)
            if "profile" in payload:
                proj.profile = payload["profile"]
            rec = payload.get("record", {})
            if rec:
                if "profile" in rec:
                    proj.profile = rec["profile"]
                plan_rec_id = rec.get("record_id")
                proj.approved_plan_digest = rec.get("record_digest")
                if control_store and plan_rec_id:
                    plan_obj = control_store.get_record(plan_rec_id)
                    if plan_obj:
                        if "profile" in plan_obj:
                            proj.profile = plan_obj["profile"]
                        proj.scope_manifest_digest = plan_obj.get("scope_manifest_digest")
                        proj.required_test_plan_digest = plan_obj.get("test_plan_digest")

        elif ev_type == "PLAN_REVISION_REQUESTED":
            proj.state = "PLAN_REVISION"

        elif ev_type == "PLAN_REVISED":
            proj.state = "PLAN_READY"
            proj.plan_revision = payload.get("plan_revision", proj.plan_revision + 1)
            rec = payload.get("record", {})
            if rec:
                plan_rec_id = rec.get("record_id")
                proj.approved_plan_digest = rec.get("record_digest")
                if control_store and plan_rec_id:
                    plan_obj = control_store.get_record(plan_rec_id)
                    if plan_obj:
                        proj.scope_manifest_digest = plan_obj.get("scope_manifest_digest")
                        proj.required_test_plan_digest = plan_obj.get("test_plan_digest")
            proj.architecture_approved = False
            proj.candidate_record_id = None
            proj.workspace_revision_digest = None
            proj.evidence_set_digest = None
            proj.approved_revision_digest = None
            proj.latest_review_record_id = None
            proj.latest_remediation_packet_id = None
            proj.open_remediation_packet_ids.clear()

        elif ev_type == "ARCHITECTURE_REVIEW_ASSIGNED":
            proj.state = "ARCHITECTURE_REVIEW"

        elif ev_type == "ARCHITECTURE_APPROVED":
            proj.state = "ARCHITECTURE_APPROVED"
            proj.architecture_approved = True

        elif ev_type == "ARCHITECTURE_BLOCKED":
            proj.state = "PLAN_REVISION"
            proj.architecture_approved = False

        elif ev_type == "IMPLEMENTATION_ASSIGNED":
            proj.state = "IMPLEMENTATION"

        elif ev_type == "IMPLEMENTATION_CONTEXT_CHECKPOINTED":
            proj.state = "IMPLEMENTATION"
            if "role_context_digest" in payload:
                proj.latest_role_context_digest = payload["role_context_digest"]

        elif ev_type == "IMPLEMENTATION_WORKER_REASSIGNED":
            proj.state = "IMPLEMENTATION"

        elif ev_type == "CANDIDATE_CAPTURED":
            proj.state = "IMPLEMENTATION_READY_FOR_REVIEW"
            rec = payload.get("record", {})
            proj.candidate_record_id = rec.get("record_id")
            proj.workspace_revision_digest = payload.get("workspace_revision_digest")
            proj.evidence_set_digest = payload.get("evidence_set_digest")

        elif ev_type == "CANDIDATE_INVALIDATED":
            proj.state = "IMPLEMENTATION"
            proj.candidate_record_id = None

        elif ev_type == "ADVERSARIAL_REVIEW_ASSIGNED":
            proj.state = "ADVERSARIAL_REVIEW"
            if "review_cycle" in payload:
                proj.review_cycle_high_water = max(proj.review_cycle_high_water, payload["review_cycle"])
            else:
                proj.review_cycle_high_water += 1

        elif ev_type == "REVIEW_ACCEPTED":
            proj.state = "COMMIT_READY"
            proj.workspace_revision_digest = payload.get("workspace_revision_digest")
            proj.evidence_set_digest = payload.get("evidence_set_digest")
            proj.approved_revision_digest = payload.get("approved_revision_digest")
            rec = payload.get("record", {})
            proj.latest_review_record_id = rec.get("record_id")
            proj.open_remediation_packet_ids.clear()

        elif ev_type == "REVIEW_BLOCKED":
            proj.state = "REMEDIATION"
            if "remediation_cycle" in payload:
                proj.remediation_cycle_high_water = max(proj.remediation_cycle_high_water, payload["remediation_cycle"])
            else:
                proj.remediation_cycle_high_water += 1
            if "related_records" in payload:
                for r in payload["related_records"]:
                    if r.get("record_type") == "REMEDIATION_PACKET":
                        proj.latest_remediation_packet_id = r["record_id"]
                        if r["record_id"] not in proj.open_remediation_packet_ids:
                            proj.open_remediation_packet_ids.append(r["record_id"])

        elif ev_type == "REVIEW_REQUIRES_PLAN_REVISION":
            proj.state = "PLAN_REVISION"

        elif ev_type == "REMEDIATION_ASSIGNED":
            proj.state = "IMPLEMENTATION"

        elif ev_type == "IMPLEMENTATION_CONTEXT_INVALID":
            proj.state = "STOPPED"
            proj.stop_reason_code = payload.get("reason_code", "CONTEXT_INVALID")
            proj.stop_reason = payload.get("reason", "Implementation context invalid")

        elif ev_type == "ACCEPTANCE_INVALIDATED":
            proj.state = "IMPLEMENTATION_READY_FOR_REVIEW"
            proj.approved_revision_digest = None
            proj.latest_review_record_id = None
            if payload.get("workspace_revision_digest"):
                proj.workspace_revision_digest = payload["workspace_revision_digest"]
            if payload.get("evidence_set_digest"):
                proj.evidence_set_digest = payload["evidence_set_digest"]
            if payload.get("candidate_record_id"):
                proj.candidate_record_id = payload["candidate_record_id"]

        elif ev_type == "COMMIT_FAILED_RECOVERABLE":
            proj.state = "COMMIT_READY"

        elif ev_type == "COMMIT_RECORDED":
            proj.state = "COMMITTED"
            proj.committed_implementation_oid = payload.get("commit_oid")

        elif ev_type == "GOVERNANCE_STARTED":
            proj.state = "GOVERNANCE_RECONCILIATION"

        elif ev_type == "GOVERNANCE_COMMIT_RECORDED":
            proj.state = "GOVERNANCE_RECONCILIATION"
            proj.committed_governance_oid = payload.get("commit_oid")

        elif ev_type == "GOVERNANCE_RECONCILED":
            proj.state = "COMPLETE"

        elif ev_type == "RUN_PAUSED":
            proj.execution_mode = "PAUSED"

        elif ev_type == "RUN_RESUMED":
            proj.execution_mode = "RUNNING"

        elif ev_type == "RUN_STOPPED":
            code = payload.get("reason_code", "STOPPED")
            proj.stop_reason_code = code
            proj.stop_reason = payload.get("reason", "Run stopped by operator or system")
            proj.state = "FAILED" if code in SliceRunState.FAILURE_REASON_CODES else "STOPPED"

        elif ev_type == "HUMAN_RECOVERY_OPENED":
            target = payload.get("target_state", "PLANNING")
            proj.state = target
            proj.approved_revision_digest = None
            proj.committed_implementation_oid = None
            proj.committed_governance_oid = None

    return proj


class TransitionEngine:
    """
    Validates state transitions against installed transitions.yaml.
    """

    def __init__(self, transitions_policy: dict[str, Any], slice_policy: dict[str, Any]):
        self.transitions_policy = transitions_policy
        self.slice_policy = slice_policy
        self.states = set(transitions_policy.get("states", []))
        self.transitions = transitions_policy.get("transitions", {})
        self.max_review_cycles = slice_policy.get("cycles", {}).get(
            "max_review_cycles", slice_policy.get("max_review_cycles", 5)
        )
        self.max_remediation_cycles = slice_policy.get("cycles", {}).get(
            "max_remediation_cycles", slice_policy.get("max_remediation_cycles", 5)
        )

    def validate_transition(
        self,
        current_state: SliceRunState | None,
        event_type: str,
        actor_role: str,
        proposed_payload: dict[str, Any],
    ) -> str:
        """
        Validate transition legality and return next state name.
        If cycle limits exceeded, returns 'STOPPED' with MAX_CYCLES_EXCEEDED.
        """
        if current_state is None:
            if event_type != "RUN_OPENED":
                raise TransitionError(f"Initial event must be RUN_OPENED, got {event_type}")
            initial_t = self.transitions_policy.get("initial_transition", {})
            allowed_roles = initial_t.get("actor_roles", ["CONTROL_OPERATOR", "CONTROLLER_SYSTEM"])
            if allowed_roles and actor_role not in allowed_roles:
                raise TransitionError(f"Actor role {actor_role} not allowed for initial RUN_OPENED")
            return "PLANNING"

        if current_state.is_terminal():
            if current_state.state in ("STOPPED", "FAILED") and event_type == "HUMAN_RECOVERY_OPENED":
                if actor_role != "CONTROL_OPERATOR":
                    raise TransitionError("Only CONTROL_OPERATOR can trigger HUMAN_RECOVERY_OPENED")
                target = proposed_payload.get("target_state")
                if target in ("COMMIT_READY", "COMMITTED", "GOVERNANCE_RECONCILIATION", "COMPLETE", "FAILED"):
                    raise TransitionError(f"Forbidden human recovery target state: {target}")
                return target
            raise TransitionError(f"Cannot transition out of terminal state {current_state.state}")

        SIDE_EVENTS = {
            "ASSIGNMENT_ISSUED": ["CONTROLLER_SYSTEM"],
            "ASSIGNMENT_CONSUMED": [
                "CONTROLLER_SYSTEM", "PLANNER", "ARCHITECTURE_REVIEWER",
                "IMPLEMENTER", "ADVERSARIAL_REVIEWER", "GOVERNANCE_AGENT",
            ],
            "CONTEXT_PACK_GENERATED": ["CONTROLLER_SYSTEM"],
        }
        if event_type in SIDE_EVENTS:
            allowed = SIDE_EVENTS[event_type]
            if allowed and actor_role not in allowed:
                raise TransitionError(
                    f"Actor role {actor_role} not permitted for side event {event_type}"
                )
            return current_state.state

        if event_type in ("RUN_PAUSED", "RUN_RESUMED"):
            if actor_role not in ("CONTROL_OPERATOR", "CONTROLLER_SYSTEM"):
                raise TransitionError(f"Only CONTROL_OPERATOR or CONTROLLER_SYSTEM can execute {event_type}")
            return current_state.state

        if event_type == "RUN_STOPPED":
            if actor_role not in ("CONTROL_OPERATOR", "CONTROLLER_SYSTEM"):
                raise TransitionError(
                    f"Actor role {actor_role} not permitted for RUN_STOPPED "
                    "(allowed: ['CONTROL_OPERATOR', 'CONTROLLER_SYSTEM'])"
                )
            return "STOPPED"

        if event_type == "ADVERSARIAL_REVIEW_ASSIGNED":
            proposed_cycle = current_state.review_cycle_high_water + 1
            if proposed_cycle > self.max_review_cycles:
                raise TransitionError(f"MAX_CYCLES_EXCEEDED: review cycle {proposed_cycle} > max {self.max_review_cycles}")

        if event_type == "REVIEW_BLOCKED":
            proposed_cycle = current_state.remediation_cycle_high_water + 1
            if proposed_cycle > self.max_remediation_cycles:
                raise TransitionError(f"MAX_CYCLES_EXCEEDED: remediation cycle {proposed_cycle} > max {self.max_remediation_cycles}")

        if event_type == "IMPLEMENTATION_ASSIGNED" and current_state.state == "PLAN_READY":
            if getattr(current_state, "profile", "standard") != "fast-track":
                raise TransitionError("IMPLEMENTATION_ASSIGNED directly from PLAN_READY is only permitted for 'fast-track' profile")

        if event_type == "REVIEW_ACCEPTED" and current_state.state == "IMPLEMENTATION_READY_FOR_REVIEW":
            if getattr(current_state, "profile", "standard") != "fast-track":
                raise TransitionError("Direct REVIEW_ACCEPTED from IMPLEMENTATION_READY_FOR_REVIEW is only permitted for 'fast-track' profile")

        EVENT_STATE_MAP = {
            ("PLANNING", "PLAN_PERSISTED"): "PLAN_READY",
            ("PLAN_READY", "ARCHITECTURE_REVIEW_ASSIGNED"): "ARCHITECTURE_REVIEW",
            ("PLAN_READY", "IMPLEMENTATION_ASSIGNED"): "IMPLEMENTATION",
            ("PLAN_READY", "PLAN_REVISION_REQUESTED"): "PLAN_REVISION",
            ("PLAN_REVISION", "PLAN_REVISED"): "PLAN_READY",
            ("PLAN_REVISION", "PLAN_PERSISTED"): "PLAN_READY",
            ("ARCHITECTURE_REVIEW", "ARCHITECTURE_APPROVED"): "ARCHITECTURE_APPROVED",
            ("ARCHITECTURE_REVIEW", "ARCHITECTURE_BLOCKED"): "PLAN_REVISION",
            ("ARCHITECTURE_APPROVED", "IMPLEMENTATION_ASSIGNED"): "IMPLEMENTATION",
            ("IMPLEMENTATION", "CANDIDATE_CAPTURED"): "IMPLEMENTATION_READY_FOR_REVIEW",
            ("IMPLEMENTATION", "IMPLEMENTATION_CONTEXT_CHECKPOINTED"): "IMPLEMENTATION",
            ("IMPLEMENTATION", "IMPLEMENTATION_WORKER_REASSIGNED"): "IMPLEMENTATION",
            ("IMPLEMENTATION_READY_FOR_REVIEW", "ADVERSARIAL_REVIEW_ASSIGNED"): "ADVERSARIAL_REVIEW",
            ("IMPLEMENTATION_READY_FOR_REVIEW", "REVIEW_ACCEPTED"): "COMMIT_READY",
            ("IMPLEMENTATION_READY_FOR_REVIEW", "CANDIDATE_CAPTURED"): "IMPLEMENTATION_READY_FOR_REVIEW",
            ("ADVERSARIAL_REVIEW", "REVIEW_ACCEPTED"): "COMMIT_READY",
            ("ADVERSARIAL_REVIEW", "REVIEW_BLOCKED"): "REMEDIATION",
            ("ADVERSARIAL_REVIEW", "REVIEW_REQUIRES_PLAN_REVISION"): "PLAN_REVISION",
            ("REMEDIATION", "REMEDIATION_ASSIGNED"): "IMPLEMENTATION",
            ("REMEDIATION", "CANDIDATE_CAPTURED"): "IMPLEMENTATION_READY_FOR_REVIEW",
            ("COMMIT_READY", "COMMIT_RECORDED"): "COMMITTED",
            ("COMMIT_READY", "ACCEPTANCE_INVALIDATED"): "IMPLEMENTATION_READY_FOR_REVIEW",
            ("COMMIT_READY", "COMMIT_FAILED_RECOVERABLE"): "COMMIT_READY",
            ("COMMITTED", "GOVERNANCE_STARTED"): "GOVERNANCE_RECONCILIATION",
            ("GOVERNANCE_RECONCILIATION", "GOVERNANCE_COMMIT_RECORDED"): "GOVERNANCE_RECONCILIATION",
            ("GOVERNANCE_RECONCILIATION", "GOVERNANCE_RECONCILED"): "COMPLETE",
        }

        state_rules = self.transitions.get(current_state.state, [])
        matching_rule = None
        for rule in state_rules:
            if rule.get("event") == event_type:
                matching_rule = rule
                break

        if not matching_rule:
            expected_target = EVENT_STATE_MAP.get((current_state.state, event_type))
            if expected_target:
                for rule in state_rules:
                    if rule.get("to") == expected_target:
                        matching_rule = rule
                        break
                if not matching_rule:
                    matching_rule = {"to": expected_target, "actor_roles": []}

        if not matching_rule:
            raise TransitionError(
                f"Illegal transition: event {event_type} is not permitted from state {current_state.state}"
            )

        DEFAULT_EVENT_ROLES = {
            "RUN_OPENED": ["CONTROL_OPERATOR", "CONTROLLER_SYSTEM"],
            "PLAN_PERSISTED": ["PLANNER"],
            "PLAN_REVISION_REQUESTED": ["CONTROL_OPERATOR", "CONTROLLER_SYSTEM"],
            "PLAN_REVISED": ["PLANNER"],
            "ARCHITECTURE_REVIEW_ASSIGNED": ["CONTROLLER_SYSTEM"],
            "ARCHITECTURE_APPROVED": ["ARCHITECTURE_REVIEWER"],
            "ARCHITECTURE_BLOCKED": ["ARCHITECTURE_REVIEWER"],
            "IMPLEMENTATION_ASSIGNED": ["CONTROLLER_SYSTEM"],
            "IMPLEMENTATION_CONTEXT_CHECKPOINTED": ["IMPLEMENTER"],
            "IMPLEMENTATION_WORKER_REASSIGNED": ["CONTROLLER_SYSTEM"],
            "CANDIDATE_CAPTURED": ["IMPLEMENTER", "CONTROLLER_SYSTEM"],
            "ADVERSARIAL_REVIEW_ASSIGNED": ["CONTROLLER_SYSTEM"],
            "REVIEW_ACCEPTED": ["ADVERSARIAL_REVIEWER", "CONTROLLER_SYSTEM"],
            "REVIEW_BLOCKED": ["ADVERSARIAL_REVIEWER"],
            "REVIEW_REQUIRES_PLAN_REVISION": ["ADVERSARIAL_REVIEWER"],
            "REMEDIATION_ASSIGNED": ["CONTROLLER_SYSTEM"],
            "ACCEPTANCE_INVALIDATED": ["COMMIT_MANAGER", "CONTROLLER_SYSTEM"],
            "COMMIT_RECORDED": ["COMMIT_MANAGER"],
            "GOVERNANCE_STARTED": ["CONTROLLER_SYSTEM"],
            "GOVERNANCE_COMMIT_RECORDED": ["GOVERNANCE_AGENT", "COMMIT_MANAGER"],
            "GOVERNANCE_RECONCILED": ["GOVERNANCE_AGENT"],
            "RUN_STOPPED": ["CONTROL_OPERATOR", "CONTROLLER_SYSTEM"],
            "RUN_PAUSED": ["CONTROL_OPERATOR", "CONTROLLER_SYSTEM"],
            "RUN_RESUMED": ["CONTROL_OPERATOR"],
        }

        allowed_roles = matching_rule.get("actor_roles") or DEFAULT_EVENT_ROLES.get(event_type, [])
        if allowed_roles and actor_role not in allowed_roles:
            raise TransitionError(
                f"Actor role {actor_role} not permitted for event {event_type} from state {current_state.state} (allowed: {allowed_roles})"
            )

        to_state = matching_rule.get("to")
        if not to_state:
            raise TransitionError(f"Transition rule for {event_type} has no target 'to' state")

        return to_state
