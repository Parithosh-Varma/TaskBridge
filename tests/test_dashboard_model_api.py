"""Dashboard model-configuration tests.

Covers the two HTTP routes behind the dashboard's model picker
(GET /api/models, POST /api/model) and the dashboard page wiring itself.
`opencode models` and the config write are always faked here — no real
subprocess is spawned and no real worker_config.json is touched.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import opencode_bridge_mcp as bridge  # noqa: E402

MODELS = ["anthropic/claude-haiku-4", "openai/gpt-5", "opencode/deepseek-v4.1-flash-free"]
DEFAULT = "opencode/deepseek-v4.1-flash-free"


def make_request(method="GET", path="/api/models", query="", body=b"",
                 content_type="application/json"):
    """Minimal Starlette Request for calling custom-route handlers directly."""
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = []
    if body and content_type:
        headers.append((b"content-type", content_type.encode()))
    scope = {
        "type": "http", "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "root_path": "", "headers": headers,
        "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
    }
    return Request(scope, receive)


@pytest.fixture(autouse=True)
def _fresh_models_cache():
    bridge._MODELS_CACHE.update(ts=0.0, models=[])
    yield
    bridge._MODELS_CACHE.update(ts=0.0, models=[])


def fake_all(models=None):
    models = list(models or MODELS)
    calls: list[bool] = []

    def _all():
        calls.append(True)
        return list(models)

    _all.calls = calls
    return _all


def post_model(payload_or_body):
    body = (json.dumps(payload_or_body).encode()
            if not isinstance(payload_or_body, bytes) else payload_or_body)
    return asyncio.run(bridge.api_set_model(
        make_request(method="POST", path="/api/model", body=body)))


# --------------------------------------------------------------- GET /api/models


def test_list_models_is_cached_searchable_and_caps_rows(monkeypatch):
    lister = fake_all()
    monkeypatch.setattr(bridge.worker_mod, "all_opencode_models", lister)
    monkeypatch.setattr(bridge.worker_mod, "default_model", lambda: DEFAULT)

    res = asyncio.run(bridge.api_models(make_request()))
    assert res.status_code == 200
    data = json.loads(res.body)
    assert data["models"] == MODELS
    assert data["count"] == len(MODELS)
    assert data["worker_default"] == DEFAULT

    # second hit is served from the cache — opencode is not shelled out again
    asyncio.run(bridge.api_models(make_request()))
    assert len(lister.calls) == 1

    # search filters inside the cached list
    res = asyncio.run(bridge.api_models(make_request(query="search=haiku")))
    assert json.loads(res.body)["models"] == ["anthropic/claude-haiku-4"]

    # limit caps the returned rows
    res = asyncio.run(bridge.api_models(make_request(query="limit=1")))
    assert len(json.loads(res.body)["models"]) == 1

    # ?refresh=1 forces a fresh listing
    asyncio.run(bridge.api_models(make_request(query="refresh=1")))
    assert len(lister.calls) == 2


def test_list_models_search_reaches_past_row_cap(monkeypatch):
    """Regression: opencode reports 600+ models; the listing caps rows at 200,
    but search must still find models beyond the cap."""
    many = [f"vendor/model-{i:03d}" for i in range(250)] + ["opencode/deepseek-v4.1-flash-free"]
    monkeypatch.setattr(bridge.worker_mod, "all_opencode_models", fake_all(many))
    monkeypatch.setattr(bridge.worker_mod, "default_model", lambda: DEFAULT)

    res = asyncio.run(bridge.api_models(make_request()))
    data = json.loads(res.body)
    assert len(data["models"]) == 200        # rows capped
    assert data["count"] == len(many)        # count reflects everything

    res = asyncio.run(bridge.api_models(make_request(query="search=model-240")))
    assert json.loads(res.body)["models"] == ["vendor/model-240"]


def test_list_models_surfaces_opencode_failure_as_502(monkeypatch):
    def boom():
        raise RuntimeError("`opencode models` failed: command not found")

    monkeypatch.setattr(bridge.worker_mod, "all_opencode_models", boom)
    res = asyncio.run(bridge.api_models(make_request()))
    assert res.status_code == 502
    assert "opencode models" in json.loads(res.body)["error"]


# --------------------------------------------------------------- POST /api/model


def test_set_model_persists_via_worker(monkeypatch):
    saved: list[str] = []
    monkeypatch.setattr(bridge.worker_mod, "set_default_model",
                        lambda m: (saved.append(m), m)[1])

    res = post_model({"model": "anthropic/claude-haiku-4"})
    assert res.status_code == 200
    data = json.loads(res.body)
    assert data["ok"] is True
    assert data["worker_default"] == "anthropic/claude-haiku-4"
    assert "next pass" in data["note"]
    assert saved == ["anthropic/claude-haiku-4"]


def test_set_model_trims_whitespace(monkeypatch):
    saved: list[str] = []
    monkeypatch.setattr(bridge.worker_mod, "set_default_model",
                        lambda m: (saved.append(m), m)[1])
    res = post_model({"model": "  openai/gpt-5  "})
    assert res.status_code == 200
    assert saved == ["openai/gpt-5"]


@pytest.mark.parametrize("bad", ["", "rm -rf /", "../../etc/passwd",
                                 "a b/model", "x" * 200, "model;rm"])
def test_set_model_rejects_argv_shaped_strings(monkeypatch, bad):
    called: list[str] = []
    monkeypatch.setattr(bridge.worker_mod, "set_default_model",
                        lambda m: (called.append(m), m)[1])
    res = post_model({"model": bad})
    assert res.status_code == 400
    assert called == []


def test_set_model_rejects_missing_and_non_string_model(monkeypatch):
    monkeypatch.setattr(bridge.worker_mod, "set_default_model",
                        lambda m: pytest.fail("setter must not be called"))
    assert post_model({}).status_code == 400
    assert post_model({"model": 123}).status_code == 400
    assert post_model(["not", "a", "dict"]).status_code == 400


def test_set_model_unknown_model_returns_suggestions(monkeypatch):
    def nope(model):
        raise ValueError("unknown model 'foo/bar'. Did you mean one of: ['a/b']?")

    monkeypatch.setattr(bridge.worker_mod, "set_default_model", nope)
    res = post_model({"model": "foo/bar"})
    assert res.status_code == 400
    assert "unknown model 'foo/bar'" in json.loads(res.body)["error"]


def test_set_model_invalid_json_body():
    res = post_model(b"definitely not json")
    assert res.status_code == 400


def test_set_model_oversized_body():
    res = post_model(b'{"model": "' + b"a" * 2000 + b'"}')
    assert res.status_code == 413


def test_set_model_keeps_picker_cache_coherent(monkeypatch):
    lister = fake_all()
    monkeypatch.setattr(bridge.worker_mod, "all_opencode_models", lister)
    monkeypatch.setattr(bridge.worker_mod, "default_model", lambda: MODELS[0])
    monkeypatch.setattr(bridge.worker_mod, "set_default_model", lambda m: m)

    asyncio.run(bridge.api_models(make_request()))  # warm the cache
    assert post_model({"model": "fresh/arrival-1"}).status_code == 200

    listed = json.loads(asyncio.run(bridge.api_models(make_request())).body)
    assert "fresh/arrival-1" in listed["models"]


# --------------------------------------------------------------- dashboard page


def test_dashboard_page_carries_model_picker(monkeypatch):
    raw = bridge.DASHBOARD_PATH.read_text()
    res = asyncio.run(bridge.dashboard_page(make_request(path="/")))
    assert res.status_code == 200
    html = res.body.decode()

    # every inline <script> is nonce-pinned, and the CSP carries that nonce
    assert raw.count("<script>") >= 2
    assert html.count('<script nonce="') == raw.count("<script>")
    assert "script-src 'nonce-" in res.headers["content-security-policy"]

    # the picker's wiring is present in the served page
    for needle in ('id="modelbtn"', 'id="modelbtntext"', 'id="modelmodal"',
                   'id="modelclose"', 'id="modelsearch"', 'id="modelreload"',
                   'id="modellist"', 'id="modelstatus"',
                   "api/models", "api/model", "openModelPanel"):
        assert needle in raw, f"dashboard is missing {needle}"
