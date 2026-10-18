"""Tests for the non-launchd (process loop) worker backend.

These exercise the Linux/Cloud-Shell path: when no launchctl is available the
supervisor starts a detached ``worker_supervisor.py --daemon`` loop instead of
a LaunchAgent. Everything external is faked — no real process is spawned and no
real worker or task DB is touched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
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


@pytest.fixture(autouse=True)
def force_process_backend(monkeypatch):
    monkeypatch.setenv("TASKBRIDGE_SUPERVISOR_BACKEND", "process")


def _write_heartbeat(path: Path, pid: int = 4242, age_sec: float = 0) -> None:
    ts = datetime.now(timezone.utc).timestamp() - age_sec
    path.write_text(json.dumps({
        "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
        "version": "2.0.0", "pid": pid, "claimed_this_pass": 0, "current_task": "",
    }))


class Spawn:
    """Fake Popen: records argv and (unless failing) writes a heartbeat."""

    def __init__(self, heartbeat: Path, pid: int = 4242, fail: bool = False):
        self.heartbeat = heartbeat
        self.pid = pid
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.fail:
            raise OSError("spawn exploded")
        _write_heartbeat(self.heartbeat, pid=self.pid)
        return SimpleNamespace(pid=self.pid)


def make(tmp_path: Path, **over) -> ws.Supervisor:
    heartbeat = tmp_path / "heartbeat.json"
    kwargs = dict(
        repo_dir=tmp_path,
        heartbeat_path=heartbeat,
        worker_lock_path=tmp_path / ".worker.lock",
        restart_lock_path=tmp_path / ".restart.lock",
        state_path=tmp_path / ".restart_state.json",
        restart_log_path=tmp_path / "restart.log",
        worker_log_path=tmp_path / "worker.log",
        daemon_pid_path=tmp_path / ".worker_daemon.pid",
        daemon_log_path=tmp_path / "worker.daemon.log",
        queue_snapshot=lambda: {"ok": True, "pending_total": 0, "eligible_pending": 0,
                                "counts": {"pending": 0, "running": 0}},
        cooldown_sec=90, timeout_sec=10, max_stale_sec=180, grace_sec=0,
    )
    kwargs.update(over)
    return ws.Supervisor(**kwargs)


def test_backend_is_process_without_launchctl(tmp_path):
    assert make(tmp_path).backend() == "process"


def test_offline_worker_starts_loop_and_verifies(tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    spawn = Spawn(heartbeat)
    res = make(tmp_path, spawner=spawn).restart(force=False)

    assert REQUIRED_KEYS <= set(res)
    assert res["outcome"] == "restarted"
    assert res["success"] is True
    assert res["restart_method"] == "process loop"
    assert spawn.calls, "the process loop was never spawned"
    assert "--daemon" in spawn.calls[0]
    assert (tmp_path / ".worker_daemon.pid").read_text().strip() == "4242"
    assert res["worker_pid"] == 4242


def test_healthy_worker_skips_without_spawning(tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    _write_heartbeat(heartbeat, age_sec=5)
    spawn = Spawn(heartbeat)
    res = make(tmp_path, spawner=spawn).restart(force=False)

    assert res["outcome"] == "skipped_healthy"
    assert res["restart_attempted"] is False
    assert spawn.calls == []


def test_spawn_failure_is_reported(tmp_path):
    spawn = Spawn(tmp_path / "heartbeat.json", fail=True)
    res = make(tmp_path, spawner=spawn).restart(force=False)

    assert res["outcome"] == "spawn_failed"
    assert res["success"] is False
    assert res["restart_attempted"] is True
    assert any("worker loop" in s or "process loop" in s or "worker.py" in s
               for s in res["next_steps"])


def test_ensure_started_starts_then_reports_already_running(tmp_path, monkeypatch):
    heartbeat = tmp_path / "heartbeat.json"
    spawn = Spawn(heartbeat)
    sup = make(tmp_path, spawner=spawn)
    monkeypatch.setattr(ws, "default_supervisor", lambda: sup)

    first = ws.ensure_started()
    assert first["outcome"] == "started"
    assert first["success"] is True

    # a live loop (pid 1 always exists) is reported without a second spawn
    (tmp_path / ".worker_daemon.pid").write_text("1")
    calls_before = len(spawn.calls)
    second = ws.ensure_started()
    assert second["outcome"] == "already_running"
    assert len(spawn.calls) == calls_before


def test_daemon_alive_and_stop(tmp_path):
    sup = make(tmp_path)
    assert sup.daemon_alive() is False

    # a real, harmless process in its own session stands in for the loop
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    try:
        (tmp_path / ".worker_daemon.pid").write_text(str(proc.pid))
        assert sup.daemon_alive() is True
        sup._stop_process_loop()
        assert sup.daemon_alive() is False
        assert not (tmp_path / ".worker_daemon.pid").exists()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
