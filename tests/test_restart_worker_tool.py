"""MCP-surface tests for the restart_worker tool.

These verify the tool is discoverable, keeps its documented schema, never
blocks the MCP event loop, delegates to the supervisor, and always answers with
a structured JSON-serializable result — including when the supervisor explodes.
The supervisor itself is faked here; worker_supervisor has its own test file.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import opencode_bridge_mcp as bridge  # noqa: E402
import worker_supervisor  # noqa: E402

FALLBACK_KEYS = {
    "success", "previous_status", "restart_attempted", "restart_method",
    "service_label", "heartbeat_before", "heartbeat_after", "worker_pid",
    "elapsed_ms", "error", "next_steps",
}


def tools_by_name() -> dict:
    return {t.name: t for t in bridge.mcp._tool_manager.list_tools()}


def call_tool(name: str, arguments: dict):
    return asyncio.run(bridge.mcp._tool_manager.call_tool(name, arguments))


class FakeSupervisor:
    def __init__(self, result=None, exc=None):
        self.result = result or {}
        self.exc = exc
        self.calls: list[dict] = []

    def restart(self, force=False, timeout_sec=None):
        self.calls.append({"force": force, "timeout_sec": timeout_sec})
        if self.exc:
            raise self.exc
        return self.result


def ok_result(**over):
    base = {
        "success": True, "previous_status": "stale", "restart_attempted": True,
        "restart_method": "launchctl kickstart",
        "service_label": "com.taskbridge.worker",
        "heartbeat_before": {"alive": False, "age_sec": 900},
        "heartbeat_after": {"alive": True, "age_sec": 3},
        "worker_pid": 1234, "elapsed_ms": 4200, "error": None,
        "next_steps": ["Worker restarted and verified with a fresh heartbeat."],
        "outcome": "restarted",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# registration + schema discovery
# --------------------------------------------------------------------------
def test_restart_worker_is_registered():
    tools = tools_by_name()
    assert "restart_worker" in tools
    assert "worker_heartbeat" in tools and "queue_status" in tools  # siblings intact


def test_tool_schema_matches_documented_interface():
    tool = tools_by_name()["restart_worker"]
    schema = tool.parameters
    props = schema["properties"]

    assert props["force"]["type"] == "boolean"
    assert props["force"].get("default") is False
    assert props["timeout_sec"]["type"] == "integer"
    assert props["timeout_sec"].get("default") == 90
    assert schema.get("required", []) == []          # both args optional
    assert "restart" in tool.description.lower()
    assert "worker" in tool.description.lower()


def test_tool_is_async_so_it_cannot_block_the_mcp_loop():
    tool = tools_by_name()["restart_worker"]
    assert tool.is_async is True
    assert inspect.iscoroutinefunction(tool.fn)


# --------------------------------------------------------------------------
# delegation + structured answers
# --------------------------------------------------------------------------
def test_tool_delegates_to_supervisor(monkeypatch):
    fake = FakeSupervisor(result=ok_result())
    monkeypatch.setattr(worker_supervisor, "default_supervisor", lambda: fake)

    res = call_tool("restart_worker", {"force": True, "timeout_sec": 30})

    assert res["outcome"] == "restarted"
    assert fake.calls == [{"force": True, "timeout_sec": 30}]
    json.dumps(res)  # MCP results must be JSON-serializable


def test_tool_defaults_are_applied(monkeypatch):
    fake = FakeSupervisor(result=ok_result(outcome="skipped_healthy",
                                           restart_attempted=False))
    monkeypatch.setattr(worker_supervisor, "default_supervisor", lambda: fake)

    res = call_tool("restart_worker", {})

    assert fake.calls[0]["force"] is False
    assert fake.calls[0]["timeout_sec"] == 90
    assert res["outcome"] == "skipped_healthy"
    assert res["restart_attempted"] is False


def test_supervisor_exception_becomes_structured_failure(monkeypatch):
    fake = FakeSupervisor(exc=RuntimeError("kaboom"))
    monkeypatch.setattr(worker_supervisor, "default_supervisor", lambda: fake)

    res = call_tool("restart_worker", {"force": False})

    assert FALLBACK_KEYS <= set(res)
    assert res["success"] is False
    assert res["restart_attempted"] is False
    assert "kaboom" in res["error"]
    assert res["next_steps"]
    json.dumps(res)


def test_failure_result_keeps_all_documented_fields(monkeypatch):
    fake = FakeSupervisor(result={
        "success": False, "previous_status": "unknown",
        "restart_attempted": False, "restart_method": "none",
        "service_label": None, "heartbeat_before": None, "heartbeat_after": None,
        "worker_pid": None, "elapsed_ms": 3, "error": "boom",
        "next_steps": ["check logs"], "outcome": "launchctl_failed"})
    monkeypatch.setattr(worker_supervisor, "default_supervisor", lambda: fake)

    res = call_tool("restart_worker", {})
    assert FALLBACK_KEYS <= set(res)
    assert res["error"] == "boom"


# --------------------------------------------------------------------------
# the real supervisor, fake launchd: tool -> supervisor -> launchctl argv
# --------------------------------------------------------------------------
def test_tool_patch_survives_module_reimport():
    """Regression: a re-imported worker_supervisor must still reach the patch.

    The tool does `import worker_supervisor` at call time, so tests must patch
    the module object that is live in sys.modules — an earlier version of this
    suite patched a stale module object and the tool silently fell through to
    the production supervisor.
    """
    import importlib
    module = importlib.import_module("worker_supervisor")
    sys.modules.pop("worker_supervisor", None)
    fresh = importlib.import_module("worker_supervisor")
    assert fresh is not module  # a genuinely new module object

    fake = FakeSupervisor(result=ok_result(outcome="skipped_healthy",
                                           restart_attempted=False))
    original = fresh.default_supervisor
    fresh.default_supervisor = lambda: fake
    try:
        res = call_tool("restart_worker", {})
    finally:
        fresh.default_supervisor = original
        sys.modules["worker_supervisor"] = module

    assert res["outcome"] == "skipped_healthy"
    assert fake.calls == [{"force": False, "timeout_sec": 90}]


def test_tool_end_to_end_with_fake_launchd(tmp_path, monkeypatch):
    from test_worker_supervisor import World  # reuse the fake launchd world

    world = World(tmp_path)
    world.plist = world.write_plist()
    world.write_heartbeat(age_sec=5000)
    world.on_launch["kickstart"] = lambda w: w.write_heartbeat(claimed_this_pass=1)
    monkeypatch.setattr(worker_supervisor, "default_supervisor",
                        lambda: world.supervisor())

    res = call_tool("restart_worker", {"force": False, "timeout_sec": 25})

    assert res["success"] is True
    assert res["outcome"] == "restarted"
    assert res["service_label"] == world.label
    assert world.has_call("kickstart", "-k", f"gui/501/{world.label}")
    json.dumps(res)


# --------------------------------------------------------------------------
# operator CLI stays usable when the MCP server itself is down
# --------------------------------------------------------------------------
def test_cli_supervisor_status_reports_json(tmp_path):
    env = dict(os.environ)
    env.update({
        "TASKBRIDGE_SERVICE_LABEL": "com.example.notinstalled",
        "TASKBRIDGE_HEARTBEAT_PATH": str(tmp_path / "heartbeat.json"),
        "TASKBRIDGE_SERVICE_PLIST": str(tmp_path / "missing.plist"),
    })
    env.pop("TASKBRIDGE_LAUNCHCTL", None)
    proc = subprocess.run(
        [sys.executable, str(REPO / "tasks_cli.py"), "supervisor-status"],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "offline"
    assert data["service"]["loaded"] is False
    assert "cooldown_remaining_sec" in data
