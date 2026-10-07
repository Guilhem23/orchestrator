"""
60-Second Onboarding Initializer for Slice Orchestrator (Phase 5 - v4.5).

Automatically configures any target project for Slice Orchestrator governance:
1. Detects project ecosystem (Python, Node.js, Rust, Go).
2. Generates optimized `.slice.toml`.
3. Creates or updates `.mcp.json` for Claude Code / Cursor integration.
4. Ensures `.orchestrator_slice/` is ignored in `.gitignore`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def detect_ecosystem(repo_dir: Path) -> dict[str, str]:
    """Detect repo ecosystem and appropriate test command."""
    if (repo_dir / "Cargo.toml").exists():
        return {"type": "rust", "test_command": "cargo test"}
    elif (repo_dir / "package.json").exists():
        return {"type": "node", "test_command": "npm test"}
    elif (repo_dir / "go.mod").exists():
        return {"type": "go", "test_command": "go test ./..."}
    else:
        return {"type": "python", "test_command": "uv run python3 -m pytest tests/ -q"}


def initialize_project(
    repo_dir: Path,
    orchestrator_project_path: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Run 60-second zero-friction onboarding on the target repository.
    """
    repo = repo_dir.resolve()
    ecosystem = detect_ecosystem(repo)
    results: dict[str, Any] = {
        "ecosystem": ecosystem["type"],
        "slice_toml_created": False,
        "mcp_json_updated": False,
        "gitignore_updated": False,
    }

    # 1. Create .slice.toml if not present
    slice_toml_path = repo / ".slice.toml"
    if not slice_toml_path.exists() or force:
        content = (
            f"# Slice Orchestrator Polyglot Configuration\n"
            f"[project]\n"
            f'type = "{ecosystem["type"]}"\n'
            f'test_command = "{ecosystem["test_command"]}"\n'
            f'# extra_test_args = ["-q"]\n'
        )
        slice_toml_path.write_text(content, encoding="utf-8")
        results["slice_toml_created"] = True

    # 2. Configure .mcp.json for Claude Code, Cursor, Windsurf
    mcp_path = repo / ".mcp.json"
    mcp_data: dict[str, Any] = {"mcpServers": {}}
    if mcp_path.exists():
        try:
            mcp_data = json.loads(mcp_path.read_text(encoding="utf-8"))
            if "mcpServers" not in mcp_data:
                mcp_data["mcpServers"] = {}
        except Exception:
            mcp_data = {"mcpServers": {}}

    orch_args = ["run"]
    if orchestrator_project_path:
        orch_args.extend(["--project", orchestrator_project_path])
    orch_args.extend(["python3", "-m", "slice_orchestrator.mcp_server"])

    mcp_data["mcpServers"]["slice-orchestrator"] = {
        "command": "uv",
        "args": orch_args,
    }
    mcp_path.write_text(json.dumps(mcp_data, indent=2) + "\n", encoding="utf-8")
    results["mcp_json_updated"] = True

    # 3. Ensure .orchestrator_slice/ is in .gitignore
    gitignore_path = repo / ".gitignore"
    entry = ".orchestrator_slice/"
    if gitignore_path.exists():
        current_content = gitignore_path.read_text(encoding="utf-8")
        if entry not in current_content and ".orchestrator_slice" not in current_content:
            new_content = current_content.rstrip() + f"\n\n# Slice Orchestrator runtime control plane\n{entry}\n"
            gitignore_path.write_text(new_content, encoding="utf-8")
            results["gitignore_updated"] = True
    else:
        gitignore_path.write_text(f"# Slice Orchestrator runtime control plane\n{entry}\n", encoding="utf-8")
        results["gitignore_updated"] = True

    return results
