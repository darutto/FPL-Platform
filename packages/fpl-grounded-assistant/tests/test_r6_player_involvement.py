"""R6: get_player_involvement end to end over a synthetic licensed store. No network, no provider, no LLM."""
from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from fpl_grounded_assistant.atomic_tool_cards import maybe_atomic_tool_card
from fpl_grounded_assistant.football_intelligence_runtime import run_football_intelligence_tool
from fpl_grounded_assistant.player_involvement_tool import run_player_involvement
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import FI7B_TOOL_NAMES
from football_intelligence.ingestion.licensed.player_stats import PLAYER_MATCH_STATS_COLUMNS
from football_intelligence.player_involvement import MIN_MINUTES, SMALL_SIDE_BELOW, analyse

ROGERS, PEDRO, COSTINHA, MATE = 10, 20, 99, 30

BOOTSTRAP = {
    "teams": [{"id": 1, "name": "Chelsea", "short_name": "CHE"}, {"id": 2, "name": "Brighton", "short_name": "BHA"},
              {"id": 3, "name": "Everton", "short_name": "EVE"}],
    "elements": [
        {"id": ROGERS, "web_name": "Rogers", "first_name": "Morgan", "second_name": "Rogers", "team": 1, "element_type": 3, "status": "a"},
        {"id": PEDRO, "web_name": "João Pedro", "first_name": "João Pedro", "second_name": "Junqueira de Jesus", "team": 1,
         "element_type": 4, "status": "a"},
        {"id": COSTINHA, "web_name": "Costinha", "first_name": "João Pedro", "second_name": "Gonçalves Costinha", "team": 2,
         "element_type": 4, "status": "a"},
    ],
}
FIXTURES = [{"id": fid, "event": fid, "kickoff_time": f"{day}T15:00:00Z", "team_h": 1 if fid % 2 else 3,
             "team_a": 3 if fid % 2 else 1}
            for fid, day in enumerate(["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30", "2026-12-07"], start=1)]
BUILT = "2026-12-08T05:00:00Z"


@pytest.fixture(autouse=True)
def _fresh_fixture_cache():
    """The adapter caches the FPL fixture list for 10 minutes at module level; a test must not read another's."""
    from fpl_grounded_assistant import position_changes_tool
    position_changes_tool._fixture_cache.update(at=0.0, rows=None)
    yield
    position_changes_tool._fixture_cache.update(at=0.0, rows=None)


class FakeHandle:
    def __init__(self, stats):
        self._stats = stats

    def manifest(self):
        return {"built_at": BUILT, "assumption_status": "licensed_starter"}

    def table(self, name):
        assert name == "player_match_stats"
        return self._stats


def _row(element, fixture, *, started=True, minutes=90, touches=60, passes=40, accurate=34, back=8, key=1, final=10,
         observed="2026-12-01T00:00:00Z", team="CHE"):
    base = {c: 0 for c in PLAYER_MATCH_STATS_COLUMNS}
    return {**base, "element": element, "fixture_id": fixture, "team": team, "observed_at": observed, "starter": started,
            "minutes": minutes, "rating": 6.5, "touches": touches, "passes": passes, "accurate_passes": accurate,
            "backward_passes": back, "key_passes": key, "passes_final_third": final}


def _team(fixture, *, with_pedro=True, filler=9):
    """Rogers, optionally Pedro, plus filler starters so the stored XI is complete (11)."""
    rows = [_row(ROGERS, fixture, touches=40 if with_pedro else 70)]
    if with_pedro:
        rows.append(_row(PEDRO, fixture))
    rows += [_row(1000 + 10 * fixture + i, fixture) for i in range(filler + (0 if with_pedro else 1))]
    return rows


def _stats(rows):
    return pd.DataFrame(rows, columns=list(PLAYER_MATCH_STATS_COLUMNS)).astype(object)


#: Fixtures 1-3 with Pedro starting, 4-6 without him: Rogers' touches 40 with him, 70 without.
FULL = _stats([r for fid in (1, 2, 3) for r in _team(fid)] + [r for fid in (4, 5, 6) for r in _team(fid, with_pedro=False)])


def _run(stats=FULL, **args):
    return run_player_involvement(args, dict(BOOTSTRAP), handle=FakeHandle(stats), fetch_fixtures=lambda: FIXTURES)


# ------------------------------------------------------------------ the answer

def test_a_players_matches_carry_observed_totals_latest_first():
    out = _run(player="Rogers")
    assert out["status"] == "ok" and out["player"] == {"player_id": ROGERS, "web_name": "Rogers", "team_short": "CHE"}
    assert [m["gameweek"] for m in out["matches"]] == [6, 5, 4, 3, 2, 1]
    m = out["matches"][-1]
    assert (m["touches"], m["passes"], m["accurate_passes"], m["pass_accuracy_pct"], m["backward_passes"],
            m["backward_share_pct"], m["key_passes"], m["claim_status"]) == (40, 40, 34, 85.0, 8, 20.0, 1, "observed")
    assert out["data_provenance"] == {"source": "licensed_starter", "built_at": BUILT, "stat_meaning": "provider_match_totals"}
    assert out["sample"] == {"matches_with_stats": 6, "listed": 6, "small_sample": False}


def test_per_90_pools_minutes_and_ignores_cameos():
    stats = _stats([_row(ROGERS, 1, touches=90, minutes=90), _row(ROGERS, 2, touches=45, minutes=45),
                    _row(ROGERS, 3, touches=50, minutes=MIN_MINUTES - 1, started=False)])
    avg = _run(stats, player="Rogers")["averages"]
    assert avg["matches"] == 2 and avg["minutes"] == 135 and avg["touches_per90"] == 90.0   # 135 touches / 135 min * 90


def test_a_correction_replaces_the_first_read_of_the_same_match():
    stats = _stats([_row(ROGERS, 1, touches=40, observed="2026-12-01T00:00:00Z"),
                    _row(ROGERS, 1, touches=44, observed="2026-12-02T00:00:00Z")])
    out = _run(stats, player="Rogers")
    assert [m["touches"] for m in out["matches"]] == [44]


def test_zero_passes_give_no_percentage_not_a_division_error():
    out = _run(_stats([_row(ROGERS, 1, passes=0, accurate=0, back=0)]), player="Rogers")
    assert out["matches"][0]["pass_accuracy_pct"] is None and out["matches"][0]["backward_share_pct"] is None


def test_few_matches_say_small_sample():
    out = _run(_stats([_row(ROGERS, 1), _row(ROGERS, 2)]), player="Rogers")
    assert out["sample"]["small_sample"] is True


def test_no_statistics_for_the_player_is_missing_context_not_an_empty_success():
    out = _run(_stats([_row(PEDRO, 1)]), player="Rogers")
    assert out["status"] == "missing_context" and out["reason_codes"] == ["no_player_stats"]
    empty = _run(_stats([]), player="Rogers")
    assert empty["status"] == "missing_context"


def test_a_store_that_is_not_synced_or_fixtures_unreachable_degrade():
    class Broken:
        def manifest(self):
            raise FileNotFoundError("no pointer")

    out = run_player_involvement({"player": "Rogers"}, dict(BOOTSTRAP), handle=Broken(), fetch_fixtures=lambda: FIXTURES)
    assert out["status"] == "missing_context" and out["reason_codes"] == ["licensed_store_unavailable"]

    def boom():
        raise OSError("FPL unreachable")

    out = run_player_involvement({"player": "Rogers"}, dict(BOOTSTRAP), handle=FakeHandle(FULL), fetch_fixtures=boom)
    assert out["reason_codes"] == ["fixture_list_unavailable"]


def test_matches_is_clamped():
    assert len(_run(player="Rogers", matches=2)["matches"]) == 2
    assert len(_run(player="Rogers", matches=99)["matches"]) == 6
    assert len(_run(player="Rogers", matches="x")["matches"]) == 6


# ------------------------------------------------------- with / without a teammate

def test_the_comparison_splits_the_matches_by_whether_the_teammate_started():
    focus = _run(player="Rogers", absent_player="Joao Pedro")["absence_focus"]
    assert focus["teammate"] == {"player_id": PEDRO, "web_name": "João Pedro", "team_short": "CHE"}
    assert focus["without_him"]["matches"] == 3 and focus["with_him_starting"]["matches"] == 3
    assert (focus["without_him"]["touches_per90"], focus["with_him_starting"]["touches_per90"]) == (70.0, 40.0)
    assert focus["touches_without_vs_with"] == "more" and focus["claim_status"] == "associated"
    assert focus["small_sample"] is False and focus["teammate_in_store"] is True


def test_similar_touches_are_called_similar():
    stats = _stats([r for fid in (1, 2, 3) for r in _team(fid)]
                   + [{**r, "touches": 42} if r["element"] == ROGERS else r for fid in (4, 5, 6) for r in _team(fid, with_pedro=False)])
    assert _run(stats, player="Rogers", absent_player="Joao Pedro")["absence_focus"]["touches_without_vs_with"] == "similar"


def test_a_substitute_appearance_is_neither_side():
    rows = [r for fid in (1, 2, 3) for r in _team(fid)]
    rows += [{**r, "starter": False, "minutes": 20} if r["element"] == PEDRO else r for r in _team(4, filler=10)]
    focus = _run(_stats(rows), player="Rogers", absent_player="Joao Pedro")["absence_focus"]
    assert focus["matches_mixed"] == 1 and focus["without_him"]["matches"] == 0 and focus["touches_without_vs_with"] is None


def test_an_incomplete_stored_xi_does_not_read_as_an_absence():
    # fixture 4: only 10 starters stored (an unmapped starter was dropped), so Pedro's missing row proves nothing
    rows = [r for fid in (1, 2, 3) for r in _team(fid)] + _team(4, with_pedro=False, filler=8)
    focus = _run(_stats(rows), player="Rogers", absent_player="Joao Pedro")["absence_focus"]
    assert focus["matches_uncertain"] == 1 and focus["without_him"]["matches"] == 0


def test_small_sides_are_said():
    rows = [r for fid in (1, 2, 3, 4) for r in _team(fid)] + _team(5, with_pedro=False)
    focus = _run(_stats(rows), player="Rogers", absent_player="Joao Pedro")["absence_focus"]
    assert focus["without_him"]["matches"] == 1 < SMALL_SIDE_BELOW and focus["small_sample"] is True


def test_a_teammate_never_seen_in_the_store_is_flagged():
    rows = [r for fid in (1, 2, 3) for r in _team(fid, with_pedro=False)]
    focus = _run(_stats(rows), player="Rogers", absent_player="Joao Pedro")["absence_focus"]
    assert focus["teammate_in_store"] is False


def test_joao_pedro_is_the_chelsea_player_never_costinha():
    assert _run(player="Rogers", absent_player="João Pedro")["absence_focus"]["teammate"]["player_id"] == PEDRO
    assert _run(player="Rogers", absent_player="Costinha")["status"] == "not_a_teammate"
    alone = _run(player="João Pedro")
    assert alone["status"] == "ambiguous" and {c["team_short"] for c in alone["candidates"]} == {"CHE", "BHA"}


def test_analyse_joins_on_the_club_of_the_row_and_skips_unknown_fixtures():
    from football_intelligence.position_changes import FixtureMeta
    rows = [_row(ROGERS, 1), _row(ROGERS, 999)]
    out = analyse(element=ROGERS, stats=_stats(rows), fixtures={1: FixtureMeta(1, "2026-11-02T15:00:00Z", "CHE", "EVE")}, names={})
    assert [m["gameweek"] for m in out["matches"]] == [1] and out["matches"][0]["opponent"] == "EVE" and out["matches"][0]["is_home"]


# ----------------------------------------------------------- wiring, text and card

def test_the_tool_is_offered_with_the_fi_tools_and_dispatched(monkeypatch, tmp_path):
    assert "get_player_involvement" in FI7B_TOOL_NAMES
    monkeypatch.setenv("FPL_FOOTBALL_LICENSED_CACHE_ROOT", str(tmp_path))   # an empty cache: nothing synced
    out = run_football_intelligence_tool("get_player_involvement", {"player": "Rogers"}, dict(BOOTSTRAP))
    assert out["status"] == "missing_context" and out["reason_codes"] == ["licensed_store_unavailable"]


FORBIDDEN = re.compile(r"por la lesi|porque falt|because of|due to the|rendir[aá] m|will score|debilidad|weakness", re.I)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_text_states_totals_and_the_coincidence_and_never_a_cause(locale):
    text = render("get_player_involvement", _run(player="Rogers", absent_player="Joao Pedro"), locale=locale)
    assert "70" in text and "40" in text and "João Pedro" in text
    assert ("más toques" if locale == "es" else "more touches") in text
    assert ("no se afirma nada más" if locale == "es" else "nothing more is claimed") in text
    assert not FORBIDDEN.search(text)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_text_for_a_missing_store_is_plain(locale):
    text = render("get_player_involvement", {"status": "missing_context", "reason_codes": ["licensed_store_unavailable"], "matches": []},
                  locale=locale)
    assert text and "{" not in text


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_card_has_the_columns_the_ask_names_and_no_ids(locale):
    card = maybe_atomic_tool_card("get_player_involvement", _run(player="Rogers", absent_player="Joao Pedro"), None, locale)
    assert card is not None and len(card.rows) == 6 and len(card.columns) == 6
    headers = " ".join(c.header for c in card.columns).lower()
    assert ("toques" in headers and "pases" in headers and "clave" in headers and "atrás" in headers) if locale == "es" else \
        ("touches" in headers and "passes" in headers and "key" in headers and "backward" in headers)
    assert card.hero.value == "55" and any("João Pedro" in p.label for p in card.pills)
    blob = json.dumps([card.title, card.subtitle, card.rows, [p.label for p in card.pills], card.footer], ensure_ascii=False)
    assert not FORBIDDEN.search(blob) and "fixture_id" not in blob and "element" not in blob
    gw1 = next(r for r in card.rows if r[0] in ("GW1", "J1"))
    assert gw1[2:] == ("40", "40 (85%)", "1", "8 (20%)")


def test_the_card_is_none_unless_the_answer_is_ok_with_matches():
    for output in ({"status": "missing_context", "matches": []}, {"status": "ambiguous"}, {"status": "ok", "matches": []}):
        assert maybe_atomic_tool_card("get_player_involvement", output, None, "es") is None


def test_the_tool_description_forbids_causes_and_zones():
    from fpl_grounded_assistant.tool_schema_registry import GET_PLAYER_INVOLVEMENT_SCHEMA as schema
    d = schema.description
    assert "NEVER give a cause" in d and "no zones, no heat maps" in d and "tuvo mas/menos toques" in d
