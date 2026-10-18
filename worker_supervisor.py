#!/usr/bin/env python3
"""Independent supervisor/restart control for the TaskBridge worker (launchd).

Why this file exists separately from ``worker.py``: the MCP server must be able
to bring the worker back even when the worker process is dead, wedged, or was
never started. This module therefore imports **nothing** from ``worker.py`` (a
syntax error or a missing dependency in the worker must not take the restart
path down with it), and it never needs the worker to be alive to do its job.
It shells out only to ``/bin/launchctl`` with fixed argv arrays built from
validated values — never through a shell, and never with caller-supplied
commands.

Supervision model (macOS): the worker runs one pass per launchd invocation
(``StartInterval 60``), installed as a user LaunchAgent. The service label is
*discovered* from the installed configuration — never invented:

1. ``TASKBRIDGE_SERVICE_LABEL`` env override (validated identifier), else
2. a scan of ``~/Library/LaunchAgents/*.plist`` for the job whose
   ``ProgramArguments`` point at this checkout's ``worker.py``, else
3. the conventional ``com.taskbridge.worker`` label if that plist exists.

If no LaunchAgent is installed at all the tool returns an explicit
``service_missing`` result with install instructions — it never pretends a
privileged capability exists, and it never falls back to killing PIDs.

Restart policy
--------------
- healthy  + ``force=false`` → skipped; a healthy worker is never interrupted.
- stale/offline             → controlled restart via the configured supervisor.
- healthy  + ``force=true`` → intentional restart, flagged as possibly
  interrupting, with the safest shutdown first (SIGTERM via ``kickstart -k``
  after a bounded grace period for the running pass).
- A queue that is *demonstrably* not being processed (fresh heartbeat,
  eligible work older than the last pass, nothing claimed) counts as
  unhealthy and is restarted — this is the "worker alive but stuck" case.

Every attempt is serialized with an ``flock`` (concurrent restart requests
never trigger two restarts) and rate-limited by a persisted cooldown that
escalates while attempts keep failing, so a broken worker cannot be
kickstarted in a loop.

Verification is evidence-based: launchctl exit code 0 proves nothing by itself.
Success requires a heartbeat *newer than the restart attempt* (plus claimed
work when the queue shows any). Task records are never touched by this module —
it only reads the queue, so queued work survives any restart outcome.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULT_SERVICE_LABEL = "com.taskbridge.worker"
DEFAULT_LAUNCHCTL = "/bin/launchctl"
DEFAULT_COOLDOWN_SEC = 90
DEFAULT_TIMEOUT_SEC = 90
DEFAULT_MAX_STALE_SEC = 180
DEFAULT_GRACE_SEC = 20
LAUNCHCTL_TIMEOUT_SEC = 30
STATE_HISTORY = 5
# Process-backend (non-launchd) loop: one worker pass per interval, well under
# the 180s staleness threshold so the dashboard engine lamp stays green.
DEFAULT_LOOP_INTERVAL_SEC = 60
# An eligible task must predate the last pass by at least this much before the
# queue counts as "demonstrably stalled" (>2 launchd passes).
STALL_MIN_AGE_SEC = 120

# LaunchAgent labels are reverse-DNS identifiers; keep them to that alphabet so
# nothing label-shaped can smuggle whitespace/options into launchctl's argv.
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DOMAIN_RE = re.compile(r"^(?:gui|user)/\d+$")
# Redact obvious secret-shaped log content before it can reach an MCP client.
_SECRET_RE = re.compile(
    r"(?i)(token|secret|api[_-]?key|password|passwd|bearer|authorization|"
    r"anthropic|openai|sk-[A-Za-z0-9])")
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{24,}\b")


def _clamp(value, low: int, high: int, fallback: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(n, high))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid currently exists."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _age_sec(value) -> int | None:
    ts = _parse_ts(value)
    if ts is None:
        return None
    return int((datetime.now(timezone.utc) - ts).total_seconds())


def _tail(text: str, limit: int = 300) -> str:
    return (text or "").strip()[-limit:]


def _redact(line: str, limit: int = 200) -> str | None:
    """One log line, secret-free and bounded — or None if it smells like a secret."""
    line = (line or "").rstrip()
    if not line:
        return None
    if _SECRET_RE.search(line):
        return None
    line = _LONG_HEX_RE.sub("<redacted>", line)
    return line[:limit]


class Supervisor:
    """Restart controller for the launchd-supervised TaskBridge worker.

    All external effects go through ``self.runner`` (subprocess.run by default)
    and all mutable state lives in files under ``repo_dir`` so unit tests can
    swap the runner, the clock, the sleep function and every path.
    """

    def __init__(
        self,
        repo_dir: str | Path | None = None,
        label: str | None = None,
        plist_path: str | Path | None = None,
        launch_agents_dir: str | Path | None = None,
        launchctl: str | None = None,
        uid: int | None = None,
        heartbeat_path: str | Path | None = None,
        worker_lock_path: str | Path | None = None,
        restart_lock_path: str | Path | None = None,
        state_path: str | Path | None = None,
        restart_log_path: str | Path | None = None,
        worker_log_path: str | Path | None = None,
        daemon_pid_path: str | Path | None = None,
        daemon_log_path: str | Path | None = None,
        queue_snapshot=None,
        runner=None,
        spawner=None,
        clock=time.time,
        sleeper=time.sleep,
        cooldown_sec: int | None = None,
        timeout_sec: int | None = None,
        max_stale_sec: int | None = None,
        grace_sec: int | None = None,
        loop_interval_sec: int | None = None,
    ):
        self.repo_dir = Path(repo_dir).resolve() if repo_dir else HERE
        self._label_override = label or ""
        self._plist_override = Path(plist_path).expanduser() if plist_path else None
        self.launch_agents_dir = (
            Path(launch_agents_dir).expanduser()
            if launch_agents_dir
            else Path.home() / "Library" / "LaunchAgents"
        )
        # Remember whether the caller pinned launchctl explicitly: an explicit
        # (but unusable) path keeps the launchd error path, while a plain POSIX
        # host with no launchctl falls back to the process backend.
        self._launchctl_override = str(
            launchctl or os.environ.get("TASKBRIDGE_LAUNCHCTL") or "")
        self.launchctl = self._launchctl_override or DEFAULT_LAUNCHCTL
        self.uid = int(uid if uid is not None else os.getuid())
        self.heartbeat_path = Path(
            heartbeat_path or os.environ.get("TASKBRIDGE_HEARTBEAT_PATH")
            or self.repo_dir / "heartbeat.json"
        )
        self.worker_lock_path = Path(
            worker_lock_path or self.repo_dir / ".worker.lock"
        )
        self.restart_lock_path = Path(
            restart_lock_path or os.environ.get("TASKBRIDGE_RESTART_LOCK_PATH")
            or self.repo_dir / ".restart.lock"
        )
        self.state_path = Path(
            state_path or os.environ.get("TASKBRIDGE_RESTART_STATE_PATH")
            or self.repo_dir / ".restart_state.json"
        )
        self.restart_log_path = Path(
            restart_log_path or os.environ.get("TASKBRIDGE_RESTART_LOG_PATH")
            or self.repo_dir / "restart.log"
        )
        self.worker_log_path = Path(
            worker_log_path or self.repo_dir / "worker.launchd.log"
        )
        self.daemon_pid_path = Path(
            daemon_pid_path or os.environ.get("TASKBRIDGE_DAEMON_PID_PATH")
            or self.repo_dir / ".worker_daemon.pid"
        )
        self.daemon_log_path = Path(
            daemon_log_path or self.repo_dir / "worker.launchd.log"
        )
        self.runner = runner or subprocess.run
        self.spawner = spawner or subprocess.Popen
        self.clock = clock
        self.sleeper = sleeper
        self.loop_interval_sec = _clamp(
            loop_interval_sec if loop_interval_sec is not None
            else os.environ.get("TASKBRIDGE_LOOP_INTERVAL_SEC"),
            5, 3600, DEFAULT_LOOP_INTERVAL_SEC)
        self.cooldown_sec = _clamp(
            cooldown_sec if cooldown_sec is not None
            else os.environ.get("TASKBRIDGE_RESTART_COOLDOWN_SEC"),
            5, 86400, DEFAULT_COOLDOWN_SEC)
        self.timeout_sec = _clamp(
            timeout_sec if timeout_sec is not None
            else os.environ.get("TASKBRIDGE_RESTART_TIMEOUT_SEC"),
            10, 600, DEFAULT_TIMEOUT_SEC)
        self.max_stale_sec = _clamp(
            max_stale_sec, 30, 3600, DEFAULT_MAX_STALE_SEC)
        self.grace_sec = _clamp(
            grace_sec if grace_sec is not None
            else os.environ.get("TASKBRIDGE_RESTART_GRACE_SEC"),
            0, 300, DEFAULT_GRACE_SEC)
        self._queue_snapshot = queue_snapshot or _default_queue_snapshot
        self._service_cache: dict | None = None
        self._domain_cache: str | None = None

    # ------------------------------------------------------------------ paths

    def candidate_label(self) -> str:
        """Configured label: env override, else the conventional default."""
        env = (self._label_override
               or os.environ.get("TASKBRIDGE_SERVICE_LABEL")
               or "").strip()
        if env and _LABEL_RE.fullmatch(env):
            return env
        return DEFAULT_SERVICE_LABEL

    def plist_path(self, label: str) -> Path:
        if self._plist_override is not None:
            return self._plist_override
        env = os.environ.get("TASKBRIDGE_SERVICE_PLIST")
        if env:
            return Path(env).expanduser()
        return self.launch_agents_dir / f"{label}.plist"

    def domain(self) -> str:
        """launchd domain for a user LaunchAgent: gui/<uid>, else user/<uid>."""
        if self._domain_cache:
            return self._domain_cache
        for candidate in (f"gui/{self.uid}", f"user/{self.uid}"):
            out = self._launchctl(["print", candidate])
            if out["ok"]:
                self._domain_cache = candidate
                return candidate
            if out["error"] and out["rc"] is None:
                # launchctl itself missing/not executable — no domain will work
                break
        fallback = f"gui/{self.uid}"
        self._domain_cache = fallback
        return fallback

    def backend(self) -> str:
        """Which supervisor this host uses: ``launchd`` | ``process`` | ``unavailable``.

        ``launchd`` when a usable launchctl is configured (macOS), ``process``
        for a detached worker loop on other POSIX hosts. A caller that pins an
        explicit launchctl path keeps the launchd code path so misconfiguration
        is reported as such instead of silently switching backends.
        """
        forced = (os.environ.get("TASKBRIDGE_SUPERVISOR_BACKEND") or "").strip().lower()
        if forced in ("launchd", "process", "unavailable"):
            return forced
        if os.path.isabs(self.launchctl) and os.access(self.launchctl, os.X_OK):
            return "launchd"
        if self._launchctl_override:
            return "launchd"
        if os.name == "posix":
            return "process"
        return "unavailable"

    # ----------------------------------------------------- process backend

    def _daemon_pid(self) -> int | None:
        try:
            pid = int(self.daemon_pid_path.read_text().strip())
        except (OSError, ValueError):
            return None
        return pid if pid > 0 else None

    def daemon_alive(self) -> bool:
        """True while the detached process-loop supervisor is running."""
        pid = self._daemon_pid()
        return bool(pid and pid != os.getpid() and _pid_alive(pid))

    def _stop_process_loop(self) -> None:
        """Stop a previously started loop so restarts never stack processes."""
        pid = self._daemon_pid()
        if pid and pid != os.getpid() and _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            deadline = self.clock() + 5
            while self.clock() < deadline and _pid_alive(pid):
                self.sleeper(0.2)
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            self.daemon_pid_path.unlink()
        except OSError:
            pass

    def _start_process_loop(self) -> tuple[bool, str | None]:
        """Launch the detached ``worker_supervisor.py --daemon`` loop."""
        try:
            log = open(self.daemon_log_path, "ab")
        except OSError as e:
            return False, f"cannot open {self.daemon_log_path}: {type(e).__name__}"
        env = dict(os.environ)
        env["TASKBRIDGE_REPO_DIR"] = str(self.repo_dir)
        env["TASKBRIDGE_DAEMON_PID_PATH"] = str(self.daemon_pid_path)
        try:
            proc = self.spawner(
                [sys.executable, str(HERE / "worker_supervisor.py"), "--daemon",
                 "--interval", str(self.loop_interval_sec)],
                cwd=str(self.repo_dir), env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        except OSError as e:
            log.close()
            return False, f"spawn failed: {type(e).__name__}: {e}"
        finally:
            try:
                log.close()
            except OSError:
                pass
        try:
            self.daemon_pid_path.write_text(str(proc.pid))
        except OSError:
            pass
        return True, None

    # -------------------------------------------------------------- discovery

    def _plist_mentions_worker(self, path: Path) -> bool:
        """True if a plist's ProgramArguments run THIS checkout's worker.py."""
        try:
            import plistlib
            with open(path, "rb") as f:
                data = plistlib.load(f)
        except Exception:
            return False
        args = data.get("ProgramArguments") or []
        if isinstance(args, list):
            for arg in args:
                arg = str(arg)
                if arg.endswith("worker.py"):
                    try:
                        if Path(arg).resolve().parent == self.repo_dir:
                            return True
                    except OSError:
                        return False
        return False

    def discover_service(self, refresh: bool = False) -> dict:
        """Find the actual installed LaunchAgent and its runtime state.

        Never invents a label: it must come from the environment override, from
        an installed plist that runs this checkout's worker, or from the
        conventional name actually being present on disk.
        """
        if self._service_cache is not None and not refresh:
            return dict(self._service_cache)

        label = self.candidate_label()
        discovered_by = "env override" if (
            self._label_override or os.environ.get("TASKBRIDGE_SERVICE_LABEL")
        ) else "default label"
        plist = self.plist_path(label)

        if not plist.exists() and not (
            self._label_override or os.environ.get("TASKBRIDGE_SERVICE_LABEL")
        ):
            # Discover the real label from installed configuration: a plist
            # whose ProgramArguments point at this checkout's worker.py wins.
            for cand in sorted(self.launch_agents_dir.glob("*.plist")):
                if self._plist_mentions_worker(cand):
                    label = cand.stem
                    plist = cand
                    discovered_by = "installed plist scan"
                    break

        label_valid = bool(_LABEL_RE.fullmatch(label))
        info: dict = {
            "label": label if label_valid else None,
            "label_raw": label,
            "label_valid": label_valid,
            "discovered_by": discovered_by,
            "plist_path": str(plist),
            "plist_exists": plist.exists(),
            "loaded": False,
            "state": None,
            "pid": None,
            "last_exit_code": None,
            "runs": None,
            "domain": None,
            "error": None,
        }
        if not label_valid:
            info["error"] = f"service label failed validation: {label!r}"
            self._service_cache = dict(info)
            return info

        domain = self.domain()
        info["domain"] = domain
        target = f"{domain}/{label}"
        out = self._launchctl(["print", target])
        if out["error"] and out["rc"] is None:
            info["error"] = out["error"]
            self._service_cache = dict(info)
            return info
        if not out["ok"]:
            info["error"] = _tail(out["stderr"]) or None
            self._service_cache = dict(info)
            return info

        info["loaded"] = True
        info["error"] = None
        text = out["stdout"] or ""
        for key, pattern in (
            ("state", r"^\s*state\s*=\s*(.+?)\s*$"),
            ("pid", r"^\s*pid\s*=\s*(\d+)"),
            ("last_exit_code", r"^\s*last exit (?:code|status)\s*=\s*(-?\d+)"),
            ("runs", r"^\s*runs\s*=\s*(-?\d+)"),
            ("plist_loaded_from", r"^\s*path\s*=\s*(.+?)\s*$"),
        ):
            m = re.search(pattern, text, re.MULTILINE)
            if m:
                value = m.group(1)
                info[key] = int(value) if key in ("pid", "last_exit_code", "runs") else value
        if info.get("plist_loaded_from"):
            info["plist_exists"] = info["plist_exists"] or Path(
                info["plist_loaded_from"]).exists()
        self._service_cache = dict(info)
        return info

    def service_target(self) -> str | None:
        svc = self.discover_service()
        if not svc.get("label_valid"):
            return None
        return f"{svc['domain']}/{svc['label']}"

    # ----------------------------------------------------------------- probes

    def heartbeat(self, max_stale_sec: int | None = None) -> dict:
        """Worker liveness from heartbeat.json (same semantics as the MCP tool)."""
        max_stale = _clamp(max_stale_sec, 30, 3600, self.max_stale_sec)
        out: dict = {
            "alive": False, "ts": None, "age_sec": None, "pid": None,
            "version": None, "default_model": None, "claimed_this_pass": None,
            "current_task": None, "max_stale_sec": max_stale, "note": None,
        }
        try:
            hb = json.loads(self.heartbeat_path.read_text())
        except FileNotFoundError:
            out["note"] = "no heartbeat file — worker may never have run"
            return out
        except (OSError, ValueError) as e:
            out["note"] = f"heartbeat unreadable: {type(e).__name__}"
            return out
        if not isinstance(hb, dict):
            out["note"] = "heartbeat file is not a JSON object"
            return out
        out["ts"] = hb.get("ts")
        out["pid"] = hb.get("pid") if isinstance(hb.get("pid"), int) else None
        out["version"] = hb.get("version")
        out["default_model"] = hb.get("default_model")
        out["claimed_this_pass"] = hb.get("claimed_this_pass")
        out["current_task"] = hb.get("current_task") or ""
        age = _age_sec(out["ts"])
        out["age_sec"] = age
        if age is None:
            out["note"] = "heartbeat ts missing or unparsable"
            return out
        out["alive"] = age <= max_stale
        if not out["alive"]:
            out["note"] = f"heartbeat is {age}s old (stale > {max_stale}s)"
        return out

    def pass_in_progress(self) -> bool:
        """True while a worker pass holds its flock (worker.py acquire_lock).

        flock is exactly the worker's own single-instance guard, so this is a
        live fact, not a guess from a stale PID file.
        """
        try:
            fd = os.open(str(self.worker_lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)

    def queue_snapshot(self) -> dict:
        """Read-only queue view (never mutates task records)."""
        try:
            snap = self._queue_snapshot()
        except Exception as e:  # a broken DB must not break restart reporting
            return {"ok": False, "error": f"{type(e).__name__}: {_tail(str(e), 120)}"}
        return snap if isinstance(snap, dict) else {"ok": False, "error": "bad snapshot"}

    def _stalled_evidence(self, hb: dict, queue: dict) -> dict:
        """Is the worker demonstrably online but not processing queued work?

        Conservative: the last pass must have claimed nothing AND left no
        current task AND eligible pending work must predate that pass by more
        than two cadences. Anything less certain stays "healthy".
        """
        ev = {"stalled": False, "reason": None,
              "eligible_pending": queue.get("eligible_pending", 0),
              "oldest_eligible_age_sec": queue.get("oldest_eligible_age_sec")}
        claimed = hb.get("claimed_this_pass")
        if not hb.get("alive"):
            ev["reason"] = "heartbeat not fresh"
            return ev
        if isinstance(claimed, int) and claimed > 0:
            ev["reason"] = "last pass claimed work"
            return ev
        if hb.get("current_task"):
            ev["reason"] = "pass is executing a task right now"
            return ev
        oldest = _parse_ts(queue.get("oldest_eligible_created_at"))
        hb_ts = _parse_ts(hb.get("ts"))
        if not oldest or not hb_ts:
            ev["reason"] = "no eligible pending work older than the last pass"
            return ev
        if (hb_ts - oldest).total_seconds() < STALL_MIN_AGE_SEC:
            ev["reason"] = (f"oldest eligible task is younger than "
                            f"{STALL_MIN_AGE_SEC}s of passes")
            return ev
        ev["stalled"] = True
        ev["reason"] = (
            f"{ev['eligible_pending']} eligible task(s) pending for >"
            f"{STALL_MIN_AGE_SEC}s before the last pass, which claimed nothing")
        return ev

    def assess(self, max_stale_sec: int | None = None) -> dict:
        """Full worker/service assessment: healthy | stale | offline (+ detail)."""
        hb = self.heartbeat(max_stale_sec)
        svc = self.discover_service(refresh=True)
        queue = self.queue_snapshot()
        in_pass = self.pass_in_progress()
        busy = bool(in_pass and hb.get("current_task"))
        stalled = self._stalled_evidence(hb, queue)

        if hb["alive"]:
            status, reason = "healthy", "heartbeat is fresh"
        elif in_pass:
            # flock is held, so a pass process is alive and mid-flight; the
            # heartbeat just hasn't refreshed yet (older worker) or the pass
            # is wedged. "dead" is the wrong read here — see watchdog_decision.
            status = "stale"
            reason = ("a pass is in progress — heartbeat paused (long task "
                      "or older worker)")
        elif svc.get("pid"):
            status = "stale"
            reason = "worker process is alive but the heartbeat is stale"
        elif hb.get("ts"):
            status, reason = "offline", hb.get("note") or "heartbeat is stale"
        else:
            status, reason = "offline", hb.get("note") or "no heartbeat"

        diagnosis = {
            "healthy": "worker is online and checking in",
            "stale": ("a worker pass is mid-flight — likely a long task"
                      if in_pass else
                      "worker process alive but heartbeat stale — restart required"),
            "offline": "worker is offline — queue will not drain",
        }[status]
        if status == "healthy" and stalled["stalled"]:
            diagnosis = "worker online but not processing queued work"
        return {
            "status": status,
            "reason": reason,
            "diagnosis": diagnosis,
            "heartbeat": hb,
            "service": svc,
            "queue": queue,
            "pass_in_progress": in_pass,
            "busy": busy,
            "stalled": stalled,
        }

    # -------------------------------------------------------------- launchctl

    def _launchctl(self, argv_extra: list[str], timeout: int = LAUNCHCTL_TIMEOUT_SEC) -> dict:
        """Run /bin/launchctl with a fixed, validated argv. Never a shell.

        The executable is a fixed path (or an absolute override used by tests
        and packaging), and argv_extra is built exclusively by this module from
        validated labels, numeric ids and existing plist paths.
        """
        exe = str(self.launchctl)
        if not os.path.isabs(exe) or not os.access(exe, os.X_OK):
            return {"ok": False, "rc": None, "stdout": "", "stderr": "",
                    "error": f"launchctl not executable: {exe}"}
        for token in argv_extra:
            if not isinstance(token, str) or not token or "\x00" in token:
                return {"ok": False, "rc": None, "stdout": "", "stderr": "",
                        "error": "refusing to run launchctl with a malformed argument"}
        argv = [exe] + list(argv_extra)
        try:
            proc = self.runner(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "rc": None, "stdout": "", "stderr": "",
                    "error": f"launchctl {' '.join(argv_extra)} timed out after {timeout}s"}
        except (OSError, PermissionError) as e:
            return {"ok": False, "rc": None, "stdout": "", "stderr": "",
                    "error": f"launchctl unavailable: {type(e).__name__}: {e}"}
        rc = getattr(proc, "returncode", None)
        return {
            "ok": rc == 0,
            "rc": rc,
            "stdout": getattr(proc, "stdout", "") or "",
            "stderr": getattr(proc, "stderr", "") or "",
            "error": None,
        }

    @staticmethod
    def _classify_launchctl_error(out: dict) -> tuple[str, str]:
        """Map a launchctl failure to (outcome, human message)."""
        if out.get("error"):
            if "not executable" in out["error"] or "unavailable" in out["error"]:
                return "supervisor_unavailable", out["error"]
            return "launchctl_failed", out["error"]
        err = (out.get("stderr") or "") + (out.get("stdout") or "")
        low = err.lower()
        if "operation not permitted" in low or "permission denied" in low:
            return "permission_denied", _tail(err) or "launchctl permission denied"
        if "could not find service" in low or "service not found" in low:
            return "service_not_loaded", _tail(err) or "service not loaded"
        if "bootstrap failed: 5" in low or "already" in low and "loaded" in low:
            return "already_loaded", _tail(err) or "service already loaded"
        return "launchctl_failed", _tail(err) or f"launchctl exited {out.get('rc')}"

    # ------------------------------------------------------------------ state

    def _read_state(self) -> dict:
        base = {
            "last_attempt_ts": None, "last_outcome": None, "last_error": None,
            "consecutive_failures": 0, "attempts_total": 0, "history": [],
        }
        try:
            data = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return base
        if isinstance(data, dict):
            base.update({k: data.get(k, base[k]) for k in base})
            if not isinstance(base["history"], list):
                base["history"] = []
        return base

    def _write_state(self, state: dict) -> None:
        try:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2))
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.state_path)
        except OSError:
            pass  # state is advisory; never fail a restart over bookkeeping

    def _effective_cooldown(self, state: dict) -> int:
        """Base cooldown, escalated (x2 up to x8) while attempts keep failing."""
        if int(state.get("consecutive_failures") or 0) > 0:
            return self.cooldown_sec * min(2 ** int(state["consecutive_failures"]), 8)
        return self.cooldown_sec

    def _cooldown_remaining(self, state: dict) -> int | None:
        last = _parse_ts(state.get("last_attempt_ts"))
        if not last:
            return None
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        remaining = self._effective_cooldown(state) - elapsed
        return int(remaining) if remaining > 0 else None

    def _record_attempt(self, *, outcome: str, force: bool, method: str,
                        duration_ms: int, error: str | None, success: bool) -> None:
        state = self._read_state()
        state["last_attempt_ts"] = _now_iso()
        state["last_outcome"] = outcome
        state["last_error"] = _redact(error or "", 300) if error else None
        state["attempts_total"] = int(state.get("attempts_total") or 0) + 1
        state["consecutive_failures"] = 0 if success else int(
            state.get("consecutive_failures") or 0) + 1
        history = list(state.get("history") or [])
        history.append({
            "ts": state["last_attempt_ts"], "outcome": outcome,
            "force": bool(force), "method": method, "duration_ms": duration_ms,
            "error": state["last_error"],
        })
        state["history"] = history[-STATE_HISTORY:]
        self._write_state(state)

    # ----------------------------------------------------------- concurrency

    def _acquire_restart_lock(self):
        try:
            fd = os.open(str(self.restart_lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            return None, f"could not open restart lock: {type(e).__name__}"
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None, "another restart request is already in progress"
        return fd, None

    @staticmethod
    def _release_lock(fd) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    # ------------------------------------------------------------ diagnostics

    def _log(self, message: str) -> None:
        line = f"{_now_iso()} restart_worker: {message}"
        try:
            with open(self.restart_log_path, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass
        print(line, flush=True)

    def _worker_log_tail(self, lines: int = 3) -> list[str]:
        """Last few launchd-log lines, redacted. Diagnostics without secrets."""
        try:
            text = self.worker_log_path.read_text(errors="replace")
        except OSError:
            return []
        out: list[str] = []
        for raw in reversed(text.splitlines()[-50:]):
            safe = _redact(raw)
            if safe:
                out.append(safe)
            if len(out) >= lines:
                break
        return list(reversed(out))

    def _result(self, **kw) -> dict:
        """Structured result with every documented field always present."""
        out = {
            "success": False,
            "previous_status": "unknown",
            "restart_attempted": False,
            "restart_method": "none",
            "service_label": None,
            "heartbeat_before": None,
            "heartbeat_after": None,
            "worker_pid": None,
            "elapsed_ms": 0,
            "error": None,
            "next_steps": [],
            "outcome": "unknown",
            "diagnosis": "",
            "verified": False,
            "service_state_before": None,
            "service_state_after": None,
            "queue_evidence": None,
            "cooldown_remaining_sec": None,
            "interrupted_pass_possible": False,
            "stalled": False,
            "stall_reason": None,
            "logs": [],
        }
        out.update(kw)
        return out

    @staticmethod
    def _hb_summary(hb: dict | None) -> dict | None:
        if not hb:
            return None
        return {
            "alive": hb.get("alive"),
            "ts": hb.get("ts"),
            "age_sec": hb.get("age_sec"),
            "max_stale_sec": hb.get("max_stale_sec"),
            "pid": hb.get("pid"),
            "claimed_this_pass": hb.get("claimed_this_pass"),
            "current_task": hb.get("current_task"),
            "note": hb.get("note"),
        }

    @staticmethod
    def _svc_summary(svc: dict | None) -> dict | None:
        if not svc:
            return None
        return {
            "loaded": svc.get("loaded"),
            "state": svc.get("state"),
            "pid": svc.get("pid"),
            "last_exit_code": svc.get("last_exit_code"),
            "runs": svc.get("runs"),
            "plist_exists": svc.get("plist_exists"),
            "plist_path": svc.get("plist_path"),
            "domain": svc.get("domain"),
        }

    # --------------------------------------------------------------- restart

    def restart(self, force: bool = False, timeout_sec: int | None = None,
                max_stale_sec: int | None = None) -> dict:
        """Restart the worker via its supervisor and verify real recovery.

        Returns the structured result documented in the README; never raises for
        expected failure modes (missing service, permissions, timeouts).
        """
        t0 = self.clock()
        timeout = _clamp(
            timeout_sec if timeout_sec is not None else self.timeout_sec,
            10, 600, self.timeout_sec)
        max_stale = _clamp(
            max_stale_sec if max_stale_sec is not None else self.max_stale_sec,
            30, 3600, self.max_stale_sec)

        def elapsed_ms() -> int:
            return int((self.clock() - t0) * 1000)

        lock_fd, lock_err = self._acquire_restart_lock()
        if lock_fd is None:
            return self._result(
                outcome="already_in_progress", diagnosis=lock_err or "locked",
                error=lock_err, elapsed_ms=elapsed_ms(),
                next_steps=["Another restart is running; retry in a few seconds "
                            "and check worker_heartbeat."])
        logs: list[str] = []
        try:
            return self._restart_locked(
                force=force, timeout=timeout, max_stale=max_stale,
                t0=t0, logs=logs)
        finally:
            self._release_lock(lock_fd)

    def _restart_locked(self, *, force: bool, timeout: int, max_stale: int,
                        t0: float, logs: list[str]) -> dict:
        if self.backend() == "process":
            return self._process_restart_locked(
                force=force, timeout=timeout, max_stale=max_stale, t0=t0, logs=logs)
        return self._launchd_restart_locked(
            force=force, timeout=timeout, max_stale=max_stale, t0=t0, logs=logs)

    def _launchd_restart_locked(self, *, force: bool, timeout: int, max_stale: int,
                                t0: float, logs: list[str]) -> dict:
        def elapsed_ms() -> int:
            return int((self.clock() - t0) * 1000)

        hb_before = self.heartbeat(max_stale)
        svc_before = self.discover_service(refresh=True)
        queue_before = self.queue_snapshot()
        in_pass = self.pass_in_progress()
        stalled = self._stalled_evidence(hb_before, queue_before)
        status = ("healthy" if hb_before["alive"]
                  else "stale" if svc_before.get("pid") else "offline")
        diagnosis = {
            "healthy": "worker is online and checking in",
            "stale": "worker process is alive but the heartbeat is stale",
            "offline": "worker is offline",
        }[status]
        if status == "healthy" and stalled["stalled"]:
            diagnosis = "worker online but not processing queued work"
        logs.append(f"status={status} service_loaded={svc_before.get('loaded')} "
                    f"pass_in_progress={in_pass} stalled={stalled['stalled']}")

        common = dict(
            previous_status=status,
            heartbeat_before=self._hb_summary(hb_before),
            service_label=svc_before.get("label"),
            service_state_before=self._svc_summary(svc_before),
            diagnosis=diagnosis,
            interrupted_pass_possible=in_pass,
            stalled=bool(stalled.get("stalled")),
            stall_reason=stalled.get("reason"),
        )

        # 1. healthy worker + no explicit force -> never interrupt it
        if status == "healthy" and not stalled["stalled"] and not force:
            self._log(f"skipped: worker healthy (heartbeat {hb_before['age_sec']}s old)")
            return self._result(
                **common, success=True, restart_attempted=False,
                restart_method="none", verified=True, outcome="skipped_healthy",
                worker_pid=hb_before.get("pid"), elapsed_ms=elapsed_ms(),
                logs=logs,
                cooldown_remaining_sec=self._cooldown_remaining(self._read_state()),
                next_steps=["Worker is healthy — no restart needed. "
                            "Re-run with force=true only to interrupt deliberately."])

        if force and status == "healthy":
            diagnosis = ("force=true: intentionally restarting a healthy worker; "
                         "an active task may be interrupted (queued work is "
                         "preserved and stale runs are re-queued by the worker "
                         "reaper)")
            common["diagnosis"] = diagnosis

        # 2. no launchctl at all -> say so plainly, do not pretend to restart
        if not (os.path.isabs(str(self.launchctl))
                and os.access(str(self.launchctl), os.X_OK)):
            err = f"launchctl not usable at {self.launchctl}"
            self._log(f"supervisor unavailable: {err}")
            return self._result(
                **common, success=False, restart_attempted=False,
                restart_method="none", outcome="supervisor_unavailable",
                error=err, elapsed_ms=elapsed_ms(), logs=logs,
                next_steps=self._failure_next_steps("supervisor_unavailable", err))

        # 3. rate limit (applies to forced restarts too — that is the point)
        state = self._read_state()
        remaining = self._cooldown_remaining(state)
        if remaining:
            self._log(f"rate limited: {remaining}s of cooldown remain "
                      f"(last outcome: {state.get('last_outcome')})")
            return self._result(
                **common, success=False, restart_attempted=False,
                restart_method="none", outcome="rate_limited",
                cooldown_remaining_sec=remaining, error=None,
                elapsed_ms=elapsed_ms(), logs=logs,
                next_steps=[f"Cooldown active for another {remaining}s "
                            f"(base {self.cooldown_sec}s; escalates while attempts "
                            "fail). Retry after that, or investigate with "
                            "worker_heartbeat / queue_status."])

        # 4. pick the supervisor operation
        if not svc_before.get("loaded") and not svc_before.get("plist_exists"):
            err = svc_before.get("error") or "no LaunchAgent installed for this worker"
            self._log(f"service missing: {err}")
            self._record_attempt(outcome="service_missing", force=force,
                                 method="none", duration_ms=elapsed_ms(),
                                 error=err, success=False)
            return self._result(
                **common, success=False, restart_attempted=False,
                restart_method="none", outcome="service_missing", error=err,
                elapsed_ms=elapsed_ms(), logs=logs,
                next_steps=[
                    "Install the worker LaunchAgent once (see README → "
                    "'Worker supervision & restart_worker'):",
                    f"  cp launchd/com.taskbridge.worker.plist "
                    f"~/{self.launch_agents_dir.name}/{DEFAULT_SERVICE_LABEL}.plist"
                    "  (edit the paths inside first)",
                    f"  launchctl bootstrap {svc_before.get('domain')} "
                    f"~/{self.launch_agents_dir.name}/{DEFAULT_SERVICE_LABEL}.plist",
                    f"  launchctl kickstart -k {svc_before.get('domain')}/"
                    f"{DEFAULT_SERVICE_LABEL}",
                    "Then set TASKBRIDGE_SERVICE_LABEL if you used a different label."
                    if not svc_before.get("plist_exists") else "plist exists — bootstrap it.",
                ])

        if svc_before.get("loaded"):
            method = "launchctl kickstart"
            op = ["kickstart", "-k", self.service_target() or ""]
        else:
            method = "launchctl bootstrap"
            op = ["bootstrap", svc_before.get("domain") or f"gui/{self.uid}",
                  str(svc_before.get("plist_path"))]

        # 5. graceful first: give a busy pass a bounded chance to finish so an
        #    active task is not interrupted when it is about to end anyway.
        if in_pass:
            grace = min(self.grace_sec, max(0, timeout // 3))
            waited = self._wait_for_pass_to_end(grace)
            logs.append(f"waited {waited:.1f}s for the running pass to finish "
                        f"(grace {grace}s)")
            if waited < grace:
                diagnosis = (diagnosis + "; running pass finished before restart")
                common["diagnosis"] = diagnosis

        self._log(f"restarting via {method}: {' '.join(op)}")
        out = self._launchctl(op)
        logs.append(f"{method} rc={out.get('rc')} "
                    f"err={_tail(out.get('stderr') or out.get('error') or '', 200)!r}")

        if not out["ok"]:
            outcome, message = self._classify_launchctl_error(out)
            if outcome == "service_not_loaded" and svc_before.get("plist_exists"):
                # stale view: plist exists, launchd lost the job — bootstrap it
                method = "launchctl bootstrap"
                op = ["bootstrap", svc_before.get("domain") or f"gui/{self.uid}",
                      str(svc_before.get("plist_path"))]
                self._log(f"kickstart said not loaded — retrying with {method}")
                out = self._launchctl(op)
                logs.append(f"{method} rc={out.get('rc')}")
                if out["ok"]:
                    outcome, message = None, None
                else:
                    outcome, message = self._classify_launchctl_error(out)
            if outcome:
                self._record_attempt(outcome=outcome, force=force, method=method,
                                     duration_ms=elapsed_ms(), error=message,
                                     success=False)
                self._log(f"restart failed: {outcome}: {message}")
                return self._result(
                    **common, success=False, restart_attempted=True,
                    restart_method=method, outcome=outcome, error=message,
                    elapsed_ms=elapsed_ms(), logs=logs,
                    next_steps=self._failure_next_steps(outcome, message))

        # 6. verify recovery — launchctl exit 0 is NOT success evidence
        restart_verified_ts = _now_iso()
        hb_after, verified = self._wait_for_recovery(
            hb_before, max_stale, deadline=t0 + timeout, logs=logs)
        svc_after = self.discover_service(refresh=True)
        queue_after = self.queue_snapshot()
        evidence = self._queue_evidence(queue_before, queue_after, hb_after)
        worker_pid = (hb_after or {}).get("pid") or svc_after.get("pid")

        if verified:
            self._record_attempt(outcome="recovered", force=force, method=method,
                                 duration_ms=elapsed_ms(), error=None, success=True)
            self._log(f"recovered: heartbeat {hb_after.get('age_sec')}s old, "
                      f"{evidence.get('note')}")
            return self._result(
                **common, success=True, restart_attempted=True,
                restart_method=method, verified=True, outcome="restarted",
                heartbeat_after=self._hb_summary(hb_after),
                service_state_after=self._svc_summary(svc_after),
                worker_pid=worker_pid, elapsed_ms=elapsed_ms(),
                queue_evidence=evidence, logs=logs + [f"verified_at={restart_verified_ts}"],
                next_steps=["Worker restarted and verified with a fresh heartbeat."]
                + ([] if evidence.get("processing_observed") else [
                    "Submit or wait for a task and confirm with queue_status()."]))

        err = (f"restart attempted via {method}, but no fresh heartbeat within "
               f"{timeout}s")
        if svc_after.get("last_exit_code") not in (None, 0):
            err += (f"; worker last exit code {svc_after['last_exit_code']}"
                    " (78 = EX_CONFIG: launchd could not run the configured program)")
        tail = self._worker_log_tail(3)
        self._record_attempt(outcome="restart_timeout", force=force, method=method,
                             duration_ms=elapsed_ms(), error=err, success=False)
        self._log(f"verification failed: {err}")
        return self._result(
            **common, success=False, restart_attempted=True, restart_method=method,
            heartbeat_after=self._hb_summary(hb_after),
            service_state_after=self._svc_summary(svc_after),
            worker_pid=worker_pid or svc_after.get("pid"), outcome="restart_timeout",
            error=err, elapsed_ms=elapsed_ms(), queue_evidence=evidence,
             logs=logs + [f"worker log: {line}" for line in tail],
             next_steps=self._failure_next_steps("restart_timeout", err))

    def _process_restart_locked(self, *, force: bool, timeout: int, max_stale: int,
                                t0: float, logs: list[str]) -> dict:
        """Restart via the detached process loop (non-macOS / no launchd)."""
        def elapsed_ms() -> int:
            return int((self.clock() - t0) * 1000)

        hb_before = self.heartbeat(max_stale)
        queue_before = self.queue_snapshot()
        in_pass = self.pass_in_progress()
        stalled = self._stalled_evidence(hb_before, queue_before)
        status = "healthy" if hb_before["alive"] else "offline"
        diagnosis = ("worker is online and checking in" if status == "healthy"
                     else "worker is offline — queue will not drain")
        if status == "healthy" and stalled["stalled"]:
            diagnosis = "worker online but not processing queued work"
        logs.append(f"status={status} backend=process pass_in_progress={in_pass} "
                    f"stalled={stalled['stalled']}")

        common = dict(
            previous_status=status,
            heartbeat_before=self._hb_summary(hb_before),
            service_label=None,
            service_state_before=None,
            diagnosis=diagnosis,
            interrupted_pass_possible=in_pass,
            stalled=bool(stalled.get("stalled")),
            stall_reason=stalled.get("reason"),
        )

        if status == "healthy" and not stalled["stalled"] and not force:
            self._log(f"skipped: worker healthy (heartbeat {hb_before['age_sec']}s old)")
            return self._result(
                **common, success=True, restart_attempted=False,
                restart_method="none", verified=True, outcome="skipped_healthy",
                worker_pid=hb_before.get("pid"), elapsed_ms=elapsed_ms(), logs=logs,
                cooldown_remaining_sec=self._cooldown_remaining(self._read_state()),
                next_steps=["Worker is healthy — no restart needed. "
                            "Re-run with force=true only to interrupt deliberately."])

        if force and status == "healthy":
            common["diagnosis"] = (
                "force=true: intentionally restarting a healthy worker; "
                "an active task may be interrupted (queued work is preserved "
                "and stale runs are re-queued by the worker reaper)")

        state = self._read_state()
        remaining = self._cooldown_remaining(state)
        if remaining:
            self._log(f"rate limited: {remaining}s of cooldown remain "
                      f"(last outcome: {state.get('last_outcome')})")
            return self._result(
                **common, success=False, restart_attempted=False,
                restart_method="none", outcome="rate_limited",
                cooldown_remaining_sec=remaining, elapsed_ms=elapsed_ms(), logs=logs,
                next_steps=[f"Cooldown active for another {remaining}s "
                            f"(base {self.cooldown_sec}s; escalates while attempts "
                            "fail). Retry after that, or investigate with "
                            "worker_heartbeat / queue_status."])

        if in_pass:
            grace = min(self.grace_sec, max(0, timeout // 3))
            waited = self._wait_for_pass_to_end(grace)
            logs.append(f"waited {waited:.1f}s for the running pass to finish "
                        f"(grace {grace}s)")

        method = "process loop"
        self._stop_process_loop()
        started, err = self._start_process_loop()
        if not started:
            self._record_attempt(outcome="spawn_failed", force=force, method=method,
                                 duration_ms=elapsed_ms(), error=err, success=False)
            self._log(f"spawn failed: {err}")
            return self._result(
                **common, success=False, restart_attempted=True,
                restart_method=method, outcome="spawn_failed", error=err,
                elapsed_ms=elapsed_ms(), logs=logs,
                next_steps=self._failure_next_steps("spawn_failed", err or ""))
        logs.append(f"started {method} (daemon pid {self._daemon_pid()})")

        hb_after, verified = self._wait_for_recovery(
            hb_before, max_stale, deadline=t0 + timeout, logs=logs)
        queue_after = self.queue_snapshot()
        evidence = self._queue_evidence(queue_before, queue_after, hb_after)
        worker_pid = (hb_after or {}).get("pid") or self._daemon_pid()

        if verified:
            self._record_attempt(outcome="recovered", force=force, method=method,
                                 duration_ms=elapsed_ms(), error=None, success=True)
            self._log(f"recovered: heartbeat {hb_after.get('age_sec')}s old, "
                      f"{evidence.get('note')}")
            return self._result(
                **common, success=True, restart_attempted=True,
                restart_method=method, verified=True, outcome="restarted",
                heartbeat_after=self._hb_summary(hb_after), worker_pid=worker_pid,
                elapsed_ms=elapsed_ms(), queue_evidence=evidence, logs=logs,
                next_steps=["Worker restarted and verified with a fresh heartbeat."])

        err = (f"worker loop started, but no fresh heartbeat within {timeout}s")
        tail = self._worker_log_tail(3)
        self._record_attempt(outcome="restart_timeout", force=force, method=method,
                             duration_ms=elapsed_ms(), error=err, success=False)
        self._log(f"verification failed: {err}")
        return self._result(
            **common, success=False, restart_attempted=True, restart_method=method,
            heartbeat_after=self._hb_summary(hb_after), worker_pid=worker_pid,
            outcome="restart_timeout", error=err, elapsed_ms=elapsed_ms(),
            queue_evidence=evidence,
            logs=logs + [f"worker log: {line}" for line in tail],
            next_steps=self._failure_next_steps("restart_timeout", err))

    # ------------------------------------------------------------ helpers

    def _wait_for_pass_to_end(self, seconds: float) -> float:
        t0 = self.clock()
        while self.clock() - t0 < seconds:
            if not self.pass_in_progress():
                break
            self.sleeper(0.5)
        return self.clock() - t0

    def _wait_for_recovery(self, hb_before: dict, max_stale: int,
                           deadline: float, logs: list[str]) -> tuple[dict, bool]:
        """Poll until a heartbeat newer than the restart attempt appears."""
        before_ts = _parse_ts(hb_before.get("ts"))
        polls = 0
        while True:
            hb = self.heartbeat(max_stale)
            fresh_new = False
            if hb["alive"]:
                after_ts = _parse_ts(hb.get("ts"))
                fresh_new = after_ts is not None and (
                    before_ts is None or after_ts > before_ts)
            polls += 1
            if fresh_new:
                return hb, True
            if self.clock() >= deadline:
                logs.append(f"no fresh heartbeat after {polls} poll(s)")
                return hb, False
            self.sleeper(1.0)

    def _queue_evidence(self, before: dict, after: dict, hb_after: dict | None) -> dict:
        """Evidence that the recovered worker is actually processing work."""
        evidence = {
            "pending_before": before.get("pending_total"),
            "pending_after": after.get("pending_total"),
            "pending_change": None,
            "claimed_by_new_pass": None,
            "processing_observed": False,
            "note": "queue unavailable",
        }
        if before.get("ok") and after.get("ok"):
            b = before.get("pending_total")
            a = after.get("pending_total")
            evidence["pending_change"] = (a - b) if isinstance(b, int) and isinstance(a, int) else None
            claimed = (hb_after or {}).get("claimed_this_pass")
            evidence["claimed_by_new_pass"] = claimed if isinstance(claimed, int) else None
            if isinstance(claimed, int) and claimed > 0:
                evidence["processing_observed"] = True
                evidence["note"] = f"new pass claimed {claimed} task(s)"
            elif evidence["pending_change"] is not None and evidence["pending_change"] < 0:
                evidence["processing_observed"] = True
                evidence["note"] = "pending queue shrank after the restart"
            elif b == 0:
                evidence["note"] = "queue empty — heartbeat proof only"
            else:
                evidence["note"] = "pending work unchanged (pass may still be starting)"
        return evidence

    def _failure_next_steps(self, outcome: str, message: str) -> list[str]:
        steps = [f"Failure detail: {message}"]
        if outcome == "supervisor_unavailable":
            steps += [
                f"launchctl not usable at {self.launchctl} — this restart path is "
                "macOS/launchd only.",
                "Start the worker manually for now (background, logs to worker.log):",
                f"  cd {self.repo_dir} && nohup {sys.executable} worker.py >> worker.log 2>&1 &",
                "For a permanent fix on this host, install a process supervisor "
                "(systemd unit, cron @reboot, or run worker.py --loop under tmux).",
            ]
        elif outcome == "permission_denied":
            steps += [
                "launchctl refused the operation — the service is a user "
                "LaunchAgent and must be controlled from the same login session.",
                f"From a Terminal in this GUI session run: launchctl kickstart -k "
                f"{self.domain()}/{self.service_label_or_default()}",
                "If the LaunchAgent was installed with sudo, reinstall it as the "
                "logged-in user (no sudo) — see README → Worker supervision.",
            ]
        elif outcome == "service_not_loaded":
            steps += [
                f"The job is not loaded in {self.domain()}. Reinstall the plist:",
                f"  launchctl bootstrap {self.domain()} {self.plist_path(self.service_label_or_default())}",
            ]
        elif outcome == "restart_timeout":
            steps += [
                "The service command succeeded but no fresh heartbeat appeared: "
                "the worker started and died, or the plist paths are wrong.",
                f"Inspect the last lines of {self.worker_log_path} — "
                "common causes: EX_CONFIG 78 (bad ProgramArguments), missing "
                ".venv, or a crash on import.",
                f"Check 'launchctl print {self.service_target()}' for last exit code.",
                "Queued tasks are untouched; they will run as soon as the worker "
                "passes start.",
            ]
        elif outcome == "launchctl_failed":
            steps += [
                f"Run manually: launchctl kickstart -k {self.service_target()}",
                f"and inspect {self.worker_log_path}.",
            ]
        elif outcome == "spawn_failed":
            steps += [
                "Could not start the worker process loop.",
                f"Inspect {self.daemon_log_path} and check that "
                f"{sys.executable} can run {self.repo_dir / 'worker.py'}.",
            ]
        steps.append("Verify with worker_heartbeat() and queue_status().")
        return steps

    def service_label_or_default(self) -> str:
        return self.discover_service().get("label") or DEFAULT_SERVICE_LABEL

    def status(self) -> dict:
        """Diagnostic snapshot (used by the CLI and tests)."""
        a = self.assess()
        state = self._read_state()
        return {
            "backend": self.backend(),
            "daemon_alive": self.daemon_alive(),
            "service": self._svc_summary(a["service"]),
            "heartbeat": self._hb_summary(a["heartbeat"]),
            "status": a["status"],
            "diagnosis": a["diagnosis"],
            "pass_in_progress": a["pass_in_progress"],
            "busy": a["busy"],
            "stalled": a["stalled"],
            "queue": a["queue"],
            "cooldown_remaining_sec": self._cooldown_remaining(state),
            "last_attempt": {k: state.get(k) for k in
                             ("last_attempt_ts", "last_outcome", "attempts_total",
                              "consecutive_failures")},
        }


# --------------------------------------------------------------- queue read

def _default_queue_snapshot() -> dict:
    """Read-only view of the queue. Never mutates a task record."""
    import task_store
    counts = task_store.queue_status().get("counts", {})
    tasks = task_store.list_tasks("pending", 100)
    eligible = []
    for t in tasks:
        if (t.get("created_by") or "") not in ("claude", "chatgpt"):
            continue
        try:
            deps = json.loads(t.get("depends_on") or "[]")
        except (json.JSONDecodeError, ValueError):
            deps = []
        if deps:
            states = task_store.get_many([d for d in deps if isinstance(d, str)])
            if any(d not in states or states[d]["status"] != "completed" for d in deps):
                continue  # legitimately blocked on dependencies
        eligible.append(t)
    oldest = None
    if eligible:
        oldest = min(eligible, key=lambda t: t.get("created_at") or "").get("created_at")
    return {
        "ok": True,
        "counts": counts,
        "pending_total": int(counts.get("pending", 0)),
        "running_total": int(counts.get("running", 0)),
        "eligible_pending": len(eligible),
        "oldest_eligible_id": eligible and min(
            eligible, key=lambda t: t.get("created_at") or "").get("id"),
        "oldest_eligible_created_at": oldest,
        "oldest_eligible_age_sec": _age_sec(oldest),
    }


# ------------------------------------------------------------- singleton

_default_supervisor: Supervisor | None = None
_default_lock = threading.Lock()


def default_supervisor() -> Supervisor:
    """Process-wide Supervisor (paths/env resolved lazily, cached)."""
    global _default_supervisor
    with _default_lock:
        if _default_supervisor is None:
            _default_supervisor = Supervisor()
        return _default_supervisor


def reset_default_supervisor() -> None:
    """Drop the cached instance (tests / after env changes)."""
    global _default_supervisor
    with _default_lock:
        _default_supervisor = None


def restart_worker(force: bool = False, timeout_sec: int | None = None) -> dict:
    """Convenience wrapper used by the MCP tool and the CLI."""
    return default_supervisor().restart(force=force, timeout_sec=timeout_sec)


def ensure_started() -> dict:
    """Start the worker if it isn't running yet (used by the installer).

    Safe to call repeatedly: a fresh heartbeat or a live loop/launchd job is
    reported as ``already_running`` without spawning a second process.
    """
    sup = default_supervisor()
    if sup.backend() == "launchd":
        return sup.restart(force=False)
    # Process backend: liveness is the loop itself (a fresh heartbeat with no
    # live loop means the worker died mid-window, so start a new one).
    if sup.daemon_alive() or sup.pass_in_progress():
        return {"success": True, "outcome": "already_running",
                "restart_attempted": False}
    sup._stop_process_loop()
    ok, err = sup._start_process_loop()
    return {"success": bool(ok), "outcome": "started" if ok else "spawn_failed",
            "restart_attempted": bool(ok), "error": err,
            "worker_pid": sup._daemon_pid()}


def run_daemon(interval_sec: int = DEFAULT_LOOP_INTERVAL_SEC) -> int:
    """Run worker passes forever — the process-backend supervisor loop.

    One pass per interval. ``worker.py`` keeps its own flock, so an overlapping
    launchd pass (or a manual run) simply skips rather than double-processing.
    """
    repo = Path(os.environ.get("TASKBRIDGE_REPO_DIR") or HERE).resolve()
    pid_path = Path(os.environ.get("TASKBRIDGE_DAEMON_PID_PATH")
                    or repo / ".worker_daemon.pid")
    try:
        pid_path.write_text(str(os.getpid()))
    except OSError:
        pass
    interval = _clamp(interval_sec, 5, 3600, DEFAULT_LOOP_INTERVAL_SEC)
    worker = repo / "worker.py"
    while True:
        try:
            subprocess.run([sys.executable, str(worker)], cwd=str(repo), check=False)
        except Exception:  # a broken pass must never kill the loop
            pass
        time.sleep(interval)


if __name__ == "__main__":  # tiny operator CLI: python worker_supervisor.py status
    import argparse

    ap = argparse.ArgumentParser(description="TaskBridge worker supervisor")
    ap.add_argument("--status", action="store_true", help="print service/heartbeat state")
    ap.add_argument("--restart", action="store_true", help="restart (skips if healthy)")
    ap.add_argument("--force", action="store_true", help="restart even if healthy")
    ap.add_argument("--timeout", type=int, default=None, help="recovery timeout (10-600s)")
    ap.add_argument("--daemon", action="store_true",
                    help="run the worker pass loop in the foreground (process backend)")
    ap.add_argument("--interval", type=int, default=DEFAULT_LOOP_INTERVAL_SEC,
                    help=f"seconds between passes in --daemon (default {DEFAULT_LOOP_INTERVAL_SEC})")
    args = ap.parse_args()
    if args.daemon:
        raise SystemExit(run_daemon(args.interval))
    sup = default_supervisor()
    if args.restart or args.force:
        print(json.dumps(sup.restart(force=args.force, timeout_sec=args.timeout), indent=2))
    else:
        print(json.dumps(sup.status(), indent=2))
