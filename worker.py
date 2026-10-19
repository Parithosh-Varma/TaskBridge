#!/usr/bin/env python3
"""Auto-worker: poll the Claude task queue and execute pending tasks headlessly.

Designed for launchd (one pass per invocation, exits when queue is empty):
  ./worker.py   (every 60s via com.taskbridge.worker)

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
import hashlib
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


def _resolve_opencode_bin() -> str:
    """Absolute opencode path. Bare 'opencode' relies on PATH, which launchd
    does not provide (default /usr/bin:/bin) — worker then fails with
    'No such file or directory'. Prefer env, then PATH, then the standard
    install location ~/.opencode/bin/opencode."""
    import shutil as _shutil
    env = (os.environ.get("OPENCODE_BIN") or "").strip()
    if env:
        return env
    which = _shutil.which("opencode")
    if which:
        return which
    fallback = Path.home() / ".opencode" / "bin" / "opencode"
    if fallback.exists():
        return str(fallback)
    return "opencode"


OPENCODE_BIN = _resolve_opencode_bin()
_HELP_CACHE: dict[str, str | None] = {}

# Flags the worker would LIKE on `opencode run`, added only when the installed
# binary advertises them. Never pass an optional flag blindly: unknown flags
# make some builds dump help and exit 1 before the model is ever reached, so
# an unrecognized/unprobeable variant must simply run without them.
OPTIONAL_RUN_FLAGS = ("--standalone",)


def _run_help(bin_path: str) -> str | None:
    """`opencode run` help text (stdout+stderr) for this binary, or None.

    Cached per binary path. `--help` then `-h` because builds disagree which
    one they answer; unreadable/empty help returns None and callers treat all
    optional flags as unsupported rather than guessing."""
    if bin_path in _HELP_CACHE:
        return _HELP_CACHE[bin_path]
    blob = None
    for help_flag in ("--help", "-h"):
        try:
            proc = subprocess.run(
                [bin_path, "run", help_flag], capture_output=True, text=True,
                timeout=20)
        except Exception:
            continue
        text = (proc.stdout or "") + (proc.stderr or "")
        if text.strip():
            blob = text
            break
    _HELP_CACHE[bin_path] = blob
    return blob


def supported_run_flags(bin_path: str | None = None) -> list[str]:
    """Subset of OPTIONAL_RUN_FLAGS this binary's help advertises.

    Version-agnostic by construction: the binary is asked, not a version
    table. Help that can't be read means "none" — a run without optional
    flags works on every variant, it just loses the extra behavior."""
    bin_path = bin_path or OPENCODE_BIN
    help_text = _run_help(bin_path)
    if not help_text:
        return []
    return [flag for flag in OPTIONAL_RUN_FLAGS if flag in help_text]


# A CLI that rejects an unknown flag prints its usage/help and exits nonzero
# within seconds, before touching the model. Match the FIRST meaningful line
# (dumps start with it; model output rarely does, and never with rc != 0 on a
# task that did work) so a late real failure is never retried into a double-run.
_ARGV_DUMP_HEADS = ("opencode run [", "Usage:", "usage:", "Options:")
ARGV_REJECT_MAX_SEC = 60


def _looks_like_argv_reject(output: str, elapsed_sec: float) -> bool:
    if elapsed_sec > ARGV_REJECT_MAX_SEC:
        return False
    for line in output.splitlines():
        head = line.strip()
        if not head:
            continue
        return head.startswith(_ARGV_DUMP_HEADS)
    return False


WORKER_VERSION = "2.0.0"
# Free model that works without paid credits; override with WORKER_MODEL env.
# Re-check with `opencode models` when free tiers rotate — retired ids make
# `opencode run` fail with "Model unavailable".
WORKER_MODEL = os.environ.get("WORKER_MODEL", "opencode/deepseek-v4.1-flash-free")
# Ordered spares used ONLY when the requested/default model is retired or
# refuses at runtime ("Model unavailable") — a dead id must not wedge the
# queue. All free-tier, so a retirement never silently starts billing.
FALLBACK_MODELS = (
    "opencode/deepseek-v4.1-flash-free",
    "opencode/glm-5.3-flash-free",
    "opencode/mimo-v2.6-flash-free",
    "opencode/nemotron-3.5-lightning-free",
)
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


_hb_state = {"claimed": 0, "current_task": ""}
HB_TICK_SEC = 30  # run_task refreshes liveness at this cadence so a long task
                  # never looks dead (heartbeat staleness is 180s elsewhere)


def heartbeat(claimed: int | None = None, current_task: str | None = None) -> None:
    """Write heartbeat.json.

    Args default to the current pass state, so the long-task loop can keep
    liveness fresh mid-run with a bare heartbeat()."""
    if claimed is None:
        claimed = _hb_state["claimed"]
    else:
        _hb_state["claimed"] = claimed
    if current_task is None:
        current_task = _hb_state["current_task"]
    else:
        _hb_state["current_task"] = current_task
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


def _orphan_looks_like_ours(pid: int, tid: str) -> tuple[bool, str]:
    """Pid-reuse guard: only trust the pidfile if pid still leads its own
    process group (start_new_session made pgid == pid) AND its argv carries
    our --title marker for THIS task (ps-visible, travels with the process,
    unforgeable by pid reuse). Anything else -> do not kill."""
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
    if f"{TITLE_PREFIX}{tid}-" not in cmd:
        return False, f"no title marker for {tid}: {cmd[:80]!r}"
    return True, cmd[:80]


# argv marker: --title br-<repo-tag>-<tid>-a<n>. The repo tag namespaces the
# marker to THIS checkout so a worker in one clone never mistakes another
# clone's processes for its own strays (both share the host process table).
REPO_TAG = hashlib.sha1(str(HERE.resolve()).encode("utf-8")).hexdigest()[:8]
TITLE_PREFIX = f"br-{REPO_TAG}-"
# --title is ps-visible and (unlike --session) works with the opencode free
# tier: any explicit --session makes `opencode run` reject free models with
# "free tier can only be used from within OpenCode" (probed Oct 2026).
# Ps-visible, travels with the process, unforgeable by pid reuse.
TREE_KILL_ROUNDS = 4
TREE_KILL_MAX = 300  # refuse bigger trees: a matching bug must never mass-kill


def _ps_snapshot() -> list[tuple[int, int, str]]:
    """One snapshot: (pid, ppid, command). NOTE: macOS `ps sess=` returns 0
    for every process and `ps -E` exposes no env, so session matching and
    env tagging are both impossible here (probed Oct 2026) — ppid walk plus
    the argv marker below are the entire toolkit."""
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,command="],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    rows = []
    for line in (out.stdout or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
        except ValueError:
            pass
    return rows


def _title_marker(tid: str, attempt: int) -> str:
    return f"{TITLE_PREFIX}{tid}-a{attempt}"


def _task_tree_pids(root_pid: int) -> list[int]:
    """Live ppid-descendants of root. ppid-only by necessity (see _snapshot).
    Children in their own pgids are still found (pgid != ppid); only
    reparented-to-1 or setsid grandchildren escape — the sweep covers tagged
    roots, and the residual is documented, not fuzz-matched."""
    procs = _ps_snapshot()
    children: dict[int, list[int]] = {}
    for pid, ppid, _cmd in procs:
        children.setdefault(ppid, []).append(pid)
    found: set[int] = set()
    stack = [root_pid]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in found:
                found.add(c)
                stack.append(c)
    found.discard(root_pid)
    return sorted(found)


def _descendant_pids(root_pid: int) -> list[int]:
    """Compatibility wrapper (tests/tools); ppid-walk via _task_tree_pids."""
    return _task_tree_pids(root_pid)


def _kill_tree(root_pid: int) -> tuple[int, bool]:
    """Kill root's process group, then loop walk-and-kill until the tree is
    empty (closes the fork-between-walk-and-kill race). Bounded rounds, plus
    a hard cap: trees over TREE_KILL_MAX are refused outright, so a matching
    bug can never become a mass-kill. Only kills pids present in a fresh
    snapshot of the tree, so pid reuse can't redirect a kill (a reused pid
    inside the walk is our fork). Returns (kills, clean)."""
    import signal as _sig
    import time as _time
    kills = 0
    try:
        os.killpg(root_pid, _sig.SIGKILL)  # leader first: it can't fork anymore
    except (ProcessLookupError, PermissionError, OSError):
        pass
    for _ in range(TREE_KILL_ROUNDS):
        tree = _task_tree_pids(root_pid)
        if not tree:
            break
        if len(tree) > TREE_KILL_MAX:
            return kills, False  # refuse: matching bug, never mass-kill
        for p in tree:
            try:
                os.kill(p, _sig.SIGKILL)
                kills += 1
            except (ProcessLookupError, PermissionError, OSError):
                pass
        _time.sleep(0.2)
    clean = not _task_tree_pids(root_pid)
    return kills, clean


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
    ok, why = _orphan_looks_like_ours(pid, task_id)
    if ok:
        tree_n, clean = _kill_tree(pid)
        log(f"{task_id}: killed orphaned worker child pgid {pid} "
            f"(+{tree_n} tree kills, clean={clean})")
    else:
        log(f"{task_id}: orphan kill SKIPPED (pidfile={pid}): {why}")
    try:
        pid_path.unlink()
    except OSError:
        pass


def _sweep_tagged_strays() -> int:
    """Backstop (each pass, after the reaper): find CLI children carrying our
    --title argv marker whose task is NOT running, and kill their trees.
    The marker is set solely by run_task, so user processes are never touched;
    and it travels with the process, so pid reuse can't misdirect the sweep
    (re-validated per pid right before killing). Catches what the pidfile
    path misses: spawn-window orphans and anything the reaper skipped. Tasks
    still marked running are the reaper's jurisdiction — left alone."""
    import re as _re
    procs = _ps_snapshot()
    if not procs:
        return 0
    pat = _re.compile(rf"{_re.escape(TITLE_PREFIX)}([0-9a-f]{{12}})-a\d+")
    by_task: dict[str, list[int]] = {}
    for pid, _ppid, cmd in procs:
        m = pat.search(cmd)
        if m:
            by_task.setdefault(m.group(1), []).append(pid)
    if not by_task:
        return 0
    swept = 0
    for tid, pids in by_task.items():
        try:
            status = task_store.get_task(tid)["status"]
        except KeyError:
            # Not in THIS checkout's queue: almost certainly another
            # TaskBridge instance on the same host. Never kill what we don't
            # own — this was the cross-clone false-positive that SIGKILLed
            # live tasks. Genuinely deleted-task orphans are the pidfile
            # reaper's jurisdiction while the row still exists.
            log(f"{tid}: stray sweep skipped — task not in this queue")
            continue
        if status == "running":
            continue
        fresh: list[int] = []  # re-validate marker per pid (pid-reuse safety)
        for p in pids:
            try:
                chk = subprocess.run(["ps", "-o", "command=", "-p", str(p)],
                                     capture_output=True, text=True, timeout=10)
                if chk.returncode == 0 and f"{TITLE_PREFIX}{tid}-" in (chk.stdout or ""):
                    fresh.append(p)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not fresh:
            continue
        total, clean = 0, True
        for root in fresh:
            n, c = _kill_tree(root)
            total += n
            clean = clean and c
        log(f"{tid}: stray sweep killed {total} tagged process(es) "
            f"(task {status}, clean={clean})")
        swept += 1
    return swept


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


def all_opencode_models() -> list[str]:
    """Every model `opencode models` reports — uncapped, deduped, CLI order.

    The CLI reports 600+ models; use this when the whole list matters
    (validation), and list_available_models() for API payloads.
    """
    try:
        proc = subprocess.run(
            [OPENCODE_BIN, "models"], capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise RuntimeError(f"could not list opencode models: {e}")
    if proc.returncode != 0:
        raise RuntimeError(f"`opencode models` failed: {(proc.stderr or '')[-300:]}")
    seen: set[str] = set()
    out: list[str] = []
    for ln in (proc.stdout or "").splitlines():
        m = ln.strip()
        if "/" in m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def set_default_model(model: str) -> str:
    """Persist a new worker default model (validated against opencode models)."""
    model = (model or "").strip()
    if not model:
        raise ValueError("model is required, e.g. 'opencode/deepseek-v4.1-flash-free'")
    available = all_opencode_models()
    if model not in available:
        close = [m for m in available if model.lower() in m.lower()][:5]
        raise ValueError(f"unknown model '{model}'. Did you mean one of: {close or available[:5]}?")
    CONFIG_PATH.write_text(json.dumps({"default_model": model}, indent=2))
    return model


def list_available_models(search: str = "", limit: int = 100) -> list[str]:
    """All models opencode can run. Optional case-insensitive filter."""
    models = all_opencode_models()
    if search:
        models = [m for m in models if search.lower() in m.lower()]
    return models[:max(1, min(limit, 200))]


# ---------------- model resilience ----------------
# A retired model id must never take the queue down: pins and the configured
# default are checked against `opencode models` and rerouted to a runnable
# candidate. When the list itself can't be read, requests pass through
# unchanged — we never guess a replacement.

_MODEL_CACHE: dict = {"ts": 0.0, "models": frozenset()}
_MODEL_CACHE_TTL_SEC = 300
_MODEL_NOTIFIED: set = set()


def _valid_models() -> set[str] | None:
    """Model ids `opencode models` reports, cached per 300s.

    Returns None when the list can't be read — callers must then honor the
    request unchanged instead of rerouting."""
    now = time.time()
    if _MODEL_CACHE["models"] and now - _MODEL_CACHE["ts"] <= _MODEL_CACHE_TTL_SEC:
        return set(_MODEL_CACHE["models"])
    try:
        models = frozenset(all_opencode_models())
    except RuntimeError as e:
        log(f"model list unavailable ({e}) — retirement checks skipped")
        return None
    if not models:
        return None
    _MODEL_CACHE["models"], _MODEL_CACHE["ts"] = models, now
    return set(models)


def _model_candidates(requested: str = "") -> list[str]:
    """Preferred run order: task's own model, configured default, builtin,
    then the free spares. Deduped, order preserved."""
    out: list[str] = []
    for m in ((requested or "").strip(), default_model(), WORKER_MODEL,
              *FALLBACK_MODELS):
        if m and m not in out:
            out.append(m)
    return out


def resolve_model(requested: str = "") -> tuple[str, str]:
    """Pick a model opencode can actually run. Returns (model, note).

    A retired id is skipped in favor of the next runnable candidate; the note
    names the swap ("" when nothing was swapped)."""
    first = (requested or "").strip() or default_model()
    valid = _valid_models()
    if valid is None:
        return first, ""
    for m in _model_candidates(requested):
        if m in valid:
            if m == first:
                return m, ""
            return m, f"model {first!r} is retired/unavailable — using {m}"
    return first, ""


def next_fallback_model(after: str) -> str:
    """First runnable candidate that is NOT the model that just failed.

    Used after a runtime "Model unavailable": every reroute moves to a
    strictly different model, so rerun chains are bounded and cannot loop.
    """
    valid = _valid_models()
    for m in _model_candidates(""):
        if m == after:
            continue
        if valid is None or m in valid:
            return m
    return ""


def _looks_like_model_fault(output: str) -> bool:
    """opencode refuses retired/unknown ids with 'Model unavailable: <id>'."""
    return "Model unavailable" in (output or "")


def _notify_model_reroute(dead: str, replacement: str) -> None:
    """Tell the human once per (dead -> replacement) pair per worker pass."""
    key = (dead, replacement)
    if key in _MODEL_NOTIFIED:
        return
    _MODEL_NOTIFIED.add(key)
    notify("TaskBridge: model switched",
           f"{dead} is unavailable — running on {replacement} instead. "
           f"Pick a new default on the dispatch board.", sound="Basso")


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
                ["git", "-C", cwd, "-c", "user.email=taskbridge@local",
                 "-c", "user.name=taskbridge",
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


def _run_cli_attempt(cmd: list[str], workdir: str, log_path: Path, tid: str,
                     timeout: int, header: str) -> dict:
    """Spawn one `opencode run` attempt, stream it into the task log, enforce
    the timeout, and manage the pidfile (placeholder -> real pid -> cleanup).

    Returns {rc, output, killed, launch_error}; success/failure verdicts stay
    in run_task, which may retry the attempt with different argv."""
    import selectors as _selectors
    t0 = time.time()
    output_chunks: list[bytes] = []
    killed = False
    with open(log_path, "a") as lf:
        lf.write(header)
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
            return {"rc": None, "output": "", "killed": False, "launch_error": str(e)}
        # pid file: if this worker is SIGKILLed, the reaper kills this pgid
        (LOGS_DIR / f"{tid}.pid").write_text(str(proc.pid))
        sel = _selectors.DefaultSelector()
        try:
            assert proc.stdout is not None
            sel.register(proc.stdout, _selectors.EVENT_READ)
            buf = b""
            hb_next = t0 + HB_TICK_SEC
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
                if time.time() >= hb_next:
                    # keep liveness fresh mid-task: without this a long task
                    # (up to 30 min) looks like a dead worker to the board
                    heartbeat()
                    hb_next = time.time() + HB_TICK_SEC
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
        finally:
            sel.close()
            lf.flush()
            try:
                (LOGS_DIR / f"{tid}.pid").unlink()  # child is done; no orphan to reap
            except OSError:
                pass
    return {"rc": rc, "output": b"".join(output_chunks).decode(errors="replace"),
            "killed": killed, "launch_error": None}


def run_task(task: dict, dep_outputs: list[dict], attempt_no: int = 0) -> dict:
    """Execute one task. Returns outcome dict (no DB writes here)."""
    tid = task["id"]
    workdir = task.get("_cwd") or str(HERE)
    pinned = (task.get("model") or "").strip()
    if pinned and not task_store._MODEL_ID.fullmatch(pinned):
        # argv safety: a model string that could pass CLI flags is not a model
        print(f"task {tid}: invalid model {pinned!r} — falling back to worker default", flush=True)
        pinned = ""
    model, model_note = resolve_model(pinned)
    if model_note:
        log(f"{tid}: {model_note}")
        _notify_model_reroute(pinned or default_model(), model)
    timeout = max(30, min(int(task.get("timeout_sec") or 600), 1800))
    permission = task.get("permission") or "full"
    # Enforcement truth table (verified by probing, Oct 2026):
    # - readonly: writes reverted after the run (true enforcement, see process_one)
    # - no-network: prompt-level only — OS-deny bricks cloud models (they need
    #   network for inference) and the background server escapes sandbox-exec.
    # - no-shell: prompt-level only (opencode run has no tool-restriction flag).
    enforced = False  # set True below only if readonly revert removes files
    # --standalone: keeps the whole process tree under our CLI child, so the
    # reaper can enumerate and kill descendants. Plain mode spawns shell-tool
    # children under the shared `opencode-cli serve --service` daemon in their
    # own pgids — invisible to us and unkillable by task (probed Oct 2026).
    # It (and any future optional flag) is added only when THIS binary's help
    # advertises it, and stripped by a retry if the variant rejects it anyway:
    # no version tables, no blind flags — every build runs.
    # --title: argv marker (br-<tid>-a<n>) identifying OUR CLI child in ps
    # output — the reaper/sweep match on it, so pid reuse can't misdirect a
    # kill. Per-attempt (no session bleed across retries). NOTE: --session
    # cannot be used here: it makes free-tier models refuse to run.
    optional_flags = supported_run_flags()
    log_path = LOGS_DIR / f"{tid}.log"
    t0 = time.time()
    while True:
        cmd = [OPENCODE_BIN, "run", *optional_flags,
               "--title", _title_marker(tid, attempt_no),
               "--auto", "--model", model,
               build_prompt(task, dep_outputs)]
        attempt = _run_cli_attempt(
            cmd, workdir, log_path, tid, timeout,
            f"\n=== attempt starting {datetime.now(timezone.utc).isoformat()} "
            f"model={model} permission={permission} ===\n")
        if attempt["launch_error"] is not None:
            return {"ok": False, "error": f"launch failed: {attempt['launch_error']}",
                    "model": model, "latency_ms": int((time.time() - t0) * 1000),
                    "enforced": enforced}
        rc = attempt["rc"]
        # strip ANSI color codes opencode emits (keeps logs/structured clean)
        output = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", attempt["output"]).strip()
        if attempt["killed"]:
            return {"ok": False, "error": f"task timed out after {timeout}s",
                    "model": model, "latency_ms": int((time.time() - t0) * 1000),
                    "enforced": enforced, "partial": output[-2000:]}
        if (optional_flags and rc != 0
                and _looks_like_argv_reject(output, time.time() - t0)):
            # this variant rejects an optional flag despite advertising it (or
            # its help couldn't be read): drop them and retry ONCE, so an
            # unknown build degrades gracefully instead of failing the task
            log(f"{tid}: opencode rejected {' '.join(optional_flags)} "
                f"(exit {rc}, help dump); retrying without optional flags")
            with open(log_path, "a") as lf:
                lf.write(f"\n=== retrying without {' '.join(optional_flags)} "
                         f"(exit {rc}, help dump) ===\n")
            optional_flags = []
            continue
        break
    latency_ms = int((time.time() - t0) * 1000)
    if rc != 0:
        detail = output[-2000:] if output else f"exit {rc} with no output"
        outcome = {"ok": False, "error": f"opencode exited {rc}: {detail}",
                   "model": model, "latency_ms": latency_ms, "enforced": enforced}
        if _looks_like_model_fault(output):
            # infrastructure fault, not a task fault — process_one reroutes
            # to another model without spending the task's retry budget
            outcome["model_fault"] = True
        return outcome
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
    outcome = run_task(task, dep_outputs, attempt_no)
    usage = {"model": outcome.get("model"), "latency_ms": outcome.get("latency_ms"),
             "attempts": attempt_no,
             "permission": task.get("permission") or "full",
             "sandbox_enforced": outcome.get("enforced", False)}
    pinned_for_usage = (task.get("model") or "").strip()
    if pinned_for_usage and pinned_for_usage != (outcome.get("model") or ""):
        usage["model_rerouted_from"] = pinned_for_usage  # retired pin, see resolve_model
    if not outcome["ok"]:
        if outcome.get("model_fault"):
            reroute_to = next_fallback_model(outcome.get("model") or "")
            if reroute_to:
                task_store.bump_attempt(tid, model=reroute_to)
                try:
                    task_store.rollback_attempt(tid)  # infra fault, not a task attempt
                except KeyError:
                    pass
                log(f"{tid}: model {outcome.get('model')!r} unavailable — rerouting "
                    f"to {reroute_to} (no task retry used)")
                _notify_model_reroute(outcome.get("model") or "?", reroute_to)
                teardown_worktree(task, task["_cwd"], success=False)
                return
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
    except Exception as e:
        # helpers must NEVER brick the pass (a sweep crash once took down
        # every pass with rc=1): log loudly, keep processing
        log(f"reaper failed (non-fatal, investigate): {e}")
    try:
        _sweep_tagged_strays()
    except Exception as e:
        log(f"sweep failed (non-fatal, investigate): {e}")
    try:
        pending = task_store.list_tasks("pending", MAX_TASKS_PER_PASS * 3)
    except Exception as e:
        log(f"queue read failed: {e}")
        heartbeat()
        return 1
    pending = [t for t in pending if t.get("created_by") in ("claude", "chatgpt")]
    pending.sort(key=lambda t: (-int(t.get("priority") or 0), t.get("created_at") or ""))
    claimed = 0
    heartbeat(0, current_task="")
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
        heartbeat(claimed, current_task="")
    heartbeat(claimed, current_task="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
