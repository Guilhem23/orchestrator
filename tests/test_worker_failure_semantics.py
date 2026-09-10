"""Priority 5 — unimplemented and failed workers cannot approve."""

from __future__ import annotations

from pathlib import Path

from slice_orchestrator.orchestrator import SliceRunController
from slice_orchestrator.workers import (
    ClaudeCodeWorkerAdapter,
    CursorWorkerAdapter,
    GeminiWorkerAdapter,
    TestDummyWorkerAdapter,
    WorkerInputBundle,
    WorkerRegistry,
    WorkerResult,
)


def _bundle(tmp: Path, role: str = "ARCHITECTURE_REVIEWER") -> WorkerInputBundle:
    return WorkerInputBundle(
        assignment_id="a1",
        run_id="r1",
        slice="S1",
        role=role,
        prompt="review",
        base_commit_oid="sha1:" + "0" * 40,
        workspace_dir=tmp,
        output_dir=tmp,
    )


def test_unavailable_vendor_adapters():
    for cls, adapter_id in (
        (CursorWorkerAdapter, "cursor"),
        (ClaudeCodeWorkerAdapter, "claude-code"),
        (GeminiWorkerAdapter, "gemini"),
    ):
        res = cls(fallback_to_dummy=False).run(_bundle(Path("/tmp"), "ARCHITECTURE_REVIEWER"))
        assert res.success is False
        assert res.availability == "UNAVAILABLE"
        assert "not implemented" in (res.error_message or "").lower()
        assert res.adapter_id == adapter_id


def test_dummy_is_visibly_test_only():
    res = TestDummyWorkerAdapter().run(_bundle(Path("/tmp"), "PLANNER"))
    assert res.success is True
    assert res.test_only is True
    assert res.availability == "TEST_ONLY"
    assert "TEST-ONLY" in res.summary


def test_failed_architecture_worker_cannot_approve(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    st = ctrl.open_run("S10")
    st = ctrl.step("S10")  # PLAN_READY
    st = ctrl.step("S10")  # ARCHITECTURE_REVIEW
    assert st.state == "ARCHITECTURE_REVIEW"

    class FailedArch(TestDummyWorkerAdapter):
        def run(self, bundle):
            return WorkerResult(
                success=False,
                role=bundle.role,
                execution_id="x",
                worker_instance_id="x",
                adapter_id="dummy",
                availability="UNAVAILABLE",
                error_message="UNAVAILABLE: architecture backend missing",
            )

    ctrl.worker_registry.register(FailedArch())
    st = ctrl.step("S10")
    assert st.state == "FAILED"
    assert st.stop_reason_code == "WORKER_UNAVAILABLE"
    events = [e["event_type"] for e in ctrl.store.get_events() if e["slice"] == "S10"]
    assert "ARCHITECTURE_APPROVED" not in events


def test_unknown_adapter_unavailable():
    registry = WorkerRegistry()
    res = registry.get("not-a-real-backend").run(_bundle(Path("/tmp"), "IMPLEMENTER"))
    assert res.success is False
    assert res.availability == "UNAVAILABLE"


def test_cursor_adapter_does_not_silently_select_dummy():
    registry = WorkerRegistry(allow_dummy_fallback=False)
    res = registry.get("cursor").run(_bundle(Path("/tmp"), "IMPLEMENTER"))
    assert res.success is False
    assert res.availability == "UNAVAILABLE"
    assert res.test_only is False
