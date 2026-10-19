#!/bin/bash
# TaskBridge — one-command install & launch.
#
#   ./install.sh                 install deps, reuse/create the bearer token, ask
#                                which tunnel to use, serve MCP (foreground, rich TUI)
#   ./install.sh --rotate        regenerate the bearer token first
#   ./install.sh --no-serve      set everything up, print the credentials, stop
#   ./install.sh --plain         plain line output instead of the live dashboard
#   ./install.sh --tunnel cloudflare  skip the prompt: temporary trycloudflare.com URL
#   ./install.sh --tunnel ngrok       skip the prompt: ngrok (Authtoken needed)
#   ./install.sh --ngrok-token X save an ngrok Authtoken before opening the tunnel
#
# The installer asks which tunnel to use. Cloudflare quick tunnels need no account
# and are the default; ngrok suits reserved domains or existing Authtokens.
#
# Or straight from a shell (clones the repo for you):
#   curl -fsSL https://taskbridge-landing.pages.dev/install | bash
#
# Safe to re-run: an existing .venv, .bridge-token and a live ngrok tunnel for the
# same port are reused. Ctrl+C stops the server; the tunnel stays up.
#
# This file is only the bootstrap: it guarantees a python 3.12 venv with the rich
# renderer available, then hands the terminal over to installer_tui.py, which owns
# the UI and every remaining step.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export PORT="${PORT:-8000}"

PY="$HERE/.venv/bin/python"

die() {
  printf '\033[1mTaskBridge\033[0m %s\n' "$*" >&2
  exit 1
}

command -v python3.12 >/dev/null 2>&1 ||
  die "python3.12 is required — install it first (brew install python@3.12)."

# Cold path only: show one self-erasing line while a slow step runs, so the first
# run never sits in silence before the dashboard can draw.
boot_line() {
  local message="$1"
  shift
  "$@" >/dev/null 2>&1 &
  local pid=$!
  local frames='|/-\'
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r\033[2m  %s %s\033[0m' "${frames:$((i % 4)):1}" "$message"
    i=$((i + 1))
    sleep 0.12
  done
  wait "$pid"
  local status=$?
  printf '\r\033[2K'
  return $status
}

if [ ! -x "$PY" ]; then
  boot_line "first run · building the python 3.12 environment…" python3.12 -m venv "$HERE/.venv" ||
    die "could not create .venv — check that python3.12 runs (python3.12 --version)."
fi

if ! "$PY" -c 'import rich' >/dev/null 2>&1; then
  # The dashboard needs rich before it can draw; the rest comes from requirements.txt.
  boot_line "first run · preparing the installer UI…" "$PY" -m pip install -q rich ||
    printf '  \033[2m(rich unavailable — falling back to plain output)\033[0m\n'
fi

exec "$PY" "$HERE/installer_tui.py" "$@"
