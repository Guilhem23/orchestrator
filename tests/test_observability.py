"""Observability and effectiveness-measurement tests."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from slice_orchestrator.control_store import ControlStore
from slice_orchestrator.observability.compare import compare_runs, comparison_from_export
from slice_orchestrator.observability.diagnostics import build_diagnostics, build_explain, run_doctor
from slice_orchestrator.observability.export import export_run
from slice_orchestrator.observability.logging import (
    LoggingError,
    OperationalLogger,
    correlate_logs_with_events,
)
from slice_orchestrator.observability.metrics import MetricStatus, MetricsEngine
from slice_orchestrator.observability.redaction import contains_secret_material, redact_event, redact_value
from slice_orchestrator.observability.timeline import build_timeline, duration_ms_between
from slice_orchestrator.orchestrator import SliceRunController
from tests.workspace_support import seed_passing_workspace, seed_slice_to_ready_for_review


def _init_store(tmp_path: Path) -> tuple[Path, Path, ControlStore]:
    repo = tmp_path / "repo"
    home = tmp_path / "control"
    repo.mkdir()
    home.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "ObsTest"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "obs@example.com"], cwd=repo, check=True, capture_output=True)
    seed_passing_workspace(repo)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    project_root = Path(__file__).resolve().parents[1]
    bundle_src = project_root / ".orchestrator"
    store = ControlStore(home, policy_bundle_source=bundle_src)
    store.initialize_policy_bundle(bundle_src)
    store.load_and_verify_policy_bundle()
    store.init_database()
    return repo, home, store


def _append_opened(store: ControlStore, slice_name: str = "S801", run_id: str = "run-obs-1") -> None:
    digest = "0" * 64
    if store.policy_bundle is not None:
        digest = getattr(store.policy_bundle, "digest", None) or digest
    store.append_event(
        slice_name=slice_name,
        run_id=run_id,
        generation=1,
        event_type="RUN_OPENED",
        payload_type="RUN_OPENED",
        actor_role="CONTROLLER_SYSTEM",
        payload={
            "payload_type": "RUN_OPENED",
            "record": {"record_type": "SLICE_RUN", "record_id": f"{slice_name}-run", "record_digest": "0" * 64},
            "base_commit_oid": "sha1:" + "0" * 40,
            "policy_bundle_digest": digest,
        },
    )


class TestStructuredLogs:
    def test_structured_log_generation(self, tmp_path: Path):
        logs = OperationalLogger(tmp_path / "control", run_id="r1")
        entry = logs.emit(
            event_type="RUN_OPENED",
            run_id="r1",
            slice_id="S801",
            actor="controller",
            state_before=None,
            state_after="PLANNING",
            duration_ms=0,
            result="ok",
            error_code=None,
        )
        assert entry["event_type"] == "RUN_OPENED"
        assert (tmp_path / "control" / "logs" / "operational.jsonl").is_file()
        assert (tmp_path / "control" / "logs" / "operational.txt").is_file()
        rows = logs.read_entries(run_id="r1", slice_id="S801")
        assert len(rows) == 1

    def test_event_log_correlation(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        _append_opened(store)
        events = store.verify_store_integrity()
        logger = OperationalLogger(home)
        for ev in events:
            logger.emit_from_event(ev, state_after="PLANNING")
        corr = correlate_logs_with_events(logger.read_entries(), events)
        assert corr["matched"] == 1
        assert corr["unmatched_count"] == 0

    def test_logging_failure_does_not_fake_success(self, tmp_path: Path):
        # Point logs at a file path so mkdir/write fails
        bad = tmp_path / "not_a_dir"
        bad.write_text("x", encoding="utf-8")
        logger = OperationalLogger(bad)
        with pytest.raises(LoggingError):
            logger.emit(event_type="X", run_id="r", slice_id="S1")


class TestTimelineAndDurations:
    def test_missing_timestamps_and_invalid_durations(self):
        assert duration_ms_between(None, "2026-01-01T00:00:00Z") is None
        assert duration_ms_between("2026-01-01T00:00:10Z", "2026-01-01T00:00:00Z") is None
        assert duration_ms_between("2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z") == 1000

    def test_event_ordering_and_phase_durations(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S802", run_id="run-802")
        events = [e for e in store.verify_store_integrity() if e["slice"] == "S802"]
        # Break order intentionally in input; builder should sort
        shuffled = list(reversed(events))
        timeline = build_timeline(shuffled, control_store=store)
        seqs = [e["sequence"] for e in timeline["entries"]]
        assert seqs == sorted(seqs)
        assert timeline["phase_durations_ms"]["by_phase"]
        assert timeline["terminal_outcome"] in ("IN_PROGRESS", "COMPLETE", "STOPPED", "FAILED")

    def test_timeline_phase_filter_and_errors(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S803", run_id="run-803")
        events = [e for e in store.verify_store_integrity() if e["slice"] == "S803"]
        impl = build_timeline(events, control_store=store, phase_filter="implementation")
        assert all(
            e.get("phase") == "implementation" or e.get("event_name") in (
                "IMPLEMENTATION_ASSIGNED", "CANDIDATE_CAPTURED", "IMPLEMENTATION_CONTEXT_CHECKPOINTED",
            )
            for e in impl["entries"]
        )
        # Force a stop event
        store.append_event(
            slice_name="S803",
            run_id="run-803",
            generation=1,
            event_type="RUN_STOPPED",
            actor_role="CONTROL_OPERATOR",
            payload={
                "payload_type": "RUN_STOPPED",
                "stop_reason_code": "WORKER_FAILED",
                "stop_reason": "boom",
            },
        )
        events2 = [e for e in store.verify_store_integrity() if e["slice"] == "S803"]
        err_tl = build_timeline(events2, control_store=store, errors_only=True)
        assert any(e["event_name"] == "RUN_STOPPED" for e in err_tl["entries"])


class TestMetrics:
    def test_human_waiting_and_worker_failure_metrics(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S804", run_id="run-804")
        store.append_event(
            slice_name="S804",
            run_id="run-804",
            generation=1,
            event_type="RUN_STOPPED",
            actor_role="CONTROL_OPERATOR",
            payload={"payload_type": "RUN_STOPPED", "stop_reason_code": "WORKER_FAILED", "stop_reason": "x"},
        )
        report = MetricsEngine(store).compute_for_slice("S804", run_id="run-804")
        assert report["metrics"]["worker_failures"]["value"] == 1
        assert report["metrics"]["worker_failures"]["status"] == MetricStatus.MEASURED.value
        assert report["metrics"]["worker_failures"]["authoritative"] is True
        assert "source_digest" in report["metrics"]["worker_failures"]
        # human waiting may be UNAVAILABLE without pause
        assert report["metrics"]["human_waiting_time_ms"]["status"] in (
            MetricStatus.UNAVAILABLE.value,
            MetricStatus.DERIVED.value,
        )

    def test_review_remediation_and_recovery_metrics(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S805", run_id="run-805")
        store.append_event(
            slice_name="S805",
            run_id="run-805",
            generation=1,
            event_type="ADVERSARIAL_REVIEW_ASSIGNED",
            actor_role="CONTROLLER_SYSTEM",
            payload={"payload_type": "ADVERSARIAL_REVIEW_ASSIGNED", "review_cycle": 1},
        )
        store.append_event(
            slice_name="S805",
            run_id="run-805",
            generation=1,
            event_type="REVIEW_BLOCKED",
            actor_role="ADVERSARIAL_REVIEWER",
            payload={
                "payload_type": "REVIEW_BLOCKED",
                "remediation_cycle": 1,
                "record": {"record_type": "REVIEW", "record_id": "rev-1", "record_digest": "c" * 64},
            },
        )
        report = MetricsEngine(store).compute_for_slice("S805")
        assert report["metrics"]["reviews_executed"]["value"] >= 1
        assert report["metrics"]["remediation_cycles"]["value"] >= 1
        assert report["metrics"]["process_restarts"]["status"] == MetricStatus.UNAVAILABLE.value

    def test_metric_provenance_and_reproducibility(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S806", run_id="run-806")
        a = MetricsEngine(store).compute_for_slice("S806")
        time.sleep(0.01)
        b = MetricsEngine(store).compute_for_slice("S806")
        assert a["source_digest"] == b["source_digest"]
        for key in a["metrics"]:
            assert a["metrics"][key]["value"] == b["metrics"][key]["value"]
            assert a["metrics"][key]["status"] == b["metrics"][key]["status"]
            assert a["metrics"][key]["source_digest"] == b["metrics"][key]["source_digest"]

    def test_worker_claim_does_not_alter_authoritative_metrics(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S807", run_id="run-807")
        before = MetricsEngine(store).compute_for_slice("S807")
        # Worker-written declared summary must not become authoritative input
        store.store_record(
            "WORKER_SUMMARY",
            "worker-lie-1",
            {
                "schema_version": 4,
                "record_type": "WORKER_SUMMARY",
                "slice": "S807",
                "run_id": "run-807",
                "tests_passed": 999,
                "review_cycles": 0,
                "declared_productivity_gain": "100%",
            },
        )
        after = MetricsEngine(store).compute_for_slice("S807")
        assert after["metrics"]["tests_passed"]["value"] == before["metrics"]["tests_passed"]["value"]
        assert after["metrics"]["review_cycle_high_water"]["value"] == before["metrics"]["review_cycle_high_water"]["value"]


class TestRedactionExportCompare:
    def test_secret_redaction(self):
        payload = {
            "control_secret": "abc",
            "token": "secret-token",
            "receipt_mac": "deadbeef",
            "prompt": "full prompt text " * 10,
            "safe": "ok",
            "nested": {"api_key": "xyz"},
        }
        red = redact_value(payload)
        assert red["control_secret"] == "[REDACTED]"
        assert red["token"] == "[REDACTED]"
        assert red["receipt_mac"] == "[REDACTED]"
        assert "PROMPT_OMITTED" in red["prompt"]
        assert red["safe"] == "ok"
        assert red["nested"]["api_key"] == "[REDACTED]"
        assert contains_secret_material("Bearer sk-abcdefghijklmnopqrstuvwxyz")

    def test_export_integrity_and_immutability(self, tmp_path: Path):
        repo, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S808", run_id="run-808")
        ctrl = SliceRunController(repo_dir=repo, control_home=home, configured_adapter_id="dummy")
        out_root = tmp_path / "exports"
        r1 = export_run(ctrl, "S808", fmt="markdown", output_dir=out_root)
        r2 = export_run(ctrl, "S808", fmt="json", output_dir=out_root)
        assert Path(r1["directory"]) != Path(r2["directory"])
        assert Path(r1["json_path"]).is_file()
        assert Path(r1["markdown_path"]).is_file()
        assert (Path(r1["directory"]) / "IMMUTABLE.txt").is_file()
        # Do not overwrite: directories distinct
        assert r1["export_digest"]
        data = json.loads(Path(r1["json_path"]).read_text(encoding="utf-8"))
        assert data["schema_version"]
        assert "event_mac" not in json.dumps(data) or "[REDACTED]" in json.dumps(data)
        dumped = json.dumps(data)
        assert "control_secret" not in dumped or "[REDACTED]" in dumped

    def test_manual_orchestrated_comparison_and_missing_data(self):
        manual = {
            "task_identifier": "T1",
            "elapsed_time_ms": 1000,
            "tests_passed": 1,
            "final_outcome": "COMPLETE",
        }
        orch = {
            "task_identifier": "T1",
            "elapsed_time_ms": 800,
            "tests_passed": 1,
            "final_outcome": "COMPLETE",
            "number_of_questions": 2,
        }
        report = compare_runs(manual, orch)
        assert report["fields"]["elapsed_time_ms"]["absolute_difference"] == -200
        assert "number_of_questions" in report["missing_data"] or report["fields"]["number_of_questions"]["manual"] == "UNAVAILABLE"
        assert "NO UNSUPPORTED CONCLUSION" in report["productivity_conclusion"]
        # comparison_from_export leaves UNAVAILABLE explicit
        mapped = comparison_from_export(
            {"final_state": "COMPLETE", "metrics": {"metrics": {}}, "event_timeline": {}},
            task_identifier="T1",
        )
        assert mapped["human_active_time_ms"] == "UNAVAILABLE"


class TestDiagnosticsCLIDoctor:
    def test_diagnostics_and_explain(self, tmp_path: Path):
        repo, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S809", run_id="run-809")
        ctrl = SliceRunController(repo_dir=repo, control_home=home, configured_adapter_id="dummy")
        diag = build_diagnostics(ctrl, "S809")
        assert diag["exists"] is True
        assert diag["current_state"] == "IMPLEMENTATION_READY_FOR_REVIEW"
        expl = build_explain(ctrl, "S809")
        assert expl["recommendation"].startswith("RECOMMENDATION:")
        assert any("INFERENCE:" in x for x in expl["inference"])

    def test_doctor_json_and_exit_codes(self, tmp_path: Path):
        repo, home, _ = _init_store(tmp_path)
        report = run_doctor(repo_dir=repo, control_home=home)
        assert "checks" in report
        assert report["exit_code"] in (0, 1)
        # CLI
        env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        proc = subprocess.run(
            [sys.executable, "-m", "slice_orchestrator.cli", "doctor", "--json", "--repo-dir", str(repo), "--control-home", str(home)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode in (0, 1)
        data = json.loads(proc.stdout)
        assert data["summary"]["total"] >= 1

    def test_cli_timeline_json_exit(self, tmp_path: Path):
        repo, home, store = _init_store(tmp_path)
        env = {**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        project_root = Path(__file__).resolve().parents[1]
        ctrl_home = repo / ".orchestrator_slice"
        store2 = ControlStore(ctrl_home, policy_bundle_source=project_root / ".orchestrator")
        store2.initialize_policy_bundle(project_root / ".orchestrator")
        store2.load_and_verify_policy_bundle()
        store2.init_database()
        seed_slice_to_ready_for_review(store2, slice_name="S810", run_id="run-810b")
        proc = subprocess.run(
            [sys.executable, "-m", "slice_orchestrator.cli", "timeline", "S810", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["event_count"] >= 1


class TestIsolationAndCorruption:
    def test_multi_slice_isolation(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S811", run_id="run-811")
        seed_slice_to_ready_for_review(store, slice_name="S812", run_id="run-812")
        m811 = MetricsEngine(store).compute_for_slice("S811")
        m812 = MetricsEngine(store).compute_for_slice("S812")
        assert m811["run_id"] != m812["run_id"]
        assert m811["source_digest"] != m812["source_digest"]

    def test_corrupt_state_handling(self, tmp_path: Path):
        _, home, store = _init_store(tmp_path)
        seed_slice_to_ready_for_review(store, slice_name="S813", run_id="run-813")
        # Corrupt DB
        db = home / "state.db"
        db.write_bytes(b"not-a-sqlite-database")
        report = MetricsEngine(store).compute_for_slice("S813")
        assert report.get("status") == MetricStatus.UNAVAILABLE.value or "error" in report
        # Direct integrity check must fail closed
        with pytest.raises(Exception):
            store.verify_store_integrity()
