"""
Target Project Configuration for Slice Orchestrator (Polyglot Engine).
Loads configuration from .slice.toml, .slice.yaml, or pyproject.toml [tool.slice],
with intelligent auto-detection for Python, Node/TypeScript, Rust, and Go.
"""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Standard library tomllib available in Python 3.11+
import tomllib


@dataclass
class ProjectConfig:
    """Configuration loaded from target repository root."""
    project_name: str | None = None
    language: str | None = None
    test_command: list[str] | str | None = None
    test_timeout_seconds: int = 120
    expected_exit_code: int = 0
    lint_command: list[str] | str | None = None
    default_allow_paths: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)
    default_profile: str = "standard"
    source_file: str | None = None

    def get_test_command_argv(self, repo_dir: Path) -> list[str]:
        """
        Return the executable argv list for authorized test execution.
        Applies environment SLICE_TEST_ARGS if provided.
        """
        extra_args = [a for a in os.environ.get("SLICE_TEST_ARGS", "").split() if a]

        if self.test_command:
            if isinstance(self.test_command, list):
                base_cmd = list(self.test_command)
            else:
                base_cmd = shlex.split(str(self.test_command))
            return base_cmd + extra_args

        # Auto-detect by repository files
        repo_venv_py = repo_dir / ".venv" / "bin" / "python"
        repo_venv_py_win = repo_dir / ".venv" / "Scripts" / "python.exe"
        if repo_venv_py.is_file():
            py_bin = str(repo_venv_py)
        elif repo_venv_py_win.is_file():
            py_bin = str(repo_venv_py_win)
        else:
            py_bin = sys.executable

        # Check Node / TypeScript
        if (repo_dir / "package.json").is_file() and not (repo_dir / "pyproject.toml").is_file():
            return ["npm", "test"] + extra_args

        # Check Rust
        if (repo_dir / "Cargo.toml").is_file() and not (repo_dir / "pyproject.toml").is_file():
            return ["cargo", "test"] + extra_args

        # Check Go
        if (repo_dir / "go.mod").is_file() and not (repo_dir / "pyproject.toml").is_file():
            return ["go", "test", "./..."] + extra_args

        # Default to Python pytest
        return [py_bin, "-m", "pytest", "-q"] + extra_args


def load_project_config(repo_dir: Path) -> ProjectConfig:
    """
    Search and parse project configuration from repo_dir:
    1. .slice.toml
    2. .slice.yaml / .slice.yml
    3. pyproject.toml [tool.slice]
    4. Auto-detected defaults
    """
    repo_path = Path(repo_dir).resolve()

    # 1. Check .slice.toml
    slice_toml = repo_path / ".slice.toml"
    if slice_toml.is_file():
        try:
            with open(slice_toml, "rb") as f:
                data = tomllib.load(f)
            return _parse_config_dict(data, source_file=".slice.toml")
        except Exception:
            pass

    # 2. Check .slice.yaml / .slice.yml
    for yaml_name in (".slice.yaml", ".slice.yml", ".orchestrator.yaml", ".orchestrator.yml"):
        slice_yaml = repo_path / yaml_name
        if slice_yaml.is_file():
            try:
                import yaml
                data = yaml.safe_load(slice_yaml.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return _parse_config_dict(data, source_file=yaml_name)
            except Exception:
                pass

    # 3. Check pyproject.toml [tool.slice]
    pyproject = repo_path / "pyproject.toml"
    if pyproject.is_file():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            slice_section = data.get("tool", {}).get("slice")
            if isinstance(slice_section, dict):
                return _parse_config_dict(slice_section, source_file="pyproject.toml")
        except Exception:
            pass

    # 4. Default configuration
    return ProjectConfig()


def _parse_config_dict(data: dict[str, Any], source_file: str) -> ProjectConfig:
    project_sec = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    test_sec = data.get("test", {}) if isinstance(data.get("test"), dict) else {}
    scope_sec = data.get("scope", {}) if isinstance(data.get("scope"), dict) else {}
    gov_sec = data.get("governance", {}) if isinstance(data.get("governance"), dict) else {}

    # Extract test command (can be under [test] command or top-level test_command)
    test_cmd = test_sec.get("command", data.get("test_command"))
    test_timeout = int(test_sec.get("timeout_seconds", data.get("test_timeout_seconds", 120)))
    expected_exit = int(test_sec.get("expected_exit_code", data.get("expected_exit_code", 0)))

    # Extract lint command
    lint_sec = data.get("lint", {}) if isinstance(data.get("lint"), dict) else {}
    lint_cmd = lint_sec.get("command", data.get("lint_command"))

    # Extract scope
    allow_paths = scope_sec.get("default_allow_paths", data.get("default_allow_paths", []))
    protected = scope_sec.get("protected_files", data.get("protected_files", []))

    # Profile
    profile = gov_sec.get("default_profile", data.get("default_profile", "standard"))

    return ProjectConfig(
        project_name=project_sec.get("name", data.get("project_name")),
        language=project_sec.get("language", data.get("language")),
        test_command=test_cmd,
        test_timeout_seconds=test_timeout,
        expected_exit_code=expected_exit,
        lint_command=lint_cmd,
        default_allow_paths=list(allow_paths) if isinstance(allow_paths, (list, tuple)) else [],
        protected_files=list(protected) if isinstance(protected, (list, tuple)) else [],
        default_profile=str(profile),
        source_file=source_file,
    )
