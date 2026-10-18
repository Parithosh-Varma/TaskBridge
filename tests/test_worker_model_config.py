"""Worker model-configuration tests.

`opencode models` is simulated with a throwaway shell script and the config
write is redirected to a tmp dir — no real subprocess list, no real
worker_config.json, no worker restarts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import worker  # noqa: E402


def fake_opencode(tmp_path, stdout="", stderr="", code=0):
    """A stand-in `opencode` that prints fixed model lines."""
    p = tmp_path / "fake-opencode"
    body = "#!/bin/sh\n"
    if stdout:
        body += "cat <<'MODELS'\n" + stdout + "MODELS\n"
    if stderr:
        body += f"echo '{stderr}' >&2\n"
    body += f"exit {code}\n"
    p.write_text(body)
    p.chmod(0o755)
    return p


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "CONFIG_PATH", tmp_path / "worker_config.json")
    return tmp_path


# --------------------------------------------------------------- all_opencode_models


def test_all_models_parses_dedupes_and_skips_noise(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, stdout=(
        "anthropic/claude-haiku-4\n"
        "\n"
        "openai/gpt-5\n"
        "not-a-model\n"
        "anthropic/claude-haiku-4\n"
        "  openai/gpt-5  \n"
    ))
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    assert worker.all_opencode_models() == [
        "anthropic/claude-haiku-4", "openai/gpt-5"]


def test_all_models_surfaces_cli_failure(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, stderr="auth broken", code=2)
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    with pytest.raises(RuntimeError, match="opencode models"):
        worker.all_opencode_models()


def test_all_models_surfaces_missing_binary(monkeypatch):
    monkeypatch.setattr(worker, "OPENCODE_BIN", "/nonexistent/opencode")
    with pytest.raises(RuntimeError, match="could not list"):
        worker.all_opencode_models()


# --------------------------------------------------------------- list_available_models


def test_list_models_filters_and_caps_rows(tmp_path, monkeypatch):
    many = [f"vendor/model-{i:03d}" for i in range(250)]
    binp = fake_opencode(tmp_path, stdout="\n".join(many) + "\n")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))

    assert len(worker.list_available_models()) == 100          # default limit
    assert len(worker.list_available_models(limit=100000)) == 200  # hard cap
    # search runs before the cap, so late entries are reachable
    assert worker.list_available_models("model-240") == ["vendor/model-240"]


# --------------------------------------------------------------- set_default_model


def test_set_default_model_writes_config(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, stdout="alpha/one\nbeta/two\n")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))

    assert worker.set_default_model("beta/two") == "beta/two"
    cfg = json.loads((tmp_path / "worker_config.json").read_text())
    assert cfg == {"default_model": "beta/two"}
    assert worker.default_model() == "beta/two"


def test_set_default_model_validates_against_full_list(tmp_path, monkeypatch):
    """Regression: validation used to run against the first 100 rows only, so
    models further down opencode's 600+ list were rejected as unknown."""
    many = [f"vendor/model-{i:03d}" for i in range(300)]
    binp = fake_opencode(tmp_path, stdout="\n".join(many) + "\n")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))

    assert worker.set_default_model("vendor/model-299") == "vendor/model-299"


def test_set_default_model_rejects_unknown_with_suggestions(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, stdout="alpha/one\nbeta/two\n")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))

    with pytest.raises(ValueError, match="unknown model 'beta'") as ei:
        worker.set_default_model("beta")
    assert "beta/two" in str(ei.value)  # close matches offered
    assert not (tmp_path / "worker_config.json").exists()


def test_set_default_model_rejects_empty(tmp_path, monkeypatch):
    binp = fake_opencode(tmp_path, stdout="alpha/one\n")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    with pytest.raises(ValueError, match="model is required"):
        worker.set_default_model("   ")


def test_default_model_precedence(tmp_path, monkeypatch):
    """config file > WORKER_MODEL env/builtin."""
    binp = fake_opencode(tmp_path, stdout="alpha/one\nbeta/two\n")
    monkeypatch.setattr(worker, "OPENCODE_BIN", str(binp))
    monkeypatch.setattr(worker, "WORKER_MODEL", "builtin/fallback")

    assert worker.default_model() == "builtin/fallback"     # nothing persisted
    worker.set_default_model("beta/two")
    assert worker.default_model() == "beta/two"             # config wins
