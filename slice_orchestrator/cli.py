"""
CLI Interface for Method v4 Slice Orchestrator.
Supports commands: plan, status, run, inspect, explain, pause, resume, stop, recover, work, explore.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from slice_orchestrator.exploration import ExplorationManager
from slice_orchestrator.orchestrator import OrchestratorError, SliceRunController


def get_controller(
    repo_dir: Path | None = None,
    control_home: Path | None = None,
    adapter_id: str = "dummy",
) -> SliceRunController:
    cwd = (repo_dir or Path.cwd()).resolve()
    home = (control_home or cwd / ".orchestrator_slice").resolve()
    return SliceRunController(repo_dir=cwd, control_home=home, configured_adapter_id=adapter_id)


def cmd_plan(args: argparse.Namespace) -> int:
    ctrl = get_controller(adapter_id=args.adapter)
    state = ctrl.get_slice_state(args.slice) or ctrl.open_run(args.slice)
    print(f"Slice {args.slice} initialized in state {state.state} (Run ID: {state.run_id})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    state = ctrl.get_slice_state(args.slice)
    if not state:
        print(f"Slice {args.slice}: No active or past Slice Run.")
        return 0

    print(f"Slice:             {state.slice}")
    print(f"Run ID:            {state.run_id}")
    print(f"State:             {state.state}")
    print(f"Mode:              {state.execution_mode}")
    print(f"Generation:        {state.run_generation}")
    print(f"Sequence:          {state.sequence}")
    print(f"Review Cycle:      {state.review_cycle_high_water}")
    print(f"Remediation Cycle: {state.remediation_cycle_high_water}")
    if state.stop_reason:
        print(f"Stop Reason:       [{state.stop_reason_code}] {state.stop_reason}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ctrl = get_controller(adapter_id=args.adapter)
    marker = " [TEST-ONLY dummy worker]" if args.adapter == "dummy" else ""
    print(f"Driving slice {args.slice} to completion with worker adapter '{args.adapter}'{marker}...")
    final_state = ctrl.run_to_completion(args.slice)
    print(f"Slice {args.slice} execution ended in state: {final_state.state}")
    if final_state.stop_reason:
        print(f"Reason: [{final_state.stop_reason_code}] {final_state.stop_reason}")
    return 0 if final_state.state == "COMPLETE" else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    events = ctrl.store.verify_store_integrity()
    slice_events = [e for e in events if e["slice"] == args.slice]
    if args.json:
        print(json.dumps(slice_events, indent=2))
        return 0

    if not slice_events:
        print(f"No events found for slice {args.slice}")
        return 0

    print(f"=== Event History for Slice {args.slice} ({len(slice_events)} events) ===")
    for ev in slice_events:
        recorded = ev.get('recorded_at') or ev.get('timestamp', 'N/A')
        print(
            f"Seq {ev['sequence']:3d} | {recorded} | Event: {ev['event_type']:35s} | "
            f"Actor: {ev['actor']['role']:20s} | Hash: {ev['event_hash'][:12]}..."
        )
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    explanation = ctrl.explain_slice(args.slice)
    print(explanation)
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    state = ctrl.pause_slice(args.slice, reason=args.reason or "Operator paused run")
    print(f"Slice {args.slice} execution mode updated: {state.execution_mode}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    ctrl = get_controller(adapter_id=args.adapter)
    state = ctrl.resume_slice(args.slice)
    print(f"Slice {args.slice} execution mode updated: {state.execution_mode}")
    if args.run:
        return cmd_run(args)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    state = ctrl.stop_slice(args.slice, reason=args.reason or "Operator stopped run")
    print(f"Slice {args.slice} state updated: {state.state}")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    state = ctrl.recover_slice(
        slice_name=args.slice,
        target_state=args.target_state,
        reason=args.reason or "Human recovery",
    )
    print(f"Slice {args.slice} recovered to state {state.state} (New Gen: {state.run_generation}, Run ID: {state.run_id})")
    return 0


def cmd_work(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    if args.work_cmd == "list":
        state = ctrl.get_slice_state(args.slice)
        if not state:
            print(f"No run found for slice {args.slice}")
            return 1
        objs = ctrl.store.list_objectives(state.run_id, slice_name=args.slice)
        items = ctrl.store.list_work_items(state.run_id, slice_name=args.slice)

        print(f"=== Objectives for Slice {args.slice} ===")
        if not objs:
            print("(none)")
        for obj in objs:
            print(f"[{obj.status:12s}] {obj.objective_id}: {obj.description}")

        print(f"\n=== Work Items for Slice {args.slice} ===")
        if not items:
            print("(none)")
        for item in items:
            print(
                f"[{item.status:16s}] {item.work_item_id:15s} | Type: {item.type:14s} | "
                f"Role: {item.assigned_role:20s} | Scope: {item.allowed_scope}"
            )
        return 0

    elif args.work_cmd == "inspect":
        item = ctrl.store.get_work_item(args.work_item_id)
        if not item:
            print(f"WorkItem {args.work_item_id} not found.")
            return 1
        print(json.dumps(item.to_dict(), indent=2))
        return 0

    elif args.work_cmd == "retry":
        item = ctrl.store.get_work_item(args.work_item_id)
        if not item:
            print(f"WorkItem {args.work_item_id} not found.")
            return 1
        item.status = "READY"
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        item.worker_execution_id = exec_id
        item.worker_execution_ids.append(exec_id)
        ctrl.store.save_work_item(item)
        print(f"WorkItem {args.work_item_id} set to READY for retry (New Exec ID: {exec_id})")
        return 0

    return 1


def cmd_explore(args: argparse.Namespace) -> int:
    ctrl = get_controller(adapter_id=args.adapter)
    mgr = ExplorationManager(ctrl.repo_dir, ctrl.store, ctrl.worker_registry)
    report = mgr.run_exploration(slice_name=args.slice, topic=args.topic, adapter_id=args.adapter)

    print(f"=== Exploration Mode Output for Slice {args.slice} ===")
    print(f"Exploration ID: {report.exploration_id}")
    print(f"Topic:          {report.topic}")
    print(f"Scratch Path:   {report.scratch_workspace_path}")
    print(f"Findings:\n{report.findings}")
    print(f"Recommendation:\n{report.recommendation}")
    print("NOTE: Exploration ran in disposable scratch space (NO COMMIT / NO GOVERNANCE).")
    return 0


def main(sys_args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="slice",
        description="Method v4 Slice Orchestrator CLI",
    )
    parser.add_argument("--adapter", default="dummy", help="Worker adapter ID (dummy, cursor, claude, gemini, manual)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # plan
    p_plan = subparsers.add_parser("plan", help="Initialize or plan a slice")
    p_plan.add_argument("slice", help="Slice identifier (e.g. S6, S99)")

    # status
    p_status = subparsers.add_parser("status", help="Show current status of a slice")
    p_status.add_argument("slice", help="Slice identifier")

    # run
    p_run = subparsers.add_parser("run", help="Autonomously drive slice to completion")
    p_run.add_argument("slice", help="Slice identifier")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect event stream for a slice")
    p_inspect.add_argument("slice", help="Slice identifier")
    p_inspect.add_argument("--json", action="store_true", help="Output raw JSON")

    # explain
    p_explain = subparsers.add_parser("explain", help="Explain current state, legal transitions, and blocking conditions")
    p_explain.add_argument("slice", help="Slice identifier")

    # pause
    p_pause = subparsers.add_parser("pause", help="Pause an active slice run")
    p_pause.add_argument("slice", help="Slice identifier")
    p_pause.add_argument("--reason", default="Operator paused run", help="Reason for pause")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume a paused slice run")
    p_resume.add_argument("slice", help="Slice identifier")
    p_resume.add_argument("--run", action="store_true", help="Drive to completion after resuming")

    # stop
    p_stop = subparsers.add_parser("stop", help="Stop a slice run")
    p_stop.add_argument("slice", help="Slice identifier")
    p_stop.add_argument("--reason", default="Operator stopped run", help="Reason for stop")

    # recover
    p_recover = subparsers.add_parser("recover", help="Recover a STOPPED slice run to a safe target state")
    p_recover.add_argument("slice", help="Slice identifier")
    p_recover.add_argument("--target-state", required=True, choices=["PLANNING", "PLAN_REVISION", "IMPLEMENTATION", "IMPLEMENTATION_READY_FOR_REVIEW"], help="Target recovery state")
    p_recover.add_argument("--reason", default="Human recovery", help="Reason for recovery")

    # work
    p_work = subparsers.add_parser("work", help="Work Item management commands")
    w_sub = p_work.add_subparsers(dest="work_cmd", required=True)
    w_list = w_sub.add_parser("list", help="List Objectives and Work Items for slice")
    w_list.add_argument("slice", help="Slice identifier")
    w_inspect = w_sub.add_parser("inspect", help="Inspect a Work Item")
    w_inspect.add_argument("work_item_id", help="Work Item ID")
    w_retry = w_sub.add_parser("retry", help="Retry a Work Item")
    w_retry.add_argument("work_item_id", help="Work Item ID")

    # explore
    p_explore = subparsers.add_parser("explore", help="Launch exploration mode in isolated scratch space")
    p_explore.add_argument("slice", help="Slice identifier")
    p_explore.add_argument("--topic", required=True, help="Exploration topic")

    parsed = parser.parse_args(sys_args)

    cmd_map = {
        "plan": cmd_plan,
        "status": cmd_status,
        "run": cmd_run,
        "inspect": cmd_inspect,
        "explain": cmd_explain,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "stop": cmd_stop,
        "recover": cmd_recover,
        "work": cmd_work,
        "explore": cmd_explore,
    }

    try:
        return cmd_map[parsed.command](parsed)
    except OrchestratorError as exc:
        print(f"Orchestrator Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
