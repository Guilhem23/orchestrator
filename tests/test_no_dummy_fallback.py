"""
Test that vendor worker adapters do NOT silently fall back to dummy.
This is a CRITICAL security requirement.
"""

import pytest
from slice_orchestrator.workers import (
    WorkerRegistry,
    WorkerInputBundle,
    CursorWorkerAdapter,
    ClaudeCodeWorkerAdapter,
    GeminiWorkerAdapter,
)
from pathlib import Path
import uuid


def test_cursor_adapter_fails_by_default():
    """Cursor adapter should FAIL when fallback_to_dummy is False (default)."""
    adapter = CursorWorkerAdapter(fallback_to_dummy=False)
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = adapter.run(bundle)
    
    assert result.success is False
    assert "not implemented" in result.error_message.lower()
    assert result.adapter_id == "cursor"


def test_claude_adapter_fails_by_default():
    """Claude Code adapter should FAIL when fallback_to_dummy is False (default)."""
    adapter = ClaudeCodeWorkerAdapter(fallback_to_dummy=False)
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = adapter.run(bundle)
    
    assert result.success is False
    assert "not implemented" in result.error_message.lower()
    assert result.adapter_id == "claude-code"


def test_gemini_adapter_fails_by_default():
    """Gemini adapter should FAIL when fallback_to_dummy is False (default)."""
    adapter = GeminiWorkerAdapter(fallback_to_dummy=False)
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = adapter.run(bundle)
    
    assert result.success is False
    assert "not implemented" in result.error_message.lower()
    assert result.adapter_id == "gemini"


def test_worker_registry_no_dummy_fallback_by_default():
    """WorkerRegistry should NOT enable dummy fallback by default."""
    registry = WorkerRegistry()  # Default: allow_dummy_fallback=False
    
    # Get Cursor adapter
    cursor = registry.get("cursor")
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = cursor.run(bundle)
    
    # Should FAIL because no real implementation
    assert result.success is False
    assert "not implemented" in result.error_message.lower()


def test_explicit_dummy_fallback_for_testing():
    """Dummy fallback should work ONLY when explicitly enabled."""
    adapter = CursorWorkerAdapter(fallback_to_dummy=True)
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = adapter.run(bundle)
    
    # Should succeed with dummy fallback
    assert result.success is True
    assert result.adapter_id == "cursor"


def test_worker_registry_explicit_dummy_fallback():
    """WorkerRegistry should allow dummy fallback only when explicitly requested."""
    registry = WorkerRegistry(allow_dummy_fallback=True)
    
    cursor = registry.get("cursor")
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = cursor.run(bundle)
    
    # Should succeed because fallback explicitly enabled
    assert result.success is True


def test_unknown_adapter_fails_closed():
    """Unknown adapters should fail closed without execution."""
    registry = WorkerRegistry()
    
    unknown = registry.get("nonexistent-adapter")
    
    bundle = WorkerInputBundle(
        assignment_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        slice="TEST",
        role="IMPLEMENTER",
        prompt="Test prompt",
        base_commit_oid="abc123",
        workspace_dir=Path("/tmp/test"),
        output_dir=Path("/tmp/output"),
    )
    
    result = unknown.run(bundle)
    
    assert result.success is False
    assert "unknown worker adapter" in result.error_message.lower()
    assert "nonexistent-adapter" in result.error_message
