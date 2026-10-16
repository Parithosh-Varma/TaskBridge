#!/usr/bin/env python3
"""MCP server exposing an OpenCode task queue to the Claude app.

Claude flow:
  1. submit_task(title, instructions) -> task_id
  2. poll get_task(task_id) until status is completed/failed
  3. read `result` / `error`

OpenCode (this agent) flow — via shell, not MCP:
  ./tasks_cli.py pending
  ./tasks_cli.py show <id>
  ... do the work ...
  ./tasks_cli.py complete <id> --result "..."
"""
from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import task_store
import worker as worker_mod


def _transport_security() -> TransportSecuritySettings | None:
    # Hosts allowed to reach the HTTP endpoint (Host header allowlist).
    # Local-only by default; add tunnel/public hosts via MCP_ALLOWED_HOSTS
    # (comma-separated, e.g. "myname.trycloudflare.com").
    extra = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    allowed = ["127.0.0.1:*", "localhost:*", "[::1]:*"] + extra
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed,
    )


mcp = FastMCP(
    "opencode-bridge",
    host="127.0.0.1",
    port=8000,
    transport_security=_transport_security(),
)


@mcp.tool()
def submit_task(title: str, instructions: str, working_dir: str = "", model: str = "",
               depends_on: list[str] | None = None, priority: int = 0,
               timeout_sec: int = 600, max_retries: int = 0, retry_model: str = "",
               tags: list[str] | None = None, idempotency_key: str = "",
               permission: str = "full", worktree_repo: str = "",
               worktree_branch: str = "", worktree_keep: bool = False) -> dict:
    """Submit a task for the OpenCode agent to run.

    Args:
        title: Short task title.
        instructions: Full steps, context, acceptance criteria. Be explicit.
        working_dir: Absolute path the agent must operate in. Created if missing.
        model: Model for this task (see list_models). Empty = worker default.
        depends_on: Task ids that must complete first; their results are passed along.
        priority: Higher runs first (default 0).
        timeout_sec: Per-attempt timeout, 30-1800 (default 600).
        max_retries: Retries on failure, 0-5 (default 0).
        retry_model: Model to retry with. Empty = same model.
        tags: Labels for filtering in list_tasks.
        idempotency_key: Your unique key — resubmits with the same key return
            the original task instead of duplicating it.
        permission: full (default) | readonly (writes reverted after run) |
            no-network / no-shell (prompt-level constraints, recorded in usage).
        worktree_repo: Git repo to scope the task in via `git worktree add`.
        worktree_branch: Branch for the worktree (default: repo HEAD).
        worktree_keep: Keep the worktree after success (default removes it).
    Returns:
        Dict with task id, status=pending, and polling hint.
    """
    task = task_store.submit_task(
        title, instructions, working_dir, created_by="claude", model=model,
        depends_on=depends_on or [], priority=priority, timeout_sec=timeout_sec,
        max_retries=max_retries, retry_model=retry_model, tags=tags or [],
        idem_key=idempotency_key, permission=permission,
        worktree_repo=worktree_repo, worktree_branch=worktree_branch,
        worktree_keep=worktree_keep)
    if task.pop("_deduped", False):
        task["_note"] = "idempotency_key already seen — returning the original task."
    else:
        task["_hint"] = ("Poll get_task_result(task_id) — or wait_for([task_id]) — "
                         "until completed/failed, then read result/structured.")
    return task


@mcp.tool()
def list_tasks(status: str = "all", limit: int = 20, tag: str = "", since: str = "") -> list[dict]:
    """List tasks. status: all|pending|running|waiting|completed|failed|cancelled.
    tag filters by label, since filters by created_at (ISO timestamp)."""
    return task_store.list_tasks(status, limit, tag, since)


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Get one task with its status, result, and error output."""
    return task_store.get_task(task_id)


@mcp.tool()
def cancel_task(task_id: str) -> dict:
    """Cancel a pending or running task."""
    return task_store.cancel_task(task_id)


@mcp.tool()
def ping() -> dict:
    """Check the bridge is alive. Returns server time and task DB location."""
    from datetime import datetime, timezone
    return {
        "ok": True,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "db": str(task_store.DB_PATH),
    }


@mcp.tool()
def queue_status() -> dict:
    """Queue health: task counts by status plus the most recently active task.

    Use this to tell whether the OpenCode worker is picking tasks up —
    if pending tasks pile up with no recent activity, the worker is offline.
    """
    return task_store.queue_status()


@mcp.tool()
def get_task_result(task_id: str) -> dict:
    """Fetch the outcome of a task: status, result, structured summary,
    usage/cost info, questions asked, and error. Lighter than get_task."""
    import json as _json
    task = task_store.get_task(task_id)
    return {
        "id": task["id"],
        "title": task["title"],
        "status": task["status"],
        "result": task["result"],
        "structured": _json.loads(task.get("structured_json") or "{}"),
        "usage": _json.loads(task.get("usage_json") or "{}"),
        "questions": _json.loads(task.get("questions_json") or "[]"),
        "attempts": task.get("attempts", 0),
        "error": task["error"],
        "updated_at": task["updated_at"],
    }


@mcp.tool()
def add_task_note(task_id: str, note: str) -> dict:
    """Append extra context to a pending/running task before the worker finishes it."""
    return task_store.add_task_note(task_id, note, author="claude")


@mcp.tool()
def submit_batch(tasks: list[dict]) -> list[dict]:
    """Submit multiple tasks at once. Each item accepts the submit_task fields:
    {title, instructions, working_dir?, model?, depends_on?, priority?,
    timeout_sec?, max_retries?, retry_model?, tags?, idempotency_key?,
    permission?, worktree_repo?, worktree_branch?, worktree_keep?}.

    Returns the created tasks (ids + polling hints). Max 20 per call.
    """
    if not tasks or len(tasks) > 20:
        raise ValueError("submit 1-20 tasks per call")
    out = []
    for t in tasks:
        task = task_store.submit_task(
            t.get("title", ""), t.get("instructions", ""),
            t.get("working_dir", ""), created_by="claude",
            model=t.get("model", ""), depends_on=t.get("depends_on", []),
            priority=t.get("priority", 0), timeout_sec=t.get("timeout_sec", 600),
            max_retries=t.get("max_retries", 0), retry_model=t.get("retry_model", ""),
            tags=t.get("tags", []), idem_key=t.get("idempotency_key", ""),
            permission=t.get("permission", "full"),
            worktree_repo=t.get("worktree_repo", ""),
            worktree_branch=t.get("worktree_branch", ""),
            worktree_keep=t.get("worktree_keep", False),
        )
        if task.pop("_deduped", False):
            task["_note"] = "idempotency_key already seen — returning the original task."
        out.append(task)
    return out


@mcp.tool()
def clear_finished(older_than_minutes: int = 30) -> dict:
    """Delete completed/failed/cancelled tasks to keep the queue tidy.

    Safety: only tasks finished longer ago than older_than_minutes are
    removed, so results Claude hasn't fetched yet are never wiped.
    """
    return task_store.clear_finished(older_than_minutes=older_than_minutes)


@mcp.tool()
def list_models(search: str = "", limit: int = 100) -> dict:
    """List models the OpenCode worker can run (provider/model format).

    Args:
        search: Case-insensitive filter, e.g. 'haiku' or 'opencode/'.
        limit: Max entries (default 100).
    Pass a chosen model as `model` in submit_task, or set the worker-wide
    default with set_default_model.
    """
    models = worker_mod.list_available_models(search, limit)
    return {"models": models, "count": len(models),
            "worker_default": worker_mod.default_model()}


@mcp.tool()
def set_default_model(model: str) -> dict:
    """Change the worker's default model (validated; persists in worker_config.json).

    Per-task `model` in submit_task still overrides this for that task only.
    """
    chosen = worker_mod.set_default_model(model)
    return {"worker_default": chosen}


@mcp.tool()
def get_task_logs(task_id: str, since_offset: int = 0, max_chars: int = 8000) -> dict:
    """Stream a task's live execution log. Pass back next_offset to tail it.

    Works while the task runs (status running) and after it finishes.
    """
    import os as _os
    log_path = worker_mod.LOGS_DIR / f"{task_id}.log"
    if not log_path.exists():
        # validate id while explaining the miss
        task_store.get_task(task_id)
        return {"task_id": task_id, "log": "", "next_offset": 0,
                "total_bytes": 0, "done": False,
                "note": "no log yet — worker has not started this task"}
    total = log_path.stat().st_size
    since_offset = max(0, min(int(since_offset or 0), total))
    with open(log_path, "rb") as f:
        f.seek(since_offset)
        chunk = f.read(max(100, min(int(max_chars or 8000), 50000)))
    try:
        status = task_store.get_task(task_id)["status"]
    except KeyError:
        status = "unknown"
    done = status in ("completed", "failed", "cancelled")
    return {"task_id": task_id, "log": chunk.decode(errors="replace"),
            "next_offset": since_offset + len(chunk), "total_bytes": total,
            "done": done}


@mcp.tool()
def worker_heartbeat(max_stale_sec: int = 180) -> dict:
    """Worker liveness: last poll time, version, active default model.

    alive=false means the launchd daemon hasn't checked in — tasks will pile up.
    """
    import datetime as _dt
    hb_path = worker_mod.HEARTBEAT_PATH
    out: dict = {"alive": False, "worker_default": worker_mod.default_model(),
                 "version": worker_mod.WORKER_VERSION}
    if not hb_path.exists():
        out["note"] = "no heartbeat yet — daemon may never have run"
        return out
    import json as _json
    hb = _json.loads(hb_path.read_text())
    out.update(hb)
    try:
        ts = _dt.datetime.fromisoformat(hb["ts"])
        age = (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds()
    except (KeyError, ValueError):
        age = float("inf")
    out["age_sec"] = int(age)
    out["alive"] = age <= max(30, int(max_stale_sec or 180))
    return out


@mcp.tool()
def wait_for(task_ids: list[str], timeout_sec: int = 120) -> dict:
    """Block until tasks finish — replaces client poll loops.

    Returns when every id is completed/failed/cancelled, or when any task
    starts waiting on a question for you (answer it with answer_task, then
    wait again), or on timeout (timed_out=true, check statuses and retry).
    """
    import time as _time
    if not task_ids or len(task_ids) > 20:
        raise ValueError("wait for 1-20 task ids")
    deadline = _time.time() + max(5, min(int(timeout_sec or 120), 600))
    last: dict = {}
    while True:
        states = task_store.get_many(task_ids)
        last = {i: states.get(i, {}).get("status", "unknown") for i in task_ids}
        if any(s == "waiting" for s in last.values()):
            return {"all_done": False, "waiting_on_you": True, "timed_out": False,
                    "tasks": [{"id": i, "status": s} for i, s in last.items()]}
        if all(s in ("completed", "failed", "cancelled") for s in last.values()):
            return {"all_done": True, "waiting_on_you": False, "timed_out": False,
                    "tasks": [{"id": i, "status": s} for i, s in last.items()]}
        if _time.time() >= deadline:
            return {"all_done": False, "waiting_on_you": False, "timed_out": True,
                    "tasks": [{"id": i, "status": s} for i, s in last.items()]}
        _time.sleep(3)


@mcp.tool()
def answer_task(task_id: str, answer: str) -> dict:
    """Answer the worker's mid-task question. The task resumes automatically
    on the next worker pass with your answer appended to its instructions."""
    task = task_store.answer_task(task_id, answer, author="claude")
    qs = task.get("questions_json", "[]")
    return {"id": task["id"], "status": task["status"],
            "note": "answer recorded — task requeued, worker resumes shortly."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OpenCode bridge MCP server (Claude side)")
    ap.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="stdio (Claude Desktop spawns this) or streamable-http/sse (persistent URL)",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport)
