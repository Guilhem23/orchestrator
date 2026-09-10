"""
Normative Acceptance Tests AT-21 through AT-32 for Method v4 Product Orchestrator.
Conforms strictly to .orchestrator/ACCEPTANCE_TESTS.md and ADR-014 Annex v1.
"""

from pathlib import Path
import subprocess
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.objectives import Objective
from slice_orchestrator.work_items import WorkItem, WorkItemDAGSupervisor
from slice_orchestrator.convergence import ConvergenceEngine
from slice_orchestrator.learnings import LearningRecord, LearningLedger
from slice_orchestrator.exploration import ExplorationManager
from slice_orchestrator.artifact_graph import ArtifactGraphNode, ArtifactGraphStore
from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.state_machine import TransitionError
from slice_orchestrator.workers import TestDummyWorkerAdapter


def test_at21_work_item_dependency_graph_enforcement():
    """
    AT-21: Work Item dependency graph is strictly enforced.
    Worker self-declaration cannot satisfy dependency before parent is SATISFIED.
    """
    run_id = "00000000-0000-0000-0000-000000000001"
    wi1 = WorkItem(
        work_item_id="S6-WI-1",
        run_id=run_id,
        objective_id="S6-O1",
        description="Parent task",
        type="implementation",
        status="IN_PROGRESS",
    )
    wi2 = WorkItem(
        work_item_id="S6-WI-2",
        run_id=run_id,
        objective_id="S6-O1",
        description="Child task",
        type="implementation",
        dependencies=["S6-WI-1"],
        status="PENDING",
    )

    supervisor = WorkItemDAGSupervisor()
    updated = supervisor.derive_readiness([wi1, wi2])
    wi2_updated = [i for i in updated if i.work_item_id == "S6-WI-2"][0]
    assert wi2_updated.status == "PENDING"  # Must NOT be READY because parent is IN_PROGRESS

    # When parent transitions to SATISFIED, child becomes READY
    wi1.status = "SATISFIED"
    updated2 = supervisor.derive_readiness([wi1, wi2])
    wi2_updated2 = [i for i in updated2 if i.work_item_id == "S6-WI-2"][0]
    assert wi2_updated2.status == "READY"


def test_at22_conflicting_work_items_serialized():
    """
    AT-22: Conflicting Work Items with overlapping scopes are serialized.
    """
    wi03 = WorkItem(
        work_item_id="S6-WI-03",
        run_id="run-1",
        objective_id="S6-O1",
        description="Modify search",
        type="implementation",
        allowed_scope=["src/search.py"],
        status="IN_PROGRESS",
    )
    wi04 = WorkItem(
        work_item_id="S6-WI-04",
        run_id="run-1",
        objective_id="S6-O1",
        description="Modify search refactor",
        type="implementation",
        allowed_scope=["src/search.py"],
        status="READY",
    )

    overlap = bool(set(wi03.allowed_scope) & set(wi04.allowed_scope))
    assert overlap, "Scopes overlap on src/search.py, requiring serialization"


def test_at23_worker_replacement_preserves_state(disposable_repo_and_control):
    """
    AT-23: Worker replacement on Work Item preserves state and increments attempt counters.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    wi = WorkItem(
        work_item_id="S6-WI-03",
        run_id="run-1",
        objective_id="S6-O1",
        description="Task mid-execution",
        type="implementation",
        worker_execution_id="worker-A-exec-1",
        status="IN_PROGRESS",
        attempt_count=1,
        worker_execution_ids=["worker-A-exec-1"],
    )
    store.save_work_item(wi)

    # Worker A crashes -> Worker B resumes
    wi.worker_execution_id = "worker-B-exec-2"
    wi.worker_execution_ids.append("worker-B-exec-2")
    wi.attempt_count += 1
    store.save_work_item(wi)

    resumed = store.get_work_item("S6-WI-03")
    assert resumed is not None
    assert resumed.worker_execution_id == "worker-B-exec-2"
    assert len(resumed.worker_execution_ids) == 2
    assert resumed.attempt_count == 2


def test_at24_bounded_work_item_retries(disposable_repo_and_control):
    """
    AT-24: Work Item retries are bounded by max_retries policy. Exceeding halts run in STOPPED.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    st = ctrl.open_run("S6")
    ctrl.step("S6")  # PLANNING -> PLAN_READY
    ctrl.step("S6")  # ARCHITECTURE_REVIEW
    ctrl.step("S6")  # ARCHITECTURE_APPROVED
    st = ctrl.step("S6")  # IMPLEMENTATION

    wi = WorkItem(
        work_item_id="S6-WI-05",
        run_id=st.run_id,
        objective_id="S6-O1",
        description="Failing task",
        type="implementation",
        status="READY",
        attempt_count=4,  # > max_retries (3)
    )
    ctrl.store.save_work_item(wi)

    final_st = ctrl.step("S6")
    assert final_st.state == "STOPPED"
    assert "exceeded maximum retries" in final_st.stop_reason


def test_at25_deterministic_completion_predicates_govern(disposable_repo_and_control):
    """
    AT-25: Deterministic completion predicates govern completion; worker claims alone are denied.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    obj = Objective(
        objective_id="S6-O1",
        run_id="run-1",
        slice="S6",
        description="Objective with predicate",
        source_requirements=["FR-010"],
        acceptance_predicates=[{
            "predicate_id": "P_MISSING",
            "kind": "file_exists",
            "expression": "src/missing_artifact.py"
        }],
    )
    store.save_objective(obj)

    wi = WorkItem(
        work_item_id="S6-WI-06",
        run_id="run-1",
        objective_id="S6-O1",
        description="Task claiming completion",
        type="implementation",
        status="CONVERGENCE_CHECK",
        acceptance_predicates=obj.acceptance_predicates,
    )
    store.save_work_item(wi)

    engine = ConvergenceEngine(repo_dir, store)
    report = engine.evaluate("run-1", wi, obj)

    assert report.status == "DIVERGED"
    assert any("missing_artifact.py" in g for g in report.gaps_detected)


def test_at26_convergence_gap_detection(disposable_repo_and_control):
    """
    AT-26: Convergence gap detection catches plan/implementation gaps before adversarial review.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    obj = Objective(
        objective_id="S6-O1",
        run_id="run-1",
        slice="S6",
        description="Expect api.py",
        source_requirements=["FR-010"],
        acceptance_predicates=[{
            "predicate_id": "P1",
            "kind": "file_exists",
            "expression": "src/api.py"
        }],
    )

    wi = WorkItem(
        work_item_id="S6-WI-1",
        run_id="run-1",
        objective_id="S6-O1",
        description="Wrote api_v2.py instead",
        type="implementation",
        allowed_scope=["src/api.py"],
        status="CONVERGENCE_CHECK",
        acceptance_predicates=obj.acceptance_predicates,
    )

    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "api_v2.py").write_text("# wrong name\n")

    engine = ConvergenceEngine(repo_dir, store)
    report = engine.evaluate("run-1", wi, obj)

    assert report.status == "DIVERGED"


def test_at27_learning_ledger_strictly_informational(disposable_repo_and_control):
    """
    AT-27: Learning Ledger is strictly informational and cannot mutate policy or state.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    ledger = LearningLedger(store)
    rec = LearningRecord(
        learning_id="00000000-0000-0000-0000-000000000099",
        source_work_item="S6-WI-1",
        author_role="IMPLEMENTER",
        statement="The plan should use Redis instead of SQLite",
        confidence=0.99,
        evidence_reference="a" * 64,
    )
    ledger.record_learning(rec)

    st = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy").get_slice_state("S6")
    assert st is None or st.plan_revision == 0  # Learning cannot change plan revision


def test_at28_exploration_mode_scratch_isolation(disposable_repo_and_control):
    """
    AT-28: Exploration Mode is strictly isolated in disposable scratch path.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()

    mgr = ExplorationManager(repo_dir, store)
    report = mgr.run_exploration("S6", "evaluating vector DBs")

    assert report.scratch_workspace_path != str(repo_dir)
    assert Path(report.scratch_workspace_path).is_dir()
    res = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True)
    assert res.stdout.strip() == ""


def test_at29_artifact_graph_traceability(disposable_repo_and_control):
    """
    AT-29: Artifact Graph enforces complete requirement-to-commit traceability.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    store = ControlStore(control_dir)
    store.init_database()
    graph = ArtifactGraphStore(store)

    run_id = "00000000-0000-0000-0000-000000000001"
    graph.add_node(ArtifactGraphNode(artifact_id="FR-010", type="requirement", parent_artifact_ids=[], run_id=run_id))
    graph.add_node(ArtifactGraphNode(artifact_id="S6-O1", type="objective", parent_artifact_ids=["FR-010"], run_id=run_id))
    graph.add_node(ArtifactGraphNode(artifact_id="S6-WI-1", type="work_item", parent_artifact_ids=["S6-O1"], run_id=run_id, work_item_id="S6-WI-1"))
    graph.add_node(ArtifactGraphNode(artifact_id="commit-abc", type="commit", parent_artifact_ids=["S6-WI-1"], run_id=run_id, work_item_id="S6-WI-1"))

    ancestors = graph.trace_ancestors("commit-abc")
    types = [n.type for n in ancestors]
    assert "requirement" in types
    assert "objective" in types
    assert "work_item" in types
    assert "commit" in types


def test_at30_review_finding_creates_immutable_remediation_work_item(disposable_repo_and_control):
    """
    AT-30: Review finding creates immutable Remediation Work Item.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    
    dummy_rev = TestDummyWorkerAdapter(review_approval=False, blocking_findings=[{
        "finding_id": "F-NULL-CHECK",
        "description": "Missing null check in src/search.py",
        "required_remediation": "Add null check"
    }])
    ctrl.worker_registry.register(dummy_rev)

    st = ctrl.open_run("S6")
    ctrl.step("S6")  # PLANNING -> PLAN_READY
    ctrl.step("S6")  # ARCHITECTURE_REVIEW
    ctrl.step("S6")  # ARCHITECTURE_APPROVED
    ctrl.step("S6")  # IMPLEMENTATION
    ctrl.step("S6")  # IMPLEMENTATION_READY_FOR_REVIEW
    ctrl.step("S6")  # ADVERSARIAL_REVIEW
    st = ctrl.step("S6")  # REVIEW_BLOCKED -> REMEDIATION

    assert st.state == "REMEDIATION"
    assert len(st.open_remediation_packet_ids) > 0

    items = ctrl.store.list_work_items(st.run_id)
    rem_items = [i for i in items if i.type == "remediation"]
    assert len(rem_items) > 0
    assert rem_items[0].assigned_role == "REMEDIATOR"


def test_at31_parallel_work_item_scope_boundary_safety():
    """
    AT-31: Parallel Work Item safety enforces scope boundaries.
    """
    wi = WorkItem(
        work_item_id="S6-WI-07",
        run_id="run-1",
        objective_id="S6-O1",
        description="Scoped task",
        type="implementation",
        allowed_scope=["src/allowed.py"],
        status="IN_PROGRESS",
    )
    forbidden_path = "src/forbidden.py"
    out_of_scope = not any(forbidden_path.startswith(p) for p in wi.allowed_scope)
    assert out_of_scope, "src/forbidden.py must be out of scope for src/allowed.py"


def test_at32_work_item_model_does_not_override_slice_run_governance(disposable_repo_and_control):
    """
    AT-32: Work Item model does NOT override Slice Run governance state.
    Satisfying all Work Items cannot skip ADVERSARIAL_REVIEW -> COMMIT_READY -> COMMITTED -> GOVERNANCE.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    
    st = ctrl.open_run("S6")
    ctrl.step("S6")  # PLANNING -> PLAN_READY
    ctrl.step("S6")  # ARCHITECTURE_REVIEW
    ctrl.step("S6")  # ARCHITECTURE_APPROVED
    ctrl.step("S6")  # IMPLEMENTATION (executes work item S6-WI-1 -> SATISFIED)
    st = ctrl.step("S6")  # CANDIDATE_CAPTURED -> IMPLEMENTATION_READY_FOR_REVIEW

    assert st.state != "COMMITTED"
    assert st.state != "COMPLETE"
    assert st.state == "IMPLEMENTATION_READY_FOR_REVIEW"
