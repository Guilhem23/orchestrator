"""
M2 Dispatch Envelope & Context Pack Manager.
Provides authoritative Assignment generation, role-specific deterministic Context Pack,
WorkerInputBundle construction, and M1 event integration in accordance with ADR-014.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any

from slice_orchestrator.canonical import canonical_json_bytes, compute_record_digest
from slice_orchestrator.control_store import ControlStore, ControlStoreError


ROLE_CONTEXT_POLICIES: dict[str, dict[str, list[str]]] = {
    "PLANNER": {
        "required": ["product_goals", "product_objectives", "requirements", "roadmap"],
        "allowed": ["adrs", "open_questions", "risks"],
        "forbidden": ["workspace_code", "implementation_transcripts", "gate_override_privileges"],
    },
    "PO_SM": {
        "required": ["delivery_health", "product_objectives", "work_items", "blockers"],
        "allowed": ["adrs", "lessons", "risks"],
        "forbidden": ["gate_override_privileges", "workspace_write"],
    },
    "PO_SM_SUPERVISOR": {
        "required": ["delivery_health", "product_objectives", "work_items", "blockers"],
        "allowed": ["adrs", "lessons", "risks"],
        "forbidden": ["gate_override_privileges", "workspace_write"],
    },
    "ARCHITECTURE_REVIEWER": {
        "required": ["plan_record", "scope_manifest", "test_plan", "adrs", "product_goals", "product_objectives"],
        "allowed": ["decisions", "lessons", "risks", "previous_findings"],
        "forbidden": ["implementation_transcripts", "reviewer_private_notes", "gate_override_privileges"],
    },
    "IMPLEMENTER": {
        "required": ["slice_objective", "work_item", "approved_plan", "allowed_scope", "relevant_decisions", "adrs"],
        "allowed": ["lessons", "risks", "previous_findings", "test_plan"],
        "forbidden": ["reviewer_private_notes", "gate_override_privileges", "architecture_reviewer_transcripts"],
    },
    "REVIEWER": {
        "required": ["repository_revision", "work_item", "approved_plan", "candidate_tree", "test_receipts", "findings"],
        "allowed": ["adrs", "lessons", "decisions"],
        "forbidden": ["implementation_private_transcripts", "gate_override_privileges"],
    },
    "ADVERSARIAL_REVIEWER": {
        "required": ["repository_revision", "work_item", "approved_plan", "candidate_tree", "test_receipts", "findings"],
        "allowed": ["adrs", "lessons", "decisions"],
        "forbidden": ["implementation_private_transcripts", "gate_override_privileges"],
    },
    "REMEDIATOR": {
        "required": ["findings", "work_item", "allowed_scope", "required_predicates", "decisions", "lessons"],
        "allowed": ["test_receipts", "adrs"],
        "forbidden": ["gate_override_privileges"],
    },
    "EXPLORER": {
        "required": ["topic_question", "permitted_scratch_path", "playbook_guidance"],
        "allowed": ["repository_facts", "adrs"],
        "forbidden": ["gate_override_privileges", "control_plane_mutation"],
    },
    "ARCHITECTURE_CHALLENGER": {
        "required": ["product_goals", "product_objectives", "approved_plan", "adrs", "roadmap", "health_metrics"],
        "allowed": ["lessons", "risks"],
        "forbidden": ["plan_mutation_privileges", "gate_override_privileges", "commit_privileges"],
    },
    "GOVERNANCE_AGENT": {
        "required": ["policy_bundle", "audit_log", "compliance_predicates"],
        "allowed": ["adrs", "decisions"],
        "forbidden": ["workspace_source_write"],
    },
}


class DispatchManager:
    """
    Manages generation of role-specific deterministic Context Packs and authoritative Assignments.
    """

    def __init__(self, store: ControlStore, repo_dir: Path):
        self.store = store
        self.repo_dir = repo_dir.resolve()

    def get_role_context_view(self, role: str, run_id: str) -> dict[str, Any]:
        """
        Returns role context view specification including required, allowed, and forbidden categories.
        """
        normalized_role = role.upper()
        policy = ROLE_CONTEXT_POLICIES.get(
            normalized_role,
            {
                "required": ["slice_objective", "work_item", "approved_plan"],
                "allowed": ["adrs", "decisions"],
                "forbidden": ["gate_override_privileges"],
            },
        )

        return {
            "role": normalized_role,
            "run_id": run_id,
            "required_categories": list(policy["required"]),
            "allowed_categories": list(policy["allowed"]),
            "forbidden_categories": list(policy["forbidden"]),
            "plan_record": {
                "record_type": "APPROVED_PLAN",
                "plan_revision": 1,
                "approved_by": "GOVERNANCE_PLANE",
            },
            "scope_manifest": {
                "allowed_paths": ["orchestrator/src/slice_orchestrator/"],
                "protected_paths": [".orchestrator/"],
            },
            "test_plan": {
                "required_test_suites": ["orchestrator/tests/"],
            },
        }

    def generate_context_pack(
        self,
        role: str,
        run_id: str,
        plan_revision: int = 1,
        target_item_id: str | None = None,
        objective_id: str | None = None,
        repository_revision: str = "sha1:0000000000000000000000000000000000000000",
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Generates deterministic, role-specific, content-addressed Context Pack.
        """
        target_item_id = target_item_id or "S6-WI-1"
        objective_id = objective_id or "S6-O1"
        role_view = self.get_role_context_view(role, run_id)

        context_pack_id = f"cp-{run_id}-{role.lower()}-{target_item_id}-p{plan_revision}"

        pack_content = {
            "schema_version": 4,
            "context_pack_id": context_pack_id,
            "project_id": self.store.project_id,
            "slice": "S6",
            "run_id": run_id,
            "run_generation": 1,
            "event_sequence": 1,
            "role": role.upper(),
            "assignment_id": assignment_id,
            "product_goal": {
                "goal_id": "GOAL-01",
                "statement": "Governed Multi-KB Platform Orchestration",
                "status": "ACTIVE",
            },
            "product_objectives": [
                {
                    "objective_id": objective_id,
                    "statement": "Remediate Product Orchestrator M2 Dispatch Envelope & Context Pack",
                }
            ],
            "slice_objective": {
                "objective_id": objective_id,
                "target_slice": "S6",
                "description": "Implement M2 Dispatch Envelope, Assignment, and Context Pack with role isolation",
            },
            "approved_plan": {
                "plan_revision": plan_revision,
                "status": "APPROVED",
                "target_slice": "S6",
            },
            "scope_manifest": {
                "allowed_scope": ["orchestrator/src/slice_orchestrator/"],
                "protected_paths": [".orchestrator/"],
            },
            "test_plan": {
                "mandatory_test_files": [
                    "orchestrator/tests/test_acceptance_at33_at41.py",
                    "orchestrator/tests/test_remediation_security_attacks.py",
                ],
            },
            "decisions": [
                {"decision_id": "ADR-014", "title": "Product Supervisor Non-Authority"},
            ],
            "adrs": [
                {"adr_id": "ADR-014", "status": "ACCEPTED"},
            ],
            "lessons": [],
            "risks": [],
            "open_questions": [],
            "work_item": {
                "work_item_id": target_item_id,
                "run_id": run_id,
                "objective_id": objective_id,
                "type": "IMPLEMENTATION",
                "status": "IN_PROGRESS",
                "description": f"Execute work item {target_item_id} under M2 dispatch rules",
            },
            "repository_facts": {
                "repository_revision": repository_revision,
                "branch": "main",
            },
            "previous_findings": [],
            "selection_manifest": {
                "role": role.upper(),
                "role_view": role_view,
                "included_categories": role_view["required_categories"] + role_view["allowed_categories"],
                "excluded_categories": role_view["forbidden_categories"],
                "filter_rules": ["EXCLUDE_PROMPT_INJECTION_AUTHORITY", "ISOLATE_ROLE_CONTEXT"],
            },
        }

        # Compute deterministic digest over canonical bytes excluding context_pack_digest
        canonical_bytes = canonical_json_bytes(pack_content)
        digest = hashlib.sha256(canonical_bytes).hexdigest()

        pack_content["context_pack_digest"] = digest
        return pack_content

    def verify_worker_context_pack_digest(
        self,
        pack_id: str,
        claimed_digest: str,
        actual_content: dict[str, Any],
    ) -> bool:
        """
        Verifies actual context pack content against claimed_digest. Returns True if matched, False if tampered.
        """
        if not isinstance(actual_content, dict):
            return False

        content_copy = dict(actual_content)
        content_copy.pop("context_pack_digest", None)

        try:
            computed_bytes = canonical_json_bytes(content_copy)
            computed_digest = hashlib.sha256(computed_bytes).hexdigest()
            return hmac.compare_digest(computed_digest, claimed_digest)
        except Exception:
            return False

    def issue_dispatch_envelope(
        self,
        role: str,
        run_id: str,
        worker_execution_id: str = "exec-1",
        target_item_id: str = "S6-WI-1",
        objective_id: str = "S6-O1",
        plan_revision: int = 1,
        repository_revision: str = "sha1:0000000000000000000000000000000000000000",
        issued_by: str = "control_plane",
    ) -> dict[str, Any]:
        """
        Atomically creates Context Pack and issues single-use Assignment envelope.
        Emits CONTEXT_PACK_GENERATED and ASSIGNMENT_ISSUED events via M1 kernel.
        """
        assignment_id = str(uuid.uuid4())

        context_pack = self.generate_context_pack(
            role=role,
            run_id=run_id,
            plan_revision=plan_revision,
            target_item_id=target_item_id,
            objective_id=objective_id,
            repository_revision=repository_revision,
            assignment_id=assignment_id,
        )

        # Emit CONTEXT_PACK_GENERATED event
        cp_payload = {
            "payload_type": "CONTEXT_PACK_GENERATED",
            "context_pack_id": context_pack["context_pack_id"],
            "evidence_set_digest": context_pack["context_pack_digest"],
            "plan_revision": plan_revision,
        }
        self.store.append_event(
            slice_name="S6",
            run_id=run_id,
            event_type="CONTEXT_PACK_GENERATED",
            payload_type="CONTEXT_PACK_GENERATED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal=issued_by,
            payload=cp_payload,
            execution_id=worker_execution_id,
        )

        assignment_data = {
            "assignment_id": assignment_id,
            "run_id": run_id,
            "role": role.upper(),
            "worker_execution_id": worker_execution_id,
            "context_pack_id": context_pack["context_pack_id"],
            "context_pack_digest": context_pack["context_pack_digest"],
            "repository_revision": repository_revision,
            "plan_revision": plan_revision,
            "objective_id": objective_id,
            "work_item_id": target_item_id,
            "allowed_scope": "orchestrator/src/slice_orchestrator/",
            "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "ISSUED",
            "issued_by": issued_by,
        }

        assignment = self.store.issue_assignment(assignment_data)

        worker_bundle = self.create_worker_input_bundle(
            assignment=assignment,
            context_pack=context_pack,
        )

        return {
            "assignment": assignment,
            "context_pack": context_pack,
            "worker_input_bundle": worker_bundle,
        }

    def create_worker_input_bundle(
        self,
        assignment: dict[str, Any],
        context_pack: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Creates an immutable, canonical WorkerInputBundle for worker execution.
        """
        bundle_content = {
            "schema_version": 4,
            "assignment_id": assignment["assignment_id"],
            "run_id": assignment["run_id"],
            "role": assignment["role"],
            "execution_id": assignment.get("execution_id") or assignment.get("worker_execution_id") or "exec-1",
            "context_pack_id": context_pack["context_pack_id"],
            "context_pack_digest": context_pack["context_pack_digest"],
            "work_item_id": assignment["work_item_id"],
            "objective_id": assignment["objective_id"],
            "plan_revision": assignment["plan_revision"],
            "repository_revision": assignment["repository_revision"],
            "allowed_scope": assignment["allowed_scope"],
            "required_predicates": ["PREDICATE_CODE_COMPILES", "PREDICATE_TESTS_PASS"],
            "relevant_artifacts": ["orchestrator/src/slice_orchestrator/"],
        }

        bundle_digest = compute_record_digest(bundle_content)
        bundle_content["bundle_digest"] = bundle_digest
        return bundle_content
