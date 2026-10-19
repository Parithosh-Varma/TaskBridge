"""Variant-agnostic `opencode run` flag handling.

The worker must run on any opencode build: optional flags are only used when
the binary's own help advertises them, and a rejected command (help dump,
nonzero exit) is retried once without them. Everything external is faked —
no real opencode, no task DB, no worker state touched.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import worker  # noqa: E402

REAL_POPEN = subprocess.Popen

HELP_WITH = (
    "opencode run [message..]\n"
    "\n"
    "Options:\n"
    "      --standalone  run in standalone mode\n"
    "      --auto        auto-approve\n"
)
HELP_WITHOUT = (
    "opencode run [message..]\n"
    "\n"
    "Options:\n"
    "      --auto        auto-approve\n"
)


def fake_opencode(tmp_path, help_text="", *, answer_dashhelp=True,
                  answer_help=True, name="fake-opencode"):
    """A stand-in CLI that answers help probes and `models`, nothing else."""
    p = tmp_path / name
    lines = [
        f"#!{sys.executable}",
        "import sys",
        "args = sys.argv[1:]",
        f"HELP = {help_text!r}",
    ]
    if answer_help:
        lines.append("if args[:2] == ['run', '--help'] and HELP:")
        lines.append("    print(HELP)")
        lines.append("    sys.exit(0)")
    if answer_dashhelp:
        lines.append("if args[:2] == ['run', '-h'] and HELP:")
        lines.append("    print(HELP)")
        lines.append("    sys.exit(0)")
    lines.append("if args[:1] == ['models']:")
    lines.append("    print('opencode/deepseek-v4.1-flash-free')")
    lines.append("    sys.exit(0)")
    lines.append("sys.exit(3)")  # everything else: refuse silently
    p.write_text("\n".join(lines) + "\n")
    p.chmod(0o755)
    return p


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "_HELP_CACHE", {})
    monkeypatch.setattr(worker, "_MODEL_CACHE", {"ts": 0.0, "models": frozenset()})
    monkeypatch.setattr(worker, "_MODEL_NOTIFIED", set())
    monkeypatch.setattr(worker, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(worker, "LOG_FILE", tmp_path / "worker.log")
    monkeypatch.setattr(worker, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    monkeypatch.setattr(worker, "CONFIG_PATH", tmp_path / "worker_config.json")
    monkeypatch.setattr(worker, "NOTIFY", False)
    return tmp_path


# ------------------------------------------------------------ flag probing


def test_flags_detected_from_help_stdout(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITH)
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    assert worker.supported_run_flags() == ["--standalone"]


def test_flags_detected_when_help_goes_to_stderr(tmp_path):
    p = tmp_path / "fake-stderr"
    p.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.stderr.write({HELP_WITH!r})\n"
        "sys.exit(0)\n"
    )
    p.chmod(0o755)
    assert worker.supported_run_flags(str(p)) == ["--standalone"]


def test_no_flags_when_help_lacks_them(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITHOUT, name="fake-old")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    assert worker.supported_run_flags() == []


def test_no_flags_when_binary_missing():
    assert worker.supported_run_flags("/nonexistent/opencode-nope") == []


def test_no_flags_when_help_unreadable(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITH, answer_dashhelp=False,
                         answer_help=False, name="fake-mute")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    assert worker.supported_run_flags() == []


def test_dash_h_fallback_when_dashdash_help_is_dead(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITH, answer_help=False, name="fake-only-h")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    assert worker.supported_run_flags() == ["--standalone"]


def test_help_probe_cached_per_binary(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITH, name="fake-cache")
    calls = []
    real_run = subprocess.run

    def counting_run(argv, **kwargs):
        calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(worker.subprocess, "run", counting_run)
    assert worker.supported_run_flags(str(binp)) == ["--standalone"]
    assert worker.supported_run_flags(str(binp)) == ["--standalone"]
    assert len(calls) == 1


# ----------------------------------------------------- run_task flag usage


class ArgvRecorder:
    """Serves real `run` invocations: records argv, then emulates a variant
    that either succeeds (`done`), fails plainly, or rejects `--standalone`
    with a usage dump (the bug this file guards). Help/models probes pass
    through to the real fake CLI."""

    def __init__(self, binp, *, reject_standalone=False, fail=False):
        self.binp = str(binp)
        self.reject_standalone = reject_standalone
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        is_real_run = (len(argv) > 2 and argv[0] == self.binp and argv[1] == "run"
                       and "--help" not in argv and "-h" not in argv)
        if not is_real_run:
            return REAL_POPEN(argv, **kwargs)
        self.calls.append(list(argv))
        if self.reject_standalone and "--standalone" in argv:
            code = ("import sys; print('opencode run [message..]'); "
                    "print('Options:'); sys.exit(1)")
        elif self.fail:
            code = "import sys; print('boom: it broke'); sys.exit(1)"
        else:
            code = "print('done')"
        return REAL_POPEN([sys.executable, "-c", code], **kwargs)


def _task(tmp_path):
    return {
        "id": "tstandalone",
        "title": "probe the flag",
        "instructions": "say hi",
        "_cwd": str(tmp_path),
        "permission": "full",
    }


def test_run_task_omits_flags_when_unsupported(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITHOUT, name="fake-old")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    rec = ArgvRecorder(binp)
    monkeypatch.setattr(worker.subprocess, "Popen", rec)

    out = worker.run_task(_task(tmp_path), [], attempt_no=0)

    assert out["ok"] is True, out
    argv = rec.calls[0]
    assert argv[:2] == [str(binp), "run"]
    assert "--standalone" not in argv
    assert "--auto" in argv and "--title" in argv


def test_run_task_keeps_flags_when_supported(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, HELP_WITH, name="fake-new")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    rec = ArgvRecorder(binp)
    monkeypatch.setattr(worker.subprocess, "Popen", rec)

    out = worker.run_task(_task(tmp_path), [], attempt_no=0)

    assert out["ok"] is True, out
    assert rec.calls[0][:3] == [str(binp), "run", "--standalone"]


def test_run_task_retries_once_without_rejected_flag(tmp_path, monkeypatch):
    """Variant advertises --standalone but rejects it at run time: the task
    must still succeed via the one-shot retry without the flag."""
    binp = fake_opencode(tmp_path, HELP_WITH, name="fake-liar")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    rec = ArgvRecorder(binp, reject_standalone=True)
    monkeypatch.setattr(worker.subprocess, "Popen", rec)

    out = worker.run_task(_task(tmp_path), [], attempt_no=0)

    assert out["ok"] is True, out
    assert len(rec.calls) == 2, rec.calls
    assert "--standalone" in rec.calls[0]
    assert "--standalone" not in rec.calls[1]
    assert "retrying without --standalone" in (tmp_path / "tstandalone.log").read_text()


def test_run_task_does_not_retry_plain_failures(tmp_path, monkeypatch):
    """A real failure (nonzero exit, no usage dump) must not be double-run."""
    binp = fake_opencode(tmp_path, HELP_WITH, name="fake-fail")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    rec = ArgvRecorder(binp, fail=True)
    monkeypatch.setattr(worker.subprocess, "Popen", rec)

    out = worker.run_task(_task(tmp_path), [], attempt_no=0)

    assert out["ok"] is False
    assert "boom" in out["error"]
    assert len(rec.calls) == 1, rec.calls
