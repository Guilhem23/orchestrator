"""Shared disposable workspace helpers. Production trees are never modified."""

from __future__ import annotations

import subprocess
from pathlib import Path


def seed_passing_workspace(repo_dir: Path) -> None:
    """Give a disposable repo an honest passing pytest so COMPLETE is reachable."""
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    if not (repo_dir / "pyproject.toml").is_file():
        (repo_dir / "pyproject.toml").write_text(
            "[project]\nname = \"disposable-slice\"\nversion = \"0.0.0\"\n",
            encoding="utf-8",
        )
    gitignore = repo_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    for line in (
        ".orchestrator_slice/",
        "__pycache__/",
        "*.pyc",
        ".pytest_cache/",
        ".venv/",
    ):
        if line not in existing:
            existing += line + "\n"
    gitignore.write_text(existing, encoding="utf-8")


def seed_slice_to_ready_for_review(store, slice_name: str = "S1", run_id: str = "r1") -> None:
    """Append a legal event prefix through CANDIDATE_CAPTURED."""
    opened = {
        "payload_type": "RUN_OPENED",
        "record": {"record_type": "SLICE_RUN", "record_id": f"{slice_name}-run-1", "record_digest": "0" * 64},
        "base_commit_oid": "sha1:" + "0" * 40,
        "policy_bundle_digest": "0" * 64,
    }
    store.append_event(
        slice_name=slice_name, run_id=run_id, generation=1,
        event_type="RUN_OPENED", payload_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM", payload=opened,
    )
    store.append_event(
        slice_name=slice_name, run_id=run_id, generation=1,
        event_type="PLAN_PERSISTED", payload_type="PLAN_PERSISTED",
        actor_role="PLANNER",
        payload={
            "payload_type": "PLAN_PERSISTED",
            "record": {"record_type": "PLAN", "record_id": f"{slice_name}-plan", "record_digest": "a" * 64},
            "plan_revision": 1,
        },
    )
    store.append_event(
        slice_name=slice_name, run_id=run_id, generation=1,
        event_type="ARCHITECTURE_REVIEW_ASSIGNED", payload_type="ARCHITECTURE_REVIEW_ASSIGNED",
        actor_role="CONTROLLER_SYSTEM",
        payload={"payload_type": "ARCHITECTURE_REVIEW_ASSIGNED", "assignment_id": "as-arch"},
    )
    store.append_event(
        slice_name=slice_name, run_id=run_id, generation=1,
        event_type="ARCHITECTURE_APPROVED", payload_type="ARCHITECTURE_APPROVED",
        actor_role="ARCHITECTURE_REVIEWER",
        payload={"payload_type": "ARCHITECTURE_APPROVED", "record": {"record_type": "ARCHITECTURE_REVIEW", "record_id": "arch-1", "record_digest": "b" * 64}},
    )
    store.append_event(
        slice_name=slice_name, run_id=run_id, generation=1,
        event_type="IMPLEMENTATION_ASSIGNED", payload_type="IMPLEMENTATION_ASSIGNED",
        actor_role="CONTROLLER_SYSTEM",
        payload={"payload_type": "IMPLEMENTATION_ASSIGNED", "assignment_id": "as-impl"},
    )
    store.append_event(
        slice_name=slice_name, run_id=run_id, generation=1,
        event_type="CANDIDATE_CAPTURED", payload_type="CANDIDATE_CAPTURED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "CANDIDATE_CAPTURED",
            "record": {"record_type": "CANDIDATE", "record_id": "cand-1", "record_digest": "c" * 64},
            "workspace_revision_digest": "d" * 64,
            "evidence_set_digest": "e" * 64,
        },
    )


def git_commit_all(repo_dir: Path, message: str = "Seed passing workspace") -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_dir, check=True, capture_output=True)
