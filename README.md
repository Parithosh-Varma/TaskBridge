# Claude–OpenCode Bridge

> Let Claude dispatch coding work to headless OpenCode agents — with a durable SQLite queue in between.

Claude submits tasks over MCP. An auto-worker picks them up within ~60s, runs them with `opencode run`, and writes structured results back for Claude to read. Works from Claude Desktop (stdio), any MCP client (HTTP), and in reverse — OpenCode can drive Claude too.

![Python 3.12](https://img.shields.io/badge/python-3.12-blue) ![MCP](https://img.shields.io/badge/protocol-MCP-green) ![SQLite](https://img.shields.io/badge/queue-SQLite-lightgrey)

## Why this exists

Claude is a great planner but can't run code on your machine. OpenCode runs code on your machine but isn't inside Claude's context. This bridge connects them:

- **Claude** stays the interface: it breaks work down and delegates.
- **OpenCode** does the execution: edits, tests, shell — headlessly.
- **SQLite** (`tasks.db`) is the durable handoff: survives restarts, supports retries, priorities, dependencies, and two-way questions.

## Features

- **16 MCP tools for Claude**: `submit_task`, `submit_batch` (up to 20), `get_task` / `get_task_result`, `get_task_logs` (live tail), `wait_for` (no poll loops), `answer_task` (resume waiting tasks), `list_tasks` (status/tag/date), `queue_status` / `worker_heartbeat`, `add_task_note`, `cancel_task` / `clear_finished`, `list_models` / `set_default_model`, `ping`.
- **Auto-worker** (`worker.py`): launchd polls every 60s, claims oldest-first by priority, streams output to `task_logs/<id>.log`, completes with structured `{summary, files_touched, tests_run, open_questions}` + git-aware diff summary.
- **Two-way questions**: worker emits a `question` block → task goes `waiting` + macOS banner → Claude answers via `answer_task` → run resumes with the answer in context.
- **Worktree isolation**: per-task branch + `git worktree`, auto-committed on success, cleaned up unless `worktree_keep`.
- **Honest permissions**: `readonly` reverts writes after the run (`usage.sandbox_enforced` + `reverted` list); `no-network` / `no-shell` are prompt-level and labeled as such.
- **Reverse bridge** (`claude_control_mcp.py`): 6 tools for OpenCode to drive Claude — `claude_ask` (sync), `claude_submit` / `claude_poll` / `claude_result` / `claude_cancel` (background), `claude_status`. API backend if `ANTHROPIC_API_KEY` is set, else `claude -p` CLI.
- **Public-URL mode** (`start_public.sh`): MCP over ngrok fixed domain or Cloudflare quick tunnel with automatic `MCP_ALLOWED_HOSTS` pairing.
- **Live dispatch board** (`bridge_dashboard.html`, served as `GET /` on the same port/URL): warm dispatch-hall design with tally counts, per-task live log printouts, reverse Claude jobs, engine log tail, and a scrolling wire of the freshest output. Polls `/api/*` — the MCP endpoint at `/mcp` is untouched.
- **Caller detection**: `submit_task`/`submit_batch` stamp the true caller from the MCP handshake (`clientInfo`), so Claude and ChatGPT dockets get their own origin marks automatically; explicit `origin` overrides. The worker claims tasks from both.
- **Reliability**: per-attempt timeouts, 15-min stale-`running` reaper (kills orphaned process groups), single-instance flock, heartbeat file with `current_task`, macOS completion banners (`WORKER_NOTIFY=0` to silence).

## Quickstart

Prerequisites: Python 3.12, `opencode` CLI on `PATH`, a checkout of this repo.

```bash
git clone https://github.com/Parithosh-Varma/claude-opencode-bridge.git
cd claude-opencode-bridge
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Run the MCP server (stdio — Claude Desktop spawns this):

```bash
./.venv/bin/python opencode_bridge_mcp.py
```

Or serve HTTP locally:

```bash
./.venv/bin/python opencode_bridge_mcp.py --transport streamable-http --port 8000
# → http://127.0.0.1:8000/mcp
```

Wire into Claude Desktop — merge `claude_desktop_config.snippet.json` into
`~/Library/Application Support/Claude/claude_desktop_config.json` under `mcpServers`
(replace `<REPO_PATH>` with your checkout path), then restart Claude Desktop.
Verify: ask Claude to list MCP tools — you should see `submit_task`, `get_task`, `list_tasks` under `opencode-bridge`.

Run one worker pass manually:

```bash
./.venv/bin/python worker.py
```

Or schedule it every 60s with launchd (macOS) — see `worker.py` header and adjust the plist `ProgramArguments` to your checkout path.

## Usage

From Claude:

1. `submit_task(title="Add retry tests", instructions="Steps..., paths..., acceptance criteria...", working_dir="/path/to/target-repo")` → returns `id`
2. `wait_for(task_ids=["<id>"], timeout_sec=120)` — blocks instead of polling
3. `get_task_result(task_id="<id>")` → `result`, `structured`, `usage`, `diff`

Batch + follow-ups:

- `submit_batch(tasks=[...])` — up to 20 tasks with per-item `model`, `depends_on`, `priority`, `timeout_sec`, `max_retries` / `retry_model`, `tags`, `idempotency_key`, `permission`, `worktree_*`
- `get_task_logs(task_id="...", since_offset=0)` — tail live output
- `answer_task(task_id="...", answer="...")` — answer a `waiting` task's question
- `queue_status()` / `worker_heartbeat()` — queue counts + daemon liveness

From OpenCode (manual worker loop):

```bash
./.venv/bin/python tasks_cli.py pending
./.venv/bin/python tasks_cli.py show <id>
./.venv/bin/python tasks_cli.py claim <id>
# ... do the work (edits, shell, tests) ...
./.venv/bin/python tasks_cli.py complete <id> --result "..."
./.venv/bin/python tasks_cli.py fail <id> --error "..."
```

Reverse (OpenCode → Claude) via `claude_control_mcp.py` (registered as an OpenCode MCP server): `claude_ask` for one-shot answers, `claude_submit` + `claude_poll` / `claude_result` for background jobs.

## How it works

```mermaid
flowchart LR
  Claude -- MCP stdio/HTTP --> Bridge[opencode_bridge_mcp.py]
  Bridge -- read/write --> DB[(tasks.db - SQLite)]
  CLI[tasks_cli.py] -- claim/complete --> DB
  Worker[worker.py - launchd 60s] -- polls DB, runs opencode run --> Target[working_dir / worktree]
  Worker -- streams logs --> Logs[task_logs/ID.log]
  Worker -- result/structured/usage --> DB
  Claude -- get_task_result / wait_for --> Bridge
  OpenCode -- claude_ask/submit --> Reverse[claude_control_mcp.py]
  Reverse --> ClaudeCLI[claude -p / Anthropic API]
```

Key components:

| File | Role |
|---|---|
| `opencode_bridge_mcp.py` | MCP server (Claude side), stdio + `streamable-http` / `sse`, host allowlist |
| `task_store.py` | Shared SQLite logic: submit/claim/complete, retries, deps, notes, heartbeat |
| `tasks_cli.py` | CLI for manual runs: `pending list show claim complete fail logs heartbeat answer` |
| `worker.py` | Headless executor: `opencode run --auto`, timeouts, reaper, worktrees, banners |
| `claude_control_mcp.py` | Reverse MCP server (OpenCode → Claude) |
| `start_public.sh` | One-command public stack: tunnel + allowlisted MCP server |
| `claude_desktop_config.snippet.json` | Claude Desktop wiring template (`<REPO_PATH>` placeholder) |

## Configuration

| Variable | Used by | Purpose |
|---|---|---|
| `TASK_DB_PATH` | bridge, CLI | SQLite path (default: `<repo>/tasks.db`) |
| `WORKER_MODEL` | worker | Default model, e.g. `opencode/cat-jam-free` |
| `OPENCODE_BIN` | worker | `opencode` binary (default: `opencode` on `PATH`) |
| `WORKER_NOTIFY` | worker | `1` (default) macOS banners, `0` to silence |
| `MCP_ALLOWED_HOSTS` | bridge (HTTP) | Comma-separated tunnel hosts (required behind ngrok/cloudflared, else 421) |
| `ANTHROPIC_API_KEY` | reverse bridge | Direct API backend; else `claude -p` CLI |
| `CLAUDE_API_MODEL` / `CLAUDE_MCP_HOME` | reverse bridge | Model override / shadow HOME for CLI backend |

`start_public.sh`: uses `.ngrok-domain` if present (fixed domain), else Cloudflare quick tunnel. It re-pairs `MCP_ALLOWED_HOSTS` automatically — rerun it whenever the URL changes.

## Project structure

```
.
├── opencode_bridge_mcp.py          # MCP server (Claude → queue)
├── task_store.py                   # SQLite queue logic
├── tasks_cli.py                    # Manual worker CLI
├── worker.py                       # Auto-worker (launchd, 60s)
├── claude_control_mcp.py           # Reverse bridge (OpenCode → Claude)
├── start_public.sh                 # Public tunnel + server launcher
├── claude_desktop_config.snippet.json
├── claude-clean.settings.json
├── requirements.txt                # mcp>=1.0,<2
└── .gitignore                      # excludes .venv/, tasks.db, logs, task_logs/, claude_jobs/, worktrees/
```

Runtime state (never committed): `tasks.db`, `task_logs/`, `claude_jobs/`, `worktrees/`, `*.log`, `heartbeat.json`.

## Troubleshooting / FAQ

- **421 behind tunnel**: `MCP_ALLOWED_HOSTS` must exactly match the tunnel host. Run `./start_public.sh` — it sets this automatically.
- **Tunnel URL changed (Cloudflare)**: quick-tunnel hostnames rotate every restart. Rerun `./start_public.sh` or switch to an ngrok fixed domain via `.ngrok-domain`.
- **Worker looks stuck**: check `./.venv/bin/python tasks_cli.py heartbeat` and `task_logs/<id>.log`. Stale `running` tasks are reaped after 15 min (per-task `timeout_sec` + slack honored).
- **Double-run after kill**: every attempt spawns `opencode run --standalone --title br-<id>-a<n>` (per-attempt argv marker, ps-visible). The reaper kills the orphaned CLI child **plus its ppid tree** (loop-until-empty, hard-capped so a matching bug can't mass-kill); a per-pass sweep catches tagged strays of non-running tasks. Reaper deadline is per-task (`max(900s, timeout_sec + 120s)`). macOS gives no session/env signal (`ps sess=` is 0 everywhere, `ps -E` shows no env), so ppid walk + argv marker are the whole toolkit — reparented-to-1/setsid grandchildren are the known residual. NOTE: never pass `--session` to the CLI: it makes free-tier models refuse to run.
- **No banners**: macOS only. Set `WORKER_NOTIFY=0` to silence intentionally; full output is always in `tasks.db` + `worker.log`.
- **Reverse bridge fails fast (~1s)**: run `claude login` once or set `ANTHROPIC_API_KEY`.
- **`opencode` not found**: put it on `PATH` or set `OPENCODE_BIN=/path/to/opencode`.

## Limitations

- Token counts aren't exposed by the `opencode` CLI — `usage` reports model, latency, attempts, and sandbox status, not tokens.
- `no-network` / `no-shell` are prompt-level restrictions, not OS-enforced sandboxes (documented in `worker.py`).
- Desktop banners and launchd scheduling are macOS-specific; Linux needs its own scheduler (systemd/cron) + `worker.py` still runs manually.
- Long tasks (up to 1800s `timeout_sec`) are supported, but the 60s launchd cadence means pickup latency averages ~30s.

## Verified

- `task_store` submit → claim → complete round-trip: OK
- MCP `submit_task` / `get_task` / `list_tasks` via `call_tool`: OK
- CLI `pending` / `show` / `claim` / `complete`: OK
- `submit_task` → auto-picked-up in ~60s → `get_task_result` with zero manual steps: OK
