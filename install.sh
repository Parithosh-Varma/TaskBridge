#!/bin/bash
# TaskBridge — one-command install & launch.
#
#   ./install.sh            install deps, reuse/create the bearer token, open the
#                           ngrok tunnel, pair the allowlist, serve MCP (foreground)
#   ./install.sh --rotate   regenerate the bearer token first
#
# Safe to re-run: an existing .venv, .bridge-token and a live ngrok tunnel for
# the same port are reused. Ctrl+C stops the server; the ngrok tunnel stays up.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PORT="${PORT:-8000}"
TOKEN_FILE="$HERE/.bridge-token"
NGROK_API="http://127.0.0.1:4040/api/tunnels"
ROTATE=0
[ "${1:-}" = "--rotate" ] && ROTATE=1

echo "========================================="
echo "            TaskBridge installer"
echo "========================================="

# 1. ngrok Authtoken (press Enter to keep an existing configuration)
read -rsp "🔑 Enter your ngrok Authtoken (blank = already configured): " NGROK_TOKEN
echo; echo "========================================="

# 2. Ensure ngrok is installed, then authenticate if a token was given
if ! command -v ngrok >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "📦 ngrok not found — installing via Homebrew..."
    brew install -q ngrok/ngrok/ngrok
  else
    echo "⚠️ ngrok is not installed. Download it from https://ngrok.com/download and re-run." >&2
    exit 1
  fi
fi
if [ -n "$NGROK_TOKEN" ]; then
  ngrok config add-authtoken "$NGROK_TOKEN" >/dev/null
  echo "✓ ngrok authenticated"
fi

# 3. Project dependencies (Python 3.12 + venv)
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "⚠️ python3.12 not found — install it first (e.g. brew install python@3.12)" >&2
  exit 1
fi
if [ ! -x "$HERE/.venv/bin/python" ]; then
  echo "📦 Creating virtual environment..."
  python3.12 -m venv "$HERE/.venv"
fi
echo "📦 Installing project dependencies..."
"$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"

# 4. Bearer token (reused across restarts; --rotate regenerates)
if [ "$ROTATE" = 1 ] || [ ! -s "$TOKEN_FILE" ]; then
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32 > "$TOKEN_FILE"
  else
    "$HERE/.venv/bin/python" -c "import secrets; print(secrets.token_hex(32))" > "$TOKEN_FILE"
  fi
  chmod 600 "$TOKEN_FILE"
  echo "🔑 Generated bearer token -> .bridge-token"
else
  echo "🔑 Reusing bearer token from .bridge-token (./install.sh --rotate regenerates it)"
fi
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"

# 5. ngrok tunnel — reuse a live one for this port, else start a new one
ngrok_url_for_port() {
  curl -s --max-time 2 "$NGROK_API" | PORT="$PORT" "$HERE/.venv/bin/python" -c '
import json, os, sys
try:
    tunnels = json.load(sys.stdin).get("tunnels", [])
except Exception:
    tunnels = []
suffix = ":" + os.environ["PORT"]
for t in tunnels:
    if t.get("config", {}).get("addr", "").endswith(suffix) and t.get("public_url", "").startswith("https://"):
        print(t["public_url"])
        break
' 2>/dev/null
}
PUBLIC_URL="$(ngrok_url_for_port)"
if [ -n "$PUBLIC_URL" ]; then
  echo "🌐 Reusing live ngrok tunnel for port $PORT"
else
  echo "🌐 Starting ngrok tunnel on port $PORT..."
  if [ -s "$HERE/.ngrok-domain" ]; then
    nohup ngrok http --url="$(tr -d '[:space:]' < "$HERE/.ngrok-domain")" "$PORT" > "$HERE/ngrok.log" 2>&1 &
  else
    nohup ngrok http "$PORT" --log=stdout > "$HERE/ngrok.log" 2>&1 &
  fi
  for _ in $(seq 1 15); do
    sleep 1
    PUBLIC_URL="$(ngrok_url_for_port)"
    [ -n "$PUBLIC_URL" ] && break
  done
fi
if [ -z "$PUBLIC_URL" ]; then
  echo "⚠️ ngrok tunnel failed to start — last ngrok.log lines:" >&2
  tail -n 5 "$HERE/ngrok.log" >&2
  [ -z "$NGROK_TOKEN" ] && echo "hint: re-run and paste your Authtoken from https://dashboard.ngrok.com/get-started/your-authtoken" >&2
  exit 1
fi
HOST="${PUBLIC_URL#https://}"

command -v opencode >/dev/null 2>&1 || echo "⚠️ opencode CLI not on PATH — the worker needs it, the MCP server doesn't."

# 6. Stop a previous instance of our own server, if any
pkill -f "opencode_bridge_mcp.py --transport" 2>/dev/null && echo "↻ Stopped previous MCP server instance"

# 7. Configuration box
echo "========================================="
echo "🚀 SETUP COMPLETE"
echo "========================================="
echo "🔗 MCP URL:        $PUBLIC_URL/mcp"
echo "🔑 Bearer Token:   $TOKEN"
echo "========================================="
echo "Claude / ChatGPT web connector:"
echo "    URL:    $PUBLIC_URL/mcp"
echo "    Header: Authorization: Bearer $TOKEN"
echo "Claude Desktop: stdio mode — no URL or token needed."
echo "Dashboard:       $PUBLIC_URL/  (asks for the token)"
echo "Health check:    curl $PUBLIC_URL/health"
echo "Rotate token:    ./install.sh --rotate"
echo "========================================="
echo "Starting the MCP server now..."

# 8. Serve (foreground). Ctrl+C stops the server; ngrok stays up for the next run.
MCP_ALLOWED_HOSTS="$HOST" BRIDGE_AUTH_TOKEN="$TOKEN" exec "$HERE/.venv/bin/python" "$HERE/opencode_bridge_mcp.py" \
  --transport streamable-http --port "$PORT"
