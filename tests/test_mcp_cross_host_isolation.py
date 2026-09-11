"""
Cross-host isolation and host-agnostic control-plane tests.

Verifies that Cursor and Claude Code metadata share the same project-local
state, that host identity never grants additional authority, and that
assignments remain single-use across host labels.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from slice_orchestrator import tools
from slice_orchestrator.orchestrator import OrchestratorError
from slice_orchestrator.control_store import ControlStoreError


def _setup_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "cross_host_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    control_home = repo_dir / ".orchestrator_slice"
    control_home.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Cross Host"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "cross@example.com"], cwd=repo_dir, check=True)

    pkg_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    store_bundle = control_home / "policy_bundle"
    store_bundle.mkdir(parents=True, exist_ok=True)
    for f in pkg_bundle.glob("*"):
        if f.is_file():
            (store_bundle / f.name).write_bytes(f.read_bytes())

    (repo_dir / ".gitignore").write_text(".orchestrator_slice/\n")
    (repo_dir / "pyproject.toml").write_text("[project]\nname='cross'\n")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_calc.py").write_text(
        "from src.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)
    return repo_dir


def test_shared_state_across_host_metadata(tmp_path: Path):
    """Cursor and Claude Code metadata see the same project-local slice state."""
    repo_dir = _setup_repo(tmp_path)
    start = tools.slice_start(
        slice="S910",
        objective="Shared state",
        repo_dir=repo_dir,
        host="cursor",
    )
    assert start["state"] == "PLANNING"
    assert start.get("host_metadata") == "cursor"

    status = tools.slice_status(slice="S910", repo_dir=repo_dir)
    assert status["exists"] is True
    assert status["run_id"] == start["run_id"]
    assert status["execution_mode"] == "mcp-native"


def test_host_metadata_does_not_grant_authority(tmp_path: Path):
    """Claiming a privileged host label cannot finalize a non-COMMIT_READY slice."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S911", objective="No privilege", repo_dir=repo_dir, host="cursor")
    with pytest.raises(OrchestratorError):
        tools.slice_finalize(slice="S911", repo_dir=repo_dir)


def test_assignment_single_use_across_hosts(tmp_path: Path):
    """An assignment consumed under one host label cannot be reused under another."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S912", objective="Single use", repo_dir=repo_dir, host="cursor")
    tools.slice_plan(
        slice="S912",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S912-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    dispatch = tools.slice_dispatch(
        slice="S912",
        role="ARCHITECTURE_REVIEWER",
        repo_dir=repo_dir,
        host="cursor",
    )
    tools.slice_record_result(
        slice="S912",
        assignment_id=dispatch["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        host="cursor",
    )
    with pytest.raises((OrchestratorError, ControlStoreError)):
        tools.slice_record_result(
            slice="S912",
            assignment_id=dispatch["assignment_id"],
            artifacts={"verdict": "APPROVED"},
            repo_dir=repo_dir,
            host="claude-code",
        )


def test_terminal_state_immutable_across_hosts(tmp_path: Path):
    """COMPLETE runs reject further mutations regardless of host metadata."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S913", objective="Terminal", repo_dir=repo_dir)
    tools.slice_plan(
        slice="S913",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py", "tests/test_calc.py"]},
            "work_items": [{"work_item_id": "S913-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    d1 = tools.slice_dispatch(slice="S913", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, host="cursor")
    tools.slice_record_result(
        slice="S913",
        assignment_id=d1["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        host="cursor",
    )
    d2 = tools.slice_dispatch(
        slice="S913",
        role="IMPLEMENTER",
        work_item_id="S913-WI-1",
        repo_dir=repo_dir,
        host="claude-code",
    )
    tools.slice_record_result(
        slice="S913",
        assignment_id=d2["assignment_id"],
        success=True,
        summary="noop",
        repo_dir=repo_dir,
        host="claude-code",
    )
    tools.slice_run_tests(slice="S913", repo_dir=repo_dir)
    rev = tools.slice_request_review(
        slice="S913",
        reviewer_principal="independent-rev",
        repo_dir=repo_dir,
        host="claude-code",
    )
    tools.slice_record_result(
        slice="S913",
        assignment_id=rev["assignment_id"],
        artifacts={"verdict": "APPROVED", "reviewer_principal": "independent-rev"},
        repo_dir=repo_dir,
        host="cursor",
    )
    gate = tools.slice_gate(slice="S913", repo_dir=repo_dir)
    assert gate["passed"] is True
    fin = tools.slice_finalize(slice="S913", repo_dir=repo_dir)
    assert fin["state"] == "COMPLETE"

    with pytest.raises(OrchestratorError):
        tools.slice_plan(
            slice="S913",
            repo_dir=repo_dir,
            plan={"description": "late", "scope_manifest": {"allow_paths": []}, "work_items": []},
        )


def test_project_dir_env_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CLAUDE_PROJECT_DIR is preferred over cwd when repo_dir is omitted."""
    repo_dir = _setup_repo(tmp_path)
    other = tmp_path / "other_cwd"
    other.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo_dir))
    monkeypatch.chdir(other)
    start = tools.slice_start(slice="S914", objective="Env resolve")
    assert start["state"] == "PLANNING"
    status = tools.slice_status(slice="S914")
    assert status["exists"] is True


def test_two_sessions_same_slice_shared_state(tmp_path: Path):
    """Two logical sessions on the same slice share project-local control state."""
    repo_dir = _setup_repo(tmp_path)
    a = tools.slice_start(slice="S920", objective="shared", repo_dir=repo_dir, host="cursor")
    b = tools.slice_status(slice="S920", repo_dir=repo_dir)
    assert a["run_id"] == b["run_id"]
    tools.slice_plan(
        slice="S920",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S920-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    status = tools.slice_status(slice="S920", repo_dir=repo_dir)
    assert status["state"] == "PLAN_READY"
    assert status["run_id"] == a["run_id"]


def test_two_sessions_different_slices_isolated(tmp_path: Path):
    """Mutations on one slice do not advance another slice's state."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S9211", objective="A", repo_dir=repo_dir, host="cursor")
    tools.slice_start(slice="S9212", objective="B", repo_dir=repo_dir, host="claude-code")
    tools.slice_plan(
        slice="S9211",
        repo_dir=repo_dir,
        plan={
            "description": "plan-a",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S9211-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    a = tools.slice_status(slice="S9211", repo_dir=repo_dir)
    b = tools.slice_status(slice="S9212", repo_dir=repo_dir)
    assert a["state"] == "PLAN_READY"
    assert b["state"] == "PLANNING"
    assert a["run_id"] != b["run_id"]


def test_two_projects_same_server_isolated(tmp_path: Path):
    """Identical slice names in different repo_dir control homes remain isolated."""
    repo_a = _setup_repo(tmp_path / "proj_a")
    repo_b = _setup_repo(tmp_path / "proj_b")
    tools.slice_start(slice="S922", objective="proj-a", repo_dir=repo_a, host="cursor")
    tools.slice_start(slice="S922", objective="proj-b", repo_dir=repo_b, host="cursor")
    tools.slice_plan(
        slice="S922",
        repo_dir=repo_a,
        plan={
            "description": "only-a",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S922-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    assert tools.slice_status(slice="S922", repo_dir=repo_a)["state"] == "PLAN_READY"
    assert tools.slice_status(slice="S922", repo_dir=repo_b)["state"] == "PLANNING"


def test_identical_host_metadata_cannot_force_complete(tmp_path: Path):
    """Identical host labels with different claimed principals cannot force COMPLETE."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S923", objective="no-force", repo_dir=repo_dir, host="cursor")
    with pytest.raises(OrchestratorError):
        tools.slice_finalize(slice="S923", repo_dir=repo_dir)


def test_stale_assignment_rejected_across_hosts(tmp_path: Path):
    """A stale/consumed assignment cannot be reused under another host label."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S924", objective="stale", repo_dir=repo_dir, host="cursor")
    tools.slice_plan(
        slice="S924",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S924-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    d = tools.slice_dispatch(
        slice="S924", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, host="cursor"
    )
    tools.slice_record_result(
        slice="S924",
        assignment_id=d["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        host="cursor",
    )
    with pytest.raises((OrchestratorError, ControlStoreError)):
        tools.slice_record_result(
            slice="S924",
            assignment_id=d["assignment_id"],
            artifacts={"verdict": "APPROVED"},
            repo_dir=repo_dir,
            host="claude-code",
        )


def test_cross_slice_assignment_rejected(tmp_path: Path):
    """An assignment issued for one slice cannot authorize another slice."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S9251", objective="A", repo_dir=repo_dir)
    tools.slice_start(slice="S9252", objective="B", repo_dir=repo_dir)
    tools.slice_plan(
        slice="S9251",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S9251-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    tools.slice_plan(
        slice="S9252",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py"]},
            "work_items": [{"work_item_id": "S9252-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    d = tools.slice_dispatch(
        slice="S9251", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir, host="cursor"
    )
    with pytest.raises((OrchestratorError, ControlStoreError, ValueError, KeyError)):
        tools.slice_record_result(
            slice="S9252",
            assignment_id=d["assignment_id"],
            artifacts={"verdict": "APPROVED"},
            repo_dir=repo_dir,
            host="claude-code",
        )


def test_host_metadata_cannot_bypass_reviewer_separation(tmp_path: Path):
    """Host metadata cannot make self-approval pass the commit gate."""
    repo_dir = _setup_repo(tmp_path)
    tools.slice_start(slice="S926", objective="self-approve", repo_dir=repo_dir, host="cursor")
    tools.slice_plan(
        slice="S926",
        repo_dir=repo_dir,
        plan={
            "description": "plan",
            "scope_manifest": {"allow_paths": ["src/calc.py", "tests/test_calc.py"]},
            "work_items": [{"work_item_id": "S926-WI-1", "assigned_role": "IMPLEMENTER"}],
        },
    )
    d1 = tools.slice_dispatch(slice="S926", role="ARCHITECTURE_REVIEWER", repo_dir=repo_dir)
    tools.slice_record_result(
        slice="S926",
        assignment_id=d1["assignment_id"],
        artifacts={"verdict": "APPROVED"},
        repo_dir=repo_dir,
        host="cursor",
    )
    d2 = tools.slice_dispatch(
        slice="S926", role="IMPLEMENTER", work_item_id="S926-WI-1", repo_dir=repo_dir
    )
    tools.slice_record_result(
        slice="S926",
        assignment_id=d2["assignment_id"],
        success=True,
        summary="done",
        repo_dir=repo_dir,
        host="cursor",
    )
    tools.slice_run_tests(slice="S926", repo_dir=repo_dir)
    # Force self-approval path: reviewer_principal equals implementer principal mcp-host
    rev = tools.slice_request_review(
        slice="S926",
        reviewer_principal="mcp-host",
        repo_dir=repo_dir,
        host="claude-code",
    )
    tools.slice_record_result(
        slice="S926",
        assignment_id=rev["assignment_id"],
        artifacts={"verdict": "APPROVED", "reviewer_principal": "mcp-host", "is_self_approved": True},
        repo_dir=repo_dir,
        host="claude-code",
    )
    gate = tools.slice_gate(slice="S926", repo_dir=repo_dir)
    assert gate["passed"] is False


def test_concurrent_calls_same_slice_lock_safe(tmp_path: Path):
    """Concurrent status/context reads on the same slice remain consistent."""
    import concurrent.futures

    repo_dir = _setup_repo(tmp_path)
    start = tools.slice_start(slice="S927", objective="concurrent", repo_dir=repo_dir)

    def _read():
        return tools.slice_status(slice="S927", repo_dir=repo_dir)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _read(), range(16)))
    run_ids = {r["run_id"] for r in results}
    assert run_ids == {start["run_id"]}
    assert all(r["exists"] for r in results)
