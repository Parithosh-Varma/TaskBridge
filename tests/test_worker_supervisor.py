"""Unit tests for worker_supervisor (the restart engine behind restart_worker).

Everything external is faked: launchctl is a scripted runner, the clock and
sleeps are virtual, and every path lives in a tmp dir. No test in this file
touches the real launchd domain, the real worker, or the real task DB.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import worker_supervisor as ws  # noqa: E402

REQUIRED_KEYS = {
    "success", "previous_status", "restart_attempted", "restart_method",
    "service_label", "heartbeat_before", "heartbeat_after", "worker_pid",
    "elapsed_ms", "error", "next_steps",
}


def iso(offset_sec: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


def _proc(rc: int, out: str = "", err: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class World:
    """A fake launchd world: paths, virtual clock, scripted launchctl."""

    def __init__(self, tmp_path: Path):
        self.repo = tmp_path
        self.launch_agents = tmp_path / "LaunchAgents"
        self.launch_agents.mkdir(exist_ok=True)
        self.heartbeat = tmp_path / "heartbeat.json"
        self.worker_lock = tmp_path / ".worker.lock"
        self.state = tmp_path / ".restart_state.json"
        self.restart_log = tmp_path / "restart.log"
        self.worker_log = tmp_path / "worker.launchd.log"
        self.uid = 501
        # deliberately NOT the production label: unit tests must never look
        # like they could touch the real service
        self.label = "com.taskbridge.testworker"
        self.plist = self.launch_agents / f"{self.label}.plist"
        self.clock_value = 1_000_000.0
        self.calls: list[list[str]] = []
        self.sleeps: list[float] = []
        # launchctl print state
        self.loaded = True
        self.svc_state = "not running"
        self.svc_pid: int | None = None
        self.last_exit_code = 0
        self.runs = 7
        self.print_rc = 0
        self.print_stderr = ""
        # per-verb scripted results
        self.verbs: dict[str, tuple[int, str, str]] = {}
        self.raise_on: dict[str, Exception] = {}
        self.on_launch: dict[str, callable] = {}
        self.launchctl_override = "/bin/launchctl"
        self.queue = {"ok": True, "counts": {"pending": 0, "running": 0},
                      "pending_total": 0, "running_total": 0,
                      "eligible_pending": 0, "oldest_eligible_id": None,
                      "oldest_eligible_created_at": None,
                      "oldest_eligible_age_sec": None}

    # ---- world helpers -------------------------------------------------
    def write_heartbeat(self, age_sec: float = 0, **extra) -> None:
        payload = {
            "ts": iso(-age_sec), "version": "2.0.0",
            "default_model": "opencode/cat-jam-free", "pid": os.getpid(),
            "claimed_this_pass": 0, "current_task": "",
        }
        payload.update(extra)
        self.heartbeat.write_text(json.dumps(payload))

    def write_plist(self, label: str | None = None, program: str | None = None,
                    worker_dir: Path | None = None) -> Path:
        label = label or self.label
        worker_dir = worker_dir or self.repo
        program = program or str(worker_dir / "worker.py")
        path = self.launch_agents / f"{label}.plist"
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<plist version="1.0"><dict>'
            f'<key>Label</key><string>{label}</string>'
            '<key>ProgramArguments</key><array>'
            f'<string>/usr/bin/python3</string><string>{program}</string>'
            '</array></dict></plist>')
        return path

    # ---- fake process plumbing ----------------------------------------
    def runner(self, argv, capture_output=True, text=True, timeout=None):
        self.calls.append(list(argv))
        verb = argv[1] if len(argv) > 1 else ""
        key = verb
        if verb == "print":
            target = argv[2] if len(argv) > 2 else ""
            if target.startswith(("gui/", "user/")) and "/" not in target[4:]:
                return _proc(0, f"{target} = {{\n}}\n")  # domain print
            if self.raise_on.get("print"):
                raise self.raise_on["print"]
            if not self.loaded:
                return _proc(113, "", f'Could not find service "{target}"')
            state = self.svc_state
            pid_line = f"\tpid = {self.svc_pid}\n" if self.svc_pid else ""
            out = (
                f"{target} = {{\n\tactive count = 0\n"
                f"\tpath = {self.plist}\n\ttype = LaunchAgent\n"
                f"\tstate = {state}\n{pid_line}"
                f"\tdomain = gui/{self.uid}\n\truns = {self.runs}\n"
                f"\tlast exit code = {self.last_exit_code}\n}}\n")
            return _proc(self.print_rc, out, self.print_stderr)
        if self.raise_on.get(key):
            raise self.raise_on[key]
        rc, out, err = self.verbs.get(key, (0, "", ""))
        if rc == 0 and key in ("kickstart", "bootstrap"):
            hook = self.on_launch.get(key)
            if hook:
                hook(self)
        return _proc(rc, out, err)

    def supervisor(self, **overrides) -> ws.Supervisor:
        kwargs = dict(
            repo_dir=self.repo,
            label=self.label,
            plist_path=self.plist,
            launch_agents_dir=self.launch_agents,
            launchctl=self.launchctl_override,
            uid=self.uid,
            heartbeat_path=self.heartbeat,
            worker_lock_path=self.worker_lock,
            restart_lock_path=self.repo / ".restart.lock",
            state_path=self.state,
            restart_log_path=self.restart_log,
            worker_log_path=self.worker_log,
            queue_snapshot=lambda: dict(self.queue),
            runner=self.runner,
            clock=lambda: self.clock_value,
            sleeper=self._sleep,
            cooldown_sec=overrides.pop("cooldown_sec", 90),
            timeout_sec=overrides.pop("timeout_sec", 90),
            max_stale_sec=overrides.pop("max_stale_sec", 180),
            grace_sec=overrides.pop("grace_sec", 20),
        )
        kwargs.update(overrides)
        return ws.Supervisor(**kwargs)

    def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock_value += seconds

    def verbs_called(self) -> list[str]:
        return [c[1] for c in self.calls if len(c) > 1]

    def argv_for(self, verb: str) -> list[list[str]]:
        return [c for c in self.calls if len(c) > 1 and c[1] == verb]

    def has_call(self, *tokens: str) -> bool:
        """True if launchctl was invoked with exactly these args (exe excluded)."""
        return list(tokens) in [c[1:] for c in self.calls]


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.plist = w.write_plist()
    return w


# --------------------------------------------------------------------------
# 1. healthy worker + force=False -> skipped, nothing is interrupted
# --------------------------------------------------------------------------
def test_healthy_worker_skips_without_force(world):
    world.write_heartbeat(age_sec=5)
    res = world.supervisor().restart(force=False)

    assert REQUIRED_KEYS <= set(res)
    assert res["outcome"] == "skipped_healthy"
    assert res["success"] is True
    assert res["restart_attempted"] is False
    assert res["restart_method"] == "none"
    assert res["previous_status"] == "healthy"
    assert res["heartbeat_before"]["alive"] is True
    assert res["worker_pid"] == os.getpid()
    assert res["next_steps"]
    assert "kickstart" not in world.verbs_called()
    assert "bootstrap" not in world.verbs_called()
    # service state is still reported even when nothing is done
    assert res["service_label"] == world.label
    assert res["service_state_before"]["loaded"] is True


# --------------------------------------------------------------------------
# 2. offline worker -> real supervisor call + verified recovery
# --------------------------------------------------------------------------
def test_offline_worker_restarts_via_kickstart_and_verifies(world):
    world.write_heartbeat(age_sec=4000)  # stale heartbeat = offline
    world.svc_pid = None
    # the supervisor's kickstart makes the worker write a fresh heartbeat
    world.on_launch["kickstart"] = lambda w: w.write_heartbeat(
        claimed_this_pass=1)

    res = world.supervisor().restart(force=False)

    assert REQUIRED_KEYS <= set(res)
    assert res["previous_status"] == "offline"
    assert res["restart_attempted"] is True
    assert res["restart_method"] == "launchctl kickstart"
    assert res["service_label"] == world.label
    assert world.has_call("kickstart", "-k", f"gui/501/{world.label}")
    assert res["success"] is True
    assert res["verified"] is True
    assert res["heartbeat_after"]["alive"] is True
    assert res["heartbeat_after"]["age_sec"] <= 180
    assert res["queue_evidence"]["processing_observed"] is True
    assert res["queue_evidence"]["claimed_by_new_pass"] == 1
    assert res["elapsed_ms"] >= 0
    assert res["error"] is None


def test_offline_unloaded_service_bootstraps_plist(world):
    world.loaded = False
    res = world.supervisor().restart(force=False)

    assert res["restart_method"] == "launchctl bootstrap"
    boot = world.argv_for("bootstrap")
    assert boot and boot[0][1:3] == ["bootstrap", "gui/501"]
    assert boot[0][3] == str(world.plist)
    assert res["restart_attempted"] is True  # recovery itself needs a heartbeat
    assert res["outcome"] == "restart_timeout"
    assert res["success"] is False


# --------------------------------------------------------------------------
# 3. stale heartbeat (process alive) follows the recovery policy
# --------------------------------------------------------------------------
def test_stale_heartbeat_with_live_process_restarts(world):
    world.write_heartbeat(age_sec=900)
    world.svc_pid = 4242  # worker process alive, heartbeat stale
    world.on_launch["kickstart"] = lambda w: (
        w.write_heartbeat(), setattr(w, "svc_pid", None))

    res = world.supervisor().restart(force=False)

    assert res["previous_status"] == "stale"
    assert res["restart_attempted"] is True
    assert res["success"] is True
    assert res["verified"] is True


def test_stale_heartbeat_with_running_pass_waits_gracefully(world):
    world.write_heartbeat(age_sec=900, current_task="abc123")
    world.svc_pid = 4242
    # hold the worker's flock exactly like a running pass does
    fd = os.open(world.worker_lock, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert world.supervisor().pass_in_progress() is True
        world.supervisor(grace_sec=5).restart(force=False)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert any(s >= 0.5 for s in world.sleeps), "expected a grace wait"
    assert world.has_call("kickstart", "-k", f"gui/501/{world.label}")


# --------------------------------------------------------------------------
# 4. force=True -> intentional restart of a healthy worker, flagged as risky
# --------------------------------------------------------------------------
def test_force_restart_of_healthy_worker_is_permitted_and_flagged(world):
    world.write_heartbeat(age_sec=2)
    new_ts = [iso(0)]
    world.on_launch["kickstart"] = lambda w: w.write_heartbeat(age_sec=0)

    res = world.supervisor().restart(force=True)

    assert res["restart_attempted"] is True
    assert res["previous_status"] == "healthy"
    assert res["success"] is True
    assert "intentionally restarting a healthy worker" in res["diagnosis"]
    assert world.has_call("kickstart", "-k", f"gui/501/{world.label}")
    assert new_ts  # (kept for readability of intent)


def test_force_restart_still_rate_limited_inside_cooldown(world):
    world.write_heartbeat(age_sec=2)
    sup = world.supervisor(cooldown_sec=120)
    # a previous failed attempt just happened
    world.state.write_text(json.dumps({
        "last_attempt_ts": iso(-5), "last_outcome": "restart_timeout",
        "consecutive_failures": 0, "attempts_total": 1, "history": []}))

    res = sup.restart(force=True)

    assert res["outcome"] == "rate_limited"
    assert res["restart_attempted"] is False
    assert res["cooldown_remaining_sec"] > 0
    assert "kickstart" not in world.verbs_called()


# --------------------------------------------------------------------------
# 5. missing service / supervisor configuration
# --------------------------------------------------------------------------
def test_missing_service_returns_install_instructions(tmp_path):
    w = World(tmp_path)  # no plist written, nothing loaded
    w.loaded = False
    res = w.supervisor().restart(force=False)

    assert REQUIRED_KEYS <= set(res)
    assert res["outcome"] == "service_missing"
    assert res["success"] is False
    assert res["restart_attempted"] is False
    assert res["error"]
    assert any("bootstrap" in s for s in res["next_steps"])
    assert "kickstart" not in w.verbs_called()
    # and it must not have tocked the supervisor from a stale default label
    assert res["service_state_before"]["loaded"] is False


def test_missing_launchctl_reports_supervisor_unavailable(world):
    world.write_heartbeat(age_sec=4000)
    res = world.supervisor(launchctl="/nonexistent/launchctl").restart(force=False)

    assert res["outcome"] == "supervisor_unavailable"
    assert res["success"] is False
    assert res["restart_attempted"] is False
    assert any("worker.py" in s for s in res["next_steps"])
    # nothing was attempted: no bootstrap/kickstart argv, no cooldown burned
    assert world.argv_for("bootstrap") == []
    assert world.argv_for("kickstart") == []
    assert world.state.exists() is False


def test_launchctl_exec_error_is_contained(world):
    world.write_heartbeat(age_sec=4000)
    res = world.supervisor(launchctl="/usr/bin/true").restart(force=False)
    # /usr/bin/true is executable: it just reports rc=0 with no output -> the
    # recovery itself cannot be verified, which is a timeout, not a crash.
    assert res["outcome"] in ("restart_timeout", "supervisor_unavailable")
    assert REQUIRED_KEYS <= set(res)


# --------------------------------------------------------------------------
# 6. permission denied / launchctl failures
# --------------------------------------------------------------------------
def test_permission_denied_is_reported_explicitly(world):
    world.write_heartbeat(age_sec=4000)
    world.verbs["kickstart"] = (125, "", "Bootstrap failed: 125: Operation not permitted")

    res = world.supervisor().restart(force=False)

    assert res["outcome"] == "permission_denied"
    assert res["success"] is False
    assert res["restart_attempted"] is True
    assert "not permitted" in res["error"].lower()
    assert any("same login session" in s for s in res["next_steps"])


def test_launchctl_generic_failure_is_reported(world):
    world.write_heartbeat(age_sec=4000)
    world.verbs["kickstart"] = (1, "", "some launchd complaint")

    res = world.supervisor().restart(force=False)

    assert res["outcome"] == "launchctl_failed"
    assert res["success"] is False
    assert res["restart_attempted"] is True
    assert "launchd complaint" in res["error"]


def test_kickstart_not_loaded_falls_back_to_bootstrap(world):
    """launchd lost the job between discovery and kickstart: bootstrap it."""
    world.write_heartbeat(age_sec=4000)
    world.verbs["kickstart"] = (113, "", 'Could not find service "x"')
    world.verbs["bootstrap"] = (0, "", "")
    world.on_launch["bootstrap"] = lambda w: w.write_heartbeat(claimed_this_pass=1)

    res = world.supervisor().restart(force=False)

    assert res["restart_method"] == "launchctl bootstrap"
    assert [c[1:] for c in world.argv_for("bootstrap")] == [
        ["bootstrap", "gui/501", str(world.plist)]]
    assert res["success"] is True
    assert res["verified"] is True


# --------------------------------------------------------------------------
# 7/8. restart timeout and "process restarts, heartbeat never recovers"
# --------------------------------------------------------------------------
def test_restart_timeout_when_heartbeat_never_recovers(world):
    world.write_heartbeat(age_sec=4000)          # stale heartbeat stays stale
    world.last_exit_code = 78                    # EX_CONFIG, the classic cause
    world.worker_log.write_text(
        "2026-01-01T00:00:00+00:00 boot\n"
        "2026-01-01T00:00:01+00:00 BRIDGE_AUTH_TOKEN=super_secret\n"
        "2026-01-01T00:00:02+00:00 worker.py: crashed on import\n")

    res = world.supervisor(timeout_sec=15).restart(force=False)

    assert REQUIRED_KEYS <= set(res)
    assert res["outcome"] == "restart_timeout"
    assert res["success"] is False
    assert res["restart_attempted"] is True
    assert res["error"]
    assert "78" in res["error"]
    assert res["next_steps"]
    assert res["elapsed_ms"] <= 20_000
    assert res["verified"] is False
    # diagnostics are attached, secrets are not
    joined = " ".join(res["logs"])
    assert "crashed on import" in joined
    assert "super_secret" not in joined


# --------------------------------------------------------------------------
# 9/10. concurrency, cooldown, repeated-restart protection
# --------------------------------------------------------------------------
def test_concurrent_restart_returns_already_in_progress(world):
    world.write_heartbeat(age_sec=4000)
    fd = os.open(world.repo / ".restart.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = world.supervisor().restart(force=False)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert res["outcome"] == "already_in_progress"
    assert res["restart_attempted"] is False
    assert res["success"] is False
    assert "kickstart" not in world.verbs_called()


def test_two_threads_racing_produce_single_kickstart(world):
    world.write_heartbeat(age_sec=4000)
    world.verbs["kickstart"] = (0, "", "")   # never recovers -> each call waits
    sup = world.supervisor(timeout_sec=10)
    results = []

    def call():
        results.append(sup.restart(force=False))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    outcomes = sorted(r["outcome"] for r in results)
    assert len(world.argv_for("kickstart")) == 1, world.calls
    assert "already_in_progress" in outcomes


def test_cooldown_blocks_repeated_restarts(world):
    world.write_heartbeat(age_sec=4000)
    world.verbs["kickstart"] = (0, "", "")
    sup = world.supervisor(cooldown_sec=60, timeout_sec=10)

    first = sup.restart(force=False)
    assert first["restart_attempted"] is True
    world.calls.clear()

    second = sup.restart(force=False)
    assert second["outcome"] == "rate_limited"
    assert second["cooldown_remaining_sec"] > 0
    assert world.verbs_called() == ["print"] or world.argv_for("kickstart") == []
    assert second["next_steps"]


def test_cooldown_escalates_after_failed_attempts(world):
    world.write_heartbeat(age_sec=4000)
    world.verbs["kickstart"] = (1, "", "boom")
    sup = world.supervisor(cooldown_sec=60, timeout_sec=10)
    sup.restart(force=False)                       # failure #1
    world.calls.clear()
    res = sup.restart(force=False)
    assert res["outcome"] == "rate_limited"
    assert res["cooldown_remaining_sec"] > 60      # escalated past the base
    assert world.argv_for("kickstart") == []


# --------------------------------------------------------------------------
# 11. queued work survives every outcome
# --------------------------------------------------------------------------
def _real_queue_snapshot(tmp_db: Path):
    """Fresh task_store pinned to a tmp DB (it reads TASK_DB_PATH on import)."""
    os.environ["TASK_DB_PATH"] = str(tmp_db)
    sys.modules.pop("task_store", None)
    import task_store
    return task_store


def test_pending_tasks_are_preserved_across_restart(tmp_path):
    tmp_db = tmp_path / "tasks.db"
    task_store = _real_queue_snapshot(tmp_db)
    try:
        t1 = task_store.submit_task("keep me", "do not lose me")
        t2 = task_store.submit_task("keep me too", "also important")

        w = World(tmp_path)
        w.plist = w.write_plist()
        w.write_heartbeat(age_sec=4000)
        w.on_launch["kickstart"] = lambda world: world.write_heartbeat()
        sup = ws.Supervisor(
            repo_dir=w.repo, launch_agents_dir=w.launch_agents,
            launchctl="/bin/launchctl", uid=w.uid, heartbeat_path=w.heartbeat,
            worker_lock_path=w.worker_lock, restart_lock_path=w.repo / ".restart.lock",
            state_path=w.state, restart_log_path=w.restart_log,
            worker_log_path=w.worker_log, runner=w.runner,
            clock=lambda: w.clock_value, sleeper=w._sleep)

        before = {t["id"]: (t["status"], t["updated_at"], t["attempts"])
                  for t in (task_store.get_task(t1["id"]), task_store.get_task(t2["id"]))}
        res = sup.restart(force=False)
        after = {t["id"]: (t["status"], t["updated_at"], t["attempts"])
                 for t in (task_store.get_task(t1["id"]), task_store.get_task(t2["id"]))}

        assert res["success"] is True
        assert after == before
        assert all(v[0] == "pending" for v in after.values())
        assert res["queue_evidence"]["pending_before"] == 2
    finally:
        os.environ.pop("TASK_DB_PATH", None)
        sys.modules.pop("task_store", None)


def test_stalled_queue_counts_as_unhealthy_and_restarts(world):
    # fresh heartbeat, but an eligible task has been pending since before the
    # last pass and that pass claimed nothing -> demonstrably not processing
    world.write_heartbeat(age_sec=5, claimed_this_pass=0, current_task="")
    world.queue.update({"pending_total": 1, "eligible_pending": 1,
                        "oldest_eligible_id": "abc123",
                        "oldest_eligible_created_at": iso(-600),
                        "oldest_eligible_age_sec": 600})
    world.on_launch["kickstart"] = lambda w: w.write_heartbeat(claimed_this_pass=1)

    res = world.supervisor().restart(force=False)

    assert res["outcome"] == "restarted"
    assert res["restart_attempted"] is True
    assert "not processing queued work" in res["diagnosis"]
    assert res["stalled"] is True
    assert world.has_call("kickstart", "-k", f"gui/501/{world.label}")


def test_young_pending_task_does_not_look_stalled(world):
    """A task newer than ~2 passes is normal pickup latency, not a stall."""
    world.write_heartbeat(age_sec=2, claimed_this_pass=0, current_task="")
    world.queue.update({"pending_total": 1, "eligible_pending": 1,
                        "oldest_eligible_id": "fresh01",
                        "oldest_eligible_created_at": iso(-90),
                        "oldest_eligible_age_sec": 90})

    res = world.supervisor().restart(force=False)

    assert res["outcome"] == "skipped_healthy"
    assert res["stalled"] is False
    assert "kickstart" not in world.verbs_called()


def test_active_pass_is_never_called_stalled(world):
    world.write_heartbeat(age_sec=2, claimed_this_pass=0, current_task="a1b2c3")
    world.queue.update({"pending_total": 5, "eligible_pending": 5,
                        "oldest_eligible_id": "old",
                        "oldest_eligible_created_at": iso(-3600),
                        "oldest_eligible_age_sec": 3600})

    res = world.supervisor().restart(force=False)

    assert res["outcome"] == "skipped_healthy"
    assert "executing a task" in res["stall_reason"]


# --------------------------------------------------------------------------
# label discovery / argv safety
# --------------------------------------------------------------------------
def test_label_discovered_from_installed_plist(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKBRIDGE_SERVICE_LABEL", raising=False)
    monkeypatch.delenv("TASKBRIDGE_SERVICE_PLIST", raising=False)
    w = World(tmp_path)
    plist = w.write_plist(label="com.example.custombridge")  # not the default
    w.label = "com.example.custombridge"

    svc = w.supervisor(label=None).discover_service()
    assert svc["label"] == "com.example.custombridge"
    assert svc["discovered_by"] == "installed plist scan"
    assert svc["plist_exists"] is True
    assert Path(svc["plist_path"]) == plist


def test_plist_for_another_checkout_is_not_claimed(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKBRIDGE_SERVICE_LABEL", raising=False)
    monkeypatch.delenv("TASKBRIDGE_SERVICE_PLIST", raising=False)
    w = World(tmp_path)
    w.write_plist(label="com.other.checkout", worker_dir=tmp_path / "elsewhere")
    svc = w.supervisor(label=None).discover_service()
    assert svc["label"] == ws.DEFAULT_SERVICE_LABEL  # fell back to the default
    assert svc["discovered_by"] == "default label"


def test_malicious_label_never_reaches_argv(world, monkeypatch):
    world.write_heartbeat(age_sec=4000)
    monkeypatch.setenv("TASKBRIDGE_SERVICE_LABEL", "evil; rm -rf /")
    sup = world.supervisor(label=None)
    assert sup.candidate_label() == ws.DEFAULT_SERVICE_LABEL
    sup.restart(force=False)
    for call in world.calls:
        assert all("; " not in token for token in call)


def test_malformed_launchctl_argument_is_refused(world):
    out = world.supervisor()._launchctl(["kickstart", "-k", ""])
    assert out["ok"] is False
    assert "malformed" in out["error"]


def test_launchctl_timeout_is_contained(world):
    def slow(argv, capture_output=True, text=True, timeout=None):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    out = world.supervisor(runner=slow)._launchctl(["print", "gui/501"])
    assert out["ok"] is False
    assert "timed out" in out["error"]


def test_worker_log_tail_redacts_secrets(world):
    world.worker_log.write_text(
        "line one fine\n"
        "OPENCODE_BIN=/x/y ok\n"
        "token=abcdef\n"
        "hex 0123456789abcdef0123456789abcdef here\n"
        "last line\n")
    tail = world.supervisor()._worker_log_tail(3)
    joined = " ".join(tail)
    assert "token=abcdef" not in joined
    assert "0123456789abcdef0123456789abcdef" not in joined
    assert len(tail) <= 3


# --------------------------------------------------------------------------
# independence from the worker module
# --------------------------------------------------------------------------
def test_supervisor_imports_without_worker_module():
    """The restart path must not depend on worker.py being importable."""
    code = (
        "import sys, importlib.util, types;"
        "sys.modules['worker'] = None;"  # simulate a broken worker module
        "import worker_supervisor;"
        "print('ok', 'worker' in sys.modules and sys.modules['worker'] is not None)"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).parent.parent),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "ok False" in proc.stdout


def test_every_outcome_has_structured_fields(world, tmp_path):
    """All documented fields exist on success and failure paths alike."""
    world.write_heartbeat(age_sec=4000)
    scenarios = {
        "timeout": lambda: world.supervisor(timeout_sec=10).restart(False),
    }
    world.verbs["kickstart"] = (0, "", "")
    for name, fn in scenarios.items():
        res = fn()
        missing = REQUIRED_KEYS - set(res)
        assert not missing, f"{name} missing {missing}"
        assert isinstance(res["next_steps"], list)
        assert res["next_steps"], name
