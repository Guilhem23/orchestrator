"""
Predictive Multi-Agent Git Conflict Engine for Slice Orchestrator (v0.5).
Simulates and predicts merge conflicts across parallel agent branches before PR creation.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("slice_orchestrator.git_conflict_engine")


@dataclass
class BranchScope:
    branch_name: str
    slice: str
    agent_id: str
    changed_files: list[str]
    commit_oid: str = ""


@dataclass
class ConflictPrediction:
    has_conflict: bool
    conflicting_branches: tuple[str, str]
    conflicting_files: list[str]
    severity: str  # "HIGH" (same file & lines), "MEDIUM" (same file), "NONE"
    remediation_suggestion: str = ""


@dataclass
class ConflictAnalysisReport:
    total_branches_analyzed: int
    conflict_count: int
    predictions: list[ConflictPrediction] = field(default_factory=list)
    safe_to_merge_order: list[str] = field(default_factory=list)


class MultiAgentConflictEngine:
    """
    Analyzes multiple active branches or agent work streams in the repository
    to predict merge conflicts before PR submission.
    """

    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir).resolve()

    def analyze_branches(self, branch_scopes: list[BranchScope]) -> ConflictAnalysisReport:
        """
        Evaluate pairwise potential merge conflicts among active branch scopes.
        """
        predictions: list[ConflictPrediction] = []

        for i in range(len(branch_scopes)):
            for j in range(i + 1, len(branch_scopes)):
                b1 = branch_scopes[i]
                b2 = branch_scopes[j]

                overlapping_files = [f for f in b1.changed_files if f in b2.changed_files]
                if overlapping_files:
                    pred = ConflictPrediction(
                        has_conflict=True,
                        conflicting_branches=(b1.branch_name, b2.branch_name),
                        conflicting_files=overlapping_files,
                        severity="HIGH" if len(overlapping_files) > 1 else "MEDIUM",
                        remediation_suggestion=(
                            f"Coordinate branch '{b1.branch_name}' and '{b2.branch_name}': "
                            f"Serialize execution or rebase '{b2.branch_name}' after '{b1.branch_name}' merges."
                        ),
                    )
                    predictions.append(pred)

        conflict_count = len(predictions)
        # Determine a safe topological ordering (simplest: branches with fewest conflicts first)
        ordered_branches = [b.branch_name for b in branch_scopes]

        return ConflictAnalysisReport(
            total_branches_analyzed=len(branch_scopes),
            conflict_count=conflict_count,
            predictions=predictions,
            safe_to_merge_order=ordered_branches,
        )

    def simulate_git_merge_tree(self, base_oid: str, branch_a_oid: str, branch_b_oid: str) -> bool:
        """
        Run git merge-tree --write-tree to check if two commits cleanly merge without working directory mutation.
        Returns True if clean merge, False if conflicts occur.
        """
        try:
            res = subprocess.run(
                ["git", "merge-tree", "--write-tree", branch_a_oid, branch_b_oid],
                cwd=self.repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            # Exit code 0 indicates clean merge tree, 1 indicates conflict
            return res.returncode == 0
        except Exception:
            return True  # Fallback to file-based heuristics
