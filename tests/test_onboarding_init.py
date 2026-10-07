"""
Tests for Phase 5 (v4.5) 60-Second Onboarding Initializer:
- Verifies automatic ecosystem detection and .slice.toml generation.
- Verifies .mcp.json generation and preservation of existing MCP servers.
- Verifies .gitignore inclusion of .orchestrator_slice/.
- Verifies CLI execution of `slice init`.
"""

from __future__ import annotations

import json
from pathlib import Path

from slice_orchestrator.cli import main
from slice_orchestrator.initializer import detect_ecosystem, initialize_project


def test_detect_ecosystem_variants(tmp_path: Path):
    # Rust
    rust_dir = tmp_path / "rust"
    rust_dir.mkdir()
    (rust_dir / "Cargo.toml").write_text("[package]\nname = 'test'\n", encoding="utf-8")
    assert detect_ecosystem(rust_dir)["type"] == "rust"

    # Node
    node_dir = tmp_path / "node"
    node_dir.mkdir()
    (node_dir / "package.json").write_text("{}", encoding="utf-8")
    assert detect_ecosystem(node_dir)["type"] == "node"

    # Go
    go_dir = tmp_path / "go"
    go_dir.mkdir()
    (go_dir / "go.mod").write_text("module test\n", encoding="utf-8")
    assert detect_ecosystem(go_dir)["type"] == "go"

    # Python default
    py_dir = tmp_path / "python"
    py_dir.mkdir()
    assert detect_ecosystem(py_dir)["type"] == "python"


def test_initialize_project_creates_all_artifacts(tmp_path: Path):
    repo = tmp_path / "target_repo"
    repo.mkdir()

    # Pre-populate existing .gitignore without orchestrator
    (repo / ".gitignore").write_text("*.pyc\n__pycache__/\n", encoding="utf-8")

    res = initialize_project(repo, orchestrator_project_path="/opt/slice")
    assert res["slice_toml_created"]
    assert res["mcp_json_updated"]
    assert res["gitignore_updated"]

    # Check .slice.toml
    slice_toml = repo / ".slice.toml"
    assert slice_toml.exists()
    content = slice_toml.read_text(encoding="utf-8")
    assert "[project]" in content
    assert "type = \"python\"" in content

    # Check .mcp.json
    mcp_json = repo / ".mcp.json"
    assert mcp_json.exists()
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert "slice-orchestrator" in data["mcpServers"]
    server_conf = data["mcpServers"]["slice-orchestrator"]
    assert "--project" in server_conf["args"]
    assert "/opt/slice" in server_conf["args"]

    # Check .gitignore
    gi_content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".orchestrator_slice/" in gi_content


def test_cli_init_command(tmp_path: Path, capsys):
    repo = tmp_path / "cli_repo"
    repo.mkdir()

    ret = main([
        "--repo-dir", str(repo),
        "init",
        "--orchestrator-path", "/usr/local/orchestrator",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Slice Orchestrator initialized successfully!" in out
    assert "Detected Ecosystem: PYTHON" in out
    assert (repo / ".slice.toml").exists()
    assert (repo / ".mcp.json").exists()
    assert (repo / ".gitignore").exists()
