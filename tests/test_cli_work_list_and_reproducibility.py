"""CLI work-list, default control-home lifecycle, and clean-checkout notes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from slice_orchestrator.cli import main
from slice_orchestrator.orchestrator import SliceRunController
from tests.workspace_support import seed_passing_workspace


def _copy_policy(dest: Path) -> None:
    import shutil
    src = Path(__file__).resolve().parents[1] / ".orchestrator"
    shutil.copytree(src, dest / ".orchestrator")


def test_work_list_cli_after_plan(disposable_repo_and_control, monkeypatch, capsys):
    repo_dir, control_dir, _ = disposable_repo_and_control
    import slice_orchestrator.cli as cli_mod

    def patched(repo_dir=None, control_home=None, adapter_id="dummy"):
        cwd = (repo_dir or Path.cwd()).resolve()
        return SliceRunController(cwd, control_dir, configured_adapter_id=adapter_id)

    monkeypatch.setattr(cli_mod, "get_controller", patched)
    monkeypatch.chdir(repo_dir)
    assert main(["plan", "S23"]) == 0
    capsys.readouterr()
    assert main(["work", "list", "S23"]) == 0
    out = capsys.readouterr().out
    assert "Objectives" in out
    assert "Work Items" in out


def test_production_default_control_home_can_complete(tmp_path: Path):
    """CLI default layout: control home is repo/.orchestrator_slice."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    seed_passing_workspace(repo)
    _copy_policy(repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.run(
        [sys.executable, "-m", "slice_orchestrator.cli", "--adapter", "dummy", "run", "S24"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "COMPLETE" in proc.stdout
    assert (repo / ".orchestrator_slice" / "state.db").is_file()
    status = subprocess.run(
        [sys.executable, "-m", "slice_orchestrator.cli", "status", "S24"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "COMPLETE" in status.stdout


def test_clean_checkout_reproducibility_command_surface():
    """Documented install/test commands exist; HEAD is not claimed equivalent to this tree."""
    root = Path(__file__).resolve().parents[1]
    assert (root / "pyproject.toml").is_file()
    assert (root / "slice_orchestrator" / "cli.py").is_file()
    assert (root / ".orchestrator" / "event.schema.json").is_file()
