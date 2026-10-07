"""
Tests for Polyglot Project Configuration (.slice.toml, .slice.yaml, pyproject.toml [tool.slice]).
Verifies auto-detection and custom test runner configuration across Python, Node, Rust, and Go.
"""

import os
from pathlib import Path
import pytest

from slice_orchestrator.config import ProjectConfig, load_project_config
from slice_orchestrator.orchestrator import SliceRunController


def test_default_python_detection(tmp_path: Path):
    """If pyproject.toml exists with no config, default to pytest."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n', encoding="utf-8")
    config = load_project_config(tmp_path)
    cmd = config.get_test_command_argv(tmp_path)
    assert "-m" in cmd
    assert "pytest" in cmd
    assert "-q" in cmd


def test_slice_toml_custom_test_command(tmp_path: Path):
    """Custom test command in .slice.toml overrides defaults."""
    slice_toml = tmp_path / ".slice.toml"
    slice_toml.write_text("""
[project]
name = "node-app"
language = "typescript"

[test]
command = "npm test -- --bail"
timeout_seconds = 45
expected_exit_code = 0

[scope]
default_allow_paths = ["src/**", "tests/**"]
protected_files = ["package-lock.json"]
""", encoding="utf-8")

    config = load_project_config(tmp_path)
    assert config.project_name == "node-app"
    assert config.language == "typescript"
    assert config.test_timeout_seconds == 45
    assert config.default_allow_paths == ["src/**", "tests/**"]
    assert config.protected_files == ["package-lock.json"]

    argv = config.get_test_command_argv(tmp_path)
    assert argv == ["npm", "test", "--", "--bail"]


def test_slice_yaml_support(tmp_path: Path):
    """.slice.yaml parses correctly if present."""
    slice_yaml = tmp_path / ".slice.yaml"
    slice_yaml.write_text("""
project:
  name: "rust-crate"
  language: "rust"
test:
  command: "cargo test --quiet"
""", encoding="utf-8")

    config = load_project_config(tmp_path)
    assert config.project_name == "rust-crate"
    assert config.get_test_command_argv(tmp_path) == ["cargo", "test", "--quiet"]


def test_pyproject_tool_slice_support(tmp_path: Path):
    """pyproject.toml [tool.slice] parses correctly."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""
[project]
name = "my-service"

[tool.slice.project]
name = "governed-service"

[tool.slice.test]
command = "pytest -k unit -v"
timeout_seconds = 30
""", encoding="utf-8")

    config = load_project_config(tmp_path)
    assert config.project_name == "governed-service"
    assert config.test_timeout_seconds == 30
    assert config.get_test_command_argv(tmp_path) == ["pytest", "-k", "unit", "-v"]


def test_auto_detect_node(tmp_path: Path):
    """package.json without Python project files defaults to npm test."""
    (tmp_path / "package.json").write_text('{"name": "my-pkg"}', encoding="utf-8")
    config = load_project_config(tmp_path)
    assert config.get_test_command_argv(tmp_path) == ["npm", "test"]


def test_auto_detect_rust(tmp_path: Path):
    """Cargo.toml without Python project files defaults to cargo test."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "my-crate"', encoding="utf-8")
    config = load_project_config(tmp_path)
    assert config.get_test_command_argv(tmp_path) == ["cargo", "test"]


def test_auto_detect_go(tmp_path: Path):
    """go.mod without Python project files defaults to go test."""
    (tmp_path / "go.mod").write_text("module example.com/mod\ngo 1.22", encoding="utf-8")
    config = load_project_config(tmp_path)
    assert config.get_test_command_argv(tmp_path) == ["go", "test", "./..."]


def test_slice_test_args_env_var(tmp_path: Path, monkeypatch):
    """SLICE_TEST_ARGS appends extra flags to the resolved test command."""
    monkeypatch.setenv("SLICE_TEST_ARGS", "-m unit --tb=short")
    config = load_project_config(tmp_path)
    argv = config.get_test_command_argv(tmp_path)
    assert "-m" in argv
    assert "unit" in argv
    assert "--tb=short" in argv


def test_controller_uses_project_config(disposable_repo_and_control):
    """SliceRunController._authorized_test_def reflects .slice.toml in repo."""
    repo_dir, control_dir, _ = disposable_repo_and_control
    (repo_dir / ".slice.toml").write_text("""
[test]
command = "pytest tests/ -k test_ok"
timeout_seconds = 15
expected_exit_code = 0
""", encoding="utf-8")

    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    test_def = ctrl._authorized_test_def()
    assert test_def["command"] == ["pytest", "tests/", "-k", "test_ok"]
    assert test_def["timeout_sec"] == 15
    assert test_def["expected_exit_code"] == 0
