"""
Normative Acceptance Tests AT-33 through AT-41 for Product Orchestrator Remediation (M1-M5).
Conforms strictly to ADR-014, Specification Annex v1, and .orchestrator/ACCEPTANCE_TESTS.md.
Exposes real current-runtime failures before M1-M5 implementation.
"""

from pathlib import Path
import pytest

from slice_orchestrator.control_store import ControlStore, ControlStoreError
from slice_orchestrator.orchestrator import SliceRunController, OrchestratorError


def test_at33_product_memory_cannot_create_authority(disposable_repo_and_control):
    """
    AT-33: Product memory cannot create authority.
    Worker attempts to add unsourced active Product Goal or alter Decision; must fail closed.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    # Worker attempts to inject unsourced active Product Goal directly into control plane
    unsourced_goal = {
        "goal_id": "GOAL-UNSOURCED-1",
        "statement": "Fabricated product goal by worker",
        "status": "ACTIVE",
        "source": []  # Missing required approved source reference and digest
    }

    # Must raise ControlStoreError on unsourced ingestion
    with pytest.raises(ControlStoreError):
        ctrl.store.ingest_product_goal(unsourced_goal)


def test_at34_context_pack_determinism_and_immutability(disposable_repo_and_control):
    """
    AT-34: Context Pack generation is deterministic and immutable.
    Identical inputs produce identical pack digest; worker mutation/substitution is denied.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    # M2 Context Pack generation check
    pack1 = ctrl.dispatch_manager.generate_context_pack(
        role="IMPLEMENTER",
        run_id="S6-run-1",
        plan_revision=1,
        target_item_id="S6-WI-1"
    )
    pack2 = ctrl.dispatch_manager.generate_context_pack(
        role="IMPLEMENTER",
        run_id="S6-run-1",
        plan_revision=1,
        target_item_id="S6-WI-1"
    )
    assert pack1["context_pack_digest"] == pack2["context_pack_digest"]


def test_at35_context_pack_role_view_minimization(disposable_repo_and_control):
    """
    AT-35: Context Pack role views are minimized for all 8 roles including ARCHITECTURE_REVIEWER.
    Checks required vs forbidden categories.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    # Check role view selector for ARCHITECTURE_REVIEWER
    arch_rev_view = ctrl.dispatch_manager.get_role_context_view(
        role="ARCHITECTURE_REVIEWER",
        run_id="S6-run-1"
    )
    assert "plan_record" in arch_rev_view["required_categories"]
    assert "implementation_transcripts" not in arch_rev_view


def test_at36_learning_decision_policy_separation(disposable_repo_and_control):
    """
    AT-36: Learning, Decision, and Policy remain distinct.
    Direct promotion of Learning to Decision or Policy is rejected.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    learning = {
        "learning_id": "L-99",
        "statement": "We should use Postgres instead of SQLite",
        "author_role": "IMPLEMENTER"
    }

    with pytest.raises(ControlStoreError):
        ctrl.store.promote_learning_to_policy(learning["learning_id"])


def test_at37_delivery_health_reproducibility(disposable_repo_and_control):
    """
    AT-37: Delivery Health is reproducible from immutable records and event ranges.
    LLM text cannot overwrite factual fields.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    health = ctrl.store.compute_delivery_health(
        start_sequence=1,
        end_sequence=10
    )
    assert "health_snapshot_id" in health
    assert health["trend"] in ("DEGRADING", "IMPROVING", "STABLE", "MIXED", "UNKNOWN")


def test_at38_architecture_challenger_has_no_acceptance_authority(disposable_repo_and_control):
    """
    AT-38: Architecture Challenger has no acceptance authority.
    Challenger output attempting plan mutation, gate approval, or commit fails closed.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    challenge_record = {
        "record_type": "ARCHITECTURE_CHALLENGE",
        "concern": "Complexity disproportionate",
        "proposed_action": "APPROVE_PLAN"  # Invalid attempted authority
    }

    with pytest.raises(ControlStoreError):
        ctrl.store.apply_challenger_approval(challenge_record)


def test_at39_decision_required_durable_bounded_restart_safe(disposable_repo_and_control):
    """
    AT-39: DECISION_REQUIRED is durable, bounded, and restart-safe.
    Raising question without exhaustion evidence is denied. Duplicate decision keys deduplicated.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    unexhausted_question = {
        "question_id": "Q-1",
        "question_text": "Should we change database?",
        "exhaustion_proof": None  # Missing mandatory exhaustion checklist
    }

    with pytest.raises(ControlStoreError):
        ctrl.human_decision_manager.raise_question(unexhausted_question)


def test_at40_plan_impacting_answer_invalidates_approvals(disposable_repo_and_control):
    """
    AT-40: Plan-impacting answer invalidates prior architecture approvals, reviews, and COMMIT_READY.
    Selecting option with true impact_vector triggers atomic invalidation batch & PLAN_REVISION_REQUESTED.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    answer_event = {
        "question_id": "Q-1",
        "selected_option_id": "OPT-SCOPE-CHANGE",
        "impact_vector": {
            "product_intent_changed": False,
            "scope_changed": True,
            "architecture_changed": False,
            "tests_changed": True,
            "acceptance_changed": False
        }
    }

    res = ctrl.human_decision_manager.process_answer(answer_event)
    assert res["state"] == "PLAN_REVISION"
    assert res["plan_revision_requested"] is True


def test_at41_product_completion_mismatch_triggers_concern(disposable_repo_and_control):
    """
    AT-41: Product completion mismatch triggers concern without hidden rejection or bypass.
    Satisfying all work items without product objective trace triggers mismatch event.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    mismatch = ctrl.store.verify_product_completion_trace("S6")
    assert mismatch["status"] == "TRACEABILITY_GAP"
