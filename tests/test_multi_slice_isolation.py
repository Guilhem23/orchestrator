"""Priority 6 — multi-slice coexistence, work-list CLI, receipt isolation."""

from __future__ import annotations

import json
import threading

from slice_orchestrator.cli import main
from slice_orchestrator.control_store import ControlStoreError
from slice_orchestrator.gates import run_control_test
from slice_orchestrator.orchestrator import SliceRunController


def test_two_slices_coexist_and_complete(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    a = ctrl.run_to_completion("S11")
    b = ctrl.run_to_completion("S12")
    assert a.state == "COMPLETE"
    assert b.state == "COMPLETE"
    assert a.run_id != b.run_id
    events = ctrl.store.get_events()
    slices = {e["slice"] for e in events}
    assert {"S11", "S12"} <= slices
    assert ctrl.store.list_slices() == ["S11", "S12"] or set(ctrl.store.list_slices()) == {"S11", "S12"}


def test_objectives_and_work_items_isolated(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.run_to_completion("S13")
    ctrl.run_to_completion("S14")
    s13 = ctrl.get_slice_state("S13")
    s14 = ctrl.get_slice_state("S14")
    objs13 = ctrl.store.list_objectives(s13.run_id, slice_name="S13")
    objs14 = ctrl.store.list_objectives(s14.run_id, slice_name="S14")
    assert objs13 and all(o.slice == "S13" for o in objs13)
    assert objs14 and all(o.slice == "S14" for o in objs14)
    assert {o.objective_id for o in objs13}.isdisjoint({o.objective_id for o in objs14})


def test_receipt_from_other_slice_rejected(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S15")
    (repo_dir / "test_sample.py").write_text("def test_pass(): assert True\n", encoding="utf-8")
    receipt = run_control_test(
        {"test_id": "t", "command": "pytest test_sample.py -q"},
        repo_dir, "tree", "rev", ctrl.store, slice_name="S15", run_id="other-run",
    )
    import pytest
    with pytest.raises(ControlStoreError, match="slice|run"):
        ctrl.store.verify_test_receipt_integrity(
            receipt, expected_slice="S16", expected_run_id=ctrl.get_slice_state("S15").run_id
        )


def test_work_list_zero_one_multiple(disposable_repo_and_control, monkeypatch, capsys):
    repo_dir, control_dir, _ = disposable_repo_and_control
    monkeypatch.chdir(repo_dir)
    monkeypatch.setattr(
        "slice_orchestrator.cli.get_controller",
        lambda repo_dir=None, control_home=None, adapter_id="dummy": SliceRunController(
            repo_dir or repo_dir, control_dir, configured_adapter_id=adapter_id
        ),
    )

    # The CLI constructs its own controller from cwd; point it at our control home
    def fake_get_controller(repo_dir=None, control_home=None, adapter_id="dummy"):
        return SliceRunController(repo_dir or repo_dir, control_dir, configured_adapter_id=adapter_id)

    # Patch using the real signature
    import slice_orchestrator.cli as cli_mod

    def patched(repo_dir=None, control_home=None, adapter_id="dummy"):
        from pathlib import Path
        cwd = (repo_dir or Path.cwd()).resolve()
        return SliceRunController(cwd, control_dir, configured_adapter_id=adapter_id)

    monkeypatch.setattr(cli_mod, "get_controller", patched)

    rc = main(["work", "list", "S99"])
    assert rc == 1
    capsys.readouterr()

    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    ctrl.open_run("S17")
    rc = main(["work", "list", "S17"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Objectives" in out
    assert "Work Items" in out

    ctrl.open_run("S18")
    rc = main(["work", "list", "S18"])
    assert rc == 0


def test_inspect_json_empty_is_array(disposable_repo_and_control, monkeypatch, capsys):
    repo_dir, control_dir, _ = disposable_repo_and_control
    import slice_orchestrator.cli as cli_mod

    def patched(repo_dir=None, control_home=None, adapter_id="dummy"):
        from pathlib import Path
        cwd = (repo_dir or Path.cwd()).resolve()
        return SliceRunController(cwd, control_dir, configured_adapter_id=adapter_id)

    monkeypatch.setattr(cli_mod, "get_controller", patched)
    monkeypatch.chdir(repo_dir)
    rc = main(["inspect", "S40", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_one_slice_cannot_invalidate_another(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    a = ctrl.run_to_completion("S19")
    assert a.state == "COMPLETE"
    b = ctrl.open_run("S20")
    assert b.state == "PLANNING"
    a2 = ctrl.get_slice_state("S19")
    assert a2.state == "COMPLETE"
    assert a2.sequence == a.sequence


def test_concurrent_operations_on_separate_slices(disposable_repo_and_control):
    repo_dir, control_dir, _ = disposable_repo_and_control
    errors: list[BaseException] = []
    states: dict[str, str] = {}

    def run_slice(name: str):
        try:
            ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
            st = ctrl.run_to_completion(name)
            states[name] = st.state
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=run_slice, args=("S21",))
    t2 = threading.Thread(target=run_slice, args=("S22",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    # Shared ref CAS must fail closed rather than corrupt the store.
    ctrl = SliceRunController(repo_dir, control_dir, configured_adapter_id="dummy")
    events = ctrl.store.verify_store_integrity()
    assert {e["slice"] for e in events} >= {"S21", "S22"}
    for name in ("S21", "S22"):
        st = ctrl.get_slice_state(name)
        assert st is not None
    for exc in errors:
        assert "update-ref" in str(exc) or "expected" in str(exc).lower()
