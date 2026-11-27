"""
The position pitch is always drawn when there is a counted start.

«¿Qué posición jugó X su último partido?» about a player who keeps one role, listed by
FPL in that line, got text and a table but no mini-pitch: the card only drew it for a
role switch or an FPL-position gap. The third kind, ``steady``, draws where he starts.

Synthetic players and a synthetic licensed store. The HTTP bodies come from the real
tool and the real routes (only the model is stubbed) and are the UI tests' fixtures
(``UPDATE_PITCH_FIXTURES=1 pytest tests/test_position_pitch_steady.py``).
"""
from __future__ import annotations

import json
import os
import pathlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fpl_server
from football_intelligence.distribution import licensed_runtime
from football_intelligence.ingestion.licensed.store import TABLES
from fpl_grounded_assistant.atomic_tool_cards import compose_position_changes_card
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult
from fpl_grounded_assistant.position_changes_tool import run_position_changes
from fpl_grounded_assistant.quota import reset_quota

TOOL = "get_position_changes"
ALDER = 910
UI_FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fpl-ui" / "__tests__" / "fixtures" / "position-pitch"

AM = ("Attacking Midfield", "centre", "4:2")
DM = ("Defensive Midfield", "left", "3:1")
RM = ("Right Midfield", "right", "4:3")
BENCH = None

#: oldest first; one entry per gameweek
ONE_ROLE = [AM] * 6
MOSTLY_ONE = [AM, AM, DM, AM, AM, AM]
SPLIT = [AM, DM, AM, RM, DM, AM]          # AM 3 of 6: no role holds more than half


def _fixtures(n):
    return [{"id": f, "event": f, "kickoff_time": f"2026-11-{f:02d}T15:00:00Z", "team_h": 1, "team_a": 2}
            for f in range(1, n + 1)]


def _bootstrap(roles, element_type=3):
    return {
        **STANDARD_BOOTSTRAP,
        "teams": [{"id": 1, "name": "Northbury", "short_name": "NOR", "code": 1},
                  {"id": 2, "name": "Eastport", "short_name": "EAS", "code": 2}],
        "elements": [{"id": ALDER, "web_name": "Alder", "first_name": "Ben", "second_name": "Alder", "team": 1,
                      "team_code": 1, "element_type": element_type, "status": "a", "now_cost": 80,
                      "selected_by_percent": "5.0", "form": "4.0", "total_points": 40, "points_per_game": "4.0",
                      "minutes": 500}],
        "fixture_index": _fixtures(len(roles)),
    }


class _Handle:
    def __init__(self, roles):
        snaps, slots = [], []
        for fid, role in enumerate(roles, start=1):
            obs = f"2026-11-{fid:02d}T14:00:00Z"
            snaps.append({"fixture_id": fid, "team": "NOR", "observed_at": obs, "state": "finished", "confirmed": True,
                          "formation": "4-2-3-1", "n_starters": 1, "n_bench": 1})
            row = {"fixture_id": fid, "team": "NOR", "observed_at": obs, "element": ALDER, "starter": role is not None,
                   "detailed_position": None, "grid_slot": None, "side": None}
            if role is not None:
                row.update(detailed_position=role[0], side=role[1], grid_slot=role[2])
            slots.append(row)
        frames = {"lineup_snapshots": snaps, "lineup_slots": slots, "sidelined": [],
                  "squad_membership": [{"team": "NOR", "element": ALDER, "jersey_number": 8,
                                        "observed_at": "2026-10-01T05:00:00Z"}]}
        self._t = {n: pd.DataFrame(r, columns=list(TABLES[n][0])).astype(object) for n, r in frames.items()}

    def manifest(self):
        return {"built_at": "2026-11-20T05:00:00Z"}

    def table(self, name):
        return self._t[name]      # no match statistics: KeyError, as on an older build


def _run(roles, element_type=3):
    return run_position_changes({"player": "Alder"}, _bootstrap(roles, element_type), handle=_Handle(roles))


def _card(roles, locale="es", element_type=3):
    return compose_position_changes_card(_run(roles, element_type), locale)


# -- what is drawn -----------------------------------------------------------------


@pytest.mark.parametrize("locale,label,hero", [
    ("es", "Mediapunta · 6 de 6 titularidades", ("6/6", "como mediapunta")),
    ("en", "Attacking Midfield · 6 of 6 starts", ("6/6", "as attacking midfield")),
])
def test_one_role_is_one_spot_with_its_count_and_no_table(locale, label, hero):
    raw = _run(ONE_ROLE)
    assert "role_switch" not in raw and "fpl_position_gap" not in raw   # the case that had no pitch
    card = compose_position_changes_card(raw, locale)
    pp = card.position_pitch
    assert (pp["kind"], pp["from"], pp["others"]) == ("steady", None, [])
    assert pp["to"] == {"detailed_position": "Attacking Midfield", "side": None, "line": "MID"}
    assert pp["labels"]["to"] == label and (card.hero.value, card.hero.label) == hero
    assert card.rows == () and card.columns == () and pp["rows"] == [] and pp["note"] is None
    assert "grid_slot" not in str(pp)
    assert not any(p.label.startswith(("FPL", "Antes", "Before", "Misma", "Same")) for p in card.pills)


def test_a_majority_role_is_one_spot_and_the_other_start_brings_the_table():
    card = _card(MOSTLY_ONE)
    assert card.position_pitch["labels"]["to"] == "Mediapunta · 5 de 6 titularidades"
    assert card.position_pitch["others"] == [] and card.hero.value == "5/6"
    assert len(card.rows) == 6 and "Pivote" in [r[2] for r in card.rows]


def test_split_starts_draw_the_main_role_and_the_others_with_counts():
    raw = _run(SPLIT)
    assert "role_switch" not in raw
    card = compose_position_changes_card(raw, "es")
    pp = card.position_pitch
    assert pp["labels"]["to"] == "Mediapunta · 3 de 6 titularidades"
    assert [(o["detailed_position"], o["side"], o["starts"], o["label"]) for o in pp["others"]] == [
        ("Defensive Midfield", "left", 2, "Pivote · 2"),
        ("Right Midfield", "right", 1, "Banda derecha · 1"),
    ]
    assert card.rows == ()                       # every role is on the pitch with its count


def test_a_tie_puts_the_most_recently_started_role_first():
    card = _card([AM, DM, AM, DM, AM, DM], "en")
    pp = card.position_pitch
    assert pp["to"]["detailed_position"] == "Defensive Midfield"
    assert [(o["detailed_position"], o["starts"]) for o in pp["others"]] == [("Attacking Midfield", 3)]


def test_one_start_is_worded_in_the_singular():
    assert _card([BENCH, AM], "es").position_pitch["labels"]["to"] == "Mediapunta · 1 de 1 titularidad"
    assert _card([BENCH, AM], "en").position_pitch["labels"]["to"] == "Attacking Midfield · 1 of 1 start"


def test_bench_matches_are_not_counted():
    card = _card([AM, BENCH, AM, BENCH, AM, AM])
    assert card.position_pitch["labels"]["to"] == "Mediapunta · 4 de 4 titularidades"


def test_a_predicted_xi_is_not_counted_and_keeps_its_row():
    raw = _run(ONE_ROLE)
    raw["matches"][-1]["played"] = False
    card = compose_position_changes_card(raw, "es")
    assert card.position_pitch["labels"]["to"] == "Mediapunta · 5 de 5 titularidades"
    assert len(card.rows) == 6


def test_bench_only_has_no_pitch_and_keeps_the_table():
    card = _card([BENCH] * 4)
    assert card.position_pitch is None and len(card.rows) == 4


def test_the_switch_and_listing_kinds_are_as_before():
    switch = _card([RM, RM, RM, AM, AM, AM])
    assert switch.position_pitch["kind"] == "switch" and "others" not in switch.position_pitch
    listing = _card(ONE_ROLE, element_type=2)    # FPL lists him as a defender
    assert listing.position_pitch["kind"] == "fpl_listing" and "others" not in listing.position_pitch


# -- over HTTP ---------------------------------------------------------------------


def _serve(monkeypatch, roles, locale):
    boot = _bootstrap(roles)
    raw = run_position_changes({"player": "Alder"}, boot, handle=_Handle(roles))
    trace = ({"round": 1, "tool_call_id": "c0", "name": TOOL, "args": {"player": "Alder"}, "output": raw,
              "success": True},)
    result = OrchestratorResult(
        question="q", tool_chosen=TOOL, tool_args={"player": "Alder"}, tool_output=raw,
        answer_text="Lectura.", llm_used=True, model="stub-model", outcome=OUTCOME_OK,
        primary_input_tokens=10, primary_output_tokens=5, total_tokens=15, tool_call_count=1,
        tool_calls_trace=trace, synthesis_turn=True,
    )
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    monkeypatch.setattr(licensed_runtime, "handle_from_env", lambda: _Handle(roles))
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    fpl_server._init_bootstrap(boot)
    fpl_server._sessions.clear()
    reset_quota()
    body = {"question": "¿Qué posición jugó Alder su último partido?", "locale": locale}
    try:
        client = TestClient(fpl_server.app)
        ask = client.post("/ask", json=body, headers={"X-User-Id": f"pp-ask-{locale}"})
        sid = client.post("/session").json()["session_id"]
        sess = client.post(f"/session/{sid}/ask", json=body, headers={"X-User-Id": f"pp-sess-{locale}"})
        assert (ask.status_code, sess.status_code) == (200, 200)
        return ask.json(), sess.json()
    finally:
        fpl_server._sessions.clear()
        reset_quota()


@pytest.mark.parametrize("name,roles,locale,first_label", [
    ("one-role-es", ONE_ROLE, "es", "Mediapunta · 6 de 6 titularidades"),
    ("majority-es", MOSTLY_ONE, "es", "Mediapunta · 5 de 6 titularidades"),
    ("split-es", SPLIT, "es", "Mediapunta · 3 de 6 titularidades"),
    ("split-en", SPLIT, "en", "Attacking Midfield · 3 of 6 starts"),
])
def test_both_routes_serve_the_steady_pitch(monkeypatch, name, roles, locale, first_label):
    ask, sess = _serve(monkeypatch, roles, locale)
    assert ask["generic_card"] == sess["generic_card"]
    card = ask["generic_card"]
    assert card["position_pitch"]["kind"] == "steady"
    assert card["position_pitch"]["labels"]["to"] == first_label
    wire = {k: ask[k] for k in ("final_text", "outcome", "intent", "generic_card")}
    path = UI_FIXTURES / f"{name}.json"
    if os.environ.get("UPDATE_PITCH_FIXTURES"):
        UI_FIXTURES.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(wire, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert path.exists(), f"missing {path.name}: run UPDATE_PITCH_FIXTURES=1"
    assert json.loads(path.read_text(encoding="utf-8")) == wire
