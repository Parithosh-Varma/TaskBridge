# Claude <-> OpenCode Bridge (MCP)

 lets the **Claude app** give tasks to **this OpenCode agent**, which runs them and writes output back for Claude to read.

## How it works

```
Claude app --(MCP stdio)--> opencode_bridge_mcp.py --(SQLite)--> tasks.db
OpenCode agent --(shell)--> tasks_cli.py ---------(SQLite)--> tasks.db
```

- Claude uses MCP tools: `submit_task`, `get_task`, `list_tasks`, `cancel_task`
- OpenCode (me) uses `tasks_cli.py` via shell to claim/complete tasks
- `tasks.db` is the shared queue. `TASK_DB_PATH` env overrides location.

## Files

- `opencode_bridge_mcp.py` — MCP server (Claude side)
- `task_store.py` — shared SQLite logic
- `tasks_cli.py` — CLI for OpenCode side
- `claude_desktop_config.snippet.json` — copy/paste for Claude Desktop
- `.venv/` — Python 3.12 venv with `mcp>=1,<2`

## Setup (already done here)

```bash
cd ~/claude-opencode-bridge
~/.local/bin/python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Auto-worker (no more waiting on me)

A launchd daemon runs `worker.py` every 60s. It claims pending tasks and
executes them headlessly via `opencode run --auto --model opencode/cat-jam-free`
(free model — the default OpenRouter model has no credits), then writes results back.

- Daemon: `~/Library/LaunchAgents/com.claude-opencode-bridge.worker.plist`
- Logs: `worker.log` (task activity), `worker.launchd.log` (daemon output)
- Reload: `launchctl unload/load ~/Library/LaunchAgents/com.claude-opencode-bridge.worker.plist`
- Model override: `WORKER_MODEL=provider/model` env in the plist
- Manual pass: `./.venv/bin/python worker.py`
- Reliability: timeouts enforced even on silent hangs (select-loop, not
  readline); stale `running` tasks requeued after 15 min; heartbeat written
  at pass start and per task (with `current_task`) so long runs read alive.
  Attempts counted at start, so top-level and `usage.attempts` always agree;
  each attempt gets the full `timeout_sec` budget.
- Concurrency: a flock single-instance lock (`.worker.lock`) makes an
  overlapping launchd/manual pass skip cleanly (logged) instead of
  double-finalizing a task. If a worker is SIGKILLed mid-task, the 15-min
  reaper requeues the row AND kills the orphaned opencode child
  (`task_logs/<id>.pid` records its process group) so no double-run.

Every finished task also fires a macOS Notification Center banner with the
result (failures get a different sound). Silence with `WORKER_NOTIFY=0`.
Full output always in `tasks.db` (`tasks_cli.py show <id>`) and `worker.log` —
the banner carries the first ~300 chars.

So Claude's `submit_task` → picked up within ~60s automatically → `get_task_result`
shows the answer. Verified: submitted test task completed with zero manual steps.

## Reverse bridge: MCP to control Claude (me → Claude)

`claude_control_mcp.py` — 6 tools I use to drive Claude: `claude_ask`
(sync), `claude_submit`/`claude_poll`/`claude_result`/`claude_cancel`
(background jobs in `claude_jobs/`), `claude_status` (health).
`permission_mode`: `auto` (acts headless) or `readonly`.

Backends: `ANTHROPIC_API_KEY` → direct API; else `claude -p` CLI in a
shadow HOME (`~/.claude-mcp`, login symlinked) so the dead router config
in `~/.claude/settings.json` (proxy 127.0.0.1:3456 DOWN, bogus model) is
bypassed without touching your setup. Registered globally in opencode
(`opencode mcp list` → ✓ connected).

**One step left: run `claude login` once** (or set `ANTHROPIC_API_KEY`).
Until then tools fail fast in ~1s with setup instructions — no hangs.

## Tools (16)

| Tool | What Claude uses it for |
|---|---|
| `submit_task` | Send one task: folder auto-created, per-task `model`, `depends_on`, `priority`, `timeout_sec`, `max_retries`/`retry_model`, `tags`, `idempotency_key`, `permission`, `worktree_*` |
| `submit_batch` | Up to 20 tasks, same fields per item |
| `get_task` / `get_task_result` | Full details / outcome + structured summary + usage + questions |
| `get_task_logs` | Tail live execution logs by byte offset (top-3 pick) |
| `wait_for` | Block until tasks finish — replaces poll loops (top-3 pick) |
| `answer_task` | Answer the worker's mid-task question; task auto-resumes |
| `list_tasks` | Filter by status, tag, date (`since`) |
| `queue_status` / `worker_heartbeat` | Queue counts + daemon liveness (version, model, last poll) |
| `add_task_note` | Append context to a pending/running task |
| `cancel_task` / `clear_finished` | Cancel; tidy finished results (30-min grace, never wipes unread) |
| `list_models` / `set_default_model` | See + choose worker models |
| `ping` | Connectivity check |

Semantics worth knowing:
- **Structured results**: every completion carries `{summary, files_touched, tests_run, open_questions}` plus a **diff summary** (top-3 pick) — git-aware, fallback file-walk.
- **Usage**: `{model actually used, latency_ms, attempts, permission, sandbox_enforced}`. Token counts aren't exposed by the opencode CLI, so those aren't faked.
- **Permissions, honestly enforced**: `readonly` reverts all writes after the run; `usage.sandbox_enforced` is true only if the revert actually removed files (plus a `reverted` list either way). `files_touched` is cwd-relative, deduped, `.git` internals excluded. `no-network`/`no-shell` are prompt-level — OS-denying network bricks cloud models and the background server escapes sandbox-exec (both probed, documented in `worker.py`).
- **Worktrees**: task runs on its own branch, auto-committed on success, worktree removed unless `worktree_keep`.
- **Two-way**: worker emits a question → status `waiting` + banner → `answer_task` resumes it with the answer in context.

## MCP server URL (HTTP mode)

The server also runs as a persistent HTTP endpoint:

**`https://<your-static-domain>.ngrok-free.dev/mcp`** (fixed ngrok domain — never changes)

Paste that into Claude: connectors/add-custom place where it asks for a public `https://` URL.

How it's running (both must stay up; `./start_public.sh` does it all —
ngrok fixed domain if `.ngrok-domain` exists, else cloudflare quick tunnel):
```bash
cd ~/claude-opencode-bridge
# 1. MCP server, allowlisting the tunnel host (required — otherwise 421)
MCP_ALLOWED_HOSTS="<your-tunnel-host>" \
  nohup ./.venv/bin/python opencode_bridge_mcp.py --transport streamable-http --port 8000 > mcp_http.log 2>&1 &
# 2. public tunnel to port 8000 (free, no account)
nohup cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000 > cloudflared.log 2>&1 &
```

Important: with the ngrok fixed domain the URL never changes — restart-safe.
(On a cloudflare quick tunnel the `trycloudflare.com` hostname changes every
restart; if you ever go back to that, update `MCP_ALLOWED_HOSTS` — or just
run `./start_public.sh`, which re-pairs it automatically.) Local-only use
needs no allowlist: `./.venv/bin/python opencode_bridge_mcp.py --transport streamable-http --port 8000`
serves `http://127.0.0.1:8000/mcp`.

Stdio mode (default, spawned by Claude Desktop, no URL) is unchanged:
`./.venv/bin/python opencode_bridge_mcp.py`

## Wire into Claude Desktop

Merge `claude_desktop_config.snippet.json` into:

`~/Library/Application Support/Claude/claude_desktop_config.json`

under top-level `mcpServers`. Then restart Claude Desktop.
A merge script already applied this (backup at `claude_desktop_config.json.bak-*`).

Verify in Claude:
> list available MCP tools — you should see `submit_task`, `get_task`, `list_tasks`, `cancel_task` under `opencode-bridge`.

## Claude usage

1. `submit_task(title="...", instructions="...")` → returns `id`
2. Poll `get_task(task_id="...")` until `status` is `completed`/`failed`
3. Read `result` / `error`

Be explicit in `instructions`: steps, paths, acceptance criteria.

## OpenCode worker loop (me)

When the user says "check Claude tasks" or on a schedule, I run:

```bash
cd ~/claude-opencode-bridge
./.venv/bin/python tasks_cli.py pending
./.venv/bin/python tasks_cli.py show <id>
./.venv/bin/python tasks_cli.py claim <id>
# ... do the work (edits, shell, tests) ...
./.venv/bin/python tasks_cli.py complete <id> --result "..."
# on failure:
./.venv/bin/python tasks_cli.py fail <id> --error "..."
```

Claude sees the result on its next `get_task` poll.

## Verified

- `task_store` submit → claim → complete round-trip: OK
- MCP `call_tool(submit_task/get_task/list_tasks)`: OK
- CLI `pending/show/claim/complete`: OK
