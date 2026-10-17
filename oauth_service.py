"""Minimal OAuth 2.1 authorization server + Protected Resource Metadata, for TaskBridge.

Why: claude.ai custom connectors negotiate MCP authorization (RFC 9728 PRM discovery,
RFC 8414 AS metadata, RFC 7591 dynamic client registration, OAuth 2.1 + PKCE) before
they will connect to a remote MCP endpoint. This module implements exactly that
protocol for a single-user, self-hosted bridge — no Keycloak, no Docker, no new deps
(PyJWT is already used).

Endpoints (all served on the same port / tunnel URL as MCP):
  GET  /.well-known/oauth-protected-resource[/mcp]   PRM document (RFC 9728)
  GET  /.well-known/oauth-authorization-server       AS metadata (RFC 8414)
  GET  /.well-known/openid-configuration             OIDC alias of the above
  POST /register                                     dynamic client registration
  GET  /authorize                                    human consent page
  POST /authorize                                    approve -> one-time code (302)
  POST /token                                        code+PKCE or refresh -> JWT
  POST /revoke                                       consent-gated refresh revocation

Tokens are HS256 JWTs (key persisted in .oauth-key, chmod 600). Token expiry defaults:
  access: 24 h (TASKBRIDGE_TOKEN_TTL_SEC)
  refresh: 30 d (TASKBRIDGE_REFRESH_TTL_SEC), rotated on use (atomic: one
  redemption per refresh token, races lose).

The human barrier ("Yes, this was me who is logging in") is enforced at /authorize:
approval requires the consent secret — TASKBRIDGE_CONSENT_SECRET env, the
.consent-secret file, or (legacy) the .bridge-token value. Failed attempts hit a
sliding-window block (default 10 in 15 min, persisted until restart), and /revoke
shares the same gate. PKCE is S256 only (OAuth 2.1 — no "plain"). /register is
public (claude.ai registers before login) but throttled and capped.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

HERE = Path(__file__).parent
OAUTH_DB = Path(os.environ.get("OAUTH_DB_PATH", HERE / "oauth.db"))
KEY_FILE = HERE / ".oauth-key"
CONSENT_FILE = HERE / ".consent-secret"

ACCESS_TTL = int(os.environ.get("TASKBRIDGE_TOKEN_TTL_SEC", str(24 * 3600)))
REFRESH_TTL = int(os.environ.get("TASKBRIDGE_REFRESH_TTL_SEC", str(30 * 86400)))
CODE_TTL = 300
SUPPORTED_SCOPES = ["mcp:tools"]

# /register is unauthenticated by protocol necessity (claude.ai calls it before
# any login), so it gets a global sliding-window throttle plus a row cap:
_REG_WINDOW_SEC = 600
_REG_MAX_PER_WINDOW = 20
_REG_MAX_ROWS = 500
_reg_log: list[float] = []  # single-process server; no lock needed at this scale

# Redirect-URI allowlist for dynamic client registration: only these hosts may
# receive an authorization code (plus http loopback for local MCP clients).
# Extend with TASKBRIDGE_ALLOWED_REDIRECT_HOSTS=host1,host2 (subdomains match).
ALLOWED_REDIRECT_HOSTS = [h.strip().lower() for h in os.environ.get(
    "TASKBRIDGE_ALLOWED_REDIRECT_HOSTS",
    "claude.ai,claude.com,anthropic.com,chatgpt.com,openai.com",
).split(",") if h.strip()]
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Consent brute-force guard: N failed "this was me" attempts inside the window
# block further attempts (in-memory, resets on restart).
CONSENT_MAX_ATTEMPTS = max(1, int(os.environ.get("TASKBRIDGE_CONSENT_MAX_ATTEMPTS", "10")))
CONSENT_WINDOW_SEC = max(60, int(os.environ.get("TASKBRIDGE_CONSENT_WINDOW_SEC", "900")))

# Cap on registered OAuth clients — /register is open, so the table must not grow forever.
MAX_CLIENTS = max(10, int(os.environ.get("TASKBRIDGE_MAX_CLIENTS", "200")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_clients (
  client_id TEXT PRIMARY KEY,
  client_name TEXT DEFAULT '',
  redirect_uris TEXT DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
  code TEXT PRIMARY KEY,
  client_id TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  challenge TEXT NOT NULL,
  challenge_method TEXT NOT NULL,
  resource TEXT DEFAULT '',
  scope TEXT DEFAULT '',
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_refresh (
  jti TEXT PRIMARY KEY,
  client_id TEXT NOT NULL,
  expires_at REAL NOT NULL
);
"""

# ---------------------------------------------------------------- key handling


def _signing_key() -> str:
    """Load (or create once) the HS256 signing key."""
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    KEY_FILE.write_text(key)
    try:
        KEY_FILE.chmod(0o600)
    except OSError:
        pass
    return key


_KEY = _signing_key()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(OAUTH_DB)
    conn.executescript(_SCHEMA)
    try:
        OAUTH_DB.chmod(0o600)
    except OSError:
        pass
    return conn


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _purge_expired(conn: sqlite3.Connection) -> None:
    now = time.time()
    conn.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (now,))
    conn.execute("DELETE FROM oauth_refresh WHERE expires_at < ?", (now,))


def _load_bridge_token() -> str:
    """Own copy of the static-token loader (env var or .bridge-token file)."""
    token = os.environ.get("BRIDGE_AUTH_TOKEN", "").strip()
    if not token:
        try:
            token_file = HERE / ".bridge-token"
            if token_file.exists():
                token = token_file.read_text().strip()
        except (OSError, ValueError):
            pass
    return token


def _static_secret() -> str:
    """The human's consent secret: TASKBRIDGE_CONSENT_SECRET env, then the
    .consent-secret file, then (legacy) the bridge token. Kept separate from
    the API bearer token by default so the consent gate and the MCP
    credential aren't the same string."""
    secret = os.environ.get("TASKBRIDGE_CONSENT_SECRET", "").strip()
    if secret:
        return secret
    try:
        if CONSENT_FILE.exists():
            file_secret = CONSENT_FILE.read_text().strip()
            if file_secret:
                return file_secret
    except (OSError, ValueError):
        pass
    return _load_bridge_token()


def consent_secret_matches(value: str) -> bool:
    expected = _static_secret()
    return bool(expected) and hmac.compare_digest(value.strip(), expected)


def _redirect_allowed(uri: str) -> bool:
    """True if `uri` may receive an authorization code (parsed allowlist — no prefix games)."""
    if not isinstance(uri, str):
        return False
    parts = urlsplit(uri)
    host = (parts.hostname or "").lower()
    if not host:
        return False
    if parts.scheme == "http" and host in LOOPBACK_HOSTS:
        return True
    if parts.scheme != "https":
        return False
    return any(host == d or host.endswith("." + d) for d in ALLOWED_REDIRECT_HOSTS)


_consent_failures: list[float] = []


def consent_rate_limited() -> int:
    """Seconds to wait before another consent attempt, or 0 when allowed."""
    now = time.time()
    fresh = [t for t in _consent_failures if now - t < CONSENT_WINDOW_SEC]
    _consent_failures[:] = fresh
    if len(fresh) < CONSENT_MAX_ATTEMPTS:
        return 0
    return max(1, int(CONSENT_WINDOW_SEC - (now - fresh[0])))


def _consent_failed() -> None:
    _consent_failures.append(time.time())


def _clean_scope(raw: str) -> str:
    """Keep only supported scopes; default to all supported when nothing parses."""
    kept = [s for s in (raw or "").replace(",", " ").split() if s in SUPPORTED_SCOPES]
    return " ".join(kept) or " ".join(SUPPORTED_SCOPES)


def _origin_from_request(request: Request) -> str:
    """Public origin as the caller sees it (tunnel host beats local)."""
    if os.environ.get("MCP_PUBLIC_URL", "").strip():
        return os.environ["MCP_PUBLIC_URL"].strip().rstrip("/")
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if not proto:
        proto = request.url.scheme
    host = request.headers.get("host") or f"127.0.0.1:{request.url.port or ''}"
    return f"{proto}://{host}".rstrip("/")


# ---------------------------------------------------------------- token logic


def _aud_matches(aud: str | list[str], origin: str) -> bool:
    """Token aud must equal the origin or the origin's /mcp resource (RFC 8707)."""
    allowed = {origin.rstrip("/"), (origin.rstrip("/") + "/mcp").rstrip("/")}
    auds = aud if isinstance(aud, list) else [aud]
    return any(str(a).rstrip("/") in allowed for a in auds)


def verify_bearer(token: str, origin: str) -> bool:
    """True for the static bridge token OR a locally-issued OAuth JWT."""
    static_token = _load_bridge_token()
    if static_token and hmac.compare_digest(token.strip(), static_token):
        return True
    try:
        claims = jwt.decode(
            token, _KEY, algorithms=["HS256"],
            audience=_aud_allowed(origin),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        return False
    if claims.get("iss", "").rstrip("/") != origin.rstrip("/"):
        return False
    if not _aud_matches(claims.get("aud", ""), origin):
        return False
    if claims.get("sub") == "refresh":
        return False  # refresh tokens only feed /token, never /mcp
    return True


def _aud_allowed(origin: str) -> list[str]:
    base = origin.rstrip("/")
    return [base, base + "/mcp"]


def _issue_access(origin: str, client_id: str, resource: str, scope: str) -> str:
    payload = {
        "iss": origin,
        "sub": f"client:{client_id}",
        "aud": (resource or origin).rstrip("/") or origin,
        "scope": scope,
        "cid": client_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ACCESS_TTL,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _KEY, algorithm="HS256")


def _issue_refresh(origin: str, client_id: str, resource: str) -> str:
    jti = uuid.uuid4().hex
    payload = {
        "iss": origin,
        "sub": "refresh",
        "aud": (resource or origin).rstrip("/") or origin,
        "cid": client_id,
        "jti": jti,
        "iat": int(time.time()),
        "exp": int(time.time()) + REFRESH_TTL,
    }
    with _db() as conn:
        conn.execute(
            "INSERT INTO oauth_refresh (jti, client_id, expires_at) VALUES (?,?,?)",
            (jti, client_id, time.time() + REFRESH_TTL),
        )
        conn.commit()
    return jwt.encode(payload, _KEY, algorithm="HS256")


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _pkce_ok(challenge: str, method: str, verifier: str) -> bool:
    if method == "S256":
        return hmac.compare_digest(challenge, _b64url_no_pad(hashlib.sha256(verifier.encode()).digest()))
    return False


def _oauth_error(error: str, status: int = 400, description: str = "",
                 headers: dict | None = None) -> JSONResponse:
    body = {"error": error}
    if description:
        body["error_description"] = description
    return JSONResponse(body, status_code=status, headers=headers)


# ---------------------------------------------------------------- routes


def register_routes(mcp) -> None:
    """Attach the OAuth endpoints to a FastMCP instance via custom routes."""

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    @mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
    async def protected_resource_metadata(request: Request) -> JSONResponse:
        origin = _origin_from_request(request)
        return JSONResponse(
            {
                "resource": f"{origin}/mcp",
                "authorization_servers": [origin],
                "scopes_supported": SUPPORTED_SCOPES,
                "bearer_methods_supported": ["header"],
                "resource_documentation": "https://github.com/Parithosh-Varma/TaskBridge",
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    def _as_metadata(origin: str) -> dict:
        return {
            "issuer": origin,
            "authorization_endpoint": f"{origin}/authorize",
            "token_endpoint": f"{origin}/token",
            "registration_endpoint": f"{origin}/register",
            "revocation_endpoint": f"{origin}/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": SUPPORTED_SCOPES,
            "service_documentation": "https://github.com/Parithosh-Varma/TaskBridge",
        }

    # The /mcp-suffixed variant matters: ChatGPT fetches
    # /.well-known/oauth-authorization-server/mcp (Claude only asks for the
    # top-level form) and fails the connector with "Failed to resolve OAuth
    # client" when it is missing.
    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    @mcp.custom_route("/.well-known/oauth-authorization-server/mcp", methods=["GET"])
    @mcp.custom_route("/.well-known/oauth-authorization-server/mcp/", methods=["GET"])
    @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
    async def authorization_server_metadata(request: Request) -> JSONResponse:
        origin = _origin_from_request(request)
        return JSONResponse(
            _as_metadata(origin),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @mcp.custom_route("/register", methods=["POST"])
    async def register(request: Request) -> JSONResponse:
        # global sliding-window throttle: unauthenticated endpoint, so keep it slow
        now = time.time()
        while _reg_log and _reg_log[0] <= now - _REG_WINDOW_SEC:
            _reg_log.pop(0)
        if len(_reg_log) >= _REG_MAX_PER_WINDOW:
            return _oauth_error("too_many_requests", 429,
                                "too many registrations — retry later",
                                headers={"Retry-After": "60"})
        _reg_log.append(now)
        try:
            body = await request.json()
        except Exception:
            return _oauth_error("invalid_request", 400, "body must be JSON")
        uris = body.get("redirect_uris") or []
        if not isinstance(uris, list) or not uris:
            return _oauth_error("invalid_request", 400, "redirect_uris required")
        bad = [u for u in uris if not _redirect_allowed(u)]
        if bad:
            return _oauth_error("invalid_request", 400,
                                f"redirect_uri not allowed: {bad[0]} "
                                "(extend TASKBRIDGE_ALLOWED_REDIRECT_HOSTS to permit it)")
        with _db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM oauth_clients").fetchone()[0]
        if count >= MAX_CLIENTS:
            return _oauth_error("temporarily_unavailable", 429,
                                f"client limit reached ({MAX_CLIENTS}) — prune oauth.db to reset")
        client_id = uuid.uuid4().hex[:16]
        with _db() as conn:
            conn.execute(
                "INSERT INTO oauth_clients (client_id, client_name, redirect_uris, created_at) VALUES (?,?,?,?)",
                (client_id, str(body.get("client_name", ""))[:120], json.dumps(uris), _now_iso()),
            )
            _purge_expired(conn)
            conn.commit()
        return JSONResponse(
            {
                "client_id": client_id,
                "client_name": body.get("client_name", ""),
                "redirect_uris": uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "client_id_issued_at": int(time.time()),
            },
            status_code=201,
        )

    @mcp.custom_route("/authorize", methods=["GET"])
    async def authorize_page(request: Request) -> Response:
        import html as _html

        p = request.query_params

        def esc(v: str) -> str:
            return _html.escape(str(v), quote=True)

        client_id = p.get("client_id", "")
        redirect_uri = p.get("redirect_uri", "")
        challenge = p.get("code_challenge", "")
        challenge_method = p.get("code_challenge_method", "")
        resource = p.get("resource", "")
        scope = p.get("scope", "")
        state = p.get("state", "")
        origin = _origin_from_request(request)
        with _db() as conn:
            row = conn.execute(
                "SELECT client_name, redirect_uris, created_at FROM oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if not row:
            return _oauth_error("invalid_client", 401, "unknown or unregistered client_id")
        uris = json.loads(row[1])
        if redirect_uri not in uris or not _redirect_allowed(redirect_uri):
            return _oauth_error("invalid_request", 400, "redirect_uri not registered for this client")
        if not challenge or challenge_method != "S256":
            return _oauth_error("invalid_request", 400, "code_challenge (PKCE S256) required")
        _aud_ok = _aud_matches(resource or f"{origin}/mcp", origin)
        warn = "" if _aud_ok else "<p><em>Note: resource is outside this server's origin — it will still be bound as the token audience.</em></p>"
        client_name = esc(row[0] or f"App {esc(client_id[:8])}")
        display_resource = esc(resource or (request.headers.get("host", "") + "/mcp"))
        reg_age = ""
        try:
            import datetime as _dt
            created = _dt.datetime.fromisoformat(str(row[2]))
            age_min = (_dt.datetime.now(_dt.timezone.utc) - created).total_seconds() / 60
            if age_min < 2:
                reg_age = "just now"
            elif age_min < 60:
                reg_age = f"{int(age_min)} min ago"
            elif age_min < 24 * 60:
                reg_age = f"{int(age_min / 60)} h ago"
            else:
                reg_age = created.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            reg_age = "unknown"
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TaskBridge — Connect approval</title>
<style>
  body {{ margin:0; font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         background:#101014; color:#EDEBE5; display:flex; min-height:100vh; align-items:center; justify-content:center; padding:20px; box-sizing:border-box; }}
  .card {{ background:#1e1712; border:1px solid #3a2f22; border-radius:10px; padding:28px; max-width:440px; width:100%; }}
  h1 {{ font-size:19px; margin:0 0 6px; letter-spacing:.01em; }}
  p {{ margin:6px 0; color:#ab9c83; }}
  .mono {{ font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:12.5px;
           background:#14100b; border:1px solid #3a2f22; border-radius:6px; padding:10px 12px; color:#f2a007; word-break:break-all; }}
  form {{ margin-top:18px; }}
  input[type=password] {{ width:100%; box-sizing:border-box; padding:10px 12px; border-radius:6px;
           border:1px solid #3a2f22; background:#14100b; color:#EDEBE5; font-size:14px; }}
  button {{ margin-top:14px; width:100%; padding:12px; border-radius:6px; border:1px solid #8fc39a;
           background:#8fc39a; color:#14100b; font-weight:600; font-size:15px; cursor:pointer; }}
  button:hover {{ filter:brightness(1.06); }}
  .brand {{ color:#f2a007; font-weight:700; letter-spacing:.02em; }}
  small {{ color:#ab9c83; }}
</style></head>
<body><div class="card">
  <p class="brand">⇄ TaskBridge</p>
  <h1>Connect approval</h1>
  <p><strong>{client_name}</strong> (client registered: {reg_age}) wants to reach the TaskBridge dispatch queue:</p>
  <div class="mono">{display_resource}</div>
  <p>Scope requested: <code>{esc(scope or "mcp:tools")}</code></p>
  <p>Approving gives this app a bearer token — enough to <strong>queue and steer agent tasks
  that run code, edit files, and use your credentials on this machine</strong>. Only approve apps you recognize.</p>
  {warn}
  <form method="post" action="/authorize">
    <input type="hidden" name="client_id" value="{esc(client_id)}">
    <input type="hidden" name="redirect_uri" value="{esc(redirect_uri)}">
    <input type="hidden" name="code_challenge" value="{esc(challenge)}">
    <input type="hidden" name="code_challenge_method" value="{esc(challenge_method)}">
    <input type="hidden" name="resource" value="{esc(resource)}">
    <input type="hidden" name="scope" value="{esc(scope)}">
    <input type="hidden" name="state" value="{esc(state)}">
    <p>Access code <small>(from .consent-secret or TASKBRIDGE_CONSENT_SECRET — proves “this was me”)</small>:</p>
    <input type="password" name="consent_secret" required autocomplete="off" placeholder="paste your access code">
    <button type="submit">Yes, this was me who is logging in — Approve</button>
  </form>
  <p><small>One-time code lives 5 minutes. Tokens issued: access {ACCESS_TTL // 3600}h, refresh {REFRESH_TTL // 86400}d.</small></p>
</div></body></html>"""
        return Response(html, media_type="text/html", headers={
            "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; "
                                        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        })

    @mcp.custom_route("/authorize", methods=["POST"])
    async def authorize_submit(request: Request) -> Response:
        form = await request.form()
        p = {k: str(form.get(k, "")) for k in (
            "client_id", "redirect_uri", "code_challenge", "code_challenge_method",
            "resource", "scope", "state", "consent_secret")}
        if not p["code_challenge"] or p["code_challenge_method"] != "S256":
            # same S256 rule as the GET page — an approval must never mint a
            # code bound to a weaker challenge scheme
            return _oauth_error("invalid_request", 400, "code_challenge (PKCE S256) required")
        wait = consent_rate_limited()
        if wait:
            return _oauth_error("too_many_requests", 429,
                                f"too many failed attempts — retry in {wait}s",
                                headers={"Retry-After": str(wait)})
        if not consent_secret_matches(p["consent_secret"]):
            _consent_failed()
            return _oauth_error("access_denied", 403, "access code did not match — ‘this was me’ could not be confirmed")
        _consent_failures.clear()
        with _db() as conn:
            row = conn.execute(
                "SELECT redirect_uris FROM oauth_clients WHERE client_id = ?", (p["client_id"],)
            ).fetchone()
        if not row:
            return _oauth_error("invalid_client", 401, "unknown client")
        uris = json.loads(row[0])
        if p["redirect_uri"] not in uris or not _redirect_allowed(p["redirect_uri"]):
            return _oauth_error("invalid_request", 400, "redirect_uri not registered")
        code = secrets.token_urlsafe(32)
        with _db() as conn:
            _purge_expired(conn)
            conn.execute(
                "INSERT INTO oauth_codes (code, client_id, redirect_uri, challenge, challenge_method, resource, scope, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (code, p["client_id"], p["redirect_uri"], p["code_challenge"],
                 p["code_challenge_method"], p["resource"], _clean_scope(p["scope"]),
                 time.time() + CODE_TTL),
            )
            conn.commit()
        from urllib.parse import urlencode

        sep = "&" if "?" in p["redirect_uri"] else "?"
        params = {"code": code}
        if p["state"]:
            params["state"] = p["state"]
        return Response(
            status_code=302,
            headers={"Location": f"{p['redirect_uri']}{sep}{urlencode(params)}"},
        )

    @mcp.custom_route("/token", methods=["POST"])
    async def token_endpoint(request: Request) -> Response:
        ctype = (request.headers.get("content-type") or "").split(";")[0]
        if ctype == "application/json":
            try:
                form = {k: str(v) for k, v in (await request.json()).items()}
            except Exception:
                return _oauth_error("invalid_request", 400, "malformed JSON body")
        else:
            form = dict(await request.form())
        grant = form.get("grant_type", "")
        client_id = (form.get("client_id") or "").strip()
        origin = _origin_from_request(request)

        def _client_exists(cid: str) -> bool:
            with _db() as conn:
                return conn.execute(
                    "SELECT 1 FROM oauth_clients WHERE client_id = ?", (cid,)
                ).fetchone() is not None

        if grant == "authorization_code":
            code = form.get("code", "")
            with _db() as conn:
                prow = conn.execute(
                    "SELECT client_id, redirect_uri, challenge, challenge_method, resource, scope, expires_at FROM oauth_codes WHERE code = ?",
                    (code,),
                ).fetchone()
            if not prow:
                return _oauth_error("invalid_grant", 400, "code not found, expired or already used")
            if not client_id:
                # ChatGPT omits client_id at token exchange. The one-time code
                # row was already bound to a single client at /authorize time,
                # so restore that binding instead of failing the client lookup.
                client_id = prow[0]
            if not _client_exists(client_id):
                return _oauth_error("invalid_client", 401, "unknown client")
            if prow[0] != client_id:
                return _oauth_error("invalid_grant", 400, "code belongs to another client")
            redirect_uri = form.get("redirect_uri", "") or prow[1]
            if prow[1] != redirect_uri:
                return _oauth_error("invalid_grant", 400, "redirect_uri mismatch")
            verifier = form.get("code_verifier", "")
            if not verifier or not _pkce_ok(prow[2], prow[3], verifier):
                return _oauth_error("invalid_grant", 400, "PKCE verification failed")
            with _db() as conn:  # one-time use: consume atomically, races lose
                cur = conn.execute("DELETE FROM oauth_codes WHERE code = ?", (code,))
                conn.commit()
                consumed = cur.rowcount
            if consumed != 1:  # concurrent redemption already burned this code
                return _oauth_error("invalid_grant", 400, "code not found, expired or already used")
            access = _issue_access(origin, client_id, prow[4], prow[5])
            refresh = _issue_refresh(origin, client_id, prow[4])
            return JSONResponse(
                {
                    "access_token": access,
                    "token_type": "Bearer",
                    "expires_in": ACCESS_TTL,
                    "refresh_token": refresh,
                    "scope": prow[5] or " ".join(SUPPORTED_SCOPES),
                }
            )

        if grant == "refresh_token":
            try:
                claims = jwt.decode(form.get("refresh_token", ""), _KEY,
                                    algorithms=["HS256"], audience=_aud_allowed(origin),
                                    options={"require": ["exp", "jti", "sub"]})
            except jwt.PyJWTError:
                return _oauth_error("invalid_grant", 400, "refresh token invalid or expired")
            if claims.get("sub") != "refresh":
                return _oauth_error("invalid_grant", 400, "not a refresh token")
            if claims.get("iss", "").rstrip("/") != origin.rstrip("/"):
                return _oauth_error("invalid_grant", 400, "issuer mismatch")
            jti = claims["jti"]
            if not client_id:
                # ChatGPT-style refreshes may omit client_id; the signed cid
                # claim is the binding and is verified in the next line.
                client_id = claims.get("cid", "")
            if claims.get("cid", "") != client_id:
                return _oauth_error("invalid_grant", 400, "refresh token belongs to another client")
            with _db() as conn:
                cur = conn.execute("DELETE FROM oauth_refresh WHERE jti = ?", (jti,))
                consumed = cur.rowcount
                conn.commit()
            if consumed != 1:  # row vanished between SELECT and DELETE — token already used
                return _oauth_error("invalid_grant", 400, "refresh token already rotated or revoked")
            resource = str(claims.get("aud", "") or "")
            access = _issue_access(origin, client_id, resource, form.get("scope", ""))
            refresh = _issue_refresh(origin, client_id, resource)
            return JSONResponse(
                {
                    "access_token": access,
                    "token_type": "Bearer",
                    "expires_in": ACCESS_TTL,
                    "refresh_token": refresh,
                    "scope": _clean_scope(form.get("scope", "")),
                }
            )

        return _oauth_error("unsupported_grant_type", 400, f"grant_type {grant!r} not supported")

    @mcp.custom_route("/revoke", methods=["POST"])
    async def revoke(request: Request) -> JSONResponse:
        """Consent-gated revocation (RFC 7009 spirit, single-user flavor).

        Body (JSON or form): consent_secret + either client_id (revoke every
        refresh token and pending code for that client) or token=<refresh JWT>
        (revoke that one). Access tokens are stateless JWTs and die within
        ACCESS_TTL — revoking refresh stops all renewals going forward.
        """
        ctype = (request.headers.get("content-type") or "").split(";")[0]
        try:
            if ctype == "application/json":
                form = {k: str(v) for k, v in (await request.json()).items()}
            else:
                form = dict(await request.form())
        except Exception:
            return _oauth_error("invalid_request", 400, "malformed body")
        wait = consent_rate_limited()
        if wait:
            return _oauth_error("too_many_requests", 429,
                                f"too many failed attempts — retry in {wait}s",
                                headers={"Retry-After": str(wait)})
        if not consent_secret_matches(str(form.get("consent_secret", ""))):
            _consent_failed()
            return _oauth_error("access_denied", 403, "access code did not match")
        _consent_failures.clear()
        client_id = (form.get("client_id") or "").strip()
        token_in = (form.get("token") or "").strip()
        with _db() as conn:
            if client_id:
                cur = conn.execute("DELETE FROM oauth_refresh WHERE client_id = ?", (client_id,))
                codes = conn.execute("DELETE FROM oauth_codes WHERE client_id = ?", (client_id,))
                conn.commit()
            elif token_in:
                try:
                    claims = jwt.decode(token_in, _KEY, algorithms=["HS256"],
                                        options={"require": ["exp", "jti", "sub"]})
                except jwt.PyJWTError:
                    return _oauth_error("invalid_request", 400, "token invalid")
                if claims.get("sub") != "refresh":
                    return _oauth_error("invalid_request", 400, "pass a refresh token (sub != refresh)")
                cur = conn.execute("DELETE FROM oauth_refresh WHERE jti = ?", (claims["jti"],))
                conn.commit()
            else:
                return _oauth_error("invalid_request", 400, "client_id or token required")
            n = cur.rowcount
        return JSONResponse({"revoked": max(0, n), "scope": "client" if client_id else "token"})
