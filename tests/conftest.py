"""
Reusable Security Fixtures for Step 2 Product Orchestrator Remediation Tests.

All security fixtures use disposable OS-level temporary directories, Git repositories,
and subprocess execution environments. Production files are never modified.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def disposable_repo_and_control(tmp_path: Path):
    """
    Creates a disposable Git repository and control home directory.
    Configures git user identity and creates an initial commit.
    """
    repo_dir = tmp_path / "repo"
    control_dir = tmp_path / "control"
    slice_dir = repo_dir / ".orchestrator_slice"
    
    repo_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)
    slice_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "SecurityTestOperator"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "security-test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    
    # Create initial files plus an honest passing test suite
    (repo_dir / "README.md").write_text("# Disposable Security Test Repository\n")
    from tests.workspace_support import seed_passing_workspace
    seed_passing_workspace(repo_dir)
    
    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial security baseline commit"], cwd=repo_dir, check=True, capture_output=True)

    return repo_dir, control_dir, slice_dir


@pytest.fixture
def isolated_subprocess_runner():
    """
    Runner for executing worker scripts in isolated OS subprocesses.
    """
    def run_worker_process(script_code: str, cwd: Path, env_override: dict = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_override:
            env.update(env_override)
        
        cmd = [sys.executable, "-c", script_code]
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    return run_worker_process


@pytest.fixture
def read_only_dir(tmp_path: Path):
    """
    Creates a directory with read-only permissions (0o555) to test permission denial.
    """
    ro_path = tmp_path / "read_only_store"
    ro_path.mkdir(parents=True, exist_ok=True)
    (ro_path / "protected.file").write_text("protected content\n")
    os.chmod(ro_path / "protected.file", 0o444)
    os.chmod(ro_path, 0o555)
    
    yield ro_path
    
    # Cleanup permissions
    os.chmod(ro_path, 0o755)
    os.chmod(ro_path / "protected.file", 0o644)
