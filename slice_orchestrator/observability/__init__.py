"""
Observability layer for Slice Orchestrator.

Observes and reports on control-plane state. Never grants authority,
never mutates gates/transitions, and never treats worker summaries as
authoritative metrics.
"""

from slice_orchestrator.observability.compare import compare_runs, load_comparison_run
from slice_orchestrator.observability.diagnostics import (
    build_diagnostics,
    build_explain,
    run_doctor,
)
from slice_orchestrator.observability.export import export_run
from slice_orchestrator.observability.logging import OperationalLogger, correlate_logs_with_events
from slice_orchestrator.observability.metrics import MetricsEngine, MetricProvenance, MetricStatus
from slice_orchestrator.observability.timeline import build_timeline

__all__ = [
    "OperationalLogger",
    "correlate_logs_with_events",
    "MetricsEngine",
    "MetricProvenance",
    "MetricStatus",
    "build_timeline",
    "build_diagnostics",
    "build_explain",
    "run_doctor",
    "export_run",
    "compare_runs",
    "load_comparison_run",
]
