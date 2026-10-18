"""Shared test guards.

Automated tests must never touch the production worker service. This conftest
points every env-driven supervisor default at a throwaway label/heartbeat, so a
test that accidentally uses the *real* default supervisor fails harmlessly
against a non-existent service instead of restarting the live worker.

Tests that intentionally exercise launchd (tests/test_restart_integration.py)
pass their own disposable label, plist and paths explicitly, so they are
unaffected; the live MCP check documented in launchd/README.md is a manual step.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_ISOLATED_DIR = Path(tempfile.mkdtemp(prefix="taskbridge-test-isolation-"))


@pytest.fixture(autouse=True)
def _never_target_the_real_service(monkeypatch):
    """Force every default supervisor to a test-only, non-existent service."""
    monkeypatch.setenv("TASKBRIDGE_SERVICE_LABEL", "com.taskbridge.test-isolation")
    monkeypatch.setenv("TASKBRIDGE_SERVICE_PLIST",
                       str(_ISOLATED_DIR / "com.taskbridge.test-isolation.plist"))
    monkeypatch.setenv("TASKBRIDGE_HEARTBEAT_PATH", str(_ISOLATED_DIR / "heartbeat.json"))
    monkeypatch.setenv("TASKBRIDGE_RESTART_STATE_PATH", str(_ISOLATED_DIR / "state.json"))
    monkeypatch.setenv("TASKBRIDGE_RESTART_LOCK_PATH", str(_ISOLATED_DIR / "restart.lock"))
    monkeypatch.setenv("TASKBRIDGE_RESTART_LOG_PATH", str(_ISOLATED_DIR / "restart.log"))
    monkeypatch.delenv("TASK_DB_PATH", raising=False)
    yield
