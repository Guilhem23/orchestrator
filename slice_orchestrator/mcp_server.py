"""
Slice Orchestrator host-agnostic MCP server.

Exposes control-plane tools over Model Context Protocol (MCP) using stdio
transport. The same server is consumed by:

* Cursor Chat — primary native MCP host
* Claude Code — secondary compatible native MCP host

Neither host launches cursor-agent or claude as a subprocess worker.
Host identity may be passed as optional metadata and never grants authority.
"""

from __future__ import annotations

from typing import Any, Optional, List
from mcp.server.fastmcp import FastMCP

from slice_orchestrator import tools


mcp = FastMCP(
    name="Slice Orchestrator",
    instructions=(
        "Slice Orchestrator native development tool interface. "
        "Host-agnostic MCP tools for Cursor Chat (primary) and Claude Code "
        "(secondary). Both hosts share one control plane. Optional host "
        "metadata is observational only and never grants authority."
    ),
)


@mcp.tool()
def slice_start(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    objective: Optional[str] = None,
    description: Optional[str] = None,
    base_commit: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new persistent slice run or resume an existing one."""
    return tools.slice_start(
        slice=slice,
        slice_name=slice_name,
        objective=objective,
        description=description,
        base_commit=base_commit,
        repo_dir=repo_dir,
        host=host,
    )


@mcp.tool()
def slice_context(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    include_plan: bool = True,
    include_work_items: bool = True,
    include_remediation: bool = True,
    include_role_context: bool = True,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve structured context pack for the current slice state."""
    return tools.slice_context(
        slice=slice,
        slice_name=slice_name,
        include_plan=include_plan,
        include_work_items=include_work_items,
        include_remediation=include_remediation,
        include_role_context=include_role_context,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_grill(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    objective: Optional[str] = None,
    objective_description: Optional[str] = None,
    scope_hints: Optional[List[str]] = None,
    requirement_clarification: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Challenge and validate an objective or requirement before planning."""
    return tools.slice_grill(
        slice=slice,
        slice_name=slice_name,
        objective=objective,
        objective_description=objective_description,
        scope_hints=scope_hints,
        requirement_clarification=requirement_clarification,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_plan(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    plan: Optional[dict[str, Any]] = None,
    is_revision: bool = False,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Submit or revise a structured execution plan for the slice.

    plan.scope_manifest.allow_paths (list of path strings or
    {"pattern": str, "allowed_operations": [...]} dicts) is the only field
    slice_gate/slice_finalize check to authorize file changes. Other scope
    keys (allowed_scope, files, ...) are ignored.
    """
    return tools.slice_plan(
        slice=slice,
        slice_name=slice_name,
        plan=plan,
        is_revision=is_revision,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_work_list(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    action: str = "list",
    work_item: Optional[dict[str, Any]] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """List, create, update, or inspect work items for the slice."""
    return tools.slice_work_list(
        slice=slice,
        slice_name=slice_name,
        action=action,
        work_item=work_item,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_dispatch(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    role: Optional[str] = None,
    work_item_id: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Create an execution assignment for a role and work item."""
    return tools.slice_dispatch(
        slice=slice,
        slice_name=slice_name,
        role=role,
        work_item_id=work_item_id,
        repo_dir=repo_dir,
        host=host,
    )


@mcp.tool()
def slice_record_result(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    assignment_id: Optional[str] = None,
    success: bool = True,
    summary: str = "",
    artifacts: Optional[dict[str, Any]] = None,
    role_context_update: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Bind execution result to the control plane and advance state."""
    return tools.slice_record_result(
        slice=slice,
        slice_name=slice_name,
        assignment_id=assignment_id,
        success=success,
        summary=summary,
        artifacts=artifacts,
        role_context_update=role_context_update,
        error_message=error_message,
        repo_dir=repo_dir,
        host=host,
    )


@mcp.tool()
def slice_run_tests(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    test_ids: Optional[List[str]] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Execute authorized test suite independently and persist HMAC receipt."""
    return tools.slice_run_tests(
        slice=slice,
        slice_name=slice_name,
        test_ids=test_ids,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_status(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    verbose: bool = False,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Query current slice state, progress, and next legal actions."""
    return tools.slice_status(
        slice=slice,
        slice_name=slice_name,
        verbose=verbose,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_report(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    include_event_history: bool = False,
    include_evidence: bool = True,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Generate a human-facing summary report of a slice run."""
    return tools.slice_report(
        slice=slice,
        slice_name=slice_name,
        include_event_history=include_event_history,
        include_evidence=include_evidence,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_request_review(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    reviewer_principal: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Request an independent adversarial review assignment for a slice."""
    return tools.slice_request_review(
        slice=slice,
        slice_name=slice_name,
        reviewer_principal=reviewer_principal,
        repo_dir=repo_dir,
        host=host,
    )


@mcp.tool()
def slice_remediate(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    work_item_id: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Resume an implementation thread from REMEDIATION state after review findings."""
    return tools.slice_remediate(
        slice=slice,
        slice_name=slice_name,
        work_item_id=work_item_id,
        repo_dir=repo_dir,
        host=host,
    )


@mcp.tool()
def slice_gate(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Evaluate deterministic commit gate preconditions."""
    return tools.slice_gate(
        slice=slice,
        slice_name=slice_name,
        repo_dir=repo_dir,
    )


@mcp.tool()
def slice_finalize(
    slice: Optional[str] = None,
    slice_name: Optional[str] = None,
    commit_message: Optional[str] = None,
    repo_dir: Optional[str] = None,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """Finalize an approved slice run and transition state to terminal COMPLETE."""
    return tools.slice_finalize(
        slice=slice,
        slice_name=slice_name,
        commit_message=commit_message,
        repo_dir=repo_dir,
    )


def main() -> None:
    """Entrypoint for starting the Slice Orchestrator MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
