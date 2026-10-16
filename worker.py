#!/usr/bin/env python3
"""Auto-worker: poll the Claude task queue and execute pending tasks headlessly.

Designed for launchd (one pass per invocation, exits when queue is empty):
  ./worker.py   (every 60s via com.claude-opencode-bridge.worker)

Per pass, oldest-first within priority (priority DESC, created_at ASC):
  1. claim  -> running   (skips: non-claude mail, unmet dependencies)
  2. snapshot workdir for diff summary
  3. run `opencode run --auto --model <task.model or default>`, streaming
     stdout/stderr live into task_logs/<id>.log (tail via get_task_logs)
  4. parse structured result block (```json) and mid-task questions
     (```question) from the output
  5. complete (result + structured + usage + diff) | waiting (question asked)
     | requeue (retries left, optionally on retry_model) | failed

Folders: working_dir is created if missing; the agent is pinned to it.
Worktrees: worktree_repo -> `git worktree add` sandbox, removed on success
unless worktree_keep. Permissions: full | no-network | readonly (sandbox-exec
enforced) | no-shell (prompt-level only, recorded honestly).

Logs to worker.log. macOS banner on completion / failure / question.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "opencode")
WORKER_VERSION = "2.0.0"
# Free model that works without paid credits; override with WORKER_MODEL env.
WORKER_MODEL = os.environ.get("WORKER_MODEL", "opencode/cat-jam-free")
CONFIG_PATH = HERE / "worker_config.json"
LOG_FILE = HERE / "worker.log"
LOGS_DIR = HERE / "task_logs"
WORKTREES_DIR = HERE / "worktrees"
HEARTBEAT_PATH = HERE / "heartbeat.json"
LOGS_DIR.mkdir(exist_ok=True)
# Set WORKER_NOTIFY=0 to silence macOS banners (results still land in tasks.db + worker.log).
NOTIFY = os.environ.get("WORKER_NOTIFY", "1") == "1"
MAX_TASKS_PER_PASS = 3
MAX_RESULT_CHARS = 8000

sys.path.insert(0, str(HERE))
import task_store


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def notify(title: str, message: str, sound: str = "Glass") -> None:
    """macOS Notification Center banner. Best-effort: never fails the task."""
    if not NOTIFY:
        return
    try:
        msg = message.replace('"', "'")[:300]
        t = title.replace('"', "'")[:80]
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{t}" sound name "{sound}"'],
            capture_output=True,
            timeout=10,
        )
    except Exception as e:
        log(f"notify failed (non-fatal): {e}")


def heartbeat(claimed: int = 0, current_task: str = "") -> None:
    try:
        HEARTBEAT_PATH.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "version": WORKER_VERSION,
            "default_model": default_model(),
            "pid": os.getpid(),
            "claimed_this_pass": claimed,
            "current_task": current_task,
        }, indent=2))
    except OSError as e:
        log(f"heartbeat write failed: {e}")


REAP_SLACK_SEC = 120


def requeue_stale_running(stale_after_sec: int = 900) -> int:
    """Tasks stuck in running (dead worker / killed pass) go back to pending.

    Staleness is PER-TASK: deadline = max(stale_after_sec, timeout_sec +
    REAP_SLACK_SEC) after updated_at. A flat 900s would reap a live task
    whose timeout_sec is larger (tasks may run up to 1800s).

    Also kills the orphaned opencode child (own process group) so a requeued
    task can't double-run alongside the zombie of its first attempt. The
    pidfile's pgid is validated before killing (see _orphan_looks_like_ours)
    so a reused pid never kills an unrelated process group.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    requeued = 0
    with task_store.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, timeout_sec, updated_at FROM tasks WHERE status='running'").fetchall()
        for r in rows:
            try:
                last = datetime.fromisoformat(r["updated_at"])
            except (TypeError, ValueError):
                last = now - timedelta(days=365)  # unparsable -> treat as stale
            deadline_sec = max(int(stale_after_sec),
                               int(r["timeout_sec"] or 600) + REAP_SLACK_SEC)
            if (now - last).total_seconds() < deadline_sec:
                continue
            _kill_orphan(r["id"])
            conn.execute("UPDATE tasks SET status='pending', updated_at=? WHERE id=?",
                         (task_store._now(), r["id"]))
            log(f"{r['id']}: stale running task requeued")
            requeued += 1
    return requeued


def _orphan_looks_like_ours(pid: int) -> tuple[bool, str]:
    """Pid-reuse guard: only trust the pidfile if pid still leads its own
    process group (start_new_session made pgid == pid) AND still runs
    opencode. Anything else -> do not kill."""
    try:
        out = subprocess.run(["ps", "-o", "pgid=,command=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"ps failed: {e}"
    line = (out.stdout or "").strip()
    if not line:
        return False, "leader no longer exists"
    parts = line.split(None, 1)
    try:
        pgid = int(parts[0])
    except (ValueError, IndexError):
        return False, f"unparsable ps line: {line[:80]!r}"
    cmd = parts[1] if len(parts) > 1 else ""
    if pgid != pid:
        return False, f"pgid {pgid} != {pid} (pid reused, not our group leader)"
    if "opencode" not in cmd:
        return False, f"leader is not an opencode child: {cmd[:80]!r}"
    return True, cmd[:80]


def _kill_orphan(task_id: str) -> None:
    pid_path = LOGS_DIR / f"{task_id}.pid"
    try:
        raw = pid_path.read_text().strip()
    except OSError:
        return
    try:
        pid = int(raw)
    except ValueError:
        # placeholder survived: worker died between spawn and the real pid
        # write. Cannot kill safely, but say so instead of silently trusting.
        log(f"{task_id}: pidfile holds {raw!r} — possible untracked orphan "
            "(worker died in the spawn window); requeueing without kill")
        return
    ok, why = _orphan_looks_like_ours(pid)
    if ok:
        try:
            import signal as _sig
            os.killpg(pid, _sig.SIGKILL)  # child was started with start_new_session
            log(f"{task_id}: killed orphaned worker child pgid {pid} ({why[:60]})")
        except (ProcessLookupError, PermissionError, OSError) as e:
            log(f"{task_id}: orphan kill failed ({e})")
    else:
        log(f"{task_id}: orphan kill SKIPPED (pidfile={pid}): {why}")
    try:
        pid_path.unlink()
    except OSError:
        pass


def default_model() -> str:
    """Worker default model: config file > env > builtin free model."""
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text())
            if cfg.get("default_model"):
                return cfg["default_model"]
    except Exception as e:
        log(f"config read failed ({e}), using builtin default")
    return WORKER_MODEL


def set_default_model(model: str) -> str:
    """Persist a new worker default model (validated against opencode models)."""
    model = (model or "").strip()
    if not model:
        raise ValueError("model is required, e.g. 'opencode/cat-jam-free'")
    available = list_available_models()
    if model not in available:
        close = [m for m in available if model.lower() in m.lower()][:5]
        raise ValueError(f"unknown model '{model}'. Did you mean one of: {close or available[:5]}?")
    CONFIG_PATH.write_text(json.dumps({"default_model": model}, indent=2))
    return model


def list_available_models(search: str = "", limit: int = 100) -> list[str]:
    """All models opencode can run. Optional case-insensitive filter."""
    try:
        proc = subprocess.run(
            [OPENCODE_BIN, "models"], capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise RuntimeError(f"could not list opencode models: {e}")
    if proc.returncode != 0:
        raise RuntimeError(f"`opencode models` failed: {(proc.stderr or '')[-300:]}")
    models = [ln.strip() for ln in (proc.stdout or "").splitlines() if "/" in ln.strip()]
    if search:
        models = [m for m in models if search.lower() in m.lower()]
    return models[:max(1, min(limit, 200))]


# ---------------- snapshots & diffs ----------------

def _snapshot(workdir: str) -> dict:
    """File state before the run, for the changed-files summary."""
    snap: dict = {"workdir": workdir, "git": None, "files": {}}
    try:
        out = subprocess.run(["git", "-C", workdir, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0:
            top = out.stdout.strip()
            st = subprocess.run(["git", "-C", workdir, "status", "--porcelain"],
                                capture_output=True, text=True, timeout=15)
            head = subprocess.run(["git", "-C", workdir, "rev-parse", "--short", "HEAD"],
                                  capture_output=True, text=True, timeout=15)
            snap["git"] = {"top": top,
                           "status": st.stdout if st.returncode == 0 else "",
                           "head": head.stdout.strip() if head.returncode == 0 else ""}
            return snap
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    for root, _, files in os.walk(workdir):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                stt = os.stat(p)
                snap["files"][os.path.relpath(p, workdir)] = (stt.st_size, int(stt.st_mtime))
            except OSError:
                pass
    return snap


def _diff_summary(workdir: str, before: dict) -> tuple[list[str], str]:
    """Changed files + short diff stat since the snapshot."""
    touched: list[str] = []
    stat = ""
    if before.get("git"):
        try:
            st = subprocess.run(["git", "-C", workdir, "status", "--porcelain"],
                                capture_output=True, text=True, timeout=15)
            if st.returncode == 0:
                after, old = st.stdout, before["git"]["status"]
                after_set = {l[3:] for l in after.splitlines() if len(l) > 3}
                old_set = {l[3:] for l in old.splitlines() if len(l) > 3}
                touched = sorted(after_set - old_set)
                d = subprocess.run(["git", "-C", workdir, "diff", "--stat", "HEAD", "--", "."],
                                   capture_output=True, text=True, timeout=15)
                if d.returncode == 0 and d.stdout.strip():
                    stat = d.stdout.strip()[-1500:]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return touched, stat
    after_files: dict = {}
    for root, _, files in os.walk(workdir):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                stt = os.stat(p)
                after_files[os.path.relpath(p, workdir)] = (stt.st_size, int(stt.st_mtime))
            except OSError:
                pass
    old_files = before.get("files", {})
    for rel, meta in after_files.items():
        if rel not in old_files or old_files[rel] != meta:
            touched.append(rel)
    return sorted(touched), ""


# ---------------- output parsing ----------------

def _extract_fenced(output: str, tag: str) -> list[dict]:
    """All ```tag {...} JSON blocks in the output, last one wins upstream."""
    found = []
    for m in re.finditer(rf"```{tag}\s*\n(.*?)\n```", output, re.DOTALL):
        try:
            found.append(json.loads(m.group(1)))
        except (json.JSONDecodeError, ValueError):
            pass
    if not found:
        # tolerate an unclosed trailing block (agent cut off / forgot fence)
        m = re.search(rf"```{tag}\s*\n(\{{.*)\s*$", output, re.DOTALL)
        if m:
            try:
                found.append(json.loads(m.group(1)))
            except (json.JSONDecodeError, ValueError):
                pass
    return found


def parse_structured(output: str) -> dict:
    """Structured result envelope; falls back to wrapping raw text."""
    blocks = _extract_fenced(output, "json")
    for block in reversed(blocks):
        if isinstance(block, dict) and any(
                k in block for k in ("summary", "files_touched", "tests_run", "open_questions")):
            return {
                "summary": str(block.get("summary", ""))[:2000],
                "files_touched": list(block.get("files_touched") or [])[:50],
                "tests_run": list(block.get("tests_run") or [])[:50],
                "open_questions": list(block.get("open_questions") or [])[:20],
                "raw": output[:MAX_RESULT_CHARS],
            }
    return {"summary": output[:2000], "files_touched": [],
            "tests_run": [], "open_questions": [], "raw": output[:MAX_RESULT_CHARS]}


# ---------------- worktrees & sandboxing ----------------

def setup_worktree(task: dict) -> tuple[str, str]:
    """git worktree sandbox for the task. Returns (cwd, note)."""
    repo = (task.get("worktree_repo") or "").strip()
    if not repo:
        return "", ""
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        # also accept bare repos / worktree gitfiles
        probe = subprocess.run(["git", "-C", repo, "rev-parse", "--git-dir"],
                               capture_output=True, text=True, timeout=15)
        if probe.returncode != 0:
            raise RuntimeError(f"worktree_repo is not a git repo: {repo}")
    dest = str(WORKTREES_DIR / task["id"])
    WORKTREES_DIR.mkdir(exist_ok=True)
    branch = (task.get("worktree_branch") or "").strip()
    proc = None
    if branch:
        # existing branch? attach; otherwise create it (-b)
        probe = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", branch],
                               capture_output=True, text=True, timeout=15)
        cmd = ["git", "-C", repo, "worktree", "add", dest]
        cmd += [branch] if probe.returncode == 0 else ["-b", branch]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    else:
        proc = subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", dest],
                              capture_output=True, text=True, timeout=120)
    if proc is None or proc.returncode != 0:
        err = ((proc.stderr or proc.stdout) if proc else "")[-500:]
        raise RuntimeError(f"git worktree add failed: {err}")
    return dest, f"worktree at {dest}" + (f" (branch {branch})" if branch else " (detached)")


def teardown_worktree(task: dict, cwd: str, success: bool) -> str:
    if not cwd or not cwd.startswith(str(WORKTREES_DIR)):
        return ""
    note = ""
    if success:
        # commit the work onto the branch so removing the worktree keeps it
        st = subprocess.run(["git", "-C", cwd, "status", "--porcelain"],
                            capture_output=True, text=True, timeout=30)
        if st.returncode == 0 and st.stdout.strip():
            subprocess.run(["git", "-C", cwd, "add", "-A"], capture_output=True, timeout=60)
            cm = subprocess.run(
                ["git", "-C", cwd, "-c", "user.email=opencode-bridge@local",
                 "-c", "user.name=opencode-bridge",
                 "commit", "-qm", f"task {task['id']}: {task['title']}"],
                capture_output=True, text=True, timeout=60)
            sha = subprocess.run(["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                                 capture_output=True, text=True, timeout=15)
            note = f"committed {sha.stdout.strip() or '?'} (rc={cm.returncode})"
    if success and not task.get("worktree_keep"):
        repo = (task.get("worktree_repo") or "").strip()
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", cwd],
                       capture_output=True, timeout=120)
        return f"worktree removed ({cwd})" + (f", {note}" if note else ", no changes")
    return f"worktree kept at {cwd}" + (f", {note}" if note else "")


# ---------------- task execution ----------------

def build_prompt(task: dict, dep_outputs: list[dict]) -> str:
    permission = task.get("permission") or "full"
    parts = [
        "You are the OpenCode worker fulfilling a task from Claude via the MCP bridge.",
        f"Task title: {task['title']}",
        "",
        f"Your working directory is: {task['_cwd']}",
        "You are already running inside it. Create, read, and edit files ONLY under "
        "this exact absolute path — never in any other directory.",
        "",
        f"Instructions:\n{task['instructions']}",
    ]
    if dep_outputs:
        parts.append("\nCompleted dependency results (build on these):")
        for d in dep_outputs:
            parts.append(f"\n--- [{d['id']}] {d['title']} ---\n{(d.get('result') or '')[:3000]}")
    if permission == "no-shell":
        parts.append("\nConstraint: do NOT run shell commands; read and reason only.")
    elif permission == "readonly":
        parts.append("\nConstraint: READ-ONLY analysis. Explain, summarize, answer — "
                     "do not treat file writes as part of the deliverable.")
    elif permission == "no-network":
        parts.append("\nConstraint: NO NETWORK TOOLS. Do not use WebFetch, WebSearch, "
                     "curl, or any network access; work from local context only.")
    parts.append(
        "\nDo the work. End your reply with a fenced ```json block shaped like:\n"
        '{"summary": "...", "files_touched": ["path"], "tests_run": ["..."], "open_questions": ["..."]}\n'
        "If you are BLOCKED and need Claude to decide something before you can continue, "
        "end instead with a fenced ```question block: {\"question\": \"...\"} — "
        "Claude will answer and you will be re-run with the answer."
    )
    return "\n".join(parts)


def _clean_paths(paths: list[str], workdir: str) -> list[str]:
    """Relative, deduped, no .git internals."""
    clean: list[str] = []
    for p in paths or []:
        p = (p or "").strip()
        if not p:
            continue
        if os.path.isabs(p):
            try:
                p = os.path.relpath(p, workdir)
            except ValueError:
                pass
        if p.startswith(".git/") or p == ".git" or p.startswith(".."):
            continue
        if p not in clean:
            clean.append(p)
    return clean[:50]


def _revert_touched(workdir: str, touched: list[str]) -> list[str]:
    """Undo a readonly task's writes: restore tracked files, delete new ones."""
    reverted: list[str] = []
    for rel in touched:
        abs_p = os.path.join(workdir, rel)
        try:
            probe = subprocess.run(["git", "-C", workdir, "ls-files", "--error-unmatch", rel],
                                   capture_output=True, timeout=15)
            if probe.returncode == 0:
                r = subprocess.run(["git", "-C", workdir, "checkout", "--", rel],
                                   capture_output=True, timeout=30)
                if r.returncode == 0:
                    reverted.append(rel + " (restored)")
            else:
                os.remove(abs_p)
                reverted.append(rel + " (removed)")
        except OSError:
            pass
    return reverted


def run_task(task: dict, dep_outputs: list[dict]) -> dict:
    """Execute one task. Returns outcome dict (no DB writes here)."""
    import selectors as _selectors
    tid = task["id"]
    workdir = task.get("_cwd") or str(HERE)
    model = task.get("model") or default_model()
    timeout = max(30, min(int(task.get("timeout_sec") or 600), 1800))
    permission = task.get("permission") or "full"
    # Enforcement truth table (verified by probing, Oct 2026):
    # - readonly: writes reverted after the run (true enforcement, see process_one)
    # - no-network: prompt-level only — OS-deny bricks cloud models (they need
    #   network for inference) and the background server escapes sandbox-exec.
    # - no-shell: prompt-level only (opencode run has no tool-restriction flag).
    enforced = False  # set True below only if readonly revert removes files
    cmd = [OPENCODE_BIN, "run", "--auto", "--model", model,
           build_prompt(task, dep_outputs)]
    log_path = LOGS_DIR / f"{tid}.log"
    t0 = time.time()
    with open(log_path, "a") as lf:
        lf.write(f"\n=== attempt starting {datetime.now(timezone.utc).isoformat()} "
                 f"model={model} permission={permission} ===\n")
        lf.flush()
        # placeholder written BEFORE spawn: if the worker is SIGKILLed inside
        # the spawn window the reaper still sees evidence (an untracked-orphan
        # warning) instead of an absent pidfile; overwritten with the real pid
        # immediately after Popen returns.
        (LOGS_DIR / f"{tid}.pid").write_text("spawning")
        try:
            proc = subprocess.Popen(
                cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=False, bufsize=0, start_new_session=True)
        except FileNotFoundError as e:
            return {"ok": False, "error": f"launch failed: {e}", "model": model,
                    "latency_ms": 0, "enforced": enforced}
        # pid file: if this worker is SIGKILLed, the reaper kills this pgid
        (LOGS_DIR / f"{tid}.pid").write_text(str(proc.pid))
        output_chunks: list[bytes] = []
        sel = _selectors.DefaultSelector()
        try:
            assert proc.stdout is not None
            sel.register(proc.stdout, _selectors.EVENT_READ)
            buf = b""
            killed = False
            while True:
                if proc.poll() is not None:
                    break
                if time.time() - t0 > timeout:
                    try:
                        import signal as _sig
                        os.killpg(proc.pid, _sig.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    killed = True
                    break
                # wait up to 1s for output; the loop above re-checks the deadline
                # even when the child is completely silent (blocking readline can't)
                for key, _ in sel.select(timeout=1.0):
                    try:
                        data = os.read(key.fd, 65536)
                    except OSError:
                        data = b""
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        output_chunks.append(line + b"\n")
                        lf.write((line + b"\n").decode(errors="replace"))
                lf.flush()
            # drain anything left after exit — bounded: the background opencode
            # server can inherit stdout and hold it open, so never block here
            try:
                import fcntl as _fcntl
                _flags = _fcntl.fcntl(proc.stdout.fileno(), _fcntl.F_GETFL)
                _fcntl.fcntl(proc.stdout.fileno(), _fcntl.F_SETFL, _flags | os.O_NONBLOCK)
                try:
                    while True:
                        sel2 = _selectors.DefaultSelector()
                        sel2.register(proc.stdout, _selectors.EVENT_READ)
                        ready = sel2.select(timeout=2.0)
                        sel2.close()
                        if not ready:
                            break
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        output_chunks.append(chunk)
                        lf.write(chunk.decode(errors="replace"))
                finally:
                    pass
            except (OSError, ValueError):
                pass
            try:
                rc = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    import signal as _sig
                    os.killpg(proc.pid, _sig.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                rc = proc.wait()
                killed = True
            if killed:
                lf.write(f"\n=== TIMEOUT after {timeout}s, killed ===\n")
                return {"ok": False, "error": f"task timed out after {timeout}s",
                        "model": model, "latency_ms": int((time.time() - t0) * 1000),
                        "enforced": enforced,
                        "partial": b"".join(output_chunks).decode(errors="replace")[-2000:]}
        finally:
            sel.close()
            lf.flush()
            try:
                (LOGS_DIR / f"{tid}.pid").unlink()  # child is done; no orphan to reap
            except OSError:
                pass
    latency_ms = int((time.time() - t0) * 1000)
    output = b"".join(output_chunks).decode(errors="replace").strip()
    # strip ANSI color codes opencode emits (keeps logs/structured clean)
    output = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", output)
    if rc != 0:
        detail = output[-2000:] if output else f"exit {rc} with no output"
        return {"ok": False, "error": f"opencode exited {rc}: {detail}",
                "model": model, "latency_ms": latency_ms, "enforced": enforced}
    if not output:
        return {"ok": False, "error": "opencode produced no output",
                "model": model, "latency_ms": latency_ms, "enforced": enforced}
    return {"ok": True, "output": output[:MAX_RESULT_CHARS * 2],
            "model": model, "latency_ms": latency_ms, "enforced": enforced}


def deps_ready(task: dict) -> tuple[bool, str, list[dict]]:
    dep_ids = []
    try:
        dep_ids = json.loads(task.get("depends_on") or "[]")
    except (json.JSONDecodeError, ValueError):
        return False, "depends_on is not valid JSON", []
    if not dep_ids:
        return True, "", []
    states = task_store.get_many(dep_ids)
    missing = [d for d in dep_ids if d not in states]
    if missing:
        return False, f"unknown dependency ids: {missing}", []
    bad = [d for d in dep_ids if states[d]["status"] in ("failed", "cancelled")]
    if bad:
        return False, f"dependencies failed/cancelled: {bad}", []
    waiting = [d for d in dep_ids if states[d]["status"] != "completed"]
    if waiting:
        return False, "", []  # not ready yet, stay pending (no error)
    return True, "", [{"id": d, "title": states[d]["title"],
                       "result": states[d].get("result", "")} for d in dep_ids]


def process_one(task: dict) -> None:
    tid = task["id"]
    # dependencies
    ready, err, dep_outputs = deps_ready(task)
    if err:
        task_store.complete_task(tid, error=f"dependency error: {err}", status="failed")
        log(f"{tid}: dependency error, failed: {err}")
        notify(f"OpenCode FAILED: {task['title']}", err, sound="Basso")
        return
    if not ready:
        return  # deps still running; try next pass
    # working dir (created if missing)
    workdir = task.get("working_dir") or str(HERE)
    try:
        os.makedirs(workdir, exist_ok=True)
    except OSError as e:
        task_store.complete_task(tid, error=f"could not create working_dir {workdir}: {e}", status="failed")
        return
    task["_cwd"] = workdir
    wt_note = ""
    try:
        wt_cwd, wt_note = setup_worktree(task)
        if wt_cwd:
            task["_cwd"] = wt_cwd
    except Exception as e:
        task_store.complete_task(tid, error=str(e)[-1000:], status="failed")
        log(f"{tid}: worktree setup failed: {e}")
        return
    before = _snapshot(task["_cwd"])
    attempt_no = task_store.start_attempt(tid)
    outcome = run_task(task, dep_outputs)
    usage = {"model": outcome.get("model"), "latency_ms": outcome.get("latency_ms"),
             "attempts": attempt_no,
             "permission": task.get("permission") or "full",
             "sandbox_enforced": outcome.get("enforced", False)}
    if not outcome["ok"]:
        max_retries = int(task.get("max_retries") or 0)
        if attempt_no <= max_retries:
            retry_model = (task.get("retry_model") or "").strip() or outcome.get("model", "")
            task_store.bump_attempt(tid, model=retry_model)
            log(f"{tid}: attempt {attempt_no} failed, retrying with {retry_model}: "
                f"{outcome['error'][:150]}")
            teardown_worktree(task, task["_cwd"], success=False)
            return
        task_store.complete_task(tid, error=outcome["error"], status="failed",
                                 usage={**usage, "worktree": teardown_worktree(task, task["_cwd"], success=False)})
        log(f"{tid}: FAILED {outcome['error'][:200]}")
        notify(f"OpenCode FAILED: {task['title']}", outcome["error"], sound="Basso")
        return
    output = outcome["output"]
    # mid-task question for Claude?
    questions = _extract_fenced(output, "question")
    if questions and isinstance(questions[-1], dict) and questions[-1].get("question"):
        q = str(questions[-1]["question"])[:2000]
        task_store.set_waiting(tid, q)
        teardown_worktree(task, task["_cwd"], success=False)
        log(f"{tid}: asked Claude a question, waiting")
        notify(f"OpenCode needs input: {task['title']}", q)
        return
    structured = parse_structured(output)
    touched, stat = _diff_summary(task["_cwd"], before)
    structured["files_touched"] = _clean_paths(
        (structured.get("files_touched") or []) + touched, task["_cwd"])
    if stat:
        structured["diff_stat"] = stat
    reverted: list[str] = []
    enforced = False
    if (task.get("permission") or "full") == "readonly" and touched:
        reverted = _revert_touched(task["_cwd"], touched)
        structured["reverted"] = reverted
        enforced = bool(reverted)  # True only if the mechanism actually fired
    elif (task.get("permission") or "full") == "readonly":
        structured["reverted"] = []
    usage["sandbox_enforced"] = enforced  # honest: True only if revert fired
    wt_done = teardown_worktree(task, task["_cwd"], success=True)
    result = output[:MAX_RESULT_CHARS]
    if wt_note or wt_done:
        result += f"\n\n[{wt_note}; {wt_done}]"
    task_store.complete_task(tid, result=result, structured=structured,
                             usage={**usage, "worktree": wt_done or wt_note})
    log(f"{tid}: completed ({len(result)} chars, {len(structured.get('files_touched', []))} files)")
    notify(f"OpenCode done: {task['title']}", structured.get("summary") or result)


def acquire_lock():
    """Single-instance guard: launchd pass + manual pass must never overlap
    (two claimers of the same task -> one finalize loses the race and drops
    usage/structured). Returns an open fd, or None if another pass holds it."""
    import fcntl
    lock_path = HERE / ".worker.lock"
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        return None
    fd.write(str(os.getpid()))
    fd.flush()
    return fd


def main() -> int:
    lock_fd = acquire_lock()
    if lock_fd is None:
        # another worker pass is mid-run; skip this tick (evidence for audit)
        log("pass skipped: another worker pass holds the lock")
        return 0
    try:
        requeue_stale_running()
        pending = task_store.list_tasks("pending", MAX_TASKS_PER_PASS * 3)
    except Exception as e:
        log(f"queue read failed: {e}")
        heartbeat()
        return 1
    pending = [t for t in pending if t.get("created_by") == "claude"]
    pending.sort(key=lambda t: (-int(t.get("priority") or 0), t.get("created_at") or ""))
    claimed = 0
    heartbeat(0)
    for task in pending:
        if claimed >= MAX_TASKS_PER_PASS:
            break
        tid = task["id"]
        try:
            task_store.claim_task(tid, worker="opencode-auto")
        except Exception as e:
            log(f"{tid}: claim failed ({e}), skipping")
            continue
        claimed += 1
        log(f"{tid}: claimed '{task['title']}' (priority {task.get('priority') or 0})")
        heartbeat(claimed, current_task=tid)
        try:
            process_one(task_store.get_task(tid))
        except Exception:
            err = traceback.format_exc()[-2000:]
            try:
                task_store.complete_task(tid, error=err, status="failed")
            except Exception as e2:
                log(f"{tid}: write-back failed: {e2}")
            log(f"{tid}: worker crashed: {err[:200]}")
        heartbeat(claimed)
    heartbeat(claimed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
