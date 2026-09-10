"""
Unit tests for Deterministic Predicates and Convergence Engine.
"""

import tempfile
from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.objectives import Objective
from slice_orchestrator.work_items import WorkItem
from slice_orchestrator.predicates import PredicateEvaluator
from slice_orchestrator.convergence import ConvergenceEngine


def test_file_exists_and_schema_predicates():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        evaluator = PredicateEvaluator(workspace)

        # File exists
        test_file = workspace / "src" / "sample.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("print('hello')\n")

        res1 = evaluator.evaluate({
            "predicate_id": "P1",
            "kind": "file_exists",
            "expression": "src/sample.py"
        })
        assert res1.passed

        res2 = evaluator.evaluate({
            "predicate_id": "P2",
            "kind": "file_exists",
            "expression": "src/missing.py"
        })
        assert not res2.passed

        # File content matches
        res3 = evaluator.evaluate({
            "predicate_id": "P3",
            "kind": "file_content_matches",
            "expression": "src/sample.py::hello"
        })
        assert res3.passed


def test_convergence_engine_pass():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".slice-orchestrator"
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        store = ControlStore(home)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        # Create file expected by work item
        (repo / "src").mkdir()
        (repo / "src" / "impl.py").write_text("# Implementation code\n")

        run_id = "00000000-0000-0000-0000-000000000001"
        obj = Objective(
            objective_id="S6-O1",
            run_id=run_id,
            slice="S6",
            description="Impl search",
            source_requirements=["FR-010"],
            acceptance_predicates=[{
                "predicate_id": "P1",
                "kind": "file_exists",
                "expression": "src/impl.py"
            }],
            status="IN_PROGRESS"
        )
        store.save_objective(obj)

        wi = WorkItem(
            work_item_id="S6-WI-1",
            run_id=run_id,
            objective_id="S6-O1",
            description="Write search impl",
            type="implementation",
            dependencies=[],
            allowed_scope=["src/impl.py"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="exec-1",
            status="CONVERGENCE_CHECK",
            input_artifacts=[],
            output_artifacts=[],
            acceptance_predicates=[{
                "predicate_id": "P1",
                "kind": "file_exists",
                "expression": "src/impl.py"
            }],
            revision=1,
        )
        store.save_work_item(wi)

        engine = ConvergenceEngine(repo, store)
        report = engine.evaluate(run_id, wi, obj)

        assert report.status == "CONVERGED"
        assert len(report.gaps_detected) == 0


def test_convergence_engine_diverged_file_mismatch():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".slice-orchestrator"
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        store = ControlStore(home)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        run_id = "00000000-0000-0000-0000-000000000001"
        obj = Objective(
            objective_id="S6-O1",
            run_id=run_id,
            slice="S6",
            description="Impl search",
            source_requirements=["FR-010"],
            acceptance_predicates=[{
                "predicate_id": "P1",
                "kind": "file_exists",
                "expression": "src/impl.py"
            }],
            status="IN_PROGRESS"
        )
        store.save_objective(obj)

        wi = WorkItem(
            work_item_id="S6-WI-1",
            run_id=run_id,
            objective_id="S6-O1",
            description="Write search impl",
            type="implementation",
            dependencies=[],
            allowed_scope=["src/impl.py"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="exec-1",
            status="CONVERGENCE_CHECK",
            input_artifacts=[],
            output_artifacts=[],
            acceptance_predicates=[{
                "predicate_id": "P1",
                "kind": "file_exists",
                "expression": "src/impl.py"  # File doesn't exist in repo!
            }],
            revision=1,
        )
        store.save_work_item(wi)

        engine = ConvergenceEngine(repo, store)
        report = engine.evaluate(run_id, wi, obj)

        assert report.status == "DIVERGED"
        assert len(report.gaps_detected) > 0
