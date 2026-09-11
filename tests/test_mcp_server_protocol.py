"""
IN_PROCESS_MCP_TEST — FastMCP in-process tool discovery and call_tool.

These tests invoke the FastMCP server object directly in the same Python
process. They are NOT stdio protocol tests and do NOT prove Cursor Chat or
Claude Code client invocation.

Classification:
    IN_PROCESS_MCP_TEST
        direct Python invocation of mcp.list_tools / mcp.call_tool

Not covered by this file:
    RAW_STDIO_PROTOCOL_TEST  → tests/test_mcp_stdio_protocol.py
    CURSOR_CHAT_INVOCATION   → requires live Cursor Chat session evidence
    CLAUDE_CODE_INVOCATION   → requires live Claude Code session evidence
"""

from __future__ import annotations

import subprocess
import pytest
from pathlib import Path

from slice_orchestrator.mcp_server import mcp


@pytest.fixture
def disposable_repo_and_control(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    control_home = tmp_path / "control"
    control_home.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Copy policy bundle
    pkg_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    store_bundle = control_home / "policy_bundle"
    store_bundle.mkdir(parents=True, exist_ok=True)
    for f in pkg_bundle.glob("*"):
        if f.is_file():
            (store_bundle / f.name).write_bytes(f.read_bytes())

    (repo_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    return repo_dir, control_home


@pytest.mark.anyio
async def test_mcp_server_tool_discovery():
    """IN_PROCESS_MCP_TEST: verify all MCP tools are discoverable in-process."""
    tool_list = await mcp.list_tools()
    tool_names = [t.name for t in tool_list]

    expected_tools = [
        "slice_start",
        "slice_context",
        "slice_grill",
        "slice_plan",
        "slice_work_list",
        "slice_dispatch",
        "slice_record_result",
        "slice_run_tests",
        "slice_status",
        "slice_report",
        "slice_request_review",
        "slice_gate",
        "slice_finalize",
    ]

    for expected in expected_tools:
        assert expected in tool_names, f"Tool '{expected}' missing from MCP server tool inventory"

    assert len(tool_names) == 13


@pytest.mark.anyio
async def test_mcp_server_tool_invocation(disposable_repo_and_control):
    """IN_PROCESS_MCP_TEST: tool invocation through FastMCP call_tool interface."""
    repo_dir, control_home = disposable_repo_and_control

    # 1. Call slice_start via MCP
    res_start = await mcp.call_tool("slice_start", {"slice": "S901", "objective": "MCP protocol test", "repo_dir": str(repo_dir)})
    assert res_start is not None
    assert len(res_start) > 0
    start_data = res_start[0].text if hasattr(res_start[0], "text") else str(res_start[0])
    assert "S901" in start_data
    assert "PLANNING" in start_data

    # 2. Call slice_status via MCP
    res_status = await mcp.call_tool("slice_status", {"slice": "S901", "repo_dir": str(repo_dir)})
    status_data = res_status[0].text if hasattr(res_status[0], "text") else str(res_status[0])
    assert "S901" in status_data
    assert "PLANNING" in status_data


@pytest.mark.anyio
async def test_mcp_server_invalid_tool_call():
    """IN_PROCESS_MCP_TEST: error behavior on unknown tool call."""
    with pytest.raises(Exception):
        await mcp.call_tool("nonexistent_tool", {})
