"""Regression tests for the stray-process sweep.

Two TaskBridge checkouts can run workers on the same host. The ``--title``
marker must be namespaced per checkout, and the sweep must never kill a process
whose task id is absent from this checkout's queue — otherwise one clone's
worker SIGKILLs the other clone's live ``opencode`` run (a false "failed").
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import worker  # noqa: E402


def _marker(tid: str = "abcdef123456", attempt: int = 1) -> str:
    return f"opencode run --title {worker.TITLE_PREFIX}{tid}-a{attempt} --auto"


def test_title_marker_is_namespaced_per_checkout():
    marker = worker._title_marker("abcdef123456", 2)
    assert marker == f"{worker.TITLE_PREFIX}abcdef123456-a2"
    assert worker.REPO_TAG in worker.TITLE_PREFIX
    assert worker.TITLE_PREFIX != "br-"
    pat = re.compile(rf"{re.escape(worker.TITLE_PREFIX)}([0-9a-f]{{12}})-a\d+")
    assert pat.search(marker)
    # another checkout's marker (different tag) must not match ours
    foreign = "br-deadbeef-abcdef123456-a1"
    assert not pat.search(foreign)


def test_foreign_checkout_processes_are_not_swept(monkeypatch):
    procs = [(111, 1, "opencode run --title br-deadbeef-abcdef123456-a1 --auto")]
    monkeypatch.setattr(worker, "_ps_snapshot", lambda: procs)
    killed: list[int] = []
    monkeypatch.setattr(worker, "_kill_tree",
                        lambda pid: killed.append(pid) or (1, True))

    assert worker._sweep_tagged_strays() == 0
    assert killed == []


def test_missing_task_is_never_killed(monkeypatch):
    tid = "abcdef123456"
    procs = [(111, 1, _marker(tid))]
    monkeypatch.setattr(worker, "_ps_snapshot", lambda: procs)

    def _missing(_tid):
        raise KeyError(_tid)

    monkeypatch.setattr(worker.task_store, "get_task", _missing)
    killed: list[int] = []
    monkeypatch.setattr(worker, "_kill_tree",
                        lambda pid: killed.append(pid) or (1, True))

    assert worker._sweep_tagged_strays() == 0
    assert killed == []


def test_known_nonrunning_task_is_swept(monkeypatch):
    tid = "abcdef123456"
    raw = _marker(tid)
    monkeypatch.setattr(worker, "_ps_snapshot", lambda: [(111, 1, raw)])
    monkeypatch.setattr(worker.task_store, "get_task",
                        lambda _tid: {"status": "failed"})

    class _Proc:
        returncode = 0
        stdout = raw

    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: _Proc())
    killed: list[int] = []
    monkeypatch.setattr(worker, "_kill_tree",
                        lambda pid: killed.append(pid) or (1, True))

    assert worker._sweep_tagged_strays() == 1
    assert killed == [111]
