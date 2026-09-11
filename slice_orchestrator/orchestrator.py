"""
Slice Orchestrator Controller for Method v4.
Autonomous lifecycle loop, worker dispatching, remediation handling, governance sequencing, and CLI actions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slice_orchestrator.canonical import compute_record_digest
from slice_orchestrator.control_store import ControlStore, SliceLockManager
from slice_orchestrator.convergence import ConvergenceEngine
from slice_orchestrator.dispatch import DispatchManager
from slice_orchestrator.human_decision import HumanDecisionManager
from slice_orchestrator.gates import (
    GateEvaluator,
    execute_control_test,
    persist_signed_receipt,
)
from slice_orchestrator.objectives import Objective
from slice_orchestrator.git_manager import (
    AtomicCommitManager,
    CandidateTreeBuilder,
    ScopeManifestValidator,
    compute_approved_revision_digest,
    compute_evidence_set_digest,
    compute_workspace_revision_digest,
    get_git_object_format,
    get_head_commit_oid,
)
from slice_orchestrator.policy import PolicyBundle
from slice_orchestrator.state_machine import (
    SliceRunState,
    TransitionEngine,
    TransitionError,
    project_slice_run_state,
)
from slice_orchestrator.workers import (
    WorkerInputBundle,
    WorkerRegistry,
    WorkerResult,
)


class OrchestratorError(ValueError):
    """Raised when orchestrator execution fails."""
    pass


class SliceRunController:
    """
    Method v4 Slice Run Controller.
    """

    def __init__(
        self,
        repo_dir: Path,
        control_home: Path,
        worker_registry: WorkerRegistry | None = None,
        configured_adapter_id: str = "dummy",
        policy_bundle_source: Path | None = None,
        allow_dummy_fallback: bool = False,
    ):
        self.repo_dir = repo_dir.resolve()
        self.control_home = control_home.resolve()
        self.worker_registry = worker_registry or WorkerRegistry(allow_dummy_fallback=allow_dummy_fallback)
        self.configured_adapter_id = configured_adapter_id

        self.store = ControlStore(self.control_home)

        # Initialize policy bundle if not already present
        if not (self.control_home / "policy_bundle_digest").is_file():
            bundle_src = policy_bundle_source or (self.repo_dir / ".orchestrator")
            if not bundle_src.is_dir():
                bundle_src = Path.cwd() / ".orchestrator"
            if not bundle_src.is_dir():
                bundle_src = Path(__file__).resolve().parents[1] / ".orchestrator"
            if bundle_src.is_dir():
                self.store.initialize_policy_bundle(bundle_src)
            else:
                raise OrchestratorError(f"No policy bundle found at {bundle_src}")

        self.policy_bundle = self.store.load_and_verify_policy_bundle()
        self.store.init_database()
        self.dispatch_manager = DispatchManager(self.store, self.repo_dir)
        self.human_decision_manager = HumanDecisionManager(self.store)
        self.convergence_engine = ConvergenceEngine(self.store)
        self.transition_engine = TransitionEngine(
            self.policy_bundle.transitions,
            self.policy_bundle.slice_policy,
        )

    def _get_lock(self, slice_name: str) -> SliceLockManager:
        return SliceLockManager(self.store.locks_dir / f"{slice_name}.lock")

    def get_slice_state(self, slice_name: str) -> SliceRunState | None:
        events = self.store.verify_store_integrity()
        slice_events = [e for e in events if e["slice"] == slice_name]
        return project_slice_run_state(slice_events, self.store)

    def open_run(self, slice_name: str, base_commit: str | None = None) -> SliceRunState:
        """
        Create a new persistent Slice Run for slice_name.
        """
        with self._get_lock(slice_name):
            return self._open_run_unlocked(slice_name, base_commit=base_commit)

    def _open_run_unlocked(self, slice_name: str, base_commit: str | None = None) -> SliceRunState:
        current_state = self.get_slice_state(slice_name)
        if current_state is not None and not current_state.is_terminal():
            return current_state

        run_id = str(uuid.uuid4())
        generation = (current_state.run_generation + 1) if current_state else 1
        base_commit_oid = base_commit or get_head_commit_oid(self.repo_dir)

        token = str(uuid.uuid4())
        token_hash = self.store.set_ownership(slice_name, run_id, generation, 1, token)

        now_iso = datetime.now(timezone.utc).isoformat()
        run_record = {
            "schema_version": 4,
            "record_type": "SLICE_RUN",
            "run_id": run_id,
            "slice": slice_name,
            "project_id": self.store.project_id,
            "run_generation": generation,
            "state": "PLANNING",
            "plan_revision": 0,
            "review_cycle_high_water": 0,
            "remediation_cycle_high_water": 0,
            "policy_bundle_digest": self.policy_bundle.computed_digest,
            "base_commit_oid": base_commit_oid,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        run_rec_digest = self.store.store_record("SLICE_RUN", run_id, run_record)

        payload = {
            "payload_type": "RUN_OPENED",
            "record": {
                "record_type": "SLICE_RUN",
                "record_id": run_id,
                "record_digest": run_rec_digest,
            },
            "base_commit_oid": base_commit_oid,
            "policy_bundle_digest": self.policy_bundle.computed_digest,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=run_id,
            generation=generation,
            event_type="RUN_OPENED",
            payload_type="RUN_OPENED",
            actor_role="CONTROL_OPERATOR",
            actor_principal="operator-local",
            payload=payload,
            token_hash=token_hash,
        )

        return self.get_slice_state(slice_name)  # type: ignore

    def step(self, slice_name: str) -> SliceRunState:
        """
        Perform exactly one legal workflow step in the autonomous run loop.
        """
        with self._get_lock(slice_name):
            state = self.get_slice_state(slice_name)
            if state is None:
                state = self._open_run_unlocked(slice_name)

            if state.is_terminal():
                return state

            if state.execution_mode == "PAUSED":
                return state

            curr_seq = state.sequence
            curr_tail = state.stream_tail_hash

            if state.state == "PLANNING":
                return self._step_planning(slice_name, state, curr_seq, curr_tail)
            elif state.state == "PLAN_READY":
                return self._step_plan_ready(slice_name, state, curr_seq, curr_tail)
            elif state.state == "ARCHITECTURE_REVIEW":
                return self._step_architecture_review(slice_name, state, curr_seq, curr_tail)
            elif state.state == "ARCHITECTURE_APPROVED":
                return self._step_architecture_approved(slice_name, state, curr_seq, curr_tail)
            elif state.state == "IMPLEMENTATION":
                return self._step_implementation(slice_name, state, curr_seq, curr_tail)
            elif state.state == "IMPLEMENTATION_READY_FOR_REVIEW":
                return self._step_implementation_ready_for_review(slice_name, state, curr_seq, curr_tail)
            elif state.state == "ADVERSARIAL_REVIEW":
                return self._step_adversarial_review(slice_name, state, curr_seq, curr_tail)
            elif state.state == "REMEDIATION":
                return self._step_remediation(slice_name, state, curr_seq, curr_tail)
            elif state.state == "PLAN_REVISION":
                return self._step_plan_revision(slice_name, state, curr_seq, curr_tail)
            elif state.state == "COMMIT_READY":
                return self._step_commit_ready(slice_name, state, curr_seq, curr_tail)
            elif state.state == "COMMITTED":
                return self._step_committed(slice_name, state, curr_seq, curr_tail)
            elif state.state == "GOVERNANCE_RECONCILIATION":
                return self._step_governance_reconciliation(slice_name, state, curr_seq, curr_tail)
            else:
                raise OrchestratorError(f"Unhandled state {state.state}")

    def run_to_completion(self, slice_name: str) -> SliceRunState:
        """
        Autonomously drive the run loop until terminal or PAUSED state.
        """
        state = self.get_slice_state(slice_name) or self.open_run(slice_name)
        while not state.is_terminal() and state.execution_mode != "PAUSED":
            new_state = self.step(slice_name)
            if new_state.sequence == state.sequence and new_state.state == state.state:
                break
            state = new_state
        return state

    # Step Handlers

    def _step_planning(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        adapter = self.worker_registry.get(self.configured_adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=str(uuid.uuid4()),
            run_id=state.run_id,
            slice=slice_name,
            role="PLANNER",
            prompt=f"Create a plan for slice {slice_name}",
            base_commit_oid=state.base_commit_oid or get_head_commit_oid(self.repo_dir),
            workspace_dir=self.repo_dir,
            output_dir=self.store.artifacts_dir,
            candidate_tree_oid=getattr(state, "candidate_tree_oid", state.candidate_record_id),
            workspace_revision_digest=state.workspace_revision_digest,
            evidence_set_digest=state.evidence_set_digest,
        )
        result = adapter.run(bundle)
        if result.availability == "UNAVAILABLE" or not result.success:
            code = "WORKER_UNAVAILABLE" if result.availability == "UNAVAILABLE" else "PLANNER_FAILED"
            self._stop_run(slice_name, state, seq, tail, code, result.error_message or "Planner worker failed")
            return self.get_slice_state(slice_name)  # type: ignore

        plan_data = result.artifacts.get("plan", {})
        if not plan_data:
            self._stop_run(slice_name, state, seq, tail, "MALFORMED_WORKER_OUTPUT", "Planner produced no plan artifact")
            return self.get_slice_state(slice_name)  # type: ignore
        plan_id = plan_data.get("record_id", str(uuid.uuid4()))
        plan_digest = self.store.store_record("PLAN", plan_id, plan_data)

        objective = Objective(
            objective_id=f"{slice_name}-O1",
            run_id=state.run_id,
            slice=slice_name,
            description=plan_data.get("plan_digest") and f"Deliver slice {slice_name}" or f"Deliver slice {slice_name}",
            source_requirements=[slice_name],
            acceptance_predicates=[{
                "predicate_id": "P-tests",
                "kind": "test_pass",
                "expression": "pytest -q",
            }],
            status="IN_PROGRESS",
            plan_revision=state.plan_revision + 1,
        )
        self.store.save_objective(objective)

        payload = {
            "payload_type": "PLAN_PERSISTED",
            "record": {"record_type": "PLAN", "record_id": plan_id, "record_digest": plan_digest},
            "plan_revision": state.plan_revision + 1,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="PLAN_PERSISTED",
            payload_type="PLAN_PERSISTED",
            actor_role="PLANNER",
            actor_principal="planner-worker",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_plan_ready(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        as_id = str(uuid.uuid4())
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        payload = {
            "payload_type": "ARCHITECTURE_REVIEW_ASSIGNED",
            "record": {
                "record_type": "ASSIGNMENT",
                "record_id": as_id,
                "record_digest": hashlib.sha256(as_id.encode("utf-8")).hexdigest(),
            },
            "assignment_id": as_id,
            "principal_id": "arch-reviewer-1",
            "execution_id": exec_id,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="ARCHITECTURE_REVIEW_ASSIGNED",
            payload_type="ARCHITECTURE_REVIEW_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_architecture_review(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        adapter = self.worker_registry.get(self.configured_adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=state.current_assignment_id or str(uuid.uuid4()),
            run_id=state.run_id,
            slice=slice_name,
            role="ARCHITECTURE_REVIEWER",
            prompt=f"Review architecture for slice {slice_name}",
            base_commit_oid=state.base_commit_oid or get_head_commit_oid(self.repo_dir),
            workspace_dir=self.repo_dir,
            output_dir=self.store.artifacts_dir,
            candidate_tree_oid=getattr(state, "candidate_tree_oid", state.candidate_record_id),
            workspace_revision_digest=state.workspace_revision_digest,
            evidence_set_digest=state.evidence_set_digest,
        )
        result = adapter.run(bundle)
        if result.availability == "UNAVAILABLE" or not result.success:
            code = "WORKER_UNAVAILABLE" if result.availability == "UNAVAILABLE" else "WORKER_FAILED"
            self._stop_run(
                slice_name, state, seq, tail, code,
                result.error_message or "Architecture worker failed; refusing implicit approval",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        arch_data = result.artifacts.get("architecture_review")
        if not isinstance(arch_data, dict) or not arch_data:
            self._stop_run(
                slice_name, state, seq, tail, "MALFORMED_WORKER_OUTPUT",
                "Architecture worker produced no review artifact; refusing implicit approval",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        arch_id = arch_data.get("architecture_review_id", str(uuid.uuid4()))
        arch_digest = self.store.store_record("ARCHITECTURE_REVIEW", arch_id, arch_data)

        verdict = arch_data.get("verdict")
        if verdict not in ("APPROVED", "BLOCKED"):
            self._stop_run(
                slice_name, state, seq, tail, "MALFORMED_WORKER_OUTPUT",
                f"Architecture worker produced invalid verdict {verdict!r}",
            )
            return self.get_slice_state(slice_name)  # type: ignore
        event_type = "ARCHITECTURE_APPROVED" if verdict == "APPROVED" else "ARCHITECTURE_BLOCKED"

        payload = {
            "payload_type": event_type,
            "record": {"record_type": "ARCHITECTURE_REVIEW", "record_id": arch_id, "record_digest": arch_digest},
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type=event_type,
            payload_type=event_type,
            actor_role="ARCHITECTURE_REVIEWER",
            actor_principal="arch-reviewer-1",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_architecture_approved(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        as_id = str(uuid.uuid4())
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        payload = {
            "payload_type": "IMPLEMENTATION_ASSIGNED",
            "record": {
                "record_type": "ASSIGNMENT",
                "record_id": as_id,
                "record_digest": hashlib.sha256(as_id.encode("utf-8")).hexdigest(),
            },
            "assignment_id": as_id,
            "principal_id": "implementer-1",
            "execution_id": exec_id,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="IMPLEMENTATION_ASSIGNED",
            payload_type="IMPLEMENTATION_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_implementation(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        work_items = self.store.list_work_items(state.run_id)
        if work_items:
            for item in work_items:
                if item.attempt_count > 3:
                    self._stop_run(
                        slice_name, state, seq, tail,
                        "WORK_ITEM_MAX_RETRIES_EXCEEDED",
                        f"Work item {item.work_item_id} exceeded maximum retries ({item.attempt_count} > 3)"
                    )
                    return self.get_slice_state(slice_name)  # type: ignore

            from slice_orchestrator.work_items import WorkItemDAGSupervisor
            supervisor = WorkItemDAGSupervisor()
            ready_items = supervisor.derive_readiness(work_items)
            from slice_orchestrator.artifact_graph import ArtifactGraphNode, ArtifactGraphStore
            graph = ArtifactGraphStore(self.store)
            for item in work_items:
                if not graph.get_node(item.work_item_id):
                    graph.add_node(ArtifactGraphNode(
                        artifact_id=item.work_item_id,
                        type="work_item",
                        parent_artifact_ids=[item.objective_id] if item.objective_id else [],
                        run_id=state.run_id,
                        work_item_id=item.work_item_id,
                        revision=item.revision,
                        hash=item.compute_hash(),
                        creator_role="PLANNER",
                    ))
                impl_id = f"impl-{item.work_item_id}"
                if not graph.get_node(impl_id):
                    graph.add_node(ArtifactGraphNode(
                        artifact_id=impl_id,
                        type="source_change",
                        parent_artifact_ids=[item.work_item_id],
                        run_id=state.run_id,
                        work_item_id=item.work_item_id,
                        revision=item.revision,
                        hash=item.compute_hash(),
                        creator_role="IMPLEMENTER",
                    ))
            for item in ready_items:
                if item.status == "READY":
                    item.status = "SATISFIED"
                    item.updated_at = datetime.now(timezone.utc).isoformat()
                    self.store.save_work_item(item)
                    break

            all_items = self.store.list_work_items(state.run_id)
            if any(item.status != "SATISFIED" for item in all_items):
                return self.get_slice_state(slice_name)  # type: ignore

        adapter = self.worker_registry.get(self.configured_adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=state.current_assignment_id or str(uuid.uuid4()),
            run_id=state.run_id,
            slice=slice_name,
            role="IMPLEMENTER",
            prompt=f"Implement slice {slice_name}",
            base_commit_oid=state.base_commit_oid or get_head_commit_oid(self.repo_dir),
            workspace_dir=self.repo_dir,
            output_dir=self.store.artifacts_dir,
            candidate_tree_oid=getattr(state, "candidate_tree_oid", state.candidate_record_id),
            workspace_revision_digest=state.workspace_revision_digest,
            evidence_set_digest=state.evidence_set_digest,
        )
        result = adapter.run(bundle)
        if result.availability == "UNAVAILABLE" or not result.success:
            code = "WORKER_UNAVAILABLE" if result.availability == "UNAVAILABLE" else "IMPLEMENTATION_FAILED"
            self._stop_run(slice_name, state, seq, tail, code, result.error_message or "Implementer worker failed")
            return self.get_slice_state(slice_name)  # type: ignore

        # 1. Checkpoint Role Context
        ctx_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        ctx_data = {
            "schema_version": 4,
            "record_type": "ROLE_CONTEXT",
            "context_id": ctx_id,
            "context_version": 1,
            "previous_context_digest": state.latest_role_context_digest,
            "project_id": self.store.project_id,
            "slice": slice_name,
            "run_id": state.run_id,
            "run_generation": state.run_generation,
            "role": "IMPLEMENTATION",
            "checkpoint_event_sequence": seq,
            "plan_revision": state.plan_revision,
            "plan_digest": state.approved_plan_digest or hashlib.sha256(b"plan").hexdigest(),
            "scope_manifest_digest": state.scope_manifest_digest or hashlib.sha256(b"scope").hexdigest(),
            "test_plan_digest": state.required_test_plan_digest or hashlib.sha256(b"test").hexdigest(),
            "base_commit_oid": state.base_commit_oid or get_head_commit_oid(self.repo_dir),
            "workspace_tree_oid": None,
            "workspace_revision_digest": None,
            "open_remediation_packets": [],
            "work_journal": [{
                "entry_id": str(uuid.uuid4()),
                "summary": result.summary or "Work completed",
                "paths": result.role_context_update.get("paths", []) if result.role_context_update else [],
                "evidence_references": [],
            }],
            "decision_journal": [],
            "artifact_references": [],
            "last_worker_execution_id": result.execution_id,
            "created_at": now_iso,
        }
        ctx_data["context_digest"] = compute_record_digest(ctx_data)
        ctx_digest = self.store.store_record("ROLE_CONTEXT", ctx_id, ctx_data)

        # Append Checkpoint Event
        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="IMPLEMENTATION_CONTEXT_CHECKPOINTED",
            payload_type="IMPLEMENTATION_CONTEXT_CHECKPOINTED",
            actor_role="IMPLEMENTER",
            actor_principal="implementer-1",
            payload={
                "payload_type": "IMPLEMENTATION_CONTEXT_CHECKPOINTED",
                "record": {"record_type": "ROLE_CONTEXT", "record_id": ctx_id, "record_digest": ctx_digest},
            },
        )

        state2 = self.get_slice_state(slice_name)  # type: ignore

        # 2. Run tests first, then capture the resulting tree (excluding control residue)
        cap = self._capture_and_verify_tests(slice_name, state2)
        if not cap["tests_passed"]:
            self._stop_run(
                slice_name, state2, state2.sequence, state2.stream_tail_hash,
                "TESTS_FAILED",
                cap.get("reason") or "Required tests failed; refusing candidate capture for review",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        payload_cand = {
            "payload_type": "CANDIDATE_CAPTURED",
            "record": {
                "record_type": "CANDIDATE",
                "record_id": cap["candidate_id"],
                "record_digest": cap["candidate_digest"],
            },
            "workspace_revision_digest": cap["workspace_revision_digest"],
            "evidence_set_digest": cap["evidence_set_digest"],
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="CANDIDATE_CAPTURED",
            payload_type="CANDIDATE_CAPTURED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload_cand,
        )

        return self.get_slice_state(slice_name)  # type: ignore

    def _step_implementation_ready_for_review(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        as_id = str(uuid.uuid4())
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        cycle = state.review_cycle_high_water + 1
        sp = self.policy_bundle.slice_policy
        max_cycles = sp.get("cycles", {}).get("max_review_cycles", sp.get("max_review_cycles", 5))

        if cycle > max_cycles:
            self._stop_run(
                slice_name, state, seq, tail,
                "MAX_CYCLES_EXCEEDED",
                f"Maximum review cycle limit ({max_cycles}) exceeded (attempted cycle {cycle})"
            )
            return self.get_slice_state(slice_name)  # type: ignore

        payload = {
            "payload_type": "ADVERSARIAL_REVIEW_ASSIGNED",
            "record": {
                "record_type": "ASSIGNMENT",
                "record_id": as_id,
                "record_digest": hashlib.sha256(as_id.encode("utf-8")).hexdigest(),
            },
            "assignment_id": as_id,
            "principal_id": "adversarial-reviewer-1",
            "execution_id": exec_id,
            "review_cycle": cycle,
        }

        try:
            self.transition_engine.validate_transition(state, "ADVERSARIAL_REVIEW_ASSIGNED", "CONTROLLER_SYSTEM", payload)
        except TransitionError as exc:
            self._stop_run(
                slice_name, state, seq, tail,
                "MAX_CYCLES_EXCEEDED",
                str(exc)
            )
            return self.get_slice_state(slice_name)  # type: ignore

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="ADVERSARIAL_REVIEW_ASSIGNED",
            payload_type="ADVERSARIAL_REVIEW_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_adversarial_review(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        adapter = self.worker_registry.get(self.configured_adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=state.current_assignment_id or str(uuid.uuid4()),
            run_id=state.run_id,
            slice=slice_name,
            role="ADVERSARIAL_REVIEWER",
            prompt=f"Perform adversarial review for slice {slice_name}",
            base_commit_oid=state.base_commit_oid or get_head_commit_oid(self.repo_dir),
            workspace_dir=self.repo_dir,
            output_dir=self.store.artifacts_dir,
            remediation_packets=[self.store.get_record(p) for p in state.open_remediation_packet_ids if self.store.get_record(p)],
            candidate_tree_oid=getattr(state, "candidate_tree_oid", state.candidate_record_id),
            workspace_revision_digest=state.workspace_revision_digest,
            evidence_set_digest=state.evidence_set_digest,
        )
        result = adapter.run(bundle)
        if result.availability == "UNAVAILABLE" or not result.success:
            code = "WORKER_UNAVAILABLE" if result.availability == "UNAVAILABLE" else "WORKER_FAILED"
            self._stop_run(
                slice_name, state, seq, tail, code,
                result.error_message or "Adversarial review worker failed; refusing implicit approval",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        rev_data = result.artifacts.get("review")
        if not isinstance(rev_data, dict) or not rev_data:
            self._stop_run(
                slice_name, state, seq, tail, "MALFORMED_WORKER_OUTPUT",
                "Adversarial review worker produced no review artifact",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        rev_id = rev_data.get("review_id", str(uuid.uuid4()))
        rev_data.setdefault("implementer_principal", "implementer-worker")
        rev_data.setdefault("reviewer_principal", "adversarial-reviewer")
        rev_data.setdefault("is_self_approved", False)
        rev_digest = self.store.store_record("ADVERSARIAL_REVIEW", rev_id, rev_data)

        verdict = rev_data.get("verdict")
        if verdict not in ("APPROVED", "BLOCKED", "REQUIRES_PLAN_REVISION"):
            self._stop_run(
                slice_name, state, seq, tail, "MALFORMED_WORKER_OUTPUT",
                f"Adversarial review produced invalid verdict {verdict!r}",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        if verdict == "APPROVED":
            ev_type = "REVIEW_ACCEPTED"
            approved_rev_digest = compute_approved_revision_digest(
                state.workspace_revision_digest or "",
                state.evidence_set_digest or "",
            )

            payload = {
                "payload_type": "REVIEW_ACCEPTED",
                "record": {"record_type": "ADVERSARIAL_REVIEW", "record_id": rev_id, "record_digest": rev_digest},
                "review_cycle": state.review_cycle_high_water,
                "workspace_revision_digest": state.workspace_revision_digest or hashlib.sha256(b"ws").hexdigest(),
                "evidence_set_digest": state.evidence_set_digest or hashlib.sha256(b"ev").hexdigest(),
                "approved_revision_digest": approved_rev_digest,
                "plan_revision": state.plan_revision,
            }

        elif verdict == "BLOCKED":
            ev_type = "REVIEW_BLOCKED"
            pkt_id = str(uuid.uuid4())
            pkt_data = {
                "schema_version": 4,
                "record_type": "REMEDIATION_PACKET",
                "remediation_packet_id": pkt_id,
                "slice": slice_name,
                "review_id": rev_id,
                "remediation_cycle": state.remediation_cycle_high_water + 1,
                "findings": rev_data.get("findings", []),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            pkt_digest = self.store.store_record("REMEDIATION_PACKET", pkt_id, pkt_data)

            from slice_orchestrator.work_items import WorkItem
            rem_wi = WorkItem(
                work_item_id=f"{slice_name}-WI-REM-{pkt_id[:6]}",
                run_id=state.run_id,
                objective_id=f"{slice_name}-O1",
                description=f"Remediate findings for review {rev_id}",
                type="remediation",
                assigned_role="REMEDIATOR",
                status="READY",
            )
            self.store.save_work_item(rem_wi)

            payload = {
                "payload_type": "REVIEW_BLOCKED",
                "record": {"record_type": "ADVERSARIAL_REVIEW", "record_id": rev_id, "record_digest": rev_digest},
                "review_cycle": state.review_cycle_high_water,
                "remediation_cycle": state.remediation_cycle_high_water + 1,
                "workspace_revision_digest": state.workspace_revision_digest or hashlib.sha256(b"ws").hexdigest(),
                "evidence_set_digest": state.evidence_set_digest or hashlib.sha256(b"ev").hexdigest(),
                "plan_revision": state.plan_revision,
                "related_records": [{"record_type": "REMEDIATION_PACKET", "record_id": pkt_id, "record_digest": pkt_digest}],
            }
        else:
            ev_type = "REVIEW_REQUIRES_PLAN_REVISION"
            payload = {
                "payload_type": "REVIEW_REQUIRES_PLAN_REVISION",
                "record": {"record_type": "ADVERSARIAL_REVIEW", "record_id": rev_id, "record_digest": rev_digest},
                "review_cycle": state.review_cycle_high_water,
                "workspace_revision_digest": state.workspace_revision_digest or hashlib.sha256(b"ws").hexdigest(),
                "evidence_set_digest": state.evidence_set_digest or hashlib.sha256(b"ev").hexdigest(),
                "plan_revision": state.plan_revision,
                "reason_code": "PLAN_DEFECT",
                "reason": "Review indicated plan revision is required",
            }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type=ev_type,
            payload_type=ev_type,
            actor_role="ADVERSARIAL_REVIEWER",
            actor_principal="adversarial-reviewer-1",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_remediation(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        as_id = str(uuid.uuid4())
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        sp = self.policy_bundle.slice_policy
        max_remediation = sp.get("cycles", {}).get("max_remediation_cycles", sp.get("max_remediation_cycles", 5))

        if state.remediation_cycle_high_water >= max_remediation:
            self._stop_run(
                slice_name, state, seq, tail,
                "MAX_CYCLES_EXCEEDED",
                f"Maximum remediation cycle limit ({max_remediation}) exceeded"
            )
            return self.get_slice_state(slice_name)  # type: ignore

        payload = {
            "payload_type": "REMEDIATION_ASSIGNED",
            "record": {
                "record_type": "ASSIGNMENT",
                "record_id": as_id,
                "record_digest": hashlib.sha256(as_id.encode("utf-8")).hexdigest(),
            },
            "assignment_id": as_id,
            "principal_id": "implementer-1",
            "execution_id": exec_id,
        }

        try:
            self.transition_engine.validate_transition(state, "REMEDIATION_ASSIGNED", "CONTROLLER_SYSTEM", payload)
        except TransitionError as exc:
            self._stop_run(
                slice_name, state, seq, tail,
                "MAX_CYCLES_EXCEEDED",
                str(exc)
            )
            return self.get_slice_state(slice_name)  # type: ignore

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="REMEDIATION_ASSIGNED",
            payload_type="REMEDIATION_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_plan_revision(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        adapter = self.worker_registry.get(self.configured_adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=str(uuid.uuid4()),
            run_id=state.run_id,
            slice=slice_name,
            role="PLANNER",
            prompt=f"Revise plan for slice {slice_name}",
            base_commit_oid=state.base_commit_oid or get_head_commit_oid(self.repo_dir),
            workspace_dir=self.repo_dir,
            output_dir=self.store.artifacts_dir,
            candidate_tree_oid=getattr(state, "candidate_tree_oid", state.candidate_record_id),
            workspace_revision_digest=state.workspace_revision_digest,
            evidence_set_digest=state.evidence_set_digest,
        )
        result = adapter.run(bundle)
        if result.availability == "UNAVAILABLE" or not result.success:
            code = "WORKER_UNAVAILABLE" if result.availability == "UNAVAILABLE" else "PLANNER_FAILED"
            self._stop_run(slice_name, state, seq, tail, code, result.error_message or "Plan revision worker failed")
            return self.get_slice_state(slice_name)  # type: ignore

        plan_data = result.artifacts.get("plan", {})
        if not plan_data:
            self._stop_run(slice_name, state, seq, tail, "MALFORMED_WORKER_OUTPUT", "Plan revision produced no plan artifact")
            return self.get_slice_state(slice_name)  # type: ignore
        plan_id = plan_data.get("record_id", str(uuid.uuid4()))
        plan_digest = self.store.store_record("PLAN", plan_id, plan_data)

        payload = {
            "payload_type": "PLAN_REVISED",
            "record": {"record_type": "PLAN", "record_id": plan_id, "record_digest": plan_digest},
            "plan_revision": state.plan_revision + 1,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="PLAN_REVISED",
            payload_type="PLAN_REVISED",
            actor_role="PLANNER",
            actor_principal="planner-worker",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_commit_ready(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        evaluator = GateEvaluator(self.repo_dir, self.store)
        gate_res = evaluator.evaluate_commit_gate(state)

        if not gate_res.passed:
            cap = self._capture_and_verify_tests(slice_name, state)
            if not cap["tests_passed"]:
                self._stop_run(
                    slice_name, state, seq, tail,
                    "TESTS_FAILED",
                    cap.get("reason") or f"Gate failed and required tests failed: {gate_res.reason}",
                )
                return self.get_slice_state(slice_name)  # type: ignore
            payload_inv = {
                "payload_type": "ACCEPTANCE_INVALIDATED",
                "reason_code": "GATE_FAILED",
                "reason": gate_res.reason,
                "workspace_revision_digest": cap["workspace_revision_digest"],
                "evidence_set_digest": cap["evidence_set_digest"],
                "candidate_record_id": cap["candidate_id"],
            }
            self.store.append_event(
                slice_name=slice_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type="ACCEPTANCE_INVALIDATED",
                payload_type="ACCEPTANCE_INVALIDATED",
                actor_role="COMMIT_MANAGER",
                actor_principal="commit-manager",
                payload=payload_inv,
            )
            return self.get_slice_state(slice_name)  # type: ignore

        cm = AtomicCommitManager(self.repo_dir, self.store.control_home)
        base_commit = state.base_commit_oid or get_head_commit_oid(self.repo_dir)

        created_commit_oid = cm.create_commit_and_update_ref(
            accepted_candidate_tree_oid=gate_res.candidate_tree_oid or "",
            expected_parent_commit_oid=base_commit,
            commit_message=f"Commit vertical slice {slice_name}",
        )

        commit_id = str(uuid.uuid4())
        commit_rec = {
            "schema_version": 4,
            "record_type": "COMMIT",
            "commit_record_id": commit_id,
            "slice": slice_name,
            "commit_oid": created_commit_oid,
            "tree_oid": gate_res.candidate_tree_oid,
            "parent_commit_oid": base_commit,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        commit_rec_digest = self.store.store_record("COMMIT", commit_id, commit_rec)

        payload_commit = {
            "payload_type": "COMMIT_RECORDED",
            "record": {"record_type": "COMMIT", "record_id": commit_id, "record_digest": commit_rec_digest},
            "commit_oid": created_commit_oid,
            "tree_oid": gate_res.candidate_tree_oid,
            "parent_commit_oid": base_commit,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="COMMIT_RECORDED",
            payload_type="COMMIT_RECORDED",
            actor_role="COMMIT_MANAGER",
            actor_principal="commit-manager",
            payload=payload_commit,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_committed(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        as_id = str(uuid.uuid4())
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        payload = {
            "payload_type": "GOVERNANCE_STARTED",
            "record": {
                "record_type": "ASSIGNMENT",
                "record_id": as_id,
                "record_digest": hashlib.sha256(as_id.encode("utf-8")).hexdigest(),
            },
            "assignment_id": as_id,
            "principal_id": "governance-agent-1",
            "execution_id": exec_id,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="GOVERNANCE_STARTED",
            payload_type="GOVERNANCE_STARTED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _step_governance_reconciliation(self, slice_name: str, state: SliceRunState, seq: int, tail: str) -> SliceRunState:
        adapter = self.worker_registry.get(self.configured_adapter_id)
        bundle = WorkerInputBundle(
            assignment_id=state.current_assignment_id or str(uuid.uuid4()),
            run_id=state.run_id,
            slice=slice_name,
            role="GOVERNANCE_AGENT",
            prompt=f"Reconcile governance for slice {slice_name}",
            base_commit_oid=state.committed_implementation_oid or get_head_commit_oid(self.repo_dir),
            workspace_dir=self.repo_dir,
            output_dir=self.store.artifacts_dir,
            candidate_tree_oid=getattr(state, "candidate_tree_oid", state.candidate_record_id),
            workspace_revision_digest=state.workspace_revision_digest,
            evidence_set_digest=state.evidence_set_digest,
        )
        result = adapter.run(bundle)
        if result.availability == "UNAVAILABLE" or not result.success:
            code = "WORKER_UNAVAILABLE" if result.availability == "UNAVAILABLE" else "WORKER_FAILED"
            self._stop_run(
                slice_name, state, seq, tail, code,
                result.error_message or "Governance worker failed",
            )
            return self.get_slice_state(slice_name)  # type: ignore

        cm = AtomicCommitManager(self.repo_dir, self.store.control_home)
        builder = CandidateTreeBuilder(self.repo_dir, self.store.control_home)

        impl_commit = state.committed_implementation_oid or get_head_commit_oid(self.repo_dir)
        gov_tree_oid = builder.capture_candidate_tree(impl_commit)

        gov_commit_oid = cm.create_commit_and_update_ref(
            accepted_candidate_tree_oid=gov_tree_oid,
            expected_parent_commit_oid=impl_commit,
            commit_message=f"Governance reconciliation for slice {slice_name}",
        )

        gov_commit_rec_id = str(uuid.uuid4())
        gov_commit_rec = {
            "schema_version": 4,
            "record_type": "COMMIT",
            "commit_record_id": gov_commit_rec_id,
            "slice": slice_name,
            "commit_oid": gov_commit_oid,
            "tree_oid": gov_tree_oid,
            "parent_commit_oid": impl_commit,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        gov_commit_digest = self.store.store_record("COMMIT", gov_commit_rec_id, gov_commit_rec)

        payload_gov_commit = {
            "payload_type": "GOVERNANCE_COMMIT_RECORDED",
            "record": {"record_type": "COMMIT", "record_id": gov_commit_rec_id, "record_digest": gov_commit_digest},
            "commit_oid": gov_commit_oid,
            "tree_oid": gov_tree_oid,
            "parent_commit_oid": impl_commit,
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="GOVERNANCE_COMMIT_RECORDED",
            payload_type="GOVERNANCE_COMMIT_RECORDED",
            actor_role="COMMIT_MANAGER",
            actor_principal="commit-manager",
            payload=payload_gov_commit,
        )

        state2 = self.get_slice_state(slice_name)  # type: ignore

        gov_data = result.artifacts.get("governance", {})
        gov_id = gov_data.get("governance_id", str(uuid.uuid4()))
        gov_digest = self.store.store_record("GOVERNANCE", gov_id, gov_data)

        payload_gov_rec = {
            "payload_type": "GOVERNANCE_RECONCILED",
            "record": {"record_type": "GOVERNANCE", "record_id": gov_id, "record_digest": gov_digest},
        }

        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="GOVERNANCE_RECONCILED",
            payload_type="GOVERNANCE_RECONCILED",
            actor_role="GOVERNANCE_AGENT",
            actor_principal="governance-agent-1",
            payload=payload_gov_rec,
        )
        return self.get_slice_state(slice_name)  # type: ignore

    def _authorized_test_def(self) -> dict[str, Any]:
        import sys
        return {
            "test_id": "test_unit",
            "command": [sys.executable, "-m", "pytest", "-q"],
            "expected_exit_code": 0,
        }

    def _capture_and_verify_tests(self, slice_name: str, state: SliceRunState) -> dict[str, Any]:
        """
        Run the authorized test command, then capture the candidate tree with
        control-residue exclusions, and persist a receipt bound to that tree.
        """
        test_def = self._authorized_test_def()
        try:
            execution = execute_control_test(test_def, self.repo_dir)
        except Exception as exc:
            return {"tests_passed": False, "reason": str(exc)}

        builder = CandidateTreeBuilder(self.repo_dir, self.store.control_home)
        base_commit = state.base_commit_oid or get_head_commit_oid(self.repo_dir)
        captured_tree_oid = builder.capture_candidate_tree(base_commit)
        git_fmt = get_git_object_format(self.repo_dir)
        workspace_rev_digest = compute_workspace_revision_digest(
            project_id=self.store.project_id,
            git_object_format=git_fmt,
            base_commit_oid=base_commit,
            candidate_tree_oid=captured_tree_oid,
            plan_revision=state.plan_revision,
            plan_digest=state.approved_plan_digest or "",
            scope_manifest_digest=state.scope_manifest_digest or "",
            required_test_plan_digest=state.required_test_plan_digest or "",
            policy_bundle_digest=self.policy_bundle.computed_digest,
        )
        receipt = persist_signed_receipt(
            execution,
            test_def,
            self.repo_dir,
            captured_tree_oid,
            workspace_rev_digest,
            self.store,
            slice_name=slice_name,
            run_id=state.run_id,
        )
        evidence_set_digest = compute_evidence_set_digest([receipt["record_digest"]])
        cand_id = str(uuid.uuid4())
        cand_data = {
            "schema_version": 4,
            "record_type": "CANDIDATE",
            "candidate_id": cand_id,
            "slice": slice_name,
            "run_id": state.run_id,
            "candidate_tree_oid": captured_tree_oid,
            "workspace_revision_digest": workspace_rev_digest,
            "evidence_set_digest": evidence_set_digest,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        cand_digest = self.store.store_record("CANDIDATE", cand_id, cand_data)
        return {
            "tests_passed": bool(execution.passed),
            "reason": None if execution.passed else f"Required tests exited {execution.exit_code}",
            "candidate_id": cand_id,
            "candidate_digest": cand_digest,
            "candidate_tree_oid": captured_tree_oid,
            "workspace_revision_digest": workspace_rev_digest,
            "evidence_set_digest": evidence_set_digest,
            "receipt": receipt,
        }

    # Operational Commands

    def _stop_run(self, slice_name: str, state: SliceRunState, seq: int, tail: str, reason_code: str, reason: str) -> None:
        payload = {
            "payload_type": "RUN_STOPPED",
            "reason_code": reason_code,
            "reason": reason,
        }
        self.store.append_event(
            slice_name=slice_name,
            run_id=state.run_id,
            generation=state.run_generation,
            event_type="RUN_STOPPED",
            payload_type="RUN_STOPPED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal="controller",
            payload=payload,
        )

    def pause_slice(self, slice_name: str, reason: str = "Operator paused run") -> SliceRunState:
        with self._get_lock(slice_name):
            state = self.get_slice_state(slice_name)
            if not state or state.is_terminal():
                raise OrchestratorError(f"Cannot pause slice {slice_name} in state {state.state if state else 'NONE'}")

            payload = {
                "payload_type": "RUN_PAUSED",
                "reason_code": "OPERATOR_PAUSE",
                "reason": reason,
            }
            self.store.append_event(
                slice_name=slice_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type="RUN_PAUSED",
                payload_type="RUN_PAUSED",
                actor_role="CONTROL_OPERATOR",
                actor_principal="operator-local",
                payload=payload,
            )
            return self.get_slice_state(slice_name)  # type: ignore

    def resume_slice(self, slice_name: str) -> SliceRunState:
        with self._get_lock(slice_name):
            state = self.get_slice_state(slice_name)
            if not state or state.is_terminal():
                raise OrchestratorError(f"Cannot resume slice {slice_name} in state {state.state if state else 'NONE'}")

            rec_id = str(uuid.uuid4())
            own_rec = {
                "schema_version": 4,
                "record_type": "OWNERSHIP_LEASE",
                "ownership_lease_id": rec_id,
                "slice": slice_name,
                "run_id": state.run_id,
                "generation": state.run_generation,
                "epoch": 2,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            rec_digest = self.store.store_record("OWNERSHIP_LEASE", rec_id, own_rec)

            payload = {
                "payload_type": "RUN_RESUMED",
                "record": {"record_type": "OWNERSHIP_LEASE", "record_id": rec_id, "record_digest": rec_digest},
            }
            self.store.append_event(
                slice_name=slice_name,
                run_id=state.run_id,
                generation=state.run_generation,
                event_type="RUN_RESUMED",
                payload_type="RUN_RESUMED",
                actor_role="CONTROL_OPERATOR",
                actor_principal="operator-local",
                payload=payload,
            )
            return self.get_slice_state(slice_name)  # type: ignore

    def stop_slice(self, slice_name: str, reason: str = "Operator stopped run") -> SliceRunState:
        with self._get_lock(slice_name):
            state = self.get_slice_state(slice_name)
            if not state or state.is_terminal():
                return state  # type: ignore
            self._stop_run(slice_name, state, state.sequence, state.stream_tail_hash, "OPERATOR_STOP", reason)
            return self.get_slice_state(slice_name)  # type: ignore

    def recover_slice(self, slice_name: str, target_state: str, reason: str = "Human recovery") -> SliceRunState:
        with self._get_lock(slice_name):
            state = self.get_slice_state(slice_name)
            if not state or state.state not in ("STOPPED", "FAILED"):
                raise OrchestratorError(f"Human recovery requires state STOPPED or FAILED, current is {state.state if state else 'NONE'}")

            if target_state not in ("PLANNING", "PLAN_REVISION", "IMPLEMENTATION", "IMPLEMENTATION_READY_FOR_REVIEW"):
                raise OrchestratorError(f"Forbidden recovery target state: {target_state}")

            new_gen = state.run_generation + 1
            new_run_id = str(uuid.uuid4())
            token = str(uuid.uuid4())
            tok_hash = self.store.set_ownership(slice_name, new_run_id, new_gen, 1, token)

            rec_id = str(uuid.uuid4())
            rec_data = {
                "schema_version": 4,
                "record_type": "RECOVERY",
                "recovery_id": rec_id,
                "slice": slice_name,
                "prior_run_id": state.run_id,
                "prior_generation": state.run_generation,
                "new_generation": new_gen,
                "target_state": target_state,
                "reason": reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            rec_digest = self.store.store_record("RECOVERY", rec_id, rec_data)

            payload = {
                "payload_type": "HUMAN_RECOVERY_OPENED",
                "record": {"record_type": "RECOVERY", "record_id": rec_id, "record_digest": rec_digest},
                "target_state": target_state,
            }

            self.store.append_event(
                slice_name=slice_name,
                run_id=new_run_id,
                generation=new_gen,
                event_type="HUMAN_RECOVERY_OPENED",
                payload_type="HUMAN_RECOVERY_OPENED",
                actor_role="CONTROL_OPERATOR",
                actor_principal="operator-local",
                payload=payload,
                token_hash=tok_hash,
            )
            return self.get_slice_state(slice_name)  # type: ignore

    def explain_slice(self, slice_name: str) -> str:
        state = self.get_slice_state(slice_name)
        if not state:
            return f"Slice {slice_name}: No persistent Slice Run exists."

        legal_next = []
        if not state.is_terminal():
            state_rules = self.policy_bundle.transitions.get("transitions", {}).get(state.state, [])
            legal_next = [r.get("event") for r in state_rules]

        lines = [
            f"=== Slice Run Explanation for {slice_name} ===",
            f"Run ID:                    {state.run_id}",
            f"Current State:             {state.state}",
            f"Execution Mode:            {state.execution_mode}",
            f"Generation:                {state.run_generation}",
            f"Sequence:                  {state.sequence}",
            f"Plan Revision:             {state.plan_revision}",
            f"Review Cycle High Water:   {state.review_cycle_high_water} (Max: {self.policy_bundle.slice_policy.get('cycles', {}).get('max_review_cycles', 5)})",
            f"Remediation Cycle High Wtr: {state.remediation_cycle_high_water} (Max: {self.policy_bundle.slice_policy.get('cycles', {}).get('max_remediation_cycles', 5)})",
            f"Stream Tail Hash:          {state.stream_tail_hash[:16]}...",
            f"Workspace Revision Digest: {state.workspace_revision_digest[:16] if state.workspace_revision_digest else 'None'}",
            f"Approved Revision Digest:  {state.approved_revision_digest[:16] if state.approved_revision_digest else 'None'}",
            f"Open Remediation Packets:  {len(state.open_remediation_packet_ids)}",
            f"Legal Next Transitions:    {', '.join(legal_next) if legal_next else 'None (Terminal state)'}",
            f"Next Legal Action:         {legal_next[0] if legal_next else 'None'}",
        ]
        if state.stop_reason:
            lines.append(f"Blocking Condition / Stop: [{state.stop_reason_code}] {state.stop_reason}")

        return "\n".join(lines)
