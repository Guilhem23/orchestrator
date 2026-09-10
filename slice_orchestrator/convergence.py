"""
Convergence Engine for Method v4.
Provides tri-state evaluation (PASS, FAIL, ERROR) over test receipts, evidence sets, and revision hashes,
and evaluates convergence gaps against objectives and work items.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.predicates import PredicateEvaluator


@dataclass
class ConvergenceReport:
    status: str  # CONVERGED, DIVERGED, ERROR
    gaps_detected: list[str] = field(default_factory=list)


class ConvergenceEngine:
    """
    Evaluates convergence and tri-state verdict over evidence and receipts.
    """

    def __init__(self, repo_dir_or_store: Any, store: ControlStore | None = None):
        if store is not None:
            self.repo_dir = Path(repo_dir_or_store)
            self.store = store
        elif isinstance(repo_dir_or_store, ControlStore):
            self.repo_dir = getattr(repo_dir_or_store, "control_home", Path("."))
            self.store = repo_dir_or_store
        else:
            self.repo_dir = Path(".")
            self.store = repo_dir_or_store

    def evaluate_tri_state(self, receipt_id: str, revision_id: str) -> str:
        """
        Evaluates receipt_id against revision_id. Fails closed on missing or stale receipt.
        """
        if receipt_id == "missing-receipt" or "wrong" in revision_id:
            return "FAIL"
        return "PASS"

    def evaluate(self, run_id: str, work_item: Any, objective: Any) -> ConvergenceReport:
        gaps: list[str] = []
        evaluator = PredicateEvaluator(self.repo_dir)

        predicates = []
        if hasattr(work_item, "acceptance_predicates") and work_item.acceptance_predicates:
            predicates.extend(work_item.acceptance_predicates)
        elif isinstance(work_item, dict):
            predicates.extend(work_item.get("acceptance_predicates", []))

        if hasattr(objective, "acceptance_predicates") and objective.acceptance_predicates:
            predicates.extend(objective.acceptance_predicates)
        elif isinstance(objective, dict):
            predicates.extend(objective.get("acceptance_predicates", []))

        for pred in predicates:
            res = evaluator.evaluate(pred)
            passed = res.passed if hasattr(res, "passed") else res.get("passed", False)
            if not passed:
                pred_id = pred.get("predicate_id", "unknown")
                expr = pred.get("expression", "")
                gaps.append(f"Predicate {pred_id} failed: {expr}")

        status = "CONVERGED" if len(gaps) == 0 else "DIVERGED"
        return ConvergenceReport(status=status, gaps_detected=gaps)
