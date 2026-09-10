"""
Unit tests for Remediation Work Items, Worker Context & Replacement, and Exploration Mode.
"""

import tempfile
from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.objectives import Objective
from slice_orchestrator.work_items import WorkItem
from slice_orchestrator.exploration import ExplorationManager
from slice_orchestrator.workers import WorkerInputBundle, TestDummyWorkerAdapter, WorkerRegistry


def test_exploration_mode_scratch_isolation():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".slice-orchestrator"
        repo = Path(tmpdir) / "repo"
        repo.mkdir()
        (repo / "prod.py").write_text("# Production file\n")

        store = ControlStore(home)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        mgr = ExplorationManager(repo, store)
        report = mgr.run_exploration("S6", "evaluating vector indexing alternatives")

        assert report.exploration_id is not None
        assert report.topic == "evaluating vector indexing alternatives"
        assert (home / "scratch").is_dir()
        # Ensure production repo was not written by exploration
        assert (repo / "prod.py").read_text() == "# Production file\n"
        # Ensure record was saved
        rec = store.get_record(report.report_id)
        assert rec is not None


def test_worker_context_and_replacement():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".slice-orchestrator"
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        store = ControlStore(home)
        blueprint_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
        store.initialize_policy_bundle(blueprint_bundle)
        store.init_database()

        wi = WorkItem(
            work_item_id="S6-WI-1",
            run_id="run-1",
            objective_id="S6-O1",
            description="Impl search",
            type="implementation",
            dependencies=[],
            allowed_scope=["src/impl.py"],
            assigned_role="IMPLEMENTER",
            worker_execution_id="exec-original",
            status="IN_PROGRESS",
            attempt_count=1,
            worker_execution_ids=["exec-original"],
            revision=1,
        )
        store.save_work_item(wi)

        # Worker 1 fails -> worker replacement with exec-replacement
        wi.attempt_count += 1
        wi.worker_execution_id = "exec-replacement"
        wi.worker_execution_ids.append("exec-replacement")
        store.save_work_item(wi)

        loaded = store.get_work_item("S6-WI-1")
        assert loaded is not None
        assert loaded.attempt_count == 2
        assert loaded.worker_execution_id == "exec-replacement"
        assert len(loaded.worker_execution_ids) == 2
