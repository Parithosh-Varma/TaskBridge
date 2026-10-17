#!/bin/bash
# One command to (re)start the whole public stack:
#   1. cloudflared quick tunnel -> parse its public hostname
#   2. MCP server with exactly that hostname allowlisted
# Run again any time the URL changes; it re-pairs everything itself.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
# Fixed URL mode: set NGROK_DOMAIN (or write it to .ngrok-domain) after
# reserving a free static domain at https://dashboard.ngrok.com/domains
# e.g. echo "mybridge.ngrok-free.dev" > .ngrok-domain
NGROK_DOMAIN="${NGROK_DOMAIN:-$(cat "$HERE/.ngrok-domain" 2>/dev/null || true)}"
# Load bearer token if available
BRIDGE_AUTH_TOKEN="$(cat "$HERE/.bridge-token" 2>/dev/null || true)"
pkill -f "cloudflared tunnel --url" 2>/dev/null
pkill -f "ngrok http" 2>/dev/null
pkill -f "opencode_bridge_mcp.py --transport" 2>/dev/null
sleep 1
if [ -n "$NGROK_DOMAIN" ]; then
  nohup ngrok http --url="$NGROK_DOMAIN" 8000 > "$HERE/ngrok.log" 2>&1 &
  URL="https://$NGROK_DOMAIN"
  echo "waiting for ngrok tunnel..." && sleep 6
else
  nohup cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000 > "$HERE/cloudflared.log" 2>&1 &
  URL=""
  for _ in $(seq 1 30); do
    URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$HERE/cloudflared.log" 2>/dev/null | head -n 1)
    [ -n "$URL" ] && break
    sleep 1
  done
  [ -z "$URL" ] && echo "tunnel failed to start (see cloudflared.log)" && exit 1
fi
HOST="${URL#https://}"
MCP_ALLOWED_HOSTS="$HOST" BRIDGE_AUTH_TOKEN="$BRIDGE_AUTH_TOKEN" nohup "$HERE/.venv/bin/python" "$HERE/opencode_bridge_mcp.py" \
  --transport streamable-http --port 8000 > "$HERE/mcp_http.log" 2>&1 &
sleep 4
echo "MCP public URL: $URL/mcp"
curl -s -o /dev/null -w "tunnel check -> %{http_code} (421 empty-host-probe would mean allowlist mismatch)\n" \
  --max-time 10 "$URL/mcp" || true
