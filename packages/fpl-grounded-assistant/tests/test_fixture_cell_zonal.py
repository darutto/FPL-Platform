"""The team zonal link under a /fixtures cell answer (fixture_cell_zonal.py).

Synthetic data only: invented clubs and shots, no value from any real store. No network, no provider.
"""
from __future__ import annotations

import pandas as pd
import pytest

from fpl_grounded_assistant import fixture_cell_zonal as mod
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY

_TEAMS = [
    {"id": 1, "name": "Northbury", "short_name": "NOR"},
    {"id": 2, "name": "Eastport", "short_name": "EAS"},
    {"id": 3, "name": "Westvale", "short_name": "WES"},
    {"id": 4, "name": "Southmere", "short_name": "SOU"},
]


def _bs(locale: str = "es") -> dict:
    return {"teams": _TEAMS, "elements": [], "events": [], BOOTSTRAP_LOCALE_KEY: locale}


def _shot(conceding: str, shooting: str, x: float, y: float, xg: float, match_id: int) -> dict:
    return {"season": "2026-2027", "match_id": match_id, "date": "2026-10-01T15:00:00",
            "shooting_team": shooting, "conceding_team": conceding, "player": f"{shooting} Nine",
            "is_home_shot": True, "minute": 10, "x": x, "y": y, "xg": xg, "situation": "Open Play",
            "shot_type": "Right Foot", "result": "Saved Shot"}


def _store() -> pd.DataFrame:
    """Every club concedes the same central chance per game; Eastport and Southmere also leak on the right of the
    box (a clear weak zone), Westvale and Northbury do not. Southmere never shoots."""
    rows = []
    shooters = {"Northbury": "Westvale", "Eastport": "Northbury", "Westvale": "Northbury", "Southmere": "Northbury"}
    for match_id in (1, 2):
        for conceding, shooting in shooters.items():
            mid = match_id * 10 + len(rows)
            rows.append(_shot(conceding, shooting, 0.90, 0.50, 0.30, mid))
            if conceding in ("Eastport", "Southmere"):
                rows.append(_shot(conceding, shooting, 0.90, 0.20, 0.40, mid))
    return pd.DataFrame(rows)


def _cell(*rivals: str, gw: int = 11) -> dict:
    return {"gameweek": gw, "fixtures": [{"opponent_short": r, "is_home": False, "band": 2} for r in rivals]}


def _links(series: list, team_id: int = 1, locale: str = "es", store=None):
    team = next(t for t in _TEAMS if t["id"] == team_id)
    return mod.match_zonal_links({"series": series}, team, _bs(locale), store=_store() if store is None else store)


def test_one_cell_against_a_rival_with_a_weak_zone_gives_the_link_es_en():
    assert _links([_cell("EAS")]) == [{
        "label": "Quién del NOR explota al EAS",
        "send_text": "¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?"}]
    assert _links([_cell("EAS")], locale="en") == [{
        "label": "Who at NOR exploits EAS",
        "send_text": "Which Northbury players can exploit Eastport's weak zones?"}]


def test_rival_without_a_weak_zone_gives_no_link():
    assert _links([_cell("WES")]) == []


def test_rival_missing_from_the_store_gives_no_link():
    store = _store()
    assert _links([_cell("EAS")], store=store[store["conceding_team"] != "Eastport"]) == []


def test_own_club_without_shots_gives_no_link():
    assert _links([_cell("EAS")], team_id=4) == []


@pytest.mark.parametrize("series", [
    [],                                     # nothing
    [_cell()],                              # blank gameweek: no rival
    [_cell("EAS", gw=11), _cell("EAS", gw=12)],  # two gameweeks: not a cell
])
def test_not_one_match_cell_gives_no_link(series):
    assert _links(series) == []


def test_double_gameweek_gives_one_link_per_rival_worth_it():
    assert [x["label"] for x in _links([_cell("EAS", "SOU")])] == [
        "Quién del NOR explota al EAS", "Quién del NOR explota al SOU"]
    assert [x["label"] for x in _links([_cell("WES", "EAS")])] == ["Quién del NOR explota al EAS"]
    assert mod.MAX_LINKS == 2


def test_no_store_or_a_failure_gives_no_link(monkeypatch):
    assert _links([_cell("EAS")], store=pd.DataFrame()) == []
    monkeypatch.setattr(mod, "_rival_has_weak_zone", lambda *a: 1 / 0)
    assert _links([_cell("EAS")]) == []


def test_the_link_is_the_existing_team_zonal_question():
    from fpl_grounded_assistant.zonal_weakness_tool import infer_subject_teams

    for locale in ("es", "en"):
        q = _links([_cell("EAS")], locale=locale)[0]["send_text"]
        assert infer_subject_teams(q, "Eastport", _bs(locale)) == ["NOR"]


# ---------------------------------------------------------------------------
# Wiring: hidden from the model, carried on the outlook meta and the wire
# ---------------------------------------------------------------------------

_LINK = {"label": "Quién del NOR explota al EAS", "send_text": "q"}


def test_links_are_hidden_from_the_model():
    from fpl_grounded_assistant.orchestrator import _truncate_tool_output

    raw = {"status": "ok", "team_short": "NOR", "series": [_cell("EAS")], "zonal_links": [_LINK]}
    assert "zonal_links" not in _truncate_tool_output(raw, max_items=10, tool_name="get_fixture_outlook")


def test_meta_carries_well_formed_links_only():
    from fpl_grounded_assistant.final_response import ZonalLink, _extract_fixture_outlook_meta
    from fpl_grounded_assistant.harness_adapter import _to_dict

    ro = {"axis": "defence", "horizon": 1, "team_short": "NOR", "series": [_cell("EAS")], "runs": [],
          "zonal_links": [_LINK, {"label": "", "send_text": "q"}, "junk"]}
    meta = _extract_fixture_outlook_meta(ro)
    assert meta.zonal_links == (ZonalLink("Quién del NOR explota al EAS", "q"),)
    assert _to_dict(meta)["zonal_links"] == [_LINK]
    assert _extract_fixture_outlook_meta({**ro, "zonal_links": None}).zonal_links == ()


def test_handler_attaches_links_only_to_a_one_gameweek_answer(monkeypatch):
    from fpl_grounded_assistant import fixture_outlook_tool as tool

    calls = []
    monkeypatch.setattr(tool, "match_zonal_links", lambda outlook, team, bs: calls.append(team["short_name"]) or [_LINK])
    monkeypatch.setattr(tool, "_resolve_team", lambda q, bs: _TEAMS[0])
    monkeypatch.setattr(tool, "describe_short_horizon", lambda *a: "match")

    def outlook(n):
        return lambda *a, **k: {"team_short": "NOR", "series": [_cell("EAS", gw=11 + i) for i in range(n)], "runs": []}

    bs = {**_bs(), "team_fixtures": {"1": []}}
    monkeypatch.setattr(tool, "get_team_outlook", outlook(1))
    assert tool._get_fixture_outlook_handler({"axis": "attack", "team_query": "NOR", "target_gw": 11}, bs)[
        "zonal_links"] == [_LINK]
    monkeypatch.setattr(tool, "get_team_outlook", outlook(5))
    assert "zonal_links" not in tool._get_fixture_outlook_handler({"axis": "attack", "team_query": "NOR"}, bs)
    assert calls == ["NOR"]
