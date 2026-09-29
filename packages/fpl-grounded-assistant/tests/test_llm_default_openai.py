"""
The LLM layer defaults to OpenAI / gpt-5.6-luna (Leo, 2026-09-29).

Before this, with DEFAULT_PROVIDER unset or =gemini (prod had it =gemini),
three things still ran on the deprecated gemini-2.5-flash while the
orchestrator already ran luna: the legacy presentation call
(``llm_layer.ask_llm`` -- session turns carrying an ``intent_hint``), the
intent classifier behind it, and the provider line of ``/healthz``. And the
OpenAI entry of the llm_layer table was gpt-4o-mini, so flipping only the
env var would have moved those calls to gpt-4o-mini, not luna.

Nothing pinned the old default -- the whole suite passed with it changed --
so these tests pin the new one. ``llm_layer`` reads DEFAULT_PROVIDER at
import, so the module-level defaults are checked in a fresh subprocess with
a controlled environment, never by reloading shared modules in-process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _p in [
    _PKG,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fpl_grounded_assistant.intent_classifier import (  # noqa: E402
    OPENAI_CLASSIFIER_MIN_OUTPUT_TOKENS,
    OpenAIClassifierAdapter,
    classify_intent_llm,
)
from fpl_grounded_assistant.provider_client import check_provider_health  # noqa: E402

_PROBE = """
import json, os
from fpl_grounded_assistant import llm_layer
print(json.dumps({"provider": llm_layer._PROVIDER, "model": llm_layer.DEFAULT_MODEL}))
"""


def _module_defaults(default_provider: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "DEFAULT_PROVIDER"}
    if default_provider is not None:
        env["DEFAULT_PROVIDER"] = default_provider
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    done = subprocess.run(
        [sys.executable, "-c", _PROBE], env=env, cwd=Path(_PKG),
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# llm_layer module defaults
# ---------------------------------------------------------------------------

def test_unset_default_provider_is_openai_luna():
    assert _module_defaults(None) == {"provider": "openai", "model": "gpt-5.6-luna"}


def test_explicit_openai_is_luna_not_gpt4o_mini():
    """The table entry itself: flipping only the env var must land on luna."""
    assert _module_defaults("openai") == {"provider": "openai", "model": "gpt-5.6-luna"}


def test_explicit_gemini_still_selects_gemini():
    """DEFAULT_PROVIDER=gemini remains an explicit escape hatch."""
    got = _module_defaults("gemini")
    assert got["provider"] == "gemini" and got["model"].startswith("gemini")


def test_unknown_provider_falls_back_to_the_openai_model():
    assert _module_defaults("nonsense")["model"] == "gpt-5.6-luna"


# ---------------------------------------------------------------------------
# /healthz provider line
# ---------------------------------------------------------------------------

def test_health_default_checks_openai(monkeypatch):
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "present")   # a gemini default would read this
    out = check_provider_health()
    assert out["available"] is False
    assert "OPENAI_API_KEY" in (out["error"] or "")


# ---------------------------------------------------------------------------
# Classifier built by the server
# ---------------------------------------------------------------------------

def test_server_builds_the_openai_classifier_by_default(monkeypatch):
    import fpl_server
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    built: list = []
    monkeypatch.setattr(fpl_server, "_init_classifier_client", lambda c: built.append(c))
    fpl_server._try_init_classifier_from_env()
    assert len(built) == 1 and isinstance(built[0], OpenAIClassifierAdapter)


def test_server_builds_no_classifier_without_openai_key(monkeypatch):
    import fpl_server
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    built: list = []
    monkeypatch.setattr(fpl_server, "_init_classifier_client", lambda c: built.append(c))
    fpl_server._try_init_classifier_from_env()
    assert built == []   # deterministic routing, never a crash


def test_server_gemini_branch_still_selectable(monkeypatch):
    import fpl_server
    pytest.importorskip("google.generativeai")
    from fpl_grounded_assistant.intent_classifier import GeminiClassifierAdapter
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test-not-used")
    built: list = []
    monkeypatch.setattr(fpl_server, "_init_classifier_client", lambda c: built.append(c))
    fpl_server._try_init_classifier_from_env()
    assert len(built) == 1 and isinstance(built[0], GeminiClassifierAdapter)


# ---------------------------------------------------------------------------
# OpenAIClassifierAdapter -- read off the request the fake client received
# ---------------------------------------------------------------------------

class _FakeResponses:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(output_text=self.text)


class _FakeOpenAI:
    def __init__(self, text: str):
        self.responses = _FakeResponses(text)


_JSON = '{"intent": "current_gameweek", "canonical_question": "what gameweek is it", "confidence": 0.99, "language": "es"}'


def test_adapter_request_shape():
    fake = _FakeOpenAI(_JSON)
    out = classify_intent_llm("¿qué jornada es?", OpenAIClassifierAdapter(fake))
    assert out is not None and out.intent == "current_gameweek"
    (req,) = fake.responses.calls
    assert req["model"] == "gpt-5.6-luna"              # the caller's Claude id is ignored
    # The user turn classify_intent_llm built, forwarded verbatim.
    (turn,) = req["input"]
    assert turn["role"] == "user" and turn["content"].endswith("¿qué jornada es?")
    assert isinstance(req["instructions"], str) and req["instructions"]
    # Reasoning tokens come out of max_output_tokens: never the bare 128.
    assert req["max_output_tokens"] >= OPENAI_CLASSIFIER_MIN_OUTPUT_TOKENS
    # GPT-5.6 rejects both with a 400.
    assert "temperature" not in req and "top_p" not in req


def test_adapter_strips_code_fences():
    fake = _FakeOpenAI("```json\n" + _JSON + "\n```")
    out = classify_intent_llm("¿qué jornada es?", OpenAIClassifierAdapter(fake))
    assert out is not None and out.canonical_question == "what gameweek is it"


def test_adapter_empty_reply_is_no_classification_not_a_crash():
    out = classify_intent_llm("¿qué jornada es?", OpenAIClassifierAdapter(_FakeOpenAI("")))
    assert out is None
