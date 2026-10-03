"""i60 (re-opened) -- the ambiguity chips reach the user in production.

PR #262 armed the chips in harness.py's GROUNDED orchestrator branch, and its
tests stubbed ``ask_orchestrated`` with ``outcome="ok"`` for an ambiguous
tool output. The real orchestrator never returns that: an ambiguous player is
``status != "ok"``, so it reports ``tool_result_error``, the turn lands in the
"no grounded tool" branch, and the chips -- armed only in the other branch --
never reached prod. The turn also left as ``intent=unsupported``, which the UI
does not arm on (ChatShell.tsx WIZARD_ARMING_INTENTS).

These tests drive the REAL ``ask_orchestrated`` (single-round path, the one
prod runs) with a fake Anthropic-shaped client and the REAL tool handlers,
and read the chips off the HTTP JSON body -- never off the fixture that asked
for them. Prod case: "Martínez" = Emiliano (CHE, GKP) / Lisandro (MUN, DEF).
No network: an autouse fixture refuses every socket connect and the Jev
shadow stays off.
"""
from __future__ import annotations

import copy
import importlib
import socket
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fpl_server
import fpl_grounded_assistant.get_player_season_points  # noqa: F401 -- load the module, not the re-export
from fpl_grounded_assistant import harness as harness_mod
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.quota import reset_quota
from fpl_grounded_assistant.suggestions import KIND_HISTORICAL_PLAYER_REWRITE

from conftest import BOOTSTRAP

sp = sys.modules["fpl_grounded_assistant.get_player_season_points"]

SEASON = "2025-2026"
FORM_Q = "¿Cómo viene la forma de Martínez?"
SEASON_Q = "¿Cuántos puntos hizo Martínez la temporada pasada?"

_MARTINEZ = [
    {"id": 31, "first_name": "Emiliano", "second_name": "Martínez", "web_name": "Martínez",
     "team": 8, "team_code": 8, "element_type": 1, "status": "a", "now_cost": 50,
     "selected_by_percent": "10.0", "form": "4.0", "expected_goals": "0.00",
     "expected_assists": "0.00", "expected_goal_involvements": "0.00"},
    {"id": 32, "first_name": "Lisandro", "second_name": "Martínez", "web_name": "Martínez",
     "team": 11, "team_code": 12, "element_type": 2, "status": "a", "now_cost": 50,
     "selected_by_percent": "3.0", "form": "3.0", "expected_goals": "0.05",
     "expected_assists": "0.02", "expected_goal_involvements": "0.07"},
]


def _bootstrap() -> dict:
    b = copy.deepcopy(BOOTSTRAP)
    b["elements"] = b["elements"] + copy.deepcopy(_MARTINEZ)
    return b


# ---------------------------------------------------------------------------
# no network, no paid call, no shadow
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i60 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")


# ---------------------------------------------------------------------------
# fake provider: one tool_use, then the model's clarifying prose
# ---------------------------------------------------------------------------

class _SeqClient:
    def __init__(self, tool: str, args: dict) -> None:
        self.messages = self
        self.queue = [
            NS(content=[NS(type="tool_use", id="tu_1", name=tool, input=args)],
               stop_reason="tool_use",
               usage=NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)),
            NS(content=[NS(type="text", text="Hay dos Martínez: ¿Emiliano (CHE) o Lisandro (MUN)?")],
               stop_reason="end_turn",
               usage=NS(input_tokens=120, output_tokens=20, cache_read_input_tokens=0)),
        ]

    def create(self, **_kwargs):
        if not self.queue:
            raise AssertionError("unexpected extra provider call")
        return self.queue.pop(0)


def _fake_provider(monkeypatch: pytest.MonkeyPatch, tool: str, args: dict) -> None:
    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: _SeqClient(tool, args))


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(_bootstrap())
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


# ---------------------------------------------------------------------------
# past-season store with the same two Martínez
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path):
    merged = tmp_path / "historical" / "seasons" / SEASON / "parquet_merged"
    merged.mkdir(parents=True)
    pd.DataFrame([
        {"player_id": 501, "web_name": "Martínez", "first_name": "Emiliano", "second_name": "Martínez",
         "team_id": 8, "element_type": 1, "total_points": 150},
        {"player_id": 502, "web_name": "Martínez", "first_name": "Lisandro", "second_name": "Martínez",
         "team_id": 11, "element_type": 2, "total_points": 60},
    ]).to_parquet(merged / "players.parquet")
    pd.DataFrame([{"team_id": 8, "short_name": "CHE"}, {"team_id": 11, "short_name": "MUN"}]).to_parquet(
        merged / "teams.parquet")
    pd.DataFrame([
        {"event_id": 1, "player_id": pid, "total_points": pts, "minutes": 90,
         "goals_scored": 0, "assists": 0, "clean_sheets": 1, "bonus": 0}
        for pid, pts in ((501, 150), (502, 60))
    ]).to_parquet(merged / "player_gw_stats.parquet")
    pd.DataFrame([{"event_id": 1, "finished": True}]).to_parquet(merged / "events.parquet")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FPL_HISTORICAL_ROOT", str(tmp_path / "historical"))
        importlib.reload(sp)
        yield
    importlib.reload(sp)


# ---------------------------------------------------------------------------
# premise: the real orchestrator puts this turn in the no-grounded branch
# ---------------------------------------------------------------------------

def test_premise_real_orchestrator_reports_tool_result_error(monkeypatch):
    _fake_provider(monkeypatch, "get_player_form", {"query": "Martínez"})
    out = ask_v2(FORM_Q, _bootstrap())
    assert out["routing_trace"]["orchestrator_outcome"] == "tool_result_error"
    assert out["routing_trace"]["branch"] == "unsupported"
    assert out["selected_tool"] is None
    statuses = [c["output_status"] for c in out["tool_calls_trace"]]
    assert statuses == ["ambiguous"]


# ---------------------------------------------------------------------------
# current season: stable-id chips + an intent the UI arms on
# ---------------------------------------------------------------------------

def test_post_ask_form_ambiguity_serves_stable_id_chips(server, monkeypatch):
    _fake_provider(monkeypatch, "get_player_form", {"query": "Martínez"})
    body = server.post("/ask", json={"question": FORM_Q}, headers={"X-User-Id": "u-i60-form"}).json()
    assert body["intent"] == "player_form"
    assert body["outcome"] == "ambiguous"
    chips = body["suggestions"]
    assert chips is not None
    assert sorted(c["player_id"] for c in chips) == [31, 32]
    assert {c["label"] for c in chips} == {"Martínez (CHE)", "Martínez (MUN)"}
    assert all(c.get("kind") in (None, "") for c in chips)


def test_session_ask_form_ambiguity_serves_the_same_chips(server, monkeypatch):
    _fake_provider(monkeypatch, "get_player_form", {"query": "Martínez"})
    sid = server.post("/session").json()["session_id"]
    body = server.post(f"/session/{sid}/ask", json={"question": FORM_Q},
                       headers={"X-User-Id": "u-i60-sess"}).json()
    assert body["intent"] == "player_form"
    assert sorted(c["player_id"] for c in body["suggestions"]) == [31, 32]


def test_chip_tap_resolves_to_the_picked_player(server, monkeypatch):
    """The tap re-sends the chip's player_id; that id must resolve to exactly
    the player the chip named (fed back through the real /ask)."""
    _fake_provider(monkeypatch, "get_player_form", {"query": "Martínez"})
    chips = server.post("/ask", json={"question": FORM_Q}, headers={"X-User-Id": "u-i60-tap"}).json()["suggestions"]
    mun = next(c for c in chips if c["label"] == "Martínez (MUN)")
    picked = next(e for e in _bootstrap()["elements"] if e["id"] == mun["player_id"])
    assert (picked["first_name"], picked["team"]) == ("Lisandro", 11)


# ---------------------------------------------------------------------------
# past season: rewrite chips with no id, the UI arms them intent-agnostically
# ---------------------------------------------------------------------------

def test_post_ask_past_season_ambiguity_serves_historical_chips(server, store, monkeypatch):
    _fake_provider(monkeypatch, "get_player_season_points", {"query": "Martínez", "season": SEASON})
    body = server.post("/ask", json={"question": SEASON_Q}, headers={"X-User-Id": "u-i60-hist"}).json()
    assert body["outcome"] == "ambiguous"
    assert body["intent"] == "player_season_points"
    chips = body["suggestions"]
    assert chips is not None and len(chips) == 2
    assert all(c["kind"] == KIND_HISTORICAL_PLAYER_REWRITE for c in chips)
    assert all(c.get("player_id") is None for c in chips)
    assert {c["send_text"] for c in chips} == {
        f"puntos de Emiliano Martínez (CHE) en la temporada {SEASON}",
        f"puntos de Lisandro Martínez (MUN) en la temporada {SEASON}",
    }


# ---------------------------------------------------------------------------
# negatives: nothing else in the no-grounded branch changes
# ---------------------------------------------------------------------------

def test_not_found_player_stays_unsupported_without_chips(server, monkeypatch):
    _fake_provider(monkeypatch, "get_player_form", {"query": "Zzyzx"})
    body = server.post("/ask", json={"question": "forma de Zzyzx"}, headers={"X-User-Id": "u-i60-nf"}).json()
    assert body["intent"] == "unsupported"
    assert body["suggestions"] is None


def test_ambiguous_non_arming_tool_does_not_arm():
    assert harness_mod._last_ambiguous_chip_call([
        {"name": "get_player_history", "output": {"status": "ambiguous", "candidates": [{}]}},
    ]) is None


def test_last_ambiguous_call_wins_and_retry_calls_count():
    first = {"name": "get_player_form", "output": {"status": "ambiguous", "candidates": []}}
    retry = {"name": "get_player_season_points", "output": {"status": "ambiguous"}, "retry": True}
    later_ok = {"name": "get_current_gameweek", "output": {"status": "ok"}}
    assert harness_mod._last_ambiguous_chip_call([first, retry, later_ok]) is retry


# ---------------------------------------------------------------------------
# the UI's fixture is the body this backend serves (no hand-written shape)
# ---------------------------------------------------------------------------

_UI_FIXTURE = Path(__file__).resolve().parents[2] / "fpl-ui" / "__tests__" / "fixtures" / "i60-ask-martinez.json"
_PINNED = ("final_text", "outcome", "supported", "intent", "suggestions")


def test_ui_fixture_matches_what_post_ask_serves(server, store, monkeypatch):
    import json

    pinned = json.loads(_UI_FIXTURE.read_text(encoding="utf-8"))
    _fake_provider(monkeypatch, "get_player_form", {"query": "Martínez"})
    form = server.post("/ask", json={"question": FORM_Q}, headers={"X-User-Id": "u-i60-pin-1"}).json()
    _fake_provider(monkeypatch, "get_player_season_points", {"query": "Martínez", "season": SEASON})
    season = server.post("/ask", json={"question": SEASON_Q}, headers={"X-User-Id": "u-i60-pin-2"}).json()
    for key in _PINNED:
        assert pinned["form"][key] == form[key], key
        assert pinned["season"][key] == season[key], key
