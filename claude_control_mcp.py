#!/usr/bin/env python3
"""MCP server that lets THIS OpenCode agent control Claude (reverse bridge).

Tools:
  claude_ask      sync Q&A / task, waits up to timeout_sec
  claude_submit   launch a long task in the background -> job_id
  claude_poll     check job status + output tail
  claude_result   full output once done
  claude_cancel   kill a running job
  claude_status   backend health (what auth works)

Backends (auto, in order):
  1. anthropic-api — if ANTHROPIC_API_KEY is set (most reliable)
  2. claude-cli   — `claude -p` with a clean settings file + scrubbed env,
                    so the dead local-router config in ~/.claude/settings.json
                    is bypassed without touching it. Needs `claude login` once.

permission_mode:
  "auto"     — headless, no approval prompts (CLI passes
               --dangerously-skip-permissions). Claude can edit/run.
  "readonly" — CLI restricted to Read/Glob/Grep/WebFetch/WebSearch.
               API backend is inherently readonly (no tools).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).parent
CLEAN_SETTINGS = HERE / "claude-clean.settings.json"
JOBS_DIR = HERE / "claude_jobs"
JOBS_DIR.mkdir(exist_ok=True)

DEFAULT_TIMEOUT = 300
MAX_OUT = 20000
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
API_MODEL = os.environ.get("CLAUDE_API_MODEL", "claude-sonnet-4-5")

# Router/proxy leftovers that must not leak into the CLI backend.
_SCRUB_PREFIXES = ("ANTHROPIC_", "CLAUDE_", "CCR_", "CODEXL_")

# Shadow HOME so `claude -p` never sees the user's router-injected
# ~/.claude/settings.json (which points at a dead local proxy). Only the
# login credential is shared (symlinked); the user's real config is untouched.
SHADOW_HOME = Path(os.environ.get("CLAUDE_MCP_HOME", Path.home() / ".claude-mcp"))


def _shadow_home() -> Path:
    dot = SHADOW_HOME / ".claude"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "settings.json").write_text("{}\n")
    cred, link = Path.home() / ".claude" / ".credentials.json", dot / ".credentials.json"
    if link.is_symlink() or link.exists():
        link.unlink()
    try:
        link.symlink_to(cred)
    except OSError:
        pass
    return SHADOW_HOME


def _scrub_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(_SCRUB_PREFIXES)}
    if "ANTHROPIC_API_KEY" in os.environ:
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    env["HOME"] = str(_shadow_home())
    return env


def _job_paths(job_id: str) -> tuple[Path, Path]:
    return JOBS_DIR / f"{job_id}.json", JOBS_DIR / f"{job_id}.out"


def _read_job(job_id: str) -> dict:
    meta, _ = _job_paths(job_id)
    if not meta.exists():
        raise KeyError(f"job not found: {job_id}")
    return json.loads(meta.read_text())


def _write_job(job_id: str, data: dict) -> None:
    meta, _ = _job_paths(job_id)
    meta.write_text(json.dumps(data, indent=2))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _api_ask(prompt: str, timeout: int) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    body = json.dumps({
        "model": API_MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": API_VERSION,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(texts).strip() or "(empty response)"


def _cli_cmd(prompt: str, permission_mode: str, model: str) -> list[str]:
    cmd = ["claude", "-p", "--output-format", "text",
           "--settings", str(CLEAN_SETTINGS)]
    if model:
        cmd += ["--model", model]
    if permission_mode == "readonly":
        cmd += ["--allowedTools", "Read Glob Grep WebFetch WebSearch"]
    elif permission_mode == "auto":
        cmd += ["--dangerously-skip-permissions"]
    else:
        raise ValueError("permission_mode must be 'auto' or 'readonly'")
    cmd.append(prompt)
    return cmd


def _cli_ask(prompt: str, working_dir: str, timeout: int,
             permission_mode: str, model: str) -> str:
    workdir = working_dir or str(HERE)
    if not os.path.isdir(workdir):
        raise ValueError(f"working_dir does not exist: {workdir}")
    try:
        proc = subprocess.run(
            _cli_cmd(prompt, permission_mode, model),
            cwd=workdir, capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL, env=_scrub_env(),
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"claude did not answer within {timeout}s")
    out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
    if proc.returncode != 0:
        hint = ""
        if "login" in err.lower() or "auth" in err.lower() or "credit" in err.lower():
            hint = " (setup needed: run `claude login`, or set ANTHROPIC_API_KEY for the API backend)"
        raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {(err or out)[-800:]}{hint}")
    return out[:MAX_OUT] or "(empty response)"


def ask(prompt: str, working_dir: str = "", timeout_sec: int = DEFAULT_TIMEOUT,
        permission_mode: str = "auto", model: str = "") -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    timeout_sec = max(10, min(int(timeout_sec or DEFAULT_TIMEOUT), 1800))
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"backend": "anthropic-api", "model": API_MODEL,
                "output": _api_ask(prompt, timeout_sec)[:MAX_OUT]}
    return {"backend": "claude-cli",
            "output": _cli_ask(prompt, working_dir, timeout_sec, permission_mode, model)}


mcp = FastMCP("claude-control")


@mcp.tool()
def claude_ask(prompt: str, working_dir: str = "", timeout_sec: int = 300,
               permission_mode: str = "auto", model: str = "") -> dict:
    """Ask Claude something (or hand it a task) and wait for the answer.

    Args:
        prompt: The question/task. Be explicit; the reply is the result.
        working_dir: Directory Claude works in (default: this project).
        timeout_sec: Max wait (10-1800). Use claude_submit for longer jobs.
        permission_mode: 'auto' (Claude can edit/run, no prompts) or
            'readonly' (read/search only).
        model: CLI model override, e.g. 'sonnet'. Empty = default.
    """
    return ask(prompt, working_dir, timeout_sec, permission_mode, model)


@mcp.tool()
def claude_submit(prompt: str, working_dir: str = "",
                  permission_mode: str = "auto", model: str = "") -> dict:
    """Launch Claude on a long task in the background. Returns job_id.

    Poll with claude_poll, fetch with claude_result, stop with claude_cancel.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    workdir = working_dir or str(HERE)
    if not os.path.isdir(workdir):
        raise ValueError(f"working_dir does not exist: {workdir}")
    job_id = uuid.uuid4().hex[:12]
    _, out_path = _job_paths(job_id)
    use_api = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_api:
        # API jobs run via a tiny inline python worker (no CLI needed)
        runner = [sys.executable, "-c",
                  "import sys,urllib.request,json; "
                  f"prompt={prompt!r}; "
                  "body=json.dumps({'model':" + repr(API_MODEL) + ",'max_tokens':8192,"
                  "'messages':[{'role':'user','content':prompt}]}).encode(); "
                  "req=urllib.request.Request(" + repr(API_URL) + ",data=body,method='POST',"
                  "headers={'content-type':'application/json','x-api-key':"
                  "__import__('os').environ['ANTHROPIC_API_KEY'],"
                  "'anthropic-version':" + repr(API_VERSION) + "}); "
                  "d=json.loads(urllib.request.urlopen(req,timeout=1500).read()); "
                  "print('\\n'.join(b.get('text','') for b in d.get('content',[]) if b.get('type')=='text'))"]
        env: dict | None = dict(os.environ)
    else:
        runner = _cli_cmd(prompt, permission_mode, model)
        env = _scrub_env()
    with open(out_path, "w") as f:
        proc = subprocess.Popen(
            runner, cwd=workdir, stdout=f, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    _write_job(job_id, {"id": job_id, "prompt": prompt[:500],
                        "working_dir": workdir, "backend": "anthropic-api" if use_api else "claude-cli",
                        "pid": proc.pid, "status": "running",
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return {"job_id": job_id, "status": "running",
            "_hint": "Poll claude_poll(job_id), then claude_result(job_id) when done."}


def _refresh(job_id: str) -> dict:
    job = _read_job(job_id)
    if job["status"] == "running" and not _alive(job["pid"]):
        job["status"] = "done"
        _write_job(job_id, job)
    return job


@mcp.tool()
def claude_poll(job_id: str, tail_chars: int = 4000) -> dict:
    """Check a background Claude job: status plus the tail of its output so far."""
    job = _refresh(job_id)
    _, out_path = _job_paths(job_id)
    tail = out_path.read_text()[-max(100, min(tail_chars, MAX_OUT)):] if out_path.exists() else ""
    return {"job_id": job_id, "status": job["status"], "backend": job["backend"],
            "output_tail": tail}


@mcp.tool()
def claude_result(job_id: str, max_chars: int = 20000) -> dict:
    """Full output of a finished Claude job. Errors if still running (use claude_poll)."""
    job = _refresh(job_id)
    if job["status"] == "running":
        raise RuntimeError(f"job {job_id} still running — use claude_poll")
    _, out_path = _job_paths(job_id)
    out = out_path.read_text() if out_path.exists() else ""
    return {"job_id": job_id, "status": job["status"],
            "output": out[:max(100, min(max_chars, 100000))]}


@mcp.tool()
def claude_cancel(job_id: str) -> dict:
    """Kill a running Claude job."""
    job = _read_job(job_id)
    if job["status"] != "running":
        return {"job_id": job_id, "status": job["status"], "note": "already finished"}
    try:
        os.killpg(job["pid"], signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    job["status"] = "cancelled"
    _write_job(job_id, job)
    return {"job_id": job_id, "status": "cancelled"}


@mcp.tool()
def claude_status() -> dict:
    """Backend health: is the CLI present, is an API key set, is login needed?"""
    import shutil
    cli = shutil.which("claude")
    return {
        "cli_present": bool(cli),
        "cli_path": cli or "",
        "api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "clean_settings": str(CLEAN_SETTINGS),
        "note": "If neither API key nor `claude login` is done, claude_ask fails fast "
                "with setup instructions instead of hanging.",
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Claude-control MCP server (OpenCode side)")
    ap.add_argument("--transport", choices=["stdio", "streamable-http"],
                    default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
