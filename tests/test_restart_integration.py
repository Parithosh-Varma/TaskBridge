"""Real-launchd integration test with a *disposable* probe worker.

Opt-in (never runs in CI or during a normal test run):

    TASKBRIDGE_RUN_LAUNCHD_E2E=1 .venv/bin/python -m pytest tests/test_restart_integration.py -q

It talks to the real ``launchctl`` but only ever touches its own probe job
(unique label per run, plist kept in a tmp dir, bootstrapped by path). The
production worker LabelAgent, the real heartbeat and the real task DB are never
touched — the supervisor is pointed at the probe's tmp paths and a tmp queue.

What it proves end to end: an "offline" worker (job loaded, heartbeat stale) is
restarted through the real supervisor, a *fresh* heartbeat appears, a healthy
probe is left alone without force, and an intentionally forced restart replaces
the live process (SIGTERM path). Cleanup always boots the probe out.
"""
from __future__ import annotations

import json
import os
import plistlib
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import worker_supervisor as ws  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.environ.get("TASKBRIDGE_RUN_LAUNCHD_E2E"),
    reason="set TASKBRIDGE_RUN_LAUNCHD_E2E=1 to exercise real launchd")

PROBE = '''\
import json, os, signal, sys, time
from datetime import datetime, timezone
from pathlib import Path

state_dir = Path(sys.argv[1])
heartbeat, pidfile = state_dir / "heartbeat.json", state_dir / "probe.pid"
pidfile.write_text(str(os.getpid()))
heartbeat.write_text(json.dumps({
    "ts": datetime.now(timezone.utc).isoformat(),
    "version": "probe-1.0", "default_model": "-",
    "pid": os.getpid(), "claimed_this_pass": 0, "current_task": "",
}))
stop = False

def _term(_sig, _frm):
    global stop
    stop = True

signal.signal(signal.SIGTERM, _term)
while not stop:
    time.sleep(0.2)
'''


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True,
                          timeout=30)


def _require_macos() -> None:
    if platform.system() != "Darwin":
        pytest.skip("launchd integration test is macOS-only")


@pytest.fixture
def probe(tmp_path):
    _require_macos()
    if not os.access("/bin/launchctl", os.X_OK):
        pytest.skip("launchctl unavailable")

    label = f"com.taskbridge.probe.{os.getpid()}"
    domain = f"gui/{os.getuid()}"
    heartbeat = tmp_path / "heartbeat.json"
    plist = tmp_path / f"{label}.plist"
    plist.write_bytes(plistlib.dumps({
        "Label": label,
        "ProgramArguments": [sys.executable, "-c", PROBE, str(tmp_path)],
        "StartInterval": 60,
        "RunAtLoad": True,   # mirrors the real worker plist: start on bootstrap
        "StandardOutPath": str(tmp_path / "probe.log"),
        "StandardErrorPath": str(tmp_path / "probe.log"),
    }))

    yield {"label": label, "domain": domain, "plist": plist, "dir": tmp_path,
           "heartbeat": heartbeat}
    _launchctl("bootout", f"{domain}/{label}")
    time.sleep(0.3)


def _supervisor(probe, tmp_path, queue=None):
    return ws.Supervisor(
        repo_dir=tmp_path,
        label=probe["label"],
        plist_path=probe["plist"],
        heartbeat_path=probe["heartbeat"],
        worker_lock_path=tmp_path / ".worker.lock",
        restart_lock_path=tmp_path / ".restart.lock",
        state_path=tmp_path / ".restart_state.json",
        restart_log_path=tmp_path / "restart.log",
        worker_log_path=tmp_path / "worker.launchd.log",
        cooldown_sec=5,
        timeout_sec=60,
        queue_snapshot=queue or (lambda: {"ok": True, "pending_total": 0,
                                          "eligible_pending": 0}),
    )


def test_real_launchd_offline_to_recovered(probe, tmp_path):
    """No heartbeat + not loaded -> bootstrap -> fresh heartbeat, then skip."""
    sup = _supervisor(probe, tmp_path)

    res = sup.restart(force=False)
    assert res["service_label"] == probe["label"]
    assert res["previous_status"] == "offline"
    assert res["restart_method"] == "launchctl bootstrap"
    assert res["success"] is True, res
    assert res["verified"] is True
    assert res["heartbeat_after"]["alive"] is True
    hb = json.loads(probe["heartbeat"].read_text())
    assert hb["version"] == "probe-1.0"

    # healthy again: a second non-forced call must leave the probe alone
    probe_pid = int((probe["dir"] / "probe.pid").read_text())
    res2 = sup.restart(force=False)
    assert res2["outcome"] == "skipped_healthy"
    assert res2["restart_attempted"] is False
    assert int((probe["dir"] / "probe.pid").read_text()) == probe_pid


def _age_heartbeat(probe):
    hb = json.loads(probe["heartbeat"].read_text())
    hb["ts"] = "2020-01-01T00:00:00+00:00"
    probe["heartbeat"].write_text(json.dumps(hb))


def _clear_cooldown(tmp_path):
    """Cooldown is a real safeguard — a test phase must step over it explicitly."""
    (tmp_path / ".restart_state.json").unlink(missing_ok=True)


def test_real_launchd_stale_then_forced_restart(probe, tmp_path):
    """Live process with a stale heartbeat: kickstart -k replaces it (SIGTERM)."""
    sup = _supervisor(probe, tmp_path)
    assert sup.restart(force=False)["success"] is True          # bring it up
    pid_before = int((probe["dir"] / "probe.pid").read_text())

    # age the heartbeat so the worker looks stale while the process lives on
    _age_heartbeat(probe)
    _clear_cooldown(tmp_path)

    res = sup.restart(force=False)
    assert res["previous_status"] == "stale"
    assert res["restart_method"] == "launchctl kickstart"
    assert res["success"] is True, res
    pid_after = int((probe["dir"] / "probe.pid").read_text())
    assert pid_after != pid_before, "kickstart -k must have replaced the process"

    # job loaded but dead (the most common real outage): kill it, then recover
    assert _launchctl("kill", "SIGKILL", f"{probe['domain']}/{probe['label']}").returncode == 0
    _age_heartbeat(probe)
    _clear_cooldown(tmp_path)
    res_dead = sup.restart(force=False)
    assert res_dead["restart_method"] == "launchctl kickstart"
    assert res_dead["success"] is True, res_dead
    assert int((probe["dir"] / "probe.pid").read_text()) != pid_after

    # and the forced path works on a healthy probe too
    _clear_cooldown(tmp_path)
    res_force = sup.restart(force=True)
    assert res_force["restart_attempted"] is True
    assert res_force["success"] is True, res_force
    assert "intentionally restarting" in res_force["diagnosis"]


def test_real_launchd_recovers_with_pending_tasks_untouched(probe, tmp_path):
    """A queued task in a real (tmp) DB is byte-identical after recovery."""
    db_path = tmp_path / "tasks.db"
    os.environ["TASK_DB_PATH"] = str(db_path)
    sys.modules.pop("task_store", None)
    try:
        import task_store
        task = task_store.submit_task("probe task", "must survive a restart")
        before = task_store.get_task(task["id"])

        sup = ws.Supervisor(
            repo_dir=tmp_path, label=probe["label"], plist_path=probe["plist"],
            heartbeat_path=probe["heartbeat"],
            worker_lock_path=tmp_path / ".worker.lock",
            restart_lock_path=tmp_path / ".restart.lock",
            state_path=tmp_path / ".restart_state.json",
            restart_log_path=tmp_path / "restart.log",
            cooldown_sec=5, timeout_sec=60)
        probe["heartbeat"].unlink(missing_ok=True)
        res = sup.restart(force=False)
        after = task_store.get_task(task["id"])

        assert res["success"] is True, res
        assert after["status"] == "pending"
        assert after["updated_at"] == before["updated_at"]
        assert res["queue_evidence"]["pending_before"] == 1
    finally:
        os.environ.pop("TASK_DB_PATH", None)
        sys.modules.pop("task_store", None)
