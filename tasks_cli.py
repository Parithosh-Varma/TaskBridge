#!/usr/bin/env python3
"""CLI for the OpenCode side (this agent) to process Claude's tasks.

Usage:
  ./tasks_cli.py pending [--limit 20]
  ./tasks_cli.py list [--status all] [--limit 20]
  ./tasks_cli.py show <id>
  ./tasks_cli.py claim <id> [--worker opencode]
  ./tasks_cli.py complete <id> --result "..."        # or --result-file out.txt
  ./tasks_cli.py fail <id> --error "..."
  ./tasks_cli.py restart-worker [--force] [--timeout 90]   # via launchd
  ./tasks_cli.py supervisor-status
"""
from __future__ import annotations
import argparse
import json
import sys

import task_store


def _print(obj):
    print(json.dumps(obj, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(description="OpenCode worker CLI for Claude task bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("pending", help="list pending tasks (what Claude is waiting on)")
    pp.add_argument("--limit", type=int, default=20)

    lp = sub.add_parser("list", help="list tasks")
    lp.add_argument("--status", default="all")
    lp.add_argument("--limit", type=int, default=20)
    lp.add_argument("--tag", default="")
    lp.add_argument("--since", default="")

    sp = sub.add_parser("show", help="show one task")
    sp.add_argument("id")

    cp = sub.add_parser("claim", help="mark pending task as running")
    cp.add_argument("id")
    cp.add_argument("--worker", default="opencode")

    dp = sub.add_parser("complete", help="mark task completed with result")
    dp.add_argument("id")
    g = dp.add_mutually_exclusive_group(required=True)
    g.add_argument("--result", default=None)
    g.add_argument("--result-file", default=None)

    fp = sub.add_parser("fail", help="mark task failed")
    fp.add_argument("id")
    fp.add_argument("--error", required=True)

    mp = sub.add_parser("leave-message", help="leave a message for Claude to read (worker will not touch it)")
    mp.add_argument("--text", required=True)

    gp = sub.add_parser("logs", help="tail a task's execution log")
    gp.add_argument("id")
    gp.add_argument("--offset", type=int, default=0)

    sub.add_parser("heartbeat", help="show worker heartbeat file")

    rw = sub.add_parser("restart-worker",
                        help="restart the worker via launchd (skips if healthy)")
    rw.add_argument("--force", action="store_true",
                    help="restart even when the worker is healthy")
    rw.add_argument("--timeout", type=int, default=None,
                    help="seconds to wait for a verified recovery (10-600)")

    sub.add_parser("supervisor-status",
                   help="launchd service + heartbeat + queue snapshot")

    ap = sub.add_parser("answer", help="answer a waiting task's question (requeues it)")
    ap.add_argument("id")
    ap.add_argument("--answer", required=True)

    args = p.parse_args()
    try:
        if args.cmd == "pending":
            _print(task_store.list_tasks("pending", args.limit))
        elif args.cmd == "list":
            _print(task_store.list_tasks(args.status, args.limit, args.tag, args.since))
        elif args.cmd == "show":
            _print(task_store.get_task(args.id))
        elif args.cmd == "claim":
            _print(task_store.claim_task(args.id, args.worker))
        elif args.cmd == "complete":
            result = args.result
            if args.result_file:
                with open(args.result_file) as f:
                    result = f.read()
            _print(task_store.complete_task(args.id, result=result or ""))
        elif args.cmd == "fail":
            _print(task_store.complete_task(args.id, error=args.error, status="failed"))
        elif args.cmd == "leave-message":
            _print(task_store.submit_task(
                "Message from OpenCode (not a task — just read it)",
                args.text, created_by="opencode"))
        elif args.cmd == "logs":
            from pathlib import Path
            p = Path(__file__).parent / "task_logs" / f"{args.id}.log"
            data = p.read_bytes()[args.offset:] if p.exists() else b"(no log yet)"
            print(data.decode(errors="replace"))
        elif args.cmd == "heartbeat":
            from pathlib import Path
            p = Path(__file__).parent / "heartbeat.json"
            print(p.read_text() if p.exists() else "(no heartbeat yet)")
        elif args.cmd == "supervisor-status":
            import worker_supervisor
            _print(worker_supervisor.default_supervisor().status())
        elif args.cmd == "restart-worker":
            import worker_supervisor
            res = worker_supervisor.restart_worker(force=args.force,
                                                   timeout_sec=args.timeout)
            _print(res)
            if not res.get("success"):
                return 1
        elif args.cmd == "answer":
            _print(task_store.answer_task(args.id, args.answer, author="opencode"))
    except (KeyError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
