"""
Tests for Slice Orchestrator v5 Phase 1:
- Binary Mutant Arbitrage Engine (MutantArbitrageEngine)
- Inference Router & <500ms Fallback Cascade (InferenceRouter)
"""

import sys
from pathlib import Path
import pytest

from slice_orchestrator.inference_router import InferenceRouter, InferenceResult
from slice_orchestrator.mutant_arbitrage import MutantArbitrageEngine, MutantTestCase


def test_inference_router_cloud_default():
    router = InferenceRouter(primary_provider="cloud", cloud_provider="anthropic")
    res = router.call("Test prompt", system_prompt="System instructions")
    assert isinstance(res, InferenceResult)
    assert res.provider == "anthropic"
    assert "anthropic" in res.text or "Deterministic" in res.text
    assert not res.fallback_occurred
    assert res.latency_ms >= 0


def test_inference_router_mock_handler():
    def dummy_handler(prompt: str, sys: str) -> str:
        return f"ECHO:{prompt}"

    router = InferenceRouter(mock_handler=dummy_handler)
    res = router.call("hello world")
    assert res.text == "ECHO:hello world"
    assert res.provider == "mock"


def test_inference_router_local_fallback_cascade():
    # Configure an unreachable local endpoint to trigger transparent cloud cascade
    router = InferenceRouter(
        primary_provider="local",
        cloud_provider="gemini",
        local_endpoint="http://127.0.0.1:54321",  # Unbound port
        fallback_timeout_ms=300.0,
    )
    res = router.call("Analyze function invariants")
    assert res.fallback_occurred is True
    assert res.provider == "gemini"
    assert "gemini" in res.text or "Deterministic" in res.text
    assert "Local Ollama failure" in (res.fallback_reason or "")


def test_mutant_arbitrage_engine_generation_and_execution(tmp_path: Path):
    # Setup simple Python module
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample_file = src_dir / "math_ops.py"
    sample_file.write_text(
        "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    engine = MutantArbitrageEngine(tmp_path)
    mutants = engine.generate_mutants(["src/math_ops.py"])
    assert len(mutants) >= 2
    assert any("add" in m.test_id for m in mutants)
    assert any("multiply" in m.test_id for m in mutants)

    # Execute mutants (all should pass on valid code)
    verdict = engine.execute_mutants(mutants)
    assert verdict.passed is True
    assert verdict.exit_code == 0
    assert verdict.mutant_count == len(mutants)


def test_mutant_arbitrage_engine_catches_defect(tmp_path: Path):
    engine = MutantArbitrageEngine(tmp_path)
    # Deliberately failing mutant test
    failing_mutant = MutantTestCase(
        test_id="mutant_deliberate_failure",
        target_module="test",
        description="Fails when invariant is broken",
        code="def test_broken_invariant():\n    assert 1 == 2, 'Invariant broken!'\n",
        category="invariant",
    )

    verdict = engine.execute_mutants([failing_mutant])
    assert verdict.passed is False
    assert verdict.exit_code != 0
    assert verdict.failed_count >= 1
    assert any("Invariant broken!" in d or "FAILED" in d for d in verdict.failure_details or [verdict.raw_output])
