"""
Human Decision and Question Exhaustion Manager for Method v4.
Handles bounded DECISION_REQUIRED lifecycle and impact-driven approval invalidations.
"""

from typing import Any
from slice_orchestrator.control_store import ControlStore, ControlStoreError


class HumanDecisionManager:
    """
    Manages questions, exhaustion checklists, and decision answers.
    """

    def __init__(self, store: ControlStore):
        self.store = store

    def raise_question(self, question_dict: dict[str, Any]) -> dict[str, Any]:
        exhaustion_proof = question_dict.get("exhaustion_proof")
        if not exhaustion_proof or not isinstance(exhaustion_proof, (dict, list)):
            raise ControlStoreError("Missing mandatory exhaustion proof checklist: Question cannot be raised without exhaustion evidence")

        return {
            "question_id": question_dict["question_id"],
            "status": "DECISION_REQUIRED",
        }

    def process_answer(self, answer_event: dict[str, Any]) -> dict[str, Any]:
        impact = answer_event.get("impact_vector", {})
        has_impact = any(
            impact.get(k, False)
            for k in ("product_intent_changed", "scope_changed", "architecture_changed", "tests_changed", "acceptance_changed")
        )

        if has_impact:
            return {
                "state": "PLAN_REVISION",
                "plan_revision_requested": True,
                "invalidated_commit_ready": True,
            }

        return {
            "state": "IMPLEMENTATION",
            "plan_revision_requested": False,
            "invalidated_commit_ready": False,
        }

    def submit_answer(self, answer_event: dict[str, Any]) -> dict[str, Any]:
        return self.process_answer(answer_event)
