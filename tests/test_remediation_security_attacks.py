"""
Security Fixture and Attack Tests for Product Orchestrator Remediation (M1-M5).
Covers Sections 4 through 18 of Product Orchestrator Remediation Step 2 Specification.
All tests run against un-remediated runtime to expose current security/control gaps.
"""

import os
import sqlite3
import subprocess
import pytest
from pathlib import Path

from slice_orchestrator.control_store import ControlStore, ControlStoreError
from slice_orchestrator.orchestrator import SliceRunController, OrchestratorError
from slice_orchestrator.policy import PolicyError
from slice_orchestrator.state_machine import TransitionError, TransitionEngine


# ==============================================================================
# SECTION 4: CONTROL PLANE ATTACKS
# ==============================================================================

def test_sec_attack_control_plane_tampering(disposable_repo_and_control, isolated_subprocess_runner):
    """
    Section 4 Attack: Malicious worker attempts direct modification of .orchestrator/,
    .orchestrator_slice/, SQLite event store, trusted tail, policy, transitions, or gates.
    """
    repo_dir, control_dir, slice_dir = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    # Subprocess attempts writing directly into control_dir
    attack_script = f"""
from pathlib import Path
p = Path({repr(str(control_dir))}) / "policy_bundle_digest"
p.write_text("MALICIOUS_FORGED_DIGEST\\n")
"""
    res = isolated_subprocess_runner(attack_script, cwd=repo_dir)

    # Corrupt policy digest file to simulate successful file write
    digest_file = control_dir / "policy_bundle_digest"
    digest_file.write_text("0" * 64 + "\n")

    # Controller must detect integrity mismatch and fail closed
    with pytest.raises(PolicyError):
        SliceRunController(repo_dir, control_dir)


def test_sec_attack_trusted_tail_and_event_forgery(disposable_repo_and_control):
    """
    Section 4 Attack: Malicious worker attempts appending forged event without HMAC secret
    or altering the trusted tail anchor file.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    # Attack: Append row to events table directly via sqlite3 without control secret HMAC
    db_path = control_dir / "state.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO events (sequence, event_id, project_id, slice, run_id, run_generation, event_type, payload_json, event_json, event_hash, event_mac) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (999, "ev-999", "proj-1", "S6", "run-1", 1, "COMMIT_RECORDED", "{}", '{"forged": true}', "hash-999", "mac-999")
    )
    conn.commit()
    conn.close()

    # M1 kernel must detect broken hash/HMAC chain or sequence gap
    with pytest.raises(ControlStoreError):
        ctrl.store.verify_store_integrity()


# ==============================================================================
# SECTION 5: OBJECTIVE / WORK ITEM ATTACKS
# ==============================================================================

def test_sec_attack_objective_and_work_item_tampering(disposable_repo_and_control):
    """
    Section 5 Attack: Malicious worker attempts to mutate Objective, delete Objective,
    modify predicate, modify dependency, forge dependency completion, or alter retry budget.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    forged_objective = {
        "objective_id": "S6-O1",
        "description": "Mutated by worker",
        "acceptance_predicates": []  # Worker deleted acceptance predicates
    }

    # Updating Objective from worker must be denied by control plane
    with pytest.raises(ControlStoreError):
        ctrl.store.update_objective_from_worker("S6-O1", forged_objective)


# ==============================================================================
# SECTION 6: CONTEXT PACK
# ==============================================================================

def test_sec_attack_context_pack_tampering_and_role_view(disposable_repo_and_control):
    """
    Section 6 Attack: Context Pack generation, assignment binding, role views, replay, and stale context.
    Must fail closed if ARCHITECTURE_REVIEWER view is missing or context pack is modified by worker.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    # M2 requirement: verify worker context pack digest
    res = ctrl.dispatch_manager.verify_worker_context_pack_digest(
        pack_id="cp-123",
        claimed_digest="0" * 64,
        actual_content={"role": "IMPLEMENTER"}
    )
    assert res is False


# ==============================================================================
# SECTION 7: ASSIGNMENT
# ==============================================================================

def test_sec_attack_assignment_minting_and_replay(disposable_repo_and_control):
    """
    Section 7 Attack: Worker attempts minting assignment, replaying assignment from another run,
    modifying assignment scope/revision, or executing without active assignment grant.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    forged_assignment = {
        "assignment_id": "minted-by-worker-123",
        "role": "ADVERSARIAL_REVIEWER",
        "run_id": "S6",
        "status": "ISSUED"
    }

    with pytest.raises(ControlStoreError):
        ctrl.store.register_worker_minted_assignment(forged_assignment)


# ==============================================================================
# SECTION 8: HUMAN DECISION
# ==============================================================================

def test_sec_attack_human_decision_invalidation_and_replay(disposable_repo_and_control):
    """
    Section 8 Attack: Plan-impacting answer invalidates architecture approval, review, convergence, COMMIT_READY.
    Duplicate answer, answer replay, and invalid option testing.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    plan_impacting_answer = {
        "question_id": "Q-SEC-1",
        "selected_option_id": "OPT-SCOPE-EXPAND",
        "impact_vector": {"scope_changed": True}
    }

    res = ctrl.human_decision_manager.submit_answer(plan_impacting_answer)
    assert res["invalidated_commit_ready"] is True


# ==============================================================================
# SECTION 9: PRODUCT MEMORY
# ==============================================================================

def test_sec_attack_product_memory_rewrite_and_promotion(disposable_repo_and_control):
    """
    Section 9 Attack: Worker attempts rewriting, deleting, reclassifying, changing provenance/severity,
    or promoting Learning directly into Policy.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    with pytest.raises(ControlStoreError):
        ctrl.store.promote_learning_to_installed_policy("L-SEC-1")


# ==============================================================================
# SECTION 10: ROADMAP / REQUIREMENT REVISION
# ==============================================================================

def test_sec_attack_roadmap_source_revision_invalidation(disposable_repo_and_control):
    """
    Section 10 Attack: Source v1 -> plan -> source v2 changes digest.
    Dependent planning artifacts must become invalid and force PLAN_REVISION.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    valid = ctrl.store.check_source_revision_anchor("FR-010", current_bytes_digest="a" * 64, pinned_bytes_digest="b" * 64)
    assert valid is False


# ==============================================================================
# SECTION 11: RISK / DELIVERY HEALTH
# ==============================================================================

def test_sec_attack_delivery_health_and_risk_text_override(disposable_repo_and_control):
    """
    Section 11 Attack: Worker text attempt to alter derived risk severity, completion percentage,
    or delivery health trend classification must be ignored by control plane calculations.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    worker_claimed_health = {
        "claimed_trend": "IMPROVING",
        "claimed_completion_percentage": 100.0,
        "claimed_risk_severity": "LOW"
    }

    with pytest.raises(ControlStoreError):
        ctrl.store.apply_worker_health_claim(worker_claimed_health)


# ==============================================================================
# SECTION 12: CONVERGENCE
# ==============================================================================

def test_sec_attack_convergence_fail_closed_on_error(disposable_repo_and_control):
    """
    Section 12 Attack: Missing test, stale test, missing benchmark, malformed benchmark,
    missing evidence, scope violation, predicate exception, wrong revision -> fail closed (never evaluate to PASS).
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    verdict = ctrl.convergence_engine.evaluate_tri_state(
        receipt_id="missing-receipt",
        revision_id="rev-wrong"
    )
    assert verdict in ("FAIL", "ERROR")


# ==============================================================================
# SECTION 13: WORK ITEM DAG
# ==============================================================================

def test_sec_attack_dag_cycle_and_forged_completion(disposable_repo_and_control):
    """
    Section 13 Attack: Missing dependency, cycle, self dependency, duplicate ID,
    forged SATISFIED dependency, retry reset, illegal transition.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    from slice_orchestrator.work_items import WorkItem, WorkItemDAGSupervisor
    
    wiA = WorkItem(work_item_id="WI-A", run_id="S6", objective_id="O1", type="implementation", dependencies=["WI-B"], description="A")
    wiB = WorkItem(work_item_id="WI-B", run_id="S6", objective_id="O1", type="implementation", dependencies=["WI-A"], description="B")

    supervisor = WorkItemDAGSupervisor()
    with pytest.raises(ValueError):
        supervisor.validate_dag_acyclic([wiA, wiB])


# ==============================================================================
# SECTION 14: PO/SM SUPERVISION BOUNDARY
# ==============================================================================

def test_sec_attack_posm_authority_transgression(disposable_repo_and_control):
    """
    Section 14 Attack: PO/SM worker attempting approval, gate override, commit,
    acceptance waiver, policy modification, scope modification, or reviewer substitution.
    All must fail closed.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    st = ctrl.open_run("S6")

    engine = TransitionEngine(ctrl.policy_bundle.transitions, ctrl.policy_bundle.slice_policy)

    with pytest.raises(TransitionError):
        engine.validate_transition(st, "COMMIT_READY", "PO_SM_SUPERVISOR", {})


# ==============================================================================
# SECTION 15: ARCHITECTURE CHALLENGER
# ==============================================================================

def test_sec_attack_architecture_challenger_non_authority(disposable_repo_and_control):
    """
    Section 15 Attack: Architecture Challenger attempts approving plan, rejecting candidate,
    mutating plan, or committing code. Must fail closed.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    st = ctrl.open_run("S6")

    engine = TransitionEngine(ctrl.policy_bundle.transitions, ctrl.policy_bundle.slice_policy)

    with pytest.raises(TransitionError):
        engine.validate_transition(st, "PLAN_APPROVED", "ARCHITECTURE_CHALLENGER", {})


# ==============================================================================
# SECTION 16: WORKER COLLUSION
# ==============================================================================

def test_sec_attack_worker_collusion_prevention(disposable_repo_and_control):
    """
    Section 16 Attack: Collusion between PO/SM worker and Implementer worker attempting to
    bypass review, reduce scope, alter risk, modify decision, or fabricate evidence.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S6")

    collusive_payload = {
        "roles": ["PO_SM_SUPERVISOR", "IMPLEMENTER"],
        "action": "BYPASS_ADVERSARIAL_REVIEW",
        "target_state": "COMMIT_READY"
    }

    with pytest.raises(ControlStoreError):
        ctrl.store.apply_collusive_transition(collusive_payload)


# ==============================================================================
# SECTION 17: WORKER ADAPTER SAFETY SHELL
# ==============================================================================

def test_sec_attack_worker_adapter_fail_closed(disposable_repo_and_control):
    """
    Section 17 Attack:
    - Dummy enabled explicitly -> allowed
    - Dummy disabled -> FAIL
    - Unknown adapter -> FAIL
    - Missing executable -> FAIL
    - No silent fallback
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="unknown_vendor_adapter_xyz")

    adapter = ctrl.worker_registry.get("unknown_vendor_adapter_xyz")
    assert adapter.adapter_id == "unknown_vendor_adapter_xyz", (
        f"Adapter safety violation: expected 'unknown_vendor_adapter_xyz' or Exception, "
        f"got silent fallback to {adapter.adapter_id!r}"
    )


# ==============================================================================
# SECTION 18: ENVIRONMENT VALIDATION
# ==============================================================================

def test_sec_attack_environment_validation(disposable_repo_and_control):
    """
    Section 18 Attack: Explicit validation for Python, uv, pytest, Git, SQLite.
    Missing environment dependencies must fail closed with explicit diagnostic error.
    """
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")

    valid = ctrl.store.verify_toolchain_environment(required=["python3", "uv", "pytest", "git", "sqlite3"])
    assert valid is True
