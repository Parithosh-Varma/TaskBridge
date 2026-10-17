"""Shared SQLite task store for TaskBridge (Claude <-> OpenCode)."""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("TASK_DB_PATH", Path(__file__).parent / "tasks.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  instructions TEXT NOT NULL,
  working_dir TEXT DEFAULT '',
  model TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  result TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_by TEXT DEFAULT 'claude',
  worker TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled", "waiting"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    for ddl in (
        "ALTER TABLE tasks ADD COLUMN model TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN depends_on TEXT DEFAULT '[]'",
        "ALTER TABLE tasks ADD COLUMN priority INTEGER DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN timeout_sec INTEGER DEFAULT 600",
        "ALTER TABLE tasks ADD COLUMN max_retries INTEGER DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN retry_model TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN attempts INTEGER DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN tags TEXT DEFAULT '[]'",
        "ALTER TABLE tasks ADD COLUMN idem_key TEXT DEFAULT NULL",
        "ALTER TABLE tasks ADD COLUMN permission TEXT DEFAULT 'full'",
        "ALTER TABLE tasks ADD COLUMN worktree_repo TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN worktree_branch TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN worktree_keep INTEGER DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN usage_json TEXT DEFAULT '{}'",
        "ALTER TABLE tasks ADD COLUMN structured_json TEXT DEFAULT '{}'",
        "ALTER TABLE tasks ADD COLUMN questions_json TEXT DEFAULT '[]'",
    ):
        name = ddl.split("ADD COLUMN ")[1].split()[0]
        if name not in cols:
            conn.execute(ddl)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idem ON tasks(idem_key) WHERE idem_key IS NOT NULL")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    _migrate(conn)
    return conn


def _as_json_list(v) -> str:
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return json.dumps(parsed if isinstance(parsed, list) else [v])
        except (json.JSONDecodeError, ValueError):
            return json.dumps([v] if v else [])
    return json.dumps(list(v or []))


def submit_task(title: str, instructions: str, working_dir: str = "", created_by: str = "claude",
                model: str = "", depends_on=None, priority: int = 0,
                timeout_sec: int = 600, max_retries: int = 0, retry_model: str = "",
                tags=None, idem_key: str = "", permission: str = "full",
                worktree_repo: str = "", worktree_branch: str = "",
                worktree_keep: bool = False) -> dict:
    title = (title or "").strip()
    instructions = (instructions or "").strip()
    if not title:
        raise ValueError("title is required")
    if not instructions:
        raise ValueError("instructions is required")
    permission = (permission or "full").strip()
    if permission not in ("full", "no-network", "readonly", "no-shell"):
        raise ValueError("permission must be full|no-network|readonly|no-shell")
    depends_on = list(depends_on or [])
    task_id = uuid.uuid4().hex[:12]
    now = _now()
    with get_conn() as conn:
        if idem_key:
            row = conn.execute("SELECT * FROM tasks WHERE idem_key = ?", (idem_key,)).fetchone()
            if row:
                task = dict(row)
                task["_deduped"] = True
                return task
        conn.execute(
            "INSERT INTO tasks (id, title, instructions, working_dir, model, depends_on,"
            " priority, timeout_sec, max_retries, retry_model, attempts, tags, idem_key,"
            " permission, worktree_repo, worktree_branch, worktree_keep,"
            " status, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (task_id, title, instructions, working_dir or "", model or "",
             json.dumps(depends_on), int(priority or 0),
             max(30, min(int(timeout_sec or 600), 1800)), max(0, min(int(max_retries or 0), 5)),
             retry_model or "", _as_json_list(tags), idem_key or None,
             permission, worktree_repo or "", worktree_branch or "",
             1 if worktree_keep else 0, created_by, now, now),
        )
    return get_task(task_id)


def list_tasks(status: str = "all", limit: int = 20, tag: str = "",
               since: str = "") -> list[dict]:
    limit = max(1, min(int(limit or 20), 100))
    with get_conn() as conn:
        if status and status != "all":
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status: {status}")
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at ASC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    tasks = [dict(r) for r in rows]
    if tag:
        tasks = [t for t in tasks if tag in (json.loads(t.get("tags") or "[]"))]
    if since:
        tasks = [t for t in tasks if (t.get("created_at") or "") >= since]
    return tasks


def get_many(task_ids: list[str]) -> dict[str, dict]:
    if not task_ids:
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE id IN ({','.join('?' * len(task_ids))})",
            tuple(task_ids)).fetchall()
    return {r["id"]: dict(r) for r in rows}


def get_task(task_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise KeyError(f"task not found: {task_id}")
    return dict(row)


def claim_task(task_id: str, worker: str = "opencode") -> dict:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status='running', worker=?, updated_at=? WHERE id=? AND status='pending'",
            (worker, now, task_id),
        )
        if cur.rowcount == 0:
            # either missing or not pending — surface current state
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(f"task not found: {task_id}")
            raise RuntimeError(f"task {task_id} is not pending (status={row['status']})")
    return get_task(task_id)


def complete_task(task_id: str, result: str = "", error: str = "", status: str = "completed",
                  structured: dict | None = None, usage: dict | None = None) -> dict:
    if status not in ("completed", "failed"):
        raise ValueError("status must be completed or failed")
    now = _now()
    with get_conn() as conn:
        if structured is not None or usage is not None:
            row = conn.execute("SELECT structured_json, usage_json FROM tasks WHERE id=?",
                               (task_id,)).fetchone()
            if not row:
                raise KeyError(f"task not found: {task_id}")
            merged_struct = json.loads(row["structured_json"] or "{}")
            if structured:
                merged_struct.update(structured)
            merged_usage = json.loads(row["usage_json"] or "{}")
            if usage:
                merged_usage.update(usage)
            cur = conn.execute(
                "UPDATE tasks SET status=?, result=?, error=?, structured_json=?,"
                " usage_json=?, updated_at=? WHERE id=? AND status IN ('pending','running','waiting')",
                (status, result or "", error or "", json.dumps(merged_struct),
                 json.dumps(merged_usage), now, task_id),
            )
        else:
            cur = conn.execute(
                "UPDATE tasks SET status=?, result=?, error=?, updated_at=? WHERE id=? AND status IN ('pending','running','waiting')",
                (status, result or "", error or "", now, task_id),
            )
        if cur.rowcount == 0:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(f"task not found: {task_id}")
            raise RuntimeError(f"task {task_id} already finished (status={row['status']})")
    return get_task(task_id)


def bump_attempt(task_id: str, model: str = "") -> dict:
    """Requeue after a failed attempt, optionally on another model.

    attempts is incremented by start_attempt (once per started attempt),
    not here, so top-level and usage counts always agree.
    """
    now = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"task not found: {task_id}")
        if model:
            conn.execute("UPDATE tasks SET model=?, status='pending', updated_at=? WHERE id=?",
                         (model, now, task_id))
        else:
            conn.execute("UPDATE tasks SET status='pending', updated_at=? WHERE id=?",
                         (now, task_id))
    return get_task(task_id)


def start_attempt(task_id: str) -> int:
    """Count a started attempt. Returns the 1-based attempt number."""
    with get_conn() as conn:
        row = conn.execute("SELECT attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"task not found: {task_id}")
        attempts = (row["attempts"] or 0) + 1
        conn.execute("UPDATE tasks SET attempts=? WHERE id=?", (attempts, task_id))
    return attempts


def set_waiting(task_id: str, question: str) -> dict:
    now = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT questions_json FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"task not found: {task_id}")
        qs = json.loads(row["questions_json"] or "[]")
        qs.append({"question": question, "asked_at": now, "answer": None})
        conn.execute("UPDATE tasks SET questions_json=?, status='waiting', updated_at=? WHERE id=?",
                     (json.dumps(qs), now, task_id))
    return get_task(task_id)


def answer_task(task_id: str, answer: str, author: str = "claude") -> dict:
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("answer is required")
    now = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"task not found: {task_id}")
        if row["status"] != "waiting":
            raise RuntimeError(f"task {task_id} is not waiting (status={row['status']})")
        qs = json.loads(row["questions_json"] or "[]")
        if qs and qs[-1].get("answer") is None:
            qs[-1]["answer"] = answer
            qs[-1]["answered_at"] = now
        new_instructions = (row["instructions"] or "") + (
            f"\n\n--- answer from {author} at {now} ---\n{answer}\n"
            f"(Resume the task with this answer. Do not re-ask settled questions.)")
        conn.execute("UPDATE tasks SET questions_json=?, instructions=?, status='pending', updated_at=? WHERE id=?",
                     (json.dumps(qs), new_instructions, now, task_id))
    return get_task(task_id)


def cancel_task(task_id: str) -> dict:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status='cancelled', updated_at=? WHERE id=? AND status IN ('pending','running','waiting')",
            (now, task_id),
        )
        if cur.rowcount == 0:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(f"task not found: {task_id}")
            raise RuntimeError(f"task {task_id} already finished (status={row['status']})")
    return get_task(task_id)


def queue_status() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
        last = conn.execute("SELECT id, title, status, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 1").fetchone()
    counts = {r["status"]: r["n"] for r in rows}
    return {"counts": counts, "total": sum(counts.values()), "most_recent": dict(last) if last else None}


def add_task_note(task_id: str, note: str, author: str = "claude") -> dict:
    note = (note or "").strip()
    if not note:
        raise ValueError("note is required")
    now = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"task not found: {task_id}")
        if row["status"] not in ("pending", "running"):
            raise RuntimeError(f"task {task_id} already finished (status={row['status']})")
        new_instructions = row["instructions"] + f"\n\n--- note from {author} at {now} ---\n{note}"
        conn.execute(
            "UPDATE tasks SET instructions=?, updated_at=? WHERE id=?",
            (new_instructions, now, task_id),
        )
    return get_task(task_id)


def clear_finished(statuses: tuple[str, ...] = ("completed", "failed", "cancelled"),
                   older_than_minutes: int = 30) -> dict:
    for s in statuses:
        if s not in ("completed", "failed", "cancelled"):
            raise ValueError(f"cannot clear status: {s}")
    # Never wipe results Claude may not have fetched yet: only delete tasks
    # finished longer ago than the grace period.
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(0, older_than_minutes))).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            f"DELETE FROM tasks WHERE status IN ({','.join('?' * len(statuses))}) AND updated_at < ?",
            tuple(statuses) + (cutoff,),
        )
        deleted = cur.rowcount
    return {"deleted": deleted, "statuses": list(statuses),
            "older_than_minutes": older_than_minutes}
