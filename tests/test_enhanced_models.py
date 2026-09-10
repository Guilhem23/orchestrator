"""
Unit tests for Enhanced Method v4 Models: Objectives, Work Items, DAG Supervisor,
Learning Ledger, and Artifact Graph persistence.
"""

import tempfile
from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.objectives import Objective
from slice_orchestrator.work_items import WorkItem, WorkItemDAGSupervisor
from slice_orchestrator.learnings import LearningRecord, LearningLedger
from slice_orchestrator.artifact_graph import ArtifactGraphNode, ArtifactGraphStore


def test_objective_model_and_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        store = ControlStore(home)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        obj = Objective(
            objective_id="S6-O1",
            run_id="00000000-0000-0000-0000-000000000001",
            slice="S6",
            description="Provide lexical search",
            source_requirements=["FR-010"],
            acceptance_predicates=[{
                "predicate_id": "P1",
                "kind": "test_pass",
                "expression": "pytest tests/unit/test_s6_search_service.py"
            }],
            dependencies=[],
            status="PENDING",
            plan_revision=1,
        )

        digest = store.save_objective(obj)
        assert digest is not None

        loaded = store.get_objective("S6-O1")
        assert loaded is not None
        assert loaded.objective_id == "S6-O1"
        assert loaded.description == "Provide lexical search"
        assert loaded.source_requirements == ["FR-010"]
        assert loaded.status == "PENDING"


def test_work_item_model_and_dag_supervisor():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        store = ControlStore(home)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        run_id = "00000000-0000-0000-0000-000000000001"
        wi1 = WorkItem(
            work_item_id="S6-WI-1",
            run_id=run_id,
            objective_id="S6-O1",
            description="Create search schema",
            type="implementation",
            dependencies=[],
            allowed_scope=["src/search/schema.py"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="exec-1",
            status="SATISFIED",
            input_artifacts=[],
            output_artifacts=[],
            acceptance_predicates=[],
            revision=1,
        )

        wi2 = WorkItem(
            work_item_id="S6-WI-2",
            run_id=run_id,
            objective_id="S6-O1",
            description="Implement search query engine",
            type="implementation",
            dependencies=["S6-WI-1"],
            allowed_scope=["src/search/engine.py"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="exec-2",
            status="PENDING",
            input_artifacts=[],
            output_artifacts=[],
            acceptance_predicates=[],
            revision=1,
        )

        store.save_work_item(wi1)
        store.save_work_item(wi2)

        items = store.list_work_items(run_id)
        assert len(items) == 2

        supervisor = WorkItemDAGSupervisor()
        valid, err = supervisor.validate_dag(items)
        assert valid, f"DAG should be valid: {err}"

        updated = supervisor.derive_readiness(items)
        wi2_updated = [item for item in updated if item.work_item_id == "S6-WI-2"][0]
        assert wi2_updated.status == "READY"


def test_work_item_cycle_detection():
    run_id = "00000000-0000-0000-0000-000000000001"
    wi1 = WorkItem(
        work_item_id="S6-WI-1",
        run_id=run_id,
        objective_id="S6-O1",
        description="Task 1",
        type="implementation",
        dependencies=["S6-WI-2"],
        allowed_scope=["src/a.py"],
        assigned_role="IMPLEMENTER",
        worker_execution_id="exec-1",
        status="PENDING",
        input_artifacts=[],
        output_artifacts=[],
        acceptance_predicates=[],
        revision=1,
    )
    wi2 = WorkItem(
        work_item_id="S6-WI-2",
        run_id=run_id,
        objective_id="S6-O1",
        description="Task 2",
        type="implementation",
        dependencies=["S6-WI-1"],
        allowed_scope=["src/b.py"],
        assigned_role="IMPLEMENTER",
        worker_execution_id="exec-2",
        status="PENDING",
        input_artifacts=[],
        output_artifacts=[],
        acceptance_predicates=[],
        revision=1,
    )

    supervisor = WorkItemDAGSupervisor()
    valid, err = supervisor.validate_dag([wi1, wi2])
    assert not valid
    assert "Cycle" in err or "cycle" in err.lower()


def test_learning_ledger_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        store = ControlStore(home)
        store.init_database()

        ledger = LearningLedger(store)
        rec = LearningRecord(
            learning_id="00000000-0000-0000-0000-000000000010",
            source_work_item="S6-WI-1",
            author_role="IMPLEMENTER",
            statement="SQLite WAL mode improves local concurrency",
            confidence=0.9,
            evidence_reference="a" * 64,
        )

        ledger.record_learning(rec)

        learnings = ledger.list_learnings()
        assert len(learnings) == 1
        assert learnings[0].statement == "SQLite WAL mode improves local concurrency"
        assert (home / "learnings").is_dir()


def test_artifact_graph_traceability():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        store = ControlStore(home)
        store.init_database()

        graph = ArtifactGraphStore(store)

        run_id = "00000000-0000-0000-0000-000000000001"
        graph.add_node(ArtifactGraphNode(
            artifact_id="FR-010",
            type="requirement",
            parent_artifact_ids=[],
            run_id=run_id,
            work_item_id="",
            revision=1,
            hash="a" * 64,
            creator_role="PLANNER"
        ))

        graph.add_node(ArtifactGraphNode(
            artifact_id="S6-O1",
            type="objective",
            parent_artifact_ids=["FR-010"],
            run_id=run_id,
            work_item_id="",
            revision=1,
            hash="b" * 64,
            creator_role="PLANNER"
        ))

        graph.add_node(ArtifactGraphNode(
            artifact_id="S6-WI-1",
            type="work_item",
            parent_artifact_ids=["S6-O1"],
            run_id=run_id,
            work_item_id="S6-WI-1",
            revision=1,
            hash="c" * 64,
            creator_role="PLANNER"
        ))

        graph.add_node(ArtifactGraphNode(
            artifact_id="commit-123",
            type="commit",
            parent_artifact_ids=["S6-WI-1"],
            run_id=run_id,
            work_item_id="S6-WI-1",
            revision=1,
            hash="d" * 64,
            creator_role="COMMIT_MANAGER"
        ))

        ancestors = graph.trace_ancestors("commit-123")
        ancestor_ids = [n.artifact_id for n in ancestors]
        assert "S6-WI-1" in ancestor_ids
        assert "S6-O1" in ancestor_ids
        assert "FR-010" in ancestor_ids
