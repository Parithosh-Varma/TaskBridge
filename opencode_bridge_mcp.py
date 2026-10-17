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
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

import task_store
import worker as worker_mod

HERE = Path(__file__).parent
DASHBOARD_PATH = HERE / "bridge_dashboard.html"
CLAUDE_JOBS_DIR = HERE / "claude_jobs"
TOKEN_FILE = HERE / ".bridge-token"


def _load_auth_token() -> str | None:
    """Load bearer token from env var or .bridge-token file."""
    token = os.environ.get("BRIDGE_AUTH_TOKEN", "").strip()
    if not token:
        try:
            if TOKEN_FILE.exists():
                token = TOKEN_FILE.read_text().strip()
        except (OSError, ValueError):
            pass
    return token or None


def _auth_middleware(app: ASGIApp) -> ASGIApp:
    """Simple bearer auth middleware for HTTP transport.
    
    Requires Authorization: Bearer <token> for all routes except:
    - /health (open for monitoring)
    - / (dashboard page, serves HTML)
    - Static assets served via dashboard
    """
    token = _load_auth_token()
    
    async def middleware(scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        
        # Open routes (no auth required)
        if path == "/health" or path == "/":
            await app(scope, receive, send)
            return
        
        # If no token configured, allow all (dev mode)
        if not token:
            await app(scope, receive, send)
            return
        
        # Check Authorization header
        auth_header = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                auth_header = v.decode()
                break
        
        if not auth_header or not auth_header.startswith("Bearer "):
            response = Response(
                "Unauthorized: Bearer token required",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer realm=\"bridge\""},
            )
            await response(scope, receive, send)
            return
        
        provided_token = auth_header[7:].strip()
        if not hmac.compare_digest(provided_token, token):
            response = Response(
                "Unauthorized: Invalid bearer token",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer realm=\"bridge\""},
            )
            await response(scope, receive, send)
            return
        
        await app(scope, receive, send)
    
    return middleware


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
    "taskbridge",
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
               worktree_branch: str = "", worktree_keep: bool = False,
               origin: str = "", ctx: Context | None = None) -> dict:
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
        origin: Optional override ('chatgpt' etc.). Empty = auto-detected
            from your MCP handshake, shown as the origin mark on the board.
    Returns:
        Dict with task id, status=pending, and polling hint.
    """
    who, raw = _resolve_origin(origin, ctx)
    print(f"submit_task from client {raw!r} -> origin {who}", flush=True)
    task = task_store.submit_task(
        title, instructions, working_dir, created_by=who, model=model,
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
def submit_batch(tasks: list[dict], origin: str = "", ctx: Context | None = None) -> list[dict]:
    """Submit multiple tasks at once. Each item accepts the submit_task fields:
    {title, instructions, working_dir?, model?, depends_on?, priority?,
    timeout_sec?, max_retries?, retry_model?, tags?, idempotency_key?,
    permission?, worktree_repo?, worktree_branch?, worktree_keep?}.

    origin is an optional override; empty = auto-detected from your
    MCP handshake and applied to the whole batch.

    Returns the created tasks (ids + polling hints). Max 20 per call.
    """
    if not tasks or len(tasks) > 20:
        raise ValueError("submit 1-20 tasks per call")
    who, raw = _resolve_origin(origin, ctx)
    print(f"submit_batch ({len(tasks)}) from client {raw!r} -> origin {who}", flush=True)
    out = []
    for t in tasks:
        task = task_store.submit_task(
            t.get("title", ""), t.get("instructions", ""),
            t.get("working_dir", ""), created_by=who,
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


# ---------------- live dashboard (same port, same ngrok URL) ----------------
# GET / serves a no-dependency HTML page that polls the /api/* endpoints
# below, so opening the ngrok URL in a browser shows exactly what the
# agent is doing: queue, per-task live logs, reverse Claude jobs, worker log.
# None of this touches the MCP tools at /mcp.

def _alive(pid: int) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _summary(t: dict) -> dict:
    model = t.get("model", "") or ""
    return {
        "id": t.get("id", ""), "title": t.get("title", ""),
        "status": t.get("status", ""), "model": model,
        "origin": t.get("created_by", "") or "claude",
        "provider": model.split("/")[0] if "/" in model else "",
        "attempts": t.get("attempts", 0), "priority": t.get("priority", 0),
        "created_at": t.get("created_at", ""), "updated_at": t.get("updated_at", ""),
    }


def _clean_origin(origin: str) -> str:
    """Short lowercase origin tag: claude | chatgpt | opencode | ..."""
    cleaned = "".join(c for c in (origin or "").strip().lower() if c.isalnum())[:20]
    return cleaned or "claude"


def _detect_origin(ctx: Context | None) -> str:
    """True caller from the MCP handshake, not the caller's own label.

    Every MCP client introduces itself in `initialize` with
    clientInfo {name, version} before any tool call — Claude sends a
    claude-* name, ChatGPT sends its own. Unknown clients return ""
    (caller falls back to the default so the task still runs).
    """
    try:
        params = ctx.session.client_params if ctx is not None else None
        info = getattr(params, "clientInfo", None)
        name = (f"{getattr(info, 'name', '') or ''} "
                f"{getattr(info, 'version', '') or ''}").lower()
    except Exception:
        return ""
    if "chatgpt" in name or "openai" in name:
        return "chatgpt"
    if "claude" in name or "anthropic" in name:
        return "claude"
    if "opencode" in name:
        return "opencode"
    return ""


def _resolve_origin(origin: str, ctx: Context | None) -> tuple[str, str]:
    """Final origin tag + raw handshake name (for the log).

    An explicit non-default label wins; otherwise the handshake decides;
    otherwise "claude" so the worker still picks the task up.
    """
    try:
        params = ctx.session.client_params if ctx is not None else None
        info = getattr(params, "clientInfo", None)
        raw = str(getattr(info, "name", "") or "")
    except Exception:
        raw = ""
    who = _clean_origin(origin)
    if who in ("", "claude"):
        who = _detect_origin(ctx) or "claude"
    return who, raw


def _heartbeat() -> dict:
    out: dict = {"alive": False, "worker_default": worker_mod.default_model(),
                 "version": worker_mod.WORKER_VERSION, "age_sec": None,
                 "current_task": ""}
    try:
        hb = json.loads(worker_mod.HEARTBEAT_PATH.read_text())
        out.update(hb)
        from datetime import datetime, timezone
        try:
            ts = datetime.fromisoformat(hb["ts"])
            out["age_sec"] = int((datetime.now(timezone.utc) - ts).total_seconds())
            out["alive"] = out["age_sec"] <= 180
        except (KeyError, ValueError):
            pass
    except (OSError, ValueError):
        out["note"] = "no heartbeat yet — daemon may never have run"
    return out


def _claude_jobs(limit: int = 10) -> list[dict]:
    jobs: list[dict] = []
    if not CLAUDE_JOBS_DIR.is_dir():
        return jobs
    metas = sorted(CLAUDE_JOBS_DIR.glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:max(1, min(limit, 20))]
    for meta in metas:
        try:
            job = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        if job.get("status") == "running" and not _alive(job.get("pid", -1)):
            job["status"] = "done"
            try:
                meta.write_text(json.dumps(job, indent=2))
            except OSError:
                pass
        jobs.append({
            "id": job.get("id", meta.stem),
            "status": job.get("status", ""),
            "backend": job.get("backend", ""),
            "prompt": (job.get("prompt", "") or "")[:300],
            "created_at": job.get("created_at", ""),
        })
    return jobs


def _read_chunk(path: Path, offset: int, max_chars: int) -> tuple[str, int, int]:
    try:
        total = path.stat().st_size
    except OSError:
        return "", 0, 0
    offset = max(0, min(int(offset or 0), total))
    max_chars = max(100, min(int(max_chars or 8000), 50000))
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(max_chars)
    return chunk.decode(errors="replace"), offset + len(chunk), total


@mcp.custom_route("/", methods=["GET"])
async def dashboard_page(request: Request) -> HTMLResponse:
    try:
        html = DASHBOARD_PATH.read_text()
    except OSError:
        html = "<h1>Bridge Live</h1><p>dashboard file missing.</p>"
    return HTMLResponse(html)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@mcp.custom_route("/api/overview", methods=["GET"])
async def api_overview(request: Request) -> JSONResponse:
    try:
        counts_task = task_store.queue_status()
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=500)
    try:
        recent = [_summary(t) for t in task_store.list_tasks("all", 30, "", "")]
    except Exception:
        recent = []
    hb = _heartbeat()
    try:
        tail, _, _ = _tail(worker_mod.HERE / "worker.log", 6000)
    except Exception:
        tail = ""
    return JSONResponse({
        "counts": counts_task.get("counts", {}),
        "total": counts_task.get("total", 0),
        "most_recent": counts_task.get("most_recent"),
        "recent": recent,
        "heartbeat": hb,
        "worker_default": worker_mod.default_model(),
        "claude_jobs": _claude_jobs(),
        "worker_log_tail": tail,
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def _tail(path: Path, max_chars: int) -> tuple[str, int, int]:
    try:
        total = path.stat().st_size
    except OSError:
        return "", 0, 0
    with open(path, "rb") as f:
        f.seek(max(0, total - max_chars))
        data = f.read().decode(errors="replace")
    return data, total, total


@mcp.custom_route("/api/tasks", methods=["GET"])
async def api_tasks(request: Request) -> JSONResponse:
    status = request.query_params.get("status", "all")
    try:
        limit = max(1, min(int(request.query_params.get("limit", "50")), 100))
    except ValueError:
        limit = 50
    try:
        tasks = [_summary(t) for t in task_store.list_tasks(status, limit, "", "")]
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=400)
    return JSONResponse({"tasks": tasks})


@mcp.custom_route("/api/task", methods=["GET"])
async def api_task(request: Request) -> JSONResponse:
    task_id = (request.query_params.get("id") or "").strip()
    if not task_id:
        return JSONResponse({"error": "id is required"}, status_code=400)
    try:
        off = int(request.query_params.get("log_offset", "0") or 0)
    except ValueError:
        off = 0
    try:
        nchars = int(request.query_params.get("log_chars", "30000") or 30000)
    except ValueError:
        nchars = 30000
    nchars = max(100, min(nchars, 50000))
    try:
        task = task_store.get_task(task_id)
    except KeyError:
        return JSONResponse({"error": f"task not found: {task_id}"}, status_code=404)
    log_path = worker_mod.LOGS_DIR / f"{task_id}.log"
    if off < 0:
        # tail mode: last nchars bytes (the interesting end of a finished log)
        try:
            off = max(0, log_path.stat().st_size - nchars)
        except OSError:
            off = 0
    start = off
    log, nxt, total = _read_chunk(log_path, off, nchars)
    if not log_path.exists():
        note = "no log yet — worker has not started this task"
    elif task.get("status") in ("completed", "failed", "cancelled"):
        note = "task finished — showing final log"
    else:
        note = "streaming live — auto-refreshes every 2s"
    return JSONResponse({
        "task": task, "log": log, "next_offset": nxt, "start_offset": start,
        "total_bytes": total, "done": task.get("status") in ("completed", "failed", "cancelled"),
        "note": note,
    })


@mcp.custom_route("/api/worker-log", methods=["GET"])
async def api_worker_log(request: Request) -> JSONResponse:
    try:
        nchars = int(request.query_params.get("tail_chars", "15000") or 15000)
    except ValueError:
        nchars = 15000
    tail, _, total = _tail(worker_mod.HERE / "worker.log", max(100, min(nchars, 50000)))
    return JSONResponse({"log": tail, "total_bytes": total,
                         "heartbeat": _heartbeat()})


@mcp.custom_route("/api/claude-job", methods=["GET"])
async def api_claude_job(request: Request) -> JSONResponse:
    job_id = (request.query_params.get("id") or "").strip()
    if not job_id:
        return JSONResponse({"error": "id is required"}, status_code=400)
    meta = CLAUDE_JOBS_DIR / f"{job_id}.json"
    out_path = CLAUDE_JOBS_DIR / f"{job_id}.out"
    if not meta.exists():
        return JSONResponse({"error": f"job not found: {job_id}"}, status_code=404)
    try:
        job = json.loads(meta.read_text())
    except ValueError:
        return JSONResponse({"error": "job file corrupt"}, status_code=500)
    if job.get("status") == "running" and not _alive(job.get("pid", -1)):
        job["status"] = "done"
        try:
            meta.write_text(json.dumps(job, indent=2))
        except OSError:
            pass
    try:
        nchars = int(request.query_params.get("tail_chars", "8000") or 8000)
    except ValueError:
        nchars = 8000
    tail = out_path.read_text()[-max(100, min(nchars, 50000)):] if out_path.exists() else ""
    return JSONResponse({"job_id": job_id, "status": job.get("status", ""),
                         "backend": job.get("backend", ""),
                         "output_tail": tail})


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
    
    # Wrap HTTP app with auth middleware
    if args.transport != "stdio":
        original_streamable_app = mcp.streamable_http_app
        original_sse_app = mcp.sse_app
        
        def wrapped_streamable_app():
            app = original_streamable_app()
            return _auth_middleware(app)
        
        def wrapped_sse_app(mount_path=None):
            app = original_sse_app(mount_path)
            return _auth_middleware(app)
        
        mcp.streamable_http_app = wrapped_streamable_app
        mcp.sse_app = wrapped_sse_app
    
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport)
