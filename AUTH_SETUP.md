# Bearer Authentication Setup

## Overview

TaskBridge now supports install-time bearer token authentication for HTTP mode, similar to ngrok. This protects your public MCP endpoint from unauthorized access.

## Installation

Run the install script once:

```bash
./install.sh
```

This will:
1. Prompt for your ngrok Authtoken (press Enter to keep an existing ngrok config)
2. Install dependencies into `.venv` (created if missing)
3. Generate a 64-character hex token into `.bridge-token`
4. Open the ngrok tunnel and pair `MCP_ALLOWED_HOSTS` automatically
5. Print the public URL **and** the bearer token box
6. Serve the MCP server in the foreground

The token is reused on later runs — regenerate it with `./install.sh --rotate`.
It remains safe with you and unlocks the MCP server.

## How It Works

### Token Storage
- Token is stored in `.bridge-token` file (chmod 600)
- Can be overridden via `BRIDGE_AUTH_TOKEN` environment variable
- Generated with `openssl rand -hex 32` or Python secrets

### Authentication Flow

```
Client (web/phone)
  ↓ Authorization: Bearer <token>
Public Tunnel (ngrok/cloudflared)
  ↓
Bearer Gate (opencode_bridge_mcp.py)
  ↓ 401 if invalid/missing
MCP Server + API Routes
```

### Protected Routes
- **Public**: `/health`, `/` (dashboard serves HTML)
- **Protected**: `/api/*`, `/mcp` (MCP endpoint)

### Dashboard Auth
The dispatch board at `/` automatically handles authentication:
1. Prompts for token on first visit
2. Stores token in sessionStorage
3. Includes Authorization header on all API calls
4. Shows token status in masthead (click to change)

## Usage

### Start Public Server
```bash
./start_public.sh
```
Automatically loads token from `.bridge-token` if present.

Output:
```
MCP public URL: https://xxxx.trycloudflare.com/mcp
```

### Access with curl
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-tunnel/mcp

curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-tunnel/api/overview
```

### Configure MCP Client
For Claude Web / ChatGPT Web, configure the MCP server URL with headers:
- URL: `https://your-tunnel/mcp`
- Headers: `Authorization: Bearer YOUR_TOKEN`

### OAuth Sign-In (claude.ai custom connectors)
Claude's custom connector flow negotiates MCP authorization before connecting.
TaskBridge publishes the required documents and flows on the same port/tunnel URL
(see `oauth_service.py`; no external identity provider needed):

- `/.well-known/oauth-protected-resource[/mcp]` — PRM (RFC 9728)
- `/.well-known/oauth-authorization-server` — AS metadata (RFC 8414)
- `/register` (dynamic client registration), `/authorize` (consent), `/token` (PKCE)

Flow: add the connector with `https://your-tunnel/mcp` → Claude detects OAuth →
your browser opens `https://your-tunnel/authorize` → paste your TaskBridge access
code (the `.bridge-token` value, or `TASKBRIDGE_CONSENT_SECRET` if you set one) →
click **"Yes, this was me who is logging in — Approve"**. Claude then carries an
access token (24 h, refreshable 30 d) automatically — no static header config needed.

Tokens are HS256 JWTs signed with `.oauth-key`; the static bearer token continues
to work everywhere (curl, dashboard, MCP) for backward compatibility.

Verify the whole chain anytime:

```bash
.venv/bin/python oauth_selftest.py http://127.0.0.1:8000
.venv/bin/python oauth_selftest.py https://your-tunnel
```

### Local Development
Stdio transport (Claude Desktop) doesn't require auth — it's localhost only.

## Security Notes

- Token is never logged
- Uses constant-time comparison (hmac.compare_digest)
- 401 returned for invalid/missing tokens
- `/health` remains open for monitoring
- Token can be rotated by deleting `.bridge-token` and re-running `./install.sh`

## Troubleshooting

**401 Unauthorized**
- Verify token matches `.bridge-token` file
- Check Authorization header format: `Bearer <token>` (no quotes)
- Ensure `BRIDGE_AUTH_TOKEN` env var is set if not using file

**Dashboard won't load**
- Clear sessionStorage for the site
- Check browser console for 401 errors
- Verify token via curl test

**Token not loading**
- Check `start_public.sh` loads `BRIDGE_AUTH_TOKEN`
- Verify `.bridge-token` exists and is readable
- Check file permissions (should be 600)
