"""
RAW_STDIO_PROTOCOL_TEST — genuine stdio JSON-RPC protocol tests.

Spawns the actual FastMCP server process via `python -m slice_orchestrator.mcp_server`
over stdio subprocess pipes and verifies raw JSON-RPC 2.0 frames, protocol handshakes,
tool discovery, tool execution, error handling, process resilience, output isolation,
and complete lifecycle over stdio transport.

Classification:
    RAW_STDIO_PROTOCOL_TEST
        actual server process over stdin/stdout

This is NOT:
    IN_PROCESS_MCP_TEST     → tests/test_mcp_server_protocol.py
    CURSOR_CHAT_INVOCATION  → live Cursor Chat session (UNVERIFIED without evidence)
    CLAUDE_CODE_INVOCATION  → live Claude Code session (UNVERIFIED without evidence)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import pytest
from pathlib import Path


class StdioMcpClient:
    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "slice_orchestrator.mcp_server"],
            cwd=str(repo_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        self.msg_id = 0

    def send_raw(self, line: str):
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def send_request(self, method: str, params: dict | None = None) -> dict:
        self.msg_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.msg_id,
            "method": method,
        }
        if params is not None:
            req["params"] = params
        self.send_raw(json.dumps(req))
        return self.read_response(expected_id=self.msg_id)

    def read_response(self, expected_id: int | None = None, timeout_sec: float = 5.0) -> dict:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            assert line, "Server stdout closed unexpectedly"
            try:
                msg = json.loads(line)
                # Skip notification frames when waiting for a request response
                if "method" in msg and "id" not in msg:
                    continue
                if expected_id is not None and msg.get("id") != expected_id:
                    continue
                return msg
            except json.JSONDecodeError as exc:
                raise ValueError(f"Failed to decode JSON-RPC frame: {line!r}") from exc

    def close(self):
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=5.0)


def setup_protocol_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "stdio_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    control_home = repo_dir / ".orchestrator_slice"
    control_home.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Protocol Tester"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "protocol@example.com"], cwd=repo_dir, check=True)

    pkg_bundle = Path(__file__).resolve().parents[1] / ".orchestrator"
    store_bundle = control_home / "policy_bundle"
    store_bundle.mkdir(parents=True, exist_ok=True)
    for f in pkg_bundle.glob("*"):
        if f.is_file():
            (store_bundle / f.name).write_bytes(f.read_bytes())

    (repo_dir / ".gitignore").write_text(".orchestrator_slice/\n__pycache__/\n")
    (repo_dir / "pyproject.toml").write_text("[project]\nname='calc'\n")
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "tests").mkdir(parents=True, exist_ok=True)

    (repo_dir / "src" / "calc.py").write_text("def sub(a, b):\n    return a - b\n")
    (repo_dir / "tests" / "test_calc.py").write_text("from src.calc import sub\ndef test_sub():\n    assert sub(5, 2) == 3\n")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    return repo_dir


def test_stdio_protocol_handshake_and_discovery(tmp_path: Path):
    repo_dir = setup_protocol_repo(tmp_path)
    client = StdioMcpClient(repo_dir)

    try:
        # 1. Handshake (initialize)
        init_res = client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })
        assert "result" in init_res
        server_info = init_res["result"]["serverInfo"]
        assert server_info["name"] == "Slice Orchestrator"

        # Send initialized notification
        client.send_raw(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))

        # 2. Tool Discovery (tools/list)
        list_res = client.send_request("tools/list")
        assert "result" in list_res
        tools = list_res["result"]["tools"]
        tool_names = {t["name"] for t in tools}

        expected_names = {
            "slice_start", "slice_context", "slice_grill", "slice_plan",
            "slice_work_list", "slice_dispatch", "slice_record_result",
            "slice_run_tests", "slice_status", "slice_report",
            "slice_request_review", "slice_gate", "slice_finalize"
        }
        assert expected_names.issubset(tool_names)

    finally:
        client.close()


def test_stdio_protocol_error_handling_and_resilience(tmp_path: Path):
    repo_dir = setup_protocol_repo(tmp_path)
    client = StdioMcpClient(repo_dir)

    try:
        client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })

        # 1. Unknown tool
        unk_res = client.send_request("tools/call", {"name": "non_existent_tool", "arguments": {}})
        assert "result" in unk_res
        assert unk_res["result"].get("isError") is True

        # 2. Malformed JSON frame
        client.send_raw("{malformed_json_frame: true")

        # Process should survive and respond to subsequent valid request
        res = client.send_request("tools/list")
        assert "result" in res

        # 3. Missing required argument
        missing_arg_res = client.send_request("tools/call", {"name": "slice_status", "arguments": {}})
        assert "result" in missing_arg_res
        assert missing_arg_res["result"].get("isError") is True

    finally:
        client.close()


def test_stdio_protocol_complete_lifecycle(tmp_path: Path):
    repo_dir = setup_protocol_repo(tmp_path)
    client = StdioMcpClient(repo_dir)
    slice_name = "S700"

    try:
        client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })

        # 1. slice_start
        r1 = client.send_request("tools/call", {"name": "slice_start", "arguments": {"slice": slice_name, "objective": "Add subtract test"}})
        out1 = json.loads(r1["result"]["content"][0]["text"])
        assert out1["state"] == "PLANNING"

        # 2. slice_plan
        plan = {
            "description": "Plan for S700",
            "scope_manifest": {"allow_paths": ["src/calc.py", "tests/test_calc.py"]},
            "work_items": [{"work_item_id": "S700-WI-1", "assigned_role": "IMPLEMENTER"}]
        }
        r2 = client.send_request("tools/call", {"name": "slice_plan", "arguments": {"slice": slice_name, "plan": plan}})
        out2 = json.loads(r2["result"]["content"][0]["text"])
        assert out2["state"] == "PLAN_READY"

        # 3. slice_dispatch -> ARCHITECTURE_REVIEWER
        r3 = client.send_request("tools/call", {"name": "slice_dispatch", "arguments": {"slice": slice_name, "role": "ARCHITECTURE_REVIEWER"}})
        out3 = json.loads(r3["result"]["content"][0]["text"])
        assert out3["state"] == "ARCHITECTURE_REVIEW"

        # 4. slice_record_result -> ARCHITECTURE_APPROVED
        r4 = client.send_request("tools/call", {"name": "slice_record_result", "arguments": {
            "slice": slice_name, "assignment_id": out3["assignment_id"], "artifacts": {"verdict": "APPROVED"}
        }})
        out4 = json.loads(r4["result"]["content"][0]["text"])
        assert out4["state"] == "ARCHITECTURE_APPROVED"

        # 5. slice_dispatch -> IMPLEMENTER
        r5 = client.send_request("tools/call", {"name": "slice_dispatch", "arguments": {"slice": slice_name, "role": "IMPLEMENTER"}})
        out5 = json.loads(r5["result"]["content"][0]["text"])
        assert out5["state"] == "IMPLEMENTATION"

        # 6. slice_record_result -> IMPLEMENTATION_READY_FOR_REVIEW
        r6 = client.send_request("tools/call", {"name": "slice_record_result", "arguments": {
            "slice": slice_name, "assignment_id": out5["assignment_id"], "success": True
        }})
        out6 = json.loads(r6["result"]["content"][0]["text"])
        assert out6["state"] == "IMPLEMENTATION_READY_FOR_REVIEW"

        # 7. slice_run_tests
        r7 = client.send_request("tools/call", {"name": "slice_run_tests", "arguments": {"slice": slice_name}})
        out7 = json.loads(r7["result"]["content"][0]["text"])
        assert out7["tests_passed"] is True

        # 8. slice_request_review -> ADVERSARIAL_REVIEWER
        r8 = client.send_request("tools/call", {"name": "slice_request_review", "arguments": {"slice": slice_name, "reviewer_principal": "independent-rev"}})
        out8 = json.loads(r8["result"]["content"][0]["text"])
        assert out8["state"] == "ADVERSARIAL_REVIEW"

        # 9. slice_record_result -> COMMIT_READY
        r9 = client.send_request("tools/call", {"name": "slice_record_result", "arguments": {
            "slice": slice_name, "assignment_id": out8["assignment_id"], "artifacts": {"verdict": "APPROVED", "reviewer_principal": "independent-rev"}
        }})
        out9 = json.loads(r9["result"]["content"][0]["text"])
        assert out9["state"] == "COMMIT_READY"

        # 10. slice_gate
        r10 = client.send_request("tools/call", {"name": "slice_gate", "arguments": {"slice": slice_name}})
        out10 = json.loads(r10["result"]["content"][0]["text"])
        assert out10["passed"] is True

        # 11. slice_finalize
        r11 = client.send_request("tools/call", {"name": "slice_finalize", "arguments": {"slice": slice_name}})
        out11 = json.loads(r11["result"]["content"][0]["text"])
        assert out11["finalized"] is True
        assert out11["state"] == "COMPLETE"

        # 12. slice_report
        r12 = client.send_request("tools/call", {"name": "slice_report", "arguments": {"slice": slice_name}})
        out12 = json.loads(r12["result"]["content"][0]["text"])
        assert out12["final_state"] == "COMPLETE"
        assert out12["verdict"] == "COMPLETE"

    finally:
        client.close()


def test_stdio_protocol_restart_and_persistence(tmp_path: Path):
    repo_dir = setup_protocol_repo(tmp_path)
    slice_name = "S800"

    # Session 1: Start and plan
    c1 = StdioMcpClient(repo_dir)
    try:
        c1.send_request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "c1", "version": "1.0"}})
        c1.send_request("tools/call", {"name": "slice_start", "arguments": {"slice": slice_name, "objective": "Persistence test"}})
    finally:
        c1.close()

    # Session 2: Server restarted, verify state persisted
    c2 = StdioMcpClient(repo_dir)
    try:
        c2.send_request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "c2", "version": "1.0"}})
        res = c2.send_request("tools/call", {"name": "slice_status", "arguments": {"slice": slice_name}})
        out = json.loads(res["result"]["content"][0]["text"])
        assert out["exists"] is True
        assert out["state"] == "PLANNING"
    finally:
        c2.close()
