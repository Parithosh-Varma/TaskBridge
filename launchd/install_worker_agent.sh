#!/bin/bash
# Install (or update / remove) the TaskBridge worker LaunchAgent.
#
#   ./launchd/install_worker_agent.sh            install or update, then start
#   ./launchd/install_worker_agent.sh --uninstall  boot out and delete the plist
#
# No sudo: this is a *user* LaunchAgent in gui/$(id -u). Re-run after moving the
# checkout — the plist embeds absolute paths. The label defaults to
# com.taskbridge.worker; override with TASKBRIDGE_SERVICE_LABEL=<label>.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${TASKBRIDGE_SERVICE_LABEL:-com.taskbridge.worker}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
PYTHON="$REPO_DIR/.venv/bin/python"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL (plist: $PLIST)"
  echo "the worker no longer runs automatically; start it manually with:"
  echo "  cd $REPO_DIR && .venv/bin/python worker.py"
  exit 0
fi

[ -x "$PYTHON" ] || { echo "no python at $PYTHON — run ./install.sh first" >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__REPO_DIR__|$REPO_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$REPO_DIR/launchd/com.taskbridge.worker.plist.template" > "$PLIST"

# Reload so an updated plist takes effect; bootout is a no-op if not loaded.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "installed and started $LABEL"
echo "verify:  launchctl print $DOMAIN/$LABEL | head -20"
echo "heartbeat: $REPO_DIR/heartbeat.json  (or ./tasks_cli.py heartbeat)"
