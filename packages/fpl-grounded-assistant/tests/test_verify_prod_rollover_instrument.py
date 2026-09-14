"""
tests/test_verify_prod_rollover_instrument.py
==============================================
2-E (i80/i36/i57): scripts/verify_prod_rollover.py gained two checks --
/healthz.orchestrator must be present, and one session turn with debug=true
must carry routing_trace.tool_call_count != None. These pin both directions
for each: a compliant payload adds no failure, and each way the backend could
regress (block missing, key missing, no debug bundle, orchestration_absent,
tool_call_count None) adds a failure that names the cause.

No network: requests.get / requests.post are monkeypatched at the module's
own import of them. The script lives at the repo root (scripts/), three
levels above this package.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os
from types import SimpleNamespace

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_HERE)))
_SCRIPT_PATH = _os.path.join(_REPO_ROOT, "scripts", "verify_prod_rollover.py")
_spec = _ilu.spec_from_file_location("verify_prod_rollover", _SCRIPT_PATH)
verify_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(verify_mod)

_URL = "https://example.test"


def _resp(body: dict, status: int = 200):
    def _raise():
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
    return SimpleNamespace(status_code=status, json=lambda: body, raise_for_status=_raise)


_HEALTHY_BLOCK = {
    "enabled": True, "loop_enabled": True, "max_rounds": 3,
    "provider": "openai", "model": "some-model",
}


# ---------------------------------------------------------------------------
# /healthz.orchestrator
# ---------------------------------------------------------------------------

def _healthz(monkeypatch, body: dict) -> list[str]:
    calls: list[str] = []

    def _get(url, *a, **k):
        calls.append(url)
        return _resp(body)

    monkeypatch.setattr(verify_mod.requests, "get", _get)
    failures: list[str] = []
    verify_mod.verify_healthz_orchestrator(_URL, failures)
    assert calls == [f"{_URL}/healthz"]
    return failures


def test_healthz_orchestrator_block_present_adds_no_failure(monkeypatch):
    assert _healthz(monkeypatch, {"orchestrator": _HEALTHY_BLOCK}) == []


def test_healthz_orchestrator_block_missing_is_a_failure(monkeypatch):
    failures = _healthz(monkeypatch, {"routing_counters": {}})
    assert len(failures) == 1
    assert "orchestrator block missing" in failures[0]


def test_healthz_orchestrator_block_lacking_a_key_is_a_failure(monkeypatch):
    partial = dict(_HEALTHY_BLOCK)
    del partial["loop_enabled"]
    failures = _healthz(monkeypatch, {"orchestrator": partial})
    assert len(failures) == 1
    assert "loop_enabled" in failures[0]


def test_healthz_orchestrator_values_are_reported_not_judged(monkeypatch):
    """The block's job is to be READ; loop_enabled=False is a finding for the
    operator, not a failure of the script."""
    block = dict(_HEALTHY_BLOCK, loop_enabled=False, provider=None)
    assert _healthz(monkeypatch, {"orchestrator": block}) == []


# ---------------------------------------------------------------------------
# session turn with debug=true
# ---------------------------------------------------------------------------

def _session(monkeypatch, ask_body: dict) -> tuple[list[str], list[tuple[str, dict | None]]]:
    posts: list[tuple[str, dict | None]] = []

    def _post(url, *a, **k):
        posts.append((url, k.get("json")))
        if url.endswith("/session"):
            return _resp({"session_id": "sess-1"})
        return _resp(ask_body)

    monkeypatch.setattr(verify_mod.requests, "post", _post)
    failures: list[str] = []
    verify_mod.verify_session_debug_trace(_URL, "u-test", "pregunta", failures)
    return failures, posts


def _ask_body(trace: dict | None, **debug_extra) -> dict:
    debug = {"routing_trace": trace, "tokens": {"total": 900}, "tool_calls": [{"name": "t"}]}
    debug.update(debug_extra)
    return {"outcome": "ok", "intent": "x", "synthesis_turn": True, "debug": debug}


def test_session_turn_with_tool_call_count_adds_no_failure(monkeypatch):
    failures, posts = _session(monkeypatch, _ask_body({
        "branch": "orchestrator", "tool_call_count": 2, "synthesis_turn": True,
        "retry_attempted": False, "tool_sequence": ["t", "t"],
    }))
    assert failures == []
    # The turn is a real session turn (create, then ask on that id) and it
    # asks for the debug bundle -- otherwise routing_trace never arrives.
    assert posts[0][0] == f"{_URL}/session"
    assert posts[1][0] == f"{_URL}/session/sess-1/ask"
    assert posts[1][1] == {"question": "pregunta", "debug": True}


def test_session_turn_with_tool_call_count_zero_is_still_measured(monkeypatch):
    """0 is a measurement (the orchestrator ran and called nothing); only
    None is 'not measured'."""
    failures, _ = _session(monkeypatch, _ask_body({"branch": "unsupported", "tool_call_count": 0}))
    assert failures == []


def test_session_turn_with_tool_call_count_none_is_a_failure(monkeypatch):
    failures, _ = _session(monkeypatch, _ask_body({"branch": "route", "tool_call_count": None}))
    assert len(failures) == 1
    assert "tool_call_count is None" in failures[0]


def test_session_turn_without_routing_trace_is_a_failure(monkeypatch):
    body = _ask_body(None)
    del body["debug"]["routing_trace"]
    failures, _ = _session(monkeypatch, body)
    assert len(failures) == 1
    assert "routing_trace missing" in failures[0]


def test_session_turn_without_debug_bundle_is_a_failure(monkeypatch):
    failures, _ = _session(monkeypatch, {"outcome": "ok", "debug": None})
    assert len(failures) == 1
    assert "no debug bundle" in failures[0]


def test_session_turn_on_legacy_path_is_a_failure_naming_the_cause(monkeypatch):
    failures, _ = _session(monkeypatch, _ask_body(None, orchestration_absent=True))
    assert len(failures) == 1
    assert "orchestration_absent" in failures[0]


def test_session_create_without_id_is_a_failure(monkeypatch):
    monkeypatch.setattr(verify_mod.requests, "post", lambda url, *a, **k: _resp({}))
    failures: list[str] = []
    verify_mod.verify_session_debug_trace(_URL, "u-test", "pregunta", failures)
    assert len(failures) == 1
    assert "no session_id" in failures[0]


# ---------------------------------------------------------------------------
# main() wires both checks in (after the existing ones), still no network
# ---------------------------------------------------------------------------

def test_main_runs_both_new_checks(monkeypatch, capsys):
    """End to end through main() with every HTTP call faked: the two new
    checks run, print their values, and a compliant backend exits 0."""
    import sys as _sys

    def _get(url, *a, **k):
        assert url.endswith("/healthz")
        return _resp({
            "owned_store_seasons": [
                {"season": "2026-2027", "complete": True, "merged_at": "M"},
                {"season": "2025-2026", "complete": True, "merged_at": "M"},
            ],
            "owned_store_sync": {},
            "orchestrator": _HEALTHY_BLOCK,
        })

    def _post(url, *a, **k):
        if url.endswith("/session"):
            return _resp({"session_id": "sess-9"})
        if "/session/sess-9/ask" in url:
            return _resp(_ask_body({"branch": "orchestrator", "tool_call_count": 1}))
        q = (k.get("json") or {}).get("question", "")
        if "Arsenal" in q:
            return _resp({"outcome": "ok", "final_text": "texto",
                          "debug": {"routing_trace": {"orchestrator_tool_calls": ["get_zonal_weakness"]}}})
        if "Salah" in q:
            return _resp({"final_text": "t", "debug": {
                "routing_trace": {"orchestrator_tool_calls": ["get_player_season_points"]},
                "raw_output": {"season": "2025-2026", "summary": {"total_points": 200}},
            }})
        return _resp({"final_text": "t", "debug": {
            "routing_trace": {"orchestrator_tool_calls": ["get_historical_gameweek_top_scorer"]},
            "raw_output": {"status": "ok", "season": "2026-2027", "entries": [{"x": 1}]},
        }})

    monkeypatch.setattr(verify_mod.requests, "get", _get)
    monkeypatch.setattr(verify_mod.requests, "post", _post)
    monkeypatch.setattr(_sys, "argv", [
        "verify_prod_rollover.py", "--url", _URL, "--expected-season", "2026-2027",
        "--user-id", "u-test",
    ])
    verify_mod.main()  # exits 1 on failure; returning is the pass
    out = capsys.readouterr().out
    assert "i57 /healthz orchestrator" in out
    assert "orchestrator={'enabled': True" in out
    assert "i80/i36 session turn with debug=true" in out
    assert "tool_call_count=1" in out
    assert "all checks passed" in out


def test_main_exits_one_when_the_session_trace_is_missing(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(verify_mod.requests, "get", lambda url, *a, **k: _resp({
        "owned_store_seasons": [
            {"season": "2026-2027", "complete": True}, {"season": "2025-2026", "complete": True},
        ],
        "orchestrator": _HEALTHY_BLOCK,
    }))

    def _post(url, *a, **k):
        if url.endswith("/session"):
            return _resp({"session_id": "sess-9"})
        if "/session/sess-9/ask" in url:
            return _resp(_ask_body({"branch": "route", "tool_call_count": None}))
        q = (k.get("json") or {}).get("question", "")
        if "Arsenal" in q:
            return _resp({"outcome": "ok", "final_text": "texto",
                          "debug": {"routing_trace": {"orchestrator_tool_calls": ["get_zonal_weakness"]}}})
        if "Salah" in q:
            return _resp({"final_text": "t", "debug": {
                "routing_trace": {"orchestrator_tool_calls": ["get_player_season_points"]},
                "raw_output": {"season": "2025-2026", "summary": {"total_points": 200}},
            }})
        return _resp({"final_text": "t", "debug": {
            "routing_trace": {"orchestrator_tool_calls": ["get_historical_gameweek_top_scorer"]},
            "raw_output": {"status": "ok", "season": "2026-2027", "entries": [{"x": 1}]},
        }})

    monkeypatch.setattr(verify_mod.requests, "post", _post)
    monkeypatch.setattr(_sys, "argv", [
        "verify_prod_rollover.py", "--url", _URL, "--expected-season", "2026-2027",
    ])
    with pytest.raises(SystemExit) as exc:
        verify_mod.main()
    assert exc.value.code == 1
