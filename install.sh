#!/bin/bash
# Install and setup TaskBridge with bearer auth
# Generates a secure token on first install, displays it once

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
TOKEN_FILE="$HERE/.bridge-token"

# Check if token already exists
if [ -f "$TOKEN_FILE" ]; then
    echo "✓ Bridge token already exists at $TOKEN_FILE"
    TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
    echo ""
    echo "Existing token: $TOKEN"
    echo ""
    echo "To rotate token, delete $TOKEN_FILE and re-run install.sh"
else
    # Generate secure token
    if command -v openssl >/dev/null 2>&1; then
        TOKEN=$(openssl rand -hex 32)
    elif command -v python3 >/dev/null 2>&1; then
        TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    else
        echo "Error: openssl or python3 required to generate token" >&2
        exit 1
    fi
    
    # Save token securely
    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    
    echo "✓ Generated new bridge token"
    echo ""
    echo "🔐 YOUR BRIDGE TOKEN (SAVE THIS!):"
    echo "=================================="
    echo "$TOKEN"
    echo "=================================="
    echo ""
    echo "This token unlocks your MCP server. Keep it safe!"
    echo "You can also find it in: $TOKEN_FILE"
    echo ""
fi

# Check Python environment
if [ ! -d "$HERE/.venv" ]; then
    echo "Creating virtual environment..."
    python3.12 -m venv "$HERE/.venv"
fi

# Install requirements
echo "Installing Python dependencies..."
"$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"

# Display next steps
cat << EOF

✓ Installation complete!

Next steps:
1. Set BRIDGE_AUTH_TOKEN env var (optional, defaults to .bridge-token):
   export BRIDGE_AUTH_TOKEN="$(cat $TOKEN_FILE)"

2. Start public server (with bearer auth):
   ./start_public.sh

3. Configure Claude Desktop:
   Copy config from claude_desktop_config.snippet.json
   Replace <REPO_PATH> with: $HERE

4. Public URL format:
   https://<your-tunnel>/mcp
   Authorization: Bearer $TOKEN

5. Dashboard:
   https://<your-tunnel>/
   (Will prompt for token on first visit)

EOF

# Show example curl
echo "Test with curl:"
echo "curl -H \"Authorization: Bearer $TOKEN\" https://<your-tunnel>/health"
