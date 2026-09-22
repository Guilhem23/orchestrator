"""Productivity comparison between manual and orchestrated runs.

Does not claim causality from a single comparison. Missing data stays explicit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COMPARISON_SCHEMA_VERSION = "productivity-comparison-v1"

COMPARABLE_FIELDS = [
    "task_identifier",
    "task_complexity",
    "starting_revision",
    "final_revision",
    "elapsed_time_ms",
    "human_active_time_ms",
    "human_waiting_time_ms",
    "number_of_questions",
    "number_of_interruptions",
    "number_of_tool_calls",
    "number_of_context_reconstructions",
    "tests_added",
    "tests_passed",
    "review_findings",
    "remediation_cycles",
    "defects_introduced",
    "defects_detected",
    "final_outcome",
    "developer_assessment",
]


def load_comparison_run(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Comparison run file must be a JSON object")
    return data


def _pct_diff(a: Any, b: Any) -> Any:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    if a == 0:
        return None if b == 0 else None
    return round(((b - a) / abs(a)) * 100.0, 2)


def compare_runs(
    manual: dict[str, Any],
    orchestrated: dict[str, Any],
    *,
    qualitative_observations: list[str] | None = None,
    confounding_factors: list[str] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    missing: list[str] = []
    for field in COMPARABLE_FIELDS:
        m_val = manual.get(field, "UNAVAILABLE")
        o_val = orchestrated.get(field, "UNAVAILABLE")
        if m_val == "UNAVAILABLE" or o_val == "UNAVAILABLE" or m_val is None or o_val is None:
            if m_val in (None, "UNAVAILABLE") or o_val in (None, "UNAVAILABLE"):
                missing.append(field)
        abs_diff = None
        if isinstance(m_val, (int, float)) and isinstance(o_val, (int, float)):
            abs_diff = o_val - m_val
        fields[field] = {
            "manual": m_val if m_val is not None else "UNAVAILABLE",
            "orchestrated": o_val if o_val is not None else "UNAVAILABLE",
            "absolute_difference": abs_diff,
            "percent_difference": _pct_diff(m_val, o_val),
        }

    default_confounders = [
        "Single-run comparison cannot establish causality.",
        "Task familiarity, IDE state, and developer fatigue may differ.",
        "Tooling versions and model availability may differ across runs.",
        "Missing fields must not be imputed.",
    ]
    report = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "fields": fields,
        "missing_data": missing,
        "confounding_factors": confounding_factors or default_confounders,
        "qualitative_observations": qualitative_observations or [],
        "productivity_conclusion": (
            "NO UNSUPPORTED CONCLUSION: This report presents absolute and relative "
            "differences only. Do not claim the orchestrator improves productivity "
            "until the comparison protocol has been executed on multiple comparable tasks."
        ),
    }
    return report


def comparison_from_export(
    export_payload: dict[str, Any],
    *,
    task_identifier: str,
    task_complexity: str | int | None = None,
    mode: str = "orchestrated",
    developer_assessment: str | None = None,
) -> dict[str, Any]:
    """Map an orchestrated export into the comparison schema; unknowns stay UNAVAILABLE."""
    metrics = (export_payload.get("metrics") or {}).get("metrics") or {}

    def mval(name: str) -> Any:
        meta = metrics.get(name) or {}
        status = meta.get("status")
        if status in ("UNAVAILABLE", "DECLARED", None) and meta.get("value") is None:
            return "UNAVAILABLE"
        if status == "DECLARED":
            return "UNAVAILABLE"
        return meta.get("value")

    timeline = export_payload.get("event_timeline") or {}
    return {
        "mode": mode,
        "task_identifier": task_identifier,
        "task_complexity": task_complexity if task_complexity is not None else "UNAVAILABLE",
        "starting_revision": "UNAVAILABLE",
        "final_revision": mval("final_commit_oid"),
        "elapsed_time_ms": timeline.get("total_elapsed_ms")
        if timeline.get("total_elapsed_ms") is not None
        else mval("total_elapsed_time_ms"),
        "human_active_time_ms": "UNAVAILABLE",
        "human_waiting_time_ms": mval("human_waiting_time_ms"),
        "number_of_questions": mval("human_questions"),
        "number_of_interruptions": mval("human_interruptions"),
        "number_of_tool_calls": mval("number_of_mcp_tool_calls"),
        "number_of_context_reconstructions": mval("context_reconstruction_events"),
        "tests_added": "UNAVAILABLE",
        "tests_passed": mval("tests_passed"),
        "review_findings": mval("review_findings"),
        "remediation_cycles": mval("remediation_cycles"),
        "defects_introduced": "UNAVAILABLE",
        "defects_detected": mval("defects_detected_during_review"),
        "final_outcome": export_payload.get("final_state") or "UNAVAILABLE",
        "developer_assessment": developer_assessment or "UNAVAILABLE",
    }


def format_compare_human(report: dict[str, Any]) -> str:
    lines = [
        "=== slice compare ===",
        f"Schema: {report.get('schema_version')}",
        "",
        f"{'field':40s} {'manual':20s} {'orchestrated':20s} {'diff':12s} {'pct':8s}",
        "-" * 100,
    ]
    for name, row in (report.get("fields") or {}).items():
        lines.append(
            f"{name:40s} {str(row.get('manual')):20s} {str(row.get('orchestrated')):20s} "
            f"{str(row.get('absolute_difference')):12s} {str(row.get('percent_difference')):8s}"
        )
    lines.append("")
    lines.append(f"Missing data: {report.get('missing_data')}")
    lines.append("Confounding factors:")
    for c in report.get("confounding_factors") or []:
        lines.append(f"  - {c}")
    lines.append("")
    lines.append(str(report.get("productivity_conclusion")))
    return "\n".join(lines)
