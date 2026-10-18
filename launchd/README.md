# Worker supervision (launchd) & the `restart_worker` tool

TaskBridge runs the worker (`worker.py`) as a **user LaunchAgent**: launchd starts
one pass every 60 s and the pass exits when the queue is empty. The MCP server
(`opencode_bridge_mcp.py`) is a separate process, so it stays reachable — and can
restart the worker — even when the worker is completely offline.

## The moving parts

| Piece | Where | Notes |
|---|---|---|
| Service label | `com.taskbridge.worker` (default) | Discovered from the installed plist, never invented. Override with `TASKBRIDGE_SERVICE_LABEL`. |
| Plist | `~/Library/LaunchAgents/com.taskbridge.worker.plist` | Template in this directory; `install_worker_agent.sh` fills in the paths. |
| Domain | `gui/$(id -u)` | The logged-in GUI session. No `sudo` — a user agent must not be installed as root. |
| Heartbeat | `<repo>/heartbeat.json` | Written at the start of every pass. Fresh = worker is in contact. |
| Single-instance lock | `<repo>/.worker.lock` | `flock` held for the duration of a pass; the restart logic probes it to avoid interrupting an active pass. |
| Restart state | `<repo>/.restart_state.json` | Cooldown + attempt history (mode 600). Never contains secrets. |
| Restart log | `<repo>/restart.log` | One line per restart decision/outcome. |

## Install / update

```bash
# from the repo root (no sudo)
./launchd/install_worker_agent.sh              # install or update, then start
./launchd/install_worker_agent.sh --uninstall  # boot out and delete the plist
```

The script embeds absolute paths, so re-run it after moving the checkout.
Manual equivalent:

```bash
LABEL=com.taskbridge.worker
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
sed -e "s|__PYTHON__|$PWD/.venv/bin/python|g" \
    -e "s|__REPO_DIR__|$PWD|g" -e "s|__HOME__|$HOME|g" \
    launchd/com.taskbridge.worker.plist.template > "$PLIST"
launchctl bootout  "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
```

## Verify the label and the state

```bash
launchctl print "gui/$(id -u)/com.taskbridge.worker" | head -20   # label, state, runs, last exit code
./.venv/bin/python tasks_cli.py supervisor-status                 # service + heartbeat + queue, JSON
./.venv/bin/python tasks_cli.py heartbeat                         # heartbeat.json contents
launchctl list com.taskbridge.worker                              # legacy short form
```

`state = not running` between passes is normal (the worker is a one-shot job).
What matters is a **fresh heartbeat**: `tasks_cli.py heartbeat` should show
`ts` within the last ~180 s (and `worker_heartbeat()` over MCP says `alive: true`).

## Calling `restart_worker` from an MCP client

```
restart_worker(force=false, timeout_sec=90)
```

| Parameter | Meaning |
|---|---|
| `force` | `false` (default) never interrupts a healthy worker — the call returns `outcome: skipped_healthy`. `true` restarts even a healthy worker (an active task may be interrupted; queued tasks are preserved). |
| `timeout_sec` | How long to wait for a verified recovery, 10–600 (default 90). |

Result fields: `success`, `previous_status` (`healthy` \| `stale` \| `offline`),
`restart_attempted`, `restart_method` (`launchctl kickstart` \|
`launchctl bootstrap` \| `none`), `service_label`, `heartbeat_before`,
`heartbeat_after`, `worker_pid`, `elapsed_ms`, `error`, `next_steps`, plus
`outcome`, `diagnosis`, `verified`, `queue_evidence` and a redacted `logs` trail.

Typical chat usage: "the worker looks offline — restart it" → the model calls
`worker_heartbeat()` first, then `restart_worker()`, then verifies with
`worker_heartbeat()` / `queue_status()`.

Contract highlights:

- **Exit code 0 from launchctl is not success.** A restart counts as recovered
  only when a heartbeat *newer than the attempt* appears (and, when the queue
  shows work, that pass claimed a task).
- **Independence:** the restart runs inside the MCP server (or
  `tasks_cli.py restart-worker`), which imports nothing from `worker.py`, so a
  crashed or un-importable worker can still be recovered.
- **One at a time:** attempts are serialized with `flock`; concurrent requests
  get `outcome: already_in_progress`.
- **Rate limited:** a cooldown (default 90 s, `TASKBRIDGE_RESTART_COOLDOWN_SEC`)
  blocks restart storms; it doubles (up to ×8) while attempts keep failing.
- **Graceful first:** if a pass is running, the tool waits up to
  `TASKBRIDGE_RESTART_GRACE_SEC` (default 20 s) for it to finish before
  `kickstart -k` (SIGTERM). Queued tasks are never deleted or rewritten; an
  interrupted run is re-queued by the worker's own stale-`running` reaper.

## How long a restart takes

- Not loaded → `bootstrap` with `RunAtLoad: true`: the new pass starts in ~0.1 s.
- Loaded → `kickstart -k`: launchd throttles restarts by ~10 s (measured; ~20 s
  after a crash). That is why the default timeout is 90 s — a slow verification
  is launchd throttling, not a failure.

## Required macOS permissions

Nothing privileged: `restart_worker` only ever runs `/bin/launchctl` for the
**fixed label** of this repo's LaunchAgent, in the caller's own `gui/<uid>`
domain. It cannot run arbitrary commands, cannot kill arbitrary PIDs, and never
uses `sudo`. Consequences:

- Run the MCP server (and Terminal) as the same user that installed the plist;
  `sudo`-installed **system daemons** are out of scope by design.
- From a remote/ssh-only session there is no `gui/<uid>` domain — restart then
  requires a GUI login session (see Troubleshooting).
- `Full Disk Access` is not needed; `launchctl` on a user agent needs no TCC
  grant. (macOS *notifications* from `worker.py` may need permission — unrelated.)

## When `restart_worker` fails

`next_steps` in the result is written for the exact failure; the common ones:

| `outcome` | Meaning | Fix |
|---|---|---|
| `service_missing` | No LaunchAgent installed for this checkout (`loaded=false`, no plist). | `./launchd/install_worker_agent.sh`, then retry. |
| `supervisor_unavailable` | `/bin/launchctl` missing/not executable (non-macOS host). | Run the worker manually: `nohup .venv/bin/python worker.py >> worker.log 2>&1 &`, or add a systemd/cron supervisor. |
| `permission_denied` | launchctl refused (wrong session/owner). | Re-run from a Terminal in the GUI session; reinstall the agent **without** sudo. |
| `service_not_loaded` | launchd lost the job although the plist exists. | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.taskbridge.worker.plist`. |
| `launchctl_failed` | launchd rejected the operation. | Run the equivalent `launchctl` command by hand (shown in `next_steps`) and read `worker.launchd.log`. |
| `restart_timeout` | The job started but no fresh heartbeat appeared. | Almost always a worker-side startup failure: `last exit code 78 (EX_CONFIG)` = bad `ProgramArguments`, missing `.venv`, or a crash on import (see `worker.launchd.log`); a missing `opencode` binary shows up as an early failure in `worker.log`. |
| `rate_limited` | A restart already ran inside the cooldown window. | Wait `cooldown_remaining_sec`, then retry. |
| `already_in_progress` | Another restart call is still verifying. | Retry in a few seconds. |

Manual recovery sequence:

```bash
launchctl print "gui/$(id -u)/com.taskbridge.worker" | grep -E 'state|last exit|runs'
tail -20 worker.launchd.log            # launchd-level stdout/stderr
tail -20 worker.log                    # worker pass log
./.venv/bin/python tasks_cli.py supervisor-status
./.venv/bin/python tasks_cli.py restart-worker --force   # same engine as the MCP tool
```

## Uninstall safely

```bash
./launchd/install_worker_agent.sh --uninstall
```

That boots the job out of `gui/<id>` and deletes the plist; the repo, the task
DB, and `task_logs/` are untouched. Remove the state files if you want a clean
slate: `rm -f .restart_state.json .restart.lock`. To keep the worker running
without launchd, start it manually (`worker.py` per pass, or wrap it in a loop
of your own).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TASKBRIDGE_SERVICE_LABEL` | `com.taskbridge.worker` | Label to control (must be a plain reverse-DNS identifier). |
| `TASKBRIDGE_SERVICE_PLIST` | `~/Library/LaunchAgents/<label>.plist` | Explicit plist path. |
| `TASKBRIDGE_LAUNCHCTL` | `/bin/launchctl` | Absolute path to launchctl (packaging/tests). |
| `TASKBRIDGE_RESTART_COOLDOWN_SEC` | `90` | Minimum gap between restart attempts (5–86400). |
| `TASKBRIDGE_RESTART_TIMEOUT_SEC` | `90` | Default verified-recovery timeout (10–600). |
| `TASKBRIDGE_RESTART_GRACE_SEC` | `20` | Max wait for a running pass before `kickstart -k`. |
| `TASKBRIDGE_RESTART_STATE_PATH` | `<repo>/.restart_state.json` | Cooldown/attempt state file. |
| `TASKBRIDGE_RESTART_LOCK_PATH` | `<repo>/.restart.lock` | Concurrency lock between restart callers. |
| `TASKBRIDGE_RESTART_LOG_PATH` | `<repo>/restart.log` | Restart decision/outcome log. |
| `TASKBRIDGE_HEARTBEAT_PATH` | `<repo>/heartbeat.json` | Heartbeat file (tests/odd layouts). |
