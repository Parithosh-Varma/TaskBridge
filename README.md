# TaskBridge

> **Claude plans. OpenCode builds.** Dispatch real coding work from Claude to headless OpenCode agents via a durable SQLite queue.

Claude submits tasks over MCP. An auto-worker picks them up in ~60 s, runs `opencode run` in an isolated worktree, and returns a structured summary, git-aware diff, logs, and usage for Claude to read. Works from Claude Desktop (stdio), any MCP client over HTTP, and in reverse — OpenCode can drive Claude too.

![Python 3.12](https://img.shields.io/badge/python-3.12-blue) ![MCP](https://img.shields.io/badge/protocol-MCP-green) ![SQLite](https://img.shields.io/badge/queue-SQLite-lightgrey) ![Worker](https://img.shields.io/badge/worker-2.0.0-blue) ![License](https://img.shields.io/badge/license-Apache--2.0-blue)

## Why this exists

Claude is a powerful planner that can't touch your filesystem. OpenCode runs code locally but lives outside Claude's context. The bridge closes the loop:

- **Claude stays the interface** — breaks work down, delegates, and reads results.
- **OpenCode does the execution** — edits, tests, shell, headlessly and reproducibly.
- **SQLite is the durable handoff** — survives restarts, supports retries, priorities, dependencies, and two-way questions.

## Features

- **17 MCP tools for Claude** — `submit_task`, `submit_batch` (up to 20), `get_task` / `get_task_result`, `get_task_logs` (live tail), `wait_for`, `answer_task`, `list_tasks`, `queue_status` / `worker_heartbeat`, **`restart_worker`** (recover a dead/stale worker through launchd, from the MCP server itself), `add_task_note`, `cancel_task` / `clear_finished`, `list_models` / `set_default_model`, `ping`. No polling loops, full observability.
- **Headless auto-worker** (`worker.py`) — launchd polls every 60 s, claims oldest-first by priority, streams output to `task_logs/<id>.log`, returns structured `{summary, files_touched, tests_run, open_questions}` plus a git-aware diff.
- **Two-way questions** — worker can pause with a `question` block → task goes `waiting` + macOS banner → Claude answers via `answer_task` → run resumes with the answer in context.
- **Worktree isolation** — per-task branch + `git worktree`, auto-committed on success, cleaned up unless `worktree_keep`.
- **Honest permissions** — `readonly` reverts writes and reports `reverted` files; `no-network` / `no-shell` are prompt-level and explicitly labeled.
- **Reverse bridge** (`claude_control_mcp.py`) — 6 tools for OpenCode to drive Claude: `claude_ask` (sync), `claude_submit` / `claude_poll` / `claude_result` / `claude_cancel` (background), `claude_status`. Uses Anthropic API if `ANTHROPIC_API_KEY` is set, else `claude -p`.
- **Public-URL mode** (`install.sh` / `start_public.sh`) — one command to expose MCP via ngrok (the installer prompts for your Authtoken) or Cloudflare quick tunnel with automatic `MCP_ALLOWED_HOSTS` pairing.
- **Live dispatch board** (`bridge_dashboard.html`) — served at `GET /` on the same host. Tally counts, per-task live logs, reverse jobs, engine tail, and a scrolling feed of fresh output. The **Model** button sets the worker default model (persisted to `worker_config.json`) without touching the CLI. Polls `/api/*`; MCP stays at `/mcp`.
- **Caller detection** — `submit_task`/`submit_batch` stamp the true caller from the MCP handshake `clientInfo`, so Claude and ChatGPT dockets stay separate. `origin` can be overridden explicitly.
- **Production reliability** — per-attempt timeouts, 15-min stale-`running` reaper with pid-reuse guard, single-instance flock, heartbeat file, macOS banners (`WORKER_NOTIFY=0` to silence).

## Quickstart

Prerequisites: Python 3.12, `opencode` CLI on `PATH`, and (for public access) a free ngrok account.

**One command — install, tunnel, serve, print your connector box:**

```bash
git clone https://github.com/Parithosh-Varma/TaskBridge.git
cd TaskBridge
./install.sh
```

`install.sh` prompts for your ngrok Authtoken (blank = already configured), installs dependencies into `.venv`, generates or reuses the bearer token in `.bridge-token`, opens the ngrok tunnel (fixed domain from `.ngrok-domain` when present), pairs `MCP_ALLOWED_HOSTS`, prints the public URL + token box, then serves MCP in the foreground. Ctrl+C stops the server; the tunnel stays up for the next run. Rotate the token with `./install.sh --rotate`.

**Manual setup** (stdio / local dev):

```bash
git clone https://github.com/Parithosh-Varma/TaskBridge.git
cd TaskBridge
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
Verify: ask Claude to list MCP tools — you should see `submit_task`, `get_task`, `list_tasks` under `taskbridge`.

## Authentication (HTTP mode)

`install.sh` generates the bearer token and serves the public endpoint:

```bash
./install.sh            # reuse or generate .bridge-token, tunnel + serve
./install.sh --rotate   # regenerate the bearer token first
```

Token is loaded from `.bridge-token` file or `BRIDGE_AUTH_TOKEN` env var.
`install.sh` and `start_public.sh` (the background / Cloudflare-tunnel variant) both pick it up automatically.

**Public URL access requires**:
```
Authorization: Bearer <your-token>
```

- `/health` is open (monitoring)
- `/` dashboard prompts for token (stored in sessionStorage)
- `/api/*` and `/mcp` require Bearer token
- stdio transport (Claude Desktop) is local-only, no token needed

To rotate token: `./install.sh --rotate`

Run one worker pass manually:

```bash
./.venv/bin/python worker.py
```

Or schedule it every 60s with launchd (macOS):

```bash
./launchd/install_worker_agent.sh     # install/update the user LaunchAgent, then start
```

That installs `~/Library/LaunchAgents/com.taskbridge.worker.plist` (a user agent —
no sudo) from `launchd/com.taskbridge.worker.plist.template`, with paths for this
checkout. See [launchd/README.md](launchd/README.md) for label verification,
update/uninstall, and the `restart_worker` contract.

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
- `restart_worker(force=false, timeout_sec=90)` — recover the worker through launchd
  when it is offline/stale (or `force=true` to restart a healthy one deliberately);
  returns a verified result with `previous_status`, `restart_method`, heartbeat
  before/after and `next_steps` on failure
- `list_models(search="")` / `set_default_model(model="opencode/deepseek-v4.1-flash-free")` —
  change the worker-wide default model (validated against `opencode models`, saved
  to `worker_config.json`). The dashboard's **Model** button is the same picker:
  it calls `GET /api/models` + `POST /api/model` behind the bearer token.

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
  Bridge -- restart_worker --> Supervisor[worker_supervisor.py] -- launchctl --> Worker
  OpenCode -- claude_ask/submit --> Reverse[claude_control_mcp.py]
  Reverse --> ClaudeCLI[claude -p / Anthropic API]
```

Key components:

| File | Role |
|---|---|
| `opencode_bridge_mcp.py` | MCP server (Claude side), stdio + `streamable-http` / `sse`, host allowlist |
| `task_store.py` | Shared SQLite logic: submit/claim/complete, retries, deps, notes, heartbeat |
| `tasks_cli.py` | CLI for manual runs: `pending list show claim complete fail logs heartbeat answer restart-worker supervisor-status` |
| `worker.py` | Headless executor: `opencode run --auto`, timeouts, reaper, worktrees, banners |
| `worker_supervisor.py` | Independent restart engine behind `restart_worker` (launchd control, cooldown, verification); imports nothing from `worker.py` |
| `claude_control_mcp.py` | Reverse MCP server (OpenCode → Claude) |
| `install.sh` | One command: deps + bearer token + ngrok tunnel + allowlist + serve |
| `start_public.sh` | Background variant: tunnel + allowlisted MCP server (ngrok fixed domain or Cloudflare) |
| `launchd/` | Worker LaunchAgent template + install/uninstall script + supervision docs |
| `claude_desktop_config.snippet.json` | Claude Desktop wiring template (`<REPO_PATH>` placeholder) |

## Configuration

| Variable | Used by | Purpose |
|---|---|---|
| `TASK_DB_PATH` | bridge, CLI | SQLite path (default: `<repo>/tasks.db`) |
| `WORKER_MODEL` | worker | Default model fallback, e.g. `opencode/deepseek-v4.1-flash-free` (`worker_config.json` from the dashboard / `set_default_model` wins over it) |
| `OPENCODE_BIN` | worker | `opencode` binary (default: `opencode` on `PATH`) |
| `WORKER_NOTIFY` | worker | `1` (default) macOS banners, `0` to silence |
| `MCP_ALLOWED_HOSTS` | bridge (HTTP) | Comma-separated tunnel hosts (required behind ngrok/cloudflared, else 421) |
| `BRIDGE_AUTH_TOKEN` | bridge (HTTP) | Bearer token for MCP/API access (defaults to `.bridge-token` file) |
| `TASKBRIDGE_CONSENT_SECRET` | OAuth consent | Secret for the /approve "this was me" page (defaults to the bridge token) |
| `TASKBRIDGE_TOKEN_TTL_SEC` | OAuth | Access-token lifetime (default 86400 = 24h) |
| `TASKBRIDGE_REFRESH_TTL_SEC` | OAuth | Refresh-token lifetime (default 2592000 = 30d) |
| `MCP_PUBLIC_URL` | bridge (HTTP) | Force the public origin in OAuth documents when behind unusual proxies |
| `ANTHROPIC_API_KEY` | reverse bridge | Direct API backend; else `claude -p` CLI |
| `CLAUDE_API_MODEL` / `CLAUDE_MCP_HOME` | reverse bridge | Model override / shadow HOME for CLI backend |
| `TASKBRIDGE_SERVICE_LABEL` | `restart_worker` | LaunchAgent label (default `com.taskbridge.worker`) |
| `TASKBRIDGE_RESTART_COOLDOWN_SEC` | `restart_worker` | Minimum gap between restart attempts (default 90) |
| `TASKBRIDGE_RESTART_TIMEOUT_SEC` | `restart_worker` | Default verified-recovery timeout (default 90) |
| `TASKBRIDGE_RESTART_GRACE_SEC` | `restart_worker` | Max wait for a running pass before `kickstart -k` (default 20) |

`start_public.sh`: uses `.ngrok-domain` if present (fixed domain), else Cloudflare quick tunnel. It re-pairs `MCP_ALLOWED_HOSTS` automatically — rerun it whenever the URL changes. If `.bridge-token` exists, `BRIDGE_AUTH_TOKEN` is loaded automatically. `install.sh` is the interactive equivalent — it prompts for the ngrok Authtoken and serves MCP in the foreground.

## Project structure

```
.
├── opencode_bridge_mcp.py          # MCP server (Claude → queue)
├── task_store.py                   # SQLite queue logic
├── tasks_cli.py                    # Manual worker CLI (+ restart-worker)
├── worker.py                       # Auto-worker (launchd, 60s)
├── worker_supervisor.py            # restart_worker engine: launchd control, cooldown, verify
├── claude_control_mcp.py           # Reverse bridge (OpenCode → Claude)
├── install.sh                      # One-command installer: deps, token, tunnel, serve
├── start_public.sh                 # Public tunnel + server launcher (background)
├── launchd/                        # Worker LaunchAgent template + install/uninstall docs
├── tests/                          # pytest suite (supervisor, MCP tool surface, launchd E2E)
├── claude_desktop_config.snippet.json
├── claude-clean.settings.json
├── requirements.txt                # mcp>=1.0,<2
├── requirements-dev.txt            # pytest (tests only)
└── .gitignore                      # excludes .venv/, tasks.db, logs, task_logs/, claude_jobs/, worktrees/
```

Runtime state (never committed): `tasks.db`, `task_logs/`, `claude_jobs/`, `worktrees/`, `*.log`, `heartbeat.json`, `.worker.lock`, `.restart_state.json`.

## Troubleshooting / FAQ

- **421 behind tunnel**: `MCP_ALLOWED_HOSTS` must exactly match the tunnel host. Run `./install.sh` or `./start_public.sh` — they set this automatically.
- **Tunnel URL changed (Cloudflare)**: quick-tunnel hostnames rotate every restart. Rerun `./install.sh` (or `./start_public.sh`), or reserve an ngrok fixed domain via `.ngrok-domain`.
- **Worker looks stuck**: check `./.venv/bin/python tasks_cli.py heartbeat` and `task_logs/<id>.log`. Stale `running` tasks are reaped after 15 min (per-task `timeout_sec` + slack honored).
- **Worker offline / heartbeat stale**: call MCP `restart_worker()` — it restarts through launchd from the MCP server process (which does not depend on the worker), waits for a *verified* fresh heartbeat, and explains itself (`outcome`, `next_steps`). Same engine from a terminal: `./.venv/bin/python tasks_cli.py restart-worker [--force]`. Full runbook: [launchd/README.md](launchd/README.md).
- **`restart_worker` says `service_missing`**: no LaunchAgent is installed for this checkout — run `./launchd/install_worker_agent.sh`, then retry.
- **`restart_worker` says `restart_timeout`**: launchctl started the job but no heartbeat appeared. `launchctl print "gui/$(id -u)/com.taskbridge.worker" | grep -E 'state|last exit'` — `last exit code 78` (EX_CONFIG) means launchd could not run the configured program (wrong paths in the plist, missing `.venv`); otherwise read the tail of `worker.launchd.log` / `worker.log`.
- **Double-run after kill**: every attempt spawns `opencode run [--standalone] --title br-<id>-a<n>` (per-attempt argv marker, ps-visible). Optional flags such as `--standalone` are probed from the binary's own `run --help` (`-h` fallback) once per install and only passed when advertised; if a build still rejects the command (help dump, nonzero exit), the worker retries once without them. Unreadable or older/newer variants just run without the extras — no version tables; the reaper then relies on the pid-tree/argv walk alone. The reaper kills the orphaned CLI child **plus its ppid tree** (loop-until-empty, hard-capped so a matching bug can't mass-kill); a per-pass sweep catches tagged strays of non-running tasks. Reaper deadline is per-task (`max(900s, timeout_sec + 120s)`). macOS gives no session/env signal (`ps sess=` is 0 everywhere, `ps -E` shows no env), so ppid walk + argv marker are the whole toolkit — reparented-to-1/setsid grandchildren are the known residual. NOTE: never pass `--session` to the CLI: it makes free-tier models refuse to run.
- **No banners**: macOS only. Set `WORKER_NOTIFY=0` to silence intentionally; full output is always in `tasks.db` + `worker.log`.
- **Reverse bridge fails fast (~1s)**: run `claude login` once or set `ANTHROPIC_API_KEY`.
- **`opencode` not found**: put it on `PATH` or set `OPENCODE_BIN=/path/to/opencode`.

## Limitations

- Token counts aren't exposed by the `opencode` CLI — `usage` reports model, latency, attempts, and sandbox status, not tokens.
- `no-network` / `no-shell` are prompt-level restrictions, not OS-enforced sandboxes (documented in `worker.py`).
- Desktop banners and launchd scheduling are macOS-specific; Linux needs its own scheduler (systemd/cron) + `worker.py` still runs manually. `restart_worker` is likewise macOS/launchd-only — on a host without launchd it returns `supervisor_unavailable` with manual instructions instead of pretending.
- Long tasks (up to 1800s `timeout_sec`) are supported, but the 60s launchd cadence means pickup latency averages ~30s.
- `restart_worker` cannot recover from a broken *plist* either: if the configured program can't run, the result is `restart_timeout` with the launchd diagnostics you need. Queued tasks are untouched either way.

## Verified

- `task_store` submit → claim → complete round-trip: OK
- MCP `submit_task` / `get_task` / `list_tasks` via `call_tool`: OK
- CLI `pending` / `show` / `claim` / `complete`: OK
- `submit_task` → auto-picked-up in ~60s → `get_task_result` with zero manual steps: OK
- `restart_worker` registered + schema (`force` boolean default false, `timeout_sec` integer) via MCP tool discovery: OK
- `restart_worker` unit suite (skip/offline/stale/force, missing service, permission denied, launchctl failure, timeout, concurrency, cooldown, queue preservation, label discovery) with a faked launchctl: OK
- `restart_worker` against **real launchd** with a disposable probe LaunchAgent: offline → fresh heartbeat, stale → `kickstart -k` replaces the process, healthy + `force=false` → skipped, pending task byte-identical after recovery: OK (`TASKBRIDGE_RUN_LAUNCHD_E2E=1`)

## License

Apache-2.0 — see [LICENSE](LICENSE). Fork it, self-host it, build on it.
