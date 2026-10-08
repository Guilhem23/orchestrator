"""
Tests for Slice Orchestrator v0.5 Phase 3:
- Developer Armor & One-Click Auto-Fix Engine (AutoFixEngine)
- Reversion of test tampering and scope breaches
- CLI `slice remediate --auto-fix`
"""

import subprocess
from pathlib import Path
import pytest

from slice_orchestrator.auto_fix import AutoFixEngine, AutoFixResult
from slice_orchestrator.tools import slice_start, slice_plan, slice_remediate


def _init_git_repo(repo_dir: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    
    # Create baseline files
    (repo_dir / "src").mkdir(parents=True)
    (repo_dir / "src" / "math_ops.py").write_text("def add(a, b): return a + b\n")
    (repo_dir / "tests").mkdir(parents=True)
    test_file = repo_dir / "tests" / "test_math.py"
    test_file.write_text("from src.math_ops import add\ndef test_add(): assert add(1, 2) == 3\n")
    
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)
    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True)
    return res.stdout.strip()


def test_auto_fix_restores_tampered_test(tmp_path: Path):
    base_oid = _init_git_repo(tmp_path)
    control_home = tmp_path / ".orchestrator_slice"

    # Start and plan slice
    slice_start(slice="S1", repo_dir=tmp_path, control_home=control_home)
    plan_dict = {
        "objective": "Modify math ops",
        "scope_manifest": {"allow_paths": ["src/math_ops.py"]},
        "required_test_plan": [{"id": "t1", "command": "python3 -m pytest tests/test_math.py"}],
    }
    slice_plan(
        slice="S1",
        plan=plan_dict,
        repo_dir=tmp_path,
        control_home=control_home,
    )

    # Tamper with baseline test
    test_file = tmp_path / "tests" / "test_math.py"
    test_file.write_text("def test_add(): assert True  # Tampered!\n")

    fixer = AutoFixEngine(repo_dir=tmp_path, control_home=control_home)
    res = fixer.auto_fix_slice("S1")

    assert res.success is True
    assert res.remediation_type == "TEST_TAMPER_REVERT"
    assert "tests/test_math.py" in res.fixed_files
    # Verify content was restored
    assert "assert add(1, 2) == 3" in test_file.read_text()


def test_auto_fix_reverts_scope_breach(tmp_path: Path):
    base_oid = _init_git_repo(tmp_path)
    control_home = tmp_path / ".orchestrator_slice"

    slice_start(slice="S2", repo_dir=tmp_path, control_home=control_home)
    plan_dict = {
        "objective": "Scoped feature",
        "scope_manifest": {"allow_paths": ["src/math_ops.py"]},
        "required_test_plan": [{"id": "t1", "command": "python3 -m pytest tests/test_math.py"}],
    }
    slice_plan(
        slice="S2",
        plan=plan_dict,
        repo_dir=tmp_path,
        control_home=control_home,
    )

    # Agent touches out of scope file
    rogue_file = tmp_path / "src" / "rogue.py"
    rogue_file.write_text("# Unauthorized code\n")

    fixer = AutoFixEngine(repo_dir=tmp_path, control_home=control_home)
    res = fixer.auto_fix_slice("S2")

    assert res.success is True
    assert res.remediation_type == "SCOPE_BREACH_REVERT"
    assert not rogue_file.exists()
