#!/usr/bin/env python3
"""End-to-end selftest for the MCP authorization flow built into TaskBridge.

Simulates exactly what an MCP client (claude.ai custom connector) does:
  1. POST /mcp initialize with no token    -> 401 + WWW-Authenticate(PRM pointer)
  2. GET  PRM                              -> authorization_servers
  3. GET  /.well-known/oauth-authorization-server -> endpoints
  4. POST /register                        -> client_id (DCR)
  5. GET  /authorize                       -> consent page
  6. POST /authorize with consent secret   -> 302 with one-time code
  7. POST /token + PKCE verifier           -> access + refresh JWT
  8. POST /mcp initialize WITH token       -> 200 (and 401 for a refresh token)
  9. ChatGPT-style: AS metadata /mcp path, chatgpt.com callback DCR, token
     grant with client_id omitted, /mcp/ alias, refresh without client_id
 10. Negatives: wrong secret, code reuse, bad verifier, rotated refresh
 11. Static bridge token still accepted; health/openid aliases open.

Usage: .venv/bin/python oauth_selftest.py [base_url]   (default http://127.0.0.1:8000)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
TOKEN_FILE = Path(__file__).parent / ".bridge-token"
CONSENT_FILE = Path(__file__).parent / ".consent-secret"
SECRET = (os.environ.get("TASKBRIDGE_CONSENT_SECRET")
          or (CONSENT_FILE.read_text().strip() if CONSENT_FILE.exists() else "")
          or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")).strip()
# the static API bearer is a different secret from the consent pin by default
STATIC = (os.environ.get("BRIDGE_AUTH_TOKEN")
          or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")).strip()
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
# ChatGPT developer-mode connector callback (registered automatically by
# ChatGPT's client; must pass the server's redirect allowlist)
GPT_CALLBACK = "https://chatgpt.com/backend-api/connector/connector_platform_oauth/callback"
GPT_ALLOWLISTED: list[str] = []  # filled by section 4 when registration succeeds

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ok  - {name}")
    else:
        FAIL.append(f"{name}: {detail}")
        print(f"  FAIL - {name} [{detail}]")


def http(method: str, url: str, *, data: dict | None = None,
         form: bool = False, headers: dict | None = None):
    """Returns (status, headers, parsed). 302s are captured, not followed."""
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), _parse(raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), _parse(raw)


def _parse(raw: bytes):
    text = raw.decode(errors="replace")
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return text


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def get_code(origin: str, client_id: str, challenge: str, secret: str,
             method: str = "S256", redirect_uri: str = CALLBACK) -> str:
    """POST /authorize with the correct secret, return the one-time code from the 302."""
    status, headers, body = http("POST", f"{origin}/authorize", data={
        "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": method,
        "resource": f"{origin}/mcp", "scope": "mcp:tools", "state": "st-123",
        "consent_secret": secret,
    }, form=True)
    loc = (headers.get("Location") or headers.get("location") or "")
    if status != 302 or "code=" not in loc:
        raise AssertionError(f"expected 302 with code, got {status} loc={loc!r} body={body}")
    return urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["code"][0]


def token(origin: str, fields: dict):
    return http("POST", f"{origin}/token", data={"client_id": "x", **fields}, form=True)


def main() -> int:
    print(f"Selftest against {BASE}\n")

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "selftest", "version": "1.0"}}}
    accept = {"Accept": "application/json, text/event-stream"}

    # 1. unauthenticated MCP call -> 401 + PRM pointer
    status, headers, _ = http("POST", f"{BASE}/mcp", data=init, headers=accept)
    wa = next((v for k, v in headers.items() if k.lower() == "www-authenticate"), "")
    check("401 without token", status == 401, f"got {status}")
    check("WWW-Authenticate has resource_metadata", "resource_metadata=" in wa, f"got {wa!r}")

    # 2. PRM document
    status, _, prm = http("GET", f"{BASE}/.well-known/oauth-protected-resource/mcp")
    check("PRM served", status == 200 and isinstance(prm, dict) and prm.get("resource"),
          f"{status} {prm}")
    as_url = (prm.get("authorization_servers") or [BASE])[0]

    # 3. AS metadata (+ OIDC alias)
    status, _, asm = http("GET", f"{as_url}/.well-known/oauth-authorization-server")
    check("AS metadata served", status == 200 and asm.get("issuer"), f"{status} {asm}")
    check("PKCE S256 advertised",
          "S256" in (asm.get("code_challenge_methods_supported") or []), f"{asm}")
    status, _, _ = http("GET", f"{as_url}/.well-known/openid-configuration")
    check("openid-configuration alias", status == 200, f"got {status}")
    status, _, asm_mcp = http("GET", f"{as_url}/.well-known/oauth-authorization-server/mcp")
    check("AS metadata at /mcp path (ChatGPT discovery)",
          status == 200 and isinstance(asm_mcp, dict) and asm_mcp.get("issuer"), f"{status}")

    # 4. dynamic client registration (+ off-allowlist redirect rejected)
    status, _, reg = http("POST", f"{as_url}/register",
                          data={"client_name": "selftest",
                                "redirect_uris": [CALLBACK,
                                                  "https://claude.com/api/mcp/auth_callback"]})
    client_id = reg.get("client_id", "") if isinstance(reg, dict) else ""
    check("DCR returns client_id", status == 201 and bool(client_id), f"{status} {reg}")
    status, _, _ = http("POST", f"{as_url}/register",
                        data={"client_name": "selftest-bad",
                              "redirect_uris": ["https://attacker.example.com/cb"]})
    check("DCR rejects off-allowlist redirect_uri", status == 400, f"got {status}")
    status, _, greg = http("POST", f"{as_url}/register",
                           data={"client_name": "ChatGPT Connector",
                                 "redirect_uris": [GPT_CALLBACK]})
    gpt_id = greg.get("client_id", "") if isinstance(greg, dict) else ""
    GPT_ALLOWLISTED.append(gpt_id)
    check("DCR accepts chatgpt.com callback (ChatGPT client)",
          status == 201 and bool(gpt_id), f"{status} {greg}")

    # 5. consent page renders with the human barrier copy
    verifier = uuid.uuid4().hex + uuid.uuid4().hex
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    qs = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK,
        "scope": "mcp:tools", "state": "st-123", "resource": f"{BASE}/mcp",
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    status, _, page = http("GET", f"{as_url}/authorize?{qs}")
    check("consent page renders", status == 200 and "this was me" in str(page), f"{status}")

    # 6. approve with the access code -> one-time code
    authz_code = get_code(BASE, client_id, challenge, SECRET)
    check("approve -> 302 with code", bool(authz_code), "no code")
    try:
        get_code(BASE, client_id, challenge, SECRET, method="plain")
        check("plain PKCE rejected", False, "plain method produced a code")
    except AssertionError:
        check("plain PKCE rejected", True)
    status, _, _ = http("POST", f"{as_url}/authorize", data={
        "client_id": client_id, "redirect_uri": CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": f"{BASE}/mcp", "scope": "mcp:tools", "state": "x",
        "consent_secret": "nope-wrong",
    }, form=True)
    check("wrong consent secret rejected", status == 403, f"got {status}")

    # 7. token exchange with PKCE
    status, _, tok = token(BASE, {
        "grant_type": "authorization_code", "code": authz_code,
        "redirect_uri": CALLBACK, "client_id": client_id,
        "code_verifier": verifier,
    })
    access = tok.get("access_token", "") if isinstance(tok, dict) else ""
    refresh = tok.get("refresh_token", "") if isinstance(tok, dict) else ""
    check("token exchange ok", status == 200 and access and refresh, f"{status} {tok}")
    check("access token is a JWT", len(access.split(".")) == 3, access[:40])

    # 8. authenticated MCP initialize
    status, _, _ = http("POST", f"{BASE}/mcp", data=init,
                        headers={**accept, "Authorization": f"Bearer {access}"})
    check("MCP initialize with OAuth token -> 200", status == 200, f"got {status}")
    status, _, _ = http("POST", f"{BASE}/mcp", data=init,
                        headers={**accept, "Authorization": f"Bearer {refresh}"})
    check("refresh token rejected at /mcp", status == 401, f"got {status}")

    # 9. ChatGPT-style flow: client_id omitted at /token, /mcp/ alias.
    #    Skips gracefully when chatgpt.com is not on the redirect allowlist.
    if gpt_id:
        verifier3 = uuid.uuid4().hex + uuid.uuid4().hex
        challenge3 = b64url(hashlib.sha256(verifier3.encode()).digest())
        code3 = get_code(BASE, gpt_id, challenge3, SECRET, redirect_uri=GPT_CALLBACK)
        status, _, tok3 = http("POST", f"{BASE}/token", data={
            "grant_type": "authorization_code", "code": code3,
            "redirect_uri": GPT_CALLBACK, "code_verifier": verifier3,
        }, form=True)
        gpt_access = tok3.get("access_token", "") if isinstance(tok3, dict) else ""
        check("ChatGPT-style token (client_id omitted)",
              status == 200 and gpt_access, f"{status} {tok3}")
        status, _, _ = http("POST", f"{BASE}/mcp/", data=init,
                            headers={**accept, "Authorization": f"Bearer {gpt_access}"})
        check("MCP initialize at /mcp/ alias -> 200", status == 200, f"got {status}")
        gpt_refresh = tok3.get("refresh_token", "") if isinstance(tok3, dict) else ""
        status, _, tokr = http("POST", f"{BASE}/token", data={
            "grant_type": "refresh_token", "refresh_token": gpt_refresh,
        }, form=True)
        got_refresh = isinstance(tokr, dict) and tokr.get("refresh_token", "")
        check("ChatGPT-style refresh (client_id omitted)",
              status == 200 and got_refresh, f"{status} {tokr}")
    else:
        print("  skip - ChatGPT flow (chatgpt.com callback not allowlisted)")

    # 10. negatives
    status, _, err = token(BASE, {
        "grant_type": "authorization_code", "code": authz_code,
        "redirect_uri": CALLBACK, "client_id": client_id, "code_verifier": verifier,
    })
    check("code reuse rejected (one-time)",
          status == 400 and isinstance(err, dict) and err.get("error") == "invalid_grant",
          f"{status} {err}")

    verifier2 = uuid.uuid4().hex + uuid.uuid4().hex
    challenge2 = b64url(hashlib.sha256(verifier2.encode()).digest())
    code2 = get_code(BASE, client_id, challenge2, SECRET)
    status, _, _ = token(BASE, {
        "grant_type": "authorization_code", "code": code2,
        "redirect_uri": CALLBACK, "client_id": client_id,
        "code_verifier": "wrong-verifier-not-matching",
    })
    check("bad PKCE verifier rejected", status == 400, f"got {status}")
    status, _, tok2b = token(BASE, {
        "grant_type": "authorization_code", "code": code2,
        "redirect_uri": CALLBACK, "client_id": client_id,
        "code_verifier": verifier2,
    })
    check("failed attempts don't consume codes", status == 200, f"got {status}")

    # 11. refresh rotation
    status, _, tok2 = token(BASE, {
        "grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id,
    })
    refresh2 = tok2.get("refresh_token", "") if isinstance(tok2, dict) else ""
    check("refresh works", status == 200 and refresh2 and refresh2 != refresh, f"{status}")
    status, _, _ = token(BASE, {
        "grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id,
    })
    check("old refresh rejected after rotation", status == 400, f"got {status}")

    # 11b. consent-gated revocation kills the remaining refresh ability
    status, _, rev = http("POST", f"{BASE}/revoke",
                          data={"client_id": client_id, "consent_secret": SECRET}, form=True)
    check("revoke ok", status == 200 and isinstance(rev, dict) and rev.get("revoked", 0) >= 1,
          f"{status} {rev}")
    status, _, _ = token(BASE, {
        "grant_type": "refresh_token", "refresh_token": refresh2, "client_id": client_id,
    })
    check("refresh rejected after revoke", status == 400, f"got {status}")
    status, _, _ = http("POST", f"{BASE}/revoke",
                        data={"client_id": client_id, "consent_secret": "nope"}, form=True)
    check("revoke needs consent secret", status == 403 or status == 429, f"got {status}")

    # 11. static token backward compat; open routes stay open
    status, _, _ = http("GET", f"{BASE}/api/overview",
                        headers={"Authorization": f"Bearer {STATIC}"})
    check("static bridge token still accepted", status == 200, f"got {status}")
    status, _, _ = http("GET", f"{BASE}/health")
    status2, _, _ = http("GET", f"{BASE}/.well-known/oauth-authorization-server")
    check("health + discovery open", status == 200 and status2 == 200, f"{status} {status2}")
    status, _, _ = http("POST", f"{BASE}/mcp", data=init, headers=accept)
    status2, _, _ = http("GET", f"{BASE}/api/overview")
    check("mcp + api closed without token", status == 401 and status2 == 401,
          f"{status} {status2}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("Failures:")
        for f in FAIL:
            print(" -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
